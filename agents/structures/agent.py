"""Structures Agent: real FEA via CalculiX (ccx.exe), two ways.

Not a surrogate — this drives the genuine CalculiX FEA solver via
subprocess, the same way agents/aerodynamics drives real XFOIL:

- `evaluate_cantilever_beam`: 1D B31 Timoshenko beam elements on a
  parametric beam, validated against closed-form Euler-Bernoulli theory
  (~0.3% error on the reference case — see vendor/calculix/README.md).
- `evaluate_plate_with_hole`: real 3D solid FEA on actual meshed CAD
  geometry (gmsh C3D10 quadratic tets on a build123d plate-with-hole,
  see agents/structures/plate_with_hole.py), validated against Kirsch's
  classical stress-concentration solution (Kt=3.0 for a small hole in a
  wide plate under tension). Observed error on the reference case
  (200x200x5mm plate, 10mm hole): ~0.4%; across hole diameters from 3% to
  8% of plate width: within ~2%.
- `evaluate_bracket`: real 3D solid FEA on the ACTUAL Geometry Agent
  bracket component (agents/geometry/bracket.py's `build_bracket`, not a
  dedicated fixture), bolted at all 4 holes and transversely loaded on
  its top face. There's no closed-form solution for this case, so it's
  validated two ways instead: (1) exact force equilibrium — sum of
  reaction forces at the fixed nodes must equal the applied load, a
  mathematical identity for any correctly converged linear static solve,
  regardless of geometry complexity (observed: ~0.001-0.08% error); and
  (2) mesh convergence — solved at two mesh densities, max stress and max
  deflection compared between them (observed on the reference case:
  ~0.8% deflection change, ~3% stress change between the shipped
  densities — see agents/structures/bracket_mesh.py's module docstring
  for the convergence sweep this was picked from, including a real,
  reported peak-stress non-monotonicity at coarser densities consistent
  with the fixed-hole-rim edge being a classic FEA stress-singularity
  location, not fully eliminated by 2 mesh points).

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

from agents.geometry.validation import GeometryValidationError, validate_bracket_parameters
from agents.geometry.bracket import build_bracket
from agents.structures.bracket_mesh import BracketMesh, mesh_bracket
from agents.structures.inp_utils import format_nset_lines
from agents.structures.plate_with_hole import PlateMesh, build_plate_with_hole, mesh_plate_with_hole
from cad.exporters import export_step

_DEFAULT_CCX_PATH = r"C:\msys64\mingw64\bin\ccx.exe"
_BEAM_CCX_TIMEOUT_S = 30
_BEAM_JOBNAME = "beam"

# 3D solid meshes solve much slower than the 1D beam case (a few tens of
# seconds observed for a few thousand C3D10 elements) — generous margin for
# slower machines, while still bounding a hang.
_PLATE_CCX_TIMEOUT_S = 180
_PLATE_JOBNAME = "plate"

# Kirsch (1898): stress concentration factor at the edge of a small circular
# hole in a wide plate under uniaxial tension, in the infinite-plate limit.
_KIRSCH_KT = 3.0

# Kirsch's Kt=3.0 only holds as the hole becomes small relative to plate
# width; beyond this ratio it needs a finite-width correction this agent
# doesn't implement, so it's rejected rather than silently validated against
# the wrong target.
_MAX_HOLE_TO_WIDTH_RATIO = 0.1

_BRACKET_CCX_TIMEOUT_S = 180
_BRACKET_JOBNAME = "bracket"

# The two mesh densities compared for evaluate_bracket's convergence check
# (see agents/structures/bracket_mesh.py's mesh_bracket `density_factor` —
# smaller means finer). Picked from an actual convergence sweep (2.0 down
# to 0.8) where deflection converged smoothly but peak stress did not
# monotonically settle until around this pair — see bracket_mesh.py's
# module docstring for the full sweep.
_BRACKET_COARSE_DENSITY_FACTOR = 1.0
_BRACKET_FINE_DENSITY_FACTOR = 0.9

# How much max_stress/max_deflection may differ between the coarse and fine
# meshes to be considered converged — standard FEA verification practice
# when no closed-form answer exists to validate against directly.
_MESH_CONVERGENCE_TOLERANCE_PCT = 10.0


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


@dataclass
class PlateWithHoleResult:
    """Result of a plate-with-hole FEA evaluation, vs. Kirsch's closed-form
    stress concentration solution."""

    max_stress_mpa: float
    nominal_stress_mpa: float
    stress_concentration_factor: float
    theoretical_kt: float
    error_pct: float


@dataclass
class BracketStructuralResult:
    """Result of a mounting-bracket FEA evaluation (bolted at all 4 holes,
    transversely loaded on the top face), validated via force equilibrium
    and mesh convergence rather than a closed-form solution."""

    max_stress_mpa: float
    max_deflection_mm: float
    equilibrium_error_pct: float
    mesh_converged: bool
    coarse_mesh_max_stress_mpa: float
    fine_mesh_max_stress_mpa: float


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

        with tempfile.TemporaryDirectory(prefix="aeroforge_ccx_beam_") as work_dir:
            inp_path = os.path.join(work_dir, f"{_BEAM_JOBNAME}.inp")
            with open(inp_path, "w", encoding="ascii") as f:
                f.write(
                    self._build_input_deck(
                        length_mm, width_mm, height_mm, force_n, youngs_modulus_mpa, poissons_ratio, num_elements
                    )
                )

            self._run_ccx(ccx_path, work_dir, jobname=_BEAM_JOBNAME, timeout=_BEAM_CCX_TIMEOUT_S)

            dat_text = self._read_dat_file(work_dir, _BEAM_JOBNAME)

        tip_node = num_elements + 1
        tip_vy_mm = self._parse_node_displacement(dat_text, tip_node, jobname=_BEAM_JOBNAME)
        max_abs_sxx_mpa = self._parse_max_abs_sxx(dat_text, jobname=_BEAM_JOBNAME)
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

    def evaluate_plate_with_hole(
        self,
        width_mm: float,
        height_mm: float,
        thickness_mm: float,
        hole_diameter_mm: float,
        tensile_stress_mpa: float,
        youngs_modulus_mpa: float = 210000.0,
        poissons_ratio: float = 0.3,
    ) -> PlateWithHoleResult:
        """Evaluate a rectangular plate with a centered circular hole under
        uniaxial tension (fixed at X=0, loaded at X=width_mm) using real
        solid FEA: a build123d plate meshed with gmsh into quadratic
        (C3D10) tets, refined near the hole, solved by CalculiX.

        Validates against Kirsch's classical closed-form result: a small
        hole in a wide plate under remote uniaxial tension has a stress
        concentration factor of exactly 3.0 at the hole edge perpendicular
        to loading, in the small-hole/infinite-plate limit.

        Args:
            width_mm: Plate dimension along the loading direction (X). Must
                be positive.
            height_mm: Plate dimension transverse to loading (Y). Must be
                positive.
            thickness_mm: Plate thickness (Z). Must be positive.
            hole_diameter_mm: Diameter of the centered hole. Must be
                positive and at most `_MAX_HOLE_TO_WIDTH_RATIO * width_mm`
                — Kirsch's Kt=3.0 requires the small-hole/infinite-plate
                approximation; a larger hole needs a finite-width
                correction this agent doesn't implement.
            tensile_stress_mpa: Remote/nominal applied tensile stress
                (MPa), applied as a statically-equivalent distributed
                nodal load on the X=width_mm face. Must be positive.
            youngs_modulus_mpa: Young's modulus (MPa). Must be positive.
            poissons_ratio: Poisson's ratio.

        Returns:
            PlateWithHoleResult with the FEA stress concentration factor
            and its error against Kirsch's theoretical Kt=3.0.

        Raises:
            StructuresEvaluationError: If inputs are invalid, ccx.exe
                cannot be located, meshing/solving fails or times out, or
                the output can't be parsed.
        """
        self._validate_plate_inputs(
            width_mm, height_mm, thickness_mm, hole_diameter_mm, tensile_stress_mpa, youngs_modulus_mpa
        )

        ccx_path = _find_ccx_path()
        if ccx_path is None:
            raise StructuresEvaluationError(
                "ccx.exe (CalculiX) not found on PATH or at the default MSYS2 "
                f"install location ({_DEFAULT_CCX_PATH}). Install it via "
                "scripts/install_calculix_windows.sh — see vendor/calculix/README.md."
            )

        with tempfile.TemporaryDirectory(prefix="aeroforge_ccx_plate_") as work_dir:
            step_path = os.path.join(work_dir, f"{_PLATE_JOBNAME}.step")
            plate = build_plate_with_hole(width_mm, height_mm, thickness_mm, hole_diameter_mm)
            export_step(plate, step_path)

            mesh = mesh_plate_with_hole(step_path, width_mm, height_mm, thickness_mm, hole_diameter_mm)

            inp_path = os.path.join(work_dir, f"{_PLATE_JOBNAME}.inp")
            with open(inp_path, "w", encoding="ascii") as f:
                f.write(
                    self._build_plate_input_deck(
                        mesh, youngs_modulus_mpa, poissons_ratio, tensile_stress_mpa, height_mm, thickness_mm
                    )
                )

            self._run_ccx(ccx_path, work_dir, jobname=_PLATE_JOBNAME, timeout=_PLATE_CCX_TIMEOUT_S)

            dat_text = self._read_dat_file(work_dir, _PLATE_JOBNAME)

        max_abs_sxx_mpa = self._parse_max_abs_sxx(dat_text, jobname=_PLATE_JOBNAME)

        nominal_stress_mpa = tensile_stress_mpa
        kt = max_abs_sxx_mpa / nominal_stress_mpa
        error_pct = abs(kt - _KIRSCH_KT) / _KIRSCH_KT * 100

        return PlateWithHoleResult(
            max_stress_mpa=max_abs_sxx_mpa,
            nominal_stress_mpa=nominal_stress_mpa,
            stress_concentration_factor=kt,
            theoretical_kt=_KIRSCH_KT,
            error_pct=error_pct,
        )

    def _validate_plate_inputs(
        self,
        width_mm: float,
        height_mm: float,
        thickness_mm: float,
        hole_diameter_mm: float,
        tensile_stress_mpa: float,
        youngs_modulus_mpa: float,
    ) -> None:
        for name, value in (
            ("width_mm", width_mm),
            ("height_mm", height_mm),
            ("thickness_mm", thickness_mm),
            ("hole_diameter_mm", hole_diameter_mm),
            ("tensile_stress_mpa", tensile_stress_mpa),
            ("youngs_modulus_mpa", youngs_modulus_mpa),
        ):
            if value <= 0:
                raise StructuresEvaluationError(f"'{name}' must be strictly positive, got {value}.")

        max_hole_diameter = _MAX_HOLE_TO_WIDTH_RATIO * width_mm
        if hole_diameter_mm > max_hole_diameter:
            raise StructuresEvaluationError(
                f"hole_diameter_mm ({hole_diameter_mm} mm) is too large relative to width_mm "
                f"({width_mm} mm) for Kirsch's stress concentration solution: it requires the "
                f"small-hole/infinite-plate approximation, valid here only for hole_diameter_mm "
                f"<= {_MAX_HOLE_TO_WIDTH_RATIO} * width_mm ({max_hole_diameter} mm). A larger "
                "hole would need a finite-width correction factor this agent doesn't implement — "
                "it isn't the same validation target, so it's rejected rather than silently "
                "compared against the wrong theoretical Kt."
            )

    def _build_plate_input_deck(
        self,
        mesh: PlateMesh,
        youngs_modulus_mpa: float,
        poissons_ratio: float,
        tensile_stress_mpa: float,
        height_mm: float,
        thickness_mm: float,
    ) -> str:
        total_force_n = tensile_stress_mpa * height_mm * thickness_mm
        force_per_node_n = total_force_n / len(mesh.loaded_node_ids)

        boundary_lines = [f"{node_id}, 1, 1" for node_id in mesh.fixed_node_ids]
        # Minimal extra constraints to remove rigid-body motion without
        # over-constraining: one node's Y/Z translation, plus a second
        # node's Z to remove the remaining X-axis rotation (see
        # plate_with_hole.py's mesh_plate_with_hole for how these are
        # picked). The whole-face UX=0 above already blocks rotation about
        # Y and Z, so only 3 more DOFs (Y-trans, Z-trans, X-rotation) need
        # pinning.
        boundary_lines.append(f"{mesh.center_node_id}, 2, 3")
        boundary_lines.append(f"{mesh.offset_node_id}, 3, 3")

        cload_lines = [f"{node_id}, 1, {force_per_node_n:.6f}" for node_id in mesh.loaded_node_ids]

        return "\n".join(
            [
                "*NODE",
                *mesh.node_lines,
                "*NSET, NSET=NALL, GENERATE",
                f"1, {mesh.max_node_id}, 1",
                "*ELEMENT, TYPE=C3D10, ELSET=VOL",
                *mesh.element_lines,
                "*SOLID SECTION, ELSET=VOL, MATERIAL=STEEL",
                "*MATERIAL, NAME=STEEL",
                "*ELASTIC",
                f"{youngs_modulus_mpa:.6f}, {poissons_ratio:.6f}",
                "*BOUNDARY",
                *boundary_lines,
                "*STEP",
                "*STATIC, SOLVER=SPOOLES",
                "*CLOAD",
                *cload_lines,
                "*NODE PRINT, NSET=NALL",
                "U",
                "*EL PRINT, ELSET=VOL",
                "S",
                "*END STEP",
                "",
            ]
        )

    def evaluate_bracket(
        self,
        length_mm: float,
        width_mm: float,
        thickness_mm: float,
        hole_diameter_mm: float,
        hole_count: int,
        applied_force_n: float,
        youngs_modulus_mpa: float = 210000.0,
        poissons_ratio: float = 0.3,
    ) -> BracketStructuralResult:
        """Evaluate the actual Geometry Agent bracket component
        (agents/geometry/bracket.py's `build_bracket`) under a real
        "bolted mounting bracket" load case: all 4 holes rigidly fixed
        (bolted), a distributed transverse load on the top face.

        There's no closed-form solution for this case (unlike the beam or
        plate-with-hole), so it's validated two ways instead:

        - Force equilibrium (exact, primary check): the sum of reaction
          forces at the fixed nodes must equal the applied load — a
          mathematical identity for any correctly converged linear static
          solve, regardless of geometry complexity.
        - Mesh convergence (secondary check): solved at two mesh
          densities; `mesh_converged` is True only if both max stress and
          max deflection change by less than
          `_MESH_CONVERGENCE_TOLERANCE_PCT` between them. See
          agents/structures/bracket_mesh.py's module docstring for why
          this doesn't always converge (a likely stress singularity at
          the fixed-hole-rim edge) and isn't forced to.

        Args:
            length_mm, width_mm, thickness_mm, hole_diameter_mm,
                hole_count: Same parameters and constraints as
                agents/geometry/bracket.py's build_bracket (validated with
                the same agents/geometry/validation.validate_bracket_parameters).
            applied_force_n: Total transverse load on the top face,
                pressing in -Z, distributed evenly across its (non-fixed)
                nodes. Must be positive.
            youngs_modulus_mpa: Young's modulus (MPa). Must be positive.
            poissons_ratio: Poisson's ratio.

        Returns:
            BracketStructuralResult with the fine-mesh max stress/
            deflection, the equilibrium check, and the convergence check.

        Raises:
            StructuresEvaluationError: If inputs are invalid, ccx.exe
                cannot be located, meshing/solving fails or times out, or
                the output can't be parsed.
        """
        self._validate_bracket_inputs(
            length_mm, width_mm, thickness_mm, hole_diameter_mm, hole_count, applied_force_n, youngs_modulus_mpa
        )

        ccx_path = _find_ccx_path()
        if ccx_path is None:
            raise StructuresEvaluationError(
                "ccx.exe (CalculiX) not found on PATH or at the default MSYS2 "
                f"install location ({_DEFAULT_CCX_PATH}). Install it via "
                "scripts/install_calculix_windows.sh — see vendor/calculix/README.md."
            )

        coarse_max_stress, coarse_max_defl, _ = self._solve_bracket(
            ccx_path, length_mm, width_mm, thickness_mm, hole_diameter_mm, hole_count,
            applied_force_n, youngs_modulus_mpa, poissons_ratio, _BRACKET_COARSE_DENSITY_FACTOR, "coarse",
        )
        fine_max_stress, fine_max_defl, equilibrium_error_pct = self._solve_bracket(
            ccx_path, length_mm, width_mm, thickness_mm, hole_diameter_mm, hole_count,
            applied_force_n, youngs_modulus_mpa, poissons_ratio, _BRACKET_FINE_DENSITY_FACTOR, "fine",
        )

        stress_change_pct = abs(fine_max_stress - coarse_max_stress) / fine_max_stress * 100
        defl_change_pct = abs(fine_max_defl - coarse_max_defl) / fine_max_defl * 100
        mesh_converged = (
            stress_change_pct < _MESH_CONVERGENCE_TOLERANCE_PCT
            and defl_change_pct < _MESH_CONVERGENCE_TOLERANCE_PCT
        )

        return BracketStructuralResult(
            max_stress_mpa=fine_max_stress,
            max_deflection_mm=fine_max_defl,
            equilibrium_error_pct=equilibrium_error_pct,
            mesh_converged=mesh_converged,
            coarse_mesh_max_stress_mpa=coarse_max_stress,
            fine_mesh_max_stress_mpa=fine_max_stress,
        )

    def _solve_bracket(
        self,
        ccx_path: str,
        length_mm: float,
        width_mm: float,
        thickness_mm: float,
        hole_diameter_mm: float,
        hole_count: int,
        applied_force_n: float,
        youngs_modulus_mpa: float,
        poissons_ratio: float,
        density_factor: float,
        tag: str,
    ) -> tuple[float, float, float]:
        """Mesh, solve, and parse one bracket density. Returns
        (max_von_mises_stress_mpa, max_deflection_mm, equilibrium_error_pct)."""
        jobname = f"{_BRACKET_JOBNAME}_{tag}"
        with tempfile.TemporaryDirectory(prefix=f"aeroforge_ccx_bracket_{tag}_") as work_dir:
            step_path = os.path.join(work_dir, f"{jobname}.step")
            part = build_bracket(
                {
                    "length": length_mm,
                    "width": width_mm,
                    "thickness": thickness_mm,
                    "hole_diameter": hole_diameter_mm,
                    "hole_count": hole_count,
                }
            )
            export_step(part, step_path)

            mesh = mesh_bracket(
                step_path, length_mm, width_mm, thickness_mm, hole_diameter_mm, hole_count, density_factor
            )

            inp_path = os.path.join(work_dir, f"{jobname}.inp")
            with open(inp_path, "w", encoding="ascii") as f:
                f.write(self._build_bracket_input_deck(mesh, youngs_modulus_mpa, poissons_ratio, applied_force_n))

            self._run_ccx(ccx_path, work_dir, jobname=jobname, timeout=_BRACKET_CCX_TIMEOUT_S)

            dat_text = self._read_dat_file(work_dir, jobname)

        max_deflection_mm = self._parse_max_displacement_magnitude(dat_text, jobname=jobname)
        max_stress_mpa = self._parse_max_von_mises(dat_text, jobname=jobname)
        reaction_force_z = self._parse_reaction_force_sum(dat_text, direction_index=3, jobname=jobname)
        equilibrium_error_pct = abs(reaction_force_z - applied_force_n) / applied_force_n * 100

        return max_stress_mpa, max_deflection_mm, equilibrium_error_pct

    def _validate_bracket_inputs(
        self,
        length_mm: float,
        width_mm: float,
        thickness_mm: float,
        hole_diameter_mm: float,
        hole_count: int,
        applied_force_n: float,
        youngs_modulus_mpa: float,
    ) -> None:
        try:
            validate_bracket_parameters(length_mm, width_mm, thickness_mm, hole_diameter_mm, hole_count)
        except GeometryValidationError as exc:
            raise StructuresEvaluationError(str(exc)) from exc

        for name, value in (
            ("applied_force_n", applied_force_n),
            ("youngs_modulus_mpa", youngs_modulus_mpa),
        ):
            if value <= 0:
                raise StructuresEvaluationError(f"'{name}' must be strictly positive, got {value}.")

    def _build_bracket_input_deck(
        self,
        mesh: BracketMesh,
        youngs_modulus_mpa: float,
        poissons_ratio: float,
        applied_force_n: float,
    ) -> str:
        force_per_node_n = applied_force_n / len(mesh.loaded_node_ids)

        # All 3 translational DOFs fixed at every node on all 4 hole
        # surfaces (rigid bolted connections) — solid elements have no
        # rotational DOFs, so this is full fixity, unlike the beam/plate
        # cases which needed extra rigid-body-motion constraints.
        boundary_lines = [f"{node_id}, 1, 3" for node_id in mesh.fixed_node_ids]
        cload_lines = [f"{node_id}, 3, {-force_per_node_n:.6f}" for node_id in mesh.loaded_node_ids]

        return "\n".join(
            [
                "*NODE",
                *mesh.node_lines,
                "*NSET, NSET=NALL, GENERATE",
                f"1, {mesh.max_node_id}, 1",
                "*NSET, NSET=FIXED",
                *format_nset_lines(mesh.fixed_node_ids),
                "*ELEMENT, TYPE=C3D10, ELSET=VOL",
                *mesh.element_lines,
                "*SOLID SECTION, ELSET=VOL, MATERIAL=STEEL",
                "*MATERIAL, NAME=STEEL",
                "*ELASTIC",
                f"{youngs_modulus_mpa:.6f}, {poissons_ratio:.6f}",
                "*BOUNDARY",
                *boundary_lines,
                "*STEP",
                "*STATIC, SOLVER=SPOOLES",
                "*CLOAD",
                *cload_lines,
                "*NODE PRINT, NSET=NALL",
                "U",
                "*NODE PRINT, NSET=FIXED",
                "RF",
                "*EL PRINT, ELSET=VOL",
                "S",
                "*END STEP",
                "",
            ]
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

    def _run_ccx(self, ccx_path: str, work_dir: str, *, jobname: str, timeout: int) -> None:
        env = os.environ.copy()
        env["PATH"] = os.path.dirname(ccx_path) + os.pathsep + env.get("PATH", "")

        try:
            subprocess.run(
                [ccx_path, jobname],
                cwd=work_dir,
                env=env,
                timeout=timeout,
                capture_output=True,
                text=True,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise StructuresEvaluationError(
                f"ccx.exe did not finish within {timeout}s. This should not "
                "happen if the generated .inp deck's *STATIC card specifies "
                "SOLVER=SPOOLES — the bundled PaStiX default solver hangs "
                "indefinitely on this machine. See vendor/calculix/README.md."
            ) from exc

    def _read_dat_file(self, work_dir: str, jobname: str) -> str:
        dat_path = os.path.join(work_dir, f"{jobname}.dat")
        if not os.path.isfile(dat_path):
            raise StructuresEvaluationError(
                f"ccx.exe finished but produced no {jobname}.dat output file — "
                "the solve likely failed. Check the generated .inp for errors."
            )
        with open(dat_path, encoding="latin-1") as f:
            return f.read()

    def _parse_node_displacement(self, dat_text: str, node_id_wanted: int, *, jobname: str) -> float:
        lines = dat_text.splitlines()
        vy_mm: float | None = None

        i = 0
        while i < len(lines):
            if "displacements (vx,vy,vz)" in lines[i]:
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
                        if node_id == node_id_wanted:
                            vy_mm = float(parts[2])
                    i += 1
                continue
            i += 1

        if vy_mm is None:
            raise StructuresEvaluationError(
                f"Could not find node {node_id_wanted}'s displacement in ccx output "
                f"({jobname}.dat) — the solve may have failed silently."
            )
        return vy_mm

    def _parse_max_abs_sxx(self, dat_text: str, *, jobname: str) -> float:
        lines = dat_text.splitlines()
        max_abs_sxx_mpa: float | None = None

        i = 0
        while i < len(lines):
            if "stresses (elem, integ.pnt.,sxx" in lines[i]:
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

        if max_abs_sxx_mpa is None:
            raise StructuresEvaluationError(
                f"Could not find stress output in ccx output ({jobname}.dat) — "
                "the solve may have failed silently."
            )
        return max_abs_sxx_mpa

    def _parse_max_von_mises(self, dat_text: str, *, jobname: str) -> float:
        lines = dat_text.splitlines()
        max_vm_mpa: float | None = None

        i = 0
        while i < len(lines):
            if "stresses (elem, integ.pnt.,sxx" in lines[i]:
                i += 1
                while i < len(lines) and not lines[i].strip():
                    i += 1  # skip the blank separator line before the data rows
                while i < len(lines) and lines[i].strip():
                    parts = lines[i].split()
                    if len(parts) == 8:
                        sxx, syy, szz, sxy, sxz, syz = (float(x) for x in parts[2:8])
                        vm = (
                            0.5
                            * (
                                (sxx - syy) ** 2
                                + (syy - szz) ** 2
                                + (szz - sxx) ** 2
                                + 6 * (sxy**2 + sxz**2 + syz**2)
                            )
                        ) ** 0.5
                        if max_vm_mpa is None or vm > max_vm_mpa:
                            max_vm_mpa = vm
                    i += 1
                continue
            i += 1

        if max_vm_mpa is None:
            raise StructuresEvaluationError(
                f"Could not find stress output in ccx output ({jobname}.dat) — "
                "the solve may have failed silently."
            )
        return max_vm_mpa

    def _parse_max_displacement_magnitude(self, dat_text: str, *, jobname: str) -> float:
        lines = dat_text.splitlines()
        max_mag_mm: float | None = None

        i = 0
        while i < len(lines):
            if "displacements (vx,vy,vz)" in lines[i]:
                i += 1
                while i < len(lines) and not lines[i].strip():
                    i += 1  # skip the blank separator line before the data rows
                while i < len(lines) and lines[i].strip():
                    parts = lines[i].split()
                    if len(parts) == 4:
                        vx, vy, vz = (float(x) for x in parts[1:4])
                        mag = (vx**2 + vy**2 + vz**2) ** 0.5
                        if max_mag_mm is None or mag > max_mag_mm:
                            max_mag_mm = mag
                    i += 1
                continue
            i += 1

        if max_mag_mm is None:
            raise StructuresEvaluationError(
                f"Could not find displacement output in ccx output ({jobname}.dat) — "
                "the solve may have failed silently."
            )
        return max_mag_mm

    def _parse_reaction_force_sum(self, dat_text: str, *, direction_index: int, jobname: str) -> float:
        """Sum the reaction force component `direction_index` (1=fx, 2=fy,
        3=fz) across a `*NODE PRINT, NSET=..., RF` block."""
        lines = dat_text.splitlines()
        column = direction_index  # parts[0] is node id, parts[1:4] are fx,fy,fz
        total: float | None = None

        i = 0
        while i < len(lines):
            if "forces (fx,fy,fz)" in lines[i]:
                total = 0.0
                i += 1
                while i < len(lines) and not lines[i].strip():
                    i += 1  # skip the blank separator line before the data rows
                while i < len(lines) and lines[i].strip():
                    parts = lines[i].split()
                    if len(parts) == 4:
                        total += float(parts[column])
                    i += 1
                continue
            i += 1

        if total is None:
            raise StructuresEvaluationError(
                f"Could not find reaction force output in ccx output ({jobname}.dat) — "
                "the solve may have failed silently."
            )
        return total
