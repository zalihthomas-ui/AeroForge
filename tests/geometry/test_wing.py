"""Tests for the wing Geometry Agent: valid geometry generation with real NACA airfoil sections."""

from __future__ import annotations

import pytest
from build123d import Part
import aerosandbox as asb

from agents.geometry.agent import GeometryAgent
from agents.geometry.validation import GeometryValidationError
from agents.geometry.wing import build_wing, estimate_wing_shell_mass_kg
from engineering.requirements.schema import EngineeringSpec

REFERENCE_PARAMETERS = {
    "wing_span": 1800.0,
    "root_chord": 240.0,
    "tip_chord": 140.0,
    "sweep": 12.0,
    "dihedral": 4.0,
}


def _spec(**parameters: float) -> EngineeringSpec:
    return EngineeringSpec(component="wing", parameters=parameters)


def _expected_volume(
    wing_span: float,
    root_chord: float,
    tip_chord: float,
    naca_airfoil: float = 12.0,
) -> float:
    naca_digits = f"{int(naca_airfoil):04d}"
    af = asb.Airfoil(f"naca{naca_digits}").repanel(n_points_per_side=40)
    area_norm = af.area()
    return area_norm * wing_span * (root_chord**2 + root_chord * tip_chord + tip_chord**2) / 3.0


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


def test_cambered_naca2412_wing_generates_valid_solid() -> None:
    params = {**REFERENCE_PARAMETERS, "naca_airfoil": 2412.0}
    part = GeometryAgent().generate(_spec(**params))

    assert isinstance(part, Part)
    assert part.is_valid
    assert part.is_manifold
    assert part.volume > 0
    assert part.volume == pytest.approx(
        _expected_volume(
            REFERENCE_PARAMETERS["wing_span"],
            REFERENCE_PARAMETERS["root_chord"],
            REFERENCE_PARAMETERS["tip_chord"],
            naca_airfoil=2412.0,
        ),
        rel=1e-3,
    )


def test_cambered_naca4412_wing_generates_valid_solid() -> None:
    params = {**REFERENCE_PARAMETERS, "naca_airfoil": 4412.0}
    part = GeometryAgent().generate(_spec(**params))

    assert isinstance(part, Part)
    assert part.is_valid
    assert part.is_manifold
    assert part.volume == pytest.approx(
        _expected_volume(
            REFERENCE_PARAMETERS["wing_span"],
            REFERENCE_PARAMETERS["root_chord"],
            REFERENCE_PARAMETERS["tip_chord"],
            naca_airfoil=4412.0,
        ),
        rel=1e-3,
    )


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
    expected_volume = _expected_volume(REFERENCE_PARAMETERS["wing_span"], root_chord, root_chord)
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


def test_reference_wing_shell_mass_is_physically_plausible() -> None:
    """A solid-aluminum reference wing computes to ~14.7 kg -- heavier
    than the entire 12 kg aircraft the mission doc's flagship demo
    targets -- because real small UAV wings are a thin skin over a
    lightweight internal structure, not solid material. The shell-mass
    estimate should be well under the aircraft's MTOW and notably
    lighter than that solid-aluminum figure."""
    mass_kg = estimate_wing_shell_mass_kg(REFERENCE_PARAMETERS)

    assert 0.0 < mass_kg < 12.0
    solid_aluminum_mass_kg = build_wing(REFERENCE_PARAMETERS).volume * 1e-9 * 2700.0
    assert mass_kg < solid_aluminum_mass_kg


def test_shell_mass_scales_with_skin_thickness_and_density() -> None:
    baseline = estimate_wing_shell_mass_kg(REFERENCE_PARAMETERS, skin_thickness_mm=0.5, material_density_kg_m3=1600.0)
    doubled_thickness = estimate_wing_shell_mass_kg(
        REFERENCE_PARAMETERS, skin_thickness_mm=1.0, material_density_kg_m3=1600.0
    )
    doubled_density = estimate_wing_shell_mass_kg(
        REFERENCE_PARAMETERS, skin_thickness_mm=0.5, material_density_kg_m3=3200.0
    )

    assert doubled_thickness == pytest.approx(2 * baseline, rel=1e-9)
    assert doubled_density == pytest.approx(2 * baseline, rel=1e-9)


@pytest.mark.parametrize("field", ["skin_thickness_mm", "material_density_kg_m3"])
def test_non_positive_shell_mass_inputs_are_rejected(field: str) -> None:
    with pytest.raises(GeometryValidationError):
        estimate_wing_shell_mass_kg(REFERENCE_PARAMETERS, **{field: 0.0})
    with pytest.raises(GeometryValidationError):
        estimate_wing_shell_mass_kg(REFERENCE_PARAMETERS, **{field: -1.0})


def test_invalid_wing_parameters_are_rejected_via_build_wing() -> None:
    params = {**REFERENCE_PARAMETERS, "wing_span": 0.0}
    with pytest.raises(GeometryValidationError):
        estimate_wing_shell_mass_kg(params)
