"""Manufacturing demonstration: Wing rib sheet nesting, DXF generation, and BOM cost estimation.

Demonstrates:
1. Sizing the real designed campaign wing via `engineering.analysis.wing_campaign.run_campaign`.
2. Extracting rib flat patterns (2D cutting profiles with lightening holes, 14 ribs total for 6-bay wing).
3. Deterministic 2D sheet nesting onto stock aluminium sheet (1000 x 500 x 1 mm, 5 mm clearance).
4. Multi-sheet DXF profile export for CNC laser/water-jet cutters.
5. Full wing assembly Bill of Materials (BOM) with 68 parts, raw stock mass, machining cycle times, and cost estimation.
6. Export of BOM to CSV and visual CAD rendering of the nested sheet layout to PNG.

Run from repo root:
    python examples/wing/manufacturing.py
"""

from __future__ import annotations

import os
import sys

import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from agents.geometry.wing_structure import rib_flat_patterns  # noqa: E402
from agents.manufacturing import (  # noqa: E402
    BOMCostRates,
    ManufacturingAgent,
    StockSheetSpec,
    generate_wing_bom,
    nest_ribs,
)
from engineering.analysis.wing_campaign import (  # noqa: E402
    CampaignRequirement,
    build_structure_cad,
    run_campaign,
)

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")


