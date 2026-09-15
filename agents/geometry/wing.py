"""Wing geometry: a tapered, swept, dihedral-angled 3D wing with NACA airfoil sections.

Generates a symmetric 3D wing solid by lofting between NACA 4-digit airfoil cross-sections
at the root and tip, scaled by root_chord and tip_chord, swept and dihedral-angled,
and mirrored about the root plane (Plane.XZ).

Coordinate convention: X = chordwise (leading edge at X=0, chord extends
in +X), Y = spanwise (root at Y=0, tip at Y=wing_span/2), Z = vertical.

Reference case (mission doc's Geometry Agent example): wing_span=1800mm,
root_chord=240mm, tip_chord=140mm, sweep=12deg, dihedral=4deg, naca_airfoil=0012 (12.0).

Known crash: hollowing this solid with a constant-wall-thickness offset
(build123d's `offset(wing, amount=-t, kind=Kind.INTERSECTION)`) hangs and
can crash the OCC kernel outright (not a clean Python exception) on this
geometry — reproduced independently. Root cause is presumed to be the
offset surface self-intersecting right at the already-razor-thin
trailing edge (see build_wing's ~0.25%-of-chord TE, the same feature that
caused v0.10's meshing sliver-element problem). Don't hollow this solid
directly; `estimate_wing_shell_mass_kg` below uses a surface-area-based
shell mass approximation instead, which needs no boolean operation.
"""

from __future__ import annotations

import math

import aerosandbox as asb
from build123d import Face, Part, Plane, Wire, loft, make_face, mirror

from .validation import (
    GeometryValidationError,
    validate_expected_volume,
    validate_solid,
    validate_wing_parameters,
)

# Sources (same "document the number, don't just assert it" discipline as
# the Manufacturing Agent's drill-ratio/edge-margin thresholds):
# - DEFAULT_SKIN_THICKNESS_MM: a typical thin fiberglass/composite skin
#   laminate for small UAV wings (roughly two light plies of E-glass
#   cloth), a common small-UAV/RC construction practice.
# - DEFAULT_SKIN_DENSITY_KG_M3: a typical E-glass/epoxy composite
#   laminate density (commonly cited in the 1600-1800 kg/m^3 range
#   depending on fiber volume fraction; 1600 is the lighter, more
#   optimistic end of that range).
# Neither is the wing's real committed material -- both are overridable.
DEFAULT_SKIN_THICKNESS_MM = 0.5
DEFAULT_SKIN_DENSITY_KG_M3 = 1600.0

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


def estimate_wing_shell_mass_kg(
    parameters: dict[str, float],
    skin_thickness_mm: float = DEFAULT_SKIN_THICKNESS_MM,
    material_density_kg_m3: float = DEFAULT_SKIN_DENSITY_KG_M3,
) -> float:
    """Estimate the wing's mass as a thin skin shell, not a solid.

    build_wing's actual CAD solid, filled with a structural material like
    aluminum, computes to ~14.7 kg for the reference case — heavier than
    the entire 12 kg aircraft the mission doc's flagship demo targets.
    Real small UAV wings are built as a thin skin over a lightweight
    internal structure (spars, ribs, foam core), not solid material, so
    that number was never a meaningful mass estimate.

    Hollowing the actual 3D solid to model this properly (a constant-
    wall-thickness offset) was tried and hangs/crashes on this geometry
    (the offset surface self-intersecting right at the already-razor-thin
    trailing edge — the same root cause class as the v0.10 meshing
    sliver-element problem). This instead uses the standard first-order
    aircraft-conceptual-design approximation for a thin shell:

        mass ≈ surface_area * skin_thickness * material_density

    valid whenever skin thickness is small relative to the structure's
    overall size (true here: ~0.5mm skin vs. a ~240mm root chord), using
    only `Part.area` — a safe, fast geometric query, not a boolean
    operation. This is skin mass only, not total wing structural mass
    (it doesn't include spars, ribs, or any internal structure).

    Args:
        parameters: Same parameters build_wing takes (used only to
            compute the wing's actual surface area via the real CAD
            geometry).
        skin_thickness_mm: Shell wall thickness (mm). Defaults to a
            typical thin composite skin — see this module's
            DEFAULT_SKIN_THICKNESS_MM for the source. Must be positive.
        material_density_kg_m3: Material density (kg/m^3). Defaults to a
            typical fiberglass-composite laminate density — see this
            module's DEFAULT_SKIN_DENSITY_KG_M3 for the source. Must be
            positive.

    Returns:
        Estimated skin mass in kg.

    Raises:
        GeometryValidationError: If skin_thickness_mm or
            material_density_kg_m3 is not strictly positive, or the wing
            parameters themselves are invalid (via build_wing).
    """
    if skin_thickness_mm <= 0:
        raise GeometryValidationError(
            f"'skin_thickness_mm' must be strictly positive, got {skin_thickness_mm}."
        )
    if material_density_kg_m3 <= 0:
        raise GeometryValidationError(
            f"'material_density_kg_m3' must be strictly positive, got {material_density_kg_m3}."
        )

    wing = build_wing(parameters)
    surface_area_m2 = wing.area / 1e6  # mm^2 -> m^2
    skin_thickness_m = skin_thickness_mm / 1000.0

    return surface_area_m2 * skin_thickness_m * material_density_kg_m3
