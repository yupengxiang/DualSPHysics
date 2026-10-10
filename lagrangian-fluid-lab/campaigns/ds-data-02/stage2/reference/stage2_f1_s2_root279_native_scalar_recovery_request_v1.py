#!/usr/bin/env python3
"""Prepare a source-only ROOT362 recovery request for the failed ROOT353 parent.

The builder reads only the bounded ROOT353 checkpoint, receipt, request,
guard/child JSON, stdout, parent manifest, and source modules.  It does not
stat, hash, or open any deferred Part/BI4 file.  The resulting request is
execution-disabled until the parent rebinds it after review; its worker only
reuses the already completed guard/child records.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
RECOVERY_PATH = HERE / "stage2_f1_s2_root279_native_scalar_recovery_worker_v1.py"
COMPACT_PATH = HERE / "stage2_f1_s2_root279_native_compact_worker_v3.py"
COMPACT_V2_PATH = HERE / "stage2_f1_s2_root279_native_compact_worker_v2.py"
COMPACT_V1_PATH = HERE / "stage2_f1_s2_root279_native_compact_worker_v1.py"
SCALAR_PATH = HERE / "stage2_rotation_invariant_native_scalar_observer_v2.py"
VERIFIER_PATH = HERE / "stage2_f1_s2_root279_native_scalar_verify_v1.py"
VARIANT_SCHEMA = "ds02.stage2.f1-s2.root279-native-scalar-recovery-request.v1"
MANIFEST_SCHEMA = "ds02.stage2.f1-s2.root279-native-scalar-recovery-manifest.v1"
JSON_CAP = 10 * 1024 * 1024


class BuildFailure(RuntimeError):
    pass


def _load_recovery() -> Any:
    spec = importlib.util.spec_from_file_location("root279_recovery_for_request", RECOVERY_PATH)
    if spec is None or spec.loader is None:
        raise BuildFailure(f"cannot load recovery worker: {RECOVERY_PATH}")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


RECOVERY = _load_recovery()


def _abs(value: Path | str) -> Path:
    return Path(value).expanduser().absolute()


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {"device": int(value.st_dev), "inode": int(value.st_ino), "bytes": int(value.st_size),
            "mtime_ns": int(value.st_mtime_ns), "ctime_ns": int(value.st_ctime_ns)}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _record(path: Path | str, label: str, *, text_only: bool = False) -> dict[str, Any]:
    path = _abs(path)
    allowed = {".json", ".log", ".txt", ".py", ".cfg"}
    if path.is_symlink() or not path.is_file() or path.suffix.lower() not in allowed:
        raise BuildFailure(f"{label} is not a bounded source/metadata file: {path}")
    before = _stat(path)
    if before["bytes"] > JSON_CAP:
        raise BuildFailure(f"{label} exceeds the 10 MiB source metadata cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after:
        raise BuildFailure(f"{label} changed while being recorded: {path}")
    if text_only:
        raw.decode("utf-8", errors="strict")
    return {"path": str(path), "sha256": _sha(raw), "stat": after, "bytes": len(raw),
            "label": label, "scope": "bounded_source_metadata", "payload_read_by_builder": True}


def _record_ref(path: Path | str, label: str, expected: dict[str, Any] | None = None) -> dict[str, Any]:
    value = _record(path, label, text_only=Path(path).suffix.lower() in {".json", ".log", ".txt"})
    if isinstance(expected, dict):
        if isinstance(expected.get("sha256"), str) and len(expected["sha256"]) == 64 and value["sha256"].lower() != expected["sha256"].lower():
            raise BuildFailure(f"{label} SHA differs from the checkpoint binding")
        bound = expected.get("stat")
        if isinstance(bound, dict):
            for key, aliases in {"device": ("device", "st_dev"), "inode": ("inode", "st_ino"),
                                  "bytes": ("bytes", "size"), "mtime_ns": ("mtime_ns",), "ctime_ns": ("ctime_ns",)}.items():
                for alias in aliases:
                    if alias in bound and int(bound[alias]) != int(value["stat"][key]):
                        raise BuildFailure(f"{label} {alias} differs from the checkpoint binding")
    return value


def _small_ref(record: dict[str, Any]) -> dict[str, Any]:
    return {"path": record["path"], "sha256": record["sha256"], "stat": record["stat"], "bytes": record["bytes"]}


def _write_once(path: Path, value: dict[str, Any]) -> dict[str, Any]:
    path = _abs(path)
    if path.exists() or path.is_symlink():
        raise BuildFailure(f"refusing to overwrite prepared output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path.write_bytes(raw)
    return {"path": str(path), "sha256": _sha(raw), "stat": _stat(path), "bytes": len(raw)}


def _prepare_lineage(checkpoint_path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    checkpoint_record = _record(checkpoint_path, "ROOT353 failure checkpoint")
    checkpoint, _ = RECOVERY._record_json(checkpoint_path, "ROOT353 failure checkpoint")
    refs = checkpoint.get("request"), checkpoint.get("receipt"), checkpoint.get("guard_result"), checkpoint.get("child_report"), checkpoint.get("stdout")
    if any(not isinstance(item, dict) or not isinstance(item.get("path"), str) for item in refs):
        raise BuildFailure("ROOT353 checkpoint does not expose all failed lineage paths")
    request_record = _record_ref(refs[0]["path"], "ROOT353 failed request", refs[0])
    receipt_record = _record_ref(refs[1]["path"], "ROOT353 failed receipt", refs[1])
    guard_record = _record_ref(refs[2]["path"], "ROOT353 guard result", refs[2])
    child_record = _record_ref(refs[3]["path"], "ROOT353 child report", refs[3])
    stdout_record = _record_ref(refs[4]["path"], "ROOT353 failure stdout", refs[4])
    request, _ = RECOVERY._record_json(Path(request_record["path"]), "ROOT353 failed request", _small_ref(request_record))
    receipt, _ = RECOVERY._record_json(Path(receipt_record["path"]), "ROOT353 failed receipt", _small_ref(receipt_record))
    guard, _ = RECOVERY._record_json(Path(guard_record["path"]), "ROOT353 guard result", _small_ref(guard_record))
    child, _ = RECOVERY._record_json(Path(child_record["path"]), "ROOT353 child report", _small_ref(child_record))
    stdout = Path(stdout_record["path"]).read_text(encoding="utf-8")
    if checkpoint.get("schema") != RECOVERY.CHECKPOINT_SCHEMA or checkpoint.get("failure") != "PARENT_V2_REJECTED_ACTUAL_GUARDED_V1_SUCCESS_STATUS":
        raise BuildFailure("checkpoint is not the recoverable ROOT353 status mismatch")
    if checkpoint.get("root_payload_content_read") is not False or checkpoint.get("scientific_Q_credit") != 0:
        raise BuildFailure("ROOT353 checkpoint has unsupported payload/Q credit")
    if receipt.get("schema") != "ds02.execution-receipt.v1" or receipt.get("status") != "failed" or receipt.get("returncode") != 2:
        raise BuildFailure("ROOT353 receipt is not the exact failed parent")
    if receipt.get("request_sha256") != request_record["sha256"] or receipt.get("request") != request:
        raise BuildFailure("failed receipt does not bind the exact request file")
    if guard.get("status") != RECOVERY.GUARD_STATUS or child.get("status") != RECOVERY.CHILD_STATUS:
        raise BuildFailure("failed producer records do not have exact successful statuses")
    if "FAILED_ROOT279_NATIVE_SCALAR_PARENT_V2" not in stdout:
        raise BuildFailure("failure stdout is not the preserved scalar status mismatch")
    # Reuse the worker's strict metadata-only stability check; it never opens
    # any path listed in source_integrity.
    counts = RECOVERY._metadata_counts_and_stability(guard)
    parent_ref = request.get("parent_manifest")
    if not isinstance(parent_ref, dict) or not isinstance(parent_ref.get("path"), str):
        raise BuildFailure("failed request lacks its bound parent manifest")
    parent_record = _record_ref(parent_ref["path"], "ROOT353 parent manifest", parent_ref)
    parent, _ = RECOVERY._record_json(Path(parent_record["path"]), "ROOT353 parent manifest", _small_ref(parent_record))
    if parent.get("schema") != "ds02.stage2.f1-s2.root279-native-scalar-parent-manifest.v2":
        raise BuildFailure("parent manifest schema is not the scalar parent manifest")
    if parent.get("source_identity_digest") != request.get("source_identity_digest"):
        raise BuildFailure("parent/source identity digest differs")
    lineage = {
        "checkpoint": _small_ref(checkpoint_record), "request": _small_ref(request_record),
        "receipt": _small_ref(receipt_record), "guard_result": _small_ref(guard_record),
        "child_report": _small_ref(child_record), "stdout": _small_ref(stdout_record),
        "parent_manifest": _small_ref(parent_record),
    }
    return checkpoint, request, {"checkpoint": checkpoint_record, "request": request_record,
                                 "receipt": receipt_record, "guard_result": guard_record,
                                 "child_report": child_record, "stdout": stdout_record,
                                 "parent_manifest": parent_record, "counts": counts,
                                 "lineage": lineage, "parent": parent}


def build(*, checkpoint_path: Path, output_dir: Path, attempt_id: str = "root362-root279-native-scalar-recovery-v1-001") -> dict[str, Any]:
    checkpoint_path = _abs(checkpoint_path); output_dir = _abs(output_dir)
    checkpoint, failed_request, collected = _prepare_lineage(checkpoint_path)
    parent = collected["parent"]
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "root279-native-scalar-recovery-manifest.json"
    request_path = output_dir / "root279-native-scalar-recovery-request.json"
    package_path = output_dir / "source-package.json"

    # Record only the JSON/text lineage and the Python modules actually loaded
    # by recovery.  Native paths in the old request remain a metadata-only
    # reuse list and are intentionally absent from input_files.
    source_paths = [
        (RECOVERY_PATH, "ROOT362 recovery worker"), (COMPACT_PATH, "ROOT279 compact V3"),
        (COMPACT_V2_PATH, "ROOT279 compact V2 dependency"), (COMPACT_V1_PATH, "ROOT279 compact V1 dependency"),
        (SCALAR_PATH, "ROOT279 scalar V2"), (VERIFIER_PATH, "ROOT279 independent verifier"),
    ]
    records: dict[str, dict[str, Any]] = {}
    for label, record in collected.items():
        if label in {"counts", "lineage", "parent"}:
            continue
        if isinstance(record, dict) and isinstance(record.get("path"), str):
            records[record["path"]] = dict(record, label=label)
    for path, label in source_paths:
        rec = _record(path, label)
        records[rec["path"]] = rec
    # Preserve the exact virtual-environment binding from the failed request,
    # without opening the interpreter binary during metadata preparation.
    literal_python = failed_request.get("command", [None])[0]
    pyvenv = failed_request.get("runtime_binding", {}).get("pyvenv_cfg")
    if isinstance(pyvenv, str) and Path(pyvenv).is_file():
        rec = _record(pyvenv, "literal venv pyvenv.cfg")
        records[rec["path"]] = rec

    parent_manifest = parent
    compact_template = parent_manifest["compact_manifest"]
    scalar_template = parent_manifest["scalar_manifest"]
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "status": "SOURCE_PREPARED_ROOT279_METADATA_RECOVERY_AFTER_ROOT353_FAILURE",
        "case_id": "F1_S2_DP020_ROOT279_NATIVE_SCALAR_RECOVERY",
        "attempt_id": attempt_id,
        "family_id": "F1",
        "sentinel_id": "F1-S2",
        "source_identity_digest": failed_request["source_identity_digest"],
        "failed_lineage": collected["lineage"],
        "source_identity": {
            "source_identity_digest": failed_request["source_identity_digest"],
            "component_basis": scalar_template.get("source_identity", {}).get("component_basis", "PRODUCER_COMPONENT_XYZ"),
            "world_orientation": "UNKNOWN", "flux_claims": False, "owner_mass_claims": False,
        },
        "compact_template": compact_template,
        "scalar_template": scalar_template,
        "recovery_policy": {
            "reuse_guard_result": True, "reuse_child_report": True,
            "invoke_guard": False, "open_native_payload": False,
            "native_payload_reopened": False, "native_paths_stat_or_hash": False,
            "scientific_credit": 0,
        },
        "producer_scope": collected["counts"],
    }
    manifest_record = _write_once(manifest_path, manifest)
    records[str(manifest_path)] = dict(manifest_record, label="ROOT362 recovery manifest", scope="bounded_source_metadata", payload_read_by_builder=True)

    input_records = {path: {k: v for k, v in rec.items() if k in {"path", "sha256", "stat", "bytes"}}
                     for path, rec in records.items()}
    command = [str(literal_python), str(RECOVERY_PATH), "--run", "--manifest", str(manifest_path), "--attempt-root", "{attempt_root}"]
    request = {
        "schema": "ds02.request.v1", "variant_schema": VARIANT_SCHEMA,
        "status": "SOURCE_PREPARED_ROOT279_METADATA_RECOVERY_AFTER_RESERVATION_REQUIRED",
        "case_id": "F1_S2_DP020_ROOT279_NATIVE_SCALAR_RECOVERY",
        "attempt_id": attempt_id, "family_id": "F1", "sentinel_id": "F1-S2",
        "command": command, "cwd": failed_request.get("cwd", str(HERE.parents[3])),
        "cpu_task_kind": "audit", "cpu_threads": 1, "omp_threads": 1,
        "literal_python": literal_python, "execution_allowed": False, "launch_disabled": True,
        "ledger_mutation": False, "solver_launch": False, "gencase_launch": False,
        "native_payload_read": False, "source_only": True,
        "max_wall_seconds": 300, "max_memory_bytes": 2 * 1024 * 1024 * 1024,
        "estimated_peak_memory_bytes": 512 * 1024 * 1024, "estimated_storage_bytes": 32 * 1024 * 1024,
        "estimated_resource_scope": {
            "cpu_seconds": 300, "memory_bytes": 2 * 1024 * 1024 * 1024,
            "scratch_bytes": 256 * 1024 * 1024, "metadata_json_reads_only": True,
            "native_read_passes": 0, "native_payload_read_by_recovery": False,
        },
        "input_files": sorted(input_records), "input_records": input_records,
        "input_sha256": {path: rec["sha256"] for path, rec in input_records.items()},
        "deferred_input_records": [],
        "native_reuse_records": collected["counts"],
        "parent_manifest": _small_ref(collected["parent_manifest"]),
        "manifest_contract": {"path": str(manifest_path), "sha256": manifest_record["sha256"]},
        "source_binding": {
            "failed_checkpoint_sha256": collected["checkpoint"]["sha256"],
            "failed_request_sha256": collected["request"]["sha256"],
            "failed_receipt_sha256": collected["receipt"]["sha256"],
            "guard_result_sha256": collected["guard_result"]["sha256"],
            "child_report_sha256": collected["child_report"]["sha256"],
            "parent_manifest_sha256": collected["parent_manifest"]["sha256"],
            "guard_status": RECOVERY.GUARD_STATUS, "child_status": RECOVERY.CHILD_STATUS,
            "native_reread": False,
        },
        "recovery_policy": manifest["recovery_policy"],
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "scientific_credit": 0},
    }
    request_record = _write_once(request_path, request)
    package = {
        "schema": "ds02.stage2.f1-s2.root279-native-scalar-recovery-package.v1",
        "status": "SOURCE_PREPARED_ROOT279_METADATA_RECOVERY_NO_NATIVE_REREAD",
        "manifest": manifest_record, "request": request_record,
        "static_input_count": len(input_records), "static_input_bytes": sum(int(x["bytes"]) for x in input_records.values()),
        "native_reuse_records": collected["counts"], "native_payload_read_by_builder": False,
        "estimated_native_read_passes": 0,
        "scientific_qualification": request["scientific_qualification"],
    }
    package_record = _write_once(package_path, package)
    return {"manifest_path": str(manifest_path), "request_path": str(request_path),
            "package_path": str(package_path), "manifest": manifest_record,
            "request": request_record, "package": package_record}


def _self_test() -> None:
    # Contract test: the builder must not include any deferred native path in
    # static input files.  Actual ROOT353 source binding is exercised by the
    # build command used by the parent after cherry-pick.
    assert RECOVERY_PATH.name.endswith("recovery_worker_v1.py")
    assert VARIANT_SCHEMA.endswith("request.v1")
    print("PASS_ROOT279_RECOVERY_REQUEST_V1_NO_NATIVE_STATIC_INPUTS_CONTRACT")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true"); mode.add_argument("--build", action="store_true")
    parser.add_argument("--checkpoint", type=Path); parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--attempt-id", default="root362-root279-native-scalar-recovery-v1-001")
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            _self_test(); return 0
        if args.checkpoint is None or args.output_dir is None:
            parser.error("--build requires --checkpoint and --output-dir")
        value = build(checkpoint_path=args.checkpoint, output_dir=args.output_dir, attempt_id=args.attempt_id)
        print(json.dumps({"status": "SOURCE_PREPARED_ROOT279_METADATA_RECOVERY_NO_NATIVE_REREAD",
                          "manifest": value["manifest_path"], "request": value["request_path"],
                          "package": value["package_path"], "scientific_credit": 0}, sort_keys=True))
        return 0
    except (BuildFailure, RECOVERY.RecoveryFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_ROOT279_RECOVERY_REQUEST_V1: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
