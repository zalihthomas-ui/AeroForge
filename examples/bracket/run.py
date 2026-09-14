"""End-to-end v0.1 demonstration (mission doc Phase 1 example):

    "Create a 100 x 80 x 5 mm mounting bracket with four 8 mm holes."
        -> Design Agent -> Geometry Agent -> STEP / STL / 3MF

Run from the repo root: python examples/bracket/run.py
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from backend.pipeline import run_pipeline  # noqa: E402

REQUIREMENT = "Create a 100 x 80 x 5 mm mounting bracket with four 8 mm holes."


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
