"""Design loads: CS-23 gust formula, V-n envelope, shear/bending integration."""

import math

import numpy as np
import pytest

from engineering.analysis.wing_lifting_line import elliptic_chord, solve_lifting_line
from engineering.analysis.wing_loads import (
    WingLoadsError,
    gust_load_factors,
    load_envelope,
    spanwise_loads,
)


def test_gust_formula_hand_calculation():
    # W/S = 300 Pa, c = 0.25 m, CLa = 4.8/rad, V = 25 m/s
    ws, c, cla, v = 300.0, 0.25, 4.8, 25.0
    mu = 2 * ws / (1.225 * c * cla * 9.81)
    kg = 0.88 * mu / (5.3 + mu)
    dn = kg * 1.225 * 15.24 * v * cla / (2 * ws)
    n_pos, n_neg, mu_out, kg_out = gust_load_factors(ws, c, cla, v)
    assert mu_out == pytest.approx(mu)
    assert kg_out == pytest.approx(kg)
    assert n_pos == pytest.approx(1 + dn)
    assert n_neg == pytest.approx(1 - dn)


def test_envelope_picks_governing_case_and_ultimate_factor():
    env = load_envelope(12.0, 0.44, 0.24, 4.87, 1.32, 25.0)
    assert env.n_limit == pytest.approx(max(3.8, env.n_gust_pos, env.gust_n_pos[-1]))
    assert env.n_ultimate == pytest.approx(1.5 * env.n_limit)
    assert env.governing_case in ("manoeuvre", "gust")
    # stall line: n = q CLmax S / W
    w = 12.0 * 9.81
    i = np.searchsorted(env.vn_speed_mps, 20.0)
    v = env.vn_speed_mps[i]
    assert env.vn_n_pos[i] == pytest.approx(min(0.5 * 1.225 * v**2 * 1.32 * 0.44 / w, 3.8), rel=1e-9)
    assert env.v_stall_mps == pytest.approx(math.sqrt(w / 0.44 / (0.5 * 1.225 * 1.32)))


def test_heavier_wing_loading_lowers_gust_factor():
    light = load_envelope(5.0, 0.44, 0.24, 4.8, 1.3, 25.0)
    heavy = load_envelope(20.0, 0.44, 0.24, 4.8, 1.3, 25.0)
    assert heavy.n_gust_pos < light.n_gust_pos


def test_elliptic_loading_shear_and_root_moment_closed_form():
    span = 2.0
    ll = solve_lifting_line(span, elliptic_chord(0.3, span), math.radians(5), 2 * math.pi, n_terms=20,
                            n_output=2001)
    total = 1000.0
    sl = spanwise_loads(ll, total, load_factor=2.0)
    semispan_lift = 0.5 * 2.0 * total
    assert sl.root_shear_n == pytest.approx(semispan_lift, rel=1e-3)
    # elliptic load: centroid of a quarter ellipse at 4 s / (3 pi) from the root
    assert sl.root_bending_nm == pytest.approx(semispan_lift * 4 * (span / 2) / (3 * math.pi), rel=2e-3)
    assert sl.shear_n[-1] == pytest.approx(0.0, abs=1e-9)
    assert np.all(np.diff(sl.bending_nm) <= 1e-9)


def test_rejects_bad_envelope_inputs():
    with pytest.raises(WingLoadsError):
        load_envelope(12.0, 0.44, 0.24, 4.8, 1.3, 25.0, n_pos=0.5)
