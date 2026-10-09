#!/usr/bin/env python3
"""Append a sampled operational CPU observation to the shared ledger.

The stale-search helper recorded four exact ``(pid, process_starttime_ticks)``
identities and their pre-signal CPU counters.  Those counters are known work
that future parent budget checks must include, but they are not a terminal
process charge: ancestor-shell CPU, signal teardown, and final CPU remain
unknown.  This forward reconciler appends one CPU-only
``operational_cpu_sample`` charge under the existing shared ledger lock.

Only small JSON/code files are read.  The snapshot, signal sidecar, and
operational ledger are SHA-bound and revalidated immediately before the
locked append.  The resource ledger's existing charges, reservations, limits,
and attempts are preserved byte-for-byte; the only permitted mutation is one
idempotent charge with zero GPU/storage and no reservation.  No scientific
qualification or attempt counter is changed.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import stat
import sys
from typing import Any, Iterator, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
SCHEMA = "ds02.stage2.operational-cpu-reconciler.v2"
OPERATIONAL_SCHEMA = "ds02.stage2.operational-stale-search-ledger.v1"
SNAPSHOT_SCHEMA = "ds02.stage2.task-owned-stale-search-resource-snapshot.v1"
SIGNAL_SCHEMA = "ds02.stage2.task-owned-stale-search-signal.v1"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
EXPECTED_ROW_COUNT = 4
MAX_JSON_BYTES = 64 * 1024 * 1024
RUNTIME_MAX_BYTES = 16 * 1024 * 1024


class OperationalReconciliationError(RuntimeError):
    """Raised when an operational sample cannot be safely appended."""


def sha256_file(path: Path | str) -> str:
    target = Path(path).expanduser()
    digest = hashlib.sha256()
    with target.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _file(path: Path | str, role: str, *, max_bytes: int = MAX_JSON_BYTES) -> Path:
    target = Path(path).expanduser()
    if target.is_symlink() or not target.is_file():
        raise OperationalReconciliationError(
            f"{role} must be an existing regular non-symlink file: {target}"
        )
    if target.stat().st_size > max_bytes:
        raise OperationalReconciliationError(f"{role} exceeds small-file bound: {target}")
    return target


def load_json(path: Path | str, role: str, *, max_bytes: int = MAX_JSON_BYTES) -> tuple[Path, dict[str, Any]]:
    target = _file(path, role, max_bytes=max_bytes)
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise OperationalReconciliationError(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise OperationalReconciliationError(f"{role} must be a JSON object")
    return target, value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser()
    if target.exists() or target.is_symlink():
        raise OperationalReconciliationError(f"refusing to overwrite report: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2,
                  sort_keys=True, allow_nan=False)
        stream.write("\n")
    return target


def _integer(value: Any, role: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise OperationalReconciliationError(f"{role} must be an integer >= {minimum}")
    return value


def _finite(value: Any, role: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise OperationalReconciliationError(f"{role} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        raise OperationalReconciliationError(f"{role} must be finite and >= {minimum}")
    return result


def _canonical(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False, default=str).encode("utf-8")).hexdigest()


def _same_path(left: Path | str, right: Path | str) -> bool:
    return Path(left).expanduser().resolve() == Path(right).expanduser().resolve()


def _validate_snapshot(snapshot_path: Path, value: Mapping[str, Any]) -> list[dict[str, Any]]:
    if value.get("schema") != SNAPSHOT_SCHEMA:
        raise OperationalReconciliationError("snapshot schema differs")
    if value.get("status") != "OWNERSHIP_VERIFIED_SNAPSHOT_BEFORE_SIGNAL":
        raise OperationalReconciliationError("snapshot is not the ownership-verified pre-signal record")
    if value.get("array_content_read_by_root") is not False:
        raise OperationalReconciliationError("snapshot does not rule out array reads")
    if value.get("io_not_equal_decoded_scientific_arrays") is not True:
        raise OperationalReconciliationError("snapshot lacks the scientific-credit boundary")
    budget_scope = value.get("budget_scope")
    if not isinstance(budget_scope, str) or "unreserved operational search" not in budget_scope:
        raise OperationalReconciliationError("snapshot is not an unreserved operational sample")
    raw_rows = value.get("rows")
    if not isinstance(raw_rows, list) or len(raw_rows) != EXPECTED_ROW_COUNT:
        raise OperationalReconciliationError(
            f"snapshot must contain exactly {EXPECTED_ROW_COUNT} RG rows"
        )
    rows: list[dict[str, Any]] = []
    identities: set[tuple[int, int]] = set()
    for index, raw in enumerate(raw_rows):
        if not isinstance(raw, Mapping):
            raise OperationalReconciliationError(f"snapshot row {index} is malformed")
        pid = _integer(raw.get("pid"), f"snapshot row {index}.pid", minimum=1)
        start = _integer(raw.get("process_starttime_ticks"),
                         f"snapshot row {index}.process_starttime_ticks", minimum=1)
        identity = (pid, start)
        if identity in identities:
            raise OperationalReconciliationError(f"duplicate snapshot PID/starttime: {identity}")
        identities.add(identity)
        argv = raw.get("argv")
        if not isinstance(argv, list) or not argv or Path(str(argv[0])).name != "rg":
            raise OperationalReconciliationError(f"snapshot row {index} is not an rg process")
        hz = _integer(raw.get("clock_ticks_per_second"),
                      f"snapshot row {index}.clock_ticks_per_second", minimum=1)
        utime = _integer(raw.get("sampled_utime_ticks"),
                         f"snapshot row {index}.sampled_utime_ticks")
        stime = _integer(raw.get("sampled_stime_ticks"),
                         f"snapshot row {index}.sampled_stime_ticks")
        cpu = _finite(raw.get("sampled_process_cpu_seconds"),
                      f"snapshot row {index}.sampled_process_cpu_seconds")
        expected = (utime + stime) / hz
        if not math.isclose(cpu, expected, rel_tol=0.0, abs_tol=1e-9):
            raise OperationalReconciliationError(f"snapshot row {index} CPU counters do not close")
        rows.append({
            "pid": pid,
            "process_starttime_ticks": start,
            "cwd": raw.get("cwd"),
            "argv": list(argv),
            "clock_ticks_per_second": hz,
            "sampled_utime_ticks": utime,
            "sampled_stime_ticks": stime,
            "sampled_process_cpu_seconds": cpu,
        })
    return rows


def _validate_signal(signal_path: Path, value: Mapping[str, Any], snapshot_path: Path,
                     rows: Sequence[Mapping[str, Any]]) -> None:
    if value.get("schema") != SIGNAL_SCHEMA:
        raise OperationalReconciliationError("signal schema differs")
    if not _same_path(value.get("snapshot", ""), snapshot_path):
        raise OperationalReconciliationError("signal does not bind the supplied snapshot")
    if value.get("foreign_processes_signalled") is not False:
        raise OperationalReconciliationError("signal sidecar reports foreign processes")
    results = value.get("results")
    if not isinstance(results, list) or len(results) != len(rows):
        raise OperationalReconciliationError("signal result count differs from snapshot")
    expected = {(int(row["pid"]), int(row["process_starttime_ticks"])) for row in rows}
    observed: set[tuple[int, int]] = set()
    for index, raw in enumerate(results):
        if not isinstance(raw, Mapping):
            raise OperationalReconciliationError(f"signal result {index} is malformed")
        pid = _integer(raw.get("pid"), f"signal result {index}.pid", minimum=1)
        matching = [identity for identity in expected if identity[0] == pid]
        if len(matching) != 1:
            raise OperationalReconciliationError(f"signal PID is not uniquely bound: {pid}")
        if matching[0] in observed:
            raise OperationalReconciliationError(f"duplicate signal PID: {pid}")
        observed.add(matching[0])
        if raw.get("signal") != "SIGTERM" or raw.get("only_exact_verified_rg_process_signalled") is not True:
            raise OperationalReconciliationError(f"signal result {index} is not an exact SIGTERM record")
    if observed != expected:
        raise OperationalReconciliationError("signal identities differ from snapshot identities")


def _validate_operational_ledger(path: Path, value: Mapping[str, Any], snapshot_path: Path,
                                 signal_path: Path, snapshot_sha: str, signal_sha: str,
                                 snapshot_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if value.get("schema") != OPERATIONAL_SCHEMA:
        raise OperationalReconciliationError("operational ledger schema differs")
    if value.get("status") != "APPEND_ONLY_OPERATIONAL_NONSCIENTIFIC":
        raise OperationalReconciliationError("operational ledger status is not append-only")
    if value.get("resource_ledger_mutated") is not False or value.get("reservation_created") is not False:
        raise OperationalReconciliationError("operational ledger claims resource mutation/reservation")
    if value.get("qualification_credit") != "NONE" or value.get("qualification") != UNKNOWN:
        raise OperationalReconciliationError("operational ledger contains qualification credit")
    rows = value.get("rows")
    if not isinstance(rows, list) or len(rows) != EXPECTED_ROW_COUNT:
        raise OperationalReconciliationError(
            f"operational ledger must contain exactly {EXPECTED_ROW_COUNT} rows"
        )
    expected_by_identity = {
        (int(row["pid"]), int(row["process_starttime_ticks"])): row
        for row in snapshot_rows
    }
    observed: set[tuple[int, int]] = set()
    sampled_total = 0.0
    for index, raw in enumerate(rows):
        if not isinstance(raw, Mapping):
            raise OperationalReconciliationError(f"operational row {index} is malformed")
        identity = (_integer(raw.get("pid"), f"operational row {index}.pid", minimum=1),
                    _integer(raw.get("process_starttime_ticks"),
                             f"operational row {index}.process_starttime_ticks", minimum=1))
        if identity in observed:
            raise OperationalReconciliationError(f"duplicate operational PID/starttime: {identity}")
        observed.add(identity)
        source = expected_by_identity.get(identity)
        if source is None:
            raise OperationalReconciliationError(f"operational identity is absent from snapshot: {identity}")
        cpu = _finite(raw.get("sampled_process_cpu_seconds"),
                      f"operational row {index}.sampled_process_cpu_seconds")
        if not math.isclose(cpu, float(source["sampled_process_cpu_seconds"]), rel_tol=0.0, abs_tol=1e-9):
            raise OperationalReconciliationError(f"operational row {index} CPU differs from snapshot")
        if raw.get("snapshot_sha256") != snapshot_sha or raw.get("signal_sidecar_sha256") != signal_sha:
            raise OperationalReconciliationError(f"operational row {index} source SHA differs")
        if raw.get("accounting_status") != "SAMPLED_PRE_SIGNAL_ONLY":
            raise OperationalReconciliationError(f"operational row {index} status is not pre-signal-only")
        if raw.get("post_signal_cpu") != "UNKNOWN" or raw.get("teardown_cpu") != "UNKNOWN":
            raise OperationalReconciliationError(f"operational row {index} overstates post-signal CPU")
        if raw.get("scientific_credit") != "NONE" or raw.get("qualification") != UNKNOWN:
            raise OperationalReconciliationError(f"operational row {index} has scientific credit")
        sampled_total += cpu
    if observed != set(expected_by_identity):
        raise OperationalReconciliationError("operational identities differ from snapshot")
    history = value.get("append_history")
    matching_history = []
    if isinstance(history, list):
        for raw in history:
            if not isinstance(raw, Mapping):
                continue
            if raw.get("snapshot_sha256") == snapshot_sha and raw.get("signal_sidecar_sha256") == signal_sha:
                matching_history.append(raw)
    if len(matching_history) != 1:
        raise OperationalReconciliationError("operational ledger has no unique matching append history")
    append = matching_history[0]
    if append.get("row_count") != EXPECTED_ROW_COUNT or append.get("content_read") is not False:
        raise OperationalReconciliationError("operational append history is not a metadata-only four-row append")
    if append.get("resource_ledger_mutated") is not False:
        raise OperationalReconciliationError("operational append history claims resource mutation")
    last = value.get("last_append")
    if not isinstance(last, Mapping) or last.get("snapshot_sha256") != snapshot_sha \
            or last.get("signal_sidecar_sha256") != signal_sha \
            or last.get("rows") != EXPECTED_ROW_COUNT:
        raise OperationalReconciliationError("operational last_append is not bound to the supplied sample")
    last_total = _finite(last.get("sampled_cpu_seconds_total"), "operational sampled total")
    if not math.isclose(last_total, sampled_total, rel_tol=0.0, abs_tol=1e-9):
        raise OperationalReconciliationError("operational sampled total does not close")
    return {
        "row_count": EXPECTED_ROW_COUNT,
        "sampled_cpu_seconds": sampled_total,
        "identities": sorted([{"pid": pid, "process_starttime_ticks": start}
                               for pid, start in observed], key=lambda item: (item["pid"], item["process_starttime_ticks"])),
    }


def _load_observation(*, snapshot_path: Path | str, signal_path: Path | str,
                      operational_ledger_path: Path | str) -> dict[str, Any]:
    snapshot_file, snapshot = load_json(snapshot_path, "stale-search snapshot")
    signal_file, signal = load_json(signal_path, "stale-search signal sidecar")
    operational_file, operational = load_json(operational_ledger_path, "operational ledger")
    snapshot_sha = sha256_file(snapshot_file)
    signal_sha = sha256_file(signal_file)
    operational_sha = sha256_file(operational_file)
    rows = _validate_snapshot(snapshot_file, snapshot)
    _validate_signal(signal_file, signal, snapshot_file, rows)
    details = _validate_operational_ledger(operational_file, operational, snapshot_file,
                                           signal_file, snapshot_sha, signal_sha, rows)
    return {
        "snapshot": {"path": str(snapshot_file), "sha256": snapshot_sha},
        "signal": {"path": str(signal_file), "sha256": signal_sha},
        "operational_ledger": {"path": str(operational_file), "sha256": operational_sha},
        **details,
    }


def _load_runtime(path: Path | str) -> Any:
    runtime_path = _file(path, "bound ledger runtime", max_bytes=RUNTIME_MAX_BYTES)
    module_name = "ds02_operational_reconciler_bound_runtime_v2"
    parent = str(runtime_path.parent)
    inserted = parent not in sys.path
    if inserted:
        sys.path.insert(0, parent)
    try:
        spec = importlib.util.spec_from_file_location(module_name, runtime_path)
        if spec is None or spec.loader is None:
            raise OperationalReconciliationError(f"cannot load bound ledger runtime: {runtime_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        if inserted:
            sys.path.remove(parent)
    if not callable(getattr(module, "ledger_locked", None)):
        raise OperationalReconciliationError("bound ledger runtime has no ledger_locked API")
    return runtime_path, module


def _resource_ledger_path(path: Path | str) -> tuple[Path, Path]:
    ledger_file = _file(path, "resource ledger", max_bytes=MAX_JSON_BYTES)
    expected = ledger_file.parent.parent / "runtime" / "resource-ledger.json"
    if ledger_file.resolve() != expected.resolve():
        raise OperationalReconciliationError(
            "resource ledger must be data_root/runtime/resource-ledger.json for the shared lock"
        )
    return ledger_file, ledger_file.parent.parent


def _ledger_shape(ledger: Mapping[str, Any]) -> None:
    if not isinstance(ledger.get("charges"), list):
        raise OperationalReconciliationError("resource ledger charges must be a list")
    if not isinstance(ledger.get("reservations"), list):
        raise OperationalReconciliationError("resource ledger reservations must be a list")
    if not isinstance(ledger.get("attempts"), list):
        raise OperationalReconciliationError("resource ledger attempts must be a list")
    if not isinstance(ledger.get("limits"), Mapping):
        raise OperationalReconciliationError("resource ledger limits must be an object")


def _resource_totals(ledger: Mapping[str, Any]) -> dict[str, float]:
    result = {"gpu_seconds": 0.0, "cpu_core_seconds": 0.0, "new_storage_bytes": 0.0}
    for section in ("charges", "reservations"):
        for index, row in enumerate(ledger[section]):
            if not isinstance(row, Mapping):
                raise OperationalReconciliationError(f"resource ledger {section}[{index}] is malformed")
            for key in result:
                result[key] += _finite(row.get(key, 0), f"resource ledger {section}[{index}].{key}")
    return result


def _charge_matches(row: Mapping[str, Any], charge_id: str, observation: Mapping[str, Any]) -> bool:
    return (
        row.get("id") == charge_id
        and row.get("kind") == "operational_cpu_sample"
        and math.isclose(_finite(row.get("cpu_core_seconds"), "existing operational CPU"),
                         float(observation["sampled_cpu_seconds"]), rel_tol=0.0, abs_tol=1e-9)
        and _finite(row.get("gpu_seconds"), "existing operational GPU") == 0.0
        and _finite(row.get("new_storage_bytes"), "existing operational storage") == 0.0
        and row.get("reservation_created") is False
        and row.get("snapshot_sha256") == observation["snapshot"]["sha256"]
        and row.get("signal_sidecar_sha256") == observation["signal"]["sha256"]
        and row.get("operational_ledger_sha256") == observation["operational_ledger"]["sha256"]
    )


def _report_matches(existing: Mapping[str, Any], observation: Mapping[str, Any], charge_id: str) -> bool:
    return (
        existing.get("schema") == SCHEMA
        and existing.get("charge_id") == charge_id
        and existing.get("snapshot", {}).get("sha256") == observation["snapshot"]["sha256"]
        and existing.get("signal", {}).get("sha256") == observation["signal"]["sha256"]
        and existing.get("operational_ledger", {}).get("sha256") == observation["operational_ledger"]["sha256"]
        and math.isclose(float(existing.get("sampled_cpu_seconds", -1)),
                         float(observation["sampled_cpu_seconds"]), rel_tol=0.0, abs_tol=1e-9)
    )


def inspect(*, snapshot_path: Path | str, signal_path: Path | str,
            operational_ledger_path: Path | str, resource_ledger_path: Path | str,
            runtime_path: Path | str) -> dict[str, Any]:
    observation = _load_observation(snapshot_path=snapshot_path, signal_path=signal_path,
                                    operational_ledger_path=operational_ledger_path)
    ledger_file, _data_root = _resource_ledger_path(resource_ledger_path)
    _runtime_file, _runtime = _load_runtime(runtime_path)
    _ledger_shape(load_json(ledger_file, "resource ledger")[1])
    charge_id = "operational::stale-search::" + observation["snapshot"]["sha256"]
    return {
        "schema": SCHEMA,
        "status": "READY_FOR_OPERATIONAL_CPU_SAMPLE",
        "charge_id": charge_id,
        "snapshot": observation["snapshot"],
        "signal": observation["signal"],
        "operational_ledger": observation["operational_ledger"],
        "row_count": observation["row_count"],
        "identities": observation["identities"],
        "sampled_cpu_seconds": observation["sampled_cpu_seconds"],
        "ancestor_cpu_seconds": "UNKNOWN",
        "teardown_cpu_seconds": "UNKNOWN",
        "resource_ledger": {"path": str(ledger_file), "runtime_path": str(_runtime_file)},
        "reservation_created": False,
        "attempts_mutated": False,
        "original_charges_mutated": False,
        "qualification_credit": "NONE",
        "qualification": dict(UNKNOWN),
    }


def reconcile(*, snapshot_path: Path | str, signal_path: Path | str,
              operational_ledger_path: Path | str, resource_ledger_path: Path | str,
              runtime_path: Path | str, output: Path | str) -> dict[str, Any]:
    observation = _load_observation(snapshot_path=snapshot_path, signal_path=signal_path,
                                    operational_ledger_path=operational_ledger_path)
    ledger_file, data_root = _resource_ledger_path(resource_ledger_path)
    runtime_file, runtime = _load_runtime(runtime_path)
    charge_id = "operational::stale-search::" + observation["snapshot"]["sha256"]
    target = Path(output).expanduser()
    if target.exists():
        existing = load_json(target, "existing reconciliation report")[1]
        if not _report_matches(existing, observation, charge_id):
            raise OperationalReconciliationError("existing report does not match this input bundle")
        ledger_value = load_json(ledger_file, "resource ledger")[1]
        rows = [row for row in ledger_value["charges"]
                if isinstance(row, Mapping) and row.get("id") == charge_id]
        if len(rows) != 1 or not _charge_matches(rows[0], charge_id, observation):
            raise OperationalReconciliationError("existing report has no matching operational charge")
        result = dict(existing)
        result["status"] = "ALREADY_APPLIED_OPERATIONAL_CPU_SAMPLE"
        return result

    preflight_ledger = load_json(ledger_file, "resource ledger")[1]
    _ledger_shape(preflight_ledger)
    preflight_charges = copy.deepcopy(preflight_ledger["charges"])
    preflight_reservations = copy.deepcopy(preflight_ledger["reservations"])
    preflight_attempts = copy.deepcopy(preflight_ledger["attempts"])
    preflight_limits = copy.deepcopy(preflight_ledger["limits"])
    preflight_totals = _resource_totals(preflight_ledger)
    # The lock API is the same parent lock used by runtime v2/v6.  No new
    # ledger or reservation owner is created here.
    with runtime.ledger_locked(data_root) as ledger:
        _ledger_shape(ledger)
        if copy.deepcopy(ledger["charges"]) != preflight_charges \
                or copy.deepcopy(ledger["reservations"]) != preflight_reservations \
                or copy.deepcopy(ledger["attempts"]) != preflight_attempts \
                or copy.deepcopy(ledger["limits"]) != preflight_limits:
            raise OperationalReconciliationError("resource ledger changed after preflight")
        fresh_observation = _load_observation(snapshot_path=snapshot_path, signal_path=signal_path,
                                              operational_ledger_path=operational_ledger_path)
        if fresh_observation != observation:
            raise OperationalReconciliationError("operational source bundle changed before append")
        existing = [row for row in ledger["charges"]
                    if isinstance(row, Mapping) and row.get("id") == charge_id]
        if existing:
            if len(existing) != 1 or not _charge_matches(existing[0], charge_id, observation):
                raise OperationalReconciliationError("operational charge ID exists with different accounting")
            status = "ALREADY_APPLIED_OPERATIONAL_CPU_SAMPLE"
        else:
            if any(isinstance(row, Mapping)
                   and row.get("operational_ledger_sha256") == observation["operational_ledger"]["sha256"]
                   for row in ledger["charges"]):
                raise OperationalReconciliationError("operational ledger SHA already has a different charge")
            if any(isinstance(row, Mapping)
                   and row.get("kind") == "operational_cpu_sample"
                   and row.get("snapshot_sha256") == observation["snapshot"]["sha256"]
                   for row in ledger["charges"]):
                raise OperationalReconciliationError("snapshot already has an operational CPU charge")
            ledger["charges"].append({
                "id": charge_id,
                "kind": "operational_cpu_sample",
                "status": "sampled_operational_only",
                "cpu_core_seconds": observation["sampled_cpu_seconds"],
                "gpu_seconds": 0.0,
                "new_storage_bytes": 0,
                "reservation_created": False,
                "snapshot_sha256": observation["snapshot"]["sha256"],
                "signal_sidecar_sha256": observation["signal"]["sha256"],
                "operational_ledger_sha256": observation["operational_ledger"]["sha256"],
                "sampled_row_count": observation["row_count"],
                "sampled_pid_starttime": observation["identities"],
                "ancestor_cpu_seconds": "UNKNOWN",
                "teardown_cpu_seconds": "UNKNOWN",
                "scientific_credit": "NONE",
                "qualification": dict(UNKNOWN),
                "reconciliation_schema": SCHEMA,
            })
            status = "APPENDED_OPERATIONAL_CPU_SAMPLE"
        if copy.deepcopy(ledger["reservations"]) != preflight_reservations \
                or copy.deepcopy(ledger["attempts"]) != preflight_attempts \
                or copy.deepcopy(ledger["limits"]) != preflight_limits:
            raise OperationalReconciliationError("operational append changed reservations/limits/attempts")
        if status != "ALREADY_APPLIED_OPERATIONAL_CPU_SAMPLE":
            if ledger["charges"][:-1] != preflight_charges:
                raise OperationalReconciliationError("operational append changed an original charge")
        elif ledger["charges"] != preflight_charges:
            raise OperationalReconciliationError("idempotent operational check changed existing charges")
        after_totals = _resource_totals(ledger)
        expected_cpu = preflight_totals["cpu_core_seconds"] + (
            0.0 if status.startswith("ALREADY") else observation["sampled_cpu_seconds"]
        )
        if not math.isclose(after_totals["cpu_core_seconds"], expected_cpu, rel_tol=0.0, abs_tol=1e-9):
            raise OperationalReconciliationError("resource CPU totals do not close")
        if after_totals["gpu_seconds"] != preflight_totals["gpu_seconds"] \
                or after_totals["new_storage_bytes"] != preflight_totals["new_storage_bytes"]:
            raise OperationalReconciliationError("operational append changed GPU/storage totals")
        if status.startswith("ALREADY"):
            final_charge = next(row for row in ledger["charges"] if row.get("id") == charge_id)
        else:
            final_charge = ledger["charges"][-1]
    report = {
        "schema": SCHEMA,
        "status": status,
        "charge_id": charge_id,
        "snapshot": observation["snapshot"],
        "signal": observation["signal"],
        "operational_ledger": observation["operational_ledger"],
        "row_count": observation["row_count"],
        "identities": observation["identities"],
        "sampled_cpu_seconds": observation["sampled_cpu_seconds"],
        "ancestor_cpu_seconds": "UNKNOWN",
        "teardown_cpu_seconds": "UNKNOWN",
        "resource_ledger": {"path": str(ledger_file), "runtime_path": str(runtime_file),
                             "before_totals": preflight_totals, "after_totals": after_totals},
        "charge": dict(final_charge),
        "reservation_created": False,
        "attempts_mutated": False,
        "original_charges_mutated": False,
        "qualification_credit": "NONE",
        "qualification": dict(UNKNOWN),
        "scientific_credit": "NONE",
    }
    _write_new(target, report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("inspect", "reconcile"):
        command = sub.add_parser(name)
        command.add_argument("--snapshot", type=Path, required=True)
        command.add_argument("--signal", type=Path, required=True)
        command.add_argument("--operational-ledger", type=Path, required=True)
        command.add_argument("--resource-ledger", type=Path, required=True)
        command.add_argument("--runtime", type=Path, required=True)
        if name == "reconcile":
            command.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            value = inspect(snapshot_path=args.snapshot, signal_path=args.signal,
                            operational_ledger_path=args.operational_ledger,
                            resource_ledger_path=args.resource_ledger, runtime_path=args.runtime)
        else:
            value = reconcile(snapshot_path=args.snapshot, signal_path=args.signal,
                              operational_ledger_path=args.operational_ledger,
                              resource_ledger_path=args.resource_ledger,
                              runtime_path=args.runtime, output=args.output)
    except (OperationalReconciliationError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"operational CPU reconciler v2: {error}", file=sys.stderr)
        return 2
    print(json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
