#!/usr/bin/env python3
"""Evaluate a completed portable F2 typed replay without invoking a model.

The portable runner reads the relocated HDF5 and applies the v15 observer and
label operators.  This evaluator consumes that JSON result and the immutable
orchestration receipt; it does not reopen HDF5, BI4, PartOut, or RunPARTs.
It scores hand supplied macro and finite-receiver predictions through the
frozen v14 operators and records binding errors separately from scientific
prediction failures.

The portable result is deliberately treated as a typed replay.  It is not an
independent raw-to-typed reconstruction proof, and this entry point never
promotes QI, QN, or QE.  A request is built only after a completed
orchestration report contains the same result bytes, so a previous typed-only
product cannot be substituted silently.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import ds_data02_stage2_f2_replay_v14 as v14
import ds_data02_stage2_f2_replay_v15 as v15


REQUEST_SCHEMA = "ds02.stage2.f2-portable-no-model-evaluator-request.v1"
REPORT_SCHEMA = "ds02.stage2.f2-portable-no-model-evaluator-report.v1"
ORCHESTRATION_SCHEMA = "ds02.stage2.f2-portable-orchestration-report.v7"
PORTABLE_RESULT_SCHEMA = v15.RESULT_SCHEMA
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")


class PortableEvaluatorBindingError(RuntimeError):
    """Raised for an unsafe or incomplete portable-evaluator binding."""


def _json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"not JSON serializable: {type(value)!r}")


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        default=_json_default).encode("utf-8")).hexdigest()


def canonical_value_sha(value: Mapping[str, Any]) -> str:
    """Hash a nested JSON object independently of its pretty-printing."""
    return canonical_sha(value)


def file_sha256(path: Path | str, *, chunk_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for block in iter(lambda: stream.read(chunk_size), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PortableEvaluatorBindingError(f"cannot read JSON {target}: {error}") from error
    if not isinstance(value, dict):
        raise PortableEvaluatorBindingError(f"JSON object required: {target}")
    return value


def write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise PortableEvaluatorBindingError(f"refusing to overwrite existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False,
                  allow_nan=False, default=_json_default)
        stream.write("\n")
    return target


def _require_file(path: Path | str, role: str) -> Path:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise PortableEvaluatorBindingError(f"{role} is missing: {target}")
    return target


def _require_sha(value: Any, name: str) -> str:
    if (not isinstance(value, str) or len(value) != 64 or
            any(character not in HEX64 for character in value)):
        raise PortableEvaluatorBindingError(f"{name} must be a lowercase SHA-256")
    return value


def _unknown(value: Any) -> bool:
    return isinstance(value, Mapping) and all(value.get(key) == "UNKNOWN" for key in UNKNOWN)


def _expected_source_binding(frozen: Mapping[str, Any]) -> dict[str, Any]:
    current = frozen.get("current_binding")
    trajectory = frozen.get("trajectory_h5")
    source_files = frozen.get("source_files")
    if not isinstance(current, Mapping) or not isinstance(trajectory, Mapping):
        raise PortableEvaluatorBindingError("frozen CURRENT/HDF5 binding is missing")
    if not isinstance(source_files, list) or not source_files:
        raise PortableEvaluatorBindingError("frozen source_files are missing")
    result: dict[str, str] = {}
    for item in source_files:
        if not isinstance(item, Mapping) or not isinstance(item.get("role"), str):
            raise PortableEvaluatorBindingError("malformed frozen source entry")
        role = str(item["role"])
        digest = _require_sha(item.get("sha256"), f"frozen source {role}.sha256")
        if role in result:
            raise PortableEvaluatorBindingError(f"duplicate frozen source role: {role}")
        result[role] = digest
    return {
        "current_catalog_sha256": _require_sha(current.get("sha256"), "CURRENT SHA"),
        "trajectory_h5_producer_sha256": _require_sha(
            trajectory.get("producer_declared_sha256"), "trajectory producer SHA"),
        "source_files": result,
    }


def validate_frozen_request(frozen: Mapping[str, Any]) -> dict[str, Any]:
    """Validate v15 semantics and HDF5 stat only; no trajectory bytes are read."""
    if frozen.get("schema") != v15.REQUEST_SCHEMA:
        raise PortableEvaluatorBindingError("frozen request must use the v15 schema")
    if frozen.get("model_invoked") is not False or frozen.get("cfd_invoked") is not False:
        raise PortableEvaluatorBindingError("frozen request is not model/CFD free")
    if not _unknown(frozen.get("qualification")):
        raise PortableEvaluatorBindingError("frozen request qualification must remain UNKNOWN")
    try:
        bound = v15.validate_request_v15(
            frozen, verify_sources=False, verify_hdf5_stat=True)
        profile = frozen.get("observer_profile")
        v14.validate_observer_profile(profile, request=frozen)
    except Exception as error:
        raise PortableEvaluatorBindingError(f"v15 frozen request validation failed: {error}") from error
    expected = _expected_source_binding(frozen)
    return {
        "request_id": frozen.get("request_id"),
        "current_catalog_sha256": expected["current_catalog_sha256"],
        "trajectory_h5_producer_sha256": expected["trajectory_h5_producer_sha256"],
        "source_file_count": len(expected["source_files"]),
        "trajectory_content_read": False,
        "verified_hdf5": bound.get("_verified_hdf5"),
        "observer_profile_sha256": profile.get("sha256") if isinstance(profile, Mapping) else None,
    }


def _walk_for_result(value: Any) -> dict[str, Any] | None:
    if isinstance(value, Mapping):
        if value.get("schema") == PORTABLE_RESULT_SCHEMA and value.get("trajectory_read") is True:
            return dict(value)
        for child in value.values():
            found = _walk_for_result(child)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _walk_for_result(child)
            if found is not None:
                return found
    return None


def extract_portable_result(report: Mapping[str, Any]) -> dict[str, Any]:
    """Return the v15 result nested in a completed v7 orchestration receipt."""
    if report.get("schema") != ORCHESTRATION_SCHEMA:
        raise PortableEvaluatorBindingError("orchestration report is not v7")
    result = _walk_for_result(report.get("stages", report))
    if result is None:
        raise PortableEvaluatorBindingError("completed report has no portable v15 result")
    return result


def validate_orchestration_report(report: Mapping[str, Any]) -> dict[str, Any]:
    if report.get("schema") != ORCHESTRATION_SCHEMA:
        raise PortableEvaluatorBindingError("orchestration report must use v7 schema")
    if report.get("sha256") != canonical_sha(report):
        raise PortableEvaluatorBindingError("orchestration report canonical SHA differs")
    status = report.get("status")
    if not isinstance(status, str) or not status.startswith("COMPLETE"):
        raise PortableEvaluatorBindingError("portable replay is not a completed result")
    if report.get("model_invoked") is not False or report.get("cfd_invoked") is not False:
        raise PortableEvaluatorBindingError("portable orchestration invoked model/CFD")
    if not _unknown(report.get("qualification")):
        raise PortableEvaluatorBindingError("portable orchestration qualification was promoted")
    if report.get("original_path_fallback") != "FORBIDDEN":
        raise PortableEvaluatorBindingError("portable orchestration permits original-path fallback")
    if report.get("os_open_audit_required") is not True:
        raise PortableEvaluatorBindingError("portable orchestration lacks the required OS open audit")
    private = report.get("private_subprocess")
    if not isinstance(private, Mapping) or private.get("fresh_interpreter") is not True:
        raise PortableEvaluatorBindingError("portable replay was not run in a fresh interpreter")
    forbidden = private.get("forbidden_module_files", [])
    if not isinstance(forbidden, list) or forbidden:
        raise PortableEvaluatorBindingError("portable replay imported a forbidden module path")
    loader = report.get("stages", {}).get("raw_to_typed_loader")
    if not isinstance(loader, Mapping):
        raise PortableEvaluatorBindingError("portable loader receipt is missing")
    return {
        "status": status,
        "request": report.get("request"),
        "private_interpreter": True,
        "forbidden_module_files": [],
        "os_open_audit_required": report.get("os_open_audit_required") is True,
        "nested_result_canonical_sha256": canonical_value_sha(extract_portable_result(report)),
    }


def validate_portable_result(result: Mapping[str, Any], frozen: Mapping[str, Any]) -> dict[str, Any]:
    if result.get("schema") != PORTABLE_RESULT_SCHEMA:
        raise PortableEvaluatorBindingError("portable result must be v15")
    if result.get("trajectory_read") is not True or result.get("runner_status") != "COMPLETE_PROVISIONAL_H5_READ":
        raise PortableEvaluatorBindingError("portable result does not prove a completed H5 read")
    if result.get("original_path_fallback") != "FORBIDDEN":
        raise PortableEvaluatorBindingError("portable result permits original-path fallback")
    if result.get("model_invoked") is not False:
        raise PortableEvaluatorBindingError("portable result model_invoked must be false")
    if not _unknown(result.get("quality", UNKNOWN)):
        raise PortableEvaluatorBindingError("portable result quality was promoted")
    scope = result.get("typed_replay_scope")
    if not isinstance(scope, Mapping) or scope.get("raw_to_label_complete") is not False:
        raise PortableEvaluatorBindingError("portable result is not explicitly typed-replay-only")
    expected = _expected_source_binding(frozen)
    source = result.get("source_binding")
    if not isinstance(source, Mapping):
        raise PortableEvaluatorBindingError("portable result source_binding is missing")
    for key, value in expected.items():
        if source.get(key) != value:
            raise PortableEvaluatorBindingError(f"portable result source binding differs for {key}")
    if result.get("case_identity") != frozen.get("case_identity"):
        raise PortableEvaluatorBindingError("portable result case identity differs from frozen request")
    profile = frozen.get("observer_profile")
    if not isinstance(profile, Mapping) or result.get("observer_profile", {}).get("sha256") != profile.get("sha256"):
        raise PortableEvaluatorBindingError("portable result observer profile differs")
    labels = result.get("labels")
    frames = result.get("frame_observations")
    if not isinstance(labels, list) or len(labels) != 21114:
        raise PortableEvaluatorBindingError("portable result does not cover all 21114 labels")
    if not isinstance(frames, list) or len(frames) != 401:
        raise PortableEvaluatorBindingError("portable result does not cover all 401 frames")
    return {
        "schema": PORTABLE_RESULT_SCHEMA,
        "trajectory_read": True,
        "typed_replay_only": True,
        "label_count": len(labels),
        "frame_count": len(frames),
        "source_binding": copy.deepcopy(dict(source)),
        "observer_profile_sha256": profile["sha256"],
        "raw_to_label_complete": False,
        "qualification": dict(UNKNOWN),
    }


def _result_view(result: Mapping[str, Any]) -> dict[str, Any]:
    view = copy.deepcopy(dict(result))
    view["schema"] = v14.RESULT_SCHEMA
    return view


def _macro_prediction(result: Mapping[str, Any], profile: Mapping[str, Any], *, mutation: str = "pass") -> dict[str, Any]:
    frames = {int(item["frame"]): item for item in result.get("frame_observations", [])}
    indices = [int(value) for value in profile["query_frame_indices"]]
    prediction: dict[str, Any] = {
        "observer_profile_sha256": profile["sha256"],
        "source_binding": copy.deepcopy(result["source_binding"]),
        "query_times_s": list(profile["query_times_s"]),
        "mass_weighted_com_m": [list(frames[index]["mass_weighted_com_m"]) for index in indices],
        "mass_weighted_mean_velocity_m_s": [list(frames[index]["mass_weighted_mean_velocity_m_s"]) for index in indices],
        "mass_weighted_kinetic_energy_J": [float(frames[index]["mass_weighted_kinetic_energy_J"]) for index in indices],
        "mass_quantile_front_m": [[float(frames[index]["mass_quantile_front_m"][str(q)])
                                    for q in profile["mass_quantiles"]] for index in indices],
        "mass_distribution_fraction": [
            [float(value) / float(result["initial_mass_denominator"]["denominator_kg"])
             for value in frames[index]["mass_distribution_kg"]] for index in indices],
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
    if mutation == "wrong_velocity":
        prediction["mass_weighted_mean_velocity_m_s"][0][0] += float(profile["velocity_scale_m_s"]) * 0.5
    elif mutation == "wrong_time":
        index = next((i for i, item in enumerate(result["labels"])
                      if item.get("status") == "observed"), None)
        if index is None:
            raise PortableEvaluatorBindingError("no observed first-passage event for wrong-time case")
        prediction["event_time_s"][index] += float(profile["event_time_scale_s"]) * 0.5
    elif mutation == "wrong_budget":
        prediction["scientific_error_budget_estimate"]["time_integration_fraction"] = 0.5
    elif mutation == "wrong_shape":
        prediction["mass_weighted_com_m"] = prediction["mass_weighted_com_m"][:-1]
    elif mutation == "wrong_source":
        prediction["source_binding"] = copy.deepcopy(result["source_binding"])
        prediction["source_binding"]["current_catalog_sha256"] = "0" * 64
    elif mutation != "pass":
        raise PortableEvaluatorBindingError(f"unknown macro mutation: {mutation}")
    return prediction


def _receiver_prediction(result: Mapping[str, Any], profile: Mapping[str, Any], *, mutation: str = "pass") -> dict[str, Any]:
    labels = result.get("labels")
    if not isinstance(labels, list) or not labels:
        raise PortableEvaluatorBindingError("portable result labels are missing")
    identity: list[list[int]] = []
    volume: list[str] = []
    aperture: list[str] = []
    destination: list[str] = []
    volume_times: list[Any] = []
    aperture_times: list[Any] = []
    masses = [0.0, 0.0, 0.0]
    for item in labels:
        receiver = item.get("receiver_volume_label")
        if not isinstance(receiver, Mapping):
            raise PortableEvaluatorBindingError("portable result lacks finite receiver labels")
        identity.append([int(item["zone"]), int(item["idp"])])
        volume.append(str(receiver.get("status")))
        aperture.append(str(receiver.get("aperture_first_arrival_status")))
        destination_token = str(receiver.get("final_destination_status"))
        destination.append(destination_token)
        volume_times.append(receiver.get("event_time_s"))
        first = receiver.get("aperture_downward_first")
        aperture_times.append(first.get("time_s") if isinstance(first, Mapping) else None)
        mass = float(item["initial_mass_kg"])
        if destination_token == "inside_receiver_volume":
            masses[0] += mass
        elif destination_token == "outside_receiver_volume":
            masses[1] += mass
        elif destination_token == "unknown_final_destination":
            masses[2] += mass
        else:
            raise PortableEvaluatorBindingError(f"unsupported destination token: {destination_token}")
    total = sum(masses)
    if not math.isfinite(total) or total <= 0:
        raise PortableEvaluatorBindingError("receiver initial mass sum is invalid")
    # v14 accepts NaN for non-observed event times; JSON serialization is only
    # performed for the outer report, never for this in-memory prediction.
    prediction: dict[str, Any] = {
        "observer_scope": v14.RECEIVER_EVALUATION_SCOPE,
        "observer_profile_sha256": profile["sha256"],
        "source_binding": copy.deepcopy(result["source_binding"]),
        "identity": identity,
        "receiver_event_status": volume,
        "aperture_event_status": aperture,
        "final_destination_status": destination,
        "receiver_event_time_s": [float(value) if value is not None else float("nan") for value in volume_times],
        "aperture_event_time_s": [float(value) if value is not None else float("nan") for value in aperture_times],
        "destination_mass_fraction": [value / total for value in masses],
    }
    if mutation == "status_mismatch":
        prediction["receiver_event_status"] = list(volume)
        prediction["receiver_event_status"][0] = "wrong_status_for_counterexample"
    elif mutation == "time_mismatch":
        index = next((i for i, token in enumerate(volume) if token == "observed"), None)
        if index is None or not math.isfinite(float(prediction["receiver_event_time_s"][index])):
            raise PortableEvaluatorBindingError("no observed receiver event for wrong-time case")
        prediction["receiver_event_time_s"][index] += float(profile["event_time_scale_s"]) * 0.5
    elif mutation == "mass_mismatch":
        prediction["destination_mass_fraction"] = [0.0, 0.0, 1.0]
    elif mutation == "wrong_identity":
        prediction["identity"] = list(identity)
        prediction["identity"][0] = [identity[0][0], identity[0][1] + 1]
    elif mutation != "pass":
        raise PortableEvaluatorBindingError(f"unknown receiver mutation: {mutation}")
    return prediction


def _score_macro(result: Mapping[str, Any], prediction: Mapping[str, Any], profile: Mapping[str, Any]) -> dict[str, Any]:
    try:
        score = v14.evaluate_manual_predictions(_result_view(result), prediction, profile)
    except Exception as error:
        raise PortableEvaluatorBindingError(str(error)) from error
    score["model_invoked"] = False
    score["qualification"] = dict(UNKNOWN)
    return score


def _score_receiver(result: Mapping[str, Any], prediction: Mapping[str, Any],
                    profile: Mapping[str, Any], frozen: Mapping[str, Any]) -> dict[str, Any]:
    try:
        score = v14.evaluate_receiver_manual_predictions(
            _result_view(result), prediction, profile, frozen_request=frozen)
    except Exception as error:
        raise PortableEvaluatorBindingError(str(error)) from error
    score["model_invoked"] = False
    score["qualification"] = dict(UNKNOWN)
    return score


def _verify_input_files(request: Mapping[str, Any]) -> list[dict[str, Any]]:
    verified: list[dict[str, Any]] = []
    entries = request.get("input_files")
    if not isinstance(entries, list) or not entries:
        raise PortableEvaluatorBindingError("evaluator input_files are missing")
    for item in entries:
        if not isinstance(item, Mapping) or item.get("hash_mode") != "content_sha256":
            raise PortableEvaluatorBindingError("evaluator input must use content_sha256")
        path = _require_file(item.get("path"), f"input {item.get('role')}")
        actual = file_sha256(path)
        if actual != item.get("sha256"):
            raise PortableEvaluatorBindingError(f"input SHA differs for {item.get('role')}")
        if item.get("bytes") is not None and path.stat().st_size != int(item["bytes"]):
            raise PortableEvaluatorBindingError(f"input byte stat differs for {item.get('role')}")
        verified.append({"role": item.get("role"), "path": str(path),
                         "sha256": actual, "bytes": path.stat().st_size,
                         "content_read": True})
    return verified


def _verify_named_bindings(request: Mapping[str, Any], verified: Sequence[Mapping[str, Any]]) -> None:
    by_role = {str(item.get("role")): item for item in verified}
    for field, role in (("portable_result", "portable_result"),
                        ("orchestration_report", "orchestration_report"),
                        ("frozen_request", "frozen_v15_request"),
                        ("portable_runner_request", "portable_runner_request")):
        binding = request.get(field)
        if not isinstance(binding, Mapping):
            raise PortableEvaluatorBindingError(f"{field} binding is missing")
        checked = by_role.get(role)
        if checked is None or checked.get("sha256") != binding.get("sha256"):
            raise PortableEvaluatorBindingError(f"{field} binding is not covered by input_files")


def _run_case(fn: Any) -> dict[str, Any]:
    try:
        return fn()
    except PortableEvaluatorBindingError as error:
        return {"status": "BINDING_ERROR", "error": str(error),
                "binding_error": True, "model_invoked": False,
                "qualification": dict(UNKNOWN)}


def run_trial(request: Mapping[str, Any], *, output: Path) -> dict[str, Any]:
    if request.get("schema") != REQUEST_SCHEMA or request.get("sha256") != canonical_sha(request):
        raise PortableEvaluatorBindingError("portable evaluator request canonical schema/hash differs")
    if request.get("role") != "DEVELOPMENT" or request.get("model_invoked") is not False:
        raise PortableEvaluatorBindingError("portable evaluator must remain model-free DEVELOPMENT")
    if request.get("cfd_invoked") is not False or not _unknown(request.get("qualification")):
        raise PortableEvaluatorBindingError("portable evaluator model/CFD/qualification boundary is unsafe")
    input_validation = _verify_input_files(request)
    _verify_named_bindings(request, input_validation)
    result_path = _require_file(request["portable_result"]["path"], "portable result")
    report_path = _require_file(request["orchestration_report"]["path"], "orchestration report")
    frozen_path = _require_file(request["frozen_request"]["path"], "frozen v15 request")
    result = load_json(result_path)
    report = load_json(report_path)
    frozen = load_json(frozen_path)
    frozen_validation = validate_frozen_request(frozen)
    report_validation = validate_orchestration_report(report)
    nested = extract_portable_result(report)
    if canonical_value_sha(nested) != canonical_value_sha(result):
        raise PortableEvaluatorBindingError("portable result bytes are not the result nested in the completed report")
    result_validation = validate_portable_result(result, frozen)
    profile = frozen["observer_profile"]

    macro_cases: dict[str, Any] = {}
    for mutation in ("pass", "wrong_velocity", "wrong_time", "wrong_budget", "wrong_shape", "wrong_source"):
        macro_cases[mutation] = _run_case(
            lambda mutation=mutation: _score_macro(
                result, _macro_prediction(result, profile, mutation=mutation), profile))
    receiver_cases: dict[str, Any] = {}
    for mutation in ("pass", "status_mismatch", "time_mismatch", "mass_mismatch", "wrong_identity"):
        receiver_cases[mutation] = _run_case(
            lambda mutation=mutation: _score_receiver(
                result, _receiver_prediction(result, profile, mutation=mutation), profile, frozen))

    # A full case normally contains both observed and non-observed particles;
    # if an event family has no observed sample, retain a visible N/A rather
    # than turning the absence into a fabricated scientific pass.
    macro_expected = {
        "pass": "PASS", "wrong_velocity": "FAIL", "wrong_budget": "FAIL",
        "wrong_shape": "BINDING_ERROR", "wrong_source": "BINDING_ERROR",
    }
    if any(macro_cases[key].get("status") != value for key, value in macro_expected.items()):
        raise PortableEvaluatorBindingError("portable macro counterexample expectations were not met")
    observed = any(item.get("status") == "observed" for item in result.get("labels", []))
    if observed:
        if macro_cases["wrong_time"].get("status") != "FAIL":
            raise PortableEvaluatorBindingError("portable wrong-time macro counterexample did not fail")
    else:
        macro_cases["wrong_time"] = {"status": "NOT_APPLICABLE_NO_OBSERVED_EVENT",
                                      "model_invoked": False, "qualification": dict(UNKNOWN)}
    receiver_expected = {"pass": "PASS", "status_mismatch": "FAIL",
                         "mass_mismatch": "FAIL", "wrong_identity": "BINDING_ERROR"}
    if any(receiver_cases[key].get("status") != value for key, value in receiver_expected.items()):
        raise PortableEvaluatorBindingError("portable receiver counterexample expectations were not met")
    if observed:
        if receiver_cases["time_mismatch"].get("status") != "FAIL":
            raise PortableEvaluatorBindingError("portable wrong-time receiver counterexample did not fail")
    else:
        receiver_cases["time_mismatch"] = {"status": "NOT_APPLICABLE_NO_OBSERVED_EVENT",
                                            "model_invoked": False, "qualification": dict(UNKNOWN)}

    report_value = {
        "schema": REPORT_SCHEMA,
        "status": "PASS_PORTABLE_TYPED_RESULT_OPERATOR_TRIAL",
        "request_id": request.get("request_id"),
        "frozen_request_validation": frozen_validation,
        "orchestration_binding": report_validation,
        "portable_result_validation": result_validation,
        "input_validation": input_validation,
        "macro_cases": macro_cases,
        "receiver_cases": receiver_cases,
        "model_invoked": False,
        "cfd_invoked": False,
        "hdf5_or_bi4_content_read": False,
        "raw_to_typed_reconstruction_invoked": False,
        "raw_to_label_complete": False,
        "qualification": dict(UNKNOWN),
        "development_only": True,
        "limitations": [
            "The portable result is a relocated HDF5-to-typed replay, not an independent raw-to-typed reconstruction proof.",
            "Pass cases are deterministic operator self-tests; prediction failures are not solver qualification.",
            "This evaluator reads only JSON receipts/results and does not reopen HDF5, BI4, PartOut, or RunPARTs.",
            "Unknown fate, hidden recrossings, numerical exclusions, and QI/QN/QE remain UNKNOWN.",
        ],
    }
    write_new(output, report_value)
    return report_value


def _input_entry(role: str, path: Path) -> dict[str, Any]:
    path = _require_file(path, role)
    return {"role": role, "path": str(path), "bytes": path.stat().st_size,
            "mtime_ns": path.stat().st_mtime_ns, "sha256": file_sha256(path),
            "hash_mode": "content_sha256"}


def build_request(*, portable_result: Path, orchestration_report: Path,
                  frozen_request: Path, portable_request: Path, output: Path) -> dict[str, Any]:
    result_path = _require_file(portable_result, "portable result")
    report_path = _require_file(orchestration_report, "orchestration report")
    frozen_path = _require_file(frozen_request, "frozen v15 request")
    portable_request_path = _require_file(portable_request, "portable runner request")
    result = load_json(result_path)
    report = load_json(report_path)
    frozen = load_json(frozen_path)
    portable_request_value = load_json(portable_request_path)
    if result.get("schema") != PORTABLE_RESULT_SCHEMA:
        raise PortableEvaluatorBindingError("portable result must be v15")
    validate_frozen_request(frozen)
    validate_orchestration_report(report)
    nested = extract_portable_result(report)
    if canonical_value_sha(nested) != canonical_value_sha(result):
        raise PortableEvaluatorBindingError("portable result does not match completed report nested result")
    validate_portable_result(result, frozen)
    # A generic v27/ds02.request.v1 or v25 v15 request is accepted as the
    # already-bound runner provenance.  Its own canonical hash, when present,
    # is checked here; the evaluator never treats its case name as identity.
    declared_runner_sha = portable_request_value.get("sha256")
    if declared_runner_sha is not None and declared_runner_sha != canonical_sha(portable_request_value):
        raise PortableEvaluatorBindingError("portable runner request canonical SHA differs")
    source_bindings = [
        _input_entry("portable_result", result_path),
        _input_entry("orchestration_report", report_path),
        _input_entry("frozen_v15_request", frozen_path),
        _input_entry("portable_runner_request", portable_request_path),
        _input_entry("portable_evaluator", SCRIPT_DIR / Path(__file__).name),
        _input_entry("v14_operator", SCRIPT_DIR / "ds_data02_stage2_f2_replay_v14.py"),
        _input_entry("v15_operator", SCRIPT_DIR / "ds_data02_stage2_f2_replay_v15.py"),
        _input_entry("portable_runner_v25", SCRIPT_DIR / "ds_data02_stage2_f2_replay_runner_v25.py"),
        _input_entry("portable_loader_v25", SCRIPT_DIR / "ds_data02_stage2_f2_portable_v25.py"),
        _input_entry("portable_orchestrator_v7", SCRIPT_DIR / "ds_data02_stage2_f2_portable_orchestrator_v7.py"),
    ]
    expected = _expected_source_binding(frozen)
    h5 = frozen["trajectory_h5"]
    trial: dict[str, Any] = {
        "schema": REQUEST_SCHEMA,
        "request_id": "f2-s1-portable-no-model-evaluator-v1-001",
        "role": "DEVELOPMENT",
        "status": "READY_FOR_PARENT_CPU_SLOT",
        "model_invoked": False,
        "cfd_invoked": False,
        "qualification": dict(UNKNOWN),
        "scope": "F2-S1 relocated v15 typed replay macro and finite-receiver operator evaluation",
        "portable_result": {"path": str(result_path), "schema": result["schema"],
                            "sha256": file_sha256(result_path), "content_read_by_evaluator": True},
        "orchestration_report": {"path": str(report_path), "schema": report["schema"],
                                  "sha256": file_sha256(report_path), "content_read_by_evaluator": True},
        "frozen_request": {"path": str(frozen_path), "schema": frozen["schema"],
                            "sha256": file_sha256(frozen_path)},
        "portable_runner_request": {"path": str(portable_request_path),
                                     "schema": portable_request_value.get("schema"),
                                     "sha256": file_sha256(portable_request_path)},
        "source_binding": expected,
        "source_stat_only": [{"role": item["role"], "path": item["path"],
                               "declared_sha256": item["sha256"], "access": "stat_only"}
                              for item in frozen["source_files"]],
        "trajectory_h5_stat_only": {
            "path": h5["path"], "bytes": h5["bytes"], "mtime_ns": h5["mtime_ns"],
            "producer_declared_sha256": h5["producer_declared_sha256"],
            "content_read_by_evaluator": False,
        },
        "input_files": source_bindings,
        "execution": {
            "python": sys.executable,
            "command": [sys.executable, str(SCRIPT_DIR / Path(__file__).name), "run",
                         "--request", "<this-request>", "--output", "<new-output.json>"],
            "requires_shared_four_guard": True,
            "io_slot": "CPU_JSON_ONLY_NO_HDF5_BI4",
            "hdf5_or_bi4_read": False,
            "raw_partout_read": False,
            "original_path_fallback": "FORBIDDEN",
            "private_interpreter_module_sha_binding": True,
        },
        "score_contract": {
            "macro_observables": ["mass_weighted_com_m", "mass_weighted_mean_velocity_m_s",
                                   "mass_weighted_kinetic_energy_J", "mass_quantile_front_m",
                                   "mass_distribution_fraction"],
            "receiver_observables": ["receiver_event_status", "aperture_event_status",
                                      "final_destination_status", "receiver_event_time_s",
                                      "aperture_event_time_s", "destination_mass_fraction"],
            "identity_and_source_errors": "BINDING_ERROR",
            "wrong_prediction_values": "SCIENTIFIC_SCORE_FAIL",
            "thresholds": "frozen observer profile only; caller overrides forbidden",
            "runtime_and_output": "diagnostic only; scientific time/output fractions are separate",
        },
        "expected_cases": {
            "macro": ["pass", "wrong_velocity", "wrong_time", "wrong_budget", "wrong_shape", "wrong_source"],
            "receiver": ["pass", "status_mismatch", "time_mismatch", "mass_mismatch", "wrong_identity"],
        },
        "portable_scope": {
            "raw_to_typed_reconstruction_proof": False,
            "typed_replay_only": True,
            "model_free": True,
            "qualification": dict(UNKNOWN),
        },
        "limitations": [
            "Request is buildable only from a completed v7 report containing the same result object.",
            "The result inherits the portable HDF5 replay's source audit; this evaluator does not reread native arrays.",
            "All QI/QN/QE remain UNKNOWN and no hidden-test or scientific acceptance credit is implied.",
        ],
    }
    trial["sha256"] = canonical_sha(trial)
    write_new(output, trial)
    return trial


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    extract = sub.add_parser("extract-result")
    extract.add_argument("--orchestration-report", type=Path, required=True)
    extract.add_argument("--output", type=Path, required=True)
    build = sub.add_parser("build-request")
    build.add_argument("--portable-result", type=Path, required=True)
    build.add_argument("--orchestration-report", type=Path, required=True)
    build.add_argument("--frozen-request", type=Path, required=True)
    build.add_argument("--portable-request", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    run = sub.add_parser("run")
    run.add_argument("--request", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "extract-result":
            report = load_json(args.orchestration_report)
            value = extract_portable_result(report)
            write_new(args.output, value)
            print(json.dumps({"status": "EXTRACTED_NESTED_V15_RESULT",
                              "sha256": file_sha256(args.output)}, sort_keys=True))
        elif args.command == "build-request":
            value = build_request(portable_result=args.portable_result,
                                  orchestration_report=args.orchestration_report,
                                  frozen_request=args.frozen_request,
                                  portable_request=args.portable_request,
                                  output=args.output)
            print(json.dumps({"status": value["status"], "sha256": value["sha256"],
                              "input_count": len(value["input_files"])}, sort_keys=True))
        else:
            value = run_trial(load_json(args.request), output=args.output)
            print(json.dumps({"status": value["status"], "sha256": file_sha256(args.output),
                              "macro": {key: item["status"] for key, item in value["macro_cases"].items()},
                              "receiver": {key: item["status"] for key, item in value["receiver_cases"].items()}},
                             sort_keys=True))
    except (PortableEvaluatorBindingError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
