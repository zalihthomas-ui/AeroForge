"""End-to-end v0.2 demonstration: a wing planform (mission doc geometry
example, mission doc section 3.1):

    "Create a wing with span 1800 mm, root chord 240 mm, tip chord 140 mm,
    sweep 12 degrees, dihedral 4 degrees."
        -> Design Agent -> Geometry Agent -> STEP / STL / 3MF

Note: this is a CAD-only planform approximation (flat-plate thickness, no
airfoil section) — the Aerodynamics Agent that would make this
aerodynamically real doesn't exist yet. See docs/architecture/roadmap.md.

Run from the repo root: python examples/wing/run.py
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from backend.pipeline import run_pipeline  # noqa: E402

REQUIREMENT = (
    "Create a wing with span 1800 mm, root chord 240 mm, tip chord 140 mm, "
    "sweep 12 degrees, dihedral 4 degrees."
)


def main() -> None:
    output_dir = os.path.join(os.path.dirname(__file__), "output")
    result = run_pipeline(REQUIREMENT, output_dir)

    print(f"Component:  {result.spec.component}")
    print(f"Parameters: {result.spec.parameters}")
    print(f"STEP:       {result.step_path}")
    print(f"STL:        {result.stl_path}")
    print(f"3MF:        {result.threemf_path}")


if __name__ == "__main__":
    main()
