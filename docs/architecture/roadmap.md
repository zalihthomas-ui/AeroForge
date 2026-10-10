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

## Milestone: v0.9 — first Manufacturing Agent + optimizer-to-CAD closed loop (DONE)

Two parallel, non-overlapping tracks, both landed 2026-09-15.

### Manufacturing Agent (Phase 6, first version)

`agents/manufacturing/` had been a placeholder since v0.1. Two real,
sourced CNC design-for-manufacturability checks on the **actual**
`agents/geometry/bracket.py` component:

- **Drill depth-to-diameter ratio** (`thickness_mm / hole_diameter_mm`)
  against a 5:1 standard jobber-drill limit — a widely cited CNC
  design-for-manufacturability rule of thumb (e.g. Protolabs' design
  guides), documented as convention rather than asserted as a rigid
  standard.
- **Real hole-to-part-edge clearance** — the genuine worst-case minimum
  distance from any hole's edge to the nearest part edge (checked in both
  length and width directions, across every hole), against a
  1x-hole-diameter minimum (Xometry/Protolabs convention). On the
  reference bracket this is 8.5mm — genuinely tight against the 8mm
  requirement, not the much looser 36mm a naive width-only check would
  report. `agents/geometry/validation.py`'s existing `MIN_EDGE_MARGIN_MM`
  (2mm) only guarantees non-degenerate geometry; this is a materially
  tighter, real manufacturability bar on top of it.

**The additive-manufacturing overhang stretch goal was investigated and
deliberately not shipped**: the bracket's planar faces are geometrically
guaranteed zero-overhang in Z-up build orientation (a plain box — every
planar face normal has Z in {0, +1, -1}), so a planar-only check would
always trivially report "fully self-supporting," providing no real
signal. The bracket's actual overhang risk is entirely in its cylindrical
hole walls, which need point-sampling or parametric-surface analysis to
check properly — explicit future work, not silently skipped, and not
padded into the deliverable just to have shipped *something* for the
stretch goal.

A genuine duplication was also caught and fixed in passing: the hole-
spacing formula existed independently in both `bracket.py` and
`bracket_mesh.py`; factored into a single `hole_center_x_positions()` now
shared by geometry, structures, and this new manufacturing check —
verified as a pure refactor via the unchanged existing test suite.

`examples/bracket/manufacturability.py` demonstrates both the reference
bracket (manufacturable) and a deliberately thick/narrow-hole case that
genuinely fails the drill-ratio check.

### Closing the loop: optimizer → revised CAD

Mission doc §14's closed-loop diagram ends in "OPTIMIZATION AGENT →
REVISED CAD → ITERATE" — never implemented until now. v0.8's bracket
optimizer and v0.7's wing optimizer both found *numeric* optima, but
nothing then generated the actual CAD geometry for the chosen design.

- `engineering/analysis/wing_materializer.py` —
  `materialize_optimal_wing(base_spec, optimization_result, output_dir,
  ...) -> MaterializedWingResult`: takes a `WingOptimizationResult`,
  builds the revised `EngineeringSpec` with the winning airfoil, generates
  real geometry via `GeometryAgent`, exports STEP/STL/3MF, and — a genuine
  consistency check, not just trusting the optimizer — **re-evaluates**
  aerodynamics on the final materialized spec at the optimizer's own
  optimal angle of attack, comparing L/D against what the optimizer
  originally reported.
- Verified end-to-end: reference wing (NACA 4412 winner, α=6.16°) 
  produces a real 562KB STEP / 34KB STL / 11KB 3MF, and the re-analysis
  reproduces the optimizer's L/D=101.71 with **0.0000% discrepancy** —
  exactly as expected for an identical underlying evaluation, and a
  meaningful confirmation that nothing was lost or inconsistent between
  the optimization and materialization stages.
- `examples/wing/materialize.py` demonstrates the first genuinely
  complete chain in this project: natural-language requirement → Design
  Agent → closed-loop aerodynamic optimizer → materialized, re-verified
  CAD.

Explicitly **out of scope**: closing the same loop for the bracket
optimizer (v0.8) — the bracket's revised-CAD step would just re-run
`build_bracket` with the optimal thickness, which is straightforward, but
wasn't asked for this round; and any iteration back into a *further*
optimization pass (this is one closed loop, not yet a multi-generation
iterate-until-convergence process).

