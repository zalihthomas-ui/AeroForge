"""Tests for the plate-with-hole solid FEA path (gmsh C3D10 mesh -> real
CalculiX), validated against Kirsch's classical stress concentration
solution (Kt=3.0 for a small hole in a wide plate under uniaxial tension).

Skipped entirely when ccx.exe isn't installed, same as test_agent.py.
These are slower than the beam tests (real 3D meshing + solid FEA, tens of
seconds per case rather than milliseconds) since they're proving the
mesh -> solid-FEA pipeline itself, not just the beam path.
"""

from __future__ import annotations

import pytest

from agents.structures import (
    CALCULIX_AVAILABLE,
    PlateWithHoleResult,
    StructuresAgent,
    StructuresEvaluationError,
)

pytestmark = pytest.mark.skipif(
    not CALCULIX_AVAILABLE,
    reason="ccx.exe (CalculiX) not installed on this machine — see vendor/calculix/README.md",
)

# A 5%-of-width hole, well inside the small-hole limit Kirsch's Kt=3.0
# requires. Observed error on this exact case during development: ~0.4%.
REFERENCE_CASE = dict(width_mm=200.0, height_mm=200.0, thickness_mm=5.0, hole_diameter_mm=10.0, tensile_stress_mpa=100.0)


@pytest.fixture
def agent() -> StructuresAgent:
    return StructuresAgent()


def test_reference_plate_converges_to_kirsch_kt(agent: StructuresAgent) -> None:
    """Kirsch's Kt=3.0 is one of the most well-established results in
    classical elasticity. A tolerance of 5% is generous relative to the
    ~0.4% actually observed during development (see module docstring) —
    it's set loosely to stay robust to gmsh mesh nondeterminism across
    machines/versions rather than to hide a marginal result."""
    result = agent.evaluate_plate_with_hole(**REFERENCE_CASE)

    assert isinstance(result, PlateWithHoleResult)
    assert result.theoretical_kt == 3.0
    assert result.nominal_stress_mpa == REFERENCE_CASE["tensile_stress_mpa"]
    assert result.stress_concentration_factor == pytest.approx(3.0, abs=0.15)
    assert result.error_pct < 5.0


def test_max_stress_is_consistent_with_reported_kt(agent: StructuresAgent) -> None:
    result = agent.evaluate_plate_with_hole(**REFERENCE_CASE)

    assert result.max_stress_mpa > result.nominal_stress_mpa
    assert result.max_stress_mpa == pytest.approx(
        result.stress_concentration_factor * result.nominal_stress_mpa, rel=1e-6
    )


def test_hole_too_large_relative_to_width_is_rejected(agent: StructuresAgent) -> None:
    params = {**REFERENCE_CASE, "hole_diameter_mm": 0.5 * REFERENCE_CASE["width_mm"]}
    with pytest.raises(StructuresEvaluationError, match="small-hole/infinite-plate"):
        agent.evaluate_plate_with_hole(**params)


def test_hole_just_over_the_ratio_limit_is_rejected(agent: StructuresAgent) -> None:
    width = REFERENCE_CASE["width_mm"]
    just_over = {**REFERENCE_CASE, "hole_diameter_mm": 0.1 * width + 0.5}
    with pytest.raises(StructuresEvaluationError):
        agent.evaluate_plate_with_hole(**just_over)


@pytest.mark.parametrize(
    "field", ["width_mm", "height_mm", "thickness_mm", "hole_diameter_mm", "tensile_stress_mpa", "youngs_modulus_mpa"]
)
def test_non_positive_inputs_are_rejected(agent: StructuresAgent, field: str) -> None:
    params = {**REFERENCE_CASE, field: 0.0}
    with pytest.raises(StructuresEvaluationError):
        agent.evaluate_plate_with_hole(**params)
