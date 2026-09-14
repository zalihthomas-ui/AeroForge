"""Tests for cad/exporters: STEP, STL, and 3MF export produce non-empty files."""

from __future__ import annotations

import os

from cad.exporters import export_3mf, export_step, export_stl
from engineering.requirements.schema import EngineeringSpec

from agents.geometry.agent import GeometryAgent


def _reference_bracket():
    spec = EngineeringSpec(
        component="bracket",
        parameters={
            "length": 100.0,
            "width": 80.0,
            "thickness": 5.0,
            "hole_diameter": 8.0,
            "hole_count": 4,
        },
    )
    return GeometryAgent().generate(spec)


def test_export_step_writes_a_non_empty_file(tmp_path) -> None:
    path = tmp_path / "bracket.step"
    export_step(_reference_bracket(), str(path))

    assert path.exists()
    assert path.stat().st_size > 0


def test_export_stl_writes_a_non_empty_file(tmp_path) -> None:
    path = tmp_path / "bracket.stl"
    export_stl(_reference_bracket(), str(path))

    assert path.exists()
    assert path.stat().st_size > 0


def test_export_3mf_writes_a_non_empty_file(tmp_path) -> None:
    path = tmp_path / "bracket.3mf"
    export_3mf(_reference_bracket(), str(path))

    assert path.exists()
    assert path.stat().st_size > 0


def test_export_creates_missing_parent_directories(tmp_path) -> None:
    path = tmp_path / "nested" / "dir" / "bracket.step"
    export_step(_reference_bracket(), str(path))

    assert path.exists()
    assert os.path.isdir(tmp_path / "nested" / "dir")
