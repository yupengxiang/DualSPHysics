#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Build the ROOT243 deferred ROOT150 compact-observer request.

Only ROOT150 proof/request/receipt and source code are read and hashed here.
The 14,825,462-byte observer report is stat'ed and bound to the proof but is
never opened or hashed by this builder.  The guarded worker performs that
read after the parent reservation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
HERE = Path(__file__).resolve().parent
WORKER = HERE / "stage2_f3_s2_coarse_deferred_json_observer_v1.py"
CONTRACT = HERE / "stage2_f3_s2_coarse_deferred_json_observer_contract_v1.json"
SCHEMA = "ds02.request.v1"
VARIANT = "ds02.stage2.f3-s2.coarse-deferred-json-observer-request.v1"
CASE = "F3_S2_COARSE_DEFERRED_JSON_OBSERVER_ROOT243"
ATTEMPT = "f3-s2-coarse-deferred-json-observer-v1-root-243-001"
QUERY_TIMES_S = (0.0, 2.0, 4.0, 6.0, 8.0)
MAX_BUILDER_REPORT_BYTES = 64 * 1024 * 1024


def _regular(path: Path, label: str) -> Path:
    raw = path.expanduser()
    if raw.is_symlink() or not raw.is_file():
        raise FileNotFoundError(f"{label}: {raw}")
    resolved = raw.resolve()
    if resolved.is_symlink() or not resolved.is_file():
        raise FileNotFoundError(f"{label} is not regular: {resolved}")
    return resolved


def _stat(path: Path) -> tuple[int, int, int, int, int, int]:
    st = path.stat()
    return (int(st.st_size), int(st.st_mtime_ns), int(st.st_ctime_ns), int(st.st_dev), int(st.st_ino), int(st.st_mode))


def _stat_dict(v: tuple[int, int, int, int, int, int]) -> dict[str, int]:
    return {"bytes": v[0], "mtime_ns": v[1], "ctime_ns": v[2], "st_dev": v[3], "st_ino": v[4], "mode": v[5]}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hex(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value.lower()):
        raise ValueError(f"{label} is not SHA-256")
    return value.lower()


