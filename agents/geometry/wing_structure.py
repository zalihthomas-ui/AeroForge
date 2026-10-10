"""Complete wing structure CAD: ribs, spars, box covers and leading/trailing-edge skin.

Turns the sized wing box of the v0.14 campaign (`agents/structures/wing_box.py`)
into a manufacturable-looking assembly of separate solids, so the design ends
as real geometry rather than a set of thicknesses:

* front and rear spar webs at `front_spar_xc` / `rear_spar_xc`, full local
  airfoil depth, thickness stepped per bay (the sized `t_web`);
* upper and lower box covers between the spars, following the true airfoil
  surface, thickness stepped per bay (the sized `t_cap`);
* ribs at every bay boundary (the FE model's rib stations), full airfoil
  profile, `rib_thickness_mm` thick;
* a non-structural leading-edge skin (nose to front spar) and trailing-edge
  skins (rear spar to `te_skin_end_xc`), `skin_thickness_mm` thick.

Conventions follow `agents/geometry/wing.py`: X chordwise (LE at 0, unswept),
Y spanwise (root at 0), Z up; the half wing is mirrored about the XZ plane.

With `details` (v0.16, `StructureDetails`) the joints are modelled too:
C-channel spars (flanges riveted to the covers, rivets as separate solids at the
designed pitch), bonded angle stringers per bay (run-outs at ribs), and ribs
inset under the skin, split at the spar webs, with stringer mouseholes,
spar-flange notches, flanged lightening holes and bonded rib flanges.

Honest limits: covers are offset vertically (not along the surface normal);
without `details` parts touch/overlap by up to one skin thickness at joints and
no fasteners, flanges or bonding lands are modelled; the trailing-edge skin
stops short of the sharp trailing edge, leaving it open; adhesive layers are
not drawn (bonding lands are the stringer/rib-flange contact faces). The structural analysis idealises this box as a rectangle at
the thinner spar depth (conservative), while this CAD keeps the true airfoil
shape. Mass is from solid volumes x density.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field

import numpy as np
from build123d import (
    Box,
    Circle,
    Color,
    Compound,
    Cylinder,
    Face,
    Part,
    Plane,
    Pos,
    Rot,
    Wire,
    extrude,
    loft,
    make_face,
    mirror,
)

AL_DENSITY_KG_M3 = 2700.0
SKIN_DENSITY_KG_M3 = 1600.0  # light glass/epoxy, as in agents/geometry/wing.py

# Assembly-tree names and display colours per component group (exported to STEP).
GROUP_LABELS = {"ribs": "Ribs", "spars": "Spars", "box covers": "BoxCovers",
                "leading-edge skin": "LeadingEdgeSkin", "trailing-edge skin": "TrailingEdgeSkin",
                "spar flanges": "SparFlanges", "stringers": "Stringers", "rib flanges": "RibFlanges",
                "fasteners": "Fasteners"}
GROUP_COLORS = {"ribs": Color(0.40, 0.73, 0.42), "spars": Color(1.00, 0.70, 0.00),
                "box covers": Color(0.31, 0.76, 0.97), "leading-edge skin": Color(0.75, 0.78, 0.82),
                "trailing-edge skin": Color(0.62, 0.65, 0.70), "spar flanges": Color(1.00, 0.55, 0.10),
                "stringers": Color(0.85, 0.35, 0.85), "rib flanges": Color(0.25, 0.60, 0.30),
                "fasteners": Color(0.95, 0.95, 0.95)}
RIVET_DENSITY_KG_M3 = 2750.0  # 2117-T4


class WingStructureError(ValueError):
    """Raised for inconsistent structure inputs."""


def naca4_surfaces(naca: str, x_c: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Upper and lower surface z/c of a NACA 4-digit section at the given x/c (closed TE)."""
    m = int(naca[0]) / 100.0
    p = int(naca[1]) / 10.0
    t = int(naca[2:]) / 100.0
    x = np.asarray(x_c, dtype=float)
    yt = 5 * t * (0.2969 * np.sqrt(x) - 0.1260 * x - 0.3516 * x**2 + 0.2843 * x**3 - 0.1036 * x**4)
    if m == 0 or p == 0:
        yc = np.zeros_like(x)
        dyc = np.zeros_like(x)
    else:
        yc = np.where(x < p, m / p**2 * (2 * p * x - x**2), m / (1 - p) ** 2 * (1 - 2 * p + 2 * p * x - x**2))
        dyc = np.where(x < p, 2 * m / p**2 * (p - x), 2 * m / (1 - p) ** 2 * (p - x))
    th = np.arctan(dyc)
    xu, zu = x - yt * np.sin(th), yc + yt * np.cos(th)
    xl, zl = x + yt * np.sin(th), yc - yt * np.cos(th)
    # resample both surfaces back onto the requested x/c stations
    return np.interp(x, xu, zu), np.interp(x, xl, zl)


