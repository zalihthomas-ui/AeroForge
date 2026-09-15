"""Example: 2D Bracket Optimization (Thickness and Hole Diameter).

Demonstrates multi-parameter derivative-free constrained optimization (COBYLA)
to minimize bracket mass while satisfying structural stress and geometric constraints.

Usage:
    python examples/bracket/optimize_2d.py
"""

from __future__ import annotations

import os
import sys

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from engineering.analysis.bracket_optimizer import calculate_bracket_mass
from engineering.analysis.bracket_optimizer_2d import (
    BracketOptimization2DResult,
    optimize_bracket_thickness_and_hole_for_min_mass,
)


def main() -> None:
    print("=" * 80)
    print(" AeroForge Multi-Parameter 2D Bracket Optimization (Thickness & Hole Diameter)")
    print("=" * 80)

    # 1. Problem Specification
    length_mm = 100.0
    width_mm = 80.0
    hole_count = 4
    applied_force_n = 500.0
    max_allowable_stress_mpa = 6.50
    t_bounds = (2.0, 10.0)
    d_bounds = (4.0, 15.0)
    max_evals = 18

    print("\n[1] OPTIMIZATION PROBLEM:")
    print(f"  * Bracket Dimensions:      {length_mm:.1f} mm x {width_mm:.1f} mm")
    print(f"  * Mounting Holes:          {hole_count} through-holes")
    print(f"  * Transverse Load:         {applied_force_n:.1f} N")
    print(f"  * Max Allowable Stress:    {max_allowable_stress_mpa:.2f} MPa")
    print(f"  * Thickness Bounds:        {t_bounds[0]:.1f} - {t_bounds[1]:.1f} mm")
    print(f"  * Hole Diameter Bounds:    {d_bounds[0]:.1f} - {d_bounds[1]:.1f} mm")
    print(f"  * Evaluation Budget:       {max_evals} iterations (COBYLA)")

    # Baseline reference design
    baseline_t = 5.0
    baseline_d = 8.0
    baseline_mass = calculate_bracket_mass(length_mm, width_mm, baseline_t, baseline_d, hole_count)

    print(f"\n  * Reference 1D Design:     t={baseline_t:.1f} mm, d={baseline_d:.1f} mm -> mass={baseline_mass:.4f} kg")

    # 2. Execute 2D Optimization
    print("\n[2] RUNNING COBYLA 2D CONSTRAINED SEARCH...")
    result = optimize_bracket_thickness_and_hole_for_min_mass(
        length_mm=length_mm,
        width_mm=width_mm,
        hole_count=hole_count,
        applied_force_n=applied_force_n,
        max_allowable_stress_mpa=max_allowable_stress_mpa,
        thickness_bounds_mm=t_bounds,
        hole_diameter_bounds_mm=d_bounds,
        max_evaluations=max_evals,
    )

    # 3. Print Evaluation History
    print("\n[3] EVALUATION HISTORY:")
    print("-" * 80)
    print(f"{'#':<3} | {'Thickness (mm)':<14} | {'Hole Dia (mm)':<14} | {'Mass (kg)':<10} | {'Stress (MPa)':<12} | {'Feasible'}")
    print("-" * 80)
    for idx, eval_pt in enumerate(result.evaluations, 1):
        feas_str = "YES" if eval_pt.feasible else "NO"
        stress_str = f"{eval_pt.hotspot_stress_mpa:.3f}" if eval_pt.hotspot_stress_mpa < 1e5 else "PENALTY"
        mass_str = f"{eval_pt.mass_kg:.4f}" if eval_pt.mass_kg < 50.0 else "PENALTY"
        print(f"{idx:<3} | {eval_pt.thickness_mm:<14.3f} | {eval_pt.hole_diameter_mm:<14.3f} | {mass_str:<10} | {stress_str:<12} | {feas_str}")
    print("-" * 80)

    # 4. Optimal Result Summary
    mass_saving_pct = (baseline_mass - result.optimal_mass_kg) / baseline_mass * 100.0

    print("\n[4] OPTIMAL 2D DESIGN RESULT:")
    print(f"  * Optimal Thickness:       {result.optimal_thickness_mm:.3f} mm")
    print(f"  * Optimal Hole Diameter:   {result.optimal_hole_diameter_mm:.3f} mm")
    print(f"  * Optimal Mass:            {result.optimal_mass_kg:.4f} kg ({mass_saving_pct:+.1f}% vs baseline)")
    print(f"  * Von Mises Hotspot Stress:{result.stress_at_optimum_mpa:.3f} MPa (Allowable: {max_allowable_stress_mpa:.2f} MPa)")
    print(f"  * Converged:               {result.converged}")
    print("=" * 80)


if __name__ == "__main__":
    main()
