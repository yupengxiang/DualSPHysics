#!/usr/bin/env python3
"""Bind the actual C082S1 GenCase/placement/short/typed/XMF products.

This binder is metadata-only.  It reads JSON/XML metadata and producer-declared
hashes, but it never opens, decodes, or hashes BI4/CSV/H5 science arrays.  The
result is a Root-review binding for the unchanged 51-frame bed audit worker;
it does not enable or run that worker.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

CASE_ID = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1"
PHYSICAL_CASE_ID = "F5_COMPACT_STILL_WATER_RUNUP_RECOVERY_C082S1"
CANONICAL_SHA = "e691d030eda575b9cfabe62f295c9bdc142e5a04cb4357c9fe2790aaec549dbf"
SOURCE_PLAN_SHA = "5bad3ec9f9a71aa87da8272003c357f4523d4ffa164d3f06e5d25fee1a4fbfa6"
LEGACY_H5_SCOPE_SHA = "3cd1ceab16be11428bbc1011a1b4e297c384d8c7926432c222c254064744ccd0"
LEGACY_SCOPE_SCHEMA = "legacy-owner-scope.v0"
LEGACY_SCOPE_STATUS = "legacy_incomplete; no cross-resolution physical claim"
EXPECTED = {
    "total_particles": 194427,
    "fixed_particles": 158559,
    "moving_particles": 4210,
    "floating_particles": 0,
    "fluid_particles": 31658,
    "dimension": 3,
    "frames": 51,
}
SCIENCE_SUFFIXES = {".bi4", ".csv", ".h5", ".hdf5", ".vtk", ".vtu", ".npz", ".npy"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def load_json(path: Path) -> dict[str, Any]:
    require(path.suffix.lower() == ".json", f"metadata binder accepts JSON only: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"JSON object required: {path}")
    return value


def sha256_file(path: Path) -> str:
    require(path.suffix.lower() not in SCIENCE_SUFFIXES,
            f"science array/artifact hashing is forbidden: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def completed(receipt: Mapping[str, Any], label: str) -> None:
    require(receipt.get("status") == "completed", f"{label} is not completed")
    code = receipt.get("returncode", receipt.get("return_code", receipt.get("exit_code")))
    require(code is not None and int(code) == 0, f"{label} return code is not zero: {code!r}")


def identity(receipt: Mapping[str, Any]) -> tuple[str | None, str | None, str | None]:
    request = receipt.get("request") if isinstance(receipt.get("request"), dict) else {}
    attempt = request.get("attempt_id") or receipt.get("attempt_id")
    case = request.get("case_id") or receipt.get("case_id")
    output_root = receipt.get("output_root") or request.get("output_root")
    return (
        str(attempt) if attempt is not None else None,
        str(case) if case is not None else None,
        str(output_root) if output_root is not None else None,
    )


def exact_counts(actual: Mapping[str, Any], *, label: str) -> dict[str, Any]:
    """Keep producer placement counts verbatim, including nested XML counts."""
    expected = {
        "fixed_particles": EXPECTED["fixed_particles"],
        "floating_particles": EXPECTED["floating_particles"],
        "fluid_particles": EXPECTED["fluid_particles"],
        "moving_particles": EXPECTED["moving_particles"],
        "solver_dimension": EXPECTED["dimension"],
        "total_particles": EXPECTED["total_particles"],
        "xml_particle_counts": {
            "fixed": EXPECTED["fixed_particles"],
            "floating": EXPECTED["floating_particles"],
            "fluid": EXPECTED["fluid_particles"],
            "moving": EXPECTED["moving_particles"],
        },
    }
    require(dict(actual) == expected, f"{label} actual_counts differ from producer-bound counts: {actual!r}")
    return dict(actual)


def dimension_evidence(report: Mapping[str, Any]) -> dict[str, Any]:
    raw = report.get("solver_dimension")
    require(isinstance(raw, dict), "typed report solver_dimension must retain its producer evidence object")
    require(int(raw.get("solver_dimension", -1)) == 3, "typed report is not 3-D")
    run_out = raw.get("run_out_dimensions")
    require(isinstance(run_out, list) and 3 in {int(value) for value in run_out},
            "typed report Run.out dimension evidence does not contain 3")
    require(str(raw.get("xml_data2d", "")).strip().lower() in {"false", "0"},
            "typed report is marked 2-D")
    return {
        "producer_field_shape": "evidence_object",
        "solver_dimension": 3,
        "run_out_dimensions": [int(value) for value in run_out],
        "xml_data2d": raw.get("xml_data2d"),
        "source_paths": raw.get("source_paths"),
    }


def role_counts(report: Mapping[str, Any]) -> dict[str, int]:
    identity_data = report.get("typed_identity")
    require(isinstance(identity_data, dict), "typed report lacks typed_identity")
    blocks = identity_data.get("blocks")
    require(isinstance(blocks, list), "typed report lacks typed_identity.blocks")
    result: dict[str, int] = {}
    for block in blocks:
        require(isinstance(block, dict), "typed identity block is not an object")
        tag = str(block.get("tag", ""))
        result[tag] = result.get(tag, 0) + int(block.get("count", 0))
    require(result.get("fixed") == EXPECTED["fixed_particles"], "typed fixed count mismatch")
    require(result.get("moving") == EXPECTED["moving_particles"], "typed moving count mismatch")
    require(result.get("fluid") == EXPECTED["fluid_particles"], "typed fluid count mismatch")
    observed_types = {int(value) for value in identity_data.get("observed_types", [])}
    observed_mks = {int(value) for value in identity_data.get("observed_mks", [])}
    require({0, 1, 3}.issubset(observed_types), "typed native type identity incomplete")
    require(50 in observed_mks, "typed native Mk50 identity missing")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", type=Path, required=True)
    parser.add_argument("--gencase-receipt", type=Path, required=True)
    parser.add_argument("--prepared-report", type=Path, required=True)
    parser.add_argument("--generated-xml", type=Path, required=True)
    parser.add_argument("--placement-receipt", type=Path, required=True)
    parser.add_argument("--placement-report", type=Path, required=True)
    parser.add_argument("--short-receipt", type=Path, required=True)
    parser.add_argument("--short-metadata", type=Path, required=True)
    parser.add_argument("--typed-receipt", type=Path, required=True)
    parser.add_argument("--typed-report", type=Path, required=True)
    parser.add_argument("--xmf-receipt", type=Path, required=True)
    parser.add_argument("--xmf-manifest", type=Path, required=True)
    parser.add_argument("--output-binding", type=Path, required=True)
    parser.add_argument("--output-summary", type=Path, required=True)
    args = parser.parse_args(argv)

    paths = {
        "owner": args.owner.resolve(),
        "gencase_receipt": args.gencase_receipt.resolve(),
        "prepared_report": args.prepared_report.resolve(),
        "generated_xml": args.generated_xml.resolve(),
        "placement_receipt": args.placement_receipt.resolve(),
        "placement_report": args.placement_report.resolve(),
        "short_receipt": args.short_receipt.resolve(),
        "short_metadata": args.short_metadata.resolve(),
        "typed_receipt": args.typed_receipt.resolve(),
        "typed_report": args.typed_report.resolve(),
        "xmf_receipt": args.xmf_receipt.resolve(),
        "xmf_manifest": args.xmf_manifest.resolve(),
    }
    for label, path in paths.items():
        require(path.is_file(), f"{label} does not exist: {path}")

    owner = load_json(paths["owner"])
    gencase = load_json(paths["gencase_receipt"])
    prepared = load_json(paths["prepared_report"])
    placement_receipt = load_json(paths["placement_receipt"])
    placement = load_json(paths["placement_report"])
    short_receipt = load_json(paths["short_receipt"])
    short_metadata = load_json(paths["short_metadata"])
    typed_receipt = load_json(paths["typed_receipt"])
    typed = load_json(paths["typed_report"])
    xmf_receipt = load_json(paths["xmf_receipt"])
    xmf = load_json(paths["xmf_manifest"])

    owner_sha = sha256_file(paths["owner"])
    json_shas = {label: sha256_file(path) for label, path in paths.items()
                 if label != "generated_xml"}
    generated_xml_sha = sha256_file(paths["generated_xml"])

    require(owner.get("case_id") == CASE_ID and owner.get("physical_case_id") == PHYSICAL_CASE_ID,
            "owner physical/case identity mismatch")
    require(owner.get("physical_condition_sha256") == CANONICAL_SHA,
            "owner canonical physical identity mismatch")
    require(owner.get("source_plan_physical_condition_sha256") == SOURCE_PLAN_SHA,
            "owner source-plan identity mismatch")
    require(owner.get("legacy_scope_sha256") == LEGACY_H5_SCOPE_SHA,
            "owner legacy H5 scope mismatch")
    owner_scope = owner.get("owner_scope_semantics", {})
    require(owner_scope.get("selected_scope_schema") == LEGACY_SCOPE_SCHEMA and
            owner_scope.get("semantic_status") == LEGACY_SCOPE_STATUS,
            "owner legacy scope semantics changed")

    completed(gencase, "GenCase receipt")
    gen_attempt, gen_case, gen_root_raw = identity(gencase)
    require(gen_case == CASE_ID, "GenCase receipt case identity mismatch")
    require(gen_attempt == "root-stage1-f5-c082s1-solid-fluid-recovery-genuine-gencase-293",
            "unexpected actual GenCase attempt")
    gen_root = Path(str(gen_root_raw)).resolve()
    require(gen_root.is_dir(), "GenCase receipt output root missing")
    require(int(gencase.get("total_particles", -1)) == EXPECTED["total_particles"],
            "GenCase receipt total particle count mismatch")
    require(int(gencase.get("fluid_particles", -1)) == EXPECTED["fluid_particles"],
            "GenCase receipt fluid particle count mismatch")
    require(int(gencase.get("solver_dimension_from_gencase", -1)) == EXPECTED["dimension"],
            "GenCase receipt dimension mismatch")
    require(prepared.get("case_id") == CASE_ID, "prepared report case identity mismatch")
    require(int(prepared.get("actual_total_particles", -1)) == EXPECTED["total_particles"],
            "prepared report total particle count mismatch")
    generated = prepared.get("generated_xml_particle_counts")
    require(isinstance(generated, dict), "prepared report lacks generated_xml_particle_counts")
    require(generated == {"fixed": EXPECTED["fixed_particles"], "moving": EXPECTED["moving_particles"],
                          "floating": EXPECTED["floating_particles"], "fluid": EXPECTED["fluid_particles"]},
            "prepared report generated XML counts mismatch")
    require(prepared.get("xml_sha256") == generated_xml_sha,
            "prepared report XML SHA differs from actual generated XML")
    require(paths["generated_xml"].parent == gen_root / "prepared",
            "generated XML is not in the actual GenCase prepared directory")

    completed(placement_receipt, "placement receipt")
    placement_attempt, placement_case, placement_root_raw = identity(placement_receipt)
    require(placement_case == CASE_ID, "placement receipt case identity mismatch")
    placement_root = Path(str(placement_root_raw)).resolve()
    require(placement.get("status") == "completed_stage1_placement_mk50_diagnostic",
            "placement report status changed")
    require(placement.get("all_basic_placement_checks_pass") is True,
            "stage-one basic placement proof did not pass")
    require(placement.get("stage1_basic_placement_proof") == "pass_excluding_numerical_precision",
            "stage-one proof boundary changed")
    require(placement.get("numerical_precision_result_accepted") is False,
            "historical numerical precision failure was relabelled")
    placement_counts = exact_counts(placement.get("actual_counts", {}), label="placement")
    coverage = placement.get("mk50_coverage")
    require(isinstance(coverage, dict), "placement report lacks mk50_coverage")
    require(coverage.get("native_bed_mk") == 50 and coverage.get("source_mkbound") == 40,
            "placement marker mapping changed")
    bins = coverage.get("six_segment_bins")
    require(isinstance(bins, list) and len(bins) == 6, "placement six-segment coverage missing")
    central_counts = [int(row.get("central_abs_y_le_0p01_surface_half_dp_count", 0)) for row in bins]
    require(all(value > 0 for value in central_counts), "placement central Mk50 support is incomplete")
    require(Path(str(placement_receipt.get("output_root"))).resolve() == placement_root,
            "placement receipt output root is inconsistent")

    completed(short_receipt, "short native receipt")
    short_attempt, short_case, short_root_raw = identity(short_receipt)
    require(short_case == CASE_ID and
            short_attempt == "root-stage1-f5-c082s1-solid-fluid-recovery-short-native-qualification-316",
            "short native receipt identity mismatch")
    short_root = Path(str(short_root_raw)).resolve()
    require(short_metadata.get("status") == "completed" and short_metadata.get("all_51_saved_states") is True,
            "short metadata is not completed with all 51 states")
    require(short_metadata.get("attempt_id") == short_attempt and short_metadata.get("case_id") == CASE_ID,
            "short metadata identity mismatch")
    require(int(short_metadata.get("saved_state_count", -1)) == EXPECTED["frames"],
            "short metadata frame count mismatch")
    filenames = short_metadata.get("saved_state_filenames")
    require(filenames == [f"Part_{index:04d}.bi4" for index in range(EXPECTED["frames"])],
            "short metadata filenames are not exactly Part_0000..Part_0050")
    command = short_receipt.get("command", [])
    require(any(str(item).startswith("-tmax:1") for item in command) and
            any(str(item).startswith("-tout:0.02") for item in command),
            "short native command window/cadence mismatch")
    require(Path(str(short_receipt.get("output_root"))).resolve() == short_root,
            "short receipt output root is inconsistent")

    completed(typed_receipt, "typed317 receipt")
    typed_attempt, typed_case, typed_root_raw = identity(typed_receipt)
    require(typed_case == CASE_ID and
            typed_attempt == "root-stage1-f5-c082s1-solid-fluid-recovery-short-native-typed-nvme-317",
            "typed317 receipt identity mismatch")
    typed_root = Path(str(typed_root_raw)).resolve()
    require(typed.get("conversion_status") == "completed", "typed317 conversion report is not completed")
    require(int(typed.get("frames", -1)) == EXPECTED["frames"] and
            int(typed.get("particles", -1)) == EXPECTED["total_particles"],
            "typed317 dimensions mismatch")
    require(typed.get("coordinate_frame") == "DualSPHysics case Cartesian coordinates (x,y,z)",
            "typed317 coordinate frame mismatch")
    dimension = dimension_evidence(typed)
    typed_roles = role_counts(typed)
    typed_identity = typed["typed_identity"]
    observed_mks = sorted(int(value) for value in typed_identity.get("observed_mks", []))
    observed_types = sorted(int(value) for value in typed_identity.get("observed_types", []))
    hash_scopes = typed.get("hash_scopes")
    require(isinstance(hash_scopes, dict), "typed317 lacks hash scopes")
    physical_scope = hash_scopes.get("physical_condition")
    require(isinstance(physical_scope, dict), "typed317 lacks physical scope object")
    require(physical_scope.get("schema") == LEGACY_SCOPE_SCHEMA and
            physical_scope.get("semantic_binding_status") == LEGACY_SCOPE_STATUS,
            "typed317 legacy scope semantics changed")
    legacy_sha = hash_scopes.get("physical_condition_sha256")
    require(legacy_sha == LEGACY_H5_SCOPE_SHA and legacy_sha not in {CANONICAL_SHA, SOURCE_PLAN_SHA},
            "typed317 legacy physical scope is not distinct")
    provenance = typed.get("source_provenance")
    require(isinstance(provenance, dict), "typed317 source provenance missing")
    owner_provenance = provenance.get("owner_metadata")
    require(isinstance(owner_provenance, dict) and owner_provenance.get("sha256") == owner_sha,
            "typed317 owner provenance mismatch")
    gen_provenance = provenance.get("gencase_receipt")
    require(isinstance(gen_provenance, dict) and gen_provenance.get("sha256") == json_shas["gencase_receipt"],
            "typed317 GenCase provenance mismatch")
    xml_provenance = provenance.get("generated_xml")
    require(isinstance(xml_provenance, dict) and xml_provenance.get("sha256") == generated_xml_sha,
            "typed317 generated XML provenance mismatch")
    solver_provenance = provenance.get("solver_receipt")
    require(isinstance(solver_provenance, dict) and solver_provenance.get("sha256") == json_shas["short_receipt"],
            "typed317 solver provenance mismatch")
    trajectory_h5 = Path(str(typed.get("output_hdf5", ""))).resolve()
    trajectory_h5_sha = str(typed.get("output_sha256", typed.get("source_h5_sha256", "")))
    # The direct converter names the actual trajectory digest output_sha256;
    # source_h5_sha256 belongs to the XMF manifest, not conversion-report.json.
    producer_h5_sha = str(typed.get("output_sha256", ""))
    require(trajectory_h5.suffix.lower() == ".h5" and trajectory_h5_sha == producer_h5_sha and len(producer_h5_sha) == 64,
            "typed317 producer H5 path/digest is not concrete")
    require(trajectory_h5.parent == typed_root, "typed317 output H5 is outside typed output root")

    completed(xmf_receipt, "XMF318 receipt")
    xmf_attempt, xmf_case, xmf_root_raw = identity(xmf_receipt)
    require(xmf_case == CASE_ID and
            xmf_attempt == "root-stage1-f5-c082s1-solid-fluid-recovery-short-native-xmf-318",
            "XMF318 receipt identity mismatch")
    xmf_root = Path(str(xmf_root_raw)).resolve()
    require(xmf.get("case_id") == CASE_ID and xmf.get("physical_case_id") == PHYSICAL_CASE_ID,
            "XMF318 case/physical identity mismatch")
    require(int(xmf.get("frames", -1)) == EXPECTED["frames"] and
            int(xmf.get("particles", -1)) == EXPECTED["total_particles"],
            "XMF318 dimensions mismatch")
    require(xmf.get("physical_condition_sha256") == CANONICAL_SHA and
            xmf.get("canonical_physical_condition_sha256") == CANONICAL_SHA and
            xmf.get("source_plan_condition_sha256") == SOURCE_PLAN_SHA,
            "XMF318 canonical/source-plan identity mismatch")
    require(xmf.get("source_h5_physical_condition_sha256") == LEGACY_H5_SCOPE_SHA and
            xmf.get("source_h5_sha256") == producer_h5_sha and
            xmf.get("source_h5_read_only") is True,
            "XMF318 H5 provenance mismatch")
    require(xmf.get("full801_authorized") is False and xmf.get("mass_rescale") is False,
            "XMF318 authorization/mass semantics changed")
    xdmf = Path(str(xmf.get("xdmf", ""))).resolve()
    require(xdmf.suffix.lower() == ".xmf" and xdmf.is_file(), "XMF318 case.xmf is missing")
    xdmf_sha = sha256_file(xdmf)
    require(xdmf_sha == xmf.get("xdmf_sha256"), "XMF318 case.xmf digest differs from manifest")
    require(Path(str(xmf.get("trajectory_h5"))).resolve() == trajectory_h5,
            "XMF318 trajectory H5 path differs from typed report")
    require(Path(str(xmf.get("conversion_report"))).resolve() == paths["typed_report"],
            "XMF318 conversion report path differs from typed report")
    require(Path(str(xmf.get("typed_receipt"))).resolve() == paths["typed_receipt"],
            "XMF318 typed receipt path differs from typed receipt")
    require(Path(str(xmf.get("native_receipt"))).resolve() == paths["short_receipt"],
            "XMF318 native receipt path differs from short receipt")
    xmf_manifest_sha = json_shas["xmf_manifest"]

    binding = {
        "schema": "ds02.f5.c082s1.short-event-bed-audit-binding.fresh096.v1",
        "status": "metadata_bound_root_review_required",
        "source_only": True,
        "case_id": CASE_ID,
        "physical_case_id": PHYSICAL_CASE_ID,
        "candidate_id": "C082S1_solid_fluid_recovery",
        "expected_dimension": EXPECTED["dimension"],
        "expected_frames": EXPECTED["frames"],
        "expected_particle_axis": EXPECTED["total_particles"],
        "expected_fixed_particles": EXPECTED["fixed_particles"],
        "expected_moving_particles": EXPECTED["moving_particles"],
        "expected_floating_particles": EXPECTED["floating_particles"],
        "expected_fluid_particles": EXPECTED["fluid_particles"],
        "actual_counts": placement_counts,
        "native_bed_marker_mk": 50,
        "source_bed_marker_mkbound": 40,
        "physical_condition_sha256": CANONICAL_SHA,
        "source_plan_physical_condition_sha256": SOURCE_PLAN_SHA,
        "source_h5_physical_condition_sha256": LEGACY_H5_SCOPE_SHA,
        "source_h5_scope_schema": LEGACY_SCOPE_SCHEMA,
        "source_h5_scope_status": LEGACY_SCOPE_STATUS,
        "physical_condition_hash_semantics": {
            "canonical_owner_sha256": CANONICAL_SHA,
            "source_plan_sha256": SOURCE_PLAN_SHA,
            "source_h5_sha256": LEGACY_H5_SCOPE_SHA,
            "source_h5_scope_schema": LEGACY_SCOPE_SCHEMA,
            "source_h5_scope_status": LEGACY_SCOPE_STATUS,
            "relation": "distinct; producer H5 attribute is legacy scope and is never substituted for canonical owner",
        },
        "gencase_receipt": str(paths["gencase_receipt"]),
        "gencase_receipt_sha256": json_shas["gencase_receipt"],
        "gencase_output_root": str(gen_root),
        "gencase_prepared_output_root": str(paths["prepared_report"].parent),
        "gencase_prepared_report": str(paths["prepared_report"]),
        "gencase_prepared_report_sha256": json_shas["prepared_report"],
        "canonical_generated_xml": str(paths["generated_xml"]),
        "canonical_generated_xml_sha256": generated_xml_sha,
        "initial_qa_receipt": str(paths["placement_receipt"]),
        "initial_qa_receipt_sha256": json_shas["placement_receipt"],
        "initial_qa_output_root": str(placement_root),
        "initial_qa_report": str(paths["placement_report"]),
        "initial_qa_report_sha256": json_shas["placement_report"],
        "short_solver_receipt": str(paths["short_receipt"]),
        "short_solver_receipt_sha256": json_shas["short_receipt"],
        "short_solver_output_root": str(short_root),
        "short_saved_state_metadata": {
            "path": str(paths["short_metadata"]),
            "sha256": json_shas["short_metadata"],
            "all_51_saved_states": True,
            "saved_state_count": EXPECTED["frames"],
        },
        "native_conversion_report": str(paths["typed_report"]),
        "native_conversion_report_sha256": json_shas["typed_report"],
        "native_conversion_receipt": str(paths["typed_receipt"]),
        "native_conversion_receipt_sha256": json_shas["typed_receipt"],
        "native_conversion_attempt_id": typed_attempt,
        "native_conversion_metadata": {
            "frames": EXPECTED["frames"],
            "particles": EXPECTED["total_particles"],
            "solver_dimension": dimension,
            "typed_role_counts": typed_roles,
            "observed_types": observed_types,
            "observed_mks": observed_mks,
            "native_bed_marker_mk": 50,
            "source_bed_marker_mkbound": 40,
            "coordinate_frame": typed.get("coordinate_frame"),
            "mass_report_without_rescale": bool(typed.get("mass_rescale") is False or xmf.get("mass_rescale") is False),
            "legacy_physical_scope_sha256": legacy_sha,
        },
        "trajectory_h5": str(trajectory_h5),
        "trajectory_h5_sha256": producer_h5_sha,
        "trajectory_h5_physical_condition_sha256": LEGACY_H5_SCOPE_SHA,
        "xdmf": str(xdmf),
        "xdmf_sha256": xdmf_sha,
        "xmf_manifest": str(paths["xmf_manifest"]),
        "xmf_manifest_sha256": xmf_manifest_sha,
        "xmf_receipt": str(paths["xmf_receipt"]),
        "xmf_receipt_sha256": json_shas["xmf_receipt"],
        "xmf_metadata": {
            "schema": xmf.get("schema"),
            "frames": EXPECTED["frames"],
            "particles": EXPECTED["total_particles"],
            "actual_time_s_is_producer_metadata": True,
            "visual_status": xmf.get("visual_status"),
            "full801_authorized": False,
            "mass_rescale": False,
        },
        "owner_metadata": str(paths["owner"]),
        "owner_metadata_sha256": owner_sha,
        "generated_xml_sha256": generated_xml_sha,
        "gencase_actual_metadata": {
            "attempt_id": gen_attempt,
            "total_particles": EXPECTED["total_particles"],
            "fluid_particles": EXPECTED["fluid_particles"],
            "solver_dimension_from_gencase": EXPECTED["dimension"],
            "prepared_report_sha256": json_shas["prepared_report"],
        },
        "stage1_placement": {
            "all_basic_placement_checks_pass": True,
            "numerical_precision_result_accepted": False,
            "central_mk50_surface_half_dp_counts": central_counts,
            "native_type0_mk50_count": int(coverage.get("native_type0_mk50_count", 0)),
            "fluid_y_levels": int(placement.get("fluid_geometry", {}).get("fluid_y_levels", 15)),
        },
        "mass_report_without_rescale": True,
        "continuum_fluid_mass_kg": owner.get("continuum_fluid_mass_kg"),
        "native_fluid_mass_kg": None,
        "short_event": {
            "window_s": [0.0, 1.0],
            "save_interval_s": 0.02,
            "frames": EXPECTED["frames"],
            "right_censored": True,
            "dynamic_acceptance": "not granted; Root must review every frame and visual render",
        },
        "future_output_hashes": None,
        "full801_authorized": False,
        "repair_success": "unknown_until_registered_dynamic_bed_audit_and_visual_review",
        "science_arrays_read_by_binder": False,
        "science_arrays_hashed_by_binder": False,
        "dynamic_worker_started_by_binder": False,
    }

    summary = {
        "schema": "ds02.f5.c082s1.actual-typed317-xmf318-metadata-summary.fresh096.v1",
        "status": "actual_upstream_metadata_bound_root_review_required",
        "case_id": CASE_ID,
        "physical_case_id": PHYSICAL_CASE_ID,
        "attempts": {
            "gencase": gen_attempt,
            "placement": placement_attempt,
            "short_native": short_attempt,
            "typed": typed_attempt,
            "xmf": xmf_attempt,
        },
        "counts": placement_counts,
        "typed317": {
            "report_sha256": json_shas["typed_report"],
            "receipt_sha256": json_shas["typed_receipt"],
            "frames": EXPECTED["frames"],
            "particles": EXPECTED["total_particles"],
            "solver_dimension_evidence": dimension,
            "typed_role_counts": typed_roles,
            "observed_types": observed_types,
            "observed_mks": observed_mks,
            "producer_h5_path": str(trajectory_h5),
            "producer_h5_sha256_from_report_only": producer_h5_sha,
        },
        "xmf318": {
            "manifest": str(paths["xmf_manifest"]),
            "manifest_sha256": xmf_manifest_sha,
            "receipt_sha256": json_shas["xmf_receipt"],
            "xdmf": str(xdmf),
            "xdmf_sha256": xdmf_sha,
            "source_h5_sha256_from_manifest": xmf.get("source_h5_sha256"),
        },
        "placement": {
            "report_sha256": json_shas["placement_report"],
            "receipt_sha256": json_shas["placement_receipt"],
            "central_mk50_surface_half_dp_counts": central_counts,
            "numerical_precision_result_accepted": False,
        },
        "physical_hash_semantics": {
            "canonical_owner_sha256": CANONICAL_SHA,
            "source_plan_sha256": SOURCE_PLAN_SHA,
            "legacy_h5_scope_sha256": LEGACY_H5_SCOPE_SHA,
            "legacy_scope_schema": LEGACY_SCOPE_SCHEMA,
            "cross_resolution_claim": False,
        },
        "future_and_acceptance": {
            "full801_authorized": False,
            "dynamic_bed_audit_started": False,
            "visual_acceptance": "pending",
            "repair_success": "unknown",
            "science_arrays_read_or_hashed_by_binder": False,
        },
        "producer_metadata_sha256s": json_shas | {"generated_xml": generated_xml_sha, "owner": owner_sha},
    }
    args.output_binding.parent.mkdir(parents=True, exist_ok=True)
    args.output_summary.parent.mkdir(parents=True, exist_ok=True)
    args.output_binding.write_text(json.dumps(binding, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.output_summary.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": binding["status"], "binding": str(args.output_binding), "summary": str(args.output_summary), "xmf_manifest_sha256": xmf_manifest_sha, "producer_h5_sha256_from_report_only": producer_h5_sha}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
