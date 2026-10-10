"""Close-up CalculiX models of structural details (v0.16), each checked against a closed-form method.

gmsh meshes 8-node quadrilaterals (6-node triangles where it must), CalculiX
solves (SOLVER=SPOOLES, single-threaded -- see `wing_box_fe.run_ccx`):

1. `open_hole_kt`        fastener hole in a strip, tension (CPS8, quarter model) vs Heywood.
2. `edge_notch_kt`       opposite semicircular notches in a strip, tension (CPS8) vs Peterson;
   `rib_notch_kt`        the real rib mousehole (U-slot) -- FE only, two meshes.
3. `bonded_lap`          adherend / adhesive / adherend, plane strain (CPE8): adhesive shear
                          along the overlap vs Volkersen (adherends supported -> no peel), and the
                          unsupported joint showing peel.
4. `stiffened_panel_buckling`  cover bay between two ribs with its stringers (S8R) vs
                          plate + Euler-Johnson column closed form.
5. `shear_web_buckling`  rib web in shear (S8R) without holes (vs ks closed form), with plain
                          and with flanged lightening holes; `hole_in_shear_kt` (CPS8) vs 4 tau.

Stresses are CalculiX nodal values (extrapolated, averaged); peak stresses are
read at the free edge of the hole / notch, where averaging is one-sided.
"""

from __future__ import annotations

import math
import os
import tempfile
from dataclasses import dataclass, field

import gmsh
import numpy as np

from agents.structures.agent import _find_ccx_path
from agents.structures.frd_utils import parse_frd_nodal_block
from agents.structures.inp_utils import format_nset_lines
from agents.structures.wing_box_fe import (
    BUCKLE_REFERENCE_SCALE,
    parse_buckling_factors,
    run_ccx,
)


class DetailFEError(RuntimeError):
    pass


@dataclass
class Mesh2D:
    nodes: dict[int, np.ndarray]
    elements: dict[str, list[tuple[str, list[int]]]]  # elset -> [(etype, connectivity)]
    edge_elems: dict[int, list[list[int]]] = field(default_factory=dict)  # curve tag -> line3 elements

    def nodes_where(self, pred) -> list[int]:
        return [n for n, x in self.nodes.items() if pred(x)]


def _gmsh_start(name: str) -> None:
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.model.add(name)


def _quad8_options() -> None:
    gmsh.option.setNumber("Mesh.RecombineAll", 1)
    gmsh.option.setNumber("Mesh.Algorithm", 8)
    gmsh.option.setNumber("Mesh.RecombinationAlgorithm", 1)
    gmsh.option.setNumber("Mesh.ElementOrder", 2)
    gmsh.option.setNumber("Mesh.SecondOrderIncomplete", 1)
    gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
    gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)


