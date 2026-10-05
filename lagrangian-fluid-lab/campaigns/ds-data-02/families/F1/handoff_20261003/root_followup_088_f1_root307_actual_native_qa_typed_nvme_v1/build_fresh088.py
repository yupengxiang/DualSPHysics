#!/usr/bin/env python3
"""Build the F1 fresh088 Root307-to-typed-NVMe source handoff.

This source-only builder reads JSON/XML/text metadata and executable metadata.
It does not open, copy, or hash BI4/H5/CSV/VTK scientific arrays, and never
launches GenCase, solver, conversion, or rendering work.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

F1 = Path("/home/jade/.codex/worktrees/ds-data-02-f1/DualSPHysics")
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1")
SOURCE087 = F1 / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F1/handoff_20261003/root_followup_087_f1_root298_actual_gencase_qa_native_bind_v1"
ROOT298 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f1_gencase_qa_path_type_repair_298"
ROOT299 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f1_actualGenQA298_eight_full_native_299"
ROOT307 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f1_actual_native299_frame0_qa_307"
ROOT230 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_native_home_floor_eight_solver_dispatch_230"
GPU_POLICY = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f3_first24_eight_solver_resource_policy_134/ds02_root_all_idle_gpu_policy_v2.py"
RESOURCE = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json"
RUNTIME = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
STRICT = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py"
GOAL = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/GOAL_STAGE1_VISUAL_GPT56LUNA_20261004_ZH.md"
PYTHON = INTEGRATION / "lagrangian-fluid-lab/.venv/bin/python"
CONVERTER = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_nvme_convert_v1.py"
DIRECT_CONVERTER = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_direct_convert.py"
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
PARTVTK = INTEGRATION / "lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64"
PACKAGE = F1 / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F1/handoff_20261003/root_followup_088_f1_root307_actual_native_qa_typed_nvme_v1"
CASES = [
    "F1_STAGE1_DUAL_H240_DP020",
    "F1_STAGE1_DUAL_H240_DP020_VX010",
    "F1_STAGE1_DUAL_H280_DP020",
    "F1_STAGE1_DUAL_H320_DP020",
    "F1_STAGE1_ECC_H120_DP010",
    "F1_STAGE1_ECC_H140_DP010",
    "F1_STAGE1_ECC_H160_DP010",
    "F1_STAGE1_ECC_H180_DP010",
]


def ensure(condition: object, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def load(path: Path) -> dict:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    ensure(isinstance(value, dict), f"expected JSON object: {path}")
    return value


def sha(path: Path) -> str:
    path = Path(path)
    if path.suffix.lower() in {".bi4", ".h5", ".hdf5", ".csv", ".vtk", ".npy", ".npz"}:
        raise RuntimeError(f"scientific-array read/hash forbidden: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def write_json(relative: str, value: object) -> Path:
    path = PACKAGE / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def copy_file(source: Path, relative: str) -> Path:
    source = Path(source)
    ensure(source.is_file(), f"source file missing: {source}")
    destination = PACKAGE / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination


def safe_input(path: Path) -> Path:
    path = Path(path)
    ensure(path.is_file(), f"required input missing: {path}")
    ensure(path.suffix.lower() not in {".bi4", ".h5", ".hdf5", ".csv", ".vtk", ".npy", ".npz"}, f"scientific input cannot be registered: {path}")
    return path


def actual_gencase_qa(case: str) -> dict:
    old = load(SOURCE087 / "actual-gencase-qa-bindings" / f"{case}.json")
    request = Path(old["actual_request"])
    receipt = Path(old["actual_receipt"])
    report = Path(old["actual_report"])
    ensure(request.is_file() and receipt.is_file() and report.is_file(), f"Root298 evidence missing for {case}")
    receipt_data = load(receipt)
    report_data = load(report)
    row = report_data.get("cases")
    ensure(receipt_data.get("status") == "completed" and receipt_data.get("returncode") == 0, f"Root298 not completed/0: {case}")
    ensure(receipt_data.get("request_sha256") == sha(request), f"Root298 request/receipt hash mismatch: {case}")
    ensure(report_data.get("schema") == "ds02.f1.gencase-initial-qa.v1" or str(report_data.get("schema", "")).endswith("gencase-initial-qa.v1"), f"Root298 report schema mismatch: {case}")
    ensure(isinstance(row, list) and len(row) == 1 and row[0].get("passed") is True, f"Root298 QA not passed: {case}")
    command = request_data = load(request).get("command", [])
    worker = Path(command[1]) if len(command) > 1 else None
    ensure(worker is not None and worker.is_file(), f"Root298 QA worker missing: {case}")
    return {
        "case": case,
        "attempt_id": old["actual_attempt_id"],
        "request": str(request),
        "request_sha256": sha(request),
        "receipt": str(receipt),
        "receipt_sha256": sha(receipt),
        "report": str(report),
        "report_sha256": sha(report),
        "receipt_data": receipt_data,
        "report_data": report_data,
        "row": row[0],
        "worker": str(worker),
        "worker_sha256": sha(worker),
        "gencase_receipt": old["gencase_receipt"],
        "gencase_receipt_sha256": old["gencase_receipt_sha256"],
        "generated_xml": old["generated_xml"],
        "generated_xml_sha256": old["generated_xml_sha256"],
        "prepared_input_report": old["prepared_input_report"],
        "prepared_input_report_sha256": old["prepared_input_report_sha256"],
        "gencase_attempt_id": old["gencase_attempt_id"],
    }


def actual_native(case: str) -> dict:
    old = load(SOURCE087 / "actual-native-bindings" / f"{case}.json")
    request_path = Path(old["actual_request"])
    receipt_path = Path(old["actual_receipt"])
    run_out = Path(old["actual_solver_log"])
    ensure(request_path.is_file() and receipt_path.is_file() and run_out.is_file(), f"Root299 evidence missing for {case}")
    request = load(request_path)
    receipt = load(receipt_path)
    ensure(receipt.get("status") == "completed" and receipt.get("returncode") == 0, f"Root299 not completed/0: {case}")
    ensure(receipt.get("request_sha256") == sha(request_path), f"Root299 request/receipt hash mismatch: {case}")
    expected = int(old["expected_frame_count"])
    ensure(int(old["observed_frame_file_count"]) == expected, f"Root299 frame inventory mismatch: {case}")
    return {
        "case": case,
        "attempt_id": old["actual_attempt_id"],
        "request": str(request_path),
        "request_sha256": sha(request_path),
        "request_data": request,
        "receipt": str(receipt_path),
        "receipt_sha256": sha(receipt_path),
        "receipt_data": receipt,
        "run_out": str(run_out),
        "run_out_sha256": sha(run_out),
        "data_root": old["actual_native_data_root"],
        "output_root": old["actual_output_root"],
        "expected_frames": expected,
        "observed_frame_file_count": int(old["observed_frame_file_count"]),
        "solver_command": old["root299_actual_solver_command"],
        "request_command": old["root299_request_command"],
        "termination_reason": old.get("actual_receipt_termination_reason"),
    }


def actual_frame0(case: str) -> dict:
    request_path = ROOT307 / f"{case}-native-frame0-qa-request.json"
    request = load(request_path)
    attempt = request.get("attempt_id")
    ensure(isinstance(attempt, str) and attempt, f"Root307 attempt missing: {case}")
    root = DATA / case / attempt
    receipt_path = root / "execution-receipt.json"
    report_path = root / "audit/native-initial-height-audit.json"
    ensure(receipt_path.is_file() and report_path.is_file(), f"Root307 output missing: {case}")
    receipt = load(receipt_path)
    report = load(report_path)
    rows = report.get("cases")
    ensure(receipt.get("status") == "completed" and receipt.get("returncode") == 0, f"Root307 not completed/0: {case}")
    ensure(receipt.get("request_sha256") == sha(request_path), f"Root307 request/receipt hash mismatch: {case}")
    ensure(isinstance(rows, list) and len(rows) == 1 and rows[0].get("passed") is True, f"Root307 QA not passed: {case}")
    row = rows[0]
    ensure(row.get("max_abs_velocity_error_m_per_s") == 0.0, f"Root307 velocity error is not zero: {case}")
    command = request.get("command", [])
    worker = Path(command[1]) if len(command) > 1 else None
    ensure(worker is not None and worker.is_file(), f"Root307 worker missing: {case}")
    return {
        "case": case,
        "attempt_id": attempt,
        "request": str(request_path),
        "request_sha256": sha(request_path),
        "request_data": request,
        "receipt": str(receipt_path),
        "receipt_sha256": sha(receipt_path),
        "receipt_data": receipt,
        "report": str(report_path),
        "report_sha256": sha(report_path),
        "report_data": report,
        "row": row,
        "worker": str(worker),
        "worker_sha256": sha(worker),
        "output_root": str(root),
    }


def dispatch() -> dict:
    old = load(SOURCE087 / "metadata/root230-policy.json")
    return old["dispatch"]


def typed_owner(case: str, canonical_path: Path, canonical: dict, gqa: dict, native: dict, frame: dict, source_definition: Path, source_plan: Path) -> tuple[dict, Path]:
    owner = {
        "schema": "ds02.f1.fresh088.actual-root307-typed-owner.v1",
        "family_id": "F1",
        "fresh_id": "fresh088",
        "case_id": case,
        "scope_id": "F1_STAGE1_FIRST24_HEIGHT_EXTENSION_V1",
        "canonical_owner": str(canonical_path),
        "canonical_owner_sha256": sha(canonical_path),
        "physical_case_id": canonical["physical_case_id"],
        "physical_condition_sha256": canonical["physical_condition_sha256"],
        "source_plan_condition_sha256": canonical.get("source_plan_condition_sha256"),
        "physical_binding": canonical["physical_binding"],
        "canonical_physical_binding_sha256": canonical_sha(canonical["physical_binding"]),
        "source_definition": str(source_definition),
        "source_definition_sha256": sha(source_definition),
        "source_plan": str(source_plan),
        "source_plan_sha256": sha(source_plan),
        "actual_gencase": {
            "attempt_id": canonical["actual_gencase"]["attempt_id"],
            "receipt": canonical["actual_gencase"]["receipt"],
            "receipt_sha256": canonical["actual_gencase"]["receipt_sha256"],
            "generated_xml": canonical["actual_gencase"]["generated_xml"],
            "generated_xml_sha256": canonical["actual_gencase"]["generated_xml_sha256"],
            "prepared_input_report": canonical["actual_gencase"]["prepared_input_report"],
            "prepared_input_report_sha256": canonical["actual_gencase"]["prepared_input_report_sha256"],
            "status": "completed/0",
            "solver_dimension": 3,
        },
        "actual_gencase_initial_qa": {
            "attempt_id": gqa["attempt_id"], "request": gqa["request"], "request_sha256": gqa["request_sha256"],
            "receipt": gqa["receipt"], "receipt_sha256": gqa["receipt_sha256"], "report": gqa["report"], "report_sha256": gqa["report_sha256"],
            "status": "completed/0", "passed": True, "actual_counts": gqa["row"].get("actual_particle_counts", gqa["row"].get("actual_particle_counts")),
        },
        "actual_native": {
            "attempt_id": native["attempt_id"], "request": native["request"], "request_sha256": native["request_sha256"],
            "receipt": native["receipt"], "receipt_sha256": native["receipt_sha256"], "status": "completed/0", "expected_frames": native["expected_frames"],
            "observed_frame_file_count": native["observed_frame_file_count"], "data_root": native["data_root"], "run_out": native["run_out"], "run_out_sha256": native["run_out_sha256"],
            "solver_command": native["solver_command"], "numerical_recipe": native["request_data"].get("numerical_recipe"),
        },
        "actual_native_frame0_qa": {
            "attempt_id": frame["attempt_id"], "request": frame["request"], "request_sha256": frame["request_sha256"],
            "receipt": frame["receipt"], "receipt_sha256": frame["receipt_sha256"], "report": frame["report"], "report_sha256": frame["report_sha256"],
            "status": "completed/0", "passed": True, "native_rows": frame["row"]["native_rows"],
            "actual_particle_counts": frame["row"]["actual_particle_counts"], "actual_total_particles": frame["row"]["actual_total_particles"],
            "native_frame0_bi4_sha256": frame["row"]["native_frame0_bi4_sha256_after_partvtk"],
            "native_frame0_bi4_sha256_before_partvtk": frame["row"]["native_frame0_bi4_sha256_before_partvtk"],
            "native_frame0_bi4_sha256_after_partvtk": frame["row"]["native_frame0_bi4_sha256_after_partvtk"],
            "max_abs_velocity_error_m_per_s": frame["row"]["max_abs_velocity_error_m_per_s"],
        },
        "legacy_h5_physical_condition_scope": {
            "schema": "legacy-owner-scope.v0",
            "status": "deferred_until_actual_converter_report",
            "physical_case_id": canonical["physical_case_id"],
            "legacy_h5_physical_condition_sha256": None,
            "semantic_note": "Legacy H5/report scope is separate from canonical physical_binding and is not asserted by source metadata.",
        },
        "typed_status": "prospective_disabled_until_root_conversion",
        "future_hashes_null": True,
        "raw_scientific_arrays_read_by_builder": False,
        "mass_rescale": False,
        "q_n": "not_assessed",
        "production_approval": "none",
        "source_only": True,
        "execution_allowed": False,
        "launch_allowed": False,
        "status": "root307_actual_native_frame0_qa_completed_zero_typed_pending",
    }
    path = PACKAGE / "owners" / f"{case}.typed-owner.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(owner, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return owner, path


def typed_binding(case: str, owner: dict, owner_path: Path, canonical_path: Path, gqa: dict, native: dict, frame: dict, source_definition: Path, source_plan: Path) -> tuple[dict, Path, Path]:
    slug = case.lower()
    output_root = DATA / case / f"root-stage1-f1-{slug}-full-native-typed-nvme-088"
    binding_path = PACKAGE / "bindings" / f"{case}.typed-nvme-binding.json"
    binding = {
        "schema": "ds02.f1.fresh088.actual-root307-native-frame0-typed-binding.v1",
        "family_id": "F1", "fresh_id": "fresh088", "case_id": case, "scope_id": "F1_STAGE1_FIRST24_HEIGHT_EXTENSION_V1",
        "canonical_owner": str(canonical_path), "canonical_owner_sha256": sha(canonical_path),
        "typed_owner": str(owner_path), "typed_owner_sha256": sha(owner_path),
        "canonical_physical_binding_sha256": owner["canonical_physical_binding_sha256"],
        "physical_case_id": owner["physical_case_id"], "physical_condition_sha256": owner["physical_condition_sha256"],
        "source_plan_condition_sha256": owner["source_plan_condition_sha256"],
        "source_definition": str(source_definition), "source_definition_sha256": sha(source_definition),
        "source_plan": str(source_plan), "source_plan_sha256": sha(source_plan),
        "generated_xml": owner["actual_gencase"]["generated_xml"], "generated_xml_sha256": owner["actual_gencase"]["generated_xml_sha256"],
        "actual_gencase_receipt": owner["actual_gencase"]["receipt"], "actual_gencase_receipt_sha256": owner["actual_gencase"]["receipt_sha256"],
        "actual_gencase_report": owner["actual_gencase"]["prepared_input_report"], "actual_gencase_report_sha256": owner["actual_gencase"]["prepared_input_report_sha256"],
        "actual_gencase_initial_qa": owner["actual_gencase_initial_qa"],
        "actual_native_receipt": native["receipt"], "actual_native_receipt_sha256": native["receipt_sha256"],
        "actual_native_attempt_id": native["attempt_id"], "actual_native_data_root": native["data_root"],
        "actual_native_expected_frames": native["expected_frames"], "actual_native_observed_frame_file_count": native["observed_frame_file_count"],
        "actual_native_receipt_status": "completed/0",
        "actual_native_frame0_qa": owner["actual_native_frame0_qa"],
        "typed_output_root": str(output_root), "typed_output_h5": str(output_root / "trajectory.h5"),
        "typed_conversion_report": str(output_root / "conversion-report.json"), "typed_execution_receipt": str(output_root / "execution-receipt.json"),
        "typed_output_sha256": None, "typed_conversion_report_sha256": None, "typed_execution_receipt_sha256": None,
        "legacy_h5_physical_condition_scope": owner["legacy_h5_physical_condition_scope"], "legacy_h5_physical_condition_sha256": None,
        "expected_frames": native["expected_frames"], "expected_particles": frame["row"]["actual_total_particles"], "expected_dimension": 3,
        "actual_particle_counts": frame["row"]["actual_particle_counts"],
        "full_time_window_s": float(native["request_data"]["expected_output"]["full_window_s"]),
        "save_interval_s": float(native["request_data"]["expected_output"]["save_interval_s"]),
        "native_frame0_bi4_sha256": frame["row"]["native_frame0_bi4_sha256_after_partvtk"],
        "max_abs_velocity_error_m_per_s": frame["row"]["max_abs_velocity_error_m_per_s"],
        "typed_status": "pending_root_conversion", "future_hashes_null": True,
        "raw_arrays_read": False, "mass_rescale": False, "independent_case_count_increment": 0,
        "q_n": "not_assessed", "production_approval": "none", "source_only": True,
        "execution_allowed": False, "launch_allowed": False,
        "status": "source_only_disabled_waiting_root_typed_conversion",
    }
    binding_path.parent.mkdir(parents=True, exist_ok=True)
    binding_path.write_text(json.dumps(binding, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return binding, binding_path, output_root


def typed_request(case: str, owner: dict, owner_path: Path, canonical_path: Path, binding: dict, binding_path: Path, gqa: dict, native: dict, frame: dict, source_definition: Path, source_plan: Path, gencase_binding: Path) -> Path:
    slug = case.lower()
    output_root = Path(binding["typed_output_root"])
    attempt = f"root-stage1-f1-{slug}-full-native-typed-nvme-088"
    command = [
        str(PYTHON), str(CONVERTER), "--staging-root", "/tmp/ds02-nvme-conversion", "--staging-limit-bytes", "25769803776", "--",
        "--data-root", native["data_root"], "--generated-xml", owner["actual_gencase"]["generated_xml"],
        "--output", "{attempt_root}/trajectory.h5", "--report", "{attempt_root}/conversion-report.json",
        "--solver-log", native["run_out"], "--solver-receipt", native["receipt"], "--gencase-receipt", owner["actual_gencase"]["receipt"],
        "--decoder", str(DECODER), "--partvtk", str(PARTVTK), "--validation-dir", "{attempt_root}/partvtk-validation",
        "--keep-validation-csv", "--owner-metadata", str(owner_path), "--particle-chunk", "65536",
    ]
    root230 = dispatch()
    frame_request = Path(frame["request"])
    gqa_request = Path(gqa["request"])
    root299_request = Path(native["request"])
    actual_gencase_receipt = Path(owner["actual_gencase"]["receipt"])
    actual_gencase_report = Path(owner["actual_gencase"]["prepared_input_report"])
    generated_xml = Path(owner["actual_gencase"]["generated_xml"])
    generated_report = Path(owner["actual_gencase"]["prepared_input_report"])
    root230_local = PACKAGE / "metadata/root230-policy.json"
    root307_summary = PACKAGE / "metadata/root307-frame0-qa-summary.json"
    root299_summary = PACKAGE / "metadata/root299-native-summary.json"
    inputs = [
        PYTHON, CONVERTER, DIRECT_CONVERTER, RUNTIME, STRICT, GOAL, GPU_POLICY, RESOURCE,
        ROOT230 / "launch.py", ROOT230 / "root_native_home_floor_inventory_policy.py", ROOT230 / "source-policy-contract.json",
        DECODER, PARTVTK, owner_path, canonical_path, binding_path, source_definition, source_plan, gencase_binding,
        gqa_request, Path(gqa["worker"]), Path(gqa["receipt"]), Path(gqa["report"]),
        actual_gencase_receipt, actual_gencase_report, generated_xml, generated_report,
        root299_request, Path(native["receipt"]), Path(native["run_out"]),
        frame_request, Path(frame["worker"]), Path(frame["receipt"]), Path(frame["report"]),
        root230_local,
    ]
    inputs = [safe_input(p) for p in inputs]
    dedup = []
    seen = set()
    for p in inputs:
        key = str(p.resolve())
        if key not in seen:
            seen.add(key); dedup.append(p)
    input_files = [str(p.resolve()) for p in sorted(dedup, key=lambda p: str(p.resolve()))]
    input_sha = {str(p.resolve()): sha(p) for p in sorted(dedup, key=lambda p: str(p.resolve()))}
    request = {
        "schema": "ds02.runner-request.v2", "family_id": "F1", "fresh_id": "fresh088", "case_id": case,
        "scope_id": "F1_STAGE1_FIRST24_HEIGHT_EXTENSION_V1", "kind": "cpu", "cpu_task_kind": "conversion", "cpu_threads": 2,
        "attempt_id": attempt, "cwd": str(INTEGRATION / "lagrangian-fluid-lab"), "worktree_root": str(INTEGRATION),
        "command": command, "estimated_storage_bytes": 25769803776, "estimated_peak_gpu_mib": 0, "max_wall_seconds": 14400,
        "launch_owner": "root", "launch": False, "launch_allowed": False, "execution_allowed": False, "disabled": True,
        "source_only": True, "root_review_required": True, "production_approval": "none", "q_n": "not_assessed",
        "status": "source_only_disabled_waiting_root_typed_conversion", "independent_case_count_increment": 0,
        "depends_on_attempts": [gqa["attempt_id"], native["attempt_id"], frame["attempt_id"]],
        "depends_on": "Root298 GenQA completed/0 pass -> Root299 native completed/0 -> Root307 saved-frame0 QA completed/0 pass",
        "binding": str(binding_path), "binding_sha256": sha(binding_path), "typed_owner": str(owner_path), "typed_owner_sha256": sha(owner_path),
        "source_owner": str(canonical_path), "source_owner_sha256": sha(canonical_path),
        "canonical_condition": {"physical_case_id": owner["physical_case_id"], "physical_condition_sha256": owner["physical_condition_sha256"], "source_plan_condition_sha256": owner["source_plan_condition_sha256"], "canonical_physical_binding_sha256": owner["canonical_physical_binding_sha256"]},
        "legacy_h5_physical_condition_scope": owner["legacy_h5_physical_condition_scope"],
        "actual_gencase_receipt": {"attempt_id": owner["actual_gencase"]["attempt_id"], "receipt": owner["actual_gencase"]["receipt"], "receipt_sha256": owner["actual_gencase"]["receipt_sha256"], "generated_xml": owner["actual_gencase"]["generated_xml"], "generated_xml_sha256": owner["actual_gencase"]["generated_xml_sha256"], "status": "completed/0", "solver_dimension": 3},
        "actual_gencase_initial_qa": {"attempt_id": gqa["attempt_id"], "request": gqa["request"], "request_sha256": gqa["request_sha256"], "receipt": gqa["receipt"], "receipt_sha256": gqa["receipt_sha256"], "report": gqa["report"], "report_sha256": gqa["report_sha256"], "status": "completed/0", "passed": True, "actual_counts": gqa["row"].get("actual_particle_counts"), "actual_total_particles": gqa["row"].get("actual_total_particles")},
        "actual_native_receipt": {"attempt_id": native["attempt_id"], "request": native["request"], "request_sha256": native["request_sha256"], "receipt": native["receipt"], "receipt_sha256": native["receipt_sha256"], "status": "completed/0", "expected_frames": native["expected_frames"], "observed_frame_file_count": native["observed_frame_file_count"], "data_root": native["data_root"], "run_out": native["run_out"], "run_out_sha256": native["run_out_sha256"]},
        "actual_native_frame0_qa": owner["actual_native_frame0_qa"],
        "future_input_files": [native["data_root"], str(Path(native["data_root"]) / "Part_0000.bi4")], "future_input_sha256": None,
        "future_outputs": {"attempt_root": str(output_root), "trajectory_h5": binding["typed_output_h5"], "conversion_report": binding["typed_conversion_report"], "execution_receipt": binding["typed_execution_receipt"], "trajectory_h5_sha256": None, "conversion_report_sha256": None, "execution_receipt_sha256": None, "typed_partvtk_sha256": None, "typed_partvtk_validation": "{attempt_root}/partvtk-validation/*.csv"},
        "nvme_policy": {"conversion_slots": 2, "staging_limit_bytes": 25769803776, "free_space_floor_bytes": 107374182400, "converter": str(CONVERTER), "converter_sha256": sha(CONVERTER), "official_base_decoder": str(DECODER), "official_base_decoder_sha256": "b8ac8cf4aff68ffd089da6cf3ef19dfd0c6473121475f4c198b720a0ddaa8b2e", "official_partvtk": str(PARTVTK), "official_partvtk_sha256": sha(PARTVTK), "approved_interpreter": str(PYTHON), "approved_interpreter_sha256": sha(PYTHON)},
        "typed_field_contract": {"full_native_frames": native["expected_frames"], "full_time_window_s": float(native["request_data"]["expected_output"]["full_window_s"]), "output_timestep_s": float(native["request_data"]["expected_output"]["save_interval_s"]), "actual_native_particle_counts": frame["row"]["actual_particle_counts"], "actual_native_rows": frame["row"]["native_rows"], "actual_native_dimension": 3, "native_frame0_bi4_sha256": frame["row"]["native_frame0_bi4_sha256_after_partvtk"], "max_abs_velocity_error_m_per_s": frame["row"]["max_abs_velocity_error_m_per_s"], "preserve_native_identity": "UID/Zone/Type/Mk and native mass; no continuum or CSV rescale", "required_fields": ["Idp", "Zone", "Type", "Mk", "position", "velocity", "density", "mass", "pressure"], "q_n": "not_assessed"},
        "root230_dispatch": root230,
        "parent_budget": "Root resource window 512 GPUh / 3840 CPUcoreh / qualification1024 / production720; no reservation in source turn",
        "input_files": input_files, "input_sha256": input_sha,
        "raw_arrays_read": False, "mass_rescale": False, "physical_recipe_unchanged": True,
    }
    return write_json(f"requests/{case}.full-native-typed-nvme.request.json", request)


def build() -> None:
    ensure(not PACKAGE.exists(), f"fresh088 package already exists: {PACKAGE}")
    required = [SOURCE087, ROOT298, ROOT299, ROOT307, ROOT230, GPU_POLICY, RESOURCE, RUNTIME, STRICT, GOAL, PYTHON, CONVERTER, DIRECT_CONVERTER, DECODER, PARTVTK]
    for path in required:
        ensure(Path(path).exists(), f"required path missing: {path}")
    actual_gqa = {case: actual_gencase_qa(case) for case in CASES}
    actual_native_data = {case: actual_native(case) for case in CASES}
    actual_frame_data = {case: actual_frame0(case) for case in CASES}
    (PACKAGE / "source").mkdir(parents=True, exist_ok=True)
    for d in ["definitions", "source-plans", "owners", "gencase-bindings"]:
        for src in sorted((SOURCE087 / d).glob("*")):
            if src.is_file():
                copy_file(src, f"source/{d}/{src.name}")
    # Immutable policy/lineage summaries are package-local metadata; actual receipts remain external evidence.
    root230_policy = load(SOURCE087 / "metadata/root230-policy.json")
    write_json("metadata/root230-policy.json", root230_policy)
    write_json("metadata/lineage.json", {
        "schema": "ds02.f1.fresh088.lineage.v1", "fresh_id": "fresh088", "family_id": "F1",
        "upstream_source": str(SOURCE087), "upstream_commit": "445885d63144d9757df46f8edba04e88a38fc0c5",
        "source_unchanged": True, "fresh087_preserved": True,
        "dependency_graph": "Root283 -> Root298 GenQA completed/0 -> Root299 native completed/0 -> Root307 frame0 QA completed/0 -> fresh088 disabled typed NVMe",
        "canonical_owner_and_legacy_scope_separate": True,
        "scientific_arrays_read_or_hashed_by_builder": False,
    })
    rows = []
    root299_rows = []
    root307_rows = []
    for case in CASES:
        gqa, native, frame = actual_gqa[case], actual_native_data[case], actual_frame_data[case]
        canonical_src = PACKAGE / "source/owners" / f"{case}.actual-root283.owner.json"
        canonical = load(canonical_src)
        source_definition = PACKAGE / "source/definitions" / f"{case}_Def.xml"
        source_plan = PACKAGE / "source/source-plans" / f"{case}.json"
        gencase_binding = PACKAGE / "source/gencase-bindings" / f"{case}.actual-root283.json"
        ensure(sha(Path(canonical["actual_gencase"]["generated_xml"])) == canonical["actual_gencase"]["generated_xml_sha256"], f"generated XML evidence changed: {case}")
        ensure(sha(Path(canonical["actual_gencase"]["receipt"])) == canonical["actual_gencase"]["receipt_sha256"], f"GenCase receipt evidence changed: {case}")
        owner, owner_path = typed_owner(case, canonical_src, canonical, gqa, native, frame, source_definition, source_plan)
        binding, binding_path, output_root = typed_binding(case, owner, owner_path, canonical_src, gqa, native, frame, source_definition, source_plan)
        req_path = typed_request(case, owner, owner_path, canonical_src, binding, binding_path, gqa, native, frame, source_definition, source_plan, gencase_binding)
        # Actual evidence summaries are metadata-only.  They intentionally retain the frame-0 producer digest without reading BI4.
        write_json(f"metadata/root307/{case}.json", {
            "schema": "ds02.f1.fresh088.root307-frame0-qa-provenance.v1", "case_id": case,
            "request": frame["request"], "request_sha256": frame["request_sha256"], "receipt": frame["receipt"], "receipt_sha256": frame["receipt_sha256"], "report": frame["report"], "report_sha256": frame["report_sha256"],
            "attempt_id": frame["attempt_id"], "status": "completed/0", "passed": True, "native_rows": frame["row"]["native_rows"], "actual_particle_counts": frame["row"]["actual_particle_counts"], "actual_total_particles": frame["row"]["actual_total_particles"], "native_frame0_bi4_sha256": frame["row"]["native_frame0_bi4_sha256_after_partvtk"], "max_abs_velocity_error_m_per_s": 0.0, "official_partvtk_worker": frame["worker"], "official_partvtk_worker_sha256": frame["worker_sha256"], "source_builder_scientific_array_read": False,
        })
        rows.append({"case_id": case, "gencase_qa_attempt_id": gqa["attempt_id"], "native_attempt_id": native["attempt_id"], "frame0_qa_attempt_id": frame["attempt_id"], "native_frames": native["expected_frames"], "native_observed_frame_file_count": native["observed_frame_file_count"], "frame0_qa_status": "completed/0_pass", "typed_request": str(req_path), "typed_binding": str(binding_path), "typed_future_hashes_null": True, "canonical_physical_condition_sha256": owner["physical_condition_sha256"], "legacy_h5_physical_condition_sha256": None})
        root299_rows.append({"case_id": case, "attempt_id": native["attempt_id"], "receipt": native["receipt"], "receipt_sha256": native["receipt_sha256"], "expected_frames": native["expected_frames"], "observed_frame_file_count": native["observed_frame_file_count"], "status": "completed/0", "scientific_output_hash": None})
        root307_rows.append({"case_id": case, "attempt_id": frame["attempt_id"], "receipt": frame["receipt"], "receipt_sha256": frame["receipt_sha256"], "report": frame["report"], "report_sha256": frame["report_sha256"], "status": "completed/0", "passed": True, "native_rows": frame["row"]["native_rows"], "actual_particle_counts": frame["row"]["actual_particle_counts"], "native_frame0_bi4_sha256": frame["row"]["native_frame0_bi4_sha256_after_partvtk"], "max_abs_velocity_error_m_per_s": 0.0})
    write_json("metadata/root299-native-summary.json", {"schema": "ds02.f1.fresh088.root299-native-summary.v1", "handoff": str(ROOT299), "actual_case_count": 8, "all_completed_zero": True, "cases": root299_rows, "scientific_arrays_read_or_hashed_by_builder": False})
    write_json("metadata/root307-frame0-qa-summary.json", {"schema": "ds02.f1.fresh088.root307-frame0-qa-summary.v1", "handoff": str(ROOT307), "actual_case_count": 8, "all_completed_zero_pass": True, "cases": root307_rows, "scientific_arrays_read_or_hashed_by_builder": False})
    write_json("metadata/typed-candidate-registry.json", {"schema": "ds02.f1.fresh088.typed-candidate-registry.v1", "family_id": "F1", "fresh_id": "fresh088", "scope_id": "F1_STAGE1_FIRST24_HEIGHT_EXTENSION_V1", "source_only": True, "execution_allowed": False, "launch_allowed": False, "root298_gencase_qa_completed_zero": 8, "root299_native_completed_zero": 8, "root307_frame0_qa_completed_zero_pass": 8, "typed_requests_disabled": 8, "cases": rows, "independent_case_count_increment": 0, "q_n": "not_assessed", "production_approval": "none"})
    write_json("metadata/contracts/typed-conversion-contract.json", {
        "schema": "ds02.f1.fresh088.typed-conversion-contract.v1", "cpu_task_kind": "conversion", "cpu_threads": 2, "estimated_storage_bytes": 25769803776, "staging_limit_bytes": 25769803776, "free_space_floor_bytes": 107374182400, "conversion_slots": 2,
        "approved_interpreter": str(PYTHON), "approved_converter": str(CONVERTER), "approved_base_decoder": str(DECODER), "approved_partvtk": str(PARTVTK), "required_command_keys": ["--data-root", "--generated-xml", "--solver-log", "--solver-receipt", "--gencase-receipt", "--decoder", "--partvtk", "--validation-dir", "--owner-metadata", "--particle-chunk"],
        "required_dependencies": ["Root298 GenCase QA completed/0 pass", "Root299 native completed/0", "Root307 saved frame-0 QA completed/0 pass"], "future_hashes": "null until Root-owned converter receipt/report", "canonical_legacy_scope": "separate",
    })
    validator_src = Path(__file__).with_name("validate_f1_fresh088.py")
    ensure(validator_src.is_file(), f"validator source missing: {validator_src}")
    copy_file(validator_src, "validate_source_contract.py")
    copy_file(Path(__file__), "build_fresh088.py")
    readme = f"""# F1 fresh088: actual Root307 frame-0 QA to typed NVMe handoff

