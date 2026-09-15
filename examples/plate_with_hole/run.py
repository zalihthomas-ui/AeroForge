"""v0.6 demonstration: real 3D solid FEA validated against Kirsch's classical
stress-concentration solution (Kt=3.0 for a small circular hole in a wide
plate under uniaxial tension).

Unlike examples/beam/run.py (1D CalculiX beam elements on a parametric
beam), this meshes an actual build123d solid (a plate with a hole) via
gmsh into quadratic tetrahedra and solves it as real 3D solid FEA -- the
first time this project analyzes actual CAD geometry rather than a
parametric idealization. See docs/architecture/roadmap.md's v0.6 section.

Run from the repo root: python examples/plate_with_hole/run.py
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from agents.structures.agent import CALCULIX_AVAILABLE, StructuresAgent  # noqa: E402

WIDTH_MM = 200.0
HEIGHT_MM = 200.0
THICKNESS_MM = 5.0
HOLE_DIAMETER_MM = 10.0  # 5% of width -- well within the small-hole approximation
TENSILE_STRESS_MPA = 100.0


def main() -> None:
    if not CALCULIX_AVAILABLE:
        print(
            "CalculiX (ccx.exe) not found -- install it with "
            "scripts/install_calculix_windows.sh, see vendor/calculix/README.md."
        )
        return

    agent = StructuresAgent()
    result = agent.evaluate_plate_with_hole(
        width_mm=WIDTH_MM,
        height_mm=HEIGHT_MM,
        thickness_mm=THICKNESS_MM,
        hole_diameter_mm=HOLE_DIAMETER_MM,
        tensile_stress_mpa=TENSILE_STRESS_MPA,
    )

    print(
        f"Plate {WIDTH_MM:.0f}x{HEIGHT_MM:.0f}x{THICKNESS_MM:.0f}mm, "
        f"{HOLE_DIAMETER_MM:.0f}mm hole ({HOLE_DIAMETER_MM / WIDTH_MM * 100:.0f}% of width), "
        f"{TENSILE_STRESS_MPA:.0f}MPa remote tension"
    )
    print(f"Max stress (FEA):         {result.max_stress_mpa:.2f} MPa")
    print(f"Nominal stress:           {result.nominal_stress_mpa:.2f} MPa")
    print(f"Stress concentration Kt:  {result.stress_concentration_factor:.4f}")
    print(f"Kirsch's theoretical Kt:  {result.theoretical_kt:.4f}")
    print(f"Error:                    {result.error_pct:.3f}%")


if __name__ == "__main__":
    main()
