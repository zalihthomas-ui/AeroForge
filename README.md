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
time (see `docs/architecture/roadmap.md`). Working today (v0.4):

```text
Engineering Prompt → Design Agent → Geometry Agent → build123d → STEP / STL
```

for two components: a mounting **bracket** and a flat-plate **wing**
planform (see `examples/bracket/`, `examples/wing/`) — plus a standalone
2D **Aerodynamics Agent** (`examples/airfoil/`) evaluating NACA airfoils
via NeuralFoil, a validated neural surrogate, *not* real XFOIL/OpenFOAM/SU2
(those failed to build on this machine's toolchain — see the roadmap's
decision record) and not yet wired into the CAD loop.

FEA, manufacturing analysis, optimization, and any aerodynamic realism for
the wing are real, unimplemented future phases — not stubbed out as if
they worked. Do not assume they exist yet just because the mission doc
describes them.

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

python examples/bracket/run.py
python examples/wing/run.py
python examples/airfoil/run.py
```

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md).

## License

[MIT](LICENSE)
