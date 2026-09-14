"""Tests for the wing Geometry Agent: valid geometry generation and
rejection of invalid parameters.

Reminder: this is a flat-plate planform approximation (see wing.py's
module docstring) — these tests check it's a valid, correctly-sized
solid, not that it's aerodynamically meaningful.
"""

from __future__ import annotations

import math

import pytest
from build123d import Part

from agents.geometry.agent import GeometryAgent
from agents.geometry.validation import GeometryValidationError
from engineering.requirements.schema import EngineeringSpec

REFERENCE_PARAMETERS = {
    "wing_span": 1800.0,
    "root_chord": 240.0,
    "tip_chord": 140.0,
    "sweep": 12.0,
    "dihedral": 4.0,
}

_THICKNESS_RATIO = 0.08


def _spec(**parameters: float) -> EngineeringSpec:
    return EngineeringSpec(component="wing", parameters=parameters)


def _expected_volume(wing_span: float, root_chord: float, tip_chord: float) -> float:
    half_span = wing_span / 2
    thickness = root_chord * _THICKNESS_RATIO
    return 2 * thickness * half_span * (root_chord + tip_chord) / 2


def test_reference_wing_generates_a_valid_solid() -> None:
    part = GeometryAgent().generate(_spec(**REFERENCE_PARAMETERS))

    assert isinstance(part, Part)
    assert part.is_valid
    assert part.is_manifold
    assert part.volume > 0
    assert part.volume == pytest.approx(
        _expected_volume(
            REFERENCE_PARAMETERS["wing_span"],
            REFERENCE_PARAMETERS["root_chord"],
            REFERENCE_PARAMETERS["tip_chord"],
        ),
        rel=1e-3,
    )


def test_default_parameters_match_reference_case() -> None:
    part = GeometryAgent().generate(_spec())

    assert part.volume == pytest.approx(_expected_volume(1800.0, 240.0, 140.0), rel=1e-3)


def test_wing_is_symmetric_about_the_root() -> None:
    part = GeometryAgent().generate(_spec(**REFERENCE_PARAMETERS))
    bbox = part.bounding_box()

    half_span = REFERENCE_PARAMETERS["wing_span"] / 2
    assert bbox.min.Y == pytest.approx(-half_span, rel=1e-3)
    assert bbox.max.Y == pytest.approx(half_span, rel=1e-3)


@pytest.mark.parametrize(
    ("sweep", "dihedral"),
    [(0.0, 0.0), (30.0, 0.0), (0.0, 15.0), (-20.0, -10.0), (45.0, 20.0)],
)
def test_various_sweep_and_dihedral_produce_valid_solids(sweep: float, dihedral: float) -> None:
    params = {**REFERENCE_PARAMETERS, "sweep": sweep, "dihedral": dihedral}
    part = GeometryAgent().generate(_spec(**params))

    assert part.is_valid
    assert part.is_manifold


def test_untapered_wing_is_a_rectangular_planform() -> None:
    params = {**REFERENCE_PARAMETERS, "tip_chord": REFERENCE_PARAMETERS["root_chord"], "sweep": 0.0}
    part = GeometryAgent().generate(_spec(**params))

    root_chord = REFERENCE_PARAMETERS["root_chord"]
    thickness = root_chord * _THICKNESS_RATIO
    expected_volume = root_chord * REFERENCE_PARAMETERS["wing_span"] * thickness
    assert part.volume == pytest.approx(expected_volume, rel=1e-3)


@pytest.mark.parametrize("field", ["wing_span", "root_chord", "tip_chord"])
def test_non_positive_dimensions_are_rejected(field: str) -> None:
    params = {**REFERENCE_PARAMETERS, field: 0.0}
    with pytest.raises(GeometryValidationError):
        GeometryAgent().generate(_spec(**params))


@pytest.mark.parametrize("field", ["sweep", "dihedral"])
def test_extreme_angles_are_rejected(field: str) -> None:
    params = {**REFERENCE_PARAMETERS, field: 89.9}
    with pytest.raises(GeometryValidationError):
        GeometryAgent().generate(_spec(**params))
