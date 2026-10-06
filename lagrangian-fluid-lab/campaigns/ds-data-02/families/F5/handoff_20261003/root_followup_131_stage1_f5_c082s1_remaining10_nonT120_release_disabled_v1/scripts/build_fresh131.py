#!/usr/bin/env python3
"""Build the fresh131 metadata-only release pack.

This builder reads JSON/XML/source metadata only.  It deliberately refuses to
hash or open scientific payloads; producer-attested hashes for BI4/DAT remain
opaque values copied from the already completed Root640 metadata.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any


# .../DualSPHysics/lagrangian-fluid-lab/campaigns/.../handoff/.../scripts
ROOT = Path(__file__).resolve().parents[8]
HANDOFF = ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003"
PKG = HANDOFF / "root_followup_131_stage1_f5_c082s1_remaining10_nonT120_release_disabled_v1"
FRESH118 = HANDOFF / "root_followup_118_stage1_f5_c082s1_first24_cpu_contract_disabled_v1"
FRESH119 = HANDOFF / "root_followup_119_stage1_f5_c082s1_actual_gencase640_initial_qa_disabled_v1"
FRESH125 = HANDOFF / "root_followup_125_stage1_f5_c082s1_full801_native_qualification_disabled_v1"
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
INTEGRATION_HANDOFF = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1")

ROOT783 = INTEGRATION_HANDOFF / "root_stage1_f5_actual777_XMF778_bed_two_full801_native_render_shared4_783"
ROOT786 = INTEGRATION_HANDOFF / "root_stage1_f5_M085_prelaunch_CPU_reservation_repair1_sequential_and_773_resume_786"
ROOT644_REVIEW = INTEGRATION_HANDOFF / "root_stage1_f5_actualGen640_16_independent_review_644/actual-root16-GenCase-independent-review.json"
ROOT663_REVIEW = INTEGRATION_HANDOFF / "root_stage1_f5_actual_initialQA661_16_independent_Mk50_review_663/actual-root16-native-initial-Mk50-independent-review.json"
ROOT630_REVIEW = INTEGRATION_HANDOFF / "root_stage1_f5_fresh117_actual16_motion630_independent_review_632/actual-root16-motion-transform-independent-review.json"
ROOT142_LAUNCH = INTEGRATION_HANDOFF / "root_stage1_home_floor_inventory_dispatch_142/launch.py"
ROOT142_POLICY = INTEGRATION_HANDOFF / "root_stage1_home_floor_inventory_dispatch_142/root_home_floor_inventory_policy.py"
ROOT230_LAUNCH = INTEGRATION_HANDOFF / "root_stage1_native_home_floor_eight_solver_dispatch_230/launch.py"
ROOT230_POLICY = INTEGRATION_HANDOFF / "root_stage1_native_home_floor_eight_solver_dispatch_230/root_native_home_floor_inventory_policy.py"
RUNTIME = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
STRICT = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py"
PYTHON = INTEGRATION / "lagrangian-fluid-lab/.venv/bin/python"
RESOURCE_APPROVAL = INTEGRATION_HANDOFF.parent / "root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json"
PARTVTK = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64")
SOLVER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64")

DENIED_SUFFIXES = {".bi4", ".dat", ".h5", ".csv", ".vtk", ".vtu", ".vtp"}
TAGS = [
    "M085_T090", "M085_T100",
    "M095_T080", "M095_T090", "M095_T100",
    "M105_T080", "M105_T090", "M105_T100",
    "M115_T080", "M115_T090",
]
ALL_T120 = ["M085_T120", "M095_T120", "M105_T120", "M115_T120"]


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def load_json(path: Path) -> dict[str, Any]:
    if path.suffix.lower() in DENIED_SUFFIXES:
        raise RuntimeError(f"refusing scientific payload read: {path}")
    return json.loads(path.read_text())


def sha(path: Path) -> str:
    if path.suffix.lower() in DENIED_SUFFIXES:
        raise RuntimeError(f"refusing scientific payload hash: {path}")
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def template_sha(path: Path) -> str | None:
    """Return a static metadata hash; directories and runtime binaries stay null."""
    if path.is_dir() or not path.exists():
        return None
    if path.suffix.lower() in DENIED_SUFFIXES:
        raise RuntimeError(f"template_sha cannot consume payload: {path}")
    if path == PYTHON or path.name in {"DualSPHysics5.4_linux64", "PartVTK_linux64"}:
        return None
    return sha(path)


def add_input(entries: list[dict[str, Any]], path: str | Path, value: str | None, provenance: str) -> None:
    text = str(path)
    if text in {entry["path"] for entry in entries}:
        return
    entries.append({"path": text, "sha256": value, "provenance": provenance})


def add_static(entries: list[dict[str, Any]], path: Path, provenance: str) -> None:
    add_input(entries, path, template_sha(path), provenance)


def add_metadata(entries: list[dict[str, Any]], path: Path, provenance: str) -> None:
    add_static(entries, path, provenance)


def producer_payload(entries: list[dict[str, Any]], path: str, attested_sha: str, provenance: str) -> None:
    """Register opaque science input without opening or hashing it."""
    if Path(path).suffix.lower() not in DENIED_SUFFIXES:
        raise ValueError(f"producer_payload expects an opaque payload: {path}")
    add_input(entries, path, attested_sha, provenance)


def receipt_summary(request_path: Path) -> dict[str, Any]:
    request = load_json(request_path)
    attempt_root = Path(request.get("attempt_root", ""))
    receipt_path = attempt_root / "execution-receipt.json"
    out: dict[str, Any] = {
        "request_path": str(request_path),
        "request_sha256": sha(request_path),
        "candidate_id": request.get("candidate_id"),
        "attempt_id": request.get("attempt_id"),
        "attempt_root": str(attempt_root),
        "receipt_path": str(receipt_path),
        "receipt_exists": receipt_path.exists(),
    }
    if receipt_path.exists():
        receipt = load_json(receipt_path)
        out.update({
            "receipt_sha256": sha(receipt_path),
            "status": receipt.get("status"),
            "returncode": receipt.get("returncode"),
            "termination_reason": receipt.get("termination_reason"),
            "error": receipt.get("error"),
            "started_at_utc": receipt.get("started_at_utc"),
            "finished_at_utc": receipt.get("finished_at_utc"),
        })
    else:
        out["status"] = "no_receipt_yet"
    return out


def process_live(pid: int | None) -> bool:
    if not pid:
        return False
    result = subprocess.run(["ps", "-p", str(pid), "-o", "pid="], capture_output=True, text=True, check=False)
    return bool(result.stdout.strip())


def build_render_status() -> dict[str, Any]:
    old = {
        "controller_launch": str(ROOT783 / "controller-launch-process.json"),
        "controller_launch_sha256": sha(ROOT783 / "controller-launch-process.json"),
        "controller_log": str(ROOT783 / "controller.log"),
        "M085_T080": receipt_summary(ROOT783 / "M085_T080-render-request.json"),
        "M115_T100": receipt_summary(ROOT783 / "M115_T100-render-request.json"),
    }
    launch = load_json(ROOT783 / "controller-launch-process.json")
    old["controller_pid"] = launch.get("pid")
    old["controller_live"] = process_live(launch.get("pid"))

    repair = {
        "handoff": str(ROOT786),
        "controller_launch": str(ROOT786 / "controller-launch-process.json"),
        "controller_launch_sha256": sha(ROOT786 / "controller-launch-process.json"),
        "request": str(ROOT786 / "M085_T080-render-request.json"),
        "request_sha256": sha(ROOT786 / "M085_T080-render-request.json"),
        "dispatch_config": str(ROOT786 / "dispatch-config.json"),
        "dispatch_config_sha256": sha(ROOT786 / "dispatch-config.json"),
        "M085_T080": receipt_summary(ROOT786 / "M085_T080-render-request.json"),
    }
    repair_launch = load_json(ROOT786 / "controller-launch-process.json")
    repair["controller_pid"] = repair_launch.get("pid")
    repair["controller_live"] = process_live(repair_launch.get("pid"))

    status = {
        "schema": "ds02.f5.c082s1.root783-root786-render-status.fresh131.v1",
        "source_only": True,
        "source_agent_did_not_read_or_hash_science_payloads": True,
        "root783": old,
        "root786": repair,
        "interpretation": {
            "M085_T080_root783": "prelaunch shared CPU64 reservation rejection; no renderer worker/science product",
            "M085_T080_root786": "new sequential CPU-slot repair controller; status must be re-read by Root before gate use",
            "M115_T100_root783": "actual render remains pending until receipt completed/0",
            "visual_acceptance": False,
            "remaining10_release": False,
        },
    }
    return status


def qa_paths(tag: str) -> tuple[Path, Path, Path]:
    suffix = tag.lower()
    root = DATA_ROOT / f"root-stage1-f5-c082s1-{suffix}-actual-initial-placement-mk50-119-root661"
    receipt = root / "execution-receipt.json"
    report = root / "initial-qa/placement/c082s1-stage1-placement-mk50-audit.json"
    producer = root / "initial-qa/registered-export-and-placement-producer.json"
    return receipt, report, producer


def make_gate(render_status_path: Path) -> dict[str, Any]:
    return {
        "schema": "ds02.f5.c082s1.remaining10-release-gate.fresh131.v1",
        "status": "WAIT",
        "source_status_snapshot": str(render_status_path),
        "source_status_snapshot_sha256": sha(render_status_path),
        "required_current_endpoint_cases": ["M085_T080", "M115_T100"],
        "M085_T080": {
            "root783": "failed_prelaunch_shared_cpu64_reservation",
            "root786": "pending_actual_completed0_receipt_and_render_product",
            "visual_acceptance": False,
        },
        "M115_T100": {
            "root783": "running_at_source_build",
            "visual_acceptance": False,
        },
        "requires_each_endpoint_actual_full801_render_completed0": True,
        "requires_manual_root_visual_review_of_each_endpoint": True,
        "remaining10_release_enabled": False,
        "T120_release_enabled": False,
        "T120_reason": "forcing endpoint is 19.2 s while this release qualification window is 0..16 s; it needs a separate longer-window source package",
        "short_window_or_bed_diagnostic_is_insufficient": True,
        "historical_A_B_penetration_failures_retained": True,
        "historical_precision_negative": {
            "classification": "numerical_precision",
            "max_residual_cells": 5.000000015797923e-06,
            "threshold_cells": 1.0e-06,
            "accepted": False,
        },
    }


def main() -> None:
    if set(TAGS) & set(ALL_T120):
        raise AssertionError("T120 must never enter fresh131")
    review = load_json(FRESH119 / "metadata/fresh119-gencase640-independent-review.json")
    rows = {row["tag"]: row for row in review["cases"]}
    if len(rows) != 16 or any(tag not in rows for tag in TAGS):
        raise AssertionError("fresh119 does not contain all requested producer rows")

    render_status = build_render_status()
    render_status_path = PKG / "metadata/root783-root786-render-status.json"
    dump(render_status_path, render_status)
    gate = make_gate(render_status_path)

    source_plan: dict[str, Any] = {
        "schema": "ds02.f5.c082s1.fresh131-remaining10-release-source-plan.v1",
        "source_only": True,
        "source_agent_did_not_read_or_hash_science_payloads": True,
        "candidate_count": len(TAGS),
        "candidate_tags": TAGS,
        "excluded_T120_tags": ALL_T120,
        "physical_domain": "C082S1 analytic closed bed/tank, source Mk40 -> native Mk50, 3D DP=0.02 m",
        "native_release_window": {"tmax_s": 16.0, "tout_s": 0.02, "expected_frames": 801, "reason": "endpoint-contained qualification window"},
        "gencase_source": str(FRESH119 / "metadata/fresh119-gencase640-independent-review.json"),
        "gencase_source_sha256": sha(FRESH119 / "metadata/fresh119-gencase640-independent-review.json"),
        "initial_qa_source": str(ROOT663_REVIEW),
        "initial_qa_source_sha256": sha(ROOT663_REVIEW),
        "actual_counts_are_per_candidate_producer_attested": True,
        "expected_counts_are_not_forecast": True,
        "full_native_requests_disabled": True,
        "full_native_authorized": False,
        "remaining10_release_enabled": False,
        "gate": gate,
        "future_payload_hashes": None,
        "no_new_case_credit": True,
        "historical_A_B_penetration_failures_retained": True,
        "exact_dp_lattice_negative_retained": True,
        "jobs_started": False,
        "shared_state_modified": False,
    }
    dump(PKG / "metadata/fresh131-source-plan.json", source_plan)

    rows_out: list[dict[str, Any]] = []
    for tag in TAGS:
        row = rows[tag]
        template = load_json(FRESH125 / f"requests/{tag}-full801-native-qualification-request.json")
        physical_binding_path = FRESH125 / f"bindings/{tag}-physical-binding.json"
        owner_path = FRESH125 / f"candidates/{tag}/owner.json"
        definition_path = FRESH125 / f"candidates/{tag}/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_{tag}_Def.xml"
        physical = load_json(physical_binding_path)
        actual_gencase_binding_path = FRESH119 / f"bindings/{tag}-actual-gencase-adapter.json"
        actual_qa_binding_path = FRESH119 / f"bindings/{tag}-initial-qa-mk50-binding.json"
        actual_gencase = load_json(actual_gencase_binding_path)
        actual_qa_binding = load_json(actual_qa_binding_path)
        gencase_receipt = Path(row["receipt"])
        prepared_report = Path(row["prepared_report"])
        generated_xml = Path(row["generated_xml"])
        generated_bi4 = Path(row["generated_bi4"])
        motion_asset = Path(actual_gencase["motion_asset"]["path"])
        motion_report = Path(actual_gencase["root_actual_motion_report"]["path"])
        motion_attempt_root = motion_report.parent
        motion_receipt = motion_attempt_root / "execution-receipt.json"
        qa_receipt, qa_report, qa_producer = qa_paths(tag)
        qa = load_json(qa_report)
        qr = load_json(qa_receipt)
        if qr.get("status") != "completed" or qr.get("returncode") != 0:
            raise AssertionError(f"initial QA is not completed/0 for {tag}")
        if qa.get("status") != "completed_stage1_placement_mk50_diagnostic":
            raise AssertionError(f"unexpected QA status for {tag}: {qa.get('status')}")
        if not qa.get("all_basic_placement_checks_pass"):
            raise AssertionError(f"basic placement failed for {tag}")
        if qa.get("numerical_precision_result_accepted", qa.get("numerical_precision", {}).get("accepted_as_stage1_placement_gate", True)):
            raise AssertionError(f"precision negative was silently accepted for {tag}")
        counts = copy.deepcopy(qa["actual_counts"])
        row_counts = {k: v for k, v in row["actual_counts"].items() if k != "xml_particle_counts"}
        qa_counts = {k: v for k, v in counts.items() if k != "xml_particle_counts"}
        if row_counts != qa_counts:
            raise AssertionError(f"GenCase/QA count mismatch for {tag}")

        qa_report_sha = sha(qa_report)
        qa_receipt_sha = sha(qa_receipt)
        qa_producer_sha = sha(qa_producer)
        motion_receipt_sha = sha(motion_receipt)
        request_id = f"f5-fresh131-{tag.lower()}-full801-native-release"
        attempt_id = f"root-stage1-f5-c082s1-{tag.lower()}-full801-native-release-131"
        binding_rel = f"bindings/{tag}-full801-native-release-binding.json"
        request_rel = f"requests/{tag}-full801-native-release-request.json"
        binding_path = PKG / binding_rel
        request_path = PKG / request_rel
        prefix = str(generated_xml.with_suffix(""))
        prepared_root = str(generated_xml.parent)
        physical_sha = sha(physical_binding_path)
        owner_sha = sha(owner_path)
        definition_sha = sha(definition_path)
        actual_counts = counts

        binding = {
            "schema": "ds02.f5.c082s1.remaining10-native-release-binding.fresh131.v1",
            "source_only": True,
            "candidate_id": row["candidate_id"],
            "tag": tag,
            "case_id": row.get("case_id", template["case_id"]),
            "condition_id": template["condition_id"],
            "physical_case_id": physical["physical_case_id"],
            "physical_condition_sha256": physical["physical_condition_sha256"],
            "canonical_physical_scope": {
                "schema": "ds02.f5.c082s1.fresh125-physical-binding.v1",
                "sha256": physical["physical_condition_sha256"],
                "source_plan_sha256": physical.get("source_plan_physical_condition_sha256"),
                "source_definition_sha256": physical.get("source_definition_sha256"),
                "canonical_and_source_plan_are_distinct": True,
            },
            "source_definition": str(definition_path),
            "source_definition_sha256": definition_sha,
            "source_owner": str(owner_path),
            "source_owner_sha256": owner_sha,
            "physical_binding": str(physical_binding_path),
            "physical_binding_sha256": physical_sha,
            "source_mkbound": 40,
            "native_bed_marker_mk": 50,
            "genuine_gencase": {
                "attempt_id": row["attempt_id"],
                "receipt": str(gencase_receipt),
                "receipt_sha256": row["receipt_sha256"],
                "prepared_input_report": str(prepared_report),
                "prepared_input_report_sha256": row["prepared_report_sha256"],
                "generated_xml": str(generated_xml),
                "generated_xml_sha256": row["generated_xml_sha256"],
                "generated_bi4": str(generated_bi4),
                "generated_bi4_sha256_producer_attested": row["generated_bi4_sha256"],
                "motion_asset": str(motion_asset),
                "motion_asset_sha256_producer_attested": actual_gencase["motion_asset"]["sha256"],
                "motion_transform_receipt": actual_gencase["motion_transform_receipt"],
                "motion_transform_receipt_sha256": motion_receipt_sha,
                "status": "completed/0",
            },
            "actual_initial_qa": {
                "attempt_id": actual_qa_binding["qa_attempt_id"],
                "receipt": str(qa_receipt),
                "receipt_sha256": qa_receipt_sha,
                "report": str(qa_report),
                "report_sha256": qa_report_sha,
                "producer_metadata": str(qa_producer),
                "producer_metadata_sha256": qa_producer_sha,
                "status": "completed/0",
                "basic_placement_checks_pass": True,
                "central_mk50_support": True,
                "fluid_exact_15_y_levels": True,
                "fluid_initial_above_bed": True,
                "exact_dp_lattice": {
                    "status": "diagnostic_negative_preserved",
                    "max_residual_cells": 5.000000015797923e-06,
                    "threshold_cells": 1.0e-06,
                    "accepted_as_stage1_gate": False,
                },
            },
            "actual_counts": actual_counts,
            "actual_counts_provenance": "Root644 generated-report row plus Root661/663 actual initial Mk50 placement report; copied per candidate",
            "motion_end_s": physical.get("motion_transform", {}).get("output_time_window_s", [None, None])[1],
            "qualification_window_s": [0.0, 16.0],
            "expected_frames": 801,
            "tout_s": 0.02,
            "array_edit_allowed": False,
            "arrays_allowed": False,
            "future_payload_hashes": None,
            "request_path": str(request_path),
            "upstream_gate": gate,
            "full_native_authorized": False,
            "launch_allowed": False,
            "source_agent_did_not_read_or_hash_science_payloads": True,
        }
        dump(binding_path, binding)
        binding_sha = sha(binding_path)

        base = copy.deepcopy(template)
        # Remove stale, placeholder-bound values by replacing every launch/input field below.
        base.update({
            "schema": "ds02.runner-request.v2",
            "request_id": request_id,
            "attempt_id": attempt_id,
            "candidate_id": row["candidate_id"],
            "condition_id": template["condition_id"],
            "case_id": row.get("case_id", template["case_id"]),
            "binding": str(binding_path),
            "binding_sha256": binding_sha,
            "kind": "qualification",
            "cpu_task_kind": "solver",
            "cpu_threads": 2,
            "omp_threads": 2,
            "disabled": True,
            "execution_allowed": False,
            "launch": False,
            "launch_allowed": False,
            "source_only": True,
            "solver_allowed": False,
            "solver_command_is_template_only": True,
            "launch_owner": "root",
            "cwd": prepared_root,
            "command": [str(SOLVER), prefix, "{attempt_root}/solver_output", "-tmax:16", "-tout:0.02"],
            "gencase_attempt_id": row["attempt_id"],
            "gencase_prepared_root": prepared_root,
            "gencase_prefix": prefix,
            "gencase_receipt": str(gencase_receipt),
            "gencase_receipt_sha256": row["receipt_sha256"],
            "generated_xml": str(generated_xml),
            "generated_xml_sha256": row["generated_xml_sha256"],
            "generated_bi4": str(generated_bi4),
            "generated_bi4_sha256_producer_attested": row["generated_bi4_sha256"],
            "motion_asset_path": str(motion_asset),
            "motion_asset_sha256": actual_gencase["motion_asset"]["sha256"],
            "actual_initial_qa_binding": str(actual_qa_binding_path),
            "actual_initial_qa_binding_sha256": sha(actual_qa_binding_path),
            "actual_initial_qa_receipt": str(qa_receipt),
            "actual_initial_qa_receipt_sha256": qa_receipt_sha,
            "actual_initial_qa_report": str(qa_report),
            "actual_initial_qa_report_sha256": qa_report_sha,
            "actual_initial_qa_completed0": True,
            "native_initial_qa_basic_checks_pass": True,
            "native_initial_qa_precision_check": "separate historical negative: max 5e-6 cells > 1e-6; no threshold relaxation",
            "actual_counts": actual_counts,
            "expected_counts": actual_counts,
            "expected_particles": actual_counts["total_particles"],
            "expected_particle_axis": actual_counts["total_particles"],
            "expected_dimension": actual_counts["solver_dimension"],
            "expected_fixed_particles": actual_counts["fixed_particles"],
            "expected_moving_particles": actual_counts["moving_particles"],
            "expected_fluid_particles": actual_counts["fluid_particles"],
            "expected_floating_particles": actual_counts["floating_particles"],
            "expected_frames": 801,
            "tmax_s": 16.0,
            "tout_s": 0.02,
            "qualification_window_s": [0.0, 16.0],
            "event_window_semantics": "16s/801 qualification window; each source tag has forcing_end_s <= 16 s; this is a new native run, never an output slice",
            "motion_end_s": binding["motion_end_s"],
            "depends_on_attempt": actual_qa_binding["qa_attempt_id"],
            "full801_authorized": False,
            "full_native_authorized": False,
            "production_approval": "none",
            "q_n_granted": False,
            "native_bed_mk": 50,
            "source_mkbound": 40,
            "physical_case_id": physical["physical_case_id"],
            "physical_condition_sha256": physical["physical_condition_sha256"],
            "physical_binding": str(physical_binding_path),
            "physical_binding_sha256": physical_sha,
            "source_definition": str(definition_path),
            "source_definition_sha256": definition_sha,
            "owner": str(owner_path),
            "owner_sha256": owner_sha,
            "independent_case_count_increment": 0,
            "no_new_case_credit": True,
            "historical_A_B_penetration_failures_retained": True,
            "root_review_required": True,
            "status": "disabled_until_M085_T080_and_M115_T100_root786_root783_full801_render_and_manual_visual_review",
            "upstream_full801_visual_gate": gate,
            "promotion_policy": {
                "remaining10_release_only_after_current_endpoint_render_and_root_visual_pass": True,
                "T120_not_included": True,
                "new_case_credit": False,
            },
            "future_candidate_counts_and_hashes_null": False,
            "future_output_hashes": {
                "solver_receipt_sha256": None,
                "solver_stdout_sha256": None,
                "solver_data_manifest_sha256": None,
                "solver_part_count": None,
                "typed_receipt_sha256": None,
                "typed_h5_sha256": None,
                "xmf_manifest_sha256": None,
                "bed_audit_report_sha256": None,
                "render_receipt_sha256": None,
                "render_manifest_sha256": None,
            },
            "resource_window": template["resource_window"],
            "shared_registry_write_allowed": False,
            "shared_lease_required": True,
            "root230_gpu_protection_required_for_native_solver": True,
            "root230_live_uuid_lease_required": True,
            "root_inventory_policy_source_sha256": template.get("root230_policy_source_sha256"),
            "root_dataset_inventory_profile": template["root_dataset_inventory_profile"],
            "source_agent_did_not_read_or_hash_science_payloads": True,
        })

        # fresh125's exact static runtime/Root230 fields remain useful, but add
        # the live Root142 closure explicitly so registration cannot infer it.
        base["root142_runtime_binding"] = {
            "schema": "ds02.root142.runtime-binding.v1",
            "root142_entrypoint": str(ROOT142_LAUNCH),
            "root142_entrypoint_sha256": sha(ROOT142_LAUNCH),
            "root142_policy_source": str(ROOT142_POLICY),
            "root142_policy_source_sha256": sha(ROOT142_POLICY),
            "runtime_entrypoint": str(RUNTIME),
            "runtime_entrypoint_sha256": sha(RUNTIME),
            "strict_dispatch_entrypoint": str(STRICT),
            "strict_dispatch_entrypoint_sha256": sha(STRICT),
            "root_dataset_inventory_profile": template["root_dataset_inventory_profile"],
            "input_sha256_required": True,
            "launch_owner": "root",
            "source_preparation_may_not_launch": True,
        }
        base["root786_repair_handoff"] = str(ROOT786 / "dispatch-config.json")
        base["root786_repair_handoff_sha256"] = sha(ROOT786 / "dispatch-config.json")
        base["root783_render_handoff"] = str(ROOT783 / f"{tag if tag in {'M085_T080', 'M115_T100'} else 'M115_T100'}-render-request.json")

        entries: list[dict[str, Any]] = []
        # Fresh131 sources and actual producer metadata.
        add_static(entries, binding_path, "fresh131 generated binding metadata")
        add_metadata(entries, PKG / "metadata/fresh131-source-plan.json", "fresh131 source plan metadata")
        add_metadata(entries, render_status_path, "Root783/Root786 receipt status metadata")
        for source in [actual_gencase_binding_path, actual_qa_binding_path, physical_binding_path, owner_path, definition_path]:
            add_static(entries, source, "source/JSON/XML metadata; source agent did not read science payloads")
        for source in [ROOT644_REVIEW, ROOT663_REVIEW, ROOT630_REVIEW, ROOT142_LAUNCH, ROOT142_POLICY, ROOT230_LAUNCH, ROOT230_POLICY, RUNTIME, STRICT, RESOURCE_APPROVAL, ROOT783 / "actual-root-full801-render-enabling-review.json", ROOT786 / "dispatch-config.json", ROOT786 / "controller-launch-process.json"]:
            add_static(entries, source, "Root-owned static metadata/runtime source; source agent did not read science payloads")
        for source in [Path(actual_gencase["actual_gencase_request"]), Path(actual_gencase["source_binding"]), motion_report, motion_receipt, gencase_receipt, prepared_report, qa_receipt, qa_report, qa_producer]:
            add_static(entries, source, "registered JSON metadata; no scientific payload read")
        add_static(entries, generated_xml, "Root640 producer-attested XML; source does not read science arrays")
        add_static(entries, PYTHON, "Root142 runtime Python; validated by Root at registration")
        producer_payload(entries, str(generated_bi4), row["generated_bi4_sha256"], "Root640 producer-attested BI4; source did not read or hash BI4")
        producer_payload(entries, str(motion_asset), actual_gencase["motion_asset"]["sha256"], "Root630 producer-attested motion DAT; source did not read or hash DAT")
        add_input(entries, str(DATA_ROOT / row["attempt_id"]), None, "producer output directory; Root runner resolves it, source did not walk payload")
        # Official binaries are command inputs, but Root142 validates them at execution.
        add_input(entries, str(SOLVER), None, "official solver binary validated by Root230 at registration")
        add_input(entries, str(PARTVTK), None, "official PartVTK binary validated by Root142 at registration")
        base["input_files"] = [entry["path"] for entry in entries]
        base["input_sha256"] = {entry["path"]: entry["sha256"] for entry in entries}
        base["input_sha256_provenance"] = {entry["path"]: entry["provenance"] for entry in entries}
        base["input_sha256_required"] = True
        dump(request_path, base)

        rows_out.append({
            "tag": tag,
            "candidate_id": row["candidate_id"],
            "condition_id": template["condition_id"],
            "physical_condition_sha256": physical["physical_condition_sha256"],
            "gencase_attempt_id": row["attempt_id"],
            "gencase_receipt": str(gencase_receipt),
            "gencase_receipt_sha256": row["receipt_sha256"],
            "initial_qa_attempt_id": actual_qa_binding["qa_attempt_id"],
            "initial_qa_receipt": str(qa_receipt),
            "initial_qa_receipt_sha256": qa_receipt_sha,
            "initial_qa_report": str(qa_report),
            "initial_qa_report_sha256": qa_report_sha,
            "generated_xml": str(generated_xml),
            "generated_xml_sha256": row["generated_xml_sha256"],
            "generated_bi4_sha256_producer_attested": row["generated_bi4_sha256"],
            "motion_asset_sha256_producer_attested": actual_gencase["motion_asset"]["sha256"],
            "request": str(request_path),
            "request_sha256": sha(request_path),
            "binding": str(binding_path),
            "binding_sha256": binding_sha,
            "actual_counts": actual_counts,
            "basic_placement_checks_pass": True,
            "precision_gate": "diagnostic_negative_preserved",
        })

    # Update source plan with the exact per-case closure after all records exist.
    source_plan["cases"] = rows_out
    dump(PKG / "metadata/fresh131-source-plan.json", source_plan)

    # The source plan hash changed after request construction.  It is a metadata
    # input, so rewrite the request maps to close the final source-plan hash.
    plan_path = PKG / "metadata/fresh131-source-plan.json"
    plan_sha = sha(plan_path)
    for tag in TAGS:
        request_path = PKG / f"requests/{tag}-full801-native-release-request.json"
        req = load_json(request_path)
        plan_text = str(plan_path)
        req["input_sha256"][plan_text] = plan_sha
        req["input_sha256_provenance"][plan_text] = "fresh131 final source plan metadata hash"
        if plan_text not in req["input_files"]:
            req["input_files"].append(plan_text)
        dump(request_path, req)

    manifest_files: list[dict[str, str]] = []
    for path in sorted(PKG.rglob("*")):
        if not path.is_file() or path.name == "manifest.json" or path.name == "fresh131-validator-report.json":
            continue
        # No scientific payload is created in this package; fail closed if that changes.
        if path.suffix.lower() in DENIED_SUFFIXES:
            raise RuntimeError(f"fresh131 unexpectedly contains scientific payload: {path}")
        manifest_files.append({"path": str(path.relative_to(PKG)), "sha256": sha(path)})
    manifest = {
        "schema": "ds02.f5.c082s1.fresh131-manifest.v1",
        "source_only": True,
        "files": manifest_files,
        "excluded_generated_report": "metadata/fresh131-validator-report.json (not part of its own fixed hash set)",
        "science_payloads_read_or_hashed_by_source_agent": False,
        "jobs_started": False,
        "shared_state_modified": False,
        "remaining10_release_enabled": False,
        "T120_included": False,
    }
    dump(PKG / "manifest.json", manifest)

    # README is intentionally emitted after data is available and is also in the
    # manifest; it contains no claim of scientific acceptance.
    readme = f"""# F5 fresh131: remaining ten non-T120 native-release closures

