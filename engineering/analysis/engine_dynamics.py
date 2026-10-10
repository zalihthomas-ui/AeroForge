"""Crank-train dynamics of the V6: forces, crank torque, shaking forces/moments, flywheel.

Uses the exact slider-crank kinematics of every cylinder in `EngineSpec` (bank
angle, crank-pin angle, axial position) and the 720 deg pressure trace of
`engine_cycle` (closed cycle from the model; exhaust and intake strokes at
constant placeholder pressures).

* Piston force along the cylinder axis (towards the crank):
  F = (p - p_crankcase) A - m_rec * x''      (x measured from TDC, m_rec = piston group + small-end rod share)
* Crank torque by virtual work: T = F dx/dphi.
* Shaking force on the block from the reciprocating masses only (rotating
  masses are assumed fully counterbalanced, which is what crank counterweights
  are for), and the shaking moment about the middle of the crank.
* Harmonic orders by Fourier analysis over one revolution (order 1 = primary,
  order 2 = secondary).
* Flywheel inertia for a target coefficient of speed fluctuation.

Validation hooks (tests/powertrain): a single cylinder's primary force
amplitude is m r w^2; an inline six is free of primary and secondary forces and
moments; the mean gas torque equals the cycle work x cylinders / 4 pi.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from agents.powertrain.spec import Cylinder, EngineSpec
from engineering.analysis.engine_cycle import CycleResult

# Gas-exchange strokes at crankcase pressure: the Barnes-Moss correlation used for
# friction already contains the pumping loss, so an explicit pumping loop here would
# count it twice.
EXHAUST_STROKE_PA = 101_325.0
INTAKE_STROKE_PA = 101_325.0


def slider_crank(r: float, rod: float, phi: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Piston displacement from TDC x(phi) and its first/second derivatives w.r.t. phi (exact)."""
    sin, cos = np.sin(phi), np.cos(phi)
    q = np.sqrt(rod**2 - (r * sin) ** 2)
    s = r * cos + q
    ds = -r * sin - r**2 * sin * cos / q
    d2s = -r * cos - r**2 * (cos**2 - sin**2) / q - r**4 * sin**2 * cos**2 / q**3
    return rod + r - s, -ds, -d2s


def reciprocating_mass_kg(spec: EngineSpec) -> float:
    return spec.reciprocating_mass_kg + (1.0 - spec.rod_big_end_fraction) * spec.rod_mass_kg


def pressure_720(cycle: CycleResult, local_deg: np.ndarray) -> np.ndarray:
    """Cylinder pressure over the full 4-stroke cycle; local angle 0 = firing TDC, wrapped to [-360, 360)."""
    a = (np.asarray(local_deg) + 360.0) % 720.0 - 360.0
    p = np.where(a >= 180.0, EXHAUST_STROKE_PA, INTAKE_STROKE_PA)
    closed = (a >= -180.0) & (a < 180.0)
    p = np.where(closed, np.interp(a, cycle.theta_deg, cycle.pressure_pa), p)
    return p


@dataclass
class CrankTorque:
    """Crank torque over one 4-stroke cycle at one speed."""

    rpm: float
    theta_deg: np.ndarray  # 0 .. 720
    per_cylinder_nm: np.ndarray  # (6, N) gas + inertia
    gas_nm: np.ndarray  # total gas torque
    inertia_nm: np.ndarray  # total reciprocating inertia torque
    total_nm: np.ndarray  # gas + inertia
    rod_force_n: np.ndarray  # (6, N), + = compression
    mean_nm: float
    friction_nm: float
    brake_mean_nm: float


def crank_torque(spec: EngineSpec, cycle: CycleResult, n_points: int = 2881) -> CrankTorque:
    """Total crank torque of all cylinders over 720 deg at the cycle's speed."""
    theta = np.linspace(0.0, 720.0, n_points)
    r = spec.crank_radius_mm / 1000.0
    rod = spec.rod_length_mm / 1000.0
    omega = cycle.rpm * 2.0 * math.pi / 60.0
    m_rec = reciprocating_mass_kg(spec)
    area = spec.piston_area_m2
    per_cyl, gas_tot, inert_tot, rod_f = [], np.zeros_like(theta), np.zeros_like(theta), []
    for c in spec.cylinders:
        phi = np.radians(theta + c.pin_angle_deg - c.axis_angle_deg)
        _, dx, d2x = slider_crank(r, rod, phi)
        p = pressure_720(cycle, theta - c.firing_angle_deg)
        f_gas = (p - 101_325.0) * area
        f_in = -m_rec * omega**2 * d2x
        t_gas, t_in = f_gas * dx, f_in * dx
        gas_tot += t_gas
        inert_tot += t_in
        per_cyl.append(t_gas + t_in)
        cos_beta = np.sqrt(1.0 - (r / rod * np.sin(phi)) ** 2)
        rod_f.append((f_gas + f_in) / cos_beta)
    total = gas_tot + inert_tot
    mean = float(np.trapezoid(total, theta) / 720.0)
    friction = cycle.fmep_pa * spec.swept_volume_per_cyl_m3 * spec.n_cylinders / (4.0 * math.pi)
    return CrankTorque(
        rpm=cycle.rpm, theta_deg=theta, per_cylinder_nm=np.array(per_cyl), gas_nm=gas_tot,
        inertia_nm=inert_tot, total_nm=total, rod_force_n=np.array(rod_f), mean_nm=mean,
        friction_nm=friction, brake_mean_nm=mean - friction,
    )


