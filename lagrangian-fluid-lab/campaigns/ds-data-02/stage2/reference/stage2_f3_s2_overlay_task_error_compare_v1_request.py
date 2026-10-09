#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Build the bounded post-terminal ROOT173/174 comparison request.

The request consumes three small observer summaries: ROOT162 same-CFL
baseline, ROOT173 half-CFL, and ROOT174 half-output.  It also binds each
summary to the actual terminal proof/request/receipt.  The large native Part
trees and full observer reports remain outside this consumer and are never
read by the builder.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
PRIMARY_REPO = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
LOCAL_REPO = Path(__file__).resolve().parents[5]
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
WORKER_NAME = "stage2_f3_s2_overlay_task_error_compare_v1.py"
CONTRACT_NAME = "stage2_f3_s2_overlay_native_task_contract_v1.json"
SCHEMA = "ds02.request.v1"
VARIANT = "ds02.stage2.f3-s2.overlay-task-error-compare-request.v1"


def _repo_file(name: str) -> Path:
    for root in (PRIMARY_REPO, LOCAL_REPO):
        candidate = root / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference" / name
        if candidate.is_file() and not candidate.is_symlink():
            return candidate
    raise FileNotFoundError(name)


def _load_worker():
    path = _repo_file(WORKER_NAME)
    spec = importlib.util.spec_from_file_location("stage2_f3_s2_overlay_task_error_compare_v1_request_worker", path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _path(value: Path | str) -> Path:
    return Path(value).expanduser().resolve()


def _record(path: Path, label: str, *, max_bytes: int = 32 * 1024 * 1024) -> dict[str, Any]:
    path = _path(path)
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    stat = path.stat()
    if int(stat.st_size) > max_bytes:
        raise ValueError(f"{label} exceeds bounded small-input limit: {stat.st_size}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {
        "path": str(path),
        "label": label,
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "sha256": digest.hexdigest(),
        "content_scope": "bounded_summary_or_terminal_metadata_hashed_by_builder_and_parent_v8",
    }


def _canonical(value: dict[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False, default=str).encode()).hexdigest()


def _parse_binding(text: str) -> tuple[str, Path, Path, Path, Path]:
    parts = text.split("|")
    if len(parts) != 5 or any(not part for part in parts):
        raise ValueError("binding must be label|summary|proof|request|receipt")
    return parts[0], Path(parts[1]), Path(parts[2]), Path(parts[3]), Path(parts[4])


def build(args: argparse.Namespace) -> dict[str, Any]:
    if len(args.binding) != 3:
        raise ValueError("three bindings are required: same_cfl_baseline, half_cfl, half_output")
    worker = _repo_file(WORKER_NAME)
    contract = _repo_file(CONTRACT_NAME)
    worker_module = _load_worker()
    contract_value = worker_module._contract(contract)
    records: dict[str, dict[str, Any]] = {}
    records[str(contract)] = _record(contract, "overlay task contract")
    records[str(worker)] = _record(worker, "overlay task comparison worker")
    labels: set[str] = set()
    binding_values: list[str] = []
    binding_metadata: dict[str, Any] = {}
    for raw in args.binding:
        label, summary, proof, request, receipt = _parse_binding(raw)
        if label in labels:
            raise ValueError(f"duplicate comparison label: {label}")
        labels.add(label)
        normalized = worker_module._normalize(label, summary, contract_value["physical_case_id"])
        terminal = worker_module._validate_terminal_binding(label, normalized, proof, request, receipt, contract_value["physical_case_id"])
        binding_values.append("|".join((label, str(_path(summary)), str(_path(proof)), str(_path(request)), str(_path(receipt)))))
        binding_metadata[label] = {
            "summary": _record(summary, f"{label} bounded native observer summary", max_bytes=4 * 1024 * 1024),
            "proof": terminal["proof"],
            "request": terminal["request"],
            "receipt": terminal["receipt"],
            "native_mass_values_seen": normalized["native_mass_values"],
            "query_count": len(normalized["queries"]),
        }
        for key, record in (("summary", binding_metadata[label]["summary"]), ("proof", terminal["proof"]), ("request", terminal["request"]), ("receipt", terminal["receipt"])):
            records[record["path"]] = record
    if labels != {"same_cfl_baseline", "half_cfl", "half_output"}:
        raise ValueError(f"unexpected comparison labels: {sorted(labels)}")

    output_path = "{attempt_root}/comparison/f3_s2_overlay_task_error_compare_v1.json"
    command = [str(PYTHON), str(worker), "--run", "--contract", str(contract), "--output", output_path]
    for binding in binding_values:
        command.extend(["--binding", binding])
    input_files = sorted(records)
    hashes = {path: records[path]["sha256"] for path in input_files}
    static_bytes = sum(int(record["bytes"]) for record in records.values())
    value: dict[str, Any] = {
        "schema": SCHEMA,
        "variant_schema": VARIANT,
        "status": "READY_FOR_PARENT_V8_OVERLAY_TASK_ERROR_COMPARISON",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "family_id": "F3",
        "sentinel_id": "F3-S2",
        "physical_case_id": contract_value["physical_case_id"],
        "case_id": args.case_id,
        "attempt_id": args.attempt_id,
        "launch_commit": args.launch_commit,
        "cwd": str(PRIMARY_REPO / "lagrangian-fluid-lab"),
        "worktree_root": str(PRIMARY_REPO),
        "command": command,
        "input_files": input_files,
        "input_hashes": hashes,
        "input_sha256": hashes,
        "input_records": records,
        "deferred_input_files": [],
        "deferred_input_policy": "none; only bounded summaries and small terminal metadata are read after parent reservation",
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 1800,
        "max_memory_bytes": 2 * 1024**3,
        "estimated_peak_memory_bytes": 2 * 1024**3,
        "estimated_storage_bytes": 32 * 1024**2,
        "estimated_input_read_bytes": static_bytes,
        "estimated_native_read_bytes": 0,
        "estimated_hdf5_read_bytes": 0,
        "execution_allowed": True,
        "launch_disabled": False,
        "solver_started": False,
        "solver_launch": False,
        "gencase_launch": False,
        "native_payload_read": False,
        "full_report_read": False,
        "hdf5_read": False,
        "raw_directory_scan": False,
        "output_root": "{attempt_root}",
        "output": {"atomic": True, "refuse_overwrite": True, "path": output_path},
        "source_binding": {
            "observer_summary_only": True,
            "full_report_deferred_or_not_opened": True,
            "native_mass_source": "decoded native_header.MassFluid in observer summary",
            "xml_mass_fallback": False,
            "continuous_owner_and_forcing": "bound by each terminal observer request/proof; no replacement from neighboring grid",
            "time_interpolation": False,
            "event_time": "UNKNOWN_NO_SOURCE_EVENT_DEFINITION",
        },
        "comparison_binding": binding_metadata,
        "frozen_scales_and_gates": contract_value["frozen_scales_and_gates"],
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": "parent-v8-audit",
            "fresh_uuid_lease": False,
            "payload_read": "none; bounded JSON only",
            "solver_launch": "forbidden",
        },
        "qualification_stage": "stage2_f3_s2_overlay_task_error_comparison_pending_parent_guard",
        "scientific_qualification": {
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
            "reason": "measured exact endpoint diagnostics only; time/output/integration/spatial/event error remains unresolved",
        },
    }
    value["sha256"] = _canonical(value)
    return value


