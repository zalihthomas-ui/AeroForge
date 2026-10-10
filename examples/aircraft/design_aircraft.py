"""Whole-aircraft layout around the v0.14 campaign wing (v0.15).

Wing (lifting line + sized structure) -> empennage by tail-volume coefficients
-> fuselage sized around the systems -> mass & balance -> neutral point (VLM +
fuselage increment) -> wing placed for 10 % static margin -> cruise trim ->
labelled full-aircraft STEP assembly + one STEP per part.

Usage:
    python examples/aircraft/design_aircraft.py [--out artifacts/aircraft]
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from cad.exporters import export_parts_step, export_step_assembly
from engineering.analysis.aircraft_layout import (
    V_H_DEFAULT,
    V_V_DEFAULT,
    build_aircraft_assembly,
    design_aircraft,
)
from engineering.analysis.wing_campaign import (
    CampaignRequirement,
    build_structure_cad,
    run_campaign,
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join("artifacts", "aircraft"))
    args = ap.parse_args()

    campaign = run_campaign(CampaignRequirement(), run_fe=False)
    structure = build_structure_cad(campaign)
    d = design_aircraft(campaign, structure.masses_kg())
    t = d.tail
    line = "=" * 78
    print(line, "\n AeroForge v0.15 -- whole aircraft: fuselage, tail, mass & balance, stability\n", line, sep="")
    print(f"\n[1] Wing (v0.14): NACA {campaign.aero.naca}, root/tip {campaign.aero.root_chord_mm:.0f}/"
          f"{campaign.aero.tip_chord_mm:.0f} mm, MAC {d.mac_mm:.1f} mm, structure {sum(structure.masses_kg().values()):.2f} kg")
    print(f"\n[2] Empennage (Raymer Table 6.4: V_H = {V_H_DEFAULT}, V_V = {V_V_DEFAULT}), tail arm {t.l_h_mm:.0f} mm")
    print(f"  horizontal: NACA {t.htail.naca}, S {2 * t.htail.area_mm2 / 1e6:.4f} m^2, span {2 * t.htail.span_mm:.0f} mm, "
          f"root/tip {t.htail.root_chord_mm:.0f}/{t.htail.tip_chord_mm:.0f} mm, elevator {1 - t.htail.hinge_xc:.0%} chord")
    print(f"  vertical:   NACA {t.vtail.naca}, S {t.vtail.area_mm2 / 1e6:.4f} m^2, height {t.vtail.span_mm:.0f} mm, "
          f"rudder {1 - t.vtail.hinge_xc:.0%} chord")
    print("\n[3] Mass & balance (station from nose)")
    for it in d.mass_items:
        print(f"  {it.name:18s} {it.mass_kg:6.3f} kg  x {it.x_mm:7.1f} mm")
    print(f"  {'total':18s} {d.total_mass_kg:6.3f} kg  CG x {d.x_cg_mm:.1f} mm ({(d.x_cg_mm - d.x_mac_le_mm) / d.mac_mm:.1%} MAC)")
    print("\n[4] Static stability")
    print(f"  neutral point: VLM (wing+tails) {d.x_np_vlm_mm:.1f} mm; fuselage increment (AeroBuildup) "
          f"{d.x_np_aerobuildup_mm - d.x_np_aerobuildup_nofus_mm:+.1f} mm -> design NP {d.x_np_mm:.1f} mm")
    print(f"  wing leading edge placed at x = {d.wing_x_le_mm:.1f} mm -> static margin {d.static_margin:.1%} MAC")
    print(f"\n[5] Cruise trim (CL {d.cl_cruise:.3f}): alpha {d.trim_alpha_deg:.2f} deg, elevator "
          f"{d.trim_elevator_deg:+.2f} deg (AeroBuildup); VLM all-moving-tail equivalent {d.trim_elevator_vlm_deg:+.2f} deg")

    aircraft = build_aircraft_assembly(d, structure)
    os.makedirs(args.out, exist_ok=True)
    step = os.path.join(args.out, "aircraft_assembly.step")
    export_step_assembly(aircraft, step)
    parts = export_parts_step(aircraft, os.path.join(args.out, "parts"))
    print(f"\n[6] CAD: {step} ({len(aircraft.solids())} solids in {len(aircraft.children)} groups), "
          f"{len(parts)} part files")
    report = {
        "tail": {"l_h_mm": t.l_h_mm, "S_h_m2": 2 * t.htail.area_mm2 / 1e6, "S_v_m2": t.vtail.area_mm2 / 1e6,
                 "V_H": V_H_DEFAULT, "V_V": V_V_DEFAULT},
        "mass_items": [vars(i) for i in d.mass_items], "payload_kg": d.payload_kg,
        "x_cg_mm": d.x_cg_mm, "mac_mm": d.mac_mm, "x_mac_le_mm": d.x_mac_le_mm, "wing_x_le_mm": d.wing_x_le_mm,
        "x_np_mm": d.x_np_mm, "x_np_vlm_mm": d.x_np_vlm_mm, "x_np_aerobuildup_mm": d.x_np_aerobuildup_mm,
        "x_np_aerobuildup_nofus_mm": d.x_np_aerobuildup_nofus_mm, "static_margin": d.static_margin,
        "trim": {"alpha_deg": d.trim_alpha_deg, "elevator_deg": d.trim_elevator_deg,
                 "elevator_vlm_equiv_deg": d.trim_elevator_vlm_deg, "cl": d.cl_cruise},
        "sm_vs_wing_x": d.sm_vs_lh, "step": step, "solids": len(aircraft.solids()),
    }
    with open(os.path.join(args.out, "aircraft_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=float)


if __name__ == "__main__":
    main()