def _cosine(a: float, b: float, n: int) -> np.ndarray:
    s = 0.5 * (1 - np.cos(np.linspace(0, math.pi, n)))
    return a + (b - a) * s


def _face(points_xz: np.ndarray, y: float) -> Face:
    pts = [(float(px), y, float(pz)) for px, pz in points_xz]
    return make_face(Wire.make_polygon(pts, close=True))


@dataclass
class StructureDetails:
    """Joint-level detail (v0.16): stringers per bay, spar flanges, rivets, rib flanges, flanged holes.

    Per-bay lists run root -> tip like `WingStructureSpec.t_cap_mm` (which then is the SKIN gauge).
    """

    stringers_per_bay: list[int]
    stringer_leg_mm: list[float]
    stringer_t_mm: list[float]
    spar_flange_width_mm: float = 10.0
    rivet_diameter_mm: float = 2.4
    rivet_pitch_mm: float = 18.0
    rib_flange_width_mm: float = 6.0
    mousehole_clearance_mm: float = 1.0
    hole_radius_depth_ratio: float = 0.20  # flanged lightening hole radius / local box depth
    hole_lip_mm: float = 2.5  # flange (lip) height of the lightening holes
    spar_slot_clearance_mm: float = 0.4
    max_rivets_per_line: int | None = None  # thin the rivet rows for previews (None = all)


@dataclass
class WingStructureSpec:
    """Planform + sized box thickness (mm). `bay_edges_mm` root -> tip on one semispan."""

    semispan_mm: float
    root_chord_mm: float
    tip_chord_mm: float
    naca: str
    bay_edges_mm: list[float]
    t_cap_mm: list[float]
    t_web_mm: list[float]
    front_spar_xc: float = 0.20
    rear_spar_xc: float = 0.60
    rib_thickness_mm: float = 1.0
    rib_lightening_holes: bool = True
    skin_thickness_mm: float = 0.5
    te_skin_end_xc: float = 0.95
    n_profile: int = 41
    sweep_le_deg: float = 0.0  # leading-edge sweep (fins); sections are sheared aft, not rotated
    details: StructureDetails | None = None

    def chord(self, y: float) -> float:
        return self.root_chord_mm + (self.tip_chord_mm - self.root_chord_mm) * y / self.semispan_mm

    def x_le(self, y: float) -> float:
        return y * math.tan(math.radians(self.sweep_le_deg))

    def validate(self) -> None:
        n = len(self.t_cap_mm)
        if len(self.t_web_mm) != n or len(self.bay_edges_mm) != n + 1:
            raise WingStructureError("need one t_cap / t_web per bay and n_bays + 1 bay edges.")
        if not 0 < self.front_spar_xc < self.rear_spar_xc < self.te_skin_end_xc < 1:
            raise WingStructureError("need 0 < front spar < rear spar < TE skin end < 1 (x/c).")
        if abs(self.bay_edges_mm[0]) > 1e-9 or abs(self.bay_edges_mm[-1] - self.semispan_mm) > 1e-6:
            raise WingStructureError("bay edges must run from the root (0) to the tip (semispan).")


