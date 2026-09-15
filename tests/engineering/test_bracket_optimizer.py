"""Unit tests for bracket thickness optimization (engineering.analysis.bracket_optimizer).

Tests:
1. Mass calculation against analytical geometry.
2. Input validation and early parameter rejection.
3. Infeasible and invalid thickness bounds raising informative errors.
4. Physical monotonicity verification.
5. Algorithmic convergence and transparent evaluation logging with mock agent.
6. Real CalculiX 3D solid FEA optimization (gated by CALCULIX_AVAILABLE).
"""

from __future__ import annotations

import math
from unittest.mock import MagicMock
import pytest

from agents.structures import CALCULIX_AVAILABLE, BracketStructuralResult, StructuresAgent
from engineering.analysis.bracket_optimizer import (
    BracketDesignPoint,
    BracketOptimizationResult,
    BracketOptimizerError,
    calculate_bracket_mass,
    optimize_bracket_thickness_for_min_mass,
)


def test_calculate_bracket_mass_matches_analytical_geometry() -> None:
    """Validate mass calculation against exact analytical formula:
    Plate volume = 100 x 80 x 5 = 40,000 mm^3
    4 holes volume = 4 x pi x (4^2) x 5 = 1,005.30965 mm^3
    Net volume = 38,994.69035 mm^3 = 3.899469e-5 m^3
    Steel mass (rho=7850 kg/m^3) = 0.306108 kg.
    """
    mass = calculate_bracket_mass(
        length_mm=100.0,
        width_mm=80.0,
        thickness_mm=5.0,
        hole_diameter_mm=8.0,
        hole_count=4,
        material_density_kg_m3=7850.0,
    )
    expected_vol_m3 = (100.0 * 80.0 * 5.0 - 4.0 * math.pi * (4.0**2) * 5.0) * 1e-9
    expected_mass = expected_vol_m3 * 7850.0

    assert mass == pytest.approx(expected_mass, rel=1e-5)
    assert 0.30 < mass < 0.31


@pytest.mark.parametrize(
    "kwargs, err_match",
    [
        ({"length_mm": 0.0}, "strictly positive"),
        ({"width_mm": -10.0}, "strictly positive"),
        ({"thickness_mm": 0.0}, "strictly positive"),
        ({"hole_diameter_mm": -1.0}, "strictly positive"),
        ({"hole_count": -1}, "non-negative integer"),
        ({"material_density_kg_m3": 0.0}, "strictly positive"),
    ],
)
def test_calculate_bracket_mass_invalid_inputs(kwargs: dict, err_match: str) -> None:
    base = dict(
        length_mm=100.0,
        width_mm=80.0,
        thickness_mm=5.0,
        hole_diameter_mm=8.0,
        hole_count=4,
        material_density_kg_m3=7850.0,
    )
    base.update(kwargs)
    with pytest.raises(BracketOptimizerError, match=err_match):
        calculate_bracket_mass(**base)


def test_calculate_bracket_mass_excessive_hole_area_rejected() -> None:
    """When hole area exceeds plate area, calculate_bracket_mass must raise."""
    with pytest.raises(BracketOptimizerError, match="exceeds or equals plate area"):
        calculate_bracket_mass(
            length_mm=10.0,
            width_mm=10.0,
            thickness_mm=5.0,
            hole_diameter_mm=10.0,
            hole_count=2,  # 2 * pi * 25 = 157 mm^2 > 100 mm^2
        )


@pytest.mark.parametrize(
    "kwargs, err_match",
    [
        ({"max_allowable_stress_mpa": 0.0}, "max_allowable_stress_mpa must be strictly positive"),
        ({"max_allowable_stress_mpa": -50.0}, "max_allowable_stress_mpa must be strictly positive"),
        ({"thickness_bounds_mm": (5.0, 2.0)}, "Invalid thickness_bounds_mm"),
        ({"thickness_bounds_mm": (-1.0, 5.0)}, "Invalid thickness_bounds_mm"),
        ({"thickness_bounds_mm": (5.0, 5.0)}, "Invalid thickness_bounds_mm"),
        ({"applied_force_n": 0.0}, "applied_force_n must be strictly positive"),
        ({"xtol_mm": 0.0}, "xtol_mm must be strictly positive"),
        ({"maxiter": 0}, "maxiter must be >= 1"),
    ],
)
def test_optimizer_parameter_validations(kwargs: dict, err_match: str) -> None:
    base = dict(
        length_mm=100.0,
        width_mm=80.0,
        hole_diameter_mm=8.0,
        hole_count=4,
        applied_force_n=500.0,
        max_allowable_stress_mpa=10.0,
    )
    base.update(kwargs)
    with pytest.raises(BracketOptimizerError, match=err_match):
        optimize_bracket_thickness_for_min_mass(**base)


