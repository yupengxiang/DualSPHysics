#!/usr/bin/env python3
"""Archive terminal runtime outputs without changing execution or qualification state."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).absolute().parents[1]))
from scripts.core_runtime import DEFAULT_ROOT, Store, atomic_json, canonical, digest


def selected_outputs(receipt):
    if receipt.get("execution_status") != "succeeded":
        raise ValueError("archive requires a successful terminal execution receipt")
    entries = list(receipt.get("outputs", []))
    entries += [x for x in receipt.get("artifact_index", [])
                if Path(x["path"]).name in ("Run.out", "RunPARTs.csv")]
    result = {}
    for item in entries:
        relative = Path(item["path"])
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ValueError("unsafe artifact path")
        if item["path"] in result and result[item["path"]] != item:
            raise ValueError("conflicting artifact registrations")
        result[item["path"]] = item
    if not result:
        raise ValueError("receipt has no registered outputs")
    return list(result.values())


def verify_files(root, outputs):
    for item in outputs:
        path = root / item["path"]
        path.resolve().relative_to(root.resolve())
        if (not path.is_file() or path.stat().st_size != item["bytes"]
                or digest(path) != item["sha256"]):
            raise ValueError("archive artifact integrity failure: " + item["path"])


def effective_host(job):
    """Resolve the concrete worker host recorded by the scheduler.

    Jobs submitted with ``host=scheduler-selected`` retain that declaration in
    their immutable spec.  Once admitted, the coordinator freezes the actual
    host in ``allocation._host`` so archive/recovery code can use the same
    source without guessing from current inventory.
    """
    allocation = job.get("allocation") or {}
    return allocation.get("_host") or job.get("spec", {}).get("host")


def archive_job(job, hosts, destination):
    """Caller owns the archive-root lock. Existing archives are never overwritten."""
    if job["status"] != "succeeded":
        raise ValueError("job is not terminal-successful")
    receipt = job["result"]
    if receipt.get("job_id") != job["job_id"]:
        raise ValueError("receipt/job identity mismatch")
    outputs = selected_outputs(receipt)
    receipt_sha = hashlib.sha256(canonical(receipt).encode()).hexdigest()
    job_id = job["job_id"]
    if Path(job_id).name != job_id or job_id in (".", ".."):
        raise ValueError("unsafe job identifier")
    target = destination / job_id
    if target.exists():
        manifest = json.loads((target / "archive.json").read_text())
        if manifest["receipt_sha256"] != receipt_sha:
            raise ValueError("existing archive has different receipt")
        verify_files(target, outputs)
        return {"job_id": job_id, "status": "already_verified", "path": str(target)}
    destination.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="." + job_id + ".", dir=destination))
    try:
        host_name = effective_host(job)
        if host_name not in hosts:
            raise ValueError("unknown effective archive host: " + str(host_name))
        host = hosts[host_name]
        source = Path(job["attempt_dir"])
        if host.get("ssh"):
            names = b"\0".join(x["path"].encode() for x in outputs) + b"\0"
            subprocess.run(["rsync", "-a", "--protect-args", "--from0", "--files-from=-",
                            host["ssh"] + ":" + str(source) + "/", str(staging) + "/"],
                           input=names, check=True)
        else:
            for item in outputs:
                path = staging / item["path"]
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source / item["path"], path)
        verify_files(staging, outputs)
        atomic_json(staging / "execution-receipt.json", receipt)
        atomic_json(staging / "archive.json", {
            "schema": "core.verified_archive.v1", "job_id": job_id,
            "attempt_dir": str(source), "source_host": host_name,
            "receipt_sha256": receipt_sha, "outputs": outputs,
            "verified_at_unix_s": time.time(), "qualification_claim": "none",
            "execution_status": receipt["execution_status"],
            "scientific_status": "not_inferred_from_archive",
        })
        os.rename(staging, target)
        return {"job_id": job_id, "status": "published", "path": str(target)}
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--hosts", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--exclude-job", action="append", default=[])
    parser.add_argument("--follow", action="store_true")
    args = parser.parse_args()
    args.destination.mkdir(parents=True, exist_ok=True)
    with (args.destination / ".archive.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        hosts = json.loads(args.hosts.read_text())
        store = Store(args.root)
        # Rehash once per collector process, then trust only this process's
        # completed immutable publications until it restarts.
        handled = set()
        while True:
            for job in store.jobs():
                if (not job["job_id"].startswith(args.prefix)
                        or job["job_id"] in args.exclude_job or job["status"] != "succeeded"
                        or job["job_id"] in handled):
                    continue
                result = archive_job(job, hosts, args.destination)
                print(json.dumps(result), flush=True)
                handled.add(job["job_id"])
            if not args.follow:
                return 0
            time.sleep(10)


if __name__ == "__main__":
    raise SystemExit(main())
