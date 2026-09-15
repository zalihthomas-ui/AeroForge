"""Multi-parameter 2D bracket optimization module (thickness and hole_diameter).

Finds the minimum-mass mounting bracket by simultaneously optimizing thickness
and mounting hole diameter subject to a maximum allowable von Mises hotspot stress
constraint and geometric feasibility constraints.

Methodology:
- 2D constrained derivative-free optimization via COBYLA (`scipy.optimize.minimize(method='COBYLA')`).
- Unlike 1D root-finding (brentq), the 2D design space has a curve of constraint-satisfying
  points; COBYLA searches along this trade-off curve to minimize mass.
- Bounded evaluation budget (`max_evaluations`, default 18) to strictly manage FEA computational cost.
- Probes landing on geometrically invalid parameters (e.g. hole too large for bracket width/length)
  are caught prior to FEA via `validate_bracket_parameters` and penalized without running expensive solves.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

import numpy as np
from scipy.optimize import minimize

from agents.geometry.validation import (
    GeometryValidationError,
    MIN_EDGE_MARGIN_MM,
    MIN_HOLE_SPACING_MM,
    validate_bracket_parameters,
)
from agents.structures.agent import (
    CALCULIX_AVAILABLE,
    BracketStructuralResult,
    StructuresAgent,
    StructuresEvaluationError,
)
from engineering.analysis.bracket_optimizer import calculate_bracket_mass


class BracketOptimizer2DError(Exception):
    """Raised when 2D bracket optimization fails due to invalid parameters or solver configuration."""

    pass


@dataclass
class BracketDesignPoint2D:
    """Evaluated 2D design point for a mounting bracket."""

    thickness_mm: float
    hole_diameter_mm: float
    mass_kg: float
    hotspot_stress_mpa: float
    mesh_converged: bool
    feasible: bool  # Geometrically valid, within bounds, AND hotspot_stress <= allowable


@dataclass
class BracketOptimization2DResult:
    """Result of 2D bracket thickness and hole diameter optimization for minimum mass."""

    optimal_thickness_mm: float
    optimal_hole_diameter_mm: float
    optimal_mass_kg: float
    stress_at_optimum_mpa: float
    max_allowable_stress_mpa: float
    converged: bool  # True if at least one feasible point was found within the evaluation budget
    evaluations: list[BracketDesignPoint2D]  # Transparent log of all evaluated points


def optimize_bracket_thickness_and_hole_for_min_mass(
    length_mm: float,
    width_mm: float,
    hole_count: int,
    applied_force_n: float,
    max_allowable_stress_mpa: float,
    material_density_kg_m3: float = 7850.0,
    thickness_bounds_mm: tuple[float, float] = (2.0, 10.0),
    hole_diameter_bounds_mm: tuple[float, float] = (4.0, 15.0),
    max_evaluations: int = 18,
    youngs_modulus_mpa: float = 210000.0,
    poissons_ratio: float = 0.3,
    structures_agent: StructuresAgent | None = None,
) -> BracketOptimization2DResult:
    """Optimize bracket thickness and hole diameter simultaneously for minimum mass.

    Uses derivative-free constrained optimization (COBYLA) with inequality constraints
    for the maximum allowable stress and geometric bounds.

    Args:
        length_mm: Bracket length along X (mm). Must be positive.
        width_mm: Bracket width along Y (mm). Must be positive.
        hole_count: Number of mounting holes (must be non-negative integer, e.g. 4).
        applied_force_n: Transverse force applied to top face (N). Must be positive.
        max_allowable_stress_mpa: Upper limit on von Mises hotspot stress (MPa). Must be positive.
        material_density_kg_m3: Density in kg/m^3 (default: 7850.0 for steel).
        thickness_bounds_mm: (min_t, max_t) search bounds for thickness in mm.
        hole_diameter_bounds_mm: (min_d, max_d) search bounds for hole diameter in mm.
        max_evaluations: Maximum number of optimizer iterations/evaluations (default: 18).
        youngs_modulus_mpa: Young's modulus in MPa (default: 210000.0).
        poissons_ratio: Poisson's ratio (default: 0.3).
        structures_agent: Optional StructuresAgent instance (defaults to new instance).

    Returns:
        BracketOptimization2DResult: Best feasible design, stress, mass, and evaluation log.

    Raises:
        BracketOptimizer2DError: If inputs/bounds are invalid or CalculiX is unavailable.
    """
    # 1. Parameter and bound validations
    if length_mm <= 0 or width_mm <= 0:
        raise BracketOptimizer2DError(
            f"Bracket dimensions must be strictly positive: length={length_mm}, width={width_mm}."
        )

    if hole_count < 0 or hole_count != int(hole_count):
        raise BracketOptimizer2DError(f"hole_count must be a non-negative integer, got {hole_count}.")
    hole_count = int(hole_count)

    if applied_force_n <= 0:
        raise BracketOptimizer2DError(f"applied_force_n must be strictly positive, got {applied_force_n}.")

    if max_allowable_stress_mpa <= 0:
        raise BracketOptimizer2DError(
            f"max_allowable_stress_mpa must be strictly positive, got {max_allowable_stress_mpa}."
        )

    if material_density_kg_m3 <= 0:
        raise BracketOptimizer2DError(
            f"material_density_kg_m3 must be strictly positive, got {material_density_kg_m3}."
        )

    if (
        not isinstance(thickness_bounds_mm, (tuple, list))
        or len(thickness_bounds_mm) != 2
        or thickness_bounds_mm[0] <= 0
        or thickness_bounds_mm[0] >= thickness_bounds_mm[1]
    ):
        raise BracketOptimizer2DError(
            f"Invalid thickness_bounds_mm: {thickness_bounds_mm}. Expected (min_t, max_t) with 0 < min_t < max_t."
        )

    if (
        not isinstance(hole_diameter_bounds_mm, (tuple, list))
        or len(hole_diameter_bounds_mm) != 2
        or hole_diameter_bounds_mm[0] <= 0
        or hole_diameter_bounds_mm[0] >= hole_diameter_bounds_mm[1]
    ):
        raise BracketOptimizer2DError(
            f"Invalid hole_diameter_bounds_mm: {hole_diameter_bounds_mm}. "
            "Expected (min_d, max_d) with 0 < min_d < max_d."
        )

    if max_evaluations < 1:
        raise BracketOptimizer2DError(f"max_evaluations must be >= 1, got {max_evaluations}.")

    t_min, t_max = float(thickness_bounds_mm[0]), float(thickness_bounds_mm[1])
    d_min, d_max = float(hole_diameter_bounds_mm[0]), float(hole_diameter_bounds_mm[1])

    # Check that lower diameter bound is geometrically plausible
    try:
        validate_bracket_parameters(length_mm, width_mm, t_min, d_min, hole_count)
    except GeometryValidationError as exc:
        raise BracketOptimizer2DError(
            f"Lower bounds (t={t_min}, d={d_min}) are geometrically invalid: {exc}"
        ) from exc

    if not CALCULIX_AVAILABLE and structures_agent is None:
        raise BracketOptimizer2DError(
            "CalculiX (ccx.exe) is not available on this machine and no structures_agent was provided."
        )

    agent = structures_agent or StructuresAgent()

    # 2. Evaluation tracking and caching
    evaluations: list[BracketDesignPoint2D] = []
    cache: dict[tuple[float, float], BracketDesignPoint2D] = {}

    def evaluate_point(t: float, d: float) -> BracketDesignPoint2D:
        key = (round(t, 4), round(d, 4))
        if key in cache:
            return cache[key]

        in_bounds = (t_min - 1e-6 <= t <= t_max + 1e-6) and (d_min - 1e-6 <= d <= d_max + 1e-6)

        geom_valid = True
        try:
            validate_bracket_parameters(length_mm, width_mm, t, d, hole_count)
        except (GeometryValidationError, ValueError):
            geom_valid = False

        if not (in_bounds and geom_valid):
            # Penalty evaluation without running expensive FEA
            # Calculate nominal mass or penalty
            try:
                nominal_mass = calculate_bracket_mass(
                    length_mm, width_mm, max(t, 0.1), max(d, 0.1), hole_count, material_density_kg_m3
                )
            except Exception:
                nominal_mass = 100.0

            point = BracketDesignPoint2D(
                thickness_mm=float(t),
                hole_diameter_mm=float(d),
                mass_kg=nominal_mass + 50.0,
                hotspot_stress_mpa=1e6,
                mesh_converged=False,
                feasible=False,
            )
            cache[key] = point
            evaluations.append(point)
            return point

        # Geometrically valid and in bounds: run FEA
        try:
            struct_res = agent.evaluate_bracket(
                length_mm=length_mm,
                width_mm=width_mm,
                thickness_mm=float(t),
                hole_diameter_mm=float(d),
                hole_count=hole_count,
                applied_force_n=applied_force_n,
                youngs_modulus_mpa=youngs_modulus_mpa,
                poissons_ratio=poissons_ratio,
            )
            mass_kg = calculate_bracket_mass(
                length_mm=length_mm,
                width_mm=width_mm,
                thickness_mm=float(t),
                hole_diameter_mm=float(d),
                hole_count=hole_count,
                material_density_kg_m3=material_density_kg_m3,
            )
            stress = float(struct_res.hotspot_stress_mpa)
            is_feasible = stress <= max_allowable_stress_mpa

            point = BracketDesignPoint2D(
                thickness_mm=float(t),
                hole_diameter_mm=float(d),
                mass_kg=mass_kg,
                hotspot_stress_mpa=stress,
                mesh_converged=bool(struct_res.mesh_converged),
                feasible=is_feasible,
            )
        except (StructuresEvaluationError, Exception):
            point = BracketDesignPoint2D(
                thickness_mm=float(t),
                hole_diameter_mm=float(d),
                mass_kg=100.0,
                hotspot_stress_mpa=1e6,
                mesh_converged=False,
                feasible=False,
            )

        cache[key] = point
        evaluations.append(point)
        return point

    # 3. Setup COBYLA Objective and Inequality Constraints (c_i(x) >= 0)
    def objective(x: np.ndarray) -> float:
        pt = evaluate_point(float(x[0]), float(x[1]))
        if not pt.feasible and pt.hotspot_stress_mpa == 1e6:
            return 1e4
        return pt.mass_kg

    def constraint_stress(x: np.ndarray) -> float:
        pt = evaluate_point(float(x[0]), float(x[1]))
        if pt.hotspot_stress_mpa == 1e6:
            return -1e3
        return max_allowable_stress_mpa - pt.hotspot_stress_mpa

    def constraint_t_min(x: np.ndarray) -> float:
        return float(x[0]) - t_min

    def constraint_t_max(x: np.ndarray) -> float:
        return t_max - float(x[0])

    def constraint_d_min(x: np.ndarray) -> float:
        return float(x[1]) - d_min

    def constraint_d_max(x: np.ndarray) -> float:
        return d_max - float(x[1])

    max_d_edge = width_mm - 2 * MIN_EDGE_MARGIN_MM
    max_d_spacing = length_mm / hole_count - MIN_HOLE_SPACING_MM

    def constraint_geom_edge(x: np.ndarray) -> float:
        return max_d_edge - float(x[1])

    def constraint_geom_spacing(x: np.ndarray) -> float:
        return max_d_spacing - float(x[1])

    constraints = [
        {"type": "ineq", "fun": constraint_stress},
        {"type": "ineq", "fun": constraint_t_min},
        {"type": "ineq", "fun": constraint_t_max},
        {"type": "ineq", "fun": constraint_d_min},
        {"type": "ineq", "fun": constraint_d_max},
        {"type": "ineq", "fun": constraint_geom_edge},
        {"type": "ineq", "fun": constraint_geom_spacing},
    ]

    # 4. Initial guess selection
    t0 = (t_min + t_max) / 2.0
    d0 = (d_min + d_max) / 2.0
    max_geom_d = min(max_d_edge - 1.0, max_d_spacing - 1.0, d_max)
    if d0 > max_geom_d:
        d0 = max(d_min, max_geom_d)

    x0 = np.array([t0, d0])

    # 5. Run COBYLA optimization
    minimize(
        objective,
        x0,
        method="COBYLA",
        constraints=constraints,
        options={"maxiter": max_evaluations, "rhobeg": 0.5, "tol": 1e-3, "disp": False},
    )

    # 6. Extract best feasible result or lowest stress design
    feasible_points = [p for p in evaluations if p.feasible]
    if feasible_points:
        best_point = min(feasible_points, key=lambda p: p.mass_kg)
        converged = True
    else:
        best_point = min(evaluations, key=lambda p: p.hotspot_stress_mpa)
        converged = False

    return BracketOptimization2DResult(
        optimal_thickness_mm=best_point.thickness_mm,
        optimal_hole_diameter_mm=best_point.hole_diameter_mm,
        optimal_mass_kg=best_point.mass_kg,
        stress_at_optimum_mpa=best_point.hotspot_stress_mpa,
        max_allowable_stress_mpa=max_allowable_stress_mpa,
        converged=converged,
        evaluations=evaluations,
    )
