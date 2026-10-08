#!/usr/bin/env python3
"""Reconcile the one missing terminal fee from the consumed ROOT078 run (V4 strict adapter).

This is a deliberately narrow accounting operation.  It consumes only the
already written ROOT078 request, its returned finalization report, the
immutable root binding sidecar, and the saved systemd resource evidence.  It
does not execute the evaluator and it
does not open H5, BI4, raw arrays, or the V16 result.  The original request,
report, and failed receipt are immutable; this helper appends one idempotent
``failed`` charge to the same Stage2 ledger with an explicit, one-session
``allow_missing_parent`` repair.

V4 is additive to the consumed V3 helper.  It supplies the complete
``P1._bound_for_parent`` adapter consumed by the reviewed runtime ``_charge``
implementation, including the cleanup grace field; the V2 source and its
receipts remain byte-for-byte unchanged.

The repair is intentionally separate from the V7 evaluator fix.  A future
typed evaluator request must opt into the scoped missing-parent policy at
build time (or create a real parent row); this helper never changes that old
request and never invents an ancestor row.
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
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
V6_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_typed_only_evaluator_parent_v6_current_bound.py"
SCHEMA = "ds02.stage2.f2-typed-parent-terminal-reconciliation.v4"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")


class TypedParentReconciliationError(RuntimeError):
    """Raised for stale, ambiguous, or unbound accounting repair inputs."""


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise TypedParentReconciliationError(f"cannot load bound module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V6 = _load(V6_SCRIPT, "ds02_bound_typed_parent_reconciliation_v2_v6")
PARENT = V6.V4.PARENT


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(
        {key: item for key, item in value.items() if key != "sha256"},
        sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False, default=str).encode("utf-8")).hexdigest()


def _file(value: Any, role: str, *, max_bytes: int | None = None) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not str(value):
        raise TypedParentReconciliationError(f"{role} path is missing")
    path = Path(value).expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise TypedParentReconciliationError(f"{role} is not a regular non-symlink file: {path}")
    if max_bytes is not None and path.stat().st_size > max_bytes:
        raise TypedParentReconciliationError(f"{role} exceeds the metadata-only bound: {path}")
    return path


def _json(path: Path, role: str, *, max_bytes: int = 64 * 1024 * 1024) -> dict[str, Any]:
    target = _file(path, role, max_bytes=max_bytes)
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise TypedParentReconciliationError(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise TypedParentReconciliationError(f"{role} must be a JSON object")
    return value


def _sha(value: Any, role: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in HEX64 for char in value):
        raise TypedParentReconciliationError(f"{role} must be a lowercase SHA-256")
    return value


def _number(value: Any, role: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypedParentReconciliationError(f"{role} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise TypedParentReconciliationError(f"{role} must be finite and nonnegative")
    return result


def _integer(value: Any, role: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TypedParentReconciliationError(f"{role} must be a nonnegative integer")
    return value


def _under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _tree_bytes(root: Path) -> int:
    if not root.is_dir():
        raise TypedParentReconciliationError(f"bound output root is unavailable: {root}")
    total = 0
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [name for name in dirs if not (Path(directory) / name).is_symlink()]
        for name in files:
            path = Path(directory) / name
            if path.is_symlink():
                raise TypedParentReconciliationError(f"symlink output is forbidden: {path}")
            total += int(path.stat().st_size)
    return total


def _trace_bytes(prefix: Path) -> int:
    candidates = [prefix] if prefix.exists() else []
    candidates.extend(prefix.parent.glob(prefix.name + ".*"))
    seen: set[Path] = set()
    total = 0
    for candidate in candidates:
        candidate = candidate.resolve()
        if candidate in seen or candidate.is_symlink() or not candidate.is_file():
            continue
        seen.add(candidate)
        total += int(candidate.stat().st_size)
    if not seen:
        raise TypedParentReconciliationError(f"bound trace is unavailable: {prefix}")
    return total


def _recursive_find(value: Any, keys: set[str]) -> list[Any]:
    found: list[Any] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key) in keys:
                found.append(item)
            found.extend(_recursive_find(item, keys))
    elif isinstance(value, list):
        for item in value:
            found.extend(_recursive_find(item, keys))
    return found


def _contains_file_binding(value: Any, path: Path, digest: str) -> bool:
    paths = [str(item) for item in _recursive_find(value, {"path", "request_path", "request_file"})
             if isinstance(item, (str, os.PathLike))]
    hashes = [item for item in _recursive_find(value, {"sha256", "request_sha256", "request_sha"})
              if isinstance(item, str)]
    # Some root proof sidecars call the original report ``returned_report``
    # and use ``report_sha256``.  Include all explicit SHA fields while still
    # requiring the exact absolute path and digest pair.
    hashes.extend(item for item in _recursive_find(
        value, {"report_sha256", "terminal_report_sha256", "evidence_sha256"})
                   if isinstance(item, str))
    return str(path) in paths and digest in hashes


def _contains_request_binding(value: Any, request_path: Path, request_sha: str) -> bool:
    return _contains_file_binding(value, request_path, request_sha)


def _contains_report_binding(value: Any, report_path: Path, report_sha: str) -> bool:
    return _contains_file_binding(value, report_path, report_sha)


def _cpu_evidence_values(value: Any) -> tuple[list[float], list[float]]:
    """Return seconds and nanoseconds values from the saved systemd JSON."""
    seconds: list[float] = []
    nanoseconds: list[float] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            norm = str(key).lower().replace("_", "").replace("-", "")
            if isinstance(item, (int, float)) and not isinstance(item, bool):
                if norm in {"cpuseconds", "cpucoreseconds", "systemdcpuseconds",
                            "cpuusageseconds", "systemdcpuusageseconds"}:
                    seconds.append(float(item))
                elif norm in {"cpuusagens", "cpuusagensc", "cpuusagenanoseconds",
                              "systemdcpuusagens", "systemdcpuusagenanoseconds"}:
                    nanoseconds.append(float(item))
            nested_s, nested_ns = _cpu_evidence_values(item)
            seconds.extend(nested_s)
            nanoseconds.extend(nested_ns)
    elif isinstance(value, list):
        for item in value:
            nested_s, nested_ns = _cpu_evidence_values(item)
            seconds.extend(nested_s)
            nanoseconds.extend(nested_ns)
    return seconds, nanoseconds


def _load_bound_request(request_path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Load a consumed V6 request without applying its fresh-output checks.

    V6's normal validator correctly rejects a consumed request because its
    output/receipt/trace already exist.  This repair needs the same binding
    fields but must inspect, rather than relaunch, that terminal namespace.
    """
    request = _json(request_path, "consumed V6 request", max_bytes=64 * 1024 * 1024)
    if request.get("schema") != V6.SCHEMA:
        raise TypedParentReconciliationError("request schema is not the consumed V6 schema")
    if request.get("sha256") != V6.canonical_sha(request):
        raise TypedParentReconciliationError("request canonical SHA differs")
    if request.get("status") != "READY_FOR_PARENT_GUARD":
        raise TypedParentReconciliationError("request is not the immutable parent-ready request")
    if request.get("role") != "DEVELOPMENT" or request.get("qualification") != UNKNOWN:
        raise TypedParentReconciliationError("request must remain DEVELOPMENT/UNKNOWN")
    parent = request.get("parent_resource_binding")
    storage = request.get("storage_scope")
    execution = request.get("execution")
    if not all(isinstance(item, Mapping) for item in (parent, storage, execution)):
        raise TypedParentReconciliationError("parent/storage/execution bindings are incomplete")
    ledger = _file(parent.get("ledger_path"), "Stage2 ledger", max_bytes=128 * 1024 * 1024)
    live = _json(ledger, "Stage2 ledger", max_bytes=128 * 1024 * 1024)
    limits = live.get("limits")
    if not isinstance(limits, Mapping):
        raise TypedParentReconciliationError("live ledger limits are missing")
    if str(parent.get("storage_policy")) != str(limits.get("storage_policy")):
        raise TypedParentReconciliationError("request storage policy differs from live ledger")
    if int(parent.get("home_min_free_bytes", -1)) != int(limits.get("home_min_free_bytes", -2)):
        raise TypedParentReconciliationError("request Home floor differs from live ledger")
    if str(parent.get("deadline_utc", "")) != str(live.get("deadline_utc", "")):
        raise TypedParentReconciliationError("request deadline differs from live ledger")
    external = Path(str(storage.get("external_filesystem", ""))).expanduser().resolve()
    output_root = Path(str(storage.get("supervisor_output_root", ""))).expanduser().resolve()
    receipt = Path(str(storage.get("home_receipt_path", ""))).expanduser().resolve()
    trace = Path(str(execution.get("strace", {}).get("trace_path", ""))).expanduser().resolve()
    if not external.is_dir() or not output_root.is_dir() or not receipt.is_file():
        raise TypedParentReconciliationError("consumed output namespace is unavailable")
    if not _under(output_root, external) or output_root == external:
        raise TypedParentReconciliationError("output root is outside the bound external filesystem")
    if not _under(trace, output_root):
        raise TypedParentReconciliationError("trace is outside the bound output root")
    if not parent.get("attempt_id") or not parent.get("reservation_id") or not parent.get("charge_id"):
        raise TypedParentReconciliationError("request accounting IDs are incomplete")
    runtime_path = None
    runtime_declared_sha = None
    for item in request.get("static_bindings", []):
        if isinstance(item, Mapping) and item.get("role") == "shared_runtime_v6":
            runtime_path = _file(item.get("path"), "shared runtime v6")
            runtime_declared_sha = _sha(item.get("sha256"), "shared runtime v6 SHA")
            break
    if runtime_path is None:
        raise TypedParentReconciliationError("shared runtime v6 binding is missing")
    runtime_actual_sha = sha256_file(runtime_path)
    if runtime_actual_sha != runtime_declared_sha:
        raise TypedParentReconciliationError("shared runtime v6 content differs before mutation")
    bound = {
        "path": request_path, "request": request, "ledger": ledger,
        "limits": dict(limits), "external": external, "output_root": output_root,
        "receipt": receipt, "trace_path": trace, "runtime_path": runtime_path,
        "runtime_sha": runtime_actual_sha,
        # These are required by the real P1._bound_for_parent adapter.  The
        # prior V3 loader supplied them only in its manufactured fixture,
        # which let a real ROOT078 load fail before _charge with KeyError.
        "external_estimate": int(storage.get("external_reservation_bytes", 0) or 0),
        "home_estimate": int(storage.get("home_receipt_bytes", 0) or 0),
        "parent_attempt_id": str(parent["attempt_id"]),
        "reservation_id": str(parent["reservation_id"]),
        "charge_id": str(parent["charge_id"]),
        "allow_missing_parent": bool(parent.get("allow_missing_parent", False)),
        "max_wall": float(execution.get("max_wall_seconds", 0.0) or 0.0),
    }
    if bound["external_estimate"] <= 0 or bound["home_estimate"] <= 0:
        raise TypedParentReconciliationError("consumed request storage estimates are invalid")
    if not math.isfinite(bound["max_wall"]) or bound["max_wall"] <= 0:
        raise TypedParentReconciliationError("request max wall is invalid")
    bound["cleanup_grace"] = float(execution.get("child_cleanup_grace_seconds", 25.0) or 25.0)
    if not math.isfinite(bound["cleanup_grace"]) or bound["cleanup_grace"] < 20.0:
        raise TypedParentReconciliationError("request cleanup grace is below the reviewed parent minimum")
    return request, bound, live


