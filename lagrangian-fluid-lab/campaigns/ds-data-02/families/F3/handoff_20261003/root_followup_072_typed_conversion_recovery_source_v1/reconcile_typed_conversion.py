#!/usr/bin/env python3
"""Root-reviewed, fail-closed settlement contract for orphaned CPU conversions.

This module has no solver, converter, signal, or subprocess path. It can
capture read-only /proc evidence and, after an external Root authorization,
apply one exact CPU reservation settlement through the unchanged runtime v2
``ledger_locked``/``atomic_json`` interfaces. The package CLI is permanently
disabled; Root must import and review the library call in the integration
worktree before enabling it.

The runtime v2 launcher did not persist process start ticks.  This variant
records that historical fact as ``null`` and never substitutes zero.  A
settlement therefore requires a fresh in-lock double census from a qualified
root caller: same host, boot identity, PID namespace, and complete empty
process-group scans, with every recorded PID absent as ``ENOENT``.  A caller
cannot submit a stale liveness document to the application function.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import errno
import hashlib
import json
import os
from pathlib import Path
import socket
import stat
import time
from typing import Any, Callable, Mapping


SCHEMA = "ds02.root-owned.typed-conversion-reconciliation.v2"
SAMPLE_SCHEMA = "ds02.qualified-root.proc-stat-double-sample.v2"
JOURNAL_SCHEMA = "ds02.root-owned.reconciliation-journal.v2"
CHARGE_STATUS = "interrupted_unfinalized"
TARGETS = ("launcher", "child", "group_leader")
AUTHORIZATION_TOKEN = "ROOT_REVIEWED_FRESH072"
UNKNOWN_START_TICKS = "unknown_historical_start_ticks"
ABSENCE_GUARD = "current-double-absence-only;historical-start-ticks-unknown"


class ReconciliationRefused(ValueError):
    """Raised whenever exact ownership or terminal-death proof is absent."""


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_sha256(value: Any) -> str:
    return sha256_bytes(canonical_bytes(value))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ReconciliationRefused(message)


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
    fd = os.open(path, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _runtime_atomic_json(runtime_module: Any, path: Path,
                         value: Mapping[str, Any]) -> None:
    """Call runtime-v2 atomic_json, then close its directory durability gap."""
    runtime_module.atomic_json(path, value)
    _fsync_directory(Path(path).parent)


def _read_regular_bytes(path: Path) -> bytes:
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ReconciliationRefused(
                f"receipt is not a single-link regular file: {path}")
        chunks: list[bytes] = []
        while True:
            block = os.read(fd, 1024 * 1024)
            if not block:
                break
            chunks.append(block)
        after = os.fstat(fd)
        before_id = (before.st_dev, before.st_ino, before.st_size,
                     before.st_mtime_ns, before.st_ctime_ns)
        after_id = (after.st_dev, after.st_ino, after.st_size,
                    after.st_mtime_ns, after.st_ctime_ns)
        if before_id != after_id:
            raise ReconciliationRefused(f"receipt changed during read: {path}")
        return b"".join(chunks)
    finally:
        os.close(fd)


def _exclusive_bytes(path: Path, value: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = (os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC |
             getattr(os, "O_NOFOLLOW", 0))
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        existing = _read_regular_bytes(path)
        if existing != value:
            raise ReconciliationRefused(
                f"sidecar exists with different bytes: {path}")
        return
    try:
        offset = 0
        while offset < len(value):
            offset += os.write(fd, value[offset:])
        os.fsync(fd)
        observed = os.fstat(fd)
        if not stat.S_ISREG(observed.st_mode) or observed.st_nlink != 1:
            raise ReconciliationRefused(f"sidecar is not a regular file: {path}")
    finally:
        os.close(fd)
    _fsync_directory(path.parent)


def preserve_receipt_sidecar(receipt_path: Path, sidecar_path: Path,
                             expected_sha256: str) -> dict[str, Any]:
    """Copy exact old receipt bytes once; never rewrite the source receipt."""
    raw = _read_regular_bytes(Path(receipt_path))
    observed = sha256_bytes(raw)
    if observed != expected_sha256:
        raise ReconciliationRefused(
            f"original receipt hash mismatch: expected {expected_sha256}, got {observed}")
    _exclusive_bytes(Path(sidecar_path), raw)
    return {"path": str(Path(sidecar_path)), "sha256": observed,
            "bytes": len(raw), "source_path": str(Path(receipt_path))}


def _proc_boot_id(proc_root: Path) -> str:
    path = Path(proc_root) / "sys/kernel/random/boot_id"
    try:
        return path.read_text(encoding="ascii").strip()
    except OSError as error:
        raise ReconciliationRefused(
            f"cannot read qualified proc boot id: {path}") from error


def _proc_pid_namespace(proc_root: Path) -> str:
    """Return the qualified host's PID namespace identity without spawning."""
    init_path = Path(proc_root) / "1/ns/pid"
    caller_path = Path(proc_root) / "self/ns/pid"
    try:
        value = os.readlink(init_path)
        caller_value = os.readlink(caller_path)
    except OSError as error:
        raise ReconciliationRefused(
            f"cannot read qualified PID namespace: {init_path} or {caller_path}") from error
    _require(bool(value), f"qualified PID namespace is empty: {init_path}")
    _require(value == caller_value,
             "qualified root caller is not in the observed PID namespace")
    return value


