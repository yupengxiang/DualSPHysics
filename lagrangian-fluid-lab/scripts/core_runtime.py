#!/usr/bin/env python3
"""Durable, evidence-preserving local/SSH worker queue for the adopted Core plan.

Only the coordinator writes SQLite. Workers write immutable attempt receipts.
Execution success is deliberately NOT numerical/material qualification.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import resource
import shlex
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
import uuid

LAB = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = LAB / "campaigns/core-v1/runtime"
ACTIVE = ("reserved", "launching", "running", "attention")
TERMINAL = ("succeeded", "failed", "cancelled")
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$")
_UNSET = object()
EXECUTION_RECEIPT_SCHEMA = "core.execution_receipt.v1"
RECOVERY_ATTENTION_SCHEMA = "core.reconciliation_attention.v1"


def queue_priority(job):
    # Short dependency-unblocking canaries precede long batch cells. This never
    # preempts a live worker or bypasses resource/scientific prerequisites.
    category = job['spec'].get('category', '')
    rank = {'repair_canary': 30, 'initial_state_repair_canary': 30,
            'reference_canary': 30, 'qualification_canary': 30, 'static_hold_canary': 30,
            'f2_dynamic_full_cup_closed_catchment_dbc_horizon_extension_canary': 30,
            'training_canary': 25, 'matched_stack_canary': 25,
            'scientific_qualification_gate': 20,
            'material_qualification_diagnostic': 20,
            'model_profile': 15}.get(category, 0)
    return (-rank, job.get('created', 0), job['job_id'])


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    with temporary.open("w") as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def proc_identity(pid):
    try:
        fields = Path(f"/proc/{int(pid)}/stat").read_text().rsplit(")", 1)[1].split()
        if fields[0] == "Z":
            return None
        return {"pid": int(pid), "start_ticks": int(fields[19]),
                "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip()}
    except (OSError, ValueError, IndexError):
        return None


def is_alive(identity):
    return bool(identity and proc_identity(identity["pid"]) == identity)


def process_tree(pid):
    records = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
            records[int(entry.name)] = (int(fields[1]), max(0, int(fields[21])) * os.sysconf("SC_PAGE_SIZE"))
        except (OSError, ValueError, IndexError):
            pass
    selected = {int(pid)}
    while True:
        added = {p for p, (parent, _) in records.items() if parent in selected} - selected
        if not added:
            break
        selected.update(added)
    return selected, sum(records.get(p, (0, 0))[1] for p in selected)


def gpu_snapshot():
    try:
        raw = subprocess.check_output(["nvidia-smi", "--query-gpu=index,uuid,name,memory.total,memory.used,utilization.gpu",
                                       "--format=csv,noheader,nounits"], text=True, stderr=subprocess.DEVNULL, timeout=15)
        gpus = []
        for row in csv.reader(raw.splitlines()):
            index, uid, name, total, used, util = [x.strip() for x in row]
            gpus.append(dict(index=int(index), uuid=uid, name=name, total_mib=int(total), used_mib=int(used), utilization=int(util)))
        raw = subprocess.check_output(["nvidia-smi", "--query-compute-apps=gpu_uuid,pid,used_gpu_memory",
                                       "--format=csv,noheader,nounits"], text=True, stderr=subprocess.DEVNULL, timeout=15)
        processes = []
        for row in csv.reader(raw.splitlines()):
            if len(row) == 3 and row[1].strip().isdigit() and row[2].strip().isdigit():
                processes.append(dict(uuid=row[0].strip(), pid=int(row[1]), used_mib=int(row[2])))
        return gpus, processes
    except (OSError, ValueError, subprocess.SubprocessError):
        return [], []


def shared_worker_gpu_snapshot(cache_root, *, ttl_seconds=2.0):
    """One node-local GPU query per sample interval for all worker monitors.

    Admission probes remain uncached. The cache is only for sampled worker
    usage; retained peaks and live admission reservations remain authoritative.
    A flock and atomic publication prevent concurrent refresh stampedes.
    """
    root = Path(cache_root)
    root.mkdir(parents=True, exist_ok=True)
    path = root / 'worker-gpu-snapshot.json'
    boot_id = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    with (root/'worker-gpu-snapshot.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            cached = json.loads(path.read_text())
            age = time.monotonic() - cached['monotonic_sample_end']
            if (cached.get('schema') == 'core.worker_gpu_sample.v1'
                    and cached.get('boot_id') == boot_id
                    and 0 <= age < ttl_seconds):
                return cached['gpus'], cached['processes']
        except (OSError, ValueError, KeyError, TypeError):
            pass
        gpus, processes = gpu_snapshot()
        atomic_json(path, {'schema': 'core.worker_gpu_sample.v1',
                          'boot_id': boot_id, 'time': time.time(),
                          'monotonic_sample_end': time.monotonic(),
                          'gpus': gpus, 'processes': processes})
        return gpus, processes


def probe(path):
    memory = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, value = line.split(":", 1)
        memory[key] = int(value.split()[0]) / 1024
    gpus, processes = gpu_snapshot()
    return dict(time=time.time(), hostname=os.uname().nodename, cpu_count=os.cpu_count(),
                load1=os.getloadavg()[0], ram_total_mib=memory["MemTotal"], ram_available_mib=memory["MemAvailable"],
                disk_free_bytes=shutil.disk_usage(path).free, gpus=gpus, gpu_processes=processes)


def validate_spec(spec):
    if not SAFE_ID.fullmatch(spec.get("job_id", "")):
        raise ValueError("job_id must be a safe, nonempty identifier")
    if not isinstance(spec.get("argv"), list) or not spec["argv"] or not all(isinstance(x, str) for x in spec["argv"]):
        raise ValueError("argv must be a nonempty string array, never a shell command")
    if not Path(spec.get("cwd", "")).is_absolute():
        raise ValueError("cwd must be absolute")
    resources = spec.setdefault("resources", {})
    for key, default in (("cpu_cores", 1), ("ram_mib", 1024), ("gpu_peak_mib", 0), ("io_weight", 0)):
        value = resources.setdefault(key, default)
        if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(f"invalid {key}")
    if resources["cpu_cores"] < 1 or resources["ram_mib"] < 1:
        raise ValueError("CPU and RAM reservations must be positive")
    for item in spec.get("required_outputs", []):
        p = Path(item)
        if p.is_absolute() or ".." in p.parts:
            raise ValueError("required_outputs must be relative to the attempt directory")
        if str(p) in {"result.json", "launch.json", "heartbeat.json", "spec.json",
                       "worker.log", "worker.lock"}:
            raise ValueError("required_outputs collides with reserved worker metadata: " + str(p))
    timeout = spec.setdefault("timeout_seconds", 86400)
    if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("a positive bounded timeout is required")
    spec.setdefault("host", "ada")
    spec.setdefault("depends_on", [])
    spec.setdefault("category", "diagnostic")
    spec.setdefault("logical_id", spec["job_id"])
    spec.setdefault("attempt_role", "initial")
    canonical(spec)
    return spec


def choose_resources(spec, snapshot, active):
    """Admit against external use + owned reservations, not idle-card status."""
    request = spec["resources"]
    cpu_reserved = sum(x["spec"]["resources"]["cpu_cores"] for x in active)
    ram_reserved = sum(x["spec"]["resources"]["ram_mib"] for x in active)
    owned_rss = sum(x.get("heartbeat", {}).get("rss_mib", 0) for x in active)
    owned_io = sum(x["spec"]["resources"]["io_weight"] for x in active)
    if cpu_reserved + request["cpu_cores"] > max(1, math.floor(snapshot["cpu_count"] * .8)):
        return None
    if ram_reserved + request["ram_mib"] > snapshot["ram_available_mib"] + owned_rss - .15 * snapshot["ram_total_mib"]:
        return None
    io_capacity = snapshot.get('io_capacity', 2)
    if not isinstance(io_capacity, (int, float)) or not math.isfinite(io_capacity) or io_capacity <= 0:
        raise ValueError('host io_capacity must be positive and finite')
    if owned_io + request["io_weight"] > io_capacity:
        return None
    if snapshot["disk_free_bytes"] < spec.get("min_free_disk_bytes", 20 * 1024**3):
        return None
    if not request["gpu_peak_mib"]:
        return {"gpu_uuid": None, "reserved_gpu_mib": 0}
    candidates = []
    for gpu in snapshot["gpus"]:
        if spec.get("gpu_uuids") and gpu["uuid"] not in spec["gpu_uuids"]:
            continue
        on_card = [x for x in active if x.get("allocation", {}).get("gpu_uuid") == gpu["uuid"]]
        owned_pids = {p for job in on_card for p in job.get("heartbeat", {}).get("process_ids", [])}
        owned_actual = sum(x["used_mib"] for x in snapshot.get("gpu_processes", []) if x["uuid"] == gpu["uuid"] and x["pid"] in owned_pids)
        external = max(0, gpu["used_mib"] - owned_actual)
        reserved = 0
        for job in on_card:
            heartbeat = job.get("heartbeat", {})
            pids = set(heartbeat.get("process_ids", []))
            actual = sum(p["used_mib"] for p in snapshot.get("gpu_processes", [])
                         if p["uuid"] == gpu["uuid"] and p["pid"] in pids)
            measured = max(actual, heartbeat.get("peak_gpu_mib", 0), heartbeat.get("gpu_mib", 0))
            reserved += max(job["allocation"]["reserved_gpu_mib"], math.ceil(1.2 * measured))
        needed = math.ceil(1.2 * request["gpu_peak_mib"])
        headroom = gpu["total_mib"] - max(4096, .1 * gpu["total_mib"]) - external - reserved - needed
        if headroom >= 0:
            # Spread first, then admit additional colocated jobs without a count cap.
            candidates.append((reserved + external, gpu["index"], gpu["uuid"], needed))
    if not candidates:
        return None
    _, index, uid, needed = min(candidates)
    return {"gpu_uuid": uid, "gpu_index": index, "reserved_gpu_mib": needed}


def interval_union_seconds(intervals):
    total = 0.0
    end = None
    for start, stop in sorted(intervals):
        if stop < start:
            raise ValueError("negative resource interval")
        total += max(0.0, stop - max(start, end if end is not None else start))
        end = max(stop, end if end is not None else stop)
    return total


def usage_summary(jobs):
    per_device = {}
    process_hours = cpu_seconds = physical_bytes = 0.0
    unique = {}
    for job in jobs:
        result = job.get("result", {})
        if not result.get("schema") == "core.execution_receipt.v1":
            continue
        usage = result["usage"]
        process_hours += usage.get("gpu_process_reservation_hours", 0)
        cpu_seconds += usage.get("cpu_seconds_children", 0)
        gpu = result.get("allocation", {}).get("gpu_uuid")
        if gpu:
            # A scheduler-selected spec retains its logical host declaration;
            # allocation._host is the concrete device owner used for launch.
            # Keep the union accounting keyed by that effective host so
            # receipts remain correct after coordinator restart or relocation.
            host_name = (job.get("allocation") or {}).get("_host") or job["spec"].get("host")
            per_device.setdefault((host_name, gpu), []).append((result["started"], result["finished"]))
        for item in result.get("artifact_index", result.get("outputs", [])):
            physical_bytes += item["bytes"]
            unique[item["sha256"]] = item["bytes"]
    return {"completed_attempts_gpu_process_reservation_hours": process_hours,
            "completed_attempts_gpu_device_reservation_union_hours": sum(interval_union_seconds(v) for v in per_device.values()) / 3600,
            "cpu_children_core_hours": cpu_seconds / 3600,
            "indexed_replica_bytes": int(physical_bytes), "indexed_unique_content_bytes": sum(unique.values()),
            "coverage": "completed receipts only; running usage and historical L2 remain separate",
            "gpu_semantics": "allocated worker wall-time, includes conversion; not an inference of kernel-active time"}


def concurrency_decision(measurements):
    """Workload-specific measured throughput; never equate VRAM headroom to speed."""
    rows = sorted(measurements, key=lambda x: x["concurrency"])
    if any(x["oom"] or x.get("failed", 0) for x in rows[-1:]):
        return {"increase": False, "reason": "failure_or_oom"}
    if len(rows) < 3:
        return {"increase": True, "reason": "need_two_increment_measurements"}
    gains = [rows[i]["qualified_units_per_hour"] / max(rows[i - 1]["qualified_units_per_hour"], 1e-12) - 1 for i in (-2, -1)]
    return {"increase": not all(gain < .1 for gain in gains), "last_two_relative_gains": gains,
            "reason": "measured_throughput; resource_admission_still_required"}


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root / "queue.sqlite3", timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY, spec TEXT NOT NULL, spec_hash TEXT NOT NULL,
            status TEXT NOT NULL, attempt_id TEXT, allocation TEXT, attempt_dir TEXT,
            heartbeat TEXT, result TEXT, created REAL NOT NULL, updated REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, time REAL NOT NULL,
            job_id TEXT, event TEXT NOT NULL, payload TEXT NOT NULL);
        """)
        self.db.commit()

    def event(self, job_id, event, payload):
        self.db.execute("INSERT INTO events(time,job_id,event,payload) VALUES(?,?,?,?)",
                        (time.time(), job_id, event, canonical(payload)))

    def submit(self, spec):
        spec = validate_spec(json.loads(canonical(spec)))
        encoded = canonical(spec)
        sha = hashlib.sha256(encoded.encode()).hexdigest()
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute("SELECT spec_hash FROM jobs WHERE job_id=?", (spec["job_id"],)).fetchone()
            if row:
                if row[0] != sha:
                    raise ValueError("job_id already exists with different inputs; use a new attempt ID")
                return False
            now = time.time()
            self.db.execute("INSERT INTO jobs(job_id,spec,spec_hash,status,created,updated) VALUES(?,?,?,'queued',?,?)",
                            (spec["job_id"], encoded, sha, now, now))
            self.event(spec["job_id"], "submitted", {"spec_hash": sha})
        return True

    def jobs(self):
        result = []
        for row in self.db.execute("SELECT * FROM jobs ORDER BY created,job_id"):
            item = dict(row)
            for key in ("spec", "allocation", "heartbeat", "result"):
                item[key] = json.loads(item[key]) if item[key] else {}
            result.append(item)
        return result

    def update(self, job_id, status, **fields):
        assignments = ["status=?", "updated=?"]
        values = [status, time.time()]
        for key, value in fields.items():
            if key not in ("attempt_id", "allocation", "attempt_dir", "heartbeat", "result"):
                raise ValueError(key)
            assignments.append(key + "=?")
            values.append(canonical(value) if key in ("allocation", "heartbeat", "result") else value)
        with self.db:
            self.db.execute("UPDATE jobs SET " + ",".join(assignments) + " WHERE job_id=?", values + [job_id])
            if status != "running" or "result" in fields:
                self.event(job_id, status, fields)

    @staticmethod
    def _json_value(raw):
        if not raw:
            return {}
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _where_attempt(where, values, attempt_id):
        if attempt_id is _UNSET:
            return
        if attempt_id is None:
            where.append("attempt_id IS NULL")
        else:
            where.append("attempt_id=?")
            values.append(attempt_id)

    def cas_update(self, job_id, status, *, expected_status, expected_attempt_id=_UNSET,
                   expected_job_id=None, event_name=None, **fields):
        """Atomically update one job only if its observed identity is unchanged.

        ``update`` predates the coordinator recovery path and intentionally keeps
        its unconditional behavior.  New lifecycle code uses this helper so a
        stale coordinator snapshot cannot overwrite a newer attempt.  A false
        return means the compare-and-set predicate did not match; no event or
        field is written.
        """
        if expected_job_id is not None and expected_job_id != job_id:
            return False
        assignments = ["status=?", "updated=?"]
        values = [status, time.time()]
        event_fields = {}
        for key, value in fields.items():
            if key not in ("attempt_id", "allocation", "attempt_dir", "heartbeat", "result"):
                raise ValueError(key)
            assignments.append(key + "=?")
            values.append(canonical(value) if key in ("allocation", "heartbeat", "result") else value)
            event_fields[key] = value
        where = ["job_id=?", "status=?"]
        where_values = [job_id, expected_status]
        self._where_attempt(where, where_values, expected_attempt_id)
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            cursor = self.db.execute(
                "UPDATE jobs SET " + ",".join(assignments) + " WHERE " + " AND ".join(where),
                values + where_values,
            )
            if cursor.rowcount != 1:
                return False
            if status != "running" or "result" in fields:
                self.event(job_id, event_name or status, event_fields)
        return True

    def transition(self, job_id, status, *, expected_status, expected_attempt_id=_UNSET,
                   expected_job_id=None, event_name=None, **fields):
        """Named alias for the public lifecycle CAS operation."""
        return self.cas_update(
            job_id,
            status,
            expected_status=expected_status,
            expected_attempt_id=expected_attempt_id,
            expected_job_id=expected_job_id,
            event_name=event_name,
            **fields,
        )

    @staticmethod
    def _receipt_hash(receipt):
        try:
            return hashlib.sha256(canonical(receipt).encode()).hexdigest()
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _receipt_errors(receipt, job_id, attempt_id):
        errors = []
        if not isinstance(receipt, dict):
            return ["receipt_not_object"]
        if receipt.get("schema") != EXECUTION_RECEIPT_SCHEMA:
            errors.append("invalid_schema")
        if receipt.get("job_id") != job_id:
            errors.append("job_id_mismatch")
        if attempt_id is None or receipt.get("attempt_id") != attempt_id:
            errors.append("attempt_id_mismatch")
        if receipt.get("execution_status") not in ("succeeded", "failed"):
            errors.append("invalid_execution_status")
        return errors

    @staticmethod
    def _safe_observed(observed):
        try:
            canonical(observed)
            return observed
        except (TypeError, ValueError):
            return {"type": type(observed).__name__}

    @staticmethod
    def _receipt_is_valid(receipt, job_id, attempt_id):
        return isinstance(receipt, dict) and not Store._receipt_errors(receipt, job_id, attempt_id)

    @staticmethod
    def _locked_where(row):
        where = ["job_id=?", "status=?"]
        values = [row["job_id"], row["status"]]
        Store._where_attempt(where, values, row["attempt_id"])
        return where, values

    def register_recovery(self, job_id, *, expected_status, expected_attempt_id,
                          reason, observed=None, heartbeat=None, expected_job_id=None):
        """Record an uncertain observation without relaunching or overwriting a receipt."""
        if expected_job_id is not None and expected_job_id != job_id:
            return {"action": "rejected", "reason": "expected_job_id_mismatch"}
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute(
                "SELECT job_id,status,attempt_id,heartbeat,result FROM jobs WHERE job_id=?",
                (job_id,),
            ).fetchone()
            if row is None:
                raise KeyError(job_id)
            if row["status"] != expected_status or row["attempt_id"] != expected_attempt_id:
                self.db.rollback()
                return {"action": "cas_lost", "reason": "job_identity_changed"}
            current = self._json_value(row["result"])
            if self._receipt_is_valid(current, job_id, row["attempt_id"]):
                self.db.rollback()
                return {"action": "noop", "reason": "receipt_already_finalized"}
            if (row["status"] == "attention" and current.get("schema") == RECOVERY_ATTENTION_SCHEMA
                    and current.get("reason") == reason):
                self.db.rollback()
                return {"action": "noop", "reason": "recovery_already_registered"}
            diagnostic = {
                "schema": RECOVERY_ATTENTION_SCHEMA,
                "reason": reason,
                "job_id": job_id,
                "attempt_id": row["attempt_id"],
                "observed": self._safe_observed(observed),
            }
            fields = {"result": diagnostic}
            if heartbeat is not None:
                fields["heartbeat"] = heartbeat
            assignments = ["status=?", "updated=?"]
            values = ["attention", time.time()]
            for key, value in fields.items():
                assignments.append(key + "=?")
                values.append(canonical(value))
            where, where_values = self._locked_where(row)
            cursor = self.db.execute(
                "UPDATE jobs SET " + ",".join(assignments) + " WHERE " + " AND ".join(where),
                values + where_values,
            )
            if cursor.rowcount != 1:
                self.db.rollback()
                return {"action": "cas_lost", "reason": "job_identity_changed"}
            self.event(job_id, "recovery_registered", diagnostic)
            self.db.commit()
            return {"action": "attention", "reason": reason}
        except Exception:
            self.db.rollback()
            raise

    def finalize_receipt(self, job_id, receipt, *, expected_attempt_id=_UNSET,
                         heartbeat=None, expected_job_id=None):
        """Validate and atomically accept one execution receipt.

        The stored execution receipt is the billing identity for a job.  A
        duplicate byte-for-byte receipt is a no-op.  A different receipt for
        the same job/attempt never replaces the stored receipt; it moves the
        job to ``attention`` and retains the original result so accounting can
        count at most one completion.
        """
        if expected_job_id is not None and expected_job_id != job_id:
            return {"action": "rejected", "reason": "expected_job_id_mismatch"}
        incoming_hash = self._receipt_hash(receipt)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute(
                "SELECT job_id,status,attempt_id,heartbeat,result FROM jobs WHERE job_id=?",
                (job_id,),
            ).fetchone()
            if row is None:
                raise KeyError(job_id)
            if expected_attempt_id is not _UNSET and row["attempt_id"] != expected_attempt_id:
                self.db.rollback()
                return {"action": "cas_lost", "reason": "attempt_identity_changed"}
            current = self._json_value(row["result"])
            current_valid = self._receipt_is_valid(current, job_id, row["attempt_id"])
            if current_valid:
                current_hash = self._receipt_hash(current)
                if current_hash == incoming_hash and canonical(current) == canonical(receipt):
                    self.db.rollback()
                    return {"action": "noop", "reason": "duplicate_receipt", "receipt_sha256": incoming_hash}
                metadata = self._json_value(row["heartbeat"])
                reconciliation = metadata.get("reconciliation", {})
                if reconciliation.get("conflicting_receipt_sha256") == incoming_hash:
                    self.db.rollback()
                    return {"action": "noop", "reason": "duplicate_conflicting_receipt"}
                metadata["reconciliation"] = {
                    "reason": "conflicting_receipt",
                    "conflicting_receipt_sha256": incoming_hash,
                    "original_receipt_sha256": current_hash,
                }
                assignments = ["status=?", "updated=?", "heartbeat=?"]
                values = ["attention", time.time(), canonical(metadata)]
                where, where_values = self._locked_where(row)
                cursor = self.db.execute(
                    "UPDATE jobs SET " + ",".join(assignments) + " WHERE " + " AND ".join(where),
                    values + where_values,
                )
                if cursor.rowcount != 1:
                    self.db.rollback()
                    return {"action": "cas_lost", "reason": "job_identity_changed"}
                self.event(job_id, "receipt_conflict", {
                    "original_receipt_sha256": current_hash,
                    "conflicting_receipt_sha256": incoming_hash,
                })
                self.db.commit()
                return {"action": "attention", "reason": "conflicting_receipt"}

            errors = self._receipt_errors(receipt, job_id, row["attempt_id"])
            if errors:
                if (row["status"] == "attention" and current.get("schema") == RECOVERY_ATTENTION_SCHEMA
                        and current.get("reason") == "invalid_execution_receipt"
                        and current.get("receipt_sha256") == incoming_hash
                        and current.get("errors") == errors):
                    self.db.rollback()
                    return {"action": "noop", "reason": "duplicate_invalid_receipt"}
                if row["status"] not in ACTIVE:
                    self.db.rollback()
                    return {"action": "rejected", "reason": "job_not_active"}
                diagnostic = {
                    "schema": RECOVERY_ATTENTION_SCHEMA,
                    "reason": "invalid_execution_receipt",
                    "job_id": job_id,
                    "attempt_id": row["attempt_id"],
                    "receipt_sha256": incoming_hash,
                    "errors": errors,
                }
                assignments = ["status=?", "updated=?", "result=?"]
                values = ["attention", time.time(), canonical(diagnostic)]
                if heartbeat is not None:
                    assignments.append("heartbeat=?")
                    values.append(canonical(heartbeat))
                where, where_values = self._locked_where(row)
                cursor = self.db.execute(
                    "UPDATE jobs SET " + ",".join(assignments) + " WHERE " + " AND ".join(where),
                    values + where_values,
                )
                if cursor.rowcount != 1:
                    self.db.rollback()
                    return {"action": "cas_lost", "reason": "job_identity_changed"}
                self.event(job_id, "recovery_registered", diagnostic)
                self.db.commit()
                return {"action": "attention", "reason": "invalid_execution_receipt"}

            if row["status"] not in ACTIVE:
                self.db.rollback()
                return {"action": "rejected", "reason": "job_not_active"}
            assignments = ["status=?", "updated=?", "result=?"]
            values = [receipt["execution_status"], time.time(), canonical(receipt)]
            if heartbeat is not None:
                assignments.append("heartbeat=?")
                values.append(canonical(heartbeat))
            where, where_values = self._locked_where(row)
            cursor = self.db.execute(
                "UPDATE jobs SET " + ",".join(assignments) + " WHERE " + " AND ".join(where),
                values + where_values,
            )
            if cursor.rowcount != 1:
                self.db.rollback()
                return {"action": "cas_lost", "reason": "job_identity_changed"}
            self.event(job_id, receipt["execution_status"], {"result": receipt})
            self.db.commit()
            return {"action": "accepted", "receipt_sha256": incoming_hash}
        except Exception:
            self.db.rollback()
            raise


