#!/usr/bin/env python3
"""Build a read-only, fail-closed F3 rollout evidence pack.

This sidecar composes the existing rollout/HDF5 validator and metric
summarizer.  It binds one rollout JSON, one rollout-progress JSON, and one
trajectory HDF5 by resolved path, SHA-256, and byte count.  A complete
unbounded diagnostic rollout is required: bounded ``maximum_steps`` runs,
failed/incomplete progress, non-finite state, and future-state declarations
are rejected.

The result is evidence bookkeeping only.  Even a successful pack is
diagnostic-only and always reports ``formal_eligible=false``,
``t1_eligible=false``, and zero qualification credit.  Input artifacts are
opened read-only; only the optional ``--output`` destination is written by
the command-line wrapper.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any

# Make direct ``python scripts/f3_evidence_pack_builder_v1.py`` invocation
# behave like module/test invocation without touching the repository.
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.dont_write_bytecode = True

from scripts import f3_full_rollout_receipt_hdf5_validator_v1 as validator
from scripts import f3_rollout_metric_summarizer_v1 as summarizer


SCHEMA = "core.f3.canonical_evidence_pack.v1"
DEFAULT_EXPECTED_TRANSITIONS = 835


class EvidencePackError(ValueError):
    """An input binding or completion mismatch that must fail closed."""


def _fail(message: str) -> None:
    raise EvidencePackError(f"fail-closed: {message}")


def _reject_json_constant(token: str) -> None:
    raise EvidencePackError(f"non-finite JSON constant is not allowed: {token}")


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(f"{name} must be an object")
    return value


def _strict_bool(value: Any, name: str, *, expected: bool | None = None) -> bool:
    if type(value) is not bool:
        _fail(f"{name} must be a boolean")
    if expected is not None and value is not expected:
        _fail(f"{name} must be {str(expected).lower()}")
    return value


def _strict_int(value: Any, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(f"{name} must be an integer")
    if value < minimum:
        _fail(f"{name} must be >= {minimum}")
    return int(value)


def _canonical_value(value: Any, *, name: str = "value") -> Any:
    """Validate/copy JSON values before deterministic serialization."""
    if value is None or isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            _fail(f"{name} must be finite")
        return value
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if not isinstance(key, str):
                _fail(f"{name} contains a non-string object key")
            result[key] = _canonical_value(item, name=f"{name}.{key}")
        return result
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item, name=f"{name}[{index}]")
                for index, item in enumerate(value)]
    _fail(f"{name} contains unsupported JSON value {type(value).__name__}")


def canonical_json(value: Any) -> str:
    """Return compact UTF-8-safe canonical JSON text without a newline."""
    return json.dumps(
        _canonical_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _stable_read(path: Path, name: str) -> bytes:
    try:
        before = path.stat()
        data = path.read_bytes()
        after = path.stat()
    except OSError as error:
        _fail(f"{name} cannot be read: {error}")
    if (before.st_size != len(data) or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns):
        _fail(f"{name} changed while it was being read")
    return data


def _fingerprint_bytes(path: Path, data: bytes, name: str) -> dict[str, Any]:
    try:
        stat = path.stat()
    except OSError as error:
        _fail(f"{name} cannot be stat'ed: {error}")
    if stat.st_size != len(data):
        _fail(f"{name} byte count changed while it was being read")
    return {
        "path": str(path),
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
    }


def _fingerprint_file(path: Path, name: str) -> dict[str, Any]:
    return _fingerprint_bytes(path, _stable_read(path, name), name)


def _resolve_file(value: Any, *, base: Path, name: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        _fail(f"{name} must be a non-empty path string")
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    try:
        path = candidate.resolve(strict=True)
    except OSError as error:
        _fail(f"{name} does not resolve: {error}")
    if not path.is_file():
        _fail(f"{name} is not a regular file: {path}")
    return path


def _resolve_cli_file(value: str | Path, name: str) -> Path:
    return _resolve_file(str(value), base=Path.cwd(), name=name)


def _load_json(path: Path, name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    raw = _stable_read(path, name)
    try:
        value = json.loads(raw.decode("utf-8"), parse_constant=_reject_json_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, EvidencePackError) as error:
        _fail(f"{name} is not valid UTF-8 JSON: {error}")
    return _mapping(value, name), _fingerprint_bytes(path, raw, name)


def _select_case(evaluation: dict[str, Any], requested_case_id: str | None) -> tuple[str, dict[str, Any]]:
    cases = _mapping(evaluation.get("cases"), "rollout.cases")
    if not cases:
        _fail("rollout.cases must not be empty")
    if requested_case_id is None:
        if len(cases) != 1:
            _fail("case_id is required when rollout contains multiple cases")
        case_id = next(iter(cases))
    else:
        if not isinstance(requested_case_id, str) or not requested_case_id:
            _fail("case_id must be a non-empty string")
        case_id = requested_case_id
    if case_id not in cases:
        _fail(f"case_id is not present in rollout.cases: {case_id}")
    return case_id, _mapping(cases[case_id], f"rollout.cases[{case_id!r}]")


def _path_references(
    locations: list[tuple[str, dict[str, Any], Path]],
    key: str,
    *,
    required: bool,
) -> Path | None:
    resolved: list[tuple[str, Path]] = []
    for label, location, base in locations:
        if key not in location:
            continue
        value = location[key]
        if value is None and not required:
            continue
        resolved.append((label, _resolve_file(value, base=base, name=f"{label}.{key}")))
    if required and not resolved:
        _fail(f"no {key} path reference was supplied")
    if not resolved:
        return None
    first_label, first_path = resolved[0]
    for label, path in resolved[1:]:
        if path != first_path:
            _fail(f"{key} path references disagree: {first_label} vs {label}")
    return first_path


def _optional_path_references(
    locations: list[tuple[str, dict[str, Any], Path]],
    key: str,
) -> list[tuple[str, Path]]:
    result = []
    for label, location, base in locations:
        if key not in location or location[key] is None:
            continue
        result.append((label, _resolve_file(
            location[key], base=base, name=f"{label}.{key}")))
    return result


def _require_false(locations: list[tuple[str, dict[str, Any]]], key: str) -> None:
    for label, location in locations:
        if key in location:
            _strict_bool(location[key], f"{label}.{key}", expected=False)


def _check_declared_digest(
    locations: list[tuple[str, dict[str, Any]]],
    *,
    stem: str,
    artifact: dict[str, Any],
) -> None:
    """Verify optional source-side digest/byte declarations when present."""
    for label, location in locations:
        digest_key = f"{stem}_sha256"
        bytes_key = f"{stem}_bytes"
        if digest_key in location:
            declared = location[digest_key]
            if (not isinstance(declared, str) or len(declared) != 64
                    or any(char not in "0123456789abcdefABCDEF" for char in declared)):
                _fail(f"{label}.{digest_key} is not a SHA-256 hex digest")
            if declared.lower() != artifact["sha256"]:
                _fail(f"{label}.{digest_key} does not match {stem}")
        if bytes_key in location:
            declared_bytes = _strict_int(location[bytes_key], f"{label}.{bytes_key}")
            if declared_bytes != artifact["bytes"]:
                _fail(f"{label}.{bytes_key} does not match {stem}")


def _validate_rollout_metadata(
    evaluation: dict[str, Any],
    row: dict[str, Any],
    nested: dict[str, Any] | None,
    *,
    case_id: str,
    expected_transitions: int,
) -> None:
    if evaluation.get("schema") != "core.evaluation.v1":
        _fail("rollout schema must be core.evaluation.v1")
    if evaluation.get("evaluation_mode") != "diagnostic":
        _fail("evidence pack requires a diagnostic rollout")
    _strict_bool(evaluation.get("diagnostic"), "rollout.diagnostic", expected=True)
    _strict_bool(evaluation.get("formal_eligible"), "rollout.formal_eligible", expected=False)
    _strict_bool(evaluation.get("autonomous"), "rollout.autonomous", expected=True)
    _require_false([("rollout", evaluation)], "future_state_inputs")
    if evaluation.get("maximum_steps") is not None:
        _fail("maximum_steps must be null for a full rollout evidence pack")

    if row.get("case_id") != case_id:
        _fail("rollout case_id does not match the selected case")
    if row.get("failure_category") is not None:
        _fail("rollout case declares failure_category")
    if row.get("first_failure_frame") is not None:
        _fail("rollout case declares first_failure_frame")
    if row.get("scientific_status") != "not_assessed":
        _fail("rollout scientific_status must remain not_assessed")
    if row.get("scientific_failure_category") is not None:
        _fail("rollout scientific_failure_category must be null")
    if row.get("scientific_first_failure_frame") is not None:
        _fail("rollout scientific_first_failure_frame must be null")
    for name in ("expected_frames", "frames_expected"):
        if _strict_int(row.get(name), f"rollout case.{name}", minimum=1) != expected_transitions:
            _fail(f"rollout case.{name} does not match the full denominator")
    for name in ("frames_executed", "frames_predicted"):
        if _strict_int(row.get(name), f"rollout case.{name}") != expected_transitions:
            _fail(f"rollout case.{name} does not cover the full denominator")
    _strict_bool(row.get("executed"), "rollout case.executed", expected=True)
    _strict_bool(row.get("execution_complete"), "rollout case.execution_complete", expected=True)
    _strict_bool(row.get("finite_rollout_complete"),
                 "rollout case.finite_rollout_complete", expected=True)
    _require_false([("rollout.case", row)], "future_state_inputs")

    if nested is not None:
        _require_false([("rollout.case.rollout", nested)], "future_state_inputs")
        for name in (
            "case_id", "expected_frames", "frames_expected", "frames_executed",
            "frames_predicted", "executed", "execution_complete",
            "finite_rollout_complete", "failure_category", "first_failure_frame",
            "trajectory_output", "progress_output", "scientific_status",
            "scientific_failure_category", "scientific_first_failure_frame",
        ):
            if name in nested and name in row and nested[name] != row[name]:
                _fail(f"rollout case.rollout.{name} disagrees with case.{name}")
        if nested.get("failure_category") is not None:
            _fail("rollout case.rollout declares failure_category")
        if nested.get("first_failure_frame") is not None:
            _fail("rollout case.rollout declares first_failure_frame")


def _validate_progress(
    progress: dict[str, Any],
    *,
    case_id: str,
    expected_transitions: int,
) -> None:
    if progress.get("schema") != "core.rollout.progress.v1":
        _fail("progress schema must be core.rollout.progress.v1")
    if progress.get("case_id") != case_id:
        _fail("progress case_id does not match the rollout case")
    if progress.get("status") != "completed":
        _fail("progress status is not completed")
    _strict_bool(progress.get("autonomous"), "progress.autonomous", expected=True)
    _strict_bool(progress.get("future_state_inputs"),
                 "progress.future_state_inputs", expected=False)
    for name in ("expected_frames", "frames_expected"):
        if _strict_int(progress.get(name), f"progress.{name}", minimum=1) != expected_transitions:
            _fail(f"progress.{name} does not match the full denominator")
    for name in ("completed_frames", "frames_executed"):
        if _strict_int(progress.get(name), f"progress.{name}") != expected_transitions:
            _fail(f"progress.{name} does not cover the full denominator")
    _strict_int(progress.get("particles"), "progress.particles", minimum=1)
    _strict_bool(progress.get("execution_complete"),
                 "progress.execution_complete", expected=True)
    _strict_bool(progress.get("finite_rollout_complete"),
                 "progress.finite_rollout_complete", expected=True)
    if progress.get("failure_category") is not None:
        _fail("progress declares failure_category")
    if progress.get("first_failure_frame") is not None:
        _fail("progress declares first_failure_frame")
    if progress.get("scientific_status") != "not_assessed":
        _fail("progress scientific_status must remain not_assessed")
    if progress.get("scientific_failure_category") is not None:
        _fail("progress scientific_failure_category must be null")
    if progress.get("scientific_first_failure_frame") is not None:
        _fail("progress scientific_first_failure_frame must be null")


def _validate_training_receipt(receipt: dict[str, Any]) -> None:
    if receipt.get("schema") != "core.training.v1":
        _fail("training receipt schema must be core.training.v1")
    if receipt.get("evidence_status") != "complete":
        _fail("training receipt evidence_status is not complete")
    _strict_bool(receipt.get("checkpoint_verified"),
                 "training receipt checkpoint_verified", expected=True)
    _strict_int(receipt.get("completed_updates"),
                "training receipt completed_updates", minimum=1)
    if "future_state_inputs" in receipt:
        _strict_bool(receipt["future_state_inputs"],
                     "training receipt future_state_inputs", expected=False)
    evidence = receipt.get("evidence")
    if evidence is not None:
        evidence = _mapping(evidence, "training receipt evidence")
        if evidence.get("status") != "complete":
            _fail("training receipt evidence.status is not complete")


def _checkpoint_reference(
    value: Any,
    *,
    base: Path,
    label: str,
) -> tuple[Path, dict[str, Any] | None]:
    if isinstance(value, str):
        return _resolve_file(value, base=base, name=label), None
    reference = _mapping(value, label)
    if "path" not in reference:
        _fail(f"{label}.path is missing")
    path = _resolve_file(reference["path"], base=base, name=f"{label}.path")
    return path, reference


def _verify_checkpoint_reference(
    path: Path,
    reference: dict[str, Any] | None,
    *,
    label: str,
) -> dict[str, Any]:
    artifact = _fingerprint_file(path, label)
    if reference is None:
        return artifact
    if "sha256" not in reference or "bytes" not in reference:
        _fail(f"{label} must declare sha256 and bytes")
    # Checkpoint references conventionally use bare sha256/bytes rather than
    # the source-side ``checkpoint_sha256`` naming used by JSON receipts.
    declared_sha = reference["sha256"]
    if (not isinstance(declared_sha, str) or len(declared_sha) != 64
            or any(char not in "0123456789abcdefABCDEF" for char in declared_sha)
            or declared_sha.lower() != artifact["sha256"]):
        _fail(f"{label}.sha256 does not match checkpoint")
    declared_bytes = _strict_int(reference["bytes"], f"{label}.bytes")
    if declared_bytes != artifact["bytes"]:
        _fail(f"{label}.bytes does not match checkpoint")
    return artifact


def _merge_checkpoint_paths(
    references: list[tuple[str, Path]],
    *,
    explicit: Path | None,
) -> Path | None:
    paths = [path for _label, path in references]
    if explicit is not None:
        paths.append(explicit)
    if not paths:
        return None
    first = paths[0]
    for path in paths[1:]:
        if path != first:
            _fail("checkpoint path references disagree")
    return first


def build_evidence_pack(
    rollout_json: str | Path,
    progress_json: str | Path,
    trajectory_hdf5: str | Path,
    *,
    checkpoint: str | Path | None = None,
    training_receipt: str | Path | None = None,
    case_id: str | None = None,
    expected_transitions: int = DEFAULT_EXPECTED_TRANSITIONS,
) -> dict[str, Any]:
    """Build one complete F3 evidence pack without modifying input artifacts."""
    expected_transitions = _strict_int(
        expected_transitions, "expected_transitions", minimum=1)
    rollout_path = _resolve_cli_file(rollout_json, "rollout_json")
    progress_path = _resolve_cli_file(progress_json, "progress_json")
    trajectory_path = _resolve_cli_file(trajectory_hdf5, "trajectory_hdf5")
    evaluation, rollout_artifact = _load_json(rollout_path, "rollout JSON")
    progress, progress_artifact = _load_json(progress_path, "progress JSON")
    selected_case_id, row = _select_case(evaluation, case_id)
    nested = row.get("rollout")
    nested = _mapping(nested, "rollout case.rollout") if nested is not None else None

    _validate_rollout_metadata(
        evaluation, row, nested, case_id=selected_case_id,
        expected_transitions=expected_transitions)
    rollout_locations = [
        ("rollout.case", row, rollout_path.parent),
    ]
    if nested is not None:
        rollout_locations.append(("rollout.case.rollout", nested, rollout_path.parent))
    if "trajectory_output" in evaluation:
        rollout_locations.append(("rollout", evaluation, rollout_path.parent))
    referenced_trajectory = _path_references(
        rollout_locations, "trajectory_output", required=True)
    if referenced_trajectory != trajectory_path:
        _fail("trajectory_output does not match the supplied trajectory_hdf5")
    referenced_progress = _path_references(
        rollout_locations, "progress_output", required=True)
    if referenced_progress != progress_path:
        _fail("progress_output does not match the supplied progress_json")

    progress_trajectory = _path_references(
        [("progress", progress, progress_path.parent)],
        "trajectory_output", required=True)
    if progress_trajectory != trajectory_path:
        _fail("progress trajectory_output does not match the supplied trajectory_hdf5")
    _validate_progress(
        progress, case_id=selected_case_id,
        expected_transitions=expected_transitions)

    trajectory_artifact = _fingerprint_file(trajectory_path, "trajectory HDF5")
    rollout_digest_locations = [("rollout.case", row)]
    if nested is not None:
        rollout_digest_locations.append(("rollout.case.rollout", nested))
    rollout_digest_locations.append(("rollout", evaluation))
    _check_declared_digest(
        rollout_digest_locations, stem="trajectory", artifact=trajectory_artifact)
    _check_declared_digest(
        [("progress", progress)], stem="trajectory", artifact=trajectory_artifact)
    _check_declared_digest(
        rollout_digest_locations, stem="progress", artifact=progress_artifact)

    validator_result = validator.validate_receipt(
        rollout_path, trajectory_path, case_id=selected_case_id,
        expected_transitions=expected_transitions)
    if not validator_result.get("passed") or not validator_result.get("complete"):
        _fail("existing rollout/HDF5 validator did not certify a complete rollout")
    if validator_result.get("failure_category") is not None:
        _fail("existing rollout/HDF5 validator reported a failure")
    checks = validator_result.get("checks")
    if not isinstance(checks, dict):
        _fail("existing validator did not return checks")
    if (checks.get("trajectory_transitions") != expected_transitions
            or checks.get("trajectory_frames") != expected_transitions + 1
            or checks.get("tail_frame_count") != 0
            or checks.get("executed_frame_count") != expected_transitions + 1):
        _fail("trajectory shape/completion checks do not cover the full denominator")

    metric_summary = summarizer.summarize_evaluation_file(rollout_path, family="F3")
    summary_cases = metric_summary.get("cases")
    if not isinstance(summary_cases, list) or len(summary_cases) != 1:
        _fail("metric summary must contain exactly one selected case")
    summary_case = _mapping(summary_cases[0], "metric summary case")
    if summary_case.get("case_id") != selected_case_id:
        _fail("metric summary case_id does not match the selected case")
    coverage = _mapping(summary_case.get("coverage"), "metric summary coverage")
    if (coverage.get("expected_frames") != expected_transitions
            or coverage.get("frames_executed") != expected_transitions
            or coverage.get("finite_prefix_frames") != expected_transitions
            or coverage.get("complete_over_registered_denominator") is not True
            or coverage.get("requested_maximum_steps") is not None):
        _fail("metric summary does not certify the complete unbounded denominator")
    if summary_case.get("failure_category") is not None:
        _fail("metric summary reports a failure")
    _strict_bool(summary_case.get("future_state_inputs"),
                 "metric summary future_state_inputs", expected=False)

    training_receipt_artifact = None
    training_receipt_payload = None
    receipt_primary_refs: list[tuple[str, Path]] = []
    receipt_checkpoint_details: list[dict[str, Any]] = []
    if training_receipt is not None:
        training_receipt_path = _resolve_cli_file(training_receipt, "training_receipt")
        training_receipt_payload, training_receipt_artifact = _load_json(
            training_receipt_path, "training receipt")
        _validate_training_receipt(training_receipt_payload)
        primary = training_receipt_payload.get("checkpoint")
        if not isinstance(primary, dict):
            _fail("training receipt.checkpoint must be a hashed object reference")
        primary_path, primary_ref = _checkpoint_reference(
            primary, base=training_receipt_path.parent,
            label="training receipt.checkpoint")
        receipt_primary_refs.append(("training receipt.checkpoint", primary_path))
        receipt_checkpoint_details.append(_verify_checkpoint_reference(
            primary_path, primary_ref, label="training receipt.checkpoint"))
        ledger = training_receipt_payload.get("checkpoints")
        if ledger is not None:
            if not isinstance(ledger, list) or not ledger:
                _fail("training receipt.checkpoints must be a non-empty list")
            for index, reference_value in enumerate(ledger):
                if not isinstance(reference_value, dict):
                    _fail(f"training receipt.checkpoints[{index}] must be a hashed object reference")
                ledger_path, ledger_ref = _checkpoint_reference(
                    reference_value, base=training_receipt_path.parent,
                    label=f"training receipt.checkpoints[{index}]")
                receipt_checkpoint_details.append(_verify_checkpoint_reference(
                    ledger_path, ledger_ref,
                    label=f"training receipt.checkpoints[{index}]"))
            primary_identity = (receipt_checkpoint_details[0]["path"],
                                receipt_checkpoint_details[0]["sha256"],
                                receipt_checkpoint_details[0]["bytes"])
            if not any(
                (item["path"], item["sha256"], item["bytes"]) == primary_identity
                for item in receipt_checkpoint_details[1:]
            ):
                _fail("training receipt.checkpoints does not contain its primary checkpoint")

    checkpoint_locations = [
        ("rollout", evaluation, rollout_path.parent),
        ("rollout.case", row, rollout_path.parent),
    ]
    if nested is not None:
        checkpoint_locations.append(("rollout.case.rollout", nested, rollout_path.parent))
    checkpoint_locations.append(("progress", progress, progress_path.parent))
    eval_checkpoint_refs = _optional_path_references(
        checkpoint_locations, "checkpoint")
    selected_checkpoint = _merge_checkpoint_paths(
        eval_checkpoint_refs + receipt_primary_refs,
        explicit=(None if checkpoint is None
                  else _resolve_cli_file(checkpoint, "checkpoint")),
    )
    checkpoint_artifact = None
    if selected_checkpoint is not None:
        selected_ref = None
        if training_receipt_payload is not None:
            primary = training_receipt_payload["checkpoint"]
            primary_path, primary_ref = _checkpoint_reference(
                primary,
                base=_resolve_cli_file(training_receipt, "training_receipt").parent,
                label="training receipt.checkpoint")
            if primary_path == selected_checkpoint:
                selected_ref = primary_ref
        checkpoint_artifact = _verify_checkpoint_reference(
            selected_checkpoint, selected_ref, label="checkpoint")

    if training_receipt_payload is not None:
        primary_path, _primary_ref = _checkpoint_reference(
            training_receipt_payload["checkpoint"],
            base=_resolve_cli_file(training_receipt, "training_receipt").parent,
            label="training receipt.checkpoint")
        if primary_path != selected_checkpoint:
            _fail("selected checkpoint does not match training receipt.checkpoint")

    artifacts: dict[str, Any] = {
        "rollout_json": rollout_artifact,
        "progress_json": progress_artifact,
        "trajectory_hdf5": trajectory_artifact,
        "checkpoint": checkpoint_artifact,
        "training_receipt": training_receipt_artifact,
    }
    if receipt_checkpoint_details:
        artifacts["training_receipt_checkpoints"] = receipt_checkpoint_details

    result = {
        "schema": SCHEMA,
        "passed": True,
        "fail_closed": False,
        "diagnostic_only": True,
        "formal_eligible": False,
        "t1_eligible": False,
        "qualification_credit": 0,
        "credit": 0,
        "production_artifacts_touched": False,
        "source": {
            "case_id": selected_case_id,
            "evaluation_schema": evaluation["schema"],
            "evaluation_mode": evaluation["evaluation_mode"],
            "expected_transitions": expected_transitions,
            "maximum_steps": None,
            "future_state_inputs": False,
        },
        "artifacts": artifacts,
        "checks": {
            "path_references": True,
            "sha256_and_bytes": True,
            "hdf5_shape": True,
            "hdf5_finite_state": True,
            "hdf5_valid_prefix": True,
            "full_denominator": True,
            "maximum_steps_semantics": True,
            "progress_complete": True,
            "failure_absent": True,
            "future_state_inputs": True,
        },
        "validator": validator_result,
        "metric_summary": metric_summary,
    }
    return _canonical_value(result, name="evidence pack")


def run_evidence_pack(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Return a JSON-safe pass/fail result; all failures remain fail-closed."""
    try:
        return build_evidence_pack(*args, **kwargs)
    except Exception as error:
        return {
            "schema": SCHEMA,
            "passed": False,
            "fail_closed": True,
            "diagnostic_only": True,
            "formal_eligible": False,
            "t1_eligible": False,
            "qualification_credit": 0,
            "credit": 0,
            "production_artifacts_touched": False,
            "failure_reason": str(error),
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rollout_json", type=Path)
    parser.add_argument("progress_json", type=Path)
    parser.add_argument("trajectory_hdf5", type=Path)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--training-receipt", type=Path)
    parser.add_argument("--case-id")
    parser.add_argument("--expected-transitions", type=int,
                        default=DEFAULT_EXPECTED_TRANSITIONS)
    parser.add_argument("--output", type=Path,
                        help="canonical JSON output; default is stdout")
    args = parser.parse_args(argv)
    result = run_evidence_pack(
        args.rollout_json, args.progress_json, args.trajectory_hdf5,
        checkpoint=args.checkpoint, training_receipt=args.training_receipt,
        case_id=args.case_id, expected_transitions=args.expected_transitions)
    text = canonical_json(result) + "\n"
    if args.output is None or str(args.output) == "-":
        sys.stdout.write(text)
    else:
        args.output.write_text(text, encoding="utf-8")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
