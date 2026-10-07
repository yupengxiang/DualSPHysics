#!/usr/bin/env python3
"""Source-bound, model-free F2-S1 replay operators (development v11).

The consumed v5--v9 modules remain byte-frozen.  This version validates an
exact CURRENT/manifest/XML/motion/scan/producer binding, reads only a bounded
approved HDF5 window, and evaluates an in-memory trajectory with the same
identity, mass, geometry, and event operators.  Every scientific quality and
qualification field remains UNKNOWN.

Velocity is always reported in the inertial world frame.  A body-frame
position transform never silently relabels velocity as body-frame or relative
velocity.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence
import xml.etree.ElementTree as ET

import numpy as np


REQUEST_SCHEMA = "ds02.stage2.f2-s1-replay-request.v11"
RESULT_SCHEMA = "ds02.stage2.f2-s1-replay-result.v11"
CALIBRATION_SCHEMA = "ds02.stage2.f2-s1-replay-calibration.v11"
EVALUATION_SCHEMA = "ds02.stage2.f2-s1-replay-evaluation.v11"
OBSERVER_PROFILE_SCHEMA = "ds02.stage2.f2-s1-observer-profile.v11"
_HEX64 = __import__("re").compile(r"^[0-9a-f]{64}$")


class ReplayV11BindingError(ValueError):
    """Raised when a replay source, array, or semantic binding is invalid."""


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    """Hash a JSON object without its self-reported hash field."""
    payload = {key: item for key, item in value.items() if key != "sha256"}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def _trajectory_float_array(value: Any, name: str, *, ndim: int | None = None) -> np.ndarray:
    """Keep native float32 trajectory storage to bound the full-window peak."""
    try:
        result = np.asarray(value)
    except (TypeError, ValueError) as error:
        raise ReplayV11BindingError(f"{name} must be numeric") from error
    if not np.issubdtype(result.dtype, np.number):
        raise ReplayV11BindingError(f"{name} must be numeric")
    if ndim is not None and result.ndim != ndim:
        raise ReplayV11BindingError(f"{name} must have ndim={ndim}")
    if not np.issubdtype(result.dtype, np.floating):
        result = result.astype("float32")
    return result


def sha256(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _require_sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None:
        raise ReplayV11BindingError(f"{name} must be a lowercase SHA-256")
    return value


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, np.number)):
        raise ReplayV11BindingError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ReplayV11BindingError(f"{name} must be finite")
    return result


def _float_array(value: Any, name: str, *, ndim: int | None = None) -> np.ndarray:
    try:
        result = np.asarray(value, dtype="float64")
    except (TypeError, ValueError) as error:
        raise ReplayV11BindingError(f"{name} must be numeric") from error
    if ndim is not None and result.ndim != ndim:
        raise ReplayV11BindingError(f"{name} must have ndim={ndim}")
    return result


def _numeric_array(value: Any, name: str) -> np.ndarray:
    try:
        return np.asarray(value)
    except (TypeError, ValueError) as error:
        raise ReplayV11BindingError(f"{name} is not an array") from error


def _strict_increasing(value: Any, name: str) -> np.ndarray:
    result = _float_array(value, name).reshape(-1)
    if len(result) < 2 or not np.isfinite(result).all() or np.any(np.diff(result) <= 0):
        raise ReplayV11BindingError(f"{name} must be finite and strictly increasing")
    return result


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ReplayV11BindingError(f"{name} must be a positive integer")
    return value


def _finite_vector(value: Any, name: str) -> np.ndarray:
    result = _float_array(value, name)
    if result.shape != (3,) or not np.isfinite(result).all():
        raise ReplayV11BindingError(f"{name} must have finite shape (3,)")
    return result


def _verify_small_source(item: Mapping[str, Any], index: int, *, verify: bool) -> dict[str, Any]:
    if not isinstance(item, Mapping) or not isinstance(item.get("path"), str):
        raise ReplayV11BindingError(f"source_files[{index}] is malformed")
    expected = _require_sha(item.get("sha256"), f"source_files[{index}].sha256")
    path = Path(item["path"]).expanduser()
    if not path.exists() or not path.is_file():
        raise ReplayV11BindingError(f"source_files[{index}] is missing: {path}")
    if path.suffix.lower() in {".h5", ".hdf5"}:
        raise ReplayV11BindingError("trajectory HDF5 cannot be a small source file")
    actual = sha256(path) if verify else None
    if actual is not None and actual != expected:
        raise ReplayV11BindingError(f"source_files[{index}] SHA-256 differs")
    stat = path.stat()
    return {"role": item.get("role"), "path": str(path.resolve()), "sha256": expected,
            "verified_sha256": actual, "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def _verify_hdf5_stat(binding: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(binding, Mapping) or not isinstance(binding.get("path"), str):
        raise ReplayV11BindingError("trajectory_h5 binding is malformed")
    path = Path(binding["path"]).expanduser()
    if path.suffix.lower() not in {".h5", ".hdf5"} or not path.is_file():
        raise ReplayV11BindingError(f"trajectory_h5 is missing or not HDF5: {path}")
    stat = path.stat()
    if stat.st_size != int(binding.get("bytes", -1)) or stat.st_mtime_ns != int(binding.get("mtime_ns", -1)):
        raise ReplayV11BindingError("trajectory_h5 bytes/mtime differ from producer stats")
    producer = _require_sha(binding.get("producer_declared_sha256"), "trajectory_h5.producer_declared_sha256")
    if binding.get("hash_mode") != "producer_attested_only_no_content_hash":
        raise ReplayV11BindingError("trajectory HDF5 must use producer-attested-only hash mode")
    return {"path": str(path.resolve()), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns,
            "producer_declared_sha256": producer, "content_sha256": None,
            "read_status": "NOT_READ_BY_BINDING_VALIDATOR"}


def _cross_check_source_metadata(request: Mapping[str, Any], source_files: Sequence[Mapping[str, Any]],
                                 h5: Mapping[str, Any]) -> None:
    """Cross-check producer metadata after small source hashes are verified."""
    by_role = {item.get("role"): Path(item["path"]) for item in source_files}
    current = json.loads(by_role["current_catalog"].read_text())
    cases = current.get("cases")
    if not isinstance(cases, list) or len(cases) <= 78 or not isinstance(cases[78], Mapping):
        raise ReplayV11BindingError("CURRENT cases list/index is malformed")
    row = cases[78]
    identity = request["case_identity"]
    if row.get("family_id") != "F2" or row.get("physical_case_id") != identity["physical_case_id"] or row.get("runtime_case_alias") != identity["runtime_case_alias"]:
        raise ReplayV11BindingError("CURRENT row identity differs from request")
    if row.get("frames") != 401 or row.get("particles") != 418104:
        raise ReplayV11BindingError("CURRENT row shape differs from request")
    if row.get("trajectory", {}).get("path") != h5["path"] or row.get("trajectory", {}).get("producer_declared_sha256") != h5["producer_declared_sha256"]:
        raise ReplayV11BindingError("CURRENT trajectory producer binding differs")
    manifest = json.loads(by_role["manifest"].read_text())
    for key in ("case_id", "physical_case_id"):
        if manifest.get(key) != request["case_identity"].get("manifest_" + key, request["case_identity"].get(key)):
            raise ReplayV11BindingError(f"manifest {key} differs from request")
    if manifest.get("trajectory_h5") != h5["path"] or manifest.get("source_h5_sha256") != h5["producer_declared_sha256"]:
        raise ReplayV11BindingError("manifest HDF5 binding differs")
    scan = json.loads(by_role["scientific_scan_sidecar"].read_text())
    if (scan.get("family_id") != "F2" or scan.get("physical_case_id") != request["case_identity"]["physical_case_id"] or
            scan.get("trajectory") != h5["path"] or scan.get("source_bytes") != h5["bytes"] or
            scan.get("source_mtime_ns") != h5["mtime_ns"] or scan.get("frames") != 401 or scan.get("particles") != 418104):
        raise ReplayV11BindingError("scientific scan source binding differs")
    if scan.get("full_saved_timeline_scanned") is not True:
        raise ReplayV11BindingError("scientific scan is not a complete saved timeline")
    fluid_ledger = scan.get("type_ledgers", {}).get("fluid", {})
    if fluid_ledger.get("type_code") != 3 or fluid_ledger.get("initial_active_count") != 21114:
        raise ReplayV11BindingError("scan fluid initial ledger differs from the bound cohort")
    initially_absent = fluid_ledger.get("initially_absent_count")
    if initially_absent != request["initial_mass_denominator"].get("initially_absent_count"):
        raise ReplayV11BindingError("scan initially-absent count differs from request")
    later_missing = fluid_ledger.get("cumulative_unique_missing")
    if later_missing != request["initial_mass_denominator"].get("later_missing_unique_count"):
        raise ReplayV11BindingError("scan later-missing count differs from request")
    records = scan.get("missing_id_records")
    if not isinstance(records, list) or len(records) != later_missing:
        raise ReplayV11BindingError("scan later-missing records are incomplete")
    record_mass = sum(float(item.get("initial_mass_kg", 0.0)) for item in records)
    if not math.isclose(record_mass, float(request["initial_mass_denominator"].get("later_missing_mass_kg", -1.0)),
                        rel_tol=0.0, abs_tol=1e-10):
        raise ReplayV11BindingError("scan later-missing mass differs from request")
    if initially_absent == 0 and request["initial_mass_denominator"].get("initial_missing_mass_kg") != 0.0:
        raise ReplayV11BindingError("later-missing mass must not be added to an initially complete denominator")
    initial_qa = json.loads(by_role["initial_qa"].read_text())
    if initial_qa.get("case_id") != request["case_identity"]["runtime_case_alias"] or initial_qa.get("status") != "pass":
        raise ReplayV11BindingError("initial QA source binding differs")
    if initial_qa.get("csv_summary", {}).get("fluid_type3_count") != 21114:
        raise ReplayV11BindingError("initial QA fluid cohort count differs")
    xml_root = ET.parse(by_role["generated_xml"]).getroot()
    motion_nodes = xml_root.findall(".//mvrotfile")
    if not motion_nodes or any(node.get("duration") != "4" or node.get("anglesunits") != "degrees" for node in motion_nodes):
        raise ReplayV11BindingError("generated XML motion duration/units differ")


def _validate_fixture_request(request: Mapping[str, Any]) -> dict[str, Any]:
    """Small local fixture contract used only by independent manufactured tests."""
    if request.get("fixture_mode") is not True:
        raise ReplayV11BindingError("fixture request must explicitly set fixture_mode")
    if request.get("role") != "DEVELOPMENT" or request.get("model_invoked") is not False:
        raise ReplayV11BindingError("manufactured fixture is not a development operator")
    qualification = request.get("qualification")
    if not isinstance(qualification, Mapping) or any(qualification.get(k) != "UNKNOWN" for k in ("QI", "QN", "QE")):
        raise ReplayV11BindingError("manufactured fixture qualification must remain UNKNOWN")
    if not isinstance(request.get("case_identity"), Mapping):
        raise ReplayV11BindingError("fixture case identity is required")
    source_files = request.get("source_files")
    if not isinstance(source_files, list) or not source_files:
        raise ReplayV11BindingError("fixture motion source is required")
    for i, item in enumerate(source_files):
        _verify_small_source(item, i, verify=False)
    cohort = request.get("cohort")
    if not isinstance(cohort, Mapping):
        raise ReplayV11BindingError("fixture cohort is required")
    if cohort.get("initial_type_code") != 3:
        raise ReplayV11BindingError("fixture cohort must use fluid type code 3")
    window = request.get("window")
    if not isinstance(window, Mapping):
        raise ReplayV11BindingError("fixture window is required")
    _strict_increasing(window.get("expected_times_s"), "fixture expected times")
    result = dict(request)
    result["_verified_sources"] = []
    result["_verified_hdf5"] = {}
    return result


def validate_replay_request(request: Mapping[str, Any], *, verify_sources: bool = False,
                            verify_hdf5_stat: bool = False) -> dict[str, Any]:
    """Validate the request without opening or content-hashing trajectory HDF5."""
    if not isinstance(request, Mapping) or request.get("schema") != REQUEST_SCHEMA:
        raise ReplayV11BindingError("unsupported v11 replay request schema")
    if request.get("role") != "DEVELOPMENT" or request.get("status") not in {"PENDING_IO_SLOT", "MANUFACTURED_ONLY"}:
        raise ReplayV11BindingError("request must remain pending DEVELOPMENT")
    if request.get("model_invoked") is not False:
        raise ReplayV11BindingError("model_invoked must be false")
    qualification = request.get("qualification")
    if not isinstance(qualification, Mapping) or any(qualification.get(k) != "UNKNOWN" for k in ("QI", "QN", "QE")):
        raise ReplayV11BindingError("v11 qualification must remain UNKNOWN")
    if request.get("fixture_mode") is True:
        return _validate_fixture_request(request)

    identity = request.get("case_identity")
    expected_identity = {
        "family_id": "F2",
        "physical_case_id": "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090",
        "runtime_case_alias": "F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010",
    }
    if not isinstance(identity, Mapping):
        raise ReplayV11BindingError("case_identity is required")
    for key, expected in expected_identity.items():
        if identity.get(key) != expected:
            raise ReplayV11BindingError(f"case_identity.{key} does not bind exact F2-S1")

    current = request.get("current_binding")
    if not isinstance(current, Mapping):
        raise ReplayV11BindingError("current_binding is required")
    _require_sha(current.get("sha256"), "current_binding.sha256")
    if current.get("case_index") != 78 or current.get("frames") != 401 or current.get("particles") != 418104:
        raise ReplayV11BindingError("CURRENT case index/shape binding is wrong")
    current_window = _float_array(current.get("actual_time_window_s"), "current_binding.actual_time_window_s").reshape(-1)
    if current_window.shape != (2,) or current_window[0] != 0.0 or current_window[1] <= 4.0:
        raise ReplayV11BindingError("CURRENT actual time window is not bound")

    source_files = request.get("source_files")
    if not isinstance(source_files, list) or not source_files:
        raise ReplayV11BindingError("source_files are required")
    verified_sources = [_verify_small_source(item, i, verify=verify_sources)
                        for i, item in enumerate(source_files)]
    roles = {item.get("role") for item in source_files if isinstance(item, Mapping)}
    required_roles = {
        "current_catalog", "manifest", "xmf", "generated_xml", "motion_dat",
        "conversion_report", "scientific_scan_sidecar", "initial_qa",
        "gencase_receipt", "solver_receipt", "owner_metadata",
        "native_runparts", "native_partout",
    }
    if not required_roles.issubset(roles):
        raise ReplayV11BindingError(f"source roles missing: {sorted(required_roles - roles)}")

    h5 = request.get("trajectory_h5")
    if verify_hdf5_stat:
        h5_verified = _verify_hdf5_stat(h5)
    else:
        if not isinstance(h5, Mapping) or not isinstance(h5.get("path"), str):
            raise ReplayV11BindingError("trajectory_h5 is required")
        _require_sha(h5.get("producer_declared_sha256"), "trajectory_h5.producer_declared_sha256")
        if h5.get("hash_mode") != "producer_attested_only_no_content_hash":
            raise ReplayV11BindingError("trajectory HDF5 must use producer-attested-only hash mode")
        if not isinstance(h5.get("bytes"), int) or not isinstance(h5.get("mtime_ns"), int):
            raise ReplayV11BindingError("trajectory HDF5 stats are required")
        h5_verified = {"path": h5["path"], "bytes": h5["bytes"], "mtime_ns": h5["mtime_ns"],
                       "producer_declared_sha256": h5["producer_declared_sha256"],
                       "content_sha256": None, "read_status": "NOT_READ_BY_BINDING_VALIDATOR"}
    if verify_sources:
        _cross_check_source_metadata(request, source_files, h5_verified)

    geometry = request.get("geometry")
    if not isinstance(geometry, Mapping):
        raise ReplayV11BindingError("geometry is required")
    low = _finite_vector(geometry.get("fluid_source_low_m"), "geometry.fluid_source_low_m")
    size = _finite_vector(geometry.get("fluid_source_size_m"), "geometry.fluid_source_size_m")
    if np.any(size <= 0):
        raise ReplayV11BindingError("fluid source size must be positive")
    axis1 = _finite_vector(geometry.get("moving_axis_p1_m"), "geometry.moving_axis_p1_m")
    axis2 = _finite_vector(geometry.get("moving_axis_p2_m"), "geometry.moving_axis_p2_m")
    if np.linalg.norm(axis2 - axis1) <= 0:
        raise ReplayV11BindingError("moving axis has zero length")
    if geometry.get("motion_angles_units") != "degrees" or _finite(geometry.get("motion_duration_s"), "geometry.motion_duration_s") != 4.0:
        raise ReplayV11BindingError("motion duration/units must come from actual 4 s XML control")
    if geometry.get("control_duration_s") is not None:
        raise ReplayV11BindingError("legacy 0.9 s control duration must remain absent")

    surface = request.get("event_surface")
    if (not isinstance(surface, Mapping) or surface.get("frame") != "world" or
            surface.get("kind") != "open_rim_front_halfspace_observation"):
        raise ReplayV11BindingError("event_surface must bind the explicit world open-rim diagnostic halfspace")
    _finite_vector(surface.get("origin_m"), "event_surface.origin_m")
    normal = _finite_vector(surface.get("normal"), "event_surface.normal")
    if not math.isclose(float(np.linalg.norm(normal)), 1.0, rel_tol=0.0, abs_tol=1e-12):
        raise ReplayV11BindingError("event surface normal must be unit length")
    if surface.get("positive_side") != "x_ge_origin_plane" or surface.get("target_claim") != "DIAGNOSTIC_HALFSPACE_ONLY":
        raise ReplayV11BindingError("halfspace observation cannot claim a closed receiver/aperture arrival")

    cohort = request.get("cohort")
    if not isinstance(cohort, Mapping) or cohort.get("selection") != "all_fluid_in_initial_source_region":
        raise ReplayV11BindingError("cohort must select continuous-source-region fluid")
    if cohort.get("initial_type_code") != 3 or cohort.get("initial_mk_codes") != [1, 2, 3]:
        raise ReplayV11BindingError("cohort must exclude fixed/moving walls and bind fluid MK codes")
    if cohort.get("expected_initial_fluid_count") != 21114 or cohort.get("max_particles") is not None:
        raise ReplayV11BindingError("request must use all 21114 fluid particles")

    window = request.get("window")
    if not isinstance(window, Mapping) or window.get("frame_start") != 0 or window.get("frame_stop") != 400:
        raise ReplayV11BindingError("request must bind the complete CURRENT 0..400 saved timeline")
    if window.get("mode") != "full_timeline_all_fluid_streaming_contract":
        raise ReplayV11BindingError("full replay reader mode is not bound")
    _positive_int(window.get("max_memory_bytes"), "window.max_memory_bytes")
    if window["max_memory_bytes"] > 1536 * 1024 * 1024:
        raise ReplayV11BindingError("full-window memory bound is too broad")
    expected_times = _strict_increasing(window.get("expected_times_s"), "window.expected_times_s")
    if len(expected_times) != 401 or expected_times[0] != 0.0 or expected_times[-1] <= 4.0:
        raise ReplayV11BindingError("full query times are not the frozen CURRENT timeline")

    native = request.get("native_exclusion")
    if not isinstance(native, Mapping) or native.get("runparts_excluded_count") != 3:
        raise ReplayV11BindingError("native RunPARTs exclusion count must be bound")
    if native.get("identity_mapping_status") not in {"UNKNOWN", "UNKNOWN_PENDING_SOURCE_RECONCILIATION"}:
        raise ReplayV11BindingError("native exclusion identity must remain conservative UNKNOWN")
    if native.get("exact_identity_ledger_status") not in {"PENDING_PRIMARY_INDEX", "AVAILABLE_SOURCE_BOUND"}:
        raise ReplayV11BindingError("native exact identity status cannot be fabricated unavailable or qualified")

    initial = request.get("initial_mass_denominator")
    if not isinstance(initial, Mapping):
        raise ReplayV11BindingError("initial_mass_denominator is required")
    for key in ("initial_fluid_mass_kg", "initial_missing_mass_kg", "denominator_kg",
                "later_missing_mass_kg"):
        _finite(initial.get(key), f"initial_mass_denominator.{key}")
    if initial["initial_fluid_mass_kg"] <= 0 or initial["initial_missing_mass_kg"] < 0:
        raise ReplayV11BindingError("initial mass denominator fields are invalid")
    if not math.isclose(initial["denominator_kg"], initial["initial_fluid_mass_kg"] + initial["initial_missing_mass_kg"], rel_tol=0.0, abs_tol=1e-10):
        raise ReplayV11BindingError("initial missing mass is omitted from denominator")
    if initial.get("initially_absent_count") != 0 or initial["initial_missing_mass_kg"] != 0.0:
        raise ReplayV11BindingError("this exact F2 source has no initially absent fluid; later missing mass cannot enlarge its denominator")
    if initial.get("later_missing_unique_count") != 3 or initial["later_missing_mass_kg"] <= 0:
        raise ReplayV11BindingError("later missing ledger is not bound separately")
    if initial["later_missing_mass_kg"] >= initial["denominator_kg"]:
        raise ReplayV11BindingError("later missing mass exceeds the frozen initial denominator")
    profile = request.get("observer_profile")
    if not isinstance(profile, Mapping):
        raise ReplayV11BindingError("frozen observer profile is required")
    validate_observer_profile(profile, request=request)
    result = dict(request)
    result["_verified_sources"] = verified_sources
    result["_verified_hdf5"] = h5_verified
    return result


def validate_observer_profile(profile: Mapping[str, Any], *, request: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Validate the frozen observer contract used by manual prediction scoring."""
    if not isinstance(profile, Mapping) or profile.get("schema") != OBSERVER_PROFILE_SCHEMA:
        raise ReplayV11BindingError("unsupported observer profile schema")
    if profile.get("frozen_before_reference") is not True or profile.get("scientific_status") != "DEVELOPMENT_PREREGISTERED_UNKNOWN":
        raise ReplayV11BindingError("observer profile is not frozen as a development profile")
    expected_hash = profile.get("sha256")
    if _require_sha(expected_hash, "observer_profile.sha256") != _canonical_sha256(profile):
        raise ReplayV11BindingError("observer profile self-hash differs")
    case = profile.get("case_identity")
    if not isinstance(case, Mapping) or case.get("family_id") != "F2" or not isinstance(case.get("physical_case_id"), str):
        raise ReplayV11BindingError("observer profile case identity is incomplete")
    indices = profile.get("query_frame_indices")
    times = _strict_increasing(profile.get("query_times_s"), "observer_profile.query_times_s")
    if not isinstance(indices, list) or len(indices) != len(times) or len(indices) < 2:
        raise ReplayV11BindingError("observer profile query frame/time shape is invalid")
    if any(isinstance(index, bool) or not isinstance(index, int) or index < 0 or index > 400 for index in indices):
        raise ReplayV11BindingError("observer profile query frame indices are invalid")
    if any(left >= right for left, right in zip(indices, indices[1:])):
        raise ReplayV11BindingError("observer profile query frame indices must increase")
    scale = _finite(profile.get("position_scale_m"), "observer_profile.position_scale_m")
    event_scale = _finite(profile.get("event_time_scale_s"), "observer_profile.event_time_scale_s")
    if scale <= 0 or event_scale <= 0:
        raise ReplayV11BindingError("observer profile physical scales must be positive")
    thresholds = profile.get("thresholds")
    if not isinstance(thresholds, Mapping):
        raise ReplayV11BindingError("observer profile thresholds are required")
    for key in ("position_relative", "mass_fraction", "event_time_fraction"):
        value = _finite(thresholds.get(key), f"observer_profile.thresholds.{key}")
        if value <= 0 or value > 1:
            raise ReplayV11BindingError("observer profile threshold is outside (0,1]")
    budgets = profile.get("budgets")
    if not isinstance(budgets, Mapping):
        raise ReplayV11BindingError("observer profile budgets are required")
    for key in ("time_fraction", "output_fraction"):
        value = _finite(budgets.get(key), f"observer_profile.budgets.{key}")
        if value <= 0 or value > 1:
            raise ReplayV11BindingError("observer profile budget fraction is outside (0,1]")
    names = profile.get("observable_names")
    expected_names = ["mass_weighted_com_m", "mass_weighted_mean_velocity_m_s",
                      "mass_weighted_kinetic_energy_J", "mass_quantile_front_m",
                      "mass_distribution_fraction", "event_status", "event_time_s"]
    if names != expected_names:
        raise ReplayV11BindingError("observer profile observable set is not frozen")
    quantiles = profile.get("mass_quantiles")
    bins = profile.get("normalized_bin_edges")
    if quantiles != [0.5, 0.75, 0.9, 1.0] or bins != [-2.0, -1.0, 0.0, 1.0, 2.0]:
        raise ReplayV11BindingError("observer profile mass fronts/distribution definitions are not frozen")
    if request is not None:
        if profile.get("current_binding_sha256") != request.get("current_binding", {}).get("sha256"):
            raise ReplayV11BindingError("observer profile CURRENT binding differs from request")
        if profile.get("case_identity") != request.get("case_identity"):
            raise ReplayV11BindingError("observer profile case identity differs from request")
        if not math.isclose(scale, float(request["observer"]["position_scale_m"]), rel_tol=0.0, abs_tol=1e-12):
            raise ReplayV11BindingError("observer profile scale differs from request observer")
        request_times = np.asarray(request["window"]["expected_times_s"], dtype=float)
        if not np.allclose(times, request_times[np.asarray(indices, dtype=int)], rtol=0.0, atol=2e-8):
            raise ReplayV11BindingError("observer profile query times are not CURRENT saved times")
        if profile.get("trajectory_producer_sha256") != request.get("trajectory_h5", {}).get("producer_declared_sha256"):
            raise ReplayV11BindingError("observer profile trajectory producer binding differs")
        if profile.get("source_file_sha256") != {item.get("role"): item.get("sha256") for item in request.get("source_files", [])}:
            raise ReplayV11BindingError("observer profile source hash set differs")
    return dict(profile)


