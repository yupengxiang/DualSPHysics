"""Streaming cross-host comparison of complete public-State trajectories.

The comparison is deliberately a reproduction check rather than a scientific
qualification gate. It still validates the public State and score contracts
before applying the registered numerical tolerances: a pair of malformed
reports must not pass merely because both hosts produced the same malformed
values.
"""
from __future__ import annotations

import argparse
import json
import math
from numbers import Integral, Real
from pathlib import Path
import sys

import h5py
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.core_runtime import atomic_json, digest
from scripts.core_evaluation import score_case


PROTOCOL = {
    "schema": "core.cross_host_comparison.v1",
    "relative_tolerance": 1e-4,
    "position_absolute_tolerance_m": 1e-5,
    "velocity_absolute_tolerance_mps": 1e-4,
    "identity_time_mass_valid": "exact",
    "physics_counts_and_failure_categories": "exact",
    "physics_float_relative_tolerance": 1e-4,
    "physics_float_absolute_tolerance": 1e-6,
    "score_absolute_tolerance": 1e-4,
    "interpretation": "numerical agreement, not bitwise identity or scientific qualification",
}


# These are the fields emitted by core_learning.rollout_case. Requiring the
# complete summary prevents two reports containing the same empty/custom
# dictionary from being treated as a physics-statistics match.
PHYSICS_SUMMARY_FIELDS = (
    "expected_frames",
    "completed_frames",
    "mass_error_abs_max_kg",
    "kinetic_energy_error_abs_max_j",
    "validity_mismatch_frames",
    "changed_particle_mass_frames",
    "wall_chord_statuses",
    "wall_chord_particle_count",
    "wall_chord_mass_kg",
)
PHYSICS_COUNT_FIELDS = (
    "expected_frames",
    "completed_frames",
    "validity_mismatch_frames",
    "changed_particle_mass_frames",
    "wall_chord_particle_count",
)
PHYSICS_FLOAT_FIELDS = (
    "mass_error_abs_max_kg",
    "kinetic_energy_error_abs_max_j",
    "wall_chord_mass_kg",
)


def _is_integral(value):
    return isinstance(value, (Integral, np.integer)) and not isinstance(value, (bool, np.bool_))


def _is_real(value):
    return isinstance(value, (Real, np.integer, np.floating)) and not isinstance(
        value, (bool, np.bool_)
    )


def _validate_expected_frames(value, *, minimum):
    if not _is_integral(value) or int(value) < minimum:
        raise ValueError(f"expected_frames must be an integer >= {minimum}")
    return int(value)


def _finite_positive(value):
    return _is_real(value) and math.isfinite(float(value)) and float(value) > 0


def _identity_keys(zone, particle_id):
    # Keep Python integers here instead of casting to int64: a malformed
    # uint64 identity must not wrap and accidentally collide with another ID.
    return {(int(z), int(i)) for z, i in zip(zone.tolist(), particle_id.tolist())}


def _trajectory_layout(handle, label, expected_frames):
    """Validate HDF5 layout and static public-State axes.

    Return the particle count and structural errors. Values on the large
    position/velocity datasets are checked one frame at a time by compare().
    """
    errors = []
    required = ("time", "particle_id", "particle_zone", "mass", "valid", "position", "velocity")
    for key in required:
        if key not in handle:
            errors.append(f"missing_field:{label}:{key}")
    if errors:
        return None, errors

    shapes = {key: tuple(handle[key].shape) for key in required}
    time_shape = shapes["time"]
    ids_shape = shapes["particle_id"]
    zone_shape = shapes["particle_zone"]
    mass_shape = shapes["mass"]
    if time_shape != (expected_frames,):
        errors.append("registered_frame_count_mismatch")
    if len(ids_shape) != 1 or len(zone_shape) != 1 or len(mass_shape) != 1:
        errors.append(f"invalid_identity_axis:{label}")
        return None, errors
    count = ids_shape[0]
    if count < 1 or zone_shape != (count,) or mass_shape != (count,):
        errors.append(f"invalid_identity_axis:{label}")
    if shapes["valid"] != (expected_frames, count):
        errors.append(f"invalid_valid_shape:{label}")
    if shapes["position"] != (expected_frames, count, 3):
        errors.append(f"invalid_position_shape:{label}")
    if shapes["velocity"] != (expected_frames, count, 3):
        errors.append(f"invalid_velocity_shape:{label}")

    if handle["time"].dtype.kind not in "fiu":
        errors.append(f"invalid_time_dtype:{label}")
    for key in ("particle_id", "particle_zone"):
        if handle[key].dtype.kind not in "iu":
            errors.append(f"invalid_identity_dtype:{label}:{key}")
    if handle["mass"].dtype.kind not in "fiu":
        errors.append(f"invalid_mass_dtype:{label}")
    if handle["valid"].dtype.kind not in "biu":
        errors.append(f"invalid_valid_dtype:{label}")
    for key in ("position", "velocity"):
        if handle[key].dtype.kind not in "fiu":
            errors.append(f"invalid_state_dtype:{label}:{key}")

    # Do not use equal_nan for any static field. The same NaN on both hosts is
    # not a valid identity/time/mass contract.
    if not errors:
        time = np.asarray(handle["time"][:])
        particle_id = np.asarray(handle["particle_id"][:])
        particle_zone = np.asarray(handle["particle_zone"][:])
        mass = np.asarray(handle["mass"][:])
        if not np.isfinite(time).all() or np.any(np.diff(time) <= 0):
            errors.append(f"invalid_time_axis:{label}")
        if len(_identity_keys(particle_zone, particle_id)) != count:
            errors.append(f"duplicate_identity:{label}")
        if not np.isfinite(mass).all() or np.any(mass <= 0):
            errors.append(f"invalid_mass_axis:{label}")
    return count, errors


