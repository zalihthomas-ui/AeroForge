"""Crank-train dynamics: slider-crank derivatives, balance theory checks, torque consistency."""

import math

import numpy as np
import pytest

from agents.powertrain.spec import Cylinder, EngineSpec
from engineering.analysis.engine_cycle import run_cycle_mbt
from engineering.analysis.engine_dynamics import (
    crank_torque,
    flywheel_inertia_kgm2,
    inline_six_layout,
    shaking,
    slider_crank,
)

SPEC = EngineSpec()


def test_slider_crank_derivatives_match_finite_differences():
    r, rod = 0.04, 0.145
    phi = np.linspace(0, 2 * math.pi, 2001)
    x, dx, d2x = slider_crank(r, rod, phi)
    h = phi[1] - phi[0]
    assert np.allclose(np.gradient(x, h)[2:-2], dx[2:-2], atol=1e-6)
    assert np.allclose(np.gradient(dx, h)[2:-2], d2x[2:-2], atol=1e-5)
    assert x[0] == pytest.approx(0.0, abs=1e-15) and x[1000] == pytest.approx(2 * r)


def test_single_cylinder_primary_and_secondary_forces_match_theory():
    b = shaking(SPEC, 6000, [Cylinder(1, "R", 0.0, 0.0, 0.0, 0.0)])
    lam = SPEC.rod_ratio
    assert b.force_order_n[1] / b.single_cylinder_primary_n == pytest.approx(1.0, rel=1e-3)
    # exact Fourier coefficient of the 2nd order: lambda + lambda^3/4 + O(lambda^5)
    assert b.force_order_n[2] / b.single_cylinder_primary_n == pytest.approx(lam + lam**3 / 4, rel=2e-3)


def test_inline_six_is_free_of_primary_and_secondary_forces_and_moments():
    b = shaking(SPEC, 6000, inline_six_layout())
    scale = b.single_cylinder_primary_n
    for k in (1, 2):
        assert b.force_order_n[k] < 1e-6 * scale
        assert b.moment_order_nm[k] < 1e-6 * scale


def test_60_deg_v6_has_no_shaking_forces_but_rocking_couples():
    b = shaking(SPEC, 6000)
    scale = b.single_cylinder_primary_n
    assert b.force_order_n[1] < 1e-6 * scale and b.force_order_n[2] < 1e-6 * scale
    assert b.moment_order_nm[1] > 0.01 * scale  # primary couple present (N m vs N: any real magnitude)
    assert b.moment_order_nm[2] > 0.0
    # couples scale with speed squared
    b2 = shaking(SPEC, 3000)
    assert b2.moment_order_nm[1] == pytest.approx(b.moment_order_nm[1] / 4, rel=1e-9)


def test_mean_gas_torque_equals_cycle_work_and_inertia_averages_to_zero():
    c = run_cycle_mbt(SPEC, 3500)
    t = crank_torque(SPEC, c)
    gas_mean = np.trapezoid(t.gas_nm, t.theta_deg) / 720.0
    assert gas_mean == pytest.approx(SPEC.n_cylinders * c.work_j / (4 * math.pi), rel=2e-3)
    assert abs(np.trapezoid(t.inertia_nm, t.theta_deg) / 720.0) < 1e-6 * abs(gas_mean)
    assert t.brake_mean_nm == pytest.approx(c.torque_nm, rel=2e-3)


def test_even_firing_gives_six_torque_pulses_per_cycle():
    t = crank_torque(SPEC, run_cycle_mbt(SPEC, 2000))
    spec = np.abs(np.fft.rfft(t.total_nm[:-1] - t.total_nm[:-1].mean()))
    assert int(np.argmax(spec)) == 6  # dominant order = 6 pulses per 720 deg (3rd engine order)


def test_flywheel_inertia_scales_inversely_with_allowed_fluctuation():
    t = crank_torque(SPEC, run_cycle_mbt(SPEC, 1000))
    i1, de = flywheel_inertia_kgm2(t, 0.02)
    i2, _ = flywheel_inertia_kgm2(t, 0.04)
    assert de > 0 and i1 == pytest.approx(2 * i2, rel=1e-12)
