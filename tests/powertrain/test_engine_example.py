"""The V6 example runs end to end and writes a self-consistent report."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_engine_example_writes_report(tmp_path):
    subprocess.run([sys.executable, str(ROOT / "examples" / "engine" / "simulate.py"), "--out", str(tmp_path)],
                   check=True, capture_output=True, text=True, cwd=ROOT)
    rep = json.loads((tmp_path / "engine_report.json").read_text(encoding="utf-8"))
    assert rep["peak_torque"]["rpm"] < rep["peak_power"]["rpm"]
    assert rep["conrod"]["sized"]["buckling_sf"] >= 3.0 - 1e-6
    assert abs(rep["balance_6000"]["force_orders_n"]["1"]) < 1e-6
