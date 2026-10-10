"""Detail design of the whole aircraft (v0.16).

v0.14 wing campaign -> v0.16 flight-ready layout (power-on static margin, dihedral for the spiral mode)
-> CS-23 tail loads -> built-up tail boxes (CalculiX-checked) -> stringer-stiffened wing covers, riveted
spar flanges, bonded stringers, detailed ribs (closed form + close-up CalculiX models) -> CAD-measured
masses fed back -> re-balanced aircraft, dynamic modes against MIL-F-8785C Level 1 -> labelled STEP.

Usage:
    python examples/aircraft/detailed_aircraft.py [--out artifacts/aircraft_detailed] [--no-fe]
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from agents.structures.agent import CALCULIX_AVAILABLE
from cad.exporters import export_parts_step, export_step_assembly
from engineering.analysis.aircraft_layout import build_aircraft_assembly
from engineering.analysis.detail_design import detail_tail, detail_wing, run_closeup_fe
from engineering.analysis.flight_dynamics import design_flight_ready
from engineering.analysis.tail_structure import (
    attach_details,
    design_tail_structure,
    verify_tail_fe,
)
from engineering.analysis.wing_campaign import (
    CampaignRequirement,
    build_structure_cad,
    run_campaign,
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join("artifacts", "aircraft_detailed"))
    ap.add_argument("--no-fe", action="store_true", help="skip the CalculiX close-up and tail-box checks")
    args = ap.parse_args()
    run_fe = CALCULIX_AVAILABLE and not args.no_fe
    line = "=" * 78
    print(line, "\n AeroForge v0.16 -- detail design: tails, joints, close-up FE, dynamics\n", line, sep="")

    campaign = run_campaign(CampaignRequirement(), run_fe=False)
    # 1. v0.16 (1/3) layout with estimated tails: needed for the tail loads (CG, yaw inertia, downwash)
    plain = build_structure_cad(campaign, n_profile=21)
    d0, mp0, fd0, _ = design_flight_ready(campaign, plain)
    # 2. tails: loads -> boxes -> detail
    tails = design_tail_structure(d0, fd0.deps_dalpha, mp0.izz, build_cad=False)
    print("\n[1] Tail limit loads (CS-23 style)")
    for c in tails.cases:
        print(f"  {c.name:34s} V {c.speed_mps:5.1f} m/s  {c.load_n:6.2f} N   {c.note}")
    if run_fe:
        for ts in (tails.htail, tails.vtail):
            fe = verify_tail_fe(ts)
            print(f"  {ts.surface}: tip deflection FE {fe.tip_deflection_mm:.2f} mm vs beam "
                  f"{ts.sizing.ultimate.tip_deflection_mm:.2f} mm, first buckling factor {fe.buckling_factors[0]:.2f}")
    attach_details(tails, detail_tail(tails.htail), detail_tail(tails.vtail))
    # 3. wing details
    w = detail_wing(campaign)
    print(f"\n[2] Wing covers: unstiffened {w.mass_unstiffened_covers_kg:.3f} kg -> stiffened "
          f"{w.mass_stiffened_covers_kg:.3f} kg per semispan")
    for b, p in enumerate(w.stiffened.panels):
        st = f"{p.n_stringers} x {p.stringer.leg_mm:.0f}x{p.stringer.t_mm:.1f} angle" if p.stringer else "unstiffened"
        print(f"  bay {b + 1}: skin {p.skin_t_mm:.2f} mm, {st}, min MS {min(p.margins.values()):+.2f}")
    rv = w.rivets
    print(f"  spar-flange rivets: D {rv.diameter_mm} mm @ {rv.pitch_mm} mm ({rv.governing}), "
          f"MS {', '.join(f'{k} {v:+.2f}' for k, v in rv.margins.items())}")
    if w.bond:
        print(f"  stringer bond: {w.bond.overlap_mm:.0f} mm land, peak {w.bond.tau_max_mpa:.1f} MPa, MS {w.bond.margin:+.2f}")
    if run_fe:
        print("\n[3] Close-up CalculiX checks")
        for k, v in run_closeup_fe(w).items():
            if hasattr(v, "kt_fe"):
                ref = f" vs {v.kt_ref:.3f}" if v.kt_ref else ""
                print(f"  {k:24s} Kt {v.kt_fe:.3f}{ref}")
            elif hasattr(v, "tau_max_fe"):
                print(f"  {k:24s} peak shear {v.tau_max_fe:.2f} vs Volkersen {v.tau_max_ref:.2f} MPa, "
                      f"peel {v.peel_max_fe:.2f} MPa")
            else:
                ref = f" vs {v.reference:.3f}" if v.reference else ""
                print(f"  {k:24s} buckling factor {v.factors[0]:.3f}{ref}")
    # 4. CAD masses back into the balance
    d, _, fd, _ = design_flight_ready(campaign, w.structure, iterations=3, tails=tails)
    print(f"\n[4] Re-balanced: wing x_LE {d.wing_x_le_mm:.1f} mm, CG {d.x_cg_mm:.1f} mm, power-on SM "
          f"{fd.static_margin_power_on:.1%}, dihedral {d.dihedral_deg:.1f} deg, payload {d.payload_kg:.2f} kg")
    print("\n[5] Dynamic modes (MIL-F-8785C Class I, Level 1)")
    for k, (val, lim, ok) in fd.criteria.items():
        print(f"  {k:32s} {val:9.3f}  {lim:12s} {'PASS' if ok else 'FAIL'}")
    aircraft = build_aircraft_assembly(d, w.structure)
    os.makedirs(args.out, exist_ok=True)
    step = os.path.join(args.out, "aircraft_detailed.step")
    export_step_assembly(aircraft, step)
    parts = export_parts_step(aircraft, os.path.join(args.out, "parts"))
    print(f"\n[6] CAD: {step} ({len(aircraft.solids())} solids), {len(parts)} part files")
    with open(os.path.join(args.out, "report.json"), "w", encoding="utf-8") as f:
        json.dump({"criteria": {k: [float(v[0]), v[1], bool(v[2])] for k, v in fd.criteria.items()},
                   "static_margin_power_on": fd.static_margin_power_on, "dihedral_deg": d.dihedral_deg,
                   "wing_x_le_mm": d.wing_x_le_mm, "payload_kg": d.payload_kg,
                   "masses": {i.name: i.mass_kg for i in d.mass_items}}, f, indent=1)


if __name__ == "__main__":
    main()
