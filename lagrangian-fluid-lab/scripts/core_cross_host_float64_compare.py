#!/usr/bin/env python3
"""Compare the exact state-array receipts from the float64 canary.

The float64 runner stores JSON metadata plus a compressed NPZ sidecar.  This
comparator treats the JSON as an identity/contract receipt and computes
elementwise errors from the sidecar itself.  Production defaults require all
20 transitions, 21 frames, and the registered 34,560-particle axis.  Small
fixtures can pass explicit expectations to :func:`compare_reports` without
weakening the command-line contract.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any

import numpy as np


SCHEMA = "core.cross_host_canary.float64.v1"
COMPARISON_SCHEMA = "core.cross_host_canary.float64_comparison.v1"
EXPECTED_VARIANT = "float64_inference"
EXPECTED_STEPS = 20
EXPECTED_FRAMES = 21
EXPECTED_PARTICLE_COUNT = 34560
POSITION_ATOL_M = 1.0e-5
VELOCITY_ATOL_MPS = 1.0e-4
RELATIVE_TOLERANCE = 1.0e-4
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
IDENTITY_BUNDLE_KEYS = ("manifest", "checkpoint", "core_models")
IDENTITY_CASE_KEYS = (
    "physical_case_id", "lineage_group_id", "family", "split",
    "hdf5_sha256_declared", "known_inputs_sha256",
)


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


def _digest(array: np.ndarray) -> dict[str, Any]:
    array = np.ascontiguousarray(np.asarray(array))
    finite = bool(array.dtype.kind not in "fc" or np.isfinite(array).all())
    return {
        "sha256": hashlib.sha256(array.view(np.uint8)).hexdigest(),
        "dtype": str(array.dtype),
        "shape": [int(item) for item in array.shape],
        "finite": finite,
    }


def _load(path: Path) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    try:
        value = json.loads(Path(path).read_text(), parse_constant=_reject_constant)
    except Exception as error:
        return {}, [f"invalid_json:{type(error).__name__}:{error}"]
    if not isinstance(value, dict):
        return {}, ["report_root_is_not_object"]
    return value, errors


def _identity(report: dict[str, Any], label: str, errors: list[str]) -> dict[str, Any]:
    identity: dict[str, Any] = {"bundle": {}, "case": {}}
    bundle = report.get("bundle")
    bundle_identity = bundle.get("identity") if isinstance(bundle, dict) else None
    if not isinstance(bundle_identity, dict):
        errors.append(f"{label}:missing_bundle_identity")
    else:
        for section in ("expected", "observed"):
            values = bundle_identity.get(section)
            if not isinstance(values, dict):
                errors.append(f"{label}:missing_bundle_identity:{section}")
                continue
            identity["bundle"][section] = {}
            for key in IDENTITY_BUNDLE_KEYS:
                item = values.get(key)
                if section == "expected":
                    if not _valid_sha(item):
                        errors.append(f"{label}:invalid_bundle_expected_sha:{key}")
                elif not isinstance(item, dict) or not _valid_sha(item.get("sha256")):
                    errors.append(f"{label}:invalid_bundle_observed_sha:{key}")
                observed_sha = item if section == "expected" else item.get("sha256")
                identity["bundle"][section][key] = observed_sha
                if section == "observed" and observed_sha != bundle_identity.get("expected", {}).get(key):
                    errors.append(f"{label}:bundle_expected_observed_mismatch:{key}")
    case = report.get("case")
    if not isinstance(case, dict):
        errors.append(f"{label}:missing_case_identity")
    else:
        for key in IDENTITY_CASE_KEYS:
            value = case.get(key)
            if not isinstance(value, str) or not value:
                errors.append(f"{label}:missing_case_identity:{key}")
            identity["case"][key] = value
        for key in ("hdf5_sha256_declared", "known_inputs_sha256"):
            if not _valid_sha(case.get(key)):
                errors.append(f"{label}:invalid_case_sha:{key}")
    return identity


def _validate_contract(report: dict[str, Any], label: str, *, expected_frames: int,
                       expected_particle_count: int) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    if report.get("schema") != SCHEMA:
        errors.append(f"{label}:schema")
    if report.get("status") != "complete":
        errors.append(f"{label}:status")
    if report.get("variant") != EXPECTED_VARIANT:
        errors.append(f"{label}:variant")
    if report.get("inference_dtype") != "float64":
        errors.append(f"{label}:inference_dtype")
    if report.get("model_kind") != "graph_residual":
        errors.append(f"{label}:model_kind")
    if report.get("maximum_steps") != expected_frames - 1:
        errors.append(f"{label}:maximum_steps")
    if report.get("expected_frames") != expected_frames:
        errors.append(f"{label}:expected_frames")
    if report.get("completed_steps") != expected_frames - 1:
        errors.append(f"{label}:completed_steps")
    if report.get("chunk_size") != 256:
        errors.append(f"{label}:chunk_size")
    steps = report.get("steps")
    if not isinstance(steps, list) or len(steps) != expected_frames - 1:
        errors.append(f"{label}:step_count")
    else:
        for index, step in enumerate(steps):
            if not isinstance(step, dict) or step.get("step") != index or step.get("frame") != index + 1:
                errors.append(f"{label}:step_sequence:{index}")
    protocol = report.get("comparison_protocol")
    expected_protocol = {
        "position_absolute_tolerance_m": POSITION_ATOL_M,
        "velocity_absolute_tolerance_mps": VELOCITY_ATOL_MPS,
        "relative_tolerance": RELATIVE_TOLERANCE,
        "tolerances_frozen": True,
    }
    if not isinstance(protocol, dict) or protocol.get("schema") != "core.cross_host_comparison.v1":
        errors.append(f"{label}:comparison_protocol")
    else:
        for key, value in expected_protocol.items():
            if protocol.get(key) != value:
                errors.append(f"{label}:protocol:{key}")
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
    identity = _identity(report, label, errors)
    return identity, errors


def _load_arrays(report: dict[str, Any], report_path: Path, label: str, *,
                 expected_frames: int, expected_particle_count: int) -> tuple[dict[str, np.ndarray], dict[str, Any], list[str]]:
    errors: list[str] = []
    reference = report.get("trajectory_arrays")
    if not isinstance(reference, dict):
        return {}, {}, [f"{label}:missing_trajectory_arrays"]
    raw_path = reference.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        return {}, reference, [f"{label}:trajectory_path"]
    path = Path(raw_path)
    if not path.is_absolute():
        path = report_path.parent / path
    path = path.resolve()
    if not path.is_file():
        # Collection may relocate an immutable worker output next to its JSON
        # receipt.  Permit that relocation only by basename and still require
        # the declared content hash below; never search broadly or substitute
        # an unrelated NPZ.
        relocated = (report_path.parent / path.name).resolve()
        if relocated.is_file():
            path = relocated
        else:
            return {}, reference, [f"{label}:trajectory_missing:{path}"]
    declared_sha = reference.get("sha256")
    if not _valid_sha(declared_sha):
        errors.append(f"{label}:trajectory_sha_format")
    elif sha256_file(path) != declared_sha:
        errors.append(f"{label}:trajectory_sha_mismatch")
    if reference.get("frames") != expected_frames:
        errors.append(f"{label}:trajectory_frames_metadata")
    if reference.get("particle_count") != expected_particle_count:
        errors.append(f"{label}:trajectory_particle_metadata")
    if reference.get("dtype") != "float64":
        errors.append(f"{label}:trajectory_dtype_metadata")
    if sorted(reference.get("keys", [])) != ["position", "time_s", "velocity"]:
        errors.append(f"{label}:trajectory_keys_metadata")
    try:
        with np.load(path, allow_pickle=False) as archive:
            keys = set(archive.files)
            required = {"position", "velocity", "time_s"}
            if keys != required:
                errors.append(f"{label}:trajectory_keys")
            arrays = {key: np.array(archive[key], copy=True) for key in required if key in keys}
    except Exception as error:
        return {}, reference, errors + [f"{label}:trajectory_load:{type(error).__name__}:{error}"]
    for key in ("position", "velocity"):
        value = arrays.get(key)
        if value is None or value.shape != (expected_frames, expected_particle_count, 3):
            errors.append(f"{label}:trajectory_shape:{key}")
        elif value.dtype != np.float64:
            errors.append(f"{label}:trajectory_dtype:{key}")
        elif not np.isfinite(value).all():
            errors.append(f"{label}:trajectory_nonfinite:{key}")
    times = arrays.get("time_s")
    if times is None or times.shape != (expected_frames,) or times.dtype != np.float64:
        errors.append(f"{label}:trajectory_time_shape_dtype")
    elif not np.isfinite(times).all() or np.any(np.diff(times) <= 0):
        errors.append(f"{label}:trajectory_time_nonfinite_or_nonmonotonic")
    metadata = {"path": str(path), "sha256": declared_sha,
                "frames": reference.get("frames"), "particle_count": reference.get("particle_count"),
                "dtype": reference.get("dtype"), "keys": sorted(keys)}
    return arrays, metadata, errors


def _array_error(left: np.ndarray, right: np.ndarray, *, atol: float,
                 rtol: float) -> dict[str, Any]:
    a, b = np.asarray(left), np.asarray(right)
    result: dict[str, Any] = {
        "shape_equal": a.shape == b.shape,
        "dtype_equal": a.dtype == b.dtype,
        "finite": bool(np.isfinite(a).all() and np.isfinite(b).all()) if a.dtype.kind in "fc" and b.dtype.kind in "fc" else False,
    }
    if a.shape != b.shape or not result["finite"]:
        result.update({"max_abs_error": None, "violation_count": None,
                       "max_tolerance_ratio": None, "argmax_index": None,
                       "within_tolerance": False})
        return result
    af, bf = a.astype(np.float64), b.astype(np.float64)
    difference = np.abs(af - bf)
    limit = float(atol) + float(rtol) * np.abs(af)
    violation = difference > limit
    flat_index = int(np.argmax(difference)) if difference.size else 0
    result.update({
        "max_abs_error": float(np.max(difference)) if difference.size else 0.0,
        "mean_abs_error": float(np.mean(difference)) if difference.size else 0.0,
        "rms_error": float(np.sqrt(np.mean((bf - af) ** 2))) if difference.size else 0.0,
        "violation_count": int(np.count_nonzero(violation)),
        "max_tolerance_ratio": float(np.max(np.divide(difference, limit, out=np.zeros_like(difference), where=limit > 0))) if difference.size else 0.0,
        "argmax_index": [int(item) for item in np.unravel_index(flat_index, a.shape)] if difference.size else None,
        "within_tolerance": bool(not np.any(violation)),
        "atol": float(atol),
        "rtol": float(rtol),
    })
    return result


def _check_digest_against_array(digest: Any, array: np.ndarray, label: str,
                                errors: list[str]) -> None:
    if not isinstance(digest, dict):
        errors.append(f"{label}:missing_state_digest")
        return
    observed = _digest(array)
    for key in ("sha256", "dtype", "shape", "finite"):
        if digest.get(key) != observed[key]:
            errors.append(f"{label}:state_digest:{key}")


def compare_reports(left_path: Path | str, right_path: Path | str, *,
                    expected_frames: int = EXPECTED_FRAMES,
                    expected_particle_count: int = EXPECTED_PARTICLE_COUNT) -> dict[str, Any]:
    """Return a strict paired report without raising on a bad receipt."""
    left_path, right_path = Path(left_path).resolve(), Path(right_path).resolve()
    left, left_load_errors = _load(left_path)
    right, right_load_errors = _load(right_path)
    left_identity, left_errors = _validate_contract(
        left, "left", expected_frames=expected_frames,
        expected_particle_count=expected_particle_count)
    right_identity, right_errors = _validate_contract(
        right, "right", expected_frames=expected_frames,
        expected_particle_count=expected_particle_count)
    errors = left_load_errors + right_load_errors + left_errors + right_errors
    identity_mismatches: list[str] = []
    if left_identity != right_identity:
        for section in ("bundle", "case"):
            if left_identity.get(section) != right_identity.get(section):
                identity_mismatches.append(section)
    arrays_left, metadata_left, array_errors_left = _load_arrays(
        left, left_path, "left", expected_frames=expected_frames,
        expected_particle_count=expected_particle_count)
    arrays_right, metadata_right, array_errors_right = _load_arrays(
        right, right_path, "right", expected_frames=expected_frames,
        expected_particle_count=expected_particle_count)
    errors.extend(array_errors_left + array_errors_right)
    for label, report, arrays in (("left", left, arrays_left), ("right", right, arrays_right)):
        if arrays:
            _check_digest_against_array(report.get("initial_state", {}).get("position"), arrays["position"][0], label, errors)
            _check_digest_against_array(report.get("initial_state", {}).get("velocity"), arrays["velocity"][0], label, errors)
            steps = report.get("steps", [])
            for index, step in enumerate(steps if isinstance(steps, list) else []):
                if index + 1 >= len(arrays["position"]):
                    break
                _check_digest_against_array(step.get("state_after", {}).get("position"), arrays["position"][index + 1], f"{label}:frame{index + 1}", errors)
                _check_digest_against_array(step.get("state_after", {}).get("velocity"), arrays["velocity"][index + 1], f"{label}:frame{index + 1}", errors)
    numeric: dict[str, Any] = {}
    if arrays_left and arrays_right:
        numeric["time_s"] = _array_error(arrays_left["time_s"], arrays_right["time_s"], atol=0.0, rtol=0.0)
        numeric["position"] = _array_error(arrays_left["position"], arrays_right["position"], atol=POSITION_ATOL_M, rtol=RELATIVE_TOLERANCE)
        numeric["velocity"] = _array_error(arrays_left["velocity"], arrays_right["velocity"], atol=VELOCITY_ATOL_MPS, rtol=RELATIVE_TOLERANCE)
    else:
        numeric["time_s"] = numeric["position"] = numeric["velocity"] = {"within_tolerance": False}
    identity_passed = not identity_mismatches and not any(item.startswith(("left:", "right:")) for item in errors)
    arrays_passed = not array_errors_left and not array_errors_right and all(
        numeric[key].get("within_tolerance") is True for key in ("time_s", "position", "velocity"))
    result = {
        "schema": COMPARISON_SCHEMA,
        "status": "pass" if not errors and identity_passed and arrays_passed else "fail",
        "scope": {
            "variant": EXPECTED_VARIANT,
            "expected_steps": int(expected_frames - 1),
            "expected_frames": int(expected_frames),
            "expected_particle_count": int(expected_particle_count),
            "full_835_frame_reproduction": False,
        },
        "identity": {
            "passed": identity_passed,
            "mismatches": identity_mismatches,
            "left": left_identity,
            "right": right_identity,
        },
        "arrays": {
            "passed": arrays_passed,
            "left": metadata_left,
            "right": metadata_right,
            "numeric": numeric,
        },
        "tolerances": {
            "position_absolute_m": POSITION_ATOL_M,
            "velocity_absolute_mps": VELOCITY_ATOL_MPS,
            "relative": RELATIVE_TOLERANCE,
            "frozen": True,
        },
        "errors": errors,
    }
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = compare_reports(args.left, args.right)
    atomic = Path(args.output).expanduser().resolve()
    atomic.parent.mkdir(parents=True, exist_ok=True)
    temporary = atomic.with_name(atomic.name + ".tmp")
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    temporary.replace(atomic)
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
