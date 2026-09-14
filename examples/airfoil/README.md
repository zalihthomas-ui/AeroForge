# Airfoil example (v0.4)

Run: `python examples/airfoil/run.py`

Evaluates NACA 0012 (the mission doc's Phase 3 benchmark) across an angle-
of-attack sweep using the Aerodynamics Agent.

**This uses NeuralFoil, a validated neural surrogate — not real XFOIL,
OpenFOAM, or SU2.** Real XFOIL failed to build on the development machine
(CMake/MinGW toolchain issue) and WSL wasn't installed; see
`docs/architecture/roadmap.md` for the full decision record. Swapping in a
first-principles solver is future work once that toolchain question is
resolved deliberately.

This is a standalone 2D airfoil-section case, independent of the CAD loop
(`examples/bracket/`, `examples/wing/`) — the wing geometry has no airfoil
profile yet (flat-plate approximation), so there's nothing to wire together
yet. That integration is future work once both sides are ready.
