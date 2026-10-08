#!/usr/bin/env python3
"""Reconcile an omitted terminal CPU delta in the shared Stage2 ledger.

This is the generic forward helper for ordinary ``ds02.request.v1`` and
``ds02.runner-request.v1`` CPU requests and the V5 external-solver
request/report pair.  It deliberately
does not require the typed-only V2 request fields (``accounting``,
``static_bindings`` or ``shared_runtime_v6``).  The request, execution
receipt, saved systemd CPU evidence, and existing ledger charge are joined by
their immutable family/case/attempt identity.  The evidence also binds the
request and receipt file SHA, the unit, CPU-nanosecond field, and terminal
systemd state.  This prevents a numerically plausible CPU value from being
attached to the wrong attempt.

Only a small JSON/code closure is read.  No H5, BI4, raw frame, or result
payload is opened.  A successful reconciliation appends one supplemental
CPU-only charge under the existing ledger lock; it does not create a
reservation, alter the original charge, or reset a quota.  Scientific
qualification remains UNKNOWN.
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
import sys
from typing import Any, Mapping, Sequence


SCHEMA = "ds02.stage2.terminal-cpu-delta-reconciliation-v6"
EVIDENCE_SCHEMA = "ds02.stage2.systemd-cpu-evidence.v1"
REQUEST_SCHEMAS = {"ds02.request.v1", "ds02.runner-request.v1", "ds02.stage2.external-solver-request.v5"}
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
TERMINAL_STATUSES = {"completed", "failed", "cancelled", "canceled", "timeout"}
RUNTIME_BASENAMES = (
    "ds_data02_runtime_v8.py",
    "ds_data02_runtime_v6.py",
    "ds_data02_runtime_v2.py",
)


class ReconciliationError(RuntimeError):
    pass


def sha256_file(path: Path | str) -> str:
    target = Path(path).expanduser()
    digest = hashlib.sha256()
    with target.open("rb") as stream:
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


def load_json(path: Path | str, role: str, *, max_bytes: int = 64 * 1024 * 1024) -> tuple[Path, dict[str, Any]]:
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
        raise ReconciliationError(f"refusing existing report: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True,
                  allow_nan=False)
        stream.write("\n")
    return target


def _finite(value: Any, role: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError as error:
            raise ReconciliationError(f"{role} must be numeric") from error
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ReconciliationError(f"{role} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        raise ReconciliationError(f"{role} must be finite and >= {minimum}")
    return result


def _identity(request: Mapping[str, Any], role: str = "request") -> dict[str, str]:
    values: dict[str, str] = {}
    for key in ("family_id", "case_id", "attempt_id"):
        value = request.get(key)
        if not isinstance(value, str) or not value:
            raise ReconciliationError(f"{role}.{key} is missing")
        values[key] = value
    values["charge_id"] = "/".join(values[key] for key in ("family_id", "case_id", "attempt_id"))
    return values


def _status_is_terminal(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    status = value.strip().lower()
    return (status in TERMINAL_STATUSES
            or any(status.startswith(prefix) for prefix in ("completed", "failed", "cancel", "timeout")))


def _runtime_binding(request_path: Path, request: Mapping[str, Any]) -> dict[str, Any]:
    direct = request.get("runtime_binding")
    if isinstance(direct, Mapping) and isinstance(direct.get("path"), str):
        path = _require_file(direct["path"], "bound runtime source", max_bytes=8 * 1024 * 1024)
        declared = direct.get("sha256")
        if not isinstance(declared, str) or len(declared) != 64:
            raise ReconciliationError("direct runtime binding SHA is malformed")
        observed = sha256_file(path)
        if observed != declared:
            raise ReconciliationError("direct runtime source SHA differs from request")
        return {"path": str(path), "basename": path.name, "sha256": observed,
                "role": direct.get("role"), "request_path": str(request_path)}
    values = request.get("input_hashes")
    if not isinstance(values, Mapping):
        values = request.get("input_sha256")
    if not isinstance(values, Mapping):
        raise ReconciliationError("request has no input hash map for runtime binding")
    selected: tuple[Path, str] | None = None
    for basename in RUNTIME_BASENAMES:
        for raw_path, declared in values.items():
            if Path(str(raw_path)).name != basename:
                continue
            if not isinstance(declared, str) or len(declared) != 64:
                raise ReconciliationError(f"runtime hash is malformed: {raw_path}")
            selected = (Path(str(raw_path)).expanduser(), declared)
            break
        if selected is not None:
            break
    if selected is None:
        raise ReconciliationError("request does not bind runtime v8, v6, or v2")
    path, declared_sha = selected
    path = _require_file(path, "bound runtime source", max_bytes=8 * 1024 * 1024)
    observed_sha = sha256_file(path)
    if observed_sha != declared_sha:
        raise ReconciliationError("bound runtime source SHA differs from request")
    return {"path": str(path), "basename": path.name, "sha256": observed_sha,
            "request_path": str(request_path)}


def _load_runtime(binding: Mapping[str, Any]) -> Any:
    path = Path(str(binding["path"]))
    module_name = "ds02_bound_terminal_delta_runtime_v6"
    parent = str(path.parent)
    inserted = parent not in sys.path
    if inserted:
        sys.path.insert(0, parent)
    try:
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ReconciliationError(f"cannot load bound runtime: {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if not callable(getattr(module, "ledger_locked", None)):
            raise ReconciliationError("bound runtime has no ledger_locked API")
        return module
    finally:
        if inserted:
            sys.path.remove(parent)


def _evidence_cpu_seconds(evidence: Mapping[str, Any]) -> tuple[float, int, str]:
    if evidence.get("schema") not in {EVIDENCE_SCHEMA, "ds02.stage2.systemd-cpu-evidence.v1"}:
        raise ReconciliationError("unsupported systemd CPU evidence schema")
    if evidence.get("terminal") is not True:
        raise ReconciliationError("systemd CPU evidence is not marked terminal")
    explicit_unit = evidence.get("cpu_unit", evidence.get("unit_cpu"))
    if explicit_unit is not None and str(explicit_unit).lower() not in {
        "ns", "nanosecond", "nanoseconds", "nanoseconds_cpu_time",
    }:
        raise ReconciliationError("systemd CPU evidence unit is not nanoseconds")
    raw_values = [(key, evidence[key]) for key in
                  ("cpu_usage_nanoseconds", "CPUUsageNSec", "cpu_usage_nsec", "cpu_usage_ns")
                  if key in evidence]
    if not raw_values:
        raise ReconciliationError("systemd CPU evidence has no nanosecond field")
    raw = raw_values[0][1]
    ns = _finite(raw, "systemd CPU nanoseconds", minimum=0.0)
    for key, duplicate in raw_values[1:]:
        if abs(_finite(duplicate, f"systemd CPU nanoseconds ({key})") - ns) > 0:
            raise ReconciliationError("duplicate systemd CPU nanosecond fields differ")
    if abs(ns - round(ns)) > 0:
        raise ReconciliationError("systemd CPU nanoseconds must be an integer")
    integer_ns = int(ns)
    return integer_ns / 1_000_000_000.0, integer_ns, "nanoseconds"


def _find_charge(ledger: Mapping[str, Any], charge_id: str) -> dict[str, Any]:
    rows = [row for row in ledger.get("charges", [])
            if isinstance(row, Mapping) and row.get("id") == charge_id]
    if len(rows) != 1:
        raise ReconciliationError(f"expected exactly one terminal charge for {charge_id}, found {len(rows)}")
    row = dict(rows[0])
    if not _status_is_terminal(row.get("status")):
        raise ReconciliationError(f"parent charge is not terminal: {charge_id}")
    return row


def _find_request_runtime(request_path: Path, request: Mapping[str, Any]) -> dict[str, Any]:
    return _runtime_binding(request_path, request)


def inspect_binding(*, request_path: Path | str, receipt_path: Path | str,
                    evidence_path: Path | str, ledger_path: Path | str) -> dict[str, Any]:
    request_file, request = load_json(request_path, "request")
    receipt_file, receipt = load_json(receipt_path, "execution receipt")
    evidence_file, evidence = load_json(evidence_path, "systemd CPU evidence", max_bytes=4 * 1024 * 1024)
    ledger_file, ledger = load_json(ledger_path, "resource ledger", max_bytes=512 * 1024 * 1024)
    if request.get("schema") not in REQUEST_SCHEMAS:
        raise ReconciliationError("request schema is not a supported ds02 request")
    identity = _identity(request)
    receipt_request = receipt.get("request")
    if not isinstance(receipt_request, Mapping):
        raise ReconciliationError("execution receipt has no embedded request")
    request_sha = sha256_file(request_file)
    # Ordinary runtime receipts embed the full request and carry a top-level
    # request_sha256.  External-solver V5 receipts embed the request path and
    # SHA under ``request`` and expose CPU under ``execution``.
    if all(isinstance(receipt_request.get(key), str) for key in ("family_id", "case_id", "attempt_id")):
        if _identity(receipt_request, "receipt.request") != identity:
            raise ReconciliationError("receipt identity differs from request identity")
    elif isinstance(receipt_request.get("path"), str):
        if Path(str(receipt_request["path"])).expanduser().resolve() != request_file.resolve():
            raise ReconciliationError("external receipt request path differs from bound request")
        if receipt_request.get("sha256") != request_sha:
            raise ReconciliationError("external receipt nested request SHA differs from bound request")
    else:
        raise ReconciliationError("receipt request has neither identity nor path/SHA binding")
    top_request_sha = receipt.get("request_sha256")
    if top_request_sha is not None and top_request_sha != request_sha:
        raise ReconciliationError("execution receipt request SHA differs from the bound request")
    if top_request_sha is None and not (
        isinstance(receipt_request.get("sha256"), str) and receipt_request.get("sha256") == request_sha
    ):
        raise ReconciliationError("execution receipt has no request file SHA binding")
    if not _status_is_terminal(receipt.get("status")):
        raise ReconciliationError("execution receipt is not terminal")
    execution = receipt.get("execution")
    receipt_cpu_value = execution.get("cpu_core_seconds") if isinstance(execution, Mapping) else receipt.get("cpu_core_seconds")
    receipt_cpu = _finite(receipt_cpu_value, "receipt CPU seconds")
    evidence_cpu, evidence_ns, evidence_unit = _evidence_cpu_seconds(evidence)
    if not isinstance(evidence.get("request"), str) or Path(str(evidence["request"])).expanduser().resolve() != request_file.resolve():
        raise ReconciliationError("systemd evidence request path differs from bound request")
    if evidence.get("request_sha256") != request_sha:
        raise ReconciliationError("systemd evidence request SHA differs from bound request")
    if not isinstance(evidence.get("receipt"), str) or Path(str(evidence["receipt"])).expanduser().resolve() != receipt_file.resolve():
        raise ReconciliationError("systemd evidence receipt path differs from bound receipt")
    receipt_sha = sha256_file(receipt_file)
    if evidence.get("receipt_sha256") != receipt_sha:
        raise ReconciliationError("systemd evidence receipt SHA differs from bound receipt")
    if evidence.get("identity") != {key: identity[key] for key in ("family_id", "case_id", "attempt_id")}: 
        raise ReconciliationError("systemd evidence identity differs from request identity")
    if evidence.get("charge_id") != identity["charge_id"]:
        raise ReconciliationError("systemd evidence charge ID differs from request identity")
    if not isinstance(evidence.get("unit"), str) or not evidence["unit"]:
        raise ReconciliationError("systemd evidence unit is missing")
    properties = evidence.get("systemd_properties")
    if not isinstance(properties, Mapping) or properties.get("Id") != evidence["unit"]:
        raise ReconciliationError("systemd evidence unit is not linked to terminal systemd properties")
    if str(properties.get("SubState", "")).lower() not in {"exited", "failed", "dead"}:
        raise ReconciliationError("systemd evidence systemd unit is not terminal")
    # Unit names are reusable.  Join this evidence to the exact invocation via
    # systemd's InvocationID and flattened ExecStart, and compare both copies
    # of CPUUsageNSec instead of trusting the top-level evidence field alone.
    invocation_id = properties.get("InvocationID")
    if not isinstance(invocation_id, str) or not invocation_id.strip():
        raise ReconciliationError("systemd evidence InvocationID is missing")
    exec_start = properties.get("ExecStart")
    if not isinstance(exec_start, str) or not exec_start.strip():
        raise ReconciliationError("systemd evidence ExecStart is missing")
    request_paths = {str(request_file), str(request_file.resolve())}
    if not any(path in exec_start for path in request_paths):
        raise ReconciliationError("systemd ExecStart is not bound to the actual request path")
    property_ns = properties.get("CPUUsageNSec")
    if property_ns is None:
        raise ReconciliationError("systemd properties CPUUsageNSec is missing")
    property_ns_value = _finite(property_ns, "systemd properties CPUUsageNSec", minimum=0.0)
    if abs(property_ns_value - round(property_ns_value)) > 0:
        raise ReconciliationError("systemd properties CPUUsageNSec must be an integer")
    if int(property_ns_value) != evidence_ns:
        raise ReconciliationError("systemd properties CPUUsageNSec differs from evidence CPUUsageNSec")
    charge = _find_charge(ledger, identity["charge_id"])
    charge_cpu = _finite(charge.get("cpu_core_seconds"), "parent charge CPU seconds")
    if abs(charge_cpu - receipt_cpu) > 1e-9:
        raise ReconciliationError("receipt CPU differs from the consumed parent charge")
    if evidence_cpu + 1e-12 < charge_cpu:
        raise ReconciliationError("systemd CPU evidence is below the consumed charge")
    delta = max(0.0, evidence_cpu - charge_cpu)
    supplemental_id = identity["charge_id"] + "::terminal-cpu-delta-v6"
    # A parent may receive one terminal CPU reconciliation across all forward
    # helper versions.  Permit the exact V6 row for idempotence, but reject a
    # closed V3/V4/V5 (or other same-family) row before any new append.
    for row in ledger.get("charges", []):
        if not isinstance(row, Mapping) or row.get("parent_charge_id") != identity["charge_id"]:
            continue
        row_id = str(row.get("id", ""))
        schema = str(row.get("reconciliation_schema", ""))
        is_reconciliation = (
            row.get("kind") == "supplemental_terminal_cpu_delta"
            or schema.startswith("ds02.stage2.terminal-cpu-delta-reconciliation-")
            or "::terminal-cpu-delta-" in row_id
        )
        if not is_reconciliation:
            continue
        if row_id == supplemental_id:
            if abs(_finite(row.get("cpu_core_seconds"), "existing supplemental CPU") - delta) > 1e-9:
                raise ReconciliationError("existing V6 supplemental charge has a different CPU delta")
            continue
        raise ReconciliationError(
            f"parent charge already has a terminal CPU reconciliation: {row_id}")
    runtime = _find_request_runtime(request_file, request)
    return {
        "schema": SCHEMA,
        "status": "READY_FOR_SAME_PARENT_CPU_DELTA" if delta > 0 else "NO_CPU_DELTA_REQUIRED",
        "request": {"path": str(request_file), "sha256": request_sha,
                     "schema": request.get("schema"), **identity},
        "receipt": {"path": str(receipt_file), "sha256": receipt_sha,
                     "status": receipt.get("status"), "cpu_core_seconds": receipt_cpu},
        "systemd_evidence": {"path": str(evidence_file), "sha256": sha256_file(evidence_file),
                              "cpu_usage_nanoseconds": evidence_ns,
                              "cpu_core_seconds": evidence_cpu, "cpu_unit": evidence_unit,
                              "unit": evidence["unit"], "terminal": True,
                              "invocation_id": invocation_id,
                              "exec_start_request_path_bound": True,
                              "properties_cpu_usage_nanoseconds": int(property_ns_value)},
        "ledger": {"path": str(ledger_file), "parent_charge_id": identity["charge_id"],
                    "parent_cpu_core_seconds": charge_cpu},
        "runtime_binding": runtime,
        "supplemental_charge_id": supplemental_id,
        "delta_cpu_core_seconds": delta,
        "reservation_created": False,
        "original_charge_unchanged": True,
        "qualification": dict(UNKNOWN),
    }


def reconcile(*, request_path: Path | str, receipt_path: Path | str,
              evidence_path: Path | str, ledger_path: Path | str,
              output: Path | str) -> dict[str, Any]:
    report = inspect_binding(request_path=request_path, receipt_path=receipt_path,
                             evidence_path=evidence_path, ledger_path=ledger_path)
    target = Path(output).expanduser()
    if target.exists():
        previous = load_json(target, "existing reconciliation report")[1]
        if (previous.get("schema") != SCHEMA
                or previous.get("supplemental_charge_id") != report["supplemental_charge_id"]
                or abs(float(previous.get("delta_cpu_core_seconds", -1))
                       - float(report["delta_cpu_core_seconds"])) > 1e-9):
            raise ReconciliationError(f"existing report does not match this reconciliation: {target}")
        # A stale sidecar cannot stand in for a ledger mutation.  Idempotence
        # requires the same supplemental row and exact CPU delta to exist.
        ledger_value = load_json(report["ledger"]["path"], "resource ledger")[1]
        rows = [row for row in ledger_value.get("charges", [])
                if isinstance(row, Mapping) and row.get("id") == report["supplemental_charge_id"]]
        if len(rows) != 1 or abs(_finite(rows[0].get("cpu_core_seconds"),
                                     "existing supplemental CPU")
                                - float(report["delta_cpu_core_seconds"])) > 1e-9:
            raise ReconciliationError("existing reconciliation report has no matching ledger charge")
        # A repeated invocation is a read-only confirmation.  It must never
        # append a second charge or overwrite the first sidecar.
        previous["status"] = "ALREADY_APPLIED_SAME_PARENT_CPU_DELTA"
        return previous
    if report["status"] == "NO_CPU_DELTA_REQUIRED":
        _write_new(target, report)
        return report
    request_file = Path(report["request"]["path"])
    ledger_file = Path(report["ledger"]["path"])
    runtime = _load_runtime(report["runtime_binding"])
    data_root = ledger_file.parent.parent
    supplemental_id = str(report["supplemental_charge_id"])
    delta = float(report["delta_cpu_core_seconds"])
    with runtime.ledger_locked(data_root) as ledger:
        parent = _find_charge(ledger, str(report["ledger"]["parent_charge_id"]))
        if abs(float(parent["cpu_core_seconds"]) - float(report["ledger"]["parent_cpu_core_seconds"])) > 1e-9:
            raise ReconciliationError("parent charge changed after preflight")
        existing = [row for row in ledger.get("charges", [])
                    if isinstance(row, Mapping) and row.get("id") == supplemental_id]
        if existing:
            if len(existing) != 1 or abs(float(existing[0].get("cpu_core_seconds", -1)) - delta) > 1e-9:
                raise ReconciliationError("supplemental charge ID already exists with different accounting")
            report["status"] = "ALREADY_APPLIED_SAME_PARENT_CPU_DELTA"
            report["ledger_append"] = {"id": supplemental_id, "cpu_core_seconds": delta,
                                        "new_storage_bytes": 0, "reservation_created": False,
                                        "append_performed": False}
            _write_new(target, report)
            return report
        if any(isinstance(row, Mapping) and row.get("id") == supplemental_id
               for row in ledger.get("reservations", [])):
            raise ReconciliationError("supplemental charge ID is still reserved")
        ledger.setdefault("charges", []).append({
            "id": supplemental_id,
            "parent_charge_id": str(report["ledger"]["parent_charge_id"]),
            "kind": "supplemental_terminal_cpu_delta",
            "gpu_seconds": 0.0,
            "cpu_core_seconds": delta,
            "new_storage_bytes": 0,
            "status": "completed",
            "finished_at_utc": report["receipt"].get("finished_at_utc") or "evidence-bound",
            "request_sha256": report["request"]["sha256"],
            "receipt_sha256": report["receipt"]["sha256"],
            "systemd_evidence_sha256": report["systemd_evidence"]["sha256"],
            "reconciliation_schema": SCHEMA,
            "reservation_created": False,
        })
    report["status"] = "APPENDED_SAME_PARENT_CPU_DELTA"
    report["ledger_append"] = {"id": supplemental_id, "cpu_core_seconds": delta,
                                "new_storage_bytes": 0, "reservation_created": False}
    _write_new(target, report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("inspect", "reconcile"):
        command = sub.add_parser(name)
        command.add_argument("--request", type=Path, required=True)
        command.add_argument("--receipt", type=Path, required=True)
        command.add_argument("--evidence", type=Path, required=True)
        command.add_argument("--ledger", type=Path, required=True)
        if name == "reconcile":
            command.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            value = inspect_binding(request_path=args.request, receipt_path=args.receipt,
                                    evidence_path=args.evidence, ledger_path=args.ledger)
        else:
            value = reconcile(request_path=args.request, receipt_path=args.receipt,
                              evidence_path=args.evidence, ledger_path=args.ledger,
                              output=args.output)
    except (ReconciliationError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"terminal CPU delta reconciler v6: {error}", file=sys.stderr)
        return 2
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
