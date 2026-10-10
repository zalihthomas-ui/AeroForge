"""CalculiX shell model of the tapered wing box (structured S8R mesh, no gmsh).

The box surface is a structured "tube" grid: a ring of nodes around the
rectangular cross-section (top cover -> rear web -> bottom cover -> front
web) at every spanwise node row, so covers and webs share their corner
nodes exactly. Ribs at the bay boundaries are meshed as S8R plates whose edge
nodes are the ring nodes of that station. Thickness is stepped per bay
(`BoxThickness`), so the FE model and the closed-form sizing describe the
same structure.

Coordinates [mm]: x chordwise (leading edge at 0, unswept), y spanwise
(root at 0), z up. Units: N, mm, MPa, tonne/mm^3 -> frequencies in Hz.

Load: the semispan running lift l(y) is integrated to nodal forces per node
row and shared equally by the two upper spar-cap (web/cover corner) nodes of
that row (lift through the box's shear centre: no torsion), all in +z. Boundary condition: every root node
clamped (DOF 1-6).

Three analyses, each its own deck (CalculiX buckling/frequency steps are
kept independent of the static step on purpose):
  * static      -- *STATIC, SOLVER=SPOOLES: displacement, stress, reactions
  * buckle      -- *BUCKLE, SOLVER=SPOOLES: load factor on the applied load
  * frequency   -- *FREQUENCY, SOLVER=SPOOLES: natural frequencies
SOLVER=SPOOLES is mandatory on the MSYS2 build: the PaStiX default hangs
(see vendor/calculix/README.md).
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field

import numpy as np

from agents.structures.frd_utils import parse_frd_nodal_block
from agents.structures.inp_utils import format_nset_lines
from agents.structures.wing_box import BoxThickness, Material, WingBoxGeometry

_CCX_TIMEOUT_S = 600
# This ccx build's *BUCKLE only reports buckling factors > 1 (found in v0.16: a plate whose true factor was
# 0.54 reported 1.05, its third mode). Solving at a reduced reference load and scaling back captures every
# factor > BUCKLE_REFERENCE_SCALE; the mode shapes are unchanged.
BUCKLE_REFERENCE_SCALE = 0.1


class WingBoxFEError(RuntimeError):
    """Raised when the wing-box FE model cannot be built, run or parsed."""


@dataclass
class WingBoxMesh:
    nodes: dict[int, tuple[float, float, float]]
    elements: dict[str, list[tuple[int, ...]]]  # elset name -> S8R connectivity
    elset_thickness: dict[str, float]
    root_nodes: list[int]
    tip_nodes: list[int]
    load_nodes_by_row: list[list[int]]  # upper spar-cap nodes per node row (root -> tip)
    row_y_mm: np.ndarray
    ring: dict[tuple[int, int], int] = field(default_factory=dict)  # (perimeter idx, row) -> node
    top_cover_mid: dict[int, int] = field(default_factory=dict)  # row -> mid-width top-cover node
    rib_rows: list[int] = field(default_factory=list)

    @property
    def n_elements(self) -> int:
        return sum(len(v) for v in self.elements.values())


def build_mesh(
    geometry: WingBoxGeometry,
    thickness: BoxThickness,
    n_span: int = 48,
    n_width: int = 8,
    n_height: int = 3,
    rib_thickness_mm: float = 1.0,
) -> WingBoxMesh:
    """Structured S8R mesh of the box surface plus ribs at every bay boundary."""
    semispan = geometry.semispan_mm
    n_bays = len(thickness.t_cap_mm)
    if n_span % n_bays:
        raise WingBoxFEError(f"n_span ({n_span}) must be a multiple of the number of bays ({n_bays}).")
    rows = 2 * n_span + 1
    row_y = np.linspace(0.0, semispan, rows)

    def dims(y):
        c = np.interp(y, geometry.y_mm, geometry.chord_mm)
        w = np.interp(y, geometry.y_mm, geometry.width_mm)
        h = np.interp(y, geometry.y_mm, geometry.height_mm)
        xc = 0.5 * (geometry.front_spar_xc + geometry.rear_spar_xc) * c
        return xc, w, h

    # Perimeter parametrisation (quadratic: 2 nodes per element edge).
    nw, nh = 2 * n_width, 2 * n_height
    perim = []  # (u, v) in [-1, 1]^2 local box coords, and wall tag
    for i in range(nw):  # top cover, front(-u) -> rear(+u)
        perim.append((-1.0 + 2.0 * i / nw, 1.0, "top"))
    for i in range(nh):  # rear web, top -> bottom
        perim.append((1.0, 1.0 - 2.0 * i / nh, "web"))
    for i in range(nw):  # bottom cover, rear -> front
        perim.append((1.0 - 2.0 * i / nw, -1.0, "bot"))
    for i in range(nh):  # front web, bottom -> top
        perim.append((-1.0, -1.0 + 2.0 * i / nh, "web"))
    n_p = len(perim)

    nodes: dict[int, tuple[float, float, float]] = {}
    ring: dict[tuple[int, int], int] = {}
    nid = 0
    for r in range(rows):
        xc, w, h = dims(row_y[r])
        for p in range(n_p):
            if r % 2 == 1 and p % 2 == 1:
                continue  # S8R: no element-centre nodes
            u, v, _ = perim[p]
            nid += 1
            nodes[nid] = (xc + 0.5 * w * u, float(row_y[r]), 0.5 * h * v)
            ring[(p, r)] = nid

    elements: dict[str, list[tuple[int, ...]]] = {}
    thick_map: dict[str, float] = {}
    for er in range(n_span):
        r0, r1, r2 = 2 * er, 2 * er + 1, 2 * er + 2
        bay = min(int(er * n_bays / n_span), n_bays - 1)
        for ep in range(n_p // 2):
            p0, p1, p2 = 2 * ep, 2 * ep + 1, (2 * ep + 2) % n_p
            wall = perim[p1][2]
            name = f"{'COVER' if wall in ('top', 'bot') else 'WEB'}_{bay}"
            thick_map[name] = float(thickness.t_cap_mm[bay] if name.startswith("COVER") else thickness.t_web_mm[bay])
            conn = (ring[(p0, r0)], ring[(p2, r0)], ring[(p2, r2)], ring[(p0, r2)],
                    ring[(p1, r0)], ring[(p2, r1)], ring[(p1, r2)], ring[(p0, r1)])
            elements.setdefault(name, []).append(conn)

    # Ribs at every bay boundary except the clamped root.
    rib_rows = [2 * b * n_span // n_bays for b in range(1, n_bays + 1)]
    # boundary lookup: local (i, j) on a (nw+1) x (nh+1) grid -> perimeter index
    def perim_index(i, j):
        if j == nh:
            return min(nw, i)  # top edge (i = nw is the rear-top corner)
        if i == nw:
            return nw + (nh - j)  # rear web, top -> bottom
        if j == 0:
            return nw + nh + (nw - i)  # bottom, rear -> front
        if i == 0:
            return (2 * nw + nh + j) % n_p  # front web, bottom -> top
        return None

    thick_map["RIB"] = float(rib_thickness_mm)
    for r in rib_rows:
        xc, w, h = dims(row_y[r])
        grid: dict[tuple[int, int], int] = {}
        for i in range(nw + 1):
            for j in range(nh + 1):
                pi = perim_index(i, j)
                if pi is not None:
                    grid[(i, j)] = ring[(pi, r)]
                elif not (i % 2 == 1 and j % 2 == 1):
                    nid += 1
                    nodes[nid] = (xc + 0.5 * w * (-1.0 + 2.0 * i / nw), float(row_y[r]), 0.5 * h * (-1.0 + 2.0 * j / nh))
                    grid[(i, j)] = nid
        for ei in range(n_width):
            for ej in range(n_height):
                i0, j0 = 2 * ei, 2 * ej
                conn = (grid[(i0, j0)], grid[(i0 + 2, j0)], grid[(i0 + 2, j0 + 2)], grid[(i0, j0 + 2)],
                        grid[(i0 + 1, j0)], grid[(i0 + 2, j0 + 1)], grid[(i0 + 1, j0 + 2)], grid[(i0, j0 + 1)])
                elements.setdefault("RIB", []).append(conn)

    # Lift enters along the two upper spar-cap lines (front-top and rear-top
    # corners), as upper-surface suction reaching the spars through the skin:
    # the webs hang from their top edge in tension. Spreading point loads over
    # the thin webs instead produces spurious local web crippling modes in
    # the buckling analysis.
    web_ps = [0, nw]  # front-top corner, rear-top corner
    load_rows = []
    for r in range(rows):
        load_rows.append([ring[(p, r)] for p in web_ps if (p, r) in ring])
    top_mid_p = n_width  # u = 0 on the top cover
    top_mid = {r: ring[(top_mid_p, r)] for r in range(rows) if (top_mid_p, r) in ring}
    root = [n for (p, r), n in ring.items() if r == 0]
    tip = [n for (p, r), n in ring.items() if r == rows - 1]
    return WingBoxMesh(
        nodes=nodes,
        elements=elements,
        elset_thickness=thick_map,
        root_nodes=sorted(root),
        tip_nodes=sorted(tip),
        load_nodes_by_row=load_rows,
        row_y_mm=row_y,
        ring=ring,
        top_cover_mid=top_mid,
        rib_rows=rib_rows,
    )


def nodal_lift_forces(mesh: WingBoxMesh, y_mm: np.ndarray, lift_per_span_npm: np.ndarray) -> dict[int, float]:
    """Integrate l(y) to forces per node row (tributary lengths), split over that row's load nodes."""
    ry = mesh.row_y_mm
    fine = np.linspace(0.0, ry[-1], 20 * len(ry))
    lf = np.interp(fine, y_mm, lift_per_span_npm) / 1000.0  # N/mm
    edges = np.concatenate([[ry[0]], 0.5 * (ry[1:] + ry[:-1]), [ry[-1]]])
    forces: dict[int, float] = {}
    for r in range(len(ry)):
        sel = (fine >= edges[r]) & (fine <= edges[r + 1])
        f_row = float(np.trapezoid(lf[sel], fine[sel])) if sel.sum() > 1 else 0.0
        nodes = mesh.load_nodes_by_row[r]
        for n in nodes:
            forces[n] = forces.get(n, 0.0) + f_row / len(nodes)
    # The root row is clamped: a load there would go straight into the support
    # and never show up as a reaction, so its share moves to the next row.
    root_share = sum(forces.pop(n) for n in mesh.load_nodes_by_row[0] if n in forces)
    for n in mesh.load_nodes_by_row[1]:
        forces[n] = forces.get(n, 0.0) + root_share / len(mesh.load_nodes_by_row[1])
    # correct tiny quadrature loss so the total equals the exact integral
    total = float(np.trapezoid(lf, fine))
    s = sum(forces.values())
    return {n: f * total / s for n, f in forces.items()}