def _prediction_array(predictions: Mapping[str, Any], name: str, shape: tuple[int, ...]) -> np.ndarray:
    value = _float_array(predictions.get(name), f"predictions.{name}")
    if value.shape != shape or not np.isfinite(value).all():
        raise ReplayV11BindingError(f"predictions.{name} must have finite shape {shape}")
    return value


def evaluate_manual_predictions(result: Mapping[str, Any], predictions: Mapping[str, Any],
                                profile: Mapping[str, Any]) -> dict[str, Any]:
    """Score hand-supplied macro/event predictions against replay observers.

    The function is deliberately source- and shape-bound.  It is a numerical
    development comparison; its pass/fail output never grants QI/QN/QE.
    """
    frozen = validate_observer_profile(profile)
    if not isinstance(result, Mapping) or result.get("schema") != RESULT_SCHEMA:
        raise ReplayV11BindingError("result is not a v11 replay result")
    if not isinstance(predictions, Mapping):
        raise ReplayV11BindingError("predictions must be an object")
    if predictions.get("total_tolerance") is not None or predictions.get("event_time_tolerance_fraction") is not None:
        raise ReplayV11BindingError("prediction-level tolerance overrides are forbidden")
    source = result.get("source_binding")
    if not isinstance(source, Mapping) or predictions.get("source_binding") != source:
        raise ReplayV11BindingError("predictions must bind the exact replay source hashes")
    if source.get("current_catalog_sha256") != frozen.get("current_binding_sha256") or source.get("trajectory_h5_producer_sha256") != frozen.get("trajectory_producer_sha256"):
        raise ReplayV11BindingError("result source binding differs from the frozen profile")
    if source.get("source_files") != frozen.get("source_file_sha256"):
        raise ReplayV11BindingError("result source file hash set differs from the frozen profile")
    if predictions.get("observer_profile_sha256") != frozen["sha256"]:
        raise ReplayV11BindingError("predictions use a different frozen observer profile")
    query_times = _strict_increasing(predictions.get("query_times_s"), "predictions.query_times_s")
    expected_times = np.asarray(frozen["query_times_s"], dtype=float)
    if query_times.shape != expected_times.shape or not np.array_equal(query_times, expected_times):
        raise ReplayV11BindingError("prediction query times differ from the frozen profile")
    frames = [int(value) for value in frozen["query_frame_indices"]]
    frame_map = {int(item["frame"]): item for item in result.get("frame_observations", []) if isinstance(item, Mapping)}
    try:
        observed = [frame_map[frame] for frame in frames]
    except KeyError as error:
        raise ReplayV11BindingError("replay result does not contain every frozen query frame") from error
    q = len(frames)
    com = _prediction_array(predictions, "mass_weighted_com_m", (q, 3))
    velocity = _prediction_array(predictions, "mass_weighted_mean_velocity_m_s", (q, 3))
    ke = _prediction_array(predictions, "mass_weighted_kinetic_energy_J", (q,))
    quantiles = frozen.get("mass_quantiles", [0.5, 0.75, 0.9, 1.0])
    fronts = _prediction_array(predictions, "mass_quantile_front_m", (q, len(quantiles)))
    bins = frozen.get("normalized_bin_edges")
    if not isinstance(bins, list) or len(bins) < 2:
        raise ReplayV11BindingError("observer profile distribution bins are missing")
    distribution = _prediction_array(predictions, "mass_distribution_fraction", (q, len(bins) - 1))
    if np.any(distribution < 0):
        raise ReplayV11BindingError("mass distribution fractions must be nonnegative")
    observed_com = np.asarray([item["mass_weighted_com_m"] for item in observed], dtype=float)
    observed_velocity = np.asarray([item.get("mass_weighted_mean_velocity_m_s") for item in observed], dtype=float)
    observed_ke = np.asarray([item.get("mass_weighted_kinetic_energy_J") for item in observed], dtype=float)
    observed_fronts = np.asarray([[item["mass_quantile_front_m"][str(value)] for value in quantiles] for item in observed], dtype=float)
    denominator = float(result["initial_mass_denominator"]["denominator_kg"])
    observed_distribution = np.asarray([item["mass_distribution_kg"] for item in observed], dtype=float) / denominator
    position_error = float(np.max(np.abs(com - observed_com)) / frozen["position_scale_m"])
    velocity_error = float(np.max(np.abs(velocity - observed_velocity)))
    ke_scale = max(1.0, float(np.max(np.abs(observed_ke))))
    kinetic_energy_relative_error = float(np.max(np.abs(ke - observed_ke)) / ke_scale)
    front_error = float(np.max(np.abs(fronts - observed_fronts)) / frozen["position_scale_m"])
    distribution_error = float(np.max(np.abs(distribution - observed_distribution)))
    labels = result.get("labels")
    if not isinstance(labels, list):
        raise ReplayV11BindingError("replay labels are missing")
    predicted_status = predictions.get("event_status")
    predicted_time = _float_array(predictions.get("event_time_s"), "predictions.event_time_s").reshape(-1)
    if not isinstance(predicted_status, list) or len(predicted_status) != len(labels) or len(predicted_time) != len(labels):
        raise ReplayV11BindingError("event prediction arrays have the wrong shape")
    status_matches = [predicted_status[i] == labels[i].get("status") for i in range(len(labels))]
    status_accuracy = float(np.mean(status_matches)) if status_matches else 0.0
    observed_time_errors = []
    for index, label in enumerate(labels):
        if label.get("status") == "observed":
            value = float(predicted_time[index])
            if not math.isfinite(value):
                raise ReplayV11BindingError("observed event predictions must have finite times")
            observed_time_errors.append(abs(value - float(label["event_time_s"])))
        elif math.isfinite(float(predicted_time[index])):
            raise ReplayV11BindingError("non-observed event predictions must use NaN event_time_s")
    event_time_error_fraction = (max(observed_time_errors) / frozen["event_time_scale_s"]
                                 if observed_time_errors else 0.0)
    elapsed = predictions.get("evaluation_seconds")
    output_bytes = predictions.get("output_bytes")
    if isinstance(elapsed, bool) or not isinstance(elapsed, (int, float)) or not math.isfinite(float(elapsed)) or float(elapsed) < 0:
        raise ReplayV11BindingError("evaluation_seconds is required and finite")
    if isinstance(output_bytes, bool) or not isinstance(output_bytes, int) or output_bytes < 0:
        raise ReplayV11BindingError("output_bytes is required as a nonnegative integer")
    budgets = frozen["budgets"]
    time_budget = float(frozen.get("reference_time_budget_s", 1.0)) * float(budgets["time_fraction"])
    output_budget = int(frozen.get("reference_output_budget_bytes", 1_000_000)) * float(budgets["output_fraction"])
    metrics = {
        "position_relative_max_error": position_error,
        "velocity_absolute_max_error_m_s": velocity_error,
        "kinetic_energy_relative_max_error": kinetic_energy_relative_error,
        "mass_front_relative_max_error": front_error,
        "mass_distribution_max_fraction_error": distribution_error,
        "event_status_accuracy": status_accuracy,
        "event_time_max_fraction_error": event_time_error_fraction,
        "time_seconds": float(elapsed), "time_budget_seconds": time_budget,
        "output_bytes": int(output_bytes), "output_budget_bytes": output_budget,
    }
    thresholds = frozen["thresholds"]
    checks = {
        "position": position_error <= float(thresholds["position_relative"]),
        "mass_distribution": distribution_error <= float(thresholds["mass_fraction"]),
        "event_time": event_time_error_fraction <= float(thresholds["event_time_fraction"]),
        "event_status": status_accuracy == 1.0,
        "time_budget": float(elapsed) <= time_budget,
        "output_budget": int(output_bytes) <= output_budget,
    }
    return {"schema": EVALUATION_SCHEMA, "status": "PASS" if all(checks.values()) else "FAIL",
            "development_only": True, "model_invoked": False, "checks": checks,
            "metrics": metrics, "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}}


def normalized_mass_velocity(velocities: Any, masses: Any, *, valid: Any | None = None,
                             weight_masses: Any | None = None) -> tuple[np.ndarray | None, float | None, float, float]:
    """Return normalized mass velocity, KE, known and missing *fixed* mass.

    ``weight_masses`` is used by the v11 replay for source-bound observables:
    particle mass at frame zero remains the accounting weight when a later
    frame has an invalid/missing current mass.  This prevents a NaN or a
    disappearance from silently changing the initial denominator.
    """
    vv = _float_array(velocities, "velocities")
    mm_current = _float_array(masses, "masses").reshape(-1)
    mm = mm_current if weight_masses is None else _float_array(weight_masses, "weight_masses").reshape(-1)
    if vv.ndim != 2 or vv.shape[1] != 3 or mm.shape != (len(vv),) or mm_current.shape != (len(vv),):
        raise ReplayV11BindingError("velocities/masses have incompatible shapes")
    active = np.isfinite(vv).all(axis=1) & np.isfinite(mm) & (mm > 0) & np.isfinite(mm_current) & (mm_current > 0)
    if valid is not None:
        valid_mask = np.asarray(valid, dtype=bool).reshape(-1)
        if valid_mask.shape != mm.shape:
            raise ReplayV11BindingError("valid has incompatible shape")
        active &= valid_mask
    known_mass = float(mm[active].sum())
    missing_mass = float(mm[np.isfinite(mm) & (mm > 0) & ~active].sum())
    if known_mass <= 0:
        return None, None, 0.0, missing_mass
    known_v, known_m = vv[active], mm[active]
    mean = (known_v * known_m[:, None]).sum(axis=0) / known_mass
    ke = float(0.5 * (known_m * (known_v * known_v).sum(axis=1)).sum())
    return mean, ke, known_mass, missing_mass


def _rotation_about_axis(axis: np.ndarray, angle_rad: float) -> np.ndarray:
    x, y, z = axis / np.linalg.norm(axis)
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    return np.array([
        [c + x*x*(1-c), x*y*(1-c)-z*s, x*z*(1-c)+y*s],
        [y*x*(1-c)+z*s, c + y*y*(1-c), y*z*(1-c)-x*s],
        [z*x*(1-c)-y*s, z*y*(1-c)+x*s, c + z*z*(1-c)],
    ])


def read_motion_dat(path: Path | str) -> tuple[np.ndarray, np.ndarray]:
    times, angles = [], []
    try:
        lines = Path(path).read_text().splitlines()
    except OSError as error:
        raise ReplayV11BindingError("motion.dat is not readable") from error
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fields = [x.strip() for x in line.split(";")]
        if len(fields) != 2:
            raise ReplayV11BindingError("motion.dat has an unexpected row")
        times.append(_finite(float(fields[0]), "motion time"))
        angles.append(_finite(float(fields[1]), "motion angle"))
    t = _strict_increasing(times, "motion times")
    a = _float_array(angles, "motion angles").reshape(-1)
    if len(t) != len(a):
        raise ReplayV11BindingError("motion time/angle lengths differ")
    return t, a


def motion_pose(times: Sequence[float], motion_times: Sequence[float], motion_angles_deg: Sequence[float],
                axis_p1_m: Sequence[float], axis_p2_m: Sequence[float]) -> list[dict[str, Any]]:
    query = _float_array(times, "query times").reshape(-1)
    mt = _strict_increasing(motion_times, "motion times")
    ma = _float_array(motion_angles_deg, "motion angles").reshape(-1)
    if len(mt) != len(ma) or not np.isfinite(ma).all():
        raise ReplayV11BindingError("motion arrays are malformed")
    if np.any(query < mt[0]) or np.any(query > mt[-1]):
        raise ReplayV11BindingError("query time is outside motion.dat; extrapolation is forbidden")
    p1, p2 = _finite_vector(axis_p1_m, "axis_p1_m"), _finite_vector(axis_p2_m, "axis_p2_m")
    axis = p2 - p1
    result = []
    for time in query:
        angle = float(np.interp(time, mt, ma))
        result.append({"time_s": float(time), "angle_deg": angle,
                       "rotation_matrix": _rotation_about_axis(axis, math.radians(angle)),
                       "translation_m": p1.copy(),
                       "pose_frame": "world_to_body_rotation_about_bound_axis"})
    return result


def mass_observation(points: Any, masses: Any, velocities: Any | None, *, denominator: float,
                     missing_mass: float, pose: Mapping[str, Any] | None,
                     scale_m: float, quantiles: Sequence[float],
                     bin_edges: Sequence[float], valid: Any | None = None,
                     initial_masses: Any | None = None) -> dict[str, Any]:
    """Compute fixed-scale observers with a frozen source-mass denominator.

    ``valid=False`` is an observation failure even when the retained position
    and current mass bytes happen to be finite.  The unknown bucket uses the
    corresponding ``initial_masses`` entry, never a later NaN or guessed
    current mass.  ``missing_mass`` is reserved for initially absent source
    material and is kept separate from later missing particles.
    """
    points = _float_array(points, "points")
    masses = _float_array(masses, "masses").reshape(-1)
    if points.ndim != 2 or points.shape[1] != 3 or masses.shape != (len(points),):
        raise ReplayV11BindingError("points/masses have incompatible shapes")
    source_masses = masses if initial_masses is None else _float_array(initial_masses, "initial_masses").reshape(-1)
    if source_masses.shape != masses.shape or np.any(~np.isfinite(source_masses)) or np.any(source_masses <= 0):
        raise ReplayV11BindingError("initial_masses must be finite and positive")
    valid_mask = np.ones(len(points), dtype=bool) if valid is None else np.asarray(valid, dtype=bool).reshape(-1)
    if valid_mask.shape != masses.shape:
        raise ReplayV11BindingError("valid has incompatible shape")
    scale = _finite(scale_m, "observer.position_scale_m")
    if scale <= 0:
        raise ReplayV11BindingError("observer position scale must be positive")
    edges = _strict_increasing(bin_edges, "normalized_bin_edges")
    if pose is None:
        transformed = points.copy()
    else:
        R = _float_array(pose.get("rotation_matrix"), "pose.rotation_matrix")
        if R.shape != (3, 3) or not np.isfinite(R).all() or not np.allclose(R.T @ R, np.eye(3), atol=1e-8, rtol=0):
            raise ReplayV11BindingError("pose rotation is not orthonormal")
        if not math.isclose(float(np.linalg.det(R)), 1.0, rel_tol=0, abs_tol=1e-8):
            raise ReplayV11BindingError("pose rotation determinant is not +1")
        translation = _finite_vector(pose.get("translation_m"), "pose.translation_m")
        transformed = (R.T @ (points - translation).T).T
    finite_position = np.isfinite(transformed).all(axis=1)
    positive_mass = np.isfinite(masses) & (masses > 0)
    active = valid_mask & finite_position & positive_mass
    known_mass = float(source_masses[active].sum())
    invalid_mass = float(source_masses[~active].sum())
    if known_mass <= 0:
        raise ReplayV11BindingError("mass observer has no finite positive position mass")
    denominator = _finite(denominator, "initial_mass_denominator_kg")
    missing_mass = _finite(missing_mass, "missing_mass_kg")
    if denominator <= 0 or missing_mass < 0:
        raise ReplayV11BindingError("mass denominator/missing mass invalid")
    observed = known_mass + invalid_mass + missing_mass
    if observed > denominator + 1e-10 * max(1.0, denominator):
        raise ReplayV11BindingError("mass observations exceed initial denominator")
    coordinate = transformed[active, 0] / scale
    known_weights = source_masses[active]
    bins = np.zeros(len(edges) - 1, dtype="float64")
    for i in range(len(bins)):
        mask = (coordinate >= edges[i]) & (coordinate < edges[i + 1])
        if i == len(bins) - 1:
            mask |= coordinate == edges[i + 1]
        bins[i] = float(known_weights[mask].sum())
    out_of_range = float(known_weights[(coordinate < edges[0]) | (coordinate > edges[-1])].sum())
    order = np.argsort(coordinate, kind="stable")
    cumulative = np.cumsum(known_weights[order])
    fronts: dict[str, float] = {}
    for raw_q in quantiles:
        q = _finite(raw_q, "mass quantile")
        if q < 0 or q > 1:
            raise ReplayV11BindingError("mass quantile is outside [0,1]")
        idx = min(int(np.searchsorted(cumulative, q * known_mass, side="left")), len(order) - 1)
        fronts[str(q)] = float(coordinate[order[idx]] * scale)
    result: dict[str, Any] = {
        "known_mass_kg": known_mass,
        "initial_mass_denominator_kg": denominator,
        "initial_missing_mass_bucket_kg": missing_mass,
        "later_invalid_or_missing_mass_bucket_kg": invalid_mass,
        "invalid_mass_bucket_kg": invalid_mass,
        "out_of_range_mass_bucket_kg": out_of_range,
        "denominator_unobserved_mass_kg": max(0.0, denominator - observed),
        "mass_accounting": {
            "known_finite_position_mass_kg": known_mass,
            "initial_missing_mass_kg": missing_mass,
            "later_invalid_or_missing_mass_kg": invalid_mass,
            "invalid_mass_kg": invalid_mass,
            "denominator_unobserved_mass_kg": max(0.0, denominator - observed),
            "conserved": math.isclose(observed + max(0.0, denominator - observed), denominator,
                                      rel_tol=0.0, abs_tol=1e-10),
        },
        "mass_distribution_kg": bins.tolist(),
        "mass_distribution_normalized_edges": edges.tolist(),
        "mass_quantile_front_m": fronts,
        "mass_weighted_com_m": ((transformed[active] * source_masses[active, None]).sum(axis=0) / known_mass).tolist(),
        "position_frame": "body" if pose is not None else "world",
        "position_transform": "R.T @ (x_world - axis_p1_m)" if pose is not None else "identity",
        "velocity_semantics": "inertial_world_m_per_s; never relabeled by position frame transform",
        "quality": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    if velocities is not None:
        velocity = _float_array(velocities, "velocities")
        if velocity.shape != points.shape:
            raise ReplayV11BindingError("velocities shape must match points")
        mean, ke, velocity_mass, missing_velocity_mass = normalized_mass_velocity(
            velocity, masses, valid=active, weight_masses=source_masses)
        result["mass_weighted_mean_velocity_m_s"] = None if mean is None else mean.tolist()
        result["mass_weighted_kinetic_energy_J"] = ke
        result["velocity_known_mass_kg"] = velocity_mass
        result["velocity_missing_mass_bucket_kg"] = missing_velocity_mass
        result["velocity_frame"] = "world_inertial"
        result["velocity_observation_status"] = (
            "COMPLETE_FOR_POSITION_VALID_MASS" if missing_velocity_mass == 0
            else "PARTIAL_VELOCITY_OBSERVATION_EXPLICIT_BUCKET")
    return result


def event_label(times: np.ndarray, distance: np.ndarray, position_valid: np.ndarray,
                velocities: np.ndarray | None = None,
                explicit_crossing_times: Sequence[float] | None = None,
                expected_first_bracket_s: Sequence[float] | None = None,
                expected_event_time_s: float | None = None) -> dict[str, Any]:
    """Classify first arrival while retaining bracket/censoring semantics."""
    times = _strict_increasing(times, "event times")
    distance = _float_array(distance, "signed distance").reshape(-1)
    position_valid = np.asarray(position_valid, dtype=bool).reshape(-1)
    if len(distance) != len(times) or len(position_valid) != len(times):
        raise ReplayV11BindingError("event arrays have incompatible shapes")
    first_valid = bool(position_valid[0] and math.isfinite(float(distance[0])))
    if not first_valid:
        status, first_time, first_bracket = "failed_before_observation", None, None
    elif distance[0] >= 0:
        status, first_time, first_bracket = "initially_inside", None, None
    else:
        status, first_time, first_bracket = None, None, None
        for i in range(1, len(times)):
            if not position_valid[i - 1] or not position_valid[i]:
                if not position_valid[i]:
                    status = "failed_before_observation"
                    break
                continue
            d0, d1 = float(distance[i - 1]), float(distance[i])
            if not math.isfinite(d0) or not math.isfinite(d1):
                status = "failed_before_observation"
                break
            if d0 < 0 <= d1:
                fraction = 0.0 if d1 == d0 else -d0 / (d1 - d0)
                fraction = min(1.0, max(0.0, float(fraction)))
                first_time = float(times[i - 1] + fraction * (times[i] - times[i - 1]))
                first_bracket = [float(times[i - 1]), float(times[i])]
                status = "observed"
                break
        if status is None:
            status = "right_censored"
    candidates: list[float] = []
    if explicit_crossing_times is not None:
        candidates = [_finite(x, "explicit crossing time") for x in explicit_crossing_times]
        if candidates != sorted(candidates):
            raise ReplayV11BindingError("explicit crossing candidates must be sorted")
        if candidates and (candidates[0] < times[0] or candidates[-1] > times[-1]):
            raise ReplayV11BindingError("explicit crossing candidate is outside saved timeline")
        if candidates:
            brackets = [i for i in range(len(times) - 1) if times[i] <= candidates[0] <= times[i + 1]]
            if len(brackets) != 1:
                raise ReplayV11BindingError("first crossing candidate has no unique saved bracket")
            first_bracket = [float(times[brackets[0]]), float(times[brackets[0] + 1])]
            in_first = sum(first_bracket[0] <= x <= first_bracket[1] for x in candidates)
            if in_first > 1:
                return {"status": "ambiguous_multiple_crossing", "event_time_s": None,
                        "first_saved_bracket_s": first_bracket,
                        "crossing_candidate_times_s": candidates,
                        "ambiguity_reason": "multiple candidates in first saved bracket"}
            first_time, status = candidates[0], "observed"
    if expected_first_bracket_s is not None and status == "observed":
        expected_bracket = _float_array(expected_first_bracket_s, "expected_first_bracket_s").reshape(-1)
        if expected_bracket.shape != (2,) or not np.allclose(expected_bracket, first_bracket, rtol=0, atol=1e-12):
            raise ReplayV11BindingError("first crossing is in the wrong saved bracket")
    if expected_event_time_s is not None and status == "observed":
        if not math.isclose(float(expected_event_time_s), float(first_time), rel_tol=0, abs_tol=1e-12):
            raise ReplayV11BindingError("event time differs from first candidate")
    later_crossings: list[float] = []
    if status == "observed" and first_bracket is not None and explicit_crossing_times is None:
        start = int(np.searchsorted(times, first_bracket[1], side="left"))
        for i in range(max(1, start), len(times) - 1):
            if position_valid[i] and position_valid[i + 1] and distance[i] < 0 <= distance[i + 1]:
                d0, d1 = float(distance[i]), float(distance[i + 1])
                later_crossings.append(float(times[i] - d0 * (times[i + 1] - times[i]) / (d1 - d0)))
    velocity_status, normal_speed = "NOT_REQUIRED_FOR_POSITION_EVENT", None
    if status == "observed" and first_bracket is not None and velocities is not None:
        i = int(np.searchsorted(times, first_bracket[0], side="left"))
        v0, v1 = _float_array(velocities[i], "event velocity left"), _float_array(velocities[i + 1], "event velocity right")
        if v0.shape != (3,) or v1.shape != (3,) or not np.isfinite(v0).all() or not np.isfinite(v1).all():
            velocity_status = "UNKNOWN_VELOCITY"
        else:
            normal_speed = float(0.5 * (v0[0] + v1[0]))
            velocity_status = "WORLD_INERTIAL_NORMAL_SPEED_OBSERVED"
    return {"status": status, "event_time_s": first_time,
            "first_saved_bracket_s": first_bracket,
            "crossing_candidate_times_s": candidates or ([] if first_time is None else [first_time]),
            "later_sampled_forward_crossings_s": later_crossings,
            "recross_status": "ENDPOINT_SAMPLE_ONLY_UNKNOWN_HIDDEN_RECROSSINGS",
            "velocity_status": velocity_status, "relative_normal_speed_m_s": normal_speed}


def adapt_v4_first_passage(crossing_candidates_s: Sequence[float],
                           saved_brackets_s: Sequence[Sequence[float]],
                           crossing_count: int) -> dict[str, Any]:
    """Adapt a legacy first-passage record without inventing recross times.

    A legacy total count does not identify which saved bracket contained later
    crossings.  Only candidates explicitly supplied in the first bracket are
    used for the first event; the residual count remains an unknown recross
    bucket.
    """
    if isinstance(crossing_count, bool) or not isinstance(crossing_count, int) or crossing_count < 0:
        raise ReplayV11BindingError("crossing_count must be a nonnegative integer")
    candidates = [_finite(x, "crossing candidate") for x in crossing_candidates_s]
    if candidates != sorted(candidates):
        raise ReplayV11BindingError("crossing candidates must be sorted")
    brackets = _float_array(saved_brackets_s, "saved_brackets")
    if brackets.ndim != 2 or brackets.shape[1] != 2 or len(brackets) == 0 or not np.isfinite(brackets).all() or np.any(brackets[:, 1] <= brackets[:, 0]):
        raise ReplayV11BindingError("saved_brackets must be nonempty shape (n,2)")
    if np.any(brackets[1:, 0] < brackets[:-1, 1]):
        raise ReplayV11BindingError("saved_brackets overlap or are out of order")
    if crossing_count < len(candidates):
        raise ReplayV11BindingError("crossing_count is smaller than supplied candidates")
    if candidates:
        first = float(candidates[0])
        if not brackets[0, 0] <= first <= brackets[0, 1]:
            raise ReplayV11BindingError("first crossing candidate is outside first saved bracket")
        in_first = sum(brackets[0, 0] <= value <= brackets[0, 1] for value in candidates)
        if in_first > 1:
            return {"status": "ambiguous_multiple_crossing", "event_time_s": None,
                    "first_saved_bracket_s": brackets[0].tolist(),
                    "crossing_candidate_times_s": candidates,
                    "total_crossing_count": crossing_count,
                    "unresolved_recross_count": max(0, crossing_count - len(candidates))}
        return {"status": "observed", "event_time_s": first,
                "first_saved_bracket_s": brackets[0].tolist(),
                "crossing_candidate_times_s": [first],
                "total_crossing_count": crossing_count,
                "unresolved_recross_count": max(0, crossing_count - 1),
                "recross_status": "COUNT_ONLY_LATER_BRACKETS_UNKNOWN"}
    if crossing_count:
        raise ReplayV11BindingError("positive crossing count has no first candidate")
    return {"status": "right_censored", "event_time_s": None,
            "first_saved_bracket_s": brackets[0].tolist(),
            "crossing_candidate_times_s": [], "total_crossing_count": 0,
            "unresolved_recross_count": 0}


def adapt_v4_saved_bracket_events(bracket_events: Sequence[Mapping[str, Any]],
                                  saved_brackets_s: Sequence[Sequence[float]],
                                  crossing_count: int) -> dict[str, Any]:
    """Adapt explicit v4 candidates recorded in their saved brackets.

    The old aggregate ``crossing_count`` field is insufficient to decide
    whether a first saved bracket contains more than one crossing.  This
    adapter accepts only the candidates that v4 actually records with a
    bracket index.  A candidate in a later, distinct bracket is retained as a
    later crossing and does not make the first passage ambiguous.  No bracket
    endpoint is synthesized when v4 supplied only a count.
    """
    if isinstance(crossing_count, bool) or not isinstance(crossing_count, int) or crossing_count < 0:
        raise ReplayV11BindingError("crossing_count must be a nonnegative integer")
    try:
        brackets = _float_array(saved_brackets_s, "saved_brackets").reshape(-1, 2)
    except (ValueError, ReplayV11BindingError) as error:
        raise ReplayV11BindingError("saved_brackets must be finite shape (n,2)") from error
    if brackets.ndim != 2 or brackets.shape[1] != 2 or len(brackets) == 0 or not np.isfinite(brackets).all():
        raise ReplayV11BindingError("saved_brackets must be finite shape (n,2)")
    if np.any(brackets[:, 1] <= brackets[:, 0]) or np.any(brackets[1:, 0] < brackets[:-1, 1]):
        raise ReplayV11BindingError("saved_brackets overlap or are out of order")
    if not isinstance(bracket_events, Sequence):
        raise ReplayV11BindingError("bracket_events must be a sequence of recorded events")
    all_candidates: list[tuple[int, float]] = []
    seen: set[tuple[int, float]] = set()
    for event in bracket_events:
        if not isinstance(event, Mapping) or isinstance(event.get("bracket_index"), bool) or not isinstance(event.get("bracket_index"), int):
            raise ReplayV11BindingError("each v4 event requires an integer bracket_index")
        bracket_index = int(event["bracket_index"])
        if bracket_index < 0 or bracket_index >= len(brackets):
            raise ReplayV11BindingError("v4 event bracket_index is outside saved brackets")
        candidates = event.get("candidate_times_s")
        if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes)):
            raise ReplayV11BindingError("v4 event candidate_times_s must be a sequence")
        values = [_finite(value, "v4 candidate time") for value in candidates]
        if values != sorted(values):
            raise ReplayV11BindingError("v4 candidates within a bracket must be sorted")
        lo, hi = map(float, brackets[bracket_index])
        for value in values:
            if value < lo or value > hi:
                raise ReplayV11BindingError("v4 candidate is outside its declared saved bracket")
            key = (bracket_index, value)
            if key in seen:
                raise ReplayV11BindingError("duplicate v4 candidate record")
            seen.add(key)
            all_candidates.append(key)
    all_candidates.sort(key=lambda item: (item[1], item[0]))
    if len(all_candidates) > crossing_count:
        raise ReplayV11BindingError("recorded candidates exceed v4 crossing_count")
    first = [item for item in all_candidates if item[0] == 0]
    if crossing_count and not first:
        raise ReplayV11BindingError("positive crossing_count has no recorded first-bracket candidate")
    if len(first) > 1:
        return {
            "status": "ambiguous_multiple_crossing", "event_time_s": None,
            "first_saved_bracket_s": brackets[0].tolist(),
            "crossing_candidate_times_s": [value for _, value in all_candidates],
            "later_saved_crossing_times_s": [value for index, value in all_candidates if index > 0],
            "total_crossing_count": crossing_count,
            "unresolved_recross_count": max(0, crossing_count - len(all_candidates)),
            "ambiguity_reason": "multiple explicitly recorded candidates in first saved bracket",
        }
    if not crossing_count:
        return {
            "status": "right_censored", "event_time_s": None,
            "first_saved_bracket_s": brackets[0].tolist(),
            "crossing_candidate_times_s": [], "later_saved_crossing_times_s": [],
            "total_crossing_count": 0, "unresolved_recross_count": 0,
        }
    first_time = first[0][1]
    return {
        "status": "observed", "event_time_s": first_time,
        "first_saved_bracket_s": brackets[0].tolist(),
        "crossing_candidate_times_s": [value for _, value in all_candidates],
        "later_saved_crossing_times_s": [value for index, value in all_candidates if index > 0],
        "total_crossing_count": crossing_count,
        "unresolved_recross_count": max(0, crossing_count - len(all_candidates)),
        "recross_status": "EXPLICIT_SAVED_BRACKET_EVENTS;_UNRECORDED_REMAINDER_UNKNOWN",
    }


