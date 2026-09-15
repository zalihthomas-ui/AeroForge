"""Bracket materializer module: closes the loop from structural optimization to CAD.

Takes an optimized bracket design point, generates the revised 3D CAD solid via build123d,
exports the physical models to STEP, STL, and 3MF formats, and performs a consistency
re-analysis to verify that the final materialized design reproduces the optimizer's FEA metrics.
"""

from __future__ import annotations

from dataclasses import dataclass
import os

from agents.geometry.bracket import build_bracket
from agents.geometry.validation import GeometryValidationError, validate_bracket_parameters
from agents.structures.agent import (
    CALCULIX_AVAILABLE,
    BracketStructuralResult,
    StructuresAgent,
    StructuresEvaluationError,
)
from cad.exporters import export_3mf, export_step, export_stl
from engineering.analysis.bracket_optimizer import (
    BracketOptimizationResult,
    BracketOptimizerError,
)


class BracketMaterializerError(Exception):
    """Raised when materialization of the optimal bracket CAD or consistency re-analysis fails."""

    pass


@dataclass
class MaterializedBracketResult:
    """Result of materializing an optimized bracket into CAD geometry and verifying FEA consistency."""

    optimization_result: BracketOptimizationResult  # what the optimizer found
    final_spec_parameters: dict[str, float]  # length/width/thickness/hole_diameter/hole_count at optimum
    step_path: str  # actual generated STEP file
    stl_path: str  # actual generated STL file
    threemf_path: str  # actual generated 3MF file
    reanalysis: BracketStructuralResult  # re-evaluated evaluate_bracket at optimal thickness
    reanalysis_matches_optimum: bool  # consistency check: discrepancy <= tolerance
    stress_discrepancy_pct: float  # |reanalysis.hotspot_stress - opt.max_stress| / opt.max_stress * 100


