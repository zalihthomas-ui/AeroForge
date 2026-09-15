"""Wing aerodynamic optimization module.

Performs closed-loop aerodynamic optimization to find the optimal airfoil section
and angle of attack for maximum lift-to-drag ratio (L/D).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
import re

from scipy.optimize import minimize_scalar

from engineering.analysis.wing_aero import WingAeroError, evaluate_wing_aero
from engineering.requirements.schema import EngineeringSpec

DEFAULT_CANDIDATE_AIRFOILS: list[str] = ["0009", "0012", "2412", "4412", "2415"]


@dataclass
class AirfoilCandidateResult:
    """Optimization result for an individual candidate airfoil."""

    naca_airfoil: str
    optimal_alpha_deg: float
    max_l_over_d: float
    cl_at_optimum: float
    cd_at_optimum: float


@dataclass
class WingOptimizationResult:
    """Overall result of multi-candidate wing aerodynamic optimization."""

    optimal_naca_airfoil: str
    optimal_alpha_deg: float
    max_l_over_d: float
    cl_at_optimum: float
    cd_at_optimum: float
    all_candidates: list[AirfoilCandidateResult]


def optimize_wing_for_max_l_over_d(
    base_spec: EngineeringSpec,
    candidate_naca_airfoils: list[str] | None = None,
    alpha_bounds_deg: tuple[float, float] = (-2.0, 12.0),
    cruise_velocity_mps: float = 25.0,
    backend: str = "neuralfoil",
) -> WingOptimizationResult:
    """Optimize wing angle of attack and select the best airfoil for maximum L/D.

    For each candidate NACA airfoil, finds the angle of attack that maximizes L/D
    using bounded continuous scalar minimization (scipy.optimize.minimize_scalar),
    then selects the candidate yielding the highest overall L/D.

    Args:
        base_spec: EngineeringSpec with component == "wing".
        candidate_naca_airfoils: List of candidate 4-digit NACA designations
                                 (default: ["0009", "0012", "2412", "4412", "2415"]).
        alpha_bounds_deg: Search range for angle of attack (min_alpha, max_alpha) in degrees.
        cruise_velocity_mps: Cruise airspeed in m/s (default: 25.0 m/s).
        backend: Aerodynamics solver backend ("neuralfoil" or "xfoil").

    Returns:
        WingOptimizationResult: Optimal airfoil, optimal alpha, peak L/D, and all candidate evaluations.

    Raises:
        WingAeroError: If base_spec is not a wing, candidate list is empty,
                       or alpha bounds/flight conditions are invalid.
    """
    if base_spec.component != "wing":
        raise WingAeroError(
            f"optimize_wing_for_max_l_over_d requires component='wing', got '{base_spec.component}'."
        )

    if candidate_naca_airfoils is None:
        candidate_naca_airfoils = list(DEFAULT_CANDIDATE_AIRFOILS)

    if not candidate_naca_airfoils:
        raise WingAeroError("Candidate NACA airfoil list cannot be empty.")

    if (
        not isinstance(alpha_bounds_deg, (tuple, list))
        or len(alpha_bounds_deg) != 2
        or alpha_bounds_deg[0] >= alpha_bounds_deg[1]
    ):
        raise WingAeroError(
            f"Invalid alpha_bounds_deg: {alpha_bounds_deg}. Expected (min_alpha, max_alpha) with min < max."
        )

    if cruise_velocity_mps <= 0:
        raise WingAeroError(
            f"Cruise velocity must be strictly positive. Got {cruise_velocity_mps} m/s."
        )

    all_candidate_results: list[AirfoilCandidateResult] = []

    for candidate in candidate_naca_airfoils:
        match = re.search(r"(\d{4})", str(candidate))
        if not match:
            raise WingAeroError(
                f"Invalid candidate NACA airfoil code: '{candidate}'. Expected 4 digits (e.g. '2412')."
            )
        digits = match.group(1)
        naca_float = float(digits)
        norm_str = f"{int(naca_float):04d}"

        cand_spec = copy.deepcopy(base_spec)
        cand_spec.parameters["naca_airfoil"] = naca_float

        def objective(alpha: float) -> float:
            try:
                summary = evaluate_wing_aero(
                    cand_spec,
                    cruise_velocity_mps=cruise_velocity_mps,
                    alpha_deg=float(alpha),
                    backend=backend,
                )
                return -summary.l_over_d
            except Exception:
                return 1e6

        res = minimize_scalar(
            objective,
            bounds=alpha_bounds_deg,
            method="bounded",
        )

        opt_alpha = float(res.x)
        best_summary = evaluate_wing_aero(
            cand_spec,
            cruise_velocity_mps=cruise_velocity_mps,
            alpha_deg=opt_alpha,
            backend=backend,
        )

        cand_result = AirfoilCandidateResult(
            naca_airfoil=norm_str,
            optimal_alpha_deg=opt_alpha,
            max_l_over_d=best_summary.l_over_d,
            cl_at_optimum=best_summary.cl,
            cd_at_optimum=best_summary.cd,
        )
        all_candidate_results.append(cand_result)

    best_candidate = max(all_candidate_results, key=lambda c: c.max_l_over_d)

    return WingOptimizationResult(
        optimal_naca_airfoil=best_candidate.naca_airfoil,
        optimal_alpha_deg=best_candidate.optimal_alpha_deg,
        max_l_over_d=best_candidate.max_l_over_d,
        cl_at_optimum=best_candidate.cl_at_optimum,
        cd_at_optimum=best_candidate.cd_at_optimum,
        all_candidates=all_candidate_results,
    )
