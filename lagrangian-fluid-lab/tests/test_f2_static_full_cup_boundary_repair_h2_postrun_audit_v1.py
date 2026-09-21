from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "campaigns/core-v1/cfd/f2-static-full-cup-boundary-repair-h2-runtime-postrun-audit-v1.json"


def test_h2_solver_canary_is_a_scientific_negative_with_complete_horizon() -> None:
    value = json.loads(ARTIFACT.read_text())
    scientific = value["scientific_status"]
    assert value["schema"] == "core.f2.static_full_cup.boundary_repair_h2.runtime_postrun_audit.v1"
    assert scientific["solver_execution"] == "completed_to_registered_horizon"
    assert scientific["solver_exit_code"] == 0
    assert scientific["requested_horizon_reached"] is True
    assert scientific["hard_integrity_pass"] is False
    assert scientific["T1_numerical"] is False
    assert scientific["wall_endpoint_violation_particle_frames"] == 168
    assert scientific["saved_chord_crossing_count"] == 21
    assert scientific["excluded_particle_count"] == 14
    assert value["fixed_failure_denominator"] == {
        "planned": 15,
        "executed": 1,
        "passed": 0,
        "failed": 1,
        "unattempted": 14,
        "survivor_renormalization": False,
        "same_input_retry": False,
    }
    assert all(value["checks"].values())


def test_wrapper_metadata_failure_is_separate_and_no_retry_is_allowed() -> None:
    value = json.loads(ARTIFACT.read_text())
    infrastructure = value["infrastructure_status"]
    assert infrastructure["coordinator_execution_status"] == "failed"
    assert infrastructure["worker_product_complete"] is True
    assert infrastructure["wrapper_postrun_failure"] is True
    assert infrastructure["failure_class"] == "postrun_metadata_rebind_missing_source_prepared_sha256"
    assert infrastructure["same_input_retry"] is False
    assert value["authorization_boundary"]["registry_mutation"] == 0
    assert value["authorization_boundary"]["qualification_credit"] == 0
