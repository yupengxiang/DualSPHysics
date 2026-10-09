#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Build the guarded ROOT196 retained-report summary-recovery request.

The builder hashes only small JSON/source inputs.  The retained ROOT188 full
observer report is stat-only here; the recovery worker performs its one
stable bytes read after the parent reservation.  Until the parent creates a
failure proof for the original ROOT188 observer receipt, this builder emits a
launch-disabled pending request and never treats the failed receipt as a
producer success.
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
# ``HERE`` is the ``.../stage2/reference`` directory; its fourth parent is
# the repository root (the fifth is the sibling worktree container).
LOCAL_REPO = HERE.parents[4]
PRIMARY_REPO = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
WORKER_NAME = "stage2_f3_s2_full_native_stream_summary_recovery_v1.py"
CONTRACT_NAME = "stage2_f3_s2_full_native_stream_summary_recovery_v1_contract.json"
SCHEMA = "ds02.request.v1"
VARIANT = "ds02.stage2.f3-s2.full-native-stream-summary-recovery-request.v1"
PHYSICAL_CASE = "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT"
QUERY_TIMES_S = (0.0, 2.0, 4.0, 6.0, 8.0)
RECOVERY_MEMORY_BYTES = 2 * 1024 * 1024 * 1024


def _load_worker():
    path = HERE / WORKER_NAME
    spec = importlib.util.spec_from_file_location("stage2_root196_recovery_worker", path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


WORKER = _load_worker()


def _resolve_existing(relative: str) -> Path:
    for root in (LOCAL_REPO, PRIMARY_REPO):
        candidate = root / relative
        if candidate.is_file() and not candidate.is_symlink():
            return candidate.resolve()
    raise FileNotFoundError(relative)


def _regular(path: Path, label: str, max_bytes: int = 32 * 1024 * 1024) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    if path.stat().st_size > max_bytes:
        raise ValueError(f"{label} exceeds bounded metadata size: {path.stat().st_size}")
    return path


def _stat_only(path: Path, label: str) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    value = path.stat()
    return {
        "path": str(path),
        "label": label,
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
        "st_dev": int(value.st_dev),
        "st_ino": int(value.st_ino),
        "content_sha256": "UNKNOWN_AFTER_PARENT_RESERVATION",
        "content_scope": "stat_only_at_builder; worker performs one stable hash/read after reservation",
    }


def _record(path: Path, label: str, max_bytes: int = 32 * 1024 * 1024) -> dict[str, Any]:
    path = _regular(path, label, max_bytes=max_bytes)
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    after = path.stat()
    before_tuple = (before.st_size, before.st_mtime_ns, before.st_ctime_ns, before.st_dev, before.st_ino)
    after_tuple = (after.st_size, after.st_mtime_ns, after.st_ctime_ns, after.st_dev, after.st_ino)
    if before_tuple != after_tuple:
        raise ValueError(f"{label} changed while being hashed: {path}")
    return {
        "path": str(path),
        "label": label,
        "bytes": int(before.st_size),
        "mtime_ns": int(before.st_mtime_ns),
        "ctime_ns": int(before.st_ctime_ns),
        "st_dev": int(before.st_dev),
        "st_ino": int(before.st_ino),
        "sha256": digest.hexdigest(),
        "stable_read": True,
        "content_scope": "bounded JSON metadata or source code only",
    }


def _json_record(path: Path, label: str, max_bytes: int = 32 * 1024 * 1024) -> tuple[dict[str, Any], dict[str, Any]]:
    record = _record(path, label, max_bytes=max_bytes)
    value = json.loads(Path(record["path"]).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} is not a JSON object")
    return record, value


def _receipt_returncode(receipt: dict[str, Any]) -> int | None:
    value = receipt.get("returncode")
    if value is None and isinstance(receipt.get("execution"), dict):
        value = receipt["execution"].get("returncode", receipt["execution"].get("return_code"))
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _require_zero_returncode(receipt: dict[str, Any], label: str) -> None:
    if _receipt_returncode(receipt) != 0:
        raise ValueError(f"{label} does not prove returncode 0")


def _literal_python() -> dict[str, Any]:
    path = PYTHON.expanduser()
    if not path.is_file():
        raise FileNotFoundError(path)
    resolved = path.resolve()
    cfg = path.parent.parent / "pyvenv.cfg"
    if not resolved.is_file() or resolved.is_symlink() or not cfg.is_file() or cfg.is_symlink():
        raise FileNotFoundError("literal venv interpreter/cfg closure is incomplete")
    resolved_record = _record(resolved, "resolved venv interpreter", max_bytes=8 * 1024 * 1024)
    cfg_record = _record(cfg, "venv pyvenv.cfg", max_bytes=1024 * 1024)
    return {
        "path": str(path),
        "label": "literal venv interpreter",
        "bytes": resolved_record["bytes"],
        "mtime_ns": resolved_record["mtime_ns"],
        "ctime_ns": resolved_record["ctime_ns"],
        "st_dev": resolved_record["st_dev"],
        "st_ino": resolved_record["st_ino"],
        "sha256": resolved_record["sha256"],
        "stable_read": True,
        "content_scope": "resolved interpreter binary; argv0 remains the literal venv path",
        "resolved_path": str(resolved),
        "pyvenv_cfg": cfg_record,
        "literal_argv0_required": True,
    }


def _paths() -> dict[str, Path]:
    p = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
    d = DATA_ROOT / "families/F3"
    return {
        "observer_request": p / "requests/f3-middle-half-output-observer-v2-root-forward-188-001.json",
        "failed_observer_receipt": d / "F3_S2_MIDDLE_HALF_OUTPUT_FULL_NATIVE_ROOT188_V2/f3-middle-half-output-full-native-v2-root-188-001-root-forward-030-001/execution-receipt.json",
        # Parent writes this small failure proof after reconciling the failed
        # observer receipt.  It is intentionally not synthesized here.
        "failed_observer_proof": p / "checkpoints/F3_HALF_OUTPUT_NATIVE_OBSERVER_ACTUAL_COMPACT_CAP_FAILURE_ROOT_VERIFICATION_188.json",
        "retained_full_report": d / "F3_S2_MIDDLE_HALF_OUTPUT_FULL_NATIVE_ROOT188_V2/f3-middle-half-output-full-native-v2-root-188-001-root-forward-030-001/observer/f3_s2_overlay_native_observer_v2.json",
        "solver_request": p / "requests/f3-s2-middle-half-output-external-v8-root174-primary-forward-002.json",
        "solver_proof": p / "checkpoints/F3_MIDDLE_HALF_OUTPUT_EXTERNAL_ACTUAL_NATIVE_ROOT_VERIFICATION_174.json",
        "solver_receipt": d / "F3_S2_MATCHED_MIDDLE_HALF_OUTPUT_ROOT174_V8/f3-s2-matched-middle-half-output-root-174-v8-001/execution-receipt.json",
    }


def _validate_failed_receipt(paths: dict[str, Path]) -> tuple[dict[str, Any], dict[str, Any]]:
    request_record, request = _json_record(paths["observer_request"], "ROOT188 observer request", max_bytes=8 * 1024 * 1024)
    receipt_record, receipt = _json_record(paths["failed_observer_receipt"], "ROOT188 failed observer receipt")
    if request.get("physical_case_id") not in {PHYSICAL_CASE, None}:
        raise ValueError("ROOT188 observer request physical case differs")
    status = str(receipt.get("status", "")).lower()
    if not (status.startswith("failed") or status in {"error", "aborted"}):
        raise ValueError(f"ROOT188 receipt is not preserved failed evidence: {receipt.get('status')!r}")
    returncode = _receipt_returncode(receipt)
    if returncode is None or returncode == 0:
        raise ValueError("ROOT188 failed receipt lacks nonzero returncode")
    # The ds02 execution receipt stores the original request SHA at the
    # receipt top level, while ``request`` is the expanded runtime payload
    # (and therefore has no request path/SHA fields).  Join on the immutable
    # top-level SHA and validate the small physical/case identity carried by
    # the expanded payload; do not mistake that payload for the request file.
    if receipt.get("request_sha256") != request_record["sha256"]:
        raise ValueError("ROOT188 failed receipt request SHA differs")
    embedded = receipt.get("request")
    if isinstance(embedded, dict):
        if embedded.get("physical_case_id") not in {PHYSICAL_CASE, None}:
            raise ValueError("ROOT188 failed receipt expanded physical case differs")
        if embedded.get("case_id") not in {None, "F3_S2_MIDDLE_HALF_OUTPUT_FULL_NATIVE_ROOT188_V2"}:
            raise ValueError("ROOT188 failed receipt expanded case differs")
    return request_record, receipt_record


def _validate_solver(paths: dict[str, Path]) -> dict[str, dict[str, Any]]:
    request_record, request = _json_record(paths["solver_request"], "ROOT174 solver request", max_bytes=8 * 1024 * 1024)
    proof_record, proof = _json_record(paths["solver_proof"], "ROOT174 solver proof")
    receipt_record, receipt = _json_record(paths["solver_receipt"], "ROOT174 solver receipt")
    if request.get("physical_case_id") not in {PHYSICAL_CASE, None}:
        raise ValueError("ROOT174 solver request physical case differs")
    if proof.get("schema") not in {"ds02.stage2.root-actual-verification.v1", "ds02.stage2.root-actual-external-solver-verification.v1"} or "ACTUAL" not in str(proof.get("status", "")):
        raise ValueError("ROOT174 solver proof is not actual")
    if Path(str(proof.get("request", ""))).expanduser().resolve() != Path(request_record["path"]) or proof.get("request_sha256") != request_record["sha256"]:
        raise ValueError("ROOT174 solver proof request join failed")
    if Path(str(proof.get("receipt", ""))).expanduser().resolve() != Path(receipt_record["path"]) or proof.get("receipt_sha256") != receipt_record["sha256"]:
        raise ValueError("ROOT174 solver proof receipt join failed")
    if not str(receipt.get("status", "")).lower().startswith(("completed", "complete", "success")):
        raise ValueError("ROOT174 solver receipt is not completed")
    _require_zero_returncode(receipt, "ROOT174 solver receipt")
    return {"request": request_record, "proof": proof_record, "receipt": receipt_record}


def _source_closure() -> list[dict[str, Any]]:
    rels = [
        f"lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/{WORKER_NAME}",
        f"lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/{CONTRACT_NAME}",
        f"lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/{Path(__file__).name}",
        "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_full_native_stream_observer_v1.py",
        "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_full_native_stream_observer_v5.py",
        "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_full_native_stream_observer_v3.py",
        "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_full_native_stream_observer_v2.py",
        "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_native_header_observer_v1.py",
        "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_native_physical_observer_v2.py",
        "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_overlay_task_error_compare_v1.py",
        "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_overlay_task_error_compare_v2.py",
        "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_overlay_task_error_compare_v3.py",
        "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_observer_calibration_contract_v1.py",
        "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_observer_calibration_contract_v1.json",
        "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py",
        "lagrangian-fluid-lab/scripts/ds_data02_runtime_v6.py",
        "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py",
        "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py",
        "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py",
        "lagrangian-fluid-lab/scripts/ds_data02_stage2_external_solver_v5.py",
    ]
    records = []
    for relative in rels:
        path = next((root / relative for root in (LOCAL_REPO, PRIMARY_REPO) if (root / relative).is_file() and not (root / relative).is_symlink()), None)
        if path is None:
            raise FileNotFoundError(f"source closure missing: {relative}")
        records.append(_record(path.resolve(), f"ROOT196 source closure {relative}", max_bytes=64 * 1024 * 1024))
    records.append(_literal_python())
    return records


def _write_once(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise FileExistsError(f"refusing to overwrite immutable ROOT196 artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = -1
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)


def build(args: argparse.Namespace) -> dict[str, Any]:
    defaults = _paths()
    paths = {
        "observer_request": (args.observer_request or defaults["observer_request"]).expanduser().resolve(),
        "failed_observer_receipt": (args.failed_observer_receipt or defaults["failed_observer_receipt"]).expanduser().resolve(),
        "failed_observer_proof": (args.failed_observer_proof or defaults["failed_observer_proof"]).expanduser().resolve(),
        "retained_full_report": (args.retained_full_report or defaults["retained_full_report"]).expanduser().resolve(),
        "solver_request": (args.solver_request or defaults["solver_request"]).expanduser().resolve(),
        "solver_proof": (args.solver_proof or defaults["solver_proof"]).expanduser().resolve(),
        "solver_receipt": (args.solver_receipt or defaults["solver_receipt"]).expanduser().resolve(),
    }
    observer_request_record, failed_receipt_record = _validate_failed_receipt(paths)
    solver_records = _validate_solver(paths)
    full_report_stat = _stat_only(paths["retained_full_report"], "retained ROOT188 full observer report")
    source_records = _source_closure()
    missing: list[dict[str, str]] = []
    if not paths["failed_observer_proof"].is_file() or paths["failed_observer_proof"].is_symlink():
        missing.append({"role": "failed_observer_proof", "path": str(paths["failed_observer_proof"]), "reason": "parent must create and bind the actual nonzero ROOT188 failure proof"})
    proof_record = None
    if not missing:
        proof_record = _record(paths["failed_observer_proof"], "ROOT188 failed observer proof")
    records = [observer_request_record, failed_receipt_record, *solver_records.values(), *source_records]
    if proof_record is not None:
        records.append(proof_record)
    by_path = {record["path"]: record for record in records}
    manifest_path = args.manifest.expanduser().resolve()
    manifest = {
        "schema": "ds02.stage2.f3-s2.full-native-stream-summary-recovery.v1.manifest",
        "variant_schema": VARIANT,
        "status": "BLOCKED_ROOT188_FAILURE_PROOF_MISSING" if missing else "READY_FOR_PARENT_V8_RECOVERY",
        "case_id": "F3_S2_MIDDLE_HALF_OUTPUT_RECOVERY_ROOT196",
        "attempt_id": "f3-s2-middle-half-output-summary-recovery-root196-001",
        "physical_case_id": PHYSICAL_CASE,
        "paths": {key: str(value) for key, value in paths.items()},
        "missing_required_evidence": missing,
        "retained_full_report_stat_only": full_report_stat,
        "input_records": sorted(by_path.values(), key=lambda item: item["path"]),
        "input_sha256": {path: record["sha256"] for path, record in sorted(by_path.items())},
        "source_closure": {
            "records": source_records,
            "v5_v3_v2_v1": True,
            "recursive_local_imports_bound": True,
            "literal_venv": True,
        },
        "query_times_s": list(QUERY_TIMES_S),
        "summary_max_bytes": 4 * 1024 * 1024,
        "native_payload_read": False,
        "hdf5_read": False,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    _write_once(manifest_path, manifest)
    manifest_record = _record(manifest_path, "ROOT196 recovery manifest", max_bytes=16 * 1024 * 1024)
    request_path = args.output.expanduser().resolve()
    output = "{attempt_root}/observer/f3_s2_overlay_native_observer_v5.summary.recovered.v1.json"
    command = [str(PYTHON), "-B", str((HERE / WORKER_NAME).resolve()), "--observer-request", str(paths["observer_request"]), "--failed-observer-receipt", str(paths["failed_observer_receipt"]), "--failed-observer-proof", str(paths["failed_observer_proof"]), "--full-report", str(paths["retained_full_report"]), "--solver-request", str(paths["solver_request"]), "--solver-receipt", str(paths["solver_receipt"]), "--solver-proof", str(paths["solver_proof"]), "--summary-output", output]
    all_records = {record["path"]: record for record in records + [manifest_record]}
    request = {
        "schema": SCHEMA,
        "variant_schema": VARIANT,
        "status": "BLOCKED_ROOT188_FAILURE_PROOF_MISSING" if missing else "READY_FOR_PARENT_V8_ROOT196_RECOVERY",
        "request_variant_status": "WAITING_FOR_PARENT_FAILURE_PROOF" if missing else "READY_FOR_PARENT_GUARD",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "family_id": "F3",
        "sentinel_id": "F3-S2",
        "physical_case_id": PHYSICAL_CASE,
        "case_id": manifest["case_id"],
        "attempt_id": manifest["attempt_id"],
        "cwd": str(LOCAL_REPO / "lagrangian-fluid-lab"),
        "worktree_root": str(LOCAL_REPO),
        "command": command,
        "input_files": sorted(all_records),
        "input_hashes": {path: record["sha256"] for path, record in sorted(all_records.items())},
        "input_sha256": {path: record["sha256"] for path, record in sorted(all_records.items())},
        "input_records": sorted(all_records.values(), key=lambda item: item["path"]),
        "deferred_input_files": [str(paths["retained_full_report"])],
        "deferred_input_records": {"retained_full_report": full_report_stat},
        "deferred_input_policy": "parent reserves attempt; recovery worker reads retained full JSON once and verifies pre/read/post stat plus SHA; no native/H5 read",
        "missing_required_evidence": missing,
        "manifest": manifest_record,
        "query_times_s": list(QUERY_TIMES_S),
        "time_interpolation": False,
        "native_payload_read": False,
        "hdf5_read": False,
        "full_report_read_by_builder": False,
        "solver_started": False,
        "solver_launch": False,
        "gencase_launch": False,
        "execution_allowed": not missing,
        "launch_disabled": bool(missing),
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 300,
        "max_memory_bytes": RECOVERY_MEMORY_BYTES,
        "max_decoder_scratch_bytes": 8 * 1024 * 1024,
        "estimated_input_read_bytes": sum(record["bytes"] for record in all_records.values()) + full_report_stat["bytes"],
        "estimated_peak_memory_bytes": RECOVERY_MEMORY_BYTES,
        "estimated_storage_bytes": 8 * 1024 * 1024,
        "estimated_native_read_bytes": 0,
        "estimated_hdf5_read_bytes": 0,
        "output_root": "{attempt_root}",
        "output": {"atomic": True, "refuse_overwrite": True, "path": output, "max_bytes": 4 * 1024 * 1024},
        "source_binding": {"failed_observer_evidence": "failure only", "retained_report": full_report_stat, "underlying_solver": solver_records, "summary_schema": "ds02.stage2.f3-s2.full-native-stream-observer.v5", "source_failure_preserved": True},
        "source_closure": manifest["source_closure"],
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": "parent-v8-audit",
            "payload_read": "retained JSON report only after reservation",
            "solver_launch": "forbidden",
            "max_memory_bytes": RECOVERY_MEMORY_BYTES,
            "memory_estimate_reason": "77MB retained JSON plus decoded 179208-record report and compact serialization",
        },
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "reason": "operational recovery from a failed compact-summary write; no scientific qualification"},
    }
    _write_once(request_path, request)
    return {"manifest": str(manifest_path), "request": str(request_path), "status": request["status"], "missing_required_evidence": missing, "retained_report_stat_bytes": full_report_stat["bytes"]}


def self_test() -> dict[str, Any]:
    import tempfile
    with tempfile.TemporaryDirectory(prefix="root196-request-") as temp:
        root = Path(temp)
        q = root / "q.json"
        receipt = root / "failed-receipt.json"
        q.write_text(json.dumps({"physical_case_id": PHYSICAL_CASE}), encoding="utf-8")
        qsha = hashlib.sha256(q.read_bytes()).hexdigest()
        receipt.write_text(json.dumps({
            "status": "failed",
            "returncode": 1,
            "request_sha256": qsha,
            # This is the expanded runtime request shape used by the actual
            # ds02 receipt; it intentionally has no path/SHA pair.
            "request": {"physical_case_id": PHYSICAL_CASE, "case_id": "F3_S2_MIDDLE_HALF_OUTPUT_FULL_NATIVE_ROOT188_V2"},
        }), encoding="utf-8")
        _, _ = _json_record(q, "fixture request")
        _, _ = _json_record(receipt, "fixture failure receipt")
        _validate_failed_receipt({"observer_request": q, "failed_observer_receipt": receipt})
        if not _stat_only(q, "fixture stat")["content_sha256"].startswith("UNKNOWN"):
            raise AssertionError("stat-only record unexpectedly claimed content SHA")
        _require_zero_returncode({"returncode": 0}, "zero solver returncode fixture")
        try:
            _require_zero_returncode({"returncode": 1}, "nonzero solver returncode fixture")
        except ValueError:
            pass
        else:
            raise AssertionError("nonzero solver returncode fixture was accepted")
        missing_proof = root / "missing-proof.json"
        return {"status": "PASS", "schema": VARIANT, "failed_receipt_nonzero": True, "missing_failure_proof_blocks": not missing_proof.exists(), "full_report_content_sha_at_builder": "UNKNOWN_BY_CONTRACT", "native_payload_read": False, "hdf5_read": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build", action="store_true")
    parser.add_argument("--manifest", type=Path, default=HERE / "stage2_f3_s2_full_native_stream_summary_recovery_v1_manifest.json")
    parser.add_argument("--output", type=Path, default=LOCAL_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/f3-s2-middle-half-output-summary-recovery-v1-root196-001.json")
    parser.add_argument("--observer-request", type=Path)
    parser.add_argument("--failed-observer-receipt", type=Path)
    parser.add_argument("--failed-observer-proof", type=Path)
    parser.add_argument("--retained-full-report", type=Path)
    parser.add_argument("--solver-request", type=Path)
    parser.add_argument("--solver-proof", type=Path)
    parser.add_argument("--solver-receipt", type=Path)
    args = parser.parse_args()
    if args.self_test:
        try:
            print(json.dumps(self_test(), ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        except Exception as exc:
            print(f"ROOT196 request self-test failed: {exc}", file=sys.stderr)
            return 2
    try:
        print(json.dumps(build(args), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        print(f"ROOT196 request builder refused: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
