"""Integration tests for the full v0.1 loop: Design Agent -> Geometry Agent
-> exporters, both directly via run_pipeline() and through the FastAPI app.
"""

import os

from fastapi.testclient import TestClient

from backend.main import app
from backend.pipeline import run_pipeline

BRACKET_REQUIREMENT = "Create a 100 x 80 x 5 mm mounting bracket with four 8 mm holes."


def test_run_pipeline_end_to_end(tmp_path):
    result = run_pipeline(BRACKET_REQUIREMENT, str(tmp_path))

    assert result.spec.component == "bracket"
    assert result.spec.parameters["hole_count"] == 4

    for path in (result.step_path, result.stl_path, result.threemf_path):
        assert os.path.exists(path)
        assert os.path.getsize(path) > 0


def test_design_endpoint_success():
    client = TestClient(app)
    response = client.post("/design", json={"requirement": BRACKET_REQUIREMENT})

    assert response.status_code == 200
    body = response.json()
    assert body["component"] == "bracket"
    assert os.path.exists(body["step_path"])


def test_design_endpoint_rejects_unrecognized_requirement():
    client = TestClient(app)
    response = client.post("/design", json={"requirement": "not an engineering thing"})

    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "unrecognized_requirement"


def test_design_endpoint_reports_missing_parameters():
    client = TestClient(app)
    response = client.post(
        "/design", json={"requirement": "Create a 100 x 80 mm mounting bracket"}
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["error"] == "incomplete_requirement"
    assert detail["component"] == "bracket"
    assert detail["missing"] == ["thickness"]
    assert detail["provided"] == {"length": 100.0, "width": 80.0}


def test_design_endpoint_rejects_invalid_geometry():
    client = TestClient(app)
    response = client.post(
        "/design",
        json={"requirement": "Create a 10 x 10 x 5 mm mounting bracket with four 50 mm holes."},
    )

    assert response.status_code == 422
