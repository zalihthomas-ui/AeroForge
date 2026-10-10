"""v0.16 detail design: joints closed form, stiffened panels, close-up CalculiX checks, detailed CAD."""

import math

import numpy as np
import pytest

from agents.structures.joints import (
    design_bond,
    design_rivet_line,
    inter_rivet_stress_mpa,
    kt_double_semicircular_notch,
    kt_open_hole_heywood,
    rivet_allowables,
    volkersen,
)
from agents.structures.stiffened_panel import (
    AngleStringer,
    column_stress_mpa,
    crippling_mpa,
    design_panel,
)
from agents.structures.wing_box import MATERIALS, _plate_coefficient

AL = MATERIALS["al6061-t6"]
KP = _plate_coefficient(AL)


def test_volkersen_equilibrium_and_closed_form_peak():
    x, tau = volkersen(50.0, 20.0, 68900, 0.4, 68900, 0.4)
    assert np.trapezoid(tau, x) == pytest.approx(50.0, rel=1e-3)  # adhesive carries the whole load
    assert tau[0] == pytest.approx(tau[-1])  # balanced adherends: symmetric peaks
    om = math.sqrt(700 / 0.2 * 2 / (68900 * 0.4))
    assert tau[0] == pytest.approx(50.0 * om / 2 / math.tanh(om * 10.0), rel=1e-6)  # (P w / 2) coth(w L / 2)
    _, tau_u = volkersen(50.0, 20.0, 68900, 0.3, 68900, 0.6)
    assert tau_u[0] > tau_u[-1]  # the softer adherend's loaded end peaks
    # long overlaps stop helping (elastic trough): 40 mm is no better than 20 mm
    assert design_bond(50, 68900, 0.4, 68900, 0.4, 40).tau_max_mpa == pytest.approx(
        design_bond(50, 68900, 0.4, 68900, 0.4, 20).tau_max_mpa, rel=0.02)


def test_stress_concentration_handbook_limits():
    assert kt_open_hole_heywood(0.0) == 3.0  # Kirsch
    assert kt_open_hole_heywood(0.5) == pytest.approx(2.125)
    assert kt_double_semicircular_notch(0.0) == pytest.approx(3.065)
    assert kt_double_semicircular_notch(1.0) == pytest.approx(1.0, abs=0.01)


def test_rivet_line_margins_and_pitch_rules():
    rv = design_rivet_line(400.0, 120.0, 27.0, 80.0, 0.3, 0.3, 0.5, 65.0, AL)
    assert all(m >= 0 for m in rv.margins.values())
    assert 4 * rv.diameter_mm <= rv.pitch_mm <= 8 * rv.diameter_mm
    ps, pb = rivet_allowables(rv.diameter_mm, 0.3, AL)
    assert rv.rivet_load_n <= min(ps, pb)
    assert inter_rivet_stress_mpa(0.5, rv.pitch_mm, AL) >= 65.0
    assert rv.flange_width_mm >= 4 * rv.diameter_mm  # 2D edge distance each side


def test_stiffened_panel_closed_form_pieces():
    st = AngleStringer(8.0, 0.4)
    assert st.area_mm2 == pytest.approx((16 - 0.4) * 0.4)
    assert crippling_mpa(st, AL) <= AL.fty_mpa
    col, se, scc = column_stress_mpa(st, 0.5, 30.0, 150.0, AL)
    assert col <= min(se, scc) + 1e-9
    # long column -> Euler; Johnson only near crippling
    col_long, se_long, _ = column_stress_mpa(st, 0.5, 30.0, 2000.0, AL)
    assert col_long == pytest.approx(se_long)


