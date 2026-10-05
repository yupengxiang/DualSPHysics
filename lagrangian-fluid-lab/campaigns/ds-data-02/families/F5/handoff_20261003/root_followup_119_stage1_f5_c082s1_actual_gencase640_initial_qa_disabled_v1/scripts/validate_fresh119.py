#!/usr/bin/env python3
"""Validate fresh119 without reading scientific payloads or launching work.

Only source JSON/XML/Python/text and Root644 JSON review metadata are read.
Generated BI4/XML, receipt/report paths, CSV, DAT, H5, VTK and solver outputs
are checked through producer-attested metadata and are never opened here.
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any

PKG = Path(__file__).resolve().parents[1]
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
LAB = INTEGRATION / "lagrangian-fluid-lab"
FRESH118 = Path("/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_118_stage1_f5_c082s1_first24_cpu_contract_disabled_v1")
ROOT142 = LAB / "campaigns/ds-data-02/handoff_20261003/root_stage1_home_floor_inventory_dispatch_142"
POLICY = ROOT142 / "root_home_floor_inventory_policy.py"
LAUNCH = ROOT142 / "launch.py"
RESOURCE = LAB / "campaigns/ds-data-02/handoff_20261003/root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json"
QA_WRAPPER = LAB / "campaigns/ds-data-02/handoff_20261003/root_stage1_f5_actualGen426_two_registered_initialQA_fresh103_441/export_then_fresh103_placement_qa.py"
QA_WORKER = LAB / "campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_103_stage1_f5_c082s1_typed_xmf_bed_binding_disabled_v1/workers/initial_placement_mk50_audit.py"
PYTHON = LAB / ".venv/bin/python"
PARTVTK = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64")
CASE = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1"
TAGS = tuple(f"M{amp:03d}_T{time:03d}" for amp in (85, 95, 105, 115) for time in (80, 90, 100, 120))
SOURCE_SUFFIXES = {".json", ".py", ".xml", ".md", ".txt", ".log"}
SCIENCE_SUFFIXES = {".dat", ".bi4", ".h5", ".hdf5", ".csv", ".vtk", ".vtu", ".npy", ".npz"}
REVIEW = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f5_actualGen640_16_independent_review_644/actual-root16-GenCase-independent-review.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"JSON object required: {path}")
    return value


def sha_text(path: Path) -> str:
    require(path.suffix.lower() in SOURCE_SUFFIXES, f"non-source hash requested: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalized(row: dict[str, Any]) -> dict[str, Any]:
    counts = row["actual_counts"]
    return {
        "data2d": False,
        "fixed_particles": counts["fixed"],
        "floating_particles": counts["floating"],
        "fluid_particles": counts["fluid"],
        "moving_particles": counts["moving"],
        "solver_dimension": 3,
        "total_particles": row["actual_total_particles"],
    }


def review_rows() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    review = load(REVIEW)
    require(review.get("status") == "actual16_genuineGen640_completed0", "Root644 review status")
    require(review.get("actual_counts_by_generated_report") is True, "Root644 report check")
    require(review.get("science_DIGESTs_from_registered_producers") is True, "Root644 digest provenance")
    require(review.get("main_science_read_or_hash") is False, "Root644 science provenance")
    rows = review.get("cases")
    require(isinstance(rows, list) and len(rows) == 16, "Root644 rows")
    by_tag: dict[str, dict[str, Any]] = {}
    for row in rows:
        tag = row["candidate_id"].split("C082S1_MOTION_", 1)[1]
        require(tag in TAGS and tag not in by_tag, f"Root644 tag {tag}")
        require(row.get("full_native_gate") == "WAIT two Root635 all801 mainvisual", f"{tag} Root644 gate")
        require(normalized(row)["total_particles"] == sum(normalized(row)[key] for key in ("fixed_particles", "moving_particles", "floating_particles", "fluid_particles")), f"{tag} count sum")
        by_tag[tag] = row
    require(set(by_tag) == set(TAGS), "Root644 tag set")
    return review, by_tag


def check_manifest() -> int:
    manifest = load(PKG / "manifest.json")
    require(manifest.get("schema") == "ds02.f5.c082s1.fresh119-source-manifest.v1", "manifest schema")
    require(manifest.get("validator_report_excluded_from_manifest") is True, "manifest validator exclusion")
    require(manifest.get("fresh118_modified") is False and manifest.get("root640_modified") is False and manifest.get("root644_modified") is False, "upstream mutation flags")
    require(manifest.get("native_initial_qa_requests_disabled") is True and manifest.get("full801_authorized") is False, "manifest gate")
    files = manifest.get("files")
    require(isinstance(files, dict) and files, "manifest files")
    require("metadata/fresh119-validator-report.json" not in files, "validator self-reference")
    for rel, expected in files.items():
        path = PKG / rel
        require(path.is_file(), f"manifest missing {rel}")
        require(path.suffix.lower() in SOURCE_SUFFIXES and path.suffix.lower() not in SCIENCE_SUFFIXES, f"manifest non-source {rel}")
        require(sha_text(path) == expected, f"manifest hash mismatch {rel}")
    return len(files)


def check_gate(value: Any, label: str) -> None:
    require(isinstance(value, dict), f"{label} gate object")
    require(value.get("status") == "WAIT/null", f"{label} gate status")
    require(value.get("required_current_cases") == ["A080", "A120"], f"{label} gate cases")
    require(value.get("requires_actual_all801_bed_audit") is True and value.get("requires_root_visual_pass") is True, f"{label} gate requirements")
    require(value.get("historical_root610_failure_preserved") is True, f"{label} historical failure")
    require(value.get("root635_full801_render_receipt") is None and value.get("root635_full801_render_sha256") is None, f"{label} future Root635")
    require(value.get("future_authorization_receipt") is None and value.get("future_authorization_sha256") is None, f"{label} future authorization")
    require(value.get("new_full_native_enablement") is False, f"{label} full authorization")


def check_closure(req: dict[str, Any], row: dict[str, Any], binding_path: Path, review_sha: str, tag: str) -> None:
    files = req.get("input_files")
    hashes = req.get("input_sha256")
    provenance = req.get("input_sha256_provenance")
    require(isinstance(files, list) and isinstance(hashes, dict) and isinstance(provenance, dict), f"{tag} closure shape")
    require(set(files) == set(hashes) == set(provenance), f"{tag} closure keys")
    adapter_path = PKG / "bindings" / f"{tag}-actual-gencase-adapter.json"
    actual_json = {row["request"]: row["request_sha256"], row["binding"]: row["binding_sha256"], str(adapter_path): sha_text(adapter_path), row["receipt"]: row["receipt_sha256"], row["prepared_report"]: row["prepared_report_sha256"]}
    attested = {row["generated_xml"]: row["generated_xml_sha256"], row["generated_bi4"]: row["generated_bi4_producer_sha256"]}
    for raw in files:
        if raw.startswith("<root-bind:"):
            require(hashes[raw] is None, f"{tag} future placeholder hash")
            continue
        path = Path(raw)
        if raw == str(Path(row["receipt"]).parent):
            require(hashes[raw] is None and path.is_dir(), f"{tag} output root closure")
            continue
        if raw in actual_json:
            require(hashes[raw] == actual_json[raw], f"{tag} producer JSON attestation {raw}")
            require("producer" in str(provenance[raw]).lower() or "root640" in str(provenance[raw]).lower(), f"{tag} producer JSON provenance")
            continue
        if raw in attested:
            require(hashes[raw] == attested[raw], f"{tag} producer payload attestation {raw}")
            require("producer" in str(provenance[raw]).lower(), f"{tag} payload attestation provenance")
            # Do not read generated XML or BI4 here.
            continue
        if raw == str(REVIEW):
            require(hashes[raw] == review_sha and sha_text(path) == review_sha, f"{tag} Root644 review metadata hash")
            continue
        if path.suffix.lower() in SCIENCE_SUFFIXES:
            raise ValueError(f"{tag} unregistered science payload in closure: {raw}")
        if path == PYTHON or path == PARTVTK:
            require(hashes[raw] is None, f"{tag} binary hash must remain null")
            continue
        require(path.is_file(), f"{tag} source input missing: {raw}")
        require(path.suffix.lower() in SOURCE_SUFFIXES, f"{tag} unsupported source input: {raw}")
        require(isinstance(hashes[raw], str) and len(hashes[raw]) == 64 and sha_text(path) == hashes[raw], f"{tag} source hash mismatch: {raw}")


def check_tag(tag: str, row: dict[str, Any], review_sha: str) -> dict[str, Any]:
    req_path = PKG / "requests" / f"{tag}-initial-placement-mk50-request.json"
    binding_path = PKG / "bindings" / f"{tag}-initial-qa-mk50-binding.json"
    req = load(req_path)
    binding = load(binding_path)
    adapter_path = PKG / "bindings" / f"{tag}-actual-gencase-adapter.json"
    adapter = load(adapter_path)
    adapter_sha = sha_text(adapter_path)
    expected = normalized(row)
    require(req.get("schema") == "ds02.runner-request.v2", f"{tag} request schema")
    require(binding.get("schema") == "ds02.f5.c082s1.stage1-placement-mk50-binding.fresh103.v1", f"{tag} worker schema")
    require(req.get("binding") == str(binding_path) and req.get("binding_sha256") == sha_text(binding_path), f"{tag} binding closure")
    require(req.get("case_id") == CASE and binding.get("case_id") == CASE, f"{tag} case identity")
    require(req.get("candidate_id") == row["candidate_id"] and binding.get("candidate_id") == row["candidate_id"], f"{tag} candidate identity")
    require(req.get("kind") == "cpu" and req.get("cpu_task_kind") == "audit", f"{tag} CPU audit contract")
    require(req.get("command") == [str(PYTHON), str(QA_WRAPPER), "--binding", str(binding_path), "--partvtk", str(PARTVTK), "--audit-worker", str(QA_WORKER), "--output-dir", "{attempt_root}/initial-qa"], f"{tag} Root441/fresh103 command")
    require(req.get("cwd") == str(LAB) and req.get("worktree_root") == str(INTEGRATION), f"{tag} cwd/worktree")
    for key in ("disabled", "execution_allowed", "launch", "launch_allowed", "solver_allowed", "conversion_allowed", "arrays_allowed", "array_edit_allowed"):
        expected_gate = True if key == "disabled" else False
        require(req.get(key) is expected_gate, f"{tag} gate {key}")
    require(req.get("full801_authorized") is False and req.get("q_n_granted") is False and req.get("independent_case_count_increment") == 0, f"{tag} acceptance gate")
    require(req.get("gencase_attempt_id") == Path(row["receipt"]).parent.name and req.get("depends_on_attempt") == Path(row["receipt"]).parent.name, f"{tag} own GenCase attempt")
    require(binding.get("gencase_attempt_id") == Path(row["receipt"]).parent.name and binding.get("qa_attempt_id") == req.get("attempt_id"), f"{tag} separate identities")
    require(req.get("actual_gencase_binding") == str(adapter_path) and req.get("actual_gencase_binding_sha256") == adapter_sha, f"{tag} adapter request binding")
    require(binding.get("gencase_binding") == str(adapter_path) and binding.get("gencase_binding_sha256") == adapter_sha, f"{tag} adapter QA binding")
    require(binding.get("gencase_source_binding") == row["binding"] and binding.get("gencase_source_binding_sha256") == row["binding_sha256"], f"{tag} original Root640 binding preservation")
    require(adapter.get("schema") == "ds02.f5.c082s1.actual-gencase640-producer-adapter.fresh119.v1", f"{tag} adapter schema")
    require(adapter.get("source_binding") == row["binding"] and adapter.get("source_binding_sha256") == row["binding_sha256"], f"{tag} adapter source preservation")
    require(adapter.get("attempt_id") == Path(row["receipt"]).parent.name and adapter.get("actual_counts") == expected, f"{tag} adapter identity/counts")
    for obj, label in ((req, "request"), (binding, "binding")):
        require(obj.get("actual_counts") == expected, f"{tag} {label} actual counts")
        require(obj.get("expected_counts") == expected, f"{tag} {label} expected counts")
        require(obj.get("generated_xml") == row["generated_xml"] and obj.get("generated_xml_sha256") == row["generated_xml_sha256"], f"{tag} {label} XML producer binding")
        require(obj.get("generated_bi4") == row["generated_bi4"] and obj.get("generated_bi4_sha256") == row["generated_bi4_producer_sha256"], f"{tag} {label} BI4 producer binding")
        require(obj.get("gencase_receipt") == row["receipt"] and obj.get("gencase_receipt_sha256") == row["receipt_sha256"], f"{tag} {label} receipt binding")
        require(obj.get("prepared_input_report") == row["prepared_report"] and obj.get("prepared_input_report_sha256") == row["prepared_report_sha256"], f"{tag} {label} report binding")
        require(obj.get("official_particle_csv") == "<root-bind:official_particle_csv>" and obj.get("official_particle_csv_sha256") is None, f"{tag} {label} future CSV")
    producer = binding.get("gencase_producer", {})
    require(producer.get("completed0") is True and producer.get("status") == "completed/0", f"{tag} producer completed0")
    require(producer.get("binding") == str(adapter_path) and producer.get("binding_sha256") == adapter_sha, f"{tag} producer adapter binding")
    require(producer.get("attempt_id") == Path(row["receipt"]).parent.name and producer.get("actual_counts") == expected, f"{tag} producer identity/counts")
    require(producer.get("producer_review") == str(REVIEW) and producer.get("producer_review_sha256") == review_sha, f"{tag} review provenance")
    checks = binding.get("native_initial_checks", {})
    require(checks.get("native_bed_mk") == 50 and checks.get("source_mkbound") == 40 and checks.get("required_native_3d") is True, f"{tag} Mk/3D checks")
    require(checks.get("required_transverse_y_levels") == 15 and checks.get("required_unique_finite_uid") is True and checks.get("required_initial_fluid_velocity_zero") is True, f"{tag} initial checks")
    profile = checks.get("bed_penetration_profile", {})
    require(profile.get("one_dp_depth_m") == 0.02 and profile.get("two_dp_depth_m") == 0.04 and profile.get("all_fluid_denominator") is True, f"{tag} bed profile")
    precision = checks.get("exact_dp_lattice_precision", {})
    require(precision.get("diagnostic_only") is True and precision.get("no_threshold_relaxation") is True and precision.get("accepted_as_stage1_placement_gate") is False, f"{tag} precision boundary")
    check_gate(req.get("upstream_full801_visual_gate"), f"{tag} request")
    check_gate(binding.get("upstream_full801_visual_gate"), f"{tag} binding")
    check_closure(req, row, binding_path, review_sha, tag)
    future = req.get("future_output_hashes")
    require(isinstance(future, dict) and all(value is None for value in future.values()), f"{tag} future QA hashes")
    return {"tag": tag, "gencase_attempt_id": Path(row["receipt"]).parent.name, "qa_attempt_id": req["attempt_id"], "actual_counts": expected}


def main() -> int:
    manifest_count = check_manifest()
    for path in list((PKG / "scripts").glob("*.py")):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    science_files = [str(path.relative_to(PKG)) for path in PKG.rglob("*") if path.is_file() and path.suffix.lower() in SCIENCE_SUFFIXES]
    require(not science_files, f"science files in package: {science_files}")
    review, rows = review_rows()
    review_sha = sha_text(REVIEW)
    provenance = load(PKG / "metadata/fresh119-gencase640-independent-review.json")
    require(provenance.get("source_review") == str(REVIEW) and provenance.get("source_review_sha256") == review_sha, "provenance review")
    require(provenance.get("candidate_count") == 16 and provenance.get("source_agent_did_not_read_or_hash_science_payloads") is True, "provenance summary")
    check_gate(provenance.get("full_native_gate"), "provenance")
    plan = load(PKG / "metadata/fresh119-source-plan.json")
    require(plan.get("candidate_count") == 16 and plan.get("candidate_tags") == list(TAGS), "source plan candidates")
    require(plan.get("gencase640_status") == "completed/0" and plan.get("gencase640_receipts_bound") is True, "source plan GenCase")
    require(plan.get("native_initial_qa_requests_disabled") is True and plan.get("execution_allowed") is False, "source plan QA gate")
    require(plan.get("full801_authorized") is False and plan.get("q_n_granted") is False and plan.get("independent_case_count_increment") == 0, "source plan acceptance")
    check_gate(plan.get("full_native_gate"), "source plan")
    audit = load(PKG / "metadata/fresh119-contract-audit.json")
    require(audit.get("source_agent_did_not_read_or_hash_science_payloads") is True and audit.get("jobs_started") is False and audit.get("shared_state_modified") is False, "contract audit provenance")
    require(audit.get("unchanged_worker_contracts", {}).get("wrapper") == str(QA_WRAPPER) and audit.get("unchanged_worker_contracts", {}).get("worker") == str(QA_WORKER), "worker provenance")
    results = [check_tag(tag, rows[tag], review_sha) for tag in TAGS]
    report = {
        "schema": "ds02.f5.c082s1.fresh119-validator-report.v1",
        "status": "passed_root644_16_gencase_rows_bound_disabled_native_initial_mk50_qa",
        "manifest_source_files": manifest_count,
        "candidate_count": 16,
        "gencase640_completed0_rows_checked": 16,
        "native_initial_qa_requests_disabled": True,
        "full801_authorized": False,
        "future_native_qa_hashes_null": True,
        "actual_counts_source": "Root644 generated-report rows per candidate",
        "actual_counts_not_historical_assumptions": True,
        "root441_and_fresh103_worker_contract_checked": True,
        "source_mkbound": 40,
        "native_bed_mk": 50,
        "exact_dp_lattice_negative_retained": True,
        "historical_A_B_penetration_failures_retained": True,
        "science_payloads_read_or_hashed_by_validator": False,
        "bi4_csv_dat_h5_vtk_payloads_read_or_hashed_by_validator": False,
        "jobs_started": False,
        "shared_state_modified": False,
        "results": results,
    }
    (PKG / "metadata/fresh119-validator-report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "candidate_count": 16, "gencase640_completed0_rows_checked": 16, "science_payloads_read_or_hashed_by_validator": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