def _validate_valid_frame(raw, label, frame):
    values = np.asarray(raw)
    if values.dtype.kind not in "biu" or not np.isin(values, [0, 1]).all():
        return None, [f"invalid_valid_mask:{label}:{frame}"]
    mask = values.astype(bool, copy=False)
    if not mask.any():
        # State.validate() requires at least one active particle. A failed
        # rollout's unexecuted tail is represented by this mask and must be
        # rejected by the trajectory gate; its fixed denominator is retained
        # separately by compare_scores().
        return mask, [f"no_active_particles:{label}:{frame}"]
    return mask, []


def _read_score_array(row, key, expected_frames, errors):
    value = row.get(key)
    if not isinstance(value, list) or len(value) != expected_frames:
        errors.append(f"invalid_score_denominator:{key}")
        return np.full(expected_frames, np.nan, dtype=float)
    converted = []
    for index, item in enumerate(value):
        if item is None:
            converted.append(np.nan)
        elif _is_real(item):
            converted.append(float(item))
        else:
            errors.append(f"invalid_score_value:{key}:{index}")
            converted.append(np.nan)
    return np.asarray(converted, dtype=float)


def _validate_physics_summary(row, *, expected_frames, case, side):
    errors = []
    physics = row.get("physics")
    summary = physics.get("summary") if isinstance(physics, dict) else None
    prefix = f"physics_summary:{side}:{case}"
    if not isinstance(summary, dict):
        return None, [prefix + ":missing"]
    missing = [key for key in PHYSICS_SUMMARY_FIELDS if key not in summary]
    if missing:
        return None, [prefix + ":missing:" + key for key in missing]
    extra = sorted(set(summary) - set(PHYSICS_SUMMARY_FIELDS))
    if extra:
        errors.append(f"{prefix}:unexpected_fields:{','.join(extra)}")

    for key in PHYSICS_COUNT_FIELDS:
        value = summary[key]
        if not _is_integral(value) or int(value) < 0:
            errors.append(f"{prefix}:invalid_count:{key}")
    if _is_integral(summary["expected_frames"]) and int(summary["expected_frames"]) != expected_frames:
        errors.append(f"{prefix}:expected_frame_mismatch")
    completed = int(summary["completed_frames"]) if _is_integral(summary["completed_frames"]) else -1
    if completed > expected_frames:
        errors.append(f"{prefix}:completed_frame_overflow")
    frames_predicted = row.get("frames_predicted")
    if _is_integral(frames_predicted) and completed >= 0 and int(frames_predicted) != completed:
        errors.append(f"{prefix}:completed_frame_mismatch")
    for key in PHYSICS_FLOAT_FIELDS:
        value = summary[key]
        if value is None:
            if completed != 0:
                errors.append(f"{prefix}:missing_float:{key}")
        elif not (_is_real(value) and math.isfinite(float(value)) and float(value) >= 0):
            errors.append(f"{prefix}:invalid_float:{key}")
    for key in ("validity_mismatch_frames", "changed_particle_mass_frames"):
        value = summary[key]
        if _is_integral(value) and completed >= 0 and int(value) > completed:
            errors.append(f"{prefix}:count_overflow:{key}")
    statuses = summary["wall_chord_statuses"]
    if not isinstance(statuses, list) or not all(isinstance(item, str) and item for item in statuses):
        errors.append(f"{prefix}:invalid_wall_statuses")
    elif statuses != sorted(set(statuses)):
        errors.append(f"{prefix}:invalid_wall_statuses")
    wall_count = summary["wall_chord_particle_count"]
    if _is_integral(wall_count) and int(wall_count) < 0:
        errors.append(f"{prefix}:invalid_wall_count")
    wall_mass = summary["wall_chord_mass_kg"]
    if not (_is_real(wall_mass) and math.isfinite(float(wall_mass)) and float(wall_mass) >= 0):
        errors.append(f"{prefix}:invalid_wall_mass")
    return summary, errors


