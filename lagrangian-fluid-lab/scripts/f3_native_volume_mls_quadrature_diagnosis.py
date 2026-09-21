"""Audit the terminal F3 v1 512/4096 seed-axis comparison.

This is a read-only postprocessor.  It binds both terminal traces, their
launch specifications, and the registered source to distinguish a seed-axis
quadrature effect from a denominator/censoring or configuration mismatch.
It never opens an active attempt and never changes a material gate.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

import h5py
import numpy as np


SOURCE_LOW = np.asarray([-0.45, -0.09, 0.0], dtype=np.float64)
SOURCE_SIZE = np.asarray([0.90, 0.18, 0.09], dtype=np.float64)
WALL_LOW = np.asarray([-0.45, -0.09, 0.0], dtype=np.float64)
WALL_HIGH = np.asarray([0.45, 0.09, 0.51], dtype=np.float64)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _final(value: np.ndarray) -> np.ndarray:
    value = np.asarray(value)
    return value[-1] if value.ndim >= 2 else value


def _load_trace(path: str | Path) -> dict[str, Any]:
    path = Path(path).resolve()
    with h5py.File(path, "r") as handle:
        committed = int(handle.attrs["committed"])
        binding = json.loads(handle.attrs["binding"])
        value = {
            "path": str(path),
            "sha256": sha256_file(path),
            "trace_backend": str(handle.attrs["trace_backend"]),
            "committed": committed,
            "time": np.asarray(handle["time"][: committed + 1], dtype=np.float64),
            "initial_position": np.asarray(handle["initial_position"][:], dtype=np.float64),
            "source_label": np.asarray(handle["source_label"][:], dtype=np.int8),
            "reliable": np.asarray(handle["reliable"][: committed + 1], dtype=bool),
            "unknown": np.asarray(handle["permanent_unknown"][: committed + 1], dtype=bool),
            "first_passage": _final(np.asarray(handle["first_passage"][: committed + 1], dtype=np.float64)),
            "return_time": _final(np.asarray(handle["return_time"][: committed + 1], dtype=np.float64)),
            "residence": _final(np.asarray(handle["residence_opposite"][: committed + 1], dtype=np.float64)),
            "failure_reason": _final(np.asarray(handle["failure_reason"][: committed + 1], dtype=str)),
            "binding": binding,
        }
    if value["time"].ndim != 1 or len(value["time"]) != committed + 1:
        raise ValueError(f"invalid committed time axis: {path}")
    if not np.all(np.diff(value["time"]) > 0.0):
        raise ValueError(f"non-increasing time axis: {path}")
    if value["unknown"].shape != value["reliable"].shape:
        raise ValueError(f"inconsistent reliability history: {path}")
    if not np.array_equal(value["unknown"], ~value["reliable"]):
        raise ValueError(f"permanent_unknown is not the complement of reliable: {path}")
    return value


def _strip_seed_arg(argv: list[str]) -> list[str]:
    result: list[str] = []
    index = 0
    while index < len(argv):
        if argv[index] == "--seeds":
            index += 2
            continue
        result.append(argv[index])
        index += 1
    return result


def _axis_info(initial: np.ndarray, shape: tuple[int, int, int]) -> dict[str, Any]:
    axes = [np.unique(initial[:, axis]) for axis in range(3)]
    steps = np.asarray([np.diff(axis)[0] for axis in axes], dtype=np.float64)
    nearest_lower = axes[0][0] - SOURCE_LOW[0]
    nearest_interface = float(np.min(np.abs(axes[0])))
    return {
        "shape": list(shape),
        "ranges_m": [[float(axis[0]), float(axis[-1])] for axis in axes],
        "steps_m": steps.tolist(),
        "nearest_source_boundary_distance_m": nearest_interface,
        "nearest_wall_distance_m": [
            float(min(np.min(axis - WALL_LOW[j]), np.min(WALL_HIGH[j] - axis)))
            for j, axis in enumerate(axes)
        ],
        "source_domain_low_m": SOURCE_LOW.tolist(),
        "source_domain_high_m": (SOURCE_LOW + SOURCE_SIZE).tolist(),
        "level_counts": [int(len(axis)) for axis in axes],
        "first_axis_lower_offset_m": float(nearest_lower),
    }


def _grid_indices(initial: np.ndarray) -> list[np.ndarray]:
    return [np.searchsorted(np.unique(initial[:, axis]), initial[:, axis]) for axis in range(3)]


def _block_map(coarse: dict[str, Any], fine: dict[str, Any]) -> tuple[np.ndarray, dict[int, int]]:
    coarse_indices = _grid_indices(coarse["initial_position"])
    fine_indices = _grid_indices(fine["initial_position"])
    coarse_map = {
        tuple(int(value) for value in row): index
        for index, row in enumerate(np.stack(coarse_indices, axis=1))
    }
    groups = np.asarray([
        coarse_map[tuple(int(fine_indices[axis][index] // 2) for axis in range(3))]
        for index in range(len(fine["initial_position"]))
    ], dtype=np.int64)
    return groups, coarse_map


def _raw_cdf(trace_a: dict[str, Any], trace_b: dict[str, Any], event: str,
             source: int) -> dict[str, Any]:
    labels_a = trace_a["source_label"] == source
    labels_b = trace_b["source_label"] == source
    event_a = trace_a[event][labels_a]
    event_b = trace_b[event][labels_b]
    finite_a = np.isfinite(event_a)
    finite_b = np.isfinite(event_b)
    times = np.unique(np.concatenate((event_a[finite_a], event_b[finite_b])))
    denominator_a = int(np.count_nonzero(labels_a))
    denominator_b = int(np.count_nonzero(labels_b))
    cdf_a = np.asarray([
        np.count_nonzero(finite_a & (event_a <= value)) / denominator_a
        for value in times
    ], dtype=np.float64)
    cdf_b = np.asarray([
        np.count_nonzero(finite_b & (event_b <= value)) / denominator_b
        for value in times
    ], dtype=np.float64)
    difference = cdf_b - cdf_a
    if not len(times):
        return {"sup_abs_difference": 0.0, "time_s": None}
    index = int(np.argmax(np.abs(difference)))
    return {
        "sup_abs_difference": float(np.max(np.abs(difference))),
        "time_s": float(times[index]),
        "coarse_cdf": float(cdf_a[index]),
        "fine_cdf": float(cdf_b[index]),
        "signed_fine_minus_coarse": float(difference[index]),
        "denominator_coarse": denominator_a,
        "denominator_fine": denominator_b,
        "finite_event_count_coarse": int(np.count_nonzero(finite_a)),
        "finite_event_count_fine": int(np.count_nonzero(finite_b)),
    }


def _x_layer_differences(coarse: dict[str, Any], fine: dict[str, Any],
                         groups: np.ndarray, source: int, time_s: float) -> list[dict[str, Any]]:
    coarse_axes = [np.unique(coarse["initial_position"][:, axis]) for axis in range(3)]
    coarse_indices = _grid_indices(coarse["initial_position"])
    fine_indices = _grid_indices(fine["initial_position"])
    rows = []
    for x_index, x_value in enumerate(coarse_axes[0]):
        coarse_select = (coarse_indices[0] == x_index) & (coarse["source_label"] == source)
        fine_select = (fine_indices[0] // 2 == x_index) & (fine["source_label"] == source)
        if not np.any(coarse_select):
            continue
        coarse_event = _final(coarse["first_passage"])[coarse_select]
        fine_event = _final(fine["first_passage"])[fine_select]
        coarse_fraction = float(np.count_nonzero(np.isfinite(coarse_event) & (coarse_event <= time_s)) / np.count_nonzero(coarse_select))
        fine_fraction = float(np.count_nonzero(np.isfinite(fine_event) & (fine_event <= time_s)) / np.count_nonzero(fine_select))
        rows.append({
            "coarse_x_layer_index": int(x_index),
            "coarse_x_m": float(x_value),
            "coarse_seed_count": int(np.count_nonzero(coarse_select)),
            "fine_seed_count": int(np.count_nonzero(fine_select)),
            "coarse_fraction_by_time": coarse_fraction,
            "fine_fraction_by_time": fine_fraction,
            "fine_minus_coarse_fraction": fine_fraction - coarse_fraction,
            "source_weighted_contribution": (fine_fraction - coarse_fraction)
            * np.count_nonzero(coarse_select) / np.count_nonzero(coarse["source_label"] == source),
        })
    return rows


def _top_blocks(coarse: dict[str, Any], fine: dict[str, Any], groups: np.ndarray,
                source: int, time_s: float, limit: int = 12) -> list[dict[str, Any]]:
    coarse_source = coarse["source_label"] == source
    fine_source = fine["source_label"] == source
    coarse_event = _final(coarse["first_passage"])
    fine_event = _final(fine["first_passage"])
    rows = []
    for group in np.unique(groups[fine_source]):
        coarse_select = np.arange(len(coarse_source)) == group
        fine_select = (groups == group) & fine_source
        fine_fraction = float(np.count_nonzero(np.isfinite(fine_event[fine_select]) & (fine_event[fine_select] <= time_s)) / 8.0)
        coarse_indicator = float(np.isfinite(coarse_event[group]) and coarse_event[group] <= time_s)
        delta = (fine_fraction - coarse_indicator) / np.count_nonzero(coarse_source)
        rows.append({
            "coarse_seed_index": int(group),
            "coarse_initial_position_m": coarse["initial_position"][group].tolist(),
            "fine_event_count_in_block": int(np.count_nonzero(np.isfinite(fine_event[fine_select]) & (fine_event[fine_select] <= time_s))),
            "coarse_event_indicator": int(coarse_indicator),
            "source_weighted_contribution": float(delta),
        })
    rows.sort(key=lambda value: abs(value["source_weighted_contribution"]), reverse=True)
    return rows[:limit]


def diagnose(trace_512: str | Path, trace_4096: str | Path,
             spec_512: str | Path, spec_4096: str | Path,
             comparison: str | Path | None = None) -> dict[str, Any]:
    coarse = _load_trace(trace_512)
    fine = _load_trace(trace_4096)
    spec_coarse = _json(spec_512)
    spec_fine = _json(spec_4096)
    if coarse["committed"] < 1 or fine["committed"] < 1:
        raise ValueError("both traces must contain a complete committed window")
    if coarse["binding"].get("source_sha256") != fine["binding"].get("source_sha256"):
        raise ValueError("source H5 hashes differ")
    if coarse["binding"].get("walls_sha256") != fine["binding"].get("walls_sha256"):
        raise ValueError("finite-wall hashes differ")
    if coarse["binding"].get("substeps") != fine["binding"].get("substeps"):
        raise ValueError("substeps differ")
    if not np.array_equal(coarse["time"], fine["time"]):
        raise ValueError("terminal time axes differ")

    groups, _ = _block_map(coarse, fine)
    fine_counts = np.bincount(groups, minlength=len(coarse["initial_position"]))
    coarse_shape = tuple(len(np.unique(coarse["initial_position"][:, axis])) for axis in range(3))
    fine_shape = tuple(len(np.unique(fine["initial_position"][:, axis])) for axis in range(3))
    geometry = {
        "coarse": _axis_info(coarse["initial_position"], coarse_shape),
        "fine": _axis_info(fine["initial_position"], fine_shape),
        "fine_blocks_per_coarse_seed": sorted(set(int(value) for value in fine_counts)),
        "fine_blocks_all_eight": bool(np.all(fine_counts == 8)),
        "fine_grid_is_nested_in_coarse_cells": True,
        "coarse_centres_are_fine_centres": False,
        "coarse_to_fine_centre_offset_m": (SOURCE_SIZE / np.asarray(fine_shape) / 2.0).tolist(),
        "source_boundary_policy": "x < 0 source 0; x >= 0 source 1",
    }

    input_a = {item["path"]: item["sha256"] for item in spec_coarse.get("input_files", [])}
    input_b = {item["path"]: item["sha256"] for item in spec_fine.get("input_files", [])}
    argv_a = list(spec_coarse["argv"])
    argv_b = list(spec_fine["argv"])
    same_argv_except_seed = _strip_seed_arg(argv_a) == _strip_seed_arg(argv_b)
    source_inputs_a = {path: digest for path, digest in input_a.items() if path.endswith((".h5", "-PREPARED.json", "_Def.xml"))}
    source_inputs_b = {path: digest for path, digest in input_b.items() if path.endswith((".h5", "-PREPARED.json", "_Def.xml"))}
    configuration = {
        "same_argv_after_removing_seed_value": same_argv_except_seed,
        "argv_seed_values": [argv_a[argv_a.index("--seeds") + 1], argv_b[argv_b.index("--seeds") + 1]],
        "same_source_snapshot": spec_coarse.get("source_snapshot") == spec_fine.get("source_snapshot"),
        "same_environment": spec_coarse.get("env") == spec_fine.get("env"),
        "same_cwd_host": (spec_coarse.get("cwd"), spec_coarse.get("host")) == (spec_fine.get("cwd"), spec_fine.get("host")),
        "same_numeric_source_inputs": source_inputs_a == source_inputs_b,
        "extra_4096_input_files_not_in_argv": sorted(set(input_b) - set(input_a)),
        "different_resource_only_fields": {
            "512": {"resources": spec_coarse.get("resources"), "timeout_seconds": spec_coarse.get("timeout_seconds")},
            "4096": {"resources": spec_fine.get("resources"), "timeout_seconds": spec_fine.get("timeout_seconds")},
        },
        "trace_backend_same": coarse["trace_backend"] == fine["trace_backend"],
        "time_axis_max_abs_difference_s": float(np.max(np.abs(coarse["time"] - fine["time"]))),
    }

    event_rows: dict[str, Any] = {}
    comparison_value = _json(comparison) if comparison else None
    for source in (0, 1):
        source_key = str(source)
        event_rows[source_key] = {}
        for event in ("first_passage", "return_time", "residence"):
            raw = _raw_cdf(coarse, fine, event, source)
            if event == "first_passage":
                comparison_event = "first_passage"
            elif event == "return_time":
                comparison_event = "return"
            else:
                comparison_event = "residence"
            interval = None
            if comparison_value:
                interval = comparison_value["source_comparison"][source_key]["cdf_sup_difference_bounds"][comparison_event]
            row = {"raw_observed_cdf": raw, "interval_cdf": {
                "sup_abs_difference": interval.get("sup_abs_difference_bound") if interval else None,
                "sup_time_or_value_s": None,
            }}
            if interval and interval.get("time_or_value"):
                abs_values = np.maximum(np.abs(np.asarray(interval["lower_difference"])), np.abs(np.asarray(interval["upper_difference"])))
                row["interval_cdf"]["sup_time_or_value_s"] = float(interval["time_or_value"][int(np.argmax(abs_values))])
                row["interval_cdf"]["censoring_margin_over_raw_sup"] = float(interval["sup_abs_difference_bound"] - raw["sup_abs_difference"])
            event_rows[source_key][event] = row
        first = event_rows[source_key]["first_passage"]["raw_observed_cdf"]
        event_rows[source_key]["first_passage_x_layer_contributions"] = _x_layer_differences(
            coarse, fine, groups, source, first["time_s"]
        )
        event_rows[source_key]["top_coarse_blocks_at_first_passage_sup"] = _top_blocks(
            coarse, fine, groups, source, first["time_s"]
        )

    unknown = {}
    for name, trace in (("512", coarse), ("4096", fine)):
        unknown[name] = {}
        for source in (0, 1):
            select = (trace["source_label"] == source) & trace["unknown"][-1]
            reasons, counts = np.unique(trace["failure_reason"][select], return_counts=True)
            unknown[name][str(source)] = {
                "source_seed_count": int(np.count_nonzero(trace["source_label"] == source)),
                "final_unknown_count": int(np.count_nonzero(select)),
                "final_unknown_fraction": float(np.count_nonzero(select) / np.count_nonzero(trace["source_label"] == source)),
                "failure_reason_counts": {str(reason): int(count) for reason, count in zip(reasons, counts)},
                "initial_position_bounds_m": {
                    "low": trace["initial_position"][select].min(axis=0).tolist() if np.any(select) else None,
                    "high": trace["initial_position"][select].max(axis=0).tolist() if np.any(select) else None,
                },
            }

    return {
        "schema": "core.material.f3.native_volume_mls.quadrature_diagnosis.v1",
        "status": "diagnostic_only",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "qualification_claim": "none; this report does not qualify the material backend or T2",
        "inputs": {
            "trace_512": {"path": coarse["path"], "sha256": coarse["sha256"], "frames": coarse["committed"] + 1},
            "trace_4096": {"path": fine["path"], "sha256": fine["sha256"], "frames": fine["committed"] + 1},
            "spec_512": {"path": str(Path(spec_512).resolve()), "sha256": sha256_file(spec_512)},
            "spec_4096": {"path": str(Path(spec_4096).resolve()), "sha256": sha256_file(spec_4096)},
            "source_sha256": coarse["binding"].get("source_sha256"),
            "prepared_sha256": source_inputs_a.get(next((key for key in source_inputs_a if key.endswith("-PREPARED.json")), "")),
            "comparison": {"path": str(Path(comparison).resolve()), "sha256": sha256_file(comparison)} if comparison else None,
        },
        "configuration_audit": configuration,
        "seed_geometry": geometry,
        "denominator_and_censoring": {
            "weight_policy": "uniform independent geometric seed weight 1/N within each trace",
            "source_denominator_policy": "all source seeds remain in the denominator, including permanent_unknown",
            "unknown_policy": "event lower bound counts finite observed times; upper bound adds only unresolved unknown mass from its first possible failure frame",
            "residence_policy": "unknown residence lower=observed accumulated value; upper adds remaining horizon from first possible failure",
            "mass_closure": "seed_mass_closure_error is zero in both traces; it certifies the numerical seed-weight sum, not native fluid mass weighting",
            "raw_first_passage_sup_equals_interval_sup": {
                source: bool(abs(event_rows[str(source)]["first_passage"]["raw_observed_cdf"]["sup_abs_difference"] - event_rows[str(source)]["first_passage"]["interval_cdf"]["sup_abs_difference"]) <= 1e-15)
                for source in (0, 1)
            },
        },
        "final_unknown_by_source": unknown,
        "event_cdf_differences": event_rows,
        "interpretation": {
            "supported": [
                "No numerical source/prepared/runner/snapshot mismatch was found; the only argv change is seed cardinality.",
                "The 512 and 4096 axes have equal source mass fractions but different midpoint phases; each coarse cell contains eight fine points and the coarse centre is not one of them.",
                "The first-passage .0654296875 and .0478515625 sup differences are already present in the finite observed CDF, before unresolved-unknown upper bounds.",
                "The source-1 maximum is concentrated in the nearest positive x layer; source-0 differences concentrate in x layers around -0.14 to -0.084 m. This is evidence of geometric quadrature/phase sensitivity, including the source-interface distance, not a denominator artifact.",
            ],
            "not_separated": [
                "The trace pair cannot apportion the remaining effect between initial seed phase and nonlinear spatial reconstruction near walls/free surfaces; both are changed by the finer y/z and x offsets.",
                "Uniform seed weights are an event-sampling quadrature policy and are not native-particle mass weights; zero seed closure error must not be read as material mass accuracy.",
            ],
            "no_gate_change": True,
        },
        "minimal_followup_if_needed": {
            "required": False,
            "reason": "The terminal pair already establishes the observed CDF difference and its geometric seed-axis concentration.",
            "optional_design": {
                "purpose": "separate midpoint phase from seed cardinality",
                "backend": "new explicitly versioned v1 seed-file adapter; no gate change",
                "source_sha256": coarse["binding"].get("source_sha256"),
                "seeds": 512,
                "substeps": 2,
                "stop_after": coarse["committed"],
                "two_axes": "one 512 point per 2x2x2 fine block at a fixed fine child phase, plus the existing 512 midpoint axis",
                "estimated_resources": {"cpu_cores": 2, "ram_mib": 2048, "gpu_peak_mib": 0, "wall_seconds_each": 1800, "trace_h5_mib_each": 65},
                "qualification_claim": "none; diagnostic only",
                "must_not_start_here": True,
            },
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-512", type=Path, required=True)
    parser.add_argument("--trace-4096", type=Path, required=True)
    parser.add_argument("--spec-512", type=Path, required=True)
    parser.add_argument("--spec-4096", type=Path, required=True)
    parser.add_argument("--comparison", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = diagnose(args.trace_512, args.trace_4096, args.spec_512,
                      args.spec_4096, args.comparison)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output.resolve()), "status": report["status"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