@dataclass
class WingStructure:
    """Half-wing solids by component group, plus a mirrored full-wing assembly."""

    spec: WingStructureSpec
    parts: dict[str, list[Part]] = field(default_factory=dict)  # group -> solids (half wing)
    densities: dict[str, float] = field(default_factory=dict)

    def volumes_mm3(self) -> dict[str, float]:
        return {g: 2.0 * sum(float(p.volume) for p in ps) for g, ps in self.parts.items()}

    def masses_kg(self) -> dict[str, float]:
        vol = self.volumes_mm3()
        return {g: vol[g] * 1e-9 * self.densities[g] for g in vol}

    def full_wing(self) -> dict[str, Compound]:
        """Both halves of every group as one labelled, coloured compound per group.

        The built half wing lies on +Y, which is starboard for this frame (X aft,
        Z up); its mirror image is the port half. Every solid keeps a readable
        name (e.g. ``Rib_3_Stbd``) so CAD tools show a meaningful assembly tree.
        """
        out = {}
        for g, ps in self.parts.items():
            if not ps:  # e.g. no stringers in a thin tail box: no empty compound in the tree
                continue
            solids = []
            for p in ps:
                base = p.label or g
                stbd = copy.copy(p)
                stbd.label, stbd.color = f"{base}_Stbd", GROUP_COLORS[g]
                sols = p.solids()
                # a multi-solid leaf (rivet row, rib flanges) is mirrored solid by solid: mirroring the
                # compound in one go leaves it with a zero (orientation-cancelled) volume in GProp
                port = (Compound([mirror(q, about=Plane.XZ) for q in sols]) if len(sols) > 1
                        else mirror(p, about=Plane.XZ))
                port.label, port.color = f"{base}_Port", GROUP_COLORS[g]
                solids += [stbd, port]
            out[g] = Compound(children=solids, label=GROUP_LABELS[g])
        return out

    def assembly(self, label: str = "Wing") -> Compound:
        """The full wing as a named assembly: wing -> component group -> part."""
        return Compound(children=list(self.full_wing().values()), label=label)


def _section(spec: WingStructureSpec, y: float, x0: float, x1: float, t: float, upper: bool, n: int) -> Face:
    """Thin band following one surface between x0/c and x1/c, offset inward by t (vertical)."""
    c = spec.chord(y)
    xc = np.linspace(x0, x1, n)
    zu, zl = naca4_surfaces(spec.naca, xc)
    z = (zu if upper else zl) * c
    inner = z - t if upper else z + t
    pts = np.concatenate([np.column_stack([xc * c, z]), np.column_stack([xc[::-1] * c, inner[::-1]])])
    pts[:, 0] += spec.x_le(y)
    return _face(pts, y)


def _nose_section(spec: WingStructureSpec, y: float, t: float, n: int) -> Face:
    """Leading-edge skin band: upper surface at the front spar -> nose -> lower surface, offset along the normal."""
    c = spec.chord(y)
    xc = _cosine(0.0, spec.front_spar_xc, n)
    zu, zl = naca4_surfaces(spec.naca, xc)
    outer = np.concatenate([np.column_stack([xc[::-1], zu[::-1]]), np.column_stack([xc[1:], zl[1:]])]) * c
    d = np.gradient(outer, axis=0)
    normal = np.column_stack([d[:, 1], -d[:, 0]])  # points inward for this (clockwise) traversal
    normal /= np.linalg.norm(normal, axis=1, keepdims=True)
    inner = outer + t * normal
    pts = np.concatenate([outer, inner[::-1]])
    pts[:, 0] += spec.x_le(y)
    return _face(pts, y)


def _web_section(spec: WingStructureSpec, y: float, xc_spar: float, t: float, skin: float) -> Face:
    c = spec.chord(y)
    zu, zl = naca4_surfaces(spec.naca, np.array([xc_spar]))
    x = xc_spar * c + spec.x_le(y)
    top, bot = zu[0] * c - skin, zl[0] * c + skin
    return _face(np.array([[x - t / 2, bot], [x + t / 2, bot], [x + t / 2, top], [x - t / 2, top]]), y)


def _band(spec: WingStructureSpec, y: float, x0_mm: float, x1_mm: float, d0: float, d1: float, upper: bool,
          n: int) -> Face:
    """Band under one surface between chordwise x0..x1 [mm from the local LE], depth d0..d1 below the surface."""
    c = spec.chord(y)
    xc = np.linspace(x0_mm / c, x1_mm / c, n)
    zu, zl = naca4_surfaces(spec.naca, xc)
    z = (zu if upper else zl) * c
    sgn = -1.0 if upper else 1.0
    pts = np.concatenate([np.column_stack([xc * c, z + sgn * d0]), np.column_stack([xc[::-1] * c, (z + sgn * d1)[::-1]])])
    pts[:, 0] += spec.x_le(y)
    return _face(pts, y)