def _validate_score_row(row, *, expected_frames, case, side):
    """Validate one rollout row and calculate its registered fixed score."""
    errors = []
    prefix = f"case_metadata_mismatch:{side}:{case}"
    if not isinstance(row, dict):
        return None, None, [prefix + ":row"]
    if "case_id" in row and row.get("case_id") != case:
        errors.append(prefix + ":case_id")
    if not _is_integral(row.get("expected_frames")) or int(row["expected_frames"]) != expected_frames:
        errors.append(prefix + ":expected_frames")
    for key in ("length_m", "speed_mps"):
        if not _finite_positive(row.get(key)):
            errors.append(prefix + ":" + key)
    if not isinstance(row.get("executed"), (bool, np.bool_)):
        errors.append(prefix + ":executed")
    for key in ("frames_predicted", "frames_executed", "frames_expected"):
        if not _is_integral(row.get(key)) or int(row[key]) < 0 or int(row[key]) > expected_frames:
            errors.append(prefix + ":" + key)
    if _is_integral(row.get("frames_expected")) and int(row["frames_expected"]) != expected_frames:
        errors.append(prefix + ":frames_expected")
    if _is_integral(row.get("frames_executed")) and _is_integral(row.get("frames_predicted")):
        if int(row["frames_executed"]) != int(row["frames_predicted"]):
            errors.append(prefix + ":frames_executed")
    category = row.get("failure_category")
    if category is not None and (not isinstance(category, str) or not category):
        errors.append(prefix + ":failure_category")
    first_failure = row.get("first_failure_frame")
    if first_failure is not None and (
        not _is_integral(first_failure) or int(first_failure) < 1 or int(first_failure) > expected_frames
    ):
        errors.append(prefix + ":first_failure_frame")

    position = _read_score_array(row, "position_rmse", expected_frames, errors)
    velocity = _read_score_array(row, "velocity_rmse", expected_frames, errors)
    finite = np.isfinite(position) & np.isfinite(velocity)
    first_bad = int(np.flatnonzero(~finite)[0]) if np.any(~finite) else expected_frames
    if np.any(finite[first_bad:]):
        errors.append(prefix + ":finite_prefix")

    attempted = bool(row.get("executed")) if isinstance(row.get("executed"), (bool, np.bool_)) else None
    # score_case intentionally owns the registered clipping and denominator
    # arithmetic. It rejects negative values and invalid scales for us. Its
    # unexecuted branch accepts an empty prediction sequence; represent an
    # all-null setup failure that way while retaining the registered frame
    # denominator in the resulting score.
    score_position, score_velocity = position, velocity
    if attempted is False and not finite.any():
        score_position = score_velocity = np.empty(0, dtype=float)
    try:
        score = score_case(
            score_position,
            score_velocity,
            expected_frames=expected_frames,
            length_m=float(row["length_m"]),
            speed_mps=float(row["speed_mps"]),
            executed=bool(row.get("executed")),
            failure_category=category,
        )
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        errors.append(prefix + ":invalid_score:" + type(error).__name__)
        score = None

    predicted = row.get("frames_predicted")
    if _is_integral(predicted) and int(predicted) != first_bad:
        errors.append(prefix + ":frames_predicted")
    if attempted is False and first_bad != 0:
        errors.append(prefix + ":unexecuted_predictions")
    if first_bad == expected_frames:
        if category is not None:
            errors.append(prefix + ":completed_failure_category")
        if first_failure is not None:
            errors.append(prefix + ":completed_first_failure_frame")
    else:
        if category is None:
            errors.append(prefix + ":missing_failure_category")
        if first_failure is not None and int(first_failure) != first_bad + 1:
            errors.append(prefix + ":first_failure_frame")
    physics, physics_errors = _validate_physics_summary(
        row, expected_frames=expected_frames, case=case, side=side
    )
    errors.extend(physics_errors)
    return score, physics, errors


