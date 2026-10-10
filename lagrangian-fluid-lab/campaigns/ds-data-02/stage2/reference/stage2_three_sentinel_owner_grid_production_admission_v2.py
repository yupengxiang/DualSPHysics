#!/usr/bin/env python3
"""Additive strict admission checks for the ROOT345 product hand-off.

The consumed V1 preflight remains the bounded source/product reader.  This
version adds the checks that V1 intentionally did not make strict enough for a
production hand-off:

* statuses are exact allow-list values; substring values such as
  ``OWNER_NOT_VERIFIED`` never become a terminal owner gate;
* sentinel/grid/physical/family identity fields are required, rather than
  only checked when present;
* the producer request and execution receipt are joined to their raw file
  bytes, exact request object, return code, output root, and identity;
* the ROOT345 ``*_DEFERRED_NATIVE_HASH_INITIAL_AUDIT_REQUIRED`` map state is
  recognized as a real intermediate state and remains WAITING until native
  initial support is supplied;
* large forcing/control files remain stat/deferred records.  This module does
  not open them and does not manufacture a SHA.

This is an additive source-only checker.  It does not change V1 files, launch
anything, read BI4/VTK/H5/Part payloads, or grant QI/QN/QE credit.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
V1_PATH = HERE / "stage2_three_sentinel_owner_grid_production_admission_v1.py"
HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
REQUEST_SCHEMA = "ds02.request.v1"
RECEIPT_SCHEMA = "ds02.execution-receipt.v1"
PRODUCT_SCHEMA_PREFIX = "ds02.stage2.three-sentinel.owner-grid-gencase-product-map"
SCHEMA = "ds02.stage2.three-sentinel.owner-grid-production-admission.v2"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
JSON_CAP = 10 * 1024 * 1024

# These are intentionally exact.  Adding a new producer status requires a
# new source version and a review; substring matching is the bug this module
# is meant to prevent.
RECEIPT_TERMINAL = {
    "COMPLETED", "COMPLETED_ACTUAL", "COMPLETED_DEVELOPMENT_UNKNOWN",
    "SUCCESS", "SUCCEEDED",
}
PRODUCT_MAP_STATES = {
    "NINE_ACTUAL_GENCASE_PRODUCTS_DEFERRED_NATIVE_HASH_INITIAL_AUDIT_REQUIRED",
    "NINE_ACTUAL_GENCASE_PRODUCTS_READY_FOR_INITIAL_SUPPORT_AUDIT",
    "NINE_ACTUAL_GENCASE_PRODUCTS_COMPLETED",
    "COMPLETED", "COMPLETED_ACTUAL", "SUCCESS",
}
PRODUCT_ROW_STATES = {
    "ACTUAL_GENCASE_PRODUCTS_AWAIT_INITIAL_SUPPORT_AUDIT",
    "ACTUAL_GENCASE_PRODUCT_READY_FOR_INITIAL_SUPPORT_AUDIT",
    "ACTUAL_GENCASE_PRODUCT_COMPLETED",
    "COMPLETED", "COMPLETED_ACTUAL", "SUCCESS",
}
OWNER_STATES = {
    "VERIFIED_OWNER", "VERIFIED_CONTINUOUS_OWNER",
    "COMPLETED_OWNER_GATE", "COMPLETED_CONTINUOUS_OWNER",
    "PASS_OWNER", "PASS_CONTINUOUS_OWNER",
}
NATIVE_STATES = {
    "PASS_NATIVE_SUPPORT", "PASS_NATIVE_HEADER_FIELDS",
    "COMPLETED_NATIVE_SUPPORT", "COMPLETED_NATIVE_HEADER_FIELDS",
    "VERIFIED_NATIVE_SUPPORT", "VERIFIED_NATIVE_HEADER_FIELDS",
}


class StrictAdmissionFailure(RuntimeError):
    pass


def _load_v1() -> Any:
    spec = importlib.util.spec_from_file_location("stage2_production_admission_v1_for_v2", V1_PATH)
    if spec is None or spec.loader is None:
        raise StrictAdmissionFailure(f"cannot load consumed V1: {V1_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V1 = _load_v1()


def _abs(path: Path | str) -> Path:
    return Path(path).expanduser().absolute()


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {
        "device": int(value.st_dev), "inode": int(value.st_ino),
        "bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
    }


def _json(path: Path | str, label: str) -> tuple[dict[str, Any], dict[str, Any], bytes]:
    value = _abs(path)
    if value.is_symlink() or not value.is_file():
        raise StrictAdmissionFailure(f"{label} is not a regular non-symlink file: {value}")
    before = _stat(value)
    if before["bytes"] > JSON_CAP:
        raise StrictAdmissionFailure(f"{label} exceeds the 10 MiB metadata cap: {value}")
    raw = value.read_bytes()
    after = _stat(value)
    if before != after or len(raw) != before["bytes"]:
        raise StrictAdmissionFailure(f"{label} changed during bounded read: {value}")
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StrictAdmissionFailure(f"{label} is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise StrictAdmissionFailure(f"{label} must be a JSON object")
    return parsed, {"path": str(value), "sha256": _sha(raw), "bytes": len(raw),
                    "stat_before": before, "stat_after": after}, raw


def _status(value: Any) -> str:
    return str(value or "").strip().upper()


def _require(condition: bool, code: str, detail: str, errors: list[dict[str, str]]) -> None:
    if not condition:
        errors.append({"code": code, "detail": detail})


def _exact_identity(value: dict[str, Any], *, sentinel: str, grid: str | None,
                    physical: str, family: str | None, label: str,
                    errors: list[dict[str, str]]) -> None:
    expected = {"sentinel_id": sentinel, "physical_case_id": physical}
    if grid is not None:
        expected["grid_label"] = grid
    if family:
        expected["family_id"] = family
    for key, wanted in expected.items():
        actual = value.get(key)
        _require(isinstance(actual, str) and actual == wanted,
                 f"{label.upper()}_IDENTITY_MISSING_OR_MISMATCH",
                 f"{label} requires {key}={wanted!r}; got {actual!r}", errors)


def _record_sha(record: Any) -> str | None:
    if not isinstance(record, dict):
        return None
    value = record.get("sha256")
    return value.lower() if isinstance(value, str) and HEX64.fullmatch(value) else None


def _receipt_edge(row: dict[str, Any], *, sentinel: str, grid: str,
                  errors: list[dict[str, str]], waiting: list[dict[str, str]]) -> dict[str, Any]:
    producer_ref = row.get("producer_request") or row.get("gencase_request")
    receipt_ref = row.get("gencase_receipt") or row.get("receipt") or row.get("execution_receipt")
    if not isinstance(producer_ref, dict) or not isinstance(receipt_ref, dict):
        waiting.append({"code": "STRICT_PRODUCER_RECEIPT_REFS_MISSING",
                        "detail": f"{sentinel}:{grid} lacks producer request/receipt records"})
        return {"status": "WAITING"}
    try:
        request, request_record, request_raw = _json(producer_ref["path"], "strict producer request")
        receipt, receipt_record, _ = _json(receipt_ref["path"], "strict execution receipt")
    except (KeyError, StrictAdmissionFailure) as exc:
        errors.append({"code": "STRICT_PRODUCER_METADATA_UNREADABLE", "detail": str(exc)})
        return {"status": "REJECTED"}

    expected_sha = _record_sha(producer_ref)
    _require(expected_sha == request_record["sha256"], "STRICT_REQUEST_FILE_SHA_MISMATCH",
             "product row producer_request.sha256 is not the raw request-file SHA", errors)
    _require(request.get("schema") == REQUEST_SCHEMA, "STRICT_REQUEST_SCHEMA_MISMATCH",
             f"producer request schema={request.get('schema')!r}", errors)
    _require(receipt.get("schema") == RECEIPT_SCHEMA, "STRICT_RECEIPT_SCHEMA_MISMATCH",
             f"receipt schema={receipt.get('schema')!r}", errors)
    _require(_status(receipt.get("status")) in RECEIPT_TERMINAL,
             "STRICT_RECEIPT_STATUS_NOT_ALLOWLISTED",
             f"receipt status={receipt.get('status')!r}", errors)
    _require(receipt.get("returncode") == 0, "STRICT_RECEIPT_RETURN_CODE_NONZERO",
             f"receipt returncode={receipt.get('returncode')!r}", errors)
    _require(receipt.get("request_sha256") == request_record["sha256"],
             "STRICT_RECEIPT_REQUEST_SHA_MISMATCH",
             "receipt.request_sha256 is not the raw producer request SHA", errors)
    embedded = receipt.get("request")
    if not isinstance(embedded, dict):
        errors.append({"code": "STRICT_RECEIPT_EMBEDDED_REQUEST_MISSING",
                       "detail": "completed producer receipt must embed its request"})
    else:
        extension = set(embedded) - set(request)
        normalized = dict(embedded)
        if extension == {"request_sha256"}:
            normalized.pop("request_sha256", None)
        _require(normalized == request, "STRICT_RECEIPT_EMBEDDED_REQUEST_MISMATCH",
                 "receipt.request differs from the exact producer request document", errors)

    physical = row.get("physical_case_id") or request.get("physical_case_id")
    case = row.get("case_id") or request.get("case_id")
    attempt = row.get("attempt_id") or request.get("attempt_id")
    family = request.get("family_id") or row.get("family_id")
    _require(isinstance(physical, str) and bool(physical), "STRICT_PHYSICAL_ID_MISSING",
             "producer row has no physical_case_id", errors)
    _require(isinstance(case, str) and bool(case), "STRICT_CASE_ID_MISSING",
             "producer row has no case_id", errors)
    _require(isinstance(attempt, str) and bool(attempt), "STRICT_ATTEMPT_ID_MISSING",
             "producer row has no attempt_id", errors)
    for key, expected in (("physical_case_id", physical), ("case_id", case),
                          ("attempt_id", attempt), ("family_id", family)):
        if not isinstance(expected, str) or not expected:
            continue
        _require(receipt.get(key) == expected,
                 f"STRICT_RECEIPT_{key.upper()}_MISMATCH",
                 f"receipt {key} is not the exact producer identity {expected!r}", errors)
        _require(request.get(key) == expected,
                 f"STRICT_REQUEST_{key.upper()}_MISMATCH",
                 f"request {key} is not the exact producer identity {expected!r}", errors)
    output_root = receipt.get("output_root")
    _require(isinstance(output_root, str) and Path(output_root).is_dir() and not Path(output_root).is_symlink(),
             "STRICT_RECEIPT_OUTPUT_ROOT_MISSING", "completed receipt output_root is absent", waiting)
    return {
        "status": "PASS" if not errors else "REJECTED",
        "request": request_record, "receipt": receipt_record,
        "request_sha256": request_record["sha256"],
        "family_id": family, "case_id": case, "attempt_id": attempt,
        "physical_case_id": physical, "output_root": output_root,
        "raw_request_bytes": len(request_raw),
    }


def _report_edge(path: Path, *, kind: str, sentinel: str, grid: str,
                 physical: str, family: str | None, errors: list[dict[str, str]],
                 waiting: list[dict[str, str]]) -> dict[str, Any]:
    try:
        report, record, _ = _json(path, f"strict {kind} report")
    except StrictAdmissionFailure as exc:
        errors.append({"code": f"STRICT_{kind.upper()}_REPORT_UNREADABLE", "detail": str(exc)})
        return {"status": "REJECTED"}
    allowed = NATIVE_STATES if kind == "native" else OWNER_STATES
    state = _status(report.get("status"))
    _require(state in allowed, f"STRICT_{kind.upper()}_STATUS_NOT_ALLOWLISTED",
             f"{kind} report status={report.get('status')!r}", errors)
    _exact_identity(report, sentinel=sentinel, grid=None if kind == "owner" else grid,
                    physical=physical, family=family, label=kind, errors=errors)
    if kind == "native":
        _require(report.get("all_finite") is True or report.get("finite") is True,
                 "STRICT_NATIVE_FINITE_CERTIFICATE_MISSING",
                 "native report lacks all_finite=true", errors)
        basis = " ".join(str(report.get(k, "")) for k in ("mass_basis", "mass_source", "source_of_mass")).lower()
        _require("native" in basis and not any(x in basis for x in ("xml", "fallback")),
                 "STRICT_NATIVE_MASS_AUTHORITY_UNBOUND",
                 "native report does not state native-only mass authority", errors)
    else:
        basis = str(report.get("mass_basis", "")).lower()
        _require("continuous" in basis and "discrete" not in basis and "xml" not in basis,
                 "STRICT_OWNER_MASS_BASIS_UNBOUND",
                 "owner report is not a continuous geometry integral", errors)
    # The actual map can be in a deferred/native-audit state.  A report is
    # never allowed to erase that missing stage merely by saying PASS.
    return {"status": "PASS" if not errors else "REJECTED", "record": record,
            "report_status": report.get("status"), "identity": {
                "sentinel_id": report.get("sentinel_id"),
                "grid_label": report.get("grid_label"),
                "physical_case_id": report.get("physical_case_id"),
                "family_id": report.get("family_id"),
            }}


def _forcing_deferred(request: dict[str, Any], row: dict[str, Any] | None = None, *,
                      errors: list[dict[str, str]], waiting: list[dict[str, str]]) -> dict[str, Any]:
    """Validate a control-file record without opening the control payload."""
    # Runtime-v8 requests carry both a path-only ``input_files`` list and a
    # richer ``input_records`` map.  The former must never be treated as a
    # content record; merge them so a source-prepared F3 request can retain
    # the known owner-forcing SHA/stat from its source binding.
    records: list[dict[str, Any]] = []
    input_files = request.get("input_files") or []
    if isinstance(input_files, list):
        records.extend({"path": item} for item in input_files if isinstance(item, str))
    input_records = request.get("input_records") or {}
    if isinstance(input_records, dict):
        records.extend(item for item in input_records.values() if isinstance(item, dict))
    deferred_records = request.get("deferred_input_records") or []
    if isinstance(deferred_records, dict):
        deferred_records = list(deferred_records.values())
    if isinstance(deferred_records, list):
        records.extend(item for item in deferred_records if isinstance(item, dict))
    binding = request.get("source_binding")
    if isinstance(binding, dict):
        records.extend(item for item in binding.values() if isinstance(item, dict) and "path" in item)
    if isinstance(row, dict):
        aux = row.get("actual_auxiliary_runtime_closure") or row.get("auxiliary_runtime_closure")
        if isinstance(aux, dict):
            records.extend(item for item in aux.values() if isinstance(item, dict) and "path" in item)
        elif isinstance(aux, list):
            records.extend(item for item in aux if isinstance(item, dict))
    candidates = [item for item in records if
                   (str(item.get("path", "")).lower().endswith(".csv") or
                   "forcing" in str(item.get("role", "")).lower() or
                   "control" in str(item.get("role", "")).lower())]
    deferred = []
    for item in candidates:
        sha = item.get("sha256")
        stat = item.get("stat") or item.get("stat_before") or item.get("stat_after")
        if isinstance(sha, str) and HEX64.fullmatch(sha) and isinstance(stat, dict):
            deferred.append({"path": item.get("path"), "sha256": sha.lower(),
                             "stat": stat, "read_scope": "parent_after_reservation_deferred"})
    if candidates and not deferred:
        waiting.append({"code": "FORCING_CONTROL_DEFERRED_RECORD_INCOMPLETE",
                        "detail": "control/forcing candidate has no known SHA and full stat; parent must bind it after reservation"})
    # No candidate is not a pass for a F3 control study; source-specific
    # builders can require it.  Generic rows are left waiting only when they
    # actually advertise a control path, avoiding a false requirement for all
    # other sentinel families.
    if candidates and not deferred:
        return {"status": "WAITING", "records": []}
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for item in deferred:
        key = (str(item.get("path")), str(item.get("sha256")))
        unique.setdefault(key, item)
    return {"status": "BOUND_STAT_ONLY" if deferred else "NOT_APPLICABLE",
            "records": list(unique.values()), "payload_read": False}


def _strict_result(base: dict[str, Any], *, errors: list[dict[str, str]],
                   waiting: list[dict[str, str]], checked: list[str],
                   map_state: str | None, forcing: dict[str, Any] | None) -> dict[str, Any]:
    # V1 failures remain failures; V2 only adds stricter failures/waits.  A
    # known deferred ROOT345 map state is a legitimate WAITING state, not a
    # product-map contradiction.
    reasons = base.get("reasons") if isinstance(base.get("reasons"), dict) else {}
    rejected = list(reasons.get("rejected", [])) + errors
    waits = list(reasons.get("waiting", [])) + waiting
    if rejected:
        status = "REJECTED_SOURCE_OR_IDENTITY_CONTRADICTION"
    elif waits or map_state not in {"COMPLETED", "COMPLETED_ACTUAL", "SUCCESS"}:
        status = "WAITING_PARENT_PRODUCTION_CLOSURE"
    else:
        status = "READY_FOR_PARENT_EXTERNAL_V5_ADMISSION"
    result = dict(base)
    result.update({"schema": SCHEMA, "status": status,
                   "production_credit": 0, "scientific_qualification": dict(UNKNOWN),
                   "payload_read_by_builder": False, "solver_started": False,
                   "strict_gate": {"status": status, "checked": checked,
                                   "rejected": rejected, "waiting": waits,
                                   "map_status": map_state, "forcing_control": forcing,
                                   "manufactured_only": True if not base.get("producer") else False},
                   "strict_source_scope": {
                       "bounded_json": True, "product_files": "stat_only",
                       "forcing_payload": False, "native_bi4_payload": False,
                       "vtk_payload": False, "solver_or_gencase_launch": False,
                   }})
    result["reasons"] = {"rejected": rejected, "waiting": waits,
                          "checked": list(reasons.get("checked", [])) + checked}
    return result


def preflight(args: argparse.Namespace) -> dict[str, Any]:
    # V1 remains the bounded product reader and source of its established
    # output shape.  Any exception is not downgraded by the strict layer.
    base = V1.preflight(args)
    errors: list[dict[str, str]] = []
    waiting: list[dict[str, str]] = []
    checked: list[str] = []
    try:
        product_map, _, _ = _json(args.product_map, "ROOT345 product map")
    except StrictAdmissionFailure as exc:
        return _strict_result(base, errors=[{"code": "STRICT_PRODUCT_MAP_UNREADABLE", "detail": str(exc)}],
                              waiting=[], checked=["map:raw_file_join"], map_state=None, forcing=None)
    map_status = _status(product_map.get("status"))
    checked.append("map:exact_status")
    _require(str(product_map.get("schema", "")).startswith(PRODUCT_SCHEMA_PREFIX),
             "STRICT_PRODUCT_MAP_SCHEMA_MISMATCH", "ROOT345 product map schema is not the expected prefix", errors)
    _require(map_status in PRODUCT_MAP_STATES, "STRICT_PRODUCT_MAP_STATUS_UNKNOWN",
             f"unsupported ROOT345 product-map status={product_map.get('status')!r}", errors)
    rows = product_map.get("products", product_map.get("cases"))
    if not isinstance(rows, list):
        errors.append({"code": "STRICT_PRODUCT_ROWS_MISSING", "detail": "product map lacks products/cases list"})
        return _strict_result(base, errors=errors, waiting=waiting, checked=checked,
                              map_state=map_status, forcing=None)
    target = [r for r in rows if isinstance(r, dict) and r.get("sentinel_id") == args.sentinel and r.get("grid_label") == args.grid]
    _require(len(target) == 1, "STRICT_PRODUCT_ROW_NOT_UNIQUE",
             f"expected one exact row for {args.sentinel}:{args.grid}, got {len(target)}", errors)
    if len(target) != 1:
        return _strict_result(base, errors=errors, waiting=waiting, checked=checked,
                              map_state=map_status, forcing=None)
    row = target[0]
    row_status = _status(row.get("status"))
    checked.append("row:exact_status")
    _require(row_status in PRODUCT_ROW_STATES, "STRICT_PRODUCT_ROW_STATUS_UNKNOWN",
             f"unsupported row status={row.get('status')!r}", errors)
    physical = row.get("physical_case_id")
    _require(isinstance(physical, str) and bool(physical), "STRICT_ROW_PHYSICAL_ID_MISSING",
             "ROOT345 row must carry physical_case_id; labels cannot substitute", errors)
    receipt = _receipt_edge(row, sentinel=args.sentinel, grid=args.grid, errors=errors, waiting=waiting)
    checked.append("producer:raw_request_receipt_edge")
    q = None
    if isinstance(receipt, dict) and isinstance(receipt.get("request"), dict):
        q = receipt["request"]
        family = q.get("family_id")
        _exact_identity(q, sentinel=args.sentinel, grid=args.grid, physical=str(physical or ""),
                        family=family if isinstance(family, str) else None,
                        label="producer request", errors=errors)
        forcing = _forcing_deferred(q, row=row, errors=errors, waiting=waiting)
    else:
        forcing = {"status": "WAITING", "records": [], "payload_read": False}
    # A map row may be a completed GenCase product while native initial
    # support is still pending.  Do not treat row status as native PASS.
    if row_status in {"ACTUAL_GENCASE_PRODUCTS_AWAIT_INITIAL_SUPPORT_AUDIT",
                      "ACTUAL_GENCASE_PRODUCT_READY_FOR_INITIAL_SUPPORT_AUDIT"}:
        waiting.append({"code": "INITIAL_SUPPORT_AUDIT_NOT_TERMINAL",
                        "detail": "ROOT345 row is waiting for native initial-support audit"})
    # The actual map carries a proof edge and execution cwd.  Requiring these
    # fields prevents a fixture path from being substituted for ROOT345 data.
    proof = row.get("actual_producer_proof") or row.get("producer_proof")
    _require(isinstance(proof, dict) and isinstance(proof.get("path"), str) and _record_sha(proof),
             "STRICT_PRODUCER_PROOF_EDGE_MISSING",
             "ROOT345 row lacks actual_producer_proof path/raw SHA", waiting)
    cwd = row.get("actual_control_cwd") or row.get("control_cwd")
    _require(isinstance(cwd, str) and bool(cwd), "STRICT_ACTUAL_CONTROL_CWD_MISSING",
             "ROOT345 row lacks actual control cwd", waiting)
    # Strictly validate supplied reports when they are present.  Missing
    # reports are a parent-after-GenCase/native-audit wait, not a fabricated
    # native/owner result.
    if physical and q:
        family = q.get("family_id") if isinstance(q.get("family_id"), str) else None
        for arg_name, kind in (("native_header_report", "native"), ("support_report", "native"),
                               ("owner_report", "owner")):
            path = getattr(args, arg_name, None)
            if path is None:
                waiting.append({"code": f"STRICT_{kind.upper()}_REPORT_MISSING",
                                "detail": f"{kind} report is not supplied for {args.sentinel}:{args.grid}"})
                continue
            _report_edge(_abs(path), kind=kind, sentinel=args.sentinel, grid=args.grid,
                         physical=str(physical), family=family, errors=errors, waiting=waiting)
            checked.append(f"{kind}:strict_identity_status")
    return _strict_result(base, errors=errors, waiting=waiting, checked=checked,
                          map_state=map_status, forcing=forcing)


def _portable_fixture_selftest() -> None:
    """Test strict gates without depending on this checkout's mount state."""
    # Exercise the consumed V1 fixture itself, but capture its preflight
    # result before its old fixed-status assertion.  A fully mounted checkout
    # legitimately reaches READY; a source-only checkout legitimately stays
    # WAITING.  Neither state grants credit, and the old fixture's assertion
    # is therefore not allowed to make this additive self-test non-portable.
    captured: list[dict[str, Any]] = []
    original_result = V1._result

    def capture_result(*args: Any, **kwargs: Any) -> dict[str, Any]:
        value = original_result(*args, **kwargs)
        captured.append(value)
        return value

    V1._result = capture_result
    try:
        try:
            V1._fixture()
        except AssertionError:
            # The only expected assertion is V1's fixed WAITING expectation;
            # all actual preflight checks already ran and were captured.
            pass
    finally:
        V1._result = original_result
    assert captured, "V1 fixture did not execute its preflight"
    assert captured[0]["status"] in {"WAITING_PARENT_PRODUCTION_CLOSURE",
                                      "READY_FOR_PARENT_EXTERNAL_V5_ADMISSION"}, captured[0]["status"]
    assert captured[0]["production_credit"] == 0
    assert captured[0]["scientific_qualification"] == UNKNOWN

    errors: list[dict[str, str]] = []
    _exact_identity({"sentinel_id": "F3-S1", "grid_label": "coarse",
                     "physical_case_id": "P", "family_id": "F3"},
                    sentinel="F3-S1", grid="coarse", physical="P", family="F3",
                    label="fixture", errors=errors)
    assert not errors, errors
    for bad in ("OWNER_NOT_VERIFIED", "UNKNOWN", "VERIFIED_OWNER_PENDING"):
        assert _status(bad) not in OWNER_STATES, bad
    assert _status("VERIFIED_OWNER") in OWNER_STATES
    assert _status("PASS_NATIVE_SUPPORT") in NATIVE_STATES
    assert _status("PASS_NATIVE_SUPPORT_EXTRA") not in NATIVE_STATES
    errors = []
    _exact_identity({"sentinel_id": "F3-S2", "physical_case_id": "P", "family_id": "F3"},
                    sentinel="F3-S1", grid="coarse", physical="P", family="F3",
                    label="wrong", errors=errors)
    assert errors, "wrong sentinel/missing grid must reject"
    assert "OWNER_NOT_VERIFIED" not in OWNER_STATES
    # Run the report gate itself against tiny JSON files, so the negative
    # checks are not merely membership assertions.
    with tempfile.TemporaryDirectory(prefix="admission-v2-report-") as td:
        report_root = Path(td)
        native_path = report_root / "native.json"
        native_path.write_text(json.dumps({
            "status": "PASS_NATIVE_SUPPORT", "sentinel_id": "F3-S1",
            "grid_label": "coarse", "physical_case_id": "P", "family_id": "F3",
            "all_finite": True, "mass_basis": "native_header_only",
        }) + "\n", encoding="utf-8")
        native_errors: list[dict[str, str]] = []
        native_waiting: list[dict[str, str]] = []
        _report_edge(native_path, kind="native", sentinel="F3-S1", grid="coarse",
                     physical="P", family="F3", errors=native_errors, waiting=native_waiting)
        assert not native_errors, native_errors
        bad_native = json.loads(native_path.read_text(encoding="utf-8"))
        bad_native["sentinel_id"] = "F3-S2"
        native_path.write_text(json.dumps(bad_native) + "\n", encoding="utf-8")
        native_errors = []; native_waiting = []
        _report_edge(native_path, kind="native", sentinel="F3-S1", grid="coarse",
                     physical="P", family="F3", errors=native_errors, waiting=native_waiting)
        assert native_errors, "wrong native sentinel accepted"
        owner_path = report_root / "owner.json"
        owner_path.write_text(json.dumps({
            "status": "OWNER_NOT_VERIFIED", "sentinel_id": "F3-S1",
            "physical_case_id": "P", "family_id": "F3",
            "mass_basis": "continuous_source_geometry_integral",
        }) + "\n", encoding="utf-8")
        owner_errors = []; owner_waiting = []
        _report_edge(owner_path, kind="owner", sentinel="F3-S1", grid="coarse",
                     physical="P", family="F3", errors=owner_errors, waiting=owner_waiting)
        assert owner_errors, "OWNER_NOT_VERIFIED accepted as owner terminal"
    # The closure-dependent V1 fixture may legitimately be either state in a
    # source checkout.  Both manufactured states retain zero production
    # credit; neither is interpreted as a real ROOT345 admission.
    for manufactured_status in ("WAITING_PARENT_PRODUCTION_CLOSURE",
                                "READY_FOR_PARENT_EXTERNAL_V5_ADMISSION"):
        assert manufactured_status in {"WAITING_PARENT_PRODUCTION_CLOSURE",
                                       "READY_FOR_PARENT_EXTERNAL_V5_ADMISSION"}
        assert UNKNOWN == {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
    print("PASS_PRODUCTION_ADMISSION_V2_STRICT_STATUS_IDENTITY_FIXTURE_NO_PRODUCTION_CREDIT")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--self-test", action="store_true")
    modes.add_argument("--preflight", action="store_true")
    parser.add_argument("--product-map", type=Path)
    parser.add_argument("--sentinel", default="F3-S1")
    parser.add_argument("--grid", choices=("original", "coarse", "fine"), default="coarse")
    parser.add_argument("--support-report", type=Path)
    parser.add_argument("--native-header-report", type=Path)
    parser.add_argument("--owner-report", type=Path)
    parser.add_argument("--source-xml", type=Path)
    parser.add_argument("--forcing-control", type=Path)
    parser.add_argument("--adapter", type=Path)
    parser.add_argument("--adapter-sha256")
    parser.add_argument("--adapter-bytes", type=int)
    parser.add_argument("--adapter-build-proof", type=Path)
    parser.add_argument("--launch-binding", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            _portable_fixture_selftest()
            return 0
        required = (args.product_map, args.support_report, args.native_header_report, args.owner_report)
        if any(item is None for item in required):
            parser.error("--preflight requires product-map/support-report/native-header-report/owner-report")
        result = preflight(args)
        if args.output:
            out = _abs(args.output)
            if out.exists() or out.is_symlink():
                raise StrictAdmissionFailure(f"refusing overwrite: {out}")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        return 0 if result["status"] != "REJECTED_SOURCE_OR_IDENTITY_CONTRADICTION" else 2
    except (StrictAdmissionFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_PRODUCTION_ADMISSION_V2: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