def write_deck(
    mesh: WingBoxMesh,
    material: Material,
    analysis: str,
    forces: dict[int, float] | None = None,
    n_modes: int = 4,
) -> str:
    """Assemble a CalculiX .inp deck for 'static', 'buckle' or 'frequency'."""
    if analysis not in ("static", "buckle", "frequency"):
        raise WingBoxFEError(f"unknown analysis '{analysis}'.")
    out = ["*HEADING", f"AeroForge wing box -- {analysis}", "*NODE"]
    out += [f"{n}, {x:.6f}, {y:.6f}, {z:.6f}" for n, (x, y, z) in mesh.nodes.items()]
    for name, conns in mesh.elements.items():
        out.append(f"*ELEMENT, TYPE=S8R, ELSET={name}")
        start = _element_offset(mesh, name)
        out += [f"{start + k}, " + ", ".join(str(n) for n in c) for k, c in enumerate(conns)]
    out += ["*NSET, NSET=ROOT", *format_nset_lines(mesh.root_nodes)]
    out += ["*NSET, NSET=TIP", *format_nset_lines(mesh.tip_nodes)]
    out += ["*MATERIAL, NAME=SKIN", "*ELASTIC",
            f"{material.youngs_modulus_mpa}, {material.poissons_ratio}",
            "*DENSITY", f"{material.density_kgm3 * 1e-12:.6e}"]
    for name, t in mesh.elset_thickness.items():
        if name in mesh.elements:
            out += [f"*SHELL SECTION, ELSET={name}, MATERIAL=SKIN", f"{t:.6f}"]
    out += ["*BOUNDARY", "ROOT, 1, 6"]
    if analysis == "frequency":
        out += ["*STEP", "*FREQUENCY, SOLVER=SPOOLES", f"{n_modes}", "*NODE FILE, OUTPUT=2D", "U", "*END STEP"]
        return "\n".join(out) + "\n"
    if not forces:
        raise WingBoxFEError("static/buckle analyses need nodal forces.")
    if analysis == "static":
        out += ["*STEP", "*STATIC, SOLVER=SPOOLES"]
    else:
        out += ["*STEP", "*BUCKLE, SOLVER=SPOOLES", f"{n_modes}"]
    out.append("*CLOAD")
    out += [f"{n}, 3, {f:.8e}" for n, f in sorted(forces.items())]
    out += ["*NODE FILE, OUTPUT=2D", "U"]
    if analysis == "static":
        out += ["*EL FILE, OUTPUT=2D", "S", "*NODE PRINT, NSET=ROOT", "RF", "*NODE PRINT, NSET=TIP", "U"]
    out.append("*END STEP")
    return "\n".join(out) + "\n"


