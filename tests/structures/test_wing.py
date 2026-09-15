"""Tests for the wing solid FEA path: the ACTUAL Geometry Agent wing
component (agents/geometry/wing.py — real NACA airfoil cross-sections),
loaded by its own computed lift (engineering.analysis.wing_aero), bolted
via a symmetry-plane BC at the root, validated by exact force equilibrium
and mesh convergence — no closed-form solution exists for this case,
same situation as the bracket. See agents/structures/agent.py and
wing_mesh.py's module docstrings for the full writeup, including the
trailing-edge meshing finding and the mesh convergence sweep this was
picked from.

Skipped entirely when ccx.exe isn't installed, same as the other
structures tests.
"""

from __future__ import annotations

import pytest

from agents.structures import (
    CALCULIX_AVAILABLE,
    StructuresAgent,
    StructuresEvaluationError,
    WingStructuralResult,
)
from engineering.requirements.schema import EngineeringSpec

pytestmark = pytest.mark.skipif(
    not CALCULIX_AVAILABLE,
    reason="ccx.exe (CalculiX) not installed on this machine — see vendor/calculix/README.md",
)

# Mission doc's reference wing (1800mm span, 240/140mm root/tip chord,
# 12deg sweep, 4deg dihedral, NACA 0012) at a standard cruise condition.
# Observed during development: mesh_converged=True (well under 1% change
# in both deflection and hotspot_stress), equilibrium_error_pct ~0.005%,
# safety_factor ~290 (a lightly loaded 1g cruise condition, nowhere near
# the wing's allowable stress — not a red flag, see agent.py's docstring).
REFERENCE_SPEC = EngineeringSpec(component="wing", parameters={})


@pytest.fixture
def agent() -> StructuresAgent:
    return StructuresAgent()


def test_reference_wing_converges_with_exact_equilibrium(agent: StructuresAgent) -> None:
    """Force equilibrium (sum of reaction forces = applied lift) is an
    exact identity for any correctly converged linear static solve, same
    tight tolerance rationale as the bracket's equivalent test."""
    result = agent.evaluate_wing(REFERENCE_SPEC)

    assert isinstance(result, WingStructuralResult)
    assert result.equilibrium_error_pct < 1.0
    assert result.mesh_converged is True
    assert result.hotspot_stress_mpa > 0
    assert result.raw_peak_stress_mpa > 0
    assert result.max_deflection_mm > 0
    assert result.safety_factor > 1.0
    assert result.fine_mesh_hotspot_stress_mpa == result.hotspot_stress_mpa
    assert result.coarse_mesh_hotspot_stress_mpa != result.fine_mesh_hotspot_stress_mpa
    # raw_peak_stress_mpa is the single highest nodal value; hotspot_stress_mpa
    # is a mean over the top 1% of nodes, so the peak must be >= the mean.
    assert result.raw_peak_stress_mpa >= result.hotspot_stress_mpa


def test_deflection_is_physically_plausible_for_a_slender_wing(agent: StructuresAgent) -> None:
    """A sanity bound, not a precise target: a 900mm aluminum half-wing
    under a light cruise lift load should deflect a small fraction of a
    millimeter, not meters or nanometers."""
    result = agent.evaluate_wing(REFERENCE_SPEC)

    assert 0.0001 < result.max_deflection_mm < 50.0


def test_wrong_component_is_rejected(agent: StructuresAgent) -> None:
    spec = EngineeringSpec(component="bracket", parameters={})
    with pytest.raises(StructuresEvaluationError, match="component"):
        agent.evaluate_wing(spec)


def test_invalid_wing_geometry_is_rejected(agent: StructuresAgent) -> None:
    """Reuses agents/geometry/validation.validate_wing_parameters, so
    invalid geometry is rejected before any meshing/solving."""
    spec = EngineeringSpec(component="wing", parameters={"wing_span": -100.0})
    with pytest.raises(StructuresEvaluationError):
        agent.evaluate_wing(spec)


def test_non_positive_material_properties_are_rejected(agent: StructuresAgent) -> None:
    with pytest.raises(StructuresEvaluationError):
        agent.evaluate_wing(REFERENCE_SPEC, youngs_modulus_mpa=0.0)
    with pytest.raises(StructuresEvaluationError):
        agent.evaluate_wing(REFERENCE_SPEC, allowable_stress_mpa=-1.0)


def test_invalid_flight_condition_is_rejected(agent: StructuresAgent) -> None:
    """Invalid cruise conditions surface through evaluate_wing_aero and
    are wrapped as StructuresEvaluationError for a consistent contract."""
    with pytest.raises(StructuresEvaluationError):
        agent.evaluate_wing(REFERENCE_SPEC, cruise_velocity_mps=-5.0)
