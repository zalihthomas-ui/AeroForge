"""Unit tests for wing aerodynamic coupling analysis."""

import pytest
from agents.aerodynamics.agent import XFOIL_AVAILABLE
from engineering.analysis.wing_aero import (
    WingAeroError,
    WingAeroSummary,
    evaluate_wing_aero,
)
from engineering.requirements.schema import EngineeringSpec


def _wing_spec(**params: float) -> EngineeringSpec:
    default_params = {
        "wing_span": 1800.0,
        "root_chord": 240.0,
        "tip_chord": 140.0,
        "sweep": 12.0,
        "dihedral": 4.0,
        "naca_airfoil": 12.0,
    }
    return EngineeringSpec(component="wing", parameters={**default_params, **params})


def test_reference_wing_aero_evaluation():
    """Reference UAV wing at cruise conditions produces physically sane aeroperformance."""
    spec = _wing_spec()
    res = evaluate_wing_aero(
        spec,
        cruise_velocity_mps=25.0,
        alpha_deg=4.0,
        air_density_kgm3=1.225,
        kinematic_viscosity_m2s=1.46e-5,
        backend="neuralfoil",
    )

    assert isinstance(res, WingAeroSummary)
    assert res.naca_airfoil == "0012"
    assert res.backend == "neuralfoil"

    # Re = V * root_chord / nu = 25 * 0.24 / 1.46e-5 = 410,958.9
    assert res.reynolds_number == pytest.approx(410958.9, rel=1e-3)

    assert res.cl > 0.0
    assert res.cd > 0.0
    assert res.l_over_d > 0.0
    assert res.lift_n > 0.0
    assert res.drag_n > 0.0

    # L/D ratio consistency
    assert res.lift_n / res.drag_n == pytest.approx(res.l_over_d, rel=1e-5)
    assert res.cl / res.cd == pytest.approx(res.l_over_d, rel=1e-5)


def test_cambered_airfoil_increases_lift():
    """Cambered NACA 2412 wing produces higher lift than symmetric NACA 0012 wing."""
    spec_0012 = _wing_spec(naca_airfoil=12.0)
    spec_2412 = _wing_spec(naca_airfoil=2412.0)

    res_0012 = evaluate_wing_aero(spec_0012, cruise_velocity_mps=25.0, alpha_deg=4.0)
    res_2412 = evaluate_wing_aero(spec_2412, cruise_velocity_mps=25.0, alpha_deg=4.0)

    assert res_0012.naca_airfoil == "0012"
    assert res_2412.naca_airfoil == "2412"

    assert res_2412.cl > res_0012.cl
    assert res_2412.lift_n > res_0012.lift_n


def test_reject_non_wing_component():
    """Evaluating a non-wing component must raise WingAeroError."""
    bracket_spec = EngineeringSpec(
        component="bracket",
        parameters={"length": 100.0, "width": 80.0, "thickness": 5.0},
    )
    with pytest.raises(WingAeroError) as exc:
        evaluate_wing_aero(bracket_spec)
    assert "component='wing'" in str(exc.value)


def test_reject_missing_or_non_positive_geometry():
    """Missing or non-positive geometric parameters must raise WingAeroError."""
    incomplete_spec = EngineeringSpec(
        component="wing",
        parameters={"wing_span": 1800.0, "root_chord": 240.0},
    )
    with pytest.raises(WingAeroError):
        evaluate_wing_aero(incomplete_spec)

    negative_span_spec = EngineeringSpec(
        component="wing",
        parameters={"wing_span": -100.0, "root_chord": 240.0, "tip_chord": 140.0},
    )
    with pytest.raises(WingAeroError):
        evaluate_wing_aero(negative_span_spec)


def test_reject_invalid_flight_conditions():
    """Non-positive velocity, density, or viscosity must raise WingAeroError."""
    spec = _wing_spec()

    with pytest.raises(WingAeroError):
        evaluate_wing_aero(spec, cruise_velocity_mps=0.0)

    with pytest.raises(WingAeroError):
        evaluate_wing_aero(spec, air_density_kgm3=-1.0)

    with pytest.raises(WingAeroError):
        evaluate_wing_aero(spec, kinematic_viscosity_m2s=0.0)


@pytest.mark.skipif(not XFOIL_AVAILABLE, reason="xfoil wheel not installed")
def test_wing_aero_evaluation_with_xfoil_backend():
    """If xfoil is installed, evaluate_wing_aero works with backend='xfoil'."""
    spec = _wing_spec()
    res = evaluate_wing_aero(spec, backend="xfoil")
    assert res.backend == "xfoil"
    assert res.lift_n > 0.0
    assert res.drag_n > 0.0