def _element_offset(mesh: WingBoxMesh, name: str) -> int:
    start = 1
    for k, conns in mesh.elements.items():
        if k == name:
            return start
        start += len(conns)
    raise KeyError(name)


@dataclass
class FERun:
    work_dir: str
    jobname: str
    dat_text: str
    frd_path: str


def run_ccx(ccx_path: str, deck: str, jobname: str, work_dir: str | None = None,
            timeout: int = _CCX_TIMEOUT_S) -> FERun:
    """Write the deck and run ccx.exe (explicit timeout as defence in depth)."""
    work_dir = work_dir or tempfile.mkdtemp(prefix=f"aeroforge_wingbox_{jobname}_")
    with open(os.path.join(work_dir, f"{jobname}.inp"), "w", encoding="utf-8") as f:
        f.write(deck)
    env = os.environ.copy()
    env["PATH"] = os.path.dirname(ccx_path) + os.pathsep + env.get("PATH", "")
    # Single-threaded on purpose: with OMP threads this MSYS2 ccx build's
    # *BUCKLE / *FREQUENCY eigensolver is non-deterministic and intermittently
    # returns spurious eigenvalues (same deck: 0.70 / 1.01 / 1.72); with one
    # thread it is exactly repeatable. See vendor/calculix/README.md.
    env["OMP_NUM_THREADS"] = "1"
    try:
        proc = subprocess.run([ccx_path, jobname], cwd=work_dir, env=env, timeout=timeout,
                              capture_output=True, text=True, check=False)
    except subprocess.TimeoutExpired as exc:
        raise WingBoxFEError(f"ccx.exe did not finish within {timeout}s (is SOLVER=SPOOLES set?).") from exc
    dat = os.path.join(work_dir, f"{jobname}.dat")
    if not os.path.isfile(dat):
        raise WingBoxFEError(f"ccx produced no .dat output:\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}")
    with open(dat, encoding="latin-1") as f:
        text = f.read()
    return FERun(work_dir, jobname, text, os.path.join(work_dir, f"{jobname}.frd"))


