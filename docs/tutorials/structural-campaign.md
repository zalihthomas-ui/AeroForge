# Virtual wing structural test campaign (v0.14)

```bash
python examples/wing/structural_campaign.py            # ~40 s with CalculiX installed
python examples/wing/structural_campaign.py --no-fe    # closed form only (no CalculiX needed)
```

The campaign replaces the two weakest links of the v0.8–v0.13 flagship
(`examples/wing/flagship_demo.py`, which still runs unchanged):

1. **Lift was 2D.** The old loop multiplied a 2D *section* lift coefficient
   by the planform area. A finite wing sheds trailing vortices whose
   downwash lowers the effective angle of attack, so it makes less lift.
2. **"Safety factor" was a solid-section number at 1 g cruise.** A solid
   aluminium wing under cruise lift gives SF ≈ 350–1600 — a number with no
   design meaning (real wings are thin-walled boxes, sized to ultimate
   manoeuvre/gust loads, usually by buckling).

## Pipeline

| Step | Module | What it does |
|---|---|---|
| Aero sizing | `engineering/analysis/wing_lifting_line.py` | Prandtl lifting line (Glauert Fourier collocation, odd harmonics) for a straight tapered wing; section `a0`, `alpha_L0` from NeuralFoil by finite difference at the mean-chord Re. Chord scale found by `brentq` so that 3D lift = weight. |
| Loads | `engineering/analysis/wing_loads.py` | V-n diagram (stall line, +3.8/−1.5 manoeuvre), CS-23.341 Pratt gust (Ude 15.24 m/s at Vc, 7.62 m/s at Vd, `Kg = 0.88 mu/(5.3+mu)`), ultimate = 1.5 × limit; spanwise shear and bending from the lifting-line distribution, **inertia relief ignored (conservative)**. |
| Box sizing | `agents/structures/wing_box.py` | Rectangular box 20 %–60 % chord, height = thinner airfoil thickness at the two spars; covers (t_cap) and webs (t_web) stepped per bay; bending stress, web shear, SS-plate buckling (k = 4 compression, k_s = 5.35 shear), tip deflection by integrating M/EI; per-bay minimum gauge found with `brentq` and rounded up to a 0.05 mm sheet step. |
| FE verification | `agents/structures/wing_box_fe.py`, `StructuresAgent.evaluate_wing_box` | Own structured S8R shell mesh (box "tube" + ribs, no gmsh), root clamped, lift as nodal forces on the upper spar-cap lines. Three CalculiX runs: static at **ultimate** load, `*BUCKLE`, `*FREQUENCY`, all `SOLVER=SPOOLES`. |
| CAD | `wing_campaign.export_wing_cad`, `wing_campaign.build_structure_cad` → `agents/geometry/wing_structure.py` | STEP/STL of the outer mould line, plus the **complete internal structure**: 14 ribs (with lightening holes), front and rear spar webs and upper/lower box covers stepped per sized bay, leading- and trailing-edge skin — exported as one STEP assembly and one STL per component group. |

## Validation (all in the test suite)

| Check | Result |
|---|---|
| Elliptic wing vs `CL = a0 α / (1 + a0/(π AR))`, `e = 1` | < 0.5 % (machine precision in practice) |
| Rectangular AR 6 induced-drag factor δ vs Glauert (≈ 0.046–0.05) | 0.048 |
| Convergence in the number of Fourier terms | < 0.1 % change 32 → 64 terms |
| Cross-check vs aerosandbox vortex-lattice | lifting line 4–6 % higher CL (known lifting-line bias at moderate AR; not a test) |
| Elliptic load: root moment = L·4s/(3π) | < 0.2 % |
| CS-23 gust formula | hand calculation, exact |
| FE reactions vs applied lift | equal to ~1e-8 % |
| FE tip deflection vs Euler-Bernoulli integration | +3 % (FE includes shear flexibility) |
| FE cover stress vs `M c / I` (mid-bay, inboard bays) | < 3 % |
| FE first buckling factor vs SS-plate estimate | 1.69× — inside the physical bound [1, 6.97/4] between simply-supported and clamped plate edges; mesh-converged to < 1 % |
| FE first bending frequency vs Hermite beam model (with rib masses) | −3 % |

**CalculiX gotcha found here:** with OpenMP threads, this MSYS2 ccx build's
`*BUCKLE`/`*FREQUENCY` eigensolver is non-deterministic and intermittently
returns spurious eigenvalues (the same deck gave 0.70, 1.01 and 1.72). The
wing-box runner therefore forces `OMP_NUM_THREADS=1`, which is exactly
repeatable (and tested).

## Results (12 kg MTOW, 25 m/s, 1.8 m span, 4° cruise α)

