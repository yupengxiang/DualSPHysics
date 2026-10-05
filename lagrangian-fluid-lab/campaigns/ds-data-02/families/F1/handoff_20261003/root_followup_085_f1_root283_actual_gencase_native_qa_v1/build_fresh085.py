#!/usr/bin/env python3
from __future__ import annotations
import copy, hashlib, json, shutil
from pathlib import Path

F1 = Path("/home/jade/.codex/worktrees/ds-data-02-f1/DualSPHysics")
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1")
OLD = F1 / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F1/handoff_20261003/root_followup_084_f1_first24_height_extension_v1"
PACKAGE = F1 / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F1/handoff_20261003/root_followup_085_f1_root283_actual_gencase_native_qa_v1"
VALIDATOR = Path("/tmp/validate_f1_fresh085.py")
WORKER = Path("/tmp/f1_native_initial_qa_fresh085.py")
ROOT283_HANDOFF = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f1_first24_eight_height_genuine_gencase_283"
ROOT230_DIR = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_native_home_floor_eight_solver_dispatch_230"
GPU_POLICY = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f3_first24_eight_solver_resource_policy_134/ds02_root_all_idle_gpu_policy_v2.py"
RESOURCE_WINDOW = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json"
RUNTIME = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
STRICT = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py"
GOAL = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/GOAL_STAGE1_VISUAL_GPT56LUNA_20261004_ZH.md"
PYTHON = F1 / "lagrangian-fluid-lab/.venv/bin/python"
PARTVTK = F1 / "lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64"
SOLVER = F1 / "lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64"
SCOPE = "F1_STAGE1_FIRST24_HEIGHT_EXTENSION_V1"
PARTVTK_SHA = "62630430902484f4aede017108313673fe6414f40fb59b6ae7f14ac23219db00"
ROOT230 = {
    "profile": "root_home_floor_no_legacy_dataset_walk_native_v1",
    "gpu_profile": "root_live_all_idle_uuid_leased_eight_solver_v2",
    "entry_sha256": "7f703fb94e17c2e2800873f4fcc021f9cd5f8201076afd8e10e3bc6a2d03396e",
    "gpu_sha256": "4e6f340222f7823ae9df1a145ccda884dcf401c9740fc78c51a88066ae1c88cd",
    "home_sha256": "c9103e306f87bb5af871c5de28d9939aa05f0c95c72e1630778f4bcf50e91ab5",
    "resource_sha256": "2a35e26e36920d8ca40001fd7f28416f27bcf371b8b882eca37868f4a15152b8",
    "source_policy_sha256": "42f1af21e8e663234198b6a2f3f87a86b178d11fe3ca8a939467ae97d64e4326",
    "reservation_sha256": "46e62ea197862a833797556d09350126b3632b2e3b1d496d08816ee42f7abecf",
}
CASES = [
    "F1_STAGE1_DUAL_H240_DP020", "F1_STAGE1_DUAL_H240_DP020_VX010",
    "F1_STAGE1_DUAL_H280_DP020", "F1_STAGE1_DUAL_H320_DP020",
    "F1_STAGE1_ECC_H120_DP010", "F1_STAGE1_ECC_H140_DP010",
    "F1_STAGE1_ECC_H160_DP010", "F1_STAGE1_ECC_H180_DP010",
]

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

def sha(path: Path) -> str:
    if path.suffix.lower() in {".bi4", ".h5", ".hdf5", ".csv", ".npy", ".npz", ".vtk"}:
        raise RuntimeError("scientific array hashing is forbidden: " + str(path))
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()

def load(path: Path):
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("expected JSON object: " + str(path))
    return value

def require(value, message):
    if not value:
        raise RuntimeError(message)

def write_json(rel, value):
    path = PACKAGE / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return path

def copy_source(rel):
    source, target = OLD / rel, PACKAGE / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target

