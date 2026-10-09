#!/usr/bin/env python3
"""Build the owner-grid initial-support manifest with a strict 10 MiB cap.

This is an additive wrapper around the frozen V1 builder and worker contract.
The V1 worker still receives its original manifest schema and status, but this
builder treats *every* source larger than 10 MiB as a parent-deferred input,
regardless of suffix.  In particular, the 14.9 MiB F3 forcing CSV is never
opened here: the owner-declared SHA and complete current stat are carried into
the parent request for an after-reservation read.  Small XML/JSON metadata is
handled by the V1 builder and all generated products remain deferred.

No GenCase, solver, native, VTK, BI4, HDF5, or production payload is read or
started by this module.  The V1 worker is intentionally not modified.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import tempfile
from typing import Any

HERE = Path(__file__).resolve().parent
V1_PATH = HERE / "stage2_three_sentinel_owner_grid_initial_support_request_v1.py"
SPEC = importlib.util.spec_from_file_location("stage2_owner_grid_initial_support_v1_frozen", V1_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load frozen V1 builder: {V1_PATH}")
V1 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(V1)

SCHEMA = V1.SCHEMA
REQUEST_SCHEMA = V1.REQUEST_SCHEMA
WORKER_SCHEMA = V1.WORKER_SCHEMA
SMALL_CAP = 10 * 1024 * 1024


class BuildFailure(RuntimeError):
    pass


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-fA-F]{64}", value))


def _strict_record_from_owner(value: Any, label: str, *, allow_deferred: bool = False) -> dict[str, Any]:
    """V1-shaped record with a 10 MiB all-suffix deferred boundary."""
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        raise BuildFailure(f"{label} record lacks path")
    path = V1._absolute(Path(value["path"]))
    path = V1._regular(path, label)
    before = V1._stat(path)
    declared = value.get("sha256")
    if before["bytes"] > SMALL_CAP:
        if not allow_deferred:
            raise BuildFailure(f"{label} exceeds the 10 MiB source cap: {path}")
        if not _valid_sha(declared):
            raise BuildFailure(f"{label} is deferred but has no owner-declared SHA: {path}")
        return {
            "path": str(path),
            "sha256": str(declared).lower(),
            "stat": before,
            "hash_status": "DECLARED_OWNER_V3_SHA_PARENT_REVERIFY_REQUIRED",
            "payload_read_by_builder": False,
            "scope": "deferred_parent_control_source",
            "read_mode": "stat_only_deferred_over_10MiB",
            "builder_cap_bytes": SMALL_CAP,
        }
    # Preserve V1's fields/status for worker compatibility and add explicit
    # V2 cap provenance (the worker ignores additive metadata keys).
    record = V1._record(path, label, read=True)
    record["read_mode"] = "small_read"
    record["builder_cap_bytes"] = SMALL_CAP
    return record


def _strict_read_json(path: Path, label: str, *, cap: int = SMALL_CAP) -> tuple[dict[str, Any], dict[str, Any]]:
    if cap > SMALL_CAP:
        cap = SMALL_CAP
    return _V1_READ_JSON(path, label, cap=cap)


_V1_READ_JSON = V1._read_json
V1.SMALL_CAP = SMALL_CAP
V1._record_from_owner = _strict_record_from_owner
V1._read_json = _strict_read_json


def _record(path: Path, label: str) -> dict[str, Any]:
    return V1._record(path, label, read=True)


def _augment_output(output_dir: Path) -> dict[str, Any]:
    """Bind both builder versions into V1's exact manifest/request closure."""
    manifest_path = output_dir / "owner-grid-initial-support-manifest-v1.json"
    request_path = output_dir / "owner-grid-initial-support-request-v1.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    request = json.loads(request_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != SCHEMA or manifest.get("status") != "READY_FOR_PARENT_GUARDED_OWNER_GRID_INITIAL_SUPPORT":
        raise BuildFailure("frozen V1 manifest schema/status was not preserved")
    if request.get("schema") != REQUEST_SCHEMA or request.get("variant_schema") != WORKER_SCHEMA:
        raise BuildFailure("frozen V1 request schema/status contract was not preserved")

    wrapper_record = _record(Path(__file__), "10 MiB initial-support V2 wrapper")
    v1_record = _record(V1_PATH, "frozen V1 initial-support builder")
    records = [wrapper_record, v1_record]
    for record in records:
        path = record["path"]
        if not any(item.get("path") == path for item in manifest.get("static_sources", [])):
            manifest.setdefault("static_sources", []).append(record)
        request.setdefault("input_records", {})[path] = record

    manifest["builder_provenance_v2"] = {
        "path": wrapper_record["path"],
        "sha256": wrapper_record["sha256"],
        "cap_bytes": SMALL_CAP,
        "large_control_policy": "stat_only_deferred_with_owner_sha",
        "v1_worker_schema_preserved": True,
        "production_payload_read": False,
    }
    manifest["read_cap_bytes"] = SMALL_CAP
    # Rewriting the manifest changes the manifest record embedded in the V1
    # request.  Recompute that record only after the final manifest bytes exist.
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    manifest_record = _record(manifest_path, "final V2 initial-support manifest")
    request["input_records"][manifest_record["path"]] = manifest_record
    request["input_files"] = sorted(request["input_records"])
    request["input_sha256"] = {
        path: record["sha256"] for path, record in request["input_records"].items()
        if _valid_sha(record.get("sha256"))
    }
    request["manifest"] = manifest_record
    request["builder_provenance_v2"] = manifest["builder_provenance_v2"]
    request["read_cap_bytes"] = SMALL_CAP
    request["large_control_policy"] = "stat_only_deferred_with_owner_sha"
    request_path.write_text(json.dumps(request, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return {
        "manifest": manifest,
        "manifest_path": str(manifest_path),
        "request": request,
        "request_path": str(request_path),
        "worker_schema": WORKER_SCHEMA,
        "status": manifest["status"],
        "cap_bytes": SMALL_CAP,
        "production_payload_read": False,
    }


def build(owner_report: Path, product_map: Path, output_dir: Path) -> dict[str, Any]:
    # V1 uses its module __file__ to identify the builder in generated
    # metadata.  Temporarily point that name at this wrapper so provenance
    # records identify the actual V2 source that constructed the request.
    previous_file = V1.__file__
    V1.__file__ = str(Path(__file__).resolve())
    try:
        V1.build(owner_report, product_map, output_dir)
    except Exception as exc:
        if isinstance(exc, (V1.BuildFailure, OSError, ValueError, json.JSONDecodeError)):
            raise BuildFailure(str(exc)) from exc
        raise
    finally:
        V1.__file__ = previous_file
    return _augment_output(Path(output_dir).expanduser().absolute())


def _self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="owner-grid-support-v2-") as value:
        root = Path(value)
        large = root / "large-control.csv"
        # Only a manufactured fixture is written; no production control file
        # is opened.  The record must remain stat-only and retain its SHA.
        large.write_bytes(b"x" * (SMALL_CAP + 1))
        declared = hashlib.sha256(large.read_bytes()).hexdigest()
        record = _strict_record_from_owner({"path": str(large), "sha256": declared}, "fixture control", allow_deferred=True)
        assert record["read_mode"] == "stat_only_deferred_over_10MiB"
        assert record["payload_read_by_builder"] is False
        assert record["sha256"] == declared
        try:
            _strict_record_from_owner({"path": str(large)}, "missing owner SHA", allow_deferred=True)
        except BuildFailure:
            pass
        else:
            raise AssertionError("large deferred source without owner SHA was accepted")
        small = root / "small.xml"
        small.write_text("<case/>", encoding="utf-8")
        assert _strict_record_from_owner({"path": str(small)}, "small XML")["read_mode"] == "small_read"
    print("PASS_THREE_SENTINEL_OWNER_GRID_INITIAL_SUPPORT_REQUEST_V2_SELFTEST")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build", action="store_true")
    parser.add_argument("--owner-report", type=Path, default=V1.PRIMARY_OWNER_REPORT if hasattr(V1, "PRIMARY_OWNER_REPORT") else None)
    parser.add_argument("--product-map", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    if args.self_test:
        try:
            _self_test()
        except Exception as exc:
            print(f"FAILED_THREE_SENTINEL_OWNER_GRID_INITIAL_SUPPORT_REQUEST_V2_SELFTEST: {exc}", file=sys.stderr)
            return 2
        return 0
    if args.owner_report is None or args.product_map is None or args.output_dir is None:
        parser.error("--build requires --owner-report, --product-map, and --output-dir")
    try:
        value = build(args.owner_report, args.product_map, args.output_dir)
    except (BuildFailure, V1.BuildFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_THREE_SENTINEL_OWNER_GRID_INITIAL_SUPPORT_REQUEST_V2: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": value["status"], "manifest": value["manifest_path"],
                      "request": value["request_path"], "cap_bytes": SMALL_CAP,
                      "production_payload_read": False, "scientific_credit": 0}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
