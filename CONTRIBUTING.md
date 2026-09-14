# Contributing to AEROFORGE

AEROFORGE is being developed **vertically**: one complete engineering loop at a
time, rather than many partial subsystems in parallel. See
[`docs/architecture/roadmap.md`](docs/architecture/roadmap.md) for the current
phase and what is explicitly out of scope until later phases.

## Setup

```bash
python -m venv .venv
.venv/Scripts/activate   # Windows
pip install -r backend/requirements.txt
pytest
```

## Where things live

| Path | Purpose |
|---|---|
| `agents/design/` | Turns a natural-language engineering requirement into a structured spec |
| `agents/geometry/` | Turns a structured spec into parametric CAD (build123d) |
| `cad/exporters/` | STEP / STL / 3MF export helpers |
| `backend/` | FastAPI service exposing the pipeline |
| `examples/` | End-to-end runnable demonstrations |
| `tests/` | Unit tests, mirrored by subsystem |

## Ground rules

- A design is only "done" once it exports valid geometry and passes the
  checks in `agents/geometry/validation.py` — see Core Philosophy §3.2 in the
  mission doc.
- Every parameter change should be traceable: prefer named engineering
  parameters (`wing_span`, `sweep`, ...) over raw geometry edits.
- Add a test alongside any new agent capability.
- Keep PRs scoped to one phase/subsystem where possible.
