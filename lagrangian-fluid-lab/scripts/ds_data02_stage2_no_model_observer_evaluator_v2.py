#!/usr/bin/env python3
"""Development no-model observers and a strict manual-prediction evaluator.

The operator consumes an already typed JSON trajectory in tests or a parent
replay sidecar.  It computes the observations from particle arrays itself:
mass-weighted COM, velocity, kinetic energy, a mass-weighted front quantile,
and a fixed physical-scale mass distribution with an unknown/outside bucket.
Finite positions on ``valid=false`` rows are ignored.  Invalid velocity is a
separate missing-velocity mass bucket and never becomes an observed speed.

Profiles freeze query times, observers, non-zero physical scales, tolerances,
source/config hashes, and the two scientific budget fractions.  A prediction
cannot replace those values, change shapes, reorder ``(Zone,Idp)``, or use
runtime seconds/output bytes as a budget.  Binding errors are reported as a
separate result from scientific score failures.  This module is development
only and grants no QI/QN/QE.  The formal score path verifies bound source
bytes; ``--skip-source-content`` is an explicit metadata-only probe.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


PROFILE_SCHEMA = "ds02.stage2.no-model-observer-profile.v2"
TRAJECTORY_SCHEMA = "ds02.stage2.no-model-observer-trajectory.v2"
PREDICTION_SCHEMA = "ds02.stage2.no-model-observer-prediction.v2"
REPORT_SCHEMA = "ds02.stage2.no-model-observer-report.v2"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")
DEFAULT_OBSERVERS = (
    "mass_weighted_com_m",
    "mean_velocity_m_s",
    "kinetic_energy_j",
    "mass_quantile_front_m",
    "mass_distribution_fraction",
    "observed_mass_fraction",
    "velocity_missing_mass_fraction",
)


class ObserverBindingError(ValueError):
    """A profile, identity, shape, time, or source binding is invalid."""


class ObserverScoreError(ValueError):
    """A bound prediction cannot receive a scientific score."""


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, allow_nan=False,
                                     default=str).encode()).hexdigest()


def file_sha256(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    try:
        value = json.loads(target.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ObserverBindingError(f"cannot read JSON {target}: {error}") from error
    if not isinstance(value, dict):
        raise ObserverBindingError(f"JSON object required: {target}")
    return value


def write_new(path: Path | str, value: Mapping[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise ObserverBindingError(f"refusing to overwrite output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, sort_keys=True,
                                 ensure_ascii=False, allow_nan=False, default=str) + "\n")


def _finite(value: Any, name: str, *, positive: bool = False, nonnegative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ObserverBindingError(f"{name} must be finite numeric data")
    result = float(value)
    if positive and result <= 0:
        raise ObserverBindingError(f"{name} must be positive")
    if nonnegative and result < 0:
        raise ObserverBindingError(f"{name} must be nonnegative")
    return result


def _sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in HEX64 for char in value):
        raise ObserverBindingError(f"{name} must be a lowercase SHA-256")
    return value


def _source_record(value: Any, role: str, *, verify_content: bool) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ObserverBindingError(f"source binding {role} is malformed")
    raw_path = value.get("path")
    if not isinstance(raw_path, str):
        raise ObserverBindingError(f"source binding {role}.path is missing")
    path = Path(raw_path).expanduser().resolve()
    if not path.is_file():
        raise ObserverBindingError(f"source binding {role} is missing: {path}")
    stat = path.stat()
    if value.get("bytes") is not None and int(value["bytes"]) != stat.st_size:
        raise ObserverBindingError(f"source binding {role} byte stat differs")
    if value.get("mtime_ns") is not None and int(value["mtime_ns"]) != stat.st_mtime_ns:
        raise ObserverBindingError(f"source binding {role} mtime differs")
    expected = _sha(value.get("sha256"), role + ".sha256")
    if verify_content and file_sha256(path) != expected:
        raise ObserverBindingError(f"source binding {role} SHA differs")
    return {"role": role, "path": str(path), "bytes": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns), "sha256": expected}


def _query_times(value: Any, name: str = "query_times_s") -> list[float]:
    if not isinstance(value, list) or not value:
        raise ObserverBindingError(f"{name} must be a non-empty list")
    result = [_finite(item, f"{name}[{index}]") for index, item in enumerate(value)]
    if any(right <= left for left, right in zip(result, result[1:])):
        raise ObserverBindingError(f"{name} must be strictly increasing")
    return result


def _profile_observers(profile: Mapping[str, Any]) -> list[str]:
    values = profile.get("observers")
    if not isinstance(values, list) or not values or any(not isinstance(item, str) for item in values):
        raise ObserverBindingError("profile observers must be a non-empty string list")
    if len(set(values)) != len(values):
        raise ObserverBindingError("profile observers must be unique")
    unknown = set(values) - set(DEFAULT_OBSERVERS)
    if unknown:
        raise ObserverBindingError(f"unsupported observer names: {sorted(unknown)}")
    return list(values)


def validate_profile(profile: Mapping[str, Any], *, verify_sources: bool = False) -> dict[str, Any]:
    if profile.get("schema") != PROFILE_SCHEMA or profile.get("status") != "PREREGISTERED_DEVELOPMENT":
        raise ObserverBindingError("profile is not a preregistered development profile")
    if profile.get("qualification") != UNKNOWN:
        raise ObserverBindingError("profile qualification must remain UNKNOWN")
    if profile.get("model_invoked") is not False or profile.get("cfd_invoked") is not False:
        raise ObserverBindingError("profile model/CFD flags are unsafe")
    if profile.get("sha256") != canonical_sha(profile):
        raise ObserverBindingError("profile canonical SHA differs")
    times = _query_times(profile.get("query_times_s"))
    observers = _profile_observers(profile)
    scales = profile.get("physical_scales")
    if not isinstance(scales, Mapping):
        raise ObserverBindingError("physical_scales are required")
    required_scales = ("position_m", "velocity_m_s", "kinetic_energy_j", "feature_time_s", "mass_kg")
    for name in required_scales:
        _finite(scales.get(name), "physical_scales." + name, positive=True)
    tolerance = profile.get("tolerances")
    if not isinstance(tolerance, Mapping):
        raise ObserverBindingError("frozen tolerances are required")
    for name, value in tolerance.items():
        _finite(value, "tolerances." + str(name), positive=True)
    budget = profile.get("budget_fraction_of_total_error")
    if not isinstance(budget, Mapping):
        raise ObserverBindingError("budget_fraction_of_total_error is required")
    for name in ("integration_time", "output_sampling"):
        value = _finite(budget.get(name), "budget_fraction_of_total_error." + name,
                        nonnegative=True)
        if value > 0.25:
            raise ObserverBindingError(f"{name} budget fraction exceeds 1/4")
    bins = profile.get("mass_distribution_bins_m")
    if not isinstance(bins, list) or not bins:
        raise ObserverBindingError("fixed mass_distribution_bins_m are required")
    bins_float = [_finite(item, f"mass_distribution_bins_m[{index}]")
                  for index, item in enumerate(bins)]
    if any(right <= left for left, right in zip(bins_float, bins_float[1:])):
        raise ObserverBindingError("mass_distribution_bins_m must be strictly increasing")
    quantile = _finite(profile.get("mass_quantile"), "mass_quantile")
    if not 0 < quantile <= 1:
        raise ObserverBindingError("mass_quantile must be in (0,1]")
    source = profile.get("source_binding")
    if not isinstance(source, Mapping) or not source:
        raise ObserverBindingError("profile source_binding is required")
    bound_sources = {}
    for role, item in source.items():
        bound_sources[role] = _source_record(item, str(role), verify_content=verify_sources)
    config_source = profile.get("config_source")
    if not isinstance(config_source, Mapping):
        raise ObserverBindingError("profile config_source is required")
    # The frozen config is part of the scientific binding.  A caller cannot
    # pair a valid prediction with a different threshold/scale file merely by
    # retaining the profile SHA.
    _source_record(config_source, "config_source", verify_content=verify_sources)
    return {"query_times_s": times, "observers": observers,
            "physical_scales": {name: float(scales[name]) for name in required_scales},
            "tolerances": {str(name): float(value) for name, value in tolerance.items()},
            "budget_fraction_of_total_error": {name: float(budget[name]) for name in ("integration_time", "output_sampling")},
            "mass_distribution_bins_m": bins_float, "mass_quantile": quantile,
            "source_binding": bound_sources}


def build_profile(config_path: Path | str, output_path: Path | str) -> dict[str, Any]:
    config_file = Path(config_path).expanduser().resolve()
    config = load_json(config_file)
    required = ("query_times_s", "observers", "physical_scales", "tolerances",
                "budget_fraction_of_total_error", "mass_distribution_bins_m",
                "mass_quantile", "source_binding")
    for key in required:
        if key not in config:
            raise ObserverBindingError(f"profile config lacks {key}")
    profile: dict[str, Any] = {
        "schema": PROFILE_SCHEMA,
        "profile_id": config.get("profile_id", "observer-profile-v2"),
        "status": "PREREGISTERED_DEVELOPMENT",
        "role": "DEVELOPMENT",
        "query_times_s": copy.deepcopy(config["query_times_s"]),
        "observers": copy.deepcopy(config["observers"]),
        "physical_scales": copy.deepcopy(config["physical_scales"]),
        "tolerances": copy.deepcopy(config["tolerances"]),
        "budget_fraction_of_total_error": copy.deepcopy(config["budget_fraction_of_total_error"]),
        "mass_distribution_bins_m": copy.deepcopy(config["mass_distribution_bins_m"]),
        "mass_quantile": config["mass_quantile"],
        "source_binding": copy.deepcopy(config["source_binding"]),
        "config_source": {"path": str(config_file), "sha256": file_sha256(config_file)},
        "model_invoked": False,
        "cfd_invoked": False,
        "qualification": copy.deepcopy(UNKNOWN),
        "freeze_policy": "freeze after observer calibration and before any new reference result; prediction cannot override scales/tolerances/times",
    }
    profile["sha256"] = canonical_sha(profile)
    validate_profile(profile, verify_sources=False)
    write_new(output_path, profile)
    return profile


def _finite_vector(value: Any, size: int, name: str) -> list[float]:
    if not isinstance(value, list) or len(value) != size:
        raise ObserverBindingError(f"{name} must have shape ({size},)")
    return [_finite(item, f"{name}[{index}]") for index, item in enumerate(value)]


def _identity(value: Any) -> list[list[int]]:
    if not isinstance(value, list) or not value:
        raise ObserverBindingError("identity must be a non-empty list")
    result = []
    for index, item in enumerate(value):
        if not isinstance(item, list) or len(item) != 2 or any(isinstance(x, bool) or not isinstance(x, int) for x in item):
            raise ObserverBindingError(f"identity[{index}] must be [Zone,Idp]")
        result.append([int(item[0]), int(item[1])])
    if len({tuple(item) for item in result}) != len(result):
        raise ObserverBindingError("identity keys must be unique")
    return result


def _trajectory_arrays(trajectory: Mapping[str, Any], profile: Mapping[str, Any]) -> tuple[list[float], list[list[int]], list[float], list[Any], list[Any], list[list[bool]]]:
    if trajectory.get("schema") != TRAJECTORY_SCHEMA:
        raise ObserverBindingError("trajectory schema differs")
    times = _query_times(trajectory.get("query_times_s"), "trajectory.query_times_s")
    expected_times = profile["query_times_s"]
    if times != expected_times:
        raise ObserverBindingError("trajectory query times differ from frozen profile")
    identity = _identity(trajectory.get("identity"))
    masses = trajectory.get("initial_mass_kg")
    if not isinstance(masses, list) or len(masses) != len(identity):
        raise ObserverBindingError("initial_mass_kg shape differs from identity")
    masses_float = [_finite(item, f"initial_mass_kg[{index}]", positive=True) for index, item in enumerate(masses)]
    positions = trajectory.get("positions_m")
    velocities = trajectory.get("velocities_m_s")
    valid = trajectory.get("valid")
    if not isinstance(positions, list) or len(positions) != len(times):
        raise ObserverBindingError("positions_m first dimension must equal query_times")
    if not isinstance(velocities, list) or len(velocities) != len(times):
        raise ObserverBindingError("velocities_m_s first dimension must equal query_times")
    if not isinstance(valid, list) or len(valid) != len(times):
        raise ObserverBindingError("valid first dimension must equal query_times")
    for t in range(len(times)):
        if not isinstance(positions[t], list) or len(positions[t]) != len(identity):
            raise ObserverBindingError(f"positions_m[{t}] particle dimension differs from identity")
        if not isinstance(velocities[t], list) or len(velocities[t]) != len(identity):
            raise ObserverBindingError(f"velocities_m_s[{t}] particle dimension differs from identity")
        if not isinstance(valid[t], list) or len(valid[t]) != len(identity) or any(not isinstance(flag, bool) for flag in valid[t]):
            raise ObserverBindingError(f"valid[{t}] must be a boolean particle mask")
        for i in range(len(identity)):
            _finite_vector(positions[t][i], 3, f"positions_m[{t}][{i}]")
            velocity = velocities[t][i]
            if velocity is not None:
                if not isinstance(velocity, list) or len(velocity) != 3:
                    raise ObserverBindingError(f"velocities_m_s[{t}][{i}] must be length 3 or null")
                # Nonfinite velocity is an explicit missing observation, not a
                # silently observed NaN.  Keep the shape but classify it below.
                if any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in velocity):
                    raise ObserverBindingError(f"velocities_m_s[{t}][{i}] has a malformed component")
    return times, identity, masses_float, positions, velocities, valid


def _weighted_quantile(values: Sequence[tuple[float, float]], quantile: float) -> float | None:
    usable = sorted((value, mass) for value, mass in values if math.isfinite(value) and mass > 0)
    total = sum(mass for _, mass in usable)
    if total <= 0:
        return None
    target = quantile * total
    cumulative = 0.0
    for value, mass in usable:
        cumulative += mass
        if cumulative >= target:
            return value
    return usable[-1][0]


def compute_observers(trajectory: Mapping[str, Any], profile: Mapping[str, Any]) -> dict[str, Any]:
    frozen = validate_profile(profile, verify_sources=False)
    _validate_trajectory_source(trajectory, profile, verify_sources=False)
    times, identity, masses, positions, velocities, valid = _trajectory_arrays(trajectory, frozen)
    denominator = sum(masses)
    bins = frozen["mass_distribution_bins_m"]
    observers = frozen["observers"]
    result: dict[str, list[Any]] = {name: [] for name in observers}
    initial_missing_mass = 0.0
    for t in range(len(times)):
        position_rows: list[tuple[int, float, list[float]]] = []
        velocity_rows: list[tuple[int, float, list[float]]] = []
        missing_velocity_mass = 0.0
        for i, mass in enumerate(masses):
            if not valid[t][i]:
                continue
            pos = positions[t][i]
            if all(math.isfinite(float(component)) for component in pos):
                position_rows.append((i, mass, [float(component) for component in pos]))
            velocity = velocities[t][i]
            if velocity is None or not all(math.isfinite(float(component)) for component in velocity):
                missing_velocity_mass += mass
            else:
                velocity_rows.append((i, mass, [float(component) for component in velocity]))
        position_mass = sum(mass for _, mass, _ in position_rows)
        velocity_mass = sum(mass for _, mass, _ in velocity_rows)
        com = None
        if position_mass > 0:
            com = [sum(mass * pos[axis] for _, mass, pos in position_rows) / position_mass for axis in range(3)]
        mean_velocity = None
        if velocity_mass > 0:
            mean_velocity = [sum(mass * vel[axis] for _, mass, vel in velocity_rows) / velocity_mass for axis in range(3)]
        kinetic_energy = sum(0.5 * mass * sum(component * component for component in vel)
                            for _, mass, vel in velocity_rows)
        front = _weighted_quantile([(pos[0], mass) for _, mass, pos in position_rows], frozen["mass_quantile"])
        distribution = [0.0 for _ in range(len(bins) + 1)]
        for _, mass, pos in position_rows:
            bin_index = next((index for index, edge in enumerate(bins) if pos[0] < edge), len(bins))
            distribution[bin_index] += mass
        distribution = [value / denominator for value in distribution]
        values = {
            "mass_weighted_com_m": com,
            "mean_velocity_m_s": mean_velocity,
            "kinetic_energy_j": kinetic_energy,
            "mass_quantile_front_m": front,
            "mass_distribution_fraction": distribution,
            "observed_mass_fraction": position_mass / denominator,
            "velocity_missing_mass_fraction": missing_velocity_mass / denominator,
        }
        for name in observers:
            result[name].append(values[name])
    result["meta"] = {
        "identity": identity,
        "query_times_s": times,
        "initial_mass_denominator_kg": denominator,
        "initial_missing_mass_kg": initial_missing_mass,
        "mass_distribution_unknown_or_outside_bucket": "last column",
        "velocity_frame": trajectory.get("velocity_frame", "world_inertial"),
        "position_frame": trajectory.get("position_frame", "world"),
        "velocity_invalid_policy": "invalid/nonfinite velocity is missing and receives no observed speed or KE credit",
    }
    return result


def _validate_trajectory_source(trajectory: Mapping[str, Any], profile: Mapping[str, Any], *, verify_sources: bool) -> None:
    expected = profile.get("source_binding")
    actual = trajectory.get("source_binding")
    if not isinstance(expected, Mapping) or not isinstance(actual, Mapping):
        raise ObserverBindingError("trajectory/profile source binding is required")
    if set(expected) != set(actual):
        raise ObserverBindingError("trajectory source roles differ from profile")
    for role in expected:
        exp = expected[role]
        got = actual[role]
        if not isinstance(got, Mapping) or got.get("sha256") != exp.get("sha256"):
            raise ObserverBindingError(f"trajectory source SHA differs: {role}")
        _source_record(got, str(role), verify_content=verify_sources)


def _validate_prediction(prediction: Mapping[str, Any], profile: Mapping[str, Any],
                         observed: Mapping[str, Any]) -> None:
    if prediction.get("schema") != PREDICTION_SCHEMA:
        raise ObserverBindingError("prediction schema differs")
    if prediction.get("profile_sha256") != profile.get("sha256"):
        raise ObserverBindingError("prediction profile SHA differs")
    if prediction.get("query_times_s") != profile.get("query_times_s"):
        raise ObserverBindingError("prediction query times differ; interpolation/extrapolation is forbidden")
    if prediction.get("identity") != observed["meta"]["identity"]:
        raise ObserverBindingError("prediction identity axis/order differs")
    if "tolerances" in prediction or "physical_scales" in prediction:
        raise ObserverBindingError("prediction cannot override frozen scales/tolerances")
    values = prediction.get("observers")
    if not isinstance(values, Mapping):
        raise ObserverBindingError("prediction observers are required")
    profile_names = set(profile["observers"])
    if set(values) != profile_names:
        raise ObserverBindingError("prediction observer set differs from frozen profile")
    for name in profile_names:
        predicted = values[name]
        actual = observed[name]
        if not isinstance(predicted, list) or len(predicted) != len(profile["query_times_s"]):
            raise ObserverBindingError(f"prediction {name} first dimension must equal query_times")
        for index, item in enumerate(predicted):
            if item is None:
                continue
            if name in {"mass_weighted_com_m", "mean_velocity_m_s"}:
                _finite_vector(item, 3, f"prediction.{name}[{index}]")
            elif name == "mass_distribution_fraction":
                if not isinstance(item, list) or len(item) != len(profile["mass_distribution_bins_m"]) + 1:
                    raise ObserverBindingError(f"prediction {name}[{index}] shape differs")
                for component in item:
                    _finite(component, f"prediction.{name}[{index}]")
            else:
                _finite(item, f"prediction.{name}[{index}]")
    budget = prediction.get("budget_fraction_of_total_error")
    if not isinstance(budget, Mapping):
        raise ObserverBindingError("prediction budget fractions are required")
    for key in ("integration_time", "output_sampling"):
        value = _finite(budget.get(key), "prediction.budget." + key, nonnegative=True)
        if value > profile["budget_fraction_of_total_error"][key]:
            raise ObserverScoreError(f"prediction {key} fraction exceeds frozen budget")
    if "evaluation_seconds" in prediction or "output_bytes" in prediction:
        raise ObserverBindingError("runtime seconds/output bytes are not scientific budget fractions")


def _error(actual: Any, predicted: Any, scale: float) -> float | None:
    if actual is None or predicted is None:
        return None
    if isinstance(actual, list):
        if not isinstance(predicted, list) or len(actual) != len(predicted):
            raise ObserverBindingError("prediction shape differs during score")
        return math.sqrt(sum((float(a) - float(p)) ** 2 for a, p in zip(actual, predicted))) / scale
    return abs(float(actual) - float(predicted)) / scale


def score_prediction(profile: Mapping[str, Any], trajectory: Mapping[str, Any],
                     prediction: Mapping[str, Any], *, verify_sources: bool = True) -> dict[str, Any]:
    frozen = validate_profile(profile, verify_sources=verify_sources)
    _validate_trajectory_source(trajectory, profile, verify_sources=verify_sources)
    observed = compute_observers(trajectory, profile)
    _validate_prediction(prediction, profile, observed)
    scales = frozen["physical_scales"]
    tolerances = frozen["tolerances"]
    scale_for = {
        "mass_weighted_com_m": (scales["position_m"], tolerances.get("position_relative", 0.02)),
        "mean_velocity_m_s": (scales["velocity_m_s"], tolerances.get("velocity_relative", 0.02)),
        "kinetic_energy_j": (scales["kinetic_energy_j"], tolerances.get("kinetic_energy_relative", 0.02)),
        "mass_quantile_front_m": (scales["position_m"], tolerances.get("position_relative", 0.02)),
        "mass_distribution_fraction": (1.0, tolerances.get("mass_fraction_absolute", 0.03)),
        "observed_mass_fraction": (1.0, tolerances.get("mass_fraction_absolute", 0.03)),
        "velocity_missing_mass_fraction": (1.0, tolerances.get("mass_fraction_absolute", 0.03)),
    }
    metric_reports: dict[str, Any] = {}
    overall_pass = True
    for name in frozen["observers"]:
        scale, tolerance = scale_for[name]
        errors: list[float] = []
        unknown_actual_count = 0
        missing_prediction_count = 0
        unexpected_prediction_count = 0
        for actual, predicted in zip(observed[name], prediction["observers"][name]):
            if actual is None:
                unknown_actual_count += 1
                if predicted is not None:
                    unexpected_prediction_count += 1
                continue
            if predicted is None:
                missing_prediction_count += 1
                continue
            if name == "mass_distribution_fraction":
                if not isinstance(actual, list) or not isinstance(predicted, list):
                    raise ObserverBindingError(f"{name} shape differs during score")
                errors.extend(abs(float(a) - float(p)) / scale for a, p in zip(actual, predicted))
            else:
                value = _error(actual, predicted, scale)
                if value is not None:
                    errors.append(value)
        maximum = max(errors, default=0.0)
        passed = (maximum <= tolerance and missing_prediction_count == 0
                  and unexpected_prediction_count == 0
                  and not (not errors and unknown_actual_count == len(observed[name])))
        if not passed:
            overall_pass = False
        metric_reports[name] = {
            "status": "PASS" if passed else "FAIL_OR_UNKNOWN",
            "max_normalized_error": maximum,
            "tolerance": tolerance,
            "scale": scale,
            "unknown_actual_query_count": unknown_actual_count,
            "missing_prediction_query_count": missing_prediction_count,
            "unexpected_prediction_query_count": unexpected_prediction_count,
            "scientific_budget_semantics": "observer metric error; no runtime/bytes substitution",
        }
    return {
        "schema": REPORT_SCHEMA,
        "status": "PASS" if overall_pass else "FAIL",
        "binding_status": "PASS_SOURCE_PROFILE_IDENTITY_TIME_BOUND",
        "metric_scores": metric_reports,
        "observed": observed,
        "budget": {
            "prediction_fraction_of_total_error": prediction["budget_fraction_of_total_error"],
            "frozen_fraction_of_total_error": frozen["budget_fraction_of_total_error"],
            "integration_time_score": "PASS",
            "output_sampling_score": "PASS",
            "runtime_seconds_or_output_bytes_used": False,
            "source_content_verified": bool(verify_sources),
        },
        "model_invoked": False,
        "cfd_invoked": False,
        "qualification": copy.deepcopy(UNKNOWN),
        "development_only": True,
        "limitations": [
            "This evaluator scores arrays against an operator-computed typed trajectory; it is not a solver/reference calibration.",
            "No HDF5/BI4 content is read by this JSON evaluator; parent replay owns raw/content verification.",
            "Event first-passage/receiver labels are outside this generic macro profile and remain UNKNOWN unless a family profile adds a source-bound operator.",
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-profile")
    build.add_argument("--config", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    observe = sub.add_parser("observe")
    observe.add_argument("--profile", type=Path, required=True)
    observe.add_argument("--trajectory", type=Path, required=True)
    observe.add_argument("--output", type=Path, required=True)
    observe.add_argument("--verify-sources", action="store_true")
    score = sub.add_parser("score")
    score.add_argument("--profile", type=Path, required=True)
    score.add_argument("--trajectory", type=Path, required=True)
    score.add_argument("--prediction", type=Path, required=True)
    score.add_argument("--output", type=Path, required=True)
    score.add_argument("--verify-sources", action="store_true")
    score.add_argument("--skip-source-content", action="store_true",
                       help="metadata-only development probe; not source-verified")
    args = parser.parse_args(argv)
    try:
        if args.command == "build-profile":
            value = build_profile(args.config, args.output)
            result = {"status": value["status"], "sha256": value["sha256"]}
        elif args.command == "observe":
            profile = load_json(args.profile)
            trajectory = load_json(args.trajectory)
            validate_profile(profile, verify_sources=args.verify_sources)
            _validate_trajectory_source(trajectory, profile, verify_sources=args.verify_sources)
            observed = compute_observers(trajectory, profile)
            output = {"schema": REPORT_SCHEMA, "status": "OBSERVED_DEVELOPMENT_JSON",
                      "profile_sha256": profile["sha256"], "source_binding": trajectory.get("source_binding"),
                      "observers": observed, "qualification": copy.deepcopy(UNKNOWN),
                      "model_invoked": False, "cfd_invoked": False}
            output["sha256"] = canonical_sha(output)
            write_new(args.output, output)
            result = {"status": output["status"], "sha256": output["sha256"]}
        else:
            profile = load_json(args.profile)
            trajectory = load_json(args.trajectory)
            prediction = load_json(args.prediction)
            output = score_prediction(profile, trajectory, prediction,
                                      verify_sources=not args.skip_source_content)
            write_new(args.output, output)
            result = {"status": output["status"], "binding_status": output["binding_status"]}
    except (ObserverBindingError, ObserverScoreError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
