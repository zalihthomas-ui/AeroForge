"""Wing geometry: a tapered, swept, dihedral-angled 3D wing with NACA airfoil sections.

Generates a symmetric 3D wing solid by lofting between NACA 4-digit airfoil cross-sections
at the root and tip, scaled by root_chord and tip_chord, swept and dihedral-angled,
and mirrored about the root plane (Plane.XZ).

Coordinate convention: X = chordwise (leading edge at X=0, chord extends
in +X), Y = spanwise (root at Y=0, tip at Y=wing_span/2), Z = vertical.

Reference case (mission doc's Geometry Agent example): wing_span=1800mm,
root_chord=240mm, tip_chord=140mm, sweep=12deg, dihedral=4deg, naca_airfoil=0012 (12.0).
"""

from __future__ import annotations

import math

import aerosandbox as asb
from build123d import Face, Part, Plane, Wire, loft, make_face, mirror

from .validation import validate_expected_volume, validate_solid, validate_wing_parameters

DEFAULT_PARAMETERS: dict[str, float] = {
    "wing_span": 1800.0,
    "root_chord": 240.0,
    "tip_chord": 140.0,
    "sweep": 12.0,
    "dihedral": 4.0,
    "naca_airfoil": 12.0,
}


def _airfoil_cross_section(
    af: asb.Airfoil,
    x_leading_edge: float,
    y_station: float,
    z_leading_edge: float,
    chord: float,
) -> Face:
    """Construct an airfoil cross-section Face at spanwise station `y_station`."""
    pts = [
        (
            x_leading_edge + float(x * chord),
            y_station,
            z_leading_edge + float(z * chord),
        )
        for x, z in af.coordinates
    ]
    return make_face(Wire.make_polygon(pts, close=True))


def build_wing(parameters: dict[str, float]) -> Part:
    """Build a symmetric tapered/swept/dihedral wing Part with real NACA airfoil sections.

    Missing parameters fall back to reference-case defaults. Raises
    GeometryValidationError if parameters or resulting solid are invalid.
    """
    params = {**DEFAULT_PARAMETERS, **parameters}
    wing_span = params["wing_span"]
    root_chord = params["root_chord"]
    tip_chord = params["tip_chord"]
    sweep = params["sweep"]
    dihedral = params["dihedral"]
    naca_airfoil_val = params.get("naca_airfoil", 12.0)

    validate_wing_parameters(wing_span, root_chord, tip_chord, sweep, dihedral)

    naca_digits = f"{int(naca_airfoil_val):04d}"
    af = asb.Airfoil(f"naca{naca_digits}").repanel(n_points_per_side=40)
    area_norm = af.area()

    half_span = wing_span / 2.0

    root_face = _airfoil_cross_section(af, 0.0, 0.0, 0.0, root_chord)
    tip_x = half_span * math.tan(math.radians(sweep))
    tip_z = half_span * math.tan(math.radians(dihedral))
    tip_face = _airfoil_cross_section(af, tip_x, half_span, tip_z, tip_chord)

    half_wing = loft([root_face, tip_face])

    context = "wing"
    validate_solid(half_wing, context=context)

    full_wing = half_wing + mirror(half_wing, about=Plane.XZ)
    validate_solid(full_wing, context=context)

    # Exact expected volume: cross-sectional area varies quadratically with chord
    # along the linear loft: V = area_norm * b * (c_root^2 + c_root*c_tip + c_tip^2) / 3
    expected_volume = (
        area_norm * wing_span * (root_chord**2 + root_chord * tip_chord + tip_chord**2) / 3.0
    )
    validate_expected_volume(full_wing, expected_volume, context=context)

    return full_wing
