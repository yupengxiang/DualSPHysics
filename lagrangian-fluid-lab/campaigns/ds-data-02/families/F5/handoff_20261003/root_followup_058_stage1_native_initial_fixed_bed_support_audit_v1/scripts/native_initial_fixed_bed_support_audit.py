#!/usr/bin/env python3
"""Bounded native initial fixed-bed support audit for F5.

This source-only handoff prepares a future Root-authorized worker.  Importing
the module or running ``--check`` uses only small in-memory synthetic arrays;
it does not open the bound H5/BI4/CSV sources, run GenCase or DualSPHysics,
or render a scene.

The authorized worker reads selected frames (default 0 and 400) from the
immutable original013 typed H5.  The canonical typed identity is the
``(particle_zone, particle_id)`` namespace plus the generated XML particle
ranges; an explicit native ``mk`` dataset is optional.  The worker therefore
derives the mk=40 bed cohort from the generated XML ``<particles>`` ranges,
audits valid Type-0 fixed rows against the exact continuous-bed profile, and
compares an optional native marker when one is present.  If the native marker
is absent, the full XML-derived Type-0 support cohort is retained and the
report says so explicitly.  It reports x bins, each continuous-bed segment, a
near-mid-y strip, relative particle layers, UID/mass/z/profile-distance
records, and static Gen050/XML/Def050/STL/GenCase provenance.  Every result is
diagnostic evidence; it does not infer a solver root cause or authorize a
repair.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np


SCHEMA = "ds02.f5.stage1.native-initial-fixed-bed-support-audit.v1"
FIXED_TYPE = 0
BED_MARKER = 40
DP_M = 0.02
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
BED_X_BOUNDS_M = (float(BED_NODES_XZ_M[0, 0]), float(BED_NODES_XZ_M[-1, 0]))
BED_Y_BOUNDS_M = (-0.15, 0.15)
MID_Y_HALF_WIDTH_M = DP_M / 2.0
DEPTH_TOLERANCES_M = (0.02, 0.04)
EXPECTED_FRAMES = 801
EXPECTED_PARTICLE_AXIS = 214515
TIME_DATASET_CANDIDATES = ("/time", "/times", "/Time")
ZONE_DATASET_CANDIDATES = ("/particle_zone", "/zone", "/Zone")
TYPE_DATASET_CANDIDATES = ("/type", "/initial_type")
MASS_DATASET_CANDIDATES = ("/mass", "/initial_mass")
MARKER_DATASET_CANDIDATES = (
    "/mk",
    "/initial_mk",
    "/marker",
    "/mkcode",
    "/marker_code",
)
DEFAULT_AUDIT_FRAMES = (0, 400)
DEFAULT_SAMPLE_LIMIT = 10


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path, chunk_bytes: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            block = stream.read(chunk_bytes)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def bed_profile_z(x: np.ndarray | Sequence[float] | float) -> np.ndarray:
    values = np.asarray(x, dtype=np.float64)
    flat = values.reshape(-1)
    result = np.full(flat.shape, np.nan, dtype=np.float64)
    inside = (flat >= BED_X_BOUNDS_M[0]) & (flat <= BED_X_BOUNDS_M[1])
    result[inside] = np.interp(
        flat[inside], BED_NODES_XZ_M[:, 0], BED_NODES_XZ_M[:, 1]
    )
    return result.reshape(values.shape)


def uid_digest(ids: np.ndarray | Sequence[int]) -> str:
    values = np.asarray(ids, dtype="<u8").reshape(-1)
    return sha256_bytes(np.sort(values, kind="stable").tobytes(order="C"))


def _fraction(numerator: int, denominator: int) -> float | None:
    return float(numerator) / float(denominator) if denominator else None


def _extrema(points: np.ndarray) -> dict[str, list[float] | None]:
    if points.size == 0:
        return {"min_m": None, "max_m": None}
    return {
        "min_m": [float(value) for value in np.min(points, axis=0)],
        "max_m": [float(value) for value in np.max(points, axis=0)],
    }


def _sample_rows(
    indices: np.ndarray,
    positions: np.ndarray,
    markers: np.ndarray,
    profile_z: np.ndarray,
    distances: np.ndarray,
    masses: np.ndarray,
    particle_ids: np.ndarray,
    limit: int,
) -> list[dict[str, Any]]:
    if indices.size == 0:
        return []
    order = indices[np.argsort(distances[indices], kind="stable")[::-1][:limit]]
    rows: list[dict[str, Any]] = []
    for rank, index in enumerate(order, start=1):
        marker_value = float(markers[index])
        marker = (
            None
            if not math.isfinite(marker_value)
            else int(marker_value)
            if marker_value.is_integer()
            else marker_value
        )
        mass_value = float(masses[index])
        rows.append(
            {
                "rank": rank,
                "particle_id": int(particle_ids[index]),
                "mk": marker,
                "x_m": float(positions[index, 0]),
                "y_m": float(positions[index, 1]),
                "z_m": float(positions[index, 2]),
                "bed_z_m": float(profile_z[index]),
                "bed_minus_particle_z_m": float(distances[index]),
                "mass_kg": mass_value if math.isfinite(mass_value) else None,
            }
        )
    return rows


def _mask_summary(
    *,
    mask: np.ndarray,
    positions: np.ndarray,
    markers: np.ndarray,
    profile_z: np.ndarray,
    distances: np.ndarray,
    masses: np.ndarray,
    particle_ids: np.ndarray,
    denominator: int,
    sample_limit: int,
) -> dict[str, Any]:
    mass_finite = np.isfinite(masses)
    indices = np.flatnonzero(mask)
    finite_mass = mask & mass_finite
    return {
        "count": int(mask.sum()),
        "fraction_of_fixed_valid_native": _fraction(int(mask.sum()), denominator),
        "mass_sum_finite_kg": float(masses[finite_mass].sum()),
        "mass_nonfinite_count": int((mask & ~mass_finite).sum()),
        "uid_digest_sorted_uint64le_sha256": uid_digest(particle_ids[mask]),
        "coordinate_extrema_m": _extrema(positions[mask]),
        "deepest_profile_distance_samples": _sample_rows(
            indices,
            positions,
            markers,
            profile_z,
            distances,
            masses,
            particle_ids,
            sample_limit,
        ),
    }


def _marker_label(value: Any) -> str:
    numeric = float(value)
    return str(int(numeric)) if numeric.is_integer() else str(numeric)


def _marker_histogram(
    *,
    mask: np.ndarray,
    markers: np.ndarray,
    positions: np.ndarray,
    masses: np.ndarray,
    particle_ids: np.ndarray,
    denominator: int,
) -> dict[str, Any]:
    values = markers[mask]
    output: dict[str, Any] = {}
    finite_values = values[np.isfinite(values)]
    if finite_values.size == 0:
        return output
    for value in np.unique(finite_values):
        selected = mask & np.isfinite(markers) & (markers == value)
        finite_mass = selected & np.isfinite(masses)
        label = _marker_label(value)
        output[label] = {
            "mk": int(float(value)) if float(value).is_integer() else float(value),
            "count": int(selected.sum()),
            "fraction_of_fixed_valid_native": _fraction(int(selected.sum()), denominator),
            "finite_position_count": int((selected & np.isfinite(positions).all(axis=1)).sum()),
            "mass_sum_finite_kg": float(masses[finite_mass].sum()),
            "uid_digest_sorted_uint64le_sha256": uid_digest(particle_ids[selected]),
            "coordinate_extrema_m": _extrema(positions[selected]),
        }
    return output


def _x_bin_records(
    *,
    mask: np.ndarray,
    positions: np.ndarray,
    markers: np.ndarray,
    profile_z: np.ndarray,
    distances: np.ndarray,
    masses: np.ndarray,
    particle_ids: np.ndarray,
    sample_limit: int,
) -> list[dict[str, Any]]:
    count = int(round((BED_X_BOUNDS_M[1] - BED_X_BOUNDS_M[0]) / DP_M))
    edges = np.linspace(BED_X_BOUNDS_M[0], BED_X_BOUNDS_M[1], count + 1)
    records: list[dict[str, Any]] = []
    for index in range(count):
        lower = edges[index]
        upper = edges[index + 1]
        in_bin = mask & (positions[:, 0] >= lower)
        in_bin &= positions[:, 0] < upper if index < count - 1 else positions[:, 0] <= upper
        summary = _mask_summary(
            mask=in_bin,
            positions=positions,
            markers=markers,
            profile_z=profile_z,
            distances=distances,
            masses=masses,
            particle_ids=particle_ids,
            denominator=int(mask.sum()),
            sample_limit=sample_limit,
        )
        records.append(
            {
                "bin_index": index,
                "x_min_m": float(lower),
                "x_max_m": float(upper),
                **summary,
            }
        )
    return records


def _bed_segment_records(
    *,
    mask: np.ndarray,
    positions: np.ndarray,
    markers: np.ndarray,
    profile_z: np.ndarray,
    distances: np.ndarray,
    masses: np.ndarray,
    particle_ids: np.ndarray,
    sample_limit: int,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, (lower, upper) in enumerate(zip(BED_NODES_XZ_M[:-1, 0], BED_NODES_XZ_M[1:, 0])):
        in_segment = mask & (positions[:, 0] >= lower)
        in_segment &= (
            positions[:, 0] < upper
            if index < len(BED_NODES_XZ_M) - 2
            else positions[:, 0] <= upper
        )
        records.append(
            {
                "segment_index": index,
                "x_min_m": float(lower),
                "x_max_m": float(upper),
                "bed_z_at_x_min_m": float(BED_NODES_XZ_M[index, 1]),
                "bed_z_at_x_max_m": float(BED_NODES_XZ_M[index + 1, 1]),
                **_mask_summary(
                    mask=in_segment,
                    positions=positions,
                    markers=markers,
                    profile_z=profile_z,
                    distances=distances,
                    masses=masses,
                    particle_ids=particle_ids,
                    denominator=int(mask.sum()),
                    sample_limit=sample_limit,
                ),
            }
        )
    return records


def _layer_records(
    *,
    mask: np.ndarray,
    layer_index: np.ndarray,
    positions: np.ndarray,
    markers: np.ndarray,
    profile_z: np.ndarray,
    distances: np.ndarray,
    masses: np.ndarray,
    particle_ids: np.ndarray,
    sample_limit: int,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for layer in sorted(int(value) for value in np.unique(layer_index[mask])):
        selected = mask & (layer_index == layer)
        records.append(
            {
                "relative_layer_index_dp": layer,
                "relative_layer_definition": "round((particle_z - continuous_bed_z(x)) / dp)",
                **_mask_summary(
                    mask=selected,
                    positions=positions,
                    markers=markers,
                    profile_z=profile_z,
                    distances=distances,
                    masses=masses,
                    particle_ids=particle_ids,
                    denominator=int(mask.sum()),
                    sample_limit=sample_limit,
                ),
            }
        )
    return records


def frame_metrics(
    *,
    frame_index: int,
    time_s: float,
    positions: np.ndarray,
    valid: np.ndarray,
    particle_type: np.ndarray,
    markers: np.ndarray | None,
    masses: np.ndarray,
    particle_ids: np.ndarray,
    bed_support_mask: np.ndarray | None = None,
    bed_support_source: str | None = None,
    sample_limit: int = DEFAULT_SAMPLE_LIMIT,
) -> dict[str, Any]:
    """Audit one selected native frame without changing any source arrays."""

    position_array = np.asarray(positions, dtype=np.float64)
    valid_array = np.asarray(valid).reshape(-1).astype(bool, copy=False)
    type_array = np.asarray(particle_type).reshape(-1)
    mass_array = np.asarray(masses, dtype=np.float64).reshape(-1)
    id_array = np.asarray(particle_ids).reshape(-1)
    if position_array.ndim != 2 or position_array.shape[1] != 3:
        raise ValueError("positions must have shape (particles, 3)")
    particle_count = position_array.shape[0]
    native_marker_available = markers is not None
    marker_array = (
        np.asarray(markers, dtype=np.float64).reshape(-1)
        if native_marker_available
        else np.full(particle_count, np.nan, dtype=np.float64)
    )
    for name, array in (
        ("valid", valid_array),
        ("particle_type", type_array),
        ("markers", marker_array),
        ("mass", mass_array),
        ("particle_ids", id_array),
    ):
        if array.shape[0] != particle_count:
            raise ValueError(f"{name} length does not match positions")

    fixed_valid = valid_array & (type_array == FIXED_TYPE)
    finite_position = np.isfinite(position_array).all(axis=1)
    fixed_finite = fixed_valid & finite_position
    if bed_support_mask is None:
        support_candidate = (
            fixed_valid & (marker_array == BED_MARKER)
            if native_marker_available
            else fixed_valid.copy()
        )
        support_source = bed_support_source or (
            "native_marker_mk40"
            if native_marker_available
            else "all_fixed_type0_spatial_support_no_native_marker"
        )
    else:
        support_candidate = np.asarray(bed_support_mask).reshape(-1).astype(bool, copy=False)
        if support_candidate.shape[0] != particle_count:
            raise ValueError("bed_support_mask length does not match positions")
        support_source = bed_support_source or "generated_xml_particle_range_mk40"
    support_valid = support_candidate & fixed_valid
    support_finite = support_valid & finite_position
    bed_marker_valid = fixed_valid & native_marker_available & (marker_array == BED_MARKER)
    bed_marker_finite = bed_marker_valid & finite_position
    x = position_array[:, 0]
    y = position_array[:, 1]
    z = position_array[:, 2]
    x_in_domain = support_finite & (x >= BED_X_BOUNDS_M[0]) & (x <= BED_X_BOUNDS_M[1])
    profile_z = np.full(particle_count, np.nan, dtype=np.float64)
    profile_z[x_in_domain] = bed_profile_z(x[x_in_domain])
    profile_distance = profile_z - z
    distance_evaluable = x_in_domain
    near_mid_y = support_finite & (np.abs(y) <= MID_Y_HALF_WIDTH_M)
    bed_y_width = support_finite & (y >= BED_Y_BOUNDS_M[0]) & (y <= BED_Y_BOUNDS_M[1])
    layers = np.zeros(particle_count, dtype=np.int64)
    layers[distance_evaluable] = np.rint(
        (z[distance_evaluable] - profile_z[distance_evaluable]) / DP_M
    ).astype(np.int64)
    finite_mass_fixed = fixed_valid & np.isfinite(mass_array)

    depth_bins: dict[str, Any] = {}
    for tolerance in DEPTH_TOLERANCES_M:
        key = f"{tolerance:.2f}m"
        below = distance_evaluable & (profile_distance > tolerance)
        depth_bins[key] = {
            "tolerance_m": tolerance,
            "interpretation": "diagnostic_geometry_bin_only",
            **_mask_summary(
                mask=below,
                positions=position_array,
                markers=marker_array,
                profile_z=profile_z,
                distances=profile_distance,
                masses=mass_array,
                particle_ids=id_array,
                denominator=int(distance_evaluable.sum()),
                sample_limit=sample_limit,
            ),
        }

    native_marker_comparison = {
        "available": native_marker_available,
        "expected_mk": BED_MARKER,
        "support_source": support_source,
        "xml_or_fallback_support_valid_count": int(support_valid.sum()),
        "native_mk40_valid_count": int(bed_marker_valid.sum())
        if native_marker_available
        else None,
        "native_mk40_finite_position_count": int(bed_marker_finite.sum())
        if native_marker_available
        else None,
        "native_mk40_inside_support_count": int((bed_marker_valid & support_candidate).sum())
        if native_marker_available
        else None,
        "support_without_native_mk40_count": int((support_valid & ~bed_marker_valid).sum())
        if native_marker_available
        else None,
        "native_mk40_outside_support_count": int((bed_marker_valid & ~support_candidate).sum())
        if native_marker_available
        else None,
        "interpretation": (
            "native mk40 is compared with the generated XML particle-range cohort"
            if native_marker_available
            else "native mk dataset absent; XML-derived Type-0 support cohort retained"
        ),
    }

    return {
        "frame": int(frame_index),
        "time_s": float(time_s),
        "particle_axis_count": int(particle_count),
        "valid_count": int(valid_array.sum()),
        "fixed_type0_valid_count": int(fixed_valid.sum()),
        "fixed_type0_nonfinite_position_count": int((fixed_valid & ~finite_position).sum()),
        "fixed_type0_finite_position_count": int(fixed_finite.sum()),
        "fixed_type0_valid_uid_digest_sorted_uint64le_sha256": uid_digest(id_array[fixed_valid]),
        "fixed_type0_finite_uid_digest_sorted_uint64le_sha256": uid_digest(id_array[fixed_finite]),
        "bed_support_source": support_source,
        "bed_support_valid_count": int(support_valid.sum()),
        "bed_support_finite_position_count": int(support_finite.sum()),
        "bed_support_outside_x_domain_finite_count": int((support_finite & ~x_in_domain).sum()),
        "bed_support_uid_digest_sorted_uint64le_sha256": uid_digest(id_array[support_valid]),
        "bed_marker": BED_MARKER,
        "native_marker_available": native_marker_available,
        "bed_marker_valid_count": int(bed_marker_valid.sum()) if native_marker_available else None,
        "bed_marker_finite_position_count": int(bed_marker_finite.sum())
        if native_marker_available
        else None,
        "bed_marker_outside_x_domain_finite_count": int(
            (bed_marker_finite & ~((x >= BED_X_BOUNDS_M[0]) & (x <= BED_X_BOUNDS_M[1]))).sum()
        )
        if native_marker_available
        else None,
        "bed_marker_uid_digest_sorted_uint64le_sha256": uid_digest(id_array[bed_marker_valid])
        if native_marker_available
        else None,
        "bed_marker_finite_uid_digest_sorted_uint64le_sha256": uid_digest(id_array[bed_marker_finite])
        if native_marker_available
        else None,
        "bed_marker_native_presence": _mask_summary(
            mask=bed_marker_finite,
            positions=position_array,
            markers=marker_array,
            profile_z=profile_z,
            distances=profile_distance,
            masses=mass_array,
            particle_ids=id_array,
            denominator=int(fixed_valid.sum()),
            sample_limit=sample_limit,
        ),
        "bed_support_native_presence": _mask_summary(
            mask=support_finite,
            positions=position_array,
            markers=marker_array,
            profile_z=profile_z,
            distances=profile_distance,
            masses=mass_array,
            particle_ids=id_array,
            denominator=int(fixed_valid.sum()),
            sample_limit=sample_limit,
        ),
        "native_marker_comparison": native_marker_comparison,
        "near_mid_y_strip": {
            "bounds_m": [-MID_Y_HALF_WIDTH_M, MID_Y_HALF_WIDTH_M],
            **_mask_summary(
                mask=near_mid_y,
                positions=position_array,
                markers=marker_array,
                profile_z=profile_z,
                distances=profile_distance,
                masses=mass_array,
                particle_ids=id_array,
                denominator=int(support_valid.sum()),
                sample_limit=sample_limit,
            ),
        },
        "bed_y_width": {
            "bounds_m": list(BED_Y_BOUNDS_M),
            **_mask_summary(
                mask=bed_y_width,
                positions=position_array,
                markers=marker_array,
                profile_z=profile_z,
                distances=profile_distance,
                masses=mass_array,
                particle_ids=id_array,
                denominator=int(support_valid.sum()),
                sample_limit=sample_limit,
            ),
        },
        "marker_histogram_fixed_type0_valid": _marker_histogram(
            mask=fixed_valid,
            markers=marker_array,
            positions=position_array,
            masses=mass_array,
            particle_ids=id_array,
            denominator=int(fixed_valid.sum()),
        ),
        "distance_evaluable_count": int(distance_evaluable.sum()),
        "distance_evaluable_fraction_of_bed_support_finite": _fraction(
            int(distance_evaluable.sum()), int(support_finite.sum())
        ),
        "distance_evaluable_fraction_of_bed_marker_finite": _fraction(
            int(distance_evaluable.sum()), int(bed_marker_finite.sum())
            if native_marker_available
            else 0
        ),
        "profile_distance_m": {
            "definition": "continuous_bed_z(x) - native_fixed_particle_z",
            "min": float(np.min(profile_distance[distance_evaluable]))
            if distance_evaluable.any()
            else None,
            "max": float(np.max(profile_distance[distance_evaluable]))
            if distance_evaluable.any()
            else None,
            "mean": float(np.mean(profile_distance[distance_evaluable]))
            if distance_evaluable.any()
            else None,
        },
        "depth_bins": depth_bins,
        "x_bins_dp": _x_bin_records(
            mask=support_finite,
            positions=position_array,
            markers=marker_array,
            profile_z=profile_z,
            distances=profile_distance,
            masses=mass_array,
            particle_ids=id_array,
            sample_limit=sample_limit,
        ),
        "bed_segment_bins": _bed_segment_records(
            mask=support_finite,
            positions=position_array,
            markers=marker_array,
            profile_z=profile_z,
            distances=profile_distance,
            masses=mass_array,
            particle_ids=id_array,
            sample_limit=sample_limit,
        ),
        "relative_particle_layers": _layer_records(
            mask=distance_evaluable,
            layer_index=layers,
            positions=position_array,
            markers=marker_array,
            profile_z=profile_z,
            distances=profile_distance,
            masses=mass_array,
            particle_ids=id_array,
            sample_limit=sample_limit,
        ),
        "retention_policy": {
            "valid_type0_rows_retained_in_denominators": True,
            "nonfinite_fixed_rows_reported": True,
            "outside_x_rows_reported": True,
            "no_native_array_mask_or_drop": True,
            "depth_tolerances_are_not_acceptance_thresholds": True,
        },
    }


def _parse_times(xdmf_path: Path, expected_frames: int) -> list[float]:
    root = ET.parse(xdmf_path).getroot()
    times = [float(node.attrib["Value"]) for node in root.iter("Time")]
    if len(times) != expected_frames:
        raise ValueError(f"XDMF has {len(times)} Time entries; expected {expected_frames}")
    return times


def verify_time_axes(
    h5_times: np.ndarray | Sequence[float],
    xdmf_times: np.ndarray | Sequence[float],
    *,
    atol_s: float = 1.0e-9,
) -> dict[str, Any]:
    h5_values = np.asarray(h5_times, dtype=np.float64).reshape(-1)
    xdmf_values = np.asarray(xdmf_times, dtype=np.float64).reshape(-1)
    if h5_values.size != xdmf_values.size:
        return {
            "match": False,
            "h5_time_count": int(h5_values.size),
            "xdmf_time_count": int(xdmf_values.size),
            "max_abs_difference_s": None,
            "atol_s": float(atol_s),
            "reason": "time_axis_length_mismatch",
        }
    if h5_values.size == 0:
        return {
            "match": False,
            "h5_time_count": 0,
            "xdmf_time_count": 0,
            "max_abs_difference_s": None,
            "atol_s": float(atol_s),
            "reason": "empty_time_axis",
        }
    differences = np.abs(h5_values - xdmf_values)
    max_difference = float(np.max(differences))
    finite = np.isfinite(h5_values) & np.isfinite(xdmf_values)
    match = bool(finite.all() and np.allclose(h5_values, xdmf_values, rtol=0.0, atol=atol_s))
    return {
        "match": match,
        "h5_time_count": int(h5_values.size),
        "xdmf_time_count": int(xdmf_values.size),
        "max_abs_difference_s": max_difference,
        "atol_s": float(atol_s),
        "reason": "match" if match else "time_axis_value_mismatch",
    }


def _dataset(handle: Any, name: str) -> Any:
    path = name if name.startswith("/") else "/" + name
    key = path[1:]
    if key in handle:
        return handle[key]
    if path in handle:
        return handle[path]
    raise KeyError(f"required H5 dataset missing: {name}")


def _dataset_candidates(handle: Any, names: Sequence[str]) -> tuple[Any, str]:
    for name in names:
        path = name if name.startswith("/") else "/" + name
        key = path[1:]
        if key in handle:
            return handle[key], path
        if path in handle:
            return handle[path], path
    raise KeyError("required H5 dataset missing; tried: " + ", ".join(names))


def _optional_dataset_candidates(handle: Any, names: Sequence[str]) -> tuple[Any | None, str | None]:
    for name in names:
        path = name if name.startswith("/") else "/" + name
        key = path[1:]
        if key in handle:
            return handle[key], path
        if path in handle:
            return handle[path], path
    return None, None


def _frame_array(dataset: Any, frame_index: int, expected_particles: int) -> np.ndarray:
    shape = tuple(dataset.shape)
    if len(shape) == 1:
        values = np.asarray(dataset[...])
    elif len(shape) >= 2 and shape[0] == EXPECTED_FRAMES:
        values = np.asarray(dataset[frame_index, ...])
    else:
        raise ValueError(f"unsupported frame dataset shape: {shape}")
    return values.reshape(-1) if values.ndim != 2 else values


def _xml_source_signals(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    draw_triangles = list(root.iter("drawtriangles"))
    triangle_nodes = [triangle for node in draw_triangles for triangle in node.iter("triangle")]
    triangle_points = [point for node in draw_triangles for point in node.iter("point")]
    draw_boxes = []
    for node in root.iter("drawbox"):
        point = node.find("point")
        size = node.find("size")
        draw_boxes.append(
            {
                "cmt": node.attrib.get("cmt"),
                "point": dict(point.attrib) if point is not None else None,
                "size": dict(size.attrib) if size is not None else None,
            }
        )
    clipplanes = []
    for node in root.iter("clipplane"):
        point = node.find("point")
        vector = node.find("vector")
        clipplanes.append(
            {
                "cmt": node.attrib.get("cmt"),
                "point": dict(point.attrib) if point is not None else None,
                "vector": dict(vector.attrib) if vector is not None else None,
            }
        )
    return {
        "setshapemode_text": [" ".join((node.text or "").split()) for node in root.iter("setshapemode")],
        "setdrawmode": [dict(node.attrib) for node in root.iter("setdrawmode")],
        "setmkbound": [dict(node.attrib) for node in root.iter("setmkbound")],
        "setmkfluid": [dict(node.attrib) for node in root.iter("setmkfluid")],
        "drawtriangles_count": len(draw_triangles),
        "drawtriangles_point_count": len(triangle_points),
        "drawtriangles_triangle_count": len(triangle_nodes),
        "drawtriangles_comments": [node.attrib.get("cmt") for node in draw_triangles],
        "drawfilestl": [dict(node.attrib) for node in root.iter("drawfilestl")],
        "shapeout": [dict(node.attrib) for node in root.iter("shapeout")],
        "drawboxes": draw_boxes,
        "clipplanes": clipplanes,
        "clipreset_count": len(list(root.iter("clipreset"))),
        "motion_files": [dict(node.attrib) for node in root.iter("file")],
    }


def _particle_identity_ranges(path: Path) -> list[dict[str, Any]]:
    """Read generated XML Idp ranges without opening native numerical data."""

    root = ET.parse(path).getroot()
    ranges: list[dict[str, Any]] = []
    for particles in root.iter("particles"):
        for node in list(particles):
            if node.tag not in {"fixed", "moving", "fluid"}:
                continue
            if "begin" not in node.attrib or "count" not in node.attrib:
                continue
            record: dict[str, Any] = {
                "tag": node.tag,
                "begin": int(node.attrib["begin"]),
                "count": int(node.attrib["count"]),
            }
            for name in ("mk", "mkbound", "mkfluid", "refmotion"):
                if name in node.attrib:
                    try:
                        record[name] = int(node.attrib[name])
                    except ValueError:
                        record[name] = node.attrib[name]
                else:
                    record[name] = None
            ranges.append(record)
    return sorted(ranges, key=lambda item: (int(item["begin"]), str(item["tag"])))


def _range_axis_audit(
    ranges: Sequence[Mapping[str, Any]], expected_particles: int
) -> dict[str, Any]:
    ordered = sorted(ranges, key=lambda item: int(item["begin"]))
    cursor = 0
    gaps: list[dict[str, int]] = []
    overlaps: list[dict[str, int]] = []
    for item in ordered:
        begin = int(item["begin"])
        count = int(item["count"])
        end = begin + count
        if begin > cursor:
            gaps.append({"begin": cursor, "count": begin - cursor})
        if begin < cursor:
            overlaps.append({"begin": begin, "count": min(cursor, end) - begin})
        cursor = max(cursor, end)
    return {
        "range_count": len(ordered),
        "expected_particle_axis_count": int(expected_particles),
        "range_axis_end": int(cursor),
        "contiguous_from_zero_to_expected_axis": not gaps
        and not overlaps
        and cursor == expected_particles,
        "gaps": gaps,
        "overlaps": overlaps,
        "ranges": [dict(item) for item in ordered],
    }


def _bed_support_mask_from_ranges(
    particle_ids: np.ndarray,
    particle_zone: np.ndarray,
    ranges: Sequence[Mapping[str, Any]],
    *,
    expected_zone: int = 0,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Map XML mk=40 Idp ranges into the H5 (Zone,Idp) namespace."""

    ids = np.asarray(particle_ids).reshape(-1)
    zones = np.asarray(particle_zone).reshape(-1)
    if ids.shape[0] != zones.shape[0]:
        raise ValueError("particle_id and particle_zone lengths differ")
    finite_zone = np.isfinite(zones.astype(np.float64, copy=False))
    namespace_mask = finite_zone & (zones == expected_zone)
    support = np.zeros(ids.shape[0], dtype=bool)
    bed_ranges = [
        item
        for item in ranges
        if item.get("tag") == "fixed" and int(item.get("mk", -1)) == BED_MARKER
    ]
    for item in bed_ranges:
        begin = int(item["begin"])
        end = begin + int(item["count"])
        support |= (ids >= begin) & (ids < end)
    support &= namespace_mask
    unique_zones = np.unique(zones[finite_zone]) if finite_zone.any() else np.asarray([])
    return support, {
        "identity_key": "(particle_zone, particle_id)",
        "expected_particle_zone": int(expected_zone),
        "finite_particle_zone_count": int(finite_zone.sum()),
        "unique_particle_zone_values": [
            int(value) if float(value).is_integer() else float(value)
            for value in unique_zones
        ],
        "namespace_expected_zone_count": int(namespace_mask.sum()),
        "namespace_mismatch_count": int((finite_zone & ~namespace_mask).sum()),
        "bed_range_count": len(bed_ranges),
        "bed_range_particle_count": int(
            sum(int(item["count"]) for item in bed_ranges)
        ),
        "bed_range_records": [dict(item) for item in bed_ranges],
        "mapped_bed_support_count": int(support.sum()),
        "support_mapping_uses_particle_id_ranges": True,
        "support_mapping_uses_particle_zone_namespace": True,
    }