def test_optimizer_geometric_bound_validation_rejection() -> None:
    """If bracket geometry is invalid (e.g. hole diameter too large), optimizer rejects before solving."""
    with pytest.raises(BracketOptimizerError, match="Invalid bracket parameters"):
        optimize_bracket_thickness_for_min_mass(
            length_mm=100.0,
            width_mm=80.0,
            hole_diameter_mm=79.0,  # exceeds width limit
            hole_count=4,
            applied_force_n=500.0,
            max_allowable_stress_mpa=10.0,
        )


def test_optimizer_infeasible_lower_bound_already_satisfies_allowable() -> None:
    """If even the thinnest bound has stress <= allowable, optimizer raises explaining true optimum is thinner."""
    mock_agent = MagicMock(spec=StructuresAgent)

    def mock_eval(**kwargs):
        t = kwargs["thickness_mm"]
        # Stress monotonically decreasing: sigma(t) = 50 / t
        # At t=2: stress=25 MPa, at t=10: stress=5 MPa
        return BracketStructuralResult(
            hotspot_stress_mpa=50.0 / t,
            raw_peak_stress_mpa=50.0 / t,
            max_deflection_mm=0.1,
            equilibrium_error_pct=0.001,
            mesh_converged=True,
            coarse_mesh_hotspot_stress_mpa=50.0 / t,
            fine_mesh_hotspot_stress_mpa=50.0 / t,
        )

    mock_agent.evaluate_bracket.side_effect = mock_eval

    # Allowable stress = 30.0 MPa (even t=2.0 gives 25.0 MPa <= 30.0 MPa)
    with pytest.raises(BracketOptimizerError, match="Even the thinnest candidate .* satisfies max_allowable_stress_mpa"):
        optimize_bracket_thickness_for_min_mass(
            length_mm=100.0,
            width_mm=80.0,
            hole_diameter_mm=8.0,
            hole_count=4,
            applied_force_n=500.0,
            max_allowable_stress_mpa=30.0,
            thickness_bounds_mm=(2.0, 10.0),
            structures_agent=mock_agent,
        )


def test_optimizer_infeasible_upper_bound_exceeds_allowable() -> None:
    """If even the thickest bound has stress > allowable, optimizer raises explaining true optimum is thicker."""
    mock_agent = MagicMock(spec=StructuresAgent)

    def mock_eval(**kwargs):
        t = kwargs["thickness_mm"]
        return BracketStructuralResult(
            hotspot_stress_mpa=50.0 / t,
            raw_peak_stress_mpa=50.0 / t,
            max_deflection_mm=0.1,
            equilibrium_error_pct=0.001,
            mesh_converged=True,
            coarse_mesh_hotspot_stress_mpa=50.0 / t,
            fine_mesh_hotspot_stress_mpa=50.0 / t,
        )

    mock_agent.evaluate_bracket.side_effect = mock_eval

    # Allowable stress = 3.0 MPa (even t=10.0 gives 5.0 MPa > 3.0 MPa)
    with pytest.raises(BracketOptimizerError, match="Even the thickest candidate .* exceeds max_allowable_stress_mpa"):
        optimize_bracket_thickness_for_min_mass(
            length_mm=100.0,
            width_mm=80.0,
            hole_diameter_mm=8.0,
            hole_count=4,
            applied_force_n=500.0,
            max_allowable_stress_mpa=3.0,
            thickness_bounds_mm=(2.0, 10.0),
            structures_agent=mock_agent,
        )


def test_optimizer_non_monotonic_stress_raises_error() -> None:
    """If stress increases with thickness, mechanics monotonicity assumption check fails."""
    mock_agent = MagicMock(spec=StructuresAgent)

    def mock_eval(**kwargs):
        t = kwargs["thickness_mm"]
        # Inverted stress: higher thickness = higher stress
        return BracketStructuralResult(
            hotspot_stress_mpa=5.0 * t,
            raw_peak_stress_mpa=5.0 * t,
            max_deflection_mm=0.1,
            equilibrium_error_pct=0.001,
            mesh_converged=True,
            coarse_mesh_hotspot_stress_mpa=5.0 * t,
            fine_mesh_hotspot_stress_mpa=5.0 * t,
        )

    mock_agent.evaluate_bracket.side_effect = mock_eval

    with pytest.raises(BracketOptimizerError, match="Structural mechanics monotonicity assumption violated"):
        optimize_bracket_thickness_for_min_mass(
            length_mm=100.0,
            width_mm=80.0,
            hole_diameter_mm=8.0,
            hole_count=4,
            applied_force_n=500.0,
            max_allowable_stress_mpa=25.0,
            thickness_bounds_mm=(2.0, 10.0),
            structures_agent=mock_agent,
        )


