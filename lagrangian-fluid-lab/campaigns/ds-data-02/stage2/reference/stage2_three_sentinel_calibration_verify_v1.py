#!/usr/bin/env python3
"""Independently verify a guarded three-sentinel calibration diagnostic.

The verifier consumes only the bounded JSON report, request, manifest, and
runtime receipt.  It does not reopen generated XML, VTK, BI4, HDF5, or native
Part files.  Product integrity is accepted only from the worker's recorded
pre/decode/post guards; a row failure remains a failure and is never promoted
to a scientific pass.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any


HERE = Path(__file__).resolve().parent
SCHEMA = "ds02.stage2.three-sentinel-calibration-verifier.v1"
WORKER_NAME = "stage2_three_sentinel_calibration_worker_v1.py"
MANIFEST_SCHEMA = "ds02.stage2.three-sentinel-calibration-manifest.v1"
REQUEST_SCHEMA = "ds02.request.v1"
RECEIPT_SCHEMA = "ds02.execution-receipt.v1"
TARGETS = ("F2-S2", "F3-S1", "F5-S1")
GRIDS = ("original", "coarse", "fine")
JSON_CAP = 10 * 1024 * 1024
STAT_KEYS = ("device", "inode", "bytes", "mtime_ns", "ctime_ns")
QUALIFICATION = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "scientific_credit": 0}


class VerifyFailure(RuntimeError):
    pass


def _abs(path: Path) -> Path:
    return path.expanduser().absolute()


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {"device": int(value.st_dev), "inode": int(value.st_ino),
            "bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns),
            "ctime_ns": int(value.st_ctime_ns)}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-fA-F]{64}", value))


def _read_json(path: Path, label: str) -> tuple[Any, dict[str, Any], bytes]:
    path = _abs(path)
    if path.is_symlink() or not path.is_file():
        raise VerifyFailure(f"{label} is not a regular JSON file: {path}")
    before = _stat(path)
    if before["bytes"] > JSON_CAP:
        raise VerifyFailure(f"{label} exceeds the 10 MiB cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after or len(raw) != before["bytes"]:
        raise VerifyFailure(f"{label} changed while being read: {path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerifyFailure(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise VerifyFailure(f"{label} must be a JSON object")
    return value, {"path": str(path), "sha256": _sha(raw), "stat": after}, raw


def _stat_record(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    source = value.get("stat") or value.get("stat_pre") or value.get("stat_before") or value
    aliases = {"device": ("device", "dev", "st_dev"), "inode": ("inode", "ino", "st_ino"),
               "bytes": ("bytes", "size"), "mtime_ns": ("mtime_ns",), "ctime_ns": ("ctime_ns",)}
    result: dict[str, int] = {}
    if isinstance(source, dict):
        for target, names in aliases.items():
            for name in names:
                if name in source:
                    result[target] = int(source[name])
                    break
    return result


def _same_stat(left: Any, right: Any, label: str) -> None:
    a, b = _stat_record(left), _stat_record(right)
    if set(a) != set(STAT_KEYS) or set(b) != set(STAT_KEYS) or a != b:
        raise VerifyFailure(f"{label} does not contain equal complete pre/post stat")


def _guarded_payload(value: Any, label: str) -> None:
    if not isinstance(value, dict):
        raise VerifyFailure(f"{label} guard is missing")
    if value.get("stable") is not True or value.get("post_equal") is not True:
        raise VerifyFailure(f"{label} is not stable")
    pre = value.get("sha256_pre")
    post = value.get("sha256_post")
    if not _valid_sha(pre) or not _valid_sha(post) or pre.lower() != post.lower():
        raise VerifyFailure(f"{label} has no equal concrete pre/post SHA")
    _same_stat(value.get("stat_pre"), value.get("stat_post"), label)
    if value.get("payload_read") is not True:
        raise VerifyFailure(f"{label} does not report a guarded read")


def _check_request(request: dict[str, Any], request_path: Path, manifest: dict[str, Any]) -> None:
    if request.get("schema") != REQUEST_SCHEMA:
        raise VerifyFailure("request schema mismatch")
    if request.get("kind") != "cpu" or request.get("cpu_task_kind") != "audit":
        raise VerifyFailure("request is not an allowed CPU audit")
    sid = request.get("sentinel_id")
    if sid not in TARGETS or request.get("family_id") != sid[:2]:
        raise VerifyFailure("request sentinel/family identity mismatch")
    if request.get("scientific_qualification") != QUALIFICATION:
        raise VerifyFailure("request grants scientific qualification")
    if request.get("gencase_launch") is not False or request.get("solver_launch") is not False:
        raise VerifyFailure("request permits GenCase or solver launch")
    command = request.get("command")
    if not isinstance(command, list) or "--run" not in command or str(HERE / WORKER_NAME) not in command:
        raise VerifyFailure("request does not invoke the additive calibration worker")
    if request.get("manifest", {}).get("path") != manifest.get("_path_for_verifier"):
        # The caller adds this transient field; the worker report path is the
        # authoritative manifest join.  This branch is retained only for
        # malformed direct calls where the field is absent.
        expected = request.get("manifest", {}).get("path")
        if not isinstance(expected, str) or _abs(Path(expected)) != _abs(Path(manifest.get("_path_for_verifier", expected))):
            raise VerifyFailure("request manifest path is not bound")
    input_files = request.get("input_files")
    input_sha = request.get("input_sha256")
    if not isinstance(input_files, list) or not isinstance(input_sha, dict) or set(input_files) != set(input_sha):
        raise VerifyFailure("request static input closure is incomplete")
    for path in input_files:
        if Path(path).suffix.lower() in {".bi4", ".vtk", ".vtu", ".h5", ".hdf5", ".part", ".hdf"}:
            raise VerifyFailure(f"payload was placed in static input_files: {path}")
    if request.get("deferred_input_records") is None:
        raise VerifyFailure("request has no deferred product records")
    scale = request.get("calibration_scales")
    if not isinstance(scale, dict) or not _valid_sha(scale.get("sha256")):
        raise VerifyFailure("request does not bind the frozen calibration scales")


def verify(*, manifest_path: Path, request_path: Path, receipt_path: Path, report_path: Path) -> dict[str, Any]:
    manifest, manifest_guard, _ = _read_json(manifest_path, "calibration manifest")
    request, request_guard, request_raw = _read_json(request_path, "calibration request")
    receipt, receipt_guard, _ = _read_json(receipt_path, "runtime receipt")
    # Transient path is not written to any artifact; it makes the exact path
    # comparison above explicit without trusting a basename.
    manifest_for_check = dict(manifest, _path_for_verifier=str(_abs(manifest_path)))
    _check_request(request, _abs(request_path), manifest_for_check)
    if request.get("manifest", {}).get("path") != str(_abs(manifest_path)):
        raise VerifyFailure("request manifest path differs from supplied manifest")
    if request.get("manifest", {}).get("sha256") != manifest_guard["sha256"]:
        raise VerifyFailure("request manifest SHA differs from supplied manifest")
    if receipt.get("schema") != RECEIPT_SCHEMA or receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise VerifyFailure("runtime receipt is not a successful completed CPU audit")
    if receipt.get("request") != request:
        raise VerifyFailure("receipt request object differs from request file")
    if receipt.get("request_sha256") != _sha(request_raw):
        raise VerifyFailure("receipt request SHA is not the exact request-file SHA")
    if receipt.get("family_id") is not None and receipt.get("family_id") != request.get("family_id"):
        raise VerifyFailure("receipt family identity differs")
    output_root = receipt.get("output_root")
    if not isinstance(output_root, str) or not str(_abs(report_path)).startswith(str(_abs(Path(output_root))) + "/"):
        raise VerifyFailure("report is outside the runtime receipt output root")
    launch_hashes = receipt.get("input_hashes_at_launch")
    after_hashes = receipt.get("input_hashes_after_run")
    if not isinstance(launch_hashes, dict) or launch_hashes != after_hashes:
        raise VerifyFailure("runtime static input hashes changed")
    if launch_hashes != request.get("input_sha256"):
        raise VerifyFailure("receipt static input hashes differ from request")
    report, report_guard, _ = _read_json(report_path, "calibration worker report")
    if report.get("schema") != "ds02.stage2.three-sentinel-calibration-worker.v1":
        raise VerifyFailure("worker report schema mismatch")
    if not str(report.get("status", "")).startswith("COMPLETE_PARTIAL_THREE_SENTINEL_CALIBRATION_DIAGNOSTIC"):
        raise VerifyFailure("worker report is not a completed partial diagnostic")
    sid = request["sentinel_id"]
    if report.get("sentinel_id") != sid or report.get("scientific_qualification") != QUALIFICATION:
        raise VerifyFailure("worker report sentinel/qualification mismatch")
    if report.get("manifest", {}).get("path") != str(_abs(manifest_path)) or report.get("manifest", {}).get("sha256") != manifest_guard["sha256"]:
        raise VerifyFailure("worker report manifest guard is not joined to request")
    scale = report.get("calibration_scales")
    if not isinstance(scale, dict) or scale.get("record", {}).get("path") != request["calibration_scales"]["path"] or scale.get("record", {}).get("sha256") != request["calibration_scales"]["sha256"]:
        raise VerifyFailure("worker report calibration scale registry is not joined")
    rows = report.get("grid_rows")
    if not isinstance(rows, list) or {f"{r.get('sentinel_id')}:{r.get('grid_label')}" for r in rows if isinstance(r, dict)} != {f"{sid}:{grid}" for grid in GRIDS}:
        raise VerifyFailure("worker report does not contain exactly original/coarse/fine rows")
    for row in rows:
        if not isinstance(row, dict) or row.get("scientific_qualification") != QUALIFICATION:
            raise VerifyFailure("row qualification is not explicitly unknown")
        dimension = report.get("dimension_status") or {}
        if dimension.get("spatial", {}).get("status") != "SUPPORT_ONLY_NO_CROSS_GRID_TRUTH":
            raise VerifyFailure("spatial dimension is not support-only")
        if dimension.get("integration", {}).get("status") != "NOT_IN_THIS_PARENT" or dimension.get("output_sampling", {}).get("status") != "NOT_IN_THIS_PARENT":
            raise VerifyFailure("integration/output dimension was promoted")
        status = str(row.get("status", ""))
        if status.startswith("FAILED_"):
            if not row.get("reason"):
                raise VerifyFailure("failed row has no preserved reason")
            continue
        if not status.startswith("PASS_"):
            raise VerifyFailure(f"row has unknown status: {status}")
        for role in ("fluid_vtk", "bound_vtk", "native_bi4"):
            _guarded_payload((row.get("deferred_payload_guards") or {}).get(role), f"{row.get('row_key')} {role}")
        admission = row.get("admission") or {}
        if admission.get("mass_rescale") is not False:
            raise VerifyFailure("row permits XML mass fallback or rescaling")
        native = row.get("native_header") or {}
        if native.get("xml_mass_is_not_native") is not True:
            raise VerifyFailure("row does not explicitly reject XML mass fallback")
        if str(native.get("status", "")).startswith("PASS"):
            if native.get("xml_mass_is_not_native") is not True:
                raise VerifyFailure("native header row falls back to XML mass")
    result = {
        "schema": SCHEMA,
        "status": "VERIFIED_CALIBRATION_DIAGNOSTIC_NO_Q",
        "sentinel_id": sid,
        "request": request_guard,
        "receipt": receipt_guard,
        "manifest": manifest_guard,
        "report": report_guard,
        "row_count": len(rows),
        "scientific_qualification": copy.deepcopy(QUALIFICATION),
        "scope": {
            "spatial": "support-only/no-neighbor-truth",
            "integration": "not-in-this-parent",
            "output_sampling": "not-in-this-parent",
            "native_mass": "native-header-only; XML fallback forbidden",
        },
    }
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--verification-output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = verify(manifest_path=args.manifest, request_path=args.request,
                        receipt_path=args.receipt, report_path=args.report)
    except (VerifyFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_THREE_SENTINEL_CALIBRATION_VERIFY_V1: {exc}", file=sys.stderr)
        return 2
    if args.verification_output:
        out = _abs(args.verification_output)
        if out.exists() or out.is_symlink():
            raise SystemExit(f"refusing to overwrite verification output: {out}")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "sentinel_id": result["sentinel_id"], "scientific_credit": 0}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
