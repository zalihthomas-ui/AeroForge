"""Flagship Demo: Multidisciplinary UAV Wing Evaluation & Planform Sizing.

Demonstrates the full closed-loop AeroForge design workflow:
1. Formulates mission requirements for a 12.0 kg MTOW fixed-wing UAV at 25.0 m/s cruise.
2. Evaluates the baseline reference wing geometry, showing aerodynamic lift failure (65.7 N vs 117.72 N required).
3. Executes automated planform sizing (scipy.optimize.brentq) to scale chord dimensions to satisfy Lift == Weight.
4. Generates parametric 3D CAD solid geometry (build123d) and structural FEA (CalculiX) under aerodynamic lift.
5. Verifies all constraints (lift, structural safety factor >= 1.5, span <= 1800 mm) for final PASS status.
6. Exports production-ready CAD models (STEP, STL, 3MF).

Usage:
    python examples/wing/flagship_demo.py
"""

from __future__ import annotations

import os
import sys

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from agents.geometry.wing import build_wing
from cad.exporters import export_3mf, export_step, export_stl
from engineering.analysis.wing_flagship import (
    FlagshipDesignResult,
    WingDesignRequirement,
    evaluate_wing_design,
    find_passing_wing_design,
)
from engineering.requirements.schema import EngineeringSpec