def test_stringers_beat_unstiffened_cover_and_n0_is_plain_plate():
    best, per_n = design_panel(122.0, 27.7, 0.3, 1.5 * 240.0, 1.5, 150.0, AL)
    plain = next(p for p in per_n if p.n_stringers == 0)
    assert best.area_mm2 < 0.7 * plain.area_mm2
    # n = 0 is the v0.14 unstiffened cover: buckling with k = 4 over the full width governs
    assert plain.margins["skin buckling"] == pytest.approx(min(plain.margins.values()))
    assert 4 * KP * (plain.skin_t_mm / 122.0) ** 2 >= plain.stress_ult_mpa
    assert all(m >= 0 for m in best.margins.values())


def test_detailed_structure_cad():
    from agents.geometry.wing_structure import (
        StructureDetails,
        WingStructureSpec,
        build_wing_structure,
    )

    det = StructureDetails([2, 1], [8.0, 8.0], [0.4, 0.4], rivet_pitch_mm=20.0, rivet_diameter_mm=1.6)
    spec = WingStructureSpec(300.0, 240.0, 200.0, "4412", [0.0, 150.0, 300.0], [0.5, 0.4], [0.3, 0.3],
                             rib_thickness_mm=0.5, n_profile=21, details=det)
    ws = build_wing_structure(spec)
    n = {g: len(p) for g, p in ws.parts.items()}
    assert n["stringers"] == 2 * (2 + 1)  # upper + lower per stringer per bay
    assert n["spar flanges"] == 2 * 2 * 2
    assert n["ribs"] == 3
    flange_rivets = 4 * len(np.arange(10.0, 300.0, 20.0))
    n_rivets = sum(len(p.solids()) for p in ws.parts["fasteners"])
    assert n_rivets == flange_rivets + 2 * n["stringers"]  # + anti-peel rivet at each stringer end
    assert n["fasteners"] == 4 + 2 * 2  # one leaf per rivet row + one per bay and surface (O(n) assembly)
    assert len(ws.parts["ribs"][0].solids()) == 3  # split at both spar webs (nose / box / tail rib)
    assert all(p.is_valid and p.volume > 0 for ps in ws.parts.values() for p in ps)
    # stringer volume = area x length (land + leg), within lofting error
    st = ws.parts["stringers"][0]
    length = 150.0 - 0.5 - 2.0
    assert st.volume == pytest.approx(AngleStringer(8.0, 0.4).area_mm2 * length, rel=0.03)


def test_swept_structure_sections_follow_the_leading_edge():
    from agents.geometry.wing_structure import WingStructureSpec, build_wing_structure

    spec = WingStructureSpec(260.0, 200.0, 120.0, "0010", [0.0, 130.0, 260.0], [0.3, 0.3], [0.3, 0.3],
                             front_spar_xc=0.15, rear_spar_xc=0.60, te_skin_end_xc=0.645, n_profile=15,
                             sweep_le_deg=25.0)
    ws = build_wing_structure(spec)
    tip = ws.parts["ribs"][-1].bounding_box()
    assert tip.min.X == pytest.approx(260.0 * math.tan(math.radians(25.0)), abs=0.5)


# ---------------------------------------------------------------- close-up CalculiX


def _ccx():
    from agents.structures.agent import CALCULIX_AVAILABLE

    if not CALCULIX_AVAILABLE:
        pytest.skip("CalculiX not available")


def test_closeup_kt_models_match_handbooks():
    _ccx()
    from agents.structures.detail_fe import (
        edge_notch_kt,
        hole_in_shear_kt,
        open_hole_kt,
    )

    hole = open_hole_kt(12.5, 1.7, 0.5)
    assert hole.kt_fe == pytest.approx(hole.kt_ref, rel=0.03)
    notch = edge_notch_kt(40.0, 2.0, 0.5)
    assert notch.kt_fe == pytest.approx(notch.kt_ref, rel=0.03)
    shear = hole_in_shear_kt(400.0, 10.0)
    assert shear.kt_fe == pytest.approx(4.0, rel=0.03)


