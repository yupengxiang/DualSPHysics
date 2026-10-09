#!/usr/bin/env python3
"""Append sampled stale-search CPU to a non-scientific operational ledger.

The root guard saved a small pre-SIGTERM snapshot for four owned ``rg``
processes.  Those counters are useful operational history, but they are not a
terminal process charge: signal teardown, ancestor-shell CPU, and the final
terminal observation are separate unknowns.  This helper records exactly the
sampled per-process counters under a unique ``(pid, process_starttime_ticks)``
identity and explicitly marks the row as unreserved, non-scientific, and
qualification-free.

It reads only the snapshot, its signal sidecar, and a small append-only
operational ledger.  It never opens DATA, H5, BI4, source arrays, or a
scientific attempt ledger.  The input ledger is never overwritten; callers
provide a fresh output path for each append.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA = "ds02.stage2.operational-stale-search-ledger.v1"
SNAPSHOT_SCHEMA = "ds02.stage2.task-owned-stale-search-resource-snapshot.v1"
SIGNAL_SCHEMA = "ds02.stage2.task-owned-stale-search-signal.v1"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
MAX_JSON_BYTES = 16 * 1024 * 1024


class OperationalLedgerError(RuntimeError):
    """Raised when a saved operational observation is not appendable."""


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _file(path: Path | str, role: str) -> Path:
    target = Path(path).expanduser().resolve()
    if target.is_symlink() or not target.is_file():
        raise OperationalLedgerError(f"{role} is not a regular file: {target}")
    if target.stat().st_size > MAX_JSON_BYTES:
        raise OperationalLedgerError(f"{role} exceeds the small-JSON bound: {target}")
    return target


def load_json(path: Path | str, role: str) -> tuple[Path, dict[str, Any]]:
    target = _file(path, role)
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise OperationalLedgerError(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise OperationalLedgerError(f"{role} must be a JSON object")
    return target, value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise OperationalLedgerError(f"refusing to overwrite operational ledger: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=True,
                  allow_nan=False)
        stream.write("\n")
    return target


def _integer(value: Any, role: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise OperationalLedgerError(f"{role} must be an integer >= {minimum}")
    return value


def _finite(value: Any, role: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise OperationalLedgerError(f"{role} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        raise OperationalLedgerError(f"{role} must be finite and >= {minimum}")
    return result


def _same_path(left: Path | str, right: Path | str) -> bool:
    return Path(left).expanduser().resolve() == Path(right).expanduser().resolve()


def _validate_snapshot(path: Path, snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
    if snapshot.get("schema") != SNAPSHOT_SCHEMA:
        raise OperationalLedgerError("snapshot schema differs")
    if snapshot.get("status") != "OWNERSHIP_VERIFIED_SNAPSHOT_BEFORE_SIGNAL":
        raise OperationalLedgerError("snapshot is not the ownership-verified pre-signal record")
    if snapshot.get("array_content_read_by_root") is not False:
        raise OperationalLedgerError("snapshot does not explicitly rule out root array reads")
    if snapshot.get("io_not_equal_decoded_scientific_arrays") is not True:
        raise OperationalLedgerError("snapshot does not declare the scientific-credit boundary")
    scope = snapshot.get("budget_scope")
    if not isinstance(scope, str) or "unreserved operational search" not in scope:
        raise OperationalLedgerError("snapshot budget scope is not operational/unreserved")
    rows = snapshot.get("rows")
    if not isinstance(rows, list) or not rows:
        raise OperationalLedgerError("snapshot rows are missing")
    result: list[dict[str, Any]] = []
    identities: set[tuple[int, int]] = set()
    for index, raw in enumerate(rows):
        if not isinstance(raw, Mapping):
            raise OperationalLedgerError(f"snapshot row {index} is malformed")
        pid = _integer(raw.get("pid"), f"snapshot row {index}.pid", minimum=1)
        start = _integer(raw.get("process_starttime_ticks"),
                         f"snapshot row {index}.process_starttime_ticks", minimum=1)
        identity = (pid, start)
        if identity in identities:
            raise OperationalLedgerError(f"duplicate PID/starttime in snapshot: {identity}")
        identities.add(identity)
        argv = raw.get("argv")
        if not isinstance(argv, list) or not argv or Path(str(argv[0])).name != "rg":
            raise OperationalLedgerError(f"snapshot row {index} is not an rg process")
        hz = _integer(raw.get("clock_ticks_per_second"),
                      f"snapshot row {index}.clock_ticks_per_second", minimum=1)
        utime = _integer(raw.get("sampled_utime_ticks"), f"snapshot row {index}.sampled_utime_ticks")
        stime = _integer(raw.get("sampled_stime_ticks"), f"snapshot row {index}.sampled_stime_ticks")
        cpu = _finite(raw.get("sampled_process_cpu_seconds"),
                      f"snapshot row {index}.sampled_process_cpu_seconds")
        expected_cpu = (utime + stime) / hz
        if not math.isclose(cpu, expected_cpu, rel_tol=0.0, abs_tol=1e-9):
            raise OperationalLedgerError(f"snapshot row {index} CPU counters do not close")
        result.append({
            "pid": pid,
            "process_starttime_ticks": start,
            "cwd": raw.get("cwd"),
            "argv": list(argv),
            "clock_ticks_per_second": hz,
            "sampled_utime_ticks": utime,
            "sampled_stime_ticks": stime,
            "sampled_process_cpu_seconds": cpu,
            "io_snapshot": raw.get("io"),
        })
    return result


def _validate_signal(signal_path: Path, signal: Mapping[str, Any], snapshot_path: Path,
                     rows: list[dict[str, Any]]) -> None:
    if signal.get("schema") != SIGNAL_SCHEMA:
        raise OperationalLedgerError("signal sidecar schema differs")
    if not _same_path(signal.get("snapshot", ""), snapshot_path):
        raise OperationalLedgerError("signal sidecar does not bind the supplied snapshot path")
    if signal.get("foreign_processes_signalled") is not False:
        raise OperationalLedgerError("signal sidecar reports foreign processes")
    results = signal.get("results")
    if not isinstance(results, list):
        raise OperationalLedgerError("signal sidecar results are missing")
    expected = {(row["pid"], row["process_starttime_ticks"]) for row in rows}
    observed: set[tuple[int, int]] = set()
    for index, raw in enumerate(results):
        if not isinstance(raw, Mapping):
            raise OperationalLedgerError(f"signal result {index} is malformed")
        pid = _integer(raw.get("pid"), f"signal result {index}.pid", minimum=1)
        # The signal sidecar currently records only PID.  A result without a
        # starttime is accepted only when that PID is unique in the snapshot;
        # the ledger row still carries the snapshot's exact starttime.
        matching = [key for key in expected if key[0] == pid]
        if len(matching) != 1:
            raise OperationalLedgerError(f"signal PID is not uniquely bound: {pid}")
        observed.add(matching[0])
        if raw.get("signal") != "SIGTERM" or raw.get("only_exact_verified_rg_process_signalled") is not True:
            raise OperationalLedgerError(f"signal result {index} is not an exact SIGTERM record")
    if observed != expected:
        raise OperationalLedgerError("signal result PID set differs from snapshot rows")


def _empty_ledger() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "status": "APPEND_ONLY_OPERATIONAL_NONSCIENTIFIC",
        "accounting_scope": "unreserved operational process sample; no scientific attempt charge",
        "resource_ledger_mutated": False,
        "reservation_created": False,
        "qualification_credit": "NONE",
        "qualification": dict(UNKNOWN),
        "rows": [],
    }


def append_snapshot(*, snapshot_path: Path | str, signal_path: Path | str,
                    output_ledger: Path | str, base_ledger: Path | str | None = None) -> dict[str, Any]:
    """Append one saved snapshot to a new operational ledger file."""
    snapshot_file, snapshot = load_json(snapshot_path, "stale-search snapshot")
    rows = _validate_snapshot(snapshot_file, snapshot)
    signal_file, signal = load_json(signal_path, "stale-search signal sidecar")
    _validate_signal(signal_file, signal, snapshot_file, rows)
    snapshot_sha = sha256_file(snapshot_file)
    signal_sha = sha256_file(signal_file)

    if base_ledger is None:
        ledger = _empty_ledger()
        base_path = None
        base_sha = None
    else:
        base_path, ledger = load_json(base_ledger, "base operational ledger")
        if ledger.get("schema") != SCHEMA:
            raise OperationalLedgerError("base operational ledger schema differs")
        if ledger.get("resource_ledger_mutated") is not False or ledger.get("reservation_created") is not False:
            raise OperationalLedgerError("base ledger is not operational/non-scientific")
        if ledger.get("qualification_credit") != "NONE":
            raise OperationalLedgerError("base ledger contains qualification credit")
        if not isinstance(ledger.get("rows"), list):
            raise OperationalLedgerError("base operational ledger rows are missing")
        base_sha = sha256_file(base_path)

    existing_rows = [row for row in ledger.get("rows", []) if isinstance(row, Mapping)]
    if any(row.get("snapshot_sha256") == snapshot_sha for row in existing_rows):
        raise OperationalLedgerError("snapshot has already been appended")
    existing_identities = {
        (int(row["pid"]), int(row["process_starttime_ticks"]))
        for row in existing_rows
        if isinstance(row.get("pid"), int) and isinstance(row.get("process_starttime_ticks"), int)
    }
    if existing_identities.intersection((row["pid"], row["process_starttime_ticks"]) for row in rows):
        raise OperationalLedgerError("PID/starttime identity already exists in operational ledger")

    appended = []
    for row in rows:
        appended.append({
            "observation_id": f"{snapshot_sha}:{row['pid']}:{row['process_starttime_ticks']}",
            "snapshot_sha256": snapshot_sha,
            "signal_sidecar_sha256": signal_sha,
            "pid": row["pid"],
            "process_starttime_ticks": row["process_starttime_ticks"],
            "cwd": row["cwd"], "argv": row["argv"],
            "sampled_utime_ticks": row["sampled_utime_ticks"],
            "sampled_stime_ticks": row["sampled_stime_ticks"],
            "clock_ticks_per_second": row["clock_ticks_per_second"],
            "sampled_process_cpu_seconds": row["sampled_process_cpu_seconds"],
            "io_snapshot": row["io_snapshot"],
            "accounting_status": "SAMPLED_PRE_SIGNAL_ONLY",
            "post_signal_cpu": "UNKNOWN",
            "teardown_cpu": "UNKNOWN",
            "scientific_credit": "NONE",
            "qualification": dict(UNKNOWN),
        })
    result = copy_ledger = dict(ledger)
    result["rows"] = list(existing_rows) + appended
    result["append_history"] = list(result.get("append_history", [])) + [{
        "snapshot_sha256": snapshot_sha, "signal_sidecar_sha256": signal_sha,
        "snapshot_path": str(snapshot_file), "signal_path": str(signal_file),
        "base_ledger_sha256": base_sha, "row_count": len(appended),
        "content_read": False, "resource_ledger_mutated": False,
    }]
    result["last_append"] = {
        "snapshot_sha256": snapshot_sha, "signal_sidecar_sha256": signal_sha,
        "sampled_cpu_seconds_total": sum(row["sampled_process_cpu_seconds"] for row in appended),
        "rows": len(appended), "status": "OPERATIONAL_SAMPLE_ONLY",
    }
    output = _write_new(Path(output_ledger), result)
    return {
        "schema": SCHEMA, "status": "APPENDED_OPERATIONAL_SAMPLE_ONLY",
        "output_ledger": str(output), "output_sha256": sha256_file(output),
        "snapshot_sha256": snapshot_sha, "signal_sidecar_sha256": signal_sha,
        "rows_appended": len(appended),
        "sampled_cpu_seconds_total": result["last_append"]["sampled_cpu_seconds_total"],
        "resource_ledger_mutated": False, "reservation_created": False,
        "scientific_credit": "NONE", "qualification": dict(UNKNOWN),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--signal", type=Path, required=True)
    parser.add_argument("--base-ledger", type=Path)
    parser.add_argument("--output-ledger", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = append_snapshot(snapshot_path=args.snapshot, signal_path=args.signal,
                                 base_ledger=args.base_ledger, output_ledger=args.output_ledger)
    except (OSError, OperationalLedgerError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(result, sort_keys=True, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
