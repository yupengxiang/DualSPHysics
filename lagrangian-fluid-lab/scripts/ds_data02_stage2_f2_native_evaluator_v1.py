#!/usr/bin/env python3
"""Source-bound no-model evaluator for a completed native v4 replay.

The v4 worker already wires v15/v16 labels, but the evaluator was previously
only reachable as an optional flag inside the raw converter.  This entrypoint
is a separate, replay-after-compare gate: it consumes JSON reports/results,
requires a passed v4 typed/reference comparison, verifies the immutable v4
and v2 request hashes, then invokes the frozen v15 manual evaluator.  It never
opens HDF5 or BI4 and never turns a manufactured prediction into QI/QN/QE.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


SCHEMA = "ds02.stage2.f2-native-evaluator.v1"
UNKNOWN_QUALIFICATION = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
V4_SCHEMA = "ds02.stage2.f2-native-raw-to-typed-reference-compare-request.v4"
V4_REPORT_SCHEMA = "ds02.stage2.f2-native-raw-to-typed-reference-compare-report.v4"


class NativeEvaluatorBindingError(ValueError):
    """Raised for a source/report/profile/identity binding failure."""


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value: Mapping[str, Any]) -> str:
    payload = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                      ensure_ascii=True).encode()).hexdigest()


def _load(path: Path | str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise NativeEvaluatorBindingError(f"cannot read JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise NativeEvaluatorBindingError(f"JSON object required: {path}")
    return value


def _require_sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise NativeEvaluatorBindingError(f"{name} must be a lowercase SHA-256")
    return value


def _bound_file(item: Mapping[str, Any], role: str, *, verify: bool = True) -> tuple[Path, str]:
    path_value = item.get("path")
    if not isinstance(path_value, str):
        raise NativeEvaluatorBindingError(f"{role}.path is required")
    path = Path(path_value).expanduser().resolve()
    expected = _require_sha(item.get("sha256"), f"{role}.sha256")
    if not path.is_file():
        raise NativeEvaluatorBindingError(f"{role} is missing: {path}")
    if verify and sha256_file(path) != expected:
        raise NativeEvaluatorBindingError(f"{role} content SHA differs")
    return path, expected


def _load_v15(path: Path, expected_sha: str) -> Any:
    if sha256_file(path) != expected_sha:
        raise NativeEvaluatorBindingError("v15 operator content SHA differs")
    # v15 imports the immutable v14 operator by module name.  Loading a
    # source file with importlib does not add its directory to sys.path, so
    # an evaluator launched from an arbitrary bundle root could otherwise
    # resolve an unrelated checkout (or fail only after the source hashes
    # had passed).  Bind the sibling directory before executing the copied
    # operator; the imported v14 module is then the same directory-local
    # dependency that the v4 request records.
    source_dir = str(path.parent.resolve())
    if source_dir not in sys.path:
        sys.path.insert(0, source_dir)
    spec = importlib.util.spec_from_file_location("ds02_bound_native_evaluator_v15", path)
    if spec is None or spec.loader is None:
        raise NativeEvaluatorBindingError("cannot import bound v15 operator")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _validate_v4_request(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    request = _load(path)
    if request.get("schema") != V4_SCHEMA:
        raise NativeEvaluatorBindingError("v4 request schema is required")
    if request.get("role") != "DEVELOPMENT" or request.get("model_invoked") is not False or request.get("cfd_invoked") is not False:
        raise NativeEvaluatorBindingError("v4 request must remain no-model/no-CFD DEVELOPMENT")
    if request.get("qualification") != UNKNOWN_QUALIFICATION:
        raise NativeEvaluatorBindingError("v4 request qualification must remain UNKNOWN")
    declared = _require_sha(request.get("sha256"), "v4_request.sha256")
    if canonical_sha(request) != declared:
        raise NativeEvaluatorBindingError("v4 request canonical SHA differs")
    base_item = request.get("base_v2_request")
    if not isinstance(base_item, Mapping):
        raise NativeEvaluatorBindingError("base_v2_request binding is required")
    base_path, base_sha = _bound_file(base_item, "base_v2_request")
    base = _load(base_path)
    if base.get("schema") != "ds02.stage2.f2-native-raw-to-typed-to-label-request.v2":
        raise NativeEvaluatorBindingError("base v2 request schema differs")
    modules = request.get("modules")
    if not isinstance(modules, Mapping) or not isinstance(modules.get("v15_operator"), Mapping):
        raise NativeEvaluatorBindingError("v4 v15 operator binding is required")
    v15_path, v15_sha = _bound_file(modules["v15_operator"], "modules.v15_operator")
    contract = request.get("label_evaluator_contract")
    if not isinstance(contract, Mapping) or contract.get("identity_binding") != "(Zone,Idp), source CURRENT/case/config/reference H5 hashes remain bound":
        raise NativeEvaluatorBindingError("v4 evaluator identity/source contract is not frozen")
    if contract.get("qualification") != "DEVELOPMENT; QI/QN/QE UNKNOWN":
        raise NativeEvaluatorBindingError("v4 evaluator qualification contract is malformed")
    return request, {"base": base, "base_sha": base_sha, "v15_path": v15_path, "v15_sha": v15_sha}


def validate_completed_replay(v4_request_path: Path | str, v4_report_path: Path | str) -> dict[str, Any]:
    request_path = Path(v4_request_path).expanduser().resolve()
    report_path = Path(v4_report_path).expanduser().resolve()
    request, bound = _validate_v4_request(request_path)
    report = _load(report_path)
    if report.get("schema") != V4_REPORT_SCHEMA:
        raise NativeEvaluatorBindingError("v4 comparison report schema is required")
    report_request = report.get("request")
    if not isinstance(report_request, Mapping) or report_request.get("path") != str(request_path) or report_request.get("sha256") != sha256_file(request_path):
        raise NativeEvaluatorBindingError("comparison report is bound to a different v4 request")
    if report.get("status") != "COMPLETE_DEVELOPMENT_UNKNOWN":
        raise NativeEvaluatorBindingError("v4 raw/reference comparison is not complete")
    comparison = report.get("typed_reference_comparison")
    if not isinstance(comparison, Mapping) or comparison.get("passed") is not True:
        raise NativeEvaluatorBindingError("v4 typed/reference comparison did not pass")
    base_report_item = report.get("base_v2", {}).get("report") if isinstance(report.get("base_v2"), Mapping) else None
    if not isinstance(base_report_item, str):
        raise NativeEvaluatorBindingError("v4 report has no base v2 report")
    base_report_path = Path(base_report_item).expanduser().resolve()
    if not base_report_path.is_file():
        raise NativeEvaluatorBindingError("base v2 report is missing")
    base_report = _load(base_report_path)
    if base_report.get("schema") != "ds02.stage2.f2-native-raw-to-typed-to-label-report.v2" or base_report.get("status") != "COMPLETE_DEVELOPMENT_UNKNOWN":
        raise NativeEvaluatorBindingError("base v2 report is not a complete development replay")
    typed_to_label = base_report.get("typed_to_label")
    if not isinstance(typed_to_label, Mapping) or not isinstance(typed_to_label.get("result"), str):
        raise NativeEvaluatorBindingError("base v2 report has no v15 label result")
    label_path = Path(str(typed_to_label["result"])).expanduser().resolve()
    if not label_path.is_file():
        raise NativeEvaluatorBindingError("v15 label result is missing")
    label_result = _load(label_path)
    if label_result.get("schema") != "ds02.stage2.f2-s1-replay-result.v15":
        raise NativeEvaluatorBindingError("label result is not a v15 replay result")
    v15_request = bound["base"].get("v15_request")
    if not isinstance(v15_request, Mapping):
        raise NativeEvaluatorBindingError("base v2 frozen v15 request is missing")
    profile = v15_request.get("observer_profile")
    if not isinstance(profile, Mapping):
        raise NativeEvaluatorBindingError("frozen v15 observer profile is missing")
    # This is a source/profile binding check, not merely a schema check.  It
    # compares the replay result's CURRENT, producer-HDF5, and complete
    # source-file hash map with the frozen v15 request/profile before any
    # manual prediction is admitted.  The call only consumes JSON and does
    # not reopen HDF5/BI4.
    v15 = _load_v15(bound["v15_path"], bound["v15_sha"])
    try:
        source_profile_check = v15.validate_result_source_profile(
            label_result, v15_request, profile)
    except Exception as error:
        raise NativeEvaluatorBindingError(
            f"v15 label result/source/profile binding failed: {error}") from error
    return {
        "request": request,
        "bound": bound,
        "report": report,
        "base_report": base_report,
        "label_result": label_result,
        "v15_request": dict(v15_request),
        "observer_profile": dict(profile),
        "source_profile_check": source_profile_check,
        "request_path": str(request_path),
        "report_path": str(report_path),
        "base_report_path": str(base_report_path),
        "label_result_path": str(label_path),
    }


def score_manual_predictions(v4_request_path: Path | str, v4_report_path: Path | str,
                             predictions_path: Path | str) -> dict[str, Any]:
    checked = validate_completed_replay(v4_request_path, v4_report_path)
    prediction_path = Path(predictions_path).expanduser().resolve()
    predictions = _load(prediction_path)
    v15 = _load_v15(checked["bound"]["v15_path"], checked["bound"]["v15_sha"])
    try:
        score = v15.evaluate_receiver_manual_predictions_v15(
            checked["label_result"], predictions, checked["observer_profile"],
            frozen_request=checked["v15_request"])
    except Exception as error:
        raise NativeEvaluatorBindingError(f"v15 evaluator rejected prediction/binding: {error}") from error
    if not isinstance(score, Mapping):
        raise NativeEvaluatorBindingError("v15 evaluator returned a non-object")
    result = {
        "schema": SCHEMA,
        "status": "COMPLETE_DEVELOPMENT_UNKNOWN",
        "scope": "native-v4-passed-typed-reference-to-v15-manual-prediction",
        "source_binding": {
            "v4_request": {"path": checked["request_path"], "sha256": sha256_file(checked["request_path"])},
            "v4_report": {"path": checked["report_path"], "sha256": sha256_file(checked["report_path"])},
            "base_v2_report": {"path": checked["base_report_path"], "sha256": sha256_file(checked["base_report_path"])},
            "v15_label_result": {"path": checked["label_result_path"], "sha256": sha256_file(checked["label_result_path"])},
            "observer_profile_sha256": checked["observer_profile"].get("sha256"),
            "v15_operator_sha256": checked["bound"]["v15_sha"],
        },
        "score": dict(score),
        "model_invoked": False,
        "cfd_invoked": False,
        "hdf5_opened": False,
        "raw_opened": False,
        "qualification": UNKNOWN_QUALIFICATION,
        "limitations": [
            "evaluator consumes completed JSON replay artifacts; it does not independently reopen HDF5/BI4",
            "wrong status/time/mass predictions are scientific FAIL; source/profile/identity/shape mismatches are binding errors",
            "DEVELOPMENT only; QI/QN/QE remain UNKNOWN",
        ],
    }
    result["sha256"] = canonical_sha(result)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("validate")
    check.add_argument("--v4-request", type=Path, required=True)
    check.add_argument("--v4-report", type=Path, required=True)
    score = sub.add_parser("score")
    score.add_argument("--v4-request", type=Path, required=True)
    score.add_argument("--v4-report", type=Path, required=True)
    score.add_argument("--predictions", type=Path, required=True)
    score.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            checked = validate_completed_replay(args.v4_request, args.v4_report)
            result = {"schema": SCHEMA, "status": "READY_FOR_MANUAL_PREDICTION",
                      "hdf5_opened": False, "raw_opened": False,
                      "source": {"v4_request": checked["request_path"], "v4_report": checked["report_path"]},
                      "qualification": UNKNOWN_QUALIFICATION}
            print(json.dumps(result, sort_keys=True))
            return 0
        result = score_manual_predictions(args.v4_request, args.v4_report, args.predictions)
        output = Path(args.output).expanduser()
        if output.exists():
            parser.error(f"refusing to overwrite existing output: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    except (OSError, NativeEvaluatorBindingError) as error:
        parser.error(str(error))
    print(json.dumps({"schema": result["schema"], "status": result["status"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
