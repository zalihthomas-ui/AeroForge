# Airfoil example (v0.4)

Run: `python examples/airfoil/run.py`

Evaluates NACA 0012 (the mission doc's Phase 3 benchmark) across an angle-
of-attack sweep, printing both:

- **NeuralFoil** — a validated neural surrogate, always available.
- **XFOIL** — the real Fortran panel-method/boundary-layer solver, if the
  vendored wheel is installed (Windows x64 + CPython 3.13 only — see
  `vendor/xfoil/README.md`). The two backends agree within ~1-2% across
  the sweep, which is itself a meaningful cross-validation.

Getting real XFOIL running took solving three separate problems on this
machine: a missing `mingw32-make`, a broken PyPI sdist (missing
`CMakeLists.txt`/`src/` — had to build from GitHub source instead), and
setuptools defaulting to the `msvc` compiler class. Full story in
`docs/architecture/roadmap.md`'s v0.4 section.

This is a standalone 2D airfoil-section case, independent of the CAD loop
(`examples/bracket/`, `examples/wing/`) — the wing geometry has no airfoil
profile yet (flat-plate approximation), so there's nothing to wire together
yet. That integration is future work once both sides are ready.
