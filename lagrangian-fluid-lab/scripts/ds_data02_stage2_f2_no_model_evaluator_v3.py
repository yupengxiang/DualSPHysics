#!/usr/bin/env python3
"""Source-bound model-free evaluator for the real v16 F2 result.

The consumed v2 evaluator required two fields from an earlier internal result
shape (``initial_fluid_mass_kg`` and ``initially_absent_count``).  The real
v16 result deliberately records the same provenance as
``denominator_kg``/``selected_initial_mass_kg`` and zero initial-missing
mass, while its three later losses are represented by
``later_missing_unique_count`` and ``failed_before_observation`` labels.
This forward adapter accepts that exact v16 schema only after proving the
equivalence from the source-bound denominator and frame-zero accounting.  It
does not edit or rewrite the frozen 62 MB result; the normalized view exists
only in memory for the already-consumed v2 scoring functions.

The evaluator remains a DEVELOPMENT operator self-test.  It reads JSON and
small proof/report inputs, invokes no model, CFD, HDF5, BI4, PartOut, or
RunPARTs reader, and leaves QI/QN/QE UNKNOWN.
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

import ds_data02_stage2_f2_no_model_evaluator_v2 as v2


REQUEST_SCHEMA = "ds02.stage2.f2-no-model-evaluator-request.v3"
REPORT_SCHEMA = "ds02.stage2.f2-no-model-evaluator-report.v3"
RESULT_SCHEMA = v2.RESULT_SCHEMA
UNKNOWN = dict(v2.UNKNOWN)


class EvaluatorV3BindingError(RuntimeError):
    """A source, identity, adapter, profile, or prediction-contract error."""


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        default=v2._json_default).encode("utf-8")).hexdigest()


def file_sha256(path: Path | str, *, chunk_size: int = 4 * 1024 * 1024) -> str:
    return v2.file_sha256(path, chunk_size=chunk_size)


def load_json(path: Path | str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EvaluatorV3BindingError(f"cannot read JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise EvaluatorV3BindingError(f"JSON object required: {path}")
    return value


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvaluatorV3BindingError(f"{label} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise EvaluatorV3BindingError(f"{label} must be finite")
    return number


def _same(actual: Any, expected: float, label: str, *, atol: float = 1e-10) -> float:
    value = _finite(actual, label)
    if not math.isclose(value, float(expected), rel_tol=0.0, abs_tol=atol):
        raise EvaluatorV3BindingError(f"{label} differs from source-bound denominator")
    return value


def _frame_zero(result: Mapping[str, Any]) -> Mapping[str, Any]:
    frames = result.get("frame_observations")
    if not isinstance(frames, list):
        raise EvaluatorV3BindingError("v16 frame observations are missing")
    candidates = [item for item in frames
                  if isinstance(item, Mapping) and item.get("frame") == 0]
    if len(candidates) != 1:
        raise EvaluatorV3BindingError("v16 must contain exactly one frame-zero observation")
    return candidates[0]


def adapt_v16_result(result: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Normalize only the documented real-v16 denominator spelling.

    The adapter is intentionally strict.  It will not parse numeric strings,
    infer mass from a particle sum, or turn a later missing particle into an
    initial omission.  A v16 result that already contains the legacy aliases
    must carry numeric values matching the source-bound denominator; otherwise
    it is rejected rather than silently repaired.
    """
    if not isinstance(result, Mapping) or result.get("schema") != RESULT_SCHEMA:
        raise EvaluatorV3BindingError("adapter accepts only ds02.stage2.f2-s1-replay-result.v16")
    out = copy.deepcopy(dict(result))
    denominator = out.get("initial_mass_denominator")
    if not isinstance(denominator, Mapping):
        raise EvaluatorV3BindingError("v16 initial mass denominator is missing")
    normalized = dict(denominator)
    denominator_kg = _finite(normalized.get("denominator_kg"),
                             "v16.initial_mass_denominator.denominator_kg")
    selected_mass = _same(normalized.get("selected_initial_mass_kg"), denominator_kg,
                          "v16.initial_mass_denominator.selected_initial_mass_kg")
    initial_missing = _finite(normalized.get("initial_missing_mass_kg"),
                              "v16.initial_mass_denominator.initial_missing_mass_kg")
    if initial_missing != 0.0:
        raise EvaluatorV3BindingError(
            "v16 initial missing mass is nonzero; no legacy initial-fluid alias may be derived")
    later_missing = _finite(normalized.get("later_missing_mass_kg"),
                            "v16.initial_mass_denominator.later_missing_mass_kg")
    later_count = normalized.get("later_missing_unique_count")
    if isinstance(later_count, bool) or not isinstance(later_count, int) or later_count != 3:
        raise EvaluatorV3BindingError("v16 later missing identity count must be exactly three")

    frame_zero = _frame_zero(out)
    _same(frame_zero.get("initial_mass_denominator_kg"), denominator_kg,
          "v16.frame_zero.initial_mass_denominator_kg")
    _same(frame_zero.get("initial_missing_mass_bucket_kg"), 0.0,
          "v16.frame_zero.initial_missing_mass_bucket_kg")
    mass_accounting = frame_zero.get("mass_accounting")
    if not isinstance(mass_accounting, Mapping):
        raise EvaluatorV3BindingError("v16 frame-zero mass accounting is missing")
    _same(mass_accounting.get("initial_missing_mass_kg"), 0.0,
          "v16.frame_zero.mass_accounting.initial_missing_mass_kg")
    _same(frame_zero.get("denominator_unobserved_mass_kg"), 0.0,
          "v16.frame_zero.denominator_unobserved_mass_kg")

    cohort = out.get("cohort")
    if not isinstance(cohort, Mapping):
        raise EvaluatorV3BindingError("v16 cohort is missing")
    if cohort.get("initial_fluid_candidates") != cohort.get("selected_count"):
        raise EvaluatorV3BindingError(
            "v16 cohort does not prove that the selected source cohort was complete")
    if cohort.get("selected_count") != 21114:
        raise EvaluatorV3BindingError("v16 cohort is not the exact 21114-particle source cohort")

    legacy_initial = normalized.get("initial_fluid_mass_kg")
    if legacy_initial is not None:
        _same(legacy_initial, denominator_kg,
              "v16.initial_mass_denominator.initial_fluid_mass_kg")
        legacy_initial_source = "v16_explicit_numeric_field"
    else:
        normalized["initial_fluid_mass_kg"] = denominator_kg
        legacy_initial_source = (
            "v16_denominator_kg_selected_initial_mass_kg_with_zero_initial_missing_and_frame0"
        )

    legacy_absent = normalized.get("initially_absent_count")
    if legacy_absent is not None:
        if isinstance(legacy_absent, bool) or not isinstance(legacy_absent, int) or legacy_absent != 0:
            raise EvaluatorV3BindingError(
                "v16 initially_absent_count must be integer zero when present")
        absent_source = "v16_explicit_numeric_field"
    else:
        normalized["initially_absent_count"] = 0
        absent_source = "v16_zero_initial_missing_frame0_and_complete_source_cohort"

    out["initial_mass_denominator"] = normalized
    adapter = {
        "schema": "ds02.stage2.f2-v16-denominator-adapter.v1",
        "source_schema": RESULT_SCHEMA,
        "legacy_initial_fluid_mass_kg": {
            "value": denominator_kg,
            "source": legacy_initial_source,
        },
        "legacy_initially_absent_count": {
            "value": 0,
            "source": absent_source,
        },
        "later_missing_unique_count": later_count,
        "later_missing_mass_kg": later_missing,
        "source_result_unchanged": True,
        "in_memory_only": True,
    }
    return out, adapter


