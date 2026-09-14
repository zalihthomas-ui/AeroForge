"""Unit tests for the Design Agent wing parser (v0.2/v0.3 milestones)."""

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


def test_parse_mission_doc_wing_example(agent: DesignAgent):
    """Test standard wing requirement from mission doc."""
    text = (
        "Create a wing with span 1800 mm, root chord 240 mm, tip chord 140 mm, "
        "sweep 12 degrees, dihedral 4 degrees."
    )
    spec = agent.parse(text)

    assert isinstance(spec, EngineeringSpec)
    assert spec.component == "wing"
    assert spec.parameters == {
        "wing_span": 1800.0,
        "root_chord": 240.0,
        "tip_chord": 140.0,
        "sweep": 12.0,
        "dihedral": 4.0,
    }

    # Verify requirements
    req_map = {r.name: r for r in spec.requirements}
    assert req_map["wing_span"].value == 1800.0
    assert req_map["wing_span"].unit == "mm"
    assert req_map["root_chord"].value == 240.0
    assert req_map["root_chord"].unit == "mm"
    assert req_map["tip_chord"].value == 140.0
    assert req_map["tip_chord"].unit == "mm"
    assert req_map["sweep"].value == 12.0
    assert req_map["sweep"].unit == "deg"
    assert req_map["dihedral"].value == 4.0
    assert req_map["dihedral"].unit == "deg"

    # Verify constraints
    const_map = {c.name: c for c in spec.constraints}
    assert const_map["wing_span"].value == 1800.0
    assert const_map["wing_span"].operator == "=="
    assert const_map["root_chord"].value == 240.0
    assert const_map["root_chord"].operator == "=="
    assert const_map["tip_chord"].value == 140.0
    assert const_map["tip_chord"].operator == "=="
    assert const_map["sweep"].value == 12.0
    assert const_map["sweep"].operator == "=="
    assert const_map["dihedral"].value == 4.0
    assert const_map["dihedral"].operator == "=="

    # Metadata
    assert spec.metadata.get("raw_requirement") == text


def test_parse_wing_syntax_variations(agent: DesignAgent):
    """Test various keyword aliases and structured key-value syntax."""
    text1 = "UAV wing: wing_span=2000, root_chord=300, tip_chord=150, sweep=5, dihedral=2"
    spec1 = agent.parse(text1)
    assert spec1.component == "wing"
    assert spec1.parameters["wing_span"] == 2000.0
    assert spec1.parameters["root_chord"] == 300.0
    assert spec1.parameters["tip_chord"] == 150.0
    assert spec1.parameters["sweep"] == 5.0
    assert spec1.parameters["dihedral"] == 2.0

    text2 = "Aerodynamic wing with wingspan: 1500 mm, root: 200 mm, tip: 100 mm, leading edge sweep: 10 deg, dihedral angle: 3 deg"
    spec2 = agent.parse(text2)
    assert spec2.component == "wing"
    assert spec2.parameters["wing_span"] == 1500.0
    assert spec2.parameters["root_chord"] == 200.0
    assert spec2.parameters["tip_chord"] == 100.0
    assert spec2.parameters["sweep"] == 10.0
    assert spec2.parameters["dihedral"] == 3.0


def test_parse_wing_zero_and_negative_angles(agent: DesignAgent):
    """Test 0-degree and negative sweep/dihedral values within valid range."""
    text_zero = "Wing with span 1200 mm, root chord 180 mm, tip chord 90 mm, sweep 0 degrees, dihedral 0 degrees"
    spec_zero = agent.parse(text_zero)
    assert spec_zero.parameters["sweep"] == 0.0
    assert spec_zero.parameters["dihedral"] == 0.0

    text_neg = "Wing with span 1600 mm, root chord 220 mm, tip chord 110 mm, sweep -10 deg, dihedral -3 deg"
    spec_neg = agent.parse(text_neg)
    assert spec_neg.parameters["sweep"] == -10.0
    assert spec_neg.parameters["dihedral"] == -3.0


def test_reject_incomplete_wing_parameters(agent: DesignAgent):
    """Missing any parameter must raise IncompleteRequirementError with structured attributes."""
    with pytest.raises(IncompleteRequirementError) as exc:
        agent.parse("Create a wing with span 1800 mm, root chord 240 mm, tip chord 140 mm, dihedral 4 degrees.")
    assert exc.value.component == "wing"
    assert exc.value.missing == ["sweep"]
    assert exc.value.provided == {
        "wing_span": 1800.0,
        "root_chord": 240.0,
        "tip_chord": 140.0,
        "dihedral": 4.0,
    }
    assert isinstance(exc.value, UnrecognizedRequirementError)

    with pytest.raises(IncompleteRequirementError) as exc:
        agent.parse("Create a wing with root chord 240 mm, tip chord 140 mm, sweep 12 deg, dihedral 4 deg.")
    assert exc.value.component == "wing"
    assert exc.value.missing == ["wing_span"]
    assert exc.value.provided == {
        "root_chord": 240.0,
        "tip_chord": 140.0,
        "sweep": 12.0,
        "dihedral": 4.0,
    }

    with pytest.raises(IncompleteRequirementError) as exc:
        agent.parse("Create a wing with span 1800 mm")
    assert exc.value.component == "wing"
    assert exc.value.missing == ["root_chord", "tip_chord", "sweep", "dihedral"]
    assert exc.value.provided == {"wing_span": 1800.0}

    with pytest.raises(IncompleteRequirementError) as exc:
        agent.parse("Create an aircraft wing")
    assert exc.value.component == "wing"
    assert exc.value.missing == ["wing_span", "root_chord", "tip_chord", "sweep", "dihedral"]
    assert exc.value.provided == {}


def test_reject_non_positive_wing_dimensions(agent: DesignAgent):
    """Zero or negative spans and chords must raise UnrecognizedRequirementError."""
    with pytest.raises(UnrecognizedRequirementError):
        agent.parse("Create a wing with span 0 mm, root chord 240 mm, tip chord 140 mm, sweep 12 deg, dihedral 4 deg.")

    with pytest.raises(UnrecognizedRequirementError):
        agent.parse("Create a wing with span 1800 mm, root chord -50 mm, tip chord 140 mm, sweep 12 deg, dihedral 4 deg.")

    with pytest.raises(UnrecognizedRequirementError):
        agent.parse("Create a wing with span 1800 mm, root chord 240 mm, tip chord 0 mm, sweep 12 deg, dihedral 4 deg.")


def test_reject_out_of_range_wing_angles(agent: DesignAgent):
    """Sweep or dihedral outside [-45, 45] degrees must raise UnrecognizedRequirementError."""
    with pytest.raises(UnrecognizedRequirementError):
        agent.parse("Create a wing with span 1800 mm, root chord 240 mm, tip chord 140 mm, sweep 50 degrees, dihedral 4 degrees.")

    with pytest.raises(UnrecognizedRequirementError):
        agent.parse("Create a wing with span 1800 mm, root chord 240 mm, tip chord 140 mm, sweep -60 degrees, dihedral 4 degrees.")

    with pytest.raises(UnrecognizedRequirementError):
        agent.parse("Create a wing with span 1800 mm, root chord 240 mm, tip chord 140 mm, sweep 12 degrees, dihedral 50 degrees.")

    with pytest.raises(UnrecognizedRequirementError):
        agent.parse("Create a wing with span 1800 mm, root chord 240 mm, tip chord 140 mm, sweep 12 degrees, dihedral -50 degrees.")
