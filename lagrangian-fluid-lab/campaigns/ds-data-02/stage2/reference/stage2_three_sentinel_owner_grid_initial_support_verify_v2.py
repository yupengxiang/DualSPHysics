#!/usr/bin/env python3
"""Strict metadata verifier for the owner-grid initial-support contract.

This is additive to the frozen V1 verifier.  It keeps the V1 manifest and
worker report schema, but validates the V2 request closure before delegating
the row/VTK/BI4 diagnostic checks to V1.  Every JSON source consumed here is
capped at 10 MiB, and every GenCase receipt must be a concrete
``ds02.execution-receipt.v1`` object whose request identity, request digest,
output root, terminal code, and worker guard agree with the exact receipt path.

The self-test runs the actual frozen worker and verifier against a tiny
manufactured fixture whose receipts have the runtime-v8 shape.  It also runs a
non-zero terminal receipt through the same worker, preserving one FAILED row.
No production payload or native file is read by this module.
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
from typing import Any


HERE = Path(__file__).resolve().parent
V1_PATH = HERE / "stage2_three_sentinel_owner_grid_initial_support_verify_v1.py"
WORKER_PATH = HERE / "stage2_three_sentinel_owner_grid_initial_support_audit_v1.py"
SCHEMA = "ds02.stage2.three-sentinel-owner-grid-initial-support-verifier.v2"
MANIFEST_SCHEMA = "ds02.stage2.three-sentinel-owner-grid-initial-support-manifest.v1"
REQUEST_SCHEMA = "ds02.request.v1"
RECEIPT_SCHEMA = "ds02.execution-receipt.v1"
TARGETS = ("F2-S2", "F3-S1", "F5-S1")
GRIDS = ("original", "coarse", "fine")
ROW_KEYS = tuple(f"{sid}:{grid}" for sid in TARGETS for grid in GRIDS)
STAT_FIELDS = ("device", "inode", "bytes", "mtime_ns", "ctime_ns")
JSON_CAP = 10 * 1024 * 1024
UNKNOWN = "UNKNOWN"
QUALIFICATION = {"QI": UNKNOWN, "QN": UNKNOWN, "QE": UNKNOWN, "scientific_credit": 0}


class VerifyFailure(RuntimeError):
    pass


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise VerifyFailure(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _absolute(value: Path) -> Path:
    return value.expanduser().absolute()


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {"device": int(value.st_dev), "inode": int(value.st_ino),
            "bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns),
            "ctime_ns": int(value.st_ctime_ns)}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-fA-F]{64}", value))


def _json(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _absolute(path)
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
        raise VerifyFailure(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise VerifyFailure(f"{label} must be a JSON object")
    return value, {"path": str(path), "sha256": _sha(raw), "stat": after}


def _record_path(value: Any, label: str) -> Path:
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        raise VerifyFailure(f"{label} record has no path")
    return _absolute(Path(value["path"]))


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


def _check_current_stat(path: Path, expected: dict[str, int], label: str) -> None:
    if not path.is_file() or path.is_symlink():
        raise VerifyFailure(f"{label} is not a regular file")
    actual = _stat(path)
    for key, value in expected.items():
        if actual[key] != value:
            raise VerifyFailure(f"{label} current {key} differs from request")


def _check_request_closure(request: dict[str, Any], request_path: Path,
                           manifest: dict[str, Any], manifest_path: Path) -> dict[str, Any]:
    if request.get("schema") != REQUEST_SCHEMA:
        raise VerifyFailure("initial-support request schema mismatch")
    if request.get("variant_schema") != "ds02.stage2.three-sentinel-owner-grid-initial-support-audit.v1":
        raise VerifyFailure("initial-support request worker schema mismatch")
    if request.get("read_cap_bytes") != JSON_CAP:
        raise VerifyFailure("request does not declare the strict 10 MiB JSON/source cap")
    if request.get("large_control_policy") != "stat_only_deferred_with_owner_sha":
        raise VerifyFailure("request does not preserve the large-control deferred policy")
    if request.get("execution_allowed") is not False or request.get("solver_launch") is not False:
        raise VerifyFailure("source-prepared request permits execution")
    input_files = request.get("input_files")
    input_records = request.get("input_records")
    input_sha = request.get("input_sha256")
    if not isinstance(input_files, list) or len(input_files) != len(set(input_files)):
        raise VerifyFailure("request input_files is not a unique list")
    if not isinstance(input_records, dict) or set(input_records) != set(input_files):
        raise VerifyFailure("input_records is not exactly the static input_files set")
    if not isinstance(input_sha, dict) or set(input_sha) != set(input_files):
        raise VerifyFailure("input_sha256 is not exactly keyed by input_files")
    for path_text in input_files:
        record = input_records[path_text]
        path = _record_path(record, f"static input {path_text}")
        if str(path) != str(_absolute(Path(path_text))):
            raise VerifyFailure(f"static input path normalization changed: {path_text}")
        if not _valid_sha(input_sha[path_text]) or not _valid_sha(record.get("sha256")):
            raise VerifyFailure(f"static input {path_text} lacks a concrete SHA")
        if input_sha[path_text].lower() != str(record["sha256"]).lower():
            raise VerifyFailure(f"static input {path_text} digest map disagrees with record")
        _check_current_stat(path, _record_stat(record), f"static input {path_text}")
    deferred = request.get("deferred_input_records")
    if not isinstance(deferred, list):
        raise VerifyFailure("request deferred_input_records is not a list")
    static_paths = set(input_files)
    deferred_paths: set[str] = set()
    deferred_signatures: dict[str, tuple[Any, ...]] = {}
    for index, record in enumerate(deferred):
        path = _record_path(record, f"deferred input {index}")
        key = str(path)
        signature = (
            record.get("sha256"),
            json.dumps(_record_stat(record), sort_keys=True),
            record.get("read_mode"),
            record.get("hash_status"),
        )
        # One immutable forcing source may be referenced by several grid rows.
        # Repeated paths are valid only when every source-integrity field is
        # identical; row_key/role are deliberately excluded from the
        # signature because they describe the consumer, not the source.
        if key in deferred_signatures and deferred_signatures[key] != signature:
            raise VerifyFailure(f"deferred input has conflicting repeated records: {key}")
        deferred_signatures.setdefault(key, signature)
        deferred_paths.add(key)
        if key in static_paths:
            raise VerifyFailure(f"deferred input is incorrectly in static input_files: {key}")
        declared = record.get("sha256")
        if record.get("read_mode") == "stat_only_deferred_over_10MiB" and not _valid_sha(declared):
            raise VerifyFailure(f"large deferred input lacks owner SHA: {key}")
        if path.exists():
            _check_current_stat(path, _record_stat(record), f"deferred input {key}")
    manifest_record = request.get("manifest")
    manifest_ref = _record_path(manifest_record, "request manifest")
    if manifest_ref != _absolute(manifest_path):
        raise VerifyFailure("request manifest path does not bind the supplied manifest")
    if not _valid_sha(manifest_record.get("sha256")):
        raise VerifyFailure("request manifest record has no concrete SHA")
    actual_manifest_sha = _sha(manifest_path.read_bytes())
    if actual_manifest_sha != str(manifest_record["sha256"]).lower():
        raise VerifyFailure("request manifest SHA does not match supplied manifest bytes")
    if manifest.get("read_cap_bytes") != JSON_CAP:
        raise VerifyFailure("manifest does not declare the strict 10 MiB cap")
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise VerifyFailure("manifest schema mismatch")
    return {"static_count": len(input_files), "deferred_count": len(deferred),
            "manifest_sha256": actual_manifest_sha}


def _receipt_identity(receipt_path: Path, case: dict[str, Any], receipt: dict[str, Any]) -> dict[str, str]:
    if receipt.get("schema") != RECEIPT_SCHEMA:
        raise VerifyFailure(f"{receipt_path} receipt schema is not {RECEIPT_SCHEMA}")
    output_root = _absolute(receipt_path.parent)
    if receipt.get("output_root") != str(output_root):
        raise VerifyFailure(f"{receipt_path} receipt output_root does not equal its parent")
    request = receipt.get("request")
    if not isinstance(request, dict):
        raise VerifyFailure(f"{receipt_path} runtime receipt has no request object")
    request_sha = receipt.get("request_sha256")
    canonical = json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if not _valid_sha(request_sha) or str(request_sha).lower() != _sha(canonical):
        raise VerifyFailure(f"{receipt_path} request_sha256 does not bind request bytes")
    # The producer's output contract is families/<family>/<case>/<attempt>.
    # Deriving case/attempt from the actual receipt path prevents a label-only
    # physical_case_id from silently standing in for the runtime identity.
    expected_case = output_root.parent.name
    expected_attempt = output_root.name
    if request.get("case_id") != expected_case or request.get("attempt_id") != expected_attempt:
        raise VerifyFailure(f"{receipt_path} request case/attempt does not bind output path")
    expected_family = str(case.get("family_id"))
    if request.get("family_id") != expected_family:
        raise VerifyFailure(f"{receipt_path} request family does not bind manifest case")
    if request.get("kind") not in {"cpu", "generic-cpu-audit"}:
        raise VerifyFailure(f"{receipt_path} request kind is not a CPU task")
    status = receipt.get("status")
    try:
        returncode = int(receipt.get("returncode"))
    except (TypeError, ValueError) as exc:
        raise VerifyFailure(f"{receipt_path} receipt returncode is not an integer") from exc
    if status == "completed" and returncode != 0:
        raise VerifyFailure(f"{receipt_path} completed receipt has non-zero returncode")
    if status != "completed" and returncode == 0:
        raise VerifyFailure(f"{receipt_path} non-completed receipt has zero returncode")
    for field in ("input_hashes_at_launch", "input_hashes_after_run"):
        if not isinstance(receipt.get(field), dict):
            raise VerifyFailure(f"{receipt_path} runtime receipt lacks {field}")
    return {"family_id": expected_family, "case_id": expected_case, "attempt_id": expected_attempt,
            "status": str(status), "returncode": str(returncode)}


def _check_receipts(manifest: dict[str, Any], output: dict[str, Any]) -> dict[str, Any]:
    rows = output.get("cases")
    if not isinstance(rows, list):
        raise VerifyFailure("worker report has no cases")
    by_key = {str(row.get("row_key")): row for row in rows if isinstance(row, dict)}
    if set(by_key) != set(ROW_KEYS):
        raise VerifyFailure("worker report rows do not match the nine manifest rows")
    manifest_rows = {f"{row['sentinel_id']}:{row['grid_label']}": row
                     for row in manifest.get("cases", []) if isinstance(row, dict)}
    if set(manifest_rows) != set(ROW_KEYS):
        raise VerifyFailure("manifest rows do not match the nine expected rows")
    receipt_results: dict[str, Any] = {}
    for key in ROW_KEYS:
        case = manifest_rows[key]
        receipt_path = _record_path(case.get("gencase_receipt"), f"{key} GenCase receipt")
        receipt, receipt_record = _json(receipt_path, f"{key} runtime receipt")
        identity = _receipt_identity(receipt_path, case, receipt)
        report_row = by_key[key]
        report_status = str(report_row.get("status", ""))
        if identity["status"] == "completed" and not report_status.startswith("FAILED"):
            guard = (report_row.get("source_identity") or {}).get("gencase_receipt")
            if not isinstance(guard, dict):
                raise VerifyFailure(f"{key} report has no receipt guard")
            if guard.get("path") != receipt_record["path"]:
                raise VerifyFailure(f"{key} report receipt guard path mismatch")
            if guard.get("sha256_pre") != receipt_record["sha256"] or guard.get("sha256_post") != receipt_record["sha256"]:
                raise VerifyFailure(f"{key} report receipt guard SHA does not bind runtime receipt")
            if guard.get("stat_pre") != guard.get("stat_post"):
                raise VerifyFailure(f"{key} report receipt guard stat changed")
            if _record_stat(guard) and _record_stat(guard) != receipt_record["stat"]:
                raise VerifyFailure(f"{key} report receipt guard stat does not bind runtime receipt")
        elif identity["status"] != "completed" and not report_status.startswith("FAILED"):
            raise VerifyFailure(f"{key} nonzero runtime receipt was not retained as FAILED")
        receipt_results[key] = {"receipt": receipt_record, "identity": identity,
                                "worker_status": report_status}
    return receipt_results


def verify(manifest_path: Path, request_path: Path, output_path: Path,
           verification_output: Path | None = None) -> dict[str, Any]:
    manifest, manifest_record = _json(manifest_path, "owner-grid support manifest")
    request, request_record = _json(request_path, "owner-grid support request")
    output, output_record = _json(output_path, "owner-grid support worker report")
    closure = _check_request_closure(request, request_path, manifest, manifest_path)
    v1 = _load(V1_PATH, "owner_grid_support_verifier_v1_for_v2")
    # V1 remains the row-level diagnostic verifier.  All its JSON inputs have
    # already passed the stricter 10 MiB gate above.
    v1_result = v1.verify(manifest_path, output_path)
    receipts = _check_receipts(manifest, output)
    result = {
        "schema": SCHEMA,
        "status": "VERIFIED_THREE_SENTINEL_OWNER_GRID_INITIAL_SUPPORT_V2",
        "manifest": manifest_record,
        "request": request_record,
        "worker_output": output_record,
        "request_closure": closure,
        "case_counts": output.get("case_counts"),
        "receipt_identity": receipts,
        "v1_verifier_status": v1_result.get("status"),
        "scientific_qualification": QUALIFICATION,
        "read_scope": {"json_cap_bytes": JSON_CAP, "vtk_bytes_read_by_verifier": False,
                        "bi4_bytes_read_by_verifier": False, "hdf5_read": False,
                        "solver_launch": False, "gencase_launch": False},
    }
    if verification_output is not None:
        path = _absolute(verification_output)
        if path.exists() or path.is_symlink():
            raise VerifyFailure(f"refusing overwrite: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def _receipt_for_fixture(path: Path, family: str, case_id: str, attempt_id: str,
                         returncode: int = 0) -> dict[str, Any]:
    request = {"schema": REQUEST_SCHEMA, "family_id": family, "case_id": case_id,
               "attempt_id": attempt_id, "kind": "cpu", "cpu_task_kind": "gencase"}
    request_sha = _sha(json.dumps(request, sort_keys=True, separators=(",", ":")).encode())
    return {"schema": RECEIPT_SCHEMA, "status": "completed" if returncode == 0 else "failed",
            "returncode": returncode, "request": request, "request_sha256": request_sha,
            "output_root": str(path.parent.absolute()), "input_hashes_at_launch": {},
            "input_hashes_after_run": {}, "termination": {"reason": "completed" if returncode == 0 else "child_nonzero"}}


def _fixture_record(path: Path) -> dict[str, Any]:
    return {"path": str(path.absolute()), "sha256": _sha(path.read_bytes()), "stat": _stat(path),
            "hash_status": "BOUND_RUNTIME_FIXTURE", "payload_read_by_builder": False}


def _runtime_fixture_manifest(worker: Any, root: Path, failed_key: str | None = None) -> Path:
    manifest_path = worker._fixture_manifest(root)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["read_cap_bytes"] = JSON_CAP
    manifest["builder_provenance_v2"] = {"cap_bytes": JSON_CAP,
                                          "large_control_policy": "stat_only_deferred_with_owner_sha"}
    for row in manifest["cases"]:
        key = f"{row['sentinel_id']}:{row['grid_label']}"
        path = Path(row["gencase_receipt"]["path"])
        case_id, attempt_id = path.parent.parent.name, path.parent.name
        path.write_text(json.dumps(_receipt_for_fixture(path, row["family_id"], case_id,
                                                        attempt_id, int(key == failed_key)),
                                   indent=2, sort_keys=True) + "\n", encoding="utf-8")
        row["gencase_receipt"] = _fixture_record(path)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path


def self_test() -> None:
    worker = _load(WORKER_PATH, "owner_grid_support_worker_v2_fixture")
    with tempfile.TemporaryDirectory(prefix="owner-grid-support-verifier-v2-") as value:
        root = Path(value)
        manifest_path = _runtime_fixture_manifest(worker, root)
        request = {
            "schema": REQUEST_SCHEMA,
            "variant_schema": "ds02.stage2.three-sentinel-owner-grid-initial-support-audit.v1",
            "read_cap_bytes": JSON_CAP,
            "large_control_policy": "stat_only_deferred_with_owner_sha",
            "execution_allowed": False, "solver_launch": False,
            "input_files": [], "input_records": {}, "input_sha256": {},
            "deferred_input_records": [],
            "manifest": {"path": str(manifest_path.absolute()), "sha256": _sha(manifest_path.read_bytes())},
        }
        # The real worker fixture is intentionally reused only for the report;
        # this request is a tiny source-closure fixture for the V2 contract.
        source = root / "small-source.json"
        source.write_text('{"fixture":true}\n', encoding="utf-8")
        source_record = _fixture_record(source)
        request["input_files"] = [source_record["path"]]
        request["input_records"] = {source_record["path"]: source_record}
        request["input_sha256"] = {source_record["path"]: source_record["sha256"]}
        request_path = root / "request.json"
        request_path.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        output_path = root / "positive-report.json"
        worker.run(manifest_path, root / "positive-attempt", output_path)
        result = verify(manifest_path, request_path, output_path)
        assert result["case_counts"] == {"PASS_OR_DIAGNOSTIC": 9, "FAILED": 0}

        negative_manifest_path = _runtime_fixture_manifest(worker, root / "negative", "F2-S2:original")
        negative_request = copy.deepcopy(request)
        negative_request["manifest"] = {"path": str(negative_manifest_path.absolute()),
                                         "sha256": _sha(negative_manifest_path.read_bytes())}
        negative_request_path = root / "negative-request.json"
        negative_request_path.write_text(json.dumps(negative_request, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        negative_output = root / "negative-report.json"
        worker.run(negative_manifest_path, root / "negative-attempt", negative_output)
        negative = verify(negative_manifest_path, negative_request_path, negative_output)
        assert negative["case_counts"] == {"PASS_OR_DIAGNOSTIC": 8, "FAILED": 1}

        oversized = root / "oversized.json"
        oversized.write_bytes(b"{" + b"x" * JSON_CAP + b"}")
        try:
            _json(oversized, "oversized fixture")
        except VerifyFailure:
            pass
        else:
            raise AssertionError("JSON over the 10 MiB cap was accepted")
    print("PASS_THREE_SENTINEL_OWNER_GRID_INITIAL_SUPPORT_VERIFIER_V2_SELFTEST")


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
    if args.self_test:
        try:
            self_test()
        except Exception as exc:
            print(f"FAILED_THREE_SENTINEL_OWNER_GRID_INITIAL_SUPPORT_VERIFIER_V2_SELFTEST: {exc}", file=sys.stderr)
            return 2
        return 0
    if args.manifest is None or args.request is None or args.output is None:
        parser.error("--verify requires --manifest, --request and --output")
    try:
        result = verify(args.manifest, args.request, args.output, args.verification_output)
    except (VerifyFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_THREE_SENTINEL_OWNER_GRID_INITIAL_SUPPORT_VERIFIER_V2: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": result["status"], "case_counts": result["case_counts"],
                      "scientific_credit": 0}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