This source-only pack contains the ten conditions `{', '.join(TAGS)}` from the
fresh117/fresh118 first-24 source family.  It binds each condition to its own
completed Root640 GenCase metadata and Root661 initial placement/Mk50 report,
then creates a disabled 0..16 s, 0.02 s, 801-state native qualification
request.  Counts are copied from the candidate's producer row (194427 total,
158559 fixed, 4210 moving, 31658 fluid, 0 floating, 3-D); they are not a
historical forecast.  Native Mk50 and source Mk40 remain distinct.

T120 is deliberately excluded.  Its transformed forcing ends at 19.2 s and
therefore needs a separate longer-window source package; it is not silently
fit into this 16 s qualification window.

At build time Root783 reported M085_T080 as a prelaunch shared CPU64
reservation rejection (no renderer worker or science product) and M115_T100 as
still running.  Root786 is the sequential M085 slot-repair controller.  The
remaining ten requests stay disabled until both current endpoint attempts have
real completed/0 full801 renderer receipts and independent manual Root visual
acceptance.  A return code, Root778 diagnostic, or initial placement pass alone
does not open that gate.

The exact-DP 1e-6 precision negative and historical A/B penetration failures
remain recorded.  Future native/typed/XMF/bed/render hashes are null.  This
pack creates no new case credit, does not alter the shared ledger, and did not
read or hash BI4, DAT, H5, CSV, VTK, or solver payloads; those inputs retain
producer-attested hashes for the eventual Root-owned registration only.

