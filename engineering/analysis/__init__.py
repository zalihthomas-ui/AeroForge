"""Engineering analysis package for AeroForge."""

from engineering.analysis.wing_aero import (
    WingAeroError,
    WingAeroSummary,
    evaluate_wing_aero,
)
from engineering.analysis.wing_optimizer import (
    AirfoilCandidateResult,
    WingOptimizationResult,
    optimize_wing_for_max_l_over_d,
)

__all__ = [
    "AirfoilCandidateResult",
    "WingAeroError",
    "WingAeroSummary",
    "WingOptimizationResult",
    "evaluate_wing_aero",
    "optimize_wing_for_max_l_over_d",
]
