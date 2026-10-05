#!/usr/bin/env python3
"""Build the F1 fresh087 source-only Root299 downstream handoff.

This builder reads JSON/text metadata and directory entries only.  It never
opens, copies, or hashes BI4/H5/CSV/VTK scientific arrays.  Root299 native
requests and receipts are immutable external evidence; fresh087 does not
create another native request.
"""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path

F1 = Path("/home/jade/.codex/worktrees/ds-data-02-f1/DualSPHysics")
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1")
FRESH086 = F1 / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F1/handoff_20261003/root_followup_086_f1_root283_gencase_initial_qa_acyclic_v1"
ROOT298 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f1_gencase_qa_path_type_repair_298"
ROOT299 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f1_actualGenQA298_eight_full_native_299"
ROOT230_DIR = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_native_home_floor_eight_solver_dispatch_230"
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
FRESH083 = F1 / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F1/handoff_20261003/root_followup_083_f1_h340_actual_typed186_legacy_xmf_render_and_eight_assembler_v1"
XMF_WORKER = FRESH083 / "workers/export_xmf_legacy_aware.py"
RENDER_WORKER = FRESH083 / "workers/render_native023.py"
PVPYTHON = Path("/home/jade/ParaView-6.1.1-MPI-Linux-Python3.12-x86_64/bin/pvpython")
PACKAGE = F1 / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F1/handoff_20261003/root_followup_087_f1_root298_actual_gencase_qa_native_bind_v1"
VALIDATOR = Path("/tmp/validate_f1_fresh087_root299.py")

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

