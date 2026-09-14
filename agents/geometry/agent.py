"""Geometry Agent: EngineeringSpec -> build123d Part.

Consumes the shared EngineeringSpec contract produced by the Design Agent
(see engineering/requirements/schema.py) and produces validated parametric
geometry. Out of scope for v0.1: any component other than "bracket".
"""

from __future__ import annotations

from typing import Callable

from build123d import Part

from engineering.requirements.schema import EngineeringSpec

from .bracket import build_bracket
from .validation import GeometryValidationError

_BUILDERS: dict[str, Callable[[dict[str, float]], Part]] = {
    "bracket": build_bracket,
}


class GeometryAgent:
    """Converts an EngineeringSpec into a validated build123d Part."""

    def generate(self, spec: EngineeringSpec) -> Part:
        try:
            builder = _BUILDERS[spec.component]
        except KeyError as exc:
            raise GeometryValidationError(
                f"Geometry Agent has no builder for component '{spec.component}'. "
                f"Supported components: {sorted(_BUILDERS)}."
            ) from exc

        return builder(spec.parameters)
