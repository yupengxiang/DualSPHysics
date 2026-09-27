#!/usr/bin/env python3
"""Read-only validator for an F3 rollout receipt and its trajectory HDF5.

The validator is intentionally a sidecar.  It does not import the learning
runner, open a dataset manifest, start a worker, or write a receipt.  The
only files it opens are the supplied evaluation JSON (text read) and the
supplied trajectory HDF5 (``h5py.File(..., "r")``).

The checked contract mirrors the public ``core.evaluation.v1`` rollout shape:

* a complete F3 rollout has 835 transitions and 836 saved states;
* a bounded ``maximum_steps`` rollout keeps the registered 835-transition
  denominator in JSON but stores only ``maximum_steps + 1`` HDF5 states;
* JSON completion/failure flags and metric prefixes agree with one another;
* HDF5 identity, shape, time, validity, finite-state, and tail semantics are
  internally consistent; and
* ``future_state_inputs`` is explicitly false in both artifacts.

``validate_receipt`` raises :class:`ValidationError` on every mismatch.
``run_validation`` converts the same error into a structured fail-closed
result for command-line use.  Neither entry point mutates its inputs.
"""
from __future__ import annotations

import argparse
import json
from numbers import Integral, Real
from pathlib import Path
import sys
from typing import Any, Mapping

if __name__ == "__main__":
    # A read-only command should not leave __pycache__ files beside the new
    # sidecar when it is invoked directly from a repository checkout.
    sys.dont_write_bytecode = True

import h5py
import numpy as np


SCHEMA = "core.f3.full_rollout_receipt_hdf5_validation.v1"
EVALUATION_SCHEMA = "core.evaluation.v1"
DEFAULT_EXPECTED_TRANSITIONS = 835
REQUIRED_DATASETS = frozenset(
    {"time", "position", "velocity", "particle_id", "particle_zone", "mass", "valid"}
)


class ValidationError(ValueError):
    """A receipt/HDF5 mismatch that must not be interpreted as a pass."""


def _fail(message: str) -> None:
    raise ValidationError(f"fail-closed: {message}")


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{name} must be an object")
    return value


def _strict_bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        _fail(f"{name} must be a boolean")
    return value


