"""Engine cycle model: Otto-limit validation, energy balance, physical sanity of the full-load map."""

import math

import numpy as np
import pytest

from agents.powertrain.spec import EngineSpec
from engineering.analysis.engine_cycle import (
    CycleSettings,
    EngineCycleError,
    cylinder_volume_m3,
    full_load_map,
    otto_efficiency,
    run_cycle,
    run_cycle_mbt,
)

SPEC = EngineSpec()
IDEAL = CycleSettings(gamma=1.3, heat_transfer=False)


def test_volume_limits_are_clearance_and_clearance_plus_swept():
    v = cylinder_volume_m3(SPEC, np.array([0.0, math.pi]))
    assert v[0] == pytest.approx(SPEC.clearance_volume_m3, rel=1e-12)
    assert v[1] == pytest.approx(SPEC.clearance_volume_m3 + SPEC.swept_volume_per_cyl_m3, rel=1e-12)
    assert v[1] / v[0] == pytest.approx(SPEC.compression_ratio, rel=1e-12)


@pytest.mark.parametrize("gamma", [1.3, 1.4])
def test_instantaneous_heat_release_reproduces_ideal_otto_efficiency(gamma):
    c = run_cycle(SPEC, 3000, spark_deg=-1e-6, instantaneous_combustion=True,
                  settings=CycleSettings(gamma=gamma, heat_transfer=False))
    assert c.indicated_efficiency == pytest.approx(otto_efficiency(SPEC.compression_ratio, gamma), rel=1e-4)


def test_finite_burn_and_wall_losses_each_reduce_efficiency():
    otto = otto_efficiency(SPEC.compression_ratio, 1.3)
    finite = run_cycle_mbt(SPEC, 3000, IDEAL).indicated_efficiency
    real = run_cycle_mbt(SPEC, 3000).indicated_efficiency
    assert real < finite < otto
    assert 0.33 < real < 0.45  # gross indicated efficiency of a real SI engine


def test_energy_balance_closes():
    c = run_cycle_mbt(SPEC, 4000)
    assert c.work_j + c.wall_heat_loss_j < c.heat_released_j
    assert 0.08 < c.wall_heat_loss_j / c.heat_released_j < 0.20  # literature range for the closed cycle


def test_mbt_peak_pressure_location_is_in_the_classic_band():
    for rpm in (2000, 4000, 6000):
        c = run_cycle_mbt(SPEC, rpm)
        assert 8.0 < c.theta_p_max_deg < 20.0  # MBT: peak pressure ~10-16 deg ATDC


def test_mbt_beats_retarded_and_advanced_spark():
    best = run_cycle_mbt(SPEC, 3000)
    for offset in (-10.0, 10.0):
        assert run_cycle(SPEC, 3000, best.spark_deg + offset).work_j < best.work_j


def test_torque_and_power_follow_from_bmep():
    c = run_cycle_mbt(SPEC, 5000)
    disp = SPEC.swept_volume_per_cyl_m3 * SPEC.n_cylinders
    assert c.torque_nm == pytest.approx(c.bmep_pa * disp / (4 * math.pi), rel=1e-12)
    assert c.power_kw == pytest.approx(c.torque_nm * 5000 * 2 * math.pi / 60 / 1000, rel=1e-12)


def test_full_load_map_is_physically_sane():
    m = full_load_map(SPEC)
    t_peak, n_t = m.peak_torque
    _, n_p = m.peak_power
    assert 60.0 < t_peak / SPEC.displacement_l < 110.0  # N m per litre, naturally aspirated
    assert n_t < n_p  # peak torque below peak power speed
    assert np.all(np.diff(m.fmep_bar) > 0)  # friction rises with speed
    assert np.all(m.p_max_bar < 120.0)


def test_invalid_inputs_rejected():
    with pytest.raises(EngineCycleError):
        run_cycle(SPEC, 0.0)
    with pytest.raises(EngineCycleError):
        run_cycle(SPEC, 3000.0, settings=CycleSettings(gamma=1.0))
