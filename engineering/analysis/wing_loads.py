"""Wing design loads: V-n envelope, CS-23 gust, and spanwise shear/bending.

Design load factors
-------------------
* Manoeuvre limit load factors n_pos / n_neg (defaults +3.8 / -1.5, the
  CS-23.337 normal-category values; for a small UAV they are a design choice,
  not a certification requirement -- override as needed).
* Gust: CS-23.341 Pratt formula at the design cruise speed Vc,

      mu_g = 2 (W/S) / (rho c_bar CL_alpha g),   Kg = 0.88 mu_g / (5.3 + mu_g)
      dn   = Kg rho0 Ude Ve CL_alpha / (2 W/S),   Ude = 15.24 m/s (50 ft/s) at Vc

  evaluated at sea level (Ve = V). CL_alpha is the 3D lift-curve slope from
  the lifting-line solution, not the 2D section value.
* Ultimate load = limit load x 1.5 (CS-23.303 / CS 25.303 factor of safety).

Spanwise loads
--------------
The lift distribution shape comes from the lifting-line solution and is
scaled so that the whole wing carries n x W. Shear V(y) and bending moment
M(y) are integrated from the tip inboard. Wing inertia relief (the wing's own
weight and anything mounted on it pulling the other way) is IGNORED, which is
conservative: it over-predicts root bending. Torsion is not computed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from engineering.analysis.wing_lifting_line import LiftingLineResult

G = 9.81
RHO0 = 1.225
CS23_GUST_UDE_VC_MPS = 15.24  # 50 ft/s derived gust velocity at Vc
ULTIMATE_FACTOR = 1.5


class WingLoadsError(ValueError):
    """Raised for non-physical load-case inputs."""


@dataclass
class LoadEnvelope:
    """Design load factors and V-n diagram data."""

    mass_kg: float
    wing_loading_pa: float  # W/S [N/m^2]
    cl_alpha_per_rad: float
    cl_max: float
    cl_min: float
    v_cruise_mps: float
    v_dive_mps: float
    v_stall_mps: float
    v_maneuver_mps: float  # Va: stall line meets n_pos
    n_pos_maneuver: float
    n_neg_maneuver: float
    gust_mass_ratio: float
    gust_alleviation_kg: float
    n_gust_pos: float  # at Vc
    n_gust_neg: float
    n_limit: float  # governing positive limit load factor
    n_ultimate: float
    governing_case: str
    vn_speed_mps: np.ndarray
    vn_n_pos: np.ndarray  # manoeuvre envelope upper boundary
    vn_n_neg: np.ndarray
    gust_speed_mps: np.ndarray  # gust polygon vertices: 0, Vc, Vd
    gust_n_pos: np.ndarray
    gust_n_neg: np.ndarray


@dataclass
class SpanwiseLoads:
    """Semispan shear and bending moment for one load factor."""

    load_factor: float
    y_m: np.ndarray  # root -> tip
    lift_per_span_npm: np.ndarray
    shear_n: np.ndarray
    bending_nm: np.ndarray
    semispan_lift_n: float

    @property
    def root_bending_nm(self) -> float:
        return float(self.bending_nm[0])

    @property
    def root_shear_n(self) -> float:
        return float(self.shear_n[0])


def gust_load_factors(
    wing_loading_pa: float,
    mean_chord_m: float,
    cl_alpha_per_rad: float,
    velocity_mps: float,
    ude_mps: float = CS23_GUST_UDE_VC_MPS,
    air_density_kgm3: float = RHO0,
) -> tuple[float, float, float, float]:
    """CS-23.341 gust load factors (n_pos, n_neg, mu_g, Kg)."""
    if wing_loading_pa <= 0 or mean_chord_m <= 0 or cl_alpha_per_rad <= 0:
        raise WingLoadsError("wing loading, mean chord and CL_alpha must be positive.")
    mu = 2.0 * wing_loading_pa / (air_density_kgm3 * mean_chord_m * cl_alpha_per_rad * G)
    kg = 0.88 * mu / (5.3 + mu)
    dn = kg * air_density_kgm3 * ude_mps * velocity_mps * cl_alpha_per_rad / (2.0 * wing_loading_pa)
    return 1.0 + dn, 1.0 - dn, mu, kg


def load_envelope(
    mass_kg: float,
    area_m2: float,
    mean_chord_m: float,
    cl_alpha_per_rad: float,
    cl_max: float,
    v_cruise_mps: float,
    cl_min: float | None = None,
    n_pos: float = 3.8,
    n_neg: float = -1.5,
    dive_factor: float = 1.4,
    ultimate_factor: float = ULTIMATE_FACTOR,
    air_density_kgm3: float = RHO0,
) -> LoadEnvelope:
    """Build the V-n diagram and pick the governing positive limit load factor."""
    if mass_kg <= 0 or area_m2 <= 0 or v_cruise_mps <= 0 or cl_max <= 0:
        raise WingLoadsError("mass, area, cruise speed and CL_max must be positive.")
    if n_pos <= 1.0 or n_neg >= 0.0:
        raise WingLoadsError("expected n_pos > 1 and n_neg < 0.")
    cl_min = -0.6 * cl_max if cl_min is None else cl_min
    w = mass_kg * G
    ws = w / area_m2
    q_per_v2 = 0.5 * air_density_kgm3
    v_stall = math.sqrt(ws / (q_per_v2 * cl_max))
    v_a = v_stall * math.sqrt(n_pos)
    v_d = dive_factor * v_cruise_mps

    v = np.linspace(0.0, v_d, 400)
    n_up = np.minimum(q_per_v2 * v**2 * cl_max / ws, n_pos)
    n_dn = np.maximum(q_per_v2 * v**2 * cl_min / ws, n_neg)

    n_gp, n_gn, mu, kg = gust_load_factors(ws, mean_chord_m, cl_alpha_per_rad, v_cruise_mps,
                                           air_density_kgm3=air_density_kgm3)
    # CS-23.341: Ude = 50 ft/s at Vc, 25 ft/s at Vd -> gust polygon (0,1)-(Vc)-(Vd)
    n_gdp, n_gdn, _, _ = gust_load_factors(ws, mean_chord_m, cl_alpha_per_rad, v_d,
                                           ude_mps=CS23_GUST_UDE_VC_MPS / 2.0,
                                           air_density_kgm3=air_density_kgm3)
    gv = np.array([0.0, v_cruise_mps, v_d])
    n_limit = max(n_pos, n_gp, n_gdp)
    case = "manoeuvre" if n_pos >= max(n_gp, n_gdp) else "gust"
    return LoadEnvelope(
        mass_kg=mass_kg,
        wing_loading_pa=ws,
        cl_alpha_per_rad=cl_alpha_per_rad,
        cl_max=cl_max,
        cl_min=cl_min,
        v_cruise_mps=v_cruise_mps,
        v_dive_mps=v_d,
        v_stall_mps=v_stall,
        v_maneuver_mps=v_a,
        n_pos_maneuver=n_pos,
        n_neg_maneuver=n_neg,
        gust_mass_ratio=mu,
        gust_alleviation_kg=kg,
        n_gust_pos=n_gp,
        n_gust_neg=n_gn,
        n_limit=n_limit,
        n_ultimate=ultimate_factor * n_limit,
        governing_case=case,
        vn_speed_mps=v,
        vn_n_pos=n_up,
        vn_n_neg=n_dn,
        gust_speed_mps=gv,
        gust_n_pos=np.array([1.0, n_gp, n_gdp]),
        gust_n_neg=np.array([1.0, n_gn, n_gdn]),
    )


def spanwise_loads(ll: LiftingLineResult, total_lift_n: float, load_factor: float = 1.0) -> SpanwiseLoads:
    """Shear and bending on one semispan for a wing carrying `load_factor * total_lift_n`.

    The lifting-line circulation shape is scaled so that both halves together
    carry exactly load_factor * total_lift_n (inertia relief ignored).
    """
    y = np.asarray(ll.y_m, dtype=float)
    shape = np.asarray(ll.gamma_over_v, dtype=float)
    integral = float(np.trapezoid(shape, y))
    if integral <= 0:
        raise WingLoadsError("Lifting-line lift distribution must be positive.")
    semispan_lift = 0.5 * load_factor * total_lift_n
    lift = shape * semispan_lift / integral
    shear = _cumulative_from_tip(lift, y)
    bending = _cumulative_from_tip(shear, y)
    return SpanwiseLoads(
        load_factor=load_factor,
        y_m=y,
        lift_per_span_npm=lift,
        shear_n=shear,
        bending_nm=bending,
        semispan_lift_n=semispan_lift,
    )


def _cumulative_from_tip(f: np.ndarray, y: np.ndarray) -> np.ndarray:
    """F(y) = integral_y^tip f dy (trapezoidal)."""
    seg = 0.5 * (f[1:] + f[:-1]) * np.diff(y)
    out = np.zeros_like(f)
    out[:-1] = np.cumsum(seg[::-1])[::-1]
    return out
