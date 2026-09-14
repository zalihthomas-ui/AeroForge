"""Tests for the real XFOIL backend (agents.aerodynamics.agent.XFOIL_AVAILABLE).

Skipped entirely when the vendored xfoil wheel isn't installed (e.g. CI on
ubuntu-latest, or any machine other than Windows x64 + CPython 3.13) — see
vendor/xfoil/README.md. These are NOT NeuralFoil tests; see test_agent.py
for the always-available surrogate backend.
"""

import pytest

from agents.aerodynamics import AerodynamicsAgent, AerodynamicsEvaluationError
from agents.aerodynamics.agent import XFOIL_AVAILABLE

pytestmark = pytest.mark.skipif(
    not XFOIL_AVAILABLE,
    reason="real xfoil package not installed (vendor/xfoil/*.whl) on this platform",
)


@pytest.fixture
def agent() -> AerodynamicsAgent:
    return AerodynamicsAgent()


def test_naca0012_symmetry_at_zero_alpha_xfoil(agent: AerodynamicsAgent):
    """Real XFOIL should also show near-zero CL/CM for symmetric NACA 0012 at alpha=0."""
    res = agent.evaluate_naca_airfoil("naca0012", alpha_deg=0.0, reynolds=1e6, backend="xfoil")
    assert abs(res.cl) < 0.01, f"Expected CL ~ 0 at alpha=0, got {res.cl}"
    assert abs(res.cm) < 0.01, f"Expected CM ~ 0 at alpha=0, got {res.cm}"
    assert res.cd > 0.0
    assert res.backend == "xfoil"
    assert res.confidence == 1.0


def test_monotonic_lift_curve_xfoil(agent: AerodynamicsAgent):
    """CL should increase monotonically over 0-6 deg, same invariant as the surrogate test."""
    alphas = [0.0, 2.0, 4.0, 6.0]
    cl_values = [
        agent.evaluate_naca_airfoil("0012", alpha_deg=a, reynolds=1e6, backend="xfoil").cl
        for a in alphas
    ]
    for i in range(len(cl_values) - 1):
        assert cl_values[i + 1] > cl_values[i], (
            f"CL did not increase monotonically: alpha={alphas[i]}->{cl_values[i]}, "
            f"alpha={alphas[i+1]}->{cl_values[i+1]}"
        )


def test_xfoil_and_neuralfoil_cross_validate_on_naca0012(agent: AerodynamicsAgent):
    """The real solver and the surrogate should agree closely on NACA 0012.

    This is the strongest validation we have of the NeuralFoil surrogate on
    this machine: not a memorized published number, but agreement between
    two independently-implemented aerodynamic models.
    """
    for alpha in [0.0, 2.0, 4.0, 6.0, 8.0]:
        xfoil_result = agent.evaluate_naca_airfoil(
            "naca0012", alpha_deg=alpha, reynolds=1e6, backend="xfoil"
        )
        neuralfoil_result = agent.evaluate_naca_airfoil(
            "naca0012", alpha_deg=alpha, reynolds=1e6, backend="neuralfoil"
        )
        assert xfoil_result.cl == pytest.approx(neuralfoil_result.cl, abs=0.05), (
            f"CL mismatch at alpha={alpha}: xfoil={xfoil_result.cl}, "
            f"neuralfoil={neuralfoil_result.cl}"
        )
        assert xfoil_result.cd == pytest.approx(neuralfoil_result.cd, abs=0.005), (
            f"CD mismatch at alpha={alpha}: xfoil={xfoil_result.cd}, "
            f"neuralfoil={neuralfoil_result.cd}"
        )


def test_xfoil_does_not_converge_raises_clear_error(agent: AerodynamicsAgent):
    """Deep post-stall angles should raise, not silently return garbage/NaN."""
    with pytest.raises(AerodynamicsEvaluationError, match="did not converge"):
        agent.evaluate_naca_airfoil("naca0012", alpha_deg=45.0, reynolds=1e6, backend="xfoil")
