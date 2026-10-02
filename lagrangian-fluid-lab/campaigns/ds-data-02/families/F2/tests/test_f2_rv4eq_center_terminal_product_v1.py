from __future__ import annotations

import json
from pathlib import Path


FAMILY = Path(__file__).resolve().parents[1]
HANDOFF = FAMILY / "handoff_20261003/center_baseline_terminal_v1"
CASE = "F2_RV4EQ_DP005_CENTER_V1_BASELINE_SAVE001"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_terminal_manifest_is_source_bound_without_qualification_claim():
    manifest = load(HANDOFF / "center_baseline_terminal_manifest_v1.json")
    assert manifest["status"] == "terminal_source_bound_labels_root_review_pending"
    assert manifest["q_i_status"] == "conversion_evidence_only"
    assert manifest["q_n_status"] == "not_assessed"
    assert manifest["launch_policy"] == {
        "solver": False,
        "gencase": False,
        "conversion": False,
        "labels": False,
        "root_owns_dispatch": True,
    }
    assert manifest["native_unknown"] == {
        "count": 2123,
        "mk_counts": {"1": 929, "2": 296, "3": 898},
        "motive_totals": {"1": 2123},
        "physical_fate": "unknown",
    }


def test_terminal_owner_binds_actual_3d_h5_lifecycle_and_motion_inputs():
    owner = load(HANDOFF / "owner_metadata" / f"{CASE}.owner.v2-terminal-bound.json")
    h5 = owner["fullstate_terminal_binding"]["h5_schema_metadata"]
    assert owner["status"] == "terminal_source_bound_pose_labels_deferred"
    assert owner["q_i_status"].startswith("conversion_evidence_only")
    assert owner["q_n_status"] == "not_assessed"
    assert owner["fullstate_terminal_binding"]["trajectory_h5"]["sha256"] == "7b5ec1deac349608edbc0319c7c2c2fda572b10c3d6eb2abef32f9d589ad8669"
    assert h5["has_rigid_body_state"] is False
    assert h5["required_datasets"]["position"]["shape"] == [401, 1668869, 3]
    assert h5["required_datasets"]["velocity"]["shape"] == [401, 1668869, 3]
    assert owner["moving_pose_contract"]["actual_saved_node_state"] == {
        "position_dataset": "position",
        "velocity_dataset": "velocity",
        "initial_type_dataset": "initial_type",
        "moving_type": 1,
        "moving_node_count": 76676,
        "frame_count": 401,
    }
    assert owner["typed_lifecycle_contract"]["final_unknown_count"] == 2123
    assert owner["native_exclusion_evidence"]["typed_mk_totals"] == {"1": 929, "2": 296, "3": 898}
    assert owner["native_exclusion_evidence"]["all_fate_unknown"] is True
    assert owner["native_exclusion_evidence"]["physical_spill_inference"] is False


def test_identity_sidecar_preserves_real_mk_correction_and_mass_semantics():
    sidecar = load(HANDOFF / "typed_identity" / f"{CASE}.identity-correction-sidecar.v1.json")
    assert sidecar["status"] == "actual_native_typed_identity_corrected_unknown"
    assert sidecar["unknown_native_exclusions"]["count"] == 2123
    assert sidecar["unknown_native_exclusions"]["mk_counts"] == {"1": 929, "2": 296, "3": 898}
    assert sidecar["unknown_native_exclusions"]["type"] == 3
    assert sidecar["unknown_native_exclusions"]["physical_spill_inference"] is False
    assert sidecar["mass_semantics"]["xml_massfluid_text"] == "0.000125"
    assert sidecar["mass_semantics"]["xml_massfluid_cohort_mass_kg"] == "24.576000"
    assert sidecar["mass_semantics"]["h5_initial_mass_is_float32_adapter"] is True
    assert sidecar["mass_semantics"]["strict_threshold_remains_frozen"] is True


def test_labels_request_is_correctly_bound_but_root_dispatch_only():
    request = load(HANDOFF / "labels_requests" / f"{CASE}_labels_request_v2_terminal_ready.json")
    assert request["status"] == "ready_root_cpu_labels_after_review"
    assert request["runnable"] is True
    assert request["launch_allowed"] is False
    assert request["root_only"] is True
    assert request["cpu_threads"] == 4
    assert request["input_sha256"][request["source_bindings"]["trajectory_h5"]["path"]] == "7b5ec1deac349608edbc0319c7c2c2fda572b10c3d6eb2abef32f9d589ad8669"
    command = " ".join(request["command"])
    assert "--exclusion-csv" in command
    assert "f2_rv4eq_center_terminal_product_v1.py" in command
    assert request["native_exclusion_semantics"]["motive_is_not_spill"] is True
    assert request["qualification_claim"].startswith("none")
    assert request["production_claim"] == "none"
