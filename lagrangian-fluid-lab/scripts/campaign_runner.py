#!/usr/bin/env python3
"""Immutable attempt directories, GPU UUID guards, and atomic run publication."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time
import uuid


SAFE_CASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def atomic_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(payload, indent=2) + "\n")
    os.replace(temporary, path)


def query_gpus():
    proc = subprocess.run([
        "nvidia-smi", "--query-gpu=index,uuid,memory.used,utilization.gpu",
        "--format=csv,noheader,nounits"], check=True, text=True, stdout=subprocess.PIPE)
    records = []
    for line in proc.stdout.splitlines():
        index, gpu_uuid, memory, utilization = [value.strip() for value in line.split(",")]
        records.append({"index": int(index), "uuid": gpu_uuid, "memory_used_mib": int(memory),
                        "utilization_percent": int(utilization)})
    return records


def require_idle_allowed_gpu(index, allowed_uuids, *, memory_limit_mib=1024, utilization_limit=10):
    record = next((gpu for gpu in query_gpus() if gpu["index"] == index), None)
    if record is None:
        raise RuntimeError(f"physical GPU {index} does not exist")
    if record["uuid"] not in set(allowed_uuids):
        raise RuntimeError(f"GPU {index} UUID {record['uuid']} is not in the campaign allowlist")
    if record["memory_used_mib"] >= memory_limit_mib or record["utilization_percent"] >= utilization_limit:
        raise RuntimeError(f"GPU {index} is not idle: {record}")
    return record


def execute_attempt(case_id, command_template, run_root, *, cwd=None, env=None,
                    evidence_glob="data*/Part_*.bi4", required_text=None,
                    timeout_seconds=None, resource_guard=None,
                    resource_poll_seconds=1.0):
    """Execute into a unique partial directory, then atomically publish one attempt."""
    if not SAFE_CASE_ID.fullmatch(case_id):
        raise ValueError(f"unsafe case id: {case_id!r}")
    run_root = Path(run_root).resolve()
    attempts = run_root / case_id / "attempts"
    attempts.mkdir(parents=True, exist_ok=True)
    attempt_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "-" + uuid.uuid4().hex[:8]
    partial = attempts / (attempt_id + ".partial")
    partial.mkdir()
    command = [str(value).replace("{output}", str(partial)) for value in command_template]
    started_at = datetime.now(timezone.utc).isoformat()
    atomic_json(partial / "attempt.json", {
        "schema_version": 1, "case_id": case_id, "attempt_id": attempt_id,
        "status": "running", "started_at_utc": started_at, "command": command,
        "timeout_seconds": timeout_seconds,
    })
    started = time.monotonic()
    timed_out = False
    interrupted = False
    resource_guard_triggered = None
    process_group_terminated = False
    if timeout_seconds is None:
        proc = subprocess.run(command, cwd=cwd, env=env, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        stdout = proc.stdout or ""
        returncode = proc.returncode
    else:
        proc = subprocess.Popen(command, cwd=cwd, env=env, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                start_new_session=True)
        try:
            deadline = time.monotonic() + timeout_seconds
            while True:
                wait_seconds = min(resource_poll_seconds, max(0.05, deadline - time.monotonic()))
                try:
                    stdout, _ = proc.communicate(timeout=wait_seconds)
                    stdout = stdout or ""
                    returncode = proc.returncode
                    break
                except subprocess.TimeoutExpired:
                    if time.monotonic() >= deadline:
                        timed_out = True
                        try:
                            os.killpg(proc.pid, signal.SIGKILL)
                            process_group_terminated = True
                        except ProcessLookupError:
                            process_group_terminated = True
                        stdout, _ = proc.communicate()
                        stdout = stdout or ""
                        returncode = -9
                        break
                    if resource_guard is not None:
                        try:
                            guard = resource_guard()
                        except Exception as error:  # fail closed on monitor errors
                            guard = {"ok": False, "error": repr(error)}
                        if guard and not bool(guard.get("ok", True)):
                            resource_guard_triggered = guard
                            try:
                                os.killpg(proc.pid, signal.SIGTERM)
                                process_group_terminated = True
                            except ProcessLookupError:
                                process_group_terminated = True
                            try:
                                stdout, _ = proc.communicate(timeout=10)
                            except subprocess.TimeoutExpired:
                                try:
                                    os.killpg(proc.pid, signal.SIGKILL)
                                    process_group_terminated = True
                                except ProcessLookupError:
                                    process_group_terminated = True
                                stdout, _ = proc.communicate()
                            stdout = stdout or ""
                            returncode = -12
                            break
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(proc.pid, signal.SIGKILL)
                process_group_terminated = True
            except ProcessLookupError:
                process_group_terminated = True
            stdout, _ = proc.communicate()
            stdout = stdout or ""
            returncode = -9
        except KeyboardInterrupt:
            # Keep an interrupted attempt auditable and avoid leaving a
            # ``.partial`` directory that falsely looks live.  This is used
            # by L1 when a co-run memory safety check asks the local solver to
            # stop; unrelated processes are never in this process group.
            interrupted = True
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                process_group_terminated = True
            except ProcessLookupError:
                process_group_terminated = True
            try:
                stdout, _ = proc.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                    process_group_terminated = True
                except ProcessLookupError:
                    process_group_terminated = True
                stdout, _ = proc.communicate()
            stdout = stdout or ""
            returncode = -2
    elapsed = time.monotonic() - started
    (partial / "process.stdout.log").write_text(stdout)
    evidence = sorted(partial.glob(evidence_glob))
    text_ok = required_text is None or required_text in stdout
    succeeded = returncode == 0 and bool(evidence) and text_ok
    final = attempts / (attempt_id + (".complete" if succeeded else ".failed"))
    payload = {
        "schema_version": 1, "case_id": case_id, "attempt_id": attempt_id,
        "status": "completed" if succeeded else "failed", "started_at_utc": started_at,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": elapsed, "returncode": returncode, "command": command,
        "evidence_files": [str(path.relative_to(partial)) for path in evidence],
        "required_text_found": text_ok, "timed_out": timed_out,
        "interrupted": interrupted,
        "resource_guard_triggered": resource_guard_triggered is not None,
        "resource_guard": resource_guard_triggered,
        "process_group_terminated": process_group_terminated,
        "timeout_seconds": timeout_seconds,
    }
    atomic_json(partial / "attempt.json", payload)
    os.replace(partial, final)
    payload["attempt_directory"] = str(final)
    if succeeded:
        atomic_json(run_root / case_id / "latest.json", payload)
    return payload
