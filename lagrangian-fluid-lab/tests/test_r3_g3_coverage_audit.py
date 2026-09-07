from scripts.r3_g3_coverage_audit import (
    FAMILIES,
    build_report,
    pilot_task_audit,
    w08_topology_audit,
)


def test_registry_stage_audit_distinguishes_quality_from_execution():
    report = build_report()
    counts = report["registry_stage_counts"]
    assert counts["declared"] == 30
    assert counts["executable"] == 30
    assert counts["run"] == 30
    assert counts["trajectory_structural"] == 30
    assert counts["quality_gate_pass"] == 29
    assert counts["quality_gate_expected_failure_or_rejected"] == 1


def test_w08_cards_are_not_mistaken_for_executed_cases():
    report = build_report()
    w08 = report["w08_design"]
    assert w08["declared_cards"] == 204
    assert w08["unique_execution_units"] == 196
    assert w08["execution_status_counts"] == {"planned_not_run": 204}
    assert w08["executable_definitions"] == 0
    assert w08["run_cases"] == 0


def test_declared_topology_holdouts_have_no_w08_execution_link():
    topology = w08_topology_audit()
    assert set(topology) == set(FAMILIES)
    assert all(item["w08_controlled_cards"] == 0 for item in topology.values())
    assert all(not item["holdout_gate_pass"] for item in topology.values())
    assert topology["F1"]["incidental_matching_registry_cases"] == ["F1_twin_obstacle"]
    assert topology["F2"]["incidental_matching_registry_cases"] == []


def test_pilot_tasks_expose_candidate_material_but_no_complete_t2_t3_t4():
    pilot = pilot_task_audit()
    assert pilot["pilot_manifest_case_count"] == 13
    assert pilot["pilot_split_counts"] == {"train": 6, "validation": 3, "test": 4}
    assert len(pilot["task_ready_case_ids"]["T1_particle_rollout"]) == 13
    assert len(pilot["task_ready_case_ids"]["T2_material_transport"]) == 0
    assert len(pilot["task_ready_case_ids"]["T3_interaction_observables"]) == 0
    assert len(pilot["task_ready_case_ids"]["T4_outcome_classification"]) == 0
    assert pilot["learned_baseline"]["three_seed_gate"]
    assert pilot["learned_baseline"]["case_ids"] == [
        "F1_twin_obstacle", "F3_transverse_slosh", "W06_standard_fast_center"
    ]
