#!/usr/bin/env python3
"""Metadata-only terminal CPU/storage delta adapter V4 for the V64 parent.

This forward V4 contract preserves the consumed V2 adapter and accepts the V64
parent request/report schemas in addition to the older compatibility schemas.

This is an additive, parent-schema adapter.  It joins the immutable request,
returned parent report, original Home receipt, terminal systemd evidence and
the one opaque original charge row before any ledger mutation.  ``inspect`` is
always read-only.  ``apply`` requires ``--allow-ledger-mutation`` and appends
one idempotent same-parent supplemental charge; it creates no reservation and
never edits the original charge or any scientific product.

Only bounded JSON, source code for the bound runtime, and the resource ledger
are read.  H5, BI4, raw frames, typed arrays, labels and solver products are
never opened.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

SCHEMA = "ds02.stage2.f2-v64-parent-terminal-reconciliation.v4"
REQUEST_SCHEMAS = {
    "ds02.stage2.f2-root145-copied-recovery-parent-request.v62",
    "ds02.stage2.f2-root145-copied-recovery-parent-request.v63",
    "ds02.stage2.f2-root145-copied-recovery-parent-request.v64",
    "ds02.stage2.f2-portable-executor-parent-request.v3",
}
REPORT_SCHEMAS = {
    "ds02.stage2.f2-root145-copied-recovery-report.v62",
    "ds02.stage2.f2-root145-copied-recovery-report.v63",
    "ds02.stage2.f2-root145-copied-recovery-report.v64",
    "ds02.stage2.f2-portable-executor-parent-report.v3",
}
EVIDENCE_SCHEMA = "ds02.stage2.systemd-cpu-evidence.v1"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
TERMINAL_PREFIXES = ("completed", "failed", "cancel", "timeout")
HEX64 = set("0123456789abcdef")
MAX_JSON_BYTES = 64 * 1024 * 1024


class ReconciliationError(RuntimeError):
    pass


def sha256_file(path: Path | str, *, max_bytes: int | None = None) -> str:
    target = Path(path).expanduser()
    if max_bytes is not None and target.stat().st_size > max_bytes:
        raise ReconciliationError(f"file exceeds metadata bound: {target}")
    digest = hashlib.sha256()
    with target.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _file(path: Path | str, role: str, *, max_bytes: int = MAX_JSON_BYTES) -> Path:
    target = Path(path).expanduser()
    if target.is_symlink() or not target.is_file():
        raise ReconciliationError(f"{role} is not a regular non-symlink file: {target}")
    if target.stat().st_size > max_bytes:
        raise ReconciliationError(f"{role} exceeds metadata bound: {target}")
    return target


def _json(path: Path | str, role: str, *, max_bytes: int = MAX_JSON_BYTES) -> tuple[Path, dict[str, Any]]:
    target = _file(path, role, max_bytes=max_bytes)
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ReconciliationError(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise ReconciliationError(f"{role} must be a JSON object")
    return target, value


def _sha(value: Any, role: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch not in HEX64 for ch in value):
        raise ReconciliationError(f"{role} must be a lowercase SHA-256")
    return value


def _canonical(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                      ensure_ascii=True, allow_nan=False,
                                      default=str).encode("utf-8")).hexdigest()


def _same(left: Path | str, right: Path | str) -> bool:
    return Path(left).expanduser().resolve() == Path(right).expanduser().resolve()


def _number(value: Any, role: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ReconciliationError(f"{role} must be numeric")
    value = float(value)
    if not math.isfinite(value) or value < minimum:
        raise ReconciliationError(f"{role} must be finite and >= {minimum}")
    return value


def _integer(value: Any, role: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ReconciliationError(f"{role} must be an integer >= {minimum}")
    return value


def _nsec(value: Any, role: str) -> int:
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    return _integer(value, role)


def _terminal(value: Any, role: str) -> None:
    if not isinstance(value, str) or not value.lower().startswith(TERMINAL_PREFIXES):
        raise ReconciliationError(f"{role} is not terminal: {value!r}")


def _status_family(value: Any, role: str) -> str:
    if not isinstance(value, str):
        raise ReconciliationError(f"{role} status is missing")
    status = value.strip().lower()
    if status.startswith("completed") or status in {"exited", "success", "succeeded"}:
        return "completed"
    if status.startswith("failed") or status == "failure":
        return "failed"
    if status.startswith("cancel") or status == "canceled":
        return "cancelled"
    if status.startswith("timeout"):
        return "timeout"
    raise ReconciliationError(f"{role} has unsupported terminal status: {value!r}")


def _optional_status(value: Any, role: str) -> str | None:
    if value is None:
        return None
    return _status_family(value, role)


def _request_binding(request: Mapping[str, Any]) -> dict[str, Any]:
    resource = request.get("parent_resource_binding")
    if not isinstance(resource, Mapping):
        raise ReconciliationError("parent_resource_binding is missing")
    accounting = request.get("accounting")
    if accounting is not None and not isinstance(accounting, Mapping):
        raise ReconciliationError("request accounting binding is malformed")
    charge_id = (accounting or {}).get("charge_id") or resource.get("charge_id")
    if not isinstance(charge_id, str) or not charge_id:
        raise ReconciliationError("opaque original charge_id is missing")
    reservation_id = (accounting or {}).get("reservation_id") or resource.get("reservation_id")
    if not isinstance(reservation_id, str) or not reservation_id:
        raise ReconciliationError("original reservation_id is missing")
    if reservation_id == charge_id:
        raise ReconciliationError("reservation_id must remain distinct from charge_id")
    if resource.get("reservation_id") not in {None, reservation_id}:
        raise ReconciliationError("resource reservation_id differs from accounting binding")
    if isinstance(accounting, Mapping) and accounting.get("charge_id") not in {None, charge_id}:
        raise ReconciliationError("accounting charge_id differs from resource binding")
    if resource.get("same_parent_ledger") is not True or (
            accounting is not None and accounting.get("same_parent_ledger") is not True):
        raise ReconciliationError("request is not same-parent-ledger scoped")
    ledger_path = resource.get("ledger_path")
    if not isinstance(ledger_path, str) or not ledger_path:
        raise ReconciliationError("request ledger path is missing")
    return {
        "resource": dict(resource),
        "accounting": dict(accounting or {}),
        "charge_id": charge_id,
        "reservation_id": reservation_id,
        "attempt_id": resource.get("attempt_id") or request.get("attempt_id"),
        "ledger_path": ledger_path,
        "home_path": resource.get("home_path") or "/home/jade",
        "allow_missing_parent": bool(resource.get("allow_missing_parent", False)),
    }


def _charge_row(report: Mapping[str, Any]) -> dict[str, Any]:
    outer = report.get("charge")
    if isinstance(outer, Mapping):
        nested = outer.get("charge")
        if isinstance(nested, Mapping):
            return dict(nested)
        if isinstance(outer.get("id"), str):
            return dict(outer)
    row = report.get("charge_row")
    if isinstance(row, Mapping):
        return dict(row)
    raise ReconciliationError("returned report has no charge row")


def _cpu_match(left: Mapping[str, Any], right: Mapping[str, Any], key: str) -> None:
    if abs(_number(left.get(key), f"charge.{key}") -
           _number(right.get(key), f"ledger.{key}")) > 1e-12:
        raise ReconciliationError(f"returned report and ledger charge differ: {key}")


def _integer_match(left: Mapping[str, Any], right: Mapping[str, Any], key: str) -> None:
    if _integer(left.get(key), f"returned charge {key}") != _integer(right.get(key), f"ledger {key}"):
        raise ReconciliationError(f"ledger and returned charge differ: {key}")


def _external_storage_binding(report: Mapping[str, Any], row: Mapping[str, Any]) -> dict[str, int]:
    """Validate the V64/V66 current-versus-conservative external byte contract.

    ``external_bytes`` is the current observed tree.  The V66 worker may retain
    a conservative peak that also includes its overlay and scratch accounting;
    that value is exposed as ``external_charge_bytes`` (and, for older
    producers, ``external_peak_bytes``).  The original charge must equal that
    exact peak and the peak must cover the current tree.  A missing peak keeps
    the legacy contract where the current value was the charged value.
    """
    current = _integer(report.get("external_bytes"), "returned report external_bytes")
    declared: list[tuple[str, int]] = []
    for key in ("external_charge_bytes", "external_peak_bytes"):
        if key in report and report.get(key) is not None:
            declared.append((key, _integer(report[key], f"returned report {key}")))
    filesystem = report.get("filesystem")
    if isinstance(filesystem, Mapping):
        for key in ("external_charge_bytes", "external_peak_bytes"):
            if key in filesystem and filesystem.get(key) is not None:
                declared.append((f"filesystem.{key}", _integer(filesystem[key], f"returned report filesystem.{key}")))
    if declared and len({value for _, value in declared}) != 1:
        raise ReconciliationError("returned report external peak fields differ")
    peak = declared[0][1] if declared else current
    if peak < current:
        raise ReconciliationError("returned external peak is below current external_bytes")
    charged = _integer(row.get("external_storage_bytes"), "charge external_storage_bytes")
    if charged != peak:
        raise ReconciliationError(
            "returned external charge differs from exact external peak"
        )
    return {
        "current_bytes": current,
        "peak_bytes": peak,
        "charged_bytes": charged,
    }


def _load_runtime(path: Path, expected_sha: str) -> Any:
    if sha256_file(path, max_bytes=8 * 1024 * 1024) != expected_sha:
        raise ReconciliationError("bound runtime SHA differs before ledger mutation")
    spec = importlib.util.spec_from_file_location("ds02_bound_v64_terminal_runtime", path)
    if spec is None or spec.loader is None:
        raise ReconciliationError(f"cannot load bound runtime: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not callable(getattr(module, "ledger_locked", None)):
        raise ReconciliationError("bound runtime has no ledger_locked API")
    return module


def _stat_metadata(path: Path, role: str, *, root: Path) -> dict[str, Any]:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as error:
        raise ReconciliationError(f"{role} is outside the bound Home metadata scope") from error
    return {"role": role, "path": str(path), "bytes": int(path.stat().st_size),
            "sha256": sha256_file(path)}


def _load_ledger(path: Path) -> dict[str, Any]:
    _, value = _json(path, "resource ledger", max_bytes=512 * 1024 * 1024)
    if not isinstance(value.get("charges"), list):
        raise ReconciliationError("resource ledger charges list is missing")
    return value


def inspect_binding(*, request_path: Path | str, report_path: Path | str,
                    receipt_path: Path | str, evidence_path: Path | str,
                    ledger_path: Path | str | None = None) -> dict[str, Any]:
    request_file, request = _json(request_path, "V64 parent request")
    report_file, report = _json(report_path, "returned parent report")
    receipt_file, receipt = _json(receipt_path, "original Home receipt")
    evidence_file, evidence = _json(evidence_path, "terminal systemd evidence", max_bytes=8 * 1024 * 1024)
    if request.get("schema") not in REQUEST_SCHEMAS:
        raise ReconciliationError("unsupported V62/V63/V64 request schema")
    if request.get("sha256") != _canonical(request):
        raise ReconciliationError("request canonical SHA differs")
    bind = _request_binding(request)
    request_sha = sha256_file(request_file, max_bytes=MAX_JSON_BYTES)
    if report.get("schema") not in REPORT_SCHEMAS:
        raise ReconciliationError("unsupported returned parent report schema")
    _terminal(report.get("status"), "returned parent report")
    report_family = _status_family(report.get("status"), "returned parent report")
    report_request_sha = report.get("request_sha256")
    if report_request_sha is None and isinstance(report.get("request"), Mapping):
        report_request_sha = report["request"].get("sha256")
    if report_request_sha != request_sha:
        raise ReconciliationError("returned report request SHA differs")
    report_path_value = report.get("report_path")
    if report_path_value is not None and not (_same(report_path_value, receipt_file) or _same(report_path_value, report_file)):
        raise ReconciliationError("returned report report_path is not bound to supplied metadata")
    row = _charge_row(report)
    if row.get("id") != bind["charge_id"]:
        raise ReconciliationError("returned report charge ID differs from request")
    if row.get("reservation_id") not in {None, bind["reservation_id"]}:
        raise ReconciliationError("returned report reservation_id differs from request")
    report_accounting = report.get("accounting")
    if isinstance(report_accounting, Mapping):
        if report_accounting.get("charge_id") not in {None, bind["charge_id"]}:
            raise ReconciliationError("returned report accounting charge_id differs")
        if report_accounting.get("reservation_id") not in {None, bind["reservation_id"]}:
            raise ReconciliationError("returned report accounting reservation_id differs")
    if _status_family(row.get("status"), "returned charge row") != report_family:
        raise ReconciliationError("returned report and charge terminal statuses differ")
    if bind["attempt_id"] is not None and row.get("parent_attempt_id") not in {None, bind["attempt_id"]}:
        raise ReconciliationError("returned report parent attempt differs")
    if report.get("ledger_mutated") is not True:
        raise ReconciliationError("returned report does not attest original ledger mutation")
    external_binding = _external_storage_binding(report, row)
    for report_key, row_key in (("home_bytes", "home_storage_bytes"),
                                ("trace_bytes", "trace_bytes"),
                                ("copy_hash_bytes", "copy_hash_bytes")):
        if report_key in report and row_key in row:
            if _integer(report[report_key], f"returned report {report_key}") != _integer(row[row_key], f"charge {row_key}"):
                raise ReconciliationError(f"returned report and charge differ: {report_key}")

    # Home receipt is an independent original-charge input.  It may have a
    # different schema across V62/V63/V64 and parent-v3; both forms are checked.
    receipt_request = receipt.get("request")
    if not isinstance(receipt_request, Mapping):
        raise ReconciliationError("original Home receipt request binding is missing")
    if not _same(receipt_request.get("path", ""), request_file) or receipt_request.get("sha256") != request_sha:
        raise ReconciliationError("original Home receipt is not bound to request")
    receipt_accounting = receipt.get("accounting")
    receipt_charge_id = receipt_accounting.get("charge_id") if isinstance(receipt_accounting, Mapping) else receipt.get("charge_id")
    if receipt_charge_id != bind["charge_id"]:
        raise ReconciliationError("original Home receipt charge ID differs")
    receipt_reservation_id = (receipt_accounting.get("reservation_id")
                              if isinstance(receipt_accounting, Mapping)
                              else receipt.get("reservation_id"))
    if receipt_reservation_id not in {None, bind["reservation_id"]}:
        raise ReconciliationError("original Home receipt reservation_id differs")
    receipt_status = receipt.get("status")
    if receipt_status is None and isinstance(receipt.get("execution"), Mapping):
        receipt_status = receipt["execution"].get("status")
    receipt_family = _optional_status(receipt_status, "original Home receipt")
    if receipt_family is not None and receipt_family != report_family:
        raise ReconciliationError("Home receipt and returned report terminal statuses differ")
    filesystem = receipt.get("filesystem")
    if not isinstance(filesystem, Mapping):
        raise ReconciliationError("original Home receipt filesystem binding is missing")
    home_bytes = filesystem.get("home_receipt_bytes")
    if home_bytes is not None and _integer(home_bytes, "original receipt Home bytes") != receipt_file.stat().st_size:
        raise ReconciliationError("original Home receipt byte stat differs")
    if "home_storage_bytes" in row and home_bytes is not None and _integer(row["home_storage_bytes"], "original charge Home bytes") != _integer(home_bytes, "receipt Home bytes"):
        raise ReconciliationError("original charge does not cover Home receipt bytes")

    if evidence.get("schema") != EVIDENCE_SCHEMA or evidence.get("terminal") is not True:
        raise ReconciliationError("terminal systemd evidence is not terminal v1")
    if not _same(evidence.get("request", ""), request_file) or evidence.get("request_sha256") != request_sha:
        raise ReconciliationError("systemd evidence request binding differs")
    receipt_sha = sha256_file(receipt_file)
    if not _same(evidence.get("receipt", ""), receipt_file) or evidence.get("receipt_sha256") != receipt_sha:
        raise ReconciliationError("systemd evidence receipt binding differs")
    report_sha = sha256_file(report_file)
    if not _same(evidence.get("actual_returned_report", ""), report_file) or evidence.get("actual_returned_report_sha256") != report_sha:
        raise ReconciliationError("systemd evidence returned-report binding differs")
    if evidence.get("charge_id") != bind["charge_id"]:
        raise ReconciliationError("systemd evidence charge ID differs")
    if evidence.get("reservation_id") not in {None, bind["reservation_id"]}:
        raise ReconciliationError("systemd evidence reservation_id differs")
    properties = evidence.get("systemd_properties")
    if not isinstance(properties, Mapping):
        raise ReconciliationError("systemd properties are missing")
    unit = evidence.get("unit")
    invocation = properties.get("InvocationID") or properties.get("InvocationId")
    if not isinstance(unit, str) or not unit or properties.get("Id") != unit or not invocation:
        raise ReconciliationError("systemd unit/InvocationID binding is incomplete")
    if str(properties.get("SubState", "")).lower() not in {"failed", "exited", "dead"}:
        raise ReconciliationError("systemd unit is not terminal")
    evidence_status = evidence.get("terminal_status") or evidence.get("status")
    if evidence_status is None:
        evidence_status = properties.get("SubState")
    if _status_family(evidence_status, "systemd evidence") != report_family:
        raise ReconciliationError("systemd and returned report terminal statuses differ")
    exec_start = str(properties.get("ExecStart", ""))
    if str(request_file) not in exec_start:
        raise ReconciliationError("systemd ExecStart does not contain exact request path")
    cpu_values = [evidence.get("CPUUsageNSec"), evidence.get("cpu_usage_nsec"), properties.get("CPUUsageNSec")]
    if any(value is None for value in cpu_values):
        raise ReconciliationError("systemd CPUUsageNSec evidence is incomplete")
    cpu_ns = [_nsec(value, "systemd CPUUsageNSec") for value in cpu_values]
    if len(set(cpu_ns)) != 1:
        raise ReconciliationError("systemd CPUUsageNSec copies differ")
    systemd_cpu = cpu_ns[0] / 1_000_000_000.0
    original_cpu = _number(row.get("cpu_core_seconds"), "original charge CPU")
    if systemd_cpu + 1e-12 < original_cpu:
        raise ReconciliationError("systemd CPU is below original charge CPU")
    delta_cpu = systemd_cpu - original_cpu

    ledger_file = _file(ledger_path or bind["ledger_path"], "resource ledger", max_bytes=512 * 1024 * 1024)
    if ledger_path is not None and not _same(ledger_file, bind["ledger_path"]):
        raise ReconciliationError("explicit ledger differs from request ledger")
    ledger = _load_ledger(ledger_file)
    rows = [item for item in ledger["charges"] if isinstance(item, Mapping) and item.get("id") == bind["charge_id"]]
    if len(rows) != 1:
        raise ReconciliationError(f"expected one unique original charge, found {len(rows)}")
    ledger_row = dict(rows[0])
    if ledger_row.get("reservation_id") not in {None, bind["reservation_id"]}:
        raise ReconciliationError("ledger original reservation_id differs")
    for key in ("cpu_core_seconds", "external_storage_bytes", "home_storage_bytes", "trace_bytes", "copy_hash_bytes", "new_storage_bytes"):
        if key in row and key in ledger_row:
            _cpu_match(row, ledger_row, key) if key == "cpu_core_seconds" else _integer_match(row, ledger_row, key)
    if _status_family(ledger_row.get("status"), "original ledger charge") != report_family:
        raise ReconciliationError("ledger and returned report terminal statuses differ")
    reservations = ledger.get("reservations", [])
    if any(isinstance(item, Mapping) and item.get("id") in {bind["reservation_id"], bind["charge_id"]}
           for item in reservations):
        raise ReconciliationError("original reservation remains active")

    home_root = Path(str(bind["home_path"])).expanduser().resolve()
    metadata = [_stat_metadata(report_file, "actual_returned_parent_report", root=home_root),
                _stat_metadata(evidence_file, "actual_terminal_systemd_evidence", root=home_root)]
    if len({item["path"] for item in metadata}) != len(metadata):
        raise ReconciliationError("returned report and terminal evidence must be separate files")
    metadata_bytes = sum(item["bytes"] for item in metadata)
    supplemental_id = bind["charge_id"] + "::v64-parent-terminal-reconciliation-v4"
    existing = [item for item in ledger["charges"] if isinstance(item, Mapping) and item.get("id") == supplemental_id]
    if len(existing) > 1:
        raise ReconciliationError("duplicate V64 supplemental rows already exist")
    if existing:
        existing_row = existing[0]
        if existing_row.get("parent_charge_id") != bind["charge_id"]:
            raise ReconciliationError("existing supplemental parent charge differs")
        if existing_row.get("request_sha256") != request_sha:
            raise ReconciliationError("existing supplemental request SHA differs")
        if existing_row.get("receipt_sha256") != receipt_sha:
            raise ReconciliationError("existing supplemental receipt SHA differs")
        if existing_row.get("returned_report_sha256") != report_sha:
            raise ReconciliationError("existing supplemental returned-report SHA differs")
        evidence_sha = sha256_file(evidence_file)
        if existing_row.get("terminal_evidence_sha256") != evidence_sha:
            raise ReconciliationError("existing supplemental terminal-evidence SHA differs")
        if abs(_number(existing_row.get("cpu_core_seconds"), "existing supplemental CPU") - delta_cpu) > 1e-12:
            raise ReconciliationError("existing supplemental CPU differs")
        if _integer(existing_row.get("home_storage_bytes"), "existing supplemental Home bytes") != metadata_bytes:
            raise ReconciliationError("existing supplemental metadata bytes differ")
        if _integer(existing_row.get("returned_report_bytes"), "existing returned-report bytes") != metadata[0]["bytes"]:
            raise ReconciliationError("existing returned-report byte stat differs")
        if _integer(existing_row.get("terminal_evidence_bytes"), "existing terminal-evidence bytes") != metadata[1]["bytes"]:
            raise ReconciliationError("existing terminal-evidence byte stat differs")
        existing_files = existing_row.get("metadata_files")
        if not isinstance(existing_files, list) or len(existing_files) != len(metadata):
            raise ReconciliationError("existing supplemental metadata file list differs")
        for expected, actual in zip(metadata, existing_files):
            if not isinstance(actual, Mapping):
                raise ReconciliationError("existing supplemental metadata file entry is malformed")
            for field in ("role", "path", "bytes", "sha256"):
                if actual.get(field) != expected[field]:
                    raise ReconciliationError(f"existing supplemental metadata {field} differs")
        status = "ALREADY_APPLIED_SAME_PARENT_TERMINAL_DELTA"
    else:
        status = "READY_FOR_SAME_PARENT_TERMINAL_DELTA"
    runtime_binding = request.get("runtime_binding")
    if not isinstance(runtime_binding, Mapping):
        raise ReconciliationError("runtime_binding is missing")
    runtime_path = _file(runtime_binding.get("path"), "bound runtime", max_bytes=8 * 1024 * 1024)
    runtime_sha = _sha(runtime_binding.get("sha256"), "bound runtime SHA")
    if sha256_file(runtime_path, max_bytes=8 * 1024 * 1024) != runtime_sha:
        raise ReconciliationError("bound runtime SHA differs")
    return {
        "schema": SCHEMA, "status": status,
        "request": {"path": str(request_file), "sha256": request_sha,
                     "canonical_sha256": request["sha256"], "charge_id": bind["charge_id"],
                     "reservation_id": bind["reservation_id"], "attempt_id": bind["attempt_id"]},
        "returned_parent_report": {"path": str(report_file), "sha256": report_sha,
                                    "bytes": report_file.stat().st_size,
                                    "status": report.get("status"),
                                    "charge_id": bind["charge_id"],
                                    "cpu_core_seconds": original_cpu,
                                    "external_current_bytes": external_binding["current_bytes"],
                                    "external_peak_bytes": external_binding["peak_bytes"],
                                    "external_charge_bytes": external_binding["charged_bytes"]},
        "original_home_receipt": {"path": str(receipt_file), "sha256": receipt_sha,
                                   "bytes_already_charged": int(home_bytes) if home_bytes is not None else receipt_file.stat().st_size},
        "systemd_evidence": {"path": str(evidence_file), "sha256": sha256_file(evidence_file),
                              "unit": unit, "invocation_id": invocation,
                              "exec_start": exec_start, "cpu_usage_nanoseconds": cpu_ns[0],
                              "cpu_core_seconds": systemd_cpu},
        "ledger": {"path": str(ledger_file), "original_charge_id": bind["charge_id"],
                    "original_reservation_id": bind["reservation_id"],
                    "original_cpu_core_seconds": original_cpu},
        "supplemental_charge_id": supplemental_id,
        "delta_cpu_core_seconds": delta_cpu,
        "additional_metadata_bytes": metadata_bytes,
        "additional_returned_report_bytes": metadata[0]["bytes"],
        "additional_terminal_evidence_bytes": metadata[1]["bytes"],
        "additional_metadata_files": metadata,
        "external_storage_bytes": 0, "home_storage_bytes": metadata_bytes,
        "trace_bytes": 0, "copy_hash_bytes": 0,
        "reservation_created": False, "same_parent_ledger": True,
        "original_charge_unchanged": True, "no_scientific_credit": True,
        "qualification": dict(UNKNOWN),
    }


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser()
    if target.exists():
        raise ReconciliationError(f"refusing existing reconciliation output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False)
        stream.write("\n")
    return target


def apply_binding(*, request_path: Path | str, report_path: Path | str,
                  receipt_path: Path | str, evidence_path: Path | str,
                  ledger_path: Path | str | None, output: Path | str,
                  allow_ledger_mutation: bool = False) -> dict[str, Any]:
    if not allow_ledger_mutation:
        raise ReconciliationError("ledger mutation requires explicit allow_ledger_mutation")
    target = Path(output).expanduser()
    if target.exists():
        previous, value = _json(target, "existing V64 V4 reconciliation output")
        if value.get("schema") != SCHEMA:
            raise ReconciliationError("existing output is not a V64 V4 reconciliation sidecar")
        # Re-run all source and evidence bindings; then verify the idempotent row.
        current = inspect_binding(request_path=request_path, report_path=report_path,
                                  receipt_path=receipt_path, evidence_path=evidence_path,
                                  ledger_path=ledger_path)
        if current["supplemental_charge_id"] != value.get("supplemental_charge_id"):
            raise ReconciliationError("existing sidecar supplemental ID differs")
        if current["status"] != "ALREADY_APPLIED_SAME_PARENT_TERMINAL_DELTA":
            raise ReconciliationError("existing sidecar has no matching ledger append")
        value["status"] = "ALREADY_APPLIED_SAME_PARENT_TERMINAL_DELTA"
        return value
    plan = inspect_binding(request_path=request_path, report_path=report_path,
                           receipt_path=receipt_path, evidence_path=evidence_path,
                           ledger_path=ledger_path)
    if plan["status"] == "ALREADY_APPLIED_SAME_PARENT_TERMINAL_DELTA":
        _write_new(target, plan)
        return plan
    request_file, request = _json(plan["request"]["path"], "V64 parent request")
    ledger_file = Path(plan["ledger"]["path"])
    binding = _request_binding(request)
    runtime_binding = request.get("runtime_binding")
    runtime = _load_runtime(Path(runtime_binding["path"]), _sha(runtime_binding.get("sha256"), "runtime SHA"))
    data_root = ledger_file.parent.parent
    with runtime.ledger_locked(data_root) as ledger:
        rows = [item for item in ledger.get("charges", []) if isinstance(item, Mapping) and item.get("id") == binding["charge_id"]]
        if len(rows) != 1:
            raise ReconciliationError("unique original charge changed before append")
        if abs(_number(rows[0].get("cpu_core_seconds"), "live original CPU") - plan["returned_parent_report"]["cpu_core_seconds"]) > 1e-12:
            raise ReconciliationError("live original charge CPU changed")
        existing = [item for item in ledger.get("charges", []) if isinstance(item, Mapping) and item.get("id") == plan["supplemental_charge_id"]]
        if len(existing) > 1:
            raise ReconciliationError("duplicate supplemental rows")
        if existing:
            if abs(_number(existing[0].get("cpu_core_seconds"), "existing supplemental CPU") - plan["delta_cpu_core_seconds"]) > 1e-12:
                raise ReconciliationError("existing supplemental CPU differs")
            plan["status"] = "ALREADY_APPLIED_SAME_PARENT_TERMINAL_DELTA"
        else:
            metadata = plan["additional_metadata_files"]
            ledger.setdefault("charges", []).append({
                "id": plan["supplemental_charge_id"],
                "parent_charge_id": binding["charge_id"],
                "kind": "supplemental_v64_parent_terminal_reconciliation_v4",
                "status": str(rows[0].get("status", "failed")),
                "gpu_seconds": 0.0,
                "cpu_core_seconds": float(plan["delta_cpu_core_seconds"]),
                "new_storage_bytes": int(plan["additional_metadata_bytes"]),
                "external_storage_bytes": 0,
                "home_storage_bytes": int(plan["additional_metadata_bytes"]),
                "trace_bytes": 0, "copy_hash_bytes": 0,
                "storage_filesystems": [str(Path(str(binding["home_path"])).expanduser().resolve())],
                "request_sha256": plan["request"]["sha256"],
                "receipt_sha256": plan["original_home_receipt"]["sha256"],
                "returned_report_sha256": plan["returned_parent_report"]["sha256"],
                "terminal_evidence_sha256": plan["systemd_evidence"]["sha256"],
                "returned_report_bytes": int(plan["additional_returned_report_bytes"]),
                "terminal_evidence_bytes": int(plan["additional_terminal_evidence_bytes"]),
                "reconciliation_schema": SCHEMA,
                "reservation_created": False,
                "accounting_scope": "returned report + terminal systemd evidence; original Home receipt already charged",
                "metadata_files": metadata,
            })
            plan["status"] = "APPENDED_SAME_PARENT_TERMINAL_DELTA"
            plan["ledger_append"] = {"id": plan["supplemental_charge_id"],
                                      "cpu_core_seconds": plan["delta_cpu_core_seconds"],
                                      "home_storage_bytes": plan["additional_metadata_bytes"],
                                      "returned_report_bytes": plan["additional_returned_report_bytes"],
                                      "terminal_evidence_bytes": plan["additional_terminal_evidence_bytes"],
                                      "reservation_created": False, "append_performed": True}
    _write_new(target, plan)
    return plan


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command_name in ("inspect", "apply"):
        command = sub.add_parser(command_name)
        command.add_argument("--request", type=Path, required=True)
        command.add_argument("--report", type=Path, required=True)
        command.add_argument("--receipt", type=Path, required=True)
        command.add_argument("--evidence", type=Path, required=True)
        command.add_argument("--ledger", type=Path)
        if command_name == "apply":
            command.add_argument("--output", type=Path, required=True)
            command.add_argument("--allow-ledger-mutation", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            value = inspect_binding(request_path=args.request, report_path=args.report,
                                    receipt_path=args.receipt, evidence_path=args.evidence,
                                    ledger_path=args.ledger)
        else:
            value = apply_binding(request_path=args.request, report_path=args.report,
                                  receipt_path=args.receipt, evidence_path=args.evidence,
                                  ledger_path=args.ledger, output=args.output,
                                  allow_ledger_mutation=args.allow_ledger_mutation)
    except (ReconciliationError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"V64 terminal CPU delta adapter V4: {error}", file=sys.stderr)
        return 2
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
