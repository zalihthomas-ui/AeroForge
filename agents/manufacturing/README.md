# Manufacturing Agent (v0.9)

`ManufacturingAgent.evaluate_bracket_cnc(length_mm, width_mm, thickness_mm,
hole_diameter_mm, hole_count, ...)` runs two real, sourced CNC
design-for-manufacturability checks on the **actual**
`agents/geometry/bracket.py` component (not a fixture):

- **Drill depth-to-diameter ratio** — `thickness_mm / hole_diameter_mm`
  against a 5:1 standard jobber-length twist drill limit (a widely cited
  CNC design-for-manufacturability rule of thumb, e.g. Protolabs' design
  guides — documented as convention, not asserted as a rigid physical
  standard).
- **Real hole-to-part-edge clearance** — the genuine worst-case minimum
  distance from any hole's edge to the nearest part edge (checked in both
  length and width directions, across every hole — not just the loosest
  number), against a 1x-hole-diameter minimum (Xometry/Protolabs design
  guide convention). On the reference bracket this is 8.5mm at the
  outermost holes' length-direction clearance — genuinely tight against
  the 8mm requirement, not the much looser 36mm a naive width-only check
  would report.

Both thresholds are overridable (`max_drill_ratio`,
`min_edge_margin_ratio`) if a specific shop's capability differs from the
documented convention.

**Additive manufacturing overhang checking was investigated and
deliberately not implemented**: the bracket's planar faces are
geometrically guaranteed zero-overhang in Z-up build orientation (a plain
box — all 6 planar face normals have Z in {0, +1, -1}), so a planar-only
overhang check would always trivially report "fully self-supporting" with
no real manufacturability signal. The bracket's actual overhang risk is
entirely in its cylindrical hole walls, which need point-sampling or
parametric-surface analysis to check properly — explicit future work, not
silently skipped.

Sheet-metal and composite manufacturability checks (mission doc §11) are
not implemented — no sheet-metal or composite component exists yet in
`agents/geometry`.
