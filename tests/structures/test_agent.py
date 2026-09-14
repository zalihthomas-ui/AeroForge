"""Tests for the Structures Agent (agents.structures.agent.CALCULIX_AVAILABLE).

Skipped entirely when ccx.exe isn't installed (e.g. CI, or any machine
without CalculiX via scripts/install_calculix_windows.sh) — see
vendor/calculix/README.md.
"""

from __future__ import annotations

import pytest

from agents.structures import (
    CALCULIX_AVAILABLE,
    StructuralResult,
    StructuresAgent,
    StructuresEvaluationError,
)

pytestmark = pytest.mark.skipif(
    not CALCULIX_AVAILABLE,
    reason="ccx.exe (CalculiX) not installed on this machine — see vendor/calculix/README.md",
)

REFERENCE_CASE = dict(length_mm=1000.0, width_mm=20.0, height_mm=10.0, force_n=100.0)


@pytest.fixture
def agent() -> StructuresAgent:
    return StructuresAgent()


def test_reference_cantilever_matches_closed_form_theory(agent: StructuresAgent) -> None:
    """1m steel cantilever, 20x10mm section, 100N tip load — hand-verified
    against closed-form Euler-Bernoulli theory (see vendor/calculix/README.md's
    Validation section). This is the strongest validation in the repo so
    far: exact theory, not an invariant or cross-validation."""
    result = agent.evaluate_cantilever_beam(**REFERENCE_CASE)

    assert isinstance(result, StructuralResult)
    assert result.analytical_deflection_mm == pytest.approx(95.238, rel=1e-3)
    assert result.tip_deflection_mm == pytest.approx(result.analytical_deflection_mm, rel=0.01)
    assert result.deflection_error_pct < 1.0


def test_max_bending_stress_is_nonzero_and_right_order_of_magnitude(agent: StructuresAgent) -> None:
    """B31 stress is reported at Gauss integration points, not the exact
    extreme fiber, so only check sign/magnitude sanity — see
    vendor/calculix/README.md's Validation section for why a tight
    tolerance isn't meaningful here."""
    result = agent.evaluate_cantilever_beam(**REFERENCE_CASE)

    assert result.max_bending_stress_mpa > 0
    assert 50.0 < result.max_bending_stress_mpa < 500.0


def test_deflection_scales_with_force(agent: StructuresAgent) -> None:
    """Linear elastic beam theory: deflection should scale linearly with load."""
    low = agent.evaluate_cantilever_beam(**{**REFERENCE_CASE, "force_n": 50.0})
    high = agent.evaluate_cantilever_beam(**{**REFERENCE_CASE, "force_n": 100.0})

    assert high.tip_deflection_mm == pytest.approx(2 * low.tip_deflection_mm, rel=0.02)


@pytest.mark.parametrize(
    "field", ["length_mm", "width_mm", "height_mm", "force_n", "youngs_modulus_mpa"]
)
def test_non_positive_inputs_are_rejected(agent: StructuresAgent, field: str) -> None:
    params = {**REFERENCE_CASE, field: 0.0}
    with pytest.raises(StructuresEvaluationError):
        agent.evaluate_cantilever_beam(**params)


@pytest.mark.parametrize("num_elements", [0, -1, 2.5])
def test_invalid_num_elements_is_rejected(agent: StructuresAgent, num_elements) -> None:
    with pytest.raises(StructuresEvaluationError):
        agent.evaluate_cantilever_beam(**REFERENCE_CASE, num_elements=num_elements)
