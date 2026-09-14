"""Tests the ccx.exe-not-found path specifically — deliberately NOT gated by
CALCULIX_AVAILABLE (unlike test_agent.py) since it exercises what happens
when ccx.exe can't be located, regardless of whether it's actually
installed on this machine."""

from __future__ import annotations

import pytest

import agents.structures.agent as agent_module
from agents.structures import StructuresAgent, StructuresEvaluationError


def test_missing_ccx_raises_clear_error_not_a_raw_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agent_module.shutil, "which", lambda name: None)
    monkeypatch.setattr(agent_module, "_DEFAULT_CCX_PATH", r"Z:\definitely\not\here\ccx.exe")

    with pytest.raises(StructuresEvaluationError, match="ccx.exe"):
        StructuresAgent().evaluate_cantilever_beam(
            length_mm=1000.0, width_mm=20.0, height_mm=10.0, force_n=100.0
        )
