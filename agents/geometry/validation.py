"""Validation for the Geometry Agent.

Two layers of checks:

- parameter validation, run *before* build123d touches OCCT, catching
  obviously bad input cheaply (e.g. a hole wider than the plate).
- solid validation, run *after* a Part is built, catching geometry that
  OCCT itself considers broken (invalid/non-manifold shapes) or that
  silently lost volume to overlapping features.

Both raise GeometryValidationError with a human-readable reason instead of
letting bad geometry reach the exporters.
"""

from __future__ import annotations

from build123d import Part

# Minimum clearance (mm) required between a hole's edge and the plate's long
# edge, so a hole can never breach the side of the bracket.
MIN_EDGE_MARGIN_MM = 2.0

# Minimum clearance (mm) required between the edges of two adjacent holes,
# so holes can never overlap or touch.
MIN_HOLE_SPACING_MM = 2.0

# How much a solid's actual volume may deviate from the analytically
# expected volume before it's treated as a self-intersection.
VOLUME_TOLERANCE_RATIO = 1e-3


class GeometryValidationError(Exception):
    """Raised when a spec's parameters or the geometry built from them are invalid."""


def _require_positive(name: str, value: float) -> None:
    if value <= 0:
        raise GeometryValidationError(f"'{name}' must be positive, got {value}.")


def validate_bracket_parameters(
    length: float,
    width: float,
    thickness: float,
    hole_diameter: float,
    hole_count: float,
) -> None:
    """Reject bracket parameters that can't produce valid geometry.

    `hole_count` is accepted as a float (its un-truncated raw form) so a
    non-integer value can be caught here rather than silently truncated by
    the caller before validation runs.

    Runs before any OCCT calls so bad input fails fast with a clear reason.
    """
    _require_positive("length", length)
    _require_positive("width", width)
    _require_positive("thickness", thickness)

    if hole_count < 0 or hole_count != int(hole_count):
        raise GeometryValidationError(
            f"'hole_count' must be a non-negative integer, got {hole_count!r}."
        )
    hole_count = int(hole_count)

    if hole_count == 0:
        return

    _require_positive("hole_diameter", hole_diameter)

    max_hole_diameter = width - 2 * MIN_EDGE_MARGIN_MM
    if hole_diameter >= max_hole_diameter:
        raise GeometryValidationError(
            f"hole_diameter ({hole_diameter} mm) is too large for width ({width} mm): "
            f"it must be less than {max_hole_diameter} mm to leave at least "
            f"{MIN_EDGE_MARGIN_MM} mm of material on each long edge."
        )

    segment = length / hole_count
    min_segment = hole_diameter + MIN_HOLE_SPACING_MM
    if segment < min_segment:
        raise GeometryValidationError(
            f"{hole_count} holes of diameter {hole_diameter} mm do not fit evenly "
            f"along a length of {length} mm without overlapping: each hole needs "
            f"at least {min_segment} mm of the {segment:.3f} mm available per hole."
        )


def validate_solid(part: Part, *, context: str) -> None:
    """Reject a build123d Part that OCCT itself considers defective."""
    if part.volume <= 0:
        raise GeometryValidationError(
            f"{context}: generated geometry has non-positive volume ({part.volume})."
        )
    if not part.is_valid:
        raise GeometryValidationError(
            f"{context}: generated geometry failed the OCCT solid validity check "
            "(BRepCheck_Analyzer) — the shape has topological defects."
        )
    if not part.is_manifold:
        raise GeometryValidationError(
            f"{context}: generated geometry is not manifold (not watertight) — "
            "it likely has self-intersecting or overlapping features."
        )


def validate_expected_volume(
    part: Part,
    expected_volume: float,
    *,
    context: str,
    tolerance_ratio: float = VOLUME_TOLERANCE_RATIO,
) -> None:
    """Reject a Part whose volume doesn't match the analytically expected
    volume for its parameters.

    Overlapping cut features (e.g. two holes that intersect) remove less
    total material than the sum of their individual volumes, so a mismatch
    here is a reliable, cheap self-intersection signal that complements
    `validate_solid`'s topological check.
    """
    tolerance = max(abs(expected_volume) * tolerance_ratio, 1e-6)
    deviation = abs(part.volume - expected_volume)
    if deviation > tolerance:
        raise GeometryValidationError(
            f"{context}: resulting volume ({part.volume:.3f} mm^3) does not match "
            f"the expected volume ({expected_volume:.3f} mm^3, tolerance "
            f"{tolerance:.3f}) — likely self-intersecting or overlapping features."
        )
