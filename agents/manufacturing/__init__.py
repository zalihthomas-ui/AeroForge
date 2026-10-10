"""Manufacturing Agent package: CNC checks, sheet nesting, and BOM cost estimation."""

from agents.manufacturing.agent import (
    DEFAULT_MAX_DRILL_RATIO,
    DEFAULT_MIN_EDGE_MARGIN_RATIO,
    CNCManufacturabilityResult,
    ManufacturabilityError,
    ManufacturingAgent,
    WingManufacturingEvaluation,
)
from agents.manufacturing.bom import (
    BOMCostRates,
    BOMItem,
    BillOfMaterials,
    generate_wing_bom,
)
from agents.manufacturing.nesting import (
    NestingPlan,
    PlacedPart,
    SheetNestingResult,
    StockSheetSpec,
    nest_ribs,
)

__all__ = [
    "BOMCostRates",
    "BOMItem",
    "BillOfMaterials",
    "CNCManufacturabilityResult",
    "DEFAULT_MAX_DRILL_RATIO",
    "DEFAULT_MIN_EDGE_MARGIN_RATIO",
    "ManufacturabilityError",
    "ManufacturingAgent",
    "NestingPlan",
    "PlacedPart",
    "SheetNestingResult",
    "StockSheetSpec",
    "WingManufacturingEvaluation",
    "generate_wing_bom",
    "nest_ribs",
]