def _strict_int(value: Any, name: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        _fail(f"{name} must be an integer")
    result = int(value)
    if minimum is not None and result < minimum:
        _fail(f"{name} must be >= {minimum}")
    return result


def _strict_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        _fail(f"{name} must be numeric")
    result = float(value)
    if not np.isfinite(result):
        _fail(f"{name} must be finite")
    return result


def _strict_false(value: Any, name: str) -> None:
    """Accept HDF5's scalar bool/integer representation, never strings."""
    if isinstance(value, (bool, np.bool_)):
        if bool(value):
            _fail(f"{name} must be false")
        return
    if isinstance(value, Integral) and not isinstance(value, bool):
        if int(value) != 0:
            _fail(f"{name} must be false")
        return
    _fail(f"{name} must be an explicit false boolean")


def _strict_true(value: Any, name: str) -> None:
    if isinstance(value, (bool, np.bool_)):
        if not bool(value):
            _fail(f"{name} must be true")
        return
    if isinstance(value, Integral) and not isinstance(value, bool):
        if int(value) != 1:
            _fail(f"{name} must be true")
        return
    _fail(f"{name} must be an explicit true boolean")


def _finite_metric_prefix(values: Any, *, name: str, expected: int, executed: int) -> None:
    if not isinstance(values, list) or len(values) != expected:
        _fail(f"{name} must have the fixed {expected}-frame denominator")
    for index, value in enumerate(values):
        if index < executed:
            _strict_number(value, f"{name}[{index}]")
        elif value is not None:
            _fail(f"{name}[{index}] must be null after the executed prefix")


def _resolve_path(value: Any, *, base: Path, name: str) -> Path:
    if not isinstance(value, (str, Path)) or not value:
        _fail(f"{name} must be a non-empty path")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    path = path.resolve()
    if not path.is_file():
        _fail(f"{name} does not exist: {path}")
    return path


def _load_evaluation(path: Path) -> dict[str, Any]:
    if not path.is_file():
        _fail(f"evaluation JSON does not exist: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        _fail(f"evaluation JSON cannot be read: {error}")
    return dict(_mapping(value, "evaluation JSON"))


def _select_case(evaluation: Mapping[str, Any], requested_case_id: str | None) -> tuple[str, Mapping[str, Any]]:
    cases = _mapping(evaluation.get("cases"), "evaluation.cases")
    if not cases:
        _fail("evaluation.cases must not be empty")
    if requested_case_id is None:
        if len(cases) != 1:
            _fail("case_id is required when evaluation contains multiple cases")
        case_id = next(iter(cases))
    else:
        if not isinstance(requested_case_id, str) or not requested_case_id:
            _fail("case_id must be a non-empty string")
        case_id = requested_case_id
    if case_id not in cases:
        _fail(f"case_id is not present in evaluation.cases: {case_id}")
    return case_id, _mapping(cases[case_id], f"evaluation.cases[{case_id!r}]")


def _validate_case_lists(evaluation: Mapping[str, Any], case_id: str) -> None:
    for name in ("registered_case_ids", "selected_case_ids"):
        values = evaluation.get(name)
        if not isinstance(values, list) or not values or any(
                not isinstance(item, str) or not item for item in values):
            _fail(f"evaluation.{name} must be a non-empty string list")
        if len(set(values)) != len(values):
            _fail(f"evaluation.{name} contains duplicate case IDs")
        if case_id not in values:
            _fail(f"evaluation.{name} does not contain selected case {case_id!r}")


def _validate_score(row: Mapping[str, Any], *, expected: int, executed: int,
                    failure_category: str | None, execution_complete: bool) -> None:
    score = _mapping(row.get("score"), "case.score")
    score_expected = _strict_int(score.get("expected_frames"), "case.score.expected_frames",
                                 minimum=1)
    if score_expected != expected:
        _fail("case.score.expected_frames disagrees with the fixed denominator")
    finite_prefix = _strict_int(score.get("finite_prefix_frames"),
                                "case.score.finite_prefix_frames", minimum=0)
    if finite_prefix != executed:
        _fail("case.score.finite_prefix_frames disagrees with the executed prefix")
    if _strict_bool(score.get("executed"), "case.score.executed") is not _strict_bool(
            row.get("executed"), "case.executed"):
        _fail("case.score.executed disagrees with case.executed")
    if _strict_bool(score.get("complete"), "case.score.complete") is not execution_complete:
        _fail("case.score.complete disagrees with rollout completion")
    score_failure = score.get("failure_category")
    if score_failure != failure_category:
        _fail("case.score.failure_category disagrees with case.failure_category")
    if "raw_error_coverage" in score:
        coverage = _strict_number(score["raw_error_coverage"], "case.score.raw_error_coverage")
        expected_coverage = executed / expected
        if not np.isclose(coverage, expected_coverage, rtol=0.0, atol=1.0e-12):
            _fail("case.score.raw_error_coverage disagrees with the executed prefix")


def _validate_evaluation(path: Path, requested_case_id: str | None,
                         expected_transitions: int) -> tuple[dict[str, Any], str,
                                                              Mapping[str, Any], Path]:
    evaluation = _load_evaluation(path)
    if evaluation.get("schema") != EVALUATION_SCHEMA:
        _fail("unsupported evaluation schema")
    if "autonomous" in evaluation:
        if _strict_bool(evaluation["autonomous"], "evaluation.autonomous") is not True:
            _fail("evaluation.autonomous must be true")
    else:
        _fail("evaluation.autonomous is missing")
    _strict_false(evaluation.get("future_state_inputs"), "evaluation.future_state_inputs")

    mode = evaluation.get("evaluation_mode")
    if mode not in {"diagnostic", "formal"}:
        _fail("evaluation.evaluation_mode is invalid")
    if "diagnostic" in evaluation and _strict_bool(
            evaluation["diagnostic"], "evaluation.diagnostic") is not (mode == "diagnostic"):
        _fail("evaluation.diagnostic disagrees with evaluation_mode")
    if "formal_eligible" in evaluation and _strict_bool(
            evaluation["formal_eligible"], "evaluation.formal_eligible") is not (mode == "formal"):
        _fail("evaluation.formal_eligible disagrees with evaluation_mode")

    maximum_steps = evaluation.get("maximum_steps")
    if maximum_steps is not None:
        maximum_steps = _strict_int(maximum_steps, "evaluation.maximum_steps", minimum=1)
    case_id, row = _select_case(evaluation, requested_case_id)
    _validate_case_lists(evaluation, case_id)

    expected_map = _mapping(evaluation.get("expected_frames"), "evaluation.expected_frames")
    expected = _strict_int(expected_map.get(case_id),
                           f"evaluation.expected_frames[{case_id!r}]", minimum=1)
    if expected != expected_transitions:
        _fail(f"expected transition count must be {expected_transitions}, got {expected}")

    row_case_id = row.get("case_id")
    if row_case_id != case_id:
        _fail("case.case_id disagrees with the selected case")
    for name in ("frames_expected", "expected_frames"):
        value = _strict_int(row.get(name), f"case.{name}", minimum=1)
        if value != expected:
            _fail(f"case.{name} disagrees with the fixed denominator")
    executed = _strict_int(row.get("frames_executed"), "case.frames_executed", minimum=0)
    predicted = _strict_int(row.get("frames_predicted"), "case.frames_predicted", minimum=0)
    if executed > expected or predicted != executed:
        _fail("case frame counts are inconsistent")

    executed_flag = _strict_bool(row.get("executed"), "case.executed")
    if not executed_flag and executed != 0:
        _fail("case.executed=false cannot have executed frames")
    failure_category = row.get("failure_category")
    if failure_category is not None and (
            not isinstance(failure_category, str) or not failure_category):
        _fail("case.failure_category must be null or a non-empty string")
    first_failure = row.get("first_failure_frame")
    if failure_category is None:
        if first_failure is not None:
            _fail("case.first_failure_frame must be null for a complete attempt")
    else:
        first_failure = _strict_int(first_failure, "case.first_failure_frame", minimum=1)
        if first_failure != executed + 1:
            _fail("case.first_failure_frame must follow the executed prefix")

    execution_complete = bool(expected > 0 and executed == expected and failure_category is None)
    if executed < expected and failure_category is None:
        _fail("an incomplete rollout must declare failure_category")
    if executed == expected and failure_category is not None:
        _fail("a full executed prefix cannot declare an execution failure")
    if _strict_bool(row.get("execution_complete"), "case.execution_complete") is not execution_complete:
        _fail("case.execution_complete disagrees with frame/failure semantics")
    for name in ("position_rmse", "velocity_rmse", "position_ade", "velocity_ade"):
        _finite_metric_prefix(row.get(name), name=f"case.{name}", expected=expected,
                              executed=executed)
    finite_complete = bool(execution_complete)
    if _strict_bool(row.get("finite_rollout_complete"), "case.finite_rollout_complete") is not finite_complete:
        _fail("case.finite_rollout_complete disagrees with metric completion")

    scientific_status = row.get("scientific_status")
    if scientific_status != "not_assessed":
        _fail("case.scientific_status must remain not_assessed")
    if row.get("scientific_failure_category") is not None:
        _fail("case.scientific_failure_category must be null")
    if row.get("scientific_first_failure_frame") is not None:
        _fail("case.scientific_first_failure_frame must be null")
    _strict_false(row.get("future_state_inputs"), "case.future_state_inputs")
    _validate_score(row, expected=expected, executed=executed,
                    failure_category=failure_category,
                    execution_complete=execution_complete)

    if failure_category == "maximum_steps_limit":
        if maximum_steps is None or maximum_steps >= expected or maximum_steps != executed:
            _fail("maximum_steps_limit requires a shorter matching maximum_steps")
        if mode != "diagnostic":
            _fail("maximum_steps_limit is diagnostic-only")
    elif maximum_steps is not None and maximum_steps < expected and executed == maximum_steps:
        _fail("a bounded rollout must declare failure_category=maximum_steps_limit")

    trajectory_value = row.get("trajectory_output")
    trajectory_path = _resolve_path(trajectory_value, base=path.parent,
                                    name="case.trajectory_output")
    context = {
        "maximum_steps": maximum_steps,
        "expected_transitions": expected,
        "frames_executed": executed,
        "failure_category": failure_category,
        "execution_complete": execution_complete,
        "executed": executed_flag,
    }
    return context, case_id, row, trajectory_path


def _read_identity(dataset: h5py.Dataset, *, name: str, particles: int) -> np.ndarray:
    if dataset.shape != (particles,) or dataset.dtype.kind not in "iu":
        _fail(f"HDF5 {name} must be a one-dimensional integer axis")
    values = np.asarray(dataset[...])
    if values.dtype.kind == "u" and values.size and int(values.max()) > np.iinfo(np.int64).max:
        _fail(f"HDF5 {name} exceeds int64 identity range")
    return values.astype(np.int64, copy=False)


def _validate_hdf5(path: Path, *, context: Mapping[str, Any], case_id: str) -> dict[str, Any]:
    expected = int(context["expected_transitions"])
    executed = int(context["frames_executed"])
    failure_category = context["failure_category"]
    maximum_steps = context["maximum_steps"]
    if failure_category == "maximum_steps_limit":
        expected_hdf5_transitions = executed
    else:
        expected_hdf5_transitions = expected

    # Explicitly read-only: this is the only HDF5 open in the sidecar.
    with h5py.File(path, "r") as handle:
        missing = REQUIRED_DATASETS - set(handle)
        if missing:
            _fail(f"HDF5 is missing datasets: {sorted(missing)}")
        if "future_state_inputs" not in handle.attrs:
            _fail("HDF5 future_state_inputs attribute is missing")
        _strict_false(handle.attrs["future_state_inputs"], "HDF5 future_state_inputs")
        if "autonomous_prediction" not in handle.attrs:
            _fail("HDF5 autonomous_prediction attribute is missing")
        _strict_true(handle.attrs["autonomous_prediction"], "HDF5 autonomous_prediction")
        if "case_id" in handle.attrs and handle.attrs["case_id"] != case_id:
            _fail("HDF5 case_id disagrees with the evaluation case")

        time_dataset = handle["time"]
        if len(time_dataset.shape) != 1:
            _fail("HDF5 time must be one-dimensional")
        frame_count = int(time_dataset.shape[0])
        if frame_count != expected_hdf5_transitions + 1:
            _fail(
                "HDF5 frame count disagrees with completion semantics: "
                f"expected {expected_hdf5_transitions + 1}, got {frame_count}")
        times = np.asarray(time_dataset[...], dtype=np.float64)
        if (times.shape != (frame_count,) or not np.isfinite(times).all()
                or np.any(np.diff(times) <= 0)):
            _fail("HDF5 time must be finite and strictly increasing")

        position = handle["position"]
        velocity = handle["velocity"]
        if (len(position.shape) != 3 or position.shape[0] != frame_count
                or position.shape[2] != 3):
            _fail("HDF5 position must have shape [frames, particles, 3]")
        if velocity.shape != position.shape:
            _fail("HDF5 velocity shape must equal position shape")
        particles = int(position.shape[1])
        if particles < 1:
            _fail("HDF5 trajectory must contain at least one particle")

        particle_id = _read_identity(handle["particle_id"], name="particle_id",
                                     particles=particles)
        particle_zone = _read_identity(handle["particle_zone"], name="particle_zone",
                                       particles=particles)
        identity = np.column_stack((particle_zone, particle_id))
        if len(np.unique(identity, axis=0)) != particles:
            _fail("HDF5 composite particle identities are not unique")

        valid_dataset = handle["valid"]
        if valid_dataset.shape != (frame_count, particles):
            _fail("HDF5 valid shape must be [frames, particles]")
        if valid_dataset.dtype.kind not in "biu":
            _fail("HDF5 valid must use an explicit binary dtype")
        valid_raw = np.asarray(valid_dataset[...])
        if not np.isin(valid_raw, (0, 1)).all():
            _fail("HDF5 valid must contain only 0/1 values")
        valid = valid_raw.astype(bool, copy=False)
        initial_valid = np.array(valid[0], dtype=bool, copy=True)
        if not initial_valid.any():
            _fail("HDF5 initial valid mask must contain an active particle")
        completed_frames = executed + 1
        if not np.all(valid[:completed_frames] == initial_valid[None, :]):
            _fail("HDF5 valid lifecycle changed inside the executed prefix")
        if completed_frames < frame_count and np.any(valid[completed_frames:]):
            _fail("HDF5 unexecuted frames must have valid=false")

        for name, dataset in (("position", position), ("velocity", velocity)):
            completed_values = np.asarray(dataset[:completed_frames])
            active_values = completed_values[valid[:completed_frames]]
            if not np.isfinite(active_values).all():
                _fail(f"HDF5 active {name} values are not finite in the executed prefix")
            if completed_frames < frame_count:
                tail = np.asarray(dataset[completed_frames:])
                if not np.isnan(tail).all():
                    _fail(f"HDF5 unexecuted {name} values must be NaN")

        mass = handle["mass"]
        if mass.shape not in ((particles,), (frame_count, particles)):
            _fail("HDF5 mass must have shape [particles] or [frames, particles]")
        mass_values = np.asarray(mass[...], dtype=np.float64)
        initial_mass = mass_values if mass.ndim == 1 else mass_values[0]
        active_initial_mass = initial_mass[initial_valid]
        if (not np.isfinite(active_initial_mass).all()
                or np.any(active_initial_mass <= 0)):
            _fail("HDF5 active mass must be finite and positive")
        if mass.ndim == 2:
            active_completed_mass = mass_values[:completed_frames, initial_valid]
            if not np.isfinite(active_completed_mass).all() or np.any(active_completed_mass <= 0):
                _fail("HDF5 active temporal mass must be finite and positive")
            if not np.array_equal(active_completed_mass,
                                  np.broadcast_to(active_initial_mass,
                                                  active_completed_mass.shape)):
                _fail("HDF5 active mass changed inside the executed prefix")

    return {
        "frame_count": frame_count,
        "transition_count": frame_count - 1,
        "particle_count": particles,
        "time_start": float(times[0]),
        "time_end": float(times[-1]),
        "executed_frame_count": completed_frames,
        "tail_frame_count": frame_count - completed_frames,
    }


def validate_receipt(evaluation_json: str | Path, trajectory_hdf5: str | Path | None = None,
                     *, case_id: str | None = None,
                     expected_transitions: int = DEFAULT_EXPECTED_TRANSITIONS) -> dict[str, Any]:
    """Validate one F3 evaluation case and trajectory without writing files."""
    expected_transitions = _strict_int(expected_transitions, "expected_transitions", minimum=1)
    evaluation_path = Path(evaluation_json).expanduser().resolve()
    context, selected_case_id, row, embedded_trajectory = _validate_evaluation(
        evaluation_path, case_id, expected_transitions)
    trajectory_path = embedded_trajectory if trajectory_hdf5 is None else _resolve_path(
        trajectory_hdf5, base=evaluation_path.parent, name="trajectory_hdf5")
    hdf5 = _validate_hdf5(trajectory_path, context=context, case_id=selected_case_id)
    complete = bool(context["execution_complete"])
    return {
        "schema": SCHEMA,
        "passed": True,
        "fail_closed": False,
        "diagnostic_only": True,
        "synthetic_only": False,
        "production_artifacts_touched": False,
        "qualification_credit": 0,
        "case_id": selected_case_id,
        "evaluation_json": str(evaluation_path),
        "trajectory_hdf5": str(trajectory_path),
        "expected_transitions": expected_transitions,
        "frames_executed": int(context["frames_executed"]),
        "complete": complete,
        "incomplete": not complete,
        "failure_category": context["failure_category"],
        "checks": {
            "case_binding": True,
            "shape": True,
            "time": True,
            "valid": True,
            "future_state_inputs": True,
            "completion_semantics": True,
            "trajectory_frames": hdf5["frame_count"],
            "trajectory_transitions": hdf5["transition_count"],
            "particle_count": hdf5["particle_count"],
            "time_start": hdf5["time_start"],
            "time_end": hdf5["time_end"],
            "executed_frame_count": hdf5["executed_frame_count"],
            "tail_frame_count": hdf5["tail_frame_count"],
        },
        "row_fields_checked": sorted(row.keys()),
    }


def run_validation(evaluation_json: str | Path, trajectory_hdf5: str | Path | None = None,
                   *, case_id: str | None = None,
                   expected_transitions: int = DEFAULT_EXPECTED_TRANSITIONS) -> dict[str, Any]:
    """Return a JSON-safe pass/fail receipt; failures always remain fail-closed."""
    try:
        return validate_receipt(
            evaluation_json, trajectory_hdf5, case_id=case_id,
            expected_transitions=expected_transitions)
    except Exception as error:
        return {
            "schema": SCHEMA,
            "passed": False,
            "fail_closed": True,
            "diagnostic_only": True,
            "synthetic_only": False,
            "production_artifacts_touched": False,
            "qualification_credit": 0,
            "failure_reason": str(error),
        }


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evaluation_json", type=Path)
    parser.add_argument("--trajectory", type=Path, default=None,
                        help="optional read-only trajectory HDF5 override")
    parser.add_argument("--case-id", default=None)
    parser.add_argument("--expected-transitions", type=int,
                        default=DEFAULT_EXPECTED_TRANSITIONS)
    args = parser.parse_args(argv)
    result = run_validation(
        args.evaluation_json, args.trajectory, case_id=args.case_id,
        expected_transitions=args.expected_transitions)
    print(_canonical_json(result))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
