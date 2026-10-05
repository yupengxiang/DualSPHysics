#!/usr/bin/env python3
"""Read-only full801 shoreline/runup mechanism diagnostic for F5 C082S1.

Root enables this CPU audit only after binding the completed typed350/XMF351
products.  It reads the native H5 through h5py, preserves the complete
particle axis and actual H5 time axis, and writes diagnostic metrics around
the source Mk50 bed.  It does not alter particles, crop the reader, certify
runup, grant precision, or create case credit.

The wetness proxy is deliberately explicit: finite active native Type-3 fluid
rows inside the exact source bed x/y footprint and at or above the piecewise
linear Mk50 bed profile.  Shoreward is +x because the source bed rises toward
the final x nodes.  The surface proxy is the 95th percentile of z in the
sloped local wetness window; its frame-zero value is the initial reference,
not an equilibrium or physics acceptance claim.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

SCHEMA = "ds02.f5.c082s1.full801-shoreline-mechanism-diagnostic.fresh100.v1"
BINDING_SCHEMA = "ds02.f5.c082s1.full801-shoreline-mechanism-binding.fresh100.v1"
CASE_ID = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1"
PHYSICAL_CASE_ID = "F5_COMPACT_STILL_WATER_RUNUP_RECOVERY_C082S1"
CANONICAL_OWNER_SHA256 = "e691d030eda575b9cfabe62f295c9bdc142e5a04cb4357c9fe2790aaec549dbf"
SOURCE_PLAN_SHA256 = "5bad3ec9f9a71aa87da8272003c357f4523d4ffa164d3f06e5d25fee1a4fbfa6"
SOURCE_H5_SCOPE_SHA256 = "3cd1ceab16be11428bbc1011a1b4e297c384d8c7926432c222c254064744ccd0"
SOURCE_H5_SCOPE_SCHEMA = "legacy-owner-scope.v0"
FRAMES = 801
PARTICLES = 194427
FLUID_PARTICLES = 31658
FIXED_PARTICLES = 158559
MOVING_PARTICLES = 4210
FLOATING_PARTICLES = 0
FLUID_TYPE = 3
BED_MK = 50
SOURCE_MKBOUND = 40
DP_M = 0.02
TIME_ATOL_S = 1.0e-9
BED_NODES_XZ_M = np.asarray(
    (
        (-0.2, 0.0),
        (2.0, 0.0),
        (3.0, 0.28),
        (3.6, 0.448),
        (3.9, 0.448),
        (4.4, 0.05),
        (4.8, 0.05),
    ),
    dtype=np.float64,
)
BED_X_BOUNDS_M = (-0.2, 4.8)
BED_Y_BOUNDS_M = (-0.22, 0.22)
SLOPE_X_BOUNDS_M = (2.0, 4.4)
SEGMENTS = (
    (2.0, 3.0, "slope_2p0_3p0"),
    (3.0, 3.6, "slope_3p0_3p6"),
    (3.6, 3.9, "slope_3p6_3p9"),
    (3.9, 4.4, "slope_3p9_4p4"),
    (4.4, 4.8, "toe_4p4_4p8"),
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"JSON object required: {path}")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def bound_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value) and not value.startswith("<")


def uid_digest(values: np.ndarray) -> str:
    ordered = np.sort(np.asarray(values, dtype="<u8").reshape(-1), kind="stable")
    return hashlib.sha256(ordered.tobytes(order="C")).hexdigest()


def uid_summary(values: np.ndarray, sample_limit: int = 16) -> dict[str, Any]:
    ordered = np.sort(np.asarray(values, dtype=np.uint64).reshape(-1), kind="stable")
    return {
        "count": int(ordered.size),
        "sha256_sorted_uint64le": uid_digest(ordered),
        "sample_first": [int(v) for v in ordered[:sample_limit]],
        "sample_last": [int(v) for v in ordered[-sample_limit:]],
    }


def _load_module(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("ds02_root363_bed_worker", path)
    require(spec is not None and spec.loader is not None, f"cannot import worker: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _hash_metadata_records(binding: Mapping[str, Any]) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for entry in binding.get("metadata_records", []):
        require(isinstance(entry, Mapping), "metadata_records entries must be objects")
        path = Path(str(entry.get("path", ""))).resolve()
        expected = str(entry.get("sha256", ""))
        require(path.is_file(), f"metadata input missing: {path}")
        require(bound_text(expected), f"metadata input hash missing: {path}")
        actual = sha256_file(path)
        require(actual == expected, f"metadata input SHA mismatch: {path}")
        records.append({"role": str(entry.get("role", "")), "path": str(path), "sha256": actual})
    require(records, "fresh100 metadata_records are empty")
    return records


def _verify_root370(binding: Mapping[str, Any]) -> dict[str, Any]:
    path = Path(str(binding["root370_motion_audit"])).resolve()
    report = load_json(path)
    require(report.get("schema") == "ds02.root.f5.actual-full801-motion-trajectory-diagnostic.v1",
            "Root370 motion audit schema mismatch")
    require(report.get("status") == "completed" and report.get("diagnostic_only") is True,
            "Root370 motion audit is not completed diagnostic metadata")
    require(report.get("full_visual_runup_event_not_granted") is True,
            "Root370 visual runup hold was removed")
    require(report.get("precision_not_granted") is True and report.get("case_increment") == 0,
            "Root370 precision/case boundary changed")
    rows = report.get("frames")
    require(isinstance(rows, list) and len(rows) == FRAMES, "Root370 does not contain all 801 frame metadata")
    by_frame = {int(row["frame"]): row for row in rows if isinstance(row, Mapping) and "frame" in row}
    require(len(by_frame) == FRAMES, "Root370 frame metadata is not one-to-one")
    focus = []
    for item in binding["focus_frame_evidence"]:
        frame = int(item["frame"])
        require(frame in by_frame, f"Root370 focus frame missing: {frame}")
        row = by_frame[frame]
        require(abs(float(row["time_s"]) - float(item["time_s"])) <= 2.0e-6,
                f"Root370 focus time mismatch at frame {frame}")
        focus.append({
            "frame": frame,
            "time_s_from_root370": float(row["time_s"]),
            "reason": str(item["reason"]),
            "root370_metric": str(item["metric"]),
            "root370_value": float(row[str(item["metric"])]),
        })
    return {
        "path": str(path),
        "schema": report["schema"],
        "control_rows": int(report["control_rows"]),
        "control_x_peak_to_peak_m": float(report["control_x_peak_to_peak_m"]),
        "moving_saved_displacement_max_m": float(report["moving_saved_displacement_max_m"]),
        "fluid_saved_displacement_max_m": float(report["fluid_saved_displacement_max_m"]),
        "focus_frames": focus,
        "visual_runup_event_granted": False,
        "precision_granted": False,
        "case_increment": 0,
    }


def _verify_binding(binding: Mapping[str, Any], h5_path: Path, xdmf_path: Path) -> dict[str, Any]:
    require(binding.get("schema") == BINDING_SCHEMA, "fresh100 binding schema mismatch")
    require(binding.get("case_id") == CASE_ID and binding.get("physical_case_id") == PHYSICAL_CASE_ID,
            "fresh100 case identity mismatch")
    require(binding.get("expected_dimension") == 3 and binding.get("expected_frames") == FRAMES,
            "fresh100 dimension/frame contract mismatch")
    counts = binding.get("expected_counts", {})
    require(counts == {
        "total": PARTICLES,
        "fixed": FIXED_PARTICLES,
        "moving": MOVING_PARTICLES,
        "fluid": FLUID_PARTICLES,
        "floating": FLOATING_PARTICLES,
    }, "fresh100 actual counts mismatch")
    require(binding.get("native_bed_marker_mk") == BED_MK and binding.get("source_mkbound") == SOURCE_MKBOUND,
            "fresh100 Mk mapping mismatch")
    require(binding.get("physical_condition_sha256") == CANONICAL_OWNER_SHA256,
            "fresh100 canonical owner mismatch")
    require(binding.get("source_plan_physical_condition_sha256") == SOURCE_PLAN_SHA256,
            "fresh100 source plan identity mismatch")
    require(binding.get("source_h5_physical_condition_sha256") == SOURCE_H5_SCOPE_SHA256,
            "fresh100 H5 legacy scope mismatch")
    require(binding.get("source_h5_scope_schema") == SOURCE_H5_SCOPE_SCHEMA,
            "fresh100 H5 scope schema mismatch")
    require(binding.get("trajectory_h5") == str(h5_path), "CLI H5 path does not match binding")
    require(binding.get("xdmf") == str(xdmf_path), "CLI XDMF path does not match binding")
    require(bound_text(binding.get("trajectory_h5_sha256")), "producer H5 SHA is missing")
    require(bound_text(binding.get("xdmf_sha256")), "XDMF SHA is missing")

    base_binding_path = Path(str(binding["base_bed_binding"])).resolve()
    base_worker_path = Path(str(binding["base_bed_worker"])).resolve()
    require(base_binding_path.is_file() and base_worker_path.is_file(), "Root363 base binding/worker missing")
    require(sha256_file(base_binding_path) == binding["base_bed_binding_sha256"],
            "Root363 base binding SHA mismatch")
    require(sha256_file(base_worker_path) == binding["base_bed_worker_sha256"],
            "Root363 base worker SHA mismatch")
    base_worker = _load_module(base_worker_path)
    base_binding = load_json(base_binding_path)
    base_meta = base_worker._verify_bound_metadata(base_binding)
    require(base_binding.get("trajectory_h5") == str(h5_path), "Root363 H5 binding differs from fresh100")
    require(base_binding.get("xdmf") == str(xdmf_path), "Root363 XDMF binding differs from fresh100")

    records = _hash_metadata_records(binding)
    root370 = _verify_root370(binding)
    require(Path(str(binding["root363_report"])).is_file(), "Root363 report path missing")
    root363_report = load_json(Path(str(binding["root363_report"])))
    require(root363_report.get("schema") == "ds02.f5.c082s1.full-event-bed-footprint-audit.fresh098.v1",
            "Root363 report schema mismatch")
    require(root363_report.get("status") == "completed_worker_output_pending_root_review",
            "Root363 report status/lineage changed")
    require(root363_report.get("scan", {}).get("frames_scanned") == FRAMES,
            "Root363 report is not full801")
    require(root363_report.get("source_arrays_modified") is False and
            root363_report.get("source_arrays_dropped_or_masked") is False,
            "Root363 source-array boundary changed")

    focus_indices = [int(item["frame"]) for item in binding["focus_frame_evidence"]]
    require(len(focus_indices) == len(set(focus_indices)), "focus frames are duplicated")
    require(all(0 <= frame < FRAMES for frame in focus_indices), "focus frame outside 801 range")
    profile = binding.get("bed_profile_nodes_xz_m")
    require(profile == [list(map(float, row)) for row in BED_NODES_XZ_M.tolist()],
            "fresh100 bed profile differs from Root363")
    require(binding.get("bed_x_bounds_m") == list(BED_X_BOUNDS_M) and
            binding.get("bed_y_bounds_m") == list(BED_Y_BOUNDS_M),
            "fresh100 bed domain differs from Root363")
    return {
        "base_binding": str(base_binding_path),
        "base_worker": str(base_worker_path),
        "base_metadata": base_meta,
        "metadata_records": records,
        "root363": {
            "path": str(Path(str(binding["root363_report"])).resolve()),
            "sha256": str(binding["root363_report_sha256"]),
            "frames_scanned": FRAMES,
        },
        "root370": root370,
        "focus_indices": focus_indices,
    }


def _dataset(handle: Any, base_worker: Any, name: str) -> Any:
    return base_worker._dataset(handle, name)


def bed_profile_z(x: np.ndarray, nodes: np.ndarray) -> np.ndarray:
    values = np.asarray(x, dtype=np.float64)
    flat = values.reshape(-1)
    result = np.full(flat.shape, np.nan, dtype=np.float64)
    inside = (flat >= BED_X_BOUNDS_M[0]) & (flat <= BED_X_BOUNDS_M[1])
    result[inside] = np.interp(flat[inside], nodes[:, 0], nodes[:, 1])
    return result.reshape(values.shape)


def finite_bounds(points: np.ndarray) -> dict[str, list[float] | None]:
    if points.size == 0:
        return {"min_m": None, "max_m": None}
    return {
        "min_m": [float(v) for v in np.min(points, axis=0)],
        "max_m": [float(v) for v in np.max(points, axis=0)],
    }


def _unique_difference(expected: np.ndarray, observed: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    expected_set = set(int(v) for v in expected)
    observed_set = set(int(v) for v in observed)
    missing = np.asarray(sorted(expected_set - observed_set), dtype=np.uint64)
    unexpected = np.asarray(sorted(observed_set - expected_set), dtype=np.uint64)
    return missing, unexpected


def _percentile_or_none(values: np.ndarray, percentile: float) -> float | None:
    if values.size == 0:
        return None
    return float(np.percentile(values, percentile))


def segment_report(
    x: np.ndarray,
    y: np.ndarray,
    z: np.ndarray,
    wet: np.ndarray,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, (low, high, label) in enumerate(SEGMENTS):
        right_inclusive = index == len(SEGMENTS) - 1
        interval = wet & (x >= low) & ((x <= high) if right_inclusive else (x < high))
        selected = np.flatnonzero(interval)
        rows.append({
            "label": label,
            "x_bounds_m": [low, high],
            "right_endpoint_inclusive": right_inclusive,
            "wet_fluid_uid_count": int(selected.size),
            "shoreward_reach_x_m": float(np.max(x[selected])) if selected.size else None,
            "surface_proxy_z95_m": _percentile_or_none(z[selected], 95.0),
            "y_bounds_m": (
                [float(np.min(y[selected])), float(np.max(y[selected]))]
                if selected.size else None
            ),
        })
    return rows


def frame_diagnostic(
    *,
    frame: int,
    time_s: float,
    positions: np.ndarray,
    valid: np.ndarray,
    particle_type: np.ndarray,
    particle_ids: np.ndarray,
    initial_fluid_ids: np.ndarray,
    initial_fluid_z_by_id: np.ndarray,
    initial_ids_sorted: np.ndarray,
    nodes: np.ndarray,
) -> dict[str, Any]:
    pos = np.asarray(positions, dtype=np.float64)
    valid_array = np.asarray(valid).reshape(-1).astype(bool, copy=False)
    type_array = np.asarray(particle_type).reshape(-1)
    ids = np.asarray(particle_ids, dtype=np.uint64).reshape(-1)
    require(pos.ndim == 2 and pos.shape == (PARTICLES, 3), f"frame {frame} position shape mismatch")
    require(valid_array.size == PARTICLES and type_array.size == PARTICLES and ids.size == PARTICLES,
            f"frame {frame} particle axis mismatch")
    require(np.unique(ids).size == PARTICLES, f"frame {frame} particle IDs are not unique")

    finite_position = np.isfinite(pos).all(axis=1)
    active_fluid = valid_array & (type_array == FLUID_TYPE)
    finite_fluid = active_fluid & finite_position
    fluid_ids = ids[active_fluid]
    missing, unexpected = _unique_difference(initial_fluid_ids, fluid_ids)
    initial_uid_rows = np.isin(ids, initial_fluid_ids)
    nonfinite_initial = initial_uid_rows & ~finite_position
    initial_uid_not_fluid = initial_uid_rows & ~active_fluid
    x, y, z = pos[:, 0], pos[:, 1], pos[:, 2]
    x_in_profile = finite_fluid & (x >= BED_X_BOUNDS_M[0]) & (x <= BED_X_BOUNDS_M[1])
    y_in_footprint = finite_fluid & (y >= BED_Y_BOUNDS_M[0]) & (y <= BED_Y_BOUNDS_M[1])
    footprint = x_in_profile & y_in_footprint
    profile = np.full(PARTICLES, np.nan, dtype=np.float64)
    profile[x_in_profile] = bed_profile_z(x[x_in_profile], nodes)
    depth_below_bed = profile - z
    above_bed = finite_fluid & np.isfinite(profile) & (z >= profile)
    local = above_bed & (x >= BED_X_BOUNDS_M[0]) & (x <= BED_X_BOUNDS_M[1]) & (
        y >= BED_Y_BOUNDS_M[0]) & (y <= BED_Y_BOUNDS_M[1])
    slope_surface = local & (x >= SLOPE_X_BOUNDS_M[0]) & (x <= SLOPE_X_BOUNDS_M[1])

    local_indices = np.flatnonzero(local)
    wet_x = x[local]
    wet_y = y[local]
    wet_z = z[local]
    surface_values = z[slope_surface]
    current_ids = fluid_ids
    current_uid_summary = uid_summary(current_ids)
    missing_summary = uid_summary(missing)
    unexpected_summary = uid_summary(unexpected)

    local_ids = ids[local]
    local_matches = np.searchsorted(initial_ids_sorted, local_ids)
    local_match_ok = (
        (local_matches < initial_ids_sorted.size)
        & (initial_ids_sorted[np.minimum(local_matches, initial_ids_sorted.size - 1)] == local_ids)
    ) if local_ids.size else np.asarray([], dtype=bool)
    local_dz = (
        z[local] - initial_fluid_z_by_id[local_matches[local_match_ok]]
        if local_ids.size and local_match_ok.any() else np.asarray([], dtype=np.float64)
    )
    below = footprint & np.isfinite(depth_below_bed) & (depth_below_bed > 0.0)
    return {
        "frame": int(frame),
        "actual_time_s": float(time_s),
        "uid_tracking": {
            "initial_fluid_uid_count": int(initial_fluid_ids.size),
            "current_valid_type3_fluid_count": int(current_ids.size),
            "current_fluid_uid_summary": current_uid_summary,
            "missing_initial_fluid_uids": missing_summary,
            "unexpected_current_fluid_uids": unexpected_summary,
            "nonfinite_initial_fluid_uid_count": int(nonfinite_initial.sum()),
            "initial_uid_not_current_type3_count": int(initial_uid_not_fluid.sum()),
            "unexplained_uid_or_nonfinite_state": bool(
                missing.size or unexpected.size or nonfinite_initial.any() or initial_uid_not_fluid.any()
            ),
        },
        "finite_state": {
            "particle_axis_count": PARTICLES,
            "finite_current_type3_fluid_count": int(finite_fluid.sum()),
            "nonfinite_current_type3_position_count": int((active_fluid & ~finite_position).sum()),
            "finite_active_position_count": int((valid_array & finite_position).sum()),
            "all_active_positions_finite": bool(np.isfinite(pos[valid_array]).all()),
        },
        "bed_and_wetness": {
            "exact_profile_x_domain_m": list(BED_X_BOUNDS_M),
            "exact_bed_y_footprint_m": list(BED_Y_BOUNDS_M),
            "native_bed_mk": BED_MK,
            "source_mkbound": SOURCE_MKBOUND,
            "finite_fluid_in_exact_footprint_count": int(footprint.sum()),
            "fluid_above_or_on_profile_count": int(local.sum()),
            "fluid_below_profile_count": int(below.sum()),
            "deepest_below_profile_m": float(np.max(depth_below_bed[below])) if below.any() else None,
            "wetness_definition": (
                "finite active native Type-3 rows in exact bed x/y footprint with "
                "z >= piecewise-linear Mk50 bed_profile_z(x)"
            ),
            "wet_extent_m": finite_bounds(np.column_stack((wet_x, wet_y, wet_z)) if local_indices.size else np.empty((0, 3))),
            "wet_fluid_uid_count": int(local.sum()),
            "wet_fraction_of_initial_fluid_uid_set": float(local.sum()) / float(initial_fluid_ids.size),
            "shoreward_direction": "+x along the source bed profile",
            "shoreward_reach_x_m": float(np.max(wet_x)) if wet_x.size else None,
            "shoreward_reach_x_min_m": float(np.min(wet_x)) if wet_x.size else None,
            "slope_window_x_m": list(SLOPE_X_BOUNDS_M),
            "surface_proxy_definition": (
                "95th percentile of z for finite active Type-3 rows above/on the "
                "profile in slope window x=2.0..4.4 m and y=-0.22..0.22 m"
            ),
            "surface_proxy_z95_m": _percentile_or_none(surface_values, 95.0),
            "surface_proxy_zmax_m": float(np.max(surface_values)) if surface_values.size else None,
            "surface_proxy_sample_count": int(surface_values.size),
            "local_vertical_displacement_proxy": {
                "definition": "current z minus frame-zero z for matching stable UIDs in the local wet set",
                "matched_uid_count": int(local_dz.size),
                "max_abs_m": float(np.max(np.abs(local_dz))) if local_dz.size else None,
                "p95_abs_m": _percentile_or_none(np.abs(local_dz), 95.0),
                "max_positive_m": float(np.max(local_dz)) if local_dz.size else None,
                "min_negative_m": float(np.min(local_dz)) if local_dz.size else None,
            },
            "segment_reports": segment_report(wet_x, wet_y, wet_z, np.ones(wet_x.size, dtype=bool)),
        },
        "diagnostic_boundary": {
            "penetration_thresholds_are_not_used": True,
            "runup_acceptance": "not evaluated",
            "precision_status": "not granted",
            "case_credit": 0,
        },
    }


def _add_frame_zero_deltas(rows: list[dict[str, Any]]) -> dict[str, Any]:
    require(rows, "no frame reports")
    baseline = rows[0]
    base_wet = baseline["bed_and_wetness"]
    base_reach = base_wet["shoreward_reach_x_m"]
    base_surface = base_wet["surface_proxy_z95_m"]
    for row in rows:
        metrics = row["bed_and_wetness"]
        reach = metrics["shoreward_reach_x_m"]
        surface = metrics["surface_proxy_z95_m"]
        row["relative_to_frame_zero"] = {
            "frame_zero_reference_semantics": (
                "frame 0 is the initial still-water candidate reference only; "
                "this worker does not certify equilibrium"
            ),
            "shoreward_reach_delta_m": (
                None if reach is None or base_reach is None else float(reach - base_reach)
            ),
            "surface_proxy_amplitude_delta_m": (
                None if surface is None or base_surface is None else float(surface - base_surface)
            ),
            "wet_fluid_uid_count_delta": int(
                metrics["wet_fluid_uid_count"] - base_wet["wet_fluid_uid_count"]
            ),
        }
    return {
        "frame": 0,
        "actual_time_s": float(baseline["actual_time_s"]),
        "wet_fluid_uid_count": int(base_wet["wet_fluid_uid_count"]),
        "shoreward_reach_x_m": base_reach,
        "surface_proxy_z95_m": base_surface,
        "surface_proxy_zmax_m": base_wet["surface_proxy_zmax_m"],
        "initial_reference_is_not_equilibrium_certificate": True,
    }


def run_worker(binding_path: Path, trajectory_h5: Path, xdmf: Path, output_dir: Path) -> dict[str, Any]:
    binding = load_json(binding_path)
    verified = _verify_binding(binding, trajectory_h5.resolve(), xdmf.resolve())
    base_worker = _load_module(Path(verified["base_worker"]))
    import h5py

    expected_h5_sha = str(binding["trajectory_h5_sha256"])
    actual_h5_sha = sha256_file(trajectory_h5)
    require(actual_h5_sha == expected_h5_sha, "typed350 H5 producer SHA mismatch")
    actual_xdmf_sha = sha256_file(xdmf)
    require(actual_xdmf_sha == str(binding["xdmf_sha256"]), "XMF SHA mismatch")
    xdmf_times = base_worker._parse_xdmf_times(xdmf)
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    runtime_names = {"stdout.log", "execution-receipt.json"}
    prior = [
        path.name for path in output_dir.iterdir()
        if path.name not in runtime_names and not path.name.startswith("execution-receipt.json.")
    ]
    require(not prior, f"diagnostic output directory contains prior artifacts: {prior}")
    nodes = BED_NODES_XZ_M.copy()

    with h5py.File(trajectory_h5, "r") as handle:
        source_scope = str(handle.attrs.get("physical_condition_sha256", ""))
        require(source_scope == SOURCE_H5_SCOPE_SHA256, "H5 legacy scope differs from binding")
        positions_ds = _dataset(handle, base_worker, "position")
        valid_ds = _dataset(handle, base_worker, "valid")
        type_ds = _dataset(handle, base_worker, "type")
        ids_ds = _dataset(handle, base_worker, "particle_id")
        time_ds = None
        for candidate in ("/time", "/times", "/Time"):
            try:
                time_ds = _dataset(handle, base_worker, candidate)
                break
            except KeyError:
                continue
        require(time_ds is not None, "H5 actual time dataset missing")
        times = np.asarray(time_ds[...], dtype=np.float64).reshape(-1)
        xdmf_time_report = base_worker._check_time_axes(times, xdmf_times)
        require(positions_ds.shape == (FRAMES, PARTICLES, 3),
                f"position dataset shape mismatch: {positions_ds.shape}")
        require(valid_ds.shape == (FRAMES, PARTICLES) and type_ds.shape == (FRAMES, PARTICLES),
                "valid/type dataset shape mismatch")
        ids = np.asarray(ids_ds[...]).reshape(-1).astype(np.uint64)
        require(ids.size == PARTICLES and np.unique(ids).size == PARTICLES,
                "particle_id is not a stable unique axis")
        frame0_positions = np.asarray(positions_ds[0, ...], dtype=np.float64)
        frame0_valid = np.asarray(valid_ds[0, ...]).reshape(-1).astype(bool, copy=False)
        frame0_type = np.asarray(type_ds[0, ...]).reshape(-1)
        initial_mask = frame0_valid & (frame0_type == FLUID_TYPE)
        initial_ids = ids[initial_mask]
        require(initial_ids.size == FLUID_PARTICLES and np.unique(initial_ids).size == FLUID_PARTICLES,
                "frame-zero Type-3 UID count mismatch")
        initial_sorted_order = np.argsort(initial_ids, kind="stable")
        initial_ids_sorted = initial_ids[initial_sorted_order]
        initial_z_sorted = frame0_positions[initial_mask, 2][initial_sorted_order]
        frame_reports: list[dict[str, Any]] = []
        for frame in range(FRAMES):
            position = np.asarray(positions_ds[frame, ...], dtype=np.float64)
            valid = np.asarray(valid_ds[frame, ...])
            particle_type = np.asarray(type_ds[frame, ...])
            frame_reports.append(frame_diagnostic(
                frame=frame,
                time_s=float(times[frame]),
                positions=position,
                valid=valid,
                particle_type=particle_type,
                particle_ids=ids,
                initial_fluid_ids=initial_ids,
                initial_fluid_z_by_id=initial_z_sorted,
                initial_ids_sorted=initial_ids_sorted,
                nodes=nodes,
            ))

    initial_reference = _add_frame_zero_deltas(frame_reports)
    focus_indices = verified["focus_indices"]
    focus_reports = [frame_reports[index] for index in focus_indices]
    max_wet = max((r["bed_and_wetness"]["wet_fluid_uid_count"] for r in frame_reports), default=0)
    max_reach = max(
        (r["bed_and_wetness"]["shoreward_reach_x_m"] for r in frame_reports
         if r["bed_and_wetness"]["shoreward_reach_x_m"] is not None),
        default=None,
    )
    max_surface_amp = max(
        (abs(r["relative_to_frame_zero"]["surface_proxy_amplitude_delta_m"])
         for r in frame_reports
         if r["relative_to_frame_zero"]["surface_proxy_amplitude_delta_m"] is not None),
        default=None,
    )
    report = {
        "schema": SCHEMA,
        "status": "completed",
        "diagnostic_only": True,
        "case_id": CASE_ID,
        "physical_case_id": PHYSICAL_CASE_ID,
        "physical_condition_sha256": CANONICAL_OWNER_SHA256,
        "source_plan_physical_condition_sha256": SOURCE_PLAN_SHA256,
        "source_h5_physical_condition_sha256": SOURCE_H5_SCOPE_SHA256,
        "physical_condition_hash_semantics": {
            "canonical_owner_sha256": CANONICAL_OWNER_SHA256,
            "source_plan_sha256": SOURCE_PLAN_SHA256,
            "source_h5_sha256": SOURCE_H5_SCOPE_SHA256,
            "source_h5_scope_schema": SOURCE_H5_SCOPE_SCHEMA,
            "cross_resolution_claim": False,
        },
        "bound_metadata": verified,
        "source": {
            "trajectory_h5": str(trajectory_h5),
            "trajectory_h5_sha256": actual_h5_sha,
            "xdmf": str(xdmf),
            "xdmf_sha256": actual_xdmf_sha,
            "datasets_read": ["position", "valid", "type", "particle_id", "time"],
            "source_arrays_modified": False,
            "source_arrays_dropped_or_masked": False,
        },
        "time_axis": xdmf_time_report,
        "bed_profile": {
            "native_bed_mk": BED_MK,
            "source_mkbound": SOURCE_MKBOUND,
            "dp_m": DP_M,
            "nodes_xz_m": BED_NODES_XZ_M.tolist(),
            "x_bounds_m": list(BED_X_BOUNDS_M),
            "y_bounds_m": list(BED_Y_BOUNDS_M),
            "shoreward_direction": "+x",
        },
        "initial_reference": initial_reference,
        "focus_frame_indices": focus_indices,
        "focus_frame_reports": focus_reports,
        "summary": {
            "frames_scanned": FRAMES,
            "initial_fluid_uid_count": FLUID_PARTICLES,
            "particle_axis_count": PARTICLES,
            "max_wet_fluid_uid_count": int(max_wet),
            "max_shoreward_reach_x_m": max_reach,
            "max_abs_surface_proxy_amplitude_delta_m": max_surface_amp,
            "full_event_runup_acceptance": "not evaluated",
            "full_event_visual_coverage": "not granted",
            "precision_granted": False,
            "independent_case_count_increment": 0,
        },
        "frame_reports": frame_reports,
        "interpretation_boundary": {
            "definition": "local wetness/surface proxies against exact source bed profile",
            "initial_static_comparison": "all deltas are relative to frame 0 only",
            "stable_uid_policy": "frame-zero Type-3 UID set remains the denominator; missing/nonfinite/type changes are reported",
            "actual_time_policy": "H5 time dataset and XDMF Time values are checked; no equal-spacing assumption",
            "no_acceptance_inference": True,
            "no_threshold_relaxation": True,
            "no_wave_label_certification": True,
        },
        "science_inputs_read_only": True,
        "science_arrays_hashed_by_source_agent": False,
        "precision_not_granted": True,
        "case_increment": 0,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "c082s1-full801-shoreline-mechanism-diagnostic.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "schema": SCHEMA,
        "status": "completed",
        "frames_scanned": FRAMES,
        "focus_frame_indices": focus_indices,
        "full_event_runup_acceptance": "not evaluated",
        "precision_granted": False,
        "case_increment": 0,
    }, sort_keys=True), flush=True)
    return report


def synthetic_check() -> None:
    nodes = BED_NODES_XZ_M.copy()
    pos = np.asarray(
        [[2.2, 0.0, 0.10], [3.2, 0.0, 0.40], [0.0, 0.0, 0.0]],
        dtype=np.float64,
    )
    report = frame_diagnostic(
        frame=0,
        time_s=0.0,
        positions=np.pad(pos, ((0, PARTICLES - len(pos)), (0, 0))),
        valid=np.pad(np.asarray([1, 1, 0], dtype=np.uint8), (0, PARTICLES - 3)),
        particle_type=np.pad(np.asarray([3, 3, 0], dtype=np.int32), (0, PARTICLES - 3)),
        particle_ids=np.arange(PARTICLES, dtype=np.uint64),
        initial_fluid_ids=np.asarray([0, 1], dtype=np.uint64),
        initial_fluid_z_by_id=np.asarray([0.10, 0.40], dtype=np.float64),
        initial_ids_sorted=np.asarray([0, 1], dtype=np.uint64),
        nodes=nodes,
    )
    require(report["bed_and_wetness"]["wet_fluid_uid_count"] == 2, "synthetic wetness check failed")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", type=Path, required=False)
    parser.add_argument("--trajectory-h5", type=Path, required=False)
    parser.add_argument("--xdmf", type=Path, required=False)
    parser.add_argument("--output-dir", type=Path, required=False)
    parser.add_argument("--synthetic-check", action="store_true")
    args = parser.parse_args(argv)
    if args.synthetic_check:
        synthetic_check()
        print("synthetic-check: pass")
        return 0
    require(args.binding and args.trajectory_h5 and args.xdmf and args.output_dir,
            "binding, trajectory-h5, xdmf and output-dir are required")
    run_worker(args.binding.resolve(), args.trajectory_h5.resolve(), args.xdmf.resolve(), args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