def _verify_input_files(request: Mapping[str, Any]) -> list[dict[str, Any]]:
    return v2._verify_input_files(request)


def run_trial(request: Mapping[str, Any], *, output: Path) -> dict[str, Any]:
    if request.get("schema") != REQUEST_SCHEMA or request.get("sha256") != canonical_sha(request):
        raise EvaluatorV3BindingError("evaluator v3 request canonical schema/hash differs")
    if request.get("role") != "DEVELOPMENT" or request.get("model_invoked") is not False:
        raise EvaluatorV3BindingError("evaluator v3 must remain model-free DEVELOPMENT")
    if request.get("qualification") != UNKNOWN:
        raise EvaluatorV3BindingError("evaluator v3 qualification must remain UNKNOWN")
    input_validation = _verify_input_files(request)
    result_path = v2._require_file(request["result"]["path"], "v16 result")
    frozen_path = v2._require_file(request["frozen_request"]["path"], "frozen v15 request")
    proof_path = v2._require_file(request["independent_proof"]["path"], "independent raw proof")
    raw_report_path = v2._require_file(request["raw_to_label_report"]["path"], "raw-to-label report")
    raw_result = load_json(result_path)
    result, adapter = adapt_v16_result(raw_result)
    frozen = load_json(frozen_path)
    proof = load_json(proof_path)
    raw_report = load_json(raw_report_path)
    frozen_validation = v2.validate_frozen_request(frozen)
    result_validation = v2._validate_result_shape(result, frozen)
    result_sha = next((item["sha256"] for item in input_validation
                       if item["role"] == "v16_label_result"), None)
    report_sha = next((item["sha256"] for item in input_validation
                       if item["role"] == "raw_to_label_report"), None)
    if result_sha is None or report_sha is None:
        raise EvaluatorV3BindingError("request must bind result and raw report input hashes")
    proof_validation = v2.validate_reconstruction_proof(
        result, result_sha, proof, proof_path, raw_report, report_sha)
    profile = frozen["observer_profile"]
    cases: dict[str, Any] = {}
    for mutation in ("pass", "wrong_velocity", "wrong_time", "wrong_budget",
                     "wrong_shape", "wrong_source"):
        try:
            prediction = v2.macro_prediction_from_result(result, profile, mutation=mutation)
            cases[mutation] = v2.score_macro_prediction(result, prediction, profile)
        except v2.EvaluatorV2BindingError as error:
            cases[mutation] = {
                "status": "BINDING_ERROR", "error": str(error),
                "binding_error": True, "model_invoked": False,
                "qualification": dict(UNKNOWN),
            }
    expected = {
        "pass": "PASS", "wrong_velocity": "FAIL", "wrong_time": "FAIL",
        "wrong_budget": "FAIL", "wrong_shape": "BINDING_ERROR",
        "wrong_source": "BINDING_ERROR",
    }
    if any(cases[key].get("status") != value for key, value in expected.items()):
        raise EvaluatorV3BindingError("operator evaluator counterexample expectations were not met")
    report = {
        "schema": REPORT_SCHEMA,
        "status": "PASS_DEVELOPMENT_RAW_TYPED_LABEL_OPERATOR_TRIAL_V3_ADAPTED",
        "request_id": request.get("request_id"),
        "source_profile_binding": frozen_validation,
        "result_binding": result_validation,
        "v16_schema_adapter": adapter,
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
            "The v16 denominator adapter is an in-memory source-bound view; the frozen result bytes are unchanged.",
            "The pass case is derived from source-bound v16 observations and remains an operator self-test.",
            "This evaluator does not recalibrate or accept a solver and grants no QI/QN/QE.",
            "HDF5/BI4/PartOut/RunPARTs are not opened; content credit is inherited only from the bound reconstruction proof.",
            "Physical fate of numerical exclusions, hidden recrossings, and scientific qualification remain UNKNOWN.",
        ],
    }
    v2.write_new(output, report)
    return report


