#!/usr/bin/env python3
"""Strict, read-only 51-frame native bed-footprint audit for F5 B071.

This source-only handoff is deliberately disabled until Root binds the actual
short solver receipt and the native H5/XDMF conversion products.  A real
invocation reads those products read-only and writes one JSON report.  It
never starts DualSPHysics, GenCase, PartVTK, or a converter.

The penetration metrics are calculated only for finite Type-3 fluid rows whose
coordinates lie in the exact source profile x domain and in the actual bed
footprint y interval [-0.15, 0.15] m.  Every frame retains the complete
initial Type-3 UID set as the reference denominator.  Current invalid/type
changed rows, nonfinite positions, and missing initial UIDs are reported as
unexplained observations; they are never silently dropped or treated as a
successful repair.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np


BINDING_SCHEMA = "ds02.f5.b071.short-event-bed-audit-binding.fresh081.v1"
SCHEMA = "ds02.f5.b071.short-event-bed-footprint-audit.fresh081.v1"
CASE_ID = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_B071"
PHYSICAL_CASE_ID = "F5_COMPACT_STILL_WATER_RUNUP_REPAIR_B_CENTRAL_SUPPORT_V1"
CANONICAL_PHYSICAL_CONDITION_SHA256 = "d791355fcb5d8562a45ecdbee1772b1039f2fe8e6534760734509b51511c5d3f"
SOURCE_PLAN_PHYSICAL_CONDITION_SHA256 = "e912c12cc6cf9d3e754cba69a307f47588e717a8a4717f1ed190c63443cc3e72"
SOURCE_H5_PHYSICAL_CONDITION_SHA256 = "efa8c9822ee12f6400e36e09e6b1edaebb760882f3354adabb6113a72f380047"
SOURCE_H5_SCOPE_SCHEMA = "legacy-owner-scope.v0"
SOURCE_H5_SCOPE_STATUS = "legacy_incomplete; no cross-resolution physical claim"
FLUID_TYPE = 3
DP_M = 0.02
DEPTH_TOLERANCES_M = (DP_M, 2.0 * DP_M)
EXPECTED_FRAMES = 51
EXPECTED_PARTICLE_AXIS = 174896
EXPECTED_FLUID_PARTICLES = 40710
EXPECTED_FIXED_PARTICLES = 130392
EXPECTED_MOVING_PARTICLES = 3794
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
BED_X_BOUNDS_M = (
    float(BED_NODES_XZ_M[0, 0]),
    float(BED_NODES_XZ_M[-1, 0]),
)
BED_Y_BOUNDS_M = (-0.15, 0.15)
TIME_ATOL_S = 1.0e-9
TIME_SCHEDULE_ATOL_S = 1.0e-3
UID_SAMPLE_LIMIT = 32
DEPTH_SAMPLE_LIMIT = 10


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_file(path: Path, chunk_bytes: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            block = stream.read(chunk_bytes)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    require(isinstance(value, dict), f"JSON object required: {path}")
    return value


def text_attr(value: Any) -> str:
    """Decode a scalar HDF5 text attribute without changing its semantics."""
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if hasattr(value, "tobytes"):
        raw = value.tobytes()
        if isinstance(raw, bytes):
            return raw.decode("utf-8")
    return str(value)


def is_bound(value: Any) -> bool:
    return isinstance(value, str) and bool(value) and not value.startswith("<")


def uid_digest(ids: np.ndarray | Sequence[int]) -> str:
    values = np.asarray(ids, dtype="<u8").reshape(-1)
    return hashlib.sha256(np.sort(values, kind="stable").tobytes(order="C")).hexdigest()


def uid_summary(ids: np.ndarray | Sequence[int]) -> dict[str, Any]:
    values = np.asarray(ids, dtype=np.uint64).reshape(-1)
    ordered = np.sort(values, kind="stable")
    return {
        "count": int(ordered.size),
        "sha256_sorted_uint64le": uid_digest(ordered),
        "sample_first": [int(value) for value in ordered[:UID_SAMPLE_LIMIT]],
        "sample_last": [int(value) for value in ordered[-UID_SAMPLE_LIMIT:]],
    }


def fraction(numerator: int, denominator: int) -> float | None:
    return float(numerator) / float(denominator) if denominator else None


def bed_profile_z(x: np.ndarray | Sequence[float] | float) -> np.ndarray:
    values = np.asarray(x, dtype=np.float64)
    flat = values.reshape(-1)
    result = np.full(flat.shape, np.nan, dtype=np.float64)
    inside = (flat >= BED_X_BOUNDS_M[0]) & (flat <= BED_X_BOUNDS_M[1])
    result[inside] = np.interp(
        flat[inside],
        BED_NODES_XZ_M[:, 0],
        BED_NODES_XZ_M[:, 1],
    )
    return result.reshape(values.shape)


def _finite_extrema(points: np.ndarray) -> dict[str, list[float] | None]:
    if points.size == 0:
        return {"min_m": None, "max_m": None}
    return {
        "min_m": [float(value) for value in np.min(points, axis=0)],
        "max_m": [float(value) for value in np.max(points, axis=0)],
    }


def _sample_deepest(
    indices: np.ndarray,
    positions: np.ndarray,
    profile_z: np.ndarray,
    depth: np.ndarray,
    particle_ids: np.ndarray,
    limit: int = DEPTH_SAMPLE_LIMIT,
) -> list[dict[str, Any]]:
    if indices.size == 0:
        return []
    order = indices[np.argsort(depth[indices], kind="stable")[::-1][:limit]]
    rows: list[dict[str, Any]] = []
    for rank, index in enumerate(order, start=1):
        rows.append(
            {
                "rank": rank,
                "particle_id": int(particle_ids[index]),
                "x_m": float(positions[index, 0]),
                "y_m": float(positions[index, 1]),
                "z_m": float(positions[index, 2]),
                "bed_z_m": float(profile_z[index]),
                "depth_below_bed_m": float(depth[index]),
            }
        )
    return rows


def _uids_from_mask(mask: np.ndarray, particle_ids: np.ndarray) -> np.ndarray:
    return np.asarray(particle_ids[mask], dtype=np.uint64).reshape(-1)


def _set_difference_summary(
    expected_ids: np.ndarray,
    observed_ids: np.ndarray,
) -> dict[str, Any]:
    expected = set(int(value) for value in np.asarray(expected_ids, dtype=np.uint64))
    observed = set(int(value) for value in np.asarray(observed_ids, dtype=np.uint64))
    missing = np.asarray(sorted(expected - observed), dtype=np.uint64)
    extra = np.asarray(sorted(observed - expected), dtype=np.uint64)
    return {
        "missing_initial_uid": uid_summary(missing),
        "unexpected_current_uid": uid_summary(extra),
        "unexplained": bool(missing.size or extra.size),
        "interpretation": (
            "UID set differs from frame-zero Type-3 fluid set; cause is "
            "unexplained by this geometry audit"
            if missing.size or extra.size
            else "same UID set as frame-zero Type-3 fluid set"
        ),
    }


def _depth_bin(
    *,
    threshold_m: float,
    footprint_mask: np.ndarray,
    depth: np.ndarray,
    positions: np.ndarray,
    profile_z: np.ndarray,
    particle_ids: np.ndarray,
    initial_fluid_count: int,
    current_fluid_count: int,
) -> dict[str, Any]:
    below = footprint_mask & (depth > threshold_m)
    below_indices = np.flatnonzero(below)
    footprint_count = int(footprint_mask.sum())
    count = int(below.sum())
    finite_depth = depth[footprint_mask]
    return {
        "threshold_m": float(threshold_m),
        "count": count,
        "fraction_of_initial_fluid_uid_set": fraction(count, initial_fluid_count),
        "fraction_of_current_valid_type3_fluid": fraction(count, current_fluid_count),
        "fraction_of_finite_bed_footprint_fluid": fraction(count, footprint_count),
        "footprint_evaluable_count": footprint_count,
        "deepest_depth_m": float(np.max(depth[below])) if below.any() else None,
        "minimum_depth_m_in_footprint": (
            float(np.min(finite_depth)) if finite_depth.size else None
        ),
        "deepest_samples": _sample_deepest(
            below_indices,
            positions,
            profile_z,
            depth,
            particle_ids,
        ),
        "threshold_interpretation": "diagnostic bin; not an acceptance threshold",
    }


def frame_metrics(
    *,
    frame_index: int,
    time_s: float,
    positions: np.ndarray,
    valid: np.ndarray,
    particle_type: np.ndarray,
    mass: np.ndarray,
    particle_ids: np.ndarray,
    initial_fluid_ids: np.ndarray,
) -> dict[str, Any]:
    position_array = np.asarray(positions, dtype=np.float64)
    valid_array = np.asarray(valid).reshape(-1).astype(bool, copy=False)
    type_array = np.asarray(particle_type).reshape(-1)
    mass_array = np.asarray(mass, dtype=np.float64).reshape(-1)
    id_array = np.asarray(particle_ids, dtype=np.uint64).reshape(-1)
    require(position_array.ndim == 2 and position_array.shape[1] == 3, "positions must be (N,3)")
    particle_count = position_array.shape[0]
    for name, array in (
        ("valid", valid_array),
        ("particle_type", type_array),
        ("mass", mass_array),
        ("particle_id", id_array),
    ):
        require(array.shape[0] == particle_count, f"{name} axis mismatch")

    current_fluid = valid_array & (type_array == FLUID_TYPE)
    finite_position = np.isfinite(position_array).all(axis=1)
    finite_current_fluid = current_fluid & finite_position
    initial_mask = np.isin(id_array, initial_fluid_ids)
    nonfinite_initial_position = initial_mask & ~finite_position
    nonfinite_current_fluid_position = current_fluid & ~finite_position
    current_fluid_ids = _uids_from_mask(current_fluid, id_array)
    uid_change = _set_difference_summary(initial_fluid_ids, current_fluid_ids)

    x = position_array[:, 0]
    y = position_array[:, 1]
    x_in_domain = finite_current_fluid & (x >= BED_X_BOUNDS_M[0]) & (x <= BED_X_BOUNDS_M[1])
    y_in_footprint = finite_current_fluid & (
        (y >= BED_Y_BOUNDS_M[0]) & (y <= BED_Y_BOUNDS_M[1])
    )
    footprint = x_in_domain & y_in_footprint
    profile_z = np.full(particle_count, np.nan, dtype=np.float64)
    profile_z[x_in_domain] = bed_profile_z(x[x_in_domain])
    depth = profile_z - position_array[:, 2]

    initial_count = int(initial_fluid_ids.size)
    current_count = int(current_fluid.sum())
    footprint_count = int(footprint.sum())
    finite_mass_current = current_fluid & np.isfinite(mass_array)
    report = {
        "frame": int(frame_index),
        "time_s": float(time_s),
        "particle_axis_count": int(particle_count),
        "initial_fluid_uid_count": initial_count,
        "current_valid_type3_fluid_count": current_count,
        "current_valid_type3_fraction_of_initial_uid_set": fraction(
            current_count, initial_count
        ),
        "finite_position_current_fluid_count": int(finite_current_fluid.sum()),
        "nonfinite_position_current_fluid_count": int(nonfinite_current_fluid_position.sum()),
        "nonfinite_initial_fluid_uid_count": int(nonfinite_initial_position.sum()),
        "nonfinite_initial_fluid_uids": uid_summary(
            _uids_from_mask(nonfinite_initial_position, id_array)
        ),
        "uid_tracking": uid_change,
        "finite_mass_current_fluid_count": int(finite_mass_current.sum()),
        "nonfinite_mass_current_fluid_count": int((current_fluid & ~np.isfinite(mass_array)).sum()),
        "finite_current_fluid_extrema_m": _finite_extrema(position_array[finite_current_fluid]),
        "bed_domain": {
            "x_in_exact_profile_domain_count": int(x_in_domain.sum()),
            "x_outside_exact_profile_domain_count": int((finite_current_fluid & ~x_in_domain).sum()),
            "y_in_actual_bed_footprint_count": int(y_in_footprint.sum()),
            "y_outside_actual_bed_footprint_with_x_in_domain_count": int(
                (x_in_domain & ~y_in_footprint).sum()
            ),
            "finite_bed_footprint_evaluable_count": footprint_count,
            "fraction_of_initial_fluid_uid_set": fraction(footprint_count, initial_count),
            "fraction_of_current_valid_type3_fluid": fraction(footprint_count, current_count),
            "profile_nodes_xz_m": BED_NODES_XZ_M.tolist(),
            "x_bounds_m": list(BED_X_BOUNDS_M),
            "y_bounds_m": list(BED_Y_BOUNDS_M),
        },
        "penetration": {
            "only_finite_current_type3_inside_exact_x_y_bed_footprint": True,
            "one_dp": _depth_bin(
                threshold_m=DEPTH_TOLERANCES_M[0],
                footprint_mask=footprint,
                depth=depth,
                positions=position_array,
                profile_z=profile_z,
                particle_ids=id_array,
                initial_fluid_count=initial_count,
                current_fluid_count=current_count,
            ),
            "two_dp": _depth_bin(
                threshold_m=DEPTH_TOLERANCES_M[1],
                footprint_mask=footprint,
                depth=depth,
                positions=position_array,
                profile_z=profile_z,
                particle_ids=id_array,
                initial_fluid_count=initial_count,
                current_fluid_count=current_count,
            ),
            "depth_sign": "bed_profile_z_minus_particle_z; positive means below bed",
            "depth_unevaluable_current_fluid_count": int(
                current_fluid.sum() - footprint_count
            ),
        },
        "denominator_policy": {
            "all_fluid_reference": (
                "frame-zero valid Type-3 UID set; all 40710 initial UIDs remain "
                "the reference denominator even when current rows are invalid, "
                "nonfinite, outside x, or outside the bed y footprint"
            ),
            "penetration_counts": (
                "only finite current valid Type-3 rows inside exact profile x "
                "domain and y in [-0.15,0.15] m"
            ),
            "outside_and_invalid_rows": "retained and reported; never masked or dropped",
            "thresholds_are_diagnostic_only": True,
        },
        "unexplained_state": {
            "nonfinite_or_lost_initial_uid_present": bool(
                nonfinite_initial_position.any()
                or uid_change["missing_initial_uid"]["count"]
            ),
            "cause_assigned": False,
            "interpretation": "UID loss/nonfinite state is reported without causal inference",
        },
    }
    return report


def _parse_xdmf_times(path: Path) -> list[float]:
    root = ET.parse(path).getroot()
    values = [float(node.attrib["Value"]) for node in root.iter("Time")]
    require(len(values) == EXPECTED_FRAMES, f"XDMF time count {len(values)} != {EXPECTED_FRAMES}")
    return values


def _check_time_axes(h5_times: np.ndarray, xdmf_times: Sequence[float]) -> dict[str, Any]:
    h5_values = np.asarray(h5_times, dtype=np.float64).reshape(-1)
    xdmf_values = np.asarray(xdmf_times, dtype=np.float64).reshape(-1)
    require(h5_values.size == EXPECTED_FRAMES, "H5 time axis is not 51 frames")
    require(xdmf_values.size == EXPECTED_FRAMES, "XDMF time axis is not 51 frames")
    finite = np.isfinite(h5_values) & np.isfinite(xdmf_values)
    strictly_increasing = bool(np.all(np.diff(h5_values) > 0.0))
    require(
        bool(finite.all())
        and h5_values[0] == 0.0
        and h5_values[-1] >= 1.0
        and strictly_increasing
        and np.allclose(h5_values, xdmf_values, rtol=0.0, atol=TIME_ATOL_S),
        "H5/XDMF time axes differ or do not cover the complete 0..1 s short event",
    )
    steps = np.diff(h5_values)
    return {
        "match": True,
        "frame_count": EXPECTED_FRAMES,
        "first_s": float(h5_values[0]),
        "last_s": float(h5_values[-1]),
        "max_h5_xdmf_abs_difference_s": float(np.max(np.abs(h5_values - xdmf_values))),
        "min_actual_step_s": float(np.min(steps)),
        "max_actual_step_s": float(np.max(steps)),
        "h5_xdmf_atol_s": TIME_ATOL_S,
        "strictly_increasing": strictly_increasing,
        "nominal_save_interval_s": 0.02,
        "uniform_spacing_assumption": False,
        "time_source": "native H5 time dataset and XDMF Time/@Value metadata",
    }
def _dataset(handle: Any, name: str) -> Any:
    if name in handle:
        return handle[name]
    slash_name = "/" + name
    if slash_name in handle:
        return handle[slash_name]
    raise KeyError(f"required H5 dataset missing: {name}")


def _verify_bound_metadata(binding: Mapping[str, Any]) -> dict[str, Any]:
    """Verify the actual 075/083/short-solver metadata before opening H5."""

    require(binding.get("schema") == BINDING_SCHEMA, "fresh081 binding schema mismatch")
    require(binding.get("case_id") == CASE_ID, "fresh081 case_id mismatch")
    require(binding.get("physical_case_id") == PHYSICAL_CASE_ID, "fresh081 physical_case_id mismatch")
    require(binding.get("expected_dimension") == 3, "fresh081 binding is not 3D")
    require(binding.get("expected_frames") == EXPECTED_FRAMES, "fresh081 frame contract mismatch")
    require(binding.get("expected_particle_axis") == EXPECTED_PARTICLE_AXIS, "fresh081 particle axis contract mismatch")
    require(binding.get("expected_fluid_particles") == EXPECTED_FLUID_PARTICLES, "fresh081 fluid count contract mismatch")
    require(binding.get("expected_fixed_particles") == EXPECTED_FIXED_PARTICLES, "fresh081 fixed count contract mismatch")
    require(binding.get("expected_moving_particles") == EXPECTED_MOVING_PARTICLES, "fresh081 moving count contract mismatch")
    require(binding.get("native_bed_marker_mk") == 50, "fresh081 native bed marker must be Mk50")
    require(binding.get("source_bed_marker_mkbound") == 40, "fresh081 source bed marker must be mkbound40")
    require(binding.get("physical_condition_sha256") == CANONICAL_PHYSICAL_CONDITION_SHA256,
            "fresh081 canonical physical owner changed")
    require(binding.get("source_plan_physical_condition_sha256") == SOURCE_PLAN_PHYSICAL_CONDITION_SHA256,
            "fresh081 source plan hash changed")
    require(binding.get("source_h5_physical_condition_sha256") == SOURCE_H5_PHYSICAL_CONDITION_SHA256,
            "fresh081 source H5 legacy hash changed")
    require(binding.get("source_h5_physical_condition_sha256") != binding.get("physical_condition_sha256"),
            "fresh081 collapsed legacy and canonical physical hashes")
    semantics = binding.get("physical_condition_hash_semantics", {})
    require(semantics.get("canonical_owner_sha256") == CANONICAL_PHYSICAL_CONDITION_SHA256,
            "fresh081 canonical semantic binding missing")
    require(semantics.get("source_h5_sha256") == SOURCE_H5_PHYSICAL_CONDITION_SHA256,
            "fresh081 source H5 semantic binding missing")
    require(semantics.get("source_h5_scope_schema") == SOURCE_H5_SCOPE_SCHEMA,
            "fresh081 source H5 scope schema changed")
    require(semantics.get("source_h5_scope_status") == SOURCE_H5_SCOPE_STATUS,
            "fresh081 source H5 scope was presented as canonical")

    records: list[dict[str, Any]] = []
    for role, path_key, hash_key in (
        ("genuine163_gencase_receipt", "gencase_receipt", "gencase_receipt_sha256"),
        ("actual175_qa_receipt", "initial_qa_receipt", "initial_qa_receipt_sha256"),
        ("actual175_qa_report", "initial_qa_report", "initial_qa_report_sha256"),
        ("short_solver_receipt", "short_solver_receipt", "short_solver_receipt_sha256"),
        ("native_conversion_report", "native_conversion_report", "native_conversion_report_sha256"),
        ("canonical_generated_xml", "canonical_generated_xml", "canonical_generated_xml_sha256"),
        ("actual_xmf_manifest", "xmf_manifest", "xmf_manifest_sha256"),
    ):
        raw_path = binding.get(path_key)
        raw_hash = binding.get(hash_key)
        require(is_bound(raw_path), f"{role} path is not Root-bound")
        require(is_bound(raw_hash), f"{role} sha256 is not Root-bound")
        path = Path(str(raw_path)).resolve()
        require(path.is_file(), f"{role} does not exist: {path}")
        actual_hash = sha256_file(path)
        require(actual_hash == raw_hash, f"{role} sha256 mismatch: {actual_hash} != {raw_hash}")
        records.append({"role": role, "path": str(path), "sha256": actual_hash})

    gencase = load_json(Path(str(binding["gencase_receipt"])))
    require(gencase.get("status") == "completed", "163 GenCase receipt is not completed")
    require(gencase.get("returncode") == 0, "163 GenCase returncode is not zero")
    receipt_output_root = Path(str(binding.get("gencase_receipt_output_root", ""))).resolve()
    prepared_output_root = Path(str(binding.get("gencase_prepared_output_root", ""))).resolve()
    binding_output_root = Path(str(binding.get("gencase_output_root", ""))).resolve()
    require(is_bound(binding.get("gencase_receipt_output_root")),
            "163 GenCase receipt output root is not Root-bound")
    require(is_bound(binding.get("gencase_prepared_output_root")),
            "163 GenCase prepared output root is not Root-bound")
    require(binding_output_root == receipt_output_root,
            "163 GenCase binding output-root aliases disagree")
    generated_xml_path = Path(str(binding["canonical_generated_xml"])).resolve()
    require(generated_xml_path.parent == prepared_output_root,
            "163 generated XML is outside the bound prepared output root")
    try:
        prepared_output_root.relative_to(receipt_output_root)
    except ValueError as exc:
        raise ValueError("163 prepared output root is outside the receipt output root") from exc
    require(
        Path(str(gencase.get("output_root", ""))).resolve()
        == receipt_output_root,
        "163 GenCase receipt output root does not match the actual attempt root",
    )
    require(gencase.get("total_particles") == EXPECTED_PARTICLE_AXIS, "163 total particle count mismatch")
    require(gencase.get("fluid_particles") == EXPECTED_FLUID_PARTICLES, "163 fluid particle count mismatch")
    require(gencase.get("solver_dimension_from_gencase") == 3, "163 GenCase is not 3D")

    qa_receipt = load_json(Path(str(binding["initial_qa_receipt"])))
    require(qa_receipt.get("status") == "completed", "175 initial QA receipt is not completed")
    require(qa_receipt.get("returncode") == 0, "175 initial QA returncode is not zero")
    require(
        Path(str(qa_receipt.get("output_root", ""))).resolve()
        == Path(str(binding["initial_qa_output_root"])).resolve(),
        "175 initial QA receipt output root mismatch",
    )
    qa_report = load_json(Path(str(binding["initial_qa_report"])))
    require(qa_report.get("schema") == "ds02.f5.b071.actual-initial-qa.v1", "175 report schema mismatch")
    require(qa_report.get("all_actual_checks_pass") is True, "175 actual initial QA did not pass")
    require(qa_report.get("status") == "actual_native_qa", "175 report status mismatch")
    require(qa_report.get("full_solver_authorized") is False, "175 report authorized solver unexpectedly")

    solver_receipt = load_json(Path(str(binding["short_solver_receipt"])))
    require(solver_receipt.get("status") == "completed", "short solver receipt is not completed")
    require(solver_receipt.get("returncode") == 0, "short solver returncode is not zero")
    require(
        Path(str(solver_receipt.get("output_root", ""))).resolve()
        == Path(str(binding["short_solver_output_root"])).resolve(),
        "short solver receipt output root mismatch",
    )
    actual_command = solver_receipt.get("command", [])
    require("-tmax:1.0" in actual_command, "short solver was not bounded to 1.0 s")
    require("-tout:0.02" in actual_command, "short solver save cadence is not 0.02 s")

    conversion = load_json(Path(str(binding["native_conversion_report"])))
    require(conversion.get("schema") == "ds-data-02.bi4-direct-conversion.v1",
            "native conversion schema mismatch")
    require(conversion.get("conversion_status") == "completed", "native conversion is not completed")
    require(
        Path(str(conversion.get("output_hdf5", ""))).resolve()
        == Path(str(binding["trajectory_h5"])).resolve(),
        "native conversion H5 path mismatch",
    )
    require(conversion.get("frames") == EXPECTED_FRAMES, "native conversion frame count is not 51")
    require(conversion.get("particles") == EXPECTED_PARTICLE_AXIS, "native conversion particle count mismatch")
    require(conversion.get("solver_dimension", {}).get("solver_dimension") == 3, "native conversion is not 3D")
    report_scopes = conversion.get("hash_scopes", {})
    report_scope = report_scopes.get("physical_condition", {})
    require(report_scopes.get("physical_condition_sha256") == SOURCE_H5_PHYSICAL_CONDITION_SHA256,
            "native conversion legacy physical hash mismatch")
    require(report_scope.get("schema") == SOURCE_H5_SCOPE_SCHEMA,
            "native conversion physical scope schema mismatch")
    require(report_scope.get("semantic_binding_status") == SOURCE_H5_SCOPE_STATUS,
            "native conversion physical scope was presented as canonical")
    identity = conversion.get("typed_identity", {})
    blocks = identity.get("blocks", [])
    require(isinstance(blocks, list), "native typed identity blocks missing")
    role_counts: dict[str, int] = {}
    for block in blocks:
        if isinstance(block, dict):
            role = str(block.get("tag", ""))
            role_counts[role] = role_counts.get(role, 0) + int(block.get("count", 0))
    require(role_counts.get("fixed") == EXPECTED_FIXED_PARTICLES,
            "native fixed identity count mismatch")
    require(role_counts.get("moving") == EXPECTED_MOVING_PARTICLES,
            "native moving identity count mismatch")
    require(role_counts.get("fluid") == EXPECTED_FLUID_PARTICLES,
            "native fluid identity count mismatch")
    require(50 in identity.get("observed_mks", []), "native bed Mk50 missing")
    require({0, 1, 3}.issubset(set(identity.get("observed_types", []))),
            "native type identity incomplete")

    manifest = load_json(Path(str(binding["xmf_manifest"])))
    require(manifest.get("schema") == "ds02.stage1.paraview-temporal-product.v1",
            "XMF manifest schema mismatch")
    require(manifest.get("case_id") == CASE_ID, "XMF manifest case_id mismatch")
    require(manifest.get("source_h5_sha256") == binding.get("trajectory_h5_sha256"),
            "XMF manifest H5 digest mismatch")
    require(manifest.get("physical_condition_sha256") == CANONICAL_PHYSICAL_CONDITION_SHA256,
            "XMF manifest canonical physical owner mismatch")
    require(manifest.get("canonical_physical_condition_sha256") == CANONICAL_PHYSICAL_CONDITION_SHA256,
            "XMF manifest canonical sidecar mismatch")
    require(manifest.get("source_h5_physical_condition_sha256") == SOURCE_H5_PHYSICAL_CONDITION_SHA256,
            "XMF manifest legacy H5 hash mismatch")
    manifest_semantics = manifest.get("physical_condition_hash_semantics", {})
    require(manifest_semantics.get("source_h5_scope_schema") == SOURCE_H5_SCOPE_SCHEMA,
            "XMF manifest legacy scope schema mismatch")
    require(manifest_semantics.get("source_h5_scope_status") == SOURCE_H5_SCOPE_STATUS,
            "XMF manifest legacy scope was presented as canonical")

    return {
        "records": records,
        "gencase": {
            "status": gencase["status"],
            "total_particles": gencase["total_particles"],
            "fluid_particles": gencase["fluid_particles"],
            "dimension": gencase["solver_dimension_from_gencase"],
            "receipt_output_root": str(receipt_output_root),
            "prepared_output_root": str(prepared_output_root),
        },
        "initial_qa": {
            "status": qa_receipt["status"],
            "all_actual_checks_pass": qa_report["all_actual_checks_pass"],
            "report_sha256": str(binding["initial_qa_report_sha256"]),
        },
        "short_solver": {
            "status": solver_receipt["status"],
            "command": actual_command,
        },
        "native_conversion": {
            "status": conversion["conversion_status"],
            "frames": conversion["frames"],
            "particles": conversion["particles"],
            "fixed_particles": EXPECTED_FIXED_PARTICLES,
            "moving_particles": EXPECTED_MOVING_PARTICLES,
            "fluid_particles": EXPECTED_FLUID_PARTICLES,
            "native_bed_marker_mk": 50,
            "source_bed_marker_mkbound": 40,
            "source_h5_physical_condition_sha256": SOURCE_H5_PHYSICAL_CONDITION_SHA256,
            "canonical_physical_condition_sha256": CANONICAL_PHYSICAL_CONDITION_SHA256,
        },
    }


def run_worker(
    *,
    binding_path: Path,
    trajectory_h5: Path,
    xdmf: Path,
    output_dir: Path,
) -> dict[str, Any]:
    import h5py

    binding = load_json(binding_path)
    require(binding.get("schema") == BINDING_SCHEMA, "fresh081 binding schema mismatch")
    metadata = _verify_bound_metadata(binding)
    expected_h5_sha256 = str(binding.get("trajectory_h5_sha256", ""))
    expected_xdmf_sha256 = str(binding.get("xdmf_sha256", ""))
    require(is_bound(expected_h5_sha256), "trajectory H5 sha256 is not Root-bound")
    require(is_bound(expected_xdmf_sha256), "XDMF sha256 is not Root-bound")
    require(trajectory_h5.is_file(), f"trajectory H5 missing: {trajectory_h5}")
    require(xdmf.is_file(), f"XDMF missing: {xdmf}")
    h5_sha256 = sha256_file(trajectory_h5)
    xdmf_sha256 = sha256_file(xdmf)
    require(h5_sha256 == expected_h5_sha256, "trajectory H5 sha256 mismatch")
    require(xdmf_sha256 == expected_xdmf_sha256, "XDMF sha256 mismatch")

    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    runtime_names = {"stdout.log", "execution-receipt.json"}
    prior_artifacts = [
        path.name
        for path in output_dir.iterdir()
        if path.name not in runtime_names
        and not path.name.startswith("execution-receipt.json.")
    ]
    require(not prior_artifacts, f"audit output directory contains prior artifacts: {prior_artifacts}")
    xdmf_times = _parse_xdmf_times(xdmf)
    frame_reports: list[dict[str, Any]] = []

    with h5py.File(trajectory_h5, "r") as handle:
        source_h5_condition = text_attr(handle.attrs.get("physical_condition_sha256", ""))
        require(source_h5_condition == SOURCE_H5_PHYSICAL_CONDITION_SHA256,
                "H5 legacy physical hash does not match bound report scope")
        positions_ds = _dataset(handle, "position")
        valid_ds = _dataset(handle, "valid")
        type_ds = _dataset(handle, "type")
        mass_ds = _dataset(handle, "mass")
        particle_ids_ds = _dataset(handle, "particle_id")
        time_ds = None
        time_path = None
        for candidate in ("/time", "/times", "/Time"):
            try:
                time_ds = _dataset(handle, candidate)
                time_path = candidate
                break
            except KeyError:
                continue
        require(time_ds is not None, "H5 time dataset missing")
        h5_times = np.asarray(time_ds[...], dtype=np.float64).reshape(-1)
        time_provenance = _check_time_axes(h5_times, xdmf_times)
        require(positions_ds.shape[0] == EXPECTED_FRAMES, "position frame count is not 51")
        require(positions_ds.shape[1] == EXPECTED_PARTICLE_AXIS, "particle axis is not 174896")
        for name, dataset in (("valid", valid_ds), ("type", type_ds), ("mass", mass_ds)):
            require(dataset.shape[0] == EXPECTED_FRAMES, f"{name} frame count is not 51")
            require(dataset.shape[1] == EXPECTED_PARTICLE_AXIS, f"{name} particle axis mismatch")
        particle_ids = np.asarray(particle_ids_ds[...]).reshape(-1)
        require(particle_ids.size == EXPECTED_PARTICLE_AXIS, "particle_id axis mismatch")
        require(np.isfinite(particle_ids.astype(np.float64)).all(), "particle_id has nonfinite values")
        require(np.unique(particle_ids).size == EXPECTED_PARTICLE_AXIS, "particle_id is not unique")
        frame0_valid = np.asarray(valid_ds[0, ...]).reshape(-1).astype(bool, copy=False)
        frame0_type = np.asarray(type_ds[0, ...]).reshape(-1)
        initial_mask = frame0_valid & (frame0_type == FLUID_TYPE)
        initial_fluid_ids = np.asarray(particle_ids[initial_mask], dtype=np.uint64)
        require(initial_fluid_ids.size == EXPECTED_FLUID_PARTICLES, "frame-zero fluid UID count mismatch")
        require(np.unique(initial_fluid_ids).size == EXPECTED_FLUID_PARTICLES, "frame-zero fluid UIDs are not unique")
        for frame_index in range(EXPECTED_FRAMES):
            report = frame_metrics(
                frame_index=frame_index,
                time_s=float(h5_times[frame_index]),
                positions=np.asarray(positions_ds[frame_index, ...]),
                valid=np.asarray(valid_ds[frame_index, ...]),
                particle_type=np.asarray(type_ds[frame_index, ...]),
                mass=np.asarray(mass_ds[frame_index, ...]),
                particle_ids=particle_ids,
                initial_fluid_ids=initial_fluid_ids,
            )
            frame_reports.append(report)

    require(len(frame_reports) == EXPECTED_FRAMES, "did not produce 51 frame reports")
    report = {
        "schema": SCHEMA,
        "status": "completed_worker_output_pending_root_review",
        "diagnostic_only": True,
        "repair_success": "unknown_until_short_event_bed_audit_review",
        "full16_authorized": False,
        "production_approval": "none",
        "q_n_status": "not_granted",
        "source_arrays_modified": False,
        "source_arrays_dropped_or_masked": False,
        "physical_condition_sha256": CANONICAL_PHYSICAL_CONDITION_SHA256,
        "source_plan_physical_condition_sha256": SOURCE_PLAN_PHYSICAL_CONDITION_SHA256,
        "source_h5_physical_condition_sha256": SOURCE_H5_PHYSICAL_CONDITION_SHA256,
        "physical_condition_hash_semantics": {
            "canonical_owner_sha256": CANONICAL_PHYSICAL_CONDITION_SHA256,
            "source_h5_sha256": SOURCE_H5_PHYSICAL_CONDITION_SHA256,
            "source_h5_scope_schema": SOURCE_H5_SCOPE_SCHEMA,
            "source_h5_scope_status": SOURCE_H5_SCOPE_STATUS,
            "relation": "distinct; H5 attribute was validated against producer legacy scope and never substituted for canonical owner",
        },
        "native_identity_contract": {
            "total_particles": EXPECTED_PARTICLE_AXIS,
            "fixed_particles": EXPECTED_FIXED_PARTICLES,
            "moving_particles": EXPECTED_MOVING_PARTICLES,
            "fluid_particles": EXPECTED_FLUID_PARTICLES,
            "native_bed_marker_mk": 50,
            "source_bed_marker_mkbound": 40,
        },
        "bound_actual_inputs": metadata,
        "source": {
            "trajectory_h5": str(trajectory_h5),
            "trajectory_h5_sha256": h5_sha256,
            "xdmf": str(xdmf),
            "xdmf_sha256": xdmf_sha256,
            "time_dataset_path": time_path,
            "datasets": ["position", "valid", "type", "mass", "particle_id", "time"],
            "coordinate_frame": "DualSPHysics case Cartesian coordinates (x,y,z)",
        },
        "scan": {
            "frames_scanned": EXPECTED_FRAMES,
            "frame_indices": [0, 1, 2, 25, 50],
            "full_scan_range": [0, 50],
            "times_s": {
                "first": float(h5_times[0]),
                "last": float(h5_times[-1]),
                "nominal_save_interval_s": 0.02,
                "min_actual_step_s": float(np.min(np.diff(h5_times))),
                "max_actual_step_s": float(np.max(np.diff(h5_times))),
                "uniform_spacing_assumption": False,
            },
            "particle_axis_count": EXPECTED_PARTICLE_AXIS,
            "initial_fluid_uid_count": EXPECTED_FLUID_PARTICLES,
            "fluid_type_code": FLUID_TYPE,
            "dp_m": DP_M,
            "bed_nodes_xz_m": BED_NODES_XZ_M.tolist(),
            "bed_x_domain_m": list(BED_X_BOUNDS_M),
            "bed_y_domain_m": list(BED_Y_BOUNDS_M),
            "depth_tolerances_m": list(DEPTH_TOLERANCES_M),
        },
        "time_provenance": time_provenance,
        "initial_fluid_uid_reference": {
            "policy": "frame-zero valid Type-3 rows",
            "uid_count": EXPECTED_FLUID_PARTICLES,
            "uid_digest_sorted_uint64le_sha256": uid_digest(initial_fluid_ids),
            "all_uids_retained_as_reference_denominator": True,
        },
        "frame_reports": frame_reports,
        "interpretation_boundary": {
            "penetration_scope": "finite current Type-3 rows inside exact x profile and y [-0.15,0.15] bed footprint only",
            "one_dp_and_two_dp": "diagnostic depth bins with counts and ratios; no threshold relaxation or acceptance gate",
            "nonfinite_or_lost_uid": "reported per frame with UID digest/sample and cause unassigned",
            "repair_success": "not inferred from this source-only worker; Root review required",
            "short_event_limit": "0..1 s only; late 8 s/full16 behavior remains untested",
        },
    }
    output_path = output_dir / "b071-short-event-bed-footprint-audit.json"
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def _synthetic_check() -> None:
    require(
        np.allclose(
            bed_profile_z(np.asarray([-0.2, 2.0, 3.0, 4.8])),
            np.asarray([0.0, 0.0, 0.28, 0.05]),
        ),
        "piecewise profile interpolation mismatch",
    )
    positions = np.asarray(
        [
            [0.0, 0.0, -0.03],
            [0.0, 0.16, -0.03],
            [4.9, 0.0, -0.03],
            [0.0, 0.0, np.nan],
        ],
        dtype=np.float64,
    )
    metrics = frame_metrics(
        frame_index=0,
        time_s=0.0,
        positions=positions,
        valid=np.ones(4, dtype=np.uint8),
        particle_type=np.full(4, FLUID_TYPE, dtype=np.int8),
        mass=np.ones(4),
        particle_ids=np.asarray([10, 11, 12, 13], dtype=np.uint64),
        initial_fluid_ids=np.asarray([10, 11, 12, 13], dtype=np.uint64),
    )
    require(metrics["penetration"]["one_dp"]["count"] == 1, "synthetic 1DP count mismatch")
    require(metrics["penetration"]["two_dp"]["count"] == 0, "synthetic 2DP count mismatch")
    require(metrics["bed_domain"]["finite_bed_footprint_evaluable_count"] == 1, "synthetic footprint mismatch")
    require(metrics["nonfinite_initial_fluid_uid_count"] == 1, "synthetic nonfinite UID mismatch")
    require(metrics["unexplained_state"]["cause_assigned"] is False, "synthetic causal claim")
    print("source-only synthetic API checks passed")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--binding", type=Path)
    parser.add_argument("--trajectory-h5", type=Path)
    parser.add_argument("--xdmf", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    if args.check:
        _synthetic_check()
        return 0
    required = (args.binding, args.trajectory_h5, args.xdmf, args.output_dir)
    if any(value is None for value in required):
        parser.error("--binding, --trajectory-h5, --xdmf, and --output-dir are required")
    run_worker(
        binding_path=args.binding,
        trajectory_h5=args.trajectory_h5,
        xdmf=args.xdmf,
        output_dir=args.output_dir,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