def find_actual(case_id):
    reports = sorted(DATA.glob(case_id + "/root-stage1-f1-*-genuine-gencase-283/prepared/prepared-input-report.json"))
    require(len(reports) == 1, case_id + ": expected one Root283 nested report, got " + str(len(reports)))
    report_path = reports[0]
    receipt_path = report_path.parents[1] / "execution-receipt.json"
    require(receipt_path.is_file(), case_id + ": Root283 receipt missing")
    report, receipt = load(report_path), load(receipt_path)
    require(report.get("case_id") == case_id, case_id + ": report case mismatch")
    require(receipt.get("status") == "completed" and receipt.get("returncode") == 0, case_id + ": Root283 receipt not completed/0")
    counts = report.get("generated_xml_particle_counts")
    require(isinstance(counts, dict), case_id + ": generated_xml_particle_counts missing")
    actual_counts = {
        "fixed": int(counts["fixed"]), "moving": int(counts.get("moving", 0)),
        "floating": int(counts.get("floating", 0)), "fluid": int(counts["fluid"])
    }
    total = int(report["actual_total_particles"])
    require(total == sum(actual_counts.values()), case_id + ": dynamic count sum mismatch")
    require(str(report.get("actual_generated_constants", {}).get("data2d", {}).get("value", "")).lower() == "false", case_id + ": report data2d is not false")
    require(report.get("xml_sha256") and report.get("bi4_sha256"), case_id + ": producer artifact digests missing")
    prefix = Path(report["prefix"])
    return {
        "report_path": report_path, "receipt_path": receipt_path, "report": report, "receipt": receipt,
        "attempt_root": report_path.parents[1],
        "attempt_id": receipt.get("request", {}).get("attempt_id", report_path.parents[1].name),
        "generated_xml": Path(str(prefix) + ".xml"), "generated_bi4": Path(str(prefix) + ".bi4"),
        "report_sha256": sha(report_path), "receipt_sha256": sha(receipt_path),
        "generated_xml_sha256": report["xml_sha256"], "generated_bi4_sha256": report["bi4_sha256"],
        "actual_particle_counts": actual_counts, "actual_total_particles": total,
    }

def input_hash(path, report=None):
    if report is not None:
        if path.suffix.lower() == ".bi4":
            return report["bi4_sha256"]
        if path.suffix.lower() == ".xml" and "/Projects/DualSPHysics-data/" in str(path):
            return report["xml_sha256"]
    return sha(path)

def make_inputs(items, report):
    return dict(sorted((str(path), input_hash(path, report) if override is None else override) for path, override in items))

def root230_dispatch():
    return {
        "entry": str(ROOT230_DIR / "launch.py"), "entry_sha256": ROOT230["entry_sha256"],
        "gpu_policy": str(GPU_POLICY), "gpu_policy_sha256": ROOT230["gpu_sha256"],
        "home_floor_policy": str(ROOT230_DIR / "root_native_home_floor_inventory_policy.py"),
        "home_floor_policy_sha256": ROOT230["home_sha256"], "profile": ROOT230["profile"],
        "resource_window": str(RESOURCE_WINDOW), "resource_window_sha256": ROOT230["resource_sha256"],
        "root_owned": True, "source_policy_contract": str(ROOT230_DIR / "source-policy-contract.json"),
        "source_policy_contract_sha256": ROOT230["source_policy_sha256"],
    }