# ------------------------------------------------------------------ parsing

def parse_reaction_sum(dat_text: str) -> np.ndarray:
    """Sum of the root reaction forces (fx, fy, fz)."""
    tot = np.zeros(3)
    found = False
    for block in _dat_blocks(dat_text, "forces (fx,fy,fz)"):
        found = True
        for parts in block:
            tot += np.array([float(v) for v in parts[1:4]])
    if not found:
        raise WingBoxFEError("no reaction-force block in .dat")
    return tot


def parse_node_displacements(dat_text: str) -> dict[int, np.ndarray]:
    out = {}
    for block in _dat_blocks(dat_text, "displacements (vx,vy,vz)"):
        for parts in block:
            out[int(parts[0])] = np.array([float(v) for v in parts[1:4]])
    if not out:
        raise WingBoxFEError("no displacement block in .dat")
    return out


def parse_buckling_factors(dat_text: str) -> list[float]:
    """Buckling load factors from the 'B U C K L I N G   F A C T O R' table."""
    i = dat_text.find("B U C K L I N G   F A C T O R")
    if i < 0:
        raise WingBoxFEError("no buckling-factor table in .dat")
    vals = []
    for line in dat_text[i:].splitlines()[1:]:
        parts = line.split()
        if len(parts) == 2 and parts[0].isdigit():
            vals.append(float(parts[1]))
        elif vals and not parts:
            break
    if not vals:
        raise WingBoxFEError("empty buckling-factor table")
    return vals


