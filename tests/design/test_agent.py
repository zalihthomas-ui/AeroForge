"""Unit tests for the Design Agent bracket parser."""

import pytest
from agents.design import (
    DesignAgent,
    IncompleteRequirementError,
    UnrecognizedRequirementError,
)
from engineering.requirements.schema import EngineeringSpec


@pytest.fixture
def agent() -> DesignAgent:
    return DesignAgent()


def test_parse_mission_doc_bracket_example(agent: DesignAgent):
    """Test standard Phase 1 bracket requirement from mission doc."""
    text = "Create a 100 x 80 x 5 mm mounting bracket with four 8 mm holes."
    spec = agent.parse(text)

    assert isinstance(spec, EngineeringSpec)
    assert spec.component == "bracket"
    assert spec.parameters == {
        "length": 100.0,
        "width": 80.0,
        "thickness": 5.0,
        "hole_diameter": 8.0,
        "hole_count": 4.0,
    }

    # Verify requirements
    req_map = {r.name: r for r in spec.requirements}
    assert req_map["length"].value == 100.0
    assert req_map["length"].unit == "mm"
    assert req_map["width"].value == 80.0
    assert req_map["width"].unit == "mm"
    assert req_map["thickness"].value == 5.0
    assert req_map["thickness"].unit == "mm"
    assert req_map["hole_diameter"].value == 8.0
    assert req_map["hole_diameter"].unit == "mm"
    assert req_map["hole_count"].value == 4.0

    # Verify constraints
    const_map = {c.name: c for c in spec.constraints}
    assert const_map["length"].value == 100.0
    assert const_map["length"].operator == "=="
    assert const_map["width"].value == 80.0
    assert const_map["width"].operator == "=="
    assert const_map["thickness"].value == 5.0
    assert const_map["thickness"].operator == "=="
    assert const_map["hole_diameter"].value == 8.0
    assert const_map["hole_diameter"].operator == "=="
    assert const_map["hole_count"].value == 4.0
    assert const_map["hole_count"].operator == "=="

    # Metadata
    assert spec.metadata.get("raw_requirement") == text


def test_parse_numeric_holes_variation(agent: DesignAgent):
    """Test requirement using digit numbers for holes."""
    text = "100 x 80 x 5 mm mounting bracket with 4 8mm holes"
    spec = agent.parse(text)

    assert spec.component == "bracket"
    assert spec.parameters["length"] == 100.0
    assert spec.parameters["width"] == 80.0
    assert spec.parameters["thickness"] == 5.0
    assert spec.parameters["hole_diameter"] == 8.0
    assert spec.parameters["hole_count"] == 4.0


def test_parse_alternative_formats(agent: DesignAgent):
    """Test unicode multiplication, 'by' phrasing, and uppercase."""
    text_unicode = "100 × 80 × 5 mm bracket with four 8 mm holes"
    spec1 = agent.parse(text_unicode)
    assert spec1.parameters["length"] == 100.0

    text_by = "100 mm by 80 mm by 5 mm mounting bracket with 4 holes of 8 mm"
    spec2 = agent.parse(text_by)
    assert spec2.parameters["length"] == 100.0
    assert spec2.parameters["hole_count"] == 4.0
    assert spec2.parameters["hole_diameter"] == 8.0

    text_named = "Mounting bracket with length: 120, width: 60, thickness: 4, hole count: 2, hole diameter: 6 mm"
    spec3 = agent.parse(text_named)
    assert spec3.parameters["length"] == 120.0
    assert spec3.parameters["width"] == 60.0
    assert spec3.parameters["thickness"] == 4.0
    assert spec3.parameters["hole_count"] == 2.0
    assert spec3.parameters["hole_diameter"] == 6.0


