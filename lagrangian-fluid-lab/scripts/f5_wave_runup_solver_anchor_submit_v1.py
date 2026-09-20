#!/usr/bin/env python3
"""Submit the single F5 solver anchor through ``core_runtime``.

This is the only mutating step after root review.  It creates one queue spec
and, when explicitly requested, inserts that spec into the persistent queue.
It never starts a solver directly and refuses a stale receipt, stale input, or
an already-used job id.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any


LAB = Path(__file__).resolve().parents[1]
ROOT = LAB / "campaigns/core-v1/cfd/f5-wave-runup-third-t1/fresh-definition-v2"
JOB = ROOT / "solver-anchor-job-spec-v1.json"
REVIEW = ROOT / "solver-anchor-root-review-v1.json"
QUEUE_SPEC = ROOT / "solver-anchor-queue-spec-v1.json"
RUNTIME = LAB / "scripts/f5_wave_runup_solver_anchor_runtime_v1.py"
RUNTIME_ROOT = LAB / "campaigns/core-v1/runtime"
HOSTS = RUNTIME_ROOT / "hosts-mixed-canary-v4.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def verify_inputs() -> tuple[dict[str, Any], dict[str, Any]]:
    job, review = load(JOB), load(REVIEW)
    if job.get("schema") != "core.f5.third_t1.solver_anchor_job_spec.v1":
        raise ValueError("wrong anchor job schema")
    if job.get("job_spec_status") != "root_review_only_not_submitted":
        raise ValueError("anchor job has already been submitted or superseded")
    if job.get("exactly_one_anchor") is not True or job.get("matrix_credit") != 0 or job.get("qualification_claim") != "none":
        raise ValueError("anchor job is not zero-credit single-use")
    decision = review.get("review_decision", {})
    if review.get("schema") != "core.f5.third_t1.solver_anchor_root_review_receipt.v1":
        raise ValueError("wrong anchor root review schema")
    if review.get("status") != "root_review_only_protected_gpu_solver_anchor_authorized_not_submitted":
        raise ValueError("root review is not active")
    if decision.get("authorized_solver") is not True or decision.get("authorized_gpu") is not True or decision.get("authorized_queue") is not True:
        raise ValueError("root review does not authorize one protected queue execution")
    if any(decision.get(key) for key in ("authorized_registry", "authorized_ledger", "authorized_matrix")):
        raise ValueError("root review opens a forbidden scientific mutation path")
    if job.get("root_review", {}).get("sha256") != sha256(REVIEW):
        raise ValueError("job is bound to a different root review")
    for item in job.get("hash_bindings", {}).values():
        path = LAB / item["path"]
        if not path.is_file() or path.stat().st_size != item["bytes"] or sha256(path) != item["sha256"]:
            raise ValueError(f"stale job binding: {path}")
    if not RUNTIME.is_file() or sha256(RUNTIME) != job.get("runtime_worker", {}).get("sha256"):
        raise ValueError("runtime worker hash is stale")
    return job, review


def build_queue_spec(job: dict[str, Any]) -> dict[str, Any]:
    resources = dict(job["resources"])
    timeout = resources.pop("timeout_seconds")
    inputs = [dict(item, path=str((LAB / item["path"]).resolve())) for item in job["input_files"]]
    argv = [
        str(LAB / ".venv/bin/python"), str(RUNTIME),
        "--job", str(JOB), "--review", str(REVIEW),
        "--output", "{attempt_dir}/product",
    ]
    return {
        "schema": "core.f5.third_t1.solver_anchor_queue_spec.v1",
        "job_id": job["job_id"],
        "logical_id": job["logical_id"],
        "attempt_role": "protected_single_gpu_solver_anchor",
        "category": "f5_protected_solver_anchor",
        "host": "ada",
        "source_lab": str(LAB),
        "cwd": str(LAB),
        "argv": argv,
        "required_outputs": job["required_outputs"],
        "resources": resources,
        "timeout_seconds": timeout,
        "depends_on": [],
        "input_files": inputs,
        "qualification_claim": "none",
        "qualification_only": True,
        "split": "qualification_only",
        "family": "F5",
        "scope_id": job["scope_id"],
        "prepared_case_id": job["prepared_case_id"],
        "registered_window_s": job["registered_window_s"],
        "output_interval_s": job["output_interval_s"],
        "root_review": job["root_review"],
        "job_spec": {"path": str(JOB), "sha256": sha256(JOB)},
        "runtime_worker": job["runtime_worker"],
        "one_submission_only": True,
        "scientific_status": "execution_only; scientific review pending",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("dry-run", "submit"))
    args = parser.parse_args()
    job, _review = verify_inputs()
    spec = build_queue_spec(job)
    encoded = json.dumps(spec, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    if QUEUE_SPEC.exists():
        existing = load(QUEUE_SPEC)
        if existing != spec:
            raise ValueError("existing queue spec differs; refuse to overwrite a protected submission")
    else:
        QUEUE_SPEC.write_text(encoded, encoding="utf-8")
    if args.command == "dry-run":
        print(json.dumps({"status": "queue_spec_written_not_submitted", "job_id": spec["job_id"],
                          "queue_spec": str(QUEUE_SPEC), "queue_mutation": 0}, indent=2))
        return 0
    command = [str(LAB / ".venv/bin/python"), str(LAB / "scripts/core_runtime.py"),
               "--root", str(RUNTIME_ROOT), "submit", "--spec", str(QUEUE_SPEC)]
    completed = subprocess.run(command, cwd=LAB, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        print(completed.stdout, end="")
        print(completed.stderr, end="")
        return completed.returncode
    response = json.loads(completed.stdout)
    if response.get("inserted") is not True:
        raise SystemExit("queue already contains this job id; no second submission was performed")
    print(json.dumps({"status": "queue_submitted_once", "job_id": spec["job_id"],
                      "queue_spec": str(QUEUE_SPEC), "queue_mutation": 1,
                      "runtime_output": "attempt_dir/product"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
