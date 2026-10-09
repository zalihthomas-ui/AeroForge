"""CalculiX shell model of the wing box, validated against closed-form beam/plate theory."""

import numpy as np
import pytest

from agents.structures.agent import CALCULIX_AVAILABLE, StructuresAgent
from agents.structures.wing_box import (
    MATERIALS,
    BoxThickness,
    WingBoxGeometry,
    analyze_box,
    beam_natural_frequencies,
)
from agents.structures.wing_box_fe import (
    build_mesh,
    nodal_lift_forces,
    parse_buckling_factors,
    parse_frequencies_hz,
    write_deck,
)

AL = MATERIALS["al6061-t6"]
SEMISPAN = 900.0


@pytest.fixture(scope="module")
def case():
    geo = WingBoxGeometry.from_planform(SEMISPAN, 305.0, 178.0, "4412", n_stations=181)
    th = BoxThickness(np.linspace(0, SEMISPAN, 7), np.array([1.4, 1.2, 1.0, 0.8, 0.6, 0.35]), np.full(6, 0.3))
    y = geo.y_mm / 1000.0
    lift = 600.0 * np.sqrt(np.clip(1 - (y / 0.9) ** 2, 0, 1))  # N/m
    shear = np.array([np.trapezoid(lift[i:], y[i:]) for i in range(len(y))])
    bending = np.array([np.trapezoid(shear[i:], y[i:]) for i in range(len(y))])
    return geo, th, lift, shear, bending


def test_mesh_is_structured_and_conserves_load(case):
    geo, th, lift, _, _ = case
    mesh = build_mesh(geo, th, n_span=48, n_width=8, n_height=3)
    assert mesh.n_elements == 48 * 2 * (8 + 3) + 6 * 8 * 3  # box shell + 6 ribs
    forces = nodal_lift_forces(mesh, geo.y_mm, lift)
    assert sum(forces.values()) == pytest.approx(float(np.trapezoid(lift, geo.y_mm / 1000.0)), rel=1e-5)
    assert not set(forces) & set(mesh.root_nodes)  # nothing applied to clamped nodes
    assert "*STATIC, SOLVER=SPOOLES" in write_deck(mesh, AL, "static", forces)
    assert "*BUCKLE, SOLVER=SPOOLES" in write_deck(mesh, AL, "buckle", forces)
    assert "*FREQUENCY, SOLVER=SPOOLES" in write_deck(mesh, AL, "frequency")


def test_parsers_read_ccx_tables():
    buckle = (
        "\n     B U C K L I N G   F A C T O R   O U T P U T\n\n MODE NO       BUCKLING\n"
        "                FACTOR\n\n      1   0.1727516E+01\n      2   0.1823600E+01\n\n"
    )
    assert parse_buckling_factors(buckle) == [1.727516, 1.8236]
    freq = (
        "\n    E I G E N V A L U E   O U T P U T\n\n MODE NO    EIGENVALUE      OMEGA          FREQUENCY\n"
        "                                       REAL PART  (RAD/TIME) (CYCLES/TIME)\n\n"
        "      1   0.1802E+06   0.4245E+03   0.6757E+02   0.0000E+00\n\n"
    )
    assert parse_frequencies_hz(freq) == pytest.approx([67.57])


@pytest.mark.skipif(not CALCULIX_AVAILABLE, reason="CalculiX (ccx) not installed")
def test_fe_matches_closed_form(case, tmp_path):
    geo, th, lift, shear, bending = case
    fe = StructuresAgent().evaluate_wing_box(geo, th, AL, geo.y_mm, lift, n_span=96, n_width=12, n_height=4,
                                             work_dir=str(tmp_path))
    cf = analyze_box(geo, th, AL, shear, bending, 1.0)
    # exact equilibrium
    assert fe.equilibrium_error_pct < 1e-4
    # tip deflection: shells include shear flexibility -> FE slightly softer
    assert fe.tip_deflection_mm == pytest.approx(cf.tip_deflection_mm, rel=0.05)
    assert fe.tip_deflection_mm >= cf.tip_deflection_mm
    # cover membrane stress at mid-bay stations of the inboard bays
    for y in (75.0, 225.0, 375.0, 525.0):
        fe_s = abs(float(np.interp(y, fe.cover_stress_y_mm, fe.cover_stress_mpa)))
        assert fe_s == pytest.approx(float(np.interp(y, cf.y_mm, cf.bending_stress_mpa)), rel=0.03)
    # buckling: real edge restraint lies between simply supported (k=4) and clamped (k=6.97) edges
    loaded = cf.bending_stress_mpa > 0
    ss_factor = float(np.min(cf.cover_buckling_mpa[loaded] / cf.bending_stress_mpa[loaded]))
    assert ss_factor <= fe.buckling_factors[0] <= ss_factor * 6.97 / 4.0
    # first vertical bending frequency vs an Euler-Bernoulli beam with the rib masses
    ribs = [
        (yr, float(np.interp(yr, geo.y_mm, geo.width_mm) * np.interp(yr, geo.y_mm, geo.height_mm)
                   * 1.0e-9 * AL.density_kgm3))
        for yr in np.linspace(150, 900, 6)
    ]
    f_beam = beam_natural_frequencies(geo, th, AL, 1, point_masses=ribs)[0]
    assert fe.frequencies_hz[0] == pytest.approx(f_beam, rel=0.05)


@pytest.mark.skipif(not CALCULIX_AVAILABLE, reason="CalculiX (ccx) not installed")
def test_buckling_eigenvalue_is_mesh_converged_and_repeatable(case, tmp_path):
    geo, th, lift, _, _ = case
    agent = StructuresAgent()

    def run(ns, nw, nh, tag):
        return agent.evaluate_wing_box(geo, th, AL, geo.y_mm, lift, n_span=ns, n_width=nw, n_height=nh,
                                       n_frequency_modes=1, work_dir=str(tmp_path / tag))

    coarse, fine, again = run(48, 8, 3, "c"), run(96, 12, 4, "f"), run(96, 12, 4, "f2")
    assert fine.buckling_factors[0] == pytest.approx(coarse.buckling_factors[0], rel=0.02)
    assert again.buckling_factors == fine.buckling_factors  # single-threaded ccx: deterministic
