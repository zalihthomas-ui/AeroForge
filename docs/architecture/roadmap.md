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

## Next milestone: v0.3 (not yet scoped)

Candidates, to be decided before assigning: (a) Design Agent as engineering
project manager (mission doc §7 — missing-parameter detection, requirement
decomposition) still without touching simulation; (b) begin Phase 3 (CFD)
research spike — evaluate OpenFOAM vs. SU2 vs. XFOIL against the NACA 0012
reference case per mission doc Phase 3, as research only, no autonomous
optimization until validated. (b) is a materially bigger, slower-moving
piece of work than anything done so far and should be scoped deliberately
before starting.
