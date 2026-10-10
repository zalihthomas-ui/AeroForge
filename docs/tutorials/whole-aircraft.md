# Whole aircraft: fuselage, tail, mass & balance, stability (v0.15)

```bash
python examples/aircraft/design_aircraft.py      # ~4 min (VLM/AeroBuildup inside a root-finder)
```

The aircraft is grown around the v0.14 campaign wing (`docs/tutorials/structural-campaign.md`):
NACA 4412, root/tip 305/178 mm, span 1.8 m, MAC 246.9 mm, sized wing structure 1.52 kg.

## Pipeline

| Step | Module | Method |
|---|---|---|
| Empennage | `engineering/analysis/aircraft_layout.py` `size_tail`, `agents/geometry/fuselage_tail.py` | Tail-volume coefficients V_H = 0.70, V_V = 0.04 (Raymer, *Aircraft Design: A Conceptual Approach*, Table 6.4, single-engine GA); tail arm 3 × MAC; htail AR 4.5, taper 0.7, NACA 0009, elevator 30 % chord; fin AR 1.6, taper 0.6, 25° LE sweep, NACA 0010, rudder 35 % chord |
| Fuselage | `fuselage_stations`, `build_fuselage` | Elliptical stations lofted into a 0.8 mm glass skin; cabin cross-section = largest component box + 10 mm clearance + skin; ply ring formers at the cabin ends and middle; boom to the tail |
| Mass & balance | `default_components`, `_structure_masses`, `mass_balance` | Representative systems of a 12 kg electric UAV (motor, prop, ESC, 2.8 kg battery, avionics, servos, wiring) + structure masses from the CAD volumes; payload = MTOW − everything else |
| Neutral point | `neutral_points` | aerosandbox vortex-lattice on wing + tails, plus the fuselage increment from AeroBuildup (NP with − without fuselage) |
| Balancing | `design_aircraft` | brentq on the wing leading-edge station for static margin = 10 % MAC (band 5–15 %) |
| Trim | `trim` | fsolve on (α, δe) with AeroBuildup for CL = W/(qS), Cm_cg = 0; VLM cross-check with an all-moving tail converted by thin-airfoil flap effectiveness τ(cf/c) |
| CAD | `build_aircraft_assembly` + `cad.exporters.export_step_assembly` / `export_parts_step` | Labelled, coloured STEP tree `Aircraft > Wing / Fuselage / HorizontalTail / VerticalTail / Systems`, one STEP per part |

## Why the wing position, not the tail arm, sets the static margin

With the tail sized by a fixed volume coefficient, S_h·l_h is constant, so lengthening the tail arm
shrinks the tail and the neutral point barely moves (measured: NP 507 → 513 mm for l_h 0.5 → 1.6 m in
an early layout). The CG, meanwhile, is dominated by the fuselage-mounted battery and payload. The wing
carries the neutral point with it, so its longitudinal station is the balancing variable — the classic
"wing placement" step of conceptual design. SM rises monotonically from −14 % (wing LE at 200 mm) to
+118 % (600 mm); 10 % is reached at x_LE = 272.6 mm.

## Why the design neutral point is VLM + fuselage increment

AeroBuildup alone put the neutral point *aft* of the lifting-surfaces-only VLM value (455.7 vs
418.4 mm) even though it includes the destabilising fuselage — its empirical downwash at the tail is
weaker than the potential-flow downwash VLM computes. The design therefore uses VLM for the lifting
surfaces and AeroBuildup only for the fuselage increment (−5.9 mm), which is the more forward,
conservative neutral point.

## Results

| | |
|---|---|
| Tail | arm 741 mm; S_h 0.1014 m² (span 675 mm, chords 177/124 mm); S_v 0.0422 m² (height 260 mm) |
| Mass | 12.00 kg total, payload capacity 5.33 kg; structure: wing 1.52, fuselage skin 0.50, formers 0.04, htail 0.13, fin 0.06 kg |
| CG | x = 387.8 mm from the nose = 46.6 % MAC |
| Neutral point | VLM 418.4 mm; fuselage −5.9 mm → 412.4 mm |
| Static margin | **10.0 % MAC** (wing LE at 272.6 mm) |
| Cruise trim | CL 0.708, α 2.71°, elevator −2.10° (AeroBuildup); VLM all-moving-tail equivalent −0.23° |
| CAD | 84 labelled solids in 5 groups, `artifacts/aircraft/aircraft_assembly.step` + `parts/*.step` |

The two trim-elevator values bracket the answer: AeroBuildup includes the viscous section pitching
moment of the cambered NACA 4412 wing (nose-down, needs more up-elevator), VLM does not. Both are a
few degrees — the tail is not undersized.

## Caveats

* Conceptual-design fidelity: no propeller slipstream, thrust line, downwash lag, landing gear or
  control-surface gap effects; static (not dynamic) stability only.
* Component masses are representative values for this class of UAV, not a specific product; the
  payload is whatever mass is left to reach MTOW.
* Tail surfaces are modelled as foam core + 0.3 mm glass skin (mass from area and section volume), the
  fuselage as a 0.8 mm glass shell with three ply formers — no internal tail spars, hinges or
  fasteners.
* The fin arm is taken equal to the stabiliser arm; lateral-directional stability is not analysed.