def materialize_optimal_bracket(
    length_mm: float,
    width_mm: float,
    hole_diameter_mm: float,
    hole_count: int,
    applied_force_n: float,
    optimization_result: BracketOptimizationResult,
    output_dir: str,
    youngs_modulus_mpa: float = 210000.0,
    poissons_ratio: float = 0.3,
    tolerance_pct: float = 0.5,
    filename_prefix: str = "bracket_optimized",
    structures_agent: StructuresAgent | None = None,
) -> MaterializedBracketResult:
    """Generate revised CAD geometry for an optimized bracket and perform consistency re-analysis.

    Closes the loop from structural FEA thickness optimization back to parametric CAD:
    1. Validates geometric bounds at the optimal thickness.
    2. Builds the revised 3D CAD solid via build_bracket (build123d Part).
    3. Exports the part to STEP, STL, and 3MF formats in output_dir.
    4. Re-evaluates structural FEA (evaluate_bracket) on the final geometry at the optimal thickness.
    5. Checks that the re-analyzed hotspot stress matches the optimizer's reported stress within tolerance_pct.

    Args:
        length_mm: Bracket length along X in mm.
        width_mm: Bracket width along Y in mm.
        hole_diameter_mm: Mounting hole diameter in mm.
        hole_count: Number of mounting holes (e.g. 4).
        applied_force_n: Total transverse load in N on the top face.
        optimization_result: Result from optimize_bracket_thickness_for_min_mass.
        output_dir: Directory where STEP, STL, and 3MF files are saved.
        youngs_modulus_mpa: Young's modulus in MPa (default: 210000.0).
        poissons_ratio: Poisson's ratio (default: 0.3).
        tolerance_pct: Allowable relative percentage discrepancy between optimizer stress
                       and re-analysis stress (default: 0.5%).
        filename_prefix: Base name for output CAD files (default: 'bracket_optimized').
        structures_agent: Optional StructuresAgent instance.

    Returns:
        MaterializedBracketResult: Complete record of materialized CAD files, final parameters,
                                   and structural consistency verification.

    Raises:
        BracketMaterializerError: If geometry validation fails, CAD export fails, CalculiX is
                                 unavailable, or re-analysis fails.
    """
    opt_t = optimization_result.optimal_thickness_mm

    # 1. Validate geometric parameters at optimal thickness
    try:
        validate_bracket_parameters(length_mm, width_mm, opt_t, hole_diameter_mm, hole_count)
    except (GeometryValidationError, ValueError) as exc:
        raise BracketMaterializerError(
            f"Geometry validation failed for optimized bracket parameters at thickness {opt_t:.4f} mm: {exc}"
        ) from exc

    if applied_force_n <= 0:
        raise BracketMaterializerError(f"applied_force_n must be strictly positive, got {applied_force_n}.")

    final_spec_parameters = {
        "length": float(length_mm),
        "width": float(width_mm),
        "thickness": float(opt_t),
        "hole_diameter": float(hole_diameter_mm),
        "hole_count": float(hole_count),
    }

    # 2. Ensure output directory exists
    try:
        os.makedirs(output_dir, exist_ok=True)
    except OSError as exc:
        raise BracketMaterializerError(f"Failed to create output directory '{output_dir}': {exc}") from exc

    # 3. Generate 3D CAD solid
    try:
        part = build_bracket(final_spec_parameters)
    except GeometryValidationError as exc:
        raise BracketMaterializerError(
            f"Failed to build 3D CAD geometry for bracket: {exc}"
        ) from exc
    except Exception as exc:
        raise BracketMaterializerError(
            f"Unexpected error during bracket geometry generation: {exc}"
        ) from exc

    # 4. Export CAD artifacts
    step_path = os.path.abspath(os.path.join(output_dir, f"{filename_prefix}.step"))
    stl_path = os.path.abspath(os.path.join(output_dir, f"{filename_prefix}.stl"))
    threemf_path = os.path.abspath(os.path.join(output_dir, f"{filename_prefix}.3mf"))

    try:
        export_step(part, step_path)
        export_stl(part, stl_path)
        export_3mf(part, threemf_path)
    except Exception as exc:
        raise BracketMaterializerError(f"Failed to export bracket CAD artifacts: {exc}") from exc

    # 5. Re-analysis on the final geometry
    if not CALCULIX_AVAILABLE:
        raise BracketMaterializerError(
            "CalculiX (ccx.exe) is not available on this machine. Cannot run bracket consistency re-analysis."
        )

    agent = structures_agent or StructuresAgent()
    try:
        reanalysis = agent.evaluate_bracket(
            length_mm=length_mm,
            width_mm=width_mm,
            thickness_mm=opt_t,
            hole_diameter_mm=hole_diameter_mm,
            hole_count=hole_count,
            applied_force_n=applied_force_n,
            youngs_modulus_mpa=youngs_modulus_mpa,
            poissons_ratio=poissons_ratio,
        )
    except StructuresEvaluationError as exc:
        raise BracketMaterializerError(f"Structural re-analysis failed on final bracket: {exc}") from exc

    # 6. Consistency check
    opt_stress = optimization_result.max_stress_at_optimum_mpa
    if opt_stress != 0:
        stress_discrepancy_pct = abs(reanalysis.hotspot_stress_mpa - opt_stress) / abs(opt_stress) * 100.0
    else:
        stress_discrepancy_pct = abs(reanalysis.hotspot_stress_mpa - opt_stress) * 100.0

    reanalysis_matches_optimum = stress_discrepancy_pct <= tolerance_pct

    return MaterializedBracketResult(
        optimization_result=optimization_result,
        final_spec_parameters=final_spec_parameters,
        step_path=step_path,
        stl_path=stl_path,
        threemf_path=threemf_path,
        reanalysis=reanalysis,
        reanalysis_matches_optimum=reanalysis_matches_optimum,
        stress_discrepancy_pct=stress_discrepancy_pct,
    )
