#!/usr/bin/env python3
"""Strict model-free evaluation of the source-bound F2 raw reconstruction.

The v1 evaluator was a stat-only wrapper around an older typed-only result.
This forward evaluator consumes the immutable v16 JSON produced by the real
native raw-to-typed worker and the independent verification proof.  It checks
the source, case, cohort, identity axis, frozen observer profile, macro-array
shapes, and reconstruction proof before scoring an operator-derived prediction
with the frozen v14 macro evaluator.  It never opens HDF5, BI4, PartOut, or
RunPARTs; the JSON result and the small proof/report are its only data inputs.

The successful prediction is explicitly an operator self-test.  It is useful
for exercising the no-model scoring contract, but it is not a reference
calibration and cannot grant QI/QN/QE.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any, Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import ds_data02_stage2_f2_replay_v14 as v14
import ds_data02_stage2_f2_replay_v15 as v15


REQUEST_SCHEMA = "ds02.stage2.f2-no-model-evaluator-request.v2"
REPORT_SCHEMA = "ds02.stage2.f2-no-model-evaluator-report.v2"
RESULT_SCHEMA = "ds02.stage2.f2-s1-replay-result.v16"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
ALLOWED_LABEL_STATUS = {
    "observed", "right_censored", "failed_before_observation",
    "initially_inside", "ambiguous_multiple_crossing",
}


class EvaluatorV2BindingError(RuntimeError):
    """A source, identity, profile, or prediction-contract error."""


def _json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"not JSON serializable: {type(value)!r}")


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        default=_json_default).encode("utf-8")).hexdigest()


def file_sha256(path: Path | str, *, chunk_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for block in iter(lambda: stream.read(chunk_size), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path | str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EvaluatorV2BindingError(f"cannot read JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise EvaluatorV2BindingError(f"JSON object required: {path}")
    return value


def _require_file(path: Path | str, role: str) -> Path:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise EvaluatorV2BindingError(f"{role} is missing: {target}")
    return target


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvaluatorV2BindingError(f"{label} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise EvaluatorV2BindingError(f"{label} must be finite")
    return number


def _finite_vector(value: Any, label: str, length: int) -> list[float]:
    if not isinstance(value, list) or len(value) != length:
        raise EvaluatorV2BindingError(f"{label} must have shape ({length},)")
    return [_finite(item, f"{label}[{index}]") for index, item in enumerate(value)]


def _same_float(actual: Any, expected: float, label: str, *, atol: float = 1e-10) -> None:
    if not math.isclose(_finite(actual, label), float(expected), rel_tol=0.0, abs_tol=atol):
        raise EvaluatorV2BindingError(f"{label} differs from frozen value")


def _source_map(request: Mapping[str, Any]) -> dict[str, str]:
    entries = request.get("source_files")
    if not isinstance(entries, list) or not entries:
        raise EvaluatorV2BindingError("frozen request source_files are missing")
    result: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("role"), str):
            raise EvaluatorV2BindingError("malformed frozen source entry")
        role = str(entry["role"])
        digest = entry.get("sha256")
        if not isinstance(digest, str) or len(digest) != 64:
            raise EvaluatorV2BindingError(f"frozen source hash missing for {role}")
        if role in result:
            raise EvaluatorV2BindingError(f"duplicate frozen source role {role}")
        result[role] = digest
    return result


def validate_frozen_request(request: Mapping[str, Any]) -> dict[str, Any]:
    """Validate v15 semantics with HDF5 stat only and no source content read."""
    try:
        bound = v15.validate_request_v15(
            request, verify_sources=False, verify_hdf5_stat=True)
        profile = request.get("observer_profile")
        v14.validate_observer_profile(profile, request=request)
    except Exception as error:
        raise EvaluatorV2BindingError(f"frozen v15 request is invalid: {error}") from error
    if request.get("model_invoked") is not False:
        raise EvaluatorV2BindingError("frozen request model_invoked must be false")
    qualification = request.get("qualification")
    if qualification != UNKNOWN:
        raise EvaluatorV2BindingError("frozen request qualification must remain UNKNOWN")
    return {
        "request_id": request.get("request_id"),
        "source_file_count": len(_source_map(request)),
        "trajectory_content_read": False,
        "verified_hdf5": bound.get("_verified_hdf5"),
        "observer_profile_sha256": profile.get("sha256") if isinstance(profile, Mapping) else None,
    }


def _validate_source_binding(result: Mapping[str, Any], request: Mapping[str, Any]) -> None:
    source = result.get("source_binding")
    if not isinstance(source, Mapping):
        raise EvaluatorV2BindingError("result source_binding is missing")
    if source.get("binding_status") not in {
            "EXACT_CURRENT_SOURCE_BOUND", "EXACT_CURRENT_SOURCE_BOUND_RELOCATED"}:
        raise EvaluatorV2BindingError("result is not exactly CURRENT-bound")
    expected_sources = _source_map(request)
    if source.get("current_catalog_sha256") != request["current_binding"]["sha256"]:
        raise EvaluatorV2BindingError("result CURRENT hash differs from frozen request")
    if source.get("trajectory_h5_producer_sha256") != request["trajectory_h5"]["producer_declared_sha256"]:
        raise EvaluatorV2BindingError("result producer HDF5 hash differs from frozen request")
    if source.get("source_files") != expected_sources:
        raise EvaluatorV2BindingError("result source-file hash map differs from frozen request")


def _validate_result_shape(result: Mapping[str, Any], request: Mapping[str, Any]) -> dict[str, Any]:
    if result.get("schema") != RESULT_SCHEMA:
        raise EvaluatorV2BindingError("result must be the immutable v16 raw-to-label result")
    if result.get("model_invoked") is not False:
        raise EvaluatorV2BindingError("result model_invoked must be false")
    case = result.get("case_identity")
    if case != request.get("case_identity"):
        raise EvaluatorV2BindingError("result case identity differs from frozen request")
    _validate_source_binding(result, request)

    profile = request.get("observer_profile")
    if not isinstance(profile, Mapping):
        raise EvaluatorV2BindingError("frozen observer profile is missing")
    result_profile = result.get("observer_profile")
    if not isinstance(result_profile, Mapping) or result_profile.get("sha256") != profile.get("sha256"):
        raise EvaluatorV2BindingError("result observer profile is not the frozen profile")

    cohort = result.get("cohort")
    if not isinstance(cohort, Mapping):
        raise EvaluatorV2BindingError("result cohort is missing")
    if cohort.get("identity_key") != "(Zone,Idp)" or cohort.get("selected_count") != 21114:
        raise EvaluatorV2BindingError("result cohort is not the exact 21114 fluid identity set")
    if cohort.get("selected_identity_sha256") != request["cohort"]["source_identity_set_sha256"]:
        raise EvaluatorV2BindingError("result cohort identity hash differs from frozen source cohort")

    denominator = result.get("initial_mass_denominator")
    if not isinstance(denominator, Mapping):
        raise EvaluatorV2BindingError("result initial mass denominator is missing")
    _same_float(denominator.get("denominator_kg"), profile["mass_denominator_kg"],
                "result.initial_mass_denominator.denominator_kg")
    _same_float(denominator.get("initial_fluid_mass_kg"), profile["mass_denominator_kg"],
                "result.initial_mass_denominator.initial_fluid_mass_kg")
    _same_float(denominator.get("initial_missing_mass_kg"), 0.0,
                "result.initial_mass_denominator.initial_missing_mass_kg")
    if denominator.get("initially_absent_count") != 0 or denominator.get("later_missing_unique_count") != 3:
        raise EvaluatorV2BindingError("initial and later missing ledgers are not separated")
    later_missing = _finite(denominator.get("later_missing_mass_kg"), "later missing mass")
    if later_missing <= 0 or later_missing >= float(profile["mass_denominator_kg"]):
        raise EvaluatorV2BindingError("later missing mass is outside the frozen denominator")

    labels = result.get("labels")
    if not isinstance(labels, list) or len(labels) != 21114:
        raise EvaluatorV2BindingError("result labels do not cover all 21114 cohort particles")
    identity: list[tuple[int, int]] = []
    label_status_counts: dict[str, int] = {}
    for index, item in enumerate(labels):
        if not isinstance(item, Mapping):
            raise EvaluatorV2BindingError(f"label {index} is not an object")
        zone, idp = item.get("zone"), item.get("idp")
        if (isinstance(zone, bool) or not isinstance(zone, int) or
                isinstance(idp, bool) or not isinstance(idp, int)):
            raise EvaluatorV2BindingError(f"label {index} has malformed identity")
        identity.append((zone, idp))
        mass = _finite(item.get("initial_mass_kg"), f"label {index} initial mass")
        if mass <= 0:
            raise EvaluatorV2BindingError(f"label {index} initial mass is not positive")
        status = item.get("status")
        if status not in ALLOWED_LABEL_STATUS:
            raise EvaluatorV2BindingError(f"label {index} has unsupported first-passage status {status!r}")
        label_status_counts[str(status)] = label_status_counts.get(str(status), 0) + 1
    if len(set(identity)) != len(identity):
        raise EvaluatorV2BindingError("label identity axis contains duplicates")

    frames = result.get("frame_observations")
    if not isinstance(frames, list) or len(frames) != 401:
        raise EvaluatorV2BindingError("result must retain all 401 frame observations")
    frame_map: dict[int, Mapping[str, Any]] = {}
    for item in frames:
        if not isinstance(item, Mapping) or isinstance(item.get("frame"), bool) or not isinstance(item.get("frame"), int):
            raise EvaluatorV2BindingError("frame observation has no integer frame identity")
        frame = int(item["frame"])
        if frame in frame_map:
            raise EvaluatorV2BindingError("duplicate frame observation")
        frame_map[frame] = item
    indices = profile.get("query_frame_indices")
    times = profile.get("query_times_s")
    if not isinstance(indices, list) or not isinstance(times, list) or len(indices) != len(times):
        raise EvaluatorV2BindingError("frozen query frame/time shape is invalid")
    for frame, expected_time in zip(indices, times):
        if frame not in frame_map:
            raise EvaluatorV2BindingError(f"frozen query frame {frame} is absent")
        observation = frame_map[frame]
        _same_float(observation.get("time_s"), float(expected_time),
                    f"frame {frame} time", atol=2e-8)
        _finite_vector(observation.get("mass_weighted_com_m"), f"frame {frame} COM", 3)
        _finite_vector(observation.get("mass_weighted_mean_velocity_m_s"), f"frame {frame} velocity", 3)
        _finite(observation.get("mass_weighted_kinetic_energy_J"), f"frame {frame} KE")
        if observation.get("position_frame") != "body" or observation.get("velocity_frame") != "world_inertial":
            raise EvaluatorV2BindingError("moving-frame position/velocity semantics are not explicit")
        front = observation.get("mass_quantile_front_m")
        if not isinstance(front, Mapping):
            raise EvaluatorV2BindingError(f"frame {frame} mass fronts are missing")
        for quantile in profile.get("mass_quantiles", []):
            _finite(front.get(str(quantile)), f"frame {frame} mass front {quantile}")
        distribution = observation.get("mass_distribution_kg")
        if not isinstance(distribution, list) or len(distribution) != 4:
            raise EvaluatorV2BindingError(f"frame {frame} mass distribution shape differs")
        if any(_finite(value, f"frame {frame} mass distribution") < 0 for value in distribution):
            raise EvaluatorV2BindingError(f"frame {frame} mass distribution contains negative mass")
    return {
        "label_count": len(labels),
        "identity_count": len(identity),
        "frame_count": len(frames),
        "label_status_counts": label_status_counts,
        "initial_mass_denominator_kg": float(denominator["denominator_kg"]),
        "later_missing_mass_kg": later_missing,
    }


def validate_reconstruction_proof(result: Mapping[str, Any], result_sha256: str,
                                  proof: Mapping[str, Any], proof_path: Path,
                                  raw_report: Mapping[str, Any], raw_report_sha256: str) -> dict[str, Any]:
    if proof.get("schema") != "ds02.stage2.native-raw-to-typed-label-independent-verification.v1":
        raise EvaluatorV2BindingError("independent raw reconstruction proof schema differs")
    labels = proof.get("labels")
    if not isinstance(labels, Mapping) or labels.get("v16_sha256") != result_sha256:
        raise EvaluatorV2BindingError("independent proof is not bound to the v16 result bytes")
    raw_tree = proof.get("raw_tree_evidence")
    reconstruction = result.get("reconstruction_binding")
    if not isinstance(raw_tree, Mapping) or not isinstance(reconstruction, Mapping):
        raise EvaluatorV2BindingError("raw tree proof/reconstruction binding is missing")
    expected_tree = raw_tree.get("expected_raw_tree_sha256")
    if not isinstance(expected_tree, str) or reconstruction.get("raw_tree_sha256") != expected_tree:
        raise EvaluatorV2BindingError("raw tree reconstruction hash differs from independent proof")
    reconstructed = proof.get("reconstructed_H5")
    report_typed = raw_report.get("typed_output")
    if not isinstance(reconstructed, Mapping) or not isinstance(report_typed, Mapping):
        raise EvaluatorV2BindingError("typed reconstruction/report binding is missing")
    if reconstructed.get("sha256") != report_typed.get("sha256") or reconstructed.get("bytes") != report_typed.get("bytes"):
        raise EvaluatorV2BindingError("reconstructed typed output is not report-bound")
    comparison = proof.get("full401_comparison_worker")
    if not isinstance(comparison, Mapping) or not all(comparison.get(key) is True for key in ("all_nonpressure_exact", "structural_exact")):
        raise EvaluatorV2BindingError("independent full401 comparison is not exact")
    if float(comparison.get("pressure_max_absolute_error", math.inf)) != 0.0:
        raise EvaluatorV2BindingError("independent pressure comparison is not exact")
    if labels.get("cohort_count") != 21114 or labels.get("frame_count") != 401:
        raise EvaluatorV2BindingError("independent label proof shape differs")
    if raw_report.get("schema") != "ds02.stage2.f2-native-raw-to-typed-label-report.v2":
        raise EvaluatorV2BindingError("raw-to-label report schema differs")
    boundary = raw_report.get("execution_boundary")
    if not isinstance(boundary, Mapping) or boundary.get("model_invoked") is not False or boundary.get("cfd_invoked") is not False:
        raise EvaluatorV2BindingError("raw-to-label report invokes model/CFD")
    report_self_hash = raw_report.get("report_sha256")
    if report_self_hash is not None:
        body = {key: value for key, value in raw_report.items() if key != "report_sha256"}
        expected_report_self_hash = hashlib.sha256(json.dumps(
            body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            default=_json_default).encode("utf-8")).hexdigest()
        if report_self_hash != expected_report_self_hash:
            raise EvaluatorV2BindingError("raw-to-label report canonical self hash differs")
    return {
        "proof_path": str(proof_path),
        "proof_sha256_verified_by_input": True,
        "raw_tree_sha256": expected_tree,
        "full401_exact": True,
        "typed_reconstruction_sha256": reconstructed.get("sha256"),
        "raw_report_sha256": raw_report_sha256,
        "proof_scope": proof.get("scope"),
    }


def macro_prediction_from_result(result: Mapping[str, Any], profile: Mapping[str, Any],
                                 *, mutation: str = "pass") -> dict[str, Any]:
    """Build a deterministic manual-prediction fixture from frozen observations."""
    frames = {int(item["frame"]): item for item in result["frame_observations"]}
    query_indices = [int(item) for item in profile["query_frame_indices"]]
    prediction: dict[str, Any] = {
        "observer_profile_sha256": profile["sha256"],
        "source_binding": copy.deepcopy(result["source_binding"]),
        "query_times_s": list(profile["query_times_s"]),
        "mass_weighted_com_m": [list(frames[i]["mass_weighted_com_m"]) for i in query_indices],
        "mass_weighted_mean_velocity_m_s": [list(frames[i]["mass_weighted_mean_velocity_m_s"]) for i in query_indices],
        "mass_weighted_kinetic_energy_J": [float(frames[i]["mass_weighted_kinetic_energy_J"]) for i in query_indices],
        "mass_quantile_front_m": [[float(frames[i]["mass_quantile_front_m"][str(q)]) for q in profile["mass_quantiles"]] for i in query_indices],
        "mass_distribution_fraction": [
            [float(value) / float(result["initial_mass_denominator"]["denominator_kg"])
             for value in frames[i]["mass_distribution_kg"]] for i in query_indices],
        "event_status": [str(item["status"]) for item in result["labels"]],
        "event_time_s": [
            float(item["event_time_s"]) if item.get("status") == "observed" else float("nan")
            for item in result["labels"]],
        "scientific_error_budget_estimate": {
            "time_integration_fraction": 0.0,
            "output_sampling_fraction": 0.0,
        },
        "runtime_seconds": 0.0,
        "output_bytes": 0,
    }
    if mutation == "pass":
        return prediction
    if mutation == "wrong_velocity":
        prediction["mass_weighted_mean_velocity_m_s"][0][0] += float(profile["velocity_scale_m_s"]) * 0.5
    elif mutation == "wrong_time":
        first = next((index for index, item in enumerate(result["labels"]) if item.get("status") == "observed"), None)
        if first is None:
            raise EvaluatorV2BindingError("result has no observed event for time counterexample")
        prediction["event_time_s"][first] += float(profile["event_time_scale_s"]) * 0.5
    elif mutation == "wrong_budget":
        prediction["scientific_error_budget_estimate"] = {
            "time_integration_fraction": 0.5,
            "output_sampling_fraction": 0.0,
        }
    elif mutation == "wrong_shape":
        prediction["mass_weighted_com"] = prediction.pop("mass_weighted_com_m")[:-1]
    elif mutation == "wrong_source":
        prediction["source_binding"] = copy.deepcopy(result["source_binding"])
        prediction["source_binding"]["current_catalog_sha256"] = "0" * 64
    else:
        raise EvaluatorV2BindingError(f"unknown prediction mutation {mutation}")
    return prediction


def score_macro_prediction(result: Mapping[str, Any], prediction: Mapping[str, Any],
                           profile: Mapping[str, Any]) -> dict[str, Any]:
    """Score macro/event arrays; source/shape errors remain binding errors."""
    view = copy.deepcopy(dict(result))
    view["schema"] = v14.RESULT_SCHEMA
    try:
        score = v14.evaluate_manual_predictions(view, prediction, profile)
    except Exception as error:
        raise EvaluatorV2BindingError(str(error)) from error
    score["model_invoked"] = False
    score["qualification"] = dict(UNKNOWN)
    return score


def _verify_input_files(request: Mapping[str, Any]) -> list[dict[str, Any]]:
    verified: list[dict[str, Any]] = []
    for entry in request.get("input_files", []):
        if not isinstance(entry, Mapping) or entry.get("hash_mode") != "content_sha256":
            raise EvaluatorV2BindingError("input file must use content_sha256")
        path = _require_file(entry.get("path"), f"input {entry.get('role')}")
        actual = file_sha256(path)
        if actual != entry.get("sha256"):
            raise EvaluatorV2BindingError(f"input SHA differs for {entry.get('role')}")
        expected_bytes = entry.get("bytes")
        if expected_bytes is not None and path.stat().st_size != expected_bytes:
            raise EvaluatorV2BindingError(f"input byte stat differs for {entry.get('role')}")
        verified.append({"role": entry.get("role"), "path": str(path),
                         "sha256": actual, "bytes": path.stat().st_size,
                         "content_read": True})
    return verified


def run_trial(request: Mapping[str, Any], *, output: Path) -> dict[str, Any]:
    if request.get("schema") != REQUEST_SCHEMA or request.get("sha256") != canonical_sha(request):
        raise EvaluatorV2BindingError("evaluator v2 request canonical schema/hash differs")
    if request.get("role") != "DEVELOPMENT" or request.get("model_invoked") is not False:
        raise EvaluatorV2BindingError("evaluator v2 must remain model-free DEVELOPMENT")
    if request.get("qualification") != UNKNOWN:
        raise EvaluatorV2BindingError("evaluator v2 qualification must remain UNKNOWN")
    input_validation = _verify_input_files(request)
    result_path = _require_file(request["result"]["path"], "v16 result")
    frozen_path = _require_file(request["frozen_request"]["path"], "frozen v15 request")
    proof_path = _require_file(request["independent_proof"]["path"], "independent raw proof")
    raw_report_path = _require_file(request["raw_to_label_report"]["path"], "raw-to-label report")
    # The result hash is verified by input_files before parsing; loading it is
    # the only large JSON read in this evaluator and is bounded by the request.
    result = load_json(result_path)
    frozen = load_json(frozen_path)
    proof = load_json(proof_path)
    raw_report = load_json(raw_report_path)
    frozen_validation = validate_frozen_request(frozen)
    result_validation = _validate_result_shape(result, frozen)
    result_sha = next((item["sha256"] for item in input_validation if item["role"] == "v16_label_result"), None)
    report_sha = next((item["sha256"] for item in input_validation if item["role"] == "raw_to_label_report"), None)
    if result_sha is None or report_sha is None:
        raise EvaluatorV2BindingError("request must bind result and raw report input hashes")
    proof_validation = validate_reconstruction_proof(result, result_sha, proof, proof_path,
                                                     raw_report, report_sha)
    profile = frozen["observer_profile"]
    cases: dict[str, Any] = {}
    for mutation in ("pass", "wrong_velocity", "wrong_time", "wrong_budget", "wrong_shape", "wrong_source"):
        try:
            score = score_macro_prediction(result, macro_prediction_from_result(result, profile, mutation=mutation), profile)
            cases[mutation] = score
        except EvaluatorV2BindingError as error:
            cases[mutation] = {"status": "BINDING_ERROR", "error": str(error),
                               "binding_error": True, "model_invoked": False,
                               "qualification": dict(UNKNOWN)}
    expected = {
        "pass": "PASS",
        "wrong_velocity": "FAIL",
        "wrong_time": "FAIL",
        "wrong_budget": "FAIL",
        "wrong_shape": "BINDING_ERROR",
        "wrong_source": "BINDING_ERROR",
    }
    if any(cases[key].get("status") != value for key, value in expected.items()):
        raise EvaluatorV2BindingError("operator evaluator counterexample expectations were not met")
    report = {
        "schema": REPORT_SCHEMA,
        "status": "PASS_DEVELOPMENT_RAW_TYPED_LABEL_OPERATOR_TRIAL",
        "request_id": request.get("request_id"),
        "source_profile_binding": frozen_validation,
        "result_binding": result_validation,
        "reconstruction_proof": proof_validation,
        "input_validation": input_validation,
        "cases": cases,
        "case_expectations": expected,
        "hdf5_or_bi4_content_read": False,
        "raw_partout_content_read": False,
        "model_invoked": False,
        "cfd_invoked": False,
        "qualification": dict(UNKNOWN),
        "development_only": True,
        "limitations": [
            "The pass case is derived from the source-bound v16 observations and is an operator self-test.",
            "This evaluator does not recalibrate or accept a solver and grants no QI/QN/QE.",
            "HDF5/BI4/PartOut/RunPARTs are not opened; content credit is inherited only from the bound reconstruction proof.",
            "Physical fate of numerical exclusions, hidden recrossings, and all scientific qualification remain UNKNOWN.",
        ],
    }
    write_new(output, report)
    return report


def write_new(path: Path | str, value: Mapping[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise EvaluatorV2BindingError(f"refusing to overwrite existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False,
                  allow_nan=False, default=_json_default)
        stream.write("\n")


def build_request(*, result: Path, frozen_request: Path, proof: Path,
                  raw_report: Path, output: Path) -> dict[str, Any]:
    """Build an exact request; the parent guard performs the large JSON read."""
    result = _require_file(result, "v16 result")
    frozen_request = _require_file(frozen_request, "frozen v15 request")
    proof = _require_file(proof, "independent proof")
    raw_report = _require_file(raw_report, "raw-to-label report")
    frozen = load_json(frozen_request)
    if frozen.get("schema") != v15.REQUEST_SCHEMA:
        raise EvaluatorV2BindingError("frozen request must be v15")
    source_scripts = [
        ("evaluator_v2", SCRIPT_DIR / "ds_data02_stage2_f2_no_model_evaluator_v2.py"),
        ("v14_operator", SCRIPT_DIR / "ds_data02_stage2_f2_replay_v14.py"),
        ("v15_operator", SCRIPT_DIR / "ds_data02_stage2_f2_replay_v15.py"),
        ("v16_operator", SCRIPT_DIR / "ds_data02_stage2_f2_flux_v16.py"),
        ("raw_converter", SCRIPT_DIR / "ds_data02_f5_bi4.py"),
        ("raw_reconstruction_worker", SCRIPT_DIR / "ds_data02_stage2_f2_native_raw_to_typed_label_v2.py"),
    ]
    inputs = []
    for role, path in [
            ("v16_label_result", result), ("frozen_v15_request", frozen_request),
            ("independent_raw_proof", proof), ("raw_to_label_report", raw_report),
            *source_scripts]:
        path = _require_file(path, role)
        inputs.append({"role": role, "path": str(path), "bytes": path.stat().st_size,
                       "mtime_ns": path.stat().st_mtime_ns,
                       "sha256": file_sha256(path), "hash_mode": "content_sha256"})
    h5 = frozen["trajectory_h5"]
    request: dict[str, Any] = {
        "schema": REQUEST_SCHEMA,
        "request_id": "f2-s1-no-model-evaluator-v2-001",
        "role": "DEVELOPMENT",
        "status": "READY_FOR_PARENT_GUARD",
        "model_invoked": False,
        "cfd_invoked": False,
        "qualification": dict(UNKNOWN),
        "scope": "F2-S1 raw-to-typed-to-label macro/event operator evaluation",
        "frozen_request": {"path": str(frozen_request.resolve()), "schema": frozen["schema"],
                           "sha256": file_sha256(frozen_request)},
        "result": {"path": str(result.resolve()), "schema": RESULT_SCHEMA,
                    "sha256": file_sha256(result), "content_read_by_evaluator": True},
        "independent_proof": {"path": str(proof.resolve()), "sha256": file_sha256(proof)},
        "raw_to_label_report": {"path": str(raw_report.resolve()), "sha256": file_sha256(raw_report)},
        "source_stat_only": [{"role": item["role"], "path": item["path"],
                               "declared_sha256": item["sha256"], "access": "stat_only"}
                              for item in frozen["source_files"]],
        "trajectory_h5_stat_only": {"path": h5["path"], "bytes": h5["bytes"],
                                    "mtime_ns": h5["mtime_ns"],
                                    "producer_declared_sha256": h5["producer_declared_sha256"],
                                    "content_read_by_evaluator": False},
        "input_files": inputs,
        "execution": {
            "command": [sys.executable, str(SCRIPT_DIR / "ds_data02_stage2_f2_no_model_evaluator_v2.py"),
                         "run", "--request", "<this-request>", "--output", "<new-output.json>"],
            "requires_shared_four_guard": True,
            "io_slot": "CPU_JSON_RESULT_AND_SMALL_PROOF;NO_HDF5_OR_BI4_READ",
            "hdf5_or_bi4_read": False,
            "raw_partout_read": False,
            "original_path_fallback": "FORBIDDEN",
            "private_module_imports_must_match_input_sha256": True,
        },
        "score_contract": {
            "macro_observables": ["mass_weighted_com_m", "mass_weighted_mean_velocity_m_s",
                                   "mass_weighted_kinetic_energy_J", "mass_quantile_front_m",
                                   "mass_distribution_fraction"],
            "event_observables": ["event_status", "event_time_s"],
            "source_and_identity_errors": "BINDING_ERROR",
            "wrong_prediction_values": "SCIENTIFIC_SCORE_FAIL",
            "thresholds": "frozen observer_profile only; caller overrides forbidden",
            "time_and_output_budget_basis": "scientific_error_budget fractions; runtime/bytes diagnostic only",
        },
        "expected_cases": ["pass", "wrong_velocity", "wrong_time", "wrong_budget", "wrong_shape", "wrong_source"],
        "limitations": [
            "Pass is a result-derived operator self-test, not reference calibration.",
            "No HDF5/BI4/PartOut/RunPARTs content read by this evaluator.",
            "All QI/QN/QE remain UNKNOWN.",
        ],
    }
    request["sha256"] = canonical_sha(request)
    write_new(output, request)
    return request


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-request")
    build.add_argument("--result", type=Path, required=True)
    build.add_argument("--frozen-request", type=Path, required=True)
    build.add_argument("--proof", type=Path, required=True)
    build.add_argument("--raw-report", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    run = sub.add_parser("run")
    run.add_argument("--request", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "build-request":
            value = build_request(result=args.result, frozen_request=args.frozen_request,
                                  proof=args.proof, raw_report=args.raw_report, output=args.output)
            print(json.dumps({"status": value["status"], "sha256": value["sha256"],
                              "input_count": len(value["input_files"])}, sort_keys=True))
        else:
            value = run_trial(load_json(args.request), output=args.output)
            print(json.dumps({"status": value["status"], "sha256": file_sha256(args.output),
                              "cases": {key: item["status"] for key, item in value["cases"].items()}},
                             sort_keys=True))
    except (EvaluatorV2BindingError, OSError, ValueError, TypeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
