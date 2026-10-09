#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Build the ROOT195 metadata-only three-way overlay comparison request.

The comparison is deliberately source-bound before it is runnable.  Each
observer producer must join its own request, receipt, verification proof, and
compact summary, and the summary must join the underlying solver request,
receipt, and proof.  ROOT177/187 are actual producers.  The half-output
producer is now the actual ROOT196 recovered compact summary.  Its ROOT188
source failure remains bound as failure provenance and is never converted
into an ROOT188 observer pass.

Only bounded JSON metadata and compact summaries are read.  Native Part/BI4,
H5, RunPARTs, and full observer reports are never opened by this builder.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
# ``HERE`` is ``.../stage2/reference``; parent four is the repository root.
LOCAL_REPO = HERE.parents[4]
PRIMARY_REPO = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")

V1_NAME = "stage2_f3_s2_overlay_task_error_compare_v1.py"
V2_NAME = "stage2_f3_s2_overlay_task_error_compare_v2.py"
V4_NAME = "stage2_f3_s2_overlay_task_error_compare_v4.py"
LEGACY_V3_NAME = "stage2_f3_s2_overlay_task_error_compare_v3.py"
# The consumed comparison normalizer validates the frozen scientific
# observation contract (v1).  The additive v2 file is an adapter/source
# binding contract and remains in the transitive closure, but it is not the
# object passed to V1._contract().
CONTRACT_NAME = "stage2_f3_s2_overlay_native_task_contract_v1.json"
ADAPTER_CONTRACT_NAME = "stage2_f3_s2_overlay_native_task_contract_v2.json"
CALIBRATION_PY_NAME = "stage2_f3_s2_observer_calibration_contract_v1.py"
CALIBRATION_JSON_NAME = "stage2_f3_s2_observer_calibration_contract_v1.json"

SCHEMA = "ds02.request.v1"
VARIANT = "ds02.stage2.f3-s2.overlay-task-error-compare-request.v4"
MANIFEST_SCHEMA = "ds02.stage2.f3-s2.overlay-task-error-compare.v4.binding-manifest"
PHYSICAL_CASE = "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT"
QUERY_TIMES_S = (0.0, 2.0, 4.0, 6.0, 8.0)
MAX_SUMMARY_BYTES = 4 * 1024 * 1024
MAX_JSON_BYTES = 32 * 1024 * 1024


def _load_v4():
    path = HERE / V4_NAME
    spec = importlib.util.spec_from_file_location("stage2_root195_v4_comparator", path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


V4 = _load_v4()


def _resolve_existing(relative: str, *, allow_primary_fallback: bool = True) -> Path:
    """Resolve a source file without silently substituting a missing file."""

    candidates = [LOCAL_REPO / relative]
    if allow_primary_fallback:
        candidates.append(PRIMARY_REPO / relative)
    for candidate in candidates:
        if candidate.is_file() and not candidate.is_symlink():
            return candidate.resolve()
    raise FileNotFoundError(relative)


def _regular(path: Path, label: str, *, max_bytes: int = MAX_JSON_BYTES) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    if path.stat().st_size > max_bytes:
        raise ValueError(f"{label} exceeds bounded input limit: {path.stat().st_size}")
    return path


def _record(path: Path, label: str, *, max_bytes: int = MAX_JSON_BYTES) -> dict[str, Any]:
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
        raise ValueError(f"{label} changed during metadata read: {path}")
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
        "content_scope": "bounded_JSON_metadata_or_source_code_only",
    }


def _load_json(path: Path, label: str, *, max_bytes: int = MAX_JSON_BYTES) -> tuple[dict[str, Any], dict[str, Any]]:
    record = _record(path, label, max_bytes=max_bytes)
    value = json.loads(Path(record["path"]).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} is not a JSON object")
    return record, value


