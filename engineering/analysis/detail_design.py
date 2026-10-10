"""Detail design of the wing and tail boxes (v0.16): stiffeners, flanges, fasteners, bonding lands, notches.

For each lifting surface (wing semispan, stabiliser half, fin):

1. Stringer-stiffened covers replace the unstiffened buckling-sized covers
   (`agents.structures.stiffened_panel`), bay by bay, stringers running out
   outboard.
2. Spars become formed C-channels; their flanges are riveted to the covers.
   Rivet size and pitch from the box shear flow, rivet shear, sheet bearing
   and inter-rivet buckling (`agents.structures.joints`).
3. Stringers are bonded to the skin; the bonding land (the attached leg)
   must pass the full stringer load into the skin at every run-out
   (Volkersen; overlap chosen past the elastic plateau).
4. Ribs: 0.5 mm webs (handling minimum gauge), split at the spar webs,
   mouseholes for the stringers, notches for the spar flanges, flanged
   lightening holes, bonded rib flanges. Rib web shear from the bay's air
   load; skin-suction peel on the rib-flange bond.
5. Close-up CalculiX models check each hand method (`agents.structures.detail_fe`).

The detailed CAD (`agents.geometry.wing_structure.StructureDetails`) is built
from these numbers and its measured mass goes back into the aircraft balance.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from agents.geometry.wing_structure import (
    StructureDetails,
    WingStructureSpec,
    build_wing_structure,
)
from agents.structures.joints import (
    ADHESIVE_TAU_ALLOW_MPA,
    BondedLap,
    RivetedLine,
    design_bond,
    design_rivet_line,
)
from agents.structures.stiffened_panel import StiffenedBoxDesign, design_stiffened_box
from agents.structures.wing_box import BoxThickness, Material, WingBoxGeometry

RIB_T_MM = 0.5
BOND_OVERLAPS_MM = (5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 40.0)


@dataclass
class RibCheck:
    t_mm: float
    bay_air_load_n: float
    web_depth_net_mm: float
    tau_mpa: float
    tau_cr_plain_mpa: float
    suction_kpa: float
    flange_peel_mpa: float
    margins: dict[str, float]


@dataclass
class SurfaceDetailDesign:
    name: str
    geometry: WingBoxGeometry
    thickness_v014: BoxThickness
    stiffened: StiffenedBoxDesign
    rivets: RivetedLine
    bond: BondedLap
    bond_curve: list[tuple[float, float]]  # (overlap, tau_max)
    rib: RibCheck
    details: StructureDetails
    spec: WingStructureSpec
    structure: object = None
    mass_unstiffened_covers_kg: float = 0.0
    mass_stiffened_covers_kg: float = 0.0
    fe: dict = field(default_factory=dict)

    @property
    def root(self):
        return self.stiffened.panels[0]


def _rib_check(geometry: WingBoxGeometry, lift_ult_npm: np.ndarray, bay_edges: np.ndarray, mat: Material,
               hole_ratio: float, rib_pitch: float) -> RibCheck:
    from agents.structures.wing_box import _plate_coefficient

    y = geometry.y_mm
    sel = y <= bay_edges[1] + 1e-9
    bay_load = float(np.trapezoid(lift_ult_npm[sel], y[sel] / 1000.0))  # N on the root bay
    w, h = geometry.width_mm[0], geometry.height_mm[0]
    net = h * (1 - 2 * hole_ratio)
    tau = bay_load / (net * RIB_T_MM)
    a, b = max(w, h), min(w, h)
    tau_cr = (5.35 + 4 * (b / a) ** 2) * _plate_coefficient(mat) * (RIB_T_MM / b) ** 2
    chord = geometry.chord_mm[0]
    suction = 2.0 * bay_load / ((bay_edges[1] - bay_edges[0]) * chord) * 1e3  # kPa: peak ~ 2 x mean (upper)
    peel = suction * 1e-3 * rib_pitch / 6.0  # MPa on a 6 mm rib flange
    ms = {"rib web shear strength": mat.fsu_mpa / tau - 1, "rib web shear buckling": tau_cr / tau - 1,
          "rib flange peel": 5.0 / max(peel, 1e-9) - 1}  # 5 MPa flatwise tension allowable (paste epoxy)
    return RibCheck(RIB_T_MM, bay_load, net, tau, tau_cr, suction, peel, ms)


def detail_surface(name: str, geometry: WingBoxGeometry, thickness: BoxThickness, shear_limit_n: np.ndarray,
                   bending_limit_nm: np.ndarray, lift_limit_npm: np.ndarray, mat: Material, spec_kwargs: dict,
                   ultimate: float = 1.5, min_gauge_mm: float = 0.3, build: bool = True,
                   n_profile: int = 25) -> SurfaceDetailDesign:
    sd = design_stiffened_box(geometry, thickness, bending_limit_nm, mat, ultimate, min_gauge_mm)
    root = sd.panels[0]
    t_web0 = float(thickness.t_web_mm[0])
    rv = design_rivet_line(ultimate * shear_limit_n[0], geometry.width_mm[0], geometry.height_mm[0], root.area_mm2,
                           t_web0, t_web0, root.skin_t_mm, root.stress_ult_mpa, mat)
    # stringer run-out bond (root bay stringer, the most loaded)
    st = next((p.stringer for p in sd.panels if p.stringer is not None), None)
    if st is not None:
        p_st = root.stress_ult_mpa * st.area_mm2 / st.leg_mm  # N/mm of land width
        t2_eff = st.area_mm2 / st.leg_mm
        curve = []
        for ov in BOND_OVERLAPS_MM:
            b = design_bond(p_st, mat.youngs_modulus_mpa, root.skin_t_mm, mat.youngs_modulus_mpa, t2_eff, ov)
            curve.append((ov, b.tau_max_mpa))
        ok = [ov for ov, tm in curve if tm <= ADHESIVE_TAU_ALLOW_MPA]
        ov = ok[0] if ok else BOND_OVERLAPS_MM[-1]
        # past the elastic plateau: at least 3 / omega so the peak no longer drops with length
        b0 = design_bond(p_st, mat.youngs_modulus_mpa, root.skin_t_mm, mat.youngs_modulus_mpa, t2_eff, ov)
        ov = max(ov, 5.0 * math.ceil(3.0 / b0.omega_per_mm / 5.0))
        bond = design_bond(p_st, mat.youngs_modulus_mpa, root.skin_t_mm, mat.youngs_modulus_mpa, t2_eff, ov)
    else:
        bond, curve = None, []
    edges = thickness.bay_edges_mm
    rib = _rib_check(geometry, ultimate * lift_limit_npm, edges, mat, 0.20, float(np.mean(np.diff(edges))))
    det = StructureDetails(
        stringers_per_bay=[p.n_stringers for p in sd.panels],
        stringer_leg_mm=[p.stringer.leg_mm if p.stringer else 8.0 for p in sd.panels],
        stringer_t_mm=[p.stringer.t_mm if p.stringer else 0.4 for p in sd.panels],
        spar_flange_width_mm=max(6.0, rv.flange_width_mm),
        rivet_diameter_mm=rv.diameter_mm,
        rivet_pitch_mm=rv.pitch_mm,
    )
    spec = WingStructureSpec(
        bay_edges_mm=[float(e) for e in edges], t_cap_mm=[p.skin_t_mm for p in sd.panels],
        t_web_mm=[float(t) for t in thickness.t_web_mm], rib_thickness_mm=RIB_T_MM, n_profile=n_profile,
        details=det, **spec_kwargs,
    )
    y = geometry.y_mm
    unst = 2 * np.trapezoid(geometry.width_mm * thickness.at(y)[0], y) * 1e-9 * mat.density_kgm3
    out = SurfaceDetailDesign(name, geometry, thickness, sd, rv, bond, curve, rib, det, spec,
                              mass_unstiffened_covers_kg=float(unst),
                              mass_stiffened_covers_kg=sd.cover_mass_kg(geometry, mat))
    if build:
        out.structure = build_wing_structure(spec)
    return out


def detail_wing(campaign, build: bool = True, n_profile: int = 31) -> SurfaceDetailDesign:
    from agents.structures.wing_box import MATERIALS

    a, g, L = campaign.aero, campaign.box_geometry, campaign.loads_limit
    y_m = g.y_mm / 1000.0
    v = np.interp(y_m, L.y_m, L.shear_n)
    m = np.interp(y_m, L.y_m, L.bending_nm)
    lift = np.interp(y_m, L.y_m, L.lift_per_span_npm)
    kw = {"semispan_mm": campaign.requirement.span_mm / 2, "root_chord_mm": a.root_chord_mm,
          "tip_chord_mm": a.tip_chord_mm, "naca": a.naca, "front_spar_xc": g.front_spar_xc,
          "rear_spar_xc": g.rear_spar_xc}
    return detail_surface("wing", g, campaign.sizing.thickness, v, m, lift,
                          MATERIALS[campaign.requirement.material], kw, campaign.requirement.ultimate_factor,
                          campaign.requirement.min_gauge_mm, build, n_profile)


def detail_tail(ts, build: bool = True, n_profile: int = 25) -> SurfaceDetailDesign:
    """Stiffened/detailed version of a `tail_structure.TailSurfaceStructure` (bending already includes 1/cos sweep)."""
    from engineering.analysis.tail_structure import (
        FRONT_SPAR_XC,
        TAIL_MIN_GAUGE_MM,
        TAIL_SKIN_MM,
    )

    geo = ts.geometry
    kw = {"semispan_mm": geo.span_mm, "root_chord_mm": geo.root_chord_mm, "tip_chord_mm": geo.tip_chord_mm,
          "naca": geo.naca, "front_spar_xc": FRONT_SPAR_XC, "rear_spar_xc": ts.rear_spar_xc,
          "skin_thickness_mm": TAIL_SKIN_MM, "te_skin_end_xc": geo.hinge_xc - 0.005,
          "sweep_le_deg": geo.sweep_le_deg}
    return detail_surface(ts.surface, ts.box, ts.sizing.thickness, ts.shear_limit_n, ts.bending_limit_nm,
                          ts.lift_limit_npm, ts.sizing.material, kw, 1.5, TAIL_MIN_GAUGE_MM, build, n_profile)


# --------------------------------------------------------------------------- close-up FE


def run_closeup_fe(w: SurfaceDetailDesign, work_root: str | None = None) -> dict:
    """The five close-up CalculiX checks for one surface's root details (serial; a few seconds each)."""
    import os

    from agents.structures import detail_fe as fe
    from agents.structures.wing_box import _plate_coefficient

    def wd(name):
        return os.path.join(work_root, name) if work_root else None

    mat_e = 68900.0
    out = {}
    root, rv = w.root, w.rivets
    d_hole = rv.diameter_mm + 0.1  # drilled hole, #52 drill for 1/16" rivets
    out["fastener_hole"] = fe.open_hole_kt(rv.pitch_mm, d_hole, root.skin_t_mm, work_dir=wd("hole"))
    out["notch_validation"] = fe.edge_notch_kt(40.0, 2.0, RIB_T_MM, work_dir=wd("notch_val"))
    det = w.details
    depth = float(w.geometry.height_mm[0])
    slot_w = det.stringer_leg_mm[0] + 2 * det.mousehole_clearance_mm
    slot_d = det.stringer_leg_mm[0] + det.mousehole_clearance_mm
    out["rib_notch"] = fe.rib_notch_kt(depth, slot_w, slot_d, RIB_T_MM, work_dir=wd("rib_notch"))
    out["rib_notch_fine"] = fe.rib_notch_kt(depth, slot_w, slot_d, RIB_T_MM, refine=2.0, work_dir=wd("rib_notch2"))
    if w.bond is not None:
        st = root.stringer
        t2 = st.area_mm2 / st.leg_mm
        out["bond_supported"] = fe.bonded_lap(w.bond.p_npmm, w.bond.overlap_mm, root.skin_t_mm, t2,
                                              work_dir=wd("bond_s"))
        out["bond_unsupported"] = fe.bonded_lap(w.bond.p_npmm, w.bond.overlap_mm, root.skin_t_mm, t2,
                                                supported=False, work_dir=wd("bond_u"))
    pitch = float(np.mean(np.diff(w.stiffened.bay_edges_mm)))
    wd0 = float(w.geometry.width_mm[0])
    if root.stringer is not None:
        out["panel_stiffened"] = fe.stiffened_panel_buckling(pitch, wd0, root.skin_t_mm, root.n_stringers,
                                                             root.stringer.leg_mm, root.stringer.t_mm,
                                                             root.stress_ult_mpa, work_dir=wd("panel"))
    t0 = float(w.thickness_v014.t_cap_mm[0])
    out["panel_unstiffened_v014"] = fe.stiffened_panel_buckling(pitch, wd0, t0, 0, 8.0, 0.4, root.stress_ult_mpa,
                                                                work_dir=wd("panel0"))
    a_r = pitch / wd0
    k_exact = min((m / a_r + a_r / m) ** 2 for m in range(1, 6))
    out["panel_unstiffened_v014"].reference = (k_exact * _plate_coefficient(_al()) * (t0 / wd0) ** 2
                                               / root.stress_ult_mpa)
    # rib web in shear at the rib's design shear stress
    h_web, w_web = depth - 2 * float(w.spec.t_cap_mm[0]), wd0
    from agents.geometry.wing_structure import detailed_rib_holes

    x_front = w.spec.front_spar_xc * w.spec.chord(0.0)
    holes = [(xh - x_front, h_web / 2, r) for xh, _, r in detailed_rib_holes(w.spec, 0.0)]  # the root rib's holes
    tau = w.rib.tau_mpa
    ks = 5.35 + 4 * (min(w_web, h_web) / max(w_web, h_web)) ** 2
    plain = fe.shear_web_buckling(w_web, h_web, RIB_T_MM, tau_ref_mpa=tau, work_dir=wd("web_plain"))
    plain.reference = ks * _plate_coefficient(_al()) * (RIB_T_MM / min(w_web, h_web)) ** 2 / tau
    out["web_plain"] = plain
    out["web_holes"] = fe.shear_web_buckling(w_web, h_web, RIB_T_MM, holes, tau_ref_mpa=tau, work_dir=wd("web_h"))
    out["web_flanged"] = fe.shear_web_buckling(w_web, h_web, RIB_T_MM, holes, lip_mm=det.hole_lip_mm,
                                               tau_ref_mpa=tau, work_dir=wd("web_f"))
    out["hole_shear_validation"] = fe.hole_in_shear_kt(40 * 10.0, 10.0, work_dir=wd("hole_shear"))
    del mat_e
    w.fe = out
    return out


def _al():
    from agents.structures.wing_box import MATERIALS

    return MATERIALS["al6061-t6"]
