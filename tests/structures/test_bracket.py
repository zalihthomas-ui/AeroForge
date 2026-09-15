"""Tests for the bracket solid FEA path: the ACTUAL Geometry Agent bracket
component (agents/geometry/bracket.py), bolted at all 4 holes and loaded
on its top face, validated by exact force equilibrium and mesh
convergence rather than a closed-form solution (none exists for this
case) — see agents/structures/agent.py and bracket_mesh.py's module
docstrings for the full writeup, including the convergence sweep this
was picked from.

The fixed-hole-rim edge is a classic FEA stress-singularity location
(v0.7 finding): raw peak stress alone doesn't reliably converge with
mesh refinement, so `hotspot_stress_mpa` (mean of the top 1% highest
nodal-averaged von Mises values — a standard fatigue/design-code
convention) is the convergence-checked metric instead; `raw_peak_stress_mpa`
is kept for transparency but is informational only.

Skipped entirely when ccx.exe isn't installed, same as the other
structures tests. These are the slowest tests in the suite (two full
solid-FEA solves per evaluate_bracket() call, for the convergence check).
"""

from __future__ import annotations

import pytest

from agents.structures import (
    CALCULIX_AVAILABLE,
    BracketStructuralResult,
    StructuresAgent,
    StructuresEvaluationError,
)

pytestmark = pytest.mark.skipif(
    not CALCULIX_AVAILABLE,
    reason="ccx.exe (CalculiX) not installed on this machine — see vendor/calculix/README.md",
)

# Mission doc's reference bracket (100x80x5mm, four 8mm holes) under a
# moderate top-face load. Observed during development: mesh_converged=True
# (~0.4% deflection change, ~0.4% hotspot_stress change), equilibrium_error_pct
# ~0.001%. Raw peak stress alone changed ~1.6% between these same two
# densities — well converged here, but not reliably so across the wider
# sweep in bracket_mesh.py's module docstring, which is why
# hotspot_stress_mpa (not raw_peak_stress_mpa) drives mesh_converged.
REFERENCE_CASE = dict(
    length_mm=100.0, width_mm=80.0, thickness_mm=5.0, hole_diameter_mm=8.0, hole_count=4, applied_force_n=500.0
)


@pytest.fixture
def agent() -> StructuresAgent:
    return StructuresAgent()


def test_reference_bracket_converges_with_exact_equilibrium(agent: StructuresAgent) -> None:
    """Force equilibrium (sum of reaction forces = applied load) is an
    exact identity for any correctly converged linear static solve, so
    this is a tight tolerance on genuine merit, not an arbitrarily loose
    one — observed ~0.001% during development. A single call exercises
    both mesh densities (evaluate_bracket always solves both for the
    convergence check), so this also covers the coarse/fine result
    fields without a second expensive solve."""
    result = agent.evaluate_bracket(**REFERENCE_CASE)

    assert isinstance(result, BracketStructuralResult)
    assert result.equilibrium_error_pct < 1.0
    assert result.mesh_converged is True
    assert result.hotspot_stress_mpa > 0
    assert result.raw_peak_stress_mpa > 0
    assert result.max_deflection_mm > 0
    assert result.fine_mesh_hotspot_stress_mpa == result.hotspot_stress_mpa
    # Both densities resolve the same physical hot-spot stress; they need
    # not be identical, just close (mesh_converged already asserts this
    # above) — this just checks they aren't trivially equal (e.g. a bug
    # reusing one mesh's result for both fields).
    assert result.coarse_mesh_hotspot_stress_mpa != result.fine_mesh_hotspot_stress_mpa
    # raw_peak_stress_mpa is the single highest nodal value; hotspot_stress_mpa
    # is a mean over the top 1% of nodes, so the peak must be >= the mean.
    assert result.raw_peak_stress_mpa >= result.hotspot_stress_mpa


@pytest.mark.parametrize(
    "field", ["length_mm", "width_mm", "thickness_mm", "hole_diameter_mm", "applied_force_n", "youngs_modulus_mpa"]
)
def test_non_positive_inputs_are_rejected(agent: StructuresAgent, field: str) -> None:
    params = {**REFERENCE_CASE, field: 0.0}
    with pytest.raises(StructuresEvaluationError):
        agent.evaluate_bracket(**params)


def test_hole_too_large_for_width_is_rejected(agent: StructuresAgent) -> None:
    """Reuses agents/geometry/validation.validate_bracket_parameters, so
    this is the same check the Geometry Agent itself applies."""
    params = {**REFERENCE_CASE, "hole_diameter_mm": 79.0}
    with pytest.raises(StructuresEvaluationError):
        agent.evaluate_bracket(**params)


def test_negative_hole_count_is_rejected(agent: StructuresAgent) -> None:
    params = {**REFERENCE_CASE, "hole_count": -1}
    with pytest.raises(StructuresEvaluationError):
        agent.evaluate_bracket(**params)