def _record_literal_python() -> dict[str, Any]:
    path = PYTHON.expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"literal venv interpreter: {path}")
    resolved = path.resolve()
    if not resolved.is_file() or resolved.is_symlink():
        raise FileNotFoundError(f"resolved venv interpreter: {resolved}")
    cfg = path.parent.parent / "pyvenv.cfg"
    if not cfg.is_file() or cfg.is_symlink():
        raise FileNotFoundError(f"literal venv has no stable pyvenv.cfg: {cfg}")
    resolved_record = _record(resolved, "resolved venv interpreter", max_bytes=8 * 1024 * 1024)
    cfg_record = _record(cfg, "venv pyvenv.cfg", max_bytes=1024 * 1024)
    return {
        "path": str(path),
        "resolved_path": str(resolved),
        "label": "literal venv interpreter",
        "bytes": resolved_record["bytes"],
        "sha256": resolved_record["sha256"],
        "resolved_sha256": resolved_record["sha256"],
        "pyvenv_cfg": cfg_record,
        "literal_argv0_required": True,
        "content_scope": "literal_venv_interpreter_with_resolved_binary_and_pyvenv_binding",
    }


def _root177_spec() -> dict[str, Any]:
    p = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
    d = DATA_ROOT / "families/F3"
    return {
        "label": "same_cfl_baseline",
        "expected_physical_case": PHYSICAL_CASE,
        "producer": {
            "request": str(p / "requests/f3-s2-middle-full-native-stream-v6-root-forward-177-001.json"),
            "proof": str(p / "checkpoints/F3_MIDDLE_FULL836_NATIVE_COMPACT_ACTUAL_ROOT_VERIFICATION_177.json"),
            "receipt": str(d / "F3_S2_MIDDLE_FULL_NATIVE_STREAM_V6_ROOT_177/f3-s2-middle-full-native-stream-v6-root-177-001-root-forward-030-001/execution-receipt.json"),
            "summary": str(d / "F3_S2_MIDDLE_FULL_NATIVE_STREAM_V6_ROOT_177/f3-s2-middle-full-native-stream-v6-root-177-001-root-forward-030-001/observer/f3_s2_full_native_stream_observer_v5.summary.json"),
        },
        "solver": {
            "request": str(p / "requests/f3-s2-middle-external-v5-root-forward-162-001.json"),
            "proof": str(p / "checkpoints/F3_DP006_MIDDLE_EXTERNAL_ACTUAL_NATIVE_ROOT_VERIFICATION_162.json"),
            "receipt": str(d / "F3_S2_MATCHED_MIDDLE_SAME_CFL_ROOT_162/f3-s2-matched-middle-same-cfl-v5-root-162-001/execution-receipt.json"),
        },
    }


def _root187_spec() -> dict[str, Any]:
    p = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
    d = DATA_ROOT / "families/F3"
    return {
        "label": "half_cfl",
        "expected_physical_case": PHYSICAL_CASE,
        "producer": {
            "request": str(p / "requests/f3-middle-half-cfl-observer-v2-root-forward-187-001.json"),
            "proof": str(p / "checkpoints/F3_MIDDLE_HALF_CFL_FULL836_NATIVE_COMPACT_ACTUAL_ROOT_VERIFICATION_187.json"),
            "receipt": str(d / "F3_S2_MIDDLE_HALF_CFL_FULL_NATIVE_ROOT187_V2/f3-middle-half-cfl-full-native-v2-root-187-001-root-forward-030-001/execution-receipt.json"),
            "summary": str(d / "F3_S2_MIDDLE_HALF_CFL_FULL_NATIVE_ROOT187_V2/f3-middle-half-cfl-full-native-v2-root-187-001-root-forward-030-001/observer/f3_s2_overlay_native_observer_v2.summary.json"),
        },
        "solver": {
            "request": str(p / "requests/f3-s2-middle-half-cfl-external-v8-root173-primary-forward-002.json"),
            "proof": str(p / "checkpoints/F3_MIDDLE_HALF_CFL_EXTERNAL_ACTUAL_NATIVE_ROOT_VERIFICATION_173.json"),
            "receipt": str(d / "F3_S2_MATCHED_MIDDLE_HALF_CFL_ROOT173_V8/f3-s2-matched-middle-half-cfl-root-173-v8-001/execution-receipt.json"),
        },
    }


