#!/usr/bin/env python3
"""Build a proposal-only full-source F4 material canary contract.

This module only reads existing receipts, the existing short trace, and the
native time axis.  It writes a versioned contract for a future CPU-only
candidate run; it never starts that run and never changes a registry, ledger,
threshold, event definition, CDF, or scientific denominator.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any

import h5py
import numpy as np

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))


SCHEMA = "core.material.f4.tallwall120.full_source_canary_contract.v1"
SCOPE_ID = "F4_resting_pool_laminar_tallwall120_x_v1"
SOURCE_H5 = LAB_ROOT / (
    "campaigns/core-v1/cfd/f4-tallwall120-archives-v2/"
    "f4-tallwall120-qualification-cell-14/product/trajectory.h5"
)
PREFLIGHT_RECEIPT = LAB_ROOT / (
    "campaigns/core-v1/material/evidence/"
    "f4-tallwall120-native-cell14-material-preflight-20260921.json"
)
ROOT_CAUSE_AUDIT = LAB_ROOT / (
    "campaigns/core-v1/material/evidence/"
    "f4-tallwall120-native-cell14-root-cause-audit-20260921.json"
)
CANDIDATE_CONTRACT = LAB_ROOT / (
    "campaigns/core-v1/material/evidence/"
    "f4-tallwall120-native-cell14-candidate-contract-20260921.json"
)
TRACE_H5 = LAB_ROOT / (
    "campaigns/core-v1/material/evidence/"
    "f4-tallwall120-native-cell14-material-preflight-20260921.trace.h5"
)
TRACE_RESULT = LAB_ROOT / (
    "campaigns/core-v1/material/evidence/"
    "f4-tallwall120-native-cell14-material-preflight-20260921.trace.json"
)
DEFAULT_OUTPUT = LAB_ROOT / (
    "campaigns/core-v1/material/evidence/"
    "f4-tallwall120-native-cell14-f4-ess32-full-source-canary-contract-20260921.json"
)
EXPECTED_SOURCE_SHA256 = "91846866c177e4c3036b7ef92c33a4e0bde7d9e8993efb01dde300811b7c096e"
EXPECTED_FRAMES = 1086
EXPECTED_PARTICLES = 217485
EXPECTED_END_S = 4.340002980805959
SEEDS = 512
UNKNOWN_LIMIT = 0.01
RESUME_BOUNDARY_FRAME = 40
FINAL_FRAME = EXPECTED_FRAMES - 1


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def file_ref(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{role}: {path}")
    return {"path": str(path), "sha256": sha256(path), "role": role}


def source_window(source: Path) -> dict[str, Any]:
    """Read only HDF5 metadata/time, never source particle frames."""
    source = Path(source).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    with h5py.File(source, "r") as handle:
        required = {"time", "position", "velocity", "valid", "type"}
        missing = sorted(required - set(handle))
        if missing:
            raise ValueError(f"source missing required datasets: {missing}")
        times = np.asarray(handle["time"][:], dtype=np.float64)
        frame_count = int(handle["position"].shape[0])
        particle_count = int(handle["position"].shape[1])
        if frame_count != EXPECTED_FRAMES or particle_count != EXPECTED_PARTICLES:
            raise ValueError("source shape is outside the registered full window")
        if not np.isfinite(times).all() or len(times) != EXPECTED_FRAMES or np.any(np.diff(times) <= 0.0):
            raise ValueError("source time axis is not strictly increasing")
        attrs = {
            str(key): (value.item() if isinstance(value, np.generic) else value)
            for key, value in handle.attrs.items()
            if key in {"case_id", "family", "recipe_id", "schema_version", "conversion_complete"}
        }
    intervals = np.diff(times)
    return {
        "frame_start": 0,
        "frame_end": FINAL_FRAME,
        "frame_count": frame_count,
        "particle_count": particle_count,
        "time_start_s": float(times[0]),
        "time_end_s": float(times[-1]),
        "native_interval_nominal_s": 0.004,
        "native_interval_min_s": float(np.min(intervals)),
        "native_interval_median_s": float(np.median(intervals)),
        "native_interval_max_s": float(np.max(intervals)),
        "native_rows_exact": True,
        "cadence_substitution": False,
        "attrs": attrs,
        "source_size_bytes": int(source.stat().st_size),
    }


def validate_contract(contract: dict[str, Any]) -> None:
    """Fail closed if a proposed run mutates a scientific gate or denominator."""
    if contract.get("schema") != SCHEMA:
        raise ValueError("contract schema mismatch")
    candidate = contract["candidate"]
    if candidate["unknown_fraction_limit"] != UNKNOWN_LIMIT:
        raise ValueError("candidate changes unknown threshold")
    if candidate["event_gate_changed"] or candidate["cdf_changed"]:
        raise ValueError("candidate changes event/CDF gate")
    if candidate["qualification_credit"] != "none":
        raise ValueError("proposal carries qualification credit")
    window = contract["source_window"]
    if (window["frame_start"], window["frame_end"]) != (0, FINAL_FRAME):
        raise ValueError("contract is not the complete native source window")
    execution = contract["execution"]
    if execution["output_stem"] in {str(TRACE_H5.with_suffix("")), str(PREFLIGHT_RECEIPT.with_suffix(""))}:
        raise ValueError("proposal reuses an existing negative output stem")
    if execution["existing_trace_reuse"]["candidate_output_reuse"]:
        raise ValueError("old trace may only be a binding input")
    if contract["execution_constraints"]["solver_started"] or contract["execution_constraints"]["gpu_started"]:
        raise ValueError("proposal starts solver/GPU")
    if contract["execution_constraints"]["scientific_denominator_changed"]:
        raise ValueError("proposal changes scientific denominator")


def build_contract(
    *,
    source: Path = SOURCE_H5,
    preflight_receipt: Path = PREFLIGHT_RECEIPT,
    root_cause_audit: Path = ROOT_CAUSE_AUDIT,
    candidate_contract: Path = CANDIDATE_CONTRACT,
    trace_h5: Path = TRACE_H5,
    trace_result: Path = TRACE_RESULT,
    output: Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    source = Path(source).resolve()
    preflight_receipt = Path(preflight_receipt).resolve()
    root_cause_audit = Path(root_cause_audit).resolve()
    candidate_contract = Path(candidate_contract).resolve()
    trace_h5 = Path(trace_h5).resolve()
    trace_result = Path(trace_result).resolve()
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError(f"immutable contract already exists: {output}")
    preflight = read_json(preflight_receipt)
    root_audit = read_json(root_cause_audit)
    candidate = read_json(candidate_contract)
    trace = read_json(trace_result)
    source_sha = preflight["source_t1_binding"]["source"]["sha256"]
    if source_sha != EXPECTED_SOURCE_SHA256:
        raise ValueError("preflight source hash is not the registered cell-14 trajectory")
    if preflight["qualification"]["T2_macro"] or preflight["qualification"]["T2_path"]:
        raise ValueError("existing preflight unexpectedly carries T2 credit")
    if root_audit["qualification"]["qualification_credit"] != "none":
        raise ValueError("root-cause audit unexpectedly carries credit")
    ess32 = candidate["contracts"]["f4_ess32_v2"]
    if ess32["backend"] != "f4_ckdtree_visible_shepard_ess32_v2" or ess32["neighbours"] != 32:
        raise ValueError("candidate contract is not the registered ESS32 proposal")
    if candidate["candidate_evaluation"]["f4_ess32_v2"]["counterfactual_cohort_survivors"] != 0:
        raise ValueError("proposal binding changed its one-transition evidence")
    window = source_window(source)
    if trace["binding"]["source_sha256"] != source_sha:
        raise ValueError("existing negative trace is not bound to the same source")
    output_stem = LAB_ROOT / (
        "campaigns/core-v1/material/evidence/"
        "f4-tallwall120-native-cell14-f4-ess32-full-source-canary-20260921"
    )
    fixed_gate = ess32["fixed_gate"]
    contract = {
        "schema": SCHEMA,
        "record_id": "f4-tallwall120-cell14-f4-ess32-full-source-canary-contract-20260921",
        "created_at_utc": stamp(),
        "status": "proposal_only_deferred_after_one_transition_failure",
        "scope_id": SCOPE_ID,
        "route_decision": {
            "automatic_execution": False,
            "decision": "deferred",
            "reason": (
                "the one-transition ESS32 and affine proposals both retain zero survivors "
                "from the 128-seed frame-40->41 first-failure cohort; a full canary would "
                "be diagnostic only until candidate implementation review"
            ),
            "reopen_condition": "explicit future review with this contract unchanged and a new output stem",
        },
        "candidate": {
            "candidate_id": "f4_ess32_v2",
            "backend": ess32["backend"],
            "neighbours": int(ess32["neighbours"]),
            "error_estimator": ess32["error_estimator"],
            "regularization_m": float(ess32["regularization_m"]),
            "maximum_support_distance_m": float(ess32["maximum_support_distance_m"]),
            "fixed_gate": fixed_gate,
            "unknown_fraction_limit": UNKNOWN_LIMIT,
            "event_gate_changed": False,
            "cdf_changed": False,
            "qualification_credit": "none",
            "qualification_status": "proposal_only",
            "one_transition_counterfactual": candidate["candidate_evaluation"]["f4_ess32_v2"],
        },
        "source_window": {
            **window,
            "source": {
                "path": str(source),
                "sha256": source_sha,
                "role": "T1-qualified terminal native trajectory",
            },
            "full_native_window_required": True,
            "no_stride_or_synthetic_cadence": True,
            "interpolation": "linear x/v only between adjacent registered native frames",
            "integration": "RK2 with two substeps per native interval",
            "event_unknown_policy": "NaN/right-censored; no saved-chord imputation",
        },
        "execution": {
            "output_stem": str(output_stem),
            "output_stem_is_new": True,
            "planned_artifacts": {
                "trace_h5": str(output_stem) + ".trace.h5",
                "trace_result": str(output_stem) + ".trace.json",
                "receipt": str(output_stem) + ".json",
                "checkpoint_manifest": str(output_stem) + ".trace.h5.checkpoint.json",
                "checkpoint_generations": str(output_stem) + ".trace.h5.checkpoints",
            },
            "seed_count": SEEDS,
            "q": 0.5,
            "dp_m": 0.0075,
            "substeps": 2,
            "phase_0": {
                "stop_after_frame": RESUME_BOUNDARY_FRAME,
                "purpose": "create an immutable checkpoint immediately before the audited failure transition",
            },
            "phase_1": {
                "resume_from_frame": RESUME_BOUNDARY_FRAME,
                "stop_after_frame": FINAL_FRAME,
                "purpose": "complete every native frame through 4.340002980805959 s",
            },
            "resume_policy": {
                "checkpoint_every_native_frame": True,
                "recovery_point": RESUME_BOUNDARY_FRAME,
                "after_interruption": "verify manifest binding/generation SHA and resume latest committed frame",
                "generation_policy": "content-addressed append-only; never overwrite or delete prior generation",
                "rerun_from_zero_after_interruption": False,
            },
            "existing_trace_reuse": {
                "binding_only": True,
                "candidate_output_reuse": False,
                "old_trace_h5": file_ref(trace_h5, "existing negative trace binding only"),
                "old_trace_result": file_ref(trace_result, "existing negative result binding only"),
                "reason": "baseline24 negative evidence is provenance input; candidate state is never copied",
            },
        },
        "resource_profile": {
            "execution_mode": "CPU-only proposal; one process; no solver/GPU/queue",
            "cKDTree_workers": 1,
            "max_concurrent_processes": 1,
            "thread_environment": {
                "OPENBLAS_NUM_THREADS": "1",
                "OMP_NUM_THREADS": "1",
                "MKL_NUM_THREADS": "1",
                "NUMEXPR_NUM_THREADS": "1",
            },
            "reference_frame_cache_max": 2,
            "observed_baseline_reference": {
                "committed_frame": int(trace["committed_frame"]),
                "elapsed_seconds": float(trace["elapsed_seconds"]),
                "max_rss_kib": int(trace["max_rss_kib"]),
            },
            "budgets": {
                "max_wall_seconds": 1800,
                "max_rss_kib": 1048576,
                "max_new_disk_bytes": 536870912,
                "source_read_bytes_not_materialized": True,
            },
            "fail_fast_on_budget": True,
        },
        "success_and_failure_criteria": {
            "structural_success": [
                "source_sha256 equals the bound trajectory hash",
                "committed_frame equals 1085 and committed_time reaches the native 4.34 s endpoint",
                "all native rows are exact and adjacent-frame interpolation contract is recorded",
                "checkpoint manifest and generation SHA verify after the frame-40 resume",
                "seed denominator remains exactly 512 and mass closure is evaluated",
            ],
            "candidate_gate_observation": {
                "pass_if": [
                    "unknown_fraction_max <= 0.01 on all source labels",
                    "event window is complete under the registered event definition",
                ],
                "fail_if": [
                    "unknown_fraction_max > 0.01",
                    "right-censored/unresolved event remains at the full source endpoint",
                    "mass closure fails",
                    "any denominator drop, cadence substitution, or threshold change occurs",
                ],
                "right_censor_is_reported_as_failure_or_unknown": True,
                "no_partial_credit": True,
            },
            "qualification_effect": "none; this contract cannot change T2 or Core gate",
        },
        "hash_bindings": {
            "source_trajectory_sha256": source_sha,
            "preflight_receipt": file_ref(preflight_receipt, "existing negative preflight binding"),
            "root_cause_audit": file_ref(root_cause_audit, "existing root-cause binding"),
            "candidate_contract": file_ref(candidate_contract, "existing candidate binding"),
            "tracer_code_sha256": trace["binding"]["code_sha256"],
            "core_material_sha256": trace["binding"]["core_material_sha256"],
            "neighbor_code_sha256": trace["binding"]["neighbor_code_sha256"],
            "passive_code_sha256": trace["binding"]["passive_code_sha256"],
            "contract_implementation_sha256": sha256(Path(__file__).resolve()),
        },
        "execution_constraints": {
            "proposal_only": True,
            "source_read_only": True,
            "existing_trace_modified": False,
            "new_job_submitted": False,
            "solver_started": False,
            "gpu_started": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "central_ledger_mutation": 0,
            "thresholds_changed": False,
            "scientific_denominator_changed": False,
        },
    }
    validate_contract(contract)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".partial")
    temporary.write_text(json.dumps(contract, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temporary, output)
    return contract


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE_H5)
    parser.add_argument("--preflight-receipt", type=Path, default=PREFLIGHT_RECEIPT)
    parser.add_argument("--root-cause-audit", type=Path, default=ROOT_CAUSE_AUDIT)
    parser.add_argument("--candidate-contract", type=Path, default=CANDIDATE_CONTRACT)
    parser.add_argument("--trace-h5", type=Path, default=TRACE_H5)
    parser.add_argument("--trace-result", type=Path, default=TRACE_RESULT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    result = build_contract(
        source=args.source,
        preflight_receipt=args.preflight_receipt,
        root_cause_audit=args.root_cause_audit,
        candidate_contract=args.candidate_contract,
        trace_h5=args.trace_h5,
        trace_result=args.trace_result,
        output=args.output,
    )
    print(json.dumps({
        "output": str(Path(args.output).resolve()),
        "status": result["status"],
        "candidate": result["candidate"]["candidate_id"],
        "output_stem": result["execution"]["output_stem"],
        "frame_window": [result["source_window"]["frame_start"], result["source_window"]["frame_end"]],
        "resume_point": result["execution"]["phase_1"]["resume_from_frame"],
        "T2_macro": False,
        "T2_path": False,
    }, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
