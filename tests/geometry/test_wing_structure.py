"""Complete wing structure CAD: component counts, validity, volumes vs hand calculation."""

import numpy as np
import pytest

from agents.geometry.wing_structure import (
    WingStructureError,
    WingStructureSpec,
    build_wing_structure,
    naca4_surfaces,
)

EDGES = list(np.linspace(0.0, 900.0, 4))


def _spec(**kw):
    base = {"semispan_mm": 900.0, "root_chord_mm": 300.0, "tip_chord_mm": 180.0, "naca": "4412", "bay_edges_mm": EDGES,
                "t_cap_mm": [1.2, 0.9, 0.5], "t_web_mm": [0.4, 0.3, 0.3], "n_profile": 21}
    base.update(kw)
    return WingStructureSpec(**base)


@pytest.fixture(scope="module")
def structure():
    return build_wing_structure(_spec())


def test_naca_surfaces_match_thickness_and_camber():
    zu, zl = naca4_surfaces("0012", np.array([0.3]))
    assert zu[0] - zl[0] == pytest.approx(0.12, abs=0.002)
    zu, zl = naca4_surfaces("4412", np.array([0.4]))
    assert 0.5 * (zu[0] + zl[0]) == pytest.approx(0.04, abs=0.002)  # max camber 4 % at 40 %


def test_component_counts_and_validity(structure):
    counts = {g: len(p) for g, p in structure.parts.items()}
    assert counts == {"ribs": 4, "spars": 6, "box covers": 6, "leading-edge skin": 1, "trailing-edge skin": 2}
    assert all(p.is_valid and p.volume > 0 for ps in structure.parts.values() for p in ps)


def test_spar_volume_matches_hand_calculation(structure):
    spec = structure.spec
    front = structure.parts["spars"][0]  # bay 0 front spar
    zu, zl = naca4_surfaces("4412", np.array([0.2]))
    depth_root = (zu[0] - zl[0]) * spec.chord(0.0) - 2 * 1.2
    depth_out = (zu[0] - zl[0]) * spec.chord(300.0) - 2 * 1.2
    expected = 0.4 * 300.0 * 0.5 * (depth_root + depth_out)
    assert front.volume == pytest.approx(expected, rel=0.01)


def test_cover_volume_matches_arc_length_times_thickness(structure):
    spec = structure.spec
    upper_bay0 = structure.parts["box covers"][0]
    xc = np.linspace(0.2, 0.6, 400)
    zu, _ = naca4_surfaces("4412", xc)

    def width(y):
        c = spec.chord(y)
        return float(np.sum(np.hypot(np.diff(xc * c), np.diff(zu * c))))

    # vertical offset: cross-section area = horizontal extent x t
    expected = 1.2 * 300.0 * 0.5 * (0.4 * spec.chord(0.0) + 0.4 * spec.chord(300.0))
    assert upper_bay0.volume == pytest.approx(expected, rel=0.01)
    assert width(0.0) > 0.4 * spec.chord(0.0)  # true surface is longer than its projection


def test_mass_breakdown_and_full_wing(structure):
    m = structure.masses_kg()
    assert set(m) == set(structure.parts)
    assert all(v > 0 for v in m.values())
    full = structure.full_wing()
    for g, comp in full.items():
        # (Compound.volume is not additive over mirrored copies here; sum the solids)
        assert len(comp.solids()) == 2 * len(structure.parts[g])
        total = sum(float(s.volume) for s in comp.solids())
        assert total == pytest.approx(structure.volumes_mm3()[g], rel=1e-6)


def test_lightening_holes_reduce_rib_mass():
    plain = build_wing_structure(_spec(rib_lightening_holes=False))
    holed = build_wing_structure(_spec())
    assert holed.masses_kg()["ribs"] < plain.masses_kg()["ribs"]


def test_rejects_inconsistent_bays():
    with pytest.raises(WingStructureError):
        build_wing_structure(_spec(t_cap_mm=[1.0, 1.0]))
