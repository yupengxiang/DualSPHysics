#!/usr/bin/env python3
"""Build the disabled Root575 full801 downstream source pack.

Only source code and JSON/XML metadata are read.  Generated BI4/CSV/DAT/H5/
VTK/solver products are represented by producer attestations or future bind
placeholders; this builder never opens or hashes those payloads.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

PKG = Path(__file__).resolve().parents[1]
HANDOFF = PKG.parent
FRESH097 = HANDOFF / "root_followup_097_stage1_f5_c082s1_full801_disabled_pipeline_v1"
FRESH098 = HANDOFF / "root_followup_098_stage1_f5_c082s1_full801_bed_audit_disabled_v1"
FRESH109 = HANDOFF / "root_followup_109_stage1_f5_c082s1_actual_bed_full801_disabled_v1"
FRESH111 = HANDOFF / "root_followup_111_stage1_f5_c082s1_full1201_gate_sidecar_v1"
FRESH114 = HANDOFF / "root_followup_114_stage1_f5_c082s1_actual_initial_qa_bound_native_disabled_v1"
DATA_CASE = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1")
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
CASE = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1"
TAGS = ("A080", "A120")
COUNTS = {
    "dimension": 3,
    "fixed": 158559,
    "floating": 0,
    "fluid": 31658,
    "moving": 4210,
    "total": 194427,
}
SCIENCE_SUFFIXES = {".dat", ".bi4", ".h5", ".hdf5", ".csv", ".vtk", ".vtu", ".npy", ".npz"}


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha_source(path: Path) -> str:
    if path.suffix.lower() in SCIENCE_SUFFIXES:
        raise ValueError(f"science payload hash forbidden: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source109(tag: str, name: str) -> Path:
    return FRESH109 / name.replace("{tag}", tag)


def source_native(tag: str) -> dict[str, Any]:
    return load(source109(tag, "requests/{tag}-full801-native-request.json"))


def source_phys(tag: str) -> dict[str, Any]:
    return load(source109(tag, "bindings/{tag}-physical-binding.json"))


def source_xmf_binding(tag: str) -> dict[str, Any]:
    return load(source109(tag, "bindings/{tag}-short-xmf-binding.json"))


def source_bed_binding(tag: str) -> dict[str, Any]:
    return load(source109(tag, "bindings/{tag}-short-bed-audit-binding.json"))


def root575_attempt(tag: str, kind: str) -> str:
    base = source_native(tag)["attempt_id"]
    if kind == "native":
        return f"{base}-root575"
    return f"root-stage1-f5-c082s1-{tag}-full801-native-{kind}-575"


def root575_gate() -> dict[str, Any]:
    return {
        "schema": "ds02.f5.c082s1.root574-to-root575-full801-gate.fresh115.v1",
        "status": "WAIT/root574_short_window_visual_review_record",
        "root574_short_window_visual_pass": None,
        "root574_receipt": None,
        "root574_report": None,
        "root574_receipt_sha256": None,
        "root574_report_sha256": None,
        "root575_native_launch_allowed": False,
        "root575_requires_manual_root_review": True,
        "short_window_can_authorize_current_A080_A120_full801_only_after_root574": True,
        "short_window_can_authorize_new_fresh110_full24s_1201": False,
        "six_fresh110_full24s_1201_gate": "WAIT/null",
        "future_receipts_and_hashes": None,
    }


def gencase_paths(tag: str) -> dict[str, Any]:
    native = source_native(tag)
    # These are producer-attested metadata values from source109; no generated
    # XML/BI4 payload is opened by this builder.
    return {
        "gencase_attempt_id": native.get("gencase_attempt_id"),
        "gencase_receipt": native.get("gencase_receipt"),
        "gencase_receipt_sha256": native.get("gencase_receipt_sha256"),
        "generated_xml": native.get("generated_xml"),
        "generated_xml_sha256": native.get("generated_xml_sha256"),
        "generated_bi4": "<root-bind:generated_bi4>",
        "generated_bi4_sha256": None,
        "gencase_prefix": native.get("gencase_prefix"),
        "prepared_input_report": str(DATA_CASE / f"root-stage1-f5-c082s1-{tag}-genuine-gencase-102/prepared/prepared-input-report.json"),
        "prepared_input_report_sha256": None,
    }


def local_path(rel: str) -> str:
    return str((PKG / rel).resolve())


def static_source_paths(tag: str, worker_paths: list[Path]) -> list[str]:
    native = source_native(tag)
    values = [
        local_path(f"bindings/{tag}-full801-physical-binding.json"),
        local_path(f"bindings/{tag}-full801-bed-audit-binding.json"),
        local_path(f"bindings/{tag}-full801-xmf-binding.json"),
        local_path(f"bindings/{tag}-full801-render-binding.json"),
        local_path(f"inputs/{tag}-Definition.xml"),
        local_path(f"inputs/{tag}-owner.json"),
        str(INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"),
        str(INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py"),
        str(INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_native_home_floor_eight_solver_dispatch_230/launch.py"),
        str(INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_native_home_floor_eight_solver_dispatch_230/root_native_home_floor_inventory_policy.py"),
        str(INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json"),
        str(INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_nvme_convert_v1.py"),
        str(INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_native_renderer_proxy_lifetime_diagnostic_023/render.py"),
        str(DATA_CASE / f"root-stage1-f5-c082s1-{tag}-genuine-gencase-102/execution-receipt.json"),
        str(DATA_CASE / f"root-stage1-f5-c082s1-{tag}-genuine-gencase-102/prepared/prepared-input-report.json"),
        native.get("generated_xml"),
        "<root-bind:generated_bi4>",
        "<root-bind:root574_gate_receipt>",
        "<root-bind:root574_gate_report>",
    ]
    values.extend(str(path) for path in worker_paths)
    # Preserve order while removing empty/duplicate entries.
    result: list[str] = []
    for value in values:
        if not value or value in result:
            continue
        result.append(value)
    return result


def metadata_hashes(paths: list[str], attested: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    attested = attested or {}
    hashes: dict[str, Any] = {}
    provenance: dict[str, Any] = {}
    for raw in paths:
        if raw.startswith("<root-bind:"):
            hashes[raw] = None
            provenance[raw] = "future Root575/root574 binding; remains null in source package"
            continue
        path = Path(raw)
        if path.suffix.lower() in SCIENCE_SUFFIXES:
            hashes[raw] = attested.get(raw)
            provenance[raw] = "producer-attested payload digest; source builder did not open or rehash payload"
            continue
        # A generated GenCase XML under DATA is a producer artifact.  Its
        # digest may be supplied by the immutable source109 attestation, but
        # this source-only builder must never open or rehash it.  Keeping a
        # missing attestation null is safer than silently turning a future
        # producer file into a source read.
        if path.suffix.lower() == ".xml" and str(DATA_CASE) in raw:
            hashes[raw] = attested.get(raw)
            provenance[raw] = "producer-attested generated XML; source builder did not open or rehash artifact"
            continue
        if raw in attested:
            hashes[raw] = attested[raw]
            provenance[raw] = "producer-attested metadata digest"
            continue
        if path.exists():
            hashes[raw] = sha_source(path)
            provenance[raw] = "source/JSON metadata hash"
        else:
            hashes[raw] = None
            provenance[raw] = "future or external runtime input; no source read"
    return hashes, provenance


def write_workers(tag: str) -> tuple[Path, Path]:
    template = (FRESH098 / "workers/bed_audit_full801.py").read_text(encoding="utf-8")
    src_phys = source_phys(tag)
    src_xmf = source_xmf_binding(tag)
    replacements = {
        'BINDING_SCHEMA = "ds02.f5.c082s1.full-event-bed-audit-binding.fresh098.v1"': 'BINDING_SCHEMA = "ds02.f5.c082s1.full-event-bed-audit-binding.fresh115.v1"',
        'SCHEMA = "ds02.f5.c082s1.full-event-bed-footprint-audit.fresh098.v1"': 'SCHEMA = "ds02.f5.c082s1.full-event-bed-footprint-audit.fresh115.v1"',
        "PHYSICAL_CASE_ID = 'F5_COMPACT_STILL_WATER_RUNUP_RECOVERY_C082S1'": f"PHYSICAL_CASE_ID = {src_phys['physical_case_id']!r}",
        "CANONICAL_PHYSICAL_CONDITION_SHA256 = 'e691d030eda575b9cfabe62f295c9bdc142e5a04cb4357c9fe2790aaec549dbf'": f"CANONICAL_PHYSICAL_CONDITION_SHA256 = {src_phys['physical_condition_sha256']!r}",
        "SOURCE_PLAN_PHYSICAL_CONDITION_SHA256 = '5bad3ec9f9a71aa87da8272003c357f4523d4ffa164d3f06e5d25fee1a4fbfa6'": f"SOURCE_PLAN_PHYSICAL_CONDITION_SHA256 = {src_phys['source_plan_physical_condition_sha256']!r}",
        "SOURCE_H5_PHYSICAL_CONDITION_SHA256 = '3cd1ceab16be11428bbc1011a1b4e297c384d8c7926432c222c254064744ccd0'": f"SOURCE_H5_PHYSICAL_CONDITION_SHA256 = {src_xmf['source_h5_physical_condition_sha256']!r}",
    }
    for old, new in replacements.items():
        if old not in template:
            raise ValueError(f"worker replacement missing: {old}")
        template = template.replace(old, new)
    out = PKG / "workers" / f"bed_audit_{tag}_full801.py"
    out.write_text(template, encoding="utf-8")
    return out, PKG / "workers/export_xmf_legacy_aware.py"


def make_gate_fields(gate: dict[str, Any]) -> dict[str, Any]:
    return {
        "root574_gate": gate,
        "full801_authorized": False,
        "full16_authorized": False,
        "q_n_granted": False,
        "independent_case_count_increment": 0,
        "production_approval": "none",
    }


def make_physical_binding(tag: str) -> dict[str, Any]:
    binding = source_phys(tag)
    binding["schema"] = "ds02.f5.c082s1.full801-physical-binding.fresh115.v1"
    binding["physical_binding_path"] = local_path(f"bindings/{tag}-full801-physical-binding.json")
    binding["source_preparation"] = {
        **(binding.get("source_preparation") or {}),
        "source_only_package": "fresh115",
        "same_recipe_as_fresh109": True,
        "root575_native_future": True,
        "science_payloads_read_or_hashed_by_source_builder": False,
    }
    return binding


def make_native_binding(tag: str, gate: dict[str, Any], paths: dict[str, Any]) -> dict[str, Any]:
    native = source_native(tag)
    physical = source_phys(tag)
    binding = {
        "schema": "ds02.f5.c082s1.root575-full801-native-binding.fresh115.v1",
        "source_only": True,
        "candidate_id": native["candidate_id"],
        "case_id": CASE,
        "condition_id": native["condition_id"],
        "physical_case_id": physical["physical_case_id"],
        "physical_condition_sha256": physical["physical_condition_sha256"],
        "source_plan_physical_condition_sha256": physical["source_plan_physical_condition_sha256"],
        "source_mkbound": 40,
        "native_bed_mk": 50,
        "actual_counts": native["actual_counts"],
        "expected_frames": 801,
        "time_window_s": [0.0, 16.0],
        "save_interval_s": 0.02,
        "gencase": paths,
        "motion_asset_path": native.get("motion_asset_path"),
        "motion_asset_sha256": native.get("motion_asset_sha256"),
        "motion_asset_provenance": "fresh109 producer-attested source metadata; source115 did not read DAT",
        "root575_attempt_id": root575_attempt(tag, "native"),
        "root575_gate": gate,
        "future_native_receipt": None,
        "future_solver_output": None,
        "future_output_hashes": None,
        "full801_authorized": False,
        "root_review_required": True,
        "source_agent_did_not_read_science_payloads": True,
        "numerical_precision_negative": {"classification": "numerical_precision", "max_residual_cells": 5.000000015797923e-06, "threshold_cells": 1e-06, "accepted": False},
    }
    return binding


def make_xmf_binding(tag: str, gate: dict[str, Any], native_bind: dict[str, Any], binding_path: Path) -> dict[str, Any]:
    src = source_xmf_binding(tag)
    physical = source_phys(tag)
    native_attempt = root575_attempt(tag, "native")
    typed_attempt = root575_attempt(tag, "typed")
    return {
        "schema": "ds02.f5.c082s1.legacy-aware-xmf-binding.fresh115.v1",
        "candidate_id": src["candidate_id"], "case_id": CASE, "condition_id": src["condition_id"],
        "physical_case_id": physical["physical_case_id"], "physical_condition_sha256": physical["physical_condition_sha256"],
        "physical_condition_hash_semantics": src["physical_condition_hash_semantics"],
        "source_h5_physical_condition_sha256": src["source_h5_physical_condition_sha256"],
        "source_h5_scope_schema": src["source_h5_scope_schema"], "source_h5_scope_status": src["source_h5_scope_status"],
        "source_plan_physical_condition_sha256": physical["source_plan_physical_condition_sha256"],
        "source_mkbound": 40, "native_bed_marker_mk": 50,
        "native_attempt_id": native_attempt, "native_receipt": "<root-bind:full_native_receipt>", "native_receipt_sha256": None,
        "typed_attempt_id": typed_attempt, "typed_receipt": "<root-bind:full_typed_receipt>", "typed_receipt_sha256": None,
        "conversion_report": "<root-bind:full_typed_report>", "conversion_report_sha256": None,
        "trajectory_h5": "<root-bind:full_trajectory_h5>", "trajectory_h5_sha256": None,
        "typed_identity": None, "native_fields_preserved": True,
        "expected_dimension": 3, "expected_frames": 801, "expected_particles": 194427,
        "physical_window_s": [0.0, 16.0],
        "future_output_hashes": {"xmf_manifest_sha256": None, "xmf_receipt_sha256": None, "xmf_sha256": None, "xdmf_sha256": None},
        "xmf_actual": None, "visual_status": "pending Root575 actual full801 product and Root023 review",
        "root575_gate": gate, "full801_authorized": False, "q_n_granted": False,
        "binding_path": str(binding_path), "source_agent_did_not_read_science_payloads": True,
    }


def make_bed_binding(tag: str, gate: dict[str, Any], native_bind: dict[str, Any], xmf_bind: dict[str, Any]) -> dict[str, Any]:
    src = source_bed_binding(tag)
    physical = source_phys(tag)
    paths = gencase_paths(tag)
    native_attempt = root575_attempt(tag, "native")
    typed_attempt = root575_attempt(tag, "typed")
    xmf_attempt = root575_attempt(tag, "xmf")
    return {
        "schema": "ds02.f5.c082s1.full-event-bed-audit-binding.fresh115.v1",
        "candidate_id": src["candidate_id"], "case_id": CASE, "condition_id": src["condition_id"],
        "physical_case_id": physical["physical_case_id"], "physical_condition_sha256": physical["physical_condition_sha256"],
        "physical_condition_hash_semantics": src["physical_condition_hash_semantics"],
        "source_h5_physical_condition_sha256": src["source_h5_physical_condition_sha256"],
        "source_h5_scope_schema": src["source_h5_scope_schema"], "source_h5_scope_status": src["source_h5_scope_status"],
        "source_plan_physical_condition_sha256": physical["source_plan_physical_condition_sha256"],
        "source_bed_marker_mkbound": 40, "native_bed_marker_mk": 50,
        "bed_x_bounds_m": [-0.2, 4.8], "bed_y_bounds_m": [-0.22, 0.22], "penetration_bins_m": [0.02, 0.04],
        "full_event": {"frames": 801, "window_s": [0.0, 16.0], "save_interval_s": 0.02, "short_event_result_reused": False},
        "actual_counts": src["actual_counts"], "expected_particle_axis": 194427, "expected_frames": 801,
        "expected_dimension": 3, "expected_fixed_particles": 158559, "expected_floating_particles": 0,
        "expected_fluid_particles": 31658, "expected_moving_particles": 4210, "expected_total_particles": 194427,
        "gencase_attempt_id": paths["gencase_attempt_id"], "gencase_receipt": paths["gencase_receipt"],
        "gencase_receipt_sha256": paths["gencase_receipt_sha256"], "gencase_prepared_report": paths["prepared_input_report"],
        "gencase_prepared_report_sha256": paths["prepared_input_report_sha256"], "canonical_generated_xml": paths["generated_xml"],
        "canonical_generated_xml_sha256": paths["generated_xml_sha256"],
        # The output-root path is metadata, but the binding field is an
        # attempt identity.  Preserve the real producer attempt basename
        # instead of putting a filesystem path into an *_attempt_id field.
        "initial_qa_attempt_id": Path(src["initial_qa_output_root"]).name if src.get("initial_qa_output_root") else None,
        "initial_qa_receipt": src.get("initial_qa_receipt"),
        "initial_qa_receipt_sha256": src.get("initial_qa_receipt_sha256"), "initial_qa_report": src.get("initial_qa_report"),
        "initial_qa_report_sha256": src.get("initial_qa_report_sha256"),
        "full_native_attempt_id": native_attempt, "full_native_receipt": "<root-bind:full_native_receipt>", "full_native_receipt_sha256": None,
        "full_typed_attempt_id": typed_attempt, "full_typed_receipt": "<root-bind:full_typed_receipt>", "full_typed_receipt_sha256": None,
        "full_typed_conversion_report": "<root-bind:full_typed_report>", "full_typed_conversion_report_sha256": None,
        "full_xmf_attempt_id": xmf_attempt, "xmf_receipt": "<root-bind:full_xmf_receipt>", "xmf_receipt_sha256": None,
        "xmf_manifest": "<root-bind:full_xmf_manifest>", "xmf_manifest_sha256": None,
        "xdmf": "<root-bind:full_xdmf>", "xdmf_sha256": None, "trajectory_h5": "<root-bind:full_trajectory_h5>",
        "trajectory_h5_sha256": None,
        "future_output_hashes": {"bed_audit_report_sha256": None, "typed_h5_sha256": None, "typed_receipt_sha256": None, "xmf_manifest_sha256": None},
        "stage1_placement": {"initial_qa_report": src.get("initial_qa_report"), "initial_qa_report_sha256": src.get("initial_qa_report_sha256"), "native_mk50": 50, "precision_negative_retained": True},
        "root575_gate": gate, "full801_authorized": False, "repair_success": "unknown_until_actual_full801_particle_audit_and_root_review",
        "dynamic_worker_started_by_binder": False, "science_arrays_read_by_binder": False, "science_arrays_hashed_by_binder": False,
        "q_n_granted": False, "status": "disabled_until_root575_full801_typed_xmf_and_root_review",
        "worker_contract": {"scan_all_801_frames": True, "complete_frame_zero_fluid_uid_denominator": True, "exact_profile_x_and_y_footprint": True, "missing_uid_and_nonfinite_per_frame": True, "one_dp_two_dp_counts_fractions_depths": True, "thresholds_diagnostic_only": True, "short_event_result_reused_as_pass": False, "native_bed_mk50_source_mkbound40": True},
    }


def make_render_binding(tag: str, gate: dict[str, Any], bed_bind: dict[str, Any]) -> dict[str, Any]:
    physical = source_phys(tag)
    return {
        "schema": "ds02.f5.c082s1.root023-full801-render-binding.fresh115.v1",
        "candidate_id": f"C082S1_MOTION_{tag}", "case_id": CASE, "physical_case_id": physical["physical_case_id"],
        "physical_condition_sha256": physical["physical_condition_sha256"], "native_bed_mk": 50, "source_mkbound": 40,
        "expected_frames": 801, "expected_particles": 194427, "expected_dimension": 3,
        "xmf_manifest": "<root-bind:full_xmf_manifest>", "render_report": "<root-bind:full_render_report>",
        "future_output_hashes": {"render_report_sha256": None, "frame_hashes": None},
        "camera_bounds": None, "domain_bounds": None, "camera_bounds_policy": "auto_scan_all_actual_valid_native_points",
        "native_fields_preserved": True, "native_time_axis_preserved": True, "no_particle_clipping_or_reader_filtering": True,
        "root023_renderer_sha256": "5e78f7b92ad7c6f1d15902e3ccacc9099affb04b1b992a42f540eb88241bde66",
        "root575_gate": gate, "full801_authorized": False, "visual_review_required": True, "derived_view_only": True,
        "bed_binding": local_path(f"bindings/{tag}-full801-bed-audit-binding.json"), "bed_binding_sha256": None,
        "science_arrays_read_or_hashed_by_source_builder": False,
    }


def base_gate_fields(req: dict[str, Any], gate: dict[str, Any]) -> None:
    req.update({
        "disabled": True, "execution_allowed": False, "launch": False, "launch_allowed": False,
        "solver_allowed": False, "full16_authorized": False, "full801_authorized": False,
        "q_n_granted": False, "independent_case_count_increment": 0, "root_review_required": True,
        "root575_gate": gate, "source_only": True, "source_arrays_read_or_hashed_by_source_agent": False,
        "production_approval": "none", "status": "disabled_until_root575_actual_outputs_and_root_review",
    })


def make_native_request(tag: str, gate: dict[str, Any], phys_path: Path, phys_sha: str) -> dict[str, Any]:
    req = copy.deepcopy(source_native(tag))
    paths = gencase_paths(tag)
    physical = source_phys(tag)
    native_attempt = root575_attempt(tag, "native")
    req["attempt_id"] = native_attempt
    req["binding"] = str(phys_path)
    req["binding_sha256"] = phys_sha
    req["physical_binding_path"] = str(phys_path)
    req["physical_binding_sha256"] = phys_sha
    req["physical_case_id"] = physical["physical_case_id"]
    req["physical_condition_sha256"] = physical["physical_condition_sha256"]
    req["source_plan_physical_condition_sha256"] = physical["source_plan_physical_condition_sha256"]
    req["gencase_attempt_id"] = paths["gencase_attempt_id"]
    req["gencase_receipt"] = paths["gencase_receipt"]
    req["gencase_receipt_sha256"] = paths["gencase_receipt_sha256"]
    req["generated_xml"] = paths["generated_xml"]
    req["generated_xml_sha256"] = paths["generated_xml_sha256"]
    req["generated_bi4"] = paths["generated_bi4"]
    req["generated_bi4_sha256"] = paths["generated_bi4_sha256"]
    req["prepared_input_report"] = paths["prepared_input_report"]
    req["prepared_input_report_sha256"] = paths["prepared_input_report_sha256"]
    req["depends_on_attempt"] = "<root-bind:root574_full801_enablement>"
    req["depends_on_attempts"] = ["<root-bind:root574_full801_enablement>"]
    req["actual_native_result"] = {"status": "WAIT/null", "receipt": None, "receipt_sha256": None, "returncode": None, "solver_output": None, "all_801_saved_states": None}
    req["future_output_hashes"] = {"solver_receipt_sha256": None, "solver_stdout_sha256": None, "solver_data_manifest_sha256": None, "solver_part_count": None, "typed_receipt_sha256": None, "xmf_receipt_sha256": None, "bed_audit_receipt_sha256": None}
    req["full801_gate"] = "WAIT/root574_short_window_visual_review_record"
    req["short_bed_audit"] = None
    req["short_visual_review"] = {"status": "WAIT/root574_record_not_bound_in_source_pack", "receipt": None, "report": None}
    worker_paths = [PKG / f"workers/bed_audit_{tag}_full801.py", PKG / "workers/export_xmf_legacy_aware.py"]
    req["input_files"] = static_source_paths(tag, worker_paths)
    attested = {paths["generated_xml"]: paths["generated_xml_sha256"], paths["gencase_receipt"]: paths["gencase_receipt_sha256"]}
    req["input_sha256"], req["input_sha256_provenance"] = metadata_hashes(req["input_files"], attested)
    req["input_sha256"][str(phys_path)] = phys_sha
    req["input_sha256_provenance"][str(phys_path)] = "fresh115 physical-binding JSON hash"
    base_gate_fields(req, gate)
    return req


def make_typed_request(tag: str, gate: dict[str, Any], phys_path: Path, phys_sha: str) -> dict[str, Any]:
    req = copy.deepcopy(load(FRESH097 / "requests/full-typed-801-request.json"))
    native = source_native(tag); physical = source_phys(tag); paths = gencase_paths(tag)
    native_attempt = root575_attempt(tag, "native"); attempt = root575_attempt(tag, "typed")
    owner_path = PKG / "metadata" / f"{tag}-full801-typed-owner.json"
    owner = {"schema": "ds02.f5.c082s1.full801-typed-owner.fresh115.v1", "candidate_id": native["candidate_id"], "physical_case_id": physical["physical_case_id"], "physical_condition_sha256": physical["physical_condition_sha256"], "source_h5_scope_schema": source_xmf_binding(tag)["source_h5_scope_schema"], "source_h5_scope_status": source_xmf_binding(tag)["source_h5_scope_status"], "owner_status": "future Root575 conversion producer", "actual_conversion_report": None, "actual_typed_receipt": None, "actual_trajectory_h5": None, "future_hashes": None, "source_payloads_read_or_hashed_by_builder": False}
    dump(owner_path, owner)
    req.update({
        "attempt_id": attempt, "candidate_id": native["candidate_id"], "case_id": CASE, "condition_id": native["condition_id"],
        "depends_on_attempt": native_attempt, "actual_native_dependency": {"attempt_id": native_attempt, "receipt": "<root-bind:full_native_receipt>", "receipt_sha256": None, "status": "WAIT/null"},
        "physical_binding_path": str(phys_path), "physical_binding_sha256": phys_sha, "physical_case_id": physical["physical_case_id"], "physical_condition_sha256": physical["physical_condition_sha256"], "source_plan_physical_condition_sha256": physical["source_plan_physical_condition_sha256"],
        "owner_metadata": str(owner_path), "native_bed_marker_mk": 50, "source_bed_marker_mkbound": 40,
        "expected_frames": 801, "expected_particles": 194427, "expected_particle_axis": 194427, "expected_dimension": 3, "expected_fixed_particles": 158559, "expected_floating_particles": 0, "expected_fluid_particles": 31658, "expected_moving_particles": 4210,
        "gencase_receipt": paths["gencase_receipt"], "gencase_receipt_sha256": paths["gencase_receipt_sha256"], "prepared_input_report": paths["prepared_input_report"], "prepared_input_report_sha256": paths["prepared_input_report_sha256"],
        "full_event_gate": {"root574_gate": gate, "manual_root_review_required": True, "full801_authorized": False},
        "future_bindings": {"native_receipt": "<root-bind:full_native_receipt>", "typed_receipt": "<root-bind:full_typed_receipt>", "trajectory_h5": "<root-bind:full_trajectory_h5>", "conversion_report": "<root-bind:full_typed_report>", "all_future_hashes": None},
        "future_output_hashes": {"typed_receipt_sha256": None, "conversion_report_sha256": None, "trajectory_h5_sha256": None},
        "motion_window_s": [0.0, 16.0], "time_window_s": [0.0, 16.0], "save_interval_s": 0.02,
        "status": "disabled_until_root575_actual_native_receipt", "source_arrays_read_or_hashed_by_source_agent": False,
    })
    req["command"] = [str(INTEGRATION / "lagrangian-fluid-lab/.venv/bin/python"), str(INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_nvme_convert_v1.py"), "--staging-root", "/tmp/ds02-nvme-conversion", "--staging-limit-bytes", "25769803776", "--", "--data-root", "<root-bind:full_solver_data_root>", "--generated-xml", paths["generated_xml"], "--output", "<root-bind:full_trajectory_h5>", "--report", "<root-bind:full_typed_report>", "--decoder", "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump", "--partvtk", "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64", "--validation-dir", "{attempt_root}/partvtk-validation", "--solver-receipt", "<root-bind:full_native_receipt>", "--gencase-receipt", paths["gencase_receipt"], "--owner-metadata", str(owner_path), "--particle-chunk", "65536"]
    worker_paths = [PKG / "workers/export_xmf_legacy_aware.py"]
    req["input_files"] = static_source_paths(tag, worker_paths) + [str(owner_path), "<root-bind:full_native_receipt>", "<root-bind:full_solver_data_root>", "<root-bind:full_solver_log>"]
    attested = {paths["generated_xml"]: paths["generated_xml_sha256"], paths["gencase_receipt"]: paths["gencase_receipt_sha256"]}
    req["input_sha256"], req["input_sha256_provenance"] = metadata_hashes(req["input_files"], attested)
    req["input_sha256"][str(phys_path)] = phys_sha; req["input_sha256_provenance"][str(phys_path)] = "fresh115 physical-binding JSON hash"
    req["input_sha256"][str(owner_path)] = sha_source(owner_path); req["input_sha256_provenance"][str(owner_path)] = "fresh115 owner metadata hash"
    base_gate_fields(req, gate); req["kind"] = "cpu"; req["cpu_task_kind"] = "conversion"; req["conversion_allowed"] = False
    return req


def make_xmf_request(tag: str, gate: dict[str, Any], xmf_path: Path, xmf_sha: str, phys_path: Path, phys_sha: str) -> dict[str, Any]:
    req = copy.deepcopy(load(FRESH097 / "requests/full-xmf-801-request.json"))
    native = source_native(tag); physical = source_phys(tag); attempt = root575_attempt(tag, "xmf"); typed = root575_attempt(tag, "typed"); native_attempt = root575_attempt(tag, "native")
    req.update({"attempt_id": attempt, "candidate_id": native["candidate_id"], "case_id": CASE, "condition_id": native["condition_id"], "depends_on_attempt": typed, "physical_binding_path": str(phys_path), "physical_binding_sha256": phys_sha, "binding": str(xmf_path), "binding_sha256": xmf_sha, "physical_case_id": physical["physical_case_id"], "physical_condition_sha256": physical["physical_condition_sha256"], "canonical_condition_sha256": physical["physical_condition_sha256"], "source_plan_physical_condition_sha256": physical["source_plan_physical_condition_sha256"], "native_bed_marker_mk": 50, "source_bed_marker_mkbound": 40, "expected_frames": 801, "expected_particles": 194427, "expected_particle_axis": 194427, "expected_dimension": 3, "full_event_gate": {"root574_gate": gate, "manual_root_review_required": True, "full801_authorized": False}, "actual_native_dependency": {"attempt_id": native_attempt, "receipt": "<root-bind:full_native_receipt>", "receipt_sha256": None, "status": "WAIT/null"}, "future_bindings": {"native_receipt": "<root-bind:full_native_receipt>", "typed_receipt": "<root-bind:full_typed_receipt>", "conversion_report": "<root-bind:full_typed_report>", "case_xmf": "<root-bind:full_xdmf>", "xmf_manifest": "<root-bind:full_xmf_manifest>", "all_future_hashes": None}, "future_output_hashes": {"xmf_manifest_sha256": None, "xmf_receipt_sha256": None, "xmf_sha256": None, "xdmf_sha256": None}, "status": "disabled_until_root575_actual_typed_receipt", "source_arrays_read_or_hashed_by_source_agent": False, "source_agent_did_not_read_science_payloads": True})
    req["command"] = [str(INTEGRATION / "lagrangian-fluid-lab/.venv/bin/python"), str(PKG / "workers/export_xmf_legacy_aware.py"), "--binding", "<root-bind:full_xmf_binding>", "--output-dir", "{attempt_root}/xmf"]
    req["input_files"] = static_source_paths(tag, [PKG / "workers/export_xmf_legacy_aware.py"]) + [str(xmf_path), "<root-bind:full_typed_receipt>", "<root-bind:full_typed_report>", "<root-bind:full_trajectory_h5>", "<root-bind:full_native_receipt>"]
    req["input_sha256"], req["input_sha256_provenance"] = metadata_hashes(req["input_files"], {str(source_native(tag).get("generated_xml")): source_native(tag).get("generated_xml_sha256")})
    req["input_sha256"][str(xmf_path)] = xmf_sha; req["input_sha256_provenance"][str(xmf_path)] = "fresh115 XMF binding JSON hash"
    base_gate_fields(req, gate); req["kind"] = "cpu"; req["cpu_task_kind"] = "audit"; req["conversion_allowed"] = False; req["derived_view_only"] = True
    return req


def make_bed_request(tag: str, gate: dict[str, Any], bed_path: Path, bed_sha: str, phys_path: Path, phys_sha: str, xmf_path: Path, xmf_sha: str) -> dict[str, Any]:
    src = source_bed_binding(tag); native = source_native(tag); physical = source_phys(tag); attempt = root575_attempt(tag, "bed-audit"); native_attempt = root575_attempt(tag, "native"); typed = root575_attempt(tag, "typed"); xmf = root575_attempt(tag, "xmf")
    runtime = load(source109(tag, "requests/{tag}-bed-audit-request.json"))
    req = {
        "schema": "ds02.runner-request.v2", "attempt_id": attempt, "candidate_id": native["candidate_id"], "case_id": CASE, "condition_id": native["condition_id"], "family_id": "F5", "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 2, "launch_owner": "root", "cwd": str(INTEGRATION / "lagrangian-fluid-lab"), "worktree_root": str(PKG.parents[6]) if len(PKG.parents) > 6 else str(PKG),
        "disabled": True, "execution_allowed": False, "launch": False, "launch_allowed": False, "solver_allowed": False, "conversion_allowed": False, "arrays_allowed": False, "array_edit_allowed": False,
        "estimated_peak_gpu_mib": 0, "estimated_storage_bytes": runtime.get("estimated_storage_bytes"), "max_wall_seconds": runtime.get("max_wall_seconds"),
        "resource_window": runtime.get("resource_window"), "strict_dispatch_source": runtime.get("strict_dispatch_source"), "root_inventory_policy_source": runtime.get("root_inventory_policy_source"), "root_inventory_policy_source_sha256": runtime.get("root_inventory_policy_source_sha256"), "root_inventory_profile": runtime.get("root_inventory_profile"), "shared_registry_write_allowed": False,
        "command": [str(INTEGRATION / "lagrangian-fluid-lab/.venv/bin/python"), str(PKG / f"workers/bed_audit_{tag}_full801.py"), "--binding", str(bed_path), "--output", "{attempt_root}/audit-output"],
        "binding": str(bed_path), "binding_sha256": bed_sha, "physical_binding_path": str(phys_path), "physical_binding_sha256": phys_sha,
        "depends_on_attempt": xmf, "depends_on_attempts": [xmf], "native_attempt_id": native_attempt, "typed_attempt_id": typed, "xmf_attempt_id": xmf,
        "native_receipt": "<root-bind:full_native_receipt>", "native_receipt_sha256": None, "trajectory_h5": "<root-bind:full_trajectory_h5>", "trajectory_h5_sha256": None, "xmf_manifest": "<root-bind:full_xmf_manifest>", "xmf_manifest_sha256": None,
        "physical_case_id": physical["physical_case_id"], "physical_condition_sha256": physical["physical_condition_sha256"], "source_plan_physical_condition_sha256": physical["source_plan_physical_condition_sha256"], "source_mkbound": 40, "native_bed_mk": 50,
        "actual_counts": {"dimension": 3, "fixed": 158559, "floating": 0, "fluid": 31658, "moving": 4210, "total": 194427}, "expected_dimension": 3, "expected_frames": 801, "expected_particle_axis": 194427, "expected_particles": 194427, "expected_fixed_particles": 158559, "expected_floating_particles": 0, "expected_fluid_particles": 31658, "expected_moving_particles": 4210, "fluid_type_code": 3,
        "bed_x_bounds_m": [-0.2, 4.8], "bed_y_bounds_m": [-0.22, 0.22], "penetration_bins_m": [0.02, 0.04], "time_window_s": [0.0, 16.0], "save_interval_s": 0.02,
        "diagnostic_only": True, "dynamic_acceptance": "not granted; Root must review every full801 frame, report, and Root023 visual render", "full801_authorized": False, "full16_authorized": False, "q_n_granted": False, "independent_case_count_increment": 0, "no_new_case_credit": True,
        "future_candidate_fields_remain_null": True, "future_output_hashes": {"bed_audit_report_sha256": None, "bed_audit_receipt_sha256": None, "xmf_manifest_sha256": None, "typed_receipt_sha256": None}, "root575_gate": gate, "root_review_required": True, "production_approval": "none", "source_only": True, "source_agent_did_not_read_science_payloads": True,
        "output_contract": {"scan_all_801_frames": True, "scope_exact_profile_x_and_bed_y": True, "full_initial_fluid_uid_denominator": True, "report_one_dp_two_dp_count_fraction_depth": True, "report_nonfinite_and_lost_uid_unexplained": True, "thresholds_diagnostic_only": True, "short_event_result_not_reused": True, "repair_success_not_inferred": True},
        "status": "disabled_until_root575_actual_xmf_and_typed_metadata",
    }
    req["input_files"] = static_source_paths(tag, [PKG / f"workers/bed_audit_{tag}_full801.py"]) + [str(bed_path), str(xmf_path), "<root-bind:full_xmf_manifest>", "<root-bind:full_trajectory_h5>", "<root-bind:full_native_receipt>"]
    gen = gencase_paths(tag)
    attested = {gen["generated_xml"]: gen["generated_xml_sha256"], gen["gencase_receipt"]: gen["gencase_receipt_sha256"]}
    req["input_sha256"], req["input_sha256_provenance"] = metadata_hashes(req["input_files"], attested)
    req["input_sha256"][str(bed_path)] = bed_sha; req["input_sha256_provenance"][str(bed_path)] = "fresh115 bed binding JSON hash"
    req["input_sha256"][str(phys_path)] = phys_sha; req["input_sha256_provenance"][str(phys_path)] = "fresh115 physical binding JSON hash"
    req["input_sha256"][str(xmf_path)] = xmf_sha; req["input_sha256_provenance"][str(xmf_path)] = "fresh115 XMF binding JSON hash"
    return req


def make_render_request(tag: str, gate: dict[str, Any], render_path: Path, render_sha: str, phys_path: Path, phys_sha: str, xmf_path: Path, xmf_sha: str, bed_path: Path, bed_sha: str) -> dict[str, Any]:
    native = source_native(tag); physical = source_phys(tag); attempt = root575_attempt(tag, "render"); xmf = root575_attempt(tag, "xmf")
    req = copy.deepcopy(load(FRESH097 / "requests/full-render-root023-801-request.json"))
    req.update({"attempt_id": attempt, "candidate_id": native["candidate_id"], "case_id": CASE, "condition_id": native["condition_id"], "depends_on_attempt": xmf, "physical_binding_path": str(phys_path), "physical_binding_sha256": phys_sha, "physical_case_id": physical["physical_case_id"], "physical_condition_sha256": physical["physical_condition_sha256"], "expected_frames": 801, "expected_particles": 194427, "expected_particle_axis": 194427, "expected_dimension": 3, "native_bed_marker_mk": 50, "source_mkbound": 40, "full801_authorized": False, "full16_authorized": False, "root575_gate": gate, "future_bindings": {"xmf_manifest": "<root-bind:full_xmf_manifest>", "render_report": "<root-bind:full_render_report>", "all_future_hashes": None}, "future_output_hashes": {"render_report_sha256": None, "frame_hashes": None}, "full_event_gate": {"root574_gate": gate, "manual_root_visual_review_required": True, "full801_authorized": False}, "status": "disabled_until_root575_actual_xmf_and_root023_review", "source_agent_did_not_read_science_payloads": True, "camera_bounds": None, "domain_bounds": None, "camera_bounds_policy": "auto_scan_all_actual_valid_native_points", "derived_view_only": True})
    req["binding"] = str(render_path); req["binding_sha256"] = render_sha
    req["command"] = ["/home/jade/ParaView-6.1.1-MPI-Linux-Python3.12-x86_64/bin/pvpython", "--force-offscreen-rendering", str(INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_native_renderer_proxy_lifetime_diagnostic_023/render.py"), "--manifest", "<root-bind:full_xmf_manifest>", "--output-dir", "{attempt_root}/render"]
    req["input_files"] = static_source_paths(tag, []) + [str(render_path), str(xmf_path), str(bed_path), "<root-bind:full_xmf_manifest>"]
    gen = gencase_paths(tag)
    attested = {gen["generated_xml"]: gen["generated_xml_sha256"], gen["gencase_receipt"]: gen["gencase_receipt_sha256"]}
    req["input_sha256"], req["input_sha256_provenance"] = metadata_hashes(req["input_files"], attested)
    req["input_sha256"][str(render_path)] = render_sha; req["input_sha256_provenance"][str(render_path)] = "fresh115 render binding JSON hash"
    req["input_sha256"][str(xmf_path)] = xmf_sha; req["input_sha256_provenance"][str(xmf_path)] = "fresh115 XMF binding JSON hash"
    req["input_sha256"][str(bed_path)] = bed_sha; req["input_sha256_provenance"][str(bed_path)] = "fresh115 bed binding JSON hash"
    base_gate_fields(req, gate); req["kind"] = "cpu"; req["cpu_task_kind"] = "audit"; req["solver_allowed"] = False; req["conversion_allowed"] = False; req["renderer_sha256"] = "5e78f7b92ad7c6f1d15902e3ccacc9099affb04b1b992a42f540eb88241bde66"
    return req


def write_manifest() -> None:
    files: dict[str, str] = {}
    for path in sorted(PKG.rglob("*")):
        if not path.is_file() or path.name in {"manifest.json", "fresh115-validator-report.json"}:
            continue
        if path.suffix.lower() in SCIENCE_SUFFIXES:
            raise ValueError(f"science payload in fresh115: {path}")
        files[str(path.relative_to(PKG))] = sha_source(path)
    dump(PKG / "manifest.json", {"schema": "ds02.f5.c082s1.fresh115-source-manifest.v1", "status": "root575_full801_downstream_disabled_root574_gate_wait", "files": files, "validator_report_excluded_from_manifest": True, "source109_modified": False, "source097_modified": False, "source098_modified": False, "fresh110_full24_gate": "WAIT/null", "full801_authorized": False, "future_receipts_and_hashes_null": True, "science_payloads_read_or_hashed_by_source_builder": False, "jobs_started": False, "shared_state_modified": False})


def main() -> int:
    gate = root575_gate()
    # Keep only the two candidate-bound workers.  The copied fresh098 generic
    # worker is an implementation source, but leaving it beside the bound
    # entrypoints would make the handoff ambiguous and permit an old binding
    # schema to be selected accidentally.
    stale_worker = PKG / "workers/bed_audit_full801.py"
    if stale_worker.exists():
        stale_worker.unlink()
    provenance: dict[str, Any] = {"schema": "ds02.f5.c082s1.fresh115-root575-provenance.v1", "status": "future_root575_full801_pipeline_disabled", "candidate_count": 2, "candidates": {}, "root574_gate": gate, "full801_window": {"frames": 801, "tmax_s": 16.0, "tout_s": 0.02}, "counts": COUNTS, "native_axis": 194427, "fluid_uid_denominator": 31658, "native_bed_mk": 50, "source_mkbound": 40, "exact_dp_lattice_negative": {"max_residual_cells": 5.000000015797923e-06, "threshold_cells": 1e-06, "accepted": False}, "six_new_full24_conditions_gate": "WAIT/null", "science_payloads_read_or_hashed_by_source_builder": False}
    for tag in TAGS:
        bed_worker, xmf_worker = write_workers(tag)
        phys = make_physical_binding(tag); phys_path = PKG / "bindings" / f"{tag}-full801-physical-binding.json"; dump(phys_path, phys); phys_sha = sha_source(phys_path)
        native_paths = gencase_paths(tag); native_bind = make_native_binding(tag, gate, native_paths); native_path = PKG / "bindings" / f"{tag}-full801-native-binding.json"; dump(native_path, native_bind); native_sha = sha_source(native_path)
        xmf_bind = make_xmf_binding(tag, gate, native_bind, PKG / "bindings" / f"{tag}-full801-xmf-binding.json"); xmf_path = PKG / "bindings" / f"{tag}-full801-xmf-binding.json"; dump(xmf_path, xmf_bind); xmf_sha = sha_source(xmf_path)
        bed_bind = make_bed_binding(tag, gate, native_bind, xmf_bind); bed_path = PKG / "bindings" / f"{tag}-full801-bed-audit-binding.json"; dump(bed_path, bed_bind); bed_sha = sha_source(bed_path)
        render_bind = make_render_binding(tag, gate, bed_bind); render_path = PKG / "bindings" / f"{tag}-full801-render-binding.json"; dump(render_path, render_bind); render_sha = sha_source(render_path)
        dump(PKG / "requests" / f"{tag}-full801-native-request.json", make_native_request(tag, gate, phys_path, phys_sha))
        dump(PKG / "requests" / f"{tag}-full801-typed-request.json", make_typed_request(tag, gate, phys_path, phys_sha))
        dump(PKG / "requests" / f"{tag}-full801-xmf-request.json", make_xmf_request(tag, gate, xmf_path, xmf_sha, phys_path, phys_sha))
        dump(PKG / "requests" / f"{tag}-full801-bed-audit-request.json", make_bed_request(tag, gate, bed_path, bed_sha, phys_path, phys_sha, xmf_path, xmf_sha))
        dump(PKG / "requests" / f"{tag}-full801-render-root023-request.json", make_render_request(tag, gate, render_path, render_sha, phys_path, phys_sha, xmf_path, xmf_sha, bed_path, bed_sha))
        provenance["candidates"][tag] = {"native_attempt": root575_attempt(tag, "native"), "typed_attempt": root575_attempt(tag, "typed"), "xmf_attempt": root575_attempt(tag, "xmf"), "bed_attempt": root575_attempt(tag, "bed-audit"), "render_attempt": root575_attempt(tag, "render"), "gencase_attempt": native_paths["gencase_attempt_id"], "physical_condition_sha256": source_phys(tag)["physical_condition_sha256"], "future_receipts_and_hashes": None, "worker_sources": {"bed": str(bed_worker), "xmf": str(xmf_worker)}}
    plan = {"schema": "ds02.f5.c082s1.fresh115-source-plan.v1", "status": "root575_full801_typed_xmf_bed_render_disabled", "candidates": list(TAGS), "full801_window": {"frames": 801, "tmax_s": 16.0, "tout_s": 0.02}, "root575_native_attempt_suffix": "-root575", "root574_gate_status": "WAIT/root574_short_window_visual_review_record", "root574_receipt": None, "root574_report": None, "all_requests_disabled": True, "future_receipts_and_hashes_null": True, "short_window_is_not_full_event_acceptance": True, "full801_bed_audit_scans_all_frames": True, "root023_render_scans_all_actual_valid_native_points": True, "six_new_full24_conditions_gate": "WAIT/null", "exact_dp_lattice_negative_preserved": True, "no_qn_or_case_credit": True, "science_payloads_read_or_hashed_by_source_builder": False}
    dump(PKG / "metadata/fresh115-source-plan.json", plan); dump(PKG / "metadata/fresh115-root575-provenance.json", provenance); dump(PKG / "metadata/root574-gate.json", gate)
    (PKG / "README.md").write_text("# F5 fresh115: Root575 full801 downstream source pack\n\n" "This package prepares disabled Root575 full16 s / 0.02 s / 801-frame native, typed NVMe, legacy-aware N3 XMF, full-frame bed audit, and Root023 renderer requests for A080 and A120. The native attempt IDs are the fresh109 full801 IDs with `-root575`.\n\n" "Root574 short-window review is represented as a future gate with receipt/report/hash null. All requests remain disabled until Root binds that gate and reviews the actual native product. The full bed worker scans all 801 saved states using the complete initial Type-3 UID denominator, exact bed x/y footprint, Mk50/source-mkbound40 mapping, 1DP/2DP diagnostic bins, finite/lost UID reporting, and no acceptance threshold changes.\n\n" "Typed conversion preserves native 194427 particle rows, 31658 fluid rows, 3-D state, native weights, and the canonical physical owner separately from the legacy H5 scope. XMF is a derived view. Root023 rendering preserves all fields/time states and derives camera bounds from actual valid native points. Future receipts, H5/XMF/bed/render hashes and acceptance remain null.\n\n" "The six fresh110 full24 s / 1201 conditions remain `WAIT/null`; current A080/A120 full801 evidence cannot authorize those new conditions. The historical 5e-6 versus 1e-6 DP lattice negative is retained. This source task did not read or hash BI4, CSV, DAT, H5, VTK, or solver arrays and did not start a job.\n", encoding="utf-8")
    write_manifest()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
