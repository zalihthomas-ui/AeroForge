# Plate-with-hole example (v0.6)

Run: `python examples/plate_with_hole/run.py`

Real **3D solid FEA** (not 1D beam elements) on an actual build123d solid:
a plate with a centered hole, meshed via gmsh into quadratic (C3D10)
tetrahedra and solved by CalculiX. Validated against **Kirsch's classical
solution** (1898): a small circular hole in a wide plate under uniaxial
tension has a stress concentration factor of exactly 3.0 at the hole edge.
The reference case here converges to Kt≈2.99, ~0.36% error.

This is the first time this project meshes and analyzes actual CAD
geometry rather than a parametric beam idealization
(`examples/beam/run.py`) — directly relevant to the bracket's real
hole-in-plate geometry (`agents/geometry/bracket.py`), though this
validation fixture isn't wired into the CAD loop itself. See
`docs/architecture/roadmap.md`'s v0.6 section and
`agents/structures/plate_with_hole.py`'s docstring for the meshing
gotchas this uncovered.

Requires CalculiX (`ccx.exe`) and gmsh — install with
`scripts/install_calculix_windows.sh` and `pip install -r
backend/requirements.txt`.
