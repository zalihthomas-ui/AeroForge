"""Structures Agent: cantilever beam FEA via real CalculiX (ccx.exe).

Not a surrogate — this drives the genuine CalculiX FEA solver (B31
Timoshenko beam elements) via subprocess, the same way agents/aerodynamics
drives real XFOIL. See vendor/calculix/README.md for the full install and
validation story.

Critical gotcha (see vendor/calculix/README.md): this MSYS2 build of
CalculiX (2.23) hangs indefinitely on this machine when its default sparse
solver (PaStiX) is used. Every generated .inp deck's *STATIC card must
therefore say `*STATIC, SOLVER=SPOOLES` explicitly — never emit a bare
*STATIC card. As defense in depth in case some other input triggers a
similar hang, ccx.exe is also always run with an explicit subprocess
timeout.

CalculiX is not vendored (unlike xfoil): ccx.exe depends on a large stack
of MSYS2 runtime DLLs. It's located at runtime via `shutil.which("ccx")`,
falling back to the default MSYS2 install location.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass

_DEFAULT_CCX_PATH = r"C:\msys64\mingw64\bin\ccx.exe"
_CCX_TIMEOUT_S = 30
_JOBNAME = "beam"


class StructuresEvaluationError(Exception):
    """Raised when structural FEA evaluation fails due to invalid inputs or solver error."""

    pass


@dataclass
class StructuralResult:
    """Result of a cantilever beam FEA evaluation, with closed-form comparison."""

    tip_deflection_mm: float
    max_bending_stress_mpa: float
    analytical_deflection_mm: float
    deflection_error_pct: float


def _find_ccx_path() -> str | None:
    path = shutil.which("ccx")
    if path:
        return path
    if os.path.isfile(_DEFAULT_CCX_PATH):
        return _DEFAULT_CCX_PATH
    return None


CALCULIX_AVAILABLE = _find_ccx_path() is not None


class StructuresAgent:
    """Evaluates a fixed-free cantilever beam under a transverse tip load via CalculiX."""

    def evaluate_cantilever_beam(
        self,
        length_mm: float,
        width_mm: float,
        height_mm: float,
        force_n: float,
        youngs_modulus_mpa: float = 210000.0,
        poissons_ratio: float = 0.3,
        num_elements: int = 10,
    ) -> StructuralResult:
        """Evaluate a cantilever beam (fixed at one end, transverse tip load at
        the other) using CalculiX B31 beam elements.

        Args:
            length_mm: Beam length along global X (mm). Must be positive.
            width_mm: Cross-section dimension along global Z (mm, RECT
                section's first parameter). Must be positive.
            height_mm: Cross-section dimension along global Y (mm, RECT
                section's second parameter) — the bending-direction height
                for a tip load applied in global Y. Must be positive.
            force_n: Transverse tip load in global Y (N). Must be positive.
            youngs_modulus_mpa: Young's modulus (MPa = N/mm^2). Must be positive.
            poissons_ratio: Poisson's ratio.
            num_elements: Number of B31 elements along the beam. Must be >= 1.

        Returns:
            StructuralResult with FEA tip deflection/stress plus a
            closed-form Euler-Bernoulli comparison.

        Raises:
            StructuresEvaluationError: If inputs are invalid, ccx.exe cannot
                be located, the solve fails or times out, or the output
                can't be parsed.
        """
        self._validate_inputs(length_mm, width_mm, height_mm, force_n, youngs_modulus_mpa, num_elements)

        ccx_path = _find_ccx_path()
        if ccx_path is None:
            raise StructuresEvaluationError(
                "ccx.exe (CalculiX) not found on PATH or at the default MSYS2 "
                f"install location ({_DEFAULT_CCX_PATH}). Install it via "
                "scripts/install_calculix_windows.sh — see vendor/calculix/README.md."
            )

        with tempfile.TemporaryDirectory(prefix="aeroforge_ccx_") as work_dir:
            inp_path = os.path.join(work_dir, f"{_JOBNAME}.inp")
            with open(inp_path, "w", encoding="ascii") as f:
                f.write(
                    self._build_input_deck(
                        length_mm, width_mm, height_mm, force_n, youngs_modulus_mpa, poissons_ratio, num_elements
                    )
                )

            self._run_ccx(ccx_path, work_dir)

            dat_path = os.path.join(work_dir, f"{_JOBNAME}.dat")
            if not os.path.isfile(dat_path):
                raise StructuresEvaluationError(
                    f"ccx.exe finished but produced no {_JOBNAME}.dat output file — "
                    "the solve likely failed. Check the generated .inp for errors."
                )

            with open(dat_path, encoding="latin-1") as f:
                dat_text = f.read()

        tip_node = num_elements + 1
        tip_vy_mm, max_abs_sxx_mpa = self._parse_dat_file(dat_text, tip_node)
        tip_deflection_mm = abs(tip_vy_mm)

        moment_of_inertia_mm4 = width_mm * height_mm**3 / 12
        analytical_deflection_mm = (force_n * length_mm**3) / (3 * youngs_modulus_mpa * moment_of_inertia_mm4)
        deflection_error_pct = abs(tip_deflection_mm - analytical_deflection_mm) / analytical_deflection_mm * 100

        return StructuralResult(
            tip_deflection_mm=tip_deflection_mm,
            max_bending_stress_mpa=max_abs_sxx_mpa,
            analytical_deflection_mm=analytical_deflection_mm,
            deflection_error_pct=deflection_error_pct,
        )

    def _validate_inputs(
        self,
        length_mm: float,
        width_mm: float,
        height_mm: float,
        force_n: float,
        youngs_modulus_mpa: float,
        num_elements: int,
    ) -> None:
        for name, value in (
            ("length_mm", length_mm),
            ("width_mm", width_mm),
            ("height_mm", height_mm),
            ("force_n", force_n),
            ("youngs_modulus_mpa", youngs_modulus_mpa),
        ):
            if value <= 0:
                raise StructuresEvaluationError(f"'{name}' must be strictly positive, got {value}.")

        if num_elements < 1 or num_elements != int(num_elements):
            raise StructuresEvaluationError(
                f"'num_elements' must be a positive integer, got {num_elements!r}."
            )

    def _build_input_deck(
        self,
        length_mm: float,
        width_mm: float,
        height_mm: float,
        force_n: float,
        youngs_modulus_mpa: float,
        poissons_ratio: float,
        num_elements: int,
    ) -> str:
        num_nodes = num_elements + 1
        tip_node = num_nodes

        node_lines = [
            f"{i + 1}, {i * length_mm / num_elements:.6f}, 0.0, 0.0" for i in range(num_nodes)
        ]
        element_lines = [f"{i + 1}, {i + 1}, {i + 2}" for i in range(num_elements)]

        return "\n".join(
            [
                "*NODE",
                *node_lines,
                "*NSET, NSET=NALL, GENERATE",
                f"1, {num_nodes}, 1",
                "*ELEMENT, TYPE=B31, ELSET=BEAM",
                *element_lines,
                "*BEAM SECTION, ELSET=BEAM, MATERIAL=STEEL, SECTION=RECT",
                f"{width_mm:.6f}, {height_mm:.6f}",
                "0.0, 0.0, 1.0",
                "*MATERIAL, NAME=STEEL",
                "*ELASTIC",
                f"{youngs_modulus_mpa:.6f}, {poissons_ratio:.6f}",
                "*BOUNDARY",
                "1, 1, 6",
                "*STEP",
                "*STATIC, SOLVER=SPOOLES",
                "*CLOAD",
                f"{tip_node}, 2, {-force_n:.6f}",
                "*NODE PRINT, NSET=NALL",
                "U",
                "*EL PRINT, ELSET=BEAM",
                "S",
                "*END STEP",
                "",
            ]
        )

    def _run_ccx(self, ccx_path: str, work_dir: str) -> None:
        env = os.environ.copy()
        env["PATH"] = os.path.dirname(ccx_path) + os.pathsep + env.get("PATH", "")

        try:
            subprocess.run(
                [ccx_path, _JOBNAME],
                cwd=work_dir,
                env=env,
                timeout=_CCX_TIMEOUT_S,
                capture_output=True,
                text=True,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise StructuresEvaluationError(
                f"ccx.exe did not finish within {_CCX_TIMEOUT_S}s. This should not "
                "happen if the generated .inp deck's *STATIC card specifies "
                "SOLVER=SPOOLES — the bundled PaStiX default solver hangs "
                "indefinitely on this machine. See vendor/calculix/README.md."
            ) from exc

    def _parse_dat_file(self, dat_text: str, tip_node: int) -> tuple[float, float]:
        lines = dat_text.splitlines()
        tip_vy_mm: float | None = None
        max_abs_sxx_mpa: float | None = None

        i = 0
        while i < len(lines):
            line = lines[i]
            if "displacements (vx,vy,vz)" in line:
                i += 1
                while i < len(lines) and not lines[i].strip():
                    i += 1  # skip the blank separator line before the data rows
                while i < len(lines) and lines[i].strip():
                    parts = lines[i].split()
                    if len(parts) == 4:
                        try:
                            node_id = int(parts[0])
                        except ValueError:
                            i += 1
                            continue
                        if node_id == tip_node:
                            tip_vy_mm = float(parts[2])
                    i += 1
                continue
            if "stresses (elem, integ.pnt.,sxx" in line:
                i += 1
                while i < len(lines) and not lines[i].strip():
                    i += 1  # skip the blank separator line before the data rows
                while i < len(lines) and lines[i].strip():
                    parts = lines[i].split()
                    if len(parts) == 8:
                        sxx = float(parts[2])
                        if max_abs_sxx_mpa is None or abs(sxx) > max_abs_sxx_mpa:
                            max_abs_sxx_mpa = abs(sxx)
                    i += 1
                continue
            i += 1

        if tip_vy_mm is None:
            raise StructuresEvaluationError(
                f"Could not find tip node {tip_node}'s displacement in ccx output "
                f"({_JOBNAME}.dat) — the solve may have failed silently."
            )
        if max_abs_sxx_mpa is None:
            raise StructuresEvaluationError(
                f"Could not find stress output in ccx output ({_JOBNAME}.dat) — "
                "the solve may have failed silently."
            )

        return tip_vy_mm, max_abs_sxx_mpa
