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

## Milestone: v0.4 — Aerodynamics Agent research spike (DONE, surrogate)

Mission doc Phase 3: "begin with a well-understood benchmark: NACA 0012 →
CL/CD, validated against published/reference data."

**Solver decision record:** the mission doc lists OpenFOAM, SU2, XFOIL as
candidates. We evaluated XFOIL first (lightest-weight, matches the 2D
NACA 0012 benchmark exactly):

1. `pip install xfoil` (compiled-from-source Fortran module, DARcorporation/
   xfoil-python) fails to build on this machine — CMake configure step
   errors under the MinGW Makefiles generator, even with `gfortran`
   already present via MinGW64. Root cause not chased further (native
   build-toolchain debugging, unbounded time cost).
2. WSL is not installed (`wsl --install` needs a reboot/admin — not done
   without an explicit ask).
3. A prebuilt third-party XFOIL `.exe` (e.g. from a GitHub repo's bundled
   binary) was considered and rejected for now — running unverified
   third-party native code is a materially different trust decision than
   installing from PyPI.

**Chosen instead: NeuralFoil** (`agents/aerodynamics/agent.py`) — a
pip-installable, no-compiler-needed neural-network aerodynamic surrogate,
published and validated against XFOIL/experimental data. This is
explicitly **not** XFOIL/OpenFOAM/SU2 — every file that uses it says so.
Real first-principles solver integration remains future work, to be
revisited once the toolchain/WSL question is deliberately resolved.

Scope:

- `agents/aerodynamics/agent.py` — `AerodynamicsAgent.evaluate_naca_airfoil
  (designation, alpha_deg, reynolds) -> AeroResult(cl, cd, cm, l_over_d,
  confidence)`, wrapping `aerosandbox.Airfoil` + `neuralfoil.get_aero_from_airfoil`.
- Validated against **physically-grounded invariants**, not memorized
  reference numbers we couldn't independently verify: NACA 0012 (symmetric)
  gives ~zero CL/CM at alpha=0; CL increases monotonically over a small
  positive alpha sweep; CD is always positive; a cambered airfoil (e.g.
  NACA 2412) gives positive lift at alpha=0.
- `examples/airfoil/run.py` — NACA 0012 alpha sweep (0–10°, Re=1e6).
  Verified 2026-09-14: CL≈0 at alpha=0, monotonic lift increase, L/D peaks
  around alpha=8° (~76) then falls off toward alpha=10° — textbook-shaped
  polar, consistent with the surrogate being physically sound.

Explicitly **out of scope**: wiring this into the CAD loop (the wing
geometry has no airfoil section yet — flat-plate approximation, see v0.2),
and any first-principles solver. 76/76 tests passing.

## Ownership (current sprint)

| Area | Owner |
|---|---|
| Repo scaffolding, backend integration, CI, releases | chief (logo) |
| Geometry Agent + CAD exporters + geometry validity checks | kilo |
| Design Agent + Aerodynamics Agent | dune |

## Next milestone: v0.5 (not yet scoped)

Candidates: give the wing geometry a real airfoil cross-section (instead
of the flat-plate approximation) so the Aerodynamics Agent's NACA
evaluation can eventually attach to actual wing CAD; resolve the
XFOIL/WSL toolchain question deliberately as its own scoped task; or begin
Phase 4 (Structures/FEA) research the same way Phase 3 was approached here
— evaluate solver options, document constraints honestly, choose a
pragmatic validated path rather than forcing the exact tool list if it
doesn't fit this environment.
