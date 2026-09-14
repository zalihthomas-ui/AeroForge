"""Wing aerodynamic analysis module.

Couples the wing EngineeringSpec geometry parameters (wing_span, root_chord,
tip_chord, sweep, dihedral, naca_airfoil) to the Aerodynamics Agent to compute
operating Reynolds number, aerodynamic coefficients (CL, CD, L/D), and total lift
and drag forces.
"""

from __future__ import annotations

from dataclasses import dataclass

from agents.aerodynamics.agent import AerodynamicsAgent, AerodynamicsEvaluationError
from engineering.requirements.schema import EngineeringSpec


class WingAeroError(AerodynamicsEvaluationError):
    """Raised when wing aerodynamic analysis fails due to invalid spec or non-physical parameters."""

    pass


@dataclass
class WingAeroSummary:
    """Summary of wing aerodynamic performance at specified cruise conditions."""

    naca_airfoil: str  # e.g. "0012"
    reynolds_number: float  # computed operating Reynolds number
    cl: float  # section lift coefficient
    cd: float  # section drag coefficient
    l_over_d: float  # lift-to-drag ratio
    lift_n: float  # total wing lift force in Newtons
    drag_n: float  # total wing drag force in Newtons
    backend: str  # "neuralfoil" or "xfoil"


def evaluate_wing_aero(
    spec: EngineeringSpec,
    cruise_velocity_mps: float = 25.0,
    alpha_deg: float = 4.0,
    air_density_kgm3: float = 1.225,
    kinematic_viscosity_m2s: float = 1.46e-5,
    backend: str = "neuralfoil",
) -> WingAeroSummary:
    """Evaluate aerodynamic performance of a wing defined by an EngineeringSpec.

    Args:
        spec: Validated EngineeringSpec with component == "wing".
        cruise_velocity_mps: Cruise airspeed in m/s (default: 25.0 m/s).
        alpha_deg: Angle of attack in degrees (default: 4.0 deg).
        air_density_kgm3: Air density in kg/m^3 (default: 1.225 kg/m^3 standard sea level).
        kinematic_viscosity_m2s: Air kinematic viscosity in m^2/s (default: 1.46e-5 m^2/s).
        backend: "neuralfoil" (default) or "xfoil".

    Returns:
        WingAeroSummary: Aerodynamic coefficients and dimensional lift/drag forces.

    Raises:
        WingAeroError: If component is not 'wing', required parameters are missing/non-positive,
                       or flight conditions are invalid.
    """
    if spec.component != "wing":
        raise WingAeroError(
            f"evaluate_wing_aero requires an EngineeringSpec with component='wing', got '{spec.component}'."
        )

    wing_span = spec.parameters.get("wing_span")
    root_chord = spec.parameters.get("root_chord")
    tip_chord = spec.parameters.get("tip_chord")
    naca_airfoil_val = spec.parameters.get("naca_airfoil", 12.0)

    if wing_span is None or root_chord is None or tip_chord is None:
        raise WingAeroError(
            f"Wing spec is missing required geometric parameters. "
            f"Got: wing_span={wing_span}, root_chord={root_chord}, tip_chord={tip_chord}."
        )

    if wing_span <= 0 or root_chord <= 0 or tip_chord <= 0:
        raise WingAeroError(
            f"Wing dimensions must be strictly positive. "
            f"Got: wing_span={wing_span}, root_chord={root_chord}, tip_chord={tip_chord}."
        )

    if cruise_velocity_mps <= 0:
        raise WingAeroError(
            f"Cruise velocity must be strictly positive. Got {cruise_velocity_mps} m/s."
        )
    if air_density_kgm3 <= 0:
        raise WingAeroError(
            f"Air density must be strictly positive. Got {air_density_kgm3} kg/m^3."
        )
    if kinematic_viscosity_m2s <= 0:
        raise WingAeroError(
            f"Kinematic viscosity must be strictly positive. Got {kinematic_viscosity_m2s} m^2/s."
        )

    # Convert geometry from mm to meters
    root_chord_m = root_chord / 1000.0
    tip_chord_m = tip_chord / 1000.0
    span_m = wing_span / 1000.0

    # Reynolds number based on root chord
    reynolds_number = cruise_velocity_mps * root_chord_m / kinematic_viscosity_m2s

    # Planform area (trapezoidal wing, full span tip-to-tip)
    planform_area_m2 = span_m * (root_chord_m + tip_chord_m) / 2.0

    # Dynamic pressure q = 0.5 * rho * V^2
    dynamic_pressure_pa = 0.5 * air_density_kgm3 * (cruise_velocity_mps**2)

    # Format 4-digit NACA string (e.g. 12.0 -> "0012", 2412.0 -> "2412")
    naca_str = f"{int(naca_airfoil_val):04d}"

    agent = AerodynamicsAgent()
    try:
        aero_result = agent.evaluate_naca_airfoil(
            naca_str,
            alpha_deg=alpha_deg,
            reynolds=reynolds_number,
            backend=backend,
        )
    except AerodynamicsEvaluationError as exc:
        raise WingAeroError(f"Aerodynamics evaluation failed for wing spec: {exc}") from exc

    lift_n = aero_result.cl * dynamic_pressure_pa * planform_area_m2
    drag_n = aero_result.cd * dynamic_pressure_pa * planform_area_m2

    return WingAeroSummary(
        naca_airfoil=naca_str,
        reynolds_number=reynolds_number,
        cl=aero_result.cl,
        cd=aero_result.cd,
        l_over_d=aero_result.l_over_d,
        lift_n=lift_n,
        drag_n=drag_n,
        backend=aero_result.backend,
    )
