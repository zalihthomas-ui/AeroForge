"""Parametric CAD of the 60 deg split-pin V6 defined by `EngineSpec`.

Everything is derived from `agents.powertrain.spec.EngineSpec` (bore, stroke,
rod length, compression ratio, cylinder axis angles, pin angles and axial
positions); this module only adds the proportions a drawing needs (journal
diameters, wall thicknesses, ...), collected in `V6CadProportions`.

Frame (same as EngineSpec): Z = crankshaft axis from the timing end (z=0) to
the flywheel, Y up, X to the right bank. Angles are measured from +Y towards
+X. A direction at angle ``a`` is ``(sin a, cos a, 0)``.

Parts and their local frames (what `pose` places):

* Crankshaft, Flywheel -- built in the engine frame at theta = 0; at crank
  angle theta every crank pin points along ``theta + pin_angle_deg``, i.e. the
  crank is rotated by ``-theta`` about Z.
* Piston_k, GudgeonPin_k -- origin at the gudgeon-pin centre, local +Y = up
  the cylinder axis, local Z = pin axis (parallel to the crank).
* Rod_k -- origin at the big-end centre, local +Y towards the small end
  (small-end centre at (0, rod_length, 0)), local Z = pin axis.

Kinematics are exact slider-crank: with phi = theta + pin - axis, the gudgeon
pin sits ``s = r cos(phi) + sqrt(l^2 - r^2 sin^2 phi)`` up the cylinder axis
from the crank centre, so a cylinder is at TDC (s = r + l) exactly when
``theta + pin == axis``, the EngineSpec convention.

Deliberate simplifications (representative, not production detail): no oil
galleries, water jackets, valves, cams, timing drive, bolts or fillets; the
block is one solid with simple bulkheads; the crank webs are flat plates with
a sector counterweight; the head combustion chamber is a cylindrical recess
sized so the CAD compression ratio equals the spec's; piston rings are
represented by their grooves only.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from build123d import (
    Box,
    Color,
    Compound,
    Cylinder,
    Location,
    Part,
    Polygon,
    Pos,
    Rot,
    Shape,
    extrude,
)
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.Extrema import Extrema_ExtFlag_MIN
from scipy.spatial import ConvexHull, cKDTree

from agents.powertrain.spec import EngineSpec

STEEL_DENSITY = 7850.0  # kg/m^3
ALUMINIUM_DENSITY = 2700.0
CAST_IRON_DENSITY = 7200.0


class V6CadError(ValueError):
    """Raised when the drawing proportions cannot fit the EngineSpec geometry."""


@dataclass(frozen=True)
class V6CadProportions:
    """Drawing proportions (mm) not defined by EngineSpec. Defaults suit the 3.0 L V6."""

    main_journal_dia: float = 60.0
    main_journal_width: float = 22.0
    crank_pin_dia: float = 50.0
    rod_width: float = 16.0  # big and small end; must fit the split-pin bank offset
    big_end_wall: float = 9.0
    small_end_wall: float = 6.0
    gudgeon_pin_dia: float = 22.0
    gudgeon_pin_bore: float = 13.0
    gudgeon_pin_length: float = 70.0
    shank_width: float = 22.0
    shank_pocket_depth: float = 5.0
    web_lobe_radius: float = 34.0
    counterweight_radius: float = 78.0
    counterweight_half_angle_deg: float = 65.0
    deck_height: float = 215.0  # crank centre to deck face along the cylinder axis
    head_gasket: float = 1.0  # piston-to-head clearance at TDC with a zero-deck block
    piston_skirt_below_pin: float = 20.0
    piston_radial_clearance: float = 0.05
    piston_inner_dia: float = 74.0
    crown_thickness: float = 8.0
    top_land: float = 6.0
    ring_grooves: tuple[float, ...] = (1.5, 1.5, 2.5)  # widths, top to bottom
    ring_land: float = 2.5
    ring_groove_depth: float = 3.5
    pin_boss_dia: float = 34.0
    bore_wall: float = 10.0  # liner/bank wall each side of the bore
    bank_low: float = 95.0  # bottom of the cylinder barrel, along the axis
    crankcase_cavity_radius: float = 100.0
    bulkhead_axial_gap: float = 1.0  # crank web to bulkhead face
    head_height: float = 80.0
    cam_cover_height: float = 30.0
    pan_depth: float = 110.0
    pan_wall: float = 3.0
    flange_dia: float = 90.0
    flange_length: float = 12.0
    flywheel_dia: float = 280.0
    flywheel_thickness: float = 25.0
    snout_dia: float = 35.0
    snout_length: float = 43.0


@dataclass
class V6Model:
    """Built parts in their local frames plus everything `pose` needs."""

    spec: EngineSpec
    prop: V6CadProportions
    crankshaft: Part
    flywheel: Part
    piston: Part
    gudgeon_pin: Part
    rod: Part
    block: Part
    heads: dict[str, Part]
    cam_covers: dict[str, Part]
    oil_pan: Part
    compression_height: float
    chamber_depth: float
    main_journal_z: list[float] = field(default_factory=list)


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def direction(angle_deg: float) -> np.ndarray:
    """Unit vector in the XY plane at `angle_deg` from +Y towards +X."""
    a = math.radians(angle_deg)
    return np.array([math.sin(a), math.cos(a), 0.0])


def _rot_z(beta_deg: float) -> np.ndarray:
    b = math.radians(beta_deg)
    m = np.eye(4)
    m[:2, :2] = [[math.cos(b), -math.sin(b)], [math.sin(b), math.cos(b)]]
    return m


def _transform(translation, beta_deg: float) -> np.ndarray:
    """4x4: rotate by beta about Z, then translate."""
    m = _rot_z(beta_deg)
    m[:3, 3] = translation
    return m


def to_location(m: np.ndarray) -> Location:
    """4x4 transform (rotation about Z + translation) -> build123d Location."""
    beta = math.degrees(math.atan2(m[1, 0], m[0, 0]))
    return Location((float(m[0, 3]), float(m[1, 3]), float(m[2, 3])), (0, 0, beta))


def _along_y(radius: float, y0: float, y1: float) -> Part:
    """Solid cylinder on the local Y axis from y0 to y1."""
    return Pos(0, (y0 + y1) / 2, 0) * (Rot(X=-90) * Cylinder(radius, y1 - y0))


def _along_z(radius: float, z0: float, z1: float, x: float = 0.0, y: float = 0.0) -> Part:
    return Pos(x, y, (z0 + z1) / 2) * Cylinder(radius, z1 - z0)


def _hull_polygon(points: np.ndarray) -> Polygon:
    hull = ConvexHull(points)
    return Polygon(*[tuple(points[i]) for i in hull.vertices], align=None)


def _circle_points(cx: float, cy: float, r: float, n: int = 48) -> np.ndarray:
    t = np.linspace(0, 2 * math.pi, n, endpoint=False)
    return np.column_stack([cx + r * np.sin(t), cy + r * np.cos(t)])


# ---------------------------------------------------------------------------
# kinematics
# ---------------------------------------------------------------------------
def piston_travel(spec: EngineSpec, cylinder_number: int, theta_deg: float) -> float:
    """Gudgeon-pin distance from the crank centre along the cylinder axis [mm]."""
    c = spec.cylinder(cylinder_number)
    r, l = spec.crank_radius_mm, spec.rod_length_mm
    phi = math.radians(theta_deg + c.pin_angle_deg - c.axis_angle_deg)
    return r * math.cos(phi) + math.sqrt(l * l - (r * math.sin(phi)) ** 2)


def crank_pin_centre(spec: EngineSpec, cylinder_number: int, theta_deg: float) -> np.ndarray:
    c = spec.cylinder(cylinder_number)
    p = spec.crank_radius_mm * direction(theta_deg + c.pin_angle_deg)
    p[2] = c.z_mm
    return p


def gudgeon_pin_centre(spec: EngineSpec, cylinder_number: int, theta_deg: float) -> np.ndarray:
    c = spec.cylinder(cylinder_number)
    p = piston_travel(spec, cylinder_number, theta_deg) * direction(c.axis_angle_deg)
    p[2] = c.z_mm
    return p


def pose(spec: EngineSpec, theta_deg: float) -> dict[str, np.ndarray]:
    """4x4 local->engine transforms of every moving part at crank angle `theta_deg`.

    Keys: ``Crankshaft``, ``Flywheel``, ``Piston_k``, ``GudgeonPin_k``, ``Rod_k``.
    """
    out = {"Crankshaft": _rot_z(-theta_deg), "Flywheel": _rot_z(-theta_deg)}
    for c in spec.cylinders:
        k = c.number
        g = gudgeon_pin_centre(spec, k, theta_deg)
        out[f"Piston_{k}"] = _transform(g, -c.axis_angle_deg)
        out[f"GudgeonPin_{k}"] = _transform(g, -c.axis_angle_deg)
        b = crank_pin_centre(spec, k, theta_deg)
        d = g - b
        out[f"Rod_{k}"] = _transform(b, -math.degrees(math.atan2(d[0], d[1])))
    return out


# ---------------------------------------------------------------------------
# parts
# ---------------------------------------------------------------------------
def _throw_pairs(spec: EngineSpec):
    """[(right cylinder, left cylinder)] sharing a split-pin throw, front to rear."""
    right = sorted((c for c in spec.cylinders if c.bank == "R"), key=lambda c: c.z_mm)
    out = []
    for r in right:
        partner = min((c for c in spec.cylinders if c.bank == "L"), key=lambda c: abs(c.z_mm - r.z_mm))
        out.append((r, partner))
    return out


def _crank_layout(spec: EngineSpec, p: V6CadProportions):
    """Axial layout: (pin spans, web spans, main journal centres)."""
    half = spec.bank_offset_mm / 2
    pairs = _throw_pairs(spec)
    spans = [(min(a.z_mm, b.z_mm) - half, max(a.z_mm, b.z_mm) + half) for a, b in pairs]
    gaps = [spans[i + 1][0] - spans[i][1] for i in range(len(spans) - 1)]
    web_t = (min(gaps) - p.main_journal_width) / 2
    if web_t < 8.0:
        raise V6CadError(f"crank webs would be {web_t:.1f} mm thick; reduce main_journal_width")
    mains = [spans[0][0] - web_t - p.main_journal_width / 2]
    mains += [(spans[i][1] + spans[i + 1][0]) / 2 for i in range(len(spans) - 1)]
    mains += [spans[-1][1] + web_t + p.main_journal_width / 2]
    return pairs, spans, web_t, mains


def _web(spec: EngineSpec, p: V6CadProportions, pin_angles: tuple[float, float], z0: float, t: float) -> Part:
    r = spec.crank_radius_mm
    pts = [_circle_points(0, 0, p.main_journal_dia / 2 + 6)]
    for a in pin_angles:
        d = direction(a)
        pts.append(_circle_points(r * d[0], r * d[1], p.web_lobe_radius))
    lobe = _hull_polygon(np.vstack(pts))
    mean = math.degrees(math.atan2(sum(direction(a)[0] for a in pin_angles),
                                   sum(direction(a)[1] for a in pin_angles)))
    arc = np.linspace(mean + 180 - p.counterweight_half_angle_deg, mean + 180 + p.counterweight_half_angle_deg, 40)
    cw_pts = np.vstack([[[0.0, 0.0]], [[p.counterweight_radius * math.sin(math.radians(a)),
                                        p.counterweight_radius * math.cos(math.radians(a))] for a in arc]])
    cw = _hull_polygon(np.vstack([cw_pts, _circle_points(0, 0, p.main_journal_dia / 2 + 6)]))
    return Pos(0, 0, z0) * (extrude(lobe, amount=t) + extrude(cw, amount=t))


def build_crankshaft(spec: EngineSpec, p: V6CadProportions) -> tuple[Part, list[float]]:
    pairs, spans, web_t, mains = _crank_layout(spec, p)
    half = spec.bank_offset_mm / 2
    shape = None
    for (a, b), (z0, z1) in zip(pairs, spans):
        for c in (a, b):
            d = spec.crank_radius_mm * direction(c.pin_angle_deg)
            pin = _along_z(p.crank_pin_dia / 2, c.z_mm - half, c.z_mm + half, d[0], d[1])
            shape = pin if shape is None else shape + pin
        angles = (a.pin_angle_deg, b.pin_angle_deg)
        shape += _web(spec, p, angles, z0 - web_t, web_t)
        shape += _web(spec, p, angles, z1, web_t)
    for zm in mains:
        shape += _along_z(p.main_journal_dia / 2, zm - p.main_journal_width / 2, zm + p.main_journal_width / 2)
    z_front = mains[0] - p.main_journal_width / 2
    z_rear = mains[-1] + p.main_journal_width / 2
    shape += _along_z(p.snout_dia / 2, z_front - p.snout_length, z_front)
    shape += _along_z(p.flange_dia / 2, z_rear, z_rear + p.flange_length)
    return shape, mains


def build_flywheel(p: V6CadProportions, z_flange_end: float) -> Part:
    disk = _along_z(p.flywheel_dia / 2, z_flange_end, z_flange_end + p.flywheel_thickness)
    recess = _along_z(p.flywheel_dia / 2 - 25, z_flange_end + p.flywheel_thickness - 8,
                      z_flange_end + p.flywheel_thickness)
    hub = _along_z(p.flange_dia / 2, z_flange_end, z_flange_end + p.flywheel_thickness)
    return disk - recess + hub


def build_piston(spec: EngineSpec, p: V6CadProportions, compression_height: float) -> Part:
    radius = spec.bore_mm / 2 - p.piston_radial_clearance
    crown = compression_height
    bottom = -p.piston_skirt_below_pin
    body = _along_y(radius, bottom, crown)
    body -= _along_y(p.piston_inner_dia / 2, bottom - 1, crown - p.crown_thickness)
    y = crown - p.top_land
    for w in p.ring_grooves:
        groove = _along_y(radius + 1, y - w, y) - _along_y(radius - p.ring_groove_depth, y - w - 1, y + 1)
        body -= groove
        y -= w + p.ring_land
    bosses = _along_z(p.pin_boss_dia / 2, -p.piston_inner_dia / 2 - 1, p.piston_inner_dia / 2 + 1)
    body += bosses & _along_y(radius - 1, bottom, crown)
    body -= _along_z(p.gudgeon_pin_dia / 2, -radius - 2, radius + 2)
    return body


def build_gudgeon_pin(p: V6CadProportions) -> Part:
    h = p.gudgeon_pin_length / 2
    return _along_z(p.gudgeon_pin_dia / 2, -h, h) - _along_z(p.gudgeon_pin_bore / 2, -h - 1, h + 1)


def build_rod(spec: EngineSpec, p: V6CadProportions) -> Part:
    l, w = spec.rod_length_mm, p.rod_width
    big_r = p.crank_pin_dia / 2 + p.big_end_wall
    small_r = p.gudgeon_pin_dia / 2 + p.small_end_wall
    y0, y1 = big_r * 0.7, l - small_r * 0.7
    shank = Pos(0, (y0 + y1) / 2, 0) * Box(p.shank_width, y1 - y0, w)
    pocket_len = (l - small_r) - big_r - 6
    pocket_y = (big_r + l - small_r) / 2
    for sgn in (1, -1):
        shank -= Pos(0, pocket_y, sgn * (w / 2 - p.shank_pocket_depth / 2 + 0.01)) * \
            Box(p.shank_width - 8, pocket_len, p.shank_pocket_depth + 0.02)
    rod = shank + _along_z(big_r, -w / 2, w / 2) + _along_z(small_r, -w / 2, w / 2, 0, l)
    rod -= _along_z(p.crank_pin_dia / 2, -w, w)
    rod -= _along_z(p.gudgeon_pin_dia / 2, -w, w, 0, l)
    return rod


def _bank_frame(shape: Part, axis_angle_deg: float) -> Part:
    """Place a part built in bank-local coords (local +Y = cylinder axis)."""
    return Rot(Z=-axis_angle_deg) * shape


def _bank_z_range(spec: EngineSpec, bank: str, p: V6CadProportions) -> tuple[float, float]:
    zs = [c.z_mm for c in spec.cylinders if c.bank == bank]
    half = spec.bore_mm / 2 + p.bore_wall
    return min(zs) - half, max(zs) + half


def build_block(spec: EngineSpec, p: V6CadProportions, mains: list[float]) -> Part:
    zf = mains[0] - p.main_journal_width / 2 - 10
    zr = mains[-1] + p.main_journal_width / 2 + 10
    width = 2 * (p.crankcase_cavity_radius + 25)
    case = Pos(0, (120 - 75) / 2, (zf + zr) / 2) * Box(width, 195, zr - zf)
    block = case
    for bank in ("R", "L"):
        axis = next(c.axis_angle_deg for c in spec.cylinders if c.bank == bank)
        z0, z1 = _bank_z_range(spec, bank, p)
        half_w = spec.bore_mm / 2 + p.bore_wall
        barrel = Pos(0, (p.bank_low + p.deck_height) / 2, (z0 + z1) / 2) * \
            Box(2 * half_w, p.deck_height - p.bank_low, z1 - z0)
        block += _bank_frame(barrel, axis)
    # crankcase cavity between the main-bearing bulkheads, open at the bottom for the pan
    bulk = [(zm - p.main_journal_width / 2 + p.bulkhead_axial_gap, zm + p.main_journal_width / 2 - p.bulkhead_axial_gap)
            for zm in mains]
    for (_, a), (b, _) in zip(bulk[:-1], bulk[1:]):
        block -= _along_z(p.crankcase_cavity_radius, a, b)
    block -= _along_z(p.main_journal_dia / 2, zf - 1, zr + 1)
    for c in spec.cylinders:
        bore = Pos(0, 0, c.z_mm) * _along_y(spec.bore_mm / 2, p.bank_low - 15.0, p.deck_height + 1)
        block -= _bank_frame(bore, c.axis_angle_deg)
    return block


def build_head(spec: EngineSpec, p: V6CadProportions, bank: str, chamber_depth: float) -> tuple[Part, Part]:
    axis = next(c.axis_angle_deg for c in spec.cylinders if c.bank == bank)
    z0, z1 = _bank_z_range(spec, bank, p)
    half_w = spec.bore_mm / 2 + p.bore_wall
    y0 = p.deck_height + p.head_gasket
    head = Pos(0, y0 + p.head_height / 2, (z0 + z1) / 2) * Box(2 * half_w, p.head_height, z1 - z0)
    for c in spec.cylinders:
        if c.bank == bank:
            head -= Pos(0, 0, c.z_mm) * _along_y(spec.bore_mm / 2, y0 - 1, y0 + chamber_depth)
    cover = Pos(0, y0 + p.head_height + p.cam_cover_height / 2, (z0 + z1) / 2) * \
        Box(2 * half_w - 14, p.cam_cover_height, z1 - z0 - 14)
    return _bank_frame(head, axis), _bank_frame(cover, axis)


def build_oil_pan(p: V6CadProportions, mains: list[float]) -> Part:
    zf = mains[0] - p.main_journal_width / 2 - 10
    zr = mains[-1] + p.main_journal_width / 2 + 10
    w = 2 * (p.crankcase_cavity_radius + 15)
    outer = Pos(0, -75 - p.pan_depth / 2, (zf + zr) / 2) * Box(w, p.pan_depth, zr - zf)
    inner = Pos(0, -75 - p.pan_depth / 2 + p.pan_wall / 2 + 0.01, (zf + zr) / 2) * \
        Box(w - 2 * p.pan_wall, p.pan_depth - p.pan_wall + 0.02, zr - zf - 2 * p.pan_wall)
    return outer - inner


def build_v6(spec: EngineSpec | None = None, proportions: V6CadProportions | None = None) -> V6Model:
    """Build every part of the V6 from `spec` (default EngineSpec())."""
    spec = spec or EngineSpec()
    p = proportions or V6CadProportions()
    if p.rod_width > spec.bank_offset_mm:
        raise V6CadError(f"rod_width {p.rod_width} mm exceeds the split-pin offset {spec.bank_offset_mm} mm")
    compression_height = p.deck_height - (spec.crank_radius_mm + spec.rod_length_mm)
    if compression_height < sum(p.ring_grooves) + p.top_land + p.pin_boss_dia / 2:
        raise V6CadError(f"deck_height leaves only {compression_height:.1f} mm compression height")
    # chamber volume = clearance volume - gasket volume (zero-deck block, flat crown)
    area = math.pi / 4 * spec.bore_mm**2
    chamber_depth = (spec.clearance_volume_m3 * 1e9 - area * p.head_gasket) / area
    crank, mains = build_crankshaft(spec, p)
    z_flange_end = mains[-1] + p.main_journal_width / 2 + p.flange_length
    heads, covers = {}, {}
    for bank in ("R", "L"):
        heads[bank], covers[bank] = build_head(spec, p, bank, chamber_depth)
    return V6Model(
        spec=spec, prop=p, crankshaft=crank, flywheel=build_flywheel(p, z_flange_end),
        piston=build_piston(spec, p, compression_height), gudgeon_pin=build_gudgeon_pin(p),
        rod=build_rod(spec, p), block=build_block(spec, p, mains), heads=heads, cam_covers=covers,
        oil_pan=build_oil_pan(p, mains), compression_height=compression_height,
        chamber_depth=chamber_depth, main_journal_z=mains)


# ---------------------------------------------------------------------------
# assembly, masses, checks
# ---------------------------------------------------------------------------
COLORS = {
    "Block": Color(0.55, 0.57, 0.60), "Heads": Color(0.70, 0.74, 0.80), "CamCovers": Color(0.75, 0.15, 0.15),
    "OilPan": Color(0.25, 0.27, 0.30), "Crankshaft": Color(0.80, 0.80, 0.82), "Flywheel": Color(0.35, 0.36, 0.40),
    "Pistons": Color(0.85, 0.86, 0.88), "GudgeonPins": Color(0.85, 0.70, 0.30), "Rods": Color(0.45, 0.47, 0.52),
}


def _placed(shape: Shape, m: np.ndarray, label: str, group: str) -> Shape:
    # plain Part: primitives (e.g. a cam cover that is just a Box) keep their
    # subclass otherwise, which the per-part STEP exporter cannot re-wrap
    s = Part(shape.moved(to_location(m)).wrapped)
    s.label, s.color = label, COLORS[group]
    return s


def assembly(model: V6Model, theta_deg: float = 0.0, label: str = "Engine") -> Compound:
    """Labelled, coloured assembly: Engine > Block/Heads/.../Pistons/Rods at crank angle theta."""
    t = pose(model.spec, theta_deg)
    eye = np.eye(4)
    groups: dict[str, list[Shape]] = {g: [] for g in COLORS}
    groups["Block"].append(_placed(model.block, eye, "Block", "Block"))
    for bank in ("R", "L"):
        groups["Heads"].append(_placed(model.heads[bank], eye, f"Head_{bank}", "Heads"))
        groups["CamCovers"].append(_placed(model.cam_covers[bank], eye, f"CamCover_{bank}", "CamCovers"))
    groups["OilPan"].append(_placed(model.oil_pan, eye, "OilPan", "OilPan"))
    groups["Crankshaft"].append(_placed(model.crankshaft, t["Crankshaft"], "Crankshaft", "Crankshaft"))
    groups["Flywheel"].append(_placed(model.flywheel, t["Flywheel"], "Flywheel", "Flywheel"))
    for c in model.spec.cylinders:
        k = c.number
        groups["Pistons"].append(_placed(model.piston, t[f"Piston_{k}"], f"Piston_{k}", "Pistons"))
        groups["GudgeonPins"].append(_placed(model.gudgeon_pin, t[f"GudgeonPin_{k}"], f"GudgeonPin_{k}", "GudgeonPins"))
        groups["Rods"].append(_placed(model.rod, t[f"Rod_{k}"], f"Rod_{k}", "Rods"))
    return Compound(children=[Compound(children=v, label=g) for g, v in groups.items()], label=label)


def part_masses_kg(model: V6Model) -> dict[str, float]:
    """CAD volume x density for the moving parts (steel crank/rods/pins/flywheel, Al pistons)."""
    v = lambda s: s.volume * 1e-9  # noqa: E731  mm^3 -> m^3
    return {
        "crankshaft": v(model.crankshaft) * STEEL_DENSITY,
        "flywheel": v(model.flywheel) * STEEL_DENSITY,
        "piston": v(model.piston) * ALUMINIUM_DENSITY,
        "gudgeon_pin": v(model.gudgeon_pin) * STEEL_DENSITY,
        "rod": v(model.rod) * STEEL_DENSITY,
    }


def rod_small_end_fraction(model: V6Model) -> float:
    """Two-point equivalent: share of rod mass at the small end = CG distance from big end / l."""
    return float(model.rod.center().Y) / model.spec.rod_length_mm


def reciprocating_mass_kg(model: V6Model) -> float:
    """Piston + gudgeon pin + small-end share of the rod (rings not modelled)."""
    m = part_masses_kg(model)
    return m["piston"] + m["gudgeon_pin"] + rod_small_end_fraction(model) * m["rod"]


def min_distance(a: Shape, b: Shape) -> float:
    """Minimum distance between two shapes [mm] (0 if they touch or overlap).

    OCC BRepExtrema in min-only, multithreaded mode: ~4x faster than
    Shape.distance_to for these curved parts, same value.
    """
    d = BRepExtrema_DistShapeShape()
    d.LoadS1(a.wrapped)
    d.LoadS2(b.wrapped)
    d.SetFlag(Extrema_ExtFlag_MIN)
    d.SetMultiThread(True)
    d.Perform()
    if not d.IsDone():
        raise V6CadError("distance computation failed")
    return float(d.Value())


def bdc_angle(spec: EngineSpec, cylinder_number: int) -> float:
    return (spec.cylinder(cylinder_number).firing_angle_deg + 180.0) % 720.0


def piston_counterweight_clearance(model: V6Model) -> dict[int, float]:
    """Min distance [mm] from each piston (at its BDC) to the crankshaft (webs/counterweights)."""
    out = {}
    for c in model.spec.cylinders:
        th = bdc_angle(model.spec, c.number)
        t = pose(model.spec, th)
        piston = model.piston.moved(to_location(t[f"Piston_{c.number}"]))
        crank = model.crankshaft.moved(to_location(t["Crankshaft"]))
        out[c.number] = min_distance(piston, crank)
    return out


def surface_points(shape: Shape, spacing_mm: float = 1.0, seed: int = 0) -> np.ndarray:
    """Points sampled on the surface of `shape`, about one per spacing^2 of area.

    Tessellates the B-rep (0.05 mm chord tolerance) and samples each triangle
    in proportion to its area, so flat faces are covered as densely as curved ones.
    """
    verts, tris = shape.tessellate(0.05, 0.1)
    v = np.array([[q.X, q.Y, q.Z] for q in verts])
    t = np.array(tris)
    a, b, c = v[t[:, 0]], v[t[:, 1]], v[t[:, 2]]
    area = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    n = np.maximum(1, np.ceil(area / spacing_mm**2)).astype(int)
    rng = np.random.default_rng(seed)
    idx = np.repeat(np.arange(len(t)), n)
    r1, r2 = rng.random(len(idx)), rng.random(len(idx))
    flip = r1 + r2 > 1
    r1[flip], r2[flip] = 1 - r1[flip], 1 - r2[flip]
    pts = a[idx] + r1[:, None] * (b[idx] - a[idx]) + r2[:, None] * (c[idx] - a[idx])
    return np.vstack([v, pts])


def rod_block_clearance(model: V6Model, step_deg: float = 5.0, block_spacing_mm: float = 1.5,
                        rod_spacing_mm: float = 2.0, search_mm: float = 25.0, exact_check: int = 3) -> dict:
    """Min rod-to-block clearance over a 720 deg cycle.

    Every `step_deg` every rod's sampled surface is posed and queried against a
    KD-tree of the block's sampled surface; the sampled minimum over-estimates
    the true gap by at most about the point spacing. Gaps above `search_mm` are
    not resolved (reported as inf). The `exact_check` tightest (cylinder, angle)
    samples are then re-measured with the exact B-rep distance, which is what is
    reported as ``min_clearance_mm``. (An exact B-rep distance at every sample
    gives the same answer but takes ~10 min instead of ~30 s.)
    """
    tree = cKDTree(surface_points(model.block, block_spacing_mm))
    rod_pts = surface_points(model.rod, rod_spacing_mm)
    rod_h = np.hstack([rod_pts, np.ones((len(rod_pts), 1))])
    samples = []
    for th in np.arange(0.0, 720.0, step_deg):
        t = pose(model.spec, float(th))
        for c in model.spec.cylinders:
            pts = (rod_h @ t[f"Rod_{c.number}"].T)[:, :3]
            d, _ = tree.query(pts, k=1, distance_upper_bound=search_mm, workers=-1)
            samples.append((float(d.min()), c.number, float(th)))
    samples.sort()
    exact = []
    for _, k, th in samples[:exact_check]:
        rod = model.rod.moved(to_location(pose(model.spec, th)[f"Rod_{k}"]))
        exact.append((min_distance(rod, model.block), k, th))
    exact.sort()
    return {"min_clearance_mm": exact[0][0], "cylinder": exact[0][1], "theta_deg": exact[0][2],
            "sampled_min_mm": samples[0][0], "n_samples": len(samples), "exact_checked": exact}


def geometric_compression_ratio(model: V6Model) -> float:
    """(swept + gasket + chamber) / (gasket + chamber) from the CAD dimensions."""
    area = math.pi / 4 * model.spec.bore_mm**2
    clearance = area * (model.prop.head_gasket + model.chamber_depth)
    return (area * model.spec.stroke_mm + clearance) / clearance
