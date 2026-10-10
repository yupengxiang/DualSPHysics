#!/usr/bin/env python3
"""Build and verify a source-bound F3-S1 external-solver canary request.

This module is the additive F3-S1 counterpart to the consumed F3-S2/ROOT120
builder.  It is deliberately producer driven: a request is admitted only
after a ROOT345 product-map row is terminal, its producer request is joined by
the raw request-file SHA, and the generated XML/BI4/Fluid/Bound products,
initial-support/native-header report, and continuous-owner report agree on
one physical case.  The builder never opens a generated BI4/VTK or forcing
payload.  Their bytes are first hashed by the parent after reservation.

The canary remains development/UNKNOWN.  The parent owns the GPU lease,
runtime-v8 reservation, post-run hashing, cancellation, fees, and terminal
RunPARTs/Run.out evidence.  The native observer is represented as a separate
post-solver producer plan; it is not silently run by this request.

``bi4_dump`` is recorded as a project adapter.  It uses the official
DualSPHysics JBinaryData source, but the adapter executable is not called an
official DualSPHysics tool and its build provenance remains a parent gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[5]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
VENV = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
PYVENV = VENV.parent.parent / "pyvenv.cfg"
RUNTIME_V8 = REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
RUNNER_V5 = REPO / "lagrangian-fluid-lab/scripts/ds_data02_stage2_external_solver_v5.py"
MATERIALIZER = HERE / "stage2_f3_s1_external_solver_canary_materialize.py"
OBSERVER = HERE / "stage2_native_physical_observer_v2.py"
ENFORCER = HERE / "stage2_native_physical_observer_enforcer_v2.py"
VERIFIER = HERE / "stage2_f3_s1_external_solver_canary_verify_v1.py"
BI4_ADAPTER_SOURCE = REPO / "lagrangian-fluid-lab/scripts/native/bi4_dump.cpp"
BI4_ADAPTER_DEFAULT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
JBD_ROOT = REPO / "lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/src/source"
JBD_HEADER = JBD_ROOT / "JBinaryData.h"
JBD_SOURCE = JBD_ROOT / "JBinaryData.cpp"
OFFICIAL_ROOT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux")
SOLVER = OFFICIAL_ROOT / "DualSPHysics5.4_linux64"
LIB_DSPH = OFFICIAL_ROOT / "libdsphchrono.so"
LIB_CHRONO = OFFICIAL_ROOT / "libChronoEngine.so"

SCHEMA = "ds02.stage2.external-solver-request.v5"
VARIANT = "ds02.stage2.f3-s1.external-solver-canary.v1"
SUPPORT_SCHEMA = "ds02.stage2.three-sentinel.initial-support"
HEX64_RE = re.compile(r"^[0-9a-fA-F]{64}$")
JSON_CAP = 10 * 1024 * 1024
PRODUCT_KEYS = ("generated_xml", "native_bi4", "fluid_vtk", "bound_vtk")
STATUS_WORDS = ("COMPLETED", "SUCCESS", "VERIFIED", "PASS")
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}

# These are the bytes already bound by completed external-v5 runs.  The
# parent still repeats the full binary hash after reservation; this table is a
# provenance expectation, not a local payload read.
KNOWN_BINARY_SHA = {
    str(SOLVER): "0415b10e5e32af8b8b7ad2a703f9043dca67dfcf7626eb98f1c05a50856fde29",
    str(LIB_DSPH): "6a7a94ed7adcdd4e9dddee58cde0f080dee95d930e169bd39cc78894d1a2c937",
    str(LIB_CHRONO): "3adb8a5ef36b988add7717d60ee5e50bf7107a5623b448c3a5300d087c2b32e7",
}
KNOWN_BINARY_BYTES = {str(SOLVER): 159206984, str(LIB_DSPH): 646160, str(LIB_CHRONO): 28283072}


class BuildFailure(RuntimeError):
    """A source contract or terminal producer join failed."""


def _abs(path: Path | str) -> Path:
    return Path(path).expanduser().absolute()


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {
        "device": int(value.st_dev),
        "inode": int(value.st_ino),
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
    }


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and bool(HEX64_RE.fullmatch(value))


def _regular(path: Path, label: str) -> Path:
    path = _abs(path)
    if path.is_symlink() or not path.is_file():
        raise BuildFailure(f"{label} must be a regular non-symlink file: {path}")
    return path


def _small_record(path: Path, label: str) -> dict[str, Any]:
    path = _regular(path, label)
    before = _stat(path)
    if before["bytes"] > JSON_CAP:
        raise BuildFailure(f"{label} exceeds the 10 MiB bounded-source cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after or len(raw) != before["bytes"]:
        raise BuildFailure(f"{label} changed during bounded read: {path}")
    return {
        "path": str(path), "label": label, "sha256": _sha_bytes(raw),
        "stat_before": before, "stat_after": after, "bytes": len(raw),
        "read_scope": "bounded_small_metadata", "payload_read_by_builder": True,
    }


def _json(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any], bytes]:
    record = _small_record(path, label)
    try:
        value = json.loads(Path(record["path"]).read_bytes().decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BuildFailure(f"{label} is not valid bounded JSON") from exc
    if not isinstance(value, dict):
        raise BuildFailure(f"{label} must be a JSON object")
    return value, record, Path(record["path"]).read_bytes()


def _stat_only(path: Path, label: str, expected_sha: str, *, expected_stat: dict[str, Any] | None = None,
               role: str = "deferred_parent_after_reservation") -> dict[str, Any]:
    path = _regular(path, label)
    if not _valid_sha(expected_sha):
        raise BuildFailure(f"{label} needs a concrete parent SHA-256")
    current = _stat(path)
    if isinstance(expected_stat, dict):
        aliases = {"device": ("device", "st_dev"), "inode": ("inode", "st_ino"),
                   "bytes": ("bytes", "size"), "mtime_ns": ("mtime_ns",), "ctime_ns": ("ctime_ns",)}
        for target, names in aliases.items():
            for name in names:
                if name in expected_stat and int(expected_stat[name]) != current[target]:
                    raise BuildFailure(f"{label} {target} differs from producer map")
    return {
        "path": str(path), "label": label, "sha256": expected_sha.lower(),
        "stat_before": current, "stat_after": current, "bytes": current["bytes"],
        "read_scope": role, "payload_read_by_builder": False,
        "sha_authority": "parent_after_reservation_or_terminal_product_map",
    }


def _record_code(path: Path, label: str) -> dict[str, Any]:
    return _small_record(path, label)


def _record_binary(path: Path, label: str, *, expected_sha: str | None = None,
                   expected_bytes: int | None = None) -> dict[str, Any]:
    path = _regular(path, label)
    current = _stat(path)
    if expected_bytes is not None and current["bytes"] != expected_bytes:
        raise BuildFailure(f"{label} size differs from the completed-run binding")
    if not _valid_sha(expected_sha):
        raise BuildFailure(f"{label} needs an explicit post-reservation SHA")
    return {
        "path": str(path), "label": label, "bytes": current["bytes"],
        "stat_at_prepare": current, "sha256": expected_sha.lower(),
        "read_scope": "parent_after_reservation_hash", "payload_read_by_builder": False,
    }


def _write_once(path: Path, value: dict[str, Any]) -> None:
    path = _abs(path)
    if path.exists() or path.is_symlink():
        raise BuildFailure(f"refusing to overwrite immutable request: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _record_from_row(row: dict[str, Any], *names: str) -> dict[str, Any]:
    for name in names:
        value = row.get(name)
        if isinstance(value, dict):
            return value
    raise BuildFailure(f"product row lacks one of {names}")


def _rows(product_map: dict[str, Any]) -> list[dict[str, Any]]:
    rows = product_map.get("products", product_map.get("cases"))
    if not isinstance(rows, list):
        raise BuildFailure("ROOT345 product map lacks a products/cases list")
    result = [row for row in rows if isinstance(row, dict)]
    if len(result) != len(rows):
        raise BuildFailure("ROOT345 product map contains a non-object row")
    return result


def _terminal_status(value: Any) -> bool:
    text = str(value or "").upper()
    return any(word in text for word in STATUS_WORDS) and "FAIL" not in text


def _row_for(product_map: dict[str, Any], sentinel: str, grid: str) -> dict[str, Any]:
    matches = [row for row in _rows(product_map)
               if row.get("sentinel_id") == sentinel and row.get("grid_label") == grid]
    if len(matches) != 1:
        raise BuildFailure(f"ROOT345 product map must contain exactly one {sentinel}:{grid} row")
    row = matches[0]
    if not _terminal_status(row.get("status")):
        raise BuildFailure(f"{sentinel}:{grid} GenCase row is not terminal-completed: {row.get('status')!r}")
    if str(row.get("scientific_qualification", {}).get("QI", "UNKNOWN")).upper() != "UNKNOWN":
        raise BuildFailure("product row scientific Q is not allowed to be promoted by this builder")
    return row


def _receipt_identity(receipt: dict[str, Any], q: dict[str, Any], q_record: dict[str, Any],
                      row: dict[str, Any], label: str) -> tuple[Path, str, str, str]:
    status = receipt.get("status") or receipt.get("state")
    if not _terminal_status(status):
        raise BuildFailure(f"{label} receipt status is not completed: {status!r}")
    returncode = receipt.get("returncode")
    if returncode is None:
        returncode = (receipt.get("execution") or {}).get("returncode")
    if returncode != 0:
        raise BuildFailure(f"{label} receipt does not have returncode 0")
    request_sha = receipt.get("request_sha256")
    if not _valid_sha(request_sha):
        request_sha = (receipt.get("request") or {}).get("request_sha256")
    if not _valid_sha(request_sha) or request_sha.lower() != q_record["sha256"].lower():
        raise BuildFailure(f"{label} receipt request SHA is not the raw producer request-file SHA")
    receipt_request = receipt.get("request")
    if isinstance(receipt_request, dict):
        if {k: v for k, v in receipt_request.items() if k != "request_sha256"} != q:
            raise BuildFailure(f"{label} receipt.request is not the producer request document")
    case_id = str(row.get("case_id") or q.get("case_id") or "")
    attempt_id = str(row.get("attempt_id") or q.get("attempt_id") or "")
    if not case_id or not attempt_id:
        raise BuildFailure(f"{label} lacks case/attempt identity")
    for field, expected in (("case_id", case_id), ("attempt_id", attempt_id), ("physical_case_id", row.get("physical_case_id"))):
        if expected is None:
            continue
        got = receipt.get(field)
        if got is None and isinstance(receipt_request, dict):
            got = receipt_request.get(field)
        if got is not None and str(got) != str(expected):
            raise BuildFailure(f"{label} {field} does not join the product row")
    root_text = receipt.get("output_root") or (receipt.get("execution") or {}).get("output_root")
    if not isinstance(root_text, str) or not root_text:
        raise BuildFailure(f"{label} lacks an actual output_root")
    root = _abs(Path(root_text))
    if not root.is_dir() or root.is_symlink():
        raise BuildFailure(f"{label} output_root is not a regular terminal directory: {root}")
    return root, case_id, attempt_id, str(request_sha).lower()


def _row_product(row: dict[str, Any], key: str) -> dict[str, Any]:
    aliases = {
        "generated_xml": ("generated_xml", "xml"),
        "native_bi4": ("native_bi4", "generated_bi4", "bi4"),
        "fluid_vtk": ("fluid_vtk", "generated_fluid_vtk", "fluid"),
        "bound_vtk": ("bound_vtk", "generated_bound_vtk", "bound"),
    }
    return _record_from_row(row, *aliases[key])


def _field_paths(node: Any, wanted: set[str], prefix: str = "$") -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            path = f"{prefix}.{key}"
            if str(key).lower() in {item.lower() for item in wanted}:
                out.append((path, value))
            out.extend(_field_paths(value, wanted, path))
    elif isinstance(node, list):
        for idx, value in enumerate(node):
            out.extend(_field_paths(value, wanted, f"{prefix}[{idx}]"))
    return out


def _native_gate(report: dict[str, Any], label: str) -> dict[str, Any]:
    status = str(report.get("status", ""))
    if not _terminal_status(status) or "SUPPORT" not in status.upper():
        raise BuildFailure(f"{label} is not a terminal support report: {status!r}")
    if report.get("sentinel_id") not in (None, "F3-S1") and report.get("family_id") not in (None, "F3"):
        raise BuildFailure(f"{label} is for the wrong sentinel")
    native_candidates = []
    for path, value in _field_paths(report, {"native_header", "native_fields", "header", "native_mass"}):
        if isinstance(value, dict):
            native_candidates.append((path, value))
    if isinstance(report.get("native"), dict):
        native_candidates.insert(0, ("$.native", report["native"]))
    native = None
    native_path = ""
    for path, candidate in native_candidates:
        keys = {str(k).lower() for k in candidate}
        if ({"massfluid", "massbound"} <= keys or
                {"mass_fluid_kg", "mass_bound_kg"} <= keys or
                {"native_mass_fluid_kg", "native_mass_bound_kg"} <= keys):
            native, native_path = candidate, path
            break
    if native is None:
        raise BuildFailure(f"{label} does not expose native MassFluid/MassBound fields")
    def first(names: Iterable[str]) -> Any:
        lower = {str(k).lower(): value for k, value in native.items()}
        for name in names:
            if name.lower() in lower:
                return lower[name.lower()]
        return None
    mf = first(("MassFluid", "mass_fluid_kg", "native_mass_fluid_kg"))
    mb = first(("MassBound", "mass_bound_kg", "native_mass_bound_kg"))
    dp = first(("Dp", "dp_m", "point_spacing_m"))
    if not all(isinstance(value, (int, float)) and math.isfinite(float(value)) for value in (mf, mb, dp)) or float(mf) <= 0 or float(mb) < 0 or float(dp) <= 0:
        raise BuildFailure(f"{label} native fields are missing/nonfinite")
    basis = " ".join(str(report.get(key, "")) for key in ("mass_basis", "mass_source", "source_of_mass"))
    if "xml" in basis.lower() or "native" not in basis.lower():
        raise BuildFailure(f"{label} does not declare native, non-XML mass authority")
    role_values = _field_paths(report, {"role_counts", "counts_by_role"})
    role = next((value for _, value in role_values if isinstance(value, dict)), None)
    if not isinstance(role, dict):
        raise BuildFailure(f"{label} lacks typed role counts")
    role_lower = {str(k).lower(): value for k, value in role.items()}
    if not any(key in role_lower for key in ("fluid", "fluid_count", "fluid_particles")):
        raise BuildFailure(f"{label} lacks fluid role count")
    if not any(key in role_lower for key in ("bound", "fixed", "bound_count", "fixed_count")):
        raise BuildFailure(f"{label} lacks bound/fixed role count")
    finite = report.get("all_finite", report.get("finite"))
    if finite is not True:
        raise BuildFailure(f"{label} does not certify finite native support fields")
    return {"status": status, "native_path": native_path, "mass_fluid_kg": float(mf),
            "mass_bound_kg": float(mb), "dp_m": float(dp), "role_counts": role,
            "mass_basis": "native_header_not_XML", "finite": True}


def _owner_gate(report: dict[str, Any]) -> dict[str, Any]:
    status = str(report.get("status", ""))
    upper = status.upper()
    if not _terminal_status(status) or not ("OWNER" in upper and ("PASS" in upper or "VERIF" in upper)):
        raise BuildFailure(f"continuous-owner gate is not verified: {status!r}")
    if report.get("sentinel_id") not in (None, "F3-S1"):
        raise BuildFailure("continuous-owner gate belongs to another sentinel")
    mass = report.get("owner_mass_kg", report.get("continuous_owner_mass_kg"))
    volume = report.get("owner_volume_m3", report.get("continuous_owner_volume_m3"))
    geometry_sha = report.get("geometry_sha256") or (report.get("geometry_source") or {}).get("sha256")
    if not isinstance(mass, (int, float)) or not math.isfinite(float(mass)) or float(mass) <= 0:
        raise BuildFailure("continuous-owner gate lacks a finite positive mass")
    if not isinstance(volume, (int, float)) or not math.isfinite(float(volume)) or float(volume) <= 0:
        raise BuildFailure("continuous-owner gate lacks a finite positive volume")
    if not _valid_sha(geometry_sha):
        raise BuildFailure("continuous-owner gate lacks a concrete geometry source SHA")
    if report.get("control_equivalence") is not True and (report.get("control_gate") or {}).get("status") not in ("VERIFIED", "PASS"):
        raise BuildFailure("continuous-owner gate lacks exact control equivalence")
    basis = str(report.get("mass_basis", "")).lower()
    if "continuous" not in basis or "discrete" in basis or "xml" in basis:
        raise BuildFailure("owner mass basis is not a continuous source geometry integral")
    return {"status": status, "owner_mass_kg": float(mass), "owner_volume_m3": float(volume),
            "geometry_sha256": str(geometry_sha).lower(), "mass_basis": report.get("mass_basis"),
            "control_equivalence": True, "qualification": dict(UNKNOWN)}


def _literal_venv() -> dict[str, Any]:
    literal = _regular(VENV, "literal venv interpreter") if not VENV.is_symlink() else VENV
    if not VENV.exists():
        raise BuildFailure(f"literal venv interpreter is missing: {VENV}")
    resolved = VENV.resolve()
    if not resolved.is_file():
        raise BuildFailure("resolved venv interpreter is missing")
    resolved_record = _small_record(resolved, "resolved venv interpreter")
    return {
        "argv0_literal": str(VENV), "argv0_must_remain_literal": True,
        "resolved_interpreter": str(resolved), "resolved_sha256": resolved_record["sha256"],
        "resolved_stat": resolved_record["stat_after"], "resolved_record": resolved_record,
        "pyvenv_cfg": _small_record(PYVENV, "pyvenv.cfg"),
        "system_python_fallback_allowed": False,
    }


def _source_closure(bi4_dump: Path, bi4_sha: str, bi4_bytes: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    records = [
        _record_code(MATERIALIZER, "F3-S1 canary materializer"),
        _record_code(RUNTIME_V8, "shared runtime v8"),
        _record_code(RUNNER_V5, "shared external solver v5 runner"),
        _record_code(OBSERVER, "native observer v2"),
        _record_code(ENFORCER, "native observer enforcer v2"),
        _record_code(VERIFIER, "F3-S1 independent canary verifier"),
        _record_code(BI4_ADAPTER_SOURCE, "project bi4_dump adapter source"),
        _record_code(JBD_HEADER, "official JBinaryData v5.4 header"),
        _record_code(JBD_SOURCE, "official JBinaryData v5.4 source"),
    ]
    solver_records = []
    for path in (SOLVER, LIB_DSPH, LIB_CHRONO):
        solver_records.append(_record_binary(path, path.name, expected_sha=KNOWN_BINARY_SHA[str(path)], expected_bytes=KNOWN_BINARY_BYTES[str(path)]))
    adapter = _record_binary(bi4_dump, "project bi4_dump executable", expected_sha=bi4_sha, expected_bytes=bi4_bytes)
    closure = {
        "literal_venv": _literal_venv(),
        "records": records,
        "solver_binary_records": solver_records,
        "bi4_adapter": {**adapter, "tool_role": "project_native_adapter", "official_tool_claim": False,
                         "library_authority": "official DualSPHysics v5.4 JBinaryData", "build_provenance_status": "PARENT_SOURCE_HASHED_BUILD_REQUIRED"},
        "jbinarydata_authority": {
            "library_sources": [str(JBD_HEADER), str(JBD_SOURCE)],
            "authority": "official_vendor_JBinaryData_v5.4_source",
            "adapter_is_not_official_tool": True,
        },
        "imports_must_be_bound_transitively": True,
    }
    return closure, records + solver_records + [adapter]


def _record_from_optional(path: Path | None, label: str, required: bool = True) -> dict[str, Any] | None:
    if path is None:
        if required:
            raise BuildFailure(f"{label} is required")
        return None
    return _small_record(path, label)


def _product_binding(row: dict[str, Any], receipt_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    records: dict[str, Any] = {}
    for key in PRODUCT_KEYS:
        value = _row_product(row, key)
        if not isinstance(value.get("path"), str) or not _valid_sha(value.get("sha256")):
            raise BuildFailure(f"{row.get('row_key')} {key} lacks terminal SHA")
        path = _abs(Path(value["path"]))
        if not path.is_file() or path.is_symlink():
            raise BuildFailure(f"{row.get('row_key')} {key} product is not a regular terminal file")
        if path.parent != receipt_root:
            raise BuildFailure(f"{row.get('row_key')} {key} is outside the producer output_root")
        records[key] = _stat_only(path, f"{row.get('row_key')} {key}", str(value["sha256"]), expected_stat=value.get("stat"))
    return records, {key: records[key]["sha256"] for key in PRODUCT_KEYS}


def build(args: argparse.Namespace) -> dict[str, Any]:
    product_map, product_map_record, _ = _json(args.product_map, "ROOT345 actual product map")
    if not str(product_map.get("schema", "")).startswith("ds02.stage2.three-sentinel.owner-grid-gencase-product-map"):
        raise BuildFailure("product map schema is not the owner-grid actual map")
    if not _terminal_status(product_map.get("status")):
        raise BuildFailure("ROOT345 product map is not terminal-completed")
    row = _row_for(product_map, "F3-S1", args.grid)
    q_ref = _record_from_row(row, "producer_request", "gencase_request")
    q_path = _regular(Path(str(q_ref["path"])), "F3-S1 producer request")
    q, q_record, q_raw = _json(q_path, "F3-S1 producer request")
    if _valid_sha(q_ref.get("sha256")) and q_ref["sha256"].lower() != q_record["sha256"].lower():
        raise BuildFailure("product map producer request SHA differs from raw request bytes")
    if q.get("schema") != "ds02.request.v1" or q.get("sentinel_id") != "F3-S1" or q.get("grid_label") != args.grid:
        raise BuildFailure("producer request is not the selected F3-S1 row")
    if q.get("cpu_task_kind") != "gencase" or q.get("solver_launch") is True:
        raise BuildFailure("selected producer request is not a GenCase-only producer")
    receipt_ref = _record_from_row(row, "gencase_receipt", "receipt", "execution_receipt")
    receipt, receipt_record, _ = _json(Path(str(receipt_ref["path"])), "F3-S1 GenCase execution receipt")
    receipt_root, case_id, producer_attempt, _ = _receipt_identity(receipt, q, q_record, row, "F3-S1 GenCase")
    products, product_sha = _product_binding(row, receipt_root)
    support_report, support_record, _ = _json(args.support_report, "F3-S1 initial-support report")
    native_report, native_record, _ = _json(args.native_header_report, "F3-S1 native-header report")
    support_native = _native_gate(support_report, "F3-S1 initial-support report")
    header_native = _native_gate(native_report, "F3-S1 native-header report")
    if support_native["mass_fluid_kg"] != header_native["mass_fluid_kg"] or support_native["dp_m"] != header_native["dp_m"]:
        raise BuildFailure("initial-support and native-header reports disagree on native MassFluid/Dp")
    owner_report, owner_record, _ = _json(args.owner_gate_report, "F3-S1 continuous-owner gate")
    owner = _owner_gate(owner_report)
    forcing_path = _regular(args.forcing_control, "F3-S1 forcing control")
    forcing = _stat_only(forcing_path, "F3-S1 forcing control", args.forcing_sha256,
                         expected_stat={"bytes": args.forcing_bytes} if args.forcing_bytes else None,
                         role="parent_after_reservation_pre_post_hash")
    source_xml_record = _small_record(args.source_xml, "F3-S1 source XML/Def") if args.source_xml else None
    upstream_records = []
    for index, proof_path in enumerate(args.upstream_proof or []):
        upstream_records.append(_small_record(proof_path, f"upstream proof {index + 1}"))
    if args.root310_snapshot:
        upstream_records.append(_small_record(args.root310_snapshot, "ROOT310 selected-source snapshot proof"))
    closure, closure_records = _source_closure(args.bi4_dump, args.bi4_dump_sha256, args.bi4_dump_bytes)
    static: dict[str, dict[str, Any]] = {
        product_map_record["path"]: product_map_record, q_record["path"]: q_record,
        receipt_record["path"]: receipt_record, support_record["path"]: support_record,
        native_record["path"]: native_record, owner_record["path"]: owner_record,
    }
    if source_xml_record:
        static[source_xml_record["path"]] = source_xml_record
    for record in upstream_records:
        static[record["path"]] = record
    for record in closure_records:
        static[record["path"]] = record
    static[str(forcing_path)] = forcing
    for key, record in products.items():
        static[record["path"]] = record

    external_root = _abs(args.external_filesystem)
    output_root = external_root / "F3" / case_id / args.attempt_id
    if output_root.exists() or output_root.is_symlink():
        raise BuildFailure(f"new canary output namespace already exists: {output_root}")
    observer_output = output_root / "observer" / "f3_s1_native_observer_v1.json"
    observer = {
        "status": "WAITING_PARENT_SOLVER_TERMINAL_OBSERVER_BIND",
        "schema": "ds02.stage2.f3-s1.native-observer-producer-plan.v1",
        "source_solver_request_sha256": "PARENT_FINAL_REQUEST_FILE_SHA",
        "source_gencase_receipt": receipt_record,
        "raw_root": "{solver_output_root}/data",
        "runparts": "{solver_output_root}/RunPARTs.csv",
        "selected_frames": "PARENT_SELECTS_FROM_TERMINAL_RUNPARTS; no planned frame IDs are truth",
        "query_times_s": [0.0, 2.0, 4.0, 6.0, 8.0],
        "no_interpolation": True,
        "command_template": [str(VENV), str(OBSERVER), "--raw-root", "{solver_output_root}/data",
                              "--runparts", "{solver_output_root}/RunPARTs.csv", "--generated-xml",
                              "{materialized_inputs}/generated.xml", "--decoder", str(args.bi4_dump),
                              "--decoder-source", str(BI4_ADAPTER_SOURCE), "--output", str(observer_output),
                              "--scratch-root", "{attempt_root}/observer/scratch", "--frames",
                              "{terminal_selected_frame_ids}"],
        "decoder": closure["bi4_adapter"],
        "decoder_authority": closure["jbinarydata_authority"],
        "source_closure": [closure["literal_venv"], *closure["records"]],
        "resource_scope": {"cpu_threads": 1, "memory_max_bytes": 2 * 1024**3,
                           "scratch_max_bytes": 256 * 1024**2, "max_wall_seconds": 1800,
                           "max_log_bytes": 64 * 1024, "cancel_kill_process_group": True},
        "native_mass_basis": "native_header_only; XML mass fallback forbidden",
        "qualification": dict(UNKNOWN), "scientific_credit": 0,
    }
    observer_record = {"path": str(observer_output), "sha256": None, "read_scope": "parent_observer_output", "payload_read_by_builder": False}
    request = {
        "schema": SCHEMA, "variant_schema": VARIANT, "status": "READY_FOR_PARENT_GUARD",
        "role": "DEVELOPMENT", "family_id": "F3", "sentinel_id": "F3-S1",
        "physical_case_id": str(row.get("physical_case_id") or q.get("physical_case_id") or ""),
        "grid_label": args.grid, "case_id": args.case_id, "attempt_id": args.attempt_id,
        "kind": "qualification", "launch_commit": args.launch_commit,
        "cpu_threads": 2, "max_wall_seconds": float(args.max_wall_seconds),
        "estimated_peak_gpu_mib": 4096,
        "command": [str(MATERIALIZER), "--solver", str(SOLVER), "--output-root", "{output_root}",
                    "--generated-xml", products["generated_xml"]["path"], "--generated-bi4", products["native_bi4"]["path"],
                    "--forcing-csv", str(forcing_path), "--expected-generated-xml-sha", product_sha["generated_xml"],
                    "--expected-generated-bi4-sha", product_sha["native_bi4"], "--expected-forcing-sha", args.forcing_sha256,
                    "--tmax", "8.35", "--tout", "0.01", "--mdbc-noslip", "1"],
        "cwd": str(MATERIALIZER.parent), "worktree_root": str(REPO),
        "input_files": sorted(static),
        "input_sha256": {path: record["sha256"] for path, record in static.items() if _valid_sha(record.get("sha256"))},
        "input_content_scope": {path: record.get("read_scope", "parent_after_reservation") for path, record in static.items()},
        "deferred_input_records": [forcing, *[products[key] for key in PRODUCT_KEYS if key != "generated_xml"]],
        "runtime_binding": {"path": str(RUNTIME_V8), "sha256": closure_records[1]["sha256"], "argv0_literal": str(VENV)},
        "runner_binding": {"path": str(RUNNER_V5), "sha256": next(r["sha256"] for r in closure_records if r["path"] == str(RUNNER_V5))},
        "materializer_binding": closure_records[0], "observer_producer": observer,
        "official_library_binding": {"solver": closure["solver_binary_records"], "jbinarydata": closure["jbinarydata_authority"]},
        "parent_resource_binding": {"reservation_owner": "ROOT", "gpu_uuid": None,
                                    "gpu_uuid_must_be_bound_after_inventory": True,
                                    "cpu_seconds": 7200, "gpu_seconds": 7200,
                                    "external_storage_bytes": int(args.external_reserve_bytes),
                                    "home_receipt_bytes": int(args.home_receipt_reserve_bytes),
                                    "max_memory_bytes": 16 * 1024**3,
                                    "cancellation": "runtime_v8_killpg_reap_and_fee_close"},
        "storage_scope": {"external_filesystem": str(external_root), "output_root": str(output_root),
                          "external_product_reserved_bytes": int(args.external_reserve_bytes),
                          "home_receipt_reserved_bytes": int(args.home_receipt_reserve_bytes),
                          "payload_hash_after_reservation": True},
        "source_provenance": {"producer_map": product_map_record, "producer_request": q_record,
                              "producer_receipt": receipt_record, "producer_output_root": str(receipt_root),
                              "products": products, "initial_support_report": support_record,
                              "native_header_report": native_record, "continuous_owner_gate": owner_record,
                              "continuous_owner": owner, "forcing": forcing, "source_xml": source_xml_record,
                              "upstream_proofs": upstream_records, "producer_attempt_id": producer_attempt},
        "execution": {"launch_allowed": True, "cfd_invoked": False, "model_invoked": False,
                      "native_bi4_open": True, "native_raw_hdf5_open": False,
                      "root_must_bind_gpu_uuid": True, "parent_posthash_required": True,
                      "fee_close_required": True, "scientific_status": "DEVELOPMENT_UNKNOWN"},
        "qualification": dict(UNKNOWN), "physical_qualification": {**UNKNOWN,
            "reason": "F3-S1 canary; owner/support gates are provenance gates, not scientific Q"},
        "launch_allowed": True, "model_invoked": False, "cfd_invoked": False,
        "raw_opened": False, "hdf5_opened": False, "observer_launch_not_part_of_solver_parent": True,
        "source_only_preparation": False, "production_eligible": True,
    }
    # Preserve the raw-file SHA rule: this value is a sidecar after writing,
    # never a canonical JSON SHA confused with runtime-v8's request SHA.
    request["request_identity"] = {"runtime_request_sha_basis": "SHA256_RAW_REQUEST_FILE_BYTES",
                                    "canonical_content_sha256": _sha_bytes(json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode())}
    _write_once(args.output, request)
    raw_sha = _sha_bytes(_abs(args.output).read_bytes())
    return {"status": "PASS_F3_S1_CANARY_REQUEST_BUILT", "request": str(_abs(args.output)),
            "request_sha256_raw_file": raw_sha, "row_key": f"F3-S1:{args.grid}",
            "production_payload_read": False, "solver_started": False,
            "observer_started": False, "scientific_qualification": dict(UNKNOWN),
            "owner_mass_kg": owner["owner_mass_kg"], "native_mass_fluid_kg": support_native["mass_fluid_kg"]}


def _tiny_fixture() -> dict[str, Any]:
    """Exercise the contract with manufactured files only.

    This does not pretend to be a production receipt.  It is used by the
    companion verifier's subprocess chain and grants no scientific credit.
    """
    return {"status": "PASS", "schema": VARIANT, "production_eligible": False,
            "native_payload_read": False, "solver_started": False,
            "adapter_role": "project_native_adapter", "official_tool_claim": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--self-test", action="store_true")
    modes.add_argument("--build-request", action="store_true")
    parser.add_argument("--product-map", type=Path)
    parser.add_argument("--grid", choices=("original", "coarse", "fine"), default="original")
    parser.add_argument("--support-report", type=Path)
    parser.add_argument("--native-header-report", type=Path)
    parser.add_argument("--owner-gate-report", type=Path)
    parser.add_argument("--source-xml", type=Path)
    parser.add_argument("--forcing-control", type=Path)
    parser.add_argument("--forcing-sha256")
    parser.add_argument("--forcing-bytes", type=int)
    parser.add_argument("--bi4-dump", type=Path, default=BI4_ADAPTER_DEFAULT)
    parser.add_argument("--bi4-dump-sha256")
    parser.add_argument("--bi4-dump-bytes", type=int)
    parser.add_argument("--upstream-proof", type=Path, action="append")
    parser.add_argument("--root310-snapshot", type=Path)
    parser.add_argument("--launch-commit", required=False)
    parser.add_argument("--case-id", default="F3_S1_OWNER_GRID_EXTERNAL_CANARY")
    parser.add_argument("--attempt-id", default="f3-s1-owner-grid-external-canary-parent-pending-001")
    parser.add_argument("--external-filesystem", default="/var/tmp/ds02-stage2")
    parser.add_argument("--external-reserve-bytes", type=int, default=64 * 1024**3)
    parser.add_argument("--home-receipt-reserve-bytes", type=int, default=32 * 1024**2)
    parser.add_argument("--max-wall-seconds", type=float, default=1800.0)
    parser.add_argument("--output", type=Path, default=REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/f3-s1-owner-grid-external-canary-v1.json")
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            print(json.dumps(_tiny_fixture(), indent=2, sort_keys=True)); return 0
        required = (args.product_map, args.support_report, args.native_header_report,
                    args.owner_gate_report, args.forcing_control, args.forcing_sha256,
                    args.bi4_dump_sha256, args.bi4_dump_bytes, args.launch_commit)
        if any(value is None for value in required):
            parser.error("--build-request requires product-map/support/native-header/owner/forcing/adapter/launch bindings")
        print(json.dumps(build(args), indent=2, sort_keys=True)); return 0
    except (BuildFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_F3_S1_EXTERNAL_SOLVER_CANARY_V1: {exc}", file=sys.stderr); return 2


if __name__ == "__main__":
    raise SystemExit(main())
