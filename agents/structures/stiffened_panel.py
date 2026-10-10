"""Stringer-stiffened box covers: closed-form panel design (v0.16).

The v0.14 box covers are unstiffened plates between the spars, so cover
buckling (k = 4 over the full spar-to-spar width) sized every bay. Real wing
covers carry bonded or riveted stringers: the skin then buckles over the much
narrower stringer pitch and the stringers + skin work as columns between ribs.

Per bay, for a cover of width w carrying the ultimate compressive stress:

* skin between stringers, simply supported long plate,
  sigma_cr = 4 pi^2 E / (12 (1 - nu^2)) (t / b)^2,  b = w / (n + 1);
* stringer: bent-sheet equal angle (leg a, thickness t_s), bonded to the skin
  by its attached leg (the bonding land). Crippling (Gerard, angle, g = 2):
  sigma_cc / sigma_cy = 0.56 [ (g t_s^2 / A) sqrt(E / sigma_cy) ]^0.85 <= 1;
* stringer + skin strip b as a column between ribs (pin ended, c = 1:
  conservative -- ribs give some fixity), Euler with the Johnson parabola when
  sigma_e > sigma_cc / 2:  sigma_col = sigma_cc (1 - sigma_cc / (4 sigma_e));
* cover strength (ultimate vs Ftu) and yield (limit vs Fty);
* the bonded attached leg (bonding land) must pass the whole stringer load
  into the skin at a run-out: Volkersen peak shear <= the adhesive allowable.

The cover stress uses the box section with the stringer area added to the
cover (I = 2 (w t + n A_s) (h/2)^2 + webs), so stiffening also lowers stress.
No post-buckling credit, as in `wing_box`: no buckling below ultimate.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from agents.structures.wing_box import (
    PLATE_K_COMPRESSION,
    BoxThickness,
    Material,
    WingBoxGeometry,
    _plate_coefficient,
)

GERARD_G_ANGLE = 2.0
STRINGER_LEGS_MM = (6.0, 8.0, 10.0, 12.0)  # attached leg = bonding land (>= 6 mm to bond and inspect)
STRINGER_GAUGES_MM = (0.4, 0.5, 0.6, 0.8, 1.0)
MAX_STRINGERS = 4
MOUSEHOLE_DEPTH_FRACTION = 0.35  # stringer + clearance may use at most 35 % of the box depth at a rib (both covers
BOND_PLATEAU_OVERLAP_MM = 40.0  # long enough that the Volkersen peak no longer falls with overlap
MOUSEHOLE_CLEARANCE_MM = 1.0     # notched -> >= 30 % of the rib web depth stays continuous)


@dataclass(frozen=True)
class AngleStringer:
    leg_mm: float
    t_mm: float

    @property
    def area_mm2(self) -> float:
        return (2 * self.leg_mm - self.t_mm) * self.t_mm

    def centroid_above_skin_mm(self) -> float:
        a, t = self.leg_mm, self.t_mm
        a1, z1 = a * t, t / 2
        a2, z2 = (a - t) * t, t + (a - t) / 2
        return (a1 * z1 + a2 * z2) / (a1 + a2)

    def own_inertia_mm4(self) -> float:
        """Second moment of the angle about its own centroid, bending normal to the skin."""
        a, t = self.leg_mm, self.t_mm
        zc = self.centroid_above_skin_mm()
        i1 = a * t**3 / 12 + a * t * (t / 2 - zc) ** 2
        h2 = a - t
        i2 = t * h2**3 / 12 + t * h2 * (t + h2 / 2 - zc) ** 2
        return i1 + i2


def crippling_mpa(s: AngleStringer, m: Material) -> float:
    """Gerard crippling stress of a formed angle, capped at the compressive yield (~Fty)."""
    ratio = 0.56 * (GERARD_G_ANGLE * s.t_mm**2 / s.area_mm2 * math.sqrt(m.youngs_modulus_mpa / m.fty_mpa)) ** 0.85
    return min(1.0, ratio) * m.fty_mpa


def column_section(s: AngleStringer, skin_t: float, skin_b: float) -> tuple[float, float]:
    """(area, radius of gyration) of one stringer + its skin strip b (skin mid-plane at z = -t/2)."""
    a_k, z_k = skin_b * skin_t, -skin_t / 2
    a_s, z_s = s.area_mm2, s.centroid_above_skin_mm()
    a = a_k + a_s
    zc = (a_k * z_k + a_s * z_s) / a
    i = skin_b * skin_t**3 / 12 + a_k * (z_k - zc) ** 2 + s.own_inertia_mm4() + a_s * (z_s - zc) ** 2
    return a, math.sqrt(i / a)


def column_stress_mpa(s: AngleStringer, skin_t: float, skin_b: float, length_mm: float, m: Material,
                      fixity: float = 1.0) -> tuple[float, float, float]:
    """(sigma_col, sigma_euler, sigma_cc): Euler-Johnson column strength of stringer + skin strip."""
    _, rho = column_section(s, skin_t, skin_b)
    lp = length_mm / math.sqrt(fixity)
    se = math.pi**2 * m.youngs_modulus_mpa / (lp / rho) ** 2
    scc = crippling_mpa(s, m)
    col = se if se <= scc / 2 else scc * (1 - scc / (4 * se))
    return col, se, scc


@dataclass
class PanelDesign:
    n_stringers: int
    skin_t_mm: float
    stringer: AngleStringer | None
    width_mm: float
    stress_ult_mpa: float
    margins: dict[str, float]

    @property
    def area_mm2(self) -> float:
        """Cover cross-section area (skin + stringers) -- mass per unit span / density."""
        return self.width_mm * self.skin_t_mm + (self.n_stringers * self.stringer.area_mm2 if self.stringer else 0.0)

    @property
    def pitch_mm(self) -> float:
        return self.width_mm / (self.n_stringers + 1)

    @property
    def smeared_t_mm(self) -> float:
        return self.area_mm2 / self.width_mm


def panel_margins(n: int, t: float, st: AngleStringer | None, w: float, h: float, t_web: float,
                  m_ult_nmm: float, m_lim_nmm: float, rib_pitch_mm: float, mat: Material) -> tuple[float, dict]:
    a_cov = w * t + (n * st.area_mm2 if st else 0.0)
    inertia = 2 * a_cov * (h / 2) ** 2 + 2 * t_web * h**3 / 12
    s_u = max(abs(m_ult_nmm) * (h / 2) / inertia, 1e-9)
    s_l = max(abs(m_lim_nmm) * (h / 2) / inertia, 1e-9)
    kp = _plate_coefficient(mat)
    b = w / (n + 1)
    ms = {
        "cover strength": mat.ftu_mpa / s_u - 1,
        "cover yield": mat.fty_mpa / s_l - 1,
        "skin buckling": PLATE_K_COMPRESSION * kp * (t / b) ** 2 / s_u - 1,
    }
    if st is not None:
        col, _, _ = column_stress_mpa(st, t, b, rib_pitch_mm, mat)
        ms["stringer column"] = col / s_u - 1
        # the bonding land must hand the full stringer load to the skin at a run-out (Volkersen plateau)
        from agents.structures.joints import design_bond

        land = design_bond(s_u * st.area_mm2 / st.leg_mm, mat.youngs_modulus_mpa, t, mat.youngs_modulus_mpa,
                           st.area_mm2 / st.leg_mm, BOND_PLATEAU_OVERLAP_MM)
        ms["stringer run-out bond"] = land.margin
    return s_u, ms


def design_panel(w: float, h: float, t_web: float, m_ult_nm: float, ultimate_factor: float, rib_pitch_mm: float,
                 mat: Material, min_gauge_mm: float = 0.3, gauge_step_mm: float = 0.05,
                 max_stringers: int = MAX_STRINGERS,
                 max_leg_mm: float | None = None) -> tuple[PanelDesign, list[PanelDesign]]:
    """Lightest cover (area) over stringer count, angle size and skin gauge with all margins >= 0.

    Returns (best, best-per-stringer-count) so the trade can be shown.
    """
    m_u = m_ult_nm * 1000.0
    m_l = m_u / ultimate_factor
    per_n: list[PanelDesign] = []
    for n in range(max_stringers + 1):
        legs = [a for a in STRINGER_LEGS_MM if max_leg_mm is None or a <= max_leg_mm]
        if n > 0 and not legs:
            break
        stringers = [None] if n == 0 else [AngleStringer(a, ts) for a in legs for ts in STRINGER_GAUGES_MM
                                           if ts <= a / 6]
        best_n = None
        for st in stringers:
            t = min_gauge_mm
            while t <= 6.0:
                s_u, ms = panel_margins(n, t, st, w, h, t_web, m_u, m_l, rib_pitch_mm, mat)
                if min(ms.values()) >= 0:
                    cand = PanelDesign(n, round(t, 3), st, w, s_u, ms)
                    if best_n is None or cand.area_mm2 < best_n.area_mm2 - 1e-9:
                        best_n = cand
                    break
                t += gauge_step_mm
        if best_n is not None:
            per_n.append(best_n)
    if not per_n:
        raise ValueError("no stiffened panel satisfies the margins")
    return min(per_n, key=lambda p: p.area_mm2), per_n


@dataclass
class StiffenedBoxDesign:
    bay_edges_mm: np.ndarray
    panels: list[PanelDesign]  # per bay (critical = root of the bay)
    trade_root: list[PanelDesign]  # stringer-count trade at the root bay
    t_web_mm: np.ndarray
    rib_pitch_mm: float

    def smeared_thickness(self) -> BoxThickness:
        """Equivalent BoxThickness (smeared cover area) for beam/FE bending checks."""
        return BoxThickness(self.bay_edges_mm, np.array([p.smeared_t_mm for p in self.panels]), self.t_web_mm)

    def cover_mass_kg(self, geometry: WingBoxGeometry, mat: Material) -> float:
        """Both covers of one semispan."""
        y = geometry.y_mm
        total = 0.0
        for b, p in enumerate(self.panels):
            sel = (y >= self.bay_edges_mm[b]) & (y <= self.bay_edges_mm[b + 1])
            ys, ws = y[sel], geometry.width_mm[sel]
            area = ws * p.skin_t_mm + (p.n_stringers * p.stringer.area_mm2 if p.stringer else 0.0)
            total += 2 * np.trapezoid(area, ys) * 1e-9 * mat.density_kgm3
        return float(total)


def design_stiffened_box(geometry: WingBoxGeometry, thickness: BoxThickness, bending_limit_nm: np.ndarray,
                         mat: Material, ultimate_factor: float = 1.5, min_gauge_mm: float = 0.3,
                         max_stringers: int = MAX_STRINGERS) -> StiffenedBoxDesign:
    """Stiffened covers bay by bay (ribs at the bay edges); webs as already sized.

    Stringer count is non-increasing outboard (stringers run out at ribs, they never start mid-span), and a
    stringer must fit the rib mouseholes: leg + clearance <= 35 % of the bay's smallest box depth.
    """
    y = geometry.y_mm
    edges = thickness.bay_edges_mm
    panels, trade = [], []
    n_max = max_stringers
    for b in range(len(edges) - 1):
        sel = np.where((y >= edges[b] - 1e-9) & (y <= edges[b + 1] + 1e-9))[0]
        # each station checked; the design (fixed across the bay) must satisfy all -> take the worst station
        best = None
        max_leg = MOUSEHOLE_DEPTH_FRACTION * float(np.min(geometry.height_mm[sel])) - MOUSEHOLE_CLEARANCE_MM
        for i in sel:
            cand, per_n = design_panel(geometry.width_mm[i], geometry.height_mm[i], thickness.t_web_mm[b],
                                       ultimate_factor * bending_limit_nm[i], ultimate_factor,
                                       edges[b + 1] - edges[b], mat, min_gauge_mm, max_stringers=n_max,
                                       max_leg_mm=max_leg)
            if best is None or cand.area_mm2 > best[0].area_mm2:
                best = (cand, per_n)
        panels.append(best[0])
        n_max = best[0].n_stringers  # stringers only run out outboard, never start mid-span
        if b == 0:
            trade = best[1]
    pitch = float(np.mean(np.diff(edges)))
    return StiffenedBoxDesign(np.asarray(edges), panels, trade, np.asarray(thickness.t_web_mm), pitch)