def test_parse_bracket_without_holes(agent: DesignAgent):
    """Test bracket with no holes specified."""
    text = "Create a 100 x 80 x 5 mm mounting bracket"
    spec = agent.parse(text)

    assert spec.parameters["length"] == 100.0
    assert spec.parameters["width"] == 80.0
    assert spec.parameters["thickness"] == 5.0
    assert spec.parameters["hole_count"] == 0.0
    assert spec.parameters["hole_diameter"] == 0.0


def test_parse_bracket_explicit_no_holes(agent: DesignAgent):
    """Test bracket with explicit no holes phrasing."""
    text = "100 x 80 x 5 mm bracket with no holes"
    spec = agent.parse(text)
    assert spec.parameters["hole_count"] == 0.0
    assert spec.parameters["hole_diameter"] == 0.0


def test_parse_floating_point_dimensions(agent: DesignAgent):
    """Test float dimensions and diameters."""
    text = "100.5 x 80.25 x 4.5 mm mounting bracket with 2 6.5 mm holes"
    spec = agent.parse(text)
    assert spec.parameters["length"] == 100.5
    assert spec.parameters["width"] == 80.25
    assert spec.parameters["thickness"] == 4.5
    assert spec.parameters["hole_diameter"] == 6.5
    assert spec.parameters["hole_count"] == 2.0


def test_reject_empty_input(agent: DesignAgent):
    """Empty or whitespace input must raise UnrecognizedRequirementError."""
    with pytest.raises(UnrecognizedRequirementError):
        agent.parse("")
    with pytest.raises(UnrecognizedRequirementError):
        agent.parse("   ")


def test_reject_unsupported_component(agent: DesignAgent):
    """Unsupported components (like rocket nozzle) must raise UnrecognizedRequirementError."""
    with pytest.raises(UnrecognizedRequirementError):
        agent.parse("Build a rocket combustion chamber with throat radius 20mm")


def test_reject_non_engineering_text(agent: DesignAgent):
    """Non-engineering text must raise UnrecognizedRequirementError."""
    with pytest.raises(UnrecognizedRequirementError):
        agent.parse("Hello, how are you?")


def test_reject_incomplete_dimensions(agent: DesignAgent):
    """Missing thickness or dimensions must raise IncompleteRequirementError with structured details."""
    with pytest.raises(IncompleteRequirementError) as exc:
        agent.parse("Create a mounting bracket")
    assert exc.value.component == "bracket"
    assert exc.value.missing == ["length", "width", "thickness"]
    assert exc.value.provided == {}
    # Also verify it is an instance of UnrecognizedRequirementError for backwards compatibility
    assert isinstance(exc.value, UnrecognizedRequirementError)

    with pytest.raises(IncompleteRequirementError) as exc:
        agent.parse("Create a 100 x 80 mm mounting bracket")
    assert exc.value.component == "bracket"
    assert exc.value.missing == ["thickness"]
    assert exc.value.provided == {"length": 100.0, "width": 80.0}

    with pytest.raises(IncompleteRequirementError) as exc:
        agent.parse("Mounting bracket with length: 120, thickness: 5")
    assert exc.value.component == "bracket"
    assert exc.value.missing == ["width"]
    assert exc.value.provided == {"length": 120.0, "thickness": 5.0}


def test_reject_invalid_dimensions(agent: DesignAgent):
    """Zero or negative dimensions must raise UnrecognizedRequirementError."""
    with pytest.raises(UnrecognizedRequirementError):
        agent.parse("0 x 80 x 5 mm mounting bracket")


def test_reject_unparseable_hole_info(agent: DesignAgent):
    """Mentioning holes without valid count or diameter must raise UnrecognizedRequirementError."""
    with pytest.raises(UnrecognizedRequirementError):
        agent.parse("100 x 80 x 5 mm mounting bracket with some holes")


def test_reject_oversized_hole_diameter(agent: DesignAgent):
    """Hole diameter larger than bracket dimensions must raise UnrecognizedRequirementError."""
    with pytest.raises(UnrecognizedRequirementError):
        agent.parse("10 x 10 x 5 mm mounting bracket with 4 50 mm holes")
