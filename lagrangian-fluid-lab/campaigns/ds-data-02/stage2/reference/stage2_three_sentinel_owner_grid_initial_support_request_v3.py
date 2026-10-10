#!/usr/bin/env python3
"""Attach exact producer-request file records to the V2 support request.

The runtime receipt ABI uses the SHA of the producer request *file bytes*, not
canonical JSON.  This additive builder preserves the V1 manifest/request schema
for the frozen worker, but joins each of the nine product-map producer request
records into the manifest and static source closure with its actual file SHA.
The companion verifier V3 then checks ``receipt.request == file JSON`` and
``receipt.request_sha256 == sha256(file bytes)``.  No GenCase, solver, or
production payload is read or started here.
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
V2_PATH = HERE / "stage2_three_sentinel_owner_grid_initial_support_request_v2.py"
SPEC = importlib.util.spec_from_file_location("owner_grid_initial_support_request_v2_for_v3", V2_PATH)
if SPEC is None or SPEC.loader is None: raise RuntimeError(f"cannot load {V2_PATH}")
V2 = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(V2)
V1 = V2.V1
SMALL_CAP = 10 * 1024 * 1024
SCHEMA = V2.SCHEMA
REQUEST_SCHEMA = V2.REQUEST_SCHEMA
WORKER_SCHEMA = V2.WORKER_SCHEMA
TARGETS = tuple(V1.TARGETS); GRIDS = tuple(V1.GRIDS)
ROW_KEYS = tuple(f"{sid}:{grid}" for sid in TARGETS for grid in GRIDS)


class BuildFailure(RuntimeError): pass


def _stat(path: Path) -> dict[str, int]:
    s = path.stat(); return {"device": int(s.st_dev), "inode": int(s.st_ino), "bytes": int(s.st_size),
                              "mtime_ns": int(s.st_mtime_ns), "ctime_ns": int(s.st_ctime_ns)}


def _sha(raw: bytes) -> str: return hashlib.sha256(raw).hexdigest()


def _read_json(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any], bytes]:
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file(): raise BuildFailure(f"{label} is not regular: {path}")
    before = _stat(path)
    if before["bytes"] > SMALL_CAP: raise BuildFailure(f"{label} exceeds 10 MiB cap")
    raw = path.read_bytes(); after = _stat(path)
    if before != after: raise BuildFailure(f"{label} changed during read")
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict): raise BuildFailure(f"{label} must be object")
    return value, {"path": str(path), "sha256": _sha(raw), "bytes": before["bytes"],
                   "stat_before": before, "stat_after": after, "read_mode": "small_read",
                   "payload_read_by_builder": True}, raw


def _record(path: Path, label: str) -> dict[str, Any]:
    value, rec, _ = _read_json(path, label)
    del value
    return rec


def _write(path: Path, value: Any) -> None:
    if path.is_symlink() or path.exists(): raise BuildFailure(f"refusing overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def _product_rows(product_map: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = product_map.get("products", product_map.get("cases"))
    if not isinstance(rows, list): raise BuildFailure("product map lacks products list")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict): raise BuildFailure("product row malformed")
        key = f"{row.get('sentinel_id')}:{row.get('grid_label')}"
        if key in result or key not in ROW_KEYS: raise BuildFailure(f"invalid/duplicate product row {key}")
        producer = row.get("producer_request")
        if not isinstance(producer, dict) or not isinstance(producer.get("path"), str):
            raise BuildFailure(f"{key} has no explicit producer_request file record")
        result[key] = row
    if set(result) != set(ROW_KEYS): raise BuildFailure("product map does not cover exactly nine rows")
    return result


def _attach(output_dir: Path, product_map_path: Path) -> dict[str, Any]:
    manifest_path = output_dir / "owner-grid-initial-support-manifest-v1.json"
    request_path = output_dir / "owner-grid-initial-support-request-v1.json"
    manifest, _, _ = _read_json(manifest_path, "V2 support manifest")
    request, _, _ = _read_json(request_path, "V2 support request")
    products, products_record, _ = _read_json(product_map_path, "producer product map")
    rows = _product_rows(products)
    cases = manifest.get("cases")
    if not isinstance(cases, list) or {f"{x.get('sentinel_id')}:{x.get('grid_label')}" for x in cases} != set(ROW_KEYS):
        raise BuildFailure("support manifest does not cover nine rows")
    producer_records: dict[str, dict[str, Any]] = {}
    for case in cases:
        key = f"{case['sentinel_id']}:{case['grid_label']}"
        record = rows[key]["producer_request"]
        producer_record = _record(Path(record["path"]), f"{key} producer request")
        declared = record.get("sha256")
        if isinstance(declared, str) and declared.lower() != producer_record["sha256"].lower():
            raise BuildFailure(f"{key} producer request declared SHA differs from file bytes")
        case["producer_request"] = producer_record
        producer_records[key] = producer_record
    manifest["producer_request_identity_basis"] = "EXACT_PRODUCER_REQUEST_FILE_BYTES"
    manifest["producer_request_records"] = producer_records
    manifest["builder_provenance_v3"] = {"path": str(Path(__file__).resolve()),
                                           "schema": "ds02.stage2.three-sentinel-owner-grid-initial-support-manifest.v1",
                                           "receipt_request_sha_basis": "SHA256_RAW_PRODUCER_REQUEST_FILE_BYTES",
                                           "production_payload_read": False}
    # Final manifest bytes are written before its request record is made.
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    manifest_record = _record(manifest_path, "final V3 support manifest")
    static = request.get("input_records")
    if not isinstance(static, dict): raise BuildFailure("V2 request input_records is not a map")
    static = {str(k): dict(v) for k, v in static.items() if isinstance(v, dict)}
    static[manifest_record["path"]] = manifest_record
    static[products_record["path"]] = products_record
    for rec in producer_records.values(): static[rec["path"]] = rec
    request["input_records"] = static
    request["input_files"] = sorted(static)
    request["input_sha256"] = {path: rec["sha256"] for path, rec in static.items() if isinstance(rec.get("sha256"), str)}
    request["manifest"] = manifest_record
    request["producer_request_records"] = producer_records
    request["producer_request_identity_basis"] = "EXACT_PRODUCER_REQUEST_FILE_BYTES"
    request["builder_provenance_v3"] = manifest["builder_provenance_v3"]
    request_path.write_text(json.dumps(request, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"manifest_path": str(manifest_path), "request_path": str(request_path),
            "producer_request_records": producer_records, "manifest": manifest, "request": request}


def build(owner_report: Path, product_map: Path, output_dir: Path) -> dict[str, Any]:
    output_dir = output_dir.expanduser().absolute()
    if output_dir.exists() and any(output_dir.iterdir()): raise BuildFailure(f"refusing non-empty output: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    V2.build(owner_report, product_map, output_dir)
    return _attach(output_dir, product_map)


def _self_test() -> None:
    # V2's manufactured owner/product fixture is enough to exercise the real
    # builder.  Producer request files are genuine small JSON documents, and
    # their raw-byte SHA is then checked against the attached records.
    with tempfile.TemporaryDirectory(prefix="owner-grid-support-request-v3-") as td:
        root = Path(td); owner, product = V1._fixture_owner(root)
        product_value = json.loads(product.read_text())
        for row in product_value["products"]:
            key = f"{row['sentinel_id']}:{row['grid_label']}"
            producer = root / "producer" / (key.replace(":", "_") + ".json"); producer.parent.mkdir(parents=True, exist_ok=True)
            producer.write_text(json.dumps({"schema": REQUEST_SCHEMA, "family_id": row["sentinel_id"][:2],
                                            "sentinel_id": row["sentinel_id"], "grid_label": row["grid_label"],
                                            "case_id": key.replace(":", "_"), "attempt_id": "fixture-attempt",
                                            "execution_allowed": False}, sort_keys=True) + "\n")
            raw = producer.read_bytes(); st = _stat(producer)
            row["producer_request"] = {"path": str(producer), "sha256": _sha(raw), "stat": st}
        product.write_text(json.dumps(product_value, indent=2) + "\n")
        out = root / "out"; result = build(owner, product, out)
        assert len(result["producer_request_records"]) == 9
        for key, rec in result["producer_request_records"].items():
            assert rec["sha256"] == _sha(Path(rec["path"]).read_bytes())
        # A file-byte mutation is rejected on the next additive attach.
        one = Path(next(iter(result["producer_request_records"].values()))["path"]); one.write_text(one.read_text() + "tamper")
        try: _attach(out, product)
        except (BuildFailure, OSError, ValueError, json.JSONDecodeError): pass
        else: raise AssertionError("tampered producer request accepted")
    print("PASS_THREE_SENTINEL_OWNER_GRID_INITIAL_SUPPORT_REQUEST_V3_SELFTEST")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__); g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--self-test", action="store_true"); g.add_argument("--build", action="store_true")
    p.add_argument("--owner-report", type=Path); p.add_argument("--product-map", type=Path); p.add_argument("--output-dir", type=Path)
    args = p.parse_args(argv)
    try:
        if args.self_test: _self_test(); return 0
        if args.owner_report is None or args.product_map is None or args.output_dir is None: p.error("--build requires owner/product/output")
        result = build(args.owner_report, args.product_map, args.output_dir)
        print(json.dumps({"status": result["manifest"]["status"], "manifest": result["manifest_path"],
                          "request": result["request_path"], "producer_requests": 9, "scientific_credit": 0}, sort_keys=True)); return 0
    except (BuildFailure, V2.BuildFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_THREE_SENTINEL_OWNER_GRID_INITIAL_SUPPORT_REQUEST_V3: {exc}", file=sys.stderr); return 2


if __name__ == "__main__": raise SystemExit(main())
