"""V6 engine, start to end: geometry -> cycle -> full-load map -> crank dynamics -> balance -> con rod.

    python examples/engine/simulate.py [--out artifacts/engine]

Prints a report and writes engine_report.json (every number the video and
README quote). The CAD of the same EngineSpec is built by examples/engine/cad.py.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from agents.powertrain.spec import EngineSpec
from engineering.analysis.engine_conrod import (
    ISection,
    check_rod,
    size_rod,
    worst_case_rod_loads,
)
from engineering.analysis.engine_cycle import (
    full_load_map,
    otto_efficiency,
    run_cycle_mbt,
)
from engineering.analysis.engine_dynamics import (
    crank_torque,
    flywheel_inertia_kgm2,
    shaking,
)

REDLINE_RPM = 7000.0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=os.path.join("artifacts", "engine"))
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    spec = EngineSpec()
    print(f"V6 60 deg split-pin: {spec.displacement_l:.3f} L, bore {spec.bore_mm} x stroke {spec.stroke_mm} mm, "
          f"rod {spec.rod_length_mm} mm (lambda {spec.rod_ratio:.3f}), CR {spec.compression_ratio}")
    for c in spec.cylinders:
        print(f"  cyl {c.number} bank {c.bank}  pin {c.pin_angle_deg:5.1f} deg  z {c.z_mm:5.1f} mm  "
              f"fires at {c.firing_angle_deg:5.1f} deg")

    emap = full_load_map(spec)
    t_pk, n_t = emap.peak_torque
    p_pk, n_p = emap.peak_power
    print(f"\nFull load (MBT spark): peak torque {t_pk:.1f} N m @ {n_t:.0f} rpm, "
          f"peak power {p_pk:.1f} kW @ {n_p:.0f} rpm")
    print(f"  Otto reference (gamma 1.3) {otto_efficiency(spec.compression_ratio, 1.3):.3f}; "
          f"model gross indicated efficiency {emap.indicated_efficiency.min():.3f}-{emap.indicated_efficiency.max():.3f}")

    cyc = run_cycle_mbt(spec, n_t)
    torque = crank_torque(spec, cyc)
    print(f"\nAt {n_t:.0f} rpm: peak pressure {cyc.p_max_pa / 1e5:.1f} bar at {cyc.theta_p_max_deg:.1f} deg ATDC, "
          f"spark {cyc.spark_deg:.1f} deg, wall loss {cyc.wall_heat_loss_j / cyc.heat_released_j:.1%} of fuel energy")
    print(f"  crank torque {torque.total_nm.min():.0f} .. {torque.total_nm.max():.0f} N m "
          f"(mean {torque.mean_nm:.1f}, brake {torque.brake_mean_nm:.1f})")

    bal = shaking(spec, 6000.0)
    print(f"\nBalance @ 6000 rpm (reciprocating masses): forces 1st {bal.force_order_n[1]:.2e} N, "
          f"2nd {bal.force_order_n[2]:.2e} N; couples 1st {bal.moment_order_nm[1]:.0f} N m, "
          f"2nd {bal.moment_order_nm[2]:.0f} N m")

    idle = crank_torque(spec, run_cycle_mbt(spec, 1000.0))
    fly = {cs: flywheel_inertia_kgm2(idle, cs)[0] for cs in (0.02, 0.05, 0.1)}
    print("Flywheel inertia @ 1000 rpm full load: " + ", ".join(f"Cs {k}: {v:.3f} kg m^2" for k, v in fly.items()))

    loads = worst_case_rod_loads(spec, emap, REDLINE_RPM)
    base = check_rod(spec, ISection(), loads)
    sized, k = size_rod(spec, ISection(), loads)
    print(f"\nCon rod: compression {loads.compression_n / 1e3:.1f} kN @ {loads.compression_rpm:.0f} rpm, "
          f"tension {loads.tension_n / 1e3:.1f} kN @ {loads.tension_rpm:.0f} rpm")
    print(f"  initial section: buckling SF {base.buckling_sf:.2f}, fatigue SF {base.fatigue_sf:.2f}")
    print(f"  sized (x{k:.3f}): buckling SF {sized.buckling_sf:.2f}, fatigue SF {sized.fatigue_sf:.2f}, "
          f"shank {sized.shank_mass_kg * 1000:.0f} g")

    report = {
        "spec": {"displacement_l": spec.displacement_l, "bore_mm": spec.bore_mm, "stroke_mm": spec.stroke_mm,
                 "rod_mm": spec.rod_length_mm, "compression_ratio": spec.compression_ratio,
                 "cylinders": [c.__dict__ for c in spec.cylinders]},
        "map": {k2: np.asarray(v).tolist() for k2, v in emap.__dict__.items()},
        "peak_torque": {"nm": t_pk, "rpm": n_t}, "peak_power": {"kw": p_pk, "rpm": n_p},
        "cycle_at_peak_torque": {"theta_deg": cyc.theta_deg[::4].tolist(), "pressure_bar": (cyc.pressure_pa[::4] / 1e5).tolist(),
                                 "volume_l": (cyc.volume_m3[::4] * 1000).tolist(), "p_max_bar": cyc.p_max_pa / 1e5,
                                 "theta_p_max_deg": cyc.theta_p_max_deg, "spark_deg": cyc.spark_deg,
                                 "wall_loss_fraction": cyc.wall_heat_loss_j / cyc.heat_released_j},
        "crank_torque": {"theta_deg": torque.theta_deg[::4].tolist(), "total_nm": torque.total_nm[::4].tolist(),
                         "per_cylinder_nm": torque.per_cylinder_nm[:, ::4].tolist(), "mean_nm": torque.mean_nm},
        "balance_6000": {"force_orders_n": bal.force_order_n, "moment_orders_nm": bal.moment_order_nm},
        "flywheel_kgm2": fly,
        "conrod": {"compression_kn": loads.compression_n / 1e3, "tension_kn": loads.tension_n / 1e3,
                   "base": {"buckling_sf": base.buckling_sf, "fatigue_sf": base.fatigue_sf},
                   "sized": {"scale": k, "buckling_sf": sized.buckling_sf, "fatigue_sf": sized.fatigue_sf,
                             "shank_mass_g": sized.shank_mass_kg * 1000}},
        "otto_efficiency_gamma_1_3": otto_efficiency(spec.compression_ratio, 1.3),
        "redline_rpm": REDLINE_RPM, "omega_redline": REDLINE_RPM * 2 * math.pi / 60,
    }
    path = os.path.join(args.out, "engine_report.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    print(f"\nreport: {path}")


if __name__ == "__main__":
    main()
