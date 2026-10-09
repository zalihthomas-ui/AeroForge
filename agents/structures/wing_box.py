"""Thin-walled wing-box structure: geometry, materials, closed-form beam analysis, sizing.

The primary structure of a real wing is a box: two spars (front and rear
webs) and the upper/lower skin panels between them acting as spar caps. This
replaces the v0.8-v0.13 solid-section FEA (a solid aluminium wing at 1 g
cruise, which gave meaningless safety factors of ~350-1600) with a
thin-walled box sized to ultimate load.

Idealisation (stated, so the results can be judged):
* Rectangular box between the front spar at `front_spar_xc` (default 20 %
  chord) and rear spar at `rear_spar_xc` (60 %), straight and unswept.
* Box height = local airfoil thickness at the thinner of the two spar
  stations (NACA 4-digit thickness law) -- conservative, since the true
  cover is curved and deeper in between.
* Covers (thickness t_cap, width w) carry bending; webs (t_web, height h)
  carry shear. Thin-wall section: I = 2 w t_cap (h/2)^2 + 2 t_web h^3 / 12.
* Bending stress sigma = M (h/2) / I; web shear tau = V / (2 h t_web);
  torsion is not carried (lift assumed applied at the shear centre).
* Buckling, both as simply supported flat plates (Bruhn ch. C5; NACA TN 3781):
  compression cover between the webs,  sigma_cr = k pi^2 E / (12(1-nu^2)) (t/w)^2, k = 4;
  web in shear,                          tau_cr  = ks pi^2 E / (12(1-nu^2)) (t/h)^2, ks = 5.35
  (long-plate values; ribs are assumed at a pitch >= the cover width).
  No post-buckling strength is credited: the design requirement is
  "no buckling below ultimate load" -- conservative for metal skins, which
  real aircraft allow to buckle elastically above limit load.
* Margins of safety MS = allowable / applied - 1, required >= 0:
  ultimate load vs Ftu / Fsu, limit load vs Fty, ultimate load vs buckling.
* Tip deflection by double integration of M / (E I) (Euler-Bernoulli; shear
  deformation neglected).

Thickness is constant within each spanwise bay (between ribs) and is sized
per bay -- a stepped, manufacturable "fully stressed" design with a minimum
gauge, not a continuous taper.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import brentq


class WingBoxError(ValueError):
    """Raised for invalid wing-box inputs or an unsizeable design."""


@dataclass(frozen=True)
class Material:
    """Isotropic (or quasi-isotropic) sheet material with design allowables [MPa, kg/m^3]."""

    name: str
    youngs_modulus_mpa: float
    poissons_ratio: float
    ftu_mpa: float  # ultimate tensile strength (design allowable)
    fty_mpa: float  # tensile yield strength
    fsu_mpa: float  # ultimate shear strength
    density_kgm3: float
    note: str = ""


# Typical sheet allowables (MMPDS-style A/B-basis order of magnitude; verify
# against your own source before using for anything that flies).
MATERIALS: dict[str, Material] = {
    "al6061-t6": Material("Al 6061-T6", 68900.0, 0.33, 290.0, 241.0, 186.0, 2700.0),
    "al7075-t6": Material("Al 7075-T6", 71000.0, 0.33, 524.0, 462.0, 317.0, 2810.0),
    "cfrp-qi": Material(
        "CFRP quasi-isotropic (T300/epoxy)",
        50000.0,
        0.30,
        300.0,
        300.0,
        100.0,
        1600.0,
        note=(
            "Smeared quasi-isotropic laminate treated as an isotropic plate: no ply-level "
            "failure criteria, no stacking-sequence (D-matrix) effect on buckling, strength "
            "knocked down to ~300 MPa for impact damage/environment. A first-pass number only."
        ),
    ),
}

PLATE_K_COMPRESSION = 4.0  # SS long plate, uniaxial compression
PLATE_KS_SHEAR = 5.35  # SS long plate, pure shear


def naca4_thickness_ratio(naca: str, x_c: float) -> float:
    """Full thickness / chord of a NACA 4-digit section at x/c (closed trailing edge form)."""
    t = int(naca[-2:]) / 100.0
    x = x_c
    return 2.0 * 5.0 * t * (0.2969 * math.sqrt(x) - 0.1260 * x - 0.3516 * x**2 + 0.2843 * x**3 - 0.1036 * x**4)


@dataclass
class WingBoxGeometry:
    """Spanwise box dimensions at the analysis stations (one semispan, mm)."""

    y_mm: np.ndarray
    chord_mm: np.ndarray
    width_mm: np.ndarray  # spar-to-spar
    height_mm: np.ndarray  # cover-to-cover
    front_spar_xc: float
    rear_spar_xc: float
    naca: str

    @classmethod
    def from_planform(
        cls,
        semispan_mm: float,
        root_chord_mm: float,
        tip_chord_mm: float,
        naca: str,
        n_stations: int = 81,
        front_spar_xc: float = 0.20,
        rear_spar_xc: float = 0.60,
    ) -> WingBoxGeometry:
        if not 0.0 < front_spar_xc < rear_spar_xc < 1.0:
            raise WingBoxError("need 0 < front_spar_xc < rear_spar_xc < 1.")
        y = np.linspace(0.0, semispan_mm, n_stations)
        c = root_chord_mm + (tip_chord_mm - root_chord_mm) * y / semispan_mm
        tc = min(naca4_thickness_ratio(naca, front_spar_xc), naca4_thickness_ratio(naca, rear_spar_xc))
        return cls(
            y_mm=y,
            chord_mm=c,
            width_mm=(rear_spar_xc - front_spar_xc) * c,
            height_mm=tc * c,
            front_spar_xc=front_spar_xc,
            rear_spar_xc=rear_spar_xc,
            naca=naca,
        )

    @property
    def semispan_mm(self) -> float:
        return float(self.y_mm[-1])


@dataclass
class BoxThickness:
    """Stepped thickness: one (t_cap, t_web) per spanwise bay, bays equally spaced."""

    bay_edges_mm: np.ndarray  # len n_bays + 1, root -> tip
    t_cap_mm: np.ndarray  # len n_bays
    t_web_mm: np.ndarray

    def at(self, y_mm: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        idx = np.clip(np.searchsorted(self.bay_edges_mm, y_mm, side="right") - 1, 0, len(self.t_cap_mm) - 1)
        return self.t_cap_mm[idx], self.t_web_mm[idx]

    @classmethod
    def uniform(cls, semispan_mm: float, n_bays: int, t_cap_mm: float, t_web_mm: float) -> BoxThickness:
        return cls(
            bay_edges_mm=np.linspace(0.0, semispan_mm, n_bays + 1),
            t_cap_mm=np.full(n_bays, float(t_cap_mm)),
            t_web_mm=np.full(n_bays, float(t_web_mm)),
        )


@dataclass
class WingBoxAnalysis:
    """Closed-form beam results along the semispan at one load factor."""

    load_factor: float
    y_mm: np.ndarray
    inertia_mm4: np.ndarray
    bending_stress_mpa: np.ndarray  # cover membrane stress (|M| c / I)
    web_shear_mpa: np.ndarray
    cover_buckling_mpa: np.ndarray  # sigma_cr
    web_buckling_mpa: np.ndarray  # tau_cr
    deflection_mm: np.ndarray  # vertical deflection w(y)
    tip_deflection_mm: float


@dataclass
class WingBoxMargins:
    """Minimum margins of safety over the span (MS >= 0 passes)."""

    ms_cover_ultimate: float  # ultimate load vs Ftu
    ms_cover_yield: float  # limit load vs Fty
    ms_web_ultimate: float  # ultimate load vs Fsu
    ms_cover_buckling: float  # ultimate load vs sigma_cr
    ms_web_buckling: float  # ultimate load vs tau_cr
    critical: str = ""
    values: dict[str, float] = field(default_factory=dict)

    @property
    def minimum(self) -> float:
        return min(self.values.values())

    @property
    def passes(self) -> bool:
        return self.minimum >= -1e-9


def section_inertia_mm4(width_mm, height_mm, t_cap_mm, t_web_mm):
    """Thin-walled rectangular box second moment of area about the horizontal axis."""
    return 2.0 * width_mm * t_cap_mm * (height_mm / 2.0) ** 2 + 2.0 * t_web_mm * height_mm**3 / 12.0


def _plate_coefficient(material: Material) -> float:
    return math.pi**2 * material.youngs_modulus_mpa / (12.0 * (1.0 - material.poissons_ratio**2))


def analyze_box(
    geometry: WingBoxGeometry,
    thickness: BoxThickness,
    material: Material,
    shear_n: np.ndarray,
    bending_nm: np.ndarray,
    load_factor: float,
) -> WingBoxAnalysis:
    """Closed-form stresses, buckling allowables and deflection (shear/bending at the stations)."""
    y = geometry.y_mm
    t_cap, t_web = thickness.at(y)
    w, h = geometry.width_mm, geometry.height_mm
    inertia = section_inertia_mm4(w, h, t_cap, t_web)
    m_nmm = np.asarray(bending_nm) * 1000.0
    sigma = np.abs(m_nmm) * (h / 2.0) / inertia
    tau = np.abs(np.asarray(shear_n)) / (2.0 * h * t_web)
    kp = _plate_coefficient(material)
    sigma_cr = PLATE_K_COMPRESSION * kp * (t_cap / w) ** 2
    tau_cr = PLATE_KS_SHEAR * kp * (t_web / h) ** 2
    curvature = m_nmm / (material.youngs_modulus_mpa * inertia)  # 1/mm
    slope = _cumtrapz(curvature, y)
    deflection = _cumtrapz(slope, y)
    return WingBoxAnalysis(
        load_factor=load_factor,
        y_mm=y,
        inertia_mm4=inertia,
        bending_stress_mpa=sigma,
        web_shear_mpa=tau,
        cover_buckling_mpa=sigma_cr,
        web_buckling_mpa=tau_cr,
        deflection_mm=deflection,
        tip_deflection_mm=float(deflection[-1]),
    )


def margins(limit: WingBoxAnalysis, ultimate: WingBoxAnalysis, material: Material) -> WingBoxMargins:
    """Minimum margins of safety over the span."""

    def ms(allow, applied):
        applied = np.maximum(applied, 1e-12)
        return float(np.min(allow / applied - 1.0))

    vals = {
        "cover strength (ultimate vs Ftu)": ms(material.ftu_mpa, ultimate.bending_stress_mpa),
        "cover yield (limit vs Fty)": ms(material.fty_mpa, limit.bending_stress_mpa),
        "web shear strength (ultimate vs Fsu)": ms(material.fsu_mpa, ultimate.web_shear_mpa),
        "cover buckling (ultimate)": ms(ultimate.cover_buckling_mpa, ultimate.bending_stress_mpa),
        "web shear buckling (ultimate)": ms(ultimate.web_buckling_mpa, ultimate.web_shear_mpa),
    }
    critical = min(vals, key=vals.get)
    keys = list(vals.values())
    return WingBoxMargins(*keys, critical=critical, values=vals)


def box_mass_kg(geometry: WingBoxGeometry, thickness: BoxThickness, material: Material) -> float:
    """Mass of the full (two-semispan) box: covers + webs, no ribs/fasteners."""
    t_cap, t_web = thickness.at(geometry.y_mm)
    area_mm2 = 2.0 * geometry.width_mm * t_cap + 2.0 * geometry.height_mm * t_web
    volume_mm3 = float(np.trapezoid(area_mm2, geometry.y_mm))
    return 2.0 * volume_mm3 * 1e-9 * material.density_kgm3


@dataclass
class WingBoxSizing:
    thickness: BoxThickness
    material: Material
    mass_kg: float
    limit: WingBoxAnalysis
    ultimate: WingBoxAnalysis
    margins: WingBoxMargins
    governing_per_bay: list[str]


def size_box(
    geometry: WingBoxGeometry,
    material: Material,
    shear_limit_n: np.ndarray,
    bending_limit_nm: np.ndarray,
    n_limit: float,
    ultimate_factor: float = 1.5,
    n_bays: int = 6,
    min_gauge_mm: float = 0.3,
    max_gauge_mm: float = 20.0,
    gauge_step_mm: float = 0.05,
) -> WingBoxSizing:
    """Minimum-mass stepped box: per bay, the thinnest t_web then t_cap with all margins >= 0.

    `shear_limit_n` / `bending_limit_nm` are the LIMIT-load distributions at
    the geometry stations; ultimate = ultimate_factor x limit. Each bay's
    thickness is found by brentq on the bay's minimum margin (monotone in
    thickness) and rounded UP to `gauge_step_mm` (a sheet-gauge step), never
    below `min_gauge_mm`.
    """
    y = geometry.y_mm
    edges = np.linspace(0.0, geometry.semispan_mm, n_bays + 1)
    v_lim, m_lim = np.asarray(shear_limit_n), np.asarray(bending_limit_nm)
    v_ult, m_ult = ultimate_factor * v_lim, ultimate_factor * m_lim
    kp = _plate_coefficient(material)
    t_caps, t_webs, governing = [], [], []

    for b in range(n_bays):
        sel = (y >= edges[b] - 1e-9) & (y <= edges[b + 1] + 1e-9)
        w, h = geometry.width_mm[sel], geometry.height_mm[sel]

        def web_margin(t, sel=sel, h=h):
            tau = np.abs(v_ult[sel]) / (2.0 * h * t)
            tau = np.maximum(tau, 1e-12)
            return min(np.min(material.fsu_mpa / tau - 1.0),
                       np.min(PLATE_KS_SHEAR * kp * (t / h) ** 2 / tau - 1.0))

        t_web = _solve_gauge(web_margin, min_gauge_mm, max_gauge_mm, gauge_step_mm)

        def cap_margins(t, sel=sel, w=w, h=h, t_web=t_web):
            inertia = section_inertia_mm4(w, h, t, t_web)
            s_u = np.maximum(np.abs(m_ult[sel]) * 1000.0 * (h / 2.0) / inertia, 1e-12)
            s_l = np.maximum(np.abs(m_lim[sel]) * 1000.0 * (h / 2.0) / inertia, 1e-12)
            return {
                "cover strength": np.min(material.ftu_mpa / s_u - 1.0),
                "cover yield": np.min(material.fty_mpa / s_l - 1.0),
                "cover buckling": np.min(PLATE_K_COMPRESSION * kp * (t / w) ** 2 / s_u - 1.0),
            }

        t_cap = _solve_gauge(lambda t: min(cap_margins(t).values()), min_gauge_mm, max_gauge_mm, gauge_step_mm)
        cm = cap_margins(t_cap)
        if t_cap <= min_gauge_mm + 1e-9 and min(cm.values()) > 0.05:
            governing.append("minimum gauge")
        else:
            governing.append(min(cm, key=cm.get))
        t_caps.append(t_cap)
        t_webs.append(t_web)

    thick = BoxThickness(edges, np.array(t_caps), np.array(t_webs))
    lim = analyze_box(geometry, thick, material, v_lim, m_lim, n_limit)
    ult = analyze_box(geometry, thick, material, v_ult, m_ult, n_limit * ultimate_factor)
    return WingBoxSizing(
        thickness=thick,
        material=material,
        mass_kg=box_mass_kg(geometry, thick, material),
        limit=lim,
        ultimate=ult,
        margins=margins(lim, ult, material),
        governing_per_bay=governing,
    )


def _solve_gauge(margin_fn, t_min: float, t_max: float, step: float) -> float:
    if margin_fn(t_min) >= 0.0:
        return t_min
    if margin_fn(t_max) < 0.0:
        raise WingBoxError(f"No thickness <= {t_max} mm gives non-negative margins.")
    t = brentq(margin_fn, t_min, t_max, xtol=1e-6)
    return float(min(t_max, math.ceil(t / step - 1e-9) * step))


def _cumtrapz(f: np.ndarray, x: np.ndarray) -> np.ndarray:
    out = np.zeros_like(f, dtype=float)
    out[1:] = np.cumsum(0.5 * (f[1:] + f[:-1]) * np.diff(x))
    return out


def beam_natural_frequencies(
    geometry: WingBoxGeometry,
    thickness: BoxThickness,
    material: Material,
    n_modes: int = 3,
    point_masses: list[tuple[float, float]] | None = None,
    n_elements: int = 80,
) -> np.ndarray:
    """Cantilever bending frequencies [Hz] of the box as an Euler-Bernoulli beam.

    Hermite-cubic beam finite elements with the box's own EI(y) and mass per
    length (covers + webs), plus optional point masses [(y_mm, kg)] such as
    ribs. Used as an independent check on the shell model's bending modes.
    """
    y = np.linspace(0.0, geometry.semispan_mm, n_elements + 1) / 1000.0  # m
    ymm = y * 1000.0
    t_cap, t_web = thickness.at(0.5 * (ymm[1:] + ymm[:-1]))
    ym = 0.5 * (ymm[1:] + ymm[:-1])
    w = np.interp(ym, geometry.y_mm, geometry.width_mm) / 1000.0
    h = np.interp(ym, geometry.y_mm, geometry.height_mm) / 1000.0
    tc, tw = t_cap / 1000.0, t_web / 1000.0
    ei = material.youngs_modulus_mpa * 1e6 * section_inertia_mm4(w, h, tc, tw)
    mu = material.density_kgm3 * (2.0 * w * tc + 2.0 * h * tw)
    ndof = 2 * (n_elements + 1)
    k_glob = np.zeros((ndof, ndof))
    m_glob = np.zeros((ndof, ndof))
    for e in range(n_elements):
        le = y[e + 1] - y[e]
        ke = ei[e] / le**3 * np.array([[12, 6 * le, -12, 6 * le], [6 * le, 4 * le**2, -6 * le, 2 * le**2],
                                       [-12, -6 * le, 12, -6 * le], [6 * le, 2 * le**2, -6 * le, 4 * le**2]])
        me = mu[e] * le / 420.0 * np.array([[156, 22 * le, 54, -13 * le], [22 * le, 4 * le**2, 13 * le, -3 * le**2],
                                            [54, 13 * le, 156, -22 * le], [-13 * le, -3 * le**2, -22 * le, 4 * le**2]])
        idx = slice(2 * e, 2 * e + 4)
        k_glob[idx, idx] += ke
        m_glob[idx, idx] += me
    for y_pm, mass in point_masses or []:
        node = int(np.argmin(np.abs(ymm - y_pm)))
        m_glob[2 * node, 2 * node] += mass
    free = slice(2, ndof)  # clamp root deflection and slope
    from scipy.linalg import eigh

    vals = eigh(k_glob[free, free], m_glob[free, free], eigvals_only=True)
    return np.sqrt(np.maximum(vals[:n_modes], 0.0)) / (2.0 * np.pi)
