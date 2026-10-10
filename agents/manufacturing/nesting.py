"""Rib nesting on stock sheet metal (mission doc Phase 6).

Deterministic 2D nesting of wing rib flat cutting patterns onto stock aluminium
sheet (default 1000 x 500 mm, 1 mm thickness, 5 mm part spacing and edge margin).

Calculates:
- Sheet count and per-sheet / overall material utilisation %
- Part placements (x, y, rotation, width, height, bounding box)
- Total cut length (outer boundary + internal lightening hole perimeters)
- Laser cutting time at configurable feed rate (default 3000 mm/min = 50 mm/s)
- DXF export per sheet via cad.exporters / ExportDXF
"""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from build123d import Axis, Compound, ExportDXF, Face, Unit

if TYPE_CHECKING:
    from agents.geometry.wing_structure import WingStructureSpec


@dataclass
class StockSheetSpec:
    """Stock sheet dimensions and nesting clearance constraints."""

    width_mm: float = 1000.0
    height_mm: float = 500.0
    thickness_mm: float = 1.0
    margin_mm: float = 5.0
    spacing_mm: float = 5.0
    material: str = "Aluminium 6061-T6"
    density_kg_m3: float = 2700.0

    @property
    def area_mm2(self) -> float:
        return self.width_mm * self.height_mm

    @property
    def mass_kg(self) -> float:
        return self.area_mm2 * self.thickness_mm * 1e-9 * self.density_kg_m3


@dataclass
class PlacedPart:
    """A nested part placed on a specific sheet."""

    part_id: str
    rib_name: str
    wing_half: str  # "Stbd" or "Port"
    sheet_index: int
    x_mm: float
    y_mm: float
    rotation_deg: float  # 0.0 or 180.0
    width_mm: float
    height_mm: float
    face: Face
    cut_length_mm: float
    area_mm2: float

    @property
    def bounding_box_area_mm2(self) -> float:
        return self.width_mm * self.height_mm


@dataclass
class SheetNestingResult:
    """Nesting layout and metrics for one stock sheet."""

    sheet_index: int
    placements: list[PlacedPart]
    sheet_spec: StockSheetSpec

    @property
    def used_part_area_mm2(self) -> float:
        return sum(p.area_mm2 for p in self.placements)

    @property
    def sheet_area_mm2(self) -> float:
        return self.sheet_spec.area_mm2

    @property
    def utilisation_percent(self) -> float:
        if self.sheet_area_mm2 <= 0:
            return 0.0
        return (self.used_part_area_mm2 / self.sheet_area_mm2) * 100.0

    @property
    def bounding_box_utilisation_percent(self) -> float:
        if self.sheet_area_mm2 <= 0:
            return 0.0
        return (sum(p.bounding_box_area_mm2 for p in self.placements) / self.sheet_area_mm2) * 100.0

    @property
    def total_cut_length_mm(self) -> float:
        return sum(p.cut_length_mm for p in self.placements)

    def laser_cut_time_s(self, feed_rate_mm_min: float = 3000.0) -> float:
        if feed_rate_mm_min <= 0:
            return 0.0
        feed_mm_s = feed_rate_mm_min / 60.0
        return self.total_cut_length_mm / feed_mm_s

    @property
    def compound(self) -> Compound:
        return Compound(children=[p.face for p in self.placements])

    def export_dxf(self, path: str) -> None:
        """Export all nested part profiles on this sheet to a DXF file."""
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        dxf = ExportDXF(unit=Unit.MM)
        dxf.add_shape(self.compound)
        dxf.write(path)