def residence(times: np.ndarray, distance: np.ndarray, valid: np.ndarray) -> dict[str, Any]:
    """Integrate target-side residence with an explicit unknown interval bucket."""
    times = _strict_increasing(times, "residence times")
    distance = _float_array(distance, "residence distance").reshape(-1)
    valid = np.asarray(valid, dtype=bool).reshape(-1)
    if len(distance) != len(times) or len(valid) != len(times):
        raise ReplayV11BindingError("residence arrays have incompatible shapes")
    known, unknown, intervals = 0.0, 0.0, []
    for i in range(len(times) - 1):
        t0, t1 = float(times[i]), float(times[i + 1])
        if not valid[i] or not valid[i + 1] or not np.isfinite(distance[i:i + 2]).all():
            unknown += t1 - t0
            continue
        d0, d1 = float(distance[i]), float(distance[i + 1])
        if d0 >= 0 and d1 >= 0:
            known += t1 - t0
            intervals.append([t0, t1])
        elif d0 < 0 <= d1 or d0 >= 0 > d1:
            alpha = min(1.0, max(0.0, float(-d0 / (d1 - d0)))) if d1 != d0 else 0.0
            cross = t0 + alpha * (t1 - t0)
            if d0 < 0 <= d1:
                known += t1 - cross
                intervals.append([cross, t1])
            else:
                known += cross - t0
                intervals.append([t0, cross])
    return {"known_residence_s": known, "unknown_residence_s": unknown,
            "residence_intervals_s": intervals,
            "integration": "linear_signed_distance_between_saved_frames"}


