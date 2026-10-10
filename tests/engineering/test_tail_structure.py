"""v0.16 tail internal structure: loads, Schrenk distribution, box sizing, built-up CAD."""

import math
from types import SimpleNamespace

import numpy as np
import pytest

from agents.geometry.fuselage_tail import SurfaceGeometry
from engineering.analysis.tail_structure import (
    CS23_UDE_VC_MPS,
    helmbold_slope,
    schrenk,
    shear_bending,
    tail_load_cases,
)

HT = SurfaceGeometry(176.6, 123.6, 337.7, 0.0, "0009", 0.70)
VT = SurfaceGeometry(203.1, 121.8, 259.9, 25.0, "0010", 0.65)


def _design():
    env = SimpleNamespace(v_maneuver_mps=35.7, v_cruise_mps=25.0, v_dive_mps=35.0, gust_alleviation_kg=0.773)
    tail = SimpleNamespace(htail=HT, vtail=VT, x_vtail_le_mm=1007.0, x_htail_le_mm=1041.0)
    return SimpleNamespace(campaign=SimpleNamespace(envelope=env), tail=tail, x_cg_mm=384.0, total_mass_kg=12.0,
                           mass_items=[])


def test_helmbold_limits():
    assert helmbold_slope(1e6) == pytest.approx(2 * math.pi, rel=1e-3)
    assert helmbold_slope(0.01) == pytest.approx(math.pi * 0.01 / 2, rel=0.01)  # slender wing: pi A / 2
    assert helmbold_slope(4.5, 30.0) < helmbold_slope(4.5)


def test_schrenk_carries_the_load_and_root_shear_equals_it():
    y = np.linspace(0, HT.span_mm, 401)
    w = schrenk(HT, 40.0, y)
    assert np.trapezoid(w, y / 1000) == pytest.approx(40.0, rel=2e-3)
    v, m = shear_bending(y, w)
    assert v[0] == pytest.approx(40.0, rel=2e-3)
    ybar = np.trapezoid(w * y / 1000, y / 1000) / 40.0
    assert m[0] == pytest.approx(40.0 * ybar, rel=2e-3)  # root moment = load x centroid
    assert v[-1] == 0 and m[-1] == 0


def test_tail_load_cases_cs23():
    cases, k = tail_load_cases(_design(), deps_dalpha=0.42, izz_kgm2=0.62)
    by = {c.name: c for c in cases}
    q_a = 0.5 * 1.225 * 35.7**2
    assert by["HT manoeuvre (C_Lh,max at V_A)"].load_n == pytest.approx(0.5 * q_a * 2 * HT.area_mm2 * 1e-6)
    s_h = 2 * HT.area_mm2 * 1e-6
    gust = 0.5 * 1.225 * 0.773 * CS23_UDE_VC_MPS * 25.0 * k["a_h"] * s_h * (1 - 0.42) / 2
    assert by[f"HT gust U_de = {CS23_UDE_VC_MPS:.2f} m/s"].load_n == pytest.approx(gust)
    assert 0 < k["k_gt"] < 0.88  # K_gt -> 0.88 as mu_gt -> infinity
    assert all(c.load_n > 0 for c in cases)


def test_sized_tail_boxes_pass_and_cad_matches():
    from engineering.analysis.tail_structure import (
        design_tail_structure,
        tail_mass_items,
    )

    r = design_tail_structure(_design(), 0.42, 0.62, n_profile=15)
    for ts in (r.htail, r.vtail):
        assert ts.sizing.margins.passes
        assert ts.design_case.load_n == max(c.load_n for c in r.cases if c.surface == ts.surface)
        assert all(p.is_valid for ps in ts.structure.parts.values() for p in ps)
    assert r.vtail.box_sweep_deg == pytest.approx(math.degrees(math.atan2(
        VT.span_mm * math.tan(math.radians(25)) + 0.375 * (VT.tip_chord_mm - VT.root_chord_mm), VT.span_mm)))
    items = tail_mass_items(r)
    assert items["Horizontal tail"][0] == pytest.approx(r.htail.total_mass_kg, rel=1e-6)
    assert items["Vertical tail"][0] == pytest.approx(r.vtail.total_mass_kg, rel=1e-6)
    assert 0 < items["Vertical tail"][2] < VT.span_mm  # fin centroid is above its root
