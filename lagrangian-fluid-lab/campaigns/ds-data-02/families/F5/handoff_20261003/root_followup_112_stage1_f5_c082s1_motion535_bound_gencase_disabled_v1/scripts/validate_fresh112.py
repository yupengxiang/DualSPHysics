#!/usr/bin/env python3
"""Validate fresh112 bindings using JSON/source metadata only.

The output motion paths and hashes are checked against Root535's producer
report fields.  The validator never opens or hashes a motion DAT and never
executes GenCase.
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any

PKG = Path(__file__).resolve().parents[1]
FRESH110 = PKG.parent / "root_followup_110_stage1_f5_c082s1_six_forcing_conditions_disabled_v1"
FRESH111 = PKG.parent / "root_followup_111_stage1_f5_c082s1_full1201_gate_sidecar_v1"
DATA_CASE = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1")
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
HANDOFF535 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f5_fresh110_six_actual_motion_preparation_535"
TAGS = ("M080_T090", "M080_T110", "M100_T090", "M100_T110", "M120_T090", "M120_T110")
SOURCE_SUFFIXES = {".json", ".py", ".md", ".txt", ".xml", ".log"}
SCIENCE_SUFFIXES = {".dat", ".bi4", ".h5", ".hdf5", ".csv", ".vtk", ".vtu", ".npy", ".npz"}
FRESH110_COMMIT = "57ccfc730bdaf2eae462591ff9f3b737e5272dd3"
FRESH111_COMMIT = "d5d888cfa35f94ae5ebaf315c10e1eaddd8f16f0"


def sha_json(path: Path) -> str:
    if path.suffix.lower() in SCIENCE_SUFFIXES:
        raise AssertionError(f"science payload hash attempted: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"JSON object required: {path}")
    return value


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def producer_paths(tag: str) -> tuple[Path, Path, Path]:
    attempt = f"root-stage1-f5-c082s1-{tag.lower()}-motion-transform-110-root535"
    root = DATA_CASE / attempt
    return root / "motion-transform-report.json", root / "execution-receipt.json", HANDOFF535 / f"C082S1_MOTION_{tag}-motion-request.json"


def validate_manifest() -> None:
    manifest = load(PKG / "manifest.json")
    require(manifest.get("schema") == "ds02.f5.c082s1.fresh112-source-manifest.v1", "manifest schema")
    require(manifest.get("status") == "six_motion535_bound_gencase_requests_disabled_full1201_gate_wait", "manifest status")
    require(manifest.get("validator_report_excluded_from_manifest") is True, "validator exclusion")
    require(manifest.get("fresh110_modified") is False and manifest.get("fresh111_modified") is False, "upstream mutation")
    require(manifest.get("full1201_authorized") is False, "full1201 authorization")
    require(manifest.get("science_payloads_read_or_hashed_by_source_builder") is False, "science builder marker")
    require(manifest.get("motion_dat_read_copied_or_hashed_by_source_builder") is False, "motion DAT marker")
    require(manifest.get("jobs_started") is False and manifest.get("shared_state_modified") is False, "side effects")
    files = manifest.get("files")
    require(isinstance(files, dict) and files, "manifest files")
    require("metadata/fresh112-validator-report.json" not in files, "validator report must be excluded")
    for rel, expected in files.items():
        path = PKG / rel
        require(path.is_file(), f"missing package file: {rel}")
        require(path.suffix.lower() in SOURCE_SUFFIXES, f"non-source package file: {rel}")
        require(path.suffix.lower() not in SCIENCE_SUFFIXES, f"science package file: {rel}")
        require(sha_json(path) == expected, f"package hash mismatch: {rel}")


def validate_scripts() -> None:
    for path in sorted((PKG / "scripts").glob("*.py")):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def validate_gate() -> dict[str, Any]:
    sidecar_path = FRESH111 / "metadata/fresh111-full1201-gate-sidecar.json"
    sidecar = load(sidecar_path)
    require(sidecar.get("status") == "fresh110_full1201_blocked_on_existing_A080_A120_full801_visual_pass", "fresh111 status")
    require(sidecar.get("short_window_semantics", {}).get("can_authorize_fresh110_full1201") is False, "Root511 overreach")
    require(sidecar.get("existing_full801_gate", {}).get("current_status") == "WAIT/null", "existing full801 status")
    require(sidecar.get("existing_full801_gate", {}).get("full801_visual_pass") is False, "existing visual pass")
    return {
        "sidecar_path": str(sidecar_path),
        "sidecar_sha256": sha_json(sidecar_path),
        "sidecar_commit": FRESH111_COMMIT,
        "status": "WAIT/null",
        "root511_short_render_can_authorize_new_full1201": False,
        "existing_A080_A120_full801_visual_pass": False,
    }


def require_gate(value: Any, gate: dict[str, Any], label: str) -> None:
    require(isinstance(value, dict), f"{label} gate object")
    for key, expected in gate.items():
        require(value.get(key) == expected, f"{label} gate field {key}")
    require(value.get("required_before_fresh110_full1201") is True, f"{label} full1201 dependency")
    require(value.get("future_authorization_receipt") is None, f"{label} future authorization receipt")
    require(value.get("future_authorization_sha256") is None, f"{label} future authorization hash")


def validate_candidate(tag: str, provenance: dict[str, Any], gate: dict[str, Any]) -> None:
    report_path, receipt_path, source_request_path = producer_paths(tag)
    report = load(report_path)
    receipt = load(receipt_path)
    source_request = load(source_request_path)
    nested_request = receipt.get("request", {})
    require(isinstance(nested_request, dict), f"{tag} Root535 receipt request")
    require(source_request.get("attempt_id") == nested_request.get("attempt_id"), f"{tag} Root535 attempt")
    require(report.get("schema") == "ds02.f5.c082s1.motion-transform-receipt.fresh110.v1", f"{tag} report schema")
    record = provenance
    require(record["report_path"] == str(report_path), f"{tag} report path")
    require(record["receipt_path"] == str(receipt_path), f"{tag} receipt path")
    require(record["report_sha256"] == sha_json(report_path), f"{tag} report hash")
    require(record["receipt_sha256"] == sha_json(receipt_path), f"{tag} receipt hash")
    require(record["root_request_sha256"] == sha_json(source_request_path), f"{tag} source request hash")

    request_path = PKG / "requests" / f"{tag}-gencase-request.json"
    binding_path = PKG / "bindings" / f"{tag}-gencase-binding.json"
    request = load(request_path)
    binding = load(binding_path)
    require(request.get("schema") == "ds02.runner-request.v2", f"{tag} request schema")
    require(request.get("binding") == str(binding_path), f"{tag} binding path")
    require(request.get("binding_sha256") == sha_json(binding_path), f"{tag} binding hash")
    require(binding.get("schema") == "ds02.f5.c082s1.motion535-gencase-binding.fresh112.v1", f"{tag} binding schema")
    require(request.get("disabled") is True and request.get("execution_allowed") is False, f"{tag} disabled execution")
    require(request.get("launch") is False and request.get("launch_allowed") is False and request.get("solver_allowed") is False, f"{tag} launch controls")
    require(request.get("full801_authorized") is False and request.get("q_n_granted") is False, f"{tag} authorization")
    require(request.get("expected_counts") is None, f"{tag} expected counts")
    require(request.get("generated_bi4") is None and request.get("generated_xml") is None, f"{tag} generated outputs")
    require(all(value is None for value in request.get("future_output_hashes", {}).values()), f"{tag} future hashes")
    require_gate(request.get("upstream_full801_visual_gate"), gate, f"{tag} request")
    require_gate(binding.get("upstream_full801_visual_gate"), gate, f"{tag} binding")
    require(request.get("motion_transform_attempt") == record["attempt_id"], f"{tag} producer attempt")
    require(request.get("motion_transform_report") == record["report_path"], f"{tag} producer report")
    require(request.get("motion_transform_receipt") == record["receipt_path"], f"{tag} producer receipt")
    require(request.get("motion_transform_report_sha256") == record["report_sha256"], f"{tag} producer report hash")
    require(request.get("motion_transform_receipt_sha256") == record["receipt_sha256"], f"{tag} producer receipt hash")
    require(request.get("root_source_interpreter_digest") is None, f"{tag} source interpreter digest must remain null")
    require(request.get("root_actual_interpreter_digest") == record["root_actual_interpreter_digest"], f"{tag} actual interpreter digest")
    require(request.get("motion_asset_sha256") == record["output_motion_sha256"], f"{tag} producer motion hash")
    require(request.get("motion_asset_sha256_provenance", "").startswith("Root535 motion-transform-report.json producer field"), f"{tag} motion hash provenance")
    require(request.get("motion_asset_path") == record["output_motion"], f"{tag} motion path")
    require(request.get("motion_rows") == record["rows"] == 641, f"{tag} motion rows")
    require(request.get("motion_output_time_end_s") == record["output_time_end_s"], f"{tag} motion endpoint")
    require(request.get("input_sha256", {}).get(record["output_motion"]) == record["output_motion_sha256"], f"{tag} DAT producer SHA binding")
    require(request.get("input_sha256", {}).get(record["report_path"]) == record["report_sha256"], f"{tag} report input hash")
    require(request.get("input_sha256", {}).get(record["receipt_path"]) == record["receipt_sha256"], f"{tag} receipt input hash")
    require(binding.get("full_event_window_s") == [0.0, 24.0], f"{tag} full event window")
    require(binding.get("motion_output_sha256") == record["output_motion_sha256"], f"{tag} binding motion hash")
    require(binding.get("motion_output_rows") == 641, f"{tag} binding motion rows")
    require(binding.get("actual_counts") is None and binding.get("expected_fluid") is None, f"{tag} binding counts")
    require(binding.get("root_source_interpreter_digest") is None, f"{tag} binding source interpreter digest")
    require(binding.get("root_actual_interpreter_digest") == record["root_actual_interpreter_digest"], f"{tag} binding actual interpreter digest")
    require(binding.get("motion_asset", {}).get("path") == record["output_motion"], f"{tag} binding asset path")
    require(binding.get("motion_asset", {}).get("sha256") == record["output_motion_sha256"], f"{tag} binding asset hash")
    require(binding.get("assets", [{}])[0].get("sha256") == record["output_motion_sha256"], f"{tag} asset hash")


def main() -> int:
    validate_manifest()
    validate_scripts()
    plan = load(PKG / "metadata/fresh112-source-plan.json")
    provenance = load(PKG / "metadata/fresh112-motion535-binding-provenance.json")
    require(plan.get("schema") == "ds02.f5.c082s1.fresh112-source-plan.v1", "plan schema")
    require(plan.get("candidate_count") == 6 and plan.get("candidate_tags") == list(TAGS), "candidate set")
    require(plan.get("full_event_window") == {"tmax_s": 24.0, "tout_s": 0.02, "frames": 1201}, "full event window")
    require(plan.get("gencase_requests_disabled") is True and plan.get("execution_allowed") is False, "GenCase disabled gate")
    require(plan.get("future_counts_and_hashes_null") is True, "future producer fields")
    require(plan.get("fresh111_gate_status") == "WAIT/null", "fresh111 gate status")
    require(plan.get("root511_short_window_can_authorize_new_full1201") is False, "Root511 gate role")
    require(plan.get("existing_A080_A120_full801_visual_pass") is False, "existing full visual status")
    require(plan.get("source110_forecast_interpreter_digest_used") is False, "source forecast digest")
    require(plan.get("root535_actual_interpreter_digest_bound") is True, "actual interpreter digest")
    require(provenance.get("schema") == "ds02.f5.c082s1.fresh112-motion535-binding-provenance.v1", "provenance schema")
    require(provenance.get("fresh110_commit") == FRESH110_COMMIT and provenance.get("fresh111_commit") == FRESH111_COMMIT, "upstream commits")
    require(provenance.get("full_event_window") == plan["full_event_window"], "provenance window")
    require(provenance.get("fresh111_gate", {}).get("status") == "WAIT/null", "provenance gate")
    require(provenance.get("future_gencase_counts") is None, "provenance counts")
    require(provenance.get("motion_dat_read_copied_or_hashed_by_source_agent") is False, "provenance DAT marker")
    records = provenance.get("candidates")
    require(isinstance(records, list) and len(records) == 6, "provenance candidates")
    by_tag = {record.get("tag"): record for record in records}
    require(set(by_tag) == set(TAGS), "provenance tag set")
    gate = validate_gate()
    for tag in TAGS:
        validate_candidate(tag, by_tag[tag], gate)
    report = {
        "schema": "ds02.f5.c082s1.fresh112-validator-report.v1",
        "status": "passed_six_root535_motion_bindings_gencase_disabled_full1201_gate_wait",
        "candidate_count": 6,
        "full_event_window": plan["full_event_window"],
        "all_motion_producers_completed": all(record.get("status") == "completed" for record in records),
        "all_gencase_requests_disabled": True,
        "full1201_authorized": False,
        "fresh111_gate_status": "WAIT/null",
        "future_counts_and_hashes_null": True,
        "science_payloads_read_or_hashed_by_validator": False,
        "motion_dat_read_or_hashed_by_validator": False,
        "jobs_started": False,
        "shared_state_modified": False,
    }
    (PKG / "metadata/fresh112-validator-report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "candidate_count": 6, "full1201_authorized": False, "motion_dat_read_or_hashed_by_validator": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
