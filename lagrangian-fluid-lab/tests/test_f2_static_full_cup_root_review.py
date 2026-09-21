from __future__ import annotations

import hashlib
import json
from pathlib import Path


LAB = Path(__file__).resolve().parents[1]
REVIEW = LAB / "campaigns/core-v1/cfd/f2-static-full-cup-root-review-v1.json"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_root_review_allows_only_future_cpu_prepare_decode() -> None:
    review = json.loads(REVIEW.read_text())
    assert review["status"] == "approved_for_cpu_only_prepare_decode_pending_execution"
    decision = review["root_review_decision"]
    assert decision["candidate_card_consistent"] is True
    assert decision["static_anchor_consistent"] is True
    assert decision["dependency_hashes_consistent"] is True
    assert decision["resource_contract_consistent"] is True
    assert decision["admission_contract_consistent"] is True
    assert decision["failure_denominator_contract_consistent"] is True
    assert decision["cpu_only_full_matrix_prepare_decode_allowed_subsequently"] is True
    assert decision["solver_allowed"] is False
    assert decision["gpu_allowed"] is False
    assert decision["matrix_job_creation_allowed"] is False
    assert decision["central_registry_mutation_allowed"] is False
    assert decision["central_ledger_mutation_allowed"] is False

    controls = review["execution_controls"]
    assert controls["read_only_review"] is True
    assert controls["gen_case_run_now"] is False
    assert controls["decoder_run_now"] is False
    assert controls["solver_run_now"] is False
    assert controls["gpu_launch_now"] is False
    assert controls["matrix_inputs_materialized_now"] is False
    assert controls["matrix_jobs_materialized_now"] is False
    assert controls["queue_mutation_now"] == 0
    assert controls["ledger_mutation_now"] == 0
    assert controls["registry_mutation_now"] == 0


def test_root_review_closes_15_cells_resources_and_failure_denominator() -> None:
    review = json.loads(REVIEW.read_text())
    card = json.loads(
        (LAB / review["candidate_card"]["path"]).read_text()
    )
    design = review["registered_15_cell_design"]
    assert design["cell_count"] == 15
    assert design["spatial_cell_count"] == 13
    assert design["temporal_cell_count"] == 2
    assert design["qualification_q"] == [0.0, 0.5, 1.0]
    assert design["held_out_q"] == [0.25, 0.75]
    assert design["resolutions_m"] == [0.01, 0.0075, 0.005]
    assert design["matrix_inputs_materialized"] is False
    assert design["matrix_jobs_materialized"] is False
    assert design["cell_statuses"] == ["design_only_unprepared"]
    assert design["anchor_excluded_from_numerator"] is True
    card_design = card["qualification_design"]
    assert design["cell_count"] == card_design["cell_count"]
    assert design["spatial_cell_count"] == sum(
        row["design_cell"].startswith("spatial") for row in card_design["cells"]
    )
    assert design["temporal_cell_count"] == sum(
        not row["design_cell"].startswith("spatial") for row in card_design["cells"]
    )
    assert design["registered_window_s"] == card_design["registered_window_s"]
    assert design["output_interval_s"] == card_design["output_interval_s"]
    assert design["static_settle_hold_s"] == card_design["settle_hold_s"]
    assert design["matrix_inputs_materialized"] == card_design["matrix_inputs_materialized"]
    assert design["matrix_jobs_materialized"] == card_design["matrix_jobs_materialized"]

    resources = review["resource_contract"]["per_cell"]
    assert resources == {
        "dp_0.010": {"cpu_cores": 2, "ram_mib": 12288, "gpu_peak_mib_recorded": 3072, "timeout_seconds": 1800},
        "dp_0.0075": {"cpu_cores": 2, "ram_mib": 16384, "gpu_peak_mib_recorded": 4096, "timeout_seconds": 1800},
        "dp_0.005": {"cpu_cores": 2, "ram_mib": 24576, "gpu_peak_mib_recorded": 8192, "timeout_seconds": 3600},
    }
    assert review["resource_contract"]["gpu_fields_are_estimates_only"] is True
    assert review["resource_contract"]["cpu_only_phase_may_use_recorded_cpu_and_ram_bounds"] is True
    for dp_key, source_key in (
        ("dp_0.010", "dp_0.010"),
        ("dp_0.0075", "dp_0.0075"),
        ("dp_0.005", "dp_0.005"),
    ):
        source = card["resource_estimate"]["per_cell"][source_key]
        assert resources[dp_key] == {
            "cpu_cores": source["cpu_cores"],
            "ram_mib": source["ram_mib"],
            "gpu_peak_mib_recorded": source["gpu_peak_mib"],
            "timeout_seconds": source["timeout_seconds"],
        }

    gates = review["qualification_gate_contract"]
    assert gates["source"] == "candidate_card.gates"
    assert {key: gates[key] for key in card["gates"]} == card["gates"]
    assert card["input_closure"]["frozen_source_snapshot_required"] is True
    assert card["input_closure"]["future_matrix_rule"].startswith(
        "no matrix case may reuse the anchor trajectory"
    )

    denominator = review["failure_denominator_contract"]
    assert denominator["fixed_registered_cell_denominator"] == 15
    assert denominator["all_15_cells_remain_in_denominator"] is True
    assert denominator["held_out_rows_remain_registered"] is True
    assert denominator["temporal_rows_remain_registered"] is True
    assert denominator["unprepared_rows_are_not_successes"] is True
    assert denominator["missing_or_failed_rows_are_not_dropped"] is True
    assert denominator["failed_rows_are_not_replaced"] is True
    assert denominator["anchor_canary_is_excluded_from_numerator"] is True
    assert denominator["survivor_renormalization"] is False
    assert denominator["any_cell_failure_blocks_f2_t1_registration"] is True


def test_root_review_hashes_anchor_dependencies_and_preserves_central_state() -> None:
    review = json.loads(REVIEW.read_text())
    for ref in review["dependency_closure"]:
        path = LAB / ref["path"]
        assert path.is_file(), ref["path"]
        assert path.stat().st_size == ref["bytes"], ref["path"]
        assert _digest(path) == ref["sha256"], ref["path"]

    anchor = review["static_anchor_review"]
    integration = json.loads(
        (LAB / anchor["integration"]["path"]).read_text()
    )
    prepared = json.loads(
        (LAB / anchor["prepared"]["path"]).read_text()
    )
    native_preflight = json.loads(
        (LAB / anchor["native_preflight"]["path"]).read_text()
    )
    assert anchor["integration"]["hard_integrity_pass"] is True
    assert anchor["integration"]["event_window_complete"] is True
    assert anchor["integration"]["static_settled"] is True
    assert anchor["prepared"]["preflight_pass"] is True
    assert anchor["native_preflight"]["preflight_pass"] is True
    assert anchor["native_preflight"]["mass_rescaling"] is False
    assert anchor["native_preflight"]["native_ids_unique_finite"] is True
    assert integration["hard_integrity_pass"] is True
    assert integration["event_window_complete"] is True
    assert integration["static_settled"] is True
    assert prepared["preflight_pass"] is True
    assert native_preflight["preflight_pass"] is True
    assert native_preflight["mass_preflight"]["mass_rescaling"] is False
    assert native_preflight["checks"]["native_ids_unique_finite"] is True

    state = review["central_state_observation"]
    registry = LAB / state["registry_path"]
    assert registry.stat().st_size == state["registry_bytes"]
    assert _digest(registry) == state["registry_sha256"]
    assert state["registered_scope_families"] == ["F3", "F4"]
    assert state["f2_scope_present_at_review"] is False
    assert state["mutation_by_this_review"] == 0
