"""Lifting-line validation: elliptic closed form, Glauert's rectangular-wing delta, convergence."""

import math

import numpy as np
import pytest

from engineering.analysis.wing_lifting_line import (
    LiftingLineError,
    elliptic_chord,
    evaluate_tapered_wing,
    section_lift_parameters,
    solve_lifting_line,
    tapered_chord,
)


@pytest.mark.parametrize("aspect_ratio", [6.0, 8.0, 12.0])
@pytest.mark.parametrize("a0", [2 * math.pi, 5.7])
def test_elliptic_wing_matches_closed_form(aspect_ratio, a0):
    span = 2.0
    c0 = 4.0 * span / (math.pi * aspect_ratio)  # S = pi b c0 / 4
    alpha = math.radians(5.0)
    res = solve_lifting_line(span, elliptic_chord(c0, span), alpha, a0, 0.0, n_terms=20,
                             area_m2=math.pi * span * c0 / 4.0)
    exact = a0 * alpha / (1.0 + a0 / (math.pi * aspect_ratio))
    assert res.cl_wing == pytest.approx(exact, rel=5e-3)
    assert res.span_efficiency == pytest.approx(1.0, rel=5e-3)
    assert res.cdi == pytest.approx(res.cl_wing**2 / (math.pi * aspect_ratio), rel=5e-3)
    # elliptic loading: constant section cl along the span (away from the tip)
    inner = res.y_m < 0.9 * span / 2
    assert np.ptp(res.cl_section[inner]) < 1e-3


def test_zero_lift_angle_shifts_lift_linearly():
    span, c0 = 2.0, 0.3
    a0 = 2 * math.pi
    r1 = solve_lifting_line(span, elliptic_chord(c0, span), math.radians(2.0), a0, math.radians(-4.0))
    r2 = solve_lifting_line(span, elliptic_chord(c0, span), math.radians(6.0), a0, 0.0)
    assert r1.cl_wing == pytest.approx(r2.cl_wing, rel=1e-9)


def test_rectangular_wing_matches_glauert_delta():
    # Glauert / Anderson Fig. 5.20: rectangular AR = 6 wing, delta ~ 0.046-0.05
    span = 6.0
    res = solve_lifting_line(span, tapered_chord(1.0, 1.0, span), math.radians(5.0), 2 * math.pi, n_terms=40)
    assert 1.0 / res.span_efficiency - 1.0 == pytest.approx(0.048, abs=0.005)


def test_converges_with_number_of_terms():
    span = 10.0
    chord = tapered_chord(1.0, 0.4, span)
    vals = [solve_lifting_line(span, chord, math.radians(4.0), 2 * math.pi, n_terms=n).cl_wing
            for n in (8, 16, 32, 64)]
    diffs = np.abs(np.diff(vals))
    assert diffs[-1] < diffs[0]
    assert abs(vals[-1] - vals[-2]) / vals[-1] < 1e-3


def test_lift_per_span_integrates_to_total_lift():
    span = 1.8
    res = solve_lifting_line(span, tapered_chord(0.3, 0.18, span), math.radians(4.0), 6.2, math.radians(-4.0))
    v, rho = 25.0, 1.225
    semispan_lift = float(np.trapezoid(res.lift_per_span(v, rho), res.y_m))
    assert 2.0 * semispan_lift == pytest.approx(res.lift_n(v, rho), rel=2e-3)


def test_finite_wing_makes_less_lift_than_section():
    res, sec = evaluate_tapered_wing(1.8, 0.30, 0.18, 4.0, "4412", 25.0)
    section_cl = sec.a0_per_rad * (math.radians(4.0) - sec.alpha_l0_rad)
    assert res.cl_wing < section_cl
    assert 0.9 < res.span_efficiency <= 1.0


def test_section_parameters_from_neuralfoil_are_physical():
    sym = section_lift_parameters("0012", 4e5)
    cam = section_lift_parameters("4412", 4e5)
    assert 5.0 < sym.a0_per_rad < 7.5  # near thin-airfoil 2 pi
    assert abs(math.degrees(sym.alpha_l0_rad)) < 0.3
    assert -5.5 < math.degrees(cam.alpha_l0_rad) < -3.0  # thin-airfoil theory: ~ -4.2 deg for 4% camber


def test_rejects_bad_inputs():
    with pytest.raises(LiftingLineError):
        solve_lifting_line(-1.0, tapered_chord(1, 1, 1), 0.1, 6.0)
    with pytest.raises(LiftingLineError):
        solve_lifting_line(1.0, tapered_chord(1, 1, 1), 0.1, 0.0)
