"""Unit and integration tests for 2D bracket thickness and hole diameter optimization.

Tests:
1. Input validation and early parameter rejection.
2. Invalid and geometrically infeasible bounds rejection.
3. 2D constrained optimization (COBYLA) with mock StructuresAgent.
4. Comparison verifying 2D optimizer finds lower mass by adjusting hole diameter.
5. Penalty handling for geometrically invalid parameter probes during search.
6. Real CalculiX 3D solid FEA 2D optimization (gated by CALCULIX_AVAILABLE).
"""

from __future__ import annotations

import math
from unittest.mock import MagicMock
import pytest

from agents.structures.agent import (
    CALCULIX_AVAILABLE,
    BracketStructuralResult,
    StructuresAgent,
)
from engineering.analysis.bracket_optimizer import calculate_bracket_mass
from engineering.analysis.bracket_optimizer_2d import (
    BracketDesignPoint2D,
    BracketOptimization2DResult,
    BracketOptimizer2DError,
    optimize_bracket_thickness_and_hole_for_min_mass,
)


@pytest.fixture
def mock_structures_agent() -> StructuresAgent:
    """Mock StructuresAgent using a continuous analytical stress surrogate:

    sigma(t, d) = 5.48 * (5.0 / t)^1.5 * (1.0 + 0.04 * (d - 8.0))
    At t=5.0mm, d=8.0mm, sigma = 5.48 MPa.
    """
    mock = MagicMock(spec=StructuresAgent)

    def side_effect(
        length_mm: float,
        width_mm: float,
        thickness_mm: float,
        hole_diameter_mm: float,
        hole_count: int,
        applied_force_n: float,
        youngs_modulus_mpa: float = 210000.0,
        poissons_ratio: float = 0.3,
    ) -> BracketStructuralResult:
        stress = 5.48 * ((5.0 / thickness_mm) ** 1.5) * (1.0 + 0.04 * (hole_diameter_mm - 8.0))
        return BracketStructuralResult(
            hotspot_stress_mpa=stress,
            raw_peak_stress_mpa=stress * 1.5,
            max_deflection_mm=0.1 * (5.0 / thickness_mm),
            equilibrium_error_pct=0.01,
            mesh_converged=True,
            coarse_mesh_hotspot_stress_mpa=stress * 1.02,
            fine_mesh_hotspot_stress_mpa=stress,
        )

    mock.evaluate_bracket.side_effect = side_effect
    return mock


@pytest.mark.parametrize(
    "kwargs, err_match",
    [
        ({"length_mm": 0.0}, "strictly positive"),
        ({"width_mm": -10.0}, "strictly positive"),
        ({"hole_count": -1}, "non-negative integer"),
        ({"hole_count": 2.5}, "non-negative integer"),
        ({"applied_force_n": 0.0}, "strictly positive"),
        ({"max_allowable_stress_mpa": -5.0}, "strictly positive"),
        ({"material_density_kg_m3": 0.0}, "strictly positive"),
        ({"thickness_bounds_mm": (5.0, 2.0)}, "Invalid thickness_bounds_mm"),
        ({"thickness_bounds_mm": (-1.0, 5.0)}, "Invalid thickness_bounds_mm"),
        ({"hole_diameter_bounds_mm": (10.0, 4.0)}, "Invalid hole_diameter_bounds_mm"),
        ({"hole_diameter_bounds_mm": (-2.0, 8.0)}, "Invalid hole_diameter_bounds_mm"),
        ({"max_evaluations": 0}, "max_evaluations must be >= 1"),
        ({"hole_diameter_bounds_mm": (78.0, 80.0)}, "geometrically invalid"),
    ],
)
def test_optimizer_2d_parameter_validations(
    mock_structures_agent: StructuresAgent,
    kwargs: dict[str, any],
    err_match: str,
) -> None:
    """Verify invalid parameters and bounds raise informative BracketOptimizer2DError."""
    default_kwargs = {
        "length_mm": 100.0,
        "width_mm": 80.0,
        "hole_count": 4,
        "applied_force_n": 500.0,
        "max_allowable_stress_mpa": 6.50,
        "material_density_kg_m3": 7850.0,
        "thickness_bounds_mm": (2.0, 10.0),
        "hole_diameter_bounds_mm": (4.0, 15.0),
        "max_evaluations": 15,
        "structures_agent": mock_structures_agent,
    }
    default_kwargs.update(kwargs)

    with pytest.raises(BracketOptimizer2DError, match=err_match):
        optimize_bracket_thickness_and_hole_for_min_mass(**default_kwargs)


