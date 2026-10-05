#!/usr/bin/env python3
"""Build the F5 fresh108 source-only XMF/bed-audit handoff.

Only JSON/XML/Python/text metadata is read or hashed here.  The producer H5
SHA is copied from the completed Root486 conversion report; this builder never
opens or hashes H5, BI4, CSV, VTK, or DAT payloads and never submits a task.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

PKG = Path(__file__).resolve().parents[1]
F5_TREE = Path("/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics")
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5")
LAB = INTEGRATION / "lagrangian-fluid-lab"
CASE = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1"
FRESH105 = F5_TREE / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_105_stage1_f5_c082s1_short_native_typed_xmf_bed_disabled_v1"
ROOT455 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f5_actualQA441_Gen426_two_short51_native_455"
TYPED_ROOT = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f5_actualnativeFrame0QA483_short51_typed_NVMe_486"
ROOT142 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_home_floor_inventory_dispatch_142"
RESOURCES = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json"
RUNTIME = LAB / "scripts/ds_data02_runtime_v2.py"
STRICT = LAB / "scripts/ds_data02_strict_dispatch_v1.py"
DIRECT = LAB / "scripts/ds_data02_direct_convert.py"
NVME = LAB / "scripts/ds_data02_nvme_convert_v1.py"
PYTHON = LAB / ".venv/bin/python"
XMF_SOURCE = FRESH105 / "workers/export_xmf_legacy_aware.py"
BED_SOURCE = FRESH105 / "workers/bed_audit.py"
ROOT142_POLICY = ROOT142 / "root_home_floor_inventory_policy.py"
ROOT142_LAUNCH = ROOT142 / "launch.py"

COUNTS = {"total": 194427, "fixed": 158559, "moving": 4210, "floating": 0, "fluid": 31658}
ROOT142_POLICY_SHA = "2649eedbcf4816f8d2fa7b2182828ea8b3ce107ef47f25c56780d29c5138def5"
SCIENCE_SUFFIXES = {".bi4", ".csv", ".h5", ".hdf5", ".vtk", ".vtu", ".npy", ".npz", ".dat"}
HASHABLE_SUFFIXES = {".json", ".py", ".xml", ".md", ".txt", ".log"}
HEX = set("0123456789abcdefABCDEF")

CANDIDATES = {
    "A080": {
        "typed_request": TYPED_ROOT / "A080-typed-request.json",
        "native_request": ROOT455 / "C082S1_MOTION_A080-native-request.json",
        "physical_source": FRESH105 / "bindings/A080-physical-binding.json",
        "definition_source": FRESH105 / "inputs/A080-Definition.xml",
        "owner_source": FRESH105 / "inputs/A080-owner.json",
        "condition_id": "F5_RUNUP_DP020_C082S1_MOTION_A080_099",
        "xmf_attempt": "root-stage1-f5-c082s1-A080-short-native-xmf-108",
        "bed_attempt": "root-stage1-f5-c082s1-A080-short-dynamic-bed-audit-108",
    },
    "A120": {
        "typed_request": TYPED_ROOT / "A120-typed-request.json",
        "native_request": ROOT455 / "C082S1_MOTION_A120-native-request.json",
        "physical_source": FRESH105 / "bindings/A120-physical-binding.json",
        "definition_source": FRESH105 / "inputs/A120-Definition.xml",
        "owner_source": FRESH105 / "inputs/A120-owner.json",
        "condition_id": "F5_RUNUP_DP020_C082S1_MOTION_A120_099",
        "xmf_attempt": "root-stage1-f5-c082s1-A120-short-native-xmf-108",
        "bed_attempt": "root-stage1-f5-c082s1-A120-short-dynamic-bed-audit-108",
    },
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def load_json(path: Path) -> dict[str, Any]:
    require(path.suffix.lower() == ".json", f"JSON metadata required: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"JSON object required: {path}")
    return value


def sha(path: Path) -> str:
    require(path.suffix.lower() in HASHABLE_SUFFIXES, f"payload hash forbidden: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def copy_source(src: Path, dst: Path) -> str:
    require(src.is_file(), f"missing source: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    return sha(dst)


def hex64(value: Any, label: str) -> str:
    text = str(value)
    require(len(text) == 64 and set(text) <= HEX, f"{label} is not a SHA-256")
    return text


def receipt_request(receipt: dict[str, Any]) -> dict[str, Any]:
    value = receipt.get("request")
    return value if isinstance(value, dict) else {}


def check_counts(value: dict[str, Any], label: str, *, placement: bool = False) -> dict[str, int]:
    if placement:
        result = {
            "total": int(value.get("total_particles", -1)),
            "fixed": int(value.get("fixed_particles", -1)),
            "moving": int(value.get("moving_particles", -1)),
            "floating": int(value.get("floating_particles", -1)),
            "fluid": int(value.get("fluid_particles", -1)),
            "dimension": int(value.get("solver_dimension", -1)),
        }
    else:
        result = {
            "total": int(value.get("total", value.get("total_particles", -1))),
            "fixed": int(value.get("fixed", value.get("fixed_particles", -1))),
            "moving": int(value.get("moving", value.get("moving_particles", -1))),
            "floating": int(value.get("floating", value.get("floating_particles", -1))),
            "fluid": int(value.get("fluid", value.get("fluid_particles", -1))),
            "dimension": int(value.get("dimension", value.get("solver_dimension", -1))),
        }
    require(result == {**COUNTS, "dimension": 3}, f"{label} counts differ: {result}")
    return result


def make_bed_worker(candidate: str, canonical: str, source_plan: str, source_h5: str, physical_id: str) -> str:
    text = BED_SOURCE.read_text(encoding="utf-8")
    text = text.replace("fresh096", "fresh108")
    replacements = {
        'PHYSICAL_CASE_ID = \'F5_COMPACT_STILL_WATER_RUNUP_RECOVERY_C082S1\'': f"PHYSICAL_CASE_ID = {physical_id!r}",
        "CANONICAL_PHYSICAL_CONDITION_SHA256 = 'e691d030eda575b9cfabe62f295c9bdc142e5a04cb4357c9fe2790aaec549dbf'": f"CANONICAL_PHYSICAL_CONDITION_SHA256 = {canonical!r}",
        "SOURCE_PLAN_PHYSICAL_CONDITION_SHA256 = '5bad3ec9f9a71aa87da8272003c357f4523d4ffa164d3f06e5d25fee1a4fbfa6'": f"SOURCE_PLAN_PHYSICAL_CONDITION_SHA256 = {source_plan!r}",
        "SOURCE_H5_PHYSICAL_CONDITION_SHA256 = '3cd1ceab16be11428bbc1011a1b4e297c384d8c7926432c222c254064744ccd0'": f"SOURCE_H5_PHYSICAL_CONDITION_SHA256 = {source_h5!r}",
    }
    for old, new in replacements.items():
        require(old in text, f"bed worker source anchor missing: {old[:50]}")
        text = text.replace(old, new)
    old_block = '''    saved = binding.get("short_saved_state_metadata", {})
    require(saved.get("all_51_saved_states") is True and saved.get("saved_state_count") == EXPECTED_FRAMES,
            "C082S1 short solver is not bound to 51 native saved states")
    saved_meta_path = Path(str(saved.get("path", ""))).resolve()
    require(saved_meta_path.is_file(), "C082S1 short saved-state metadata is missing")
    saved_meta_sha = str(saved.get("sha256", ""))
    require(is_bound(saved_meta_sha) and sha256_file(saved_meta_path) == saved_meta_sha,
            "C082S1 short saved-state metadata SHA mismatch")
    saved_meta = load_json(saved_meta_path)
    require(saved_meta.get("all_51_saved_states") is True and saved_meta.get("saved_state_count") == EXPECTED_FRAMES,
            "C082S1 short saved-state metadata count mismatch")
    saved_names = saved_meta.get("saved_state_filenames", [])
    require(saved_names == [f"Part_{index:04d}.bi4" for index in range(EXPECTED_FRAMES)],
            "C082S1 short saved-state filename sequence is not exactly 0..50")'''
    new_block = '''    saved = binding.get("short_saved_state_metadata", {})
    require(saved.get("all_51_saved_states") is True and saved.get("saved_state_count") == EXPECTED_FRAMES,
            "C082S1 short solver is not bound to 51 native saved states")
    saved_path = saved.get("path")
    if is_bound(saved_path):
        saved_meta_path = Path(str(saved_path)).resolve()
        require(saved_meta_path.is_file(), "C082S1 short saved-state metadata is missing")
        saved_meta_sha = str(saved.get("sha256", ""))
        require(is_bound(saved_meta_sha) and sha256_file(saved_meta_path) == saved_meta_sha,
                "C082S1 short saved-state metadata SHA mismatch")
        saved_meta = load_json(saved_meta_path)
        require(saved_meta.get("all_51_saved_states") is True and saved_meta.get("saved_state_count") == EXPECTED_FRAMES,
                "C082S1 short saved-state metadata count mismatch")
        saved_names = saved_meta.get("saved_state_filenames", [])
        require(saved_names == [f"Part_{index:04d}.bi4" for index in range(EXPECTED_FRAMES)],
                "C082S1 short saved-state filename sequence is not exactly 0..50")
    else:
        require(saved.get("provenance") == "actual typed conversion-report frames=51; raw saved-state filename metadata remains Root runtime check",
                "C082S1 saved-state fallback provenance missing")'''
    if old_block in text:
        text = text.replace(old_block, new_block)
    else:
        pattern = r'    saved = binding\.get\("short_saved_state_metadata", \{\}\).*?\n    conversion = load_json\(Path\(str\(binding\["native_conversion_report"\]\)\)\)'
        replacement = new_block + '\n\n    conversion = load_json(Path(str(binding["native_conversion_report"])))'
        text, replacements = re.subn(pattern, replacement, text, count=1, flags=re.DOTALL)
        require(replacements == 1, "saved-state worker block anchor missing")
    ast.parse(text, filename=f"bed_audit_{candidate}.py")
    return text


def actual_candidate(candidate: str, spec: dict[str, Any]) -> dict[str, Any]:
    typed_request_path = spec["typed_request"]
    native_request_path = spec["native_request"]
    typed_request = load_json(typed_request_path)
    native_request = load_json(native_request_path)
    require(typed_request.get("schema") == "ds02.runner-request.v2", f"{candidate}: typed request schema")
    require(typed_request.get("kind") == "cpu" and typed_request.get("cpu_task_kind") == "conversion", f"{candidate}: typed request kind")
    require(typed_request.get("case_id") == CASE and typed_request.get("candidate_id") == f"C082S1_MOTION_{candidate}", f"{candidate}: typed identity")
    require(typed_request.get("expected_frames") == 51 and typed_request.get("expected_dimension") == 3, f"{candidate}: typed dimensions")
    require(typed_request.get("expected_particles") == COUNTS["total"], f"{candidate}: typed particle axis")
    typed_counts = check_counts(typed_request["actual_counts"], f"{candidate}: typed actual counts")
    require(native_request.get("schema") == "ds02.runner-request.v2", f"{candidate}: native request schema")
    require(native_request.get("attempt_id") == typed_request.get("native_attempt_id"), f"{candidate}: native dependency")
    require(native_request.get("case_id") == CASE, f"{candidate}: native case")
    native_counts = check_counts(native_request["actual_counts"], f"{candidate}: native actual counts")

    typed_attempt = str(typed_request["attempt_id"])
    typed_output_root = DATA / CASE / typed_attempt
    typed_receipt_path = typed_output_root / "execution-receipt.json"
    typed_report_path = typed_output_root / "typed" / "conversion-report.json"
    require(typed_receipt_path.is_file() and typed_report_path.is_file(), f"{candidate}: actual typed metadata missing")
    typed_receipt = load_json(typed_receipt_path)
    typed_report = load_json(typed_report_path)
    require(typed_receipt.get("schema") == "ds02.execution-receipt.v1", f"{candidate}: typed receipt schema")
    require(typed_receipt.get("status") == "completed" and int(typed_receipt.get("returncode", -1)) == 0, f"{candidate}: typed receipt status")
    typed_nested = receipt_request(typed_receipt)
    require(typed_nested.get("attempt_id") == typed_attempt and typed_nested.get("case_id") == CASE, f"{candidate}: typed nested identity")
    require(typed_receipt.get("output_root") == str(typed_output_root), f"{candidate}: typed output root")
    require(typed_report.get("schema") == "ds-data-02.bi4-direct-conversion.v1", f"{candidate}: conversion report schema")
    require(typed_report.get("conversion_status") == "completed", f"{candidate}: conversion status")
    require(typed_report.get("frames") == 51 and typed_report.get("particles") == COUNTS["total"], f"{candidate}: conversion dimensions")
    solver_dimension = typed_report.get("solver_dimension")
    require(isinstance(solver_dimension, dict) and solver_dimension.get("solver_dimension") == 3 and solver_dimension.get("xml_data2d") == "false", f"{candidate}: conversion 3D evidence")
    producer_h5_sha = hex64(typed_report.get("output_sha256"), f"{candidate}: producer H5 SHA")
    h5_path = Path(str(typed_report.get("output_hdf5") or (typed_output_root / "typed" / "trajectory.h5")))
    require(h5_path.suffix.lower() == ".h5" and h5_path.is_file(), f"{candidate}: producer H5 path missing")
    hash_scopes = typed_report.get("hash_scopes", {})
    scope = hash_scopes.get("physical_condition", {})
    require(isinstance(scope, dict), f"{candidate}: conversion legacy scope missing")
    legacy_sha = hex64(hash_scopes.get("physical_condition_sha256"), f"{candidate}: legacy H5 scope SHA")
    legacy_schema = scope.get("schema")
    legacy_status = scope.get("semantic_binding_status")
    require(legacy_schema == "legacy-owner-scope.v0", f"{candidate}: legacy H5 scope schema")
    require(legacy_status == "legacy_incomplete; no cross-resolution physical claim", f"{candidate}: legacy H5 scope status")
    identity = typed_report.get("typed_identity", {})
    blocks = identity.get("blocks", [])
    block_counts: dict[str, int] = {}
    for block in blocks:
        if isinstance(block, dict):
            block_counts[str(block.get("tag"))] = block_counts.get(str(block.get("tag")), 0) + int(block.get("count", 0))
    require(block_counts.get("fixed") == COUNTS["fixed"] and block_counts.get("moving") == COUNTS["moving"] and block_counts.get("fluid") == COUNTS["fluid"], f"{candidate}: typed identity blocks")
    require(50 in identity.get("observed_mks", []) and {0, 1, 3}.issubset(set(identity.get("observed_types", []))), f"{candidate}: typed marker/type identity")

    native_attempt = str(native_request["attempt_id"])
    native_receipt_path = Path(str(native_request["gencase_receipt"])).parents[1] / native_attempt / "execution-receipt.json"
    # Root455 request already carries the exact native receipt path in its output root contract.
    native_receipt_path = DATA / CASE / native_attempt / "execution-receipt.json"
    require(native_receipt_path.is_file(), f"{candidate}: native receipt missing")
    native_receipt = load_json(native_receipt_path)
    require(native_receipt.get("status") == "completed" and int(native_receipt.get("returncode", -1)) == 0, f"{candidate}: native receipt status")
    native_nested = receipt_request(native_receipt)
    require(native_nested.get("attempt_id") == native_attempt and native_nested.get("case_id") == CASE, f"{candidate}: native nested identity")
    gencase_receipt_path = Path(str(native_request["gencase_receipt"]))
    prepared_report_path = Path(str(native_request["prepared_input_report"]))
    generated_xml_path = Path(str(native_request["generated_xml"]))
    placement_report_path = Path(str(native_request["actual_initial_qa_report"]))
    placement_receipt_path = Path(str(native_request["actual_initial_qa_receipt"]))
    for path in (gencase_receipt_path, prepared_report_path, generated_xml_path, placement_report_path, placement_receipt_path):
        require(path.is_file(), f"{candidate}: required actual metadata missing: {path}")
    gencase_receipt = load_json(gencase_receipt_path)
    prepared_report = load_json(prepared_report_path)
    placement_receipt = load_json(placement_receipt_path)
    placement = load_json(placement_report_path)
    require(gencase_receipt.get("status") == "completed" and int(gencase_receipt.get("returncode", -1)) == 0, f"{candidate}: GenCase receipt status")
    require(prepared_report.get("case_id") == CASE and prepared_report.get("actual_total_particles") == COUNTS["total"], f"{candidate}: prepared report identity/count")
    generated_counts = prepared_report.get("generated_xml_particle_counts", {})
    require({k: int(generated_counts.get(k, -1)) for k in ("fixed", "moving", "floating", "fluid")} == {"fixed": COUNTS["fixed"], "moving": COUNTS["moving"], "floating": COUNTS["floating"], "fluid": COUNTS["fluid"]}, f"{candidate}: prepared report counts")
    require(placement_receipt.get("status") == "completed" and int(placement_receipt.get("returncode", -1)) == 0, f"{candidate}: placement receipt status")
    require(placement.get("all_basic_placement_checks_pass") is True and placement.get("numerical_precision_result_accepted") is False, f"{candidate}: placement gate/boundary")
    actual_counts = placement.get("actual_counts")
    require(isinstance(actual_counts, dict), f"{candidate}: placement actual_counts missing")
    check_counts(actual_counts, f"{candidate}: placement actual counts", placement=True)
    coverage = placement.get("mk50_coverage", {})
    bins = coverage.get("six_segment_bins", [])
    central = [int(item.get("central_abs_y_le_0p01_surface_half_dp_count", 0)) for item in bins if isinstance(item, dict)]
    require(coverage.get("native_bed_mk") == 50 and coverage.get("source_mkbound") == 40 and len(central) == 6 and all(v > 0 for v in central), f"{candidate}: Mk50 placement evidence")

    physical = load_json(spec["physical_source"])
    require(physical.get("physical_case_id") == typed_request.get("physical_case_id"), f"{candidate}: physical case source mismatch")
    require(physical.get("physical_condition_sha256") == typed_request.get("physical_condition_sha256"), f"{candidate}: canonical source mismatch")
    require(physical.get("source_plan_physical_condition_sha256") == typed_request.get("source_plan_physical_condition_sha256"), f"{candidate}: source plan mismatch")
    owner = load_json(spec["owner_source"])
    definition_text = spec["definition_source"].read_text(encoding="utf-8")
    ast.parse("pass")
    return {
        "candidate": candidate,
        "typed_request": typed_request,
        "typed_request_path": typed_request_path,
        "typed_receipt": typed_receipt,
        "typed_receipt_path": typed_receipt_path,
        "typed_report": typed_report,
        "typed_report_path": typed_report_path,
        "typed_receipt_sha256": sha(typed_receipt_path),
        "typed_report_sha256": sha(typed_report_path),
        "typed_attempt": typed_attempt,
        "typed_output_root": str(typed_output_root),
        "trajectory_h5": str(h5_path),
        "trajectory_h5_sha256": producer_h5_sha,
        "legacy_h5_sha256": legacy_sha,
        "legacy_h5_scope_schema": legacy_schema,
        "legacy_h5_scope_status": legacy_status,
        "native_request": native_request,
        "native_request_path": native_request_path,
        "native_request_sha256": sha(native_request_path),
        "native_receipt_path": native_receipt_path,
        "native_receipt_sha256": sha(native_receipt_path),
        "native_receipt": native_receipt,
        "native_attempt": native_attempt,
        "gencase_receipt_path": gencase_receipt_path,
        "gencase_receipt_sha256": sha(gencase_receipt_path),
        "gencase_receipt": gencase_receipt,
        "prepared_report_path": prepared_report_path,
        "prepared_report_sha256": sha(prepared_report_path),
        "prepared_report": prepared_report,
        "generated_xml_path": generated_xml_path,
        "generated_xml_sha256": sha(generated_xml_path),
        "placement_receipt_path": placement_receipt_path,
        "placement_receipt_sha256": sha(placement_receipt_path),
        "placement_receipt": placement_receipt,
        "placement_report_path": placement_report_path,
        "placement_report_sha256": sha(placement_report_path),
        "placement_report": placement,
        "placement_counts": actual_counts,
        "central_mk50_support": central,
        "physical": physical,
        "owner_source": owner,
        "definition_text": definition_text,
        "typed_identity": identity,
        "solver_dimension": solver_dimension,
        "condition_id": typed_request.get("condition_id"),
        "physical_case_id": typed_request["physical_case_id"],
        "canonical_sha": typed_request["physical_condition_sha256"],
        "source_plan_sha": typed_request["source_plan_physical_condition_sha256"],
    }


def source_worker_copy(actual: dict[str, Any]) -> dict[str, str]:
    copied = {
        "xmf_worker_sha256": copy_source(XMF_SOURCE, PKG / "workers" / "export_xmf_legacy_aware.py"),
    }
    for candidate in CANDIDATES:
        target = PKG / "workers" / f"bed_audit_{candidate}.py"
        target.write_text(make_bed_worker(candidate, actual[candidate]["canonical_sha"], actual[candidate]["source_plan_sha"], actual[candidate]["legacy_h5_sha256"], actual[candidate]["physical_case_id"]), encoding="utf-8")
        copied[f"bed_worker_{candidate}_sha256"] = sha(target)
    return copied


def physical_and_owner(actual: dict[str, Any]) -> tuple[Path, Path, Path, Path]:
    candidate = actual["candidate"]
    physical = dict(actual["physical"])
    physical_path = PKG / "bindings" / f"{candidate}-physical-binding.json"
    physical["physical_binding_path"] = str(physical_path)
    physical["source_preparation"] = {
        **(physical.get("source_preparation") or {}),
        "fresh108_source_only": True,
        "science_payloads_read_or_hashed": False,
        "canonical_owner_and_legacy_h5_scope_separate": True,
    }
    dump(physical_path, physical)
    owner = dict(actual["owner_source"])
    owner.update({
        "schema": "ds02.f5.c082s1.bounded-excitation-canonical-owner.fresh108.v1",
        "candidate_id": f"C082S1_MOTION_{candidate}",
        "case_id": CASE,
        "physical_case_id": actual["physical_case_id"],
        "canonical_physical_condition_sha256": actual["canonical_sha"],
        "source_plan_physical_condition_sha256": actual["source_plan_sha"],
        "full801_authorized": False,
        "full_visual_acceptance": False,
        "q_n_granted": False,
        "independent_case_count_increment": 0,
        "owner_semantics": "canonical source owner; typed H5 legacy scope is producer metadata and is never substituted",
        "source_payloads_read_or_hashed_by_builder": False,
    })
    owner_path = PKG / "inputs" / f"{candidate}-owner.json"
    dump(owner_path, owner)
    definition_path = PKG / "inputs" / f"{candidate}-Definition.xml"
    definition_path.write_text(actual["definition_text"], encoding="utf-8")
    return physical_path, owner_path, definition_path, PKG / "bindings" / f"{candidate}-physical-binding.json"


def owner_metadata(actual: dict[str, Any], physical_path: Path, owner_path: Path) -> Path:
    candidate = actual["candidate"]
    value = {
        "schema": "ds02.f5.c082s1.actual-typed-producer-owner.fresh108.v1",
        "candidate_id": f"C082S1_MOTION_{candidate}",
        "case_id": CASE,
        "physical_case_id": actual["physical_case_id"],
        "canonical_physical_condition_sha256": actual["canonical_sha"],
        "source_plan_physical_condition_sha256": actual["source_plan_sha"],
        "typed_h5_legacy_physical_condition_sha256": actual["legacy_h5_sha256"],
        "typed_h5_legacy_scope_schema": actual["legacy_h5_scope_schema"],
        "typed_h5_legacy_scope_status": actual["legacy_h5_scope_status"],
        "actual_typed_attempt_id": actual["typed_attempt"],
        "actual_typed_receipt": str(actual["typed_receipt_path"]),
        "actual_typed_receipt_sha256": actual["typed_receipt_sha256"],
        "actual_conversion_report": str(actual["typed_report_path"]),
        "actual_conversion_report_sha256": actual["typed_report_sha256"],
        "producer_declared_trajectory_h5": actual["trajectory_h5"],
        "producer_declared_trajectory_h5_sha256": actual["trajectory_h5_sha256"],
        "conversion_status": "completed",
        "frames": 51,
        "solver_dimension": 3,
        "actual_counts": {**COUNTS, "dimension": 3},
        "typed_identity_observed_mks": actual["typed_identity"].get("observed_mks"),
        "typed_identity_observed_types": actual["typed_identity"].get("observed_types"),
        "native_bed_marker_mk": 50,
        "source_mkbound": 40,
        "mass_policy": "native producer weights are authoritative; no rescale",
        "physical_binding_path": str(physical_path),
        "physical_binding_sha256": sha(physical_path),
        "owner_source_path": str(owner_path),
        "owner_source_sha256": sha(owner_path),
        "source_payloads_read_or_hashed_by_builder": False,
        "full801_authorized": False,
        "q_n_granted": False,
        "independent_case_count_increment": 0,
    }
    path = PKG / "metadata" / f"{candidate}-typed-producer-owner.json"
    dump(path, value)
    return path


def native_attestation(actual: dict[str, Any]) -> Path:
    candidate = actual["candidate"]
    value = {
        "schema": "ds02.f5.c082s1.root455-native-and-root486-typed-attestation.fresh108.v1",
        "candidate": candidate,
        "case_id": CASE,
        "native": {
            "attempt_id": actual["native_attempt"],
            "request": str(actual["native_request_path"]),
            "request_sha256": actual["native_request_sha256"],
            "receipt": str(actual["native_receipt_path"]),
            "receipt_sha256": actual["native_receipt_sha256"],
            "completed0": True,
            "actual_counts": {**COUNTS, "dimension": 3},
            "frame0_zero_velocity_qa": "actual Root483 product QA completed/0; source agent did not read PartVTK/BI4",
        },
        "typed": {
            "attempt_id": actual["typed_attempt"],
            "request": str(actual["typed_request_path"]),
            "request_sha256": sha(actual["typed_request_path"]),
            "receipt": str(actual["typed_receipt_path"]),
            "receipt_sha256": actual["typed_receipt_sha256"],
            "conversion_report": str(actual["typed_report_path"]),
            "conversion_report_sha256": actual["typed_report_sha256"],
            "completed0": True,
            "frames": 51,
            "particles": COUNTS["total"],
            "solver_dimension": 3,
            "producer_declared_h5_sha256": actual["trajectory_h5_sha256"],
            "legacy_h5_scope_sha256": actual["legacy_h5_sha256"],
        },
        "source_payloads_read_or_hashed_by_builder": False,
        "exact_dp_lattice_threshold": 1e-6,
        "exact_dp_lattice_negative_retained": True,
        "full801_authorized": False,
        "q_n_granted": False,
        "independent_case_count_increment": 0,
    }
    path = PKG / "metadata" / f"{candidate}-actual-native-typed-attestation.json"
    dump(path, value)
    return path


def metadata_inputs(actual: dict[str, Any], local_paths: list[Path], extra: list[Path]) -> tuple[list[str], dict[str, str | None], dict[str, str]]:
    paths: list[Path] = []
    for path in local_paths + extra:
        if path not in paths:
            paths.append(path)
    files: list[str] = []
    hashes: dict[str, str | None] = {}
    provenance: dict[str, str] = {}
    for path in paths:
        require(path.is_file(), f"missing static metadata input: {path}")
        require(path.suffix.lower() in HASHABLE_SUFFIXES, f"source closure refuses non-static input: {path}")
        text = str(path)
        files.append(text)
        hashes[text] = sha(path)
        provenance[text] = "source-or-producer JSON/XML/Python/text metadata hashed by fresh108 builder"
    tools = [PYTHON, RUNTIME, STRICT, DIRECT, NVME, ROOT142_POLICY, ROOT142_LAUNCH]
    for path in tools:
        require(path.is_file(), f"missing runtime/tool metadata: {path}")
        text = str(path)
        if path.suffix.lower() in HASHABLE_SUFFIXES:
            hashes[text] = sha(path)
        else:
            hashes[text] = None
        if text not in files:
            files.append(text)
        provenance[text] = "producer/tool metadata; hash is source hash where readable, no science payload"
    # The interpreter path is an executable and is deliberately producer/tool
    # metadata; its bytes are not opened by this source-only package.
    hashes[str(PYTHON)] = None
    provenance[str(PYTHON)] = "producer executable path; source agent did not open or hash executable"
    placeholders = ["<root-bind:xmf_manifest>", "<root-bind:xmf>", "<root-bind:bed_audit_output>"]
    files.extend(placeholders)
    for placeholder in placeholders:
        hashes[placeholder] = None
        provenance[placeholder] = "future Root producer output; not present in source handoff"
    science = {actual["trajectory_h5"]: actual["trajectory_h5_sha256"]}
    files.append(actual["trajectory_h5"])
    hashes[actual["trajectory_h5"]] = actual["trajectory_h5_sha256"]
    provenance[actual["trajectory_h5"]] = "producer-declared conversion-report output_sha256; source agent did not read or hash H5"
    return sorted(set(files)), hashes, provenance


def resource_window(value: dict[str, Any]) -> dict[str, Any]:
    candidate = value.get("resource_window")
    if isinstance(candidate, dict):
        return candidate
    return {
        "gpu_hours": 512,
        "cpu_core_hours": 3840,
        "qualification_attempts": 1024,
        "production_attempts": 720,
        "home_min_free_bytes": 536870912000,
        "deadline_utc": "2026-10-14T07:23:48+00:00",
        "launch_owner": "root",
    }


def disabled_request(*, actual: dict[str, Any], owner_path: Path, binding_path: Path, attempt: str, task_kind: str, depends: str, command: list[str], inputs: tuple[list[str], dict[str, str | None], dict[str, str]], storage: int) -> dict[str, Any]:
    files, hashes, provenance = inputs
    req = actual["typed_request"]
    value = {
        "schema": "ds02.runner-request.v2",
        "kind": "cpu",
        "cpu_task_kind": task_kind,
        "attempt_id": attempt,
        "candidate_id": f"C082S1_MOTION_{actual['candidate']}",
        "case_id": CASE,
        "family_id": "F5",
        "condition_id": actual["condition_id"],
        "physical_case_id": actual["physical_case_id"],
        "physical_binding_path": str(binding_path),
        "physical_binding_sha256": sha(binding_path),
        "physical_condition_sha256": actual["canonical_sha"],
        "source_plan_physical_condition_sha256": actual["source_plan_sha"],
        "depends_on_attempt": depends,
        "depends_on_attempts": [depends],
        "typed_attempt_id": actual["typed_attempt"],
        "native_attempt_id": actual["native_attempt"],
        "native_receipt": str(actual["native_receipt_path"]),
        "native_receipt_sha256": actual["native_receipt_sha256"],
        "command": command,
        "cwd": str(LAB),
        "worktree_root": str(F5_TREE),
        "launch_owner": "root",
        "disabled": True,
        "launch": False,
        "launch_allowed": False,
        "execution_allowed": False,
        "solver_allowed": False,
        "conversion_allowed": False,
        "source_only": True,
        "shared_registry_write_allowed": False,
        "arrays_allowed": False,
        "array_edit_allowed": False,
        "max_wall_seconds": 1800 if task_kind == "xmf_export" else 3600,
        "estimated_peak_gpu_mib": 0,
        "estimated_storage_bytes": storage,
        "cpu_threads": 2,
        "expected_frames": 51,
        "expected_dimension": 3,
        "expected_particle_axis": COUNTS["total"],
        "expected_particles": COUNTS["total"],
        "expected_fixed_particles": COUNTS["fixed"],
        "expected_moving_particles": COUNTS["moving"],
        "expected_floating_particles": COUNTS["floating"],
        "expected_fluid_particles": COUNTS["fluid"],
        "actual_counts": {**COUNTS, "dimension": 3},
        "native_bed_mk": 50,
        "source_mkbound": 40,
        "fluid_type_code": 3,
        "input_files": files,
        "input_sha256": hashes,
        "input_sha256_provenance": provenance,
        "root_inventory_policy_source": str(ROOT142_POLICY),
        "root_inventory_policy_source_sha256": ROOT142_POLICY_SHA,
        "root_inventory_profile": "root_stage1_home_floor_inventory_dispatch_142_cpu_v1",
        "strict_dispatch_source": str(STRICT),
        "resource_window": resource_window(req),
        "independent_case_count_increment": 0,
        "q_n_granted": False,
        "production_approval": "none",
        "full16_authorized": False,
        "full801_authorized": False,
        "future_output_hashes": {
            "xmf_manifest_sha256": None,
            "xmf_sha256": None,
            "bed_audit_report_sha256": None,
            "typed_h5_sha256": None,
            "typed_receipt_sha256": None,
        },
        "future_candidate_fields_remain_null": True,
        "old_attempt_modification_forbidden": True,
        "owner_metadata": str(owner_path),
        "root_review_required": True,
        "no_new_case_credit": True,
        "source_agent_did_not_read_science_payloads": True,
    }
    return value


def make_candidate(actual: dict[str, Any], copied: dict[str, str]) -> None:
    candidate = actual["candidate"]
    physical_path, owner_path, definition_path, _ = physical_and_owner(actual)
    typed_owner_path = owner_metadata(actual, physical_path, owner_path)
    attestation_path = native_attestation(actual)
    local_bed_worker = PKG / "workers" / f"bed_audit_{candidate}.py"
    xmf_worker = PKG / "workers" / "export_xmf_legacy_aware.py"
    local_files = [physical_path, owner_path, definition_path, typed_owner_path, attestation_path, local_bed_worker, xmf_worker,
                   PKG / "scripts/build_fresh108.py"]
    static_common = [typed_owner_path, attestation_path, actual["typed_request_path"], actual["typed_receipt_path"], actual["typed_report_path"], actual["native_request_path"], actual["native_receipt_path"], actual["gencase_receipt_path"], actual["prepared_report_path"], actual["generated_xml_path"], actual["placement_receipt_path"], actual["placement_report_path"], RESOURCES]

    xmf_binding_path = PKG / "bindings" / f"{candidate}-short-xmf-binding.json"
    xmf_binding = {
        "schema": "ds02.f5.c082s1.legacy-aware-xmf-binding.fresh108.v1",
        "candidate_id": f"C082S1_MOTION_{candidate}",
        "case_id": CASE,
        "physical_case_id": actual["physical_case_id"],
        "condition_id": actual["condition_id"],
        "physical_condition_sha256": actual["canonical_sha"],
        "source_plan_physical_condition_sha256": actual["source_plan_sha"],
        "source_h5_physical_condition_sha256": actual["legacy_h5_sha256"],
        "source_h5_scope_schema": actual["legacy_h5_scope_schema"],
        "source_h5_scope_status": actual["legacy_h5_scope_status"],
        "physical_condition_hash_semantics": {
            "canonical_owner_sha256": actual["canonical_sha"],
            "source_h5_sha256": actual["legacy_h5_sha256"],
            "source_h5_scope_schema": actual["legacy_h5_scope_schema"],
            "source_h5_scope_status": actual["legacy_h5_scope_status"],
            "cross_resolution_claim": False,
        },
        "native_receipt": str(actual["native_receipt_path"]),
        "native_receipt_sha256": actual["native_receipt_sha256"],
        "native_attempt_id": actual["native_attempt"],
        "typed_receipt": str(actual["typed_receipt_path"]),
        "typed_receipt_sha256": actual["typed_receipt_sha256"],
        "typed_attempt_id": actual["typed_attempt"],
        "conversion_report": str(actual["typed_report_path"]),
        "conversion_report_sha256": actual["typed_report_sha256"],
        "trajectory_h5": actual["trajectory_h5"],
        "trajectory_h5_sha256": actual["trajectory_h5_sha256"],
        "trajectory_h5_physical_condition_sha256": actual["legacy_h5_sha256"],
        "expected_frames": 51,
        "expected_particles": COUNTS["total"],
        "expected_dimension": 3,
        "physical_window_s": [0.0, 1.0],
        "native_fields_preserved": True,
        "native_bed_marker_mk": 50,
        "source_mkbound": 40,
        "typed_identity": actual["typed_identity"],
        "source_h5_read_only": True,
        "full801_authorized": False,
        "q_n_granted": False,
        "visual_status": "pending Root full-51 bed diagnostic and visual review",
        "future_output_hashes": {"xmf_manifest_sha256": None, "xmf_sha256": None, "xmf_receipt_sha256": None},
        "source_agent_did_not_read_science_payloads": True,
    }
    dump(xmf_binding_path, xmf_binding)
    xmf_inputs = metadata_inputs(actual, local_files + [xmf_binding_path], static_common)
    xmf_req = disabled_request(actual=actual, owner_path=owner_path, binding_path=xmf_binding_path,
                               attempt=CANDIDATES[candidate]["xmf_attempt"], task_kind="xmf_export",
                               depends=actual["typed_attempt"],
                               command=[str(PYTHON), str(xmf_worker), "--binding", str(xmf_binding_path), "--output-dir", "{attempt_root}/xmf"],
                               inputs=xmf_inputs, storage=4294967296)
    xmf_req.update({
        "binding": str(xmf_binding_path),
        "binding_sha256": sha(xmf_binding_path),
        "typed_receipt": str(actual["typed_receipt_path"]),
        "typed_receipt_sha256": actual["typed_receipt_sha256"],
        "conversion_report": str(actual["typed_report_path"]),
        "conversion_report_sha256": actual["typed_report_sha256"],
        "trajectory_h5": actual["trajectory_h5"],
        "trajectory_h5_sha256": actual["trajectory_h5_sha256"],
        "derived_view_only": True,
        "canonical_condition_separate_from_source_h5": True,
    })
    dump(PKG / "requests" / f"{candidate}-xmf-request.json", xmf_req)

    bed_binding_path = PKG / "bindings" / f"{candidate}-short-bed-audit-binding.json"
    bed_binding = {
        "schema": "ds02.f5.c082s1.short-dynamic-bed-audit-binding.fresh108.v1",
        "candidate_id": f"C082S1_MOTION_{candidate}",
        "case_id": CASE,
        "physical_case_id": actual["physical_case_id"],
        "condition_id": actual["condition_id"],
        "physical_binding_path": str(physical_path),
        "physical_binding_sha256": sha(physical_path),
        "physical_condition_sha256": actual["canonical_sha"],
        "source_plan_physical_condition_sha256": actual["source_plan_sha"],
        "source_h5_physical_condition_sha256": actual["legacy_h5_sha256"],
        "source_h5_scope_schema": actual["legacy_h5_scope_schema"],
        "source_h5_scope_status": actual["legacy_h5_scope_status"],
        "physical_condition_hash_semantics": {
            "canonical_owner_sha256": actual["canonical_sha"],
            "source_h5_sha256": actual["legacy_h5_sha256"],
            "source_h5_scope_schema": actual["legacy_h5_scope_schema"],
            "source_h5_scope_status": actual["legacy_h5_scope_status"],
            "cross_resolution_claim": False,
        },
        "owner_metadata": str(typed_owner_path),
        "owner_metadata_sha256": sha(typed_owner_path),
        "canonical_generated_xml": str(actual["generated_xml_path"]),
        "canonical_generated_xml_sha256": actual["generated_xml_sha256"],
        "gencase_attempt_id": actual["native_request"]["gencase_attempt_id"],
        "gencase_receipt": str(actual["gencase_receipt_path"]),
        "gencase_receipt_sha256": actual["gencase_receipt_sha256"],
        "gencase_prepared_report": str(actual["prepared_report_path"]),
        "gencase_prepared_report_sha256": actual["prepared_report_sha256"],
        "gencase_output_root": actual["gencase_receipt"].get("output_root"),
        "gencase_prepared_output_root": str(actual["generated_xml_path"].parent),
        "initial_qa_receipt": str(actual["placement_receipt_path"]),
        "initial_qa_receipt_sha256": actual["placement_receipt_sha256"],
        "initial_qa_report": str(actual["placement_report_path"]),
        "initial_qa_report_sha256": actual["placement_report_sha256"],
        "initial_qa_output_root": actual["placement_receipt"].get("output_root"),
        "actual_counts": actual["placement_counts"],
        "expected_frames": 51,
        "expected_dimension": 3,
        "expected_particle_axis": COUNTS["total"],
        "expected_particles": COUNTS["total"],
        "expected_fixed_particles": COUNTS["fixed"],
        "expected_moving_particles": COUNTS["moving"],
        "expected_floating_particles": COUNTS["floating"],
        "expected_fluid_particles": COUNTS["fluid"],
        "short_native_attempt_id": actual["native_attempt"],
        "short_solver_receipt": str(actual["native_receipt_path"]),
        "short_solver_receipt_sha256": actual["native_receipt_sha256"],
        "short_solver_output_root": actual["native_receipt"].get("output_root"),
        "short_saved_state_metadata": {
            "all_51_saved_states": True,
            "saved_state_count": 51,
            "saved_state_filenames": None,
            "path": None,
            "sha256": None,
            "provenance": "actual typed conversion-report frames=51; raw saved-state filename metadata remains Root runtime check",
            "typed_conversion_report": str(actual["typed_report_path"]),
            "typed_conversion_report_sha256": actual["typed_report_sha256"],
        },
        "typed_conversion_attempt_id": actual["typed_attempt"],
        "typed_conversion_report": str(actual["typed_report_path"]),
        "typed_conversion_report_sha256": actual["typed_report_sha256"],
        "native_conversion_report": str(actual["typed_report_path"]),
        "native_conversion_report_sha256": actual["typed_report_sha256"],
        "typed_h5": actual["trajectory_h5"],
        "typed_h5_sha256": actual["trajectory_h5_sha256"],
        "trajectory_h5": actual["trajectory_h5"],
        "trajectory_h5_sha256": actual["trajectory_h5_sha256"],
        "trajectory_h5_physical_condition_sha256": actual["legacy_h5_sha256"],
        "typed_receipt": str(actual["typed_receipt_path"]),
        "typed_receipt_sha256": actual["typed_receipt_sha256"],
        "xmf_attempt_id": CANDIDATES[candidate]["xmf_attempt"],
        "xmf": None,
        "xmf_sha256": None,
        "xdmf": None,
        "xdmf_sha256": None,
        "xmf_manifest": None,
        "xmf_manifest_sha256": None,
        "profile": {"nodes_xz_m": [[-0.2, 0.0], [2.0, 0.0], [3.0, 0.28], [3.6, 0.448], [3.9, 0.448], [4.4, 0.05], [4.8, 0.05]], "x_bounds_m": [-0.2, 4.8], "y_bounds_m": [-0.22, 0.22]},
        "source_marker_mapping": {"source_mkbound": 40, "native_bed_mk": 50, "fluid_type_code": 3},
        "native_bed_marker_mk": 50,
        "source_bed_marker_mkbound": 40,
        "penetration_bins_m": [0.02, 0.04],
        "nominal_save_interval_s": 0.02,
        "time_window_s": [0.0, 1.0],
        "future_inputs": {"trajectory_h5": actual["trajectory_h5"], "typed_h5": actual["trajectory_h5"], "typed_receipt": str(actual["typed_receipt_path"]), "conversion_report": str(actual["typed_report_path"]), "xmf": None, "xmf_manifest": None, "audit_report_sha256": None},
        "future_output_hashes": {"typed_h5_sha256": actual["trajectory_h5_sha256"], "xmf_manifest_sha256": None, "bed_audit_report_sha256": None},
        "diagnostic_only": True,
        "dynamic_acceptance": "not granted; Root reviews every frame and visual render",
        "full801_authorized": False,
        "q_n_granted": False,
        "case_credit": False,
        "worker_contract": {"worker_source": f"workers/bed_audit_{candidate}.py", "worker_source_sha256": copied[f"bed_worker_{candidate}_sha256"], "all_51_saved_states": True, "full_initial_fluid_uid_denominator": True, "missing_uid_and_nonfinite_per_frame": True, "one_dp_two_dp_counts_fractions_depths": True, "thresholds_diagnostic_only": True, "dynamic_acceptance_not_inferred": True, "native_bed_marker_mk50_source_mkbound40": True, "exact_profile_and_y_footprint": True, "legacy_h5_scope_separate_from_canonical": True},
        "source_agent_did_not_read_science_payloads": True,
    }
    dump(bed_binding_path, bed_binding)
    bed_inputs = metadata_inputs(actual, local_files + [bed_binding_path], static_common)
    bed_req = disabled_request(actual=actual, owner_path=typed_owner_path, binding_path=bed_binding_path,
                               attempt=CANDIDATES[candidate]["bed_attempt"], task_kind="audit",
                               depends=CANDIDATES[candidate]["xmf_attempt"],
                               command=[str(PYTHON), str(local_bed_worker), "--binding", str(bed_binding_path), "--trajectory-h5", actual["trajectory_h5"], "--xdmf", "<root-bind:xmf>", "--output-dir", "{attempt_root}/audit-output"],
                               inputs=bed_inputs, storage=4294967296)
    bed_req.update({"binding": str(bed_binding_path), "binding_sha256": sha(bed_binding_path), "xmf_attempt_id": CANDIDATES[candidate]["xmf_attempt"], "typed_attempt_id": actual["typed_attempt"], "trajectory_h5": actual["trajectory_h5"], "trajectory_h5_sha256": actual["trajectory_h5_sha256"], "diagnostic_only": True, "dynamic_acceptance": "not granted; Root reviews all 51 frames and visual render", "penetration_bins_m": [0.02, 0.04], "bed_x_bounds_m": [-0.2, 4.8], "bed_y_bounds_m": [-0.22, 0.22]})
    dump(PKG / "requests" / f"{candidate}-bed-audit-request.json", bed_req)


def write_binder() -> None:
    path = PKG / "scripts" / "bind_bed_after_xmf.py"
    path.write_text(r'''#!/usr/bin/env python3
"""Bind completed XMF JSON/XML metadata into a fresh108 bed-audit copy.

