# Structures Agent (v0.5)

`StructuresAgent.evaluate_cantilever_beam(length_mm, width_mm, height_mm,
force_n, ...)` evaluates a fixed-free cantilever beam under a transverse
tip load using **real CalculiX** (`ccx.exe`, B31 Timoshenko beam elements)
— not a surrogate, the genuine FEA solver, the same way
`agents/aerodynamics` can drive real XFOIL.

Requires CalculiX installed separately (`scripts/install_calculix_windows.sh`)
since `ccx.exe` depends on a large stack of MSYS2 runtime DLLs that can't
be vendored as a single file the way the XFOIL wheel was. Feature-detected
via `agents.structures.agent.CALCULIX_AVAILABLE`; raises
`StructuresEvaluationError` (not a raw exception) if unavailable.

**Critical gotcha** (see `vendor/calculix/README.md`): this MSYS2 build's
default solver (PaStiX) hangs indefinitely on this machine, confirmed even
on a trivial problem. Every generated `.inp` deck forces
`SOLVER=SPOOLES` explicitly — never remove that if editing the deck
template.

Validated against exact closed-form Euler-Bernoulli beam theory (not an
invariant or cross-validation): FEA and analytical tip deflection agree
within ~0.3% on the reference case. See `examples/beam/run.py`.

Not yet meshing/analyzing real 3D CAD solids (the bracket/wing geometry
from `agents/geometry`) — this uses CalculiX's native 1D beam elements
directly on a parametric beam, not an imported mesh. That integration
needs a real mesher (e.g. gmsh) and is future work.