def build_request(*, result: Path, frozen_request: Path, proof: Path,
                  raw_report: Path, output: Path) -> dict[str, Any]:
    """Build a fresh v3 request from the immutable v2 request graph."""
    v2.build_request(result=result, frozen_request=frozen_request, proof=proof,
                     raw_report=raw_report, output=output)
    target = Path(output).expanduser().resolve()
    request = load_json(target)
    request["schema"] = REQUEST_SCHEMA
    request["request_id"] = "f2-s1-no-model-evaluator-v3-v16-adapter-001"
    request["scope"] = "F2-S1 real v16 raw-to-typed-to-label macro/event operator evaluation with strict denominator adapter"
    request["adapter"] = {
        "schema": "ds02.stage2.f2-v16-denominator-adapter.v1",
        "source_result_schema": RESULT_SCHEMA,
        "in_memory_only": True,
        "legacy_aliases": {
            "initial_fluid_mass_kg": "denominator_kg == selected_initial_mass_kg with zero initial missing and frame-zero proof",
            "initially_absent_count": "zero initial missing mass/bucket, zero frame-zero unobserved mass, complete selected source cohort",
        },
        "numeric_string_coercion": False,
        "later_missing_is_not_initial_missing": True,
    }
    inputs = []
    evaluator_replaced = False
    for item in request.get("input_files", []):
        value = dict(item)
        if value.get("role") == "evaluator_v2":
            value.update({
                "role": "evaluator_v3",
                "path": str(SCRIPT),
                "bytes": SCRIPT.stat().st_size,
                "mtime_ns": SCRIPT.stat().st_mtime_ns,
                "sha256": file_sha256(SCRIPT),
            })
            evaluator_replaced = True
        inputs.append(value)
    if not evaluator_replaced:
        raise EvaluatorV3BindingError("v2 request did not contain evaluator_v2 input")
    request["input_files"] = inputs
    execution = dict(request.get("execution", {}))
    command = list(execution.get("command", []))
    if len(command) >= 2:
        command[1] = str(SCRIPT)
    execution["command"] = command
    execution["adapter_schema"] = "ds02.stage2.f2-v16-denominator-adapter.v1"
    request["execution"] = execution
    request["limitations"] = list(request.get("limitations", [])) + [
        "The v3 adapter accepts only numeric source-bound v16 denominator fields and derives legacy aliases in memory.",
        "The original v16 JSON remains immutable and is hash-verified as an input.",
    ]
    request["sha256"] = canonical_sha(request)
    target.unlink()
    v2.write_new(target, request)
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
                                  proof=args.proof, raw_report=args.raw_report,
                                  output=args.output)
            print(json.dumps({"status": value["status"], "sha256": value["sha256"],
                              "input_count": len(value["input_files"])}, sort_keys=True))
        else:
            value = run_trial(load_json(args.request), output=args.output)
            print(json.dumps({"status": value["status"], "sha256": file_sha256(args.output),
                              "cases": {key: item["status"] for key, item in value["cases"].items()}},
                             sort_keys=True))
    except (EvaluatorV3BindingError, v2.EvaluatorV2BindingError,
            OSError, ValueError, TypeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
