"""Tests for wing structure manufacturing: rib nesting, DXF export, BOM generation,
mass reconciliation, and cost estimation.
"""

from __future__ import annotations

import os
import tempfile

import pytest

from agents.geometry.wing_structure import (
    WingStructureSpec,
    build_wing_structure,
    rib_flat_patterns,
)
from agents.manufacturing import (
    BOMCostRates,
    BillOfMaterials,
    ManufacturingAgent,
    NestingPlan,
    StockSheetSpec,
    generate_wing_bom,
    nest_ribs,
)


@pytest.fixture
def reference_spec() -> WingStructureSpec:
    """Standard 4-bay tapered wing structure spec."""
    return WingStructureSpec(
        semispan_mm=1000.0,
        root_chord_mm=250.0,
        tip_chord_mm=150.0,
        naca="2412",
        bay_edges_mm=[0.0, 250.0, 500.0, 750.0, 1000.0],
        t_cap_mm=[2.0, 1.8, 1.5, 1.2],
        t_web_mm=[1.5, 1.5, 1.2, 1.0],
        front_spar_xc=0.20,
        rear_spar_xc=0.60,
        rib_thickness_mm=1.0,
        rib_lightening_holes=True,
        skin_thickness_mm=0.5,
        te_skin_end_xc=0.95,
    )


def test_nesting_utilisation_in_valid_range(reference_spec: WingStructureSpec) -> None:
    """Utilisation percentage must be strictly within (0, 100]."""
    plan = nest_ribs(reference_spec)
    assert isinstance(plan, NestingPlan)
    assert 0.0 < plan.overall_utilisation_percent <= 100.0
    for sheet in plan.sheets:
        assert 0.0 < sheet.utilisation_percent <= 100.0
        assert 0.0 < sheet.bounding_box_utilisation_percent <= 100.0


def test_nesting_no_two_nested_parts_overlap(reference_spec: WingStructureSpec) -> None:
    """No two nested parts on the same sheet may overlap (intersection area == 0)."""
    plan = nest_ribs(reference_spec)
    for sheet in plan.sheets:
        placements = sheet.placements
        n = len(placements)
        for i in range(n):
            for j in range(i + 1, n):
                p1, p2 = placements[i], placements[j]
                # 1. Check bounding box spacing
                bb1_x0, bb1_y0 = p1.x_mm, p1.y_mm
                bb1_x1, bb1_y1 = p1.x_mm + p1.width_mm, p1.y_mm + p1.height_mm
                bb2_x0, bb2_y0 = p2.x_mm, p2.y_mm
                bb2_x1, bb2_y1 = p2.x_mm + p2.width_mm, p2.y_mm + p2.height_mm

                # Check bounding boxes don't overlap within part spacing
                bbox_overlap = not (
                    bb1_x1 + sheet.sheet_spec.spacing_mm <= bb2_x0
                    or bb2_x1 + sheet.sheet_spec.spacing_mm <= bb1_x0
                    or bb1_y1 + sheet.sheet_spec.spacing_mm <= bb2_y0
                    or bb2_y1 + sheet.sheet_spec.spacing_mm <= bb1_y0
                )
                assert not bbox_overlap, f"Bounding boxes overlap for {p1.part_id} and {p2.part_id}"

                # 2. Geometric boolean intersection test
                inter = p1.face.intersect(p2.face)
                if inter is not None:
                    if isinstance(inter, (list, tuple)) or hasattr(inter, "__iter__"):
                        overlap_area = sum(getattr(s, "area", 0.0) for s in inter)
                    else:
                        overlap_area = getattr(inter, "area", 0.0)
                    assert overlap_area == pytest.approx(0.0, abs=1e-5), (
                        f"Non-zero geometric intersection ({overlap_area:.4f} mm2) between {p1.part_id} and {p2.part_id}"
                    )


def test_nesting_parts_inside_sheet_boundary(reference_spec: WingStructureSpec) -> None:
    """Every placed part must lie strictly inside the stock sheet boundaries with margin."""
    stock = StockSheetSpec(width_mm=1000.0, height_mm=500.0, margin_mm=5.0, spacing_mm=5.0)
    plan = nest_ribs(reference_spec, stock=stock)

    for sheet in plan.sheets:
        for p in sheet.placements:
            # Check bounding box bounds
            assert p.x_mm >= stock.margin_mm - 1e-6, f"{p.part_id} x_min < margin"
            assert p.y_mm >= stock.margin_mm - 1e-6, f"{p.part_id} y_min < margin"
            assert p.x_mm + p.width_mm <= stock.width_mm - stock.margin_mm + 1e-6, f"{p.part_id} x_max > usable width"
            assert p.y_mm + p.height_mm <= stock.height_mm - stock.margin_mm + 1e-6, f"{p.part_id} y_max > usable height"

            # Check actual face bounding box
            f_bb = p.face.bounding_box()
            assert float(f_bb.min.X) >= stock.margin_mm - 1e-6
            assert float(f_bb.min.Y) >= stock.margin_mm - 1e-6
            assert float(f_bb.max.X) <= stock.width_mm - stock.margin_mm + 1e-6
            assert float(f_bb.max.Y) <= stock.height_mm - stock.margin_mm + 1e-6