def _blade(spec: WingStructureSpec, y: float, x_mm: float, t: float, d0: float, d1: float, upper: bool) -> Face:
    """Vertical leg (thickness t, centred on x_mm) from depth d0 to d1 under one surface."""
    c = spec.chord(y)
    zu, zl = naca4_surfaces(spec.naca, np.array([x_mm / c]))
    z = (zu[0] if upper else zl[0]) * c
    sgn = -1.0 if upper else 1.0
    x = x_mm + spec.x_le(y)
    za, zb = z + sgn * d0, z + sgn * d1
    return _face(np.array([[x - t / 2, za], [x + t / 2, za], [x + t / 2, zb], [x - t / 2, zb]]), y)


def stringer_positions_mm(spec: WingStructureSpec, bay: int, c: float) -> list[float]:
    """Chordwise centres [mm] of the bay's stringers: uniform pitch between the spar webs."""
    n = spec.details.stringers_per_bay[bay]
    f, r = spec.front_spar_xc * c, spec.rear_spar_xc * c
    return [f + (r - f) * (i + 1) / (n + 1) for i in range(n)]


def _rib_profile(spec: WingStructureSpec, c: float, n: int) -> np.ndarray:
    """Closed rib outline (x, z) in mm for local chord c."""
    xc = _cosine(0.0, 1.0, n)
    zu, zl = naca4_surfaces(spec.naca, xc)
    return np.concatenate([np.column_stack([xc[::-1], zu[::-1]]), np.column_stack([xc[1:-1], zl[1:-1]])]) * c


def _rib_holes(spec: WingStructureSpec, c: float) -> list[tuple[float, float, float]]:
    """Lightening holes as (x, z, radius) in mm: two round holes in the box, 55 % of local depth."""
    if not spec.rib_lightening_holes:
        return []
    holes = []
    for frac in (0.3, 0.7):
        xh = spec.front_spar_xc + frac * (spec.rear_spar_xc - spec.front_spar_xc)
        zu_h, zl_h = naca4_surfaces(spec.naca, np.array([xh]))
        depth = (zu_h[0] - zl_h[0]) * c
        holes.append((xh * c, 0.5 * (zu_h[0] + zl_h[0]) * c, 0.275 * depth))
    return holes


def _rib_bays(spec: WingStructureSpec, y: float) -> list[int]:
    edges = spec.bay_edges_mm
    i = int(np.argmin(np.abs(np.asarray(edges) - y)))
    return [b for b in (i - 1, i) if 0 <= b < len(spec.t_cap_mm)]


def detailed_rib_holes(spec: WingStructureSpec, y: float) -> list[tuple[float, float, float]]:
    """Flanged lightening holes (x, z, r) [mm] of the detailed rib at station y.

    Holes sit in the centres of the two widest gaps between the spar flanges and the stringers, so the
    mouseholes never cut into them; the radius is capped to leave a >= 2 mm ligament to every cutout.
    """
    det = spec.details
    c = spec.chord(y)
    bays = _rib_bays(spec, y)
    t_cov = max(spec.t_cap_mm[b] for b in bays)
    f, r_sp = spec.front_spar_xc * c, spec.rear_spar_xc * c
    edges = [(f, f + det.spar_flange_width_mm + 0.5)]
    for b in bays:
        hw = det.stringer_leg_mm[b] / 2 + det.mousehole_clearance_mm
        edges += [(xm - hw, xm + hw) for xm in stringer_positions_mm(spec, b, c)]
    edges.append((r_sp - det.spar_flange_width_mm - 0.5, r_sp))
    edges.sort()
    gaps = [(edges[i][1], edges[i + 1][0]) for i in range(len(edges) - 1) if edges[i + 1][0] > edges[i][1]]
    gaps = sorted(gaps, key=lambda g: g[1] - g[0], reverse=True)[:2]
    holes = []
    for g0, g1 in sorted(gaps):
        xh = 0.5 * (g0 + g1)
        zu_h, zl_h = naca4_surfaces(spec.naca, np.array([xh / c]))
        depth = (zu_h[0] - zl_h[0]) * c
        r = min(det.hole_radius_depth_ratio * depth, 0.5 * (g1 - g0) - 2.0, 0.5 * depth - t_cov - 2.0)
        if r >= 2.0:
            holes.append((xh, 0.5 * (zu_h[0] + zl_h[0]) * c, r))
    return holes


