"""Manufacturing Agent: CNC manufacturability, sheet nesting, and BOM cost estimation (mission doc Phase 6).

Covers:
1. CNC bracket manufacturability (drill depth-to-diameter ratio, hole-edge clearance).
2. Wing rib flat pattern nesting on stock sheet metal with DXF export, cut length, and laser time estimation.
3. Full wing assembly Bill of Materials (BOM) with raw stock sizing, material and machine cost estimation,
   and mass reconciliation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agents.geometry.bracket import hole_center_x_positions
from agents.geometry.validation import GeometryValidationError, validate_bracket_parameters
from agents.manufacturing.bom import (
    BOMCostRates,
    BillOfMaterials,
    generate_wing_bom,
)
from agents.manufacturing.nesting import (
    NestingPlan,
    StockSheetSpec,
    nest_ribs,
)

if TYPE_CHECKING:
    from agents.geometry.wing_structure import WingStructure, WingStructureSpec
    from build123d import Face

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


@dataclass
class WingManufacturingEvaluation:
    """Consolidated manufacturing evaluation for a wing structure."""

    nesting_plan: NestingPlan
    bom: BillOfMaterials


class ManufacturingAgent:
    """Evaluates manufacturability, sheet nesting, and cost for engineered components."""

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
        """Evaluate CNC manufacturability of a bracket with these parameters."""
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
        """Worst-case clearance from any hole edge to nearest part edge."""
        hole_radius = hole_diameter_mm / 2
        width_margin = width_mm / 2 - hole_radius

        margins = [width_margin]
        for x_center in hole_center_x_positions(length_mm, hole_count):
            distance_to_nearest_length_edge = length_mm / 2 - abs(x_center)
            margins.append(distance_to_nearest_length_edge - hole_radius)

        return min(margins)

    def nest_wing_ribs(
        self,
        rib_patterns_or_spec: dict[str, Face] | WingStructureSpec,
        stock: StockSheetSpec = StockSheetSpec(),
        feed_rate_mm_min: float = 3000.0,
        both_wings: bool = True,
    ) -> NestingPlan:
        """Nest rib flat patterns onto stock sheets."""
        return nest_ribs(
            rib_patterns_or_spec,
            stock=stock,
            feed_rate_mm_min=feed_rate_mm_min,
            both_wings=both_wings,
        )

    def generate_wing_bom(
        self,
        structure_or_spec: WingStructure | WingStructureSpec,
        nesting_plan: NestingPlan | None = None,
        rates: BOMCostRates = BOMCostRates(),
    ) -> BillOfMaterials:
        """Generate full Bill of Materials and manufacturing cost rollups."""
        return generate_wing_bom(
            structure_or_spec,
            nesting_plan=nesting_plan,
            rates=rates,
        )

    def evaluate_wing_manufacturing(
        self,
        structure_or_spec: WingStructure | WingStructureSpec,
        stock: StockSheetSpec = StockSheetSpec(),
        rates: BOMCostRates = BOMCostRates(),
    ) -> WingManufacturingEvaluation:
        """Full manufacturing pipeline: rib nesting + BOM cost estimation."""
        nesting = self.nest_wing_ribs(
            structure_or_spec if hasattr(structure_or_spec, "chord") else structure_or_spec.spec,  # type: ignore[union-attr]
            stock=stock,
            feed_rate_mm_min=rates.laser_feed_rate_mm_min,
            both_wings=True,
        )
        bom = self.generate_wing_bom(
            structure_or_spec,
            nesting_plan=nesting,
            rates=rates,
        )
        return WingManufacturingEvaluation(nesting_plan=nesting, bom=bom)
