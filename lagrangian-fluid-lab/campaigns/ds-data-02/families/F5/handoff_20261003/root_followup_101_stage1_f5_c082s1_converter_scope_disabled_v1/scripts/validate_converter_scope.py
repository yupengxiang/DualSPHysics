#!/usr/bin/env python3
"""Metadata-only F5 fresh101 converter-scope and GenCase-contract validator.

The validator reads JSON/XML/Python metadata only.  It imports the checked-in
integration converter and calls ``_physical_condition_scope`` and
``canonical_hash``; it never calls conversion and refuses science-artifact
inputs.  A fresh099 candidate owner is deliberately treated as a custom owner
identity, not as ``ds-data-02.physical-binding.v1``.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

SCIENCE_SUFFIXES = {".dat", ".bi4", ".csv", ".h5", ".hdf5", ".vtk", ".vtu", ".xmf", ".xdmf"}
LEGACY_SCOPE_FIELDS = (
    "family_id", "physical_case_id", "lineage_group_id", "paired_background_id",
    "mechanism_id", "geometry_family_id", "geometry", "control_family_id",
    "gravity_m_s2", "density_kg_m3", "parameters", "initial_state",
    "continuum_geometry",
)


def fail(message: str) -> "NoReturn":
    raise ValueError(message)


def load_json(path: Path) -> dict[str, Any]:
    if path.suffix.lower() in SCIENCE_SUFFIXES:
        fail(f"science artifact is forbidden to metadata validator: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load JSON metadata: {path}") from exc
    if not isinstance(value, dict):
        fail(f"expected JSON object: {path}")
    return value


def sha256_static(path: Path) -> str:
    if path.suffix.lower() in SCIENCE_SUFFIXES:
        fail(f"science artifact hash is forbidden to metadata validator: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def load_converter(path: Path):
    spec = importlib.util.spec_from_file_location("ds02_fresh101_direct_convert", path)
    if spec is None or spec.loader is None:
        fail(f"cannot import direct converter: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def owner_digest_without_self_field(module: Any, owner: dict[str, Any]) -> str:
    candidate = dict(owner)
    candidate.pop("canonical_physical_condition_sha256", None)
    return module.canonical_hash(candidate)


def parse_definition(path: Path) -> dict[str, Any]:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise ValueError(f"cannot parse candidate Definition XML: {path}") from exc
    definition = root.find(".//geometry/definition")
    require(definition is not None, "candidate Definition lacks geometry/definition")
    dp = definition.get("dp")
    require(dp == "0.02", f"candidate Definition dp is not 0.02: {dp!r}")
    pointref = definition.find("pointref")
    pointmin = definition.find("pointmin")
    pointmax = definition.find("pointmax")
    require(pointref is not None and pointmin is not None and pointmax is not None,
            "candidate Definition lacks point reference/domain metadata")
    commands = root.findall(".//geometry/commands/mainlist/*")
    closed = [node for node in commands if node.tag == "drawextrude" and node.get("closed") == "true"]
    require(len(closed) == 1, f"candidate Definition closed drawextrude count is {len(closed)}")
    setmkbound = [node.get("mk") for node in commands if node.tag == "setmkbound"]
    setmkfluid = [node.get("mk") for node in commands if node.tag == "setmkfluid"]
    drawmodes = [node.get("mode") for node in commands if node.tag == "setdrawmode"]
    drawbox_fill = [node.findtext("boxfill") for node in commands if node.tag == "drawbox"]
    layer_specs = [node.find("layers").get("vdp") for node in commands if node.find("layers") is not None]
    motion_files = [node.get("name") for node in root.findall(".//motion//file")]
    output_dt = root.find(".//execution/special/gauges/default/_outputdt")
    computed_dt = root.find(".//execution/special/gauges/default/_computedt")
    return {
        "definition_sha256": sha256_static(path),
        "dp_m": float(dp),
        "pointref_m": {key: float(pointref.get(key)) for key in ("x", "y", "z")},
        "pointmin_m": {key: float(pointmin.get(key)) for key in ("x", "y", "z")},
        "pointmax_m": {key: float(pointmax.get(key)) for key in ("x", "y", "z")},
        "closed_drawextrude_count": len(closed),
        "closed_drawextrude": {
            "closed": True,
            "extrude": dict(closed[0].find("extrude").attrib) if closed[0].find("extrude") is not None else None,
            "layers": closed[0].find("layers").get("vdp") if closed[0].find("layers") is not None else None,
        },
        "setmkbound_sequence": setmkbound,
        "setmkfluid_sequence": setmkfluid,
        "drawmode_sequence": drawmodes,
        "drawbox_fill_sequence": drawbox_fill,
        "layer_specs": layer_specs,
        "motion_files": motion_files,
        "computed_dt_s": None if computed_dt is None else computed_dt.get("value"),
        "output_dt_s": None if output_dt is None else output_dt.get("value"),
        "generated_xml_data2d": None,
        "generated_xml_particle_counts": None,
        "semantic_status": "Definition source only; generated XML/producer counts are future root-bound values",
    }


def check_disabled_gencase(binding: dict[str, Any], request: dict[str, Any], owner: dict[str, Any], definition: Path) -> dict[str, Any]:
    require(binding.get("candidate_id") == owner.get("candidate_id"), "GenCase binding candidate mismatch")
    require(binding.get("physical_case_id") == owner.get("physical_case_id"), "GenCase binding physical case mismatch")
    require(binding.get("actual_counts") is None, "candidate actual_counts must remain producer-bound null")
    require(binding.get("expected_fluid") is None, "candidate expected_fluid must remain null")
    require(binding.get("solver_dimension_required") == 3, "candidate 3-D requirement missing")
    require(binding.get("native_bed_mk") == 50 and binding.get("source_mkbound") == 40,
            "native Mk50/source Mk40 mapping changed")
    require(binding.get("mass_rescale") is False, "candidate mass rescale is forbidden")
    require(request.get("schema") == "ds02.runner-request.v2", "GenCase request schema mismatch")
    require(request.get("kind") == "cpu" and request.get("cpu_task_kind") == "gencase",
            "GenCase request kind/allowlist contract mismatch")
    for key in ("disabled", "execution_allowed", "launch", "launch_allowed"):
        require(request.get(key) is (True if key == "disabled" else False),
                f"GenCase request is not disabled at {key}")
    require(request.get("arrays_allowed") is False and request.get("solver_allowed") is False,
            "GenCase request permits arrays or solver")
    require(request.get("genuine_gencase") is True and request.get("genuine_gencase_required") is True,
            "genuine GenCase requirement missing")
    require(request.get("actual_counts") is None and request.get("generated_xml") is None and request.get("generated_bi4") is None,
            "future GenCase products were prefilled")
    require(request.get("full801_authorized") is False and request.get("full16_authorized") is False,
            "GenCase request authorizes downstream run")
    require(request.get("independent_case_count_increment") == 0, "GenCase increments case credit")
    input_files = set(str(value) for value in request.get("input_files", []))
    require(str(definition) in input_files, "GenCase request does not bind candidate Definition")
    return {
        "binding_actual_counts": binding.get("actual_counts"),
        "binding_expected_fluid": binding.get("expected_fluid"),
        "solver_dimension_required": binding.get("solver_dimension_required"),
        "native_bed_mk": binding.get("native_bed_mk"),
        "source_mkbound": binding.get("source_mkbound"),
        "request_future_counts": request.get("actual_counts"),
        "request_generated_xml": request.get("generated_xml"),
        "request_generated_bi4": request.get("generated_bi4"),
        "request_disabled": True,
        "producer_fields_required_after_actual_run": [
            "execution-receipt.status=completed",
            "execution-receipt.output_root",
            "execution-receipt.producer_metadata.actual_total_particles",
            "execution-receipt.producer_metadata.generated_xml_particle_counts",
            "execution-receipt.solver_dimension_from_gencase=3",
            "prepared-input-report generated_xml_particle_counts",
            "generated XML execution/constants/data2d value=false",
            "generated XML SHA and producer-reported BI4 SHA",
        ],
    }


def inspect_candidate(args: argparse.Namespace, module: Any, baseline_owner: dict[str, Any]) -> dict[str, Any]:
    owner = load_json(args.owner)
    binding = load_json(args.gencase_binding)
    request = load_json(args.gencase_request)
    definition_info = parse_definition(args.definition)
    require(owner.get("candidate_id") == f"C082S1_MOTION_{args.candidate_id}", "candidate_id does not match owner")
    require(owner.get("source_definition_sha256") == definition_info["definition_sha256"],
            "candidate Definition SHA does not match owner source_definition_sha256")
    require(owner.get("source_plan_physical_condition_sha256") == definition_info["definition_sha256"],
            "source-plan SHA is not the candidate Definition SHA")
    expected_scale = {"A080": 0.8, "A120": 1.2}[args.candidate_id]
    require(owner.get("motion_transform", {}).get("scale") == expected_scale,
            f"{args.candidate_id} motion scale is not the legal {expected_scale}")
    require(owner.get("full801_authorized") is False and owner.get("full_visual_acceptance") is False,
            "fresh099 candidate unexpectedly grants full801/visual acceptance")
    require(owner.get("mass_rescale") is False, "fresh099 candidate mass policy changed")
    gencase_semantics = check_disabled_gencase(binding, request, owner, args.definition)

    candidate_scope = module._physical_condition_scope(owner)
    candidate_scope_sha = module.canonical_hash(candidate_scope)
    owner_digest = owner_digest_without_self_field(module, owner)
    declared_owner_digest = owner.get("canonical_physical_condition_sha256")
    require(owner_digest == declared_owner_digest,
            "fresh099 owner self-excluding digest no longer matches its declared owner identity")
    require(candidate_scope.get("schema") == "legacy-owner-scope.v0",
            "fresh099 candidate unexpectedly supplied explicit physical_binding.v1")
    require(candidate_scope.get("semantic_binding_status") == "legacy_incomplete; no cross-resolution physical claim",
            "legacy scope status changed")
    require(candidate_scope_sha not in {declared_owner_digest, owner.get("source_plan_physical_condition_sha256")},
            "converter legacy probe collapsed into candidate owner/source-plan identity")
    missing_legacy_fields = [key for key in LEGACY_SCOPE_FIELDS if key not in owner]

    baseline_scope = module._physical_condition_scope(baseline_owner)
    baseline_scope_sha = module.canonical_hash(baseline_scope)
    require(baseline_scope_sha == baseline_owner.get("legacy_scope_sha256"),
            "baseline actual converter legacy scope does not match registered metadata")
    baseline_counts = baseline_owner.get("actual_counts")
    expected_baseline_counts = {
        "dimension": 3,
        "fixed_particles": 158559,
        "floating_particles": 0,
        "fluid_particles": 31658,
        "moving_particles": 4210,
        "total_particles": 194427,
    }
    require(isinstance(baseline_counts, dict), "baseline C082S1 actual_counts is not an object")
    require(all(baseline_counts.get(key) == value for key, value in expected_baseline_counts.items()),
            "baseline C082S1 actual counts changed or were not producer-bound")

    return {
        "schema": "ds02.f5.c082s1.converter-scope-candidate-report.fresh101.v1",
        "status": "passed_with_converter_hold",
        "candidate_id": args.candidate_id,
        "candidate_id_semantics": "fresh099 bounded-excitation owner identity; not ds-data-02.physical-binding.v1",
        "case_id": owner.get("case_id"),
        "physical_case_id": owner.get("physical_case_id"),
        "motion_scale": expected_scale,
        "source_definition": str(args.definition.resolve()),
        "source_definition_sha256": definition_info["definition_sha256"],
        "source_plan_physical_condition_sha256": owner.get("source_plan_physical_condition_sha256"),
        "definition_semantics": definition_info,
        "fresh099_owner_identity": {
            "owner_metadata": str(args.owner.resolve()),
            "owner_metadata_sha256": sha256_static(args.owner),
            "declared_canonical_physical_condition_sha256": declared_owner_digest,
            "recomputed_self_excluding_owner_digest": owner_digest,
            "matches_declared": True,
            "field_semantics": "custom fresh099 whole-owner identity; never passed as converter physical_condition_sha256",
        },
        "converter_scope_probe": {
            "function": "ds_data02_direct_convert._physical_condition_scope",
            "canonical_hash_function": "ds_data02_direct_convert.canonical_hash",
            "scope_schema": candidate_scope.get("schema"),
            "scope_sha256": candidate_scope_sha,
            "scope_semantic_status": candidate_scope.get("semantic_binding_status"),
            "scope_fields_present": sorted(candidate_scope),
            "legacy_required_fields_missing_from_candidate_owner": missing_legacy_fields,
            "explicit_physical_binding_present": "physical_binding" in owner,
            "physical_binding_schema": module.PHYSICAL_BINDING_SCHEMA,
            "direct_conversion_eligible": False,
            "eligibility_reason": "fresh099 owner lacks explicit physical_binding.v1 and is incomplete as a legacy converter owner; Root must bind a fresh producer owner or explicit physical binding before any conversion",
        },
        "hash_layers": {
            "fresh099_owner_identity_sha256": declared_owner_digest,
            "converter_legacy_probe_sha256": candidate_scope_sha,
            "source_plan_sha256": owner.get("source_plan_physical_condition_sha256"),
            "all_layers_distinct": len({declared_owner_digest, candidate_scope_sha, owner.get("source_plan_physical_condition_sha256")}) == 3,
            "owner_digest_is_not_converter_scope": True,
            "legacy_scope_is_not_source_plan": True,
        },
        "baseline_c082s1_actual_provenance": {
            "owner_metadata": str(args.baseline_owner.resolve()),
            "owner_metadata_sha256": sha256_static(args.baseline_owner),
            "actual_counts": baseline_counts,
            "generated_xml_sha256": baseline_owner.get("generated_xml_sha256"),
            "prepared_input_report_sha256": baseline_owner.get("gencase_prepared_report_sha256"),
            "gencase_receipt_sha256": baseline_owner.get("gencase_receipt_sha256"),
            "physical_condition_sha256": baseline_owner.get("physical_condition_sha256"),
            "legacy_scope_sha256": baseline_scope_sha,
            "counts_semantics": "actual C082S1 baseline only; never copied into A080/A120 candidate counts",
        },
        "gencase_contract": gencase_semantics,
        "future_producer_values": {
            "actual_counts": None,
            "generated_xml_particle_counts": None,
            "solver_dimension_from_gencase": None,
            "generated_xml_sha256": None,
            "generated_bi4_sha256": None,
            "prepared_input_report_sha256": None,
            "gencase_receipt_sha256": None,
            "motion_output_sha256": None,
            "conversion_report_sha256": None,
            "trajectory_h5_sha256": None,
        },
        "downstream_policy": {
            "motion_transform": "disabled; Root may run only after review",
            "genuine_gencase": "disabled; actual producer must supply counts/XML/BI4/3-D metadata",
            "initial_placement_mk50": "disabled until candidate producer output; preserve native Mk50/source Mk40 mapping",
            "short_native": "disabled",
            "typed_conversion": "disabled; no converter owner is currently eligible",
            "xmf_render_bed_audit": "disabled",
            "full16_full801": "disabled; no default approval",
            "case_credit": 0,
            "precision_grant": False,
        },
        "source_only": True,
        "science_arrays_read": False,
        "science_arrays_hashed": False,
        "conversion_run": False,
        "job_started": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-id", choices=("A080", "A120"), required=True)
    parser.add_argument("--owner", type=Path, required=True)
    parser.add_argument("--definition", type=Path, required=True)
    parser.add_argument("--gencase-binding", type=Path, required=True)
    parser.add_argument("--gencase-request", type=Path, required=True)
    parser.add_argument("--baseline-owner", type=Path, required=True)
    parser.add_argument("--converter", type=Path, required=True)
    parser.add_argument("--root230-entrypoint", type=Path, required=True)
    parser.add_argument("--root230-policy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    module = load_converter(args.converter)
    baseline_owner = load_json(args.baseline_owner)
    report = inspect_candidate(args, module, baseline_owner)
    report["converter_source"] = str(args.converter.resolve())
    report["converter_source_sha256"] = sha256_static(args.converter)
    report["root230_semantics"] = {
        "entrypoint": str(args.root230_entrypoint.resolve()),
        "entrypoint_sha256": sha256_static(args.root230_entrypoint),
        "policy_source": str(args.root230_policy.resolve()),
        "policy_source_sha256": sha256_static(args.root230_policy),
        "semantic_gencase_fields_are_future_producer_fields": True,
        "required_fields": [
            "execution-receipt.output_root",
            "execution-receipt.producer_metadata.actual_total_particles",
            "execution-receipt.producer_metadata.generated_xml_particle_counts",
            "execution-receipt.solver_dimension_from_gencase",
            "prepared-input-report.generated_xml_particle_counts",
            "generated XML execution/constants/data2d=false",
        ],
        "launch_owner": "root",
        "request_disabled": True,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"candidate_id": args.candidate_id, "status": report["status"], "scope_sha256": report["converter_scope_probe"]["scope_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
