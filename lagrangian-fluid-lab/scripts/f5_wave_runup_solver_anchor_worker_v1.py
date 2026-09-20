#!/usr/bin/env python3
"""Static guard for the F5 protected solver-anchor job specification.

This module is intentionally a contract-only worker.  It can verify the
hash-bound job specification, but it has no solver, CUDA, queue, ledger, or
registry entry point.  A later, separately reviewed runtime worker may consume
the specification after the root review is accepted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
BASE = LAB / "campaigns/core-v1/cfd/f5-wave-runup-third-t1/fresh-definition-v2"
DEFAULT_JOB = BASE / "solver-anchor-job-spec-v1.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def verify_job(path: Path = DEFAULT_JOB) -> dict[str, Any]:
    """Verify the static job contract without starting a workload."""

    job = load(Path(path))
    if job.get("schema") != "core.f5.third_t1.solver_anchor_job_spec.v1":
        raise ValueError("wrong F5 solver-anchor job schema")
    if job.get("job_spec_status") != "root_review_only_not_submitted":
        raise ValueError("job is no longer root-review-only")
    if job.get("attempt_role") != "protected_single_gpu_solver_anchor":
        raise ValueError("job is not the protected single anchor")
    if job.get("qualification_claim") != "none" or job.get("matrix_credit") != 0:
        raise ValueError("job carries scientific credit")
    if job.get("exactly_one_anchor") is not True:
        raise ValueError("job must authorize exactly one anchor")

    policy = job.get("execution_policy", {})
    required_false = (
        "submit_allowed",
        "queue_mutation",
        "ledger_mutation",
        "registry_mutation",
        "matrix_submission",
        "same_input_retry",
    )
    for key in required_false:
        if policy.get(key) not in (False, 0):
            raise ValueError(f"forbidden execution policy is open: {key}")
    if policy.get("solver_launch") is not True or policy.get("gpu_launch") is not True:
        raise ValueError("protected solver/GPU authorization is missing")
    if policy.get("failure_credit") != 0:
        raise ValueError("failure policy must award zero credit")

    worker = job.get("worker", {})
    if worker.get("runtime_enabled") is not False:
        raise ValueError("contract worker must remain runtime-disabled")
    if worker.get("solver_calls") != 0 or worker.get("gpu_calls") != 0:
        raise ValueError("contract worker reports runtime calls")
    if worker.get("path") != "scripts/f5_wave_runup_solver_anchor_worker_v1.py":
        raise ValueError("unexpected worker binding")
    worker_path = LAB / worker["path"]
    if not worker_path.is_file() or sha256(worker_path) != worker.get("sha256"):
        raise ValueError("worker hash binding is stale")

    stem = Path(job["anchor_output"]["stem"])
    if stem.name != "F5_wave_runup_q0p50_dp0p0075_v2_anchor":
        raise ValueError("unexpected anchor output stem")
    if stem.name == "F5_wave_runup_q0p50_dp0p0075_v2":
        raise ValueError("anchor output reuses the CPU/native preflight stem")
    if (LAB / stem).exists():
        raise ValueError("anchor output stem is no longer fresh")

    bindings = job.get("hash_bindings", {})
    for item in bindings.values():
        if not isinstance(item, dict) or not {"path", "sha256", "bytes"} <= set(item):
            raise ValueError("malformed job hash binding")
        bound = LAB / item["path"]
        if not bound.is_file() or bound.stat().st_size != item["bytes"] or sha256(bound) != item["sha256"]:
            raise ValueError(f"stale job hash binding: {bound}")
    return job


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("verify", "run"), nargs="?", default="verify")
    parser.add_argument("--job", type=Path, default=DEFAULT_JOB)
    args = parser.parse_args()
    if args.command == "run":
        raise SystemExit("F5 solver anchor worker is contract-only; runtime launch requires a separately reviewed worker")
    job = verify_job(args.job)
    print(json.dumps({"status": "contract_verified_runtime_closed", "job_id": job["job_id"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
