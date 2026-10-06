#!/usr/bin/env python3
"""Validate fresh118 without opening scientific payloads."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
REQUEST = HERE / "requests/F3_STAGE1_DP006_P0800_AY0360-typed157-4gib-root118.disabled-request.json"
BINDING = HERE / "metadata/F3_STAGE1_DP006_P0800_AY0360-typed4gib-binding.json"
ROUTE = HERE / "metadata/fresh118-native-route.json"
FEASIBILITY = HERE / "metadata/fresh118-typed-feasibility.json"
ROOT157 = HERE / "metadata/fresh118-root157-contract.json"
REPORT = HERE / "metadata/fresh118-validator-report.json"
FORBIDDEN_SUFFIXES = {
    ".h5", ".hdf5", ".bi4", ".ibi4", ".csv", ".dat", ".vtk", ".vtu",
    ".npy", ".npz", ".raw", ".bin",
}
OLD_ROOT839_RECEIPT = "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3/F3_STAGE1_DP006_P0800_AY0360/root-stage1-f3-f3_stage1_dp006_p0800_ay0360-next20-full836-native-visual-rectangle-root839/execution-receipt.json"
ACTUAL_ROOT884_RECEIPT = "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3/F3_STAGE1_DP006_P0800_AY0360/root-stage1-f3-f3_stage1_dp006_p0800_ay0360-next20-full836-native-visual-rectangle-root839-CPU-registration-receipt-successor-root884/execution-receipt.json"
ACTUAL_ROOT884_REQUEST = "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_F3_actual839_full836_native7_remaining13_receipt_finalization_wait_884/requests/F3_STAGE1_DP006_P0800_AY0360-native-request.json"
ACTUAL_DATA_ROOT = "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3/F3_STAGE1_DP006_P0800_AY0360/root-stage1-f3-f3_stage1_dp006_p0800_ay0360-next20-full836-native-visual-rectangle-root839-CPU-registration-receipt-successor-root884/solver_output/data"
ROOT839_DATA_ROOT = "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3/F3_STAGE1_DP006_AY0360/root-stage1-f3-f3_stage1_dp006_p0800_ay0360-next20-full836-native-visual-rectangle-root839/solver_output/data"
WORKER = "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_157_nvme_typed_home_cap_publish_cleanup_fix_v1/scripts/nvme_convert_home_capped_v2.py"
WORKER_SHA = "37fe7eaff4405e9ba6d9b7f666a53d7c02ee65fc6f30992fc1a8fdb0d8a61b11"
LEDGER_LOCK = "/home/jade/Projects/DualSPHysics-data/ds-data-02/runtime/resource-ledger.lock"

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

def main() -> int:
    request = json.loads(REQUEST.read_text(encoding="utf-8"))
    binding = json.loads(BINDING.read_text(encoding="utf-8"))
    route = json.loads(ROUTE.read_text(encoding="utf-8"))
    feasibility = json.loads(FEASIBILITY.read_text(encoding="utf-8"))
    root157 = json.loads(ROOT157.read_text(encoding="utf-8"))
    command = request["command"]
    input_files = request["input_files"]
    input_sha = request["input_sha256"]
    package_payloads = [
        path for path in HERE.rglob("*")
        if path.is_file() and path.suffix.lower() in FORBIDDEN_SUFFIXES
    ]
    checks = {
        "request_binding_metadata_present": all(path.is_file() for path in (REQUEST, BINDING, ROUTE, FEASIBILITY, ROOT157)),
        "disabled_source_only_no_launch": request["disabled"] is True and request["source_only"] is True and request["launch"] is False and request["launch_allowed"] is False and request["execution_allowed"] is False,
        "case_and_recipe_closed": request["family_id"] == "F3" and request["case_id"] == "F3_STAGE1_DP006_P0800_AY0360" and request["physical_case_id"] == "F3_TWOAXIS_P0800_AY0360_STAGE1_FIRST48_PITCH_VARIANT" and request["expected_frames"] == 836 and request["expected_particles"] == 179208 and request["expected_dimension"] == 3 and request["physical_condition_sha256"] == "7560a18fa29742681ee567b06567ed4052da8ceb138b601e94b5223df22660f5" and request["binding"] == str(BINDING),
        "successor_is_distinct_from_root885": request["attempt_id"] != "root-stage1-f3-f3_stage1_dp006_p0800_ay0360-actual839-full836-typed-root885" and request["attempt_id"].endswith("typed157-4gib-root118"),
        "actual884_receipt_is_active_dependency": request["actual_native_dependency"]["status"] == "completed" and request["actual_native_dependency"]["returncode"] == 0 and request["actual_native_dependency"]["receipt"]["path"] == ACTUAL_ROOT884_RECEIPT and request["actual_native_dependency"]["request"]["path"] == ACTUAL_ROOT884_REQUEST and ACTUAL_ROOT884_RECEIPT in input_files,
        "root839_negative_is_preserved_but_not_active": request["historical_root839_negative"]["status"] == "failed" and request["historical_root839_negative"]["active_typed_input"] is False and OLD_ROOT839_RECEIPT not in input_files and OLD_ROOT839_RECEIPT not in command,
        "actual_data_root_replaces_old_route": ACTUAL_DATA_ROOT in command and ROOT839_DATA_ROOT not in command,
        "root157_worker_contract": command[1] == WORKER and request["source157_worker"]["path"] == WORKER and request["source157_worker"]["sha256"] == WORKER_SHA and request["source157_worker"]["must_be_revalidated_by_root"] is True,
        "wrapper_cli_contract": command.count("--") == 1 and "ds_data02_nvme_convert_v1.py" not in command and command[command.index("--") + 1] == "--data-root" and command[command.index("--") + 3] == "--generated-xml",
        "storage_guards": request["estimated_storage_bytes"] == 4 * 1024**3 and request["storage_policy"]["home_publish_cap_bytes"] == 4 * 1024**3 and request["storage_policy"]["home_free_floor_bytes"] == 500 * 1024**3 and request["storage_policy"]["private_nvme_staging_limit_bytes"] == 24 * 1024**3 and request["storage_policy"]["private_nvme_free_reserve_bytes"] == 100 * 1024**3 and request["storage_policy"]["resource_ledger_lock"] == LEDGER_LOCK,
        "fixed_point_and_lock_contract_attested": root157["reviewed_contract"]["exact_report_bytes_fixed_point_before_home_write"] is True and root157["reviewed_contract"]["ledger_lock_is_required"] is True and root157["reviewed_contract"]["flat_output_layout"] is True,
        "scope_layers_are_separate": binding["canonical_scope"]["sha256"] == request["physical_condition_sha256"] and binding["actual_converter_scope"]["sha256"] is None and binding["actual_converter_scope"]["status"] == "WAIT_ROOT157_METADATA_PREFLIGHT" and binding["legacy_converter_scope"]["sha256"] is None and request["root_prospective_legacy_scope_sha256"] is None and request["source_plan_scope_sha256"] is None,
        "future_outputs_null": all(value is None for key, value in request["future_outputs"].items() if key != "case_credit") and request["future_outputs"]["case_credit"] == 0 and request["future_input_hashes_null"] is True,
        "typed_result_is_waiting": binding["typed_result"]["status"] == "not_started" and request["actual_counts"]["typed_result"]["status"] == "WAIT_ROOT157_CONVERSION_REPORT",
        "input_hash_shape_closed_without_payload_read": bool(input_files) and set(input_files) == set(input_sha) and all(isinstance(value, str) and len(value) == 64 for value in input_sha.values()) and request["scientific_input_hash_policy"]["payload_hashes_computed_by_source_agent"] is False and request["scientific_input_hash_policy"]["payload_hashes_guessed"] is False,
        "package_binding_hash_closed": input_sha[str(BINDING)] == sha256(BINDING) and request["binding_sha256"] == sha256(BINDING),
        "no_scientific_payload_files_in_package": not package_payloads,
        "feasibility_is_not_result_claim": feasibility["interpretation"]["4gib_is_a_root157_hard_cap_and_estimate_not_a_completed_result"] is True and feasibility["scientific_payload_policy"]["h5_evidence_stat_only"] is True and feasibility["root939_cross_family_comparator"]["not_a_F3_guarantee"] is True,
        "accepted_and_typed_dedup_closed": feasibility["deduplication_audit"]["exact_case_id_in_acceptance_decision_files"] is False and feasibility["deduplication_audit"]["exact_physical_case_id_in_acceptance_decision_files"] is False and feasibility["deduplication_audit"]["selected_case_typed_outputs_at_audit"]["conversion_report_exists"] is False and feasibility["deduplication_audit"]["selected_case_typed_outputs_at_audit"]["trajectory_h5_exists"] is False,
        "route_metadata_matches_request": route["actual_route"]["receipt"]["path"] == ACTUAL_ROOT884_RECEIPT and route["actual_route"]["status"] == "completed" and route["historical_route"]["status"] == "failed",
        "source_boundaries_closed": request["source_agent_boundary"]["jobs_started"] == 0 and request["source_agent_boundary"]["scientific_payload_read"] is False and request["source_agent_boundary"]["scientific_payload_hashed"] is False and request["source_agent_boundary"]["shared_state_modified"] is False,
    }
    report = {
        "schema": "ds02.stage1.f3.fresh118.validator-report.v1",
        "package": str(HERE),
        "checks": checks,
        "forbidden_payload_files": [str(path) for path in package_payloads],
        "request_sha256": sha256(REQUEST),
        "binding_sha256": sha256(BINDING),
        "source_only": True,
        "external_science_payloads_opened_or_hashed_by_validator": False,
    }
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if all(checks.values()) else 1

if __name__ == "__main__":
    raise SystemExit(main())