def flux(times: np.ndarray, distance: np.ndarray, valid: np.ndarray, masses: np.ndarray,
         *, initial_mass: float | None = None) -> dict[str, Any]:
    times = _strict_increasing(times, "flux times")
    distance = _float_array(distance, "flux distance").reshape(-1)
    masses = _float_array(masses, "flux masses").reshape(-1)
    valid = np.asarray(valid, dtype=bool).reshape(-1)
    if not (len(distance) == len(masses) == len(valid) == len(times)):
        raise ReplayV11BindingError("flux arrays have incompatible shapes")
    intervals, unknown_intervals, net = [], [], 0.0
    has_unknown_interval = False
    for i in range(len(times) - 1):
        if not valid[i] or not valid[i + 1] or not np.isfinite(masses[i:i + 2]).all():
            candidate = masses[i:i + 2][np.isfinite(masses[i:i + 2]) & (masses[i:i + 2] > 0)]
            if len(candidate):
                has_unknown_interval = True
            unknown_intervals.append({
                "bracket_s": [float(times[i]), float(times[i + 1])],
                "reason": "position_or_mass_invalid; crossing and flux mass unknown",
            })
            continue
        d0, d1 = float(distance[i]), float(distance[i + 1])
        direction = 1 if d0 < 0 <= d1 else (-1 if d0 >= 0 > d1 else 0)
        if not direction:
            continue
        dt = float(times[i + 1] - times[i])
        alpha = min(1.0, max(0.0, float(-d0 / (d1 - d0)))) if d1 != d0 else 0.0
        event_time = float(times[i] + alpha * dt)
        mass = (float(initial_mass) if initial_mass is not None else
                float(masses[i] + alpha * (masses[i + 1] - masses[i])))
        net += direction * mass
        intervals.append({"bracket_s": [float(times[i]), float(times[i + 1])],
                          "event_time_s": event_time,
                          "direction": "into_receiver" if direction > 0 else "out_of_receiver",
                          "mass_kg": mass, "signed_mass_flux_kg_s": direction * mass / dt,
                          "mass_status": "OBSERVED_FROZEN_INITIAL_PARTICLE_MASS" if initial_mass is not None else "OBSERVED_LINEAR_INTERPOLATION"})
    frozen_mass = _finite(initial_mass, "initial_mass") if initial_mass is not None else float(
        np.nanmax(masses[np.isfinite(masses) & (masses > 0)]) if np.any(np.isfinite(masses) & (masses > 0)) else 0.0)
    unknown_mass = frozen_mass if has_unknown_interval else 0.0
    return {"net_flux_mass_kg": net, "unknown_flux_mass_kg": unknown_mass,
            "unknown_flux_gross_mass_kg": unknown_mass,
            "unknown_flux_net_bound_kg": unknown_mass,
            "flux_intervals": intervals, "unknown_flux_intervals": unknown_intervals,
            "flux_semantics": "signed mass crossing per saved bracket; no aperture area inferred",
            "unknown_mass_semantics": "one frozen particle mass bound for all connected unknown intervals; gross and net bounds are reported separately; no interval double-counting"}


