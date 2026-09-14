"""Wing planform: a tapered, swept, dihedral-angled flat plate.

FLAT-PLATE PLANFORM APPROXIMATION ONLY — not an aerodynamically real wing.
v0.2 is still CAD-only (no Aerodynamics Agent/CFD yet), so this has no
airfoil section, camber, or twist: it's a constant-thickness slab whose
outline follows the tapered/swept/dihedral planform. Do not use this for
anything aerodynamic; real airfoil sections are future work once an
Aerodynamics Agent exists.

Coordinate convention: X = chordwise (leading edge at X=0, chord extends
in +X), Y = spanwise, Z = vertical.

Reference case (mission doc's Geometry Agent example): wing_span=1800mm,
root_chord=240mm, tip_chord=140mm, sweep=12deg, dihedral=4deg.
"""

from __future__ import annotations

import math

from build123d import Face, Part, Plane, Sketch, Wire, loft, make_face, mirror

from .validation import validate_expected_volume, validate_solid, validate_wing_parameters

DEFAULT_PARAMETERS: dict[str, float] = {
    "wing_span": 1800.0,
    "root_chord": 240.0,
    "tip_chord": 140.0,
    "sweep": 12.0,
    "dihedral": 4.0,
}

# Flat-plate thickness as a fraction of root chord. There's no real airfoil
# section at this milestone, so any constant thickness is equally
# "correct" for a planform approximation — 8% scales sensibly across the
# range of wing sizes the mission doc's examples use, rather than a fixed
# mm value that would look absurdly thick or thin outside that range.
_THICKNESS_RATIO = 0.08


def _cross_section(
    x_leading_edge: float, y_station: float, z_leading_edge: float, chord: float, thickness: float
) -> Face | Sketch:
    """A thin rectangular cross-section (chord x thickness) at spanwise
    station `y_station`, leading edge at (x_leading_edge, y_station, z_leading_edge)."""
    half_thickness = thickness / 2
    corners = [
        (x_leading_edge, y_station, z_leading_edge - half_thickness),
        (x_leading_edge + chord, y_station, z_leading_edge - half_thickness),
        (x_leading_edge + chord, y_station, z_leading_edge + half_thickness),
        (x_leading_edge, y_station, z_leading_edge + half_thickness),
    ]
    return make_face(Wire.make_polygon(corners, close=True))


def build_wing(parameters: dict[str, float]) -> Part:
    """Build a symmetric tapered/swept/dihedral wing planform Part from
    `parameters`.

    Missing parameters fall back to the reference-case defaults. Raises
    GeometryValidationError if the parameters or the resulting solid are
    invalid.
    """
    params = {**DEFAULT_PARAMETERS, **parameters}
    wing_span = params["wing_span"]
    root_chord = params["root_chord"]
    tip_chord = params["tip_chord"]
    sweep = params["sweep"]
    dihedral = params["dihedral"]

    validate_wing_parameters(wing_span, root_chord, tip_chord, sweep, dihedral)

    half_span = wing_span / 2
    thickness = root_chord * _THICKNESS_RATIO

    root_face = _cross_section(0.0, 0.0, 0.0, root_chord, thickness)
    tip_x = half_span * math.tan(math.radians(sweep))
    tip_z = half_span * math.tan(math.radians(dihedral))
    tip_face = _cross_section(tip_x, half_span, tip_z, tip_chord, thickness)

    half_wing = loft([root_face, tip_face])

    context = "wing"
    validate_solid(half_wing, context=context)

    full_wing = half_wing + mirror(half_wing, about=Plane.XZ)

    validate_solid(full_wing, context=context)
    # The loft is a ruled surface between two parallel-thickness rectangular
    # cross-sections, so each half's cross-sectional area varies linearly
    # from root_chord*thickness to tip_chord*thickness along the span —
    # giving an exact (not approximate) expected volume, independent of
    # sweep/dihedral since those only translate each cross-section, not
    # its area.
    expected_volume = 2 * thickness * half_span * (root_chord + tip_chord) / 2
    validate_expected_volume(full_wing, expected_volume, context=context)

    return full_wing