def _detailed_rib(spec: WingStructureSpec, y: float, t: float, n: int) -> tuple[Part, list[Part]]:
    """Rib inset under the skin, split at the spar webs, notched for stringers and spar flanges, flanged holes.

    Returns (rib web, [rib flanges + hole lips]).
    """
    det = spec.details
    c = spec.chord(y)
    bays = _rib_bays(spec, y)
    t_cov = max(spec.t_cap_mm[b] for b in bays)
    t_web = max(spec.t_web_mm[b] for b in bays)
    sk = spec.skin_thickness_mm
    xc = _cosine(0.0, 1.0, n)
    zu, zl = naca4_surfaces(spec.naca, xc)
    inset = np.where((xc >= spec.front_spar_xc) & (xc <= spec.rear_spar_xc), t_cov, sk)
    prof = np.concatenate([np.column_stack([xc[::-1], zu[::-1] * c - inset[::-1]]),
                           np.column_stack([xc[1:-1], zl[1:-1] * c + inset[1:-1]])])
    prof[: n, 0] *= c
    prof[n:, 0] *= c
    keep = prof[:, 0] <= spec.te_skin_end_xc * c  # rib ends where the TE skin ends
    prof = prof[keep]
    y0 = min(max(y - t / 2, 0.0), spec.semispan_mm - t)
    rib = extrude(_face(prof, y0), amount=t, dir=(0, 1, 0))
    cutters = []
    for xs in (spec.front_spar_xc, spec.rear_spar_xc):
        zu_s, zl_s = naca4_surfaces(spec.naca, np.array([xs]))
        zc = 0.5 * (zu_s[0] + zl_s[0]) * c
        dz = (zu_s[0] - zl_s[0]) * c
        cutters.append(Pos(xs * c, y0 + t / 2, zc) * Box(t_web + det.spar_slot_clearance_mm, 3 * t, dz + 2))
        # spar-flange notches (top and bottom), on the box side of each web
        wf = det.spar_flange_width_mm + 0.5
        xn = xs * c + (wf / 2 if xs == spec.front_spar_xc else -wf / 2)
        for zs, sgn in ((zu_s[0] * c, -1.0), (zl_s[0] * c, 1.0)):
            hn = t_cov + t_web + 0.3
            cutters.append(Pos(xn, y0 + t / 2, zs + sgn * hn / 2) * Box(wf, 3 * t, hn + 0.6))
    for b in bays:
        # stringer cutouts ("mouseholes"): U-slot clearing the whole angle, rounded end radius = half width
        cl = det.mousehole_clearance_mm
        leg = det.stringer_leg_mm[b]
        r_m = leg / 2 + cl
        depth = leg + cl
        for xm in stringer_positions_mm(spec, b, c):
            zu_m, zl_m = naca4_surfaces(spec.naca, np.array([xm / c]))
            for zs, sgn in ((zu_m[0] * c - t_cov, -1.0), (zl_m[0] * c + t_cov, 1.0)):
                straight = depth - r_m + 1.0  # + 1 mm past the rib edge
                cutters.append(Pos(xm, y0 + t / 2, zs + sgn * (depth - r_m - 1.0) / 2) * Box(2 * r_m, 3 * t, straight))
                cutters.append(Pos(xm, y0 + t / 2, zs + sgn * (depth - r_m)) * Rot(90, 0, 0) * Cylinder(r_m, 3 * t))
    lips = []
    for xh, zc, r in detailed_rib_holes(spec, y):
        cutters.append(Pos(xh, y0 + t / 2, zc) * Rot(90, 0, 0) * Cylinder(r, 3 * t))
        lip_dir = 1.0 if y0 + t + det.hole_lip_mm <= spec.semispan_mm else -1.0
        y_lip = y0 + t if lip_dir > 0 else y0 - det.hole_lip_mm
        lip = (Pos(xh, y_lip + det.hole_lip_mm / 2, zc) * Rot(90, 0, 0)
               * (Cylinder(r + t, det.hole_lip_mm) - Cylinder(r, det.hole_lip_mm + 1)))
        lips.append(lip)
    for cut in cutters:
        rib = rib - cut
    # bonded rib flanges (caps): bands under the skin on both surfaces, split at spars / stringers
    bf = det.rib_flange_width_mm
    fl_dir = 1.0 if y0 + t + bf <= spec.semispan_mm else -1.0
    ya, yb = (y0 + t, y0 + t + bf) if fl_dir > 0 else (y0 - bf, y0)
    flanges = []
    gaps = [(spec.front_spar_xc * c - t_web, spec.front_spar_xc * c + det.spar_flange_width_mm + 0.5),
            (spec.rear_spar_xc * c - det.spar_flange_width_mm - 0.5, spec.rear_spar_xc * c + t_web)]
    for b in bays:
        for xm in stringer_positions_mm(spec, b, c):
            hw = det.stringer_leg_mm[b] / 2 + det.mousehole_clearance_mm
            gaps.append((xm - hw, xm + hw))
    gaps.sort()
    segs, x_prev = [], 0.03 * c
    for g0, g1 in gaps:
        if g0 - x_prev > 3.0:
            segs.append((x_prev, g0))
        x_prev = max(x_prev, g1)
    if spec.te_skin_end_xc * c - 2.0 - x_prev > 3.0:
        segs.append((x_prev, spec.te_skin_end_xc * c - 2.0))
    for x0, x1 in segs:
        mid = 0.5 * (x0 + x1) / c
        d0 = t_cov if spec.front_spar_xc <= mid <= spec.rear_spar_xc else sk
        for upper in (True, False):
            ca = spec.chord(ya) / c
            fa = _band(spec, ya, x0 * ca, x1 * ca, d0, d0 + t, upper, 9)
            fb = _band(spec, yb, x0 * spec.chord(yb) / c, x1 * spec.chord(yb) / c, d0, d0 + t, upper, 9)
            flanges.append(loft([fa, fb]))
    shift = Pos(spec.x_le(y), 0, 0) if spec.sweep_le_deg else None
    if shift is not None:
        rib = shift * rib
        lips = [shift * q for q in lips]
    return rib, flanges + lips