def _compare_physics(left, right, *, case):
    errors = []
    prefix = f"physics_metric_mismatch:{case}"
    if set(left) != set(right):
        return [f"physics_summary_missing_or_mismatched:{case}"]
    for key in PHYSICS_SUMMARY_FIELDS:
        x, y = left[key], right[key]
        if key in PHYSICS_COUNT_FIELDS or key == "wall_chord_statuses":
            if x != y:
                errors.append(f"{prefix}:{key}")
            continue
        if x is None or y is None:
            if x is not y:
                errors.append(f"{prefix}:{key}")
            continue
        if not np.isclose(
            float(x),
            float(y),
            rtol=PROTOCOL["physics_float_relative_tolerance"],
            atol=PROTOCOL["physics_float_absolute_tolerance"],
            equal_nan=False,
        ):
            errors.append(f"{prefix}:{key}")
    return errors


def _report_metadata_mismatches(a, b):
    errors = []
    if a.get("model_kind") != b.get("model_kind") or not isinstance(a.get("model_kind"), str):
        errors.append("model_kind_mismatch")
    # Paths are host-local, so compare only stable identity fields when they
    # are supplied. A field present on one side but absent on the other is a
    # missing identity, not an agreement.
    for key in ("schema", "seed", "hidden", "checkpoint_sha256", "bundle_sha256", "dataset_id"):
        if (key in a or key in b) and (key not in a or key not in b or a.get(key) != b.get(key)):
            errors.append("report_identity_mismatch:" + key)
    return errors


def compare_scores(left, right, *, expected_frames):
    """Compare fixed-denominator score reports from two hosts.

    Input rows must retain one score slot per registered future frame,
    including null slots after a failure. This keeps a truncated report from
    being silently promoted to a shorter denominator by score_case().
    """
    expected_frames = _validate_expected_frames(expected_frames, minimum=1)
    a, b = [json.loads(Path(path).read_text()) for path in (left, right)]
    errors = _report_metadata_mismatches(a, b)
    cases = {}
    a_cases, b_cases = a.get("cases"), b.get("cases")
    if not isinstance(a_cases, dict) or not isinstance(b_cases, dict) or not a_cases:
        errors.append("case_denominator_mismatch")
    elif set(a_cases) != set(b_cases):
        errors.append("case_denominator_mismatch")
    else:
        for case in sorted(a_cases):
            x, y = a_cases[case], b_cases[case]
            sx, px, ex = _validate_score_row(x, expected_frames=expected_frames, case=case, side="left")
            sy, py, ey = _validate_score_row(y, expected_frames=expected_frames, case=case, side="right")
            errors.extend(ex)
            errors.extend(ey)
            if isinstance(x, dict) and isinstance(y, dict):
                if x.get("failure_category") != y.get("failure_category"):
                    errors.append("case_metadata_mismatch:" + case + ":failure_category")
                if x.get("frames_predicted") != y.get("frames_predicted"):
                    errors.append("case_metadata_mismatch:" + case + ":frames_predicted")
            if sx is not None and sy is not None:
                difference = abs(sx["selection_score"] - sy["selection_score"])
                if difference > PROTOCOL["score_absolute_tolerance"]:
                    errors.append("fixed_denominator_score_mismatch:" + case)
                if sx["complete"] != sy["complete"]:
                    errors.append("fixed_denominator_completion_mismatch:" + case)
                if sx["first_failure_frame"] != sy["first_failure_frame"]:
                    errors.append("fixed_denominator_failure_frame_mismatch:" + case)
            else:
                difference = None
            if px is not None and py is not None:
                errors.extend(_compare_physics(px, py, case=case))
            cases[case] = {
                "left": sx,
                "right": sy,
                "absolute_score_difference": difference,
                "left_complete": bool(sx and sx["complete"]),
                "right_complete": bool(sy and sy["complete"]),
            }
    return {
        "passed": not errors,
        "errors": errors,
        "cases": cases,
        "score_absolute_tolerance": PROTOCOL["score_absolute_tolerance"],
        "physics_float_rtol": PROTOCOL["physics_float_relative_tolerance"],
        "physics_float_atol": PROTOCOL["physics_float_absolute_tolerance"],
        "left_sha256": digest(left),
        "right_sha256": digest(right),
    }


