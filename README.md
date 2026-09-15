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
time (see `docs/architecture/roadmap.md`). Working today (v0.9):

```text
Engineering Prompt → Design Agent → Geometry Agent → build123d → STEP / STL
```

for two components: a mounting **bracket** and a **wing** planform with a
real NACA airfoil cross-section (see `examples/bracket/`, `examples/wing/`)
— plus real-solver Aerodynamics, Structures, and (new in v0.9)
Manufacturing agents, and a genuinely closed optimization loop for the
wing (Design Agent → optimizer → **materialized, re-verified CAD**, the
first complete "prompt to optimized CAD" chain in this project):

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
  `examples/bracket/structural_analysis.py`, `examples/bracket/optimize.py`):
  real **CalculiX** FEA — a parametric cantilever beam (validated against
  Euler-Bernoulli theory, ~0.3% error), a meshed 3D solid plate-with-hole
  (gmsh + C3D10 tets, validated against Kirsch's classical solution,
  ~0.4% error), and the **actual bracket geometry** under a real
  bolted-mounting load, validated by exact force equilibrium (~0.001%
  error) and mesh convergence — including a resolved stress-concentration
  singularity (hot-spot stress convention, ~3% convergence) since no
  closed-form solution exists for that case. Closed-loop optimization
  (`engineering/analysis/bracket_optimizer.py`) finds the minimum-mass
  bracket thickness satisfying a stress constraint via bounded
  root-finding against real FEA.
- **Manufacturing Agent** (new in v0.9, `examples/bracket/manufacturability.py`):
  real CNC design-for-manufacturability checks — drill depth-to-diameter
  ratio and actual hole-to-edge clearance — on the actual bracket
  geometry, each against a sourced, documented machining convention.

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
python examples/bracket/optimize.py    # slow: real closed-loop FEA optimization, ~10 min
```

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md).

## License

[MIT](LICENSE)
