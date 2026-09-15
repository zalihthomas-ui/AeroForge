"""v0.8 demonstration: closed-loop bracket thickness optimization for minimum mass.

Finds the thinnest (lightest) mounting bracket that satisfies a maximum allowable
von Mises stress constraint under a real bolted-mounting load case using CalculiX 3D solid FEA
and bounded 1D root-finding (scipy.optimize.brentq).

Problem statement:
    Minimize: Mass(thickness)
    Subject to: max_stress(thickness) <= max_allowable_stress_mpa
    Where thickness in [t_min, t_max]

Run from the repo root: python examples/bracket/optimize.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from agents.structures.agent import CALCULIX_AVAILABLE  # noqa: E402
from engineering.analysis.bracket_optimizer import (  # noqa: E402
    BracketOptimizationResult,
    optimize_bracket_thickness_for_min_mass,
)

# Reference bracket parameters
LENGTH_MM = 100.0
WIDTH_MM = 80.0
HOLE_DIAMETER_MM = 8.0
HOLE_COUNT = 4
APPLIED_FORCE_N = 500.0
MAX_ALLOWABLE_STRESS_MPA = 6.50  # Baseline 5mm bracket's hotspot_stress_mpa is ~5.48 MPa
THICKNESS_BOUNDS_MM = (3.0, 8.0)


def main() -> None:
    if not CALCULIX_AVAILABLE:
        print(
            "CalculiX (ccx.exe) not found -- install it with "
            "scripts/install_calculix_windows.sh, see vendor/calculix/README.md."
        )
        return

    print("=" * 80)
    print("AEROSPACE MOUNTING BRACKET: CLOSED-LOOP THICKNESS OPTIMIZER")
    print("=" * 80)
    print(f"Geometry: {LENGTH_MM:.0f} x {WIDTH_MM:.0f} mm plate with {HOLE_COUNT} x {HOLE_DIAMETER_MM:.0f} mm holes")
    print(f"Applied Load: {APPLIED_FORCE_N:.0f} N (transverse -Z on top face)")
    print(f"Allowable Stress: {MAX_ALLOWABLE_STRESS_MPA:.2f} MPa")
    print(f"Search Bounds: [{THICKNESS_BOUNDS_MM[0]:.1f}, {THICKNESS_BOUNDS_MM[1]:.1f}] mm")
    print("Optimization Method: Bounded 1D Root-Finding (Brent's method via scipy.optimize.brentq)")
    print("-" * 80)

    start_time = time.time()

    result: BracketOptimizationResult = optimize_bracket_thickness_for_min_mass(
        length_mm=LENGTH_MM,
        width_mm=WIDTH_MM,
        hole_diameter_mm=HOLE_DIAMETER_MM,
        hole_count=HOLE_COUNT,
        applied_force_n=APPLIED_FORCE_N,
        max_allowable_stress_mpa=MAX_ALLOWABLE_STRESS_MPA,
        thickness_bounds_mm=THICKNESS_BOUNDS_MM,
        xtol_mm=0.05,
        maxiter=15,
    )

    elapsed_s = time.time() - start_time

    print("\n" + "=" * 80)
    print("EVALUATION HISTORY")
    print("=" * 80)
    print(f"{'Eval #':<8} {'Thickness (mm)':<16} {'Mass (g)':<12} {'Max Stress (MPa)':<18} {'Mesh Converged':<16}")
    print("-" * 80)

    for i, pt in enumerate(result.evaluations, start=1):
        print(
            f"{i:<8} {pt.thickness_mm:<16.4f} {pt.mass_kg * 1000.0:<12.2f} "
            f"{pt.hotspot_stress_mpa:<18.4f} {str(pt.mesh_converged):<16}"
        )

    print("-" * 80)
    print(f"Total Evaluations: {len(result.evaluations)}")
    print(f"Optimization Elapsed Time: {elapsed_s:.1f} s ({elapsed_s / 60.0:.2f} min)")

    print("\n" + "=" * 80)
    print("OPTIMAL DESIGN SUMMARY")
    print("=" * 80)
    print(f"Optimal Thickness:      {result.optimal_thickness_mm:.4f} mm")
    print(f"Optimal Bracket Mass:   {result.optimal_mass_kg * 1000.0:.2f} g ({result.optimal_mass_kg:.4f} kg)")
    print(f"Peak Von Mises Stress:  {result.max_stress_at_optimum_mpa:.4f} MPa")
    print(f"Allowable Stress Limit: {result.max_allowable_stress_mpa:.4f} MPa")
    stress_delta_pct = (
        (result.max_stress_at_optimum_mpa - result.max_allowable_stress_mpa)
        / result.max_allowable_stress_mpa
        * 100.0
    )
    print(f"Stress Constraint Diff: {stress_delta_pct:+.2f}% (active constraint target: 0.00%)")
    print("=" * 80)


if __name__ == "__main__":
    main()
