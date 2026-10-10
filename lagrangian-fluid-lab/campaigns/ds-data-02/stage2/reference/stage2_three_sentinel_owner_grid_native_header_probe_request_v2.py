#!/usr/bin/env python3
"""Prepare a parent-guarded native-header probe manifest.

This builder is additive to the frozen initial-support request builders.  It
joins each initial-support product row to the explicit producer request record
from the nine-row GenCase product map, then defers the receipt and BI4 until a
parent has reserved the corresponding GenCase outputs.  The builder reads no
BI4/VTK/native payload.  Its output is a source-prepared request; a root
normalizer may enable it only after the real GenCase receipt and request-file
byte SHA are available.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
from typing import Any


HERE = Path(__file__).resolve().parent
PROBE = HERE / "stage2_three_sentinel_owner_grid_native_header_probe_v2.py"
VERIFY = HERE / "stage2_three_sentinel_owner_grid_initial_support_verify_v3.py"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
JSON_CAP = 10 * 1024 * 1024
SCHEMA = "ds02.stage2.three-sentinel-owner-grid-native-header-probe-manifest.v2"
REQUEST_SCHEMA = "ds02.stage2.three-sentinel-owner-grid-native-header-probe-request.v2"
TARGETS = ("F2-S2", "F3-S1", "F5-S1")
GRIDS = ("original", "coarse", "fine")


class BuildFailure(RuntimeError):
    pass


def _abs(path: Path) -> Path:
    return path.expanduser().absolute()


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {"device": int(value.st_dev), "inode": int(value.st_ino), "bytes": int(value.st_size),
            "mtime_ns": int(value.st_mtime_ns), "ctime_ns": int(value.st_ctime_ns)}


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-fA-F]{64}", value))


def _record(path: Path, label: str, *, read_json: bool = False) -> dict[str, Any]:
    path = _abs(path)
    if path.is_symlink() or not path.is_file():
        raise BuildFailure(f"{label} is not a regular file: {path}")
    st = _stat(path)
    if read_json and st["bytes"] > JSON_CAP:
        raise BuildFailure(f"{label} exceeds the 10 MiB metadata cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if st != after:
        raise BuildFailure(f"{label} changed during bounded metadata read")
    return {"path": str(path), "sha256": _sha(raw), "stat": after,
            "hash_status": "BOUND_SMALL_METADATA", "payload_read_by_builder": False}


def _read_json(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    record = _record(path, label, read_json=True)
    value = json.loads(Path(record["path"]).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise BuildFailure(f"{label} is not an object")
    return value, record


def _deferred_record(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        raise BuildFailure(f"{label} lacks a path")
    path = _abs(Path(value["path"]))
    if path.is_symlink() or not path.is_file():
        # Parent may create the product after this source package.  Preserve
        # the producer-declared digest/stat without pretending it is present.
        declared = value.get("sha256")
        if not _valid_sha(declared):
            raise BuildFailure(f"{label} is absent and has no declared SHA")
        return {"path": str(path), "sha256": str(declared).lower(),
                "stat": value.get("stat") or value.get("stat_after") or {},
                "hash_status": "PARENT_AFTER_RESERVATION_REQUIRED",
                "payload_read_by_builder": False, "read_mode": "parent_after_reservation"}
    st = _stat(path)
    declared = value.get("sha256")
    if _valid_sha(declared) and st["bytes"] <= JSON_CAP:
        # JSON receipts/request files may be verified by the parent, but this
        # builder does not classify the BI4 as a small source merely by suffix.
        if path.suffix.lower() in {".bi4", ".vtk", ".h5", ".hdf5"}:
            return {"path": str(path), "sha256": str(declared).lower(), "stat": st,
                    "hash_status": "PARENT_AFTER_RESERVATION_REQUIRED",
                    "payload_read_by_builder": False, "read_mode": "parent_after_reservation"}
    return {"path": str(path), "sha256": str(declared).lower() if _valid_sha(declared) else None,
            "stat": st, "hash_status": "PARENT_AFTER_RESERVATION_REQUIRED",
            "payload_read_by_builder": False, "read_mode": "parent_after_reservation"}


def _write_once(path: Path, value: Any) -> None:
    path = _abs(path)
    if path.exists() or path.is_symlink():
        raise BuildFailure(f"refusing overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def build(initial_manifest_path: Path, product_map_path: Path, decoder: Path,
          output_dir: Path) -> dict[str, Any]:
    initial, initial_record = _read_json(initial_manifest_path, "initial-support manifest")
    products, product_map_record = _read_json(product_map_path, "GenCase product map")
    if initial.get("schema") != "ds02.stage2.three-sentinel-owner-grid-initial-support-manifest.v1":
        raise BuildFailure("initial manifest schema mismatch")
    product_rows = {(str(row.get("sentinel_id")), str(row.get("grid_label"))): row
                    for row in products.get("products", []) if isinstance(row, dict)}
    if set(product_rows) != {(sid, grid) for sid in TARGETS for grid in GRIDS}:
        raise BuildFailure("product map does not cover exactly nine rows")
    decoder_record = _record(decoder, "official BI4 decoder")
    output_dir = _abs(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise BuildFailure(f"refusing overwrite of non-empty output directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    cases: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    producer_records: list[dict[str, Any]] = []
    for row in initial.get("cases", []):
        if not isinstance(row, dict):
            raise BuildFailure("initial manifest case is malformed")
        sid, grid = str(row.get("sentinel_id")), str(row.get("grid_label"))
        key = (sid, grid)
        if key not in product_rows:
            raise BuildFailure(f"product map lacks {sid}:{grid}")
        producer = product_rows[key].get("producer_request")
        if not isinstance(producer, dict) or not isinstance(producer.get("path"), str):
            raise BuildFailure(f"{sid}:{grid} product map has no explicit producer_request")
        producer_record = _record(Path(producer["path"]), f"{sid}:{grid} producer request", read_json=True)
        if _valid_sha(producer.get("sha256")) and producer["sha256"].lower() != producer_record["sha256"]:
            raise BuildFailure(f"{sid}:{grid} producer request SHA differs from product map")
        producer_records.append({"row_key": f"{sid}:{grid}", **producer_record})
        receipt = _deferred_record(row.get("gencase_receipt"), f"{sid}:{grid} receipt")
        native = _deferred_record(row.get("native_bi4"), f"{sid}:{grid} BI4")
        deferred.extend([
            {"row_key": f"{sid}:{grid}", "role": "gencase_receipt", **receipt},
            {"row_key": f"{sid}:{grid}", "role": "native_bi4", **native},
        ])
        cases.append({
            "row_key": f"{sid}:{grid}", "sentinel_id": sid, "grid_label": grid,
            "family_id": row.get("family_id"), "physical_case_id": row.get("physical_case_id"),
            "gencase_receipt": receipt, "producer_request": producer_record,
            "native_bi4": native, "decoder": decoder_record,
            "source_xml": row.get("source_xml"), "candidate_def": row.get("candidate_def"),
            "native_header_probe": {"status": "PARENT_AFTER_RESERVATION_REQUIRED"},
        })
    manifest = {
        "schema": SCHEMA, "status": "READY_FOR_PARENT_GUARDED_NATIVE_HEADER_PROBE",
        "initial_support_manifest": initial_record, "product_map": product_map_record,
        "producer_requests": producer_records, "cases": cases,
        "decoder": decoder_record,
        "read_scope": {"production_payload_read_by_builder": False, "xml_mass_fallback": False,
                        "solver_launch": False, "gencase_launch": False, "hdf5_read": False,
                        "native_header_only": True, "parent_after_reservation_bi4_read": True},
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0},
    }
    manifest_path = output_dir / "native-header-probe-manifest-v2.json"
    _write_once(manifest_path, manifest)
    manifest_record = _record(manifest_path, "native-header probe manifest", read_json=True)
    static = {initial_record["path"]: initial_record, product_map_record["path"]: product_map_record,
              str(PROBE): _record(PROBE, "native-header probe worker", read_json=False),
              str(VERIFY): _record(VERIFY, "initial-support V3 verifier", read_json=False),
              decoder_record["path"]: decoder_record}
    static.update({item["path"]: item for item in producer_records})
    static[manifest_record["path"]] = manifest_record
    request = {
        "schema": "ds02.request.v1", "variant_schema": REQUEST_SCHEMA,
        "status": "READY_FOR_PARENT_GUARDED_NATIVE_HEADER_PROBE",
        "kind": "generic-cpu-audit", "cpu_task_kind": "initial_support_native_header_probe",
        "family_id": "DS02-THREE-SENTINEL", "case_id": "F2_F3_F5_OWNER_GRID_NATIVE_HEADER_PROBE_V2",
        "attempt_id": "PARENT_ASSIGNED_AFTER_GENCASE",
        "command": [str(PYTHON), str(PROBE), "--run", "--manifest", str(manifest_path),
                    "--attempt-root", "{attempt_root}", "--output", "{attempt_root}/report/native-header-probe-v2.json"],
        "input_files": sorted(static), "input_records": static,
        "input_sha256": {path: rec["sha256"] for path, rec in static.items() if _valid_sha(rec.get("sha256"))},
        "manifest": manifest_record, "deferred_input_records": deferred,
        "execution_allowed": False, "gencase_launch": False, "solver_launch": False,
        "parent_v8_deferred_fields_not_credit": True,
        "resource_scope": {"cpu_threads": 1, "max_wall_seconds": 1800, "memory_max_bytes": 4 * 1024**3,
                           "scratch_max_bytes": 256 * 1024**2, "log_max_bytes": 64 * 1024, "gpu": "none"},
        "source_binding": {"receipt_request_exact_file_sha": True, "native_bi4_pre_post_sha_stat": True,
                           "decoder_output_xml_pre_post_sha_stat": True, "xml_mass_fallback": False,
                           "same_parent_initial_support": True},
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0},
    }
    request_path = output_dir / "native-header-probe-request-v2.json"
    _write_once(request_path, request)
    return {"manifest": str(manifest_path), "request": str(request_path),
            "manifest_sha256": manifest_record["sha256"], "producer_request_count": len(producer_records),
            "deferred_product_count": len(deferred), "execution_allowed": False,
            "production_payload_read": False}


def self_test() -> None:
    # This is a source-shape test only; the probe worker's own manufactured
    # decoder fixture is the executable metadata test.  No production path is
    # opened here.
    with __import__("tempfile").TemporaryDirectory(prefix="owner-grid-header-request-v2-") as value:
        root = Path(value)
        initial = {"schema": "ds02.stage2.three-sentinel-owner-grid-initial-support-manifest.v1", "cases": []}
        products = {"products": []}
        for sid in TARGETS:
            for grid in GRIDS:
                case_dir = root / sid / grid; case_dir.mkdir(parents=True)
                def tiny(name: str, text: str = "x") -> dict[str, Any]:
                    path = case_dir / name; path.write_text(text, encoding="utf-8")
                    return {"path": str(path), "sha256": _sha(path.read_bytes()), "stat": _stat(path)}
                req = root / "producer" / f"{sid}_{grid}.json"; req.parent.mkdir(exist_ok=True)
                req.write_text(json.dumps({"schema": "ds02.request.v1", "case_id": "case", "attempt_id": "attempt"}) + "\n", encoding="utf-8")
                initial["cases"].append({"sentinel_id": sid, "grid_label": grid, "family_id": sid[:2],
                                         "physical_case_id": f"{sid}-{grid}", "gencase_receipt": tiny("receipt.json"),
                                         "native_bi4": tiny("native.bi4"), "source_xml": tiny("source.xml"),
                                         "candidate_def": tiny("candidate_Def.xml")})
                products["products"].append({"sentinel_id": sid, "grid_label": grid,
                                              "producer_request": {"path": str(req), "sha256": _sha(req.read_bytes()), "stat": _stat(req)}})
        initial_path = root / "initial.json"; initial_path.write_text(json.dumps(initial) + "\n", encoding="utf-8")
        product_path = root / "products.json"; product_path.write_text(json.dumps(products) + "\n", encoding="utf-8")
        decoder = root / "decoder"; decoder.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8"); decoder.chmod(0o755)
        result = build(initial_path, product_path, decoder, root / "out")
        request = json.loads(Path(result["request"]).read_text(encoding="utf-8"))
        assert len(request["deferred_input_records"]) == 18
        assert request["execution_allowed"] is False
        assert all("producer_request" in case for case in json.loads(Path(result["manifest"]).read_text())["cases"])
    print("PASS_THREE_SENTINEL_OWNER_GRID_NATIVE_HEADER_PROBE_REQUEST_V2_SELFTEST")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build", action="store_true")
    parser.add_argument("--initial-manifest", type=Path)
    parser.add_argument("--product-map", type=Path)
    parser.add_argument("--decoder", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            self_test(); return 0
        if None in (args.initial_manifest, args.product_map, args.decoder, args.output_dir):
            parser.error("--build requires --initial-manifest, --product-map, --decoder, and --output-dir")
        build(args.initial_manifest, args.product_map, args.decoder, args.output_dir); return 0
    except (BuildFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_THREE_SENTINEL_OWNER_GRID_NATIVE_HEADER_PROBE_REQUEST_V2: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