def main() -> None:
    print("=" * 80)
    print(" AeroForge Multidisciplinary UAV Wing Evaluation & Planform Sizing Demo")
    print("=" * 80)

    # 1. Define UAV Mission Requirements
    mtow_kg = 12.0
    cruise_velocity_mps = 25.0
    max_span_mm = 1800.0
    min_safety_factor = 1.5
    required_lift_n = mtow_kg * 9.81

    requirement = WingDesignRequirement(
        mtow_kg=mtow_kg,
        cruise_velocity_mps=cruise_velocity_mps,
        max_span_mm=max_span_mm,
        min_safety_factor=min_safety_factor,
    )

    print("\n[1] MISSION REQUIREMENTS:")
    print(f"  * Maximum Takeoff Weight (MTOW): {mtow_kg:.2f} kg")
    print(f"  * Level Cruise Airspeed (V):      {cruise_velocity_mps:.2f} m/s (approx {(cruise_velocity_mps * 3.6):.1f} km/h)")
    print(f"  * Required Cruise Lift (L_req):  {required_lift_n:.2f} N (MTOW * 9.81 m/s^2)")
    print(f"  * Maximum Allowable Span:        {max_span_mm:.1f} mm")
    print(f"  * Minimum Structural Safety:     {min_safety_factor:.2f}")

    # 2. Define Baseline Reference Wing
    baseline_spec = EngineeringSpec(
        component="wing",
        parameters={
            "wing_span": 1800.0,
            "root_chord": 240.0,
            "tip_chord": 140.0,
            "sweep": 12.0,
            "dihedral": 4.0,
            "naca_airfoil": 12.0,
        },
    )

    print("\n[2] EVALUATING INITIAL BASELINE DESIGN:")
    print(f"  * Span: {baseline_spec.parameters['wing_span']:.1f} mm")
    print(f"  * Root Chord: {baseline_spec.parameters['root_chord']:.1f} mm")
    print(f"  * Tip Chord:  {baseline_spec.parameters['tip_chord']:.1f} mm")
    print(f"  * Airfoil:    NACA {int(baseline_spec.parameters['naca_airfoil']):04d}")

    initial_result = evaluate_wing_design(
        baseline_spec,
        requirement,
        alpha_deg=4.0,
        backend="neuralfoil",
    )

    print(f"  -> Produced Lift:    {initial_result.lift_n:.2f} N (Deficit: {(initial_result.lift_n - required_lift_n):.2f} N)")
    print(f"  -> Lift Adequate:    {initial_result.lift_adequate} (Target: >= {required_lift_n:.2f} N)")
    print(f"  -> Lift-to-Drag L/D: {initial_result.l_over_d:.2f}")
    print(f"  -> Safety Factor:    {initial_result.safety_factor:.2f} (Target: >= {min_safety_factor:.2f})")
    print(f"  -> Shell Mass (est): {initial_result.shell_mass_kg:.3f} kg (informational -- thin-skin estimate, not part of PASS/FAIL)")
    print(f"  -> Solid CAD Volume: {initial_result.solid_volume_mm3 * 1e-6:.4f} dm^3 (raw geometric fact, NOT a mass estimate)")
    print(f"  -> OVERALL STATUS:   [{initial_result.overall_status}]")

    # 3. Perform Closed-Loop Planform Sizing
    print("\n[3] RUNNING CLOSED-LOOP PLANFORM SIZING (scipy.optimize.brentq):")
    print("  -> Searching chord scale factor k in [1.0, 2.5] preserving span and taper ratio...")

    sized_result = find_passing_wing_design(
        baseline_spec,
        requirement,
        alpha_deg=4.0,
        backend="neuralfoil",
        chord_scale_bounds=(1.0, 2.5),
    )

    final_root = sized_result.spec_parameters["root_chord"]
    final_tip = sized_result.spec_parameters["tip_chord"]
    k_scale = final_root / baseline_spec.parameters["root_chord"]

    print(f"  -> Converged Chord Scale Factor k: {k_scale:.4f}")
    print(f"  -> Sized Root Chord:               {final_root:.2f} mm")
    print(f"  -> Sized Tip Chord:                {final_tip:.2f} mm")
    print(f"  -> Sized Span:                     {sized_result.spec_parameters['wing_span']:.1f} mm")
    print(f"  -> Final Lift:                     {sized_result.lift_n:.2f} N (Target: {required_lift_n:.2f} N)")
    print(f"  -> Final Lift-to-Drag L/D:         {sized_result.l_over_d:.2f}")
    print(f"  -> Final Safety Factor:            {sized_result.safety_factor:.2f} (Adequate: {sized_result.safety_adequate})")
    print(f"  -> Sized Shell Mass (est):         {sized_result.shell_mass_kg:.3f} kg (informational)")
    print(f"  -> Sized Solid CAD Volume:         {sized_result.solid_volume_mm3 * 1e-6:.4f} dm^3")
    print(f"  -> FINAL OVERALL STATUS:           [{sized_result.overall_status}]")

    # 4. Materialize and Export CAD Models
    output_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "artifacts", "wing_flagship"))
    os.makedirs(output_dir, exist_ok=True)

    print(f"\n[4] EXPORTING SIZED CAD ARTIFACTS TO {output_dir}:")
    sized_part = build_wing(sized_result.spec_parameters)
    step_path = os.path.join(output_dir, "wing_flagship_sized.step")
    stl_path = os.path.join(output_dir, "wing_flagship_sized.stl")
    threemf_path = os.path.join(output_dir, "wing_flagship_sized.3mf")

    export_step(sized_part, step_path)
    export_stl(sized_part, stl_path)
    export_3mf(sized_part, threemf_path)

    print(f"  * STEP: {step_path}")
    print(f"  * STL:  {stl_path}")
    print(f"  * 3MF:  {threemf_path}")

    # 5. Summary Table
    print("\n" + "=" * 80)
    print(" MULTIDISCIPLINARY SIZING SUMMARY")
    print("=" * 80)
    print(f"{'Metric':<30} | {'Initial Baseline':<20} | {'Sized Wing':<20}")
    print("-" * 76)
    print(f"{'Root Chord (mm)':<30} | {baseline_spec.parameters['root_chord']:<20.1f} | {final_root:<20.1f}")
    print(f"{'Tip Chord (mm)':<30} | {baseline_spec.parameters['tip_chord']:<20.1f} | {final_tip:<20.1f}")
    print(f"{'Wing Span (mm)':<30} | {baseline_spec.parameters['wing_span']:<20.1f} | {sized_result.spec_parameters['wing_span']:<20.1f}")
    print(f"{'Shell Mass, est. (kg)':<30} | {initial_result.shell_mass_kg:<20.3f} | {sized_result.shell_mass_kg:<20.3f}")
    print(f"{'Produced Lift (N)':<30} | {initial_result.lift_n:<20.2f} | {sized_result.lift_n:<20.2f}")
    print(f"{'Required Lift (N)':<30} | {required_lift_n:<20.2f} | {required_lift_n:<20.2f}")
    print(f"{'Lift Adequate':<30} | {str(initial_result.lift_adequate):<20} | {str(sized_result.lift_adequate):<20}")
    print(f"{'Lift-to-Drag (L/D)':<30} | {initial_result.l_over_d:<20.2f} | {sized_result.l_over_d:<20.2f}")
    print(f"{'Safety Factor':<30} | {initial_result.safety_factor:<20.2f} | {sized_result.safety_factor:<20.2f}")
    print(f"{'Overall Status':<30} | {initial_result.overall_status:<20} | {sized_result.overall_status:<20}")
    print("=" * 80)


if __name__ == "__main__":
    main()
