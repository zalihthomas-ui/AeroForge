"""Shared helpers for extracting CalculiX .inp text blocks from gmsh's raw
Abaqus/.inp export.

Used by both plate_with_hole.py and bracket_mesh.py: gmsh's own .inp writer
also emits shell elements (CPS6) for any 2D physical group, which ccx.exe
rejects in a 3D analysis, so neither module hands gmsh's raw output to
ccx.exe directly — both extract just the *NODE and *ELEMENT, type=C3D10
blocks and build their own deck around them. See plate_with_hole.py's
module docstring for the full gotcha writeup.
"""

from __future__ import annotations


def extract_mesh_blocks(raw_inp_path: str) -> tuple[list[str], list[str]]:
    """Extract the *NODE and *ELEMENT, type=C3D10 blocks from a gmsh-written
    .inp file, as raw text lines ready to paste into a hand-assembled deck."""
    with open(raw_inp_path, encoding="utf-8") as f:
        lines = f.read().splitlines()

    node_lines = _extract_block(lines, lambda line: line.strip() == "*NODE")
    element_lines = _extract_block(
        lines, lambda line: line.strip().upper().startswith("*ELEMENT") and "C3D10" in line.upper()
    )
    return node_lines, element_lines


def _extract_block(lines: list[str], is_header) -> list[str]:
    for i, line in enumerate(lines):
        if is_header(line):
            rows = []
            j = i + 1
            while j < len(lines) and not lines[j].lstrip().startswith("*"):
                rows.append(lines[j])
                j += 1
            return rows
    raise ValueError("Expected block header not found in gmsh's .inp output.")


def format_nset_lines(node_ids: list[int], per_line: int = 8) -> list[str]:
    """Format node IDs as *NSET data lines, chunked to a safe entries-per-line count."""
    return [
        ", ".join(str(n) for n in node_ids[i : i + per_line]) for i in range(0, len(node_ids), per_line)
    ]