def default_hosts(lab):
    lab = str(Path(lab).resolve())
    return {"ada": {"ssh": None, "lab": lab, "python": lab + "/.venv/bin/python"},
            "h200": {"ssh": "h200-deepdebris", "lab": "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab",
                     "python": "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python"}}


def host_run(host, argv, **kwargs):
    if host.get("ssh"):
        argv = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host["ssh"], shlex.join(list(map(str, argv)))]
    return subprocess.run(argv, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60, **kwargs)


def deploy_runtime(host):
    path = Path(__file__).resolve()
    sha = digest(path)
    remote = Path(host["lab"]) / "campaigns/core-v1/runtime/bootstrap" / sha / "core_runtime.py"
    if not host.get("ssh"):
        remote.parent.mkdir(parents=True, exist_ok=True)
        if not remote.exists():
            shutil.copyfile(path, remote)
        return str(remote)
    host_run(host, ["mkdir", "-p", str(remote.parent)])
    subprocess.run(["scp", "-q", str(path), host["ssh"] + ":" + str(remote)], check=True, timeout=60)
    actual = host_run(host, ["sha256sum", str(remote)]).stdout.split()[0]
    if actual != sha:
        raise RuntimeError("runtime transfer hash mismatch")
    return str(remote)


def collect_attempt(path):
    path = Path(path)
    result = {}
    receipt_errors = []
    for name in ("launch", "heartbeat", "result"):
        try:
            value = json.loads((path / (name + ".json")).read_text())
            if not isinstance(value, dict):
                receipt_errors.append({"file": name + ".json", "error": "JSONShapeError"})
            else:
                result[name] = value
        except FileNotFoundError:
            pass
        except (OSError, TypeError, ValueError) as exc:
            receipt_errors.append({"file": name + ".json", "error": type(exc).__name__})
    if receipt_errors:
        result["receipt_errors"] = receipt_errors
    launch = result.get("launch", {})
    heartbeat = result.get("heartbeat", {})
    identity = launch.get("worker_identity")
    result["worker_alive"] = is_alive(identity)
    result["child_alive"] = is_alive(heartbeat.get("child_identity"))
    return result