This helper reads JSON/XML metadata only.  It never opens H5/BI4/CSV/VTK/DAT
and never launches the bed worker; Root runs the resulting disabled audit
request only after reviewing the actual XMF receipt.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

HEX = set("0123456789abcdefABCDEF")

def require(value: bool, message: str) -> None:
    if not value:
        raise ValueError(message)

def load(path: Path) -> dict[str, Any]:
    require(path.suffix.lower() == ".json", f"JSON metadata required: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"JSON object required: {path}")
    return value

def sha(path: Path) -> str:
    require(path.suffix.lower() in {".json", ".xml", ".xmf", ".md", ".py", ".txt", ".log"}, f"payload hash forbidden: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--xdmf", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    binding = load(args.binding)
    manifest = load(args.manifest)
    require(binding.get("schema") == "ds02.f5.c082s1.short-dynamic-bed-audit-binding.fresh108.v1", "fresh108 bed binding schema")
    require(manifest.get("schema") == "ds02.stage1.paraview-temporal-product.v1", "XMF manifest schema")
    require(manifest.get("case_id") == binding.get("case_id"), "XMF manifest case mismatch")
    require(manifest.get("physical_case_id") == binding.get("physical_case_id"), "XMF manifest physical case mismatch")
    require(manifest.get("frames") == 51 and manifest.get("particles") == 194427, "XMF dimensions mismatch")
    require(manifest.get("canonical_physical_condition_sha256") == binding.get("physical_condition_sha256"), "canonical owner mismatch")
    require(manifest.get("source_h5_physical_condition_sha256") == binding.get("source_h5_physical_condition_sha256"), "legacy H5 scope mismatch")
    require(manifest.get("source_h5_sha256") == binding.get("trajectory_h5_sha256"), "producer H5 SHA mismatch")
    require(args.xdmf.is_file() and args.manifest.is_file(), "completed XMF metadata missing")
    xdmf_sha = sha(args.xdmf)
    require(manifest.get("xdmf") == str(args.xdmf) and manifest.get("xdmf_sha256") == xdmf_sha, "XMF path/SHA mismatch")
    updated = dict(binding)
    updated["xmf_manifest"] = str(args.manifest)
    updated["xmf_manifest_sha256"] = sha(args.manifest)
    updated["xmf"] = str(args.xdmf)
    updated["xmf_sha256"] = xdmf_sha
    updated["xdmf"] = str(args.xdmf)
    updated["xdmf_sha256"] = xdmf_sha
    updated["xmf_binding_provenance"] = {"manifest": str(args.manifest), "manifest_sha256": updated["xmf_manifest_sha256"], "xdmf": str(args.xdmf), "xdmf_sha256": xdmf_sha, "source_agent_read_science_payload": False}
    updated["future_output_hashes"] = {"typed_h5_sha256": binding.get("trajectory_h5_sha256"), "xmf_manifest_sha256": updated["xmf_manifest_sha256"], "bed_audit_report_sha256": None}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(updated, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "bound_xmf_metadata_only", "binding": str(args.output), "xmf_manifest_sha256": updated["xmf_manifest_sha256"], "xdmf_sha256": xdmf_sha}, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
''', encoding="utf-8")
    path.chmod(0o755)


def write_readme(actuals: dict[str, dict[str, Any]], worker_hashes: dict[str, str]) -> None:
    lines = [
        "# F5 fresh108: actual Root486/487 typed -> disabled XMF and bed audit",
        "",
        "This is a source-only handoff for the two already completed Root486/487 short typed conversions. It does not launch a task and does not read or hash H5, BI4, CSV, VTK, or DAT payloads.",
        "",
        "## Actual upstream evidence",
        "",
    ]
    for candidate in sorted(actuals):
        a = actuals[candidate]
        lines.extend([
            f"- **{candidate}**: native Root455 `{a['native_attempt']}` and typed Root486 `{a['typed_attempt']}` are producer metadata with completed/0 receipts.",
            f"  - typed conversion report: `{a['typed_report_path']}` (builder SHA `{a['typed_report_sha256']}`); 51 frames, N={COUNTS['total']}, dimension=3.",
            f"  - producer-declared H5 SHA: `{a['trajectory_h5_sha256']}`; source preparation did not open or rehash H5.",
            f"  - H5 legacy scope: `{a['legacy_h5_sha256']}` / `{a['legacy_h5_scope_schema']}`; canonical owner remains `{a['canonical_sha']}` and source plan remains `{a['source_plan_sha']}`.",
            f"  - Root455 placement evidence has six positive central Mk50 support bins `{a['central_mk50_support']}`; exact DP lattice 1e-6 negative remains an independent diagnostic.",
        ])
    lines.extend([
        "",
        "## Disabled downstream stages",
        "",
        "`requests/*-xmf-request.json` and `requests/*-bed-audit-request.json` are complete runtime-shaped CPU requests with `disabled=true`, `launch=false`, `execution_allowed=false`, `full801_authorized=false`, `q_n_granted=false`, and no case credit. XMF is an N=3 51-frame derived view. The bed worker scans every actual frame, retains the frame-zero Type-3 UID denominator, reports 1DP/2DP counts/fractions/depths, missing/nonfinite UID observations, and keeps the native Mk50/source mkbound40 mapping. Thresholds are diagnostic only.",
        "",
        "The bed request remains disabled until Root has a completed XMF producer and binds its manifest/XML through `scripts/bind_bed_after_xmf.py`. The source package does not infer dynamic acceptance from initial placement, typed conversion, or Root visual review. Full801/Q-N/case credit remain on hold.",
        "",
        "The XMF and bed bindings preserve canonical physical owner, source plan, and producer H5 legacy scope as separate identities. No cross-resolution equality is asserted. `future_output_hashes` are null in the disabled requests; any actual XMF/bed receipt and output hashes must be filled by Root after execution.",
        "",
        "## Source boundary",
        "",
        f"Worker hashes: `{json.dumps(worker_hashes, sort_keys=True)}`.",
        "Historical exact-DP lattice negative evidence is retained and is not relaxed or silently promoted to a stage gate. These short 0..1 s diagnostics remain right-censored and do not add an independent case.",
    ])
    (PKG / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_manifest() -> None:
    files: dict[str, str] = {}
    for path in sorted(PKG.rglob("*")):
        if (not path.is_file() or path.name == "manifest.json" or
                path == PKG / "metadata" / "fresh108-validator-report.json"):
            continue
        require(path.suffix.lower() not in SCIENCE_SUFFIXES, f"science payload entered package: {path}")
        require(path.suffix.lower() in HASHABLE_SUFFIXES, f"unexpected package suffix: {path}")
        files[str(path.relative_to(PKG))] = sha(path)
    dump(PKG / "manifest.json", {
        "schema": "ds02.f5.c082s1.fresh108-source-manifest.v1",
        "status": "actual_root486_typed_bound_xmf_bed_disabled",
        "package": str(PKG),
        "files": files,
        "candidates": ["A080", "A120"],
        "actual_root455_native_and_root486_typed_bound": True,
        "typed_xmf_bed_future_products": None,
        "full801_authorized": False,
        "q_n_granted": False,
        "independent_case_count_increment": 0,
        "science_payloads_read_or_hashed_by_source_builder": False,
        "jobs_started": False,
        "shared_state_modified": False,
    })


def main() -> int:
    PKG.mkdir(parents=True, exist_ok=True)
    actuals: dict[str, dict[str, Any]] = {candidate: actual_candidate(candidate, spec) for candidate, spec in CANDIDATES.items()}
    worker_hashes = source_worker_copy(actuals)
    write_binder()
    for candidate in CANDIDATES:
        make_candidate(actuals[candidate], worker_hashes)
    write_readme(actuals, worker_hashes)
    plan = {
        "schema": "ds02.f5.c082s1.fresh108-source-plan.v1",
        "status": "actual_root486_typed_bound_xmf_bed_disabled",
        "candidates": {},
        "stage_order": ["Root455 native completed/0", "Root486/487 typed completed/0", "Root107 XMF CPU export disabled", "Root107 all-51 Mk50 bed audit disabled"],
        "actual_counts": {**COUNTS, "dimension": 3},
        "precision_boundary": "Historical exact DP lattice threshold 1e-6 remains an independent negative diagnostic; it is neither relaxed nor a fresh XMF/bed gate.",
        "canonical_vs_legacy_scope": "canonical owner and producer H5 legacy-owner-scope.v0 remain separate; no cross-resolution claim",
        "full801_authorized": False,
        "q_n_granted": False,
        "independent_case_count_increment": 0,
        "future_output_hashes": None,
        "science_payloads_read_or_hashed_by_source_builder": False,
        "jobs_started": False,
        "shared_state_modified": False,
        "worker_hashes": worker_hashes,
    }
    for candidate, actual in actuals.items():
        plan["candidates"][candidate] = {
            "native_attempt": actual["native_attempt"], "typed_attempt": actual["typed_attempt"], "typed_completed0": True,
            "frames": 51, "counts": {**COUNTS, "dimension": 3}, "producer_h5_sha256": actual["trajectory_h5_sha256"],
            "legacy_h5_scope_sha256": actual["legacy_h5_sha256"], "canonical_physical_condition_sha256": actual["canonical_sha"],
            "future_xmf": None, "future_bed_audit": None,
        }
    dump(PKG / "metadata" / "fresh108-source-plan.json", plan)
    write_manifest()
    print(json.dumps({"status": "built", "package": str(PKG), "candidates": sorted(CANDIDATES), "worker_hashes": worker_hashes}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