def _rib(spec: WingStructureSpec, y: float, t: float, n: int) -> Part:
    c = spec.chord(y)
    y0 = min(max(y - t / 2, 0.0), spec.semispan_mm - t)
    rib = extrude(_face(_rib_profile(spec, c, n), y0), amount=t, dir=(0, 1, 0))
    for xh, zc, r in _rib_holes(spec, c):
        rib = rib - Pos(xh, y0 + t / 2, zc) * Rot(90, 0, 0) * Cylinder(r, 3 * t)
    return Pos(spec.x_le(y), 0, 0) * rib if spec.sweep_le_deg else rib


def rib_flat_patterns(spec: WingStructureSpec) -> dict[str, Face]:
    """2-D cutting profiles of every rib (outline + lightening holes) in the XY plane, mm.

    X is chordwise from the leading edge and Y is the airfoil's thickness
    direction, ready for laser/water-jet cutting from `rib_thickness_mm` sheet.
    Keys match the rib part labels (``Rib_1`` at the root ... tip).
    """
    spec.validate()
    out = {}
    for i, y in enumerate(spec.bay_edges_mm):
        c = spec.chord(float(y))
        pts = [(float(px), float(pz), 0.0) for px, pz in _rib_profile(spec, c, spec.n_profile)]
        face = make_face(Wire.make_polygon(pts, close=True))
        for xh, zc, r in _rib_holes(spec, c):
            face = face - Pos(xh, zc, 0) * Circle(r)
        out[f"Rib_{i + 1}"] = face
    return out


