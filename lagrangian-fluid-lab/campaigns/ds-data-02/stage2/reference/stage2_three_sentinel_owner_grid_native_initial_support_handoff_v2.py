#!/usr/bin/env python3
"""Strict ROOT345 product-to-initial-support handoff (additive V2).

The older handoff was useful for preparing a request, but it accepted
substring statuses and did not close the producer request -> execution
receipt -> terminal proof edge.  This module keeps that source package
separate and makes the edge explicit.  It reads only small JSON/source
metadata while building.  GenCase XML/VTK/BI4 and large control files are
deferred to the reserved parent; no scientific qualification is emitted.

The ROOT345 map is allowed to remain in its real intermediate state
``NINE_ACTUAL_GENCASE_PRODUCTS_DEFERRED_NATIVE_HASH_INITIAL_AUDIT_REQUIRED``.
The output becomes ``WAITING`` until all nine actual producer edges are
available, rather than treating a path or a label as a completed product.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
LAB_ROOT = HERE.parents[4]
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
PYVENV = PYTHON.parent.parent / "pyvenv.cfg"
JSON_CAP = 10 * 1024 * 1024
HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
SCHEMA = "ds02.stage2.three-sentinel.owner-grid-native-initial-support-handoff.v2"
REQUEST_SCHEMA = "ds02.request.v1"
MAP_SCHEMA = "ds02.stage2.three-sentinel.owner-grid-gencase-product-map.v2"
MAP_STATUS = "NINE_ACTUAL_GENCASE_PRODUCTS_DEFERRED_NATIVE_HASH_INITIAL_AUDIT_REQUIRED"
ROW_STATUS = "ACTUAL_GENCASE_PRODUCTS_AWAIT_INITIAL_SUPPORT_AUDIT"
TARGETS = ("F2-S2", "F3-S1", "F5-S1")
GRIDS = ("original", "coarse", "fine")
ROW_KEYS = tuple(f"{sid}:{grid}" for sid in TARGETS for grid in GRIDS)
RECEIPT_STATUS = {"COMPLETED", "COMPLETED_ACTUAL", "COMPLETED_DEVELOPMENT_UNKNOWN", "SUCCESS", "SUCCEEDED"}
PROOF_STATUS = "VERIFIED_ACTUAL_OWNER_GRID_GENCASE_PRODUCTS_NO_SCIENTIFIC_Q"
NO_CREDIT = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "scientific_credit": 0}


class HandoffV2Failure(RuntimeError):
    pass


def _abs(path: Path | str) -> Path:
    return Path(path).expanduser().absolute()


def _stat(path: Path) -> dict[str, int]:
    s = path.stat()
    return {"device": int(s.st_dev), "inode": int(s.st_ino), "bytes": int(s.st_size),
            "mtime_ns": int(s.st_mtime_ns), "ctime_ns": int(s.st_ctime_ns)}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and bool(HEX64.fullmatch(value))


def _read_small(path: Path | str, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _abs(path)
    if path.is_symlink() or not path.is_file():
        raise HandoffV2Failure(f"{label} is not a regular non-symlink file: {path}")
    before = _stat(path)
    if before["bytes"] > JSON_CAP:
        raise HandoffV2Failure(f"{label} exceeds the 10 MiB metadata cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after or len(raw) != before["bytes"]:
        raise HandoffV2Failure(f"{label} changed during bounded read: {path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HandoffV2Failure(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise HandoffV2Failure(f"{label} must be a JSON object")
    return value, {"path": str(path), "sha256": _sha(raw), "stat_before": before,
                   "stat_after": after, "read_mode": "bounded_small_source",
                   "payload_read_by_builder": True}


def _source(path: Path | str, label: str, *, required: bool = True) -> tuple[dict[str, Any] | None, str | None]:
    path = _abs(path)
    if not path.exists():
        if required:
            return None, f"{label} missing: {path}"
        return None, None
    if path.is_symlink() or not path.is_file():
        return None, f"{label} is not a regular file: {path}"
    before = _stat(path)
    if before["bytes"] > JSON_CAP:
        return None, f"{label} exceeds 10 MiB source cap: {path}"
    raw = path.read_bytes()
    after = _stat(path)
    if before != after:
        return None, f"{label} changed during bounded read: {path}"
    return {"path": str(path), "sha256": _sha(raw), "stat_before": before,
            "stat_after": after, "read_mode": "bounded_small_source",
            "payload_read_by_builder": True, "label": label}, None


def _record_ref(value: Any, label: str, *, read_json: bool = True) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str | None]:
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        return None, None, f"{label} has no explicit path record"
    path = _abs(value["path"])
    declared = value.get("sha256")
    if declared is not None and declared not in {"PARENT_AFTER_RESERVATION", "PARENT_AFTER_RESERVATION_REQUIRED",
                                                   "PARENT_AFTER_GENCASE_REQUIRED"} and not _valid_sha(declared):
        return None, None, f"{label} has malformed SHA"
    if not path.is_file() or path.is_symlink():
        return None, None, f"{label} file is unavailable: {path}"
    if not read_json:
        st = _stat(path)
        return {"path": str(path), "sha256": declared, "stat": st,
                "payload_read_by_builder": False, "scope": "parent_deferred"}, None, None
    try:
        parsed, rec = _read_small(path, label)
    except HandoffV2Failure as exc:
        return None, None, str(exc)
    if _valid_sha(declared) and declared.lower() != rec["sha256"].lower():
        return None, None, f"{label} declared SHA does not match file bytes"
    return rec, parsed, None


def _identity(value: dict[str, Any], expected: dict[str, str], label: str, errors: list[str]) -> None:
    for key, wanted in expected.items():
        got = value.get(key)
        if not isinstance(got, str) or got != wanted:
            errors.append(f"{label}.{key}={got!r}; expected exact {wanted!r}")


def _receipt_ref(row: dict[str, Any], proof: dict[str, Any]) -> Any:
    for value in (row.get("actual_producer_receipt"), row.get("producer_receipt"), row.get("gencase_receipt"),
                  proof.get("actual_producer_receipt"), proof.get("producer_receipt"), proof.get("gencase_receipt"),
                  proof.get("execution_receipt"), proof.get("receipt")):
        if isinstance(value, dict) and isinstance(value.get("path"), str):
            return value
    products = proof.get("products")
    if isinstance(products, dict):
        value = products.get("gencase_receipt") or products.get("execution_receipt")
        if isinstance(value, dict) and isinstance(value.get("path"), str):
            return value
    return None


def _product_record(row: dict[str, Any], proof: dict[str, Any], key: str) -> dict[str, Any] | None:
    aliases = {
        "generated_xml": ("generated_xml",),
        "fluid_vtk": ("fluid_vtk", "generated_fluid_vtk"),
        "bound_vtk": ("bound_vtk", "generated_bound_vtk"),
        "native_bi4": ("native_bi4", "generated_bi4"),
    }
    for source in (row, proof.get("products") if isinstance(proof.get("products"), dict) else {}):
        for alias in aliases[key]:
            value = source.get(alias)
            if isinstance(value, dict) and isinstance(value.get("path"), str):
                return {"path": str(_abs(value["path"])),
                        "sha256": value.get("sha256"),
                        "stat": value.get("stat") or value.get("stat_after"),
                        "hash_status": value.get("hash_status") or "PARENT_AFTER_RESERVATION_REQUIRED",
                        "payload_read_by_builder": False,
                        "scope": "parent_deferred_gencase_product"}
    return None


def _edge(row: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    sid, grid = str(row.get("sentinel_id")), str(row.get("grid_label"))
    key = f"{sid}:{grid}"
    expected = {"sentinel_id": sid, "grid_label": grid,
                "physical_case_id": str(row.get("physical_case_id")),
                "case_id": str(row.get("case_id")), "attempt_id": str(row.get("attempt_id"))}
    errors: list[str] = []
    static: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    request_rec, request, error = _record_ref(row.get("producer_request"), f"{key} producer request")
    if error:
        errors.append(error)
    elif request_rec and request:
        static.append(request_rec)
        _identity(request, expected, f"{key} request", errors)
        if request.get("schema") != REQUEST_SCHEMA:
            errors.append(f"{key} request schema is not {REQUEST_SCHEMA}")
        if request.get("cpu_task_kind") != "gencase" or request.get("execution_allowed") is not True:
            errors.append(f"{key} request is not a completed real GenCase request")
        if request.get("source_only") is True or request.get("launch_disabled") is True:
            errors.append(f"{key} request is still source-only/launch-disabled")
    proof_rec, proof, error = _record_ref(row.get("actual_producer_proof") or row.get("producer_proof"), f"{key} producer proof")
    if error:
        errors.append(error)
    elif proof_rec and proof:
        static.append(proof_rec)
        _identity(proof, expected, f"{key} proof", errors)
        if proof.get("status") != PROOF_STATUS:
            errors.append(f"{key} proof status is not exact terminal product status: {proof.get('status')!r}")
        if request_rec and proof.get("request_sha256") not in (None, request_rec["sha256"]):
            errors.append(f"{key} proof request SHA does not equal request file-byte SHA")
    receipt_rec, receipt, error = _record_ref(_receipt_ref(row, proof or {}), f"{key} execution receipt")
    if error:
        errors.append(error)
    elif receipt_rec and receipt:
        static.append(receipt_rec)
        if receipt.get("schema") != "ds02.execution-receipt.v1":
            errors.append(f"{key} receipt schema is not ds02.execution-receipt.v1")
        status = str(receipt.get("status", "")).upper()
        if status not in RECEIPT_STATUS:
            errors.append(f"{key} receipt status is not exact completed status: {receipt.get('status')!r}")
        if receipt.get("returncode") != 0:
            errors.append(f"{key} receipt returncode is not exactly 0")
        if request_rec:
            if receipt.get("request_sha256") != request_rec["sha256"]:
                errors.append(f"{key} receipt.request_sha256 is not request file-byte SHA")
            if receipt.get("request") != request:
                errors.append(f"{key} receipt.request does not equal the request file document")
            if receipt.get("request_path") not in (None, request_rec["path"]):
                errors.append(f"{key} receipt.request_path does not bind exact request path")
        _identity(receipt, expected, f"{key} receipt", errors)
        if request and receipt.get("output_root") not in (None, request.get("output_root")):
            errors.append(f"{key} receipt output_root differs from request")
    # Product paths are deferred.  The builder must never hash or parse them.
    product_paths: dict[str, dict[str, Any]] = {}
    for product_key in ("generated_xml", "fluid_vtk", "bound_vtk", "native_bi4"):
        product = _product_record(row, proof or {}, product_key)
        if product is None:
            errors.append(f"{key} lacks deferred {product_key} product path")
        else:
            product_paths[product_key] = product
            deferred.append({"row_key": key, "role": product_key, **product})
    # Large forcing/control is source-deferred even when its map record has a
    # known SHA.  If the producer request supplies the record, retain it.
    if request:
        for candidate in (request.get("root_exact_auxiliary_closure"), request.get("input_files")):
            if not isinstance(candidate, list):
                continue
            for item in candidate:
                if isinstance(item, dict) and isinstance(item.get("path"), str):
                    p = _abs(item["path"])
                    declared = item.get("sha256")
                    if p.suffix.lower() == ".csv" or (isinstance(item.get("stat"), dict) and int(item["stat"].get("bytes", 0)) > JSON_CAP):
                        deferred.append({"row_key": key, "role": "control_or_forcing", "path": str(p),
                                         "sha256": declared, "stat": item.get("stat"),
                                         "payload_read_by_builder": False,
                                         "scope": "parent_deferred_control"})
    row_out = {"row_key": key, **expected, "row_status": row.get("status"),
               "producer_request": request_rec, "producer_proof": proof_rec,
               "producer_receipt": receipt_rec, "product_records": product_paths,
               "actual_control_cwd": row.get("actual_control_cwd"),
               "edge_status": "VERIFIED_COMPLETED_PRODUCER_EDGE" if not errors else "WAITING_OR_REJECTED",
               "edge_errors": errors, "initial_support": "NOT_RUN",
               "scientific_qualification": dict(NO_CREDIT)}
    return row_out, static + deferred, errors


def _closure_paths() -> list[Path]:
    names = [
        "stage2_three_sentinel_owner_grid_native_initial_support_handoff_v1.py",
        "stage2_three_sentinel_owner_grid_native_header_probe_v2.py",
        "stage2_three_sentinel_owner_grid_native_header_probe_v3.py",
        "stage2_three_sentinel_owner_grid_initial_support_audit_v1.py",
        "stage2_three_sentinel_owner_grid_initial_support_verify_v4.py",
        "stage2_three_sentinel_owner_grid_production_admission_v2.py",
        "stage2_actual_receipt_injection_v2.py",
        "stage2_three_sentinel_owner_grid_runtime_receipt_bridge_v1.py",
        "stage2_three_sentinel_owner_grid_abi_chain_v1.py",
        "stage2_three_sentinel_calibration_worker_v1.py",
        "stage2_three_sentinel_calibration_request_v1.py",
        "stage2_three_sentinel_calibration_verify_v1.py",
        "stage2_three_sentinel_calibration_worker_contract_v1.json",
        "stage2_three_sentinel_calibration_preregister_v1.json",
        "stage2_three_sentinel_calibration_scales_v2.json",
        "stage2_f1_com_observer_calibration_v1.py",
        "stage2_f1_com_observer_calibration_request_v1.py",
        "stage2_f3_s2_initial_support_audit_v3.py",
        "stage2_f5_s1_clipplane_initial_support_audit_v7.py",
        "stage2_rotation_invariant_native_scalar_observer_v1.py",
        "stage2_rotation_invariant_native_scalar_request_v1.py",
        "stage2_rotation_invariant_native_scalar_observer_v2.py",
        "stage2_rotation_invariant_native_scalar_request_v2.py",
        "stage2_f1_s2_root279_native_scalar_parent_worker_v1.py",
        "stage2_f1_s2_root279_native_scalar_parent_request_v1.py",
    ]
    return [HERE / name for name in names]


def _runtime_records() -> tuple[list[dict[str, Any]], list[str]]:
    records: list[dict[str, Any]] = []
    missing: list[str] = []
    for path in [LAB_ROOT / "scripts/ds_data02_runtime_v2.py", PYVENV, PYTHON.resolve()]:
        record, error = _source(path, f"runtime closure {path.name}", required=True)
        if error:
            missing.append(error)
        elif record:
            records.append(record)
    return records, missing


def build(product_map_path: Path, output_dir: Path, *, decoder: Path | None = None) -> dict[str, Any]:
    product_map, map_record = _read_small(product_map_path, "ROOT345 actual product map")
    if product_map.get("schema") != MAP_SCHEMA:
        raise HandoffV2Failure(f"product map schema must be {MAP_SCHEMA}, got {product_map.get('schema')!r}")
    if product_map.get("status") != MAP_STATUS:
        raise HandoffV2Failure("ROOT345 map status is not the exact deferred initial-audit state")
    rows = product_map.get("products")
    if not isinstance(rows, list):
        raise HandoffV2Failure("ROOT345 map products is not a list")
    by_key: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise HandoffV2Failure("ROOT345 product row is not an object")
        key = f"{row.get('sentinel_id')}:{row.get('grid_label')}"
        if key not in ROW_KEYS or key in by_key:
            raise HandoffV2Failure(f"invalid/duplicate ROOT345 row {key}")
        if row.get("status") != ROW_STATUS:
            raise HandoffV2Failure(f"{key} row status is not exact {ROW_STATUS}")
        for field in ("physical_case_id", "case_id", "attempt_id"):
            if not isinstance(row.get(field), str) or not row[field]:
                raise HandoffV2Failure(f"{key} lacks exact {field}")
        by_key[key] = row
    if set(by_key) != set(ROW_KEYS):
        raise HandoffV2Failure("ROOT345 map must contain exactly the nine expected rows")

    row_outputs: list[dict[str, Any]] = []
    static: dict[str, dict[str, Any]] = {map_record["path"]: map_record}
    deferred: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for key in ROW_KEYS:
        row_out, records, row_errors = _edge(by_key[key])
        row_outputs.append(row_out)
        for record in records:
            if record.get("payload_read_by_builder") is False:
                deferred.append(record)
            elif isinstance(record.get("path"), str):
                static[record["path"]] = record
        if row_errors:
            errors.append({"row_key": key, "errors": row_errors})

    closure_missing: list[str] = []
    for path in _closure_paths():
        record, error = _source(path, f"whole-parent source {path.name}", required=True)
        if error:
            closure_missing.append(error)
        elif record:
            static[record["path"]] = record
    runtime_records, runtime_missing = _runtime_records()
    closure_missing.extend(runtime_missing)
    for record in runtime_records:
        static[record["path"]] = record
    if decoder is not None:
        decoder = _abs(decoder)
        # The executable is the project custom JBinaryData adapter, not an
        # official DualSPHysics tool.  Keep it deferred unless a caller gives
        # a small source/binary record; never hash a production payload here.
        if decoder.is_file() and not decoder.is_symlink() and decoder.stat().st_size <= JSON_CAP:
            record, error = _source(decoder, "custom BI4 adapter", required=True)
            if error:
                closure_missing.append(error)
            elif record:
                static[record["path"]] = record
        else:
            deferred.append({"role": "custom_bi4_adapter_executable", "path": str(decoder),
                             "sha256": "PARENT_AFTER_RESERVATION_REQUIRED", "stat": {},
                             "payload_read_by_builder": False,
                             "tool_authority": "project_custom_jbinarydata_adapter_not_official_tool"})
    completed = not errors and not closure_missing
    status = ("READY_FOR_PARENT_NATIVE_HEADER_V3_AND_INITIAL_SUPPORT" if completed
              else "WAITING_ROOT345_PRODUCER_EDGES_OR_WHOLE_PARENT_SOURCE_CLOSURE")
    output_dir = _abs(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise HandoffV2Failure(f"refusing to overwrite nonempty output: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    handoff = {
        "schema": SCHEMA, "status": status,
        "source_status": "SOURCE_ONLY_NO_PRODUCTION_CREDIT",
        "product_map": map_record, "product_map_status": product_map["status"],
        "rows": row_outputs, "row_count": len(row_outputs),
        "validation_errors": errors, "closure_missing": closure_missing,
        "whole_parent_v10": {
            "request_receipt_proof_exact_edges": True,
            "request_sha_basis": "raw_request_file_bytes",
            "receipt_request_must_equal_file_document": True,
            "returncode_must_equal_zero": True,
            "identity_fields": ["sentinel_id", "grid_label", "family_id", "physical_case_id", "case_id", "attempt_id"],
            "generated_products": ["generated_xml", "fluid_vtk", "bound_vtk", "native_bi4"],
            "large_control_and_native_payload": "parent_after_reservation_full_sha_stat_only",
            "source_input_files": sorted(static),
            "deferred_input_records": deferred,
        },
        "native_header_contract": {
            "status": "WAITING_FOR_PARENT_NATIVE_HEADER_V3",
            "tool_authority": "project_custom_jbinarydata_adapter; official-tool-identity-unknown",
            "fields": ["MassFluid", "MassBound", "Dp", "Idp", "role_counts"],
            "xml_mass_fallback": False, "per_particle_mass_semantics": True,
            "world_axis": "UNKNOWN", "scientific_credit": 0,
        },
        "initial_support_contract": {
            "status": "WAITING_FOR_PARENT_INITIAL_SUPPORT_AUDIT",
            "checks": ["finite", "Fluid/Bound separation", "Idp role counts", "source/control cwd", "native header"],
            "xml_mass_fallback": False, "scientific_credit": 0,
        },
        "three_calibration_contracts": {
            "status": "SOURCE_PREPARED_WAITING_FOR_NATIVE_INITIAL_SUPPORT",
            "sentinels": list(TARGETS), "grid_scope": list(GRIDS),
            "neighbor_grid_truth": False, "interpolation": False,
            "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "scientific_credit": 0,
        },
        "static_source_records": list(static.values()),
        "deferred_input_records": deferred,
        "scientific_qualification": dict(NO_CREDIT),
        "execution_allowed": False,
    }
    manifest_path = output_dir / "native-initial-support-handoff-manifest-v2.json"
    manifest_path.write_text(json.dumps(handoff, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest_record = {"path": str(manifest_path), "sha256": _sha(manifest_path.read_bytes()), "stat": _stat(manifest_path),
                       "payload_read_by_builder": False, "scope": "builder_output_metadata"}
    static[manifest_record["path"]] = manifest_record
    request = {
        "schema": REQUEST_SCHEMA, "variant_schema": SCHEMA, "status": status,
        "request_variant": "root345-native-initial-support-handoff-v2",
        "family_id": "infra", "sentinel_id": "THREE-SENTINEL-OWNER-GRID",
        "physical_case_id": "ROOT345-NINE-ACTUAL-GENCASE-PRODUCTS",
        "case_id": "ROOT345_NATIVE_HEADER_V3_INITIAL_SUPPORT_AND_CALIBRATION_V2",
        "attempt_id": "PARENT_AFTER_RESERVATION_REQUIRED", "cpu_task_kind": "audit", "cpu_threads": 1,
        "execution_allowed": False, "solver_launch": False, "gencase_launch": False,
        "command": [str(PYTHON), str(Path(__file__).absolute()), "--run", "--manifest",
                     "{attempt_root}/native-initial-support-handoff-manifest-v2.json", "--attempt-root",
                     "{attempt_root}", "--output", "{attempt_root}/report/native-initial-support-handoff-v2.json"],
        "worktree_root": str(LAB_ROOT), "cwd": str(LAB_ROOT),
        "manifest": manifest_record, "input_files": sorted(static),
        "input_records": static, "input_sha256": {p: r["sha256"] for p, r in static.items() if _valid_sha(r.get("sha256"))},
        "deferred_input_records": deferred,
        "resource_scope": {"cpu_seconds": 900, "memory_bytes": 4 * 1024 * 1024 * 1024,
                           "scratch_bytes": 512 * 1024 * 1024, "static_metadata_cap_bytes": JSON_CAP,
                           "native_payload_reads": "parent_deferred_only"},
        "scientific_qualification": dict(NO_CREDIT),
    }
    request_path = output_dir / "native-initial-support-handoff-request-v2.json"
    request_path.write_text(json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"status": status, "manifest_path": str(manifest_path), "request_path": str(request_path),
            "manifest": handoff, "request": request}


def _fixture_map(root: Path) -> Path:
    """Make a tiny *actual-shaped* completed map for strict edge tests only."""
    rows: list[dict[str, Any]] = []
    producer = root / "producer"; producer.mkdir(parents=True)
    for sid in TARGETS:
        for grid in GRIDS:
            key = f"{sid}:{grid}"; case = root / key.replace(":", "_"); case.mkdir()
            q = {"schema": REQUEST_SCHEMA, "sentinel_id": sid, "grid_label": grid,
                 "family_id": sid[:2], "physical_case_id": f"P-{key}", "case_id": f"C-{key}",
                 "attempt_id": f"A-{key}", "cpu_task_kind": "gencase", "execution_allowed": True,
                 "source_only": False, "launch_disabled": False, "output_root": str(case)}
            qp = producer / f"{key.replace(':', '_')}.request.json"; qp.write_text(json.dumps(q, sort_keys=True) + "\n")
            products = {}
            for name in ("generated_xml", "fluid_vtk", "bound_vtk", "native_bi4"):
                products[name] = {"path": str(case / name), "sha256": None, "stat": None}
            receipt = {"schema": "ds02.execution-receipt.v1", "status": "COMPLETED_ACTUAL", "returncode": 0,
                       "sentinel_id": sid, "grid_label": grid, "family_id": sid[:2],
                       "physical_case_id": q["physical_case_id"], "case_id": q["case_id"], "attempt_id": q["attempt_id"],
                       "output_root": str(case), "request_sha256": _sha(qp.read_bytes()), "request": q}
            rp = case / "execution-receipt.json"; rp.write_text(json.dumps(receipt, sort_keys=True) + "\n")
            products["gencase_receipt"] = {"path": str(rp), "sha256": _sha(rp.read_bytes())}
            proof = {"schema": "ds02.stage2.root-owner-grid-gencase-proof.v2", "status": PROOF_STATUS,
                     "sentinel_id": sid, "grid_label": grid, "family_id": sid[:2],
                     "physical_case_id": q["physical_case_id"], "case_id": q["case_id"], "attempt_id": q["attempt_id"],
                     "request_sha256": _sha(qp.read_bytes()), "products": products}
            pp = producer / f"{key.replace(':', '_')}.proof.json"; pp.write_text(json.dumps(proof, sort_keys=True) + "\n")
            rows.append({"sentinel_id": sid, "grid_label": grid, "family_id": sid[:2],
                         "physical_case_id": q["physical_case_id"], "case_id": q["case_id"], "attempt_id": q["attempt_id"],
                         "status": ROW_STATUS, "producer_request": {"path": str(qp), "sha256": _sha(qp.read_bytes())},
                         "actual_producer_proof": {"path": str(pp), "sha256": _sha(pp.read_bytes())},
                         "generated_xml": products["generated_xml"], "fluid_vtk": products["fluid_vtk"],
                         "bound_vtk": products["bound_vtk"], "native_bi4": products["native_bi4"],
                         "actual_control_cwd": str(case)})
    path = root / "owner-grid-actual-gencase-product-map-v2.json"
    path.write_text(json.dumps({"schema": MAP_SCHEMA, "status": MAP_STATUS, "products": rows}, indent=2, sort_keys=True) + "\n")
    return path


def _self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="root345-handoff-v2-") as td:
        root = Path(td)
        result = build(_fixture_map(root), root / "out")
        assert result["status"] == "WAITING_ROOT345_PRODUCER_EDGES_OR_WHOLE_PARENT_SOURCE_CLOSURE", result["status"]
        # The tiny map edges are all real file-byte joins; only the required
        # source closure is absent in this temp directory.  No product bytes
        # are opened and no status is upgraded to scientific PASS.
        assert len(result["manifest"]["rows"]) == 9
        assert result["manifest"]["scientific_qualification"] == NO_CREDIT
        base_map = root / "owner-grid-actual-gencase-product-map-v2.json"
        bad = json.loads(base_map.read_text())
        bad["products"][0]["actual_producer_proof"] = None
        bad_path = root / "bad-map.json"; bad_path.write_text(json.dumps(bad) + "\n")
        out = root / "bad-out"
        value = build(bad_path, out)
        assert value["status"].startswith("WAITING_")
        assert any("producer proof" in err for item in value["manifest"]["validation_errors"] for err in item["errors"])
    print("PASS_ROOT345_HANDOFF_V2_EXACT_EDGE_WAITING_FIXTURE_NO_SCIENTIFIC_CREDIT")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build", action="store_true")
    parser.add_argument("--product-map", type=Path)
    parser.add_argument("--decoder", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            _self_test(); return 0
        if args.product_map is None or args.output_dir is None:
            parser.error("--build requires --product-map and --output-dir")
        value = build(args.product_map, args.output_dir, decoder=args.decoder)
        print(json.dumps({"status": value["status"], "manifest": value["manifest_path"],
                          "request": value["request_path"], "scientific_credit": 0}, sort_keys=True))
        return 0
    except (HandoffV2Failure, OSError, ValueError) as exc:
        print(f"FAILED_ROOT345_HANDOFF_V2: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
