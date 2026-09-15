"""Demonstration of closed-loop wing aerodynamic optimization.

Optimizes angle of attack and evaluates multiple candidate NACA airfoil sections
for maximum lift-to-drag ratio (L/D) on a mission-doc reference wing geometry.

Run from repo root: python examples/wing/optimize.py
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from agents.design import DesignAgent
from engineering.analysis.wing_optimizer import optimize_wing_for_max_l_over_d

REQUIREMENT = (
    "Create a wing with span 1800 mm, root chord 240 mm, tip chord 140 mm, "
    "sweep 12 degrees, dihedral 4 degrees."
)


def main() -> None:
    agent = DesignAgent()
    base_spec = agent.parse(REQUIREMENT)

    print("=" * 70)
    print("AEROFORGE - CLOSED-LOOP WING AERODYNAMIC OPTIMIZATION")
    print("=" * 70)
    print(f"Base Requirement: {REQUIREMENT}")
    print(
        f"Planform:         Span={base_spec.parameters.get('wing_span')} mm, "
        f"Root={base_spec.parameters.get('root_chord')} mm, "
        f"Tip={base_spec.parameters.get('tip_chord')} mm"
    )
    print("Cruise Speed:     25.0 m/s")
    print("Search Bounds:    alpha in [-2.0, 12.0] deg")
    print("-" * 70)
    print("Evaluating candidate airfoils (scipy bounded scalar optimization)...")

    result = optimize_wing_for_max_l_over_d(
        base_spec,
        alpha_bounds_deg=(-2.0, 12.0),
        cruise_velocity_mps=25.0,
    )

    print("\nCandidate Evaluations:")
    print(f"{'Airfoil':<12} {'Opt Alpha (deg)':<18} {'Max L/D':<12} {'CL':<10} {'CD':<10}")
    print("-" * 70)
    for cand in result.all_candidates:
        winner_mark = (
            " <-- BEST" if cand.naca_airfoil == result.optimal_naca_airfoil else ""
        )
        print(
            f"NACA {cand.naca_airfoil:<7} "
            f"{cand.optimal_alpha_deg:<18.2f} "
            f"{cand.max_l_over_d:<12.2f} "
            f"{cand.cl_at_optimum:<10.4f} "
            f"{cand.cd_at_optimum:<10.6f}"
            f"{winner_mark}"
        )

    print("=" * 70)
    print(f"OPTIMAL SECTION:  NACA {result.optimal_naca_airfoil}")
    print(f"OPTIMAL ALPHA:    {result.optimal_alpha_deg:.2f} deg")
    print(f"PEAK L/D RATIO:   {result.max_l_over_d:.2f}")
    print(f"LIFT COEFF (CL):  {result.cl_at_optimum:.4f}")
    print(f"DRAG COEFF (CD):  {result.cd_at_optimum:.6f}")
    print("=" * 70)


if __name__ == "__main__":
    main()
