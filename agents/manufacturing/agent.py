"""Manufacturing Agent: CNC manufacturability checks (mission doc Phase 6).

First version. Applied to the actual Geometry Agent bracket component
(agents/geometry/bracket.py's `build_bracket`, via its `hole_center_x_positions`
helper — not a dedicated fixture), the same "check the real component, not
a stand-in" discipline as the Structures Agent's evaluate_bracket. Every
numeric threshold below is a real, documented machining convention, not an
invented scoring heuristic with no ground truth.

## Drill depth-to-diameter ratio

Standard jobber-length twist drills (HSS or carbide) are commonly limited
to roughly 5:1 depth-to-diameter for a single accurate pass — beyond that,
drill wander and breakage risk increases enough that shops typically
require peck-drilling cycles or dedicated deep-hole drilling tooling
(gun drills, etc.), which cost more and take longer. ~5:1 is a widely
cited CNC design-for-manufacturability rule of thumb (e.g. Protolabs' and
similar CNC machining design guides use this figure), not a rigid
physical/ISO standard — documented here rather than asserted blindly, and
easy to override (`max_standard_drill_ratio`) if a shop's own capability
differs. For the bracket, "depth" is thickness_mm: each hole is a
through-hole drilled along the thickness axis.

## Minimum hole-edge distance

A hole drilled too close to the part's outer edge risks breakout (the
drill or endmill exits through the side face instead of cleanly through
the bottom) and leaves too little material around the hole for structural
margin. agents/geometry/validation.py already enforces a geometric-
validity minimum (MIN_EDGE_MARGIN_MM = 2mm) — but that only guarantees
non-degenerate geometry (material exists at all), not that the part is
comfortably manufacturable. This check instead computes the actual
worst-case clearance: the minimum distance from any hole's edge to the
nearest part edge, in either the length or width direction, and compares
it against a commonly cited CNC design-guide minimum of 1x the hole
diameter (e.g. Xometry/Protolabs machining design guides recommend at
least one hole-diameter of clearance from a hole edge to a part edge or
another feature) — a materially different, and typically much tighter,
bar than the geometric-validity check.
"""

from __future__ import annotations

from dataclasses import dataclass

from agents.geometry.bracket import hole_center_x_positions
from agents.geometry.validation import GeometryValidationError, validate_bracket_parameters

# Source: widely used CNC machining design-for-manufacturability guidance
# (e.g. Protolabs' CNC design guide) — a practical single-pass drilling
# limit for standard jobber-length HSS/carbide twist drills before
# peck-drilling or deep-hole drilling techniques become necessary.
DEFAULT_MAX_DRILL_RATIO = 5.0

# Source: commonly cited CNC design-guide minimum (e.g. Xometry/Protolabs
# machining design guides) for clearance from a hole's edge to the
# nearest part edge, to avoid drill/endmill breakout and leave adequate
# surrounding material.
DEFAULT_MIN_EDGE_MARGIN_RATIO = 1.0  # x hole_diameter_mm


class ManufacturabilityError(Exception):
    """Raised when manufacturability evaluation fails due to invalid inputs."""

    pass


@dataclass
class CNCManufacturabilityResult:
    """CNC manufacturability of a bracket: drill depth-to-diameter ratio
    and real hole-to-part-edge clearance, each against a documented
    machining convention (see agent.py's module docstring for sources)."""

    depth_to_diameter_ratio: float
    standard_drillable: bool
    max_standard_ratio: float
    hole_edge_margin_mm: float
    edge_margin_adequate: bool
    overall_manufacturable: bool


class ManufacturingAgent:
    """Evaluates CNC manufacturability of the actual bracket geometry."""

    def evaluate_bracket_cnc(
        self,
        length_mm: float,
        width_mm: float,
        thickness_mm: float,
        hole_diameter_mm: float,
        hole_count: int,
        max_drill_ratio: float = DEFAULT_MAX_DRILL_RATIO,
        min_edge_margin_ratio: float = DEFAULT_MIN_EDGE_MARGIN_RATIO,
    ) -> CNCManufacturabilityResult:
        """Evaluate CNC manufacturability of a bracket with these
        parameters (same as agents/geometry/bracket.py's build_bracket).

        Args:
            length_mm, width_mm, thickness_mm, hole_diameter_mm,
                hole_count: Same parameters and constraints as
                build_bracket (validated with the same
                agents/geometry/validation.validate_bracket_parameters —
                there's no point checking manufacturability of geometry
                that isn't even valid).
            max_drill_ratio: Maximum standard single-pass drill
                depth-to-diameter ratio. Defaults to the documented 5:1
                rule of thumb; override if a specific shop's capability
                differs.
            min_edge_margin_ratio: Minimum required hole-edge-to-part-edge
                clearance, as a multiple of hole_diameter_mm. Defaults to
                the documented 1x rule of thumb.

        Returns:
            CNCManufacturabilityResult with both checks and their
            real underlying numbers (not just pass/fail).

        Raises:
            ManufacturabilityError: If inputs are invalid (wrapping
                agents.geometry.validation.GeometryValidationError, so
                geometrically invalid brackets are rejected the same way
                the Geometry Agent itself would reject them) or hole_count
                is 0 (no holes to drill — nothing to evaluate here).
        """
        try:
            validate_bracket_parameters(length_mm, width_mm, thickness_mm, hole_diameter_mm, hole_count)
        except GeometryValidationError as exc:
            raise ManufacturabilityError(str(exc)) from exc

        hole_count = int(hole_count)
        if hole_count == 0:
            raise ManufacturabilityError(
                "hole_count is 0 — there are no drilled holes for a CNC manufacturability check to evaluate."
            )

        depth_to_diameter_ratio = thickness_mm / hole_diameter_mm
        standard_drillable = depth_to_diameter_ratio <= max_drill_ratio

        hole_edge_margin_mm = self._min_hole_edge_margin_mm(length_mm, width_mm, hole_diameter_mm, hole_count)
        required_margin_mm = min_edge_margin_ratio * hole_diameter_mm
        edge_margin_adequate = hole_edge_margin_mm >= required_margin_mm

        return CNCManufacturabilityResult(
            depth_to_diameter_ratio=depth_to_diameter_ratio,
            standard_drillable=standard_drillable,
            max_standard_ratio=max_drill_ratio,
            hole_edge_margin_mm=hole_edge_margin_mm,
            edge_margin_adequate=edge_margin_adequate,
            overall_manufacturable=standard_drillable and edge_margin_adequate,
        )

    def _min_hole_edge_margin_mm(
        self, length_mm: float, width_mm: float, hole_diameter_mm: float, hole_count: int
    ) -> float:
        """The worst-case (minimum) clearance from any hole's edge to the
        nearest part edge, checking both the length direction (relevant
        for the two outermost holes) and the width direction (the same
        for every hole, since all holes are centered on the width axis)."""
        hole_radius = hole_diameter_mm / 2
        width_margin = width_mm / 2 - hole_radius

        margins = [width_margin]
        for x_center in hole_center_x_positions(length_mm, hole_count):
            distance_to_nearest_length_edge = length_mm / 2 - abs(x_center)
            margins.append(distance_to_nearest_length_edge - hole_radius)

        return min(margins)
