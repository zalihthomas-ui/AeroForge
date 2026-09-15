# AEROFORGE Roadmap & Current Milestone

The full 8-phase roadmap (research, CAD MVP, design agent, CFD, FEA,
closed-loop optimization, manufacturing intelligence, dashboard, autonomous
lab) is defined in the root mission doc. That roadmap spans an estimated
20+ weeks of work, including integrating real CFD/FEA solvers — it is not
something to fake or stub out as "done."

Development proceeds **vertically**: one working loop end-to-end before
adding the next discipline.

## Milestone: v0.1 — CAD MVP loop (DONE)

```text
Prompt → Design Agent → Geometry Agent → build123d → STEP / STL
```

Scope:

- `agents/design/` — parses a structured (or lightly natural-language)
  engineering requirement into an `EngineeringSpec` (requirements,
  constraints, objectives, parameters).
- `agents/geometry/` — turns an `EngineeringSpec` into parametric geometry
  via build123d, with validity/self-intersection/solid checks.
- `cad/exporters/` — STEP, STL, 3MF export.
- `backend/` — thin FastAPI wrapper exposing `POST /design` end-to-end.
- `examples/bracket/` — a mounting-bracket requirement running the full loop.

Explicitly **out of scope** for v0.1: CFD, FEA, manufacturing analysis,
optimization loops, frontend dashboard. Those are Phases 3–8 and depend on
real external solvers (OpenFOAM, SU2, CalculiX, ...) that must be evaluated
and integrated deliberately, not simulated.

## Ownership (current sprint)

| Area | Owner |
|---|---|
| Repo scaffolding, backend integration, CI, releases | chief (logo) |
| Geometry Agent + CAD exporters + geometry validity checks | kilo |
| Design Agent + requirement/spec schema | dune |

## Definition of done for v0.1 / "1.0.0" of this milestone

- [x] `examples/bracket/run.py` runs end-to-end and produces a valid `.step`
  + `.stl` from a plain-language bracket requirement.
- [x] `agents/geometry` rejects/flags invalid geometry (self-intersections,
  non-solids) rather than silently exporting bad output.
- [x] Unit tests exist for both agents and pass in CI (44 tests: Design
  Agent, Geometry Agent, exporters, validation, backend integration).
- [x] README and this roadmap accurately describe what exists vs. what is
  future work.

Verified 2026-09-14: `python examples/bracket/run.py` produces a
`bracket.step` that OCCT reads back successfully, plus valid `.stl`/`.3mf`,
from the mission doc's exact Phase 1 requirement string. The FastAPI
`POST /design` endpoint wraps the same pipeline and correctly returns 422
for both unrecognized requirements and geometrically invalid parameters.

## Milestone: v0.2 — second component: wing planform (DONE)

```text
"Create a wing with span 1800mm, root chord 240mm, tip chord 140mm,
 sweep 12 degrees, dihedral 4 degrees."
        → Design Agent → Geometry Agent → build123d → STEP / STL
```

Scope:

- `agents/design/agent.py` — wing parser (`wing_span`, `root_chord`,
  `tip_chord`, `sweep`, `dihedral`), same rule-based approach as bracket.
- `agents/geometry/wing.py` — a **flat-plate planform approximation**
  (constant-thickness slab, tapered/swept/dihedral, mirrored for symmetry).
  Explicitly not an aerodynamically real wing — no airfoil section, camber,
  or twist. That requires an Aerodynamics Agent, which doesn't exist yet.
- `agents/geometry/validation.py` generalized: `validate_solid` /
  `validate_expected_volume` are now component-agnostic, reused by both
  bracket and wing.
- `examples/wing/run.py` — end-to-end demonstration.

Verified 2026-09-14: `python examples/wing/run.py` produces a valid
`wing.step`/`.stl`/`.3mf` from the mission doc's own geometry example
values. 67/67 tests passing (bracket + wing + backend integration).

Explicitly **out of scope**: any aerodynamic realism for the wing (that's
Phase 3, Aerodynamics Agent / CFD), and the Design Agent's fuller
"engineering project manager" responsibilities from mission doc §7
(identify missing parameters, decompose problems, coordinate agents) —
both parsers remain deliberately simple, rule-based, single-component-at-a-
time.