Two coordination notes worth recording honestly: this round repeated
v0.8's worktree-isolation mistake once (task B work briefly created
outside its proper worktree — caught immediately, no work lost, same fix
pattern as before) and needed a trivial post-hoc fix (a Windows console
encoding issue with a unicode degree symbol in example output, garbling
to `?` — fixed before merge, matching every other example's plain-text
convention).

161/161 (non-slow-FEA) tests passing.

## Ownership (current sprint)

| Area | Owner |
|---|---|
| Repo scaffolding, backend integration, CI, releases | chief (logo) |
| Geometry Agent + CAD exporters + geometry validity checks + Structures Agent + Manufacturing Agent | kilo |
| Design Agent + Aerodynamics Agent + wing airfoil sections + wing/aero/bracket analysis + optimization + CAD materialization | dune |

## Milestone: v0.10 — real wing structural FEA + bracket optimizer-to-CAD loop (DONE)

Two parallel, non-overlapping tracks, both landed 2026-09-15.

### Real solid FEA on the actual wing, loaded by real aerodynamics

Mission doc §20's flagship UAV wing demonstration needs mass, L/D, *and*
safety factor. Mass and L/D existed (v0.5/v0.7); structural safety factor
for a wing did not — `evaluate_cantilever_beam` and `evaluate_bracket`
only ever handled flat/beam idealizations. This closes that gap the same
way v0.6→v0.9 closed the others: mesh the actual `agents/geometry/wing.py`
solid (real NACA airfoil sections, not an idealization) and load it with
a **real computed value**, not a hand-picked one —
`engineering.analysis.wing_aero.evaluate_wing_aero`'s own lift_n. First
time an aerodynamic result drives a structural load in this project.

No closed-form solution exists for this geometry (same situation as the
bracket), so validated the same rigorous way: exact force equilibrium
(0.005-0.02% error on the reference case) plus mesh convergence, with the
same hot-spot stress convention reused unchanged for the same fixed-edge
singularity pattern found on the bracket.

Two genuinely new, non-obvious problems surfaced and were fixed — this
geometry is meaningfully harder to mesh than the bracket's flat plate:

1. **Real-airfoil trailing-edge sliver elements.** A NACA 0012's trailing
   edge is only ~0.25% of chord thick (~0.6mm on a 240mm root chord). The
   bracket's local Distance+Threshold mesh refinement field silently
   *overrode* gmsh's automatic curvature-adaptive sizing rather than
   combining with it, so its coarser `SizeMax` won right at the
   razor-thin TE — producing genuine negative-volume ("sliver")
   tetrahedra that CalculiX rejected outright ("nonpositive jacobian
   determinant"). A properly-combined `Curvature`+`Min` field was tried
   first (correct in principle) but didn't finish computing in over 10
   minutes on this geometry — abandoned honestly rather than forced. The
   fix that actually works: drop the custom field entirely, rely solely
   on gmsh's global curvature-adaptive sizing — zero bad elements, meshes
   in under a second.
2. **No face exists at the wing's root.** `build_wing()` mirrors both
   halves into one fused solid, so after that boolean union y=0 is purely
   interior geometry — no 2D face to apply a boundary condition to.
   Fixed by intersecting the full wing with a half-space to recover a
   genuine half-wing solid with a real planar root face (verified to have
   exactly half the full wing's volume) — which also enabled a **proper
   symmetry-plane BC** (`UY=0` only at the root) instead of full fixity,
   since the wing is physically continuous through its centerline under
   symmetric loading and full fixity there would have been wrong (it
   would block natural in-plane elastic deformation, artificially
   over-stiffening the result) — unlike the bracket's holes, which really
   are rigid bolted connections.

Reference case (1800mm span, NACA 0012, 65.7N real lift at 25 m/s
cruise): `mesh_converged`=True, equilibrium error 0.005-0.02%,
**safety factor ≈290** — correctly recognized and reported as physically
sane rather than a suspicious number: this is a lightly loaded 1g steady
cruise condition on an aluminum structure, not a limit-load case, so a
large margin is expected, not a red flag. Material (aluminum 6061,
documented as a simplification — a real small UAV wing might use
foam-core composite) and all properties are configurable, not hardcoded.

`agents/structures/wing_mesh.py`, `examples/wing/structural_analysis.py`.
6 new tests.

### Closing the optimizer-to-CAD loop for the bracket

The wing got this in v0.9; the bracket's own optimizer (v0.8) still
lacked it. `engineering/analysis/bracket_materializer.py` mirrors
`wing_materializer.py`'s pattern (generate real CAD for the optimizer's
chosen design, re-verify it reproduces the optimizer's numbers) — with
one structural difference worth noting: the bracket path has no
`EngineeringSpec`/`GeometryAgent` indirection the wing path does (those
agents work with plain parameter dicts directly), so
`materialize_optimal_bracket` calls `build_bracket()` directly rather
than going through the Design/Geometry Agent pipeline.

Independently verified twice by chief: the standalone real-FEA test alone
(104.8s) and the full end-to-end example chaining optimization (~15 min,
8 evaluations) plus materialization (~95s) — both confirm **0.0000%**
stress discrepancy between the optimizer's prediction and the
materialized design's actual re-analysis, `mesh_converged`=True,
equilibrium error 0.00007%. Both mission-doc components (wing, bracket)
now have complete "prompt → optimized → materialized → re-verified CAD"
chains.

`examples/bracket/materialize.py`. 4 new tests.

Explicitly **out of scope**: an elliptical (Prandtl) spanwise lift
distribution for the wing load (uniform distribution used instead,
clearly documented as a first-order simplification); iterating the
optimizer-to-CAD loop more than once (this is one closed loop per
component, not yet a multi-generation converge-until-stable process).

172/172 (non-slowest-bracket-FEA) tests passing.

## Ownership (current sprint)

| Area | Owner |
|---|---|
| Repo scaffolding, backend integration, CI, releases | chief (logo) |
| Geometry Agent + CAD exporters + geometry validity checks + Structures Agent + Manufacturing Agent | kilo |
| Design Agent + Aerodynamics Agent + wing airfoil sections + wing/aero/bracket analysis + optimization + CAD materialization | dune |

## Milestone: v0.11 — the actual mission doc §20 flagship demonstration (DONE)

Two parallel, non-overlapping tracks, both landed 2026-09-15. The first
time every real discipline built so far (Design, Geometry, Aerodynamics,
Structures, Optimization) works together on one end-to-end case.

### Mission doc §20's flagship demonstration, with real numbers

Mission doc §20 describes an illustrative UAV wing example: INITIAL
DESIGN (Mass 2.91kg, L/D 14.2, SF 1.32, FAIL) → iterate → FINAL DESIGN
(Mass 2.47kg, L/D 17.8, SF 1.71, PASS). Those specific numbers are
fictional prose, not a target — the goal was to build the genuine
pipeline and let real numbers fall out, matching or not.

**Chief worked out the physics before delegating**: for level cruise
flight, Lift = Weight, so `required_lift_n = mtow_kg * 9.81` is a real,
checkable constraint — not invented. Checked it against the actual
reference wing (1800mm span, 240/140mm chords) for a 12kg-MTOW aircraft
at 25 m/s: its planform area needs CL≈0.90 to produce enough lift, a
genuine, non-rigged number. This predicted the reference wing would
authentically FAIL a lift-adequacy check — confirmed exactly: 65.67N
produced vs. 117.72N required.

**Chief also caught a mass-modeling honesty issue before it could
mislead**: the wing's current geometry is a *solid* airfoil shape (no
hollow/shell structure). A solid-aluminum reference wing computes to
~14.7kg — heavier than the entire 12kg aircraft, obviously not
representative of real (foam/composite/hollow) UAV wing construction.
Scoped mass as informational-only (`solid_volume_mm3`, explicitly labeled
as not a realistic mass estimate) rather than part of the PASS/FAIL
determination, which would have required inventing an unsourced "effective
density" — avoided rather than papered over.

- `engineering/analysis/wing_flagship.py` — `evaluate_wing_design(spec,
  requirement)` assembles lift, L/D (`wing_aero`), safety factor
  (`evaluate_wing`), and span into one PASS/FAIL `FlagshipDesignResult`.
  `find_passing_wing_design(base_spec, requirement)` closes the loop for
  real when the initial design fails: scales chord (preserving span and
  taper ratio) via bounded root-finding (`scipy.optimize.brentq`) to hit
  the required lift exactly, re-verifies structural safety factor and
  span, and exports the sized CAD.
- **Verified end-to-end**: initial design (65.67N, FAIL) → sized design
  (chord ×2.05, 117.72N exactly, L/D 57.16, safety factor 1374→1643
  after v0.11's elliptical-load update, PASS). `examples/wing/flagship_demo.py`
  presents this in the mission doc's own INITIAL/FINAL style — the single
  most complete, most important demonstration in the repo.
- A minor self-referential data-model quirk was found, verified non-fatal
  (Python's dataclass `__repr__` auto-guards against the reference cycle),
  and cleaned up anyway once flagged: an already-passing design now
  returns `iterations=[]` instead of `iterations=[self]`.

Explicitly **out of scope**: a real mass/weight PASS/FAIL criterion (needs
a hollow/foam-core wing geometry model that doesn't exist yet — honestly
deferred, not faked); Manufacturing Agent checks in the flagship score
(no wing manufacturing process chosen yet).

### Elliptical (Prandtl) spanwise lift distribution for the wing

v0.10 documented the wing's uniform load as a first-order simplification.
This replaces it with the real classical elliptical distribution —
`L'(y) = (4L)/(π·b)·√(1-(2y/b)²)` (Prandtl lifting-line theory) — verified
by numerical integration to reduce to exactly the total lift before being
relied on, applied as normalized per-node weights so the equilibrium
check is preserved unchanged regardless of the (non-uniform) mesh node
distribution.

**A genuine correction to chief's own task brief, caught and explained
rigorously**: the brief predicted concentrating load near the root would
be *more* structurally demanding. Verified opposite: switching to
elliptical loading *decreased* peak stress and deflection (~0.79MPa/
0.25mm vs. v0.10's ~0.95MPa/0.34mm) — concentrating force near the root
actually *shortens* its average moment arm to the fixed root (elliptical
force centroid at ~43% of half-span vs. uniform's 50%), reducing bending
demand rather than increasing it. Confirmed both analytically and against
actual mesh node positions before writing it up. Mesh convergence was
re-verified under the new load at three densities rather than assuming
the v0.10 density pair still held (it did).

One unrelated, honestly-flagged finding: `test_bracket_optimizer.py`'s
real-CalculiX test failed once during a full-suite run but passed
reliably in isolation (chief independently confirmed: 21/21 fast +
reliable standalone) — an environment/timing flake under sustained
multi-process load, not a regression, and not code this track touched.

184+/185ish tests passing across both tracks combined (exact count shifts
run-to-run given the flake above; every individual suite run clean).

## Ownership (current sprint)

| Area | Owner |
|---|---|
| Repo scaffolding, backend integration, CI, releases | chief (logo) |
| Geometry Agent + CAD exporters + geometry validity checks + Structures Agent + Manufacturing Agent | kilo |
| Design Agent + Aerodynamics Agent + wing airfoil sections + wing/aero/bracket/flagship analysis + optimization + CAD materialization | dune |

## Milestone: v0.12 — realistic wing mass + multi-parameter bracket optimization (DONE)

Two parallel, non-overlapping tracks, both landed 2026-09-15, then wired
together by chief into the flagship demo (a small, deliberate follow-up
integration, not delegated — see below).

### Realistic wing mass, closing the v0.11 honesty gap

v0.11 explicitly deferred a real mass estimate: a solid-aluminum wing
computes to ~14.7kg, heavier than the entire 12kg aircraft, obviously not
representative of real (thin-skin) UAV construction.

**Chief found a genuine crash before delegating**: the obvious approach
(hollow the solid via build123d's `offset(amount=-t,
kind=Kind.INTERSECTION)`, a constant-wall-thickness boolean) **segfaulted**
(exit code 139, a hard crash in the OCC kernel, not a clean exception) on
this geometry. Kilo independently reproduced it (hung past 90s, consistent
with the segfault) before building anything on the finding.

Rather than fight the crash, used the standard first-order aircraft-
conceptual-design thin-shell approximation instead: `mass ≈ surface_area ×
skin_thickness × density`, needing only `Part.area` (a safe, fast
geometric query — no boolean operation, no crash risk). Defaults sourced
the same way the Manufacturing Agent sourced its thresholds (0.5mm typical
thin composite skin, 1600 kg/m³ typical E-glass/epoxy laminate), both
overridable. Reference wing: **~0.56kg** — clearly lighter than the solid-
aluminum figure it replaces, and (documented honestly) skin mass only, not
including spars/ribs/internal structure.

**Kilo made a disciplined call on the stretch goal** (attempting real
hollow 3D geometry via loft-based construction instead of post-hoc
offsetting): worked out *analytically* that the root trailing edge is only
~0.6mm thick, so any offset-based approach — solid-hollowing or profile-
lofting — would hit the identical self-intersection failure there,
independent of construction method. Reported this reasoning instead of
spending implementation time re-deriving the same failure empirically.

`agents/geometry/wing.py`'s `estimate_wing_shell_mass_kg()`. 7 new tests.

**Chief wired this into the flagship demo** (`wing_flagship.py`) as a
small follow-up integration: `FlagshipDesignResult` gains `shell_mass_kg`
alongside the existing `solid_volume_mm3` (kept, now clearly labeled as a
raw geometric fact, NOT a mass estimate, to avoid confusion). Still
informational only, not part of `overall_status` — there's no sourced
"max wing mass" requirement to check it against (would need a full
aircraft weight budget, out of scope). Verified end-to-end: the flagship
demo's sized design now reports **1.159kg** — a genuinely plausible number
for a real UAV wing panel, landing naturally in the same order of
magnitude as the mission doc's own fictional example range (2.47-2.91kg
for, presumably, the whole aircraft) without ever being tuned to match it.

### Multi-parameter bracket optimization (thickness + hole diameter)

v0.8's `bracket_optimizer.py` optimized one variable (thickness) via
root-finding, since the problem was a single equation, single unknown. Two
variables (thickness, hole diameter) with one constraint (max stress)
means a whole *curve* of constraint-satisfying points — a genuine
constrained optimization problem, not a root-find.

**A real cost-profile decision, made explicit before coding** (mirroring
v0.8's brentq reasoning): a gradient-based constrained method (SLSQP,
trust-constr) would need finite-difference gradients (~3 evaluations per
2D iteration) over 10-20+ iterations — 30-60+ evaluations at ~1-1.5min
each is a real risk. Used `scipy.optimize.minimize(method='COBYLA')`
instead — derivative-free, handles inequality constraints natively,
query-efficient for low-dimensional expensive problems — with an explicit
bounded evaluation budget and a fast geometric pre-filter
(`validate_bracket_parameters`) so COBYLA probes on invalid geometry never
waste an expensive FEA solve.

`engineering/analysis/bracket_optimizer_2d.py`. Fast/mocked tests use a
stress surrogate *calibrated against the actual verified reference stress
value* (5.48 MPa at t=5mm, d=8mm — matching v0.10's real measurement, not
an arbitrary function). Real-FEA test verified (7:44, 4 evaluations) —
surfaced a useful, honestly-reported finding: COBYLA's scipy
implementation silently raises a too-small `max_evaluations` up to its 2D
minimum (`num_vars+2`) with a warning, worth knowing about even though the
optimizer still worked correctly. 16 new tests, 36/36 fast bracket-
optimizer tests (1D+2D combined) passing.

Explicitly **out of scope**: wiring the 2D optimizer's result into a
CAD-materializer (v0.8/v0.9's bracket_materializer.py only knows the 1D
result shape; a 2D materializer is straightforward future work, not done
here); resolving the `test_bracket_optimizer.py` flake (kilo independently
saw it recur a second time this round, unrelated to either track's
changes — now flagged twice across two rounds, worth root-causing if it
keeps happening).

204/204 fast tests passing combined (full suite with all real-FEA tests
now takes ~20+ minutes given the growing number of closed-loop
optimization/materialization chains).

## Ownership (current sprint)

| Area | Owner |
|---|---|
| Repo scaffolding, backend integration, CI, releases | chief (logo) |
| Geometry Agent + CAD exporters + geometry validity checks + Structures Agent + Manufacturing Agent | kilo |
| Design Agent + Aerodynamics Agent + wing airfoil sections + wing/aero/bracket/flagship analysis + optimization + CAD materialization | dune |

## Next milestone: v0.13 (not yet scoped)

Candidates: a 2D bracket optimizer-to-CAD materializer (mirroring the 1D
one, now that the 2D optimizer exists); extending Manufacturing Agent
checks to the wing once a real wing manufacturing process (sheet-metal,
composite layup) is chosen; investigating the recurring
`test_bracket_optimizer.py` full-suite flake (seen twice now); or a full
aircraft weight budget model, enabling a genuine mass-based PASS/FAIL
criterion in the flagship demo (currently informational only for lack of
a sourced requirement to check against).

## Milestone: v0.14 — virtual wing structural test campaign (DONE)

Replaces the flagship's two weak points: lift computed as a 2D section CL
times planform area (no finite-wing correction), and a "safety factor" from
solid-section FEA at 1 g cruise (SF ~350-1600, no design meaning).

### What was built

- `engineering/analysis/wing_lifting_line.py` — Prandtl lifting line
  (Glauert Fourier collocation) for straight tapered wings; section `a0`
  and `alpha_L0` from NeuralFoil at mean-chord Re. Outputs CL, CDi, span
  efficiency, cl(y), lift per span.
- `engineering/analysis/wing_loads.py` — V-n diagram, CS-23.341 gust
  (Pratt, Kg), ultimate factor 1.5, spanwise shear/bending (inertia relief
  ignored, conservative).
- `agents/structures/wing_box.py` — thin-walled box (20-60 % chord, depth
  from the airfoil thickness), materials (Al 6061-T6, 7075-T6, quasi-iso
  CFRP with caveats), closed-form stress/deflection/plate buckling,
  per-bay minimum-mass sizing (brentq + sheet-gauge rounding), beam
  natural frequencies.
- `agents/structures/wing_box_fe.py` + `StructuresAgent.evaluate_wing_box`
  — own structured S8R mesh (no gmsh), CalculiX static / `*BUCKLE` /
  `*FREQUENCY`, all `SOLVER=SPOOLES`.
- `engineering/analysis/wing_campaign.py`, `examples/wing/structural_campaign.py`
  — requirement → aero sizing → loads → box sizing → FE verification → CAD.
- `agents/geometry/wing_structure.py` — the complete internal structure as
  CAD from the sized result: ribs (lightening holes), front/rear spar webs and
  box covers stepped per bay, LE/TE skin; STEP assembly + per-group STL and a
  mass breakdown (68 solids, 1.52 kg for the campaign wing).

### Decision record

- **The old flagship answer does not survive the 3D correction**: its
  sized wing (NACA 0012, 492 mm root, AR 4.6) makes 82.5 N, not 117.7 N.
  Closing lift = weight with NACA 0012 in 3D needs AR 2.5, outside
  lifting-line validity, so the campaign selects among NACA 0012/2412/4412
  the smallest valid wing: NACA 4412, root 305 mm, AR 7.46. The old
  flagship is left untouched for comparison.
- **Unswept planform** for the campaign: lifting line and the straight
  box beam assume no sweep.
- **Gust governs** (n = 4.24 vs 3.8) and Va > Vd for this slow wing; the
  gust formula is not stall-limited, so the result is conservative — kept
  and reported rather than tuned away.
- **Load introduction on the upper spar-cap lines**: spreading nodal lift
  over the 0.3 mm webs produced spurious web-crippling buckling modes.
- **Single-threaded ccx** for eigenvalue runs (non-deterministic otherwise;
  see vendor/calculix/README.md).
- **Buckling requirement is "none below ultimate" with SS-plate edges** —
  conservative; FE shows the real first buckling at 1.73 × ultimate. A
  calibrated coefficient would save mass; deliberately not done yet.

### Results and validation

See `docs/tutorials/structural-campaign.md` for the full tables. Box mass
0.95 kg (Al 6061-T6), all margins >= 0, every bay buckling-governed. FE vs
closed form: equilibrium ~1e-8 %, tip deflection +3 %, cover stress < 3 %,
first bending frequency -3 %, buckling factor inside the SS/clamped bound
and mesh-converged < 1 %. 33 new tests.

## Milestone: v0.15 — whole aircraft: fuselage, tail, mass & balance, stability (DONE)

- `agents/geometry/fuselage_tail.py` — lofted elliptical fuselage (hollow 0.8 mm skin + ply formers),
  NACA 0009 stabiliser / NACA 0010 fin split into fixed surfaces and elevator / rudder; labelled and
  coloured for the STEP assembly exporter; thin-airfoil flap effectiveness.
- `engineering/analysis/aircraft_layout.py` — tail-volume sizing (Raymer V_H 0.70, V_V 0.04), cabin
  sized around component boxes, component-based mass & balance, neutral point (VLM + AeroBuildup
  fuselage increment), wing placement by brentq for 10 % static margin, cruise trim (AeroBuildup
  with elevator; VLM all-moving-tail cross-check), full-aircraft labelled assembly.
- `examples/aircraft/design_aircraft.py`, `docs/tutorials/whole-aircraft.md`, 8 tests.
- `cad.exporters.export_parts_step` fixed for primitive solids (Box/Cylinder).

### Decision record

- **The wing position, not the tail arm, balances the aircraft**: with a fixed tail-volume
  coefficient the neutral point hardly moves with tail arm, so the tail arm is set by rule
  (3 × MAC) and the wing is placed (x_LE 272.6 mm → SM 10.0 %).
- **Design NP = VLM + fuselage increment**: AeroBuildup alone placed the NP aft of the VLM value
  despite the fuselage (weaker empirical tail downwash), so only its fuselage increment is used.

Result: 12.0 kg, payload capacity 5.33 kg, CG 46.6 % MAC, NP 412.4 mm, SM 10.0 %, trim α 2.71°,
elevator −2.10° (VLM equivalent −0.23°), 84-part STEP assembly.

## Milestone: v0.16 — detail design: dynamics, built-up tails, joints, close-up FE (DONE)

- `engineering/analysis/propulsion.py` — actuator-disk propeller, slipstream immersion and tail
  dynamic-pressure ratio, thrust-line moment, propeller normal-force ΔCmα.
- `engineering/analysis/flight_dynamics.py` — CAD inertia tensor, VLM downwash, power-on trim and
  neutral point, small-perturbation longitudinal/lateral models (Ixz primed derivatives), mode
  identification, MIL-F-8785C Level 1 checks, dihedral sized for the spiral mode, control authority,
  `design_flight_ready` (accepts built-up tails).
- `engineering/analysis/tail_structure.py` — CS-23-style tail loads (manoeuvre, 23.425 / 23.443
  gusts), Schrenk distribution, sized tail boxes, CalculiX check, built-up tail CAD (swept fin via
  `WingStructureSpec.sweep_le_deg`), CAD-measured tail masses.
- `agents/structures/stiffened_panel.py`, `joints.py`, `detail_fe.py`,
  `engineering/analysis/detail_design.py` — stringer-stiffened covers, riveted spar flanges, bonded
  stringers (Volkersen), rib checks; five close-up CalculiX models (open hole, notches/mousehole,
  bonded lap, stiffened panel and rib-web buckling) each checked against its hand method.
- `agents/geometry/wing_structure.py` `StructureDetails` — C-channel spars, stringers with run-outs and
  anti-peel rivets, ribs split at the spars with mouseholes, spar-flange notches, flanged lightening
  holes, bonded rib flanges, rivet rows.
- `examples/aircraft/detailed_aircraft.py`, `docs/tutorials/detail-design.md`.

### Decision record

- **Stringers must fit the ribs**: leg + 1 mm ≤ 35 % of the bay's box depth (both caps are
  notched), stringer count non-increasing outboard, and the bonding land must pass the full stringer
  load (Volkersen) — so the 11-15 mm deep tail boxes stay unstiffened.
- **CalculiX `*BUCKLE` lists only factors > 1** in this build (0.54 was reported as 1.05): all
  buckling runs solve at 0.1 × load and scale back (`BUCKLE_REFERENCE_SCALE`).
- **Wing-location bug**: leaves of moved sub-assemblies were exported/measured in local coordinates
  (the v0.15 video drew the wing at x = 0); `cad.exporters.world_shape` now applies the parents'
  transform to the raw OCC shape (also avoiding a deep copy of the assembly tree).
- **Masses close the loop**: detailed wing 1.14 kg (was 1.52), tails 0.247 + 0.094 kg (foam estimates
  0.128 + 0.056) → wing re-placed 63 mm aft, power-on SM 10.1 %, dihedral 3.5°, all modes Level 1;
  tail loads on the final design change < 1 %.

## Next milestone: v0.17 (candidates)

CG envelope over payload/battery cases and a weight budget with tolerances; fuselage FE (boom
bending/torsion from tail loads) and the wing-fuselage attachment (lugs, bolts); fastener
flexibility / load sharing; fatigue of the riveted joints; landing or launch/recovery loads;
gust response in the time domain with the linear models.
