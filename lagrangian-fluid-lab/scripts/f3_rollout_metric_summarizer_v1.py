#!/usr/bin/env python3
"""Create a stable, read-only summary of an F3 rollout evaluation JSON.

This adapter consumes only JSON emitted by the Core rollout/evaluation path.
It never opens a trajectory, dataset, checkpoint, or solver input, and it
does not recompute a prediction.  In particular, ``future_state_inputs`` must
not be true in the source receipt.

The canonical result keeps the registered future-frame denominator even when
the source evaluation is an incomplete ``maximum_steps`` diagnostic.  Missing
tail frames are represented by JSON ``null`` in the per-step metric rows.
The serializer uses sorted keys, compact separators, UTF-8, and rejects
non-finite JSON numbers so the same receipt has stable bytes across runs.
"""
from __future__ import annotations

import argparse
from collections.abc import Mapping
import json
import math
from numbers import Real
from pathlib import Path
import sys
from typing import Any


SUMMARY_SCHEMA = "core.f3.rollout_metric_summary.v1"
_MISSING = object()
_METRICS = (
    ("position_rmse", "position_rmse_m"),
    ("position_ade", "position_ade_m"),
    ("velocity_rmse", "velocity_rmse_mps"),
    ("velocity_ade", "velocity_ade_mps"),
)


def _reject_json_constant(token: str) -> None:
    raise ValueError(f"non-finite JSON constant is not allowed: {token}")


def load_json(path: str | Path) -> Any:
    """Read one JSON value without opening any non-JSON model/data artifact."""
    if str(path) == "-":
        text = sys.stdin.read()
    else:
        text = Path(path).read_text(encoding="utf-8")
    return json.loads(text, parse_constant=_reject_json_constant)


def _canonical_value(value: Any, *, name: str = "value") -> Any:
    """Validate and copy JSON-compatible values for deterministic output."""
    if value is None or isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{name} must be finite")
        return value
    if isinstance(value, Mapping):
        result = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{name} contains a non-string object key")
            result[key] = _canonical_value(item, name=f"{name}.{key}")
        return result
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item, name=f"{name}[{index}]")
                for index, item in enumerate(value)]
    raise ValueError(f"{name} contains unsupported JSON value {type(value).__name__}")


