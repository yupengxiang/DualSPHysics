#!/usr/bin/env python3
"""Source-bound F4-S1 saved-frame transport diagnostics (forward V3).

This module is deliberately independent of the consumed F4-S1 V1 stream.  It
implements the finite-aperture operator used by this forward request instead
of importing the legacy ``compute_curve_and_events`` operator.  The operator
only records what can be established from adjacent saved trajectory frames:

* a crossing is accepted when the line segment intersects ``x=plane_x`` and
  the intersection point is inside the finite ``(y,z)`` aperture;
* crossing counts are kept per typed identity ``(Zone, Idp)``.  A later saved
  crossing is counted separately from the first crossing for that identity;
* event time is a saved-record bracket, never a continuous event time;
* invalid fluid identities are accumulated against the whole initial fluid
  mass.  They remain numerical/identity unknowns and are never called a
  physical exit or a flux.

The real worker reads only the already-produced trajectory HDF5 and the
source-bound small files declared by the V3 manifest.  It does not run a
solver, decode BI4, read PartOut, or modify any producer artifact.  The
manufactured fixtures in :func:`operator_regression_fixtures` are regression
tests for geometry and censoring semantics; they do not qualify a physical
case.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

import h5py
import numpy as np


SCHEMA = "ds02.stage2.f4-s1-stream.v3"
MANIFEST_SCHEMA = "ds02.stage2.f4-s1-stream-manifest.v3"
EXPECTED_FAMILY = "F4"
EXPECTED_CASE = "F4_DROP_gap0p22000_xoff0p00000_yoff0p00000_uz0p50000"
EXPECTED_ARTIFACT_PREFIX = "f4_drop_gap0p22000_xoff0p00000_yoff0p00000_uz0p50000"
EXPECTED_ARTIFACT_SUFFIXES = (
    "coarse-native",
    "medium-native",
    "fine-native",
    "fine-half_dt",
    "fine-half_save",
)
EXPECTED_VARIANT = {
    "coarse-native": ("coarse", "native"),
    "medium-native": ("medium", "native"),
    "fine-native": ("fine", "native"),
    "fine-half_dt": ("fine", "half_dt"),
    "fine-half_save": ("fine", "half_save"),
}
REQUIRED_H5 = (
    "time",
    "particle_id",
    "particle_zone",
    "initial_type",
    "initial_mk",
    "initial_mass",
    "valid",
    "type",
    "mk",
    "position",
    "velocity",
    "mass",
)
SOURCE_BINDING_KEYS = (
    "definition_xml",
    "gencase_receipt",
    "generated_xml",
    "owner_metadata_source",
    "solver_log",
    "solver_receipt",
)


class StreamContractError(RuntimeError):
    """Raised when a V3 request or source closure is malformed."""


def _json_default(value: Any) -> Any:
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"not JSON serializable: {type(value)!r}")


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=_json_default).encode("utf-8")
    ).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: Path) -> Any:
    try:
        with Path(path).open(encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise StreamContractError(f"missing JSON input: {path}") from exc
    except json.JSONDecodeError as exc:
        raise StreamContractError(f"invalid JSON input: {path}: {exc}") from exc


def _load_object(path: Path) -> dict[str, Any]:
    value = _load_json(path)
    if not isinstance(value, dict):
        raise StreamContractError(f"expected JSON object: {path}")
    return value


def _path_hash_entry(value: Any, label: str) -> tuple[Path, str]:
    if not isinstance(value, Mapping) or not isinstance(value.get("path"), str) or not isinstance(value.get("sha256"), str):
        raise StreamContractError(f"{label} must contain string path and sha256")
    digest = str(value["sha256"])
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest.lower()):
        raise StreamContractError(f"{label}.sha256 is not a hexadecimal SHA-256 digest")
    return Path(str(value["path"])), digest


def _verify_small_file(value: Any, label: str, *, require_exists: bool) -> tuple[Path, str]:
    path, expected = _path_hash_entry(value, label)
    if not require_exists:
        return path, expected
    if not path.is_file():
        raise StreamContractError(f"{label} is not a file: {path}")
    actual = sha256_file(path)
    if actual != expected:
        raise StreamContractError(f"{label} SHA mismatch: expected {expected}, got {actual}: {path}")
    return path, actual


def _validate_metadata(metadata_path: Path, expected_binding: str, *, require_exists: bool) -> dict[str, Any]:
    if not require_exists:
        return {}
    metadata = _load_object(metadata_path)
    if metadata.get("schema") != "ds02.f4.direct-binding.v1":
        raise StreamContractError(f"unexpected F4 metadata schema: {metadata_path}")
    if metadata.get("family_id") != EXPECTED_FAMILY or metadata.get("physical_case_id") != EXPECTED_CASE:
        raise StreamContractError(f"metadata physical identity mismatch: {metadata_path}")
    if metadata.get("mechanism_id") != "finite_drop_pool":
        raise StreamContractError(f"unexpected F4 mechanism: {metadata_path}")
    if metadata.get("physical_binding_sha256") != expected_binding:
        raise StreamContractError(f"metadata physical binding mismatch: {metadata_path}")
    binding = metadata.get("physical_binding")
    if not isinstance(binding, Mapping) or binding.get("family_id") != EXPECTED_FAMILY:
        raise StreamContractError(f"metadata physical binding is not F4: {metadata_path}")
    event_window = binding.get("event_window")
    if not isinstance(event_window, Mapping) or event_window.get("time_start_s") != 0.0 or event_window.get("time_end_s") != 1.2:
        raise StreamContractError(f"metadata event window is not the frozen [0,1.2] window: {metadata_path}")
    typed = metadata.get("typed_identity_binding")
    if not isinstance(typed, Mapping) or typed.get("fluid_mkfluid_to_native_mk") != {"0": 1, "1": 2}:
        raise StreamContractError(f"metadata typed identity mapping is not the F4-S1 mapping: {metadata_path}")
    source_binding = metadata.get("source_binding")
    if not isinstance(source_binding, Mapping):
        raise StreamContractError(f"metadata has no source_binding closure: {metadata_path}")
    for key in SOURCE_BINDING_KEYS:
        _path_hash_entry(source_binding.get(key), f"metadata.source_binding.{key}")
    return metadata


def _validate_source_binding(
    item: Mapping[str, Any],
    metadata: Mapping[str, Any],
    *,
    require_exists: bool,
) -> dict[str, dict[str, str]]:
    """Require actual producer/control/geometry provenance, not a lone binding SHA."""

    declared = item.get("source_binding")
    metadata_binding = metadata.get("source_binding")
    if not isinstance(declared, Mapping) or not isinstance(metadata_binding, Mapping):
        raise StreamContractError("V3 artifact needs both declared and metadata source_binding")
    normalized: dict[str, dict[str, str]] = {}
    for key in SOURCE_BINDING_KEYS:
        declared_path, declared_sha = _verify_small_file(declared.get(key), f"source_binding.{key}", require_exists=require_exists)
        meta_path, meta_sha = _path_hash_entry(metadata_binding.get(key), f"metadata.source_binding.{key}")
        if str(declared_path) != str(meta_path) or declared_sha != meta_sha:
            raise StreamContractError(f"source binding mismatch between manifest and metadata: {key}")
        normalized[key] = {"path": str(declared_path), "sha256": declared_sha}
    identity = item.get("source_identity")
    if not isinstance(identity, Mapping):
        raise StreamContractError("source_identity is required; physical_binding_sha256 alone is insufficient")
    physical = metadata.get("physical_binding")
    if isinstance(physical, Mapping):
        expected = {
            "physical_case_id": EXPECTED_CASE,
            "physical_binding_sha256": item.get("physical_binding_sha256"),
            "control_family_id": physical.get("control_family_id"),
            "geometry_family_id": physical.get("geometry_family_id"),
            "lineage_group_id": physical.get("lineage_group_id"),
            "mass_policy": physical.get("mass_policy"),
        }
        expected_typed = metadata.get("typed_identity_binding")
    else:
        # JSON-only request tests intentionally do not open the metadata file.
        # They still have to provide the complete identity tuple so this path
        # cannot turn a physical_binding SHA into an identity claim.
        source_identity = item.get("source_identity")
        if not isinstance(source_identity, Mapping):
            raise StreamContractError("source_identity is required for JSON-only validation")
        expected = {
            "physical_case_id": EXPECTED_CASE,
            "physical_binding_sha256": item.get("physical_binding_sha256"),
            "control_family_id": "F4_native_dbc_verlet_wendland_v1",
            "geometry_family_id": "F4_finite_drop_pool_finite_geometry_v1",
            "lineage_group_id": "finite_drop_pool_frozen_geometry_control_domain",
            "mass_policy": "native_rho_dp_cubed_no_rescaling",
        }
        expected_typed = {
            "fluid_mkfluid_to_native_mk": {"0": 1, "1": 2},
            "source": "generated XML typed fluid ranges",
        }
    for key, expected_value in expected.items():
        if identity.get(key) != expected_value:
            raise StreamContractError(f"source_identity mismatch for {key}")
    actual_typed = identity.get("typed_identity_binding")
    if not isinstance(actual_typed, Mapping) or actual_typed.get("fluid_mkfluid_to_native_mk") != expected_typed.get("fluid_mkfluid_to_native_mk"):
        raise StreamContractError("source_identity typed identity mapping mismatch")
    if not isinstance(actual_typed.get("source"), str) or not actual_typed["source"].strip():
        raise StreamContractError("source_identity typed identity source provenance is missing")
    if isinstance(physical, Mapping) and actual_typed != expected_typed:
        raise StreamContractError("source_identity typed identity provenance mismatch")
    return normalized


def validate_manifest_dict(manifest: Mapping[str, Any], *, require_files: bool = False) -> list[dict[str, Any]]:
    """Validate V3 identity and source closure without reading trajectory HDF5."""

    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise StreamContractError(f"unexpected V3 manifest schema: {manifest.get('schema')!r}")
    if manifest.get("family_id") != EXPECTED_FAMILY or manifest.get("case_id") != EXPECTED_CASE:
        raise StreamContractError("F4-S1 V3 manifest physical identity mismatch")
    if manifest.get("trajectory_read_policy") != "guarded_h5_read_only_no_bi4_no_solver":
        raise StreamContractError("V3 manifest trajectory read policy is not HDF5-only")
    claim_boundary = manifest.get("claim_boundary")
    if not isinstance(claim_boundary, Mapping):
        raise StreamContractError("V3 claim_boundary is required")
    if claim_boundary.get("physical_fate") != "unknown" or claim_boundary.get("continuous_event_time_between_saved_frames") != "unknown":
        raise StreamContractError("V3 cannot claim physical fate or continuous event time")
    operator_contract = manifest.get("operator_contract")
    if not isinstance(operator_contract, Mapping) or operator_contract.get("schema") != "ds02.stage2.f4-typed-operator.v3":
        raise StreamContractError("V3 operator contract is missing")
    if operator_contract.get("mass_denominator") != "whole_initial_fluid_mass_kg":
        raise StreamContractError("V3 must use the whole initial fluid mass denominator")
    if operator_contract.get("legacy_event_budget_fraction") is not None or operator_contract.get("legacy_temporal_item_allocation") is not None:
        raise StreamContractError("legacy 2% event or 20% temporal thresholds cannot enter V3")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != len(EXPECTED_ARTIFACT_SUFFIXES):
        raise StreamContractError("V3 manifest must contain exactly five artifacts")
    seen: set[str] = set()
    validated: list[dict[str, Any]] = []
    for item in artifacts:
        if not isinstance(item, dict):
            raise StreamContractError("V3 artifact must be an object")
        artifact_id = item.get("artifact_id")
        if not isinstance(artifact_id, str) or artifact_id in seen:
            raise StreamContractError(f"duplicate or invalid artifact id: {artifact_id!r}")
        seen.add(artifact_id)
        prefix = EXPECTED_ARTIFACT_PREFIX + "-"
        if not artifact_id.startswith(prefix) or artifact_id[len(prefix):] not in EXPECTED_ARTIFACT_SUFFIXES:
            raise StreamContractError(f"unsupported F4-S1 V3 artifact id: {artifact_id}")
        variant = artifact_id[len(prefix):]
        resolution, time_variant = EXPECTED_VARIANT[variant]
        if item.get("case_id") != EXPECTED_CASE or item.get("resolution") != resolution or item.get("time_variant") != time_variant:
            raise StreamContractError(f"V3 variant identity mismatch: {artifact_id}")
        if item.get("physical_binding_sha256") != manifest.get("physical_binding_sha256"):
            raise StreamContractError(f"V3 physical binding mismatch: {artifact_id}")
        for key in ("trajectory_hdf5", "metadata", "conversion_report", "conversion_receipt", "source_regions"):
            _path_hash_entry(item.get(key), f"{artifact_id}.{key}")
        h5_path, h5_sha = _path_hash_entry(item["trajectory_hdf5"], f"{artifact_id}.trajectory_hdf5")
        if require_files and not h5_path.is_file():
            raise StreamContractError(f"trajectory_hdf5 path is not a file: {h5_path}")
        metadata_path, metadata_sha = _verify_small_file(item["metadata"], f"{artifact_id}.metadata", require_exists=require_files)
        conversion_path, conversion_sha = _verify_small_file(item["conversion_report"], f"{artifact_id}.conversion_report", require_exists=require_files)
        receipt_path, receipt_sha = _verify_small_file(item["conversion_receipt"], f"{artifact_id}.conversion_receipt", require_exists=require_files)
        regions_path, regions_sha = _verify_small_file(item["source_regions"], f"{artifact_id}.source_regions", require_exists=require_files)
        metadata = _validate_metadata(metadata_path, str(manifest["physical_binding_sha256"]), require_exists=require_files)
        source_binding = _validate_source_binding(item, metadata, require_exists=require_files) if require_files else _validate_source_binding(item, {"source_binding": item.get("source_binding")}, require_exists=False)
        if require_files:
            conversion = _load_object(conversion_path)
            receipt = _load_object(receipt_path)
            regions = _load_object(regions_path)
            if conversion.get("schema") and not str(conversion["schema"]).startswith("ds-data-02.bi4-direct-conversion"):
                raise StreamContractError(f"unexpected conversion schema: {conversion_path}")
            if receipt.get("status") not in {"completed", "completed_actual", "success"}:
                raise StreamContractError(f"conversion receipt is not completed: {receipt_path}")
            if not isinstance(regions, Mapping):
                raise StreamContractError(f"source regions is not an object: {regions_path}")
        validated.append({
            **item,
            "variant": variant,
            "trajectory_hdf5_path": str(h5_path),
            "trajectory_hdf5_sha256": h5_sha,
            "metadata_path": str(metadata_path),
            "metadata_sha256": metadata_sha,
            "conversion_report_path": str(conversion_path),
            "conversion_report_sha256": conversion_sha,
            "conversion_receipt_path": str(receipt_path),
            "conversion_receipt_sha256": receipt_sha,
            "source_regions_path": str(regions_path),
            "source_regions_sha256": regions_sha,
            "source_binding_normalized": source_binding,
        })
    if {item["variant"] for item in validated} != set(EXPECTED_ARTIFACT_SUFFIXES):
        raise StreamContractError("V3 manifest does not cover all variants")
    return validated


def _source_mapping(metadata: Mapping[str, Any]) -> tuple[dict[int, str], dict[str, int]]:
    binding = metadata.get("physical_binding")
    typed = metadata.get("typed_identity_binding")
    if not isinstance(binding, Mapping) or not isinstance(typed, Mapping):
        raise StreamContractError("metadata lacks physical/typed binding")
    labels = binding.get("initial_state", {}).get("source_labels", {})
    mapping = typed.get("fluid_mkfluid_to_native_mk", {})
    if not isinstance(labels, Mapping) or not isinstance(mapping, Mapping):
        raise StreamContractError("metadata source mapping is malformed")
    mk_to_source: dict[int, str] = {}
    source_to_mk: dict[str, int] = {}
    for mkfluid, native_mk in mapping.items():
        label = labels.get(f"mkfluid:{int(mkfluid)}")
        if label is None:
            raise StreamContractError(f"missing source label for mkfluid {mkfluid}")
        mk_to_source[int(native_mk)] = str(label)
        source_to_mk[str(label)] = int(native_mk)
    if len(mk_to_source) < 2:
        raise StreamContractError("F4-S1 requires both typed fluid sources")
    return mk_to_source, source_to_mk


def _finite_aperture(metadata: Mapping[str, Any]) -> tuple[float, np.ndarray, np.ndarray]:
    binding = metadata.get("physical_binding")
    if not isinstance(binding, Mapping) or binding.get("mechanism_id") != "finite_drop_pool":
        raise StreamContractError("V3 supports only finite_drop_pool")
    geometry = binding.get("geometry")
    if not isinstance(geometry, Mapping) or not isinstance(geometry.get("pool"), Mapping):
        raise StreamContractError("F4 pool geometry is missing")
    pool = geometry["pool"]
    low = np.asarray(pool.get("low_m"), dtype=np.float64)
    size = np.asarray(pool.get("size_m"), dtype=np.float64)
    if low.shape != (3,) or size.shape != (3,) or not np.isfinite(low).all() or not np.isfinite(size).all() or np.any(size <= 0):
        raise StreamContractError("F4 pool geometry is invalid")
    high = low + size
    return float(high[0]), low[[1, 2]], high[[1, 2]]


def segment_plane_aperture(
    previous_position: Sequence[float],
    current_position: Sequence[float],
    *,
    plane_x: float,
    aperture_low_yz: Sequence[float],
    aperture_high_yz: Sequence[float],
) -> dict[str, Any]:
    """Classify one saved segment at a finite x-plane.

    The x crossing uses a half-open convention ``x0 < plane <= x1`` for a
    positive crossing and ``x0 >= plane > x1`` for a negative crossing.  The
    y/z aperture is evaluated at the exact line/plane intersection, which
    handles endpoints outside the aperture and avoids counting an endpoint
    that leaves the aperture before reaching the plane.
    """

    p0 = np.asarray(previous_position, dtype=np.float64)
    p1 = np.asarray(current_position, dtype=np.float64)
    low = np.asarray(aperture_low_yz, dtype=np.float64)
    high = np.asarray(aperture_high_yz, dtype=np.float64)
    if p0.shape != (3,) or p1.shape != (3,) or low.shape != (2,) or high.shape != (2,) or not np.isfinite(np.concatenate((p0, p1, low, high))).all():
        raise ValueError("segment and aperture must be finite vectors")
    if np.any(high < low):
        raise ValueError("aperture high must not be below low")
    x0, x1 = float(p0[0]), float(p1[0])
    if x0 == x1:
        return {
            "crossing": False,
            "status": "coplanar_segment" if x0 == float(plane_x) else "no_crossing",
            "direction": None,
            "u": None,
            "intersection_m": None,
            "aperture_at_plane": False,
        }
    direction: str | None
    if x0 < float(plane_x) <= x1:
        direction = "positive_x"
    elif x0 >= float(plane_x) > x1:
        direction = "negative_x"
    else:
        direction = None
    if direction is None:
        return {
            "crossing": False,
            "status": "no_crossing",
            "direction": None,
            "u": None,
            "intersection_m": None,
            "aperture_at_plane": False,
        }
    u = (float(plane_x) - x0) / (x1 - x0)
    point = p0 + u * (p1 - p0)
    in_aperture = bool(np.all(point[[1, 2]] >= low) and np.all(point[[1, 2]] <= high))
    return {
        "crossing": True,
        "status": "accepted" if in_aperture else "outside_aperture",
        "direction": direction,
        "u": float(u),
        "intersection_m": [float(value) for value in point],
        "aperture_at_plane": in_aperture,
    }


def _new_particle_event() -> dict[str, Any]:
    return {
        "total_saved_crossings": 0,
        "first_saved_crossings": 0,
        "later_saved_crossings": 0,
        "positive_saved_crossings": 0,
        "negative_saved_crossings": 0,
        "saved_initial_mass_kg": 0.0,
        "first_bracket_s": None,
        "first_direction": None,
        "later_brackets_s": [],
    }


def _new_source_event() -> dict[str, Any]:
    return {
        "candidate_plane_crossings": 0,
        "outside_aperture_crossings": 0,
        "accepted_saved_crossings": 0,
        "first_saved_crossings": 0,
        "later_saved_crossings": 0,
        "positive_saved_crossings": 0,
        "negative_saved_crossings": 0,
        "accepted_saved_initial_mass_kg": 0.0,
        "finite_aperture_saved_mass_time_kg_s": 0.0,
        "finite_aperture_saved_frame_count": 0,
        "first_passage_bracket_s": None,
        "per_typed_identity": {},
        "semantics": {
            "crossing_counts": "saved-record crossings accepted at the finite plane/aperture intersection",
            "later_saved_crossings": "accepted crossings after the first for the same (Zone,Idp)",
            "continuous_event_time": "unknown; only adjacent saved-record bracket is retained",
            "physical_flux": "unknown; counts are not a flux or fate classification",
        },
    }


def _record_crossing(
    source_event: dict[str, Any],
    *,
    typed_key: str,
    event: Mapping[str, Any],
    bracket: list[float],
    initial_mass_kg: float,
) -> None:
    source_event["accepted_saved_crossings"] += 1
    direction = str(event["direction"])
    if direction == "positive_x":
        source_event["positive_saved_crossings"] += 1
    else:
        source_event["negative_saved_crossings"] += 1
    source_event["accepted_saved_initial_mass_kg"] += float(initial_mass_kg)
    identity = source_event["per_typed_identity"].setdefault(typed_key, _new_particle_event())
    is_first = identity["total_saved_crossings"] == 0
    identity["total_saved_crossings"] += 1
    identity["saved_initial_mass_kg"] += float(initial_mass_kg)
    if direction == "positive_x":
        identity["positive_saved_crossings"] += 1
    else:
        identity["negative_saved_crossings"] += 1
    if is_first:
        source_event["first_saved_crossings"] += 1
        identity["first_saved_crossings"] = 1
        identity["first_bracket_s"] = [float(bracket[0]), float(bracket[1])]
        identity["first_direction"] = direction
        if source_event["first_passage_bracket_s"] is None:
            source_event["first_passage_bracket_s"] = [float(bracket[0]), float(bracket[1])]
    else:
        source_event["later_saved_crossings"] += 1
        identity["later_saved_crossings"] += 1
        identity["later_brackets_s"].append([float(bracket[0]), float(bracket[1])])


def _csv_fields(source_labels: Sequence[str]) -> list[str]:
    fields = [
        "frame",
        "time_s",
        "active_fluid_mass_kg",
        "unknown_fluid_mass_kg",
        "unknown_fluid_fraction_whole_initial",
        "cumulative_unique_unknown_fluid_mass_kg",
        "cumulative_unique_unknown_fluid_fraction_whole_initial",
        "unknown_fluid_id_count",
        "active_momentum_x_kg_m_s",
        "active_momentum_y_kg_m_s",
        "active_momentum_z_kg_m_s",
        "active_kinetic_energy_j",
    ]
    for label in source_labels:
        fields.extend(
            (
                f"{label}_active_mass_kg",
                f"{label}_finite_aperture_mass_kg",
                f"{label}_finite_aperture_particles",
                f"{label}_momentum_x_kg_m_s",
                f"{label}_momentum_y_kg_m_s",
                f"{label}_momentum_z_kg_m_s",
                f"{label}_kinetic_energy_j",
            )
        )
    return fields


def compute_typed_stream_v3(
    *,
    h5_path: Path,
    metadata: Mapping[str, Any],
    output_csv: Path,
    declared_h5_sha256: str,
) -> dict[str, Any]:
    """Read one trajectory once and emit saved-frame macro/event diagnostics."""

    mk_to_source, source_to_mk = _source_mapping(metadata)
    source_labels = sorted(source_to_mk)
    plane_x, aperture_low, aperture_high = _finite_aperture(metadata)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    source_events = {label: _new_source_event() for label in source_labels}
    rows = 0
    malformed = []
    with h5py.File(h5_path, "r") as h5:
        missing = [name for name in REQUIRED_H5 if name not in h5]
        if missing:
            raise StreamContractError(f"trajectory lacks required datasets: {missing}")
        times = np.asarray(h5["time"][...], dtype=np.float64)
        ids = np.asarray(h5["particle_id"][...], dtype=np.int64)
        zones = np.asarray(h5["particle_zone"][...], dtype=np.int64)
        initial_type = np.asarray(h5["initial_type"][...], dtype=np.int8)
        initial_mk = np.asarray(h5["initial_mk"][...], dtype=np.int16)
        initial_mass = np.asarray(h5["initial_mass"][...], dtype=np.float64)
        frames = int(times.size)
        particles = int(ids.size)
        if frames < 1 or particles < 1 or not np.isfinite(times).all() or (frames > 1 and not np.all(np.diff(times) > 0)):
            raise StreamContractError("trajectory time axis is not finite and increasing")
        for name in REQUIRED_H5:
            if name in {"time", "particle_id", "particle_zone", "initial_type", "initial_mk", "initial_mass"}:
                continue
            if h5[name].shape[:2] != (frames, particles):
                raise StreamContractError(f"trajectory dataset shape mismatch: {name}: {h5[name].shape}")
        if initial_mass.shape != (particles,) or not np.isfinite(initial_mass).all() or np.any(initial_mass <= 0):
            raise StreamContractError("initial_mass must be finite positive per typed identity")
        fluid = initial_type == 3
        initial_fluid_mass = float(np.sum(initial_mass[fluid]))
        if initial_fluid_mass <= 0:
            raise StreamContractError("trajectory has no positive initial fluid mass")
        source_indices = {
            label: np.flatnonzero(fluid & (initial_mk == native_mk))
            for label, native_mk in source_to_mk.items()
        }
        previous_positions = np.full((particles, 3), np.nan, dtype=np.float64)
        previous_valid = np.zeros(particles, dtype=bool)
        ever_unknown = np.zeros(particles, dtype=bool)
        fields = _csv_fields(source_labels)
        with output_csv.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for frame in range(frames):
                time_s = float(times[frame])
                valid_raw = np.asarray(h5["valid"][frame, ...])
                valid = np.asarray(valid_raw, dtype=bool)
                types = np.asarray(h5["type"][frame, ...], dtype=np.int8)
                positions = np.asarray(h5["position"][frame, ...], dtype=np.float64)
                velocities = np.asarray(h5["velocity"][frame, ...], dtype=np.float64)
                masses = np.asarray(h5["mass"][frame, ...], dtype=np.float64)
                if valid.shape != (particles,) or positions.shape != (particles, 3) or velocities.shape != (particles, 3) or masses.shape != (particles,):
                    raise StreamContractError(f"trajectory frame shape mismatch at frame {frame}")
                active = valid & fluid & (types == 3)
                current_unknown = fluid & ~valid
                ever_unknown |= current_unknown
                unknown_mass = float(np.sum(initial_mass[current_unknown]))
                unique_unknown_mass = float(np.sum(initial_mass[ever_unknown]))
                row: dict[str, Any] = {
                    "frame": frame,
                    "time_s": time_s,
                    "active_fluid_mass_kg": float(np.sum(masses[active])),
                    "unknown_fluid_mass_kg": unknown_mass,
                    "unknown_fluid_fraction_whole_initial": unknown_mass / initial_fluid_mass,
                    "cumulative_unique_unknown_fluid_mass_kg": unique_unknown_mass,
                    "cumulative_unique_unknown_fluid_fraction_whole_initial": unique_unknown_mass / initial_fluid_mass,
                    "unknown_fluid_id_count": int(np.sum(current_unknown)),
                    "active_momentum_x_kg_m_s": float(np.sum(masses[active] * velocities[active, 0])),
                    "active_momentum_y_kg_m_s": float(np.sum(masses[active] * velocities[active, 1])),
                    "active_momentum_z_kg_m_s": float(np.sum(masses[active] * velocities[active, 2])),
                    "active_kinetic_energy_j": float(0.5 * np.sum(masses[active] * np.sum(velocities[active] ** 2, axis=1))),
                }
                for label in source_labels:
                    source_index = source_indices[label]
                    source_active = active[source_index]
                    selected = source_index[source_active]
                    selected_positions = positions[selected]
                    selected_velocities = velocities[selected]
                    selected_masses = masses[selected]
                    aperture = np.zeros(particles, dtype=bool)
                    if selected.size:
                        aperture[selected] = (
                            np.all(selected_positions[:, [1, 2]] >= aperture_low, axis=1)
                            & np.all(selected_positions[:, [1, 2]] <= aperture_high, axis=1)
                        )
                    aperture_selected = selected[aperture[selected]]
                    row[f"{label}_active_mass_kg"] = float(np.sum(selected_masses))
                    row[f"{label}_finite_aperture_mass_kg"] = float(np.sum(masses[aperture_selected]))
                    row[f"{label}_finite_aperture_particles"] = int(aperture_selected.size)
                    row[f"{label}_momentum_x_kg_m_s"] = float(np.sum(selected_masses * selected_velocities[:, 0]))
                    row[f"{label}_momentum_y_kg_m_s"] = float(np.sum(selected_masses * selected_velocities[:, 1]))
                    row[f"{label}_momentum_z_kg_m_s"] = float(np.sum(selected_masses * selected_velocities[:, 2]))
                    row[f"{label}_kinetic_energy_j"] = float(0.5 * np.sum(selected_masses * np.sum(selected_velocities ** 2, axis=1)))
                    source_events[label]["finite_aperture_saved_mass_time_kg_s"] += float(np.sum(masses[aperture_selected])) * (0.0 if frame == 0 else time_s - float(times[frame - 1]))
                    source_events[label]["finite_aperture_saved_frame_count"] += int(aperture_selected.size > 0)
                    if frame > 0:
                        for index in selected.tolist():
                            if not previous_valid[index] or not np.isfinite(previous_positions[index]).all():
                                continue
                            event = segment_plane_aperture(
                                previous_positions[index],
                                positions[index],
                                plane_x=plane_x,
                                aperture_low_yz=aperture_low,
                                aperture_high_yz=aperture_high,
                            )
                            if not event["crossing"]:
                                continue
                            source_events[label]["candidate_plane_crossings"] += 1
                            bracket = [float(times[frame - 1]), time_s]
                            if not event["aperture_at_plane"]:
                                source_events[label]["outside_aperture_crossings"] += 1
                                continue
                            typed_key = f"{int(zones[index])}:{int(ids[index])}"
                            _record_crossing(
                                source_events[label],
                                typed_key=typed_key,
                                event=event,
                                bracket=bracket,
                                initial_mass_kg=float(initial_mass[index]),
                            )
                writer.writerow(row)
                rows += 1
                previous_positions = positions.copy()
                previous_valid = valid.copy()
        typed_keys = {(int(zone), int(idp)) for zone, idp in zip(zones, ids)}
        if len(typed_keys) != particles:
            malformed.append("duplicate_typed_identity")
    return {
        "schema": "ds02.stage2.f4-s1-typed-stream-artifact.v3",
        "trajectory_hdf5": {"path": str(h5_path), "declared_sha256": declared_h5_sha256, "worker_rehashed": False},
        "frames": rows,
        "particles": particles,
        "saved_time_window_s": [float(times[0]), float(times[-1])],
        "finite_aperture": {
            "plane_x_m": plane_x,
            "low_yz_m": [float(value) for value in aperture_low],
            "high_yz_m": [float(value) for value in aperture_high],
            "intersection_rule": "evaluate y/z at the line-segment intersection with x=plane_x; inclusive bounds",
        },
        "whole_initial_fluid_mass_kg": initial_fluid_mass,
        "source_initial_mass_kg": {label: float(np.sum(initial_mass[index])) for label, index in source_indices.items()},
        "source_event_data": source_events,
        "unknown_identity_policy": {
            "denominator": "whole_initial_fluid_mass_kg",
            "missing_identity": "numerical_unknown",
            "cumulative_unique_unknown": "identity remains unknown after first invalid saved frame, even if later valid",
            "physical_fate_inferred": False,
        },
        "errors": malformed,
        "status": "saved_frame_source_bound_diagnostic; no_physical_flux_or_calibration_credit",
    }


def _unknown_fraction_fixture(initial_mass: Sequence[float], valid_frames: Sequence[Sequence[bool]]) -> list[dict[str, float | int]]:
    masses = np.asarray(initial_mass, dtype=np.float64)
    ever_missing = np.zeros(masses.size, dtype=bool)
    total = float(np.sum(masses))
    result = []
    for frame, flags in enumerate(valid_frames):
        valid = np.asarray(flags, dtype=bool)
        missing = ~valid
        ever_missing |= missing
        current = float(np.sum(masses[missing]))
        unique = float(np.sum(masses[ever_missing]))
        result.append({
            "frame": frame,
            "current_unknown_mass_kg": current,
            "current_unknown_fraction_whole_initial": current / total,
            "cumulative_unique_unknown_mass_kg": unique,
            "cumulative_unique_unknown_fraction_whole_initial": unique / total,
        })
    return result


def operator_regression_fixtures() -> dict[str, Any]:
    """Return deterministic geometry/censoring fixtures used by V3 tests."""

    low = np.asarray([-0.1, -0.1])
    high = np.asarray([0.1, 0.1])
    endpoints_outside = segment_plane_aperture(
        [-1.0, -1.0, 0.0], [1.0, 1.0, 0.0], plane_x=0.0, aperture_low_yz=low, aperture_high_yz=high
    )
    inside_endpoint_plane_outside = segment_plane_aperture(
        [-1.0, 0.0, 0.0], [1.0, 1.0, 0.0], plane_x=0.0, aperture_low_yz=low, aperture_high_yz=high
    )
    first_in = segment_plane_aperture(
        [-1.0, 0.0, 0.0], [1.0, 0.0, 0.0], plane_x=0.0, aperture_low_yz=low, aperture_high_yz=high
    )
    later_out = segment_plane_aperture(
        [1.0, 0.0, 0.0], [-1.0, 0.0, 0.0], plane_x=0.0, aperture_low_yz=low, aperture_high_yz=high
    )
    events = _new_source_event()
    _record_crossing(events, typed_key="7:42", event=first_in, bracket=[0.0, 1.0], initial_mass_kg=2.0)
    _record_crossing(events, typed_key="7:42", event=later_out, bracket=[1.0, 2.0], initial_mass_kg=2.0)
    unknown = _unknown_fraction_fixture([1.0, 2.0, 3.0], [[True, True, True], [True, False, True], [True, True, True]])
    return {
        "schema": "ds02.stage2.f4-typed-operator-v3-regression.v1",
        "endpoints_outside_but_plane_intersection_inside": endpoints_outside,
        "inside_endpoint_but_plane_intersection_outside": inside_endpoint_plane_outside,
        "same_identity_first_then_later_crossing": events,
        "missing_identity_whole_initial_accumulation": unknown,
        "interpretation": "manufactured operator regression only; no physical F4 result or calibration credit",
    }


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=_json_default) + "\n", encoding="utf-8")


def run(*, manifest_path: Path, output_dir: Path) -> dict[str, Any]:
    if output_dir.exists():
        leftovers = [path for path in output_dir.iterdir() if path.name not in {"stdout.log", "execution-receipt.json"}]
        if leftovers:
            raise StreamContractError(f"refusing to overwrite output directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = _load_object(manifest_path)
    entries = validate_manifest_dict(manifest, require_files=True)
    started = time.monotonic()
    artifacts = []
    for item in sorted(entries, key=lambda value: EXPECTED_ARTIFACT_SUFFIXES.index(value["variant"])):
        metadata_path = Path(item["metadata_path"])
        metadata = _load_object(metadata_path)
        artifact_dir = output_dir / "artifacts" / str(item["artifact_id"])
        artifact_dir.mkdir(parents=True, exist_ok=True)
        curve_path = artifact_dir / "typed-science-timeseries-v3.csv"
        science = compute_typed_stream_v3(
            h5_path=Path(item["trajectory_hdf5_path"]),
            metadata=metadata,
            output_csv=curve_path,
            declared_h5_sha256=str(item["trajectory_hdf5_sha256"]),
        )
        labels_path = artifact_dir / "typed-science-labels-v3.json"
        _write_json(labels_path, science["source_event_data"])
        report = {
            **science,
            "artifact_id": item["artifact_id"],
            "case_id": item["case_id"],
            "resolution": item["resolution"],
            "time_variant": item["time_variant"],
            "metadata": {"path": str(metadata_path), "sha256": item["metadata_sha256"]},
            "conversion_report": {"path": item["conversion_report_path"], "sha256": item["conversion_report_sha256"]},
            "conversion_receipt": {"path": item["conversion_receipt_path"], "sha256": item["conversion_receipt_sha256"]},
            "source_regions": {"path": item["source_regions_path"], "sha256": item["source_regions_sha256"]},
            "source_binding": item["source_binding_normalized"],
            "physical_binding_sha256": item["physical_binding_sha256"],
            "curve": {"path": str(curve_path), "sha256": sha256_file(curve_path), "rows": science["frames"]},
            "labels": {"path": str(labels_path), "sha256": sha256_file(labels_path)},
            "legacy_operator_comparison": {
                "legacy_compute_curve_and_events_used": False,
                "legacy_event_budget_fraction_used": None,
                "legacy_temporal_item_allocation_used": None,
                "legacy_repeat_crossings_reused": False,
                "reason": "V3 counts per typed identity and uses exact saved-segment plane intersections; old aggregate endpoint operator is not a Stage2 calibration source",
            },
            "claim_boundary": {
                "continuous_event_time_between_saved_frames": "unknown",
                "physical_fate": "unknown",
                "physical_flux": "unknown",
                "position_velocity_energy_error": "unknown",
                "q_n": "not_assessed",
                "q_e": "not_assessed",
                "calibration_credit": "not_granted; manufactured regression only",
            },
        }
        _write_json(artifact_dir / "f4-s1-stream-artifact-v3.json", report)
        artifacts.append(report)
    output_report = {
        "schema": SCHEMA,
        "attempt_status": "completed_actual_source_bound_saved_frame_diagnostics",
        "manifest": {"path": str(manifest_path), "sha256": sha256_file(manifest_path)},
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "operator_regression_fixtures": operator_regression_fixtures(),
        "claim_boundary": manifest["claim_boundary"],
        "trajectory_read_policy": manifest["trajectory_read_policy"],
        "legacy_semantics": {
            "old_event_budget_fraction": "not imported",
            "old_temporal_item_allocation": "not imported",
            "old_repeat_crossings": "not imported",
            "old_endpoint_aperture_test": "not imported",
            "physical_fate": "unknown",
        },
        "resource": {"wall_seconds": time.monotonic() - started},
    }
    report_path = output_dir / "f4-s1-stream-v3-report.json"
    _write_json(report_path, output_report)
    output_report["report"] = {"path": str(report_path), "sha256": sha256_file(report_path)}
    return output_report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", nargs="?", choices=("run",), default="run")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    report = run(manifest_path=args.manifest, output_dir=args.output)
    print(json.dumps({"report": report["report"], "artifacts": report["artifact_count"], "status": report["attempt_status"]}, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
