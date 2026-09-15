"""Unit tests for wing CAD materializer (engineering.analysis.wing_materializer).

Tests:
1. End-to-end materialization on reference wing with real optimization result.
2. CAD exports exist, are non-empty, and valid (STEP, STL, 3MF).
3. Consistency re-analysis matches optimizer's reported L/D within tight tolerance.
4. Non-wing component specs are rejected with clear error.
5. Geometry validation errors are caught and cleanly wrapped.
6. Automatic creation of nested output directories.
"""

from __future__ import annotations

import os
from pathlib import Path
import pytest

from engineering.analysis.wing_materializer import (
    MaterializedWingResult,
    WingMaterializerError,
    materialize_optimal_wing,
)
from engineering.analysis.wing_optimizer import (
    AirfoilCandidateResult,
    WingOptimizationResult,
    optimize_wing_for_max_l_over_d,
)
from engineering.requirements.schema import EngineeringSpec

REFERENCE_WING_SPEC = EngineeringSpec(
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


def test_materialize_optimal_wing_end_to_end(tmp_path: Path) -> None:
    """Run full optimization and materialize the resulting optimal CAD wing.

    Verifies:
    - Optimization selects best airfoil (e.g. NACA 4412).
    - Materializer generates and exports valid STEP, STL, and 3MF files.
    - Final spec parameters reflect the optimal airfoil.
    - Re-analysis L/D matches optimizer's reported max L/D within tight tolerance.
    """
    opt_result = optimize_wing_for_max_l_over_d(
        REFERENCE_WING_SPEC,
        candidate_naca_airfoils=["0012", "4412"],
        alpha_bounds_deg=(0.0, 10.0),
        cruise_velocity_mps=25.0,
    )

    out_dir = str(tmp_path / "cad_export")
    mat_result = materialize_optimal_wing(
        REFERENCE_WING_SPEC,
        opt_result,
        output_dir=out_dir,
        cruise_velocity_mps=25.0,
        backend="neuralfoil",
        tolerance_pct=0.1,
    )

    assert isinstance(mat_result, MaterializedWingResult)
    assert mat_result.optimization_result == opt_result
    assert mat_result.final_spec.component == "wing"
    assert mat_result.final_spec.parameters["naca_airfoil"] == float(opt_result.optimal_naca_airfoil)

    # Check that export files exist and are non-empty
    for path in (mat_result.step_path, mat_result.stl_path, mat_result.threemf_path):
        assert os.path.isfile(path), f"File {path} does not exist."
        assert os.path.getsize(path) > 100, f"File {path} is suspiciously small ({os.path.getsize(path)} bytes)."

    # Verify consistency re-analysis
    assert mat_result.reanalysis_matches_optimum is True
    assert mat_result.l_over_d_discrepancy_pct < 0.05
    assert mat_result.reanalysis.l_over_d == pytest.approx(opt_result.max_l_over_d, rel=1e-4)
    assert mat_result.reanalysis.naca_airfoil == opt_result.optimal_naca_airfoil


def test_materialize_rejects_non_wing_component(tmp_path: Path) -> None:
    """Passing a bracket spec must be rejected with WingMaterializerError."""
    bracket_spec = EngineeringSpec(
        component="bracket",
        parameters={
            "length": 100.0,
            "width": 80.0,
            "thickness": 5.0,
            "hole_diameter": 8.0,
            "hole_count": 4.0,
        },
    )
    dummy_opt = WingOptimizationResult(
        optimal_naca_airfoil="4412",
        optimal_alpha_deg=5.0,
        max_l_over_d=50.0,
        cl_at_optimum=0.8,
        cd_at_optimum=0.016,
        all_candidates=[],
    )

    with pytest.raises(WingMaterializerError, match="requires component='wing'"):
        materialize_optimal_wing(bracket_spec, dummy_opt, output_dir=str(tmp_path))


def test_materialize_wraps_geometry_validation_errors(tmp_path: Path) -> None:
    """If base wing spec parameters fail geometry validation (e.g. non-positive chord),
    the error must be caught and wrapped cleanly as WingMaterializerError."""
    invalid_spec = EngineeringSpec(
        component="wing",
        parameters={
            "wing_span": 1800.0,
            "root_chord": -50.0,  # invalid chord
            "tip_chord": 140.0,
            "sweep": 12.0,
            "dihedral": 4.0,
            "naca_airfoil": 12.0,
        },
    )
    dummy_opt = WingOptimizationResult(
        optimal_naca_airfoil="0012",
        optimal_alpha_deg=4.0,
        max_l_over_d=40.0,
        cl_at_optimum=0.5,
        cd_at_optimum=0.0125,
        all_candidates=[],
    )

    with pytest.raises(WingMaterializerError, match="Geometry validation failed"):
        materialize_optimal_wing(invalid_spec, dummy_opt, output_dir=str(tmp_path))


def test_materialize_creates_nested_output_directory(tmp_path: Path) -> None:
    """Missing nested directory path is automatically created."""
    nested_dir = str(tmp_path / "deeply" / "nested" / "models")
    assert not os.path.exists(nested_dir)

    dummy_opt = WingOptimizationResult(
        optimal_naca_airfoil="2412",
        optimal_alpha_deg=5.0,
        max_l_over_d=80.0,
        cl_at_optimum=0.7,
        cd_at_optimum=0.00875,
        all_candidates=[],
    )

    result = materialize_optimal_wing(
        REFERENCE_WING_SPEC,
        dummy_opt,
        output_dir=nested_dir,
    )

    assert os.path.isdir(nested_dir)
    assert os.path.isfile(result.step_path)
    assert os.path.isfile(result.stl_path)
    assert os.path.isfile(result.threemf_path)