def input_inventory(spec):
    """Describe missing inputs; an existing mismatch must never be overwritten."""
    result = []
    for item in spec.get("input_files", []):
        path = Path(item["path"])
        exists = path.exists()
        matches = exists and path.is_file() and digest(path) == item["sha256"]
        if exists and not matches:
            raise ValueError("existing input hash mismatch: " + str(path))
        result.append(dict(item, exists=exists, matches=matches))
    return result


def publish_inputs(spec, staging):
    """Publish verified staged bytes with exclusive creation, never replacement."""
    staging = Path(staging)
    for item in input_inventory(spec):
        if item["matches"]:
            continue
        source, target = staging / item["sha256"], Path(item["path"])
        if digest(source) != item["sha256"]:
            raise ValueError("staged input hash mismatch: " + str(target))
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.parent / (".core-input-" + uuid.uuid4().hex)
        try:
            shutil.copyfile(source, temporary)
            shutil.copymode(source, temporary)
            if digest(temporary) != item["sha256"]:
                raise ValueError("input copy hash mismatch")
            try:
                os.link(temporary, target)
            except FileExistsError:
                if not target.is_file() or digest(target) != item["sha256"]:
                    raise ValueError("concurrent input publication conflict: " + str(target))
        finally:
            temporary.unlink(missing_ok=True)
    return input_inventory(spec)