def _extract(surface_sets: dict[str, list[int]], curves: list[int] | None = None) -> Mesh2D:
    tags, coords, _ = gmsh.model.mesh.getNodes()
    nodes = {int(t): coords[3 * i: 3 * i + 3].copy() for i, t in enumerate(tags)}
    elements: dict[str, list] = {}
    for name, surfs in surface_sets.items():
        lst = []
        for sf in surfs:
            types, _, conns = gmsh.model.mesh.getElements(2, sf)
            for et, cn in zip(types, conns):
                if et == 16:
                    lst += [("Q8", [int(v) for v in cn[8 * k: 8 * k + 8]]) for k in range(len(cn) // 8)]
                elif et == 9:
                    lst += [("T6", [int(v) for v in cn[6 * k: 6 * k + 6]]) for k in range(len(cn) // 6)]
                else:
                    raise DetailFEError(f"unexpected gmsh element type {et}")
        elements[name] = lst
    edges = {}
    for cv in curves or []:
        types, _, conns = gmsh.model.mesh.getElements(1, cv)
        edges[cv] = [[int(v) for v in conns[0][3 * k: 3 * k + 3]] for k in range(len(conns[0]) // 3)]
    return Mesh2D(nodes, elements, edges)


def _curves_in_box(x0, y0, z0, x1, y1, z1, eps=1e-4) -> list[int]:
    return [t for _, t in gmsh.model.getEntitiesInBoundingBox(x0 - eps, y0 - eps, z0 - eps, x1 + eps, y1 + eps,
                                                               z1 + eps, dim=1)]


def _refine(curves: list[int], size_min: float, size_max: float, d_min: float, d_max: float) -> None:
    f = gmsh.model.mesh.field
    f.add("Distance", 1)
    f.setNumbers(1, "CurvesList", curves)
    f.setNumber(1, "Sampling", 200)
    f.add("Threshold", 2)
    f.setNumber(2, "InField", 1)
    f.setNumber(2, "SizeMin", size_min)
    f.setNumber(2, "SizeMax", size_max)
    f.setNumber(2, "DistMin", d_min)
    f.setNumber(2, "DistMax", d_max)
    f.setAsBackgroundMesh(2)


def _deck_elements(mesh: Mesh2D, kind: str) -> tuple[list[str], dict[str, str]]:
    """*ELEMENT blocks; kind 'CPS' / 'CPE' (2D) or 'S' (shell). Returns lines and elset -> eset names."""
    q8, t6 = {"CPS": ("CPS8", "CPS6"), "CPE": ("CPE8", "CPE6"), "S": ("S8R", "S6")}[kind]
    out, eid, names = [], 1, {}
    for name, lst in mesh.elements.items():
        for et, typ in (("Q8", q8), ("T6", t6)):
            sel = [c for e, c in lst if e == et]
            if not sel:
                continue
            es = f"{name}_{et}"
            out.append(f"*ELEMENT, TYPE={typ}, ELSET={es}")
            for c in sel:
                out.append(f"{eid}, " + ", ".join(str(n) for n in c))
                eid += 1
            names.setdefault(name, [])
            names[name].append(es)
    return out, names


def _sections(names: dict, thickness: dict[str, float], material: dict[str, str], kind: str) -> list[str]:
    out = []
    for name, sets in names.items():
        out.append(f"*ELSET, ELSET={name}")
        out.append(", ".join(sets))
        card = "*SHELL SECTION" if kind == "S" else "*SOLID SECTION"
        out += [f"{card}, ELSET={name}, MATERIAL={material[name]}", f"{thickness[name]:.6f}"]
    return out


def _materials(mats: dict[str, tuple[float, float]]) -> list[str]:
    out = []
    for m, (e, nu) in mats.items():
        out += [f"*MATERIAL, NAME={m}", "*ELASTIC", f"{e}, {nu}"]
    return out


def _nset(name: str, ids: list[int]) -> list[str]:
    return [f"*NSET, NSET={name}", *format_nset_lines(sorted(set(ids)))]


def _ccx() -> str:
    path = _find_ccx_path()
    if path is None:
        raise DetailFEError("ccx (CalculiX) not found")
    return path


def _solve(deck: str, job: str, work_dir: str | None):
    work_dir = work_dir or tempfile.mkdtemp(prefix=f"aeroforge_{job}_")
    os.makedirs(work_dir, exist_ok=True)
    return run_ccx(_ccx(), deck, job, work_dir)


def parse_total_force(dat_text: str) -> np.ndarray:
    """(fx, fy, fz) of the last '*NODE PRINT ..., TOTALS=ONLY' block."""
    lines = dat_text.splitlines()
    idx = [i for i, ln in enumerate(lines) if "total force (fx,fy,fz)" in ln]
    if not idx:
        raise DetailFEError("no total-force block in .dat")
    for ln in lines[idx[-1] + 1:]:
        parts = ln.split()
        if len(parts) == 3:
            return np.array([float(v) for v in parts])
    raise DetailFEError("empty total-force block")


def _stress(frd: str) -> dict[int, np.ndarray]:
    return {k: np.array(v) for k, v in parse_frd_nodal_block(frd, "STRESS", 6).items()}


# --------------------------------------------------------------------------- 1. open hole


@dataclass
class KtResult:
    kt_fe: float
    kt_ref: float | None
    peak_mpa: float
    nominal_mpa: float
    n_elements: int
    mesh: Mesh2D
    stress: dict[int, np.ndarray]
    label: str = ""

    @property
    def error_pct(self) -> float | None:
        return None if self.kt_ref is None else 100 * (self.kt_fe / self.kt_ref - 1)


def _tension_quarter(name: str, build, hole_curves_fn, w_half: float, l_half: float, t: float, e: float, nu: float,
                     sym_x_pred, size_min: float, size_max: float, d_max: float, net_half: float,
                     peak_xy: tuple[float, float], work_dir: str | None) -> KtResult:
    _gmsh_start(name)
    try:
        surf = build()
        gmsh.model.occ.synchronize()
        _refine(hole_curves_fn(), size_min, size_max, 0.0, d_max)
        _quad8_options()
        gmsh.model.mesh.generate(2)
        mesh = _extract({"PLATE": [surf]})
    finally:
        gmsh.finalize()
    tol = 1e-6
    sym_x = mesh.nodes_where(sym_x_pred)
    sym_y = mesh.nodes_where(lambda p: abs(p[1]) < tol)
    load = mesh.nodes_where(lambda p: abs(p[0] - l_half) < tol)
    els, names = _deck_elements(mesh, "CPS")
    delta = 1e-3 * l_half
    deck = ["*HEADING", name, "*NODE"]
    deck += [f"{n}, {p[0]:.7f}, {p[1]:.7f}, 0.0" for n, p in mesh.nodes.items()]
    deck += els + _nset("SYMX", sym_x) + _nset("SYMY", sym_y) + _nset("LOAD", load)
    deck += _materials({"AL": (e, nu)}) + _sections(names, {"PLATE": t}, {"PLATE": "AL"}, "CPS")
    deck += ["*BOUNDARY", "SYMX, 1, 1", "SYMY, 2, 2", "*STEP", "*STATIC, SOLVER=SPOOLES", "*BOUNDARY",
             f"LOAD, 1, 1, {delta}", "*NODE PRINT, NSET=LOAD, TOTALS=ONLY", "RF", "*EL FILE", "S", "*END STEP"]
    run = _solve("\n".join(deck) + "\n", name, work_dir)
    rf = abs(parse_total_force(run.dat_text)[0])
    s = _stress(run.frd_path)
    nominal = rf / (net_half * t)
    nid = min(mesh.nodes, key=lambda n: np.hypot(*(mesh.nodes[n][:2] - np.array(peak_xy))))
    peak = s[nid][0]
    n_el = sum(len(v) for v in mesh.elements.values())
    return KtResult(peak / nominal, None, peak, nominal, n_el, mesh, s, name)


def open_hole_kt(width_mm: float, hole_d_mm: float, t_mm: float = 1.0, e: float = 68900.0, nu: float = 0.33,
                 refine: float = 1.0, work_dir: str | None = None) -> KtResult:
    """Quarter model of a strip (width W, length 4W) with a central hole, uniform end displacement."""
    from agents.structures.joints import kt_open_hole_heywood

    wh, lh, r = width_mm / 2, 2 * width_mm, hole_d_mm / 2

    def build():
        rect = gmsh.model.occ.addRectangle(0, 0, 0, lh, wh)
        disk = gmsh.model.occ.addDisk(0, 0, 0, r, r)
        out, _ = gmsh.model.occ.cut([(2, rect)], [(2, disk)])
        return out[0][1]

    def hole():
        return [t for t in _curves_in_box(0, 0, 0, r, r, 0) if t]

    res = _tension_quarter("open_hole", build, hole, wh, lh, t_mm, e, nu,
                           lambda p: abs(p[0]) < 1e-6 and p[1] >= r - 1e-6, r / 24 / refine, wh / 8 / refine, 4 * r,
                           wh - r, (0.0, r), work_dir)
    res.kt_ref = kt_open_hole_heywood(hole_d_mm / width_mm)
    return res


def edge_notch_kt(width_mm: float, notch_r_mm: float, t_mm: float = 1.0, e: float = 68900.0, nu: float = 0.33,
                  refine: float = 1.0, work_dir: str | None = None) -> KtResult:
    """Quarter model: strip of width D with opposite semicircular edge notches of radius r at x = 0."""
    from agents.structures.joints import kt_double_semicircular_notch

    dh, lh, r = width_mm / 2, 2 * width_mm, notch_r_mm

    def build():
        rect = gmsh.model.occ.addRectangle(0, 0, 0, lh, dh)
        disk = gmsh.model.occ.addDisk(0, dh, 0, r, r)
        out, _ = gmsh.model.occ.cut([(2, rect)], [(2, disk)])
        return out[0][1]

    def notch():
        return _curves_in_box(0, dh - r, 0, r, dh, 0)

    res = _tension_quarter("edge_notch", build, notch, dh, lh, t_mm, e, nu,
                           lambda p: abs(p[0]) < 1e-6 and p[1] <= dh - r + 1e-6, r / 24 / refine, dh / 8 / refine,
                           4 * r, dh - r, (0.0, dh - r), work_dir)
    res.kt_ref = kt_double_semicircular_notch(2 * r / width_mm)
    return res


def rib_notch_kt(depth_mm: float, slot_w_mm: float, slot_d_mm: float, t_mm: float = 0.5, e: float = 68900.0,
                 nu: float = 0.33, refine: float = 1.0, work_dir: str | None = None) -> KtResult:
    """Rib strip of depth H with opposite U-slot mouseholes (width w, depth d, round end r = w/2), tension.

    Net-section Kt; no handbook value for this exact shape -> compare two mesh densities (`refine`).
    """
    hh, lh, r = depth_mm / 2, 2 * depth_mm, slot_w_mm / 2
    straight = slot_d_mm - r

    def build():
        rect = gmsh.model.occ.addRectangle(0, 0, 0, lh, hh)
        cut_box = gmsh.model.occ.addRectangle(0, hh - straight, 0, r, straight + 1.0)
        disk = gmsh.model.occ.addDisk(0, hh - straight, 0, r, r)
        out, _ = gmsh.model.occ.cut([(2, rect)], [(2, cut_box), (2, disk)])
        return out[0][1]

    def notch():
        return _curves_in_box(0, hh - slot_d_mm, 0, r, hh, 0)

    return _tension_quarter("rib_notch", build, notch, hh, lh, t_mm, e, nu,
                            lambda p: abs(p[0]) < 1e-6 and p[1] <= hh - slot_d_mm + 1e-6, r / 24 / refine,
                            hh / 8 / refine, 4 * r, hh - slot_d_mm, (0.0, hh - slot_d_mm), work_dir)


# --------------------------------------------------------------------------- 3. bonded lap


@dataclass
class BondedLapFE:
    x_mm: np.ndarray
    tau_mpa: np.ndarray
    peel_mpa: np.ndarray
    x_ref: np.ndarray
    tau_ref: np.ndarray
    supported: bool
    p_npmm: float
    tau_max_fe: float
    tau_max_ref: float
    peel_max_fe: float
    mesh: Mesh2D = None
    stress: dict = None

    @property
    def error_pct(self) -> float:
        return 100 * (self.tau_max_fe / self.tau_max_ref - 1)


def bonded_lap(p_npmm: float, overlap_mm: float, t1: float, t2: float, e1: float = 68900.0, e2: float = 68900.0,
               g_a: float | None = None, t_a: float | None = None, nu_a: float = 0.35, free_mm: float = 10.0,
               supported: bool = True, n_overlap: int = 200, work_dir: str | None = None) -> BondedLapFE:
    """Plane-strain lap joint; adherend 1 (bottom) loaded at its left end, adherend 2 (top) held at its right end."""
    from agents.structures.joints import ADHESIVE_G_MPA, ADHESIVE_T_MM, volkersen

    g_a = g_a or ADHESIVE_G_MPA
    t_a = t_a or ADHESIVE_T_MM
    e_a = 2 * g_a * (1 + nu_a)
    half = overlap_mm / 2
    xa, xb = -half - free_mm, half + free_mm
    y1, y2, y3 = t1, t1 + t_a, t1 + t_a + t2
    _gmsh_start("bonded_lap")
    try:
        occ = gmsh.model.occ
        r = {
            "A1F": occ.addRectangle(xa, 0, 0, free_mm, t1),
            "A1O": occ.addRectangle(-half, 0, 0, overlap_mm, t1),
            "ADH": occ.addRectangle(-half, y1, 0, overlap_mm, t_a),
            "A2O": occ.addRectangle(-half, y2, 0, overlap_mm, t2),
            "A2F": occ.addRectangle(half, y2, 0, free_mm, t2),
        }
        occ.fragment([(2, v) for v in r.values()], [])
        occ.synchronize()
        h_ov = overlap_mm / n_overlap
        for _, cv in gmsh.model.getEntities(1):
            bb = gmsh.model.getBoundingBox(1, cv)
            dx, dy = bb[3] - bb[0], bb[4] - bb[1]
            if dx > dy:
                n = max(2, round(dx / h_ov)) if dx <= overlap_mm + 1e-6 else max(2, round(dx / (4 * h_ov)))
                gmsh.model.mesh.setTransfiniteCurve(cv, n + 1)
            else:
                gmsh.model.mesh.setTransfiniteCurve(cv, 5)
        for _, sf in gmsh.model.getEntities(2):
            gmsh.model.mesh.setTransfiniteSurface(sf)
            gmsh.model.mesh.setRecombine(2, sf)
        gmsh.option.setNumber("Mesh.ElementOrder", 2)
        gmsh.option.setNumber("Mesh.SecondOrderIncomplete", 1)
        gmsh.model.mesh.generate(2)
        sets = {"ADH": [], "ADHERENDS": []}
        for _, sf in gmsh.model.getEntities(2):
            bb = gmsh.model.getBoundingBox(2, sf)
            (sets["ADH"] if bb[1] > y1 - 1e-6 and bb[4] < y2 + 1e-6 else sets["ADHERENDS"]).append(sf)
        mesh = _extract(sets)
    finally:
        gmsh.finalize()
    tol = 1e-6
    left = mesh.nodes_where(lambda p: abs(p[0] - xa) < tol)
    right = mesh.nodes_where(lambda p: abs(p[0] - xb) < tol)
    bc = ["*BOUNDARY", "RIGHT, 1, 2"]
    sets_txt = _nset("LEFT", left) + _nset("RIGHT", right)
    if supported:
        bottom = mesh.nodes_where(lambda p: abs(p[1]) < tol)
        top = mesh.nodes_where(lambda p: abs(p[1] - y3) < tol)
        sets_txt += _nset("BOT", bottom) + _nset("TOP", top)
        bc += ["BOT, 2, 2", "TOP, 2, 2"]
    else:
        bc += ["LEFT, 2, 2"]
    els, names = _deck_elements(mesh, "CPE")
    deck = ["*HEADING", "bonded lap", "*NODE"]
    deck += [f"{n}, {p[0]:.7f}, {p[1]:.7f}, 0.0" for n, p in mesh.nodes.items()]
    deck += els + sets_txt
    deck += _materials({"AL": (e1, 0.33), "ADHM": (e_a, nu_a)})
    deck += _sections(names, {"ADH": 1.0, "ADHERENDS": 1.0}, {"ADH": "ADHM", "ADHERENDS": "AL"}, "CPE")
    deck += bc + ["*STEP", "*STATIC, SOLVER=SPOOLES", "*BOUNDARY", "LEFT, 1, 1, -0.01",
                  "*NODE PRINT, NSET=LEFT, TOTALS=ONLY", "RF", "*EL FILE", "S", "*END STEP"]
    run = _solve("\n".join(deck) + "\n", "bonded_lap", work_dir)
    rf = abs(parse_total_force(run.dat_text)[0])  # N per mm width (unit thickness)
    scale = p_npmm / rf
    s = _stress(run.frd_path)
    ymid = 0.5 * (y1 + y2)
    mid = sorted((n for n, p in mesh.nodes.items() if abs(p[1] - ymid) < 1e-6 and n in s), key=lambda n: mesh.nodes[n][0])
    x = np.array([mesh.nodes[n][0] for n in mid])
    tau = np.array([abs(s[n][3]) for n in mid]) * scale
    peel = np.array([s[n][1] for n in mid]) * scale
    x_ref, tau_ref = volkersen(p_npmm, overlap_mm, e1, t1, e2, t2, g_a, t_a)
    for k in s:
        s[k] = s[k] * scale
    return BondedLapFE(x, tau, peel, x_ref, np.abs(tau_ref), supported, p_npmm, float(tau.max()),
                       float(np.abs(tau_ref).max()), float(peel.max()), mesh, s)


# --------------------------------------------------------------------------- 4/5. shell buckling


@dataclass
class BucklingFE:
    factors: list[float]
    mode: dict[int, np.ndarray]
    mesh: Mesh2D
    label: str
    reference: float | None = None
    note: str = ""

    @property
    def first(self) -> float:
        return self.factors[0]

    @property
    def error_pct(self) -> float | None:
        return None if self.reference is None else 100 * (self.first / self.reference - 1)


def _first_mode(frd: str) -> dict[int, np.ndarray]:
    from agents.structures.wing_box_fe import read_frd_displacements

    blocks = read_frd_displacements(frd)
    return blocks[-1] if len(blocks) == 1 else blocks[1]  # block 0 = static base state


def stiffened_panel_buckling(length_mm: float, width_mm: float, skin_t: float, n_stringers: int, leg_mm: float,
                             stringer_t: float, sigma_ref_mpa: float, e: float = 68900.0, nu: float = 0.33,
                             mesh_size: float | None = None, n_modes: int = 4,
                             work_dir: str | None = None) -> BucklingFE:
    """Cover bay between two ribs (x = 0, L), spar webs at y = 0, w; stringers as land strip + blade (S8R).

    Edges simply supported out of plane; loaded ends carry sigma_ref x local thickness (skin, land, blade),
    i.e. a uniform stress `sigma_ref_mpa` on the whole cover section -> factor = sigma_cr / sigma_ref.
    """
    pitch = width_mm / (n_stringers + 1)
    h = mesh_size or min(pitch / 6, leg_mm / 2, 4.0)
    _gmsh_start("stiffened_panel")
    try:
        occ = gmsh.model.occ
        ys = [0.0]
        for k in range(n_stringers):
            yc = pitch * (k + 1)
            ys += [yc - leg_mm / 2, yc + leg_mm / 2]
        ys.append(width_mm)
        tags = {}
        for k in range(len(ys) - 1):
            sf = occ.addRectangle(0, ys[k], 0, length_mm, ys[k + 1] - ys[k])
            tags[sf] = "LAND" if k % 2 == 1 else "SKIN"
        blades = []
        for k in range(n_stringers):
            yb = pitch * (k + 1) + leg_mm / 2 - stringer_t / 2
            sf = occ.addRectangle(0, 0, 0, length_mm, leg_mm)
            occ.rotate([(2, sf)], 0, 0, 0, 1, 0, 0, math.pi / 2)
            occ.translate([(2, sf)], 0, yb, 0)
            blades.append(sf)
        ents = [(2, t) for t in list(tags) + blades]
        if len(ents) > 1:
            _, omap = occ.fragment(ents, [])
        else:
            omap = [[e] for e in ents]  # gmsh returns an empty map for a single entity
        occ.synchronize()
        sets = {"SKIN": [], "LAND": [], "BLADE": []}
        for (_, orig), children in zip(ents, omap):
            name = tags.get(orig, "BLADE")
            sets[name] += [c[1] for c in children]
        gmsh.option.setNumber("Mesh.MeshSizeMax", h)
        gmsh.option.setNumber("Mesh.MeshSizeMin", h / 2)
        _quad8_options()
        gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 1)
        gmsh.model.mesh.generate(2)
        thick = {"SKIN": skin_t, "LAND": skin_t + stringer_t, "BLADE": stringer_t}
        surf_t = {sf: thick[k] for k, v in sets.items() for sf in v}
        end_curves = {}
        for x_end, sgn in ((0.0, 1.0), (length_mm, -1.0)):
            for cv in _curves_in_box(x_end, 0, 0, x_end, width_mm, leg_mm):
                up, _ = gmsh.model.getAdjacencies(1, cv)
                end_curves[cv] = (sgn, max(surf_t[int(u)] for u in up))
        mesh = _extract({k: v for k, v in sets.items() if v}, list(end_curves))
    finally:
        gmsh.finalize()
    # Loaded ends: consistent edge forces sigma_ref * t (an SPC on ux of a shell node would also fix the
    # expanded through-thickness nodes and clamp the edge's rotation -- the ribs are simple supports).
    forces: dict[int, float] = {}
    for cv, (sgn, t_cv) in end_curves.items():
        for a, b, m in mesh.edge_elems[cv]:
            length = np.linalg.norm(mesh.nodes[a] - mesh.nodes[b])
            for n, wgt in ((a, 1 / 6), (b, 1 / 6), (m, 2 / 3)):
                forces[n] = forces.get(n, 0.0) + sgn * BUCKLE_REFERENCE_SCALE * sigma_ref_mpa * t_cv * length * wgt
    tol = 1e-6
    xs0 = mesh.nodes_where(lambda p: abs(p[0]) < tol)
    xs1 = mesh.nodes_where(lambda p: abs(p[0] - length_mm) < tol)
    skin_edge = mesh.nodes_where(lambda p: abs(p[2]) < tol and (abs(p[1]) < tol or abs(p[1] - width_mm) < tol))
    end_skin = [n for n in xs0 + xs1 if abs(mesh.nodes[n][2]) < tol]
    end_blade = [n for n in xs0 + xs1 if mesh.nodes[n][2] > tol]
    els, names = _deck_elements(mesh, "S")
    deck = ["*HEADING", "stiffened panel", "*NODE"]
    deck += [f"{n}, {p[0]:.7f}, {p[1]:.7f}, {p[2]:.7f}" for n, p in mesh.nodes.items()]
    deck += els + _nset("EDGES", skin_edge) + _nset("ENDSKIN", end_skin)
    if end_blade:
        deck += _nset("ENDBLADE", end_blade)
    deck += _materials({"AL": (e, nu)})
    deck += _sections(names, {k: thick[k] for k in names}, {k: "AL" for k in names}, "S")
    c0 = min(xs0, key=lambda n: np.linalg.norm(mesh.nodes[n]))
    c1 = min(xs0, key=lambda n: np.linalg.norm(mesh.nodes[n] - np.array([0.0, width_mm, 0.0])))
    deck += ["*BOUNDARY", "EDGES, 3, 3", "ENDSKIN, 3, 3", f"{c0}, 1, 2", f"{c1}, 1, 1"]
    if end_blade:
        deck += ["ENDBLADE, 2, 2"]
    deck += ["*STEP", "*BUCKLE, SOLVER=SPOOLES", f"{n_modes}", "*CLOAD"]
    deck += [f"{n}, 1, {f:.8e}" for n, f in sorted(forces.items())]
    deck += ["*NODE FILE, OUTPUT=2D", "U", "*END STEP"]  # 2D: mode shapes on the shell nodes
    run = _solve("\n".join(deck) + "\n", "stiffened_panel", work_dir)
    return BucklingFE([f * BUCKLE_REFERENCE_SCALE for f in parse_buckling_factors(run.dat_text)], _first_mode(run.frd_path), mesh,
                      f"{n_stringers} stringers")


def _shear_edge_loads(mesh: Mesh2D, curves: dict[str, list[int]], tau_t: float) -> dict[int, np.ndarray]:
    """Consistent nodal forces of a uniform shear flow tau*t [N/mm] on the four panel edges."""
    dirs = {"bottom": (-1, 0), "top": (1, 0), "left": (0, -1), "right": (0, 1)}
    f: dict[int, np.ndarray] = {}
    for side, cvs in curves.items():
        dvec = np.array([*dirs[side], 0.0])
        for cv in cvs:
            for a, b, m in mesh.edge_elems[cv]:
                length = np.linalg.norm(mesh.nodes[a] - mesh.nodes[b])
                for n, wgt in ((a, 1 / 6), (b, 1 / 6), (m, 2 / 3)):
                    f[n] = f.get(n, np.zeros(3)) + tau_t * length * wgt * dvec
    return f


def _shear_panel_mesh(w: float, h: float, holes: list[tuple[float, float, float]], lip_mm: float, size: float,
                      size_min: float | None = None):
    _gmsh_start("shear_panel")
    try:
        occ = gmsh.model.occ
        plate = occ.addRectangle(0, 0, 0, w, h)
        tools, lips = [], []
        for xc, yc, r in holes:
            tools.append((2, occ.addDisk(xc, yc, 0, r, r)))
        if tools:
            plate = occ.cut([(2, plate)], tools)[0][0][1]
        if lip_mm > 0:
            for xc, yc, r in holes:
                circ = occ.addCircle(xc, yc, 0, r)
                # structured layers (an unstructured lip recombines into degenerate quads)
                ext = occ.extrude([(1, circ)], 0, 0, lip_mm, numElements=[3], recombine=True)
                lips += [t for d, t in ext if d == 2]
            _, omap = occ.fragment([(2, plate)] + [(2, t) for t in lips], [])
            plate_tags = [c[1] for c in omap[0]]
            lip_tags = [c[1] for m in omap[1:] for c in m]
        else:
            plate_tags, lip_tags = [plate], []
        occ.synchronize()
        hole_curves = []
        for xc, yc, r in holes:
            hole_curves += _curves_in_box(xc - r, yc - r, 0, xc + r, yc + r, 0)
        if hole_curves:
            _refine(hole_curves, size_min or size / 4, size, 0.0, 3 * max(r for *_, r in holes))
        else:
            gmsh.option.setNumber("Mesh.MeshSizeMax", size)
        _quad8_options()
        gmsh.model.mesh.generate(2)
        sides = {"bottom": _curves_in_box(0, 0, 0, w, 0, 0), "top": _curves_in_box(0, h, 0, w, h, 0),
                 "left": _curves_in_box(0, 0, 0, 0, h, 0), "right": _curves_in_box(w, 0, 0, w, h, 0)}
        sets = {"WEB": plate_tags}
        if lip_tags:
            sets["LIP"] = lip_tags
        mesh = _extract(sets, [c for v in sides.values() for c in v])
    finally:
        gmsh.finalize()
    return mesh, sides


def shear_web_buckling(w: float, h: float, t: float, holes: list[tuple[float, float, float]] | None = None,
                       lip_mm: float = 0.0, tau_ref_mpa: float = 1.0, e: float = 68900.0, nu: float = 0.33,
                       size: float | None = None, n_modes: int = 4, work_dir: str | None = None) -> BucklingFE:
    """Rib web panel w x h in pure shear (edges simply supported), optional (flanged) lightening holes."""
    holes = holes or []
    size = size or min(w, h) / 12
    mesh, sides = _shear_panel_mesh(w, h, holes, lip_mm, size)
    f = _shear_edge_loads(mesh, sides, BUCKLE_REFERENCE_SCALE * tau_ref_mpa * t)
    tol = 1e-6
    edge_nodes = mesh.nodes_where(lambda p: abs(p[2]) < tol and (abs(p[0]) < tol or abs(p[0] - w) < tol
                                                                 or abs(p[1]) < tol or abs(p[1] - h) < tol))
    n00 = min(edge_nodes, key=lambda n: np.linalg.norm(mesh.nodes[n]))
    nw0 = min(edge_nodes, key=lambda n: np.linalg.norm(mesh.nodes[n] - np.array([w, 0, 0])))
    els, names = _deck_elements(mesh, "S")
    deck = ["*HEADING", "shear web", "*NODE"]
    deck += [f"{n}, {p[0]:.7f}, {p[1]:.7f}, {p[2]:.7f}" for n, p in mesh.nodes.items()]
    deck += els + _nset("EDGE", edge_nodes) + _materials({"AL": (e, nu)})
    deck += _sections(names, {k: t for k in names}, {k: "AL" for k in names}, "S")
    deck += ["*BOUNDARY", "EDGE, 3, 3", f"{n00}, 1, 2", f"{nw0}, 2, 2",
             "*STEP", "*BUCKLE, SOLVER=SPOOLES", f"{n_modes}", "*CLOAD"]
    for n, v in sorted(f.items()):
        for d in (0, 1):
            if abs(v[d]) > 0:
                deck.append(f"{n}, {d + 1}, {v[d]:.8e}")
    deck += ["*NODE FILE, OUTPUT=2D", "U", "*END STEP"]  # 2D: mode shapes on the shell nodes
    tag = "plain" if not holes else ("flanged" if lip_mm > 0 else "holes")
    run = _solve("\n".join(deck) + "\n", f"shear_web_{tag}", work_dir)
    return BucklingFE([f * BUCKLE_REFERENCE_SCALE for f in parse_buckling_factors(run.dat_text)], _first_mode(run.frd_path), mesh, tag)


def hole_in_shear_kt(size_mm: float, hole_d_mm: float, t: float = 1.0, e: float = 68900.0, nu: float = 0.33,
                     work_dir: str | None = None) -> KtResult:
    """Square panel in pure shear with a central hole: max principal stress at the hole / tau vs 4 (Kirsch)."""
    from agents.structures.joints import KT_HOLE_PURE_SHEAR

    c = size_mm / 2
    r = hole_d_mm / 2
    mesh, sides = _shear_panel_mesh(size_mm, size_mm, [(c, c, r)], 0.0, size_mm / 16, size_min=r / 24)
    tau = 1.0
    f = _shear_edge_loads(mesh, sides, tau * t)
    tol = 1e-6
    edge_nodes = mesh.nodes_where(lambda p: abs(p[0]) < tol or abs(p[0] - size_mm) < tol or abs(p[1]) < tol
                                  or abs(p[1] - size_mm) < tol)
    n00 = min(edge_nodes, key=lambda n: np.linalg.norm(mesh.nodes[n]))
    nw0 = min(edge_nodes, key=lambda n: np.linalg.norm(mesh.nodes[n] - np.array([size_mm, 0, 0])))
    els, names = _deck_elements(mesh, "CPS")
    deck = ["*HEADING", "hole in shear", "*NODE"]
    deck += [f"{n}, {p[0]:.7f}, {p[1]:.7f}, 0.0" for n, p in mesh.nodes.items()]
    deck += els + _materials({"AL": (e, nu)}) + _sections(names, {"WEB": t}, {"WEB": "AL"}, "CPS")
    deck += ["*BOUNDARY", f"{n00}, 1, 2", f"{nw0}, 2, 2", "*STEP", "*STATIC, SOLVER=SPOOLES", "*CLOAD"]
    for n, v in sorted(f.items()):
        for d in (0, 1):
            if abs(v[d]) > 0:
                deck.append(f"{n}, {d + 1}, {v[d]:.8e}")
    deck += ["*EL FILE", "S", "*END STEP"]
    run = _solve("\n".join(deck) + "\n", "hole_shear", work_dir)
    s = _stress(run.frd_path)
    rim = [n for n, p in mesh.nodes.items() if abs(np.hypot(p[0] - c, p[1] - c) - r) < 1e-4 and n in s]

    def s1(v):
        sxx, syy, sxy = v[0], v[1], v[3]
        return 0.5 * (sxx + syy) + math.hypot(0.5 * (sxx - syy), sxy)

    peak = max(s1(s[n]) for n in rim)
    n_el = sum(len(v) for v in mesh.elements.values())
    return KtResult(peak / tau, KT_HOLE_PURE_SHEAR, peak, tau, n_el, mesh, s, "hole in shear")
