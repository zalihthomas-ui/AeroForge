"""Unit tests for the Aerodynamics Agent using NeuralFoil surrogate."""

import pytest
from agents.aerodynamics import (
    AeroResult,
    AerodynamicsAgent,
    AerodynamicsEvaluationError,
)


@pytest.fixture
def agent() -> AerodynamicsAgent:
    return AerodynamicsAgent()


def test_naca0012_symmetry_at_zero_alpha(agent: AerodynamicsAgent):
    """NACA 0012 is symmetric, so CL and CM must be approximately zero at alpha=0."""
    for reynolds in [1e5, 5e5, 1e6, 3e6]:
        res = agent.evaluate_naca_airfoil("naca0012", alpha_deg=0.0, reynolds=reynolds)
        assert isinstance(res, AeroResult)
        assert abs(res.cl) < 0.02, f"Expected CL ~ 0 at alpha=0, got {res.cl} (Re={reynolds})"
        assert abs(res.cm) < 0.02, f"Expected CM ~ 0 at alpha=0, got {res.cm} (Re={reynolds})"
        assert res.cd > 0.0, f"Expected CD > 0, got {res.cd}"
        assert 0.0 <= res.confidence <= 1.0


def test_monotonic_lift_curve_in_linear_regime(agent: AerodynamicsAgent):
    """CL should increase monotonically over small positive angles of attack (0 to 6 deg)."""
    alphas = [0.0, 2.0, 4.0, 6.0]
    results = [
        agent.evaluate_naca_airfoil("0012", alpha_deg=alpha, reynolds=1e6)
        for alpha in alphas
    ]

    cl_values = [r.cl for r in results]
    for i in range(len(cl_values) - 1):
        assert (
            cl_values[i + 1] > cl_values[i]
        ), f"CL did not increase monotonically: alpha={alphas[i]}->{cl_values[i]}, alpha={alphas[i+1]}->{cl_values[i+1]}"


def test_strictly_positive_drag(agent: AerodynamicsAgent):
    """Drag coefficient CD must always be strictly positive across varied conditions."""
    test_cases = [
        ("naca0012", 0.0, 1e6),
        ("naca0012", 5.0, 5e5),
        ("naca2412", 2.0, 1e6),
        ("naca4412", -2.0, 2e6),
    ]
    for designation, alpha, reynolds in test_cases:
        res = agent.evaluate_naca_airfoil(designation, alpha_deg=alpha, reynolds=reynolds)
        assert res.cd > 0.0, f"Expected CD > 0 for {designation} at alpha={alpha}, got {res.cd}"


def test_lift_to_drag_ratio_consistency(agent: AerodynamicsAgent):
    """L/D ratio must match cl / cd."""
    res = agent.evaluate_naca_airfoil("naca2412", alpha_deg=4.0, reynolds=1e6)
    assert res.l_over_d == pytest.approx(res.cl / res.cd, rel=1e-5)


def test_cambered_airfoil_positive_zero_alpha_lift(agent: AerodynamicsAgent):
    """Cambered airfoils (e.g. NACA 2412, NACA 4412) produce positive lift at alpha=0."""
    res_2412 = agent.evaluate_naca_airfoil("naca2412", alpha_deg=0.0, reynolds=1e6)
    res_4412 = agent.evaluate_naca_airfoil("naca4412", alpha_deg=0.0, reynolds=1e6)

    assert res_2412.cl > 0.1, f"Expected positive CL for NACA 2412 at alpha=0, got {res_2412.cl}"
    assert res_4412.cl > 0.2, f"Expected higher positive CL for NACA 4412 at alpha=0, got {res_4412.cl}"


def test_designation_formatting_variations(agent: AerodynamicsAgent):
    """Various casing and prefix formats should resolve to the same airfoil section."""
    res1 = agent.evaluate_naca_airfoil("0012", alpha_deg=2.0, reynolds=1e6)
    res2 = agent.evaluate_naca_airfoil("naca0012", alpha_deg=2.0, reynolds=1e6)
    res3 = agent.evaluate_naca_airfoil("NACA 0012", alpha_deg=2.0, reynolds=1e6)
    res4 = agent.evaluate_naca_airfoil("NACA0012", alpha_deg=2.0, reynolds=1e6)

    assert res1.cl == pytest.approx(res2.cl, abs=1e-5)
    assert res1.cl == pytest.approx(res3.cl, abs=1e-5)
    assert res1.cl == pytest.approx(res4.cl, abs=1e-5)


def test_reject_invalid_designations(agent: AerodynamicsAgent):
    """Malformed or non-NACA designations must raise AerodynamicsEvaluationError."""
    invalid_codes = [
        "",
        "   ",
        "invalid",
        "naca999999",
        "naca12",
        "12",
        "naca",
        "b737",
    ]
    for code in invalid_codes:
        with pytest.raises(AerodynamicsEvaluationError):
            agent.evaluate_naca_airfoil(code, alpha_deg=0.0, reynolds=1e6)


def test_reject_non_positive_reynolds(agent: AerodynamicsAgent):
    """Zero or negative Reynolds number must raise AerodynamicsEvaluationError."""
    with pytest.raises(AerodynamicsEvaluationError):
        agent.evaluate_naca_airfoil("naca0012", alpha_deg=0.0, reynolds=0.0)

    with pytest.raises(AerodynamicsEvaluationError):
        agent.evaluate_naca_airfoil("naca0012", alpha_deg=0.0, reynolds=-1000.0)
