"""v0.14 structural campaign: modelling implications, sizing closure, FE verification."""

import pytest

from agents.structures.agent import CALCULIX_AVAILABLE
from engineering.analysis.wing_campaign import (
    CampaignRequirement,
    build_structure_cad,
    fe_vs_closed_form,
    margins_from_fe,
    run_campaign,
)


@pytest.fixture(scope="module")
def closed_form_result():
    return run_campaign(CampaignRequirement(), run_fe=False)


def test_3d_correction_exposes_old_2d_sizing(closed_form_result):
    c = closed_form_result.comparison
    weight = 12.0 * 9.81
    # the v0.8-v0.13 2D sizing closes lift = weight by construction ...
    assert c.old_lift_2d_n == pytest.approx(weight)
    # ... but the same wing makes far less lift once downwash is accounted for
    assert c.old_lift_3d_n < 0.8 * weight
    # and the same airfoil would need an aspect ratio outside lifting-line validity
    assert c.same_airfoil_3d_aspect_ratio < 4.0


def test_selected_wing_closes_lift_in_3d(closed_form_result):
    a = closed_form_result.aero
    assert a.valid_lifting_line
    assert a.lift_n == pytest.approx(12.0 * 9.81, rel=1e-3)
    assert a.naca == "4412"


def test_box_is_sized_to_ultimate_with_non_negative_margins(closed_form_result):
    r = closed_form_result
    assert r.envelope.n_ultimate == pytest.approx(1.5 * r.envelope.n_limit)
    assert r.sizing.margins.passes
    assert 0.2 < r.sizing.mass_kg < 3.0
    assert r.sizing.ultimate.tip_deflection_mm == pytest.approx(1.5 * r.sizing.limit.tip_deflection_mm, rel=1e-9)


@pytest.mark.skipif(not CALCULIX_AVAILABLE, reason="CalculiX (ccx) not installed")
def test_fe_verifies_the_sized_box(tmp_path):
    r = run_campaign(CampaignRequirement(), run_fe=True, work_dir=str(tmp_path))
    cmp = fe_vs_closed_form(r)
    assert r.fe.equilibrium_error_pct < 1e-4
    assert abs(cmp["tip_deflection_diff_pct"]) < 5.0
    assert cmp["max_cover_stress_diff_pct_mid_bay"] < 3.0
    assert abs(cmp["first_bending_freq_diff_pct"]) < 5.0
    assert 1.0 <= cmp["buckling_fe_over_ss_plate"] <= 6.97 / 4.0
    assert all(v >= 0.0 for v in margins_from_fe(r).values())


def test_structure_cad_export_writes_named_assembly_parts_and_rib_flats(closed_form_result, tmp_path):
    structure = build_structure_cad(closed_form_result, export_dir=str(tmp_path), n_profile=21)
    step = (tmp_path / "wing_structure_assembly.step").read_text(encoding="latin-1")
    assert "PRODUCT('Wing'" in step and "PRODUCT('Rib_1_Stbd'" in step and "COLOUR_RGB" in step
    n_solids = 2 * sum(len(ps) for ps in structure.parts.values())
    assert len(list((tmp_path / "parts").glob("*.step"))) == n_solids
    assert len(list((tmp_path / "rib_flats").glob("Rib_*.dxf"))) == len(structure.spec.bay_edges_mm)
