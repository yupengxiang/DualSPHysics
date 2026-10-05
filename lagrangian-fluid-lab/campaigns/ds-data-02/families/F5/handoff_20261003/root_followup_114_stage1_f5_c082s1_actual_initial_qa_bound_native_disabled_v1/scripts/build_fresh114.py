#!/usr/bin/env python3
"""Build fresh114 from Root553 JSON metadata only.

The builder reads execution receipts, placement reports, and the registered
producer JSON sidecars.  It never opens or hashes BI4, CSV, DAT, H5, VTK, or
any other science payload.  Producer-attested payload digests are carried as
provenance only.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

PKG = Path(__file__).resolve().parents[1]
HANDOFF = PKG.parent
FRESH110 = HANDOFF / "root_followup_110_stage1_f5_c082s1_six_forcing_conditions_disabled_v1"
FRESH111 = HANDOFF / "root_followup_111_stage1_f5_c082s1_full1201_gate_sidecar_v1"
FRESH113 = HANDOFF / "root_followup_113_stage1_f5_c082s1_actual_gencase_bound_initial_qa_disabled_v1"
DATA_CASE = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1")
CASE = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1"
TAGS = ("M080_T090", "M080_T110", "M100_T090", "M100_T110", "M120_T090", "M120_T110")
SCIENCE_SUFFIXES = {".dat", ".bi4", ".h5", ".hdf5", ".csv", ".vtk", ".vtu", ".npy", ".npz"}
FRESH113_COMMIT = "00b4cc7ffcd6acdaac8623067b4a7f33fac5ccac"
FRESH111_COMMIT = "d5d888cfa35f94ae5ebaf315c10e1eaddd8f16f0"


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha_json(path: Path) -> str:
    if path.suffix.lower() in SCIENCE_SUFFIXES:
        raise ValueError(f"science payload hash forbidden: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def qa_attempt(tag: str) -> Path:
    return DATA_CASE / f"root-stage1-f5-c082s1-{tag.lower()}-actual-initial-qa-113-root553"


def qa_paths(tag: str) -> tuple[Path, Path, Path]:
    attempt = qa_attempt(tag)
    return (
        attempt / "execution-receipt.json",
        attempt / "initial-qa/placement/c082s1-stage1-placement-mk50-audit.json",
        attempt / "initial-qa/registered-export-and-placement-producer.json",
    )


def gate() -> dict[str, Any]:
    path = FRESH111 / "metadata/fresh111-full1201-gate-sidecar.json"
    sidecar = load(path)
    if sidecar.get("status") != "fresh110_full1201_blocked_on_existing_A080_A120_full801_visual_pass":
        raise ValueError("fresh111 gate changed")
    if sidecar.get("short_window_semantics", {}).get("can_authorize_fresh110_full1201") is not False:
        raise ValueError("short-window gate changed")
    if sidecar.get("existing_full801_gate", {}).get("current_status") != "WAIT/null":
        raise ValueError("A080/A120 full801 gate is not WAIT/null")
    return {
        "status": "WAIT/null",
        "sidecar_path": str(path),
        "sidecar_sha256": sha_json(path),
        "sidecar_commit": FRESH111_COMMIT,
        "existing_A080_A120_full801_visual_pass": False,
        "root511_short_render_can_authorize_new_full1201": False,
        "required_before_any_full24s_1201": True,
        "future_authorization_receipt": None,
        "future_authorization_sha256": None,
    }


def qa_record(tag: str) -> dict[str, Any]:
    receipt_path, report_path, producer_path = qa_paths(tag)
    receipt = load(receipt_path)
    report = load(report_path)
    producer = load(producer_path)
    request = receipt.get("request", {})
    counts = report.get("actual_counts")
    normalized_counts = request.get("actual_counts") if isinstance(request, dict) else None
    checks = report.get("checks", {})
    geometry = report.get("fluid_geometry", {})
    coverage = report.get("mk50_coverage", {})
    precision = report.get("numerical_precision", {})
    required_checks = (
        "actual_gencase_completed_3d_and_counts", "all_native_rows_finite",
        "all_particle_positions_unique", "categorical_zone_id_type_mk_integral",
        "central_mk50_surface_support_is_present", "fixed_moving_floating_fluid_spatial_no_overlap",
        "fluid_has_exact_15_transverse_levels", "fluid_initial_above_exact_continuous_bed",
        "fluid_inside_exact_source_box", "native_type0_mk50_exists",
        "native_type_set_and_counts_match_actual_producer", "positive_mass_and_density",
        "uid_unique_consecutive", "zero_initial_velocity", "zone_zero",
    )
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise ValueError(f"{tag}: Root553 receipt is not completed/0")
    if not isinstance(request, dict) or request.get("case_id") != CASE:
        raise ValueError(f"{tag}: receipt identity")
    if report.get("status") != "completed_stage1_placement_mk50_diagnostic":
        raise ValueError(f"{tag}: placement report status")
    if report.get("all_basic_placement_checks_pass") is not True:
        raise ValueError(f"{tag}: basic placement did not pass")
    if report.get("diagnostic_only") is not True or report.get("arrays_opened_by_source_agent") is not False:
        raise ValueError(f"{tag}: report provenance")
    if not isinstance(counts, dict) or not all(isinstance(counts.get(k), int) for k in ("total_particles", "fixed_particles", "moving_particles", "floating_particles", "fluid_particles", "solver_dimension")):
        raise ValueError(f"{tag}: actual counts")
    if counts["total_particles"] != sum(counts[k] for k in ("fixed_particles", "moving_particles", "floating_particles", "fluid_particles")) or counts["solver_dimension"] != 3:
        raise ValueError(f"{tag}: producer count arithmetic")
    if not isinstance(normalized_counts, dict) or normalized_counts.get("data2d") is not False:
        raise ValueError(f"{tag}: normalized Root553 count shape")
    for key in ("total_particles", "fixed_particles", "moving_particles", "floating_particles", "fluid_particles", "solver_dimension"):
        if normalized_counts.get(key) != counts.get(key):
            raise ValueError(f"{tag}: normalized count {key}")
    if any(checks.get(k) is not True for k in required_checks):
        raise ValueError(f"{tag}: required native placement check is false")
    if geometry.get("below_profile_count") != 0 or geometry.get("outside_source_box_count") != 0:
        raise ValueError(f"{tag}: initial fluid geometry is outside the reported gate")
    if coverage.get("native_bed_mk") != 50 or coverage.get("source_mkbound") != 40 or coverage.get("all_six_segments_central_positive") is not True:
        raise ValueError(f"{tag}: Mk50/source marker mapping")
    if len(geometry.get("unique_y_levels", [])) != 15:
        raise ValueError(f"{tag}: transverse y-level count")
    if precision.get("classification") != "numerical_precision" or precision.get("pass_at_original_threshold") is not False or report.get("numerical_precision_result_accepted") is not False:
        raise ValueError(f"{tag}: precision negative was changed")
    # Keep only report metadata needed by downstream binders; do not copy CSV/BI4 fields.
    selected_checks = {key: checks.get(key) for key in required_checks}
    return {
        "tag": tag,
        "status": "completed/0",
        "qa_attempt_id": report.get("qa_attempt_id") or request.get("attempt_id"),
        "gencase_attempt_id": report.get("gencase_attempt_id"),
        "qa_receipt": str(receipt_path),
        "qa_receipt_sha256": sha_json(receipt_path),
        "placement_report": str(report_path),
        "placement_report_sha256": sha_json(report_path),
        "registered_producer": str(producer_path),
        "registered_producer_sha256": sha_json(producer_path),
        "actual_counts": copy.deepcopy(normalized_counts),
        "producer_report_actual_counts": copy.deepcopy(counts),
        "basic_placement_pass": True,
        "stage1_basic_placement_proof": report.get("stage1_basic_placement_proof"),
        "diagnostic_only": True,
        "checks": selected_checks,
        "fluid_geometry": {
            "below_profile_count": geometry.get("below_profile_count"),
            "outside_source_box_count": geometry.get("outside_source_box_count"),
            "unique_y_levels": geometry.get("unique_y_levels"),
        },
        "mk50_coverage": {
            "native_bed_mk": coverage.get("native_bed_mk"),
            "source_mkbound": coverage.get("source_mkbound"),
            "native_type0_mk50_count": coverage.get("native_type0_mk50_count"),
            "central_half_dp_global_count": coverage.get("central_half_dp_global_count"),
            "all_six_segments_central_positive": coverage.get("all_six_segments_central_positive"),
        },
        "precision_negative": {
            "classification": precision.get("classification"),
            "max_residual_cells": precision.get("max_residual_cells"),
            "axis_max_residual_cells": precision.get("axis_max_residual_cells"),
            "threshold": precision.get("threshold"),
            "pass_at_original_threshold": precision.get("pass_at_original_threshold"),
            "accepted_as_stage1_placement_gate": precision.get("accepted_as_stage1_placement_gate"),
            "numerical_precision_result_accepted": report.get("numerical_precision_result_accepted"),
        },
        "derived_bed_depth_diagnostics": {
            "one_dp_count": 0,
            "two_dp_count": 0,
            "one_dp_depth_m": 0.02,
            "two_dp_depth_m": 0.04,
            "derived_inference": True,
            "inference_basis": "Root553 report fluid_geometry.below_profile_count == 0",
            "not_a_new_array_audit": True,
            "frame_scope": "native initial state only",
            "all_fluid_denominator": True,
        },
        "review_boundary": copy.deepcopy(report.get("review_boundary", {})),
        "producer_json_fields": {
            "placement_returncode": producer.get("placement_returncode"),
            "input_BI4_SHA_unchanged": producer.get("input_BI4_SHA_unchanged"),
            "official_export_command_present": isinstance(producer.get("official_export_command"), list),
        },
    }


def base_binding(tag: str) -> dict[str, Any]:
    # The fresh113 binding contains source/condition provenance, not science data.
    return load(FRESH113 / "bindings" / f"{tag}-initial-qa-mk50-binding.json")


def make_binding(tag: str, qa: dict[str, Any], full_gate: dict[str, Any]) -> dict[str, Any]:
    binding = base_binding(tag)
    physical = {key: binding.get(key) for key in (
        "candidate_id", "case_id", "condition_id", "physical_case_id", "physical_condition_sha256",
        "source_plan_physical_condition_sha256", "source_definition", "source_definition_sha256",
        "owner", "owner_sha256", "physical_binding_path", "physical_binding_sha256",
    ) if key in binding}
    counts = qa["actual_counts"]
    out = {
        "schema": "ds02.f5.c082s1.actual-initial-qa-bound-native-disabled.fresh114.v1",
        "source_only": True,
        "tag": tag,
        **physical,
        "dp_m": 0.02,
        "native_bed_marker_mk": 50,
        "source_bed_marker_mkbound": 40,
        "required_native_3d": True,
        "required_transverse_y_levels": 15,
        "actual_counts": counts,
        "producer_report_actual_counts": qa.get("producer_report_actual_counts"),
        "actual_counts_provenance": "Root553 placement report actual_counts; producer-bound, not forecast",
        "initial_qa": qa,
        "initial_qa_status": "completed/0",
        "initial_qa_basic_pass": True,
        "initial_qa_diagnostic_only": True,
        "initial_qa_precision_negative_preserved": True,
        "no_count_rescaling": True,
        "no_threshold_relaxation": True,
        "bed_profile": {
            "native_initial_below_profile_count": qa["fluid_geometry"]["below_profile_count"],
            "one_dp_count": 0,
            "two_dp_count": 0,
            "one_dp_two_dp_are_derived_inferences": True,
            "derived_inference_is_not_new_array_audit": True,
            "one_dp_depth_m": 0.02,
            "two_dp_depth_m": 0.04,
            "all_fluid_denominator": True,
        },
        "upstream_full801_visual_gate": full_gate,
        "future_native_outputs": {
            "short_51_solver_receipt_sha256": None,
            "short_51_typed_h5_sha256": None,
            "short_51_xmf_manifest_sha256": None,
            "short_51_bed_audit_report_sha256": None,
            "full_1201_solver_receipt_sha256": None,
            "full_1201_typed_h5_sha256": None,
            "full_1201_xmf_manifest_sha256": None,
            "full_1201_bed_audit_report_sha256": None,
        },
        "full24_authorized": False,
        "full801_authorized": False,
        "short_solver_authorized": False,
        "q_n_granted": False,
        "independent_case_count_increment": 0,
    }
    return out


def make_request(tag: str, qa: dict[str, Any], binding_path: Path, binding_sha: str, full_gate: dict[str, Any], full: bool) -> dict[str, Any]:
    template_name = f"{tag}-full-native-qualification-request.json" if full else f"{tag}-short-native-qualification-request.json"
    req = load(FRESH110 / "requests" / template_name)
    source = base_binding(tag)
    gencase_receipt = source.get("gencase_receipt")
    gencase_receipt_sha = source.get("gencase_receipt_sha256")
    generated_xml = source.get("generated_xml")
    generated_xml_sha = source.get("generated_xml_sha256")
    generated_bi4 = source.get("generated_bi4")
    generated_bi4_sha = source.get("generated_bi4_sha256")
    prepared_report = source.get("prepared_input_report")
    prepared_report_sha = source.get("prepared_input_report_sha256")
    counts = qa["actual_counts"]
    lower = tag.lower()
    kind = "full24" if full else "short51"
    req.update({
        "schema": "ds02.runner-request.v2",
        "attempt_id": f"root-stage1-f5-c082s1-{lower}-{kind}-native-qualification-114",
        "binding": str(binding_path),
        "binding_sha256": binding_sha,
        "actual_initial_qa_report": qa["placement_report"],
        "depends_on_attempt": qa["qa_attempt_id"],
        "gencase_attempt_id": qa["gencase_attempt_id"],
        "gencase_receipt": gencase_receipt,
        "gencase_receipt_sha256": gencase_receipt_sha,
        "prepared_input_report": prepared_report,
        "prepared_input_report_sha256": prepared_report_sha,
        "generated_xml": generated_xml,
        "generated_xml_sha256": generated_xml_sha,
        "generated_bi4": generated_bi4,
        "generated_bi4_sha256": generated_bi4_sha,
        "gencase_prefix": str(Path(generated_xml).with_suffix("")) if generated_xml else "<root-bind:gencase_prefix>",
        "gencase_prepared_root": str(Path(generated_xml).parent) if generated_xml else "<root-bind:gencase_prepared_root>",
        "actual_counts": counts,
        "actual_counts_provenance": "Root553 placement report actual_counts; producer-bound",
        "expected_counts": counts,
        "expected_particles": counts["total_particles"],
        "expected_fixed_particles": counts["fixed_particles"],
        "expected_moving_particles": counts["moving_particles"],
        "expected_floating_particles": counts["floating_particles"],
        "expected_fluid_particles": counts["fluid_particles"],
        "expected_dimension": counts["solver_dimension"],
        "future_candidate_counts_and_hashes_null": True,
        "disabled": True,
        "execution_allowed": False,
        "launch": False,
        "launch_allowed": False,
        "solver_allowed": False,
        "full_native_authorized": False,
        "full801_authorized": False,
        "q_n_granted": False,
        "independent_case_count_increment": 0,
        "production_approval": "none",
        "status": "disabled_until_root_review_and_actual_initial_qa_binding",
        "root_review_required": True,
        "source_only": True,
        "short_window_is_right_censored": not full,
        "initial_qa_status": "completed/0",
        "initial_qa_basic_pass": True,
        "initial_qa_diagnostic_only": True,
        "initial_qa_precision_negative_preserved": True,
        "initial_qa_bed_zero_depth_inference": "below_profile_count_zero_implies zero 1DP/2DP counts; not a new array audit",
        "upstream_full801_visual_gate": full_gate,
    })
    if full:
        req["upstream_visual_gate"] = "WAIT_existing_A080_A120_full801_root_visual_pass"
        req["fresh110_full_enablement_requires_root_visual_approval"] = True
        req["full_event_window"] = {"tmax_s": 24.0, "tout_s": 0.02, "frames": 1201, "not_a_slice_of_old_output": True}
    else:
        req["event_window_s"] = [0.0, 1.0]
        req["expected_frames"] = 51
    # Replace only metadata placeholders.  Motion and future solver products remain producer-bound placeholders.
    files = []
    for value in req.get("input_files", []):
        if value == "<root-bind:actual_initial_qa_report>":
            files.append(qa["placement_report"])
        elif value == "<root-bind:gencase_receipt>":
            files.append(gencase_receipt)
        elif value == "<root-bind:generated_xml>":
            files.append(generated_xml)
        elif value == "<root-bind:generated_bi4>":
            files.append(generated_bi4)
        elif value == "<root-bind:gencase_prefix>":
            files.append(req["gencase_prefix"])
        elif value == "<root-bind:gencase_prepared_root>":
            files.append(req["gencase_prepared_root"])
        else:
            files.append(value)
    for value in (qa["placement_report"], qa["qa_receipt"], qa["registered_producer"]):
        if value not in files:
            files.append(value)
    req["input_files"] = files
    hashes = {}
    provenance = {}
    old_initial_binding_suffix = "-initial-qa-mk50-binding.json"
    for key, value in req.get("input_sha256", {}).items():
        if key in {str(binding_path), str(qa["placement_report"]), str(qa["qa_receipt"]), str(qa["registered_producer"])}:
            continue
        if key.endswith(old_initial_binding_suffix) and "root_followup_110" in key:
            continue
        if key.startswith("<root-bind:"):
            continue
        if key.endswith("<root-bind:actual_initial_qa_report>") or key == "<root-bind:actual_initial_qa_report>":
            continue
        hashes[key] = value
        provenance[key] = req.get("input_sha256_provenance", {}).get(key, "inherited static source metadata; no science payload read")
    hashes[str(binding_path)] = binding_sha
    provenance[str(binding_path)] = "fresh114 binding JSON metadata hash"
    hashes[qa["placement_report"]] = qa["placement_report_sha256"]
    provenance[qa["placement_report"]] = "Root553 placement report JSON metadata hash"
    hashes[qa["qa_receipt"]] = qa["qa_receipt_sha256"]
    provenance[qa["qa_receipt"]] = "Root553 execution receipt JSON metadata hash"
    hashes[qa["registered_producer"]] = qa["registered_producer_sha256"]
    provenance[qa["registered_producer"]] = "Root553 registered producer JSON metadata hash"
    if prepared_report:
        hashes[prepared_report] = prepared_report_sha
        provenance[prepared_report] = "Root544 prepared-input-report producer-attested JSON hash from fresh113; source agent did not read payload"
    if gencase_receipt:
        hashes[gencase_receipt] = gencase_receipt_sha
        provenance[gencase_receipt] = "Root544 execution-receipt producer-attested metadata hash"
    if generated_xml:
        hashes[generated_xml] = generated_xml_sha
        provenance[generated_xml] = "Root544 producer-attested XML digest; source agent did not read or rehash XML"
    if generated_bi4:
        hashes[generated_bi4] = generated_bi4_sha
        provenance[generated_bi4] = "Root544 producer-attested BI4 digest; source agent did not read or rehash BI4"
    req["input_sha256"] = hashes
    req["input_sha256_provenance"] = provenance
    req["future_output_hashes"] = {key: None for key in req.get("future_output_hashes", {})}
    req["motion_asset_sha256"] = None
    return req


def write_manifest() -> None:
    files: dict[str, str] = {}
    for path in sorted(PKG.rglob("*")):
        if not path.is_file() or path.name in {"manifest.json", "fresh114-validator-report.json"}:
            continue
        if path.suffix.lower() in SCIENCE_SUFFIXES:
            raise ValueError(f"science file in source package: {path}")
        files[str(path.relative_to(PKG))] = sha_json(path)
    dump(PKG / "manifest.json", {
        "schema": "ds02.f5.c082s1.fresh114-source-manifest.v1",
        "status": "six_root553_initial_qa_completed_basic_pass_native_downstream_disabled_full1201_gate_wait",
        "files": files,
        "validator_report_excluded_from_manifest": True,
        "fresh113_modified": False,
        "fresh111_modified": False,
        "science_payloads_read_or_hashed_by_source_builder": False,
        "bi4_csv_dat_h5_vtk_payloads_read_or_hashed_by_source_builder": False,
        "jobs_started": False,
        "shared_state_modified": False,
        "full1201_authorized": False,
    })


def main() -> int:
    full_gate = gate()
    records = [qa_record(tag) for tag in TAGS]
    provenance = {
        "schema": "ds02.f5.c082s1.fresh114-actual-initial-qa-provenance.v1",
        "candidate_count": len(TAGS),
        "candidate_tags": list(TAGS),
        "fresh113_commit": FRESH113_COMMIT,
        "fresh111_gate": full_gate,
        "actual_root553_completed0_count": len(records),
        "actual_basic_placement_pass_count": sum(record["basic_placement_pass"] for record in records),
        "initial_qa_reports_are_diagnostic_only": True,
        "derived_1dp_2dp_zero_is_not_new_array_audit": True,
        "precision_negative_preserved": True,
        "future_short_native_receipts": None,
        "future_full_native_receipts": None,
        "future_typed_xmf_bed_render_hashes": None,
        "science_payloads_read_or_hashed_by_source_builder": False,
        "candidates": records,
    }
    plan = {
        "schema": "ds02.f5.c082s1.fresh114-source-plan.v1",
        "status": "actual_root553_initial_qa_bound_native_future_disabled",
        "candidate_count": len(TAGS),
        "candidate_tags": list(TAGS),
        "full_event_window": {"tmax_s": 24.0, "tout_s": 0.02, "frames": 1201},
        "short_event_window": {"tmax_s": 1.0, "tout_s": 0.02, "frames": 51, "right_censored": True},
        "actual_initial_qa_completed0": True,
        "actual_initial_qa_basic_pass_excluding_precision": True,
        "native_initial_bed_profile_below_count": 0,
        "derived_1dp_2dp_zero_is_inference_only": True,
        "exact_dp_lattice_precision_negative": {"classification": "numerical_precision", "max_residual_cells": 5.000000015797923e-06, "threshold_cells": 1e-06, "accepted": False},
        "native_future_requests_disabled": True,
        "short_solver_authorized": False,
        "full24_authorized": False,
        "full801_authorized": False,
        "root511_short_render_can_authorize_new_full1201": False,
        "existing_A080_A120_full801_visual_gate": "WAIT/null",
        "future_outputs_all_null": True,
        "no_case_credit": True,
        "science_payloads_read_or_hashed_by_source_builder": False,
    }
    dump(PKG / "metadata/fresh114-source-plan.json", plan)
    dump(PKG / "metadata/fresh114-actual-initial-qa-provenance.json", provenance)
    for tag, qa in zip(TAGS, records):
        binding_path = PKG / "bindings" / f"{tag}-actual-initial-qa-bound-binding.json"
        binding = make_binding(tag, qa, full_gate)
        dump(binding_path, binding)
        binding_sha = sha_json(binding_path)
        for full in (False, True):
            name = f"{tag}-{'full24' if full else 'short51'}-native-qualification-request.json"
            dump(PKG / "requests" / name, make_request(tag, qa, binding_path, binding_sha, full_gate, full))
    (PKG / "README.md").write_text(
        "# F5 fresh114: Root553 actual initial placement/Mk50 bindings\n\n"
        "All six Root553 initial QA attempts are completed/0 and pass the basic native placement/Mk50 checks. "
        "Each binding uses the actual Root553 receipt, placement report, and registered producer JSON sidecar; counts are producer-bound.\n\n"
        "The reports record `below_profile_count=0`. The recorded zero 1DP/2DP values are derived implications for that native initial state, marked as inference only; fresh114 does not claim a new 1DP/2DP array audit.\n\n"
        "The exact-DP lattice diagnostic remains a `numerical_precision` negative (maximum residual about 5e-6 cells against the original 1e-6 threshold). No threshold or count is relaxed.\n\n"
        "Short 1s/51 and full 24s/1201 native requests remain disabled. Future solver, typed, XMF, bed-audit, and render hashes are null. Existing A080/A120 full16/801 visual approval remains `WAIT/null`; a short window cannot authorize new full24/1201 cases.\n\n"
        "The builder reads JSON metadata only. It does not open, copy, read, or hash BI4, CSV, DAT, H5, VTK, or solver arrays; producer-attested payload digests are provenance only. Fresh113 and Root553 outputs are immutable inputs.\n",
        encoding="utf-8",
    )
    write_manifest()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
