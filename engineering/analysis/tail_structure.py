"""Tail internal structure (v0.16): CS-23-style tail loads -> box sizing -> built-up CAD -> shell FE check.

The v0.15 tails were solid foam-cored glass shells (a mass estimate only). Here
the horizontal stabiliser and the fin get the same built-up construction as
the wing -- front spar, rear (hinge) spar, ribs, box covers, LE/TE skin -- with
the elevator / rudder as separate foam-cored glass surfaces hinged behind the
rear spar.

Limit load cases (each side of the stabiliser / the fin; sign does not matter,
the boxes are symmetric):

* Horizontal tail manoeuvre (CS-23.421/423 style): the tail at its maximum
  lift coefficient (full elevator) at manoeuvring speed,
  L_h = C_Lh,max q_A S_h.
* Horizontal tail gust (CS-23.425):
  dL_h = 1/2 rho0 K_g U_de V a_h S_h (1 - d eps/d alpha), at V_C (U_de = 15.24
  m/s) and V_D (7.62 m/s), K_g the wing's gust alleviation factor.
* Fin manoeuvre (CS-23.441 style): C_Lv,max q_A S_v (full rudder / sideslip).
* Fin gust (CS-23.443): L_v = 1/2 rho0 K_gt U_de V a_v S_v with the lateral
  mass ratio mu_gt = 2 W / (rho c_v g a_v S_v) (K / l_v)^2, K_gt = 0.88 mu_gt /
  (5.3 + mu_gt), K the yaw radius of gyration.

Ultimate = 1.5 x limit. Spanwise distribution: Schrenk (mean of planform and
elliptic). The swept fin's bending moment is divided by cos(sweep of the box
mid-line) to get the moment about the swept box axis (the box is analysed as a
straight beam of that length -- the FE mesh is straight too). Torsion and hinge
moments are not carried by the box model; the hinge-line loads go to the
joint/fastener checks (`joint_design`).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from agents.geometry.fuselage_tail import SurfaceGeometry
from agents.structures.wing_box import (
    MATERIALS,
    WingBoxGeometry,
    WingBoxSizing,
    size_box,
)
from engineering.analysis.wing_loads import RHO0, G

CS23_UDE_VC_MPS = 15.24
CS23_UDE_VD_MPS = 7.62
CL_H_MAX = 1.0  # NACA 0009 stabiliser + 30 % elevator at full deflection (low Re)
CL_V_MAX = 1.0
FIN_ENDPLATE_FACTOR = 1.55  # effective fin AR = 1.55 x geometric (fuselage + stabiliser end plate, Raymer 16.4)
FRONT_SPAR_XC = 0.15
REAR_SPAR_GAP_XC = 0.05  # rear spar this far ahead of the hinge line
TAIL_MIN_GAUGE_MM = 0.3
TAIL_SKIN_MM = 0.3
TAIL_RIB_MM = 0.8
CONTROL_SURFACE_FOAM = 30.0  # kg/m^3
CONTROL_SURFACE_GLASS = 1600.0
CONTROL_SURFACE_SKIN_MM = 0.3


def helmbold_slope(aspect_ratio: float, sweep_half_chord_deg: float = 0.0) -> float:
    """3D lift slope per rad (Helmbold / DATCOM, section slope 2 pi)."""
    t2 = math.tan(math.radians(sweep_half_chord_deg)) ** 2
    return 2 * math.pi * aspect_ratio / (2 + math.sqrt(aspect_ratio**2 * (1 + t2) + 4))


def _sweep_at(geo: SurfaceGeometry, xc: float) -> float:
    """Sweep angle [deg] of the constant-x/c line `xc`."""
    dx = geo.span_mm * math.tan(math.radians(geo.sweep_le_deg)) + xc * (geo.tip_chord_mm - geo.root_chord_mm)
    return math.degrees(math.atan2(dx, geo.span_mm))


def schrenk(geo: SurfaceGeometry, total_n: float, y: np.ndarray) -> np.ndarray:
    """Running load [N/m] over one span of `geo` carrying `total_n` (mean of planform and elliptic)."""
    s = geo.span_mm
    c = geo.root_chord_mm + (geo.tip_chord_mm - geo.root_chord_mm) * y / s
    plan = total_n * c / geo.area_mm2
    ell = 4 * total_n / (math.pi * s) * np.sqrt(np.clip(1 - (y / s) ** 2, 0, None))
    return 0.5 * (plan + ell) * 1000.0  # N/mm -> N/m


def shear_bending(y_mm: np.ndarray, w_npm: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Shear [N] and bending [N m] from the tip inward."""
    ym = y_mm / 1000.0
    v = np.zeros_like(ym)
    m = np.zeros_like(ym)
    for i in range(len(ym) - 2, -1, -1):
        h = ym[i + 1] - ym[i]
        v[i] = v[i + 1] + 0.5 * (w_npm[i] + w_npm[i + 1]) * h
        m[i] = m[i + 1] + 0.5 * (v[i] + v[i + 1]) * h
    return v, m


