"""Prandtl lifting-line analysis for straight (unswept) tapered wings.

Replaces the "2D section CL x planform area" shortcut of `wing_aero.py` with
the classical finite-wing correction: a finite wing sheds trailing vorticity,
which induces a downwash that lowers the effective angle of attack, so a 3D
wing makes *less* lift than its 2D section at the same geometric angle and
pays induced drag for it.

Formulation (Glauert's Fourier / monoplane-equation collocation, e.g.
Anderson, *Fundamentals of Aerodynamics*, sec. 5.3; Katz & Plotkin sec. 8.1):

    Gamma(theta) = 2 b V  sum_n A_n sin(n theta),   y = -(b/2) cos(theta)

    sum_n A_n sin(n theta_i) (mu_i n + sin theta_i) = mu_i (alpha_i - alpha_L0) sin theta_i,
    mu_i = c_i a0 / (4 b)

solved at collocation points theta_i in (0, pi/2] for a symmetric wing (odd n
only). Then

    CL  = pi AR A_1
    CDi = pi AR sum_n n A_n^2  =  CL^2 / (pi e AR),   e = 1 / (1 + delta)
    cl(y) = 2 Gamma / (V c),   lift per unit span l(y) = rho V Gamma.

The section lift-curve slope a0 and zero-lift angle alpha_L0 come from the
Aerodynamics Agent (NeuralFoil by default) by finite difference at the
mean-geometric-chord Reynolds number (`section_lift_parameters`), i.e. the
linear part of the real section polar -- lifting-line theory is a linear
theory and is only valid below stall.

Validity: unswept, moderate-to-high aspect-ratio wings (AR >~ 4), attached
flow, incompressible. Sweep is not modelled; that is why the structural
campaign (`wing_campaign.py`) uses an unswept planform.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from agents.aerodynamics.agent import AerodynamicsAgent, AerodynamicsEvaluationError


class LiftingLineError(ValueError):
    """Raised for non-physical lifting-line inputs."""


@dataclass
class SectionLiftParameters:
    """Linear part of a 2D section polar."""

    naca_airfoil: str
    reynolds_number: float
    a0_per_rad: float  # section lift-curve slope dcl/dalpha
    alpha_l0_rad: float  # zero-lift angle of attack
    backend: str


@dataclass
class LiftingLineResult:
    """Finite-wing aerodynamic solution."""

    span_m: float
    area_m2: float
    aspect_ratio: float
    alpha_rad: float
    n_terms: int
    coefficients: np.ndarray  # A_1, A_3, A_5, ... (odd harmonics)
    cl_wing: float  # 3D wing lift coefficient CL
    cdi: float  # induced drag coefficient
    span_efficiency: float  # Oswald span efficiency e (= 1 for elliptic loading)
    cl_alpha_per_rad: float  # 3D lift-curve slope dCL/dalpha
    y_m: np.ndarray  # spanwise stations (one semispan, root -> tip)
    chord_m: np.ndarray
    cl_section: np.ndarray  # local section cl(y)
    gamma_over_v: np.ndarray  # circulation / freestream speed, Gamma/V [m]

    def lift_per_span(self, velocity_mps: float, air_density_kgm3: float) -> np.ndarray:
        """Running lift l(y) = rho V Gamma(y) [N/m] at the stored stations."""
        return air_density_kgm3 * velocity_mps**2 * self.gamma_over_v

    def lift_n(self, velocity_mps: float, air_density_kgm3: float) -> float:
        """Total wing lift [N] = q S CL."""
        return 0.5 * air_density_kgm3 * velocity_mps**2 * self.area_m2 * self.cl_wing


def tapered_chord(root_chord_m: float, tip_chord_m: float, span_m: float):
    """Linear (trapezoidal) chord distribution c(y), y measured from the root."""

    def chord(y: np.ndarray) -> np.ndarray:
        return root_chord_m + (tip_chord_m - root_chord_m) * np.abs(y) / (span_m / 2.0)

    return chord


def elliptic_chord(root_chord_m: float, span_m: float):
    """Elliptic chord distribution c(y) = c0 sqrt(1 - (2y/b)^2)."""

    def chord(y: np.ndarray) -> np.ndarray:
        eta = np.clip(2.0 * np.abs(y) / span_m, 0.0, 1.0)
        return root_chord_m * np.sqrt(1.0 - eta**2)

    return chord


def solve_lifting_line(
    span_m: float,
    chord_fn,
    alpha_rad: float,
    a0_per_rad: float,
    alpha_l0_rad: float = 0.0,
    n_terms: int = 24,
    n_output: int = 81,
    area_m2: float | None = None,
) -> LiftingLineResult:
    """Solve the monoplane equation for a symmetric, untwisted, unswept wing.

    Args:
        span_m: Tip-to-tip span b [m].
        chord_fn: c(y) [m] for y in [0, b/2] (vectorised; symmetric in y).
        alpha_rad: Geometric angle of attack (root and tip; no twist).
        a0_per_rad: Section lift-curve slope (2 pi for thin-airfoil theory).
        alpha_l0_rad: Section zero-lift angle (negative for positive camber).
        n_terms: Number of odd Fourier harmonics (A_1, A_3, ...).
        n_output: Number of output stations on the semispan.
        area_m2: Planform area; integrated from chord_fn if omitted.
    """
    if span_m <= 0:
        raise LiftingLineError(f"span_m must be positive, got {span_m}.")
    if a0_per_rad <= 0:
        raise LiftingLineError(f"a0_per_rad must be positive, got {a0_per_rad}.")
    if n_terms < 1:
        raise LiftingLineError(f"n_terms must be >= 1, got {n_terms}.")

    if area_m2 is None:
        yy = np.linspace(0.0, span_m / 2.0, 2001)
        area_m2 = 2.0 * float(np.trapezoid(chord_fn(yy), yy))
    if area_m2 <= 0:
        raise LiftingLineError("Planform area must be positive.")
    aspect_ratio = span_m**2 / area_m2

    n = np.arange(1, 2 * n_terms, 2)  # odd harmonics only (symmetric loading)
    # Collocation at theta_i = i pi / (2 N), i = 1..N, all in (0, pi/2].
    theta = np.arange(1, n_terms + 1) * math.pi / (2.0 * n_terms)
    y_col = (span_m / 2.0) * np.cos(theta)  # distance from root
    c_col = chord_fn(y_col)
    mu = c_col * a0_per_rad / (4.0 * span_m)

    sin_nt = np.sin(np.outer(theta, n))
    lhs = sin_nt * (mu[:, None] * n[None, :] + np.sin(theta)[:, None])
    rhs = mu * (alpha_rad - alpha_l0_rad) * np.sin(theta)
    coeffs = np.linalg.solve(lhs, rhs)

    cl_wing = math.pi * aspect_ratio * coeffs[0]
    if abs(coeffs[0]) > 0:
        delta = float(np.sum(n[1:] * (coeffs[1:] / coeffs[0]) ** 2))
    else:
        delta = 0.0
    cdi = math.pi * aspect_ratio * float(np.sum(n * coeffs**2))
    e = 1.0 / (1.0 + delta)

    # Output stations root -> tip on the semispan (theta = pi/2 -> 0).
    y_out = np.linspace(0.0, span_m / 2.0, n_output)
    th_out = np.arccos(np.clip(y_out / (span_m / 2.0), -1.0, 1.0))
    gamma_over_v = 2.0 * span_m * (np.sin(np.outer(th_out, n)) @ coeffs)
    c_out = chord_fn(y_out)
    with np.errstate(divide="ignore", invalid="ignore"):
        cl_local = np.where(c_out > 1e-12, 2.0 * gamma_over_v / np.maximum(c_out, 1e-12), 0.0)

    d_alpha = alpha_rad - alpha_l0_rad
    cl_alpha = cl_wing / d_alpha if abs(d_alpha) > 1e-12 else float("nan")

    return LiftingLineResult(
        span_m=span_m,
        area_m2=area_m2,
        aspect_ratio=aspect_ratio,
        alpha_rad=alpha_rad,
        n_terms=n_terms,
        coefficients=coeffs,
        cl_wing=float(cl_wing),
        cdi=float(cdi),
        span_efficiency=float(e),
        cl_alpha_per_rad=float(cl_alpha),
        y_m=y_out,
        chord_m=c_out,
        cl_section=cl_local,
        gamma_over_v=gamma_over_v,
    )


def section_lift_parameters(
    naca_airfoil: str,
    reynolds_number: float,
    backend: str = "neuralfoil",
    alpha_low_deg: float = 0.0,
    alpha_high_deg: float = 4.0,
) -> SectionLiftParameters:
    """a0 and alpha_L0 from the real section polar by finite difference.

    Two section evaluations in the linear range (default 0 and 4 deg):
    a0 = (cl_hi - cl_lo) / (alpha_hi - alpha_lo), alpha_L0 = alpha_lo - cl_lo / a0.
    """
    agent = AerodynamicsAgent()
    try:
        lo = agent.evaluate_naca_airfoil(naca_airfoil, alpha_low_deg, reynolds_number, backend=backend)
        hi = agent.evaluate_naca_airfoil(naca_airfoil, alpha_high_deg, reynolds_number, backend=backend)
    except AerodynamicsEvaluationError as exc:
        raise LiftingLineError(f"Section polar evaluation failed: {exc}") from exc
    d_alpha = math.radians(alpha_high_deg - alpha_low_deg)
    a0 = (hi.cl - lo.cl) / d_alpha
    if a0 <= 0:
        raise LiftingLineError(f"Non-positive section lift slope {a0:.3f}/rad from the polar.")
    alpha_l0 = math.radians(alpha_low_deg) - lo.cl / a0
    return SectionLiftParameters(
        naca_airfoil=naca_airfoil,
        reynolds_number=reynolds_number,
        a0_per_rad=float(a0),
        alpha_l0_rad=float(alpha_l0),
        backend=hi.backend,
    )


def section_cl_max(
    naca_airfoil: str, reynolds_number: float, backend: str = "neuralfoil"
) -> float:
    """Section maximum lift coefficient from a 0.5-deg alpha sweep (0..20 deg)."""
    agent = AerodynamicsAgent()
    best = -math.inf
    for a in np.arange(0.0, 20.01, 0.5):
        cl = agent.evaluate_naca_airfoil(naca_airfoil, float(a), reynolds_number, backend=backend).cl
        if cl < best - 0.02:  # past the peak
            break
        best = max(best, cl)
    return float(best)


def evaluate_tapered_wing(
    span_m: float,
    root_chord_m: float,
    tip_chord_m: float,
    alpha_deg: float,
    naca_airfoil: str,
    velocity_mps: float,
    air_density_kgm3: float = 1.225,
    kinematic_viscosity_m2s: float = 1.46e-5,
    backend: str = "neuralfoil",
    n_terms: int = 24,
    section: SectionLiftParameters | None = None,
) -> tuple[LiftingLineResult, SectionLiftParameters]:
    """Lifting-line solution for a trapezoidal wing, section data at mean-chord Re."""
    mean_chord = 0.5 * (root_chord_m + tip_chord_m)
    re = velocity_mps * mean_chord / kinematic_viscosity_m2s
    if section is None:
        section = section_lift_parameters(naca_airfoil, re, backend=backend)
    res = solve_lifting_line(
        span_m,
        tapered_chord(root_chord_m, tip_chord_m, span_m),
        math.radians(alpha_deg),
        section.a0_per_rad,
        section.alpha_l0_rad,
        n_terms=n_terms,
        area_m2=span_m * mean_chord,
    )
    return res, section