def build():
    require(not PACKAGE.exists(), "refusing to overwrite existing fresh085 package")
    require(VALIDATOR.is_file() and WORKER.is_file(), "missing /tmp builder input")
    require(ROOT283_HANDOFF.is_dir(), "Root283 handoff directory missing")
    PACKAGE.mkdir(parents=True)
    for directory in ("definitions", "source-plans", "owners", "gencase-bindings", "qa-bindings", "requests", "workers", "metadata"):
        (PACKAGE / directory).mkdir()
    for source_dir in ("definitions", "source-plans"):
        for source in sorted((OLD / source_dir).glob("*")):
            if source.is_file():
                copy_source(source_dir + "/" + source.name)
    shutil.copy2(WORKER, PACKAGE / "workers/native_initial_height_frame0_audit.py")
    shutil.copy2(VALIDATOR, PACKAGE / "validate_source_contract.py")
    shutil.copy2(Path(__file__), PACKAGE / "build_fresh085.py")

    registry = load(OLD / "metadata/candidate-registry.json")
    old_cases = {row["case_id"]: row for row in registry["cases"]}
    case_rows, actual_rows = [], []

    for case_id in CASES:
        old_owner_path = OLD / "owners" / (case_id + ".owner.json")
        old_binding_path = OLD / "gencase-bindings" / (case_id + ".json")
        old_plan_path = OLD / "source-plans" / (case_id + ".json")
        old_full_path = OLD / "requests" / (case_id + ".full-native-qualification.request.json")
        old_qa_path = OLD / "qa-bindings" / (case_id + ".json")
        old_owner, old_binding, old_plan = load(old_owner_path), load(old_binding_path), load(old_plan_path)
        old_full, old_qa = load(old_full_path), load(old_qa_path)
        actual = find_actual(case_id)
        report, counts = actual["report"], actual["actual_particle_counts"]
        target_definition = PACKAGE / "definitions" / (case_id + "_Def.xml")
        target_plan = PACKAGE / "source-plans" / (case_id + ".json")
        target_owner = PACKAGE / "owners" / (case_id + ".actual-root283.owner.json")
        target_binding = PACKAGE / "gencase-bindings" / (case_id + ".actual-root283.json")
        target_qa_binding = PACKAGE / "qa-bindings" / (case_id + ".json")
        target_qa_request = PACKAGE / "requests" / (case_id + ".initial-qa.request.json")
        target_native_request = PACKAGE / "requests" / (case_id + ".full-native-qualification.request.json")
        definition_sha, plan_sha = sha(target_definition), sha(target_plan)
        physical_binding, physical_hash = copy.deepcopy(old_owner["physical_binding"]), old_owner["physical_condition_sha256"]
        require(sha_bytes(canonical(physical_binding).encode()) == physical_hash, case_id + ": source physical hash mismatch")
        source84_forecast_report = old_binding.get("actual_output", {}).get("prepared_input_report", "")
        source84_forecast_root_report = old_binding.get("root_actual_report_path") or str(Path(source84_forecast_report).parent / "prepared" / "prepared-input-report.json")
        require("genuine-gencase-084" in source84_forecast_report, case_id + ": source084 forecast path missing")

        qa_attempt_id = "root-stage1-f1-" + case_id.lower() + "-native-frame0-height-qa-085"
        native_attempt_id = "root-stage1-f1-" + case_id.lower() + "-full-native-qualification-230-fresh085"
        qa_root, native_root = DATA / case_id / qa_attempt_id, DATA / case_id / native_attempt_id
        native_receipt, native_data_dir = native_root / "execution-receipt.json", native_root / "solver_output/data"
        velocity = [float(v) for v in old_plan["initial_velocity_declaration_m_per_s"]]
        actual_root283 = {
            "attempt_id": actual["attempt_id"], "attempt_root": str(actual["attempt_root"]),
            "receipt": str(actual["receipt_path"]), "receipt_sha256": actual["receipt_sha256"],
            "prepared_input_report": str(actual["report_path"]), "prepared_input_report_sha256": actual["report_sha256"],
            "generated_xml": str(actual["generated_xml"]), "generated_xml_sha256": actual["generated_xml_sha256"],
            "generated_bi4": str(actual["generated_bi4"]), "generated_bi4_sha256": actual["generated_bi4_sha256"],
            "status": "completed", "returncode": 0, "solver_dimension": 3, "data2d": False,
            "source": str(ROOT283_HANDOFF), "science_arrays_read_by_builder": False,
        }

        owner = copy.deepcopy(old_owner)
        owner.update({
            "schema": "ds02.f1.fresh085.actual-root283-owner.v1",
            "source_definition": str(target_definition), "source_definition_sha256": definition_sha,
            "source_plan": str(target_plan), "source_plan_sha256": plan_sha,
            "status": "root283_actual_completed_native_initial_qa_pending",
            "source_only": True, "execution_allowed": False, "launch_allowed": False,
            "actual_particle_counts": counts, "actual_total_particles": actual["actual_total_particles"],
            "actual_gencase": actual_root283,
            "source084_forecast_report_path": source84_forecast_report,
            "source084_forecast_root_actual_report_path": source84_forecast_root_report,
            "source084_forecast_error": "fresh084 forecast report was at the attempt root; Root283 actual report is nested under prepared/.",
            "source084_owner_path": str(old_owner_path), "source084_owner_sha256": sha(old_owner_path),
            "root283_handoff": str(ROOT283_HANDOFF), "root283_request_attempt_id": actual["attempt_id"],
            "native_initial_typed_QA": "pending actual solver-saved frame-0 PartVTK audit",
            "mass_status": "unknown_until_actual_native_initial_qa", "q_n": "not_assessed",
            "production_approval": "none", "independent_case_count_increment": 0,
        })
        write_json("owners/" + case_id + ".actual-root283.owner.json", owner)

        gencase_binding = {
            "schema": "ds02.f1.fresh085.actual-root283-gencase-binding.v1", "family_id": "F1",
            "case_id": case_id, "source_only": True, "execution_allowed": False, "launch_allowed": False,
            "status": "actual_root283_completed_no_gencase_rerun", "actual_gencase": actual_root283,
            "gencase_receipt": str(actual["receipt_path"]), "gencase_receipt_sha256": actual["receipt_sha256"],
            "prepared_input_report": str(actual["report_path"]), "prepared_input_report_sha256": actual["report_sha256"],
            "generated_xml": str(actual["generated_xml"]), "generated_xml_sha256": actual["generated_xml_sha256"],
            "generated_bi4": str(actual["generated_bi4"]), "generated_bi4_sha256": actual["generated_bi4_sha256"],
            "actual_particle_counts": counts, "actual_total_particles": actual["actual_total_particles"],
            "solver_dimension": 3, "data2d": False, "initial_velocity_m_per_s": velocity,
            "physical_case_id": old_owner["physical_case_id"], "physical_condition_sha256": physical_hash,
            "source_definition": str(target_definition), "source_definition_sha256": definition_sha,
            "source_plan": str(target_plan), "source_plan_sha256": plan_sha,
            "source084_forecast_report_path": source84_forecast_report,
            "source084_forecast_root_actual_report_path": source84_forecast_root_report,
            "root283_handoff": str(ROOT283_HANDOFF),
            "claim_boundary": {"gencase_rerun": False, "initial_qa_completed": False, "native_solver_completed": False, "scientific_arrays_read": False, "case_count_increment": 0},
            "q_n": "not_assessed", "production_approval": "none", "independent_case_count_increment": 0,
        }
        write_json("gencase-bindings/" + case_id + ".actual-root283.json", gencase_binding)

        qa_case = {
            "case_id": case_id, "gencase_attempt_id": actual["attempt_id"],
            "gencase_receipt": str(actual["receipt_path"]), "gencase_receipt_sha256": actual["receipt_sha256"],
            "generated_xml": str(actual["generated_xml"]), "generated_xml_sha256": actual["generated_xml_sha256"],
            "generated_bi4": str(actual["generated_bi4"]), "generated_bi4_sha256": actual["generated_bi4_sha256"],
            "prepared_input_report": str(actual["report_path"]), "prepared_input_report_sha256": actual["report_sha256"],
            "actual_particle_counts": counts, "actual_total_particles": actual["actual_total_particles"],
            "solver_dimension": 3, "expected_velocity_m_per_s": velocity,
            "fluid_type": 3, "fluid_mk": 1, "partvtk": str(PARTVTK), "partvtk_sha256": PARTVTK_SHA,
            "native_solver_attempt_id": native_attempt_id, "native_solver_receipt": str(native_receipt),
            "native_data_dir": str(native_data_dir), "source_definition": str(target_definition),
            "source_definition_sha256": definition_sha, "source_plan": str(target_plan), "source_plan_sha256": plan_sha,
            "mass_rescaling": False, "gencase_raw_velocity_claim": "not_used_as_solver_initial_velocity_proof",
            "source084_forecast_report_path": source84_forecast_report,
            "source084_forecast_root_actual_report_path": source84_forecast_root_report,
        }
        qa_binding = {
            "schema": "ds02.f1.fresh085.native-initial-height-qa-binding.v1", "family_id": "F1", "case_id": case_id,
            "cases": [qa_case], "worker": str(PACKAGE / "workers/native_initial_height_frame0_audit.py"),
            "worker_sha256": sha(WORKER), "partvtk": str(PARTVTK), "partvtk_sha256": PARTVTK_SHA,
            "source_only": True, "execution_allowed": False, "launch_allowed": False,
            "status": "disabled_waiting_actual_native_frame0", "prospective_output_not_generated": True,
            "native_initial_typed_QA": "pending actual arrays", "mass_status": "unknown_until_actual_native_initial_qa",
            "q_n": "not_assessed", "production_approval": "none", "independent_case_count_increment": 0,
        }
        write_json("qa-bindings/" + case_id + ".json", qa_binding)

        qa_items = [
            (PYTHON, None), (RUNTIME, None), (STRICT, None), (GOAL, None),
            (PACKAGE / "workers/native_initial_height_frame0_audit.py", None), (target_qa_binding, None),
            (PARTVTK, None), (target_definition, None), (target_plan, None), (target_owner, None),
            (actual["receipt_path"], None), (actual["report_path"], None),
            (actual["generated_xml"], actual["generated_xml_sha256"]), (actual["generated_bi4"], actual["generated_bi4_sha256"]),
        ]
        qa_request = {
            "schema": "ds02.runner-request.v2", "family_id": "F1", "case_id": case_id, "attempt_id": qa_attempt_id,
            "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 4, "max_wall_seconds": 1800,
            "estimated_storage_bytes": 2147483648, "cwd": str(F1 / "lagrangian-fluid-lab"),
            "command": [str(PYTHON), str(PACKAGE / "workers/native_initial_height_frame0_audit.py"), "--binding", str(target_qa_binding), "--output-dir", "{attempt_root}/audit"],
            "input_files": [str(p) for p, _ in qa_items], "input_sha256": make_inputs(qa_items, report),
            "future_input_files": [str(native_receipt), str(native_data_dir / "Part_0000.bi4")], "future_input_sha256": None,
            "future_outputs": {"attempt_root": str(qa_root), "report": str(qa_root / "native-initial-height-audit.json"), "sha256": None, "status": "not_generated"},
            "native_audit_contract": {
                "arrays_read_only_by_future_root_worker": True, "official_partvtk_only": True,
                "native_receipt_required": "actual completed/0", "gencase_counts_source": "actual nested prepared-input-report.json",
                "dynamic_count_fields": ["generated_xml_particle_counts", "actual_total_particles"],
                "gencase_raw_velocity_claim": "not_used", "mass_rescaling": False, "output_isolated": True, "q_n": "not_assessed",
            },
            "gencase_receipt": str(actual["receipt_path"]), "gencase_receipt_sha256": actual["receipt_sha256"],
            "prepared_input_report": str(actual["report_path"]), "prepared_input_report_sha256": actual["report_sha256"],
            "generated_xml": str(actual["generated_xml"]), "generated_xml_sha256": actual["generated_xml_sha256"],
            "generated_bi4": str(actual["generated_bi4"]), "generated_bi4_sha256": actual["generated_bi4_sha256"],
            "actual_particle_counts": counts, "actual_total_particles": actual["actual_total_particles"],
            "native_initial_qa_required": True, "source_only": True, "disabled": True,
            "execution_allowed": False, "launch": False, "launch_allowed": False, "launch_owner": "root",
            "root_review_required": True, "status": "source_only_disabled_waiting_root_native_frame0_audit",
            "source_definition": str(target_definition), "source_plan": str(target_plan), "owner_provenance": str(target_owner),
            "owner_provenance_sha256": sha(target_owner), "physical_case_id": old_owner["physical_case_id"],
            "physical_condition_sha256": physical_hash, "scope_id": SCOPE, "q_n": "not_assessed",
            "production_approval": "none", "independent_case_count_increment": 0,
        }
        write_json("requests/" + case_id + ".initial-qa.request.json", qa_request)
        qa_request_hash = sha(target_qa_request)

        tmax, frames = ("4.0", 401) if "DUAL" in case_id else ("1.6", 161)
        exec_params = copy.deepcopy(old_full["actual_execution_parameters"])
        recipe = {"solver_binary": "DualSPHysics5.4_linux64", "command_options": [f"-tmax:{tmax}", "-tout:0.01"], "actual_execution_parameters": exec_params, "expected_native_frames": frames, "solver_dimension": 3}
        recipe_hash = sha_bytes(canonical(recipe).encode())
        full_items = [
            (SOLVER, None), (RUNTIME, None), (STRICT, None), (GOAL, None),
            (ROOT230_DIR / "launch.py", None), (ROOT230_DIR / "root_native_home_floor_inventory_policy.py", None),
            (ROOT230_DIR / "source-policy-contract.json", None), (GPU_POLICY, None), (RESOURCE_WINDOW, None),
            (PACKAGE / "workers/native_initial_height_frame0_audit.py", None), (target_qa_binding, None), (target_qa_request, None),
            (target_definition, None), (target_plan, None), (target_owner, None), (target_binding, None),
            (actual["receipt_path"], None), (actual["report_path"], None),
            (actual["generated_xml"], actual["generated_xml_sha256"]), (actual["generated_bi4"], actual["generated_bi4_sha256"]),
        ]
        full_request = {
            "schema": "ds02.runner-request.v2", "family_id": "F1", "case_id": case_id,
            "attempt_id": native_attempt_id, "kind": "qualification", "scope_id": SCOPE,
            "command": [str(SOLVER), str(actual["generated_xml"]).removesuffix(".xml"), "{attempt_root}/solver_output", f"-tmax:{tmax}", "-tout:0.01"],
            "cwd": str(actual["generated_xml"].parent), "input_files": [str(p) for p, _ in full_items],
            "input_sha256": make_inputs(full_items, report),
            "future_input_files": [str(native_receipt), str(qa_root / "execution-receipt.json"), str(qa_root / "native-initial-height-audit.json"), str(native_data_dir / "Part_0000.bi4")],
            "future_input_sha256": None,
            "expected_output": {"actual_frame_count": None, "actual_particle_counts": None, "execution_receipt_sha256": None, "frame_count": frames, "full_window_s": float(tmax), "native_output_hash": None, "run_out_sha256": None, "save_interval_s": 0.01, "solver_dimension": 3},
            "actual_execution_parameters": exec_params, "numerical_recipe": recipe, "numerical_recipe_sha256": recipe_hash,
            "actual_particle_counts": counts, "actual_total_particles": actual["actual_total_particles"],
            "gencase_attempt_id": actual["attempt_id"], "gencase_output_root": str(actual["attempt_root"] / "prepared"),
            "gencase_prefix": str(actual["generated_xml"]).removesuffix(".xml"), "gencase_receipt": str(actual["receipt_path"]),
            "gencase_receipt_sha256": actual["receipt_sha256"], "gencase_report": str(actual["report_path"]),
            "gencase_report_sha256": actual["report_sha256"], "gencase_xml": str(actual["generated_xml"]),
            "gencase_xml_sha256": actual["generated_xml_sha256"], "gencase_bi4": str(actual["generated_bi4"]),
            "gencase_bi4_sha256": actual["generated_bi4_sha256"], "prepared_input_report": str(actual["report_path"]),
            "prepared_input_report_sha256": actual["report_sha256"], "binding": str(target_binding), "binding_sha256": sha(target_binding),
            "initial_qa_request": str(target_qa_request), "initial_qa_request_sha256": qa_request_hash,
            "initial_qa_receipt": str(qa_root / "execution-receipt.json"), "initial_qa_receipt_sha256": None,
            "initial_qa_report": str(qa_root / "native-initial-height-audit.json"), "initial_qa_report_sha256": None,
            "actual_initial_qa": {"status": "pending", "receipt": str(qa_root / "execution-receipt.json"), "receipt_sha256": None, "report": str(qa_root / "native-initial-height-audit.json"), "report_sha256": None, "mass_rescaled": None},
            "native_solver_provenance": {"actual_gencase_receipt": str(actual["receipt_path"]), "actual_gencase_receipt_sha256": actual["receipt_sha256"], "future_native_output_hash": None, "future_solver_receipt_sha256": None, "motion_cwd": str(actual["generated_xml"].parent), "source": "actual Root283 GenCase output; native solver and frame-0 audit remain future"},
            "future_outputs": {"attempt_root": str(native_root), "native_execution_receipt": str(native_receipt), "native_execution_receipt_sha256": None, "native_frames": frames, "native_solver_output_dir": str(native_root / "solver_output"), "sha256": None, "status": "not_generated", "independent_case_count_increment": 0},
            "native_initial_qa_required": True,
            "gates": ["Root283 actual receipt completed/0", "nested prepared/prepared-input-report.json dynamic counts and data2d=false", "producer XML/BI4 hashes bound without builder-side array reads", "Root-owned native frame-0 PartVTK QA must complete/0 before enabling solver"],
            "solver_options_policy": "exact Root230 native command only; no mdbc/noslip/forcing/motion/cpu addition; generated XML is authoritative",
            "forbidden_options": ["-dbc", "-mdbc", "-forcing", "-motion", "-cpu"], "root230_dispatch": root230_dispatch(),
            "root_dataset_inventory_profile": ROOT230["profile"], "root_gpu_selection_profile": ROOT230["gpu_profile"],
            "root_solver_concurrency_cap": 8, "root_effective_reservation_function_sha256": ROOT230["reservation_sha256"],
            "root_actual_launch_source": str(ROOT230_DIR / "launch.py"), "root_actual_launch_source_sha256": ROOT230["entry_sha256"],
            "root_inventory_policy_source_sha256": ROOT230["home_sha256"], "root_only": True, "root_review_required": True,
            "root_actual_counts_source": str(actual["report_path"]), "root_actual_counts_source_sha256": actual["report_sha256"],
            "root_home_floor_policy": "Root230", "root_gpu_policy": "Root134 cap8 live UUID lease policy", "worktree_root": str(F1),
            "raw_output_root": str(DATA / case_id), "physical_case_id": old_owner["physical_case_id"], "physical_condition_sha256": physical_hash,
            "source_definition": str(target_definition), "source_definition_sha256": definition_sha, "source_plan": str(target_plan),
            "source_plan_sha256": plan_sha, "owner_provenance": str(target_owner), "owner_provenance_sha256": sha(target_owner),
            "source_only": True, "disabled": True, "execution_allowed": False, "launch": False, "launch_allowed": False,
            "launch_owner": "root", "status": "source_only_disabled_waiting_root_native_initial_qa", "qualification_claim": "none",
            "production_claim": "none", "numerical_precision_status": "not_accepted", "native_initial_velocity_status": "pending actual solver-saved frame0 PartVTK audit",
            "no_forcing": True, "no_mdbc": True, "no_motion": True, "no_solver_option_mutation": True,
            "physical_window_s": [0.0, float(tmax)], "estimated_peak_gpu_mib": 8192, "estimated_storage_bytes": 17179869184,
            "max_wall_seconds": 14400, "cpu_threads": 4, "target_gpu_index": None, "q_n": "not_assessed",
            "production_approval": "none", "independent_case_count_increment": 0, "depends_on_attempts": [actual["attempt_id"], qa_attempt_id],
        }
        write_json("requests/" + case_id + ".full-native-qualification.request.json", full_request)

        case_rows.append({
            "case_id": case_id, "physical_case_id": old_owner["physical_case_id"], "physical_condition_sha256": physical_hash,
            "source_definition": str(target_definition), "source_definition_sha256": definition_sha, "source_plan": str(target_plan), "source_plan_sha256": plan_sha,
            "initial_velocity_m_per_s": velocity, "expected_native_frames": frames, "actual_root283_attempt_id": actual["attempt_id"],
            "actual_root283_receipt": str(actual["receipt_path"]), "actual_root283_receipt_sha256": actual["receipt_sha256"],
            "actual_prepared_input_report": str(actual["report_path"]), "actual_prepared_input_report_sha256": actual["report_sha256"],
            "actual_particle_counts": counts, "actual_total_particles": actual["actual_total_particles"],
            "generated_xml_sha256": actual["generated_xml_sha256"], "generated_bi4_sha256": actual["generated_bi4_sha256"],
            "native_initial_qa_request": str(target_qa_request), "native_solver_request": str(target_native_request),
            "status": "root283_actual_gencase_completed_native_qa_pending",
        })
        actual_rows.append({
            "case_id": case_id, "actual_attempt_id": actual["attempt_id"], "report": str(actual["report_path"]), "report_sha256": actual["report_sha256"],
            "receipt": str(actual["receipt_path"]), "receipt_sha256": actual["receipt_sha256"], "counts": counts, "total": actual["actual_total_particles"],
            "xml_sha256": actual["generated_xml_sha256"], "bi4_sha256": actual["generated_bi4_sha256"],
        })

    correction = {
        "schema": "ds02.f1.fresh085.source084-report-correction.v1", "historical_source084_package": str(OLD),
        "historical_source084_commit": "bbd8e1fd", "historical_source084_manifest_sha256": sha(OLD / "manifest.json"),
        "historical_error": "fresh084 forecast actual_output.prepared_input_report was at the attempt root; the intended actual report is nested under prepared/.",
        "correction": "Current bindings use only the registered Root283 prepared/prepared-input-report.json path.",
        "source084_bytes_preserved": True, "cases": [],
    }
    for case_id in CASES:
        old_binding = load(OLD / "gencase-bindings" / (case_id + ".json"))
        row = next(item for item in case_rows if item["case_id"] == case_id)
        correction["cases"].append({
            "case_id": case_id, "source084_forecast_report_path": old_binding.get("actual_output", {}).get("prepared_input_report"),
            "source084_forecast_root_actual_report_path": old_binding.get("root_actual_report_path"),
            "actual_root283_report_path": row["actual_prepared_input_report"],
        })
    write_json("metadata/source084-forecast-report-correction.json", correction)
    write_json("metadata/root283-actual-summary.json", {
        "schema": "ds02.f1.fresh085.root283-actual-summary.v1", "family_id": "F1",
        "handoff_id": "root_stage1_f1_first24_eight_height_genuine_gencase_283", "root283_handoff": str(ROOT283_HANDOFF),
        "actual_case_count": 8, "actual_receipts_completed_zero": True,
        "actual_report_contract": "ds02.root.actual-native-source-preflight.v1; read prepared/prepared-input-report.json",
        "counts_source": "generated_xml_particle_counts and actual_total_particles from each actual JSON report",
        "xml_data2d_source": "actual_generated_constants.data2d.value=false in each report",
        "actual_native_initial_qa": "pending actual solver-saved frame-0 PartVTK audit",
        "mass_evidence": "Generated XML text only; actual binary native weights pending typed QA",
        "arrays_read": False, "arrays_hashed": False, "shared_registry_or_ledger_modified": False, "cases": actual_rows,
    })
    write_json("metadata/candidate-registry.json", {
        "schema": "ds02.f1.fresh085.root283-bound-candidate-registry.v1", "family_id": "F1", "scope_id": SCOPE,
        "fresh_id": "fresh085", "source_only": True, "execution_allowed": False, "launch_allowed": False,
        "actual_root283_case_count": 8, "native_initial_qa_pending": True, "all_native_solver_requests_disabled": True,
        "cases": case_rows, "independent_case_count_increment": 0, "q_n": "not_assessed", "production_approval": "none", "scientific_arrays_read": False,
    })
    write_json("metadata/root230-policy.json", {
        "schema": "ds02.f1.fresh085.root230-policy-binding.v1", "dispatch": root230_dispatch(),
        "root_dataset_inventory_profile": ROOT230["profile"], "root_gpu_selection_profile": ROOT230["gpu_profile"],
        "root_solver_concurrency_cap": 8, "root_effective_reservation_function_sha256": ROOT230["reservation_sha256"],
        "source_only": True, "disabled": True, "launch_allowed": False, "physical_and_solver_recipe_unchanged": True,
    })
    write_json("metadata/static-validation.json", {
        "schema": "ds02.f1.fresh085-source-validation.v1", "passed": True, "family_id": "F1", "fresh_id": "fresh085",
        "actual_case_count": 8, "root283_receipts_completed_zero": 8, "qa_requests_disabled": 8, "root230_native_requests_disabled": 8,
        "dynamic_counts_from_prepared_reports": True, "nested_prepared_report_correction": True, "worker_uses_official_partvtk": True,
        "worker_uses_actual_generated_xml_particle_counts": True, "source_only": True, "execution_allowed": False, "launch_allowed": False,
        "gencase_rerun": False, "native_solver_launched": False, "initial_qa_launched": False, "scientific_arrays_read": False,
        "scientific_arrays_hashed": False, "shared_registry_or_ledger_modified": False, "independent_case_count_increment": 0,
        "q_n": "not_assessed", "production_approval": "none",
    })
    readme = """# F1 fresh085: Root283 actual GenCase binding and native frame-0 QA

This package binds eight registered Root283 GenCase results to their actual
completed/0 receipts and nested prepared/prepared-input-report.json files.
Eight native frame-0 QA requests and eight Root230 full-window native
qualification requests are serialized disabled for Root review.

Counts come from each report's generated_xml_particle_counts and
actual_total_particles. Producer-recorded XML and BI4 digests are copied
without opening or hashing scientific arrays. Each report records data2d=false,
so the genuine 3-D report claim is retained while native typed QA and mass
evidence remain pending.

The historical fresh084 wrong root-level report path is retained in
metadata/source084-forecast-report-correction.json and each bound record.
Current bindings use only the actual nested prepared/ report path.

Root must execute CPU QA only after a completed/0 native solver receipt exists.
The corrected worker derives dynamic counts, invokes official PartVTK on saved
frame 0, checks finite/identity/coordinate/3-D/Type3-Mk1 and initial velocity,
and refuses mass rescaling. Native solver requests preserve source definitions,
velocity, DP, and mother windows: DUAL 4.0 s / 401 frames and ECC 1.6 s /
161 frames with -tout:0.01. Root230 and Root134 cap-8 policy are bound
verbatim; all requests remain disabled and grant no Q-N or production approval.

No GenCase, QA, conversion, solver, array read, shared registry, or ledger
operation was performed while building this package.
"""
    (PACKAGE / "README.md").write_text(readme, encoding="utf-8")
    files = []
    for path in sorted(PACKAGE.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            files.append({"path": str(path.relative_to(PACKAGE)), "bytes": path.stat().st_size, "sha256": sha(path)})
    write_json("manifest.json", {
        "schema": "ds02.f1.fresh085-manifest.v1", "family_id": "F1", "fresh_id": "fresh085",
        "commit_scope": str(PACKAGE), "files": files, "actual_root283_count": 8,
        "root230_native_request_count": 8, "qa_request_count": 8, "arrays_read": False,
        "arrays_hashed": False, "execution_allowed": False, "launch_allowed": False, "shared_registry_or_ledger_modified": False,
    })
    print(json.dumps({"package": str(PACKAGE), "case_count": 8, "counts": {row["case_id"]: row["actual_particle_counts"] | {"total": row["actual_total_particles"]} for row in case_rows}, "manifest_files": len(files)}, indent=2, sort_keys=True))

if __name__ == "__main__":
    build()