@dataclass
class TailLoadCase:
    name: str
    surface: str  # "htail" | "vtail"
    speed_mps: float
    load_n: float  # limit load on one stabiliser half / the fin
    note: str = ""


@dataclass
class TailSurfaceStructure:
    surface: str
    geometry: SurfaceGeometry
    box: WingBoxGeometry
    sizing: WingBoxSizing
    design_case: TailLoadCase
    y_mm: np.ndarray
    lift_limit_npm: np.ndarray
    shear_limit_n: np.ndarray
    bending_limit_nm: np.ndarray
    box_sweep_deg: float
    rear_spar_xc: float
    structure: object = None  # WingStructure (one side)
    control_surface_mass_kg: float = 0.0
    fe: object = None  # WingBoxFEResult
    detail: object = None  # detail_design.SurfaceDetailDesign

    @property
    def n_sides(self) -> int:
        return 2 if self.surface == "htail" else 1

    @property
    def structure_mass_kg(self) -> float:
        """Built-up box + ribs + skins for the whole surface (both stabiliser halves)."""
        m = sum(self.structure.masses_kg().values())  # masses_kg counts a mirrored pair
        return m if self.n_sides == 2 else 0.5 * m

    @property
    def total_mass_kg(self) -> float:
        return self.structure_mass_kg + self.n_sides * self.control_surface_mass_kg


@dataclass
class TailStructureResult:
    cases: list[TailLoadCase]
    htail: TailSurfaceStructure
    vtail: TailSurfaceStructure
    a_h_per_rad: float
    a_v_per_rad: float
    mu_gt: float
    k_gt: float
    foam_estimate_kg: dict[str, float] = field(default_factory=dict)


def tail_load_cases(d, deps_dalpha: float, izz_kgm2: float) -> tuple[list[TailLoadCase], dict]:
    """CS-23-style limit loads on one stabiliser half and on the fin."""
    env = d.campaign.envelope
    ht, vt = d.tail.htail, d.tail.vtail
    s_h = 2 * ht.area_mm2 * 1e-6
    s_v = vt.area_mm2 * 1e-6
    ar_h = (2 * ht.span_mm) ** 2 / (2 * ht.area_mm2)
    ar_v = vt.span_mm**2 / vt.area_mm2 * FIN_ENDPLATE_FACTOR
    a_h = helmbold_slope(ar_h, _sweep_at(ht, 0.5))
    a_v = helmbold_slope(ar_v, _sweep_at(vt, 0.5))
    q = lambda v: 0.5 * RHO0 * v**2
    va, vc, vd, kg = env.v_maneuver_mps, env.v_cruise_mps, env.v_dive_mps, env.gust_alleviation_kg
    cases = [TailLoadCase("HT manoeuvre (C_Lh,max at V_A)", "htail", va, 0.5 * CL_H_MAX * q(va) * s_h,
                          f"C_Lh,max = {CL_H_MAX}")]
    for v, u in ((vc, CS23_UDE_VC_MPS), (vd, CS23_UDE_VD_MPS)):
        dl = 0.5 * RHO0 * kg * u * v * a_h * s_h * (1 - deps_dalpha)
        cases.append(TailLoadCase(f"HT gust U_de = {u:.2f} m/s", "htail", v, 0.5 * dl, f"K_g = {kg:.3f}"))
    l_v = (d.tail.x_vtail_le_mm + 0.25 * vt.mac_mm - d.x_cg_mm) / 1000.0
    k_rad = math.sqrt(izz_kgm2 / d.total_mass_kg)
    mu_gt = 2 * d.total_mass_kg * G / (RHO0 * vt.mac_mm / 1000.0 * G * a_v * s_v) * (k_rad / l_v) ** 2
    k_gt = 0.88 * mu_gt / (5.3 + mu_gt)
    cases.append(TailLoadCase("Fin manoeuvre (C_Lv,max at V_A)", "vtail", va, CL_V_MAX * q(va) * s_v,
                              f"C_Lv,max = {CL_V_MAX}"))
    for v, u in ((vc, CS23_UDE_VC_MPS), (vd, CS23_UDE_VD_MPS)):
        cases.append(TailLoadCase(f"Fin gust U_de = {u:.2f} m/s", "vtail", v,
                                  0.5 * RHO0 * k_gt * u * v * a_v * s_v, f"K_gt = {k_gt:.3f}"))
    return cases, {"a_h": a_h, "a_v": a_v, "mu_gt": mu_gt, "k_gt": k_gt}


