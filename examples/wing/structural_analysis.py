"""v0.10 demonstration: real 3D solid FEA on the ACTUAL wing geometry
(agents/geometry/wing.py's build_wing(), real NACA airfoil cross-sections,
not a flat-plate approximation), loaded by its own computed aerodynamic
lift -- the first time an aerodynamic result drives a structural load in
this project rather than a hand-picked force.

No closed-form solution exists for this geometry, so validated by exact
force equilibrium and mesh convergence, same methodology as the bracket.
See agents/structures/wing_mesh.py's module docstring for two real
meshing findings this surfaced (trailing-edge sliver elements, no root
face on the mirrored wing solid).

Run from the repo root: python examples/wing/structural_analysis.py
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from agents.structures.agent import CALCULIX_AVAILABLE, StructuresAgent  # noqa: E402
from engineering.requirements.schema import EngineeringSpec  # noqa: E402

WING_SPEC = EngineeringSpec(
    component="wing",
    parameters={
        "wing_span": 1800.0,
        "root_chord": 240.0,
        "tip_chord": 140.0,
        "sweep": 12.0,
        "dihedral": 4.0,
        "naca_airfoil": 12.0,
    },
)


def main() -> None:
    if not CALCULIX_AVAILABLE:
        print(
            "CalculiX (ccx.exe) not found -- install it with "
            "scripts/install_calculix_windows.sh, see vendor/calculix/README.md."
        )
        return

    agent = StructuresAgent()
    result = agent.evaluate_wing(WING_SPEC)

    print("Wing: span 1800mm, root chord 240mm, tip chord 140mm, NACA 0012")
    print("Load: real aerodynamic lift at 25 m/s cruise (via wing_aero.evaluate_wing_aero)")
    print(f"Hotspot stress:     {result.hotspot_stress_mpa:.4f} MPa")
    print(f"Raw peak stress:    {result.raw_peak_stress_mpa:.4f} MPa (informational, not mesh-convergent)")
    print(f"Max deflection:     {result.max_deflection_mm:.4f} mm")
    print(f"Safety factor:      {result.safety_factor:.1f} (aluminum 6061, 1g cruise -- expect large margin)")
    print(f"Equilibrium error:  {result.equilibrium_error_pct:.4f}% (exact check)")
    print(f"Mesh converged:     {result.mesh_converged}")


if __name__ == "__main__":
    main()
