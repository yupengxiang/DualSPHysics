#!/usr/bin/env python3
"""Calibrate bounded F1-S1 output subsampling on v2 native observer rows.

The worker consumes only small selected-observer JSON sidecars and their
RunPARTs CSV time axes.  For each registered query it compares the observed
rows against a linear reconstruction after retaining every 2nd or 4th row in
the same local saved-time window.  This is an empirical output sampling
diagnostic.  It does not claim a bound on solver time integration, field
interpolation, event timing, or physical qualification.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any


SCHEMA = "ds02.stage2.f1-s1-output-resolution-calibration.v2"
TIME_TOLERANCE_S = 1.0e-12
WINDOW_RADIUS_FRAMES = 4
SUBSAMPLE_FACTORS = (2, 4)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(path)
    stat = path.stat()
    return {"path": str(path), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": sha256_file(path)}


def atomic_json(path: Path, value: Any) -> None:
    encoded = (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    if path.exists():
        raise FileExistsError(f"refuse to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        temporary.write_bytes(encoded)
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def finite(value: Any, label: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} is not finite")
    return result


def vector(value: Any, label: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{label} is not a 3-vector")
    return [finite(item, label) for item in value]


def read_runparts(path: Path) -> list[dict[str, Any]]:
    lines = [line for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    rows: list[dict[str, Any]] = []
    for row in csv.DictReader(lines, delimiter=";"):
        part = (row.get("Part") or "").strip()
        if not part.isdigit():
            continue
        rows.append({"frame": int(part), "time_s": finite(row.get("TimeStep [s]"), f"{path}:time")})
    if not rows or [row["frame"] for row in rows] != list(range(len(rows))):
        raise ValueError(f"RunPARTs is not contiguous from zero: {path}")
    if any(right["time_s"] <= left["time_s"] for left, right in zip(rows, rows[1:])):
        raise ValueError(f"RunPARTs times are not strictly increasing: {path}")
    return rows


def read_observer(path: Path) -> dict[int, dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("status") != "PASS_DECODED_SELECTED_NATIVE_FIELDS":
        raise ValueError(f"observer is not a completed selected native sidecar: {path}")
    if value.get("schema") != "ds02.stage2.native-physical-observer.v2":
        raise ValueError(f"observer is not the MK-explicit v2 worker output: {path}")
    if value.get("manufactured_semantic_selftests", {}).get("status") != "PASS":
        raise ValueError(f"observer manufactured semantic self-tests are not PASS: {path}")
    scope = value.get("scope", {})
    if scope.get("selected_frames_only") is not True or scope.get("hdf5_read") is not False:
        raise ValueError(f"observer scope is not selected native only: {path}")
    rows = value.get("observations")
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"observer has no observations: {path}")
    result: dict[int, dict[str, Any]] = {}
    for row in rows:
        frame = int(row["frame"])
        if frame in result:
            raise ValueError(f"duplicate observer frame {frame}: {path}")
        fluid = row.get("groups", {}).get("fluid")
        if not isinstance(fluid, dict):
            raise ValueError(f"fluid group missing at frame {frame}: {path}")
        if "by_mk_absolute" not in fluid or "by_mkfluid_relative" not in fluid:
            raise ValueError(f"observer lacks explicit MK coordinate groups at frame {frame}: {path}")
        decoded = finite(row.get("time", {}).get("decoded_s"), f"{path}:frame {frame} time")
        runparts = finite(row.get("time", {}).get("runparts_s"), f"{path}:frame {frame} RunPARTs time")
        if abs(decoded - runparts) > TIME_TOLERANCE_S:
            raise ValueError(f"observer/RunPART time mismatch at frame {frame}: {path}")
        result[frame] = {
            "frame": frame,
            "time_s": runparts,
            "position_m": vector(fluid["weighted_centroid_m"], f"{path}:frame {frame} position"),
            "velocity_m_per_s": vector(fluid["weighted_velocity_m_per_s"], f"{path}:frame {frame} velocity"),
            "kinetic_energy_j": finite(fluid["kinetic_energy_j"], f"{path}:frame {frame} KE"),
            "sample_mass_kg": finite(fluid["sample_mass_kg"], f"{path}:frame {frame} mass"),
            "raw_field_digest_sha256": row.get("raw_field_digest_sha256", "UNKNOWN"),
        }
    return result


def bracket(rows: list[dict[str, Any]], query: float) -> tuple[int, int] | None:
    if query < rows[0]["time_s"] or query > rows[-1]["time_s"]:
        return None
    for index, row in enumerate(rows):
        if abs(row["time_s"] - query) <= TIME_TOLERANCE_S:
            return row["frame"], row["frame"]
        if row["time_s"] > query:
            return rows[index - 1]["frame"], row["frame"]
    return None


def interpolate(lower: dict[str, Any], upper: dict[str, Any], query_time: float) -> dict[str, Any]:
    width = upper["time_s"] - lower["time_s"]
    if width <= 0:
        raise ValueError("non-increasing local observer times")
    fraction = (query_time - lower["time_s"]) / width
    def mix(a: list[float], b: list[float]) -> list[float]:
        return [x + fraction * (y - x) for x, y in zip(a, b)]
    return {
        "position_m": mix(lower["position_m"], upper["position_m"]),
        "velocity_m_per_s": mix(lower["velocity_m_per_s"], upper["velocity_m_per_s"]),
        "kinetic_energy_j": lower["kinetic_energy_j"] + fraction * (upper["kinetic_energy_j"] - lower["kinetic_energy_j"]),
        "sample_mass_kg": lower["sample_mass_kg"] + fraction * (upper["sample_mass_kg"] - lower["sample_mass_kg"]),
        "interpolation_fraction": fraction,
    }


def errors(native: dict[str, Any], reconstructed: dict[str, Any]) -> dict[str, Any]:
    position_delta = [a - b for a, b in zip(native["position_m"], reconstructed["position_m"])]
    velocity_delta = [a - b for a, b in zip(native["velocity_m_per_s"], reconstructed["velocity_m_per_s"])]
    position_l2 = math.sqrt(sum(item * item for item in position_delta))
    velocity_l2 = math.sqrt(sum(item * item for item in velocity_delta))
    ke_abs = abs(native["kinetic_energy_j"] - reconstructed["kinetic_energy_j"])
    mass_abs = abs(native["sample_mass_kg"] - reconstructed["sample_mass_kg"])
    return {
        "position_delta_m": position_delta,
        "position_l2_m": position_l2,
        "velocity_delta_m_per_s": velocity_delta,
        "velocity_l2_m_per_s": velocity_l2,
        "kinetic_energy_abs_j": ke_abs,
        "kinetic_energy_relative": ke_abs / max(abs(native["kinetic_energy_j"]), 1.0e-12),
        "sample_mass_abs_kg": mass_abs,
        "sample_mass_relative": mass_abs / max(abs(native["sample_mass_kg"]), 1.0e-12),
    }


def local_factor_result(observer: dict[int, dict[str, Any]], rows: list[dict[str, Any]], query: float, factor: int) -> dict[str, Any]:
    bracket_frames = bracket(rows, query)
    if bracket_frames is None:
        return {"status": "OUTSIDE_SAVED_WINDOW", "query_time_s": query, "factor": factor}
    _, upper = bracket_frames
    start = max(0, upper - WINDOW_RADIUS_FRAMES)
    end = min(len(rows) - 1, upper + WINDOW_RADIUS_FRAMES)
    local_frames = list(range(start, end + 1))
    missing = [frame for frame in local_frames if frame not in observer]
    if missing:
        return {
            "status": "UNKNOWN_MISSING_SELECTED_FRAME",
            "query_time_s": query,
            "factor": factor,
            "required_frames": local_frames,
            "missing_frames": missing,
        }
    retained = [frame for offset, frame in enumerate(local_frames) if offset % factor == 0]
    if retained[-1] != local_frames[-1]:
        retained.append(local_frames[-1])
    dropped = [frame for frame in local_frames if frame not in retained]
    comparisons: list[dict[str, Any]] = []
    for frame in dropped:
        lower_candidates = [candidate for candidate in retained if candidate < frame]
        upper_candidates = [candidate for candidate in retained if candidate > frame]
        if not lower_candidates or not upper_candidates:
            continue
        lower_frame = lower_candidates[-1]
        upper_frame = upper_candidates[0]
        native = observer[frame]
        reconstruction = interpolate(observer[lower_frame], observer[upper_frame], native["time_s"])
        comparisons.append({
            "frame": frame,
            "time_s": native["time_s"],
            "lower_retained_frame": lower_frame,
            "upper_retained_frame": upper_frame,
            "errors": errors(native, reconstruction),
        })
    return {
        "status": "PASS_EMPIRICAL_SUBSAMPLE_DIAGNOSTIC" if comparisons else "UNKNOWN_NO_DROPPED_BRACKETED_ROWS",
        "query_time_s": query,
        "query_bracket_frames": list(bracket_frames),
        "local_frames": local_frames,
        "retained_frames": retained,
        "dropped_rows_compared": len(comparisons),
        "comparisons": comparisons,
        "qualification": "UNKNOWN_OUTPUT_CALIBRATION_ONLY",
    }


def run(observer_specs: list[str], runparts_specs: list[str], queries: list[float]) -> dict[str, Any]:
    observers: dict[str, Path] = {}
    runparts: dict[str, Path] = {}
    for spec in observer_specs:
        label, raw_path = spec.split("=", 1)
        observers[label] = Path(raw_path).resolve()
    for spec in runparts_specs:
        label, raw_path = spec.split("=", 1)
        runparts[label] = Path(raw_path).resolve()
    if set(observers) != set(runparts) or not observers:
        raise ValueError("observer/runparts labels must match and be non-empty")
    output: dict[str, Any] = {}
    for label in sorted(observers):
        obs_path = observers[label]
        runparts_path = runparts[label]
        obs = read_observer(obs_path)
        rows = read_runparts(runparts_path)
        if any(frame >= len(rows) for frame in obs):
            raise ValueError(f"observer frame exceeds RunPARTs axis: {label}")
        for frame, value in obs.items():
            if abs(rows[frame]["time_s"] - value["time_s"]) > TIME_TOLERANCE_S:
                raise ValueError(f"observer/RunPARTs binding mismatch {label} frame {frame}")
        results = {
            str(query): {
                str(factor): local_factor_result(obs, rows, query, factor)
                for factor in SUBSAMPLE_FACTORS
            }
            for query in queries
        }
        output[label] = {
            "observer": record(obs_path),
            "runparts": record(runparts_path),
            "selected_frame_count": len(obs),
            "selected_frame_ids": sorted(obs),
            "full_runparts_frame_count": len(rows),
            "query_results": results,
            "scope": {
                "native_payload_read_by_worker": False,
                "hdf5_read": False,
                "full_native_tree_scanned": False,
                "interpolation_used": "only for empirical output-subsampling diagnostic",
                "physical_qualification": "UNKNOWN",
            },
        }
    return {
        "schema": SCHEMA,
        "status": "COMPLETED_SELECTED_ROW_OUTPUT_RESOLUTION_CALIBRATION",
        "queries_s": queries,
        "subsample_factors": list(SUBSAMPLE_FACTORS),
        "local_window_radius_frames": WINDOW_RADIUS_FRAMES,
        "runs": output,
        "interpretation": {
            "purpose": "empirical comparison of actual saved rows with local 2x/4x row subsampling",
            "time_axis": "actual RunPARTs timestamps; no frame-index time assumption",
            "interpolation": "linear reconstruction is a diagnostic procedure, not a validated solver/field interpolation error bound",
            "qualification": "UNKNOWN; consumer calibration and physical event analysis remain separate",
            "mk_semantics": "fluid relative mkfluid and absolute XML mk are retained separately; this comparison uses aggregate fluid observables and never joins relative labels to absolute labels",
            "pressure": "UNKNOWN_NOT_DECODED_BY_OBSERVER_WORKER",
        },
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observer", action="append", required=True, help="LABEL=selected observer JSON")
    parser.add_argument("--runparts", action="append", required=True, help="LABEL=RunPARTs.csv")
    parser.add_argument("--query-time", action="append", type=float, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = run(args.observer, args.runparts, args.query_time)
    atomic_json(args.output.resolve(), value)
    print(json.dumps({"status": value["status"], "output": str(args.output.resolve())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
