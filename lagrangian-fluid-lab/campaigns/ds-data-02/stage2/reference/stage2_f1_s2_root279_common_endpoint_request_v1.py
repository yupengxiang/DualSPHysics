#!/usr/bin/env python3
"""Build a source-only ROOT279 common-endpoint observer request.

This builder binds the frozen F1-S2 calibration card and the prepared ROOT279
pair manifest.  The guarded ROOT279 result and its child report are explicitly
deferred until the parent has run ROOT310/ROOT279; no placeholder SHA is ever
treated as executable evidence.  The emitted worker is the additive
``stage2_f1_s2_root279_common_endpoint_observer_v1.py`` consumer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
PYVENV = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/pyvenv.cfg")
WORKER = HERE / "stage2_f1_s2_root279_common_endpoint_observer_v1.py"
CONTRACT = HERE / "stage2_f1_s2_root279_common_endpoint_observer_v1.json"
SCHEMA = "ds02.request.v1"
VARIANT = "ds02.stage2.f1-s2.root279-common-endpoint-observer.v1"
MANIFEST_SCHEMA = "ds02.stage2.f1-s2.root279-common-endpoint-manifest.v1"
MAX_SMALL_BYTES = 16 * 1024 * 1024
QUERY_TIMES = (0.0, 0.25, 0.5)


class BuildFailure(RuntimeError):
    pass


def _absolute(path: Path) -> Path:
    return path.expanduser().absolute()


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {"device": int(value.st_dev), "inode": int(value.st_ino), "bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns), "ctime_ns": int(value.st_ctime_ns)}


def _record(path: Path, label: str, *, parse: bool = False) -> tuple[Any, dict[str, Any]]:
    path = _absolute(path)
    if path.is_symlink() or not path.is_file():
        raise BuildFailure(f"{label} is not a regular non-symlink file: {path}")
    before = _stat(path)
    if before["bytes"] > MAX_SMALL_BYTES:
        raise BuildFailure(f"{label} exceeds bounded source cap: {path}")
    raw = path.read_bytes(); after = _stat(path)
    if before != after:
        raise BuildFailure(f"{label} changed during source read: {path}")
    record = {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "stat": after, "payload_read_by_builder": False}
    if not parse:
        return None, record
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BuildFailure(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise BuildFailure(f"{label} must be a JSON object")
    return value, record


def _write_once(path: Path, value: Any) -> None:
    path = _absolute(path)
    if path.exists() or path.is_symlink():
        raise BuildFailure(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _literal_python_record() -> dict[str, Any]:
    path = _absolute(PYTHON)
    if not path.is_symlink():
        raise BuildFailure(f"worker argv0 must remain literal venv symlink: {path}")
    target = path.resolve(strict=True)
    _, record = _record(target, "resolved venv interpreter")
    record.update({"path": str(path), "literal_argv0": True, "resolved_target": str(target), "payload_read_by_builder": False})
    return record


def build(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    card, card_record = _record(args.card, "F1-S2 calibration card", parse=True)
    root279, root279_record = _record(args.root279_manifest, "ROOT279 pair manifest", parse=True)
    if card.get("schema") != "ds02.stage2.f1-s2.common-endpoint-calibration.v1":
        raise BuildFailure("calibration card schema mismatch")
    if root279.get("schema") != "ds02.stage2.f1.native-selected-observer-manifest.v2":
        raise BuildFailure("ROOT279 manifest schema mismatch")
    if root279.get("status") not in {"PREPARED_ROOT279_PAIR_NATIVE_OBSERVER_V3_PENDING_PARENT_SNAPSHOT", "PREPARED_ROOT279_PAIR_NATIVE_OBSERVER_V3_WITH_PARENT_SNAPSHOT"}:
        raise BuildFailure("ROOT279 manifest is not a prepared source manifest")
    card_brackets = card.get("observed_brackets")
    if not isinstance(card_brackets, dict):
        raise BuildFailure("calibration card lacks observed brackets")
    root_cases = root279.get("cases")
    if not isinstance(root_cases, list) or {item.get("label") for item in root_cases if isinstance(item, dict)} != {"same_cfl", "half_cfl"}:
        raise BuildFailure("ROOT279 manifest lacks the same/half pair")
    cases: list[dict[str, Any]] = []
    for source_case in sorted(root_cases, key=lambda item: item["label"]):
        label = str(source_case["label"])
        selected = source_case.get("selected_frames")
        if selected != [0, 49, 50, 99, 100]:
            raise BuildFailure(f"{label} selected frame contract differs from the preregistered endpoints")
        identity = source_case.get("identity")
        if not isinstance(identity, dict) or identity.get("sentinel_id") != "F1-S2" or identity.get("grid") != "medium" or identity.get("cfl_mode") != label:
            raise BuildFailure(f"{label} producer identity is not the F1-S2 medium pair")
        controls = card.get("actual_pair_controls", {}).get(label)
        if not isinstance(controls, dict):
            raise BuildFailure(f"{label} actual control binding is absent from card")
        cases.append({"label": label, "identity": identity, "control_binding": {"effective_CFL": controls.get("effective_cfl"), "TimeMax_s": controls.get("TimeMax_s"), "output_interval_s": 0.005, "SaveDt_logging_active": controls.get("SaveDt_logging_active")}, "brackets": card_brackets[label]})

    static_records = {
        card_record["path"]: card_record,
        root279_record["path"]: root279_record,
        str(_absolute(WORKER)): _record(WORKER, "ROOT279 common-endpoint worker")[1],
        str(_absolute(CONTRACT)): _record(CONTRACT, "ROOT279 common-endpoint contract")[1],
        str(_absolute(PYVENV)): _record(PYVENV, "literal venv configuration")[1],
    }
    root_result_path = _absolute(args.root279_result)
    child_report_path = _absolute(args.child_report)
    pending_result = {"path": str(root_result_path), "sha256": "PARENT_AFTER_ROOT279_RESULT_REQUIRED", "stat": "PARENT_AFTER_ROOT279_RESULT_STAT_REQUIRED", "status": "DEFERRED_UNTIL_ROOT279_TERMINAL"}
    pending_child = {"path": str(child_report_path), "sha256": "PARENT_AFTER_ROOT279_CHILD_REPORT_REQUIRED", "stat": "PARENT_AFTER_ROOT279_CHILD_REPORT_STAT_REQUIRED", "status": "DEFERRED_UNTIL_ROOT279_TERMINAL"}
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "status": "PREPARED_ROOT279_COMMON_ENDPOINT_OBSERVER_V1_WAITING_RESULT",
        "query_times_s": list(QUERY_TIMES),
        "query_policy": {"interpolation": False, "extrapolation": False, "saved_time_source": "ROOT277/278 RunPARTs actual brackets carried by ROOT279 child"},
        "sources": {"calibration_card": card_record, "root279_manifest": root279_record, "root279_guard_result": pending_result, "root279_child_report": pending_child},
        "cases": cases,
        "frozen_tolerances": card["frozen_tolerances"],
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0},
        "read_scope": {"builder_reads_native_payload": False, "builder_reads_hdf5": False, "solver_launch": False},
    }
    manifest_path = _absolute(args.manifest_output)
    _write_once(manifest_path, manifest)
    manifest_record = _record(manifest_path, "generated common-endpoint manifest")[1]
    static_records[manifest_record["path"]] = manifest_record
    input_files = sorted(static_records)
    input_sha256 = {path: record["sha256"] for path, record in static_records.items()}
    request = {
        "schema": SCHEMA, "variant_schema": VARIANT, "status": "WAITING_ROOT279_TERMINAL_COMMON_ENDPOINT_OBSERVER", "request_id": "f1-s2-root279-common-endpoint-observer-v1", "kind": "cpu", "cpu_task_kind": "audit", "family_id": "F1", "sentinel_ids": ["F1-S2"], "case_id": "F1_S2_ROOT279_COMMON_ENDPOINT_OBSERVER_V1", "attempt_id": "f1-s2-root279-common-endpoint-observer-v1-001", "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 1800, "max_memory_bytes": 2 * 1024 * 1024 * 1024, "estimated_storage_bytes": 32 * 1024 * 1024, "command": [str(PYTHON), str(WORKER), "--run", "--manifest", str(manifest_path), "--output", str(_absolute(args.observer_output))], "cwd": str(HERE.parents[5]), "input_files": input_files, "input_records": static_records, "input_sha256": input_sha256, "deferred_observer_outputs": [pending_result, pending_child], "execution_allowed": False, "launch_disabled": True, "native_payload_read": False, "hdf5_read": False, "solver_launch": False, "parent_result_rebind_required": True, "frozen_tolerances": card["frozen_tolerances"], "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0}, "source_binding": {"same_half_proofs_bound_in_card": True, "root279_source_manifest": root279_record, "missing_native_mass": "UNKNOWN; no XML fallback", "interpolation": False, "neighbor_grid_truth": False},
    }
    request_path = _absolute(args.request_output)
    _write_once(request_path, request)
    return manifest, request


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="f1-s2-root279-request-") as td:
        root = Path(td)
        card = root / "card.json"; card.write_text(json.dumps({"schema": "ds02.stage2.f1-s2.common-endpoint-calibration.v1", "frozen_tolerances": {"position_fraction_of_registered_L": {"value": 0.02, "measured": False}, "velocity_and_ke_fraction_of_registered_nonzero_scale": {"value": 0.05, "measured": False}, "time_and_output_each_fraction_of_task_tolerance": {"value": 0.25, "measured": False}}, "observed_brackets": {"same_cfl": [{"query_s": 0, "left_part": 0, "left_time_s": 0, "right_part": 0, "right_time_s": 0}, {"query_s": .25, "left_part": 49, "left_time_s": .245, "right_part": 50, "right_time_s": .25}, {"query_s": .5, "left_part": 99, "left_time_s": .495, "right_part": 100, "right_time_s": .5}], "half_cfl": [{"query_s": 0, "left_part": 0, "left_time_s": 0, "right_part": 0, "right_time_s": 0}, {"query_s": .25, "left_part": 49, "left_time_s": .245, "right_part": 50, "right_time_s": .25}, {"query_s": .5, "left_part": 99, "left_time_s": .495, "right_part": 100, "right_time_s": .5}]}, "actual_pair_controls": {"same_cfl": {"effective_cfl": .2, "TimeMax_s": .5, "SaveDt_logging_active": True}, "half_cfl": {"effective_cfl": .1, "TimeMax_s": .5, "SaveDt_logging_active": True}}}), encoding="utf-8")
        root279 = root / "root279.json"; root279.write_text(json.dumps({"schema": "ds02.stage2.f1.native-selected-observer-manifest.v2", "status": "PREPARED_ROOT279_PAIR_NATIVE_OBSERVER_V3_PENDING_PARENT_SNAPSHOT", "cases": [{"label": "same_cfl", "selected_frames": [0, 49, 50, 99, 100], "identity": {"sentinel_id": "F1-S2", "grid": "medium", "cfl_mode": "same_cfl"}}, {"label": "half_cfl", "selected_frames": [0, 49, 50, 99, 100], "identity": {"sentinel_id": "F1-S2", "grid": "medium", "cfl_mode": "half_cfl"}}]}), encoding="utf-8")
        args = argparse.Namespace(card=card, root279_manifest=root279, root279_result=root / "root-result.json", child_report=root / "child.json", manifest_output=root / "manifest.json", request_output=root / "request.json", observer_output=root / "observer.json")
        manifest, request = build(args)
        assert manifest["status"].startswith("PREPARED_ROOT279") and request["execution_allowed"] is False
        assert request["deferred_observer_outputs"][0]["sha256"].startswith("PARENT_AFTER")
    print("PASS_F1_S2_ROOT279_COMMON_ENDPOINT_REQUEST_SELFTEST")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--self-test", action="store_true"); parser.add_argument("--card", type=Path); parser.add_argument("--root279-manifest", type=Path); parser.add_argument("--root279-result", type=Path); parser.add_argument("--child-report", type=Path); parser.add_argument("--manifest-output", type=Path); parser.add_argument("--request-output", type=Path); parser.add_argument("--observer-output", type=Path)
    args = parser.parse_args(argv)
    if args.self_test:
        self_test(); return 0
    required = (args.card, args.root279_manifest, args.root279_result, args.child_report, args.manifest_output, args.request_output, args.observer_output)
    if any(value is None for value in required):
        parser.error("all source and output paths are required")
    try:
        _, request = build(args)
    except (BuildFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_F1_S2_ROOT279_COMMON_ENDPOINT_REQUEST: {exc}", file=sys.stderr); return 2
    print(json.dumps({"status": request["status"], "manifest": str(_absolute(args.manifest_output)), "request": str(_absolute(args.request_output)), "execution_allowed": False, "native_payload_read": False}, sort_keys=True)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