@dataclass
class NestingPlan:
    """Complete multi-sheet nesting plan for wing rib manufacturing."""

    sheets: list[SheetNestingResult]
    feed_rate_mm_min: float = 3000.0

    @property
    def total_parts_nested(self) -> int:
        return sum(len(s.placements) for s in self.sheets)

    @property
    def total_sheet_count(self) -> int:
        return len(self.sheets)

    @property
    def total_part_area_mm2(self) -> float:
        return sum(s.used_part_area_mm2 for s in self.sheets)

    @property
    def total_stock_area_mm2(self) -> float:
        return sum(s.sheet_area_mm2 for s in self.sheets)

    @property
    def overall_utilisation_percent(self) -> float:
        if self.total_stock_area_mm2 <= 0:
            return 0.0
        return (self.total_part_area_mm2 / self.total_stock_area_mm2) * 100.0

    @property
    def total_cut_length_mm(self) -> float:
        return sum(s.total_cut_length_mm for s in self.sheets)

    @property
    def total_laser_cut_time_s(self) -> float:
        if self.feed_rate_mm_min <= 0:
            return 0.0
        feed_mm_s = self.feed_rate_mm_min / 60.0
        return self.total_cut_length_mm / feed_mm_s

    def export_dxfs(self, directory: str, prefix: str = "rib_sheet_") -> list[str]:
        """Export DXF files for all sheets in the plan."""
        os.makedirs(directory, exist_ok=True)
        paths = []
        for i, sheet in enumerate(self.sheets):
            path = os.path.join(directory, f"{prefix}{i + 1}.dxf")
            sheet.export_dxf(path)
            paths.append(path)
        return paths


def _face_cut_length(face: Face) -> float:
    """Sum of outer perimeter and all inner lightening hole perimeters in mm."""
    return sum(float(w.length) for w in face.wires())


