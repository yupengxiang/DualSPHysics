#!/usr/bin/env python3
"""Independently verify a completed three-sentinel refstudy diagnostic.

This verifier is intentionally separate from the worker.  It joins the raw
request file bytes, manifest, runtime receipt, and compact worker report.  A
successful join means only that a bounded diagnostic was consumed; QI/QN/QE
remain UNKNOWN and no interpolation or neighboring-grid truth is accepted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
WORKER = HERE / "stage2_three_sentinel_refstudy_worker_v1.py"
REQUEST_BUILDER = HERE / "stage2_three_sentinel_refstudy_request_v1.py"
MANIFEST_SCHEMA = "ds02.stage2.three-sentinel.refstudy-manifest.v1"
REQUEST_SCHEMA = "ds02.request.v1"
WORKER_SCHEMA = "ds02.stage2.three-sentinel.refstudy-worker.v1"
UNKNOWN_Q = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "scientific_credit": 0}
MAX_JSON_BYTES = 10 * 1024 * 1024


class VerifyFailure(RuntimeError):
    pass


def _abs(path: str | Path) -> Path:
    return Path(path).expanduser().absolute()


def _stat(path: Path) -> dict[str, int]:
    s = path.stat()
    return {"device": int(s.st_dev), "inode": int(s.st_ino), "bytes": int(s.st_size),
            "mtime_ns": int(s.st_mtime_ns), "ctime_ns": int(s.st_ctime_ns)}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _abs(path)
    if path.is_symlink() or not path.is_file():
        raise VerifyFailure(f"{label} is not a regular non-symlink file: {path}")
    before = _stat(path)
    if before["bytes"] > MAX_JSON_BYTES:
        raise VerifyFailure(f"{label} exceeds 10 MiB: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after or len(raw) != before["bytes"]:
        raise VerifyFailure(f"{label} changed during bounded read: {path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerifyFailure(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise VerifyFailure(f"{label} must be an object")
    return value, {"path": str(path), "sha256": _sha(raw), "stat": after}


def _record_equal(record: dict[str, Any], actual: dict[str, Any], label: str) -> None:
    if not isinstance(record, dict) or record.get("path") != actual["path"]:
        raise VerifyFailure(f"{label} path is not joined")
    if str(record.get("sha256", "")).lower() != actual["sha256"]:
        raise VerifyFailure(f"{label} SHA is not joined")
    declared = record.get("stat")
    # A deferred placeholder is acceptable to the source builder, but never
    # to this post-reservation verifier.  Every consumed observer must carry
    # the concrete five-field stat join.
    if not isinstance(declared, dict):
        raise VerifyFailure(f"{label} has no concrete post-reservation stat")
    for key in ("device", "inode", "bytes", "mtime_ns", "ctime_ns"):
        if key not in declared or int(declared[key]) != int(actual["stat"][key]):
            raise VerifyFailure(f"{label} stat.{key} is not joined")


def _receipt_returncode(receipt: dict[str, Any]) -> Any:
    if "returncode" in receipt:
        return receipt["returncode"]
    execution = receipt.get("execution")
    if isinstance(execution, dict) and "returncode" in execution:
        return execution["returncode"]
    raise VerifyFailure("runtime receipt has no explicit returncode")


def _receipt_output_root(receipt: dict[str, Any]) -> Path:
    value = receipt.get("output_root")
    if value is None and isinstance(receipt.get("filesystem"), dict):
        value = receipt["filesystem"].get("output_root")
    if not isinstance(value, str) or not value:
        raise VerifyFailure("runtime receipt has no authoritative output_root")
    return _abs(value)


def verify(request_path: Path, receipt_path: Path, report_path: Path) -> dict[str, Any]:
    request, request_record = _json(request_path, "request")
    if request.get("schema") != REQUEST_SCHEMA or not str(request.get("request_variant", "")).startswith("three-sentinel-refstudy-v1"):
        raise VerifyFailure("request is not the frozen refstudy variant")
    if request.get("execution_allowed") is not True:
        raise VerifyFailure("source-prepared request was not rebound for actual parent execution")
    if request.get("solver_launch") is not False or request.get("gencase_launch") is not False:
        raise VerifyFailure("refstudy request allows a solver/GenCase launch")
    manifest_path = _abs(request.get("manifest", {}).get("path", "")) if isinstance(request.get("manifest"), dict) else None
    if manifest_path is None:
        raise VerifyFailure("request has no manifest record")
    manifest, manifest_record = _json(manifest_path, "manifest")
    _record_equal(request["manifest"], manifest_record, "request manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != "READY_FOR_PARENT_GUARDED_REFSTUDY":
        raise VerifyFailure("manifest schema/status is invalid")
    if request.get("sentinel_id") != manifest.get("sentinel_id"):
        raise VerifyFailure("request/manifest identity mismatch")
    if manifest.get("scientific_scope", {}).get("scientific_qualification") != UNKNOWN_Q:
        raise VerifyFailure("manifest grants scientific qualification")
    if manifest.get("scientific_scope", {}).get("interpolation") is not False or manifest.get("scientific_scope", {}).get("neighbor_grid_truth") is not False:
        raise VerifyFailure("manifest permits interpolation or neighbor truth")

    receipt, receipt_record = _json(receipt_path, "runtime receipt")
    status = str(receipt.get("status", "")).lower()
    if not status.startswith(("completed", "complete", "success")):
        raise VerifyFailure(f"runtime receipt is not terminal success: {receipt.get('status')!r}")
    if _receipt_returncode(receipt) not in (0, "0"):
        raise VerifyFailure("runtime receipt returncode is not zero")
    if str(receipt.get("request_sha256", "")).lower() != request_record["sha256"]:
        raise VerifyFailure("receipt request_sha256 is not the exact request file SHA")
    embedded = receipt.get("request")
    if isinstance(embedded, str) and _abs(embedded) != _abs(request_path):
        raise VerifyFailure("receipt request path differs from supplied request")
    output_root = _receipt_output_root(receipt)
    report, report_record = _json(report_path, "refstudy report")
    try:
        _abs(report_path).relative_to(output_root)
    except ValueError as exc:
        raise VerifyFailure("report is outside the receipt output_root") from exc
    if report.get("schema") != WORKER_SCHEMA or not str(report.get("status", "")).startswith("COMPLETE_REFSTUDY"):
        raise VerifyFailure("worker report is not a completed refstudy diagnostic")
    if report.get("scientific_qualification") != UNKNOWN_Q:
        raise VerifyFailure("worker report grants scientific qualification")
    if report.get("sentinel_id") != manifest.get("sentinel_id") or report.get("dimension") != manifest.get("dimension"):
        raise VerifyFailure("report identity/dimension differs from manifest")
    if report.get("manifest", {}).get("sha256") != manifest_record["sha256"]:
        raise VerifyFailure("report does not bind the exact manifest")
    if report.get("interpretation", {}).get("time_alignment") != "exact common saved times only; no interpolation":
        raise VerifyFailure("report time alignment is not the frozen exact-time policy")
    if report.get("read_scope", {}).get("production_bi4") is not False or report.get("read_scope", {}).get("production_vtk") is not False:
        raise VerifyFailure("report read scope is wider than JSON-only")

    observer_records = manifest.get("observer_records")
    guards = report.get("observer_sources")
    if not isinstance(observer_records, list) or not isinstance(guards, list) or len(observer_records) != len(guards):
        raise VerifyFailure("observer source count is not joined")
    for index, (planned, observed) in enumerate(zip(observer_records, guards)):
        _record_equal(planned, observed, f"observer {index}")
    return {"status": "VERIFIED_REFSTUDY_DIAGNOSTIC_NO_Q", "request_sha256": request_record["sha256"],
            "receipt_sha256": receipt_record["sha256"], "report_sha256": report_record["sha256"],
            "sentinel_id": manifest["sentinel_id"], "dimension": manifest["dimension"],
            "comparison_count": report.get("comparison_count"), "scientific_credit": 0}


def self_test() -> None:
    # Use the real worker to create the report; only the tiny receipt is
    # manufactured, so this test never claims a runtime or scientific result.
    import importlib.util
    spec = importlib.util.spec_from_file_location("refstudy_worker", WORKER)
    assert spec and spec.loader
    worker = importlib.util.module_from_spec(spec); spec.loader.exec_module(worker)
    with tempfile.TemporaryDirectory(prefix="three-sentinel-refstudy-verify-") as td:
        root = Path(td)
        manifest_path = worker._fixture_manifest(root / "fixture", "integration")
        report_path = root / "attempt" / "report.json"; report_path.parent.mkdir(parents=True)
        worker.run(manifest_path, report_path)
        request_path = root / "request.json"
        request = {"schema": REQUEST_SCHEMA, "request_variant": "three-sentinel-refstudy-v1-source-prepared",
                   "execution_allowed": True, "solver_launch": False, "gencase_launch": False,
                   "sentinel_id": "F3-S1", "case_id": "F3_S1_INTEGRATION_REFSTUDY_V1",
                   "manifest": {"path": str(manifest_path), "sha256": _sha(manifest_path.read_bytes()),
                                "stat": _stat(manifest_path)}}
        request_path.write_text(json.dumps(request, sort_keys=True) + "\n")
        receipt_path = root / "receipt.json"
        receipt_path.write_text(json.dumps({"status": "completed", "returncode": 0,
                                            "request_sha256": _sha(request_path.read_bytes()),
                                            "request": str(request_path), "output_root": str(report_path.parent)}) + "\n")
        value = verify(request_path, receipt_path, report_path)
        assert value["scientific_credit"] == 0
        bad = json.loads(receipt_path.read_text()); bad["request_sha256"] = "0" * 64
        receipt_path.write_text(json.dumps(bad) + "\n")
        try:
            verify(request_path, receipt_path, report_path)
        except VerifyFailure:
            pass
        else:
            raise AssertionError("tampered receipt request SHA was accepted")
    print("PASS_THREE_SENTINEL_REFSTUDY_VERIFY_V1_SELFTEST")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--request", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    if args.self_test:
        self_test(); return 0
    if not all((args.request, args.receipt, args.report)):
        parser.error("--request, --receipt and --report are required")
    try:
        print(json.dumps(verify(args.request, args.receipt, args.report), sort_keys=True))
    except (VerifyFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_THREE_SENTINEL_REFSTUDY_VERIFY_V1: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
