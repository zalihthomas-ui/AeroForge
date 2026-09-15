"""Wing Flagship Demo: Multidisciplinary UAV Wing Evaluation & Planform Sizing.

Integrates aerodynamic analysis (NeuralFoil/XFoil via AerodynamicsAgent),
3D parametric CAD geometry (build123d via GeometryAgent), and structural FEA
(CalculiX via StructuresAgent) into a closed-loop multidisciplinary sizing workflow.

Physics Formulation:
- Level cruise flight requires Lift == Weight (L_req = MTOW * g, where g = 9.81 m/s^2).
- Baseline reference wing (b = 1.8m, c_root = 0.24m, c_tip = 0.14m, NACA 0012, alpha = 4 deg, V = 25 m/s)
  produces ~65.7 N of lift, which fails to support a 12.0 kg UAV (L_req = 117.72 N).
- Closed-loop planform sizing scales root and tip chords by factor k in [1.0, 2.5]
  using bounded 1D root-finding (scipy.optimize.brentq) to achieve Lift == L_req.
- Sized wing preserves aspect ratio / taper characteristics while satisfying span constraints (b <= max_span)
  and is re-verified for structural safety factor (eta >= min_safety_factor) under aerodynamic loading.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

from scipy.optimize import brentq

from agents.geometry.wing import build_wing
from agents.structures.agent import (
    CALCULIX_AVAILABLE,
    StructuresAgent,
    StructuresEvaluationError,
    WingStructuralResult,
)
from engineering.analysis.wing_aero import WingAeroError, evaluate_wing_aero
from engineering.requirements.schema import EngineeringSpec


class WingFlagshipError(Exception):
    """Raised when flagship multidisciplinary evaluation or sizing fails."""

    pass


@dataclass
class WingDesignRequirement:
    """Multidisciplinary mission and structural requirements for a UAV wing."""

    mtow_kg: float
    cruise_velocity_mps: float
    max_span_mm: float
    min_safety_factor: float


@dataclass
class FlagshipDesignResult:
    """Multidisciplinary performance and adequacy evaluation result for a UAV wing design."""

    spec_parameters: dict[str, float]
    solid_volume_mm3: float  # informational CAD solid volume
    lift_n: float
    required_lift_n: float  # mtow_kg * 9.81
    lift_adequate: bool
    l_over_d: float
    safety_factor: float
    min_safety_factor: float
    safety_adequate: bool
    span_adequate: bool
    overall_status: str  # "PASS" or "FAIL"
    iterations: list[FlagshipDesignResult] = field(default_factory=list)


def evaluate_wing_design(
    spec: EngineeringSpec,
    requirement: WingDesignRequirement,
    alpha_deg: float = 4.0,
    backend: str = "neuralfoil",
    structures_agent: StructuresAgent | None = None,
) -> FlagshipDesignResult:
    """Evaluate a wing design against multidisciplinary aerodynamic, structural, and geometric requirements.

    Args:
        spec: Validated EngineeringSpec with component == 'wing'.
        requirement: WingDesignRequirement specifying MTOW, cruise velocity, max span, and safety factor.
        alpha_deg: Angle of attack in degrees (default: 4.0 deg).
        backend: Aerodynamics solver backend ('neuralfoil' or 'xfoil').
        structures_agent: Optional StructuresAgent instance (if None, instantiates StructuresAgent()).

    Returns:
        FlagshipDesignResult with aerodynamic, structural, and geometric metrics.

    Raises:
        WingFlagshipError: If inputs are invalid or solver evaluation fails.
    """
    if spec.component != "wing":
        raise WingFlagshipError(
            f"evaluate_wing_design requires component='wing', got '{spec.component}'."
        )

    wing_span = spec.parameters.get("wing_span")
    root_chord = spec.parameters.get("root_chord")
    tip_chord = spec.parameters.get("tip_chord")

    if wing_span is None or root_chord is None or tip_chord is None:
        raise WingFlagshipError(
            f"Wing spec is missing required parameters: wing_span={wing_span}, root_chord={root_chord}, tip_chord={tip_chord}."
        )

    if wing_span <= 0 or root_chord <= 0 or tip_chord <= 0:
        raise WingFlagshipError(
            f"Wing dimensions must be strictly positive: wing_span={wing_span}, root_chord={root_chord}, tip_chord={tip_chord}."
        )

    if requirement.mtow_kg <= 0:
        raise WingFlagshipError(f"mtow_kg must be strictly positive, got {requirement.mtow_kg}.")
    if requirement.cruise_velocity_mps <= 0:
        raise WingFlagshipError(f"cruise_velocity_mps must be strictly positive, got {requirement.cruise_velocity_mps}.")
    if requirement.max_span_mm <= 0:
        raise WingFlagshipError(f"max_span_mm must be strictly positive, got {requirement.max_span_mm}.")
    if requirement.min_safety_factor <= 0:
        raise WingFlagshipError(f"min_safety_factor must be strictly positive, got {requirement.min_safety_factor}.")

    required_lift_n = requirement.mtow_kg * 9.81

    # 1. Aerodynamic Evaluation
    try:
        aero = evaluate_wing_aero(
            spec,
            cruise_velocity_mps=requirement.cruise_velocity_mps,
            alpha_deg=alpha_deg,
            backend=backend,
        )
    except Exception as exc:
        raise WingFlagshipError(f"Aerodynamic evaluation failed: {exc}") from exc

    lift_n = aero.lift_n
    l_over_d = aero.l_over_d

    # 2. Informational CAD solid volume (build123d)
    try:
        part = build_wing(spec.parameters)
        solid_volume_mm3 = float(part.volume)
    except Exception as exc:
        raise WingFlagshipError(f"Geometry generation failed: {exc}") from exc

    # 3. Structural Evaluation (CalculiX FEA under computed aerodynamic lift)
    agent = structures_agent or StructuresAgent()
    try:
        struct_res = agent.evaluate_wing(
            spec,
            cruise_velocity_mps=requirement.cruise_velocity_mps,
            alpha_deg=alpha_deg,
            backend=backend,
        )
        safety_factor = struct_res.safety_factor
    except Exception as exc:
        raise WingFlagshipError(f"Structural evaluation failed: {exc}") from exc

    lift_adequate = bool(lift_n >= required_lift_n - 1e-6)
    safety_adequate = bool(safety_factor >= requirement.min_safety_factor - 1e-6)
    span_adequate = bool(wing_span <= requirement.max_span_mm + 1e-6)
    overall_status = "PASS" if (lift_adequate and safety_adequate and span_adequate) else "FAIL"

    return FlagshipDesignResult(
        spec_parameters=dict(spec.parameters),
        solid_volume_mm3=solid_volume_mm3,
        lift_n=lift_n,
        required_lift_n=required_lift_n,
        lift_adequate=lift_adequate,
        l_over_d=l_over_d,
        safety_factor=safety_factor,
        min_safety_factor=requirement.min_safety_factor,
        safety_adequate=safety_adequate,
        span_adequate=span_adequate,
        overall_status=overall_status,
        iterations=[],
    )


def find_passing_wing_design(
    base_spec: EngineeringSpec,
    requirement: WingDesignRequirement,
    alpha_deg: float = 4.0,
    backend: str = "neuralfoil",
    chord_scale_bounds: tuple[float, float] = (1.0, 2.5),
    structures_agent: StructuresAgent | None = None,
) -> FlagshipDesignResult:
    """Find a passing wing design by scaling chord dimensions to satisfy lift = MTOW * g.

    Preserves span and planform taper ratio while adjusting root and tip chords.
    Uses bounded 1D root-finding (scipy.optimize.brentq) to find the chord scale factor k.
    Re-verifies structural safety factor and geometrical constraints.

    Args:
        base_spec: Base EngineeringSpec with component == 'wing'.
        requirement: WingDesignRequirement specifying MTOW, cruise velocity, max span, and min safety factor.
        alpha_deg: Angle of attack in degrees (default: 4.0 deg).
        backend: Aerodynamics solver backend ('neuralfoil' or 'xfoil').
        chord_scale_bounds: (k_min, k_max) search interval for chord scaling factor (default: (1.0, 2.5)).
        structures_agent: Optional StructuresAgent instance for FEA evaluation.

    Returns:
        FlagshipDesignResult for the final sized wing, with iterations recording initial/intermediate evaluations.

    Raises:
        WingFlagshipError: If inputs are invalid, root-finding cannot bracket required lift, or evaluations fail.
    """
    if base_spec.component != "wing":
        raise WingFlagshipError(
            f"find_passing_wing_design requires component='wing', got '{base_spec.component}'."
        )

    if (
        not isinstance(chord_scale_bounds, (tuple, list))
        or len(chord_scale_bounds) != 2
        or chord_scale_bounds[0] <= 0
        or chord_scale_bounds[0] >= chord_scale_bounds[1]
    ):
        raise WingFlagshipError(
            f"Invalid chord_scale_bounds: {chord_scale_bounds}. Expected (k_min, k_max) with 0 < k_min < k_max."
        )

    base_root = base_spec.parameters.get("root_chord")
    base_tip = base_spec.parameters.get("tip_chord")
    base_span = base_spec.parameters.get("wing_span")

    if base_root is None or base_tip is None or base_span is None:
        raise WingFlagshipError(
            f"Base spec missing required parameters: root_chord={base_root}, tip_chord={base_tip}, wing_span={base_span}."
        )

    required_lift_n = requirement.mtow_kg * 9.81
    agent = structures_agent or StructuresAgent()

    # Track iteration history
    iterations: list[FlagshipDesignResult] = []

    # 1. Evaluate baseline initial design
    initial_res = evaluate_wing_design(
        base_spec,
        requirement,
        alpha_deg=alpha_deg,
        backend=backend,
        structures_agent=agent,
    )
    iterations.append(initial_res)

    if initial_res.overall_status == "PASS":
        # Already passing
        initial_res.iterations = iterations
        return initial_res

    # 2. Setup root finding over chord scale factor k
    k_min, k_max = float(chord_scale_bounds[0]), float(chord_scale_bounds[1])

    def make_scaled_spec(k: float) -> EngineeringSpec:
        s = copy.deepcopy(base_spec)
        s.parameters["root_chord"] = base_root * k
        s.parameters["tip_chord"] = base_tip * k
        return s

    def lift_residual(k: float) -> float:
        s = make_scaled_spec(k)
        aero = evaluate_wing_aero(
            s,
            cruise_velocity_mps=requirement.cruise_velocity_mps,
            alpha_deg=alpha_deg,
            backend=backend,
        )
        return aero.lift_n - required_lift_n

    f_min = lift_residual(k_min)
    f_max = lift_residual(k_max)

    if f_min * f_max > 0:
        raise WingFlagshipError(
            f"Chord scale bounds {chord_scale_bounds} do not bracket required lift ({required_lift_n:.2f} N). "
            f"Lift at k_min={k_min}: {f_min + required_lift_n:.2f} N, at k_max={k_max}: {f_max + required_lift_n:.2f} N."
        )

    # Solve for optimal k
    k_opt = float(brentq(lift_residual, k_min, k_max, xtol=1e-4, maxiter=25))

    # 3. Evaluate final sized design with full FEA structural and geometric verification
    final_spec = make_scaled_spec(k_opt)
    final_res = evaluate_wing_design(
        final_spec,
        requirement,
        alpha_deg=alpha_deg,
        backend=backend,
        structures_agent=agent,
    )
    final_res.iterations = iterations
    return final_res
