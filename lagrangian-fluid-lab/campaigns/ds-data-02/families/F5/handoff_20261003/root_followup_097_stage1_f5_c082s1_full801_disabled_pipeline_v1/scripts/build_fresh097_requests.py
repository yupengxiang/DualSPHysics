#!/usr/bin/env python3
"""Build disabled C082S1 full16/801 downstream request templates.

The builder reads only source/JSON/XML metadata and known producer hashes.  It
never opens or hashes .dat, BI4, CSV, H5, VTK, or any future full-event output.
Root has since completed bed321 and native attempt349; the native receipt is
bound as metadata, while typed/XMF/render remain disabled pending downstream
review.  This source builder itself never starts a job.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab")
CAMPAIGNS = INTEGRATION / "campaigns/ds-data-02"
HANDOFF = CAMPAIGNS / "handoff_20261003"
F5_DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5")
CASE = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1"
PHYSICAL = "F5_COMPACT_STILL_WATER_RUNUP_RECOVERY_C082S1"
CANONICAL = "e691d030eda575b9cfabe62f295c9bdc142e5a04cb4357c9fe2790aaec549dbf"
SOURCE_PLAN = "5bad3ec9f9a71aa87da8272003c357f4523d4ffa164d3f06e5d25fee1a4fbfa6"
LEGACY_SCOPE = "3cd1ceab16be11428bbc1011a1b4e297c384d8c7926432c222c254064744ccd0"
MOTION_SHA_FROM_PRIOR_ACTUAL_METADATA = "51e197f0831915a73534c619704658b06812c9d52c38c470ab4cbb8d59f5614a"
RESOURCE_SHA = "2a35e26e36920d8ca40001fd7f28416f27bcf371b8b882eca37868f4a15152b8"
RENDERER_SHA = "5e78f7b92ad7c6f1d15902e3ccacc9099affb04b1b992a42f540eb88241bde66"
FULL_NATIVE_ATTEMPT = "root-stage1-f5-c082s1-solid-fluid-recovery-full801-native-qualification-349"
FULL_TYPED_ATTEMPT = "root-stage1-f5-c082s1-solid-fluid-recovery-full801-native-typed-nvme-350"
FULL_XMF_ATTEMPT = "root-stage1-f5-c082s1-solid-fluid-recovery-full801-native-xmf-351"
FULL_RENDER_ATTEMPT = "root-stage1-f5-c082s1-solid-fluid-recovery-full801-native-render-352"
BED_ATTEMPT = "root-stage1-f5-c082s1-solid-fluid-recovery-short-native-bed-audit-321"
BED_RECEIPT = "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1/root-stage1-f5-c082s1-solid-fluid-recovery-short-native-bed-audit-321/execution-receipt.json"
BED_REPORT = "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1/root-stage1-f5-c082s1-solid-fluid-recovery-short-native-bed-audit-321/audit-output/c082s1-short-event-bed-footprint-audit.json"
BED_BINDING = "/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_096_stage1_f5_c082s1_actual_typed_dynamic_adapter_v1/bindings/short-event-bed-audit-binding.json"
FULL_NATIVE_RECEIPT = "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1/root-stage1-f5-c082s1-solid-fluid-recovery-full801-native-qualification-349/execution-receipt.json"
FULL_NATIVE_REPORT = "<root-bind:full_native_report>"
FULL_TYPED_RECEIPT = "<root-bind:full_typed_receipt>"
FULL_TYPED_REPORT = "<root-bind:full_typed_report>"
FULL_H5 = "<root-bind:full_trajectory_h5>"
FULL_XMF_RECEIPT = "<root-bind:full_xmf_receipt>"
FULL_XMF_MANIFEST = "<root-bind:full_xmf_manifest>"
FULL_XDMF = "<root-bind:full_xdmf>"

DATA_ROOT = F5_DATA / f"{CASE}"
GEN_ROOT = DATA_ROOT / "root-stage1-f5-c082s1-solid-fluid-recovery-genuine-gencase-293"
PREPARED_PREFIX = GEN_ROOT / "prepared" / CASE
GENERATED_XML = GEN_ROOT / "prepared" / f"{CASE}.xml"
GEN_RECEIPT = GEN_ROOT / "execution-receipt.json"
PREPARED_REPORT = GEN_ROOT / "prepared" / "prepared-input-report.json"
PLACEMENT_RECEIPT = DATA_ROOT / "root-stage1-f5-c082s1-solid-fluid-recovery-stage1-placement-mk50-audit-315/execution-receipt.json"
SHORT_RECEIPT = DATA_ROOT / "root-stage1-f5-c082s1-solid-fluid-recovery-short-native-qualification-316/execution-receipt.json"
TYPED_REPORT = DATA_ROOT / "root-stage1-f5-c082s1-solid-fluid-recovery-short-native-typed-nvme-317/conversion-report.json"
TYPED_RECEIPT = DATA_ROOT / "root-stage1-f5-c082s1-solid-fluid-recovery-short-native-typed-nvme-317/execution-receipt.json"
XMF_MANIFEST = DATA_ROOT / "root-stage1-f5-c082s1-solid-fluid-recovery-short-native-xmf-318/xmf/manifest.json"
XMF_RECEIPT = DATA_ROOT / "root-stage1-f5-c082s1-solid-fluid-recovery-short-native-xmf-318/execution-receipt.json"
XDMF = DATA_ROOT / "root-stage1-f5-c082s1-solid-fluid-recovery-short-native-xmf-318/xmf/case.xmf"
ROOT348_APPROVAL = INTEGRATION / "campaigns/ds-data-02/handoff_20261003/root_stage1_f5_actual_short51_bed_visual_full801_launch_approval_348/full801-root-launch-approval.json"
ROOT349_REQUEST = INTEGRATION / "campaigns/ds-data-02/handoff_20261003/root_stage1_f5_actual_bed347_visual346_approved_full801_native_349/full801-native-request.json"
ROOT349_REVIEW = INTEGRATION / "campaigns/ds-data-02/handoff_20261003/root_stage1_f5_actual_bed347_visual346_approved_full801_native_349/full801-native-review.json"
FRESH096 = ROOT.parent / "root_followup_096_stage1_f5_c082s1_actual_typed_dynamic_adapter_v1"
FRESH096_BINDING = FRESH096 / "bindings/short-event-bed-audit-binding.json"
FRESH096_SUMMARY = FRESH096 / "metadata/actual-typed317-xmf318-summary.json"
RECIPE = ROOT.parent / "root_followup_093_stage1_f5_c082s1_short51_pipeline_v1/canonical-physical-recipe.json"
PHYSICAL_BINDING = ROOT.parent / "root_followup_093_stage1_f5_c082s1_short51_pipeline_v1/physical-binding.json"
RESOURCE = HANDOFF / "root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json"
INVENTORY = HANDOFF / "root_stage1_home_floor_inventory_dispatch_142/root_home_floor_inventory_policy.py"
RUNTIME = INTEGRATION / "scripts/ds_data02_runtime_v2.py"
STRICT = INTEGRATION / "scripts/ds_data02_strict_dispatch_v1.py"
PYTHON = INTEGRATION / ".venv/bin/python"
SOLVER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64")
CONVERTER = INTEGRATION / "scripts/ds_data02_nvme_convert_v1.py"
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
PARTVTK = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64")
EXPORT_XMF = INTEGRATION / "campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_079_stage1_f5_b071_post_conversion_pipeline_v1/workers/export_xmf_legacy_aware.py"
RENDER = INTEGRATION / "campaigns/ds-data-02/handoff_20261003/root_stage1_native_renderer_proxy_lifetime_diagnostic_023/render.py"
PV_PYTHON = Path("/home/jade/ParaView-6.1.1-MPI-Linux-Python3.12-x86_64/bin/pvpython")
RENDER_ROOT = DATA_ROOT / "root-stage1-f5-c082s1-actual-xmf339-full51-render-344"
RENDER_RECEIPT = RENDER_ROOT / "execution-receipt.json"
RENDER_REPORT = RENDER_ROOT / "render/paraview-full-animation-report.json"
RENDER_RECEIPT_SHA = "e5c8a658522d61af600203026ece77d5d8e561a4ba0103a1b9d6ea0bf7ab6d20"
RENDER_REPORT_SHA = "b3b56191f615e22aa3ee2461ff1cd1fd2fb228c56162baac856f27ee36649410"
BED_RECEIPT_SHA = "f25d0b7405763b98d4df092e00ed98e8e256a3cf6fd2de5ae7dcdb1b9a1376ee"
BED_REPORT_SHA = "e838dc331b06b6b039a00c9cff4dcca2b98bb4df2ea6b2dbd6a76bc81b643f57"
BED_BINDING_SHA = "3564df477f38532d572e9c3d0866fdfa358bda045727c1a662d3eddbc9b71831"
ROOT348_APPROVAL_SHA = "d1c97f5a3cfe9f94bed79d8c47211d7dbfc1dada77f850154d45d2feabe769e2"
ROOT349_REQUEST_SHA = "289b063f63f3669433e645cf18fafaaad57cf371f4549e6e1070958fb0477e02"
ROOT349_REVIEW_SHA = "fcf8f7aab075bc421e0fdc8652fa766b073ed6670513160f3ecaf3e247c28100"
FULL_NATIVE_RECEIPT_SHA = "2fd76bde16769e2febae752be38b1f83175f8b0fe5d607045cf48ec5039fee1f"
XMF_MANIFEST_SHA = "b8aecefeb0963bcca445e8958d26756307f50e766cb6958fcd710814765f9dbc"
XDMF_SHA = "b7df1464dc0a33e0b02126bbb5ff247058c3f44a0319d13c9fd17857ee423bd2"
H5_SHA = "d8cb7ed80bbc995e9b8b7d6575dd0dee502ae305f57287feec6eaf460dd57856"
GEN_RECEIPT_SHA = "651f3dd714ded9a9d8e4cc158702925f0cb06d0b778dcc66827de4b085e058b7"
GEN_XML_SHA = "19102e12efb4ba6d36f12bc020135fbcd7013949b9089fe1b6197b8e23c51e8e"
PREPARED_REPORT_SHA = "c0572867ac670c4d4676f40463ebc903ace06ddf9bf5a47f533a2cfd5c83585a"
PLACEMENT_RECEIPT_SHA = "ecc8f405f988ddc1fc5e50f853f29316ddea480aa548651be21f5494aa1c9c8a"
SHORT_RECEIPT_SHA = "c20d140e02fb35536045ccab4b423b10eb91f8d11c6df429e205de5679442ea5"
TYPED_REPORT_SHA = "d2fc6991f059eef49e65f0725da8bf4a228e55b6ff895de0bb0d5106fa7592dc"
TYPED_RECEIPT_SHA = "cb1187bcfdefe86b3953d69bcdd920af9234afc39a4fa73be97d74bc0288c0b1"
XMF_RECEIPT_SHA = "1e988f960eb15cc59813a2a0ef048c2c5bd19287be00afa029aa11447c158502"


def sha(path: Path) -> str:
    if path.suffix.lower() in {".dat", ".bi4", ".csv", ".h5", ".hdf5", ".vtk", ".vtu"}:
        raise ValueError(f"fresh097 source builder must not hash science artifact: {path}")
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def existing_inputs(paths: list[Path]) -> list[Path]:
    result = []
    for path in paths:
        path = path.resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        if path not in result:
            result.append(path)
    return result


def hashes(paths: list[Path], known: dict[str, str] | None = None) -> dict[str, str]:
    known = known or {}
    out = {}
    for path in paths:
        key = str(path.resolve())
        if key in known:
            out[key] = known[key]
        else:
            out[key] = sha(path)
    return out


def resource_window() -> dict:
    return {
        "approval_sha256": RESOURCE_SHA,
        "gpu_hours": 512,
        "cpu_core_hours": 3840,
        "qualification_attempts": 1024,
        "production_attempts": 720,
        "home_min_free_bytes": 536870912000,
        "deadline_utc": "2026-10-14T07:23:48+00:00",
        "launch_owner": "root",
        "profile": "root_home_floor_no_legacy_dataset_walk_v1",
    }


def gate() -> dict:
    return {
        "schema": "ds02.f5.c082s1.full801-promotion-gate.fresh097.v1",
        "status": "downstream_disabled_after_actual_bed321_root348_and_native349",
        "case_id": CASE,
        "physical_case_id": PHYSICAL,
        "bed_audit": {
            "attempt_id": BED_ATTEMPT,
            "binding": BED_BINDING,
            "binding_sha256": BED_BINDING_SHA,
            "receipt": BED_RECEIPT,
            "receipt_sha256": BED_RECEIPT_SHA,
            "report": BED_REPORT,
            "report_sha256": BED_REPORT_SHA,
            "required_status": "completed/0",
            "required_all_51_frames": True,
            "required_exact_profile_x_and_y_domain": True,
            "required_uid_finite_and_unexplained_loss_report": True,
            "required_one_dp_two_dp_counts_fractions_depths": True,
            "actual_frames": 51,
            "actual_initial_fluid_uids": 31658,
            "actual_max_missing_or_unexpected_uid": 0,
            "actual_max_nonfinite_fluid_states": 0,
            "actual_max_gt_one_dp_02m_belowbed_count": 0,
            "actual_max_gt_two_dp_04m_belowbed_count": 0,
            "actual_bed_x_domain_m": [-0.2, 4.8],
            "actual_bed_y_domain_m": [-0.22, 0.22],
            "actual_depth_tolerances_m": [0.02, 0.04],
            "actual_stage1_central_mk50_surface_half_dp_counts": [208, 27, 22, 15, 20, 20],
            "thresholds_remain_diagnostic_only": True,
            "does_not_auto_authorize_full801": True,
            "manual_root_review_required": True,
        },
        "root346_visual_evidence": {
            "attempt_id": "root-stage1-f5-c082s1-actual-xmf339-full51-render-344",
            "receipt": str(RENDER_RECEIPT),
            "receipt_sha256": RENDER_RECEIPT_SHA,
            "report": str(RENDER_REPORT),
            "report_sha256": RENDER_REPORT_SHA,
            "status": "completed/0_structural_render_evidence",
            "frames": 51,
            "all_frames_rendered": True,
            "native_identity_axis_preserved": True,
            "nonfinite_active_states": 0,
            "production_product_acceptance": "not_assessed",
            "visual_gate_status": "pending_manual_root_visual_review",
            "does_not_authorize_full801": True,
        },
        "root348_launch_approval": {
            "path": str(ROOT348_APPROVAL),
            "sha256": ROOT348_APPROVAL_SHA,
            "status": "approved_to_run_full16s_native_for_stage1_validation",
            "full801_launch_authorized": True,
            "complete_case_accepted": False,
            "q_n_granted": False,
            "numerical_precision_status": "not_accepted",
            "independent_case_increment": 0,
            "future_downstream_products_still_require_actual_receipts": True,
        },
        "native349_actual": {
            "attempt_id": FULL_NATIVE_ATTEMPT,
            "receipt": FULL_NATIVE_RECEIPT,
            "receipt_sha256": FULL_NATIVE_RECEIPT_SHA,
            "status": "completed/0",
            "returncode": 0,
            "production_product_acceptance": "not_assessed",
            "numerical_reference_status": "not_assessed",
            "downstream_typed_xmf_render_still_disabled": True,
        },
        "historical_negative_preserved": {
            "root314_numerical_precision_classification": "numerical_precision",
            "root314_max_residual_cells": 5.000000015797923e-06,
            "root314_threshold_cells": 1e-06,
            "accepted": False,
            "old_a061_full16_rejection_not_erased": True,
        },
        "canonical_identity": {
            "canonical_owner_sha256": CANONICAL,
            "source_plan_sha256": SOURCE_PLAN,
            "legacy_h5_scope_sha256": LEGACY_SCOPE,
            "cross_resolution_claim": False,
        },
        "counts": {
            "total_particles": 194427,
            "fixed_particles": 158559,
            "moving_particles": 4210,
            "floating_particles": 0,
            "fluid_particles": 31658,
            "dimension": 3,
            "short_frames": 51,
            "full_frames": 801,
        },
        "authorization": {
            "full16_authorized": False,
            "full801_authorized": False,
            "root348_full16_launch_allowed": True,
            "root348_full801_launch_allowed": True,
            "native349_completed_zero": True,
            "downstream_promotion_authorized": False,
            "q_n_granted": False,
            "independent_case_count_increment": 0,
            "future_receipts_and_hashes": None,
        },
    }


def base(kind: str, attempt: str, depends: str, command: list[str], cwd: Path, *, max_wall: int, storage: int, threads: int) -> dict:
    return {
        "schema": "ds02.runner-request.v2",
        "status": "disabled_downstream_after_actual_bed321_root348_and_native349",
        "family_id": "F5",
        "candidate_id": "C082S1_solid_fluid_recovery",
        "condition_id": "F5_RUNUP_DP020_EQUILIBRIUM_ROOT050_C_SOLID_FLUID_RECOVERY_090",
        "repair_id": "F5_BED_RECOVERY_C082S1_SOLID_FLUID_SOURCE_090",
        "case_id": CASE,
        "physical_case_id": PHYSICAL,
        "attempt_id": attempt,
        "depends_on_attempt": depends,
        "kind": kind,
        "launch_owner": "root",
        "cwd": str(cwd),
        "worktree_root": str(INTEGRATION.parent),
        "command": command,
        "input_files": [],
        "input_sha256": {},
        "input_sha256_provenance": "static source/JSON/XML metadata only; no full output or H5/BI4/CSV/.dat artifact was read or hashed by fresh097",
        "array_edit_allowed": False,
        "arrays_allowed": False,
        "source_only": True,
        "execution_allowed": False,
        "launch": False,
        "launch_allowed": False,
        "disabled": True,
        "solver_allowed": False,
        "conversion_allowed": False,
        "production_approval": "none",
        "q_n_granted": False,
        "full16_authorized": False,
        "full801_authorized": False,
        "independent_case_count_increment": 0,
        "cpu_threads": threads,
        "max_wall_seconds": max_wall,
        "estimated_storage_bytes": storage,
        "expected_dimension": 3,
        "expected_frames": 801,
        "expected_particles": 194427,
        "expected_particle_axis": 194427,
        "expected_fixed_particles": 158559,
        "expected_moving_particles": 4210,
        "expected_floating_particles": 0,
        "expected_fluid_particles": 31658,
        "dp_m": 0.02,
        "save_interval_s": 0.02,
        "time_window_s": [0.0, 16.0],
        "motion_window_s": [0.0, 16.0],
        "native_bed_marker_mk": 50,
        "source_bed_marker_mkbound": 40,
        "physical_condition_sha256": CANONICAL,
        "source_plan_physical_condition_sha256": SOURCE_PLAN,
        "source_h5_legacy_scope_sha256": LEGACY_SCOPE,
        "physical_condition_hash_semantics": {
            "canonical_owner_sha256": CANONICAL,
            "source_plan_sha256": SOURCE_PLAN,
            "source_h5_scope_sha256": LEGACY_SCOPE,
            "source_h5_scope_schema": "legacy-owner-scope.v0",
            "cross_resolution_claim": False,
        },
        "full_event_gate": {
            "bed_audit_attempt": BED_ATTEMPT,
            "bed_audit_receipt": BED_RECEIPT,
            "bed_audit_receipt_sha256": BED_RECEIPT_SHA,
            "bed_audit_report": BED_REPORT,
            "bed_audit_report_sha256": BED_REPORT_SHA,
            "bed_audit_binding": BED_BINDING,
            "bed_audit_binding_sha256": BED_BINDING_SHA,
            "root348_launch_approval": str(ROOT348_APPROVAL),
            "root348_launch_approval_sha256": ROOT348_APPROVAL_SHA,
            "native349_receipt": FULL_NATIVE_RECEIPT,
            "native349_receipt_sha256": FULL_NATIVE_RECEIPT_SHA,
            "root346_visual_receipt": str(RENDER_RECEIPT),
            "root346_visual_report": str(RENDER_REPORT),
            "actual_bed_audit_completed_zero": True,
            "manual_root_visual_review_required": True,
            "audit_does_not_auto_authorize": True,
            "prior_full16_rejection_preserved": True,
        },
        "resource_window": resource_window(),
        "root_review_required": True,
        "shared_registry_write_allowed": False,
        "future_output_hashes": None,
        "source_arrays_read_or_hashed_by_source_agent": False,
    }


def static_inputs(*, include_solver=False, include_converter=False, include_xmf=False, include_render=False, include_full_refs=False) -> list[Path]:
    paths = [PYTHON, RUNTIME, STRICT, INVENTORY, RESOURCE, ROOT / "README.md", ROOT / "metadata/full801-gate.json", ROOT / "scripts/preflight_fresh097.py", FRESH096_BINDING, FRESH096_SUMMARY, RECIPE, PHYSICAL_BINDING, GEN_RECEIPT, PREPARED_REPORT, GENERATED_XML, PLACEMENT_RECEIPT, SHORT_RECEIPT, TYPED_RECEIPT, TYPED_REPORT, XMF_RECEIPT, XMF_MANIFEST, XDMF, Path(BED_RECEIPT), Path(BED_REPORT), Path(BED_BINDING), ROOT348_APPROVAL, ROOT349_REQUEST, ROOT349_REVIEW, Path(FULL_NATIVE_RECEIPT)]
    if include_solver:
        paths += [SOLVER]
    if include_converter:
        paths += [CONVERTER, DECODER, PARTVTK]
    if include_xmf:
        paths += [EXPORT_XMF]
    if include_render:
        paths += [PV_PYTHON, RENDER]
    if include_full_refs:
        paths += [RENDER_RECEIPT, RENDER_REPORT]
    return existing_inputs(paths)


def write_request(name: str, request: dict, paths: list[Path], *, known: dict[str, str] | None = None) -> None:
    request["input_files"] = [str(path.resolve()) for path in paths]
    request["input_sha256"] = hashes(paths, known)
    (ROOT / "requests" / name).write_text(json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    (ROOT / "metadata/full801-gate.json").write_text(json.dumps(gate(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    prepared_dir = GEN_ROOT / "prepared"
    native = base("qualification", FULL_NATIVE_ATTEMPT, BED_ATTEMPT, [str(SOLVER), str(PREPARED_PREFIX), "{attempt_root}/solver_output", "-tmax:16.0", "-tout:0.02"], prepared_dir, max_wall=7200, storage=51539607552, threads=2)
    native.update({
        "gpu": True,
        "cpu_task_kind": "solver",
        "estimated_peak_gpu_mib": 4096,
        "genuine_gencase_required": True,
        "gencase_attempt_id": "root-stage1-f5-c082s1-solid-fluid-recovery-genuine-gencase-293",
        "gencase_receipt": str(GEN_RECEIPT),
        "gencase_receipt_sha256": GEN_RECEIPT_SHA,
        "prepared_prefix": str(PREPARED_PREFIX),
        "generated_xml": str(GENERATED_XML),
        "generated_xml_sha256": GEN_XML_SHA,
        "prepared_input_report": str(PREPARED_REPORT),
        "prepared_input_report_sha256": PREPARED_REPORT_SHA,
        "motion_asset_relative_name": "assets/f5_compact_packet_motion.dat",
        "motion_asset_sha256_from_prior_actual_metadata": MOTION_SHA_FROM_PRIOR_ACTUAL_METADATA,
        "motion_asset_hash_provenance": "known actual source metadata; fresh097 did not read or rehash .dat",
        "full16_gate": gate()["bed_audit"],
        "full801_gate": gate()["authorization"],
        "root348_launch_approval": str(ROOT348_APPROVAL),
        "root348_launch_approval_sha256": ROOT348_APPROVAL_SHA,
        "actual_native_result": {
            "attempt_id": FULL_NATIVE_ATTEMPT,
            "receipt": FULL_NATIVE_RECEIPT,
            "receipt_sha256": FULL_NATIVE_RECEIPT_SHA,
            "status": "completed/0",
            "returncode": 0,
            "production_product_acceptance": "not_assessed",
            "numerical_reference_status": "not_assessed",
            "source_agent_did_not_run_solver": True,
        },
        "numerical_reference_status": "native349_completed_zero; product acceptance and precision remain unassessed",
        "native_output_contract": {
            "all_801_saved_states_required": True,
            "time_max_s": 16.0,
            "save_interval_s": 0.02,
            "expected_frames": 801,
            "native_identity_axis_preserved": True,
            "native_mk50_mapping_preserved": True,
            "no_mass_rescale": True,
            "actual_receipt_bound": True,
            "future_receipt_and_hashes": None,
        },
    })
    native_paths = static_inputs(include_solver=True, include_full_refs=True)
    known_native = {str(Path(binding).resolve()): value for binding, value in {str(GEN_RECEIPT): GEN_RECEIPT_SHA, str(GENERATED_XML): GEN_XML_SHA, str(PREPARED_REPORT): PREPARED_REPORT_SHA, str(PLACEMENT_RECEIPT): PLACEMENT_RECEIPT_SHA, str(SHORT_RECEIPT): SHORT_RECEIPT_SHA, str(TYPED_RECEIPT): TYPED_RECEIPT_SHA, str(TYPED_REPORT): TYPED_REPORT_SHA, str(XMF_RECEIPT): XMF_RECEIPT_SHA, str(XMF_MANIFEST): XMF_MANIFEST_SHA, str(XDMF): XDMF_SHA, str(RENDER_RECEIPT): RENDER_RECEIPT_SHA, str(RENDER_REPORT): RENDER_REPORT_SHA, str(FRESH096_BINDING): BED_BINDING_SHA, str(Path(BED_RECEIPT)): BED_RECEIPT_SHA, str(Path(BED_REPORT)): BED_REPORT_SHA, str(ROOT348_APPROVAL): ROOT348_APPROVAL_SHA, str(ROOT349_REQUEST): ROOT349_REQUEST_SHA, str(ROOT349_REVIEW): ROOT349_REVIEW_SHA, str(Path(FULL_NATIVE_RECEIPT)): FULL_NATIVE_RECEIPT_SHA}.items()}
    write_request("full-native-801-request.json", native, native_paths, known=known_native)

    typed = base("cpu", FULL_TYPED_ATTEMPT, FULL_NATIVE_ATTEMPT, [str(PYTHON), str(CONVERTER), "--staging-root", "/tmp/ds02-nvme-conversion", "--staging-limit-bytes", "25769803776", "--", "--data-root", "<root-bind:full_solver_data_root>", "--generated-xml", str(GENERATED_XML), "--output", FULL_H5, "--report", FULL_TYPED_REPORT, "--decoder", str(DECODER), "--partvtk", str(PARTVTK), "--validation-dir", "{attempt_root}/partvtk-validation", "--solver-log", "<root-bind:full_solver_log>", "--solver-receipt", FULL_NATIVE_RECEIPT, "--gencase-receipt", str(GEN_RECEIPT), "--owner-metadata", "<root-bind:conversion_owner_metadata>", "--particle-chunk", "65536"], INTEGRATION, max_wall=5400, storage=137438953472, threads=2)
    typed.update({
        "cpu_task_kind": "conversion",
        "conversion_allowed": False,
        "conversion_contract": {
            "all_801_saved_states_required": True,
            "all_actual_counts_from_gencase_and_report": True,
            "canonical_condition_separate_from_legacy_h5_scope": True,
            "mass_report_without_rescale": True,
            "native_mk50_bed_mapping_preserved": True,
            "solver_dimension_required": 3,
            "source_h5_read_only": True,
            "source_native_identity_preserved": True,
            "future_hashes": None,
        },
        "actual_native_dependency": {"attempt_id": FULL_NATIVE_ATTEMPT, "receipt": FULL_NATIVE_RECEIPT, "receipt_sha256": FULL_NATIVE_RECEIPT_SHA, "status": "completed/0"},
        "future_bindings": {"native_receipt": FULL_NATIVE_RECEIPT, "conversion_report": FULL_TYPED_REPORT, "trajectory_h5": FULL_H5, "typed_receipt": FULL_TYPED_RECEIPT, "all_future_hashes": None},
        "owner_metadata": "<root-bind:conversion_owner_metadata>",
        "native_conversion_identity": {"total_particles":194427,"fixed_particles":158559,"moving_particles":4210,"floating_particles":0,"fluid_particles":31658,"native_bed_mk":50,"source_mkbound":40},
    })
    write_request("full-typed-801-request.json", typed, static_inputs(include_converter=True, include_full_refs=True), known=known_native)

    xmf = base("cpu", FULL_XMF_ATTEMPT, FULL_TYPED_ATTEMPT, [str(PYTHON), str(EXPORT_XMF), "--binding", "<root-bind:full_xmf_binding>", "--output-dir", "{attempt_root}/xmf"], INTEGRATION, max_wall=1800, storage=8589934592, threads=2)
    xmf.update({
        "cpu_task_kind": "audit",
        "derived_view_only": True,
        "conversion_allowed": False,
        "xmf_product_kind": "N3_native_temporal_full_saved_states",
        "xmf_contract": {
            "all_801_saved_states": True,
            "canonical_owner_separate_from_legacy_h5_scope": True,
            "derived_view_only": True,
            "native_fields_preserved": True,
            "native_time_axis_preserved": True,
            "no_cross_resolution_claim": True,
            "source_h5_read_only": True,
            "future_manifest_and_xdmf_hashes": None,
        },
        "actual_native_dependency": {"attempt_id": FULL_NATIVE_ATTEMPT, "receipt": FULL_NATIVE_RECEIPT, "receipt_sha256": FULL_NATIVE_RECEIPT_SHA, "status": "completed/0"},
        "future_bindings": {"case_xmf": FULL_XDMF, "xmf_manifest": FULL_XMF_MANIFEST, "native_receipt": FULL_NATIVE_RECEIPT, "typed_receipt": FULL_TYPED_RECEIPT, "conversion_report": FULL_TYPED_REPORT, "all_future_hashes": None},
        "canonical_condition_sha256": CANONICAL,
        "source_plan_condition_sha256": SOURCE_PLAN,
        "source_h5_legacy_scope_sha256": LEGACY_SCOPE,
        "physical_condition_hash_semantics": {"canonical_owner_sha256":CANONICAL,"source_plan_sha256":SOURCE_PLAN,"source_h5_scope_sha256":LEGACY_SCOPE,"cross_resolution_claim":False},
    })
    write_request("full-xmf-801-request.json", xmf, static_inputs(include_xmf=True, include_full_refs=True), known=known_native)

    render = base("cpu", FULL_RENDER_ATTEMPT, FULL_XMF_ATTEMPT, [str(PV_PYTHON), "--force-offscreen-rendering", str(RENDER), "--manifest", FULL_XMF_MANIFEST, "--output-dir", "{attempt_root}/render"], INTEGRATION, max_wall=5400, storage=34359738368, threads=2)
    render.update({
        "cpu_task_kind": "audit",
        "derived_view_only": True,
        "conversion_allowed": False,
        "render_kind": "native_root023_full_saved_animation",
        "renderer_sha256": RENDERER_SHA,
        "camera_bounds": None,
        "domain_bounds": None,
        "camera_bounds_policy": "auto_scan_all_actual_valid_native_points",
        "environment": {"LIBGL_ALWAYS_SOFTWARE":"1","LP_NUM_THREADS":"2","MESA_LOADER_DRIVER_OVERRIDE":"llvmpipe","OMP_NUM_THREADS":"2","QT_QPA_PLATFORM":"offscreen","VTK_DEFAULT_OPENGL_WINDOW":"vtkEGLRenderWindow","VTK_SMP_MAX_THREADS":"2","__EGL_VENDOR_LIBRARY_FILENAMES":"/usr/share/glvnd/egl_vendor.d/50_mesa.json"},
        "render_contract": {
            "all_801_frames": True,
            "camera_derived_from_all_actual_valid_native_points": True,
            "native_fields_preserved": True,
            "native_time_axis_preserved": True,
            "no_particle_clipping_or_reader_filtering": True,
            "precision_not_certified": True,
            "visual_review_required": True,
            "future_render_report_and_frame_hashes": None,
        },
        "future_bindings": {"xmf_manifest": FULL_XMF_MANIFEST, "render_report": "<root-bind:full_render_report>", "all_future_hashes": None},
    })
    write_request("full-render-root023-801-request.json", render, static_inputs(include_render=True, include_full_refs=True), known=known_native)

    provenance = {
        "schema": "ds02.f5.c082s1.full801-source-input-provenance.fresh097.v1",
        "status": "source_ready_disabled",
        "attempts": {"native":FULL_NATIVE_ATTEMPT,"typed":FULL_TYPED_ATTEMPT,"xmf":FULL_XMF_ATTEMPT,"render":FULL_RENDER_ATTEMPT},
        "actual_gate": gate(),
        "counts": {"total":194427,"fixed":158559,"moving":4210,"floating":0,"fluid":31658,"dimension":3},
        "motion_asset": {"relative_name":"assets/f5_compact_packet_motion.dat","sha256_from_prior_actual_metadata":MOTION_SHA_FROM_PRIOR_ACTUAL_METADATA,"read_or_rehashed_by_fresh097":False},
        "future_products": None,
        "no_science_arrays_read_or_hashed": True,
    }
    (ROOT / "metadata/full801-source-input-provenance.json").write_text(json.dumps(provenance,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print(json.dumps({"status":"fresh097_disabled_requests_written","requests":[str(p) for p in sorted((ROOT/'requests').glob('*.json'))],"bed_attempt":BED_ATTEMPT,"full801_authorized":False},sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
