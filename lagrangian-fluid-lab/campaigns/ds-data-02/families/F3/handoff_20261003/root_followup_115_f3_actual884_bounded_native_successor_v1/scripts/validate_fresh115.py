#!/usr/bin/env python3
"""Metadata-only validator for the F3 fresh115 Root884 successor."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
REQUEST = HERE / "requests/F3_STAGE1_DP006_P1200_AY0360-native-successor-115.disabled-request.json"
SOURCE_REQUEST = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_F3_actual839_full836_native7_remaining13_receipt_finalization_wait_884/requests/F3_STAGE1_DP006_P1200_AY0360-native-request.json")
AUDIT = HERE / "metadata/actual884-frontier-audit.json"
POLICY = HERE / "metadata/successor-policy.json"
CORRECTION = HERE / "metadata/root943-h5-boundary-correction.json"
FORBIDDEN_SUFFIXES = {".h5", ".hdf5", ".bi4", ".ibi4", ".csv", ".dat", ".vtk", ".vtu", ".npy", ".npz", ".raw", ".bin"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    request = json.loads(REQUEST.read_text(encoding="utf-8"))
    source_request = json.loads(SOURCE_REQUEST.read_text(encoding="utf-8"))
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    correction = json.loads(CORRECTION.read_text(encoding="utf-8"))
    package_payloads = [
        path for path in HERE.rglob("*")
        if path.is_file() and path.suffix.lower() in FORBIDDEN_SUFFIXES
    ]
    fields = request["fresh115_successor_provenance"]
    budget = request["home_storage_budget"]
    future = request["future_artifacts"]
    frontier = audit["frontier"]
    current = audit["handle884_runtime_audit"]
    checks = {
        "request_present": REQUEST.is_file(),
        "request_disabled": request["disabled"] is True and request["launch"] is False and request["launch_allowed"] is False and request["execution_allowed"] is False,
        "request_source_only": request["source_only"] is True and request["future_input_hashes_null"] is True,
        "selected_case_is_next_unstarted": request["case_id"] == "F3_STAGE1_DP006_P1200_AY0360" and policy["selected_first_unstarted_case"] == request["case_id"],
        "source_request_metadata_preserved": all(request[key] == source_request[key] for key in ("family_id", "case_id", "physical_case_id", "physical_condition_sha256", "gencase_receipt", "gencase_receipt_sha256", "actual_preparation_receipt", "initial_QA_exact_clone_evidence", "genuine_parent_initial_QA", "physical_binding", "command", "omp_threads", "expected_saved_frames", "physical_window_s", "save_interval_s", "input_files", "input_sha256")),
        "source_digest_policy_closed": fields["source_input_sha256_object_copied_without_rehash"] is True and request["science_digest_policy"]["payload_hashed_by_source_package"] is False,
        "science_recipe_preserved": fields["source_scientific_recipe_unchanged"] is True and fields["source_physical_binding_unchanged"] is True and request["expected_saved_frames"] == 836 and request["physical_window_s"] == [0, 8.35] and request["save_interval_s"] == 0.01,
        "genuine_initial_provenance_retained": fields["source_gen_case_and_initial_qa_actual0_provenance_retained"] is True,
        "future_outputs_null": all(future[key] is None for key in ("native_execution_receipt", "solver_output_root", "native_science_h5", "visual_receipt")) and future["case_credit"] == 0,
        "home_budget_10_plus_2": budget["base_native_estimate_bytes"] == 10 * 1024**3 and budget["additional_headroom_bytes"] == 2 * 1024**3 and budget["requested_estimated_storage_bytes"] == 12 * 1024**3 and request["estimated_storage_bytes"] == 12 * 1024**3,
        "home_floor_500_gib": request["home_free_floor_bytes"] >= 500 * 1024**3 and budget["home_free_floor_bytes"] >= 500 * 1024**3,
        "source_frontier_four_plus_nine": len(frontier["actual_completed0_retained"]) == 4 and len(frontier["original_remaining9_at_884_snapshot"]) == 9,
        "current_frontier_one_plus_eight": len(frontier["current_root948_successor_active"]) == 1 and len(frontier["current_unstarted_after_root948"]) == 8,
        "root948_not_duplicated": current["do_not_kill_or_retire_root948"] is True and current["lineage_successor_currently_active"] is True,
        "root947_lifecycle_disclosed": audit["subsequent_root_owned_event"]["root947"]["old_request_and_receipt_bytes_unchanged"] is True and audit["subsequent_root_owned_event"]["root947"]["performed_by_fresh115"] is False,
        "original_controller_no_children": current["original_884_controller_no_children_now"] is True and current["original_884_controller_absent_now"] is True,
        "root943_boundary_corrected": correction["corrected_boundary"]["registered_paraview_child_read_source_h5_via_xmf"] is True and correction["corrected_boundary"]["source_orchestrator_read_or_hashed_h5"] is False,
        "package_has_no_science_payload_files": not package_payloads,
        "no_shared_mutation_claimed": audit["live_ledger_audit"]["no_ledger_write_by_source_package"] is True,
    }
    report = {
        "schema": "ds02.stage1.f3.fresh115.validator-report.v1",
        "package": str(HERE),
        "checks": checks,
        "forbidden_payload_files": [str(path) for path in package_payloads],
        "request_sha256": sha256(REQUEST),
        "source_only": True,
    }
    (HERE / "metadata/fresh115-validator-report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