def snapshot_code(lab, root):
    """Freeze Python source; asset directories remain explicitly shared read-only inputs."""
    lab, root = Path(lab).resolve(), Path(root).resolve()
    files = sorted((lab / "scripts").glob("*.py"))
    for path in files:
        if path.name.startswith("core_"):
            compile(path.read_text(), str(path), "exec")
    hashes = {str(p.relative_to(lab)): digest(p) for p in files}
    sha = hashlib.sha256(canonical(hashes).encode()).hexdigest()
    snapshot = root / "snapshots" / sha / "lagrangian-fluid-lab"
    if not (snapshot / "source-manifest.json").exists():
        (snapshot / "scripts").mkdir(parents=True, exist_ok=True)
        for path in files:
            shutil.copyfile(path, snapshot / "scripts" / path.name)
        for path in lab.iterdir():
            if path.name == "scripts":
                continue
            target = snapshot / path.name
            if not target.exists():
                target.symlink_to(path, target_is_directory=path.is_dir())
        # Support historical helpers whose repository is LAB.parent.
        for name in ("bin", "src", "f3-ref0081818-material-archive", "f3-ref0081818-training-archive"):
            source = lab.parent / name
            target = snapshot.parent / name
            if source.exists() and not target.exists():
                target.symlink_to(source, target_is_directory=True)
        atomic_json(snapshot / "source-manifest.json", {"schema": "core.source.v1", "sha256": sha, "files": hashes,
                                                       "asset_root": str(lab)})
    # A race while files were copied must not yield a misleading source hash.
    for path, expected in hashes.items():
        if digest(snapshot / path) != expected:
            raise RuntimeError("source changed during snapshot; retry after edit completion")
    return snapshot, sha


