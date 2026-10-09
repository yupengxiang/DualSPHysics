#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Build the guarded ROOT171 fine-grid selected-native observer request.

This is a forward request builder for the terminal ROOT170 ``dp=.003`` run.
It deliberately cannot build from a running receipt: the solver request,
terminal receipt, independent terminal proof, RunPARTs, and generated XML
must all be supplied after the parent has closed the run.  The large native
output directory is deferred to the parent worker and is never hashed or
scanned by this builder.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any


PRIMARY_REPO = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
LOCAL_REPO = Path(__file__).resolve().parents[5]
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
SCHEMA = "ds02.request.v1"
VARIANT = "ds02.stage2.f3-s2.fine-selected-native-observer-request.v1"
PHYSICAL_CASE_ID = "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT"
FAMILY_ID = "F3"
SENTINEL_ID = "F3-S2"
DP_M = 0.003
ROOT169_BI4_SHA = "ad10eb47299148d529883d1e4e4468b19076a8744d227187ec9208b6892e504e"
ROOT169_BI4_BYTES = 48_183_300
CALIBRATION = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_observer_calibration_contract_v1.json"
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
DECODER_SOURCE = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/native/bi4_dump.cpp"
STREAM_WORKER = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_full_native_stream_observer_v2.py"
HEADER_WORKER = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_native_header_observer_v1.py"
PHYSICAL_WORKER = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_native_physical_observer_v2.py"
RUNTIME_V2 = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
RUNTIME_V6 = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v6.py"
RUNTIME_V8 = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
DISPATCH = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"
STRICT = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"


