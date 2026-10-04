#!/usr/bin/env python3
"""Build the F1 prospective initial-horizontal-velocity source package.

The builder audits only ordinary JSON/XML/text provenance from the already
completed first-eight cases.  It never opens a BI4 particle array, calls
GenCase, calls PartVTK, starts DualSPHysics, or modifies a shared registry.
Every generated case is source-only and disabled until Root performs genuine
GenCase, initial-state QA, and full native visual review.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping


HERE = Path(__file__).resolve().parent
INTEGRATION_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
INTEGRATION_LAB = INTEGRATION_ROOT / "lagrangian-fluid-lab"
CAMPAIGN = INTEGRATION_LAB / "campaigns/ds-data-02"
ROOT_HANDOFF = CAMPAIGN / "handoff_20261003"
FAMILY_HANDOFF = CAMPAIGN / "families/F1/handoff_20261003"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1")
OFFICIAL_LAB = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab")
OFFICIAL = OFFICIAL_LAB / "vendor/official/DualSPHysics_v5.4"

ROOT094 = ROOT_HANDOFF / "root_stage1_f1_two_interior_actual_visual_production_094"
SIX_QA = ROOT_HANDOFF / "root_stage1_f1_six_new_head_actual_initial_qa_031/binding.json"
FALLBACK_QA = FAMILY_HANDOFF / "root_actual_bounded_fallback_initial_029/binding.json"
GENCASE = ROOT_HANDOFF / "root_native_source_preflight_tools_001/gencase.py"
RUNTIME = INTEGRATION_LAB / "scripts/ds_data02_runtime_v2.py"
STRICT = INTEGRATION_LAB / "scripts/ds_data02_strict_dispatch_v1.py"
GOAL = CAMPAIGN / "GOAL_STAGE1_VISUAL_GPT56LUNA_20261004_ZH.md"
PARTVTK = OFFICIAL / "bin/linux/PartVTK_linux64"
GENCASE_BIN = OFFICIAL / "bin/linux/GenCase_linux64"
SOLVER_BIN = OFFICIAL / "bin/linux/DualSPHysics5.4_linux64"

TEMPLATE = OFFICIAL / "doc/xml_format/GenCase_CaseTemplate.xml"
INITIALIZE_DOC = OFFICIAL / "doc/xml_format/_FmtXML_Initialize.xml"
EXAMPLE = OFFICIAL / "examples/inletoutlet/01_FlowCylinder/CaseFlowCylinder_Re020_Def.xml"
INITIALIZE_CPP = OFFICIAL_LAB / "vendor/src/source/JDsInitialize.cpp"
INITIALIZE_H = OFFICIAL_LAB / "vendor/src/source/JDsInitialize.h"

SPECS = [
    {"family": "ecc", "base": "F1_STAGE1_ECC_H110_DP010", "head": "110", "dp": 0.01, "tmax": 1.6, "frames": 161, "fallback": False, "recipe": "F1_STAGE1_ECC_H110_DP010"},
    {"family": "ecc", "base": "F1_STAGE1_ECC_H130_DP010", "head": "130", "dp": 0.01, "tmax": 1.6, "frames": 161, "fallback": False, "recipe": "F1_STAGE1_ECC_H110_DP010"},
    {"family": "ecc", "base": "F1_FALLBACK_ECC_COARSE", "head": "150", "dp": 0.01, "tmax": 1.6, "frames": 161, "fallback": True, "recipe": "F1_STAGE1_ECC_H110_DP010"},
    {"family": "ecc", "base": "F1_STAGE1_ECC_H190_DP010", "head": "190", "dp": 0.01, "tmax": 1.6, "frames": 161, "fallback": False, "recipe": "F1_STAGE1_ECC_H110_DP010"},
    {"family": "dual", "base": "F1_STAGE1_DUAL_H220_DP020", "head": "220", "dp": 0.02, "tmax": 4.0, "frames": 401, "fallback": False, "recipe": "F1_STAGE1_DUAL_H220_DP020"},
    {"family": "dual", "base": "F1_STAGE1_DUAL_H260_DP020", "head": "260", "dp": 0.02, "tmax": 4.0, "frames": 401, "fallback": False, "recipe": "F1_STAGE1_DUAL_H220_DP020"},
    {"family": "dual", "base": "F1_FALLBACK_DUAL_COARSE", "head": "300", "dp": 0.02, "tmax": 4.0, "frames": 401, "fallback": True, "recipe": "F1_STAGE1_DUAL_H220_DP020"},
    {"family": "dual", "base": "F1_STAGE1_DUAL_H340_DP020", "head": "340", "dp": 0.02, "tmax": 4.0, "frames": 401, "fallback": False, "recipe": "F1_STAGE1_DUAL_H220_DP020"},
]
VELOCITIES = (0.1, 0.2)


class BuildError(ValueError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def load(path: Path) -> Any:
    if not path.is_file():
        raise BuildError(f"missing provenance file: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BuildError(f"invalid JSON provenance: {path}") from exc


def save(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def file_binding(path: Path) -> dict[str, str]:
    path = path.resolve()
    if not path.is_file():
        raise BuildError(f"missing file for hash closure: {path}")
    return {"path": str(path), "sha256": sha256(path)}


def assert_equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise BuildError(f"{label}: {actual!r} != {expected!r}")


def row_for(rows: list[Any], case_id: str) -> Mapping[str, Any]:
    matches = [row for row in rows if isinstance(row, Mapping) and row.get("case_id") == case_id]
    if len(matches) != 1:
        raise BuildError(f"Root094 must contain one row for {case_id}")
    return matches[0]


def qa_row(binding: Mapping[str, Any], case_id: str) -> Mapping[str, Any]:
    return row_for(list(binding.get("cases", [])), case_id)


def source_definition(spec: Mapping[str, Any]) -> Path:
    base = str(spec["base"])
    if spec["fallback"]:
        return FAMILY_HANDOFF / "root_actual_bounded_fallback_three_dp_gencase_027/selected_definitions" / f"{base}_Def.xml"
    return ROOT_HANDOFF / "root_stage1_f1_six_new_head_physics_gencase_027" / base / f"{base}_Def.xml"


def actual_gencase_dir(spec: Mapping[str, Any]) -> Path:
    base = str(spec["base"])
    family = str(spec["family"])
    if spec["fallback"]:
        slug = f"root-fallback-{family}-coarse-actual-gencase-027"
    else:
        slug = f"root-stage1-{family}-h{spec['head'].lower()}-actual-gencase-027"
    return DATA_ROOT / base / slug


def recipe_receipt(spec: Mapping[str, Any]) -> Path:
    recipe = str(spec["recipe"])
    family = "ecc" if recipe.startswith("F1_STAGE1_ECC") else "dual"
    head = "110" if family == "ecc" else "220"
    slug = f"root-stage1-{family}-h{head}-physical-endpoint-full-native-032"
    return DATA_ROOT / recipe / slug / "execution-receipt.json"


def recipe_request(spec: Mapping[str, Any]) -> Path:
    recipe = str(spec["recipe"])
    return ROOT_HANDOFF / "root_stage1_f1_four_physical_head_endpoints_native_032" / recipe / "request.json"


def source_owner(row: Mapping[str, Any]) -> Path:
    path = Path(str(row["source_owner"]["path"]))
    return path


def read_baseline(spec: Mapping[str, Any], manifests: Mapping[str, Any]) -> dict[str, Any]:
    base = str(spec["base"])
    row = row_for(list(manifests[spec["family"]].get("cases", [])), base)
    physical = copy.deepcopy(row["physical_binding"])
    assert_equal(canonical_hash(physical), row["physical_condition_sha256"], f"{base} physical hash")
    gdir = actual_gencase_dir(spec)
    receipt_path = gdir / "execution-receipt.json"
    prepared_path = gdir / "prepared/prepared-input-report.json"
    receipt = load(receipt_path)
    prepared = load(prepared_path)
    assert_equal(receipt.get("status"), "completed", f"{base} GenCase status")
    assert_equal(receipt.get("returncode"), 0, f"{base} GenCase returncode")
    assert_equal(receipt.get("solver_dimension_from_gencase"), 3, f"{base} GenCase dimension")
    total = int(receipt["total_particles"])
    fluid = int(receipt["fluid_particles"])
    assert_equal(total, int(prepared["actual_total_particles"]), f"{base} total count")
    generated_xml = gdir / "prepared" / f"{base}.xml"
    definition = source_definition(spec)
    assert_equal(sha256(definition), prepared["definition_sha256"], f"{base} definition hash")
    assert_equal(sha256(generated_xml), prepared["xml_sha256"], f"{base} generated XML hash")
    definition_text = definition.read_text(encoding="utf-8")
    if "<initials" in definition_text:
        raise BuildError(f"baseline definition already has initials: {definition}")
    constants = prepared.get("actual_generated_constants", {})
    assert_equal(str(constants.get("data2d", {}).get("value")).lower(), "false", f"{base} data2d")
    assert_equal(str(constants.get("dp", {}).get("value")), str(spec["dp"]), f"{base} dp")
    qa_binding_path = SIX_QA if not spec["fallback"] else FALLBACK_QA
    qa_binding = load(qa_binding_path)
    qa = qa_row(qa_binding, base)
    assert_equal(int(qa["expected_total"]), total, f"{base} QA total")
    assert_equal(int(qa["expected_fluid"]), fluid, f"{base} QA fluid")
    recipe_path = recipe_receipt(spec)
    recipe = load(recipe_path)
    command = list(recipe.get("command", []))
    if len(command) < 6 or "-gpu:0" not in command or f"-tmax:{spec['tmax']:g}" not in command or "-tout:0.01" not in command:
        raise BuildError(f"{base} native032 receipt does not have the expected exact command: {command}")
    if any("mdbc" in str(item).lower() or "noslip" in str(item).lower() for item in command):
        raise BuildError(f"{base} native032 receipt unexpectedly has an mdbc/no-slip option")
    source_req = load(recipe_request(spec))
    if any("mdbc" in str(item).lower() or "noslip" in str(item).lower() for item in source_req.get("command", [])):
        raise BuildError(f"{base} source request has an mdbc/no-slip option")
    return {
        "spec": dict(spec),
        "case_id": base,
        "row": row,
        "physical_binding": physical,
        "physical_case_id": row["physical_case_id"],
        "physical_condition_sha256": row["physical_condition_sha256"],
        "source_owner": file_binding(source_owner(row)),
        "definition": file_binding(definition),
        "gencase_receipt": file_binding(receipt_path),
        "prepared_report": file_binding(prepared_path),
        "generated_xml": file_binding(generated_xml),
        "total": total,
        "fluid": fluid,
        "boundary": total - fluid,
        "qa_binding": file_binding(qa_binding_path),
        "qa": dict(qa),
        "recipe_receipt": file_binding(recipe_path),
        "recipe_request": file_binding(recipe_request(spec)),
        "recipe_command": command,
        "recipe_cwd": str(source_req.get("cwd", INTEGRATION_LAB)),
        "generated_xml_particle_counts": prepared.get("generated_xml_particle_counts", {}),
        "generated_constants": {
            key: constants[key]
            for key in ("data2d", "dp", "gravity", "massfluid", "massbound", "rhop0")
            if key in constants
        },
    }


def add_initial_velocity(definition: Path, output: Path, velocity: float) -> None:
    text = definition.read_text(encoding="utf-8")
    if text.count("</casedef>") != 1 or "<initials" in text:
        raise BuildError(f"cannot safely add initials to {definition}")
    vx = f"{velocity:.1f}"
    initials = f'  <initials>\n    <velocity mkfluid="0" x="{vx}" y="0" z="0" />\n  </initials>\n'
    text = text.replace("</casedef>", initials + "</casedef>", 1)
    ET.fromstring(text)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")


def slug(case_id: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", case_id.lower()).strip("-")


def hash_inputs(paths: list[Path]) -> tuple[list[str], dict[str, str]]:
    unique = []
    seen = set()
    for path in paths:
        path = path.resolve()
        if str(path) not in seen:
            if not path.is_file():
                raise BuildError(f"input file missing: {path}")
            seen.add(str(path))
            unique.append(path)
    return [str(path) for path in unique], {str(path): sha256(path) for path in unique}


def disabled_fields() -> dict[str, Any]:
    return {
        "launch_allowed": False,
        "execution_allowed": False,
        "source_only": True,
        "production_approval": "none",
        "launch_owner": "root",
        "independent_case_count_increment": 0,
    }


def deferred(path: Path, reason: str) -> dict[str, Any]:
    return {"path": str(path), "sha256": None, "status": "not_generated", "reason": reason}


def make_case(baseline: Mapping[str, Any], velocity: float) -> dict[str, Any]:
    spec = baseline["spec"]
    base = str(baseline["case_id"])
    vx_tag = f"VX{int(round(velocity * 100)):03d}"
    case_id = f"{base}_{vx_tag}"
    case_slug = slug(case_id)
    data_case = DATA_ROOT / case_id
    gencase_attempt = data_case / f"root-stage1-f1-{case_slug}-gencase-064"
    native_attempt = data_case / f"root-stage1-f1-{case_slug}-native-visual-064"
    definition = HERE / "definitions" / f"{case_id}_Def.xml"
    owner_path = HERE / "owners" / f"{case_id}.owner.json"
    gencase_binding_path = HERE / "gencase-bindings" / f"{case_id}.json"
    qa_binding_path = HERE / "qa-bindings" / f"{case_id}.json"
    gencase_request_path = HERE / "requests" / f"{case_id}.gencase.request.json"
    qa_request_path = HERE / "requests" / f"{case_id}.initial-qa.request.json"
    native_request_path = HERE / "requests" / f"{case_id}.native.request.json"
    add_initial_velocity(Path(baseline["definition"]["path"]), definition, velocity)
    physical = copy.deepcopy(baseline["physical_binding"])
    physical["physical_case_id"] = f"{baseline['physical_case_id']}_INITIAL_VX{int(round(velocity * 100)):03d}_MS_V1"
    physical["control_family_id"] = "F1_CONTROL_GRAVITY_RELEASE_INITIAL_VX_AXIS_V1"
    physical["initial_state"]["velocities_m_per_s"]["fluid"] = [velocity, 0.0, 0.0]
    physical["initial_state"]["velocity_control"] = {
        "axis": "x",
        "fluid_mk": 0,
        "fluid_native_type": 3,
        "velocity_m_per_s": [velocity, 0.0, 0.0],
        "profile": "uniform_direct_initials_velocity",
    }
    physical_hash = canonical_hash(physical)
    if physical_hash == baseline["physical_condition_sha256"]:
        raise BuildError(f"{case_id} physical hash did not change")
    parent_prefix = DATA_ROOT / base / str(baseline["row"].get("actual_gencase_attempt", ""))
    future_prefix = gencase_attempt / "prepared" / case_id
    owner = {
        "schema": "ds02.f1.initial-vx-axis-owner.v1",
        "family_id": "F1",
        "case_id": case_id,
        "physical_case_id": physical["physical_case_id"],
        "physical_condition_sha256": physical_hash,
        "physical_binding": physical,
        "parent_case_id": base,
        "parent_physical_case_id": baseline["physical_case_id"],
        "parent_physical_condition_sha256": baseline["physical_condition_sha256"],
        "parent_source_owner": baseline["source_owner"],
        "axis": {
            "name": "uniform_initial_fluid_vx",
            "velocity_m_per_s": [velocity, 0.0, 0.0],
            "fluid_mk": 0,
            "fluid_native_type": 3,
            "source_xml_expression": f'<velocity mkfluid="0" x="{velocity:.1f}" y="0" z="0" />',
        },
        "geometry_and_solver": "inherited exactly from the parent source definition and native032 recipe; only the initials velocity element changes",
        "parent_actual_voxelization_reference": {
            "total_particles": baseline["total"],
            "fluid_particles": baseline["fluid"],
            "boundary_particles": baseline["boundary"],
            "dimension": 3,
            "status": "parent_metadata_reference_only",
        },
        "new_case_status": "prospective_source_only_not_generated",
        "visual_review_status": "pending_root_actual_initial_qa_and_full_native_visual_review",
        **disabled_fields(),
    }
    save(owner_path, owner)
    gencase_binding = {
        "schema": "ds02.f1.initial-vx-axis-gencase-binding.v1",
        "family_id": "F1",
        "case_id": case_id,
        "definition": str(definition.resolve()),
        "definition_sha256": sha256(definition),
        "gencase": str(GENCASE_BIN),
        "dp_m": spec["dp"],
        "expected_fluid": baseline["fluid"],
        "expected_total_reference": baseline["total"],
        "expected_geometry_reference": baseline["qa"].get("expected_fluid_envelope_m"),
        "threads": 2,
        "initial_velocity_m_per_s": [velocity, 0.0, 0.0],
        "fluid_mk": 0,
        "expected_native_type": 3,
        "geometry_count_reference_only": True,
        "new_output_status": "not_generated",
        **disabled_fields(),
    }
    save(gencase_binding_path, gencase_binding)
    qa_binding = {
        "schema": "ds02.f1.initial-vx-axis-qa-binding.v1",
        "family_id": "F1",
        "partvtk": str(PARTVTK),
        "worker": str((HERE / "qa_initial_vx.py").resolve()),
        "cases": [
            {
                "case_id": case_id,
                "parent_case_id": base,
                "prefix": str(future_prefix),
                "receipt": str(gencase_attempt / "execution-receipt.json"),
                "expected_total": baseline["total"],
                "expected_fluid": baseline["fluid"],
                "expected_types": [0, 3],
                "fluid_type": 3,
                "expected_fluid_envelope_m": baseline["qa"].get("expected_fluid_envelope_m"),
                "expected_velocity_m_per_s": [velocity, 0.0, 0.0],
                "parent_voxelization_reference": True,
                "prospective_output_not_generated": True,
            }
        ],
        **disabled_fields(),
    }
    save(qa_binding_path, qa_binding)
    source_recipe_command = list(baseline["recipe_command"])
    if len(source_recipe_command) < 6 or "-gpu:0" not in source_recipe_command:
        raise BuildError(f"unexpected native032 command for {case_id}: {source_recipe_command}")
    target_command = list(source_recipe_command)
    if len(target_command) != 6 or target_command[0] != str(SOLVER_BIN) or target_command[1] != "-gpu:0":
        raise BuildError(f"cannot identify native032 executable/options: {source_recipe_command}")
    # The native032 receipt shape is [solver, -gpu:0, prefix, output, -tmax, -tout].
    # Preserve every option and replace only the input prefix and output path.
    target_command[2] = str(future_prefix)
    target_command[3] = "{attempt_root}/solver_output"
    if any("mdbc" in str(item).lower() or "noslip" in str(item).lower() for item in target_command):
        raise BuildError(f"generated command contains a forbidden mdbc/no-slip option: {target_command}")
    gencase_input_paths, gencase_input_hashes = hash_inputs([
        INTEGRATION_LAB / ".venv/bin/python",
        GENCASE,
        gencase_binding_path,
        definition,
        GENCASE_BIN,
        RUNTIME,
        STRICT,
        GOAL,
        HERE / "build_f1_initial_vx_axis_source.py",
    ])
    gencase_request = {
        "schema": "ds02.runner-request.v2",
        "family_id": "F1",
        "case_id": case_id,
        "attempt_id": gencase_attempt.name,
        "kind": "cpu",
        "cpu_task_kind": "gencase",
        "cpu_threads": 2,
        "max_wall_seconds": 600,
        "estimated_storage_bytes": 1073741824,
        "cwd": str(INTEGRATION_LAB),
        "worktree_root": str(INTEGRATION_ROOT),
        "command": [str(INTEGRATION_LAB / ".venv/bin/python"), str(GENCASE), "--binding", str(gencase_binding_path.resolve()), "--output-dir", "{attempt_root}/prepared"],
        "input_files": gencase_input_paths,
        "input_sha256": gencase_input_hashes,
        "future_outputs": {
            "attempt_root": str(gencase_attempt),
            "prepared_prefix": str(future_prefix),
            "execution_receipt": str(gencase_attempt / "execution-receipt.json"),
            "sha256": None,
            "status": "not_generated",
        },
        **disabled_fields(),
    }
    save(gencase_request_path, gencase_request)
    qa_input_paths, qa_input_hashes = hash_inputs([
        INTEGRATION_LAB / ".venv/bin/python",
        HERE / "qa_initial_vx.py",
        qa_binding_path,
        PARTVTK,
        RUNTIME,
        STRICT,
        GOAL,
    ])
    qa_request = {
        "schema": "ds02.runner-request.v2",
        "family_id": "F1",
        "case_id": case_id,
        "attempt_id": f"{case_slug}-initial-qa-064",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 2,
        "max_wall_seconds": 1800,
        "estimated_storage_bytes": 2147483648,
        "cwd": str(INTEGRATION_LAB),
        "worktree_root": str(INTEGRATION_ROOT),
        "command": [str(INTEGRATION_LAB / ".venv/bin/python"), str((HERE / "qa_initial_vx.py").resolve()), "--binding", str(qa_binding_path.resolve()), "--output-dir", "{attempt_root}"],
        "input_files": qa_input_paths,
        "input_sha256": qa_input_hashes,
        "future_input_files": [str(future_prefix) + ".xml", str(future_prefix) + ".bi4", str(gencase_attempt / "execution-receipt.json")],
        "future_input_sha256": None,
        "cpu_audit_contract": {
            "fluid_type": 3,
            "fluid_mk": 0,
            "fluid_velocity_m_per_s": [velocity, 0.0, 0.0],
            "boundary_velocity_m_per_s": [0.0, 0.0, 0.0],
            "arrays_are_read_only": True,
        },
        **disabled_fields(),
    }
    save(qa_request_path, qa_request)
    native_input_paths, native_input_hashes = hash_inputs([
        SOLVER_BIN,
        RUNTIME,
        STRICT,
        GOAL,
        owner_path,
        gencase_binding_path,
        qa_binding_path,
        Path(baseline["recipe_receipt"]["path"]),
        Path(baseline["recipe_request"]["path"]),
        Path(baseline["source_owner"]["path"]),
        HERE / "qa_initial_vx.py",
        HERE / "build_f1_initial_vx_axis_source.py",
    ])
    native_request = {
        "schema": "ds02.runner-request.v2",
        "family_id": "F1",
        "case_id": case_id,
        "attempt_id": native_attempt.name,
        "kind": "production",
        "max_wall_seconds": 900 if spec["family"] == "ecc" else 1800,
        "cpu_threads": 4,
        "estimated_peak_gpu_mib": 8000,
        "estimated_storage_bytes": 4294967296,
        "cwd": str(INTEGRATION_LAB),
        "worktree_root": str(INTEGRATION_ROOT),
        "command": target_command,
        "solver_command": target_command,
        "solver_cwd": str(baseline["recipe_cwd"]),
        "gencase_prefix": str(future_prefix),
        "gencase_receipt": str(gencase_attempt / "execution-receipt.json"),
        "gencase_receipt_sha256": None,
        "expected_native_frames": spec["frames"],
        "event_window_s": [0.0, spec["tmax"]],
        "native_frame_interval_s": 0.01,
        "physical_case_id": physical["physical_case_id"],
        "physical_condition_sha256": physical_hash,
        "physical_binding": physical,
        "owner_metadata": file_binding(owner_path),
        "initial_qa_request": file_binding(qa_request_path),
        "source_native032_receipt": baseline["recipe_receipt"],
        "source_native032_request": baseline["recipe_request"],
        "exact_recipe_rule": "Reuse the native032 receipt command exactly; replace only the GenCase prefix and output path. No extra mdbc/noslip option.",
        "input_files": native_input_paths,
        "input_sha256": native_input_hashes,
        "future_input_files": [str(future_prefix) + ".xml", str(future_prefix) + ".bi4", str(gencase_attempt / "execution-receipt.json")],
        "future_input_sha256": None,
        "visual_review_pending": True,
        "q_n": "not_granted",
        "numerical_precision_status": "not_accepted",
        **disabled_fields(),
    }
    save(native_request_path, native_request)
    return {
        "case_id": case_id,
        "parent_case_id": base,
        "family": spec["family"],
        "head": spec["head"],
        "velocity_m_per_s": [velocity, 0.0, 0.0],
        "physical_case_id": physical["physical_case_id"],
        "physical_condition_sha256": physical_hash,
        "parent_physical_condition_sha256": baseline["physical_condition_sha256"],
        "definition": file_binding(definition),
        "owner": file_binding(owner_path),
        "gencase_binding": file_binding(gencase_binding_path),
        "qa_binding": file_binding(qa_binding_path),
        "gencase_request": file_binding(gencase_request_path),
        "initial_qa_request": file_binding(qa_request_path),
        "native_request": file_binding(native_request_path),
        "status": "prospective_source_only_disabled",
        "visual_review_status": "pending_root_actual_initial_qa_and_full_native_visual_review",
    }


def official_syntax_evidence() -> dict[str, Any]:
    files = [TEMPLATE, INITIALIZE_DOC, EXAMPLE, INITIALIZE_CPP, INITIALIZE_H]
    for path in files:
        if not path.is_file():
            raise BuildError(f"official syntax evidence is missing: {path}")
    texts = {path: path.read_text(encoding="utf-8", errors="replace") for path in files}
    checks = {
        "template_direct_velocity": '<velocity mkfluid="0"' in texts[TEMPLATE],
        "initialize_doc_fluidvelocity": "<fluidvelocity mkfluid=" in texts[INITIALIZE_DOC],
        "official_example_direct_velocity": '<initials>' in texts[EXAMPLE] and '<velocity mkfluid="0"' in texts[EXAMPLE],
        "source_reads_mkfluid": "MkFluid" in texts[INITIALIZE_CPP] and "mktype" in texts[INITIALIZE_CPP],
        "source_implements_fluid_velocity": "JDsInitializeOp_FluidVel" in texts[INITIALIZE_CPP] and "JDsInitializeOp_FluidVel" in texts[INITIALIZE_H],
    }
    if not all(checks.values()):
        raise BuildError(f"official initial velocity syntax checks failed: {checks}")
    excerpts = {}
    for path, text in texts.items():
        lines = []
        for number, line in enumerate(text.splitlines(), 1):
            if any(token in line for token in ("<velocity", "fluidvelocity", "JDsInitializeOp_FluidVel", "MkFluid", "mktype")):
                lines.append({"line": number, "text": line.strip()})
        excerpts[str(path)] = {"sha256": sha256(path), "matching_lines": lines[:20]}
    return {
        "schema": "ds02.f1.initial-vx-axis-official-syntax-evidence.v1",
        "checks": checks,
        "files": excerpts,
        "interpretation": "GenCase accepts direct initials/velocity with mkfluid=0; JDsInitialize applies it to the selected fluid Mk. The source package uses vx=0.1 or 0.2 m/s and vy=vz=0.",
    }


def first8_audit(baselines: list[Mapping[str, Any]]) -> dict[str, Any]:
    cases = []
    for item in baselines:
        cases.append(
            {
                "case_id": item["case_id"],
                "family": item["spec"]["family"],
                "head_label": f"{int(item['spec']['head']) / 1000:.2f} m",
                "physical_case_id": item["physical_case_id"],
                "physical_condition_sha256": item["physical_condition_sha256"],
                "actual_gencase": {
                    "status": "completed",
                    "returncode": 0,
                    "dimension": 3,
                    "total_particles": item["total"],
                    "fluid_particles": item["fluid"],
                    "boundary_particles": item["boundary"],
                    "type_count_metadata": {"type_0_boundary": item["boundary"], "type_3_fluid": item["fluid"]},
                },
                "generated_xml_particle_counts": item["generated_xml_particle_counts"],
                "generated_constants": item["generated_constants"],
                "source": {
                    "definition": item["definition"],
                    "generated_xml": item["generated_xml"],
                    "gencase_receipt": item["gencase_receipt"],
                    "prepared_report": item["prepared_report"],
                    "initial_qa_binding": item["qa_binding"],
                    "native032_receipt": item["recipe_receipt"],
                },
                "arrays_read": False,
                "arrays_hashed": False,
            }
        )
    by_family: dict[str, list[dict[str, Any]]] = {"ecc": [], "dual": []}
    for case in cases:
        by_family[case["family"]].append({"case_id": case["case_id"], "head_label": case["head_label"], "fluid": case["actual_gencase"]["fluid_particles"], "boundary": case["actual_gencase"]["boundary_particles"]})
    for family, rows in by_family.items():
        if len(rows) != 4 or len({row["physical_case_id"] for row in cases if row["family"] == family}) != 4:
            raise BuildError(f"{family} first-eight identities are not unique")
        if len({row["boundary"] for row in rows}) != 1:
            raise BuildError(f"{family} boundary voxelization inventory is not invariant")
    return {
        "schema": "ds02.f1.first8-native-voxelization-audit.v1",
        "scope": "ECC H110/H130/H150/H190 and DUAL H220/H260/H300/H340",
        "source_only_audit": True,
        "cases": cases,
        "family_comparison": by_family,
        "interpretation": "The first-eight native differences are recorded from completed GenCase metadata: fluid counts vary with the actual head reservoir geometry while the family boundary inventory is invariant. Physical IDs and condition hashes are distinct. No velocity-axis case is called actual by this package.",
        "arrays_read": False,
        "arrays_hashed": False,
    }


def main() -> None:
    manifests = {"ecc": load(ROOT094 / "ecc/case-manifest.json"), "dual": load(ROOT094 / "dual/case-manifest.json")}
    baselines = [read_baseline(spec, manifests) for spec in SPECS]
    syntax = official_syntax_evidence()
    first8 = first8_audit(baselines)
    save(HERE / "evidence/official-initial-velocity-syntax.json", syntax)
    save(HERE / "evidence/first8-native-voxelization-audit.json", first8)
    generated = [make_case(baseline, velocity) for baseline in baselines for velocity in VELOCITIES]
    readme = HERE / "README.md"
    readme.write_text(
        """# F1 fresh064 initial-vx source handoff

