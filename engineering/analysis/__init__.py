"""Engineering analysis package for AeroForge."""

from engineering.analysis.bracket_materializer import (
    BracketMaterializerError,
    MaterializedBracketResult,
    materialize_optimal_bracket,
)
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
from engineering.analysis.wing_materializer import (
    MaterializedWingResult,
    WingMaterializerError,
    materialize_optimal_wing,
)
from engineering.analysis.wing_optimizer import (
    AirfoilCandidateResult,
    WingOptimizationResult,
    optimize_wing_for_max_l_over_d,
)

__all__ = [
    "AirfoilCandidateResult",
    "BracketDesignPoint",
    "BracketMaterializerError",
    "BracketOptimizationResult",
    "BracketOptimizerError",
    "MaterializedBracketResult",
    "MaterializedWingResult",
    "WingAeroError",
    "WingAeroSummary",
    "WingMaterializerError",
    "WingOptimizationResult",
    "calculate_bracket_mass",
    "evaluate_wing_aero",
    "materialize_optimal_bracket",
    "materialize_optimal_wing",
    "optimize_bracket_thickness_for_min_mass",
    "optimize_wing_for_max_l_over_d",
]