def build_wing_structure(spec: WingStructureSpec) -> WingStructure:
    """Build ribs, spars, box covers and LE/TE skin for one semispan (mirrored on request)."""
    spec.validate()
    n = spec.n_profile
    sk = spec.skin_thickness_mm
    parts: dict[str, list[Part]] = {"ribs": [], "spars": [], "box covers": [], "leading-edge skin": [],
                                    "trailing-edge skin": []}
    edges = spec.bay_edges_mm
    for b in range(len(spec.t_cap_mm)):
        ya, yb = float(edges[b]), float(edges[b + 1])
        tc, tw = float(spec.t_cap_mm[b]), float(spec.t_web_mm[b])
        for name, xs in (("Front", spec.front_spar_xc), ("Rear", spec.rear_spar_xc)):
            web = loft([_web_section(spec, ya, xs, tw, tc), _web_section(spec, yb, xs, tw, tc)])
            web.label = f"{name}Spar_Bay{b + 1}"
            parts["spars"].append(web)
        for name, upper in (("Upper", True), ("Lower", False)):
            cover = loft([
                _section(spec, ya, spec.front_spar_xc, spec.rear_spar_xc, tc, upper, n),
                _section(spec, yb, spec.front_spar_xc, spec.rear_spar_xc, tc, upper, n),
            ])
            cover.label = f"{name}Cover_Bay{b + 1}"
            parts["box covers"].append(cover)
    s0, s1 = 0.0, spec.semispan_mm
    nose = loft([_nose_section(spec, s0, sk, n), _nose_section(spec, s1, sk, n)])
    nose.label = "LeadingEdgeSkin"
    parts["leading-edge skin"].append(nose)
    for name, upper in (("Upper", True), ("Lower", False)):
        te = loft([
            _section(spec, s0, spec.rear_spar_xc, spec.te_skin_end_xc, sk, upper, n),
            _section(spec, s1, spec.rear_spar_xc, spec.te_skin_end_xc, sk, upper, n),
        ])
        te.label = f"TrailingEdgeSkin_{name}"
        parts["trailing-edge skin"].append(te)
    det = spec.details
    if det is None:
        for i, y in enumerate(edges):
            rib = _rib(spec, float(y), spec.rib_thickness_mm, n)
            rib.label = f"Rib_{i + 1}"
            parts["ribs"].append(rib)
    else:
        _add_details(spec, parts, n)
    for g, ps in parts.items():
        for p in ps:
            if not p.is_valid or p.volume <= 0:
                raise WingStructureError(f"invalid solid in group '{g}'")
    dens = {"ribs": AL_DENSITY_KG_M3, "spars": AL_DENSITY_KG_M3, "box covers": AL_DENSITY_KG_M3,
            "leading-edge skin": SKIN_DENSITY_KG_M3, "trailing-edge skin": SKIN_DENSITY_KG_M3,
            "spar flanges": AL_DENSITY_KG_M3, "stringers": AL_DENSITY_KG_M3, "rib flanges": AL_DENSITY_KG_M3,
            "fasteners": RIVET_DENSITY_KG_M3}
    return WingStructure(spec=spec, parts=parts, densities=dens)