def select_fluid_cohort(initial_position: Any, initial_type: Any, initial_mk: Any,
                        particle_zone: Any, particle_id: Any, initial_mass: Any,
                        cohort: Mapping[str, Any]) -> tuple[np.ndarray, dict[str, Any]]:
    position = _float_array(initial_position, "initial_position")
    types = _numeric_array(initial_type, "initial_type").reshape(-1)
    mks = _numeric_array(initial_mk, "initial_mk").reshape(-1)
    zones = _numeric_array(particle_zone, "particle_zone").reshape(-1)
    ids = _numeric_array(particle_id, "particle_id").reshape(-1)
    masses = _float_array(initial_mass, "initial_mass").reshape(-1)
    n = len(position)
    if position.shape != (n, 3) or any(len(a) != n for a in (types, mks, zones, ids, masses)):
        raise ReplayV11BindingError("initial identity arrays have inconsistent lengths")
    low = _finite_vector(cohort.get("source_low_m"), "cohort.source_low_m")
    size = _finite_vector(cohort.get("source_size_m"), "cohort.source_size_m")
    high = low + size
    mask = ((types == int(cohort.get("initial_type_code"))) &
            np.isin(mks, np.asarray(cohort.get("initial_mk_codes"), dtype=mks.dtype)) &
            np.isfinite(position).all(axis=1) &
            np.all((position >= low) & (position <= high), axis=1))
    candidates = np.flatnonzero(mask)
    if not len(candidates):
        raise ReplayV11BindingError("fluid source-region cohort is empty")
    order = np.lexsort((ids[candidates], zones[candidates]))
    selected = candidates[order]
    max_particles = cohort.get("max_particles")
    if max_particles is not None:
        selected = selected[:_positive_int(max_particles, "cohort.max_particles")]
    selection = cohort.get("selection")
    if selection not in {"all_fluid_in_initial_source_region", "lowest_identity_in_source_region"}:
        raise ReplayV11BindingError("unsupported cohort selection")
    if selection == "all_fluid_in_initial_source_region" and max_particles is not None:
        raise ReplayV11BindingError("all-fluid cohort cannot have max_particles")
    expected_count = cohort.get("expected_initial_fluid_count")
    if expected_count is not None and len(candidates) != int(expected_count):
        raise ReplayV11BindingError("initial fluid cohort count differs from source evidence")
    key_bytes = np.stack([zones[selected].astype("<i8"), ids[selected].astype("<i8")], axis=1).tobytes()
    summary = {
        "initial_fluid_candidates": int(len(candidates)),
        "selected_count": int(len(selected)),
        "selected_initial_mass_kg": float(masses[selected].sum()),
        "identity_key": "(Zone,Idp)",
        "selected_identity_sha256": hashlib.sha256(key_bytes).hexdigest(),
        "selected_first_identity": [int(zones[selected[0]]), int(ids[selected[0]])],
        "selected_last_identity": [int(zones[selected[-1]]), int(ids[selected[-1]])],
        "selected_indices": selected,
        "material_initial_mass_kg": {
            str(int(mk)): float(masses[selected][mks[selected] == mk].sum())
            for mk in sorted(set(mks[selected].tolist()))
        },
    }
    return selected, summary