def parse_frequencies_hz(dat_text: str) -> list[float]:
    """Natural frequencies (cycles/time column) from the eigenvalue output table."""
    i = dat_text.find("E I G E N V A L U E   O U T P U T")
    if i < 0:
        raise WingBoxFEError("no eigenvalue table in .dat")
    vals = []
    for line in dat_text[i:].splitlines()[1:]:
        parts = line.split()
        if len(parts) == 5 and parts[0].isdigit():
            vals.append(float(parts[3]))
        elif vals and not parts:
            break
    if not vals:
        raise WingBoxFEError("empty eigenvalue table")
    return vals


def read_frd_displacements(frd_path: str) -> list[dict[int, np.ndarray]]:
    """All DISP blocks (one per load step / mode) from a .frd file."""
    with open(frd_path, encoding="latin-1") as f:
        lines = f.read().splitlines()
    blocks, i = [], 0
    while i < len(lines):
        if lines[i].strip().startswith("-4") and "DISP" in lines[i]:
            i += 1
            while i < len(lines) and lines[i].strip().startswith("-5"):
                i += 1
            d = {}
            while i < len(lines) and lines[i].strip().startswith("-1"):
                ln = lines[i]
                d[int(ln[3:13])] = np.array([float(ln[13 + 12 * k: 25 + 12 * k]) for k in range(3)])
                i += 1
            blocks.append(d)
        i += 1
    if not blocks:
        raise WingBoxFEError(f"no DISP blocks in {frd_path}")
    return blocks


def read_frd_stress(frd_path: str) -> dict[int, np.ndarray]:
    """Nodal stress tensor (SXX, SYY, SZZ, SXY, SYZ, SZX) from the static .frd."""
    return {k: np.array(v) for k, v in parse_frd_nodal_block(frd_path, "STRESS", 6).items()}


def von_mises(s: np.ndarray) -> float:
    sxx, syy, szz, sxy, syz, szx = s
    return float(np.sqrt(0.5 * ((sxx - syy) ** 2 + (syy - szz) ** 2 + (szz - sxx) ** 2)
                         + 3.0 * (sxy**2 + syz**2 + szx**2)))


def _dat_blocks(dat_text: str, header: str):
    lines = dat_text.splitlines()
    i = 0
    while i < len(lines):
        if header in lines[i]:
            i += 1
            while i < len(lines) and not lines[i].strip():
                i += 1
            block = []
            while i < len(lines) and lines[i].strip():
                parts = lines[i].split()
                if len(parts) >= 4 and re.fullmatch(r"\d+", parts[0]):
                    block.append(parts)
                i += 1
            yield block
            continue
        i += 1


@dataclass
class WingBoxFEResult:
    """Static (at the applied load), buckling and modal results of the shell model."""

    n_elements: int
    n_nodes: int
    applied_lift_n: float  # sum of nodal forces (one semispan)
    reaction_z_n: float  # root reaction (should equal -applied)
    equilibrium_error_pct: float
    tip_deflection_mm: float  # mean vertical tip displacement
    max_von_mises_mpa: float  # peak nodal von Mises, all nodes
    max_von_mises_away_from_root_mpa: float  # excluding the first bay-length/8 at the clamp
    cover_stress_y_mm: np.ndarray  # stations where top-cover mid-width stress is sampled
    cover_stress_mpa: np.ndarray  # spanwise membrane stress S_yy at those stations
    buckling_factors: list[float]  # load multipliers on the applied load
    frequencies_hz: list[float]
    nodes: dict[int, tuple[float, float, float]] = field(repr=False, default_factory=dict)
    elements: dict[str, list[tuple[int, ...]]] = field(repr=False, default_factory=dict)
    static_displacement: dict[int, np.ndarray] = field(repr=False, default_factory=dict)
    von_mises: dict[int, float] = field(repr=False, default_factory=dict)
    buckling_modes: list[dict[int, np.ndarray]] = field(repr=False, default_factory=list)
    vibration_modes: list[dict[int, np.ndarray]] = field(repr=False, default_factory=list)


