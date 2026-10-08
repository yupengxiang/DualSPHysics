#!/usr/bin/env python3
"""Forward the v3 source-bound evaluator for the actual native report schema.

The real F2 native worker report uses
``f2-native-raw-to-typed-to-label-report.v2``.  The consumed v2 evaluator
spelled that schema without the second ``to`` and rejected the actual report
before checking its proof.  This adapter accepts the two documented report
spellings only when the report is a canonical, complete, model-free native
conversion with a typed-output binding, then delegates all denominator,
identity, macro score, and counterexample checks to v3/v2.  It never changes
the 62 MB result or the native report bytes.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping

SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import ds_data02_stage2_f2_no_model_evaluator_v3 as v3


REQUEST_SCHEMA = "ds02.stage2.f2-no-model-evaluator-request.v4"
REPORT_SCHEMA = "ds02.stage2.f2-no-model-evaluator-report.v4"
ACCEPTED_RAW_REPORT_SCHEMAS = {
    "ds02.stage2.f2-native-raw-to-typed-label-report.v2",
    "ds02.stage2.f2-native-raw-to-typed-to-label-report.v2",
}
# These are the statuses emitted by the source-bound native worker.  The
# label replay status is deliberately not normalized to a generic COMPLETE:
# accepting an invented/partial phase marker would make a report look like a
# complete label product without proving the actual operator ran.
EXPECTED_RAW_TO_TYPED_STATUS = "COMPLETE"
EXPECTED_TYPED_TO_LABEL_STATUS = "V15_LABEL_REPLAY_COMPLETE_DEVELOPMENT_UNKNOWN"
UNKNOWN = dict(v3.UNKNOWN)


class EvaluatorV4BindingError(RuntimeError):
    pass


def canonical_sha(value: Mapping[str, Any]) -> str:
    return v3.canonical_sha(value)


def file_sha256(path: Path | str) -> str:
    return v3.file_sha256(path)


def load_json(path: Path | str) -> dict[str, Any]:
    return v3.load_json(path)


def _validate_actual_raw_report(result: Mapping[str, Any], result_sha256: str,
                                proof: Mapping[str, Any], proof_path: Path,
                                raw_report: Mapping[str, Any], raw_report_sha256: str) -> dict[str, Any]:
    """Apply v2 proof checks plus the actual report's schema/phase gates."""
    if raw_report.get("schema") not in ACCEPTED_RAW_REPORT_SCHEMAS:
        raise v3.v2.EvaluatorV2BindingError("raw-to-label report schema differs")
    if raw_report.get("status") != "COMPLETE_DEVELOPMENT_UNKNOWN":
        raise v3.v2.EvaluatorV2BindingError("raw-to-label report is not a complete development report")
    boundary = raw_report.get("execution_boundary")
    if not isinstance(boundary, Mapping):
        raise v3.v2.EvaluatorV2BindingError("raw-to-label execution boundary is missing")
    for key, expected in (("model_invoked", False), ("cfd_invoked", False),
                          ("raw_opened", True), ("hdf5_opened", True),
                          ("converter_invoked", True), ("label_operator_invoked", True),
                          ("parent_stage2guard_required", True)):
        if boundary.get(key) is not expected:
            raise v3.v2.EvaluatorV2BindingError(
                f"raw-to-label execution boundary {key} is not {expected!r}")
    typed = raw_report.get("typed_output")
    raw_stage = raw_report.get("raw_to_typed")
    label_stage = raw_report.get("typed_to_label")
    if not isinstance(typed, Mapping) or not isinstance(raw_stage, Mapping) or not isinstance(label_stage, Mapping):
        raise v3.v2.EvaluatorV2BindingError("actual raw-to-label stage bindings are incomplete")
    if typed.get("sha256") != proof.get("reconstructed_H5", {}).get("sha256"):
        raise v3.v2.EvaluatorV2BindingError("actual typed output is not proof-bound")
    if typed.get("bytes") != proof.get("reconstructed_H5", {}).get("bytes"):
        raise v3.v2.EvaluatorV2BindingError("actual typed output byte count is not proof-bound")
    if raw_stage.get("status") != EXPECTED_RAW_TO_TYPED_STATUS:
        raise v3.v2.EvaluatorV2BindingError(
            "actual raw-to-typed stage status is not the native COMPLETE status")
    if label_stage.get("status") != EXPECTED_TYPED_TO_LABEL_STATUS:
        raise v3.v2.EvaluatorV2BindingError(
            "actual typed-to-label stage status is not the native v15 complete development status")
    report_self_hash = raw_report.get("report_sha256")
    if not isinstance(report_self_hash, str):
        raise v3.v2.EvaluatorV2BindingError("actual raw-to-label report self hash is missing")
    body = {key: value for key, value in raw_report.items() if key != "report_sha256"}
    expected_self_hash = hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        default=v3.v2._json_default).encode("utf-8")).hexdigest()
    if report_self_hash != expected_self_hash:
        raise v3.v2.EvaluatorV2BindingError("actual raw-to-label report self hash differs")
    # Reuse the strict identity/cohort/proof checks.  The only old assumption
    # being replaced is the report schema spelling and the missing phase gate.
    old = v3.v2.validate_reconstruction_proof
    v3.v2.validate_reconstruction_proof = lambda *args, **kwargs: None
    try:
        # Inline the v2 proof checks that do not inspect report schema.
        labels = proof.get("labels")
        if not isinstance(labels, Mapping) or labels.get("v16_sha256") != result_sha256:
            raise v3.v2.EvaluatorV2BindingError("independent proof is not bound to the v16 result bytes")
        raw_tree = proof.get("raw_tree_evidence")
        reconstruction = result.get("reconstruction_binding")
        if not isinstance(raw_tree, Mapping) or not isinstance(reconstruction, Mapping):
            raise v3.v2.EvaluatorV2BindingError("raw tree proof/reconstruction binding is missing")
        expected_tree = raw_tree.get("expected_raw_tree_sha256")
        if not isinstance(expected_tree, str) or reconstruction.get("raw_tree_sha256") != expected_tree:
            raise v3.v2.EvaluatorV2BindingError("raw tree reconstruction hash differs from independent proof")
        comparison = proof.get("full401_comparison_worker")
        if not isinstance(comparison, Mapping) or not all(
                comparison.get(key) is True for key in ("all_nonpressure_exact", "structural_exact")):
            raise v3.v2.EvaluatorV2BindingError("independent full401 comparison is not exact")
        if float(comparison.get("pressure_max_absolute_error", float("inf"))) != 0.0:
            raise v3.v2.EvaluatorV2BindingError("independent pressure comparison is not exact")
        if labels.get("cohort_count") != 21114 or labels.get("frame_count") != 401:
            raise v3.v2.EvaluatorV2BindingError("independent label proof shape differs")
    finally:
        v3.v2.validate_reconstruction_proof = old
    return {"proof_path": str(proof_path), "proof_sha256_verified_by_input": True,
            "raw_tree_sha256": proof["raw_tree_evidence"]["expected_raw_tree_sha256"],
            "full401_exact": True, "typed_reconstruction_sha256": typed.get("sha256"),
            "raw_report_sha256": raw_report_sha256, "raw_report_schema": raw_report.get("schema"),
            "proof_scope": proof.get("scope")}