def _root188_spec() -> dict[str, Any]:
    p = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
    d = DATA_ROOT / "families/F3"
    # ROOT196 is the actual half-output producer.  The original ROOT188
    # observer remains a failed source artifact referenced by the recovery
    # proof; it is never substituted with an observer-success claim.
    return {
        "label": "half_output",
        "expected_physical_case": PHYSICAL_CASE,
        "producer": {
            "request": str(p / "requests/f3-middle-half-output-summary-recovery-v1-root-forward-196-001.json"),
            "proof": str(p / "checkpoints/F3_HALF_OUTPUT_RETAINED_REPORT_SUMMARY_RECOVERY_ACTUAL_ROOT_VERIFICATION_196.json"),
            "receipt": str(d / "F3_S2_MIDDLE_HALF_OUTPUT_RECOVERY_ROOT196/f3-s2-middle-half-output-summary-recovery-root196-001-root-forward-030-001/execution-receipt.json"),
            "summary": str(d / "F3_S2_MIDDLE_HALF_OUTPUT_RECOVERY_ROOT196/f3-s2-middle-half-output-summary-recovery-root196-001-root-forward-030-001/observer/f3_s2_overlay_native_observer_v5.summary.recovered.v1.json"),
        },
        "solver": {
            "request": str(p / "requests/f3-s2-middle-half-output-external-v8-root174-primary-forward-002.json"),
            "proof": str(p / "checkpoints/F3_MIDDLE_HALF_OUTPUT_EXTERNAL_ACTUAL_NATIVE_ROOT_VERIFICATION_174.json"),
            "receipt": str(d / "F3_S2_MATCHED_MIDDLE_HALF_OUTPUT_ROOT174_V8/f3-s2-matched-middle-half-output-root-174-v8-001/execution-receipt.json"),
        },
        "source_failure": {
            "request": str(p / "requests/f3-middle-half-output-observer-v2-root-forward-188-001.json"),
            "receipt": str(d / "F3_S2_MIDDLE_HALF_OUTPUT_FULL_NATIVE_ROOT188_V2/f3-middle-half-output-full-native-v2-root-188-001-root-forward-030-001/execution-receipt.json"),
            "proof": str(p / "checkpoints/F3_HALF_OUTPUT_NATIVE_OBSERVER_ACTUAL_COMPACT_CAP_FAILURE_ROOT_VERIFICATION_188.json"),
            "status": "FAILED_COMPACT_SUMMARY_CAP_PRESERVED",
        },
    }


def _specs() -> list[dict[str, Any]]:
    return [_root177_spec(), _root187_spec(), _root188_spec()]


def _missing_producer(spec: dict[str, Any]) -> list[dict[str, str]]:
    missing: list[dict[str, str]] = []
    for role in ("request", "proof", "receipt", "summary"):
        path = Path(spec["producer"][role]).expanduser().resolve()
        if not path.is_file() or path.is_symlink():
            missing.append({"label": spec["label"], "role": f"producer.{role}", "path": str(path), "reason": "actual producer artifact is absent; planned request is not evidence"})
    return missing


def _validate_solver_metadata(spec: dict[str, Any]) -> dict[str, Any]:
    """Validate a solver proof/request/receipt without touching payload data."""

    label = f"{spec['label']}.underlying_solver"
    proof_record, proof = _load_json(Path(spec["solver"]["proof"]), f"{label} proof")
    request_record, request = _load_json(Path(spec["solver"]["request"]), f"{label} request", max_bytes=8 * 1024 * 1024)
    receipt_record, receipt = _load_json(Path(spec["solver"]["receipt"]), f"{label} receipt")
    schema = proof.get("schema")
    if schema not in {"ds02.stage2.root-actual-verification.v1", "ds02.stage2.root-actual-external-solver-verification.v1"}:
        raise ValueError(f"{label} proof schema is not an actual root proof")
    if "ACTUAL" not in str(proof.get("status", "")) and not str(proof.get("status", "")).startswith("VERIFIED"):
        raise ValueError(f"{label} proof is not an actual terminal verification")
    if request.get("physical_case_id") not in {PHYSICAL_CASE, None}:
        raise ValueError(f"{label} physical case differs")
    if Path(str(proof.get("request", ""))).expanduser().resolve() != Path(request_record["path"]):
        raise ValueError(f"{label} proof request path differs")
    if proof.get("request_sha256") != request_record["sha256"]:
        raise ValueError(f"{label} proof request SHA differs")
    if Path(str(proof.get("receipt", ""))).expanduser().resolve() != Path(receipt_record["path"]):
        raise ValueError(f"{label} proof receipt path differs")
    if proof.get("receipt_sha256") != receipt_record["sha256"]:
        raise ValueError(f"{label} proof receipt SHA differs")
    status = str(receipt.get("status", "")).lower()
    if not status.startswith(("completed", "complete", "success")):
        raise ValueError(f"{label} receipt is not completed: {receipt.get('status')!r}")
    return {"proof": proof_record, "request": request_record, "receipt": receipt_record}