## Root handoff

* Source plan: `metadata/fresh131-source-plan.json`
* Current endpoint status: `metadata/root783-root786-render-status.json`
* Disabled bindings: `bindings/*-full801-native-release-binding.json`
* Disabled requests: `requests/*-full801-native-release-request.json`
* Metadata-only validator: `scripts/validate_fresh131.py`
* T120 and all downstream typed/XMF/bed/render stages remain closed.
"""
    (PKG / "README.md").write_text(readme)

    # README was not present when the manifest was first constructed; rebuild
    # the manifest now so its hash is closed without including itself.
    manifest_files = []
    for path in sorted(PKG.rglob("*")):
        if not path.is_file() or path.name == "manifest.json" or path.name == "fresh131-validator-report.json":
            continue
        if path.suffix.lower() in DENIED_SUFFIXES:
            raise RuntimeError(f"fresh131 unexpectedly contains scientific payload: {path}")
        manifest_files.append({"path": str(path.relative_to(PKG)), "sha256": sha(path)})
    manifest["files"] = manifest_files
    dump(PKG / "manifest.json", manifest)
    print(json.dumps({"package": str(PKG), "candidate_count": len(TAGS), "manifest_files": len(manifest_files), "status": "built"}, indent=2))


if __name__ == "__main__":
    main()
