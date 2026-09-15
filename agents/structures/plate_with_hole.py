"""Plate-with-a-hole geometry and gmsh meshing for the Structures Agent's
Kirsch stress-concentration validation (see agents/structures/agent.py's
`evaluate_plate_with_hole`).

This is a validation fixture, not a mission-doc CAD component — it exists
to prove the real solid-FEA (gmsh mesh -> CalculiX C3D10) pipeline against
Kirsch's classical closed-form stress-concentration solution, the same way
the cantilever beam proves the 1D-beam pipeline against Euler-Bernoulli
theory. It is deliberately NOT registered as an agents/geometry component.

Two gotchas specific to meshing real CAD geometry for CalculiX, on top of
the SOLVER=SPOOLES one in vendor/calculix/README.md:

1. gmsh's own Abaqus/.inp writer switches to "only write grouped entities"
   mode as soon as ANY Physical Group is defined, silently dropping
   ungrouped entities. Every entity ccx.exe needs (the volume, and the
   fixed/loaded faces for node sets) must therefore be grouped.
2. That same writer also emits CPS6 plane-stress shell elements for any 2D
   physical group — harmless in the .inp file itself, but ccx.exe rejects
   a 3D analysis containing them ("*ERROR in gen3delem..."). So this never
   hands gmsh's raw .inp output to ccx.exe directly: it extracts just the
   *NODE and *ELEMENT, type=C3D10 (volume) blocks from that text and lets
   the caller build its own deck around them (BOUNDARY/CLOAD/STEP cards),
   the same way the beam's .inp is hand-assembled.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import gmsh
from build123d import Align, Box, Cylinder, Part, Pos

from agents.structures.inp_utils import extract_mesh_blocks
from cad.exporters import export_step

# Mesh refinement (gmsh Distance+Threshold fields) relative to hole size and
# plate width. Tuned empirically: this converges the stress concentration
# factor to within ~2% of Kirsch's Kt=3.0 across hole diameters from 3% to
# 8% of plate width, at a few tens of seconds' solve time — see
# agents/structures/agent.py's module docstring for the numbers observed.
_SIZE_MIN_RATIO = 1 / 20  # of hole_diameter_mm
_SIZE_MAX_RATIO = 1 / 16  # of width_mm
_DIST_MIN_RATIO = 0.5  # of hole_radius_mm
_DIST_MAX_RATIO = 5.0  # of hole_radius_mm

_BOUNDING_BOX_EPS_MM = 1e-3


@dataclass
class PlateMesh:
    """A C3D10 tet mesh of a plate with a central hole, as CalculiX .inp
    text blocks, plus the node sets needed to apply boundary conditions."""

    node_lines: list[str]
    element_lines: list[str]
    max_node_id: int
    fixed_node_ids: list[int]
    loaded_node_ids: list[int]
    center_node_id: int
    offset_node_id: int


def build_plate_with_hole(
    width_mm: float, height_mm: float, thickness_mm: float, hole_diameter_mm: float
) -> Part:
    """A rectangular plate in the X-Y plane, X spanning [0, width_mm], with
    a centered through-hole at (width_mm/2, 0) — loading direction is X."""
    hole_radius = hole_diameter_mm / 2
    plate = Box(width_mm, height_mm, thickness_mm, align=(Align.MIN, Align.CENTER, Align.CENTER))
    plate -= Pos(width_mm / 2, 0, 0) * Cylinder(hole_radius, thickness_mm * 1.2)
    return plate


def mesh_plate_with_hole(
    step_path: str,
    width_mm: float,
    height_mm: float,
    thickness_mm: float,
    hole_diameter_mm: float,
) -> PlateMesh:
    """Mesh a plate-with-hole STEP file with quadratic (C3D10) tets refined
    near the hole, identifying faces by location (not assumed numbering)."""
    hole_radius = hole_diameter_mm / 2
    eps = _BOUNDING_BOX_EPS_MM

    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("plate_with_hole")
        gmsh.model.occ.importShapes(step_path)
        gmsh.model.occ.synchronize()

        volumes = gmsh.model.getEntities(dim=3)
        fixed_faces = gmsh.model.getEntitiesInBoundingBox(
            -eps, -height_mm / 2 - eps, -thickness_mm / 2 - eps,
            eps, height_mm / 2 + eps, thickness_mm / 2 + eps,
            dim=2,
        )
        loaded_faces = gmsh.model.getEntitiesInBoundingBox(
            width_mm - eps, -height_mm / 2 - eps, -thickness_mm / 2 - eps,
            width_mm + eps, height_mm / 2 + eps, thickness_mm / 2 + eps,
            dim=2,
        )
        hole_faces = gmsh.model.getEntitiesInBoundingBox(
            width_mm / 2 - hole_radius - eps, -hole_radius - eps, -thickness_mm / 2 - eps,
            width_mm / 2 + hole_radius + eps, hole_radius + eps, thickness_mm / 2 + eps,
            dim=2,
        )

        # Every entity ccx.exe needs must be grouped (gotcha 1 above).
        gmsh.model.addPhysicalGroup(3, [tag for _, tag in volumes])
        fixed_group = gmsh.model.addPhysicalGroup(2, [tag for _, tag in fixed_faces])
        loaded_group = gmsh.model.addPhysicalGroup(2, [tag for _, tag in loaded_faces])

        gmsh.model.mesh.field.add("Distance", 1)
        gmsh.model.mesh.field.setNumbers(1, "SurfacesList", [tag for _, tag in hole_faces])
        gmsh.model.mesh.field.add("Threshold", 2)
        gmsh.model.mesh.field.setNumber(2, "InField", 1)
        gmsh.model.mesh.field.setNumber(2, "SizeMin", hole_diameter_mm * _SIZE_MIN_RATIO)
        gmsh.model.mesh.field.setNumber(2, "SizeMax", width_mm * _SIZE_MAX_RATIO)
        gmsh.model.mesh.field.setNumber(2, "DistMin", hole_radius * _DIST_MIN_RATIO)
        gmsh.model.mesh.field.setNumber(2, "DistMax", hole_radius * _DIST_MAX_RATIO)
        gmsh.model.mesh.field.setAsBackgroundMesh(2)
        gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
        gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
        gmsh.option.setNumber("Mesh.ElementOrder", 2)
        gmsh.model.mesh.generate(3)

        fixed_node_tags, fixed_coords = gmsh.model.mesh.getNodesForPhysicalGroup(2, fixed_group)
        loaded_node_tags, _ = gmsh.model.mesh.getNodesForPhysicalGroup(2, loaded_group)
        fixed_node_ids = [int(tag) for tag in fixed_node_tags]
        loaded_node_ids = [int(tag) for tag in loaded_node_tags]
        fixed_coords = fixed_coords.reshape(-1, 3)

        raw_inp_path = os.path.splitext(step_path)[0] + "_raw.inp"
        gmsh.write(raw_inp_path)
    finally:
        gmsh.finalize()

    # Rigid-body constraint nodes (see agent.py's BOUNDARY card comment):
    # closest-to-centroid node pins Y/Z translation, a second node offset
    # in Y pins the remaining X-rotation (twist) degree of freedom.
    center_node_id = _closest_node(fixed_node_ids, fixed_coords, (0.0, 0.0, 0.0))
    offset_node_id = _closest_node(fixed_node_ids, fixed_coords, (0.0, height_mm * 0.3, 0.0))

    node_lines, element_lines = extract_mesh_blocks(raw_inp_path)
    max_node_id = int(node_lines[-1].split(",")[0])

    return PlateMesh(
        node_lines=node_lines,
        element_lines=element_lines,
        max_node_id=max_node_id,
        fixed_node_ids=fixed_node_ids,
        loaded_node_ids=loaded_node_ids,
        center_node_id=center_node_id,
        offset_node_id=offset_node_id,
    )


def _closest_node(node_ids: list[int], coords, target: tuple[float, float, float]) -> int:
    best_index = min(
        range(len(node_ids)),
        key=lambda i: sum((coords[i][k] - target[k]) ** 2 for k in range(3)),
    )
    return node_ids[best_index]


