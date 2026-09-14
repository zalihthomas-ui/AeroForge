"""Geometry Agent: turns a validated EngineeringSpec into build123d geometry."""

from .agent import GeometryAgent
from .validation import GeometryValidationError

__all__ = ["GeometryAgent", "GeometryValidationError"]