ROOT230_HASHES = {
    "entry_sha256": "7f703fb94e17c2e2800873f4fcc021f9cd5f8201076afd8e10e3bc6a2d03396e",
    "gpu_sha256": "4e6f340222f7823ae9df1a145ccda884dcf401c9740fc78c51a88066ae1c88cd",
    "home_sha256": "c9103e306f87bb5af871c5de28d9939aa05f0c95c72e1630778f4bcf50e91ab5",
    "resource_sha256": "2a35e26e36920d8ca40001fd7f28416f27bcf371b8b882eca37868f4a15152b8",
    "source_policy_sha256": "42f1af21e8e663234198b6a2f3f87a86b178d11fe3ca8a939467ae97d64e4326",
    "profile": "root_home_floor_no_legacy_dataset_walk_native_v1",
    "gpu_profile": "root_live_all_idle_uuid_leased_eight_solver_v2",
}


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def sha(path: Path) -> str:
    path = Path(path)
    if path.suffix.lower() in {".bi4", ".h5", ".hdf5", ".csv", ".npy", ".npz", ".vtk"}:
        raise RuntimeError(f"scientific array read is forbidden: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def canonical_sha(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def ensure(condition: object, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def write_json(relative: str, value: object) -> Path:
    path = PACKAGE / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def copy_file(source: Path, relative: str) -> Path:
    destination = PACKAGE / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination


def request_for_case(case: str) -> Path:
    paths = sorted(ROOT299.glob(f"{case}-native-request.json"))
    ensure(len(paths) == 1, f"Root299 request missing/ambiguous for {case}: {paths}")
    return paths[0]


def actual_gencase_qa(case: str) -> dict:
    receipts = sorted(DATA.glob(f"{case}/root-stage1-f1-*-gencase-initial-qa-path-repair-298/execution-receipt.json"))
    ensure(len(receipts) == 1, f"Root298 receipt missing/ambiguous for {case}: {receipts}")
    receipt_path = receipts[0]
    attempt_root = receipt_path.parent
    report_path = attempt_root / "audit/gencase-initial-qa.json"
    request_path = ROOT298 / f"{case}-initial-qa-request.json"
    ensure(report_path.is_file() and request_path.is_file(), f"Root298 files missing for {case}")
    receipt = load(receipt_path)
    report = load(report_path)
    request = load(request_path)
    rows = report.get("cases")
    ensure(receipt.get("status") == "completed" and receipt.get("returncode") == 0, f"Root298 not completed/0: {case}")
    ensure(report.get("schema") == "ds02.f1.gencase-initial-qa.v1", f"Root298 schema mismatch: {case}")
    ensure(isinstance(rows, list) and len(rows) == 1 and rows[0].get("passed") is True, f"Root298 did not pass: {case}")
    ensure(sha(request_path) == receipt.get("request_sha256"), f"Root298 request SHA mismatch: {case}")
    command = request.get("command", [])
    worker = Path(command[1]) if len(command) > 1 else None
    ensure(worker is not None and worker.is_file(), f"Root298 worker missing: {case}")
    return {
        "case": case,
        "attempt_id": receipt.get("request", {}).get("attempt_id", attempt_root.name),
        "attempt_root": str(attempt_root),
        "receipt": str(receipt_path),
        "receipt_sha256": sha(receipt_path),
        "receipt_data": receipt,
        "report": str(report_path),
        "report_sha256": sha(report_path),
        "report_data": report,
        "request": str(request_path),
        "request_sha256": sha(request_path),
        "request_data": request,
        "worker": str(worker),
        "worker_sha256": sha(worker),
        "row": rows[0],
    }


def actual_native(case: str) -> dict:
    request_path = request_for_case(case)
    request = load(request_path)
    attempt_id = request.get("attempt_id")
    ensure(isinstance(attempt_id, str) and attempt_id, f"Root299 attempt missing: {case}")
    receipt_path = DATA / case / attempt_id / "execution-receipt.json"
    ensure(receipt_path.is_file(), f"Root299 receipt missing: {receipt_path}")
    receipt = load(receipt_path)
    ensure(receipt.get("status") == "completed" and receipt.get("returncode") == 0, f"Root299 not completed/0: {case}")
    ensure(sha(request_path) == receipt.get("request_sha256"), f"Root299 request SHA mismatch: {case}")
    requested_command = [str(x) for x in request.get("command", [])]
    actual_command = [str(x) for x in receipt.get("command", [])]
    ensure(requested_command[-2:] == actual_command[-2:], f"Root299 solver option provenance mismatch: {case}")
    ensure("-mdbc" not in " ".join(actual_command) and "-forcing" not in " ".join(actual_command), f"forbidden solver option in Root299 command: {case}")
    expected = request.get("expected_output", {})
    frame_count = int(expected.get("frame_count", 0))
    output_root = Path(receipt["output_root"])
    data_root = output_root / "solver_output/data"
    ensure(data_root.is_dir(), f"Root299 data directory missing: {data_root}")
    # Directory inventory is metadata only.  We do not open or hash any BI4.
    frame_files = sorted(data_root.glob("Part_*.bi4"))
    observed = len(frame_files)
    ensure(observed == frame_count, f"Root299 frame inventory differs for {case}: {observed} != {frame_count}")
    run_out = output_root / "solver_output/Run.out"
    ensure(run_out.is_file(), f"Root299 Run.out missing: {case}")
    return {
        "case": case,
        "request": str(request_path),
        "request_sha256": sha(request_path),
        "request_data": request,
        "solver_command": actual_command,
        "attempt_id": attempt_id,
        "receipt": str(receipt_path),
        "receipt_sha256": sha(receipt_path),
        "receipt_data": receipt,
        "output_root": str(output_root),
        "data_root": str(data_root),
        "run_out": str(run_out),
        "run_out_sha256": sha(run_out),
        "expected_frame_count": frame_count,
        "observed_frame_file_count": observed,
        "actual_output_inventory": {
            "part_bi4_file_count": observed,
            "scientific_bytes_opened_by_builder": False,
            "scientific_bytes_hashed_by_builder": False,
        },
        "receipt_status": receipt.get("status"),
        "receipt_returncode": receipt.get("returncode"),
        "receipt_termination_reason": receipt.get("termination_reason"),
    }


def dispatch() -> dict:
    return {
        "entry": str(ROOT230_DIR / "launch.py"),
        "entry_sha256": ROOT230_HASHES["entry_sha256"],
        "gpu_policy": str(GPU_POLICY),
        "gpu_policy_sha256": ROOT230_HASHES["gpu_sha256"],
        "home_floor_policy": str(ROOT230_DIR / "root_native_home_floor_inventory_policy.py"),
        "home_floor_policy_sha256": ROOT230_HASHES["home_sha256"],
        "profile": ROOT230_HASHES["profile"],
        "resource_window": str(RESOURCE),
        "resource_window_sha256": ROOT230_HASHES["resource_sha256"],
        "source_policy_contract": str(ROOT230_DIR / "source-policy-contract.json"),
        "source_policy_contract_sha256": ROOT230_HASHES["source_policy_sha256"],
        "root_owned": True,
    }


def frame_binding(case: str, old_bind: dict, old_frame_bind: dict, qa: dict, native: dict, path: Path) -> dict:
    old_case = old_frame_bind["cases"][0]
    actual_counts = qa["row"]["native_type_counts"]
    counts = {
        "fixed": int(actual_counts.get("0", actual_counts.get(0, 0))),
        "moving": int(old_case.get("actual_particle_counts", {}).get("moving", 0)),
        "floating": int(old_case.get("actual_particle_counts", {}).get("floating", 0)),
        "fluid": int(qa["row"]["native_fluid"]),
    }
    # Keep the existing worker contract while replacing only the native
    # attempt/output provenance with Root299 actual evidence.
    binding = copy.deepcopy(old_frame_bind)
    case_row = copy.deepcopy(old_case)
    case_row.update({
        "actual_particle_counts": counts,
        "actual_total_particles": int(qa["row"]["native_particles"]),
        "native_solver_attempt_id": native["attempt_id"],
        "native_solver_receipt": native["receipt"],
        "native_solver_receipt_sha256": native["receipt_sha256"],
        "native_data_dir": native["data_root"],
        "native_output_inventory": native["actual_output_inventory"],
        "native_receipt_observed": {"status": native["receipt_status"], "returncode": native["receipt_returncode"], "termination_reason": native["receipt_termination_reason"]},
        "native_frame0_bi4_sha256": None,
        "prospective_output_not_generated": True,
    })
    binding["cases"] = [case_row]
    binding.update({
        "schema": "ds02.f1.fresh087.native-frame0-height-qa-binding.v1",
        "status": "source_only_disabled_waiting_root_frame0_qa",
        "source_only": True,
        "execution_allowed": False,
        "launch_allowed": False,
        "native_solver_attempt_id": native["attempt_id"],
        "native_solver_receipt": native["receipt"],
        "native_solver_receipt_sha256": native["receipt_sha256"],
        "native_data_dir": native["data_root"],
        "native_observed_frame_file_count": native["observed_frame_file_count"],
        "native_expected_frame_count": native["expected_frame_count"],
        "native_initial_qa": "downstream after actual Root299 native completed/0; no frame-0 QA claim",
        "native_frame0_bi4_sha256": None,
        "prospective_output_not_generated": True,
        "root299_actual_native_request": native["request"],
        "root299_actual_native_request_sha256": native["request_sha256"],
        "root299_actual_native_receipt": native["receipt"],
        "root299_actual_native_receipt_sha256": native["receipt_sha256"],
        "source086_lineage": str(FRESH086),
    })
    return binding


def frame_request(case: str, frame_attempt: str, binding_path: Path, binding: dict, native: dict, old_frame: dict, root: Path) -> dict:
    request = copy.deepcopy(old_frame)
    # Preserve the validated worker command/field contract but point it at the
    # package-local binding and actual Root299 native attempt.
    worker = PACKAGE / "workers/native_initial_height_frame0_audit.py"
    request["attempt_id"] = frame_attempt
    request["binding"] = str(binding_path)
    request["binding_sha256"] = sha(binding_path)
    command = [str(PYTHON), str(worker), "--binding", str(binding_path), "--output-dir", "{attempt_root}/audit"]
    request["command"] = command
    request["cwd"] = str(INTEGRATION / "lagrangian-fluid-lab")
    request["depends_on_attempts"] = [native["attempt_id"]]
    request["native_solver_attempt_id"] = native["attempt_id"]
    request["native_solver_receipt"] = native["receipt"]
    request["native_solver_receipt_sha256"] = native["receipt_sha256"]
    request["future_input_files"] = [native["receipt"], str(Path(native["data_root"]) / "Part_0000.bi4")]
    request["future_input_sha256"] = None
    request["future_outputs"] = {
        "attempt_root": str(root),
        "report": str(root / "audit/native-initial-height-audit.json"),
        "execution_receipt": str(root / "execution-receipt.json"),
        "sha256": None,
        "status": "not_generated",
    }
    request.update({
        "schema": "ds02.runner-request.v2",
        "status": "source_only_disabled_waiting_root_frame0_qa",
        "disabled": True,
        "execution_allowed": False,
        "launch": False,
        "launch_allowed": False,
        "source_only": True,
        "root_review_required": True,
        "source086_lineage": str(FRESH086),
        "root299_actual_native_receipt": native["receipt"],
        "root299_actual_native_receipt_sha256": native["receipt_sha256"],
    })
    # The copied binding is the only package-local input whose hash changes.
    old_binding = old_frame.get("binding")
    files = [str(PACKAGE / "workers/native_initial_height_frame0_audit.py"), str(binding_path)]
    for raw in old_frame.get("input_files", []):
        if raw == old_binding:
            continue
        p = Path(raw)
        if p.suffix.lower() in {".bi4", ".csv", ".h5", ".vtk"}:
            continue
        if p.is_file():
            files.append(str(p))
    files.extend([native["receipt"], native["run_out"]])
    files = sorted(dict.fromkeys(files))
    hashes: dict[str, str] = {}
    for raw in files:
        p = Path(raw)
        if p == binding_path:
            hashes[raw] = sha(binding_path)
        elif p.is_file() and p.suffix.lower() not in {".bi4", ".csv", ".h5", ".vtk"}:
            hashes[raw] = sha(p)
    request["input_files"] = files
    request["input_sha256"] = hashes
    return request


def typed_owner(case: str, old_owner: dict, owner_path: Path, definition_path: Path, source_plan_path: Path, native: dict, qa: dict) -> tuple[dict, Path]:
    owner = copy.deepcopy(old_owner)
    owner["schema"] = "ds02.f1.fresh087.native-full-typed-conversion-owner.v1"
    owner["fresh_id"] = "fresh087"
    owner["source_owner"] = str(owner_path)
    owner["source_owner_sha256"] = sha(owner_path)
    owner["source_definition"] = str(definition_path)
    owner["source_definition_sha256"] = sha(definition_path)
    owner["source_plan"] = str(source_plan_path)
    owner["source_plan_sha256"] = sha(source_plan_path)
    owner["actual_gencase_initial_qa"] = {
        "receipt": qa["receipt"], "receipt_sha256": qa["receipt_sha256"],
        "report": qa["report"], "report_sha256": qa["report_sha256"],
        "status": "completed", "passed": True,
    }
    owner["actual_native"] = {
        "attempt_id": native["attempt_id"], "data_root": native["data_root"],
        "expected_frames": native["expected_frame_count"],
        "observed_frame_file_count": native["observed_frame_file_count"],
        "receipt": native["receipt"], "receipt_sha256": native["receipt_sha256"],
        "status": "completed", "returncode": 0,
        "tmax_s": float(load(Path(native["request"])).get("expected_output", {}).get("full_window_s")),
        "tout_s": float(load(Path(native["request"])).get("expected_output", {}).get("save_interval_s")),
        "scientific_output_hashes": "deferred to Root-owned typed conversion; no BI4/H5 read by source builder",
    }
    owner["typed_status"] = "prospective_disabled_until_root_frame0_qa_and_conversion"
    owner["gencase_initial_qa"] = "actual Root298 completed/0 official initial QA pass"
    owner["native_initial_typed_QA"] = "pending actual solver-saved frame-0 PartVTK audit"
    owner["status"] = "root299_actual_native_completed_zero_frame0_qa_pending"
    owner["execution_allowed"] = False
    owner["launch_allowed"] = False
    owner["source_only"] = True
    path = PACKAGE / "typed-conversion/owners" / f"{case}.owner.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(owner, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return owner, path


def typed_request(case: str, old_owner: dict, owner_path: Path, definition_path: Path, source_plan_path: Path, qa: dict, native: dict, frame_request_path: Path, typed_owner_path: Path) -> tuple[dict, Path, Path]:
    case_root = DATA / case
    tmax = float(load(Path(native["request"])).get("expected_output", {}).get("full_window_s"))
    tout = float(load(Path(native["request"])).get("expected_output", {}).get("save_interval_s"))
    frames = int(native["expected_frame_count"])
    slug = case.lower()
    native_data = native["data_root"]
    output_root = case_root / f"root-stage1-f1-{slug}-full-native-typed-nvme-087"
    generated_xml = old_owner["actual_gencase"]["generated_xml"]
    generated_def = str(definition_path)
    gencase_receipt = old_owner["actual_gencase"]["receipt"]
    run_out = native["run_out"]
    attempt = f"root-stage1-f1-{slug}-full-native-typed-nvme-087"
    binding_path = PACKAGE / "typed-conversion/bindings" / f"{case}.json"
    report_path = output_root / "conversion-report.json"
    receipt_path = output_root / "execution-receipt.json"
    h5_path = output_root / "trajectory.h5"
    binding = {
        "schema": "ds02.f1.fresh087.native-full-typed-binding.v1",
        "family_id": "F1", "case_id": case, "fresh_id": "fresh087",
        "canonical_owner": str(owner_path), "canonical_owner_sha256": sha(owner_path),
        "typed_owner": str(typed_owner_path),
        "typed_owner_sha256": sha(typed_owner_path),
        "physical_case_id": old_owner["physical_case_id"],
        "physical_condition_sha256": old_owner["physical_condition_sha256"],
        "source_plan_condition_sha256": old_owner.get("source_plan_condition_sha256"),
        "source_definition": generated_def, "source_definition_sha256": sha(definition_path),
        "generated_def": generated_def, "generated_def_sha256": sha(definition_path),
        "generated_xml": generated_xml, "generated_xml_sha256": old_owner["actual_gencase"]["generated_xml_sha256"],
        "actual_gencase_receipt": gencase_receipt, "actual_gencase_receipt_sha256": old_owner["actual_gencase"]["receipt_sha256"],
        "actual_gencase_report": old_owner["actual_gencase"]["prepared_input_report"], "actual_gencase_report_sha256": old_owner["actual_gencase"]["prepared_input_report_sha256"],
        "actual_gencase_initial_qa": {"receipt": qa["receipt"], "receipt_sha256": qa["receipt_sha256"], "report": qa["report"], "report_sha256": qa["report_sha256"], "status": "completed", "passed": True},
        "actual_native_receipt": native["receipt"], "actual_native_receipt_sha256": native["receipt_sha256"],
        "actual_native_attempt_id": native["attempt_id"], "actual_native_data_root": native_data,
        "actual_native_expected_frames": frames, "actual_native_observed_frame_file_count": native["observed_frame_file_count"],
        "actual_native_receipt_status": "completed/0",
        "typed_output_h5": str(h5_path), "typed_output_sha256": None,
        "typed_conversion_report": str(report_path), "typed_conversion_report_sha256": None,
        "typed_execution_receipt": str(receipt_path), "typed_execution_receipt_sha256": None,
        "typed_status": "pending_root_conversion", "legacy_h5_physical_condition_sha256": None,
        "expected_frames": frames, "expected_particles": int(old_owner["actual_total_particles"]), "expected_dimension": 3,
        "full_time_window_s": tmax, "save_interval_s": tout,
        "future_hashes_null": True, "raw_arrays_read": False, "mass_rescale": False,
        "independent_case_count_increment": 0, "q_n": "not_assessed", "production_approval": "none",
        "source_only": True, "execution_allowed": False, "launch_allowed": False, "root_review_required": True,
        "status": "source_only_disabled_waiting_root_frame0_qa_then_typed_conversion",
    }
    binding_path.parent.mkdir(parents=True, exist_ok=True)
    binding_path.write_text(json.dumps(binding, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    attempt_root = output_root
    command = [
        str(PYTHON), str(CONVERTER), "--staging-root", "/tmp/ds02-nvme-conversion", "--staging-limit-bytes", "25769803776", "--",
        "--data-root", native_data, "--generated-xml", generated_xml,
        "--output", "{attempt_root}/trajectory.h5", "--report", "{attempt_root}/conversion-report.json",
        "--solver-log", run_out, "--solver-receipt", native["receipt"], "--gencase-receipt", gencase_receipt,
        "--decoder", str(DECODER), "--partvtk", str(PARTVTK), "--validation-dir", "{attempt_root}/partvtk-validation",
        "--keep-validation-csv", "--owner-metadata", str(typed_owner_path), "--particle-chunk", "65536",
    ]
    generated_def_path = Path(generated_xml).with_name(Path(generated_xml).stem + "_Def.xml")
    source_files = [PYTHON, CONVERTER, DIRECT_CONVERTER, RUNTIME, STRICT, GOAL, ROOT230_DIR / "launch.py", ROOT230_DIR / "root_native_home_floor_inventory_policy.py", ROOT230_DIR / "source-policy-contract.json", GPU_POLICY, RESOURCE, owner_path, typed_owner_path, definition_path, source_plan_path, Path(generated_xml), generated_def_path, Path(qa["receipt"]), Path(qa["report"]), Path(native["receipt"]), Path(native["run_out"]), frame_request_path]
    source_files = [p for p in source_files if p.is_file()]
    input_files = sorted(dict.fromkeys(str(p) for p in source_files))
    input_sha = {str(p): sha(p) for p in source_files}
    request = {
        "schema": "ds02.runner-request.v2", "family_id": "F1", "fresh_id": "fresh087", "case_id": case,
        "scope_id": "F1_STAGE1_FIRST24_HEIGHT_EXTENSION_V1", "kind": "cpu", "cpu_task_kind": "conversion", "cpu_threads": 2,
        "attempt_id": attempt, "cwd": str(INTEGRATION / "lagrangian-fluid-lab"), "worktree_root": str(INTEGRATION),
        "command": command, "estimated_storage_bytes": 25769803776, "estimated_peak_gpu_mib": 0, "max_wall_seconds": 14400,
        "launch_owner": "root", "launch": False, "launch_allowed": False, "execution_allowed": False, "disabled": True,
        "source_only": True, "root_review_required": True, "production_approval": "none", "q_n": "not_assessed",
        "status": "source_only_disabled_waiting_root_frame0_qa_and_typed_conversion", "independent_case_count_increment": 0,
        "depends_on_attempts": [native["attempt_id"], load(frame_request_path)["attempt_id"]],
        "depends_on": "Root299 native completed/0, then fresh087 native frame-0 QA completed/0 passed",
        "binding": str(binding_path), "binding_sha256": sha(binding_path), "typed_owner": str(typed_owner_path), "typed_owner_sha256": sha(typed_owner_path),
        "source_owner": str(owner_path), "source_owner_sha256": sha(owner_path),
        "actual_gencase_receipt": {"receipt": gencase_receipt, "receipt_sha256": old_owner["actual_gencase"]["receipt_sha256"], "generated_xml": generated_xml, "generated_xml_sha256": old_owner["actual_gencase"]["generated_xml_sha256"], "generated_def": generated_def, "generated_def_sha256": sha(definition_path), "status": "completed/0", "total_particles": int(old_owner["actual_total_particles"]), "fluid_particles": int(old_owner["actual_particle_counts"]["fluid"])},
        "actual_native_receipt": {"attempt_id": native["attempt_id"], "receipt": native["receipt"], "receipt_sha256": native["receipt_sha256"], "status": "completed/0", "expected_frames": frames, "observed_frame_file_count": native["observed_frame_file_count"], "data_root": native_data},
        "native_full_binding": {"data_root": native_data, "expected_frames": frames, "native_receipt": native["receipt"], "native_receipt_sha256": native["receipt_sha256"], "tmax_s": tmax, "tout_s": tout},
        "frame0_qa_dependency": {"request": str(frame_request_path), "request_sha256": sha(frame_request_path), "receipt": str(output_root / "frame0-qa-receipt.json"), "receipt_sha256": None, "report": str(output_root / "frame0-qa-report.json"), "report_sha256": None, "status": "required_actual_pass_before_conversion"},
        "canonical_condition": {"physical_case_id": old_owner["physical_case_id"], "physical_condition_sha256": old_owner["physical_condition_sha256"], "source_plan_condition_sha256": old_owner.get("source_plan_condition_sha256")},
        "input_files": input_files, "input_sha256": input_sha,
        "future_input_files": [native_data, str(Path(native_data) / "Part_0000.bi4")], "future_input_sha256": None,
        "future_outputs": {"attempt_root": str(attempt_root), "trajectory_h5": str(h5_path), "conversion_report": str(report_path), "execution_receipt": str(receipt_path), "trajectory_h5_sha256": None, "conversion_report_sha256": None, "execution_receipt_sha256": None, "typed_partvtk_sha256": None, "typed_partvtk_validation": "{attempt_root}/partvtk-validation/*.csv"},
        "nvme_policy": {"conversion_slots": 2, "staging_limit_bytes": 25769803776, "free_space_floor_bytes": 107374182400, "converter": str(CONVERTER), "converter_sha256": sha(CONVERTER), "official_decoder": str(DECODER), "official_decoder_sha256": "b8ac8cf4aff68ffd089da6cf3ef19dfd0c6473121475f4c198b720a0ddaa8b2e", "official_partvtk": str(PARTVTK), "official_partvtk_sha256": sha(PARTVTK)},
        "typed_field_contract": {"full_native_frames": frames, "full_time_window_s": tmax, "output_timestep_s": tout, "native_fluid_mk": int(qa["row"]["fluid_mk"]), "native_fluid_type": 3, "preserve_native_identity": "UID/Zone, Type and Mk for fixed/moving/floating/fluid; no CSV/native mass rescale", "required_fields": ["Idp", "Zone", "Type", "Mk", "position", "velocity", "density", "mass", "pressure"], "q_n": "not_assessed"},
        "root230_dispatch": dispatch(), "parent_budget": "Root resource window 512 GPUh / 3840 CPUcoreh / qualification1024 / production720; no reservation in source turn",
        "raw_arrays_read": False, "mass_rescale": False, "physical_recipe_unchanged": True,
    }
    request_path = PACKAGE / "typed-conversion/requests" / f"{case}.full-native-typed-nvme.request.json"
    request_path.parent.mkdir(parents=True, exist_ok=True)
    request_path.write_text(json.dumps(request, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return binding, binding_path, request_path


def xmf_binding(case: str, owner: dict, owner_path: Path, typed_owner_path: Path, typed_request: dict, typed_binding: dict, definition_path: Path, source_plan_path: Path, native: dict, qa: dict, frame_request_path: Path) -> tuple[dict, Path]:
    slug = case.lower()
    typed_root = DATA / case / f"root-stage1-f1-{slug}-full-native-typed-nvme-087"
    xmf_root = DATA / case / f"root-stage1-f1-{slug}-full401-paraview-dynamic-xdmf-087"
    binding_path = PACKAGE / "xmf/bindings" / f"{case}.legacy-aware-binding.json"
    canonical_owner = load(owner_path)
    binding = {
        "schema": "ds02.f1.fresh087.legacy-aware-temporal-binding.v1", "scope_id": "root_followup_087_f1_root299_native_bind_v1", "fresh_id": "fresh087", "family_id": "F1", "case_id": case,
        "canonical_owner": str(owner_path), "canonical_owner_sha256": sha(owner_path), "typed_owner": str(typed_owner_path), "typed_owner_sha256": sha(typed_owner_path),
        "canonical_physical_condition_sha256": owner["physical_condition_sha256"], "canonical_physical_binding_sha256": canonical_sha(canonical_owner["physical_binding"]),
        "physical_case_id": owner["physical_case_id"], "topphysical_case_id": owner["physical_case_id"], "source_plan_condition_sha256": owner.get("source_plan_condition_sha256"),
        "source_definition": str(definition_path), "source_definition_sha256": sha(definition_path), "generated_def": owner["actual_gencase"]["generated_xml"].replace(".xml", "_Def.xml"), "generated_def_sha256": sha(definition_path),
        "generated_xml": owner["actual_gencase"]["generated_xml"], "generated_xml_sha256": owner["actual_gencase"]["generated_xml_sha256"],
        "actual_gencase_receipt": owner["actual_gencase"]["receipt"], "actual_gencase_receipt_sha256": owner["actual_gencase"]["receipt_sha256"], "actual_gencase_report": owner["actual_gencase"]["prepared_input_report"], "actual_gencase_report_sha256": owner["actual_gencase"]["prepared_input_report_sha256"],
        "actual_gencase_initial_qa": {"receipt": qa["receipt"], "receipt_sha256": qa["receipt_sha256"], "report": qa["report"], "report_sha256": qa["report_sha256"], "status": "completed/0", "passed": True},
        "actual_native_receipt": native["receipt"], "actual_native_receipt_sha256": native["receipt_sha256"], "actual_native_attempt_id": native["attempt_id"], "actual_native_observed_frame_file_count": native["observed_frame_file_count"],
        "actual_frame0_qa": {"request": str(frame_request_path), "request_sha256": sha(frame_request_path), "receipt": str(DATA / case / f"root-stage1-f1-{slug}-native-frame0-height-qa-087/execution-receipt.json"), "receipt_sha256": None, "report": str(DATA / case / f"root-stage1-f1-{slug}-native-frame0-height-qa-087/audit/native-initial-height-audit.json"), "report_sha256": None, "status": "pending_disabled_downstream"},
        "typed_conversion_report": str(typed_root / "conversion-report.json"), "typed_conversion_report_sha256": None, "typed_execution_receipt": str(typed_root / "execution-receipt.json"), "typed_execution_receipt_sha256": None, "typed_output_h5": str(typed_root / "trajectory.h5"), "typed_output_sha256": None,
        "legacy_h5_physical_condition_scope": {"schema": "legacy-owner-scope.v0", "physical_case_id": owner["physical_case_id"], "semantic_binding_status": "future converter report required; canonical owner scope remains separate"}, "legacy_h5_physical_condition_sha256": None,
        "expected_frames": native["expected_frame_count"], "expected_particles": int(owner["actual_total_particles"]), "expected_dimension": 3, "physical_window_s": [0.0, float(load(Path(native["request"])).get("expected_output", {}).get("full_window_s"))], "save_interval_s": float(load(Path(native["request"])).get("expected_output", {}).get("save_interval_s")),
        "native_identity_contract": {"required_fields": ["Idp", "Zone", "Type", "Mk", "position", "velocity", "density", "mass", "pressure"], "native_fluid_type": 3, "native_fluid_mk": int(qa["row"]["fluid_mk"]), "mass_policy": "native mass weights; no continuum rescale"},
        "root193_xmf": {"attempt_id": f"root-stage1-f1-{slug}-full401-paraview-dynamic-xdmf-087", "output_root": str(xmf_root), "execution_receipt": str(xmf_root / "execution-receipt.json"), "manifest": str(xmf_root / "manifest.json"), "xdmf": str(xmf_root / "case.xmf"), "execution_receipt_sha256": None, "manifest_sha256": None, "xdmf_sha256": None},
        "root194_render": {"attempt_id": f"root-stage1-f1-{slug}-full401-native023-render-087", "output_root": str(DATA / case / f"root-stage1-f1-{slug}-full401-native023-render-087/render"), "execution_receipt": str(DATA / case / f"root-stage1-f1-{slug}-full401-native023-render-087/render/execution-receipt.json"), "report": str(DATA / case / f"root-stage1-f1-{slug}-full401-native023-render-087/render/paraview-full-animation-report.json"), "execution_receipt_sha256": None, "report_sha256": None, "frame_sha256": None},
        "legacy_canonical_mapping": {"canonical_hash_is_physical_binding_json": True, "legacy_hash_is_report_and_h5_attribute": True, "legacy_scope_schema": "legacy-owner-scope.v0", "cross_resolution_precision_claim": False},
        "camera_bounds_policy": "native023 scans valid native positions across every actual saved XDMF time; no fixed camera/domain bounds",
        "full_saved_frames_required": True, "independent_case_count_increment": 0, "production_approval": "none", "q_n": "not_assessed", "source_only": True, "execution_allowed": False, "launch_allowed": False, "root_review_required": True,
        "status": "source_only_disabled_waiting_root_frame0_qa_then_typed_report", "future_hashes_null": True,
    }
    binding_path.parent.mkdir(parents=True, exist_ok=True)
    binding_path.write_text(json.dumps(binding, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return binding, binding_path


def xmf_request(case: str, xmf_bind_path: Path, xmf_binding: dict, typed_request_path: Path, native: dict) -> Path:
    slug = case.lower(); xmf_root = DATA / case / f"root-stage1-f1-{slug}-full401-paraview-dynamic-xdmf-087"
    worker = PACKAGE / "workers/export_xmf_legacy_aware.py"
    input_files = [PYTHON, RUNTIME, STRICT, GOAL, ROOT230_DIR / "launch.py", ROOT230_DIR / "root_native_home_floor_inventory_policy.py", ROOT230_DIR / "source-policy-contract.json", worker, xmf_bind_path, typed_request_path, Path(xmf_binding["canonical_owner"]), Path(xmf_binding["typed_owner"]), Path(xmf_binding["source_definition"]), Path(xmf_binding["generated_def"]), Path(xmf_binding["generated_xml"]), Path(xmf_binding["actual_gencase_receipt"]), Path(xmf_binding["actual_gencase_report"]), Path(xmf_binding["actual_native_receipt"])]
    input_files = [p for p in input_files if p.is_file()]
    request = {
        "schema": "ds02.runner-request.v2", "fresh_id": "fresh087", "family_id": "F1", "case_id": case, "scope_id": "root_followup_087_f1_root299_native_bind_v1", "kind": "cpu", "cpu_task_kind": "conversion", "cpu_threads": 2,
        "attempt_id": f"root-stage1-f1-{slug}-full401-paraview-dynamic-xdmf-087", "cwd": str(INTEGRATION / "lagrangian-fluid-lab"), "worktree_root": str(F1),
        "command": [str(PYTHON), str(worker), "--binding", str(xmf_bind_path), "--output-dir", "{attempt_root}"], "binding": str(xmf_bind_path), "binding_sha256": sha(xmf_bind_path),
        "depends_on_attempts": [native["attempt_id"], load(Path(xmf_binding["actual_frame0_qa"]["request"]))["attempt_id"], load(typed_request_path)["attempt_id"]], "depends_on": "Root299 native completed/0 -> frame0 QA completed/0 pass -> typed conversion completed/0",
        "execution_allowed": False, "launch_allowed": False, "launch": False, "disabled": True, "source_only": True, "root_review_required": True, "launch_owner": "root", "status": "source_only_disabled_waiting_root_typed_conversion", "production_approval": "none", "q_n": "not_assessed", "independent_case_count_increment": 0,
        "estimated_storage_bytes": 8589934592, "max_wall_seconds": 1800, "future_input_files": [xmf_binding["typed_output_h5"], xmf_binding["typed_conversion_report"], xmf_binding["typed_execution_receipt"]], "future_input_sha256": None,
        "future_outputs": {"attempt_root": str(xmf_root), "execution_receipt": str(xmf_root / "execution-receipt.json"), "manifest": str(xmf_root / "manifest.json"), "case_xmf": str(xmf_root / "case.xmf"), "execution_receipt_sha256": None, "manifest_sha256": None, "xdmf_sha256": None},
        "input_files": [str(p) for p in sorted(input_files)], "input_sha256": {str(p): sha(p) for p in input_files}, "raw_arrays_read": False, "physical_condition_scope": "canonical owner and legacy H5 scope remain distinct; no precision/Q-N claim",
    }
    path = PACKAGE / "xmf/requests" / f"{case}.root193-xmf.request.json"; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(request, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"); return path


def render_binding(case: str, xmf_binding: dict, xmf_path: Path, owner_path: Path, typed_owner_path: Path, native: dict, owner: dict) -> tuple[dict, Path]:
    binding = {
        "schema": "ds02.f1.fresh087.native023-render-binding.v1", "family_id": "F1", "fresh_id": "fresh087", "case_id": case,
        "canonical_owner": str(owner_path), "canonical_owner_sha256": sha(owner_path), "typed_owner": str(typed_owner_path), "typed_owner_sha256": sha(typed_owner_path),
        "canonical_physical_condition_sha256": owner["physical_condition_sha256"], "canonical_physical_binding_sha256": xmf_binding["canonical_physical_binding_sha256"], "physical_case_id": owner["physical_case_id"],
        "xmf_binding": str(xmf_path), "xmf_binding_sha256": sha(xmf_path), "xmf_manifest": xmf_binding["root193_xmf"]["manifest"], "xmf_manifest_sha256": None, "xdmf": xmf_binding["root193_xmf"]["xdmf"], "xdmf_sha256": None,
        "typed_output_h5": xmf_binding["typed_output_h5"], "typed_output_sha256": None, "expected_frames": xmf_binding["expected_frames"], "expected_particles": xmf_binding["expected_particles"], "expected_dimension": 3,
        "camera_bounds_policy": "native023 auto-all-frame native bounds; no source camera crop", "native_identity_contract": xmf_binding["native_identity_contract"], "visual_status": "pending actual Root023 render", "precision_status": "not accepted; no Q-N claim",
        "root_review_required": True, "source_only": True, "execution_allowed": False, "launch_allowed": False, "production_approval": "none", "q_n": "not_assessed", "independent_case_count_increment": 0, "status": "source_only_disabled_waiting_root_xmf_manifest",
        "future_outputs": {"attempt_root": xmf_binding["root194_render"]["output_root"], "execution_receipt": xmf_binding["root194_render"]["execution_receipt"], "report": xmf_binding["root194_render"]["report"], "frame_sha256": None, "report_sha256": None, "execution_receipt_sha256": None},
    }
    path = PACKAGE / "render/bindings" / f"{case}.render-binding.json"; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(binding, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"); return binding, path


def render_request(case: str, render_bind_path: Path, render_binding: dict, xmf_path: Path, xmf_binding: dict, native: dict) -> Path:
    slug = case.lower(); root = DATA / case / f"root-stage1-f1-{slug}-full401-native023-render-087"
    worker = PACKAGE / "workers/render_native023.py"
    input_files = [RUNTIME, STRICT, GOAL, ROOT230_DIR / "launch.py", ROOT230_DIR / "root_native_home_floor_inventory_policy.py", ROOT230_DIR / "source-policy-contract.json", worker, PVPYTHON, render_bind_path, xmf_path, Path(render_binding["xmf_binding"])]
    input_files = [p for p in input_files if p.is_file()]
    request = {
        "schema": "ds02.runner-request.v2", "fresh_id": "fresh087", "family_id": "F1", "case_id": case, "scope_id": "root_followup_087_f1_root299_native_bind_v1", "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 2,
        "attempt_id": f"root-stage1-f1-{slug}-full401-native023-render-087", "cwd": str(INTEGRATION / "lagrangian-fluid-lab"), "worktree_root": str(F1),
        "command": ["/usr/bin/env", "VTK_SMP_MAX_THREADS=2", "LP_NUM_THREADS=2", "LIBGL_ALWAYS_SOFTWARE=1", "MESA_LOADER_DRIVER_OVERRIDE=llvmpipe", "__EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/50_mesa.json", "VTK_DEFAULT_OPENGL_WINDOW=vtkEGLRenderWindow", "QT_QPA_PLATFORM=offscreen", "OMP_NUM_THREADS=2", str(PVPYTHON), "--force-offscreen-rendering", str(worker), "--manifest", xmf_binding["root193_xmf"]["manifest"], "--output-dir", "{attempt_root}/render"],
        "binding": str(render_bind_path), "binding_sha256": sha(render_bind_path), "depends_on_attempts": [f"root-stage1-f1-{slug}-full401-paraview-dynamic-xdmf-087"], "depends_on": "fresh087 Root193 XMF completed/0 with actual manifest",
        "execution_allowed": False, "launch_allowed": False, "launch": False, "disabled": True, "source_only": True, "root_review_required": True, "launch_owner": "root", "status": "source_only_disabled_waiting_root_xmf_manifest", "production_approval": "none", "q_n": "not_assessed", "independent_case_count_increment": 0,
        "estimated_storage_bytes": 8589934592, "max_wall_seconds": 1800, "future_input_files": [xmf_binding["root193_xmf"]["manifest"], xmf_binding["root193_xmf"]["xdmf"], render_binding["typed_output_h5"]], "future_input_sha256": None,
        "future_outputs": render_binding["future_outputs"], "input_files": [str(p) for p in sorted(input_files)], "input_sha256": {str(p): sha(p) for p in input_files}, "camera_bounds_policy": "native023 auto-all-frame native bounds", "raw_arrays_read": False,
    }
    path = PACKAGE / "render/requests" / f"{case}.root194-render.request.json"; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(request, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"); return path


def build() -> None:
    ensure(not PACKAGE.exists(), f"fresh087 package already exists: {PACKAGE}")
    for path in [FRESH086, ROOT298, ROOT299, ROOT230_DIR, GPU_POLICY, RESOURCE, RUNTIME, STRICT, GOAL, PYTHON, CONVERTER, DIRECT_CONVERTER, DECODER, PARTVTK, XMF_WORKER, RENDER_WORKER, PVPYTHON, VALIDATOR]:
        ensure(Path(path).exists(), f"required path missing: {path}")
    actual_qa = {case: actual_gencase_qa(case) for case in CASES}
    actual_native_data = {case: actual_native(case) for case in CASES}
    for directory in ["definitions", "source-plans", "owners", "gencase-bindings", "gencase-initial-qa-bindings", "actual-gencase-qa-bindings", "actual-native-bindings", "native-frame0-qa-bindings", "requests", "workers", "metadata", "typed-conversion/owners", "typed-conversion/bindings", "typed-conversion/requests", "xmf/bindings", "xmf/requests", "render/bindings", "render/requests"]:
        (PACKAGE / directory).mkdir(parents=True, exist_ok=True)
    for directory in ["definitions", "source-plans", "owners", "gencase-bindings", "gencase-initial-qa-bindings", "workers"]:
        for source in sorted((FRESH086 / directory).glob("*")):
            if source.is_file():
                copy_file(source, f"{directory}/{source.name}")
    copy_file(VALIDATOR, "validate_source_contract.py")
    copy_file(Path(__file__), "build_fresh087.py")
    copy_file(XMF_WORKER, "workers/export_xmf_legacy_aware.py")
    copy_file(RENDER_WORKER, "workers/render_native023.py")
    rows = []
    for case in CASES:
        qa = actual_qa[case]; native = actual_native_data[case]
        old_bind = load(FRESH086 / "gencase-bindings" / f"{case}.actual-root283.json")
        old_owner = load(FRESH086 / "owners" / f"{case}.actual-root283.owner.json")
        old_frame_bind = load(FRESH086 / "native-frame0-qa-bindings" / f"{case}.json")
        old_frame_req = load(FRESH086 / "requests" / f"{case}.native-frame0-qa.request.json")
        owner_path = PACKAGE / "owners" / f"{case}.actual-root283.owner.json"
        definition_path = PACKAGE / "definitions" / f"{case}_Def.xml"
        source_plan_path = PACKAGE / "source-plans" / f"{case}.json"
        actual_binding = {
            "schema": "ds02.f1.fresh087.actual-root298-gencase-initial-qa-binding.v1", "family_id": "F1", "case_id": case, "stage": "pre_native_gencase_initial", "status": "completed/0", "passed": True, "returncode": 0,
            "actual_attempt_id": qa["attempt_id"], "actual_attempt_root": qa["attempt_root"], "actual_request": qa["request"], "actual_request_sha256": qa["request_sha256"], "actual_receipt": qa["receipt"], "actual_receipt_sha256": qa["receipt_sha256"], "actual_report": qa["report"], "actual_report_sha256": qa["report_sha256"], "actual_worker": qa["worker"], "actual_worker_sha256": qa["worker_sha256"], "actual_source_handoff": str(ROOT298),
            "gencase_attempt_id": old_bind["actual_gencase"]["attempt_id"], "gencase_receipt": old_bind["gencase_receipt"], "gencase_receipt_sha256": old_bind["gencase_receipt_sha256"], "generated_xml": old_bind["generated_xml"], "generated_xml_sha256": old_bind["generated_xml_sha256"], "generated_bi4": old_bind["generated_bi4"], "generated_bi4_sha256": old_bind["generated_bi4_sha256"], "prepared_input_report": old_bind["prepared_input_report"], "prepared_input_report_sha256": old_bind["prepared_input_report_sha256"], "actual_particle_counts": old_bind["actual_particle_counts"], "actual_total_particles": old_bind["actual_total_particles"], "qa_summary": qa["row"],
            "gencase_raw_velocity_claim": "not_used_as_solver_initial_velocity_proof", "mass_rescaling": False, "independent_case_count_increment": 0, "q_n": "not_assessed", "production_approval": "none", "source_only": True, "execution_allowed": False, "launch_allowed": False, "scientific_arrays_read_by_builder": False,
        }
        actual_binding_path = write_json(f"actual-gencase-qa-bindings/{case}.json", actual_binding)
        native_binding = {
            "schema": "ds02.f1.fresh087.actual-root299-native-binding.v1", "family_id": "F1", "case_id": case, "fresh_id": "fresh087", "stage": "actual_native_completed_zero_provenance", "source_only": True, "execution_allowed": False, "launch_allowed": False,
            "actual_request": native["request"], "actual_request_sha256": native["request_sha256"], "actual_attempt_id": native["attempt_id"], "actual_receipt": native["receipt"], "actual_receipt_sha256": native["receipt_sha256"], "actual_receipt_status": native["receipt_status"], "actual_receipt_returncode": native["receipt_returncode"], "actual_receipt_termination_reason": native["receipt_termination_reason"], "actual_output_root": native["output_root"], "actual_native_data_root": native["data_root"], "actual_solver_log": native["run_out"], "actual_solver_log_sha256": native["run_out_sha256"],
            "actual_output_inventory": native["actual_output_inventory"], "expected_frame_count": native["expected_frame_count"], "observed_frame_file_count": native["observed_frame_file_count"], "actual_native_particle_counts": None, "actual_native_particle_counts_status": "not_present_in_execution_receipt; Root298 GenCase/initial-QA counts are the actual input counts", "actual_native_output_hash": None,
            "root299_request_status_at_launch": native["request_data"].get("status"), "root299_request_command": native["request_data"].get("command"), "root299_actual_solver_command": native["solver_command"], "root299_request_command_sha256": sha(native["request"]), "root299_worktree_root": native["request_data"].get("worktree_root"), "root299_runner_source": native["receipt_data"].get("runner_source"), "root299_runner_sha256": native["receipt_data"].get("runner_sha256"),
            "root298_gencase_qa": {"attempt_id": qa["attempt_id"], "receipt": qa["receipt"], "receipt_sha256": qa["receipt_sha256"], "report": qa["report"], "report_sha256": qa["report_sha256"], "passed": True, "actual_particle_counts": old_bind["actual_particle_counts"], "actual_total_particles": old_bind["actual_total_particles"]},
            "canonical_owner": str(owner_path), "canonical_owner_sha256": sha(owner_path), "physical_case_id": old_owner["physical_case_id"], "physical_condition_sha256": old_owner["physical_condition_sha256"], "source_plan_condition_sha256": old_owner.get("source_plan_condition_sha256"), "numerical_recipe": native["request_data"].get("numerical_recipe", old_bind.get("numerical_recipe")), "no_solver_option_mutation": True, "production_approval": "none", "q_n": "not_assessed", "independent_case_count_increment": 0,
        }
        native_binding_path = write_json(f"actual-native-bindings/{case}.json", native_binding)
        frame_attempt = f"root-stage1-f1-{case.lower()}-native-frame0-height-qa-087"
        frame_root = DATA / case / frame_attempt
        frame_bind = frame_binding(case, old_bind, old_frame_bind, qa, native, PACKAGE / "native-frame0-qa-bindings" / f"{case}.json")
        frame_bind_path = write_json(f"native-frame0-qa-bindings/{case}.json", frame_bind)
        frame_req = frame_request(case, frame_attempt, frame_bind_path, frame_bind, native, old_frame_req, frame_root)
        frame_req_path = write_json(f"requests/{case}.native-frame0-qa.request.json", frame_req)
        # Actual native provenance is recorded separately; there is no new native request.
        write_json(f"metadata/root299-native-provenance/{case}.json", native)
        owner, typed_owner_path = typed_owner(case, old_owner, owner_path, definition_path, source_plan_path, native, qa)
        typed_binding, typed_binding_path, typed_req_path = typed_request(case, old_owner, owner_path, definition_path, source_plan_path, qa, native, frame_req_path, typed_owner_path)
        xmf_bind, xmf_bind_path = xmf_binding(case, owner, owner_path, typed_owner_path, typed_req_path, typed_binding, definition_path, source_plan_path, native, qa, frame_req_path)
        xmf_req_path = xmf_request(case, xmf_bind_path, xmf_bind, typed_req_path, native)
        render_bind, render_bind_path = render_binding(case, xmf_bind, xmf_bind_path, owner_path, typed_owner_path, native, owner)
        render_req_path = render_request(case, render_bind_path, render_bind, xmf_req_path, xmf_bind, native)
        rows.append({"case_id": case, "actual_gencase_qa_receipt": qa["receipt"], "actual_gencase_qa_receipt_sha256": qa["receipt_sha256"], "actual_gencase_qa_report": qa["report"], "actual_gencase_qa_report_sha256": qa["report_sha256"], "actual_native_attempt_id": native["attempt_id"], "actual_native_receipt": native["receipt"], "actual_native_receipt_sha256": native["receipt_sha256"], "actual_native_expected_frames": native["expected_frame_count"], "actual_native_observed_frame_file_count": native["observed_frame_file_count"], "actual_native_particle_counts": None, "frame0_request": str(frame_req_path), "typed_request": str(typed_req_path), "xmf_request": str(xmf_req_path), "render_request": str(render_req_path), "status": "Root299_completed_zero_downstream_source_disabled"})
    write_json("metadata/fresh086-lineage.json", {"schema": "ds02.f1.fresh087.fresh086-lineage.v1", "source_package": str(FRESH086), "source_commit": "0806ab224fcb82288f75265f6bb4e9af8abfb9b4", "source_unchanged": True, "canonical_recipe_and_owner_preserved": True, "fresh085_cycle_and_root298_path_failure_preserved": True})
    review = ROOT298 / "source-repair-review.json"
    write_json("metadata/root298-provenance.json", {"schema": "ds02.f1.fresh087.root298-provenance.v1", "handoff": str(ROOT298), "review_file": str(review), "review_sha256": sha(review), "purpose": "actual GenCase initial QA path-type repair completed/0; no solver/native evidence in this file"})
    write_json("metadata/root299-native-summary.json", {"schema": "ds02.f1.fresh087.root299-native-summary.v1", "handoff": str(ROOT299), "actual_case_count": 8, "all_completed_zero": True, "cases": rows, "part_bi4_inventory_count_is_metadata_only": True, "scientific_arrays_read_by_source_builder": False, "scientific_arrays_hashed_by_source_builder": False, "independent_case_count_increment": 0, "q_n": "not_assessed", "production_approval": "none"})
    write_json("metadata/candidate-registry.json", {"schema": "ds02.f1.fresh087.root299-downstream-candidate-registry.v1", "family_id": "F1", "fresh_id": "fresh087", "scope_id": "F1_STAGE1_FIRST24_HEIGHT_EXTENSION_V1", "source_only": True, "execution_allowed": False, "launch_allowed": False, "actual_root298_gencase_qa_count": 8, "actual_root299_native_completed_zero_count": 8, "native_frame0_qa_requests_disabled": 8, "typed_conversion_requests_disabled": 8, "xmf_requests_disabled": 8, "render_requests_disabled": 8, "cases": rows, "independent_case_count_increment": 0, "q_n": "not_assessed", "production_approval": "none"})
    write_json("metadata/root230-policy.json", {"schema": "ds02.f1.fresh087.root230-policy-binding.v1", "dispatch": dispatch(), "root_solver_concurrency_cap": 8, "source_only": True, "disabled": True, "launch_allowed": False, "physical_and_solver_recipe_unchanged": True, "native_provenance": "Root299 actual requests/receipts; no fresh087 native request"})
    readme = f"""# F1 fresh087: Root298 QA -> actual Root299 native -> downstream source handoff

Fresh086 remains immutable at `{FRESH086}` (commit `0806ab224fcb82288f75265f6bb4e9af8abfb9b4`). The historical fresh085 circular source and Root298's earlier path-type failure remain recorded as evidence. Root298's corrected GenCase initial QA produced eight actual completed/0 reports with `passed=true`; those exact request, receipt, report, worker, and producer hashes are bound under `actual-gencase-qa-bindings/`.

Root has already executed the eight native cases through the Root299 adapter. `actual-native-bindings/` records the exact Root299 request and completed/0 receipt path/SHA, BASE command/options, output root, Run.out SHA, and a metadata-only `Part_*.bi4` filename count (401 DUAL or 161 ECC). The receipt does not contain native particle counts or a scientific output digest, so those fields remain null. GenCase/Root298 initial-QA counts are labelled as input counts and are never relabelled as solver-observed counts. The builder did not open or hash BI4, H5, CSV, or VTK arrays.

The eight disabled downstream frame-0 PartVTK QA requests depend on the actual Root299 attempt IDs and use actual completed/0 native receipt hashes; frame-0 BI4 hashes and QA reports remain null. Disabled typed NVME conversion requests then depend on a future frame-0 pass, followed by disabled XMF and Root023 renderer requests. All future H5/XMF/render hashes remain null until Root runs the corresponding registered CPU tasks. Canonical owner/physical condition hashes, DP, solver options, windows, initial velocity, and source geometry are preserved without a new native launch request or a production/Q-N claim.

The package is source-only: no solver, GenCase, conversion, XMF, renderer, array read, shared registry/ledger write, or launch occurred while building it.
"""
    (PACKAGE / "README.md").write_text(readme, encoding="utf-8")
    # Static validation is deliberately a source-only Python check.
    import subprocess
    subprocess.run([str(PYTHON), str(PACKAGE / "validate_source_contract.py"), "--output", str(PACKAGE / "metadata/static-validation.json")], check=True)
    files = []
    for path in sorted(PACKAGE.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            files.append({"path": str(path.relative_to(PACKAGE)), "bytes": path.stat().st_size, "sha256": sha(path)})
    write_json("manifest.json", {"schema": "ds02.f1.fresh087-root299-downstream-manifest.v1", "family_id": "F1", "fresh_id": "fresh087", "commit_scope": str(PACKAGE), "files": files, "actual_root298_gencase_qa_count": 8, "actual_root299_native_completed_zero_count": 8, "native_frame0_request_count": 8, "typed_request_count": 8, "xmf_request_count": 8, "render_request_count": 8, "dependency_graph": "Root283 -> Root298 GenCase QA completed/0 -> actual Root299 native completed/0 -> disabled frame0 QA -> disabled typed NVME -> disabled XMF -> disabled Root023 render", "arrays_read": False, "arrays_hashed": False, "execution_allowed": False, "launch_allowed": False, "shared_registry_or_ledger_modified": False})
    print(json.dumps({"package": str(PACKAGE), "cases": 8, "root298_qa_completed_zero": 8, "root299_native_completed_zero": 8, "frame0_requests": 8, "typed_requests": 8, "xmf_requests": 8, "render_requests": 8}, indent=2))


if __name__ == "__main__":
    build()
