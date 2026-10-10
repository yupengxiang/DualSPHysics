#!/usr/bin/env python3
"""Recover the ROOT353 metadata chain without reopening native payloads.

ROOT353 already completed the guarded producer and wrote a valid guard result
and child observer report.  Its parent stopped only because the parent used
the legacy literal ``PASS`` status.  This worker consumes the failed receipt,
checkpoint, guard JSON, and child JSON, verifies that lineage, and then runs
the JSON-only compact V3 -> scalar V2 -> independent verifier chain.  It
never calls the guarded producer and never opens a Part/BI4/VTK/H5 file.

The recovery is deliberately a new parent namespace.  The failed ROOT353
request, receipt, and proof remain immutable inputs and the result carries
zero scientific credit.  A missing or changed small record fails closed; a
native path appearing inside a record is metadata only and is never opened.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
COMPACT_PATH = HERE / "stage2_f1_s2_root279_native_compact_worker_v3.py"
SCALAR_PATH = HERE / "stage2_rotation_invariant_native_scalar_observer_v2.py"
VERIFIER_PATH = HERE / "stage2_f1_s2_root279_native_scalar_verify_v1.py"
SCHEMA = "ds02.stage2.f1-s2.root279-native-scalar-recovery-worker.v1"
RESULT_STATUS = "COMPLETE_ROOT279_METADATA_RECOVERY_COMPACT_V3_SCALAR_V2_VERIFIER_NO_NATIVE_REREAD"
GUARD_STATUS = "PASS_GUARDED_V1_NATIVE_SELECTED_OBSERVABLES"
CHILD_STATUS = "PASS_F1_NATIVE_HEADER_SELECTED_OBSERVABLES"
CHECKPOINT_SCHEMA = "ds02.stage2.root353-failed-native-scalar-metadata-closure.v1"
JSON_CAP = 10 * 1024 * 1024
UNKNOWN = "UNKNOWN"


class RecoveryFailure(RuntimeError):
    pass


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RecoveryFailure(f"cannot load recovery dependency: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


COMPACT = _load(COMPACT_PATH, "root279_compact_v3_for_recovery")
SCALAR = _load(SCALAR_PATH, "root279_scalar_v2_for_recovery")
VERIFIER = _load(VERIFIER_PATH, "root279_verifier_v1_for_recovery")


def _abs(value: Path | str) -> Path:
    return Path(value).expanduser().absolute()


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {
        "device": int(value.st_dev),
        "inode": int(value.st_ino),
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
    }


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _record_json(path: Path | str, label: str, expected: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read one bounded JSON record and verify its producer binding.

    This function intentionally rejects non-JSON paths.  It therefore cannot
    accidentally turn a native path embedded in a guard report into a payload
    read during recovery.
    """
    path = _abs(path)
    if path.suffix.lower() != ".json" or path.is_symlink() or not path.is_file():
        raise RecoveryFailure(f"{label} is not a regular JSON metadata file: {path}")
    before = _stat(path)
    if before["bytes"] > JSON_CAP:
        raise RecoveryFailure(f"{label} exceeds the 10 MiB metadata cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    digest = _sha(raw)
    if before != after or len(raw) != before["bytes"]:
        raise RecoveryFailure(f"{label} changed while being read: {path}")
    if isinstance(expected, dict):
        wanted = expected.get("sha256")
        if isinstance(wanted, str) and len(wanted) == 64 and digest.lower() != wanted.lower():
            raise RecoveryFailure(f"{label} SHA differs from its failed producer binding")
        bound = expected.get("stat")
        if isinstance(bound, dict):
            # Accept the two stat spellings used by old runtime receipts, but
            # require every field that the producer actually supplied.
            aliases = {"device": ("device", "st_dev"), "inode": ("inode", "st_ino"),
                       "bytes": ("bytes", "size"), "mtime_ns": ("mtime_ns",),
                       "ctime_ns": ("ctime_ns",)}
            for key, names in aliases.items():
                for name in names:
                    if name in bound and int(bound[name]) != after[key]:
                        raise RecoveryFailure(f"{label} {name} differs from its failed producer binding")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RecoveryFailure(f"{label} is not bounded UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise RecoveryFailure(f"{label} is not a JSON object")
    return value, {"path": str(path), "sha256": digest, "stat": after,
                   "bytes": len(raw), "payload_read": True, "scope": "bounded_json_only"}


def _record_text(path: Path | str, expected: dict[str, Any] | None = None) -> dict[str, Any]:
    path = _abs(path)
    if path.is_symlink() or not path.is_file() or path.suffix.lower() not in {".log", ".txt"}:
        raise RecoveryFailure(f"failure stdout is not a regular bounded text record: {path}")
    before = _stat(path)
    if before["bytes"] > JSON_CAP:
        raise RecoveryFailure("failure stdout exceeds the metadata cap")
    raw = path.read_bytes()
    after = _stat(path)
    digest = _sha(raw)
    if before != after:
        raise RecoveryFailure("failure stdout changed while being read")
    if isinstance(expected, dict):
        wanted = expected.get("sha256")
        if isinstance(wanted, str) and len(wanted) == 64 and digest.lower() != wanted.lower():
            raise RecoveryFailure("failure stdout SHA differs from checkpoint")
    return {"path": str(path), "sha256": digest, "stat": after, "bytes": len(raw),
            "text": raw.decode("utf-8", errors="replace")}


def _write_once(path: Path, value: dict[str, Any]) -> None:
    path = _abs(path)
    if path.exists() or path.is_symlink():
        raise RecoveryFailure(f"refusing to overwrite recovery output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _same_ref(actual: dict[str, Any], bound: dict[str, Any], label: str) -> None:
    if not isinstance(actual, dict) or not isinstance(bound, dict):
        raise RecoveryFailure(f"{label} is not a record reference")
    if _abs(actual.get("path", "")) != _abs(bound.get("path", "")):
        raise RecoveryFailure(f"{label} path is not the checkpoint-bound path")
    if actual.get("sha256") != bound.get("sha256"):
        raise RecoveryFailure(f"{label} SHA is not the checkpoint-bound SHA")


def _metadata_counts_and_stability(guard: dict[str, Any]) -> dict[str, Any]:
    if guard.get("schema") != "ds02.stage2.f1-s2.root279-native-observer-guarded.v1":
        raise RecoveryFailure("ROOT353 guard schema is not the guarded observer schema")
    if guard.get("status") != GUARD_STATUS:
        raise RecoveryFailure("ROOT353 guard status is not the exact guarded PASS")
    integrity = guard.get("source_integrity")
    if not isinstance(integrity, dict) or integrity.get("pre_post_exact_sha_and_stat") is not True:
        raise RecoveryFailure("ROOT353 guard did not establish native pre/post identity")
    pre, post = integrity.get("pre"), integrity.get("post")
    if not isinstance(pre, list) or not isinstance(post, list) or len(pre) != 10 or len(post) != 10:
        raise RecoveryFailure("ROOT353 guard does not contain exactly ten selected native records")
    for index, (left, right) in enumerate(zip(pre, post)):
        if not isinstance(left, dict) or not isinstance(right, dict):
            raise RecoveryFailure(f"ROOT353 guard record {index} is malformed")
        for key in ("frame", "path", "sha256", "stat"):
            if left.get(key) != right.get(key):
                raise RecoveryFailure(f"ROOT353 guard record {index} changed between pre and post")
        # This is metadata comparison only.  Do not stat or hash left['path'].
    accounting = guard.get("native_read_accounting")
    if not isinstance(accounting, dict) or accounting.get("selected_frame_count") != 10:
        raise RecoveryFailure("ROOT353 native read accounting is not the ten-frame guard")
    return {"selected_frame_count": 10, "pre_post_exact_sha_and_stat": True,
            "native_paths_reused_as_metadata": [str(x["path"]) for x in pre],
            "native_payload_reopened_by_recovery": False}


def _load_lineage(manifest_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    recovery, recovery_record = _record_json(manifest_path, "ROOT279 recovery manifest")
    if recovery.get("schema") != "ds02.stage2.f1-s2.root279-native-scalar-recovery-manifest.v1":
        raise RecoveryFailure("recovery manifest schema mismatch")
    if recovery.get("status") not in {"READY_FOR_PARENT_ROOT279_METADATA_RECOVERY",
                                       "SOURCE_PREPARED_ROOT279_METADATA_RECOVERY",
                                       "SOURCE_PREPARED_ROOT279_METADATA_RECOVERY_AFTER_ROOT353_FAILURE"}:
        raise RecoveryFailure("recovery manifest is not parent-ready")
    return recovery, recovery_record


def _validate_failure(recovery: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    lineage = recovery.get("failed_lineage")
    if not isinstance(lineage, dict):
        raise RecoveryFailure("recovery manifest lacks failed ROOT353 lineage")
    checkpoint, checkpoint_record = _record_json(lineage["checkpoint"]["path"], "ROOT353 failure checkpoint", lineage["checkpoint"])
    if checkpoint.get("schema") != CHECKPOINT_SCHEMA or checkpoint.get("status") != "VERIFIED_FAILED_PARENT_FULL_CPU_NATIVE_PRODUCER_PRESERVED_NO_CHAIN_CREDIT":
        raise RecoveryFailure("checkpoint is not the exact preserved ROOT353 failure")
    if checkpoint.get("failure") != "PARENT_V2_REJECTED_ACTUAL_GUARDED_V1_SUCCESS_STATUS":
        raise RecoveryFailure("checkpoint failure is not the recoverable guard-status mismatch")
    if checkpoint.get("root_payload_content_read") is not False or checkpoint.get("scientific_Q_credit") != 0:
        raise RecoveryFailure("checkpoint has an unsupported payload/Q claim")

    request, request_record = _record_json(lineage["request"]["path"], "ROOT353 failed request", lineage["request"])
    receipt, receipt_record = _record_json(lineage["receipt"]["path"], "ROOT353 failed execution receipt", lineage["receipt"])
    if request.get("schema") != "ds02.request.v1":
        raise RecoveryFailure("ROOT353 request schema is not ds02.request.v1")
    if receipt.get("schema") != "ds02.execution-receipt.v1" or receipt.get("status") != "failed" or receipt.get("returncode") != 2:
        raise RecoveryFailure("ROOT353 receipt is not the recorded failed parent")
    if receipt.get("request_sha256") != request_record["sha256"] or receipt.get("request") != request:
        raise RecoveryFailure("ROOT353 receipt does not bind the exact failed request file")
    if checkpoint.get("request", {}).get("sha256") != request_record["sha256"]:
        raise RecoveryFailure("checkpoint request binding differs from the failed request")
    if checkpoint.get("receipt", {}).get("sha256") != receipt_record["sha256"]:
        raise RecoveryFailure("checkpoint receipt binding differs from the failed receipt")

    guard, guard_record = _record_json(lineage["guard_result"]["path"], "ROOT353 guard result", lineage["guard_result"])
    child, child_record = _record_json(lineage["child_report"]["path"], "ROOT353 child report", lineage["child_report"])
    if guard.get("status") != GUARD_STATUS or child.get("status") != CHILD_STATUS:
        raise RecoveryFailure("ROOT353 preserved producer records do not have exact successful statuses")
    if child.get("schema") != "ds02.stage2.f1.native-selected-observer.v1":
        raise RecoveryFailure("ROOT353 child report schema is not the native observer schema")
    if guard.get("child_output", {}).get("path") != child_record["path"]:
        raise RecoveryFailure("ROOT353 guard child path differs from checkpoint child path")
    if guard.get("child_output", {}).get("parsed_status") != CHILD_STATUS:
        raise RecoveryFailure("ROOT353 guard child status edge is not exact")
    counts = _metadata_counts_and_stability(guard)
    stdout = _record_text(lineage["stdout"]["path"], lineage["stdout"])
    if "FAILED_ROOT279_NATIVE_SCALAR_PARENT_V2" not in stdout["text"]:
        raise RecoveryFailure("ROOT353 stdout does not identify the preserved parent status failure")
    return checkpoint, checkpoint_record, request, request_record, receipt, receipt_record, guard, guard_record, child, child_record, counts, stdout


def _sealed_manifest(compact_manifest: dict[str, Any], compact_result: dict[str, Any], path: Path) -> dict[str, Any]:
    reports = compact_result.get("compact_reports")
    if not isinstance(reports, dict) or set(reports) != {"same_cfl", "half_cfl"}:
        raise RecoveryFailure("compact V3 did not seal both reports")
    sealed = dict(compact_manifest)
    sealed["schema"] = "ds02.stage2.f1-s2.root279-native-compact-manifest.v1"
    sealed["status"] = "READY_FOR_PARENT_ROOT279_NATIVE_COMPACT"
    sealed["outputs"] = reports
    sealed["sealed_result"] = compact_result.get("result") or {"status": compact_result.get("status")}
    _write_once(path, sealed)
    return sealed


def run(manifest_path: Path, attempt_root: Path) -> dict[str, Any]:
    recovery, recovery_record = _load_lineage(manifest_path)
    values = _validate_failure(recovery)
    (checkpoint, checkpoint_record, failed_request, failed_request_record, failed_receipt,
     failed_receipt_record, guard, guard_record, child, child_record, counts, stdout) = values
    parent_ref = recovery.get("failed_lineage", {}).get("parent_manifest")
    parent_manifest, parent_record = _record_json(parent_ref["path"], "ROOT353 parent manifest", parent_ref)
    if parent_manifest.get("schema") != "ds02.stage2.f1-s2.root279-native-scalar-parent-manifest.v2":
        raise RecoveryFailure("ROOT353 parent manifest schema is not the source scalar manifest")
    identity = parent_manifest.get("source_identity_digest")
    if not isinstance(identity, str) or identity != failed_request.get("source_identity_digest"):
        raise RecoveryFailure("recovery source identity differs from the failed parent")
    compact_template = parent_manifest.get("compact_manifest")
    scalar_template = parent_manifest.get("scalar_manifest")
    if not isinstance(compact_template, dict) or not isinstance(scalar_template, dict):
        raise RecoveryFailure("ROOT353 parent manifest lacks compact/scalar templates")
    attempt_root = _abs(attempt_root)
    observer = attempt_root / "observer"
    compact_dir = observer / "compact"
    observer.mkdir(parents=True, exist_ok=True)
    compact_dir.mkdir(parents=True, exist_ok=True)

    # These references are the only producer outputs consumed by recovery.
    # In particular, no deferred native path from failed_request is opened.
    compact_manifest = dict(compact_template)
    compact_manifest["status"] = "READY_FOR_PARENT_ROOT279_NATIVE_COMPACT"
    compact_manifest["source_identity_digest"] = identity
    compact_manifest["guard_result"] = guard_record
    compact_manifest["child_report"] = child_record
    compact_manifest["outputs"] = {
        "same_cfl": {"path": str(compact_dir / "same_cfl.json")},
        "half_cfl": {"path": str(compact_dir / "half_cfl.json")},
    }
    compact_manifest["result_path"] = str(compact_dir / "root279-native-compact-result.json")
    compact_manifest["recovery_lineage"] = {
        "failed_checkpoint": checkpoint_record,
        "failed_request": failed_request_record,
        "failed_receipt": failed_receipt_record,
        "producer_guard": guard_record,
        "producer_child": child_record,
        "native_reread": False,
    }
    compact_path = observer / "recovery-compact-manifest.json"
    _write_once(compact_path, compact_manifest)
    compact_result = COMPACT.run(compact_path)
    if compact_result.get("status") != "COMPLETE_ROOT279_NATIVE_COMPACT_REPORTS_NO_SCIENTIFIC_Q":
        raise RecoveryFailure("compact V3 returned an unexpected status")
    compact_result_path = _abs(compact_manifest["result_path"])
    compact_result_value, compact_result_record = _record_json(compact_result_path, "recovered compact result")
    sealed_path = observer / "compact/recovery-compact-sealed-manifest.json"
    sealed_manifest = _sealed_manifest(compact_manifest, compact_result_value, sealed_path)
    sealed_record = {"path": str(sealed_path), "sha256": _sha(sealed_path.read_bytes()), "stat": _stat(sealed_path)}

    scalar_manifest = dict(scalar_template)
    scalar_manifest["status"] = "READY_FOR_PARENT_ROTATION_INVARIANT_NATIVE_SCALAR"
    scalar_manifest["attempts"] = []
    scalar_manifest.setdefault("source_identity", {})["source_identity_digest"] = identity
    reports = compact_result_value.get("compact_reports")
    if not isinstance(reports, dict):
        raise RecoveryFailure("recovered compact result has no report records")
    # The independent verifier's pair contract is keyed by these stable
    # producer labels.  Recovery changes the parent namespace, not the two
    # already-produced physical attempts, so keep the established IDs.
    for label, attempt_id in (("same_cfl", "root279-same-cfl"), ("half_cfl", "root279-half-cfl")):
        record = reports.get(label)
        if not isinstance(record, dict) or not isinstance(record.get("path"), str) or not record.get("sha256"):
            raise RecoveryFailure(f"recovered compact report missing for {label}")
        scalar_manifest["attempts"].append({"label": label.replace("_", "-"), "attempt_id": attempt_id,
                                             "rows_key": "observations",
                                             "source_identity_digest": identity,
                                             "report": record})
    scalar_manifest_path = observer / "recovery-scalar-manifest.json"
    _write_once(scalar_manifest_path, scalar_manifest)
    scalar_output_path = observer / "recovery-scalar-result.json"
    scalar_result = SCALAR.run(scalar_manifest_path, scalar_output_path)
    scalar_result_value, scalar_result_record = _record_json(scalar_output_path, "recovered scalar result")
    if scalar_result_value.get("status") != "COMPLETE_ROTATION_INVARIANT_NATIVE_SCALAR_DIAGNOSTIC":
        raise RecoveryFailure("scalar V2 returned an unexpected status")
    verification_path = observer / "recovery-independent-verification.json"
    verification = VERIFIER.verify(sealed_path, scalar_manifest_path, scalar_output_path, verification_path)
    verification_value, verification_record = _record_json(verification_path, "recovered scalar verification")

    result = {
        "schema": SCHEMA,
        "status": RESULT_STATUS,
        "recovery_lineage": {
            "checkpoint": checkpoint_record,
            "failed_request": failed_request_record,
            "failed_receipt": failed_receipt_record,
            "failure_stdout": {"path": stdout["path"], "sha256": stdout["sha256"], "stat": stdout["stat"]},
            "parent_manifest": parent_record,
            "producer_guard": guard_record,
            "producer_child": child_record,
            "failed_parent_status": failed_receipt.get("status"),
            "failed_parent_returncode": failed_receipt.get("returncode"),
            "failed_parent_failure": checkpoint.get("failure"),
        },
        "producer_scope": counts,
        "compact_result": compact_result_record,
        "compact_sealed_manifest": sealed_record,
        "scalar_result": scalar_result_record,
        "verification": verification_record,
        "read_scope": {
            "failed_json_and_text_metadata_only": True,
            "guard_result_reused": True,
            "child_report_reused": True,
            "compact_scalar_verifier_json_only": True,
            "native_payload_reopened_by_recovery": False,
            "native_paths_stat_or_hash_by_recovery": False,
            "solver_launch": False,
            "gencase_launch": False,
        },
        "scientific_qualification": {"QI": UNKNOWN, "QN": UNKNOWN, "QE": UNKNOWN, "scientific_credit": 0},
    }
    output_path = observer / "root279-native-scalar-recovery-result-v1.json"
    _write_once(output_path, result)
    result["result"] = {"path": str(output_path), "sha256": _sha(output_path.read_bytes()), "stat": _stat(output_path)}
    return result


def _self_test() -> None:
    """Exercise the complete JSON-only downstream chain on tiny records.

    The production guard is intentionally not invoked here: ROOT353's guard
    output is an immutable input to recovery, and the self-test must prove
    that recovery itself has no native-reader call.  The parent-side actual
    run below additionally binds the real ROOT353 guard/child records.
    """
    with tempfile.TemporaryDirectory(prefix="root279-recovery-v1-") as value:
        root = Path(value)
        producer_dir = root / "producer"
        producer_dir.mkdir(parents=True, exist_ok=True)
        guard_path, child_path = COMPACT.V1._fixture_child(producer_dir)
        gv = json.loads(guard_path.read_text(encoding="utf-8")); gv["status"] = GUARD_STATUS
        guard_path.write_text(json.dumps(gv, sort_keys=True) + "\n", encoding="utf-8")
        cv = json.loads(child_path.read_text(encoding="utf-8")); cv["status"] = CHILD_STATUS
        child_path.write_text(json.dumps(cv, sort_keys=True) + "\n", encoding="utf-8")
        _, guard_rec = COMPACT.V1._record_json(guard_path, "fixture guard")
        _, child_rec = COMPACT.V1._record_json(child_path, "fixture child")
        compact_manifest = {"schema": COMPACT.V1.MANIFEST_SCHEMA,
                            "status": "READY_FOR_PARENT_ROOT279_NATIVE_COMPACT",
                            "source_identity_digest": "fixture-recovery-identity",
                            "guard_result": guard_rec, "child_report": child_rec,
                            "outputs": {label: {"path": str(root / f"{label}.json")} for label in ("same_cfl", "half_cfl")},
                            "result_path": str(root / "compact-result.json")}
        compact_path = root / "compact-manifest.json"
        compact_path.write_text(json.dumps(compact_manifest) + "\n", encoding="utf-8")
        compact_result = COMPACT.run(compact_path)
        assert compact_result["guard_status_basis"] == GUARD_STATUS
        assert compact_result["read_scope"]["native_payload_read"] is False
        sealed_path = root / "sealed-manifest.json"
        _sealed_manifest(compact_manifest, compact_result, sealed_path)
        scalar_manifest = {
            "schema": SCALAR.MANIFEST_SCHEMA,
            "status": "READY_FOR_PARENT_ROTATION_INVARIANT_NATIVE_SCALAR",
            "source_identity": {"source_identity_digest": compact_manifest["source_identity_digest"],
                                 "component_basis": "PRODUCER_COMPONENT_XYZ", "world_orientation": UNKNOWN,
                                 "world_directional_claims": False, "flux_claims": False, "owner_mass_claims": False},
            "attempts": [{"label": label.replace("_", "-"), "attempt_id": label,
                           "rows_key": "observations", "source_identity_digest": compact_manifest["source_identity_digest"],
                           "report": compact_result["compact_reports"][label]}
                          for label in ("same_cfl", "half_cfl")],
            "query_times_s": [0.0, 0.25, 0.5],
        }
        scalar_path = root / "scalar-manifest.json"
        scalar_path.write_text(json.dumps(scalar_manifest) + "\n", encoding="utf-8")
        scalar_output = root / "scalar.json"
        SCALAR.run(scalar_path, scalar_output)
        verification = VERIFIER.verify(sealed_path, scalar_path, scalar_output)
        assert verification["scientific_qualification"]["scientific_credit"] == 0
        print("PASS_ROOT279_METADATA_RECOVERY_V1_REUSES_GUARD_CHILD_COMPACT_SCALAR_VERIFIER")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true"); mode.add_argument("--run", action="store_true")
    parser.add_argument("--manifest", type=Path); parser.add_argument("--attempt-root", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            _self_test(); return 0
        if args.manifest is None or args.attempt_root is None:
            parser.error("--run requires --manifest and --attempt-root")
        result = run(args.manifest, args.attempt_root)
        print(json.dumps({"status": result["status"], "scientific_credit": 0,
                          "native_payload_reopened_by_recovery": False}, sort_keys=True))
        return 0
    except (RecoveryFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_ROOT279_METADATA_RECOVERY_V1: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