This package prepares 16 prospective F1 cases: each completed first-eight head
geometry is paired with a uniform Type 3/Mk 0 fluid initial velocity of `vx=0.1`
or `0.2 m/s`, with `vy=vz=0`. The only XML change is the official direct
`<initials><velocity mkfluid="0" ... /></initials>` element. Geometry, DP,
solver options, and full native windows are copied from the parent source and
native032 receipt.

The first-eight audit records actual completed GenCase metadata and canonical
physical IDs without opening BI4 arrays. All new definitions, owner bindings,
GenCase/initial-QA/native requests, and the vx-aware QA worker are source-only
and disabled. Root must run genuine GenCase, the read-only initial QA, the
exact native032 solver recipe, and full visual review before accepting this
axis. No case count, Q-N status, production approval, shared index, or ledger
entry is asserted here.
""",
        encoding="utf-8",
    )
    manifest = {
        "schema": "ds02.f1.initial-vx-axis-source-handoff.v1",
        "handoff_id": "root_followup_064_f1_initial_vx_axis_source_v1",
        "family_id": "F1",
        "package_status": "source_only_disabled_pending_root_actual_gencase_initial_qa_and_native_visual_review",
        "source_only": True,
        "launch_allowed": False,
        "execution_allowed": False,
        "solver_launched": False,
        "gencase_launched": False,
        "initial_qa_launched": False,
        "raw_arrays_read": False,
        "raw_arrays_hashed": False,
        "shared_index_or_ledger_modified": False,
        "axis": {
            "name": "uniform_initial_fluid_vx",
            "values_m_per_s": [0.1, 0.2],
            "fluid_mk": 0,
            "fluid_native_type": 3,
            "vy_vz_m_per_s": [0.0, 0.0],
            "syntax": "<initials><velocity mkfluid=0 x=... y=0 z=0 /></initials>",
            "official_syntax_evidence": file_binding(HERE / "evidence/official-initial-velocity-syntax.json"),
        },
        "first8_audit": file_binding(HERE / "evidence/first8-native-voxelization-audit.json"),
        "readme": file_binding(readme),
        "independent_case_count_increment": 0,
        "cases": generated,
        "acceptance_rule": "Root must run genuine GenCase, then the vx-aware PartVTK QA worker, then the exact native032 full-window solver and visual review. Until all pass, this axis remains prospective and no Stage1 case count is granted.",
        "builder": file_binding(HERE / "build_f1_initial_vx_axis_source.py"),
    }
    save(HERE / "manifest.json", manifest)
    print(json.dumps({"package": str(HERE), "cases": len(generated), "first8_audit": str(HERE / 'evidence/first8-native-voxelization-audit.json'), "status": manifest["package_status"]}, indent=2))


if __name__ == "__main__":
    main()
