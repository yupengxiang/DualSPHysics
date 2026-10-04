#!/usr/bin/env python3
"""Bind fresh065 motion/GenCase JSON receipts without reading BI4/CSV/H5 arrays.

The --mode static path checks source plans and canonical owners.  The --mode bind
path is run by Root only after the disabled motion and genuine GenCase requests
complete.  It reads JSON receipts and generated XML metadata, computes hashes,
and emits the binding consumed by the Root-enabled official PartVTK QA worker.
It never opens a BI4, CSV, H5, or solver data file.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

EXPECTED_BLOCKS = [
    {"name": "fixed", "begin": 0, "count": 27495, "type": 0, "mk": 10},
    {"name": "moving", "begin": 27495, "count": 1984, "type": 1, "mk": 12},
    {"name": "fluid", "begin": 29479, "count": 40700, "type": 3, "mk": 2},
]
EXPECTED = {
    "total": 70179,
    "fixed": 27495,
    "moving": 1984,
    "fluid": 40700,
    "dp_m": 0.02,
    "time_max_s": 12.0,
    "time_out_s": 0.02,
    "frames": 601,
    "motion_rows": 12001,
    "native_fluid_mass_kg": 325.60001628,
    "continuum_envelope_mass_kg": 320.1984,
}
PARTVTK = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64")
SOURCE_DEF_SHA = "f45a212f48ae0d55485e795b63e38702edd5cd2aac40aa69d4be9c155e7a4d37"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def completed(path: Path, label: str) -> dict[str, Any]:
    require(path.is_file(), f"{label} missing: {path}")
    value = load(path)
    require(value.get("status") == "completed", f"{label} status is not completed")
    require(value.get("returncode") == 0, f"{label} returncode is not zero")
    return value


def static_check(plan_path: Path, owner_dir: Path) -> dict[str, Any]:
    plan = load(plan_path)
    require(plan.get("schema") == "ds02.f7.stage1.first8-target-angle-source-plan.v1", "unexpected fresh065 plan schema")
    require(plan.get("family_id") == "F7", "plan family mismatch")
    contract = plan.get("stage_contract", {})
    require(contract.get("launch_allowed") is False, "plan is not disabled")
    require(contract.get("endpoint_count") == 5, "fresh065 must contain five new endpoints")
    require(contract.get("first8_axis_values_deg") == [30.0, 35.0, 40.0, 45.0, 50.0, 55.0, 60.0, 65.0], "first8 axis changed")
    require(contract.get("fresh_internal_axis_values_deg") == [35.0, 40.0, 50.0, 55.0, 60.0], "fresh angle replacement changed")
    require(plan["mother_binding"]["verified_target_amplitude_deg"] == 45.0, "verified mother angle changed")
    require(plan["collision_resolution"]["replacement_angle_deg"] == 50.0, "replacement angle changed")
    require(sha(Path(plan["source_definition"])) == plan["source_definition_sha256"], "mother Definition hash changed")
    require(sha(Path(plan["selected_motion_module"])) == plan["selected_motion_module_sha256"], "selected motion module hash changed")
    require(sha(Path(plan["source_motion_template"])) == plan["source_motion_template_sha256"], "source motion template hash changed")
    require(len(plan.get("endpoints", [])) == 5, "fresh065 endpoint plan is incomplete")
    owners = []
    for endpoint in plan["endpoints"]:
        source = plan_path.parent / endpoint["source_definition_clone"]
        require(source.is_file(), f"source Definition clone missing: {source}")
        require(sha(source) == endpoint["source_definition_clone_sha256"], f"source Definition clone hash changed: {source}")
        owner_path = owner_dir / f"{endpoint['endpoint_id']}.owner.json"
        owner = load(owner_path)
        require(owner.get("launch_allowed") is False, f"owner is enabled: {owner_path}")
        binding = owner.get("physical_binding")
        require(isinstance(binding, dict), f"owner lacks physical binding: {owner_path}")
        require(canonical_hash(binding) == owner.get("canonical_physical_binding_sha256"), f"owner canonical hash is stale: {owner_path}")
        require(owner.get("physical_condition_sha256") == endpoint["physical_condition_sha256"], f"owner source hash mismatch: {owner_path}")
        owners.append({
            "case_id": endpoint["endpoint_id"],
            "source_condition_sha256": endpoint["physical_condition_sha256"],
            "canonical_physical_binding_sha256": owner["canonical_physical_binding_sha256"],
        })
    return {
        "plan": str(plan_path),
        "plan_sha256": sha(plan_path),
        "endpoint_count": 5,
        "owners": owners,
        "source_definition_sha256": plan["source_definition_sha256"],
        "mother_target_angle_deg": 45.0,
        "replacement_target_angle_deg": 50.0,
        "launch_allowed": False,
    }


def xml_contract(xml_path: Path, endpoint: dict[str, Any]) -> dict[str, Any]:
    require(xml_path.is_file(), f"generated XML missing: {xml_path}")
    root = ET.parse(xml_path).getroot()
    definition = root.find("casedef/geometry/definition")
    constants = root.find("execution/constants")
    particles = root.find("execution/particles")
    require(definition is not None and constants is not None and particles is not None, f"generated XML lacks contract sections: {xml_path}")
    data2d = constants.find("data2d")
    params = {str(node.get("key")): str(node.get("value")) for node in root.findall("execution/parameters/parameter")}
    counts = {}
    for block in EXPECTED_BLOCKS:
        node = particles.find(block["name"])
        require(node is not None, f"generated XML missing block {block['name']}: {xml_path}")
        counts[block["name"]] = {
            "begin": int(node.get("begin")),
            "count": int(node.get("count")),
            "type": int(node.get("type")),
            "mk": int(node.get("mk")),
        }
    checks = {
        "dp": definition.get("dp") == "0.02",
        "actual_3d": data2d is not None and data2d.get("value") == "false",
        "time_max": params.get("TimeMax") == "12",
        "time_out": params.get("TimeOut") == "0.02",
        "counts": all(counts[b["name"]] == {k: b[k] for k in ("begin", "count", "type", "mk")} for b in EXPECTED_BLOCKS),
        "total": int(particles.get("np")) == EXPECTED["total"],
        "fixed": int(particles.get("nbf")) == EXPECTED["fixed"],
        "moving_plus_fixed": int(particles.get("nb")) == EXPECTED["fixed"] + EXPECTED["moving"],
    }
    require(all(checks.values()), f"generated XML contract failed for {endpoint['endpoint_id']}: {checks}")
    return {
        "xml_sha256": sha(xml_path),
        "counts": counts,
        "total": int(particles.get("np")),
        "actual_3d": True,
        "dp_m": EXPECTED["dp_m"],
        "time_max_s": EXPECTED["time_max_s"],
        "time_out_s": EXPECTED["time_out_s"],
    }


def bind(plan_path: Path, motion_report_path: Path, motion_receipt_path: Path,
         gencase_report_path: Path, owner_dir: Path, output_path: Path) -> dict[str, Any]:
    static = static_check(plan_path, owner_dir)
    plan = load(plan_path)
    motion_report = load(motion_report_path)
    require(motion_report.get("schema") == "ds02.f7.target-angle-source-preparation.v1", "motion report schema changed")
    require(motion_report.get("launch_allowed") is False, "motion report unexpectedly enabled")
    require(motion_report.get("source_plan_sha256") == static["plan_sha256"], "motion report plan hash changed")
    motion_receipt = completed(motion_receipt_path, "motion preparation receipt")
    gencase_report = load(gencase_report_path)
    require(gencase_report.get("schema") == "ds02.f7.target-angle-gencase-result.v1", "GenCase report schema changed")
    require(gencase_report.get("status") == "completed", "GenCase report is not completed")
    require(gencase_report.get("returncode_failures") == 0, "GenCase report contains failures")
    require(gencase_report.get("endpoint_count") == 5, "GenCase report endpoint count changed")
    motion_rows = {row["endpoint_id"]: row for row in motion_report.get("endpoints", [])}
    gencase_rows = {row["endpoint_id"]: row for row in gencase_report.get("endpoints", [])}
    require(set(motion_rows) == set(gencase_rows) == {e["endpoint_id"] for e in plan["endpoints"]}, "motion/GenCase endpoint sets differ")
    cases = []
    for endpoint in plan["endpoints"]:
        case_id = endpoint["endpoint_id"]
        mrow = motion_rows[case_id]
        grow = gencase_rows[case_id]
        require(grow.get("executed") is True and grow.get("returncode") == 0, f"GenCase did not complete: {case_id}")
        generated_xml = Path(grow["generated_xml"])
        generated_bi4 = Path(grow["generated_bi4"])
        generated_definition = Path(mrow["prepared_definition"])
        generated_motion = Path(mrow["motion_file"])
        gencase_receipt = generated_xml.parent / "execution-receipt.json"
        prepared_input_report = generated_xml.parent / "prepared-input-report.json"
        receipt = completed(gencase_receipt, f"GenCase receipt {case_id}")
        require(receipt.get("total_particles") == EXPECTED["total"], f"GenCase total metadata changed: {case_id}")
        require(receipt.get("fluid_particles") == EXPECTED["fluid"], f"GenCase fluid metadata changed: {case_id}")
        require(receipt.get("solver_dimension_from_gencase") == 3, f"GenCase dimension metadata changed: {case_id}")
        contract = xml_contract(generated_xml, endpoint)
        require(grow.get("generated_xml_sha256") == contract["xml_sha256"], f"GenCase XML hash row stale: {case_id}")
        require(generated_bi4.is_file(), f"generated BI4 missing: {case_id}")
        require(prepared_input_report.is_file(), f"prepared input report missing: {case_id}")
        preflight = load(prepared_input_report)
        require(preflight.get("schema") == "ds02.root.actual-native-source-preflight.v1", f"preflight schema changed: {case_id}")
        require(preflight.get("actual_total_particles") == EXPECTED["total"], f"preflight total changed: {case_id}")
        require(preflight.get("xml_sha256") == contract["xml_sha256"], f"preflight XML hash changed: {case_id}")
        require(preflight.get("bi4_sha256") == sha(generated_bi4), f"preflight BI4 hash changed: {case_id}")
        require(sha(generated_definition) == endpoint["source_definition_clone_sha256"], f"prepared Definition changed: {case_id}")
        require(sha(generated_motion) == mrow["motion_file_sha256"], f"prepared motion changed: {case_id}")
        cases.append({
            "role": f"new_internal_{int(endpoint['amplitude_deg']):03d}",
            "endpoint_id": case_id,
            "case_id": case_id,
            "amplitude_deg": endpoint["amplitude_deg"],
            "physical_condition_sha256": endpoint["physical_condition_sha256"],
            "source_definition": str(plan_path.parent / endpoint["source_definition_clone"]),
            "source_definition_sha256": endpoint["source_definition_clone_sha256"],
            "prepared_definition": str(generated_definition),
            "prepared_definition_sha256": sha(generated_definition),
            "source_motion": str(generated_motion),
            "source_motion_sha256": sha(generated_motion),
            "generated_definition": str(generated_definition),
            "generated_definition_sha256": sha(generated_definition),
            "generated_motion": str(generated_motion),
            "generated_motion_sha256": sha(generated_motion),
            "generated_xml": str(generated_xml),
            "generated_xml_sha256": contract["xml_sha256"],
            "generated_bi4": str(generated_bi4),
            "generated_bi4_sha256": sha(generated_bi4),
            "gencase_receipt": str(gencase_receipt),
            "gencase_receipt_sha256": sha(gencase_receipt),
            "prepared_input_report": str(prepared_input_report),
            "prepared_input_report_sha256": sha(prepared_input_report),
            "expected": {
                "total_particles": EXPECTED["total"], "fixed_particles": EXPECTED["fixed"],
                "moving_particles": EXPECTED["moving"], "fluid_particles": EXPECTED["fluid"],
                "solver_dimension": 3, "dp_m": EXPECTED["dp_m"],
                "type_mk_blocks": EXPECTED_BLOCKS, "motion_rows": EXPECTED["motion_rows"],
                "velocity_zero_tolerance_m_per_s": 1e-12,
                "native_fluid_mass_kg": EXPECTED["native_fluid_mass_kg"],
                "continuum_envelope_mass_kg": EXPECTED["continuum_envelope_mass_kg"],
                "mass_tolerance_kg": 1e-8,
            },
        })
    endpoint_metadata = {case_id: motion_rows[case_id] for case_id in motion_rows}
    binding = {
        "schema": "ds02.f7.first8-target-angle-actual-native-qa-binding.v1",
        "family_id": "F7", "scope_id": "root_followup_065_stage1_first8_target_angles_v1",
        "parent_source_plan": str(plan_path), "parent_source_plan_sha256": static["plan_sha256"],
        "motion_preparation_report": str(motion_report_path),
        "motion_preparation_report_sha256": sha(motion_report_path),
        "motion_preparation_receipt": str(motion_receipt_path),
        "motion_preparation_receipt_sha256": sha(motion_receipt_path),
        "motion_preparation_receipt_status": motion_receipt.get("status"),
        "partvtk": str(PARTVTK), "partvtk_sha256": sha(PARTVTK),
        "stage_contract": {
            "endpoint_count": 5, "axis": "paddle_amplitude_deg",
            "axis_values_deg": [35.0, 40.0, 50.0, 55.0, 60.0],
            "native_initial_only": True, "launch_allowed": False,
            "production_approval": "none", "q_n_status": "not_assessed",
            "visual_acceptance": "pending actual native/whole-frame review",
            "no_solver_in_worker": True, "no_conversion": True, "no_rendering": True,
            "array_policy": "only the Root-enabled official PartVTK worker may read BI4; this binder reads JSON/XML metadata only",
        },
        "mother_recipe": {
            "native_total_particles": EXPECTED["total"], "native_fixed_particles": EXPECTED["fixed"],
            "native_moving_particles": EXPECTED["moving"], "native_fluid_particles": EXPECTED["fluid"],
            "dp_m": EXPECTED["dp_m"], "time_max_s": EXPECTED["time_max_s"], "time_out_s": EXPECTED["time_out_s"],
            "native_frame_count": EXPECTED["frames"], "motion_rows": EXPECTED["motion_rows"],
            "native_motion_reader": "piecewise_linear_absolute_angle_increment",
            "analytic_target_regular": "C2", "native_sampled_regular": "not C2",
            "pivot_p1_m": [-0.04, 0.0, 0.05], "pivot_p2_m": [-0.04, 0.0, 1.05],
            "native_fluid_mass_kg": EXPECTED["native_fluid_mass_kg"],
            "continuum_envelope_mass_kg": EXPECTED["continuum_envelope_mass_kg"],
            "mass_policy": "native unscaled; report against continuum separately; no rescale",
        },
        "forcing_source": {
            "source_plan": str(plan_path), "source_plan_sha256": static["plan_sha256"],
            "motion_preparation_report": str(motion_report_path),
            "motion_preparation_report_sha256": sha(motion_report_path),
            "motion_preparation_receipt": str(motion_receipt_path),
            "motion_preparation_receipt_sha256": sha(motion_receipt_path),
            "motion_preparation_schema": "ds02.f7.target-angle-source-preparation.v1",
            "endpoint_metadata": endpoint_metadata,
        },
        "source_wet_obstacle_contract": {
            "required_definition_fragments": [
                'dp="0.02"', '<setmkbound mk="2">', '<setmkfluid mk="1">',
                "Explicit native cell-center slab 0", "Explicit native cell-center slab 1",
                "Explicit native cell-center slab 2", "Explicit native cell-center slab 3",
                '<boxfill>solid</boxfill>',
            ],
        },
        "cases": cases,
        "launch_allowed": False, "launch": False, "status": "source_bound_root_review_required",
        "q_n_status": "not_assessed", "precision_status": "not_accepted",
        "production_approval": "none",
        "claim_boundary": "JSON/XML source and genuine GenCase binding only; PartVTK typed initial checks, full native dynamics, visual acceptance, Q-N, and domain approval remain pending.",
    }
    require(not output_path.exists(), f"refusing to overwrite binding: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(binding, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "binding": str(output_path),
        "binding_sha256": sha(output_path),
        "cases": [row["case_id"] for row in cases],
        "all_gencase_completed_zero": True,
        "array_files_opened": False,
        "launch_allowed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("static", "bind"), required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--owner-dir", type=Path, default=None)
    parser.add_argument("--motion-report", type=Path)
    parser.add_argument("--motion-receipt", type=Path)
    parser.add_argument("--gencase-report", type=Path)
    parser.add_argument("--output-binding", type=Path)
    args = parser.parse_args()
    owner_dir = args.owner_dir or args.plan.parent.parent / "owners"
    if args.mode == "static":
        print(json.dumps(static_check(args.plan, owner_dir), indent=2, sort_keys=True))
        return 0
    for value, label in (
        (args.motion_report, "--motion-report"), (args.motion_receipt, "--motion-receipt"),
        (args.gencase_report, "--gencase-report"), (args.output_binding, "--output-binding"),
    ):
        if value is None:
            parser.error(f"{label} is required in bind mode")
    print(json.dumps(bind(args.plan, args.motion_report, args.motion_receipt, args.gencase_report,
                          owner_dir, args.output_binding), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
