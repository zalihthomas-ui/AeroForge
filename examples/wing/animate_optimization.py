"""Animate the closed-loop wing aerodynamic optimizer, one solver call per frame.

`optimize_wing_for_max_l_over_d` searches each candidate NACA section for the
angle of attack with maximum L/D (scipy bounded scalar minimization), then
keeps the best section. This script records every aerodynamic evaluation the
optimizer actually makes and animates them:

- left:  the airfoil section being evaluated (true NACA 4-digit geometry,
         morphing between candidates) at the current angle of attack
- right: L/D vs angle of attack for every probe so far, per candidate
- below: best L/D found so far vs evaluation number (convergence)

The planform is fixed by this optimizer (it varies section + alpha only),
so the morphing shown is the section shape, not the planform.

Usage (repo root):
    python examples/wing/animate_optimization.py --out artifacts/wing_optimization.mp4
    python examples/wing/animate_optimization.py --out wing_opt.gif --fps 12
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from contextlib import contextmanager
from dataclasses import dataclass

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import numpy as np

import engineering.analysis.wing_optimizer as wing_optimizer
from engineering.requirements.schema import EngineeringSpec

REFERENCE_WING = {
    "wing_span": 1800.0,
    "root_chord": 240.0,
    "tip_chord": 140.0,
    "sweep": 12.0,
    "dihedral": 4.0,
    "naca_airfoil": 12.0,
}


@dataclass
class AeroProbe:
    """One aerodynamic evaluation made by the optimizer, in call order."""

    index: int
    naca_airfoil: str
    alpha_deg: float
    l_over_d: float
    cl: float
    cd: float


@contextmanager
def _recording_aero(history: list[AeroProbe]):
    """Temporarily wrap the optimizer's aero evaluator to log every call."""
    original = wing_optimizer.evaluate_wing_aero

    def recorder(spec, **kwargs):
        summary = original(spec, **kwargs)
        history.append(AeroProbe(
            index=len(history),
            naca_airfoil=f"{int(spec.parameters.get('naca_airfoil', 12.0)):04d}",
            alpha_deg=float(kwargs.get("alpha_deg", 0.0)),
            l_over_d=float(summary.l_over_d),
            cl=float(summary.cl),
            cd=float(summary.cd),
        ))
        return summary

    wing_optimizer.evaluate_wing_aero = recorder
    try:
        yield
    finally:
        wing_optimizer.evaluate_wing_aero = original


def record_wing_optimization(
    base_spec: EngineeringSpec | None = None,
    candidate_naca_airfoils: list[str] | None = None,
    alpha_bounds_deg: tuple[float, float] = (-2.0, 12.0),
    cruise_velocity_mps: float = 25.0,
    backend: str = "neuralfoil",
):
    """Run the real optimizer and return (result, probes in call order)."""
    spec = base_spec or EngineeringSpec(component="wing", parameters=dict(REFERENCE_WING))
    history: list[AeroProbe] = []
    with _recording_aero(history):
        result = wing_optimizer.optimize_wing_for_max_l_over_d(
            spec,
            candidate_naca_airfoils=candidate_naca_airfoils,
            alpha_bounds_deg=alpha_bounds_deg,
            cruise_velocity_mps=cruise_velocity_mps,
            backend=backend,
        )
    return result, history


def naca4_coordinates(code: str, n: int = 80) -> tuple[np.ndarray, np.ndarray]:
    """Closed NACA 4-digit outline (unit chord), upper surface TE->LE then lower LE->TE."""
    m, p, t = int(code[0]) / 100.0, int(code[1]) / 10.0, int(code[2:]) / 100.0
    beta = np.linspace(0.0, np.pi, n)
    x = 0.5 * (1 - np.cos(beta))
    yt = 5 * t * (0.2969 * np.sqrt(x) - 0.1260 * x - 0.3516 * x**2 + 0.2843 * x**3 - 0.1036 * x**4)
    if m > 0 and p > 0:
        yc = np.where(x < p, m / p**2 * (2 * p * x - x**2), m / (1 - p) ** 2 * (1 - 2 * p + 2 * p * x - x**2))
        dyc = np.where(x < p, 2 * m / p**2 * (p - x), 2 * m / (1 - p) ** 2 * (p - x))
    else:
        yc = np.zeros_like(x)
        dyc = np.zeros_like(x)
    th = np.arctan(dyc)
    xu, yu = x - yt * np.sin(th), yc + yt * np.cos(th)
    xl, yl = x + yt * np.sin(th), yc - yt * np.cos(th)
    return np.concatenate([xu[::-1], xl[1:]]), np.concatenate([yu[::-1], yl[1:]])