## Ownership (current sprint)

| Area | Owner |
|---|---|
| Repo scaffolding, backend integration, CI, releases | chief (logo) |
| Geometry Agent + CAD exporters + geometry validity checks | kilo |
| Design Agent + requirement/spec schema | dune |

## Milestone: v0.3 — structured missing-parameter detection (DONE)

Mission doc §7 lists "identify missing parameters" as a Design Agent
responsibility distinct from general requirement decomposition. v0.3 makes
that a first-class, programmatic outcome rather than just an error string:

- `IncompleteRequirementError(component, missing, provided)` — raised when
  a component (bracket/wing) is recognized but required parameters are
  absent, as opposed to the general `UnrecognizedRequirementError` for a
  component that isn't recognized at all. Callers (e.g. a future UI) can
  now prompt for exactly the missing fields instead of restating the whole
  requirement.
- `POST /design` returns a structured 422 body
  (`{"error": "incomplete_requirement", "component", "missing", "provided"}`)
  distinct from `unrecognized_requirement` and `invalid_geometry`.

Explicitly **out of scope**: the rest of mission doc §7's PM
responsibilities (decompose problems, assign tasks, coordinate agents,
monitor simulations, resolve conflicts, determine iteration) — those need
either multiple components interacting or a simulation agent to coordinate
with, neither of which exist yet.

68/68 tests passing.

## Milestone: v0.4 — Aerodynamics Agent research spike (DONE, real XFOIL + surrogate)

Mission doc Phase 3: "begin with a well-understood benchmark: NACA 0012 →
CL/CD, validated against published/reference data."

**Solver decision record, part 1 (2026-09-14):** the mission doc lists
OpenFOAM, SU2, XFOIL as candidates. `pip install xfoil` failed with an
opaque CMake configure error under the MinGW Makefiles generator, even
with `gfortran` present via MinGW64, and WSL wasn't installed. Rather than
sink unbounded time into native build debugging, we shipped v0.4 with
**NeuralFoil** — a pip-installable neural-network aerodynamic surrogate,
published and validated against XFOIL/experimental data — clearly
disclaimed as not a first-principles solver.

**Solver decision record, part 2 — real XFOIL, resolved (2026-09-15):**
asked to actually fix the toolchain rather than settle. Root-caused
properly instead of guessing:

1. **Missing `mingw32-make`**: MinGW64 had `gcc`/`g++`/`gfortran` but not
   `mingw32-make.exe`, which CMake's `MinGW Makefiles` generator requires
   to even configure. Fixed: `pacman -S mingw-w64-x86_64-make`.
2. **The PyPI sdist for `xfoil` 1.1.1 is broken** — comparing it to the
   GitHub repo, the sdist is missing `CMakeLists.txt` and the entire
   `src/` Fortran tree entirely (an upstream packaging bug, not
   environment-specific — `pip install xfoil` would fail this way on any
   platform). Confirmed by extracting both and diffing. Worked around by
   building directly from `github.com/DARcorporation/xfoil-python`
   instead of PyPI.
3. **setuptools defaults to the `msvc` compiler class on Windows**
   regardless of whether Visual Studio is installed, which made CMake try
   to use a nonexistent VS generator. Fixed by pinning
   `[build_ext]\ncompiler=mingw32` in `setup.cfg`.
4. **The resulting DLL depended on MinGW runtime DLLs**
   (`libgfortran`/`libgcc`/`libwinpthread`) that Windows/Python 3.8+'s
   `ctypes.cdll.LoadLibrary` won't find via `PATH` alone (dependent-DLL
   search was restricted for security). Fixed by statically linking
   (`-DCMAKE_SHARED_LINKER_FLAGS=-static`), producing a wheel that depends
   only on `KERNEL32.dll`/`msvcrt.dll` — no runtime PATH tricks needed.

Real XFOIL now runs and gives genuine Newton-iteration boundary-layer
convergence output, not a surrogate estimate. The built wheel is vendored
at `vendor/xfoil/` (Windows x64 + CPython 3.13 only — see its README) with
a reproducible build script at `scripts/build_xfoil_windows.sh`, since the
PyPI package can't be relied on. **NeuralFoil is kept as the always-
available default backend** (works on CI/ubuntu-latest and any platform);
real XFOIL is an opt-in `backend="xfoil"` parameter, feature-detected via
`agents.aerodynamics.agent.XFOIL_AVAILABLE`.

