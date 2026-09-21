from __future__ import annotations

import hashlib
import json
from pathlib import Path


LAB = Path(__file__).resolve().parents[1]
HANDOFF = LAB / "campaigns/core-v1/cfd/f2-third-family-next-step-candidate-v1.json"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_f2_next_step_handoff_is_hash_bound_and_unexecuted() -> None:
    handoff = json.loads(HANDOFF.read_text())

    assert handoff["status"] == "candidate_handoff_root_review_only"
    assert handoff["qualification_claim"].startswith("none;")
    assert handoff["core_gate"]["current_registered_t1_families"] == ["F3", "F4"]
    assert handoff["core_gate"]["candidate_family"] == "F2"
    controls = handoff["execution_controls"]
    assert controls["read_only_audit"] is True
    assert controls["gen_case_run_by_this_handoff"] is False
    assert controls["decoder_run_by_this_handoff"] is False
    assert controls["solver_run_by_this_handoff"] is False
    assert controls["gpu_launched_by_this_handoff"] is False
    assert controls["central_queue_mutation"] == 0
    assert controls["central_ledger_mutation"] == 0
    assert controls["central_registry_mutation"] == 0
    assert controls["matrix_materialized"] is False
    assert controls["matrix_submitted"] is False

    dynamic = handoff["dynamic_f2_audit"]
    assert dynamic["five_second_terminal"]["hard_integrity_pass"] is True
    assert dynamic["five_second_terminal"]["event_window_complete"] is False
    assert dynamic["five_second_terminal"]["qualified"] is False
    assert dynamic["ten_second_extension"]["preflight"]["preflight_pass"] is True
    assert dynamic["ten_second_extension"]["preflight"]["solver_product_present"] is False
    assert dynamic["ten_second_extension"]["audit"]["hard_integrity_pass"] is True
    assert dynamic["ten_second_extension"]["audit"]["event_window_complete"] is False
    assert dynamic["ten_second_extension"]["audit"]["qualified"] is False

    candidate = handoff["candidate"]
    assert candidate["status"] == "design_only_anchor_canary_supported"
    assert candidate["qualification_only"] is True
    assert candidate["qualified"] is False
    design = candidate["registered_design"]
    assert design["cell_count"] == 15
    assert design["matrix_materialized"] is False
    assert design["prepared_count"] == 0
    assert design["job_count"] == 0
    assert design["all_cell_statuses"] == ["design_only_unprepared"]
    assert candidate["launch_policy"] == {
        "gpu_submit": False,
        "ledger_submit": False,
        "root_review_required": True,
        "candidate_canary_relaunch": False,
        "qualification_claim_allowed_now": False,
    }

    for ref in [candidate["card"], *handoff["dependency_closure"]]:
        path = LAB / ref["path"]
        assert path.is_file(), ref["path"]
        assert path.stat().st_size == ref["bytes"], ref["path"]
        assert _digest(path) == ref["sha256"], ref["path"]


def test_f2_next_step_handoff_preserves_dynamic_hold_and_static_scope_boundary() -> None:
    handoff = json.loads(HANDOFF.read_text())
    lock = json.loads(
        (LAB / handoff["dynamic_f2_audit"]["ten_second_extension"]["scientific_lock"]["path"]).read_text()
    )
    assert lock["scientific_conclusion"]["status"] == "negative_dynamic_canary_incomplete_event_window"
    assert lock["scientific_conclusion"]["qualified"] is False
    assert lock["scientific_conclusion"]["next_action"].startswith("hold;")

    card = json.loads((LAB / handoff["candidate"]["card"]["path"]).read_text())
    assert card["scope_id"] == "F2_static_full_cup_volume_hold_x_v1"
    assert card["qualification_design"]["cell_count"] == 15
    assert card["qualification_design"]["matrix_inputs_materialized"] is False
    assert card["qualification_design"]["matrix_jobs_materialized"] is False
    assert card["decision_rule"].startswith("The anchor pass supports preparation of this distinct static scene only.")
    assert card["launch_policy"]["gpu_submit"] is False
    assert card["launch_policy"]["ledger_submit"] is False
    assert card["launch_policy"]["qualification_claim_allowed_now"] is False

