"""Engineering analysis package for AeroForge."""

from engineering.analysis.bracket_optimizer import (
    BracketDesignPoint,
    BracketOptimizationResult,
    BracketOptimizerError,
    calculate_bracket_mass,
    optimize_bracket_thickness_for_min_mass,
)
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
    "BracketDesignPoint",
    "BracketOptimizationResult",
    "BracketOptimizerError",
    "WingAeroError",
    "WingAeroSummary",
    "WingOptimizationResult",
    "calculate_bracket_mass",
    "evaluate_wing_aero",
    "optimize_bracket_thickness_for_min_mass",
    "optimize_wing_for_max_l_over_d",
]
