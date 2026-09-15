"""Unit tests for closed-loop wing aerodynamic optimization."""

import pytest
from engineering.analysis.wing_aero import WingAeroError
from engineering.analysis.wing_optimizer import (
    AirfoilCandidateResult,
    WingOptimizationResult,
    optimize_wing_for_max_l_over_d,
)
from engineering.requirements.schema import EngineeringSpec


def _wing_spec() -> EngineeringSpec:
    return EngineeringSpec(
        component="wing",
        parameters={
            "wing_span": 1800.0,
            "root_chord": 240.0,
            "tip_chord": 140.0,
            "sweep": 12.0,
            "dihedral": 4.0,
            "naca_airfoil": 12.0,
        },
    )


def test_reference_wing_optimization():
    """Default multi-candidate optimization converges to a non-edge optimum."""
    spec = _wing_spec()
    bounds = (-2.0, 12.0)
    res = optimize_wing_for_max_l_over_d(
        spec,
        alpha_bounds_deg=bounds,
        cruise_velocity_mps=25.0,
    )

    assert isinstance(res, WingOptimizationResult)
    assert res.optimal_naca_airfoil in ["0009", "0012", "2412", "4412", "2415"]

    # Optimum is strictly inside the bounds (not stuck at an edge)
    assert bounds[0] < res.optimal_alpha_deg < bounds[1]
    assert res.max_l_over_d > 50.0
    assert res.cl_at_optimum > 0.0
    assert res.cd_at_optimum > 0.0

    # All 5 candidates are recorded for transparency
    assert len(res.all_candidates) == 5
    airfoil_names = [c.naca_airfoil for c in res.all_candidates]
    assert airfoil_names == ["0009", "0012", "2412", "4412", "2415"]

    for cand in res.all_candidates:
        assert isinstance(cand, AirfoilCandidateResult)
        assert bounds[0] < cand.optimal_alpha_deg < bounds[1]
        assert cand.max_l_over_d > 0.0
        assert cand.cl_at_optimum > 0.0
        assert cand.cd_at_optimum > 0.0


def test_cambered_airfoils_differ_from_symmetric():
    """Cambered sections (2412, 4412) achieve higher L/D than symmetric sections (0009, 0012)."""
    spec = _wing_spec()
    res = optimize_wing_for_max_l_over_d(spec)

    cand_map = {c.naca_airfoil: c for c in res.all_candidates}
    assert cand_map["2412"].max_l_over_d > cand_map["0012"].max_l_over_d
    assert cand_map["4412"].max_l_over_d > cand_map["0012"].max_l_over_d
    assert cand_map["0012"].max_l_over_d > cand_map["0009"].max_l_over_d


def test_custom_candidates_and_alpha_bounds():
    """Custom candidate airfoils and restricted bounds are respected."""
    spec = _wing_spec()
    bounds = (0.0, 8.0)
    res = optimize_wing_for_max_l_over_d(
        spec,
        candidate_naca_airfoils=["0012", "2412"],
        alpha_bounds_deg=bounds,
    )

    assert len(res.all_candidates) == 2
    assert bounds[0] < res.optimal_alpha_deg < bounds[1]
    assert res.optimal_naca_airfoil == "2412"


def test_reject_non_wing_spec():
    """Non-wing components must raise WingAeroError."""
    bracket_spec = EngineeringSpec(
        component="bracket",
        parameters={"length": 100.0, "width": 80.0, "thickness": 5.0},
    )
    with pytest.raises(WingAeroError) as exc:
        optimize_wing_for_max_l_over_d(bracket_spec)
    assert "component='wing'" in str(exc.value)


def test_reject_empty_candidates():
    """Empty candidate airfoil list must raise WingAeroError."""
    spec = _wing_spec()
    with pytest.raises(WingAeroError):
        optimize_wing_for_max_l_over_d(spec, candidate_naca_airfoils=[])


def test_reject_invalid_alpha_bounds():
    """Degenerate or inverted alpha bounds must raise WingAeroError."""
    spec = _wing_spec()
    with pytest.raises(WingAeroError):
        optimize_wing_for_max_l_over_d(spec, alpha_bounds_deg=(8.0, 2.0))
    with pytest.raises(WingAeroError):
        optimize_wing_for_max_l_over_d(spec, alpha_bounds_deg=(5.0, 5.0))


def test_reject_invalid_naca_code_in_candidates():
    """Malformed candidate codes must raise WingAeroError."""
    spec = _wing_spec()
    with pytest.raises(WingAeroError):
        optimize_wing_for_max_l_over_d(spec, candidate_naca_airfoils=["invalid_code"])
