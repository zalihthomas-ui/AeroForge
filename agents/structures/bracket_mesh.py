"""Bracket geometry meshing for the Structures Agent's real mounting-bracket
solid FEA (see agents/structures/agent.py's `evaluate_bracket`).

Reuses agents/geometry/bracket.py's `build_bracket()` directly rather than
duplicating the bracket shape — this meshes the actual Geometry Agent
component, unlike plate_with_hole.py's dedicated validation fixture.
Mirrors plate_with_hole.py's meshing approach (gmsh C3D10 tets, the same
two .inp gotchas — see that module's docstring), but with a different
boundary-condition setup: all 4 hole cylindrical faces are treated as
rigid bolted connections (fully fixed) rather than a tension face, and the
top face carries a distributed transverse (-Z) load instead of tension.

## Mesh convergence sweep (reference bracket: 100x80x5mm, four 8mm holes,
## 500N top-face load)

There's no closed-form answer to validate this case against (unlike the
beam or plate-with-hole), so `evaluate_bracket` instead runs at two mesh
densities and checks that both max stress and max deflection settle.
`density_factor` sweep actually run during development (smaller = finer):

| density_factor | elements | max deflection (mm) | max von Mises (MPa) |
|---|---|---|---|
| 2.0 | 8,075   | 0.000956 | 5.808 |
| 1.5 | 18,397  | 0.000815 | 6.044 |
| 1.0 | 58,036  | 0.000721 | 6.866 |
| 0.9 | 78,011  | 0.000715 | 7.087 |
| 0.8 | 109,530 | 0.000692 | 7.340 |

Deflection converges smoothly and monotonically (17.3% -> 13.0% -> 0.8% ->
3.9% change per step). Max von Mises stress increases monotonically too,
but its step-to-step % change does NOT shrink monotonically (4.1% -> 13.6%
-> 3.1% -> 3.4%) — consistent with the fixed-hole-rim edge (where the
boundary condition jumps from fully-fixed to free right at a sharp
geometric corner) being a classic FEA stress-singularity location, where
peak nodal/Gauss-point stress has no guaranteed mesh-independent limit.
`evaluate_bracket` ships the 1.0/0.9 pair (both changes comfortably under
10%) since that's where it happened to observe convergence, not because a
finer pair is guaranteed to also converge — see agents/structures/
agent.py's module docstring.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import gmsh

from agents.geometry.bracket import hole_center_x_positions
from agents.structures.inp_utils import extract_mesh_blocks

# Mesh refinement (gmsh Distance+Threshold fields) relative to hole size and
# bracket length, same style as plate_with_hole.py. `density_factor` scales
# both size bounds uniformly so evaluate_bracket can mesh twice (coarse,
# fine) for a mesh-convergence check — there's no closed-form answer for a
# 4-hole bracket under an arbitrary load, so convergence is the validation
# target here instead of a Kirsch-style theoretical value.
_SIZE_MIN_RATIO = 1 / 15  # of hole_diameter_mm
_SIZE_MAX_RATIO = 1 / 10  # of length_mm
_DIST_MIN_RATIO = 0.5  # of hole_radius_mm
_DIST_MAX_RATIO = 5.0  # of hole_radius_mm

_BOUNDING_BOX_EPS_MM = 1e-3


@dataclass
class BracketMesh:
    """A C3D10 tet mesh of the bracket, as CalculiX .inp text blocks, plus
    the node sets needed for boundary conditions."""

    node_lines: list[str]
    element_lines: list[str]
    max_node_id: int
    fixed_node_ids: list[int]
    loaded_node_ids: list[int]


def mesh_bracket(
    step_path: str,
    length_mm: float,
    width_mm: float,
    thickness_mm: float,
    hole_diameter_mm: float,
    hole_count: int,
    density_factor: float = 1.0,
) -> BracketMesh:
    """Mesh a bracket STEP file with quadratic (C3D10) tets refined near
    each hole, identifying the hole and top faces by location."""
    hole_radius = hole_diameter_mm / 2
    eps = _BOUNDING_BOX_EPS_MM

    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("bracket")
        gmsh.model.occ.importShapes(step_path)
        gmsh.model.occ.synchronize()

        volumes = gmsh.model.getEntities(dim=3)

        hole_faces: list[tuple[int, int]] = []
        for x_center in hole_center_x_positions(length_mm, hole_count):
            hole_faces.extend(
                gmsh.model.getEntitiesInBoundingBox(
                    x_center - hole_radius - eps, -hole_radius - eps, -thickness_mm / 2 - eps,
                    x_center + hole_radius + eps, hole_radius + eps, thickness_mm / 2 + eps,
                    dim=2,
                )
            )

        top_faces = gmsh.model.getEntitiesInBoundingBox(
            -length_mm / 2 - eps, -width_mm / 2 - eps, thickness_mm / 2 - eps,
            length_mm / 2 + eps, width_mm / 2 + eps, thickness_mm / 2 + eps,
            dim=2,
        )

        # Every entity ccx.exe needs must be grouped (gmsh's .inp writer
        # silently drops ungrouped entities once any physical group exists
        # — see plate_with_hole.py's module docstring).
        gmsh.model.addPhysicalGroup(3, [tag for _, tag in volumes])
        fixed_group = gmsh.model.addPhysicalGroup(2, [tag for _, tag in hole_faces])
        loaded_group = gmsh.model.addPhysicalGroup(2, [tag for _, tag in top_faces])

        gmsh.model.mesh.field.add("Distance", 1)
        gmsh.model.mesh.field.setNumbers(1, "SurfacesList", [tag for _, tag in hole_faces])
        gmsh.model.mesh.field.add("Threshold", 2)
        gmsh.model.mesh.field.setNumber(2, "InField", 1)
        gmsh.model.mesh.field.setNumber(2, "SizeMin", hole_diameter_mm * _SIZE_MIN_RATIO * density_factor)
        gmsh.model.mesh.field.setNumber(2, "SizeMax", length_mm * _SIZE_MAX_RATIO * density_factor)
        gmsh.model.mesh.field.setNumber(2, "DistMin", hole_radius * _DIST_MIN_RATIO)
        gmsh.model.mesh.field.setNumber(2, "DistMax", hole_radius * _DIST_MAX_RATIO)
        gmsh.model.mesh.field.setAsBackgroundMesh(2)
        gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
        gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
        gmsh.option.setNumber("Mesh.ElementOrder", 2)
        gmsh.model.mesh.generate(3)

        fixed_node_tags, _ = gmsh.model.mesh.getNodesForPhysicalGroup(2, fixed_group)
        loaded_node_tags, _ = gmsh.model.mesh.getNodesForPhysicalGroup(2, loaded_group)
        fixed_node_ids = [int(tag) for tag in fixed_node_tags]

        # The hole rims are shared edges between each hole's cylindrical
        # face and the top face, so some "loaded" nodes are also "fixed"
        # ones. A node that's both is fully constrained (u=0), so any
        # *CLOAD there is a no-op that CalculiX does not fold back into the
        # reaction-force total — discovered via the equilibrium check
        # itself (sum(RF) was short of the applied load by exactly the
        # overlap node count's share of it). Excluding them keeps the
        # total applied load physically meaningful and the reaction sum
        # exact, rather than silently losing a few percent of it.
        fixed_node_id_set = set(fixed_node_ids)
        loaded_node_ids = [int(tag) for tag in loaded_node_tags if int(tag) not in fixed_node_id_set]

        raw_inp_path = os.path.splitext(step_path)[0] + f"_raw_{density_factor}.inp"
        gmsh.write(raw_inp_path)
    finally:
        gmsh.finalize()

    node_lines, element_lines = extract_mesh_blocks(raw_inp_path)
    max_node_id = int(node_lines[-1].split(",")[0])

    return BracketMesh(
        node_lines=node_lines,
        element_lines=element_lines,
        max_node_id=max_node_id,
        fixed_node_ids=fixed_node_ids,
        loaded_node_ids=loaded_node_ids,
    )
