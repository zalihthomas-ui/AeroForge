"""Animate the 2D bracket optimizer (thickness + hole diameter, COBYLA).

Runs `optimize_bracket_thickness_and_hole_for_min_mass` (CalculiX FEA per
probe) on the same problem as examples/bracket/optimize_2d.py and animates its
evaluation log, one evaluation per step:

- left:  the bracket at the probed thickness / hole diameter (top view, drawn
         to scale; thickness shown as an edge-on strip), coloured green when
         the FEA hotspot stress is within the limit and red when it is not
- right: the design space (hole diameter vs thickness) with iso-mass lines,
         the optimizer's path and every probe
- below: mass per evaluation and the best feasible mass so far

Usage (repo root, needs CalculiX):
    python examples/bracket/animate_optimization_2d.py --out artifacts/bracket_optimization_2d.mp4
"""

from __future__ import annotations

import argparse
import math
import os
import shutil
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import numpy as np

from agents.geometry.bracket import hole_center_x_positions
from engineering.analysis.bracket_optimizer import calculate_bracket_mass
from engineering.analysis.bracket_optimizer_2d import (
    BracketOptimization2DResult,
    optimize_bracket_thickness_and_hole_for_min_mass,
)

PROBLEM = dict(
    length_mm=100.0,
    width_mm=80.0,
    hole_count=4,
    applied_force_n=500.0,
    max_allowable_stress_mpa=6.50,
    thickness_bounds_mm=(2.0, 10.0),
    hole_diameter_bounds_mm=(4.0, 15.0),
    max_evaluations=18,
)
BASELINE = (5.0, 8.0)  # (thickness, hole diameter) of the reference design in optimize_2d.py

PENALTY_STRESS_MPA = 1e5  # the optimizer marks probes rejected before FEA with stress 1e6


def run_optimization(structures_agent=None, **overrides) -> tuple[dict, BracketOptimization2DResult]:
    """Run the real optimizer on the example problem; returns (problem, result)."""
    problem = dict(PROBLEM, **overrides)
    result = optimize_bracket_thickness_and_hole_for_min_mass(**problem, structures_agent=structures_agent)
    return problem, result


