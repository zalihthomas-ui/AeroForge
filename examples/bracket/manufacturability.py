"""v0.9 demonstration: CNC manufacturability checks on the actual bracket
geometry (mission doc Phase 6, first Manufacturing Agent).

Both checks are real, sourced CNC design-for-manufacturability
conventions (see agents/manufacturing/agent.py's module docstring), not
invented heuristics. Also runs a deliberately non-manufacturable case
(thick plate, narrow holes) to show the drill-ratio check actually
catching something.

Run from the repo root: python examples/bracket/manufacturability.py
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from agents.manufacturing.agent import ManufacturingAgent  # noqa: E402


def report(label: str, **kwargs) -> None:
    agent = ManufacturingAgent()
    result = agent.evaluate_bracket_cnc(**kwargs)
    print(f"\n{label}")
    print(f"  Geometry: {kwargs}")
    print(
        f"  Drill ratio:  {result.depth_to_diameter_ratio:.3f} "
        f"(max {result.max_standard_ratio:.1f}) -> drillable={result.standard_drillable}"
    )
    print(
        f"  Edge margin:  {result.hole_edge_margin_mm:.2f} mm "
        f"-> adequate={result.edge_margin_adequate}"
    )
    print(f"  Overall manufacturable: {result.overall_manufacturable}")


def main() -> None:
    report(
        "Reference bracket (mission doc example)",
        length_mm=100.0, width_mm=80.0, thickness_mm=5.0,
        hole_diameter_mm=8.0, hole_count=4,
    )
    report(
        "Thick plate, narrow holes (should fail drill ratio)",
        length_mm=100.0, width_mm=80.0, thickness_mm=30.0,
        hole_diameter_mm=4.0, hole_count=4,
    )


if __name__ == "__main__":
    main()
