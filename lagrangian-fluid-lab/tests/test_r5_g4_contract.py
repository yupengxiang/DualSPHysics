"""CPU-only tests for the R5 G4 contract helpers.

These tests intentionally do not import the R4 trainer, PyTorch, NumPy, HDF5,
or any GPU runtime.  They exercise the gates that a future trainer must call
before a model is built and before an artifact is accepted.
"""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "experiments/r5_g4_contract.py"


def load_contract():
    spec = importlib.util.spec_from_file_location("r5_g4_contract", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def hashes(module):
    return {
        "trainer_sha256": "1" * 64,
        "config_sha256": "2" * 64,
        "data_sha256": "3" * 64,
    }


def component(component_id, kind, distance):
    return {
        "component_id": component_id,
        "type": kind,
        "features": {
            "presence": 1.0,
            "distance": distance,
            "normal_x": 1.0,
            "normal_y": 0.0,
            "normal_z": 0.0,
            "type": float(kind),
            "wall_velocity_x": 0.0,
            "wall_velocity_y": 0.0,
            "wall_velocity_z": 0.0,
        },
    }


def test_contract_snapshot_is_self_hashing_and_route_widths_are_explicit():
    module = load_contract()
    snapshot = module.contract_snapshot()

    assert module.validate_contract_snapshot(snapshot)["valid"] is True
    assert module.route_width("particle_mlp") == 115
    assert module.route_width("deepset_context") == 115
    assert module.route_width("physics_residual") == 115
    assert module.route_width("local_interaction") == 123
    assert snapshot["feature_layout"]["routes"]["local_interaction"]["model_input_width"] == 123
    assert snapshot["historical_feature_widths_rejected"] == [43, 51]


def test_feature_layout_and_route_target_semantics_are_frozen():
    module = load_contract()
    layout = module.feature_layout("local_interaction")
    ranges = {field["name"]: (field["start"], field["end"]) for field in layout["base"]}

    assert ranges["centered_xyz"] == (0, 3)
    assert ranges["current_boundary_summary"] == (28, 35)
    assert ranges["dt"] == (42, 43)
    assert layout["boundary_component_block"]["slot_count"] == 8
    assert layout["boundary_component_block"]["slot_width"] == 9
    assert layout["route_width"]["local_extension"]["start"] == 115
    assert layout["route_width"]["local_extension"]["end"] == 123

    for route in ("particle_mlp", "deepset_context", "local_interaction"):
        target = module.target_semantics(route)
        assert target["id"] == "direct_next_velocity_scaled_v1"
        assert target["formula"] == "y_t = v_(t+1) * dt / dp"
    physics_target = module.target_semantics("physics_residual")
    assert physics_target["id"] == "acceleration_residual_dt2_over_dp_v1"
    assert "dt^2 / dp" in physics_target["formula"]

    assert module.ROLLOUT_STATE["future_reference_is_model_input"] is False
    assert module.ROLLOUT_STATE["integrator_id"] == "trapezoid_predicted_velocity_v1"


def test_component_set_encoding_is_invariant_to_sidecar_row_order():
    module = load_contract()
    first = component(7, 1, 0.2)
    second = component(3, 0, 0.4)

    left = module.pack_boundary_component_set([first, second])
    right = module.pack_boundary_component_set([second, first])

    assert left["keys"] == [[0, 3], [1, 7]]
    assert left["keys"] == right["keys"]
    assert left["flat_features"] == right["flat_features"]
    assert left["missing_masks"] == right["missing_masks"]
    assert module.canonical_component_slots([first, second]) == (
        (0, 3),
        (1, 7),
        None,
        None,
        None,
        None,
        None,
        None,
    )
    assert module.validate_packed_boundary_component_set(left)["valid"] is True


def test_component_reordering_in_packed_payload_is_rejected():
    module = load_contract()
    packed = module.pack_boundary_component_set([component(7, 1, 0.2), component(3, 0, 0.4)])
    tampered = copy.deepcopy(packed)
    tampered["slots"][0]["key"], tampered["slots"][1]["key"] = (
        tampered["slots"][1]["key"],
        tampered["slots"][0]["key"],
    )
    tampered["keys"] = [tampered["slots"][0]["key"], tampered["slots"][1]["key"]]

    report = module.validate_packed_boundary_component_set(tampered)
    assert report["valid"] is False
    assert "boundary_component_order_not_canonical" in {error["code"] for error in report["errors"]}


def test_missing_masks_are_explicit_and_absent_slots_are_zero_filled():
    module = load_contract()
    packed = module.pack_boundary_component_set([component(7, 1, 0.2)])

    assert packed["missing_masks"]["boundary_component_presence"] == [1, 0, 0, 0, 0, 0, 0, 0]
    assert packed["slots"][1]["features"] == [0.0] * module.BOUNDARY_COMPONENT_WIDTH
    assert module.validate_packed_boundary_component_set(packed)["valid"] is True

    packed["missing_masks"]["boundary_component_presence"][1] = 1
    report = module.validate_packed_boundary_component_set(packed)
    assert report["valid"] is False
    assert "boundary_presence_mask_mismatch" in {error["code"] for error in report["errors"]}


def test_good_result_and_inference_only_checkpoint_bind_all_hashes():
    module = load_contract()
    common = hashes(module)
    result = module.build_result_metadata("particle_mlp", 17, **common)
    checkpoint = module.build_checkpoint_metadata("particle_mlp", 17, **common)
    checkpoint["state_dict"] = {"net.0.weight": "cpu-only-test-placeholder"}

    assert module.validate_result_metadata(result)["valid"] is True
    assert module.validate_checkpoint_payload(checkpoint)["valid"] is True
    pair = module.validate_result_checkpoint_pair(result, checkpoint)
    assert pair["valid"] is True
    assert result["input_contract_hash"] == result["contract_hash"]
    assert checkpoint["resume_capable"] is False


def test_result_hash_or_contract_tampering_is_rejected():
    module = load_contract()
    result = module.build_result_metadata("particle_mlp", 17, **hashes(module))

    result["data_sha256"] = "not-a-sha256"
    report = module.validate_result_metadata(result)
    assert report["valid"] is False
    assert "missing_or_invalid_sha256" in {error["code"] for error in report["errors"]}

    result = module.build_result_metadata("particle_mlp", 17, **hashes(module))
    result["input_contract_hash"] = "f" * 64
    report = module.validate_result_metadata(result)
    assert report["valid"] is False
    assert "contract_field_mismatch" in {error["code"] for error in report["errors"]}


def test_historical_43_wide_checkpoint_cannot_be_mixed_with_current_contract():
    module = load_contract()
    legacy = module.build_result_metadata("particle_mlp", 17, feature_width=43, **hashes(module))
    legacy["first_linear_input_width"] = 43
    report = module.validate_result_metadata(legacy)
    codes = {error["code"] for error in report["errors"]}

    assert report["valid"] is False
    assert "historical_feature_width_rejected" in codes
    assert "historical_checkpoint_input_width_rejected" in codes

    local = module.build_result_metadata("local_interaction", 17, **hashes(module))
    local["first_linear_input_width"] = 43
    report = module.validate_result_metadata(local)
    assert report["valid"] is False
    assert "historical_checkpoint_input_width_rejected" in {error["code"] for error in report["errors"]}


def test_current_result_plus_historical_checkpoint_is_rejected_as_a_pair():
    module = load_contract()
    current_result = module.build_result_metadata("local_interaction", 17, **hashes(module))
    historical_checkpoint = module.build_checkpoint_metadata("local_interaction", 17, **hashes(module))
    historical_checkpoint["feature_width"] = 43
    historical_checkpoint["model_input_width"] = 43
    historical_checkpoint["first_linear_input_width"] = 43
    historical_checkpoint["state_dict"] = {}

    report = module.validate_result_checkpoint_pair(current_result, historical_checkpoint)
    codes = {error["code"] for error in report["errors"]}

    assert report["valid"] is False
    assert "historical_feature_width_rejected" in codes
    assert "historical_checkpoint_input_width_rejected" in codes
    assert "result_checkpoint_binding_mismatch" in codes


def test_local_route_requires_123_model_width_while_sharing_115_base_block():
    module = load_contract()
    local = module.build_result_metadata("local_interaction", 17, feature_width=115, **hashes(module))
    report = module.validate_result_metadata(local)

    assert report["valid"] is False
    assert report["expected_feature_width"] == 123
    assert "feature_width_mismatch" in {error["code"] for error in report["errors"]}


def test_resume_checkpoint_requires_complete_training_state():
    module = load_contract()
    common = hashes(module)
    checkpoint = module.build_checkpoint_metadata(
        "physics_residual", 29, checkpoint_mode="resume_training", **common
    )
    checkpoint["state_dict"] = {}
    checkpoint.update({
        "optimizer_state_dict": {},
        "scheduler_state_dict": {},
        "rng_state": {"python": "present", "numpy": "present", "torch": "present", "cuda": "present"},
        "epoch": 4,
        "best_metric": 0.125,
    })
    assert module.validate_checkpoint_payload(checkpoint)["valid"] is True

    del checkpoint["scheduler_state_dict"]
    report = module.validate_checkpoint_payload(checkpoint)
    assert report["valid"] is False
    assert "missing_resume_state" in {error["code"] for error in report["errors"]}


def test_inference_only_checkpoint_must_be_explicit_and_not_resumable():
    module = load_contract()
    checkpoint = module.build_checkpoint_metadata("particle_mlp", 17, **hashes(module))
    checkpoint["state_dict"] = {}
    checkpoint["resume_capable"] = True
    checkpoint["optimizer_state_dict"] = {}
    report = module.validate_checkpoint_payload(checkpoint)
    codes = {error["code"] for error in report["errors"]}

    assert report["valid"] is False
    assert "inference_only_not_explicit" in codes
    assert "inference_only_contains_training_state" in codes


def test_cuda_determinism_policy_is_recorded_without_invoking_cuda():
    module = load_contract()
    cpu = module.make_cuda_determinism_policy("cpu", seed=17)
    cuda = module.make_cuda_determinism_policy("cuda:4", seed=17, strict=True)

    assert module.validate_cuda_determinism_policy(cpu, device="cpu")["valid"] is True
    assert module.validate_cuda_determinism_policy(cuda, device="cuda:4")["valid"] is True
    cuda["cudnn_benchmark"] = True
    report = module.validate_cuda_determinism_policy(cuda, device="cuda:4")
    assert report["valid"] is False
    assert "strict_cuda_policy_benchmark" in {error["code"] for error in report["errors"]}


def test_pair_validation_detects_cross_run_provenance_mismatch():
    module = load_contract()
    result = module.build_result_metadata("particle_mlp", 17, **hashes(module))
    checkpoint = module.build_checkpoint_metadata(
        "particle_mlp", 17, trainer_sha256="9" * 64, config_sha256="2" * 64, data_sha256="3" * 64
    )
    checkpoint["state_dict"] = {}
    report = module.validate_result_checkpoint_pair(result, checkpoint)

    assert report["valid"] is False
    mismatch_fields = {
        error["field"]
        for error in report["errors"]
        if error["code"] == "result_checkpoint_binding_mismatch"
    }
    assert "trainer_sha256" in mismatch_fields


def test_static_snapshot_writer_and_repository_snapshot_are_machine_readable(tmp_path):
    module = load_contract()
    destination = module.write_contract_snapshot(tmp_path / "contract.json")
    payload = json.loads(destination.read_text())

    assert module.validate_contract_snapshot(payload)["valid"] is True
    assert payload["contract_hash"] == module.CONTRACT_HASH

    repository_snapshot = ROOT / "campaigns/v0.1-candidate/r5-g4-contract/input-contract.json"
    if repository_snapshot.is_file():
        assert module.validate_contract_snapshot(json.loads(repository_snapshot.read_text()))["valid"] is True


def test_strict_assertion_exposes_structured_errors():
    module = load_contract()
    bad = module.build_result_metadata("particle_mlp", 17, **hashes(module))
    bad["feature_width"] = 43

    with pytest.raises(module.ContractError) as raised:
        module.assert_valid_input_contract_metadata(bad)
    assert raised.value.errors
    assert any(error["code"] == "historical_feature_width_rejected" for error in raised.value.errors)