def regular(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    return path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with regular(path, "hash input").open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(regular(path, label).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def record(path: Path, label: str) -> dict[str, Any]:
    path = regular(path, label)
    stat = path.stat()
    return {
        "path": str(path),
        "label": label,
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "sha256": sha256(path),
        "content_scope": "small_terminal_metadata_hashed_by_builder_and_parent_v8",
    }


def record_literal(path: Path, label: str) -> dict[str, Any]:
    path = path.expanduser()
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(f"{label}: {path}")
    stat = path.stat()
    return {
        "path": str(path),
        "label": label,
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "sha256": sha256(path),
        "content_scope": "literal_venv_interpreter_hash",
    }


def _terminal_status(value: Any) -> bool:
    return str(value or "").lower() in {
        "completed",
        "complete",
        "success",
        "completed0",
        "completed_development_unknown",
    } or str(value or "").upper().startswith("COMPLETED_")


def _returncode(value: dict[str, Any]) -> Any:
    execution = value.get("execution")
    if isinstance(execution, dict) and "returncode" in execution:
        return execution.get("returncode")
    if "returncode" in value:
        return value.get("returncode")
    if "return_code" in value:
        return value.get("return_code")
    return None


def _request_binding(value: dict[str, Any], request_path: Path, request_sha: str, label: str) -> None:
    binding = value.get("request")
    if not isinstance(binding, dict):
        raise ValueError(f"{label} has no request provenance")
    bound_sha = binding.get("sha256") or binding.get("request_sha256")
    if bound_sha != request_sha:
        raise ValueError(f"{label} request SHA does not match ROOT170 request")
    bound_path = binding.get("path") or binding.get("request_path")
    if bound_path is not None and Path(str(bound_path)).expanduser().resolve() != request_path:
        raise ValueError(f"{label} request path does not match ROOT170 request")


def _identity(value: dict[str, Any], label: str) -> None:
    for key, expected in (
        ("family_id", FAMILY_ID),
        ("sentinel_id", SENTINEL_ID),
        ("physical_case_id", PHYSICAL_CASE_ID),
    ):
        actual = value.get(key)
        if actual not in (None, expected):
            raise ValueError(f"{label} {key} mismatch: {actual!r}")


def validate_terminal_inputs(args: argparse.Namespace) -> dict[str, Any]:
    request_path = args.solver_request.expanduser().resolve()
    receipt_path = args.terminal_receipt.expanduser().resolve()
    proof_path = args.terminal_proof.expanduser().resolve()
    request = load_json(request_path, "ROOT170 solver request")
    receipt = load_json(receipt_path, "ROOT170 terminal receipt")
    proof = load_json(proof_path, "ROOT170 terminal proof")
    _identity(request, "ROOT170 solver request")
    if request.get("schema") != "ds02.stage2.external-solver-request.v5":
        raise ValueError("ROOT170 request is not the external-solver-request.v5 schema")
    if request.get("status") != "READY_FOR_PARENT_GUARD":
        raise ValueError("ROOT170 request does not carry the consumed READY_FOR_PARENT_GUARD status")
    request_sha = sha256(request_path)
    if not _terminal_status(receipt.get("status")) or _returncode(receipt) not in (0, None):
        raise ValueError("ROOT170 receipt is not a completed zero-return terminal receipt")
    _request_binding(receipt, request_path, request_sha, "ROOT170 receipt")
    if proof.get("schema") not in {
        "ds02.stage2.root-actual-verification.v1",
        "ds02.stage2.root-actual-external-solver-verification.v1",
    } or "ACTUAL" not in str(proof.get("status", "")):
        raise ValueError("ROOT170 proof is not an actual terminal proof")
    _identity(proof, "ROOT170 proof")
    proof_request_sha = proof.get("request_sha256")
    if proof_request_sha not in (None, request_sha):
        raise ValueError("ROOT170 proof request SHA does not match solver request")
    proof_receipt = proof.get("receipt")
    if proof_receipt is not None and Path(str(proof_receipt)).expanduser().resolve() != receipt_path:
        raise ValueError("ROOT170 proof receipt path does not match terminal receipt")
    proof_receipt_sha = proof.get("receipt_sha256")
    if proof_receipt_sha not in (None, sha256(receipt_path)):
        raise ValueError("ROOT170 proof receipt SHA does not match terminal receipt")
    if proof.get("parent_source_prepost_full_sha_equal") is not True:
        raise ValueError("ROOT170 proof does not close materialized source pre/post hashes")
    runparts_summary = proof.get("RunPARTs_summary")
    if not isinstance(runparts_summary, dict) or int(runparts_summary.get("rows", 0) or 0) < 2:
        raise ValueError("ROOT170 proof lacks terminal RunPARTs row evidence")
    actual_bytes = int(proof.get("actual_output_bytes", 0) or 0)
    filesystem = receipt.get("filesystem") if isinstance(receipt.get("filesystem"), dict) else {}
    actual_bytes = actual_bytes or int(filesystem.get("measured_total_bytes", 0) or 0)
    if actual_bytes <= 0:
        raise ValueError("ROOT170 terminal proof/receipt has no positive output-byte evidence")
    if args.expected_frame_count < 2 or args.expected_final_time_s <= 8.0:
        raise ValueError("ROOT170 terminal window does not cover 0,2,4,6,8 s and a final query")
    summary_final = runparts_summary.get("final_time_s")
    if summary_final is not None and abs(float(summary_final) - float(args.expected_final_time_s)) > args.final_time_tolerance_s:
        raise ValueError("ROOT170 expected final time disagrees with terminal proof RunPARTs summary")

    root169_proof = load_json(args.root169_proof, "ROOT169 snapshot proof")
    root169_report = load_json(args.root169_report, "ROOT169 snapshot report")
    if root169_proof.get("schema") != "ds02.stage2.root-actual-verification.v1" or "ACTUAL" not in str(root169_proof.get("status", "")):
        raise ValueError("ROOT169 proof is not an actual source snapshot proof")
    if root169_proof.get("solver_started") is not False or root169_proof.get("native_particle_fields_decoded") is not False:
        raise ValueError("ROOT169 proof unexpectedly includes solver/native field decoding")
    snapshot = root169_proof.get("worker_source_snapshot")
    if not isinstance(snapshot, dict) or snapshot.get("sha256") != ROOT169_BI4_SHA or int(snapshot.get("bytes", 0)) != ROOT169_BI4_BYTES:
        raise ValueError("ROOT169 proof does not bind the expected fine BI4 snapshot")
    if root169_proof.get("parent_actual_prepost_content_hashes_equal") is not True:
        raise ValueError("ROOT169 source snapshot pre/post content closure is not PASS")
    if root169_report.get("status") not in {"PASS_F3_S2_FINE_BI4_HASHED_STABLE", "PASS_F3_S2_FINE_BI4_HASHED_STABLE_ROOT169"}:
        raise ValueError("ROOT169 snapshot report is not a successful stable hash report")
    report_sha = sha256(args.root169_report)
    if root169_proof.get("report_sha256") not in (None, report_sha):
        raise ValueError("ROOT169 proof does not bind the supplied snapshot report")
    return {
        "request": request,
        "receipt": receipt,
        "proof": proof,
        "request_sha256": request_sha,
        "actual_output_bytes": actual_bytes,
        "root169_proof": root169_proof,
        "root169_report": root169_report,
    }


def canonical(value: dict[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False, default=str).encode()).hexdigest()


def primary_worker() -> Path:
    path = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_fine_selected_native_observer_v1.py"
    if path.is_file() and not path.is_symlink():
        return path
    local = LOCAL_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_fine_selected_native_observer_v1.py"
    if local.is_file() and not local.is_symlink():
        return local
    raise FileNotFoundError("fine selected observer worker is missing from primary and local trees")


def build(args: argparse.Namespace) -> dict[str, Any]:
    validated = validate_terminal_inputs(args)
    worker = primary_worker()
    small_paths: list[tuple[Path, str]] = [
        (args.solver_request, "ROOT170 solver request"),
        (args.terminal_receipt, "ROOT170 terminal receipt"),
        (args.terminal_proof, "ROOT170 terminal proof"),
        (args.root169_proof, "ROOT169 snapshot proof"),
        (args.root169_report, "ROOT169 snapshot report"),
        (args.runparts, "ROOT170 RunPARTs"),
        (args.generated_xml, "ROOT170 generated XML"),
        (worker, "fine selected observer worker"),
        (STREAM_WORKER, "F3 full-native stream safety dependency"),
        (HEADER_WORKER, "F3 native header dependency"),
        (PHYSICAL_WORKER, "generic physical observer dependency"),
        (args.calibration_contract, "F3 observer calibration contract"),
        (DECODER, "official BI4 decoder"),
        (DECODER_SOURCE, "official BI4 decoder source"),
        (RUNTIME_V2, "runtime v2"),
        (RUNTIME_V6, "runtime v6"),
        (RUNTIME_V8, "runtime v8"),
        (DISPATCH, "dispatch v8"),
        (STRICT, "strict dispatch v8"),
    ]
    records = {str(regular(path, label)): record(path, label) for path, label in small_paths}
    records[str(PYTHON)] = record_literal(PYTHON, "literal venv interpreter")
    raw_root = args.raw_root.expanduser().resolve()
    if not raw_root.is_dir() or raw_root.is_symlink():
        raise FileNotFoundError(f"ROOT170 deferred native output root is not a directory: {raw_root}")
    query_times = [0.0, 2.0, 4.0, 6.0, 8.0, float(args.expected_final_time_s)]
    worker_path = str(worker.resolve())
    output_path = "{attempt_root}/observer/f3_s2_fine_selected_native_observer_v1.json"
    command = [
        str(PYTHON), worker_path,
        "--raw-root", str(raw_root),
        "--runparts", str(args.runparts.expanduser().resolve()),
        "--generated-xml", str(args.generated_xml.expanduser().resolve()),
        "--decoder", str(DECODER),
        "--decoder-source", str(DECODER_SOURCE),
        "--calibration-contract", str(args.calibration_contract.expanduser().resolve()),
        "--output", output_path,
        "--scratch-root", "{attempt_root}/scratch/bi4_decode",
        "--expected-frame-count", str(args.expected_frame_count),
        "--expected-final-time-s", repr(float(args.expected_final_time_s)),
        "--frames", "0", str(args.expected_frame_count - 1),
        "--query-times", *(repr(value) for value in query_times),
        "--decoder-timeout-s", "300",
        "--max-decoder-log-bytes", "65536",
        "--max-decoder-scratch-bytes", str(256 * 1024 * 1024),
    ]
    input_files = sorted(records)
    hashes = {path: records[path]["sha256"] for path in input_files}
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "variant_schema": VARIANT,
        "status": "READY_FOR_PARENT_V8_F3_FINE_SELECTED_NATIVE_OBSERVER",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "family_id": FAMILY_ID,
        "sentinel_id": SENTINEL_ID,
        "physical_case_id": PHYSICAL_CASE_ID,
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
        "deferred_input_files": [str(raw_root)],
        "deferred_input_policy": "ROOT170 terminal raw tree is read only after parent reservation; selected frame 0/final and RunPARTs brackets receive full pre/decode/post SHA+stat closure",
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 1800,
        "max_memory_bytes": 512 * 1024**2,
        "estimated_storage_bytes": 32 * 1024**2,
        "estimated_peak_memory_bytes": 256 * 1024**2,
        "estimated_input_read_bytes": sum(item["bytes"] for item in records.values()),
        "estimated_native_read_bytes": int(args.estimated_native_bytes),
        "estimated_hdf5_read_bytes": 0,
        "execution_allowed": True,
        "launch_disabled": False,
        "solver_started": False,
        "gencase_launch": False,
        "solver_launch": False,
        "hdf5_read": False,
        "native_payload_read": True,
        "raw_directory_scan": False,
        "output_root": "{attempt_root}",
        "output": {"atomic": True, "refuse_overwrite": True, "path": output_path},
        "source_binding": {
            "schema": VARIANT,
            "root170_solver_request_path": str(args.solver_request.expanduser().resolve()),
            "root170_solver_request_sha256": validated["request_sha256"],
            "root170_terminal_receipt_path": str(args.terminal_receipt.expanduser().resolve()),
            "root170_terminal_proof_path": str(args.terminal_proof.expanduser().resolve()),
            "root170_terminal_output_bytes": validated["actual_output_bytes"],
            "root169_snapshot_proof_path": str(args.root169_proof.expanduser().resolve()),
            "root169_snapshot_report_path": str(args.root169_report.expanduser().resolve()),
            "root169_native_bi4_sha256": ROOT169_BI4_SHA,
            "root169_native_bi4_bytes": ROOT169_BI4_BYTES,
            "fine_grid_dp_m": DP_M,
            "query_times_s": query_times,
            "query_semantics": "actual RunPARTs and decoder timestamps; exact/bracketed labels only; no particle/time interpolation or extrapolation",
            "native_massfluid_required": True,
            "continuum_owner_mass": "UNKNOWN_NOT_DERIVED_FROM_PARTICLE_SUM",
            "full_pre_decode_post_decode_sha_and_stat_per_selected_part": True,
            "decoder_process_group_cleanup": True,
        },
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": "parent-v8-audit",
            "cpu_parent_binding": "required",
            "payload_read": "selected Part files only after parent reservation",
            "solver_launch": "forbidden",
        },
        "qualification_stage": "stage2_f3_s2_fine_selected_native_fields_pending_parent_guard",
        "scientific_qualification": {
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
            "reason": "fine selected native header/finite/identity/time audit only; ROOT170 is a source-bound canary and does not establish dynamics, spatial truth, or event qualification",
        },
    }
    payload["sha256"] = canonical(payload)
    return payload


