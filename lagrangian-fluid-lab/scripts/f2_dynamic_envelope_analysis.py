#!/usr/bin/env python3
"""Estimate a finite F2 runtime envelope from native position exclusions.

This is read-only evidence analysis.  It uses the saved PartOut position and
velocity at each exclusion, constant velocity in x/y, and public gravity
``g=-9.81 m/s^2`` in z to form a conservative diagnostic envelope through the
registered 2.5 s window.  It never launches a solver or changes the product.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

import numpy as np

SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from scripts import core_cfd, core_f2, core_f2_qualification


GRAVITY_M_S2 = -9.81
DEFAULT_MARGIN_M = 0.5
DEFAULT_CELL_SIZE_M = 0.0195


def _number(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None


def _integer(value: object) -> int | None:
    number = _number(value)
    return None if number is None else int(number)


def _runparts_times(path: Path) -> dict[int, float]:
    result = {}
    with Path(path).open() as handle:
        reader = csv.DictReader(handle, delimiter=";")
        for row in reader:
            part = _integer(row.get("Part")) if row else None
            time_s = _number(row.get("TimeStep [s]")) if row else None
            if part is not None and time_s is not None:
                result[part] = time_s
    return result


def _partout_rows(product: Path) -> tuple[list[dict], dict]:
    solver = Path(product) / "solver"
    binary = core_f2_qualification.SOURCE_ROOT / "vendor/official/DualSPHysics_v5.4/bin/linux/PartVTKOut_linux64"
    if not binary.is_file():
        raise FileNotFoundError(binary)
    runparts = _runparts_times(solver / "RunPARTs.csv")
    with tempfile.TemporaryDirectory(prefix="f2-envelope-analysis-") as folder:
        csv_path = Path(folder) / "excluded.csv"
        process = subprocess.run(
            [str(binary), "-dirdata", str(solver), "-savecsv", str(csv_path), "-csvsep:0"],
            cwd=core_f2_qualification.SOURCE_ROOT,
            env=core_f2.environment(core_f2_qualification.SOURCE_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if process.returncode or not csv_path.is_file():
            raise RuntimeError(f"PartVTKOut failed with code {process.returncode}: {process.stdout[-1000:]}")
        rows = []
        with csv_path.open(newline="") as handle:
            for raw in csv.DictReader(handle, delimiter=";"):
                if not raw or raw.get("Idp") is None:
                    continue
                row = {str(key).strip(): str(value).strip() for key, value in raw.items() if key is not None}
                part = _integer(row.get("PartOut"))
                motive = _integer(row.get("Motive"))
                if part is None or motive is None or part not in runparts:
                    continue
                position = [_number(row.get(f"Pos.{axis} [m]")) for axis in "xyz"]
                velocity = [_number(row.get(f"Vel.{axis} [m/s]")) for axis in "xyz"]
                if any(value is None for value in position + velocity):
                    continue
                rows.append({
                    "particle_id": _integer(row.get("Idp")),
                    "part": part,
                    "time_s": runparts[part],
                    "motive": motive,
                    "position_m": position,
                    "velocity_m_s": velocity,
                })
    return rows, {"binary": str(binary), "runparts_rows": len(runparts)}


def _solver_cell_cost(product: Path) -> dict:
    run_out = Path(product) / "solver" / "Run.out"
    text = run_out.read_text(errors="replace") if run_out.is_file() else ""
    match = re.search(r"MapCells=\((\d+),(\d+),(\d+)\).*?\((\d[\d,]*) cells\)", text)
    memory_match = re.search(r"\*\*CellDiv: Requested GPU memory for [\d,]+ cells.*?:\s*([\d.]+) MiB", text)
    size_match = re.search(r"PosCellSize=([0-9.]+)", text)
    if match:
        dimensions = [int(match.group(index)) for index in range(1, 4)]
        cells = int(np.prod(dimensions))
    else:
        dimensions, cells = [149, 75, 144], 149 * 75 * 144
    memory_mib = float(memory_match.group(1)) if memory_match else float(cells * 16 / 1024**2)
    cell_size_m = float(size_match.group(1)) if size_match else DEFAULT_CELL_SIZE_M
    return {
        "source_run_out": str(run_out),
        "source_map_cells": dimensions,
        "source_cells": cells,
        "source_gpu_cell_memory_mib": memory_mib,
        "source_cell_size_m": cell_size_m,
        "bytes_per_cell": float(memory_mib * 1024**2 / max(cells, 1)),
    }


def _domain_cost(domain: dict, baseline: dict) -> dict:
    cell_size = float(baseline["source_cell_size_m"])
    widths = [float(domain["posmax"][i] - domain["posmin"][i]) for i in range(3)]
    dimensions = [int(math.ceil(width / cell_size)) for width in widths]
    cells = int(np.prod(dimensions))
    memory_mib = cells * float(baseline["bytes_per_cell"]) / 1024**2
    return {
        "posmin": list(domain["posmin"]),
        "posmax": list(domain["posmax"]),
        "widths_m": widths,
        "cell_size_m": cell_size,
        "cell_dimensions": dimensions,
        "cells": cells,
        "relative_cells_to_failed_generated_domain": cells / max(int(baseline["source_cells"]), 1),
        "estimated_gpu_cell_memory_mib": memory_mib,
    }


def _first_predicted_crossings(rows: list[dict], domain: dict, horizon_s: float) -> dict:
    lower = np.asarray(domain["posmin"], dtype=float)
    upper = np.asarray(domain["posmax"], dtype=float)
    result = {f"{axis}{side}": None for axis in "xyz" for side in ("min", "max")}
    for row in rows:
        position = np.asarray(row["position_m"], dtype=float)
        velocity = np.asarray(row["velocity_m_s"], dtype=float)
        time_s = float(row["time_s"])
        remaining = horizon_s - time_s
        if remaining <= 0.0:
            continue
        for axis in range(3):
            for side, boundary in (("min", lower[axis]), ("max", upper[axis])):
                if axis < 2:
                    if velocity[axis] < 0.0 and position[axis] > boundary:
                        delay = (boundary - position[axis]) / velocity[axis]
                    elif velocity[axis] > 0.0 and position[axis] < boundary:
                        delay = (boundary - position[axis]) / velocity[axis]
                    else:
                        continue
                else:
                    a, b, c = 0.5 * GRAVITY_M_S2, velocity[axis], position[axis] - boundary
                    discriminant = b * b - 4.0 * a * c
                    if discriminant < 0.0:
                        continue
                    roots = [(-b + sign * math.sqrt(discriminant)) / (2.0 * a) for sign in (1.0, -1.0)]
                    positive = [root for root in roots if root > 0.0]
                    if not positive:
                        continue
                    delay = min(positive)
                if delay < 0.0 or delay > remaining:
                    continue
                key = f"{'xyz'[axis]}{side}"
                if result[key] is None or delay < result[key]["delay_s"]:
                    result[key] = {
                        "delay_s": float(delay),
                        "crossing_time_s": float(time_s + delay),
                        "part": int(row["part"]),
                        "source_time_s": time_s,
                        "source_position_m": list(row["position_m"]),
                        "source_velocity_m_s": list(row["velocity_m_s"]),
                    }
    return result


def analyze(product: Path, output: Path, margin_m: float = DEFAULT_MARGIN_M) -> dict:
    product = Path(product).resolve()
    prepared_path = product / "prepared.json"
    prepared = json.loads(prepared_path.read_text())
    config = prepared["config"]
    generated_path = Path(prepared["generated_prefix"]).with_suffix(".xml")
    generated_domain = core_f2_qualification._runtime_domain_from_xml(ET.parse(generated_path).getroot())
    rows, export = _partout_rows(product)
    horizon_s = float(config["time_max_s"])
    predicted = []
    for row in rows:
        dt = max(0.0, horizon_s - float(row["time_s"]))
        position = np.asarray(row["position_m"], dtype=float)
        velocity = np.asarray(row["velocity_m_s"], dtype=float)
        endpoint = position + velocity * dt
        endpoint[2] += 0.5 * GRAVITY_M_S2 * dt * dt
        predicted.append(endpoint)
    predicted_array = np.asarray(predicted, dtype=float)
    envelope_min = predicted_array.min(axis=0).tolist()
    envelope_max = predicted_array.max(axis=0).tolist()
    margin_domain = {
        "posmin": list(map(float, core_f2_qualification.F2_ENVELOPE_REPAIR_DOMAIN["posmin"])),
        "posmax": list(map(float, core_f2_qualification.F2_ENVELOPE_REPAIR_DOMAIN["posmax"])),
    }
    ballistic_domain = {
        "posmin": [
            math.floor((envelope_min[index] - margin_m) * 10.0) / 10.0 for index in range(3)
        ],
        "posmax": [
            math.ceil((envelope_max[index] + margin_m) * 10.0) / 10.0 for index in range(3)
        ],
    }
    # Preserve the source's upper computational limit because no upper-face
    # exclusion occurred and the registered geometry pointmax is 2.4 m.
    ballistic_domain["posmax"][2] = max(float(generated_domain["posmax"][2]), ballistic_domain["posmax"][2])
    baseline = _solver_cell_cost(product)
    first = rows[0] if rows else None
    report = {
        "schema": "core.f2.dynamic_envelope_analysis.v1",
        "product": str(product),
        "case_id": config.get("case_id"),
        "read_only": True,
        "solver_relaunched": False,
        "gravity_m_s2": GRAVITY_M_S2,
        "registered_horizon_s": horizon_s,
        "observed_exclusion_rows": len(rows),
        "observed_motive_counts": {
            str(motive): sum(row["motive"] == motive for row in rows) for motive in sorted({row["motive"] for row in rows})
        },
        "first_observed_exclusion": first,
        "observed_position_min_m": np.asarray([row["position_m"] for row in rows]).min(axis=0).tolist(),
        "observed_position_max_m": np.asarray([row["position_m"] for row in rows]).max(axis=0).tolist(),
        "observed_velocity_min_m_s": np.asarray([row["velocity_m_s"] for row in rows]).min(axis=0).tolist(),
        "observed_velocity_max_m_s": np.asarray([row["velocity_m_s"] for row in rows]).max(axis=0).tolist(),
        "projection": {
            "assumptions": [
                "each PartOut position/velocity is advanced to 2.5 s with constant x/y velocity",
                "z uses only public gravity -9.81 m/s^2 after the observed exclusion",
                "no tray, receiver, or other unseen impact is credited; this is a conservative unbounded-spill diagnostic",
            ],
            "predicted_endpoint_min_m": envelope_min,
            "predicted_endpoint_max_m": envelope_max,
            "margin_m": margin_m,
        },
        "domain_comparison": {
            "failed_generated_xml": generated_domain,
            "finite_margin_candidate": margin_domain,
            "ballistic_full_window_candidate": ballistic_domain,
        },
        "finite_margin_first_predicted_crossings": _first_predicted_crossings(
            rows, margin_domain, horizon_s
        ),
        "cell_cost": {
            "baseline_failed_run": baseline,
            "finite_margin_candidate": _domain_cost(margin_domain, baseline),
            "ballistic_full_window_candidate": _domain_cost(ballistic_domain, baseline),
        },
        "interpretation": {
            "finite_margin_candidate_suffices_for_registered_window": False,
            "reason": "the earliest observed z=-0.4 m exclusion with vz about -6 m/s reaches z=-0.9 m in about 0.074 s under gravity; this is far shorter than the remaining 1.36 s window",
            "bounded_scope_status": "a finite runtime domain is physically reasonable only as an explicit spill/censoring boundary; it cannot satisfy the current no-missing-native-id hard gate for unbounded free-fall spill",
            "ballistic_candidate_status": "diagnostic canary only; its estimated cell map is expensive and it does not change physical geometry, mass, or particle identities",
        },
        "qualification_claim": "none; full-window envelope estimate only",
        "analysis_script_sha256": core_cfd.digest(Path(__file__)),
        "qualification_script_sha256": core_cfd.digest(Path(core_f2_qualification.__file__)),
        "input_sha256": {str(path): core_cfd.digest(path) for path in (prepared_path, product / "solver" / "RunPARTs.csv", product / "solver" / "Run.out") if path.is_file()},
    }
    core_f2_qualification._write_json(output, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--product", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--margin-m", type=float, default=DEFAULT_MARGIN_M)
    args = parser.parse_args()
    report = analyze(args.product, args.output, args.margin_m)
    print(json.dumps({
        "schema": report["schema"],
        "rows": report["observed_exclusion_rows"],
        "predicted_min": report["projection"]["predicted_endpoint_min_m"],
        "predicted_max": report["projection"]["predicted_endpoint_max_m"],
        "ballistic_cells": report["cell_cost"]["ballistic_full_window_candidate"]["cells"],
        "ballistic_gpu_cell_memory_mib": report["cell_cost"]["ballistic_full_window_candidate"]["estimated_gpu_cell_memory_mib"],
        "qualification_claim": report["qualification_claim"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
