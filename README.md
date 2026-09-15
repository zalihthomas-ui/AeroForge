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
time (see `docs/architecture/roadmap.md`). Working today (v0.7):

```text
Engineering Prompt → Design Agent → Geometry Agent → build123d → STEP / STL
```

for two components: a mounting **bracket** and a **wing** planform with a
real NACA airfoil cross-section (see `examples/bracket/`, `examples/wing/`)
— plus real-solver Aerodynamics and Structures agents, now both wired to
the actual CAD geometry:

- **Aerodynamics Agent** (`examples/airfoil/`, `examples/wing/aero_summary.py`,
  `examples/wing/optimize.py`): NACA airfoils via NeuralFoil (a validated
  neural surrogate, always available) or real **XFOIL** (vendored at
  `vendor/xfoil/` for Windows x64 + CPython 3.13 — the PyPI package is
  broken upstream; see the roadmap's decision record). Coupled to the
  wing's own CAD parameters for real Reynolds number/lift/drag, plus a
  closed-loop optimizer (`engineering/analysis/wing_optimizer.py`) that
  finds the best airfoil/angle-of-attack combination for max L/D via a
  real `scipy` optimizer.
- **Structures Agent** (`examples/beam/`, `examples/plate_with_hole/`,
  `examples/bracket/structural_analysis.py`): real **CalculiX** FEA — a
  parametric cantilever beam (validated against Euler-Bernoulli theory,
  ~0.3% error), a meshed 3D solid plate-with-hole (gmsh + C3D10 tets,
  validated against Kirsch's classical solution, ~0.4% error), and now
  the **actual bracket geometry** under a real bolted-mounting load,
  validated by exact force equilibrium (~0.001% error) and mesh
  convergence since no closed-form solution exists for that case.

Manufacturing analysis and the frontend dashboard are real, unimplemented
future phases — not stubbed out as if they worked. Do not assume they
exist yet just because the mission doc describes them.

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
python examples/bracket/structural_analysis.py
```

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md).

## License

[MIT](LICENSE)