def _validate_actual_binding(spec: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    normalized, evidence = V4._validate_binding(spec)
    return normalized, evidence


def _validate_recovered_failure_marker(spec: dict[str, Any]) -> dict[str, Any] | None:
    """Require ROOT196 to retain ROOT188 failure provenance explicitly."""
    failure = spec.get("source_failure")
    if failure is None:
        return None
    if spec.get("label") != "half_output" or not isinstance(failure, dict):
        raise ValueError("source_failure is only valid for the recovered half-output binding")
    failure_request_record, failure_request = _load_json(Path(failure["request"]), "ROOT188 failed request", max_bytes=4 * 1024 * 1024)
    failure_receipt_record, failure_receipt = _load_json(Path(failure["receipt"]), "ROOT188 failed receipt", max_bytes=32 * 1024 * 1024)
    failure_proof_record, failure_proof = _load_json(Path(failure["proof"]), "ROOT188 failure proof", max_bytes=32 * 1024 * 1024)
    if failure_request.get("physical_case_id") not in {PHYSICAL_CASE, None}:
        raise ValueError("ROOT188 failure request physical case differs")
    if not str(failure_receipt.get("status", "")).lower().startswith(("failed", "error", "aborted")):
        raise ValueError("ROOT188 failure receipt is not failed evidence")
    if failure_receipt.get("request_sha256") != failure_request_record["sha256"]:
        raise ValueError("ROOT188 failure receipt request SHA differs")
    if failure_proof.get("request_sha256") != failure_request_record["sha256"] or failure_proof.get("receipt_sha256") != failure_receipt_record["sha256"]:
        raise ValueError("ROOT188 failure proof request/receipt join differs")
    if "FAIL" not in str(failure_proof.get("status", "")).upper():
        raise ValueError("ROOT188 failure proof does not preserve failure status")

    recovery_proof_record, recovery_proof = _load_json(Path(spec["producer"]["proof"]), "ROOT196 recovery proof", max_bytes=32 * 1024 * 1024)
    if recovery_proof.get("source_failure_preserved") is not True:
        raise ValueError("ROOT196 proof does not preserve ROOT188 failure")
    if Path(str(recovery_proof.get("source_failure_proof", ""))).expanduser().resolve() != Path(failure_proof_record["path"]):
        raise ValueError("ROOT196 proof source failure proof path differs")
    if recovery_proof.get("source_failure_proof_sha256") != failure_proof_record["sha256"]:
        raise ValueError("ROOT196 proof source failure proof SHA differs")
    return {
        "failure_request": failure_request_record,
        "failure_receipt": failure_receipt_record,
        "failure_proof": failure_proof_record,
        "recovery_proof": recovery_proof_record,
        "source_failure_preserved": True,
    }


def _source_closure() -> tuple[list[dict[str, Any]], dict[str, str]]:
    relative_files = [
        f"lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/{V1_NAME}",
        f"lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/{V2_NAME}",
        f"lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/{V4_NAME}",
        f"lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/{LEGACY_V3_NAME}",
        "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_full_native_stream_observer_v1.py",
        "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_full_native_stream_observer_v2.py",
        "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_full_native_stream_observer_v3.py",
        "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_full_native_stream_observer_v5.py",
        "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_native_header_observer_v1.py",
        "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_native_physical_observer_v2.py",
        "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_full_native_stream_summary_recovery_v1.py",
        "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_full_native_stream_summary_recovery_v1_contract.json",
        "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_full_native_stream_summary_recovery_v1_request.py",
        "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_overlay_task_error_compare_v1_request.py",
        "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_saved_bracket_compare_v2_request.py",
        "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_saved_bracket_compare_v3_request.py",
        f"lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/{CONTRACT_NAME}",
        f"lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/{ADAPTER_CONTRACT_NAME}",
        f"lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/{CALIBRATION_PY_NAME}",
        f"lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/{CALIBRATION_JSON_NAME}",
        "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_overlay_native_observer_v1.py",
        "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_overlay_native_observer_v2.py",
        "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_overlay_native_observer_v1_request.py",
        "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_overlay_native_observer_v2_request.py",
        "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py",
        "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch.py",
        "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py",
        "lagrangian-fluid-lab/scripts/ds_data02_batch_runner.py",
        "lagrangian-fluid-lab/scripts/ds_data02_runtime_v6.py",
        "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py",
        "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py",
        "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py",
        "lagrangian-fluid-lab/scripts/ds_data02_stage2_external_solver_v5.py",
    ]
    records: list[dict[str, Any]] = []
    missing: list[str] = []
    for relative in relative_files:
        try:
            path = _resolve_existing(relative)
        except FileNotFoundError:
            missing.append(relative)
            continue
        records.append(_record(path, f"source closure: {relative}", max_bytes=64 * 1024 * 1024))
    if missing:
        raise FileNotFoundError("source closure files missing: " + ", ".join(missing))
    records.append(_record_literal_python())
    return records, {item["path"]: item["sha256"] for item in records if item.get("sha256")}


def _manifest_payload() -> dict[str, Any]:
    source_records, source_hashes = _source_closure()
    specs = _specs()
    binding_status: list[dict[str, Any]] = []
    all_records: dict[str, dict[str, Any]] = {}
    missing: list[dict[str, str]] = []
    for spec in specs:
        for role, path_text in spec["producer"].items():
            path = Path(path_text)
            if path.is_file() and not path.is_symlink():
                # Missing ROOT188 output paths are intentionally not read.
                max_bytes = MAX_SUMMARY_BYTES if role == "summary" else MAX_JSON_BYTES
                rec = _record(path, f"{spec['label']} producer {role}", max_bytes=max_bytes)
                all_records[rec["path"]] = rec
        missing.extend(_missing_producer(spec))
        solver_meta = _validate_solver_metadata(spec)
        for record in solver_meta.values():
            all_records[record["path"]] = record
        if not _missing_producer(spec):
            _, evidence = _validate_actual_binding(spec)
            failure_evidence = _validate_recovered_failure_marker(spec)
            binding_status.append({"label": spec["label"], "status": "ACTUAL_PRODUCER_AND_SOLVER_JOIN_VALIDATED", "evidence": evidence, "source_failure": failure_evidence})
        else:
            binding_status.append({"label": spec["label"], "status": "BLOCKED_ACTUAL_PRODUCER_EVIDENCE_MISSING", "missing": _missing_producer(spec), "planned_request_is_not_evidence": True})
    for rec in source_records:
        all_records[rec["path"]] = rec
    return {
        "schema": MANIFEST_SCHEMA,
        "variant_schema": VARIANT,
        "status": "READY_FOR_THREE_WAY_METADATA_COMPARISON" if not missing else "BLOCKED_ROOT188_PRODUCER_EVIDENCE_MISSING",
        "case_id": "F3_S2_OVERLAY_TASK_ERROR_COMPARE_V4_ROOT195",
        "attempt_id": "f3-s2-overlay-task-error-compare-v4-root195-001",
        "physical_case_id": PHYSICAL_CASE,
        "bindings": specs,
        "binding_status": binding_status,
        "required_labels": ["same_cfl_baseline", "half_cfl", "half_output"],
        "root188_source_failure_preserved": True,
        "missing_required_evidence": missing,
        "calibration_contract": str(_resolve_existing(f"lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/{CONTRACT_NAME}")),
        "fixed_query_times_s": list(QUERY_TIMES_S),
        "time_interpolation": False,
        "neighbor_grid_truth": False,
        "native_payload_read": False,
        "hdf5_read": False,
        "source_closure": {
            "records": source_records,
            "sha256": source_hashes,
            "transitive_imports": [V4_NAME, LEGACY_V3_NAME, V2_NAME, V1_NAME],
            "recovery_chain": [
                "stage2_f3_s2_full_native_stream_summary_recovery_v1.py",
                "stage2_f3_s2_full_native_stream_observer_v5.py",
                "stage2_f3_s2_full_native_stream_observer_v3.py",
                "stage2_f3_s2_full_native_stream_observer_v2.py",
                "stage2_f3_s2_native_header_observer_v1.py",
                "stage2_native_physical_observer_v2.py",
            ],
            "calibration": [CALIBRATION_PY_NAME, CALIBRATION_JSON_NAME],
        },
        "input_records": sorted(all_records.values(), key=lambda item: item["path"]),
        "input_sha256": {path: record["sha256"] for path, record in sorted(all_records.items())},
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "reason": "metadata-only producer/solver/source joins; no scientific qualification"},
    }


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise FileExistsError(f"refusing to overwrite immutable artifact: {path}")
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