def _small_json(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _regular(path, label)
    before = _stat(path)
    data = path.read_bytes()
    after = _stat(path)
    if before != after:
        raise RuntimeError(f"{label} changed during read")
    value = json.loads(data.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} is not an object")
    return value, {"path": str(path), "bytes": len(data), "sha256": _sha(data), "stat_before": _stat_dict(before), "stat_after": _stat_dict(after), "stable_read": True, "content_scope": "small_json_hashed_by_builder"}


def _code_record(path: Path, label: str) -> dict[str, Any]:
    path = _regular(path, label)
    before = _stat(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    after = _stat(path)
    if before != after:
        raise RuntimeError(f"{label} changed during hash")
    return {"path": str(path), "bytes": before[0], "sha256": digest.hexdigest(), "stat_before": _stat_dict(before), "stat_after": _stat_dict(after), "stable_read": True, "label": label, "content_scope": "source_code_hashed_by_builder"}


def _literal_python() -> dict[str, Any]:
    raw = PYTHON.expanduser()
    if not raw.is_symlink():
        raise ValueError(f"literal venv interpreter must remain a symlink: {raw}")
    resolved = _regular(raw.resolve(), "resolved venv interpreter")
    cfg = _regular(raw.parent.parent / "pyvenv.cfg", "pyvenv.cfg")
    return {"literal_path": str(raw), "resolved_path": str(resolved), "literal_is_symlink": True, "resolved": _code_record(resolved, "resolved venv interpreter"), "pyvenv_cfg": _code_record(cfg, "pyvenv.cfg")}


def _proof_and_deferred(proof_path: Path, report_path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    proof, proof_record = _small_json(proof_path, "ROOT150 verification proof")
    if proof.get("schema") != "ds02.stage2.root-actual-verification.v1" or "ACTUAL" not in str(proof.get("status", "")):
        raise ValueError("ROOT150 proof is not actual")
    expected_report = _regular(Path(str(proof.get("report", ""))), "ROOT150 proof report")
    report_path = _regular(report_path, "ROOT150 deferred report")
    if expected_report != report_path:
        raise ValueError("report path differs from ROOT150 proof")
    report_bytes = int(proof.get("report_bytes", -1))
    if report_bytes <= 0 or report_bytes > MAX_BUILDER_REPORT_BYTES:
        raise ValueError(f"invalid deferred report byte count {report_bytes}")
    report_stat = _stat(report_path)
    if report_stat[0] != report_bytes:
        raise ValueError("deferred report current size differs from proof")
    report_sha = _hex(proof.get("report_sha256"), "ROOT150 report SHA")
    request_path = _regular(Path(str(proof.get("request", ""))), "ROOT150 request")
    receipt_path = _regular(Path(str(proof.get("receipt", ""))), "ROOT150 receipt")
    request, request_record = _small_json(request_path, "ROOT150 request")
    receipt, receipt_record = _small_json(receipt_path, "ROOT150 receipt")
    if request_record["sha256"] != _hex(proof.get("request_sha256"), "ROOT150 request SHA"):
        raise ValueError("ROOT150 request SHA differs")
    if receipt_record["sha256"] != _hex(proof.get("receipt_sha256"), "ROOT150 receipt SHA"):
        raise ValueError("ROOT150 receipt SHA differs")
    if str(receipt.get("status", "")).lower() not in {"completed", "complete", "success", "completed_development_unknown"}:
        raise ValueError("ROOT150 receipt is not terminal")
    records = [proof_record, request_record, receipt_record]
    deferred = {
        "path": str(report_path),
        "expected_sha256": report_sha,
        "expected_bytes": report_bytes,
        "proof_stat_at_build": _stat_dict(report_stat),
        "content_read_by_builder": False,
        "worker_read_policy": "after-parent-reservation-single-stream-pre-stat-read-post-stat-sha-parse",
        "native_payload_read": False,
    }
    binding = {"proof": proof_record, "request": request_record, "receipt": receipt_record}
    return proof, binding, deferred, records


def _canonical(payload: dict[str, Any]) -> str:
    body = {k: v for k, v in payload.items() if k != "canonical_sha256"}
    return _sha(json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())


def build(args: argparse.Namespace) -> dict[str, Any]:
    proof_path = args.proof.expanduser().resolve()
    report_path = args.report.expanduser().resolve()
    proof, binding, deferred, records = _proof_and_deferred(proof_path, report_path)
    worker = _code_record(WORKER, "ROOT243 guarded deferred-json worker")
    contract = _code_record(CONTRACT, "ROOT243 worker contract")
    py = _literal_python()
    input_records = {r["path"]: r for r in records}
    input_records[worker["path"]] = worker
    input_records[contract["path"]] = contract
    input_records[py["resolved"]["path"]] = py["resolved"]
    input_records[py["pyvenv_cfg"]["path"]] = py["pyvenv_cfg"]
    input_files = sorted(input_records)
    input_hashes = {path: input_records[path]["sha256"] for path in input_files}
    command = [str(PYTHON), str(WORKER), "--report", str(report_path), "--proof", str(proof_path), "--query-times", *(repr(q) for q in QUERY_TIMES_S), "--output", "{attempt_root}/observer/f3_s2_coarse_deferred_json_observer_v1.json"]
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "variant_schema": VARIANT,
        "status": "READY_FOR_PARENT_V8_DEFERRED_LARGE_JSON_F3_COARSE_ROOT243",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "family_id": "F3",
        "sentinel_id": "F3-S2",
        "physical_case_id": "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT",
        "case_id": args.case_id,
        "attempt_id": args.attempt_id,
        "launch_commit": args.launch_commit,
        "cwd": str(PRIMARY / "lagrangian-fluid-lab"),
        "worktree_root": str(PRIMARY),
        "command": command,
        "input_files": input_files,
        "input_hashes": input_hashes,
        "input_sha256": input_hashes,
        "input_records": input_records,
        "deferred_input_files": [str(report_path)],
        "deferred_input_records": {str(report_path): deferred},
        "deferred_input_policy": "v8-parent-does-not-hash-deferred-report; worker performs full pre/post stat and one content SHA pass only after reservation",
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 1800,
        "max_memory_bytes": 2 * 1024**3,
        "max_log_bytes": 64 * 1024,
        "estimated_storage_bytes": 2 * 1024 * 1024,
        "estimated_peak_memory_bytes": 256 * 1024 * 1024,
        "estimated_input_read_bytes": sum(int(r["bytes"]) for r in input_records.values()) + report_bytes_for_estimate(deferred),
        "estimated_small_input_read_bytes": sum(int(r["bytes"]) for r in input_records.values()),
        "estimated_deferred_full_report_bytes": int(deferred["expected_bytes"]),
        "estimated_deferred_content_passes": 1,
        "estimated_hdf5_read_bytes": 0,
        "execution_allowed": True,
        "launch_disabled": False,
        "solver_started": False,
        "gencase_launch": False,
        "solver_launch": False,
        "native_payload_read": False,
        "hdf5_read": False,
        "raw_directory_scan": False,
        "output_root": "{attempt_root}",
        "output": {"atomic": True, "refuse_overwrite": True, "path": "{attempt_root}/observer/f3_s2_coarse_deferred_json_observer_v1.json", "max_bytes": 2 * 1024 * 1024},
        "source_binding": {
            "root150_proof": str(proof_path),
            "root150_report": deferred,
            "query_times_s": list(QUERY_TIMES_S),
            "saved_endpoint_only": True,
            "interpolation": False,
            "adjacent_grid_truth": False,
            "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
        "literal_venv": py,
        "canonical_sha256": "",
    }
    payload["canonical_sha256"] = _canonical(payload)
    return payload


def report_bytes_for_estimate(deferred: dict[str, Any]) -> int:
    return int(deferred["expected_bytes"])


def self_test() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="ds02-root243-builder-") as directory:
        root = Path(directory)
        report = root / "report.json"
        request = root / "request.json"
        receipt = root / "receipt.json"
        report.write_text("{}\n", encoding="utf-8")
        request.write_text(json.dumps({"physical_case_id": "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT"}) + "\n", encoding="utf-8")
        receipt.write_text(json.dumps({"status": "completed"}) + "\n", encoding="utf-8")
        def sha(path: Path) -> str: return _sha(path.read_bytes())
        proof = root / "proof.json"
        proof.write_text(json.dumps({"schema": "ds02.stage2.root-actual-verification.v1", "status": "VERIFIED_ACTUAL_FIXTURE", "report": str(report), "report_sha256": sha(report), "report_bytes": report.stat().st_size, "request": str(request), "request_sha256": sha(request), "receipt": str(receipt), "receipt_sha256": sha(receipt)}) + "\n", encoding="utf-8")
        payload = build(argparse.Namespace(proof=proof, report=report, case_id=CASE, attempt_id=ATTEMPT, launch_commit="fixture"))
        if payload["deferred_input_records"][str(report)]["content_read_by_builder"] is not False:
            raise AssertionError("builder read deferred report")
        if str(report) in payload["input_files"]:
            raise AssertionError("deferred report was charged as small input")
    return {"status": "PASS", "schema": VARIANT, "deferred_report_not_opened": True, "report_stat_bound": True}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--proof", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--case-id", default=CASE)
    parser.add_argument("--attempt-id", default=ATTEMPT)
    parser.add_argument("--launch-commit", default="unbound-until-parent-forward")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.self_test:
        print(json.dumps(self_test(), sort_keys=True))
        return 0
    if args.proof is None or args.report is None or args.output is None:
        parser.error("--proof, --report, and --output are required")
    payload = build(args)
    output = args.output.expanduser().resolve()
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "output": str(output), "canonical_sha256": payload["canonical_sha256"], "deferred_report_bytes": payload["estimated_deferred_full_report_bytes"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
