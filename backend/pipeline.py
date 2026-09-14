"""Wires the Design Agent and Geometry Agent into the v0.1 CAD MVP loop:

    Prompt -> Design Agent -> Geometry Agent -> build123d -> STEP / STL

This module has no FastAPI/HTTP concerns — it's the shared core used by both
backend/main.py and examples/bracket/run.py.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from agents.design.agent import DesignAgent
from agents.geometry.agent import GeometryAgent
from cad.exporters import export_step, export_stl, export_3mf
from engineering.requirements.schema import EngineeringSpec


@dataclass
class PipelineResult:
    spec: EngineeringSpec
    step_path: str
    stl_path: str
    threemf_path: str


def run_pipeline(requirement_text: str, output_dir: str) -> PipelineResult:
    """Run the full v0.1 loop for a single requirement and write exports to
    `output_dir`. Raises whatever DesignAgent/GeometryAgent raise on invalid
    input or invalid geometry — callers should not swallow those silently.
    """
    os.makedirs(output_dir, exist_ok=True)

    spec = DesignAgent().parse(requirement_text)
    part = GeometryAgent().generate(spec)

    step_path = os.path.join(output_dir, f"{spec.component}.step")
    stl_path = os.path.join(output_dir, f"{spec.component}.stl")
    threemf_path = os.path.join(output_dir, f"{spec.component}.3mf")

    export_step(part, step_path)
    export_stl(part, stl_path)
    export_3mf(part, threemf_path)

    return PipelineResult(
        spec=spec,
        step_path=step_path,
        stl_path=stl_path,
        threemf_path=threemf_path,
    )
