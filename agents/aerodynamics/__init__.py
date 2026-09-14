"""Aerodynamics Agent package."""

from agents.aerodynamics.agent import (
    XFOIL_AVAILABLE,
    AeroResult,
    AerodynamicsAgent,
    AerodynamicsEvaluationError,
)

__all__ = [
    "AeroResult",
    "AerodynamicsAgent",
    "AerodynamicsEvaluationError",
    "XFOIL_AVAILABLE",
]