def compare(left, right, *, expected_frames):
    """Compare two HDF5 public-State trajectories frame by frame."""
    expected_frames = _validate_expected_frames(expected_frames, minimum=2)
    fields = ("time", "particle_id", "particle_zone", "mass", "valid", "position", "velocity")
    errors = []
    max_difference = {}
    first_mismatch = {}
    with h5py.File(left, "r") as a, h5py.File(right, "r") as b:
        for key in fields:
            if key not in a or key not in b:
                errors.append("missing_field:" + key)
            elif a[key].shape != b[key].shape:
                errors.append("shape_mismatch:" + key)
        if not errors:
            left_count, left_errors = _trajectory_layout(a, "left", expected_frames)
            right_count, right_errors = _trajectory_layout(b, "right", expected_frames)
            errors.extend(left_errors)
            errors.extend(right_errors)
            if left_count is not None and right_count is not None and left_count != right_count:
                errors.append("particle_count_mismatch")
        if not errors:
            for key in ("time", "particle_id", "particle_zone", "mass"):
                if not np.array_equal(a[key][:], b[key][:]):
                    errors.append("exact_mismatch:" + key)
            frames = expected_frames
            for frame in range(frames):
                va, ea = _validate_valid_frame(a["valid"][frame], "left", frame)
                vb, eb = _validate_valid_frame(b["valid"][frame], "right", frame)
                errors.extend(ea)
                errors.extend(eb)
                if va is None or vb is None:
                    continue
                if not np.array_equal(va, vb):
                    first_mismatch.setdefault("valid", frame)
                    errors.append(f"valid_mask_mismatch:{frame}")
                common = va & vb
                for key, tolerance in (
                    ("position", PROTOCOL["position_absolute_tolerance_m"]),
                    ("velocity", PROTOCOL["velocity_absolute_tolerance_mps"]),
                ):
                    left_state = np.asarray(a[key][frame])
                    right_state = np.asarray(b[key][frame])
                    # Validate each host's active state before intersecting
                    # masks. A valid/nonfinite left particle must not be
                    # hidden by a false right valid bit.
                    if not np.isfinite(left_state[va]).all():
                        first_mismatch.setdefault(key, frame)
                        errors.append(f"nonfinite_valid_state:left:{key}:{frame}")
                    if not np.isfinite(right_state[vb]).all():
                        first_mismatch.setdefault(key, frame)
                        errors.append(f"nonfinite_valid_state:right:{key}:{frame}")
                    if not common.any():
                        continue
                    x, y = left_state[common], right_state[common]
                    if not np.isfinite(x).all() or not np.isfinite(y).all():
                        # The host-specific checks above already recorded the
                        # failure. Do not manufacture a NaN maximum that
                        # would make the JSON result itself unwritable.
                        continue
                    difference = float(np.max(np.abs(x - y)))
                    max_difference[key] = max(max_difference.get(key, 0.0), difference)
                    if not np.allclose(
                        x,
                        y,
                        rtol=PROTOCOL["relative_tolerance"],
                        atol=tolerance,
                        equal_nan=False,
                    ):
                        first_mismatch.setdefault(key, frame)
    return {
        "schema": "core.cross_host_result.v1",
        "protocol": PROTOCOL,
        "passed": not errors and not first_mismatch,
        "errors": errors,
        "first_mismatch_frame": first_mismatch,
        "maximum_absolute_difference": max_difference,
        "left_sha256": digest(left),
        "right_sha256": digest(right),
        "scientific_qualification": False,
        "scoring_agreement": "requires separate score comparison",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("left", "right", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--expected-frames", type=int, required=True)
    parser.add_argument("--left-score", type=Path, required=True)
    parser.add_argument("--right-score", type=Path, required=True)
    args = parser.parse_args()
    result = compare(args.left, args.right, expected_frames=args.expected_frames)
    result["scoring_agreement"] = compare_scores(
        args.left_score, args.right_score, expected_frames=args.expected_frames - 1
    )
    result["passed"] = result["passed"] and result["scoring_agreement"]["passed"]
    atomic_json(args.output, result)
