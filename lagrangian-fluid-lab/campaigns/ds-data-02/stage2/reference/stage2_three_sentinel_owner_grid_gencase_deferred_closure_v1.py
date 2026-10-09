#!/usr/bin/env python3
"""Audit the source-prepared GenCase deferred-input boundary.

The V2 GenCase requests intentionally keep large controls outside the
source-prepared runtime ``input_files`` set because the parent has not yet
reserved a destination namespace.  Runtime-v8 does not consume a custom
``deferred_input_files`` field.  This sidecar therefore makes the boundary
explicit: a parent normalizer must add every deferred control to the actual
post-reservation input closure and establish its full pre/post digest before
GenCase is admitted.

This module reads only the nine small V2 request/manifest JSON files and their
stat metadata.  It never opens the deferred control, generated products, BI4,
VTK, HDF5, or solver output.  It does not create or launch a runtime job.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
DEFAULT_PACKAGE = HERE.parent / "requests" / "three-sentinel-owner-grid-gencase-producer-v2-prepared-001"
SCHEMA = "ds02.stage2.three-sentinel.owner-grid-gencase-deferred-closure.v1"
REQUEST_SCHEMA = "ds02.request.v1"
JSON_CAP = 10 * 1024 * 1024
TARGETS = ("F2-S2", "F3-S1", "F5-S1")
GRIDS = ("original", "coarse", "fine")


class ClosureFailure(RuntimeError):
    pass


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {"device": int(value.st_dev), "inode": int(value.st_ino),
            "bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns),
            "ctime_ns": int(value.st_ctime_ns)}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file():
        raise ClosureFailure(f"{label} is not a regular JSON file: {path}")
    before = _stat(path)
    if before["bytes"] > JSON_CAP:
        raise ClosureFailure(f"{label} exceeds the 10 MiB metadata cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after or len(raw) != before["bytes"]:
        raise ClosureFailure(f"{label} changed during read: {path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ClosureFailure(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ClosureFailure(f"{label} must be a JSON object")
    return value, {"path": str(path), "sha256": _sha(raw), "stat": after}


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-fA-F]{64}", value))


def _audit_request(path: Path) -> dict[str, Any]:
    request, request_record = _json(path, f"request {path.name}")
    if request.get("schema") != REQUEST_SCHEMA:
        raise ClosureFailure(f"{path.name} request schema mismatch")
    if request.get("request_variant") != "three-sentinel-owner-grid-gencase-producer-v2":
        raise ClosureFailure(f"{path.name} is not the V2 producer request")
    static = request.get("input_files")
    static_records = request.get("input_records")
    digests = request.get("input_sha256")
    deferred = request.get("deferred_input_records")
    if not isinstance(static, list) or not isinstance(static_records, dict) or not isinstance(digests, dict):
        raise ClosureFailure(f"{path.name} lacks static input closure maps")
    if set(static) != set(static_records) or set(static) != set(digests):
        raise ClosureFailure(f"{path.name} static closure maps do not have exact keys")
    if not isinstance(deferred, list):
        raise ClosureFailure(f"{path.name} has no deferred_input_records list")
    static_paths = set(static)
    rows: list[dict[str, Any]] = []
    for item in deferred:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise ClosureFailure(f"{path.name} has malformed deferred record")
        source = str(item["path"])
        if source in static_paths:
            raise ClosureFailure(f"{path.name} deferred input also appears in input_files: {source}")
        stat = item.get("stat_before") or item.get("stat") or {}
        bytes_value = int(item.get("bytes") or stat.get("bytes") or 0)
        declared = item.get("sha256")
        if bytes_value > JSON_CAP and not _valid_sha(declared):
            raise ClosureFailure(f"{path.name} large deferred input lacks owner SHA: {source}")
        rows.append({"path": source, "bytes": bytes_value, "sha256": declared,
                     "role": item.get("role"), "row_key": item.get("row_key"),
                     "stat": stat})
    return {
        "request": {"path": request_record["path"], "sha256": request_record["sha256"], "stat": request_record["stat"]},
        "sentinel_id": request.get("sentinel_id"), "grid_label": request.get("grid_label"),
        "family_id": request.get("family_id"), "case_id": request.get("case_id"),
        "attempt_id": request.get("attempt_id"), "static_input_count": len(static),
        "deferred_inputs": rows,
        "deferred_input_paths_excluded_from_static": all(row["path"] not in static_paths for row in rows),
        "runtime_rebind_required": bool(rows),
        "runtime_v8_consumes_custom_deferred_field": False,
        "parent_after_reservation_prepost_full_hash_required": bool(rows),
    }


def audit(package: Path, output: Path) -> dict[str, Any]:
    package = package.expanduser().absolute()
    manifest_path = package / "owner-grid-gencase-producer-manifest-v2.json"
    manifest, manifest_record = _json(manifest_path, "producer V2 manifest")
    if manifest.get("schema") != "ds02.stage2.three-sentinel.owner-grid-gencase-producer-manifest.v2":
        raise ClosureFailure("producer manifest schema mismatch")
    paths = sorted((package / "requests").glob("*-owner-grid-gencase-v2-request.json"))
    if len(paths) != 9:
        raise ClosureFailure(f"expected 9 V2 producer requests, found {len(paths)}")
    rows = [_audit_request(path) for path in paths]
    forcing = [item for row in rows for item in row["deferred_inputs"]
               if str(item.get("path", "")).lower().endswith(".csv")]
    result = {
        "schema": SCHEMA,
        "status": "SOURCE_PREPARED_DEFERRED_BOUNDARY_REQUIRES_PARENT_RUNTIME_REBIND",
        "producer_manifest": manifest_record,
        "requests": rows,
        "deferred_control_summary": {
            "large_control_count": len(forcing),
            "paths": sorted({str(item["path"]) for item in forcing}),
            "all_large_controls_have_owner_sha": all(_valid_sha(item.get("sha256")) for item in forcing),
        },
        "parent_contract": {
            "runtime_v8_custom_deferred_fields_are_not_consumed": True,
            "normalizer_must_add_deferred_controls_to_actual_input_files": True,
            "normalizer_must_reserve_then_hash_pre_and_post": True,
            "normalizer_must_rebind_input_sha256_to_actual_parent_request": True,
            "source_prepared_request_is_not_launch_ready": True,
            "relative_control_paths": {
                "status": "PARENT_STAGING_REQUIRED",
                "rule": "stage the candidate Def and every relative motion/forcing dependency under the attempt-contained input namespace, or bind an exact immutable absolute source; no fallback path search",
                "cwd": "GenCase command cwd and staged XML directory must be recorded in the parent request",
            },
        },
        "read_scope": {"json_cap_bytes": JSON_CAP, "deferred_payload_bytes_read": False,
                        "solver_launch": False, "gencase_launch": False, "scientific_credit": 0},
    }
    output = output.expanduser().absolute()
    if output.exists() or output.is_symlink():
        raise ClosureFailure(f"refusing overwrite: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def _self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="owner-grid-deferred-closure-") as value:
        root = Path(value)
        request = root / "request.json"
        large = root / "control.csv"
        large.write_bytes(b"x" * (JSON_CAP + 1))
        digest = _sha(large.read_bytes())
        request.write_text(json.dumps({
            "schema": REQUEST_SCHEMA,
            "request_variant": "three-sentinel-owner-grid-gencase-producer-v2",
            "sentinel_id": "F3-S1", "grid_label": "coarse", "family_id": "F3",
            "case_id": "F3_CASE", "attempt_id": "f3-attempt",
            "input_files": [], "input_records": {}, "input_sha256": {},
            "deferred_input_records": [{"path": str(large), "bytes": large.stat().st_size,
                                         "sha256": digest, "read_mode": "stat_only_deferred_over_10MiB"}],
        }, indent=2), encoding="utf-8")
        row = _audit_request(request)
        assert row["runtime_rebind_required"] is True
        assert row["deferred_input_paths_excluded_from_static"] is True
        broken = json.loads(request.read_text())
        broken["input_files"] = [str(large)]
        broken["input_records"] = {str(large): {"sha256": digest}}
        broken["input_sha256"] = {str(large): digest}
        request.write_text(json.dumps(broken), encoding="utf-8")
        try:
            _audit_request(request)
        except ClosureFailure:
            pass
        else:
            raise AssertionError("deferred input was accepted in static input_files")
    print("PASS_THREE_SENTINEL_OWNER_GRID_DEFERRED_CLOSURE_SELFTEST")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--audit", action="store_true")
    parser.add_argument("--package", type=Path, default=DEFAULT_PACKAGE)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.self_test:
        try:
            _self_test()
        except Exception as exc:
            print(f"FAILED_THREE_SENTINEL_OWNER_GRID_DEFERRED_CLOSURE_SELFTEST: {exc}", file=sys.stderr)
            return 2
        return 0
    if args.output is None:
        parser.error("--audit requires --output")
    try:
        result = audit(args.package, args.output)
    except (ClosureFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_THREE_SENTINEL_OWNER_GRID_DEFERRED_CLOSURE: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": result["status"], "requests": len(result["requests"]),
                      "large_controls": result["deferred_control_summary"]["large_control_count"],
                      "scientific_credit": 0}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
