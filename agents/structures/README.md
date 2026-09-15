# Structures Agent (v0.5 beam, v0.6 solid FEA fixture, v0.7 bracket, v0.10 wing)

Four evaluation methods, all using **real CalculiX** (`ccx.exe`) — not a
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
  hole_count, applied_force_n, ...)` (v0.7, stress metric fixed in v0.8):
  real 3D solid FEA on the **actual** `agents/geometry/bracket.py`
  component, under a bolted-mounting load case (holes fixed, top face
  loaded). No closed-form solution exists here, so validated by **exact
  force equilibrium** (sum of reaction forces must equal the applied load
  — a mathematical identity for any correct linear solve, ~0.001% error on
  the reference case) and mesh convergence at two densities. Stress is
  reported two ways: `hotspot_stress_mpa` (mean of the top 1% highest
  nodal-averaged von Mises values — a standard fatigue/design-code
  convention for singular locations, and what `mesh_converged` is based
  on, ~3% convergence) and `raw_peak_stress_mpa` (the single highest
  value, informational only — does not reliably converge, a real FEA
  stress singularity at the fixed-hole-rim corner, not a bug). See
  `agents/structures/bracket_mesh.py`, `agents/structures/frd_utils.py`,
  and `examples/bracket/structural_analysis.py`.
- `evaluate_wing(wing_spec, cruise_velocity_mps=25.0, alpha_deg=4.0, ...)`
  (v0.10, load distribution made realistic in v0.11): real 3D solid FEA
  on the **actual** `agents/geometry/wing.py` component (real NACA
  airfoil cross-sections, not a flat-plate approximation), loaded by its
  own computed aerodynamic lift via
  `engineering.analysis.wing_aero.evaluate_wing_aero` — the first time an
  aerodynamic result drives a structural load in this project rather than
  a hand-picked force. Lift is distributed spanwise per the classical
  **elliptical (Prandtl) distribution**, not uniformly (v0.10's
  documented simplification) — concentrating more force near the root,
  which *reduced* peak stress/deflection versus uniform loading rather
  than increasing it (a shorter average moment arm to the fixed root, a
  counterintuitive but verified finding). A genuine symmetry-plane BC
  (`UY=0` at the root only) rather than full fixity, since the wing is
  physically continuous through its centerline under symmetric loading.
  Validated the same way as the bracket (exact force equilibrium + mesh
  convergence + hot-spot stress for the same fixed-edge singularity).
  Reference case: 1800mm span, NACA 0012, 65.7N real lift at 25m/s cruise
  → safety factor ~350 (correctly large for a lightly loaded 1g cruise
  condition, not a red flag). See `agents/structures/wing_mesh.py` for
  two genuinely non-obvious meshing findings (real-airfoil trailing-edge
  sliver elements; no face exists at the wing's root after `build_wing`'s
  mirror/fuse operation) and `examples/wing/structural_analysis.py`.

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
reaction-force balance — excluded from the loaded set once identified. A
fourth found in v0.8: CalculiX's `.frd` nodal-results file is fixed-width
ASCII, not whitespace-delimited — adjacent values can abut with no
separating space when a negative sign takes a positive value's leading
space, so it must be parsed by character position (`frd_utils.py`), not
`split()`.

`engineering/analysis/bracket_optimizer.py` (v0.8) closes the loop:
`optimize_bracket_thickness_for_min_mass(...)` finds the thinnest
(lightest) bracket satisfying a maximum allowable stress, via bounded
root-finding (`scipy.optimize.brentq`) against `evaluate_bracket` —
query-efficient by design since each FEA evaluation costs ~1-1.5 minutes.
`engineering/analysis/bracket_materializer.py` and
`engineering/analysis/wing_materializer.py` (v0.9/v0.10) close the loop
the rest of the way, generating real CAD for the optimizer's chosen
design and re-verifying it reproduces the optimizer's own numbers. See
`examples/bracket/optimize.py`, `examples/bracket/materialize.py`,
`examples/wing/optimize.py`, `examples/wing/materialize.py`.
