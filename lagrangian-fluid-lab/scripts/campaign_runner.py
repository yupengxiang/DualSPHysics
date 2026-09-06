#!/usr/bin/env python3
"""Immutable attempt directories, GPU UUID guards, and atomic run publication."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
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
                    evidence_glob="data*/Part_*.bi4", required_text=None):
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
    })
    started = time.monotonic()
    proc = subprocess.run(command, cwd=cwd, env=env, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    elapsed = time.monotonic() - started
    (partial / "process.stdout.log").write_text(proc.stdout)
    evidence = sorted(partial.glob(evidence_glob))
    text_ok = required_text is None or required_text in proc.stdout
    succeeded = proc.returncode == 0 and bool(evidence) and text_ok
    final = attempts / (attempt_id + (".complete" if succeeded else ".failed"))
    payload = {
        "schema_version": 1, "case_id": case_id, "attempt_id": attempt_id,
        "status": "completed" if succeeded else "failed", "started_at_utc": started_at,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": elapsed, "returncode": proc.returncode, "command": command,
        "evidence_files": [str(path.relative_to(partial)) for path in evidence],
        "required_text_found": text_ok,
    }
    atomic_json(partial / "attempt.json", payload)
    os.replace(partial, final)
    payload["attempt_directory"] = str(final)
    if succeeded:
        atomic_json(run_root / case_id / "latest.json", payload)
    return payload
