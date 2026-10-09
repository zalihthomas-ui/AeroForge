"""Virtual wing structural test campaign (v0.14 flagship).

Requirement -> lifting-line aero sizing -> V-n / gust loads -> wing-box sizing
-> CalculiX shell FE (static to ultimate, buckling, modes) -> CAD export.

Usage:
    python examples/wing/structural_campaign.py [--no-fe] [--out artifacts/wing_campaign]

Writes a JSON report (and, with --save-fields, an .npz with the FE fields
used for visualisation) next to the exported CAD.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import numpy as np

from engineering.analysis.wing_campaign import (
    CampaignRequirement,
    fe_vs_closed_form,
    margins_from_fe,
    run_campaign,
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-fe", action="store_true", help="skip the CalculiX verification")
    ap.add_argument("--out", default=os.path.join("artifacts", "wing_campaign"))
    ap.add_argument("--save-fields", action="store_true", help="also write FE fields (.npz)")
    args = ap.parse_args()

    req = CampaignRequirement()
    res = run_campaign(req, run_fe=not args.no_fe, export_dir=args.out,
                       work_dir=os.path.join(args.out, "ccx") if not args.no_fe else None)
    c, a, e, s = res.comparison, res.aero, res.envelope, res.sizing
    w = req.mtow_kg * 9.81

    line = "=" * 78
    print(line, "\n AeroForge v0.14 -- virtual wing structural test campaign\n", line, sep="")
    print(f"\n[1] Requirement: {req.mtow_kg:.1f} kg MTOW ({w:.2f} N), cruise {req.cruise_velocity_mps:.0f} m/s, "
          f"span {req.span_mm:.0f} mm, alpha {req.alpha_deg:.0f} deg")
    print("\n[2] Aerodynamic sizing -- 2D section method (v0.8-v0.13) vs lifting line")
    print(f"  old 2D answer (NACA {c.old_naca}): root chord {c.old_root_chord_mm:.0f} mm, AR {c.old_aspect_ratio:.2f};"
          f" claimed lift {c.old_lift_2d_n:.1f} N, lifting-line lift of that wing {c.old_lift_3d_n:.1f} N "
          f"({100 * (c.old_lift_3d_n / c.old_lift_2d_n - 1):+.0f} %)")
    for naca, cand in c.candidates.items():
        flag = "" if cand.valid_lifting_line else "  <- AR < 4: outside lifting-line validity"
        print(f"  3D, NACA {naca}: root chord {cand.root_chord_mm:6.1f} mm, AR {cand.aspect_ratio:5.2f}, "
              f"CL {cand.lifting_line.cl_wing:.3f}, e {cand.lifting_line.span_efficiency:.3f}{flag}")
    ll = a.lifting_line
    print(f"  -> selected NACA {a.naca}: root {a.root_chord_mm:.1f} mm / tip {a.tip_chord_mm:.1f} mm, "
          f"S {ll.area_m2:.3f} m^2, AR {ll.aspect_ratio:.2f}, CL {ll.cl_wing:.3f}, CDi {ll.cdi:.4f}, "
          f"e {ll.span_efficiency:.3f}, CL_alpha {ll.cl_alpha_per_rad:.2f}/rad")

    print("\n[3] Design loads (CS-23-style)")
    print(f"  Vs {e.v_stall_mps:.1f} m/s (CLmax {e.cl_max:.2f}), Va {e.v_maneuver_mps:.1f}, Vc {e.v_cruise_mps:.1f}, "
          f"Vd {e.v_dive_mps:.1f} m/s")
    print(f"  manoeuvre n = +{e.n_pos_maneuver:.2f} / {e.n_neg_maneuver:.2f}; gust (Ude 15.24 m/s @Vc, "
          f"mu_g {e.gust_mass_ratio:.1f}, Kg {e.gust_alleviation_kg:.3f}) n = {e.n_gust_pos:.2f} / {e.n_gust_neg:.2f}")
    print(f"  governing: {e.governing_case}; limit n = {e.n_limit:.2f}, ultimate n = {e.n_ultimate:.2f}")
    if e.v_maneuver_mps > e.v_dive_mps:
        print("  note: Va > Vd -- this slow wing stalls before reaching n = +3.8 anywhere in the envelope;"
              " the CS-23 gust formula (not stall-limited) still governs: conservative.")
    lim = res.loads_limit
    print(f"  root shear / bending at limit: {lim.root_shear_n:.1f} N / {lim.root_bending_nm:.1f} N m "
          "(inertia relief ignored: conservative)")

    print(f"\n[4] Wing-box sizing ({s.material.name}, {req.n_bays} bays, min gauge {req.min_gauge_mm} mm)")
    print("  bay  t_cap [mm]  t_web [mm]  governed by")
    for i, (tc, tw, g) in enumerate(zip(s.thickness.t_cap_mm, s.thickness.t_web_mm, s.governing_per_bay)):
        print(f"  {i:3d}  {tc:9.2f}  {tw:10.2f}   {g}")
    print(f"  box mass (covers + webs, both halves): {s.mass_kg:.3f} kg")
    for k, v in s.margins.values.items():
        print(f"  MS {k:40s} {v:+.3f}")
    print("  alternatives: " + ", ".join(f"{alt.material.name} {alt.mass_kg:.3f} kg" for alt in res.alternatives.values()))
    print(f"  tip deflection (closed form) at limit / ultimate: {s.limit.tip_deflection_mm:.1f} / "
          f"{s.ultimate.tip_deflection_mm:.1f} mm; 1st bending (beam) {res.beam_frequencies_hz[0]:.1f} Hz")

    if res.fe is not None:
        fe = res.fe
        print(f"\n[5] CalculiX shell FE verification at ULTIMATE load ({fe.n_elements} S8R elements)")
        print(f"  equilibrium: applied {fe.applied_lift_n:.2f} N, reaction {-fe.reaction_z_n:.2f} N "
              f"(error {fe.equilibrium_error_pct:.1e} %)")
        print(f"  tip deflection {fe.tip_deflection_mm:.2f} mm; peak von Mises {fe.max_von_mises_mpa:.1f} MPa "
              f"({fe.max_von_mises_away_from_root_mpa:.1f} MPa away from the clamp)")
        print(f"  buckling load factors: {', '.join(f'{x:.3f}' for x in fe.buckling_factors[:3])}")
        print(f"  natural frequencies [Hz]: {', '.join(f'{x:.1f}' for x in fe.frequencies_hz)}")
        for k, v in fe_vs_closed_form(res).items():
            print(f"  FE vs closed form: {k} = {v:+.2f}")
        for k, v in margins_from_fe(res).items():
            print(f"  FE MS {k}: {v:+.3f}")
    print(f"\n[6] CAD: {res.cad_paths}")

    report = _report_dict(res)
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "campaign_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    if args.save_fields and res.fe is not None:
        _save_fields(res, os.path.join(args.out, "campaign_fields.npz"))
    print(f"\nreport: {os.path.join(args.out, 'campaign_report.json')}")


def _report_dict(res) -> dict:
    c, a, e, s = res.comparison, res.aero, res.envelope, res.sizing
    out = {
        "requirement": vars(res.requirement) | {"airfoil_candidates": list(res.requirement.airfoil_candidates)},
        "modelling_comparison": {
            "old_2d": {"naca": c.old_naca, "root_chord_mm": c.old_root_chord_mm, "aspect_ratio": c.old_aspect_ratio,
                       "claimed_lift_n": c.old_lift_2d_n, "lifting_line_lift_n": c.old_lift_3d_n},
            "candidates_3d": {k: {"root_chord_mm": v.root_chord_mm, "aspect_ratio": v.aspect_ratio,
                                  "cl": v.lifting_line.cl_wing, "e": v.lifting_line.span_efficiency,
                                  "valid": v.valid_lifting_line} for k, v in c.candidates.items()},
        },
        "aero": {"naca": a.naca, "root_chord_mm": a.root_chord_mm, "tip_chord_mm": a.tip_chord_mm,
                 "area_m2": a.lifting_line.area_m2, "aspect_ratio": a.aspect_ratio, "cl": a.lifting_line.cl_wing,
                 "cdi": a.lifting_line.cdi, "e": a.lifting_line.span_efficiency,
                 "cl_alpha_per_rad": a.lifting_line.cl_alpha_per_rad,
                 "a0_per_rad": a.section.a0_per_rad, "alpha_l0_deg": math.degrees(a.section.alpha_l0_rad)},
        "loads": {"n_limit": e.n_limit, "n_ultimate": e.n_ultimate, "governing": e.governing_case,
                  "n_gust_pos": e.n_gust_pos, "v_stall": e.v_stall_mps, "v_a": e.v_maneuver_mps,
                  "v_d": e.v_dive_mps, "root_bending_limit_nm": res.loads_limit.root_bending_nm,
                  "root_shear_limit_n": res.loads_limit.root_shear_n},
        "box": {"material": s.material.name, "t_cap_mm": s.thickness.t_cap_mm.tolist(),
                "t_web_mm": s.thickness.t_web_mm.tolist(), "governing": s.governing_per_bay,
                "mass_kg": s.mass_kg, "margins": s.margins.values,
                "tip_deflection_limit_mm": s.limit.tip_deflection_mm,
                "tip_deflection_ultimate_mm": s.ultimate.tip_deflection_mm,
                "alternatives_mass_kg": {k: v.mass_kg for k, v in res.alternatives.items()},
                "beam_frequencies_hz": res.beam_frequencies_hz.tolist()},
    }
    if res.fe is not None:
        fe = res.fe
        out["fe"] = {"elements": fe.n_elements, "equilibrium_error_pct": fe.equilibrium_error_pct,
                     "tip_deflection_mm": fe.tip_deflection_mm, "max_von_mises_mpa": fe.max_von_mises_mpa,
                     "max_von_mises_away_from_root_mpa": fe.max_von_mises_away_from_root_mpa,
                     "buckling_factors": fe.buckling_factors, "frequencies_hz": fe.frequencies_hz,
                     "vs_closed_form": {k: float(v) for k, v in fe_vs_closed_form(res).items()},
                     "fe_margins": margins_from_fe(res)}
    out["cad"] = res.cad_paths
    return out


def _save_fields(res, path: str) -> None:
    fe = res.fe
    ids = np.array(sorted(fe.nodes))
    xyz = np.array([fe.nodes[i] for i in ids])
    index = {n: k for k, n in enumerate(ids)}
    quads, quad_set = [], []
    for name, conns in fe.elements.items():
        for c in conns:
            quads.append([index[n] for n in c])
            quad_set.append(name)

    def field(d):
        return np.array([d.get(i, np.zeros(3)) for i in ids])

    np.savez_compressed(
        path,
        xyz=xyz, quads=np.array(quads), quad_set=np.array(quad_set),
        u_static=field(fe.static_displacement),
        vm=np.array([fe.von_mises.get(i, 0.0) for i in ids]),
        buckle=np.array([field(m) for m in fe.buckling_modes]),
        modes=np.array([field(m) for m in fe.vibration_modes]),
        buckling_factors=np.array(fe.buckling_factors), frequencies=np.array(fe.frequencies_hz),
        cover_y=fe.cover_stress_y_mm, cover_s=fe.cover_stress_mpa,
    )


if __name__ == "__main__":
    main()
