"""v0.16 flight dynamics: propeller model, mass properties, modes, criteria, power-on design."""

import math

import numpy as np
import pytest

from engineering.analysis.flight_dynamics import (
    MIL_LEVEL1,
    analyze_flight_dynamics,
    check_criteria,
    identify_modes,
    mass_properties,
)
from engineering.analysis.propulsion import (
    Propeller,
    actuator_disk,
    immersed_fraction,
    tail_efficiency,
)


def test_actuator_disk_momentum_theory():
    prop = Propeller(diameter_m=0.38)
    st = actuator_disk(prop, 8.0, 25.0)
    # T = 2 rho A v_i (V + v_i)
    assert 2 * 1.225 * prop.area_m2 * st.induced_velocity_mps * (25.0 + st.induced_velocity_mps) == pytest.approx(8.0)
    assert st.slipstream_velocity_mps == pytest.approx(25.0 + 2 * st.induced_velocity_mps)
    # continuity: far-wake area x velocity = disk area x disk velocity
    assert math.pi * st.slipstream_radius_m**2 * st.slipstream_velocity_mps == pytest.approx(
        prop.area_m2 * (25.0 + st.induced_velocity_mps))
    assert st.ideal_efficiency == pytest.approx(25.0 / (25.0 + st.induced_velocity_mps))
    assert st.shaft_power_w == pytest.approx(8.0 * 25.0 / st.efficiency)
    static = actuator_disk(prop, 8.0, 1e-6)
    assert static.induced_velocity_mps == pytest.approx(math.sqrt(8.0 / (2 * 1.225 * prop.area_m2)), rel=1e-3)


def test_slipstream_immersion_geometry():
    # rectangular tail, slipstream centred: fraction = half-width inside / semispan
    assert immersed_fraction(0.2, 0.0, 0.4, 0.15, 0.15) == pytest.approx(0.5, abs=0.01)
    assert immersed_fraction(0.2, 0.25, 0.4, 0.15, 0.15) == 0.0
    st = actuator_disk(Propeller(), 7.0, 25.0)
    assert tail_efficiency(st, 0.0) == pytest.approx(0.90)
    assert tail_efficiency(st, 1.0) == pytest.approx(0.90 * st.slipstream_q_ratio)


def test_mode_identification_and_criteria_on_known_eigenvalues():
    sp = complex(-4.0, 6.0)
    ph = complex(-0.02, 0.4)
    long_eigs = np.array([sp, sp.conjugate(), ph, ph.conjugate()])
    dr = complex(-0.8, 3.0)
    lat_eigs = np.array([-9.0, dr, dr.conjugate(), -0.01])
    m = identify_modes(long_eigs, lat_eigs)
    assert m["short_period"].omega_n == pytest.approx(abs(sp))
    assert m["short_period"].zeta == pytest.approx(4.0 / abs(sp))
    assert m["phugoid"].period_s == pytest.approx(2 * math.pi / 0.4)
    assert m["roll"].time_constant_s == pytest.approx(1 / 9.0)
    assert m["spiral"].time_constant_s == pytest.approx(100.0)
    c = check_criteria(m)
    assert all(ok for _, _, ok in c.values())
    # an unstable spiral that doubles in 10 s fails Level 1 (20 s)
    m2 = identify_modes(long_eigs, np.array([-9.0, dr, dr.conjugate(), math.log(2) / 10.0]))
    assert not check_criteria(m2)["spiral time to double"][2]
    # overdamped short period: equivalent zeta from both real roots
    m3 = identify_modes(np.array([-2.0, -8.0, ph, ph.conjugate()]), lat_eigs)
    assert m3["short_period"].omega_n == pytest.approx(4.0)
    assert m3["short_period"].zeta == pytest.approx(10.0 / 8.0)
    assert MIL_LEVEL1["spiral_time_to_double_min_s"] == 20.0


@pytest.fixture(scope="module")
def flight_ready():
    from engineering.analysis.aircraft_layout import design_aircraft
    from engineering.analysis.wing_campaign import (
        CampaignRequirement,
        build_structure_cad,
        run_campaign,
    )

    c = run_campaign(CampaignRequirement(), run_fe=False)
    st = build_structure_cad(c, n_profile=21)
    d = design_aircraft(c, st.masses_kg(), payload_at_empty_cg=True, sm_target=0.134, wing_x_bounds=(270.0, 285.0))
    d.dihedral_deg = 3.5
    mp = mass_properties(d, st)
    return d, mp, analyze_flight_dynamics(d, st, mass=mp)


def test_cad_mass_properties_match_mass_balance(flight_ready):
    d, mp, _ = flight_ready
    assert mp.mass_kg == pytest.approx(12.0, rel=1e-6)
    assert mp.cg_m[0] * 1e3 == pytest.approx(d.x_cg_mm, abs=3.0)  # CAD centroid CG vs component table
    assert 0 < mp.ixx < mp.izz and mp.iyy < mp.izz  # long fuselage, wide wing: yaw inertia largest
    payload = next(i for i in d.mass_items if i.name == "Payload")
    assert payload.x_mm == pytest.approx(d.x_cg_mm, abs=1.0)  # CG-centred payload bay


def test_flight_ready_design_meets_level1_and_approximations(flight_ready):
    _, _, fd = flight_ready
    assert all(ok for _, _, ok in fd.criteria.values()), fd.criteria
    assert 0.05 <= fd.static_margin_power_on <= 0.15
    # VLM downwash gradient vs the classic estimate 2 CL_alpha / (pi AR)
    assert fd.deps_dalpha == pytest.approx(fd.deps_dalpha_empirical, rel=0.10)
    a = fd.approximations
    assert fd.modes["short_period"].zeta == pytest.approx(a["short_period_zeta_approx"], rel=0.10)
    assert fd.modes["roll"].time_constant_s == pytest.approx(a["roll_tau_approx"], rel=0.10)
    assert fd.modes["dutch_roll"].omega_n == pytest.approx(a["dutch_roll_omega_approx"], rel=0.10)
    assert fd.modes["phugoid"].omega_n == pytest.approx(a["phugoid_omega_lanchester"], rel=0.25)
    # power on: thrust equals drag, slipstream raises the tail dynamic pressure above the power-off 0.90
    t = fd.trim
    assert t.thrust_n == pytest.approx(t.cd * 0.5 * 1.225 * 25**2 * fd_area(flight_ready), rel=1e-3)
    assert t.eta_h > 0.90


def fd_area(flight_ready):
    return flight_ready[0].campaign.aero.lifting_line.area_m2