def freeze_job(spec, lab, root):
    spec = json.loads(canonical(spec))
    if spec.get('source_snapshot'):
        snapshot = Path(spec['source_snapshot']['path']).resolve()
        manifest = json.loads((snapshot/'source-manifest.json').read_text())
        sha = hashlib.sha256(canonical(manifest['files']).encode()).hexdigest()
        if sha != spec['source_snapshot']['sha256'] or manifest['sha256'] != sha:
            raise ValueError('registered source snapshot identity mismatch')
        for relative, expected in manifest['files'].items():
            target = (snapshot/relative).resolve()
            target.relative_to(snapshot)
            if digest(target) != expected:
                raise ValueError('registered source snapshot content mismatch')
    else:
        snapshot, sha = snapshot_code(lab, root)
    scripts = str(Path(lab).resolve() / "scripts") + "/"
    spec["argv"] = [str(snapshot / "scripts" / x[len(scripts):]) if x.startswith(scripts) else x for x in spec["argv"]]
    for item in spec.get('input_files', []):
        if item['path'].startswith(scripts):
            item['path'] = str(snapshot/'scripts'/item['path'][len(scripts):])
    # A pinned snapshot can predate a newly added entrypoint. Verifying only
    # its old manifest would accept a command whose rewritten script is absent.
    frozen_scripts = str(snapshot / 'scripts') + '/'
    for argument in spec['argv']:
        if argument.startswith(frozen_scripts) and not Path(argument).is_file():
            raise ValueError('entrypoint/input absent from registered source snapshot: ' + argument)
    for item in spec.get('input_files', []):
        if item['path'].startswith(frozen_scripts):
            if not Path(item['path']).is_file() or digest(item['path']) != item['sha256']:
                raise ValueError('script input does not match registered source snapshot: ' + item['path'])
    spec["source_snapshot"] = {"sha256": sha, "path": str(snapshot)}
    spec.setdefault("env", {})["PYTHONPATH"] = os.pathsep.join((str(snapshot), str(snapshot / "scripts")))
    return spec


