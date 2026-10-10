# Detail design: tails, joints, close-up FE, dynamics (v0.16)

```bash
python examples/aircraft/detailed_aircraft.py          # ~30 min: VLM/AeroBuildup loops + CalculiX
python examples/aircraft/detailed_aircraft.py --no-fe  # skip the CalculiX checks
```

v0.15 ended with a balanced, trimmed aircraft whose tails were solid foam shells and whose wing box was
a set of thicknesses with no joints. v0.16 takes it to preliminary-design detail:

1. **Flight-ready layout** (`engineering/analysis/flight_dynamics.py`, `propulsion.py`): CAD inertia
   tensor, actuator-disk propeller with slipstream over the tail and thrust-line moment, VLM downwash,
   power-on static margin, small-perturbation longitudinal/lateral models, dihedral sized for the
   spiral mode, MIL-F-8785C Level 1 checks, control authority.
2. **Built-up tails** (`engineering/analysis/tail_structure.py`): CS-23-style tail loads, boxes sized
   like the wing, CalculiX shell check, CAD with the elevator / rudder hinged behind the rear spar.
3. **Joint details** (`agents/structures/joints.py`, `stiffened_panel.py`, `detail_fe.py`,
   `engineering/analysis/detail_design.py`): stringer-stiffened covers, C-channel spars with riveted
   flanges, bonded stringers, split ribs with mouseholes, spar-flange notches, flanged lightening holes
   and bonded rib flanges; each hand method checked by a close-up CalculiX model.
4. **Mass feedback**: the detailed wing and tail CAD masses replace the estimates; the aircraft is
   re-balanced and its dynamics re-checked.

## 1. Tail loads and boxes

| Case (limit, one stabiliser half / fin) | Method |
|---|---|
| HT manoeuvre | C_Lh,max = 1.0 (NACA 0009 + full elevator) × q_A × S_h at V_A |
| HT gust | CS-23.425: ΔL = ½ρ₀ K_g U_de V a_h S_h (1 − dε/dα), U_de 15.24 m/s at V_C and 7.62 m/s at V_D |
| Fin manoeuvre | C_Lv,max = 1.0 × q_A × S_v |
| Fin gust | CS-23.443: L = ½ρ₀ K_gt U_de V a_v S_v, μ_gt = 2W/(ρ c̄_v g a_v S_v)(K/l_v)², K_gt = 0.88μ/(5.3 + μ) |

Lift slopes from Helmbold/DATCOM (fin aspect ratio × 1.55 for the fuselage/stabiliser end plate);
spanwise distribution by Schrenk; ultimate = 1.5 × limit. The fin's bending moment is divided by
cos(box sweep) to give the moment about the swept box axis. The boxes (front spar 15 % c, rear spar
5 % c ahead of the hinge, Al 6061-T6, 0.3 mm minimum gauge) are sized with `size_box` and checked
with the same CalculiX S8R model as the wing. Design cases: HT manoeuvre 39.6 N, fin manoeuvre 33.0 N.

The tail boxes are only 11-15 mm deep, too shallow for stringers that the rib mouseholes can clear
(stringer leg + 1 mm ≤ 35 % of the box depth), so their covers stay unstiffened (0.7/0.55/0.4/0.3 mm
stabiliser, 0.55/0.4/0.3 mm fin). Built-up masses (structure + elevators/rudder): stabiliser
0.247 kg, fin 0.094 kg, against the v0.15 foam estimates of 0.128 and 0.056 kg.

## 2. Stiffened covers

The v0.14 covers were sized by plate buckling over the full spar-to-spar width in every bay. Each bay
now gets 0-4 bonded equal-angle stringers (6-12 mm legs, 0.4-1.0 mm), sized for the lightest cover
section with all margins ≥ 0 at ultimate:

* skin between stringers, k = 4 on the stringer pitch;
* stringer + skin strip as a pin-ended column between ribs, Euler with the Johnson parabola; Gerard
  crippling of the formed angle;
* cover strength and yield;
* the bonding land (attached leg) must pass the whole stringer load into the skin at a run-out
  (Volkersen plateau);
