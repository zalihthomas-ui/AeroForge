"""v0.4 demonstration: NACA 0012 aerodynamic evaluation (mission doc Phase 3
benchmark) via the Aerodynamics Agent's NeuralFoil surrogate.

DISCLAIMER: NeuralFoil is a validated neural surrogate, not a first-principles
CFD/panel-method solver (see agents/aerodynamics/agent.py). Real XFOIL/
OpenFOAM/SU2 integration remains future work.

This is a standalone airfoil-section case per the mission doc's own Phase 3
plan ("begin with a well-understood benchmark: NACA 0012"). It is not wired
into the Design Agent -> Geometry Agent CAD loop -- the wing geometry built
in examples/wing/ has no airfoil section yet (flat-plate approximation).

Run from the repo root: python examples/airfoil/run.py
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from agents.aerodynamics.agent import AerodynamicsAgent  # noqa: E402

NACA_DESIGNATION = "0012"
REYNOLDS = 1_000_000
ALPHA_SWEEP_DEG = [0, 2, 4, 6, 8, 10]


def main() -> None:
    agent = AerodynamicsAgent()

    print(f"NACA {NACA_DESIGNATION}  Re={REYNOLDS:,.0f}")
    print(f"{'alpha (deg)':>12} {'CL':>8} {'CD':>10} {'CM':>8} {'L/D':>8} {'confidence':>11}")
    for alpha in ALPHA_SWEEP_DEG:
        result = agent.evaluate_naca_airfoil(NACA_DESIGNATION, alpha, REYNOLDS)
        print(
            f"{alpha:>12} {result.cl:>8.3f} {result.cd:>10.5f} "
            f"{result.cm:>8.3f} {result.l_over_d:>8.2f} {result.confidence:>11.3f}"
        )


if __name__ == "__main__":
    main()