def _add_details(spec: WingStructureSpec, parts: dict, n: int) -> None:
    """Spar flanges, stringers, detailed ribs (+ flanges, hole lips) and flange rivets."""
    det = spec.details
    edges = spec.bay_edges_mm
    for g in ("spar flanges", "stringers", "rib flanges", "fasteners"):
        parts[g] = []
    bf = det.spar_flange_width_mm
    for b in range(len(spec.t_cap_mm)):
        ya, yb = float(edges[b]), float(edges[b + 1])
        tc, tw = float(spec.t_cap_mm[b]), float(spec.t_web_mm[b])
        for name, xs, sgn in (("Front", spec.front_spar_xc, 1.0), ("Rear", spec.rear_spar_xc, -1.0)):
            for surf, upper in (("U", True), ("L", False)):
                def sec(yy, xs=xs, sgn=sgn, upper=upper, tc=tc, tw=tw):
                    c = spec.chord(yy)
                    x0 = xs * c + (tw / 2 if sgn > 0 else -tw / 2 - bf)
                    return _band(spec, yy, x0, x0 + bf, tc, tc + tw, upper, 7)
                fl = loft([sec(ya), sec(yb)])
                fl.label = f"{name}SparFlange{surf}_Bay{b + 1}"
                parts["spar flanges"].append(fl)
        leg, ts = det.stringer_leg_mm[b], det.stringer_t_mm[b]
        anti_peel: dict[str, list] = {"U": [], "L": []}
        for k in range(det.stringers_per_bay[b]):
            for surf, upper in (("U", True), ("L", False)):
                def land(yy, k=k, upper=upper, tc=tc, b=b, leg=leg, ts=ts):
                    xm = stringer_positions_mm(spec, b, spec.chord(yy))[k]
                    return _band(spec, yy, xm - leg / 2, xm + leg / 2, tc, tc + ts, upper, 5)

                def leg_v(yy, k=k, upper=upper, tc=tc, b=b, leg=leg, ts=ts):
                    xm = stringer_positions_mm(spec, b, spec.chord(yy))[k]
                    return _blade(spec, yy, xm + leg / 2 - ts / 2, ts, tc + ts, tc + leg, upper)
                # stringer ends stop 1 mm short of the ribs (run-outs / splices at every rib)
                y0, y1 = ya + spec.rib_thickness_mm / 2 + 1.0, yb - spec.rib_thickness_mm / 2 - 1.0
                st = loft([land(y0), land(y1)]) + loft([leg_v(y0), leg_v(y1)])
                st.label = f"Stringer{surf}{k + 1}_Bay{b + 1}"
                parts["stringers"].append(st)
                # anti-peel rivet at each bonded run-out (the bond alone peels at an unsupported end)
                for end, ye in (("a", y0 + 3.0), ("b", y1 - 3.0)):
                    c = spec.chord(ye)
                    xm = stringer_positions_mm(spec, b, c)[k] - leg / 4
                    zu_r, zl_r = naca4_surfaces(spec.naca, np.array([xm / c]))
                    z_out = zu_r[0] * c if upper else zl_r[0] * c
                    length = tc + ts + 0.3 + 0.6
                    zc = z_out + (-1.0 if upper else 1.0) * (length / 2 - 0.6)
                    anti_peel[surf].append(Pos(xm + spec.x_le(ye), ye, zc) * Cylinder(det.rivet_diameter_mm / 2, length))
        # one leaf per group of identical fasteners: build123d rebuilds a compound on every child attach, so
        # hundreds of single-rivet leaves make assembly O(n^2); each leaf still holds every rivet solid
        for surf, rvs in anti_peel.items():
            if rvs:
                grp = Compound(rvs)
                grp.label = f"AntiPeelRivets{surf}_Bay{b + 1}"
                parts["fasteners"].append(grp)
    for i, y in enumerate(edges):
        rib, extras = _detailed_rib(spec, float(y), spec.rib_thickness_mm, n)
        rib.label = f"Rib_{i + 1}"
        parts["ribs"].append(rib)
        fl = Compound(extras)
        fl.label = f"Rib_{i + 1}_Flanges"
        parts["rib flanges"].append(fl)
    # rivets: one row along each spar flange, top and bottom, at the designed pitch
    p = det.rivet_pitch_mm
    ys = np.arange(p / 2, spec.semispan_mm, p)
    if det.max_rivets_per_line:
        ys = ys[:: max(1, math.ceil(len(ys) / det.max_rivets_per_line))]
    for name, xs, sgn in (("F", spec.front_spar_xc, 1.0), ("R", spec.rear_spar_xc, -1.0)):
        for surf, upper in (("U", True), ("L", False)):
            row = []
            for yy in ys:
                b = min(int(np.searchsorted(edges, yy, side="right")) - 1, len(spec.t_cap_mm) - 1)
                tc, tw = spec.t_cap_mm[b], spec.t_web_mm[b]
                c = spec.chord(float(yy))
                xr = xs * c + sgn * (tw / 2 + bf / 2)
                zu_r, zl_r = naca4_surfaces(spec.naca, np.array([xr / c]))
                z_out = zu_r[0] * c if upper else zl_r[0] * c
                length = tc + tw + 0.3 + 0.6  # stack + shop head + manufactured head
                zc = z_out + (-1.0 if upper else 1.0) * (length / 2 - 0.6)
                row.append(Pos(xr + spec.x_le(float(yy)), float(yy), zc) * Cylinder(det.rivet_diameter_mm / 2, length))
            grp = Compound(row)
            grp.label = f"RivetRow_{name}{surf}"
            parts["fasteners"].append(grp)
