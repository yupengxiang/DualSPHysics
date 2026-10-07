#!/usr/bin/env python3
"""F2-S1 replay v15: source-bound motion completion semantics.

The v14 implementation remains byte-frozen.  v14 rejected the last CURRENT
sample because it is a few microseconds after the ``finish=4`` event even
though the native JMotion implementation keeps the completed pose.  This
module wraps the v14 operators and adds the narrowly bound, source-backed
completion rule:

* ``0 <= t < finish`` uses the motion file interpolation;
* ``t >= finish`` uses the last file angle and zero angular velocity;
* a query after the bound CURRENT window, or before the active interval, is
  rejected rather than extrapolated.

The wrapper is deliberately separate from v14.  It never changes v14 module
globals on disk and every scientific qualification remains UNKNOWN.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence
import xml.etree.ElementTree as ET

import numpy as np

import ds_data02_stage2_f2_replay_v14 as v14


REQUEST_SCHEMA = "ds02.stage2.f2-s1-replay-request.v15"
RESULT_SCHEMA = "ds02.stage2.f2-s1-replay-result.v15"
MOTION_SEMANTICS_SCHEMA = "ds02.stage2.f2-s1-motion-completion-semantics.v15"
ENGINE_SOURCE_ROLES = (
    "motion_engine_jmotion_obj",
    "motion_engine_jmotion_mov",
    "motion_engine_jmotion_data",
)


class ReplayV15BindingError(v14.ReplayV14BindingError):
    """Raised when v15 request or motion-completion semantics are invalid."""


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, np.number)):
        raise ReplayV15BindingError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ReplayV15BindingError(f"{name} must be finite")
    return result


def _as_v14_request(request: Mapping[str, Any]) -> dict[str, Any]:
    """Make an in-memory v14 view for the frozen v14 reader implementation."""
    if not isinstance(request, Mapping):
        raise ReplayV15BindingError("request must be an object")
    view = copy.deepcopy(dict(request))
    view["schema"] = v14.REQUEST_SCHEMA
    # v14's frozen validator used a now-corrected diagnostic phrase for the
    # ROT090 name.  Keep that compatibility value only in this in-memory
    # adapter; the v15 request itself records the physical timing/angle
    # semantics without the old conflict claim.
    control = view.get("motion_control")
    # v14 also called the four-second table coverage a motion duration.  Its
    # validator is immutable, so preserve that view while v15 exposes the
    # distinct rotation_duration_s and table_coverage_s fields.
    if isinstance(control, dict):
        control["case_name_angle_conflict"] = (
            "case label ROT090; actual SHA-bound motion.dat terminal angle is -105 deg")
    return view


def _xml_motion_semantics(xml_path: Path | str) -> dict[str, Any]:
    """Read all repeated casedef/execution motion declarations consistently."""
    try:
        root = ET.parse(Path(xml_path)).getroot()
    except (OSError, ET.ParseError) as error:
        raise ReplayV15BindingError("generated XML cannot be parsed for motion semantics") from error
    begins: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    for obj in root.findall(".//objreal"):
        if obj.get("ref") != "0":
            continue
        for begin in obj.findall("./begin"):
            begins.append({
                "mov": begin.get("mov"),
                "start_s": _finite(float(begin.get("start", "nan")), "XML begin.start"),
                "finish_s": _finite(float(begin.get("finish", "nan")), "XML begin.finish"),
            })
        for node in obj.findall("./mvrotfile"):
            files.append({
                "id": node.get("id"),
                "duration_s": _finite(float(node.get("duration", "nan")), "XML mvrotfile.duration"),
                "angles_units": node.get("anglesunits"),
            })
    if not begins or not files or len(begins) != len(files):
        raise ReplayV15BindingError("XML does not contain paired ref=0 begin/mvrotfile declarations")
    first_begin, first_file = begins[0], files[0]
    for item in begins[1:]:
        if item != first_begin:
            raise ReplayV15BindingError("repeated XML begin declarations disagree")
    for item in files[1:]:
        if item != first_file:
            raise ReplayV15BindingError("repeated XML mvrotfile declarations disagree")
    if first_begin["mov"] != first_file["id"]:
        raise ReplayV15BindingError("XML begin mov does not bind mvrotfile id")
    return {
        "source_role": "generated_xml",
        "objreal_ref": 0,
        "begin_start_s": first_begin["start_s"],
        "finish_s": first_begin["finish_s"],
        "motion_file_duration_s": first_file["duration_s"],
        "angles_units": first_file["angles_units"],
        "declaration_count": len(begins),
    }


def _engine_source_binding(request: Mapping[str, Any]) -> dict[str, str]:
    values = request.get("motion_engine_sources")
    if not isinstance(values, Mapping):
        raise ReplayV15BindingError("motion_engine_sources is required")
    result: dict[str, str] = {}
    for role in ENGINE_SOURCE_ROLES:
        item = values.get(role)
        if not isinstance(item, Mapping) or not isinstance(item.get("path"), str):
            raise ReplayV15BindingError(f"missing official motion source {role}")
        expected = item.get("sha256")
        if not isinstance(expected, str) or len(expected) != 64:
            raise ReplayV15BindingError(f"official motion source {role} has no SHA-256")
        path = Path(item["path"]).expanduser()
        if not path.is_file():
            raise ReplayV15BindingError(f"official motion source is missing: {path}")
        actual = v14.sha256(path)
        if actual != expected:
            raise ReplayV15BindingError(f"official motion source SHA differs: {role}")
        result[role] = expected
    return result


def validate_motion_completion_contract(request: Mapping[str, Any]) -> dict[str, Any]:
    """Validate XML finish semantics and the official source proof."""
    if request.get("schema") != REQUEST_SCHEMA:
        raise ReplayV15BindingError("unsupported v15 request schema")
    source_files = request.get("source_files")
    if not isinstance(source_files, list):
        raise ReplayV15BindingError("source_files are required")
    by_role = {item.get("role"): item for item in source_files if isinstance(item, Mapping)}
    xml_item = by_role.get("generated_xml")
    motion_item = by_role.get("motion_dat")
    metadata_item = by_role.get("source_metadata")
    if (not isinstance(xml_item, Mapping) or not isinstance(motion_item, Mapping) or
            not isinstance(metadata_item, Mapping)):
        raise ReplayV15BindingError("generated XML, motion.dat, and source metadata bindings are required")
    xml_semantics = _xml_motion_semantics(xml_item["path"])
    control = request.get("motion_control")
    if not isinstance(control, Mapping):
        raise ReplayV15BindingError("motion_control is required")
    if (control.get("completion_policy") != "hold_last_pose_zero_angular_velocity_after_finish" or
            control.get("active_interval_s") != [0.0, 4.0] or
            control.get("finish_inclusive") is not True):
        raise ReplayV15BindingError("motion completion policy is not explicit")
    if not math.isclose(xml_semantics["begin_start_s"], float(control["active_interval_s"][0]), rel_tol=0.0, abs_tol=1e-12):
        raise ReplayV15BindingError("XML begin start differs from motion contract")
    if not math.isclose(xml_semantics["finish_s"], float(control["finish_s"]), rel_tol=0.0, abs_tol=1e-12):
        raise ReplayV15BindingError("XML begin finish differs from motion contract")
    if not math.isclose(xml_semantics["motion_file_duration_s"], float(control["finish_s"]), rel_tol=0.0, abs_tol=1e-12):
        raise ReplayV15BindingError("XML motion-file duration differs from finish contract")
    if xml_semantics["angles_units"] != "degrees":
        raise ReplayV15BindingError("motion completion contract requires degree angles")
    try:
        metadata = json.loads(Path(metadata_item["path"]).read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ReplayV15BindingError("source metadata cannot be read") from error
    try:
        parameter_values = metadata["parameter_values"]
        motion_metadata = metadata["motion"]
        metadata_motion_sha = motion_metadata["sha256"]
        rotation_duration = float(parameter_values["rotation_duration_s"])
        rotation_stop = float(motion_metadata["rotation_stop_s"])
        hold_start = float(motion_metadata["static_hold_start_s"])
        final_angle = float(motion_metadata["final_angle_deg"])
    except (KeyError, TypeError, ValueError) as error:
        raise ReplayV15BindingError("source metadata lacks explicit rotation timing/angle") from error
    if v14.sha256(metadata_item["path"]) != metadata_item.get("sha256"):
        raise ReplayV15BindingError("source metadata SHA-256 differs")
    if (metadata.get("schema") != "ds02.f2.stage1.first48.prospective-source.v1" or
            metadata_motion_sha != motion_item.get("sha256") or
            not math.isclose(rotation_duration, 0.9, rel_tol=0.0, abs_tol=1e-12) or
            not math.isclose(rotation_stop, 1.4, rel_tol=0.0, abs_tol=1e-12) or
            not math.isclose(hold_start, 0.5, rel_tol=0.0, abs_tol=1e-12) or
            not math.isclose(final_angle, -105.0, rel_tol=0.0, abs_tol=1e-12)):
        raise ReplayV15BindingError("source metadata rotation semantics differ")
    expected_control = {
        "rotation_duration_s": rotation_duration,
        "rotation_hold_start_s": hold_start,
        "rotation_stop_s": rotation_stop,
        "table_coverage_s": [float(xml_semantics["begin_start_s"]), float(xml_semantics["finish_s"])],
    }
    for key, expected in expected_control.items():
        actual = control.get(key)
        if isinstance(expected, list):
            if (not isinstance(actual, list) or len(actual) != len(expected) or
                    any(not math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=1e-12)
                        for a, b in zip(actual, expected))):
                raise ReplayV15BindingError(f"motion_control.{key} differs from source-bound metadata")
        else:
            try:
                matches = math.isclose(float(actual), float(expected), rel_tol=0.0, abs_tol=1e-12)
            except (TypeError, ValueError):
                matches = False
            if not matches:
                raise ReplayV15BindingError(f"motion_control.{key} differs from source-bound metadata")
    receipt_support: dict[str, Any] = {}
    for role in ("gencase_receipt", "solver_receipt"):
        item = by_role.get(role)
        if not isinstance(item, Mapping):
            raise ReplayV15BindingError(f"{role} is required for motion source provenance")
        try:
            receipt = json.loads(Path(item["path"]).read_text())
        except (OSError, json.JSONDecodeError) as error:
            raise ReplayV15BindingError(f"{role} cannot be read") from error
        launch = receipt.get("input_hashes_at_launch", {})
        finish = receipt.get("input_hashes_after_run", {})
        if not isinstance(launch, Mapping) or not isinstance(finish, Mapping):
            raise ReplayV15BindingError(f"{role} lacks input hash receipts")
        metadata_supported = any(value == metadata_item["sha256"] for value in launch.values())
        metadata_supported = metadata_supported and any(value == metadata_item["sha256"] for value in finish.values())
        motion_supported = any(value == motion_item["sha256"] for value in launch.values())
        motion_supported = motion_supported and any(value == motion_item["sha256"] for value in finish.values())
        if not metadata_supported or not motion_supported:
            raise ReplayV15BindingError(f"{role} does not support source metadata and motion hashes")
        receipt_support[role] = {
            "metadata_sha256_supported_at_launch_and_finish": True,
            "motion_sha256_supported_at_launch_and_finish": True,
            "receipt_sha256": item["sha256"],
        }
    window = request.get("window")
    if not isinstance(window, Mapping):
        raise ReplayV15BindingError("window is required")
    expected_times = np.asarray(window.get("expected_times_s"), dtype=float).reshape(-1)
    if len(expected_times) < 2 or not np.isfinite(expected_times).all() or np.any(np.diff(expected_times) <= 0):
        raise ReplayV15BindingError("window expected times are malformed")
    hold_until = _finite(control.get("hold_until_s"), "motion_control.hold_until_s")
    if not math.isclose(hold_until, float(expected_times[-1]), rel_tol=0.0, abs_tol=2e-8):
        raise ReplayV15BindingError("post-finish hold is not bounded by the frozen CURRENT timeline")
    if hold_until < float(control["finish_s"]):
        raise ReplayV15BindingError("post-finish hold bound precedes the control finish")
    motion_times, motion_angles = v14.read_motion_dat(motion_item["path"])
    if (not math.isclose(float(motion_times[0]), float(control["active_interval_s"][0]), rel_tol=0.0, abs_tol=1e-12) or
            not math.isclose(float(motion_times[-1]), float(control["finish_s"]), rel_tol=0.0, abs_tol=1e-12) or
            not math.isclose(float(motion_angles[0]), float(control["start_angle_deg"]), rel_tol=0.0, abs_tol=1e-12) or
            not math.isclose(float(motion_angles[-1]), float(control["end_angle_deg"]), rel_tol=0.0, abs_tol=1e-12)):
        raise ReplayV15BindingError("motion.dat endpoints differ from the v15 completion contract")
    engine_hashes = _engine_source_binding(request)
    return {
        "schema": MOTION_SEMANTICS_SCHEMA,
        "active_interval_s": [float(control["active_interval_s"][0]), float(control["active_interval_s"][1])],
        "finish_s": float(control["finish_s"]),
        "hold_until_s": hold_until,
        "start_angle_deg": float(motion_angles[0]),
        "finish_angle_deg": float(motion_angles[-1]),
        "post_finish_angular_velocity_world_rad_s": [0.0, 0.0, 0.0],
        "policy": "hold_last_pose_zero_angular_velocity_after_finish",
        "xml": xml_semantics,
        "motion_dat_sha256": motion_item["sha256"],
        "source_metadata_sha256": metadata_item["sha256"],
        "receipt_input_hash_support": receipt_support,
        "rotation_duration_s": rotation_duration,
        "rotation_stop_s": rotation_stop,
        "static_hold_start_s": hold_start,
        "table_coverage_s": [0.0, float(xml_semantics["finish_s"])],
        "rotation_semantics": "0..0.5 static hold; 0.5..1.4 time-scaled rotation; 1.4..4 static final pose",
        "official_engine_source_sha256": engine_hashes,
        "source_basis": "src/source/JMotionObj.cpp DfGetNewAng last-value hold plus ProcessTime finish deletion",
        "status": "SOURCE_BOUND_DEVELOPMENT_UNKNOWN",
    }


def validate_request_v15(request: Mapping[str, Any], *, verify_sources: bool = False,
                         verify_hdf5_stat: bool = False) -> dict[str, Any]:
    """Validate v15 plus all frozen v14 source/CURRENT contracts."""
    if not isinstance(request, Mapping) or request.get("schema") != REQUEST_SCHEMA:
        raise ReplayV15BindingError("unsupported v15 replay request schema")
    try:
        bound_v14 = v14.validate_replay_request(_as_v14_request(request),
                                                verify_sources=verify_sources,
                                                verify_hdf5_stat=verify_hdf5_stat)
    except v14.ReplayV14BindingError as error:
        raise ReplayV15BindingError(str(error)) from error
    semantics = validate_motion_completion_contract(request)
    result = dict(request)
    result["motion_completion_semantics"] = semantics
    result["_verified_sources"] = bound_v14.get("_verified_sources", [])
    result["_verified_hdf5"] = bound_v14.get("_verified_hdf5")
    return result


def motion_pose_v15(times: Sequence[float], motion_times: Sequence[float],
                    motion_angles_deg: Sequence[float], axis_p1_m: Sequence[float],
                    axis_p2_m: Sequence[float], *, finish_time_s: float,
                    hold_until_s: float) -> list[dict[str, Any]]:
    """Evaluate native file motion with an explicit finite post-finish hold."""
    query = v14._float_array(times, "query times").reshape(-1)
    mt = v14._strict_increasing(motion_times, "motion times")
    ma = v14._float_array(motion_angles_deg, "motion angles").reshape(-1)
    if len(mt) != len(ma) or not np.isfinite(ma).all():
        raise ReplayV15BindingError("motion arrays are malformed")
    finish = _finite(finish_time_s, "finish_time_s")
    hold_until = _finite(hold_until_s, "hold_until_s")
    if hold_until < finish or np.any(query < mt[0]) or np.any(query > hold_until + 2e-12):
        raise ReplayV15BindingError("query time is outside the active interval or bounded post-finish hold")
    if mt[-1] > finish + 1e-12:
        raise ReplayV15BindingError("motion data extends beyond the XML finish")
    p1, p2 = v14._finite_vector(axis_p1_m, "axis_p1_m"), v14._finite_vector(axis_p2_m, "axis_p2_m")
    axis = p2 - p1
    axis_unit = axis / np.linalg.norm(axis)
    angle_rad = np.deg2rad(ma)
    angular_rate = np.gradient(angle_rad, mt) if len(mt) > 1 else np.zeros_like(angle_rad)
    result: list[dict[str, Any]] = []
    for time in query:
        t = float(time)
        if t >= finish - 2e-12:
            # Native JMotion's completed event retains DfAng[last] and stops
            # reporting motion after Finish.  The inclusive tolerance only
            # absorbs the saved-time roundoff around the finish event.
            angle = float(ma[-1])
            rate = 0.0
            phase = "POST_FINISH_HOLD"
        elif t <= mt[-1]:
            angle = float(np.interp(t, mt, ma))
            rate = float(np.interp(t, mt, angular_rate))
            phase = "ACTIVE_FILE_INTERPOLATION"
        else:
            # JMotion DfGetNewAng returns the last value when the file is
            # exhausted; this branch is still inside the explicitly active
            # event and therefore cannot be used past hold_until.
            angle = float(ma[-1])
            rate = 0.0
            phase = "ACTIVE_FILE_LAST_VALUE_HOLD"
        result.append({
            "time_s": t,
            "angle_deg": angle,
            "rotation_matrix": v14._rotation_about_axis(axis, math.radians(angle)),
            "translation_m": p1.copy(),
            "translation_velocity_m_s": np.zeros(3),
            "angular_velocity_world_rad_s": axis_unit * rate,
            "motion_phase": phase,
            "pose_frame": "world_to_body_rotation_about_bound_axis",
        })
    return result


def _with_motion_pose_v15(callback: Any, request: Mapping[str, Any]) -> Any:
    bound = validate_request_v15(request, verify_sources=False, verify_hdf5_stat=False)
    control = bound["motion_control"]
    finish = float(control["finish_s"])
    hold_until = float(control["hold_until_s"])
    old_pose = v14.motion_pose

    def patched(times: Sequence[float], motion_times: Sequence[float],
                motion_angles_deg: Sequence[float], axis_p1_m: Sequence[float],
                axis_p2_m: Sequence[float]) -> list[dict[str, Any]]:
        return motion_pose_v15(times, motion_times, motion_angles_deg, axis_p1_m,
                               axis_p2_m, finish_time_s=finish, hold_until_s=hold_until)

    v14.motion_pose = patched
    try:
        return callback(_as_v14_request(request))
    finally:
        v14.motion_pose = old_pose


def replay_trajectory_v15(trajectory: Mapping[str, Any], request: Mapping[str, Any]) -> dict[str, Any]:
    """Replay an in-memory trajectory with v15 motion completion semantics."""
    validate_request_v15(request)
    result = _with_motion_pose_v15(
        lambda view: v14.replay_trajectory(trajectory, view), request)
    result["schema"] = RESULT_SCHEMA
    result["replay_implementation"] = "v15_motion_completion_wrapper_over_v14_immutable_operators"
    result["motion_completion_semantics"] = validate_motion_completion_contract(request)
    result["quality"] = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
                          "qualification": "UNKNOWN"}
    return result


def read_hdf5_initial_frame_v15(request: Mapping[str, Any], *, io_slot_approved: bool = False) -> dict[str, Any]:
    validate_request_v15(request, verify_sources=True, verify_hdf5_stat=True)
    result = v14.read_hdf5_initial_frame(_as_v14_request(request), io_slot_approved=io_slot_approved)
    result["schema"] = "ds02.stage2.f2-s1-initial-frame-result.v15"
    result["motion_completion_semantics"] = validate_motion_completion_contract(request)
    return result


def read_hdf5_window_v15(request: Mapping[str, Any], *, io_slot_approved: bool = False) -> dict[str, Any]:
    """Read the full bound HDF5 window through the parent-approved v14 reader."""
    validate_request_v15(request, verify_sources=True, verify_hdf5_stat=True)
    result = _with_motion_pose_v15(
        lambda view: v14.read_hdf5_window(view, io_slot_approved=io_slot_approved), request)
    result["schema"] = RESULT_SCHEMA
    result["replay_implementation"] = "v15_motion_completion_wrapper_over_v14_immutable_reader"
    result["motion_completion_semantics"] = validate_motion_completion_contract(request)
    result["quality"] = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
                          "qualification": "UNKNOWN"}
    return result


def validate_result_source_profile(result: Mapping[str, Any], request: Mapping[str, Any],
                                   profile: Mapping[str, Any]) -> dict[str, Any]:
    """Independently verify result/profile/request source identity before scoring."""
    if not isinstance(result, Mapping) or result.get("schema") != RESULT_SCHEMA:
        raise ReplayV15BindingError("result is not a v15 replay result")
    validate_request_v15(request, verify_sources=True, verify_hdf5_stat=True)
    view = _as_v14_request(request)
    v14.validate_observer_profile(profile, request=view)
    source = result.get("source_binding")
    if not isinstance(source, Mapping):
        raise ReplayV15BindingError("result source binding is missing")
    expected = {
        "current_catalog_sha256": request["current_binding"]["sha256"],
        "trajectory_h5_producer_sha256": request["trajectory_h5"]["producer_declared_sha256"],
        "source_files": {str(item["role"]): item["sha256"] for item in request["source_files"]},
    }
    for key, value in expected.items():
        if source.get(key) != value:
            raise ReplayV15BindingError(f"result source binding differs from frozen request: {key}")
    if result.get("observer_profile", {}).get("sha256") != profile.get("sha256"):
        raise ReplayV15BindingError("result observer profile hash differs")
    return {
        "schema": "ds02.stage2.f2-s1-source-profile-binding-check.v15",
        "status": "PASS_SOURCE_PROFILE_BOUND_DEVELOPMENT",
        "current_catalog_sha256": expected["current_catalog_sha256"],
        "trajectory_h5_producer_sha256": expected["trajectory_h5_producer_sha256"],
        "source_file_count": len(expected["source_files"]),
        "observer_profile_sha256": profile["sha256"],
        "trajectory_content_sha256": request["portable_migration"].get("expected_trajectory_content_sha256"),
        "content_hash_credit": "requires parent guard full-H5 digest; this check does not reread H5",
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "model_invoked": False,
    }


def evaluate_receiver_manual_predictions_v15(result: Mapping[str, Any], predictions: Mapping[str, Any],
                                             profile: Mapping[str, Any], *,
                                             frozen_request: Mapping[str, Any]) -> dict[str, Any]:
    """Use the immutable v14 scorer only after the v15 source/profile gate."""
    validate_result_source_profile(result, frozen_request, profile)
    result_view = copy.deepcopy(dict(result))
    result_view["schema"] = v14.RESULT_SCHEMA
    return v14.evaluate_receiver_manual_predictions(
        result_view, predictions, profile, frozen_request=_as_v14_request(frozen_request))


__all__ = [
    "REQUEST_SCHEMA", "RESULT_SCHEMA", "MOTION_SEMANTICS_SCHEMA",
    "ReplayV15BindingError", "validate_motion_completion_contract",
    "validate_request_v15", "motion_pose_v15", "replay_trajectory_v15",
    "read_hdf5_initial_frame_v15", "read_hdf5_window_v15",
    "validate_result_source_profile", "evaluate_receiver_manual_predictions_v15",
]
