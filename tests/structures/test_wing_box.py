"""Closed-form thin-walled wing box: section properties, buckling, deflection, sizing."""

import math

import numpy as np
import pytest

from agents.structures.wing_box import (
    MATERIALS,
    BoxThickness,
    WingBoxError,
    WingBoxGeometry,
    analyze_box,
    beam_natural_frequencies,
    box_mass_kg,
    naca4_thickness_ratio,
    section_inertia_mm4,
    size_box,
)

AL = MATERIALS["al6061-t6"]


def _uniform_geometry(length=1000.0, w=100.0, h=30.0, n=401):
    y = np.linspace(0.0, length, n)
    return WingBoxGeometry(y, np.full(n, 250.0), np.full(n, w), np.full(n, h), 0.2, 0.6, "0012")


def test_naca_thickness_law():
    assert naca4_thickness_ratio("0012", 0.3) == pytest.approx(0.12, abs=0.001)  # max thickness near 30 %
    assert naca4_thickness_ratio("4412", 0.6) < naca4_thickness_ratio("4412", 0.2)


def test_inertia_thin_wall_formula():
    i = section_inertia_mm4(100.0, 30.0, 1.0, 0.5)
    assert i == pytest.approx(2 * 100 * 1 * 15**2 + 2 * 0.5 * 30**3 / 12)


def test_uniform_cantilever_tip_load_deflection_and_stress():
    geo = _uniform_geometry()
    th = BoxThickness.uniform(1000.0, 4, 1.0, 0.5)
    p = 200.0  # N at the tip
    shear = np.full_like(geo.y_mm, p)
    bending = p * (1000.0 - geo.y_mm) / 1000.0  # N m
    res = analyze_box(geo, th, AL, shear, bending, 1.0)
    inertia = section_inertia_mm4(100.0, 30.0, 1.0, 0.5)
    assert res.tip_deflection_mm == pytest.approx(p * 1000.0**3 / (3 * AL.youngs_modulus_mpa * inertia), rel=1e-4)
    assert res.bending_stress_mpa[0] == pytest.approx(p * 1000.0 * 15.0 / inertia, rel=1e-9)
    assert res.web_shear_mpa[0] == pytest.approx(p / (2 * 30.0 * 0.5))


def test_plate_buckling_coefficients():
    geo = _uniform_geometry()
    th = BoxThickness.uniform(1000.0, 1, 1.2, 0.6)
    res = analyze_box(geo, th, AL, np.zeros_like(geo.y_mm), np.zeros_like(geo.y_mm), 1.0)
    d = math.pi**2 * AL.youngs_modulus_mpa / (12 * (1 - AL.poissons_ratio**2))
    assert res.cover_buckling_mpa[0] == pytest.approx(4.0 * d * (1.2 / 100.0) ** 2)
    assert res.web_buckling_mpa[0] == pytest.approx(5.35 * d * (0.6 / 30.0) ** 2)


def _elliptic_limit_loads(geo, peak_npm=400.0):
    y = geo.y_mm / 1000.0
    s = geo.semispan_mm / 1000.0
    lift = peak_npm * np.sqrt(np.clip(1 - (y / s) ** 2, 0, 1))
    shear = np.array([np.trapezoid(lift[i:], y[i:]) for i in range(len(y))])
    bending = np.array([np.trapezoid(shear[i:], y[i:]) for i in range(len(y))])
    return lift, shear, bending


def test_sizing_is_minimum_mass_with_non_negative_margins():
    geo = WingBoxGeometry.from_planform(900.0, 305.0, 178.0, "4412", n_stations=181)
    _, shear, bending = _elliptic_limit_loads(geo)
    sz = size_box(geo, AL, shear, bending, n_limit=4.0, n_bays=6, min_gauge_mm=0.3)
    assert sz.margins.passes
    assert np.all(np.diff(sz.thickness.t_cap_mm) <= 1e-12)  # thinner outboard
    # one gauge step (0.05 mm) thinner in any non-minimum-gauge bay must fail that bay
    for b in range(6):
        if sz.thickness.t_cap_mm[b] <= 0.3 + 1e-9:
            continue
        caps = sz.thickness.t_cap_mm.copy()
        caps[b] -= 0.05
        thinner = BoxThickness(sz.thickness.bay_edges_mm, caps, sz.thickness.t_web_mm)
        ult = analyze_box(geo, thinner, AL, 1.5 * shear, 1.5 * bending, 6.0)
        sel = (geo.y_mm >= thinner.bay_edges_mm[b]) & (geo.y_mm <= thinner.bay_edges_mm[b + 1])
        sel &= ult.bending_stress_mpa > 0
        buckling = np.min(ult.cover_buckling_mpa[sel] / ult.bending_stress_mpa[sel])
        strength = np.min(AL.ftu_mpa / ult.bending_stress_mpa[sel])
        assert min(buckling, strength) < 1.0
    assert sz.mass_kg == pytest.approx(box_mass_kg(geo, sz.thickness, AL))


def test_unsizeable_load_raises():
    geo = _uniform_geometry()
    with pytest.raises(WingBoxError):
        size_box(geo, AL, np.full_like(geo.y_mm, 1e7), np.full_like(geo.y_mm, 1e7), 4.0, max_gauge_mm=2.0)


def test_beam_frequency_uniform_cantilever():
    geo = _uniform_geometry(n=101)
    th = BoxThickness.uniform(1000.0, 1, 1.0, 0.5)
    f = beam_natural_frequencies(geo, th, AL, 2, n_elements=60)
    ei = AL.youngs_modulus_mpa * 1e6 * section_inertia_mm4(0.1, 0.03, 1e-3, 0.5e-3)
    mu = AL.density_kgm3 * (2 * 0.1 * 1e-3 + 2 * 0.03 * 0.5e-3)
    exact = [(bl**2 / (2 * math.pi)) * math.sqrt(ei / mu) for bl in (1.8751, 4.6941)]
    assert f[0] == pytest.approx(exact[0], rel=1e-3)
    assert f[1] == pytest.approx(exact[1], rel=2e-3)
