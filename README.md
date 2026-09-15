# AEROFORGE

### Autonomous AI Engineering & Generative CAD Platform

> **From Engineering Intent to Verified Geometry.**

AEROFORGE is an open-source, multi-agent engineering platform that transforms
high-level engineering requirements into parametric CAD, simulation-validated
designs, and manufacturable components.

```text
Engineering Requirement → Design Agent → Geometry Agent → Parametric CAD
                                              ↓
                                       CFD  ⇄  FEA
                                              ↓
                              Manufacturing Agent → Optimization Agent
                                              ↓
                                        Revised CAD → Re-Analysis (loop)
```

The full mission, philosophy, and long-term roadmap are documented in
[`AEROFORGE — Mission, Vision & Production Plan.md`](<AEROFORGE — Mission, Vision & Production Plan.md>).

## Current status

This repository is built **vertically**, one complete engineering loop at a
time (see `docs/architecture/roadmap.md`). Working today (v0.11), and
worth starting here: **`python examples/wing/flagship_demo.py`** runs the
actual mission doc §20 flagship demonstration end-to-end — a UAV wing
requirement, evaluated for real, genuinely failing a lift-adequacy check
(65.67N produced vs. 117.72N needed for a 12kg-MTOW aircraft), then
closed-loop resized until it passes (real CAD exported), all with real
solvers, no fictional numbers:

```text
Engineering Prompt → Design Agent → Geometry Agent → build123d → STEP / STL
```

for two components: a mounting **bracket** and a **wing** planform with a
real NACA airfoil cross-section (see `examples/bracket/`, `examples/wing/`)
— plus real-solver Aerodynamics, Structures, and Manufacturing agents, and
genuinely closed optimization loops for *both* components (Design Agent →
optimizer → **materialized, re-verified CAD**, complete "prompt to
optimized CAD" chains):

- **Aerodynamics Agent** (`examples/airfoil/`, `examples/wing/aero_summary.py`,
  `examples/wing/optimize.py`): NACA airfoils via NeuralFoil (a validated
  neural surrogate, always available) or real **XFOIL** (vendored at
  `vendor/xfoil/` for Windows x64 + CPython 3.13 — the PyPI package is
  broken upstream; see the roadmap's decision record). Coupled to the
  wing's own CAD parameters for real Reynolds number/lift/drag, plus a
  closed-loop optimizer (`engineering/analysis/wing_optimizer.py`) that
  finds the best airfoil/angle-of-attack combination for max L/D via a
  real `scipy` optimizer — and (new in v0.9) `wing_materializer.py`
  actually **regenerates real CAD** for that optimum and re-verifies it
  reproduces the optimizer's numbers (`examples/wing/materialize.py`).
- **Structures Agent** (`examples/beam/`, `examples/plate_with_hole/`,
  `examples/bracket/structural_analysis.py`, `examples/bracket/optimize.py`,
  `examples/wing/structural_analysis.py`): real **CalculiX** FEA — a
  parametric cantilever beam (validated against Euler-Bernoulli theory,
  ~0.3% error), a meshed 3D solid plate-with-hole (gmsh + C3D10 tets,
  validated against Kirsch's classical solution, ~0.4% error), the
  **actual bracket geometry** under a real bolted-mounting load, and the
  **actual wing geometry** loaded by its own real computed aerodynamic
  lift — the first time an aerodynamic result drives a structural load in
  this project — distributed spanwise per the real elliptical (Prandtl)
  lift distribution, not a uniform approximation. Both real-CAD cases
  validated by exact force equilibrium and mesh convergence, including a
  resolved stress-concentration singularity (hot-spot stress convention)
  since no closed-form solution exists for either. Closed-loop
  optimization (`bracket_optimizer.py`) plus materialization for both
  wing and bracket (`bracket_materializer.py`, `wing_materializer.py`) —
  every optimizer now regenerates and re-verifies real CAD, not just
  numbers.
- **Manufacturing Agent** (`examples/bracket/manufacturability.py`): real
  CNC design-for-manufacturability checks — drill depth-to-diameter ratio
  and actual hole-to-edge clearance — on the actual bracket geometry,
  each against a sourced, documented machining convention.
- **Flagship demo** (`engineering/analysis/wing_flagship.py`,
  `examples/wing/flagship_demo.py`): the actual mission doc §20
  demonstration — mission requirements (MTOW, cruise speed, span, safety
  factor) → real lift/L-D/safety-factor evaluation → PASS/FAIL →
  closed-loop resizing until it passes → sized CAD exported. Mass is
  reported as informational solid-CAD-volume only, not part of PASS/FAIL
  (a solid-aluminum wing computes to ~14.7kg, heavier than the whole
  aircraft — unrepresentative of real hollow/foam UAV construction, a
  gap noted honestly rather than papered over).

The frontend dashboard is a real, unimplemented future phase — not
stubbed out as if it worked. Do not assume it exists yet just because the
mission doc describes it.

## Repository layout

```text
agents/          design, geometry, aerodynamics, structures, manufacturing, optimization agents
cad/             build123d / cadquery geometry generation + exporters
simulation/      cfd, fea, meshing (future phases)
optimization/    genetic, bayesian, pareto search (future phases)
engineering/     requirement/constraint/knowledge schemas
backend/         FastAPI service exposing the pipeline
frontend/        React + Three.js engineering dashboard (future phase)
examples/        end-to-end runnable demonstrations
tests/           unit tests, mirrored by subsystem
docs/            architecture notes, tutorials, research
```

## Quickstart

```bash
python -m venv .venv
.venv/Scripts/activate         # Windows; use `source .venv/bin/activate` on Unix
pip install -r backend/requirements.txt
pytest

# optional: real XFOIL backend (Windows x64 + CPython 3.13 only)
pip install vendor/xfoil/xfoil-1.1.1-cp313-cp313-win_amd64.whl

# optional: real CalculiX FEA solver (Windows, via MSYS2)
./scripts/install_calculix_windows.sh

python examples/bracket/run.py
python examples/wing/run.py
python examples/airfoil/run.py
python examples/beam/run.py
python examples/plate_with_hole/run.py
python examples/wing/aero_summary.py
python examples/wing/optimize.py
python examples/wing/materialize.py
python examples/bracket/structural_analysis.py
python examples/bracket/manufacturability.py
python examples/wing/structural_analysis.py
python examples/bracket/optimize.py    # slow: real closed-loop FEA optimization, ~10 min
python examples/bracket/materialize.py # slow: chains optimize + materialize, ~15-17 min
python examples/wing/flagship_demo.py  # the flagship demo -- start here if you only run one
```

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md).

## License

[MIT](LICENSE)