This source-only package binds eight actual chains: Root298 GenCase initial QA completed/0, Root299 full native completed/0, and Root307 official PartVTK saved-frame-0 QA completed/0 with `passed=true` and zero maximum velocity error. The frame-0 rows and producer digests are copied from the actual JSON report; this builder did not open or hash BI4/H5/CSV/VTK arrays.

Each disabled typed conversion request uses the approved integration `.venv` interpreter, `ds_data02_nvme_convert_v1.py`, official `bi4_dump` decoder, official PartVTK, 24 GiB NVMe staging cap, 100 GiB free-space floor, CPU conversion kind, two conversion slots, and the Root230 home-floor/dispatch profile. Its strict input closure includes Root298 GenQA receipt/report, Root299 native receipt/Run.out, Root307 frame-0 receipt/report, canonical owner/source definition/plan, converter dependencies, and the root policies. Future H5/report/receipt hashes remain null until Root runs the request.

Canonical physical owner/condition hashes remain separate from the deferred `legacy-owner-scope.v0` H5/report scope. Native recipes, windows, DP, geometry, initial velocity, and native identity fields are preserved. This package does not grant Q-N, visual, production, or independent-case approval and does not alter shared registry/ledger state.

Upstream fresh087 remains immutable at `{SOURCE087}` (commit `445885d63144d9757df46f8edba04e88a38fc0c5`). No GenCase, solver, converter, renderer, job, or scientific-array read occurred while building fresh088.
"""
    (PACKAGE / "README.md").write_text(readme, encoding="utf-8")
    # Validate once, then write a deterministic manifest excluding the manifest itself.
    static = PACKAGE / "metadata/static-validation.json"
    subprocess.run([str(PYTHON), str(PACKAGE / "validate_source_contract.py"), "--output", str(static)], check=True)
    files = []
    for path in sorted(PACKAGE.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            files.append({"path": str(path.relative_to(PACKAGE)), "bytes": path.stat().st_size, "sha256": sha(path)})
    write_json("manifest.json", {"schema": "ds02.f1.fresh088-root307-typed-nvme-manifest.v1", "family_id": "F1", "fresh_id": "fresh088", "commit_scope": str(PACKAGE), "files": files, "case_count": 8, "root298_gencase_qa_completed_zero": 8, "root299_native_completed_zero": 8, "root307_frame0_qa_completed_zero_pass": 8, "typed_request_count": 8, "arrays_read": False, "arrays_hashed": False, "execution_allowed": False, "launch_allowed": False, "shared_registry_or_ledger_modified": False})
    print(json.dumps({"status": "built", "package": str(PACKAGE), "cases": CASES, "typed_requests": 8}, indent=2))


if __name__ == "__main__":
    build()
