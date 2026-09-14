"""Direct tests for validation.py's building blocks, including the
volume-based self-intersection check that the bracket builder's parameter
pre-checks make otherwise unreachable through the public API."""

from __future__ import annotations

import pytest
from build123d import Box, Cylinder, Pos

from agents.geometry.validation import (
    GeometryValidationError,
    validate_bracket_parameters,
    validate_expected_volume,
    validate_solid,
)


def test_validate_bracket_parameters_accepts_reference_case() -> None:
    validate_bracket_parameters(100.0, 80.0, 5.0, 8.0, 4)


def test_validate_bracket_parameters_rejects_hole_too_wide_for_plate() -> None:
    with pytest.raises(GeometryValidationError, match="hole_diameter"):
        validate_bracket_parameters(100.0, 80.0, 5.0, 79.0, 1)


def test_validate_bracket_parameters_rejects_holes_that_would_overlap() -> None:
    with pytest.raises(GeometryValidationError, match="overlap"):
        validate_bracket_parameters(100.0, 80.0, 5.0, 8.0, 20)


def test_validate_solid_accepts_a_valid_box() -> None:
    validate_solid(Box(10, 10, 10), context="test")


def test_validate_solid_rejects_zero_volume() -> None:
    empty = Box(10, 10, 10) - Box(20, 20, 20)
    with pytest.raises(GeometryValidationError, match="volume"):
        validate_solid(empty, context="test")


def test_validate_expected_volume_accepts_matching_volume() -> None:
    box = Box(10, 10, 10)
    validate_expected_volume(box, 1000.0, context="test")


def test_validate_expected_volume_rejects_overlapping_holes() -> None:
    # Two overlapping cylindrical cuts remove less material than the sum of
    # their individual volumes would suggest — the classic self-intersection
    # signature this check is meant to catch.
    plate = Box(100, 80, 5)
    plate -= Pos(0, 0, 0) * Cylinder(6, 6)
    plate -= Pos(5, 0, 0) * Cylinder(6, 6)  # overlaps the first hole

    non_overlapping_expected = 100 * 80 * 5 - 2 * (3.14159265 * 6**2 * 5)
    with pytest.raises(GeometryValidationError, match="self-intersecting|overlapping"):
        validate_expected_volume(plate, non_overlapping_expected, context="test")
