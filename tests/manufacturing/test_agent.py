"""Tests for the Manufacturing Agent's CNC checks: drill depth-to-diameter
ratio and real hole-to-part-edge clearance, applied to the actual
Geometry Agent bracket component. Pure geometry/arithmetic — no CalculiX
dependency, runs fast."""

from __future__ import annotations

import pytest

from agents.manufacturing import (
    CNCManufacturabilityResult,
    ManufacturabilityError,
    ManufacturingAgent,
)

REFERENCE_CASE = dict(length_mm=100.0, width_mm=80.0, thickness_mm=5.0, hole_diameter_mm=8.0, hole_count=4)


@pytest.fixture
def agent() -> ManufacturingAgent:
    return ManufacturingAgent()


def test_reference_bracket_is_manufacturable(agent: ManufacturingAgent) -> None:
    """Mission-doc reference bracket: thickness/hole_diameter = 5/8 = 0.625,
    well under the 5:1 drill limit; real edge margin (worst case: the
    outermost holes' clearance to the bracket's short ends) is 8.5mm
    against a required 1x hole_diameter = 8mm — deliberately tight but
    passing, not a trivially-satisfied check."""
    result = agent.evaluate_bracket_cnc(**REFERENCE_CASE)

    assert isinstance(result, CNCManufacturabilityResult)
    assert result.depth_to_diameter_ratio == pytest.approx(0.625)
    assert result.standard_drillable is True
    assert result.max_standard_ratio == 5.0
    assert result.hole_edge_margin_mm == pytest.approx(8.5)
    assert result.edge_margin_adequate is True
    assert result.overall_manufacturable is True


def test_thick_narrow_hole_bracket_fails_drill_ratio(agent: ManufacturingAgent) -> None:
    """A 30mm-thick plate with 4mm holes: depth/diameter = 7.5, over the
    5:1 standard limit."""
    params = {**REFERENCE_CASE, "thickness_mm": 30.0, "hole_diameter_mm": 4.0}
    result = agent.evaluate_bracket_cnc(**params)

    assert result.depth_to_diameter_ratio == pytest.approx(7.5)
    assert result.standard_drillable is False
    assert result.overall_manufacturable is False


def test_edge_margin_reports_a_real_number_not_a_duplicate_boolean(agent: ManufacturingAgent) -> None:
    """hole_edge_margin_mm must be the actual clearance distance (usable
    for e.g. deciding how much bigger a part could be shrunk), not just
    mirroring the geometric-validity pass/fail."""
    wide_margin = agent.evaluate_bracket_cnc(**{**REFERENCE_CASE, "hole_count": 1})
    narrow_margin = agent.evaluate_bracket_cnc(**REFERENCE_CASE)

    # A single centered hole has much more length-direction clearance than
    # 4 holes spread toward the ends — the margin should reflect that
    # difference numerically, not just report the same "True" for both.
    assert wide_margin.hole_edge_margin_mm > narrow_margin.hole_edge_margin_mm


def test_max_drill_ratio_and_edge_margin_ratio_are_overridable(agent: ManufacturingAgent) -> None:
    result = agent.evaluate_bracket_cnc(**REFERENCE_CASE, max_drill_ratio=0.5)

    assert result.standard_drillable is False
    assert result.max_standard_ratio == 0.5


@pytest.mark.parametrize("field", ["length_mm", "width_mm", "thickness_mm", "hole_diameter_mm"])
def test_non_positive_dimensions_are_rejected(agent: ManufacturingAgent, field: str) -> None:
    params = {**REFERENCE_CASE, field: 0.0}
    with pytest.raises(ManufacturabilityError):
        agent.evaluate_bracket_cnc(**params)


def test_hole_too_large_for_width_is_rejected(agent: ManufacturingAgent) -> None:
    """Reuses agents/geometry/validation.validate_bracket_parameters, so
    invalid geometry is rejected before any manufacturability check runs."""
    params = {**REFERENCE_CASE, "hole_diameter_mm": 79.0}
    with pytest.raises(ManufacturabilityError):
        agent.evaluate_bracket_cnc(**params)


def test_zero_holes_is_rejected() -> None:
    """Nothing to drill, so nothing for a CNC check to evaluate."""
    agent = ManufacturingAgent()
    params = {**REFERENCE_CASE, "hole_count": 0}
    with pytest.raises(ManufacturabilityError):
        agent.evaluate_bracket_cnc(**params)
