from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import f4_supportcap_r002_static_design_v1 as design


def test_alignment_contract_requires_full_forward_advection_window():
    contract = {
        "initial_native_frame": 0,
        "last_native_frame_inclusive": 41,
        "target_transition": [40, 41],
        "expected_saved_rows": 42,
        "advect_initial_seeds_before_target_transition": True,
        "query_original_t0_seed_positions_at_row40": False,
    }
    design.validate_alignment_contract(contract)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("initial_native_frame", 40),
        ("last_native_frame_inclusive", 40),
        ("target_transition", [39, 40]),
        ("expected_saved_rows", 2),
        ("advect_initial_seeds_before_target_transition", False),
        ("query_original_t0_seed_positions_at_row40", True),
    ],
)
def test_alignment_contract_rejects_r001_or_truncated_window(key, value):
    contract = {
        "initial_native_frame": 0,
        "last_native_frame_inclusive": 41,
        "target_transition": [40, 41],
        "expected_saved_rows": 42,
        "advect_initial_seeds_before_target_transition": True,
        "query_original_t0_seed_positions_at_row40": False,
    }
    contract[key] = value
    with pytest.raises(ValueError, match="temporal-alignment"):
        design.validate_alignment_contract(contract)


def test_recipe_keeps_r001_immutable_and_builds_fresh_unrun_r002():
    recipe = design.build_recipe()
    assert recipe["historical_attempt"] == {
        "attempt_id": design.R001_ID,
        "status": "failed_one_attempt_zero_credit",
        "modified": False,
        "retried": False,
        "trace_sha256": recipe["historical_attempt"]["trace_sha256"],
        "failure_classification": "t0_geometric_seeds_compared_to_later_native_frame_support",
    }
    prospective = recipe["prospective_attempt"]
    assert prospective["attempt_id"] == design.R002_ID
    assert prospective["not_created"] is True
    assert prospective["command_not_run"][0:3] == [
        ".venv/bin/python", "-m", "scripts.f4_tallwall120_material"
    ]
    assert prospective["command_not_run"][-2:] == ["--stop-after", "41"]
    assert prospective["alignment"]["target_transition"] == [40, 41]


def test_recipe_preserves_denominator_gates_and_zero_credit():
    recipe = design.build_recipe()
    prospective = recipe["prospective_attempt"]
    assert prospective["denominator"] == 512
    assert prospective["all_gates_and_event_censoring_unchanged"] is True
    assert prospective["failure_denominator_retained"] is True
    assert prospective["fixed_gate"] == {
        "minimum_effective_sample_size": 4.0,
        "minimum_geometry_rank": 3,
        "minimum_anisotropy": 0.005,
        "maximum_reconstruction_error_mps": design.candidate.FIXED_GATE[
            "maximum_reconstruction_error_mps"
        ],
        "unknown_fraction_limit": 0.01,
    }
    assert prospective["maximum_support_distance_m"] == 0.03
    assert recipe["execution_authority"]["qualification_credit"] == 0
    assert recipe["execution_authority"]["T1_numerical"] is False
    assert recipe["execution_authority"]["T2_macro"] is False


def test_short_prefix_cannot_be_mistaken_for_event_qualification():
    recipe = design.build_recipe()
    attempt = recipe["prospective_attempt"]
    event = attempt["event_observation_scope"]
    registered = recipe["unchanged_registered_f4_physics_and_events"]["event_definition"]
    assert event["purpose"] == "temporal-alignment prefix diagnostic only"
    assert event["end_time_s"] < event["initial_event_horizon_s"]
    assert event["initial_event_horizon_s"] == 4.34
    assert event["maximum_extended_event_horizon_s"] == 8.68
    assert event["event_horizon_complete"] is False
    assert event["unobserved_event_policy"] == registered["unobserved_event_policy"]
    assert event["residence_right_censored_if_unresolved"] is True
    assert event["event_qualification_claim"] == "none; this prefix cannot qualify contact, propagation, return, or residence"


