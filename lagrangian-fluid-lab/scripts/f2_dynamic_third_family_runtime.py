#!/usr/bin/env python3
"""Create a hash-bound job spec for one approved F2 dynamic matrix row.

The candidate and its fifteen-cell denominator are deliberately separate from
runtime authorization.  This adapter verifies the fixed matrix, lineage
clarification, CPU/native preflight, and a root review that authorizes exactly
one scientific row.  It only writes a job specification; the queue worker is
the only component allowed to run the solver and produce an attempt.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts import core_cfd

SCHEMA = "core.f2.dynamic_third_family.runtime_job_adapter.v1"
JOB_SCHEMA = "core.cfd.job.v1"
REVIEW_SCHEMA = "core.root_review.v1"
SCOPE_ID = "F2_dynamic_third_family_dbc_duration_x_v1"
REVISION_ID = "F2_dynamic_third_family_dbc_duration_v1"
TARGET_CASE = "CORE_F2_DYNAMIC_THIRD_DBC_DURATION_q0p75000000_dp0p007500000000_held_out"
TARGET_Q = 0.75
TARGET_DP = 0.0075
JOB_ID = "f2-dynamic-third-family-dbc-duration-q0p75-dp0075-canary-001"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    partial.replace(path)


def ref(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": str(path), "sha256": digest(path), "bytes": path.stat().st_size, "role": role}


def _verify_review(review_path: Path, *, target_case: str) -> dict[str, Any]:
    review = read_json(review_path)
    if review.get("schema") != REVIEW_SCHEMA:
        raise ValueError("root review schema mismatch")
    if review.get("decision") != "approved_for_first_scientific_row":
        raise ValueError("review does not authorize the first scientific row")
    if review.get("scope_id") != SCOPE_ID or review.get("revision_id") != REVISION_ID:
        raise ValueError("root review scope/revision mismatch")
    if target_case not in review.get("authorized_case_ids", []):
        raise ValueError("target case is not explicitly authorized")
    controls = review.get("authorization", {})
    for key in ("solver_launch", "gpu_launch", "job_spec_creation", "queue_mutation", "ledger_mutation"):
        if controls.get(key) is not True:
            raise ValueError(f"root review does not authorize {key}")
    if controls.get("registry_mutation") is not False:
        raise ValueError("registry mutation must remain forbidden")
    if review.get("qualification_claim") != "none":
        raise ValueError("runtime review must carry qualification_claim=none")
    return review


def _matrix_row(matrix: dict[str, Any], case_id: str) -> dict[str, Any]:
    rows = [row for row in matrix.get("cells", []) if row.get("case_id") == case_id]
    if len(rows) != 1:
        raise ValueError(f"expected exactly one matrix row for {case_id}, found {len(rows)}")
    row = rows[0]
    if row.get("status") != "not_started":
        raise ValueError("target matrix row is no longer unattempted")
    if float(row.get("q")) != TARGET_Q or float(row.get("dp_m")) != TARGET_DP:
        raise ValueError("target row parameters do not match the approved anchor")
    return row


def create_job(
    *,
    lab: Path,
    prepared: Path,
    candidate: Path,
    matrix: Path,
    lineage: Path,
    review_path: Path,
    output: Path,
) -> dict[str, Any]:
    lab = Path(lab).resolve()
    prepared = Path(prepared).resolve()
    candidate = Path(candidate).resolve()
    matrix = Path(matrix).resolve()
    lineage = Path(lineage).resolve()
    review_path = Path(review_path).resolve()
    prepared_payload = read_json(prepared)
    candidate_payload = read_json(candidate)
    matrix_payload = read_json(matrix)
    lineage_payload = read_json(lineage)
    review = _verify_review(review_path, target_case=TARGET_CASE)
    row = _matrix_row(matrix_payload, TARGET_CASE)

    if prepared_payload.get("schema") != "core.cfd.v1" or prepared_payload.get("preflight_pass") is not True:
        raise ValueError("prepared target is not a passing CPU/native preflight")
    config = prepared_payload.get("config", {})
    if config.get("scope_id") != SCOPE_ID or config.get("revision_id") != "F2_dynamic_third_family_dbc_duration_q0p75_anchor_v1":
        raise ValueError("prepared scope/revision mismatch")
    if config.get("case_id") != "CORE_F2_DYNAMIC_THIRD_DBC_DURATION_q0p75000000_dp0p007500000000_anchor":
        raise ValueError("anchor preflight is not the approved input")
    if float(config.get("parameter", {}).get("q")) != TARGET_Q or float(config.get("dp_m")) != TARGET_DP:
        raise ValueError("anchor preflight parameters mismatch")
    if config.get("qualification_only") is not True or config.get("qualified") is not False:
        raise ValueError("target must remain qualification-only and unqualified")
    if prepared_payload.get("execution_controls", {}).get("solver_allowed") is not False:
        raise ValueError("CPU preflight must not authorize solver launch itself")
    if lineage_payload.get("candidate_comparison", {}).get("candidate_q") != TARGET_Q:
        raise ValueError("lineage clarification does not bind target q")
    if lineage_payload.get("candidate_comparison", {}).get("candidate_prepared_geometry_changed_relative_to_dynamic_baseline") is not False:
        raise ValueError("dynamic baseline geometry is not closed")
    if candidate_payload.get("scope_id") != SCOPE_ID or candidate_payload.get("qualified") is not False:
        raise ValueError("candidate card is not the unqualified target scope")
    if matrix_payload.get("denominator") != 15 or matrix_payload.get("numerator") != 0:
        raise ValueError("matrix denominator/numerator was changed before the first row")

    solver = Path(prepared_payload["solver_binary"]).resolve()
    decoder = Path(prepared_payload["decoder"]).resolve()
    for item in (solver, decoder):
        if not item.is_file():
            raise FileNotFoundError(item)
    input_files = [
        ref(prepared, "q=.75 CPU/native anchor preflight"),
        ref(candidate, "independent third-family candidate card"),
        ref(matrix, "fixed fifteen-row qualification matrix"),
        ref(lineage, "static-source/dynamic-baseline lineage clarification"),
        ref(review_path, "root approval for one first scientific row"),
        ref(solver, "pinned DualSPHysics solver"),
        ref(decoder, "pinned native decoder"),
    ]
    output = Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"job output is not fresh: {output}")
    spec: dict[str, Any] = {
        "schema": JOB_SCHEMA,
        "job_id": JOB_ID,
        "logical_id": JOB_ID,
        "attempt_role": "first_scientific_matrix_row",
        "category": "f2_dynamic_third_family_scientific_canary",
        "host": "ada",
        "source_lab": str(lab),
        "cwd": str(lab),
        "argv": [
            str(lab / ".venv/bin/python"),
            str(lab / "scripts/core_f2_qualification.py"),
            "--lab-root", str(lab), "run", "--prepared", str(prepared),
            "--output", "{attempt_dir}/product",
        ],
        "required_outputs": [
            "product/result.json", "product/trajectory.h5", "product/audit.json",
            "product/observations.json",
        ],
        "resources": {"cpu_cores": 4, "ram_mib": 32768, "gpu_peak_mib": 12288, "io_weight": 2},
        "timeout_seconds": 14400,
        "depends_on": [],
        "qualification_claim": "none",
        "qualification_status": "first-row scientific canary; fifteen-row F2 scope remains unqualified",
        "input_files": input_files,
        "prepared_case_id": str(config["case_id"]),
        "matrix_case_id": TARGET_CASE,
        "matrix_index": int(row["index"]),
        "registered_window_s": float(config["time_max_s"]),
        "output_interval_s": float(config["output_interval_s"]),
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "family": "F2",
        "parameter_axis": "rotation_duration_s",
        "parameter_q": TARGET_Q,
        "parameter_dp_m": TARGET_DP,
        "root_review_decision": review["decision"],
        "solver_launch_authorized": True,
        "gpu_launch_authorized": True,
        "job_spec_creation_authorized": True,
        "queue_mutation_authorized": True,
        "ledger_mutation_authorized": True,
        "registry_mutation_authorized": False,
        "worker_contract": "core_runtime worker; scheduler supplies one CUDA UUID and solver uses -gpu:0",
        "postcondition": "hard_integrity_pass=true and requested_horizon_reached=true and event_window_complete=true are required for any future scope review",
    }
    write_json(output, spec)
    return spec


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lab-root", type=Path, default=LAB_ROOT)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--lineage", type=Path, required=True)
    parser.add_argument("--root-review", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = create_job(
        lab=args.lab_root, prepared=args.prepared, candidate=args.candidate,
        matrix=args.matrix, lineage=args.lineage, review_path=args.root_review,
        output=args.output,
    )
    print(json.dumps({"schema": SCHEMA, "job_id": result["job_id"], "case_id": result["prepared_case_id"],
                      "matrix_index": result["matrix_index"], "qualification_claim": result["qualification_claim"],
                      "registry_mutation_authorized": result["registry_mutation_authorized"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
