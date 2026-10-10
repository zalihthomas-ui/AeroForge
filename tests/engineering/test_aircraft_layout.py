"""v0.15 whole-aircraft layout: tail sizing, fuselage, mass & balance, stability, trim, CAD."""

import itertools
import math

import pytest

from agents.geometry.fuselage_tail import (
    build_fuselage,
    build_htail,
    build_vtail,
    flap_effectiveness,
    fuselage_stations,
    tail_surface,
)
from engineering.analysis.aircraft_layout import (
    V_H_DEFAULT,
    V_V_DEFAULT,
    MassItem,
    build_aircraft_assembly,
    default_components,
    design_aircraft,
    mass_balance,
    size_tail,
    wing_mac,
)
from engineering.analysis.wing_campaign import (
    CampaignRequirement,
    build_structure_cad,
    run_campaign,
)


@pytest.fixture(scope="module")
def campaign():
    return run_campaign(CampaignRequirement(), run_fe=False)


@pytest.fixture(scope="module")
def design(campaign):
    st = build_structure_cad(campaign, n_profile=21)
    return design_aircraft(campaign, st.masses_kg()), st


def test_flap_effectiveness_thin_airfoil_values():
    assert flap_effectiveness(1.0) == pytest.approx(1.0)
    assert flap_effectiveness(0.0) == pytest.approx(0.0, abs=1e-12)
    assert flap_effectiveness(0.3) == pytest.approx(0.66, abs=0.01)  # Anderson Fig. 4.x, cf/c = 0.3


def test_mac_of_rectangular_and_tapered_wings():
    assert wing_mac(300, 300, 900)[0] == pytest.approx(300)
    mac, y = wing_mac(300, 150, 900)
    assert mac == pytest.approx(2 / 3 * 300 * (1 + 0.5 + 0.25) / 1.5)
    assert y == pytest.approx(900 / 3 * 2 / 1.5)


def test_tail_volume_coefficients_are_met(campaign):
    tail = size_tail(campaign, 740.0, 300.0)
    s = campaign.aero.lifting_line.area_m2 * 1e6
    mac, _ = wing_mac(campaign.aero.root_chord_mm, campaign.aero.tip_chord_mm, 900)
    assert 2 * tail.htail.area_mm2 * 740.0 / (s * mac) == pytest.approx(V_H_DEFAULT, rel=1e-9)
    assert tail.vtail.area_mm2 * 740.0 / (s * 1800.0) == pytest.approx(V_V_DEFAULT, rel=1e-9)
    ht = tail_surface(80000.0, 4.5, 0.7, "0009", 0.7)
    assert 2 * ht.area_mm2 == pytest.approx(80000.0)
    assert (2 * ht.span_mm) ** 2 / (2 * ht.area_mm2) == pytest.approx(4.5)


def test_mass_balance_moment_identity():
    items = [MassItem("a", 2.0, 100.0, 0.0, "x"), MassItem("b", 1.0, 400.0, 30.0, "x")]
    m, x, z = mass_balance(items)
    assert (m, x, z) == pytest.approx((3.0, 200.0, 10.0))


def test_fuselage_and_tail_cad_are_valid_and_enclose_components():
    st = fuselage_stations(130, 130, 110, 600, 1200)
    fus = build_fuselage(st, former_x_mm=[110, 350, 600])
    assert next(c.label for c in fus.children) == "FuselageSkin"
    assert all(c.is_valid and c.volume > 0 for c in fus.children)
    battery = next(c for c in default_components() if c.name == "Battery")
    assert battery.box_mm[1] < st[2].width_mm and battery.box_mm[2] < st[2].height_mm
    ht = build_htail(tail_surface(80000.0, 4.5, 0.7, "0009", 0.7), 1000, 0)
    vt = build_vtail(tail_surface(35000.0, 1.6, 0.6, "0010", 0.65, sweep_le_deg=25, both_sides=False), 1000, 0)
    assert {c.label for c in ht.children} == {"Stabilizer_Stbd", "Elevator_Stbd", "Stabilizer_Port", "Elevator_Port"}
    assert {c.label for c in vt.children} == {"Fin", "Rudder"}
    assert all(c.is_valid for c in list(ht.children) + list(vt.children))


def test_design_hits_static_margin_and_trims(design):
    d, _ = design
    assert d.total_mass_kg == pytest.approx(d.mtow_kg)
    assert d.payload_kg > 0
    assert d.static_margin == pytest.approx(0.10, abs=0.005)
    assert 0.05 <= d.static_margin <= 0.15
    # fuselage is destabilising: increment moves the NP forward
    assert d.x_np_aerobuildup_mm < d.x_np_aerobuildup_nofus_mm
    # SM increases monotonically as the wing moves aft
    sms = [sm for _, sm in d.sm_vs_lh]
    assert all(b >= a - 1e-6 for a, b in itertools.pairwise(sms))
    # trimmed at cruise with small angles
    assert 0.0 < d.trim_alpha_deg < 8.0
    assert abs(d.trim_elevator_deg) < 10.0
    assert d.cl_cruise == pytest.approx(12.0 * 9.81 / (0.5 * 1.225 * 25**2 * d.campaign.aero.lifting_line.area_m2))
    assert math.isfinite(d.trim_elevator_vlm_deg)


def test_aircraft_assembly_is_labelled(design):
    d, st = design
    ac = build_aircraft_assembly(d, st)
    assert ac.label == "Aircraft"
    assert [c.label for c in ac.children] == ["Wing", "Fuselage", "HorizontalTail", "VerticalTail", "Systems"]
    bb = ac.bounding_box()
    assert bb.max.Y == pytest.approx(900.0, abs=1.0) and bb.min.Y == pytest.approx(-900.0, abs=1.0)
    assert bb.max.X > d.tail.x_htail_le_mm


def test_export_parts_step_handles_primitive_solids(tmp_path):
    from build123d import Box, Compound, Cylinder

    from cad.exporters import export_parts_step

    b, c = Box(10, 10, 10), Cylinder(5, 20)
    b.label, c.label = "Block", "Pin"
    paths = export_parts_step(Compound(children=[b, c], label="Kit"), str(tmp_path))
    assert sorted(p.split("\\")[-1].split("/")[-1] for p in paths) == ["Block.step", "Pin.step"]


def test_parts_of_moved_subassemblies_export_in_world_coordinates(tmp_path):
    from build123d import Box, Compound, Pos, import_step

    from cad.exporters import export_parts_step, world_shape

    leaf = Box(10, 10, 10)
    leaf.label = "Leaf"
    top = Compound(children=[Pos(250, 0, 0) * Compound(children=[leaf], label="Sub")], label="Top")
    inner = top.children[0].children[0]
    assert world_shape(inner).center().X == pytest.approx(250.0)
    (path,) = export_parts_step(top, str(tmp_path))
    assert import_step(path).center().X == pytest.approx(250.0)