def _request_from_manifest(manifest_path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    source_records = list(manifest["source_closure"]["records"])
    input_records = list(manifest["input_records"])
    request_path = LOCAL_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/f3-s2-overlay-task-error-compare-v4-root195-001.json"
    output_path = "{attempt_root}/comparison/f3_s2_overlay_task_error_compare_v4.json"
    command = [
        str(PYTHON), "-B", str((HERE / V4_NAME).resolve()),
        "--manifest", str(manifest_path.resolve()), "--require-three-way",
        "--output", output_path,
    ]
    all_records = {record["path"]: record for record in input_records + source_records}
    manifest_record = _record(manifest_path, "ROOT195 binding manifest", max_bytes=16 * 1024 * 1024)
    all_records[manifest_record["path"]] = manifest_record
    missing = list(manifest["missing_required_evidence"])
    blocked = bool(missing)
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "variant_schema": VARIANT,
        "status": "BLOCKED_ROOT188_PRODUCER_EVIDENCE_MISSING" if blocked else "READY_FOR_PARENT_V8_METADATA_COMPARISON",
        "request_variant_status": "NOT_RUN_PENDING_ROOT188_ACTUAL_OBSERVER" if blocked else "READY_FOR_PARENT_GUARD",
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
        "required_missing_evidence": missing,
        "source_closure": manifest["source_closure"],
        "manifest": manifest_record,
        "fixed_query_times_s": list(QUERY_TIMES_S),
        "time_interpolation": False,
        "adjacent_grid_truth": False,
        "deferred_input_files": [],
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 300,
        "max_memory_bytes": 1024 * 1024 * 1024,
        "max_decoder_scratch_bytes": 8 * 1024 * 1024,
        "estimated_storage_bytes": 8 * 1024 * 1024,
        "estimated_peak_memory_bytes": 256 * 1024 * 1024,
        "estimated_input_read_bytes": sum(int(record["bytes"]) for record in all_records.values()),
        "estimated_native_read_bytes": 0,
        "estimated_hdf5_read_bytes": 0,
        "native_payload_read": False,
        "hdf5_read": False,
        "full_report_read": False,
        "raw_directory_scan": False,
        "solver_started": False,
        "solver_launch": False,
        "gencase_launch": False,
        "execution_allowed": not blocked,
        "launch_disabled": blocked,
        "output_root": "{attempt_root}",
        "output": {"atomic": True, "refuse_overwrite": True, "path": output_path},
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "reason": "metadata-only comparison diagnostics; asynchronous saved times are not interpolated and no truth/error credit is granted"},
        "resource_guard": {"owner": "stage2-reference-preparation", "runner": "parent-v8-audit", "parent_reservation_required": True, "payload_read": "bounded JSON metadata only", "solver_launch": "forbidden"},
        "root195_policy": {
            "root196_recovery_is_actual_half_output_producer": True,
            "root188_source_failure_preserved": True,
            "root188_failure_is_not_promoted_to_observer_pass": True,
            "planned_root188_request_is_not_evidence": True,
            "strict_build_must_fail_while_any_required_artifact_is_missing": True,
        },
    }
    return payload


