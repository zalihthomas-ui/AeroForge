"""Shared contract between the Design Agent and the Geometry Agent.

The Design Agent (agents/design) produces an EngineeringSpec.
The Geometry Agent (agents/geometry) consumes an EngineeringSpec.

Keeping this schema in `engineering/` (rather than inside either agent)
means neither agent owns the other's input/output format.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Requirement(BaseModel):
    """A single named engineering requirement, e.g. cruise velocity."""

    name: str
    value: float | str
    unit: str | None = None


class Constraint(BaseModel):
    """A bound on a design variable, e.g. span <= 2 m."""

    name: str
    operator: str  # one of: "<=", ">=", "==", "<", ">"
    value: float


class Objective(BaseModel):
    """An optimization objective, e.g. minimize weight."""

    name: str
    direction: str  # "minimize" | "maximize"


class EngineeringSpec(BaseModel):
    """Structured output of the Design Agent / input to the Geometry Agent."""

    component: str  # e.g. "bracket", "wing"
    requirements: list[Requirement] = Field(default_factory=list)
    constraints: list[Constraint] = Field(default_factory=list)
    objectives: list[Objective] = Field(default_factory=list)
    parameters: dict[str, float] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
