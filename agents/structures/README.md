# Structures Agent (v0.5 beam, v0.6 solid FEA fixture, v0.7 real bracket)

Three evaluation methods, all using **real CalculiX** (`ccx.exe`) — not a
surrogate, the genuine FEA solver, the same way `agents/aerodynamics` can
drive real XFOIL:

- `evaluate_cantilever_beam(length_mm, width_mm, height_mm, force_n, ...)`
  (v0.5): a fixed-free cantilever beam via B31 Timoshenko beam elements —
  a parametric 1D idealization, not a meshed solid. Validated against
  exact closed-form Euler-Bernoulli theory (~0.3% error). See
  `examples/beam/run.py`.
- `evaluate_plate_with_hole(width_mm, height_mm, thickness_mm,
  hole_diameter_mm, tensile_stress_mpa, ...)` (v0.6): real **3D solid
  FEA** on a purpose-built validation fixture (not a mission-doc
  component) — a build123d solid, meshed via **gmsh** into quadratic
  (C3D10) tetrahedra, refined near the hole. Validated against Kirsch's
  classical stress-concentration solution (Kt=3.0), ~0.4% error. See
  `agents/structures/plate_with_hole.py` and `examples/plate_with_hole/run.py`.
- `evaluate_bracket(length_mm, width_mm, thickness_mm, hole_diameter_mm,
  hole_count, applied_force_n, ...)` (v0.7): real 3D solid FEA on the
  **actual** `agents/geometry/bracket.py` component, under a bolted-
  mounting load case (holes fixed, top face loaded). No closed-form
  solution exists here, so validated by **exact force equilibrium**
  (sum of reaction forces must equal the applied load — a mathematical
  identity for any correct linear solve, ~0.001% error on the reference
  case) and mesh convergence at two densities — with peak stress reported
  honestly as not always monotonically convergent (a real FEA stress
  singularity at the fixed-hole-rim corner, not a bug). See
  `agents/structures/bracket_mesh.py` and
  `examples/bracket/structural_analysis.py`.

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
around by extracting just the `*NODE`/`*ELEMENT,type=C3D10` blocks
(`agents/structures/inp_utils.py`, shared between the plate and bracket
meshing code) rather than feeding gmsh's raw output to `ccx.exe`. A third
gotcha found in v0.7: shared nodes between a fixed face and a loaded face
(e.g. a bracket hole's rim, which borders both the fixed hole surface and
the loaded top face) silently drop their share of applied load from the
reaction-force balance — excluded from the loaded set once identified.