def run_wing_box_fe(
    ccx_path: str,
    geometry: WingBoxGeometry,
    thickness: BoxThickness,
    material: Material,
    lift_y_mm: np.ndarray,
    lift_per_span_npm: np.ndarray,
    n_span: int = 96,
    n_width: int = 12,
    n_height: int = 4,
    rib_thickness_mm: float = 1.0,
    n_buckling_modes: int = 6,
    n_frequency_modes: int = 6,
    work_dir: str | None = None,
) -> WingBoxFEResult:
    """Build the shell model once and run static, buckling and frequency analyses."""
    mesh = build_mesh(geometry, thickness, n_span=n_span, n_width=n_width, n_height=n_height,
                      rib_thickness_mm=rib_thickness_mm)
    forces = nodal_lift_forces(mesh, np.asarray(lift_y_mm), np.asarray(lift_per_span_npm))
    base = work_dir or tempfile.mkdtemp(prefix="aeroforge_wingbox_")
    os.makedirs(base, exist_ok=True)

    st = run_ccx(ccx_path, write_deck(mesh, material, "static", forces), "static", work_dir=base)
    applied = float(sum(forces.values()))
    rz = float(parse_reaction_sum(st.dat_text)[2])
    disp = read_frd_displacements(st.frd_path)[0]
    tip = float(np.mean([disp[n][2] for n in mesh.tip_nodes]))
    stress = read_frd_stress(st.frd_path)
    vm = {n: von_mises(s) for n, s in stress.items() if n in mesh.nodes}
    root_zone = geometry.semispan_mm / len(thickness.t_cap_mm) / 8.0
    vm_away = [v for n, v in vm.items() if mesh.nodes[n][1] > root_zone]
    rows = sorted(r for r in mesh.top_cover_mid if r % 2 == 0)
    ys = np.array([mesh.row_y_mm[r] for r in rows])
    syy = np.array([stress[mesh.top_cover_mid[r]][1] for r in rows])

    scaled = {n: f * BUCKLE_REFERENCE_SCALE for n, f in forces.items()}
    bk = run_ccx(ccx_path, write_deck(mesh, material, "buckle", scaled, n_modes=n_buckling_modes), "buckle",
                 work_dir=base)
    factors = [f * BUCKLE_REFERENCE_SCALE for f in parse_buckling_factors(bk.dat_text)]
    bmodes = read_frd_displacements(bk.frd_path)[1:]  # block 0 is the static base state

    fq = run_ccx(ccx_path, write_deck(mesh, material, "frequency", n_modes=n_frequency_modes), "frequency",
                 work_dir=base)
    freqs = parse_frequencies_hz(fq.dat_text)
    vmodes = read_frd_displacements(fq.frd_path)

    return WingBoxFEResult(
        n_elements=mesh.n_elements,
        n_nodes=len(mesh.nodes),
        applied_lift_n=applied,
        reaction_z_n=rz,
        equilibrium_error_pct=abs(applied + rz) / applied * 100.0,
        tip_deflection_mm=tip,
        max_von_mises_mpa=max(vm.values()),
        max_von_mises_away_from_root_mpa=max(vm_away),
        cover_stress_y_mm=ys,
        cover_stress_mpa=syy,
        buckling_factors=factors,
        frequencies_hz=freqs,
        nodes=mesh.nodes,
        elements=mesh.elements,
        static_displacement=disp,
        von_mises=vm,
        buckling_modes=bmodes,
        vibration_modes=vmodes,
    )