def _write_once(path: Path, value: dict[str, Any]) -> None:
    path = _path(path)
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable request: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def self_test() -> dict[str, Any]:
    worker = _load_worker()
    result = worker.manufactured_self_test()
    if result.get("status") != "PASS":
        raise AssertionError(result)
    return {
        "status": "PASS",
        "schema": SCHEMA,
        "variant_schema": VARIANT,
        "payload_read": False,
        "solver_started": False,
        "native_payload_read": False,
        "manufactured_trajectory_fixture": "PASS",
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build-request", action="store_true")
    parser.add_argument("--binding", action="append", help="label|observer-summary|terminal-proof|terminal-request|terminal-receipt")
    parser.add_argument("--launch-commit")
    parser.add_argument("--case-id", default="F3_S2_OVERLAY_TASK_ERROR_COMPARISON")
    parser.add_argument("--attempt-id", default="f3-s2-overlay-task-error-compare-v1-001")
    parser.add_argument("--output", type=Path, default=LOCAL_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/f3-s2-overlay-task-error-compare-v1.json")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2))
        return 0
    if not args.binding or args.launch_commit is None:
        parser.error("--build-request requires three --binding values and --launch-commit")
    try:
        value = build(args)
        _write_once(args.output, value)
    except BaseException as exc:
        print(json.dumps({"status": "FAILED_F3_OVERLAY_TASK_ERROR_COMPARISON_REQUEST_BUILD", "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=False))
        return 1
    print(json.dumps({"status": value["status"], "output": str(_path(args.output)), "native_payload_read": False, "solver_started": False}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
