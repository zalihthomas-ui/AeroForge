"""Propeller model for the whole-aircraft analysis: actuator-disk thrust/power, slipstream, power effects on stability.

* Actuator-disk momentum theory (Glauert; McCormick, *Aerodynamics, Aeronautics and Flight Mechanics*, ch. 6):
      T = 2 rho A v_i (V + v_i)     ->  v_i = (-V + sqrt(V^2 + 2 T / (rho A))) / 2
  far-wake velocity V + 2 v_i, contracted slipstream radius R_s = R sqrt((V + v_i) / (V + 2 v_i)),
  ideal efficiency eta_i = V / (V + v_i). Real propellers lose another ~15 % to profile drag and swirl, so
  shaft power = T V / (eta_i * eta_profile) with eta_profile = 0.85 (stated assumption).
* Tail in the slipstream: the slipstream tube follows the thrust line, deflected by the wing downwash angle at
  the tail; the part of the stabiliser span inside the tube sees dynamic pressure q (V + 2 v_i)^2 / V^2.
  Outside it, the fuselage-wake factor 0.90 applies (Raymer sec. 16.3 typical eta_h 0.85-0.95).
* Thrust-line moment: thrust T acting along the thrust line at height z_T gives
  Cm_T = T (z_cg - z_T) / (q S c_bar)  (nose-up positive when the thrust line is below the CG).
* Propeller normal force (destabilising, tractor): Delta Cm_alpha = (A_p / (S c_bar)) (x_cg - x_p)/c_bar *
  dCN_p/dalpha * (1 + d eps_u / dalpha) * (q_p / q). dCN_p/dalpha = 0.12 /rad per unit disk area is an assumed
  order-of-magnitude value for a 2-blade propeller at cruise advance ratio (Perkins & Hage; Raymer sec. 16.3);
  the upwash gradient at the propeller d eps_u/dalpha = 0.25 (Raymer). Treat this term as an estimate.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

RHO = 1.225
ETA_PROFILE = 0.85
ETA_FUSELAGE_WAKE = 0.90
DCNP_DALPHA = 0.12
UPWASH_GRADIENT_AT_PROP = 0.25


@dataclass(frozen=True)
class Propeller:
    diameter_m: float = 0.38
    n_blades: int = 2
    x_m: float = -0.015  # disk station
    z_m: float = 0.0  # thrust-line height

    @property
    def area_m2(self) -> float:
        return math.pi * self.diameter_m**2 / 4.0


@dataclass
class PropellerState:
    thrust_n: float
    velocity_mps: float
    induced_velocity_mps: float
    slipstream_velocity_mps: float  # far-wake velocity V + 2 v_i
    slipstream_radius_m: float
    ideal_efficiency: float
    efficiency: float
    shaft_power_w: float

    @property
    def slipstream_q_ratio(self) -> float:
        return (self.slipstream_velocity_mps / self.velocity_mps) ** 2


def actuator_disk(prop: Propeller, thrust_n: float, velocity_mps: float, rho: float = RHO) -> PropellerState:
    if thrust_n < 0 or velocity_mps <= 0:
        raise ValueError("thrust must be >= 0 and velocity > 0")
    a = prop.area_m2
    v_i = 0.5 * (-velocity_mps + math.sqrt(velocity_mps**2 + 2.0 * thrust_n / (rho * a)))
    eta_i = velocity_mps / (velocity_mps + v_i)
    eta = eta_i * ETA_PROFILE
    r_s = prop.diameter_m / 2.0 * math.sqrt((velocity_mps + v_i) / (velocity_mps + 2.0 * v_i))
    return PropellerState(thrust_n, velocity_mps, v_i, velocity_mps + 2.0 * v_i, r_s, eta_i, eta,
                          thrust_n * velocity_mps / eta)


def immersed_fraction(slip_radius_m: float, dz_m: float, tail_semispan_m: float, root_chord_m: float,
                      tip_chord_m: float, n: int = 400) -> float:
    """Area fraction of a symmetric trapezoidal tail lying inside a circular slipstream (offset dz vertically)."""
    if abs(dz_m) >= slip_radius_m:
        return 0.0
    half = math.sqrt(slip_radius_m**2 - dz_m**2)
    ys = [i * tail_semispan_m / n for i in range(n + 1)]
    chord = [root_chord_m + (tip_chord_m - root_chord_m) * y / tail_semispan_m for y in ys]
    total = sum(0.5 * (chord[i] + chord[i + 1]) * (ys[i + 1] - ys[i]) for i in range(n))
    inside = sum(0.5 * (chord[i] + chord[i + 1]) * (ys[i + 1] - ys[i]) for i in range(n) if ys[i + 1] <= half)
    return inside / total


def tail_efficiency(state: PropellerState, immersed: float) -> float:
    """Area-weighted dynamic-pressure ratio q_h / q at the stabiliser (power on)."""
    return ETA_FUSELAGE_WAKE * ((1.0 - immersed) + immersed * state.slipstream_q_ratio)


def thrust_moment_coefficient(thrust_n: float, z_cg_m: float, z_thrust_m: float, q_pa: float, s_m2: float,
                              c_m: float) -> float:
    return thrust_n * (z_cg_m - z_thrust_m) / (q_pa * s_m2 * c_m)


def prop_normal_force_cma(prop: Propeller, state: PropellerState, x_cg_m: float, s_m2: float, c_m: float) -> float:
    """Destabilising Cm_alpha [/rad] of a tractor propeller's normal force (positive = destabilising)."""
    q_ratio = 0.5 * (1.0 + state.slipstream_q_ratio)  # mean dynamic pressure through the disk
    arm = (x_cg_m - prop.x_m) / c_m
    return prop.area_m2 / s_m2 * arm * DCNP_DALPHA * (1.0 + UPWASH_GRADIENT_AT_PROP) * q_ratio
