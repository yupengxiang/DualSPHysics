from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
REQS = sorted((ROOT / "requests").glob("*.full601-native-qualification-request.json"))
CASES = ["A035", "A040", "A050", "A055", "A060"]

def test_fresh068_disabled_resource_contract():
    assert len(REQS) == 5
    for suffix, path in zip(CASES, REQS):
        req = json.loads(path.read_text())
        assert suffix in req["case_id"]
        assert req["schema"] == "ds02.runner-request.v2"
        assert req["kind"] == "qualification"
        assert req["cpu_threads"] == 4
        assert req["estimated_peak_gpu_mib"] == 8192
        assert req["estimated_storage_bytes"] == 17179869184
        assert req["max_wall_seconds"] == 14400
        assert req["launch"] is False
        assert req["launch_allowed"] is False
        assert req["execution_allowed"] is False
        assert req["root_only"] is True
        assert req["launch_owner"] == "root"
        assert req["root_review_required"] is True
        assert req["root_solver_concurrency_cap"] == 8
        assert req["root_resource_contract"]["live_uuid_lease_required_at_enable"] is True
        assert req["root_resource_contract"]["live_uuid_lease_acquired_in_disabled_request"] is False
        assert req["root_resource_contract"]["foreign_process_protection"] is True
        assert req["root_resource_contract"]["parent_budget_reservation"] is True
        assert req["root_resource_contract"]["parent_budget_reservation_acquired_in_disabled_request"] is False
        assert req["root_resource_contract"]["campaign_resource_window"]["cpu_thread_cap"] == 64
        assert req["root_resource_contract"]["campaign_resource_window"]["home_free_floor_gib"] == 500
        assert req["root_resource_contract"]["campaign_resource_window"]["deadline_policy"] == "shared runtime ledger deadline; unchanged"
        assert req["time_contract"] == {
            "time_max_s": 12.0,
            "time_out_s": 0.02,
            "full_event_window_s": [0.0, 12.0],
            "expected_native_frames": 601,
            "motion_rows": 12001,
            "unchanged_from_mother_recipe": True,
        }
        assert req["command"][-2:] == ["-tmax:12", "-tout:0.02"]
        assert req["runtime_command_template"][1] == "-gpu:0"
        assert not set(req["command"]).intersection(req["forbidden_options"])
        assert req["root117_runtime_contract"]["status"] == "completed"
        assert req["root117_runtime_contract"]["returncode"] == 0
        assert req["root117_runtime_contract"]["actual_total_particles"] == 70179
        assert req["root117_runtime_contract"]["actual_fluid_particles"] == 40700
        assert req["root117_runtime_contract"]["actual_solver_dimension"] == 3
        assert req["root117_top_level_failure"]["status"] == "failed"
        assert req["root117_top_level_failure"]["used_as_success_evidence"] is False
        assert req["root117_top_level_failure_preserved"] is True
        assert req["initial_qa_evidence"]["execution_status"] == "completed"
        assert req["initial_qa_evidence"]["execution_returncode"] == 0
        assert req["initial_qa_evidence"]["report_all_cases_passed"] is True
        assert req["motion_source"]["required_filename"] == "motion_obstacle_quintic.dat"
        assert req["motion_source"]["required_in_solver_cwd"] is True
        assert req["condition_hash_semantics"]["equality_claim"] == "none"
        assert req["condition_hash_semantics"]["source_and_canonical_hashes_are_distinct"] is True
        assert req["source_and_canonical_hashes_are_distinct"] is True
        assert req["future_hashes_null"] is True
        assert req["future_outputs"]["solver_execution_receipt_sha256"] is None
        assert req["future_outputs"]["trajectory_h5_sha256"] is None
        assert req["future_outputs"]["typed_conversion_receipt_sha256"] is None


def test_manifest_contract():
    manifest = json.loads((ROOT / "manifest.json").read_text())
    assert manifest["request_count"] == 5
    assert manifest["actual_root117_per_case_completed_count"] == 5
    assert manifest["actual_root126_initial_qa_completed_count"] == 5
    assert manifest["root117_top_level_failure_preserved"] is True
    assert manifest["root117_top_level_failure_used_as_success_evidence"] is False
    assert manifest["source_and_canonical_hashes_are_distinct"] is True
    assert manifest["future_hashes_null"] is True
