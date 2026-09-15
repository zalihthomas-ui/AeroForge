"""Wing geometry meshing for the Structures Agent's real wing solid FEA
(see agents/structures/agent.py's `evaluate_wing`).

Reuses agents/geometry/wing.py's `build_wing()` directly rather than
duplicating the wing shape — this meshes the actual Geometry Agent
component (real NACA airfoil cross-sections lofted root-to-tip and
mirrored, not a flat-plate approximation). Mirrors bracket_mesh.py's
overall approach (gmsh C3D10 tets, the same two .inp gotchas — see
plate_with_hole.py's module docstring) but with two differences specific
to this geometry:

1. **No face exists at the root (y=0).** build_wing() mirrors and fuses
   both wing halves into one continuous solid, so after that boolean
   union y=0 is purely interior — there's a closed perimeter *curve*
   there (where the two halves' faces meet) but no 2D *face*, so there's
   nothing to apply a boundary condition to directly, and no guarantee a
   volume mesher places any nodes exactly on that plane. This module
   instead intersects the full wing with a half-space box (X/Z Box,
   Y in [0, huge]) to get back a genuine half-wing solid *with* a real
   planar face at y=0 covering the whole root cross-section — verified
   to have exactly half the full wing's volume. Meshing only this half
   is also standard practice for a symmetric structure under symmetric
   loading (see agent.py's module docstring on the symmetry-plane BC this
   enables).

2. **Faces are identified by surface normal direction, not just location.**
   The real airfoil loft produces roughly 40 narrow BSPLINE strip faces
   per side (one per polygon edge in the airfoil's point cloud), not one
   flat top/bottom face like the bracket. "Top surface" (for the lift
   load) is identified via gmsh's own `getNormal` at each face's
   parametric midpoint: faces with a normal Z-component above
   `_TOP_SURFACE_NZ_THRESHOLD` are treated as top surface; this cleanly
   separates ~38 upper-camber faces from ~38 lower-camber faces plus a
   handful of near-vertical faces (leading/trailing edge, tip cap) that
   are neither. Each top-surface node's spanwise (Y) coordinate is
   collected alongside it (`WingMesh.top_surface_y_mm`) so
   agent.py's `_build_wing_input_deck` can weight the lift load
   elliptically rather than uniformly across the span.

3. **Mesh sizing must be curvature-adaptive, globally — not the bracket's
   local Distance+Threshold refinement.** A real NACA airfoil's trailing
   edge is only ~0.25% of chord thick (e.g. ~0.6mm for a 240mm root
   chord), far thinner than any uniform size reasonable for the rest of
   the wing. This was found the hard way: a uniform-away-from-root
   Distance+Threshold field (the bracket/plate approach) produced meshes
   ccx.exe rejected outright ("nonpositive jacobian determinant"), and
   root-caused to a handful of genuinely negative-volume ("sliver") tets
   from gmsh's own linear tetrahedralizer — confirmed present even before
   quadratic-order curving, and unaffected by tightening the trailing-
   edge size floor alone. The cause: gmsh's per-entity background field
   silently overrides its own automatic curvature-based sizing rather
   than combining with it, so the custom field's coarser SizeMax was
   winning right at the razor-thin trailing edge. Combining them properly
   via a dedicated `Curvature` field + `Min` field was correct in
   principle but too expensive to compute on this geometry (didn't
   finish in 10+ minutes). The fix that actually works: drop the custom
   Distance+Threshold field entirely and rely solely on gmsh's global
   `Mesh.MeshSizeFromCurvature` / `MeshSizeMin` / `MeshSizeMax` options —
   confirmed zero negative-volume elements, fast (<1s to mesh). This
   sacrifices the bracket-style *extra* refinement specifically at the
   root/BC region, but curvature-adaptive sizing already resolves the
   root cross-section's own curvature reasonably, and `density_factor`
   still scales the two size bounds together for the convergence check.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import gmsh
from build123d import Align, Box, Part

from agents.structures.inp_utils import extract_mesh_blocks

# Global curvature-adaptive mesh sizing relative to root chord — see this
# module's docstring for why a bracket-style local Distance+Threshold
# field doesn't work here. `_CURVATURE_ELEMENTS_PER_2PI` is gmsh's
# "elements per full circle of curvature" quality knob
# (Mesh.MeshSizeFromCurvature); higher = finer near curved features.
_SIZE_MIN_RATIO = 1 / 480  # of root_chord_mm — resolves the thin trailing edge
_SIZE_MAX_RATIO = 1 / 6  # of root_chord_mm
_CURVATURE_ELEMENTS_PER_2PI = 20

# A face is "top surface" if its normal's Z-component exceeds this —
# separates upper-camber faces from lower-camber and near-vertical
# (leading/trailing edge, tip cap) faces.
_TOP_SURFACE_NZ_THRESHOLD = 0.1

_BOUNDING_BOX_EPS_MM = 1e-3

# Half-space cutting box: generously larger than any realistic wing so the
# intersection is bounded only by the actual wing geometry, not this box.
_HALF_SPACE_MARGIN_MM = 2000.0


@dataclass
class WingMesh:
    """A C3D10 tet mesh of the half-wing (root to tip), as CalculiX .inp
    text blocks, plus the node sets needed for boundary conditions.

    `top_surface_y_mm` is parallel to `top_surface_node_ids` (same order,
    same length) — each node's spanwise position, needed to weight the
    lift load elliptically (see agent.py's `_build_wing_input_deck`)."""

    node_lines: list[str]
    element_lines: list[str]
    max_node_id: int
    root_node_ids: list[int]
    top_surface_node_ids: list[int]
    top_surface_y_mm: list[float]
    center_node_id: int
    offset_node_id: int


def build_half_wing(wing_part: Part, half_span_mm: float, root_chord_mm: float) -> Part:
    """Intersect the full (mirrored) wing with a half-space to recover a
    half-wing solid with a genuine planar face at the root (y=0)."""
    box_x = root_chord_mm + _HALF_SPACE_MARGIN_MM
    box_y = half_span_mm + _HALF_SPACE_MARGIN_MM
    box_z = _HALF_SPACE_MARGIN_MM
    half_space = Box(box_x, box_y, box_z, align=(Align.MIN, Align.MIN, Align.CENTER))
    return wing_part & half_space


def mesh_half_wing(
    step_path: str, half_span_mm: float, root_chord_mm: float, density_factor: float = 1.0
) -> WingMesh:
    """Mesh a half-wing STEP file (see build_half_wing) with quadratic
    (C3D10) tets, curvature-adaptively sized (see this module's
    docstring), identifying the root face (for the symmetry BC) and
    top-surface faces (for the lift load) by location and surface normal
    respectively. `density_factor` scales the mesh size bounds uniformly
    (smaller = finer), so evaluate_wing can mesh twice (coarse, fine) for
    a mesh-convergence check, same as bracket_mesh.py's mesh_bracket."""
    eps = _BOUNDING_BOX_EPS_MM

    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("half_wing")
        gmsh.model.occ.importShapes(step_path)
        gmsh.model.occ.synchronize()

        volumes = gmsh.model.getEntities(dim=3)
        all_faces = gmsh.model.getEntities(dim=2)

        root_faces = gmsh.model.getEntitiesInBoundingBox(
            -eps, -eps, -_HALF_SPACE_MARGIN_MM,
            root_chord_mm + _HALF_SPACE_MARGIN_MM, eps, _HALF_SPACE_MARGIN_MM,
            dim=2,
        )
        root_tags = {tag for _, tag in root_faces}

        top_faces = []
        for dim, tag in all_faces:
            if tag in root_tags:
                continue
            p_min, p_max = gmsh.model.getParametrizationBounds(dim, tag)
            u_mid = (p_min[0] + p_max[0]) / 2
            v_mid = (p_min[1] + p_max[1]) / 2
            normal = gmsh.model.getNormal(tag, [u_mid, v_mid])
            if normal[2] > _TOP_SURFACE_NZ_THRESHOLD:
                top_faces.append((dim, tag))

        # Every entity ccx.exe needs must be grouped (gmsh's .inp writer
        # silently drops ungrouped entities once any physical group exists
        # — see plate_with_hole.py's module docstring).
        gmsh.model.addPhysicalGroup(3, [tag for _, tag in volumes])
        root_group = gmsh.model.addPhysicalGroup(2, [tag for _, tag in root_faces])
        top_group = gmsh.model.addPhysicalGroup(2, [tag for _, tag in top_faces])

        # Global curvature-adaptive sizing only — see this module's
        # docstring point 3 for why a custom background field (the
        # bracket/plate approach) doesn't work here: it silently overrides
        # gmsh's automatic curvature sizing instead of combining with it,
        # which is fatal right at the razor-thin trailing edge.
        # `density_factor` scales both bounds together for the
        # convergence check.
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", _CURVATURE_ELEMENTS_PER_2PI)
        gmsh.option.setNumber("Mesh.MeshSizeMin", root_chord_mm * _SIZE_MIN_RATIO * density_factor)
        gmsh.option.setNumber("Mesh.MeshSizeMax", root_chord_mm * _SIZE_MAX_RATIO * density_factor)
        gmsh.option.setNumber("Mesh.ElementOrder", 2)
        gmsh.model.mesh.generate(3)

        root_node_tags, root_coords = gmsh.model.mesh.getNodesForPhysicalGroup(2, root_group)
        top_node_tags, top_coords = gmsh.model.mesh.getNodesForPhysicalGroup(2, top_group)
        root_node_ids = [int(tag) for tag in root_node_tags]
        root_coords = root_coords.reshape(-1, 3)
        top_coords = top_coords.reshape(-1, 3)

        # Some top-surface nodes lie on the root-face perimeter (shared
        # edge); a node that's both fixed and loaded silently drops its
        # applied load from the reaction-force total (the exact bug found
        # and fixed on the bracket) — excluded here from the start.
        root_node_id_set = set(root_node_ids)
        top_surface_node_ids: list[int] = []
        top_surface_y_mm: list[float] = []
        for tag, coord in zip(top_node_tags, top_coords):
            tag = int(tag)
            if tag not in root_node_id_set:
                top_surface_node_ids.append(tag)
                top_surface_y_mm.append(float(coord[1]))

        raw_inp_path = os.path.splitext(step_path)[0] + "_raw.inp"
        gmsh.write(raw_inp_path)
    finally:
        gmsh.finalize()

    # Minimal rigid-body constraints beyond the symmetry face's UY=0 (see
    # agent.py's module docstring): one node's X/Z translation, a second
    # node's Z to remove the remaining Y-axis rotation — same pattern as
    # plate_with_hole.py's center_node_id/offset_node_id.
    center_node_id = _closest_node(root_node_ids, root_coords, (root_chord_mm * 0.25, 0.0, 0.0))
    offset_node_id = _closest_node(root_node_ids, root_coords, (root_chord_mm * 0.75, 0.0, 0.0))

    node_lines, element_lines = extract_mesh_blocks(raw_inp_path)
    max_node_id = int(node_lines[-1].split(",")[0])

    return WingMesh(
        node_lines=node_lines,
        element_lines=element_lines,
        max_node_id=max_node_id,
        root_node_ids=root_node_ids,
        top_surface_node_ids=top_surface_node_ids,
        top_surface_y_mm=top_surface_y_mm,
        center_node_id=center_node_id,
        offset_node_id=offset_node_id,
    )


def _closest_node(node_ids: list[int], coords, target: tuple[float, float, float]) -> int:
    best_index = min(
        range(len(node_ids)),
        key=lambda i: sum((coords[i][k] - target[k]) ** 2 for k in range(3)),
    )
    return node_ids[best_index]
