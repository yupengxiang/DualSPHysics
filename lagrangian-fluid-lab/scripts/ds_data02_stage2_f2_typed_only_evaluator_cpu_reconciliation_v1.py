#!/usr/bin/env python3
"""Reconcile missing child CPU for an immutable failed evaluator attempt.

The V2/061 failed receipt and its original charge are immutable.  A managed
service can account CPU for a traced child in ``CPUUsageNSec`` even when the
parent process's ``RUSAGE_CHILDREN`` snapshot is smaller.  This helper adds a
single, idempotent *delta* charge under the existing Stage2 ledger after
checking an immutable CPU evidence sidecar.  It never rewrites or recharges
the original failed row, creates a reservation, or reads HDF5/BI4/raw data.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import resource
import sys
from typing import Any, Mapping, Sequence


SCHEMA = "ds02.stage2.f2-typed-only-evaluator-cpu-reconciliation.v1"
REPORT_SCHEMA = "ds02.stage2.f2-typed-only-evaluator-cpu-reconciliation-report.v1"
EVIDENCE_SCHEMA = "ds02.stage2.f2-typed-only-evaluator-cpu-evidence.v1"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")


class CpuReconciliationError(RuntimeError):
    pass


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, default=str).encode()).hexdigest()


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha(value: Any, role: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch not in HEX64 for ch in value):
        raise CpuReconciliationError(f"{role} must be lowercase SHA-256")
    return value


def load_json(path: Path | str, role: str, *, max_bytes: int = 8 * 1024 * 1024) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    if not target.is_file() or target.is_symlink() or target.stat().st_size > max_bytes:
        raise CpuReconciliationError(f"{role} is missing, symlinked, or too large: {target}")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CpuReconciliationError(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise CpuReconciliationError(f"{role} must be a JSON object")
    return value


def write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise CpuReconciliationError(f"refusing existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False,
                  allow_nan=False, default=str)
        stream.write("\n")
    return target


def _stat(path: Path, role: str) -> dict[str, int]:
    info = path.stat()
    if not path.is_file() or path.is_symlink():
        raise CpuReconciliationError(f"{role} is not a regular file: {path}")
    return {"bytes": int(info.st_size), "mtime_ns": int(info.st_mtime_ns),
            "mode_bits": int(info.st_mode & 0o777)}


def _load_runtime(path: Path, expected_sha: str) -> Any:
    if _sha(expected_sha, "runtime SHA") != sha256_file(path):
        raise CpuReconciliationError("bound runtime SHA differs")
    spec = importlib.util.spec_from_file_location("ds02_bound_runtime_v6_for_cpu_reconciliation", path)
    if spec is None or spec.loader is None:
        raise CpuReconciliationError(f"cannot load runtime: {path}")
    module = importlib.util.module_from_spec(spec)
    # The runtime's declared sibling imports (runtime_v2 and accounting
    # helpers) must resolve from the bound scripts directory.  This is a
    # private closure path, not a process-wide PYTHONPATH/original fallback.
    scripts_dir = str(path.parent)
    inserted = scripts_dir not in sys.path
    if inserted:
        sys.path.insert(0, scripts_dir)
    try:
        spec.loader.exec_module(module)
    finally:
        if inserted:
            try:
                sys.path.remove(scripts_dir)
            except ValueError:
                pass
    if not callable(getattr(module, "ledger_locked", None)):
        raise CpuReconciliationError("bound runtime does not expose ledger_locked")
    return module


def _cpu_from_evidence(evidence: Mapping[str, Any]) -> tuple[float, int]:
    if evidence.get("schema") != EVIDENCE_SCHEMA:
        raise CpuReconciliationError("CPU evidence schema differs")
    value = evidence.get("cpu_usage_nanoseconds")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CpuReconciliationError("CPU evidence nanoseconds must be a nonnegative integer")
    seconds = float(value) / 1_000_000_000.0
    if not math.isfinite(seconds):
        raise CpuReconciliationError("CPU evidence is not finite")
    return seconds, value


def _evidence_binding(path: Path | str) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    target = Path(path).expanduser().resolve()
    evidence = load_json(target, "CPU evidence")
    if evidence.get("sha256") != canonical_sha(evidence):
        raise CpuReconciliationError("CPU evidence canonical SHA differs")
    stat = _stat(target, "CPU evidence")
    return target, evidence, stat


def build_request(*, original_request: Path | str, evidence: Path | str,
                  output: Path | str, report_path: Path | str,
                  supplemental_charge_id: str | None = None) -> dict[str, Any]:
    original_path = Path(original_request).expanduser().resolve()
    original = load_json(original_path, "immutable failed evaluator request")
    if original.get("sha256") != canonical_sha(original):
        raise CpuReconciliationError("immutable failed evaluator request canonical SHA differs")
    parent = original.get("parent_resource_binding")
    accounting = original.get("accounting")
    if not isinstance(parent, Mapping) or not isinstance(accounting, Mapping):
        raise CpuReconciliationError("original request lacks parent accounting binding")
    ledger_path = Path(str(parent.get("ledger_path", ""))).expanduser().resolve()
    ledger = load_json(ledger_path, "parent resource ledger", max_bytes=128 * 1024 * 1024)
    charge_id = str(accounting.get("charge_id") or parent.get("charge_id") or "")
    attempt_id = str(parent.get("attempt_id") or accounting.get("attempt_id") or "")
    if not charge_id or not attempt_id:
        raise CpuReconciliationError("original charge/attempt ID is missing")
    old_rows = [row for row in ledger.get("charges", [])
                if isinstance(row, Mapping) and str(row.get("id")) == charge_id]
    if len(old_rows) != 1:
        raise CpuReconciliationError("original failed charge must be present exactly once")
    old = old_rows[0]
    old_cpu = float(old.get("cpu_core_seconds", 0.0) or 0.0)
    if str(old.get("status")) not in {"failed", "FAILED", "failed_parent", "FAILED_PARENT_EXECUTOR"}:
        raise CpuReconciliationError("original charge is not a failed terminal row")
    evidence_path, evidence_value, evidence_stat = _evidence_binding(evidence)
    observed_cpu, observed_ns = _cpu_from_evidence(evidence_value)
    if observed_cpu <= old_cpu:
        raise CpuReconciliationError("observed service CPU does not exceed original charge")
    delta = observed_cpu - old_cpu
    report_target = Path(report_path).expanduser().resolve()
    if report_target.exists():
        raise CpuReconciliationError("reconciliation report must be fresh")
    if supplemental_charge_id is None:
        supplemental_charge_id = charge_id + "::cpu-reconciliation-v1"
    runtime_candidates = [item for item in original.get("static_bindings", [])
                          if isinstance(item, Mapping) and item.get("role") == "shared_runtime_v6"]
    if not runtime_candidates:
        raise CpuReconciliationError("original request has no shared_runtime_v6 binding")
    runtime_binding = runtime_candidates[0]
    runtime_path = Path(str(runtime_binding.get("path", ""))).expanduser().resolve()
    runtime_sha = _sha(runtime_binding.get("sha256"), "shared_runtime_v6")
    request: dict[str, Any] = {
        "schema": SCHEMA, "status": "READY_FOR_PARENT_LEDGER_RECONCILIATION",
        "role": "DEVELOPMENT_ACCOUNTING", "model_invoked": False, "cfd_invoked": False,
        "qualification": dict(UNKNOWN),
        "original_request": {"path": str(original_path), "sha256": original["sha256"],
                              "attempt_id": attempt_id, "charge_id": charge_id},
        "parent_resource_binding": {"ledger_path": str(ledger_path), "same_parent_ledger": True,
                                     "new_ledger_owner": False, "no_new_reservation": True,
                                     "storage_policy": str(ledger.get("limits", {}).get("storage_policy", ""))},
        "evidence": {"path": str(evidence_path), "sha256": sha256_file(evidence_path),
                     "stat": evidence_stat, "schema": EVIDENCE_SCHEMA,
                     "observed_cpu_usage_nanoseconds": observed_ns,
                     "observed_cpu_seconds": observed_cpu,
                     "source_scope": evidence_value.get("source_scope")},
        "accounting": {"supplemental_charge_id": str(supplemental_charge_id),
                       "original_failed_charge_id": charge_id,
                       "original_failed_cpu_seconds": old_cpu,
                       "observed_service_cpu_seconds": observed_cpu,
                       "delta_cpu_seconds": delta,
                       "storage_delta_bytes": 0, "idempotent": True,
                       "original_charge_immutable": True},
        "runtime_binding": {"path": str(runtime_path), "sha256": runtime_sha,
                            "role": "shared_runtime_v6"},
        "report_path": str(report_target),
        "limitations": [
            "The original failed charge and receipt are immutable; only the measured CPU delta is added.",
            "The evidence is service/cgroup CPU usage, not a fabricated child rusage value.",
            "No reservation, HDF5/BI4/raw read, or scientific qualification is created.",
        ],
    }
    request["sha256"] = canonical_sha(request)
    write_new(output, request)
    return {"status": request["status"], "request": str(Path(output).expanduser().resolve()),
            "sha256": request["sha256"], "delta_cpu_seconds": delta,
            "observed_cpu_seconds": observed_cpu, "original_cpu_seconds": old_cpu,
            "payload_read": False, "qualification": dict(UNKNOWN)}


def _validate_request(request_path: Path | str) -> tuple[Path, dict[str, Any], dict[str, Any], Any]:
    path = Path(request_path).expanduser().resolve()
    request = load_json(path, "CPU reconciliation request")
    if request.get("schema") != SCHEMA or request.get("sha256") != canonical_sha(request):
        raise CpuReconciliationError("CPU reconciliation request schema/SHA differs")
    original_ref = request.get("original_request")
    evidence_ref = request.get("evidence")
    accounting = request.get("accounting")
    runtime_ref = request.get("runtime_binding")
    if not all(isinstance(item, Mapping) for item in (original_ref, evidence_ref, accounting, runtime_ref)):
        raise CpuReconciliationError("CPU reconciliation bindings are incomplete")
    original_path = Path(str(original_ref.get("path", ""))).expanduser().resolve()
    original = load_json(original_path, "immutable failed evaluator request")
    if original.get("sha256") != original_ref.get("sha256") or original.get("sha256") != canonical_sha(original):
        raise CpuReconciliationError("immutable original request changed")
    ledger_path = Path(str(original.get("parent_resource_binding", {}).get("ledger_path", ""))).expanduser().resolve()
    ledger = load_json(ledger_path, "parent resource ledger", max_bytes=128 * 1024 * 1024)
    evidence_path, evidence, evidence_stat = _evidence_binding(evidence_ref.get("path"))
    if evidence_ref.get("sha256") != sha256_file(evidence_path):
        raise CpuReconciliationError("CPU evidence bytes changed")
    if evidence_ref.get("stat") != evidence_stat:
        raise CpuReconciliationError("CPU evidence stat changed")
    observed_cpu, observed_ns = _cpu_from_evidence(evidence)
    old_charge_id = str(original.get("accounting", {}).get("charge_id") or original.get("parent_resource_binding", {}).get("charge_id") or "")
    old_rows = [row for row in ledger.get("charges", [])
                if isinstance(row, Mapping) and str(row.get("id")) == old_charge_id]
    if len(old_rows) != 1 or str(old_rows[0].get("status")) not in {"failed", "FAILED", "failed_parent", "FAILED_PARENT_EXECUTOR"}:
        raise CpuReconciliationError("original failed charge is missing or no longer failed")
    old_cpu = float(old_rows[0].get("cpu_core_seconds", 0.0) or 0.0)
    if abs(old_cpu - float(accounting.get("original_failed_cpu_seconds", -1.0))) > 1e-9:
        raise CpuReconciliationError("original failed CPU value changed")
    if observed_cpu <= old_cpu:
        raise CpuReconciliationError("observed service CPU does not exceed original charge")
    runtime_path = Path(str(runtime_ref.get("path", ""))).expanduser().resolve()
    runtime = _load_runtime(runtime_path, str(runtime_ref.get("sha256", "")))
    return path, request, {"ledger_path": ledger_path, "ledger": ledger,
                           "original": original, "old_cpu": old_cpu,
                           "observed_cpu": observed_cpu, "observed_ns": observed_ns,
                           "evidence_path": evidence_path, "evidence": evidence,
                           "evidence_stat": evidence_stat, "runtime_path": runtime_path}, runtime


def apply(request_path: Path | str) -> dict[str, Any]:
    request_file, request, bound, runtime = _validate_request(request_path)
    accounting = request["accounting"]
    supplement_id = str(accounting["supplemental_charge_id"])
    ledger_path = bound["ledger_path"]
    data_root = ledger_path.parent.parent
    original = bound["original"]
    attempt_id = str(original["parent_resource_binding"].get("attempt_id", ""))
    old_charge_id = str(accounting["original_failed_charge_id"])
    observed_cpu = float(bound["observed_cpu"])
    old_cpu = float(bound["old_cpu"])
    delta = observed_cpu - old_cpu
    report_path = Path(str(request["report_path"])).expanduser().resolve()
    now = datetime.now(timezone.utc).isoformat()
    with runtime.ledger_locked(data_root) as ledger:
        charges = ledger.setdefault("charges", [])
        rows = [row for row in charges if isinstance(row, Mapping) and row.get("id") == old_charge_id]
        if len(rows) != 1 or str(rows[0].get("status")) not in {"failed", "FAILED", "failed_parent", "FAILED_PARENT_EXECUTOR"}:
            raise CpuReconciliationError("original failed charge changed before reconciliation")
        existing = [row for row in charges if isinstance(row, Mapping) and row.get("id") == supplement_id]
        if existing:
            row = dict(existing[-1])
            if abs(float(row.get("cpu_core_seconds", -1.0)) - delta) > 1e-9:
                raise CpuReconciliationError("existing CPU reconciliation has a different delta")
            return {"schema": REPORT_SCHEMA, "status": "IDEMPOTENT_ALREADY_RECONCILED",
                    "charge": row, "original_charge_unchanged": True,
                    "payload_read": False, "qualification": dict(UNKNOWN)}
        if any(isinstance(row, Mapping) and str(row.get("id")) == attempt_id and
               str(row.get("status")) in {"reserved", "running"}
               for row in ledger.get("reservations", []) + charges):
            raise CpuReconciliationError("original attempt still has an active reservation/charge")
        max_cpu = ledger.get("limits", {}).get("cpu_core_seconds")
        used_cpu = sum(float(row.get("cpu_core_seconds", 0.0) or 0.0)
                       for row in charges if isinstance(row, Mapping))
        if max_cpu is not None and used_cpu + delta > float(max_cpu):
            raise CpuReconciliationError("parent CPU budget lacks reconciliation headroom")
        row = {
            "id": supplement_id, "parent_attempt_id": attempt_id,
            "kind": "typed_only_evaluator_failed_cpu_reconciliation_v1",
            "status": "completed", "gpu_seconds": 0.0,
            "cpu_core_seconds": delta, "new_storage_bytes": 0,
            "external_storage_bytes": 0, "home_storage_bytes": 0, "trace_bytes": 0,
            "original_failed_charge_id": old_charge_id,
            "original_failed_charge_cpu_seconds": old_cpu,
            "observed_service_cpu_seconds": observed_cpu,
            "cpu_evidence_path": str(bound["evidence_path"]),
            "cpu_evidence_sha256": sha256_file(bound["evidence_path"]),
            "cpu_evidence_nanoseconds": bound["observed_ns"],
            "accounting_scope": "same_parent_failed_evaluator_cpu_delta_only",
            "original_charge_immutable": True,
            "finished_at_utc": now,
        }
        charges.append(row)
    report = {
        "schema": REPORT_SCHEMA, "status": "CPU_DELTA_RECONCILED",
        "request": {"path": str(request_file), "sha256": request["sha256"]},
        "original_failed_charge": {"id": old_charge_id, "cpu_core_seconds": old_cpu,
                                    "immutable": True},
        "observed_service_cpu": {"nanoseconds": bound["observed_ns"],
                                  "seconds": observed_cpu,
                                  "evidence_path": str(bound["evidence_path"]),
                                  "evidence_sha256": sha256_file(bound["evidence_path"])},
        "reconciled_delta_cpu_seconds": delta,
        "charge": row, "same_parent_ledger": True, "new_ledger_owner": False,
        "reservation_created": False, "hdf5_or_bi4_read": False,
        "model_invoked": False, "cfd_invoked": False,
        "qualification": dict(UNKNOWN),
    }
    report["sha256"] = canonical_sha(report)
    write_new(report_path, report)
    return {"schema": REPORT_SCHEMA, "status": "CPU_DELTA_RECONCILED",
            "report_path": str(report_path), "charge": row,
            "original_charge_unchanged": True, "payload_read": False,
            "qualification": dict(UNKNOWN)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-request")
    build.add_argument("--original-request", type=Path, required=True)
    build.add_argument("--evidence", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--report-path", type=Path, required=True)
    build.add_argument("--supplemental-charge-id")
    apply_parser = sub.add_parser("apply")
    apply_parser.add_argument("--request", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "build-request":
            value = build_request(original_request=args.original_request, evidence=args.evidence,
                                  output=args.output, report_path=args.report_path,
                                  supplemental_charge_id=args.supplemental_charge_id)
        else:
            value = apply(args.request)
    except (CpuReconciliationError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"typed-only CPU reconciliation: {error}", file=sys.stderr)
        return 2
    print(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