def render_nesting_layout_image(plan, output_path: str) -> None:
    """Render a visual CAD-style plot of the nested sheet layout to PNG."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    fig, ax = plt.subplots(figsize=(14, 8), dpi=200, facecolor="#0f172a")
    ax.set_facecolor("#1e293b")

    sheet = plan.sheets[0]
    stock = sheet.sheet_spec

    # Draw stock sheet boundary
    sheet_rect = Rectangle(
        (0, 0),
        stock.width_mm,
        stock.height_mm,
        fill=True,
        facecolor="#1e293b",
        edgecolor="#38bdf8",
        linewidth=2.0,
        linestyle="-",
        label=f"Stock Sheet ({stock.width_mm:.0f} x {stock.height_mm:.0f} mm)",
    )
    ax.add_patch(sheet_rect)

    # Draw usable boundary (margin)
    margin_rect = Rectangle(
        (stock.margin_mm, stock.margin_mm),
        stock.width_mm - 2 * stock.margin_mm,
        stock.height_mm - 2 * stock.margin_mm,
        fill=False,
        edgecolor="#64748b",
        linewidth=1.0,
        linestyle="--",
        label=f"Usable Margin ({stock.margin_mm:.0f} mm)",
    )
    ax.add_patch(margin_rect)

    # Palette for parts
    colors = [
        "#38bdf8", "#4ade80", "#fbbf24", "#f472b6", "#a78bfa",
        "#2dd4bf", "#f87171", "#c084fc", "#fb923c", "#34d399",
        "#e879f9", "#38bdf8", "#facc15", "#4ade80",
    ]

    for i, p in enumerate(sheet.placements):
        color = colors[i % len(colors)]

        # Draw bounding box
        bbox_rect = Rectangle(
            (p.x_mm, p.y_mm),
            p.width_mm,
            p.height_mm,
            fill=True,
            facecolor=color,
            alpha=0.15,
            edgecolor=color,
            linewidth=1.0,
            linestyle=":",
        )
        ax.add_patch(bbox_rect)

        # Plot all wires smoothly by sampling edges
        for wire in p.face.wires():
            for edge in wire.edges():
                samples = 50 if len(wire.edges()) == 1 else 10
                t_vals = np.linspace(0.0, 1.0, samples)
                edge_pts = np.array([[float(p_vec.X), float(p_vec.Y)] for p_vec in (edge.position_at(t) for t in t_vals)])
                ax.plot(edge_pts[:, 0], edge_pts[:, 1], color=color, linewidth=1.5)

        # Part label and dimensions
        cx = p.x_mm + p.width_mm / 2.0
        cy = p.y_mm + p.height_mm / 2.0
        ax.text(
            cx,
            cy,
            f"{p.part_id}\n{p.width_mm:.0f}x{p.height_mm:.0f} mm",
            color="#f8fafc",
            fontsize=7,
            fontweight="bold",
            ha="center",
            va="center",
            bbox=dict(boxstyle="round,pad=0.2", facecolor="#0f172a", edgecolor=color, alpha=0.85, lw=1),
        )

    ax.set_xlim(-20, stock.width_mm + 20)
    ax.set_ylim(-20, stock.height_mm + 40)
    ax.set_aspect("equal")

    ax.set_title(
        f"AeroForge: 2D Wing Rib Nesting Layout (Sheet 1/{plan.total_sheet_count})\n"
        f"Designed Wing: NACA {sheet.placements[0].face.bounding_box().size.X:.0f}mm chord | "
        f"Stock: {stock.width_mm:.0f} x {stock.height_mm:.0f} x {stock.thickness_mm:.1f} mm {stock.material} | "
        f"Parts: {plan.total_parts_nested} | Utilisation: {plan.overall_utilisation_percent:.1f}% | "
        f"Cut Length: {plan.total_cut_length_mm:.1f} mm | Laser Time: {plan.total_laser_cut_time_s:.1f} s",
        color="#f8fafc",
        fontsize=11,
        fontweight="bold",
        pad=15,
    )
    ax.set_xlabel("Sheet X (mm)", color="#94a3b8", fontsize=10)
    ax.set_ylabel("Sheet Y (mm)", color="#94a3b8", fontsize=10)
    ax.tick_params(colors="#94a3b8")
    for spine in ax.spines.values():
        spine.set_color("#475569")
    ax.grid(True, linestyle="--", alpha=0.2, color="#94a3b8")
    ax.legend(loc="upper right", facecolor="#0f172a", edgecolor="#475569", labelcolor="#f8fafc", fontsize=8)

    plt.tight_layout()
    plt.savefig(output_path, dpi=200, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)


def main() -> None:
    print("=" * 80)
    print("AEROFORGE MANUFACTURING: WING RIB NESTING & BOM COST ESTIMATION")
    print("=" * 80)

    # 1. Run campaign sizing to get the real designed wing structure
    print("\n[1] Running Wing Sizing Campaign (Lifting-Line Aero + Load Envelope + Wing Box Sizing)...")
    campaign_res = run_campaign(CampaignRequirement(), run_fe=False)
    structure = build_structure_cad(campaign_res)
    spec = structure.spec

    print(f"  - Semispan:          {spec.semispan_mm:.1f} mm (Full span: {2*spec.semispan_mm:.1f} mm)")
    print(f"  - Root / Tip Chord:  {spec.root_chord_mm:.1f} mm / {spec.tip_chord_mm:.1f} mm")
    print(f"  - Airfoil Section:   NACA {spec.naca}")
    print(f"  - Bay Stations:      {spec.bay_edges_mm} mm ({len(spec.bay_edges_mm)-1} bays, {len(spec.bay_edges_mm)} rib stations)")
    print(f"  - Sized Box Mass:    {campaign_res.sizing.mass_kg:.3f} kg (FE box model)")
    print(f"  - Total Solid CAD:   {sum(structure.masses_kg().values()):.3f} kg (all 68 assembly solids)")

    # 2. Extract 2D cutting flat patterns
    print("\n[2] Extracting Rib Flat Patterns (2D profiles + lightening holes)...")
    ribs = rib_flat_patterns(spec)
    for name, face in ribs.items():
        bb = face.bounding_box()
        wires = face.wires()
        perim = sum(float(w.length) for w in wires)
        print(f"  - {name:<6}: Area = {face.area:>7.1f} mm2, BBox = ({bb.size.X:>5.1f} x {bb.size.Y:>4.1f}) mm, Wires = {len(wires)}, Cut Perim = {perim:>6.1f} mm")

    # 3. Perform 2D sheet nesting
    stock = StockSheetSpec(
        width_mm=1000.0,
        height_mm=500.0,
        thickness_mm=1.0,
        margin_mm=5.0,
        spacing_mm=5.0,
        material="Aluminium 6061-T6",
        density_kg_m3=2700.0,
    )
    print(f"\n[3] Nesting Ribs onto Stock Sheet ({stock.width_mm:.0f} x {stock.height_mm:.0f} x {stock.thickness_mm:.1f} mm {stock.material})...")
    agent = ManufacturingAgent()
    eval_res = agent.evaluate_wing_manufacturing(structure, stock=stock)
    nesting_plan = eval_res.nesting_plan

    print(f"  - Total Sheets Required: {nesting_plan.total_sheet_count}")
    print(f"  - Total Nested Parts:    {nesting_plan.total_parts_nested} (7 Stbd + 7 Port ribs)")
    print(f"  - Net Part Area:         {nesting_plan.total_part_area_mm2:.1f} mm2")
    print(f"  - Stock Sheet Area:      {nesting_plan.total_stock_area_mm2:.1f} mm2")
    print(f"  - Material Utilisation:  {nesting_plan.overall_utilisation_percent:.2f}%")
    print(f"  - Total Cut Length:      {nesting_plan.total_cut_length_mm:.1f} mm ({nesting_plan.total_cut_length_mm/1000.0:.2f} m)")
    print(f"  - Laser Cutting Time:    {nesting_plan.total_laser_cut_time_s:.1f} s ({nesting_plan.total_laser_cut_time_s/60.0:.2f} min @ {nesting_plan.feed_rate_mm_min:.0f} mm/min)")

    # 4. Export DXFs
    dxf_dir = os.path.join(OUTPUT_DIR, "dxf")
    dxf_paths = nesting_plan.export_dxfs(dxf_dir)
    print(f"\n[4] Exported {len(dxf_paths)} DXF cutting files:")
    for p in dxf_paths:
        print(f"  - DXF: {p} ({os.path.getsize(p)/1024.0:.1f} KB)")

    # 5. Render Nesting Layout Image
    img_path = os.path.join(OUTPUT_DIR, "rib_nesting_layout.png")
    render_nesting_layout_image(nesting_plan, img_path)
    print(f"\n[5] Saved Nesting Visualization Image:\n  - Image: {img_path} ({os.path.getsize(img_path)/1024.0:.1f} KB)")

    # 6. Generate and Display Bill of Materials
    bom = eval_res.bom
    csv_path = os.path.join(OUTPUT_DIR, "wing_bom.csv")
    bom.to_csv(csv_path)

    print("\n[6] Bill of Materials (BOM) & Manufacturing Cost Rollup:")
    print(bom.summary_table())
    print(f"\n  - Saved BOM CSV: {csv_path} ({len(bom.items)} items)")

    # 7. Mass Reconciliation
    expected_mass = sum(structure.masses_kg().values())
    diff_kg = abs(bom.total_part_mass_kg - expected_mass)
    print("\n[7] Mass Reconciliation Verification:")
    print(f"  - BOM Total Part Mass:        {bom.total_part_mass_kg:.5f} kg")
    print(f"  - WingStructure Solid Mass:   {expected_mass:.5f} kg")
    print(f"  - Discrepancy:                {diff_kg:.6e} kg ({diff_kg/expected_mass * 100:.4f}%)")
    print(f"  - Reconciliation Status:      {'PASSED (< 0.1%)' if diff_kg/expected_mass < 0.001 else 'FAILED'}")
    print("=" * 80)


if __name__ == "__main__":
    main()
