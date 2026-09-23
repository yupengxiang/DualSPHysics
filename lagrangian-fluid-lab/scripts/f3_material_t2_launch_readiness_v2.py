#!/usr/bin/env python3
"""Versioned F3 macro-material readiness audit with strict matrix-v2 wiring.

This is a JSON/source-only audit.  It reconciles the old static row-30 gap with
the separately authorized r003 attempt, but deliberately does not infer that
attempt's current process state or grant permission to start/retry any work.
"""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path
import sys
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts import f3_material_t2_launch_readiness_v1 as v1
from scripts import f3_native_mls_matrix_acceptance_v2 as matrix_v2


SCHEMA = "core.material.f3.t2.launch_readiness.v2"
DEFAULT_OUTPUT = Path(
    "campaigns/core-v1/material/evidence/"
    "f3-material-t2-launch-readiness-v2-20260923/receipt.json"
)

R003_AUTHORIZATION = Path(
    "campaigns/core-v1/material/evidence/"
    "f3-material-row30-core-cpu-r003-authorization-v1/authorization.json"
)
R003_JOB_SPEC = Path(
    "campaigns/core-v1/material/evidence/"
    "f3-material-row30-core-cpu-r003-authorization-v1/job-spec.json"
)

INPUTS: dict[str, Path] = {
    **v1.INPUTS,
    "native_mls_matrix_acceptance_adapter_v2": Path(
        "scripts/f3_native_mls_matrix_acceptance_v2.py"
    ),
    "row30_r003_authorization": R003_AUTHORIZATION,
    "row30_r003_job_spec": R003_JOB_SPEC,
    "launch_readiness_adapter_v2": Path(__file__).resolve(),
}


