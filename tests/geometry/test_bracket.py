"""Tests for the bracket Geometry Agent: valid geometry generation and
rejection of invalid parameters."""

from __future__ import annotations

import math

import pytest
from build123d import Part

from agents.geometry.agent import GeometryAgent
from agents.geometry.validation import GeometryValidationError
from engineering.requirements.schema import EngineeringSpec

REFERENCE_PARAMETERS = {
    "length": 100.0,
    "width": 80.0,
    "thickness": 5.0,
    "hole_diameter": 8.0,
    "hole_count": 4,
}


def _spec(**parameters: float) -> EngineeringSpec:
    return EngineeringSpec(component="bracket", parameters=parameters)


def test_reference_bracket_generates_a_valid_solid() -> None:
    part = GeometryAgent().generate(_spec(**REFERENCE_PARAMETERS))

    assert isinstance(part, Part)
    assert part.is_valid
    assert part.is_manifold
    assert part.volume > 0

    plate_volume = (
        REFERENCE_PARAMETERS["length"]
        * REFERENCE_PARAMETERS["width"]
        * REFERENCE_PARAMETERS["thickness"]
    )
    hole_volume = (
        math.pi
        * (REFERENCE_PARAMETERS["hole_diameter"] / 2) ** 2
        * REFERENCE_PARAMETERS["thickness"]
    )
    expected_volume = plate_volume - REFERENCE_PARAMETERS["hole_count"] * hole_volume
    assert part.volume == pytest.approx(expected_volume, rel=1e-3)


def test_default_parameters_match_reference_case() -> None:
    part = GeometryAgent().generate(_spec())

    plate_volume = 100.0 * 80.0 * 5.0
    hole_volume = math.pi * (8.0 / 2) ** 2 * 5.0
    expected_volume = plate_volume - 4 * hole_volume
    assert part.volume == pytest.approx(expected_volume, rel=1e-3)


def test_zero_holes_is_a_plain_plate() -> None:
    params = {**REFERENCE_PARAMETERS, "hole_count": 0}
    part = GeometryAgent().generate(_spec(**params))

    assert part.volume == pytest.approx(100.0 * 80.0 * 5.0, rel=1e-6)


@pytest.mark.parametrize("hole_count", [1, 2, 3, 6, 10])
def test_various_hole_counts_produce_valid_solids(hole_count: int) -> None:
    params = {**REFERENCE_PARAMETERS, "hole_count": hole_count, "hole_diameter": 4.0}
    part = GeometryAgent().generate(_spec(**params))

    assert part.is_valid
    assert part.is_manifold


def test_hole_too_large_for_width_is_rejected() -> None:
    params = {**REFERENCE_PARAMETERS, "hole_diameter": 79.0}
    with pytest.raises(GeometryValidationError):
        GeometryAgent().generate(_spec(**params))


def test_holes_that_would_overlap_are_rejected() -> None:
    params = {**REFERENCE_PARAMETERS, "hole_count": 20, "hole_diameter": 8.0}
    with pytest.raises(GeometryValidationError):
        GeometryAgent().generate(_spec(**params))


@pytest.mark.parametrize("field", ["length", "width", "thickness"])
def test_non_positive_dimensions_are_rejected(field: str) -> None:
    params = {**REFERENCE_PARAMETERS, field: 0.0}
    with pytest.raises(GeometryValidationError):
        GeometryAgent().generate(_spec(**params))


def test_negative_hole_count_is_rejected() -> None:
    params = {**REFERENCE_PARAMETERS, "hole_count": -1}
    with pytest.raises(GeometryValidationError):
        GeometryAgent().generate(_spec(**params))


def test_non_integer_hole_count_is_rejected() -> None:
    params = {**REFERENCE_PARAMETERS, "hole_count": 2.5}
    with pytest.raises(GeometryValidationError):
        GeometryAgent().generate(_spec(**params))


def test_unsupported_component_is_rejected() -> None:
    spec = EngineeringSpec(component="fuselage", parameters={})
    with pytest.raises(GeometryValidationError):
        GeometryAgent().generate(spec)
