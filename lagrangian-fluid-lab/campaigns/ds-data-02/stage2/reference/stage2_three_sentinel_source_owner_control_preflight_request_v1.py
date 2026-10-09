#!/usr/bin/env python3
"""Build the parent-ready CPU request for the three-sentinel source preflight.

The builder only binds bounded JSON/XML/receipt/motion files.  It intentionally
does not put any BI4, VTK, HDF5, or native Part path into ``input_files``.
Those products are listed as a guarded follow-up in the manifest and must be
audited only by a later parent reservation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
PYVENV = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/pyvenv.cfg")
WORKER = HERE / "stage2_three_sentinel_source_owner_control_preflight_v1.py"
CONTRACT = HERE / "stage2_three_sentinel_source_owner_control_preflight_v1.json"
SCHEMA = "ds02.request.v1"
VARIANT = "ds02.stage2.three-sentinel.source-owner-control-preflight.v1"
MANIFEST_SCHEMA = "ds02.stage2.three-sentinel.source-owner-control-manifest.v1"
TARGETS = ("F2-S2", "F3-S1", "F5-S1")
MAX_SMALL_BYTES = 16 * 1024 * 1024
FORBIDDEN_SUFFIXES = {".bi4", ".vtk", ".h5", ".hdf5", ".part"}


class BuildFailure(RuntimeError):
    pass


def _absolute(path: Path) -> Path:
    return path.expanduser().absolute()


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {"device": int(value.st_dev), "inode": int(value.st_ino), "bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns), "ctime_ns": int(value.st_ctime_ns)}


def _record(path: Path, label: str, *, parse_json: bool = False) -> tuple[Any, dict[str, Any]]:
    path = _absolute(path)
    if path.is_symlink() or not path.is_file():
        raise BuildFailure(f"{label} is not a regular non-symlink file: {path}")
    before = _stat(path)
    if before["bytes"] > MAX_SMALL_BYTES:
        raise BuildFailure(f"{label} exceeds bounded source cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after or len(raw) != before["bytes"]:
        raise BuildFailure(f"{label} changed during bounded source read: {path}")
    record = {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "stat_before": before, "stat_after": after, "payload_read_by_builder": False, "scope": "bounded_small_source_metadata"}
    if not parse_json:
        return raw, record
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BuildFailure(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise BuildFailure(f"{label} must be a JSON object")
    return value, record


def _write_once(path: Path, value: Any) -> None:
    path = _absolute(path)
    if path.exists() or path.is_symlink():
        raise BuildFailure(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    with temporary.open("rb") as handle:
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _literal_python_record() -> dict[str, Any]:
    path = _absolute(PYTHON)
    if not path.is_symlink():
        raise BuildFailure(f"worker argv0 must be the literal venv entrypoint: {path}")
    target = path.resolve(strict=True)
    _, target_record = _record(target, "resolved venv interpreter")
    target_record.update({"path": str(path), "literal_argv0": True, "resolved_target": str(target), "payload_read_by_builder": False})
    return target_record


def _source_rows(audit: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if audit.get("schema") != "ds02.stage2.fourteen-source-control-audit.v5":
        raise BuildFailure("source control audit schema mismatch")
    rows = audit.get("sources")
    if not isinstance(rows, list):
        raise BuildFailure("source control audit lacks sources")
    result = {row.get("sentinel_id"): row for row in rows if isinstance(row, dict)}
    if any(sid not in result for sid in TARGETS):
        raise BuildFailure("source control audit does not contain all three targets")
    return result


def _bounds_rows(bounds: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if bounds.get("schema") != "ds02.stage2.continuum-geometry-bounds.v1":
        raise BuildFailure("geometry bounds schema mismatch")
    rows = bounds.get("sources")
    if not isinstance(rows, list):
        raise BuildFailure("geometry bounds lacks sources")
    result = {row.get("sentinel_id"): row for row in rows if isinstance(row, dict)}
    if any(sid not in result for sid in TARGETS):
        raise BuildFailure("geometry bounds does not contain all three targets")
    return result


def _motion_path(row: dict[str, Any]) -> Path | None:
    resolution = row.get("motion_file_resolution") or {}
    refs = resolution.get("references") if isinstance(resolution, dict) else []
    for item in refs if isinstance(refs, list) else []:
        for candidate in item.get("candidates", []) if isinstance(item, dict) else []:
            if not isinstance(candidate, dict) or not candidate.get("path") or not candidate.get("actual_sha256"):
                continue
            path = Path(str(candidate["path"]))
            if path.is_file() and path.suffix.lower() not in FORBIDDEN_SUFFIXES:
                return path
    return None


def _add_record(static: dict[str, dict[str, Any]], record: dict[str, Any]) -> None:
    path = record.get("path")
    if not isinstance(path, str):
        raise BuildFailure("input record lacks path")
    if Path(path).suffix.lower() in FORBIDDEN_SUFFIXES:
        raise BuildFailure(f"forbidden native payload would enter source request: {path}")
    prior = static.get(path)
    if prior is not None and prior.get("sha256") != record.get("sha256"):
        raise BuildFailure(f"conflicting source records for {path}")
    static[path] = record


def build(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    audit, audit_record = _record(args.source_control_audit, "source control audit", parse_json=True)
    bounds, bounds_record = _record(args.geometry_bounds, "geometry bounds report", parse_json=True)
    status, status_record = _record(args.source_status, "source status report", parse_json=True)
    if not isinstance(status.get("sentinels"), list):
        raise BuildFailure("source status report lacks sentinel list")
    rows = _source_rows(audit)
    _bounds_rows(bounds)
    contract, contract_record = _record(CONTRACT, "source-owner-control contract", parse_json=True)
    if contract.get("schema") != "ds02.stage2.three-sentinel.source-owner-control-contract.v1":
        raise BuildFailure("contract schema mismatch")
    static: dict[str, dict[str, Any]] = {}
    for item in (audit_record, bounds_record, status_record, contract_record, _record(WORKER, "source-owner-control worker")[1], _literal_python_record(), _record(PYVENV, "literal venv configuration")[1]):
        _add_record(static, item)
    source_xml_records: dict[str, dict[str, Any]] = {}
    receipt_records: dict[str, dict[str, Any]] = {}
    motion_records: dict[str, dict[str, Any] | None] = {}
    for sid in TARGETS:
        row = rows[sid]
        xml_binding = row.get("source_xml")
        receipt_binding = (row.get("source_solver_control") or {}).get("receipt")
        if not isinstance(xml_binding, dict) or not isinstance(receipt_binding, dict):
            raise BuildFailure(f"{sid} source XML/receipt binding incomplete")
        _, xml_record = _record(Path(xml_binding["path"]), f"{sid} source XML")
        if xml_record["sha256"] != xml_binding.get("sha256"):
            raise BuildFailure(f"{sid} source XML SHA disagrees with source audit")
        receipt, receipt_probe_record = _record(Path(receipt_binding["path"]), f"{sid} solver receipt", parse_json=True)
        _, receipt_record = _record(Path(receipt_binding["path"]), f"{sid} solver receipt raw")
        if receipt_record["sha256"] != receipt_binding.get("sha256"):
            raise BuildFailure(f"{sid} solver receipt SHA disagrees with source audit")
        if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
            raise BuildFailure(f"{sid} solver receipt is not completed/zero")
        request = receipt.get("request")
        if not isinstance(request, dict) or request.get("family_id") != row.get("family_id") or request.get("physical_case_id") not in (None, row.get("physical_case_id")):
            raise BuildFailure(f"{sid} solver receipt identity is not source-bound")
        _add_record(static, xml_record); _add_record(static, receipt_record)
        source_xml_records[sid] = xml_record
        receipt_records[sid] = receipt_record
        motion = _motion_path(row)
        if motion is not None:
            _, motion_record = _record(motion, f"{sid} motion source")
            expected = next((candidate.get("actual_sha256") for ref in (row.get("motion_file_resolution") or {}).get("references", []) for candidate in ref.get("candidates", []) if candidate.get("path") == str(motion)), None)
            if expected and motion_record["sha256"] != expected:
                raise BuildFailure(f"{sid} motion SHA disagrees with source audit")
            _add_record(static, motion_record)
            motion_records[sid] = motion_record
        else:
            motion_records[sid] = None
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "status": "PREPARED_SOURCE_OWNER_CONTROL_PREFLIGHT_V1",
        "sentinel_ids": list(TARGETS),
        "source_inputs": {"source_control_audit": audit_record, "geometry_bounds": bounds_record, "source_status": status_record},
        "source_products": {sid: {"source_xml": source_xml_records[sid], "solver_receipt": receipt_records[sid], "motion": motion_records[sid], "guarded_payloads": {"bi4": "DEFERRED_PARENT_GUARD", "fluid_vtk": "DEFERRED_PARENT_GUARD", "bound_vtk": "DEFERRED_PARENT_GUARD"}} for sid in TARGETS},
        "static_sources": sorted(static.values(), key=lambda item: item["path"]),
        "policy": {"xml_receipt_motion_only": True, "native_payload_read": False, "bi4_read": False, "vtk_read": False, "hdf5_read": False, "solver_launch": False, "scientific_credit": 0},
        "owner_policy": {"F2-S2": "UNVERIFIED_CROSS_SENTINEL_TARGET", "F3-S1": "UNVERIFIED_SOURCE_CONTINUOUS_OWNER", "F5-S1": "UNVERIFIED_SOURCE_CONTINUOUS_OWNER"},
    }
    manifest_path = _absolute(args.manifest_output)
    _write_once(manifest_path, manifest)
    _, manifest_record = _record(manifest_path, "generated source-owner-control manifest", parse_json=True)
    _add_record(static, manifest_record)
    input_files = sorted(static)
    input_sha256 = {path: static[path]["sha256"] for path in input_files}
    request = {
        "schema": SCHEMA,
        "variant_schema": VARIANT,
        "status": "READY_FOR_PARENT_SOURCE_OWNER_CONTROL_PREFLIGHT",
        "request_id": "three-sentinel-source-owner-control-preflight-v1",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "family_id": "DS-DATA-02",
        "sentinel_ids": list(TARGETS),
        "case_id": "F2_S2_F3_S1_F5_S1_SOURCE_OWNER_CONTROL_PREFLIGHT_V1",
        "attempt_id": "three-sentinel-source-owner-control-preflight-v1-001",
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 300,
        "max_memory_bytes": 1024 * 1024 * 1024,
        "estimated_storage_bytes": 8 * 1024 * 1024,
        "command": [str(_absolute(PYTHON)), str(_absolute(WORKER)), "--run", "--manifest", str(manifest_path), "--output", str(_absolute(args.output))],
        "cwd": str(HERE.parents[5]),
        "input_files": input_files,
        "input_records": static,
        "input_sha256": input_sha256,
        "execution_allowed": True,
        "launch_disabled": False,
        "native_payload_read": False,
        "bi4_read": False,
        "vtk_read": False,
        "hdf5_read": False,
        "solver_launch": False,
        "source_only": True,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0},
        "owner_policy": manifest["owner_policy"],
        "guarded_followup": manifest["source_products"],
    }
    request_path = _absolute(args.request_output)
    _write_once(request_path, request)
    return manifest, request


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="three-sentinel-source-request-") as td:
        root = Path(td)
        for name, value in (("audit.json", {"schema": "ds02.stage2.fourteen-source-control-audit.v5", "sources": [{"sentinel_id": sid} for sid in TARGETS]}), ("bounds.json", {"schema": "ds02.stage2.continuum-geometry-bounds.v1", "sources": [{"sentinel_id": sid} for sid in TARGETS]}), ("status.json", {"sentinels": []})):
            (root / name).write_text(json.dumps(value), encoding="utf-8")
        for filename in ("bad.bi4", "bad.vtk", "bad.h5"):
            (root / filename).write_bytes(b"payload")
        # The negative is deliberately checked before any production source is
        # involved; builder input admission must reject payload suffixes.
        try:
            _add_record({}, {"path": str(root / "bad.bi4"), "sha256": "0" * 64})
        except BuildFailure:
            pass
        else:
            raise AssertionError("forbidden payload was admitted")
    assert TARGETS == ("F2-S2", "F3-S1", "F5-S1")
    print("PASS_THREE_SENTINEL_SOURCE_OWNER_CONTROL_REQUEST_SELFTEST")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--source-control-audit", type=Path)
    parser.add_argument("--geometry-bounds", type=Path)
    parser.add_argument("--source-status", type=Path)
    parser.add_argument("--manifest-output", type=Path)
    parser.add_argument("--request-output", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    required = (args.source_control_audit, args.geometry_bounds, args.source_status, args.manifest_output, args.request_output, args.output)
    if any(value is None for value in required):
        parser.error("all source and output paths are required unless --self-test is used")
    try:
        manifest, request = build(args)
    except (BuildFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_THREE_SENTINEL_SOURCE_OWNER_CONTROL_REQUEST: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": request["status"], "manifest": str(_absolute(args.manifest_output)), "request": str(_absolute(args.request_output)), "input_files": len(request["input_files"]), "native_payload_read": False, "solver_launch": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
