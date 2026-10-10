"""V6 parametric CAD: build, pose, check clearances, export STEP, render.

Builds every part of the 60 deg split-pin V6 from `EngineSpec`, reports CAD
masses of the moving parts against the spec's dynamics masses, runs the clash
checks (pistons vs counterweights at BDC, rods vs block over 720 deg), exports
the labelled assembly and one STEP per part, and renders the assembly at the
requested crank angles (block and heads ghosted so the crank train is visible).

Usage (repo root):
    python examples/engine/cad.py                      # theta = 0 and 90 deg
    python examples/engine/cad.py --theta 0 90 180 --out artifacts/engine
"""

from __future__ import annotations

import argparse
import math
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import numpy as np

from agents.powertrain.spec import EngineSpec
from agents.powertrain.v6_cad import (
    assembly,
    build_v6,
    geometric_compression_ratio,
    part_masses_kg,
    piston_counterweight_clearance,
    reciprocating_mass_kg,
    rod_block_clearance,
    rod_small_end_fraction,
)
from cad.exporters import export_parts_step, export_step_assembly

GHOSTED = {"Block", "Heads", "CamCovers", "OilPan"}


def _leaves(shape, group=None):
    kids = list(getattr(shape, "children", ()) or ())
    if not kids:
        yield group, shape
        return
    for k in kids:
        yield from _leaves(k, group if group is not None and shape.label != "Engine" else k.label)


def render(asm, path: str, theta: float, elev: float = 22.0, azim: float = 145.0) -> str:
    """Painter's-algorithm render of the assembly (no extra dependencies)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import PolyCollection

    az, el = math.radians(azim), math.radians(elev)
    # view: from the timing end (front), above and to one side; Y is up
    rot_y = np.array([[math.cos(az), 0, math.sin(az)], [0, 1, 0], [-math.sin(az), 0, math.cos(az)]])
    rot_x = np.array([[1, 0, 0], [0, math.cos(el), -math.sin(el)], [0, math.sin(el), math.cos(el)]])
    view = rot_x @ rot_y
    light = np.array([0.4, 0.8, 0.6]) / np.linalg.norm([0.4, 0.8, 0.6])
    polys, cols, depth = [], [], []
    for group, leaf in _leaves(asm):
        verts, tris = leaf.tessellate(0.4, 0.3)
        v = np.array([[q.X, q.Y, q.Z] for q in verts]) @ view.T
        t = np.array(tris)
        tri = v[t]
        n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
        shade = 0.35 + 0.65 * np.abs(n @ light)
        c = tuple(leaf.color)[:3] if leaf.color is not None else (0.7, 0.7, 0.7)
        alpha = 0.10 if group in GHOSTED else 1.0
        rgba = np.column_stack([np.clip(np.outer(shade, c), 0, 1), np.full(len(tri), alpha)])
        polys.append(tri[:, :, :2]); cols.append(rgba); depth.append(tri[:, :, 2].mean(1))
    P, C, Z = np.concatenate(polys), np.concatenate(cols), np.concatenate(depth)
    order = np.argsort(Z)  # far (negative z after view) first
    fig = plt.figure(figsize=(12, 9), dpi=120, facecolor="#0B0F14")
    ax = fig.add_axes([0, 0, 1, 0.94]); ax.set_facecolor("#0B0F14"); ax.set_axis_off()
    ax.add_collection(PolyCollection(P[order], facecolors=C[order], edgecolors="none"))
    ax.autoscale_view(); ax.set_aspect("equal")
    fig.text(0.5, 0.965, f"AeroForge 3.0 L 60° split-pin V6 — crank angle θ = {theta:.0f}°  (block & heads ghosted)",
             ha="center", color="#E6EDF3", fontsize=15)
    fig.savefig(path, facecolor="#0B0F14")
    plt.close(fig)
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--theta", type=float, nargs="+", default=[0.0, 90.0])
    ap.add_argument("--out", default=os.path.join("artifacts", "engine"))
    ap.add_argument("--no-render", action="store_true")
    args = ap.parse_args()

    spec = EngineSpec()
    model = build_v6(spec)
    print(f"V6 {spec.displacement_l:.3f} L, bore {spec.bore_mm} x stroke {spec.stroke_mm} mm, rod {spec.rod_length_mm} mm")
    print(f"  compression height {model.compression_height:.1f} mm (crown flush with deck at TDC), "
          f"head gasket {model.prop.head_gasket} mm, chamber depth {model.chamber_depth:.2f} mm "
          f"-> CR {geometric_compression_ratio(model):.2f} (spec {spec.compression_ratio})")
    print(f"  main journals at z = {', '.join(f'{z:.0f}' for z in model.main_journal_z)} mm")

    m = part_masses_kg(model)
    print("\nCAD masses (volume x density; steel 7850, Al 2700 kg/m^3; rings not modelled):")
    for k, v in m.items():
        print(f"  {k:<12} {v:7.3f} kg")
    frac = rod_small_end_fraction(model)
    print(f"  rod small-end share (two-point, from CAD CG) {frac:.3f}  -> big-end share {1 - frac:.3f} "
          f"(spec rod_big_end_fraction {spec.rod_big_end_fraction})")
    print(f"  reciprocating mass per cylinder (piston + pin + small-end share) {reciprocating_mass_kg(model):.3f} kg "
          f"(spec {spec.reciprocating_mass_kg})")
    print(f"  rod mass {m['rod']:.3f} kg (spec {spec.rod_mass_kg})")

    print("\nClash checks:")
    cw = piston_counterweight_clearance(model)
    print("  piston skirt vs crank counterweights at each cylinder's BDC: "
          + ", ".join(f"cyl{k} {v:.2f} mm" for k, v in sorted(cw.items())))
    rb = rod_block_clearance(model, step_deg=5.0)
    print(f"  rods vs block, 720 deg every 5 deg ({rb['n_samples']} rod poses): min {rb['min_clearance_mm']:.2f} mm "
          f"(cyl {rb['cylinder']} at theta {rb['theta_deg']:.0f} deg; exact B-rep distance at the tightest samples)")

    os.makedirs(args.out, exist_ok=True)
    for th in args.theta:
        asm = assembly(model, theta_deg=th)
        step = os.path.join(args.out, f"v6_theta{th:03.0f}.step")
        export_step_assembly(asm, step)
        print(f"\nExported {step}")
        if th == args.theta[0]:
            files = export_parts_step(asm, os.path.join(args.out, "parts"))
            print(f"  + {len(files)} part STEP files in {os.path.join(args.out, 'parts')}")
        if not args.no_render:
            print(f"  render: {render(asm, os.path.join(args.out, f'v6_theta{th:03.0f}.png'), th)}")


if __name__ == "__main__":
    main()