def worker(spec_file, attempt_dir):
    attempt = Path(attempt_dir).resolve()
    attempt.mkdir(parents=True, exist_ok=True)
    lock = (attempt / "worker.lock").open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return 0
    if (attempt / "result.json").exists():
        return 0
    # An incomplete previous worker is never silently re-executed in the same attempt.
    if (attempt / "launch.json").exists():
        return 2
    spec = json.loads(Path(spec_file).read_text())
    attempt_id = spec.get("attempt_id") or attempt.name
    start = time.time()
    identity = proc_identity(os.getpid())
    atomic_json(attempt / "launch.json", {"time": start, "worker_identity": identity,
                "job_id": spec["job_id"], "attempt_id": attempt_id})
    env = os.environ.copy()
    env.update({k: str(v) for k, v in spec.get("env", {}).items()})
    threads = str(max(1, int(spec["resources"]["cpu_cores"])))
    for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        env[name] = str(spec.get("env", {}).get(name, threads))
    gpu = spec.get("allocation", {}).get("gpu_uuid")
    env["CUDA_VISIBLE_DEVICES"] = gpu or ""
    env["CORE_ATTEMPT_DIR"] = str(attempt)
    argv = [x.replace("{attempt_dir}", str(attempt)) for x in spec["argv"]]
    peak_rss = peak_gpu = 0.0
    proc = None
    timeout = False
    error = None
    returncode = None
    try:
        for item in spec.get("input_files", []):
            if digest(item["path"]) != item["sha256"]:
                raise ValueError("input hash mismatch: " + item["path"])
        with (attempt / "stdout.log").open("ab", buffering=0) as log:
            proc = subprocess.Popen(argv, cwd=spec["cwd"], env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            child_identity = proc_identity(proc.pid)
            while True:
                pids, rss = process_tree(proc.pid)
                # Canonical attempts are runtime/attempts/job/attempt. Sharing
                # the runtime-local cache avoids one nvidia-smi pair per job.
                _, gpu_processes = shared_worker_gpu_snapshot(attempt.parents[2]) if gpu else ([], [])
                gpu_mib = sum(x["used_mib"] for x in gpu_processes if x["pid"] in pids and x["uuid"] == gpu)
                peak_rss, peak_gpu = max(peak_rss, rss / 1024**2), max(peak_gpu, gpu_mib)
                atomic_json(attempt / "heartbeat.json", {"time": time.time(), "worker_identity": identity,
                            "child_identity": child_identity, "process_ids": sorted(pids), "rss_mib": rss / 1024**2,
                            "gpu_mib": gpu_mib, "peak_rss_mib": peak_rss, "peak_gpu_mib": peak_gpu})
                returncode = proc.poll()
                if returncode is not None:
                    break
                if time.time() - start > spec["timeout_seconds"]:
                    timeout = True
                    os.killpg(proc.pid, signal.SIGTERM)
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(proc.pid, signal.SIGKILL)
                        proc.wait()
                    returncode = proc.returncode
                    break
                time.sleep(2)
    except Exception as exc:
        error = repr(exc)
        if proc and proc.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
    outputs = []
    missing = []
    for relative in spec.get("required_outputs", []):
        path = attempt / relative
        if path.is_file():
            outputs.append({"path": relative, "sha256": digest(path), "bytes": path.stat().st_size})
        else:
            missing.append(relative)
    # Include raw solver files and checkpoints, not just the small required reports.
    indexed = {item["path"]: item for item in outputs}
    for path in attempt.rglob("*"):
        if path.is_file() and not path.is_symlink() and path.name not in {"heartbeat.json", "worker.log", "worker.lock"}:
            relative = str(path.relative_to(attempt))
            if relative not in indexed:
                indexed[relative] = {"path": relative, "sha256": digest(path), "bytes": path.stat().st_size}
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    end = time.time()
    result = {"schema": EXECUTION_RECEIPT_SCHEMA, "job_id": spec["job_id"],
              "attempt_id": attempt_id,
              "execution_status": "succeeded" if returncode == 0 and not error and not missing and not timeout else "failed",
              "scientific_status": "not_inferred_from_execution", "started": start, "finished": end,
              "returncode": returncode, "timeout": timeout, "error": error, "missing_outputs": missing,
              "outputs": outputs, "artifact_index": list(indexed.values()), "argv": argv, "source_snapshot": spec.get("source_snapshot"),
              "usage": {"wall_seconds": end - start, "cpu_seconds_children": usage.ru_utime + usage.ru_stime,
                        "peak_rss_mib_sampled_tree": peak_rss, "max_child_rss_mib": usage.ru_maxrss / 1024,
                        "peak_gpu_mib_sampled": peak_gpu, "gpu_process_reservation_hours": (end - start) / 3600 if gpu else 0},
              "allocation": spec.get("allocation", {})}
    atomic_json(attempt / "result.json", result)
    return 0 if result["execution_status"] == "succeeded" else 1


def launch_detached(spec_file, attempt_dir):
    attempt = Path(attempt_dir)
    attempt.mkdir(parents=True, exist_ok=True)
    with (attempt / "worker.log").open("ab") as log:
        proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "worker", "--spec", spec_file,
                                 "--attempt-dir", str(attempt)], stdin=subprocess.DEVNULL,
                                stdout=log, stderr=subprocess.STDOUT, start_new_session=True, close_fds=True)
    return {"launcher_pid": proc.pid}