def _stl_mesh_attributes(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    vertices: list[tuple[float, float, float]] = []
    for match in re.finditer(
        r"\bvertex\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)",
        text,
    ):
        vertices.append(tuple(float(value) for value in match.groups()))
    points = np.asarray(vertices, dtype=np.float64).reshape((-1, 3)) if vertices else np.empty((0, 3))
    facets = len(re.findall(r"\bfacet\s+normal\b", text))
    return {
        "encoding": "ascii" if text.lstrip().startswith("solid") else "unknown",
        "facet_count": facets,
        "vertex_count": int(points.shape[0]),
        "bounds_m": _extrema(points),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def audit_source_provenance(manifest_path: Path) -> dict[str, Any]:
    """Read only the declared XML/STL/GenCase metadata sources."""

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files: dict[str, Any] = {}
    for role, entry in manifest["source_files"].items():
        path = Path(entry["path"])
        if not path.is_file():
            raise FileNotFoundError(f"provenance source missing: {path}")
        actual_sha = sha256_file(path)
        if actual_sha != entry["sha256"]:
            raise ValueError(f"provenance SHA mismatch for {role}: {actual_sha} != {entry['sha256']}")
        files[role] = {
            "path": str(path),
            "role": entry.get("role"),
            "bytes": path.stat().st_size,
            "sha256": actual_sha,
            "sha256_match": True,
        }

    xml_signals = {
        role: _xml_source_signals(Path(manifest["source_files"][role]["path"]))
        for role in ("selected_definition", "generated_xml", "generated_definition")
    }
    particle_ranges = {
        role: _particle_identity_ranges(Path(manifest["source_files"][role]["path"]))
        for role in ("selected_definition", "generated_xml", "generated_definition")
    }
    stl_path = Path(manifest["source_files"]["bed_stl"]["path"])
    stl = _stl_mesh_attributes(stl_path)
    prepared_report = json.loads(
        Path(manifest["source_files"]["prepared_input_report"]["path"]).read_text(encoding="utf-8")
    )
    receipt = json.loads(
        Path(manifest["source_files"]["gencase_receipt"]["path"]).read_text(encoding="utf-8")
    )
    stdout = Path(manifest["source_files"]["gencase_stdout"]["path"]).read_text(
        encoding="utf-8", errors="replace"
    )
    stdout_lines = [
        line.strip()
        for line in stdout.splitlines()
        if any(token in line for token in ("Particle summary", "Total particles", "Triangles:", "WARNING"))
    ]
    generated_counts = prepared_report.get("generated_xml_particle_counts", {})
    expected = manifest["expectations"]
    generated_range_audit = _range_axis_audit(
        particle_ranges["generated_xml"],
        int(expected.get("generated_total_particles", 0)),
    )
    generated_bed_ranges = [
        item
        for item in particle_ranges["generated_xml"]
        if item.get("tag") == "fixed" and int(item.get("mk", -1)) == int(expected["bed_marker_mk"])
    ]
    consistency = {
        "generated_xml_sha_matches_prepared_report": prepared_report.get("xml_sha256")
        == files["generated_xml"]["sha256"],
        "generated_definition_sha_matches_selected_definition": files["generated_definition"]["sha256"]
        == files["selected_definition"]["sha256"],
        "gencase_receipt_completed_returncode_zero": receipt.get("status") == "completed"
        and receipt.get("returncode") == 0,
        "gencase_receipt_total_matches_prepared_report": receipt.get("total_particles")
        == prepared_report.get("actual_total_particles"),
        "gencase_receipt_fluid_matches_prepared_report": receipt.get("fluid_particles")
        == generated_counts.get("fluid"),
        "generated_fixed_count_matches_prepared_report": generated_counts.get("fixed")
        == expected["generated_fixed_count"],
        "generated_xml_particle_ranges_contiguous_from_zero": generated_range_audit[
            "contiguous_from_zero_to_expected_axis"
        ],
        "generated_xml_bed_mk40_range_present": bool(generated_bed_ranges),
        "generated_xml_bed_mk40_range_count_matches_expected": sum(
            int(item["count"]) for item in generated_bed_ranges
        )
        == int(expected.get("generated_bed_mk40_count", 0))
        if "generated_bed_mk40_count" in expected
        else bool(generated_bed_ranges),
        "drawmode_full_in_all_xml": all(
            any(node.get("mode") == "full" for node in signals["setdrawmode"])
            for signals in xml_signals.values()
        ),
        "bed_stl_drawn_in_all_xml": all(
            any(
                node.get("file") == expected["bed_stl_relative_name"]
                for node in signals["drawfilestl"]
            )
            for signals in xml_signals.values()
        ),
        "triangle_mesh_declared_in_all_xml": all(
            signals["drawtriangles_count"] >= 1 and signals["drawtriangles_triangle_count"] >= expected["minimum_triangle_count"]
            for signals in xml_signals.values()
        ),
        "bed_marker_mk_declared_in_all_xml": all(
            any(str(node.get("mk")) == str(expected["bed_marker_mk"]) for node in signals["setmkbound"])
            for signals in xml_signals.values()
        ),
        "clipplane_vector_declared_in_all_xml": all(
            any(
                vector is not None
                and all(
                    math.isclose(float(vector.get(axis, "nan")), float(expected_value), abs_tol=1.0e-12)
                    for axis, expected_value in zip(("x", "y", "z"), expected["clipplane_vector"])
                )
                for clip in signals["clipplanes"]
                for vector in (clip.get("vector"),)
            )
            for signals in xml_signals.values()
        ),
    }
    return {
        "source_files": files,
        "xml_signals": xml_signals,
        "particle_identity_ranges": {
            "selected_definition": particle_ranges["selected_definition"],
            "generated_xml": generated_range_audit,
            "generated_definition": particle_ranges["generated_definition"],
            "bed_mk40_ranges": generated_bed_ranges,
        },
        "bed_stl_mesh_attributes": stl,
        "prepared_input_report_summary": {
            "generated_xml_particle_counts": generated_counts,
            "actual_total_particles": prepared_report.get("actual_total_particles"),
            "actual_generated_constants": prepared_report.get("actual_generated_constants"),
            "native_initial_typed_QA": prepared_report.get("native_initial_typed_QA"),
            "q_n": prepared_report.get("q_n"),
            "production_approval": prepared_report.get("production_approval"),
        },
        "gencase_receipt_summary": {
            key: receipt.get(key)
            for key in (
                "status",
                "returncode",
                "total_particles",
                "fluid_particles",
                "solver_dimension_from_gencase",
                "output_root",
                "binary_sha256",
                "stdout_sha256",
                "finished_at_utc",
            )
        },
        "gencase_log_evidence_lines": stdout_lines,
        "gencase_warning_lines_preserved": [line for line in stdout.splitlines() if "WARNING" in line],
        "consistency_checks": consistency,
        "interpretation_boundary": {
            "static_source_provenance_only": True,
            "generated_particle_counts_are_not_native_fixed_counts": True,
            "generated_xml_ranges_define_native_id_cohort_only": True,
            "particle_zone_is_namespace_not_mk": True,
            "no_hollow_stl_claim": True,
            "no_solver_root_cause_inferred": True,
            "no_repair_authorized": True,
        },
    }


def run_worker(
    *,
    trajectory_h5: Path,
    xdmf: Path,
    provenance_manifest: Path,
    output_dir: Path,
    expected_h5_sha256: str | None,
    expected_xdmf_sha256: str | None,
    audit_frames: Sequence[int],
    sample_limit: int,
) -> dict[str, Any]:
    """Run the future Root-authorized selected-frame H5 audit."""

    import h5py

    frame_indices = tuple(sorted(set(int(value) for value in audit_frames)))
    if not frame_indices or any(value < 0 or value >= EXPECTED_FRAMES for value in frame_indices):
        raise ValueError("audit_frames must be within [0, 800]")
    xdmf_times = _parse_times(xdmf, EXPECTED_FRAMES)
    h5_sha = sha256_file(trajectory_h5)
    xdmf_sha = sha256_file(xdmf)
    if expected_h5_sha256 and h5_sha != expected_h5_sha256:
        raise ValueError(f"H5 SHA256 mismatch: {h5_sha} != {expected_h5_sha256}")
    if expected_xdmf_sha256 and xdmf_sha != expected_xdmf_sha256:
        raise ValueError(f"XDMF SHA256 mismatch: {xdmf_sha} != {expected_xdmf_sha256}")

    output_dir.mkdir(parents=True, exist_ok=True)
    provenance = audit_source_provenance(provenance_manifest)
    frame_reports: list[dict[str, Any]] = []
    with h5py.File(trajectory_h5, "r") as handle:
        position_ds, position_path = _dataset_candidates(handle, ("/position",))
        valid_ds, valid_path = _dataset_candidates(handle, ("/valid",))
        type_ds, type_path = _dataset_candidates(handle, TYPE_DATASET_CANDIDATES)
        mass_ds, mass_path = _dataset_candidates(handle, MASS_DATASET_CANDIDATES)
        particle_ids_ds, particle_ids_path = _dataset_candidates(handle, ("/particle_id",))
        particle_zone_ds, particle_zone_path = _dataset_candidates(handle, ZONE_DATASET_CANDIDATES)
        marker_ds, marker_path = _optional_dataset_candidates(handle, MARKER_DATASET_CANDIDATES)
        time_ds, time_path = _dataset_candidates(handle, TIME_DATASET_CANDIDATES)
        if position_ds.shape[0] != EXPECTED_FRAMES:
            raise ValueError(f"position frame count is {position_ds.shape[0]}, expected {EXPECTED_FRAMES}")
        if position_ds.shape[1] != EXPECTED_PARTICLE_AXIS:
            raise ValueError(f"particle axis is {position_ds.shape[1]}, expected {EXPECTED_PARTICLE_AXIS}")
        particle_ids = np.asarray(particle_ids_ds[...]).reshape(-1)
        if particle_ids.size != EXPECTED_PARTICLE_AXIS:
            raise ValueError("particle_id axis does not match expected particle axis")
        particle_zone = np.asarray(particle_zone_ds[...]).reshape(-1)
        if particle_zone.size != EXPECTED_PARTICLE_AXIS:
            raise ValueError("particle_zone axis does not match expected particle axis")
        generated_range_audit = provenance["particle_identity_ranges"]["generated_xml"]
        generated_ranges = generated_range_audit.get("ranges", [])
        bed_range_records = provenance["particle_identity_ranges"].get("bed_mk40_ranges", [])
        if bed_range_records:
            bed_support_mask, namespace_audit = _bed_support_mask_from_ranges(
                particle_ids,
                particle_zone,
                generated_ranges,
            )
            bed_support_source = "generated_xml_particle_range_mk40_and_particle_zone_namespace"
        else:
            finite_zone = np.isfinite(particle_zone.astype(np.float64, copy=False))
            bed_support_mask = finite_zone & (particle_zone == 0)
            namespace_audit = {
                "identity_key": "(particle_zone, particle_id)",
                "expected_particle_zone": 0,
                "finite_particle_zone_count": int(finite_zone.sum()),
                "unique_particle_zone_values": [
                    int(value) if float(value).is_integer() else float(value)
                    for value in np.unique(particle_zone[finite_zone])
                ],
                "namespace_expected_zone_count": int(bed_support_mask.sum()),
                "namespace_mismatch_count": int((finite_zone & ~bed_support_mask).sum()),
                "bed_range_count": 0,
                "bed_range_particle_count": 0,
                "bed_range_records": [],
                "mapped_bed_support_count": int(bed_support_mask.sum()),
                "support_mapping_uses_particle_id_ranges": False,
                "support_mapping_uses_particle_zone_namespace": True,
                "fallback": "all_fixed_type0_spatial_support_when_generated_mk40_range_unavailable",
            }
            bed_support_source = "all_fixed_type0_spatial_support_no_generated_mk40_range"
        h5_times = np.asarray(time_ds[...], dtype=np.float64).reshape(-1)
        time_provenance = verify_time_axes(h5_times, xdmf_times)
        if not time_provenance["match"]:
            raise ValueError("H5 time axis does not match XDMF: " + canonical_json(time_provenance))
        for frame_index in frame_indices:
            positions = np.asarray(position_ds[frame_index, ...])
            valid = _frame_array(valid_ds, frame_index, EXPECTED_PARTICLE_AXIS)
            particle_type = _frame_array(type_ds, frame_index, EXPECTED_PARTICLE_AXIS)
            markers = (
                _frame_array(marker_ds, frame_index, EXPECTED_PARTICLE_AXIS)
                if marker_ds is not None
                else None
            )
            mass = _frame_array(mass_ds, frame_index, EXPECTED_PARTICLE_AXIS)
            frame_reports.append(
                frame_metrics(
                    frame_index=frame_index,
                    time_s=float(h5_times[frame_index]),
                    positions=positions,
                    valid=valid,
                    particle_type=particle_type,
                    markers=markers,
                    masses=mass,
                    particle_ids=particle_ids,
                    bed_support_mask=bed_support_mask,
                    bed_support_source=bed_support_source,
                    sample_limit=sample_limit,
                )
            )

    report: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "completed_worker_output_pending_root_review",
        "diagnostic_only": True,
        "production_approval": "none",
        "q_n_status": "not_granted",
        "visual_review_status": "not_applicable_initial_support_audit",
        "source_arrays_modified": False,
        "source_arrays_dropped_or_masked": False,
        "source": {
            "trajectory_h5": str(trajectory_h5),
            "trajectory_h5_sha256": h5_sha,
            "trajectory_h5_sha256_expected": expected_h5_sha256,
            "xdmf": str(xdmf),
            "xdmf_sha256": xdmf_sha,
            "xdmf_sha256_expected": expected_xdmf_sha256,
            "coordinate_frame": "DualSPHysics case Cartesian coordinates (x,y,z)",
            "dataset_paths": {
                "position": position_path,
                "valid": valid_path,
                "type": type_path,
                "mass": mass_path,
                "particle_id": particle_ids_path,
                "particle_zone": particle_zone_path,
                "marker": marker_path,
                "time": time_path,
            },
        },
        "native_identity_namespace": namespace_audit,
        "time_provenance": time_provenance,
        "audit_contract": {
            "audit_frames": list(frame_indices),
            "fixed_type_alias": FIXED_TYPE,
            "bed_marker_mk": BED_MARKER,
            "bed_support_source": bed_support_source,
            "particle_identity_key": "(particle_zone, particle_id)",
            "particle_zone_is_namespace_not_mk": True,
            "native_marker_optional": True,
            "bed_nodes_xz_m": BED_NODES_XZ_M.tolist(),
            "bed_y_bounds_m": list(BED_Y_BOUNDS_M),
            "near_mid_y_half_width_m": MID_Y_HALF_WIDTH_M,
            "x_bin_width_m": DP_M,
            "depth_tolerances_m": list(DEPTH_TOLERANCES_M),
        },
        "frame_reports": frame_reports,
        "static_source_provenance": provenance,
        "interpretation_boundary": {
            "fixed_type0_mk40_or_xml_cohort_presence_is_evidence_only": True,
            "native_marker_absence_is_nonfatal_and_explicit": True,
            "no_missing_bed_or_boundary_fault_claim": True,
            "no_hollow_stl_claim": True,
            "no_geometry_or_numeric_repair": True,
            "no_precision_acceptance": True,
            "no_production_approval": True,
        },
    }
    output_path = output_dir / "native_initial_fixed_bed_support_audit.json"
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def _synthetic_check() -> None:
    """Run bounded in-memory checks only; no bound source is opened."""

    positions = np.asarray(
        [
            [0.0, 0.00, 0.00],
            [2.5, 0.00, 0.14],
            [3.5, 0.02, 0.42],
            [4.9, 0.00, 0.00],
            [0.0, 0.16, 0.00],
            [1.0, 0.00, -0.10],
            [1.0, 0.00, 0.00],
        ],
        dtype=np.float64,
    )
    metrics = frame_metrics(
        frame_index=0,
        time_s=0.0,
        positions=positions,
        valid=np.ones(7, dtype=np.uint8),
        particle_type=np.asarray([0, 0, 0, 0, 0, 0, 3], dtype=np.int8),
        markers=np.asarray([40, 40, 40, 40, 40, 0, 1], dtype=np.int16),
        masses=np.ones(7, dtype=np.float64),
        particle_ids=np.arange(100, 107, dtype=np.uint32),
    )
    assert metrics["fixed_type0_valid_count"] == 6
    assert metrics["bed_marker_valid_count"] == 5
    assert metrics["bed_marker_finite_position_count"] == 5
    assert metrics["distance_evaluable_count"] == 4
    assert metrics["near_mid_y_strip"]["count"] == 3
    assert metrics["marker_histogram_fixed_type0_valid"]["40"]["count"] == 5
    assert sum(item["count"] for item in metrics["x_bins_dp"]) == 4
    assert sum(item["count"] for item in metrics["bed_segment_bins"]) == 4
    assert metrics["depth_bins"]["0.02m"]["count"] == 0
    assert metrics["relative_particle_layers"]
    markerless = frame_metrics(
        frame_index=0,
        time_s=0.0,
        positions=positions,
        valid=np.ones(7, dtype=np.uint8),
        particle_type=np.asarray([0, 0, 0, 0, 0, 0, 3], dtype=np.int8),
        markers=None,
        masses=np.ones(7, dtype=np.float64),
        particle_ids=np.arange(100, 107, dtype=np.uint32),
        bed_support_mask=np.asarray([True, True, True, True, True, False, False]),
        bed_support_source="generated_xml_particle_range_mk40_and_particle_zone_namespace",
    )
    assert markerless["native_marker_available"] is False
    assert markerless["bed_support_valid_count"] == 5
    assert markerless["bed_marker_valid_count"] is None
    assert markerless["distance_evaluable_count"] == 4
    time_check = verify_time_axes([0.0, 1.0], [0.0, 1.0 + 5.0e-10])
    assert time_check["match"] is True


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="run source-only synthetic checks")
    parser.add_argument("--trajectory-h5", type=Path)
    parser.add_argument("--xdmf", type=Path)
    parser.add_argument("--provenance-manifest", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--expected-h5-sha256")
    parser.add_argument("--expected-xdmf-sha256")
    parser.add_argument("--audit-frames", default="0,400")
    parser.add_argument("--sample-limit", type=int, default=DEFAULT_SAMPLE_LIMIT)
    args = parser.parse_args(argv)
    if args.check:
        _synthetic_check()
        print("source-only fixed-bed support synthetic checks passed")
        return 0
    required = (args.trajectory_h5, args.xdmf, args.provenance_manifest, args.output_dir)
    if any(value is None for value in required):
        parser.error(
            "--trajectory-h5, --xdmf, --provenance-manifest, and --output-dir are required for a real worker invocation"
        )
    if args.sample_limit <= 0:
        parser.error("--sample-limit must be positive")
    audit_frames = tuple(int(item.strip()) for item in args.audit_frames.split(",") if item.strip())
    run_worker(
        trajectory_h5=args.trajectory_h5,
        xdmf=args.xdmf,
        provenance_manifest=args.provenance_manifest,
        output_dir=args.output_dir,
        expected_h5_sha256=args.expected_h5_sha256,
        expected_xdmf_sha256=args.expected_xdmf_sha256,
        audit_frames=audit_frames,
        sample_limit=args.sample_limit,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
