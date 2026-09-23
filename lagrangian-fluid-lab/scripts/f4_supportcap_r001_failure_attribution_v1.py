#!/usr/bin/env python3
"""Attribute F4 supportcap r001's first-frame unknowns without rerunning it."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

import h5py
import numpy as np

from scripts import core_material as material
from scripts import f4_supportcap_affine_query_bound_candidate_v3 as candidate
from scripts import f4_tallwall120_material as tracer


LAB = Path(__file__).resolve().parents[1]
ATTEMPT_ID = "f4-supportcap-affine-query-bound-v3-cpu-native-canary-r001"
EVIDENCE = Path("campaigns/core-v1/material/evidence") / ATTEMPT_ID
CANDIDATE = Path("campaigns/core-v1/material/candidates/f4-supportcap-affine-query-bound-v3")
AUTHORIZATION = CANDIDATE / "cpu-native-canary-preflight-authorization-v1/authorization.json"
INPUT_PREFLIGHT = EVIDENCE / "input-preflight.json"
ENVIRONMENT_PREFLIGHT = EVIDENCE / "environment-preflight.json"
ATTEMPT = EVIDENCE / "attempt-manifest.json"
ACCEPTANCE = EVIDENCE / "acceptance-receipt.json"
RESULT = EVIDENCE / "result.json"
TRACE = EVIDENCE / "trace.h5"
OUTPUT = Path("campaigns/core-v1/material/evidence") / f"{ATTEMPT_ID}-failure-attribution-v1.json"
SCHEMA = "core.material.f4.supportcap_r001_failure_attribution.v1"
EXPECTED_TRACE_SHA256 = "0b1440c68e8a51d5277de82aa6979d965b8398ff6049f3a37fb45f75b260b905"
EXPECTED_TRACE_BYTES = 170248


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def binding(path: Path, role: str, *, digest: str | None = None) -> dict[str, Any]:
    absolute = (LAB / path).resolve() if not path.is_absolute() else path.resolve()
    return {
        "path": str(absolute.relative_to(LAB)), "role": role,
        "bytes": absolute.stat().st_size, "sha256": digest or sha256(absolute),
    }


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads((LAB / path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _relative(path: Path) -> str:
    absolute = (LAB / path).resolve() if not path.is_absolute() else path.resolve()
    return str(absolute.relative_to(LAB))


def validate_file_reference(reference: dict[str, Any], path: Path, label: str) -> None:
    absolute = (LAB / path).resolve() if not path.is_absolute() else path.resolve()
    if not absolute.is_file() or not (
        reference.get("path") == _relative(absolute)
        and reference.get("bytes") == absolute.stat().st_size
        and reference.get("sha256") == sha256(absolute)
    ):
        raise ValueError(f"{label} reference does not match its immutable file")


def validate_result_reference(acceptance: dict[str, Any], result_path: Path) -> None:
    validate_file_reference(acceptance.get("result", {}), result_path, "r001 result")


def canonical_json_sha256(path: Path) -> str:
    absolute = (LAB / path).resolve() if not path.is_absolute() else path.resolve()
    value = json.loads(absolute.read_text(encoding="utf-8"))
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def validate_canonical_json_digest(path: Path, expected_sha256: str, label: str) -> None:
    absolute = (LAB / path).resolve() if not path.is_absolute() else path.resolve()
    if not absolute.is_file() or canonical_json_sha256(absolute) != expected_sha256:
        raise ValueError(f"{label} canonical JSON digest does not match its immutable document")


def validate_trace_binding(
    trace_binding: dict[str, Any], result_binding: dict[str, Any],
    seeds: np.ndarray, source_sha256: str,
) -> None:
    candidate_path = Path(candidate.__file__).resolve()
    tracer_path = Path(tracer.__file__).resolve()
    expected = {
        "schema": tracer.SCHEMA,
        "scope_id": tracer.SCOPE_ID,
        "source_sha256": source_sha256,
        "code_sha256": sha256(tracer_path),
        "core_material_sha256": sha256(Path(material.__file__).resolve()),
        "neighbor_code_sha256": sha256(tracer_path.with_name("f3_material_neighbors.py")),
        "passive_code_sha256": sha256(tracer_path.with_name("passive_tracers.py")),
        "initial_sha256": tracer.array_hash(seeds),
        "substeps": 2,
        "source_semantics": "reference_native_saved_frames",
        "provider_role": "reference",
        "backend": candidate.BACKEND,
        "neighbour_variant": candidate.CANDIDATE_ID,
        "neighbours": candidate.NEIGHBOURS,
        "error_estimator": candidate.ERROR_ESTIMATOR,
        "regularization_m": candidate.REGULARIZATION_M,
        "maximum_support_distance_m": candidate.MAXIMUM_SUPPORT_DISTANCE_M,
        "support_gate": candidate.FIXED_GATE,
        "temporal_interpolation": "linear x/v only within native source frames 40 and 41",
        "repair_implementation_path": str(candidate_path),
        "repair_implementation_sha256": sha256(candidate_path),
        "repair_candidate_id": candidate.CANDIDATE_ID,
    }
    if trace_binding != result_binding:
        raise ValueError("r001 result binding differs from the trace's embedded execution binding")
    mismatches = {key: (trace_binding.get(key), value) for key, value in expected.items()
                  if trace_binding.get(key) != value}
    definition = trace_binding.get("f4_definition", {})
    if (definition.get("family_id") != "F4" or definition.get("scope_id") != tracer.SCOPE_ID
            or definition.get("q") != 0.5 or definition.get("dp_m") != 0.0075):
        mismatches["f4_definition"] = (definition, "registered F4/q=0.5/dp=0.0075")
    if mismatches:
        raise ValueError(f"r001 trace binding does not match the executed candidate contract: {mismatches}")


def validate_trace_times(trace_times: np.ndarray, native_times: np.ndarray, *, atol_s: float = 1e-12) -> None:
    trace_times = np.asarray(trace_times, dtype=np.float64)
    native_times = np.asarray(native_times, dtype=np.float64)
    if (trace_times.shape != (2,) or native_times.shape != (2,)
            or not np.isfinite(trace_times).all() or not np.isfinite(native_times).all()
            or not np.allclose(trace_times, native_times, rtol=0.0, atol=atol_s)):
        raise ValueError("r001 trace times do not match native frame 40->41 within the frozen 1e-12 s tolerance")


def validate_acceptance_result_trace(
    acceptance: dict[str, Any], result: dict[str, Any], trace_reliable: np.ndarray, seed_count: int,
) -> None:
    trace_reliable = np.asarray(trace_reliable, dtype=bool)
    rows = result.get("by_source")
    if not isinstance(rows, list) or len(rows) != 1:
        raise ValueError("r001 result must contain exactly one registered source row")
    if seed_count != 512 or trace_reliable.shape != (2, seed_count):
        raise ValueError("r001 cross-check requires the fixed 512-seed, two-frame trace")

    gate = acceptance["gate_evaluation"]
    row = rows[0]
    result_fraction = float(row["unknown_fraction_max"])
    result_final_fraction = float(row["final_unknown_fraction"])
    result_count = int(round(result_fraction * seed_count))
    trace_unknown_by_frame = seed_count - trace_reliable.sum(axis=1)
    acceptance_count = int(gate["unknown_count"])
    if not (
        int(gate["seed_denominator"]) == seed_count
        and acceptance_count == result_count == int(trace_unknown_by_frame[-1]) == seed_count
        and float(gate["unknown_fraction"]) == result_fraction == result_final_fraction == 1.0
        and result.get("unknown_gate_pass") is False
        and result.get("unknown_fraction_monotone") is True
        and row.get("first_unreliable_frame") == 0
        and np.array_equal(trace_unknown_by_frame, np.asarray([seed_count, seed_count]))
    ):
        raise ValueError("r001 acceptance, result, and both saved trace reliability frames disagree")


def validate_historical_attempt(
    authorization: dict[str, Any], input_preflight: dict[str, Any], attempt: dict[str, Any],
    acceptance: dict[str, Any], result: dict[str, Any],
) -> None:
    source_contract = authorization["input_contract"]["source"]
    native_window = input_preflight["native_frame_window"]
    executor_path = Path("scripts/f4_supportcap_affine_query_bound_cpu_canary_execute_v1.py")
    authorization_digest = sha256(LAB / AUTHORIZATION)
    if not (
        authorization.get("schema") == "core.material.f4.supportcap_affine_query_bound.cpu_canary_authorization.v1"
        and authorization["one_attempt_contract"]["max_attempts"] == 1
        and authorization["one_attempt_contract"]["retry"] is False
        and acceptance["status"] == "failed_one_attempt_zero_credit"
        and acceptance["execution_controls"]["canary_started"] is True
        and acceptance["execution_controls"]["solver_started"] is False
        and acceptance["qualification"]["credit"] == 0
        and attempt["attempt_id"] == ATTEMPT_ID
        and attempt["retry"] is False
        and attempt["max_attempts"] == 1
        and attempt["execution_controls"]["solver_started"] is False
        and attempt["authorization"]["sha256"] == authorization_digest
        and acceptance["authorization"]["sha256"] == authorization_digest
        and attempt["authorization_sha256_bound_by_executor"] == authorization_digest
        and acceptance["result"]["path"] == str(RESULT)
        and attempt["input_preflight_sha256"] == canonical_json_sha256(LAB / INPUT_PREFLIGHT)
        and attempt["environment_preflight_sha256"] == canonical_json_sha256(LAB / ENVIRONMENT_PREFLIGHT)
        and attempt["execution_authority"] == acceptance["execution_authority"]
        and attempt["execution_authority"] == "explicit user authorization: F4 supportcap CPU canary execution"
        and acceptance["executor"]["path"] == str(executor_path)
        and acceptance["executor"]["sha256"] == attempt["executor"]["sha256"]
        and result.get("status") == "completed"
        and result.get("unknown_gate_pass") is False
        and result.get("unknown_fraction_monotone") is True
        and acceptance["gate_evaluation"]["unknown_count"] == 512
        and acceptance["gate_evaluation"]["unknown_fraction"] == 1.0
        and acceptance["gate_evaluation"]["unknown_limit"] == 0.01
        and acceptance["gate_evaluation"]["checks"]["candidate_affine_estimator_bound"] is True
        and acceptance["gate_evaluation"]["checks"]["candidate_backend_bound"] is True
        and acceptance["gate_evaluation"]["checks"]["candidate_support_cap_bound"] is True
        and acceptance["gate_evaluation"]["checks"]["full_seed_denominator_bound"] is False
        and acceptance["gate_evaluation"]["checks"]["unknown_fraction_within_registered_limit"] is False
        and acceptance["gate_evaluation"]["checks"]["source_mass_closed"] is True
        and acceptance["gate_evaluation"]["checks"]["right_censored_as_required_for_one_transition"] is True
        and attempt["execution_controls"]["gpu_started"] is False
        and attempt["execution_controls"]["queue_mutation"] == 0
        and attempt["execution_controls"]["registry_mutation"] == 0
        and acceptance["execution_controls"]["gpu_started"] is False
        and acceptance["execution_controls"]["worker_started"] is False
        and acceptance["execution_controls"]["queue_mutation"] == 0
        and acceptance["execution_controls"]["registry_mutation"] == 0
        and native_window["native_rows_read_by_runner"] == [40, 41]
        and native_window["start"] == 40 and native_window["stop_inclusive"] == 41
        and input_preflight["source"]["path"] == source_contract["path"]
        and input_preflight["source"]["sha256"] == source_contract["sha256"]
        and input_preflight["fixed_contract"]["seed_denominator"] == 512
        and input_preflight["fixed_contract"]["q"] == 0.5
    ):
        raise PermissionError("r001 immutable evidence does not match its one-attempt source contract")
    validate_result_reference(acceptance, LAB / RESULT)
    validate_canonical_json_digest(INPUT_PREFLIGHT, attempt["input_preflight_sha256"], "r001 input preflight")
    validate_canonical_json_digest(
        ENVIRONMENT_PREFLIGHT, attempt["environment_preflight_sha256"], "r001 environment preflight"
    )
    validate_file_reference(attempt["authorization"], AUTHORIZATION, "r001 attempt authorization")
    validate_file_reference(acceptance["authorization"], AUTHORIZATION, "r001 acceptance authorization")
    validate_file_reference(attempt["executor"], executor_path, "r001 executor")
    validate_file_reference(acceptance["executor"], executor_path, "r001 acceptance executor")


def validate_pinned_trace(path: Path = LAB / TRACE) -> str:
    path = Path(path).resolve()
    if (not path.is_file() or path.stat().st_size != EXPECTED_TRACE_BYTES
            or sha256(path) != EXPECTED_TRACE_SHA256):
        raise ValueError("immutable r001 trace hash does not match the pinned attribution input")
    return EXPECTED_TRACE_SHA256


def classify_initial_failure(
    *, frame_time_s: float, seed_positions_match_t0: bool,
    trace_reliable: np.ndarray, support_distance: np.ndarray,
    sampler_passed: np.ndarray, maximum_support_distance_m: float,
) -> str:
    trace_reliable = np.asarray(trace_reliable, dtype=bool)
    support_distance = np.asarray(support_distance, dtype=np.float64)
    sampler_passed = np.asarray(sampler_passed, dtype=bool)
    if not (trace_reliable.shape == support_distance.shape == sampler_passed.shape):
        raise ValueError("trace and support diagnostic seed axes differ")
    if not len(trace_reliable) or not np.isfinite(frame_time_s):
        raise ValueError("failure attribution requires a nonempty finite initial frame")
    all_unknown = not trace_reliable.any()
    all_outside_support = bool(np.all(~np.isfinite(support_distance) | (support_distance > maximum_support_distance_m)))
    if frame_time_s > 0.0 and seed_positions_match_t0 and all_unknown and all_outside_support:
        return "t0_geometric_seeds_compared_to_later_native_frame_support"
    if all_unknown and not sampler_passed.any():
        return "initial_support_gate_failure_not_uniquely_attributed"
    return "initial_frame_does_not_explain_all_unknown_mass"


def _metric_failure_counts(diagnostics: dict[str, np.ndarray], gate: dict[str, float], distance_limit: float) -> dict[str, int]:
    values = {
        "effective_sample_size_below_minimum": diagnostics["effective_sample_size"] < gate["minimum_effective_sample_size"],
        "geometry_rank_below_minimum": diagnostics["geometry_rank"] < gate["minimum_geometry_rank"],
        "anisotropy_below_minimum": diagnostics["anisotropy"] < gate["minimum_anisotropy"],
        "estimated_error_above_maximum": diagnostics["estimated_interpolation_error_mps"] > gate["maximum_reconstruction_error_mps"],
        "support_distance_above_maximum": diagnostics["support_distance"] > distance_limit,
    }
    counts = {name: int(np.count_nonzero(mask)) for name, mask in values.items()}
    finite = np.ones(len(diagnostics["support_distance"]), dtype=bool)
    for name in ("effective_sample_size", "anisotropy", "estimated_interpolation_error_mps", "support_distance"):
        finite &= np.isfinite(diagnostics[name])
    finite &= np.isfinite(diagnostics["geometry_rank"])
    counts["nonfinite_support_diagnostics"] = int(np.count_nonzero(~finite))
    return counts


def build_report() -> dict[str, Any]:
    authorization = load_json(AUTHORIZATION)
    input_preflight = load_json(INPUT_PREFLIGHT)
    attempt = load_json(ATTEMPT)
    acceptance = load_json(ACCEPTANCE)
    result = load_json(RESULT)
    validate_historical_attempt(authorization, input_preflight, attempt, acceptance, result)
    source_contract = authorization["input_contract"]["source"]
    source = LAB / source_contract["path"]
    if not source.is_file() or source.stat().st_size != input_preflight["source"]["bytes"]:
        raise ValueError("hash-bound F4 source is missing or changed size")
    observed_source_hash = sha256(source)
    if observed_source_hash != source_contract["sha256"]:
        raise ValueError("F4 source hash changed; refusing to open HDF5")
    trace_digest = validate_pinned_trace(LAB / TRACE)

    seeds = material.seeds_f4(512, q=0.5)
    with h5py.File(LAB / TRACE, "r") as trace:
        if trace.attrs.get("schema") != tracer.SCHEMA or int(trace.attrs.get("committed", -1)) != 1:
            raise ValueError("r001 trace is not the expected completed one-transition material trace")
        trace_binding = json.loads(trace.attrs["binding"])
        trace_initial = np.asarray(trace["initial_position"][:], dtype=np.float64)
        trace_saved_initial = np.asarray(trace["position"][0], dtype=np.float64)
        trace_reliable = np.asarray(trace["reliable"][:], dtype=bool)
        trace_times = np.asarray(trace["time"][:], dtype=np.float64)
    if not (trace_initial.shape == trace_saved_initial.shape == seeds.shape == (512, 3)
            and trace_reliable.shape == (2, 512)
            and np.array_equal(trace_initial, seeds)
            and np.array_equal(trace_saved_initial, seeds)):
        raise ValueError("r001 trace no longer contains the registered t=0 geometric seed set at saved frame 0")
    validate_trace_binding(trace_binding, result["binding"], seeds, observed_source_hash)
    validate_acceptance_result_trace(acceptance, result, trace_reliable, len(seeds))
    trace_reliable_initial = trace_reliable[0]

    with h5py.File(source, "r") as native:
        native_times = np.asarray(native["time"][40:42], dtype=np.float64)
        position = np.asarray(native["position"][40], dtype=np.float64)
        velocity = np.asarray(native["velocity"][40], dtype=np.float64)
        valid = np.asarray(native["valid"][40], dtype=bool)
        zone = np.asarray(native["particle_zone"][:])
    validate_trace_times(trace_times, native_times)
    native_time = float(native_times[0])
    valid &= zone == 0
    valid &= np.isfinite(position).all(axis=1) & np.isfinite(velocity).all(axis=1)
    fluid_position = position[valid]
    field = material.CurrentField(position, velocity, valid)
    _, support_distance, sampler_passed, diagnostics = field.sample(
        seeds, tracer.tallwall_walls(), neighbours=candidate.NEIGHBOURS,
        regularization=candidate.REGULARIZATION_M,
        gate=candidate.FIXED_GATE, error_estimator=candidate.ERROR_ESTIMATOR,
        return_diagnostics=True,
    )
    support_distance = np.asarray(support_distance, dtype=np.float64)
    sampler_passed = np.asarray(sampler_passed, dtype=bool)
    max_distance = float(candidate.MAXIMUM_SUPPORT_DISTANCE_M)
    combined_passed = sampler_passed & np.isfinite(seeds).all(axis=1) & (support_distance <= max_distance)
    classification = classify_initial_failure(
        frame_time_s=float(native_time), seed_positions_match_t0=np.array_equal(seeds, trace_initial),
        trace_reliable=trace_reliable_initial, support_distance=support_distance,
        sampler_passed=sampler_passed, maximum_support_distance_m=max_distance,
    )
    gate = candidate.FIXED_GATE
    return {
        "schema": SCHEMA,
        "record_id": f"{ATTEMPT_ID}-failure-attribution-v1",
        "created_at_utc": stamp(),
        "status": "read_only_setup_mismatch_strongly_supported" if classification.startswith("t0_") else "read_only_initial_failure_not_fully_attributed",
        "qualification_claim": "none", "qualification_credit": 0,
        "historical_attempt_id": ATTEMPT_ID,
        "historical_attempt_status": acceptance["status"],
        "historical_attempt_modified": False,
        "canary_reexecuted": False, "solver_started": False, "gpu_started": False,
        "queue_mutation": 0, "worker_started": False, "registry_mutation": 0, "ledger_mutation": 0,
        "source_read_only": True,
        "source_read_provenance": {
            "path": source_contract["path"], "sha256": observed_source_hash,
            "native_frames_loaded": [40], "native_time_rows_read": [40, 41],
            "native_frame_time_s": float(native_time),
        },
        "trace_provenance": {
            "path": str(TRACE), "sha256": trace_digest, "time_s": trace_times.tolist(),
            "binding_matches_result_binding": True,
            "native_time_match_absolute_tolerance_s": 1e-12,
            "native_frame_rows": [40, 41],
            "initial_positions_match_registered_t0_seeds": True,
            "initial_position_bounds_m": [seeds.min(axis=0).tolist(), seeds.max(axis=0).tolist()],
            "initial_trace_reliable_count": int(trace_reliable_initial.sum()),
            "reliable_count_by_saved_frame": trace_reliable.sum(axis=1).astype(int).tolist(),
        },
        "acceptance_result_trace_crosscheck": {
            "seed_denominator": int(acceptance["gate_evaluation"]["seed_denominator"]),
            "unknown_count": int(acceptance["gate_evaluation"]["unknown_count"]),
            "unknown_fraction": float(acceptance["gate_evaluation"]["unknown_fraction"]),
            "trace_reliable_count_by_saved_frame": trace_reliable.sum(axis=1).astype(int).tolist(),
            "validated": True,
        },
        "failure_attribution": {
            "classification": classification,
            "query_time_s": float(native_time),
            "query_positions_are_original_t0_seeds": True,
            "source_time_nonzero": bool(native_time > 0.0),
            "seed_count": int(len(seeds)),
            "candidate_sampler_pass_count": int(sampler_passed.sum()),
            "combined_reliable_count_after_max_support_distance": int(combined_passed.sum()),
            "trace_reliable_count_at_first_saved_frame": int(trace_reliable_initial.sum()),
            "support_distance_limit_m": max_distance,
            "support_distance_quantiles_m": {
                "minimum": float(np.nanmin(support_distance)),
                "p05": float(np.nanquantile(support_distance, 0.05)),
                "median": float(np.nanmedian(support_distance)),
                "p95": float(np.nanquantile(support_distance, 0.95)),
                "maximum": float(np.nanmax(support_distance)),
            },
            "native_frame_fluid_particle_count": int(len(fluid_position)),
            "native_frame_fluid_z_bounds_m": [float(fluid_position[:, 2].min()), float(fluid_position[:, 2].max())],
            "initial_seed_z_bounds_m": [float(seeds[:, 2].min()), float(seeds[:, 2].max())],
            "fixed_gate_failure_counts_nonexclusive": _metric_failure_counts(diagnostics, gate, max_distance),
            "registered_gates_unchanged": True,
            "denominator_unchanged": 512,
            "event_semantics_unchanged": True,
        },
        "interpretation": (
            "The evidence strongly supports a setup-level temporal mismatch: the registered t=0 geometric seed "
            "coordinates were checked against native frame 40 at t>0, and every seed exceeded the fixed support "
            "distance. This does not prove the temporal mismatch is the only cause, establish that correctly "
            "forward-advected seeds would pass, nor exclude interactions "
            "with other fixed reliability gates; it is not candidate qualification and does not justify relaxing a gate."
            if classification.startswith("t0_") else
            "The first-saved-frame diagnostics do not uniquely explain every unknown seed; keep r001 failed and investigate only in a new static review."
        ),
        "minimum_next_step": {
            "kind": "new static candidate/root review only; no r001 retry",
            "required_temporal_alignment": "advect the original t=0 seeds using native rows from frame 0 through frame 40 before evaluating frame 40->41",
            "fixed_contracts_to_preserve": ["512 seed denominator", "all registered reliability thresholds", "source and event definitions", "right-censor semantics"],
            "new_runtime_authorization_required_before_any_future_native_canary": True,
        },
        "reproduction": {
            "command": ".venv/bin/python -m scripts.f4_supportcap_r001_failure_attribution_v1",
            "environment": "project .venv; system python3 is not assumed to have compatible h5py/numpy",
            "mode": "read-only CPU attribution; writer creates only the registered new v1 receipt",
        },
        "bindings": [
            binding(AUTHORIZATION, "one-attempt preflight contract"),
            binding(ATTEMPT, "terminal r001 attempt manifest"),
            binding(INPUT_PREFLIGHT, "r001 authorized source-frame preflight"),
            binding(ENVIRONMENT_PREFLIGHT, "r001 execution environment preflight"),
            binding(ACCEPTANCE, "terminal r001 zero-credit acceptance receipt"),
            binding(RESULT, "immutable r001 result"),
            binding(TRACE, "immutable r001 two-frame trace"),
            binding(Path("tests/test_f4_supportcap_r001_failure_attribution_v1.py"), "failure attribution integrity and tamper-rejection tests"),
            binding(Path("scripts/f4_supportcap_r001_failure_attribution_v1.py"), "read-only failure attribution code"),
            binding(Path("scripts/core_material.py"), "fixed reliability and support gate implementation"),
            binding(Path("scripts/f4_supportcap_affine_query_bound_candidate_v3.py"), "array-only supportcap candidate"),
            binding(Path("scripts/f4_tallwall120_material.py"), "registered F4 seeds, walls, and trace contract"),
        ],
    }


def write_report(path: Path = LAB / OUTPUT) -> dict[str, Any]:
    target = Path(path).resolve()
    if target != (LAB / OUTPUT).resolve():
        raise ValueError("only the registered F4 r001 attribution receipt path is permitted")
    if target.exists():
        raise FileExistsError(f"refusing to overwrite immutable F4 failure attribution: {target}")
    report = build_report()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    report = write_report()
    print(json.dumps({
        "status": report["status"], "classification": report["failure_attribution"]["classification"],
        "support_distance_quantiles_m": report["failure_attribution"]["support_distance_quantiles_m"],
        "fixed_gate_failure_counts_nonexclusive": report["failure_attribution"]["fixed_gate_failure_counts_nonexclusive"],
        "qualification_credit": 0,
    }, indent=2, sort_keys=True))