def _parse_proc_stat(raw: bytes, expected_pid: int) -> dict[str, Any]:
    # comm may contain spaces and ')' characters; the last ')' is the grammar
    # boundary for the fields that follow it.
    split_at = raw.rfind(b")")
    if split_at < 0:
        raise ReconciliationRefused(f"malformed /proc/{expected_pid}/stat")
    tail = raw[split_at + 2:].split()
    if len(tail) <= 19:
        raise ReconciliationRefused(f"short /proc/{expected_pid}/stat")
    try:
        pid = int(raw[:raw.find(b" ")])
        state = tail[0].decode("ascii")
        ppid = int(tail[1])
        pgrp = int(tail[2])
        session = int(tail[3])
        start_ticks = int(tail[19])
    except (ValueError, UnicodeDecodeError) as error:
        raise ReconciliationRefused(
            f"unparseable /proc/{expected_pid}/stat") from error
    if pid != expected_pid:
        raise ReconciliationRefused(
            f"/proc PID mismatch: expected {expected_pid}, got {pid}")
    return {"pid": pid, "state": state, "ppid": ppid, "pgid": pgrp,
            "session": session, "start_ticks": start_ticks,
            "stat_sha256": sha256_bytes(raw)}


def read_proc_stat(proc_root: Path, pid: int) -> dict[str, Any]:
    """Read one stat file without following symlinks, with explicit absence."""
    path = Path(proc_root) / str(int(pid)) / "stat"
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        return {"pid": int(pid), "present": False, "errno": "ENOENT",
                "state": None, "start_ticks": None, "stat_sha256": None}
    except OSError as error:
        return {"pid": int(pid), "present": False,
                "errno": errno.errorcode.get(error.errno, str(error.errno)),
                "state": None, "start_ticks": None, "stat_sha256": None}
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            return {"pid": int(pid), "present": False, "errno": "NOT_REGULAR",
                    "state": None, "start_ticks": None, "stat_sha256": None}
        chunks: list[bytes] = []
        while True:
            block = os.read(fd, 65536)
            if not block:
                break
            chunks.append(block)
        raw = b"".join(chunks)
        after = os.fstat(fd)
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != \
                (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            return {"pid": int(pid), "present": False, "errno": "CHANGED",
                    "state": None, "start_ticks": None, "stat_sha256": None}
        row = _parse_proc_stat(raw, int(pid))
        row["present"] = True
        row["errno"] = None
        return row
    finally:
        os.close(fd)


def _group_members(proc_root: Path, process_group_id: int) -> tuple[list[dict[str, Any]], list[str]]:
    members: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        entries = list(Path(proc_root).iterdir())
    except OSError as error:
        return [], [f"proc_iter:{type(error).__name__}:{error}"]
    for entry in entries:
        if not entry.name.isdigit():
            continue
        row = read_proc_stat(proc_root, int(entry.name))
        if not row.get("present"):
            if row.get("errno") != "ENOENT":
                errors.append(f"pid:{entry.name}:{row.get('errno')}")
            else:
                # A disappearing row means the census was not complete.
                errors.append(f"pid:{entry.name}:vanished_during_group_scan")
            continue
        if row.get("pgid") == int(process_group_id):
            members.append({key: row[key] for key in
                            ("pid", "state", "ppid", "pgid", "session",
                             "start_ticks", "stat_sha256")})
    members.sort(key=lambda item: item["pid"])
    return members, errors


def capture_sample(binding: Mapping[str, Any], proc_root: Path = Path("/proc")) -> dict[str, Any]:
    """Capture one read-only qualified-host process census."""
    host = socket.gethostname()
    boot_id = _proc_boot_id(Path(proc_root))
    pid_namespace = _proc_pid_namespace(Path(proc_root))
    caller_euid = os.geteuid()
    _require(caller_euid == 0,
             "fresh072 liveness capture requires a qualified root caller")
    targets = {
        "launcher": int(binding["launcher_pid"]),
        "child": int(binding["child_pid"]),
        "group_leader": int(binding["group_leader_pid"]),
    }
    rows = {name: read_proc_stat(Path(proc_root), pid)
            for name, pid in targets.items()}
    members, errors = _group_members(Path(proc_root), int(binding["process_group_id"]))
    historical = binding.get("historical_pid_provenance", {})
    for name, row in rows.items():
        row["historical_identity"] = historical.get(name)
    return {
        "schema": SAMPLE_SCHEMA,
        "captured_at_utc": now_utc(),
        "probe_status": "qualified_host_namespace",
        "host": {"hostname": host, "boot_id": boot_id},
        "qualification": {
            "root_caller": True,
            "caller_euid": caller_euid,
            "pid_namespace": pid_namespace,
            "proc_root": str(Path(proc_root)),
        },
        "targets": rows,
        "process_group": {"id": int(binding["process_group_id"]),
                           "members": members,
                           "scan_complete": not errors,
                           "scan_errors": errors},
        "pid_reuse_guard": ABSENCE_GUARD,
        "source": "read-only /proc/<pid>/stat and complete numeric /proc census",
    }


def capture_two_samples(binding: Mapping[str, Any], proc_root: Path = Path("/proc"),
                        interval_seconds: float = 1.0,
                        sleep_fn: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    if interval_seconds < 0:
        raise ValueError("interval_seconds must be non-negative")
    first = capture_sample(binding, proc_root)
    sleep_fn(interval_seconds)
    second = capture_sample(binding, proc_root)
    first_q = first["qualification"]
    second_q = second["qualification"]
    same_namespace = (
        first_q.get("pid_namespace") == second_q.get("pid_namespace") and
        first["host"] == second["host"] and
        first_q.get("root_caller") is True and
        second_q.get("root_caller") is True and
        first_q.get("caller_euid") == 0 and
        second_q.get("caller_euid") == 0
    )
    return {"schema": SAMPLE_SCHEMA, "samples": [first, second],
            "same_process_namespace": same_namespace,
            "fresh_probe": {"mode": "two_sequential_captures",
                            "in_lock_eligible": True,
                            "interval_seconds": interval_seconds}}


def validate_cpu_binding(binding: Mapping[str, Any], reservation: Mapping[str, Any]) -> None:
    _require(binding.get("reservation_id") == reservation.get("id"),
             "reservation id does not match the binding")
    _require(binding.get("reservation_sha256") == canonical_sha256(reservation),
             "reservation canonical hash does not match the ledger row")
    _require(reservation.get("kind") == "cpu" and
             reservation.get("cpu_task_kind") == "conversion",
             "only CPU conversion reservations may be reconciled")
    _require(float(reservation.get("gpu_seconds", 0)) == 0.0,
             "GPU reconciliation is prohibited")
    _require(not reservation.get("gpu_uuid") and "gpu_index" not in reservation,
             "GPU identity is forbidden for a CPU reconciliation")
    _require(reservation.get("host") == binding.get("reservation_host"),
             "reservation host does not match binding")
    _require(reservation.get("launcher_pid") == binding.get("launcher_pid"),
             "reservation launcher PID does not match binding")
    _require(isinstance(reservation.get("cpu_core_seconds"), (int, float)) and
             reservation["cpu_core_seconds"] > 0,
             "original reserved CPU upper bound is missing or zero")
    for key in ("launcher_pid", "child_pid", "group_leader_pid", "process_group_id"):
        _require(isinstance(binding.get(key), int) and binding[key] > 0,
                 f"exact process identity is missing: {key}")
    _require("pid_anchors" not in binding,
             "fresh072 forbids fabricated historical PID anchors")
    _require(binding.get("process_group_id") == binding.get("child_pid") ==
             binding.get("group_leader_pid"),
             "runtime start_new_session process-group identity is not exact")
    runtime_identity = binding.get("runtime_start_new_session")
    _require(isinstance(runtime_identity, Mapping) and
             runtime_identity.get("enabled") is True and
             runtime_identity.get("group_leader_is_child") is True,
             "runtime start_new_session provenance is missing")
    historical = binding.get("historical_pid_provenance")
    _require(isinstance(historical, Mapping),
             "historical PID provenance is missing")
    for name in TARGETS:
        identity = historical.get(name)
        _require(isinstance(identity, Mapping) and
                 isinstance(identity.get("pid"), int) and
                 identity.get("pid") > 0 and
                 identity.get("start_ticks") is None and
                 identity.get("start_ticks_status") == UNKNOWN_START_TICKS and
                 isinstance(identity.get("source"), str) and identity["source"],
                 f"explicit unknown historical start_ticks provenance is missing: {name}")
        _require(identity["pid"] == binding[f"{name}_pid"],
                 f"historical PID provenance does not match binding: {name}")


def validate_receipt_identity(receipt_path: Path, binding: Mapping[str, Any]) -> None:
    """Bind the recorded child PID without reading any numerical payload."""
    raw = _read_regular_bytes(Path(receipt_path))
    try:
        receipt = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReconciliationRefused("original conversion receipt is not valid JSON") from error
    _require(isinstance(receipt, Mapping),
             "original conversion receipt must be a JSON object")
    _require(receipt.get("pid") == binding.get("child_pid"),
             "receipt child PID does not match the exact binding")
    _require(receipt.get("status") == "running" and receipt.get("returncode") is None,
             "receipt is no longer in the bound unknown lifecycle state")


def verify_dead_twice(binding: Mapping[str, Any], evidence: Mapping[str, Any]) -> dict[str, Any]:
    _require(evidence.get("schema") == SAMPLE_SCHEMA,
             "unexpected liveness evidence schema")
    samples = evidence.get("samples")
    _require(isinstance(samples, list) and len(samples) >= 2,
             "two independent /proc samples are required")
    _require(evidence.get("same_process_namespace") is True,
             "samples are not bound to one process namespace")
    expected_host = binding["reservation_host"]
    expected_group = int(binding["process_group_id"])
    identity = binding.get("historical_pid_provenance")
    _require(isinstance(identity, Mapping),
             "historical PID provenance is missing")
    sample_namespace: tuple[str, str, str] | None = None
    for index, sample in enumerate(samples[:2]):
        _require(sample.get("schema") == SAMPLE_SCHEMA,
                 f"sample {index} schema mismatch")
        _require(sample.get("probe_status") == "qualified_host_namespace",
                 f"sample {index} is not a qualified host probe")
        host = sample.get("host", {})
        _require(host.get("hostname") == expected_host,
                 f"sample {index} hostname does not match reservation host")
        boot_id = host.get("boot_id")
        _require(isinstance(boot_id, str) and boot_id,
                 f"sample {index} boot id missing")
        qualification = sample.get("qualification", {})
        _require(isinstance(qualification, Mapping) and
                 qualification.get("root_caller") is True and
                 qualification.get("caller_euid") == 0 and
                 isinstance(qualification.get("pid_namespace"), str) and
                 qualification.get("pid_namespace"),
                 f"sample {index} lacks qualified root/PID-namespace proof")
        current_namespace = (host["hostname"], boot_id,
                             qualification["pid_namespace"])
        if sample_namespace is None:
            sample_namespace = current_namespace
        _require(current_namespace == sample_namespace,
                 f"sample {index} changed host, boot, or PID namespace")
        for name in TARGETS:
            row = sample.get("targets", {}).get(name)
            _require(isinstance(row, Mapping),
                     f"sample {index} target missing: {name}")
            _require(row.get("pid") == binding[f"{name}_pid"],
                     f"sample {index} target PID mismatch: {name}")
            _require(row.get("present") is False and row.get("errno") == "ENOENT",
                     f"sample {index} does not prove dead {name}")
            _require(row.get("start_ticks") is None and row.get("state") is None,
                     f"sample {index} has ambiguous {name} identity")
            _require(row.get("historical_identity") == identity[name],
                     f"sample {index} lacks explicit unknown {name} PID provenance")
        group = sample.get("process_group", {})
        _require(group.get("id") == expected_group and
                 group.get("scan_complete") is True,
                 f"sample {index} process-group scan is incomplete")
        _require(group.get("scan_errors") == [],
                 f"sample {index} process-group scan has errors")
        _require(group.get("members") == [],
                 f"sample {index} process group is not empty")
        _require(sample.get("pid_reuse_guard") ==
                 ABSENCE_GUARD,
                 f"sample {index} lacks bounded absence guard")
    return {"samples_verified": 2, "process_group_id": expected_group,
            "host": expected_host, "boot_id": samples[0]["host"]["boot_id"],
            "pid_namespace": samples[0]["qualification"]["pid_namespace"],
            "historical_start_ticks": "unknown_and_null",
            "guard": ABSENCE_GUARD}


def _ledger_without_target(ledger: Mapping[str, Any], reservation_id: str) -> dict[str, Any]:
    copy = json.loads(json.dumps(ledger, allow_nan=False))
    copy["reservations"] = [row for row in copy.get("reservations", [])
                             if row.get("id") != reservation_id]
    copy["attempts"] = [row for row in copy.get("attempts", [])
                         if row.get("id") != reservation_id]
    copy["charges"] = [row for row in copy.get("charges", [])
                        if row.get("id") != reservation_id]
    return copy


def _other_ledger_bytes_equal(before: Mapping[str, Any], after: Mapping[str, Any],
                             reservation_id: str) -> None:
    """Check that only the target reservation/attempt/charge changed."""
    _require(canonical_bytes(_ledger_without_target(before, reservation_id)) ==
             canonical_bytes(_ledger_without_target(after, reservation_id)),
             "reconciliation would alter non-target ledger state")


def _find_target(ledger: Mapping[str, Any], reservation_id: str) -> Mapping[str, Any] | None:
    matches = [row for row in ledger.get("reservations", [])
               if row.get("id") == reservation_id]
    _require(len(matches) <= 1, "duplicate target reservations are unsafe")
    return matches[0] if matches else None


def _find_charge(ledger: Mapping[str, Any], reservation_id: str,
                 txid: str) -> Mapping[str, Any] | None:
    matches = [row for row in ledger.get("charges", [])
               if row.get("id") == reservation_id or
               row.get("reconciliation_txid") == txid]
    _require(len(matches) <= 1, "duplicate target charges are unsafe")
    return matches[0] if matches else None


def transaction_id(binding: Mapping[str, Any]) -> str:
    seed = {key: binding[key] for key in
            ("reservation_id", "reservation_sha256", "receipt_sha256")}
    return "ds02-reconcile-" + canonical_sha256(seed)[:32]


def _journal_path(data_root: Path, txid: str) -> Path:
    return Path(data_root) / "runtime" / "reconciliation-journal" / f"{txid}.json"


def _journal_payload(txid: str, state: str, **values: Any) -> dict[str, Any]:
    result = {"schema": JOURNAL_SCHEMA, "transaction_id": txid,
              "state": state, "updated_at_utc": now_utc()}
    result.update(values)
    return result


def apply_reconciliation(*, runtime_module: Any, data_root: Path,
                         binding: Mapping[str, Any], evidence: Mapping[str, Any] | None,
                         sidecar_dir: Path, tool_status: int,
                         enable: bool = False,
                         authorization_token: str | None = None,
                         proc_root: Path = Path("/proc"),
                         probe_interval_seconds: float = 1.0,
                         sleep_fn: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """Apply one Root-approved reconciliation; closed unless explicitly enabled.

    ``enable`` and the token are intentionally separate from the package CLI.
    A Root integration caller must provide both after reviewing the immutable
    source. Liveness evidence is deliberately not accepted as an argument:
    the two qualified /proc probes happen inside the runtime ledger lock after
    the exact reservation is found and immediately before mutation. This
    function never launches, signals, adopts, or changes a GPU process.
    """
    if not enable or authorization_token != AUTHORIZATION_TOKEN:
        raise ReconciliationRefused("fresh072 application gate is disabled")
    _require(evidence is None,
             "caller-supplied liveness evidence is stale; apply requires an in-lock recapture")
    _require(tool_status == 143,
             "tool status must be recorded separately as 143")
    data_root = Path(data_root)
    reservation_id = str(binding.get("reservation_id", ""))
    txid = transaction_id(binding)
    receipt_path = Path(str(binding["receipt_path"]))
    receipt_sha = str(binding["receipt_sha256"])
    sidecar_path = Path(sidecar_dir) / f"original-receipt-{txid}.json"
    preserved = preserve_receipt_sidecar(receipt_path, sidecar_path, receipt_sha)
    validate_receipt_identity(Path(preserved["path"]), binding)
    journal_path = _journal_path(data_root, txid)
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    journal = _journal_payload(
        txid, "prepared", reservation_id=reservation_id,
        reservation_sha256=binding["reservation_sha256"],
        original_receipt=preserved, tool_status=143,
        child_returncode=None, os_exit_zero=False,
        status=CHARGE_STATUS,
        liveness={"mode": "in_lock_double_probe_required",
                  "historical_start_ticks": "unknown_and_null"},
        source_runtime_sha256=binding.get("runtime_v2_sha256"),
    )
    # Prepared journal is durable before the ledger lock/mutation. Replaying a
    # crash after ledger commit finds the idempotent charge below.
    _runtime_atomic_json(runtime_module, journal_path, journal)

    verified_liveness: dict[str, Any] | None = None
    with runtime_module.ledger_locked(data_root) as ledger:
        row = _find_target(ledger, reservation_id)
        existing_charge = _find_charge(ledger, reservation_id, txid)
        if existing_charge is not None:
            # A committed reconciliation must have consumed the exact
            # reservation.  Treat a charge+reservation coexistence as a
            # ledger-integrity failure instead of accepting an ambiguous
            # replay state or silently charging twice later.
            _require(row is None,
                     "reconciliation charge and reservation coexist")
            _require(existing_charge.get("reconciliation_txid") == txid,
                     "existing target charge has a different transaction identity")
            _require(existing_charge.get("reservation_sha256") ==
                     binding["reservation_sha256"],
                     "existing charge does not match the exact reservation")
            result = {"status": "already_applied", "transaction_id": txid,
                      "reservation_id": reservation_id, "charge": dict(existing_charge),
                      "sidecar": preserved,
                      "fresh_liveness": "not_reprobed_already_applied"}
        else:
            _require(row is not None,
                     "exact reservation is absent; refusing adoption")
            validate_cpu_binding(binding, row)
            target_attempts = [item for item in ledger.get("attempts", [])
                               if item.get("id") == reservation_id]
            _require(len(target_attempts) == 1,
                     "exact reserved attempt row is missing")
            target_attempt = target_attempts[0]
            _require(target_attempt.get("status") in {"reserved", "running"},
                     "attempt is already terminal with an unknown state")
            # The process census is intentionally inside the runtime lock and
            # immediately precedes the in-memory ledger mutation. A stale
            # caller document can therefore never authorize this branch.
            fresh_evidence = capture_two_samples(
                binding, Path(proc_root), interval_seconds=probe_interval_seconds,
                sleep_fn=sleep_fn)
            verified_liveness = verify_dead_twice(binding, fresh_evidence)
            before = json.loads(json.dumps(ledger, allow_nan=False))
            charge = {
                "id": reservation_id,
                "gpu_seconds": 0.0,
                "cpu_core_seconds": row["cpu_core_seconds"],
                "new_storage_bytes": row.get("new_storage_bytes", 0),
                "status": CHARGE_STATUS,
                "finished_at_utc": now_utc(),
                "reconciliation_txid": txid,
                "reservation_sha256": binding["reservation_sha256"],
                "original_receipt_sha256": receipt_sha,
                "original_receipt_sidecar": preserved["path"],
                "tool_status": 143,
                "child_returncode": None,
                "os_exit_zero": False,
                "usage_semantics":
                    "full_original_reserved_cpu_core_seconds_conservative_upper_bound",
            }
            ledger["reservations"] = [item for item in ledger["reservations"]
                                       if item.get("id") != reservation_id]
            ledger["charges"].append(charge)
            target_attempt.update({
                "status": CHARGE_STATUS,
                "finished_at_utc": charge["finished_at_utc"],
                "terminal_receipt": preserved["path"],
                "terminal_receipt_sha256": receipt_sha,
                "reconciliation_txid": txid,
                "recovered": True,
                "returncode": None,
                "tool_status": 143,
                "os_exit_zero": False,
            })
            _other_ledger_bytes_equal(before, ledger, reservation_id)
            result = {"status": "applied", "transaction_id": txid,
                      "reservation_id": reservation_id, "charge": charge,
                      "sidecar": preserved,
                      "fresh_liveness": verified_liveness}
    # Runtime context has now atomically published the ledger. The journal
    # commit is a second durable marker; replay is safe if a crash occurred in
    # this narrow interval.
    _fsync_directory(data_root / "runtime")
    committed = dict(journal)
    committed.update({"state": "committed", "committed_at_utc": now_utc(),
                      "result": result})
    _runtime_atomic_json(runtime_module, journal_path, committed)
    return result


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    raise SystemExit(
        "fresh072 CLI is disabled; Root must review and import apply_reconciliation"
    )


if __name__ == "__main__":
    raise SystemExit(main())
