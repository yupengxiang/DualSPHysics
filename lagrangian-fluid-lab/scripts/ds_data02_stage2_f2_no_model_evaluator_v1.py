#!/usr/bin/env python3
"""Source-bound, model-free receiver evaluator trial for F2-S1.

This is a forward evaluator around the immutable v14/v15 operators.  It is
deliberately a JSON-only trial: the result is an already produced v15 typed
replay, while the evaluator validates the frozen request and source/profile
identity by stat and declared hashes.  It does not open the trajectory HDF5,
BI4, or any solver output and it never grants QI/QN/QE.

The generated ``pass`` prediction is an operator self-test fixture.  The
status and event-time cases are deliberately wrong predictions.  None of
these cases are calibration or scientific acceptance evidence.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
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


REQUEST_SCHEMA = "ds02.stage2.f2-no-model-evaluator-request.v1"
REPORT_SCHEMA = "ds02.stage2.f2-no-model-evaluator-report.v1"
PREDICTION_SCHEMA = "ds02.stage2.f2-no-model-receiver-predictions.v1"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}


class EvaluatorBindingError(RuntimeError):
    """Raised for a source, shape, or immutable profile binding error."""


def _json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"not JSON serializable: {type(value)!r}")


def canonical_sha(value: Mapping[str, Any]) -> str:
    payload = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, default=_json_default).encode()).hexdigest()


def file_sha256(path: Path | str, *, chunk_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(chunk_size), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path | str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise EvaluatorBindingError(f"cannot read JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise EvaluatorBindingError(f"JSON object required: {path}")
    return value


def write_new(path: Path | str, value: Mapping[str, Any]) -> None:
    target = Path(path).expanduser()
    if target.exists():
        raise EvaluatorBindingError(f"refusing to overwrite existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False,
                  allow_nan=False, default=_json_default)
        stream.write("\n")


def _require_file(path: Path | str, role: str) -> Path:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise EvaluatorBindingError(f"{role} is missing: {target}")
    return target


def _stat_declared(path: Path | str, *, role: str, expected_bytes: int | None = None,
                   expected_mtime_ns: int | None = None) -> dict[str, Any]:
    target = _require_file(path, role)
    stat = target.stat()
    if expected_bytes is not None and stat.st_size != int(expected_bytes):
        raise EvaluatorBindingError(f"{role} byte stat differs")
    if expected_mtime_ns is not None and stat.st_mtime_ns != int(expected_mtime_ns):
        raise EvaluatorBindingError(f"{role} mtime stat differs")
    return {"role": role, "path": str(target), "bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns, "content_read": False}


def _validate_request_stat_only(request: Mapping[str, Any]) -> dict[str, Any]:
    """Run the frozen v15 contract without hashing sources or reading HDF5."""
    if request.get("schema") != v15.REQUEST_SCHEMA:
        raise EvaluatorBindingError("frozen request is not v15")
    try:
        bound = v15.validate_request_v15(request, verify_sources=False,
                                         verify_hdf5_stat=True)
    except Exception as error:  # preserve the immutable validator's message
        raise EvaluatorBindingError(f"v15 stat-only validation failed: {error}") from error
    # The v15 validator deliberately reports the HDF5 as stat-only.  Make the
    # no-content-read boundary explicit in the new report.
    return {
        "request_id": request.get("request_id"),
        "current_catalog_sha256": request["current_binding"]["sha256"],
        "trajectory_producer_sha256": request["trajectory_h5"]["producer_declared_sha256"],
        "source_file_count": len(request["source_files"]),
        "trajectory_content_read": False,
        "verified_hdf5": bound.get("_verified_hdf5"),
    }


def validate_stat_source_profile(result: Mapping[str, Any], request: Mapping[str, Any],
                                 profile: Mapping[str, Any]) -> dict[str, Any]:
    if result.get("schema") != v15.RESULT_SCHEMA:
        raise EvaluatorBindingError("result is not a v15 replay result")
    if request.get("model_invoked") is not False:
        raise EvaluatorBindingError("frozen request model_invoked must be false")
    if request.get("qualification") != UNKNOWN:
        raise EvaluatorBindingError("frozen request qualification must remain UNKNOWN")
    bound = _validate_request_stat_only(request)
    try:
        frozen = v14.validate_observer_profile(profile, request=request)
    except Exception as error:
        raise EvaluatorBindingError(f"observer profile validation failed: {error}") from error
    source = result.get("source_binding")
    if not isinstance(source, Mapping):
        raise EvaluatorBindingError("result source binding is missing")
    expected = {
        "current_catalog_sha256": request["current_binding"]["sha256"],
        "trajectory_h5_producer_sha256": request["trajectory_h5"]["producer_declared_sha256"],
        "source_files": {str(item["role"]): item["sha256"] for item in request["source_files"]},
    }
    if source.get("binding_status") not in {"EXACT_CURRENT_SOURCE_BOUND", "EXACT_CURRENT_SOURCE_BOUND_RELOCATED"}:
        raise EvaluatorBindingError("result source binding status is not exact")
    for key, value in expected.items():
        if source.get(key) != value:
            raise EvaluatorBindingError(f"result source binding differs: {key}")
    if result.get("observer_profile", {}).get("sha256") != frozen.get("sha256"):
        raise EvaluatorBindingError("result observer profile hash differs")
    if profile.get("sha256") != request.get("observer_profile", {}).get("sha256"):
        raise EvaluatorBindingError("profile is not the profile frozen in the request")
    return {
        "schema": "ds02.stage2.f2-no-model-source-profile-stat-binding.v1",
        "status": "PASS_SOURCE_PROFILE_BOUND_STAT_ONLY",
        "qualification": UNKNOWN,
        "model_invoked": False,
        "content_hash_credit": "producer_and_request_declared_hashes_only; no HDF5/BI4 content reread",
        "v15_stat_validation": bound,
        "observer_profile_sha256": frozen["sha256"],
    }


def _prediction_from_result(result: Mapping[str, Any], profile: Mapping[str, Any],
                            *, mutation: str = "pass") -> dict[str, Any]:
    labels = result.get("labels")
    if not isinstance(labels, list) or not labels:
        raise EvaluatorBindingError("result labels are missing")
    identity: list[list[int]] = []
    volume_status: list[str] = []
    aperture_status: list[str] = []
    destination_status: list[str] = []
    volume_time: list[float | None] = []
    aperture_time: list[float | None] = []
    masses = [0.0, 0.0, 0.0]
    for item in labels:
        if not isinstance(item, Mapping) or not isinstance(item.get("receiver_volume_label"), Mapping):
            raise EvaluatorBindingError("result label lacks receiver payload")
        label = item["receiver_volume_label"]
        identity.append([int(item["zone"]), int(item["idp"])])
        volume_status.append(str(label.get("status")))
        aperture_status.append(str(label.get("aperture_first_arrival_status")))
        destination_status.append(str(label.get("final_destination_status")))
        volume_time.append(label.get("event_time_s"))
        first = label.get("aperture_downward_first")
        aperture_time.append(first.get("time_s") if isinstance(first, Mapping) else None)
        destination = label.get("final_destination_status")
        mass = float(item["initial_mass_kg"])
        if destination == "inside_receiver_volume":
            masses[0] += mass
        elif destination == "outside_receiver_volume":
            masses[1] += mass
        elif destination == "unknown_final_destination":
            masses[2] += mass
        else:
            raise EvaluatorBindingError(f"unknown destination token: {destination}")
    total = sum(masses)
    if not math.isfinite(total) or total <= 0:
        raise EvaluatorBindingError("initial mass sum is invalid")
    predicted: dict[str, Any] = {
        "schema": PREDICTION_SCHEMA,
        "observer_scope": v14.RECEIVER_EVALUATION_SCOPE,
        "observer_profile_sha256": profile["sha256"],
        "identity": identity,
        "receiver_event_status": volume_status,
        "aperture_event_status": aperture_status,
        "final_destination_status": destination_status,
        "receiver_event_time_s": volume_time,
        "aperture_event_time_s": aperture_time,
        "destination_mass_fraction": [value / total for value in masses],
        "model_invoked": False,
        "prediction_provenance": "operator_self_test_fixture_derived_from_source_bound_result",
        "qualification": UNKNOWN,
    }
    if mutation == "status_mismatch":
        predicted["receiver_event_status"] = list(volume_status)
        predicted["receiver_event_status"][0] = "INVALID_MANUAL_STATUS"
    elif mutation == "time_mismatch":
        predicted["receiver_event_time_s"] = list(volume_time)
        observed = next((index for index, value in enumerate(volume_status) if value == "observed"), None)
        if observed is None or volume_time[observed] is None:
            raise EvaluatorBindingError("result has no observed event for time counterexample")
        predicted["receiver_event_time_s"][observed] = float(volume_time[observed]) + float(profile["event_time_scale_s"]) * 0.5
    elif mutation != "pass":
        raise EvaluatorBindingError(f"unknown prediction mutation: {mutation}")
    return predicted


def score_prediction(result: Mapping[str, Any], prediction: Mapping[str, Any],
                     profile: Mapping[str, Any], request: Mapping[str, Any]) -> dict[str, Any]:
    result_view = copy.deepcopy(dict(result))
    result_view["schema"] = v14.RESULT_SCHEMA
    try:
        scored = v14.evaluate_receiver_manual_predictions(
            result_view, prediction, profile, frozen_request=request)
    except Exception as error:
        raise EvaluatorBindingError(f"prediction binding failed: {error}") from error
    scored["model_invoked"] = False
    scored["qualification"] = UNKNOWN
    scored["prediction_schema"] = prediction.get("schema")
    return scored


def run_trial(trial_request: Mapping[str, Any], *, output: Path) -> dict[str, Any]:
    if trial_request.get("schema") != REQUEST_SCHEMA:
        raise EvaluatorBindingError("unsupported evaluator request schema")
    if trial_request.get("sha256") != canonical_sha(trial_request):
        raise EvaluatorBindingError("evaluator request canonical SHA differs")
    if trial_request.get("role") != "DEVELOPMENT" or trial_request.get("model_invoked") is not False:
        raise EvaluatorBindingError("evaluator request must remain model-free DEVELOPMENT")
    result_path = _require_file(trial_request["result"]["path"], "result")
    request_path = _require_file(trial_request["frozen_request"]["path"], "frozen request")
    input_validation = []
    for item in trial_request.get("input_files", []):
        if not isinstance(item, Mapping) or item.get("hash_mode") != "content_sha256":
            raise EvaluatorBindingError("evaluator input file binding is malformed")
        path = _require_file(item.get("path"), f"input {item.get('role')}")
        actual = file_sha256(path)
        if actual != item.get("sha256"):
            raise EvaluatorBindingError(f"evaluator input SHA differs: {item.get('role')}")
        input_validation.append({"role": item.get("role"), "path": str(path),
                                 "sha256": actual, "content_read": True})
    result = load_json(result_path)
    frozen_request = load_json(request_path)
    profile = frozen_request.get("observer_profile")
    if not isinstance(profile, Mapping):
        raise EvaluatorBindingError("frozen request has no observer profile")
    binding = validate_stat_source_profile(result, frozen_request, profile)
    cases = {}
    for mutation in ("pass", "status_mismatch", "time_mismatch"):
        prediction = _prediction_from_result(result, profile, mutation=mutation)
        cases[mutation] = score_prediction(result, prediction, profile, frozen_request)
    report = {
        "schema": REPORT_SCHEMA,
        "status": "PASS_OPERATOR_TRIAL_WITH_EXPECTED_COUNTEREXAMPLES",
        "request_id": trial_request.get("request_id"),
        "result_path": str(result_path),
        "frozen_request_path": str(request_path),
        "source_profile_binding": binding,
        "evaluator_input_validation": input_validation,
        "cases": cases,
        "case_expectations": {
            "pass": "PASS; exact source-bound result-derived self-test only",
            "status_mismatch": "FAIL; wrong status token is a scientific score, not a binding error",
            "time_mismatch": "FAIL; wrong first-event time exceeds frozen event-time threshold",
        },
        "hdf5_or_bi4_content_read": False,
        "model_invoked": False,
        "cfd_invoked": False,
        "qualification": UNKNOWN,
        "development_only": True,
        "limitations": [
            "The pass case is an operator self-test derived from the typed result.",
            "This trial does not calibrate a reference solver or grant scientific qualification.",
            "Source validation uses declared hashes and stat-only HDF5 binding; parent full-content credit remains external.",
        ],
    }
    write_new(output, report)
    return report


def build_request(*, result: Path, frozen_request: Path, output: Path) -> dict[str, Any]:
    result = _require_file(result, "result")
    frozen_request = _require_file(frozen_request, "frozen request")
    request = load_json(frozen_request)
    if request.get("schema") != v15.REQUEST_SCHEMA:
        raise EvaluatorBindingError("frozen request must be v15")
    result_value = load_json(result)
    if result_value.get("schema") != v15.RESULT_SCHEMA:
        raise EvaluatorBindingError("result must be v15")
    # Keep content hashing bounded to the JSON result and code closure.  The
    # source/HDF5 hashes remain the already frozen values in the v15 request.
    module_paths = [SCRIPT_DIR / "ds_data02_stage2_f2_no_model_evaluator_v1.py",
                    SCRIPT_DIR / "ds_data02_stage2_f2_replay_v14.py",
                    SCRIPT_DIR / "ds_data02_stage2_f2_replay_v15.py"]
    inputs = []
    for role, path, mode in [
            ("typed_result_json", result, "content_sha256"),
            ("frozen_v15_request", frozen_request, "content_sha256"),
            ("evaluator", module_paths[0], "content_sha256"),
            ("v14_operator", module_paths[1], "content_sha256"),
            ("v15_operator", module_paths[2], "content_sha256")]:
        inputs.append({"role": role, "path": str(path.resolve()), "bytes": path.stat().st_size,
                       "mtime_ns": path.stat().st_mtime_ns, "sha256": file_sha256(path),
                       "hash_mode": mode})
    # Stat-only dependencies are listed explicitly for the guard.  The runner
    # never hashes the large CSV or opens the HDF5; it only runs the immutable
    # v15 stat/profile contract, which reads the tiny motion.dat endpoint file.
    stat_roles = []
    for item in request.get("source_files", []):
        if not isinstance(item, Mapping):
            raise EvaluatorBindingError("frozen request source entry is malformed")
        stat_roles.append({"role": item["role"], "path": item["path"],
                           "declared_sha256": item["sha256"], "access": "stat_only"})
    h5 = request.get("trajectory_h5")
    if not isinstance(h5, Mapping):
        raise EvaluatorBindingError("frozen request HDF5 binding is missing")
    trial: dict[str, Any] = {
        "schema": REQUEST_SCHEMA,
        "request_id": "f2-s1-no-model-evaluator-v1-001",
        "role": "DEVELOPMENT",
        "status": "READY_FOR_PARENT_GUARD",
        "model_invoked": False,
        "cfd_invoked": False,
        "qualification": UNKNOWN,
        "scope": "F2-S1 finite receiver volume/top aperture status-time-mass evaluator",
        "frozen_request": {"path": str(frozen_request.resolve()),
                           "sha256": file_sha256(frozen_request),
                           "schema": request["schema"]},
        "result": {"path": str(result.resolve()), "sha256": file_sha256(result),
                   "schema": result_value["schema"], "content_read_by_evaluator": True},
        "source_stat_only": stat_roles,
        "trajectory_h5_stat_only": {
            "path": h5["path"], "bytes": h5["bytes"], "mtime_ns": h5["mtime_ns"],
            "producer_declared_sha256": h5["producer_declared_sha256"],
            "content_read_by_evaluator": False,
        },
        "input_files": inputs,
        "execution": {
            "command": [sys.executable, str(module_paths[0]), "run", "--request", "<this-request>",
                         "--output", "<new-output.json>"],
            "requires_shared_four_guard": True,
            "io_slot": "CPU_METADATA_JSON_ONLY",
            "hdf5_or_bi4_read": False,
            "model_or_cfd": False,
            "original_path_fallback": "FORBIDDEN",
        },
        "expected_cases": ["pass", "status_mismatch", "time_mismatch"],
        "limitations": [
            "Stat-only source/HDF5 binding; no full source-content credit is claimed by this evaluator.",
            "Pass is a result-derived operator self-test, never a reference-solver calibration.",
            "All QI/QN/QE remain UNKNOWN.",
        ],
    }
    trial["sha256"] = canonical_sha(trial)
    write_new(output, trial)
    return trial


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-request")
    build.add_argument("--result", type=Path, required=True)
    build.add_argument("--frozen-request", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    run = sub.add_parser("run")
    run.add_argument("--request", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "build-request":
            value = build_request(result=args.result, frozen_request=args.frozen_request,
                                  output=args.output)
            print(json.dumps({"status": value["status"], "sha256": value["sha256"],
                              "input_count": len(value["input_files"])}, sort_keys=True))
        else:
            value = run_trial(load_json(args.request), output=args.output)
            print(json.dumps({"status": value["status"], "sha256": file_sha256(args.output),
                              "cases": {key: item["status"] for key, item in value["cases"].items()}},
                             sort_keys=True))
    except (EvaluatorBindingError, OSError, ValueError, TypeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
