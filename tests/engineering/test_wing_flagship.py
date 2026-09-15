"""Unit and integration tests for multidisciplinary wing flagship evaluation and planform sizing.

Tests:
1. Baseline reference wing aerodynamic failure under 12 kg MTOW cruise requirement.
2. Closed-loop planform sizing (scipy.optimize.brentq) converging to Lift == MTOW * g.
3. Informational CAD solid volume reporting without causing design rejection.
4. Comprehensive input and bounds validation (negative/zero dimensions, unbracketed bounds).
5. Mock structures agent injection for deterministic unit testing.
6. Real CalculiX multidisciplinary integration (gated by CALCULIX_AVAILABLE).
"""

from __future__ import annotations

from unittest.mock import MagicMock
import pytest

from agents.structures.agent import CALCULIX_AVAILABLE, StructuresAgent, WingStructuralResult
from engineering.analysis.wing_flagship import (
    FlagshipDesignResult,
    WingDesignRequirement,
    WingFlagshipError,
    evaluate_wing_design,
    find_passing_wing_design,
)
from engineering.requirements.schema import EngineeringSpec


@pytest.fixture
def baseline_wing_spec() -> EngineeringSpec:
    """Reference baseline wing from mission documents."""
    return EngineeringSpec(
        component="wing",
        parameters={
            "wing_span": 1800.0,
            "root_chord": 240.0,
            "tip_chord": 140.0,
            "sweep": 12.0,
            "dihedral": 4.0,
            "naca_airfoil": 12.0,
        },
    )


@pytest.fixture
def uav_requirement() -> WingDesignRequirement:
    """Reference 12.0 kg MTOW UAV mission requirement."""
    return WingDesignRequirement(
        mtow_kg=12.0,
        cruise_velocity_mps=25.0,
        max_span_mm=1800.0,
        min_safety_factor=1.5,
    )


@pytest.fixture
def mock_structures_agent() -> StructuresAgent:
    """Mock StructuresAgent returning a high safety factor."""
    mock = MagicMock(spec=StructuresAgent)
    mock.evaluate_wing.return_value = WingStructuralResult(
        hotspot_stress_mpa=5.0,
        raw_peak_stress_mpa=6.0,
        max_deflection_mm=0.5,
        safety_factor=10.0,
        equilibrium_error_pct=0.01,
        mesh_converged=True,
        coarse_mesh_hotspot_stress_mpa=5.1,
        fine_mesh_hotspot_stress_mpa=5.0,
    )
    return mock


def test_baseline_wing_fails_lift_requirement(
    baseline_wing_spec: EngineeringSpec,
    uav_requirement: WingDesignRequirement,
    mock_structures_agent: StructuresAgent,
) -> None:
    """Verify that the baseline reference wing produces ~65.7 N and FAILS the 12kg requirement (117.72 N)."""
    res = evaluate_wing_design(
        baseline_wing_spec,
        uav_requirement,
        alpha_deg=4.0,
        backend="neuralfoil",
        structures_agent=mock_structures_agent,
    )

    assert res.required_lift_n == pytest.approx(117.72, abs=0.01)
    assert res.lift_n < res.required_lift_n
    assert 60.0 < res.lift_n < 70.0  # ~65.7 N
    assert res.lift_adequate is False
    assert res.safety_adequate is True
    assert res.span_adequate is True
    assert res.overall_status == "FAIL"
    assert res.solid_volume_mm3 > 0  # informational CAD solid volume reported


def test_find_passing_wing_design_converges(
    baseline_wing_spec: EngineeringSpec,
    uav_requirement: WingDesignRequirement,
    mock_structures_agent: StructuresAgent,
) -> None:
    """Verify closed-loop root-finding sizes chords to satisfy Lift == 117.72 N with PASS status."""
    res = find_passing_wing_design(
        baseline_wing_spec,
        uav_requirement,
        alpha_deg=4.0,
        backend="neuralfoil",
        chord_scale_bounds=(1.0, 2.5),
        structures_agent=mock_structures_agent,
    )

    assert res.overall_status == "PASS"
    assert res.lift_adequate is True
    assert res.safety_adequate is True
    assert res.span_adequate is True
    assert res.lift_n == pytest.approx(res.required_lift_n, abs=0.05)
    assert res.spec_parameters["wing_span"] == 1800.0
    assert res.spec_parameters["root_chord"] > 240.0
    assert res.spec_parameters["tip_chord"] > 140.0
    # Initial failed baseline is logged in iterations
    assert len(res.iterations) == 1
    assert res.iterations[0].overall_status == "FAIL"


