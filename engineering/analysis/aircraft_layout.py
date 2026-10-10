"""Whole-aircraft layout: empennage sizing, fuselage, mass & balance, static stability, trim (v0.15).

The aircraft grows around the v0.14 campaign wing (`wing_campaign.py`):

1. Empennage by tail-volume coefficients (Raymer, *Aircraft Design: A
   Conceptual Approach*, Table 6.4, single-engine general aviation):
   V_H = S_h l_h / (S c_bar) = 0.70,  V_V = S_v l_v / (S b) = 0.04,
   with NACA 0009 (stabiliser) / NACA 0010 (fin), elevator 30 % and rudder
   35 % of local chord.
2. Fuselage cabin sized around the internal component boxes (+ clearance and
   skin); boom carries the tail.
3. Mass & balance from a component list (fictional electric 12 kg UAV:
   motor, propeller, ESC, battery, avionics, servos, wiring) plus structure
   masses computed from the CAD volumes; payload = MTOW - everything else,
   placed in the payload bay.
4. Static stability with aerosandbox: a vortex-lattice run on wing + tails
   (potential-flow downwash at the tail) plus the fuselage's destabilising
   increment from AeroBuildup (NP with minus without fuselage).
   Static margin SM = (x_np - x_cg) / c_bar.
5. With the tail volume fixed (tail arm 3 x MAC), the neutral point moves
   with the wing while the CG is dominated by the fuselage systems, so the wing
   longitudinal position x_LE is solved (brentq) for SM = 10 % MAC (5-15 %
   band); tail position, boom length, fuselage and all masses move with it.
   Design NP = VLM NP (wing + tails) + fuselage increment from AeroBuildup.
6. Trim at cruise: solve (alpha, delta_e) with AeroBuildup so that CL = W/(qS)
   and Cm_cg = 0 (AeroBuildup models the elevator); cross-check with VLM
   using an all-moving-tail incidence converted to elevator deflection with
   thin-airfoil flap effectiveness.

Honest limits: conceptual-design fidelity; no propeller/slipstream, downwash
lag, thrust-line or landing-gear effects; masses of bought-in components are
representative values for this class, not a specific product.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import brentq, fsolve

from agents.geometry.fuselage_tail import (
    SurfaceGeometry,
    build_fuselage,
    build_htail,
    build_vtail,
    flap_effectiveness,
    fuselage_stations,
    tail_surface,
)
from engineering.analysis.wing_campaign import CampaignResult

G = 9.81
RHO = 1.225
V_H_DEFAULT = 0.70  # Raymer Table 6.4, GA single engine
V_V_DEFAULT = 0.04
GLASS_DENSITY = 1600.0
FOAM_DENSITY = 30.0  # EPS/XPS tail core
PLY_DENSITY = 600.0  # light plywood formers


BATTERY_LENGTH_MM = 200.0
CABIN_START_MM = 110.0


class AircraftLayoutError(RuntimeError):
    """Raised when the layout cannot meet its stability target."""


@dataclass(frozen=True)
class Component:
    name: str
    mass_kg: float
    x_mm: float  # CG station from the nose
    z_mm: float = 0.0
    box_mm: tuple[float, float, float] | None = None  # length, width, height (for cabin sizing / CAD)
    group: str = "systems"


def default_components() -> list[Component]:
    """Representative systems of a fictional 12 kg electric fixed-wing UAV (stations in mm)."""
    return [
        Component("Propeller", 0.08, -15.0, 0.0, None, "propulsion"),
        Component("Motor", 0.45, 45.0, 0.0, (60.0, 60.0, 60.0), "propulsion"),
        Component("ESC", 0.15, 120.0, -20.0, (70.0, 40.0, 20.0), "propulsion"),
        Component("Battery", 2.80, 240.0, -10.0, (200.0, 90.0, 70.0), "energy"),
        Component("Avionics", 0.35, 370.0, 25.0, (100.0, 80.0, 40.0), "systems"),
        Component("Servos", 0.20, 520.0, 30.0, None, "systems"),
        Component("Wiring & misc", 0.40, 420.0, 0.0, None, "systems"),
    ]


BATTERY_PACK_GAP_MM = 10.0


def balanced_components() -> list[Component]:
    """Same systems as `default_components` but the battery split into two 1.4 kg packs (100 mm long) that sit
    fore and aft of a CG-centred payload bay (positions set by `design_aircraft(payload_at_empty_cg=True)`)."""
    comps = [c for c in default_components() if c.name != "Battery"]
    comps.append(Component("Battery (fwd)", 1.40, 240.0, -10.0, (100.0, 90.0, 70.0), "energy"))
    comps.append(Component("Battery (aft)", 1.40, 520.0, -10.0, (100.0, 90.0, 70.0), "energy"))
    return comps


@dataclass
class TailDesign:
    l_h_mm: float
    htail: SurfaceGeometry
    vtail: SurfaceGeometry
    x_htail_le_mm: float
    x_vtail_le_mm: float


@dataclass
class MassItem:
    name: str
    mass_kg: float
    x_mm: float
    z_mm: float
    group: str


@dataclass
class AircraftDesign:
    campaign: CampaignResult
    wing_x_le_mm: float
    wing_z_mm: float
    tail: TailDesign
    stations: list
    mass_items: list[MassItem]
    mtow_kg: float
    payload_kg: float
    x_cg_mm: float
    z_cg_mm: float
    mac_mm: float
    x_mac_le_mm: float
    x_np_mm: float  # AeroBuildup (with fuselage) -- used for design
    x_np_vlm_mm: float  # VLM, lifting surfaces only -- cross-check
    static_margin: float
    static_margin_vlm: float
    trim_alpha_deg: float
    trim_elevator_deg: float
    trim_elevator_vlm_deg: float
    cl_cruise: float
    sm_vs_lh: list[tuple[float, float]] = field(default_factory=list)  # (wing x_LE, SM) sweep
    x_np_aerobuildup_mm: float = float("nan")
    x_np_aerobuildup_nofus_mm: float = float("nan")
    dihedral_deg: float = 0.0  # set by the lateral-stability sizing (flight_dynamics.size_dihedral)
    tail_structure: object = None  # v0.16 built-up tails (tail_structure.TailStructureResult) when designed

    @property
    def total_mass_kg(self) -> float:
        return sum(m.mass_kg for m in self.mass_items)


# ---------------------------------------------------------------- geometry builders

def wing_mac(root_mm: float, tip_mm: float, semispan_mm: float) -> tuple[float, float]:
    """(MAC, spanwise station of the MAC) for a straight-tapered half wing."""
    lam = tip_mm / root_mm
    mac = 2.0 / 3.0 * root_mm * (1 + lam + lam**2) / (1 + lam)
    y = semispan_mm / 3.0 * (1 + 2 * lam) / (1 + lam)
    return mac, y


def size_tail(campaign: CampaignResult, l_h_mm: float, x_wing_qc_mm: float,
              v_h: float = V_H_DEFAULT, v_v: float = V_V_DEFAULT) -> TailDesign:
    a = campaign.aero
    s_mm2 = a.lifting_line.area_m2 * 1e6
    b_mm = campaign.requirement.span_mm
    mac, _ = wing_mac(a.root_chord_mm, a.tip_chord_mm, b_mm / 2)
    s_h = v_h * mac * s_mm2 / l_h_mm
    s_v = v_v * b_mm * s_mm2 / l_h_mm  # fin arm taken equal to the stabiliser arm
    ht = tail_surface(s_h, 4.5, 0.7, "0009", 0.70)
    vt = tail_surface(s_v, 1.6, 0.6, "0010", 0.65, sweep_le_deg=25.0, both_sides=False)
    x_h_qc = x_wing_qc_mm + l_h_mm
    x_h_le = x_h_qc - 0.25 * ht.mac_mm
    x_v_le = x_h_qc - 0.25 * vt.mac_mm - 0.15 * vt.root_chord_mm
    return TailDesign(l_h_mm, ht, vt, x_h_le, x_v_le)


def _cabin(components: list[Component], clearance_mm: float = 10.0, skin_mm: float = 0.8):
    boxes = [c.box_mm for c in components if c.box_mm]
    w = max(b[1] for b in boxes) + 2 * (clearance_mm + skin_mm)
    h = max(b[2] for b in boxes) + 2 * (clearance_mm + skin_mm)
    return w, h


def _layout(campaign, components, l_h_mm, wing_x_le_mm, payload_x_mm, payload_box, mtow_kg, aft_extent_mm=0.0):
    a = campaign.aero
    b_mm = campaign.requirement.span_mm
    mac, _y_mac = wing_mac(a.root_chord_mm, a.tip_chord_mm, b_mm / 2)
    x_mac_le = wing_x_le_mm  # unswept: MAC leading edge at the wing LE
    x_wing_qc = x_mac_le + 0.25 * mac
    tail = size_tail(campaign, l_h_mm, x_wing_qc)
    w_cab, h_cab = _cabin(components + [Component("Payload", 0, payload_x_mm, 0, payload_box)])
    cabin_end = max(wing_x_le_mm + a.root_chord_mm, payload_x_mm + payload_box[0] / 2 + 20, aft_extent_mm + 20)
    tail_end = tail.x_htail_le_mm + tail.htail.root_chord_mm
    stations = fuselage_stations(w_cab, h_cab, 110.0, cabin_end, tail_end)
    wing_z = h_cab / 2.0  # high wing: wing lower surface ~ cabin top
    return mac, x_mac_le, tail, stations, wing_z


def _structure_masses(campaign, wing_x_le_mm, wing_z_mm, tail, stations, structure_masses, tail_masses=None):
    items = []
    a = campaign.aero
    # wing structure from the v0.14 CAD (both halves): centroid ~ 40 % chord at the MAC
    mac, _ = wing_mac(a.root_chord_mm, a.tip_chord_mm, campaign.requirement.span_mm / 2)
    items.append(MassItem("Wing structure", sum(structure_masses.values()), wing_x_le_mm + 0.40 * mac,
                          wing_z_mm, "structure"))
    fus = build_fuselage(stations, former_x_mm=_former_x(stations))
    skin = next(c for c in fus.children if c.label == "FuselageSkin")
    formers = [c for c in fus.children if c.label.startswith("Former")]
    items.append(MassItem("Fuselage skin", skin.volume * 1e-9 * GLASS_DENSITY, skin.center().X, skin.center().Z,
                          "structure"))
    items.append(MassItem("Formers", sum(f.volume for f in formers) * 1e-9 * PLY_DENSITY,
                          float(np.mean([f.center().X for f in formers])), 0.0, "structure"))
    for name, geo, x_le, z in (("Horizontal tail", tail.htail, tail.x_htail_le_mm, stations[-1].z_center_mm),
                               ("Vertical tail", tail.vtail, tail.x_vtail_le_mm, stations[-1].z_center_mm)):
        if tail_masses and name in tail_masses:
            # built-up tail measured from its CAD: (mass, centroid x from the surface LE, centroid z offset)
            m_t, dx, dz = tail_masses[name]
            items.append(MassItem(name, m_t, x_le + dx, z + dz, "structure"))
            continue
        n_sides = 2 if name.startswith("Horizontal") else 1
        area_m2 = geo.area_mm2 * n_sides * 1e-6
        t_mean = int(geo.naca[-2:]) / 100.0 * 0.69 * geo.mac_mm * 1e-3  # NACA section area ~0.685 t c
        core = area_m2 * t_mean * FOAM_DENSITY
        skin_m = 2.05 * area_m2 * 0.3e-3 * GLASS_DENSITY  # wetted ~2.05 x planform, 0.3 mm glass
        items.append(MassItem(name, core + skin_m, x_le + 0.42 * geo.mac_mm, z, "structure"))
    return items


def _former_x(stations):
    return [stations[2].x_mm, 0.5 * (stations[2].x_mm + stations[3].x_mm), stations[3].x_mm]


def mass_balance(items: list[MassItem]) -> tuple[float, float, float]:
    m = sum(i.mass_kg for i in items)
    x = sum(i.mass_kg * i.x_mm for i in items) / m
    z = sum(i.mass_kg * i.z_mm for i in items) / m
    return m, x, z


# ---------------------------------------------------------------- aerodynamics (aerosandbox)

AILERON_SPAN = (0.50, 0.95)  # fraction of semispan
AILERON_HINGE_XC = 0.75
RUDDER_DEFAULT_HINGE = 0.65


def _asb_airplane(campaign, wing_x_le_mm, wing_z_mm, tail, stations, x_ref_mm, elevator_deg=0.0,
                  htail_incidence_deg=0.0, with_fuselage=True, aileron_deg=0.0, rudder_deg=0.0,
                  include_htail=True, include_vtail=True, include_wing=True, dihedral_deg=0.0):
    """aerosandbox model. Ailerons on 50-95 % semispan (25 % chord, antisymmetric: positive = right roll
    command per aerosandbox convention), elevator 30 %, rudder 35 % chord."""
    import aerosandbox as asb

    a = campaign.aero
    mm = 1e-3
    b2 = campaign.requirement.span_mm / 2 * mm
    af = asb.Airfoil(f"naca{a.naca}")

    def chord_at(eta):
        return (a.root_chord_mm + (a.tip_chord_mm - a.root_chord_mm) * eta) * mm

    ail = [asb.ControlSurface(name="aileron", symmetric=False, hinge_point=AILERON_HINGE_XC,
                              deflection=aileron_deg)]
    xs = []
    for eta, cs in ((0.0, []), (AILERON_SPAN[0], ail), (AILERON_SPAN[1], []), (1.0, [])):
        z_eta = wing_z_mm * mm + eta * b2 * math.tan(math.radians(dihedral_deg))
        xs.append(asb.WingXSec(xyz_le=[wing_x_le_mm * mm, eta * b2, z_eta], chord=chord_at(eta),
                               airfoil=af, control_surfaces=cs))
    wing = asb.Wing(name="Wing", symmetric=True, xsecs=xs)
    ht, vt = tail.htail, tail.vtail
    z_t = stations[-1].z_center_mm * mm
    elev = [asb.ControlSurface(name="elevator", symmetric=True, hinge_point=ht.hinge_xc, deflection=elevator_deg)]
    htail = asb.Wing(name="HTail", symmetric=True, xsecs=[
        asb.WingXSec(xyz_le=[tail.x_htail_le_mm * mm, 0, z_t], chord=ht.root_chord_mm * mm,
                     twist=htail_incidence_deg, airfoil=asb.Airfoil(f"naca{ht.naca}"), control_surfaces=elev),
        asb.WingXSec(xyz_le=[tail.x_htail_le_mm * mm, ht.span_mm * mm, z_t], chord=ht.tip_chord_mm * mm,
                     twist=htail_incidence_deg, airfoil=asb.Airfoil(f"naca{ht.naca}"), control_surfaces=elev),
    ])
    sweep = math.tan(math.radians(vt.sweep_le_deg))
    rud = [asb.ControlSurface(name="rudder", symmetric=True, hinge_point=vt.hinge_xc, deflection=rudder_deg)]
    vtail = asb.Wing(name="VTail", symmetric=False, xsecs=[
        asb.WingXSec(xyz_le=[tail.x_vtail_le_mm * mm, 0, z_t], chord=vt.root_chord_mm * mm,
                     airfoil=asb.Airfoil(f"naca{vt.naca}"), control_surfaces=rud),
        asb.WingXSec(xyz_le=[(tail.x_vtail_le_mm + vt.span_mm * sweep) * mm, 0, z_t + vt.span_mm * mm],
                     chord=vt.tip_chord_mm * mm, airfoil=asb.Airfoil(f"naca{vt.naca}")),
    ])
    fuselages = []
    if with_fuselage:
        fuselages = [asb.Fuselage(name="Fuselage", xsecs=[
            asb.FuselageXSec(xyz_c=[s.x_mm * mm, 0, s.z_center_mm * mm], width=s.width_mm * mm,
                             height=s.height_mm * mm) for s in stations])]
    mac, _ = wing_mac(a.root_chord_mm, a.tip_chord_mm, campaign.requirement.span_mm / 2)
    wings = ([wing] if include_wing else []) + ([htail] if include_htail else []) + ([vtail] if include_vtail else [])
    return asb.Airplane(name="AeroForge UAV", xyz_ref=[x_ref_mm * mm, 0, 0], wings=wings,
                        fuselages=fuselages, s_ref=a.lifting_line.area_m2, c_ref=mac * mm,
                        b_ref=2 * b2)


def neutral_points(campaign, wing_x_le_mm, wing_z_mm, tail, stations, x_ref_mm, alpha_deg, v):
    """Neutral points [mm]: (design, VLM lifting surfaces, AeroBuildup with fuselage, AeroBuildup without).

    Design NP = VLM NP (wing + tails, potential-flow downwash at the tail) + fuselage increment, where the
    fuselage increment is taken from AeroBuildup as NP(with fuselage) - NP(without). AeroBuildup alone is not
    used directly because its empirical tail downwash puts its NP aft of the VLM value even with the fuselage.
    """
    import aerosandbox as asb

    op = asb.OperatingPoint(velocity=v, alpha=alpha_deg)

    def ab_np(with_fuselage):
        ap = _asb_airplane(campaign, wing_x_le_mm, wing_z_mm, tail, stations, x_ref_mm, with_fuselage=with_fuselage)
        r = asb.AeroBuildup(ap, op).run_with_stability_derivatives(alpha=True, beta=False, p=False, q=False,
                                                                    r=False)
        return float(np.ravel(r["x_np"])[0]) * 1e3

    apv = _asb_airplane(campaign, wing_x_le_mm, wing_z_mm, tail, stations, x_ref_mm, with_fuselage=False)
    vl = asb.VortexLatticeMethod(apv, op).run_with_stability_derivatives(alpha=True, beta=False, p=False, q=False,
                                                                          r=False)
    x_vlm = x_ref_mm - float(vl["Cma"]) / float(vl["CLa"]) * apv.c_ref * 1e3
    ab_with, ab_without = ab_np(True), ab_np(False)
    return x_vlm + (ab_with - ab_without), x_vlm, ab_with, ab_without


def trim(campaign, wing_x_le_mm, wing_z_mm, tail, stations, x_cg_mm, mass_kg, v):
    """(alpha, elevator) for CL = W/(qS), Cm_cg = 0 with AeroBuildup; plus a VLM all-moving-tail cross-check."""
    import aerosandbox as asb

    s = campaign.aero.lifting_line.area_m2
    cl_req = mass_kg * G / (0.5 * RHO * v**2 * s)

    def ab(x):
        al, de = x
        ap = _asb_airplane(campaign, wing_x_le_mm, wing_z_mm, tail, stations, x_cg_mm, elevator_deg=de)
        r = asb.AeroBuildup(ap, asb.OperatingPoint(velocity=v, alpha=al)).run()
        return [float(np.ravel(r["CL"])[0]) - cl_req, float(np.ravel(r["Cm"])[0])]

    al, de = fsolve(ab, [2.0, 0.0], xtol=1e-6)

    def vlm(x):
        al, inc = x
        ap = _asb_airplane(campaign, wing_x_le_mm, wing_z_mm, tail, stations, x_cg_mm, htail_incidence_deg=inc,
                           with_fuselage=False)
        r = asb.VortexLatticeMethod(ap, asb.OperatingPoint(velocity=v, alpha=al)).run()
        return [float(r["CL"]) - cl_req, float(r["Cm"])]

    _, inc = fsolve(vlm, [2.0, 0.0], xtol=1e-6)
    de_vlm = inc / flap_effectiveness(1.0 - tail.htail.hinge_xc)
    return float(al), float(de), float(de_vlm), cl_req


# ---------------------------------------------------------------- design loop

def design_aircraft(campaign: CampaignResult, structure_masses: dict[str, float],
                    components: list[Component] | None = None, l_h_over_mac: float = 3.0,
                    payload_x_mm: float = 470.0, payload_box=(180.0, 100.0, 100.0),
                    sm_target: float = 0.10, wing_x_bounds=(50.0, 600.0),
                    payload_at_empty_cg: bool = False,
                    tail_masses: dict[str, tuple[float, float, float]] | None = None) -> AircraftDesign:
    """Grow the aircraft around the campaign wing and place the wing for the target static margin.

    The empennage is sized by the tail-volume coefficients at a tail arm of `l_h_over_mac` x MAC
    (typical small-UAV/GA range 2.5-3.5). With tail volume fixed, the neutral point moves with the
    wing while the CG is dominated by the fuselage-mounted systems, so the wing longitudinal position
    is the balancing variable: brentq on x_LE gives SM = `sm_target` (5-15 % band).
    """
    comps = components or default_components()
    mtow = campaign.requirement.mtow_kg
    v = campaign.requirement.cruise_velocity_mps
    a = campaign.aero
    mac0, _ = wing_mac(a.root_chord_mm, a.tip_chord_mm, campaign.requirement.span_mm / 2)
    l_h = l_h_over_mac * mac0
    history: list[tuple[float, float]] = []
    cache: dict[float, dict] = {}
    _aft_extent: dict[str, float] = {}
    if payload_at_empty_cg and components is None:
        comps = balanced_components()

    def evaluate(x_le):
        key = round(float(x_le), 3)
        if key in cache:
            return cache[key]
        mac, x_mac_le, tail, stations, wing_z = _layout(campaign, comps, l_h, x_le, payload_x_mm, payload_box,
                                                        mtow, aft_extent_mm=_aft_extent.get("x", 0.0))
        items = [MassItem(c.name, c.mass_kg, c.x_mm, c.z_mm, c.group) for c in comps]
        items += _structure_masses(campaign, x_le, wing_z, tail, stations, structure_masses, tail_masses)
        empty = sum(i.mass_kg for i in items)
        payload = mtow - empty
        if payload <= 0:
            raise AircraftLayoutError(f"no payload left: empty mass {empty:.2f} kg >= MTOW {mtow} kg")
        x_pay = payload_x_mm
        overlap = False
        if payload_at_empty_cg:
            # Real-world balancing: the payload bay is centred on the CG of everything else and the two battery
            # packs sit symmetrically fore and aft of it, so the CG does not move whether the payload is loaded
            # or not (and battery + payload together do not shift it either).
            packs = [i for i in items if i.name.startswith("Battery")]
            others = [i for i in items if not i.name.startswith("Battery")]
            x_pay = sum(i.mass_kg * i.x_mm for i in others) / sum(i.mass_kg for i in others)
            off = 0.5 * payload_box[0] + 50.0 + BATTERY_PACK_GAP_MM
            for pk, sgn in zip(sorted(packs, key=lambda i: i.name, reverse=True), (-1.0, 1.0)):
                pk.x_mm = x_pay + sgn * off  # "Battery (fwd)" forward, "Battery (aft)" aft
            overlap = x_pay - off - 50.0 < CABIN_START_MM
        items.append(MassItem("Payload", payload, x_pay, 0.0, "payload"))
        if payload_at_empty_cg:
            aft = max(i.x_mm + 50.0 for i in items if i.name.startswith("Battery"))
            if aft + 20 > stations[3].x_mm + 1e-6 and _aft_extent.get("x") != aft:
                _aft_extent["x"] = aft
                cache.pop(key, None)
                return evaluate(x_le)
        m, x_cg, z_cg = mass_balance(items)
        x_np, x_vlm, x_ab, x_ab_nofus = neutral_points(campaign, x_le, wing_z, tail, stations, x_cg,
                                                       campaign.requirement.alpha_deg, v)
        sm = (x_np - x_cg) / mac
        history.append((float(x_le), sm))
        cache[key] = {"mac": mac, "x_mac_le": x_mac_le, "tail": tail, "stations": stations, "wing_z": wing_z, "items": items,
                          "m": m, "x_cg": x_cg, "z_cg": z_cg, "x_np": x_np, "x_vlm": x_vlm, "x_ab": x_ab, "x_ab_nofus": x_ab_nofus,
                          "sm": sm, "payload": payload, "overlap": overlap}
        return cache[key]

    lo, hi = wing_x_bounds
    f_lo, f_hi = evaluate(lo)["sm"] - sm_target, evaluate(hi)["sm"] - sm_target
    if f_lo * f_hi > 0:
        raise AircraftLayoutError(f"static margin target {sm_target:.0%} not bracketed by wing x_LE in "
                                  f"{wing_x_bounds} (SM {f_lo + sm_target:.3f} .. {f_hi + sm_target:.3f})")
    x_le = brentq(lambda x: evaluate(x)["sm"] - sm_target, lo, hi, xtol=0.5)
    for x in np.linspace(lo, hi, 9):  # SM sweep for reporting / plots
        evaluate(x)
    r = evaluate(x_le)
    if r["overlap"]:
        raise AircraftLayoutError("payload bay at the empty CG overlaps the battery at the solved wing position")
    al, de, de_vlm, cl = trim(campaign, x_le, r["wing_z"], r["tail"], r["stations"], r["x_cg"], r["m"], v)
    d = AircraftDesign(
        campaign=campaign, wing_x_le_mm=float(x_le), wing_z_mm=r["wing_z"], tail=r["tail"],
        stations=r["stations"], mass_items=r["items"], mtow_kg=mtow, payload_kg=r["payload"],
        x_cg_mm=r["x_cg"], z_cg_mm=r["z_cg"], mac_mm=r["mac"], x_mac_le_mm=r["x_mac_le"], x_np_mm=r["x_np"],
        x_np_vlm_mm=r["x_vlm"], static_margin=r["sm"],
        static_margin_vlm=(r["x_vlm"] - r["x_cg"]) / r["mac"], trim_alpha_deg=al, trim_elevator_deg=de,
        trim_elevator_vlm_deg=de_vlm, cl_cruise=cl, sm_vs_lh=sorted(history))
    d.x_np_aerobuildup_mm = r["x_ab"]
    d.x_np_aerobuildup_nofus_mm = r["x_ab_nofus"]
    return d


def _with_dihedral(wing_asm, dihedral_deg: float):
    """Rotate starboard (+y) / port (-y) wing leaves about the root chord line (x axis) by +/- dihedral."""
    from build123d import Compound, Rot

    from cad.exporters import world_shape

    if abs(dihedral_deg) < 1e-9:
        return wing_asm
    groups = []
    for grp in wing_asm.children:
        leaves = []
        for leaf in grp.children:
            sgn = 1.0 if leaf.label.endswith("_Stbd") else -1.0
            # detach first: moving a leaf that still has a parent deep-copies the whole assembly tree
            moved = Rot(sgn * dihedral_deg, 0, 0) * world_shape(leaf)
            moved.label, moved.color = leaf.label, leaf.color
            leaves.append(moved)
        groups.append(Compound(children=leaves, label=grp.label))
    return Compound(children=groups, label=wing_asm.label)


def build_aircraft_assembly(design: AircraftDesign, wing_structure, component_boxes: bool = True):
    """Labelled full-aircraft compound: Wing (v0.14 structure), Fuselage, HorizontalTail, VerticalTail, Systems."""
    from build123d import Box, Color, Compound, Cylinder, Pos, Rot

    wing = Pos(design.wing_x_le_mm, 0, design.wing_z_mm) * _with_dihedral(wing_structure.assembly(label="Wing"),
                                                                         design.dihedral_deg)
    fus = build_fuselage(design.stations, former_x_mm=_former_x(design.stations))
    z_t = design.stations[-1].z_center_mm
    if design.tail_structure is not None:
        from engineering.analysis.tail_structure import tail_assembly

        ht, vt = tail_assembly(design.tail_structure, design)
    else:
        ht = build_htail(design.tail.htail, design.tail.x_htail_le_mm, z_t)
        vt = build_vtail(design.tail.vtail, design.tail.x_vtail_le_mm, z_t)
    children = [wing, fus, ht, vt]
    if component_boxes:
        sys_parts = []
        comp_color = {"propulsion": Color(0.60, 0.60, 0.65), "energy": Color(0.95, 0.80, 0.20),
                      "systems": Color(0.30, 0.75, 0.95), "payload": Color(0.90, 0.35, 0.55)}
        for it in design.mass_items:
            if it.group not in comp_color:
                continue
            if it.name == "Propeller":
                p = Pos(it.x_mm, 0, 0) * Rot(0, 90, 0) * Cylinder(190.0, 6.0)
            elif it.name == "Motor":
                p = Pos(it.x_mm, 0, 0) * Rot(0, 90, 0) * Cylinder(28.0, 55.0)
            else:
                box = {"ESC": (70, 40, 20), "Battery": (200, 90, 70), "Battery (fwd)": (100, 90, 70),
                       "Battery (aft)": (100, 90, 70), "Avionics": (100, 80, 40),
                       "Payload": (180, 100, 100)}.get(it.name)
                if box is None:
                    continue
                p = Pos(it.x_mm, 0, it.z_mm) * Box(*box)
            p.label, p.color = it.name.replace(" ", ""), comp_color[it.group]
            sys_parts.append(p)
        children.append(Compound(children=sys_parts, label="Systems"))
    return Compound(children=children, label="Aircraft")