def replay_trajectory(trajectory: Mapping[str, Any], request: Mapping[str, Any]) -> dict[str, Any]:
    """Replay an in-memory trajectory using source-bound geometry and identity."""
    bound = validate_replay_request(request)
    required = ("time", "position", "velocity", "mass", "valid", "initial_position",
                "initial_type", "initial_mk", "particle_zone", "particle_id", "initial_mass")
    for name in required:
        if name not in trajectory:
            raise ReplayV11BindingError(f"trajectory.{name} is missing")
    times = _strict_increasing(trajectory["time"], "trajectory.time")
    positions = _trajectory_float_array(trajectory["position"], "trajectory.position")
    velocities = _trajectory_float_array(trajectory["velocity"], "trajectory.velocity")
    masses = _trajectory_float_array(trajectory["mass"], "trajectory.mass")
    valid = np.asarray(trajectory["valid"], dtype=bool)
    if positions.ndim != 3 or positions.shape[2] != 3 or velocities.shape != positions.shape:
        raise ReplayV11BindingError("trajectory position/velocity shapes are invalid")
    if masses.shape != positions.shape[:2] or valid.shape != masses.shape or len(times) != positions.shape[0]:
        raise ReplayV11BindingError("trajectory time/mass/valid shapes are invalid")
    selected, cohort_summary = select_fluid_cohort(
        trajectory["initial_position"], trajectory["initial_type"], trajectory["initial_mk"],
        trajectory["particle_zone"], trajectory["particle_id"], trajectory["initial_mass"], bound["cohort"])
    initial_missing = _finite(bound["initial_mass_denominator"]["initial_missing_mass_kg"], "initial missing mass")
    denominator = _finite(bound["initial_mass_denominator"]["denominator_kg"], "initial denominator")
    if not math.isclose(denominator, cohort_summary["selected_initial_mass_kg"] + initial_missing, rel_tol=0.0, abs_tol=5e-8):
        raise ReplayV11BindingError("selected initial mass does not match request denominator")
    initial_masses_selected = _float_array(trajectory["initial_mass"], "initial_mass").reshape(-1)[selected]
    if not math.isclose(float(initial_masses_selected.sum()), cohort_summary["selected_initial_mass_kg"],
                        rel_tol=0.0, abs_tol=5e-8):
        raise ReplayV11BindingError("selected initial mass changed after cohort selection")

    frame_start, frame_stop = int(bound["window"]["frame_start"]), int(bound["window"]["frame_stop"])
    if frame_start < 0 or frame_stop >= len(times) or frame_stop < frame_start:
        raise ReplayV11BindingError("trajectory does not contain requested window")
    expected_times = _float_array(bound["window"]["expected_times_s"], "window.expected_times_s")
    if len(expected_times) != frame_stop - frame_start + 1 or not np.allclose(times[frame_start:frame_stop + 1], expected_times, rtol=0, atol=2e-8):
        raise ReplayV11BindingError("trajectory times differ from frozen CURRENT window")

    motion_items = [item for item in bound["source_files"] if item.get("role") == "motion_dat"]
    if not motion_items:
        raise ReplayV11BindingError("motion source is missing")
    motion_path = motion_items[0]["path"]
    if Path(motion_path).exists():
        motion_t, motion_a = read_motion_dat(motion_path)
    else:
        raise ReplayV11BindingError("motion source is required for replay")
    poses = motion_pose(times[frame_start:frame_stop + 1], motion_t, motion_a,
                        bound["geometry"]["moving_axis_p1_m"], bound["geometry"]["moving_axis_p2_m"])

    event_origin = _finite_vector(bound["event_surface"]["origin_m"], "event origin")
    event_normal = _finite_vector(bound["event_surface"]["normal"], "event normal")
    distance = np.einsum("tnc,c->tn",
                         positions[frame_start:frame_stop + 1, selected] - event_origin, event_normal)
    subvalid = valid[frame_start:frame_stop + 1, selected] & np.isfinite(
        positions[frame_start:frame_stop + 1, selected]).all(axis=2)
    initial_mks = _numeric_array(trajectory["initial_mk"], "initial_mk").reshape(-1)[selected]
    labels: list[dict[str, Any]] = []
    for j, index in enumerate(selected):
        label = event_label(times[frame_start:frame_stop + 1], distance[:, j], subvalid[:, j],
                            velocities[frame_start:frame_stop + 1, index])
        label.update({
            "zone": int(trajectory["particle_zone"][index]),
            "idp": int(trajectory["particle_id"][index]),
            "initial_mk": int(initial_mks[j]),
            "initial_mass_kg": float(trajectory["initial_mass"][index]),
        })
        labels.append(label)

    frame_observations: list[dict[str, Any]] = []
    for local_frame, frame in enumerate(range(frame_start, frame_stop + 1)):
        obs = mass_observation(
            positions[frame, selected], masses[frame, selected], velocities[frame, selected],
            denominator=denominator, missing_mass=initial_missing, pose=poses[local_frame],
            scale_m=float(bound["observer"]["position_scale_m"]),
            quantiles=bound["observer"]["mass_quantiles"],
            bin_edges=bound["observer"]["normalized_bin_edges"],
            valid=valid[frame, selected], initial_masses=initial_masses_selected,
        )
        material = {}
        for mk in sorted(set(initial_mks.tolist())):
            mk_mask = initial_mks == mk
            mk_mass = masses[frame, selected[mk_mask]]
            mk_initial = initial_masses_selected[mk_mask]
            mk_valid = valid[frame, selected[mk_mask]] & np.isfinite(mk_mass) & (mk_mass > 0)
            material[str(int(mk))] = {
                "known_mass_kg": float(mk_initial[mk_valid].sum()),
                "unknown_mass_kg": float(mk_initial[~mk_valid].sum()),
                "count": int(mk_mask.sum()),
                "mass_weight_source": "frozen_initial_mass",
            }
        obs.update({"frame": frame, "time_s": float(times[frame]),
                    "material_mass_by_initial_mk": material})
        frame_observations.append(obs)

    label_counts: dict[str, int] = {}
    residence_by_status: dict[str, float] = {}
    residence_intervals: list[list[float]] = []
    flux_total = {"net_flux_mass_kg": 0.0, "unknown_flux_mass_kg": 0.0,
                  "unknown_flux_gross_mass_kg": 0.0, "unknown_flux_net_bound_kg": 0.0}
    flux_intervals: list[dict[str, Any]] = []
    unknown_flux_intervals: list[dict[str, Any]] = []
    unknown_residence = 0.0
    known_residence_mass_time = 0.0
    unknown_residence_mass_time = 0.0
    for j, index in enumerate(selected):
        status = labels[j]["status"]
        label_counts[status] = label_counts.get(status, 0) + 1
        r = residence(times[frame_start:frame_stop + 1], distance[:, j], subvalid[:, j])
        particle_initial_mass = float(initial_masses_selected[j])
        f = flux(times[frame_start:frame_stop + 1], distance[:, j], subvalid[:, j],
                 masses[frame_start:frame_stop + 1, index], initial_mass=particle_initial_mass)
        residence_by_status[status] = residence_by_status.get(status, 0.0) + r["known_residence_s"] * particle_initial_mass
        residence_intervals.extend(r["residence_intervals_s"])
        unknown_residence += r["unknown_residence_s"]
        known_residence_mass_time += r["known_residence_s"] * particle_initial_mass
        unknown_residence_mass_time += r["unknown_residence_s"] * particle_initial_mass
        flux_total["net_flux_mass_kg"] += f["net_flux_mass_kg"]
        flux_total["unknown_flux_mass_kg"] += f["unknown_flux_mass_kg"]
        flux_total["unknown_flux_gross_mass_kg"] += f["unknown_flux_gross_mass_kg"]
        flux_total["unknown_flux_net_bound_kg"] += f["unknown_flux_net_bound_kg"]
        flux_intervals.extend(f["flux_intervals"])
        unknown_flux_intervals.extend(f["unknown_flux_intervals"])
    return {
        "schema": RESULT_SCHEMA,
        "model_invoked": False,
        "case_identity": dict(bound["case_identity"]),
        "source_binding": {
            "current_catalog_sha256": bound.get("current_binding", {}).get("sha256", "fixture"),
            "trajectory_h5_producer_sha256": bound.get("trajectory_h5", {}).get("producer_declared_sha256", "fixture"),
            "source_files": {str(item.get("role")): item.get("sha256") for item in bound.get("source_files", [])},
            "binding_status": "EXACT_CURRENT_SOURCE_BOUND" if request.get("fixture_mode") is not True else "MANUFACTURED_FIXTURE",
        },
        "window": {"frame_start": frame_start, "frame_stop": frame_stop,
                   "time_start_s": float(times[frame_start]), "time_stop_s": float(times[frame_stop]),
                   "frame_count": frame_stop - frame_start + 1},
        "cohort": {key: (value.tolist() if isinstance(value, np.ndarray) else value)
                   for key, value in cohort_summary.items() if key != "selected_indices"},
        "initial_mass_denominator": {
            "selected_initial_mass_kg": cohort_summary["selected_initial_mass_kg"],
            "initial_missing_mass_kg": initial_missing, "denominator_kg": denominator,
            "later_missing_unique_count": bound["initial_mass_denominator"].get("later_missing_unique_count"),
            "later_missing_mass_kg": bound["initial_mass_denominator"].get("later_missing_mass_kg"),
            "missing_scope": "initial_fluid_source_cohort_global; identity fate unknown",
        },
        "frame_observations": frame_observations,
        "labels": labels,
        "event_summary": {
            "label_counts": label_counts, "residence_known_mass_time_kg_s_by_label": residence_by_status,
            "residence_known_mass_time_kg_s": known_residence_mass_time,
            "residence_unknown_mass_time_kg_s": unknown_residence_mass_time,
            "residence_unknown_interval_s_unweighted": unknown_residence,
            "residence_intervals_s": residence_intervals, **flux_total,
            "flux_intervals": flux_intervals, "unknown_flux_intervals": unknown_flux_intervals,
            "event_surface": dict(bound["event_surface"]),
            "event_surface_scope": "diagnostic_open_rim_front_halfspace; not a closed receiver/aperture arrival",
        },
        "velocity_semantics": "world_inertial_m_per_s; body-frame position does not imply relative velocity",
        "observer_profile": dict(bound.get("observer_profile", {})),
        "quality": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "qualification": "UNKNOWN"},
        "limitations": [
            "first passage is bounded by saved-frame endpoint crossings and linear interpolation",
            "hidden recrossings within a saved bracket remain unknown",
            "native excluded-particle identity ledger is unavailable; count is not assigned to labels",
            "this full-timeline development replay does not grant scientific qualification",
            "later missing particle mass is transferred once to unknown buckets from frozen initial mass; it is never added to the initial denominator",
            "event surface is a world halfspace diagnostic because a closed receiver/孔口 volume is not bound by this request",
        ],
    }


