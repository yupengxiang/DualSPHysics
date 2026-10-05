#!/usr/bin/env python3
"""Validate fresh114 metadata bindings without opening science payloads."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any

PKG = Path(__file__).resolve().parents[1]
DATA_CASE = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1")
TAGS = ("M080_T090", "M080_T110", "M100_T090", "M100_T110", "M120_T090", "M120_T110")
SCIENCE_SUFFIXES = {".dat", ".bi4", ".h5", ".hdf5", ".csv", ".vtk", ".vtu", ".npy", ".npz"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"JSON object required: {path}")
    return value


def sha_json(path: Path) -> str:
    require(path.suffix.lower() not in SCIENCE_SUFFIXES, f"science hash attempted: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def paths(tag: str) -> tuple[Path, Path, Path]:
    root = DATA_CASE / f"root-stage1-f5-c082s1-{tag.lower()}-actual-initial-qa-113-root553"
    return (
        root / "execution-receipt.json",
        root / "initial-qa/placement/c082s1-stage1-placement-mk50-audit.json",
        root / "initial-qa/registered-export-and-placement-producer.json",
    )


def gate() -> dict[str, Any]:
    path = PKG.parent / "root_followup_111_stage1_f5_c082s1_full1201_gate_sidecar_v1/metadata/fresh111-full1201-gate-sidecar.json"
    sidecar = load(path)
    require(sidecar.get("status") == "fresh110_full1201_blocked_on_existing_A080_A120_full801_visual_pass", "fresh111 status")
    require(sidecar.get("short_window_semantics", {}).get("can_authorize_fresh110_full1201") is False, "short gate")
    require(sidecar.get("existing_full801_gate", {}).get("current_status") == "WAIT/null", "existing full gate")
    return {
        "status": "WAIT/null",
        "sidecar_path": str(path),
        "sidecar_sha256": sha_json(path),
        "sidecar_commit": "d5d888cfa35f94ae5ebaf315c10e1eaddd8f16f0",
        "existing_A080_A120_full801_visual_pass": False,
        "root511_short_render_can_authorize_new_full1201": False,
        "required_before_any_full24s_1201": True,
        "future_authorization_receipt": None,
        "future_authorization_sha256": None,
    }


def validate_manifest() -> None:
    manifest = load(PKG / "manifest.json")
    require(manifest.get("schema") == "ds02.f5.c082s1.fresh114-source-manifest.v1", "manifest schema")
    require(manifest.get("status") == "six_root553_initial_qa_completed_basic_pass_native_downstream_disabled_full1201_gate_wait", "manifest status")
    require(manifest.get("validator_report_excluded_from_manifest") is True, "validator exclusion")
    require(manifest.get("fresh113_modified") is False and manifest.get("fresh111_modified") is False, "upstream mutation")
    require(manifest.get("science_payloads_read_or_hashed_by_source_builder") is False, "science provenance")
    require(manifest.get("bi4_csv_dat_h5_vtk_payloads_read_or_hashed_by_source_builder") is False, "payload provenance")
    require(manifest.get("jobs_started") is False and manifest.get("shared_state_modified") is False, "side effects")
    require(manifest.get("full1201_authorized") is False, "full authorization")
    files = manifest.get("files")
    require(isinstance(files, dict) and files, "manifest files")
    require("metadata/fresh114-validator-report.json" not in files, "validator report in manifest")
    for rel, expected in files.items():
        path = PKG / rel
        require(path.is_file(), f"missing manifest file: {rel}")
        require(path.suffix.lower() not in SCIENCE_SUFFIXES, f"science file in package: {rel}")
        require(sha_json(path) == expected, f"manifest hash: {rel}")


def validate_external(tag: str, qa: dict[str, Any]) -> None:
    receipt_path, report_path, producer_path = paths(tag)
    receipt = load(receipt_path)
    report = load(report_path)
    producer = load(producer_path)
    require(qa.get("status") == "completed/0", f"{tag} QA status")
    require(qa.get("qa_receipt") == str(receipt_path) and qa.get("placement_report") == str(report_path), f"{tag} QA paths")
    require(qa.get("registered_producer") == str(producer_path), f"{tag} producer path")
    require(qa.get("qa_receipt_sha256") == sha_json(receipt_path), f"{tag} receipt hash")
    require(qa.get("placement_report_sha256") == sha_json(report_path), f"{tag} report hash")
    require(qa.get("registered_producer_sha256") == sha_json(producer_path), f"{tag} producer hash")
    require(receipt.get("status") == "completed" and receipt.get("returncode") == 0 and receipt.get("termination_reason") is None, f"{tag} receipt status")
    require(report.get("status") == "completed_stage1_placement_mk50_diagnostic", f"{tag} report status")
    require(report.get("all_basic_placement_checks_pass") is True and report.get("diagnostic_only") is True, f"{tag} basic placement")
    require(report.get("arrays_opened_by_source_agent") is False, f"{tag} array provenance")
    require(qa.get("producer_report_actual_counts") == report.get("actual_counts"), f"{tag} raw producer counts binding")
    request_counts = receipt.get("request", {}).get("actual_counts")
    require(qa.get("actual_counts") == request_counts, f"{tag} normalized counts binding")
    require(qa.get("basic_placement_pass") is True and qa.get("initial_qa_precision_negative_preserved", True) is True, f"{tag} QA status flags")
    require(qa.get("fluid_geometry", {}).get("below_profile_count") == 0, f"{tag} profile")
    require(len(qa.get("fluid_geometry", {}).get("unique_y_levels", [])) == 15, f"{tag} y-levels")
    require(qa.get("mk50_coverage", {}).get("native_bed_mk") == 50 and qa.get("mk50_coverage", {}).get("source_mkbound") == 40, f"{tag} markers")
    require(qa.get("precision_negative", {}).get("classification") == "numerical_precision", f"{tag} precision classification")
    require(qa.get("precision_negative", {}).get("pass_at_original_threshold") is False, f"{tag} precision result")
    require(qa.get("derived_bed_depth_diagnostics", {}).get("derived_inference") is True, f"{tag} inference marker")
    require(qa.get("derived_bed_depth_diagnostics", {}).get("not_a_new_array_audit") is True, f"{tag} array-audit marker")
    require(producer.get("placement_returncode") == 0, f"{tag} registered producer")


def validate_binding(tag: str, qa: dict[str, Any], full_gate: dict[str, Any]) -> Path:
    path = PKG / "bindings" / f"{tag}-actual-initial-qa-bound-binding.json"
    binding = load(path)
    require(binding.get("schema") == "ds02.f5.c082s1.actual-initial-qa-bound-native-disabled.fresh114.v1", f"{tag} binding schema")
    require(binding.get("source_only") is True and binding.get("actual_counts") == qa.get("actual_counts"), f"{tag} binding counts")
    require(binding.get("initial_qa", {}).get("qa_attempt_id") == qa.get("qa_attempt_id"), f"{tag} binding QA identity")
    require(binding.get("initial_qa_status") == "completed/0" and binding.get("initial_qa_basic_pass") is True, f"{tag} binding status")
    require(binding.get("native_bed_marker_mk") == 50 and binding.get("source_bed_marker_mkbound") == 40, f"{tag} binding marker")
    require(binding.get("upstream_full801_visual_gate") == full_gate, f"{tag} binding gate")
    require(binding.get("full24_authorized") is False and binding.get("full801_authorized") is False and binding.get("short_solver_authorized") is False, f"{tag} binding authorization")
    require(all(value is None for value in binding.get("future_native_outputs", {}).values()), f"{tag} future binding outputs")
    return path


def validate_request(tag: str, qa: dict[str, Any], binding_path: Path, full_gate: dict[str, Any], full: bool) -> None:
    name = f"{tag}-{'full24' if full else 'short51'}-native-qualification-request.json"
    path = PKG / "requests" / name
    req = load(path)
    counts = qa["actual_counts"]
    require(req.get("schema") == "ds02.runner-request.v2", f"{name} schema")
    require(req.get("binding") == str(binding_path) and req.get("binding_sha256") == sha_json(binding_path), f"{name} binding closure")
    require(req.get("disabled") is True and req.get("execution_allowed") is False and req.get("launch") is False and req.get("solver_allowed") is False, f"{name} disabled")
    require(req.get("actual_initial_qa_report") == qa["placement_report"], f"{name} report dependency")
    require(req.get("depends_on_attempt") == qa["qa_attempt_id"], f"{name} attempt dependency")
    require(req.get("actual_counts") == counts and req.get("expected_counts") == counts, f"{name} counts")
    require(req.get("expected_dimension") == 3 and req.get("native_bed_mk") == 50 and req.get("source_mkbound") == 40, f"{name} dimensions/markers")
    require(req.get("initial_qa_status") == "completed/0" and req.get("initial_qa_basic_pass") is True, f"{name} initial QA")
    require(req.get("full_native_authorized") is False and req.get("full801_authorized") is False and req.get("q_n_granted") is False, f"{name} authorization")
    require(req.get("upstream_full801_visual_gate") == full_gate, f"{name} gate")
    require(all(value is None for value in req.get("future_output_hashes", {}).values()), f"{name} future outputs")
    require(req.get("motion_asset_sha256") is None, f"{name} future motion hash")
    if full:
        require(req.get("tmax_s") == 24.0 and req.get("tout_s") == 0.02 and req.get("expected_frames") == 1201, f"{name} full window")
        require(req.get("upstream_visual_gate") == "WAIT_existing_A080_A120_full801_root_visual_pass", f"{name} visual gate")
    else:
        require(req.get("tmax_s") == 1.0 and req.get("tout_s") == 0.02 and req.get("expected_frames") == 51, f"{name} short window")
    sha_map = req.get("input_sha256", {})
    for key, field in ((qa["qa_receipt"], "qa_receipt_sha256"), (qa["placement_report"], "placement_report_sha256"), (qa["registered_producer"], "registered_producer_sha256")):
        require(sha_map.get(key) == qa[field], f"{name} metadata input hash {key}")
    require(sha_map.get(str(binding_path)) == sha_json(binding_path), f"{name} binding input hash")


def main() -> int:
    validate_manifest()
    for script in sorted((PKG / "scripts").glob("*.py")):
        ast.parse(script.read_text(encoding="utf-8"), filename=str(script))
    full_gate = gate()
    provenance = load(PKG / "metadata/fresh114-actual-initial-qa-provenance.json")
    plan = load(PKG / "metadata/fresh114-source-plan.json")
    require(plan.get("candidate_count") == 6 and plan.get("candidate_tags") == list(TAGS), "plan candidates")
    require(plan.get("actual_initial_qa_completed0") is True and plan.get("native_future_requests_disabled") is True, "plan QA status")
    require(plan.get("existing_A080_A120_full801_visual_gate") == "WAIT/null", "plan gate")
    require(plan.get("exact_dp_lattice_precision_negative", {}).get("accepted") is False, "plan precision")
    require(provenance.get("actual_root553_completed0_count") == 6 and provenance.get("actual_basic_placement_pass_count") == 6, "provenance statuses")
    require(provenance.get("derived_1dp_2dp_zero_is_not_new_array_audit") is True, "provenance inference")
    records = {record["tag"]: record for record in provenance.get("candidates", [])}
    require(set(records) == set(TAGS), "provenance tags")
    results = []
    for tag in TAGS:
        qa = records[tag]
        validate_external(tag, qa)
        binding_path = validate_binding(tag, qa, full_gate)
        validate_request(tag, qa, binding_path, full_gate, False)
        validate_request(tag, qa, binding_path, full_gate, True)
        results.append({"tag": tag, "status": "completed/0", "basic_placement_pass": True, "precision": "negative_preserved", "native_downstream": "disabled"})
    report = {
        "schema": "ds02.f5.c082s1.fresh114-validator-report.v1",
        "status": "passed_six_root553_actual_initial_qa_bindings_native_short_full_disabled_gate_wait",
        "candidate_count": 6,
        "candidates": results,
        "derived_zero_1dp_2dp_is_inference_only": True,
        "exact_dp_precision_negative_preserved": True,
        "full24_authorized": False,
        "full801_authorized": False,
        "future_solver_typed_xmf_bed_render_hashes_null": True,
        "science_payloads_read_or_hashed_by_validator": False,
    }
    out = PKG / "metadata/fresh114-validator-report.json"
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
