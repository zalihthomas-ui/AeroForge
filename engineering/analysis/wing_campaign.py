"""Virtual wing structural test campaign (v0.14 flagship).

Requirement -> 3D (lifting-line) aerodynamic sizing -> design loads (V-n,
CS-23 gust, ultimate factor) -> thin-walled wing-box sizing (closed form,
minimum mass with all margins >= 0) -> CalculiX shell FE verification of the
sized box (static at ultimate load, linear buckling, natural frequencies) ->
CAD export.

It deliberately reports what the finite-wing correction changes relative to
the v0.8-v0.13 flagship (`wing_flagship.py`), which multiplied a 2D section
CL by the planform area and checked a SOLID aluminium wing at 1 g cruise:

* 3D lift: at the same airfoil and angle, a finite wing makes less lift
  (downwash), so the old 2D sizing under-sized the chord.
* With the old NACA 0012 at 4 deg, closing lift = weight in 3D needs an
  aspect ratio of ~2.5 -- outside lifting-line validity and a poor wing. The
  campaign therefore re-selects a cambered NACA 4412 (alpha_L0 ~ -4 deg),
  which closes at a normal aspect ratio.
* "Safety factor" is replaced by margins of safety of a real thin-walled
  box at ULTIMATE load (limit x 1.5), including buckling, and the reported
  mass is the mass of that box.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import brentq

from agents.structures.agent import CALCULIX_AVAILABLE, StructuresAgent
from agents.structures.wing_box import (
    MATERIALS,
    Material,
    WingBoxGeometry,
    WingBoxSizing,
    beam_natural_frequencies,
    size_box,
)
from agents.structures.wing_box_fe import WingBoxFEResult
from engineering.analysis.wing_lifting_line import (
    LiftingLineResult,
    SectionLiftParameters,
    evaluate_tapered_wing,
    section_cl_max,
)
from engineering.analysis.wing_loads import (
    G,
    LoadEnvelope,
    SpanwiseLoads,
    load_envelope,
    spanwise_loads,
)

LIFTING_LINE_MIN_AR = 4.0
CL_MAX_3D_FACTOR = 0.9  # wing CLmax ~ 0.9 x section clmax (Raymer sec. 12.4 rule of thumb)


class WingCampaignError(RuntimeError):
    """Raised when the campaign cannot close a requirement."""


@dataclass
class CampaignRequirement:
    mtow_kg: float = 12.0
    cruise_velocity_mps: float = 25.0
    span_mm: float = 1800.0
    alpha_deg: float = 4.0
    taper_ratio: float = 140.0 / 240.0
    baseline_root_chord_mm: float = 240.0  # old flagship baseline planform
    airfoil_candidates: tuple[str, ...] = ("0012", "2412", "4412")
    n_pos: float = 3.8
    n_neg: float = -1.5
    ultimate_factor: float = 1.5
    material: str = "al6061-t6"
    n_bays: int = 6
    min_gauge_mm: float = 0.3


@dataclass
class AeroSizing:
    naca: str
    chord_scale: float
    root_chord_mm: float
    tip_chord_mm: float
    aspect_ratio: float
    lifting_line: LiftingLineResult
    section: SectionLiftParameters
    lift_n: float
    valid_lifting_line: bool


@dataclass
class ModellingComparison:
    """Old 2D-section answer vs the 3D answer, same requirement."""

    old_naca: str
    old_chord_scale_2d: float
    old_root_chord_mm: float
    old_aspect_ratio: float
    old_lift_2d_n: float  # what the old method claimed for its sized wing
    old_lift_3d_n: float  # what that same wing really makes (lifting line)
    same_airfoil_3d_chord_scale: float
    same_airfoil_3d_aspect_ratio: float
    candidates: dict[str, AeroSizing] = field(default_factory=dict)


@dataclass
class CampaignResult:
    requirement: CampaignRequirement
    comparison: ModellingComparison
    aero: AeroSizing
    envelope: LoadEnvelope
    loads_limit: SpanwiseLoads
    box_geometry: WingBoxGeometry
    sizing: WingBoxSizing
    alternatives: dict[str, WingBoxSizing]
    beam_frequencies_hz: np.ndarray
    fe: WingBoxFEResult | None
    cad_paths: dict[str, str] = field(default_factory=dict)


def _old_2d_lift(naca: str, root_mm: float, tip_mm: float, span_mm: float, v: float, alpha: float,
                 rho: float = 1.225, nu: float = 1.46e-5) -> float:
    """Exactly the v0.8-v0.13 `wing_aero.evaluate_wing_aero` model: 2D section CL (root-chord Re) x q x S."""
    from agents.aerodynamics.agent import AerodynamicsAgent

    re = v * root_mm / 1000.0 / nu
    cl = AerodynamicsAgent().evaluate_naca_airfoil(naca, alpha, re).cl
    return cl * 0.5 * rho * v**2 * span_mm / 1000.0 * (root_mm + tip_mm) / 2000.0


def size_planform_3d(req: CampaignRequirement, naca: str, bounds=(0.3, 6.0)) -> AeroSizing:
    """Chord scale k (span and taper fixed) such that the lifting-line lift equals the weight."""
    w = req.mtow_kg * G
    b = req.span_mm / 1000.0
    c0 = req.baseline_root_chord_mm / 1000.0

    def residual(k):
        ll, _ = evaluate_tapered_wing(b, c0 * k, c0 * k * req.taper_ratio, req.alpha_deg, naca,
                                      req.cruise_velocity_mps)
        return ll.lift_n(req.cruise_velocity_mps, 1.225) - w

    try:
        k = float(brentq(residual, *bounds, xtol=1e-4))
    except ValueError as exc:
        raise WingCampaignError(f"NACA {naca}: lift = weight not bracketed by k in {bounds}.") from exc
    ll, sec = evaluate_tapered_wing(b, c0 * k, c0 * k * req.taper_ratio, req.alpha_deg, naca,
                                    req.cruise_velocity_mps)
    return AeroSizing(naca, k, 1000 * c0 * k, 1000 * c0 * k * req.taper_ratio, ll.aspect_ratio, ll, sec,
                      ll.lift_n(req.cruise_velocity_mps, 1.225), ll.aspect_ratio >= LIFTING_LINE_MIN_AR)


def compare_models(req: CampaignRequirement) -> ModellingComparison:
    """Re-derive the old 2D answer and the 3D answers for every candidate airfoil."""
    w = req.mtow_kg * G
    c0 = req.baseline_root_chord_mm
    tr = req.taper_ratio
    old_naca = req.airfoil_candidates[0]

    def old_res(k):
        return _old_2d_lift(old_naca, c0 * k, c0 * k * tr, req.span_mm, req.cruise_velocity_mps, req.alpha_deg) - w

    k_old = float(brentq(old_res, 1.0, 2.5, xtol=1e-4))
    b = req.span_mm / 1000.0
    ll_old, _ = evaluate_tapered_wing(b, c0 * k_old / 1000, c0 * k_old * tr / 1000, req.alpha_deg, old_naca,
                                      req.cruise_velocity_mps)
    cands = {naca: size_planform_3d(req, naca) for naca in req.airfoil_candidates}
    same = cands[old_naca]
    return ModellingComparison(
        old_naca=old_naca,
        old_chord_scale_2d=k_old,
        old_root_chord_mm=c0 * k_old,
        old_aspect_ratio=ll_old.aspect_ratio,
        old_lift_2d_n=w,
        old_lift_3d_n=ll_old.lift_n(req.cruise_velocity_mps, 1.225),
        same_airfoil_3d_chord_scale=same.chord_scale,
        same_airfoil_3d_aspect_ratio=same.aspect_ratio,
        candidates=cands,
    )


def select_airfoil(comparison: ModellingComparison) -> AeroSizing:
    """Smallest wing (min chord) whose sizing is inside lifting-line validity."""
    valid = [a for a in comparison.candidates.values() if a.valid_lifting_line]
    if not valid:
        raise WingCampaignError("No candidate airfoil closes lift = weight at AR >= 4.")
    return min(valid, key=lambda a: a.chord_scale)


def run_campaign(
    req: CampaignRequirement | None = None,
    run_fe: bool = True,
    fe_mesh: tuple[int, int, int] = (96, 12, 4),
    export_dir: str | None = None,
    work_dir: str | None = None,
    structures_agent: StructuresAgent | None = None,
) -> CampaignResult:
    req = req or CampaignRequirement()
    comparison = compare_models(req)
    aero = select_airfoil(comparison)
    ll = aero.lifting_line
    mean_chord_m = 0.5 * (aero.root_chord_mm + aero.tip_chord_mm) / 1000.0
    cl_max = CL_MAX_3D_FACTOR * section_cl_max(aero.naca, aero.section.reynolds_number)
    env = load_envelope(req.mtow_kg, ll.area_m2, mean_chord_m, ll.cl_alpha_per_rad, cl_max,
                        req.cruise_velocity_mps, n_pos=req.n_pos, n_neg=req.n_neg,
                        ultimate_factor=req.ultimate_factor)
    weight = req.mtow_kg * G
    loads = spanwise_loads(ll, weight, env.n_limit)
    geo = WingBoxGeometry.from_planform(req.span_mm / 2.0, aero.root_chord_mm, aero.tip_chord_mm, aero.naca,
                                        n_stations=len(ll.y_m))
    material: Material = MATERIALS[req.material]
    sizing = size_box(geo, material, loads.shear_n, loads.bending_nm, env.n_limit,
                      ultimate_factor=req.ultimate_factor, n_bays=req.n_bays, min_gauge_mm=req.min_gauge_mm)
    alternatives = {
        key: size_box(geo, mat, loads.shear_n, loads.bending_nm, env.n_limit,
                      ultimate_factor=req.ultimate_factor, n_bays=req.n_bays, min_gauge_mm=req.min_gauge_mm)
        for key, mat in MATERIALS.items()
    }
    rib_masses = _rib_point_masses(geo, sizing, rib_thickness_mm=1.0)
    beam_f = beam_natural_frequencies(geo, sizing.thickness, material, 3, point_masses=rib_masses)

    fe = None
    if run_fe and CALCULIX_AVAILABLE:
        agent = structures_agent or StructuresAgent()
        lift_ult = loads.lift_per_span_npm * req.ultimate_factor
        ns, nw, nh = fe_mesh
        fe = agent.evaluate_wing_box(geo, sizing.thickness, material, geo.y_mm, lift_ult,
                                     n_span=ns, n_width=nw, n_height=nh, work_dir=work_dir)

    cad = {}
    if export_dir:
        cad = export_wing_cad(aero, req, export_dir)
    return CampaignResult(req, comparison, aero, env, loads, geo, sizing, alternatives, beam_f, fe, cad)


def _rib_point_masses(geo: WingBoxGeometry, sizing: WingBoxSizing, rib_thickness_mm: float):
    edges = sizing.thickness.bay_edges_mm[1:]
    return [(float(y), float(np.interp(y, geo.y_mm, geo.width_mm) * np.interp(y, geo.y_mm, geo.height_mm)
                              * rib_thickness_mm * 1e-9 * sizing.material.density_kgm3)) for y in edges]


def export_wing_cad(aero: AeroSizing, req: CampaignRequirement, export_dir: str) -> dict[str, str]:
    """Outer-mould-line CAD of the sized (unswept, untwisted) wing."""
    from agents.geometry.wing import build_wing
    from cad.exporters import export_step, export_stl

    os.makedirs(export_dir, exist_ok=True)
    params = {
        "wing_span": req.span_mm,
        "root_chord": aero.root_chord_mm,
        "tip_chord": aero.tip_chord_mm,
        "sweep": 0.0,
        "dihedral": 0.0,
        "naca_airfoil": float(int(aero.naca)),
    }
    part = build_wing(params)
    step = os.path.join(export_dir, "wing_campaign.step")
    stl = os.path.join(export_dir, "wing_campaign.stl")
    export_step(part, step)
    export_stl(part, stl)
    return {"step": step, "stl": stl}


def fe_vs_closed_form(result: CampaignResult) -> dict[str, float]:
    """Headline FE-vs-closed-form comparisons at ultimate load (percent differences)."""
    fe = result.fe
    if fe is None:
        return {}
    ult = result.sizing.ultimate
    # Compare mid-bay (away from the rib / thickness steps) wherever the cover
    # stress is at least 25 % of its peak: near the tip the stress tends to
    # zero and a fraction-of-an-MPa offset would dominate a relative error.
    bays = result.sizing.thickness.bay_edges_mm
    mids = 0.5 * (bays[1:] + bays[:-1])
    cf_mid = np.interp(mids, ult.y_mm, ult.bending_stress_mpa)
    fe_mid = np.abs(np.interp(mids, fe.cover_stress_y_mm, fe.cover_stress_mpa))
    keep = cf_mid >= 0.25 * float(np.max(ult.bending_stress_mpa))
    cf_mid, fe_mid = cf_mid[keep], fe_mid[keep]
    out = {
        "tip_deflection_diff_pct": 100.0 * (fe.tip_deflection_mm / ult.tip_deflection_mm - 1.0),
        "max_cover_stress_diff_pct_mid_bay": float(np.max(np.abs(fe_mid / cf_mid - 1.0)) * 100.0),
        "first_bending_freq_diff_pct": 100.0 * (fe.frequencies_hz[0] / result.beam_frequencies_hz[0] - 1.0),
        "buckling_fe_over_ss_plate": fe.buckling_factors[0] / (1.0 + result.sizing.margins.ms_cover_buckling),
    }
    return out


def margins_from_fe(result: CampaignResult) -> dict[str, float]:
    """Margins of safety computed from the FE results (ultimate load)."""
    fe = result.fe
    if fe is None:
        return {}
    mat = result.sizing.material
    return {
        "strength (Ftu / peak von Mises away from clamp)": mat.ftu_mpa / fe.max_von_mises_away_from_root_mpa - 1.0,
        "buckling (first eigenvalue - 1)": fe.buckling_factors[0] - 1.0,
    }


def build_structure_cad(result: CampaignResult, export_dir: str | None = None, **spec_overrides):
    """Complete wing structure (ribs, spars, box covers, LE/TE skin) from the sized campaign result.

    Returns the `WingStructure`; with `export_dir`, also writes a named, coloured
    STEP assembly of the whole wing (Wing > group > part), one STEP file per part
    under ``parts/``, a DXF cutting profile per rib under ``rib_flats/`` and one
    STL per component group.
    """
    from agents.geometry.wing_structure import WingStructureSpec, build_wing_structure

    s, a = result.sizing, result.aero
    spec = WingStructureSpec(
        semispan_mm=result.requirement.span_mm / 2.0,
        root_chord_mm=a.root_chord_mm,
        tip_chord_mm=a.tip_chord_mm,
        naca=a.naca,
        bay_edges_mm=[float(v) for v in s.thickness.bay_edges_mm],
        t_cap_mm=[float(v) for v in s.thickness.t_cap_mm],
        t_web_mm=[float(v) for v in s.thickness.t_web_mm],
        front_spar_xc=result.box_geometry.front_spar_xc,
        rear_spar_xc=result.box_geometry.rear_spar_xc,
        **spec_overrides,
    )
    structure = build_wing_structure(spec)
    if export_dir:
        from agents.geometry.wing_structure import rib_flat_patterns
        from cad.exporters import (
            export_parts_step,
            export_profile_dxf,
            export_step_assembly,
            export_stl,
        )

        os.makedirs(export_dir, exist_ok=True)
        assembly = structure.assembly()
        export_step_assembly(assembly, os.path.join(export_dir, "wing_structure_assembly.step"))
        export_parts_step(assembly, os.path.join(export_dir, "parts"))
        for name, face in rib_flat_patterns(spec).items():
            export_profile_dxf(face, os.path.join(export_dir, "rib_flats", f"{name}.dxf"))
        for group, comp in structure.full_wing().items():
            export_stl(comp, os.path.join(export_dir, f"wing_structure_{group.replace(' ', '_')}.stl"))
    return structure