def _foam_mass(geo: SurfaceGeometry, x0: float, x1: float) -> float:
    """Foam-core + glass-skin mass of the strip x0..x1 (x/c) of one surface [kg]."""
    area = geo.area_mm2 * (x1 - x0) * 1e-6
    t_mean = int(geo.naca[-2:]) / 100.0 * geo.mac_mm * 1e-3
    # thickness of the aft part tapers to zero: mean depth ~ 0.5 x the depth at x0
    frac_depth = 0.5 * 5 * 2 * (0.2969 * math.sqrt(x0) - 0.126 * x0 - 0.3516 * x0**2 + 0.2843 * x0**3
                                - 0.1015 * x0**4) if x0 > 0 else 0.69
    core = area * t_mean * frac_depth * CONTROL_SURFACE_FOAM
    return core + 2.05 * area * CONTROL_SURFACE_SKIN_MM * 1e-3 * CONTROL_SURFACE_GLASS


def size_tail_surface(surface: str, geo: SurfaceGeometry, cases: list[TailLoadCase], n_bays: int,
                      material: str = "al6061-t6", n_stations: int = 61) -> TailSurfaceStructure:
    rear = geo.hinge_xc - REAR_SPAR_GAP_XC
    box = WingBoxGeometry.from_planform(geo.span_mm, geo.root_chord_mm, geo.tip_chord_mm, geo.naca,
                                        n_stations=n_stations, front_spar_xc=FRONT_SPAR_XC, rear_spar_xc=rear)
    sweep_box = _sweep_at(geo, 0.5 * (FRONT_SPAR_XC + rear))
    mine = [c for c in cases if c.surface == surface]
    design = max(mine, key=lambda c: c.load_n)
    y = box.y_mm
    w = schrenk(geo, design.load_n, y)
    v, m = shear_bending(y, w)
    m = m / math.cos(math.radians(sweep_box))
    sizing = size_box(box, MATERIALS[material], v, m, 1.0, n_bays=n_bays, min_gauge_mm=TAIL_MIN_GAUGE_MM)
    return TailSurfaceStructure(surface, geo, box, sizing, design, y, w, v, m, sweep_box, rear)


def build_tail_structure_cad(ts: TailSurfaceStructure, n_profile: int = 25):
    from agents.geometry.wing_structure import WingStructureSpec, build_wing_structure

    th = ts.sizing.thickness
    spec = WingStructureSpec(
        semispan_mm=ts.geometry.span_mm, root_chord_mm=ts.geometry.root_chord_mm,
        tip_chord_mm=ts.geometry.tip_chord_mm, naca=ts.geometry.naca,
        bay_edges_mm=[float(e) for e in th.bay_edges_mm], t_cap_mm=[float(t) for t in th.t_cap_mm],
        t_web_mm=[float(t) for t in th.t_web_mm], front_spar_xc=FRONT_SPAR_XC, rear_spar_xc=ts.rear_spar_xc,
        rib_thickness_mm=TAIL_RIB_MM, skin_thickness_mm=TAIL_SKIN_MM,
        te_skin_end_xc=ts.geometry.hinge_xc - 0.005, n_profile=n_profile, sweep_le_deg=ts.geometry.sweep_le_deg,
    )
    ts.structure = build_wing_structure(spec)
    ts.control_surface_mass_kg = _foam_mass(ts.geometry, ts.geometry.hinge_xc, 1.0)
    return ts.structure


def design_tail_structure(d, deps_dalpha: float, izz_kgm2: float, build_cad: bool = True,
                          n_profile: int = 25) -> TailStructureResult:
    cases, k = tail_load_cases(d, deps_dalpha, izz_kgm2)
    ht = size_tail_surface("htail", d.tail.htail, cases, n_bays=4)
    vt = size_tail_surface("vtail", d.tail.vtail, cases, n_bays=3)
    if build_cad:
        build_tail_structure_cad(ht, n_profile)
        build_tail_structure_cad(vt, n_profile)
    foam = {i.name: i.mass_kg for i in d.mass_items if i.name in ("Horizontal tail", "Vertical tail")}
    return TailStructureResult(cases, ht, vt, k["a_h"], k["a_v"], k["mu_gt"], k["k_gt"], foam)


