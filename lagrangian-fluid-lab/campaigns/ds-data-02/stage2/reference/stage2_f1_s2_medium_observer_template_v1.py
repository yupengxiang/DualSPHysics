#!/usr/bin/env python3
"""Prepare the F1-S2 medium native-observer template.

This is a launch-disabled template for the already completed F1-S2 medium
solver run (dp=0.020, 401 native saves).  It reads only the small XML,
RunPARTs, and terminal receipt files.  BI4 paths are recorded as deferred
inputs; the template builder deliberately does not open, stat, or hash any
BI4.  A later source-snapshot terminal result must supply those selected
frame hashes before a canonical observer request may be created.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET
from typing import Any


SCHEMA = "ds02.stage2.f1-s2-medium-native-observer-template.v1"
REQUEST_SCHEMA = "ds02.request.v1"
REPO = Path(__file__).resolve().parents[5]
REFERENCE = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
OBSERVER_WORKER = REFERENCE / "stage2_native_physical_observer_v2.py"
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
DECODER_SOURCE = REPO / "lagrangian-fluid-lab/scripts/native/bi4_dump.cpp"
MAIN = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
V6_RUNNER = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v6.py"
V6_STRICT = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v6.py"
V6_RUNTIME = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v6.py"
V2_RUNTIME = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"

CASE_ID = "F1_S2_MEDIUM_DP020"
ATTEMPT_ID = "f1-s2-medium-dp020-actual-full4s-native-template-v1"
PHYSICAL_CASE_ID = "F1_DUAL_HEAD_340_UNCHANGED_MOTHER_GEOMETRY_V1"
SENTINEL_ID = "F1-S2"
FAMILY_ID = "F1"
XML = DATA_ROOT / "families/F1/F1_STAGE1_DUAL_H340_DP020/root-stage1-dual-h340-actual-gencase-027/prepared/F1_STAGE1_DUAL_H340_DP020.xml"
GENCASE_RECEIPT = XML.parent.parent / "execution-receipt.json"
SOLVER_ROOT = DATA_ROOT / "families/F1/F1_STAGE1_DUAL_H340_DP020/root-stage1-dual-h340-physical-endpoint-full-native-gpu-lease-retry-034"
RUNPARTS = SOLVER_ROOT / "solver_output/RunPARTs.csv"
SOLVER_RECEIPT = SOLVER_ROOT / "execution-receipt.json"
RAW_ROOT = SOLVER_ROOT / "solver_output/data"
OUTPUT = REFERENCE / "stage2_f1_s2_medium_observer_template_v1.json"

SELECTED_FRAMES = (0, 99, 100, 199, 200, 299, 300, 399, 400)
QUERY_TIMES = (0.0, 1.0, 2.0, 3.0, 4.0)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular_file(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular file: {path}")
    return path


def record(path: Path, label: str) -> dict[str, Any]:
    path = regular_file(path, label)
    stat = path.stat()
    return {"path": str(path), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": sha256(path)}


def atomic_json(path: Path, value: Any) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refuse to overwrite immutable output: {path}")
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def parse_runparts(path: Path) -> list[dict[str, Any]]:
    """Read only the semicolon CSV; no native frame is touched."""
    rows: list[dict[str, Any]] = []
    with regular_file(path, "RunPARTs") .open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        if reader.fieldnames is None or "Part" not in reader.fieldnames or "TimeStep [s]" not in reader.fieldnames:
            raise ValueError("RunPARTs lacks Part/TimeStep columns")
        for raw in reader:
            part_text = str(raw.get("Part", "")).strip()
            if not part_text or part_text.startswith("#"):
                continue
            part = int(part_text)
            time_s = float(str(raw["TimeStep [s]"]).strip())
            if part < 0 or not math.isfinite(time_s):
                raise ValueError("RunPARTs contains invalid frame/time")
            rows.append({"frame": part, "time_s": time_s})
    rows.sort(key=lambda item: item["frame"])
    if [item["frame"] for item in rows] != list(range(len(rows))):
        raise ValueError("RunPARTs frame IDs are not contiguous from zero")
    if not rows or rows[0]["time_s"] != 0.0:
        raise ValueError("RunPARTs does not begin at time zero")
    for previous, current in zip(rows, rows[1:]):
        if current["time_s"] < previous["time_s"]:
            raise ValueError("RunPARTs timestamps are not monotone")
    return rows


def query_bracket(rows: list[dict[str, Any]], query: float) -> dict[str, Any]:
    times = [float(item["time_s"]) for item in rows]
    if query < times[0] or query > times[-1]:
        return {"query_time_s": query, "status": "OUT_OF_RANGE", "lower_frame": None, "upper_frame": None,
                "lower_time_s": None, "upper_time_s": None, "bracket_width_s": None}
    for index, time_s in enumerate(times):
        if time_s == query:
            return {"query_time_s": query, "status": "EXACT", "lower_frame": index, "upper_frame": index,
                    "lower_time_s": time_s, "upper_time_s": time_s, "bracket_width_s": 0.0}
        if time_s > query:
            lower = index - 1
            return {"query_time_s": query, "status": "BRACKETED", "lower_frame": lower, "upper_frame": index,
                    "lower_time_s": times[lower], "upper_time_s": time_s,
                    "bracket_width_s": time_s - times[lower]}
    raise AssertionError("query bracket search fell through")


def parse_xml_metadata(path: Path) -> dict[str, Any]:
    root = ET.parse(regular_file(path, "generated XML")).getroot()
    definition = next((node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "definition"), None)
    if definition is None or definition.get("dp") is None:
        raise ValueError("generated XML has no geometry definition dp")
    pointref = next((node for node in definition if node.tag.rsplit("}", 1)[-1] == "pointref"), None)
    particles = next((node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "particles"), None)
    fluid = next((node for node in particles or [] if node.tag.rsplit("}", 1)[-1] == "fluid"), None)
    constants = next((node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "constants"), None)
    mass = next((node for node in constants or [] if node.tag.rsplit("}", 1)[-1] == "massfluid"), None)
    rhop0 = next((node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "rhop0"), None)
    params = {node.get("key"): node.get("value") for node in root.iter()
              if node.tag.rsplit("}", 1)[-1] == "parameter" and node.get("key")}
    return {
        "dp_m": float(definition.get("dp")),
        "pointref_m": ({axis: float(pointref.get(axis)) for axis in ("x", "y", "z")} if pointref is not None else None),
        "fluid_block": ({key: fluid.get(key) for key in ("mkfluid", "mk", "begin", "count")} if fluid is not None else None),
        "massfluid_kg": float(mass.get("value")) if mass is not None else None,
        "rhop0_kg_m3": float(rhop0.get("value")) if rhop0 is not None else None,
        "parameters": params,
    }


def build_template() -> dict[str, Any]:
    for path, label in ((XML, "generated XML"), (RUNPARTS, "RunPARTs"), (GENCASE_RECEIPT, "GenCase receipt"), (SOLVER_RECEIPT, "solver receipt"),
                        (OBSERVER_WORKER, "observer worker"), (DECODER_SOURCE, "decoder source"), (V6_RUNNER, "v6 runner"),
                        (V6_STRICT, "v6 strict runner"), (V6_RUNTIME, "v6 runtime"), (V2_RUNTIME, "v2 runtime")):
        regular_file(path, label)
    rows = parse_runparts(RUNPARTS)
    if len(rows) != 401 or rows[-1]["time_s"] != 4.000064410707409:
        raise ValueError(f"unexpected F1-S2 medium RunPARTs terminal: {len(rows)} / {rows[-1]['time_s']}")
    if SELECTED_FRAMES[-1] >= len(rows):
        raise ValueError("selected frame exceeds actual RunPARTs")
    brackets = {str(query): query_bracket(rows, query) for query in QUERY_TIMES}
    xml_meta = parse_xml_metadata(XML)
    if xml_meta["dp_m"] != 0.02 or xml_meta["fluid_block"] is None or xml_meta["fluid_block"].get("count") != "42500":
        raise ValueError("medium XML is not the expected dp=.020 / 42500-fluid source")
    selected_paths = [str(RAW_ROOT / f"Part_{frame:04d}.bi4") for frame in SELECTED_FRAMES]
    output_root = DATA_ROOT / "families/F1" / CASE_ID / ATTEMPT_ID
    static_paths = [Path(__file__).resolve(), OBSERVER_WORKER, DECODER_SOURCE, V6_RUNNER, V6_STRICT, V6_RUNTIME, V2_RUNTIME,
                    RUNPARTS, XML, GENCASE_RECEIPT, SOLVER_RECEIPT, PYTHON]
    static_paths = list(dict.fromkeys(path.resolve() for path in static_paths))
    input_files = [str(path) for path in static_paths]
    input_hashes = {str(path): ("PARENT_V6_GUARD_HASH_REQUIRED" if path == PYTHON else sha256(path)) for path in static_paths}
    command = [str(PYTHON), str(OBSERVER_WORKER), "--raw-root", str(RAW_ROOT), "--runparts", str(RUNPARTS),
               "--generated-xml", str(XML), "--decoder", str(DECODER), "--decoder-source", str(DECODER_SOURCE),
               "--output", "{attempt_root}/observer/f1_s2_medium_dp020_selected_native_observer_v1.json",
               "--scratch-root", "{attempt_root}/scratch/bi4_decode", "--expected-frame-count", "401",
               "--expected-final-time-s", "4.000064410707409", "--final-time-tolerance-s", "1e-12", "--frames",
               *[str(frame) for frame in SELECTED_FRAMES], "--query-times", *[str(query) for query in QUERY_TIMES]]
    return {
        "schema": REQUEST_SCHEMA,
        "template_schema": SCHEMA,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "family_id": FAMILY_ID,
        "sentinel_id": SENTINEL_ID,
        "physical_case_id": PHYSICAL_CASE_ID,
        "case_id": CASE_ID,
        "attempt_id": ATTEMPT_ID,
        "command": command,
        "cwd": str(REPO),
        "worktree_root": str(REPO),
        "input_files": input_files,
        "input_hashes": input_hashes,
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 1800,
        "estimated_native_read_bytes": "PARENT_GUARD_MEASURE_SELECTED_FRAME_BYTES",
        "estimated_storage_bytes": 1024 * 1024 * 1024,
        "estimated_peak_memory_bytes": 1024 * 1024 * 1024,
        "execution_allowed": False,
        "launch_disabled": True,
        "solver_started": False,
        "hdf5_read": False,
        "deferred_input_files": [str(RAW_ROOT), *selected_paths],
        "deferred_input_file_count": len(selected_paths),
        "deferred_hash_policy": {
            "snapshot_required_before_canonical_request": True,
            "selected_frame_scope": "exact Part_0000,0099,0100,0199,0200,0299,0300,0399,0400 only",
            "template_builder_bi4_read": False,
            "template_builder_bi4_stat": False,
            "template_builder_bi4_hash": False,
            "full_raw_tree_hash": "NOT_COMPUTED_BY_TEMPLATE",
            "parent_snapshot_result_must_supply_sha256": True,
        },
        "output": {
            "atomic": True,
            "refuse_overwrite": True,
            "path": "{attempt_root}/observer/f1_s2_medium_dp020_selected_native_observer_v1.json",
            "decoded_fields": ["Idp", "position", "velocity", "density/Rhop", "derived_sample_mass", "kind", "mkfluid_relative", "mk_absolute"],
            "pressure_status": "NOT_DECODED_BY_WORKER",
            "eos_pressure_status": "UNKNOWN_NOT_DECODED",
            "time_policy": "actual RunPARTs timestamps; retain EXACT/BRACKETED; no interpolation or extrapolation",
        },
        "source_binding": {
            "schema": SCHEMA,
            "family_id": FAMILY_ID,
            "sentinel_id": SENTINEL_ID,
            "physical_case_id": PHYSICAL_CASE_ID,
            "raw_root": str(RAW_ROOT),
            "runparts": record(RUNPARTS, "RunPARTs"),
            "generated_xml": record(XML, "generated XML"),
            "source_gencase_receipt": record(GENCASE_RECEIPT, "GenCase receipt"),
            "solver_receipt": record(SOLVER_RECEIPT, "solver receipt"),
            "frame_count": len(rows),
            "last_saved_time_s": rows[-1]["time_s"],
            "selected_native_frame_ids": list(SELECTED_FRAMES),
            "query_times_s": list(QUERY_TIMES),
            "query_brackets": brackets,
            "query_4s_is_exact_saved": False,
            "no_extrapolation": True,
            "no_frame_index_pairing": True,
            "native_part_ids_from_this_run_only": True,
            "xml_semantics": xml_meta,
            "selected_native_sha256": "PARENT_SOURCE_SNAPSHOT_REQUIRED",
        },
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "qualification_stage": "stage2_f1_s2_medium_selected_native_template_pending_source_snapshot",
        "source_snapshot_status": "NOT_YET_AVAILABLE",
        "output_root": str(output_root),
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": str(V6_RUNNER),
            "strict_guard": str(V6_STRICT),
            "runtime": str(V6_RUNTIME),
            "cpu_parent_binding": "required",
            "gpu": "none",
            "solver_launch": "forbidden",
            "hdf5_read": "forbidden",
            "launch_disabled": True,
        },
    }


def self_test() -> dict[str, Any]:
    rows = [{"frame": index, "time_s": float(index)} for index in range(5)]
    exact = query_bracket(rows, 0.0)
    bracketed = query_bracket(rows, 1.5)
    outside = query_bracket(rows, 6.0)
    assert exact["status"] == "EXACT" and exact["lower_frame"] == 0
    assert bracketed["status"] == "BRACKETED" and bracketed["lower_frame"] == 1 and bracketed["upper_frame"] == 2
    assert outside["status"] == "OUT_OF_RANGE"
    return {"status": "PASS", "bi4_read": False, "bracket_semantics": "EXACT/BRACKETED/OUT_OF_RANGE"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), indent=2))
        return 0
    value = build_template()
    atomic_json(args.output, value)
    print(json.dumps({"status": "PASS_TEMPLATE_BUILT", "output": str(args.output.resolve()),
                      "selected_frames": list(SELECTED_FRAMES), "bi4_read": False,
                      "last_saved_time_s": value["source_binding"]["last_saved_time_s"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