def test_recipe_pins_original_physical_source_destination_and_event_definitions():
    recipe = design.build_recipe()
    physical = recipe["unchanged_registered_f4_physics_and_events"]
    assert physical["source_definition"]["kind"] == "continuous_drop_box"
    assert physical["destination_definition"]["kind"] == "continuous_resting_pool_box"
    assert physical["event_definition"]["contact"]["direction"] == "downward"
    assert physical["event_definition"]["unobserved_event_policy"] == "NaN/right-censored; no saved-chord imputation"


def test_recipe_has_no_runtime_authority_and_does_not_open_native_source():
    recipe = design.build_recipe()
    authority = recipe["execution_authority"]
    assert authority["native_preflight_authorized"] is False
    assert authority["cpu_canary_authorized"] is False
    assert authority["solver_authorized"] is False
    assert authority["gpu_authorized"] is False
    assert authority["new_explicit_runtime_authorization_required"] is True
    assert recipe["source_identity"]["opened_or_rehashed_by_this_design"] is False
    assert recipe["execution_controls"]["native_hdf5_opened"] is False
    assert recipe["execution_controls"]["trace_runner_started"] is False


def test_recipe_binds_the_prior_attribution_and_candidate_implementation():
    recipe = design.build_recipe()
    paths = {item["path"] for item in recipe["bindings"]}
    assert str(design.ATTRIBUTION) in paths
    assert str(design.CANDIDATE_DIR / "candidate-card-v3.json") in paths
    assert "scripts/f4_supportcap_affine_query_bound_candidate_v3.py" in paths
    assert "scripts/f4_tallwall120_material.py" in paths
    assert "scripts/f4_supportcap_affine_query_bound_cpu_canary_execute_v1.py" in paths


def test_recipe_is_proposal_only_and_has_separate_output_namespace():
    recipe = design.build_recipe()
    assert recipe["status"] == "static_temporal_alignment_design_candidate_for_independent_review"
    assert recipe["prospective_attempt"]["fresh_output_namespace"].endswith(
        f"{design.R002_ID}/trace.h5"
    )
    assert recipe["prospective_attempt"]["fresh_output_namespace"] != str(
        design.R001_DIR / "trace.h5"
    )
    assert recipe["execution_controls"]["historical_r001_modified"] is False


def test_writer_refuses_to_overwrite_receipt(tmp_path, monkeypatch):
    receipt = tmp_path / "recipe.json"
    receipt.write_text("existing", encoding="utf-8")
    monkeypatch.setattr(design, "LAB", tmp_path)
    monkeypatch.setattr(design, "RECEIPT", Path("recipe.json"))
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        design.write_recipe()


def test_output_namespace_guard_rejects_directory_file_and_dangling_symlink(tmp_path):
    existing_dir = tmp_path / "existing-dir"
    existing_dir.mkdir()
    with pytest.raises(FileExistsError, match="fresh r002 output namespace"):
        design.require_absent_output_namespace(tmp_path, Path("existing-dir"))

    existing_file = tmp_path / "existing-file"
    existing_file.write_text("occupied", encoding="utf-8")
    with pytest.raises(FileExistsError, match="fresh r002 output namespace"):
        design.require_absent_output_namespace(tmp_path, Path("existing-file"))

    dangling_link = tmp_path / "dangling-link"
    dangling_link.symlink_to(tmp_path / "missing-target", target_is_directory=True)
    assert not dangling_link.exists()
    assert dangling_link.is_symlink()
    with pytest.raises(FileExistsError, match="fresh r002 output namespace"):
        design.require_absent_output_namespace(tmp_path, Path("dangling-link"))


def test_written_recipe_matches_current_sources_and_parent_hashes():
    path = design.LAB / design.RECEIPT
    receipt = json.loads(path.read_text(encoding="utf-8"))
    assert receipt == design.build_recipe()
    for binding in receipt["bindings"]:
        source = design.LAB / binding["path"]
        assert source.stat().st_size == binding["bytes"]
        assert hashlib.sha256(source.read_bytes()).hexdigest() == binding["sha256"]