def test_optimizer_brentq_convergence_and_transparency_with_mock() -> None:
    """Validate root-finding convergence to known exact solution using mock agent."""
    mock_agent = MagicMock(spec=StructuresAgent)

    # Let stress(t) = 50.0 / t
    # For allowable stress = 10.0 MPa, exact root is t* = 5.0 mm.
    def mock_eval(**kwargs):
        t = kwargs["thickness_mm"]
        return BracketStructuralResult(
            hotspot_stress_mpa=50.0 / t,
            raw_peak_stress_mpa=50.0 / t,
            max_deflection_mm=0.1 / t,
            equilibrium_error_pct=0.001,
            mesh_converged=True,
            coarse_mesh_hotspot_stress_mpa=50.0 / t,
            fine_mesh_hotspot_stress_mpa=50.0 / t,
        )

    mock_agent.evaluate_bracket.side_effect = mock_eval

    result = optimize_bracket_thickness_for_min_mass(
        length_mm=100.0,
        width_mm=80.0,
        hole_diameter_mm=8.0,
        hole_count=4,
        applied_force_n=500.0,
        max_allowable_stress_mpa=10.0,
        thickness_bounds_mm=(2.0, 10.0),
        xtol_mm=0.01,
        structures_agent=mock_agent,
    )

    assert isinstance(result, BracketOptimizationResult)
    # Optimal thickness must be very close to 5.0 mm
    assert result.optimal_thickness_mm == pytest.approx(5.0, abs=0.02)
    assert 2.0 < result.optimal_thickness_mm < 10.0
    # Stress at optimum must equal allowable stress (active constraint)
    assert result.max_stress_at_optimum_mpa == pytest.approx(10.0, abs=0.05)
    # Mass must match calculate_bracket_mass
    expected_mass = calculate_bracket_mass(100.0, 80.0, result.optimal_thickness_mm, 8.0, 4)
    assert result.optimal_mass_kg == pytest.approx(expected_mass, rel=1e-4)
    # Multiple evaluations were logged transparently
    assert len(result.evaluations) >= 3
    for pt in result.evaluations:
        assert isinstance(pt, BracketDesignPoint)
        assert pt.thickness_mm > 0
        assert pt.mass_kg > 0
        assert pt.hotspot_stress_mpa > 0
        assert pt.mesh_converged is True


@pytest.mark.skipif(
    not CALCULIX_AVAILABLE,
    reason="ccx.exe (CalculiX) not installed on this machine — see vendor/calculix/README.md",
)
def test_real_bracket_optimization_calculix() -> None:
    """Real closed-loop 3D solid FEA optimization using CalculiX.

    Reference bracket: 100x80mm, 4x8mm holes, 500N top load.
    At t=5.0mm, hotspot_stress_mpa is ~5.48 MPa (post-v0.8 stress-singularity
    fix; raw_peak_stress_mpa is ~8.38 MPa but is not the convergence-driving
    metric). Setting allowable stress to 6.50 MPa forces the optimizer to
    search within (4.0, 8.0)mm bounds -- verified to converge in ~9 minutes
    of real FEA (multiple evaluate_bracket calls via brentq).
    """
    result = optimize_bracket_thickness_for_min_mass(
        length_mm=100.0,
        width_mm=80.0,
        hole_diameter_mm=8.0,
        hole_count=4,
        applied_force_n=500.0,
        max_allowable_stress_mpa=6.50,
        thickness_bounds_mm=(4.0, 8.0),
        xtol_mm=0.1,
        maxiter=15,
    )

    assert isinstance(result, BracketOptimizationResult)
    assert 4.0 < result.optimal_thickness_mm < 8.0
    assert result.optimal_mass_kg > 0
    # Stress at optimum should be within tolerance of the allowable stress
    assert result.max_stress_at_optimum_mpa == pytest.approx(6.50, rel=0.05)
    assert len(result.evaluations) >= 2
    for pt in result.evaluations:
        assert pt.thickness_mm > 0
        assert pt.mass_kg > 0
        assert pt.hotspot_stress_mpa > 0
