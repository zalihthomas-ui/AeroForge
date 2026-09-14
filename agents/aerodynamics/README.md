# Aerodynamics Agent (v0.4)

`AerodynamicsAgent.evaluate_naca_airfoil(designation, alpha_deg, reynolds)`
evaluates a NACA airfoil section via **NeuralFoil**, a published,
XFOIL/experiment-validated neural surrogate — see `agent.py`'s module
docstring for the full disclaimer.

**This is not real XFOIL, OpenFOAM, or SU2.** Those were evaluated first;
XFOIL's PyPI build fails on this machine's toolchain (CMake/MinGW
configure error) and WSL isn't installed. See
`docs/architecture/roadmap.md`'s v0.4 section for the full decision
record. Swapping in a first-principles solver is future work.

Not yet wired into the CAD loop — the wing geometry (`agents/geometry/wing.py`)
has no airfoil section yet (flat-plate approximation).

See `examples/airfoil/run.py` for a runnable NACA 0012 demonstration.
