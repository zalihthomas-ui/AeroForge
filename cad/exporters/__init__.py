"""Export a build123d Part to STEP, STL, and 3MF."""

from __future__ import annotations

import os

from build123d import Mesher, Part
from build123d import export_step as _export_step
from build123d import export_stl as _export_stl


def _ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def export_step(part: Part, path: str) -> None:
    """Export `part` to a STEP file at `path`."""
    _ensure_parent_dir(path)
    _export_step(part, path)


def export_stl(part: Part, path: str) -> None:
    """Export `part` to an STL file at `path`."""
    _ensure_parent_dir(path)
    _export_stl(part, path)


def export_3mf(part: Part, path: str) -> None:
    """Export `part` to a 3MF file at `path`."""
    _ensure_parent_dir(path)
    mesher = Mesher()
    mesher.add_shape(part)
    mesher.write(path)


__all__ = ["export_step", "export_stl", "export_3mf"]