def _validate_terminal_inputs(request: Mapping[str, Any], bound: Mapping[str, Any],
                              report_path: Path, evidence_path: Path,
                              binding_sidecar_path: Path | None,
                              cpu_seconds: float, external_bytes: int,
                              home_bytes: int, trace_bytes: int) -> tuple[dict[str, Any], dict[str, Any]]:
    report = _json(report_path, "ROOT078 finalization report")
    evidence = _json(evidence_path, "ROOT078 systemd evidence", max_bytes=16 * 1024 * 1024)
    request_sha = sha256_file(bound["path"])
    report_sha = sha256_file(report_path)
    binding_sidecar = None
    if not _contains_request_binding(report, bound["path"], request_sha):
        if binding_sidecar_path is None:
            raise TypedParentReconciliationError(
                "finalization report is not bound to the consumed request; an immutable root binding sidecar is required")
        binding_sidecar = _json(binding_sidecar_path, "ROOT078 request/report binding sidecar")
        if not _contains_request_binding(binding_sidecar, bound["path"], request_sha):
            raise TypedParentReconciliationError(
                "root binding sidecar does not bind the consumed request")
        if not _contains_report_binding(binding_sidecar, report_path, report_sha):
            raise TypedParentReconciliationError(
                "root binding sidecar does not bind the unchanged finalization report")
    status_values = [item for item in _recursive_find(report, {"status"}) if isinstance(item, str)]
    if not any(item.startswith("FAILED") for item in status_values):
        raise TypedParentReconciliationError("ROOT078 report is not a failed terminal report")
    if report.get("model_invoked") is True or report.get("cfd_invoked") is True:
        raise TypedParentReconciliationError("accounting repair cannot credit model/CFD execution")
    # The systemd file is the authoritative outer-service evidence.  Its
    # binding is required even when its schema evolves; values are supplied
    # explicitly by the root from that saved evidence, never guessed here.
    evidence_sha = sha256_file(evidence_path)
    declared_request_hashes = _recursive_find(evidence, {"request_sha256", "request_sha"})
    if declared_request_hashes and request_sha not in declared_request_hashes:
        raise TypedParentReconciliationError("systemd evidence names a different request")
    declared_report_hashes = _recursive_find(evidence, {"report_sha256", "terminal_report_sha256"})
    report_sha = sha256_file(report_path)
    if declared_report_hashes and report_sha not in declared_report_hashes:
        raise TypedParentReconciliationError("systemd evidence names a different terminal report")
    evidence_seconds, evidence_nanoseconds = _cpu_evidence_values(evidence)
    if not evidence_seconds and not evidence_nanoseconds:
        raise TypedParentReconciliationError(
            "systemd evidence has no recognized CPU seconds/CPUUsageNSec field")
    if evidence_seconds and not any(abs(value - cpu_seconds) <= 1e-6 for value in evidence_seconds):
        raise TypedParentReconciliationError(
            f"CPU seconds differ from saved systemd evidence: requested={cpu_seconds}")
    if evidence_nanoseconds and not any(abs(value / 1_000_000_000.0 - cpu_seconds) <= 1e-6
                                        for value in evidence_nanoseconds):
        raise TypedParentReconciliationError(
            f"CPUUsageNSec differs from saved systemd evidence: requested={cpu_seconds}")
    measured_external = _tree_bytes(bound["output_root"])
    measured_home = int(bound["receipt"].stat().st_size)
    measured_trace = _trace_bytes(bound["trace_path"])
    if measured_external != external_bytes:
        raise TypedParentReconciliationError(
            f"external bytes differ: evidence={external_bytes}, live={measured_external}")
    if measured_home != home_bytes:
        raise TypedParentReconciliationError(
            f"Home receipt bytes differ: evidence={home_bytes}, live={measured_home}")
    if measured_trace != trace_bytes:
        raise TypedParentReconciliationError(
            f"trace bytes differ: evidence={trace_bytes}, live={measured_trace}")
    return report, {"request_sha256": request_sha, "report_sha256": report_sha,
                    "binding_sidecar_sha256": (None if binding_sidecar_path is None
                                                else sha256_file(binding_sidecar_path)),
                    "evidence_sha256": evidence_sha, "cpu_seconds": cpu_seconds,
                    "external_bytes": external_bytes, "home_bytes": home_bytes,
                    "trace_bytes": trace_bytes}


