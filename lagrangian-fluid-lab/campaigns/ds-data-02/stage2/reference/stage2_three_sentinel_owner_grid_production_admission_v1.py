#!/usr/bin/env python3
"""Strict, read-only admission preflight for a completed ROOT345 product row.

The source-prepared GenCase package and the F3-S1 external-solver canary are
useful inputs, but neither is an admission decision.  This module is the
small consumer between them and the parent runtime.  It joins one actual
producer request, one raw-byte execution receipt, the four generated product
records, the initial-support/native-header report, the continuous-owner gate,
and the external-v5 launch binding.

The preflight reads only bounded JSON/source files.  Generated XML/BI4/VTK and
forcing files are stat'ed and compared with a producer-provided SHA; their
contents are deliberately not opened here.  A missing custom ``bi4_dump``
build proof is a WAITING result.  The adapter uses the official
DualSPHysics JBinaryData library, but it is not itself an official tool and
must never be silently treated as one.

This is a source-only admission artifact.  It does not reserve a runtime,
launch GenCase, invoke external-v5, read native arrays, or grant QI/QN/QE.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Iterable


HERE = Path(__file__).resolve().parent
# ``HERE`` is the ``.../DualSPHysics/lagrangian-fluid-lab/.../reference``
# directory.  Its fourth parent is the worktree's DualSPHysics root; using
# the fifth parent silently dropped that component and produced paths in the
# worktrees directory itself.
REPO = HERE.parents[4]
VENV = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
PYVENV = VENV.parent.parent / "pyvenv.cfg"
RUNTIME_V8 = REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
RUNNER_V5 = REPO / "lagrangian-fluid-lab/scripts/ds_data02_stage2_external_solver_v5.py"
MATERIALIZER = HERE / "stage2_f3_s1_external_solver_canary_materialize.py"
OBSERVER = HERE / "stage2_native_physical_observer_v2.py"
ENFORCER = HERE / "stage2_native_physical_observer_enforcer_v2.py"
ENFORCER_V1 = HERE / "stage2_native_physical_observer_enforcer_v1.py"
CANARY = HERE / "stage2_f3_s1_external_solver_canary_v1.py"
BI4_SOURCE = REPO / "lagrangian-fluid-lab/scripts/native/bi4_dump.cpp"
# The checked-in official JBinaryData source is under the DualSPHysics source
# tree.  The external solver package may expose a separately built adapter;
# that binary is handled by ``--adapter`` and never inferred from this path.
JBD_ROOT = REPO / "src/source"
JBD_HEADER = JBD_ROOT / "JBinaryData.h"
JBD_SOURCE = JBD_ROOT / "JBinaryData.cpp"

SCHEMA = "ds02.stage2.three-sentinel.owner-grid-production-admission.v1"
PRODUCT_SCHEMA_PREFIX = "ds02.stage2.three-sentinel.owner-grid-gencase-product-map"
REQUEST_SCHEMA = "ds02.request.v1"
RECEIPT_SCHEMA = "ds02.execution-receipt.v1"
JSON_CAP = 10 * 1024 * 1024
SHA_RE = re.compile(r"^[0-9a-fA-F]{64}$")
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
PRODUCT_NAMES = {
    "generated_xml": "generated.xml",
    "native_bi4": "generated.bi4",
    "fluid_vtk": "generated_Fluid.vtk",
    "bound_vtk": "generated_Bound.vtk",
}


class AdmissionFailure(RuntimeError):
    """A hard source/identity contradiction, distinct from a waiting gate."""


class Gate:
    def __init__(self) -> None:
        self.rejected: list[dict[str, str]] = []
        self.waiting: list[dict[str, str]] = []
        self.checked: list[str] = []

    def reject(self, code: str, detail: str) -> None:
        self.rejected.append({"code": code, "detail": detail})

    def wait(self, code: str, detail: str) -> None:
        self.waiting.append({"code": code, "detail": detail})

    def check(self, label: str, condition: bool, *, code: str, detail: str,
              waiting: bool = False) -> bool:
        self.checked.append(label)
        if condition:
            return True
        (self.wait if waiting else self.reject)(code, detail)
        return False


def _absolute(path: Path | str) -> Path:
    return Path(path).expanduser().absolute()


def _regular(path: Path | str, label: str) -> Path:
    value = _absolute(path)
    if value.is_symlink() or not value.is_file():
        raise AdmissionFailure(f"{label} is not a regular non-symlink file: {value}")
    return value


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and bool(SHA_RE.fullmatch(value))


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {
        "device": int(value.st_dev), "inode": int(value.st_ino),
        "bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
    }


def _stat_alias(record: dict[str, Any], key: str) -> Any:
    aliases = {
        "device": ("device", "st_dev"), "inode": ("inode", "st_ino"),
        "bytes": ("bytes", "size"), "mtime_ns": ("mtime_ns",),
        "ctime_ns": ("ctime_ns",),
    }
    for name in aliases[key]:
        if name in record:
            return record[name]
    return None


def _stat_matches(actual: dict[str, int], expected: Any) -> bool:
    if not isinstance(expected, dict):
        return False
    for key in actual:
        value = _stat_alias(expected, key)
        if value is None or int(value) != actual[key]:
            return False
    return True


def _small_record(path: Path | str, label: str) -> tuple[dict[str, Any], bytes]:
    value = _regular(path, label)
    before = _stat(value)
    if before["bytes"] > JSON_CAP:
        raise AdmissionFailure(f"{label} exceeds the 10 MiB metadata cap: {value}")
    raw = value.read_bytes()
    after = _stat(value)
    if before != after or len(raw) != before["bytes"]:
        raise AdmissionFailure(f"{label} changed during bounded read: {value}")
    return ({"path": str(value), "sha256": _sha(raw), "bytes": len(raw),
             "stat_before": before, "stat_after": after,
             "read_scope": "bounded_small_metadata", "payload_read_by_builder": True}, raw)


def _small_json(path: Path | str, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    record, raw = _small_record(path, label)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AdmissionFailure(f"{label} is not valid bounded UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise AdmissionFailure(f"{label} must be a JSON object")
    return value, record


def _stat_product(path: Path | str, label: str, expected_sha: Any,
                  expected_stat: Any, gate: Gate) -> dict[str, Any] | None:
    """Stat a generated product, never hash or open its content."""
    try:
        value = _regular(path, label)
    except AdmissionFailure as exc:
        gate.wait("PRODUCT_NOT_PRESENT_AFTER_PARENT", str(exc))
        return None
    actual = _stat(value)
    if not _valid_sha(expected_sha):
        gate.wait("PRODUCT_SHA_NOT_ESTABLISHED", f"{label} has no terminal producer SHA")
    if not isinstance(expected_stat, dict):
        gate.wait("PRODUCT_STAT_NOT_ESTABLISHED", f"{label} has no terminal producer stat")
    elif not _stat_matches(actual, expected_stat):
        gate.reject("PRODUCT_STAT_MISMATCH", f"{label} stat differs from product map")
    return {"path": str(value), "sha256": str(expected_sha).lower() if _valid_sha(expected_sha) else None,
            "stat": actual, "read_scope": "stat_only_parent_product", "payload_read_by_builder": False}


def _terminal(value: Any) -> bool:
    text = str(value or "").upper()
    return any(word in text for word in ("COMPLETED", "SUCCESS", "VERIFIED", "PASS")) and "FAIL" not in text


def _find_named(node: Any, names: Iterable[str], prefix: str = "$") -> list[tuple[str, Any]]:
    wanted = {str(name).lower() for name in names}
    found: list[tuple[str, Any]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            path = f"{prefix}.{key}"
            if str(key).lower() in wanted:
                found.append((path, value))
            found.extend(_find_named(value, names, path))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.extend(_find_named(value, names, f"{prefix}[{index}]"))
    return found


def _first_number(node: Any, names: Iterable[str]) -> float | None:
    for _, value in _find_named(node, names):
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            return float(value)
    return None


def _first_dict(node: Any, names: Iterable[str]) -> tuple[str, dict[str, Any]] | None:
    for path, value in _find_named(node, names):
        if isinstance(value, dict):
            return path, value
    return None


def _identity_gate(report: dict[str, Any], *, sid: str, grid: str | None,
                   physical: str, label: str, gate: Gate) -> None:
    fields = (("sentinel_id", sid), ("physical_case_id", physical))
    if grid is not None:
        fields = (("sentinel_id", sid), ("grid_label", grid), ("physical_case_id", physical))
    for key, expected in fields:
        actual = report.get(key)
        if actual is not None and str(actual) != str(expected):
            gate.reject("REPORT_IDENTITY_MISMATCH", f"{label} {key}={actual!r}, expected {expected!r}")


def _report_native(report: dict[str, Any], *, sid: str, grid: str, physical: str,
                   product: dict[str, Any], label: str, gate: Gate) -> dict[str, Any] | None:
    _identity_gate(report, sid=sid, grid=grid, physical=physical, label=label, gate=gate)
    gate.check(f"{label}:terminal", _terminal(report.get("status")), code="REPORT_NOT_TERMINAL",
               detail=f"{label} status={report.get('status')!r}", waiting=True)
    native_item = _first_dict(report, ("native_header", "native_fields", "native", "header"))
    if native_item is None:
        gate.wait("NATIVE_HEADER_FIELDS_MISSING", f"{label} has no native header field object")
        return None
    native_path, native = native_item
    mf = _first_number(native, ("MassFluid", "mass_fluid_kg", "native_mass_fluid_kg"))
    mb = _first_number(native, ("MassBound", "mass_bound_kg", "native_mass_bound_kg"))
    dp = _first_number(native, ("Dp", "dp_m", "point_spacing_m"))
    if mf is None or mb is None or dp is None or mf <= 0 or mb < 0 or dp <= 0:
        gate.wait("NATIVE_HEADER_FIELDS_INCOMPLETE", f"{label} native MassFluid/MassBound/Dp is incomplete")
    finite = report.get("all_finite", report.get("finite"))
    gate.check(f"{label}:finite", finite is True, code="NATIVE_FIELDS_NOT_FINITE_CERTIFIED",
               detail=f"{label} lacks all_finite=true", waiting=True)
    roles = _first_dict(report, ("role_counts", "counts_by_role"))
    if roles is None:
        gate.wait("NATIVE_ROLE_COUNTS_MISSING", f"{label} has no typed role counts")
    else:
        role_values = {str(k).lower(): v for k, v in roles[1].items()}
        gate.check(f"{label}:fluid_role", any(k in role_values for k in ("fluid", "fluid_count", "fluid_particles")),
                   code="NATIVE_FLUID_ROLE_MISSING", detail=f"{label} has no fluid role", waiting=True)
        gate.check(f"{label}:bound_role", any(k in role_values for k in ("bound", "bound_count", "fixed", "fixed_count")),
                   code="NATIVE_BOUND_ROLE_MISSING", detail=f"{label} has no bound/fixed role", waiting=True)
    basis = " ".join(str(report.get(key, "")) for key in ("mass_basis", "mass_source", "source_of_mass")).lower()
    xml_fallback = any(token in basis for token in ("xml fallback", "xml_fallback", "xml-weighted", "xml weighted"))
    gate.check(f"{label}:native_mass_authority", "native" in basis and not xml_fallback,
               code="NATIVE_MASS_XML_FALLBACK_OR_UNDECLARED", detail=f"{label} mass basis is not native-only", waiting=True)

    # The report must point to the actual generated BI4 record.  A textual
    # ``native`` label is insufficient to establish this join.
    product_path = str(product.get("path"))
    product_sha = product.get("sha256")
    matches = []
    for path, value in _find_named(report, ("source_file", "source_path", "native_bi4", "bi4", "source_record")):
        if isinstance(value, str):
            matches.append((path, value, None))
        elif isinstance(value, dict):
            matches.append((path, value.get("path"), value.get("sha256")))
    joined = any(str(p) == product_path and (not product_sha or str(s).lower() == str(product_sha).lower()) for _, p, s in matches)
    gate.check(f"{label}:product_join", joined, code="NATIVE_REPORT_PRODUCT_JOIN_MISSING",
               detail="native report does not bind the generated BI4 path and producer SHA", waiting=True)
    return {"path": native_path, "mass_fluid_kg": mf, "mass_bound_kg": mb, "dp_m": dp,
            "roles": roles[1] if roles else None, "mass_basis": basis,
            "product_join": joined, "status": report.get("status")}


def _owner_gate(report: dict[str, Any], *, sid: str, physical: str, gate: Gate) -> dict[str, Any] | None:
    _identity_gate(report, sid=sid, grid=None, physical=physical, label="continuous-owner", gate=gate)
    status = str(report.get("status", ""))
    gate.check("owner:terminal", _terminal(status) and "OWNER" in status.upper(), code="OWNER_NOT_VERIFIED",
               detail=f"owner report status={status!r}", waiting=True)
    mass = _first_number(report, ("owner_mass_kg", "continuous_owner_mass_kg"))
    volume = _first_number(report, ("owner_volume_m3", "continuous_owner_volume_m3"))
    gate.check("owner:positive_mass", mass is not None and mass > 0, code="OWNER_MASS_MISSING", detail="owner mass is not finite positive", waiting=True)
    gate.check("owner:positive_volume", volume is not None and volume > 0, code="OWNER_VOLUME_MISSING", detail="owner volume is not finite positive", waiting=True)
    source = _first_dict(report, ("geometry_source", "owner_source", "source_geometry"))
    source_sha = (source[1].get("sha256") if source else None) or report.get("geometry_sha256")
    gate.check("owner:geometry_sha", _valid_sha(source_sha), code="OWNER_GEOMETRY_SHA_MISSING", detail="owner geometry source SHA is not concrete", waiting=True)
    control = report.get("control_equivalence") is True or (isinstance(report.get("control_gate"), dict) and report["control_gate"].get("status") in ("PASS", "VERIFIED"))
    gate.check("owner:control", control, code="OWNER_CONTROL_NOT_EXACT", detail="owner report does not establish exact control equivalence", waiting=True)
    basis = str(report.get("mass_basis", "")).lower()
    xml_fallback = any(token in basis for token in ("xml fallback", "xml_fallback", "xml-weighted", "xml weighted"))
    gate.check("owner:continuous_basis", "continuous" in basis and "discrete" not in basis and not xml_fallback,
               code="OWNER_DISCRETE_OR_XML_BASIS", detail="owner mass is not a continuous source geometry integral", waiting=True)
    return {"mass_kg": mass, "volume_m3": volume, "geometry_sha256": str(source_sha).lower() if _valid_sha(source_sha) else None,
            "control_equivalence": control, "mass_basis": report.get("mass_basis"), "status": status}


def _receipt_and_products(row: dict[str, Any], gate: Gate) -> dict[str, Any] | None:
    producer = row.get("producer_request") or row.get("gencase_request")
    receipt_ref = row.get("gencase_receipt") or row.get("receipt") or row.get("execution_receipt")
    if not isinstance(producer, dict) or not isinstance(receipt_ref, dict):
        gate.wait("PRODUCER_RECEIPT_REFS_MISSING", "product row lacks producer request or execution receipt record")
        return None
    try:
        q, q_rec = _small_json(producer["path"], "producer request")
        receipt, receipt_rec = _small_json(receipt_ref["path"], "GenCase execution receipt")
    except (KeyError, AdmissionFailure) as exc:
        gate.reject("PRODUCER_METADATA_UNREADABLE", str(exc))
        return None
    gate.check("producer:raw_request_sha", _valid_sha(producer.get("sha256")) and str(producer["sha256"]).lower() == q_rec["sha256"].lower(),
               code="PRODUCER_REQUEST_SHA_MISMATCH", detail="product-map request SHA is not raw request-file SHA")
    schema_ok = q.get("schema") == REQUEST_SCHEMA and receipt.get("schema", RECEIPT_SCHEMA) == RECEIPT_SCHEMA
    gate.check("producer:schemas", schema_ok, code="PRODUCER_SCHEMA_MISMATCH", detail="request/receipt schema is not runtime-v8", waiting=True)
    gate.check("producer:status", _terminal(receipt.get("status")) and receipt.get("returncode") == 0,
               code="PRODUCER_NOT_COMPLETED", detail="GenCase receipt is not completed with returncode 0", waiting=True)
    if isinstance(receipt.get("request"), dict):
        gate.check("producer:receipt_request", {k: v for k, v in receipt["request"].items() if k != "request_sha256"} == q,
                   code="PRODUCER_RECEIPT_REQUEST_MISMATCH", detail="receipt.request differs from raw producer request")
    else:
        gate.wait("PRODUCER_RECEIPT_REQUEST_MISSING", "receipt has no embedded request document")
    gate.check("producer:receipt_sha", receipt.get("request_sha256") == q_rec["sha256"],
               code="PRODUCER_RECEIPT_REQUEST_SHA_MISMATCH", detail="receipt request_sha256 is not raw request-file SHA")
    gate.check("producer:gencase_only", q.get("cpu_task_kind") == "gencase" and q.get("solver_launch") is not True,
               code="PRODUCER_NOT_GENCASE_ONLY", detail="producer request can invoke a solver")
    command = q.get("command")
    command_ok = isinstance(command, list) and len(command) >= 3 and "gencase" in Path(str(command[0])).name.lower() and str(command[1]).endswith("_Def")
    gate.check("producer:official_cli", command_ok, code="GENCASE_CLI_CONVENTION_UNPROVEN", detail="command does not preserve candidate *_Def stem")
    output_root_text = receipt.get("output_root") or q.get("output_root")
    if not isinstance(output_root_text, str):
        gate.wait("PRODUCER_OUTPUT_ROOT_MISSING", "receipt has no output_root")
        return {"request": q, "request_record": q_rec, "receipt": receipt, "receipt_record": receipt_rec}
    output_root = _absolute(output_root_text)
    gate.check("producer:output_root", output_root.is_dir() and not output_root.is_symlink(),
               code="PRODUCER_OUTPUT_ROOT_NOT_PRESENT", detail=f"output root not present: {output_root}", waiting=True)
    product_records: dict[str, Any] = {}
    for key, expected_name in PRODUCT_NAMES.items():
        item = row.get(key) or (row.get("products") or {}).get(key)
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            gate.wait("PRODUCT_RECORD_MISSING", f"row lacks {key} record")
            continue
        path = _absolute(item["path"])
        gate.check(f"product:{key}:root", path.parent == output_root and path.name == expected_name,
                   code="PRODUCT_PATH_IDENTITY_MISMATCH", detail=f"{key} is not {output_root / expected_name}")
        product_records[key] = _stat_product(path, key, item.get("sha256"), item.get("stat"), gate)
    physical = str(row.get("physical_case_id") or q.get("physical_case_id") or "")
    case_id = str(row.get("case_id") or q.get("case_id") or "")
    attempt_id = str(row.get("attempt_id") or q.get("attempt_id") or "")
    for key, expected in (("case_id", case_id), ("attempt_id", attempt_id), ("physical_case_id", physical)):
        if expected:
            gate.check(f"producer:{key}", receipt.get(key, receipt.get("request", {}).get(key)) == expected,
                       code="PRODUCER_IDENTITY_MISMATCH", detail=f"receipt {key} is not {expected!r}")
    return {"request": q, "request_record": q_rec, "receipt": receipt, "receipt_record": receipt_rec,
            "output_root": str(output_root), "case_id": case_id, "attempt_id": attempt_id,
            "physical_case_id": physical, "products": product_records}


def _adapter_gate(adapter: Path | None, adapter_sha: str | None, adapter_bytes: int | None,
                  proof_path: Path | None, gate: Gate) -> dict[str, Any]:
    result: dict[str, Any] = {"tool_role": "project_native_adapter", "official_tool_claim": False,
                              "library_authority": "official DualSPHysics JBinaryData", "status": "UNKNOWN"}
    if adapter is None or adapter_sha is None or adapter_bytes is None:
        gate.wait("NATIVE_ADAPTER_BUILD_CLOSURE_UNKNOWN", "bi4_dump executable/SHA/bytes not supplied; custom adapter cannot be admitted")
        return result
    try:
        path = _regular(adapter, "bi4_dump adapter")
    except AdmissionFailure as exc:
        gate.wait("NATIVE_ADAPTER_NOT_PRESENT", str(exc)); return result
    actual = _stat(path)
    gate.check("adapter:bytes", actual["bytes"] == int(adapter_bytes), code="NATIVE_ADAPTER_SIZE_MISMATCH", detail="adapter bytes differ")
    if not _valid_sha(adapter_sha):
        gate.wait("NATIVE_ADAPTER_SHA_UNKNOWN", "adapter SHA is not concrete")
    if proof_path is None:
        gate.wait("NATIVE_ADAPTER_BUILD_PROOF_MISSING", "compiled adapter build proof is absent")
        return result
    try:
        proof, proof_rec = _small_json(proof_path, "native adapter build proof")
    except (AdmissionFailure, OSError) as exc:
        gate.wait("NATIVE_ADAPTER_BUILD_PROOF_UNREADABLE", str(exc)); return result
    proof_sha = proof.get("binary_sha256") or proof.get("adapter_sha256")
    proof_status = str(proof.get("status", ""))
    gate.check("adapter:proof_terminal", _terminal(proof_status), code="NATIVE_ADAPTER_BUILD_NOT_VERIFIED", detail=f"adapter proof status={proof_status!r}", waiting=True)
    gate.check("adapter:proof_path", str(_absolute(proof.get("binary_path", ""))) == str(path), code="NATIVE_ADAPTER_PROOF_PATH_MISMATCH", detail="adapter proof is for another executable")
    gate.check("adapter:proof_sha", _valid_sha(proof_sha) and str(proof_sha).lower() == str(adapter_sha).lower(), code="NATIVE_ADAPTER_PROOF_SHA_MISMATCH", detail="adapter build proof SHA differs")
    gate.check("adapter:official_claim", proof.get("official_tool_claim") is False, code="NATIVE_ADAPTER_OFFICIAL_TOOL_AMBIGUOUS", detail="custom adapter is incorrectly claimed as official", waiting=True)
    result.update({"status": "VERIFIED" if not gate.waiting and not gate.rejected else "WAITING",
                   "binary": {"path": str(path), "sha256": str(adapter_sha).lower(), "bytes": actual["bytes"], "stat": actual},
                   "proof": proof_rec, "proof_status": proof_status})
    return result


def _launch_gate(path: Path | None, gate: Gate) -> dict[str, Any]:
    if path is None:
        gate.wait("EXTERNAL_V5_BINDING_MISSING", "external-v5 launch binding is not supplied")
        return {"status": "WAITING"}
    try:
        binding, record = _small_json(path, "external-v5 launch binding")
    except (AdmissionFailure, OSError) as exc:
        gate.wait("EXTERNAL_V5_BINDING_UNREADABLE", str(exc)); return {"status": "WAITING"}
    status = str(binding.get("status", ""))
    gate.check("external:status", status in {"READY_FOR_PARENT_GUARD", "READY_FOR_PARENT_EXTERNAL_V5", "READY_FOR_PARENT_EXTERNAL_V5_F3_COARSE_AFTER_ROOT128_SUPPORT_AND_BI4_SNAPSHOT"}, code="EXTERNAL_V5_BINDING_NOT_READY", detail=f"binding status={status!r}", waiting=True)
    gpu = binding.get("gpu_uuid") or (binding.get("parent_resource_binding") or {}).get("gpu_uuid")
    gate.check("external:gpu_deferred", gpu in (None, "PARENT_AFTER_INVENTORY", "ROOT_AFTER_INVENTORY"), code="EXTERNAL_GPU_PREBOUND", detail="GPU UUID must be bound after parent inventory")
    resources = binding.get("parent_resource_binding") or binding.get("resource_scope") or {}
    memory = resources.get("max_memory_bytes", resources.get("memory_max_bytes", 0))
    ext = resources.get("external_storage_bytes", resources.get("external_reserve_bytes", 0))
    gate.check("external:memory", isinstance(memory, (int, float)) and int(memory) >= 4 * 1024**3, code="EXTERNAL_MEMORY_UNBOUNDED", detail="external-v5 memory reservation is below 4 GiB", waiting=True)
    gate.check("external:storage", isinstance(ext, (int, float)) and int(ext) > 0, code="EXTERNAL_STORAGE_UNBOUNDED", detail="external-v5 external storage reservation is missing", waiting=True)
    gate.check("external:cancellation", bool(binding.get("cancellation") or resources.get("cancellation")), code="EXTERNAL_CANCELLATION_UNBOUND", detail="kill-group/fee-close policy missing", waiting=True)
    return {"status": status, "record": record, "gpu_uuid": gpu, "resource_scope": resources,
            "solver_binding": binding.get("solver_binary_records") or binding.get("official_library_binding")}


def _source_record(path: Path | None, label: str, gate: Gate) -> dict[str, Any] | None:
    if path is None:
        gate.wait("SOURCE_CONTROL_BINDING_MISSING", f"{label} is not supplied")
        return None
    try:
        record, _ = _small_record(path, label)
        return record
    except AdmissionFailure as exc:
        gate.wait("SOURCE_CONTROL_BINDING_UNREADABLE", str(exc)); return None


def _venv_closure(gate: Gate) -> dict[str, Any]:
    """Bind the literal argv0 and its resolved interpreter without replacing it."""
    if not VENV.exists():
        gate.wait("LITERAL_VENV_NOT_BOUND", f"literal venv interpreter is absent: {VENV}")
        return {"argv0_literal": str(VENV), "status": "WAITING"}
    try:
        resolved = VENV.resolve()
        interpreter, _ = _small_record(resolved, "resolved venv interpreter")
        cfg, _ = _small_record(PYVENV, "pyvenv.cfg")
    except AdmissionFailure as exc:
        gate.wait("LITERAL_VENV_CLOSURE_UNKNOWN", str(exc))
        return {"argv0_literal": str(VENV), "status": "WAITING"}
    return {"argv0_literal": str(VENV), "argv0_must_remain_literal": True,
            "resolved_interpreter": interpreter, "pyvenv_cfg": cfg,
            "system_python_fallback_allowed": False, "status": "BOUND"}


def preflight(args: argparse.Namespace) -> dict[str, Any]:
    gate = Gate()
    product_map, product_map_rec = _small_json(args.product_map, "ROOT345 product map")
    gate.check("map:schema", str(product_map.get("schema", "")).startswith(PRODUCT_SCHEMA_PREFIX), code="PRODUCT_MAP_SCHEMA_MISMATCH", detail="not a ROOT345 owner-grid product map")
    gate.check("map:terminal", _terminal(product_map.get("status")), code="PRODUCT_MAP_NOT_TERMINAL", detail=f"map status={product_map.get('status')!r}", waiting=True)
    rows = product_map.get("products", product_map.get("cases"))
    if not isinstance(rows, list):
        raise AdmissionFailure("ROOT345 product map has no products/cases list")
    target_rows = [r for r in rows if isinstance(r, dict) and r.get("sentinel_id") == args.sentinel and r.get("grid_label") == args.grid]
    gate.check("map:row_unique", len(target_rows) == 1, code="PRODUCT_ROW_NOT_UNIQUE", detail=f"expected one {args.sentinel}:{args.grid}, got {len(target_rows)}")
    if len(target_rows) != 1:
        return _result(args, gate, product_map_rec, None, None, None, None, None)
    row = target_rows[0]
    sid, grid = args.sentinel, args.grid
    physical = str(row.get("physical_case_id") or "")
    if not physical:
        gate.wait("PRODUCT_PHYSICAL_ID_MISSING", "row has no physical_case_id; no label fallback is allowed")
    producer = _receipt_and_products(row, gate)
    if producer is None:
        return _result(args, gate, product_map_rec, row, None, None, None, None)
    support, support_rec = _small_json(args.support_report, "initial-support report")
    native, native_rec = _small_json(args.native_header_report, "native-header report")
    native_summary = _report_native(native, sid=sid, grid=grid, physical=physical,
                                    product=(producer.get("products") or {}).get("native_bi4") or {},
                                    label="native-header report", gate=gate)
    support_summary = _report_native(support, sid=sid, grid=grid, physical=physical,
                                     product=(producer.get("products") or {}).get("native_bi4") or {},
                                     label="initial-support report", gate=gate)
    if support_summary and native_summary:
        gate.check("native:reports_agree", support_summary.get("mass_fluid_kg") == native_summary.get("mass_fluid_kg") and support_summary.get("dp_m") == native_summary.get("dp_m"),
                   code="NATIVE_REPORTS_DISAGREE", detail="support/native reports disagree on native header values")
    owner, owner_rec = _small_json(args.owner_report, "continuous-owner gate")
    owner_summary = _owner_gate(owner, sid=sid, physical=physical, gate=gate)
    adapter = _adapter_gate(args.adapter, args.adapter_sha256, args.adapter_bytes, args.adapter_build_proof, gate)
    launch = _launch_gate(args.launch_binding, gate)
    source_xml = _source_record(args.source_xml, "source XML/Def", gate)
    forcing = _source_record(args.forcing_control, "forcing/control metadata", gate)
    closure_paths = [RUNTIME_V8, RUNNER_V5, MATERIALIZER, OBSERVER, ENFORCER, ENFORCER_V1,
                     CANARY, HERE / Path(__file__).name, BI4_SOURCE, JBD_HEADER, JBD_SOURCE]
    closure = []
    for path in closure_paths:
        try:
            rec, _ = _small_record(path, f"source closure {path.name}")
            closure.append(rec)
        except AdmissionFailure as exc:
            # A source-only checkout can be missing the primary worktree's
            # runtime/vendor files.  This is a parent closure wait, not a
            # scientific or identity contradiction; it still prevents READY.
            gate.wait("SOURCE_CLOSURE_NOT_BOUND", str(exc))
    venv = _venv_closure(gate)
    extra = {
        "product_map": product_map_rec, "support_report": support_rec,
        "native_header_report": native_rec, "owner_report": owner_rec,
        "source_xml": source_xml, "forcing_control": forcing,
    }
    return _result(args, gate, product_map_rec, row, producer, support_summary, owner_summary,
                   {"native": native_summary, "adapter": adapter, "launch": launch,
                    "closure": closure, "literal_venv": venv, "metadata": extra})


def _result(args: argparse.Namespace, gate: Gate, product_map: dict[str, Any], row: dict[str, Any] | None,
            producer: dict[str, Any] | None, support: dict[str, Any] | None,
            owner: dict[str, Any] | None, details: dict[str, Any] | None) -> dict[str, Any]:
    if gate.rejected:
        state = "REJECTED_SOURCE_OR_IDENTITY_CONTRADICTION"
    elif gate.waiting:
        state = "WAITING_PARENT_PRODUCTION_CLOSURE"
    else:
        state = "READY_FOR_PARENT_EXTERNAL_V5_ADMISSION"
    return {
        "schema": SCHEMA, "status": state, "sentinel_id": args.sentinel,
        "grid_label": args.grid, "row_key": f"{args.sentinel}:{args.grid}",
        "physical_case_id": (row or {}).get("physical_case_id"),
        "production_credit": 0, "payload_read_by_builder": False,
        "solver_started": False, "gencase_started_by_builder": False,
        "scientific_qualification": dict(UNKNOWN),
        "reasons": {"rejected": gate.rejected, "waiting": gate.waiting,
                    "checked": gate.checked},
        "producer": producer, "native_support": support, "owner": owner,
        "details": details or {},
        "external_solver_admission": {
            "builder": str(CANARY),
            "builder_variant": "ds02.stage2.f3-s1.external-solver-canary.v1",
            "invocation": "parent invokes the canary builder only after this record is READY and binds a fresh GPU UUID/reservation",
            "required_inputs": ["ROOT345 product map", "raw producer request/receipt", "initial support report", "native header report", "continuous-owner gate", "forcing/source XML", "custom bi4_dump build proof"],
            "production_payload_read_by_this_preflight": False,
            "scientific_qualification": dict(UNKNOWN),
        },
        "next_action": ("ROOT must establish the missing parent-after-reservation or adapter closure gates; no solver admission is implied"
                         if state != "READY_FOR_PARENT_EXTERNAL_V5_ADMISSION"
                         else "ROOT may independently review and bind GPU/parent reservation before external-v5 request creation"),
        "read_scope": {"bounded_json": True, "product_files": "stat_only", "forcing_payload": False,
                       "native_bi4_payload": False, "vtk_payload": False, "solver_or_gencase_launch": False},
    }


def _write_once(path: Path, value: dict[str, Any]) -> None:
    path = _absolute(path)
    if path.exists() or path.is_symlink():
        raise AdmissionFailure(f"refusing to overwrite immutable admission report: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def _tiny_file(root: Path, name: str, content: bytes) -> Path:
    path = root / name
    path.write_bytes(content)
    return path


def _fixture() -> None:
    """Exercise actual preflight joins with tiny manufactured files only."""
    with tempfile.TemporaryDirectory(prefix="stage2-admission-", dir="/tmp") as temp:
        root = Path(temp)
        output = root / "families" / "F3" / "F3_S1_COARSE" / "attempt"
        output.mkdir(parents=True)
        products = {}
        for key, name in PRODUCT_NAMES.items():
            path = _tiny_file(output, name, (key + "-fixture\n").encode())
            products[key] = {"path": str(path), "sha256": _sha(path.read_bytes()), "stat": _stat(path)}
        q_path = root / "producer.json"
        q = {"schema": REQUEST_SCHEMA, "cpu_task_kind": "gencase", "solver_launch": False,
             "sentinel_id": "F3-S1", "grid_label": "coarse", "physical_case_id": "F3-S1-COARSE",
             "case_id": "F3_S1_COARSE", "attempt_id": "attempt",
             "command": ["GenCase_linux64", "candidate_Def", str(output / "generated")]}
        q_raw = json.dumps(q, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        q_path.write_bytes(q_raw)
        receipt_path = output / "execution-receipt.json"
        receipt = {"schema": RECEIPT_SCHEMA, "status": "completed", "returncode": 0,
                   "request_sha256": _sha(q_raw), "request": q,
                   "output_root": str(output), "case_id": q["case_id"], "attempt_id": q["attempt_id"],
                   "physical_case_id": q["physical_case_id"]}
        receipt_path.write_text(json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8")
        row = {"sentinel_id": "F3-S1", "grid_label": "coarse", "physical_case_id": q["physical_case_id"],
               "case_id": q["case_id"], "attempt_id": q["attempt_id"], "status": "COMPLETED",
               "producer_request": {"path": str(q_path), "sha256": _sha(q_raw)},
               "gencase_receipt": {"path": str(receipt_path), "sha256": _sha(receipt_path.read_bytes())}, **products}
        product_map = root / "products.json"
        product_map.write_text(json.dumps({"schema": PRODUCT_SCHEMA_PREFIX + ".v2", "status": "COMPLETED", "products": [row]}) + "\n", encoding="utf-8")
        source = _tiny_file(root, "source.xml", b"<case />\n")
        forcing = _tiny_file(root, "forcing.csv", b"t,a\n0,0\n")
        adapter = _tiny_file(root, "bi4_dump", b"adapter")
        adapter_sha = _sha(adapter.read_bytes())
        adapter_proof = root / "adapter-proof.json"
        adapter_proof.write_text(json.dumps({"status": "VERIFIED", "binary_path": str(adapter), "binary_sha256": adapter_sha,
                                             "official_tool_claim": False}) + "\n", encoding="utf-8")
        native_source = {"path": products["native_bi4"]["path"], "sha256": products["native_bi4"]["sha256"]}
        native = {"schema": "native-header.v1", "status": "COMPLETED_NATIVE_SUPPORT", "sentinel_id": "F3-S1", "grid_label": "coarse",
                  "physical_case_id": q["physical_case_id"], "native_header": {"MassFluid": 1.0, "MassBound": 2.0, "Dp": .01},
                  "source_record": native_source, "role_counts": {"fluid": 2, "bound": 1}, "all_finite": True,
                  "mass_basis": "native_header_not_XML"}
        support = dict(native); support["status"] = "COMPLETED_INITIAL_SUPPORT"
        owner = {"status": "VERIFIED_OWNER", "sentinel_id": "F3-S1", "physical_case_id": q["physical_case_id"],
                 "owner_mass_kg": 1.0, "owner_volume_m3": .001, "geometry_source": {"path": str(source), "sha256": _sha(source.read_bytes())},
                 "control_equivalence": True, "mass_basis": "continuous_source_geometry_integral"}
        def write_json(name: str, value: Any) -> Path:
            path = root / name; path.write_text(json.dumps(value) + "\n", encoding="utf-8"); return path
        support_path = write_json("support.json", support); native_path = write_json("native.json", native)
        owner_path = write_json("owner.json", owner)
        binding_path = write_json("launch.json", {"status": "READY_FOR_PARENT_EXTERNAL_V5", "gpu_uuid": None,
                                                   "parent_resource_binding": {"max_memory_bytes": 4 * 1024**3, "external_storage_bytes": 1, "cancellation": "killpg_fee_close"}})
        args = argparse.Namespace(product_map=product_map, sentinel="F3-S1", grid="coarse", support_report=support_path,
                                  native_header_report=native_path, owner_report=owner_path, source_xml=source, forcing_control=forcing,
                                  adapter=adapter, adapter_sha256=adapter_sha, adapter_bytes=adapter.stat().st_size,
                                  adapter_build_proof=adapter_proof, launch_binding=binding_path)
        result = preflight(args)
        # This isolated checkout intentionally lacks some primary runtime
        # files.  The manufactured joins therefore stop at WAITING; the test
        # proves that no missing closure is silently promoted to READY.
        assert result["status"] == "WAITING_PARENT_PRODUCTION_CLOSURE", result["status"]
        assert result["production_credit"] == 0 and result["scientific_qualification"] == UNKNOWN, result["scientific_qualification"]
        # Removing the build proof is a parent-closure wait, never a pass.
        args.adapter_build_proof = None
        waiting = preflight(args)
        assert waiting["status"] == "WAITING_PARENT_PRODUCTION_CLOSURE", waiting["status"]
        assert any(item["code"] in {"NATIVE_ADAPTER_BUILD_CLOSURE_UNKNOWN", "NATIVE_ADAPTER_BUILD_PROOF_MISSING"} for item in waiting["reasons"]["waiting"]), waiting["reasons"]
        # A changed product path is a hard identity contradiction.
        tampered_map = json.loads(product_map.read_text(encoding="utf-8"))
        tampered_map["products"][0]["native_bi4"]["path"] = str(root / "outside.bi4")
        product_map.write_text(json.dumps(tampered_map) + "\n", encoding="utf-8")
        rejected = preflight(args)
        assert rejected["status"] == "REJECTED_SOURCE_OR_IDENTITY_CONTRADICTION", rejected["status"]
    print("PASS_PRODUCTION_ADMISSION_REAL_JOIN_FIXTURE_NO_PRODUCTION_CREDIT")


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
    if args.self_test:
        try:
            _fixture()
        except (AssertionError, AdmissionFailure, OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"FAILED_PRODUCTION_ADMISSION_SELFTEST: {exc!r}")
            return 2
        return 0
    required = (args.product_map, args.support_report, args.native_header_report, args.owner_report)
    if any(value is None for value in required):
        parser.error("--preflight requires product-map/support-report/native-header-report/owner-report")
    try:
        result = preflight(args)
        if args.output:
            _write_once(args.output, result)
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        return 0 if result["status"] != "REJECTED_SOURCE_OR_IDENTITY_CONTRADICTION" else 2
    except (AdmissionFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_PRODUCTION_ADMISSION_V1: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
