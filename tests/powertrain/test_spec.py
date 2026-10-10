"""V6 layout: displacement, even firing, split-pin pairs, TDC convention."""

import itertools
import math

import pytest

from agents.powertrain.spec import EngineSpec, EngineSpecError


def test_displacement_of_default_v6():
    e = EngineSpec()
    assert e.displacement_l == pytest.approx(6 * math.pi / 4 * 0.089**2 * 0.080 * 1000, rel=1e-9)
    assert e.displacement_l == pytest.approx(2.986, abs=0.001)


def test_even_120_deg_firing_and_banks():
    e = EngineSpec()
    fires = sorted(c.firing_angle_deg for c in e.cylinders)
    assert fires == [0.0, 120.0, 240.0, 360.0, 480.0, 600.0]
    assert {c.bank for c in e.cylinders if c.number % 2} == {"R"}
    assert {c.bank for c in e.cylinders if not c.number % 2} == {"L"}


def test_each_cylinder_is_at_tdc_at_its_firing_angle():
    for c in EngineSpec().cylinders:
        assert (c.firing_angle_deg + c.pin_angle_deg - c.axis_angle_deg) % 360.0 == pytest.approx(0.0, abs=1e-9)


def test_split_pin_crank_six_pins_60_deg_apart_paired_on_throws():
    e = EngineSpec()
    pins = sorted(c.pin_angle_deg for c in e.cylinders)
    assert [b - a for a, b in itertools.pairwise(pins)] == pytest.approx([60.0] * 5)
    right = sorted((c for c in e.cylinders if c.bank == "R"), key=lambda c: c.z_mm)
    left = sorted((c for c in e.cylinders if c.bank == "L"), key=lambda c: c.z_mm)
    for r, l in zip(right, left):
        assert (l.pin_angle_deg - r.pin_angle_deg) % 360.0 == pytest.approx(60.0)
        assert l.z_mm - r.z_mm == pytest.approx(e.bank_offset_mm)


def test_invalid_specs_rejected():
    with pytest.raises(EngineSpecError):
        EngineSpec(compression_ratio=1.0)
    with pytest.raises(EngineSpecError):
        EngineSpec(rod_length_mm=30.0)
