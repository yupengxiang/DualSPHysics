"""Static provenance checks for the terminal-bound OFFSET postprocess handoff."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[6]
FAMILY = ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F2"
HANDOFF = FAMILY / "handoff_20261003/offset_baseline_terminal_v1"
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2")
CASE = "F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001"
CONVERSION = DATA / CASE / (
    "conversion-f2_rv4eq_dp005_offset_v1_baseline_save001-fullstate-root-reviewed-005"
)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_offset_conversion_is_terminal_and_source_bound():
    report = load(CONVERSION / "conversion-report.json")
    receipt = load(CONVERSION / "execution-receipt.json")
    owner = load(HANDOFF / "owner_metadata" / f"{CASE}.owner.v2-terminal-bound.json")

    assert report["conversion_status"] == "completed"
    assert receipt["status"] == "completed"
    assert receipt["returncode"] == 0
    assert report["frames"] == 401
    assert report["solver_dimension"]["solver_dimension"] == 3
    assert report["solver_dimension"]["xml_data2d"] == "false"
    assert report["output_sha256"] == owner["fullstate_terminal_binding"]["trajectory_h5"]["sha256"]
    assert owner["physical_condition_hash_declared"] == "327899e38bbad63951206d5b2fd3ef354c049a32f6671af1af7913a48b77c7ef"
    assert owner["mechanism_id"] == "offset_spill"
    assert owner["fullstate_terminal_binding"]["conversion_report"]["sha256"] == sha256(CONVERSION / "conversion-report.json")
    assert owner["fullstate_terminal_binding"]["conversion_receipt"]["sha256"] == sha256(CONVERSION / "execution-receipt.json")


def test_offset_cpu_requests_are_root_only_and_keep_unknown_separate():
    labels = load(HANDOFF / "labels_requests" / f"{CASE}_labels_request_v2_terminal_ready.json")
    qi = load(HANDOFF / "qi_audit" / f"{CASE}_actual_qi_request_v1_terminal_bound_deferred.json")
    manifest = load(HANDOFF / "offset_postprocess_handoff_manifest_v1.json")
    identity = load(HANDOFF / "typed_identity" / f"{CASE}.identity-correction-sidecar.v1.json")

    assert labels["launch_allowed"] is False
    assert labels["root_only"] is True
    assert labels["gpu_launch"]["primary_process_gpu_only"] is True
    assert labels["cpu_task_kind"] == "actual_saved_moving_pose_and_v6_event_labels"
    assert labels["pose_semantics"]["derived_dataset"] == "rigid_body_state"
    assert labels["native_exclusion_semantics"] == {
        "unknown_count": 2151,
        "mk_counts": {"1": 962, "2": 335, "3": 854},
        "motive_is_not_spill": True,
        "unknown_mass_remains_in_denominator": True,
    }
    assert qi["launch_allowed"] is False
    assert qi["status"] == "deferred_until_offset_pose_labels_terminal"
    assert qi["deferred_input_bindings"]["trajectory_with_actual_pose"]["sha256"] is None
    assert qi["source_bindings"]["terminal_trajectory_h5"]["sha256"] == labels["source_bindings"]["trajectory_h5"]["sha256"]
    assert identity["unknown_native_exclusions"]["count"] == 2151
    assert identity["unknown_native_exclusions"]["mk_counts"] == {"1": 962, "2": 335, "3": 854}
    assert identity["unknown_native_exclusions"]["physical_spill_inference"] is False
    assert manifest["launch_policy"]["conversion"] is False
    assert manifest["q_n_status"] == "not_assessed"
