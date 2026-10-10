"""Single-zone crank-angle cycle model of a spark-ignition engine (one cylinder, scaled to N).

For each engine speed the closed part of the cycle is integrated from bottom
dead centre (BDC, taken as inlet valve closing) to the next BDC (taken as
exhaust valve opening) in crank angle:

    V(theta)      exact slider-crank volume (agents/powertrain/spec.py geometry)
    x_b(theta)    Wiebe burned-mass fraction, x_b = 1 - exp(-a ((theta - theta_0)/dtheta)^(m+1))
    dp/dtheta     = ((gamma - 1) dQ/dtheta - gamma p dV/dtheta) / V        (first law, ideal gas)

Trapped mass comes from a volumetric-efficiency curve, the heat release from the
trapped fuel (stoichiometric gasoline). Spark timing can be optimised per speed
for maximum work (MBT). Gross indicated work -> IMEP; friction + pumping from
the Barnes-Moss correlation for SI engines at full load (as given in Heywood,
*Internal Combustion Engine Fundamentals*, 1988) -> BMEP -> torque and power.

Validation hooks: with instantaneous heat release and constant gamma the model
must reproduce the ideal Otto efficiency 1 - r^(1-gamma) (tests/powertrain).

Honest simplifications: single zone, one effective gamma (1.30) that lumps
real-gas and wall heat-loss effects instead of a heat-transfer model, no gas
exchange simulation (IVC/EVO at BDC, pumping inside the friction correlation),
no knock model (MBT timing is assumed achievable), a placeholder volumetric-
efficiency curve for a naturally aspirated 4-valve engine.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize_scalar

from agents.powertrain.spec import EngineSpec

R_AIR = 287.0  # J/(kg K)
LHV_GASOLINE = 43.4e6  # J/kg
AFR_STOICH = 14.7


class EngineCycleError(ValueError):
    """Raised for invalid cycle inputs."""


@dataclass(frozen=True)
class CycleSettings:
    """Operating assumptions (all documented placeholders unless stated)."""

    gamma: float | None = None  # None -> temperature-dependent gamma(T) (Gatowski fit); a number -> constant
    heat_transfer: bool = True  # Woschni wall heat transfer
    t_wall_k: float = 450.0
    p_ambient_pa: float = 101_325.0
    t_ambient_k: float = 298.0
    t_ivc_k: float = 340.0  # charge temperature at inlet valve closing (wall + residual heating)
    combustion_efficiency: float = 0.95
    lambda_: float = 1.0
    wiebe_a: float = 5.0
    wiebe_m: float = 2.0
    burn_duration_deg: float = 55.0
    dtheta_deg: float = 0.25
    crankcase_pressure_pa: float = 101_325.0


def volumetric_efficiency(rpm: float) -> float:
    """Placeholder full-load volumetric efficiency of a naturally aspirated 4-valve engine.

    Peaks at 0.93 around 4800 rpm, falls to ~0.80 at 1000 rpm and ~0.86 at 7000 rpm.
    """
    x = (rpm - 4800.0) / 3800.0
    return float(np.clip(0.93 - 0.13 * x * x, 0.6, 0.95))


def barnes_moss_fmep_pa(rpm: float) -> float:
    """Friction + pumping MEP of an SI engine at wide-open throttle (Barnes-Moss correlation).

    fmep [bar] = 0.97 + 0.15 (N/1000) + 0.05 (N/1000)^2
    """
    n = rpm / 1000.0
    return (0.97 + 0.15 * n + 0.05 * n * n) * 1e5


def gamma_of_t(t_k: float) -> float:
    """Ratio of specific heats of the cylinder charge vs temperature (Gatowski et al. 1984 linear fit)."""
    return 1.392 - 8.13e-5 * t_k


def woschni_heat_loss_j(p: float, t_gas: float, p_motored: float, vol: float, theta_deg: float, bore: float,
                        s_p: float, x_tdc: float, spec: EngineSpec, p_ref: float, v_ref: float, t_ref: float,
                        t_wall: float, dt: float) -> float:
    """Heat lost to the walls in one step [J] with Woschni's correlation (SI units, Heywood form).

    h = 3.26 B^-0.2 p_kPa^0.8 T^-0.55 w^0.8,  w = C1 Sp + C2 (Vd T_r / (p_r V_r)) (p - p_motored)
    C1 = 2.28, C2 = 3.24e-3 m/(s K) from combustion onwards (0 before). Area = head + piston + liner.
    """
    c2 = 3.24e-3 if theta_deg > -40.0 else 0.0
    w = 2.28 * s_p + c2 * (spec.swept_volume_per_cyl_m3 * t_ref / (p_ref * v_ref)) * max(p - p_motored, 0.0)
    h = 3.26 * bore**-0.2 * (p / 1000.0) ** 0.8 * t_gas**-0.55 * w**0.8
    height = vol / spec.piston_area_m2  # instantaneous gas column height
    area = 2.0 * spec.piston_area_m2 + math.pi * bore * height
    return h * area * (t_gas - t_wall) * dt


def cylinder_volume_m3(spec: EngineSpec, phi_rad: np.ndarray) -> np.ndarray:
    """Exact slider-crank volume; phi = 0 at TDC."""
    r = spec.crank_radius_mm / 1000.0
    rod = spec.rod_length_mm / 1000.0
    s = r * np.cos(phi_rad) + np.sqrt(rod**2 - (r * np.sin(phi_rad)) ** 2)
    return spec.clearance_volume_m3 + spec.piston_area_m2 * (rod + r - s)


@dataclass
class CycleResult:
    """One closed cycle (BDC -> TDC -> BDC) at one speed."""

    rpm: float
    theta_deg: np.ndarray  # -180 .. +180, 0 = firing TDC
    volume_m3: np.ndarray
    pressure_pa: np.ndarray
    burned_fraction: np.ndarray
    spark_deg: float  # combustion start (Wiebe theta_0), deg relative to TDC
    heat_released_j: float
    work_j: float  # gross indicated work per cylinder per cycle
    imep_pa: float
    fmep_pa: float
    bmep_pa: float
    p_max_pa: float
    theta_p_max_deg: float
    indicated_efficiency: float
    torque_nm: float  # whole engine
    power_kw: float  # whole engine
    trapped_air_kg: float
    wall_heat_loss_j: float = 0.0


def run_cycle(
    spec: EngineSpec,
    rpm: float,
    spark_deg: float = -20.0,
    settings: CycleSettings | None = None,
    instantaneous_combustion: bool = False,
) -> CycleResult:
    """Integrate one closed cycle at `rpm` with combustion starting at `spark_deg` (negative = BTDC)."""
    st = settings or CycleSettings()
    if rpm <= 0:
        raise EngineCycleError("rpm must be positive")
    if st.gamma is not None and st.gamma <= 1.0:
        raise EngineCycleError("gamma must be > 1")

    theta = np.arange(-180.0, 180.0 + 1e-9, st.dtheta_deg)
    phi = np.radians(theta)
    vol = cylinder_volume_m3(spec, phi)

    rho_amb = st.p_ambient_pa / (R_AIR * st.t_ambient_k)
    m_air = volumetric_efficiency(rpm) * rho_amb * spec.swept_volume_per_cyl_m3
    q_total = m_air / (AFR_STOICH * st.lambda_) * LHV_GASOLINE * st.combustion_efficiency
    p0 = m_air * R_AIR * st.t_ivc_k / vol[0]

    if instantaneous_combustion:
        xb = (theta >= spark_deg).astype(float)
    else:
        u = np.clip((theta - spark_deg) / st.burn_duration_deg, 0.0, None)
        xb = 1.0 - np.exp(-st.wiebe_a * u ** (st.wiebe_m + 1.0))

    m_charge = m_air * (1.0 + 1.0 / (AFR_STOICH * st.lambda_))
    omega = rpm * 2.0 * math.pi / 60.0
    dt = math.radians(st.dtheta_deg) / omega
    bore = spec.bore_mm / 1000.0
    s_p = 2.0 * spec.stroke_mm / 1000.0 * rpm / 60.0  # mean piston speed
    x_tdc = spec.clearance_volume_m3 / spec.piston_area_m2  # equivalent clearance height
    p = np.empty_like(theta)
    p[0] = p0
    q_wall = 0.0
    p_motored = p0
    for i in range(1, len(theta)):
        t_gas = p[i - 1] * vol[i - 1] / (m_charge * R_AIR)
        g = st.gamma if st.gamma is not None else gamma_of_t(t_gas)
        # exact step: adiabatic volume change, then heat addition/loss at the new volume
        p_ad = p[i - 1] * (vol[i - 1] / vol[i]) ** g
        p_motored = p_motored * (vol[i - 1] / vol[i]) ** g
        dq = q_total * (xb[i] - xb[i - 1])
        if st.heat_transfer:
            dq_w = woschni_heat_loss_j(p[i - 1], t_gas, p_motored, vol[i - 1], theta[i], bore, s_p, x_tdc,
                                       spec, p0, vol[0], st.t_ivc_k, st.t_wall_k, dt)
            q_wall += dq_w
            dq -= dq_w
        p[i] = p_ad + (g - 1.0) * dq / vol[i]

    work = float(np.trapezoid(p, vol))
    imep = work / spec.swept_volume_per_cyl_m3
    fmep = barnes_moss_fmep_pa(rpm)
    bmep = imep - fmep
    torque = bmep * spec.swept_volume_per_cyl_m3 * spec.n_cylinders / (4.0 * math.pi)
    power = torque * rpm * 2.0 * math.pi / 60.0 / 1000.0
    i_max = int(np.argmax(p))
    return CycleResult(
        rpm=float(rpm), theta_deg=theta, volume_m3=vol, pressure_pa=p, burned_fraction=xb,
        spark_deg=float(spark_deg), heat_released_j=q_total, work_j=work, imep_pa=imep, fmep_pa=fmep,
        bmep_pa=bmep, p_max_pa=float(p[i_max]), theta_p_max_deg=float(theta[i_max]),
        indicated_efficiency=work / q_total, torque_nm=torque, power_kw=power, trapped_air_kg=m_air,
        wall_heat_loss_j=q_wall,
    )


def run_cycle_mbt(spec: EngineSpec, rpm: float, settings: CycleSettings | None = None) -> CycleResult:
    """Cycle at maximum-brake-torque spark timing (combustion start optimised for work)."""
    res = minimize_scalar(lambda s: -run_cycle(spec, rpm, s, settings).work_j,
                          bounds=(-60.0, 10.0), method="bounded", options={"xatol": 0.1})
    return run_cycle(spec, rpm, float(res.x), settings)


@dataclass
class EngineMap:
    """Full-load performance across speed."""

    rpm: np.ndarray
    torque_nm: np.ndarray
    power_kw: np.ndarray
    imep_bar: np.ndarray
    bmep_bar: np.ndarray
    fmep_bar: np.ndarray
    p_max_bar: np.ndarray
    spark_deg: np.ndarray
    theta_p_max_deg: np.ndarray
    indicated_efficiency: np.ndarray

    @property
    def peak_torque(self) -> tuple[float, float]:
        i = int(np.argmax(self.torque_nm))
        return float(self.torque_nm[i]), float(self.rpm[i])

    @property
    def peak_power(self) -> tuple[float, float]:
        i = int(np.argmax(self.power_kw))
        return float(self.power_kw[i]), float(self.rpm[i])


def full_load_map(spec: EngineSpec, rpms: np.ndarray | None = None,
                  settings: CycleSettings | None = None) -> EngineMap:
    """Full-load torque/power curve with MBT spark at every speed."""
    rpms = np.arange(1000.0, 7001.0, 500.0) if rpms is None else np.asarray(rpms, float)
    cycles = [run_cycle_mbt(spec, n, settings) for n in rpms]

    def arr(f):
        return np.array([f(c) for c in cycles])

    return EngineMap(
        rpm=rpms, torque_nm=arr(lambda c: c.torque_nm), power_kw=arr(lambda c: c.power_kw),
        imep_bar=arr(lambda c: c.imep_pa / 1e5), bmep_bar=arr(lambda c: c.bmep_pa / 1e5),
        fmep_bar=arr(lambda c: c.fmep_pa / 1e5), p_max_bar=arr(lambda c: c.p_max_pa / 1e5),
        spark_deg=arr(lambda c: c.spark_deg), theta_p_max_deg=arr(lambda c: c.theta_p_max_deg),
        indicated_efficiency=arr(lambda c: c.indicated_efficiency),
    )


def otto_efficiency(compression_ratio: float, gamma: float) -> float:
    """Ideal air-standard Otto cycle efficiency."""
    return 1.0 - compression_ratio ** (1.0 - gamma)