class Coordinator:
    def __init__(self, root, hosts, lab=LAB):
        self.store, self.hosts, self.lab = Store(root), hosts, Path(lab)
        self.runtimes = {}

    def runtime(self, name):
        if name not in self.runtimes:
            self.runtimes[name] = deploy_runtime(self.hosts[name])
        return self.runtimes[name]

    def call(self, name, *argv):
        host = self.hosts[name]
        return json.loads(host_run(host, [host["python"], self.runtime(name), *map(str, argv)]).stdout)

    @staticmethod
    def job_host(job):
        """Return the effective host for a queued or active job.

        A scheduler-selected job keeps that declaration in its immutable
        submission spec.  Once admitted, the concrete host is persisted in
        the allocation so reconciliation after a coordinator restart uses the
        same worker instead of treating the job as an unknown host.
        """
        allocation = job.get("allocation") or {}
        return allocation.get("_host") or job["spec"].get("host")

    def reconcile(self):
        for job in self.store.jobs():
            if job["status"] not in ACTIVE:
                continue
            host_name = self.job_host(job)
            if host_name not in self.hosts:
                self.store.register_recovery(
                    job["job_id"], expected_status=job["status"],
                    expected_attempt_id=job["attempt_id"], reason="unknown_effective_host",
                    observed={"host": host_name}, expected_job_id=job["job_id"],
                )
                continue
            try:
                receipt = self.call(host_name, "collect", "--attempt-dir", job["attempt_dir"])
            except Exception as exc:
                # Unreachable is not dead; retain reservation, do not relaunch.
                self.store.register_recovery(
                    job["job_id"], expected_status=job["status"],
                    expected_attempt_id=job["attempt_id"], reason="host_unreachable",
                    observed={"error": repr(exc)}, expected_job_id=job["job_id"],
                )
                continue
            if not isinstance(receipt, dict):
                self.store.register_recovery(
                    job["job_id"], expected_status=job["status"],
                    expected_attempt_id=job["attempt_id"], reason="invalid_collect_response",
                    observed={"type": type(receipt).__name__}, expected_job_id=job["job_id"],
                )
                continue
            if receipt.get("receipt_errors"):
                self.store.register_recovery(
                    job["job_id"], expected_status=job["status"],
                    expected_attempt_id=job["attempt_id"], reason="corrupt_receipt",
                    observed={"receipt_errors": receipt["receipt_errors"]},
                    heartbeat=receipt.get("heartbeat", {}), expected_job_id=job["job_id"],
                )
                continue
            result = receipt.get("result")
            if result is not None:
                self.store.finalize_receipt(
                    job["job_id"], result, expected_attempt_id=job["attempt_id"],
                    heartbeat=receipt.get("heartbeat", {}), expected_job_id=job["job_id"],
                )
            elif receipt.get("worker_alive") or receipt.get("child_alive"):
                self.store.cas_update(
                    job["job_id"], "running", expected_status=job["status"],
                    expected_attempt_id=job["attempt_id"], expected_job_id=job["job_id"],
                    heartbeat=receipt.get("heartbeat", {}), result={},
                )
            elif time.time() - job["updated"] > 60 or job["status"] == "attention":
                self.store.register_recovery(
                    job["job_id"], expected_status=job["status"],
                    expected_attempt_id=job["attempt_id"],
                    reason="missing_receipt_requires_reconciliation", observed=receipt,
                    heartbeat=receipt.get("heartbeat", {}), expected_job_id=job["job_id"],
                )

    def launch(self, job, allocation, host_name=None):
        name = host_name or job["spec"]["host"]
        if name not in self.hosts:
            raise ValueError("unknown launch host: " + str(name))
        host = self.hosts[name]
        attempt_id = time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:12]
        attempt = Path(host["lab"]) / "campaigns/core-v1/runtime/attempts" / job["job_id"] / attempt_id
        allocation = dict(allocation)
        allocation["_host"] = name
        # Keep scheduler-selected in the submission record, but freeze the
        # concrete host into the worker request and receipt.
        spec = freeze_job(dict(job["spec"], host=name, allocation=allocation), self.lab, self.store.root)
        spec["source_lab"] = host["lab"]
        if not self.store.cas_update(
                job["job_id"], "reserved", expected_status=job["status"],
                expected_attempt_id=None, expected_job_id=job["job_id"],
                attempt_id=attempt_id, allocation=allocation, attempt_dir=str(attempt)):
            raise RuntimeError("job changed before reservation")
        spec["attempt_id"] = attempt_id
        local_spec = self.store.root / "specs" / (attempt_id + ".json")
        atomic_json(local_spec, spec)
        if not self.store.cas_update(
                job["job_id"], "launching", expected_status="reserved",
                expected_attempt_id=attempt_id, expected_job_id=job["job_id"]):
            raise RuntimeError("job changed before launch")
        try:
            if host.get("ssh"):
                source_parent = Path(spec["source_snapshot"]["path"]).parent
                host_run(host, ["mkdir", "-p", str(source_parent)])
                # -l copies asset symlinks, never their large targets or live .git.
                subprocess.run(["rsync", "-rl", str(source_parent) + "/",
                                host["ssh"] + ":" + str(source_parent) + "/"], check=True, timeout=60)
                host_run(host, ["mkdir", "-p", str(attempt)])
                subprocess.run(["scp", "-q", str(local_spec), host["ssh"] + ":" + str(attempt / "request.json")], check=True, timeout=60)
                inventory = self.call(name, "inspect-inputs", "--spec", attempt / "request.json")
                staging = attempt / "input-transfer"
                missing = [item for item in inventory if not item["matches"]]
                if missing:
                    host_run(host, ["mkdir", "-p", str(staging)])
                    for item in missing:
                        source = Path(item["path"])
                        if digest(source) != item["sha256"]:
                            raise ValueError("local input changed before transfer: " + str(source))
                        subprocess.run(["rsync", "--protect-args", "-q", str(source),
                                        host["ssh"] + ":" + str(staging / item["sha256"])],
                                       check=True, timeout=3600)
                    self.call(name, "publish-inputs", "--spec", attempt / "request.json",
                              "--staging", staging)
            else:
                attempt.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(local_spec, attempt / "request.json")
            self.call(name, "prepare-launch", "--spec", attempt / "request.json", "--attempt-dir", attempt)
        except Exception as exc:
            self.store.register_recovery(
                job["job_id"], expected_status="launching", expected_attempt_id=attempt_id,
                reason="launch_uncertain", observed={"error": repr(exc)},
                expected_job_id=job["job_id"],
            )

    def tick(self):
        self.reconcile()
        # A persistent coordinator must remain available for a later submit,
        # but terminal-only queues have no admission decision to make.  Avoid
        # repeatedly probing every host (and sampling every GPU) until there
        # is queued work to admit. Reconciliation above still runs first so an
        # active worker can always finalize before this decision.
        jobs = self.store.jobs()
        if not any(job["status"] == "queued" for job in jobs):
            summary = self.summary()
            atomic_json(self.store.root / "status.json", summary)
            return summary
        snapshots = {}
        for name, host in self.hosts.items():
            try:
                snapshots[name] = self.call(name, "probe", "--path", host["lab"])
                snapshots[name]['io_capacity'] = host.get('io_capacity', 2)
                atomic_json(self.store.root / "inventory" / (name + ".json"), snapshots[name])
            except Exception as exc:
                atomic_json(self.store.root / "inventory" / (name + "-error.json"), {"time": time.time(), "error": repr(exc)})
        planned_active = {name: [] for name in snapshots}
        for active_job in self.store.jobs():
            if active_job["status"] not in ACTIVE:
                continue
            effective = self.job_host(active_job)
            if effective in planned_active:
                planned_active[effective].append(active_job)
        for job in sorted(self.store.jobs(), key=queue_priority):
            if job["status"] != "queued":
                continue
            jobs = self.store.jobs()
            states = {x["job_id"]: x["status"] for x in jobs}
            if any(states.get(x) != "succeeded" for x in job["spec"]["depends_on"]):
                continue
            requested_host = job["spec"].get("host")
            if requested_host == "scheduler-selected":
                # Prefer H200 for GPU work, then fall back to Ada.  Resource
                # admission remains authoritative; preference never bypasses
                # CPU, RAM, I/O, disk, external-GPU, or reserved headroom.
                names = list(snapshots)
                names.sort(key=lambda n: (0 if n == "h200" and job["spec"]["resources"].get("gpu_peak_mib", 0) else 1, n))
            elif requested_host in snapshots:
                names = [requested_host]
            else:
                continue
            selected = None
            for name in names:
                allocation = choose_resources(job["spec"], snapshots[name], planned_active[name])
                if allocation is not None:
                    selected = (name, allocation)
                    break
            if selected is not None:
                name, allocation = selected
                try:
                    self.launch(job, allocation, host_name=name)
                    # Account for this launch during the same tick.  The
                    # immutable submission spec remains scheduler-selected.
                    planned_active[name].append({"status": "reserved", "spec": job["spec"],
                                                 "allocation": dict(allocation), "heartbeat": {}})
                except Exception as exc:
                    # Source can change while an agent publishes files; a queued
                    # job remains queued until a coherent snapshot can be made.
                    with self.store.db:
                        self.store.event(job["job_id"], "launch_preparation_error", {"error": repr(exc)})
        summary = self.summary()
        atomic_json(self.store.root / "status.json", summary)
        return summary

    def summary(self, *, compact=False):
        jobs = self.store.jobs()
        counts = {status: sum(x["status"] == status for x in jobs) for status in ("queued",) + ACTIVE + TERMINAL}
        common = {"time": time.time(), "counts": counts, "usage": usage_summary(jobs),
                  "scientific_completion": "not_inferred_from_queue"}
        if compact:
            # The detailed status remains the audit view. The compact view is
            # for routine monitoring: retain actionable queued/live identities
            # while summarizing terminal history only by counts and usage.
            current = []
            for x in jobs:
                if x["status"] in TERMINAL:
                    continue
                spec = x["spec"]
                entry = {
                    "job_id": x["job_id"], "status": x["status"],
                    "host": spec.get("host"), "effective_host": self.job_host(x),
                    "attempt_id": x["attempt_id"], "attempt_dir": x["attempt_dir"],
                    "created": x["created"], "updated": x["updated"],
                    "spec_hash": x["spec_hash"], "allocation": x["allocation"],
                    "resources": spec.get("resources", {}),
                }
                if x["status"] == "attention" and isinstance(x["result"], dict):
                    result = x["result"]
                    attention = {key: result[key] for key in ("reason", "error") if key in result}
                    for key in ("errors", "receipt_errors"):
                        value = result.get(key)
                        if isinstance(value, list):
                            attention[key] = value[:8]
                    if attention:
                        entry["attention"] = attention
                current.append(entry)
            return {"schema": "core.queue_status_summary.v1", **common,
                    "current_jobs": current,
                    "terminal_history": "summarized_by_counts_and_usage"}
        return {"schema": "core.queue_status.v1", **common, "jobs": [
            {"job_id": x["job_id"], "status": x["status"], "host": x["spec"]["host"],
             "effective_host": self.job_host(x),
             "attempt_dir": x["attempt_dir"], "allocation": x["allocation"], "result": x["result"]} for x in jobs]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--hosts", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    status = commands.add_parser("status")
    status.add_argument("--compact", action="store_true",
                        help="summarize terminal history; retain details only for queued/live jobs")
    for name in ("inspect-inputs", "publish-inputs"):
        p = commands.add_parser(name)
        p.add_argument("--spec", type=Path, required=True)
        if name == "publish-inputs":
            p.add_argument("--staging", type=Path, required=True)
    for name in ("submit", "worker", "prepare-launch"):
        p = commands.add_parser(name)
        p.add_argument("--spec", type=Path, required=True)
        if name != "submit":
            p.add_argument("--attempt-dir", type=Path, required=True)
    p = commands.add_parser("probe")
    p.add_argument("--path", type=Path, default=LAB)
    p = commands.add_parser("collect")
    p.add_argument("--attempt-dir", type=Path, required=True)
    p = commands.add_parser("run")
    p.add_argument("--once", action="store_true")
    p.add_argument("--poll-seconds", type=float, default=10)
    args = parser.parse_args()
    if args.command == "inspect-inputs":
        print(canonical(input_inventory(json.loads(args.spec.read_text()))))
    elif args.command == "publish-inputs":
        print(canonical(publish_inputs(json.loads(args.spec.read_text()), args.staging)))
    elif args.command == "probe":
        print(canonical(probe(args.path)))
    elif args.command == "collect":
        print(canonical(collect_attempt(args.attempt_dir)))
    elif args.command == "worker":
        return worker(args.spec, args.attempt_dir)
    elif args.command == "prepare-launch":
        spec = json.loads(args.spec.read_text())
        if spec.get("source_snapshot"):
            source = Path(spec["source_snapshot"]["path"])
            manifest = json.loads((source / "source-manifest.json").read_text())
            if manifest["sha256"] != spec["source_snapshot"]["sha256"]:
                raise ValueError("source snapshot identity mismatch")
            for relative, expected in manifest["files"].items():
                if digest(source / relative) != expected:
                    raise ValueError("source snapshot transfer hash mismatch")
        else:
            spec = freeze_job(spec, spec["source_lab"], Path(spec["source_lab"]) / "campaigns/core-v1/runtime")
        prepared = args.attempt_dir / "spec.json"
        atomic_json(prepared, spec)
        print(canonical(launch_detached(str(prepared), args.attempt_dir)))
    elif args.command == "submit":
        print(canonical({"inserted": Store(args.root).submit(json.loads(args.spec.read_text()))}))
    else:
        hosts = json.loads(args.hosts.read_text()) if args.hosts else default_hosts(LAB)
        coordinator = Coordinator(args.root, hosts)
        if args.command == "status":
            print(json.dumps(coordinator.summary(compact=args.compact), indent=2))
        else:
            args.root.mkdir(parents=True, exist_ok=True)
            with (args.root / "coordinator.lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                while True:
                    result = coordinator.tick()
                    print(canonical({"time": result["time"], "counts": result["counts"]}), flush=True)
                    if args.once:
                        break
                    time.sleep(max(1, args.poll_seconds))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