def _validate_r003_authorization(
    lab_root: str | Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    authorization = v1.load_json(lab_root, R003_AUTHORIZATION)
    job_spec = v1.load_json(lab_root, R003_JOB_SPEC)
    candidate = authorization.get("candidate", {})
    resources = authorization.get("resource_pool", {})
    invariants = authorization.get("invariants", {})

    expected_candidate = {
        "matrix_row": 30,
        "configuration_id": "F3-material-30",
        "q": 0.5,
        "seeds": 4096,
        "substeps": 4,
        "full_native_interval_count": 835,
    }
    if any(candidate.get(key) != value for key, value in expected_candidate.items()):
        raise ValueError("row30 r003 authorization does not match its frozen candidate")
    if authorization.get("schema") != "core.material.f3.row30.core_cpu_r003_authorization.v1":
        raise ValueError("row30 r003 authorization schema mismatch")
    if resources.get("max_attempts") != 1 or resources.get("cpu_cores") != 1:
        raise ValueError("row30 r003 authorization is not a single-core one-attempt grant")
    if resources.get("gpu_peak_mib") != 0 or resources.get("cpu_core_hour_cap", 0) > 16:
        raise ValueError("row30 r003 authorization exceeds its CPU-only resource boundary")
    if invariants.get("solver_forbidden") is not True or invariants.get("gpu_forbidden") is not True:
        raise ValueError("row30 r003 authorization does not preserve solver/GPU exclusions")

    argv = job_spec.get("argv", [])
    required_pairs = (("--seeds", "4096"), ("--substeps", "4"), ("--stop-after", "835"))
    if job_spec.get("schema") != "core.runtime.job_spec.v1":
        raise ValueError("row30 r003 job-spec schema mismatch")
    for flag, expected in required_pairs:
        try:
            index = argv.index(flag)
        except ValueError as exc:
            raise ValueError(f"row30 r003 job spec is missing {flag}") from exc
        if argv[index + 1 : index + 2] != [expected]:
            raise ValueError("row30 r003 job spec does not preserve the frozen full-window argv")
    if job_spec.get("timeout_seconds") != resources.get("timeout_seconds"):
        raise ValueError("row30 r003 authorization and job-spec timeout disagree")
    if job_spec.get("resources", {}).get("gpu_peak_mib") != 0:
        raise ValueError("row30 r003 job spec is not CPU-only")
    return authorization, job_spec


def _bind_inputs(lab_root: str | Path) -> dict[str, dict[str, Any]]:
    return {name: v1.bind_file(lab_root, path) for name, path in INPUTS.items()}


def build_audit(lab_root: str | Path) -> dict[str, Any]:
    root = Path(lab_root).resolve()
    result = v1.build_audit(root)
    authorization, job_spec = _validate_r003_authorization(root)
    result["schema"] = SCHEMA
    result["input_bindings"] = _bind_inputs(root)
    result["scope"].update(
        {
            "npz_opened": False,
            "trace_or_checkpoint_payload_opened": False,
            "runtime_process_state_observed": False,
        }
    )

    matrix_rows = result["plan_33_logical_configurations"]["rows"]
    row30 = matrix_rows[30]
    # v1 predates the authorized r003 attempt.  Preserve the historical row
    # evidence, but replace its stale "fresh authorization" next-gap with the
    # actual remaining operation: reconcile r003's JSON receipts first.
    row30["historical_status_precedes_r003"] = True
    row30["evidence_class"] = "authorized_attempt_without_terminal_acceptance_receipt"
    row30["next_gap"] = (
        "reconcile the separately authorized r003 attempt's immutable JSON receipts and "
        "checkpoint before deciding whether any later action is needed; do not retry from this audit"
    )
    result["plan_33_logical_configurations"]["availability_counts"] = {
        key: value
        for key, value in sorted(Counter(row["evidence_class"] for row in matrix_rows).items())
    }
    diagnostic_rows = result["plan_15_diagnostics"]["rows"]
    result["plan_15_diagnostics"]["availability_counts"] = {
        key: value
        for key, value in sorted(Counter(row["evidence_class"] for row in diagnostic_rows).items())
    }

    resource = authorization["resource_pool"]
    result["matrix_acceptance_v2"] = {
        "schema": matrix_v2.SCHEMA,
        "evidence_schema": matrix_v2.MATRIX_EVIDENCE_SCHEMA,
        "denominator_rows": matrix_v2.MATRIX_ROW_COUNT,
        "stage_row_counts": {
            "resolution_substep": 24,
            "cadence": 4,
            "seed_density": 5,
        },
        "row_acceptance_computed_from_typed_evidence": True,
        "caller_boolean_only_acceptance_rejected": True,
        "required_artifact_roles": ["comparison", "source_window", "checkpoint"],
        "at_least_one_of_artifact_roles": ["trace", "material_output"],
        "right_censored_counts_as_acceptance": False,
        "T2_macro": False,
        "T2_path": False,
        "qualification_credit": 0,
        "interpretation": (
            "the v2 adapter checks JSON evidence for all 33 rows under frozen gates; "
            "passing the adapter is neither independent root review nor T2 qualification"
        ),
    }
    result["row30_r003"] = {
        "candidate": authorization["candidate"],
        "authorization_schema": authorization["schema"],
        "authorization_record_status_at_issue": authorization["status"],
        "one_attempt_only": resource["max_attempts"] == 1,
        "cpu_cores": resource["cpu_cores"],
        "cpu_core_hour_cap": resource["cpu_core_hour_cap"],
        "estimated_core_hours": resource["estimated_core_hours"],
        "timeout_seconds": resource["timeout_seconds"],
        "solver_forbidden": authorization["invariants"]["solver_forbidden"],
        "gpu_forbidden": authorization["invariants"]["gpu_forbidden"],
        "job_spec_schema": job_spec["schema"],
        "runtime_process_state_observed": False,
        "authorization_status_is_not_runtime_status": True,
        "next_operation": "reconcile existing attempt's JSON receipts before any retry decision",
        "retry_or_launch_authorized_by_this_audit": False,
        "T2_credit": 0,
    }
    result["next_executable_step"] = {
        "status": "reconcile_existing_authorized_row30_attempt_before_any_retry_decision",
        "candidate_matrix_row": 30,
        "candidate_configuration_id": row30["configuration_id"],
        "required_action": (
            "inspect append-only JSON attempt receipts/checkpoint to establish r003 terminal state; "
            "do not open HDF5/NPZ payloads or start/retry work from this readiness audit"
        ),
        "runtime_state_observed": False,
        "retry_or_launch_authorized": False,
        "T2_credit": "none",
    }
    result["audit_status"] = "static_matrix_v2_integrated_runtime_reconciliation_required"
    result["hard_boundaries"].update(
        {
            "runtime_process_state_observed": False,
            "r003_attempt_started_by_this_audit": False,
            "matrix_acceptance_v2_grants_T2": False,
        }
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    root = args.lab_root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(build_audit(root), indent=2, sort_keys=True, allow_nan=False) + "\n"
    with output.open("x", encoding="utf-8") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps({"schema": SCHEMA, "output": str(output.resolve())}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
