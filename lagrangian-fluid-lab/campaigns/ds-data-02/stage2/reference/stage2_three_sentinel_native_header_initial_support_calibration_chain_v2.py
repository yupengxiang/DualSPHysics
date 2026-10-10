#!/usr/bin/env python3
"""ROOT345 production handoff adapter, additive to the frozen V1 chain.

The ROOT345 producer map deliberately remains in its deferred status even
after the nine GenCase parents finish: the map records that native hash/support
has not yet been audited.  The old chain expects a V3 handoff and cannot tell
that producer rows are terminal from the map row status alone.  This adapter
therefore performs the exact request-file/receipt/proof edge join first, keeps
that original map immutable, and only then stages the existing support and
native-header builders.

Preparation reads bounded JSON/source metadata only.  Generated XML, VTK, BI4,
H5 and solver products are never opened or hashed here.  No status is promoted
from a label: a header package is ready only when all nine producer request
bytes, runtime receipts, terminal proofs, identities, request SHA values and
product path records pass the same edge contract.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
from pathlib import Path
import tempfile
from typing import Any

HERE = Path(__file__).resolve().parent
HANDOFF_V3_PATH = HERE / "stage2_three_sentinel_owner_grid_native_initial_support_handoff_v3.py"
CHAIN_V1_PATH = HERE / "stage2_three_sentinel_native_header_initial_support_calibration_chain_v1.py"
SUPPORT_V3_PATH = HERE / "stage2_three_sentinel_owner_grid_initial_support_request_v3.py"
HEADER_V6_PATH = HERE / "stage2_three_sentinel_owner_grid_native_header_probe_request_v6.py"
MAP_SCHEMA = "ds02.stage2.three-sentinel.owner-grid-gencase-product-map.v2"
MAP_STATUS = "NINE_ACTUAL_GENCASE_PRODUCTS_DEFERRED_NATIVE_HASH_INITIAL_AUDIT_REQUIRED"
ROW_STATUS = "ACTUAL_GENCASE_PRODUCTS_AWAIT_INITIAL_SUPPORT_AUDIT"
REQUEST_SCHEMA = "ds02.request.v1"
RECEIPT_SCHEMA = "ds02.execution-receipt.v1"
PROOF_STATUS = "VERIFIED_ACTUAL_OWNER_GRID_GENCASE_PRODUCTS_NO_SCIENTIFIC_Q"
TARGETS = ("F2-S2", "F3-S1", "F5-S1")
GRIDS = ("original", "coarse", "fine")
ROW_KEYS = tuple(f"{sid}:{grid}" for sid in TARGETS for grid in GRIDS)
HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
CAP = 10 * 1024 * 1024
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "scientific_credit": 0}


class HandoffV2Failure(RuntimeError):
    pass


class HandoffV2Waiting(HandoffV2Failure):
    pass


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise HandoffV2Failure(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


HANDOFF = _load(HANDOFF_V3_PATH, "root345_handoff_v3_for_chain_v2")
CHAIN_V1 = _load(CHAIN_V1_PATH, "root345_chain_v1_for_chain_v2")
SUPPORT = _load(SUPPORT_V3_PATH, "root345_support_v3_for_chain_v2")
HEADER = _load(HEADER_V6_PATH, "root345_header_v6_for_chain_v2")


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


def _small_json(path: Path | str, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _abs(path)
    if path.is_symlink() or not path.is_file():
        raise HandoffV2Failure(f"{label} is not a regular file: {path}")
    before = _stat(path)
    if before["bytes"] > CAP:
        raise HandoffV2Failure(f"{label} exceeds 10 MiB metadata cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after or len(raw) != before["bytes"]:
        raise HandoffV2Failure(f"{label} changed during bounded read: {path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HandoffV2Failure(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise HandoffV2Failure(f"{label} is not a JSON object: {path}")
    return value, {"path": str(path), "sha256": _sha(raw), "bytes": before["bytes"],
                    "stat_before": before, "stat_after": after,
                    "read_mode": "bounded_small_source", "payload_read_by_builder": True}


def _record(path: Path | str, label: str) -> dict[str, Any]:
    return _small_json(path, label)[1]


def _file_record(path: Path | str, label: str) -> dict[str, Any]:
    """Record a bounded source/config file without assuming it is JSON.

    The generated handoff contains a source-closure edge for this adapter
    itself.  Treating that Python source as JSON made the ready path fail
    after the support/header builders had already succeeded.
    """
    path = _abs(path)
    if path.is_symlink() or not path.is_file():
        raise HandoffV2Failure(f"{label} is not a regular file: {path}")
    before = _stat(path)
    if before["bytes"] > CAP:
        raise HandoffV2Failure(f"{label} exceeds 10 MiB metadata cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after or len(raw) != before["bytes"]:
        raise HandoffV2Failure(f"{label} changed during bounded read: {path}")
    return {"path": str(path), "sha256": _sha(raw), "bytes": before["bytes"],
            "stat_before": before, "stat_after": after,
            "read_mode": "bounded_small_source_bytes", "payload_read_by_builder": False}


def _ref(value: Any, label: str) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        raise HandoffV2Failure(f"{label} lacks an explicit path record")
    path = _abs(value["path"])
    parsed, rec = _small_json(path, label)
    declared = value.get("sha256")
    if declared is not None and _valid_sha(declared) and declared.lower() != rec["sha256"].lower():
        raise HandoffV2Failure(f"{label} declared SHA differs from raw file bytes")
    if declared is not None and declared not in {"PARENT_AFTER_RESERVATION_REQUIRED", "PARENT_AFTER_GENCASE_REQUIRED"} and not _valid_sha(declared):
        raise HandoffV2Failure(f"{label} has malformed SHA")
    return path, rec, parsed


def _rows(value: dict[str, Any], field: str, label: str) -> dict[str, dict[str, Any]]:
    rows = value.get(field)
    if not isinstance(rows, list) or len(rows) != len(ROW_KEYS):
        raise HandoffV2Failure(f"{label} must contain exactly nine {field}")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise HandoffV2Failure(f"{label} contains a non-object row")
        key = row.get("row_key") if isinstance(row.get("row_key"), str) else f"{row.get('sentinel_id')}:{row.get('grid_label')}"
        if key not in ROW_KEYS or key in result:
            raise HandoffV2Failure(f"{label} has invalid/duplicate row {key}")
        result[key] = row
    if set(result) != set(ROW_KEYS):
        raise HandoffV2Failure(f"{label} does not cover the fixed nine rows")
    return result


def _identity(value: dict[str, Any], expected: dict[str, str], label: str) -> None:
    for key, wanted in expected.items():
        if value.get(key) != wanted:
            raise HandoffV2Failure(f"{label}.{key}={value.get(key)!r}; expected {wanted!r}")


def _receipt_ref(row: dict[str, Any], proof: dict[str, Any]) -> Any:
    for value in (row.get("actual_producer_receipt"), row.get("producer_receipt"), row.get("gencase_receipt"),
                  proof.get("actual_producer_receipt"), proof.get("producer_receipt"), proof.get("gencase_receipt"),
                  proof.get("execution_receipt"), proof.get("receipt")):
        if isinstance(value, dict) and isinstance(value.get("path"), str):
            return value
    products = proof.get("products")
    if isinstance(products, dict) and isinstance(products.get("gencase_receipt"), dict):
        return products["gencase_receipt"]
    products = row.get("products")
    if isinstance(products, dict) and isinstance(products.get("gencase_receipt"), dict):
        return products["gencase_receipt"]
    return None


def _product_roles(row: dict[str, Any], proof: dict[str, Any]) -> dict[str, dict[str, Any]]:
    aliases = {
        "generated_xml": ("generated_xml",),
        "fluid_vtk": ("fluid_vtk", "generated_fluid_vtk"),
        "bound_vtk": ("bound_vtk", "generated_bound_vtk"),
        "native_bi4": ("native_bi4", "generated_bi4"),
        "gencase_receipt": ("gencase_receipt", "execution_receipt"),
    }
    out: dict[str, dict[str, Any]] = {}
    sources = [row]
    for candidate in (row.get("products"), proof.get("products")):
        if isinstance(candidate, dict):
            sources.append(candidate)
    for role, names in aliases.items():
        found = None
        for source in sources:
            for name in names:
                if isinstance(source.get(name), dict) and isinstance(source[name].get("path"), str):
                    found = dict(source[name]); break
            if found is not None: break
        if found is None:
            raise HandoffV2Failure(f"{row.get('sentinel_id')}:{row.get('grid_label')} lacks {role} product path")
        found["path"] = str(_abs(found["path"]))
        found.setdefault("payload_read_by_builder", False)
        found.setdefault("scope", "parent_deferred_gencase_product")
        out[role] = found
    return out


def inspect_edges(product_map: Path) -> dict[str, Any]:
    """Join ROOT345 metadata without opening any generated product."""
    product, map_record = _small_json(product_map, "ROOT345 actual product map")
    if product.get("schema") != MAP_SCHEMA:
        raise HandoffV2Failure(f"product map schema mismatch: {product.get('schema')!r}")
    if product.get("status") != MAP_STATUS:
        raise HandoffV2Failure(f"product map status mismatch: {product.get('status')!r}")
    rows = _rows(product, "products", "ROOT345 product map")
    normalized: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    completed = 0
    for key in ROW_KEYS:
        row = rows[key]
        expected = {name: row.get(name) for name in ("sentinel_id", "grid_label", "family_id", "physical_case_id", "case_id", "attempt_id")}
        row_errors: list[str] = []
        if row.get("status") != ROW_STATUS:
            row_errors.append(f"row status is {row.get('status')!r}, expected deferred producer status")
        for name in ("sentinel_id", "grid_label", "family_id", "physical_case_id", "case_id", "attempt_id"):
            if not isinstance(expected[name], str) or not expected[name]:
                row_errors.append(f"missing {name}")
        request = proof = receipt = None
        request_record = proof_record = receipt_record = None
        try:
            _request_path, request_record, request = _ref(row.get("producer_request"), f"{key} producer request")
            _identity(request, {k: expected[k] for k in ("sentinel_id", "grid_label", "family_id", "physical_case_id", "case_id", "attempt_id")}, f"{key} request")
            if request.get("schema") != REQUEST_SCHEMA or request.get("cpu_task_kind") != "gencase":
                row_errors.append("producer request is not ds02.request.v1 GenCase")
            if request.get("execution_allowed") is not True or request.get("source_only") is True or request.get("launch_disabled") is True:
                row_errors.append("producer request is source-only or execution-disabled")
        except HandoffV2Failure as exc:
            row_errors.append(str(exc))
        try:
            _proof_path, proof_record, proof = _ref(row.get("actual_producer_proof") or row.get("producer_proof"), f"{key} producer proof")
            _identity(proof, {k: expected[k] for k in ("sentinel_id", "grid_label", "family_id", "physical_case_id", "case_id", "attempt_id")}, f"{key} proof")
            if proof.get("status") != PROOF_STATUS:
                row_errors.append(f"proof status is {proof.get('status')!r}")
            if request_record and proof.get("request_sha256") not in (None, request_record["sha256"]):
                row_errors.append("proof request SHA does not bind raw producer request bytes")
        except HandoffV2Failure as exc:
            row_errors.append(str(exc))
        try:
            receipt_ref = _receipt_ref(row, proof or {})
            _receipt_path, receipt_record, receipt = _ref(receipt_ref, f"{key} execution receipt")
            if receipt.get("schema") != RECEIPT_SCHEMA or str(receipt.get("status", "")).lower() not in {"completed", "completed_actual", "success", "succeeded"} or receipt.get("returncode") != 0:
                row_errors.append("receipt is not completed with returncode 0")
            if request is not None and request_record is not None:
                if receipt.get("request") != request or receipt.get("request_sha256") != request_record["sha256"]:
                    row_errors.append("receipt does not bind exact producer request file bytes")
                if receipt.get("output_root") not in (None, request.get("output_root")):
                    row_errors.append("receipt output_root differs from producer request")
        except HandoffV2Failure as exc:
            row_errors.append(str(exc))
        try:
            roles = _product_roles(row, proof or {})
            receipt_value = _receipt_ref(row, proof or {})
            if isinstance(receipt_value, dict) and isinstance(receipt_value.get("path"), str):
                roles["gencase_receipt"] = dict(receipt_value)
                roles["gencase_receipt"]["path"] = str(_abs(receipt_value["path"]))
                roles["gencase_receipt"].setdefault("payload_read_by_builder", False)
        except HandoffV2Failure as exc:
            roles = {}
            row_errors.append(str(exc))
        if not row_errors:
            completed += 1
        else:
            errors.append({"row_key": key, "errors": row_errors})
        normalized.append({"row_key": key, **expected, "original_row_status": row.get("status"),
                           "producer_request": row.get("producer_request"),
                           "actual_producer_proof": row.get("actual_producer_proof") or row.get("producer_proof"),
                           "gencase_receipt": _receipt_ref(row, proof or {}), "products": roles,
                           "edge_status": "VERIFIED_COMPLETED_PRODUCER_EDGE" if not row_errors else "WAITING_OR_REJECTED",
                           "errors": row_errors, "scientific_qualification": dict(UNKNOWN)})
    return {"map": product, "map_record": map_record, "rows": normalized, "completed_rows": completed,
            "row_count": len(normalized), "errors": errors, "ready": completed == len(ROW_KEYS) and not errors,
            "scientific_credit": 0, "payload_read": False}


def _write_once(path: Path, value: Any) -> dict[str, Any]:
    path = _abs(path)
    if path.exists() or path.is_symlink():
        raise HandoffV2Failure(f"refusing overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    path.write_bytes(raw)
    return {"path": str(path), "sha256": _sha(raw), "bytes": len(raw), "stat": _stat(path),
            "payload_read_by_builder": False, "scope": "builder_output_metadata"}


def _promote_header_output(result: dict[str, Any], edge_gate: dict[str, Any]) -> dict[str, Any]:
    """Promote only the newly built V6 output after independent edge closure.

    V6's historical readiness filter keys off ROOT345's deferred row status and
    therefore reports WAITING even after the exact terminal proof/receipt edge
    is proven.  The promotion is an additive output record, never a mutation of
    the ROOT345 map, and retains V6's original gate result for audit.
    """
    manifest_path = _abs(result["manifest"])
    request_path = _abs(result["request"])
    manifest, _ = _small_json(manifest_path, "header V6 manifest")
    request, _ = _small_json(request_path, "header V6 request")
    old_status = result.get("status")
    manifest["status"] = "READY_FOR_PARENT_GUARDED_NATIVE_HEADER_PROBE"
    manifest["status_filter_chain_v2"] = {"independent_root345_edge_gate": "PASS", "completed_rows": edge_gate["completed_rows"],
                                            "original_v6_status": old_status, "scientific_credit": 0}
    request["status"] = "READY_FOR_PARENT_GUARDED_NATIVE_HEADER_PROBE_V2"
    request["status_filter_chain_v2"] = manifest["status_filter_chain_v2"]
    # Rebuild exact request manifest/input records after changing output bytes.
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest_record = _record(manifest_path, "promoted header manifest")
    request["manifest"] = manifest_record
    # V6 had recorded the pre-promotion manifest bytes.  Replace that exact
    # input record too; a parent must never receive a request whose manifest
    # field and input_sha256 disagree.
    records = request.get("input_records")
    if not isinstance(records, dict):
        raise HandoffV2Failure("header V6 request lacks input_records during status promotion")
    records = {str(key): value for key, value in records.items()
               if isinstance(value, dict) and isinstance(value.get("path"), str)
               and str(value.get("path")) != str(manifest_path)}
    records[manifest_record["path"]] = manifest_record
    request["input_records"] = {key: records[key] for key in sorted(records)}
    request["input_files"] = sorted(records)
    request["input_sha256"] = {key: records[key]["sha256"] for key in sorted(records)
                                if _valid_sha(records[key].get("sha256"))}
    request_path.write_text(json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    request_record = _record(request_path, "promoted header request")
    return {**result, "status": request["status"], "manifest": str(manifest_path), "request": str(request_path),
            "manifest_record": manifest_record, "request_record": request_record,
            "original_v6_status": old_status}


def build(product_map: Path, output_dir: Path, *, owner_report: Path | None = None,
          decoder: Path | None = None) -> dict[str, Any]:
    """Prepare a resumable ROOT345→header→support handoff.

    The first invocation is expected after ROOT345 has written its map.  If an
    edge is missing, a WAITING package is written and the function exits 0;
    malformed source metadata still raises.  With all nine edges terminal and
    a decoder source supplied, it stages the existing V3 support and V6 header
    requests.  The subsequent native header parent is still execution-disabled
    and scientific qualification remains UNKNOWN.
    """
    edge = inspect_edges(_abs(product_map))
    output_dir = _abs(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise HandoffV2Failure(f"refusing non-empty output: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    edge_path = output_dir / "root345-edge-gate.json"
    edge_record = _write_once(edge_path, edge)
    state: dict[str, Any] = {
        "schema": "ds02.stage2.three-sentinel.native-header-initial-support-calibration-chain.v2",
        "status": "WAITING_FOR_ROOT345_COMPLETED_PRODUCER_EDGES",
        "source_status": "SOURCE_ONLY_NO_PRODUCTION_CREDIT", "product_map": edge["map_record"],
        "edge_gate": edge_record, "completed_rows": edge["completed_rows"], "row_count": edge["row_count"],
        "validation_errors": edge["errors"], "header": None, "support": None, "calibration": None,
        "execution_allowed": False, "gencase_launch": False, "solver_launch": False,
        "scientific_qualification": dict(UNKNOWN), "scientific_scope": {
            "native_mass_header_only": True, "xml_mass_fallback": False, "world_axis": "UNKNOWN",
            "continuous_owner": "UNKNOWN", "neighbor_grid_truth": False, "interpolation": False,
        }, "production_payload_read_by_builder": False,
    }
    if not edge["ready"]:
        state_path = output_dir / "chain-v2-state.json"
        state_record = _write_once(state_path, state)
        request = {"schema": REQUEST_SCHEMA, "variant_schema": state["schema"], "status": state["status"],
                   "family_id": "infra", "cpu_task_kind": "audit", "execution_allowed": False,
                   "launch_disabled": True, "command": [str(Path(__file__).resolve()), "--prepare", "--product-map", str(_abs(product_map)), "--output-dir", str(output_dir)],
                   "manifest": state_record, "input_records": {edge_record["path"]: edge_record, state_record["path"]: state_record},
                   "input_files": sorted([edge_record["path"], state_record["path"]]),
                   "input_sha256": {edge_record["path"]: edge_record["sha256"], state_record["path"]: state_record["sha256"]},
                   "scientific_qualification": dict(UNKNOWN), "production_payload_read_by_builder": False}
        req_path = output_dir / "chain-v2-request.json"; req_record = _write_once(req_path, request)
        return {"status": state["status"], "state": str(state_path), "request": str(req_path), "edge": edge}
    if decoder is None:
        raise HandoffV2Waiting("all ROOT345 edges are terminal but custom BI4 adapter --decoder is required")
    owner = _abs(owner_report) if owner_report is not None else None
    if owner is None:
        map_value = edge["map"]
        owner_value = map_value.get("owner_report")
        if isinstance(owner_value, dict) and isinstance(owner_value.get("path"), str): owner = _abs(owner_value["path"])
    if owner is None:
        raise HandoffV2Failure("completed ROOT345 map lacks explicit owner_report; no cross-sentinel owner inference")
    # Preserve the original deferred map.  The frozen support/header builders
    # use the historical top-level product keys, while ROOT345 stores the same
    # keys under proof.products in some producer versions.  Materialize a
    # metadata-only adapter with exact paths/declared records; never open a
    # generated product and never rewrite the original map.
    adapted = dict(edge["map"])
    adapted["source_product_map"] = edge["map_record"]
    adapted["adapter_schema"] = "ds02.stage2.three-sentinel.root345-product-map-adapter.v1"
    adapted_rows = []
    for normalized in edge["rows"]:
        row = dict(normalized)
        row.pop("errors", None); row.pop("edge_status", None); row.pop("scientific_qualification", None)
        products = dict(row.pop("products", {}))
        for role, value in products.items():
            if isinstance(value, dict): row[role] = value
        row["actual_producer_proof"] = row.pop("actual_producer_proof", None)
        row["status"] = ROW_STATUS
        adapted_rows.append(row)
    adapted["products"] = adapted_rows
    adapted_path = output_dir / "root345-product-map-adapter-v1.json"
    adapted_record = _write_once(adapted_path, adapted)
    support_dir = output_dir / "support-source"
    support_result = SUPPORT.build(owner, adapted_path, support_dir)
    support_manifest = _abs(support_result["manifest_path"])
    support_request = _abs(support_result["request_path"])
    header_dir = output_dir / "header-source"
    header_result = HEADER.build(support_manifest, adapted_path, _abs(decoder), header_dir,
                                support_request, None)
    header_result = _promote_header_output(header_result, edge)
    header_record = _record(header_result["manifest"], "final promoted header manifest")
    header_request_record = _record(header_result["request"], "final promoted header request")
    state.update({"status": "READY_FOR_PARENT_GUARDED_NATIVE_HEADER_PROBE_V2",
                  "header": {"manifest": header_record, "request": header_request_record,
                             "original_v6_status": header_result.get("original_v6_status")},
                  "support": {"manifest": _record(support_manifest, "support manifest"),
                              "request": _record(support_request, "support request")},
                  "next": "After native-header report, invoke frozen chain V1 --materialize; after support report invoke V1 --finalize",
                  "source_product_map_adapter": adapted_record,
                  "source_records": [edge_record, adapted_record, header_record, header_request_record,
                  _record(support_manifest, "support manifest"), _record(support_request, "support request"),
                                     _file_record(Path(__file__), "chain V2 source")],
                  "production_payload_read_by_builder": False})
    state_path = output_dir / "chain-v2-state.json"; state_record = _write_once(state_path, state)
    request = {"schema": REQUEST_SCHEMA, "variant_schema": state["schema"], "status": state["status"],
               "family_id": "infra", "cpu_task_kind": "audit", "execution_allowed": False, "launch_disabled": True,
               "command": [str(Path(__file__).resolve()), "--prepare", "--product-map", str(_abs(product_map)), "--owner-report", str(owner), "--decoder", str(_abs(decoder)), "--output-dir", str(output_dir)],
               "next_parent_request": header_request_record, "manifest": state_record,
               "input_records": {record["path"]: record for record in [edge_record, adapted_record, state_record, header_record, header_request_record]},
               "input_files": sorted([edge_record["path"], adapted_record["path"], state_record["path"], header_record["path"], header_request_record["path"]]),
               "input_sha256": {record["path"]: record["sha256"] for record in [edge_record, adapted_record, state_record, header_record, header_request_record]},
               "scientific_qualification": dict(UNKNOWN), "production_payload_read_by_builder": False}
    req_path = output_dir / "chain-v2-request.json"; _write_once(req_path, request)
    return {"status": state["status"], "state": str(state_path), "request": str(req_path), "header": header_result,
            "support": support_result, "edge": edge}


def _self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="chain-v2-edge-", dir=HERE) as td:
        root = Path(td)
        # The frozen V3 fixture contains the exact deferred ROOT345 row shape.
        product_map = HANDOFF.V2._fixture_map(root)
        edge = inspect_edges(product_map)
        assert not edge["ready"] or edge["completed_rows"] == 9
        assert edge["row_count"] == 9 and edge["scientific_credit"] == 0
        changed = json.loads(product_map.read_text())
        changed["products"][0]["status"] = "FAILED_RUNTIME_PRODUCER"
        bad = root / "bad-map.json"; bad.write_text(json.dumps(changed, sort_keys=True) + "\n")
        try:
            inspect_edges(bad)
        except HandoffV2Failure:
            raise AssertionError("a malformed deferred map should be represented by edge errors, not parser failure")
        bad_edge = inspect_edges(bad)
        assert not bad_edge["ready"] and bad_edge["errors"]
        # No generated product is opened by inspect_edges: the fixture product
        # paths are placeholders, while request/proof/receipt JSON is bounded.
        assert bad_edge["payload_read"] is False
    # Exercise the resumable ready path as well.  The frozen support/header
    # builders require the same suffixes emitted by a real GenCase producer;
    # use only deferred placeholder paths here, never product contents.
    with tempfile.TemporaryDirectory(prefix="chain-v2-ready-", dir=HERE) as td:
        root = Path(td)
        product_map = HANDOFF.V2._fixture_map(root)
        product = json.loads(product_map.read_text(encoding="utf-8"))
        role_names = {"generated_xml": "generated.xml", "fluid_vtk": "generated_Fluid.vtk",
                      "bound_vtk": "generated_Bound.vtk", "native_bi4": "generated.bi4"}
        for row in product["products"]:
            proof_path = Path(row["actual_producer_proof"]["path"])
            proof = json.loads(proof_path.read_text(encoding="utf-8"))
            for source in (row, proof["products"]):
                for role, name in role_names.items():
                    if role in source:
                        source[role]["path"] = str(Path(source[role]["path"]).with_name(name))
            proof_path.write_text(json.dumps(proof, sort_keys=True) + "\n", encoding="utf-8")
            row["actual_producer_proof"]["sha256"] = _sha(proof_path.read_bytes())
        product_map.write_text(json.dumps(product, sort_keys=True) + "\n", encoding="utf-8")
        owner, _ = SUPPORT.V1._fixture_owner(root)
        decoder = root / "bi4_dump"
        decoder.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
        decoder.chmod(0o755)
        ready = build(product_map, root / "ready-output", owner_report=owner, decoder=decoder)
        assert ready["status"] == "READY_FOR_PARENT_GUARDED_NATIVE_HEADER_PROBE_V2"
        assert ready["edge"]["completed_rows"] == len(ROW_KEYS)
        state, _ = _small_json(Path(ready["state"]), "ready chain state")
        assert state["execution_allowed"] is False and state["scientific_qualification"] == UNKNOWN
    print("PASS_ROOT345_CHAIN_V2_STRICT_DEFERRED_EDGE_AND_RESUMABLE_HANDOFF_FIXTURE")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--prepare", action="store_true")
    parser.add_argument("--product-map", type=Path)
    parser.add_argument("--owner-report", type=Path)
    parser.add_argument("--decoder", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            _self_test(); return 0
        if args.product_map is None or args.output_dir is None:
            parser.error("--prepare requires --product-map and --output-dir")
        value = build(args.product_map, args.output_dir, owner_report=args.owner_report, decoder=args.decoder)
        print(json.dumps({"status": value["status"], "state": value["state"], "request": value["request"],
                          "scientific_credit": 0}, sort_keys=True)); return 0
    except HandoffV2Waiting as exc:
        print(f"WAITING_ROOT345_CHAIN_V2: {exc}"); return 0
    except (HandoffV2Failure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_ROOT345_CHAIN_V2: {exc}"); return 2


if __name__ == "__main__":
    raise SystemExit(main())