def run_trial(request: Mapping[str, Any], *, output: Path) -> dict[str, Any]:
    if request.get("schema") != REQUEST_SCHEMA:
        raise EvaluatorV4BindingError("evaluator v4 request schema differs")
    original_request_schema = v3.REQUEST_SCHEMA
    original_report_schema = v3.REPORT_SCHEMA
    original_proof = v3.v2.validate_reconstruction_proof
    v3.REQUEST_SCHEMA = REQUEST_SCHEMA
    v3.REPORT_SCHEMA = REPORT_SCHEMA
    v3.v2.validate_reconstruction_proof = _validate_actual_raw_report
    try:
        return v3.run_trial(request, output=output)
    except (v3.EvaluatorV3BindingError, v3.v2.EvaluatorV2BindingError) as error:
        raise EvaluatorV4BindingError(str(error)) from error
    finally:
        v3.REQUEST_SCHEMA = original_request_schema
        v3.REPORT_SCHEMA = original_report_schema
        v3.v2.validate_reconstruction_proof = original_proof


def build_request(source_request: Path | str, output: Path | str) -> dict[str, Any]:
    source_path = Path(source_request).expanduser().resolve()
    source = load_json(source_path)
    if source.get("schema") != "ds02.stage2.f2-no-model-evaluator-request.v3":
        raise EvaluatorV4BindingError("source request must be the immutable v3 request")
    if source.get("sha256") != canonical_sha(source):
        raise EvaluatorV4BindingError("source v3 request canonical SHA differs")
    request = copy.deepcopy(source)
    request["schema"] = REQUEST_SCHEMA
    request["request_id"] = "f2-s1-no-model-evaluator-v4-actual-report-adapter-001"
    request["adapter"] = dict(request.get("adapter", {}))
    request["adapter"].update({
        "schema": "ds02.stage2.f2-actual-native-report-schema-adapter.v1",
        "accepted_raw_report_schemas": sorted(ACCEPTED_RAW_REPORT_SCHEMAS),
        "requires_complete_raw_to_typed_and_typed_to_label": True,
        "requires_report_self_sha256": True,
        "numeric_string_coercion": False,
        "source_result_unchanged": True,
    })
    inputs = []
    replaced = False
    for item in request.get("input_files", []):
        entry = dict(item)
        if entry.get("role") in {"evaluator_v3", "evaluator_v2"}:
            entry.update({"role": "evaluator_v4", "path": str(SCRIPT),
                         "bytes": SCRIPT.stat().st_size, "mtime_ns": SCRIPT.stat().st_mtime_ns,
                         "sha256": file_sha256(SCRIPT)})
            replaced = True
        inputs.append(entry)
    if not replaced:
        raise EvaluatorV4BindingError("v3 request evaluator source binding is missing")
    request["input_files"] = inputs
    execution = dict(request.get("execution", {}))
    command = list(execution.get("command", []))
    if len(command) >= 2:
        command[1] = str(SCRIPT)
    execution["command"] = command
    execution["adapter_schema"] = "ds02.stage2.f2-actual-native-report-schema-adapter.v1"
    request["execution"] = execution
    request["limitations"] = list(request.get("limitations", [])) + [
        "The actual native report uses the raw-to-typed-to-label schema spelling and is checked for complete guarded raw/typed/label phases.",
        "No old v2/v3 failure receipt is rewritten; the v4 request is a new source-bound attempt.",
    ]
    request["sha256"] = canonical_sha(request)
    target = Path(output).expanduser().resolve()
    if target.exists():
        raise EvaluatorV4BindingError(f"refusing existing v4 request: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(request, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    return request


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-request")
    build.add_argument("--source-request", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    run = sub.add_parser("run")
    run.add_argument("--request", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "build-request":
            value = build_request(args.source_request, args.output)
            print(json.dumps({"status": value.get("status"), "sha256": value["sha256"],
                              "input_count": len(value["input_files"])}, sort_keys=True))
        else:
            value = run_trial(load_json(args.request), output=args.output)
            print(json.dumps({"status": value["status"], "sha256": file_sha256(args.output),
                              "cases": {key: item["status"] for key, item in value["cases"].items()}},
                             sort_keys=True))
    except (EvaluatorV4BindingError, v3.EvaluatorV3BindingError,
            v3.v2.EvaluatorV2BindingError, OSError, ValueError, TypeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