def render_animation(result, history: list[AeroProbe], out_path: str, fps: int = 20,
                     frames_per_probe: int = 6) -> str:
    """Render the recorded probes to an animation (.mp4 via ffmpeg, else .gif)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import animation

    if not history:
        raise ValueError("No optimizer probes recorded -- nothing to animate.")

    bg, panel, text, muted = "#0B0F14", "#111821", "#E6EDF3", "#8FA1B3"
    palette = ["#4FC3F7", "#FFB300", "#F06292", "#66BB6A", "#B388FF", "#FF8A50"]
    codes = list(dict.fromkeys(p.naca_airfoil for p in history))
    color = {c: palette[i % len(palette)] for i, c in enumerate(codes)}
    shapes = {c: naca4_coordinates(c) for c in codes}

    plt.rcParams.update({"text.color": text, "axes.labelcolor": text, "xtick.color": muted,
                         "ytick.color": muted, "axes.edgecolor": "#2C3B4C", "font.size": 13})
    fig = plt.figure(figsize=(12.8, 7.2), dpi=100, facecolor=bg)
    ax_foil = fig.add_axes([0.05, 0.42, 0.42, 0.45], facecolor=panel)
    ax_ld = fig.add_axes([0.56, 0.42, 0.40, 0.45], facecolor=panel)
    ax_conv = fig.add_axes([0.08, 0.09, 0.88, 0.22], facecolor=panel)
    title = fig.text(0.05, 0.94, "", fontsize=18, fontweight="bold")
    fig.text(0.95, 0.94, "AeroForge wing optimizer · max L/D", ha="right", color=muted, fontsize=13)

    a_lo = min(p.alpha_deg for p in history) - 0.5
    a_hi = max(p.alpha_deg for p in history) + 0.5
    ld_hi = max(p.l_over_d for p in history) * 1.12
    best_so_far = np.maximum.accumulate([p.l_over_d for p in history])
    n_frames = len(history) * frames_per_probe + fps * 2  # hold the final state for 2 s

    def draw(frame: int):
        k = min(frame // frames_per_probe, len(history) - 1)
        u = min(1.0, (frame % frames_per_probe + 1) / frames_per_probe) if frame < len(history) * frames_per_probe else 1.0
        probe = history[k]
        prev = history[k - 1] if k > 0 else probe

        ax_foil.cla(); ax_ld.cla(); ax_conv.cla()
        for ax in (ax_foil, ax_ld, ax_conv):
            ax.set_facecolor(panel)
            ax.grid(color="#223040", lw=0.8)

        # section: morph from the previous probe's shape/alpha to this one
        x0, y0 = shapes[prev.naca_airfoil]
        x1, y1 = shapes[probe.naca_airfoil]
        xs, ys = x0 + (x1 - x0) * u, y0 + (y1 - y0) * u
        alpha = np.radians(prev.alpha_deg + (probe.alpha_deg - prev.alpha_deg) * u)
        xr = (xs - 0.25) * np.cos(alpha) + ys * np.sin(alpha)
        yr = -(xs - 0.25) * np.sin(alpha) + ys * np.cos(alpha)
        ax_foil.fill(xr, yr, color=color[probe.naca_airfoil], alpha=0.35)
        ax_foil.plot(xr, yr, color=color[probe.naca_airfoil], lw=2.5)
        ax_foil.annotate("", (-0.55, 0.0), (-0.85, 0.0), arrowprops=dict(arrowstyle="->", color=muted, lw=1.5))
        ax_foil.text(-0.85, 0.04, "V∞", color=muted)
        ax_foil.set_xlim(-0.9, 0.95); ax_foil.set_ylim(-0.42, 0.42); ax_foil.set_aspect("equal")
        ax_foil.set_xticks([]); ax_foil.set_yticks([])
        ax_foil.set_title(f"NACA {probe.naca_airfoil}  ·  α = {np.degrees(alpha):.2f}°", color=text, fontsize=15)

        for c in codes:
            pts = [p for p in history[: k + 1] if p.naca_airfoil == c]
            if pts:
                ax_ld.plot([p.alpha_deg for p in pts], [p.l_over_d for p in pts], "o", ms=6,
                           color=color[c], alpha=0.85, label=f"NACA {c}")
        ax_ld.plot([probe.alpha_deg], [probe.l_over_d], "o", ms=14, mfc="none", mec=text, mew=2)
        ax_ld.set_xlim(a_lo, a_hi); ax_ld.set_ylim(min(0.0, min(p.l_over_d for p in history)), ld_hi)
        ax_ld.set_xlabel("angle of attack α [deg]"); ax_ld.set_ylabel("section L/D")
        ax_ld.legend(loc="lower right", facecolor=panel, edgecolor="#2C3B4C", fontsize=11, labelcolor=text)

        ax_conv.plot(np.arange(1, k + 2), best_so_far[: k + 1], color="#66BB6A", lw=2.5)
        ax_conv.plot(np.arange(1, k + 2), [p.l_over_d for p in history[: k + 1]], ".", color=muted, ms=5)
        ax_conv.set_xlim(0.5, len(history) + 0.5); ax_conv.set_ylim(0, ld_hi)
        ax_conv.set_xlabel("aero evaluation #"); ax_conv.set_ylabel("best L/D")

        done = frame >= len(history) * frames_per_probe
        if done:
            title.set_text(f"Optimum: NACA {result.optimal_naca_airfoil} at α = {result.optimal_alpha_deg:.2f}°"
                           f"  ->  L/D = {result.max_l_over_d:.1f}")
            title.set_color("#66BB6A")
        else:
            title.set_text(f"Evaluation {k + 1}/{len(history)}  ·  L/D = {probe.l_over_d:.1f}"
                           f"  ·  best so far {best_so_far[k]:.1f}")
            title.set_color(text)
        return []

    anim = animation.FuncAnimation(fig, draw, frames=n_frames, blit=False)
    out_path = os.path.abspath(out_path)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    if out_path.lower().endswith(".mp4") and shutil.which("ffmpeg"):
        writer = animation.FFMpegWriter(fps=fps, codec="libx264",
                                        extra_args=["-pix_fmt", "yuv420p", "-crf", "20"])
    else:
        out_path = os.path.splitext(out_path)[0] + ".gif"
        writer = animation.PillowWriter(fps=fps)
    anim.save(out_path, writer=writer, savefig_kwargs={"facecolor": bg})
    plt.close(fig)
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=os.path.join("artifacts", "wing_optimization.mp4"))
    parser.add_argument("--backend", default="neuralfoil", choices=["neuralfoil", "xfoil"])
    parser.add_argument("--fps", type=int, default=20)
    args = parser.parse_args()

    result, history = record_wing_optimization(backend=args.backend)
    print(f"Recorded {len(history)} aerodynamic evaluations across "
          f"{len({p.naca_airfoil for p in history})} candidate sections.")
    print(f"Optimum: NACA {result.optimal_naca_airfoil}, alpha={result.optimal_alpha_deg:.2f} deg, "
          f"L/D={result.max_l_over_d:.2f}")
    path = render_animation(result, history, args.out, fps=args.fps)
    print(f"Animation written to {path}")


if __name__ == "__main__":
    main()
