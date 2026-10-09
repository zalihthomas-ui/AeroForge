"""Tests for the optimizer animation examples.

examples/wing/animate_optimization.py and examples/bracket/animate_optimization_2d.py
record the real optimizers' evaluation history and render it. Solvers are replaced
with fast analytical stand-ins here so the tests run in seconds; the recording and
rendering paths are exercised end to end (animation written as a small GIF).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

import engineering.analysis.wing_optimizer as wing_optimizer
from agents.structures.agent import BracketStructuralResult, StructuresAgent
from engineering.analysis.wing_aero import WingAeroSummary

ROOT = Path(__file__).resolve().parents[2]


def _load(rel_path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses resolve their module through sys.modules
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def wing_anim():
    return _load("examples/wing/animate_optimization.py", "wing_animate_optimization")


@pytest.fixture(scope="module")
def bracket_anim():
    return _load("examples/bracket/animate_optimization_2d.py", "bracket_animate_optimization_2d")


@pytest.fixture
def fake_aero(monkeypatch):
    """Smooth L/D(alpha) with a camber-dependent peak; returns a real WingAeroSummary."""

    def fake(spec, cruise_velocity_mps=25.0, alpha_deg=4.0, backend="neuralfoil", **_):
        code = f"{int(spec.parameters['naca_airfoil']):04d}"
        camber = int(code[0])
        peak_alpha, peak_ld = 4.0 + 0.5 * camber, 50.0 + 10.0 * camber
        ld = peak_ld - 2.0 * (alpha_deg - peak_alpha) ** 2
        cl = 0.1 * alpha_deg + 0.1 * camber
        return WingAeroSummary(naca_airfoil=code, reynolds_number=4e5, cl=cl, cd=cl / ld if ld else 1.0,
                               l_over_d=ld, lift_n=10.0, drag_n=0.1, backend=backend)

    monkeypatch.setattr(wing_optimizer, "evaluate_wing_aero", fake)
    return fake


def test_wing_recording_captures_every_optimizer_call(wing_anim, fake_aero):
    result, history = wing_anim.record_wing_optimization(candidate_naca_airfoils=["0012", "4412"])

    assert len(history) > 4
    assert [p.index for p in history] == list(range(len(history)))
    assert {p.naca_airfoil for p in history} == {"0012", "4412"}
    # the recorded probes contain the optimum the optimizer reports
    best = max(history, key=lambda p: p.l_over_d)
    assert result.optimal_naca_airfoil == "4412"
    assert best.l_over_d == pytest.approx(result.max_l_over_d, rel=1e-9)
    # the wrapper is removed afterwards
    assert wing_optimizer.evaluate_wing_aero is fake_aero


def test_wing_recording_restores_evaluator_on_error(wing_anim, monkeypatch):
    sentinel = MagicMock(side_effect=RuntimeError("solver down"))
    monkeypatch.setattr(wing_optimizer, "evaluate_wing_aero", sentinel)
    monkeypatch.setattr(wing_optimizer, "optimize_wing_for_max_l_over_d",
                        MagicMock(side_effect=RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        wing_anim.record_wing_optimization()
    assert wing_optimizer.evaluate_wing_aero is sentinel


@pytest.mark.parametrize("code", ["0012", "2412", "4415"])
def test_naca4_outline_thickness_and_closure(wing_anim, code):
    x, y = wing_anim.naca4_coordinates(code, n=200)
    # cambered sections reach slightly ahead of x=0 (thickness is applied normal to the camber line)
    assert x.min() == pytest.approx(0.0, abs=5e-3) and x.max() == pytest.approx(1.0, abs=1e-6)
    # closed at the trailing edge
    assert (x[0], y[0]) == pytest.approx((x[-1], y[-1]), abs=2e-3)
    # max thickness ~ last two digits / 100
    n = len(x) // 2 + 1
    upper = np.interp(np.linspace(0.05, 0.95, 50), x[:n][::-1], y[:n][::-1])
    lower = np.interp(np.linspace(0.05, 0.95, 50), x[n - 1:], y[n - 1:])
    assert (upper - lower).max() == pytest.approx(int(code[2:]) / 100.0, rel=0.05)


def test_wing_render_writes_animation(wing_anim, fake_aero, tmp_path):
    result, history = wing_anim.record_wing_optimization(candidate_naca_airfoils=["0012", "2412"])
    out = wing_anim.render_animation(result, history[:6], str(tmp_path / "wing.gif"), fps=4, frames_per_probe=1)
    assert Path(out).exists() and Path(out).stat().st_size > 1000


def test_wing_render_rejects_empty_history(wing_anim, tmp_path):
    with pytest.raises(ValueError):
        wing_anim.render_animation(MagicMock(), [], str(tmp_path / "x.gif"))


@pytest.fixture
def mock_structures_agent() -> StructuresAgent:
    """Analytical stress surrogate (same form as test_bracket_optimizer_2d.py)."""
    mock = MagicMock(spec=StructuresAgent)

    def side_effect(length_mm, width_mm, thickness_mm, hole_diameter_mm, hole_count, applied_force_n,
                    youngs_modulus_mpa=210000.0, poissons_ratio=0.3):
        stress = 5.48 * ((5.0 / thickness_mm) ** 1.5) * (1.0 + 0.04 * (hole_diameter_mm - 8.0))
        return BracketStructuralResult(hotspot_stress_mpa=stress, raw_peak_stress_mpa=stress * 1.5,
                                       max_deflection_mm=0.1, equilibrium_error_pct=0.01, mesh_converged=True,
                                       coarse_mesh_hotspot_stress_mpa=stress, fine_mesh_hotspot_stress_mpa=stress)

    mock.evaluate_bracket.side_effect = side_effect
    return mock


def test_bracket_animation_end_to_end(bracket_anim, mock_structures_agent, tmp_path):
    problem, result = bracket_anim.run_optimization(structures_agent=mock_structures_agent, max_evaluations=8)

    assert result.converged
    assert len(result.evaluations) <= 8 + 2
    assert result.stress_at_optimum_mpa <= problem["max_allowable_stress_mpa"] + 1e-6
    out = bracket_anim.render_animation(problem, result, str(tmp_path / "bracket.gif"), fps=4, frames_per_eval=1)
    assert Path(out).exists() and Path(out).stat().st_size > 1000