def _live_rows(ledger: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    value = _json(ledger, "Stage2 ledger", max_bytes=128 * 1024 * 1024)
    reservations = [row for row in value.get("reservations", []) if isinstance(row, dict)]
    charges = [row for row in value.get("charges", []) if isinstance(row, dict)]
    return reservations, charges


def reconcile_terminal(*, request_path: Path, report_path: Path, evidence_path: Path,
                       binding_sidecar_path: Path | None,
                       output: Path, cpu_seconds: float, external_bytes: int,
                       home_bytes: int, trace_bytes: int,
                       allow_missing_parent_repair: bool = False) -> dict[str, Any]:
    if not allow_missing_parent_repair:
        raise TypedParentReconciliationError(
            "explicit --allow-missing-parent-repair is required for ROOT078")
    cpu_seconds = _number(cpu_seconds, "systemd CPU seconds")
    external_bytes = _integer(external_bytes, "external bytes")
    home_bytes = _integer(home_bytes, "Home bytes")
    trace_bytes = _integer(trace_bytes, "trace bytes")
    if cpu_seconds <= 0 or external_bytes <= 0 or home_bytes <= 0 or trace_bytes <= 0:
        raise TypedParentReconciliationError("ROOT078 measurements must be positive")
    request_path = _file(request_path, "consumed V6 request")
    report_path = _file(report_path, "ROOT078 finalization report")
    evidence_path = _file(evidence_path, "ROOT078 systemd evidence")
    if binding_sidecar_path is not None:
        binding_sidecar_path = _file(binding_sidecar_path, "ROOT078 request/report binding sidecar")
    request, bound, live = _load_bound_request(request_path)
    report, evidence = _validate_terminal_inputs(
        request, bound, report_path, evidence_path, binding_sidecar_path, cpu_seconds,
        external_bytes, home_bytes, trace_bytes)
    # Validate the proof destination before touching the ledger.  It is
    # metadata provenance and is intentionally outside the charged external
    # output tree; a bad destination must never leave a new fee behind.
    output = Path(output).expanduser().resolve()
    if _under(output, bound["external"]) or output == bound["receipt"]:
        raise TypedParentReconciliationError(
            "repair proof must be outside the charged external namespace and receipt")
    if output.exists():
        raise TypedParentReconciliationError(f"refusing existing repair proof: {output}")
    reservations, charges = _live_rows(bound["ledger"])
    reservation_rows = [row for row in reservations if row.get("id") == bound["reservation_id"]]
    charge_rows = [row for row in charges if row.get("id") == bound["charge_id"]]
    if len(reservation_rows) > 1 or len(charge_rows) > 1:
        raise TypedParentReconciliationError("duplicate ROOT078 reservation/charge ID")
    if charge_rows:
        existing = charge_rows[0]
        expected = {
            "cpu_core_seconds": cpu_seconds, "external_storage_bytes": external_bytes,
            "home_storage_bytes": home_bytes, "trace_bytes": trace_bytes,
        }
        for key, value in expected.items():
            if float(existing.get(key, -1)) != float(value):
                raise TypedParentReconciliationError(
                    f"existing charge {bound['charge_id']} has different {key}")
        charge_result: dict[str, Any] = {"status": "PARENT_CHARGE_ALREADY_APPLIED", "charge": existing,
                                         "ledger_mutated": False}
        state = "ALREADY_RECONCILED"
    else:
        parent_rows = [row for row in charges if row.get("id") == bound["parent_attempt_id"]]
        if any(str(row.get("status")) in {"reserved", "running"} for row in parent_rows):
            raise TypedParentReconciliationError("active parent row cannot receive ROOT078 repair")
        if parent_rows:
            raise TypedParentReconciliationError(
                "ROOT078 scoped missing-parent repair is only valid when the parent row is absent")
        # Exercise the same real adapter used by the production charge path.
        # This is intentionally not a hand-built dict: P1._bound_for_parent
        # supplies the executor/runtime/storage fields expected by PARENT._charge.
        parent_bound = V6.V4.P1._bound_for_parent(bound)
        if float(parent_bound.get("cleanup_grace", -1.0)) < 20.0:
            raise TypedParentReconciliationError(
                "reviewed parent adapter did not preserve cleanup grace")
        parent_bound["allow_missing_parent"] = True
        charge_result = PARENT._charge(
            parent_bound, status="failed", cpu_seconds=cpu_seconds,
            external_bytes=external_bytes, home_bytes=home_bytes,
            trace_bytes=trace_bytes, copy_hash_bytes=0,
            allow_missing_parent=True)
        state = "RECONCILED_TERMINAL_CHARGE_APPLIED"
    # This proof is intentionally outside the charged external root, so its
    # own bytes cannot silently change the already measured fee.
    proof = {
        "schema": SCHEMA, "status": state,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "request": {"path": str(request_path), "sha256": evidence["request_sha256"],
                    "original_allow_missing_parent": bool(
                        request["parent_resource_binding"].get("allow_missing_parent", False))},
        "terminal_inputs": {
            "report": {"path": str(report_path), "sha256": evidence["report_sha256"]},
            "binding_sidecar": (None if binding_sidecar_path is None else
                                 {"path": str(binding_sidecar_path),
                                  "sha256": evidence["binding_sidecar_sha256"]}),
            "systemd_evidence": {"path": str(evidence_path), "sha256": evidence["evidence_sha256"]},
            "report_status": [item for item in _recursive_find(report, {"status"}) if isinstance(item, str)],
        },
        "parent": {"ledger_path": str(bound["ledger"]),
                   "parent_attempt_id": bound["parent_attempt_id"],
                   "reservation_id": bound["reservation_id"],
                   "charge_id": bound["charge_id"], "same_parent_ledger": True,
                   "ledger_reset": False, "parent_row_present_before_repair": False,
                   "allow_missing_parent_repair": True},
        "measurements": {"cpu_core_seconds": cpu_seconds,
                         "external_storage_bytes": external_bytes,
                         "home_storage_bytes": home_bytes, "trace_bytes": trace_bytes,
                         "copy_hash_bytes": 0, "measurement_source": "saved systemd + live stat"},
        "charge": charge_result,
        "hdf5_or_bi4_content_read": False, "raw_opened": False,
        "model_invoked": False, "cfd_invoked": False,
        "qualification": dict(UNKNOWN),
        "credit_boundary": "Accounting reconciliation only; no replay, label, QI, QN, or QE credit.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    proof["sha256"] = canonical_sha(proof)
    output.write_text(json.dumps(proof, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"schema": SCHEMA, "status": state, "proof_path": str(output),
            "proof_sha256": sha256_file(output), "charge": charge_result,
            "measurements": evidence, "payload_read": False}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--terminal-report", type=Path, required=True)
    parser.add_argument("--systemd-evidence", type=Path, required=True)
    parser.add_argument("--binding-sidecar", type=Path,
                        help="immutable root sidecar binding request and unchanged report")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu-seconds", type=float, required=True)
    parser.add_argument("--external-bytes", type=int, required=True)
    parser.add_argument("--home-bytes", type=int, required=True)
    parser.add_argument("--trace-bytes", type=int, required=True)
    parser.add_argument("--allow-missing-parent-repair", action="store_true")
    args = parser.parse_args(argv)
    try:
        value = reconcile_terminal(
            request_path=args.request, report_path=args.terminal_report,
            evidence_path=args.systemd_evidence, binding_sidecar_path=args.binding_sidecar,
            output=args.output,
            cpu_seconds=args.cpu_seconds, external_bytes=args.external_bytes,
            home_bytes=args.home_bytes, trace_bytes=args.trace_bytes,
            allow_missing_parent_repair=args.allow_missing_parent_repair)
    except (TypedParentReconciliationError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"typed parent ROOT078 reconciliation: {error}")
        return 2
    print(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
