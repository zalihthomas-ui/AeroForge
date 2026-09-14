# Wing example (v0.2, airfoil section added in v0.5)

Run: `python examples/wing/run.py`

Produces a wing planform STEP/STL/3MF from the mission doc's geometry
example values (span 1800mm, root chord 240mm, tip chord 140mm, sweep
12deg, dihedral 4deg) via the same Design Agent → Geometry Agent loop as
the bracket example.

As of v0.5 this uses a **real NACA airfoil cross-section** (NACA 0012 by
default; mention e.g. "NACA 2412 airfoil" in the requirement text for a
cambered section) instead of a flat plate — see
`docs/architecture/roadmap.md`'s v0.5 section. Still no twist/washout, and
the shape isn't yet coupled to the Aerodynamics Agent's own evaluation
(same coordinate source, but nothing feeds one into the other). The full
flagship UAV wing demonstration (mission doc §20) additionally needs the
Manufacturing and Optimization agents, and real 3D-solid meshing for
structural analysis, none of which exist yet.
