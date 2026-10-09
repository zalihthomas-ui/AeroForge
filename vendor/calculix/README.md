# CalculiX (real FEA solver)

Unlike `vendor/xfoil/`, **CalculiX is not vendored as a file here** — `ccx.exe`
depends on a large stack of MSYS2 runtime DLLs (`libopenblas`, `libarpack`,
`libpastix`, `libscotch`, `libhwloc`, ...) that would be impractical to
statically link or bundle. Install it instead:

```bash
./scripts/install_calculix_windows.sh
```

This installs `mingw-w64-x86_64-calculix-ccx` via MSYS2's `pacman` (a large
dependency chain — a few hundred MB). `agents/structures/agent.py`
auto-detects `ccx.exe` on `PATH` or at the default MSYS2 location
(`C:\msys64\mingw64\bin\ccx.exe`) at runtime; no further setup is needed
once installed.

## Critical gotcha: the default solver hangs forever

This MSYS2 build of CalculiX (2.23) resolves to **PaStiX** as its default
sparse solver when no solver is specified in the input deck. On this
machine, PaStiX's matrix-ordering step (Scotch graph partitioning) hangs
indefinitely — confirmed on a trivial 10-element, 216-equation cantilever
beam problem that should solve in milliseconds. No error, no timeout, no
partial output: the process just sits there consuming a fixed ~16MB with
zero progress.

**The fix**: always specify `*STATIC, SOLVER=SPOOLES` (CalculiX's classic
bundled direct solver) instead of the bare `*STATIC` card. With SPOOLES,
the same problem solves in ~12ms. `agents/structures/agent.py` always
generates decks with `SOLVER=SPOOLES` explicitly — never remove this if
you're editing the input-deck template, or every analysis will hang.

As defense in depth (in case some other input triggers a similar hang for
a reason we haven't found), the agent also runs `ccx.exe` with an explicit
subprocess timeout rather than trusting the solver choice alone.

## Second gotcha: run eigenvalue analyses single-threaded

With OpenMP threads (`OMP_NUM_THREADS` > 1) this build's `*BUCKLE` and
`*FREQUENCY` eigensolver is **non-deterministic** and intermittently returns
spurious eigenvalues: in v0.14 the very same wing-box buckling deck gave
first load factors of 0.70, 1.01 and 1.72 on consecutive runs. With
`OMP_NUM_THREADS=1` it returned 1.72 every time and the value is
mesh-converged (1.740 / 1.728 / 1.723 / 1.721 on four refinements).
`agents/structures/wing_box_fe.py` therefore forces one thread (the models
are small: a few seconds per solve), and
`tests/structures/test_wing_box_fe.py` checks repeatability.

## Validation

Verified 2026-09-15 against closed-form Euler-Bernoulli cantilever beam
theory: a 1m steel beam (20mm × 10mm rectangular section), fixed at one
end, 100N transverse tip load.

- Analytical tip deflection: `F·L³ / (3·E·I)` = 100 × 1000³ / (3 × 210000 ×
  1666.67) ≈ **95.24 mm**
- CalculiX (B31 Timoshenko beam elements, 10-element mesh): **94.95 mm**
- Difference: ~0.3%, consistent with B31 including shear deformation
  (Timoshenko theory) which pure Euler-Bernoulli neglects — not
  discretization error.

Bending stress was also cross-checked qualitatively (right order of
magnitude, correct sign pattern, decreasing from the fixed end toward the
tip as expected) but not asserted to a tight tolerance in tests: B31's
stress output is reported at internal Gauss integration points, not the
exact extreme fiber or exact fixed-end location, so an exact analytical
match requires knowing the element's precise integration scheme, which
wasn't pinned down further. Deflection is the primary, robust validation
metric.

## Section axis convention (BEAM SECTION, SECTION=RECT)

For a beam along the global X axis with `n1 = (0.0, 0.0, 1.0)` (the local
1-direction points along global Z):

- First `RECT` parameter = cross-section dimension along local-1 (global Z)
- Second `RECT` parameter = cross-section dimension along local-2 (global Y)

A transverse load in the global Y direction (`*CLOAD ..., 2, ...`) bends
about the Z axis, so the relevant second moment of area uses the **second**
`RECT` parameter as the bending-direction height `h`:
`I = b·h³/12` where `b` = first parameter, `h` = second parameter.