def test_cut_length_equals_sum_of_perimeters(reference_spec: WingStructureSpec) -> None:
    """Total cut length must equal the sum of outer perimeter and inner hole perimeters."""
    ribs = rib_flat_patterns(reference_spec)
    expected_single_wing_perim = sum(sum(float(w.length) for w in f.wires()) for f in ribs.values())
    expected_full_wing_perim = expected_single_wing_perim * 2.0

    plan = nest_ribs(reference_spec, both_wings=True)
    assert plan.total_cut_length_mm == pytest.approx(expected_full_wing_perim, rel=1e-6)

    # Single wing half cut length
    plan_single = nest_ribs(reference_spec, both_wings=False)
    assert plan_single.total_cut_length_mm == pytest.approx(expected_single_wing_perim, rel=1e-6)


def test_bom_mass_equals_wing_structure_mass(reference_spec: WingStructureSpec) -> None:
    """BOM total mass must match WingStructure.masses_kg() total within 0.1%."""
    structure = build_wing_structure(reference_spec)
    expected_masses = structure.masses_kg()
    expected_total_mass = sum(expected_masses.values())

    bom = generate_wing_bom(structure)
    assert isinstance(bom, BillOfMaterials)

    # Reconcile total mass
    assert bom.total_part_mass_kg == pytest.approx(expected_total_mass, rel=1e-3)

    # Reconcile group masses
    group_summary = bom.group_summary()
    for group_name, exp_mass in expected_masses.items():
        assert group_name in group_summary
        assert group_summary[group_name]["mass_kg"] == pytest.approx(exp_mass, rel=1e-3)


def test_dxf_export_creates_valid_files(reference_spec: WingStructureSpec) -> None:
    """DXF export generates non-empty files for every sheet."""
    plan = nest_ribs(reference_spec)
    with tempfile.TemporaryDirectory() as td:
        exported = plan.export_dxfs(td, prefix="test_rib_sheet_")
        assert len(exported) == plan.total_sheet_count
        for p in exported:
            assert os.path.exists(p)
            assert os.path.getsize(p) > 1000  # Non-trivial DXF size


def test_multi_sheet_nesting_on_constrained_stock(reference_spec: WingStructureSpec) -> None:
    """Small stock sheet dimensions automatically trigger multi-sheet nesting."""
    small_stock = StockSheetSpec(width_mm=300.0, height_mm=80.0, margin_mm=5.0, spacing_mm=5.0)
    plan = nest_ribs(reference_spec, stock=small_stock)

    assert plan.total_sheet_count > 1
    assert plan.total_parts_nested == 10
    for sheet in plan.sheets:
        assert len(sheet.placements) > 0
        assert sheet.utilisation_percent > 0.0


def test_oversize_part_raises_clear_error(reference_spec: WingStructureSpec) -> None:
    """A part exceeding the stock sheet dimensions raises a descriptive ValueError."""
    tiny_stock = StockSheetSpec(width_mm=100.0, height_mm=20.0)  # Rib_1 is 250x30 mm
    with pytest.raises(ValueError, match="exceeds stock sheet"):
        nest_ribs(reference_spec, stock=tiny_stock)


def test_bom_csv_and_table_generation(reference_spec: WingStructureSpec) -> None:
    """BOM exports well-formed CSV and Markdown summary tables."""
    bom = generate_wing_bom(reference_spec)
    csv_text = bom.to_csv()
    lines = csv_text.strip().splitlines()

    assert len(lines) == len(bom.items) + 1  # header + items
    assert "Part Name,Group,Material" in lines[0]

    md_table = bom.summary_table()
    assert "| Component Group |" in md_table
    assert "**TOTAL / WING**" in md_table
    assert f"{bom.total_part_mass_kg:.3f}" in md_table


def test_manufacturing_agent_integration(reference_spec: WingStructureSpec) -> None:
    """ManufacturingAgent provides end-to-end evaluation entry point."""
    agent = ManufacturingAgent()
    eval_result = agent.evaluate_wing_manufacturing(reference_spec)

    assert eval_result.nesting_plan.total_parts_nested == 10
    assert eval_result.bom.total_part_mass_kg > 0.0
    assert eval_result.bom.total_cost_eur > 0.0
