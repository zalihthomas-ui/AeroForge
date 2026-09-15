# Structures Agent (v0.5 beam, v0.6 solid FEA)

Two evaluation methods, both using **real CalculiX** (`ccx.exe`) — not a
surrogate, the genuine FEA solver, the same way `agents/aerodynamics` can
drive real XFOIL:

- `evaluate_cantilever_beam(length_mm, width_mm, height_mm, force_n, ...)`
  (v0.5): a fixed-free cantilever beam via B31 Timoshenko beam elements —
  a parametric 1D idealization, not a meshed solid. Validated against
  exact closed-form Euler-Bernoulli theory (~0.3% error). See
  `examples/beam/run.py`.
- `evaluate_plate_with_hole(width_mm, height_mm, thickness_mm,
  hole_diameter_mm, tensile_stress_mpa, ...)` (v0.6): real **3D solid
  FEA** — an actual build123d solid, meshed via **gmsh** into quadratic
  (C3D10) tetrahedra, refined near the hole. Validated against Kirsch's
  classical stress-concentration solution (Kt=3.0 for a small hole in a
  wide plate under tension), ~0.4% error on the reference case. See
  `agents/structures/plate_with_hole.py` and `examples/plate_with_hole/run.py`.

Requires CalculiX installed separately (`scripts/install_calculix_windows.sh`)
since `ccx.exe` depends on a large stack of MSYS2 runtime DLLs that can't
be vendored as a single file the way the XFOIL wheel was. Feature-detected
via `agents.structures.agent.CALCULIX_AVAILABLE`; raises
`StructuresEvaluationError` (not a raw exception) if unavailable.

**Critical gotchas** (see `vendor/calculix/README.md` and
`plate_with_hole.py`'s module docstring): this MSYS2 build's default
solver (PaStiX) hangs indefinitely — every generated `.inp` deck forces
`SOLVER=SPOOLES` explicitly. gmsh's own `.inp` writer silently drops any
ungrouped entity once *any* Physical Group is defined, and also emits
CPS6 shell elements that CalculiX rejects in a 3D analysis — both worked
around by extracting just the `*NODE`/`*ELEMENT,type=C3D10` blocks rather
than feeding gmsh's raw output to `ccx.exe`.

Not yet meshing/analyzing the actual bracket or wing geometry from
`agents/geometry` — `evaluate_plate_with_hole` proves the real-solid-mesh
pipeline on a purpose-built validation fixture (kept out of
`agents/geometry` since it isn't a mission-doc component), not yet wired
to real CAD parts.