Scope:

- `agents/aerodynamics/agent.py` — `AerodynamicsAgent.evaluate_naca_airfoil
  (designation, alpha_deg, reynolds, backend="neuralfoil"|"xfoil") ->
  AeroResult(cl, cd, cm, l_over_d, confidence, backend)`.
- Validated two ways: **physically-grounded invariants** (NACA 0012
  symmetric CL/CM≈0 at alpha=0, monotonic lift in the linear regime,
  positive drag, cambered-airfoil positive zero-alpha lift) for both
  backends, plus a **cross-validation test**
  (`test_xfoil_and_neuralfoil_cross_validate_on_naca0012`) checking the
  real solver and the surrogate agree within 0.05 CL / 0.005 CD across a
  0–8° sweep — the strongest validation available without a specific
  published reference table on hand.
- `examples/airfoil/run.py` — NACA 0012 alpha sweep (0–10°, Re=1e6),
  printing both backends side by side. Verified 2026-09-15: they agree
  within ~1-2% across the whole sweep.

Explicitly **out of scope**: wiring this into the CAD loop (the wing
geometry has no airfoil section yet — flat-plate approximation, see v0.2),
OpenFOAM/SU2 (3D CFD — a materially bigger undertaking than a 2D panel
method), and a cosmetic upstream bug in `xfoil`'s own `__del__` (harmless
`ctypes`/`PermissionError` warning on cleanup, documented in
`vendor/xfoil/README.md`, not patched since it's third-party code).
81/81 tests passing.

## Ownership (current sprint)

| Area | Owner |
|---|---|
| Repo scaffolding, backend integration, CI, releases | chief (logo) |
| Geometry Agent + CAD exporters + geometry validity checks | kilo |
| Design Agent + Aerodynamics Agent | dune |

## Milestone: v0.5 — Structures Agent (real FEA) + wing airfoil sections (DONE)

Two parallel, non-overlapping tracks, both landed 2026-09-15.

### Structures Agent — Phase 4 research spike, real CalculiX

Mission doc Phase 4: "begin with simple validation cases... Case 1:
Cantilever beam." Following the same root-cause-don't-settle approach as
v0.4 part 2:

- **CalculiX (`ccx.exe`) installed via MSYS2's `pacman`**
  (`mingw-w64-x86_64-calculix-ccx`) — chosen over Code_Aster (needs a
  ~3GB Salome-Meca install) as the lightest-weight option matching the
  mission doc's candidate list. Not vendored as a file (unlike XFOIL):
  it depends on a large MSYS2 runtime DLL stack (openblas, arpack,
  pastix, scotch) that isn't practical to statically link. Install via
  `scripts/install_calculix_windows.sh`; located at runtime via
  `shutil.which` with a default-path fallback.
- **Found and root-caused a genuine solver hang**: this build's default
  sparse solver (PaStiX) hangs indefinitely — confirmed on a trivial
  10-element, 216-equation cantilever beam that should solve in
  milliseconds (verified by manually killing the stuck process, checking
  it was genuinely stalled during PaStiX's Scotch matrix-ordering step,
  not just slow). **Fix**: every generated `.inp` deck's `*STATIC` card
  must say `SOLVER=SPOOLES` explicitly (CalculiX's classic bundled direct
  solver) — with it, the same problem solves in ~12ms. Full story in
  `vendor/calculix/README.md`.
- `agents/structures/agent.py` — `StructuresAgent.evaluate_cantilever_beam
  (length_mm, width_mm, height_mm, force_n, ...) -> StructuralResult
  (tip_deflection_mm, max_bending_stress_mpa, analytical_deflection_mm,
  deflection_error_pct)`, generating a parametric B31 beam-element `.inp`
  deck and parsing CalculiX's own `.dat` output (latin-1 encoded — an
  early parser bug from missing the blank separator line between a header
  and its data rows was caught and fixed during development).