def render_animation(problem: dict, result: BracketOptimization2DResult, out_path: str,
                     fps: int = 20, frames_per_eval: int = 12) -> str:
    """Render the evaluation log to an animation (.mp4 via ffmpeg, else .gif)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import animation
    from matplotlib.patches import Circle, Rectangle

    evals = result.evaluations
    if not evals:
        raise ValueError("Optimizer recorded no evaluations -- nothing to animate.")

    bg, panel, text, muted = "#0B0F14", "#111821", "#E6EDF3", "#8FA1B3"
    green, red, grey = "#66BB6A", "#EF5350", "#5C6B7A"
    L, W, n_holes = problem["length_mm"], problem["width_mm"], problem["hole_count"]
    limit = problem["max_allowable_stress_mpa"]
    t_lo, t_hi = problem["thickness_bounds_mm"]
    d_lo, d_hi = problem["hole_diameter_bounds_mm"]
    hole_x = hole_center_x_positions(L, n_holes)
    base_mass = calculate_bracket_mass(L, W, BASELINE[0], BASELINE[1], n_holes)

    def rejected(e) -> bool:
        return e.hotspot_stress_mpa >= PENALTY_STRESS_MPA

    best, best_trace = None, []
    for e in evals:
        if e.feasible and (best is None or e.mass_kg < best):
            best = e.mass_kg
        best_trace.append(best)

    plt.rcParams.update({"text.color": text, "axes.labelcolor": text, "xtick.color": muted,
                         "ytick.color": muted, "axes.edgecolor": "#2C3B4C", "font.size": 13})
    fig = plt.figure(figsize=(12.8, 7.2), dpi=100, facecolor=bg)
    ax_part = fig.add_axes([0.04, 0.40, 0.44, 0.48], facecolor=panel)
    ax_space = fig.add_axes([0.57, 0.40, 0.39, 0.48], facecolor=panel)
    ax_mass = fig.add_axes([0.08, 0.08, 0.88, 0.22], facecolor=panel)
    title = fig.text(0.04, 0.94, "", fontsize=18, fontweight="bold")
    fig.text(0.96, 0.94, f"AeroForge bracket optimizer · stress ≤ {limit} MPa", ha="right", color=muted)

    dd, tt = np.meshgrid(np.linspace(d_lo - 0.5, d_hi + 0.5, 60), np.linspace(t_lo - 0.3, t_hi, 60))
    mass_grid = 7850.0 * (L * W - n_holes * math.pi * (dd / 2) ** 2) * tt * 1e-9
    n_frames = len(evals) * frames_per_eval + fps * 2

    def draw(frame: int):
        k = min(frame // frames_per_eval, len(evals) - 1)
        e = evals[k]
        done = frame >= len(evals) * frames_per_eval
        for ax in (ax_part, ax_space, ax_mass):
            ax.cla(); ax.set_facecolor(panel); ax.grid(color="#223040", lw=0.8)

        show = next((x for x in evals if x.thickness_mm == result.optimal_thickness_mm
                     and x.hole_diameter_mm == result.optimal_hole_diameter_mm), e) if done else e
        col = grey if rejected(show) else (green if show.feasible else red)
        ax_part.add_patch(Rectangle((-L / 2, -W / 2), L, W, fc=col, alpha=0.30, ec=col, lw=2))
        for x in hole_x:
            ax_part.add_patch(Circle((x, 0), show.hole_diameter_mm / 2, fc=panel, ec=text, lw=1.5))
        strip = show.thickness_mm * 2.0  # edge-on thickness, 2x scale for visibility
        ax_part.add_patch(Rectangle((-L / 2, -W / 2 - 8 - strip), L, strip, fc=col, alpha=0.8, ec="none"))
        ax_part.text(L / 2, -W / 2 - 10 - strip, f"t = {show.thickness_mm:.2f} mm (edge view, 2x)",
                     ha="right", va="top", color=muted, fontsize=11)
        ax_part.set_xlim(-L / 2 - 5, L / 2 + 5); ax_part.set_ylim(-W / 2 - 34, W / 2 + 5)
        ax_part.set_aspect("equal"); ax_part.set_xticks([]); ax_part.set_yticks([])
        stress = "rejected before FEA (outside bounds)" if rejected(show) else \
            f"hotspot {show.hotspot_stress_mpa:.2f} MPa {'≤' if show.feasible else '>'} {limit}"
        ax_part.set_title(f"Ø {show.hole_diameter_mm:.2f} mm · {show.mass_kg if not rejected(show) else float('nan'):.3f} kg · {stress}",
                          color=col if not rejected(show) else muted, fontsize=13)

        cs = ax_space.contour(dd, tt, mass_grid, levels=8, colors="#2C3B4C", linewidths=1)
        ax_space.clabel(cs, fmt="%.2f kg", fontsize=9, colors=muted)
        ax_space.plot([BASELINE[1]], [BASELINE[0]], "*", ms=16, color=muted)
        path = evals[: k + 1]
        ax_space.plot([p.hole_diameter_mm for p in path], [p.thickness_mm for p in path], color=muted, lw=1, alpha=0.6)
        for p in path:
            c = grey if rejected(p) else (green if p.feasible else red)
            ax_space.plot([p.hole_diameter_mm], [p.thickness_mm], "o", color=c, ms=7)
        ax_space.plot([e.hole_diameter_mm], [e.thickness_mm], "o", ms=14, mfc="none", mec=text, mew=2)
        if done:
            ax_space.plot([result.optimal_hole_diameter_mm], [result.optimal_thickness_mm], "o", ms=20,
                          mfc="none", mec=green, mew=3)
        ax_space.set_xlim(d_lo - 0.5, d_hi + 0.5); ax_space.set_ylim(t_lo - 0.3, t_hi)
        ax_space.set_xlabel("hole diameter [mm]"); ax_space.set_ylabel("thickness [mm]")

        idx = np.arange(1, k + 2)
        masses = [np.nan if rejected(p) else p.mass_kg for p in path]
        colors = [grey if rejected(p) else (green if p.feasible else red) for p in path]
        ax_mass.scatter(idx, masses, c=colors, s=40, zorder=3)
        trace = [np.nan if b is None else b for b in best_trace[: k + 1]]
        ax_mass.step(idx, trace, where="post", color=green, lw=2.5)
        ax_mass.axhline(base_mass, color=muted, ls="--", lw=1.2)
        ax_mass.set_xlim(0.5, len(evals) + 0.5)
        ax_mass.set_xlabel("evaluation #"); ax_mass.set_ylabel("mass [kg]")

        if done:
            saving = (base_mass - result.optimal_mass_kg) / base_mass * 100
            title.set_text(f"Optimum: t = {result.optimal_thickness_mm:.2f} mm, Ø {result.optimal_hole_diameter_mm:.2f} mm"
                           f" -> {result.optimal_mass_kg:.3f} kg ({saving:+.1f}% vs baseline {base_mass:.3f} kg)")
            title.set_color(green)
        else:
            title.set_text(f"COBYLA evaluation {k + 1}/{len(evals)}")
            title.set_color(text)
        return []

    anim = animation.FuncAnimation(fig, draw, frames=n_frames, blit=False)
    out_path = os.path.abspath(out_path)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    if out_path.lower().endswith(".mp4") and shutil.which("ffmpeg"):
        writer = animation.FFMpegWriter(fps=fps, codec="libx264", extra_args=["-pix_fmt", "yuv420p", "-crf", "20"])
    else:
        out_path = os.path.splitext(out_path)[0] + ".gif"
        writer = animation.PillowWriter(fps=fps)
    anim.save(out_path, writer=writer, savefig_kwargs={"facecolor": bg})
    plt.close(fig)
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=os.path.join("artifacts", "bracket_optimization_2d.mp4"))
    parser.add_argument("--fps", type=int, default=20)
    args = parser.parse_args()

    problem, result = run_optimization()
    print(f"{len(result.evaluations)} evaluations; optimum t={result.optimal_thickness_mm:.3f} mm, "
          f"d={result.optimal_hole_diameter_mm:.3f} mm, mass={result.optimal_mass_kg:.4f} kg, "
          f"stress={result.stress_at_optimum_mpa:.3f} MPa")
    print(f"Animation written to {render_animation(problem, result, args.out, fps=args.fps)}")


if __name__ == "__main__":
    main()
