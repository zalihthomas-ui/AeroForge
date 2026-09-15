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
from engineering.analysis.bracket_optimizer_2d import (
    BracketDesignPoint2D,
    BracketOptimization2DResult,
    BracketOptimizer2DError,
    optimize_bracket_thickness_and_hole_for_min_mass,
)
from engineering.analysis.wing_aero import (
    WingAeroError,
    WingAeroSummary,
    evaluate_wing_aero,
)
from engineering.analysis.wing_flagship import (
    FlagshipDesignResult,
    WingDesignRequirement,
    WingFlagshipError,
    evaluate_wing_design,
    find_passing_wing_design,
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
    "BracketDesignPoint2D",
    "BracketMaterializerError",
    "BracketOptimization2DResult",
    "BracketOptimizationResult",
    "BracketOptimizer2DError",
    "BracketOptimizerError",
    "FlagshipDesignResult",
    "MaterializedBracketResult",
    "MaterializedWingResult",
    "WingAeroError",
    "WingAeroSummary",
    "WingDesignRequirement",
    "WingFlagshipError",
    "WingMaterializerError",
    "WingOptimizationResult",
    "calculate_bracket_mass",
    "evaluate_wing_aero",
    "evaluate_wing_design",
    "find_passing_wing_design",
    "materialize_optimal_bracket",
    "materialize_optimal_wing",
    "optimize_bracket_thickness_and_hole_for_min_mass",
    "optimize_bracket_thickness_for_min_mass",
    "optimize_wing_for_max_l_over_d",
]
