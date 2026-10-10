"""V6 parametric CAD: geometry derived from EngineSpec, exact kinematics, assembly, clash checks."""


import numpy as np
import pytest

from agents.powertrain.spec import EngineSpec
from agents.powertrain.v6_cad import (
    V6CadError,
    V6CadProportions,
    assembly,
    bdc_angle,
    build_v6,
    direction,
    geometric_compression_ratio,
    part_masses_kg,
    piston_counterweight_clearance,
    piston_travel,
    pose,
    reciprocating_mass_kg,
    rod_block_clearance,
    rod_small_end_fraction,
)
from cad.exporters import export_parts_step, export_step_assembly

SPEC = EngineSpec()
THETAS = np.arange(0.0, 720.0, 5.0)


@pytest.fixture(scope="module")
def model():
    return build_v6(SPEC)


def _apply(m, p):
    return (m @ np.append(p, 1.0))[:3]


# ---- kinematics (no CAD needed) -------------------------------------------------
@pytest.mark.parametrize("cyl", SPEC.cylinders, ids=lambda c: f"cyl{c.number}")
def test_piston_at_tdc_at_its_firing_angle(cyl):
    s_fire = piston_travel(SPEC, cyl.number, cyl.firing_angle_deg)
    assert s_fire == pytest.approx(SPEC.crank_radius_mm + SPEC.rod_length_mm, abs=1e-9)
    s_all = [piston_travel(SPEC, cyl.number, th) for th in THETAS]
    assert max(s_all) == pytest.approx(s_fire, abs=1e-9)
    s_bdc = piston_travel(SPEC, cyl.number, bdc_angle(SPEC, cyl.number))
    assert s_bdc == pytest.approx(SPEC.rod_length_mm - SPEC.crank_radius_mm, abs=1e-9)
    assert s_fire - s_bdc == pytest.approx(SPEC.stroke_mm, abs=1e-9)


@pytest.mark.parametrize("theta", THETAS)
def test_rods_keep_length_and_pistons_stay_on_their_bore_axis(theta):
    t = pose(SPEC, theta)
    for c in SPEC.cylinders:
        k = c.number
        big = _apply(t[f"Rod_{k}"], [0, 0, 0])
        small = _apply(t[f"Rod_{k}"], [0, SPEC.rod_length_mm, 0])
        pin = _apply(t[f"Piston_{k}"], [0, 0, 0])
        assert np.linalg.norm(small - big) == pytest.approx(SPEC.rod_length_mm, abs=1e-9)
        assert small == pytest.approx(pin, abs=1e-9)  # small end on the gudgeon pin
        # big end on the crank pin carried by the crankshaft transform
        pin_on_crank = SPEC.crank_radius_mm * direction(c.pin_angle_deg) + np.array([0, 0, c.z_mm])
        assert big == pytest.approx(_apply(t["Crankshaft"], pin_on_crank), abs=1e-9)
        # piston: no lateral offset from the cylinder axis, axis direction preserved
        u = direction(c.axis_angle_deg)
        lateral = pin - np.dot(pin, u) * u - np.array([0, 0, c.z_mm])
        assert np.linalg.norm(lateral) == pytest.approx(0.0, abs=1e-9)
        up = _apply(t[f"Piston_{k}"], [0, 1, 0]) - pin
        assert up == pytest.approx(u, abs=1e-12)


def test_crank_rotates_pins_to_theta_plus_pin_angle():
    for th in (0.0, 37.0, 250.0):
        t = pose(SPEC, th)
        for c in SPEC.cylinders:
            p0 = SPEC.crank_radius_mm * direction(c.pin_angle_deg)
            assert _apply(t["Crankshaft"], p0)[:2] == pytest.approx(
                (SPEC.crank_radius_mm * direction(th + c.pin_angle_deg))[:2], abs=1e-9)


# ---- CAD geometry ----------------------------------------------------------------
def test_parts_are_valid_single_solids(model):
    parts = [model.block, model.crankshaft, model.flywheel, model.piston, model.gudgeon_pin, model.rod,
             model.oil_pan, *model.heads.values(), *model.cam_covers.values()]
    for p in parts:
        assert p.is_valid
        assert len(p.solids()) == 1
        assert p.volume > 0


