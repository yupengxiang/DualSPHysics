from __future__ import annotations

import json
from pathlib import Path

from scripts.f2_submerged_orifice_normal_remediation_v4 import (
    CASE_ID,
    DEFAULT_CANDIDATE,
    DEFAULT_CONTRACT,
    DEFAULT_DEFINITION,
    DEFAULT_EVIDENCE,
    DEFAULT_OUTPUT_PREFIX,
    MASS_RELATIVE_ERROR_MAX,
    SOURCE_COUNTS,
    SOURCE_RELATIVE_ERROR,
    ZERO_NORMAL_TOLERANCE_M,
    inspect_definition,
    load_json,
    verify_contract,
)


def test_v4_definition_is_new_signed_layer_and_count_closed_recipe():
    definition = inspect_definition(DEFAULT_DEFINITION)
    assert definition["case_id"] == CASE_ID
    assert definition["normal_geometry"]["outer_layers_vdp"] == "0,-1,-2"
    assert definition["normal_geometry"]["gate_layers_vdp"] == "0,1,2"
    assert definition["source_lattice"]["expected_counts_xyz"] == list(SOURCE_COUNTS)
    assert definition["source_lattice"]["expected_particles"] == 231168
    assert definition["source_lattice"]["predicted_relative_error"] == SOURCE_RELATIVE_ERROR
    assert definition["runtime_invoked"] is False


def test_v4_failure_evidence_is_read_only_and_exact():
    evidence = load_json(DEFAULT_EVIDENCE)
    assert evidence["status"] == "read_only_v3_failure_evidence_closed"
    assert evidence["observed_failure"]["zero_boundnor_count"] == 83443
    assert evidence["observed_failure"]["zero_normal_size_count"] == 83443
    assert evidence["observed_failure"]["mk17_outer_zero_count"] == 64899
    assert evidence["observed_failure"]["mk18_gate_zero_count"] == 18544
    assert evidence["observed_failure"]["mass_relative_error"] == -0.04207502092633919
    assert evidence["geometry_observation"]["hdp_actual_shapes_by_mk"] == {"17": 15, "18": 18}
    assert evidence["source_count_observation"]["observed_fluid_count_factorization"] == [85, 55, 47]
    controls = evidence["execution_controls"]
    assert controls["gencase_invoked"] is False
    assert controls["native_decoder_invoked"] is False
    assert controls["solver_invoked"] is False
    assert controls["gpu_invoked"] is False
    assert controls["job_created"] is False
    assert controls["matrix_submission"] is False
    assert controls["qualification_numerator_credit"] == 0


def test_v4_candidate_and_contract_keep_all_hard_gates_and_runtime_closed():
    candidate = load_json(DEFAULT_CANDIDATE)
    contract = verify_contract(DEFAULT_CONTRACT, test_path=Path(__file__).resolve())
    assert candidate["candidate_status"] == "root_review_only_static_candidate_not_run"
    assert candidate["one_hypothesis"]["falsifier"]
    assert candidate["hard_preflight_gates"]["zero_boundnor_count_max"] == 0
    assert candidate["hard_preflight_gates"]["zero_normal_size_count_max"] == 0
    assert candidate["hard_preflight_gates"]["native_mass_relative_error_max"] == MASS_RELATIVE_ERROR_MAX
    assert candidate["matrix_credit"] == 0
    assert contract["authorized_now"] is False
    assert contract["proposal_only"] is True
    assert contract["authorization"]["cpu_gencase"] is False
    assert contract["authorization"]["native_decode"] is False
    assert all(contract["authorization"][key] is False for key in (
        "solver_launch", "gpu_launch", "job_spec_creation", "matrix_submission"
    ))
    assert contract["authorization"]["queue_mutation"] == 0
    assert contract["authorization"]["ledger_mutation"] == 0
    assert contract["authorization"]["registry_mutation"] == 0
    assert contract["failure_denominator"]["qualification_numerator"] == 0
    assert contract["fresh_input"]["generated_products_present"] is False
    assert contract["fresh_input"]["native_input_present"] is False
    # The static proposal remains runtime-closed even though its separately
    # authorized one-shot preflight has now materialized immutable evidence.
    assert DEFAULT_OUTPUT_PREFIX.parent.is_dir()
    assert (DEFAULT_OUTPUT_PREFIX.parent / "preflight.json").is_file()
    assert ".bi4" not in json.dumps(contract, sort_keys=True).lower()


def test_v4_candidate_does_not_reuse_failed_inputs():
    candidate = load_json(DEFAULT_CANDIDATE)
    identity = candidate["new_input_identity"]
    assert identity["new_case_id"] == CASE_ID
    assert identity["old_anchor_definition_reused"] is False
    assert identity["old_anchor_native_input_reused"] is False
    assert identity["v3_failed_definition_reused"] is False
    assert identity["v3_failed_native_input_reused"] is False
    assert identity["old_trajectory_reused"] is False
    assert candidate["source_lattice_closure"]["runtime_count_observed"] is False
    assert candidate["hard_preflight_gates"]["zero_normal_norm_threshold_m"] == ZERO_NORMAL_TOLERANCE_M
