"""Wing materializer module: closes the loop from aerodynamic optimization back to CAD.

Takes an optimized wing specification, generates the revised 3D CAD geometry via build123d,
exports the physical models to STEP, STL, and 3MF formats, and performs a consistency
re-analysis to verify that the final materialized design reproduces the optimizer's aerodynamic metrics.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
import os

from agents.geometry.agent import GeometryAgent
from agents.geometry.validation import GeometryValidationError
from cad.exporters import export_3mf, export_step, export_stl
from engineering.analysis.wing_aero import WingAeroError, WingAeroSummary, evaluate_wing_aero
from engineering.analysis.wing_optimizer import WingOptimizationResult
from engineering.requirements.schema import EngineeringSpec


class WingMaterializerError(WingAeroError):
    """Raised when materialization of the optimal wing CAD or consistency re-analysis fails."""

    pass


@dataclass
class MaterializedWingResult:
    """Result of materializing an optimized wing into revised CAD geometry and verifying consistency."""

    optimization_result: WingOptimizationResult  # what the optimizer found
    final_spec: EngineeringSpec  # the revised specification with optimal airfoil
    step_path: str  # actual generated STEP file
    stl_path: str  # actual generated STL file
    threemf_path: str  # actual generated 3MF file
    reanalysis: WingAeroSummary  # re-evaluated on the FINAL spec
    reanalysis_matches_optimum: bool  # consistency check: discrepancy <= tolerance
    l_over_d_discrepancy_pct: float  # |reanalysis.l_over_d - opt.max_l_over_d| / opt.max_l_over_d * 100


def materialize_optimal_wing(
    base_spec: EngineeringSpec,
    optimization_result: WingOptimizationResult,
    output_dir: str,
    cruise_velocity_mps: float = 25.0,
    backend: str = "neuralfoil",
    tolerance_pct: float = 0.1,
    filename_prefix: str = "wing_optimized",
) -> MaterializedWingResult:
    """Generate revised CAD geometry for an optimized wing and perform consistency re-analysis.

    Closes the loop from aerodynamic optimization back to parametric CAD:
    1. Overrides base_spec parameters with the optimal NACA airfoil section.
    2. Invokes GeometryAgent to build the validated 3D solid geometry (build123d Part).
    3. Exports the part to STEP, STL, and 3MF in output_dir.
    4. Re-evaluates aerodynamic performance (evaluate_wing_aero) on the final spec at the
       optimal angle of attack.
    5. Checks that the re-analyzed L/D matches the optimizer's reported L/D within tolerance_pct.

    Args:
        base_spec: Base EngineeringSpec with component == 'wing'.
        optimization_result: Result from optimize_wing_for_max_l_over_d.
        output_dir: Directory where STEP, STL, and 3MF files are saved.
        cruise_velocity_mps: Cruise airspeed in m/s (default: 25.0).
        backend: Aerodynamics solver backend ('neuralfoil' or 'xfoil').
        tolerance_pct: Allowable relative percentage discrepancy between optimizer L/D
                       and re-analysis L/D (default: 0.1%).
        filename_prefix: Base name for output CAD files (default: 'wing_optimized').

    Returns:
        MaterializedWingResult: Complete record of the materialized CAD files, final spec,
                                and aerodynamic consistency verification.

    Raises:
        WingMaterializerError: If base_spec is not a wing, geometry generation/export fails,
                               or re-analysis fails.
    """
    if base_spec.component != "wing":
        raise WingMaterializerError(
            f"materialize_optimal_wing requires component='wing', got '{base_spec.component}'."
        )

    # 1. Build the revised final specification
    final_spec = copy.deepcopy(base_spec)
    try:
        naca_float = float(optimization_result.optimal_naca_airfoil)
    except (ValueError, TypeError) as exc:
        raise WingMaterializerError(
            f"Invalid optimal_naca_airfoil in optimization_result: {optimization_result.optimal_naca_airfoil!r}"
        ) from exc

    final_spec.parameters["naca_airfoil"] = naca_float

    # 2. Ensure output directory exists
    try:
        os.makedirs(output_dir, exist_ok=True)
    except OSError as exc:
        raise WingMaterializerError(f"Failed to create output directory '{output_dir}': {exc}") from exc

    # 3. Generate the 3D solid geometry
    geom_agent = GeometryAgent()
    try:
        part = geom_agent.generate(final_spec)
    except GeometryValidationError as exc:
        raise WingMaterializerError(
            f"Geometry validation failed for optimized wing spec: {exc}"
        ) from exc
    except Exception as exc:
        raise WingMaterializerError(
            f"Unexpected error during wing geometry generation: {exc}"
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
        raise WingMaterializerError(f"Failed to export wing CAD artifacts: {exc}") from exc

    # 5. Re-analysis on the final spec at the optimizer's optimal angle of attack
    try:
        reanalysis = evaluate_wing_aero(
            final_spec,
            cruise_velocity_mps=cruise_velocity_mps,
            alpha_deg=optimization_result.optimal_alpha_deg,
            backend=backend,
        )
    except Exception as exc:
        raise WingMaterializerError(f"Aerodynamic re-analysis failed on final spec: {exc}") from exc

    # 6. Consistency check
    opt_l_d = optimization_result.max_l_over_d
    if opt_l_d != 0:
        discrepancy_pct = abs(reanalysis.l_over_d - opt_l_d) / abs(opt_l_d) * 100.0
    else:
        discrepancy_pct = abs(reanalysis.l_over_d - opt_l_d) * 100.0

    reanalysis_matches_optimum = discrepancy_pct <= tolerance_pct

    return MaterializedWingResult(
        optimization_result=optimization_result,
        final_spec=final_spec,
        step_path=step_path,
        stl_path=stl_path,
        threemf_path=threemf_path,
        reanalysis=reanalysis,
        reanalysis_matches_optimum=reanalysis_matches_optimum,
        l_over_d_discrepancy_pct=discrepancy_pct,
    )