def test_crown_flush_with_deck_at_tdc_and_cr_matches_spec(model):
    for c in SPEC.cylinders:
        t = pose(SPEC, c.firing_angle_deg)
        crown = _apply(t[f"Piston_{c.number}"], [0, model.compression_height, 0])
        along = np.dot(crown, direction(c.axis_angle_deg))
        assert along == pytest.approx(model.prop.deck_height, abs=1e-9)  # zero-deck block
    assert model.prop.head_gasket > 0  # piston-to-head clearance at TDC
    assert geometric_compression_ratio(model) == pytest.approx(SPEC.compression_ratio, rel=1e-9)
    assert model.chamber_depth > 0


def test_piston_and_rod_bores_match_their_pins(model):
    bb = model.rod.bounding_box()
    big_r = model.prop.crank_pin_dia / 2 + model.prop.big_end_wall
    assert bb.max.Y - bb.min.Y == pytest.approx(SPEC.rod_length_mm + big_r + model.prop.gudgeon_pin_dia / 2
                                                + model.prop.small_end_wall, abs=1e-6)
    # a pin-sized cylinder fits the big end exactly: rod volume is unchanged by subtracting it
    from agents.powertrain.v6_cad import _along_z
    assert (model.rod - _along_z(model.prop.crank_pin_dia / 2 - 1e-3, -10, 10)).volume == pytest.approx(
        model.rod.volume, rel=1e-6)
    assert model.rod.bounding_box().max.Z - model.rod.bounding_box().min.Z <= SPEC.bank_offset_mm


def test_masses_are_physically_plausible(model):
    m = part_masses_kg(model)
    assert 0.25 < m["piston"] < 0.7
    assert 0.3 < m["rod"] < 0.8
    assert 8 < m["crankshaft"] < 30
    assert 0.2 < rod_small_end_fraction(model) < 0.5
    assert 0.4 < reciprocating_mass_kg(model) < 1.2


def test_rod_wider_than_split_pin_offset_is_rejected():
    with pytest.raises(V6CadError):
        build_v6(SPEC, V6CadProportions(rod_width=SPEC.bank_offset_mm + 1))


# ---- clash checks ------------------------------------------------------------------
def test_pistons_clear_counterweights_at_bdc(model):
    clr = piston_counterweight_clearance(model)
    assert set(clr) == {1, 2, 3, 4, 5, 6}
    assert min(clr.values()) > 3.0, clr


def test_rods_clear_the_block_over_a_full_cycle(model):
    r = rod_block_clearance(model, step_deg=5.0)
    assert r["n_samples"] == 144 * 6
    assert r["min_clearance_mm"] > 5.0, r
    # the sampled sweep never under-estimates the exact distance by more than the point spacing
    assert r["sampled_min_mm"] >= r["min_clearance_mm"] - 0.5


# ---- assembly + export -------------------------------------------------------------
def test_assembly_labels_and_step_export(model, tmp_path):
    asm = assembly(model, theta_deg=90.0)
    groups = {g.label: g for g in asm.children}
    assert {"Block", "Heads", "Crankshaft", "Pistons", "Rods", "GudgeonPins", "OilPan", "Flywheel"} <= set(groups)
    assert sorted(p.label for p in groups["Pistons"].children) == [f"Piston_{k}" for k in range(1, 7)]
    path = tmp_path / "v6.step"
    export_step_assembly(asm, str(path))
    assert path.stat().st_size > 10_000
    files = export_parts_step(asm, str(tmp_path / "parts"))
    assert len(files) == 1 + 2 + 2 + 1 + 1 + 1 + 6 * 3


def test_spec_dynamics_masses_match_the_cad():
    """The dynamics run on the masses of the parts that are drawn (spec updated from the CAD)."""
    from agents.powertrain.spec import EngineSpec
    from agents.powertrain.v6_cad import (
        build_v6,
        part_masses_kg,
        rod_small_end_fraction,
    )
    from engineering.analysis.engine_dynamics import (
        reciprocating_mass_kg as analysis_recip,
    )

    spec = EngineSpec()
    model = build_v6(spec)
    m = part_masses_kg(model)
    assert spec.reciprocating_mass_kg == pytest.approx(m["piston"] + m["gudgeon_pin"], rel=1e-3)
    assert spec.rod_mass_kg == pytest.approx(m["rod"], rel=1e-3)
    assert 1.0 - spec.rod_big_end_fraction == pytest.approx(rod_small_end_fraction(model), rel=1e-3)
    assert analysis_recip(spec) == pytest.approx(m["piston"] + m["gudgeon_pin"] + m["rod"] * rod_small_end_fraction(model), rel=1e-3)
