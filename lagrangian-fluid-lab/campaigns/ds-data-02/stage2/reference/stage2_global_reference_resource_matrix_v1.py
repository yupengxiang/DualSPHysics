#!/usr/bin/env python3
"""Build a source-bound 14-sentinel resource/readiness matrix.

The matrix reads exact CURRENT336 rows, v2.3 provenance entries, review
sentinel identities, generated XML, conversion reports, RunPARTs, and native
Part_0000 stats.  It records typed HDF5 producer hashes and stat only; HDF5
datasets are never read or rehashed.  The .002/.005 plans are pre-registered
storage studies and readiness records, not solver requests.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET
from typing import Any


SCHEMA = "ds02.stage2.global-reference-resource-matrix.v1"
REQUEST_SCHEMA = "ds02.request.v1"
REPO = Path(__file__).resolve().parents[5]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
CURRENT = Path(__file__).resolve().parents[1] / "CURRENT336.json"
PROVENANCE = Path(__file__).resolve().parent / "stage2-sentinel-initial-provenance-v2_3.json"
REVIEW_MATRIX = Path(__file__).resolve().parents[1] / "review-source/SENTINEL_MATRIX.json"
MATRIX_V4 = DATA_ROOT / "families/F2/F2_S1_REFERENCE_MATRIX_V4/f2-s1-reference-matrix-v4-001/f2-s1-reference-matrix-v4.json"
QUALITY_LABELS = Path(__file__).resolve().parents[1] / "review-source/QUALITY_LABEL_SPLIT_ZH.md"
VENV_PYTHON = "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python"
HOME_PATH = Path("/home/jade")
HOME_FLOOR_GIB = 500.0
STORAGE_CONTINGENCY = 0.20
PLAN_INTERVALS_S = (0.002, 0.005)
GIB = 2**30


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_record(path: Path, *, digest: bool = True) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    stat = path.stat()
    result: dict[str, Any] = {"path": str(path), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    if digest:
        result["sha256"] = sha256_file(path)
    return result


def atomic_json(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(f"refuse to overwrite existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def require_file(path: Path, label: str) -> Path:
    if not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    return path


def git_commit() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True).stdout.strip()


def gib(value: float | int | None) -> float | None:
    return value / GIB if value is not None else None


def scalar_float(mapping: dict[str, Any], key: str) -> float | None:
    value = mapping.get(key)
    if value is None:
        return None
    try:
        return float(value.get("value", value) if isinstance(value, dict) else value)
    except (TypeError, ValueError):
        return None


def parse_xml(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    constants = {child.tag.split("}")[-1]: dict(child.attrib) for child in root.findall(".//execution/constants/*")}
    parameters = {
        child.attrib["key"]: child.attrib.get("value")
        for child in root.findall(".//execution/parameters/parameter")
        if child.attrib.get("key")
    }
    particles = root.find("execution/particles")
    particle_attr = dict(particles.attrib) if particles is not None else {}
    fluid_blocks = [
        {"mkfluid": node.attrib.get("mkfluid"), "mk": node.attrib.get("mk"), "count": int(node.attrib["count"])}
        for node in (particles.findall("fluid") if particles is not None else [])
    ]
    return {"constants": constants, "parameters": parameters, "particle_attr": particle_attr, "fluid_blocks": fluid_blocks}


def read_runparts(path: Path) -> dict[str, Any]:
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip() and not line.lstrip().startswith("#")]
    rows = list(csv.DictReader(lines, delimiter=";"))
    if not rows:
        raise ValueError(f"RunPARTs has no rows: {path}")
    times = [float(row["TimeStep [s]"]) for row in rows]
    return {
        "file": file_record(path),
        "saved_rows": len(rows),
        "first_time_s": times[0],
        "last_time_s": times[-1],
        "initial_row": rows[0],
        "last_row": rows[-1],
    }


def storage_proxy(frame0_bytes: int | None, h5_bytes: int | None, existing_frames: int | None, time_max_s: float | None, interval_s: float) -> dict[str, Any]:
    if frame0_bytes is None or time_max_s is None:
        return {"status": "UNKNOWN", "interval_s": interval_s, "reason": "native frame-zero bytes or TimeMax unavailable"}
    frames = int(round(time_max_s / interval_s)) + 1
    raw_bytes = frame0_bytes * frames
    typed_bytes = None
    if h5_bytes is not None and existing_frames and existing_frames > 0:
        typed_bytes = int(round(h5_bytes * frames / existing_frames))
    known = raw_bytes + typed_bytes if typed_bytes is not None else raw_bytes
    reserved = int(math.ceil(known * (1 + STORAGE_CONTINGENCY)))
    return {
        "status": "PROXY",
        "interval_s": interval_s,
        "planned_frames": frames,
        "native_frame0_bytes_basis": frame0_bytes,
        "native_raw_proxy_bytes": raw_bytes,
        "native_raw_proxy_gib": gib(raw_bytes),
        "typed_hdf5_proxy_bytes": typed_bytes,
        "typed_hdf5_proxy_gib": gib(typed_bytes),
        "known_proxy_bytes": known,
        "known_proxy_gib": gib(known),
        "contingency_fraction": STORAGE_CONTINGENCY,
        "reserved_bytes": reserved,
        "reserved_gib": gib(reserved),
        "basis": "Part_0000 stat × planned frames plus typed HDF5 stat scaled from existing frame count; no HDF5 rehash",
        "unknowns": ["per-frame bytes may vary", "PartVTK/observer sidecars excluded", "solver wall time not inferred from this storage proxy"],
    }


def readiness(sentinel_id: str, source_ok: bool, initial_output: Path | None, matrix_v4: dict[str, Any]) -> dict[str, Any]:
    initial = "PASS_PROVENANCE_ONLY" if initial_output is not None and initial_output.is_file() else "UNKNOWN"
    if sentinel_id == "F2-S1":
        matched = "PARTIAL_F2_S1_V4_MATRIX_AND_GENCASE_PREFLIGHT"
        dense = "PREPARED_INPUTS_NOT_SOLVER"
        next_step = "consumer calibration, then parent-reviewed dp0 same-CFL/half-CFL solver request with fixed output cadence"
    else:
        matched = "NOT_PREPARED"
        dense = "NOT_PREPARED"
        next_step = "source-bound GenCase continuous recipe and controls preflight; no cross-sentinel reuse"
    return {
        "source_binding": "PASS" if source_ok else "UNKNOWN",
        "initial_frame_v2_3": initial,
        "scientific_initial_equivalence": "UNKNOWN; frame-zero provenance PASS does not establish continuous-region or dynamics equivalence",
        "matched_three_resolution_source": matched,
        "same_cfl_half_cfl_dense": dense,
        "observer_calibration": "NOT_RUN",
        "next_bounded_input": next_step,
        "QI_QN_QE": "NOT_ASSESSED",
    }


def source_row(entry: dict[str, Any], current_rows: list[dict[str, Any]], review_rows: dict[str, dict[str, Any]], matrix_v4: dict[str, Any]) -> dict[str, Any]:
    sid = entry["sentinel_id"]
    family = entry["family_id"]
    physical = entry["physical_case_id"]
    matches = [row for row in current_rows if row.get("family_id") == family and row.get("physical_case_id") == physical]
    if len(matches) != 1:
        return {
            "sentinel_id": sid,
            "family_id": family,
            "physical_case_id": physical,
            "status": "UNKNOWN",
            "reason": f"CURRENT336 identity match count={len(matches)}",
            "readiness": readiness(sid, False, None, matrix_v4),
        }
    row = matches[0]
    report_path = Path(row["conversion_report"]["path"])
    xml_path = Path(row["source_bindings"]["generated_xml"]["path"])
    raw_root = Path(row["raw_root"]["path"])
    report = load_json(require_file(report_path, f"{sid} conversion report"))
    xml = parse_xml(require_file(xml_path, f"{sid} generated XML"))
    report_raw_root = Path(report["source_provenance"]["data_root"])
    h5_path = Path(report["output_hdf5"])
    frame0_path = raw_root / "Part_0000.bi4"
    runparts_path = raw_root.parent / "RunPARTs.csv"
    frame0 = file_record(frame0_path) if frame0_path.is_file() else None
    runparts = read_runparts(runparts_path) if runparts_path.is_file() else None
    h5_stat = file_record(h5_path, digest=False) if h5_path.is_file() else None
    report_frames = int(report["frames"]) if report.get("frames") is not None else None
    report_particles = int(report["particles"]) if report.get("particles") is not None else None
    xml_particles = int(xml["particle_attr"]["np"]) if xml["particle_attr"].get("np") else None
    tmax = scalar_float(xml["parameters"], "TimeMax")
    tout = scalar_float(xml["parameters"], "TimeOut")
    cfl = scalar_float(xml["constants"], "cflnumber")
    dp = scalar_float(xml["constants"], "dp")
    h = scalar_float(xml["constants"], "h")
    source_binding_checks = {
        "current_report_path_equals_report_output": str(Path(row["trajectory"]["path"]).resolve()) == str(h5_path.resolve()),
        "current_xml_equals_report_generated_xml": str(xml_path.resolve()) == str(Path(report["source_provenance"]["generated_xml"]["path"]).resolve()),
        "current_raw_root_equals_report_data_root": str(raw_root.resolve()) == str(report_raw_root.resolve()),
        "provenance_report_path_matches_current": str(Path(entry["source_bindings"]["conversion_report"]).resolve()) == str(report_path.resolve()),
        "provenance_native_frame0_matches_current": str(Path(entry["source_bindings"]["native_frame0"]).resolve()) == str(frame0_path.resolve()),
    }
    source_ok = all(source_binding_checks.values()) and frame0 is not None and runparts is not None and h5_stat is not None
    review = review_rows.get(sid, {})
    actual_window = report.get("time_evidence", {})
    initial_output = DATA_ROOT / "families" / family / f"{family}_{sid.split('-', 1)[1]}_INITIAL_FRAME_EQUIV_V2_3" / "initial-frame-equivalence-v2-3-001" / "initial-frame-check.json"
    # Keep the exact v2.3 output binding if the conventional path differs.
    if not initial_output.is_file():
        initial_output = DATA_ROOT / "families" / family / f"{family}_{sid.replace('-', '_')}_INITIAL_FRAME_EQUIV_V2_3" / "initial-frame-equivalence-v2-3-001" / "initial-frame-check.json"
    existing_frames = report_frames
    h5_bytes = h5_stat["bytes"] if h5_stat else None
    frame0_bytes = frame0["bytes"] if frame0 else None
    plans = [storage_proxy(frame0_bytes, h5_bytes, existing_frames, tmax, interval) for interval in PLAN_INTERVALS_S]
    return {
        "sentinel_id": sid,
        "family_id": family,
        "physical_case_id": physical,
        "runtime_case_alias": row.get("runtime_case_alias"),
        "status": "SOURCE_BOUND" if source_ok else "UNKNOWN",
        "review_parameters": {
            "proposed_spacing_m": review.get("proposed_spacing_m"),
            "proposed_dense_cadence_s": review.get("proposed_dense_cadence_s"),
            "proposed_half_cfl": review.get("proposed_half_cfl"),
        },
        "source_binding_checks": source_binding_checks,
        "source": {
            "current336_row": {
                "trajectory": row.get("trajectory"),
                "frames": row.get("frames"),
                "particles": row.get("particles"),
                "actual_time_window_s": row.get("actual_time_window_s"),
                "raw_root": row.get("raw_root"),
            },
            "generated_xml": file_record(xml_path),
            "conversion_report": file_record(report_path),
            "native_frame0": frame0 if frame0 else {"status": "UNKNOWN", "path": str(frame0_path)},
            "runparts": runparts if runparts else {"status": "UNKNOWN", "path": str(runparts_path)},
            "typed_hdf5_stat": {
                **(h5_stat if h5_stat else {"status": "UNKNOWN", "path": str(h5_path)}),
                "producer_declared_sha256": report.get("output_sha256"),
                "full_rehash": "OMITTED_BY_SCOPE",
            },
            "provenance_small": entry.get("small_provenance"),
        },
        "native_signature": {
            "n_particles_report": report_particles,
            "n_particles_xml": xml_particles,
            "n_particles_current": row.get("particles"),
            "frames_report": report_frames,
            "frame0_bytes": frame0_bytes,
            "dp_m": dp,
            "h_m": h,
            "cfl": cfl,
            "time_max_s": tmax,
            "time_out_s": tout,
            "actual_first_s": actual_window.get("first_s"),
            "actual_last_s": actual_window.get("last_s"),
            "actual_window_s": [actual_window.get("first_s"), actual_window.get("last_s")],
        },
        "planned_output_ladder": {
            "intervals_s": list(PLAN_INTERVALS_S),
            "time_output_gate_rule": "pre-register output error contribution at or below one quarter of total time/output tolerance; actual dt/clamp evidence required after solver",
            "solver_wall_time": {"status": "UNKNOWN_UNTIL_GUARDED_EXECUTION", "measured_native_runtime_if_available": runparts.get("last_row", {}).get("SimRuntime [s]") if runparts else None},
            "storage_proxies": plans,
        },
        "readiness": readiness(sid, source_ok, initial_output, matrix_v4),
        "fullscan_hash_credit": entry.get("fullscan_hash_credit", {"status": "UNKNOWN"}),
    }


def resource_snapshot() -> dict[str, Any]:
    usage = shutil.disk_usage(HOME_PATH)
    floor = int(HOME_FLOOR_GIB * GIB)
    spare = max(0, usage.free - floor)
    return {
        "path": str(HOME_PATH),
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
        "free_gib": gib(usage.free),
        "floor_gib": HOME_FLOOR_GIB,
        "spare_above_floor_bytes": spare,
        "spare_above_floor_gib": gib(spare),
        "snapshot_basis": "shutil.disk_usage_at_matrix_execution",
    }


def build_matrix() -> dict[str, Any]:
    current = load_json(require_file(CURRENT, "CURRENT336"))
    index = load_json(require_file(PROVENANCE, "v2.3 provenance index"))
    review = load_json(require_file(REVIEW_MATRIX, "review sentinel matrix"))
    matrix_v4 = load_json(require_file(MATRIX_V4, "F2-S1 v4 matrix"))
    review_rows = {row["sentinel_id"]: row for row in review.get("sentinels", [])}
    entries = index.get("cases", [])
    if len(entries) != 14:
        raise ValueError(f"expected 14 provenance entries, got {len(entries)}")
    rows = [source_row(entry, current.get("cases", []), review_rows, matrix_v4) for entry in entries]
    totals: dict[str, Any] = {}
    for interval in PLAN_INTERVALS_S:
        key = f"{interval:.3f}s"
        estimates = [next((item for item in row.get("planned_output_ladder", {}).get("storage_proxies", []) if item.get("interval_s") == interval), {}) for row in rows]
        known = [item for item in estimates if item.get("status") == "PROXY"]
        totals[key] = {
            "rows_with_proxy": len(known),
            "rows_unknown": len(rows) - len(known),
            "native_raw_proxy_bytes": sum(item.get("native_raw_proxy_bytes", 0) for item in known),
            "typed_hdf5_proxy_bytes": sum(item.get("typed_hdf5_proxy_bytes", 0) or 0 for item in known),
            "known_proxy_bytes": sum(item.get("known_proxy_bytes", 0) for item in known),
            "reserved_bytes_with_contingency": sum(item.get("reserved_bytes", 0) for item in known),
            "native_raw_proxy_gib": gib(sum(item.get("native_raw_proxy_bytes", 0) for item in known)),
            "typed_hdf5_proxy_gib": gib(sum(item.get("typed_hdf5_proxy_bytes", 0) or 0 for item in known)),
            "known_proxy_gib": gib(sum(item.get("known_proxy_bytes", 0) for item in known)),
            "reserved_gib_with_contingency": gib(sum(item.get("reserved_bytes", 0) for item in known)),
            "decision": "PARENT_GLOBAL_RESOURCE_REVIEW_REQUIRED; no solver launch is authorized by this matrix",
        }
    readiness_counts: dict[str, int] = {}
    for row in rows:
        key = row.get("readiness", {}).get("matched_three_resolution_source", "UNKNOWN")
        readiness_counts[key] = readiness_counts.get(key, 0) + 1
    return {
        "schema": SCHEMA,
        "status": "PREPARED_SOURCE_BOUND_RESOURCE_MATRIX",
        "family_id": "infra",
        "scope": {
            "sentinel_count": len(rows),
            "solver_started": False,
            "gencase_started": False,
            "full_time_hdf5_read": False,
            "full_hdf5_rehash": False,
            "observer_calibration_run": False,
            "QI_QN_QE": "NOT_ASSESSED",
        },
        "sources": {
            "current336": file_record(CURRENT),
            "provenance_v2_3": file_record(PROVENANCE),
            "review_sentinel_matrix": file_record(REVIEW_MATRIX),
            "f2_s1_matrix_v4": file_record(MATRIX_V4),
            "quality_labels": file_record(QUALITY_LABELS),
        },
        "pre_registered_ladder": {
            "output_intervals_s": list(PLAN_INTERVALS_S),
            "spatial_grid_policy": "use review proposed_spacing_m per sentinel; no cross-family spacing/geometry equivalence is inferred",
            "time_output_rule": "time and output/reconstruction each consume at most one quarter of the corresponding adopted tolerance; actual dt/clamp and output timestamps must be reported",
            "observer_calibration": "consumer-owned and must freeze before any new solver result",
            "dense_pair_solver": "not started; per-sentinel .002/.005 values are storage/readiness proxies only",
        },
        "readiness_counts": readiness_counts,
        "resource_snapshot": resource_snapshot(),
        "aggregate_storage_proxies": totals,
        "rows": rows,
    }


def request_inputs() -> list[Path]:
    current = load_json(require_file(CURRENT, "CURRENT336"))
    index = load_json(require_file(PROVENANCE, "v2.3 provenance index"))
    inputs = [
        REPO / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch.py",
        REPO / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py",
        REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py",
        Path(__file__).resolve(),
        CURRENT,
        PROVENANCE,
        REVIEW_MATRIX,
        MATRIX_V4,
        QUALITY_LABELS,
    ]
    for entry in index["cases"]:
        matches = [row for row in current["cases"] if row.get("family_id") == entry["family_id"] and row.get("physical_case_id") == entry["physical_case_id"]]
        if len(matches) != 1:
            continue
        row = matches[0]
        report_path = Path(row["conversion_report"]["path"])
        xml_path = Path(row["source_bindings"]["generated_xml"]["path"])
        raw_root = Path(row["raw_root"]["path"])
        inputs.extend([report_path, xml_path, raw_root / "Part_0000.bi4", raw_root.parent / "RunPARTs.csv"])
    unique: list[Path] = []
    seen: set[str] = set()
    for path in inputs:
        path = path.resolve()
        require_file(path, "global matrix input")
        if str(path) not in seen:
            seen.add(str(path))
            unique.append(path)
    return unique


def emit_request(output_path: Path) -> dict[str, Any]:
    inputs = request_inputs()
    root = REPO
    script = Path(__file__).resolve()
    return {
        "schema": REQUEST_SCHEMA,
        "family_id": "infra",
        "case_id": "STAGE2_GLOBAL_REFERENCE_RESOURCE_MATRIX_V1",
        "attempt_id": "stage2-global-reference-resource-matrix-v1-001",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 2,
        "max_wall_seconds": 600,
        "estimated_storage_bytes": 32 * 1024 * 1024,
        "worktree_root": str(root),
        "cwd": str(root),
        "command": [VENV_PYTHON, str(script), "--run", "--output", "{attempt_root}/stage2-global-reference-resource-matrix-v1.json"],
        "input_files": [str(path) for path in inputs],
        "input_hashes": {str(path): sha256_file(path) for path in inputs},
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": "ds_data02_stage2_dispatch.py",
            "strict_guard": "ds_data02_strict_dispatch_v1.py",
            "runtime": "ds_data02_runtime_v2.py",
            "launch_commit": git_commit(),
            "cpu_parent_binding": "required",
            "gpu": "none",
            "estimated_cpu_core_hours": 2 * 600 / 3600,
            "estimated_new_storage_bytes": 32 * 1024 * 1024,
            "full_hdf5_hash": "forbidden_by_scope",
            "solver_launch": "forbidden",
        },
        "scope": {
            "all_fourteen_sentinels": True,
            "source_stat_and_small_xml_report_only": True,
            "hdf5_policy": "producer_declared_sha256_plus_stat; no dataset read or full rehash",
            "solver_started": False,
            "gencase_started": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emit-request", type=Path)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.emit_request is not None:
        request = emit_request(args.emit_request)
        atomic_json(args.emit_request, request)
        print(json.dumps({"status": "PASS", "request": str(args.emit_request), "inputs": len(request["input_files"])}, ensure_ascii=False), flush=True)
        return 0
    if not args.run or args.output is None:
        raise SystemExit("choose --emit-request or --run with --output")
    matrix = build_matrix()
    atomic_json(args.output, matrix)
    print(json.dumps({"status": "PASS", "output": str(args.output), "rows": len(matrix["rows"])}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
