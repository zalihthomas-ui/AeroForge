"""Bracket thickness optimization module.

Finds the minimum-mass (thinnest) mounting bracket that satisfies a maximum allowable
stress constraint using bounded 1D root-finding (scipy.optimize.brentq) against the
CalculiX 3D solid FEA solver.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

from scipy.optimize import brentq

from agents.geometry.validation import GeometryValidationError, validate_bracket_parameters
from agents.structures.agent import (
    CALCULIX_AVAILABLE,
    BracketStructuralResult,
    StructuresAgent,
    StructuresEvaluationError,
)


class BracketOptimizerError(Exception):
    """Raised when bracket thickness optimization fails due to invalid parameters,
    solver errors, or infeasible/unbracketed stress bounds."""

    pass


@dataclass
class BracketDesignPoint:
    """Evaluated design point for a bracket geometry."""

    thickness_mm: float
    mass_kg: float
    hotspot_stress_mpa: float
    mesh_converged: bool


@dataclass
class BracketOptimizationResult:
    """Result of bracket thickness optimization for minimum mass."""

    optimal_thickness_mm: float
    optimal_mass_kg: float
    max_stress_at_optimum_mpa: float
    max_allowable_stress_mpa: float
    evaluations: list[BracketDesignPoint]  # every point actually tried, transparency


def calculate_bracket_mass(
    length_mm: float,
    width_mm: float,
    thickness_mm: float,
    hole_diameter_mm: float,
    hole_count: int,
    material_density_kg_m3: float = 7850.0,
) -> float:
    """Calculate the theoretical mass of a mounting bracket with through-holes in kg.

    Formula:
        Plate volume = length * width * thickness
        Hole volume = hole_count * pi * (hole_diameter / 2)^2 * thickness
        Net volume (m^3) = (Plate volume - Hole volume) * 1e-9
        Mass (kg) = Net volume * material_density_kg_m3

    Args:
        length_mm: Bracket length (along X) in mm. Must be positive.
        width_mm: Bracket width (along Y) in mm. Must be positive.
        thickness_mm: Bracket thickness (along Z) in mm. Must be positive.
        hole_diameter_mm: Diameter of mounting holes in mm. Must be positive.
        hole_count: Number of mounting holes. Must be >= 0.
        material_density_kg_m3: Material density in kg/m^3 (default: 7850.0 for steel).

    Returns:
        Mass in kilograms.

    Raises:
        BracketOptimizerError: If inputs are invalid or net area is non-positive.
    """
    if length_mm <= 0 or width_mm <= 0 or thickness_mm <= 0:
        raise BracketOptimizerError(
            f"Dimensions must be strictly positive: length={length_mm}, width={width_mm}, thickness={thickness_mm}."
        )
    if hole_diameter_mm <= 0:
        raise BracketOptimizerError(f"hole_diameter_mm must be strictly positive, got {hole_diameter_mm}.")
    if hole_count < 0 or hole_count != int(hole_count):
        raise BracketOptimizerError(f"hole_count must be a non-negative integer, got {hole_count}.")
    if material_density_kg_m3 <= 0:
        raise BracketOptimizerError(f"material_density_kg_m3 must be strictly positive, got {material_density_kg_m3}.")

    hole_radius_mm = hole_diameter_mm / 2.0
    plate_area_mm2 = length_mm * width_mm
    holes_area_mm2 = hole_count * math.pi * (hole_radius_mm**2)
    net_area_mm2 = plate_area_mm2 - holes_area_mm2

    if net_area_mm2 <= 0:
        raise BracketOptimizerError(
            f"Total hole area ({holes_area_mm2:.2f} mm^2) exceeds or equals plate area ({plate_area_mm2:.2f} mm^2)."
        )

    net_volume_mm3 = net_area_mm2 * thickness_mm
    net_volume_m3 = net_volume_mm3 * 1e-9
    return net_volume_m3 * material_density_kg_m3


def optimize_bracket_thickness_for_min_mass(
    length_mm: float,
    width_mm: float,
    hole_diameter_mm: float,
    hole_count: int,
    applied_force_n: float,
    max_allowable_stress_mpa: float,
    material_density_kg_m3: float = 7850.0,
    thickness_bounds_mm: tuple[float, float] = (2.0, 10.0),
    xtol_mm: float = 0.05,
    maxiter: int = 20,
    youngs_modulus_mpa: float = 210000.0,
    poissons_ratio: float = 0.3,
    structures_agent: StructuresAgent | None = None,
) -> BracketOptimizationResult:
    """Find the thinnest (minimum mass) mounting bracket satisfying a maximum stress allowable.

    Uses bounded 1D root-finding via Brent's method (scipy.optimize.brentq) to find the
    thickness t where stress(t) == max_allowable_stress_mpa.

    Since bracket mass scales strictly monotonically with thickness and peak stress decreases
    monotonically with increasing thickness, the minimum-mass feasible design is located at the
    active stress boundary.

    Args:
        length_mm: Bracket length along X in mm.
        width_mm: Bracket width along Y in mm.
        hole_diameter_mm: Mounting hole diameter in mm.
        hole_count: Number of mounting holes (must match geometry rules, e.g. 4).
        applied_force_n: Total transverse load in N applied to the top face.
        max_allowable_stress_mpa: Maximum allowable von Mises peak stress in MPa.
        material_density_kg_m3: Material density in kg/m^3 (default: 7850.0 for steel).
        thickness_bounds_mm: (min_thickness_mm, max_thickness_mm) search interval.
        xtol_mm: Absolute thickness convergence tolerance in mm for brentq.
        maxiter: Maximum iterations for brentq.
        youngs_modulus_mpa: Young's modulus in MPa (default: 210000.0).
        poissons_ratio: Poisson's ratio (default: 0.3).
        structures_agent: Optional StructuresAgent instance (defaults to new instance).

    Returns:
        BracketOptimizationResult: Optimal thickness, mass, stress at optimum, and full evaluation log.

    Raises:
        BracketOptimizerError: If inputs/bounds are invalid, CalculiX is unavailable,
                               bounds do not bracket the root (sign change check fails),
                               or non-monotonic stress behavior is encountered.
    """
    # 1. Parameter validations
    if max_allowable_stress_mpa <= 0:
        raise BracketOptimizerError(
            f"max_allowable_stress_mpa must be strictly positive, got {max_allowable_stress_mpa}."
        )

    if (
        not isinstance(thickness_bounds_mm, (tuple, list))
        or len(thickness_bounds_mm) != 2
        or thickness_bounds_mm[0] <= 0
        or thickness_bounds_mm[0] >= thickness_bounds_mm[1]
    ):
        raise BracketOptimizerError(
            f"Invalid thickness_bounds_mm: {thickness_bounds_mm}. Expected (min_t, max_t) with 0 < min_t < max_t."
        )

    if xtol_mm <= 0:
        raise BracketOptimizerError(f"xtol_mm must be strictly positive, got {xtol_mm}.")

    if maxiter < 1:
        raise BracketOptimizerError(f"maxiter must be >= 1, got {maxiter}.")

    t_min, t_max = float(thickness_bounds_mm[0]), float(thickness_bounds_mm[1])

    # Validate bracket geometric bounds
    for t_bound in (t_min, t_max):
        try:
            validate_bracket_parameters(length_mm, width_mm, t_bound, hole_diameter_mm, hole_count)
        except (GeometryValidationError, ValueError) as exc:
            raise BracketOptimizerError(
                f"Invalid bracket parameters at thickness {t_bound} mm: {exc}"
            ) from exc

    if applied_force_n <= 0:
        raise BracketOptimizerError(f"applied_force_n must be strictly positive, got {applied_force_n}.")

    if not CALCULIX_AVAILABLE:
        raise BracketOptimizerError(
            "CalculiX (ccx.exe) is not available on this machine. Cannot run bracket FEA optimization."
        )

    agent = structures_agent or StructuresAgent()

    # 2. Evaluation cache and tracking
    evaluations: list[BracketDesignPoint] = []
    cache: dict[float, BracketStructuralResult] = {}

    def evaluate_thickness(t: float) -> BracketStructuralResult:
        key = round(t, 5)
        if key in cache:
            return cache[key]

        try:
            res = agent.evaluate_bracket(
                length_mm=length_mm,
                width_mm=width_mm,
                thickness_mm=t,
                hole_diameter_mm=hole_diameter_mm,
                hole_count=hole_count,
                applied_force_n=applied_force_n,
                youngs_modulus_mpa=youngs_modulus_mpa,
                poissons_ratio=poissons_ratio,
            )
        except StructuresEvaluationError as exc:
            raise BracketOptimizerError(f"FEA evaluation failed at thickness {t:.4f} mm: {exc}") from exc

        cache[key] = res
        mass_kg = calculate_bracket_mass(
            length_mm=length_mm,
            width_mm=width_mm,
            thickness_mm=t,
            hole_diameter_mm=hole_diameter_mm,
            hole_count=hole_count,
            material_density_kg_m3=material_density_kg_m3,
        )
        evaluations.append(
            BracketDesignPoint(
                thickness_mm=t,
                mass_kg=mass_kg,
                hotspot_stress_mpa=res.hotspot_stress_mpa,
                mesh_converged=res.mesh_converged,
            )
        )
        return res

    # 3. Bracket bounds evaluation, monotonicity, and sign change validation
    res_min = evaluate_thickness(t_min)
    res_max = evaluate_thickness(t_max)

    stress_min = res_min.hotspot_stress_mpa
    stress_max = res_max.hotspot_stress_mpa

    # Case A: Mechanics assumption verification (stress must decrease as thickness increases)
    if stress_min <= stress_max:
        raise BracketOptimizerError(
            f"Stress at lower bound ({t_min:.2f} mm: {stress_min:.3f} MPa) is not greater than "
            f"stress at upper bound ({t_max:.2f} mm: {stress_max:.3f} MPa). "
            "Structural mechanics monotonicity assumption violated."
        )

    # Case B: Even thinnest bracket candidate is already within allowable stress
    if stress_min <= max_allowable_stress_mpa:
        raise BracketOptimizerError(
            f"Even the thinnest candidate (thickness_bounds_mm[0]={t_min:.2f} mm) satisfies "
            f"max_allowable_stress_mpa ({stress_min:.3f} MPa <= {max_allowable_stress_mpa:.3f} MPa). "
            f"The true minimum-mass optimum is thinner than {t_min:.2f} mm -- narrow or lower the lower thickness bound."
        )

    # Case C: Even thickest bracket candidate exceeds allowable stress
    if stress_max > max_allowable_stress_mpa:
        raise BracketOptimizerError(
            f"Even the thickest candidate (thickness_bounds_mm[1]={t_max:.2f} mm) exceeds "
            f"max_allowable_stress_mpa ({stress_max:.3f} MPa > {max_allowable_stress_mpa:.3f} MPa). "
            f"The true optimum is thicker than {t_max:.2f} mm -- widen the upper thickness bound or increase allowable stress."
        )

    # 4. Brent's method root-finding: find t where stress(t) - max_allowable_stress_mpa == 0
    def residual(t: float) -> float:
        res = evaluate_thickness(t)
        return res.hotspot_stress_mpa - max_allowable_stress_mpa

    try:
        opt_t = float(
            brentq(
                residual,
                t_min,
                t_max,
                xtol=xtol_mm,
                maxiter=maxiter,
            )
        )
    except Exception as exc:
        raise BracketOptimizerError(f"Root-finding with brentq failed: {exc}") from exc

    # Ensure optimal thickness is evaluated and recorded
    res_opt = evaluate_thickness(opt_t)

    # Match best design point in evaluation history
    best_point = min(evaluations, key=lambda p: abs(p.thickness_mm - opt_t))

    return BracketOptimizationResult(
        optimal_thickness_mm=best_point.thickness_mm,
        optimal_mass_kg=best_point.mass_kg,
        max_stress_at_optimum_mpa=best_point.hotspot_stress_mpa,
        max_allowable_stress_mpa=max_allowable_stress_mpa,
        evaluations=evaluations,
    )
