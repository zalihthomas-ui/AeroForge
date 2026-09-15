"""Parser for CalculiX's .frd nodal results file (fixed-width ASCII).

Used to get nodal-averaged (extrapolated from Gauss points and averaged
across all elements sharing a node) field values — e.g. stress — which
`*NODE PRINT`/`*EL PRINT`'s .dat output cannot provide (those give either
DOF values like displacement, or raw per-Gauss-point element values,
never node-averaged element results). Requested via `*NODE FILE` in a
.inp deck (see agents/structures/agent.py's `evaluate_bracket`, which
uses nodal-averaged stress as a first step toward taming its
stress-singularity hot spot).

The .frd format is fixed-column, not whitespace-delimited: a node id in
a 10-character field, followed by each value in its own 12-character
field (e.g. " 1.23456E+02" or "-1.23456E+02" — note two adjacent values
can abut with no separating space when a negative sign takes the place a
positive value's leading space would occupy), so this must slice by
character position rather than split().
"""

from __future__ import annotations

_NODE_ID_WIDTH = 10
_VALUE_WIDTH = 12
_PREFIX_WIDTH = 3  # " -1"


def parse_frd_nodal_block(frd_path: str, block_name: str, num_values: int) -> dict[int, list[float]]:
    """Parse a `-4  <block_name> ...` nodal data block from a .frd file
    into {node_id: [value_1, ..., value_num_values]}."""
    with open(frd_path, encoding="latin-1") as f:
        lines = f.read().splitlines()

    header_index = next(
        (i for i, line in enumerate(lines) if line.strip().startswith("-4") and block_name in line),
        None,
    )
    if header_index is None:
        raise ValueError(f"Block '{block_name}' not found in {frd_path}.")

    i = header_index + 1
    while i < len(lines) and lines[i].strip().startswith("-5"):
        i += 1  # skip per-component header lines (e.g. SXX, SYY, ...)

    rows: dict[int, list[float]] = {}
    while i < len(lines) and lines[i].strip().startswith("-1"):
        line = lines[i]
        node_id = int(line[_PREFIX_WIDTH : _PREFIX_WIDTH + _NODE_ID_WIDTH])
        offset = _PREFIX_WIDTH + _NODE_ID_WIDTH
        values = [
            float(line[offset + _VALUE_WIDTH * k : offset + _VALUE_WIDTH * (k + 1)]) for k in range(num_values)
        ]
        rows[node_id] = values
        i += 1

    if not rows:
        raise ValueError(f"Block '{block_name}' in {frd_path} had no data rows.")
    return rows