def nest_ribs(
    rib_patterns: dict[str, Face] | WingStructureSpec,
    stock: StockSheetSpec = StockSheetSpec(),
    feed_rate_mm_min: float = 3000.0,
    both_wings: bool = True,
) -> NestingPlan:
    """Nest rib flat patterns onto stock sheets using deterministic 2D shelf/bottom-left packing.

    Args:
        rib_patterns: Dictionary mapping rib name (e.g. 'Rib_1') to 2D Face,
            or a WingStructureSpec from which rib flat patterns will be extracted.
        stock: StockSheetSpec defining sheet dimensions, margins, and part spacing.
        feed_rate_mm_min: Laser cutter feed rate in mm/min (default 3000 mm/min = 50 mm/s).
        both_wings: If True, nests 2 of each rib (Port and Stbd halves of full wing).

    Returns:
        NestingPlan containing sheet allocations, part placements, utilisation, and cut metrics.
    """
    if not isinstance(rib_patterns, dict):
        from agents.geometry.wing_structure import rib_flat_patterns

        rib_patterns = rib_flat_patterns(rib_patterns)

    # Prepare list of items to place
    items_to_nest: list[tuple[str, str, Face]] = []
    halves = [("Stbd", "Stbd"), ("Port", "Port")] if both_wings else [("Stbd", "Stbd")]
    for rib_name, face in rib_patterns.items():
        for half_code, half_label in halves:
            part_id = f"{rib_name}_{half_label}"
            items_to_nest.append((part_id, rib_name, face))

    # Sort items by chordwise length / area descending for optimal packing
    def _sort_key(item: tuple[str, str, Face]) -> float:
        bb = item[2].bounding_box()
        return float(bb.size.X * bb.size.Y)

    items_to_nest.sort(key=_sort_key, reverse=True)

    # Sheets tracking: each sheet stores list of PlacedPart and occupied bounding boxes (x0, y0, x1, y1)
    sheets_placements: list[list[PlacedPart]] = []
    sheets_occupied_boxes: list[list[tuple[float, float, float, float]]] = []

    usable_w = stock.width_mm - stock.margin_mm
    usable_h = stock.height_mm - stock.margin_mm
    sp = stock.spacing_mm
    mg = stock.margin_mm

    for part_id, rib_name, original_face in items_to_nest:
        # Precompute geometry for 0 deg and 180 deg
        orientations: list[tuple[float, Face, float, float]] = []
        for rot in (0.0, 180.0):
            if rot == 0.0:
                f_rot = original_face
            else:
                f_rot = original_face.rotate(Axis.Z, 180.0)
            bb = f_rot.bounding_box()
            orientations.append((rot, f_rot, float(bb.size.X), float(bb.size.Y)))

        placed = False
        # Try to place on existing sheets first
        for sheet_idx in range(len(sheets_placements)):
            occupied = sheets_occupied_boxes[sheet_idx]
            candidate_positions: list[tuple[float, float, float, Face, float, float]] = []

            # Test baseline bottom-left corner
            candidate_coords: list[tuple[float, float]] = [(mg, mg)]
            # Candidate points derived from corners of already placed parts + spacing
            for ox0, oy0, ox1, oy1 in occupied:
                candidate_coords.append((ox1 + sp, oy0))
                candidate_coords.append((ox0, oy1 + sp))
                candidate_coords.append((ox1 + sp, mg))
                candidate_coords.append((mg, oy1 + sp))

            for rot, f_rot, pw, ph in orientations:
                if pw > (usable_w - mg) or ph > (usable_h - mg):
                    continue  # Part exceeds raw sheet capacity in this orientation
                for cx, cy in candidate_coords:
                    if cx + pw > usable_w or cy + ph > usable_h:
                        continue
                    # Check overlap with existing placed boxes
                    box_overlaps = False
                    for ox0, oy0, ox1, oy1 in occupied:
                        if not (cx + pw + sp <= ox0 or cx >= ox1 + sp or cy + ph + sp <= oy0 or cy >= oy1 + sp):
                            box_overlaps = True
                            break
                    if not box_overlaps:
                        candidate_positions.append((cy, cx, rot, f_rot, pw, ph))

            if candidate_positions:
                # Select best candidate by lowest Y, then lowest X (bottom-left criterion)
                candidate_positions.sort(key=lambda item: (item[0], item[1]))
                best_y, best_x, best_rot, best_f, best_w, best_h = candidate_positions[0]

                # Translate face to destination
                bb_rot = best_f.bounding_box()
                dx = best_x - float(bb_rot.min.X)
                dy = best_y - float(bb_rot.min.Y)
                placed_face = best_f.translate((dx, dy, 0.0))

                placed_part = PlacedPart(
                    part_id=part_id,
                    rib_name=rib_name,
                    wing_half="Port" if "Port" in part_id else "Stbd",
                    sheet_index=sheet_idx,
                    x_mm=best_x,
                    y_mm=best_y,
                    rotation_deg=best_rot,
                    width_mm=best_w,
                    height_mm=best_h,
                    face=placed_face,
                    cut_length_mm=_face_cut_length(placed_face),
                    area_mm2=abs(float(placed_face.area)),
                )
                sheets_placements[sheet_idx].append(placed_part)
                sheets_occupied_boxes[sheet_idx].append((best_x, best_y, best_x + best_w, best_y + best_h))
                placed = True
                break

        if not placed:
            # Open a new sheet
            sheet_idx = len(sheets_placements)
            sheets_placements.append([])
            sheets_occupied_boxes.append([])

            best_rot, best_f, best_w, best_h = orientations[0]
            if best_w > (usable_w - mg) or best_h > (usable_h - mg):
                # Try 180 or raise error if single part exceeds sheet dimensions
                best_rot, best_f, best_w, best_h = orientations[1]
                if best_w > (usable_w - mg) or best_h > (usable_h - mg):
                    raise ValueError(
                        f"Part {part_id} with dimensions ({best_w:.1f} x {best_h:.1f}) mm exceeds stock sheet "
                        f"usable dimensions ({usable_w - mg:.1f} x {usable_h - mg:.1f}) mm."
                    )

            best_x, best_y = mg, mg
            bb_rot = best_f.bounding_box()
            dx = best_x - float(bb_rot.min.X)
            dy = best_y - float(bb_rot.min.Y)
            placed_face = best_f.translate((dx, dy, 0.0))

            placed_part = PlacedPart(
                part_id=part_id,
                rib_name=rib_name,
                wing_half="Port" if "Port" in part_id else "Stbd",
                sheet_index=sheet_idx,
                x_mm=best_x,
                y_mm=best_y,
                rotation_deg=best_rot,
                width_mm=best_w,
                height_mm=best_h,
                face=placed_face,
                cut_length_mm=_face_cut_length(placed_face),
                area_mm2=abs(float(placed_face.area)),
            )
            sheets_placements[sheet_idx].append(placed_part)
            sheets_occupied_boxes[sheet_idx].append((best_x, best_y, best_x + best_w, best_y + best_h))

    # Construct SheetNestingResult objects
    sheet_results = [
        SheetNestingResult(
            sheet_index=i,
            placements=placements,
            sheet_spec=stock,
        )
        for i, placements in enumerate(sheets_placements)
    ]

    return NestingPlan(sheets=sheet_results, feed_rate_mm_min=feed_rate_mm_min)


__all__ = [
    "NestingPlan",
    "PlacedPart",
    "SheetNestingResult",
    "StockSheetSpec",
    "nest_ribs",
]
