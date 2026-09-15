"""Unit tests for bracket CAD materializer (engineering.analysis.bracket_materializer).

Tests:
1. Materialization of optimal bracket CAD models (STEP, STL, 3MF) with mock agent.
2. Consistency re-analysis verification (stress discrepancy <= tolerance).
3. Parameter validation and error wrapping (BracketMaterializerError).
4. Automatic nested output directory creation.
5. Real CalculiX FEA materialization test (gated by CALCULIX_AVAILABLE).
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from agents.structures import CALCULIX_AVAILABLE, BracketStructuralResult, StructuresAgent
from engineering.analysis.bracket_materializer import (
    BracketMaterializerError,
    MaterializedBracketResult,
    materialize_optimal_bracket,
)
from engineering.analysis.bracket_optimizer import (
    BracketDesignPoint,
    BracketOptimizationResult,
)


def test_materialize_bracket_with_mock_agent(tmp_path: Path) -> None:
    """Validate bracket CAD generation and consistency verification with a mock StructuresAgent."""
    mock_agent = MagicMock(spec=StructuresAgent)
    mock_agent.evaluate_bracket.return_value = BracketStructuralResult(
        hotspot_stress_mpa=6.5263,
        raw_peak_stress_mpa=8.3800,
        max_deflection_mm=0.00065,
        equilibrium_error_pct=0.0008,
        mesh_converged=True,
        coarse_mesh_hotspot_stress_mpa=6.4800,
        fine_mesh_hotspot_stress_mpa=6.5263,
    )

    opt_result = BracketOptimizationResult(
        optimal_thickness_mm=5.5539,
        optimal_mass_kg=0.34002,
        max_stress_at_optimum_mpa=6.5263,
        max_allowable_stress_mpa=6.5000,
        evaluations=[
            BracketDesignPoint(
                thickness_mm=5.5539,
                mass_kg=0.34002,
                hotspot_stress_mpa=6.5263,
                mesh_converged=True,
            )
        ],
    )

    out_dir = str(tmp_path / "cad_export")
    result = materialize_optimal_bracket(
        length_mm=100.0,
        width_mm=80.0,
        hole_diameter_mm=8.0,
        hole_count=4,
        applied_force_n=500.0,
        optimization_result=opt_result,
        output_dir=out_dir,
        tolerance_pct=0.1,
        structures_agent=mock_agent,
    )

    assert isinstance(result, MaterializedBracketResult)
    assert result.optimization_result == opt_result
    assert result.final_spec_parameters["thickness"] == pytest.approx(5.5539)
    assert result.final_spec_parameters["length"] == 100.0
    assert result.final_spec_parameters["width"] == 80.0
    assert result.final_spec_parameters["hole_diameter"] == 8.0
    assert result.final_spec_parameters["hole_count"] == 4.0

    # Verify generated CAD files
    for path in (result.step_path, result.stl_path, result.threemf_path):
        assert os.path.isfile(path), f"File {path} was not created."
        assert os.path.getsize(path) > 100, f"File {path} is empty or invalid."

    # Verify consistency re-analysis
    assert result.reanalysis_matches_optimum is True
    assert result.stress_discrepancy_pct < 0.01
    assert result.reanalysis.hotspot_stress_mpa == pytest.approx(6.5263)


def test_materialize_bracket_parameter_validation_rejection(tmp_path: Path) -> None:
    """Invalid geometry parameters or non-positive applied force must raise BracketMaterializerError."""
    dummy_opt = BracketOptimizationResult(
        optimal_thickness_mm=5.0,
        optimal_mass_kg=0.3,
        max_stress_at_optimum_mpa=7.0,
        max_allowable_stress_mpa=7.0,
        evaluations=[],
    )

    # Hole diameter too large for plate width
    with pytest.raises(BracketMaterializerError, match="Geometry validation failed"):
        materialize_optimal_bracket(
            length_mm=100.0,
            width_mm=80.0,
            hole_diameter_mm=79.0,  # invalid hole diameter
            hole_count=4,
            applied_force_n=500.0,
            optimization_result=dummy_opt,
            output_dir=str(tmp_path),
        )

    # Non-positive applied force
    with pytest.raises(BracketMaterializerError, match="applied_force_n must be strictly positive"):
        materialize_optimal_bracket(
            length_mm=100.0,
            width_mm=80.0,
            hole_diameter_mm=8.0,
            hole_count=4,
            applied_force_n=0.0,
            optimization_result=dummy_opt,
            output_dir=str(tmp_path),
        )


def test_materialize_bracket_creates_nested_output_directory(tmp_path: Path) -> None:
    """Nested non-existent output directory is created automatically."""
    nested_dir = str(tmp_path / "deep" / "nested" / "bracket_cad")
    assert not os.path.exists(nested_dir)

    mock_agent = MagicMock(spec=StructuresAgent)
    mock_agent.evaluate_bracket.return_value = BracketStructuralResult(
        hotspot_stress_mpa=7.0,
        raw_peak_stress_mpa=9.0,
        max_deflection_mm=0.001,
        equilibrium_error_pct=0.001,
        mesh_converged=True,
        coarse_mesh_hotspot_stress_mpa=7.0,
        fine_mesh_hotspot_stress_mpa=7.0,
    )

    dummy_opt = BracketOptimizationResult(
        optimal_thickness_mm=5.0,
        optimal_mass_kg=0.3,
        max_stress_at_optimum_mpa=7.0,
        max_allowable_stress_mpa=7.0,
        evaluations=[],
    )

    result = materialize_optimal_bracket(
        length_mm=100.0,
        width_mm=80.0,
        hole_diameter_mm=8.0,
        hole_count=4,
        applied_force_n=500.0,
        optimization_result=dummy_opt,
        output_dir=nested_dir,
        structures_agent=mock_agent,
    )

    assert os.path.isdir(nested_dir)
    assert os.path.isfile(result.step_path)
    assert os.path.isfile(result.stl_path)
    assert os.path.isfile(result.threemf_path)


@pytest.mark.skipif(
    not CALCULIX_AVAILABLE,
    reason="ccx.exe (CalculiX) not installed on this machine — see vendor/calculix/README.md",
)
def test_real_bracket_materialization_calculix(tmp_path: Path) -> None:
    """Real closed-loop CAD materialization and CalculiX 3D solid FEA consistency re-analysis."""
    # Pre-evaluated optimization result for 100x80mm bracket, 500N load, 5.0mm baseline
    opt_result = BracketOptimizationResult(
        optimal_thickness_mm=5.0,
        optimal_mass_kg=0.3061,
        max_stress_at_optimum_mpa=5.4800,  # known hotspot stress at t=5.0mm
        max_allowable_stress_mpa=6.5000,
        evaluations=[],
    )

    out_dir = str(tmp_path / "real_cad_export")
    result = materialize_optimal_bracket(
        length_mm=100.0,
        width_mm=80.0,
        hole_diameter_mm=8.0,
        hole_count=4,
        applied_force_n=500.0,
        optimization_result=opt_result,
        output_dir=out_dir,
        tolerance_pct=5.0,
    )

    assert isinstance(result, MaterializedBracketResult)
    assert os.path.isfile(result.step_path)
    assert os.path.isfile(result.stl_path)
    assert os.path.isfile(result.threemf_path)
    assert result.reanalysis.mesh_converged is True
    assert result.reanalysis.equilibrium_error_pct < 1.0
    assert result.reanalysis_matches_optimum is True