* manufacturability: stringer count only decreases outboard (run-outs at ribs), and the stringer
  must fit the rib mousehole (leg + 1 mm ≤ 35 % of the bay's smallest box depth).

Result: 3 stringers in bays 1-4 (8×0.4 mm at the root, 6 mm legs outboard), unstiffened bays 5-6;
cover mass **0.443 → 0.239 kg per semispan**. The detailed wing (with flanges, stringers, ribs, rivets)
weighs 1.14 kg against 1.52 kg for the v0.14 structure.

## 3. Joints

| Joint | Method | Root result |
|---|---|---|
| Spar flange to cover (MS20470AD rivets) | q = VQ/I at the web/cover line; rivet single shear (Fsu 207 MPa), sheet bearing (Fbru = 2.09 Ftu at e/D = 2), inter-rivet buckling σ_ir = 0.9·c·E(t/p)², c = 4; pitch 4D-8D, edge 2D; D ≥ 2 × thicker sheet | Ø1.6 mm @ 12.5 mm (8D governs), all MS ≥ +2.5 |
| Stringer bonding land | Volkersen shear lag solved exactly; overlap past the elastic plateau (≥ 3/ω) | 10 mm, peak 12.8 MPa vs 20 MPa allowable |
| Rib | 0.5 mm web, split at the spar webs; shear from the bay air load on the net depth; flange peel from upper-surface suction | MS ≫ 0 (handling gauge governs) |

## 4. Close-up CalculiX models

| Model (`agents/structures/detail_fe.py`) | FE | Hand method | Difference |
|---|---|---|---|
| Rivet hole in a cover strip, tension (CPS8 quarter) | Kt 2.69 | Heywood 2 + (1 − d/W)³ = 2.645 | +1.7 % |
| Opposite semicircular notches (validation) | Kt 2.767 | Peterson chart 2.3: 2.728 | +1.4 % |
| Rib mousehole U-slot, both caps | Kt 1.595 → 1.594 at 4× mesh | (no handbook value: converged) | — |
| Hole in pure shear (Kirsch) | σ_max/τ 4.055 | 4 | +1.4 % |
| Bonded lap, adherends supported (CPE8) | peak τ 11.6 MPa | Volkersen 12.8 MPa | −9 % (no adherend shear strain in Volkersen) |
| Same lap, free single lap | peak τ 17.9 MPa, peel 26 MPa | — | adherend bending: an anti-peel rivet goes at every stringer end |
| SS plate buckling, unstiffened v0.14 cover (S8R) | 0.538 | k = 4.17 exact: 0.543 | −0.8 % |
| Stiffened root bay (S8R, stringers as land + blade) | 1.226 | skin 1.062 (conservative), column 1.253 | between the two |
| Rib web in shear, no holes | 13.57 | k_s plate theory 13.58 | −0.1 % |
| Rib web, plain lightening holes / flanged holes | 5.80 / 14.70 | — | the holes cost 57 %; a 2.5 mm flange more than restores it |

**A solver finding.** This CalculiX build's `*BUCKLE` only lists buckling factors above 1: a plate whose
true factor was 0.54 was reported as 1.05 (its third mode). Every buckling run (wing box FE included)
now solves at 0.1 × the load and scales the factors back (`BUCKLE_REFERENCE_SCALE`), with a regression
test.

## 5. Mass feedback and dynamics

The detailed wing (1.14 kg, was 1.52) and the built-up tails (0.247 + 0.094 kg, were 0.128 + 0.056 kg
foam estimates) are measured from their CAD solids and fed back through `design_flight_ready(...,
tails=...)`: tail masses and centroids from `tail_mass_items`, the inertia tensor from every solid's
volume × density (`mass_properties`), wing placement re-solved for a 10 % power-on static margin and
the dihedral re-sized for the spiral criterion. The tail loads recomputed on the final design change by
< 1 % (fin gust 24.42 → 24.57 N): the loop is closed.

| | v0.16 (1/3), estimated tails | detailed |
|---|---|---|
| wing x_LE | 276.4 mm | 339.7 mm |
| CG | 382.8 mm | 445.5 mm |
| power-on static margin | 10.0 % MAC | 10.1 % MAC |
| dihedral | 3.5° | 3.5° |
| payload capacity | 5.32 kg | 5.51 kg |
| Ixx / Iyy / Izz | 0.308 / 0.341 / 0.616 kg·m² | 0.284 / 0.458 / 0.710 kg·m² |

The heavier built-up tail (+0.16 kg, 0.7 m behind the CG) and the lighter wing pull the empty-weight
CG aft; the CG-centred payload bay follows it, and the wing moves 63 mm aft to restore the margin.

| Mode (MIL-F-8785C Class I, Cat. B, Level 1) | detailed aircraft | requirement |
|---|---|---|
| short period | ω_n 8.23 rad/s, ζ 0.840 | 0.3 ≤ ζ ≤ 2.0 |
| phugoid | ω_n 0.466 rad/s, ζ 0.052 | ζ ≥ 0.04 |
| Dutch roll | ω_n 7.79 rad/s, ζ 0.240, ζω 1.87 | ζ ≥ 0.08, ζω ≥ 0.15, ω ≥ 0.4 |
| roll | τ 0.052 s | ≤ 1.4 s |
| spiral | doubles in 23.0 s | ≥ 20 s |

Cruise trim (power on, 25 m/s): α 2.79°, elevator −2.66°, thrust 6.81 N, shaft power 208 W,
propeller efficiency 0.82, slipstream 26.9 m/s over 59 % of the stabiliser span, η_h 0.983.

## Caveats

* Preliminary-design fidelity: linear buckling, no post-buckling credit, no fatigue / damage
  tolerance, no fastener flexibility (load sharing between rows) and no environmental knock-downs
  beyond the stated allowables. MMPDS-style values are order-of-magnitude; verify against your source.
* The tail box FE mesh is straight (sweep enters through the 1/cos Λ bending factor).
* Volkersen ignores adherend bending; the free-lap FE shows why stringer run-outs need an anti-peel
  fastener or a tapered end.
* Linear small-perturbation dynamics at one flight condition; derivatives from VLM/AeroBuildup.
