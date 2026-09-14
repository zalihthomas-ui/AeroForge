# Wing example (v0.2)

Run: `python examples/wing/run.py`

Produces a wing planform STEP/STL/3MF from the mission doc's geometry
example values (span 1800mm, root chord 240mm, tip chord 140mm, sweep
12deg, dihedral 4deg) via the same Design Agent → Geometry Agent loop as
the bracket example.

This is a **flat-plate planform approximation**, not an aerodynamically
real wing — no airfoil section, camber, or twist. The full flagship UAV
wing demonstration (mission doc §20) additionally needs the Aerodynamics,
Structures, Manufacturing, and Optimization agents, which don't exist yet.
