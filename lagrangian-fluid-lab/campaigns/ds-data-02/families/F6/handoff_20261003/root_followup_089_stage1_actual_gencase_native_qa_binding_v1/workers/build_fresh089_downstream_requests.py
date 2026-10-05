#!/usr/bin/env python3
"""Build fresh089 disabled native and FloatingInfo metadata requests.

This builder is intentionally metadata-only.  It reads JSON/XML/source files
and producer-attested BI4 digests from Root539's prepared reports; it never
opens or hashes a BI4/H5/CSV/DAT payload and never dispatches a job.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[8]
PACKAGE = ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/root_followup_089_stage1_actual_gencase_native_qa_binding_v1"
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
H = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003"
ACTUAL = PACKAGE / "metadata/root539-actual-gencase-binding.json"
QA = PACKAGE / "qa/initial-native-qa-binding.json"
QA_REQUEST = PACKAGE / "qa/requests/root539-mechanical-pose-initial-native-qa-089.json"
SOURCE088 = PACKAGE.parent / "root_followup_088_stage1_mechanical_pose_omega_extension_v1"
ROOT230 = H / "root_stage1_native_home_floor_eight_solver_dispatch_230"
GPU_POLICY = H / "root_stage1_f3_first24_eight_solver_resource_policy_134/ds02_root_all_idle_gpu_policy_v2.py"
RUNTIME = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
STRICT = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py"
GOAL = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/GOAL_STAGE1_VISUAL_GPT56LUNA_20261004_ZH.md"
RESOURCE = H / "root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json"
PYTHON = INTEGRATION / "lagrangian-fluid-lab/.venv/bin/python"
SOLVER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64")
FLOATINGINFO = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/FloatingInfo_linux64")
FLOATINGINFO_SHA = "62630430902484f4aede017108313673fe6414f40fb59b6ae7f14ac23219db00"
ROOT230_LAUNCH = ROOT230 / "launch.py"
ROOT230_POLICY = ROOT230 / "root_native_home_floor_inventory_policy.py"
NATIVE_WORKER = PACKAGE / "workers/run_f6_initial_native_qa_stage24_fresh089.py"
NATIVE_VALIDATOR = PACKAGE / "workers/validate_actual_gencase_root539_binding.py"
STATE0_WORKER = PACKAGE / "workers/run_f6_state0_omega_fresh089.py"
STATE0_AUDIT = PACKAGE / "workers/audit_f6_endpoint_floatinginfo_state0_fresh089.py"

COUNTS = {"fixed": 73441, "moving": 0, "floating": 16384, "fluid": 327680, "total": 417505}


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def metadata_files(endpoint: dict[str, Any], include_qa: bool = True) -> tuple[list[str], dict[str, str], dict[str, str]]:
    actual = endpoint["actual_gencase"]
    files: list[Path] = [
        Path(endpoint["canonical_owner"]), Path(endpoint["source_definition"]),
        SOURCE088 / "metadata/mechanical-pose-plan.json",
        SOURCE088 / "metadata/source-build-receipt.json",
        SOURCE088 / "metadata/source-validation-report.json",
        SOURCE088 / "metadata/dedup-registry.json",
        Path(actual["request"]), Path(actual["execution_receipt"]),
        Path(actual["prepared_input_report"]), Path(endpoint["generated_xml"]),
        ACTUAL, PACKAGE / "metadata/root539-review.json",
        NATIVE_WORKER, NATIVE_VALIDATOR, ROOT230_LAUNCH, ROOT230_POLICY,
        GPU_POLICY, RUNTIME, STRICT, GOAL, RESOURCE, PYTHON,
    ]
    if include_qa:
        files.extend([QA, QA_REQUEST])
    seen: set[str] = set(); ordered: list[Path] = []
    for path in files:
        if str(path) not in seen:
            seen.add(str(path)); ordered.append(path)
    # The producer report is the only authority for BI4's digest.  The path is
    # represented in input_files, but the payload itself is never opened here.
    bi4 = Path(endpoint["generated_bi4"])
    ordered.append(bi4)
    input_files = [str(path) for path in ordered]
    input_sha: dict[str, str] = {}
    sources: dict[str, str] = {}
    for path in ordered:
        if path == bi4:
            digest = str(endpoint["generated_bi4_sha256"])
            input_sha[str(path)] = digest
            sources[str(path)] = "Root539 prepared-input-report.json producer BI4 attestation; payload not read or hashed"
        else:
            if not path.is_file():
                raise FileNotFoundError(path)
            input_sha[str(path)] = sha(path)
            sources[str(path)] = "metadata/source hash"
    return input_files, input_sha, sources


def actual_initial_qa() -> dict[str, Any]:
    return {
        "status": "pending_root_actual_strict_cpu_qa",
        "pass": None,
        "attempt_id": "root-stage1-f6-mechanical-pose-omega-initial-native-qa-089",
        "binding": str(QA), "binding_sha256": sha(QA),
        "request": str(QA_REQUEST), "request_sha256": sha(QA_REQUEST),
        "receipt": str(DATA / "families/F6/F6_STAGE1_ANGULAR_RELEASE_MECHANICAL_POSE_OMEGA_BATCH/root-stage1-f6-mechanical-pose-omega-initial-native-qa-089/execution-receipt.json"),
        "receipt_sha256": None, "index": None, "index_sha256": None,
        "report": None, "report_sha256": None,
    }


def build_native(endpoint: dict[str, Any]) -> dict[str, Any]:
    case = str(endpoint["endpoint_id"])
    actual = endpoint["actual_gencase"]
    actual_xml = Path(endpoint["generated_xml"])
    prefix = str(actual_xml.with_suffix(""))
    attempt_root = DATA / "families/F6" / case / f"root-stage1-f6-{case.lower().replace('_', '-')}-full241-native-qualification-089"
    request_path = PACKAGE / "qualification/requests" / f"{case}-full241-native-qualification-089.json"
    files, hashes, sources = metadata_files(endpoint)
    owner = json.loads(Path(endpoint["canonical_owner"]).read_text())
    source_request = json.loads((SOURCE088 / "gencase/requests" / f"{case}.genuine-gencase-request.json").read_text())
    command = [str(SOLVER), prefix, "{attempt_root}/solver_output", "-tmax:12", "-tout:0.05"]
    runtime_command = [str(SOLVER), "-gpu:0", prefix, "{attempt_root}/solver_output", "-tmax:12", "-tout:0.05"]
    request = {
        "schema": "ds02.runner-request.v2", "fresh_id": "fresh089", "family_id": "F6",
        "scope_id": "root_followup_089_stage1_actual_gencase_native_qa_binding_v1",
        "binding": str(QA), "worker": str(NATIVE_WORKER),
        "kind": "qualification", "status": "source_only_disabled", "source_only": True,
        "disabled": True, "launch": False, "launch_allowed": False, "execution_allowed": False,
        "root_only": True, "launch_owner": "root", "root_review_required": True,
        "disabled_reason": "fresh089 source-only; Root may enable only after fresh089 strict PartVTK initial QA completes/0 and then use Root230 Home-floor native dispatch",
        "claim_boundary": "Root539 GenCase completed/0 plus disabled full241 recipe only; no native solver, FloatingInfo state0, typed, XMF/render, visual, Q-N, precision, or production result",
        "case_id": case, "physical_case_id": case, "topphysical_case_id": "F6_STAGE1_ANGULAR_RELEASE_MECHANICAL_POSE_OMEGA_BATCH",
        "physical_condition_sha256": endpoint["physical_condition_sha256"],
        "source_plan_condition_sha256": endpoint["source_plan_condition_sha256"],
        "canonical_owner": endpoint["canonical_owner"], "canonical_owner_sha256": endpoint["canonical_owner_sha256"],
        "source_definition": endpoint["source_definition"], "source_definition_sha256": endpoint["source_definition_sha256"],
        "scale": owner.get("physical_binding", {}).get("source_variant", {}).get("omega_scale"),
        "initial_angular_velocity_rad_s": endpoint["omega_rad_s"],
        "initial_orientation_axis_angle": endpoint["initial_orientation_axis_angle"],
        "cwd": str(Path(actual["attempt_root"])), "worktree_root": str(ROOT),
        "attempt_id": attempt_root.name, "attempt_root": str(attempt_root),
        "command": command, "runtime_command_template": runtime_command,
        "command_derivation": "exact mother native argv/options; actual Root539 prepared XML/BI4 stem and fresh089 attempt_root substituted; Root230 injects live UUID GPU visibility",
        "time_options": ["-tmax:12", "-tout:0.05"], "full_event_window_s": [0.0, 12.0],
        "expected_native_frames": 241, "physical_window_s": [0.0, 12.0],
        "cpu_threads": 4, "max_wall_seconds": 14400, "estimated_peak_gpu_mib": 8192, "estimated_storage_bytes": 17179869184,
        "no_forcing": True, "no_mdbc": True, "no_solver_option_mutation": True,
        "forbidden_options": ["-dbc", "-mdbc", "-forcing", "-motion", "-cpu"],
        "expected_native_contract": {"dimension": 3, **COUNTS, "true_3d": True, "center_m": [2.4, 1.2, 1.08], "fixed_type": 0, "fixed_mk": 30, "floating_type": 2, "floating_mk": 60, "fluid_type": 3, "fluid_mk": 1, "identity_key": "(Zone,Idp)", "counts_status": "Root strict PartVTK must confirm after native execution"},
        "native_identity_contract": {"dimension": 3, "total": COUNTS["total"], "fixed": COUNTS["fixed"], "moving": 0, "floating": COUNTS["floating"], "fluid": COUNTS["fluid"], "fixed_type": 0, "fixed_mk": 30, "floating_type": 2, "floating_mk": 60, "fluid_type": 3, "fluid_mk": 1, "center_m": [2.4, 1.2, 1.08], "identity_key": "(Zone,Idp)", "true_3d": True, "counts_status": "actual GenCase metadata; native PartVTK remains future"},
        "mass_policy": {"physical_rigid_mass_kg": 128.0, "native_support_mass_kg": 256.0, "solver_interaction_masspart_kg": 0.015625, "normalization": "none", "equality_required": False},
        "gencase_actual": {"status": "completed", "returncode": 0, "dimension": 3, "total": COUNTS["total"], "fluid": COUNTS["fluid"], "receipt": actual["execution_receipt"], "prepared_input_report": actual["prepared_input_report"]},
        "gencase_xml": actual["generated_xml"], "gencase_xml_sha256": actual["generated_xml_sha256"],
        "gencase_bi4": actual["generated_bi4"], "gencase_bi4_sha256": actual["generated_bi4_sha256"],
        "gencase_receipt": actual["execution_receipt"], "gencase_receipt_sha256": actual["execution_receipt_sha256"],
        "prepared_input_report": actual["prepared_input_report"], "prepared_input_report_sha256": actual["prepared_input_report_sha256"],
        "producer_bi4_attestation": actual["producer_bi4_attestation"],
        "actual_initial_qa": actual_initial_qa(),
        "floatinginfo_state0": {"status": "future_required_after_full241_native_completed0", "binding": str(PACKAGE / "floatinginfo/state0-binding.json"), "binding_sha256": None, "observed_omega_rad_s": None, "audit_sha256": None},
        "future_outputs": {"native_execution_receipt": str(attempt_root / "execution-receipt.json"), "native_execution_receipt_sha256": None, "native_data_root": str(attempt_root / "solver_output/data"), "native_frames": 241, "floatinginfo_state0": None, "typed_conversion": None},
        "future_input_files": [], "future_input_sha256": {},
        "input_files": files, "input_sha256": hashes, "input_hash_sources": sources,
        "root_actual_launch_source": str(ROOT230_LAUNCH), "root_actual_launch_source_sha256": sha(ROOT230_LAUNCH),
        "root_inventory_policy_source": str(ROOT230_POLICY), "root_inventory_policy_source_sha256": sha(ROOT230_POLICY),
        "root_dataset_inventory_profile": "root_home_floor_no_legacy_dataset_walk_native_v1",
        "root_gpu_selection_profile": "root_live_all_idle_uuid_leased_eight_solver_v2",
        "root_solver_concurrency_cap": 8,
        "execution_policy": "Root230 Home-floor native dispatch with live UUID lease at enable time; exact mother 12 s / 0.05 s / 241-frame recipe; Root146 is historical provenance only and is not an execution entry",
        "historical_source_execution_entry_not_used": str(source_request.get("root_actual_launch_source", "")),
        "source_build_receipt": str(SOURCE088 / "metadata/source-build-receipt.json"), "source_build_receipt_sha256": sha(SOURCE088 / "metadata/source-build-receipt.json"),
        "root_resource_window": {"gpu_hours": 512, "cpu_core_hours": 3840, "qualification_hours": 1024, "production_hours": 720, "home_floor_gib": 500, "deadline": "2026-10-14T07:23:48Z"},
        "root_actual_launch_entry": "Root230 launch.py -> ds_data02_runtime_v2 + strict dispatch + live UUID/Home-floor policies",
        "production_approval": "none", "precision_status": "not_accepted", "q_n": "not_granted", "independent_case_count_increment": 0,
        "no_array_read_by_source_package": True, "no_jobs_started_by_source_package": True,
    }
    dump(request_path, request)
    return request


def build_state0(native_requests: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    binding_path = PACKAGE / "floatinginfo/state0-binding.json"
    cases: list[dict[str, Any]] = []
    for request in native_requests:
        case = request["case_id"]
        out = Path(request["attempt_root"])
        ep = next(item for item in json.loads(QA.read_text())["endpoints"] if item["endpoint_id"] == case)
        actual = ep["actual_gencase"]
        cases.append({
            "case_id": case, "physical_condition_sha256": request["physical_condition_sha256"], "source_plan_condition_sha256": request["source_plan_condition_sha256"],
            "canonical_owner": request["canonical_owner"], "canonical_owner_sha256": request["canonical_owner_sha256"],
            "declared_omega_rad_s": request["initial_angular_velocity_rad_s"],
            "endpoint_xml": request["gencase_xml"], "endpoint_xml_sha256": request["gencase_xml_sha256"],
            "gencase_receipt": request["gencase_receipt"], "gencase_receipt_sha256": request["gencase_receipt_sha256"],
            "gencase_report": actual["prepared_input_report"], "gencase_report_sha256": actual["prepared_input_report_sha256"],
            "gencase_bi4": request["gencase_bi4"], "gencase_bi4_sha256": request["gencase_bi4_sha256"],
            "native_request": str(PACKAGE / "qualification/requests" / f"{case}-full241-native-qualification-089.json"), "native_request_sha256": None,
            "native_data": str(out / "solver_output/data"), "run_out": str(out / "solver_output/Run.out"),
            "solver_receipt": str(out / "execution-receipt.json"), "solver_receipt_sha256": None, "solver_status_snapshot": None, "solver_returncode_snapshot": None,
            "state0_future_outputs": {"audit": str(DATA / "families/F6" / "F6_STAGE1_ANGULAR_RELEASE_MECHANICAL_POSE_OMEGA_BATCH/root-stage1-f6-mechanical-pose-omega-state0-floatinginfo-089/audit" / case / "state0-omega-audit.json"), "audit_sha256": None},
        })
    binding = {
        "schema": "ds02.f6.endpoint-floatinginfo-state0-omega-binding.v2", "fresh_id": "fresh089", "family_id": "F6", "scope_id": "root_followup_089_stage1_actual_gencase_native_qa_binding_v1",
        "status": "source_only_disabled", "source_only": True, "launch_allowed": False, "execution_allowed": False, "case_count": len(cases), "cases": cases,
        "actual_gencase_completed0_all24": True, "actual_native_receipts_completed0_all24": False,
        "floatinginfo_binary": str(FLOATINGINFO), "floatinginfo_binary_sha256": FLOATINGINFO_SHA,
        "runner_worker": str(STATE0_WORKER), "runner_worker_sha256": sha(STATE0_WORKER), "audit_worker": str(STATE0_AUDIT), "audit_worker_sha256": sha(STATE0_AUDIT),
        "native_qualification_requests_dir": str(PACKAGE / "qualification/requests"), "native_qualification_request_sha256": None,
        "native_entry_policy": {"entry": str(ROOT230_LAUNCH), "entry_sha256": sha(ROOT230_LAUNCH), "policy": str(ROOT230_POLICY), "policy_sha256": sha(ROOT230_POLICY), "live_uuid_lease": "Root230 evaluates idle UUIDs at enable time", "root_solver_concurrency_cap": 8},
        "native_contract": {"dimension": 3, "fixed": COUNTS["fixed"], "moving": 0, "floating": COUNTS["floating"], "fluid": COUNTS["fluid"], "total": COUNTS["total"], "floating_type": 2, "floating_mk": 60, "frames": 241, "tout_s": 0.05, "window_s": [0.0, 12.0], "vector_shape": [COUNTS["total"], 3]},
        "expected_omega_source": "each case's generated XML angularvelini plus canonical owner and actual FloatingInfo state0; particle V0 is not an angular-state proof",
        "particle_v0_policy": "V0=0 does not prove zero angular velocity",
        "mass_policy": {"physical_mass_kg": 128.0, "native_support_mass_kg": 256.0, "masspart_kg": 0.015625, "normalization": "none"},
        "future_hashes_null": True, "future_outputs": {"execution_receipt": str(DATA / "families/F6/F6_STAGE1_ANGULAR_RELEASE_MECHANICAL_POSE_OMEGA_BATCH/root-stage1-f6-mechanical-pose-omega-state0-floatinginfo-089/execution-receipt.json"), "execution_receipt_sha256": None, "summary": str(DATA / "families/F6/F6_STAGE1_ANGULAR_RELEASE_MECHANICAL_POSE_OMEGA_BATCH/root-stage1-f6-mechanical-pose-omega-state0-floatinginfo-089/audit/eight-endpoint-omega-summary.json"), "summary_sha256": None, "observed_omega_rad_s": None, "independent_case_count_increment": 0},
        "no_arrays_read": True, "no_jobs_started": True, "no_shared_registry_write": True,
        "claim_boundary": "Disabled future FloatingInfo state-zero corroboration only; no solver completion, typed/XMF/render, visual, Q-N, precision, or production result",
    }
    dump(binding_path, binding)
    # State0 request's current input closure is metadata only; native output
    # receipt/Run.out/PartFloatInfo remain future and null.
    files: list[Path] = [binding_path, QA, QA_REQUEST, STATE0_WORKER, STATE0_AUDIT, RUNTIME, STRICT, ROOT230_LAUNCH, ROOT230_POLICY, GPU_POLICY, GOAL, RESOURCE, PYTHON, FLOATINGINFO]
    files.extend(Path(req["canonical_owner"]) for req in native_requests)
    files.extend(Path(req["gencase_xml"]) for req in native_requests)
    files.extend(Path(req["gencase_receipt"]) for req in native_requests)
    files.extend(Path(req["prepared_input_report"]) for req in native_requests)
    files.extend(Path(req["gencase_bi4"]) for req in native_requests)
    files.extend(PACKAGE / "metadata/root539-actual-gencase-binding.json" for _ in [0])
    unique: list[Path] = []; seen: set[str] = set()
    input_hash: dict[str, str | None] = {}; sources: dict[str, str] = {}
    for path in files:
        key = str(path)
        if key in seen: continue
        seen.add(key); unique.append(path)
        if path.suffix.lower() == ".bi4":
            req = next(req for req in native_requests if req["gencase_bi4"] == key)
            input_hash[key] = req["gencase_bi4_sha256"]; sources[key] = "Root539 producer attestation only; payload not read or hashed"
        else:
            if not path.is_file(): raise FileNotFoundError(path)
            input_hash[key] = sha(path); sources[key] = "metadata/source hash"
    request_path = PACKAGE / "floatinginfo/state0-request.json"
    request = {
        "schema": "ds02.runner-request.v2", "fresh_id": "fresh089", "family_id": "F6", "scope_id": binding["scope_id"],
        "kind": "audit", "status": "source_only_disabled", "source_only": True, "disabled": True, "launch": False, "launch_allowed": False, "execution_allowed": False, "launch_owner": "root", "root_only": True, "root_review_required": True,
        "request_id": "f6-mechanical-pose-omega-state0-floatinginfo-089", "attempt_id": "root-stage1-f6-mechanical-pose-omega-state0-floatinginfo-089", "attempt_root": str(DATA / "families/F6/F6_STAGE1_ANGULAR_RELEASE_MECHANICAL_POSE_OMEGA_BATCH/root-stage1-f6-mechanical-pose-omega-state0-floatinginfo-089"), "cwd": str(INTEGRATION / "lagrangian-fluid-lab"), "worktree_root": str(ROOT),
        "binding": str(binding_path), "binding_sha256": sha(binding_path),
        "command": [str(PYTHON), str(STATE0_WORKER), "--binding", str(binding_path), "--output-dir", "{attempt_root}/audit", "--floating-info-exe", str(FLOATINGINFO)],
        "cpu_task_kind": "audit", "cpu_threads": 2, "max_wall_seconds": 7200, "estimated_storage_bytes": 536870912,
        "disabled_reason": "disabled until all fresh089 full241 native receipts are terminal completed/0; each state0 audit must use its own XML/owner/receipt",
        "expected_native_contract": binding["native_contract"], "expected_omega_source": binding["expected_omega_source"], "future_hashes_null": True,
        "future_input_files": [path for case in cases for path in (case["solver_receipt"], case["run_out"], str(Path(case["native_data"]) / "PartFloatInfo.ibi4"))],
        "future_input_sha256": {path: None for case in cases for path in (case["solver_receipt"], case["run_out"], str(Path(case["native_data"]) / "PartFloatInfo.ibi4"))},
        "future_outputs": binding["future_outputs"], "input_files": [str(p) for p in unique], "input_sha256": input_hash, "input_hash_sources": sources,
        "root_entry_policy": "Root142 CPU audit policy after Root230 native qualification; no direct solver launch and no Root146 execution entry",
        "root_actual_native_entry": str(ROOT230_LAUNCH), "root_actual_native_entry_sha256": sha(ROOT230_LAUNCH),
        "expected_omega_source": binding["expected_omega_source"], "particle_v0_policy": binding["particle_v0_policy"],
        "mass_policy": binding["mass_policy"], "no_array_read_by_source_package": True, "no_jobs_started": True,
        "precision_status": "not_accepted", "production_approval": "none", "q_n_status": "not_assessed", "claim_boundary": binding["claim_boundary"],
    }
    dump(request_path, request)
    return binding, request


def main() -> int:
    actual = json.loads(ACTUAL.read_text())
    qa = json.loads(QA.read_text())
    endpoints = qa["endpoints"]
    if len(endpoints) != 24 or not actual.get("actual_completed0_all24"):
        raise RuntimeError("fresh089 requires 24 completed/0 Root539 records")
    native_requests = [build_native(endpoint) for endpoint in endpoints]
    build_state0(native_requests)
    print(json.dumps({"fresh_id": "fresh089", "native_requests": len(native_requests), "state0": str(PACKAGE / "floatinginfo/state0-request.json"), "disabled": True, "bi4_payloads_opened": False}, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
