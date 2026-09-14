"""Aerodynamics Agent for 2D airfoil section analysis.

Two backends:

- "neuralfoil" (default): a neural-network aerodynamic surrogate validated
  against XFOIL and experimental wind tunnel data. Always available (pure
  Python, pip-installable, no compiler needed).
- "xfoil": the real XFOIL Fortran solver (genuine coupled panel-method +
  boundary-layer analysis, not a surrogate). Optional: requires the
  vendored wheel at vendor/xfoil/ (Windows x64 + CPython 3.13 only) because
  the PyPI `xfoil` sdist is broken upstream (missing CMakeLists.txt/src/ —
  see vendor/xfoil/README.md and docs/architecture/roadmap.md's v0.4
  section for the full story). Feature-detected at import time; falls back
  to unavailable (raises AerodynamicsEvaluationError) everywhere it isn't
  installed, including CI (ubuntu-latest has no vendored wheel to install).

Both backends were verified 2026-09-15 to agree closely on NACA 0012
(e.g. alpha=4deg, Re=1e6: NeuralFoil CL~0.43 vs XFOIL CL~0.43) — see
tests/aerodynamics/test_xfoil_backend.py's cross-validation test.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

import aerosandbox as asb
import neuralfoil as nf

try:
    from xfoil import XFoil as _XFoil

    XFOIL_AVAILABLE = True
except ImportError:
    XFOIL_AVAILABLE = False


class AerodynamicsEvaluationError(Exception):
    """Raised when airfoil aerodynamic evaluation fails due to invalid inputs or solver error."""

    pass


@dataclass
class AeroResult:
    """Aerodynamic coefficients from airfoil evaluation.

    `confidence` means different things per backend: NeuralFoil's own
    continuous ML confidence estimate (0-1) for "neuralfoil", or 1.0
    (converged) / this is never returned unconverged, see raises) for
    "xfoil" — the real solver either converges or the call raises, it
    doesn't report a graded confidence.
    """

    cl: float
    cd: float
    cm: float
    l_over_d: float
    confidence: float
    backend: str


_NACA_PATTERN = re.compile(r"^(?:naca\s*)?(\d{4,5})$", re.IGNORECASE)
_SUPPORTED_BACKENDS = ("neuralfoil", "xfoil")


class AerodynamicsAgent:
    """Evaluates 2D airfoil section aerodynamics via NeuralFoil or real XFOIL."""

    def __init__(self) -> None:
        pass

    def evaluate_naca_airfoil(
        self,
        naca_designation: str,
        alpha_deg: float,
        reynolds: float,
        backend: str = "neuralfoil",
    ) -> AeroResult:
        """Evaluate aerodynamic performance of a NACA airfoil section.

        Args:
            naca_designation: NACA 4-digit or 5-digit code (e.g. '0012', 'naca0012', 'NACA 2412').
            alpha_deg: Angle of attack in degrees.
            reynolds: Reynolds number (must be strictly positive).
            backend: "neuralfoil" (default, always available) or "xfoil"
                (real solver, only available if the vendored wheel is
                installed — see module docstring).

        Returns:
            AeroResult: Lift (CL), drag (CD), pitching moment (CM), L/D ratio,
            confidence, and which backend produced it.

        Raises:
            AerodynamicsEvaluationError: If the designation/backend is invalid,
                                          Reynolds <= 0, or evaluation fails
                                          (including XFOIL non-convergence).
        """
        digits = self._validate_and_normalize(naca_designation, reynolds, backend)

        if backend == "neuralfoil":
            return self._evaluate_neuralfoil(naca_designation, digits, alpha_deg, reynolds)
        return self._evaluate_xfoil(naca_designation, digits, alpha_deg, reynolds)

    def _validate_and_normalize(self, naca_designation: str, reynolds: float, backend: str) -> str:
        if backend not in _SUPPORTED_BACKENDS:
            raise AerodynamicsEvaluationError(
                f"Unknown backend '{backend}'. Supported: {_SUPPORTED_BACKENDS}."
            )
        if backend == "xfoil" and not XFOIL_AVAILABLE:
            raise AerodynamicsEvaluationError(
                "backend='xfoil' requested but the 'xfoil' package is not installed. "
                "Install the vendored wheel (Windows x64 + CPython 3.13 only): "
                "pip install vendor/xfoil/xfoil-1.1.1-cp313-cp313-win_amd64.whl "
                "— see vendor/xfoil/README.md. Falling back to backend='neuralfoil' "
                "is always available."
            )

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

        return match.group(1)

    def _evaluate_neuralfoil(
        self, naca_designation: str, digits: str, alpha_deg: float, reynolds: float
    ) -> AeroResult:
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

        return AeroResult(
            cl=cl,
            cd=cd,
            cm=cm,
            l_over_d=cl / cd if cd != 0 else 0.0,
            confidence=confidence,
            backend="neuralfoil",
        )

    def _evaluate_xfoil(
        self, naca_designation: str, digits: str, alpha_deg: float, reynolds: float
    ) -> AeroResult:
        xf = _XFoil()
        try:
            xf.print = False
            xf.naca(digits)
            xf.Re = float(reynolds)
            xf.max_iter = 100
            cl, cd, cm, _cp = xf.a(float(alpha_deg))
        except Exception as exc:
            raise AerodynamicsEvaluationError(
                f"XFOIL evaluation failed for '{naca_designation}' at alpha={alpha_deg}, Re={reynolds}: {exc}"
            ) from exc
        finally:
            del xf

        if cl is None or math.isnan(cl) or math.isnan(cd) or math.isnan(cm):
            raise AerodynamicsEvaluationError(
                f"XFOIL did not converge for '{naca_designation}' at alpha={alpha_deg}, "
                f"Re={reynolds} (often means post-stall or too few iterations)."
            )

        return AeroResult(
            cl=float(cl),
            cd=float(cd),
            cm=float(cm),
            l_over_d=float(cl) / float(cd) if cd != 0 else 0.0,
            confidence=1.0,
            backend="xfoil",
        )