@dataclass
class Balance:
    """Shaking force/moment of the reciprocating masses over one revolution and their orders."""

    theta_deg: np.ndarray
    force_n: np.ndarray  # (N, 2) X, Y
    moment_nm: np.ndarray  # (N, 2) about X, Y
    force_order_n: dict[int, float]  # order -> max magnitude of that harmonic
    moment_order_nm: dict[int, float]
    single_cylinder_primary_n: float  # m r w^2, for scale


def _harmonic_peak(theta_rad: np.ndarray, vec: np.ndarray, order: int) -> float:
    """Peak magnitude of the `order`-th harmonic of a periodic 2-D vector signal over one revolution."""
    n = len(theta_rad)
    c, s = np.cos(order * theta_rad), np.sin(order * theta_rad)
    a = 2.0 / n * vec.T @ c
    b = 2.0 / n * vec.T @ s
    recon = np.outer(c, a) + np.outer(s, b)
    return float(np.max(np.linalg.norm(recon, axis=1)))


def shaking(spec: EngineSpec, rpm: float, cylinders: Sequence[Cylinder] | None = None,
            n_points: int = 720, orders: Sequence[int] = (1, 2, 4, 6)) -> Balance:
    """Reciprocating shaking force and moment (about the crank mid-length) at `rpm`."""
    cyls = list(cylinders or spec.cylinders)
    theta = np.linspace(0.0, 360.0, n_points, endpoint=False)
    th = np.radians(theta)
    r = spec.crank_radius_mm / 1000.0
    rod = spec.rod_length_mm / 1000.0
    omega = rpm * 2.0 * math.pi / 60.0
    m_rec = reciprocating_mass_kg(spec)
    z_mid = 0.5 * (min(c.z_mm for c in cyls) + max(c.z_mm for c in cyls)) / 1000.0
    force = np.zeros((n_points, 2))
    moment = np.zeros((n_points, 2))
    for c in cyls:
        phi = th + math.radians(c.pin_angle_deg - c.axis_angle_deg)
        _, _, d2x = slider_crank(r, rod, phi)
        a = math.radians(c.axis_angle_deg)
        e = np.array([math.sin(a), math.cos(a)])  # crank -> cylinder head
        f = (m_rec * omega**2 * d2x)[:, None] * e[None, :]
        force += f
        dz = c.z_mm / 1000.0 - z_mid
        moment += dz * np.column_stack([-f[:, 1], f[:, 0]])
    return Balance(
        theta_deg=theta, force_n=force, moment_nm=moment,
        force_order_n={k: _harmonic_peak(th, force, k) for k in orders},
        moment_order_nm={k: _harmonic_peak(th, moment, k) for k in orders},
        single_cylinder_primary_n=m_rec * r * omega**2,
    )


def flywheel_inertia_kgm2(torque: CrankTorque, speed_fluctuation: float) -> tuple[float, float]:
    """Flywheel inertia for a coefficient of speed fluctuation Cs = (w_max - w_min)/w_mean.

    Returns (inertia [kg m^2], fluctuating energy dE [J]); I = dE / (Cs w^2).
    """
    th = np.radians(torque.theta_deg)
    excess = torque.total_nm - torque.mean_nm
    energy = np.concatenate([[0.0], np.cumsum(0.5 * (excess[1:] + excess[:-1]) * np.diff(th))])
    d_e = float(energy.max() - energy.min())
    omega = torque.rpm * 2.0 * math.pi / 60.0
    return d_e / (speed_fluctuation * omega**2), d_e


def inline_six_layout(spacing_mm: float = 100.0) -> list[Cylinder]:
    """Reference inline six (pins 0/240/120/120/240/0, firing 1-5-3-6-2-4) for validation."""
    pins = [0.0, 240.0, 120.0, 120.0, 240.0, 0.0]
    return [Cylinder(i + 1, "R", 0.0, pins[i], i * spacing_mm, 0.0) for i in range(6)]
