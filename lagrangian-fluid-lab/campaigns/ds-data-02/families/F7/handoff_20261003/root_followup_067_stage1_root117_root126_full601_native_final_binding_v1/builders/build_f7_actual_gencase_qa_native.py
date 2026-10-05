#!/usr/bin/env python3
"""Bind Root117 per-case GenCase outputs and emit disabled F7 QA/solver requests.

This metadata-only builder intentionally treats Root117's top-level wrapper
receipt as a preserved failure (returncode 0, missing aggregate count) and
accepts only the five actual per-case receipts as GenCase evidence.  It parses
XML metadata and hashes XML/BI4/motion files; it never decodes BI4, invokes
PartVTK, invokes GenCase, starts a solver, or reads CSV arrays.  Root runs the
separate disabled requests later.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import pathlib
import xml.etree.ElementTree as ET
from typing import Any

EXPECTED_BLOCKS = {
    "fixed": {"begin": 0, "count": 27495, "mk": 10, "mk_attr": "mkbound", "mk_value": 0},
    "moving": {"begin": 27495, "count": 1984, "mk": 12, "mk_attr": "mkbound", "mk_value": 2},
    "fluid": {"begin": 29479, "count": 40700, "mk": 2, "mk_attr": "mkfluid", "mk_value": 1},
}
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
PACKAGE_SCOPE = "root_followup_066_stage1_actual_gencase_qa_native_v1"
ROOT_FAMILY = pathlib.Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7")
PYTHON = pathlib.Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
RUNTIME = pathlib.Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py")
STRICT = pathlib.Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py")
PARTVTK = pathlib.Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64")
SOLVER = pathlib.Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64")
SOURCE_QA_WORKER = pathlib.Path(
    "/home/jade/.codex/worktrees/ds-data-02-f7/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/families/F7/handoff_20261003/"
    "root_followup_065_stage1_first8_target_angles_v1/workers/"
    "run_f7_first8_target_angle_native_initial_qa.py"
)


class BuildError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise BuildError(message)


def sha(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load(path: pathlib.Path) -> dict[str, Any]:
    require(path.is_file(), f"missing JSON: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"JSON object required: {path}")
    return value


def write_json(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    require(not path.exists(), f"refusing to overwrite {path}")
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def plan_and_owners(plan_path: pathlib.Path, owner_dir: pathlib.Path) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    plan = load(plan_path)
    require(plan.get("schema") == "ds02.f7.stage1.first8-target-angle-source-plan.v1", "unexpected fresh065 plan schema")
    require(plan.get("family_id") == "F7", "source plan family mismatch")
    require(plan.get("scope_id") == "root_followup_065_stage1_first8_target_angles_v1", "source plan scope mismatch")
    contract = plan.get("stage_contract", {})
    require(contract.get("endpoint_count") == 5 and contract.get("launch_allowed") is False, "fresh065 plan must remain disabled")
    require(contract.get("fresh_internal_axis_values_deg") == [35.0, 40.0, 50.0, 55.0, 60.0], "fresh065 endpoint axis changed")
    require(sha(plan_path) == plan.get("source_plan_sha256", sha(plan_path)), "source plan self hash field is stale") if "source_plan_sha256" in plan else None
    endpoints = plan.get("endpoints", [])
    require(len(endpoints) == 5, "fresh065 endpoint plan is not five cases")
    owners = []
    for endpoint in endpoints:
        case_id = endpoint["endpoint_id"]
        owner_path = owner_dir / f"{case_id}.owner.json"
        owner = load(owner_path)
        require(owner.get("launch_allowed") is False, f"owner is enabled: {case_id}")
        binding = owner.get("physical_binding")
        require(isinstance(binding, dict), f"owner physical binding missing: {case_id}")
        owner_canonical = owner.get("canonical_physical_binding_sha256")
        require(owner_canonical == canonical_hash(binding), f"owner canonical hash stale: {case_id}")
        require(owner.get("physical_condition_sha256") == endpoint.get("physical_condition_sha256"), f"owner condition mismatch: {case_id}")
        source = owner.get("source", {})
        require(source.get("source_plan") == str(plan_path), f"owner source plan path mismatch: {case_id}")
        require(source.get("source_plan_sha256") == sha(plan_path), f"owner source plan hash mismatch: {case_id}")
        owners.append({
            "path": str(owner_path),
            "sha256": sha(owner_path),
            "case_id": case_id,
            "physical_condition_sha256": endpoint["physical_condition_sha256"],
            "canonical_physical_binding_sha256": owner_canonical,
            "source_plan_path": str(plan_path),
            "source_plan_sha256": sha(plan_path),
            "physical_binding": binding,
        })
    return plan, owners, sha(plan_path)


def verify_xml(xml_path: pathlib.Path, endpoint_id: str) -> dict[str, Any]:
    require(xml_path.is_file(), f"generated XML missing: {endpoint_id}")
    root = ET.parse(xml_path).getroot()
    constants = root.find("./execution/constants")
    parameters = {node.get("key"): node.get("value") for node in root.findall("./execution/parameters/parameter")}
    particles = root.find("./execution/particles")
    require(constants is not None and particles is not None, f"XML contract sections missing: {endpoint_id}")
    data2d = constants.find("data2d")
    dp = constants.find("dp")
    require(data2d is not None and data2d.get("value") == "false", f"XML is not actual 3D: {endpoint_id}")
    require(dp is not None and float(dp.get("value")) == EXPECTED["dp_m"], f"native dp changed: {endpoint_id}")
    require(parameters.get("TimeMax") == "12" and parameters.get("TimeOut") == "0.02", f"native time window changed: {endpoint_id}")
    require(int(particles.get("np")) == EXPECTED["total"], f"native total changed: {endpoint_id}")
    require(int(particles.get("nbf")) == EXPECTED["fixed"], f"native fixed changed: {endpoint_id}")
    require(int(particles.get("nb")) == EXPECTED["fixed"] + EXPECTED["moving"], f"native boundary total changed: {endpoint_id}")
    blocks = {}
    for name, expected in EXPECTED_BLOCKS.items():
        node = particles.find(name)
        require(node is not None, f"XML block missing {name}: {endpoint_id}")
        require(int(node.get("begin")) == expected["begin"], f"XML {name} begin changed: {endpoint_id}")
        require(int(node.get("count")) == expected["count"], f"XML {name} count changed: {endpoint_id}")
        require(int(node.get(expected["mk_attr"])) == expected["mk_value"], f"XML {name} native type changed: {endpoint_id}")
        require(int(node.get("mk")) == expected["mk"], f"XML {name} Mk changed: {endpoint_id}")
        blocks[name] = {
            "begin": expected["begin"],
            "count": expected["count"],
            "native_type": {"fixed": 0, "moving": 1, "fluid": 3}[name],
            "mk": expected["mk"],
        }
    return {
        "xml_sha256": sha(xml_path),
        "actual_3d": True,
        "dp_m": EXPECTED["dp_m"],
        "time_max_s": EXPECTED["time_max_s"],
        "time_out_s": EXPECTED["time_out_s"],
        "total_particles": EXPECTED["total"],
        "blocks": blocks,
    }


def verify_motion(motion_report: dict[str, Any], motion_receipt: dict[str, Any], plan_path: pathlib.Path, endpoint_ids: set[str]) -> dict[str, dict[str, Any]]:
    require(motion_report.get("schema") == "ds02.f7.target-angle-source-preparation.v1", "Root116 motion report schema mismatch")
    require(motion_report.get("source_plan_sha256") == sha(plan_path), "Root116 source plan hash mismatch")
    require(motion_receipt.get("status") == "completed" and motion_receipt.get("returncode") == 0, "Root116 receipt is not completed/0")
    rows = {row.get("endpoint_id"): row for row in motion_report.get("endpoints", [])}
    require(set(rows) == endpoint_ids and len(rows) == 5, "Root116 motion endpoint set mismatch")
    for case_id, row in rows.items():
        require(row.get("motion_rows") == EXPECTED["motion_rows"], f"Root116 motion rows changed: {case_id}")
        require(row.get("native_reader") == "piecewise_linear_absolute_angle_increment", f"Root116 native reader changed: {case_id}")
        require(row.get("native_sampled_regular") == "not C2", f"Root116 native regularity overclaimed: {case_id}")
        require(row.get("motion_only_undo", {}).get("geometry_identical") is True, f"Root116 geometry changed: {case_id}")
        require(row.get("motion_only_undo", {}).get("execution_identical") is True, f"Root116 execution changed: {case_id}")
        motion_file = pathlib.Path(row["motion_file"])
        prepared_definition = pathlib.Path(row["prepared_definition"])
        require(motion_file.is_file() and prepared_definition.is_file(), f"Root116 prepared inputs missing: {case_id}")
        require(sha(motion_file) == row.get("motion_file_sha256"), f"Root116 motion hash mismatch: {case_id}")
        require(sha(prepared_definition) == row.get("prepared_definition_sha256"), f"Root116 Definition hash mismatch: {case_id}")
    return rows


def bind_actual(args: argparse.Namespace) -> dict[str, Any]:
    output_root = pathlib.Path(args.output_root).resolve()
    metadata_dir = output_root / "metadata"
    request_dir = output_root / "requests"
    worker_dir = output_root / "workers"
    plan_path = pathlib.Path(args.plan).resolve()
    motion_report_path = pathlib.Path(args.motion_report).resolve()
    motion_receipt_path = pathlib.Path(args.motion_receipt).resolve()
    gencase_report_path = pathlib.Path(args.gencase_report).resolve()
    top_receipt_path = pathlib.Path(args.top_receipt).resolve()
    owner_dir = pathlib.Path(args.owner_dir).resolve()
    plan, owners, plan_sha = plan_and_owners(plan_path, owner_dir)
    motion_report = load(motion_report_path)
    motion_receipt = load(motion_receipt_path)
    endpoints = {endpoint["endpoint_id"] for endpoint in plan["endpoints"]}
    motion_rows = verify_motion(motion_report, motion_receipt, plan_path, endpoints)
    gencase_report = load(gencase_report_path)
    top_receipt = load(top_receipt_path)
    require(gencase_report.get("schema") == "ds02.f7.target-angle-gencase-result.v1", "Root117 GenCase report schema mismatch")
    require(gencase_report.get("status") == "completed" and gencase_report.get("returncode_failures") == 0, "Root117 aggregate GenCase report is not completed/zero failures")
    require(top_receipt.get("status") == "failed" and top_receipt.get("returncode") == 0, "Root117 top-level receipt failure was not preserved")
    require(top_receipt.get("error") == "GenCase actual particle count missing", "Root117 top-level failure changed")
    gencase_rows = {row.get("endpoint_id"): row for row in gencase_report.get("endpoints", [])}
    require(set(gencase_rows) == endpoints and len(gencase_rows) == 5, "Root117 GenCase endpoint set mismatch")
    owner_by_case = {row["case_id"]: row for row in owners}
    cases = []
    for endpoint in plan["endpoints"]:
        case_id = endpoint["endpoint_id"]
        grow = gencase_rows[case_id]
        mrow = motion_rows[case_id]
        require(grow.get("executed") is True and grow.get("returncode") == 0, f"Root117 per-case GenCase failed: {case_id}")
        generated_xml = pathlib.Path(grow["generated_xml"])
        generated_bi4 = pathlib.Path(grow["generated_bi4"])
        prepared_report = pathlib.Path(grow["prepared_input_report"])
        prepared_input = load(prepared_report)
        per_case_receipt = generated_xml.parent / "execution-receipt.json"
        per_case = load(per_case_receipt)
        require(per_case.get("schema") == "ds02.f7.target-angle-endpoint-execution-receipt.v1", f"per-case GenCase schema changed: {case_id}")
        require(per_case.get("status") == "completed" and per_case.get("returncode") == 0, f"per-case GenCase receipt not completed/0: {case_id}")
        require(per_case.get("endpoint_id") == case_id, f"per-case GenCase endpoint mismatch: {case_id}")
        require(per_case.get("total_particles") == EXPECTED["total"], f"per-case total changed: {case_id}")
        require(per_case.get("fluid_particles") == EXPECTED["fluid"], f"per-case fluid changed: {case_id}")
        require(per_case.get("solver_dimension_from_gencase") == 3, f"per-case dimension changed: {case_id}")
        xml = verify_xml(generated_xml, case_id)
        require(grow.get("xml_contract", {}).get("checks", {}).get("actual_3d") is True, f"Root117 actual_3d flag missing: {case_id}")
        require(prepared_input.get("schema") == "ds02.root.actual-native-source-preflight.v1", f"prepared-input schema changed: {case_id}")
        require(prepared_input.get("actual_total_particles") == EXPECTED["total"], f"prepared-input total changed: {case_id}")
        require(prepared_input.get("xml_sha256") == xml["xml_sha256"], f"prepared-input XML hash changed: {case_id}")
        bi4_sha = sha(generated_bi4)
        require(prepared_input.get("bi4_sha256") == bi4_sha, f"prepared-input BI4 hash changed: {case_id}")
        require(prepared_input.get("definition_sha256") == mrow.get("prepared_definition_sha256"), f"prepared-input Definition hash changed: {case_id}")
        require(grow.get("xml_contract", {}).get("xml_sha256") == xml["xml_sha256"], f"Root117 XML hash row changed: {case_id}")
        prepared_definition = pathlib.Path(mrow["prepared_definition"])
        motion_file = pathlib.Path(mrow["motion_file"])
        require(sha(prepared_definition) == mrow["prepared_definition_sha256"], f"prepared Definition hash changed: {case_id}")
        require(sha(motion_file) == mrow["motion_file_sha256"], f"prepared motion hash changed: {case_id}")
        owner = owner_by_case[case_id]
        cases.append({
            "case_id": case_id,
            "endpoint_id": case_id,
            "role": endpoint["role"],
            "amplitude_deg": endpoint["amplitude_deg"],
            "physical_condition_sha256": endpoint["physical_condition_sha256"],
            "canonical_owner": {
                "source_absolute_path": owner["path"],
                "source_sha256": owner["sha256"],
                "canonical_physical_binding_sha256": owner["canonical_physical_binding_sha256"],
            },
            "source_plan": {
                "source_absolute_path": str(plan_path),
                "source_sha256": plan_sha,
            },
            "gencase": {
                "per_case_receipt": str(per_case_receipt),
                "per_case_receipt_sha256": sha(per_case_receipt),
                "generated_xml": str(generated_xml),
                "generated_xml_sha256": xml["xml_sha256"],
                "generated_bi4": str(generated_bi4),
                "generated_bi4_sha256": bi4_sha,
                "prepared_input_report": str(prepared_report),
                "prepared_input_report_sha256": sha(prepared_report),
                "prepared_definition": str(prepared_definition),
                "prepared_definition_sha256": sha(prepared_definition),
                "native_counts": {"total": EXPECTED["total"], "fixed": EXPECTED["fixed"], "moving": EXPECTED["moving"], "fluid": EXPECTED["fluid"]},
                "native_3d": True,
                "dp_m": EXPECTED["dp_m"],
                "time_max_s": EXPECTED["time_max_s"],
                "time_out_s": EXPECTED["time_out_s"],
                "xml_blocks": xml["blocks"],
            },
            "motion": {
                "root116_report_endpoint": mrow,
                "motion_file": str(motion_file),
                "motion_file_sha256": mrow["motion_file_sha256"],
                "prepared_definition": str(prepared_definition),
                "prepared_definition_sha256": mrow["prepared_definition_sha256"],
                "prepared_cwd": str(motion_file.parent),
                "motion_rows": EXPECTED["motion_rows"],
                "native_reader": mrow["native_reader"],
                "native_sampled_regular": mrow["native_sampled_regular"],
            },
        })
    binding = {
        "schema": "ds02.f7.first8.actual-gencase-native-source-binding.v1",
        "family_id": "F7",
        "scope_id": PACKAGE_SCOPE,
        "source_scope": "root_followup_065_stage1_first8_target_angles_v1",
        "source_plan": {"source_absolute_path": str(plan_path), "source_sha256": plan_sha},
        "root116_motion_report": {"source_absolute_path": str(motion_report_path), "source_sha256": sha(motion_report_path)},
        "root116_motion_receipt": {"source_absolute_path": str(motion_receipt_path), "source_sha256": sha(motion_receipt_path), "status": motion_receipt["status"], "returncode": motion_receipt["returncode"]},
        "root117_gencase_report": {"source_absolute_path": str(gencase_report_path), "source_sha256": sha(gencase_report_path), "status": gencase_report["status"], "returncode_failures": gencase_report["returncode_failures"]},
        "root117_top_level_receipt_preserved_failure": {"source_absolute_path": str(top_receipt_path), "source_sha256": sha(top_receipt_path), "status": top_receipt["status"], "returncode": top_receipt["returncode"], "error": top_receipt["error"], "used_as_success_evidence": False},
        "source_qa_worker": {"source_absolute_path": str(SOURCE_QA_WORKER), "source_sha256": sha(SOURCE_QA_WORKER), "derived_worker_relative": "workers/run_f7_first8_actual_native_initial_qa.py"},
        "actual_evidence_contract": {
            "per_case_gencase_receipt_status": "completed",
            "per_case_gencase_returncode": 0,
            "aggregate_particles": 70179,
            "aggregate_fixed": 27495,
            "aggregate_moving": 1984,
            "aggregate_fluid": 40700,
            "positive_3d": True,
            "dp_m": 0.02,
            "time_max_s": 12.0,
            "time_out_s": 0.02,
            "motion_rows": 12001,
            "native_fluid_mass_kg": EXPECTED["native_fluid_mass_kg"],
            "continuum_envelope_mass_kg": EXPECTED["continuum_envelope_mass_kg"],
            "mass_rescale": False,
            "arrays_decoded": False,
        },
        "cases": cases,
        "launch_allowed": False,
        "execution_allowed": False,
        "independent_case_count_increment": 0,
        "q_n": "not_granted",
        "production_approval": "none",
        "precision_status": "not_accepted",
        "status": "actual_gencase_bound_initial_qa_pending",
        "claim_boundary": "Actual per-case GenCase/XML/BI4 hash and Root116 motion metadata only; native typed QA, solver dynamics, full-window qualification, visual acceptance, Q-N, and production remain pending.",
    }
    binding_path = metadata_dir / "actual-gencase-native-source-binding.json"
    write_json(binding_path, binding)
    binding_sha = sha(binding_path)

    request_paths = []
    for case in cases:
        cid = case["case_id"]
        owner_path = pathlib.Path(case["canonical_owner"]["source_absolute_path"])
        g = case["gencase"]
        m = case["motion"]
        qa_request = {
            "schema": "ds02.runner-request.v2",
            "family_id": "F7",
            "case_id": cid,
            "attempt_id": f"root-stage1-f7-{cid.lower()}-native-initial-qa-066-pending",
            "kind": "cpu",
            "cpu_task_kind": "audit",
            "model_profile": "gpt-5.6-luna/max",
            "cpu_threads": 2,
            "max_wall_seconds": 3600,
            "estimated_storage_bytes": 268435456,
            "cwd": "/home/jade/.codex/worktrees/ds-data-02-f7/DualSPHysics/lagrangian-fluid-lab",
            "worktree_root": "/home/jade/.codex/worktrees/ds-data-02-f7/DualSPHysics",
            "command": [str(PYTHON), str(output_root / "workers/run_f7_first8_actual_native_initial_qa.py"), "--binding", str(binding_path), "--case-id", cid, "--output-dir", "{attempt_root}/initial-qa", "--source-worker", str(SOURCE_QA_WORKER)],
            "input_files": [str(PYTHON), str(RUNTIME), str(STRICT), str(output_root / "workers/run_f7_first8_actual_native_initial_qa.py"), str(SOURCE_QA_WORKER), str(binding_path), str(plan_path), str(owner_path), str(PARTVTK), g["per_case_receipt"], g["generated_xml"], g["generated_bi4"], g["prepared_input_report"], m["prepared_definition"], m["motion_file"], str(motion_report_path), str(motion_receipt_path)],
            "future_outputs": {"native_initial_qa_report": "{attempt_root}/initial-qa/native-initial-qa.json", "native_initial_qa_report_sha256": None},
            "launch_allowed": False,
            "execution_allowed": False,
            "status": "source_only_disabled_actual_gencase_ready",
            "actual_gencase": {"receipt": g["per_case_receipt"], "receipt_sha256": g["per_case_receipt_sha256"], "xml": g["generated_xml"], "xml_sha256": g["generated_xml_sha256"], "bi4": g["generated_bi4"], "bi4_sha256": g["generated_bi4_sha256"], "native_3d": True, "total_particles": EXPECTED["total"]},
            "canonical_owner_binding_sha256": case["canonical_owner"]["canonical_physical_binding_sha256"],
            "source_plan_sha256": plan_sha,
            "independent_case_count_increment": 0,
            "q_n": "not_granted",
            "production_approval": "none",
            "arrays_read_by_source_builder": False,
            "disabled_reason": "Root117 per-case GenCase is actual completed/0, but native typed QA must run as a separately reviewed Root request; top-level Root117 wrapper failure is preserved and not used as success evidence.",
        }
        qa_request["input_sha256"] = {p: sha(pathlib.Path(p)) for p in qa_request["input_files"]}
        qa_path = request_dir / f"{cid}.native-initial-qa-request.json"
        write_json(qa_path, qa_request)
        request_paths.append(qa_path)

        qa_template = "{qa_attempt_root}/initial-qa/native-initial-qa.json"
        full_request = {
            "schema": "ds02.runner-request.v2",
            "family_id": "F7",
            "case_id": cid,
            "attempt_id": f"root-stage1-f7-{cid.lower()}-full601-native-066-pending",
            "kind": "qualification",
            "model_profile": "gpt-5.6-luna/max",
            "cpu_threads": 4,
            "max_wall_seconds": 7200,
            "estimated_peak_gpu_mib": 4096,
            "estimated_storage_bytes": 8589934592,
            "cwd": m["prepared_cwd"],
            "worktree_root": "/home/jade/.codex/worktrees/ds-data-02-f7/DualSPHysics",
            "command": [str(SOLVER), g["generated_xml"][:-4], "{attempt_root}/solver_output", "-tmax:12", "-tout:0.02"],
            "gencase_prefix": g["generated_xml"][:-4],
            "gencase_receipt": g["per_case_receipt"],
            "gencase_receipt_sha256": g["per_case_receipt_sha256"],
            "motion_source": {"prepared_motion": m["motion_file"], "prepared_motion_sha256": m["motion_file_sha256"], "solver_cwd": m["prepared_cwd"], "reason": "Root116 prepared cwd contains motion_obstacle_quintic.dat; GenCase output directory does not."},
            "initial_qa_required": {"status": "pending_actual_pass", "report": qa_template, "report_sha256": None, "receipt": "{qa_attempt_root}/execution-receipt.json", "receipt_sha256": None, "required_case_id": cid, "required_all_cases_passed": True},
            "input_files": [str(SOLVER), str(RUNTIME), str(STRICT), str(output_root / "metadata/actual-gencase-native-source-binding.json"), str(plan_path), str(owner_path), g["per_case_receipt"], g["generated_xml"], g["generated_bi4"], g["prepared_input_report"], m["prepared_definition"], m["motion_file"], str(motion_report_path), str(motion_receipt_path)],
            "launch_allowed": False,
            "execution_allowed": False,
            "launch": False,
            "status": "source_only_disabled_pending_actual_native_qa",
            "qualification_scope": {"physical_window_s": [0.0, 12.0], "native_frame_count": 601, "native_save_interval_s": 0.02, "motion_rows": 12001, "dp_m": 0.02, "native_motion_reader": "piecewise_linear_absolute_angle_increment", "native_sampled_regular": "not C2", "visual_acceptance": "pending Root full-window review", "q_n": "not_granted", "production_approval": "none"},
            "mother_recipe_exact": {"total_particles": EXPECTED["total"], "fixed_particles": EXPECTED["fixed"], "moving_particles": EXPECTED["moving"], "fluid_particles": EXPECTED["fluid"], "dp_m": EXPECTED["dp_m"], "physical_window_s": [0.0, 12.0], "native_frame_count": EXPECTED["frames"], "native_save_interval_s": EXPECTED["time_out_s"], "motion_rows": EXPECTED["motion_rows"], "native_fluid_mass_kg": EXPECTED["native_fluid_mass_kg"], "continuum_envelope_mass_kg": EXPECTED["continuum_envelope_mass_kg"], "mass_policy": "native unscaled; continuum comparison separate; no rescale"},
            "canonical_owner_binding_sha256": case["canonical_owner"]["canonical_physical_binding_sha256"],
            "source_plan_sha256": plan_sha,
            "physical_condition_sha256": case["physical_condition_sha256"],
            "independent_case_count_increment": 0,
            "precision_status": "not_accepted",
            "q_n_status": "not_assessed",
            "production_approval": "none",
            "disabled_reason": "No solver launch until Root has a completed per-case native initial-QA report and receipt; future QA hashes remain null by design.",
        }
        full_request["input_sha256"] = {p: sha(pathlib.Path(p)) for p in full_request["input_files"]}
        full_path = request_dir / f"{cid}.full601-native-qualification-request.json"
        write_json(full_path, full_request)
        request_paths.append(full_path)

    manifest = {
        "schema": "ds02.f7.stage1.actual-gencase-qa-native-source-handoff.v1",
        "handoff_id": PACKAGE_SCOPE,
        "family_id": "F7",
        "source_only": True,
        "launch_allowed": False,
        "execution_allowed": False,
        "no_jobs_started": True,
        "no_arrays_decoded": True,
        "no_solver_started": True,
        "no_shared_registry_write": True,
        "independent_physical_case_count_increment": 0,
        "root117_top_level_failure_preserved": True,
        "root117_per_case_completed_count": 5,
        "actual_positive_3d_total_particles": 70179,
        "actual_xml_bi4_motion_hashes_verified": True,
        "csv_contract": {"summary_line_count": 3, "header_line_zero_based": 3, "trailing_empty_rows_ignored": True},
        "source_plan": {"source_absolute_path": str(plan_path), "source_sha256": plan_sha},
        "binding": {"source_absolute_path": str(binding_path), "source_sha256": binding_sha},
        "request_files": [{"source_absolute_path": str(p), "source_sha256": sha(p)} for p in request_paths],
        "next_step": "Root reviews actual binding, enables five per-case CPU QA requests, then records actual QA report/receipt hashes before considering any full601 request.",
    }
    write_json(output_root / "manifest.json", manifest)
    print(json.dumps({"status": "completed", "package": str(output_root), "cases": len(cases), "qa_requests": 5, "full_native_requests": 5, "root117_per_case_completed": 5, "top_level_failure_preserved": True, "arrays_decoded": False}, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--motion-report", required=True)
    parser.add_argument("--motion-receipt", required=True)
    parser.add_argument("--gencase-report", required=True)
    parser.add_argument("--top-receipt", required=True)
    parser.add_argument("--owner-dir", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()
    bind_actual(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
