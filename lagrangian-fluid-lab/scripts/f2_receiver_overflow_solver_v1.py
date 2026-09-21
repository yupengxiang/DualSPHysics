#!/usr/bin/env python3
"""Hash-bound one-anchor worker for the F2 receiver/overflow-weir scope.

The static proposal and pure observer are deliberately separate from this
module.  A root review may authorize exactly one matrix row; this module then
creates a normal ``core.cfd.job.v1`` description or runs that one protected
worker.  The worker writes a solver trajectory and hard-audit receipt, but it
never mutates the scientific registry and never grants T1 credit.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import os
import subprocess
import sys
import time
from typing import Any

import numpy as np

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts import core_cfd
from scripts.f2_receiver_overflow_runtime_v1 import (
    DEFAULT_BASE,
    PROPOSAL_SCHEMA,
    audit_hdf5_trajectory,
    load,
)


ROOT_REVIEW_SCHEMA = "core.root_review.v1"
JOB_SCHEMA = "core.cfd.job.v1"
RUNTIME_SCHEMA = "core.f2.receiver_overflow_weir.solver_worker.v1"
REVIEW_DECISION = "approved_for_one_anchor_runtime"
SCOPE_ID = "F2_receiver_overflow_weir_v1"
REVISION_ID = "F2_receiver_overflow_weir_mdbc_v1"
MATRIX_INDEX = 4
MATRIX_CASE_ID = "CORE_F2_RECEIVER_OVERFLOW_WEIR_q0p50000000_crest0p26000000_dp0p007500000000_spatial"
RETRY_OF = "f2-receiver-overflow-weir-q05-dp0075-anchor-001"
JOB_ID = "f2-receiver-overflow-weir-q05-dp0075-anchor-002"


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(path: Path) -> str:
    return core_cfd.digest(Path(path))


def write_json(path: Path, value: dict[str, Any]) -> None:
    core_cfd.write_json(Path(path), value)


def _ref(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": str(path), "sha256": digest(path), "bytes": path.stat().st_size, "role": role}


def _static_paths(base: Path) -> dict[str, Path]:
    base = Path(base).resolve()
    return {
        "candidate": base / "candidate-card-v1.json",
        "matrix": base / "fixed-matrix-v1.json",
        "failure_denominator": base / "failure-denominator-v1.json",
        "lineage": base / "lineage-clarification-v1.json",
        "preflight": base / "cpu-native-preflight-v1.json",
        "proposal": base / "runtime-prepared-proposal-v1.json",
        "adapter": LAB_ROOT / "scripts/core_f2_receiver_overflow_weir_v1.py",
        "preparation": LAB_ROOT / "scripts/f2_receiver_overflow_runtime_v1.py",
        "solver_worker": Path(__file__).resolve(),
    }


def _review_bindings(base: Path, proposal: dict[str, Any]) -> dict[str, str]:
    paths = _static_paths(base)
    bindings = {
        "candidate": digest(paths["candidate"]),
        "matrix": digest(paths["matrix"]),
        "failure_denominator": digest(paths["failure_denominator"]),
        "lineage": digest(paths["lineage"]),
        "preflight": digest(paths["preflight"]),
        "proposal": digest(paths["proposal"]),
        "adapter": digest(paths["adapter"]),
        "preparation": digest(paths["preparation"]),
        "solver_worker": digest(paths["solver_worker"]),
        "native_bi4": str(proposal["input_hashes"]["native_bi4"]),
        "definition": str(proposal["input_hashes"]["definition"]),
        "native_metadata": str(proposal["input_hashes"]["native_metadata"]),
        "solver_binary": str(proposal["solver_sha256"]),
        "decoder": str(proposal["decoder_sha256"]),
    }
    return bindings


def _matrix_row(base: Path) -> dict[str, Any]:
    matrix = load(Path(base) / "fixed-matrix-v1.json")
    rows = [row for row in matrix.get("rows", []) if int(row.get("index", -1)) == MATRIX_INDEX]
    if len(rows) != 1:
        raise ValueError("exactly one protected F2 matrix row is required")
    row = rows[0]
    if row.get("case_id") != MATRIX_CASE_ID or row.get("status") != "not_started":
        raise ValueError("protected F2 row changed or already attempted")
    if float(row.get("q")) != 0.5 or float(row.get("dp_m")) != 0.0075 or row.get("design_cell") != "spatial":
        raise ValueError("protected F2 row parameters changed")
    return row


def make_root_review(base: Path = DEFAULT_BASE, output: Path | None = None) -> dict[str, Any]:
    """Create an exact-one-anchor review after the proposal is prepared."""
    base = Path(base).resolve()
    paths = _static_paths(base)
    proposal = load(paths["proposal"])
    if proposal.get("schema") != PROPOSAL_SCHEMA or proposal.get("root_review_required") is not True:
        raise ValueError("prepared proposal is not the protected proposal-only schema")
    if proposal.get("scope_id") != SCOPE_ID or proposal.get("revision_id") != REVISION_ID:
        raise ValueError("proposal scope/revision mismatch")
    if proposal.get("qualification_claim") != "none" or proposal.get("matrix_credit") != 0:
        raise ValueError("proposal cannot carry scientific credit")
    row = _matrix_row(base)
    bindings = _review_bindings(base, proposal)
    review = {
        "schema": ROOT_REVIEW_SCHEMA,
        "created_at_utc": stamp(),
        "decision": REVIEW_DECISION,
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "family": "F2",
        "qualification_claim": "none",
        "matrix_credit": 0,
        "authorized_case_ids": [str(proposal["config"]["case_id"])],
        "authorized_matrix_indices": [MATRIX_INDEX],
        "authorized_matrix_case_ids": [MATRIX_CASE_ID],
        "exact_one_anchor": True,
        "authorized_row": {
            "index": MATRIX_INDEX,
            "row_id": row["row_id"],
            "case_id": MATRIX_CASE_ID,
            "q": 0.5,
            "crest_height_m": 0.26,
            "dp_m": 0.0075,
            "design_cell": "spatial",
        },
        "authorization": {
            "runtime_preparation": True,
            "solver_launch": True,
            "gpu_launch": True,
            "job_spec_creation": True,
            "queue_mutation": True,
            "ledger_mutation": True,
            "registry_mutation": False,
            "matrix_submission": False,
        },
        "input_hash_bindings": bindings,
        "execution_boundary": {
            "one_anchor_only": True,
            "same_input_retry": False,
            "horizon_extension_before_anchor": False,
            "threshold_relaxation": False,
            "solver_result_is_not_qualification": True,
            "event_censoring_stays_in_denominator": True,
            "registry_update_requires_separate_scientific_admission": True,
        },
        "review_findings": {
            "candidate_mechanism_distinct": True,
            "v4_native_mass_gate_pass": True,
            "adapter_contract_reviewed": True,
            "proposal_hard_audit_implemented": True,
            "physical_trajectory_observed": False,
            "range_qualification": False,
        },
    }
    if output is not None:
        write_json(Path(output), review)
    return review


def _verify_review(base: Path, proposal: dict[str, Any], review_path: Path) -> dict[str, Any]:
    review = load(Path(review_path))
    if review.get("schema") != ROOT_REVIEW_SCHEMA or review.get("decision") != REVIEW_DECISION:
        raise ValueError("root review does not authorize this one-anchor runtime")
    if review.get("scope_id") != SCOPE_ID or review.get("revision_id") != REVISION_ID:
        raise ValueError("root review scope/revision mismatch")
    if review.get("qualification_claim") != "none" or review.get("matrix_credit") != 0:
        raise ValueError("root review may not grant qualification credit")
    if review.get("exact_one_anchor") is not True:
        raise ValueError("root review must be exact-one-anchor")
    if review.get("authorized_case_ids") != [str(proposal["config"]["case_id"])]:
        raise ValueError("root review authorized case list is not exact")
    if review.get("authorized_matrix_indices") != [MATRIX_INDEX] or review.get("authorized_matrix_case_ids") != [MATRIX_CASE_ID]:
        raise ValueError("root review authorized matrix row is not exact")
    controls = review.get("authorization", {})
    for key in ("runtime_preparation", "solver_launch", "gpu_launch", "job_spec_creation", "queue_mutation", "ledger_mutation"):
        if controls.get(key) is not True:
            raise ValueError(f"root review does not authorize {key}")
    if controls.get("registry_mutation") is not False or controls.get("matrix_submission") is not False:
        raise ValueError("registry and matrix mutation must remain forbidden")
    expected = _review_bindings(base, proposal)
    if review.get("input_hash_bindings") != expected:
        raise ValueError("root review input hash bindings are stale")
    return review


def make_job(base: Path = DEFAULT_BASE, review_path: Path | None = None, output: Path | None = None) -> dict[str, Any]:
    base = Path(base).resolve()
    paths = _static_paths(base)
    proposal = load(paths["proposal"])
    if review_path is None or output is None:
        raise ValueError("review and output paths are required")
    review = _verify_review(base, proposal, Path(review_path))
    row = _matrix_row(base)
    solver = Path(proposal["solver_binary"]).resolve()
    decoder = Path(proposal["decoder"]).resolve()
    for item in (solver, decoder):
        if not item.is_file():
            raise FileNotFoundError(item)
    input_files = [
        _ref(paths["proposal"], "protected prepared F2 anchor proposal"),
        _ref(paths["candidate"], "F2 candidate card"),
        _ref(paths["matrix"], "fixed fifteen-row denominator"),
        _ref(paths["failure_denominator"], "failure denominator"),
        _ref(paths["lineage"], "new F2 physical lineage"),
        _ref(Path(review_path), "exact-one-anchor root review"),
        _ref(paths["adapter"], "pure receiver/crest observer"),
        _ref(paths["preparation"], "proposal preparation implementation"),
        _ref(paths["solver_worker"], "solver-integrated worker"),
        _ref(solver, "pinned DualSPHysics solver"),
        _ref(decoder, "pinned native decoder"),
    ]
    output = Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"job output is not fresh: {output}")
    spec = {
        "schema": JOB_SCHEMA,
        "job_id": JOB_ID,
        "logical_id": JOB_ID,
        "retry_of": RETRY_OF,
        "retry_reason": "infrastructure_contract_field_lookup_fixed; first attempt failed before solver launch",
        "attempt_role": "protected_single_scientific_anchor",
        "category": "qualification_canary",
        "host": "ada",
        "source_lab": str(LAB_ROOT),
        "cwd": str(LAB_ROOT),
        "argv": [
            str(LAB_ROOT / ".venv/bin/python"),
            str(Path(__file__).resolve()),
            "run",
            "--prepared", str(paths["proposal"]),
            "--root-review", str(Path(review_path).resolve()),
            "--output", "{attempt_dir}/product",
        ],
        "required_outputs": ["product/result.json", "product/trajectory.h5", "product/audit.json", "product/observations.json"],
        "resources": {"cpu_cores": 4, "ram_mib": 32768, "gpu_peak_mib": 12288, "io_weight": 2},
        "timeout_seconds": 3600,
        "depends_on": [],
        "qualification_claim": "none",
        "qualification_status": "one-anchor scientific canary; matrix remains unqualified",
        "input_files": input_files,
        "prepared_case_id": str(proposal["config"]["case_id"]),
        "matrix_case_id": MATRIX_CASE_ID,
        "matrix_index": MATRIX_INDEX,
        "registered_window_s": float(proposal["config"]["time_max_s"]),
        "maximum_extended_window_s": float(proposal["config"]["event_window"]["maximum_extended_time_max_s"]),
        "output_interval_s": float(proposal["config"]["output_interval_s"]),
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "family": "F2",
        "parameter_axis": "weir_crest_height_m",
        "parameter_q": 0.5,
        "parameter_value": 0.26,
        "root_review_decision": REVIEW_DECISION,
        "solver_launch_authorized": True,
        "gpu_launch_authorized": True,
        "job_spec_creation_authorized": True,
        "queue_mutation_authorized": True,
        "ledger_mutation_authorized": True,
        "registry_mutation_authorized": False,
        "matrix_submission_authorized": False,
        "worker_contract": "core_runtime worker; scheduler supplies one CUDA UUID and solver uses -gpu:0",
        "postcondition": "retain solver result; hard integrity and complete crest/receiver event are required before any separate scope review",
    }
    write_json(output, spec)
    return spec


def _verify_runtime_inputs(base: Path, proposal: dict[str, Any], review: dict[str, Any]) -> None:
    if proposal.get("schema") != PROPOSAL_SCHEMA or proposal.get("preflight_pass") is not True:
        raise ValueError("F2 proposal is not a passing prepared input")
    controls = proposal.get("execution_controls", {})
    if controls.get("solver_invoked") is not False or controls.get("gpu_invoked") is not False:
        raise ValueError("proposal input already contains runtime execution")
    if proposal.get("qualification_claim") != "none" or proposal.get("matrix_credit") != 0:
        raise ValueError("proposal input carries scientific credit")
    _verify_review(base, proposal, Path(review["_path"]))
    native = proposal["native_initial"]
    if int(native["fluid_particles"]) <= 0 or native["normal_decode_probe"] != "passed":
        raise ValueError("native anchor preflight is incomplete")
    for key, hash_key in (("solver_binary", "solver_sha256"), ("decoder", "decoder_sha256")):
        path = Path(proposal[key]).resolve()
        if not path.is_file() or digest(path) != proposal[hash_key]:
            raise ValueError(f"{key} hash mismatch")
    if digest(Path(proposal["native_initial"]["native_bi4"])) != proposal["native_initial"]["native_bi4_sha256"]:
        raise ValueError("native initial BI4 changed")


def run_worker(prepared_path: Path, review_path: Path, output: Path, base: Path = DEFAULT_BASE) -> dict[str, Any]:
    base = Path(base).resolve()
    prepared_path, review_path, output = Path(prepared_path).resolve(), Path(review_path).resolve(), Path(output).resolve()
    proposal = load(prepared_path)
    review = load(review_path)
    review["_path"] = str(review_path)
    _verify_runtime_inputs(base, proposal, review)
    visible = os.environ.get("CUDA_VISIBLE_DEVICES", "")
    if not visible or "," in visible:
        raise ValueError("coordinator must provide exactly one CUDA_VISIBLE_DEVICES device")
    if output.exists() and any(output.iterdir()):
        raise ValueError("worker output must be fresh")
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "prepared.json", proposal)
    solver_output = output / "solver"
    argv = [proposal["solver_binary"], "-gpu:0", *proposal["solver_arguments"], proposal["generated_prefix"], str(solver_output)]
    started = time.monotonic()
    write_json(output / "worker-status.json", {
        "schema": RUNTIME_SCHEMA,
        "status": "running",
        "argv": argv,
        "started_at_utc": stamp(),
        "cuda_visible_devices": visible,
        "qualification_claim": "none",
    })
    with (output / "solver.stdout.log").open("w") as stream:
        process = subprocess.run(argv, cwd=output, env=core_cfd.environment(LAB_ROOT), stdout=stream, stderr=subprocess.STDOUT)
    elapsed = time.monotonic() - started
    stdout = (output / "solver.stdout.log").read_text(errors="replace")
    if process.returncode or "Finished execution (code=0)" not in stdout:
        write_json(output / "worker-status.json", {
            "schema": RUNTIME_SCHEMA,
            "status": "solver_failed",
            "returncode": process.returncode,
            "elapsed_seconds": elapsed,
            "qualification_claim": "none",
        })
        raise RuntimeError("F2 receiver/overflow solver failed; raw attempt retained")

    # ``convert_native`` needs the same prepared fields as the generic Core
    # converter.  The proposal already carries those fields and the observer
    # performs the receiver-specific finite-geometry audit afterwards.
    conversion = core_cfd.convert_native(proposal, solver_output / "data", output / "trajectory.h5")
    audit = audit_hdf5_trajectory(prepared_path, output / "trajectory.h5")
    observations = {
        "schema": "core.f2.receiver_overflow_weir.observations.v1",
        "case_id": proposal["config"]["case_id"],
        "event_observation": audit["event_observation"],
        "hard_integrity_pass": audit["hard_integrity_pass"],
        "event_window_complete": audit["event_window_complete"],
        "future_state_inputs": False,
        "qualification_claim": "none",
        "matrix_credit": 0,
    }
    write_json(output / "audit.json", audit)
    write_json(output / "observations.json", observations)
    result = {
        "schema": RUNTIME_SCHEMA,
        "case_id": proposal["config"]["case_id"],
        "matrix_case_id": MATRIX_CASE_ID,
        "matrix_index": MATRIX_INDEX,
        "solver_elapsed_seconds": elapsed,
        "conversion": conversion,
        "audit": audit,
        "observations": observations,
        "hard_integrity_pass": audit["hard_integrity_pass"],
        "event_window_complete": audit["event_window_complete"],
        "qualified": False,
        "qualification_claim": "none",
        "matrix_credit": 0,
        "execution_controls": {
            "solver_invoked": True,
            "gpu_invoked": True,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
        },
        "interpretation_boundary": "one protected scientific anchor result; separate scope admission is required",
    }
    write_json(output / "result.json", result)
    write_json(output / "worker-status.json", {
        "schema": RUNTIME_SCHEMA,
        "status": "complete_with_evidence",
        "hard_integrity_pass": audit["hard_integrity_pass"],
        "event_window_complete": audit["event_window_complete"],
        "finished_at_utc": stamp(),
        "qualification_claim": "none",
    })
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    review = sub.add_parser("make-root-review")
    review.add_argument("--base", type=Path, default=DEFAULT_BASE)
    review.add_argument("--output", type=Path, required=True)
    job = sub.add_parser("make-job")
    job.add_argument("--base", type=Path, default=DEFAULT_BASE)
    job.add_argument("--root-review", type=Path, required=True)
    job.add_argument("--output", type=Path, required=True)
    run = sub.add_parser("run")
    run.add_argument("--base", type=Path, default=DEFAULT_BASE)
    run.add_argument("--prepared", type=Path, required=True)
    run.add_argument("--root-review", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "make-root-review":
        value = make_root_review(args.base, args.output)
    elif args.command == "make-job":
        value = make_job(args.base, args.root_review, args.output)
    else:
        value = run_worker(args.prepared, args.root_review, args.output, args.base)
    print(json.dumps(value, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
