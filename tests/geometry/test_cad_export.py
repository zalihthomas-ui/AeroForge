"""CAD export quality: named/coloured STEP assemblies, per-part STEP files, DXF rib flat patterns."""

import os
import re

import numpy as np
import pytest

from agents.geometry.wing_structure import (
    WingStructureSpec,
    build_wing_structure,
    rib_flat_patterns,
)
from cad.exporters import export_parts_step, export_profile_dxf, export_step_assembly

EDGES = list(np.linspace(0.0, 900.0, 4))


def _spec(**kw):
    base = {"semispan_mm": 900.0, "root_chord_mm": 300.0, "tip_chord_mm": 180.0, "naca": "4412",
            "bay_edges_mm": EDGES, "t_cap_mm": [1.2, 0.9, 0.5], "t_web_mm": [0.4, 0.3, 0.3], "n_profile": 21}
    base.update(kw)
    return WingStructureSpec(**base)


@pytest.fixture(scope="module")
def structure():
    return build_wing_structure(_spec())


@pytest.fixture(scope="module")
def step_text(structure, tmp_path_factory):
    path = tmp_path_factory.mktemp("step") / "wing.step"
    export_step_assembly(structure.assembly(), str(path))
    return path.read_text(encoding="latin-1")


def test_every_solid_is_named_by_component_and_side(structure):
    names = [s.label for g in structure.full_wing().values() for s in g.children]
    assert "Rib_1_Stbd" in names and "Rib_1_Port" in names
    assert "FrontSpar_Bay2_Stbd" in names and "UpperCover_Bay3_Port" in names
    assert "LeadingEdgeSkin_Stbd" in names and "TrailingEdgeSkin_Lower_Port" in names
    assert len(names) == len(set(names))  # unique within the assembly


def test_building_the_assembly_does_not_rename_the_half_wing(structure):
    structure.assembly()
    assert structure.parts["ribs"][0].label == "Rib_1"


def test_step_keeps_assembly_tree_names(step_text):
    products = re.findall(r"PRODUCT\('([^']*)'", step_text)
    assert "Wing" in products and "Ribs" in products and "BoxCovers" in products
    assert "Rib_4_Stbd" in products and "RearSpar_Bay1_Port" in products
    assert "COMPOUND" not in products


def test_step_carries_colours_and_millimetre_units(step_text):
    assert step_text.count("COLOUR_RGB") >= 5  # one colour per component group at least
    assert "SI_UNIT(.MILLI.,.METRE.)" in step_text
    assert "AUTOMOTIVE_DESIGN" in step_text  # AP214


def test_one_step_file_per_part(structure, tmp_path):
    paths = export_parts_step(structure.assembly(), str(tmp_path))
    n_solids = 2 * sum(len(ps) for ps in structure.parts.values())
    assert len(paths) == n_solids
    assert os.path.basename(paths[0]).endswith("_Stbd.step")
    assert all(os.path.getsize(p) > 1000 for p in paths)


def test_rib_flat_pattern_area_matches_the_3d_rib(structure, tmp_path):
    flats = rib_flat_patterns(structure.spec)
    assert list(flats) == [f"Rib_{i + 1}" for i in range(len(EDGES))]
    for i, rib in enumerate(structure.parts["ribs"]):
        area_3d = float(rib.volume) / structure.spec.rib_thickness_mm
        assert flats[f"Rib_{i + 1}"].area == pytest.approx(area_3d, rel=1e-3)
    path = tmp_path / "Rib_1.dxf"
    export_profile_dxf(flats["Rib_1"], str(path))
    text = path.read_text(encoding="latin-1")
    assert "ENTITIES" in text and ("CIRCLE" in text or "ARC" in text)  # lightening holes survive


def test_flat_pattern_without_holes_is_larger(structure):
    plain = rib_flat_patterns(_spec(rib_lightening_holes=False))
    holed = rib_flat_patterns(structure.spec)
    assert plain["Rib_1"].area > holed["Rib_1"].area
