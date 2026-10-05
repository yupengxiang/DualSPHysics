#!/usr/bin/env python3
"""Build the F5 fresh119 downstream adapter from Root644 JSON metadata.

This builder consumes only JSON metadata and source text.  It never opens or
hashes BI4, CSV, DAT, H5, VTK, or solver payloads.  Root644's producer
attestations are copied as upstream evidence; the native initial QA request
stays disabled until Root enables it.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

CASE = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1"
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
LAB = INTEGRATION / "lagrangian-fluid-lab"
F5_WT = Path("/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics")
FRESH118 = F5_WT / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_118_stage1_f5_c082s1_first24_cpu_contract_disabled_v1"
REVIEW = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f5_actualGen640_16_independent_review_644/actual-root16-GenCase-independent-review.json"
DATA_CASE = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1")
PYTHON = LAB / ".venv/bin/python"
RUNTIME = LAB / "scripts/ds_data02_runtime_v2.py"
STRICT = LAB / "scripts/ds_data02_strict_dispatch_v1.py"
ROOT142 = LAB / "campaigns/ds-data-02/handoff_20261003/root_stage1_home_floor_inventory_dispatch_142"
POLICY = ROOT142 / "root_home_floor_inventory_policy.py"
LAUNCH = ROOT142 / "launch.py"
RESOURCE = LAB / "campaigns/ds-data-02/handoff_20261003/root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json"
QA_WRAPPER = LAB / "campaigns/ds-data-02/handoff_20261003/root_stage1_f5_actualGen426_two_registered_initialQA_fresh103_441/export_then_fresh103_placement_qa.py"
QA_WORKER = LAB / "campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_103_stage1_f5_c082s1_typed_xmf_bed_binding_disabled_v1/workers/initial_placement_mk50_audit.py"
PARTVTK = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64")
SOURCE_SUFFIXES = {".json", ".py", ".xml", ".md", ".txt", ".log"}
SCIENCE_SUFFIXES = {".dat", ".bi4", ".h5", ".hdf5", ".csv", ".vtk", ".vtu", ".npy", ".npz"}
TAGS = tuple(f"M{amp:03d}_T{time:03d}" for amp in (85, 95, 105, 115) for time in (80, 90, 100, 120))


def sha(path: Path) -> str:
    if path.suffix.lower() in SCIENCE_SUFFIXES:
        raise ValueError(f"science payload hash forbidden: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def producer_rows() -> tuple[dict[str, Any], dict[str, Any]]:
    review = load(REVIEW)
    require(review.get("status") == "actual16_genuineGen640_completed0", "Root644 review status")
    require(review.get("actual_counts_by_generated_report") is True, "Root644 report-count attestation")
    require(review.get("science_DIGESTs_from_registered_producers") is True, "Root644 producer digest attestation")
    require(review.get("main_science_read_or_hash") is False, "Root644 science provenance")
    cases = review.get("cases")
    require(isinstance(cases, list) and len(cases) == len(TAGS), "Root644 case count")
    by_tag: dict[str, Any] = {}
    for row in cases:
        require(isinstance(row, dict), "Root644 case row")
        candidate = row.get("candidate_id", "")
        require(candidate.startswith("C082S1_MOTION_"), f"candidate identity: {candidate}")
        tag = candidate.split("C082S1_MOTION_", 1)[1]
        require(tag in TAGS and tag not in by_tag, f"candidate tag: {tag}")
        counts = row.get("actual_counts")
        require(isinstance(counts, dict), f"{tag}: actual counts")
        require(all(isinstance(counts.get(key), int) for key in ("fixed", "moving", "floating", "fluid")), f"{tag}: integer counts")
        total = row.get("actual_total_particles")
        require(isinstance(total, int) and total == sum(counts[key] for key in ("fixed", "moving", "floating", "fluid")), f"{tag}: producer total")
        for key in ("generated_xml_sha256", "generated_bi4_producer_sha256", "prepared_report_sha256", "receipt_sha256", "request_sha256", "binding_sha256", "actual_motion_producer_sha256"):
            value = row.get(key)
            require(isinstance(value, str) and len(value) == 64, f"{tag}: missing producer digest {key}")
        for key in ("generated_xml", "generated_bi4", "prepared_report", "receipt", "request", "binding", "physical_case_id", "physical_condition_sha256"):
            require(isinstance(row.get(key), str) and row[key], f"{tag}: missing producer path {key}")
        require(row.get("full_native_gate") == "WAIT two Root635 all801 mainvisual", f"{tag}: full-native gate")
        attempt = Path(row["receipt"]).parent.name
        require(attempt.endswith("-root640"), f"{tag}: actual GenCase attempt")
        by_tag[tag] = {
            "tag": tag,
            "candidate_id": candidate,
            "physical_case_id": row["physical_case_id"],
            "physical_condition_sha256": row["physical_condition_sha256"],
            "attempt_id": attempt,
            "binding": row["binding"],
            "binding_sha256": row["binding_sha256"],
            "request": row["request"],
            "request_sha256": row["request_sha256"],
            "receipt": row["receipt"],
            "receipt_sha256": row["receipt_sha256"],
            "prepared_report": row["prepared_report"],
            "prepared_report_sha256": row["prepared_report_sha256"],
            "generated_xml": row["generated_xml"],
            "generated_xml_sha256": row["generated_xml_sha256"],
            "generated_bi4": row["generated_bi4"],
            "generated_bi4_sha256": row["generated_bi4_producer_sha256"],
            "output_root": str(Path(row["receipt"]).parent),
            "motion_producer_sha256": row["actual_motion_producer_sha256"],
            "actual_counts": {
                "data2d": False,
                "fixed_particles": counts["fixed"],
                "floating_particles": counts["floating"],
                "fluid_particles": counts["fluid"],
                "moving_particles": counts["moving"],
                "solver_dimension": 3,
                "total_particles": total,
            },
        }
    require(set(by_tag) == set(TAGS), "Root644 complete tag set")
    return review, by_tag


def gate() -> dict[str, Any]:
    return {
        "status": "WAIT/null",
        "reason": "Root610 was preserved as reserved_cpu_budget_exceeded at frames 452/453; Root635 retry must finish full801 render and Root visual review",
        "required_current_cases": ["A080", "A120"],
        "requires_actual_all801_bed_audit": True,
        "requires_root_visual_pass": True,
        "historical_root610_failure_preserved": True,
        "root635_full801_render_receipt": None,
        "root635_full801_render_sha256": None,
        "future_authorization_receipt": None,
        "future_authorization_sha256": None,
        "new_full_native_enablement": False,
    }


def static_inputs(tag: str, source_request: dict[str, Any], binding_path: Path, row: dict[str, Any], review_path: Path, review_sha: str) -> tuple[list[str], dict[str, Any], dict[str, Any]]:
    source_definition = Path(source_request["source_definition"])
    source_owner = Path(source_request["source_owner"])
    source_physical = Path(source_request["physical_binding"])
    actual_request = Path(row["request"])
    actual_binding = Path(row["binding"])
    files = [
        str(PYTHON), str(RUNTIME), str(STRICT), str(POLICY), str(LAUNCH), str(RESOURCE),
        str(source_definition), str(source_owner), str(source_physical), str(binding_path),
        str(QA_WRAPPER), str(QA_WORKER), str(PARTVTK),
        str(actual_request), str(actual_binding), str(review_path),
        row["receipt"], row["prepared_report"], row["generated_xml"], row["generated_bi4"],
        row["output_root"], "<root-bind:official_particle_csv>",
    ]
    hashes: dict[str, Any] = {}
    provenance: dict[str, Any] = {}
    source_static = [PYTHON, RUNTIME, STRICT, POLICY, LAUNCH, RESOURCE, source_definition, source_owner, source_physical, binding_path, QA_WRAPPER, QA_WORKER, PARTVTK]
    for path in source_static:
        text = str(path)
        if path in (PYTHON, PARTVTK):
            hashes[text] = None
            provenance[text] = "registered executable; source preparation did not open or hash binary"
        else:
            hashes[text] = sha(path)
            provenance[text] = "immutable source JSON/XML/Python metadata hash; no scientific payload read"
    hashes[str(actual_request)] = row["request_sha256"]
    provenance[str(actual_request)] = "Root640 genuine GenCase request JSON metadata; source did not read scientific payload"
    hashes[str(actual_binding)] = row["binding_sha256"]
    provenance[str(actual_binding)] = "Root640 genuine GenCase binding JSON metadata; source did not read scientific payload"
    hashes[str(review_path)] = review_sha
    provenance[str(review_path)] = "Root644 independent review JSON metadata; producer digests copied without payload access"
    for key, label in (("receipt", "execution-receipt.json"), ("prepared_report", "prepared-input-report.json")):
        hashes[row[key]] = row[f"{key}_sha256"]
        provenance[row[key]] = f"Root644/Root640 producer {label} JSON metadata attestation; source did not read scientific payload"
    hashes[row["generated_xml"]] = row["generated_xml_sha256"]
    provenance[row["generated_xml"]] = "Root644 generated-report producer XML digest; source did not read or rehash generated XML"
    hashes[row["generated_bi4"]] = row["generated_bi4_sha256"]
    provenance[row["generated_bi4"]] = "Root644 generated-report producer BI4 digest; source did not read or rehash BI4"
    hashes[row["output_root"]] = None
    provenance[row["output_root"]] = "Root640 producer output directory; directory is a future worker input root and is not hashed"
    hashes["<root-bind:official_particle_csv>"] = None
    provenance["<root-bind:official_particle_csv>"] = "Root441 wrapper future CSV export; source preparation does not read or hash CSV"
    require(set(files) == set(hashes) == set(provenance), f"{tag}: input closure")
    return files, hashes, provenance


def initial_checks() -> dict[str, Any]:
    return {
        "source_of_truth": "registered Root-owned native BI4/official PartVTK worker; no GenCase CSV substitution",
        "required_total_uid_rows": True,
        "required_unique_finite_uid": True,
        "required_type_and_mk_fields": True,
        "required_native_3d": True,
        "required_initial_fluid_velocity_zero": True,
        "native_bed_mk": 50,
        "source_mkbound": 40,
        "central_mk50_support_required": True,
        "required_transverse_y_levels": 15,
        "fluid_below_analytic_profile_must_be_zero": True,
        "no_initial_spatial_overlap": True,
        "bed_penetration_profile": {
            "footprint": "exact C082S1 analytic bed profile and source x/y domain",
            "one_dp_depth_m": 0.02,
            "two_dp_depth_m": 0.04,
            "all_fluid_denominator": True,
            "frame_scope": "native initial state only",
        },
        "exact_dp_lattice_precision": {
            "diagnostic_only": True,
            "threshold_cells": 1e-6,
            "historical_observed_max_cells": 5.0000000158e-6,
            "no_threshold_relaxation": True,
            "accepted_as_stage1_placement_gate": False,
        },
    }


def build(package: Path, validator_source: Path) -> None:
    require(not package.exists(), f"fresh119 target already exists: {package}")
    package.mkdir(parents=True)
    for name in ("bindings", "requests", "metadata", "scripts"):
        (package / name).mkdir()
    shutil.copy2(Path(__file__), package / "scripts/build_fresh119.py")
    shutil.copy2(validator_source, package / "scripts/validate_fresh119.py")

    review, rows = producer_rows()
    review_sha = sha(REVIEW)
    upstream_gate = gate()
    provenance_rows = []
    request_records = []
    for tag in TAGS:
        row = rows[tag]
        source_req = load(FRESH118 / "requests" / f"{tag}-initial-placement-mk50-request.json")
        source_binding = load(FRESH118 / "bindings" / f"{tag}-initial-qa-mk50-binding.json")
        source_binding_path = FRESH118 / "bindings" / f"{tag}-initial-qa-mk50-binding.json"
        binding_path = package / "bindings" / f"{tag}-initial-qa-mk50-binding.json"
        request_path = package / "requests" / f"{tag}-initial-placement-mk50-request.json"
        qa_attempt = f"root-stage1-f5-c082s1-{tag.lower()}-actual-initial-placement-mk50-119"
        counts = row["actual_counts"]
        source_gencase_binding_path = Path(row["binding"])
        source_gencase_binding = load(source_gencase_binding_path)
        adapter_path = package / "bindings" / f"{tag}-actual-gencase-adapter.json"
        adapter = copy.deepcopy(source_gencase_binding)
        adapter_counts = {"data2d": False, "fixed_particles": counts["fixed_particles"], "floating_particles": counts["floating_particles"], "fluid_particles": counts["fluid_particles"], "moving_particles": counts["moving_particles"], "solver_dimension": 3, "total_particles": counts["total_particles"]}
        adapter.update({"schema": "ds02.f5.c082s1.actual-gencase640-producer-adapter.fresh119.v1", "source_binding": str(source_gencase_binding_path), "source_binding_sha256": row["binding_sha256"], "actual_gencase_request": row["request"], "actual_gencase_request_sha256": row["request_sha256"], "actual_gencase_review": str(REVIEW), "actual_gencase_review_sha256": review_sha, "producer_status": "completed/0", "completed0": True, "actual_counts": adapter_counts, "expected_counts": adapter_counts, "expected_fluid": counts["fluid_particles"], "solver_dimension": 3, "generated_xml": row["generated_xml"], "generated_xml_sha256": row["generated_xml_sha256"], "generated_bi4": row["generated_bi4"], "generated_bi4_sha256": row["generated_bi4_sha256"], "gencase_receipt": row["receipt"], "gencase_receipt_sha256": row["receipt_sha256"], "prepared_input_report": row["prepared_report"], "prepared_input_report_sha256": row["prepared_report_sha256"], "gencase_output_root": row["output_root"], "actual_motion_producer_sha256": row["motion_producer_sha256"], "source_agent_did_not_read_or_hash_science_payloads": True, "status": "producer_metadata_adapter_only"})
        dump(adapter_path, adapter)
        adapter_sha = sha(adapter_path)
        binding = copy.deepcopy(source_binding)
        binding.update({
            "schema": "ds02.f5.c082s1.stage1-placement-mk50-binding.fresh103.v1",
            "adapter_schema": "ds02.f5.c082s1.actual-gencase640-bound-initial-mk50-adapter.fresh119.v1",
            "adapter_source": "fresh119 Root644 metadata-only adapter",
            "case_id": CASE,
            "candidate_id": row["candidate_id"],
            "qa_attempt_id": qa_attempt,
            "gencase_attempt_id": row["attempt_id"],
            "gencase_binding": str(adapter_path),
            "gencase_binding_sha256": adapter_sha,
            "gencase_source_binding": str(source_gencase_binding_path),
            "gencase_source_binding_sha256": row["binding_sha256"],
            "actual_gencase_binding": str(adapter_path),
            "actual_gencase_binding_sha256": adapter_sha,
            "gencase_receipt": row["receipt"],
            "gencase_receipt_sha256": row["receipt_sha256"],
            "prepared_input_report": row["prepared_report"],
            "prepared_input_report_sha256": row["prepared_report_sha256"],
            "generated_xml": row["generated_xml"],
            "generated_xml_sha256": row["generated_xml_sha256"],
            "generated_bi4": row["generated_bi4"],
            "generated_bi4_sha256": row["generated_bi4_sha256"],
            "gencase_output_root": row["output_root"],
            "actual_counts": counts,
            "expected_counts": counts,
            "actual_counts_provenance": "Root644 actual-root16-GenCase-independent-review.json; each row reports Root640 generated-report counts",
            "actual_gencase_review": str(REVIEW),
            "actual_gencase_review_sha256": review_sha,
            "actual_gencase_request": row["request"],
            "actual_gencase_request_sha256": row["request_sha256"],
            "native_initial_checks": initial_checks(),
            "official_particle_csv": "<root-bind:official_particle_csv>",
            "official_particle_csv_sha256": None,
            "full801_authorized": False,
            "q_n_granted": False,
            "source_only": True,
            "source_definition": source_req["source_definition"],
            "source_definition_sha256": source_req["source_definition_sha256"],
            "source_mkbound": 40,
            "native_bed_marker_mk": 50,
            "source_bed_marker_mkbound": 40,
            "no_count_rescaling": True,
            "upstream_full801_visual_gate": upstream_gate,
            "gencase_producer": {
                "status": "completed/0",
                "completed0": True,
                "attempt_id": row["attempt_id"],
                "receipt": row["receipt"],
                "receipt_sha256": row["receipt_sha256"],
                "prepared_input_report": row["prepared_report"],
                "prepared_input_report_sha256": row["prepared_report_sha256"],
                "generated_xml": row["generated_xml"],
                "generated_xml_sha256": row["generated_xml_sha256"],
                "generated_bi4": row["generated_bi4"],
                "generated_bi4_sha256": row["generated_bi4_sha256"],
                "actual_counts": counts,
                "actual_motion_producer_sha256": row["motion_producer_sha256"],
                "producer_review": str(REVIEW),
                "producer_review_sha256": review_sha,
                "binding": str(adapter_path),
                "binding_sha256": adapter_sha,
                "source_binding": str(source_gencase_binding_path),
                "source_binding_sha256": row["binding_sha256"],
                "source_agent_did_not_read_or_hash_science_payloads": True,
            },
            "files": {
                "actual_gencase_binding": {"path": str(adapter_path), "sha256": adapter_sha},
                "gencase_output_root": {"path": row["output_root"], "sha256": None},
                "gencase_receipt": {"path": row["receipt"], "sha256": row["receipt_sha256"]},
                "prepared_input_report": {"path": row["prepared_report"], "sha256": row["prepared_report_sha256"]},
                "generated_xml": {"path": row["generated_xml"], "sha256": row["generated_xml_sha256"]},
                "generated_bi4": {"path": row["generated_bi4"], "sha256": row["generated_bi4_sha256"]},
                "official_particle_csv": {"path": "<root-bind:official_particle_csv>", "sha256": None},
            },
        })
        # Keep the worker's exact required file contract while replacing every producer placeholder.
        dump(binding_path, binding)
        binding_sha = sha(binding_path)
        files, hashes, provenance = static_inputs(tag, source_req, binding_path, row, REVIEW, review_sha)
        files.insert(files.index(str(source_gencase_binding_path)) + 1, str(adapter_path))
        hashes[str(adapter_path)] = adapter_sha
        provenance[str(adapter_path)] = "fresh119 producer metadata adapter JSON; actual counts and producer attestations copied from Root644, no science payload read"
        request = copy.deepcopy(source_req)
        command = list(request["command"])
        command = [str(binding_path) if value == str(source_binding_path) else value for value in command]
        request.update({
            "schema": "ds02.runner-request.v2",
            "attempt_id": qa_attempt,
            "binding": str(binding_path),
            "binding_sha256": binding_sha,
            "candidate_id": row["candidate_id"],
            "case_id": CASE,
            "condition_id": source_req["condition_id"],
            "command": command,
            "kind": "cpu",
            "cpu_task_kind": "audit",
            "cwd": str(LAB),
            "worktree_root": str(INTEGRATION),
            "disabled": True,
            "execution_allowed": False,
            "launch": False,
            "launch_allowed": False,
            "solver_allowed": False,
            "conversion_allowed": False,
            "arrays_allowed": False,
            "array_edit_allowed": False,
            "status": "disabled_until_root_review_and_native_initial_mk50_worker_registration",
            "purpose": "native initial UID/type/Mk50/finite/3D and analytic-bed 1DP/2DP audit from Root640 producer; exact-DP precision remains independent",
            "worker_kind": "Root441 export_then_fresh103 placement/Mk50 wrapper; Root-owned native producer required",
            "genuine_gencase": True,
            "genuine_gencase_required": True,
            "gencase_attempt_id": row["attempt_id"],
            "depends_on_attempt": row["attempt_id"],
            "gencase_receipt": row["receipt"],
            "gencase_receipt_sha256": row["receipt_sha256"],
            "prepared_input_report": row["prepared_report"],
            "prepared_input_report_sha256": row["prepared_report_sha256"],
            "generated_xml": row["generated_xml"],
            "generated_xml_sha256": row["generated_xml_sha256"],
            "generated_bi4": row["generated_bi4"],
            "generated_bi4_sha256": row["generated_bi4_sha256"],
            "gencase_output_root": row["output_root"],
            "actual_gencase_binding": str(adapter_path),
            "actual_gencase_binding_sha256": adapter_sha,
            "actual_gencase_source_binding": str(source_gencase_binding_path),
            "actual_gencase_source_binding_sha256": row["binding_sha256"],
            "actual_gencase_review": str(REVIEW),
            "actual_gencase_review_sha256": review_sha,
            "actual_counts": counts,
            "expected_counts": counts,
            "expected_particles": counts["total_particles"],
            "expected_fixed_particles": counts["fixed_particles"],
            "expected_moving_particles": counts["moving_particles"],
            "expected_floating_particles": counts["floating_particles"],
            "expected_fluid_particles": counts["fluid_particles"],
            "expected_dimension": counts["solver_dimension"],
            "actual_counts_provenance": "Root644 actual-root16-GenCase-independent-review.json; each row from Root640 generated report",
            "gencase_producer": binding["gencase_producer"],
            "native_initial_checks": binding["native_initial_checks"],
            "official_particle_csv": "<root-bind:official_particle_csv>",
            "official_particle_csv_sha256": None,
            "input_files": files,
            "input_sha256": hashes,
            "input_sha256_provenance": provenance,
            "future_output_hashes": {key: None for key in request.get("future_output_hashes", {})},
            "upstream_full801_visual_gate": upstream_gate,
            "full801_authorized": False,
            "q_n_granted": False,
            "independent_case_count_increment": 0,
            "source_only": True,
            "root_review_required": True,
            "root_actual_launch_source": str(LAUNCH),
            "root_actual_launch_source_sha256": sha(LAUNCH),
            "root_inventory_policy_source": str(POLICY),
            "root_inventory_policy_source_sha256": sha(POLICY),
            "root_inventory_policy_source_sha256_provenance": "Root142 registered CPU inventory policy; source text hash",
            "resource_window": source_req["resource_window"],
            "native_bed_mk": 50,
            "source_mkbound": 40,
            "required_transverse_y_levels": 15,
            "placement_gate": "basic placement/Mk50 only; exact DP 1e-6 remains an independent numerical diagnostic",
            "binding_contract": {
                "actual_counts_must_be_copied_from_actual_root644_gencase_report": True,
                "actual_gencase_status_must_be_completed0": True,
                "fluid_below_profile_must_be_zero": True,
                "no_count_rescaling": True,
                "no_precision_threshold_relaxation": True,
                "old_precision_negative_preserved": True,
                "require_central_mk50_support": True,
            },
        })
        dump(request_path, request)
        request_records.append({"tag": tag, "binding": str(binding_path), "binding_sha256": binding_sha, "request": str(request_path), "request_sha256": sha(request_path), "gencase_attempt_id": row["attempt_id"], "actual_counts": counts})
        provenance_rows.append({**row, "source_binding": str(source_gencase_binding_path), "source_binding_sha256": row["binding_sha256"], "adapter_binding": str(adapter_path), "adapter_binding_sha256": adapter_sha, "binding_file": str(binding_path), "binding_file_sha256": binding_sha, "request_file": str(request_path), "request_file_sha256": sha(request_path), "qa_attempt_id": qa_attempt, "producer_status": "completed/0"})

    dump(package / "metadata/fresh119-gencase640-independent-review.json", {
        "schema": "ds02.f5.c082s1.fresh119-gencase640-independent-review.v1",
        "source_review": str(REVIEW),
        "source_review_sha256": review_sha,
        "source_review_status": review["status"],
        "actual_counts_by_generated_report": True,
        "science_DIGESTs_from_registered_producers": True,
        "main_science_read_or_hash": False,
        "candidate_count": len(TAGS),
        "cases": provenance_rows,
        "full_native_gate": upstream_gate,
        "source_agent_did_not_read_or_hash_science_payloads": True,
    })
    dump(package / "metadata/fresh119-source-plan.json", {
        "schema": "ds02.f5.c082s1.fresh119-source-plan.v1",
        "candidate_count": len(TAGS),
        "candidate_tags": list(TAGS),
        "upstream_gencase_attempt_family": "Root640 genuine GenCase per-case actual completed/0; Root644 independent report rows",
        "gencase640_status": "completed/0",
        "gencase640_receipts_bound": True,
        "gencase_counts_are_producer_attested": True,
        "actual_counts_are_not_historical_assumptions": True,
        "native_initial_qa_requests_disabled": True,
        "execution_allowed": False,
        "full801_authorized": False,
        "q_n_granted": False,
        "independent_case_count_increment": 0,
        "full_native_gate": upstream_gate,
        "required_native_checks": ["UID/type/Mk/finite/positive weights/density", "native 3D", "zero initial fluid velocity", "no spatial overlap", "native Mk50 central support", "15 transverse y levels", "fluid below analytic bed profile zero", "1DP/2DP native initial bed diagnostics"],
        "exact_dp_lattice_precision_negative_preserved": True,
        "historical_A_B_penetration_failures_preserved": True,
        "future_initial_qa_report_hashes_null": True,
        "source_agent_did_not_read_or_hash_science_payloads": True,
        "jobs_started": False,
        "shared_state_modified": False,
    })
    dump(package / "metadata/fresh119-contract-audit.json", {
        "schema": "ds02.f5.c082s1.fresh119-contract-audit.v1",
        "source_package_parent": str(FRESH118),
        "actual_upstream_review": str(REVIEW),
        "actual_upstream_review_sha256": review_sha,
        "unchanged_worker_contracts": {
            "wrapper": str(QA_WRAPPER),
            "wrapper_sha256": sha(QA_WRAPPER),
            "worker": str(QA_WORKER),
            "worker_sha256": sha(QA_WORKER),
            "wrapper_role": "Root441 exports the actual producer BI4 to official CSV then invokes unchanged fresh103 Mk50 worker",
        },
        "adapter_repairs": [
            "separate actual Root640 GenCase attempt from fresh119 QA attempt",
            "bind actual per-case receipt/report/XML/BI4 producer attestations from Root644",
            "copy actual counts only from the corresponding Root644 generated-report row",
            "retain native Mk40 source-boundary versus native Mk50 bed-marker mapping",
            "retain exact DP 1e-6 diagnostic negative without making it a stage1 gate",
        ],
        "not_changed": ["GenCase worker", "Root441 wrapper", "fresh103 Mk50 worker", "runtime", "strict dispatcher", "science payloads", "old fresh118 bytes"],
        "full_native_gate": upstream_gate,
        "source_agent_did_not_read_or_hash_science_payloads": True,
        "jobs_started": False,
        "shared_state_modified": False,
    })
    dump(package / "README.md", f"""# F5 fresh119: Root640 GenCase to native initial Mk50 QA adapters\n\nRoot644 independently reviewed all 16 Root640 genuine GenCase attempts as completed/0. Each row supplies its own receipt, prepared-input-report, generated XML/BI4 producer attestations, motion producer digest, and actual particle counts. The package binds those metadata rows to disabled native initial placement/Mk50 QA requests.\n\nThe requests use the unchanged Root441 `export_then_fresh103_placement_qa.py` wrapper and the unchanged fresh103 `initial_placement_mk50_audit.py` worker. The worker remains responsible for native BI4/PartVTK evidence: UID/type/Mk/finite and positive weights/density, native 3D, zero initial fluid velocity, no overlap, exact analytic-bed placement, central native Mk50 support, 15 transverse levels, and native 1DP/2DP diagnostics. GenCase CSV is not used as a substitute for native state.\n\nActual counts are producer-attested per case (`fixed=158559`, `moving=4210`, `fluid=31658`, `floating=0`, `total=194427`, 3D); they are not copied from a historical expectation. Initial QA output/CSV/report hashes remain null until Root registers and runs the disabled request. The exact DP lattice threshold of 1e-6 and its historical 5e-6 negative remain a separate diagnostic; no threshold is relaxed.\n\nFull native authorization remains `WAIT/null`: Root610's reserved CPU budget termination at frames 452/453 is preserved, and current A080/A120 full801 retry Root635 still requires actual full801 render plus Root visual pass. This package grants no Q-N, no case credit, and no full801 authorization.\n\nSource preparation read JSON/XML/Python/text metadata only. It did not read or hash BI4, CSV, DAT, H5, VTK, or solver payloads, and it started no job or shared-state write.\n""")
    # The manifest excludes itself and the validator's generated report to avoid self-reference.
    files: dict[str, str] = {}
    report = package / "metadata/fresh119-validator-report.json"
    for path in sorted(package.rglob("*")):
        if not path.is_file() or path == package / "manifest.json" or path == report:
            continue
        require(path.suffix.lower() in SOURCE_SUFFIXES, f"unsupported package file: {path}")
        require(path.suffix.lower() not in SCIENCE_SUFFIXES, f"science package file: {path}")
        files[str(path.relative_to(package))] = sha(path)
    dump(package / "manifest.json", {
        "schema": "ds02.f5.c082s1.fresh119-source-manifest.v1",
        "status": "sixteen_root640_gencase_attested_native_initial_qa_disabled_full801_wait",
        "files": files,
        "validator_report_excluded_from_manifest": True,
        "fresh118_modified": False,
        "root640_modified": False,
        "root644_modified": False,
        "native_initial_qa_requests_disabled": True,
        "full801_authorized": False,
        "q_n_granted": False,
        "independent_case_count_increment": 0,
        "science_payloads_read_or_hashed_by_source_builder": False,
        "bi4_csv_dat_h5_vtk_payloads_read_or_hashed_by_source_builder": False,
        "jobs_started": False,
        "shared_state_modified": False,
        "adapter_contract_repaired": True,
    })


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--validator-source", type=Path, required=True)
    args = parser.parse_args()
    build(args.package.resolve(), args.validator_source.resolve())
    print(json.dumps({"status": "built_fresh119", "package": str(args.package.resolve()), "candidate_count": len(TAGS)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
