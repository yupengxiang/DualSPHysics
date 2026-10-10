#!/usr/bin/env python3
"""Header-gated ROOT345 -> initial-support -> calibration source chain.

This additive source-only adapter is intentionally strict.  It materializes a
support manifest only after a terminal native-header report has been joined to
the exact ROOT345 producer request/proof/receipt edges.  The header report is
kept separate from the legacy ``native_header_probe`` sidecar: the latter
requires position/Idp fields while the real header probe only reports
 decoder-produced MassFluid/MassBound/Dp.  No generated XML, VTK, BI4, HDF5,
solver, or GenCase payload is read here.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import tempfile
from typing import Any

HERE = Path(__file__).resolve().parent
HANDOFF_PATH = HERE / "stage2_three_sentinel_owner_grid_native_initial_support_handoff_v3.py"
SUPPORT_PATH = HERE / "stage2_three_sentinel_owner_grid_initial_support_request_v3.py"
CALIBRATION_PATH = HERE / "stage2_three_sentinel_calibration_parent_v3.py"
SCHEMA = "ds02.stage2.three-sentinel.native-header-initial-support-calibration-chain.v1"
HANDOFF_SCHEMA = "ds02.stage2.three-sentinel.owner-grid-native-initial-support-handoff.v3"
HEADER_SCHEMAS = {"ds02.stage2.native-header-probe.v2", "ds02.stage2.native-header-probe.v3"}
HEADER_MANIFEST_SCHEMA = "ds02.stage2.three-sentinel-owner-grid-native-header-probe-manifest.v2"
HEADER_MANIFEST_STATUS = "READY_FOR_PARENT_GUARDED_NATIVE_HEADER_PROBE"
HEADER_REPORT_STATUS = "COMPLETE_NATIVE_HEADER_PROBE_DIAGNOSTIC"
SUPPORT_MANIFEST_SCHEMA = "ds02.stage2.three-sentinel-owner-grid-initial-support-manifest.v1"
SUPPORT_REPORT_SCHEMA = "ds02.stage2.three-sentinel-owner-grid-initial-support-audit.v1"
REQUEST_SCHEMA = "ds02.request.v1"
RECEIPT_SCHEMA = "ds02.execution-receipt.v1"
PROOF_STATUS = "VERIFIED_ACTUAL_OWNER_GRID_GENCASE_PRODUCTS_NO_SCIENTIFIC_Q"
EDGE_STATUS = "VERIFIED_COMPLETED_PRODUCER_EDGE"
TARGETS = ("F2-S2", "F3-S1", "F5-S1")
GRIDS = ("original", "coarse", "fine")
ROW_KEYS = tuple(f"{sid}:{grid}" for sid in TARGETS for grid in GRIDS)
HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
CAP = 10 * 1024 * 1024
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "scientific_credit": 0}
HEADER_ROW_STATUSES = {"PASS_NATIVE_HEADER_FIELDS", "UNKNOWN_NATIVE_HEADER_FIELDS_NOT_EXPOSED_BY_DECODER"}


class ChainFailure(RuntimeError):
    pass


class ChainWaiting(ChainFailure):
    pass


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ChainFailure(f"cannot import {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


HANDOFF = _load(HANDOFF_PATH, "root345_handoff_v3_chain_v1")
SUPPORT = _load(SUPPORT_PATH, "initial_support_request_v3_chain_v1")
CALIBRATION = _load(CALIBRATION_PATH, "three_sentinel_calibration_parent_v3_chain_v1")


def _abs(value: Path | str) -> Path:
    return Path(value).expanduser().absolute()


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and bool(HEX64.fullmatch(value))


def _stat(path: Path) -> dict[str, int]:
    s = path.stat()
    return {"device": int(s.st_dev), "inode": int(s.st_ino), "bytes": int(s.st_size),
            "mtime_ns": int(s.st_mtime_ns), "ctime_ns": int(s.st_ctime_ns)}


def _read(path: Path | str, label: str) -> tuple[dict[str, Any], dict[str, Any], bytes]:
    path = _abs(path)
    if path.is_symlink() or not path.is_file():
        raise ChainFailure(f"{label} is not a regular file: {path}")
    before = _stat(path)
    if before["bytes"] > CAP:
        raise ChainFailure(f"{label} exceeds 10 MiB metadata cap: {path}")
    raw = path.read_bytes(); after = _stat(path)
    if before != after or len(raw) != before["bytes"]:
        raise ChainFailure(f"{label} changed during bounded read: {path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ChainFailure(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ChainFailure(f"{label} is not a JSON object: {path}")
    record = {"path": str(path), "sha256": _sha(raw), "bytes": before["bytes"],
              "stat_before": before, "stat_after": after,
              "read_mode": "bounded_small_source", "payload_read_by_builder": True}
    return value, record, raw


def _record(path: Path | str, label: str) -> dict[str, Any]:
    path = _abs(path)
    if path.suffix.lower() not in {".py", ".cfg"}:
        return _read(path, label)[1]
    if path.is_symlink() or not path.is_file():
        raise ChainFailure(f"{label} is not a regular file: {path}")
    before = _stat(path)
    if before["bytes"] > CAP:
        raise ChainFailure(f"{label} exceeds 10 MiB source cap: {path}")
    raw = path.read_bytes(); after = _stat(path)
    if before != after:
        raise ChainFailure(f"{label} changed during bounded read: {path}")
    return {"path": str(path), "sha256": _sha(raw), "bytes": before["bytes"],
            "stat_before": before, "stat_after": after, "read_mode": "bounded_small_source",
            "payload_read_by_builder": True}


def _read_record(value: Any, label: str) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        raise ChainFailure(f"{label} lacks explicit path")
    parsed, record, _raw = _read(value["path"], label)
    path = _abs(value["path"])
    if _valid_sha(value.get("sha256")) and str(value["sha256"]).lower() != record["sha256"].lower():
        raise ChainFailure(f"{label} declared SHA differs from file bytes")
    return path, record, parsed


def _key(row: dict[str, Any]) -> str:
    return f"{row.get('sentinel_id')}:{row.get('grid_label')}"


def _rows(value: dict[str, Any], field: str, label: str) -> dict[str, dict[str, Any]]:
    items = value.get(field)
    if not isinstance(items, list) or len(items) != len(ROW_KEYS):
        raise ChainFailure(f"{label} must contain exactly nine {field}")
    out: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            raise ChainFailure(f"{label} contains a non-object row")
        key = _key(item)
        if key not in ROW_KEYS and isinstance(item.get("row_key"), str):
            key = item["row_key"]
        if key not in ROW_KEYS or key in out:
            raise ChainFailure(f"{label} has invalid/duplicate row {key}")
        out[key] = item
    if set(out) != set(ROW_KEYS):
        raise ChainFailure(f"{label} row set is not the nine fixed rows")
    return out


def _identity(row: dict[str, Any]) -> dict[str, str]:
    fields = ("sentinel_id", "grid_label", "family_id", "physical_case_id", "case_id", "attempt_id")
    result: dict[str, str] = {}
    for field in fields:
        value = row.get(field)
        if not isinstance(value, str) or not value:
            raise ChainFailure(f"{_key(row)} lacks exact {field}")
        result[field] = value
    return result


def _same(value: Any, expected: dict[str, str], label: str) -> None:
    if not isinstance(value, dict):
        raise ChainFailure(f"{label} is not an object")
    for field, wanted in expected.items():
        if value.get(field) != wanted:
            raise ChainFailure(f"{label}.{field}={value.get(field)!r}; expected {wanted!r}")


def _completed(value: Any) -> bool:
    return str(value or "").lower() in {"completed", "completed_actual", "success", "succeeded"}


def _validate_handoff(path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    handoff, handoff_record, _ = _read(path, "ROOT345 V3 handoff")
    if handoff.get("schema") != HANDOFF_SCHEMA:
        raise ChainFailure(f"handoff schema mismatch: {handoff.get('schema')!r}")
    rows = _rows(handoff, "rows", "ROOT345 handoff")
    if handoff.get("execution_allowed") is not False:
        raise ChainFailure("handoff is not execution-disabled source metadata")
    producer: dict[str, dict[str, Any]] = {}; products: dict[str, dict[str, Any]] = {}
    for key, row in rows.items():
        if row.get("edge_status") != EDGE_STATUS:
            raise ChainWaiting(f"{key} producer edge is not terminal: {row.get('edge_status')!r}")
        expected = _identity(row)
        req_path, req_record, request = _read_record(row.get("producer_request"), f"{key} producer request")
        proof_path, proof_record, proof = _read_record(row.get("producer_proof"), f"{key} producer proof")
        receipt_path, receipt_record, receipt = _read_record(row.get("producer_receipt"), f"{key} producer receipt")
        _same(request, expected, f"{key} request"); _same(proof, expected, f"{key} proof")
        if proof.get("status") != PROOF_STATUS:
            raise ChainFailure(f"{key} proof status is not exact terminal product status")
        if request.get("schema") != REQUEST_SCHEMA or request.get("cpu_task_kind") != "gencase":
            raise ChainFailure(f"{key} producer request is not a GenCase request")
        if request.get("execution_allowed") is not True or request.get("source_only") is True:
            raise ChainFailure(f"{key} producer request remains source-only")
        if receipt.get("schema") != RECEIPT_SCHEMA or not _completed(receipt.get("status")) or receipt.get("returncode") != 0:
            raise ChainFailure(f"{key} receipt is not completed with returncode 0")
        if receipt.get("request") != request or receipt.get("request_sha256") != req_record["sha256"]:
            raise ChainFailure(f"{key} receipt does not bind raw producer request bytes")
        if proof.get("request_sha256") not in (None, req_record["sha256"]):
            raise ChainFailure(f"{key} proof request SHA does not bind request bytes")
        if receipt.get("output_root") not in (None, request.get("output_root")):
            raise ChainFailure(f"{key} receipt output_root differs from request")
        row_products = row.get("product_records")
        if not isinstance(row_products, dict):
            raise ChainFailure(f"{key} lacks deferred product_records")
        for role in ("generated_xml", "fluid_vtk", "bound_vtk", "native_bi4"):
            record = row_products.get(role)
            if not isinstance(record, dict) or not isinstance(record.get("path"), str):
                raise ChainFailure(f"{key} lacks deferred {role}")
        producer[key] = {"request": request, "request_record": req_record, "proof": proof,
                         "proof_record": proof_record, "receipt": receipt, "receipt_record": receipt_record,
                         "request_path": str(req_path), "proof_path": str(proof_path), "receipt_path": str(receipt_path)}
        products[key] = row_products
    return handoff, handoff_record, producer, products


def _validate_header(path: Path, handoff_rows: dict[str, dict[str, Any]],
                     producer: dict[str, dict[str, Any]], products: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
    report, report_record, _ = _read(path, "native-header report")
    if report.get("schema") not in HEADER_SCHEMAS or report.get("status") != HEADER_REPORT_STATUS:
        raise ChainFailure("native-header report schema/status is not terminal V2/V3")
    if report.get("xml_fallback") is not False:
        raise ChainFailure("native-header report does not disable XML mass fallback")
    report_rows = _rows(report, "cases", "native-header report")
    manifest_ref = report.get("manifest")
    manifest_path = manifest_ref.get("path") if isinstance(manifest_ref, dict) else manifest_ref
    if not isinstance(manifest_path, str):
        raise ChainFailure("native-header report lacks input manifest path")
    header_manifest, header_record, _ = _read(manifest_path, "native-header input manifest")
    if header_manifest.get("schema") != HEADER_MANIFEST_SCHEMA or header_manifest.get("status") != HEADER_MANIFEST_STATUS:
        raise ChainFailure("native-header input manifest schema/status mismatch")
    input_rows = _rows(header_manifest, "cases", "native-header input manifest")
    joined: dict[str, dict[str, Any]] = {}
    for key in ROW_KEYS:
        handoff_row = handoff_rows[key]; expected = _identity(handoff_row)
        input_row = input_rows[key]; output_row = report_rows[key]
        _same(input_row, expected, f"{key} header input identity")
        for role, path_key in (("producer_request", "request_path"), ("gencase_receipt", "receipt_path")):
            value = input_row.get(role)
            if not isinstance(value, dict) or _abs(value.get("path", "")) != _abs(producer[key][path_key]):
                raise ChainFailure(f"{key} header input {role} does not bind producer edge")
        native = products[key]["native_bi4"]
        input_native = input_row.get("native_bi4")
        native_path = _abs(native["path"])
        if not isinstance(input_native, dict) or _abs(input_native.get("path", "")) != native_path:
            raise ChainFailure(f"{key} header input BI4 path does not bind product map")
        if output_row.get("row_key") != key or _abs(output_row.get("source_path", "")) != native_path:
            raise ChainFailure(f"{key} header report source path does not bind product map")
        source_sha = output_row.get("source_sha256")
        if not _valid_sha(source_sha):
            raise ChainFailure(f"{key} header report lacks concrete source SHA")
        product_sha = native.get("sha256")
        if _valid_sha(product_sha) and str(product_sha).lower() != str(source_sha).lower():
            raise ChainFailure(f"{key} header source SHA differs from product record")
        guard = output_row.get("source_guard")
        if not isinstance(guard, dict) or guard.get("sha256_pre") != source_sha or guard.get("sha256_post") != source_sha:
            raise ChainFailure(f"{key} header source pre/post SHA is not stable")
        if guard.get("stat_pre") != guard.get("stat_post"):
            raise ChainFailure(f"{key} header source pre/post stat is not stable")
        status = output_row.get("status")
        if status not in HEADER_ROW_STATUSES:
            raise ChainFailure(f"{key} unsupported header row status: {status!r}")
        if status == "PASS_NATIVE_HEADER_FIELDS":
            for field in ("massfluid", "dp"):
                value = output_row.get(field)
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                    raise ChainFailure(f"{key} header PASS lacks finite {field}")
        joined[key] = {"row_key": key, "status": status, "source_path": str(native_path),
                       "source_sha256": str(source_sha), "massfluid": output_row.get("massfluid"),
                       "massbound": output_row.get("massbound"), "dp": output_row.get("dp"),
                       "time_s": output_row.get("time_s"), "source_guard": guard}
    return report, report_record, header_record, joined


def _write_new(path: Path, value: Any) -> None:
    path = _abs(path)
    if path.exists() or path.is_symlink():
        raise ChainFailure(f"refusing overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def _owner_path(product: dict[str, Any], owner: Path | None) -> Path:
    if owner is not None:
        return _abs(owner)
    value = product.get("owner_report")
    if isinstance(value, dict) and isinstance(value.get("path"), str):
        return _abs(value["path"])
    raise ChainFailure("owner report path is absent from CLI and product map")


def prepare(handoff_path: Path, output_dir: Path, *, owner_report: Path | None = None,
            product_map: Path | None = None) -> dict[str, Any]:
    handoff, handoff_record, _producer, _products = _validate_handoff(handoff_path)
    if product_map is None:
        value = handoff.get("product_map")
        product_map = _abs(value["path"]) if isinstance(value, dict) and isinstance(value.get("path"), str) else None
    if product_map is None:
        raise ChainFailure("prepare needs product map")
    product, product_record, _ = _read(product_map, "ROOT345 product map")
    owner_path = _owner_path(product, owner_report)
    owner, owner_record, _ = _read(owner_path, "owner source audit")
    if owner.get("schema") != "ds02.stage2.three-sentinel.owner-grid-source-audit.v3":
        raise ChainFailure("owner report schema mismatch")
    output_dir = _abs(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ChainFailure(f"refusing nonempty output: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    source_records = [handoff_record, product_record, owner_record, _record(Path(__file__), "chain V1 source")]
    chain = {"schema": SCHEMA, "status": "WAITING_FOR_NATIVE_HEADER_REPORT_BEFORE_INITIAL_SUPPORT_MATERIALIZATION",
             "source_status": "SOURCE_ONLY_NO_PRODUCTION_CREDIT", "handoff": handoff_record,
             "product_map": product_record, "owner_report": owner_record,
             "header_gate": {"status": "WAITING_FOR_PARENT_NATIVE_HEADER_REPORT", "report": None, "rows": 0},
             "support_gate": {"status": "NOT_MATERIALIZED_UNTIL_HEADER_GATE", "manifest": None, "request": None},
             "calibration_gate": {"status": "WAITING_FOR_INITIAL_SUPPORT_REPORT", "package": None},
             "source_records": source_records, "execution_allowed": False, "gencase_launch": False,
             "solver_launch": False, "scientific_qualification": dict(UNKNOWN),
             "scientific_scope": {"header_mass_decoder_metadata_only": True, "xml_mass_fallback": False,
                                  "native_header_probe_not_promoted_to_position_idp": True, "world_axis": "UNKNOWN",
                                  "neighbor_grid_truth": False, "interpolation": False}}
    chain_path = output_dir / "chain-manifest.json"; _write_new(chain_path, chain)
    chain_record = _record(chain_path, "chain manifest")
    request = {"schema": REQUEST_SCHEMA, "variant_schema": SCHEMA, "status": chain["status"],
               "family_id": "infra", "cpu_task_kind": "audit", "case_id": "THREE_SENTINEL_HEADER_SUPPORT_CHAIN_V1",
               "attempt_id": "PARENT_ASSIGNED_AFTER_NATIVE_HEADER", "execution_allowed": False,
               "launch_disabled": True, "gencase_launch": False, "solver_launch": False,
               "command": [str(Path(__file__).resolve()), "--materialize", "--handoff", str(_abs(handoff_path)),
                           "--owner-report", str(owner_path), "--product-map", str(_abs(product_map)),
                           "--header-report", "{header_report}", "--output-dir", str(output_dir)],
               "input_records": {r["path"]: r for r in [*source_records, chain_record]},
               "input_files": sorted({r["path"] for r in [*source_records, chain_record]}),
               "input_sha256": {r["path"]: r["sha256"] for r in [*source_records, chain_record]},
               "manifest": chain_record, "deferred_input_records": [{"role": "ROOT345_PRODUCTS",
               "status": "PARENT_AFTER_RESERVATION_FULL_SHA_STAT_REQUIRED", "payload_read_by_builder": False}],
               "resource_scope": {"cpu_threads": 1, "memory_bytes": 4 * 1024**3, "max_wall_seconds": 1800,
                                  "scratch_bytes": 512 * 1024**2, "static_metadata_cap_bytes": CAP},
               "scientific_qualification": dict(UNKNOWN)}
    request_path = output_dir / "chain-request.json"; _write_new(request_path, request)
    return {"status": chain["status"], "chain_path": str(chain_path), "request_path": str(request_path), "chain": chain}


def _patch_support(support_dir: Path, report_record: dict[str, Any], header_record: dict[str, Any],
                   header_rows: dict[str, dict[str, Any]]) -> tuple[Path, Path]:
    manifest_path = support_dir / "owner-grid-initial-support-manifest-v1.json"
    request_path = support_dir / "owner-grid-initial-support-request-v1.json"
    manifest, _, _ = _read(manifest_path, "materialized support manifest")
    request, _, _ = _read(request_path, "materialized support request")
    if manifest.get("schema") != SUPPORT_MANIFEST_SCHEMA:
        raise ChainFailure("support builder did not preserve V1 manifest schema")
    cases = _rows(manifest, "cases", "materialized support manifest")
    for key, case in cases.items():
        # Do not replace native_header_probe: it has a stricter position/Idp
        # contract.  This separate record is joined by the independent stage.
        case["native_header_report"] = report_record
        case["native_header_row"] = header_rows[key]
    manifest["cases"] = list(cases.values())
    manifest["header_gate"] = {"status": "VERIFIED_NATIVE_HEADER_REPORT_IDENTITY_ONLY", "report": report_record,
                                 "input_manifest": header_record, "rows": len(header_rows), "xml_mass_fallback": False}
    manifest["chain_schema"] = SCHEMA; manifest["scientific_qualification"] = dict(UNKNOWN)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    manifest_record = _record(manifest_path, "final support manifest")
    records = request.get("input_records")
    if not isinstance(records, dict):
        raise ChainFailure("support request input_records is malformed")
    records = {str(k): v for k, v in records.items() if isinstance(v, dict) and isinstance(v.get("path"), str)}
    for rec in (report_record, header_record, manifest_record):
        records[rec["path"]] = rec
    request["input_records"] = {key: records[key] for key in sorted(records)}
    request["input_files"] = sorted(records)
    request["input_sha256"] = {key: records[key]["sha256"] for key in sorted(records) if _valid_sha(records[key].get("sha256"))}
    request["manifest"] = manifest_record; request["header_gate"] = manifest["header_gate"]
    request["chain_schema"] = SCHEMA; request["execution_allowed"] = False; request["launch_disabled"] = True
    request_path.write_text(json.dumps(request, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest_path, request_path


def materialize(handoff_path: Path, owner_report: Path, product_map: Path, header_report: Path,
                output_dir: Path) -> dict[str, Any]:
    handoff, handoff_record, producer, products = _validate_handoff(handoff_path)
    product, product_record, _ = _read(product_map, "ROOT345 product map")
    if product.get("schema") != "ds02.stage2.three-sentinel.owner-grid-gencase-product-map.v2":
        raise ChainFailure("ROOT345 product map schema mismatch")
    map_rows = _rows(product, "products", "ROOT345 product map")
    handoff_rows = _rows(handoff, "rows", "ROOT345 handoff")
    for key, row in map_rows.items():
        _same(row, {k: handoff_rows[key][k] for k in ("sentinel_id", "grid_label", "family_id", "physical_case_id", "case_id", "attempt_id")}, f"{key} product row")
        if row.get("producer_request", {}).get("path") != handoff_rows[key].get("producer_request", {}).get("path"):
            raise ChainFailure(f"{key} product row producer request does not bind handoff")
    owner_path = _owner_path(product, _abs(owner_report))
    owner, owner_record, _ = _read(owner_path, "owner source audit")
    if owner.get("schema") != "ds02.stage2.three-sentinel.owner-grid-source-audit.v3":
        raise ChainFailure("owner report schema mismatch")
    report, report_record, header_record, header_rows = _validate_header(_abs(header_report), handoff_rows, producer, products)
    output_dir = _abs(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ChainFailure(f"refusing nonempty output: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True); support_dir = output_dir / "support"
    try:
        support_result = SUPPORT.build(owner_path, _abs(product_map), support_dir)
    except Exception as exc:
        raise ChainFailure(f"initial-support source builder failed after header gate: {exc}") from exc
    support_manifest, support_request = _patch_support(support_dir, report_record, header_record, header_rows)
    support_manifest_record = _record(support_manifest, "materialized support manifest")
    support_request_record = _record(support_request, "materialized support request")
    chain = {"schema": SCHEMA, "status": "READY_FOR_PARENT_INITIAL_SUPPORT_AFTER_NATIVE_HEADER_REPORT",
             "source_status": "SOURCE_BOUND_HEADER_GATE_NO_SCIENTIFIC_CREDIT", "handoff": handoff_record,
             "product_map": product_record, "owner_report": owner_record,
             "header_gate": {"status": "VERIFIED_NATIVE_HEADER_REPORT_IDENTITY_ONLY", "report": report_record,
                             "input_manifest": header_record, "rows": 9,
                             "row_status_counts": {s: sum(v["status"] == s for v in header_rows.values()) for s in sorted(HEADER_ROW_STATUSES)},
                             "xml_mass_fallback": False},
             "support_gate": {"status": "READY_FOR_PARENT_GUARDED_INITIAL_SUPPORT", "manifest": support_manifest_record,
                              "request": support_request_record},
             "calibration_gate": {"status": "WAITING_FOR_INITIAL_SUPPORT_REPORT", "package": None},
             "source_records": [handoff_record, product_record, owner_record, report_record, header_record,
                                support_manifest_record, support_request_record, _record(Path(__file__), "chain V1 source")],
             "execution_allowed": False, "gencase_launch": False, "solver_launch": False,
             "scientific_qualification": dict(UNKNOWN),
             "scientific_scope": {"header_mass_decoder_metadata_only": True, "native_header_probe_not_promoted_to_position_idp": True,
                                  "xml_mass_fallback": False, "world_axis": "UNKNOWN", "neighbor_grid_truth": False,
                                  "interpolation": False, "support_failures_remain_separate": True}}
    chain_path = output_dir / "chain-manifest.json"; _write_new(chain_path, chain)
    chain_record = _record(chain_path, "materialized chain manifest")
    request = {"schema": REQUEST_SCHEMA, "variant_schema": SCHEMA, "status": chain["status"], "family_id": "infra",
               "cpu_task_kind": "audit", "case_id": "THREE_SENTINEL_INITIAL_SUPPORT_AFTER_HEADER_V1",
               "attempt_id": "PARENT_ASSIGNED_AFTER_HEADER_REPORT", "execution_allowed": False, "launch_disabled": True,
               "gencase_launch": False, "solver_launch": False, "command": list(support_result["request"].get("command", [])),
               "independent_verifier": [str(Path(__file__).resolve()), "--verify-support", "--chain", str(chain_path), "--support-report", "{support_report}"],
               "input_records": {r["path"]: r for r in [*chain["source_records"], chain_record]},
               "input_files": sorted({r["path"] for r in [*chain["source_records"], chain_record]}),
               "input_sha256": {r["path"]: r["sha256"] for r in [*chain["source_records"], chain_record]},
               "manifest": chain_record, "deferred_input_records": handoff.get("deferred_input_records", []),
               "resource_scope": {"cpu_threads": 1, "memory_bytes": 4 * 1024**3, "max_wall_seconds": 1800,
                                  "scratch_bytes": 1024**3, "static_metadata_cap_bytes": CAP},
               "scientific_qualification": dict(UNKNOWN)}
    request_path = output_dir / "chain-request.json"; _write_new(request_path, request)
    return {"status": chain["status"], "chain_path": str(chain_path), "request_path": str(request_path),
            "support_manifest": str(support_manifest), "support_request": str(support_request), "header": report}


def verify_support(chain_path: Path, support_report: Path, output: Path | None = None) -> dict[str, Any]:
    chain, chain_record, _ = _read(chain_path, "materialized chain manifest")
    if chain.get("schema") != SCHEMA or chain.get("status") != "READY_FOR_PARENT_INITIAL_SUPPORT_AFTER_NATIVE_HEADER_REPORT":
        raise ChainFailure("chain is not header-gated")
    report, report_record, _ = _read(support_report, "initial-support report")
    if report.get("schema") != SUPPORT_REPORT_SCHEMA:
        raise ChainFailure("support report schema mismatch")
    support_rows = _rows(report, "cases", "initial-support report")
    for row in support_rows.values():
        if row.get("status") not in {"PASS_INITIAL_SUPPORT_DIAGNOSTIC", "FAILED_INITIAL_SUPPORT_DIAGNOSTIC"}:
            raise ChainFailure(f"support row {row.get('row_key')} has no terminal status")
    manifest = report.get("manifest")
    expected = chain["support_gate"]["manifest"]
    if not isinstance(manifest, dict) or manifest.get("path") != expected.get("path") or manifest.get("sha256") != expected.get("sha256"):
        raise ChainFailure("support report manifest does not bind materialized support manifest")
    header, header_record, _ = _read(chain["header_gate"]["report"]["path"], "chain header report")
    if header_record["sha256"] != chain["header_gate"]["report"].get("sha256"):
        raise ChainFailure("header report changed after materialization")
    header_rows = _rows(header, "cases", "chain header report")
    result = {"schema": "ds02.stage2.three-sentinel.header-support-independent-verification.v1",
              "status": "VERIFIED_HEADER_SUPPORT_IDENTITY_AND_TERMINAL_DIAGNOSTICS", "chain": chain_record,
              "header_report": header_record, "support_report": report_record,
              "rows": {key: {"header": header_rows[key].get("status"), "support": support_rows[key].get("status")} for key in ROW_KEYS},
              "case_counts": {"header_pass": sum(r.get("status") == "PASS_NATIVE_HEADER_FIELDS" for r in header_rows.values()),
                              "header_unknown": sum(r.get("status") == "UNKNOWN_NATIVE_HEADER_FIELDS_NOT_EXPOSED_BY_DECODER" for r in header_rows.values()),
                              "support_pass": sum(r.get("status") == "PASS_INITIAL_SUPPORT_DIAGNOSTIC" for r in support_rows.values()),
                              "support_failed": sum(r.get("status") == "FAILED_INITIAL_SUPPORT_DIAGNOSTIC" for r in support_rows.values())},
              "scientific_qualification": dict(UNKNOWN), "scientific_scope": {"continuous_owner": "UNKNOWN",
              "world_axis": "UNKNOWN", "xml_mass_fallback": False, "neighbor_grid_truth": False, "interpolation": False}}
    if output is not None:
        _write_new(output, result)
    return result


def _write_replace(path: Path, value: Any) -> None:
    """Write a file owned by this finalization attempt, never a source input."""
    path = _abs(path)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ChainFailure(f"refusing to replace non-regular output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
                    encoding="utf-8")


def finalize(chain_path: Path, support_report: Path, output_dir: Path) -> dict[str, Any]:
    """Connect the terminal support report to the execution-disabled calibration packages.

    The calibration builder is deliberately invoked only after ``verify_support``
    has joined the materialized support manifest and the immutable native-header
    report.  A failed support case is retained in the package and leaves the
    package WAITING; it can never be promoted to a solver request by this stage.
    This keeps header metadata, initial-support diagnostics, and calibration
    admission as one auditable parent chain without granting scientific credit.
    """
    verification = verify_support(chain_path, support_report)
    chain, chain_record, _ = _read(chain_path, "materialized chain manifest")
    support_report_value, support_report_record, _ = _read(support_report, "initial-support report")
    output_dir = _abs(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ChainFailure(f"refusing nonempty finalization output: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    calibration_dir = output_dir / "calibration"
    try:
        calibration_result = CALIBRATION.build(_abs(chain["handoff"]["path"]), calibration_dir)
    except Exception as exc:
        raise ChainFailure(f"calibration source builder failed after support verification: {exc}") from exc

    support_failures = int(verification["case_counts"]["support_failed"])
    support_ready = support_failures == 0
    package = calibration_result.get("package")
    if not isinstance(package, dict):
        package_path = _abs(calibration_result["package_path"])
        package, _, _ = _read(package_path, "calibration parent package")
    package_path = _abs(calibration_result["package_path"])
    package["schema"] = "ds02.stage2.three-sentinel.native-header-initial-support-calibration-package.v1"
    package["status"] = ("READY_FOR_PARENT_CALIBRATION_AFTER_INITIAL_SUPPORT"
                          if support_ready else "WAITING_FOR_INITIAL_SUPPORT_SUCCESS")
    package["chain_schema"] = SCHEMA
    package["chain_manifest"] = chain_record
    package["header_report"] = chain["header_gate"]["report"]
    package["support_report"] = support_report_record
    package["support_verification"] = verification
    package["scientific_qualification"] = dict(UNKNOWN)
    package["execution_allowed"] = False
    package["solver_launch"] = False
    package["gencase_launch"] = False
    package["source_only"] = True
    package["production_payload_read_by_builder"] = False
    _write_replace(package_path, package)
    package_record = _record(package_path, "final calibration package")

    final_packages: list[dict[str, Any]] = []
    for item in package.get("packages", []):
        if not isinstance(item, dict):
            raise ChainFailure("calibration package contains malformed target")
        manifest_path = _abs(item["manifest"])
        request_path = _abs(item["request"])
        manifest, _, _ = _read(manifest_path, f"{item.get('sentinel_id')} calibration manifest")
        request, _, _ = _read(request_path, f"{item.get('sentinel_id')} calibration request")
        manifest["chain_schema"] = SCHEMA
        manifest["chain_manifest"] = chain_record
        manifest["header_report"] = chain["header_gate"]["report"]
        manifest["initial_support_report"] = support_report_record
        manifest["support_verification"] = verification
        manifest["status"] = ("READY_FOR_PARENT_GUARDED_THREE_SENTINEL_CALIBRATION"
                               if support_ready else "WAITING_FOR_INITIAL_SUPPORT_SUCCESS")
        manifest["execution_allowed"] = False
        manifest["solver_launch"] = False
        manifest["scientific_qualification"] = dict(UNKNOWN)
        _write_replace(manifest_path, manifest)
        manifest_record = _record(manifest_path, f"{item.get('sentinel_id')} final calibration manifest")

        request["chain_schema"] = SCHEMA
        request["chain_manifest"] = chain_record
        request["header_report"] = chain["header_gate"]["report"]
        request["initial_support_report"] = support_report_record
        request["support_verification"] = verification
        request["status"] = manifest["status"]
        request["execution_allowed"] = False
        request["launch_disabled"] = True
        request["source_only"] = True
        request["solver_launch"] = False
        request["scientific_qualification"] = dict(UNKNOWN)
        records = {str(key): value for key, value in request.get("input_records", {}).items()
                   if isinstance(value, dict) and isinstance(value.get("path"), str)}
        for record in (chain_record, package_record, support_report_record, manifest_record):
            records[record["path"]] = record
        request["input_records"] = {key: records[key] for key in sorted(records)}
        request["input_files"] = sorted(records)
        request["input_sha256"] = {key: records[key]["sha256"] for key in sorted(records)
                                    if _valid_sha(records[key].get("sha256"))}
        request["manifest"] = manifest_record
        _write_replace(request_path, request)
        request_record = _record(request_path, f"{item.get('sentinel_id')} final calibration request")
        final_packages.append({"sentinel_id": item.get("sentinel_id"), "manifest": manifest_record,
                               "request": request_record, "status": manifest["status"],
                               "scientific_qualification": dict(UNKNOWN)})

    package["packages"] = final_packages
    package["package_record"] = package_record
    _write_replace(package_path, package)
    package_record = _record(package_path, "final calibration package after requests")

    final_manifest = {"schema": SCHEMA, "status": package["status"], "source_status": "SOURCE_ONLY_NO_SCIENTIFIC_CREDIT",
                      "chain": chain_record, "header_report": chain["header_gate"]["report"],
                      "support_report": support_report_record, "support_verification": verification,
                      "calibration_package": package_record, "packages": final_packages,
                      "execution_allowed": False, "solver_launch": False, "gencase_launch": False,
                      "scientific_qualification": dict(UNKNOWN),
                      "scientific_scope": {"xml_mass_fallback": False, "native_header_mass_semantics": "per_particle_or_unknown",
                                           "world_axis": "UNKNOWN", "continuous_owner": "UNKNOWN",
                                           "neighbor_grid_truth": False, "interpolation": False}}
    final_manifest_path = output_dir / "final-chain-manifest.json"
    _write_new(final_manifest_path, final_manifest)
    final_manifest_record = _record(final_manifest_path, "final chain manifest")
    final_request = {"schema": REQUEST_SCHEMA, "variant_schema": SCHEMA, "status": package["status"],
                     "family_id": "infra", "cpu_task_kind": "audit",
                     "case_id": "THREE_SENTINEL_HEADER_SUPPORT_CALIBRATION_CHAIN_FINAL_V1",
                     "attempt_id": "PARENT_ASSIGNED_AFTER_SUPPORT_REPORT", "execution_allowed": False,
                     "launch_disabled": True, "solver_launch": False, "gencase_launch": False,
                     "command": [str(Path(__file__).resolve()), "--finalize", "--chain", str(_abs(chain_path)),
                                 "--support-report", str(_abs(support_report)), "--output-dir", str(output_dir)],
                     "calibration_requests": final_packages, "manifest": final_manifest_record,
                     "input_records": {r["path"]: r for r in [chain_record, package_record, final_manifest_record,
                                                                  support_report_record]},
                     "input_files": sorted({r["path"] for r in [chain_record, package_record, final_manifest_record,
                                                                    support_report_record]}),
                     "input_sha256": {r["path"]: r["sha256"] for r in [chain_record, package_record,
                                                                            final_manifest_record, support_report_record]},
                     "resource_scope": {"cpu_threads": 1, "memory_bytes": 4 * 1024**3, "max_wall_seconds": 1800,
                                        "scratch_bytes": 1024**3, "static_metadata_cap_bytes": CAP},
                     "scientific_qualification": dict(UNKNOWN)}
    final_request_path = output_dir / "final-chain-request.json"
    _write_new(final_request_path, final_request)
    return {"status": package["status"], "final_manifest": str(final_manifest_path),
            "final_request": str(final_request_path), "package": str(package_path),
            "support_verification": verification}


def _fixture(root: Path) -> tuple[Path, Path, Path, Path]:
    """Create a tiny actual-shaped chain fixture; no production files are read."""
    owner, old_product = SUPPORT.V1._fixture_owner(root / "owner")
    old = json.loads(old_product.read_text()); products = []; producer_dir = root / "producer"; producer_dir.mkdir(parents=True)
    for item in old["products"]:
        sid, grid = item["sentinel_id"], item["grid_label"]; case = root / "cases" / f"{sid}_{grid}"; case.mkdir(parents=True)
        request = {"schema": REQUEST_SCHEMA, "sentinel_id": sid, "grid_label": grid, "family_id": sid[:2],
                   "physical_case_id": f"P-{sid}-{grid}", "case_id": f"C-{sid}-{grid}", "attempt_id": f"A-{sid}-{grid}",
                   "cpu_task_kind": "gencase", "execution_allowed": True, "source_only": False,
                   "launch_disabled": False, "output_root": str(case)}
        request_path = producer_dir / f"{sid}_{grid}.request.json"; request_path.write_text(json.dumps(request, sort_keys=True) + "\n")
        receipt = {"schema": RECEIPT_SCHEMA, "status": "completed", "returncode": 0, "request": request,
                   "request_sha256": _sha(request_path.read_bytes()), "output_root": str(case),
                   "input_hashes_at_launch": {}, "input_hashes_after_run": {}}
        receipt_path = case / "execution-receipt.json"; receipt_path.write_text(json.dumps(receipt, sort_keys=True) + "\n")
        product_values = {name: {"path": str(case / f"{name}.payload")} for name in ("generated_xml", "fluid_vtk", "bound_vtk", "native_bi4")}
        proof = {"schema": "ds02.stage2.root-owner-grid-gencase-proof.v2", "status": PROOF_STATUS,
                 **{f: request[f] for f in ("sentinel_id", "grid_label", "family_id", "physical_case_id", "case_id", "attempt_id")},
                 "request_sha256": _sha(request_path.read_bytes()), "products": product_values}
        proof_path = producer_dir / f"{sid}_{grid}.proof.json"; proof_path.write_text(json.dumps(proof, sort_keys=True) + "\n")
        rec = lambda p: {"path": str(p), "sha256": _sha(p.read_bytes()), "stat": _stat(p)}
        products.append({**item, **{f: request[f] for f in ("sentinel_id", "grid_label", "family_id", "physical_case_id", "case_id", "attempt_id")},
                         "status": "ACTUAL_GENCASE_PRODUCTS_AWAIT_INITIAL_SUPPORT_AUDIT", "producer_request": rec(request_path),
                         "actual_producer_proof": rec(proof_path), "gencase_receipt": rec(receipt_path)})
    product_path = root / "product-map.json"; product_path.write_text(json.dumps({"schema": "ds02.stage2.three-sentinel.owner-grid-gencase-product-map.v2",
        "status": "NINE_ACTUAL_GENCASE_PRODUCTS_DEFERRED_NATIVE_HASH_INITIAL_AUDIT_REQUIRED", "owner_report": {"path": str(owner)}, "products": products}, indent=2, sort_keys=True) + "\n")
    # Add the owner record's digest after writing the map; the fixture only needs
    # a path because prepare/materialize explicitly reads and binds the file.
    hrows = []
    for row in products:
        fields = ("sentinel_id", "grid_label", "family_id", "physical_case_id", "case_id", "attempt_id")
        hrows.append({**{f: row[f] for f in fields}, "edge_status": EDGE_STATUS,
                      "producer_request": row["producer_request"], "producer_proof": row["actual_producer_proof"],
                      "producer_receipt": row["gencase_receipt"], "product_records": {n: row[n] for n in ("generated_xml", "fluid_vtk", "bound_vtk", "native_bi4")}})
    handoff_path = root / "handoff.json"; handoff_path.write_text(json.dumps({"schema": HANDOFF_SCHEMA,
        "status": "READY_FOR_PARENT_NATIVE_HEADER_V3_AND_INITIAL_SUPPORT", "execution_allowed": False,
        "product_map": {"path": str(product_path)}, "rows": hrows}, indent=2, sort_keys=True) + "\n")
    header_manifest = root / "header-manifest.json"; input_rows = []
    report_rows = []
    for row in products:
        fields = ("sentinel_id", "grid_label", "family_id", "physical_case_id", "case_id", "attempt_id")
        native = Path(row["native_bi4"]["path"]); native.write_bytes(b"tiny-bi4"); st = _stat(native); sha = _sha(native.read_bytes())
        input_rows.append({**{f: row[f] for f in fields}, "row_key": f"{row['sentinel_id']}:{row['grid_label']}",
                           "producer_request": row["producer_request"], "gencase_receipt": row["gencase_receipt"], "native_bi4": row["native_bi4"]})
        report_rows.append({"schema": "ds02.stage2.native-header-probe.v2", "status": "PASS_NATIVE_HEADER_FIELDS",
                           "row_key": f"{row['sentinel_id']}:{row['grid_label']}", "source_path": str(native), "source_sha256": sha,
                           "source_guard": {"sha256_pre": sha, "sha256_post": sha, "stat_pre": st, "stat_post": st},
                           "massfluid": .01, "massbound": .02, "dp": .01, "time_s": 0.0})
    header_manifest.write_text(json.dumps({"schema": HEADER_MANIFEST_SCHEMA, "status": HEADER_MANIFEST_STATUS, "cases": input_rows}, indent=2, sort_keys=True) + "\n")
    header_report = root / "header-report.json"; header_report.write_text(json.dumps({"schema": "ds02.stage2.native-header-probe.v3",
        "status": HEADER_REPORT_STATUS, "manifest": str(header_manifest), "cases": report_rows,
        "native_mass_source": "decoder-produced BI4 metadata only", "xml_fallback": False}, indent=2, sort_keys=True) + "\n")
    # Correct owner_report record in the product map (source package behavior).
    product = json.loads(product_path.read_text()); product["owner_report"] = _record(owner, "fixture owner report")
    product_path.write_text(json.dumps(product, indent=2, sort_keys=True) + "\n")
    return owner, product_path, handoff_path, header_report


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="header-support-chain-v1-") as td:
        root = Path(td); owner, product, handoff, header = _fixture(root)
        result = materialize(handoff, owner, product, header, root / "out")
        assert result["status"] == "READY_FOR_PARENT_INITIAL_SUPPORT_AFTER_NATIVE_HEADER_REPORT"
        chain = json.loads(Path(result["chain_path"]).read_text())
        assert chain["header_gate"]["rows"] == 9 and Path(result["support_manifest"]).is_file()
        manifest_record = _record(Path(result["support_manifest"]), "fixture support manifest")
        support = root / "support-report.json"
        support.write_text(json.dumps({"schema": SUPPORT_REPORT_SCHEMA,
            "status": "COMPLETE_PARTIAL_OWNER_GRID_INITIAL_SUPPORT_DIAGNOSTICS", "manifest": manifest_record,
            "cases": [{"row_key": key, "status": "FAILED_INITIAL_SUPPORT_DIAGNOSTIC" if i == 0 else "PASS_INITIAL_SUPPORT_DIAGNOSTIC"}
                       for i, key in enumerate(ROW_KEYS)]}, indent=2, sort_keys=True) + "\n")
        check = verify_support(Path(result["chain_path"]), support)
        assert check["case_counts"]["support_failed"] == 1
        final = finalize(Path(result["chain_path"]), support, root / "final")
        assert final["status"] == "WAITING_FOR_INITIAL_SUPPORT_SUCCESS"
        assert Path(final["final_manifest"]).is_file() and Path(final["final_request"]).is_file()
        tampered = json.loads(header.read_text()); tampered["cases"][0]["source_sha256"] = "0" * 64
        bad = root / "bad-header.json"; bad.write_text(json.dumps(tampered, sort_keys=True) + "\n")
        try:
            materialize(handoff, owner, product, bad, root / "bad-out")
        except ChainFailure:
            pass
        else:
            raise AssertionError("changed header source SHA was accepted")
    print("PASS_THREE_SENTINEL_HEADER_SUPPORT_CALIBRATION_CHAIN_TINY_NO_PRODUCTION_CREDIT")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__); group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--self-test", action="store_true"); group.add_argument("--prepare", action="store_true")
    group.add_argument("--materialize", action="store_true"); group.add_argument("--verify-support", action="store_true")
    group.add_argument("--finalize", action="store_true")
    parser.add_argument("--handoff", type=Path); parser.add_argument("--owner-report", type=Path); parser.add_argument("--product-map", type=Path)
    parser.add_argument("--header-report", type=Path); parser.add_argument("--chain", type=Path); parser.add_argument("--support-report", type=Path); parser.add_argument("--output-dir", type=Path); parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.self_test: self_test(); return 0
        if args.prepare:
            if args.handoff is None or args.output_dir is None: parser.error("--prepare requires --handoff and --output-dir")
            value = prepare(args.handoff, args.output_dir, owner_report=args.owner_report, product_map=args.product_map)
            print(json.dumps({"status": value["status"], "chain": value["chain_path"], "request": value["request_path"], "scientific_credit": 0}, sort_keys=True)); return 0
        if args.materialize:
            if None in (args.handoff, args.owner_report, args.product_map, args.header_report, args.output_dir): parser.error("--materialize requires five paths")
            value = materialize(args.handoff, args.owner_report, args.product_map, args.header_report, args.output_dir)
            print(json.dumps({"status": value["status"], "chain": value["chain_path"], "support_manifest": value["support_manifest"], "request": value["request_path"], "scientific_credit": 0}, sort_keys=True)); return 0
        if args.verify_support:
            if args.chain is None or args.support_report is None: parser.error("--verify-support requires --chain and --support-report")
            value = verify_support(args.chain, args.support_report, args.output)
            print(json.dumps({"status": value["status"], "case_counts": value["case_counts"], "scientific_credit": 0}, sort_keys=True)); return 0
        if args.finalize:
            if args.chain is None or args.support_report is None or args.output_dir is None:
                parser.error("--finalize requires --chain, --support-report and --output-dir")
            value = finalize(args.chain, args.support_report, args.output_dir)
            print(json.dumps({"status": value["status"], "final_manifest": value["final_manifest"],
                              "final_request": value["final_request"], "scientific_credit": 0}, sort_keys=True)); return 0
        parser.error("select an operation")
    except (ChainFailure, ChainWaiting, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_THREE_SENTINEL_HEADER_SUPPORT_CALIBRATION_CHAIN_V1: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
