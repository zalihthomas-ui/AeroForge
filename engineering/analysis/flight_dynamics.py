"""Flight dynamics of the v0.15 aircraft: mass properties, power-on trim, dynamic modes, control authority.

Pipeline
--------
1. Mass properties from the labelled CAD assembly: every solid gets the mass of its component (group masses
   from the mass & balance, spread over that group's solids by volume), its own inertia tensor
   (`matrix_of_inertia` x density) and the parallel-axis shift to the aircraft CG; servos and wiring are point
   masses. -> m, CG, Ixx, Iyy, Izz, Ixz.
2. Downwash at the tail measured in the vortex-lattice flow field (induced velocity at the stabiliser
   quarter-chord line), eps(alpha) and d eps / d alpha, cross-checked with the classic 2 CL_alpha / (pi AR).
3. Power-on trim at cruise: unknowns (alpha, delta_e, T) with T = D (AeroBuildup drag), L + T sin(alpha) = W,
   Cm = 0 including the thrust-line moment and the slipstream-scaled stabiliser contribution
   (`engineering/analysis/propulsion.py`).
4. Stability derivatives: VLM (wing + tails, p/q/r rates), the stabiliser and fin contributions scaled by
   eta_h (fuselage wake + slipstream) and eta_v (1 + d sigma / d beta) (DATCOM / Nelson eq. 2.47); fuselage
   increments from AeroBuildup (with minus without fuselage); propeller normal-force contributions; downwash
   lag terms Cm_alphadot, CL_alphadot from d eps / d alpha. Control derivatives from AeroBuildup (+/-2 deg).
5. Small-perturbation equations in stability axes (Nelson, *Flight Stability and Automatic Control*, ch. 4-5;
   Etkin & Reid): longitudinal [u, w, q, theta], lateral [beta, p, r, phi] with Ixz (primed derivatives),
   constant-power propeller (dT/du = -T/u0). Eigenvalues -> short period, phugoid, roll, spiral, Dutch roll,
   checked against MIL-F-8785C Class I, Category B, Level 1.
6. Control authority: elevator trim range over speed and CG envelope incl. trim at CL_max at the forward CG,
   aileron roll performance (pb/2V, time to 30 deg bank), rudder crosswind capability.

Limits: linear, quasi-steady, rigid aircraft; derivatives from potential flow + empirical increments;
propeller normal-force and slipstream models are first-order estimates (see propulsion.py).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import fsolve

from cad.exporters import world_shape
from engineering.analysis.aircraft_layout import (
    AircraftDesign,
    _asb_airplane,
    build_aircraft_assembly,
    wing_mac,
)
from engineering.analysis.propulsion import (
    Propeller,
    actuator_disk,
    immersed_fraction,
    prop_normal_force_cma,
    tail_efficiency,
    thrust_moment_coefficient,
)

G = 9.81
RHO = 1.225

# MIL-F-8785C, Class I (small light airplanes), Category B (cruise), Level 1
MIL_LEVEL1 = {
    "short_period_damping": (0.30, 2.00),
    "phugoid_damping_min": 0.04,
    "dutch_roll_damping_min": 0.08,
    "dutch_roll_zeta_omega_min": 0.15,
    "dutch_roll_omega_min": 0.4,
    "roll_time_constant_max_s": 1.4,
    "spiral_time_to_double_min_s": 20.0,
}


@dataclass
class MassProperties:
    mass_kg: float
    cg_m: np.ndarray  # (x aft, y, z up) from the nose
    inertia_kgm2: np.ndarray  # about the CG, body axes (x aft, y right, z up); Ixz sign unchanged in stability axes

    @property
    def ixx(self) -> float:
        return float(self.inertia_kgm2[0, 0])

    @property
    def iyy(self) -> float:
        return float(self.inertia_kgm2[1, 1])

    @property
    def izz(self) -> float:
        return float(self.inertia_kgm2[2, 2])

    @property
    def ixz(self) -> float:
        return float(-self.inertia_kgm2[0, 2])  # product of inertia Ixz = sum m x z


def mass_properties(design: AircraftDesign, structure) -> MassProperties:
    """CG and inertia tensor of the whole aircraft from its CAD solids + component masses."""
    ac = build_aircraft_assembly(design, structure)
    items = {i.name: i for i in design.mass_items}
    from agents.geometry.wing_structure import GROUP_LABELS

    wing_density = structure.densities
    sub_key = {v: k for k, v in GROUP_LABELS.items()}
    tails = design.tail_structure
    groups: dict[str, list] = {}

    def walk(shape, path):
        kids = list(getattr(shape, "children", ()) or ())
        if kids:
            for k in kids:
                walk(k, [*path, shape.label])
            return
        groups.setdefault(_mass_group(path, shape.label, tails is not None), []).append(world_shape(shape))

    walk(ac, [])
    masses, solids = [], []
    for key, shapes in groups.items():
        vols = np.array([float(s.volume) for s in shapes])
        if key.startswith("wing:"):
            dens = wing_density[sub_key[key.split(":", 1)[1]]]
            ms = vols * 1e-9 * dens
        elif key.startswith(("htail:", "vtail:")):
            surf = tails.htail if key.startswith("htail:") else tails.vtail
            sub = key.split(":", 1)[1].removeprefix("Fin")
            if sub in sub_key:  # built-up structure group: its own density
                ms = vols * 1e-9 * surf.structure.densities[sub_key[sub]]
            else:  # elevator / rudder (foam + glass): one surface's mass spread by volume
                ms = surf.control_surface_mass_kg * vols / vols.sum()
        else:
            total = {"fuselage_skin": items["Fuselage skin"].mass_kg, "formers": items["Formers"].mass_kg,
                     "htail": items["Horizontal tail"].mass_kg, "vtail": items["Vertical tail"].mass_kg}.get(key)
            if total is None:  # systems: CAD label is the item name without spaces
                by_label = {n.replace(" ", ""): it for n, it in items.items()}
                total = by_label[key.split(":", 1)[1]].mass_kg
            ms = total * vols / vols.sum()
        for sh, mi, vi in zip(shapes, ms, vols):
            masses.append(mi)
            solids.append((sh, mi, vi))
    pts = [(items[n].mass_kg, np.array([items[n].x_mm, 0.0, items[n].z_mm]) * 1e-3)
           for n in ("Servos", "Wiring & misc")]
    m_tot = sum(masses) + sum(p[0] for p in pts)
    mx = sum(mi * np.array(tuple(sh.center())) * 1e-3 for sh, mi, _ in solids) + sum(p[0] * p[1] for p in pts)
    cg = mx / m_tot
    inertia = np.zeros((3, 3))
    for sh, mi, vi in solids:
        i_c = np.array(sh.matrix_of_inertia) * 1e-15 * (mi / (vi * 1e-9))  # mm^5 -> m^5 times density
        r = np.array(tuple(sh.center())) * 1e-3 - cg
        inertia += i_c + mi * (np.dot(r, r) * np.eye(3) - np.outer(r, r))
    for mi, p in pts:
        r = p - cg
        inertia += mi * (np.dot(r, r) * np.eye(3) - np.outer(r, r))
    return MassProperties(m_tot, cg, inertia)


def _mass_group(path, label, built_up_tails: bool = False):
    if "Wing" in path:
        sub = path[path.index("Wing") + 1] if len(path) > path.index("Wing") + 1 else label
        return f"wing:{sub}"
    if "Fuselage" in path:
        return "formers" if label.startswith("Former") else "fuselage_skin"
    for name, key in (("HorizontalTail", "htail"), ("VerticalTail", "vtail")):
        if name in path:
            if not built_up_tails:
                return key
            i = path.index(name)
            return f"{key}:{path[i + 1] if len(path) > i + 1 else label}"
    return f"system:{label}"


# ---------------------------------------------------------------- aerodynamics helpers

def _ap(d: AircraftDesign, x_ref_mm: float, **kw):
    kw.setdefault("dihedral_deg", d.dihedral_deg)
    return _asb_airplane(d.campaign, d.wing_x_le_mm, d.wing_z_mm, d.tail, d.stations, x_ref_mm, **kw)


def downwash_at_tail(d: AircraftDesign, x_ref_mm: float, v: float, alphas=(0.0, 2.0, 4.0, 6.0)):
    """Mean downwash angle [rad] along the stabiliser quarter-chord line from the VLM flow field (wing only)."""
    import aerosandbox as asb

    ht = d.tail.htail
    z_t = d.stations[-1].z_center_mm * 1e-3
    ys = np.linspace(0.05, 0.95, 7) * ht.span_mm * 1e-3
    xq = (d.tail.x_htail_le_mm + 0.25 * ht.root_chord_mm) * 1e-3
    pts = np.column_stack([np.full_like(ys, xq), ys, np.full_like(ys, z_t)])
    eps = []
    for al in alphas:
        ap = _ap(d, x_ref_mm, include_htail=False, include_vtail=False, with_fuselage=False)
        vlm = asb.VortexLatticeMethod(ap, asb.OperatingPoint(velocity=v, alpha=al))
        vlm.run()
        w = np.asarray(vlm.get_induced_velocity_at_points(pts))
        # downwash = induced velocity component normal to the freestream, pointing down
        a = math.radians(al)
        n = np.array([-math.sin(a), 0.0, math.cos(a)])
        eps.append(float(np.mean(-(w @ n)) / v))
    eps = np.array(eps)
    slope = float(np.polyfit(np.radians(alphas), eps, 1)[0])
    return np.array(alphas), eps, slope


@dataclass
class TrimPoint:
    velocity_mps: float
    alpha_deg: float
    elevator_deg: float
    thrust_n: float
    cl: float
    cd: float
    eta_h: float
    immersed_fraction: float
    cm_thrust: float
    shaft_power_w: float
    prop_efficiency: float
    slipstream_velocity_mps: float
    slipstream_radius_m: float


def trim_power_on(d: AircraftDesign, mp: MassProperties, prop: Propeller, v: float, eps0: float, deps: float,
                  x_cg_mm: float | None = None, z_cg_m: float | None = None, power: bool = True) -> TrimPoint:
    """Solve alpha, elevator with thrust = drag, slipstream on the stabiliser and the thrust-line moment."""
    import aerosandbox as asb

    x_cg = mp.cg_m[0] * 1e3 if x_cg_mm is None else x_cg_mm
    z_cg = mp.cg_m[2] if z_cg_m is None else z_cg_m
    a = d.campaign.aero
    s = a.lifting_line.area_m2
    mac, _ = wing_mac(a.root_chord_mm, a.tip_chord_mm, d.campaign.requirement.span_mm / 2)
    c = mac * 1e-3
    q = 0.5 * RHO * v**2
    w = mp.mass_kg * G
    ht = d.tail.htail
    x_t = (d.tail.x_htail_le_mm + 0.25 * ht.root_chord_mm) * 1e-3
    z_t = d.stations[-1].z_center_mm * 1e-3
    state = {}

    def coeffs(al, de, with_h=True):
        ap = _ap(d, x_cg, elevator_deg=de, include_htail=with_h)
        r = asb.AeroBuildup(ap, asb.OperatingPoint(velocity=v, alpha=al)).run()
        return float(np.ravel(r["CL"])[0]), float(np.ravel(r["CD"])[0]), float(np.ravel(r["Cm"])[0])

    def residual(x):
        al, de, thr = x
        cl_f, cd_f, cm_f = coeffs(al, de)
        cl_0, cd_0, cm_0 = coeffs(al, de, with_h=False)
        if power and thr > 0:
            ps = actuator_disk(prop, thr, v)
            eps = eps0 + deps * math.radians(al)
            # slipstream centreline: along the flow direction behind the disk (body angle alpha - eps)
            z_s = prop.z_m - math.tan(math.radians(al) - eps) * (x_t - prop.x_m)
            frac = immersed_fraction(ps.slipstream_radius_m, z_t - z_s, ht.span_mm * 1e-3, ht.root_chord_mm * 1e-3,
                                     ht.tip_chord_mm * 1e-3)
            eta = tail_efficiency(ps, frac) / 0.90  # AeroBuildup already reflects a power-off tail; scale ratio
            cm_t = thrust_moment_coefficient(thr, z_cg, prop.z_m, q, s, c)
        else:
            ps, frac, eta, cm_t = None, 0.0, 1.0, 0.0
        cl = cl_0 + eta * (cl_f - cl_0)
        cd = cd_0 + eta * (cd_f - cd_0)
        cm = cm_0 + eta * (cm_f - cm_0) + cm_t
        state.update(cl=cl, cd=cd, eta=eta * 0.90, frac=frac, cm_t=cm_t, ps=ps)
        lift = cl * q * s + thr * math.sin(math.radians(al))
        drag = cd * q * s
        return [(lift - w) / w, cm, ((thr - drag) / w) if power else thr]

    sol = fsolve(residual, [3.0, -2.0, 6.0 if power else 0.0], xtol=1e-8)
    residual(sol)
    ps = state["ps"]
    return TrimPoint(v, float(sol[0]), float(sol[1]), float(sol[2]), state["cl"], state["cd"], state["eta"],
                     state["frac"], state["cm_t"], ps.shaft_power_w if ps else 0.0, ps.efficiency if ps else 0.0,
                     ps.slipstream_velocity_mps if ps else v, ps.slipstream_radius_m if ps else 0.0)


def _vlm_derivs(d, x_cg_mm, v, al, **kw):
    import aerosandbox as asb

    r = asb.VortexLatticeMethod(_ap(d, x_cg_mm, with_fuselage=False, **kw),
                                asb.OperatingPoint(velocity=v, alpha=al)).run_with_stability_derivatives()
    return {k: float(np.ravel(val)[0]) for k, val in r.items() if isinstance(val, (float, int, np.floating, np.ndarray))}


def _ab_derivs(d, x_cg_mm, v, al, with_fuselage=True):
    import aerosandbox as asb

    r = asb.AeroBuildup(_ap(d, x_cg_mm, with_fuselage=with_fuselage),
                        asb.OperatingPoint(velocity=v, alpha=al)).run_with_stability_derivatives(
        alpha=True, beta=True, p=False, q=False, r=False)
    return {k: float(np.ravel(val)[0]) for k, val in r.items() if k in
            ("CL", "CD", "Cm", "CLa", "CDa", "Cma", "CYb", "Clb", "Cnb")}


def _control_derivs(d, x_cg_mm, v, al, de0):
    import aerosandbox as asb

    def run(**kw):
        r = asb.AeroBuildup(_ap(d, x_cg_mm, **kw), asb.OperatingPoint(velocity=v, alpha=al)).run()
        return {k: float(np.ravel(r[k])[0]) for k in ("CL", "CD", "CY", "Cl", "Cm", "Cn")}

    h = 2.0
    out = {}
    for name, key in (("e", "elevator_deg"), ("a", "aileron_deg"), ("r", "rudder_deg")):
        base = de0 if name == "e" else 0.0
        p, m = run(**{key: base + h}), run(**{key: base - h})
        for c in ("CL", "CD", "CY", "Cl", "Cm", "Cn"):
            out[f"{c}d{name}"] = (p[c] - m[c]) / math.radians(2 * h)
    return out


@dataclass
class Mode:
    name: str
    eigenvalue: complex
    omega_n: float
    zeta: float
    time_constant_s: float | None = None
    time_to_double_s: float | None = None
    period_s: float | None = None


@dataclass
class FlightDynamicsResult:
    mass: MassProperties
    trim: TrimPoint
    trim_power_off: TrimPoint
    downwash_alphas_deg: np.ndarray
    downwash_eps_rad: np.ndarray
    deps_dalpha: float
    deps_dalpha_empirical: float
    derivatives: dict
    a_long: np.ndarray
    b_long: np.ndarray
    a_lat: np.ndarray
    b_lat: np.ndarray
    modes: dict[str, Mode]
    criteria: dict[str, tuple[float, str, bool]]
    approximations: dict[str, float]
    static_margin_power_on: float
    neutral_point_power_on_mm: float
    extras: dict = field(default_factory=dict)


def analyze_flight_dynamics(d: AircraftDesign, structure, prop: Propeller | None = None,
                            mass: MassProperties | None = None) -> FlightDynamicsResult:
    prop = prop or Propeller()
    v = d.campaign.requirement.cruise_velocity_mps
    a = d.campaign.aero
    s = a.lifting_line.area_m2
    b = d.campaign.requirement.span_mm * 1e-3
    mac, _ = wing_mac(a.root_chord_mm, a.tip_chord_mm, b * 500.0)
    c = mac * 1e-3
    mp = mass or mass_properties(d, structure)
    x_cg_mm = mp.cg_m[0] * 1e3
    q = 0.5 * RHO * v**2

    alphas, eps, deps = downwash_at_tail(d, x_cg_mm, v)
    eps0 = float(np.interp(0.0, alphas, eps))
    cla_wing = a.lifting_line.cl_alpha_per_rad
    deps_emp = 2.0 * cla_wing / (math.pi * a.aspect_ratio)

    trim = trim_power_on(d, mp, prop, v, eps0, deps)
    trim_off = trim_power_on(d, mp, prop, v, eps0, deps, power=False)
    al, de = trim.alpha_deg, trim.elevator_deg
    ps = actuator_disk(prop, trim.thrust_n, v)

    # --- derivatives: VLM configurations for tail scaling
    full = _vlm_derivs(d, x_cg_mm, v, al)
    no_h = _vlm_derivs(d, x_cg_mm, v, al, include_htail=False)
    no_v = _vlm_derivs(d, x_cg_mm, v, al, include_vtail=False)
    eta_h = trim.eta_h
    vt = d.tail.vtail
    sv = vt.area_mm2 * 1e-6
    z_w_over_d = (d.wing_z_mm - 0.0) / d.stations[2].height_mm
    eta_v_sig = 0.724 + 3.06 * (sv / s) / 2.0 + 0.4 * z_w_over_d + 0.009 * a.aspect_ratio  # DATCOM (Nelson 2.47)

    def scaled(key, eta_h_k=eta_h, eta_v_k=eta_v_sig):
        return (full[key] + (eta_h_k - 1.0) * (full[key] - no_h[key]) + (eta_v_k - 1.0) * (full[key] - no_v[key]))

    ab_f = _ab_derivs(d, x_cg_mm, v, al, True)
    ab_n = _ab_derivs(d, x_cg_mm, v, al, False)
    D = {k: scaled(k) for k in ("CLa", "Cma", "CLq", "Cmq", "CYb", "Clb", "Cnb", "CYp", "Clp", "Cnp", "CYr", "Clr",
                                 "Cnr")}
    for k in ("CLa", "Cma", "CYb", "Clb", "Cnb"):
        D[k] += ab_f[k] - ab_n[k]  # fuselage increments
    # wing-body dihedral effect of a high wing (DATCOM; Nelson eq. 3.x): AeroBuildup's fuselage model has none.
    # dCl_beta [/deg] = 1.2 sqrt(AR) / 57.3 (z_w / b) (2 d / b) -> per rad 1.2 sqrt(AR) (z_w / b) (2 d / b);
    # z_w = wing root height below the body centreline (negative for a high wing -> stabilising)
    d_body = 0.5 * (d.stations[2].width_mm + d.stations[2].height_mm) * 1e-3
    z_w = -(d.wing_z_mm * 1e-3)
    D["Clb_wing_body"] = 1.2 * math.sqrt(a.aspect_ratio) * (z_w / b) * (2 * d_body / b)
    D["Clb"] += D["Clb_wing_body"]
    cma_prop = prop_normal_force_cma(prop, ps, mp.cg_m[0], s, c)
    D["Cma"] += cma_prop
    D["Cnb"] -= cma_prop * c / b  # same normal-force mechanism in yaw (per b instead of c)
    # downwash lag
    ht = d.tail.htail
    s_h = 2 * ht.area_mm2 * 1e-6
    ar_h = (2 * ht.span_mm) ** 2 / (2 * ht.area_mm2)
    a_t = 2 * math.pi * ar_h / (2 + math.sqrt(ar_h**2 + 4))  # Helmbold
    l_t = d.tail.l_h_mm * 1e-3
    v_h = s_h * l_t / (s * c)
    D["Cmad"] = -2.0 * eta_h * a_t * v_h * (l_t / c) * deps
    D["CLad"] = 2.0 * eta_h * a_t * v_h * deps
    D["CL"], D["CD"] = trim.cl, trim.cd
    D["CDa"] = ab_f["CDa"]
    D.update(_control_derivs(d, x_cg_mm, v, al, de))
    D["eta_h"], D["eta_v_sigma"], D["Cma_prop"] = eta_h, eta_v_sig, cma_prop
    np_power_on = x_cg_mm - D["Cma"] / D["CLa"] * mac
    sm_on = (np_power_on - x_cg_mm) / mac

    # --- dimensional derivatives (stability axes, Nelson)
    m, u0 = mp.mass_kg, v
    iy, ix, iz, ixz = mp.iyy, mp.ixx, mp.izz, mp.ixz
    th0 = 0.0  # level flight
    Xu = -2.0 * D["CD"] * q * s / (m * u0) - trim.thrust_n / (m * u0)  # constant power: dT/du = -T/u0
    Xw = -(D["CDa"] - D["CL"]) * q * s / (m * u0)
    Zu = -2.0 * D["CL"] * q * s / (m * u0)
    Zw = -(D["CLa"] + D["CD"]) * q * s / (m * u0)
    Zwd = -D["CLad"] * c / (2 * u0) * q * s / (m * u0)
    Zq = -D["CLq"] * c / (2 * u0) * q * s / m
    Mu = 0.0
    Mw = D["Cma"] * q * s * c / (u0 * iy)
    Mwd = D["Cmad"] * c / (2 * u0) * q * s * c / (u0 * iy)
    Mq = D["Cmq"] * c / (2 * u0) * q * s * c / iy
    k = 1.0 / (1.0 - Zwd)
    a_long = np.array([
        [Xu, Xw, 0.0, -G * math.cos(th0)],
        [Zu * k, Zw * k, (u0 + Zq) * k, 0.0],
        [Mu + Mwd * Zu * k, Mw + Mwd * Zw * k, Mq + Mwd * (u0 + Zq) * k, 0.0],
        [0.0, 0.0, 1.0, 0.0],
    ])
    Xde = -D["CDde"] * q * s / m
    Zde = -D["CLde"] * q * s / m
    Mde = D["Cmde"] * q * s * c / iy
    b_long = np.array([[Xde], [Zde * k], [Mde + Mwd * Zde * k], [0.0]])

    Yb = q * s * D["CYb"] / m
    Yp = q * s * b * D["CYp"] / (2 * m * u0)
    Yr = q * s * b * D["CYr"] / (2 * m * u0)
    Lb = q * s * b * D["Clb"] / ix
    Lp = q * s * b * b * D["Clp"] / (2 * ix * u0)
    Lr = q * s * b * b * D["Clr"] / (2 * ix * u0)
    Nb = q * s * b * D["Cnb"] / iz
    Np = q * s * b * b * D["Cnp"] / (2 * iz * u0)
    Nr = q * s * b * b * D["Cnr"] / (2 * iz * u0)
    Lda, Ldr = q * s * b * D["Clda"] / ix, q * s * b * D["Cldr"] / ix
    Nda, Ndr = q * s * b * D["Cnda"] / iz, q * s * b * D["Cndr"] / iz
    Yda, Ydr = q * s * D["CYda"] / m, q * s * D["CYdr"] / m
    gam = 1.0 - ixz**2 / (ix * iz)

    def prime(L, N):
        return (L + ixz / ix * N) / gam, (N + ixz / iz * L) / gam

    Lb_, Nb_ = prime(Lb, Nb)
    Lp_, Np_ = prime(Lp, Np)
    Lr_, Nr_ = prime(Lr, Nr)
    Lda_, Nda_ = prime(Lda, Nda)
    Ldr_, Ndr_ = prime(Ldr, Ndr)
    a_lat = np.array([
        [Yb / u0, Yp / u0, -(1.0 - Yr / u0), G * math.cos(th0) / u0],
        [Lb_, Lp_, Lr_, 0.0],
        [Nb_, Np_, Nr_, 0.0],
        [0.0, 1.0, 0.0, 0.0],
    ])
    b_lat = np.array([[Yda / u0, Ydr / u0], [Lda_, Ldr_], [Nda_, Ndr_], [0.0, 0.0]])

    modes = identify_modes(np.linalg.eigvals(a_long), np.linalg.eigvals(a_lat))
    crit = check_criteria(modes)
    approx = {
        "phugoid_omega_lanchester": math.sqrt(2) * G / u0,
        "phugoid_zeta_lanchester": (D["CD"] / D["CL"]) / math.sqrt(2),
        "short_period_omega_approx": math.sqrt(max(Zw * Mq - u0 * Mw, 0.0)),
        "short_period_zeta_approx": -(Zw + Mq + u0 * Mwd) / (2 * math.sqrt(max(Zw * Mq - u0 * Mw, 1e-12))),
        "roll_tau_approx": -1.0 / Lp_,
        "dutch_roll_omega_approx": math.sqrt(max(Nb_ + Yb * Nr_ / u0, 0.0)),
    }
    return FlightDynamicsResult(mp, trim, trim_off, alphas, eps, deps, deps_emp, D, a_long, b_long, a_lat, b_lat,
                                modes, crit, approx, sm_on, np_power_on,
                                extras={"prop": prop, "prop_state": ps, "eta_v_sigma": eta_v_sig})


def identify_modes(eig_long, eig_lat) -> dict[str, Mode]:
    modes = {}
    cl = sorted([e for e in eig_long if e.imag > 1e-9], key=lambda e: abs(e))
    if len(cl) == 2:
        modes["phugoid"], modes["short_period"] = (_osc(n, e) for n, e in zip(("phugoid", "short_period"), cl))
    else:  # overdamped short period: two real roots + phugoid pair
        ph = cl[0] if cl else None
        if ph is not None:
            modes["phugoid"] = _osc("phugoid", ph)
        # overdamped short period: the two fastest real roots r1, r2 -> omega_n = sqrt(r1 r2),
        # zeta = -(r1 + r2) / (2 omega_n)  (> 1)
        reals = sorted([e.real for e in eig_long if abs(e.imag) <= 1e-9])
        r1, r2 = reals[0], reals[1]
        wn = math.sqrt(r1 * r2)
        modes["short_period"] = Mode("short_period", complex(r1, 0.0), wn, -(r1 + r2) / (2.0 * wn),
                                     time_constant_s=-1.0 / r2)
    osc = [e for e in eig_lat if e.imag > 1e-9]
    reals = sorted([e.real for e in eig_lat if abs(e.imag) <= 1e-9])
    if osc:
        modes["dutch_roll"] = _osc("dutch_roll", osc[0])
    roll = reals[0]
    modes["roll"] = Mode("roll", complex(roll), abs(roll), 1.0, time_constant_s=-1.0 / roll)
    sp = reals[-1]
    modes["spiral"] = Mode("spiral", complex(sp), abs(sp), 1.0,
                           time_constant_s=(-1.0 / sp) if sp < 0 else None,
                           time_to_double_s=(math.log(2) / sp) if sp > 0 else None)
    return modes


def _osc(name, e):
    wn = abs(e)
    zeta = -e.real / wn
    return Mode(name, complex(e), wn, zeta, period_s=2 * math.pi / e.imag)


def check_criteria(modes) -> dict[str, tuple[float, str, bool]]:
    c = MIL_LEVEL1
    out = {}
    sp = modes["short_period"]
    out["short-period damping"] = (sp.zeta, f"{c['short_period_damping'][0]}-{c['short_period_damping'][1]}",
                                   c["short_period_damping"][0] <= sp.zeta <= c["short_period_damping"][1])
    ph = modes.get("phugoid")
    if ph:
        out["phugoid damping"] = (ph.zeta, f">= {c['phugoid_damping_min']}", ph.zeta >= c["phugoid_damping_min"])
    dr = modes.get("dutch_roll")
    if dr:
        out["Dutch-roll damping"] = (dr.zeta, f">= {c['dutch_roll_damping_min']}",
                                     dr.zeta >= c["dutch_roll_damping_min"])
        out["Dutch-roll zeta*omega"] = (dr.zeta * dr.omega_n, f">= {c['dutch_roll_zeta_omega_min']}",
                                        dr.zeta * dr.omega_n >= c["dutch_roll_zeta_omega_min"])
        out["Dutch-roll frequency"] = (dr.omega_n, f">= {c['dutch_roll_omega_min']} rad/s",
                                       dr.omega_n >= c["dutch_roll_omega_min"])
    rl = modes["roll"]
    out["roll time constant"] = (rl.time_constant_s, f"<= {c['roll_time_constant_max_s']} s",
                                 rl.time_constant_s <= c["roll_time_constant_max_s"])
    spm = modes["spiral"]
    if spm.time_to_double_s is None:
        out["spiral"] = (spm.time_constant_s, "stable (or T2 >= 20 s)", True)
    else:
        out["spiral time to double"] = (spm.time_to_double_s, f">= {c['spiral_time_to_double_min_s']} s",
                                        spm.time_to_double_s >= c["spiral_time_to_double_min_s"])
    return out


# ---------------------------------------------------------------- control authority

@dataclass
class ControlAuthority:
    trim_curve: dict  # cg label -> list of (V, alpha, elevator)
    stall_trim_elevator_deg: float
    elevator_limit_deg: float
    roll_rate_dps: float
    pb_2v: float
    time_to_30deg_s: float
    crosswind_mps: float
    crosswind_required_mps: float
    v_stall_mps: float


def control_authority(d: AircraftDesign, fd: FlightDynamicsResult, cg_cases: dict[str, float],
                      elevator_limit_deg: float = 20.0, aileron_deg: float = 15.0, rudder_deg: float = 25.0,
                      speeds=None) -> ControlAuthority:
    import aerosandbox as asb

    mp = fd.mass
    a = d.campaign.aero
    s = a.lifting_line.area_m2
    b = d.campaign.requirement.span_mm * 1e-3
    w = mp.mass_kg * G
    cl_max = 0.9 * 1.47  # campaign wing CLmax = 0.9 x section clmax (NACA 4412 at this Re)
    v_s = math.sqrt(2 * w / (RHO * s * cl_max))
    speeds = speeds or [1.2 * v_s, 20.0, 25.0, 30.0, 35.0]
    eps0 = float(np.interp(0.0, fd.downwash_alphas_deg, fd.downwash_eps_rad))
    curves = {}
    for label, x_cg in cg_cases.items():
        pts = []
        for vv in speeds:
            t = trim_power_on(d, mp, fd.extras["prop"], vv, eps0, fd.deps_dalpha, x_cg_mm=x_cg)
            pts.append((vv, t.alpha_deg, t.elevator_deg))
        curves[label] = pts
    # elevator to trim at CL_max at the most forward CG (power off, conservative)
    x_fwd = min(cg_cases.values())

    def cm_at_clmax(de):
        ap = _ap(d, x_fwd, elevator_deg=float(de))

        def cl_err(al):
            r = asb.AeroBuildup(ap, asb.OperatingPoint(velocity=v_s * 1.05, alpha=float(al))).run()
            return float(np.ravel(r["CL"])[0]) - cl_max

        al = fsolve(lambda x: [cl_err(x[0])], [10.0])[0]
        r = asb.AeroBuildup(ap, asb.OperatingPoint(velocity=v_s * 1.05, alpha=float(al))).run()
        return float(np.ravel(r["Cm"])[0])

    de_stall = float(fsolve(lambda x: [cm_at_clmax(x[0])], [-10.0])[0])
    D = fd.derivatives
    pb2v = abs(D["Clda"] * math.radians(aileron_deg) / D["Clp"])
    v = d.campaign.requirement.cruise_velocity_mps
    p = pb2v * 2 * v / b
    tau = fd.modes["roll"].time_constant_s
    # first-order roll response to a step: phi(t) = p_ss (t - tau (1 - e^{-t/tau}))
    tt = np.linspace(0, 10, 20001)
    phi = p * (tt - tau * (1 - np.exp(-tt / tau)))
    t30 = float(tt[np.argmax(phi >= math.radians(30.0))])
    beta_max = min(abs(D["Cndr"] * math.radians(rudder_deg) / D["Cnb"]), math.radians(15.0))
    v_app = 1.3 * v_s
    return ControlAuthority(curves, de_stall, elevator_limit_deg, math.degrees(p), pb2v, t30,
                            v_app * math.tan(abs(beta_max)), 0.2 * v_s * 1.0, v_s)


def size_dihedral(d: AircraftDesign, structure, mass: MassProperties, spiral_t2_min_s: float = 20.0,
                  step_deg: float = 0.5, bounds=(0.0, 10.0)) -> tuple[float, list[tuple[float, float]]]:
    """Smallest dihedral (rounded up to `step_deg`) giving a spiral mode that is stable or doubles no faster
    than `spiral_t2_min_s` (MIL-F-8785C Level 1 for Class I is 20 s). Returns (dihedral, [(gamma, lambda)])."""
    from scipy.optimize import brentq

    target = math.log(2.0) / spiral_t2_min_s
    hist: list[tuple[float, float]] = []

    def lam(gamma):
        d.dihedral_deg = float(gamma)
        fd = analyze_flight_dynamics(d, structure, mass=mass)
        val = fd.modes["spiral"].eigenvalue.real
        hist.append((float(gamma), val))
        return val - target

    lo, hi = bounds
    if lam(lo) <= 0:
        gamma = lo
    else:
        if lam(hi) > 0:
            raise ValueError(f"spiral criterion not met with dihedral up to {hi} deg")
        gamma = brentq(lam, lo, hi, xtol=0.05)
    gamma = math.ceil(gamma / step_deg - 1e-9) * step_deg
    d.dihedral_deg = gamma
    return gamma, sorted(hist)


def design_flight_ready(campaign, structure, sm_power_on_target: float = 0.10, iterations: int = 2, tails=None):
    """v0.16 layout: split battery packs around a CG-centred payload bay, wing placed for the POWER-ON static
    margin (propeller normal force and slipstream included), dihedral sized for the spiral criterion.

    The wing-placement solver works on the power-off neutral point (VLM + fuselage); the power-on margin is
    obtained by correcting its target with the power-effect shift measured on the previous iterate.
    """
    from engineering.analysis.aircraft_layout import design_aircraft

    target = sm_power_on_target
    history = []
    d = fd = mp = None
    gamma = 0.0
    tail_masses = None
    if tails is not None:
        from engineering.analysis.tail_structure import tail_mass_items

        tail_masses = tail_mass_items(tails)
    for _ in range(iterations):
        d = design_aircraft(campaign, structure.masses_kg(), payload_at_empty_cg=True, sm_target=target,
                            tail_masses=tail_masses)
        d.tail_structure = tails
        d.dihedral_deg = gamma
        mp = mass_properties(d, structure)
        fd = analyze_flight_dynamics(d, structure, mass=mp)
        history.append((target, d.static_margin, fd.static_margin_power_on))
        target += sm_power_on_target - fd.static_margin_power_on
    gamma, _ = size_dihedral(d, structure, mp)
    fd = analyze_flight_dynamics(d, structure, mass=mp)
    return d, mp, fd, history
