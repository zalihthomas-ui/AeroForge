"""Shared V6 engine definition: geometry, layout and firing used by analysis and CAD.

One `EngineSpec` drives the thermodynamic cycle, the crank/balance dynamics,
the connecting-rod check (engineering/analysis/engine_*.py) and the parametric
CAD (agents/powertrain/), so the model that is simulated is the model that is
drawn.

Frame and conventions (all lengths in mm unless a name says otherwise):
* Z along the crankshaft axis, from the front (timing end, z=0) to the
  flywheel; X horizontal, Y up. Crank angles are measured from +Y towards +X, so
  increasing ``theta`` is a rotation about -Z (clockwise seen from the front, +Z towards the viewer).
* Crank angle ``theta`` [deg] is the rotation of the crankshaft from the
  reference position; one 4-stroke cycle is 720 deg.
* Each cylinder axis lies in the XY plane at ``bank_angle_deg`` from vertical
  (+Y): positive = right bank (+X side), negative = left bank.
* A cylinder is at top dead centre when its crank throw points along its
  cylinder axis, i.e. when ``theta + pin_angle_deg == axis_angle_deg``
  (angles measured from +Y towards +X).

Default layout: 60 deg V6 with a split-pin crankshaft (six crank pins 60 deg
apart, three throw pairs) and even 120 deg firing, firing order 1-2-3-4-5-6.
Cylinders are numbered in firing order; odd numbers on the right bank. This
is a representative even-firing 60 deg V6 layout, not a specific production
engine.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


class EngineSpecError(ValueError):
    """Raised for an inconsistent engine definition."""


@dataclass(frozen=True)
class Cylinder:
    """One cylinder: firing order position, bank, crank-pin angle and axial position."""

    number: int  # 1-based, equals firing order position
    bank: str  # "R" or "L"
    axis_angle_deg: float  # cylinder axis from vertical (+Y), + towards +X
    pin_angle_deg: float  # crank pin angle at theta = 0, from +Y towards +X
    z_mm: float  # cylinder axis position along the crankshaft
    firing_angle_deg: float  # crank angle of this cylinder's firing TDC within the 720 deg cycle


@dataclass(frozen=True)
class EngineSpec:
    """Geometry and layout of a 4-stroke V engine (defaults: 3.0 L 60 deg V6)."""

    bore_mm: float = 89.0
    stroke_mm: float = 80.0
    rod_length_mm: float = 145.0  # centre to centre
    compression_ratio: float = 10.5
    bank_angle_deg: float = 60.0  # included angle between banks
    n_cylinders: int = 6
    bore_spacing_mm: float = 100.0  # axial distance between cylinders in one bank
    bank_offset_mm: float = 18.0  # axial stagger of the left bank (split-pin pairs share a throw)
    firing_order: tuple[int, ...] = (1, 2, 3, 4, 5, 6)
    # masses for dynamics (kg), measured from the parametric CAD (agents/powertrain/v6_cad.py:
    # part_masses_kg / rod_small_end_fraction, volume x density): piston 0.4222 + gudgeon pin 0.1359,
    # steel rod 0.4440 with its CG giving a 0.638 big-end share. They replace the initial
    # assumptions (0.55 / 0.55 / 0.67) so the dynamics run on the geometry that is drawn.
    reciprocating_mass_kg: float = 0.5581  # piston + gudgeon pin (rings not modelled)
    rod_mass_kg: float = 0.4440
    rod_big_end_fraction: float = 0.6377  # share of rod mass treated as rotating
    cylinders: tuple[Cylinder, ...] = field(default=(), compare=False)

    def __post_init__(self) -> None:
        for name in ("bore_mm", "stroke_mm", "rod_length_mm", "bore_spacing_mm"):
            if getattr(self, name) <= 0:
                raise EngineSpecError(f"{name} must be positive")
        if self.compression_ratio <= 1.0:
            raise EngineSpecError("compression_ratio must be > 1")
        if self.rod_length_mm <= self.stroke_mm / 2:
            raise EngineSpecError("rod must be longer than the crank radius")
        if self.n_cylinders != 6 or self.bank_angle_deg != 60.0:
            raise EngineSpecError("this layout generator implements the 60 deg V6 only")
        if sorted(self.firing_order) != list(range(1, 7)):
            raise EngineSpecError("firing_order must be a permutation of 1..6")
        if not self.cylinders:
            object.__setattr__(self, "cylinders", self._layout())

    # ---- derived geometry -----------------------------------------------------
    @property
    def crank_radius_mm(self) -> float:
        return self.stroke_mm / 2.0

    @property
    def piston_area_m2(self) -> float:
        return math.pi / 4.0 * (self.bore_mm / 1000.0) ** 2

    @property
    def swept_volume_per_cyl_m3(self) -> float:
        return self.piston_area_m2 * self.stroke_mm / 1000.0

    @property
    def displacement_l(self) -> float:
        return self.swept_volume_per_cyl_m3 * self.n_cylinders * 1000.0

    @property
    def clearance_volume_m3(self) -> float:
        return self.swept_volume_per_cyl_m3 / (self.compression_ratio - 1.0)

    @property
    def rod_ratio(self) -> float:
        """lambda = crank radius / rod length."""
        return self.crank_radius_mm / self.rod_length_mm

    def _layout(self) -> tuple[Cylinder, ...]:
        """Even 120 deg firing: cylinder k fires at 120 (k-1) deg; odd k on the right bank."""
        half = self.bank_angle_deg / 2.0
        cyls = []
        for k in self.firing_order:
            fire = 120.0 * (k - 1)
            bank = "R" if k % 2 == 1 else "L"
            axis = half if bank == "R" else -half
            # TDC when theta + pin == axis (mod 360); the firing TDC is at theta = fire
            pin = (axis - fire) % 360.0
            cyls.append((k, bank, axis, pin, fire))
        # throw pairs: one right + one left cylinder whose pins are 60 deg apart share a throw
        right = [c for c in cyls if c[1] == "R"]
        left = [c for c in cyls if c[1] == "L"]
        out = []
        for i, r in enumerate(sorted(right, key=lambda c: c[0])):
            # left pin 60 deg after the right pin (split-pin throw)
            partner = min(left, key=lambda c: abs(((c[3] - r[3]) % 360.0) - 60.0))
            left.remove(partner)
            z_r = i * self.bore_spacing_mm
            out.append(Cylinder(r[0], "R", r[2], r[3], z_r, r[4]))
            out.append(Cylinder(partner[0], "L", partner[2], partner[3], z_r + self.bank_offset_mm, partner[4]))
        return tuple(sorted(out, key=lambda c: c.number))

    def cylinder(self, number: int) -> Cylinder:
        return next(c for c in self.cylinders if c.number == number)