def test_already_passing_design_returns_immediately(
    baseline_wing_spec: EngineeringSpec,
    mock_structures_agent: StructuresAgent,
) -> None:
    """Verify that an already-passing light requirement returns PASS directly."""
    light_req = WingDesignRequirement(
        mtow_kg=5.0,  # 5kg requires 49.05 N < baseline ~65.7 N
        cruise_velocity_mps=25.0,
        max_span_mm=1800.0,
        min_safety_factor=1.5,
    )
    res = find_passing_wing_design(
        baseline_wing_spec,
        light_req,
        alpha_deg=4.0,
        backend="neuralfoil",
        structures_agent=mock_structures_agent,
    )
    assert res.overall_status == "PASS"
    assert res.lift_adequate is True
    assert len(res.iterations) == 1
    assert res.iterations[0].overall_status == "PASS"


@pytest.mark.parametrize(
    "invalid_kwargs, err_match",
    [
        ({"mtow_kg": -1.0}, "strictly positive"),
        ({"mtow_kg": 0.0}, "strictly positive"),
        ({"cruise_velocity_mps": -5.0}, "strictly positive"),
        ({"max_span_mm": 0.0}, "strictly positive"),
        ({"min_safety_factor": -0.5}, "strictly positive"),
    ],
)
def test_invalid_requirements_raise_error(
    baseline_wing_spec: EngineeringSpec,
    invalid_kwargs: dict[str, float],
    err_match: str,
) -> None:
    """Verify invalid requirement properties raise WingFlagshipError."""
    default_kwargs = {
        "mtow_kg": 12.0,
        "cruise_velocity_mps": 25.0,
        "max_span_mm": 1800.0,
        "min_safety_factor": 1.5,
    }
    default_kwargs.update(invalid_kwargs)
    req = WingDesignRequirement(**default_kwargs)

    with pytest.raises(WingFlagshipError, match=err_match):
        evaluate_wing_design(baseline_wing_spec, req)


def test_invalid_component_type(uav_requirement: WingDesignRequirement) -> None:
    """Verify non-wing component specs are rejected."""
    bracket_spec = EngineeringSpec(
        component="bracket",
        parameters={"length": 100.0, "width": 80.0, "thickness": 5.0, "hole_diameter": 8.0, "hole_count": 4},
    )
    with pytest.raises(WingFlagshipError, match="requires component='wing'"):
        evaluate_wing_design(bracket_spec, uav_requirement)

    with pytest.raises(WingFlagshipError, match="requires component='wing'"):
        find_passing_wing_design(bracket_spec, uav_requirement)


def test_invalid_chord_scale_bounds(
    baseline_wing_spec: EngineeringSpec,
    uav_requirement: WingDesignRequirement,
) -> None:
    """Verify invalid chord scale bounds tuples raise WingFlagshipError."""
    with pytest.raises(WingFlagshipError, match="Invalid chord_scale_bounds"):
        find_passing_wing_design(baseline_wing_spec, uav_requirement, chord_scale_bounds=(2.0, 1.0))

    with pytest.raises(WingFlagshipError, match="Invalid chord_scale_bounds"):
        find_passing_wing_design(baseline_wing_spec, uav_requirement, chord_scale_bounds=(-1.0, 2.0))


def test_unbracketed_bounds_raise_informative_error(
    baseline_wing_spec: EngineeringSpec,
    uav_requirement: WingDesignRequirement,
    mock_structures_agent: StructuresAgent,
) -> None:
    """Verify bounds that do not bracket the target lift raise an informative WingFlagshipError."""
    # Target lift is 117.72 N, but bounds (1.0, 1.2) yield lift in [65.7, 78.8] N
    with pytest.raises(WingFlagshipError, match="do not bracket required lift"):
        find_passing_wing_design(
            baseline_wing_spec,
            uav_requirement,
            chord_scale_bounds=(1.0, 1.2),
            structures_agent=mock_structures_agent,
        )


@pytest.mark.skipif(not CALCULIX_AVAILABLE, reason="CalculiX ccx.exe not available")
def test_real_calculix_multidisciplinary_flow(
    baseline_wing_spec: EngineeringSpec,
    uav_requirement: WingDesignRequirement,
) -> None:
    """End-to-end integration test with real CalculiX 3D solid FEA."""
    final_res = find_passing_wing_design(
        baseline_wing_spec,
        uav_requirement,
        alpha_deg=4.0,
        backend="neuralfoil",
        chord_scale_bounds=(1.0, 2.5),
    )

    assert final_res.overall_status == "PASS"
    assert final_res.lift_adequate is True
    assert final_res.safety_adequate is True
    assert final_res.span_adequate is True
    assert final_res.safety_factor > uav_requirement.min_safety_factor
    assert final_res.lift_n == pytest.approx(117.72, abs=0.1)
