#!/usr/bin/env python3
"""Aggregate source-bound F3 ``core_learning.py evaluate`` JSON receipts.

This is a JSON-only, diagnostic-only reducer.  Each input is a thin
``core.f3.rollout_batch_item.v1`` envelope around one ``core.evaluation.v1``
payload.  The envelope binds the immutable manifest and checkpoint identity
for the batch and binds the case identity (including its source SHA) for the
individual item.  A direct ``core.evaluation.v1`` payload is also accepted
when it carries the same top-level ``binding`` object.

The reducer never opens a manifest, case HDF5, checkpoint, trajectory, or
progress path.  It only reads the supplied JSON reports and validates the
declared paths and SHA-256 values.  It never starts a runtime and never writes
registry, completion, ledger, denominator, or gate state.  ``completed``,
``failed``, and ``running`` are execution states, not qualification states:
every successful aggregate is permanently marked ``diagnostic_only`` with
``formal_eligible=false`` and zero credit.
"""
from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Mapping, Sequence
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from typing import Any


SCHEMA = "core.f3.rollout_batch_receipt.v1"
ITEM_SCHEMA = "core.f3.rollout_batch_item.v1"
EVALUATION_SCHEMA = "core.evaluation.v1"
EXPECTED_TRANSITIONS = 835
STATUSES = frozenset({"completed", "failed", "running"})
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
METRIC_FIELDS = ("position_rmse", "position_ade", "velocity_rmse", "velocity_ade")
PATH_FIELDS = ("trajectory_output", "progress_output")
ZERO_CREDIT_FIELDS = (
    "qualification_credit", "credit", "T1_credit", "T2_credit", "T2_macro_credit"
)
FALSE_FORMAL_FIELDS = ("T1_numerical", "T2_macro", "T2_path", "qualification")


class BatchReceiptError(ValueError):
    """A malformed or conflicting diagnostic receipt."""


def _fail(message: str) -> None:
    raise BatchReceiptError(f"fail-closed: {message}")


