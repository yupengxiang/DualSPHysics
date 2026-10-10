#!/usr/bin/env python3
"""Prepare the post-GenCase owner-grid chain from an actual nine-row map.

This source-only adapter is intentionally independent of the historical
ROOT337--345 attempt names.  The parent supplies a new product map after the
actual producer jobs finish (for example the 700--708 namespace).  The map's
producer request, terminal proof and execution receipt are joined through the
strict edge implementation from the consumed handoff code.  Generated XML,
Fluid/Bound VTK and BI4 files are recorded as deferred products; this builder
only stats their paths and never opens their payloads.

The output contains parent-after-reservation command templates for the native
header probe, initial-support audit and one calibration package per sentinel.
All requests are execution-disabled and carry zero scientific credit.  A
source package can therefore be made before the nine products exist; missing
products, source bindings or decoder closure remain explicit WAITING reasons.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
JSON_CAP = 10 * 1024 * 1024
HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
REQUEST_SCHEMA = "ds02.request.v1"
MAP_SCHEMA_PREFIX = "ds02.stage2.three-sentinel.owner-grid-gencase-product-map"
TARGETS = ("F2-S2", "F3-S1", "F5-S1")
GRIDS = ("original", "coarse", "fine")
ROW_KEYS = tuple(f"{sid}:{grid}" for sid in TARGETS for grid in GRIDS)
NO_CREDIT = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "scientific_credit": 0}

HEADER_MANIFEST_SCHEMA = "ds02.stage2.three-sentinel-owner-grid-native-header-probe-manifest.v2"
HEADER_STATUS = "READY_FOR_PARENT_GUARDED_NATIVE_HEADER_PROBE"
SUPPORT_MANIFEST_SCHEMA = "ds02.stage2.three-sentinel-owner-grid-initial-support-manifest.v1"
SUPPORT_STATUS = "READY_FOR_PARENT_GUARDED_OWNER_GRID_INITIAL_SUPPORT"
CALIB_MANIFEST_SCHEMA = "ds02.stage2.three-sentinel-calibration-manifest.v1"
CALIB_STATUS = "READY_FOR_PARENT_GUARDED_THREE_SENTINEL_CALIBRATION"

HEADER_WORKER = HERE / "stage2_three_sentinel_owner_grid_native_header_probe_v3.py"
SUPPORT_WORKER = HERE / "stage2_three_sentinel_owner_grid_initial_support_audit_v1.py"
CALIB_WORKER = HERE / "stage2_three_sentinel_calibration_worker_v1.py"
CALIB_VERIFY = HERE / "stage2_three_sentinel_calibration_verify_v1.py"
CALIB_CONTRACT = HERE / "stage2_three_sentinel_calibration_worker_contract_v1.json"
CALIB_SCALES = HERE / "stage2_three_sentinel_calibration_scales_v2.json"
ADMISSION_PATH = HERE / "stage2_three_sentinel_owner_grid_production_admission_v2.py"
HANDOFF_V3_PATH = HERE / "stage2_three_sentinel_owner_grid_native_initial_support_handoff_v3.py"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
PYVENV = PYTHON.parent.parent / "pyvenv.cfg"


class ChainFailure(RuntimeError):
    pass


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ChainFailure(f"cannot load {name}: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ADMISSION = _load(ADMISSION_PATH, "post_gencase_admission_v2")
HANDOFF_V3 = _load(HANDOFF_V3_PATH, "post_gencase_handoff_v3")
# Handoff V3 changes only the receipt identity ABI: real runtime receipts
# carry identity under receipt.request.  Its edge implementation is otherwise
# the strict consumed V2 implementation.
HANDOFF_V3._install_receipt_abi()
EDGE = HANDOFF_V3.V2._edge


def _abs(value: Path | str) -> Path:
    return Path(value).expanduser().absolute()


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {"device": int(value.st_dev), "inode": int(value.st_ino),
            "bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns),
            "ctime_ns": int(value.st_ctime_ns)}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and bool(HEX64.fullmatch(value))


def _read_json(path: Path | str, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _abs(path)
    if path.is_symlink() or not path.is_file():
        raise ChainFailure(f"{label} is not a regular non-symlink file: {path}")
    before = _stat(path)
    if before["bytes"] > JSON_CAP:
        raise ChainFailure(f"{label} exceeds the 10 MiB metadata cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after or len(raw) != before["bytes"]:
        raise ChainFailure(f"{label} changed during bounded read: {path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ChainFailure(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ChainFailure(f"{label} must be a JSON object: {path}")
    return value, {"path": str(path), "sha256": _sha(raw), "bytes": len(raw),
                   "stat_before": before, "stat_after": after,
                   "payload_read_by_builder": False, "scope": "bounded_small_metadata"}


def _record(path: Path | str, label: str, *, read: bool = True) -> dict[str, Any]:
    """Record a source file; product payloads always use ``read=False``."""
    path = _abs(path)
    if path.is_symlink() or not path.is_file():
        raise ChainFailure(f"{label} is not a regular non-symlink file: {path}")
    before = _stat(path)
    if read and before["bytes"] > JSON_CAP:
        raise ChainFailure(f"{label} exceeds the 10 MiB source cap: {path}")
    if read:
        raw = path.read_bytes()
        after = _stat(path)
        if before != after or len(raw) != before["bytes"]:
            raise ChainFailure(f"{label} changed during bounded read: {path}")
        digest = _sha(raw)
    else:
        after = before
        digest = None
    return {"path": str(path), "sha256": digest, "stat": after,
            "stat_before": before, "stat_after": after,
            "hash_status": "BOUND_BY_BUILDER" if digest else "PARENT_AFTER_RESERVATION_REQUIRED",
            "payload_read_by_builder": bool(read), "scope": "bounded_source_metadata" if read else "parent_deferred_product"}


def _record_declared(value: Any, label: str, *, role: str, product: bool = False) -> dict[str, Any] | None:
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        return None
    path = _abs(value["path"])
    declared = value.get("sha256")
    if declared is not None and declared not in {
        "PARENT_AFTER_RESERVATION", "PARENT_AFTER_RESERVATION_REQUIRED",
        "PARENT_AFTER_GENCASE_REQUIRED", "PARENT_AFTER_RESERVATION_FULL_SHA",
    } and not _valid_sha(declared):
        raise ChainFailure(f"{label} has malformed SHA")
    # A product path is intentionally not opened.  Its stat is useful for
    # parent admission, but a missing future product is a WAITING condition.
    stat = _stat(path) if path.is_file() and not path.is_symlink() else value.get("stat")
    if isinstance(stat, dict):
        stat = {str(k): int(v) for k, v in stat.items() if str(k) in {"device", "inode", "bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"} and isinstance(v, (int, float))}
    return {"path": str(path), "sha256": declared, "stat": stat,
            "hash_status": "MAP_DECLARED_SHA" if _valid_sha(declared) else "PARENT_AFTER_RESERVATION_REQUIRED",
            "payload_read_by_builder": False, "scope": "parent_deferred_product" if product else "parent_deferred_source",
            "role": role}


def _write_once(path: Path, value: Any) -> dict[str, Any]:
    path = _abs(path)
    if path.exists() or path.is_symlink():
        raise ChainFailure(f"refusing to overwrite output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    tmp = path.with_name(f".{path.name}.{__import__('os').getpid()}.tmp")
    tmp.write_bytes(raw)
    tmp.replace(path)
    stat = _stat(path)
    return {"path": str(path), "sha256": _sha(raw), "bytes": len(raw), "stat": stat,
            "payload_read_by_builder": False, "scope": "builder_output_metadata"}


def _row_key(row: dict[str, Any]) -> str:
    return f"{row.get('sentinel_id')}:{row.get('grid_label')}"


def _map_rows(product: dict[str, Any]) -> dict[str, dict[str, Any]]:
    schema = product.get("schema")
    if not isinstance(schema, str) or not schema.startswith(MAP_SCHEMA_PREFIX):
        raise ChainFailure(f"unexpected product-map schema: {schema!r}")
    status = str(product.get("status") or "").strip().upper()
    allowed = set(getattr(ADMISSION, "PRODUCT_MAP_STATES", ()))
    if status not in allowed:
        raise ChainFailure(f"product-map status is not an allowed exact state: {status!r}")
    rows = product.get("products")
    if rows is None:
        rows = product.get("cases")
    if not isinstance(rows, list):
        raise ChainFailure("product map lacks products/cases list")
    by_key: dict[str, dict[str, Any]] = {}
    allowed_rows = set(getattr(ADMISSION, "PRODUCT_ROW_STATES", ()))
    for row in rows:
        if not isinstance(row, dict):
            raise ChainFailure("product map row is not an object")
        key = _row_key(row)
        if key not in ROW_KEYS or key in by_key:
            raise ChainFailure(f"invalid or duplicate product-map row: {key}")
        row_status = str(row.get("status") or "").strip().upper()
        if row_status not in allowed_rows:
            raise ChainFailure(f"{key} has unsupported exact row status: {row.get('status')!r}")
        for field in ("physical_case_id", "case_id", "attempt_id"):
            if not isinstance(row.get(field), str) or not row[field]:
                raise ChainFailure(f"{key} lacks exact {field}; labels cannot substitute")
        by_key[key] = row
    if set(by_key) != set(ROW_KEYS):
        missing = sorted(set(ROW_KEYS) - set(by_key)); extra = sorted(set(by_key) - set(ROW_KEYS))
        raise ChainFailure(f"product map must contain exact nine rows; missing={missing}, extra={extra}")
    return by_key


def _load_request(record: Any, key: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str | None]:
    if not isinstance(record, dict) or not isinstance(record.get("path"), str):
        return None, None, f"{key} producer request record is absent"
    try:
        value, rec = _read_json(record["path"], f"{key} producer request")
    except ChainFailure as exc:
        return None, None, str(exc)
    declared = record.get("sha256")
    if _valid_sha(declared) and declared.lower() != rec["sha256"].lower():
        return None, None, f"{key} producer request map SHA differs from raw file bytes"
    return value, rec, None


def _nested_find(value: Any, names: set[str]) -> Any:
    if isinstance(value, dict):
        for name in names:
            candidate = value.get(name)
            if isinstance(candidate, dict) and isinstance(candidate.get("path"), str):
                return candidate
        # Source binding names may be nested in a rebind request/manifest.
        for key in ("source_binding", "rebind_request", "rebind_manifest", "source_edit_contract", "input_records", "inputs"):
            if key in value:
                found = _nested_find(value[key], names)
                if found is not None:
                    return found
        for candidate in value.values():
            if isinstance(candidate, (dict, list)):
                found = _nested_find(candidate, names)
                if found is not None:
                    return found
    elif isinstance(value, list):
        for candidate in value:
            found = _nested_find(candidate, names)
            if found is not None:
                return found
    return None


def _source_binding(request: dict[str, Any], key: str) -> dict[str, Any]:
    binding = request.get("source_binding") if isinstance(request.get("source_binding"), dict) else {}
    # Use exact named producer records where present.  For F3 the rebind
    # request/manifest is searched explicitly; no path is inferred from a
    # family or grid label.
    names = {
        "source_xml": {"source_xml", "source_xml_record", "generated_source_xml"},
        "source_def": {"source_def", "source_def_record", "original_def"},
        "candidate_def": {"candidate_def", "candidate_def_record", "generated_def"},
        "owner_predicate": {"owner_region_predicate", "owner_predicate", "owner_region"},
    }
    out: dict[str, Any] = {}
    for field, aliases in names.items():
        # Owner predicates are semantic dictionaries rather than file
        # records.  Keep the exact producer-supplied object when present;
        # requiring a ``path`` here would silently turn a real predicate into
        # the generic UNKNOWN fallback.
        raw: Any = None
        if field == "owner_predicate":
            containers = (binding, request)
            for container in containers:
                if isinstance(container, dict):
                    for alias in aliases:
                        candidate = container.get(alias)
                        if isinstance(candidate, dict):
                            raw = candidate
                            break
                    if raw is not None:
                        break
            if raw is None:
                for container in (binding.get("rebind_request"), binding.get("rebind_manifest")):
                    if isinstance(container, dict):
                        for alias in aliases:
                            candidate = container.get(alias)
                            if isinstance(candidate, dict):
                                raw = candidate
                                break
                        if raw is not None:
                            break
        else:
            raw = _nested_find(binding, aliases)
            if raw is None:
                raw = _nested_find(request, aliases)
        role = field
        if field == "owner_predicate" and isinstance(raw, dict) and not isinstance(raw.get("path"), str):
            out[field] = dict(raw)
            out[field].setdefault("mass_rescale", False)
        elif raw is not None:
            out[field] = _record_declared(raw, f"{key} {field}", role=role, product=False)
        elif field == "owner_predicate":
            out[field] = {"status": "UNKNOWN_CONTINUOUS_OWNER", "mass_rescale": False,
                          "source": "producer_binding_did_not_supply_owner_predicate",
                          "scientific_credit": 0}
        else:
            out[field] = None
    missing = [field for field in ("source_xml", "source_def", "candidate_def") if out.get(field) is None]
    if missing:
        out["status"] = "WAITING_SOURCE_BINDING_FIELDS"
        out["missing_fields"] = missing
    else:
        out["status"] = "BOUND_SOURCE_PATHS_STAT_ONLY"
        out["missing_fields"] = []
    out["source_xml_mass_is_not_native"] = True
    out["mass_rescale"] = False
    return out


def _product_records(row_out: dict[str, Any], key: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    products = row_out.get("product_records") if isinstance(row_out.get("product_records"), dict) else {}
    for role in ("generated_xml", "fluid_vtk", "bound_vtk", "native_bi4"):
        record = products.get(role)
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            result[role] = None
            continue
        value = dict(record)
        value["role"] = role
        value["payload_read_by_builder"] = False
        value["scope"] = "parent_after_reservation_product_payload"
        result[role] = value
    return result


def _closure_paths() -> tuple[Path, ...]:
    names = (
        "stage2_three_sentinel_owner_grid_production_admission_v2.py",
        "stage2_three_sentinel_owner_grid_native_initial_support_handoff_v3.py",
        "stage2_three_sentinel_owner_grid_native_header_probe_request_v6.py",
        "stage2_three_sentinel_owner_grid_native_header_probe_v3.py",
        "stage2_three_sentinel_owner_grid_initial_support_audit_v1.py",
        "stage2_three_sentinel_owner_grid_initial_support_verify_v4.py",
        "stage2_three_sentinel_calibration_worker_v1.py",
        "stage2_three_sentinel_calibration_verify_v1.py",
        "stage2_three_sentinel_calibration_worker_contract_v1.json",
        "stage2_three_sentinel_calibration_scales_v2.json",
        "stage2_three_sentinel_owner_grid_post_gencase_chain_v1.py",
    )
    return tuple(HERE / name for name in names)


def _static_closure(map_record: dict[str, Any], edge_static: list[dict[str, Any]],
                    *, decoder: Path | None) -> tuple[dict[str, dict[str, Any]], list[str]]:
    static: dict[str, dict[str, Any]] = {map_record["path"]: map_record}
    for record in edge_static:
        if isinstance(record, dict) and isinstance(record.get("path"), str):
            if record.get("payload_read_by_builder") is False:
                continue
            static[record["path"]] = record
    missing: list[str] = []
    for path in (*_closure_paths(),):
        if not path.is_file():
            missing.append(f"source closure missing: {path}")
            continue
        try:
            record = _record(path, f"post-GenCase source closure {path.name}")
        except ChainFailure as exc:
            missing.append(str(exc)); continue
        static[record["path"]] = record
    # Bind the literal venv configuration if available.  The interpreter is a
    # literal argv0 in future requests; the resolved target is provenance only
    # and is not silently substituted into command[0].
    for path in (PYVENV,):
        if path.is_file() and not path.is_symlink():
            try:
                record = _record(path, f"literal venv closure {path.name}")
                static[record["path"]] = record
            except ChainFailure as exc:
                missing.append(str(exc))
        else:
            missing.append(f"literal venv closure missing: {path}")
    if decoder is not None:
        try:
            record = _record(decoder, "custom BI4 adapter source/executable closure")
            static[record["path"]] = record
        except ChainFailure as exc:
            missing.append(str(exc))
    return static, missing


def _request(*, status: str, case_id: str, command: list[str], manifest_record: dict[str, Any],
             static: dict[str, dict[str, Any]], deferred: list[dict[str, Any]],
             variant: str, source_closure_missing: list[str]) -> dict[str, Any]:
    return {
        "schema": REQUEST_SCHEMA, "variant_schema": "ds02.stage2.three-sentinel-owner-grid-post-gencase-chain.v1",
        "status": status, "request_variant": variant, "family_id": "infra",
        "physical_case_id": f"POST_GENCASE_{variant.upper()}", "case_id": case_id,
        "attempt_id": "PARENT_AFTER_RESERVATION_REQUIRED", "kind": "cpu", "cpu_task_kind": "audit",
        "cpu_threads": 1, "execution_allowed": False, "launch_disabled": True,
        "solver_launch": False, "gencase_launch": False, "source_only": True,
        "native_payload_read": False, "command": command,
        "command_scope": "parent_after_reservation_template_only",
        "manifest": manifest_record, "input_files": sorted(static), "input_records": static,
        "input_sha256": {path: rec["sha256"] for path, rec in static.items() if _valid_sha(rec.get("sha256"))},
        "deferred_input_records": deferred,
        "source_closure_missing": source_closure_missing,
        "resource_scope": {"cpu_seconds": 900, "memory_bytes": 4 * 1024 * 1024 * 1024,
                           "scratch_bytes": 512 * 1024 * 1024, "static_metadata_cap_bytes": JSON_CAP,
                           "payload_reads": "parent_after_reservation_only"},
        "scientific_qualification": dict(NO_CREDIT), "scientific_credit": 0,
    }


def _deferred_products(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in rows:
        for role, value in (row.get("product_records") or {}).items():
            if isinstance(value, dict) and isinstance(value.get("path"), str):
                result.append({"row_key": row["row_key"], "role": role, **value,
                               "payload_read_by_builder": False,
                               "scope": "parent_after_reservation_product_payload"})
        producer = row.get("producer_receipt")
        # Receipt and proof are small metadata already in static input_files;
        # only products are deferred here.
    return result


def build(product_map_path: Path, output_dir: Path, *, decoder: Path | None = None) -> dict[str, Any]:
    product_map, map_record = _read_json(product_map_path, "actual nine-row product map")
    by_key = _map_rows(product_map)
    output_dir = _abs(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ChainFailure(f"refusing nonempty output directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    edge_static: list[dict[str, Any]] = []
    validation_errors: list[dict[str, Any]] = []
    for key in ROW_KEYS:
        source_row = by_key[key]
        normalized, records, errors = EDGE(source_row)
        normalized = dict(normalized)
        normalized["source_binding"] = {}
        request_value, request_record, request_error = _load_request(source_row.get("producer_request"), key)
        if request_error:
            errors = list(errors) + [request_error]
        elif request_value is not None:
            normalized["source_binding"] = _source_binding(request_value, key)
        normalized["product_records"] = _product_records(normalized, key)
        normalized["product_identity"] = {
            field: source_row.get(field) for field in
            ("sentinel_id", "grid_label", "family_id", "physical_case_id", "case_id", "attempt_id")
        }
        normalized["edge_errors"] = list(errors)
        normalized["edge_status"] = "VERIFIED_COMPLETED_PRODUCER_EDGE" if not errors else "WAITING_OR_REJECTED"
        normalized["scientific_qualification"] = dict(NO_CREDIT)
        rows.append(normalized)
        edge_static.extend(records)
        if errors:
            validation_errors.append({"row_key": key, "errors": list(errors)})

    # Source XML/Def records are small source inputs and may be bound into the
    # static closure.  This reads only those bounded files; generated products
    # remain deferred.  A missing F3 source binding is a WAITING condition,
    # never an inferred path or a cross-sentinel substitute.
    source_static: list[dict[str, Any]] = []
    for row in rows:
        binding = row.get("source_binding") if isinstance(row.get("source_binding"), dict) else {}
        missing_fields = list(binding.get("missing_fields") or [])
        for field in ("source_xml", "source_def", "candidate_def"):
            ref = binding.get(field)
            if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
                continue
            path = _abs(ref["path"])
            if path.is_symlink() or not path.is_file():
                missing_fields.append(f"{field}:file-unavailable")
                continue
            try:
                actual = _record(path, f"{row['row_key']} {field}")
            except ChainFailure as exc:
                missing_fields.append(f"{field}:{exc}")
                continue
            declared = ref.get("sha256")
            if _valid_sha(declared) and declared.lower() != actual["sha256"].lower():
                validation_errors.append({"row_key": row["row_key"],
                                           "errors": [f"{field} declared SHA differs from source file bytes"]})
            binding[field] = actual
            source_static.append(actual)
        binding["missing_fields"] = sorted(set(str(item) for item in missing_fields))
        binding["status"] = "BOUND_SOURCE_PATHS_STAT_ONLY" if not binding["missing_fields"] else "WAITING_SOURCE_BINDING_FIELDS"

    static, closure_missing = _static_closure(map_record, edge_static + source_static, decoder=decoder)
    edge_ready = not validation_errors and all(row.get("edge_status") == "VERIFIED_COMPLETED_PRODUCER_EDGE" for row in rows)
    source_ready = all(not row.get("source_binding", {}).get("missing_fields") for row in rows)
    decoder_ready = decoder is not None and decoder.is_file() and not decoder.is_symlink()
    header_ready = edge_ready and decoder_ready and not closure_missing
    support_ready = edge_ready and source_ready and not closure_missing
    header_status = HEADER_STATUS if header_ready else "WAITING_FOR_NINE_PRODUCTS_DECODER_OR_SOURCE_CLOSURE"
    support_status = SUPPORT_STATUS if support_ready else "WAITING_FOR_NINE_PRODUCTS_SOURCE_BINDINGS_OR_SOURCE_CLOSURE"

    # The unified handoff is small and is itself part of all child requests.
    chain_manifest = {
        "schema": "ds02.stage2.three-sentinel.owner-grid-post-gencase-chain.v1",
        "status": "READY_FOR_PARENT_CHAIN" if edge_ready else "WAITING_ACTUAL_NINE_GENCASE_PRODUCT_EDGES",
        "source_status": "SOURCE_ONLY_NO_PRODUCTION_CREDIT",
        "product_map": map_record, "product_map_status": product_map.get("status"),
        "rows": rows, "row_count": len(rows), "exact_row_keys": list(ROW_KEYS),
        "validation_errors": validation_errors, "source_closure_missing": closure_missing,
        "stages": {"native_header": header_status, "initial_support": support_status,
                    "calibration": "WAITING_FOR_HEADER_AND_INITIAL_SUPPORT_REPORTS"},
        "deferred_product_roles": ["generated_xml", "fluid_vtk", "bound_vtk", "native_bi4"],
        "payload_read_by_builder": False, "solver_or_gencase_launch": False,
        "scientific_qualification": dict(NO_CREDIT), "scientific_credit": 0,
    }
    chain_path = output_dir / "post-gencase-chain-manifest-v1.json"
    chain_record = _write_once(chain_path, chain_manifest)
    static[chain_record["path"]] = chain_record

    deferred = _deferred_products(rows)
    if decoder is None:
        decoder_record = {"path": "PARENT_AFTER_RESERVATION_REQUIRED/custom-bi4-decoder",
                          "sha256": None, "status": "WAITING_DECODER_BINDING",
                          "payload_read_by_builder": False, "scope": "parent_deferred_decoder"}
    else:
        decoder_record = _record_declared({"path": str(_abs(decoder)), "sha256": None},
                                          "custom BI4 decoder", role="decoder", product=False)
        if decoder_record is None:
            decoder_record = {"path": str(_abs(decoder)), "sha256": None,
                              "status": "WAITING_DECODER_BINDING", "payload_read_by_builder": False}

    header_cases: list[dict[str, Any]] = []
    support_cases: list[dict[str, Any]] = []
    for row in rows:
        products = row.get("product_records") or {}
        common = {"row_key": row["row_key"], "sentinel_id": row["sentinel_id"],
                  "grid_label": row["grid_label"], "family_id": row.get("family_id"),
                  "physical_case_id": row.get("physical_case_id"), "case_id": row.get("case_id"),
                  "attempt_id": row.get("attempt_id"), "producer_request": row.get("producer_request"),
                  "gencase_receipt": row.get("producer_receipt")}
        header_cases.append({**common, "native_bi4": products.get("native_bi4"), "decoder": decoder_record})
        source = row.get("source_binding") or {}
        support_case = {**common,
                        "source_xml": source.get("source_xml"), "source_def": source.get("source_def"),
                        "candidate_def": source.get("candidate_def"),
                        "generated_xml": products.get("generated_xml"),
                        "fluid_vtk": products.get("fluid_vtk"), "bound_vtk": products.get("bound_vtk"),
                        "native_bi4": products.get("native_bi4"),
                        "owner_predicate": source.get("owner_predicate"),
                        "physical_case_id": row.get("physical_case_id"),
                        "native_header_probe": None}
        support_cases.append(support_case)

    header_manifest = {"schema": HEADER_MANIFEST_SCHEMA, "status": header_status,
                       "cases": header_cases, "product_map": map_record,
                       "chain_manifest": chain_record, "source_closure_missing": closure_missing,
                       "scientific_qualification": dict(NO_CREDIT), "solver_launch": False,
                       "gencase_launch": False, "payload_read_by_builder": False}
    header_path = output_dir / "native-header-probe-manifest-v2.json"
    header_record = _write_once(header_path, header_manifest); static[header_record["path"]] = header_record
    header_request = _request(
        status=header_status, case_id="THREE_SENTINEL_OWNER_GRID_NATIVE_HEADER_PROBE_V3",
        command=[str(PYTHON), str(HEADER_WORKER), "--run", "--manifest",
                 "{attempt_root}/native-header-probe-manifest-v2.json", "--attempt-root", "{attempt_root}",
                 "--output", "{attempt_root}/report/native-header-probe-v3.json"],
        manifest_record=header_record, static=static, deferred=deferred + ([decoder_record] if decoder_record else []),
        variant="owner_grid_native_header_probe_v3", source_closure_missing=closure_missing)
    header_req_path = output_dir / "native-header-probe-request-v1.json"
    header_req_record = _write_once(header_req_path, header_request); static[header_req_record["path"]] = header_req_record

    support_manifest = {"schema": SUPPORT_MANIFEST_SCHEMA, "status": support_status,
                        "cases": support_cases, "product_map": map_record,
                        "chain_manifest": chain_record, "source_closure_missing": closure_missing,
                        "scientific_scope": {"neighbor_grid_truth": False, "interpolation": False,
                                             "mass_rescale": False, "xml_mass_fallback": False,
                                             "scientific_credit": 0, **NO_CREDIT},
                        "payload_read_by_builder": False, "solver_launch": False, "gencase_launch": False}
    support_path = output_dir / "initial-support-manifest-v1.json"
    support_record = _write_once(support_path, support_manifest); static[support_record["path"]] = support_record
    support_request = _request(
        status=support_status, case_id="THREE_SENTINEL_OWNER_GRID_INITIAL_SUPPORT_AUDIT",
        command=[str(PYTHON), str(SUPPORT_WORKER), "--run", "--manifest",
                 "{attempt_root}/initial-support-manifest-v1.json", "--attempt-root", "{attempt_root}",
                 "--output", "{attempt_root}/report/initial-support-v1.json"],
        manifest_record=support_record, static=static, deferred=deferred,
        variant="owner_grid_initial_support_audit_v1", source_closure_missing=closure_missing)
    support_req_path = output_dir / "initial-support-request-v1.json"
    support_req_record = _write_once(support_req_path, support_request); static[support_req_record["path"]] = support_req_record

    calibration_packages: list[dict[str, Any]] = []
    for sid in TARGETS:
        target_rows = [row for row in rows if row["sentinel_id"] == sid]
        target_dir = output_dir / sid.replace("-", "_"); target_dir.mkdir()
        calib_manifest = {"schema": CALIB_MANIFEST_SCHEMA,
                          "status": "WAITING_FOR_HEADER_AND_INITIAL_SUPPORT_REPORTS",
                          "sentinel_id": sid, "cases": target_rows,
                          "chain_manifest": chain_record,
                          "calibration_scales": _record_declared({"path": str(CALIB_SCALES), "sha256": None},
                                                                  f"{sid} calibration scales", role="calibration_scales"),
                          "scientific_scope": {"neighbor_grid_truth": False, "interpolation": False,
                                               "xml_mass_fallback": False, "mass_rescale": False,
                                               "scientific_credit": 0, **NO_CREDIT},
                          "source_closure_missing": closure_missing,
                          "payload_read_by_builder": False, "solver_launch": False, "gencase_launch": False}
        calib_path = target_dir / f"{sid.replace('-', '_')}-calibration-manifest-v1.json"
        calib_record = _write_once(calib_path, calib_manifest); static[calib_record["path"]] = calib_record
        calib_request = _request(
            status=calib_manifest["status"], case_id=f"{sid.replace('-', '_')}_CALIBRATION_PARENT",
            command=[str(PYTHON), str(CALIB_WORKER), "--run", "--manifest",
                     "{attempt_root}/calibration-manifest-v1.json", "--attempt-root", "{attempt_root}",
                     "--output", "{attempt_root}/report/calibration-v1.json"],
            manifest_record=calib_record, static=static, deferred=deferred,
            variant=f"{sid.lower().replace('-', '_')}_calibration_parent_v1", source_closure_missing=closure_missing)
        calib_req_path = target_dir / f"{sid.replace('-', '_')}-calibration-request-v1.json"
        calib_req_record = _write_once(calib_req_path, calib_request); static[calib_req_record["path"]] = calib_req_record
        calibration_packages.append({"sentinel_id": sid, "status": calib_manifest["status"],
                                     "manifest": calib_record, "request": calib_req_record,
                                     "scientific_qualification": dict(NO_CREDIT)})

    package = {"schema": "ds02.stage2.three-sentinel.owner-grid-post-gencase-chain-package.v1",
               "status": "READY_FOR_PARENT_CHAIN" if edge_ready else "WAITING_ACTUAL_NINE_GENCASE_PRODUCT_EDGES",
               "chain_manifest": chain_record, "native_header": {"manifest": header_record, "request": header_req_record},
               "initial_support": {"manifest": support_record, "request": support_req_record},
               "calibration": calibration_packages, "source_records": list(static.values()),
               "deferred_input_records": deferred, "source_closure_missing": closure_missing,
               "payload_read_by_builder": False, "scientific_qualification": dict(NO_CREDIT), "scientific_credit": 0}
    package_path = output_dir / "post-gencase-chain-package-v1.json"
    package_record = _write_once(package_path, package)
    return {"status": package["status"], "package": str(package_path), "package_record": package_record,
            "chain_manifest": str(chain_path), "header_request": str(header_req_path),
            "support_request": str(support_req_path), "calibration": calibration_packages,
            "scientific_credit": 0, "validation_errors": validation_errors,
            "source_closure_missing": closure_missing}


def _fixture_map(root: Path) -> Path:
    """Create exact nine tiny producer edges for contract tests only."""
    producer_dir = root / "producer"; producer_dir.mkdir()
    rows: list[dict[str, Any]] = []
    for sid in TARGETS:
        for grid in GRIDS:
            key = f"{sid}:{grid}"; case = root / key.replace(":", "_"); case.mkdir()
            q = {"schema": REQUEST_SCHEMA, "sentinel_id": sid, "grid_label": grid,
                 "family_id": sid[:2], "physical_case_id": f"P-{key}", "case_id": f"C-{key}",
                 "attempt_id": f"A-{key}", "cpu_task_kind": "gencase", "execution_allowed": True,
                 "source_only": False, "launch_disabled": False, "output_root": str(case),
                 "source_binding": {"source_xml": {"path": str(root / "source.xml"), "sha256": None},
                                     "source_def": {"path": str(root / "source_Def.xml"), "sha256": None},
                                     "candidate_def": {"path": str(root / "candidate_Def.xml"), "sha256": None},
                                     "owner_region_predicate": {"status": "UNKNOWN_CONTINUOUS_OWNER", "mass_rescale": False}}}
            qp = producer_dir / f"{key.replace(':', '_')}.json"; qp.write_text(json.dumps(q, sort_keys=True) + "\n", encoding="utf-8")
            receipt = {"schema": "ds02.execution-receipt.v1", "status": "COMPLETED_ACTUAL", "returncode": 0,
                       "output_root": str(case), "request_sha256": _sha(qp.read_bytes()), "request": q}
            rp = case / "execution-receipt.json"; rp.write_text(json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8")
            proof = {"schema": "ds02.stage2.root-owner-grid-gencase-proof.v2",
                     "status": "VERIFIED_ACTUAL_OWNER_GRID_GENCASE_PRODUCTS_NO_SCIENTIFIC_Q",
                     "sentinel_id": sid, "grid_label": grid, "family_id": sid[:2],
                     "physical_case_id": q["physical_case_id"], "case_id": q["case_id"], "attempt_id": q["attempt_id"],
                     "request_sha256": _sha(qp.read_bytes()), "products": {}}
            for name in ("generated.xml", "generated_Fluid.vtk", "generated_Bound.vtk", "generated.bi4"):
                path = case / name; path.write_bytes(b"tiny-product\n")
                role = {"generated.xml": "generated_xml", "generated_Fluid.vtk": "fluid_vtk",
                        "generated_Bound.vtk": "bound_vtk", "generated.bi4": "native_bi4"}[name]
                proof["products"][role] = {"path": str(path), "sha256": "PARENT_AFTER_RESERVATION_REQUIRED"}
            proof["products"]["gencase_receipt"] = {"path": str(rp), "sha256": _sha(rp.read_bytes())}
            pp = case / "proof.json"; pp.write_text(json.dumps(proof, sort_keys=True) + "\n", encoding="utf-8")
            rows.append({"sentinel_id": sid, "grid_label": grid, "family_id": sid[:2],
                         "physical_case_id": q["physical_case_id"], "case_id": q["case_id"], "attempt_id": q["attempt_id"],
                         "status": "ACTUAL_GENCASE_PRODUCT_COMPLETED",
                         "producer_request": {"path": str(qp), "sha256": _sha(qp.read_bytes())},
                         "actual_producer_proof": {"path": str(pp), "sha256": _sha(pp.read_bytes())},
                         "actual_control_cwd": str(case)})
    source_xml = root / "source.xml"; source_xml.write_text("<case/>\n", encoding="utf-8")
    source_def = root / "source_Def.xml"; source_def.write_text("<case dp='0.1'/>\n", encoding="utf-8")
    candidate_def = root / "candidate_Def.xml"; candidate_def.write_text("<case dp='0.05'/>\n", encoding="utf-8")
    path = root / "product-map.json"
    path.write_text(json.dumps({"schema": MAP_SCHEMA_PREFIX + ".v2", "status": "COMPLETED", "products": rows}, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="post-gencase-chain-v1-") as td:
        root = Path(td)
        # Handoff edge reads producer/proof/receipt JSON and stats products;
        # source binding is intentionally tiny.  No product bytes are opened
        # by build(), although the fixture creates them to exercise stat-only
        # records and the product-path contract.
        product_map = _fixture_map(root)
        output = root / "out"
        value = build(product_map, output)
        assert value["scientific_credit"] == 0
        package = json.loads(Path(value["package"]).read_text(encoding="utf-8"))
        assert len(package["source_records"]) >= 9
        assert package["native_header"]["request"]["path"]
        assert package["native_header"]["request"]["path"].endswith("native-header-probe-request-v1.json")
        assert package["scientific_qualification"] == NO_CREDIT
        for stage in ("native_header", "initial_support"):
            request = json.loads(Path(package[stage]["request"]["path"]).read_text(encoding="utf-8"))
            assert request["execution_allowed"] is False
            assert request["launch_disabled"] is True
            assert request["scientific_credit"] == 0
        # A duplicate row is a concrete product-map contradiction, not a
        # pending product.  The source package must reject it before output.
        bad = json.loads(product_map.read_text(encoding="utf-8"))
        bad["products"].append(dict(bad["products"][0]))
        bad_path = root / "bad-map.json"; bad_path.write_text(json.dumps(bad) + "\n", encoding="utf-8")
        try:
            build(bad_path, root / "bad-out")
        except ChainFailure as exc:
            assert "duplicate" in str(exc)
        else:
            raise AssertionError("duplicate actual product row was accepted")
        # Mutating the producer request while retaining its declared SHA must
        # be rejected by the exact raw-byte edge.
        first = bad["products"][0]
        qpath = Path(first["producer_request"]["path"])
        raw = qpath.read_text(encoding="utf-8"); qpath.write_text(raw.replace('"grid_label": "original"', '"grid_label": "fine"'), encoding="utf-8")
        tampered_result = build(product_map, root / "tampered-out")
        assert tampered_result["status"] == "WAITING_ACTUAL_NINE_GENCASE_PRODUCT_EDGES"
        assert tampered_result["validation_errors"], "tampered producer request was accepted"
    print("PASS_POST_GENCASE_CHAIN_V1_EXACT_NINE_SOURCE_ONLY_FIXTURE")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build", action="store_true")
    parser.add_argument("--product-map", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--decoder", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            _self_test(); return 0
        if args.product_map is None or args.output_dir is None:
            parser.error("--build requires --product-map and --output-dir")
        result = build(args.product_map, args.output_dir, decoder=args.decoder)
        print(json.dumps({"status": result["status"], "package": result["package"],
                          "header_request": result["header_request"],
                          "support_request": result["support_request"],
                          "scientific_credit": 0, "payload_read_by_builder": False}, sort_keys=True))
        return 0
    except (ChainFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"WAITING_OR_REJECTED_POST_GENCASE_CHAIN_V1: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
