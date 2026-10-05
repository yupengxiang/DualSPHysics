#!/usr/bin/env python3
"""Validate fresh113's Root544-bound native initial QA contracts.

The validator reads JSON metadata and checks XML/BI4 path strings and
producer-attested hashes.  It never opens or hashes XML, BI4, CSV, DAT, H5,
or VTK payloads.
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
FRESH112 = PKG.parent / "root_followup_112_stage1_f5_c082s1_motion535_bound_gencase_disabled_v1"
DATA_CASE = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1")
CASE = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1"
TAGS = ("M080_T090", "M080_T110", "M100_T090", "M100_T110", "M120_T090", "M120_T110")
SOURCE_SUFFIXES = {".json", ".py", ".md", ".txt", ".xml", ".log"}
SCIENCE_SUFFIXES = {".dat", ".bi4", ".h5", ".hdf5", ".csv", ".vtk", ".vtu", ".npy", ".npz"}
FRESH110_COMMIT = "57ccfc730bdaf2eae462591ff9f3b737e5272dd3"
FRESH111_COMMIT = "d5d888cfa35f94ae5ebaf315c10e1eaddd8f16f0"
FRESH112_COMMIT = "586555fe048c628c24ef363a301208302cef1ae9"


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


def paths(tag: str) -> tuple[Path, Path, Path, Path]:
    root = DATA_CASE / f"root-stage1-f5-c082s1-{tag.lower()}-genuine-gencase-112-root544"
    receipt = root / "execution-receipt.json"
    report = root / "prepared/prepared-input-report.json"
    report_meta = load(report)
    prefix = report_meta.get("prefix")
    require(isinstance(prefix, str), f"{tag} producer prefix")
    return receipt, report, Path(prefix + ".xml"), Path(prefix + ".bi4")


def validate_manifest() -> None:
    manifest = load(PKG / "manifest.json")
    require(manifest.get("schema") == "ds02.f5.c082s1.fresh113-source-manifest.v1", "manifest schema")
    require(manifest.get("status") == "six_root544_gencase_metadata_bound_native_initial_qa_disabled_full1201_gate_wait", "manifest status")
    require(manifest.get("validator_report_excluded_from_manifest") is True, "validator exclusion")
    require(manifest.get("fresh110_modified") is False and manifest.get("fresh111_modified") is False and manifest.get("fresh112_modified") is False, "upstream mutation")
    require(manifest.get("full1201_authorized") is False, "full1201 authorization")
    require(manifest.get("science_payloads_read_or_hashed_by_source_builder") is False, "science builder marker")
    require(manifest.get("bi4_csv_dat_h5_vtk_payloads_read_or_hashed_by_source_builder") is False, "payload marker")
    require(manifest.get("jobs_started") is False and manifest.get("shared_state_modified") is False, "side effects")
    files = manifest.get("files")
    require(isinstance(files, dict) and files, "manifest files")
    require("metadata/fresh113-validator-report.json" not in files, "validator report exclusion")
    for rel, expected in files.items():
        path = PKG / rel
        require(path.is_file(), f"missing package file: {rel}")
        require(path.suffix.lower() in SOURCE_SUFFIXES, f"non-source file: {rel}")
        require(path.suffix.lower() not in SCIENCE_SUFFIXES, f"science file in package: {rel}")
        require(sha_json(path) == expected, f"manifest hash mismatch: {rel}")


def validate_scripts() -> None:
    for path in sorted((PKG / "scripts").glob("*.py")):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def validate_gate() -> dict[str, Any]:
    sidecar_path = FRESH111 / "metadata/fresh111-full1201-gate-sidecar.json"
    sidecar = load(sidecar_path)
    require(sidecar.get("status") == "fresh110_full1201_blocked_on_existing_A080_A120_full801_visual_pass", "fresh111 status")
    require(sidecar.get("short_window_semantics", {}).get("can_authorize_fresh110_full1201") is False, "Root511 authorization")
    require(sidecar.get("existing_full801_gate", {}).get("current_status") == "WAIT/null", "existing full801 status")
    require(sidecar.get("existing_full801_gate", {}).get("full801_visual_pass") is False, "existing full801 visual")
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
        require(value.get(key) == expected, f"{label} gate {key}")
    require(value.get("required_before_any_full24s_1201") is True, f"{label} full24 dependency")
    require(value.get("future_authorization_receipt") is None, f"{label} future authorization receipt")
    require(value.get("future_authorization_sha256") is None, f"{label} future authorization hash")


def validate_producer(tag: str, record: dict[str, Any]) -> None:
    receipt_path, report_path, xml_path, bi4_path = paths(tag)
    receipt = load(receipt_path)
    report = load(report_path)
    nested = receipt.get("request", {})
    counts = report.get("generated_xml_particle_counts", {})
    require(receipt.get("status") == "completed" and receipt.get("returncode") == 0, f"{tag} completed/0")
    require(receipt.get("termination_reason") is None, f"{tag} termination")
    require(isinstance(nested, dict) and nested.get("case_id") == CASE, f"{tag} receipt identity")
    require(report.get("schema") == "ds02.root.actual-native-source-preflight.v1", f"{tag} report schema")
    require(report.get("case_id") == CASE, f"{tag} report identity")
    require(isinstance(counts, dict), f"{tag} counts")
    require(report.get("actual_total_particles") == 194427, f"{tag} total count")
    require(counts == {"fixed": 158559, "moving": 4210, "floating": 0, "fluid": 31658}, f"{tag} producer counts")
    require(receipt.get("total_particles") == 194427 and receipt.get("fluid_particles") == 31658, f"{tag} receipt counts")
    require(receipt.get("solver_dimension_from_gencase") == 3, f"{tag} dimension")
    require(isinstance(report.get("xml_sha256"), str) and len(report["xml_sha256"]) == 64, f"{tag} XML attestation")
    require(isinstance(report.get("bi4_sha256"), str) and len(report["bi4_sha256"]) == 64, f"{tag} BI4 attestation")
    require(record.get("status") == "completed/0", f"{tag} provenance status")
    require(record.get("receipt_path") == str(receipt_path) and record.get("report_path") == str(report_path), f"{tag} producer paths")
    require(record.get("receipt_sha256") == sha_json(receipt_path), f"{tag} receipt JSON hash")
    require(record.get("report_sha256") == sha_json(report_path), f"{tag} report JSON hash")
    require(record.get("generated_xml") == str(xml_path) and record.get("generated_bi4") == str(bi4_path), f"{tag} output paths")
    require(record.get("generated_xml_sha256") == report.get("xml_sha256"), f"{tag} XML producer hash")
    require(record.get("generated_bi4_sha256") == report.get("bi4_sha256"), f"{tag} BI4 producer hash")
    require(record.get("actual_counts") == {"data2d": False, "fixed_particles": 158559, "floating_particles": 0, "fluid_particles": 31658, "moving_particles": 4210, "solver_dimension": 3, "total_particles": 194427}, f"{tag} normalized counts")


def validate_candidate(tag: str, record: dict[str, Any], gate: dict[str, Any]) -> None:
    receipt_path, report_path, xml_path, bi4_path = paths(tag)
    request_path = PKG / "requests" / f"{tag}-initial-placement-mk50-request.json"
    binding_path = PKG / "bindings" / f"{tag}-initial-qa-mk50-binding.json"
    request = load(request_path)
    binding = load(binding_path)
    require(request.get("schema") == "ds02.runner-request.v2", f"{tag} request schema")
    require(binding.get("schema") == "ds02.f5.c082s1.actual-gencase-bound-initial-mk50-binding.fresh113.v1", f"{tag} binding schema")
    require(request.get("binding") == str(binding_path), f"{tag} binding path")
    require(request.get("binding_sha256") == sha_json(binding_path), f"{tag} binding hash")
    require(request.get("disabled") is True and request.get("execution_allowed") is False, f"{tag} disabled")
    require(request.get("launch") is False and request.get("launch_allowed") is False and request.get("solver_allowed") is False, f"{tag} launch controls")
    require(request.get("full801_authorized") is False and request.get("q_n_granted") is False, f"{tag} authorization")
    require(all(value is None for value in request.get("future_output_hashes", {}).values()), f"{tag} future QA hashes")
    require(request.get("upstream_full801_visual_gate", {}).get("status") == "WAIT/null", f"{tag} gate status")
    require_gate(request.get("upstream_full801_visual_gate"), gate, f"{tag} request")
    require_gate(binding.get("upstream_full801_visual_gate"), gate, f"{tag} binding")
    require(request.get("gencase_attempt_id") == record.get("attempt_id"), f"{tag} GenCase attempt")
    require(request.get("depends_on_attempt") == record.get("attempt_id"), f"{tag} dependency")
    require(request.get("gencase_receipt") == record.get("receipt_path"), f"{tag} receipt path")
    require(request.get("prepared_input_report") == record.get("report_path"), f"{tag} report path")
    require(request.get("generated_xml") == record.get("generated_xml"), f"{tag} XML path")
    require(request.get("generated_bi4") == record.get("generated_bi4"), f"{tag} BI4 path")
    require(request.get("generated_xml_sha256") == record.get("generated_xml_sha256"), f"{tag} XML hash")
    require(request.get("generated_bi4_sha256") == record.get("generated_bi4_sha256"), f"{tag} BI4 hash")
    require(request.get("gencase_receipt_sha256") == record.get("receipt_sha256"), f"{tag} receipt hash")
    require(request.get("prepared_input_report_sha256") == record.get("report_sha256"), f"{tag} report hash")
    expected = record["actual_counts"]
    require(request.get("actual_counts") == expected and request.get("expected_counts") == expected, f"{tag} actual counts")
    require(request.get("expected_particles") == 194427 and request.get("expected_fluid_particles") == 31658, f"{tag} scalar counts")
    require(request.get("expected_fixed_particles") == 158559 and request.get("expected_moving_particles") == 4210 and request.get("expected_floating_particles") == 0, f"{tag} fixed/moving counts")
    require(request.get("official_particle_csv") is None and request.get("official_particle_csv_sha256") is None, f"{tag} future CSV")
    checks = request.get("native_initial_checks", {})
    require(checks.get("native_bed_mk") == 50 and checks.get("source_mkbound") == 40, f"{tag} marker mapping")
    require(checks.get("required_native_3d") is True and checks.get("required_unique_finite_uid") is True, f"{tag} identity checks")
    require(checks.get("required_transverse_y_levels") == 15, f"{tag} y levels")
    profile = checks.get("bed_penetration_profile", {})
    require(profile.get("one_dp_depth_m") == 0.02 and profile.get("two_dp_depth_m") == 0.04, f"{tag} bed thresholds")
    require(profile.get("all_fluid_denominator") is True and profile.get("frame_scope") == "native initial state only", f"{tag} bed scope")
    producer = request.get("gencase_producer", {})
    require(producer.get("completed0") is True, f"{tag} producer completed0")
    require(producer.get("generated_xml_sha256") == record.get("generated_xml_sha256"), f"{tag} producer XML")
    require(producer.get("generated_bi4_sha256") == record.get("generated_bi4_sha256"), f"{tag} producer BI4")
    hashes = request.get("input_sha256", {})
    require(hashes.get(record["receipt_path"]) == record["receipt_sha256"], f"{tag} receipt input hash")
    require(hashes.get(record["report_path"]) == record["report_sha256"], f"{tag} report input hash")
    require(hashes.get(record["generated_xml"]) == record["generated_xml_sha256"], f"{tag} XML input hash")
    require(hashes.get(record["generated_bi4"]) == record["generated_bi4_sha256"], f"{tag} BI4 input hash")
    require(binding.get("gencase_attempt_id") == record.get("attempt_id"), f"{tag} binding GenCase attempt")
    require(binding.get("gencase_receipt") == record.get("receipt_path"), f"{tag} binding receipt")
    require(binding.get("generated_xml") == record.get("generated_xml") and binding.get("generated_bi4") == record.get("generated_bi4"), f"{tag} binding outputs")
    require(binding.get("actual_counts") == expected and binding.get("expected_counts") == expected, f"{tag} binding counts")
    require(binding.get("native_bed_marker_mk") == 50 and binding.get("source_bed_marker_mkbound") == 40, f"{tag} binding marker mapping")
    require(binding.get("official_particle_csv") is None, f"{tag} binding future CSV")


def main() -> int:
    validate_manifest()
    validate_scripts()
    plan = load(PKG / "metadata/fresh113-source-plan.json")
    provenance = load(PKG / "metadata/fresh113-gencase-producer-provenance.json")
    require(plan.get("schema") == "ds02.f5.c082s1.fresh113-source-plan.v1", "plan schema")
    require(plan.get("candidate_count") == 6 and plan.get("candidate_tags") == list(TAGS), "candidate set")
    require(plan.get("full_event_window") == {"tmax_s": 24.0, "tout_s": 0.02, "frames": 1201}, "full window")
    require(plan.get("native_initial_qa_requests_disabled") is True and plan.get("execution_allowed") is False, "QA disabled")
    require(plan.get("future_initial_qa_reports_null") is True, "future QA outputs")
    require(plan.get("fresh111_gate_status") == "WAIT/null" and plan.get("root511_short_window_can_authorize_new_full1201") is False, "full gate")
    require(provenance.get("schema") == "ds02.f5.c082s1.fresh113-gencase-producer-provenance.v1", "provenance schema")
    require(provenance.get("candidate_count") == 6, "provenance candidate count")
    require(provenance.get("fresh110_commit") == FRESH110_COMMIT and provenance.get("fresh111_commit") == FRESH111_COMMIT and provenance.get("fresh112_commit") == FRESH112_COMMIT, "upstream commits")
    require(provenance.get("future_initial_qa_report_sha256") is None and provenance.get("future_typed_h5_sha256") is None, "future hashes")
    require(provenance.get("bi4_csv_dat_h5_vtk_payloads_read_or_hashed_by_source_agent") is False, "payload provenance")
    gate = validate_gate()
    records = provenance.get("candidates", [])
    require(isinstance(records, list) and len(records) == 6, "producer records")
    by_tag = {record.get("tag"): record for record in records}
    require(set(by_tag) == set(TAGS), "producer tags")
    for tag in TAGS:
        validate_producer(tag, by_tag[tag])
        validate_candidate(tag, by_tag[tag], gate)
    report = {
        "schema": "ds02.f5.c082s1.fresh113-validator-report.v1",
        "status": "passed_six_root544_gencase_metadata_bound_native_initial_qa_disabled_full1201_gate_wait",
        "candidate_count": 6,
        "producer_completed0_count": sum(record.get("status") == "completed/0" for record in records),
        "native_initial_qa_disabled": True,
        "full1201_authorized": False,
        "future_initial_qa_hashes_null": True,
        "science_payloads_read_or_hashed_by_validator": False,
        "bi4_csv_dat_h5_vtk_payloads_read_or_hashed_by_validator": False,
        "jobs_started": False,
        "shared_state_modified": False,
    }
    (PKG / "metadata/fresh113-validator-report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "candidate_count": 6, "producer_completed0_count": report["producer_completed0_count"], "full1201_authorized": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