def estimate_window_bytes(frame_count: int, selected_count: int,
                          fields: Sequence[str] = ("position", "velocity", "mass", "valid")) -> int:
    if isinstance(frame_count, bool) or not isinstance(frame_count, int) or frame_count <= 0:
        raise ReplayV11BindingError("frame_count must be a positive integer")
    if isinstance(selected_count, bool) or not isinstance(selected_count, int) or selected_count <= 0:
        raise ReplayV11BindingError("selected_count must be a positive integer")
    bytes_per_item = {"position": 12, "velocity": 12, "mass": 4, "valid": 1,
                      "type": 1, "mk": 2, "density": 4, "pressure": 4}
    if not fields or any(field not in bytes_per_item for field in fields):
        raise ReplayV11BindingError("unknown HDF5 field in memory estimate")
    return int(frame_count * selected_count * sum(bytes_per_item[field] for field in fields) * 1.5)


def read_hdf5_window(request: Mapping[str, Any], *, io_slot_approved: bool = False) -> dict[str, Any]:
    """Read only the bound all-fluid timeline after an explicit primary I/O grant."""
    if io_slot_approved is not True:
        raise ReplayV11BindingError("trajectory HDF5 read requires io_slot_approved=True")
    bound = validate_replay_request(request, verify_sources=True, verify_hdf5_stat=True)
    try:
        import h5py  # type: ignore
    except ImportError as error:
        raise ReplayV11BindingError("h5py is required for the approved replay slot") from error
    h5 = bound["_verified_hdf5"]
    start, stop = int(bound["window"]["frame_start"]), int(bound["window"]["frame_stop"])
    with h5py.File(h5["path"], "r") as source:
        expected = {
            "time": (401,), "position": (401, 418104, 3), "velocity": (401, 418104, 3),
            "mass": (401, 418104), "valid": (401, 418104), "initial_type": (418104,),
            "initial_mk": (418104,), "particle_zone": (418104,), "particle_id": (418104,),
            "initial_mass": (418104,),
        }
        for name, shape in expected.items():
            if name not in source or tuple(source[name].shape) != shape:
                raise ReplayV11BindingError(f"HDF5 field {name!r} shape differs from CURRENT")
        full_type = source["initial_type"][...]
        full_mk = source["initial_mk"][...]
        full_zone = source["particle_zone"][...]
        full_id = source["particle_id"][...]
        full_mass = source["initial_mass"][...]
        full_position0 = source["position"][0, ...]
        selected, _ = select_fluid_cohort(
            full_position0, full_type, full_mk, full_zone, full_id, full_mass, bound["cohort"])
        estimate = estimate_window_bytes(stop - start + 1, len(selected))
        if estimate > int(bound["window"]["max_memory_bytes"]):
            raise ReplayV11BindingError("HDF5 window exceeds frozen memory bound")
        count = stop - start + 1
        # Preallocation avoids the temporary list-of-frames peak from np.stack.
        trajectory: dict[str, Any] = {
            "time": source["time"][start:stop + 1],
            "position": np.empty((count, len(selected), 3), dtype=source["position"].dtype),
            "velocity": np.empty((count, len(selected), 3), dtype=source["velocity"].dtype),
            "mass": np.empty((count, len(selected)), dtype=source["mass"].dtype),
            "valid": np.empty((count, len(selected)), dtype=source["valid"].dtype),
            "initial_position": full_position0[selected],
            "initial_type": full_type[selected],
            "initial_mk": full_mk[selected],
            "particle_zone": full_zone[selected],
            "particle_id": full_id[selected],
            "initial_mass": full_mass[selected],
        }
        for local, frame in enumerate(range(start, stop + 1)):
            trajectory["position"][local, ...] = source["position"][frame, selected, :]
            trajectory["velocity"][local, ...] = source["velocity"][frame, selected, :]
            trajectory["mass"][local, ...] = source["mass"][frame, selected]
            trajectory["valid"][local, ...] = source["valid"][frame, selected]
    local_request = json.loads(json.dumps(bound))
    local_request["window"]["frame_start"] = 0
    local_request["window"]["frame_stop"] = stop - start
    local_request["window"]["expected_times_s"] = np.asarray(trajectory["time"], dtype=float).tolist()
    return replay_trajectory(trajectory, local_request)


