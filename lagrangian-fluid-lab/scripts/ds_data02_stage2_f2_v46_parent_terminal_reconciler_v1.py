#!/usr/bin/env python3
"""Reconcile the ROOT082 V46 parent terminal CPU/storage delta.

The V46 parent is a parent-executor request, so its ledger charge ID is an
explicit opaque value (``accounting.charge_id``).  It must not be rebuilt
from the ordinary family/case/attempt identity used by the generic V6
reconciler.  This forward helper joins the exact V46 request, the returned
parent report, the original Home receipt, the terminal systemd evidence, and
the exact ledger charge row before appending one same-ledger supplemental
charge.

The original charge's CPU is taken from ``actual-returned-parent-report``
(``charge.charge.cpu_core_seconds``), never from the earlier Home receipt's
``execution.entry_cpu``.  The systemd CPU delta and two metadata files that
were written after the original charge (the returned report and terminal
evidence) are appended once.  The old Home receipt remains covered by the
original charge's Home bytes.  No reservation is created, no original JSON is
rewritten, and scientific qualification remains UNKNOWN.

Only bounded JSON and the resource ledger are read.  This module never reads
H5, BI4, raw frames, typed arrays, labels, or solver products.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


SCHEMA = "ds02.stage2.f2-v46-parent-terminal-reconciliation.v1"
REQUEST_SCHEMA = "ds02.stage2.f2-portable-executor-parent-request.v3"
REPORT_SCHEMA = "ds02.stage2.f2-portable-executor-parent-report.v3"
EVIDENCE_SCHEMA = "ds02.stage2.systemd-cpu-evidence.v1"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
TERMINAL_STATUS_PREFIXES = ("completed", "failed", "cancel", "timeout")
HEX64 = set("0123456789abcdef")


class ReconciliationError(RuntimeError):
    pass


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _require_file(path: Path | str, role: str, *, max_bytes: int = 64 * 1024 * 1024) -> Path:
    target = Path(path).expanduser()
    if target.is_symlink() or not target.is_file():
        raise ReconciliationError(f"{role} is not a regular non-symlink file: {target}")
    if target.stat().st_size > max_bytes:
        raise ReconciliationError(f"{role} exceeds metadata size bound: {target}")
    return target


def _load_json(path: Path | str, role: str, *, max_bytes: int = 64 * 1024 * 1024) -> tuple[Path, dict[str, Any]]:
    target = _require_file(path, role, max_bytes=max_bytes)
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ReconciliationError(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise ReconciliationError(f"{role} must be a JSON object")
    return target, value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser()
    if target.exists():
        raise ReconciliationError(f"refusing existing reconciliation output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True,
                  allow_nan=False)
        stream.write("\n")
    return target


def _sha(value: Any, role: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in HEX64 for char in value):
        raise ReconciliationError(f"{role} must be a lowercase SHA-256")
    return value


def _number(value: Any, role: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ReconciliationError(f"{role} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        raise ReconciliationError(f"{role} must be finite and >= {minimum}")
    return result


def _integer(value: Any, role: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ReconciliationError(f"{role} must be an integer >= {minimum}")
    return value


def _nanoseconds(value: Any, role: str) -> int:
    # ``systemctl show`` serializes CPUUsageNSec as text while the evidence
    # sidecar may preserve it as an integer.  Accept only an unsigned decimal
    # representation; never truncate a float or arbitrary numeric string.
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    return _integer(value, role)


def _terminal(value: Any, role: str) -> None:
    if not isinstance(value, str):
        raise ReconciliationError(f"{role} status is missing")
    status = value.strip().lower()
    if not any(status.startswith(prefix) for prefix in TERMINAL_STATUS_PREFIXES):
        raise ReconciliationError(f"{role} is not terminal: {value!r}")


def _canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        default=str).encode("utf-8")).hexdigest()


def _same_path(left: Path | str, right: Path | str) -> bool:
    return Path(left).expanduser().resolve() == Path(right).expanduser().resolve()


def _stat_source(path: Path, role: str, expected_sha: str | None = None) -> dict[str, Any]:
    observed_sha = sha256_file(path)
    if expected_sha is not None and observed_sha != expected_sha:
        raise ReconciliationError(f"{role} SHA differs from its bound evidence")
    return {"role": role, "path": str(path), "bytes": int(path.stat().st_size),
            "sha256": observed_sha}


def _load_runtime(path: Path, expected_sha: str) -> Any:
    if sha256_file(path) != expected_sha:
        raise ReconciliationError("bound runtime SHA differs before ledger mutation")
    module_name = "ds02_bound_f2_v46_parent_terminal_runtime_v1"
    parent = str(path.parent)
    inserted = parent not in sys.path
    if inserted:
        sys.path.insert(0, parent)
    try:
        module_spec = importlib.util.spec_from_file_location(module_name, path)
        if module_spec is None or module_spec.loader is None:
            raise ReconciliationError(f"cannot load bound runtime: {path}")
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
        if not callable(getattr(module, "ledger_locked", None)):
            raise ReconciliationError("bound runtime has no ledger_locked API")
        return module
    finally:
        if inserted:
            sys.path.remove(parent)


def _charge_row(report: Mapping[str, Any]) -> dict[str, Any]:
    outer = report.get("charge")
    if not isinstance(outer, Mapping) or outer.get("status") != "PARENT_CHARGE_APPLIED":
        raise ReconciliationError("returned parent report has no applied parent charge")
    row = outer.get("charge")
    if not isinstance(row, Mapping):
        raise ReconciliationError("returned parent report charge payload is missing")
    return dict(row)


def _charge_numeric_match(left: Mapping[str, Any], right: Mapping[str, Any], key: str) -> None:
    if abs(_number(left.get(key), f"charge.{key}") - _number(right.get(key), f"ledger.{key}")) > 1e-12:
        raise ReconciliationError(f"returned report and ledger charge differ: {key}")


def inspect_binding(*, request_path: Path | str, report_path: Path | str,
                    receipt_path: Path | str, evidence_path: Path | str,
                    ledger_path: Path | str | None = None) -> dict[str, Any]:
    request_file, request = _load_json(request_path, "V46 parent request")
    report_file, report = _load_json(report_path, "returned parent report")
    receipt_file, receipt = _load_json(receipt_path, "original Home receipt")
    evidence_file, evidence = _load_json(evidence_path, "terminal systemd evidence", max_bytes=8 * 1024 * 1024)

    if request.get("schema") != REQUEST_SCHEMA or request.get("sha256") != _canonical_sha(request):
        raise ReconciliationError("V46 parent request schema/canonical SHA differs")
    request_sha = sha256_file(request_file)
    accounting = request.get("accounting")
    resource = request.get("parent_resource_binding")
    runtime_binding = request.get("runtime_binding")
    if not isinstance(accounting, Mapping) or not isinstance(resource, Mapping):
        raise ReconciliationError("V46 parent accounting binding is missing")
    if not isinstance(runtime_binding, Mapping):
        raise ReconciliationError("V46 runtime binding is missing")
    charge_id = accounting.get("charge_id")
    if not isinstance(charge_id, str) or not charge_id:
        raise ReconciliationError("V46 accounting charge_id is missing")
    if charge_id != resource.get("charge_id"):
        raise ReconciliationError("V46 accounting and parent charge IDs differ")
    if charge_id == "/".join(str(request.get(key, "")) for key in ("family_id", "case_id", "attempt_id")):
        raise ReconciliationError("V46 charge ID must remain the explicit opaque ledger ID")
    if accounting.get("same_parent_ledger") is not True or resource.get("same_parent_ledger") is not True:
        raise ReconciliationError("V46 request is not same-parent-ledger scoped")

    if report.get("schema") != REPORT_SCHEMA:
        raise ReconciliationError("returned report schema differs")
    _terminal(report.get("status"), "returned parent report")
    if report.get("request_sha256") != request_sha:
        raise ReconciliationError("returned report request SHA differs from the V46 request")
    if report.get("report_path") and not _same_path(report["report_path"], receipt_file):
        raise ReconciliationError("returned report report_path differs from the Home receipt")
    report_row = _charge_row(report)
    if report_row.get("id") != charge_id:
        raise ReconciliationError("returned report charge ID differs from V46 accounting charge ID")
    if report_row.get("parent_attempt_id") != resource.get("attempt_id"):
        raise ReconciliationError("returned report parent attempt differs from V46 resource binding")
    if report.get("ledger_mutated") is not True:
        raise ReconciliationError("returned report does not attest the original ledger mutation")
    for key in ("external_bytes", "home_bytes", "trace_bytes", "copy_hash_bytes"):
        report_value = report.get(key)
        charge_value = report_row.get({"external_bytes": "external_storage_bytes",
                                       "home_bytes": "home_storage_bytes",
                                       "trace_bytes": "trace_bytes",
                                       "copy_hash_bytes": "copy_hash_bytes"}[key])
        if _integer(report_value, f"returned report {key}") != _integer(charge_value, f"returned charge {key}"):
            raise ReconciliationError(f"returned report and charge differ: {key}")

    if receipt.get("schema") is None:
        raise ReconciliationError("original Home receipt schema is missing")
    receipt_request = receipt.get("request")
    if not isinstance(receipt_request, Mapping):
        raise ReconciliationError("original Home receipt request binding is missing")
    if not _same_path(receipt_request.get("path", ""), request_file) or receipt_request.get("sha256") != request_sha:
        raise ReconciliationError("original Home receipt is not bound to the V46 request")
    receipt_accounting = receipt.get("accounting")
    if not isinstance(receipt_accounting, Mapping) or receipt_accounting.get("charge_id") != charge_id:
        raise ReconciliationError("original Home receipt charge ID differs")
    receipt_home_bytes = _integer(receipt.get("filesystem", {}).get("home_receipt_bytes"),
                                  "original receipt home bytes")
    if receipt_home_bytes != int(receipt_file.stat().st_size):
        raise ReconciliationError("original Home receipt byte stat differs")
    if _integer(report_row.get("home_storage_bytes"), "original charge Home bytes") != receipt_home_bytes:
        raise ReconciliationError("original charge does not cover the Home receipt bytes")
    # This is deliberately recorded but never used as the parent CPU basis.
    entry_cpu = receipt.get("execution", {}).get("entry_cpu_core_seconds")
    if entry_cpu is not None:
        _number(entry_cpu, "Home receipt entry CPU")

    if evidence.get("schema") != EVIDENCE_SCHEMA or evidence.get("terminal") is not True:
        raise ReconciliationError("terminal systemd evidence is not a terminal v1 record")
    if not _same_path(evidence.get("request", ""), request_file) or evidence.get("request_sha256") != request_sha:
        raise ReconciliationError("systemd evidence request binding differs")
    receipt_sha = sha256_file(receipt_file)
    if not _same_path(evidence.get("receipt", ""), receipt_file) or evidence.get("receipt_sha256") != receipt_sha:
        raise ReconciliationError("systemd evidence receipt binding differs")
    report_sha = sha256_file(report_file)
    if not _same_path(evidence.get("actual_returned_report", ""), report_file):
        raise ReconciliationError("systemd evidence returned-report path differs")
    if evidence.get("actual_returned_report_sha256") != report_sha:
        raise ReconciliationError("systemd evidence returned-report SHA differs")
    if evidence.get("charge_id") != charge_id:
        raise ReconciliationError("systemd evidence charge ID differs")
    properties = evidence.get("systemd_properties")
    if not isinstance(properties, Mapping):
        raise ReconciliationError("systemd property snapshot is missing")
    if properties.get("Id") != evidence.get("unit") or not properties.get("InvocationID"):
        raise ReconciliationError("systemd unit invocation binding is incomplete")
    if str(properties.get("SubState", "")).lower() not in {"failed", "exited", "dead"}:
        raise ReconciliationError("systemd unit is not terminal")
    exec_start = str(properties.get("ExecStart", ""))
    if str(request_file) not in exec_start:
        raise ReconciliationError("systemd ExecStart does not contain the V46 request path")
    cpu_fields = [evidence.get("CPUUsageNSec"), evidence.get("cpu_usage_nsec"), properties.get("CPUUsageNSec")]
    if any(value is None for value in cpu_fields):
        raise ReconciliationError("systemd CPU evidence is incomplete")
    cpu_ns = [_nanoseconds(value, "systemd CPU nanoseconds") for value in cpu_fields]
    if len(set(cpu_ns)) != 1:
        raise ReconciliationError("systemd CPU nanosecond copies differ")
    systemd_cpu = cpu_ns[0] / 1_000_000_000.0
    original_cpu = _number(report_row.get("cpu_core_seconds"), "returned parent charge CPU")
    if systemd_cpu + 1e-12 < original_cpu:
        raise ReconciliationError("systemd terminal CPU is below the returned parent charge CPU")
    delta_cpu = systemd_cpu - original_cpu

    ledger_file = _require_file(ledger_path or resource.get("ledger_path"), "resource ledger", max_bytes=512 * 1024 * 1024)
    if ledger_path is not None and not _same_path(ledger_file, resource.get("ledger_path", "")):
        raise ReconciliationError("explicit ledger differs from V46 request ledger")
    _, ledger = _load_json(ledger_file, "resource ledger", max_bytes=512 * 1024 * 1024)
    ledger_rows = [row for row in ledger.get("charges", [])
                   if isinstance(row, Mapping) and row.get("id") == charge_id]
    if len(ledger_rows) != 1:
        raise ReconciliationError(f"expected one exact V46 charge row, found {len(ledger_rows)}")
    ledger_row = dict(ledger_rows[0])
    for key in ("cpu_core_seconds", "external_storage_bytes", "home_storage_bytes",
                "trace_bytes", "copy_hash_bytes", "new_storage_bytes"):
        report_key = {"external_storage_bytes": "external_storage_bytes",
                      "home_storage_bytes": "home_storage_bytes",
                      "trace_bytes": "trace_bytes", "copy_hash_bytes": "copy_hash_bytes",
                      "new_storage_bytes": "new_storage_bytes"}.get(key, key)
        _charge_numeric_match(report_row, ledger_row, key)
    if ledger_row.get("status") not in {"failed", "completed", "cancelled", "canceled", "timeout"}:
        raise ReconciliationError("original V46 ledger charge is not terminal")
    if any(isinstance(row, Mapping) and row.get("id") == charge_id
           for row in ledger.get("reservations", [])):
        raise ReconciliationError("original V46 charge still has a reservation")

    # The old receipt is already in the original charge.  The returned report
    # and terminal systemd evidence were written later and are the only new
    # Home-side metadata bytes in this supplemental scope.
    home_root = Path(str(resource.get("home_path", "/home/jade"))).expanduser().resolve()
    extra_files = []
    for role, file in (("actual_returned_parent_report", report_file),
                       ("actual_terminal_systemd_evidence", evidence_file)):
        try:
            file.resolve().relative_to(home_root)
        except ValueError as error:
            raise ReconciliationError(f"{role} is outside the bound Home path") from error
        extra_files.append(_stat_source(file, role))
    if len({item["path"] for item in extra_files}) != len(extra_files):
        raise ReconciliationError("metadata input files overlap")
    extra_home_bytes = sum(int(item["bytes"]) for item in extra_files)
    supplemental_id = charge_id + "::v46-parent-terminal-reconciliation-v1"
    existing = [row for row in ledger.get("charges", [])
                if isinstance(row, Mapping) and row.get("id") == supplemental_id]
    if len(existing) > 1:
        raise ReconciliationError("duplicate V46 terminal reconciliation rows already exist")
    if existing:
        row = existing[0]
        if abs(_number(row.get("cpu_core_seconds"), "existing supplemental CPU") - delta_cpu) > 1e-12:
            raise ReconciliationError("existing V46 supplemental CPU differs")
        if _integer(row.get("home_storage_bytes"), "existing supplemental Home bytes") != extra_home_bytes:
            raise ReconciliationError("existing V46 supplemental Home bytes differ")
        status = "ALREADY_APPLIED_SAME_PARENT_TERMINAL_DELTA"
    else:
        status = "READY_FOR_SAME_PARENT_TERMINAL_DELTA"
    runtime_path = _require_file(runtime_binding.get("path"), "V46 shared runtime", max_bytes=8 * 1024 * 1024)
    runtime_sha = _sha(runtime_binding.get("sha256"), "V46 runtime SHA")
    if sha256_file(runtime_path) != runtime_sha:
        raise ReconciliationError("V46 shared runtime SHA differs")
    return {
        "schema": SCHEMA,
        "status": status,
        "request": {"path": str(request_file), "sha256": request_sha,
                     "canonical_sha256": request["sha256"], "charge_id": charge_id,
                     "attempt_id": resource.get("attempt_id")},
        "returned_parent_report": {"path": str(report_file), "sha256": report_sha,
                                    "status": report.get("status"),
                                    "charge_id": charge_id, "cpu_core_seconds": original_cpu},
        "original_home_receipt": {"path": str(receipt_file), "sha256": receipt_sha,
                                   "bytes_already_charged": receipt_home_bytes,
                                   "entry_cpu_core_seconds_ignored": entry_cpu},
        "systemd_evidence": {"path": str(evidence_file), "sha256": sha256_file(evidence_file),
                              "unit": evidence.get("unit"), "invocation_id": properties["InvocationID"],
                              "cpu_usage_nanoseconds": cpu_ns[0], "cpu_core_seconds": systemd_cpu},
        "ledger": {"path": str(ledger_file), "original_charge_id": charge_id,
                    "original_cpu_core_seconds": original_cpu,
                    "original_storage_bytes": int(report_row["new_storage_bytes"])},
        "supplemental_charge_id": supplemental_id,
        "delta_cpu_core_seconds": delta_cpu,
        "additional_home_metadata_bytes": extra_home_bytes,
        "additional_metadata_files": extra_files,
        "external_storage_bytes": 0,
        "trace_bytes": 0,
        "copy_hash_bytes": 0,
        "reservation_created": False,
        "same_parent_ledger": True,
        "original_charge_unchanged": True,
        "qualification": dict(UNKNOWN),
    }


def reconcile(*, request_path: Path | str, report_path: Path | str,
              receipt_path: Path | str, evidence_path: Path | str,
              ledger_path: Path | str | None, output: Path | str) -> dict[str, Any]:
    target = Path(output).expanduser()
    if target.exists():
        previous = _load_json(target, "existing reconciliation report")[1]
        if previous.get("schema") != SCHEMA:
            raise ReconciliationError("existing output is not a V46 reconciliation report")
        ledger_file = _require_file(ledger_path or previous.get("ledger", {}).get("path"),
                                    "resource ledger", max_bytes=512 * 1024 * 1024)
        _, ledger = _load_json(ledger_file, "resource ledger", max_bytes=512 * 1024 * 1024)
        sid = previous.get("supplemental_charge_id")
        rows = [row for row in ledger.get("charges", [])
                if isinstance(row, Mapping) and row.get("id") == sid]
        if len(rows) != 1:
            raise ReconciliationError("existing sidecar has no unique matching ledger append")
        row = rows[0]
        if abs(_number(row.get("cpu_core_seconds"), "existing supplemental CPU")
               - _number(previous.get("delta_cpu_core_seconds"), "sidecar delta CPU")) > 1e-12:
            raise ReconciliationError("existing sidecar CPU differs from ledger append")
        if _integer(row.get("home_storage_bytes"), "existing supplemental Home bytes") != _integer(
                previous.get("additional_home_metadata_bytes"), "sidecar Home bytes"):
            raise ReconciliationError("existing sidecar Home bytes differ from ledger append")
        previous["status"] = "ALREADY_APPLIED_SAME_PARENT_TERMINAL_DELTA"
        return previous

    report = inspect_binding(request_path=request_path, report_path=report_path,
                             receipt_path=receipt_path, evidence_path=evidence_path,
                             ledger_path=ledger_path)
    if report["status"] == "ALREADY_APPLIED_SAME_PARENT_TERMINAL_DELTA":
        _write_new(target, report)
        return report

    ledger_file = Path(report["ledger"]["path"])
    request_file = Path(report["request"]["path"])
    runtime_binding = _load_json(request_file, "V46 request")[1]["runtime_binding"]
    runtime_path = _require_file(runtime_binding["path"], "V46 shared runtime", max_bytes=8 * 1024 * 1024)
    runtime = _load_runtime(runtime_path, _sha(runtime_binding.get("sha256"), "V46 runtime SHA"))
    data_root = ledger_file.parent.parent
    with runtime.ledger_locked(data_root) as ledger:
        rows = [row for row in ledger.get("charges", [])
                if isinstance(row, Mapping) and row.get("id") == report["ledger"]["original_charge_id"]]
        if len(rows) != 1:
            raise ReconciliationError("exact V46 original charge disappeared before append")
        original = rows[0]
        if abs(_number(original.get("cpu_core_seconds"), "live original CPU")
               - _number(report["ledger"]["original_cpu_core_seconds"], "preflight original CPU")) > 1e-12:
            raise ReconciliationError("live V46 original CPU changed after preflight")
        sid = report["supplemental_charge_id"]
        existing = [row for row in ledger.get("charges", [])
                    if isinstance(row, Mapping) and row.get("id") == sid]
        if existing:
            if len(existing) != 1:
                raise ReconciliationError("duplicate V46 supplemental charge rows")
            if abs(_number(existing[0].get("cpu_core_seconds"), "live supplemental CPU")
                   - _number(report["delta_cpu_core_seconds"], "supplemental CPU")) > 1e-12:
                raise ReconciliationError("live V46 supplemental CPU differs")
            report["status"] = "ALREADY_APPLIED_SAME_PARENT_TERMINAL_DELTA"
        else:
            home_bytes = _integer(report["additional_home_metadata_bytes"], "additional Home metadata bytes")
            ledger.setdefault("charges", []).append({
                "id": sid,
                "parent_charge_id": report["ledger"]["original_charge_id"],
                "kind": "supplemental_v46_parent_terminal_reconciliation",
                "status": str(original.get("status", "failed")),
                "gpu_seconds": 0.0,
                "cpu_core_seconds": float(report["delta_cpu_core_seconds"]),
                "new_storage_bytes": home_bytes,
                "external_storage_bytes": 0,
                "home_storage_bytes": home_bytes,
                "trace_bytes": 0,
                "copy_hash_bytes": 0,
                "storage_filesystems": [str(Path(str(_load_json(request_file, "V46 request")[1]["parent_resource_binding"].get("home_path", "/home/jade"))).expanduser().resolve())],
                "finished_at_utc": original.get("finished_at_utc", "evidence-bound"),
                "request_sha256": report["request"]["sha256"],
                "receipt_sha256": report["original_home_receipt"]["sha256"],
                "returned_report_sha256": report["returned_parent_report"]["sha256"],
                "systemd_evidence_sha256": report["systemd_evidence"]["sha256"],
                "reconciliation_schema": SCHEMA,
                "reservation_created": False,
                "accounting_scope": "returned parent report + terminal systemd evidence; original Home receipt already charged",
            })
            report["status"] = "APPENDED_SAME_PARENT_TERMINAL_DELTA"
            report["ledger_append"] = {"id": sid, "cpu_core_seconds": report["delta_cpu_core_seconds"],
                                        "home_storage_bytes": home_bytes, "external_storage_bytes": 0,
                                        "reservation_created": False, "append_performed": True}
    _write_new(target, report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("inspect", "reconcile"):
        command = sub.add_parser(name)
        command.add_argument("--request", type=Path, required=True)
        command.add_argument("--report", type=Path, required=True)
        command.add_argument("--receipt", type=Path, required=True)
        command.add_argument("--evidence", type=Path, required=True)
        command.add_argument("--ledger", type=Path)
        if name == "reconcile":
            command.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            value = inspect_binding(request_path=args.request, report_path=args.report,
                                    receipt_path=args.receipt, evidence_path=args.evidence,
                                    ledger_path=args.ledger)
        else:
            value = reconcile(request_path=args.request, report_path=args.report,
                              receipt_path=args.receipt, evidence_path=args.evidence,
                              ledger_path=args.ledger, output=args.output)
    except (ReconciliationError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"V46 parent terminal reconciler: {error}", file=sys.stderr)
        return 2
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
