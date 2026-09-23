#!/usr/bin/env python3
"""Freeze the throughput-corrected F3 row-30 full-window r003 CPU job."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from scripts import f3_material_row30_core_r002_authorization_v1 as r002


LAB = r002.LAB
EVIDENCE = r002.EVIDENCE
R002_RECEIPT = LAB / "campaigns/core-v1/runtime/attempts/f3-material-30-canonical-s4-r002/20260923T104659-14c9b207b747/result.json"
R002_STDOUT = R002_RECEIPT.parent / "stdout.log"
AUTHORIZATION = EVIDENCE / "f3-material-row30-core-cpu-r003-authorization-v1/authorization.json"
JOB_SPEC = EVIDENCE / "f3-material-row30-core-cpu-r003-authorization-v1/job-spec.json"
JOB_ID = "f3-material-30-canonical-s4-r003"
OUTPUT_NAMESPACE = "campaigns/core-v1/material/attempts/f3-material-30-canonical-s4-r003"
TIMEOUT_SECONDS = 16 * 3600
CPU_CORE_HOUR_CAP = 16.0


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            value.update(block)
    return value.hexdigest()


def build() -> tuple[dict[str, Any], dict[str, Any]]:
    previous_authorization, previous_spec = r002.build()
    if not R002_RECEIPT.is_file() or not R002_STDOUT.is_file():
        raise FileNotFoundError("closed r002 throughput evidence is required")
    receipt = json.loads(R002_RECEIPT.read_text(encoding="utf-8"))
    lines = [line for line in R002_STDOUT.read_text(encoding="utf-8").splitlines() if line.startswith("{\"frame\"")]
    if receipt.get("execution_status") != "failed" or receipt.get("returncode") != -15 or len(lines) != 5:
        raise ValueError("r002 must remain the closed five-interval throughput observation")
    measured_seconds = float(receipt["usage"]["wall_seconds"])
    seconds_per_interval = measured_seconds / len(lines)
    estimated_full_seconds = seconds_per_interval * 835
    if not 12 * 3600 < estimated_full_seconds < TIMEOUT_SECONDS:
        raise ValueError("throughput-derived full-window estimate no longer justifies the r003 timeout")
    r002_ref = {"receipt": {"path": str(R002_RECEIPT.relative_to(LAB)), "sha256": digest(R002_RECEIPT)}, "stdout": {"path": str(R002_STDOUT.relative_to(LAB)), "sha256": digest(R002_STDOUT)}, "measured_completed_intervals": len(lines), "measured_wall_seconds": measured_seconds, "measured_seconds_per_interval": seconds_per_interval, "linear_full_835_estimate_seconds": estimated_full_seconds, "partial_output_reuse_forbidden": True}
    authorization = {
        **previous_authorization,
        "schema": "core.material.f3.row30.core_cpu_r003_authorization.v1",
        "status": "authorized_one_cpu_attempt_not_started",
        "purpose": "one full-window r003 attempt with timeout derived from closed r002 throughput evidence",
        "resource_pool": {**previous_authorization["resource_pool"], "pool_id": "core-f3-material-row30-cpu-r003", "max_attempts": 1, "cpu_cores": 1, "timeout_seconds": TIMEOUT_SECONDS, "cpu_core_hour_cap": CPU_CORE_HOUR_CAP, "estimated_core_hours": estimated_full_seconds / 3600.0},
        "new_output_namespace": OUTPUT_NAMESPACE,
        "closed_r002_throughput_evidence": r002_ref,
        "invariants": {**previous_authorization["invariants"], "r002_partial_output_reuse_forbidden": True, "full_native_interval_count_required": 835, "no_backend_or_threshold_change": True},
        "execution_controls": {"worker_started": False, "solver_started": False, "gpu_started": False, "queue_mutation": 0, "ledger_mutation": 0, "registry_mutation": 0},
    }
    spec = {**previous_spec, "job_id": JOB_ID, "logical_id": JOB_ID, "timeout_seconds": TIMEOUT_SECONDS,
            "resources": {**previous_spec["resources"], "cpu_cores": 1},
            "env": {**previous_spec["env"], "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"},
            "authorization": {"path": str(AUTHORIZATION.relative_to(LAB)), "required_status": authorization["status"], "one_attempt_only": True, "r002_partial_output_reuse_forbidden": True, "qualification_credit": 0}}
    return authorization, spec


def write(authorization_path: Path = AUTHORIZATION, spec_path: Path = JOB_SPEC) -> tuple[dict[str, Any], dict[str, Any]]:
    authorization_path, spec_path = Path(authorization_path).resolve(), Path(spec_path).resolve()
    if authorization_path.exists() or spec_path.exists():
        raise FileExistsError("refusing to overwrite immutable F3 row30 r003 authorization")
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
    authorization, spec = write(args.authorization, args.job_spec)
    print(json.dumps({"status": authorization["status"], "job_id": spec["job_id"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
