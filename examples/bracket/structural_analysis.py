"""v0.7 demonstration: real 3D solid FEA on the ACTUAL bracket geometry
(agents/geometry/bracket.py's build_bracket(), not a validation fixture),
under a real bolted-mounting load case.

There's no closed-form solution for this geometry (unlike the cantilever
beam or the plate-with-hole), so it's validated two ways instead: exact
force equilibrium (sum of reaction forces must equal the applied load) and
mesh convergence at two densities. See
agents/structures/bracket_mesh.py's module docstring for the full
convergence sweep and an honest note on why peak stress doesn't always
converge as cleanly as deflection (a real FEA stress singularity at the
fixed-hole-rim boundary corner, not a bug).

Run from the repo root: python examples/bracket/structural_analysis.py
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from agents.structures.agent import CALCULIX_AVAILABLE, StructuresAgent  # noqa: E402

LENGTH_MM = 100.0
WIDTH_MM = 80.0
THICKNESS_MM = 5.0
HOLE_DIAMETER_MM = 8.0
HOLE_COUNT = 4
APPLIED_FORCE_N = 500.0


def main() -> None:
    if not CALCULIX_AVAILABLE:
        print(
            "CalculiX (ccx.exe) not found -- install it with "
            "scripts/install_calculix_windows.sh, see vendor/calculix/README.md."
        )
        return

    agent = StructuresAgent()
    result = agent.evaluate_bracket(
        length_mm=LENGTH_MM,
        width_mm=WIDTH_MM,
        thickness_mm=THICKNESS_MM,
        hole_diameter_mm=HOLE_DIAMETER_MM,
        hole_count=HOLE_COUNT,
        applied_force_n=APPLIED_FORCE_N,
    )

    print(
        f"Bracket {LENGTH_MM:.0f}x{WIDTH_MM:.0f}x{THICKNESS_MM:.0f}mm, "
        f"{HOLE_COUNT} x {HOLE_DIAMETER_MM:.0f}mm holes (bolted/fixed), "
        f"{APPLIED_FORCE_N:.0f}N top-face load"
    )
    print(f"Max stress (fine mesh):    {result.max_stress_mpa:.4f} MPa")
    print(f"Max deflection:            {result.max_deflection_mm:.6f} mm")
    print(f"Equilibrium error:         {result.equilibrium_error_pct:.4f}% (exact check)")
    print(f"Mesh converged:            {result.mesh_converged}")
    print(
        f"  coarse -> fine max stress: {result.coarse_mesh_max_stress_mpa:.4f} -> "
        f"{result.fine_mesh_max_stress_mpa:.4f} MPa"
    )


if __name__ == "__main__":
    main()
