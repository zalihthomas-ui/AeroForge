"""Fuselage and empennage CAD for the whole-aircraft layout (v0.15).

Coordinates follow the wing modules: X aft from the fuselage nose, Y to
starboard, Z up, millimetres.

* Fuselage: elliptical stations lofted into an outer skin, hollowed by an
  inner loft `skin_thickness_mm` smaller, plus ring formers at the bay
  boundaries. The station table is produced by `fuselage_stations`, which sizes
  the cabin cross-section around the internal component boxes.
* Horizontal and vertical tail: NACA 4-digit symmetric sections (default
  NACA 0009 / 0010), split at the hinge line into a fixed surface and a
  movable elevator / rudder (separate solids, small hinge gap).

All solids are labelled and coloured for `cad.exporters.export_step_assembly`.
Tail and fuselage skins are solid thin shells; there is no internal tail
structure (spars/ribs) and no hinge hardware.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from build123d import Color, Compound, Part, Pos, Wire, loft, make_face

from agents.geometry.wing_structure import naca4_surfaces

FUSELAGE_COLOR = Color(0.80, 0.83, 0.87)
FORMER_COLOR = Color(0.55, 0.42, 0.30)
TAIL_COLOR = Color(0.85, 0.87, 0.90)
SURFACE_COLOR = Color(0.95, 0.55, 0.20)


@dataclass(frozen=True)
class FuselageStation:
    x_mm: float
    width_mm: float
    height_mm: float
    z_center_mm: float = 0.0


def fuselage_stations(cabin_width_mm: float, cabin_height_mm: float, cabin_start_mm: float,
                      cabin_end_mm: float, tail_end_mm: float, boom_diameter_mm: float = 40.0,
                      spinner_diameter_mm: float = 50.0) -> list[FuselageStation]:
    """Nose spinner -> constant cabin -> tapered transition -> tail boom (all elliptical)."""
    if not 0 < cabin_start_mm < cabin_end_mm < tail_end_mm:
        raise ValueError("need 0 < cabin start < cabin end < tail end")
    w, h = cabin_width_mm, cabin_height_mm
    trans_end = cabin_end_mm + 0.45 * (tail_end_mm - cabin_end_mm)
    stations = [
        FuselageStation(0.0, spinner_diameter_mm, spinner_diameter_mm),
        FuselageStation(0.35 * cabin_start_mm, 0.70 * w, 0.70 * h),
        FuselageStation(cabin_start_mm, w, h),
        FuselageStation(cabin_end_mm, w, h),
        FuselageStation(0.5 * (cabin_end_mm + trans_end), 0.55 * w, 0.55 * h, 0.12 * h),
        FuselageStation(trans_end, boom_diameter_mm, boom_diameter_mm, 0.20 * h),
        FuselageStation(tail_end_mm, 0.8 * boom_diameter_mm, 0.8 * boom_diameter_mm, 0.20 * h),
    ]
    return stations


def _ellipse_wire(st: FuselageStation, shrink: float = 0.0, n: int = 40) -> Wire:
    a = max(st.width_mm / 2.0 - shrink, 0.5)
    b = max(st.height_mm / 2.0 - shrink, 0.5)
    th = np.linspace(0.0, 2.0 * math.pi, n, endpoint=False)
    pts = [(st.x_mm, float(a * math.cos(t)), float(st.z_center_mm + b * math.sin(t))) for t in th]
    return Wire.make_polygon(pts, close=True)


def build_fuselage(stations: list[FuselageStation], skin_thickness_mm: float = 0.8,
                   former_x_mm: list[float] | None = None, former_thickness_mm: float = 3.0) -> Compound:
    """Hollow lofted fuselage skin plus ring formers; returns a labelled compound."""
    outer = loft([make_face(_ellipse_wire(s)) for s in stations], ruled=False)
    inner_st = [s for s in stations if min(s.width_mm, s.height_mm) > 4 * skin_thickness_mm]
    inner = loft([make_face(_ellipse_wire(s, skin_thickness_mm)) for s in inner_st], ruled=False)
    skin = outer - inner
    skin.label, skin.color = "FuselageSkin", FUSELAGE_COLOR
    parts = [skin]
    for i, x in enumerate(former_x_mm or []):
        xs = np.array([s.x_mm for s in stations])
        w = float(np.interp(x, xs, [s.width_mm for s in stations]))
        h = float(np.interp(x, xs, [s.height_mm for s in stations]))
        zc = float(np.interp(x, xs, [s.z_center_mm for s in stations]))
        st = FuselageStation(x, w, h, zc)
        ring_out = make_face(_ellipse_wire(st, skin_thickness_mm))
        ring_in = make_face(_ellipse_wire(st, skin_thickness_mm + 0.18 * min(w, h)))
        former = _extrude_x(ring_out, former_thickness_mm) - _extrude_x(ring_in, former_thickness_mm)
        former = Pos(-former_thickness_mm / 2.0, 0, 0) * former
        former.label, former.color = f"Former_{i + 1}", FORMER_COLOR
        parts.append(former)
    return Compound(children=parts, label="Fuselage")


def _extrude_x(face, t):
    from build123d import extrude

    return extrude(face, amount=t, dir=(1, 0, 0))


@dataclass(frozen=True)
class SurfaceGeometry:
    """A trapezoidal tail surface (one side for a symmetric htail, the full fin for a vtail)."""

    root_chord_mm: float
    tip_chord_mm: float
    span_mm: float  # semispan for the htail, height for the fin
    sweep_le_deg: float
    naca: str
    hinge_xc: float  # control-surface hinge line, fraction of local chord

    @property
    def area_mm2(self) -> float:
        return 0.5 * (self.root_chord_mm + self.tip_chord_mm) * self.span_mm

    @property
    def mac_mm(self) -> float:
        lam = self.tip_chord_mm / self.root_chord_mm
        return 2.0 / 3.0 * self.root_chord_mm * (1 + lam + lam * lam) / (1 + lam)


def tail_surface(area_mm2: float, aspect_ratio: float, taper: float, naca: str, hinge_xc: float,
                 sweep_le_deg: float = 0.0, both_sides: bool = True) -> SurfaceGeometry:
    """Planform from area, AR (full surface) and taper. `both_sides`: htail (area split over two halves)."""
    span_full = math.sqrt(area_mm2 * aspect_ratio)
    root = 2.0 * area_mm2 / (span_full * (1 + taper))
    span = span_full / 2.0 if both_sides else span_full
    return SurfaceGeometry(root, root * taper, span, sweep_le_deg, naca, hinge_xc)


def _section(naca: str, chord: float, x0: float, x1: float, n: int = 25) -> np.ndarray:
    """Closed (x/c, z/c) polygon of a NACA section between x0/c and x1/c, scaled by chord."""
    xc = 0.5 * (1 - np.cos(np.linspace(0.0, math.pi, n))) * (x1 - x0) + x0
    zu, zl = naca4_surfaces(naca, xc)
    pts = np.concatenate([np.column_stack([xc[::-1], zu[::-1]]), np.column_stack([xc[1:], zl[1:]])])
    if x1 >= 0.999:
        pts = pts[:-1] if np.allclose(pts[0], pts[-1]) else pts
    return pts * chord


def _surface_part(geo: SurfaceGeometry, x0: float, x1: float, place, label: str, color) -> Part:
    faces = []
    for eta in (0.0, 1.0):
        c = geo.root_chord_mm + (geo.tip_chord_mm - geo.root_chord_mm) * eta
        s = eta * geo.span_mm
        x_le = s * math.tan(math.radians(geo.sweep_le_deg))
        pts = _section(geo.naca, c, x0, x1)
        faces.append(make_face(Wire.make_polygon([place(x_le + px, s, pz) for px, pz in pts], close=True)))
    part = loft(faces)
    part.label, part.color = label, color
    return part


def build_htail(geo: SurfaceGeometry, x_le_mm: float, z_mm: float, gap: float = 0.01) -> Compound:
    """Horizontal tail: stabiliser + elevator on both sides."""
    parts = []
    for side, sgn in (("Stbd", 1.0), ("Port", -1.0)):
        def place(x, s, z, sgn=sgn):
            return (x_le_mm + x, sgn * s, z_mm + z)

        parts.append(_surface_part(geo, 0.0, geo.hinge_xc - gap / 2, place, f"Stabilizer_{side}", TAIL_COLOR))
        parts.append(_surface_part(geo, geo.hinge_xc + gap / 2, 1.0, place, f"Elevator_{side}", SURFACE_COLOR))
    return Compound(children=parts, label="HorizontalTail")


def build_vtail(geo: SurfaceGeometry, x_le_mm: float, z_root_mm: float, gap: float = 0.01) -> Compound:
    """Vertical tail: fin + rudder (fin span measured up from z_root)."""
    def place(x, s, z):
        return (x_le_mm + x, z, z_root_mm + s)

    fin = _surface_part(geo, 0.0, geo.hinge_xc - gap / 2, place, "Fin", TAIL_COLOR)
    rud = _surface_part(geo, geo.hinge_xc + gap / 2, 1.0, place, "Rudder", SURFACE_COLOR)
    return Compound(children=[fin, rud], label="VerticalTail")


def flap_effectiveness(cf_over_c: float) -> float:
    """Thin-airfoil flap effectiveness tau = d(alpha_0)/d(delta) for a plain flap of chord ratio cf/c.

    tau = 1 - (theta_f - sin theta_f) / pi with cos(theta_f) = 2 cf/c - 1 (Glauert / Anderson eq. 4.x).
    Real elevators are less effective (gap, viscosity); this is the ideal value.
    """
    th = math.acos(2.0 * cf_over_c - 1.0)
    return 1.0 - (th - math.sin(th)) / math.pi


def shell_volume_mm3(compound: Compound) -> float:
    return float(sum(s.volume for s in compound.solids()))