def write_once(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
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
    if not str(PYTHON).endswith("/.venv/bin/python"):
        raise AssertionError("literal venv binding changed")
    if ROOT169_BI4_BYTES <= 0 or len(ROOT169_BI4_SHA) != 64:
        raise AssertionError("ROOT169 fine snapshot binding is incomplete")
    return {
        "status": "PASS",
        "schema": SCHEMA,
        "variant_schema": VARIANT,
        "fine_grid_dp_m": DP_M,
        "selected_query_times_s": [0.0, 2.0, 4.0, 6.0, 8.0, "ACTUAL_FINAL_TIME_REQUIRED"],
        "requires_root170_terminal_receipt_and_proof": True,
        "root169_bi4_sha_bound": ROOT169_BI4_SHA,
        "native_payload_read": "parent_worker_after_reservation",
        "solver_started": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build-request", action="store_true")
    parser.add_argument("--solver-request", type=Path)
    parser.add_argument("--terminal-receipt", type=Path)
    parser.add_argument("--terminal-proof", type=Path)
    parser.add_argument("--root169-proof", type=Path)
    parser.add_argument("--root169-report", type=Path)
    parser.add_argument("--raw-root", type=Path)
    parser.add_argument("--runparts", type=Path)
    parser.add_argument("--generated-xml", type=Path)
    parser.add_argument("--calibration-contract", type=Path, default=CALIBRATION)
    parser.add_argument("--expected-frame-count", type=int)
    parser.add_argument("--expected-final-time-s", type=float)
    parser.add_argument("--final-time-tolerance-s", type=float, default=1.0e-9)
    parser.add_argument("--estimated-native-bytes", type=int)
    parser.add_argument("--output", type=Path, default=LOCAL_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/f3-s2-fine-selected-native-observer-root171-001.json")
    parser.add_argument("--launch-commit")
    parser.add_argument("--case-id", default="F3_S2_MATCHED_FINE_SELECTED_NATIVE_OBSERVER_ROOT171")
    parser.add_argument("--attempt-id", default="f3-s2-matched-fine-selected-native-observer-root-171-001")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2))
        return 0
    required = (
        args.solver_request, args.terminal_receipt, args.terminal_proof,
        args.root169_proof, args.root169_report, args.raw_root, args.runparts,
        args.generated_xml, args.expected_frame_count, args.expected_final_time_s,
        args.estimated_native_bytes, args.launch_commit,
    )
    if any(value is None for value in required):
        parser.error("--build-request requires ROOT170 terminal/source paths, frame/time/byte estimates, and --launch-commit")
    try:
        payload = build(args)
        write_once(args.output, payload)
    except BaseException as exc:
        print(json.dumps({"status": "FAILED_F3_FINE_SELECTED_NATIVE_REQUEST_BUILD", "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=False), flush=True)
        return 1
    print(json.dumps({"status": payload["status"], "output": str(args.output.expanduser().resolve()), "selected_query_times_s": [0.0, 2.0, 4.0, 6.0, 8.0, args.expected_final_time_s], "native_payload_read": "parent_worker_after_reservation", "solver_started": False}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
