"""Rectangular mounting bracket: a plate with N holes evenly spaced and
centered along the long axis.

Reference case (mission doc Phase 1 example): a 100 x 80 x 5 mm plate with
four 8 mm holes.
"""

from __future__ import annotations

import math

from build123d import Box, Cylinder, Part, Pos

from .validation import validate_bracket_parameters, validate_expected_volume, validate_solid

DEFAULT_PARAMETERS: dict[str, float] = {
    "length": 100.0,
    "width": 80.0,
    "thickness": 5.0,
    "hole_diameter": 8.0,
    "hole_count": 4,
}

# Cylinders are made taller than the plate so both cut faces clear the
# plate's top/bottom faces cleanly, avoiding coincident-face degeneracies.
_HOLE_HEIGHT_MARGIN_RATIO = 0.2


def hole_center_x_positions(length_mm: float, hole_count: int) -> list[float]:
    """X-position of each hole's center, evenly spaced and centered along
    the bracket's length. The single source of truth for this spacing —
    reused by agents/structures/bracket_mesh.py (to locate the holes in
    the meshed geometry) and agents/manufacturing/agent.py (to compute
    real edge-clearance distances), so it only needs to change in one
    place if the spacing scheme ever does.
    """
    segment = length_mm / hole_count
    return [-length_mm / 2 + (i + 0.5) * segment for i in range(hole_count)]


def build_bracket(parameters: dict[str, float]) -> Part:
    """Build a rectangular mounting bracket Part from `parameters`.

    Missing parameters fall back to the reference-case defaults. Raises
    GeometryValidationError if the parameters or the resulting solid are
    invalid.
    """
    params = {**DEFAULT_PARAMETERS, **parameters}
    length = params["length"]
    width = params["width"]
    thickness = params["thickness"]
    hole_diameter = params["hole_diameter"]
    raw_hole_count = params["hole_count"]

    validate_bracket_parameters(length, width, thickness, hole_diameter, raw_hole_count)
    hole_count = int(raw_hole_count)

    plate = Box(length, width, thickness)
    hole_volume = 0.0

    if hole_count > 0:
        hole_radius = hole_diameter / 2
        hole_height = thickness * (1 + _HOLE_HEIGHT_MARGIN_RATIO)
        for x in hole_center_x_positions(length, hole_count):
            plate -= Pos(x, 0, 0) * Cylinder(hole_radius, hole_height)
        hole_volume = math.pi * hole_radius**2 * thickness

    context = "bracket"
    validate_solid(plate, context=context)
    expected_volume = length * width * thickness - hole_count * hole_volume
    validate_expected_volume(plate, expected_volume, context=context)

    return plate
