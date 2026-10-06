#!/usr/bin/env python3
"""Strict, read-only 801-frame native bed-footprint audit for F5 C082S1.

This source-only handoff is deliberately disabled until Root binds the actual
full native solver receipt and the future full H5/XDMF conversion products.  A real
invocation reads those products read-only and writes one JSON report.  It
never starts DualSPHysics, GenCase, PartVTK, or a converter.

The penetration metrics are calculated only for finite Type-3 fluid rows whose
coordinates lie in the exact source profile x domain and in the actual bed
footprint y interval [-0.22, 0.22] m.  Every frame retains the complete
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


BINDING_SCHEMA = "ds02.f5.c082s1.full-event-bed-audit-binding.fresh138.v1"
SCHEMA = "ds02.f5.c082s1.full-event-bed-footprint-audit.fresh138.v1"
CASE_ID = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1"
PHYSICAL_CASE_PREFIX = "F5_COMPACT_RUNUP_RECOVERY_C082S1_"
SOURCE_H5_SCOPE_SCHEMA = "legacy-owner-scope.v0"
SOURCE_H5_SCOPE_STATUS = "legacy_incomplete; no cross-resolution physical claim"
FLUID_TYPE = 3
DP_M = 0.02
DEPTH_TOLERANCES_M = (DP_M, 2.0 * DP_M)
EXPECTED_FRAMES = 801
EXPECTED_PARTICLE_AXIS = 194427
EXPECTED_FLUID_PARTICLES = 31658
EXPECTED_FIXED_PARTICLES = 158559
EXPECTED_MOVING_PARTICLES = 4210
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
BED_Y_BOUNDS_M = (-0.22, 0.22)
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
                f"frame-zero valid Type-3 UID set; all {initial_count} initial "
                "UIDs remain the reference denominator even when current rows "
                "are invalid, nonfinite, outside x, or outside the bed y footprint"
            ),
            "penetration_counts": (
                "only finite current valid Type-3 rows inside exact profile x "
                f"domain and y in {list(BED_Y_BOUNDS_M)} m"
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
    require(h5_values.size == EXPECTED_FRAMES, "H5 time axis is not 801 frames")
    require(xdmf_values.size == EXPECTED_FRAMES, "XDMF time axis is not 801 frames")
    finite = np.isfinite(h5_values) & np.isfinite(xdmf_values)
    strictly_increasing = bool(np.all(np.diff(h5_values) > 0.0))
    require(
        bool(finite.all())
        and h5_values[0] == 0.0
        and h5_values[-1] >= 16.0
        and strictly_increasing
        and np.allclose(h5_values, xdmf_values, rtol=0.0, atol=TIME_ATOL_S),
        "H5/XDMF time axes differ or do not cover the complete 0..16 s full event",
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
    """Validate one fresh138 case using metadata before opening H5/XDMF arrays."""
    require(binding.get("schema") == BINDING_SCHEMA, "fresh138 binding schema mismatch")
    case_id = str(binding.get("case_id", ""))
    physical_case_id = str(binding.get("physical_case_id", ""))
    require(case_id == CASE_ID and physical_case_id.startswith(PHYSICAL_CASE_PREFIX), "F5 case/physical identity mismatch")
    require(binding.get("expected_dimension") == 3 and binding.get("expected_frames") == EXPECTED_FRAMES, "3-D/801 frame contract mismatch")
    expected_axis = int(binding.get("expected_particle_axis", 0)); expected_fluid = int(binding.get("expected_fluid_particles", 0))
    expected_fixed = int(binding.get("expected_fixed_particles", 0)); expected_moving = int(binding.get("expected_moving_particles", 0))
    require((expected_axis, expected_fluid, expected_fixed, expected_moving) == (EXPECTED_PARTICLE_AXIS, EXPECTED_FLUID_PARTICLES, EXPECTED_FIXED_PARTICLES, EXPECTED_MOVING_PARTICLES), "producer-bound counts mismatch")
    require(binding.get("native_bed_marker_mk") == 50 and binding.get("source_bed_marker_mkbound") == 40, "Mk50/mkbound40 mapping changed")
    canonical_hash = str(binding.get("physical_condition_sha256", "")); source_plan_hash = str(binding.get("source_plan_physical_condition_sha256", "")); source_h5_hash = str(binding.get("source_h5_physical_condition_sha256", ""))
    require(is_bound(canonical_hash) and is_bound(source_plan_hash) and is_bound(source_h5_hash), "future producer scope hashes are not bound")
    require(canonical_hash != source_plan_hash and canonical_hash != source_h5_hash, "physical scopes collapsed")
    semantics = binding.get("physical_condition_hash_semantics", {})
    require(semantics.get("canonical_owner_sha256") == canonical_hash and semantics.get("source_h5_sha256") == source_h5_hash, "scope semantics incomplete")
    require(semantics.get("source_h5_scope_schema") == SOURCE_H5_SCOPE_SCHEMA and semantics.get("source_h5_scope_status") == SOURCE_H5_SCOPE_STATUS, "legacy H5 scope semantics changed")
    records=[]
    for role,path_key,hash_key in (("gencase_receipt","gencase_receipt","gencase_receipt_sha256"),("gencase_prepared_report","gencase_prepared_report","gencase_prepared_report_sha256"),("initial_qa_receipt","initial_qa_receipt","initial_qa_receipt_sha256"),("initial_qa_report","initial_qa_report","initial_qa_report_sha256"),("full_native_receipt","full_native_receipt","full_native_receipt_sha256"),("typed_conversion_report","full_typed_conversion_report","full_typed_conversion_report_sha256"),("generated_xml","canonical_generated_xml","canonical_generated_xml_sha256"),("xmf_manifest","xmf_manifest","xmf_manifest_sha256")):
        raw_path,raw_hash=binding.get(path_key),binding.get(hash_key)
        require(is_bound(raw_path) and is_bound(raw_hash), f"{role} not Root-bound")
        path=Path(str(raw_path)).resolve(); require(path.is_file(), f"{role} missing: {path}"); actual=sha256_file(path); require(actual==raw_hash, f"{role} SHA mismatch")
        records.append({"role":role,"path":str(path),"sha256":actual})
    gencase=load_json(Path(str(binding["gencase_receipt"]))); require(gencase.get("status") in {"completed","completed/0"} and gencase.get("returncode")==0, "GenCase not completed/0")
    nested_case=gencase.get("request",{}).get("case_id",gencase.get("case_id")); require(nested_case==case_id, "GenCase case identity mismatch")
    receipt_root=Path(str(gencase.get("output_root",""))).resolve(); prepared_root=Path(str(binding["gencase_prepared_output_root"])).resolve(); output_root=Path(str(binding["gencase_output_root"])).resolve(); require(receipt_root==output_root, "GenCase output root mismatch")
    generated_xml=Path(str(binding["canonical_generated_xml"])).resolve(); require(generated_xml.parent==prepared_root, "generated XML outside prepared root")
    prepared=load_json(Path(str(binding["gencase_prepared_report"]))); require(prepared.get("case_id")==case_id, "prepared report case mismatch")
    counts=prepared.get("generated_xml_particle_counts",{}); require({k:int(counts.get(k,-1)) for k in ("fixed","moving","floating","fluid")} == {"fixed":expected_fixed,"moving":expected_moving,"floating":int(binding.get("expected_floating_particles",0)),"fluid":expected_fluid}, "prepared counts mismatch")
    require(prepared.get("actual_total_particles")==expected_axis and prepared.get("xml_sha256")==binding.get("canonical_generated_xml_sha256"), "prepared total/XML mismatch")
    qr=load_json(Path(str(binding["initial_qa_receipt"]))); require(qr.get("status")=="completed" and qr.get("returncode")==0, "initial QA receipt not completed/0")
    require(Path(str(qr.get("output_root",""))).resolve()==Path(str(binding["initial_qa_output_root"])).resolve(), "initial QA output root mismatch")
    placement=load_json(Path(str(binding["initial_qa_report"]))); require(placement.get("all_basic_placement_checks_pass") is True and placement.get("stage1_basic_placement_proof")=="pass_excluding_numerical_precision", "initial placement proof changed")
    require(placement.get("numerical_precision_result_accepted") is False and placement.get("actual_counts")==binding.get("actual_counts"), "precision/count evidence changed")
    bins=placement.get("mk50_coverage",{}).get("six_segment_bins",[]); central=[int(row.get("central_abs_y_le_0p01_surface_half_dp_count",0)) for row in bins]; require(len(central)==6 and all(v>0 for v in central), "central Mk50 support incomplete")
    solver=load_json(Path(str(binding["full_native_receipt"]))); require(solver.get("status")=="completed" and solver.get("returncode")==0, "native receipt not completed/0")
    require(solver.get("request",{}).get("case_id",solver.get("case_id"))==case_id, "native receipt case identity mismatch")
    require(Path(str(solver.get("output_root",""))).resolve()==Path(str(binding["full_native_output_root"])).resolve(), "native output root mismatch")
    command=solver.get("command",[]); require(any(str(x).startswith("-tmax:16") for x in command) and any(str(x).startswith("-tout:0.02") for x in command), "native 16s/.02 contract mismatch")
    data_root=Path(str(binding["full_native_data_root"])).resolve(); require(data_root.is_dir(), "native data root missing"); require(sorted(p.name for p in data_root.glob("Part_*.bi4")) == [f"Part_{i:04d}.bi4" for i in range(EXPECTED_FRAMES)], "native frame filename sequence mismatch")
    conversion=load_json(Path(str(binding["full_typed_conversion_report"]))); status=conversion.get("conversion_status",conversion.get("status")); require(status=="completed" and conversion.get("frames")==EXPECTED_FRAMES and conversion.get("particles")==expected_axis, "typed conversion dimensions mismatch")
    dim=conversion.get("solver_dimension",{}); require((dim.get("solver_dimension",dim.get("value",3)) if isinstance(dim,dict) else dim)==3, "typed conversion is not 3-D")
    identity=conversion.get("typed_identity",{}); role_counts={}
    for block in identity.get("blocks",[]):
        if isinstance(block,dict): role_counts[str(block.get("tag",""))]=role_counts.get(str(block.get("tag","")),0)+int(block.get("count",0))
    require(role_counts.get("fixed")==expected_fixed and role_counts.get("moving")==expected_moving and role_counts.get("fluid")==expected_fluid, "typed identity counts mismatch")
    require(50 in set(identity.get("observed_mks",[])) and {0,1,3}.issubset(set(identity.get("observed_types",[]))), "typed Mk/type identity incomplete")
    manifest=load_json(Path(str(binding["xmf_manifest"]))); require(manifest.get("case_id")==case_id and manifest.get("frames")==EXPECTED_FRAMES and manifest.get("particles")==expected_axis, "XMF dimensions/identity mismatch")
    require(manifest.get("source_h5_sha256")==binding.get("trajectory_h5_sha256"), "XMF H5 digest mismatch")
    require(manifest.get("physical_condition_sha256")==canonical_hash and manifest.get("canonical_physical_condition_sha256")==canonical_hash, "XMF canonical scope mismatch")
    return {"records":records,"case_id":case_id,"physical_case_id":physical_case_id,"stage1_placement":{"all_basic_placement_checks_pass":True,"numerical_precision_result_accepted":False,"central_mk50_surface_half_dp_counts":central},"full_native_solver":{"saved_state_count":EXPECTED_FRAMES},"native_conversion":{"frames":EXPECTED_FRAMES,"particles":expected_axis,"native_bed_marker_mk":50,"source_bed_marker_mkbound":40}}

def run_worker(
    *,
    binding_path: Path,
    trajectory_h5: Path,
    xdmf: Path,
    output_dir: Path,
) -> dict[str, Any]:
    import h5py

    binding = load_json(binding_path)
    require(binding.get("schema") == BINDING_SCHEMA, "fresh138 binding schema mismatch")
    metadata = _verify_bound_metadata(binding)
    expected_particle_axis = int(binding["expected_particle_axis"])
    expected_fluid_particles = int(binding["expected_fluid_particles"])
    expected_fixed_particles = int(binding["expected_fixed_particles"])
    expected_moving_particles = int(binding["expected_moving_particles"])
    case_id = str(binding["case_id"])
    physical_case_id = str(binding["physical_case_id"])
    canonical_physical_condition_sha256 = str(binding["physical_condition_sha256"])
    source_plan_physical_condition_sha256 = str(binding["source_plan_physical_condition_sha256"])
    source_h5_physical_condition_sha256 = str(binding["source_h5_physical_condition_sha256"])
    source_h5_scope_schema = str(binding.get("source_h5_scope_schema", "producer-declared"))
    source_h5_scope_status = str(binding.get("source_h5_scope_status", "producer-declared; no cross-resolution claim"))
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
        require(source_h5_condition == source_h5_physical_condition_sha256,
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
        require(positions_ds.shape[0] == EXPECTED_FRAMES, "position frame count is not 801")
        require(positions_ds.shape[1] == expected_particle_axis, f"particle axis is not {expected_particle_axis}")
        for name, dataset in (("valid", valid_ds), ("type", type_ds), ("mass", mass_ds)):
            require(dataset.shape[0] == EXPECTED_FRAMES, f"{name} frame count is not 801")
            require(dataset.shape[1] == expected_particle_axis, f"{name} particle axis mismatch")
        particle_ids = np.asarray(particle_ids_ds[...]).reshape(-1)
        require(particle_ids.size == expected_particle_axis, "particle_id axis mismatch")
        require(np.isfinite(particle_ids.astype(np.float64)).all(), "particle_id has nonfinite values")
        require(np.unique(particle_ids).size == expected_particle_axis, "particle_id is not unique")
        frame0_valid = np.asarray(valid_ds[0, ...]).reshape(-1).astype(bool, copy=False)
        frame0_type = np.asarray(type_ds[0, ...]).reshape(-1)
        initial_mask = frame0_valid & (frame0_type == FLUID_TYPE)
        initial_fluid_ids = np.asarray(particle_ids[initial_mask], dtype=np.uint64)
        require(initial_fluid_ids.size == expected_fluid_particles, "frame-zero fluid UID count mismatch")
        require(np.unique(initial_fluid_ids).size == expected_fluid_particles, "frame-zero fluid UIDs are not unique")
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

    require(len(frame_reports) == EXPECTED_FRAMES, "did not produce 801 frame reports")
    report = {
        "schema": SCHEMA,
        "status": "completed_worker_output_pending_root_review",
        "diagnostic_only": True,
        "repair_success": "unknown_until_full_event_bed_audit_review",
        "full16_authorized": False,
        "production_approval": "none",
        "q_n_status": "not_granted",
        "source_arrays_modified": False,
        "source_arrays_dropped_or_masked": False,
        "physical_condition_sha256": canonical_physical_condition_sha256,
        "source_plan_physical_condition_sha256": source_plan_physical_condition_sha256,
        "source_h5_physical_condition_sha256": source_h5_physical_condition_sha256,
        "physical_condition_hash_semantics": {
            "canonical_owner_sha256": canonical_physical_condition_sha256,
            "source_h5_sha256": source_h5_physical_condition_sha256,
            "source_h5_scope_schema": source_h5_scope_schema,
            "source_h5_scope_status": source_h5_scope_status,
            "relation": "distinct; H5 attribute was validated against producer legacy scope and never substituted for canonical owner",
        },
        "native_identity_contract": {
            "total_particles": expected_particle_axis,
            "fixed_particles": expected_fixed_particles,
            "moving_particles": expected_moving_particles,
            "fluid_particles": expected_fluid_particles,
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
            "frame_indices": [0, 1, 2, 400, 800],
            "full_scan_range": [0, 800],
            "times_s": {
                "first": float(h5_times[0]),
                "last": float(h5_times[-1]),
                "nominal_save_interval_s": 0.02,
                "min_actual_step_s": float(np.min(np.diff(h5_times))),
                "max_actual_step_s": float(np.max(np.diff(h5_times))),
                "uniform_spacing_assumption": False,
            },
            "particle_axis_count": expected_particle_axis,
            "initial_fluid_uid_count": expected_fluid_particles,
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
            "uid_count": expected_fluid_particles,
            "uid_digest_sorted_uint64le_sha256": uid_digest(initial_fluid_ids),
            "all_uids_retained_as_reference_denominator": True,
        },
        "frame_reports": frame_reports,
        "dynamic_bed_diagnostic": {
            "scope": "all 801 actual native saved frames; finite active Type-3 fluid rows inside exact profile x and y footprint",
            "native_bed_marker_mk": 50,
            "source_bed_marker_mkbound": 40,
            "stage1_central_mk50_support_provenance": metadata.get("stage1_placement", {}).get("central_mk50_surface_half_dp_counts"),
            "reports_one_dp_two_dp_counts_fractions_depths": True,
            "reports_nonfinite_and_lost_initial_uids": True,
            "thresholds_are_diagnostic_only": True,
            "dynamic_acceptance": "not granted; Root must review all frames and visual render",
        },
        "interpretation_boundary": {
            "penetration_scope": (
                "finite current Type-3 rows inside exact x profile and y "
                f"{list(BED_Y_BOUNDS_M)} bed footprint only"
            ),
            "one_dp_and_two_dp": "diagnostic depth bins with counts and ratios; no threshold relaxation or acceptance gate",
            "nonfinite_or_lost_uid": "reported per frame with UID digest/sample and cause unassigned",
            "repair_success": "not inferred from this source-only worker; Root review required",
            "full_event_limit": "0..16 s full event; short-event pass is not reused and full-case acceptance remains pending",
        },
    }
    output_path = output_dir / "c082s1-full-event-bed-footprint-audit.json"
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
            [0.0, 0.23, -0.03],
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
