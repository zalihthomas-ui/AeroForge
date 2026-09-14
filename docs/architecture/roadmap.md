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

## Next milestone: v0.5 (not yet scoped)

Candidates: give the wing geometry a real airfoil cross-section (instead
of the flat-plate approximation) so the Aerodynamics Agent's NACA
evaluation can eventually attach to actual wing CAD; or begin Phase 4
(Structures/FEA) research the same way Phase 3 was approached here —
evaluate solver options (CalculiX, Code_Aster), root-cause any toolchain
failures properly (as v0.4 part 2 did) rather than settling immediately,
and only fall back to a validated surrogate if a genuine, well-documented
blocker remains.
