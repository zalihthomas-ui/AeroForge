# Aerodynamics Agent (v0.4)

`AerodynamicsAgent.evaluate_naca_airfoil(designation, alpha_deg, reynolds,
backend=...)` evaluates a NACA airfoil section via one of two backends:

- `backend="neuralfoil"` (default) — a published, XFOIL/experiment-validated
  neural surrogate. Always available (pure Python, pip-installable).
- `backend="xfoil"` — the **real XFOIL** Fortran solver (genuine coupled
  panel-method + boundary-layer analysis). Only available if the vendored
  wheel is installed: Windows x64 + CPython 3.13 only, since the PyPI
  `xfoil` sdist is broken upstream (missing `CMakeLists.txt`/`src/`). See
  `vendor/xfoil/README.md` and `docs/architecture/roadmap.md`'s v0.4
  section for the full build story. Check
  `agents.aerodynamics.agent.XFOIL_AVAILABLE` before requesting it, or
  catch `AerodynamicsEvaluationError`.

Both backends were cross-validated against each other on NACA 0012 (agree
within ~1-2%) — see `tests/aerodynamics/test_xfoil_backend.py`.

Not yet wired into the CAD loop — the wing geometry (`agents/geometry/wing.py`)
has no airfoil section yet (flat-plate approximation).

See `examples/airfoil/run.py` for a runnable NACA 0012 demonstration.
