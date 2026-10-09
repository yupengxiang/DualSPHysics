#!/usr/bin/env python3
"""Build the ROOT246 source-bound compact JSON diagnostic request.

The builder consumes only the four actual-verification proof JSON files and
the small report/request/receipt files named by those proofs.  It records
their exact bytes/statistics in a new manifest and request.  Native payloads
are never followed, hashed, or listed as inputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Any

import stage2_f1_s2_three_grid_unified_diagnostic_v1 as worker


HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[4]
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
PYVENVCFG = PYTHON.parent.parent / "pyvenv.cfg"
CONTRACT = HERE / "stage2_f1_s2_three_grid_unified_diagnostic_contract_v1.json"
BUILDER = HERE / "stage2_f1_s2_three_grid_unified_diagnostic_request_v1.py"
WORKER = HERE / "stage2_f1_s2_three_grid_unified_diagnostic_v1.py"
REQUEST_SCHEMA = "ds02.request.v1"
VARIANT_SCHEMA = "ds02.stage2.f1-s2.three-grid-unified-diagnostic-request.v1"
MANIFEST_SCHEMA = worker.MANIFEST_SCHEMA
MAX_SMALL_BYTES = 4 * 1024 * 1024
MAX_PYTHON_BYTES = 32 * 1024 * 1024
ROOT246_STATUS = "READY_FOR_PARENT_V8_F1_S2_THREE_GRID_UNIFIED_DIAGNOSTIC_ROOT246"


class BuildFailure(RuntimeError):
    pass


def _abs(path: str | Path) -> Path:
    return Path(path).expanduser().absolute()


def _stat_tuple(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _record(path: str | Path, label: str, expected_sha: str | None = None) -> dict[str, Any]:
    target = _abs(path)
    if target.suffix.lower() in {".bi4", ".h5", ".hdf5", ".vtk", ".vtu"}:
        raise BuildFailure(f"{label} is a forbidden production payload: {target}")
    if target.is_symlink() or not target.is_file():
        raise BuildFailure(f"{label} is not a regular non-symlink file: {target}")
    before = target.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_SMALL_BYTES:
        raise BuildFailure(f"{label} is missing, unsafe, or over {MAX_SMALL_BYTES} bytes: {target}")
    data = target.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    after = target.stat()
    if _stat_tuple(before) != _stat_tuple(after):
        raise BuildFailure(f"{label} changed during bounded read: {target}")
    if expected_sha and expected_sha not in {"PARENT_AFTER_RESERVATION", "UNKNOWN"} and digest != expected_sha.lower():
        raise BuildFailure(f"{label} SHA mismatch: {digest} != {expected_sha}")
    return {"path": str(target), "label": label, "bytes": int(after.st_size), "sha256": digest, "device": int(after.st_dev), "inode": int(after.st_ino), "mtime_ns": int(after.st_mtime_ns), "ctime_ns": int(after.st_ctime_ns), "link_count": int(after.st_nlink)}


def _record_literal_python(path: Path) -> dict[str, Any]:
    path = _abs(path)
    if not path.is_symlink():
        raise BuildFailure(f"literal venv Python must remain a symlink: {path}")
    target = path.resolve(strict=True)
    if target.is_symlink() or not target.is_file():
        raise BuildFailure(f"literal venv Python resolved target is unsafe: {target}")
    link_before = path.lstat()
    target_before = target.stat()
    if target_before.st_size > MAX_PYTHON_BYTES:
        raise BuildFailure("resolved Python interpreter exceeds bounded provenance size")
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    target_after = target.stat()
    link_after = path.lstat()
    if _stat_tuple(target_before) != _stat_tuple(target_after) or _stat_tuple(link_before) != _stat_tuple(link_after):
        raise BuildFailure("literal venv Python changed while being recorded")
    return {"path": str(path), "label": "literal venv Python argv0", "bytes": int(target_after.st_size), "sha256": digest, "device": int(target_after.st_dev), "inode": int(target_after.st_ino), "mtime_ns": int(target_after.st_mtime_ns), "ctime_ns": int(target_after.st_ctime_ns), "link_count": int(target_after.st_nlink), "literal_argv0": True, "resolved_target": str(target), "symlink_device": int(link_after.st_dev), "symlink_inode": int(link_after.st_ino), "symlink_mtime_ns": int(link_after.st_mtime_ns), "symlink_ctime_ns": int(link_after.st_ctime_ns)}


def _json(path: str | Path, label: str, expected_sha: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    record = _record(path, label, expected_sha)
    try:
        value = json.loads(Path(record["path"]).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BuildFailure(f"{label} is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise BuildFailure(f"{label} must contain a JSON object")
    return value, record


def _write_once(path: str | Path, value: Any) -> None:
    target = _abs(path)
    if target.exists() or target.is_symlink():
        raise BuildFailure(f"refusing to overwrite output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _proof_sha(value: str | None, label: str) -> str:
    if value is None:
        raise BuildFailure(f"{label} SHA is required")
    value = str(value)
    if len(value) != 64 or any(char not in "0123456789abcdefABCDEF" for char in value):
        raise BuildFailure(f"{label} SHA must be 64 hexadecimal characters")
    return value.lower()


def _prepare_evidence(label: str, proof_path: Path, proof_sha: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    proof, proof_record = _json(proof_path, f"ROOT246 {label} proof", _proof_sha(proof_sha, f"{label} proof"))
    if proof.get("schema") != "ds02.stage2.root-actual-verification.v1" or not str(proof.get("status", "")).startswith("VERIFIED_ACTUAL"):
        raise BuildFailure(f"{label} proof is not a verified actual proof")
    paths = {"proof_path": proof_path, "report_path": Path(str(proof.get("report", ""))), "request_path": Path(str(proof.get("request", ""))), "receipt_path": Path(str(proof.get("receipt", "")))}
    hashes = {"proof_sha256": proof_sha, "report_sha256": proof.get("report_sha256"), "request_sha256": proof.get("request_sha256"), "receipt_sha256": proof.get("receipt_sha256")}
    for key in ("report_sha256", "request_sha256", "receipt_sha256"):
        if not isinstance(hashes[key], str):
            raise BuildFailure(f"{label} proof lacks {key}")
    records = [proof_record]
    report, report_record = _json(paths["report_path"], f"ROOT246 {label} report", hashes["report_sha256"])
    request, request_record = _json(paths["request_path"], f"ROOT246 {label} request", hashes["request_sha256"])
    receipt, receipt_record = _json(paths["receipt_path"], f"ROOT246 {label} receipt", hashes["receipt_sha256"])
    if receipt.get("schema") != "ds02.execution-receipt.v1" or receipt.get("status") != "completed" or int(receipt.get("returncode", -1)) != 0:
        raise BuildFailure(f"{label} producer receipt is not completed with returncode 0")
    if receipt.get("request_sha256") and receipt["request_sha256"] != hashes["request_sha256"]:
        raise BuildFailure(f"{label} producer receipt request SHA does not match proof")
    if request.get("family_id") not in {None, "F1"} or request.get("sentinel_id") not in {None, "F1-S2"}:
        raise BuildFailure(f"{label} producer request is not F1-S2")
    records.extend([report_record, request_record, receipt_record])
    evidence = {"label": label, "proof_path": str(_abs(paths["proof_path"])), "proof_sha256": _proof_sha(proof_sha, f"{label} proof"), "report_path": str(_abs(paths["report_path"])), "report_sha256": hashes["report_sha256"], "request_path": str(_abs(paths["request_path"])), "request_sha256": hashes["request_sha256"], "receipt_path": str(_abs(paths["receipt_path"])), "receipt_sha256": hashes["receipt_sha256"]}
    return evidence, records


def build(*, output_request: Path, output_manifest: Path, owner_proof: Path, support_proof: Path, query1_proof: Path, query234_proof: Path, owner_sha: str, support_sha: str, query1_sha: str, query234_sha: str) -> dict[str, Any]:
    evidence: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    for label, path, sha in (("owner", owner_proof, owner_sha), ("support", support_proof, support_sha), ("query1", query1_proof, query1_sha), ("query234", query234_proof, query234_sha)):
        item, item_records = _prepare_evidence(label, path, sha)
        evidence.append(item)
        records.extend(item_records)
    static = [
        _record(WORKER, "ROOT246 worker"),
        _record(BUILDER, "ROOT246 request builder"),
        _record(CONTRACT, "ROOT246 contract"),
        _record(PYVENVCFG, "literal venv pyvenv.cfg"),
        _record_literal_python(PYTHON),
    ]
    records.extend(static)
    unique: dict[str, dict[str, Any]] = {record["path"]: record for record in records}
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "status": ROOT246_STATUS,
        "family_id": "F1",
        "sentinel_id": "F1-S2",
        "physical_case_id": worker.PHYSICAL_CASE,
        "evidence": evidence,
        "contract_path": str(_abs(CONTRACT)),
        "contract_sha256": next(record["sha256"] for record in static if record["path"] == str(_abs(CONTRACT))),
        "source_only_preparation": {"production_native_payload_read": False, "production_h5_vtk_read": False, "production_solver_launch": False, "ledger_mutation": False, "qualification_credit": 0},
        "worker_read_policy": {"small_json_only": True, "max_json_bytes": MAX_SMALL_BYTES, "deferred_native_payloads": False, "interpolation": False},
    }
    manifest_path = _abs(output_manifest)
    _write_once(manifest_path, manifest)
    manifest_record = _record(manifest_path, "ROOT246 manifest")
    unique[manifest_record["path"]] = manifest_record
    input_records = list(unique.values())
    input_files = [record["path"] for record in input_records]
    input_sha256 = {record["path"]: record["sha256"] for record in input_records}
    command = [str(_abs(PYTHON)), "-B", str(_abs(WORKER)), "--run", "--manifest", "{attempt_root}/inputs/f1_s2_three_grid_unified_diagnostic_manifest_v1.json", "--output", "{attempt_root}/audit/f1_s2_three_grid_unified_diagnostic_v1.json"]
    request = {
        "schema": REQUEST_SCHEMA,
        "variant_schema": VARIANT_SCHEMA,
        "status": ROOT246_STATUS,
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "request_id": "f1-s2-three-grid-unified-diagnostic-root246-001",
        "family_id": "F1",
        "sentinel_id": "F1-S2",
        "physical_case_id": worker.PHYSICAL_CASE,
        "case_id": "F1_S2_THREE_GRID_UNIFIED_DIAGNOSTIC_ROOT246",
        "attempt_id": "f1-s2-three-grid-unified-diagnostic-root246-001",
        "command": command,
        "literal_venv_invocation": {"argv0": str(_abs(PYTHON)), "pyvenv_cfg": str(_abs(PYVENVCFG)), "argv0_must_remain_literal": True},
        "cwd": str(_abs(PROJECT)),
        "worktree_root": str(_abs(PROJECT)),
        "manifest_source_path": str(manifest_path),
        "manifest_input_rebind": {"command_manifest": "{attempt_root}/inputs/f1_s2_three_grid_unified_diagnostic_manifest_v1.json", "source_manifest": str(manifest_path), "parent_must_materialize_under_attempt_root": True},
        "input_files": input_files,
        "input_sha256": input_sha256,
        "evidence": evidence,
        "resources": {"cpu_threads": 1, "omp_threads": 1, "gpu": False, "memory_max_bytes": 1024 * 1024 * 1024, "external_storage_max_bytes": 64 * 1024 * 1024, "home_storage_max_bytes": 16 * 1024 * 1024, "max_wall_seconds": 600, "log_max_bytes": 262144, "parent_guard_required": True},
        "storage_scope": {"output_root": "{attempt_root}", "compact_report_only": True, "native_payloads_allowed": False, "h5_vtk_allowed": False},
        "source_binding": {"worker": str(_abs(WORKER)), "contract": str(_abs(CONTRACT)), "proofs_and_small_reports": True, "owner_mass_kg": 340.0, "query_times_s": [1.0, 2.0, 3.0, 4.0], "interpolation": "FORBIDDEN", "world_orientation": "UNKNOWN", "scientific_qualification": worker.QUALIFICATION},
        "launch_policy": {"solver_started": False, "native_payload_read": False, "hdf5_read": False, "vtk_read": False, "ledger_mutation": False, "qualification_credit": 0},
        "next_task_scope": {"output_cadence_isolation": "separate actual request with common receipt -tout:0.005", "time_step_isolation": "blocked until explicit source CFL/dt/CoefDtMin binding", "neighbor_grid_truth": False},
        "builder_source": str(_abs(BUILDER)),
        "builder_source_sha256": next(record["sha256"] for record in static if record["path"] == str(_abs(BUILDER))),
    }
    _write_once(output_request, request)
    return request


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="f1-s2-root246-builder-") as name:
        path = Path(name) / "small.json"
        path.write_text("{}\n", encoding="utf-8")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert _record(path, "fixture", digest)["sha256"] == digest
        try:
            _record(Path(name) / "payload.bi4", "forbidden")
        except BuildFailure:
            pass
        else:
            raise AssertionError("forbidden payload suffix was accepted")
    print("PASS_F1_S2_ROOT246_REQUEST_BUILDER_SELFTEST")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build", action="store_true")
    parser.add_argument("--output-request", type=Path)
    parser.add_argument("--output-manifest", type=Path)
    parser.add_argument("--owner-proof", type=Path)
    parser.add_argument("--support-proof", type=Path)
    parser.add_argument("--query1-proof", type=Path)
    parser.add_argument("--query234-proof", type=Path)
    parser.add_argument("--owner-sha256")
    parser.add_argument("--support-sha256")
    parser.add_argument("--query1-sha256")
    parser.add_argument("--query234-sha256")
    args = parser.parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    required = [args.output_request, args.output_manifest, args.owner_proof, args.support_proof, args.query1_proof, args.query234_proof, args.owner_sha256, args.support_sha256, args.query1_sha256, args.query234_sha256]
    if any(value is None for value in required):
        parser.error("all output/proof/SHA arguments are required with --build")
    try:
        request = build(output_request=args.output_request, output_manifest=args.output_manifest, owner_proof=args.owner_proof, support_proof=args.support_proof, query1_proof=args.query1_proof, query234_proof=args.query234_proof, owner_sha=args.owner_sha256, support_sha=args.support_sha256, query1_sha=args.query1_sha256, query234_sha=args.query234_sha256)
    except Exception as exc:
        print(json.dumps({"schema": VARIANT_SCHEMA, "status": "BLOCKED", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps({"schema": VARIANT_SCHEMA, "status": request["status"], "request": str(_abs(args.output_request)), "manifest": str(_abs(args.output_manifest)), "input_count": len(request["input_files"])}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
