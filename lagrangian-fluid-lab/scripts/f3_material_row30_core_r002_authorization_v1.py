#!/usr/bin/env python3
"""Freeze the corrected, one-time full-window F3 row-30 r002 job.

This is a new exploration scope because r001 was terminated after discovering
that its immutable job spec omitted ``--stop-after 835`` and would have used
the runner's 20-interval default.  Its partial output is negative execution
evidence only and cannot be resumed or reused.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from scripts import f3_material_row30_core_authorization_v1 as base


LAB = base.LAB
EVIDENCE = base.EVIDENCE
R001_RECEIPT = LAB / "campaigns/core-v1/runtime/attempts/f3-material-30-canonical-s4-r001/20260923T104038-fc96f5b8cf1a/result.json"
AUTHORIZATION = EVIDENCE / "f3-material-row30-core-cpu-r002-authorization-v1/authorization.json"
JOB_SPEC = EVIDENCE / "f3-material-row30-core-cpu-r002-authorization-v1/job-spec.json"
JOB_ID = "f3-material-30-canonical-s4-r002"
OUTPUT_NAMESPACE = "campaigns/core-v1/material/attempts/f3-material-30-canonical-s4-r002"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            value.update(block)
    return value.hexdigest()


def build() -> tuple[dict[str, Any], dict[str, Any]]:
    prior_auth, prior_spec = base.build()
    if prior_spec["argv"][-2:] != ["--stop-after", "835"]:
        raise ValueError("the corrected r002 job must explicitly cover all 835 intervals")
    if not R001_RECEIPT.is_file():
        raise FileNotFoundError(R001_RECEIPT)
    prior = json.loads(R001_RECEIPT.read_text(encoding="utf-8"))
    if prior.get("execution_status") != "failed" or prior.get("returncode") != -15:
        raise ValueError("r001 must remain the terminated short-window negative attempt")
    if "trace.summary.json" not in prior.get("missing_outputs", []):
        raise ValueError("r001 failure signature changed")
    prior_ref = {"path": str(R001_RECEIPT.relative_to(LAB)), "sha256": digest(R001_RECEIPT), "role": "closed noncanonical r001 execution receipt"}
    authorization = {
        **prior_auth,
        "schema": "core.material.f3.row30.core_cpu_r002_authorization.v1",
        "status": "authorized_one_cpu_attempt_not_started",
        "purpose": "corrected full-window r002 after closed r001 short-window specification failure",
        "candidate": {**prior_auth["candidate"], "full_native_interval_count": 835},
        "resource_pool": {**prior_auth["resource_pool"], "pool_id": "core-f3-material-row30-cpu-r002", "max_attempts": 1},
        "new_output_namespace": OUTPUT_NAMESPACE,
        "closed_r001": {"receipt": prior_ref, "reason": "r001 omitted explicit --stop-after 835 and was terminated before a noncanonical 20-interval result could be accepted", "partial_output_reuse_forbidden": True, "same_scope_retry_forbidden": True},
        "invariants": {**prior_auth["invariants"], "full_native_interval_count_required": 835, "r001_partial_output_reuse_forbidden": True},
        "execution_controls": {"worker_started": False, "solver_started": False, "gpu_started": False, "queue_mutation": 0, "ledger_mutation": 0, "registry_mutation": 0},
    }
    spec = {**prior_spec, "job_id": JOB_ID, "logical_id": JOB_ID,
            "authorization": {"path": str(AUTHORIZATION.relative_to(LAB)), "required_status": authorization["status"], "one_attempt_only": True, "r001_partial_output_reuse_forbidden": True, "qualification_credit": 0}}
    return authorization, spec


def write(authorization_path: Path = AUTHORIZATION, spec_path: Path = JOB_SPEC) -> tuple[dict[str, Any], dict[str, Any]]:
    authorization_path, spec_path = Path(authorization_path).resolve(), Path(spec_path).resolve()
    if authorization_path.exists() or spec_path.exists():
        raise FileExistsError("refusing to overwrite immutable F3 row30 r002 authorization")
    authorization, spec = build()
    authorization_path.parent.mkdir(parents=True, exist_ok=True)
    authorization_path.write_text(json.dumps(authorization, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    spec_path.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return authorization, spec


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorization", type=Path, default=AUTHORIZATION)
    parser.add_argument("--job-spec", type=Path, default=JOB_SPEC)
    args = parser.parse_args(argv)
    auth, spec = write(args.authorization, args.job_spec)
    print(json.dumps({"status": auth["status"], "job_id": spec["job_id"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
