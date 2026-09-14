"""Demonstration of coupled wing geometry and aerodynamic analysis.

Parses a natural language wing requirement, constructs the EngineeringSpec,
and evaluates aerodynamic performance (Reynolds number, CL, CD, L/D, lift, drag)
at nominal UAV cruise conditions (V=25 m/s, alpha=4 deg).

Run from repo root: python examples/wing/aero_summary.py
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from agents.design import DesignAgent
from engineering.analysis.wing_aero import evaluate_wing_aero

REQUIREMENT = (
    "Create a wing with span 1800 mm, root chord 240 mm, tip chord 140 mm, "
    "sweep 12 degrees, dihedral 4 degrees, NACA 2412 airfoil."
)


def main() -> None:
    agent = DesignAgent()
    spec = agent.parse(REQUIREMENT)

    print("=" * 60)
    print("AEROFORGE - WING AERODYNAMIC ANALYSIS SUMMARY")
    print("=" * 60)
    print(f"Requirement:      {REQUIREMENT}")
    print(f"Component:        {spec.component}")
    print(f"Wing Span:        {spec.parameters.get('wing_span')} mm")
    print(f"Root Chord:       {spec.parameters.get('root_chord')} mm")
    print(f"Tip Chord:        {spec.parameters.get('tip_chord')} mm")
    print(f"Sweep:            {spec.parameters.get('sweep')} deg")
    print(f"Dihedral:         {spec.parameters.get('dihedral')} deg")
    print(f"Airfoil Section:  NACA {int(spec.parameters.get('naca_airfoil', 12.0)):04d}")
    print("-" * 60)

    summary = evaluate_wing_aero(
        spec,
        cruise_velocity_mps=25.0,
        alpha_deg=4.0,
    )

    print(f"Backend:          {summary.backend}")
    print(f"Reynolds Number:  {summary.reynolds_number:,.0f}")
    print(f"Lift Coeff (CL):  {summary.cl:.4f}")
    print(f"Drag Coeff (CD):  {summary.cd:.6f}")
    print(f"L/D Ratio:        {summary.l_over_d:.2f}")
    print(f"Total Lift:       {summary.lift_n:.2f} N")
    print(f"Total Drag:       {summary.drag_n:.2f} N")
    print("=" * 60)


if __name__ == "__main__":
    main()
