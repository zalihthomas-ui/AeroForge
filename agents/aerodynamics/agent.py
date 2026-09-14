"""Aerodynamics Agent for 2D airfoil section analysis.

Wraps NeuralFoil, a neural-network aerodynamic surrogate validated against
XFOIL and experimental wind tunnel data.

DISCLAIMER: This agent uses a neural surrogate (NeuralFoil), NOT a first-principles
CFD solver (such as OpenFOAM or SU2) or a panel-method solver (such as native XFOIL).
First-principles CFD and native panel-method integrations remain future work once
native toolchain constraints are resolved (see docs/architecture/roadmap.md).
"""

from __future__ import annotations

from dataclasses import dataclass
import re

import aerosandbox as asb
import neuralfoil as nf


class AerodynamicsEvaluationError(Exception):
    """Raised when airfoil aerodynamic evaluation fails due to invalid inputs or solver error."""

    pass


@dataclass
class AeroResult:
    """Aerodynamic coefficients and confidence from airfoil evaluation."""

    cl: float
    cd: float
    cm: float
    l_over_d: float
    confidence: float  # NeuralFoil's analysis_confidence metric


_NACA_PATTERN = re.compile(r"^(?:naca\s*)?(\d{4,5})$", re.IGNORECASE)


class AerodynamicsAgent:
    """Evaluates 2D airfoil section aerodynamics using NeuralFoil surrogate."""

    def __init__(self) -> None:
        pass

    def evaluate_naca_airfoil(
        self, naca_designation: str, alpha_deg: float, reynolds: float
    ) -> AeroResult:
        """Evaluate aerodynamic performance of a NACA airfoil section.

        Args:
            naca_designation: NACA 4-digit or 5-digit code (e.g. '0012', 'naca0012', 'NACA 2412').
            alpha_deg: Angle of attack in degrees.
            reynolds: Reynolds number (must be strictly positive).

        Returns:
            AeroResult: Lift (CL), drag (CD), pitching moment (CM), L/D ratio, and analysis confidence.

        Raises:
            AerodynamicsEvaluationError: If the designation is invalid, Reynolds <= 0,
                                         or evaluation fails.
        """
        if not naca_designation or not isinstance(naca_designation, str):
            raise AerodynamicsEvaluationError(
                "Airfoil designation cannot be empty. Expected a valid NACA code (e.g. '0012', 'naca0012')."
            )

        match = _NACA_PATTERN.match(naca_designation.strip())
        if not match:
            raise AerodynamicsEvaluationError(
                f"Invalid NACA designation: '{naca_designation}'. "
                "Expected a 4-digit or 5-digit NACA code (e.g. '0012', 'naca0012', 'NACA 2412')."
            )

        if reynolds <= 0:
            raise AerodynamicsEvaluationError(
                f"Reynolds number must be strictly positive. Got {reynolds}."
            )

        digits = match.group(1)
        normalized_name = f"naca{digits}"

        try:
            airfoil = asb.Airfoil(normalized_name)
        except Exception as exc:
            raise AerodynamicsEvaluationError(
                f"Failed to load airfoil geometry for '{naca_designation}': {exc}"
            ) from exc

        if airfoil.coordinates is None or len(airfoil.coordinates) == 0:
            raise AerodynamicsEvaluationError(
                f"Failed to generate airfoil coordinates for '{naca_designation}'."
            )

        try:
            res = nf.get_aero_from_airfoil(airfoil, alpha=float(alpha_deg), Re=float(reynolds))
        except Exception as exc:
            raise AerodynamicsEvaluationError(
                f"NeuralFoil evaluation failed for '{naca_designation}' at alpha={alpha_deg}, Re={reynolds}: {exc}"
            ) from exc

        cl = float(res["CL"].item() if hasattr(res["CL"], "item") else res["CL"][0])
        cd = float(res["CD"].item() if hasattr(res["CD"], "item") else res["CD"][0])
        cm = float(res["CM"].item() if hasattr(res["CM"], "item") else res["CM"][0])
        confidence = float(
            res["analysis_confidence"].item()
            if hasattr(res["analysis_confidence"], "item")
            else res["analysis_confidence"][0]
        )

        l_over_d = cl / cd if cd != 0 else 0.0

        return AeroResult(
            cl=cl,
            cd=cd,
            cm=cm,
            l_over_d=l_over_d,
            confidence=confidence,
        )
