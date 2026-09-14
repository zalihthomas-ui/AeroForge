"""FastAPI service exposing the v0.1 CAD MVP loop.

Run with: uvicorn backend.main:app --reload
"""

from __future__ import annotations

import tempfile

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from agents.design.agent import IncompleteRequirementError, UnrecognizedRequirementError
from agents.geometry.validation import GeometryValidationError
from backend.pipeline import run_pipeline

app = FastAPI(
    title="AEROFORGE",
    description="Prompt -> Design Agent -> Geometry Agent -> STEP/STL",
    version="0.3.0",
)


class DesignRequest(BaseModel):
    requirement: str


class DesignResponse(BaseModel):
    component: str
    parameters: dict[str, float]
    step_path: str
    stl_path: str
    threemf_path: str


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/design", response_model=DesignResponse)
def design(request: DesignRequest) -> DesignResponse:
    output_dir = tempfile.mkdtemp(prefix="aeroforge_")
    try:
        result = run_pipeline(request.requirement, output_dir)
    except IncompleteRequirementError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "incomplete_requirement",
                "component": exc.component,
                "missing": exc.missing,
                "provided": exc.provided,
                "message": str(exc),
            },
        ) from exc
    except UnrecognizedRequirementError as exc:
        raise HTTPException(
            status_code=422,
            detail={"error": "unrecognized_requirement", "message": str(exc)},
        ) from exc
    except GeometryValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"error": "invalid_geometry", "message": str(exc)},
        ) from exc

    return DesignResponse(
        component=result.spec.component,
        parameters=result.spec.parameters,
        step_path=result.step_path,
        stl_path=result.stl_path,
        threemf_path=result.threemf_path,
    )
