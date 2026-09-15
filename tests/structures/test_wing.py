"""Tests for the wing solid FEA path: the ACTUAL Geometry Agent wing
component (agents/geometry/wing.py — real NACA airfoil cross-sections),
loaded by its own computed lift (engineering.analysis.wing_aero)
distributed elliptically (Prandtl lifting-line) across the span, bolted
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

from agents.geometry.wing import build_wing
from agents.structures import (
    CALCULIX_AVAILABLE,
    StructuresAgent,
    StructuresEvaluationError,
    WingStructuralResult,
)
from agents.structures.wing_mesh import build_half_wing, mesh_half_wing
from cad.exporters import export_step
from engineering.requirements.schema import EngineeringSpec

pytestmark = pytest.mark.skipif(
    not CALCULIX_AVAILABLE,
    reason="ccx.exe (CalculiX) not installed on this machine — see vendor/calculix/README.md",
)

# Mission doc's reference wing (1800mm span, 240/140mm root/tip chord,
# 12deg sweep, 4deg dihedral, NACA 0012) at a standard cruise condition.
# Observed during development (v0.11, elliptical load): mesh_converged=True
# (well under 1% change in both deflection and hotspot_stress across a
# 3-point density check), equilibrium_error_pct ~0.0001-0.0005%,
# safety_factor ~350 (a lightly loaded 1g cruise condition, nowhere near
# the wing's allowable stress — not a red flag, see agent.py's docstring).
# hotspot_stress_mpa ~0.79 MPa and max_deflection_mm ~0.25mm — both LOWER
# than v0.10's uniform-load numbers (~0.95 MPa / ~0.34mm): concentrating
# more lift near the root shortens its average moment arm to the fixed
# root, reducing bending demand there despite carrying the same total
# load — see agent.py's docstring for the verified explanation.
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


def test_elliptical_load_sums_to_the_applied_lift_and_favors_the_root(
    agent: StructuresAgent, tmp_path
) -> None:
    """Doesn't need a full ccx solve — builds the same mesh and .inp deck
    evaluate_wing does, then checks the *CLOAD block directly: (1) the
    normalization guarantees the total still sums to exactly the applied
    half-lift, the equilibrium-preservation property the per-node
    weighting is supposed to guarantee regardless of node distribution;
    (2) root-adjacent nodes carry more load than tip-adjacent nodes,
    proving the distribution is actually elliptical-shaped and not
    accidentally still uniform."""
    wing_span = 1800.0
    root_chord = 240.0
    half_span = wing_span / 2
    lift_n_half = 40.0  # arbitrary, round number for easy verification

    part = build_wing({})
    half_wing = build_half_wing(part, half_span, root_chord)
    step_path = tmp_path / "wing.step"
    export_step(half_wing, str(step_path))
    mesh = mesh_half_wing(str(step_path), half_span, root_chord, density_factor=1.0)

    deck = agent._build_wing_input_deck(mesh, 68900.0, 0.33, lift_n_half, half_span)

    lines = deck.splitlines()
    cload_start = lines.index("*CLOAD") + 1
    node_forces: dict[int, float] = {}
    i = cload_start
    while i < len(lines) and not lines[i].startswith("*"):
        node_id_str, _direction, force_str = lines[i].split(",")
        node_forces[int(node_id_str)] = float(force_str)
        i += 1

    assert sum(node_forces.values()) == pytest.approx(lift_n_half, rel=1e-6)

    y_by_node = dict(zip(mesh.top_surface_node_ids, mesh.top_surface_y_mm))
    root_forces = [f for node_id, f in node_forces.items() if y_by_node[node_id] < half_span * 0.1]
    tip_forces = [f for node_id, f in node_forces.items() if y_by_node[node_id] > half_span * 0.9]
    assert root_forces and tip_forces
    assert (sum(root_forces) / len(root_forces)) > (sum(tip_forces) / len(tip_forces))