def build_pending(manifest_path: Path, request_path: Path) -> dict[str, Any]:
    manifest = _manifest_payload()
    _atomic_json(manifest_path, manifest)
    request = _request_from_manifest(manifest_path, manifest)
    _atomic_json(request_path, request)
    return {"manifest": str(manifest_path.resolve()), "request": str(request_path.resolve()), "status": request["status"], "missing_required_evidence": request["required_missing_evidence"]}


def validate_manifest(path: Path, *, require_three_way: bool) -> dict[str, Any]:
    record, manifest = _load_json(path, "ROOT195 binding manifest", max_bytes=16 * 1024 * 1024)
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise ValueError("unexpected ROOT195 manifest schema")
    if manifest.get("fixed_query_times_s") != list(QUERY_TIMES_S):
        raise ValueError("ROOT195 fixed query times changed")
    missing = manifest.get("missing_required_evidence")
    if not isinstance(missing, list):
        raise ValueError("manifest missing_required_evidence is not a list")
    if missing:
        raise ValueError("ROOT188 producer evidence missing: strict build is refused")
    result = V4.validate_manifest(path, require_three_way=True)
    result["manifest_record"] = record
    return result


def _self_test() -> dict[str, Any]:
    # The V4 fixture tests wrong producer request/receipt/summary SHA joins.
    v4 = V4._fixture_self_test()
    with tempfile.TemporaryDirectory(prefix="root195-missing-") as temp:
        root = Path(temp)
        missing_spec = _root188_spec()
        missing_spec["producer"] = {
            role: str(root / f"missing-{role}.json")
            for role in missing_spec["producer"]
        }
        missing = _missing_producer(missing_spec)
        if len(missing) < 2:
            raise AssertionError(f"ROOT188 missing fixture unexpectedly complete: {missing}")
        if not any(item["role"] == "producer.proof" for item in missing):
            raise AssertionError("missing ROOT188 proof was not rejected")
        # A regular file at the expected path is still not sufficient: the
        # V4 fixture above mutates each producer SHA and exercises the strict
        # proof/receipt/summary join.  Keep this check separate from the
        # missing-artifact check so a placeholder file cannot masquerade as an
        # actual ROOT188 observer result.
        wrong = root / "wrong-summary.json"
        wrong.write_text("{}\n", encoding="utf-8")
        if not wrong.is_file() or wrong.is_symlink():
            raise AssertionError("manufactured regular-file fixture was not created")
        return {
            "status": "PASS",
            "schema": VARIANT,
            "v4_join_fixture": v4,
            "root188_missing_producer_rejection": True,
            "wrong_sha_counterexamples": ["producer.request_sha256", "producer.receipt_sha256", "producer.summary_sha256"],
            "fixed_query_times_s": list(QUERY_TIMES_S),
            "native_payload_read": False,
            "hdf5_read": False,
            "solver_launch": False,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build-pending", action="store_true")
    mode.add_argument("--validate-manifest", action="store_true")
    parser.add_argument("--manifest", type=Path, default=HERE / "stage2_f3_s2_overlay_task_error_compare_v4_root195_manifest.json")
    parser.add_argument("--output", type=Path, default=LOCAL_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/f3-s2-overlay-task-error-compare-v4-root195-001.json")
    parser.add_argument("--require-three-way", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            print(json.dumps(_self_test(), ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        if args.build_pending:
            print(json.dumps(build_pending(args.manifest, args.output), ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        result = validate_manifest(args.manifest, require_three_way=True)
        print(json.dumps({"status": result["status"], "manifest": str(args.manifest.resolve()), "strict_three_way": True}, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        print(f"ROOT195 V4 builder refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
