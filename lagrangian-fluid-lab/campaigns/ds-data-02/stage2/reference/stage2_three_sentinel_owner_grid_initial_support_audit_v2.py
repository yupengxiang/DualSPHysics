#!/usr/bin/env python3
"""Additive initial-support audit bound to the actual ROOT709 header report.

The consumed V1 worker is deliberately left unchanged.  This wrapper accepts
the V3/V2 native-header report produced by ROOT709, whose decoder exposed no
MassFluid, MassBound, Dp, role counts, positions, or IDs.  It materializes a
V1-compatible manifest only inside the guarded attempt, installs a strict
sidecar adapter for the V2 report rows, and then delegates the real Fluid/Bound
VTK and BI4 reads to V1.  Missing native fields remain UNKNOWN; XML mass is
never used as a native mass substitute.

The builder reads only bounded JSON and source metadata.  Product XML/VTK/BI4
bytes are deferred to the parent reservation and are never opened by
``build``.  The worker is a diagnostic with zero scientific credit.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
V1_PATH = HERE / "stage2_three_sentinel_owner_grid_initial_support_audit_v1.py"
JSON_CAP = 10 * 1024 * 1024
HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
MANIFEST_SCHEMA = "ds02.stage2.three-sentinel-owner-grid-initial-support-manifest.v2"
V1_MANIFEST_SCHEMA = "ds02.stage2.three-sentinel-owner-grid-initial-support-manifest.v1"
REPORT_SCHEMA = "ds02.stage2.native-header-probe.v3"
REPORT_ROW_SCHEMA = "ds02.stage2.native-header-probe.v2"
SIDECAR_SCHEMA = "ds02.stage2.native-header-probe.v3-sidecar.v1"
PROOF_STATUS = "VERIFIED_ACTUAL_NINE_GENCASE_NATIVE_HEADER_DIAGNOSTIC_NO_SCIENTIFIC_Q"
REPORT_STATUS = "COMPLETE_NATIVE_HEADER_PROBE_DIAGNOSTIC"
UNKNOWN_HEADER_STATUS = "UNKNOWN_NATIVE_HEADER_FIELDS_NOT_EXPOSED_BY_DECODER"
PASS_HEADER_STATUS = "PASS_NATIVE_HEADER_FIELDS"
TARGETS = ("F2-S2", "F3-S1", "F5-S1")
GRIDS = ("original", "coarse", "fine")
ROW_KEYS = tuple(f"{sid}:{grid}" for sid in TARGETS for grid in GRIDS)
NO_CREDIT = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "scientific_credit": 0}
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")


class SupportV2Failure(RuntimeError):
    pass


def _load_v1() -> Any:
    spec = importlib.util.spec_from_file_location("owner_grid_initial_support_v1_for_v2", V1_PATH)
    if spec is None or spec.loader is None:
        raise SupportV2Failure(f"cannot load frozen V1 worker: {V1_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V1 = _load_v1()


def _abs(value: Path | str) -> Path:
    return Path(value).expanduser().absolute()


def _stat(path: Path) -> dict[str, int]:
    st = path.stat()
    return {"device": int(st.st_dev), "inode": int(st.st_ino), "bytes": int(st.st_size),
            "mtime_ns": int(st.st_mtime_ns), "ctime_ns": int(st.st_ctime_ns)}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _regular(path: Path, label: str) -> Path:
    path = _abs(path)
    if path.is_symlink() or not path.is_file():
        raise SupportV2Failure(f"{label} is not a regular non-symlink file: {path}")
    return path


def _read_json(path: Path | str, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _regular(_abs(path), label)
    before = _stat(path)
    if before["bytes"] > JSON_CAP:
        raise SupportV2Failure(f"{label} exceeds the 10 MiB metadata cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after or len(raw) != before["bytes"]:
        raise SupportV2Failure(f"{label} changed during bounded read: {path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SupportV2Failure(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise SupportV2Failure(f"{label} is not a JSON object: {path}")
    return value, {"path": str(path), "sha256": _sha(raw), "bytes": len(raw),
                   "stat": after, "payload_read_by_builder": True,
                   "scope": "bounded_small_metadata"}


def _write_json(path: Path, value: dict[str, Any], label: str) -> dict[str, Any]:
    path = _abs(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    if len(raw) > JSON_CAP:
        raise SupportV2Failure(f"{label} exceeds the 10 MiB metadata cap")
    if path.exists() or path.is_symlink():
        raise SupportV2Failure(f"refusing to overwrite {label}: {path}")
    path.write_bytes(raw)
    return {"path": str(path), "sha256": _sha(raw), "bytes": len(raw),
            "stat": _stat(path), "payload_read_by_builder": False,
            "scope": "builder_output_metadata"}


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and bool(HEX64.fullmatch(value))


def _record(path: Path | str, label: str, *, payload: bool = False) -> dict[str, Any]:
    path = _regular(_abs(path), label)
    before = _stat(path)
    if before["bytes"] > JSON_CAP and not payload:
        raise SupportV2Failure(f"{label} exceeds the 10 MiB metadata cap: {path}")
    # Source XML/Def, receipts, and reports are bounded metadata.  Product
    # records are deliberately represented from the supplied manifest and are
    # never passed here.
    raw = path.read_bytes()
    after = _stat(path)
    if before != after or len(raw) != before["bytes"]:
        raise SupportV2Failure(f"{label} changed during bounded read: {path}")
    return {"path": str(path), "sha256": _sha(raw), "bytes": len(raw),
            "stat": after, "payload_read_by_builder": True,
            "scope": "bounded_small_metadata"}


def _record_from_declared(value: Any, label: str, *, read: bool = True) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        raise SupportV2Failure(f"{label} lacks a path record")
    path = _abs(value["path"])
    if read:
        result = _record(path, label)
        declared = value.get("sha256")
        if _valid_sha(declared) and declared.lower() != result["sha256"].lower():
            raise SupportV2Failure(f"{label} declared SHA differs from current bytes")
        return result
    result = dict(value)
    result["path"] = str(path)
    result["payload_read_by_builder"] = False
    result.setdefault("scope", "parent_after_reservation_product_payload")
    return result


def _field_path(value: Any, label: str) -> Path:
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        raise SupportV2Failure(f"{label} path record is missing")
    return _abs(value["path"])


def _norm_stat(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, int] = {}
    for target, names in {
        "device": ("device", "dev", "st_dev"),
        "inode": ("inode", "ino", "st_ino"),
        "bytes": ("bytes", "size"),
        "mtime_ns": ("mtime_ns",), "ctime_ns": ("ctime_ns",),
    }.items():
        for name in names:
            if name in value:
                result[target] = int(value[name])
                break
    return result


def _expected_declared_stat(record: Any) -> dict[str, int]:
    if not isinstance(record, dict):
        return {}
    return _norm_stat(record.get("stat") or record.get("stat_after") or record.get("stat_post"))


def _source_guard_stats(row: dict[str, Any]) -> tuple[dict[str, int], dict[str, int]]:
    guard = row.get("source_guard")
    if not isinstance(guard, dict):
        raise SupportV2Failure(f"{row.get('row_key')} header report lacks source_guard")
    pre = guard.get("pre") if isinstance(guard.get("pre"), dict) else guard
    post = guard.get("post") if isinstance(guard.get("post"), dict) else guard
    pre_stat = _norm_stat(pre.get("stat_pre") or pre.get("stat") or pre.get("stat_before"))
    post_stat = _norm_stat(post.get("stat_post") or post.get("stat") or post.get("stat_after"))
    if not pre_stat or not post_stat:
        raise SupportV2Failure(f"{row.get('row_key')} header source_guard lacks complete stat")
    return pre_stat, post_stat


def _read_edge(path: Path, label: str, expected_sha: Any = None) -> tuple[dict[str, Any], dict[str, Any]]:
    value, record = _read_json(path, label)
    if _valid_sha(expected_sha) and expected_sha.lower() != record["sha256"].lower():
        raise SupportV2Failure(f"{label} SHA differs from its bound proof")
    return value, record


def _validate_header_lineage(base: dict[str, Any], proof_path: Path, report_path: Path) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    proof, proof_record = _read_json(proof_path, "ROOT709 native-header proof")
    report_expected = proof.get("report")
    if not isinstance(report_expected, str) or _abs(report_expected) != _abs(report_path):
        raise SupportV2Failure("ROOT709 proof report path is not the supplied report")
    report_raw, report_stat = _read_json(report_path, "ROOT709 native-header report")
    if proof.get("report_sha256") != report_stat["sha256"]:
        raise SupportV2Failure("ROOT709 proof report SHA does not bind report bytes")
    if proof.get("status") != PROOF_STATUS:
        raise SupportV2Failure(f"ROOT709 proof status is not the actual no-Q status: {proof.get('status')!r}")
    qualification = proof.get("scientific_qualification")
    if not isinstance(qualification, dict) or any(qualification.get(k) != "UNKNOWN" for k in ("QI", "QN", "QE")):
        raise SupportV2Failure("ROOT709 proof carries a scientific qualification")
    if proof.get("scientific_Q_credit") not in (0, 0.0):
        raise SupportV2Failure("ROOT709 proof carries scientific credit")
    if proof.get("H5_BI4_read_by_root") is not False or proof.get("root_native_payload_content_read") is not False:
        raise SupportV2Failure("ROOT709 proof does not preserve root no-payload scope")
    report = report_raw
    report_record = report_stat
    # The terminal proof's request and execution receipt are part of the
    # producer identity.  A proof that merely repeats self-consistent SHA
    # strings without binding the exact raw request/receipt is not admissible.
    proof_request = proof.get("request")
    proof_receipt = proof.get("receipt")
    if not isinstance(proof_request, str) or not isinstance(proof_receipt, str):
        raise SupportV2Failure("ROOT709 proof lacks request/receipt paths")
    request, request_record = _read_json(_abs(proof_request), "ROOT709 producer request")
    receipt, receipt_record = _read_json(_abs(proof_receipt), "ROOT709 execution receipt")
    if proof.get("request_sha256") != request_record["sha256"] or proof.get("receipt_sha256") != receipt_record["sha256"]:
        raise SupportV2Failure("ROOT709 proof request/receipt SHA does not bind raw files")
    if request.get("schema") != "ds02.request.v1":
        raise SupportV2Failure("ROOT709 producer request schema mismatch")
    if receipt.get("schema") != "ds02.execution-receipt.v1" or receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise SupportV2Failure("ROOT709 execution receipt is not completed with returncode 0")
    if receipt.get("request") != request or receipt.get("request_sha256") != request_record["sha256"]:
        raise SupportV2Failure("ROOT709 receipt does not bind the exact producer request")
    if not isinstance(receipt.get("output_root"), str):
        raise SupportV2Failure("ROOT709 receipt lacks output_root")
    if report.get("schema") != REPORT_SCHEMA or report.get("status") != REPORT_STATUS:
        raise SupportV2Failure("ROOT709 report schema/status mismatch")
    if report.get("xml_fallback") not in (False, None):
        raise SupportV2Failure("ROOT709 report permits XML fallback")
    rows = report.get("cases")
    if not isinstance(rows, list) or len(rows) != len(ROW_KEYS):
        raise SupportV2Failure("ROOT709 report does not contain exactly nine cases")
    by_key: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("schema") != REPORT_ROW_SCHEMA:
            raise SupportV2Failure("ROOT709 report row schema mismatch")
        key = str(row.get("row_key"))
        if key not in ROW_KEYS or key in by_key:
            raise SupportV2Failure(f"ROOT709 report row key is invalid or duplicated: {key}")
        if row.get("status") not in (UNKNOWN_HEADER_STATUS, PASS_HEADER_STATUS):
            raise SupportV2Failure(f"ROOT709 report row status is unsupported: {key}")
        if row.get("source_xml_mass_is_not_native") is not True:
            raise SupportV2Failure(f"{key} does not prohibit XML mass fallback")
        source_path = row.get("source_path")
        if not isinstance(source_path, str) or not _valid_sha(row.get("source_sha256")):
            raise SupportV2Failure(f"{key} lacks native source path/SHA")
        _source_guard_stats(row)
        by_key[key] = row
    if set(by_key) != set(ROW_KEYS):
        raise SupportV2Failure("ROOT709 report row key set is incomplete")
    # Join every report row to the product path and make sure the report's
    # source SHA agrees with a known product SHA when one was already bound.
    base_rows = {f"{row.get('sentinel_id')}:{row.get('grid_label')}": row
                 for row in base.get("cases", []) if isinstance(row, dict)}
    if set(base_rows) != set(ROW_KEYS):
        raise SupportV2Failure("support manifest does not contain exact nine rows")
    for key, row in by_key.items():
        case = base_rows[key]
        native = case.get("native_bi4")
        native_path = _field_path(native, f"{key} native BI4")
        if native_path != _abs(Path(str(row["source_path"]))):
            raise SupportV2Failure(f"{key} ROOT709 source path differs from support manifest native BI4")
        declared_sha = native.get("sha256") if isinstance(native, dict) else None
        if _valid_sha(declared_sha) and declared_sha.lower() != str(row["source_sha256"]).lower():
            raise SupportV2Failure(f"{key} ROOT709 source SHA differs from known product SHA")
    return proof, report, [by_key[key] for key in ROW_KEYS]


def _sidecar(row: dict[str, Any], out: Path) -> tuple[Path, dict[str, Any]]:
    key = str(row["row_key"])
    value = {
        "schema": SIDECAR_SCHEMA,
        "status": row["status"],
        "row_key": key,
        "source_path": row["source_path"],
        "source_sha256": row["source_sha256"],
        "source_guard": row["source_guard"],
        "massfluid": row.get("massfluid", "UNKNOWN_NOT_EXPOSED_BY_DECODER"),
        "massbound": row.get("massbound", "UNKNOWN_NOT_EXPOSED_BY_DECODER"),
        "dp": row.get("dp", "UNKNOWN_NOT_EXPOSED_BY_DECODER"),
        "time_s": row.get("time_s", "UNKNOWN_NOT_EXPOSED_BY_DECODER"),
        "role_counts": row.get("role_counts", {}),
        "finite_fields": row.get("finite_fields", {}),
        "source_xml_mass_is_not_native": True,
        "xml_fallback": False,
        "report_row_schema": row.get("schema"),
        "report_row_status": row.get("status"),
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0},
    }
    path = out / "native-header-sidecars" / (key.replace(":", "__") + ".json")
    record = _write_json(path, value, f"{key} ROOT709 sidecar")
    return path, record


def _products(row: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for role in ("generated_xml", "fluid_vtk", "bound_vtk", "native_bi4"):
        item = row.get(role)
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise SupportV2Failure(f"{row.get('row_key')} lacks deferred product {role}")
        value = dict(item)
        value.update({"row_key": row.get("row_key"), "role": role,
                      "payload_read_by_builder": False,
                      "scope": "parent_after_reservation_product_payload"})
        result.append(value)
    return result


def _static_source_records(base: dict[str, Any], support_path: Path, proof_path: Path,
                           report_path: Path, proof: dict[str, Any],
                           sidecar_records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for path, label in ((support_path, "support manifest"), (proof_path, "ROOT709 proof"),
                        (report_path, "ROOT709 report"), (V1_PATH, "V1 worker"),
                        (HERE / "stage2_four_sentinel_gencase_geometry_support_audit_v1.py", "geometry helper"),
                        (HERE / Path(__file__).name, "V2 worker"),
                        (HERE / "stage2_three_sentinel_owner_grid_initial_support_verify_v5.py", "V2 verifier")):
        record = _record(path, label)
        records[record["path"]] = record
    for field in ("request", "receipt"):
        value = proof.get(field)
        if isinstance(value, str):
            record = _record(Path(value), f"ROOT709 proof {field}")
            records[record["path"]] = record
    pyvenv = PYTHON.parent.parent / "pyvenv.cfg"
    if pyvenv.is_file() and not pyvenv.is_symlink():
        record = _record(pyvenv, "literal venv pyvenv.cfg")
        records[record["path"]] = record
    chain = base.get("chain_manifest")
    if isinstance(chain, dict) and isinstance(chain.get("path"), str):
        record = _record(Path(chain["path"]), "post-GenCase chain manifest")
        records[record["path"]] = record
    product_map = base.get("product_map")
    if isinstance(product_map, dict) and isinstance(product_map.get("path"), str):
        record = _record(Path(product_map["path"]), "actual product map")
        records[record["path"]] = record
    for row in base.get("cases", []):
        if not isinstance(row, dict):
            continue
        for role in ("source_xml", "source_def", "candidate_def", "gencase_receipt", "producer_request"):
            ref = row.get(role)
            if isinstance(ref, dict) and isinstance(ref.get("path"), str):
                record = _record(Path(ref["path"]), f"{row.get('row_key')} {role}")
                records[record["path"]] = record
    for record in sidecar_records:
        records[record["path"]] = record
    return records


def build(support_manifest: Path, header_proof: Path, header_report: Path, output_dir: Path) -> dict[str, Any]:
    base, base_record = _read_json(support_manifest, "source initial-support manifest")
    if base.get("schema") != V1_MANIFEST_SCHEMA:
        raise SupportV2Failure(f"source initial-support manifest schema mismatch: {base.get('schema')!r}")
    proof, report, report_rows = _validate_header_lineage(base, _abs(header_proof), _abs(header_report))
    output_dir = _abs(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise SupportV2Failure(f"refusing nonempty output directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    sidecars: dict[str, dict[str, Any]] = {}
    sidecar_records: list[dict[str, Any]] = []
    for row in report_rows:
        _, record = _sidecar(row, output_dir)
        sidecars[row["row_key"]] = record
        sidecar_records.append(record)
    cases: list[dict[str, Any]] = []
    for row in base["cases"]:
        key = f"{row['sentinel_id']}:{row['grid_label']}"
        copy_row = copy.deepcopy(row)
        copy_row["native_header_probe"] = sidecars[key]
        cases.append(copy_row)
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "status": "READY_FOR_PARENT_GUARDED_OWNER_GRID_INITIAL_SUPPORT_V2",
        "cases": cases,
        "source_manifest": base_record,
        "header_binding": {
            "proof": _record(header_proof, "ROOT709 proof"),
            "report": _record(header_report, "ROOT709 report"),
            "proof_status": proof["status"],
            "report_status": report["status"],
            "report_schema": report["schema"],
            "actual_header_count": len(report_rows),
            "native_mass_source": "ROOT709_DECODER_PRODUCED_FIELDS_ONLY",
            "xml_mass_is_not_native": True,
            "xml_fallback": False,
        },
        "scientific_scope": {"neighbor_grid_truth": False, "interpolation": False,
                             "mass_rescale": False, "xml_mass_fallback": False,
                             "native_mass_unknown_if_decoder_omits_fields": True, **NO_CREDIT},
        "payload_read_by_builder": False, "solver_launch": False, "gencase_launch": False,
    }
    manifest_path = output_dir / "initial-support-manifest-v2-root709-bound.json"
    manifest_record = _write_json(manifest_path, manifest, "V2 initial-support manifest")
    static = _static_source_records(base, _abs(support_manifest), _abs(header_proof), _abs(header_report), proof, sidecar_records)
    static[manifest_record["path"]] = manifest_record
    deferred: list[dict[str, Any]] = []
    for row in cases:
        deferred.extend(_products(row))
    command = [str(PYTHON), str(HERE / Path(__file__).name), "--run", "--manifest",
               str(manifest_path), "--attempt-root", "{attempt_root}", "--output",
               "{attempt_root}/report/initial-support-v2.json"]
    request = {
        "schema": "ds02.request.v1",
        "variant_schema": "ds02.stage2.three-sentinel-owner-grid-initial-support-audit.v2",
        "status": "READY_FOR_PARENT_GUARDED_OWNER_GRID_INITIAL_SUPPORT_V2",
        "request_variant": "owner_grid_initial_support_audit_v2_root709_bound",
        "family_id": "infra", "physical_case_id": "THREE_SENTINEL_OWNER_GRID_INITIAL_SUPPORT_V2",
        "case_id": "THREE_SENTINEL_OWNER_GRID_INITIAL_SUPPORT_AUDIT_V2",
        "attempt_id": "PARENT_AFTER_RESERVATION_REQUIRED", "kind": "cpu", "cpu_task_kind": "audit",
        "cpu_threads": 1, "execution_allowed": False, "launch_disabled": True,
        "solver_launch": False, "gencase_launch": False, "source_only": True,
        "native_payload_read": False, "command": command,
        "command_scope": "parent_after_reservation_template_only",
        "manifest": manifest_record,
        "input_files": sorted(static), "input_records": static,
        "input_sha256": {path: record["sha256"] for path, record in static.items()
                         if _valid_sha(record.get("sha256"))},
        "deferred_input_records": deferred,
        "source_closure_missing": [],
        "resource_scope": {"cpu_seconds": 900, "memory_bytes": 4 * 1024 * 1024 * 1024,
                           "scratch_bytes": 512 * 1024 * 1024, "static_metadata_cap_bytes": JSON_CAP,
                           "payload_reads": "parent_after_reservation_only"},
        "header_binding": manifest["header_binding"],
        "scientific_qualification": dict(NO_CREDIT), "scientific_credit": 0,
    }
    request_path = output_dir / "initial-support-request-v2-root709-bound.json"
    request_record = _write_json(request_path, request, "V2 initial-support request")
    static[request_record["path"]] = request_record
    package = {
        "schema": "ds02.stage2.three-sentinel-owner-grid-initial-support-package.v2",
        "status": request["status"], "manifest": manifest_record, "request": request_record,
        "header_binding": manifest["header_binding"], "input_records": static,
        "deferred_input_records": deferred, "payload_read_by_builder": False,
        "solver_launch": False, "gencase_launch": False,
        "scientific_qualification": dict(NO_CREDIT), "scientific_credit": 0,
    }
    package_path = output_dir / "initial-support-package-v2-root709-bound.json"
    package_record = _write_json(package_path, package, "V2 initial-support package")
    return {"status": request["status"], "manifest": str(manifest_path),
            "request": str(request_path), "package": str(package_path),
            "manifest_record": manifest_record, "request_record": request_record,
            "package_record": package_record, "case_count": len(cases),
            "deferred_count": len(deferred), "scientific_credit": 0,
            "payload_read_by_builder": False}


def _stat_matches(actual: dict[str, int], expected: dict[str, int]) -> bool:
    return all(actual.get(k) == v for k, v in expected.items())


def _native_probe_v2(path: Path | None, record: dict[str, Any] | None,
                     native_guard: dict[str, Any], label: str) -> dict[str, Any]:
    """V1 callback accepting ROOT709 unknown-field sidecars without weakening joins."""
    if path is None or record is None:
        raise SupportV2Failure(f"{label} sidecar is required")
    value, guard = V1._small_json(path, record, label)
    if value.get("schema") != SIDECAR_SCHEMA:
        raise SupportV2Failure(f"{label} schema mismatch")
    source_path = value.get("source_path")
    if not isinstance(source_path, str) or _abs(Path(source_path)) != _abs(Path(native_guard["path"])):
        raise SupportV2Failure(f"{label} source path does not match guarded BI4")
    source_sha = value.get("source_sha256")
    if not isinstance(source_sha, str) or source_sha.lower() not in {
        str(native_guard.get("sha256_pre", "")).lower(), str(native_guard.get("sha256_post", "")).lower()}:
        raise SupportV2Failure(f"{label} source SHA does not match guarded BI4")
    expected_pre, expected_post = _source_guard_stats(value)
    if not _stat_matches(native_guard.get("stat_pre", {}), expected_pre) or not _stat_matches(native_guard.get("stat_post", {}), expected_post):
        raise SupportV2Failure(f"{label} source stat does not match guarded BI4")
    if value.get("source_xml_mass_is_not_native") is not True or value.get("xml_fallback") is not False:
        raise SupportV2Failure(f"{label} allows XML mass fallback")
    status = value.get("status")
    if status not in (UNKNOWN_HEADER_STATUS, PASS_HEADER_STATUS):
        raise SupportV2Failure(f"{label} has unsupported header status {status!r}")
    role_counts = value.get("role_counts")
    finite = value.get("finite_fields")
    if not isinstance(role_counts, dict) or not isinstance(finite, dict):
        raise SupportV2Failure(f"{label} lacks role/finite fields")
    values: dict[str, Any] = {}
    for key in ("massfluid", "massbound", "dp", "time_s"):
        item = value.get(key, "UNKNOWN_NOT_EXPOSED_BY_DECODER")
        if isinstance(item, (int, float)) and not isinstance(item, bool):
            if not math.isfinite(float(item)):
                raise SupportV2Failure(f"{label} {key} is non-finite")
        values[key] = item
    if status == PASS_HEADER_STATUS:
        if finite.get("position") is not True or finite.get("ids_unique") is not True:
            raise SupportV2Failure(f"{label} PASS row lacks finite position/identity proof")
    return {"status": status, "source_path": source_path, "source_sha256": source_sha,
            "probe": guard, "massfluid": values["massfluid"], "massbound": values["massbound"],
            "dp": values["dp"], "time_s": values["time_s"], "role_counts": role_counts,
            "finite_fields": finite, "xml_mass_is_not_native": True,
            "native_header_values_only": True,
            "native_header_unknown_reason": "ROOT709_DECODER_DID_NOT_EXPOSE_FIELDS" if status == UNKNOWN_HEADER_STATUS else None}


def _materialize_v1_manifest(manifest: dict[str, Any], attempt_root: Path) -> Path:
    value = copy.deepcopy(manifest)
    value["schema"] = V1_MANIFEST_SCHEMA
    value["status"] = "READY_FOR_PARENT_GUARDED_OWNER_GRID_INITIAL_SUPPORT"
    value["scientific_scope"] = {"neighbor_grid_truth": False, "interpolation": False,
                                  "mass_rescale": False, "xml_mass_fallback": False,
                                  "scientific_credit": 0, "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
    path = _abs(attempt_root) / "worker-materialized" / "initial-support-manifest-v1-compatible.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise SupportV2Failure(f"refusing to overwrite materialized V1 manifest: {path}")
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return path


def _validate_runtime_manifest(manifest: dict[str, Any]) -> None:
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != "READY_FOR_PARENT_GUARDED_OWNER_GRID_INITIAL_SUPPORT_V2":
        raise SupportV2Failure("V2 initial-support manifest schema/status is not guarded-ready")
    if manifest.get("gencase_launch") is not False or manifest.get("solver_launch") is not False:
        raise SupportV2Failure("V2 manifest permits GenCase/solver launch")
    scope = manifest.get("scientific_scope")
    if not isinstance(scope, dict) or scope.get("xml_mass_fallback") is not False or scope.get("scientific_credit") != 0:
        raise SupportV2Failure("V2 manifest scientific scope is not diagnostic-only")
    binding = manifest.get("header_binding")
    if not isinstance(binding, dict) or binding.get("xml_mass_is_not_native") is not True or binding.get("xml_fallback") is not False:
        raise SupportV2Failure("V2 manifest lacks strict ROOT709 no-fallback binding")
    if binding.get("actual_header_count") != 9:
        raise SupportV2Failure("V2 manifest is not bound to exactly nine ROOT709 rows")
    rows = manifest.get("cases")
    if not isinstance(rows, list) or len(rows) != 9:
        raise SupportV2Failure("V2 manifest must contain exactly nine cases")
    keys = {f"{row.get('sentinel_id')}:{row.get('grid_label')}" for row in rows if isinstance(row, dict)}
    if keys != set(ROW_KEYS):
        raise SupportV2Failure("V2 manifest row key set is incomplete")


def run(manifest_path: Path, attempt_root: Path, output_path: Path) -> dict[str, Any]:
    manifest, manifest_guard = _read_json(manifest_path, "V2 initial-support manifest")
    _validate_runtime_manifest(manifest)
    _validate_header_lineage(manifest, _field_path(manifest["header_binding"]["proof"], "ROOT709 proof"),
                             _field_path(manifest["header_binding"]["report"], "ROOT709 report"))
    materialized = _materialize_v1_manifest(manifest, _abs(attempt_root))
    compat_output = _abs(attempt_root) / "worker-materialized" / "initial-support-v1-compat-report.json"
    old_probe = V1._native_probe
    V1._native_probe = _native_probe_v2
    try:
        inner = V1.run(materialized, _abs(attempt_root), compat_output)
    finally:
        V1._native_probe = old_probe
    cases = inner.get("cases", [])
    counts = {
        "PASS_OR_DIAGNOSTIC": sum(row.get("status") != "FAILED_INITIAL_SUPPORT_DIAGNOSTIC" for row in cases),
        "FAILED": sum(row.get("status") == "FAILED_INITIAL_SUPPORT_DIAGNOSTIC" for row in cases),
        "NATIVE_HEADER_UNKNOWN": sum(row.get("native_header", {}).get("status") == UNKNOWN_HEADER_STATUS for row in cases),
        "NATIVE_HEADER_PASS": sum(row.get("native_header", {}).get("status") == PASS_HEADER_STATUS for row in cases),
    }
    value = {
        "schema": "ds02.stage2.three-sentinel-owner-grid-initial-support-audit.v2",
        "status": "COMPLETE_PARTIAL_OWNER_GRID_INITIAL_SUPPORT_V2_HEADER_709_BOUND",
        "manifest": manifest_guard,
        "header_binding": manifest["header_binding"],
        "compat_v1_report": {"path": str(compat_output), "sha256": _sha(compat_output.read_bytes()),
                             "stat": _stat(compat_output), "payload_read_by_worker": True},
        "cases": cases, "case_counts": counts,
        "native_mass_source": "ACTUAL_ROOT709_DECODER_FIELDS_ONLY",
        "native_mass_unknown_if_not_exposed": True,
        "xml_mass_is_not_native": True, "xml_fallback": False,
        "scientific_scope": {"continuous_owner": "UNKNOWN", "native_mass": "UNKNOWN",
                             "neighbor_grid_truth": False, "mass_rescale": False,
                             "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "scientific_credit": 0},
        "read_scope": {"generated_xml": True, "fluid_vtk": True, "bound_vtk": True,
                        "native_bi4_bytes": True, "native_header_report": True,
                        "solver_launch": False, "gencase_launch": False, "production_hdf5_read": False},
    }
    output_path = _abs(output_path)
    if output_path.exists() or output_path.is_symlink():
        raise SupportV2Failure(f"refusing to overwrite V2 support report: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return value


def _self_test() -> None:
    # Use the frozen V1 tiny producer and a real ROOT709-shaped unknown report.
    with tempfile.TemporaryDirectory(prefix="owner-grid-support-v2-") as td:
        root = Path(td)
        base_path = V1._fixture_manifest(root / "base")
        base, _ = _read_json(base_path, "fixture base manifest")
        rows = []
        for case in base["cases"]:
            key = f"{case['sentinel_id']}:{case['grid_label']}"
            native = case["native_bi4"]
            npath = Path(native["path"])
            stat = _stat(npath)
            rows.append({"schema": REPORT_ROW_SCHEMA, "status": UNKNOWN_HEADER_STATUS,
                         "row_key": key, "source_path": str(npath), "source_sha256": _sha(npath.read_bytes()),
                         "source_guard": {"pre": {"stat_pre": stat}, "post": {"stat_post": stat}},
                         "massfluid": "UNKNOWN_NOT_EXPOSED_BY_DECODER", "massbound": "UNKNOWN_NOT_EXPOSED_BY_DECODER",
                         "dp": "UNKNOWN_NOT_EXPOSED_BY_DECODER", "time_s": "UNKNOWN_NOT_EXPOSED_BY_DECODER",
                         "role_counts": {"fluid": "UNKNOWN_NOT_EXPOSED_BY_DECODER"},
                         "finite_fields": {"position": "UNKNOWN_NOT_DECODED_BY_HEADER_PROBE", "ids_unique": "UNKNOWN_NOT_DECODED_BY_HEADER_PROBE"},
                         "source_xml_mass_is_not_native": True})
        report = {"schema": REPORT_SCHEMA, "status": REPORT_STATUS, "cases": rows, "xml_fallback": False}
        report_path = root / "header-report.json"; report_path.write_text(json.dumps(report, sort_keys=True), encoding="utf-8")
        request = {"schema": "ds02.request.v1", "family_id": "infra", "case_id": "ROOT709_FIXTURE", "attempt_id": "fixture", "sentinel_id": "infra", "grid_label": "fixture"}
        request_path = root / "header-request.json"; request_path.write_text(json.dumps(request, sort_keys=True), encoding="utf-8")
        receipt = {"schema": "ds02.execution-receipt.v1", "status": "completed", "returncode": 0,
                   "request": request, "request_sha256": _sha(request_path.read_bytes()), "output_root": str(root)}
        receipt_path = root / "header-receipt.json"; receipt_path.write_text(json.dumps(receipt, sort_keys=True), encoding="utf-8")
        proof = {"schema": "ds02.stage2.root-actual-verification.v1", "status": PROOF_STATUS,
                 "report": str(report_path), "report_sha256": _sha(report_path.read_bytes()),
                 "request": str(request_path), "request_sha256": _sha(request_path.read_bytes()),
                 "receipt": str(receipt_path), "receipt_sha256": _sha(receipt_path.read_bytes()),
                 "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
                 "scientific_Q_credit": 0, "H5_BI4_read_by_root": False, "root_native_payload_content_read": False}
        proof_path = root / "header-proof.json"; proof_path.write_text(json.dumps(proof, sort_keys=True), encoding="utf-8")
        out = build(base_path, proof_path, report_path, root / "prepared")
        manifest, _ = _read_json(Path(out["manifest"]), "fixture V2 manifest")
        assert manifest["header_binding"]["actual_header_count"] == 9
        assert all(case["native_header_probe"]["path"].endswith(".json") for case in manifest["cases"])
        result = run(Path(out["manifest"]), root / "attempt", root / "attempt" / "report.json")
        assert result["case_counts"]["FAILED"] == 0
        assert result["case_counts"]["NATIVE_HEADER_UNKNOWN"] == 9
        assert result["scientific_scope"]["scientific_credit"] == 0
        # A report-side source SHA mutation is rejected before any product read.
        bad = json.loads(report_path.read_text())
        bad["cases"][0]["source_sha256"] = "0" * 64
        bad_path = root / "bad-report.json"; bad_path.write_text(json.dumps(bad), encoding="utf-8")
        try:
            build(base_path, proof_path, bad_path, root / "bad-prepared")
        except SupportV2Failure:
            pass
        else:
            raise AssertionError("report source SHA mutation was accepted")
    print("PASS_THREE_SENTINEL_OWNER_GRID_INITIAL_SUPPORT_V2_ROOT709_FIXTURE")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--support-manifest", type=Path)
    parser.add_argument("--header-proof", type=Path)
    parser.add_argument("--header-report", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--attempt-root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            _self_test(); return 0
        if args.build:
            if None in (args.support_manifest, args.header_proof, args.header_report, args.output_dir):
                parser.error("--build requires --support-manifest, --header-proof, --header-report, --output-dir")
            result = build(args.support_manifest, args.header_proof, args.header_report, args.output_dir)
            print(json.dumps({"status": result["status"], "manifest": result["manifest"],
                              "request": result["request"], "package": result["package"],
                              "case_count": result["case_count"], "scientific_credit": 0}, sort_keys=True))
            return 0
        if None in (args.manifest, args.attempt_root, args.output):
            parser.error("--run requires --manifest, --attempt-root, --output")
        result = run(args.manifest, args.attempt_root, args.output)
        print(json.dumps({"status": result["status"], "output": str(_abs(args.output)),
                          "case_counts": result["case_counts"], "scientific_credit": 0}, sort_keys=True))
        return 0
    except (SupportV2Failure, V1.AuditFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_THREE_SENTINEL_OWNER_GRID_INITIAL_SUPPORT_V2: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
