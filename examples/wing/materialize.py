"""v0.9 demonstration: end-to-end requirement -> design -> optimization -> revised CAD materialization.

Demonstrates the complete closed-loop workflow:
1. Requirement text -> parsed by Design Agent into an EngineeringSpec.
2. optimize_wing_for_max_l_over_d -> searches candidate airfoil sections and optimal alpha for max L/D.
3. materialize_optimal_wing -> generates the revised 3D CAD solid via build123d, exports to STEP/STL/3MF,
   and runs a consistency re-analysis verifying that the final CAD model reproduces the optimizer's metrics.

Run from repo root: python examples/wing/materialize.py
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from agents.design.agent import DesignAgent  # noqa: E402
from engineering.analysis.wing_materializer import materialize_optimal_wing  # noqa: E402
from engineering.analysis.wing_optimizer import optimize_wing_for_max_l_over_d  # noqa: E402

REQUIREMENT_TEXT = (
    "Design a fixed-wing UAV main wing with span 1800mm, root chord 240mm, tip chord 140mm, "
    "sweep 12deg, dihedral 4deg, and baseline NACA 0012 airfoil for cruise at 25 m/s."
)
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")


def main() -> None:
    print("=" * 80)
    print("AEROFORGE: END-TO-END CLOSED-LOOP WING OPTIMIZATION & CAD MATERIALIZATION")
    print("=" * 80)
    print(f"\n[1] Natural Language Requirement:\n  \"{REQUIREMENT_TEXT}\"")

    # Step 1: Design Agent parsing
    design_agent = DesignAgent()
    base_spec = design_agent.parse(REQUIREMENT_TEXT)
    print(f"\n[2] Design Agent Specification:\n  Component: {base_spec.component}")
    for k, v in sorted(base_spec.parameters.items()):
        print(f"  - {k}: {v}")

    # Step 2: Aerodynamic optimization across candidate sections
    print("\n[3] Closed-Loop Aerodynamic Optimization (scipy bounded scalar minimization)...")
    t0 = time.time()
    candidates = ["0009", "0012", "2412", "4412", "2415"]
    opt_result = optimize_wing_for_max_l_over_d(
        base_spec,
        candidate_naca_airfoils=candidates,
        alpha_bounds_deg=(-2.0, 12.0),
        cruise_velocity_mps=25.0,
        backend="neuralfoil",
    )
    t_opt = time.time() - t0

    print(f"{'Airfoil':<10} {'Opt Alpha (deg)':<18} {'Max L/D':<12} {'CL':<10} {'CD':<10}")
    print("-" * 60)
    for cand in opt_result.all_candidates:
        mark = " <-- OPTIMAL WINNER" if cand.naca_airfoil == opt_result.optimal_naca_airfoil else ""
        print(
            f"NACA {cand.naca_airfoil:<5} {cand.optimal_alpha_deg:<18.2f} {cand.max_l_over_d:<12.2f} "
            f"{cand.cl_at_optimum:<10.4f} {cand.cd_at_optimum:<10.4f}{mark}"
        )
    print("-" * 60)
    print(f"Optimization Completed in {t_opt:.2f}s")

    # Step 3: Materialize revised CAD geometry and run consistency re-analysis
    print("\n[4] Materializing Revised CAD Geometry & Consistency Re-analysis...")
    t1 = time.time()
    mat_result = materialize_optimal_wing(
        base_spec,
        opt_result,
        output_dir=OUTPUT_DIR,
        cruise_velocity_mps=25.0,
        backend="neuralfoil",
        tolerance_pct=0.1,
        filename_prefix="wing_optimized",
    )
    t_mat = time.time() - t1

    print(f"Materialization Completed in {t_mat:.2f}s")

    print("\n" + "=" * 80)
    print("FINAL MATERIALIZED ARTIFACTS")
    print("=" * 80)
    for fmt, path in [
        ("STEP", mat_result.step_path),
        ("STL", mat_result.stl_path),
        ("3MF", mat_result.threemf_path),
    ]:
        size_kb = os.path.getsize(path) / 1024.0 if os.path.isfile(path) else 0.0
        print(f"  {fmt:<6}: {path} ({size_kb:.1f} KB)")

    print("\n" + "=" * 80)
    print("CONSISTENCY RE-ANALYSIS VERIFICATION")
    print("=" * 80)
    print(f"Optimal NACA Airfoil:       NACA {opt_result.optimal_naca_airfoil}")
    print(f"Optimal Alpha (deg):        {opt_result.optimal_alpha_deg:.2f}")
    print(f"Optimizer Reported Max L/D: {opt_result.max_l_over_d:.4f}")
    print(f"CAD Spec Re-analysis L/D:   {mat_result.reanalysis.l_over_d:.4f}")
    print(f"L/D Discrepancy:            {mat_result.l_over_d_discrepancy_pct:.4f}%")
    print(f"Re-analysis Matches Optimum: {mat_result.reanalysis_matches_optimum} (tolerance <= 0.10%)")
    print(f"Re-analysis Lift Force:     {mat_result.reanalysis.lift_n:.2f} N")
    print(f"Re-analysis Drag Force:     {mat_result.reanalysis.drag_n:.2f} N")
    print("=" * 80)


if __name__ == "__main__":
    main()
