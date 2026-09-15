"""v0.10 demonstration: closed-loop bracket thickness optimization & CAD materialization.

Demonstrates the complete closed-loop bracket workflow:
1. optimize_bracket_thickness_for_min_mass -> finds the minimum-mass thickness meeting the stress limit.
2. materialize_optimal_bracket -> generates the revised 3D CAD solid via build123d, exports to STEP/STL/3MF,
   and runs a consistency re-analysis verifying that the final CAD model reproduces the optimizer's FEA metrics.

Run from repo root: python examples/bracket/materialize.py
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from agents.structures.agent import CALCULIX_AVAILABLE  # noqa: E402
from engineering.analysis.bracket_materializer import materialize_optimal_bracket  # noqa: E402
from engineering.analysis.bracket_optimizer import optimize_bracket_thickness_for_min_mass  # noqa: E402

LENGTH_MM = 100.0
WIDTH_MM = 80.0
HOLE_DIAMETER_MM = 8.0
HOLE_COUNT = 4
APPLIED_FORCE_N = 500.0
MAX_ALLOWABLE_STRESS_MPA = 6.50
THICKNESS_BOUNDS_MM = (3.0, 8.0)
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")


def main() -> None:
    if not CALCULIX_AVAILABLE:
        print(
            "CalculiX (ccx.exe) not found -- install it with "
            "scripts/install_calculix_windows.sh, see vendor/calculix/README.md."
        )
        return

    print("=" * 80)
    print("AEROFORGE: CLOSED-LOOP BRACKET OPTIMIZATION & CAD MATERIALIZATION")
    print("=" * 80)
    print(f"Geometry: {LENGTH_MM:.0f} x {WIDTH_MM:.0f} mm plate with {HOLE_COUNT} x {HOLE_DIAMETER_MM:.0f} mm holes")
    print(f"Applied Load: {APPLIED_FORCE_N:.0f} N (transverse -Z on top face)")
    print(f"Target Hotspot Stress Limit: {MAX_ALLOWABLE_STRESS_MPA:.2f} MPa")
    print("-" * 80)

    # Step 1: Optimize thickness for minimum mass
    print("\n[1] Running Closed-Loop FEA Thickness Optimization (Brent's root-finding)...")
    t0 = time.time()
    opt_result = optimize_bracket_thickness_for_min_mass(
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
    t_opt = time.time() - t0
    print(f"Optimization completed in {t_opt:.1f} s ({t_opt/60.0:.2f} min) across {len(opt_result.evaluations)} evaluations.")

    # Step 2: Materialize revised CAD solid and run consistency re-analysis
    print("\n[2] Materializing Revised CAD Geometry & Executing Consistency Re-analysis...")
    t1 = time.time()
    mat_result = materialize_optimal_bracket(
        length_mm=LENGTH_MM,
        width_mm=WIDTH_MM,
        hole_diameter_mm=HOLE_DIAMETER_MM,
        hole_count=HOLE_COUNT,
        applied_force_n=APPLIED_FORCE_N,
        optimization_result=opt_result,
        output_dir=OUTPUT_DIR,
        tolerance_pct=0.5,
        filename_prefix="bracket_optimized",
    )
    t_mat = time.time() - t1
    print(f"CAD materialization and re-analysis completed in {t_mat:.1f} s.")

    print("\n" + "=" * 80)
    print("FINAL MATERIALIZED BRACKET ARTIFACTS")
    print("=" * 80)
    for fmt, path in [
        ("STEP", mat_result.step_path),
        ("STL", mat_result.stl_path),
        ("3MF", mat_result.threemf_path),
    ]:
        size_kb = os.path.getsize(path) / 1024.0 if os.path.isfile(path) else 0.0
        print(f"  {fmt:<6}: {path} ({size_kb:.1f} KB)")

    print("\n" + "=" * 80)
    print("STRUCTURAL CONSISTENCY RE-ANALYSIS VERIFICATION")
    print("=" * 80)
    print(f"Optimal Thickness:          {opt_result.optimal_thickness_mm:.4f} mm")
    print(f"Optimal Bracket Mass:       {opt_result.optimal_mass_kg * 1000.0:.2f} g")
    print(f"Optimizer Reported Stress:  {opt_result.max_stress_at_optimum_mpa:.4f} MPa")
    print(f"Materialized Re-analysis:   {mat_result.reanalysis.hotspot_stress_mpa:.4f} MPa")
    print(f"Stress Discrepancy:         {mat_result.stress_discrepancy_pct:.4f}%")
    print(f"Re-analysis Matches:        {mat_result.reanalysis_matches_optimum} (tolerance <= 0.50%)")
    print(f"Mesh Converged:             {mat_result.reanalysis.mesh_converged}")
    print(f"Force Equilibrium Error:    {mat_result.reanalysis.equilibrium_error_pct:.6f}%")
    print("=" * 80)


if __name__ == "__main__":
    main()