def test_bonded_lap_fe_vs_volkersen_and_peel():
    _ccx()
    from agents.structures.detail_fe import bonded_lap

    sup = bonded_lap(50.0, 10.0, 0.5, 0.78)
    assert np.trapezoid(sup.tau_mpa, sup.x_mm) == pytest.approx(50.0, rel=0.02)
    assert sup.tau_max_fe == pytest.approx(sup.tau_max_ref, rel=0.12)  # Volkersen ignores adherend shear
    free = bonded_lap(50.0, 10.0, 0.5, 0.78, supported=False)
    assert free.tau_max_fe > sup.tau_max_fe and free.peel_max_fe > 3 * sup.peel_max_fe  # single-lap bending


def test_buckling_factors_below_one_are_reported():
    """Regression: this ccx build's *BUCKLE only lists factors > 1; the reference-load scaling must catch 0.54."""
    _ccx()
    from agents.structures.detail_fe import stiffened_panel_buckling

    w, L, t = 121.96, 150.0, 1.4
    a = L / w
    k = min((m / a + a / m) ** 2 for m in range(1, 5))
    sigma_cr = k * KP * (t / w) ** 2
    r = stiffened_panel_buckling(L, w, t, 0, 8.0, 0.4, 64.4)
    assert r.first == pytest.approx(sigma_cr / 64.4, rel=0.02)
    assert r.first < 1.0


def test_shear_web_plain_and_flanged_holes():
    _ccx()
    from agents.structures.detail_fe import shear_web_buckling

    w, h, t, tau = 122.0, 26.8, 0.5, 9.0
    ks = 5.35 + 4 * (h / w) ** 2
    plain = shear_web_buckling(w, h, t, tau_ref_mpa=tau)
    assert plain.first == pytest.approx(ks * KP * (t / h) ** 2 / tau, rel=0.02)
    holes = [(0.3 * w, h / 2, 5.4), (0.7 * w, h / 2, 5.4)]
    plain_holes = shear_web_buckling(w, h, t, holes, tau_ref_mpa=tau)
    flanged = shear_web_buckling(w, h, t, holes, lip_mm=2.5, tau_ref_mpa=tau)
    assert plain_holes.first < 0.8 * plain.first  # holes cost buckling strength
    assert flanged.first > plain_holes.first * 1.4  # flanging restores it


def test_stiffened_panel_fe_brackets_closed_form():
    _ccx()
    from agents.structures.detail_fe import stiffened_panel_buckling

    st = AngleStringer(8.0, 0.4)
    w, L, t, n, s = 121.96, 150.0, 0.5, 3, 64.4
    skin = 4 * KP * (t / (w / (n + 1))) ** 2 / s
    col = column_stress_mpa(st, t, w / (n + 1), L, AL)[0] / s
    fe = stiffened_panel_buckling(L, w, t, n, st.leg_mm, st.t_mm, s)
    # skin-buckling estimate (k = 4 on the stringer pitch) is conservative; FE within the column estimate
    assert skin <= fe.first <= col * 1.05


def test_mirrored_multi_solid_leaves_keep_their_volume():
    """Regression: a rivet-row compound mirrored in one go had zero GProp volume (NaN inertia downstream)."""
    from agents.geometry.wing_structure import (
        StructureDetails,
        WingStructureSpec,
        build_wing_structure,
    )

    det = StructureDetails([1], [8.0], [0.4], rivet_pitch_mm=25.0, rivet_diameter_mm=1.6)
    spec = WingStructureSpec(150.0, 240.0, 220.0, "4412", [0.0, 150.0], [0.5], [0.3], rib_thickness_mm=0.5,
                             n_profile=15, details=det)
    full = build_wing_structure(spec).full_wing()
    for grp in ("Fasteners", "RibFlanges"):
        g = next(v for v in full.values() if v.label == grp)
        stbd = sum(c.volume for c in g.children if c.label.endswith("_Stbd"))
        port = sum(c.volume for c in g.children if c.label.endswith("_Port"))
        assert stbd > 0 and port == pytest.approx(stbd, rel=1e-6)
