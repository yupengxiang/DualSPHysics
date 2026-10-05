#!/usr/bin/env python3
"""Build the F5 fresh105 source-only downstream binding package.

This builder reads only JSON/XML/Python metadata and producer attestations.  It
never opens a BI4, H5, CSV, VTK, or DAT payload, and it never submits a task.
The two Root455 native receipts are real upstream metadata; every later
typed/XMF/bed product remains disabled and null until Root binds its producer.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any


PKG = Path(__file__).resolve().parents[1]
F5_TREE = Path("/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics")
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5")
CASE = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1"
SOURCE104 = F5_TREE / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_104_stage1_f5_c082s1_native_enable_source_v1"
SHORT_REQ_ROOT = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f5_actualQA441_Gen426_two_short51_native_455"
ROOT230 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_native_home_floor_eight_solver_dispatch_230"
RESOURCES = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json"
LAB = INTEGRATION / "lagrangian-fluid-lab"
SOLVER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64")
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
PARTVTK = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64")
PYTHON = LAB / ".venv/bin/python"
RUNTIME = LAB / "scripts/ds_data02_runtime_v2.py"
STRICT = LAB / "scripts/ds_data02_strict_dispatch_v1.py"
DIRECT = LAB / "scripts/ds_data02_direct_convert.py"
NVME = LAB / "scripts/ds_data02_nvme_convert_v1.py"
XMF_SOURCE = F5_TREE / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_079_stage1_f5_b071_post_conversion_pipeline_v1/workers/export_xmf_legacy_aware.py"
BED_SOURCE = F5_TREE / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_096_stage1_f5_c082s1_actual_typed_dynamic_adapter_v1/workers/bed_audit.py"

COUNTS = {
    "total": 194427,
    "fixed": 158559,
    "moving": 4210,
    "floating": 0,
    "fluid": 31658,
}
ROOT230_POLICY_SHA = "c9103e306f87bb5af871c5de28d9939aa05f0c95c72e1630778f4bcf50e91ab5"
ROOT142_POLICY_SHA = "2649eedbcf4816f8d2fa7b2182828ea8b3ce107ef47f25c56780d29c5138def5"
ROOT230_LAUNCH_SHA = "7f703fb94e17c2e2800873f4fcc021f9cd5f8201076afd8e10e3bc6a2d03396e"
DECODER_SHA = "b8ac8cf4aff68ffd089da6cf3ef19dfd0c6473121475f4c198b720a0ddaa8b2e"
PARTVTK_SHA = "62630430902484f4aede017108313673fe6414f40fb59b6ae7f14ac23219db00"
PYTHON_SHA = "a2f33a6e006989270f4340528eb61f8f97366e00a5d1b602ac8672ea44fc56ae"
SCIENCE_SUFFIXES = {".bi4", ".csv", ".h5", ".hdf5", ".vtk", ".vtu", ".npy", ".npz", ".dat"}
HASHABLE_SUFFIXES = {".json", ".py", ".xml", ".md", ".txt", ".log"}

CANDIDATES = {
    "A080": {
        "short_request": SHORT_REQ_ROOT / "C082S1_MOTION_A080-native-request.json",
        "physical_source": SOURCE104 / "bindings/A080-physical-binding.json",
        "definition_source": SOURCE104 / "inputs/A080-Definition.xml",
        "owner_source": SOURCE104 / "inputs/A080-owner.json",
        "condition_id": "F5_RUNUP_DP020_C082S1_MOTION_A080_099",
        "typed_attempt": "root-stage1-f5-c082s1-A080-short-native-typed-nvme-105",
        "xmf_attempt": "root-stage1-f5-c082s1-A080-short-native-xmf-105",
        "bed_attempt": "root-stage1-f5-c082s1-A080-short-dynamic-bed-audit-105",
    },
    "A120": {
        "short_request": SHORT_REQ_ROOT / "C082S1_MOTION_A120-native-request.json",
        "physical_source": SOURCE104 / "bindings/A120-physical-binding.json",
        "definition_source": SOURCE104 / "inputs/A120-Definition.xml",
        "owner_source": SOURCE104 / "inputs/A120-owner.json",
        "condition_id": "F5_RUNUP_DP020_C082S1_MOTION_A120_099",
        "typed_attempt": "root-stage1-f5-c082s1-A120-short-native-typed-nvme-105",
        "xmf_attempt": "root-stage1-f5-c082s1-A120-short-native-xmf-105",
        "bed_attempt": "root-stage1-f5-c082s1-A120-short-dynamic-bed-audit-105",
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
    require(path.suffix.lower() in HASHABLE_SUFFIXES, f"payload hash forbidden in source builder: {path}")
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def copy_source(src: Path, dst: Path) -> str:
    require(src.is_file(), f"missing source input: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    return sha(dst)


def receipt_identity(receipt: dict[str, Any]) -> dict[str, Any]:
    request = receipt.get("request")
    request = request if isinstance(request, dict) else {}
    return {
        "attempt_id": request.get("attempt_id") or receipt.get("attempt_id"),
        "case_id": request.get("case_id") or receipt.get("case_id"),
        "candidate_id": request.get("candidate_id"),
    }


def check_native(candidate: str, spec: dict[str, Any]) -> dict[str, Any]:
    request_path = spec["short_request"]
    request = load_json(request_path)
    require(request.get("schema") == "ds02.runner-request.v2", f"{candidate}: native request schema")
    require(request.get("kind") == "qualification" and request.get("cpu_task_kind") == "solver", f"{candidate}: native request kind")
    require(request.get("attempt_id") == f"root-stage1-f5-c082s1-{candidate}-short-native-qualification-104-root455", f"{candidate}: native attempt")
    require(request.get("case_id") == CASE, f"{candidate}: native case")
    require(request.get("expected_frames") == 51 and request.get("expected_dimension") == 3, f"{candidate}: native shape")
    require(request.get("expected_particles") == COUNTS["total"], f"{candidate}: native particle axis")
    for key in ("expected_fixed_particles", "expected_moving_particles", "expected_floating_particles", "expected_fluid_particles"):
        count_key = key.removeprefix("expected_").removesuffix("_particles")
        require(request.get(key) == COUNTS[count_key], f"{candidate}: native {key}")
    require(request.get("root_inventory_policy_source_sha256") == ROOT230_POLICY_SHA, f"{candidate}: native policy is not Root230")
    corrected = request.get("root_corrected_source_inventory_policy_sha256")
    require(isinstance(corrected, dict) and corrected.get("actual_native230") == ROOT230_POLICY_SHA and corrected.get("source_declared") == ROOT142_POLICY_SHA, f"{candidate}: policy correction provenance")
    receipt_path = DATA / CASE / request["attempt_id"] / "execution-receipt.json"
    require(receipt_path.is_file(), f"{candidate}: actual native receipt missing: {receipt_path}")
    receipt = load_json(receipt_path)
    require(receipt.get("schema") == "ds02.execution-receipt.v1", f"{candidate}: native receipt schema")
    require(receipt.get("status") == "completed" and int(receipt.get("returncode", -1)) == 0, f"{candidate}: native receipt not completed/0")
    nested = receipt.get("request")
    require(isinstance(nested, dict), f"{candidate}: native nested request missing")
    require(nested.get("attempt_id") == request["attempt_id"] and nested.get("case_id") == CASE, f"{candidate}: native receipt identity")
    require(receipt.get("output_root") == str(DATA / CASE / request["attempt_id"]), f"{candidate}: native output root")
    require(nested.get("expected_frames") == 51 and nested.get("expected_dimension") == 3, f"{candidate}: receipt shape")
    require(nested.get("actual_counts") == COUNTS | {"dimension": 3}, f"{candidate}: receipt actual counts")
    command = request.get("command")
    require(isinstance(command, list) and command[-3:] == ["-tmax:1.0", "-tout:0.02", "-ompthreads:2"], f"{candidate}: native command tail")
    return {
        "candidate": candidate,
        "actual_request_path": str(request_path),
        "actual_request_sha256": sha(request_path),
        "actual_receipt_path": str(receipt_path),
        "actual_receipt_sha256": sha(receipt_path),
        "attempt_id": request["attempt_id"],
        "case_id": CASE,
        "candidate_id": request.get("candidate_id"),
        "output_root": receipt["output_root"],
        "solver_output_root": str(Path(receipt["output_root"]) / "solver_output"),
        "solver_data_root": str(Path(receipt["output_root"]) / "solver_output" / "data"),
        "status": receipt["status"],
        "returncode": int(receipt["returncode"]),
        "production_product_acceptance": receipt.get("production_product_acceptance"),
        "expected_frames": 51,
        "expected_dimension": 3,
        "actual_counts": {**COUNTS, "dimension": 3},
        "gencase_attempt_id": request["gencase_attempt_id"],
        "gencase_receipt": request["gencase_receipt"],
        "gencase_receipt_sha256": request["gencase_receipt_sha256"],
        "prepared_input_report": request["prepared_input_report"],
        "prepared_input_report_sha256": request["prepared_input_report_sha256"],
        "generated_xml": request["generated_xml"],
        "generated_xml_sha256": request["generated_xml_sha256"],
        "generated_bi4": request["generated_bi4"],
        "generated_bi4_sha256": request["generated_bi4_sha256"],
        "initial_qa_report": request["actual_initial_qa_report"],
        "initial_qa_report_sha256": request["actual_initial_qa_report_sha256"],
        "initial_qa_receipt": request["actual_initial_qa_receipt"],
        "initial_qa_receipt_sha256": request["actual_initial_qa_receipt_sha256"],
        "motion_asset_path": request.get("motion_asset_path"),
        "motion_asset_sha256_producer_declared": request.get("motion_asset_sha256"),
        "root_inventory_policy_source_sha256": request["root_inventory_policy_source_sha256"],
        "root_corrected_source_inventory_policy_sha256": corrected,
        "root230_dispatch_provenance": request.get("root230_dispatch_provenance"),
        "request_future_output_hashes": request.get("future_output_hashes"),
        "native_saved_state_contract": {
            "expected_saved_frames": 51,
            "native_output_root_is_bound": True,
            "solver_data_directory_is_bound": True,
            "source_agent_did_not_open_solver_output": True,
            "root_must_verify_51_saved_Part_bi4_metadata_before_typed_enablement": True,
            "first_state_zero_velocity_qa": "pending Root registered product check",
        },
        "full801_authorized": False,
        "q_n_granted": False,
        "independent_case_count_increment": 0,
    }


def make_physical(candidate: str, spec: dict[str, Any]) -> dict[str, Any]:
    source = load_json(spec["physical_source"])
    # The older physical binding intentionally carried geometry only.  The
    # immutable GenCase binding is the source of the canonical owner and
    # source-plan hashes; copy those identities without opening any payload.
    gencase_source = load_json(SOURCE104 / f"bindings/{candidate}-gencase-binding.json")
    source["physical_condition_sha256"] = gencase_source["canonical_physical_condition_sha256"]
    source["source_plan_physical_condition_sha256"] = gencase_source["source_plan_physical_condition_sha256"]
    local = PKG / "bindings" / f"{candidate}-physical-binding.json"
    source["physical_binding_path"] = str(local)
    source["source_preparation"] = {
        "source_only": True,
        "science_payloads_read_or_hashed": False,
        "legacy_h5_scope_is_separate_from_canonical_owner": True,
    }
    dump(local, source)
    return source


def make_owner(candidate: str, physical: dict[str, Any], native: dict[str, Any]) -> dict[str, Any]:
    owner = {
        "schema": "ds02.f5.c082s1.conversion-owner-metadata.fresh105.v1",
        "candidate_id": f"C082S1_MOTION_{candidate}",
        "case_id": CASE,
        "physical_case_id": physical["physical_case_id"],
        "physical_condition_sha256": physical["physical_condition_sha256"],
        "source_plan_physical_condition_sha256": physical.get("source_plan_physical_condition_sha256", physical.get("parameters", {}).get("source_plan_physical_condition_sha256")),
        "source_h5_physical_condition_sha256": None,
        "physical_condition_hash_semantics": {
            "canonical_owner_sha256": physical["physical_condition_sha256"],
            "source_h5_scope_schema": "legacy-owner-scope.v0",
            "source_h5_scope_status": "legacy_incomplete; no cross-resolution physical claim",
            "cross_resolution_claim": False,
            "source_h5_sha256": None,
        },
        "native_identity": {**native["actual_counts"], "native_bed_mk": 50, "source_mkbound": 40, "fluid_type_code": 3},
        "mass_policy": physical.get("mass_policy", "native particle weights are authoritative; no rescale"),
        "solver_dimension": 3,
        "frames": 51,
        "window_s": [0.0, 1.0],
        "source_h5_read_only": True,
        "typed_h5_sha256": None,
        "arrays_read_or_hashed_by_source_agent": False,
        "native_receipt_path": native["actual_receipt_path"],
        "native_receipt_sha256": native["actual_receipt_sha256"],
        "native_first_state_zero_velocity_qa": "pending Root registered product check",
        "full801_authorized": False,
        "independent_case_count_increment": 0,
    }
    dump(PKG / "metadata" / f"{candidate}-conversion-owner.json", owner)
    return owner


def static_inputs(candidate: str, physical_path: Path, owner_path: Path, binding_path: Path,
                  native: dict[str, Any], extra: list[Path]) -> tuple[list[str], dict[str, str | None]]:
    local = [
        PKG / "inputs" / f"{candidate}-Definition.xml",
        PKG / "inputs" / f"{candidate}-owner.json",
        physical_path,
        owner_path,
        binding_path,
        PKG / "workers" / "initial_placement_mk50_audit.py",
        PKG / "workers" / "bed_audit.py",
        PKG / "workers" / "export_xmf_legacy_aware.py",
        PKG / "scripts" / "bind_downstream_products.py",
        PKG / "scripts" / "validate_fresh105.py",
        RUNTIME,
        STRICT,
        DIRECT,
        NVME,
        ROOT230 / "root_native_home_floor_inventory_policy.py",
        ROOT230 / "launch.py",
        RESOURCES,
        Path(native["actual_request_path"]),
        Path(native["actual_receipt_path"]),
        Path(native["gencase_receipt"]),
        Path(native["prepared_input_report"]),
        # XML and solver log are metadata/control inputs for the downstream
        # producer.  They are explicitly allowed source-text inputs; the
        # generated BI4 and solver data directory remain root-bound payloads.
        Path(native["generated_xml"]),
        Path(native["output_root"]) / "stdout.log",
        Path(native["initial_qa_receipt"]),
        Path(native["initial_qa_report"]),
    ] + extra
    files: list[str] = []
    hashes: dict[str, str | None] = {}
    for path in local:
        text = str(path)
        require(path.is_file(), f"missing static closure input: {path}")
        require(path.suffix.lower() in HASHABLE_SUFFIXES, f"non-source static input in source closure: {path}")
        files.append(text)
        hashes[text] = sha(path)
    # These producer-declared tools are needed by the eventual Root process;
    # the source worker intentionally does not open or hash executable bytes.
    for path, digest in ((PYTHON, PYTHON_SHA), (DECODER, DECODER_SHA), (PARTVTK, PARTVTK_SHA)):
        files.append(str(path))
        hashes[str(path)] = digest
    placeholders = [
        "<root-bind:solver_data_root>", "<root-bind:generated_xml>",
        "<root-bind:generated_bi4>", "<root-bind:trajectory_h5>",
        "<root-bind:conversion_report>", "<root-bind:partvtk_validation_dir>",
    ]
    files.extend(placeholders)
    hashes.update({item: None for item in placeholders})
    return sorted(set(files)), hashes


def root230(request: dict[str, Any]) -> dict[str, Any]:
    value = request.get("root230_dispatch_provenance", {})
    return {
        "entrypoint": str(ROOT230 / "launch.py"),
        "entrypoint_sha256": ROOT230_LAUNCH_SHA,
        "policy_source": str(ROOT230 / "root_native_home_floor_inventory_policy.py"),
        "policy_source_sha256": ROOT230_POLICY_SHA,
        "profile": "root_home_floor_no_legacy_dataset_walk_native_v1",
        "launch_owner": "root",
        "solver_kinds_only": ["qualification", "production"],
        "gpu_protection_required": True,
        "source_request_provenance": value,
    }


def common_disabled(candidate: str, native: dict[str, Any], physical: dict[str, Any],
                   owner_path: Path, binding_path: Path, attempt_id: str,
                   kind: str, cpu_task_kind: str, depends_on: str,
                   command: list[str], max_wall: int, storage: int,
                   files: list[str], hashes: dict[str, str | None]) -> dict[str, Any]:
    return {
        "schema": "ds02.runner-request.v2",
        "kind": kind,
        "cpu_task_kind": cpu_task_kind,
        "attempt_id": attempt_id,
        "candidate_id": f"C082S1_MOTION_{candidate}",
        "case_id": CASE,
        "family_id": "F5",
        "condition_id": CANDIDATES[candidate]["condition_id"],
        "physical_case_id": physical["physical_case_id"],
        "physical_binding_path": str(binding_path),
        "physical_binding_sha256": sha(binding_path),
        "physical_condition_sha256": physical["physical_condition_sha256"],
        "source_plan_physical_condition_sha256": physical.get("source_plan_physical_condition_sha256", physical.get("parameters", {}).get("source_plan_physical_condition_sha256")),
        "depends_on_attempt": depends_on,
        "gencase_attempt_id": native["gencase_attempt_id"],
        "native_attempt_id": native["attempt_id"],
        "native_receipt": native["actual_receipt_path"],
        "native_receipt_sha256": native["actual_receipt_sha256"],
        "command": command,
        "cwd": str(LAB),
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
        "max_wall_seconds": max_wall,
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
        "input_sha256_provenance": "source/Python/XML/JSON metadata only; producer-declared executable/tool and native output metadata; no BI4/H5/CSV/VTK/DAT payload read or hash by source preparation",
        "root_inventory_policy_source_sha256": ROOT230_POLICY_SHA,
        "root_corrected_source_inventory_policy_sha256": {
            "actual_native230": ROOT230_POLICY_SHA,
            "source_declared": ROOT142_POLICY_SHA,
        },
        "root230_dispatch_provenance": root230(load_json(Path(native["actual_request_path"]))),
        "resource_window": {
            "gpu_hours": 512, "cpu_core_hours": 3840, "qualification_attempts": 1024,
            "production_attempts": 720, "home_min_free_bytes": 536870912000,
            "deadline_utc": "2026-10-14T07:23:48+00:00", "launch_owner": "root",
        },
        "independent_case_count_increment": 0,
        "q_n_granted": False,
        "production_approval": "none",
        "full16_authorized": False,
        "full801_authorized": False,
        "future_output_hashes": {
            "typed_h5_sha256": None, "typed_receipt_sha256": None,
            "conversion_report_sha256": None, "xmf_manifest_sha256": None,
            "bed_audit_report_sha256": None,
        },
        "future_candidate_fields_remain_null": True,
        "old_attempt_modification_forbidden": True,
        "owner_metadata": str(owner_path),
    }


def make_binding(candidate: str, native: dict[str, Any], physical: dict[str, Any], owner_path: Path) -> Path:
    binding_path = PKG / "bindings" / f"{candidate}-short-pipeline-binding.json"
    binding = {
        "schema": "ds02.f5.c082s1.short-native-typed-xmf-bed-binding.fresh105.v1",
        "candidate_id": f"C082S1_MOTION_{candidate}",
        "case_id": CASE,
        "physical_case_id": physical["physical_case_id"],
        "condition_id": CANDIDATES[candidate]["condition_id"],
        "physical_binding_path": str(PKG / "bindings" / f"{candidate}-physical-binding.json"),
        "physical_binding_sha256": sha(PKG / "bindings" / f"{candidate}-physical-binding.json"),
        "physical_condition_sha256": physical["physical_condition_sha256"],
        "source_plan_physical_condition_sha256": physical.get("source_plan_physical_condition_sha256", physical.get("parameters", {}).get("source_plan_physical_condition_sha256")),
        "source_h5_physical_condition_sha256": None,
        "physical_condition_hash_semantics": {
            "canonical_owner_sha256": physical["physical_condition_sha256"],
            "source_h5_sha256": None,
            "source_h5_scope_schema": "legacy-owner-scope.v0",
            "source_h5_scope_status": "legacy_incomplete; no cross-resolution physical claim",
            "cross_resolution_claim": False,
        },
        "owner_metadata": str(owner_path),
        "owner_metadata_sha256": sha(owner_path),
        "gencase": {
            "attempt_id": native["gencase_attempt_id"], "receipt": native["gencase_receipt"],
            "receipt_sha256": native["gencase_receipt_sha256"], "prepared_report": native["prepared_input_report"],
            "prepared_report_sha256": native["prepared_input_report_sha256"], "generated_xml": native["generated_xml"],
            "generated_xml_sha256": native["generated_xml_sha256"], "generated_bi4": native["generated_bi4"],
            "generated_bi4_sha256": native["generated_bi4_sha256"], "actual_counts": native["actual_counts"],
            "solver_dimension": 3, "data2d": False,
        },
        "initial_qa": {
            "attempt_id": load_json(Path(native["initial_qa_receipt"])).get("request", {}).get("attempt_id"),
            "receipt": native["initial_qa_receipt"], "receipt_sha256": native["initial_qa_receipt_sha256"],
            "report": native["initial_qa_report"], "report_sha256": native["initial_qa_report_sha256"],
            "basic_placement_mk50_pass": True, "numerical_precision_result_accepted": False,
        },
        "native": {
            "attempt_id": native["attempt_id"], "receipt": native["actual_receipt_path"],
            "receipt_sha256": native["actual_receipt_sha256"], "output_root": native["output_root"],
            "solver_output_root": native["solver_output_root"], "solver_data_root": native["solver_data_root"],
            "expected_frames": 51, "actual_counts": native["actual_counts"], "solver_dimension": 3,
            "first_state_zero_velocity_qa": "pending Root registered product check",
            "saved_state_metadata_verification": "Root must verify actual 51 Part_*.bi4 before typed enablement",
        },
        "marker_mapping": {"source_mkbound": 40, "native_bed_mk": 50, "fluid_type_code": 3},
        "bed_profile": {
            "x_bounds_m": [-0.2, 4.8], "y_bounds_m": [-0.22, 0.22],
            "nodes_xz_m": [[-0.2, 0.0], [2.0, 0.0], [3.0, 0.28], [3.6, 0.448], [3.9, 0.448], [4.4, 0.05], [4.8, 0.05]],
        },
        "typed": {"attempt_id": CANDIDATES[candidate]["typed_attempt"], "report": None, "report_sha256": None, "receipt": None, "receipt_sha256": None, "trajectory_h5": None, "trajectory_h5_sha256": None},
        "xmf": {"attempt_id": CANDIDATES[candidate]["xmf_attempt"], "manifest": None, "manifest_sha256": None, "receipt": None, "receipt_sha256": None, "xmf": None, "xmf_sha256": None},
        "bed_audit": {"attempt_id": CANDIDATES[candidate]["bed_attempt"], "report": None, "report_sha256": None, "output_root": None},
        "stage_contract": {
            "all_51_saved_states_required": True, "all_initial_fluid_uids_full_denominator": True,
            "finite_uid_type_mk_mass_checks": True, "native_bed_marker_mk50": True,
            "penetration_bins_m": [0.02, 0.04], "thresholds_diagnostic_only": True,
            "dynamic_acceptance_not_inferred": True, "visual_review_required": True,
            "full801_authorized": False, "case_credit": False,
            "exact_dp_lattice_threshold": 1e-6, "exact_dp_lattice_is_independent_diagnostic": True,
        },
        "future_hashes": None,
        "source_agent_did_not_read_science_payloads": True,
    }
    dump(binding_path, binding)
    return binding_path


def make_requests(candidate: str, native: dict[str, Any], physical: dict[str, Any], owner_path: Path, binding_path: Path) -> None:
    local_worker = PKG / "workers"
    typed_files, typed_hashes = static_inputs(candidate, PKG / "bindings" / f"{candidate}-physical-binding.json", owner_path, binding_path, native, [PKG / "metadata" / f"{candidate}-root455-native-attestation.json"])
    typed_command = [
        str(PYTHON), str(NVME), "--staging-root", "/tmp/ds02-nvme-conversion", "--staging-limit-bytes", "25769803776", "--",
        "--data-root", native["solver_data_root"], "--generated-xml", native["generated_xml"],
        "--output", "{attempt_root}/typed/trajectory.h5", "--report", "{attempt_root}/typed/conversion-report.json",
        "--decoder", str(DECODER), "--partvtk", str(PARTVTK), "--validation-dir", "{attempt_root}/typed/partvtk-validation",
        "--solver-log", str(Path(native["output_root"]) / "stdout.log"), "--solver-receipt", native["actual_receipt_path"],
        "--gencase-receipt", native["gencase_receipt"], "--owner-metadata", str(owner_path), "--particle-chunk", "65536",
    ]
    typed = common_disabled(candidate, native, physical, owner_path, binding_path, CANDIDATES[candidate]["typed_attempt"], "cpu", "conversion", native["attempt_id"], typed_command, 3600, 17179869184, typed_files, typed_hashes)
    typed.update({
        "conversion_contract": {
            "all_51_saved_states_required": True, "all_actual_counts_from_gencase_and_report": True,
            "canonical_condition_separate_from_legacy_h5_scope": True, "mass_report_without_rescale": True,
            "native_mk50_bed_mapping_preserved": True, "solver_dimension_required": 3,
            "source_h5_read_only": True, "source_native_identity_preserved": True,
        },
        "nvme_policy": {"concurrency": 2, "free_space_floor_bytes": 107374182400, "peak_staging_bytes": 25769803776, "staging_root": "/tmp/ds02-nvme-conversion", "particle_chunk": 65536, "source_h5_copy_policy": "read-only producer output; no source mutation"},
        "producer_report_contract": {"report_schema": "ds-data-02.bi4-direct-conversion.v1", "producer_h5_digest_field": "output_sha256", "solver_dimension_field_shape": "evidence_object", "solver_dimension_required_fields": ["solver_dimension", "run_out_dimensions", "xml_data2d"], "typed_identity_source": "producer report typed_identity blocks/observed_mks/observed_types", "all_51_lifecycle_source": "producer report and PartVTK metadata"},
        "future_bindings": {"conversion_report": None, "output_hdf5": None, "typed_receipt": None, "xmf_manifest": None, "bed_report": None},
        "native_saved_state_metadata": native["native_saved_state_contract"],
        "source_h5_physical_condition_sha256": None,
        "canonical_legacy_scope_sidecar": "Root must bind producer H5 legacy scope separately; canonical physical owner remains the local binding value",
    })
    dump(PKG / "requests" / f"{candidate}-typed-nvme-request.json", typed)

    xmf_binding = {
        "schema": "ds02.f5.c082s1.legacy-aware-xmf-binding.fresh105.v1",
        "candidate_id": f"C082S1_MOTION_{candidate}", "case_id": CASE, "physical_case_id": physical["physical_case_id"],
        "physical_condition_sha256": physical["physical_condition_sha256"], "source_plan_physical_condition_sha256": typed["source_plan_physical_condition_sha256"],
        "source_h5_physical_condition_sha256": None, "source_h5_scope_schema": "legacy-owner-scope.v0", "source_h5_scope_status": "legacy_incomplete; no cross-resolution physical claim",
        "physical_condition_hash_semantics": {"canonical_owner_sha256": physical["physical_condition_sha256"], "source_h5_sha256": None, "source_h5_scope_schema": "legacy-owner-scope.v0", "source_h5_scope_status": "legacy_incomplete; no cross-resolution physical claim", "cross_resolution_claim": False},
        "native_receipt": native["actual_receipt_path"], "native_receipt_sha256": native["actual_receipt_sha256"], "typed_receipt": None, "conversion_report": None,
        "trajectory_h5": None, "expected_frames": 51, "expected_particles": COUNTS["total"], "physical_window_s": [0.0, 1.0], "native_fields_preserved": True,
        "source_h5_read_only": True, "full801_authorized": False, "visual_status": "pending Root visual review", "future_output_hashes": None,
        "source_agent_did_not_read_science_payloads": True,
    }
    xmf_binding_path = PKG / "bindings" / f"{candidate}-short-xmf-binding.json"
    dump(xmf_binding_path, xmf_binding)
    xmf_files, xmf_hashes = static_inputs(candidate, PKG / "bindings" / f"{candidate}-physical-binding.json", owner_path, xmf_binding_path, native, [local_worker / "export_xmf_legacy_aware.py", PKG / "metadata" / f"{candidate}-root455-native-attestation.json"])
    xmf = common_disabled(candidate, native, physical, owner_path, xmf_binding_path, CANDIDATES[candidate]["xmf_attempt"], "cpu", "xmf_export", CANDIDATES[candidate]["typed_attempt"], [str(PYTHON), str(local_worker / "export_xmf_legacy_aware.py"), "--binding", str(xmf_binding_path), "--output-dir", "{attempt_root}/xmf"], 1800, 4294967296, xmf_files, xmf_hashes)
    xmf.update({"binding": str(xmf_binding_path), "binding_sha256": sha(xmf_binding_path), "typed_attempt_id": CANDIDATES[candidate]["typed_attempt"], "typed_receipt": None, "conversion_report": None, "trajectory_h5": None, "xmf_manifest": None, "derived_view_only": True, "canonical_condition_separate_from_source_h5": True, "future_bindings": {"typed_receipt": None, "conversion_report": None, "trajectory_h5": None, "xmf_manifest": None, "xmf_receipt": None}, "future_output_hashes": {"xmf_manifest_sha256": None, "xmf_sha256": None}})
    dump(PKG / "requests" / f"{candidate}-xmf-request.json", xmf)

    bed_binding_path = PKG / "bindings" / f"{candidate}-short-bed-audit-binding.json"
    bed_binding = {
        "schema": "ds02.f5.c082s1.short-dynamic-bed-audit-binding.fresh105.v1", "candidate_id": f"C082S1_MOTION_{candidate}", "case_id": CASE, "physical_case_id": physical["physical_case_id"],
        "physical_condition_sha256": physical["physical_condition_sha256"], "source_plan_physical_condition_sha256": typed["source_plan_physical_condition_sha256"],
        "physical_binding_path": str(binding_path), "physical_binding_sha256": sha(binding_path), "canonical_generated_xml": native["generated_xml"], "canonical_generated_xml_sha256": native["generated_xml_sha256"],
        "gencase_attempt_id": native["gencase_attempt_id"], "gencase_receipt": native["gencase_receipt"], "gencase_receipt_sha256": native["gencase_receipt_sha256"], "gencase_prepared_report": native["prepared_input_report"], "gencase_prepared_report_sha256": native["prepared_input_report_sha256"],
        "gencase_output_root": str(Path(native["gencase_receipt"]).parent), "gencase_prepared_output_root": str(Path(native["generated_xml"]).parent),
        "initial_qa_receipt": native["initial_qa_receipt"], "initial_qa_receipt_sha256": native["initial_qa_receipt_sha256"], "initial_qa_report": native["initial_qa_report"], "initial_qa_report_sha256": native["initial_qa_report_sha256"],
        "initial_qa_output_root": str(Path(native["initial_qa_receipt"]).parent), "expected_frames": 51, "expected_dimension": 3, "expected_particle_axis": COUNTS["total"], "expected_particles": COUNTS["total"], "expected_fixed_particles": COUNTS["fixed"], "expected_moving_particles": COUNTS["moving"], "expected_floating_particles": COUNTS["floating"], "expected_fluid_particles": COUNTS["fluid"],
        "short_native_attempt_id": native["attempt_id"], "short_solver_receipt": native["actual_receipt_path"], "short_solver_receipt_sha256": native["actual_receipt_sha256"], "short_solver_output_root": native["solver_output_root"],
        "short_saved_state_metadata": {"all_51_saved_states": None, "saved_state_count": None, "saved_state_filenames": None, "path": "<root-bind:short_saved_state_metadata>"},
        "typed_conversion_attempt_id": CANDIDATES[candidate]["typed_attempt"], "typed_conversion_report": None, "typed_conversion_report_sha256": None, "typed_h5": None, "typed_h5_sha256": None, "typed_receipt": None, "typed_receipt_sha256": None, "xmf_attempt_id": CANDIDATES[candidate]["xmf_attempt"], "xmf": None, "xmf_manifest": None, "xmf_manifest_sha256": None, "xmf_sha256": None,
        "profile": {"nodes_xz_m": [[-0.2, 0.0], [2.0, 0.0], [3.0, 0.28], [3.6, 0.448], [3.9, 0.448], [4.4, 0.05], [4.8, 0.05]], "x_bounds_m": [-0.2, 4.8], "y_bounds_m": [-0.22, 0.22]},
        "source_marker_mapping": {"source_mkbound": 40, "native_bed_mk": 50, "fluid_type_code": 3}, "penetration_bins_m": [0.02, 0.04], "nominal_save_interval_s": 0.02, "time_window_s": [0.0, 1.0],
        "future_inputs": {"typed_h5": None, "typed_receipt": None, "conversion_report": None, "xmf": None, "xmf_manifest": None, "audit_report_sha256": None}, "future_output_hashes": {"typed_h5_sha256": None, "xmf_manifest_sha256": None, "audit_report_sha256": None},
        "diagnostic_only": True, "dynamic_acceptance": "not granted; Root reviews every frame and visual render", "full801_authorized": False, "case_credit": False,
        "worker_contract": {"worker_source": "workers/bed_audit.py", "worker_source_sha256": sha(BED_SOURCE), "all_51_saved_states": True, "full_initial_fluid_uid_denominator": True, "missing_uid_and_nonfinite_per_frame": True, "one_dp_two_dp_counts_fractions_depths": True, "thresholds_diagnostic_only": True, "dynamic_acceptance_not_inferred": True, "native_bed_marker_mk50_source_mkbound40": True, "exact_profile_and_y_footprint": True},
        "source_agent_did_not_read_science_payloads": True,
    }
    dump(bed_binding_path, bed_binding)
    bed_files, bed_hashes = static_inputs(candidate, PKG / "bindings" / f"{candidate}-physical-binding.json", owner_path, bed_binding_path, native, [PKG / "workers" / "bed_audit.py", PKG / "metadata" / f"{candidate}-root455-native-attestation.json"])
    bed = common_disabled(candidate, native, physical, owner_path, bed_binding_path, CANDIDATES[candidate]["bed_attempt"], "cpu", "audit", CANDIDATES[candidate]["xmf_attempt"], [str(PYTHON), str(local_worker / "bed_audit.py"), "--binding", str(bed_binding_path), "--trajectory-h5", "<root-bind:trajectory_h5>", "--xdmf", "<root-bind:xmf>", "--output-dir", "{attempt_root}/audit-output"], 3600, 4294967296, bed_files, bed_hashes)
    bed.update({"binding": str(bed_binding_path), "binding_sha256": sha(bed_binding_path), "typed_attempt_id": CANDIDATES[candidate]["typed_attempt"], "xmf_attempt_id": CANDIDATES[candidate]["xmf_attempt"], "diagnostic_only": True, "dynamic_acceptance": "not granted; Root reviews all 51 frames and visual render", "penetration_bins_m": [0.02, 0.04], "bed_x_bounds_m": [-0.2, 4.8], "bed_y_bounds_m": [-0.22, 0.22], "future_output_hashes": {"audit_report_sha256": None, "typed_h5_sha256": None, "xmf_manifest_sha256": None}})
    dump(PKG / "requests" / f"{candidate}-bed-audit-request.json", bed)


def main() -> int:
    PKG.mkdir(parents=True, exist_ok=True)
    copied = {
        "xmf_worker_sha256": copy_source(XMF_SOURCE, PKG / "workers" / "export_xmf_legacy_aware.py"),
        "bed_worker_sha256": copy_source(BED_SOURCE, PKG / "workers" / "bed_audit.py"),
    }
    for candidate, spec in CANDIDATES.items():
        native = check_native(candidate, spec)
        physical = make_physical(candidate, spec)
        owner_path = PKG / "metadata" / f"{candidate}-conversion-owner.json"
        make_owner(candidate, physical, native)
        binding_path = make_binding(candidate, native, physical, owner_path)
        # The attestation is deliberately a filtered JSON metadata record; it
        # never copies receipt input-hash maps or any payload digest itself.
        attestation = {
            "schema": "ds02.f5.c082s1.root455-native-attestation.fresh105.v1",
            "candidate": candidate, "case_id": CASE, "source_only": True,
            "actual_request": {k: native[k] for k in ("actual_request_path", "actual_request_sha256", "attempt_id", "gencase_attempt_id", "generated_xml", "generated_xml_sha256", "generated_bi4_sha256", "actual_counts", "expected_frames", "expected_dimension", "root_inventory_policy_source_sha256", "root_corrected_source_inventory_policy_sha256")},
            "actual_receipt": {k: native[k] for k in ("actual_receipt_path", "actual_receipt_sha256", "status", "returncode", "output_root", "production_product_acceptance")},
            "native_saved_state_contract": native["native_saved_state_contract"],
            "actual_initial_qa": {k: native[k] for k in ("initial_qa_report", "initial_qa_report_sha256", "initial_qa_receipt", "initial_qa_receipt_sha256")},
            "producer_attested_motion": {"path": native["motion_asset_path"], "sha256": native["motion_asset_sha256_producer_declared"]},
            "actual_counts": native["actual_counts"],
            "full801_authorized": False, "q_n_granted": False, "independent_case_count_increment": 0,
            "historical_exact_dp_lattice_negative_retained": True,
            "science_payloads_read_or_hashed_by_source_agent": False,
            "future_products": {"typed": None, "xmf": None, "bed_audit": None},
            "source_worker_provenance": copied,
        }
        dump(PKG / "metadata" / f"{candidate}-root455-native-attestation.json", attestation)
        make_requests(candidate, native, physical, owner_path, binding_path)
    dump(PKG / "metadata" / "fresh105-source-plan.json", {
        "schema": "ds02.f5.c082s1.fresh105-source-plan.v1", "status": "root455_native_bound_downstream_disabled", "candidates": sorted(CANDIDATES),
        "native": {candidate: {"attempt_id": check_native(candidate, CANDIDATES[candidate])["attempt_id"], "completed0": True, "frames": 51, "counts": {**COUNTS, "dimension": 3}} for candidate in CANDIDATES},
        "stage_order": ["Root455 short native actual", "typed NVMe conversion", "legacy-aware XMF", "all-51-frame Mk50 bed diagnostic"],
        "typed_xmf_bed_enabled": False, "full801_authorized": False, "q_n_granted": False, "independent_case_count_increment": 0,
        "precision_boundary": "The exact DP lattice 1e-6 negative remains an independent numerical diagnostic; it is neither relaxed nor silently used as a stage1 gate.",
        "future_output_hashes": None, "science_payloads_read_or_hashed_by_source_agent": False, "jobs_started": False, "shared_state_modified": False,
        "worker_hashes": copied,
    })
    print(json.dumps({"status": "built", "package": str(PKG), "candidates": sorted(CANDIDATES), "worker_hashes": copied}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
