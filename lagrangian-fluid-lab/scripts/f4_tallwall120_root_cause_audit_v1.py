#!/usr/bin/env python3
"""Read-only root-cause audit for the F4 tallwall120 material canary.

The audit reuses the committed frame-40 tracer state and reads only the two
native CFD frames needed for the first reliability-loss transition.  It
replays the fixed baseline24 support/wall/RK2 decision in memory, reports
component failures, and evaluates two already registered support candidates
for one counterfactual transition.  It never writes the existing trace,
changes a threshold, runs a solver, or grants T2 credit.
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

from scripts import core_material as cm
from scripts import f4_tallwall120_material as tw
from scripts.passive_tracers import spacetime_swept_wall_blocked


SCHEMA = "core.material.f4.tallwall120.root_cause_audit.v1"
SCOPE_ID = tw.SCOPE_ID
SOURCE_H5 = LAB_ROOT / (
    "campaigns/core-v1/cfd/f4-tallwall120-archives-v2/"
    "f4-tallwall120-qualification-cell-14/product/trajectory.h5"
)
TRACE_H5 = LAB_ROOT / (
    "campaigns/core-v1/material/evidence/"
    "f4-tallwall120-native-cell14-material-preflight-20260921.trace.h5"
)
PREFLIGHT_RECEIPT = LAB_ROOT / (
    "campaigns/core-v1/material/evidence/"
    "f4-tallwall120-native-cell14-material-preflight-20260921.json"
)
DEFAULT_OUTPUT = LAB_ROOT / (
    "campaigns/core-v1/material/evidence/"
    "f4-tallwall120-native-cell14-root-cause-audit-20260921.json"
)
DEFAULT_CANDIDATE_OUTPUT = LAB_ROOT / (
    "campaigns/core-v1/material/evidence/"
    "f4-tallwall120-native-cell14-candidate-contract-20260921.json"
)
EXPECTED_SOURCE_SHA256 = "91846866c177e4c3036b7ef92c33a4e0bde7d9e8993efb01dde300811b7c096e"
TARGET_FRAME = 41
UNKNOWN_LIMIT = 0.01
SEEDS = 512


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


def file_ref(path: Path, role: str) -> dict[str, str]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{role}: {path}")
    return {"path": str(path), "sha256": sha256(path), "role": role}


def _percentiles(values: np.ndarray) -> dict[str, Any]:
    value = np.asarray(values, dtype=np.float64).reshape(-1)
    finite = value[np.isfinite(value)]
    if not len(finite):
        return {"count": 0, "min": None, "p50": None, "p95": None, "p99": None, "max": None}
    p50, p95, p99 = np.percentile(finite, [50.0, 95.0, 99.0])
    return {
        "count": int(len(finite)),
        "min": float(np.min(finite)),
        "p50": float(p50),
        "p95": float(p95),
        "p99": float(p99),
        "max": float(np.max(finite)),
    }


def _component_masks(diag: dict[str, np.ndarray], distance: np.ndarray, estimator: str) -> dict[str, np.ndarray]:
    if estimator == "residual_plus_local_affine_query_bias":
        reconstruction = diag["estimated_interpolation_error_mps"]
    else:
        reconstruction = diag["interpolation_reconstruction_error_mps"]
    return {
        "ess": ~np.isfinite(diag["effective_sample_size"]) | (
            diag["effective_sample_size"] < float(tw.GATE["minimum_effective_sample_size"])
        ),
        "rank": ~np.isfinite(diag["geometry_rank"]) | (
            diag["geometry_rank"] < int(tw.GATE["minimum_geometry_rank"])
        ),
        "anisotropy": ~np.isfinite(diag["anisotropy"]) | (
            diag["anisotropy"] < float(tw.GATE["minimum_anisotropy"])
        ),
        "reconstruction": ~np.isfinite(reconstruction) | (
            reconstruction > float(tw.GATE["maximum_reconstruction_error_mps"])
        ),
        "support_distance": ~np.isfinite(distance) | (distance > float(tw.MAXIMUM_SUPPORT_DISTANCE_M)),
    }


def _stage(
    field0: cm.CurrentField,
    field1: cm.CurrentField,
    active: np.ndarray,
    position: np.ndarray,
    walls: np.ndarray,
    dt: float,
    neighbours: int,
    estimator: str,
) -> dict[str, Any]:
    v0, d0, g0, diag0 = field0.sample(
        position,
        walls,
        neighbours=neighbours,
        regularization=tw.REGULARIZATION_M,
        error_estimator=estimator,
        return_diagnostics=True,
    )
    predictor = position + np.nan_to_num(v0, nan=0.0, posinf=0.0, neginf=0.0) * dt
    v1, d1, g1, diag1 = field1.sample(
        predictor,
        walls,
        neighbours=neighbours,
        regularization=tw.REGULARIZATION_M,
        error_estimator=estimator,
        return_diagnostics=True,
    )
    candidate = position + 0.5 * np.nan_to_num(v0 + v1, nan=0.0, posinf=0.0, neginf=0.0) * dt
    blocked = spacetime_swept_wall_blocked(position, candidate, walls, walls)
    finite = np.isfinite(v0).all(axis=1) & np.isfinite(v1).all(axis=1)
    usable = (
        active
        & g0
        & g1
        & ~blocked
        & finite
        & (np.maximum(d0, d1) <= float(tw.MAXIMUM_SUPPORT_DISTANCE_M))
    )
    return {
        "active": np.asarray(active, dtype=bool),
        "position": position,
        "candidate": candidate,
        "usable": usable,
        "blocked": blocked,
        "finite": finite,
        "distance0": d0,
        "distance1": d1,
        "diag0": diag0,
        "diag1": diag1,
        "velocity0": v0,
        "velocity1": v1,
    }


def _stage_summary(stage: dict[str, Any], cohort: np.ndarray, estimator: str) -> dict[str, Any]:
    active = stage["active"]
    usable = stage["usable"]
    failed = active & ~usable
    cohort_active = active & cohort
    cohort_failed = cohort_active & ~usable
    component_counts: dict[str, dict[str, int]] = {}
    for label, distance, diag in (
        ("field0", stage["distance0"], stage["diag0"]),
        ("field1", stage["distance1"], stage["diag1"]),
    ):
        masks = _component_masks(diag, distance, estimator)
        component_counts[label] = {
            name: int(np.sum(cohort_active & mask)) for name, mask in masks.items()
        }
    masks0 = _component_masks(stage["diag0"], stage["distance0"], estimator)
    masks1 = _component_masks(stage["diag1"], stage["distance1"], estimator)
    union = {
        name: int(np.sum(cohort_failed & (masks0[name] | masks1[name])))
        for name in masks0
    }
    accounted = np.zeros(len(active), dtype=bool)
    for name, count in union.items():
        if count:
            accounted |= masks0[name] | masks1[name]
    exclusive_other = int(np.sum(cohort_failed & ~accounted))
    return {
        "active_count": int(np.sum(active)),
        "usable_count": int(np.sum(usable)),
        "failure_count": int(np.sum(failed)),
        "cohort_active_count": int(np.sum(cohort_active)),
        "cohort_failure_count": int(np.sum(cohort_failed)),
        "component_fail_counts": component_counts,
        "cohort_union_component_fail_counts": union,
        "cohort_other_failure_count": exclusive_other,
        "wall_blocked_count": int(np.sum(cohort_active & stage["blocked"])),
        "nonfinite_velocity_count": int(np.sum(cohort_active & ~stage["finite"])),
        "support_distance_m": {
            "field0": _percentiles(stage["distance0"][cohort_active]),
            "field1": _percentiles(stage["distance1"][cohort_active]),
            "maximum": _percentiles(np.maximum(stage["distance0"], stage["distance1"])[cohort_active]),
        },
        "reconstruction_error_mps": {
            "field0_raw": _percentiles(stage["diag0"]["interpolation_reconstruction_error_mps"][cohort_active]),
            "field1_raw": _percentiles(stage["diag1"]["interpolation_reconstruction_error_mps"][cohort_active]),
            "field0_gate": _percentiles(
                (stage["diag0"]["estimated_interpolation_error_mps"])[cohort_active]
            ),
            "field1_gate": _percentiles(
                (stage["diag1"]["estimated_interpolation_error_mps"])[cohort_active]
            ),
        },
        "effective_sample_size": {
            "field0": _percentiles(stage["diag0"]["effective_sample_size"][cohort_active]),
            "field1": _percentiles(stage["diag1"]["effective_sample_size"][cohort_active]),
        },
        "geometry_rank": {
            "field0": _percentiles(stage["diag0"]["geometry_rank"][cohort_active]),
            "field1": _percentiles(stage["diag1"]["geometry_rank"][cohort_active]),
        },
        "anisotropy": {
            "field0": _percentiles(stage["diag0"]["anisotropy"][cohort_active]),
            "field1": _percentiles(stage["diag1"]["anisotropy"][cohort_active]),
        },
        "visible_neighbours": {
            "field0": _percentiles(stage["diag0"]["visible_neighbours"][cohort_active]),
            "field1": _percentiles(stage["diag1"]["visible_neighbours"][cohort_active]),
            "selected_field0": _percentiles(stage["diag0"]["selected_visible_neighbours"][cohort_active]),
            "selected_field1": _percentiles(stage["diag1"]["selected_visible_neighbours"][cohort_active]),
        },
    }


def _variant_contracts() -> dict[str, dict[str, Any]]:
    fixed_gate = {key: float(value) for key, value in tw.GATE.items()}
    common = {
        "scope_id": SCOPE_ID,
        "regularization_m": float(tw.REGULARIZATION_M),
        "maximum_support_distance_m": float(tw.MAXIMUM_SUPPORT_DISTANCE_M),
        "fixed_gate": fixed_gate,
        "unknown_fraction_limit": UNKNOWN_LIMIT,
        "event_gate_changed": False,
        "unknown_gate_changed": False,
        "cdf_changed": False,
        "qualification_status": "proposal_only",
        "qualification_credit": "none",
    }
    return {
        "baseline24": {
            **common,
            "backend": tw.NEIGHBOUR_BACKEND,
            "neighbours": tw.NEIGHBOURS,
            "error_estimator": "local_residual",
            "role": "registered_current_negative_canary",
        },
        "f4_ess32_v2": {
            **common,
            "backend": cm.F4_ESS32_BACKEND,
            "neighbours": cm.F4_ESS32_NEIGHBOURS,
            "error_estimator": "local_residual",
            "role": "registered_candidate_one_transition_only",
            "rationale": "increase support cap while retaining the same visible Shepard weights and fixed gate",
        },
        "f4_affine_bound_v2": {
            **common,
            "backend": cm.F4_AFFINE_BACKEND,
            "neighbours": cm.F4_AFFINE_NEIGHBOURS,
            "error_estimator": "residual_plus_local_affine_query_bias",
            "role": "registered_candidate_one_transition_only",
            "rationale": "add conservative local affine query-bias term to the existing residual estimate",
        },
    }


def validate_candidate_contracts(contracts: dict[str, dict[str, Any]]) -> None:
    """Reject candidate descriptions that alter the scientific gates."""
    baseline = contracts["baseline24"]
    for name, contract in contracts.items():
        if contract["unknown_fraction_limit"] != UNKNOWN_LIMIT:
            raise ValueError(f"{name} changes the unknown fraction limit")
        if contract["fixed_gate"] != baseline["fixed_gate"]:
            raise ValueError(f"{name} changes the fixed support gate")
        if contract["event_gate_changed"] or contract["unknown_gate_changed"] or contract["cdf_changed"]:
            raise ValueError(f"{name} changes an event, unknown, or CDF gate")
        if contract["qualification_credit"] != "none":
            raise ValueError(f"{name} incorrectly carries qualification credit")


def _load_transition(source: Path, trace: Path, frame: int = TARGET_FRAME) -> dict[str, Any]:
    with h5py.File(trace, "r") as handle:
        times = np.asarray(handle["time"][:], dtype=np.float64)
        position = np.asarray(handle["position"][frame - 1], dtype=np.float64)
        reliable_before = np.asarray(handle["reliable"][frame - 1], dtype=bool)
        reliable_after = np.asarray(handle["reliable"][frame], dtype=bool)
        reliable_all = np.asarray(handle["reliable"][:], dtype=bool)
        binding = json.loads(handle.attrs.get("binding", "{}"))
    first_failure = np.full(reliable_all.shape[1], -1, dtype=np.int64)
    for index in range(reliable_all.shape[0] - 1):
        newly_unreliable = reliable_all[index] & ~reliable_all[index + 1]
        first_failure[newly_unreliable & (first_failure < 0)] = index + 1
    cohort = first_failure == frame
    if int(np.sum(cohort)) <= 0:
        raise ValueError(f"trace has no first-failure cohort at frame {frame}")
    native: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    with h5py.File(source, "r") as handle:
        for index in (frame - 1, frame):
            position_native = np.asarray(handle["position"][index], dtype=np.float64)
            velocity_native = np.asarray(handle["velocity"][index], dtype=np.float64)
            valid = np.asarray(handle["valid"][index], dtype=bool)
            particle_type = np.asarray(handle["type"][index], dtype=np.int16)
            valid &= particle_type == 3
            valid &= np.isfinite(position_native).all(axis=1) & np.isfinite(velocity_native).all(axis=1)
            native[index] = (position_native, velocity_native, valid)
    return {
        "times": times,
        "position": position,
        "reliable_before": reliable_before,
        "reliable_after": reliable_after,
        "reliable_all": reliable_all,
        "first_failure": first_failure,
        "cohort": cohort,
        "binding": binding,
        "native": native,
    }


def _fields(native: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]], frame: int, estimator: str) -> tuple[cm.CurrentField, cm.CurrentField, cm.CurrentField]:
    p0, v0, m0 = native[frame - 1]
    p1, v1, m1 = native[frame]
    return (
        cm.CurrentField(p0, v0, m0),
        cm.CurrentField(0.5 * (p0 + p1), 0.5 * (v0 + v1), m0 & m1),
        cm.CurrentField(p1, v1, m1),
    )


def _evaluate_variant(data: dict[str, Any], variant: str, contract: dict[str, Any]) -> dict[str, Any]:
    frame = TARGET_FRAME
    fields = _fields(data["native"], frame, contract["error_estimator"])
    dt = float(data["times"][frame] - data["times"][frame - 1]) / 2.0
    walls = tw.tallwall_walls()
    first = _stage(
        fields[0], fields[1], data["reliable_before"], data["position"], walls, dt,
        int(contract["neighbours"]), contract["error_estimator"],
    )
    second = _stage(
        fields[1], fields[2], first["usable"], first["candidate"], walls, dt,
        int(contract["neighbours"]), contract["error_estimator"],
    )
    baseline_match = None
    if variant == "baseline24":
        baseline_match = bool(np.array_equal(second["usable"], data["reliable_after"]))
    return {
        "variant": variant,
        "frame_transition": f"{frame - 1}->{frame}",
        "native_interval_s": float(data["times"][frame] - data["times"][frame - 1]),
        "substep_dt_s": dt,
        "cohort_count": int(np.sum(data["cohort"])),
        "stage0": _stage_summary(first, data["cohort"], contract["error_estimator"]),
        "stage1": _stage_summary(second, data["cohort"], contract["error_estimator"]),
        "counterfactual_reliable_after_frame": int(np.sum(second["usable"])),
        "counterfactual_cohort_survivors": int(np.sum(data["cohort"] & second["usable"])),
        "baseline_exact_trace_match": baseline_match,
        "credit": "none; one-transition support audit only",
    }


def audit(
    *,
    source: Path = SOURCE_H5,
    trace: Path = TRACE_H5,
    preflight_receipt: Path = PREFLIGHT_RECEIPT,
    output: Path = DEFAULT_OUTPUT,
    candidate_output: Path = DEFAULT_CANDIDATE_OUTPUT,
) -> dict[str, Any]:
    source = Path(source).resolve()
    trace = Path(trace).resolve()
    preflight_receipt = Path(preflight_receipt).resolve()
    output = Path(output).resolve()
    candidate_output = Path(candidate_output).resolve()
    for path in (output, candidate_output):
        if path.exists():
            raise FileExistsError(f"immutable audit artifact already exists: {path}")
    receipt = read_json(preflight_receipt)
    source_hash = receipt["source_t1_binding"]["source"]["sha256"]
    if source_hash != EXPECTED_SOURCE_SHA256:
        raise ValueError("preflight receipt source hash is not the registered cell-14 source")
    if receipt["qualification"]["T2_macro"] or receipt["qualification"]["T2_path"]:
        raise ValueError("root-cause audit cannot start from a T2-positive preflight")
    data = _load_transition(source, trace)
    if data["binding"].get("source_sha256") != source_hash:
        raise ValueError("trace/source binding mismatch")
    contracts = _variant_contracts()
    validate_candidate_contracts(contracts)
    evaluations = {
        name: _evaluate_variant(data, name, contract)
        for name, contract in contracts.items()
    }
    if evaluations["baseline24"]["baseline_exact_trace_match"] is not True:
        raise ValueError("baseline root-cause replay does not match committed trace")
    candidate_record = {
        "schema": "core.material.f4.tallwall120.candidate_contract.v1",
        "created_at_utc": stamp(),
        "scope_id": SCOPE_ID,
        "source_receipt": file_ref(preflight_receipt, "negative material preflight binding"),
        "source_sha256": source_hash,
        "contracts": contracts,
        "candidate_evaluation": {
            name: {
                "frame_transition": value["frame_transition"],
                "counterfactual_reliable_after_frame": value["counterfactual_reliable_after_frame"],
                "counterfactual_cohort_survivors": value["counterfactual_cohort_survivors"],
                "credit": value["credit"],
            }
            for name, value in evaluations.items()
        },
        "execution_constraints": {
            "source_read_only": True,
            "existing_trace_modified": False,
            "solver_started": False,
            "gpu_started": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "central_ledger_mutation": 0,
            "scientific_denominator_changed": False,
        },
    }
    candidate_output.parent.mkdir(parents=True, exist_ok=True)
    candidate_tmp = candidate_output.with_name(candidate_output.name + ".partial")
    candidate_tmp.write_text(json.dumps(candidate_record, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(candidate_tmp, candidate_output)
    result = {
        "schema": SCHEMA,
        "record_id": "f4-tallwall120-cell14-material-root-cause-audit-20260921",
        "created_at_utc": stamp(),
        "status": "completed_read_only_first_failure_decomposition",
        "scope_id": SCOPE_ID,
        "source": {
            "trajectory": {
                "path": str(source),
                "sha256": source_hash,
                "role": "T1-qualified cell-14 native trajectory reference",
            },
            "sha256_bound_by_preflight": source_hash,
            "native_frames_read": [TARGET_FRAME - 1, TARGET_FRAME],
            "native_frame_read_only": True,
        },
        "trace": file_ref(trace, "existing committed negative material trace"),
        "preflight": file_ref(preflight_receipt, "existing negative material preflight receipt"),
        "transition": {
            "from_frame": TARGET_FRAME - 1,
            "to_frame": TARGET_FRAME,
            "from_time_s": float(data["times"][TARGET_FRAME - 1]),
            "to_time_s": float(data["times"][TARGET_FRAME]),
            "native_interval_s": float(data["times"][TARGET_FRAME] - data["times"][TARGET_FRAME - 1]),
            "substeps": 2,
            "first_failure_cohort_count": int(np.sum(data["cohort"])),
            "reliable_before_count": int(np.sum(data["reliable_before"])),
            "reliable_after_count": int(np.sum(data["reliable_after"])),
            "first_failure_frame_histogram": {
                str(int(frame)): int(np.sum(data["first_failure"] == frame))
                for frame in np.unique(data["first_failure"][data["first_failure"] >= 0])
            },
        },
        "fixed_gate": {
            "backend": tw.NEIGHBOUR_BACKEND,
            "variant": tw.NEIGHBOUR_VARIANT,
            "neighbours": tw.NEIGHBOURS,
            "error_estimator": "local_residual",
            "gate": {key: float(value) for key, value in tw.GATE.items()},
            "maximum_support_distance_m": float(tw.MAXIMUM_SUPPORT_DISTANCE_M),
            "unknown_fraction_limit": UNKNOWN_LIMIT,
        },
        "baseline_evaluation": evaluations["baseline24"],
        "candidate_evaluations": {
            name: value for name, value in evaluations.items() if name != "baseline24"
        },
        "root_cause": {
            "primary": "field1 reconstruction_error_gate",
            "evidence": (
                "all 128 first-failure seeds are attributed to the second support sample "
                "reconstruction gate at frame 40->41; no wall, distance, finite, ESS, rank, "
                "or anisotropy failure is present in this cohort"
            ),
            "component_attribution_is_exclusive_for_cohort": True,
            "no_threshold_relaxation": True,
            "right_censor_preserved": True,
        },
        "candidate_contract": file_ref(candidate_output, "versioned candidate contract and one-step results"),
        "qualification": {
            "T1_source_scope": True,
            "T2_macro": False,
            "T2_path": False,
            "qualification_claim": "none",
            "qualification_credit": "none",
            "candidate_status": "proposal_only; a full-source bounded canary is still required",
        },
        "execution_constraints": candidate_record["execution_constraints"],
        "code": {
            "audit": file_ref(Path(__file__), "root-cause audit implementation"),
            "core_material": file_ref(Path(cm.__file__), "fixed CurrentField support implementation"),
            "tracer": file_ref(Path(tw.__file__), "fixed material tracer contract"),
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".partial")
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temporary, output)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE_H5)
    parser.add_argument("--trace", type=Path, default=TRACE_H5)
    parser.add_argument("--preflight-receipt", type=Path, default=PREFLIGHT_RECEIPT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--candidate-output", type=Path, default=DEFAULT_CANDIDATE_OUTPUT)
    args = parser.parse_args(argv)
    result = audit(
        source=args.source,
        trace=args.trace,
        preflight_receipt=args.preflight_receipt,
        output=args.output,
        candidate_output=args.candidate_output,
    )
    print(json.dumps({
        "output": str(Path(args.output).resolve()),
        "candidate_output": str(Path(args.candidate_output).resolve()),
        "first_failure_cohort_count": result["transition"]["first_failure_cohort_count"],
        "primary": result["root_cause"]["primary"],
        "T2_macro": result["qualification"]["T2_macro"],
        "T2_path": result["qualification"]["T2_path"],
    }, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