def canonical_json(value: Any) -> str:
    """Return canonical JSON text, without a trailing newline."""
    return json.dumps(
        _canonical_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _require_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def _strict_int(value: Any, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return int(value)


def _strict_optional_int(value: Any, name: str, *, minimum: int = 0) -> int | None:
    if value is None:
        return None
    return _strict_int(value, name, minimum=minimum)


def _finite_nonnegative(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite non-negative number")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{name} must be a finite non-negative number")
    return result


def _optional_bool(value: Any, name: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a boolean")
    return value


def _first_value(locations: list[Mapping[str, Any]], keys: tuple[str, ...], default: Any = _MISSING) -> Any:
    for location in locations:
        for key in keys:
            if key in location:
                return location[key]
    if default is _MISSING:
        return _MISSING
    return default


def _reject_future_state_inputs(locations: list[Mapping[str, Any]]) -> None:
    for location in locations:
        value = location.get("future_state_inputs", False)
        if value is True:
            raise ValueError("evaluation declares future_state_inputs=true")
        if value is not False and value is not None:
            raise ValueError("future_state_inputs must be boolean when present")


def _unwrap_evaluation(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Accept a direct evaluation, a report wrapper, or one rollout receipt."""
    if "cases" in payload:
        return payload
    nested = payload.get("evaluation")
    if isinstance(nested, Mapping) and "cases" in nested:
        merged = dict(nested)
        for key, value in payload.items():
            merged.setdefault(key, value)
        return merged
    if "case_id" in payload and any(key in payload for key, _ in _METRICS):
        return {
            "schema": payload.get("schema", "core.rollout.v1"),
            "model_kind": payload.get("model_kind"),
            "checkpoint": payload.get("checkpoint"),
            "baseline": payload.get("baseline"),
            "maximum_steps": payload.get("maximum_steps"),
            "cases": {str(payload["case_id"]): payload},
        }
    raise ValueError("JSON does not contain an evaluation cases object")


def _case_entries(payload: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any]]]:
    cases = payload.get("cases")
    if isinstance(cases, Mapping):
        entries = []
        for case_id, row in cases.items():
            if not isinstance(case_id, str) or not case_id:
                raise ValueError("case IDs must be non-empty strings")
            entries.append((case_id, _require_mapping(row, f"case {case_id!r}")))
        if not entries:
            raise ValueError("evaluation cases must not be empty")
        return sorted(entries, key=lambda item: item[0])
    if isinstance(cases, list):
        entries = []
        for index, row in enumerate(cases):
            row = _require_mapping(row, f"cases[{index}]")
            case_id = row.get("case_id")
            if not isinstance(case_id, str) or not case_id:
                raise ValueError(f"cases[{index}].case_id must be a non-empty string")
            entries.append((case_id, row))
        if not entries:
            raise ValueError("evaluation cases must not be empty")
        if len({case_id for case_id, _ in entries}) != len(entries):
            raise ValueError("evaluation cases contain duplicate case IDs")
        return sorted(entries, key=lambda item: item[0])
    raise ValueError("evaluation cases must be an object or list")


def _case_expected_frames(
    payload: Mapping[str, Any],
    case_id: str,
    locations: list[Mapping[str, Any]],
    metric_lengths: list[int],
) -> int:
    value = _first_value(locations, ("expected_frames", "frames_expected"))
    if value is _MISSING:
        denominators = payload.get("expected_frames")
        if isinstance(denominators, Mapping):
            value = denominators.get(case_id, _MISSING)
        elif denominators is not None:
            value = denominators
    if value is _MISSING:
        fixed = payload.get("fixed_denominator")
        if isinstance(fixed, Mapping) and isinstance(fixed.get(case_id), Mapping):
            value = fixed[case_id].get("expected_frames", _MISSING)
    if value is _MISSING:
        if not metric_lengths:
            raise ValueError(f"case {case_id!r} has no expected frame denominator")
        value = max(metric_lengths)
    expected = _strict_int(value, f"case {case_id!r} expected_frames", minimum=1)
    if metric_lengths and any(length > expected for length in metric_lengths):
        raise ValueError(f"case {case_id!r} metric array exceeds expected_frames")
    return expected


def _metric_arrays(
    case_id: str,
    locations: list[Mapping[str, Any]],
    expected_frames: int,
) -> tuple[dict[str, list[float | None]], int]:
    raw: dict[str, list[Any]] = {}
    for source_name, _output_name in _METRICS:
        value = _first_value(locations, (source_name,))
        if value is _MISSING:
            raise ValueError(f"case {case_id!r} is missing {source_name}")
        if not isinstance(value, (list, tuple)):
            raise ValueError(f"case {case_id!r} {source_name} must be an array")
        raw[source_name] = list(value)
    lengths = {len(values) for values in raw.values()}
    if len(lengths) != 1:
        raise ValueError(f"case {case_id!r} metric arrays have different lengths")
    observed_length = lengths.pop()
    if observed_length > expected_frames:
        raise ValueError(f"case {case_id!r} metric array exceeds expected_frames")

    normalized: dict[str, list[float | None]] = {}
    for source_name, _output_name in _METRICS:
        values = []
        missing_seen = False
        for index, value in enumerate(raw[source_name], start=1):
            if value is None:
                missing_seen = True
                values.append(None)
                continue
            if missing_seen:
                raise ValueError(
                    f"case {case_id!r} {source_name} has a value after a missing frame"
                )
            values.append(_finite_nonnegative(
                value, f"case {case_id!r} {source_name}[{index}]"))
        values.extend([None] * (expected_frames - observed_length))
        normalized[source_name] = values

    finite_prefix = expected_frames
    for index in range(expected_frames):
        if any(normalized[name][index] is None for name, _ in _METRICS):
            finite_prefix = index
            break
    return normalized, finite_prefix


def _physics_summary(
    case_id: str,
    locations: list[Mapping[str, Any]],
    expected_frames: int,
) -> Any:
    for location in locations:
        physics = location.get("physics")
        if isinstance(physics, Mapping):
            summary = physics.get("summary")
            if summary is not None:
                summary = _require_mapping(summary, f"case {case_id!r} physics.summary")
                summary = _canonical_value(summary, name=f"case {case_id!r} physics.summary")
                declared_expected = summary.get("expected_frames")
                if declared_expected is not None and _strict_int(
                        declared_expected, f"case {case_id!r} physics.expected_frames", minimum=1
                ) != expected_frames:
                    raise ValueError(f"case {case_id!r} physics denominator mismatch")
                completed = summary.get("completed_frames")
                if completed is not None:
                    completed = _strict_int(
                        completed, f"case {case_id!r} physics.completed_frames")
                    if completed > expected_frames:
                        raise ValueError(f"case {case_id!r} physics coverage exceeds denominator")
                return summary
        summary = location.get("physics_summary")
        if summary is not None:
            return _canonical_value(
                _require_mapping(summary, f"case {case_id!r} physics_summary"),
                name=f"case {case_id!r} physics_summary",
            )
    return None


def _case_summary(
    payload: Mapping[str, Any],
    case_id: str,
    row: Mapping[str, Any],
) -> dict[str, Any]:
    nested = row.get("rollout")
    rollout = _require_mapping(nested, f"case {case_id!r}.rollout") if nested is not None else row
    score = row.get("score")
    score = score if isinstance(score, Mapping) else {}
    locations = [rollout, row, score]
    _reject_future_state_inputs([payload, row, rollout])

    metric_lengths = []
    for source_name, _output_name in _METRICS:
        value = _first_value(locations, (source_name,))
        if value is not _MISSING:
            if not isinstance(value, (list, tuple)):
                raise ValueError(f"case {case_id!r} {source_name} must be an array")
            metric_lengths.append(len(value))
    expected_frames = _case_expected_frames(payload, case_id, locations, metric_lengths)
    arrays, finite_prefix = _metric_arrays(case_id, locations, expected_frames)

    frames_executed_value = _first_value(
        locations, ("frames_executed", "frames_predicted", "finite_prefix_frames"))
    frames_executed = finite_prefix if frames_executed_value is _MISSING else _strict_int(
        frames_executed_value, f"case {case_id!r} frames_executed")
    if frames_executed != finite_prefix:
        raise ValueError(f"case {case_id!r} frames_executed disagrees with metric prefix")
    if frames_executed > expected_frames:
        raise ValueError(f"case {case_id!r} frames_executed exceeds denominator")

    maximum_steps_value = _first_value(
        [rollout, row, payload], ("maximum_steps", "requested_maximum_steps", "max_steps"),
        default=None,
    )
    maximum_steps = _strict_optional_int(
        maximum_steps_value, f"case {case_id!r} maximum_steps", minimum=1)
    requested_frames = expected_frames if maximum_steps is None else min(maximum_steps, expected_frames)

    failure_value = _first_value(
        [rollout, row, score], ("failure_category", "scientific_failure_category"),
        default=None,
    )
    if failure_value is not None and (not isinstance(failure_value, str) or not failure_value):
        raise ValueError(f"case {case_id!r} failure_category must be a non-empty string or null")
    failure_category = failure_value

    first_failure_value = _first_value(
        [rollout, row, score], ("first_failure_frame", "scientific_first_failure_frame"),
        default=None,
    )
    first_failure_frame = _strict_optional_int(
        first_failure_value, f"case {case_id!r} first_failure_frame", minimum=1)
    if first_failure_frame is None and failure_category is not None and finite_prefix < expected_frames:
        first_failure_frame = finite_prefix + 1
    if first_failure_frame is not None and first_failure_frame > expected_frames:
        raise ValueError(f"case {case_id!r} first_failure_frame exceeds denominator")

    requested_execution_value = _first_value(
        [rollout, row], ("requested_window_execution_complete",), default=_MISSING)
    if requested_execution_value is _MISSING:
        execution_value = _first_value([rollout, row], ("execution_complete",), default=_MISSING)
        if maximum_steps is None and execution_value is not _MISSING:
            requested_execution_value = execution_value
        else:
            requested_execution_value = (
                frames_executed == requested_frames
                and failure_category in (None, "maximum_steps_limit")
            )
    requested_execution_complete = _optional_bool(
        requested_execution_value, f"case {case_id!r} requested_window_execution_complete")
    if requested_execution_complete is None:
        requested_execution_complete = False

    requested_finite_value = _first_value(
        [rollout, row], ("requested_window_finite_rollout_complete",), default=_MISSING)
    if requested_finite_value is _MISSING:
        finite_value = _first_value([rollout, row], ("finite_rollout_complete",), default=_MISSING)
        if maximum_steps is None and finite_value is not _MISSING:
            requested_finite_value = finite_value
        else:
            requested_finite_value = requested_execution_complete and frames_executed == requested_frames
    requested_finite_complete = _optional_bool(
        requested_finite_value, f"case {case_id!r} requested_window_finite_rollout_complete")
    if requested_finite_complete is None:
        requested_finite_complete = False

    registered_complete_value = _first_value(
        [rollout, row], ("complete_over_registered_denominator",), default=_MISSING)
    if registered_complete_value is _MISSING:
        registered_complete = (
            frames_executed == expected_frames and failure_category is None
        )
    else:
        registered_complete = _optional_bool(
            registered_complete_value,
            f"case {case_id!r} complete_over_registered_denominator",
        )
        if registered_complete is None:
            registered_complete = False

    explicit_coverage = _first_value(
        [score, rollout, row], ("raw_error_coverage", "coverage"), default=_MISSING)
    computed_coverage = frames_executed / expected_frames
    if explicit_coverage is not _MISSING and explicit_coverage is not None:
        reported_coverage = _finite_nonnegative(
            explicit_coverage, f"case {case_id!r} raw_error_coverage")
        if reported_coverage > 1.0 or not math.isclose(
                reported_coverage, computed_coverage, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError(f"case {case_id!r} raw_error_coverage disagrees with metric prefix")
    raw_error_coverage = computed_coverage

    selection_score = _first_value(
        [score, rollout, row], ("selection_score",), default=None)
    if selection_score is not None:
        selection_score = _finite_nonnegative(
            selection_score, f"case {case_id!r} selection_score")

    per_step = []
    for index in range(expected_frames):
        per_step.append({
            "step": index + 1,
            "position_rmse_m": arrays["position_rmse"][index],
            "position_ade_m": arrays["position_ade"][index],
            "velocity_rmse_mps": arrays["velocity_rmse"][index],
            "velocity_ade_mps": arrays["velocity_ade"][index],
        })

    result: dict[str, Any] = {
        "case_id": case_id,
        "per_step": per_step,
        "coverage": {
            "expected_frames": expected_frames,
            "frames_executed": frames_executed,
            "finite_prefix_frames": finite_prefix,
            "raw_error_coverage": raw_error_coverage,
            "requested_maximum_steps": maximum_steps,
            "requested_window_frames": requested_frames,
            "requested_window_execution_complete": requested_execution_complete,
            "requested_window_finite_rollout_complete": requested_finite_complete,
            "complete_over_registered_denominator": bool(registered_complete),
        },
        "failure_category": failure_category,
        "first_failure_frame": first_failure_frame,
        "physics_summary": _physics_summary(case_id, locations, expected_frames),
        "selection_score": selection_score,
        "autonomous": True,
        "future_state_inputs": False,
    }
    return _canonical_value(result, name=f"case {case_id!r}")


def summarize_evaluation(payload: Mapping[str, Any], *, family: str = "F3") -> dict[str, Any]:
    """Summarize an evaluation payload without reading future-state data."""
    payload = _require_mapping(payload, "evaluation")
    if not isinstance(family, str) or not family:
        raise ValueError("family must be a non-empty string")
    source_family = payload.get("family")
    if source_family is not None and source_family != family:
        raise ValueError(f"evaluation family {source_family!r} does not match {family!r}")
    _reject_future_state_inputs([payload])
    evaluation = _unwrap_evaluation(payload)
    _reject_future_state_inputs([evaluation])
    evaluation_family = evaluation.get("family")
    if evaluation_family is not None and evaluation_family != family:
        raise ValueError(
            f"evaluation family {evaluation_family!r} does not match {family!r}"
        )
    entries = _case_entries(evaluation)
    cases = [_case_summary(evaluation, case_id, row) for case_id, row in entries]

    source = {
        "evaluation_schema": evaluation.get("schema", "unknown"),
        "model_kind": evaluation.get("model_kind"),
        "checkpoint": evaluation.get("checkpoint"),
        "baseline": evaluation.get("baseline"),
    }
    result = {
        "schema": SUMMARY_SCHEMA,
        "family": family,
        "source": _canonical_value(source, name="source"),
        "case_count": len(cases),
        "cases": cases,
    }
    return _canonical_value(result, name="summary")


def summarize_evaluation_file(path: str | Path, *, family: str = "F3") -> dict[str, Any]:
    """Load one JSON receipt and return its canonical summary."""
    return summarize_evaluation(load_json(path), family=family)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="evaluation JSON, or '-' for stdin")
    parser.add_argument("--output", type=Path, help="canonical JSON output; default is stdout")
    parser.add_argument("--family", default="F3", help="expected source family (default: F3)")
    args = parser.parse_args(argv)
    summary = summarize_evaluation_file(args.input, family=args.family)
    text = canonical_json(summary) + "\n"
    if args.output is None or str(args.output) == "-":
        sys.stdout.write(text)
    else:
        args.output.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
