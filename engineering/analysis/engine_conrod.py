"""Connecting-rod shank check: worst-case loads, Johnson-Euler buckling, Goodman fatigue, sizing.

Loads come from the engine model itself (`engine_cycle` + `engine_dynamics`):
* maximum compression: the largest rod force over the full-load map (firing
  pressure minus inertia, at the speed where it peaks);
* maximum tension: the largest tensile rod force at the redline, which occurs
  around gas-exchange TDC where only the reciprocating inertia pulls on the rod.

The shank is an I-section (depth H in the plane of crank rotation, flange width
B, flange and web thicknesses). Buckling uses the Johnson parabola below the
transition slenderness and Euler above it, in two planes:
* in the plane of rotation the rod is pinned at both ends (K = 1);
* out of plane the bearings constrain rotation, treated as fixed-fixed (K = 0.5).
Fatigue uses the Goodman approach for fully reversed-plus-mean axial stress
with a Marin-corrected endurance limit (Shigley's Mechanical Engineering
Design: machined-surface factor ka = 4.51 Su^-0.265 [MPa], axial-load factor
kc = 0.85). With a compressive mean stress the conservative Shigley rule
n = Se / sigma_a is used.

Honest limits: shank only (no big-end/small-end eyes, cap bolts or bearing
pressure), uniform section along the length, no stress concentrations at the
eye transitions, nominal material data for quenched-and-tempered 42CrMo4
(EN 10083-3 class values), no FE.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

import numpy as np
from scipy.optimize import brentq

from agents.powertrain.spec import EngineSpec
from engineering.analysis.engine_cycle import EngineMap, run_cycle_mbt
from engineering.analysis.engine_dynamics import crank_torque


@dataclass(frozen=True)
class RodMaterial:
    name: str = "42CrMo4 +QT (forged)"
    e_mpa: float = 210_000.0
    yield_mpa: float = 750.0
    ultimate_mpa: float = 1000.0
    density_kg_m3: float = 7850.0

    @property
    def endurance_mpa(self) -> float:
        """Marin-corrected axial endurance limit: Se = ka kc 0.5 Su (machined surface, axial load)."""
        ka = 4.51 * self.ultimate_mpa**-0.265
        return ka * 0.85 * 0.5 * self.ultimate_mpa


@dataclass(frozen=True)
class ISection:
    """Shank I-section in mm. H lies in the plane of crank rotation."""

    depth_mm: float = 22.0
    width_mm: float = 16.0
    flange_mm: float = 3.5
    web_mm: float = 4.0

    def __post_init__(self) -> None:
        if min(self.depth_mm, self.width_mm, self.flange_mm, self.web_mm) <= 0:
            raise ValueError("section dimensions must be positive")
        if 2 * self.flange_mm >= self.depth_mm or self.web_mm >= self.width_mm:
            raise ValueError("flanges/web too thick for the section")

    @property
    def area_mm2(self) -> float:
        return 2 * self.width_mm * self.flange_mm + (self.depth_mm - 2 * self.flange_mm) * self.web_mm

    @property
    def i_in_plane_mm4(self) -> float:
        """Second moment for bending in the plane of rotation (about the axis parallel to the pins)."""
        h, b, tf, tw = self.depth_mm, self.width_mm, self.flange_mm, self.web_mm
        return b * h**3 / 12.0 - (b - tw) * (h - 2 * tf) ** 3 / 12.0

    @property
    def i_out_of_plane_mm4(self) -> float:
        h, b, tf, tw = self.depth_mm, self.width_mm, self.flange_mm, self.web_mm
        return 2 * tf * b**3 / 12.0 + (h - 2 * tf) * tw**3 / 12.0

    def scaled(self, k: float) -> ISection:
        return replace(self, depth_mm=self.depth_mm * k, width_mm=self.width_mm * k,
                       flange_mm=self.flange_mm * k, web_mm=self.web_mm * k)


def critical_stress_mpa(slenderness: float, mat: RodMaterial) -> float:
    """Johnson parabola below the transition slenderness, Euler above."""
    transition = math.sqrt(2.0 * math.pi**2 * mat.e_mpa / mat.yield_mpa)
    if slenderness < transition:
        return mat.yield_mpa - (mat.yield_mpa * slenderness / (2.0 * math.pi)) ** 2 / mat.e_mpa
    return math.pi**2 * mat.e_mpa / slenderness**2


@dataclass
class RodLoads:
    compression_n: float
    compression_rpm: float
    tension_n: float
    tension_rpm: float


def worst_case_rod_loads(spec: EngineSpec, engine_map: EngineMap, redline_rpm: float) -> RodLoads:
    """Peak compressive rod force over the full-load map and peak tension at the redline."""
    comp, comp_rpm = 0.0, 0.0
    for rpm in engine_map.rpm:
        f = crank_torque(spec, run_cycle_mbt(spec, float(rpm))).rod_force_n
        if f.max() > comp:
            comp, comp_rpm = float(f.max()), float(rpm)
    f_red = crank_torque(spec, run_cycle_mbt(spec, redline_rpm)).rod_force_n
    return RodLoads(compression_n=comp, compression_rpm=comp_rpm, tension_n=float(-f_red.min()),
                    tension_rpm=float(redline_rpm))


@dataclass
class RodCheck:
    section: ISection
    loads: RodLoads
    stress_compression_mpa: float
    stress_tension_mpa: float
    buckling_sf_in_plane: float
    buckling_sf_out_of_plane: float
    fatigue_sf: float
    yield_sf: float
    shank_mass_kg: float

    @property
    def buckling_sf(self) -> float:
        return min(self.buckling_sf_in_plane, self.buckling_sf_out_of_plane)


def check_rod(spec: EngineSpec, section: ISection, loads: RodLoads, mat: RodMaterial | None = None) -> RodCheck:
    m = mat or RodMaterial()
    area = section.area_mm2
    length = spec.rod_length_mm
    rho_in = math.sqrt(section.i_in_plane_mm4 / area)
    rho_out = math.sqrt(section.i_out_of_plane_mm4 / area)
    sig_c = loads.compression_n / area
    sig_t = loads.tension_n / area
    sf_in = critical_stress_mpa(1.0 * length / rho_in, m) / sig_c
    sf_out = critical_stress_mpa(0.5 * length / rho_out, m) / sig_c
    sigma_a = 0.5 * (sig_t + sig_c)  # half the stress range (tension positive, compression negative)
    sigma_m = 0.5 * (sig_t - sig_c)
    if sigma_m >= 0:
        fatigue = 1.0 / (sigma_a / m.endurance_mpa + sigma_m / m.ultimate_mpa)
    else:
        fatigue = m.endurance_mpa / sigma_a
    return RodCheck(
        section=section, loads=loads, stress_compression_mpa=sig_c, stress_tension_mpa=sig_t,
        buckling_sf_in_plane=sf_in, buckling_sf_out_of_plane=sf_out, fatigue_sf=fatigue,
        yield_sf=m.yield_mpa / max(sig_c, sig_t),
        shank_mass_kg=area * 1e-6 * (length * 1e-3) * m.density_kg_m3,
    )


def size_rod(spec: EngineSpec, base: ISection, loads: RodLoads, min_fatigue_sf: float = 1.5,
             min_buckling_sf: float = 3.0, mat: RodMaterial | None = None) -> tuple[RodCheck, float]:
    """Smallest uniform scale of `base` meeting both safety-factor targets (returns check, scale)."""
    def margin(k: float) -> float:
        c = check_rod(spec, base.scaled(k), loads, mat)
        return min(c.fatigue_sf / min_fatigue_sf, c.buckling_sf / min_buckling_sf) - 1.0

    lo, hi = 0.3, 3.0
    if margin(hi) < 0:
        raise ValueError("even a 3x scaled section cannot meet the targets")
    k = brentq(margin, lo, hi, xtol=1e-4) if margin(lo) < 0 else lo
    k = float(np.nextafter(k, np.inf))
    return check_rod(spec, base.scaled(k), loads, mat), k
