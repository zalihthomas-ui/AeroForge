# AEROFORGE Roadmap & Current Milestone

The full 8-phase roadmap (research, CAD MVP, design agent, CFD, FEA,
closed-loop optimization, manufacturing intelligence, dashboard, autonomous
lab) is defined in the root mission doc. That roadmap spans an estimated
20+ weeks of work, including integrating real CFD/FEA solvers — it is not
something to fake or stub out as "done."

Development proceeds **vertically**: one working loop end-to-end before
adding the next discipline.

## Active milestone: v0.1 — CAD MVP loop

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

- `examples/bracket/run.py` runs end-to-end and produces a valid `.step` +
  `.stl` from a plain-language bracket requirement.
- `agents/geometry` rejects/flags invalid geometry (self-intersections,
  non-solids) rather than silently exporting bad output.
- Unit tests exist for both agents and pass in CI.
- README and this roadmap accurately describe what exists vs. what is
  future work.
