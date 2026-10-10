"""Joint and detail design, closed form (v0.16): fasteners, flanges, bonding lands, holes and notches.

Every formula here has a matching close-up CalculiX model in
`agents.structures.detail_fe`, so each hand method is checked by FE.

Fasteners (spar flange to cover)
    Shear flow at the web/cover line from beam theory, q = V Q / I with
    Q = (A_cover / 2)(h / 2) (each web collects half the cover). A protruding
    head solid rivet (MS20470AD, 2117-T4, Fsu = 207 MPa) is checked in single
    shear and in bearing in the thinner sheet (Fbru at e/D = 2). Pitch is the
    smallest of: strength pitch P_allow / q_ult, inter-rivet buckling of the
    compression cover (Bruhn C7: sigma_ir = 0.9 c E (t / p)^2, c = 4 for
    universal heads) and 8 D; never below 4 D. Edge distance 2 D sets the
    flange width.

Bonding lands (Volkersen)
    Shear-lag lap joint with adherends E1 t1, E2 t2 (per unit width) and an
    adhesive layer G_a / t_a, overlap L, load P per unit width:
    tau'' = omega^2 tau, omega^2 = (G_a / t_a)(1/(E1 t1) + 1/(E2 t2)).
    Solved exactly (cosh/sinh), peaks at the overlap ends. Adherend bending
    and peel are NOT in Volkersen; the FE close-up shows them.

Holes and notches
    Open hole in a finite-width strip (Heywood): Kt,net = 2 + (1 - d/W)^3.
    Opposite semicircular edge notches (Peterson chart 2.3, net section):
    Kt = 3.065 - 3.472 (2r/D) + 1.009 (2r/D)^2 + 0.405 (2r/D)^3.
    Circular hole in pure shear, infinite plate (Kirsch): sigma_max = 4 tau.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from agents.structures.wing_box import Material

# MS20470AD (2117-T4) solid rivet, protruding universal head
RIVET_FSU_MPA = 207.0
RIVET_DIAMETERS_MM = (1.6, 2.4, 3.2)  # 1/16", 3/32", 1/8" (AD2, AD3, AD4)
INTER_RIVET_C_UNIVERSAL = 4.0
FBRU_ED2_FACTOR = 2.09  # Fbru(e/D = 2) / Ftu for 6061-T6 sheet (88 / 42 ksi, MMPDS order of magnitude)
MIN_PITCH_D, MAX_PITCH_D, EDGE_D = 4.0, 8.0, 2.0

# Two-part structural epoxy paste, room temperature, with an environmental knock-down
ADHESIVE_G_MPA = 700.0
ADHESIVE_T_MM = 0.2
ADHESIVE_TAU_ALLOW_MPA = 20.0


@dataclass
class RivetedLine:
    diameter_mm: float
    pitch_mm: float
    edge_mm: float
    flange_width_mm: float
    q_ult_npmm: float
    rivet_load_n: float
    p_shear_n: float
    p_bearing_n: float
    sigma_ir_mpa: float
    sigma_cover_ult_mpa: float
    governing: str
    margins: dict[str, float]


def rivet_allowables(d_mm: float, t_min_mm: float, mat: Material) -> tuple[float, float]:
    """(single-shear, bearing) allowable loads [N] of one rivet."""
    shear = RIVET_FSU_MPA * math.pi * d_mm**2 / 4
    bearing = FBRU_ED2_FACTOR * mat.ftu_mpa * d_mm * t_min_mm
    return shear, bearing


def inter_rivet_stress_mpa(t_mm: float, pitch_mm: float, mat: Material, c: float = INTER_RIVET_C_UNIVERSAL) -> float:
    return 0.9 * c * mat.youngs_modulus_mpa * (t_mm / pitch_mm) ** 2


def box_shear_flow_npmm(v_n: float, w: float, h: float, a_cover_mm2: float, t_web: float) -> float:
    """Horizontal shear flow at one web/cover line, q = V Q / I."""
    inertia = 2 * a_cover_mm2 * (h / 2) ** 2 + 2 * t_web * h**3 / 12
    q_static = (a_cover_mm2 / 2) * (h / 2)
    return v_n * q_static / inertia


def design_rivet_line(v_ult_n: float, w: float, h: float, a_cover_mm2: float, t_web: float, t_flange: float,
                      t_cover: float, sigma_cover_ult_mpa: float, mat: Material) -> RivetedLine:
    """Smallest rivet and the largest pitch that pass shear, bearing and inter-rivet buckling."""
    q = box_shear_flow_npmm(v_ult_n, w, h, a_cover_mm2, t_web)
    best = None
    for d in RIVET_DIAMETERS_MM:
        if d < 2.0 * max(t_flange, t_cover):  # shop rule: D ~ 2-3 x the thicker sheet (head formation)
            continue
        ps, pb = rivet_allowables(d, min(t_flange, t_cover), mat)
        p_allow = min(ps, pb)
        p_strength = p_allow / max(q, 1e-9)
        p_ir = t_cover * math.sqrt(0.9 * INTER_RIVET_C_UNIVERSAL * mat.youngs_modulus_mpa
                                   / max(sigma_cover_ult_mpa, 1e-9))
        cands = {"rivet strength": p_strength, "inter-rivet buckling": p_ir, "max pitch 8D": MAX_PITCH_D * d}
        gov = min(cands, key=cands.get)
        pitch = math.floor(cands[gov] * 2) / 2  # 0.5 mm drilling-template step
        if pitch < MIN_PITCH_D * d:
            continue
        load = q * pitch
        s_ir = inter_rivet_stress_mpa(t_cover, pitch, mat)
        ms = {"rivet shear": ps / load - 1, "sheet bearing": pb / load - 1,
              "inter-rivet buckling": s_ir / sigma_cover_ult_mpa - 1}
        edge = EDGE_D * d
        best = RivetedLine(d, pitch, edge, 2 * edge + 2 * t_flange, q, load, ps, pb, s_ir, sigma_cover_ult_mpa,
                           gov, ms)
        break
    if best is None:
        raise ValueError("no rivet size satisfies the 4D minimum pitch")
    return best


@dataclass
class BondedLap:
    p_npmm: float  # load per unit width
    overlap_mm: float
    e1t1: float
    e2t2: float
    omega_per_mm: float
    tau_avg_mpa: float
    tau_max_mpa: float
    margin: float


def volkersen(p_npmm: float, overlap_mm: float, e1: float, t1: float, e2: float, t2: float,
              g_a: float = ADHESIVE_G_MPA, t_a: float = ADHESIVE_T_MM, n: int = 201) -> tuple[np.ndarray, np.ndarray]:
    """Adhesive shear tau(x) [MPa] along the overlap, x in [-L/2, L/2]; adherend 1 loaded at x = -L/2."""
    k = g_a / t_a
    a1, a2 = e1 * t1, e2 * t2
    om = math.sqrt(k * (1 / a1 + 1 / a2))
    half = overlap_mm / 2
    a = p_npmm * om / (2 * math.sinh(om * half))
    b = k * p_npmm * (1 / a2 - 1 / a1) / (2 * om * math.cosh(om * half))
    x = np.linspace(-half, half, n)
    return x, a * np.cosh(om * x) + b * np.sinh(om * x)


def design_bond(p_npmm: float, e1: float, t1: float, e2: float, t2: float, overlap_mm: float,
                tau_allow: float = ADHESIVE_TAU_ALLOW_MPA) -> BondedLap:
    _, tau = volkersen(p_npmm, overlap_mm, e1, t1, e2, t2)
    om = math.sqrt(ADHESIVE_G_MPA / ADHESIVE_T_MM * (1 / (e1 * t1) + 1 / (e2 * t2)))
    tmax = float(np.max(np.abs(tau)))
    return BondedLap(p_npmm, overlap_mm, e1 * t1, e2 * t2, om, p_npmm / overlap_mm, tmax, tau_allow / tmax - 1)


def kt_open_hole_heywood(d_over_w: float) -> float:
    """Net-section Kt of a central open hole in a finite strip in tension (Heywood)."""
    return 2 + (1 - d_over_w) ** 3


def kt_double_semicircular_notch(two_r_over_d: float) -> float:
    """Net-section Kt, opposite semicircular edge notches in tension (Peterson chart 2.3)."""
    x = two_r_over_d
    return 3.065 - 3.472 * x + 1.009 * x**2 + 0.405 * x**3


KT_HOLE_PURE_SHEAR = 4.0