def manufactured_replay_calibration() -> dict[str, Any]:
    """Independent hand-expected checks for normalized velocity and event labels."""
    points = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0]])
    masses = np.array([1.0, 2.0, 7.0])
    velocities = np.array([[1.0, 0.0, 0.0], [3.0, 0.0, 0.0], [5.0, 0.0, 0.0]])
    mean, ke, known_mass, missing = normalized_mass_velocity(velocities, masses)
    if mean is None or not np.allclose(mean, [4.2, 0.0, 0.0]) or not math.isclose(float(ke), 97.0) or known_mass != 10.0 or missing != 0.0:
        raise ReplayV11BindingError("hand normalized velocity expectation failed")
    scaled_mean, scaled_ke, _, _ = normalized_mass_velocity(velocities, masses * 7.0)
    if scaled_mean is None or not np.allclose(scaled_mean, [4.2, 0.0, 0.0]) or not math.isclose(float(scaled_ke), 679.0):
        raise ReplayV11BindingError("velocity mass scaling expectation failed")
    partial = velocities.copy()
    partial[1, :] = np.nan
    partial_mean, partial_ke, partial_mass, partial_missing = normalized_mass_velocity(partial, masses)
    if partial_mean is None or not np.allclose(partial_mean, [4.5, 0.0, 0.0]) or not math.isclose(float(partial_ke), 88.0) or partial_mass != 8.0 or partial_missing != 2.0:
        raise ReplayV11BindingError("partial velocity expectation failed")
    # A finite retained point with valid=False is still unknown, and its
    # frozen initial mass is not appended to the initial denominator.
    invalid_point = mass_observation(
        np.array([[0.0, 0.0, 0.0], [0.4, 0.0, 0.0]]),
        np.array([1.0, 999.0]), np.zeros((2, 3)),
        denominator=3.0, missing_mass=0.0, valid=np.array([True, False]),
        initial_masses=np.array([1.0, 2.0]), pose=None, scale_m=1.0,
        quantiles=[1.0], bin_edges=[-1.0, 1.0])
    if invalid_point["known_mass_kg"] != 1.0 or invalid_point["later_invalid_or_missing_mass_bucket_kg"] != 2.0:
        raise ReplayV11BindingError("finite invalid particle was incorrectly observed")
    # Three particles disappear after their initial frame.  The initial
    # denominator stays 3 kg; the 1 kg later-missing bucket is reported once.
    later_missing = mass_observation(
        np.array([[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]),
        np.array([1.0, np.nan, np.nan]), np.zeros((3, 3)),
        denominator=3.0, missing_mass=0.0, valid=np.array([True, False, False]),
        initial_masses=np.array([1.0, 1.0, 1.0]), pose=None, scale_m=1.0,
        quantiles=[1.0], bin_edges=[-1.0, 1.0])
    if later_missing["initial_mass_denominator_kg"] != 3.0 or later_missing["later_invalid_or_missing_mass_bucket_kg"] != 2.0:
        raise ReplayV11BindingError("later missing mass changed denominator or was not bucketed")
    times = np.array([0.0, 1.0, 2.0, 3.0])
    observed = event_label(times, np.array([-1.0, -0.5, 0.5, 1.0]), np.ones(4, dtype=bool),
                           np.zeros((4, 3)))
    if observed["status"] != "observed" or not math.isclose(observed["event_time_s"], 1.5):
        raise ReplayV11BindingError("hand first-arrival expectation failed")
    censored = event_label(times, np.array([-1.0, -0.5, -0.2, -0.1]), np.ones(4, dtype=bool))
    failed = event_label(times, np.array([-1.0, -0.5, -0.2, -0.1]), np.array([True, True, False, False]))
    inside = event_label(times, np.array([1.0, 0.8, 0.5, 0.2]), np.ones(4, dtype=bool))
    if censored["status"] != "right_censored" or failed["status"] != "failed_before_observation" or inside["status"] != "initially_inside":
        raise ReplayV11BindingError("hand censoring state expectation failed")
    ambiguous = event_label(times, np.array([-1.0, -0.5, 0.5, 1.0]), np.ones(4, dtype=bool),
                            explicit_crossing_times=[1.2, 1.8])
    if ambiguous["status"] != "ambiguous_multiple_crossing":
        raise ReplayV11BindingError("same-bracket multiple-candidate counterexample failed")
    r = residence(times, np.array([-1.0, -0.5, 0.5, 1.0]), np.ones(4, dtype=bool))
    f = flux(times, np.array([-1.0, -0.5, 0.5, 1.0]), np.ones(4, dtype=bool),
             np.full(4, 2.0))
    if not math.isclose(r["known_residence_s"], 1.5) or not math.isclose(f["net_flux_mass_kg"], 2.0):
        raise ReplayV11BindingError("hand residence/flux expectation failed")
    repeated = adapt_v4_saved_bracket_events(
        [{"bracket_index": 0, "candidate_times_s": [0.5]},
         {"bracket_index": 2, "candidate_times_s": [2.5]}],
        [[0.0, 1.0], [1.0, 2.0], [2.0, 3.0]], 2)
    if repeated["status"] != "observed" or repeated["later_saved_crossing_times_s"] != [2.5]:
        raise ReplayV11BindingError("explicit multi-bracket v4 repeat expectation failed")
    ambiguous_v4 = adapt_v4_saved_bracket_events(
        [{"bracket_index": 0, "candidate_times_s": [0.2, 0.8]}],
        [[0.0, 1.0], [1.0, 2.0]], 2)
    if ambiguous_v4["status"] != "ambiguous_multiple_crossing":
        raise ReplayV11BindingError("same-bracket v4 ambiguity expectation failed")
    return {
        "schema": CALIBRATION_SCHEMA, "status": "PASS", "model_invoked": False,
        "normalized_mean_velocity_m_s": [4.2, 0.0, 0.0],
        "normalized_kinetic_energy_J": 97.0,
        "partial_velocity_missing_mass_kg": 2.0,
        "finite_invalid_point_bucket_kg": 2.0,
        "later_missing_denominator_kg": 3.0,
        "v4_multi_bracket_repeat": repeated,
        "first_arrival_time_s": 1.5, "residence_s": 1.5, "net_flux_mass_kg": 2.0,
        "states": ["observed", "right_censored", "failed_before_observation",
                   "initially_inside", "ambiguous_multiple_crossing"],
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def _cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--manufactured-only", action="store_true")
    parser.add_argument("--io-slot-approved", action="store_true")
    args = parser.parse_args()
    if args.manufactured_only:
        print(json.dumps(manufactured_replay_calibration(), indent=2, sort_keys=True))
        return 0
    if args.request is None:
        parser.error("--request is required unless --manufactured-only is used")
    request = json.loads(args.request.read_text())
    if args.io_slot_approved:
        result = read_hdf5_window(request, io_slot_approved=True)
    else:
        result = validate_replay_request(request)
        result["status"] = "VALIDATED_PENDING_IO_SLOT"
        result.pop("_verified_sources", None)
        result.pop("_verified_hdf5", None)
    print(json.dumps(result, indent=2, sort_keys=True, default=lambda x: x.tolist() if isinstance(x, np.ndarray) else x))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
