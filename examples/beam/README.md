# Cantilever beam example (v0.5)

Run: `python examples/beam/run.py`

The mission doc's Phase 4 "Case 1: Cantilever beam" validation case,
evaluated with the Structures Agent's real CalculiX solver (not a
surrogate). Prints the FEA tip deflection alongside the closed-form
Euler-Bernoulli comparison — this is the strongest validation in the repo:
exact classical beam theory, not a physically-grounded invariant or a
cross-validation between two models.

Requires CalculiX (`ccx.exe`) — install with
`scripts/install_calculix_windows.sh`, see `vendor/calculix/README.md` for
the full story, including a critical solver-hang gotcha this project
worked around.

Standalone structural case, independent of the CAD loop
(`examples/bracket/`, `examples/wing/`) — not yet meshing/analyzing the
actual CAD geometry those produce. That integration (real 3D solid meshing
via e.g. gmsh) is future work; this uses CalculiX's native 1D beam
elements directly.
