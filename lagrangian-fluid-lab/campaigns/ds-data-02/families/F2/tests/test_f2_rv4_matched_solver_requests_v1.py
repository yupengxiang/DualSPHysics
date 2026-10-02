"""Tests for root-only matched RV4 solver request registration."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


REQUEST_ROOT = Path(__file__).resolve().parents[1] / "handoff_20261003/rv4_matched_three_dp_init_v1/solver_requests_v1"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_four_requests_bind_terminal_3d_gencase_and_keep_root_authority():
    requests = sorted(REQUEST_ROOT.glob("*_request.json"))
    assert len(requests) == 4
    seen = set()
    for path in requests:
        request = json.loads(path.read_text(encoding="utf-8"))
        assert request["kind"] == "qualification"
        assert request["root_only"] is True
        assert request["gpu_launch"]["family_owner_launch"] is False
        assert request["gencase_receipt"]
        assert request["gencase_receipt_sha256"] == sha256(Path(request["gencase_receipt"]))
        receipt = json.loads(Path(request["gencase_receipt"]).read_text(encoding="utf-8"))
        assert receipt["status"] == "completed"
        assert receipt["returncode"] == 0
        assert receipt["solver_dimension_from_gencase"] == 3
        assert receipt["total_particles"] > receipt["fluid_particles"] > 0
        assert Path(request["gencase_prefix"] + ".xml").is_file()
        assert Path(request["gencase_prefix"] + ".bi4").is_file()
        assert Path(request["gencase_prefix"] + "_motion.dat").is_file()
        assert request["gencase_artifacts"]["actual_total_particles"] == receipt["total_particles"]
        assert request["gencase_artifacts"]["actual_fluid_particles"] == receipt["fluid_particles"]
        assert request["numerical_recipe_fields"]["frame_count_expected"] == 4001
        assert request["event_window_s"] == 4.0
        assert request["save_strategy_review"]["registered_recipe_event_qualification"] == "deferred"
        assert request["save_strategy_review"]["registered_half_bracket_s"] == 0.0005
        assert request["save_strategy_review"]["per_save_allocation_s"] < 0.0005
        assert request["q_n_status"] == "not_assessed"
        seen.add(request["physical_case_id"])
    assert seen == {"F2H10V2_CENTER_V1", "F2H10V2_OFFSET_V1"}


def test_save_budget_review_does_not_relax_frozen_event_gate():
    budget = json.loads((REQUEST_ROOT / "save-budget-review-v1.json").read_text(encoding="utf-8"))
    assert budget["event_time_absolute_budget_s"] == 0.0036681953999691376
    assert budget["save_integration_total_budget_s"] == 0.0007336390799938275
    assert budget["save_per_study_allocation_s"] == 0.0001467278159987655
    assert budget["registered_spatial_save_interval_s"] == 0.001
    assert budget["registered_spatial_half_bracket_s"] == 0.0005
    assert budget["registered_spatial_recipe_event_status"] == "deferred"
    assert budget["deferred_event_save_interval_s"] == 0.00025
    assert budget["q_n_status"] == "not_assessed"
