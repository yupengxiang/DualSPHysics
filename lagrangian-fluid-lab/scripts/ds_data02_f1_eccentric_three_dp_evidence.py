#!/usr/bin/env python3
"""Compare existing F1 ECC macro sidecars and bind existing label artifacts.

The macro reducer consumes only immutable JSON observations/reports.  It uses
nominal physical save bins with linear interpolation on each observation's
actual timestamps; it does not open trajectory HDF5.  Label binding opens
only the small materialized label HDF5 files for metadata and dataset shapes,
and rejects unexpectedly large label artifacts.  Neither part is a Q-N gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import resource
from typing import Any

import h5py
import numpy as np


REQUIRED_LABEL_DATASETS = {
    "time",
    "particle_id",
    "particle_zone",
    "source_label",
    "destination_time_series",
    "final_category",
    "failure_reason",
    "first_passage_interval",
    "first_passage_chord_time",
    "first_passage_censor",
    "residence_time_s",
    "unresolved_interval_time_s",
    "forward_backward_mass_kg",
    "cumulative_net_flux_kg",
    "unknown_mass_kg",
    "numerical_loss_mass_kg",
    "invalid_state_mass_kg",
    "source_final_mass_kg",
}


def usage() -> dict[str, dict[str, float]]:
    def one(which: int) -> dict[str, float]:
        row = resource.getrusage(which)
        return {
            "user_seconds": row.ru_utime,
            "system_seconds": row.ru_stime,
            "max_rss_kib": float(row.ru_maxrss),
            "minor_faults": float(row.ru_minflt),
            "major_faults": float(row.ru_majflt),
            "in_block": float(row.ru_inblock),
            "out_block": float(row.ru_oublock),
            "voluntary_context_switches": float(row.ru_nvcsw),
            "involuntary_context_switches": float(row.ru_nivcsw),
        }

    return {"self": one(resource.RUSAGE_SELF), "children": one(resource.RUSAGE_CHILDREN)}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path_text: str) -> tuple[Path, Any]:
    path = Path(path_text)
    if path.suffix.lower() == ".h5":
        raise ValueError(f"JSON sidecar expected, HDF5 was supplied: {path}")
    if not path.exists():
        raise FileNotFoundError(path)
    return path, json.loads(path.read_text())


def _finite(value: Any) -> bool:
    return bool(np.isfinite(np.asarray(value, dtype=float)).all())


def nominal_bins(rows: list[dict[str, Any]], cadence: float, max_offset: float) -> tuple[np.ndarray, np.ndarray]:
    if not rows:
        raise ValueError("observation has no rows")
    times = np.asarray([row["time_s"] for row in rows], dtype=float)
    if not _finite(times) or np.any(np.diff(times) <= 0):
        raise ValueError("observation time must be finite and strictly increasing")
    keys = np.rint(times / cadence).astype(np.int64)
    if len(np.unique(keys)) != len(keys):
        raise ValueError("actual times collide in registered nominal bins")
    offsets = np.abs(times - keys * cadence)
    if float(offsets.max()) > max_offset:
        raise ValueError(f"timestamp offset {offsets.max()} exceeds {max_offset}")
    return keys, times


def _interpolate(rows: list[dict[str, Any]], field: str, target: np.ndarray) -> np.ndarray:
    times = np.asarray([row["time_s"] for row in rows], dtype=float)
    values = np.asarray([row[field] for row in rows], dtype=float)
    if not _finite(values):
        raise ValueError(f"nonfinite macro field: {field}")
    flat = values.reshape((len(rows), -1))
    if target[0] < times[0] - 1e-10 or target[-1] > times[-1] + 1e-10:
        raise ValueError(f"target bins outside observation interval for {field}")
    aligned = np.column_stack([np.interp(target, times, flat[:, index]) for index in range(flat.shape[1])])
    return aligned.reshape((len(target),) + values.shape[1:])


def _observation_case(case: dict[str, Any], observation: dict[str, Any], integrity: dict[str, Any]) -> dict[str, Any]:
    required = {"schema", "coordinate_frame", "geometry_sha256", "control_sha256", "continuous_initial_mass_kg", "rows"}
    missing = sorted(required - observation.keys())
    if missing:
        raise ValueError(f"{case['case_id']} observation missing {missing}")
    rows = observation["rows"]
    dimensions = integrity.get("dimensions", {})
    if len(rows) != int(dimensions.get("frames", len(rows))):
        raise ValueError(f"{case['case_id']} observation/integrity frame count differs")
    return {
        "case_id": case["case_id"],
        "resolution": case["resolution"],
        "dp_m": case["dp_m"],
        "observation": observation,
        "integrity": integrity,
        "frames": len(rows),
        "particles": int(dimensions.get("particles", 0)),
        "initial_mass_kg": float(observation["numerical_initial_mass_kg"]),
        "initial_mass_relative_error": float(observation["initial_mass_relative_error"]),
        "geometry_sha256": observation["geometry_sha256"],
        "control_sha256": observation["control_sha256"],
        "coordinate_frame": observation["coordinate_frame"],
    }


def align_case(case: dict[str, Any], keys: np.ndarray, cadence: float) -> dict[str, Any]:
    rows = case["observation"]["rows"]
    own_keys, own_times = nominal_bins(rows, cadence, float("inf"))
    index = {int(key): int(i) for i, key in enumerate(own_keys)}
    if not set(keys.tolist()).issubset(index):
        raise ValueError(f"{case['case_id']} does not cover the common nominal bins")
    target = keys.astype(float) * cadence
    return {
        "keys": keys,
        "target_time_s": target,
        "actual_time_offset_max_s": float(np.max(np.abs(own_times - own_keys * cadence))),
        "center_of_mass_m": _interpolate(rows, "center_of_mass_m", target),
        "coordinate_quantiles_m": _interpolate(rows, "coordinate_quantiles_m", target),
        "kinetic_energy_J": _interpolate(rows, "kinetic_energy_J", target),
        "fluid_mass_kg": _interpolate(rows, "fluid_mass_kg", target),
        "mean_velocity_m_s": _interpolate(rows, "mean_velocity_m_s", target),
    }


def compare_pair(reference: dict[str, Any], candidate: dict[str, Any], *, cadence: float, max_offset: float,
                 H0: float, continuous_mass: float, macro_budget: float) -> dict[str, Any]:
    ref_rows = reference["observation"]["rows"]
    cand_rows = candidate["observation"]["rows"]
    ref_keys, _ = nominal_bins(ref_rows, cadence, max_offset)
    cand_keys, _ = nominal_bins(cand_rows, cadence, max_offset)
    common = np.intersect1d(ref_keys, cand_keys)
    if len(common) != len(ref_keys) or len(common) != len(cand_keys):
        raise ValueError("three-DP comparison does not cover the same complete nominal time bins")
    a, b = align_case(reference, common, cadence), align_case(candidate, common, cadence)
    com = np.abs(a["center_of_mass_m"] - b["center_of_mass_m"])
    quantile = np.abs(a["coordinate_quantiles_m"] - b["coordinate_quantiles_m"])
    energy = np.abs(a["kinetic_energy_J"] - b["kinetic_energy_J"])
    mass = np.abs(a["fluid_mass_kg"] - b["fluid_mass_kg"])
    velocity = np.abs(a["mean_velocity_m_s"] - b["mean_velocity_m_s"])
    energy_scale = continuous_mass * 9.81 * H0
    metrics = {
        "center_of_mass_max_over_H0": float(com.max() / H0),
        "coordinate_quantiles_max_over_H0": float(quantile.max() / H0),
        "kinetic_energy_max_over_continuous_MgH0": float(energy.max() / energy_scale),
        "mean_velocity_max_absolute_m_s": float(velocity.max()),
        "fluid_mass_max_absolute_kg": float(mass.max()),
        "fluid_mass_max_over_continuous_mass": float(mass.max() / continuous_mass),
    }
    macro_metrics = [metrics["center_of_mass_max_over_H0"], metrics["coordinate_quantiles_max_over_H0"], metrics["kinetic_energy_max_over_continuous_MgH0"]]
    return {
        "reference_case_id": reference["case_id"],
        "candidate_case_id": candidate["case_id"],
        "time_alignment": {
            "method": "linear interpolation to common nominal physical save bins",
            "nominal_cadence_s": cadence,
            "common_frame_count": len(common),
            "reference_actual_to_nominal_max_s": a["actual_time_offset_max_s"],
            "candidate_actual_to_nominal_max_s": b["actual_time_offset_max_s"],
            "between_save_motion_bound": "not available from JSON sidecars; no H5 state scan performed",
        },
        "initial_mass": {
            "reference_kg": reference["initial_mass_kg"],
            "candidate_kg": candidate["initial_mass_kg"],
            "reference_relative_error": reference["initial_mass_relative_error"],
            "candidate_relative_error": candidate["initial_mass_relative_error"],
            "difference_kg": abs(reference["initial_mass_kg"] - candidate["initial_mass_kg"]),
            "mass_normalization": "none",
        },
        "metrics": metrics,
        "macro_metric_max": float(max(macro_metrics)),
        "macro_budget": macro_budget,
        "macro_screening_within_budget": bool(max(macro_metrics) <= macro_budget),
        "series": {
            "time_s": a["target_time_s"].tolist(),
            "center_of_mass_abs_m": com.tolist(),
            "coordinate_quantiles_abs_m": quantile.tolist(),
            "kinetic_energy_abs_J": energy.tolist(),
            "fluid_mass_abs_kg": mass.tolist(),
            "mean_velocity_abs_m_s": velocity.tolist(),
        },
        "q_n_status": "not_granted",
    }


def _h5_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode()
    if isinstance(value, np.generic):
        return value.item()
    return value


def inspect_label(case: dict[str, Any], label: dict[str, Any], expected_geometry: str,
                  max_label_bytes: int) -> dict[str, Any]:
    if not label.get("label_h5"):
        return {
            "case_id": case["case_id"],
            "status": "missing_artifact",
            "binding_status": "incomplete",
            "missing_requirements": ["native transport label HDF5 not registered"],
            "q_n_status": "not_granted",
        }
    path = Path(label["label_h5"])
    if not path.exists():
        raise FileNotFoundError(path)
    if path.stat().st_size > max_label_bytes:
        raise ValueError(f"label HDF5 is larger than metadata-only limit: {path}")
    receipt_path = Path(label["receipt"])
    config_path = Path(label["config"])
    receipt = json.loads(receipt_path.read_text())
    config = json.loads(config_path.read_text())
    label_sha = sha256(path)
    with h5py.File(path, "r") as h:
        attrs = {key: _h5_value(value) for key, value in h.attrs.items()}
        datasets = {}
        for name in REQUIRED_LABEL_DATASETS:
            if name in h:
                datasets[name] = list(h[name].shape)
        missing = sorted(REQUIRED_LABEL_DATASETS - set(datasets))
        source_hash = attrs.get("source_hdf5_sha256")
        receipt_input = receipt.get("input_hashes_after_run", {})
        config_hash = sha256(config_path)
        config_hash_bound = any(str(path_text) == str(config_path) and value == config_hash for path_text, value in receipt_input.items())
        geometry_hash = attrs.get("config_json")
        embedded_config = json.loads(geometry_hash) if geometry_hash else {}
        embedded_geometry = embedded_config.get("geometry_sha256")
        source_expected = label.get("source_hdf5_sha256")
        checks = {
            "complete_attribute": attrs.get("complete") is True,
            "schema": attrs.get("schema") == "ds-data-02.native-labels.v1",
            "coordinate_frame": attrs.get("coordinate_frame") == case["coordinate_frame"],
            "required_datasets_present": not missing,
            "geometry_binding_matches_expected": embedded_geometry == expected_geometry,
            "source_hdf5_hash_matches_registration": source_expected is None or source_hash == source_expected,
            "config_hash_bound_in_receipt": config_hash_bound,
            "q_n_not_granted": attrs.get("q_n_status") == "not_assessed",
        }
        required_shapes = {
            "time": [case["frames"]],
            "particle_id": [case["particles"]],
            "particle_zone": [case["particles"]],
            "destination_time_series": [case["frames"], case["particles"]],
            "source_label": [case["particles"]],
            "final_category": [case["particles"]],
        }
        checks["identity_and_frame_shapes_match"] = all(datasets.get(k) == shape for k, shape in required_shapes.items())
        status = "bound" if all(checks.values()) else "mismatch_or_incomplete"
        return {
            "case_id": case["case_id"],
            "status": "metadata_inspected",
            "binding_status": status,
            "label_h5": str(path),
            "label_h5_sha256": label_sha,
            "label_h5_bytes": path.stat().st_size,
            "receipt": str(receipt_path),
            "receipt_sha256": sha256(receipt_path),
            "config": str(config_path),
            "config_sha256": config_hash,
            "embedded_source_hdf5": attrs.get("source_hdf5"),
            "embedded_source_hdf5_sha256": source_hash,
            "embedded_geometry_sha256": embedded_geometry,
            "expected_geometry_sha256": expected_geometry,
            "initial_fluid_mass_kg": attrs.get("initial_fluid_mass_kg"),
            "dataset_shapes": datasets,
            "checks": checks,
            "missing_datasets": missing,
            "q_n_status": "not_granted",
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    before = usage()
    manifest = json.loads(args.manifest.read_text())
    input_hashes = {str(args.manifest): sha256(args.manifest)}
    cases = []
    loaded: dict[str, Any] = {}

    def get(path_text: str) -> Any:
        if path_text not in loaded:
            path, value = load_json(path_text)
            loaded[path_text] = value
            input_hashes[str(path)] = sha256(path)
        return loaded[path_text]

    for case in manifest["cases"]:
        observation = get(case["observation"])
        integrity = get(case["integrity"])
        cases.append(_observation_case(case, observation, integrity))
    geometries = {case["geometry_sha256"] for case in cases}
    controls = {case["control_sha256"] for case in cases}
    frames = {case["frames"] for case in cases}
    if len(geometries) != 1 or len(controls) != 1 or len(frames) != 1:
        raise ValueError("three-DP sidecars do not share geometry/control/frame binding")
    cadence = float(manifest["save_cadence_s"])
    max_offset = float(manifest["max_time_offset_s"])
    H0 = float(manifest["H0_m"])
    continuous_mass = float(manifest["continuous_initial_mass_kg"])
    macro_budget = float(manifest["macro_budget_fraction"])
    pairwise = {}
    for i, reference in enumerate(cases):
        for candidate in cases[i + 1:]:
            key = f"{reference['resolution']}__vs__{candidate['resolution']}"
            pairwise[key] = compare_pair(reference, candidate, cadence=cadence, max_offset=max_offset,
                                         H0=H0, continuous_mass=continuous_mass, macro_budget=macro_budget)
    for provenance in manifest.get("provenance_files", []):
        path = Path(provenance)
        if not path.exists():
            raise FileNotFoundError(path)
        input_hashes[str(path)] = sha256(path)
    label_results = []
    for label in manifest["labels"]:
        case = next(case for case in cases if case["case_id"] == label["case_id"])
        label_result = inspect_label(case, label, manifest["geometry_sha256"], int(manifest["max_label_h5_bytes"]))
        label_results.append(label_result)
        if label.get("receipt"):
            input_hashes[str(label["receipt"])] = sha256(Path(label["receipt"]))
        if label.get("config"):
            input_hashes[str(label["config"])] = sha256(Path(label["config"]))
        if label.get("label_h5"):
            input_hashes[str(label["label_h5"])] = label_result["label_h5_sha256"]
    integrity_summary = []
    for case in cases:
        report = case["integrity"]
        integrity_summary.append({
            "case_id": case["case_id"],
            "resolution": case["resolution"],
            "frames": case["frames"],
            "particles": case["particles"],
            "initial_fluid_mass_kg": case["initial_mass_kg"],
            "initial_mass_relative_error": case["initial_mass_relative_error"],
            "q_i_status": report.get("q_i_status"),
            "q_n_status": report.get("q_n_status"),
            "lifecycle": report.get("closed_lifecycle_check", {}),
        })
    macro_status = all(item["macro_screening_within_budget"] for item in pairwise.values())
    mass_status = all(abs(case["initial_mass_relative_error"]) <= float(manifest["initial_mass_budget_fraction"]) for case in cases)
    result = {
        "schema": "ds02.f1.eccentric-three-dp-evidence.v1",
        "family_id": "F1",
        "mechanism_id": "eccentric_obstacle",
        "source_hdf5_read": False,
        "trajectory_hdf5_hash_policy": "trajectory HDF5 was not opened or hashed; macro comparison consumes observations JSON only",
        "label_hdf5_policy": "only existing small native-labels HDF5 metadata and dataset shapes were inspected; no label arrays were loaded",
        "physical_binding": {
            "geometry_sha256": next(iter(geometries)),
            "control_sha256": next(iter(controls)),
            "coordinate_frame": cases[0]["coordinate_frame"],
            "continuous_initial_mass_kg": continuous_mass,
            "mass_normalization": "none",
        },
        "frozen_budget": {
            "macro_observable_relative_error": macro_budget,
            "initial_mass_relative_error": float(manifest["initial_mass_budget_fraction"]),
            "save_cadence_s": cadence,
            "timestamp_bin_offset_limit_s": max_offset,
            "event_time_budget_s": float(manifest["event_time_budget_s"]),
            "event_time_status": "not_reassessed_by_this_macro_reducer",
        },
        "cases": integrity_summary,
        "pairwise_macro_comparisons": pairwise,
        "three_dp_macro_screening": {
            "all_pairwise_registered_macro_metrics_within_5_percent": macro_status,
            "all_three_initial_mass_values_within_1_percent": mass_status,
            "natural_mass_values_retained": [case["initial_mass_kg"] for case in cases],
            "qualification_status": "not_qualified",
            "reason": "macro sidecars provide descriptive full-window comparisons, but initial mass gate and independent transport/Q-N evidence remain unresolved",
        },
        "transport_label_binding": {
            "all_three_cases_bound": all(row["binding_status"] == "bound" for row in label_results),
            "cases": label_results,
            "qualification_status": "incomplete",
            "reason": "existing coarse labels use a stale geometry hash, medium has no label artifact, and fine is the only currently bound label artifact",
        },
        "q_n_status": "not_granted",
        "production_approval": "none",
        "input_sha256": input_hashes,
        "resource_usage": {"before": before, "after": usage()},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({
        "pairwise_count": len(pairwise),
        "macro_screening": macro_status,
        "mass_gate": mass_status,
        "label_cases_bound": sum(row["binding_status"] == "bound" for row in label_results),
        "label_cases_total": len(label_results),
        "q_n_status": "not_granted",
    }))


if __name__ == "__main__":
    main()
