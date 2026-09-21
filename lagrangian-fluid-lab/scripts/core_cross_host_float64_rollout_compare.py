#!/usr/bin/env python3
"""Compare complete float64 rollout receipts and streamed HDF5 states.

The comparator validates the full input identity, 835-transition receipt,
fixed-denominator score, per-frame physics diagnostics, and every HDF5 state
frame.  HDF5 arrays are read one frame at a time so comparison memory does
not scale with the trajectory length.  The command-line contract is fixed to
the registered F3 case (836 states, 34,560 particles); smaller expectations
are available only to unit fixtures through :func:`compare_rollouts`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any

import h5py
import numpy as np


SCHEMA = "core.cross_host_float64_rollout.v1"
COMPARISON_SCHEMA = "core.cross_host_float64_rollout_comparison.v2"
EXPECTED_STEPS = 835
EXPECTED_STATE_FRAMES = 836
EXPECTED_PARTICLE_COUNT = 34560
POSITION_ATOL_M = 1.0e-5
VELOCITY_ATOL_MPS = 1.0e-4
RELATIVE_TOLERANCE = 1.0e-4
SCORE_ATOL = 1.0e-4
SCORE_RTOL = 0.0
PHYSICS_ATOL = 1.0e-6
PHYSICS_RTOL = 1.0e-4
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
BUNDLE_KEYS = ("manifest", "checkpoint", "core_models")
CASE_KEYS = ("physical_case_id", "lineage_group_id", "family", "split",
             "hdf5_sha256_declared", "known_inputs_sha256")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _reject_constant(value: str):
    raise ValueError(f"non-finite JSON constant {value}")


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and SHA256_RE.fullmatch(value) is not None


def _load_json(path: Path) -> tuple[dict[str, Any], list[str]]:
    try:
        value = json.loads(path.read_text(), parse_constant=_reject_constant)
    except Exception as error:
        return {}, [f"invalid_json:{path}:{type(error).__name__}:{error}"]
    return (value, []) if isinstance(value, dict) else ({}, [f"report_not_object:{path}"])


def _bundle_case_identity(report: dict[str, Any], label: str, errors: list[str]) -> dict[str, Any]:
    identity = {"bundle": {}, "case": {}}
    bundle = report.get("bundle")
    bundle_identity = bundle.get("identity") if isinstance(bundle, dict) else None
    if not isinstance(bundle_identity, dict):
        errors.append(f"{label}:missing_bundle_identity")
    else:
        for section in ("expected", "observed"):
            values = bundle_identity.get(section)
            if not isinstance(values, dict):
                errors.append(f"{label}:bundle_{section}_missing")
                continue
            identity["bundle"][section] = {}
            for key in BUNDLE_KEYS:
                item = values.get(key)
                digest = item if section == "expected" else item.get("sha256") if isinstance(item, dict) else None
                if not _valid_sha(digest):
                    errors.append(f"{label}:bundle_{section}_sha:{key}")
                identity["bundle"][section][key] = digest
        expected = identity["bundle"].get("expected", {})
        observed = identity["bundle"].get("observed", {})
        for key in BUNDLE_KEYS:
            if expected.get(key) != observed.get(key):
                errors.append(f"{label}:bundle_expected_observed_mismatch:{key}")
    case = report.get("case")
    if not isinstance(case, dict):
        errors.append(f"{label}:missing_case")
    else:
        for key in CASE_KEYS:
            value = case.get(key)
            if not isinstance(value, str) or not value:
                errors.append(f"{label}:case_field:{key}")
            identity["case"][key] = value
        for key in ("hdf5_sha256_declared", "known_inputs_sha256"):
            if not _valid_sha(case.get(key)):
                errors.append(f"{label}:case_sha:{key}")
    return identity


def _finite_recursive(value: Any, path: str, errors: list[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            _finite_recursive(child, f"{path}.{key}", errors)
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _finite_recursive(child, f"{path}[{index}]", errors)
    elif isinstance(value, (float, np.floating)) and not math.isfinite(float(value)):
        errors.append(f"{path}:nonfinite")


def _validate_receipt(report: dict[str, Any], label: str, *, expected_steps: int,
                      expected_state_frames: int, expected_particles: int) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    if report.get("schema") != SCHEMA:
        errors.append(f"{label}:schema")
    if report.get("status") != "complete":
        errors.append(f"{label}:status")
    if report.get("variant") != "float64_inference":
        errors.append(f"{label}:variant")
    if report.get("model_kind") != "graph_residual":
        errors.append(f"{label}:model_kind")
    if report.get("inference_dtype") != "float64":
        errors.append(f"{label}:inference_dtype")
    for key, value in (("maximum_steps", expected_steps),
                       ("expected_transition_count", expected_steps),
                       ("expected_state_frames", expected_state_frames),
                       ("completed_transitions", expected_steps)):
        if report.get(key) != value:
            errors.append(f"{label}:{key}")
    dtype = report.get("dtype_contract")
    required_dtype = {
        "feature_construction_dtype": "float32 (core_models.node_features public contract)",
        "feature_promotion": True,
        "model_input_dtype": "float64",
        "parameter_compute_dtype": "float64",
        "normalization_dtype": "float64",
        "position_tensor_dtype": "float64",
        "prior_tensor_dtype": "float64",
        "neighbor_index_dtype": "int64",
        "output_dtype": "float64 numpy SI arrays",
    }
    if not isinstance(dtype, dict):
        errors.append(f"{label}:dtype_contract")
    else:
        for key, value in required_dtype.items():
            if dtype.get(key) != value:
                errors.append(f"{label}:dtype_contract:{key}")
    protocol = report.get("comparison_protocol")
    if not isinstance(protocol, dict) or protocol.get("schema") != "core.cross_host_comparison.v1":
        errors.append(f"{label}:comparison_protocol")
    else:
        for key, value in (("position_absolute_tolerance_m", POSITION_ATOL_M),
                           ("velocity_absolute_tolerance_mps", VELOCITY_ATOL_MPS),
                           ("relative_tolerance", RELATIVE_TOLERANCE),
                           ("tolerances_frozen", True)):
            if protocol.get(key) != value:
                errors.append(f"{label}:protocol:{key}")
    score_protocol = report.get("score_protocol")
    if not isinstance(score_protocol, dict) or score_protocol.get("schema") != "core.scoring_protocol.v1":
        errors.append(f"{label}:score_protocol")
    score = report.get("score")
    if not isinstance(score, dict):
        errors.append(f"{label}:score_missing")
    else:
        if score.get("expected_frames") != expected_steps or score.get("complete") is not True:
            errors.append(f"{label}:score_incomplete")
        if score.get("finite_prefix_frames") != expected_steps:
            errors.append(f"{label}:score_finite_prefix")
        if score.get("fixed_denominator") is not True:
            errors.append(f"{label}:score_fixed_denominator")
    for key in ("position_rmse", "velocity_rmse", "position_ade", "velocity_ade"):
        values = report.get(key)
        if not isinstance(values, list) or len(values) != expected_steps:
            errors.append(f"{label}:{key}_length")
        elif any(not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) < 0
                 for value in values):
            errors.append(f"{label}:{key}_nonfinite")
    physics = report.get("physics_frames")
    if not isinstance(physics, list) or len(physics) != expected_steps or any(row is None for row in physics):
        errors.append(f"{label}:physics_frames")
    else:
        _finite_recursive(physics, f"{label}.physics_frames", errors)
    summary = report.get("physics_summary")
    if not isinstance(summary, dict) or summary.get("completed_frames") != expected_steps:
        errors.append(f"{label}:physics_summary")
    identity = _bundle_case_identity(report, label, errors)
    if identity["case"].get("family") != "F3" or identity["case"].get("split") != "validation":
        errors.append(f"{label}:case_scope")
    if report.get("case", {}).get("particle_count") != expected_particles:
        errors.append(f"{label}:particle_count")
    return identity, errors


def _resolve_artifact(report: dict[str, Any], report_path: Path, label: str,
                      errors: list[str], *, expected_frames: int,
                      expected_particles: int) -> Path | None:
    reference = report.get("trajectory")
    if not isinstance(reference, dict):
        errors.append(f"{label}:trajectory_missing")
        return None
    raw = reference.get("path")
    if not isinstance(raw, str) or not raw:
        errors.append(f"{label}:trajectory_path")
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = report_path.parent / path
    path = path.resolve()
    if not path.is_file():
        relocated = (report_path.parent / path.name).resolve()
        if relocated.is_file():
            path = relocated
        else:
            errors.append(f"{label}:trajectory_not_found:{path}")
            return None
    declared = reference.get("sha256")
    if not _valid_sha(declared) or sha256_file(path) != declared:
        errors.append(f"{label}:trajectory_hash")
    if (reference.get("frames") != expected_frames
            or reference.get("particle_count") != expected_particles):
        errors.append(f"{label}:trajectory_metadata_shape")
    if reference.get("dtype") != "float64":
        errors.append(f"{label}:trajectory_metadata_dtype")
    return path


def _h5_attr(handle: h5py.File, key: str) -> Any:
    value = handle.attrs.get(key)
    return value.decode() if isinstance(value, bytes) else value


def _validate_h5(path: Path, label: str, *, expected_frames: int,
                 expected_particles: int) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    metadata = {"path": str(path), "sha256": sha256_file(path), "frames": expected_frames,
                "particle_count": expected_particles, "dtype": "float64"}
    try:
        with h5py.File(path, "r") as handle:
            required = {"time", "position", "velocity", "particle_id", "particle_zone", "mass", "valid"}
            if set(handle.keys()) != required:
                errors.append(f"{label}:h5_keys")
            if _h5_attr(handle, "schema") != SCHEMA or _h5_attr(handle, "state_schema") != "core.state.native_velocity.v1":
                errors.append(f"{label}:h5_schema")
            if _h5_attr(handle, "storage_dtype") != "float64" or bool(_h5_attr(handle, "future_state_inputs")):
                errors.append(f"{label}:h5_contract")
            for key, shape, dtype in (
                ("time", (expected_frames,), np.dtype("float64")),
                ("position", (expected_frames, expected_particles, 3), np.dtype("float64")),
                ("velocity", (expected_frames, expected_particles, 3), np.dtype("float64")),
                ("particle_id", (expected_particles,), np.dtype("int64")),
                ("particle_zone", (expected_particles,), np.dtype("int64")),
                ("mass", (expected_particles,), np.dtype("float64")),
                ("valid", (expected_frames, expected_particles), np.dtype("bool")),
            ):
                if key not in handle or handle[key].shape != shape or handle[key].dtype != dtype:
                    errors.append(f"{label}:h5_shape_dtype:{key}")
            if not errors or all(key in handle for key in required):
                time_values = np.asarray(handle["time"][:])
                if not np.isfinite(time_values).all() or np.any(np.diff(time_values) <= 0):
                    errors.append(f"{label}:h5_time")
                mass = np.asarray(handle["mass"][:])
                if not np.isfinite(mass).all() or np.any(mass <= 0):
                    errors.append(f"{label}:h5_mass")
                for key in ("position", "velocity"):
                    dataset = handle[key]
                    for frame in range(expected_frames):
                        if not np.isfinite(dataset[frame]).all():
                            errors.append(f"{label}:h5_nonfinite:{key}:frame{frame}")
                            break
    except Exception as error:
        errors.append(f"{label}:h5_open:{type(error).__name__}:{error}")
    return metadata, errors


def _array_error(left: np.ndarray, right: np.ndarray, *, atol: float,
                 rtol: float) -> dict[str, Any]:
    a, b = np.asarray(left), np.asarray(right)
    result: dict[str, Any] = {"shape_equal": a.shape == b.shape,
                              "dtype_equal": a.dtype == b.dtype,
                              "finite": False}
    if a.shape != b.shape or a.dtype.kind not in "fc" or b.dtype.kind not in "fc":
        result.update({"within_tolerance": False, "max_abs_error": None,
                       "violation_count": None, "argmax_index": None})
        return result
    result["finite"] = bool(np.isfinite(a).all() and np.isfinite(b).all())
    if not result["finite"]:
        result.update({"within_tolerance": False, "max_abs_error": None,
                       "violation_count": None, "argmax_index": None})
        return result
    af, bf = a.astype(np.float64), b.astype(np.float64)
    delta = np.abs(af - bf)
    limit = float(atol) + float(rtol) * np.abs(af)
    violation = delta > limit
    index = int(np.argmax(delta)) if delta.size else 0
    result.update({
        "within_tolerance": bool(not np.any(violation)),
        "max_abs_error": float(delta.max()) if delta.size else 0.0,
        "mean_abs_error": float(delta.mean()) if delta.size else 0.0,
        "violation_count": int(np.count_nonzero(violation)),
        "max_tolerance_ratio": float(np.max(np.divide(delta, limit, out=np.zeros_like(delta), where=limit > 0))) if delta.size else 0.0,
        "argmax_index": [int(item) for item in np.unravel_index(index, a.shape)] if delta.size else None,
        "atol": float(atol), "rtol": float(rtol),
    })
    return result


def _compare_h5(left: Path, right: Path, *, expected_frames: int,
                expected_particles: int) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    numeric = {"position": {"within_tolerance": False},
               "velocity": {"within_tolerance": False}}
    exact = {key: False for key in ("time", "particle_id", "particle_zone", "mass", "valid")}
    try:
        with h5py.File(left, "r") as a, h5py.File(right, "r") as b:
            for key in exact:
                exact[key] = bool(np.array_equal(a[key][:], b[key][:]))
                if not exact[key]:
                    errors.append(f"h5:{key}_identity_mismatch")
            maxima = {"position": 0.0, "velocity": 0.0}
            violations = {"position": 0, "velocity": 0}
            argmax = {"position": None, "velocity": None}
            for key, atol in (("position", POSITION_ATOL_M), ("velocity", VELOCITY_ATOL_MPS)):
                for frame in range(expected_frames):
                    af = np.asarray(a[key][frame])
                    bf = np.asarray(b[key][frame])
                    row = _array_error(af, bf, atol=atol, rtol=RELATIVE_TOLERANCE)
                    if not row["finite"] or not row["shape_equal"] or not row["dtype_equal"]:
                        errors.append(f"h5:{key}:invalid_frame:{frame}")
                        continue
                    if row["max_abs_error"] > maxima[key]:
                        maxima[key] = row["max_abs_error"]
                        argmax[key] = [frame, *(row["argmax_index"] or [])]
                    violations[key] += int(row["violation_count"])
                numeric[key] = {"within_tolerance": violations[key] == 0,
                                "max_abs_error": maxima[key],
                                "violation_count": violations[key],
                                "argmax_index": argmax[key],
                                "atol": atol, "rtol": RELATIVE_TOLERANCE}
                if violations[key]:
                    errors.append(f"h5:{key}:tolerance")
    except Exception as error:
        errors.append(f"h5:compare_open:{type(error).__name__}:{error}")
    return {"exact_identity": exact, "numeric": numeric}, errors


def _flatten(value: Any, prefix: str = "") -> tuple[dict[str, float], dict[str, str]]:
    numbers: dict[str, float] = {}
    strings: dict[str, str] = {}
    if isinstance(value, dict):
        for key, child in value.items():
            n, s = _flatten(child, f"{prefix}.{key}" if prefix else str(key))
            numbers.update(n); strings.update(s)
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            n, s = _flatten(child, f"{prefix}[{index}]")
            numbers.update(n); strings.update(s)
    elif isinstance(value, (bool, int, np.integer)) or value is None:
        strings[prefix] = f"{type(value).__name__}:{value}"
    elif isinstance(value, (float, np.floating)):
        if math.isfinite(float(value)):
            numbers[prefix] = float(value)
    elif isinstance(value, str):
        strings[prefix] = value
    return numbers, strings


def _compare_receipt_arrays(left: dict[str, Any], right: dict[str, Any], key: str) -> dict[str, Any]:
    return _array_error(np.asarray(left[key], dtype=np.float64), np.asarray(right[key], dtype=np.float64),
                        atol=SCORE_ATOL, rtol=SCORE_RTOL)


def compare_rollouts(left_path: Path | str, right_path: Path | str, *,
                     expected_steps: int = EXPECTED_STEPS,
                     expected_state_frames: int = EXPECTED_STATE_FRAMES,
                     expected_particles: int = EXPECTED_PARTICLE_COUNT) -> dict[str, Any]:
    left_path, right_path = Path(left_path).resolve(), Path(right_path).resolve()
    left, left_load = _load_json(left_path)
    right, right_load = _load_json(right_path)
    left_identity, left_errors = _validate_receipt(
        left, "left", expected_steps=expected_steps,
        expected_state_frames=expected_state_frames, expected_particles=expected_particles)
    right_identity, right_errors = _validate_receipt(
        right, "right", expected_steps=expected_steps,
        expected_state_frames=expected_state_frames, expected_particles=expected_particles)
    errors = left_load + right_load + left_errors + right_errors
    identity_mismatches = [section for section in ("bundle", "case")
                           if left_identity.get(section) != right_identity.get(section)]
    if identity_mismatches:
        errors.extend(f"identity:{section}" for section in identity_mismatches)
    left_h5 = _resolve_artifact(left, left_path, "left", errors,
                                expected_frames=expected_state_frames,
                                expected_particles=expected_particles)
    right_h5 = _resolve_artifact(right, right_path, "right", errors,
                                 expected_frames=expected_state_frames,
                                 expected_particles=expected_particles)
    h5_left_meta = h5_right_meta = {}
    h5_errors: list[str] = []
    h5_numeric: dict[str, Any] = {}
    if left_h5 is not None:
        h5_left_meta, h5e = _validate_h5(left_h5, "left", expected_frames=expected_state_frames,
                                         expected_particles=expected_particles); h5_errors.extend(h5e)
    if right_h5 is not None:
        h5_right_meta, h5e = _validate_h5(right_h5, "right", expected_frames=expected_state_frames,
                                          expected_particles=expected_particles); h5_errors.extend(h5e)
    if left_h5 is not None and right_h5 is not None:
        h5_numeric, h5e = _compare_h5(left_h5, right_h5, expected_frames=expected_state_frames,
                                      expected_particles=expected_particles); h5_errors.extend(h5e)
    errors.extend(h5_errors)
    score_numeric = {}
    for key in ("position_rmse", "velocity_rmse", "position_ade", "velocity_ade"):
        if isinstance(left.get(key), list) and isinstance(right.get(key), list):
            score_numeric[key] = _compare_receipt_arrays(left, right, key)
            if not score_numeric[key].get("within_tolerance"):
                errors.append(f"score:{key}:tolerance")
        else:
            score_numeric[key] = {"within_tolerance": False}
    lnum, lexact = _flatten(left.get("score", {}))
    rnum, rexact = _flatten(right.get("score", {}))
    common_score = sorted(set(lnum) & set(rnum))
    score_summary = _array_error(np.asarray([lnum[k] for k in common_score], dtype=np.float64),
                                 np.asarray([rnum[k] for k in common_score], dtype=np.float64),
                                 atol=SCORE_ATOL, rtol=SCORE_RTOL)
    score_summary["exact_fields_equal"] = lexact == rexact
    score_summary["paths_equal"] = set(lnum) == set(rnum)
    score_summary["within_tolerance"] &= score_summary["exact_fields_equal"] and score_summary["paths_equal"]
    score_numeric["summary"] = score_summary
    if not score_summary["within_tolerance"]:
        errors.append("score:summary:tolerance_or_contract")
    physics_numeric: dict[str, Any] = {}
    lphysics, rphysics = left.get("physics_frames"), right.get("physics_frames")
    if isinstance(lphysics, list) and isinstance(rphysics, list) and len(lphysics) == len(rphysics):
        lnum, lstr = _flatten(lphysics)
        rnum, rstr = _flatten(rphysics)
        if set(lnum) != set(rnum):
            errors.append("physics:numeric_paths")
        if lstr != rstr:
            errors.append("physics:string_paths")
        common = sorted(set(lnum) & set(rnum))
        row = _array_error(np.asarray([lnum[key] for key in common]),
                           np.asarray([rnum[key] for key in common]),
                           atol=PHYSICS_ATOL, rtol=PHYSICS_RTOL)
        physics_numeric = {"paths": len(common), "numeric": row,
                           "string_equal": lstr == rstr}
        if not row.get("within_tolerance"):
            errors.append("physics:numeric_tolerance")
    else:
        errors.append("physics:frame_count")
    return {
        "schema": COMPARISON_SCHEMA,
        "status": "pass" if not errors else "fail",
        "scope": {"expected_steps": expected_steps,
                  "expected_state_frames": expected_state_frames,
                  "expected_particle_count": expected_particles,
                  "full_835_transition_reproduction": expected_steps == EXPECTED_STEPS},
        "identity": {"passed": not identity_mismatches and not left_errors and not right_errors,
                     "mismatches": identity_mismatches,
                     "left": left_identity, "right": right_identity},
        "hdf5": {"passed": not h5_errors,
                 "left": h5_left_meta, "right": h5_right_meta,
                 "comparison": h5_numeric},
        "score": {"passed": all(row.get("within_tolerance") is True for row in score_numeric.values()),
                  "comparison": score_numeric,
                  "fixed_denominator": True,
                  "atol": SCORE_ATOL, "rtol": SCORE_RTOL},
        "physics": {"passed": bool(physics_numeric) and not any(item.startswith("physics:") for item in errors),
                    "comparison": physics_numeric,
                    "atol": PHYSICS_ATOL, "rtol": PHYSICS_RTOL},
        "errors": errors,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = compare_rollouts(args.left, args.right)
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    temporary.replace(output)
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
