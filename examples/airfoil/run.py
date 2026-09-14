"""v0.4 demonstration: NACA 0012 aerodynamic evaluation (mission doc Phase 3
benchmark) via the Aerodynamics Agent.

Runs both backends when available:
- "neuralfoil": always available, a validated neural surrogate.
- "xfoil": the real XFOIL Fortran solver. Only available if the vendored
  wheel is installed (Windows x64 + CPython 3.13 only — see
  vendor/xfoil/README.md); falls back to neuralfoil-only output otherwise.

This is a standalone airfoil-section case per the mission doc's own Phase 3
plan ("begin with a well-understood benchmark: NACA 0012"). It is not wired
into the Design Agent -> Geometry Agent CAD loop -- the wing geometry built
in examples/wing/ has no airfoil section yet (flat-plate approximation).

Run from the repo root: python examples/airfoil/run.py
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from agents.aerodynamics.agent import XFOIL_AVAILABLE, AerodynamicsAgent  # noqa: E402

NACA_DESIGNATION = "0012"
REYNOLDS = 1_000_000
ALPHA_SWEEP_DEG = [0, 2, 4, 6, 8, 10]


def main() -> None:
    agent = AerodynamicsAgent()
    backends = ["neuralfoil", "xfoil"] if XFOIL_AVAILABLE else ["neuralfoil"]
    if not XFOIL_AVAILABLE:
        print(
            "(real xfoil not installed -- showing NeuralFoil surrogate only; "
            "see vendor/xfoil/README.md to install it on Windows x64 + CPython 3.13)\n"
        )

    print(f"NACA {NACA_DESIGNATION}  Re={REYNOLDS:,.0f}")
    header = f"{'alpha (deg)':>12}"
    for backend in backends:
        header += f" {'CL (' + backend + ')':>18} {'CD (' + backend + ')':>18}"
    print(header)

    for alpha in ALPHA_SWEEP_DEG:
        row = f"{alpha:>12}"
        for backend in backends:
            result = agent.evaluate_naca_airfoil(NACA_DESIGNATION, alpha, REYNOLDS, backend=backend)
            row += f" {result.cl:>18.3f} {result.cd:>18.5f}"
        print(row)


if __name__ == "__main__":
    main()
