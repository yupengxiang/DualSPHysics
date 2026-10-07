from __future__ import annotations

import json
import hashlib
from pathlib import Path
import sys

import numpy as np
import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import ds_data02_stage2_f2_replay_v15 as v15  # noqa: E402
import ds_data02_stage2_f2_replay_v14 as v14  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
V14_REQUEST = ROOT / "campaigns/ds-data-02/stage2/replay/v14/f2-s1-replay-request-v14-001.json"


def _request() -> dict:
    request = json.loads(V14_REQUEST.read_text())
    request["schema"] = v15.REQUEST_SCHEMA
    request["request_id"] = "test-f2-s1-v15-motion-completion"
    metadata_path = ROOT / "campaigns/ds-data-02/review_20261007/evidence/E01204/F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010.metadata.json"
    metadata_sha = v14.sha256(metadata_path)
    request["source_files"].append({
        "path": str(metadata_path.resolve()), "role": "source_metadata", "sha256": metadata_sha,
    })
    request["motion_control"] = {
        **request["motion_control"],
        "active_interval_s": [0.0, 4.0],
        "finish_s": 4.0,
        "finish_inclusive": True,
        "hold_until_s": request["window"]["expected_times_s"][-1],
        "completion_policy": "hold_last_pose_zero_angular_velocity_after_finish",
        "rotation_duration_s": 0.9,
        "rotation_hold_start_s": 0.5,
        "rotation_stop_s": 1.4,
        "table_coverage_s": [0.0, 4.0],
    }
    request["observer_profile"]["source_file_sha256"]["source_metadata"] = metadata_sha
    profile_payload = {k: value for k, value in request["observer_profile"].items() if k != "sha256"}
    request["observer_profile"]["sha256"] = hashlib.sha256(
        json.dumps(profile_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()
    source = ROOT.parents[0] / "src/source"
    request["motion_engine_sources"] = {
        "motion_engine_jmotion_obj": {
            "path": str((source / "JMotionObj.cpp").resolve()),
            "sha256": v14.sha256(source / "JMotionObj.cpp"),
        },
        "motion_engine_jmotion_mov": {
            "path": str((source / "JMotionMov.h").resolve()),
            "sha256": v14.sha256(source / "JMotionMov.h"),
        },
        "motion_engine_jmotion_data": {
            "path": str((source / "JMotionData.h").resolve()),
            "sha256": v14.sha256(source / "JMotionData.h"),
        },
    }
    return request


def test_after_finish_saved_time_is_a_finite_static_pose() -> None:
    poses = v15.motion_pose_v15(
        [3.99, 4.0, 4.000007783879406], [0.0, 1.0, 4.0],
        [0.0, -10.0, -105.0], [0.0, -1.0, 0.65], [0.0, 1.0, 0.65],
        finish_time_s=4.0, hold_until_s=4.000007783879406)
    assert poses[-1]["motion_phase"] == "POST_FINISH_HOLD"
    assert poses[-1]["angle_deg"] == -105.0
    assert np.allclose(poses[-1]["angular_velocity_world_rad_s"], [0.0, 0.0, 0.0])
    assert poses[1]["angle_deg"] == -105.0


def test_post_finish_query_beyond_bound_is_rejected() -> None:
    with pytest.raises(v15.ReplayV15BindingError, match="outside"):
        v15.motion_pose_v15(
            [4.1], [0.0, 4.0], [0.0, -105.0], [0.0, -1.0, 0.65],
            [0.0, 1.0, 0.65], finish_time_s=4.0, hold_until_s=4.000007783879406)


def test_active_interval_before_start_is_rejected() -> None:
    with pytest.raises(v15.ReplayV15BindingError, match="outside"):
        v15.motion_pose_v15(
            [-1e-3], [0.0, 4.0], [0.0, -105.0], [0.0, -1.0, 0.65],
            [0.0, 1.0, 0.65], finish_time_s=4.0, hold_until_s=4.000007783879406)


def test_v15_request_binds_xml_finish_and_official_engine_sources() -> None:
    request = _request()
    bound = v15.validate_request_v15(request, verify_sources=False, verify_hdf5_stat=False)
    semantics = bound["motion_completion_semantics"]
    assert semantics["finish_s"] == 4.0
    assert semantics["finish_angle_deg"] == -105.0
    assert semantics["policy"] == "hold_last_pose_zero_angular_velocity_after_finish"
    assert semantics["rotation_duration_s"] == 0.9
    assert semantics["rotation_stop_s"] == 1.4
    assert semantics["official_engine_source_sha256"]["motion_engine_jmotion_obj"]


def test_wrong_finish_contract_is_rejected_without_hdf5_read() -> None:
    request = _request()
    request["motion_control"]["finish_s"] = 3.0
    with pytest.raises(v15.ReplayV15BindingError, match="finish"):
        v15.validate_request_v15(request, verify_sources=False, verify_hdf5_stat=False)
