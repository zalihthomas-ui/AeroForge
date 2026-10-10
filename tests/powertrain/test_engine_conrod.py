"""Con-rod check: section properties, Johnson-Euler buckling, load hand-checks, sizing closure."""

import math

import numpy as np
import pytest

from agents.powertrain.spec import EngineSpec
from engineering.analysis.engine_conrod import (
    ISection,
    RodLoads,
    RodMaterial,
    check_rod,
    critical_stress_mpa,
    size_rod,
    worst_case_rod_loads,
)
from engineering.analysis.engine_cycle import full_load_map
from engineering.analysis.engine_dynamics import reciprocating_mass_kg

SPEC = EngineSpec()
MAT = RodMaterial()


def test_i_section_properties_match_numerical_integration():
    s = ISection()
    y = np.linspace(-s.depth_mm / 2, s.depth_mm / 2, 4001)
    width = np.where(np.abs(y) > s.depth_mm / 2 - s.flange_mm, s.width_mm, s.web_mm)
    assert np.trapezoid(width, y) == pytest.approx(s.area_mm2, rel=2e-3)
    assert np.trapezoid(width * y**2, y) == pytest.approx(s.i_in_plane_mm4, rel=2e-3)


def test_buckling_curve_is_euler_when_slender_and_continuous_at_transition():
    transition = math.sqrt(2 * math.pi**2 * MAT.e_mpa / MAT.yield_mpa)
    assert critical_stress_mpa(2 * transition, MAT) == pytest.approx(math.pi**2 * MAT.e_mpa / (2 * transition) ** 2)
    assert critical_stress_mpa(transition - 1e-9, MAT) == pytest.approx(critical_stress_mpa(transition + 1e-9, MAT))
    assert critical_stress_mpa(transition, MAT) == pytest.approx(MAT.yield_mpa / 2)
    assert critical_stress_mpa(0.0, MAT) == pytest.approx(MAT.yield_mpa)


@pytest.fixture(scope="module")
def loads():
    return worst_case_rod_loads(SPEC, full_load_map(SPEC), redline_rpm=7000.0)


def test_redline_tension_matches_hand_calculation(loads):
    omega = 7000 * 2 * math.pi / 60
    r = SPEC.crank_radius_mm / 1000
    hand = reciprocating_mass_kg(SPEC) * r * omega**2 * (1 + SPEC.rod_ratio)  # inertia at TDC
    assert loads.tension_n == pytest.approx(hand, rel=0.02)


def test_peak_compression_is_bounded_by_peak_gas_force(loads):
    m = full_load_map(SPEC)
    gas = (m.p_max_bar.max() * 1e5 - 101_325.0) * SPEC.piston_area_m2
    assert 0.7 * gas < loads.compression_n < 1.05 * gas


def test_sizing_meets_both_targets_with_the_governing_one_active(loads):
    check, _ = size_rod(SPEC, ISection(), loads, min_fatigue_sf=1.5, min_buckling_sf=3.0)
    assert check.fatigue_sf >= 1.5 - 1e-6 and check.buckling_sf >= 3.0 - 1e-6
    assert min(check.fatigue_sf / 1.5, check.buckling_sf / 3.0) == pytest.approx(1.0, abs=1e-3)


def test_bigger_section_is_safer():
    ld = RodLoads(30_000.0, 3000.0, 18_000.0, 7000.0)
    small, big = check_rod(SPEC, ISection().scaled(0.9), ld), check_rod(SPEC, ISection().scaled(1.1), ld)
    assert big.fatigue_sf > small.fatigue_sf and big.buckling_sf > small.buckling_sf
    assert big.shank_mass_kg > small.shank_mass_kg
