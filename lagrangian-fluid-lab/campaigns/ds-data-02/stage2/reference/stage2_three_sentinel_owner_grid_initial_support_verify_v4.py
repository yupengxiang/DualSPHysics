#!/usr/bin/env python3
"""Verify initial-support products and exercise the real runtime receipt ABI.

This is an additive successor to ``initial_support_verify_v2.py``.  The
frozen V2 verifier hashes a canonical JSON serialization of
``receipt['request']``.  runtime-v8 receipts instead store the SHA-256 of the
exact producer request file bytes.  V3 therefore requires each manifest row
to carry an explicit ``producer_request`` record, reads that request file
under the same bounded metadata guard, and joins it byte-for-byte to the
runtime receipt.  It also accepts both source-prepared requests
(``execution_allowed=false``) and an actual parent-normalized request
(``execution_allowed=true``); it never treats either state as scientific
qualification.

The row-level V1/V2 checks and all payload guards remain in force.  This
module does not start GenCase or a solver and does not read VTK/BI4 payloads
outside the already guarded worker report.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import tempfile
import subprocess
from datetime import datetime, timedelta, timezone
from typing import Any


HERE = Path(__file__).resolve().parent
V2_PATH = HERE / "stage2_three_sentinel_owner_grid_initial_support_verify_v2.py"
SCHEMA = "ds02.stage2.three-sentinel-owner-grid-initial-support-verifier.v4"
REQUEST_SCHEMA = "ds02.request.v1"
RECEIPT_SCHEMA = "ds02.execution-receipt.v1"
MANIFEST_SCHEMA = "ds02.stage2.three-sentinel-owner-grid-initial-support-manifest.v1"
JSON_CAP = 10 * 1024 * 1024
TARGETS = ("F2-S2", "F3-S1", "F5-S1")
GRIDS = ("original", "coarse", "fine")
ROW_KEYS = tuple(f"{sid}:{grid}" for sid in TARGETS for grid in GRIDS)
STAT_FIELDS = ("device", "inode", "bytes", "mtime_ns", "ctime_ns")


class VerifyFailure(RuntimeError):
    pass


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise VerifyFailure(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V2 = _load(V2_PATH, "owner_grid_initial_support_verify_v2_for_v3")


def _abs(value: Path) -> Path:
    return value.expanduser().absolute()


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-fA-F]{64}", value))


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {"device": int(value.st_dev), "inode": int(value.st_ino),
            "bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns),
            "ctime_ns": int(value.st_ctime_ns)}


def _record_stat(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    source = value.get("stat") or value.get("stat_after") or value.get("stat_post") or {}
    aliases = {"device": ("device", "dev", "st_dev"),
               "inode": ("inode", "ino", "st_ino"),
               "bytes": ("bytes", "size"),
               "mtime_ns": ("mtime_ns",), "ctime_ns": ("ctime_ns",)}
    result: dict[str, int] = {}
    if isinstance(source, dict):
        for target, names in aliases.items():
            for name in names:
                if name in source:
                    result[target] = int(source[name])
                    break
    return result


def _read_json(path: Path, label: str) -> tuple[Any, dict[str, Any], bytes]:
    path = _abs(path)
    if path.is_symlink() or not path.is_file():
        raise VerifyFailure(f"{label} is not a regular non-symlink JSON file: {path}")
    before = _stat(path)
    if before["bytes"] > JSON_CAP:
        raise VerifyFailure(f"{label} exceeds the 10 MiB JSON cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after or len(raw) != before["bytes"]:
        raise VerifyFailure(f"{label} changed during bounded JSON read: {path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerifyFailure(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise VerifyFailure(f"{label} must be an object: {path}")
    return value, {"path": str(path), "sha256": _sha(raw), "stat": after}, raw


def _path_record(value: Any, label: str) -> tuple[Path, dict[str, Any]]:
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        raise VerifyFailure(f"{label} lacks an explicit path record")
    path = _abs(Path(value["path"]))
    if path.is_symlink() or not path.is_file():
        raise VerifyFailure(f"{label} is not a regular file: {path}")
    actual = _stat(path)
    expected = _record_stat(value)
    for key, declared in expected.items():
        if actual[key] != declared:
            raise VerifyFailure(f"{label} current {key} differs from its record")
    declared_sha = value.get("sha256")
    if _valid_sha(declared_sha):
        raw = path.read_bytes()
        if _sha(raw).lower() != str(declared_sha).lower():
            raise VerifyFailure(f"{label} SHA differs from its record")
        # Request/receipt JSON is bounded; this is deliberately not a helper
        # for native, VTK, or HDF5 payloads.
        if len(raw) > JSON_CAP:
            raise VerifyFailure(f"{label} exceeds the metadata cap")
    return path, {"path": str(path), "sha256": declared_sha, "stat": actual}


def _producer_record(case: dict[str, Any], key: str) -> dict[str, Any]:
    for name in ("producer_request", "gencase_request", "producer_request_record"):
        value = case.get(name)
        if isinstance(value, dict) and isinstance(value.get("path"), str):
            return value
    # The additive builder may keep the row-specific record in a map rather
    # than duplicating it on the case.  V3 accepts that only when the map is
    # already part of the manifest; callers must not select an arbitrary
    # newest request by basename.
    maps = case.get("producer_requests")
    if isinstance(maps, dict) and isinstance(maps.get(key), dict):
        value = maps[key]
        if isinstance(value.get("path"), str):
            return value
    raise VerifyFailure(f"{key} has no explicit producer_request record")


def _request_mode(request: dict[str, Any]) -> str:
    allowed = request.get("execution_allowed")
    if isinstance(allowed, bool):
        return "actual_parent_request" if allowed else "source_prepared_request"
    raise VerifyFailure("request execution_allowed must be an explicit boolean")


def _check_request_closure_v3(request: dict[str, Any], request_path: Path,
                              manifest: dict[str, Any], manifest_path: Path) -> dict[str, Any]:
    """V2 closure with source-prepared/actual-parent modes kept distinct."""
    if request.get("schema") != REQUEST_SCHEMA:
        raise VerifyFailure("initial-support request schema mismatch")
    if request.get("variant_schema") != "ds02.stage2.three-sentinel-owner-grid-initial-support-audit.v1":
        raise VerifyFailure("initial-support request worker schema mismatch")
    if request.get("read_cap_bytes") != JSON_CAP:
        raise VerifyFailure("request does not declare the strict 10 MiB JSON/source cap")
    if request.get("large_control_policy") != "stat_only_deferred_with_owner_sha":
        raise VerifyFailure("request does not preserve the large-control deferred policy")
    mode = _request_mode(request)
    if mode == "source_prepared_request":
        if request.get("solver_launch") is not False or request.get("gencase_launch") is not False:
            raise VerifyFailure("source-prepared request permits GenCase/solver execution")
    else:
        # A root-normalized request may execute only this audit parent.  It
        # must still be an audit, never a solver, and it must expose a root
        # binding instead of silently reusing a source-prepared placeholder.
        if request.get("solver_launch") is True or request.get("gencase_launch") is True:
            raise VerifyFailure("actual initial-support request launches GenCase/solver")
        binding = request.get("root_canonical_binding") or request.get("parent_v8_binding")
        if binding is not None and not isinstance(binding, dict):
            raise VerifyFailure("actual request root binding is malformed")
        if request.get("attempt_id") in (None, "PARENT_ASSIGNED_AFTER_GENCASE", "{attempt_id}"):
            raise VerifyFailure("actual request retains a source-prepared attempt placeholder")
    input_files = request.get("input_files")
    input_records = request.get("input_records")
    input_sha = request.get("input_sha256")
    if not isinstance(input_files, list) or len(input_files) != len(set(input_files)):
        raise VerifyFailure("request input_files is not a unique list")
    if not isinstance(input_records, dict) or set(input_records) != set(input_files):
        raise VerifyFailure("input_records is not exactly the runtime static input_files set")
    if not isinstance(input_sha, dict) or set(input_sha) != set(input_files):
        raise VerifyFailure("input_sha256 is not exactly keyed by input_files")
    for path_text in input_files:
        record = input_records[path_text]
        path, actual = _path_record(record, f"static input {path_text}")
        if str(path) != str(_abs(Path(path_text))):
            raise VerifyFailure(f"static input path normalization changed: {path_text}")
        if not _valid_sha(input_sha[path_text]) or not _valid_sha(record.get("sha256")):
            raise VerifyFailure(f"static input {path_text} lacks a concrete SHA")
        if input_sha[path_text].lower() != str(record["sha256"]).lower():
            raise VerifyFailure(f"static input {path_text} digest map disagrees with record")
        if actual["sha256"] and actual["sha256"].lower() != str(input_sha[path_text]).lower():
            raise VerifyFailure(f"static input {path_text} current bytes differ from digest")
    deferred = request.get("deferred_input_records")
    if not isinstance(deferred, list):
        raise VerifyFailure("request deferred_input_records is not a list")
    static_paths = set(input_files)
    signatures: dict[str, tuple[Any, ...]] = {}
    for index, record in enumerate(deferred):
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            raise VerifyFailure(f"deferred input {index} is malformed")
        path = _abs(Path(record["path"]))
        key = str(path)
        sig = (record.get("sha256"), json.dumps(_record_stat(record), sort_keys=True),
               record.get("read_mode"), record.get("hash_status"))
        if key in signatures and signatures[key] != sig:
            raise VerifyFailure(f"deferred input has conflicting repeated records: {key}")
        signatures[key] = sig
        if key in static_paths:
            raise VerifyFailure(f"deferred input is incorrectly in static input_files: {key}")
        if path.exists():
            _path_record(record, f"deferred input {key}")
    manifest_record = request.get("manifest")
    manifest_ref, _ = _path_record(manifest_record, "request manifest")
    if manifest_ref != _abs(manifest_path):
        raise VerifyFailure("request manifest path does not bind supplied manifest")
    if not _valid_sha(manifest_record.get("sha256")):
        raise VerifyFailure("request manifest record has no concrete SHA")
    _, actual_manifest_record, _ = _read_json(manifest_path, "supplied support manifest")
    if actual_manifest_record["sha256"].lower() != str(manifest_record["sha256"]).lower():
        raise VerifyFailure("request manifest SHA does not match supplied bytes")
    if manifest.get("read_cap_bytes") != JSON_CAP or manifest.get("schema") != MANIFEST_SCHEMA:
        raise VerifyFailure("support manifest cap/schema mismatch")
    return {"mode": mode, "static_count": len(input_files),
            "deferred_count": len(deferred), "manifest_sha256": actual_manifest_record["sha256"]}


def _receipt_identity_v3(receipt_path: Path, case: dict[str, Any], receipt: dict[str, Any]) -> dict[str, str]:
    """Join runtime receipt to the exact producer request file bytes."""
    if receipt.get("schema") != RECEIPT_SCHEMA:
        raise VerifyFailure(f"{receipt_path} receipt schema mismatch")
    output_root = _abs(receipt_path.parent)
    if receipt.get("output_root") != str(output_root):
        raise VerifyFailure(f"{receipt_path} output_root does not equal receipt parent")
    producer_record = _producer_record(case, f"{case.get('sentinel_id')}:{case.get('grid_label')}")
    producer_path, producer_actual = _path_record(producer_record, "producer request")
    producer_doc, producer_file_record, producer_raw = _read_json(producer_path, "producer request")
    if receipt.get("request") != producer_doc:
        raise VerifyFailure(f"{receipt_path} receipt.request differs from producer request file")
    receipt_sha = receipt.get("request_sha256")
    if not _valid_sha(receipt_sha) or str(receipt_sha).lower() != _sha(producer_raw):
        raise VerifyFailure(f"{receipt_path} request_sha256 does not bind producer request file bytes")
    declared_sha = producer_record.get("sha256")
    if _valid_sha(declared_sha) and str(declared_sha).lower() != producer_file_record["sha256"].lower():
        raise VerifyFailure(f"{receipt_path} producer request record SHA differs from file bytes")
    expected_case = output_root.parent.name
    expected_attempt = output_root.name
    request = producer_doc
    if request.get("case_id") != expected_case or request.get("attempt_id") != expected_attempt:
        raise VerifyFailure(f"{receipt_path} producer request case/attempt does not bind output path")
    if request.get("family_id") != str(case.get("family_id")):
        raise VerifyFailure(f"{receipt_path} producer request family does not bind manifest case")
    if request.get("kind") not in {"cpu", "generic-cpu-audit"}:
        raise VerifyFailure(f"{receipt_path} producer request kind is not CPU")
    try:
        returncode = int(receipt.get("returncode"))
    except (TypeError, ValueError) as exc:
        raise VerifyFailure(f"{receipt_path} runtime returncode is not integer") from exc
    status = str(receipt.get("status"))
    if status == "completed" and returncode != 0:
        raise VerifyFailure(f"{receipt_path} completed with nonzero returncode")
    if status != "completed" and returncode == 0:
        raise VerifyFailure(f"{receipt_path} noncompleted receipt has zero returncode")
    for field in ("input_hashes_at_launch", "input_hashes_after_run"):
        if not isinstance(receipt.get(field), dict):
            raise VerifyFailure(f"{receipt_path} lacks {field}")
    # A root actual request must stop using source placeholders.  This check is
    # deliberately conditional so a source-prepared product map remains a
    # valid input to the preflight verifier.
    actual_root = request.get("execution_allowed") is True
    if actual_root and request.get("output_root") not in (None, str(output_root)):
        raise VerifyFailure(f"{receipt_path} actual producer output_root differs")
    return {"status": status, "returncode": str(returncode), "family_id": str(case.get("family_id")),
            "case_id": expected_case, "attempt_id": expected_attempt,
            "producer_request": str(producer_path), "producer_request_sha256": _sha(producer_raw),
            "runtime_request_sha256_basis": "EXACT_PRODUCER_REQUEST_FILE_BYTES"}


def _check_producer_requests(manifest: dict[str, Any], output: dict[str, Any]) -> dict[str, Any]:
    rows = output.get("cases")
    if not isinstance(rows, list):
        raise VerifyFailure("worker report has no cases")
    by_key = {str(row.get("row_key")): row for row in rows if isinstance(row, dict)}
    manifest_rows = {f"{row.get('sentinel_id')}:{row.get('grid_label')}": row
                     for row in manifest.get("cases", []) if isinstance(row, dict)}
    if set(manifest_rows) != set(ROW_KEYS) or set(by_key) != set(ROW_KEYS):
        raise VerifyFailure("producer request binding does not cover exactly nine rows")
    joined: dict[str, Any] = {}
    for key in ROW_KEYS:
        case = manifest_rows[key]
        receipt_record = case.get("gencase_receipt")
        receipt_path = _abs(Path(receipt_record["path"])) if isinstance(receipt_record, dict) and isinstance(receipt_record.get("path"), str) else None
        if receipt_path is None:
            raise VerifyFailure(f"{key} receipt path missing")
        receipt, _, _ = _read_json(receipt_path, f"{key} runtime receipt")
        identity = _receipt_identity_v3(receipt_path, case, receipt)
        joined[key] = identity
    return joined


def verify(manifest_path: Path, request_path: Path, output_path: Path,
           verification_output: Path | None = None) -> dict[str, Any]:
    # Patch only the in-memory additive import.  Frozen V2/V1 files and
    # outputs remain byte-for-byte untouched.
    V2._check_request_closure = _check_request_closure_v3
    V2._receipt_identity = _receipt_identity_v3
    result = V2.verify(manifest_path, request_path, output_path)
    manifest, _, _ = _read_json(manifest_path, "owner-grid support manifest")
    output, _, _ = _read_json(output_path, "owner-grid support worker report")
    producer = _check_producer_requests(manifest, output)
    result = dict(result)
    result["schema"] = SCHEMA
    result["status"] = "VERIFIED_THREE_SENTINEL_OWNER_GRID_INITIAL_SUPPORT_V3_RUNTIME_REQUEST_JOIN"
    result["producer_request_identity"] = producer
    result["runtime_request_sha256_basis"] = "EXACT_PRODUCER_REQUEST_FILE_BYTES"
    result["scientific_qualification"] = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "scientific_credit": 0}
    if verification_output is not None:
        path = _abs(verification_output)
        if path.exists() or path.is_symlink():
            raise VerifyFailure(f"refusing overwrite: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def _fixture_request(path: Path, family: str, case_id: str, attempt_id: str) -> dict[str, Any]:
    return {"schema": REQUEST_SCHEMA, "family_id": family, "case_id": case_id,
            "attempt_id": attempt_id, "kind": "cpu", "cpu_task_kind": "gencase",
            "execution_allowed": False, "gencase_launch": False, "solver_launch": False,
            "output_root": str(path.parent)}


def _fixture_record(path: Path) -> dict[str, Any]:
    raw = path.read_bytes(); st = _stat(path)
    return {"path": str(path.absolute()), "sha256": _sha(raw), "stat": st,
            "hash_status": "BOUND_RUNTIME_FIXTURE", "payload_read_by_builder": False}



def _runtime_v8_tiny_cpu_fixture(root: Path) -> dict[str, Any]:
    """Run primary runtime-v8 against only tiny source/code files.

    This is an ABI test, not a production experiment.  The data-root and
    resource ledger are temporary, the child merely prints one line, and no
    GenCase/solver/native payload is present.  The primary runtime is invoked
    through the literal venv path used by source requests so request-file SHA
    and receipt fields are produced by the actual runner rather than a hand
    written receipt fixture.
    """
    primary = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics").resolve()
    scripts = primary / "lagrangian-fluid-lab" / "scripts"
    runtime = scripts / "ds_data02_runtime_v8.py"
    runtime_v6 = scripts / "ds_data02_runtime_v6.py"
    runtime_v2 = scripts / "ds_data02_runtime_v2.py"
    python = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
    pyvenv = python.parent.parent / "pyvenv.cfg"
    for path, label in ((runtime, "primary runtime-v8"), (runtime_v6, "primary runtime-v6"),
                        (runtime_v2, "primary runtime-v2"), (python, "literal venv python"),
                        (pyvenv, "literal venv pyvenv.cfg")):
        if not path.exists() or path.is_symlink() and label.startswith("primary"):
            raise AssertionError(f"missing {label}: {path}")
    data_root = root / "runtime-data"
    data_root.mkdir()
    (data_root / "runtime").mkdir()
    deadline = datetime.now(timezone.utc) + timedelta(minutes=5)
    ledger = {
        "schema": "ds02.runtime.resource-ledger.v1",
        "campaign_id": "tiny-runtime-v8-initial-support-abi-fixture",
        "deadline_utc": deadline.isoformat(),
        "limits": {"gpu_seconds": 0.0, "cpu_core_seconds": 120.0,
                    "new_storage_bytes": 64 * 1024 * 1024,
                    "qualification_attempts": 0, "production_attempts": 0,
                    "storage_policy": "external", "home_min_free_bytes": 0},
        "charges": [], "reservations": [], "attempts": [],
    }
    (data_root / "runtime/resource-ledger.json").write_text(
        json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    fixture = root / "tiny-control.json"
    fixture.write_text('{"fixture":"runtime-v8-abi","payload_read_scope":"tiny"}\n', encoding="utf-8")
    cwd = root / "child-cwd"; cwd.mkdir()
    case = "INITIAL_SUPPORT_RUNTIME_ABI_FIXTURE"
    attempt = "initial-support-runtime-abi-fixture-001"
    output_root = data_root / "families" / "F1" / case / attempt
    input_files = [runtime, runtime_v6, runtime_v2, fixture]
    request = {
        "schema": "ds02.request.v1", "status": "READY_FOR_PARENT_GUARD",
        "request_variant": "initial-support-runtime-v8-abi-fixture-v1",
        "family_id": "F1", "sentinel_id": "F1-S1", "case_id": case,
        "attempt_id": attempt, "kind": "cpu", "cpu_task_kind": "audit",
        "command": [str(python), "-c", "print('tiny-runtime-v8-child')"],
        "cwd": str(cwd), "worktree_root": str(primary),
        "max_wall_seconds": 30.0, "cpu_threads": 1,
        "estimated_storage_bytes": 2 * 1024 * 1024,
        "output_root": str(output_root), "input_files": [str(p) for p in input_files],
        "input_sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in input_files},
        "execution_allowed": True, "launch_disabled": False,
        "gencase_launch": False, "solver_launch": False,
        "source_only": False, "production_eligible": False,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    request_path = root / "runtime-request-pretty.json"
    request_path.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    command = [str(python), str(runtime), "run", "--request", str(request_path),
               "--data-root", str(data_root)]
    completed = subprocess.run(command, cwd=str(primary), capture_output=True, text=True,
                               timeout=60)
    if completed.returncode != 0:
        raise AssertionError(f"primary runtime-v8 tiny command failed: {completed.stdout} {completed.stderr}")
    receipt_path = output_root / "execution-receipt.json"
    if not receipt_path.is_file():
        raise AssertionError("primary runtime-v8 did not write execution-receipt.json")
    receipt_raw = receipt_path.read_bytes()
    receipt = json.loads(receipt_raw.decode("utf-8"))
    request_raw = request_path.read_bytes()
    if receipt.get("schema") != "ds02.execution-receipt.v1" or receipt.get("status") != "completed":
        raise AssertionError(f"tiny runtime receipt is not completed: {receipt.get('status')}")
    if receipt.get("returncode") != 0:
        raise AssertionError("tiny runtime child did not return zero")
    if receipt.get("request") != request:
        raise AssertionError("runtime receipt did not preserve exact pretty request object")
    if receipt.get("request_sha256") != _sha(request_raw):
        raise AssertionError("runtime receipt request_sha256 is not raw request-file SHA")
    launch = receipt.get("input_hashes_at_launch")
    after = receipt.get("input_hashes_after_run")
    if not isinstance(launch, dict) or launch != after:
        raise AssertionError("runtime launch/after-run source hashes are not equal")
    if receipt.get("source_preflight", {}).get("reservation_registered_before_content_hash") is not True:
        raise AssertionError("runtime did not record reservation-before-hash ordering")
    if receipt.get("runner_source") != str(runtime):
        raise AssertionError("runtime receipt runner source is not the frozen primary runtime-v8")
    return {"runtime_command": command, "request_path": str(request_path),
            "request_sha256": _sha(request_raw), "receipt_path": str(receipt_path),
            "receipt_sha256": _sha(receipt_raw), "receipt_status": receipt.get("status"),
            "input_hashes_at_launch": launch, "input_hashes_after_run": after,
            "qualification": receipt.get("qualification"),
            "production_credit": 0, "payload_read": False,
            "literal_python": str(python), "runtime_source": str(runtime),
            "pyvenv_path": str(pyvenv)}


def self_test() -> None:
    """Run the frozen worker join and a real primary runtime-v8 tiny CPU command."""
    worker = _load(V2.WORKER_PATH, "owner_grid_support_worker_v3_fixture")
    with tempfile.TemporaryDirectory(prefix="owner-grid-support-verify-v3-") as value:
        root = Path(value)
        manifest_path = worker._fixture_manifest(root)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["read_cap_bytes"] = JSON_CAP
        producer_paths: dict[str, Path] = {}
        for row in manifest["cases"]:
            key = f"{row['sentinel_id']}:{row['grid_label']}"
            receipt_path = Path(row["gencase_receipt"]["path"])
            case_id = receipt_path.parent.parent.name
            attempt_id = receipt_path.parent.name
            producer_path = root / "producer-requests" / f"{key.replace(':', '_')}.json"
            producer_path.parent.mkdir(parents=True, exist_ok=True)
            producer_path.write_text(json.dumps(_fixture_request(producer_path, row["family_id"], case_id, attempt_id),
                                                indent=2, sort_keys=True) + "\n", encoding="utf-8")
            producer_paths[key] = producer_path
            producer = json.loads(producer_path.read_text(encoding="utf-8"))
            receipt = {"schema": RECEIPT_SCHEMA, "status": "completed", "returncode": 0,
                       "request": producer, "request_sha256": _sha(producer_path.read_bytes()),
                       "output_root": str(receipt_path.parent.absolute()),
                       "input_hashes_at_launch": {}, "input_hashes_after_run": {},
                       "termination": {"reason": "completed"}}
            receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            row["gencase_receipt"] = _fixture_record(receipt_path)
            row["producer_request"] = _fixture_record(producer_path)
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        source = root / "small-source.json"
        source.write_text('{"fixture":true}\n', encoding="utf-8")
        request = {"schema": REQUEST_SCHEMA,
                   "variant_schema": "ds02.stage2.three-sentinel-owner-grid-initial-support-audit.v1",
                   "read_cap_bytes": JSON_CAP,
                   "large_control_policy": "stat_only_deferred_with_owner_sha",
                   "execution_allowed": False, "gencase_launch": False, "solver_launch": False,
                   "input_files": [str(source.absolute())],
                   "input_records": {str(source.absolute()): _fixture_record(source)},
                   "input_sha256": {str(source.absolute()): _sha(source.read_bytes())},
                   "deferred_input_records": [],
                   "manifest": {"path": str(manifest_path.absolute()), "sha256": _sha(manifest_path.read_bytes())}}
        request_path = root / "support-request.json"
        request_path.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        output_path = root / "report.json"
        worker.run(manifest_path, root / "attempt", output_path)
        good = verify(manifest_path, request_path, output_path)
        assert good["schema"] == SCHEMA
        assert len(good["producer_request_identity"]) == 9
        # Changing only receipt.request_sha256 must fail; V3 must never fall
        # back to the canonical serialization accepted by the old self-test.
        bad_receipt = Path(manifest["cases"][0]["gencase_receipt"]["path"])
        value = json.loads(bad_receipt.read_text(encoding="utf-8")); value["request_sha256"] = "0" * 64
        bad_receipt.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        try:
            verify(manifest_path, request_path, output_path)
        except (VerifyFailure, V2.VerifyFailure):
            pass
        else:
            raise AssertionError("V3 accepted a runtime receipt with an incorrect request-file SHA")
        runtime_result = _runtime_v8_tiny_cpu_fixture(root)
        assert runtime_result["receipt_status"] == "completed"
        assert runtime_result["request_sha256"] == _sha(Path(runtime_result["request_path"]).read_bytes())
    print("PASS_THREE_SENTINEL_OWNER_GRID_INITIAL_SUPPORT_VERIFIER_V4_SELFTEST")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--verify", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verification-output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            self_test()
            return 0
        if args.manifest is None or args.request is None or args.output is None:
            parser.error("--verify requires --manifest, --request and --output")
        verify(args.manifest, args.request, args.output, args.verification_output)
        return 0
    except (VerifyFailure, V2.VerifyFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_THREE_SENTINEL_OWNER_GRID_INITIAL_SUPPORT_VERIFIER_V4: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
