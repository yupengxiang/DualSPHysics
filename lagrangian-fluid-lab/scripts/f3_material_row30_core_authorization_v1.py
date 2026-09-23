#!/usr/bin/env python3
"""Authorize and construct one isolated Core CPU attempt for F3 material row 30.

The expired L1 ledger is immutable historical evidence.  This module creates
no replacement for it: it records a separate, bounded Core exploration pool
and an exact runtime job for the one canonical s4/4096 row.  Submitting the
job is deliberately a separate action; this module never starts a worker.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
EVIDENCE = LAB / "campaigns/core-v1/material/evidence"
DECISION = EVIDENCE / "f3-material-row30-root-decision-v1/packet.json"
PREFLIGHT = EVIDENCE / "f3-material-row30-resource-preflight-v1/receipt.json"
SOURCE = LAB / "campaigns/l1-resume/data/continuation/F3_CELL3_LONG_dp0p0075_a1p000_noslip_visco1_nopen.h5"
PREPARED = LAB / "campaigns/l1-resume/continuation/F3_CELL3_LONG_dp0p0075_a1p000_noslip_visco1_nopen-PREPARED.json"
BACKEND = LAB / "scripts/f3_native_volume_mls.py"
AUTHORIZATION = EVIDENCE / "f3-material-row30-core-cpu-authorization-v1/authorization.json"
JOB_SPEC = EVIDENCE / "f3-material-row30-core-cpu-authorization-v1/job-spec.json"

SOURCE_SHA256 = "fb304e0bc8e5d7f51eaab0af0d8dba8c928b8146e0bf5776002f83012e4480c4"
PREPARED_SHA256 = "23d151c07c53c83b3048be9b665722161baaef37fc31e6ce6ec42e4b26b36894"
JOB_ID = "f3-material-30-canonical-s4-r001"
OUTPUT_NAMESPACE = "campaigns/core-v1/material/attempts/f3-material-30-canonical-s4-r001"
TIMEOUT_SECONDS = 21600
CPU_CORE_HOUR_CAP = 13.0


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            value.update(block)
    return value.hexdigest()


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def ref(path: Path, role: str, *, expected: str | None = None) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    actual = sha256(path)
    if expected is not None and actual != expected:
        raise ValueError(f"hash mismatch for {path}")
    return {"path": str(path.relative_to(LAB)), "role": role, "bytes": path.stat().st_size, "sha256": actual}


def build() -> tuple[dict[str, Any], dict[str, Any]]:
    decision, preflight = read(DECISION), read(PREFLIGHT)
    candidate = decision.get("candidate", {})
    if (candidate.get("configuration_id"), candidate.get("matrix_row"), candidate.get("seeds"), candidate.get("substeps")) != ("F3-material-30", 30, 4096, 4):
        raise ValueError("row30 decision is not the canonical s4/4096 candidate")
    if preflight.get("status") != "blocked_no_worker_authorized":
        raise ValueError("expected immutable historical-budget block")
    if not {"historical resource ledger has expired", "historical CPU core-hour cap is already exceeded before row30 reservation"}.issubset(set(preflight.get("blockers", []))):
        raise ValueError("historical preflight blockers changed")
    backend = ref(BACKEND, "frozen canonical current-frame MLS backend")
    inputs = [
        ref(SOURCE, "read-only registered production CFD source", expected=SOURCE_SHA256),
        ref(PREPARED, "registered production source preparation", expected=PREPARED_SHA256),
        backend,
    ]
    authorization = {
        "schema": "core.material.f3.row30.core_cpu_authorization.v1",
        "status": "authorized_one_cpu_attempt_not_started",
        "authority": "user grants all subsequent exploration authorizations in this task",
        "purpose": "isolated Core resource pool after the historical L1 ledger expired",
        "historical_ledger": {"path": str(PREFLIGHT.relative_to(LAB)), "status": preflight["status"], "must_not_modify": True},
        "candidate": {"configuration_id": "F3-material-30", "matrix_row": 30, "q": 0.5, "seeds": 4096, "substeps": 4, "window": "full native 0--8.35 s"},
        "resource_pool": {"pool_id": "core-f3-material-row30-cpu-r001", "max_attempts": 1, "cpu_cores": 2, "ram_mib": 8192, "gpu_peak_mib": 0, "io_weight": 0.25, "timeout_seconds": TIMEOUT_SECONDS, "cpu_core_hour_cap": CPU_CORE_HOUR_CAP, "estimated_core_hours": 12.0},
        "new_output_namespace": OUTPUT_NAMESPACE,
        "input_bindings": {item["role"]: item for item in inputs},
        "invariants": {"source_read_only": True, "historical_s2_output_reuse_forbidden": True, "threshold_relaxation_forbidden": True, "same_argv_resume_only": True, "solver_forbidden": True, "gpu_forbidden": True, "T2_macro": False, "T2_path": False, "qualification_credit": 0},
        "execution_controls": {"worker_started": False, "solver_started": False, "gpu_started": False, "queue_mutation": 0, "ledger_mutation": 0, "registry_mutation": 0},
    }
    spec = {
        "schema": "core.runtime.job_spec.v1", "job_id": JOB_ID, "logical_id": JOB_ID,
        "category": "material_qualification_diagnostic", "attempt_role": "initial",
        "cwd": str(LAB), "host": "ada", "timeout_seconds": TIMEOUT_SECONDS,
        "argv": [str(LAB / ".venv/bin/python"), str(BACKEND), "--source", str(SOURCE), "--prepared", str(PREPARED), "--output", "{attempt_dir}/trace.h5", "--audit-output", "{attempt_dir}/source-preflight.json", "--seeds", "4096", "--substeps", "4"],
        "env": {"OMP_NUM_THREADS": "2", "OPENBLAS_NUM_THREADS": "2", "MKL_NUM_THREADS": "2"},
        "resources": {"cpu_cores": 2, "ram_mib": 8192, "gpu_peak_mib": 0, "io_weight": 0.25},
        "min_free_disk_bytes": 8 * 1024**3,
        "required_outputs": ["trace.h5", "trace.summary.json", "source-preflight.json", "trace.h5.checkpoint.json"],
        "input_files": [{"path": str(SOURCE), "sha256": SOURCE_SHA256}, {"path": str(PREPARED), "sha256": PREPARED_SHA256}, {"path": str(BACKEND), "sha256": backend["sha256"]}],
        "authorization": {"path": str(AUTHORIZATION.relative_to(LAB)), "required_status": authorization["status"], "one_attempt_only": True, "historical_ledger_mutation_forbidden": True, "qualification_credit": 0},
    }
    return authorization, spec


def write(authorization_path: Path = AUTHORIZATION, spec_path: Path = JOB_SPEC) -> tuple[dict[str, Any], dict[str, Any]]:
    authorization_path, spec_path = Path(authorization_path).resolve(), Path(spec_path).resolve()
    if authorization_path.exists() or spec_path.exists():
        raise FileExistsError("refusing to overwrite immutable F3 row30 Core authorization")
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