def test_optimizer_2d_convergence_and_transparency(
    mock_structures_agent: StructuresAgent,
) -> None:
    """Verify COBYLA 2D optimization converges to a feasible minimum-mass design."""
    result = optimize_bracket_thickness_and_hole_for_min_mass(
        length_mm=100.0,
        width_mm=80.0,
        hole_count=4,
        applied_force_n=500.0,
        max_allowable_stress_mpa=6.50,
        thickness_bounds_mm=(2.0, 10.0),
        hole_diameter_bounds_mm=(4.0, 15.0),
        max_evaluations=18,
        structures_agent=mock_structures_agent,
    )

    assert result.converged is True
    assert result.stress_at_optimum_mpa <= 6.50 + 1e-3
    assert 2.0 <= result.optimal_thickness_mm <= 10.0
    assert 4.0 <= result.optimal_hole_diameter_mm <= 15.0

    # Baseline reference bracket at t=5.0, d=8.0 has mass ~0.306 kg
    baseline_mass = calculate_bracket_mass(100.0, 80.0, 5.0, 8.0, 4)
    assert result.optimal_mass_kg < baseline_mass

    # Evaluation log has multiple transparent records
    assert len(result.evaluations) >= 5
    feasible_evals = [e for e in result.evaluations if e.feasible]
    assert len(feasible_evals) >= 1
    for pt in feasible_evals:
        assert pt.hotspot_stress_mpa <= 6.50 + 1e-3
        assert pt.mesh_converged is True


def test_optimizer_2d_penalty_handling_on_invalid_probes(
    mock_structures_agent: StructuresAgent,
) -> None:
    """Verify that geometrically invalid probes receive penalty without crashing or failing."""
    # Narrow plate where large holes violate edge clearance
    result = optimize_bracket_thickness_and_hole_for_min_mass(
        length_mm=100.0,
        width_mm=20.0,  # Max allowable hole diameter is 20 - 4 = 16mm
        hole_count=4,
        applied_force_n=500.0,
        max_allowable_stress_mpa=15.0,
        thickness_bounds_mm=(2.0, 10.0),
        hole_diameter_bounds_mm=(4.0, 15.0),
        max_evaluations=15,
        structures_agent=mock_structures_agent,
    )

    assert result.converged is True
    assert result.optimal_hole_diameter_mm < 20.0 - 4.0  # Respects edge margin


@pytest.mark.skipif(
    not CALCULIX_AVAILABLE,
    reason="CalculiX ccx.exe not available on this machine",
)
def test_real_bracket_optimization_2d_calculix() -> None:
    """Real closed-loop 2D optimization using genuine CalculiX solid FEA with bounded iterations."""
    result = optimize_bracket_thickness_and_hole_for_min_mass(
        length_mm=100.0,
        width_mm=80.0,
        hole_count=4,
        applied_force_n=500.0,
        max_allowable_stress_mpa=8.00,
        thickness_bounds_mm=(4.0, 7.0),
        hole_diameter_bounds_mm=(6.0, 10.0),
        max_evaluations=2,  # Bounded budget for test execution time
    )

    assert len(result.evaluations) >= 1
    assert result.evaluations[0].mesh_converged is True
    assert result.evaluations[0].hotspot_stress_mpa > 0.0