def verify_tail_fe(ts: TailSurfaceStructure, work_dir: str | None = None, n_span: int = 48):
    """CalculiX S8R shell check of the sized box at ULTIMATE load (static, buckling, modes)."""
    from agents.structures.agent import StructuresAgent

    th = ts.sizing.thickness
    ts.fe = StructuresAgent().evaluate_wing_box(
        ts.box, th, ts.sizing.material, ts.y_mm, 1.5 * ts.lift_limit_npm / math.cos(math.radians(ts.box_sweep_deg)),
        n_span=n_span, n_width=8, n_height=4, rib_thickness_mm=TAIL_RIB_MM, work_dir=work_dir,
    )
    return ts.fe


def tail_assembly(result: TailStructureResult, d):
    """Labelled built-up tails placed on the aircraft: HorizontalTail (both halves) and VerticalTail."""
    from build123d import Compound, Pos, Rot

    z_t = d.stations[-1].z_center_mm
    ht_s, vt_s = result.htail.structure, result.vtail.structure
    gap = 0.01
    ht_children = list(ht_s.full_wing().values())
    for side, sgn in (("Stbd", 1.0), ("Port", -1.0)):
        el = control_surface_part(d.tail.htail, "htail", sgn, gap)
        el.label = f"Elevator_{side}"
        ht_children.append(el)
    ht = Pos(d.tail.x_htail_le_mm, 0, z_t) * Compound(children=ht_children, label="HorizontalTail")
    fin_children = []
    from agents.geometry.wing_structure import GROUP_COLORS, GROUP_LABELS

    for g, ps in vt_s.parts.items():
        if not ps:
            continue
        solids = []
        for p in ps:
            q = Rot(90, 0, 0) * p
            q.label, q.color = f"Fin{p.label}", GROUP_COLORS[g]
            solids.append(q)
        fin_children.append(Compound(children=solids, label=f"Fin{GROUP_LABELS[g]}"))
    fin_children.append(control_surface_part(d.tail.vtail, "vtail", gap=gap))
    vt = Pos(d.tail.x_vtail_le_mm, 0, z_t) * Compound(children=fin_children, label="VerticalTail")
    return ht, vt


def control_surface_part(geo: SurfaceGeometry, surface: str, side_sign: float = 1.0, gap: float = 0.01):
    """Elevator (one side) or rudder solid in the surface's own frame (x from the LE)."""
    from agents.geometry.fuselage_tail import SURFACE_COLOR, _surface_part

    if surface == "htail":
        return _surface_part(geo, geo.hinge_xc + gap / 2, 1.0, lambda x, s, z: (x, side_sign * s, z), "Elevator",
                             SURFACE_COLOR)
    return _surface_part(geo, geo.hinge_xc + gap / 2, 1.0, lambda x, s, z: (x, z, s), "Rudder", SURFACE_COLOR)


def tail_mass_items(result: TailStructureResult) -> dict[str, tuple[float, float, float]]:
    """{'Horizontal tail' / 'Vertical tail': (mass, centroid x from the surface LE, centroid z offset)} from CAD."""
    out = {}
    for name, ts in (("Horizontal tail", result.htail), ("Vertical tail", result.vtail)):
        m_tot, mx, mz = 0.0, 0.0, 0.0
        for g, ps in ts.structure.parts.items():
            rho = ts.structure.densities[g]
            for p in ps:
                m = float(p.volume) * 1e-9 * rho
                c = p.center()
                # the fin is built spanwise along y and stood up (y -> z) in the aircraft
                z = c.Y if ts.surface == "vtail" else c.Z
                m_tot += m * ts.n_sides
                mx += m * ts.n_sides * c.X
                mz += m * ts.n_sides * z
        cs = control_surface_part(ts.geometry, ts.surface)
        c = cs.center()
        m_cs = ts.n_sides * ts.control_surface_mass_kg
        m_tot += m_cs
        mx += m_cs * c.X
        mz += m_cs * (c.Z if ts.surface == "vtail" else 0.0)
        out[name] = (m_tot, mx / m_tot, mz / m_tot)
    return out


def attach_details(result: TailStructureResult, htail_detail, vtail_detail) -> TailStructureResult:
    """Use the detailed (stiffened, riveted, bonded) structures from `detail_design.detail_tail` as the tails."""
    for ts, dd in ((result.htail, htail_detail), (result.vtail, vtail_detail)):
        ts.structure = dd.structure
        ts.detail = dd
        ts.control_surface_mass_kg = _foam_mass(ts.geometry, ts.geometry.hinge_xc, 1.0)
    return result