- **Validated against exact closed-form Euler-Bernoulli beam theory** —
  the strongest validation in the repo so far (not an invariant, not a
  cross-validation between two models, but literal classical mechanics):
  reference case (1m steel beam, 20×10mm section, 100N tip load) gives FEA
  deflection 94.95mm vs. analytical 95.24mm, **0.30% error**, consistent
  with B31 correctly including Timoshenko shear deformation that pure
  Euler-Bernoulli neglects.
- `examples/beam/run.py` — runs the reference case, prints FEA vs.
  analytical side by side.

Explicitly **out of scope**: meshing/analyzing actual 3D CAD solids from
`agents/geometry` (this uses CalculiX's native 1D beam elements on a
parametric beam directly, not an imported mesh — that needs a real mesher
like gmsh) and Code_Aster (heavier install, CalculiX already satisfies the
mission doc's candidate list).

### Wing airfoil cross-sections — connecting Geometry and Aerodynamics

The wing's flat-plate approximation (v0.2) is replaced with real NACA
4-digit airfoil cross-sections, reusing `aerosandbox` (already a project
dependency via the Aerodynamics Agent) rather than reimplementing airfoil
coordinate generation — the first real connection between the Geometry
and Aerodynamics agents.

- `agents/design/agent.py` — optional `naca_airfoil` parameter parsed from
  e.g. "NACA 2412 airfoil" (defaults to 12.0 = NACA 0012 when omitted).
  Round-tripped through the existing `dict[str, float]` schema with no
  contract changes: a 4-digit NACA code is stored as a plain float (e.g.
  2412.0) and reconstructed with `f"{int(value):04d}"` zero-padding.
- `agents/geometry/wing.py` — lofts between root/tip cross-sections built
  from real `aerosandbox.Airfoil` coordinates (scaled by chord) instead of
  flat rectangles, still mirrored about the root for symmetry.
- Validated with an **exact analytical volume formula** for the
  quadratically-varying loft cross-section:
  `V = area_norm · span · (c_root² + c_root·c_tip + c_tip²) / 3` (the
  frustum-volume integral for a linearly-tapered, self-similar
  cross-section) — matched to the B-Rep volume within 0.0001%.

Explicitly **out of scope**: twist/washout, and any actual coupling to the
Aerodynamics Agent's evaluation (the wing now *looks* like a real airfoil
shape, but nothing yet feeds this geometry into `evaluate_naca_airfoil` or
vice versa — still separate agents sharing a coordinate source).

97/97 tests passing across both tracks combined.

## Ownership (current sprint)

| Area | Owner |
|---|---|
| Repo scaffolding, backend integration, CI, releases | chief (logo) |
| Geometry Agent + CAD exporters + geometry validity checks + Structures Agent | kilo |
| Design Agent + Aerodynamics Agent + wing airfoil sections | dune |

## Milestone: v0.6 — real solid-mesh FEA + wing aero coupling (DONE)

Two parallel, non-overlapping tracks, both landed 2026-09-15.

### Real 3D solid FEA on meshed CAD geometry (gmsh + CalculiX)

