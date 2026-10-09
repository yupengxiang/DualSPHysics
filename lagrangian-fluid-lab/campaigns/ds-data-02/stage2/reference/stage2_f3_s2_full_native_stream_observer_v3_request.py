#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Build a guarded ROOT177/178 full-native observer request.

The builder runs only after a terminal external-v5 request, receipt, proof,
generated XML, RunPARTs, and BI4 source snapshot are available.  It hashes
small metadata and XML/RunPARTs inputs, while the complete native Part tree is
deferred to the parent reservation.  No payload bytes are read here.
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


PRIMARY_REPO = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
LOCAL_REPO = Path(__file__).resolve().parents[5]
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
SCHEMA = "ds02.request.v1"
VARIANT = "ds02.stage2.f3-s2.full-native-stream-observer-request.v3"
PHYSICAL_CASE_ID = "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT"
CALIBRATION = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_observer_calibration_contract_v1.json"
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
DECODER_SOURCE = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/native/bi4_dump.cpp"
HEADER_WORKER = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_native_header_observer_v1.py"
PHYSICAL_WORKER = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_native_physical_observer_v2.py"
RUNTIME_V2 = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
RUNTIME_V6 = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v6.py"
RUNTIME_V8 = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
DISPATCH = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"
STRICT = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"


def _worker_path(name: str) -> Path:
    primary = PRIMARY_REPO / f"lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/{name}"
    local = LOCAL_REPO / f"lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/{name}"
    for candidate in (primary, local):
        if candidate.is_file() and not candidate.is_symlink():
            return candidate
    raise FileNotFoundError(name)


