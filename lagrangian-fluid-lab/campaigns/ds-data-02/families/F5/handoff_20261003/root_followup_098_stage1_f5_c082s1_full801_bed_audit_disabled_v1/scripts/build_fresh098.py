#!/usr/bin/env python3
"""Build the disabled full801 particle-level bed-audit binding/request.

Only JSON/XML/source metadata is read or hashed here.  The future full typed
H5, XMF, BI4, CSV, VTK, and DAT products stay root-bind placeholders.  This
builder never invokes a worker or a runtime dispatcher.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab")
HANDOFF = INTEGRATION / "campaigns/ds-data-02/handoff_20261003"
F5_DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5")
CASE = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1"
PHYSICAL = "F5_COMPACT_STILL_WATER_RUNUP_RECOVERY_C082S1"
CANONICAL = "e691d030eda575b9cfabe62f295c9bdc142e5a04cb4357c9fe2790aaec549dbf"
SOURCE_PLAN = "5bad3ec9f9a71aa87da8272003c357f4523d4ffa164d3f06e5d25fee1a4fbfa6"
LEGACY_SCOPE = "3cd1ceab16be11428bbc1011a1b4e297c384d8c7926432c222c254064744ccd0"
BED_ATTEMPT = "root-stage1-f5-c082s1-solid-fluid-recovery-short-native-bed-audit-321"
NATIVE_ATTEMPT = "root-stage1-f5-c082s1-solid-fluid-recovery-full801-native-qualification-349"
TYPED_ATTEMPT = "root-stage1-f5-c082s1-solid-fluid-recovery-full801-native-typed-nvme-350"
XMF_ATTEMPT = "root-stage1-f5-c082s1-solid-fluid-recovery-full801-native-xmf-351"
AUDIT_ATTEMPT = "root-stage1-f5-c082s1-full801-native-bed-audit-353"
DATA_ROOT = F5_DATA / CASE
GEN_ROOT = DATA_ROOT / "root-stage1-f5-c082s1-solid-fluid-recovery-genuine-gencase-293"
PLACEMENT_ROOT = DATA_ROOT / "root-stage1-f5-c082s1-solid-fluid-recovery-stage1-placement-mk50-audit-315"
NATIVE_ROOT = DATA_ROOT / NATIVE_ATTEMPT
FRESH096 = ROOT.parent / "root_followup_096_stage1_f5_c082s1_actual_typed_dynamic_adapter_v1"
FRESH097 = ROOT.parent / "root_followup_097_stage1_f5_c082s1_full801_disabled_pipeline_v1"
FRESH096_BINDING = FRESH096 / "bindings/short-event-bed-audit-binding.json"
FRESH096_WORKER = FRESH096 / "workers/bed_audit.py"
FRESH096_RECIPE = ROOT.parent / "root_followup_093_stage1_f5_c082s1_short51_pipeline_v1/canonical-physical-recipe.json"
FRESH096_PHYSICAL = ROOT.parent / "root_followup_093_stage1_f5_c082s1_short51_pipeline_v1/physical-binding.json"
FRESH097_TYPED = FRESH097 / "requests/full-typed-801-request.json"
FRESH097_XMF = FRESH097 / "requests/full-xmf-801-request.json"
FRESH097_GATE = FRESH097 / "metadata/full801-gate.json"
FRESH097_PROVENANCE = FRESH097 / "metadata/full801-source-input-provenance.json"
FRESH097_MANIFEST = FRESH097 / "metadata/fresh097-manifest.json"
GEN_RECEIPT = GEN_ROOT / "execution-receipt.json"
PREPARED_REPORT = GEN_ROOT / "prepared/prepared-input-report.json"
GENERATED_XML = GEN_ROOT / f"prepared/{CASE}.xml"
PLACEMENT_RECEIPT = PLACEMENT_ROOT / "execution-receipt.json"
PLACEMENT_REPORT = PLACEMENT_ROOT / "audit-output/c082s1-stage1-placement-mk50-audit.json"
NATIVE_RECEIPT = NATIVE_ROOT / "execution-receipt.json"
ROOT348 = HANDOFF / "root_stage1_f5_actual_short51_bed_visual_full801_launch_approval_348/full801-root-launch-approval.json"
ROOT349_REQUEST = HANDOFF / "root_stage1_f5_actual_bed347_visual346_approved_full801_native_349/full801-native-request.json"
ROOT349_REVIEW = HANDOFF / "root_stage1_f5_actual_bed347_visual346_approved_full801_native_349/full801-native-review.json"
WORKER = ROOT / "workers/bed_audit_full801.py"
RESOURCE = HANDOFF / "root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json"
INVENTORY = HANDOFF / "root_stage1_home_floor_inventory_dispatch_142/root_home_floor_inventory_policy.py"
RUNTIME = INTEGRATION / "scripts/ds_data02_runtime_v2.py"
STRICT = INTEGRATION / "scripts/ds_data02_strict_dispatch_v1.py"
PYTHON = INTEGRATION / ".venv/bin/python"

NATIVE_RECEIPT_SHA = "2fd76bde16769e2febae752be38b1f83175f8b0fe5d607045cf48ec5039fee1f"
GEN_RECEIPT_SHA = "651f3dd714ded9a9d8e4cc158702925f0cb06d0b778dcc66827de4b085e058b7"
PREPARED_REPORT_SHA = "c0572867ac670c4d4676f40463ebc903ace06ddf9bf5a47f533a2cfd5c83585a"
GEN_XML_SHA = "19102e12efb4ba6d36f12bc020135fbcd7013949b9089fe1b6197b8e23c51e8e"
PLACEMENT_RECEIPT_SHA = "ecc8f405f988ddc1fc5e50f853f29316ddea480aa548651be21f5494aa1c9c8a"
PLACEMENT_REPORT_SHA = "080f015481fb53f90479026c2eaad6ce514d79cf363d0cc2a2f5055d1650e66c"
ROOT348_SHA = "d1c97f5a3cfe9f94bed79d8c47211d7dbfc1dada77f850154d45d2feabe769e2"


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def sha(path: Path) -> str:
    if path.suffix.lower() in {".dat", ".bi4", ".csv", ".h5", ".hdf5", ".vtk", ".vtu"}:
        raise ValueError(f"science artifact is forbidden in fresh098 source hashing: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_files(paths: list[Path]) -> list[Path]:
    unique: list[Path] = []
    for path in paths:
        path = path.resolve()
        if path not in unique:
            unique.append(path)
    missing = [str(path) for path in unique if not path.is_file()]
    if missing:
        raise FileNotFoundError("missing source metadata: " + ", ".join(missing))
    return unique


def actual_counts() -> dict[str, Any]:
    return {
        "fixed_particles": 158559,
        "floating_particles": 0,
        "fluid_particles": 31658,
        "moving_particles": 4210,
        "solver_dimension": 3,
        "total_particles": 194427,
        "xml_particle_counts": {"fixed": 158559, "floating": 0, "fluid": 31658, "moving": 4210},
    }


def binding() -> dict[str, Any]:
    old = load(FRESH096_BINDING)
    counts = actual_counts()
    return {
        "schema": "ds02.f5.c082s1.full-event-bed-audit-binding.fresh098.v1",
        "status": "template_disabled_until_full_typed350_and_xmf351_metadata_bind",
        "case_id": CASE,
        "physical_case_id": PHYSICAL,
        "candidate_id": old["candidate_id"],
        "condition_id": old.get("condition_id", "F5_RUNUP_DP020_EQUILIBRIUM_ROOT050_C_SOLID_FLUID_RECOVERY_090"),
        "repair_id": old.get("repair_id", "F5_BED_RECOVERY_C082S1_SOLID_FLUID_SOURCE_090"),
        "physical_condition_sha256": CANONICAL,
        "source_plan_physical_condition_sha256": SOURCE_PLAN,
        "source_h5_physical_condition_sha256": LEGACY_SCOPE,
        "source_h5_scope_schema": "legacy-owner-scope.v0",
        "source_h5_scope_status": "legacy_incomplete; no cross-resolution physical claim",
        "physical_condition_hash_semantics": {
            "canonical_owner_sha256": CANONICAL,
            "source_plan_sha256": SOURCE_PLAN,
            "source_h5_sha256": LEGACY_SCOPE,
            "source_h5_scope_schema": "legacy-owner-scope.v0",
            "source_h5_scope_status": "legacy_incomplete; no cross-resolution physical claim",
            "relation": "distinct; future H5 legacy scope must never substitute for canonical owner",
        },
        "expected_dimension": 3,
        "expected_frames": 801,
        "expected_particle_axis": 194427,
        "expected_total_particles": 194427,
        "expected_fixed_particles": 158559,
        "expected_moving_particles": 4210,
        "expected_floating_particles": 0,
        "expected_fluid_particles": 31658,
        "actual_counts": counts,
        "dp_m": 0.02,
        "full_event": {"window_s": [0.0, 16.0], "save_interval_s": 0.02, "frames": 801, "short_event_result_reused": False},
        "native_bed_marker_mk": 50,
        "source_bed_marker_mkbound": 40,
        "bed_y_bounds_m": [-0.22, 0.22],
        "bed_x_bounds_m": [-0.2, 4.8],
        "penetration_bins_m": [0.02, 0.04],
        "bed_profile_nodes_xz_m": [[-0.2, 0.0], [2.0, 0.0], [3.0, 0.28], [3.6, 0.448], [3.9, 0.448], [4.4, 0.05], [4.8, 0.05]],
        "gencase_attempt_id": "root-stage1-f5-c082s1-solid-fluid-recovery-genuine-gencase-293",
        "gencase_output_root": str(GEN_ROOT),
        "gencase_prepared_output_root": str(GEN_ROOT / "prepared"),
        "gencase_receipt": str(GEN_RECEIPT),
        "gencase_receipt_sha256": GEN_RECEIPT_SHA,
        "gencase_prepared_report": str(PREPARED_REPORT),
        "gencase_prepared_report_sha256": PREPARED_REPORT_SHA,
        "canonical_generated_xml": str(GENERATED_XML),
        "canonical_generated_xml_sha256": GEN_XML_SHA,
        "initial_qa_attempt_id": "root-stage1-f5-c082s1-solid-fluid-recovery-stage1-placement-mk50-audit-315",
        "initial_qa_output_root": str(PLACEMENT_ROOT),
        "initial_qa_receipt": str(PLACEMENT_RECEIPT),
        "initial_qa_receipt_sha256": PLACEMENT_RECEIPT_SHA,
        "initial_qa_report": str(PLACEMENT_REPORT),
        "initial_qa_report_sha256": PLACEMENT_REPORT_SHA,
        "stage1_placement": {
            "all_basic_placement_checks_pass": True,
            "stage1_basic_placement_proof": "pass_excluding_numerical_precision",
            "numerical_precision_result_accepted": False,
            "central_mk50_surface_half_dp_counts": [208, 27, 22, 15, 20, 20],
            "native_type0_mk50_count": 30485,
            "fluid_y_levels": 15,
        },
        "full_native_attempt_id": NATIVE_ATTEMPT,
        "full_native_output_root": str(NATIVE_ROOT),
        "full_native_receipt": str(NATIVE_RECEIPT),
        "full_native_receipt_sha256": NATIVE_RECEIPT_SHA,
        "root348_launch_approval": str(ROOT348),
        "root348_launch_approval_sha256": ROOT348_SHA,
        "full_typed_attempt_id": TYPED_ATTEMPT,
        "full_typed_receipt": "<root-bind:full_typed_receipt>",
        "full_typed_receipt_sha256": "<root-bind:full_typed_receipt_sha256>",
        "full_typed_conversion_report": "<root-bind:full_typed_conversion_report>",
        "full_typed_conversion_report_sha256": "<root-bind:full_typed_conversion_report_sha256>",
        "trajectory_h5": "<root-bind:full_trajectory_h5>",
        "trajectory_h5_sha256": "<root-bind:full_trajectory_h5_sha256>",
        "trajectory_h5_physical_condition_sha256": LEGACY_SCOPE,
        "full_saved_state_metadata": {"path": "<root-bind:full_saved_state_metadata>", "sha256": "<root-bind:full_saved_state_metadata_sha256>", "all_801_saved_states": True, "saved_state_count": 801},
        "full_xmf_attempt_id": XMF_ATTEMPT,
        "xmf_receipt": "<root-bind:full_xmf_receipt>",
        "xmf_receipt_sha256": "<root-bind:full_xmf_receipt_sha256>",
        "xmf_manifest": "<root-bind:full_xmf_manifest>",
        "xmf_manifest_sha256": "<root-bind:full_xmf_manifest_sha256>",
        "xdmf": "<root-bind:full_xdmf>",
        "xdmf_sha256": "<root-bind:full_xdmf_sha256>",
        "native_conversion_contract": {
            "frames": 801,
            "particles": 194427,
            "solver_dimension": 3,
            "typed_role_counts": {"fixed": 158559, "moving": 4210, "fluid": 31658},
            "required_observed_mks": [1, 10, 20, 40, 50],
            "required_observed_types": [0, 1, 3],
            "native_bed_marker_mk": 50,
            "source_bed_marker_mkbound": 40,
            "mass_report_without_rescale": True,
        },
        "xmf_contract": {"frames": 801, "particles": 194427, "native_time_axis_preserved": True, "canonical_owner_separate_from_legacy_scope": True},
        "future_output_hashes": None,
        "full801_authorized": False,
        "q_n_granted": False,
        "repair_success": "unknown_until_full801_particle_level_audit_and_root_review",
        "science_arrays_read_by_binder": False,
        "science_arrays_hashed_by_binder": False,
        "dynamic_worker_started_by_binder": False,
    }


def source_inputs(binding_path: Path) -> list[Path]:
    return require_files([
        PYTHON, RUNTIME, STRICT, INVENTORY, RESOURCE,
        FRESH096_WORKER, FRESH096_BINDING, FRESH096_RECIPE, FRESH096_PHYSICAL,
        FRESH097_TYPED, FRESH097_XMF, FRESH097_GATE, FRESH097_PROVENANCE, FRESH097_MANIFEST,
        GEN_RECEIPT, PREPARED_REPORT, GENERATED_XML, PLACEMENT_RECEIPT, PLACEMENT_REPORT,
        NATIVE_RECEIPT, ROOT348, ROOT349_REQUEST, ROOT349_REVIEW,
        WORKER, binding_path, ROOT / "scripts/preflight_fresh098.py",
    ])


def main() -> int:
    binding_path = ROOT / "bindings/full-event-bed-audit-binding.json"
    binding_value = binding()
    binding_path.write_text(json.dumps(binding_value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    paths = source_inputs(binding_path)
    input_sha = {str(path): sha(path) for path in paths}
    request = {
        "schema": "ds02.runner-request.v2",
        "status": "disabled_until_actual_full_typed350_and_xmf351_metadata_bind",
        "family_id": "F5",
        "candidate_id": binding_value["candidate_id"],
        "condition_id": binding_value["condition_id"],
        "repair_id": binding_value["repair_id"],
        "case_id": CASE,
        "physical_case_id": PHYSICAL,
        "attempt_id": AUDIT_ATTEMPT,
        "depends_on_attempt": XMF_ATTEMPT,
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "worker_kind": "full_event_bed_footprint_audit",
        "launch_owner": "root",
        "cwd": str(INTEGRATION),
        "worktree_root": str(INTEGRATION.parent),
        "command": [str(PYTHON), str(WORKER), "--binding", str(binding_path), "--trajectory-h5", "<root-bind:full_trajectory_h5>", "--xdmf", "<root-bind:full_xdmf>", "--output-dir", "{attempt_root}/audit-output"],
        "input_files": [str(path) for path in paths],
        "input_sha256": input_sha,
        "input_sha256_provenance": {"source_metadata": "JSON/XML/Python hashes only", "future_h5_xmf": "producer-declared hashes only; source preparation did not open or rehash future H5/XMF", "science_array_policy": "no BI4/CSV/H5/VTK/DAT artifact is registered as an input"},
        "array_edit_allowed": False,
        "arrays_allowed": False,
        "source_only": True,
        "execution_allowed": False,
        "launch": False,
        "launch_allowed": False,
        "disabled": True,
        "solver_allowed": False,
        "conversion_allowed": False,
        "diagnostic_only": True,
        "production_approval": "none",
        "q_n_granted": False,
        "full16_authorized": False,
        "full801_authorized": False,
        "independent_case_count_increment": 0,
        "cpu_threads": 2,
        "max_wall_seconds": 7200,
        "estimated_peak_gpu_mib": 0,
        "estimated_storage_bytes": 34359738368,
        "expected_dimension": 3,
        "expected_frames": 801,
        "expected_particles": 194427,
        "expected_particle_axis": 194427,
        "expected_fixed_particles": 158559,
        "expected_moving_particles": 4210,
        "expected_floating_particles": 0,
        "expected_fluid_particles": 31658,
        "dp_m": 0.02,
        "time_window_s": [0.0, 16.0],
        "save_interval_s": 0.02,
        "penetration_bins_m": [0.02, 0.04],
        "bed_x_bounds_m": [-0.2, 4.8],
        "bed_y_bounds_m": [-0.22, 0.22],
        "native_bed_marker_mk": 50,
        "source_bed_marker_mkbound": 40,
        "actual_counts": actual_counts(),
        "binding_contract": {"schema": binding_value["schema"], "binding_path": str(binding_path.resolve()), "binding_sha256": sha(binding_path), "actual_counts_full_placement_copy": actual_counts(), "full_native_attempt": NATIVE_ATTEMPT, "full_typed_attempt": TYPED_ATTEMPT, "full_xmf_attempt": XMF_ATTEMPT, "future_h5_sha256": None, "future_xmf_sha256": None},
        "output_contract": {"scan_all_801_frames": True, "full_event_window_s": [0.0, 16.0], "scan_all_initial_fluid_uids_each_frame": True, "scope_exact_profile_x_and_bed_y": True, "report_one_dp_two_dp_count_fraction_depth": True, "report_nonfinite_and_lost_uid_unexplained": True, "thresholds_diagnostic_only": True, "native_bed_mk": 50, "source_mkbound": 40, "short_event_result_not_reused": True, "repair_success_not_inferred": True, "full801_authorized": False, "root_visual_review_required": True},
        "upstream_metadata": {"gencase_attempt": "root-stage1-f5-c082s1-solid-fluid-recovery-genuine-gencase-293", "stage1_placement_attempt": "root-stage1-f5-c082s1-solid-fluid-recovery-stage1-placement-mk50-audit-315", "bed321_attempt": BED_ATTEMPT, "native349_attempt": NATIVE_ATTEMPT, "native349_receipt_sha256": NATIVE_RECEIPT_SHA, "typed350_attempt": TYPED_ATTEMPT, "xmf351_attempt": XMF_ATTEMPT, "typed350_receipt": None, "typed350_conversion_report": None, "trajectory_h5": None, "xmf_manifest": None, "xdmf": None},
        "physical_condition_hash_semantics": binding_value["physical_condition_hash_semantics"],
        "future_output_hashes": None,
        "source_arrays_read_or_hashed_by_source_agent": False,
        "root_review_required": True,
        "resource_window": {"approval_sha256": sha(RESOURCE), "launch_owner": "root", "gpu_hours": 512, "cpu_core_hours": 3840, "qualification_attempts": 1024, "production_attempts": 720, "home_min_free_bytes": 536870912000, "deadline_utc": "2026-10-14T07:23:48+00:00", "profile": "root_home_floor_no_legacy_dataset_walk_v1"},
    }
    request_path = ROOT / "requests/full-bed-audit-request.json"
    request_path.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    contract = {
        "schema": "ds02.f5.c082s1.full801-bed-audit-contract.fresh098.v1",
        "status": "disabled_source_template",
        "attempt_id": AUDIT_ATTEMPT,
        "depends_on_attempt": XMF_ATTEMPT,
        "typed_attempt": TYPED_ATTEMPT,
        "native_attempt": NATIVE_ATTEMPT,
        "window_s": [0.0, 16.0],
        "frames": 801,
        "counts": actual_counts(),
        "bed_profile": {"x_m": [-0.2, 4.8], "y_m": [-0.22, 0.22], "depth_bins_m": [0.02, 0.04], "native_mk": 50, "source_mkbound": 40},
        "diagnostic_scope": "all full801 actual frames; exact x profile and y footprint; complete frame-zero fluid UID denominator; report finite/type/UID/lost/out-of-domain states without masking",
        "short_event_evidence_reused_as_pass": False,
        "future_h5_xmf_hashes": None,
        "full801_authorized": False,
        "case_increment": 0,
        "science_arrays_read_or_hashed_by_source_agent": False,
    }
    (ROOT / "metadata/full801-bed-audit-contract.json").write_text(json.dumps(contract, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (ROOT / "metadata/source-input-sha-summary.json").write_text(json.dumps({"schema":"ds02.f5.c082s1.fresh098.source-input-sha-summary.v1","status":"metadata_only","input_sha256":input_sha,"future_h5_xmf_hashes":None,"science_arrays_read_or_hashed_by_source_agent":False},indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print(json.dumps({"status":"fresh098_disabled_full801_bed_audit_written","request":str(request_path.resolve()),"binding":str(binding_path.resolve()),"inputs":len(paths),"typed_attempt":TYPED_ATTEMPT,"future_hashes":None},sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