The Structures Agent (v0.5) only analyzed a parametric 1D beam idealization
via CalculiX's native B31 elements — never an actual meshed CAD solid.
This closes that gap, proven against a second classical elasticity
benchmark (the beam validation used Euler-Bernoulli theory; this uses
**Kirsch's solution**, 1898): a small circular hole in a wide plate under
remote uniaxial tension has a stress concentration factor of exactly 3.0
at the hole edge — directly relevant since the bracket
(`agents/geometry/bracket.py`) is itself a plate with holes.

- **gmsh chosen and pre-validated by chief before delegating**: pip-
  installable, no compiler needed, and confirmed to import a
  build123d-exported STEP file directly (same OCC kernel) — including the
  actual 4-hole bracket, meshed cleanly with zero errors. A standalone box
  cantilever beam, meshed as C3D10 solid tets and solved the same way,
  gave 95.10mm tip deflection vs. 95.24mm analytical Euler-Bernoulli
  (0.15% error) — even tighter than v0.5's 1D beam-element result (0.30%).
  Three independent methods (analytical, 1D beam FEA, 3D solid FEA) agree
  within 0.3% of each other.
- Two more gmsh-specific gotchas found and documented (on top of v0.5's
  SOLVER=SPOOLES one): its Abaqus/`.inp` writer silently drops any entity
  without an explicit Physical Group as soon as *any* group is defined
  (so the volume itself must be grouped, not just the faces used for
  node sets); and it also emits CPS6 plane-stress shell elements for 2D
  physical groups that CalculiX rejects outright in a 3D analysis — fixed
  by extracting just the `*NODE`/`*ELEMENT,type=C3D10` blocks from gmsh's
  raw output rather than feeding it to `ccx.exe` directly.
- `agents/structures/agent.py` — `StructuresAgent.evaluate_plate_with_hole
  (width_mm, height_mm, thickness_mm, hole_diameter_mm, tensile_stress_mpa,
  ...) -> PlateWithHoleResult(max_stress_mpa, nominal_stress_mpa,
  stress_concentration_factor, theoretical_kt, error_pct)`.
  `agents/structures/plate_with_hole.py` builds the plate (build123d) and
  meshes it (gmsh, refined near the hole via Distance+Threshold fields
  sized as ratios of hole diameter/plate width so it generalizes across
  sizes) — kept out of `agents/geometry` since it's a validation fixture,
  not a mission-doc component.
- Textbook-correct minimal rigid-body constraint handling: the whole fixed
  face pinned only in the loading direction (which alone blocks two
  rotational DOF), plus two carefully chosen points pinning the 3
  remaining DOF — avoids over-constraining and artificially stiffening
  the stress reading.
- Hole sizes needing a finite-width correction (i.e. not small enough for
  the infinite-plate approximation) are explicitly rejected rather than
  silently validated against the wrong theoretical Kt.
- **Reported honestly, not tuned to hit a number**: reference case
  (200×200×5mm plate, 10mm hole = 5% of width) converges to Kt=2.989,
  0.36% error. Checked robustness at 3% and 8% hole-to-width ratios too —
  0.50% and 1.96% error respectively, both still small but visibly growing
  as the small-hole approximation is stretched, exactly as expected.
- `examples/plate_with_hole/run.py` demonstrates the reference case.

Explicitly **out of scope**: meshing/analyzing the bracket or wing
themselves (this proves the pipeline on a purpose-built validation
fixture, not yet wired to real mission-doc components) and a finite-width
stress-concentration correction for larger holes.

### Wing aerodynamics coupling

The Aerodynamics Agent (v0.4) and the wing's `naca_airfoil`/`root_chord`/
`wing_span` parameters (v0.5) existed independently — nothing computed a
wing's actual aerodynamic performance from its own CAD spec.

- `engineering/analysis/wing_aero.py` — `evaluate_wing_aero(spec,
  cruise_velocity_mps=25.0 [mission doc's own UAV example value],
  alpha_deg=4.0, ...) -> WingAeroSummary(reynolds_number, cl, cd,
  l_over_d, lift_n, drag_n, backend)`. Computes Reynolds number from root
  chord and cruise velocity, planform area from the trapezoidal wing
  geometry, dynamic pressure, and calls `AerodynamicsAgent` with the
  spec's actual `naca_airfoil` value to get real dimensional lift and drag
  — the first time a wing's own geometry parameters drive an aerodynamic
  evaluation rather than a hand-picked airfoil/Re/alpha.
- `examples/wing/aero_summary.py` — parses a natural-language wing
  requirement and prints its CAD parameters alongside computed
  Re/CL/CD/L/D/lift/drag. Verified 2026-09-15: mission-doc reference wing
  at 25 m/s gives Re≈4.11×10⁵ and physically sane lift/drag.

Explicitly **out of scope**: feeding this back to size the wing's
structure, or any optimization loop — this is a one-way evaluation.

113/113 tests passing across both tracks combined.

## Ownership (current sprint)

| Area | Owner |
|---|---|
| Repo scaffolding, backend integration, CI, releases | chief (logo) |
| Geometry Agent + CAD exporters + geometry validity checks + Structures Agent | kilo |
| Design Agent + Aerodynamics Agent + wing airfoil sections + wing/aero coupling | dune |

## Milestone: v0.7 — real bracket FEA + closed-loop aero optimization (DONE)

Two parallel, non-overlapping tracks, both landed 2026-09-15. Both v0.6
"next milestone" candidates were pursued together rather than choosing one.

### Real solid FEA on the actual bracket geometry

`evaluate_plate_with_hole` (v0.6) proved the mesh→CalculiX solid-FEA
pipeline on a purpose-built validation fixture. This wires it to
`agents/geometry/bracket.py`'s actual `build_bracket()` output for the
first time — under a real "bolted mounting bracket" load case: all 4
holes rigidly fixed (bolted), a distributed transverse load on the top
face.

There's no closed-form solution for a 4-hole bracket under an arbitrary
load (unlike the beam's Euler-Bernoulli or the plate-with-hole's Kirsch
solution), so **chief pre-validated a different, still-rigorous
methodology before delegating**: CalculiX's `RF` (reaction force) output,
summed across all fixed nodes, must equal the total applied load to
numerical precision for any correctly converged linear static solve —
verified on a standalone test case to 0.0002% agreement. This exact
equilibrium check, plus mesh convergence at two densities, replaces a
closed-form target.

- `agents/structures/bracket_mesh.py` meshes the real bracket (imports
  `build_bracket` directly, no duplicated geometry); `agents/structures/agent.py`'s
  `evaluate_bracket(length_mm, width_mm, thickness_mm, hole_diameter_mm,
  hole_count, applied_force_n, ...) -> BracketStructuralResult
  (max_stress_mpa, max_deflection_mm, equilibrium_error_pct,
  mesh_converged, coarse_mesh_max_stress_mpa, fine_mesh_max_stress_mpa)`.
- **Found and fixed a real bug via the equilibrium check itself**: hole
  rims are shared edges between each hole's (fixed) face and the (loaded)
  top face, so ~4.5% of "loaded" nodes were also fully constrained —
  CalculiX doesn't fold a `*CLOAD` at an already-fixed node back into that
  node's reaction force, so that fraction of the applied load was
  silently vanishing from the global balance. Excluding the overlap
  dropped equilibrium error from 4.5% to **0.001%** on the reference case
  (verified again independently: 0.0008%).
- **Convergence reported honestly, not forced**: a 5-point mesh-density
  sweep showed deflection converging smoothly and monotonically, but peak
  von Mises stress did *not* monotonically settle — consistent with a
  genuine FEA stress singularity at the sharp fixed-hole-rim
  boundary-condition corner (a real, well-known FE phenomenon: peak
  nodal/Gauss-point stress at such a corner has no guaranteed
  mesh-independent limit), not a bug. The specific density pair actually
  observed to converge (both metrics <10% change) was shipped and
  documented, rather than picking whichever pair happened to look clean.
- `agents/structures/inp_utils.py` — `.inp` block-extraction helpers
  factored out and shared with `plate_with_hole.py` (previously
  duplicated).
- `examples/bracket/structural_analysis.py` demonstrates the reference
  case: 100×80×5mm bracket, four 8mm holes, 500N top load → 7.09MPa peak
  stress (raw; see v0.8 for the hotspot-vs-raw split this number became),
  0.0007mm deflection, 0.0008% equilibrium error, converged.

The stress-singularity ambiguity noted here (peak stress not reliably
convergent) was resolved in v0.8 below — not left as permanent future
work after all.

### Closed-loop aerodynamic optimization (Phase 5 MVP)

Scoped honestly as single-discipline (aerodynamics only — no structures,
manufacturing, or cost in the loop, and no optimization feeding back into
CAD regeneration). Before writing any code, **chief checked the objective
function's math and caught a degenerate-optimization risk**: wing taper
ratio has zero effect on L/D in the current strip-theory-style
`evaluate_wing_aero` model (CL/CD come purely from the 2D section polar,
independent of planform shape), so "optimize taper for max L/D" would
have silently produced a meaningless flat-objective result. Redirected to
angle of attack instead, which does meaningfully vary L/D (a real polar
shape: rises, peaks, falls toward stall).

- `engineering/analysis/wing_optimizer.py` — `optimize_wing_for_max_l_over_d
  (base_spec, candidate_naca_airfoils=[...], alpha_bounds_deg=(-2,12), ...)
  -> WingOptimizationResult`. For each candidate NACA airfoil,
  `scipy.optimize.minimize_scalar` (bounded) finds the angle of attack
  maximizing L/D via repeated real solver calls (NeuralFoil/XFOIL); the
  best airfoil+alpha combination overall is reported alongside every
  candidate's result (losers included, not hidden).
- **Verified non-degenerate**: each candidate airfoil converges to a
  different *interior* optimum (never stuck at a search-bound edge),
  e.g. on the mission-doc reference wing: NACA 0012 peaks at L/D=57.7 at
  α=5.81°, NACA 4412 at L/D=101.7 at α=6.16° — a real, physically
  meaningful difference, not noise.
- `examples/wing/optimize.py` demonstrates the full candidate table plus
  the winner.

Explicitly **out of scope**: multi-disciplinary optimization (would need
structures/manufacturing/cost objectives too), optimizing actual geometry
parameters (only angle of attack, a flight condition, is varied — see the
degenerate-taper finding above for why), and genetic/Bayesian algorithms
(mission doc lists these as future candidates; scipy's bounded scalar
minimizer is the right-sized tool for this one-dimensional problem).

129/129 tests passing across both tracks combined (bracket FEA's two-
density convergence check is now the slowest test in the repo, ~1.5min).

## Ownership (current sprint)

| Area | Owner |
|---|---|
| Repo scaffolding, backend integration, CI, releases | chief (logo) |
| Geometry Agent + CAD exporters + geometry validity checks + Structures Agent | kilo |
| Design Agent + Aerodynamics Agent + wing airfoil sections + wing/aero analysis + optimization | dune |

## Milestone: v0.8 — bracket stress-singularity fix + geometry optimization (DONE)

Two parallel, non-overlapping tracks, both landed 2026-09-15 — both v0.7
"next milestone" candidates pursued together, same as v0.6→v0.7.

### Bracket stress-singularity resolution

v0.7 found and honestly reported a real problem: peak von Mises stress at
the bracket's fixed-hole-rim corner didn't converge with mesh refinement
(a genuine FEA stress singularity), while deflection converged cleanly.
Two standard techniques were tried, in order of invasiveness:

1. **Nodal-averaged stress** (`*NODE FILE`, extrapolated from Gauss points
   and averaged across all elements sharing a node) alone — confirmed to
   help but not fully fix it: still ~12% swings across the same 5-point
   density sweep used in v0.7.
2. **Hot-spot stress** (mean of the top 1% highest nodal-averaged von
   Mises values — a standard fatigue/design-code convention specifically
   for handling singular locations) layered on top of nodal averaging —
   converges to within ~3% across the same sweep.

`agents/geometry/bracket.py`'s actual hole geometry was deliberately left
untouched (a shared component; changing the real mission-doc bracket's
shape would have been a bigger decision than this task warranted) — this
fixes how the solved stress field is aggregated into a metric, not the
mesh or the part.

`BracketStructuralResult` fields renamed for honesty:
`max_stress_mpa` → `hotspot_stress_mpa` (now drives `mesh_converged`),
plus a new `raw_peak_stress_mpa` (kept for transparency, explicitly
documented as not reliably convergent). New
`agents/structures/frd_utils.py` parses CalculiX's `.frd` nodal-results
file — fixed-width ASCII, not whitespace-delimited (adjacent values can
abut with no separating space when a negative sign takes a positive
value's leading space) — to get nodal-averaged stress, which `.dat`'s
`*NODE PRINT`/`*EL PRINT` output cannot provide.

Reference case now converges cleanly: `hotspot_stress_mpa`=5.48MPa vs.
`raw_peak_stress_mpa`=8.38MPa at 100×80×5mm/4×8mm holes/500N,
`mesh_converged`=True (independently re-verified by chief on main).

### Closed-loop bracket mass optimization

Extends v0.7's optimization pattern to a real geometry parameter (v0.7's
optimizer only varied a flight condition, alpha — see that section for
why taper ratio would have been degenerate). Given mission doc's own
emphasis on minimizing weight subject to structural margins, and that
`evaluate_bracket` now exists and works: find the **thinnest bracket that
still satisfies a maximum allowable stress**.

**A real cost-profile design decision, made explicit before coding**:
each `evaluate_bracket` call costs ~1-1.5 minutes (unlike v0.7's aero
optimizer, where evaluations are near-instant), so a naive grid search or
gradient method would burn 20-30+ minutes on redundant evaluations.
Since the underlying problem — thinner → higher stress, thicker → lower
stress, find where stress crosses the allowable — is naturally a
**root-find**, not a general minimization, `scipy.optimize.brentq`
(bounded, guaranteed convergence given a valid sign-change bracket,
typically 10-20 evaluations) is the right-sized tool. The monotonicity
assumption and the sign-change bracket are both verified against real FEA
at both bounds *before* searching, with clear errors naming exactly which
assumption failed and how to fix the input bounds if not.

- `engineering/analysis/bracket_optimizer.py` —
  `optimize_bracket_thickness_for_min_mass(length_mm, width_mm,
  hole_diameter_mm, hole_count, applied_force_n, max_allowable_stress_mpa,
  ...) -> BracketOptimizationResult(optimal_thickness_mm, optimal_mass_kg,
  max_stress_at_optimum_mpa, max_allowable_stress_mpa, evaluations)`.
  Evaluations are cached (by rounded thickness) to avoid redundant solves
  if brentq re-probes a nearby point.
- **A real coordination hazard caught and fixed mid-flight**: this task's
  work was accidentally created directly in the shared working directory
  instead of its own git worktree (the exact mistake fixed at this
  project's very start) — caught before any commit happened, no work
  lost; files were moved into the correct worktree and a proper branch
  re-created from current main. A reminder that this discipline needs
  re-enforcing periodically, not just set up once.
- **A real cross-branch timing collision, also caught and fixed**: this
  task's code was written against the pre-v0.8 field name
  (`max_stress_mpa`) while the stress-singularity fix (renaming it to
  `hotspot_stress_mpa`) landed on main concurrently on a different branch.
  Chief updated the affected files, independently re-ran both the fast
  (mocked) and real-FEA tests to confirm correctness, before handing back
  for review — a real example of why treating a sibling agent's
  in-progress API as provisional (not final) matters even when told to
  treat it as a "stable black box."
- Verified end-to-end on the reference bracket (100×80mm, 4×8mm holes,
  500N load, 6.50MPa allowable): converges to 5.55mm thickness, 6.53MPa
  hotspot stress (+0.4% from target) in 10 real FEA evaluations
  (~9-10 minutes wall clock), independently confirmed by chief before
  merge.
- `examples/bracket/optimize.py` demonstrates the full run with an
  evaluation-history table.

Explicitly **out of scope**: optimizing multiple geometry parameters at
once (e.g. thickness + hole placement together — a genuinely harder
multi-dimensional problem needing a different algorithm than 1D
root-finding), and any manufacturability constraint on the resulting
thin-wall thickness (that's Phase 6).

151/151 tests passing across both tracks combined (two real-FEA tests now
in the suite — the bracket convergence check and the bracket optimizer's
real-CalculiX test — together push a full local run to ~12 minutes).

## Ownership (current sprint)

| Area | Owner |
|---|---|
| Repo scaffolding, backend integration, CI, releases | chief (logo) |
| Geometry Agent + CAD exporters + geometry validity checks + Structures Agent | kilo |
| Design Agent + Aerodynamics Agent + wing airfoil sections + wing/aero/bracket analysis + optimization | dune |

## Next milestone: v0.9 (not yet scoped)

Candidates: Phase 6 (manufacturing intelligence) — CNC/additive
manufacturability checks on the actual bracket/wing geometry, following
the same evaluate-honestly, validate-against-something-real approach used
for CFD/FEA rather than inventing scoring heuristics with no ground
truth; multi-parameter bracket optimization (thickness + hole placement
together, needing a proper multi-dimensional method rather than 1D
root-finding); or resolving the wing's remaining approximations (no
twist/washout, aero not yet coupled to the actual airfoil solid) toward a
fuller flagship UAV wing demonstration (mission doc §20).
