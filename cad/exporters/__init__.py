"""Export build123d geometry to STEP, STL, 3MF and DXF.

STEP files are written in AP214 (``AUTOMOTIVE_DESIGN``) with explicit
millimetre units. Assemblies keep their tree, part names and colours, so CAD
tools such as SolidWorks, Fusion, CATIA or FreeCAD show e.g.
``Wing > Ribs > Rib_3_Stbd`` instead of anonymous ``COMPOUND`` entries.

Imported STEP geometry is exact B-rep (measurable, drawable, meshable, usable in
downstream FEA) but carries no feature history: a CAD tool cannot replay the
sketches and lofts that made it. Parametric changes belong in AeroForge's input
parameters, followed by a re-export.
"""

from __future__ import annotations

import os
import re

from build123d import Compound, ExportDXF, Face, Mesher, Part, Shape, Unit
from build123d import export_step as _export_step
from build123d import export_stl as _export_stl


def _ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _safe_filename(label: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", label).strip("_") or "part"


def export_step(part: Shape, path: str) -> None:
    """Export a part or labelled assembly to a millimetre STEP file at `path`."""
    _ensure_parent_dir(path)
    _export_step(part, path, unit=Unit.MM)


def export_step_assembly(assembly: Compound, path: str) -> None:
    """Export a labelled assembly (assembly -> groups -> parts) to one STEP file.

    Part and group names come from each shape's ``label`` and colours from its
    ``color``; unlabelled shapes fall back to the exporter's generic names.
    """
    export_step(assembly, path)


def export_parts_step(assembly: Compound, directory: str) -> list[str]:
    """Write every leaf solid of a labelled assembly to its own STEP file.

    Files are named after the part labels (``Rib_3_Stbd.step``); duplicate
    labels get a numeric suffix. Returns the written paths in assembly order.
    """
    os.makedirs(directory, exist_ok=True)
    written: list[str] = []
    seen: dict[str, int] = {}

    def walk(shape: Shape) -> None:
        children = list(getattr(shape, "children", ()) or ())
        if children:
            for child in children:
                walk(child)
            return
        name = _safe_filename(shape.label or "part")
        seen[name] = seen.get(name, 0) + 1
        if seen[name] > 1:
            name = f"{name}_{seen[name]}"
        path = os.path.join(directory, f"{name}.step")
        # A shape still attached to its assembly tree fails to write on its own;
        # export a detached wrapper of the same geometry instead.
        try:
            detached = type(shape)(shape.wrapped)
        except TypeError:
            # primitives (Box, Cylinder, ...) take dimensions, not a TopoDS shape
            detached = Part(shape.wrapped)
        detached.label, detached.color = shape.label, shape.color
        export_step(detached, path)
        written.append(path)

    walk(assembly)
    return written


def export_profile_dxf(face: Face, path: str) -> None:
    """Export a planar profile (e.g. a rib flat pattern in the XY plane) to DXF in mm."""
    _ensure_parent_dir(path)
    dxf = ExportDXF(unit=Unit.MM)
    dxf.add_shape(face)
    dxf.write(path)


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


__all__ = [
    "export_3mf",
    "export_parts_step",
    "export_profile_dxf",
    "export_step",
    "export_step_assembly",
    "export_stl",
]
