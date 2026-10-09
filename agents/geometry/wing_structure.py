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

Honest limits: covers are offset vertically (not along the surface normal);
parts touch/overlap by up to one skin thickness at joints (no fasteners,
flanges or bonding lands are modelled); the trailing-edge skin stops short of
the sharp trailing edge, leaving it open; ribs carry two round lightening holes
but no flanges or spar notches. The structural analysis idealises this box as a rectangle at
the thinner spar depth (conservative), while this CAD keeps the true airfoil
shape. Mass is from solid volumes x density.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from build123d import (
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

    def chord(self, y: float) -> float:
        return self.root_chord_mm + (self.tip_chord_mm - self.root_chord_mm) * y / self.semispan_mm

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
        """Both halves of every group as one compound per group."""
        out = {}
        for g, ps in self.parts.items():
            solids = []
            for p in ps:
                solids.append(p)
                solids.append(mirror(p, about=Plane.XZ))
            out[g] = Compound(children=solids)
        return out

    def assembly(self) -> Compound:
        return Compound(children=list(self.full_wing().values()))


def _section(spec: WingStructureSpec, y: float, x0: float, x1: float, t: float, upper: bool, n: int) -> Face:
    """Thin band following one surface between x0/c and x1/c, offset inward by t (vertical)."""
    c = spec.chord(y)
    xc = np.linspace(x0, x1, n)
    zu, zl = naca4_surfaces(spec.naca, xc)
    z = (zu if upper else zl) * c
    inner = z - t if upper else z + t
    pts = np.concatenate([np.column_stack([xc * c, z]), np.column_stack([xc[::-1] * c, inner[::-1]])])
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
    return _face(np.concatenate([outer, inner[::-1]]), y)


def _web_section(spec: WingStructureSpec, y: float, xc_spar: float, t: float, skin: float) -> Face:
    c = spec.chord(y)
    zu, zl = naca4_surfaces(spec.naca, np.array([xc_spar]))
    x = xc_spar * c
    top, bot = zu[0] * c - skin, zl[0] * c + skin
    return _face(np.array([[x - t / 2, bot], [x + t / 2, bot], [x + t / 2, top], [x - t / 2, top]]), y)


def _rib(spec: WingStructureSpec, y: float, t: float, n: int) -> Part:
    c = spec.chord(y)
    xc = _cosine(0.0, 1.0, n)
    zu, zl = naca4_surfaces(spec.naca, xc)
    pts = np.concatenate([np.column_stack([xc[::-1], zu[::-1]]), np.column_stack([xc[1:-1], zl[1:-1]])]) * c
    y0 = min(max(y - t / 2, 0.0), spec.semispan_mm - t)
    rib = extrude(_face(pts, y0), amount=t, dir=(0, 1, 0))
    if spec.rib_lightening_holes:
        # two round lightening holes inside the box, each 55 % of the local depth
        for frac in (0.3, 0.7):
            xh = spec.front_spar_xc + frac * (spec.rear_spar_xc - spec.front_spar_xc)
            zu_h, zl_h = naca4_surfaces(spec.naca, np.array([xh]))
            depth = (zu_h[0] - zl_h[0]) * c
            zc = 0.5 * (zu_h[0] + zl_h[0]) * c
            hole = Pos(xh * c, y0 + t / 2, zc) * Rot(90, 0, 0) * Cylinder(0.275 * depth, 3 * t)
            rib = rib - hole
    return rib


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
        for xs in (spec.front_spar_xc, spec.rear_spar_xc):
            parts["spars"].append(loft([_web_section(spec, ya, xs, tw, tc), _web_section(spec, yb, xs, tw, tc)]))
        for upper in (True, False):
            parts["box covers"].append(loft([
                _section(spec, ya, spec.front_spar_xc, spec.rear_spar_xc, tc, upper, n),
                _section(spec, yb, spec.front_spar_xc, spec.rear_spar_xc, tc, upper, n),
            ]))
    s0, s1 = 0.0, spec.semispan_mm
    parts["leading-edge skin"].append(loft([_nose_section(spec, s0, sk, n), _nose_section(spec, s1, sk, n)]))
    for upper in (True, False):
        parts["trailing-edge skin"].append(loft([
            _section(spec, s0, spec.rear_spar_xc, spec.te_skin_end_xc, sk, upper, n),
            _section(spec, s1, spec.rear_spar_xc, spec.te_skin_end_xc, sk, upper, n),
        ]))
    for y in edges:
        parts["ribs"].append(_rib(spec, float(y), spec.rib_thickness_mm, n))
    for g, ps in parts.items():
        for p in ps:
            if not p.is_valid or p.volume <= 0:
                raise WingStructureError(f"invalid solid in group '{g}'")
    dens = {"ribs": AL_DENSITY_KG_M3, "spars": AL_DENSITY_KG_M3, "box covers": AL_DENSITY_KG_M3,
            "leading-edge skin": SKIN_DENSITY_KG_M3, "trailing-edge skin": SKIN_DENSITY_KG_M3}
    return WingStructure(spec=spec, parts=parts, densities=dens)