def _load_worker():
    path = _worker_path("stage2_f3_s2_full_native_stream_observer_v3.py")
    spec = importlib.util.spec_from_file_location("stage2_f3_s2_full_native_stream_observer_v3_request_builder", path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _path(value: Path | str) -> Path:
    return Path(value).expanduser().resolve()


def _regular(path: Path, label: str) -> Path:
    path = _path(path)
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with _regular(path, "hash input").open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _record(path: Path, label: str, *, max_bytes: int = 32 * 1024 * 1024) -> dict[str, Any]:
    path = _regular(path, label)
    stat = path.stat()
    if int(stat.st_size) > max_bytes:
        raise ValueError(f"{label} exceeds builder small-input limit: {stat.st_size}")
    return {"path": str(path), "label": label, "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns), "ctime_ns": int(stat.st_ctime_ns), "st_dev": int(stat.st_dev), "st_ino": int(stat.st_ino), "sha256": _sha256(path), "content_scope": "small_metadata_hashed_by_builder_and_parent_v8"}


def _record_literal(path: Path, label: str) -> dict[str, Any]:
    path = path.expanduser()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    stat = path.stat()
    return {"path": str(path), "label": label, "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns), "ctime_ns": int(stat.st_ctime_ns), "st_dev": int(stat.st_dev), "st_ino": int(stat.st_ino), "sha256": _sha256(path), "content_scope": "literal_venv_interpreter_hash"}


def _payload_record(path: Path, label: str, expected_sha: str, expected_bytes: int) -> dict[str, Any]:
    path = _path(path)
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    stat = path.stat()
    if int(stat.st_size) != int(expected_bytes):
        raise ValueError(f"{label} stat bytes {stat.st_size} != expected {expected_bytes}")
    return {"path": str(path), "label": label, "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns), "ctime_ns": int(stat.st_ctime_ns), "st_dev": int(stat.st_dev), "st_ino": int(stat.st_ino), "sha256": expected_sha, "sha256_computed_by_builder": False, "content_scope": "parent_after_reservation_pre_post_hash"}


def _canonical(value: dict[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False, default=str).encode()).hexdigest()


def build(args: argparse.Namespace) -> dict[str, Any]:
    if args.expected_frame_count < 2 or args.expected_final_time_s <= 0.0:
        raise ValueError("full observer needs a positive terminal frame/time contract")
    if args.expected_dp_m <= 0.0 or args.expected_initial_fluid_count <= 0:
        raise ValueError("expected source dp/count must be positive")
    if args.estimated_native_bytes <= 0 or args.estimated_storage_bytes <= 0:
        raise ValueError("native read and output storage estimates must be positive")
    worker_module = _load_worker()
    context_args = argparse.Namespace(**vars(args))
    context = worker_module._terminal_context(context_args)
    xml_gate = worker_module._xml_gate(_path(args.generated_xml), float(args.expected_dp_m), int(args.expected_initial_fluid_count))
    worker = _worker_path("stage2_f3_s2_full_native_stream_observer_v3.py")
    consumed_v2 = _worker_path("stage2_f3_s2_full_native_stream_observer_v2.py")
    small_paths = [
        (args.solver_request, "terminal solver request"), (args.terminal_receipt, "terminal solver receipt"), (args.terminal_proof, "terminal solver proof"),
        (args.source_snapshot_proof, "source snapshot proof"), (args.source_snapshot_report, "source snapshot report"),
        (args.generated_xml, "terminal generated XML"), (args.runparts, "terminal RunPARTs"),
        (worker, "strict full observer worker"), (consumed_v2, "consumed full observer decoder"),
        (HEADER_WORKER, "native header worker"), (PHYSICAL_WORKER, "generic physical worker"), (args.calibration_contract, "observer calibration contract"),
        (DECODER, "official BI4 decoder"), (DECODER_SOURCE, "official BI4 decoder source"), (RUNTIME_V2, "runtime v2"), (RUNTIME_V6, "runtime v6"), (RUNTIME_V8, "runtime v8"), (DISPATCH, "dispatch v8"), (STRICT, "strict dispatch v8"),
    ]
    records = {str(_path(path)): _record(path, label) for path, label in small_paths}
    records[str(PYTHON)] = _record_literal(PYTHON, "literal venv interpreter")
    raw_root = _path(args.raw_root)
    if raw_root.is_symlink() or not raw_root.is_dir():
        raise FileNotFoundError(f"terminal native raw root is not a directory: {raw_root}")
    bi4 = context["bi4_sha256"]
    bi4_path = context["request"].get("bi4_snapshot_binding", {}).get("bi4", {}).get("path")
    bi4_bytes = int(context["bi4_bytes"])
    if not bi4_path:
        raise ValueError("terminal request lacks bound BI4 path")
    deferred_bi4 = _payload_record(Path(str(bi4_path)), "source BI4", str(bi4), bi4_bytes)
    records[deferred_bi4["path"]] = deferred_bi4
    forcing = context["request"].get("source_provenance", {}).get("source_control")
    forcing_path = forcing.get("path") if isinstance(forcing, dict) else None
    forcing_sha = forcing.get("sha256") if isinstance(forcing, dict) else None
    forcing_record = None
    if forcing_path and forcing_sha:
        forcing_record = _payload_record(Path(str(forcing_path)), "source forcing CSV", str(forcing_sha), int(forcing.get("bytes", 0) or 0))
        records[forcing_record["path"]] = forcing_record
    query_times = [0.0, 2.0, 4.0, 6.0, 8.0, float(args.expected_final_time_s)]
    output_path = "{attempt_root}/observer/f3_s2_full_native_stream_observer_v3.json"
    command = [str(PYTHON), str(worker), "--solver-request", str(_path(args.solver_request)), "--terminal-receipt", str(_path(args.terminal_receipt)), "--terminal-proof", str(_path(args.terminal_proof)), "--source-snapshot-proof", str(_path(args.source_snapshot_proof)), "--source-snapshot-report", str(_path(args.source_snapshot_report)), "--raw-root", str(raw_root), "--runparts", str(_path(args.runparts)), "--generated-xml", str(_path(args.generated_xml)), "--decoder", str(DECODER), "--decoder-source", str(DECODER_SOURCE), "--calibration-contract", str(_path(args.calibration_contract)), "--output", output_path, "--scratch-root", "{attempt_root}/scratch/bi4_decode", "--expected-frame-count", str(args.expected_frame_count), "--expected-final-time-s", repr(float(args.expected_final_time_s)), "--expected-dp-m", repr(float(args.expected_dp_m)), "--expected-initial-fluid-count", str(args.expected_initial_fluid_count), "--query-times", *(repr(value) for value in query_times), "--decoder-timeout-s", "300", "--max-decoder-log-bytes", "65536", "--max-decoder-scratch-bytes", str(256 * 1024 * 1024)]
    input_files = sorted(records)
    hashes = {path: records[path]["sha256"] for path in input_files if records[path].get("sha256") is not None}
    deferred = {"raw_root": {"path": str(raw_root), "content_scope": "all native Part files read only after parent reservation", "estimated_bytes": int(args.estimated_native_bytes), "estimated_passes": 1, "native_payload_read_by_builder": False}, "bi4": {"path": deferred_bi4["path"], "expected_sha256": bi4, "bytes": bi4_bytes, "content_scope": "parent after-reservation source binding"}}
    if forcing_record is not None:
        deferred["forcing"] = {"path": forcing_record["path"], "expected_sha256": forcing_record["sha256"], "bytes": forcing_record["bytes"], "content_scope": "parent after-reservation source binding"}
    value: dict[str, Any] = {
        "schema": SCHEMA, "variant_schema": VARIANT, "status": "READY_FOR_PARENT_V8_F3_FULL_NATIVE_STREAM_V3", "kind": "cpu", "cpu_task_kind": "audit", "family_id": "F3", "sentinel_id": "F3-S2", "physical_case_id": PHYSICAL_CASE_ID, "case_id": args.case_id, "attempt_id": args.attempt_id, "launch_commit": args.launch_commit, "cwd": str(PRIMARY_REPO / "lagrangian-fluid-lab"), "worktree_root": str(PRIMARY_REPO), "command": command, "input_files": input_files, "input_hashes": hashes, "input_sha256": hashes, "input_records": records, "deferred_input_files": [str(raw_root), deferred_bi4["path"]] + ([forcing_record["path"]] if forcing_record else []), "deferred_input_records": deferred, "deferred_input_policy": "parent v8 reserves the actual attempt then verifies each native Part and source payload with complete SHA/stat boundaries", "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 10800, "max_memory_bytes": 4 * 1024**3, "estimated_peak_memory_bytes": 4 * 1024**3, "max_decoder_scratch_bytes": 256 * 1024**2, "estimated_storage_bytes": int(args.estimated_storage_bytes), "estimated_input_read_bytes": int(args.estimated_native_bytes) + sum(item["bytes"] for item in records.values()), "estimated_native_read_bytes": int(args.estimated_native_bytes), "estimated_native_read_passes": 1, "estimated_hdf5_read_bytes": 0, "execution_allowed": True, "launch_disabled": False, "solver_started": False, "solver_launch": False, "gencase_launch": False, "native_payload_read": True, "hdf5_read": False, "raw_directory_scan": True, "output_root": "{attempt_root}", "output": {"atomic": True, "refuse_overwrite": True, "path": output_path}, "source_binding": {"terminal_request_sha256": context["request_sha256"], "terminal_output_root": str(context["output_root"]), "raw_root_contract": str(context["output_root"] / "solver_output" / "data"), "runparts_contract": str(context["output_root"] / "solver_output" / "RunPARTs.csv"), "generated_xml_sha256": context["generated_xml_sha256"], "source_snapshot_proof_sha256": context["snapshot_proof_sha256"], "source_snapshot_report_sha256": context["snapshot_report_sha256"], "bi4_sha256": bi4, "bi4_bytes": bi4_bytes, "xml_gate": xml_gate, "expected_dp_m": float(args.expected_dp_m), "expected_initial_fluid_count": int(args.expected_initial_fluid_count), "later_fluid_counts": "observed; no all-frame initial-count assertion"}, "resource_guard": {"owner": "stage2-reference-preparation", "runner": "parent-v8-audit", "fresh_uuid_lease": True, "payload_read": "full native Part stream only after parent reservation", "solver_launch": "forbidden"}, "qualification_stage": "stage2_f3_s2_full_native_stream_pending_parent_guard", "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "reason": "full native fields/identity/header/time audit only; no interpolation, spatial truth, dynamics, continuum equivalence, or event qualification"},
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
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False); stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def self_test() -> dict[str, Any]:
    worker = _load_worker().self_test()
    if worker.get("status") != "PASS":
        raise AssertionError(worker)
    return {"status": "PASS", "schema": SCHEMA, "parameterized_grid": True, "memory_bytes": 4 * 1024**3, "scratch_bytes": 256 * 1024**2, "payload_read": False, "solver_started": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True); mode.add_argument("--self-test", action="store_true"); mode.add_argument("--build-request", action="store_true")
    parser.add_argument("--solver-request", type=Path); parser.add_argument("--terminal-receipt", type=Path); parser.add_argument("--terminal-proof", type=Path); parser.add_argument("--source-snapshot-proof", type=Path); parser.add_argument("--source-snapshot-report", type=Path); parser.add_argument("--raw-root", type=Path); parser.add_argument("--runparts", type=Path); parser.add_argument("--generated-xml", type=Path); parser.add_argument("--calibration-contract", type=Path, default=CALIBRATION); parser.add_argument("--expected-frame-count", type=int); parser.add_argument("--expected-final-time-s", type=float); parser.add_argument("--expected-dp-m", type=float); parser.add_argument("--expected-initial-fluid-count", type=int); parser.add_argument("--estimated-native-bytes", type=int); parser.add_argument("--estimated-storage-bytes", type=int); parser.add_argument("--launch-commit"); parser.add_argument("--case-id", default="F3_S2_FULL_NATIVE_STREAM_ROOT177_OR_ROOT178"); parser.add_argument("--attempt-id", default="f3-s2-full-native-stream-root177-or-root178-001"); parser.add_argument("--output", type=Path, default=LOCAL_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/f3-s2-full-native-stream-observer-v3-root177-or-root178-001.json")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2)); return 0
    required = (args.solver_request, args.terminal_receipt, args.terminal_proof, args.source_snapshot_proof, args.source_snapshot_report, args.raw_root, args.runparts, args.generated_xml, args.expected_frame_count, args.expected_final_time_s, args.expected_dp_m, args.expected_initial_fluid_count, args.estimated_native_bytes, args.estimated_storage_bytes, args.launch_commit)
    if any(item is None for item in required):
        parser.error("--build-request requires terminal/source paths, grid/frame contract, byte estimates, and launch commit")
    try:
        value = build(args); _write_once(args.output, value)
    except BaseException as exc:
        print(json.dumps({"status": "FAILED_F3_FULL_NATIVE_STREAM_REQUEST_BUILD", "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=False)); return 1
    print(json.dumps({"status": value["status"], "output": str(_path(args.output)), "payload_read": "parent_after_reservation", "solver_started": False}, ensure_ascii=False, indent=2)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
