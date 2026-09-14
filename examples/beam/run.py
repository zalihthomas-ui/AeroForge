"""v0.5 demonstration: cantilever beam FEA (mission doc Phase 4 benchmark,
"Case 1: Cantilever beam") via the Structures Agent's real CalculiX solver.

Prints the FEA result alongside the closed-form Euler-Bernoulli comparison
that StructuralResult already computes -- this is the strongest validation
in the repo: exact classical beam theory, not an invariant or
cross-validation between two models.

This is a standalone structural case, independent of the CAD loop
(examples/bracket/, examples/wing/) -- it is not yet meshing/analyzing the
actual CAD geometry those produce. See docs/architecture/roadmap.md.

Run from the repo root: python examples/beam/run.py
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from agents.structures.agent import CALCULIX_AVAILABLE, StructuresAgent  # noqa: E402

LENGTH_MM = 1000.0
WIDTH_MM = 20.0
HEIGHT_MM = 10.0
FORCE_N = 100.0


def main() -> None:
    if not CALCULIX_AVAILABLE:
        print(
            "CalculiX (ccx.exe) not found -- install it with "
            "scripts/install_calculix_windows.sh, see vendor/calculix/README.md."
        )
        return

    agent = StructuresAgent()
    result = agent.evaluate_cantilever_beam(
        length_mm=LENGTH_MM, width_mm=WIDTH_MM, height_mm=HEIGHT_MM, force_n=FORCE_N
    )

    print(f"Cantilever beam: {LENGTH_MM:.0f}mm x {WIDTH_MM:.0f}mm x {HEIGHT_MM:.0f}mm, {FORCE_N:.0f}N tip load")
    print(f"FEA tip deflection:        {result.tip_deflection_mm:.4f} mm")
    print(f"Analytical (Euler-Bernoulli): {result.analytical_deflection_mm:.4f} mm")
    print(f"Error:                     {result.deflection_error_pct:.3f}%")
    print(f"Max bending stress (FEA):  {result.max_bending_stress_mpa:.2f} MPa")


if __name__ == "__main__":
    main()