def _reject_json_constant(token: str) -> None:
    _fail(f"non-finite JSON constant is not allowed: {token}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _check_finite_json(value: Any, *, name: str = "value") -> None:
    """Reject non-JSON values and non-finite floats in programmatic inputs."""
    if value is None or isinstance(value, (bool, str, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            _fail(f"{name} contains a non-finite number")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                _fail(f"{name} contains a non-string object key")
            _check_finite_json(item, name=f"{name}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _check_finite_json(item, name=f"{name}[{index}]")
        return
    _fail(f"{name} contains unsupported value {type(value).__name__}")


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{name} must be an object")
    return value


def _strict_bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        _fail(f"{name} must be a boolean")
    return value


def _strict_int(value: Any, name: str, *, minimum: int = 0, maximum: int | None = None) -> int:
    if type(value) is not int:
        _fail(f"{name} must be an integer")
    if value < minimum or (maximum is not None and value > maximum):
        bound = f" in [{minimum}, {maximum}]" if maximum is not None else f" >= {minimum}"
        _fail(f"{name} must be{bound}")
    return value


def _finite_metric(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(f"{name} must be a finite non-negative number")
    result = float(value)
    if not math.isfinite(result) or result < 0.0:
        _fail(f"{name} must be a finite non-negative number")
    return result


def _nonempty_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        _fail(f"{name} must be a non-empty string without NUL")
    return value


def _path_string(value: Any, name: str) -> str:
    # Paths are declarations only.  They are deliberately not resolved or
    # opened, because the reducer must not touch production trajectories.
    return _nonempty_string(value, name)


def _sha256(value: Any, name: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        _fail(f"{name} must be 64 lowercase hexadecimal characters")
    return value


def _read_json(path: str | Path) -> tuple[Path, dict[str, Any], bytes]:
    report_path = Path(path).expanduser()
    if not report_path.is_file():
        _fail(f"missing report: {report_path}")
    try:
        raw = report_path.read_bytes()
        value = json.loads(
            raw.decode("utf-8"),
            parse_constant=_reject_json_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except BatchReceiptError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        _fail(f"report cannot be read as strict UTF-8 JSON: {report_path}: {error}")
    _check_finite_json(value, name="report")
    return report_path.resolve(), dict(_mapping(value, "report")), raw


def canonical_json(value: Any) -> str:
    """Return deterministic JSON and reject non-finite values."""
    _check_finite_json(value)
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _expected_batch_binding(
    *,
    manifest_path: str,
    manifest_sha256: str,
    checkpoint_path: str,
    checkpoint_sha256: str,
) -> dict[str, dict[str, str]]:
    return {
        "manifest": {
            "path": _path_string(manifest_path, "expected manifest path"),
            "sha256": _sha256(manifest_sha256, "expected manifest sha256"),
        },
        "checkpoint": {
            "path": _path_string(checkpoint_path, "expected checkpoint path"),
            "sha256": _sha256(checkpoint_sha256, "expected checkpoint sha256"),
        },
    }


def _validate_binding(
    value: Any,
    expected: Mapping[str, Mapping[str, str]],
    expected_cases: Mapping[str, Mapping[str, str]],
    *,
    report_label: str,
) -> dict[str, Any]:
    binding = _mapping(value, f"{report_label}.binding")
    manifest = _mapping(binding.get("manifest"), f"{report_label}.binding.manifest")
    checkpoint = _mapping(binding.get("checkpoint"), f"{report_label}.binding.checkpoint")
    case = _mapping(binding.get("case"), f"{report_label}.binding.case")

    observed_manifest = {
        "path": _path_string(manifest.get("path"), f"{report_label}.manifest.path"),
        "sha256": _sha256(manifest.get("sha256"), f"{report_label}.manifest.sha256"),
    }
    observed_checkpoint = {
        "path": _path_string(checkpoint.get("path"), f"{report_label}.checkpoint.path"),
        "sha256": _sha256(checkpoint.get("sha256"), f"{report_label}.checkpoint.sha256"),
    }
    if observed_manifest != dict(expected["manifest"]):
        _fail(f"{report_label} manifest binding drift")
    if observed_checkpoint != dict(expected["checkpoint"]):
        _fail(f"{report_label} checkpoint binding drift")

    case_id = _nonempty_string(case.get("case_id"), f"{report_label}.case.case_id")
    observed_case = {
        "case_id": case_id,
        "path": _path_string(case.get("path"), f"{report_label}.case.path"),
        "sha256": _sha256(case.get("sha256"), f"{report_label}.case.sha256"),
    }
    expected_case = expected_cases.get(case_id)
    if expected_case is None or observed_case != {
        "case_id": case_id,
        "path": expected_case["path"] if expected_case is not None else None,
        "sha256": expected_case["sha256"] if expected_case is not None else None,
    }:
        _fail(f"{report_label} case binding drift or missing expected case binding")
    return {
        "manifest": observed_manifest,
        "case": observed_case,
        "checkpoint": observed_checkpoint,
    }


def _reject_future_inputs(value: Any, *, name: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key == "future_state_inputs":
                if type(item) is not bool or item is not False:
                    _fail(f"{name}.future_state_inputs must be explicit false")
            _reject_future_inputs(item, name=f"{name}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_future_inputs(item, name=f"{name}[{index}]")


def _validate_zero_formal_claims(value: Any, *, name: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key in ZERO_CREDIT_FIELDS:
                if type(item) is not int or item != 0:
                    _fail(f"{name}.{key} must remain integer zero")
            if key in FALSE_FORMAL_FIELDS:
                if type(item) is not bool or item is not False:
                    _fail(f"{name}.{key} must remain false")
            if key == "formal_eligible" and (type(item) is not bool or item is not False):
                _fail(f"{name}.formal_eligible must remain false")
            _validate_zero_formal_claims(item, name=f"{name}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _validate_zero_formal_claims(item, name=f"{name}[{index}]")


def _consensus(locations: Sequence[Mapping[str, Any]], key: str, *, name: str,
               required: bool = False) -> Any:
    values = [location[key] for location in locations if key in location]
    if not values:
        if required:
            _fail(f"{name}.{key} is missing")
        return None
    first = values[0]
    if any(value != first for value in values[1:]):
        _fail(f"{name}.{key} disagrees between duplicated receipt views")
    return first


def _validate_metric_array(value: Any, *, name: str, expected: int, executed: int) -> None:
    if not isinstance(value, list) or len(value) != expected:
        _fail(f"{name} must contain exactly {expected} transition values")
    for index, entry in enumerate(value):
        if index < executed:
            _finite_metric(entry, f"{name}[{index}]")
        elif entry is not None:
            _fail(f"{name}[{index}] must be null after the executed prefix")


def _validate_path_views(
    locations: Sequence[Mapping[str, Any]],
    *,
    name: str,
) -> dict[str, str]:
    result: dict[str, str] = {}
    for key in PATH_FIELDS:
        value = _consensus(locations, key, name=name)
        if value is not None:
            result[key] = _path_string(value, f"{name}.{key}")
    return result


def _validate_score(
    score_value: Any,
    *,
    expected: int,
    executed: int,
    execution_complete: bool,
    failure_category: str | None,
    case_executed: bool,
    name: str,
) -> None:
    score = _mapping(score_value, name)
    if _strict_int(score.get("expected_frames"), f"{name}.expected_frames", minimum=1) != expected:
        _fail(f"{name}.expected_frames disagrees with fixed denominator")
    if _strict_int(score.get("finite_prefix_frames"), f"{name}.finite_prefix_frames", maximum=expected) != executed:
        _fail(f"{name}.finite_prefix_frames disagrees with executed prefix")
    if _strict_bool(score.get("executed"), f"{name}.executed") is not case_executed:
        _fail(f"{name}.executed disagrees with case.executed")
    if _strict_bool(score.get("complete"), f"{name}.complete") is not execution_complete:
        _fail(f"{name}.complete disagrees with execution state")
    if score.get("failure_category") != failure_category:
        _fail(f"{name}.failure_category disagrees with case")
    if "raw_error_coverage" not in score:
        _fail(f"{name}.raw_error_coverage is missing")
    coverage_float = _finite_metric(score["raw_error_coverage"], f"{name}.raw_error_coverage")
    if not math.isclose(coverage_float, executed / expected, rel_tol=0.0, abs_tol=1e-12):
        _fail(f"{name}.raw_error_coverage disagrees with executed prefix")


def _validate_progress(
    progress: Any,
    *,
    case_id: str,
    status: str,
    expected: int,
    executed: int,
    trajectory_path: str | None,
) -> None:
    value = _mapping(progress, "progress")
    if value.get("schema") != "core.rollout.progress.v1":
        _fail("progress schema is not core.rollout.progress.v1")
    if value.get("case_id") != case_id:
        _fail("progress case_id disagrees with binding")
    if value.get("status") != status:
        _fail("progress status disagrees with item status")
    _strict_bool(value.get("autonomous"), "progress.autonomous")
    if value["autonomous"] is not True:
        _fail("progress.autonomous must be true")
    _reject_future_inputs(value, name="progress")
    for key in ("expected_frames", "frames_expected"):
        if _strict_int(value.get(key), f"progress.{key}", minimum=1) != expected:
            _fail(f"progress.{key} disagrees with fixed denominator")
    for key in ("completed_frames", "frames_executed"):
        if _strict_int(value.get(key), f"progress.{key}", maximum=expected) != executed:
            _fail(f"progress.{key} disagrees with case")
    if "trajectory_output" in value:
        declared = _path_string(value["trajectory_output"], "progress.trajectory_output")
        if trajectory_path is None or declared != trajectory_path:
            _fail("progress.trajectory_output drifts from case trajectory_output")


def _unwrap_item(
    payload: Mapping[str, Any],
    *,
    report_label: str,
) -> tuple[Mapping[str, Any], Mapping[str, Any], str | None, Mapping[str, Any] | None]:
    _reject_future_inputs(payload, name=report_label)
    _validate_zero_formal_claims(payload, name=report_label)
    schema = payload.get("schema")
    if schema == ITEM_SCHEMA:
        evaluation = _mapping(payload.get("evaluation"), f"{report_label}.evaluation")
        binding = _mapping(payload.get("binding"), f"{report_label}.binding")
        status = payload.get("status")
        if status not in STATUSES:
            _fail(f"{report_label}.status must be completed, failed, or running")
        progress = payload.get("progress")
        if progress is not None:
            progress = _mapping(progress, f"{report_label}.progress")
        return evaluation, binding, status, progress
    if schema == EVALUATION_SCHEMA:
        # A direct Core output may be passed through if the launcher appended
        # the source binding.  Without that binding the case SHA is unknown,
        # so accepting it would silently weaken source provenance.
        binding = _mapping(payload.get("binding"), f"{report_label}.binding")
        progress_value = payload.get("progress")
        progress = None if progress_value is None else _mapping(progress_value, f"{report_label}.progress")
        status = payload.get("status")
        if status is not None and status not in STATUSES:
            _fail(f"{report_label}.status is invalid")
        return payload, binding, status, progress
    _fail(f"{report_label}.schema is not a supported F3 rollout receipt")


def _validate_evaluation(
    evaluation: Mapping[str, Any],
    binding: Mapping[str, Any],
    expected_binding: Mapping[str, Mapping[str, str]],
    expected_cases: Mapping[str, Mapping[str, str]],
    *,
    explicit_status: str | None,
    progress: Mapping[str, Any] | None,
    report_label: str,
    expected_transitions: int,
) -> dict[str, Any]:
    if evaluation.get("schema") != EVALUATION_SCHEMA:
        _fail(f"{report_label}.evaluation.schema is unsupported")
    if evaluation.get("evaluation_mode") != "diagnostic":
        _fail(f"{report_label} is not a diagnostic evaluation")
    if evaluation.get("diagnostic") is not True:
        _fail(f"{report_label}.diagnostic must be true")
    if evaluation.get("formal_eligible") is not False:
        _fail(f"{report_label}.formal_eligible must be false")
    if evaluation.get("autonomous") is not True:
        _fail(f"{report_label}.autonomous must be true")
    _reject_future_inputs(evaluation, name=f"{report_label}.evaluation")
    _validate_zero_formal_claims(evaluation, name=f"{report_label}.evaluation")

    observed_binding = _validate_binding(
        binding, expected_binding, expected_cases, report_label=report_label)
    case_id = observed_binding["case"]["case_id"]
    checkpoint_value = evaluation.get("checkpoint")
    if _path_string(checkpoint_value, f"{report_label}.evaluation.checkpoint") != expected_binding["checkpoint"]["path"]:
        _fail(f"{report_label}.evaluation checkpoint path drift")

    for list_name in ("registered_case_ids", "selected_case_ids"):
        values = evaluation.get(list_name)
        if not isinstance(values, list) or values != [case_id]:
            _fail(f"{report_label}.evaluation.{list_name} must contain exactly the bound case")
    expected_map = _mapping(evaluation.get("expected_frames"), f"{report_label}.evaluation.expected_frames")
    if list(expected_map) != [case_id] or _strict_int(
            expected_map.get(case_id), f"{report_label}.evaluation.expected_frames[{case_id}]",
            minimum=1) != expected_transitions:
        _fail(f"{report_label}.evaluation expected transition denominator is not {expected_transitions}")
    fixed_denominator = evaluation.get("fixed_denominator")
    if fixed_denominator is not None:
        fixed = _mapping(fixed_denominator, f"{report_label}.evaluation.fixed_denominator")
        if list(fixed) != [case_id]:
            _fail(f"{report_label}.evaluation.fixed_denominator must contain exactly the bound case")
        fixed_case = _mapping(fixed[case_id], f"{report_label}.fixed_denominator[{case_id!r}]")
        if _strict_int(fixed_case.get("expected_frames"),
                       f"{report_label}.fixed_denominator[{case_id!r}].expected_frames",
                       minimum=1) != expected_transitions:
            _fail(f"{report_label}.fixed_denominator disagrees with fixed 835-transition scope")
    if "formal_capacity" in evaluation and evaluation["formal_capacity"] is not None:
        _fail(f"{report_label}.evaluation.formal_capacity must be null for diagnostics")

    cases = _mapping(evaluation.get("cases"), f"{report_label}.evaluation.cases")
    if list(cases) != [case_id]:
        _fail(f"{report_label}.evaluation.cases must contain exactly the bound case")
    row = _mapping(cases[case_id], f"{report_label}.evaluation.cases[{case_id!r}]")
    nested_value = row.get("rollout")
    nested = None if nested_value is None else _mapping(nested_value, f"{report_label}.case.rollout")
    locations: list[Mapping[str, Any]] = [row] if nested is None else [nested, row]
    _reject_future_inputs(row, name=f"{report_label}.case")
    _validate_zero_formal_claims(row, name=f"{report_label}.case")
    if nested is not None:
        _reject_future_inputs(nested, name=f"{report_label}.case.rollout")
        _validate_zero_formal_claims(nested, name=f"{report_label}.case.rollout")

    if _consensus(locations, "case_id", name=f"{report_label}.case", required=True) != case_id:
        _fail(f"{report_label}.case_id disagrees with binding")
    for key in ("expected_frames", "frames_expected"):
        if _strict_int(_consensus(locations, key, name=f"{report_label}.case", required=True),
                       f"{report_label}.case.{key}", minimum=1) != expected_transitions:
            _fail(f"{report_label}.case.{key} disagrees with fixed denominator")

    executed = _strict_int(_consensus(locations, "frames_executed", name=f"{report_label}.case", required=True),
                           f"{report_label}.case.frames_executed", maximum=expected_transitions)
    predicted = _consensus(locations, "frames_predicted", name=f"{report_label}.case")
    if predicted is not None and _strict_int(predicted, f"{report_label}.case.frames_predicted",
                                             maximum=expected_transitions) != executed:
        _fail(f"{report_label}.case.frames_predicted disagrees with frames_executed")
    failure_category = _consensus(locations, "failure_category", name=f"{report_label}.case")
    if failure_category is not None and (not isinstance(failure_category, str) or not failure_category):
        _fail(f"{report_label}.case.failure_category must be a non-empty string or null")
    first_failure = _consensus(locations, "first_failure_frame", name=f"{report_label}.case")
    if first_failure is not None:
        first_failure = _strict_int(first_failure, f"{report_label}.case.first_failure_frame",
                                    minimum=1, maximum=expected_transitions)
    execution_complete = _strict_bool(
        _consensus(locations, "execution_complete", name=f"{report_label}.case", required=True),
        f"{report_label}.case.execution_complete")
    finite_complete = _strict_bool(
        _consensus(locations, "finite_rollout_complete", name=f"{report_label}.case", required=True),
        f"{report_label}.case.finite_rollout_complete")
    case_executed = _strict_bool(
        _consensus(locations, "executed", name=f"{report_label}.case", required=True),
        f"{report_label}.case.executed")

    metric_values: dict[str, Any] = {}
    for key in METRIC_FIELDS:
        metric_values[key] = _consensus(locations, key, name=f"{report_label}.case", required=True)
        _validate_metric_array(metric_values[key], name=f"{report_label}.case.{key}",
                              expected=expected_transitions, executed=executed)

    score = _consensus(locations, "score", name=f"{report_label}.case", required=True)
    # ``score`` is not duplicated in a normal nested rollout view, but it is
    # still validated as the public denominator contract when present there.
    _validate_score(score, expected=expected_transitions, executed=executed,
                    execution_complete=execution_complete,
                    failure_category=failure_category,
                    case_executed=case_executed,
                    name=f"{report_label}.case.score")

    inferred_status = "completed" if execution_complete and finite_complete and executed == expected_transitions else (
        "failed" if failure_category is not None else "running"
    )
    status = explicit_status or inferred_status
    if status not in STATUSES:
        _fail(f"{report_label} has invalid status")
    if status == "completed":
        if (executed != expected_transitions or not execution_complete or not finite_complete
                or failure_category is not None or first_failure is not None):
            _fail(f"{report_label} completed status does not cover all {expected_transitions} transitions")
    elif status == "failed":
        if executed >= expected_transitions or execution_complete or finite_complete or failure_category is None:
            _fail(f"{report_label} failed status has inconsistent completion fields")
        if first_failure is not None and first_failure != executed + 1:
            _fail(f"{report_label} failed first_failure_frame is inconsistent")
    else:  # running
        if executed >= expected_transitions or execution_complete or finite_complete or failure_category is not None:
            _fail(f"{report_label} running status has inconsistent completion fields")
        if first_failure is not None:
            _fail(f"{report_label} running status must not declare first_failure_frame")
    paths = _validate_path_views(locations, name=f"{report_label}.case")
    if progress is not None:
        _validate_progress(progress, case_id=case_id, status=status,
                           expected=expected_transitions, executed=executed,
                           trajectory_path=paths.get("trajectory_output"))
    return {
        "status": status,
        "case_id": case_id,
        "binding": observed_binding,
        "expected_transitions": expected_transitions,
        "executed_transitions": executed,
        "raw_error_coverage": executed / expected_transitions,
        "complete_over_registered_denominator": status == "completed",
        "failure_category": failure_category,
        "first_failure_frame": first_failure,
        "paths": paths,
    }


def aggregate_rollout_files(
    inputs: Sequence[str | Path],
    *,
    manifest_path: str,
    manifest_sha256: str,
    checkpoint_path: str,
    checkpoint_sha256: str,
    case_bindings: Mapping[str, Mapping[str, str]],
    expected_transitions: int = EXPECTED_TRANSITIONS,
) -> dict[str, Any]:
    """Validate and aggregate JSON-only F3 diagnostic rollout reports."""
    if not inputs:
        _fail("at least one rollout report is required")
    expected_transitions = _strict_int(expected_transitions, "expected_transitions", minimum=1)
    if expected_transitions != EXPECTED_TRANSITIONS:
        _fail(f"expected_transitions is fixed at {EXPECTED_TRANSITIONS}")
    expected_binding = _expected_batch_binding(
        manifest_path=manifest_path,
        manifest_sha256=manifest_sha256,
        checkpoint_path=checkpoint_path,
        checkpoint_sha256=checkpoint_sha256,
    )
    if not isinstance(case_bindings, Mapping) or not case_bindings:
        _fail("case_bindings must contain every expected case source binding")
    normalized_cases: dict[str, dict[str, str]] = {}
    for case_id, value in case_bindings.items():
        case_id = _nonempty_string(case_id, "case_bindings.case_id")
        case = _mapping(value, f"case_bindings[{case_id!r}]")
        normalized_cases[case_id] = {
            "path": _path_string(case.get("path"), f"case_bindings[{case_id!r}].path"),
            "sha256": _sha256(case.get("sha256"), f"case_bindings[{case_id!r}].sha256"),
        }
    items: list[dict[str, Any]] = []
    seen_cases: set[str] = set()
    seen_trajectories: dict[str, str] = {}
    seen_progress: dict[str, str] = {}
    seen_reports: set[Path] = set()
    for input_path in inputs:
        report_path, payload, raw = _read_json(input_path)
        if report_path in seen_reports:
            _fail(f"duplicate report path: {report_path}")
        seen_reports.add(report_path)
        label = str(report_path)
        evaluation, binding, explicit_status, progress = _unwrap_item(payload, report_label=label)
        item = _validate_evaluation(
            evaluation, binding, expected_binding, normalized_cases,
            explicit_status=explicit_status,
            progress=progress,
            report_label=label,
            expected_transitions=expected_transitions,
        )
        if item["case_id"] in seen_cases:
            _fail(f"duplicate case_id in batch: {item['case_id']}")
        seen_cases.add(item["case_id"])
        for path_key, seen in (("trajectory_output", seen_trajectories), ("progress_output", seen_progress)):
            declared_path = item["paths"].get(path_key)
            if declared_path is None:
                continue
            if declared_path in seen:
                _fail(f"{path_key} path collision between reports {seen[declared_path]} and {label}")
            seen[declared_path] = label
        item["report"] = {
            "path": str(report_path),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
        }
        items.append(item)

    missing_cases = sorted(set(normalized_cases) - seen_cases)
    if missing_cases:
        _fail("missing report for expected case(s): " + ", ".join(missing_cases))

    items.sort(key=lambda item: item["case_id"])
    status_counts = Counter(item["status"] for item in items)
    total_expected = expected_transitions * len(items)
    total_executed = sum(item["executed_transitions"] for item in items)
    return {
        "schema": SCHEMA,
        "status": "aggregated_diagnostic",
        "source_bound": True,
        "diagnostic_only": True,
        "formal_eligible": False,
        "T1_numerical": False,
        "T2_macro": False,
        "qualification": False,
        "qualification_credit": 0,
        "credit": 0,
        "fail_closed": False,
        "binding": expected_binding,
        "denominator": {
            "expected_transitions_per_case": expected_transitions,
            "case_count": len(items),
            "total_expected_transitions": total_expected,
            "total_executed_transitions": total_executed,
            "full_denominator_case_count": status_counts["completed"],
            "raw_error_coverage": total_executed / total_expected,
            "all_cases_complete": status_counts["completed"] == len(items),
        },
        "status_counts": {status: status_counts[status] for status in sorted(STATUSES)},
        "cases": items,
        "interpretation": (
            "This receipt aggregates source-bound F3 diagnostic execution states only. "
            "Completed coverage of the 835-transition denominator does not confer formal, T1, T2, "
            "or qualification credit."
        ),
    }


def run_batch(
    inputs: Sequence[str | Path],
    *,
    manifest_path: str,
    manifest_sha256: str,
    checkpoint_path: str,
    checkpoint_sha256: str,
    case_bindings: Mapping[str, Mapping[str, str]],
    expected_transitions: int = EXPECTED_TRANSITIONS,
) -> dict[str, Any]:
    """Return a structured receipt; every validation error remains fail-closed."""
    try:
        return aggregate_rollout_files(
            inputs,
            manifest_path=manifest_path,
            manifest_sha256=manifest_sha256,
            checkpoint_path=checkpoint_path,
            checkpoint_sha256=checkpoint_sha256,
            case_bindings=case_bindings,
            expected_transitions=expected_transitions,
        )
    except Exception as error:
        return {
            "schema": SCHEMA,
            "status": "fail_closed",
            "source_bound": False,
            "diagnostic_only": True,
            "formal_eligible": False,
            "T1_numerical": False,
            "T2_macro": False,
            "qualification": False,
            "qualification_credit": 0,
            "credit": 0,
            "fail_closed": True,
            "error": str(error),
        }


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(value) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, action="append", required=True,
                        help="one JSON item; repeat for every rollout case")
    parser.add_argument("--manifest-path", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--checkpoint-path", required=True)
    parser.add_argument("--checkpoint-sha256", required=True)
    parser.add_argument(
        "--case-binding", action="append", nargs=3, metavar=("CASE_ID", "CASE_PATH", "CASE_SHA256"),
        required=True, help="repeat once per expected case")
    parser.add_argument("--expected-transitions", type=int, default=EXPECTED_TRANSITIONS)
    parser.add_argument("--output", type=Path, help="write the canonical aggregate JSON")
    args = parser.parse_args(argv)
    case_bindings: dict[str, dict[str, str]] = {}
    for case_id, case_path, case_sha256 in args.case_binding:
        if case_id in case_bindings:
            result = {
                "schema": SCHEMA,
                "status": "fail_closed",
                "source_bound": False,
                "diagnostic_only": True,
                "formal_eligible": False,
                "T1_numerical": False,
                "T2_macro": False,
                "qualification": False,
                "qualification_credit": 0,
                "credit": 0,
                "fail_closed": True,
                "error": f"duplicate CLI case binding: {case_id}",
            }
            if args.output is not None:
                _write_json(args.output, result)
            else:
                sys.stdout.write(canonical_json(result) + "\n")
            return 1
        case_bindings[case_id] = {"path": case_path, "sha256": case_sha256}
    result = run_batch(
        args.input,
        manifest_path=args.manifest_path,
        manifest_sha256=args.manifest_sha256,
        checkpoint_path=args.checkpoint_path,
        checkpoint_sha256=args.checkpoint_sha256,
        case_bindings=case_bindings,
        expected_transitions=args.expected_transitions,
    )
    text = canonical_json(result) + "\n"
    if args.output is not None:
        _write_json(args.output, result)
    else:
        sys.stdout.write(text)
    return 0 if result.get("fail_closed") is False else 1


if __name__ == "__main__":
    raise SystemExit(main())