| | Value |
|---|---|
| Selected section | NACA 4412 (`a0` 6.27/rad, `alpha_L0` −4.3°) |
| Planform | root 305 mm / tip 178 mm, S 0.434 m², AR 7.46 |
| 3D aero | CL 0.708, CDi 0.0218, e 0.979, CL_α 4.87/rad |
| Loads | Vs 18.3 m/s; gust n = 4.24 governs (manoeuvre 3.8); ultimate n = 6.36; root bending 98 N·m limit |
| Box (Al 6061-T6) | t_cap 1.40→0.35 mm in 6 bays, t_web 0.30 mm (min gauge); **every bay buckling-governed** |
| Box mass (covers + webs, both halves) | **0.95 kg** (Al 7075-T6 0.98 kg — stiffness-, not strength-critical; quasi-iso CFRP 0.63 kg, see caveats) |
| Margins (closed form, ultimate) | cover buckling +0.02, web shear buckling +0.77, cover strength +8.5 |
| FE at ultimate | tip deflection 9.8 mm, peak von Mises 39 MPa away from the clamp (52 MPa at it), first buckling factor 1.73, first modes 67.6 / 186.8 / 220.5 Hz |

## Complete wing structure (CAD)

| Component (both halves) | Solids | Material | Mass |
|---|---|---|---|
| Ribs (1 mm, 2 lightening holes each) | 14 | Al 6061-T6 | 0.172 kg |
| Spar webs (front 20 %, rear 60 % chord) | 24 | Al 6061-T6 | 0.067 kg |
| Box covers (stepped per bay) | 24 | Al 6061-T6 | 0.887 kg |
| Leading-edge skin (0.5 mm) | 2 | glass/epoxy | 0.153 kg |
| Trailing-edge skin (0.5 mm, to 95 % chord) | 4 | glass/epoxy | 0.243 kg |
| **Total wing structure** | **68** | | **1.52 kg** |

The CAD keeps the true NACA 4412 surface (the analysis idealises the box as a
rectangle at the thinner spar depth — conservative). Parts touch/overlap at
joints by up to one skin thickness; no fasteners, flanges or bonding lands;
the trailing edge is left open behind 95 % chord. This 1.52 kg, not the
0.95 kg box alone, is the like-for-like comparison with the old 1.16 kg
whole-wing skin estimate (which had no internal structure at all).

## Modelling implications: old 2D flagship vs v0.14 campaign

| Quantity | v0.8–v0.13 flagship | v0.14 campaign | Why it changed |
|---|---|---|---|
| Lift model | 2D section CL × area | Prandtl lifting line (finite wing) | downwash |
| Lift of the old sized wing (NACA 0012, 492 mm root) | 117.7 N "= weight, PASS" | **82.5 N (−30 %), would FAIL** | same wing, 3D physics |
| Chord needed with NACA 0012 at 4° | 492 mm root (AR 4.6) | 904 mm root (AR 2.5) — outside lifting-line validity, rejected | |
| Chord / AR actually adopted | 492 mm / 4.6 | 305 mm / 7.5 (NACA 4412) | camber shifts alpha_L0 by −4.3° |
| Structural load | 1 g cruise lift | ultimate n = 6.36 (gust, × 1.5) | design-load cases |
| Structure | solid aluminium section | thin-walled box, 6 sized bays | real wing construction |
| "Safety" metric | SF 350 → 1643 (meaningless) | margins of safety ≥ 0 incl. buckling; FE buckling factor 1.73 at ultimate | |
| Mass | 1.16 kg skin-only estimate (0.5 mm glass shell, informational) | 0.95 kg sized box (Al 6061-T6); 1.52 kg complete structure (box + ribs + LE/TE skin, from CAD) | the old number had no internal structure |
| Sweep / dihedral | 12° / 4° | 0° / 0° | lifting line and the straight-beam box are for unswept wings |

## Caveats

* Lifting line: unswept, attached flow, incompressible, AR ≳ 4; CL is
  4–6 % above a vortex-lattice result. Wing CL_max = 0.9 × section cl_max
  (rule of thumb).
* Loads: CS-23 values applied to a small UAV are a design choice, not a
  certification basis. This slow wing has Va (35.7 m/s) > Vd (35 m/s): it
  stalls before it can reach +3.8 g anywhere in the envelope, while the
  CS-23 gust formula is not stall-limited — the gust-governed design is
  therefore conservative. Inertia relief and torsion are ignored.
* Box: rectangular idealisation at the thinner spar depth (conservative);
  no skin outside the box, no stringers, no fasteners; rib mass excluded
  from the box mass. "No buckling below ultimate" with SS-plate edges is
  conservative — the FE shows a 73 % reserve, which a calibrated buckling
  coefficient (or allowing elastic skin buckling above limit load, as metal
  aircraft do) would turn into lighter covers. Not done here.
* CFRP option: smeared quasi-isotropic laminate treated as an isotropic
  plate, strength knocked down to 300 MPa; no ply-level criteria.
* Frequencies are of the bare box (no skin, systems, fuel or payload mass).
