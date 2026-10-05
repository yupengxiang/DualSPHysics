#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

F1 = Path("/home/jade/.codex/worktrees/ds-data-02-f1/DualSPHysics")
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1")
OLD = F1 / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F1/handoff_20261003/root_followup_085_f1_root283_actual_gencase_native_qa_v1"
PACKAGE = F1 / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F1/handoff_20261003/root_followup_086_f1_root283_gencase_initial_qa_acyclic_v1"
ROOT283_HANDOFF = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f1_first24_eight_height_genuine_gencase_283"
ROOT230_DIR = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_native_home_floor_eight_solver_dispatch_230"
GPU_POLICY = INTEGRATION / "lagrangian-fluid-lab/handoff_20261003/root_stage1_f3_first24_eight_solver_resource_policy_134/ds02_root_all_idle_gpu_policy_v2.py"
# The resource handoff is under campaigns/ds-data-02 in this checkout.
GPU_POLICY = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f3_first24_eight_solver_resource_policy_134/ds02_root_all_idle_gpu_policy_v2.py"
RESOURCE_WINDOW = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json"
RUNTIME = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
STRICT = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py"
GOAL = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/GOAL_STAGE1_VISUAL_GPT56LUNA_20261004_ZH.md"
PYTHON = F1 / "lagrangian-fluid-lab/.venv/bin/python"
PARTVTK = F1 / "lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64"
SOLVER = F1 / "lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64"
GENQA_SOURCE = Path("/tmp/f1_gencase_initial_qa_fresh086.py")
VALIDATOR_SOURCE = Path("/tmp/validate_f1_fresh086.py")
NATIVE_WORKER_SOURCE = OLD / "workers/native_initial_height_frame0_audit.py"
SCOPE = "F1_STAGE1_FIRST24_HEIGHT_EXTENSION_V1"
CASES = [
    "F1_STAGE1_DUAL_H240_DP020", "F1_STAGE1_DUAL_H240_DP020_VX010",
    "F1_STAGE1_DUAL_H280_DP020", "F1_STAGE1_DUAL_H320_DP020",
    "F1_STAGE1_ECC_H120_DP010", "F1_STAGE1_ECC_H140_DP010",
    "F1_STAGE1_ECC_H160_DP010", "F1_STAGE1_ECC_H180_DP010",
]
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
PARTVTK_SHA = "62630430902484f4aede017108313673fe6414f40fb59b6ae7f14ac23219db00"


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha(path: Path) -> str:
    if path.suffix.lower() in {".bi4", ".h5", ".hdf5", ".csv", ".npy", ".npz", ".vtk"}:
        raise RuntimeError("builder attempted to read scientific array: " + str(path))
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("expected JSON object: " + str(path))
    return value


def require(value: object, message: str) -> None:
    if not value:
        raise RuntimeError(message)


def write_json(rel: str, value: object) -> Path:
    path = PACKAGE / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def find_actual(case_id: str) -> dict:
    reports = sorted(DATA.glob(case_id + "/root-stage1-f1-*-genuine-gencase-283/prepared/prepared-input-report.json"))
    require(len(reports) == 1, f"{case_id}: expected one nested Root283 report, got {len(reports)}")
    report_path = reports[0]
    receipt_path = report_path.parents[1] / "execution-receipt.json"
    require(receipt_path.is_file(), f"{case_id}: Root283 receipt missing")
    report, receipt = load(report_path), load(receipt_path)
    require(report.get("case_id") == case_id, f"{case_id}: report case mismatch")
    require(receipt.get("status") == "completed" and receipt.get("returncode") == 0, f"{case_id}: Root283 not completed/0")
    counts = report.get("generated_xml_particle_counts")
    require(isinstance(counts, dict), f"{case_id}: generated_xml_particle_counts missing")
    actual_counts = {
        "fixed": int(counts["fixed"]), "moving": int(counts.get("moving", 0)),
        "floating": int(counts.get("floating", 0)), "fluid": int(counts["fluid"]),
    }
    total = int(report["actual_total_particles"])
    require(total == sum(actual_counts.values()), f"{case_id}: dynamic count sum mismatch")
    data2d = str(report.get("actual_generated_constants", {}).get("data2d", {}).get("value", "")).lower()
    require(data2d == "false", f"{case_id}: actual XML data2d is not false")
    require(report.get("xml_sha256") and report.get("bi4_sha256"), f"{case_id}: producer artifact digests missing")
    prefix = Path(report["prefix"])
    return {
        "report_path": report_path,
        "receipt_path": receipt_path,
        "report": report,
        "receipt": receipt,
        "attempt_root": report_path.parents[1],
        "attempt_id": receipt.get("request", {}).get("attempt_id", report_path.parents[1].name),
        "generated_xml": Path(str(prefix) + ".xml"),
        "generated_bi4": Path(str(prefix) + ".bi4"),
        "report_sha256": sha(report_path),
        "receipt_sha256": sha(receipt_path),
        "generated_xml_sha256": report["xml_sha256"],
        "generated_bi4_sha256": report["bi4_sha256"],
        "actual_particle_counts": actual_counts,
        "actual_total_particles": total,
    }


def input_hash(path: Path, override: str | None = None) -> str:
    return override if override is not None else sha(path)


def make_inputs(items: list[tuple[Path, str | None]]) -> dict[str, str]:
    return dict(sorted((str(path), input_hash(path, override)) for path, override in items))


def root230_dispatch() -> dict:
    return {
        "entry": str(ROOT230_DIR / "launch.py"), "entry_sha256": ROOT230["entry_sha256"],
        "gpu_policy": str(GPU_POLICY), "gpu_policy_sha256": ROOT230["gpu_sha256"],
        "home_floor_policy": str(ROOT230_DIR / "root_native_home_floor_inventory_policy.py"),
        "home_floor_policy_sha256": ROOT230["home_sha256"], "profile": ROOT230["profile"],
        "resource_window": str(RESOURCE_WINDOW), "resource_window_sha256": ROOT230["resource_sha256"],
        "root_owned": True, "source_policy_contract": str(ROOT230_DIR / "source-policy-contract.json"),
        "source_policy_contract_sha256": ROOT230["source_policy_sha256"],
    }


def copy_file(source: Path, rel: str) -> Path:
    target = PACKAGE / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target


def build() -> None:
    require(not PACKAGE.exists(), "refusing to overwrite existing fresh086 package")
    for required in [OLD, ROOT283_HANDOFF, ROOT230_DIR, GPU_POLICY, RESOURCE_WINDOW, RUNTIME, STRICT, GOAL, PYTHON, PARTVTK, SOLVER, GENQA_SOURCE, VALIDATOR_SOURCE, NATIVE_WORKER_SOURCE]:
        require(required.exists(), "missing required source: " + str(required))
    PACKAGE.mkdir(parents=True)
    for directory in ("definitions", "source-plans", "owners", "gencase-bindings", "gencase-initial-qa-bindings", "native-frame0-qa-bindings", "requests", "workers", "metadata"):
        (PACKAGE / directory).mkdir()
    for source in sorted((OLD / "definitions").glob("*.xml")):
        copy_file(source, "definitions/" + source.name)
    copy_file(GENQA_SOURCE, "workers/gencase_initial_qa.py")
    copy_file(NATIVE_WORKER_SOURCE, "workers/native_initial_height_frame0_audit.py")
    copy_file(VALIDATOR_SOURCE, "validate_source_contract.py")
    copy_file(Path(__file__), "build_fresh086.py")

    # Copy source plans while rebinding only their materialized definition path.
    for source in sorted((OLD / "source-plans").glob("*.json")):
        plan = load(source)
        plan["materialized_definition"] = str(PACKAGE / "definitions" / (source.stem + "_Def.xml"))
        plan["schema"] = "ds02.f1.fresh086.height-source-plan.v1"
        write_json("source-plans/" + source.name, plan)

    old_registry = load(OLD / "metadata/candidate-registry.json")
    old_registry_rows = {row["case_id"]: row for row in old_registry["cases"]}
    case_rows: list[dict] = []
    actual_rows: list[dict] = []
    for case_id in CASES:
        old_owner_path = OLD / "owners" / f"{case_id}.actual-root283.owner.json"
        old_binding_path = OLD / "gencase-bindings" / f"{case_id}.actual-root283.json"
        old_full_path = OLD / "requests" / f"{case_id}.full-native-qualification.request.json"
        old_owner, old_binding, old_full = load(old_owner_path), load(old_binding_path), load(old_full_path)
        actual = find_actual(case_id)
        counts = actual["actual_particle_counts"]
        source_definition = PACKAGE / "definitions" / f"{case_id}_Def.xml"
        source_plan = PACKAGE / "source-plans" / f"{case_id}.json"
        owner_path = PACKAGE / "owners" / f"{case_id}.actual-root283.owner.json"
        binding_path = PACKAGE / "gencase-bindings" / f"{case_id}.actual-root283.json"
        genqa_binding_path = PACKAGE / "gencase-initial-qa-bindings" / f"{case_id}.json"
        frame_binding_path = PACKAGE / "native-frame0-qa-bindings" / f"{case_id}.json"
        genqa_request_path = PACKAGE / "requests" / f"{case_id}.initial-qa.request.json"
        native_request_path = PACKAGE / "requests" / f"{case_id}.full-native-qualification.request.json"
        frame_request_path = PACKAGE / "requests" / f"{case_id}.native-frame0-qa.request.json"
        definition_sha, plan_sha = sha(source_definition), sha(source_plan)
        physical_binding = copy.deepcopy(old_owner["physical_binding"])
        physical_hash = old_owner["physical_condition_sha256"]
        require(sha_bytes(canonical(physical_binding).encode()) == physical_hash, f"{case_id}: physical binding hash mismatch")
        velocity = [float(v) for v in load(OLD / "source-plans" / f"{case_id}.json")["initial_velocity_declaration_m_per_s"]]
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
            "schema": "ds02.f1.fresh086.actual-root283-owner.v1",
            "source_definition": str(source_definition), "source_definition_sha256": definition_sha,
            "source_plan": str(source_plan), "source_plan_sha256": plan_sha,
            "status": "root283_actual_completed_gencase_initial_qa_pending",
            "source_only": True, "execution_allowed": False, "launch_allowed": False,
            "actual_particle_counts": counts, "actual_total_particles": actual["actual_total_particles"],
            "actual_gencase": actual_root283, "root283_handoff": str(ROOT283_HANDOFF),
            "root283_request_attempt_id": actual["attempt_id"],
            "gencase_initial_qa": "pending pre-native official PartVTK audit",
            "native_initial_typed_QA": "pending actual solver-saved frame-0 PartVTK audit",
            "mass_status": "unknown_until_gencase_initial_qa_and_native_initial_qa",
            "q_n": "not_assessed", "production_approval": "none", "independent_case_count_increment": 0,
            "fresh085_circular_evidence": {
                "package": str(OLD), "commit": "65220599bded147d4c0b3e32d119509b7faa76ae",
                "preserved_unchanged": True, "relationship": "historical circular native/frame0 source; replaced by fresh086 DAG",
            },
        })
        write_json(f"owners/{case_id}.actual-root283.owner.json", owner)
        gencase_binding = {
            "schema": "ds02.f1.fresh086.actual-root283-gencase-binding.v1", "family_id": "F1",
            "case_id": case_id, "source_only": True, "execution_allowed": False, "launch_allowed": False,
            "status": "actual_root283_completed_no_gencase_rerun", "actual_gencase": actual_root283,
            "gencase_receipt": str(actual["receipt_path"]), "gencase_receipt_sha256": actual["receipt_sha256"],
            "prepared_input_report": str(actual["report_path"]), "prepared_input_report_sha256": actual["report_sha256"],
            "generated_xml": str(actual["generated_xml"]), "generated_xml_sha256": actual["generated_xml_sha256"],
            "generated_bi4": str(actual["generated_bi4"]), "generated_bi4_sha256": actual["generated_bi4_sha256"],
            "actual_particle_counts": counts, "actual_total_particles": actual["actual_total_particles"],
            "solver_dimension": 3, "data2d": False, "initial_velocity_m_per_s": velocity,
            "physical_case_id": old_owner["physical_case_id"], "physical_condition_sha256": physical_hash,
            "source_definition": str(source_definition), "source_definition_sha256": definition_sha,
            "source_plan": str(source_plan), "source_plan_sha256": plan_sha,
            "source084_forecast_report_path": old_binding.get("source084_forecast_report_path", ""),
            "source084_forecast_root_actual_report_path": old_binding.get("source084_forecast_root_actual_report_path", ""),
            "root283_handoff": str(ROOT283_HANDOFF),
            "claim_boundary": {"gencase_rerun": False, "gencase_initial_qa_completed": False, "native_solver_completed": False, "native_frame0_qa_completed": False, "scientific_arrays_read": False, "case_count_increment": 0},
            "gencase_raw_velocity_claim": "not_used_as_solver_initial_velocity_proof",
            "q_n": "not_assessed", "production_approval": "none", "independent_case_count_increment": 0,
        }
        write_json(f"gencase-bindings/{case_id}.actual-root283.json", gencase_binding)
        genqa_attempt_id = "root-stage1-f1-" + case_id.lower() + "-gencase-initial-qa-086"
        native_attempt_id = "root-stage1-f1-" + case_id.lower() + "-full-native-qualification-230-fresh086"
        frame_attempt_id = "root-stage1-f1-" + case_id.lower() + "-native-frame0-height-qa-086"
        genqa_root = DATA / case_id / genqa_attempt_id
        native_root = DATA / case_id / native_attempt_id
        frame_root = DATA / case_id / frame_attempt_id
        genqa_receipt = genqa_root / "execution-receipt.json"
        genqa_report = genqa_root / "audit/gencase-initial-qa.json"
        native_receipt = native_root / "execution-receipt.json"
        native_data_dir = native_root / "solver_output/data"
        frame_report = frame_root / "audit/native-initial-height-audit.json"
        genqa_case = {
            "case_id": case_id, "parent_case_id": old_owner.get("parent_case_id"),
            "prefix": str(actual["generated_xml"]).removesuffix(".xml"),
            "gencase_receipt": str(actual["receipt_path"]), "gencase_receipt_sha256": actual["receipt_sha256"],
            "generated_xml": str(actual["generated_xml"]), "generated_xml_sha256": actual["generated_xml_sha256"],
            "generated_bi4": str(actual["generated_bi4"]), "generated_bi4_sha256": actual["generated_bi4_sha256"],
            "prepared_input_report": str(actual["report_path"]), "prepared_input_report_sha256": actual["report_sha256"],
            "actual_particle_counts": counts, "actual_total_particles": actual["actual_total_particles"],
            "expected_types": [0, 3], "fluid_type": 3, "fluid_mk": 1, "solver_dimension": 3,
            "source_initial_velocity_declaration_m_per_s": velocity,
            "gencase_raw_velocity_claim": "not_used_as_solver_initial_velocity_proof",
            "prospective_output_not_generated": True,
        }
        genqa_binding = {
            "schema": "ds02.f1.fresh086.gencase-initial-qa-binding.v1", "family_id": "F1", "case_id": case_id,
            "stage": "pre_native_gencase_initial", "cases": [genqa_case], "partvtk": str(PARTVTK), "partvtk_sha256": PARTVTK_SHA,
            "worker": str(PACKAGE / "workers/gencase_initial_qa.py"),
            "worker_sha256": sha(PACKAGE / "workers/gencase_initial_qa.py"),
            "native_solver_receipt_required": False, "native_solver_output_required": False,
            "arrays_read_only_by_future_root_worker": True, "source_only": True, "execution_allowed": False, "launch_allowed": False,
            "status": "disabled_waiting_actual_gencase_initial_qa", "prospective_output_not_generated": True,
            "gencase_raw_velocity_claim": "not_used_as_solver_initial_velocity_proof",
            "q_n": "not_assessed", "production_approval": "none", "independent_case_count_increment": 0,
        }
        write_json(f"gencase-initial-qa-bindings/{case_id}.json", genqa_binding)
        genqa_items = [
            (PYTHON, None), (RUNTIME, None), (STRICT, None), (GOAL, None),
            (PACKAGE / "workers/gencase_initial_qa.py", None), (genqa_binding_path, None), (PARTVTK, None),
            (source_definition, None), (source_plan, None), (owner_path, None), (binding_path, None),
            (actual["receipt_path"], None), (actual["report_path"], None),
            (actual["generated_xml"], actual["generated_xml_sha256"]), (actual["generated_bi4"], actual["generated_bi4_sha256"]),
        ]
        genqa_request = {
            "schema": "ds02.runner-request.v2", "family_id": "F1", "case_id": case_id, "attempt_id": genqa_attempt_id,
            "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 4, "max_wall_seconds": 1800,
            "estimated_storage_bytes": 2147483648, "cwd": str(F1 / "lagrangian-fluid-lab"), "worktree_root": str(F1),
            "command": [str(PYTHON), str(PACKAGE / "workers/gencase_initial_qa.py"), "--binding", str(genqa_binding_path), "--output-dir", "{attempt_root}/audit"],
            "input_files": [str(path) for path, _ in genqa_items], "input_sha256": make_inputs(genqa_items),
            "future_input_files": [], "future_input_sha256": None,
            "future_outputs": {"attempt_root": str(genqa_root), "report": str(genqa_report), "sha256": None, "status": "not_generated"},
            "depends_on_attempts": [actual["attempt_id"]],
            "actual_gencase_attempt_id": actual["attempt_id"], "gencase_receipt": str(actual["receipt_path"]), "gencase_receipt_sha256": actual["receipt_sha256"],
            "prepared_input_report": str(actual["report_path"]), "prepared_input_report_sha256": actual["report_sha256"],
            "generated_xml": str(actual["generated_xml"]), "generated_xml_sha256": actual["generated_xml_sha256"],
            "generated_bi4": str(actual["generated_bi4"]), "generated_bi4_sha256": actual["generated_bi4_sha256"],
            "actual_particle_counts": counts, "actual_total_particles": actual["actual_total_particles"],
            "cpu_audit_contract": {
                "stage": "pre_native_gencase_initial", "official_partvtk_only": True, "arrays_are_read_only": True,
                "checks": ["receipt completed/0", "dynamic counts", "Idp/Zone identity", "Type/Mk partition", "finite coordinates", "positive mass and density", "genuine 3-D extent", "source XML data2d=false"],
                "native_solver_receipt_required": False, "native_solver_output_required": False,
                "gencase_raw_velocity_claim": "not_used_as_solver_initial_velocity_proof", "mass_rescaling": False,
            },
            "source_definition": str(source_definition), "source_definition_sha256": definition_sha,
            "source_plan": str(source_plan), "source_plan_sha256": plan_sha,
            "owner_provenance": str(owner_path), "owner_provenance_sha256": sha(owner_path),
            "binding": str(genqa_binding_path), "binding_sha256": sha(genqa_binding_path),
            "physical_case_id": old_owner["physical_case_id"], "physical_condition_sha256": physical_hash, "scope_id": SCOPE,
            "source_only": True, "disabled": True, "execution_allowed": False, "launch": False, "launch_allowed": False,
            "launch_owner": "root", "root_review_required": True, "status": "source_only_disabled_waiting_root_gencase_initial_qa",
            "production_approval": "none", "q_n": "not_assessed", "independent_case_count_increment": 0,
        }
        write_json(f"requests/{case_id}.initial-qa.request.json", genqa_request)

        # Downstream native frame-0 binding and request are deliberately separate.
        frame_case = copy.deepcopy(genqa_case)
        frame_case.update({
            "native_solver_attempt_id": native_attempt_id, "native_solver_receipt": str(native_receipt),
            "native_data_dir": str(native_data_dir), "partvtk": str(PARTVTK), "partvtk_sha256": PARTVTK_SHA,
            "expected_velocity_m_per_s": velocity, "mass_rescaling": False,
        })
        frame_binding = {
            "schema": "ds02.f1.fresh086.native-frame0-qa-binding.v1", "family_id": "F1", "case_id": case_id,
            "stage": "downstream_native_frame0", "native_solver_attempt_id": native_attempt_id, "native_solver_receipt": str(native_receipt),
            "cases": [frame_case], "worker": str(PACKAGE / "workers/native_initial_height_frame0_audit.py"),
            "worker_sha256": sha(PACKAGE / "workers/native_initial_height_frame0_audit.py"), "partvtk": str(PARTVTK), "partvtk_sha256": PARTVTK_SHA,
            "source_only": True, "execution_allowed": False, "launch_allowed": False,
            "status": "disabled_waiting_actual_native_frame0_qa", "prospective_output_not_generated": True,
            "native_solver_receipt_required": True, "native_initial_qa": "downstream after native completion",
            "gencase_raw_velocity_claim": "not_used_as_solver_initial_velocity_proof",
            "q_n": "not_assessed", "production_approval": "none", "independent_case_count_increment": 0,
        }
        write_json(f"native-frame0-qa-bindings/{case_id}.json", frame_binding)
        frame_items = [
            (PYTHON, None), (RUNTIME, None), (STRICT, None), (GOAL, None),
            (PACKAGE / "workers/native_initial_height_frame0_audit.py", None), (frame_binding_path, None), (PARTVTK, None),
            (source_definition, None), (source_plan, None), (owner_path, None), (binding_path, None),
            (actual["receipt_path"], None), (actual["report_path"], None),
            (actual["generated_xml"], actual["generated_xml_sha256"]), (actual["generated_bi4"], actual["generated_bi4_sha256"]),
        ]
        frame_request = {
            "schema": "ds02.runner-request.v2", "family_id": "F1", "case_id": case_id, "attempt_id": frame_attempt_id,
            "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 4, "max_wall_seconds": 1800,
            "estimated_storage_bytes": 2147483648, "cwd": str(F1 / "lagrangian-fluid-lab"), "worktree_root": str(F1),
            "command": [str(PYTHON), str(PACKAGE / "workers/native_initial_height_frame0_audit.py"), "--binding", str(frame_binding_path), "--output-dir", "{attempt_root}/audit"],
            "input_files": [str(path) for path, _ in frame_items], "input_sha256": make_inputs(frame_items),
            "future_input_files": [str(native_receipt), str(native_data_dir / "Part_0000.bi4")], "future_input_sha256": None,
            "future_outputs": {"attempt_root": str(frame_root), "report": str(frame_report), "sha256": None, "status": "not_generated"},
            "depends_on_attempts": [native_attempt_id], "native_solver_attempt_id": native_attempt_id,
            "native_solver_receipt": str(native_receipt), "native_solver_receipt_sha256": None,
            "gencase_receipt": str(actual["receipt_path"]), "gencase_receipt_sha256": actual["receipt_sha256"],
            "generated_xml": str(actual["generated_xml"]), "generated_xml_sha256": actual["generated_xml_sha256"],
            "generated_bi4": str(actual["generated_bi4"]), "generated_bi4_sha256": actual["generated_bi4_sha256"],
            "prepared_input_report": str(actual["report_path"]), "prepared_input_report_sha256": actual["report_sha256"],
            "actual_particle_counts": counts, "actual_total_particles": actual["actual_total_particles"],
            "native_audit_contract": {"stage": "downstream_native_frame0", "native_receipt_required": "actual completed/0", "official_partvtk_only": True, "arrays_are_read_only": True, "gencase_raw_velocity_claim": "not_used", "mass_rescaling": False},
            "source_definition": str(source_definition), "source_definition_sha256": definition_sha,
            "source_plan": str(source_plan), "source_plan_sha256": plan_sha, "owner_provenance": str(owner_path), "owner_provenance_sha256": sha(owner_path),
            "binding": str(frame_binding_path), "binding_sha256": sha(frame_binding_path),
            "physical_case_id": old_owner["physical_case_id"], "physical_condition_sha256": physical_hash, "scope_id": SCOPE,
            "source_only": True, "disabled": True, "execution_allowed": False, "launch": False, "launch_allowed": False,
            "launch_owner": "root", "root_review_required": True, "status": "source_only_disabled_waiting_root_native_frame0_qa",
            "production_approval": "none", "q_n": "not_assessed", "independent_case_count_increment": 0,
        }
        write_json(f"requests/{case_id}.native-frame0-qa.request.json", frame_request)

        tmax = "4.0" if "DUAL" in case_id else "1.6"
        frames = 401 if "DUAL" in case_id else 161
        exec_params = copy.deepcopy(old_full["actual_execution_parameters"])
        require(str(exec_params["TimeMax"]) == tmax, f"{case_id}: old Root230 TimeMax changed")
        require(str(exec_params["TimeOut"]) == "0.01", f"{case_id}: old Root230 TimeOut changed")
        recipe = {"solver_binary": "DualSPHysics5.4_linux64", "command_options": [f"-tmax:{tmax}", "-tout:0.01"], "actual_execution_parameters": exec_params, "expected_native_frames": frames, "solver_dimension": 3}
        recipe_hash = sha_bytes(canonical(recipe).encode())
        native_items = [
            (SOLVER, None), (RUNTIME, None), (STRICT, None), (GOAL, None),
            (ROOT230_DIR / "launch.py", None), (ROOT230_DIR / "root_native_home_floor_inventory_policy.py", None),
            (ROOT230_DIR / "source-policy-contract.json", None), (GPU_POLICY, None), (RESOURCE_WINDOW, None),
            (source_definition, None), (source_plan, None), (owner_path, None), (binding_path, None),
            (genqa_binding_path, None), (genqa_request_path, None),
            (actual["receipt_path"], None), (actual["report_path"], None),
            (actual["generated_xml"], actual["generated_xml_sha256"]), (actual["generated_bi4"], actual["generated_bi4_sha256"]),
        ]
        native_request = {
            "schema": "ds02.runner-request.v2", "family_id": "F1", "case_id": case_id,
            "attempt_id": native_attempt_id, "kind": "qualification", "scope_id": SCOPE,
            "command": [str(SOLVER), str(actual["generated_xml"]).removesuffix(".xml"), "{attempt_root}/solver_output", f"-tmax:{tmax}", "-tout:0.01"],
            "cwd": str(actual["generated_xml"].parent), "input_files": [str(path) for path, _ in native_items], "input_sha256": make_inputs(native_items),
            "future_input_files": [str(genqa_receipt), str(genqa_report), str(native_receipt), str(native_data_dir / "Part_0000.bi4")], "future_input_sha256": None,
            "depends_on_attempts": [actual["attempt_id"], genqa_attempt_id],
            "expected_output": {"actual_frame_count": None, "actual_particle_counts": None, "execution_receipt_sha256": None, "frame_count": frames, "full_window_s": float(tmax), "native_output_hash": None, "run_out_sha256": None, "save_interval_s": 0.01, "solver_dimension": 3},
            "actual_execution_parameters": exec_params, "numerical_recipe": recipe, "numerical_recipe_sha256": recipe_hash,
            "actual_particle_counts": counts, "actual_total_particles": actual["actual_total_particles"],
            "gencase_attempt_id": actual["attempt_id"], "gencase_output_root": str(actual["attempt_root"] / "prepared"),
            "gencase_prefix": str(actual["generated_xml"]).removesuffix(".xml"), "gencase_receipt": str(actual["receipt_path"]), "gencase_receipt_sha256": actual["receipt_sha256"],
            "gencase_report": str(actual["report_path"]), "gencase_report_sha256": actual["report_sha256"], "gencase_xml": str(actual["generated_xml"]), "gencase_xml_sha256": actual["generated_xml_sha256"],
            "gencase_bi4": str(actual["generated_bi4"]), "gencase_bi4_sha256": actual["generated_bi4_sha256"], "prepared_input_report": str(actual["report_path"]), "prepared_input_report_sha256": actual["report_sha256"],
            "binding": str(binding_path), "binding_sha256": sha(binding_path),
            "initial_qa_request": str(genqa_request_path), "initial_qa_request_sha256": sha(genqa_request_path),
            "initial_qa_receipt": str(genqa_receipt), "initial_qa_receipt_sha256": None, "initial_qa_report": str(genqa_report), "initial_qa_report_sha256": None,
            "gencase_initial_qa_request": str(genqa_request_path), "gencase_initial_qa_request_sha256": sha(genqa_request_path),
            "gencase_initial_qa_receipt": str(genqa_receipt), "gencase_initial_qa_receipt_sha256": None, "gencase_initial_qa_report": str(genqa_report), "gencase_initial_qa_report_sha256": None,
            "native_frame0_qa_request": str(frame_request_path), "native_frame0_qa_request_sha256": sha(frame_request_path),
            "native_frame0_qa_receipt": str(frame_root / "execution-receipt.json"), "native_frame0_qa_receipt_sha256": None,
            "native_frame0_qa_report": str(frame_report), "native_frame0_qa_report_sha256": None,
            "actual_initial_qa": {"stage": "gencase_initial_pre_native", "status": "pending", "receipt": str(genqa_receipt), "receipt_sha256": None, "report": str(genqa_report), "report_sha256": None, "mass_rescaled": False},
            "native_solver_provenance": {"actual_gencase_receipt": str(actual["receipt_path"]), "actual_gencase_receipt_sha256": actual["receipt_sha256"], "future_native_output_hash": None, "future_solver_receipt_sha256": None, "motion_cwd": str(actual["generated_xml"].parent), "source": "actual Root283 GenCase output; GenCase QA gates native, native frame-0 QA is downstream"},
            "future_outputs": {"attempt_root": str(native_root), "native_execution_receipt": str(native_receipt), "native_execution_receipt_sha256": None, "native_frames": frames, "native_solver_output_dir": str(native_root / "solver_output"), "sha256": None, "status": "not_generated", "independent_case_count_increment": 0},
            "gencase_initial_qa_required": True, "native_initial_qa_required": True, "native_frame0_qa_downstream_only": True,
            "gates": ["Root283 actual receipt completed/0", "nested prepared/prepared-input-report.json dynamic counts and data2d=false", "producer XML/BI4 hashes bound without builder-side array reads", "GenCase initial QA completed/0 from official PartVTK before enabling native solver", "native frame-0 PartVTK QA is downstream after native completion and cannot gate this solver request"],
            "solver_options_policy": "exact Root230 native command only; no mdbc/noslip/forcing/motion/cpu addition; generated XML is authoritative",
            "forbidden_options": ["-dbc", "-mdbc", "-forcing", "-motion", "-cpu"], "root230_dispatch": root230_dispatch(),
            "root_dataset_inventory_profile": ROOT230["profile"], "root_gpu_selection_profile": ROOT230["gpu_profile"], "root_solver_concurrency_cap": 8, "root_effective_reservation_function_sha256": ROOT230["reservation_sha256"],
            "root_actual_launch_source": str(ROOT230_DIR / "launch.py"), "root_actual_launch_source_sha256": ROOT230["entry_sha256"], "root_inventory_policy_source_sha256": ROOT230["home_sha256"], "root_only": True, "root_review_required": True,
            "root_actual_counts_source": str(actual["report_path"]), "root_actual_counts_source_sha256": actual["report_sha256"], "root_home_floor_policy": "Root230", "root_gpu_policy": "Root134 cap8 live UUID lease policy", "worktree_root": str(F1),
            "raw_output_root": str(DATA / case_id), "physical_case_id": old_owner["physical_case_id"], "physical_condition_sha256": physical_hash,
            "source_definition": str(source_definition), "source_definition_sha256": definition_sha, "source_plan": str(source_plan), "source_plan_sha256": plan_sha, "owner_provenance": str(owner_path), "owner_provenance_sha256": sha(owner_path),
            "source_only": True, "disabled": True, "execution_allowed": False, "launch": False, "launch_allowed": False, "launch_owner": "root", "status": "source_only_disabled_waiting_root_gencase_initial_qa", "qualification_claim": "none", "production_claim": "none", "numerical_precision_status": "not_accepted", "native_initial_velocity_status": "pending downstream solver-saved frame0 PartVTK audit", "no_forcing": True, "no_mdbc": True, "no_motion": True, "no_solver_option_mutation": True,
            "physical_window_s": [0.0, float(tmax)], "estimated_peak_gpu_mib": 8192, "estimated_storage_bytes": 17179869184, "max_wall_seconds": 14400, "cpu_threads": 4, "target_gpu_index": None, "q_n": "not_assessed", "production_approval": "none", "independent_case_count_increment": 0,
            "fresh085_circular_source_replaced": True,
        }
        write_json(f"requests/{case_id}.full-native-qualification.request.json", native_request)
        case_rows.append({
            "case_id": case_id, "physical_case_id": old_owner["physical_case_id"], "physical_condition_sha256": physical_hash,
            "source_definition": str(source_definition), "source_definition_sha256": definition_sha, "source_plan": str(source_plan), "source_plan_sha256": plan_sha,
            "initial_velocity_m_per_s": velocity, "expected_native_frames": frames, "actual_root283_attempt_id": actual["attempt_id"], "actual_root283_receipt": str(actual["receipt_path"]), "actual_root283_receipt_sha256": actual["receipt_sha256"],
            "actual_prepared_input_report": str(actual["report_path"]), "actual_prepared_input_report_sha256": actual["report_sha256"], "actual_particle_counts": counts, "actual_total_particles": actual["actual_total_particles"], "generated_xml_sha256": actual["generated_xml_sha256"], "generated_bi4_sha256": actual["generated_bi4_sha256"],
            "gencase_initial_qa_request": str(genqa_request_path), "native_solver_request": str(native_request_path), "native_frame0_qa_request": str(frame_request_path), "status": "root283_completed_gencase_initial_qa_pending",
            "source085_circular_replaced": True,
        })
        actual_rows.append({"case_id": case_id, "actual_attempt_id": actual["attempt_id"], "report": str(actual["report_path"]), "report_sha256": actual["report_sha256"], "receipt": str(actual["receipt_path"]), "receipt_sha256": actual["receipt_sha256"], "counts": counts, "total": actual["actual_total_particles"], "xml_sha256": actual["generated_xml_sha256"], "bi4_sha256": actual["generated_bi4_sha256"]})

    write_json("metadata/fresh085-circular-evidence.json", {
        "schema": "ds02.f1.fresh086.fresh085-circular-evidence.v1", "preserved_unchanged": True,
        "historical_package": str(OLD), "historical_commit": "65220599bded147d4c0b3e32d119509b7faa76ae", "historical_manifest_sha256": sha(OLD / "manifest.json"),
        "observed_cycle": {"native_depended_on_frame0_qa": True, "frame0_qa_required_native_receipt": True, "native_gate_required_frame0_before_solver": True},
        "replacement": "fresh086 Root283 -> GenCase initial QA -> Root230 native -> native frame-0 QA",
        "current_package_does_not_edit_historical_bytes": True,
    })
    write_json("metadata/root283-actual-summary.json", {
        "schema": "ds02.f1.fresh086.root283-actual-summary.v1", "family_id": "F1", "handoff_id": "root_stage1_f1_first24_eight_height_genuine_gencase_283", "root283_handoff": str(ROOT283_HANDOFF), "actual_case_count": 8, "actual_receipts_completed_zero": True,
        "actual_report_contract": "ds02.root.actual-native-source-preflight.v1; read prepared/prepared-input-report.json", "counts_source": "generated_xml_particle_counts and actual_total_particles from each actual JSON report", "xml_data2d_source": "actual_generated_constants.data2d.value=false in each report", "gencase_initial_qa": "pending pre-native official PartVTK audit", "native_initial_qa": "downstream after native solver", "mass_evidence": "actual GenCase QA first; native binary weights remain a downstream audit", "arrays_read": False, "arrays_hashed": False, "shared_registry_or_ledger_modified": False, "cases": actual_rows,
    })
    write_json("metadata/candidate-registry.json", {
        "schema": "ds02.f1.fresh086.acyclic-candidate-registry.v1", "family_id": "F1", "scope_id": SCOPE, "fresh_id": "fresh086", "source_only": True, "execution_allowed": False, "launch_allowed": False, "actual_root283_case_count": 8, "gencase_initial_qa_pending": True, "all_gencase_qa_requests_disabled": True, "all_native_solver_requests_disabled": True, "all_native_frame0_qa_requests_disabled": True, "dependency_graph": "Root283 -> GenCase initial QA -> native solver -> native frame-0 QA", "cases": case_rows, "independent_case_count_increment": 0, "q_n": "not_assessed", "production_approval": "none", "scientific_arrays_read": False,
    })
    write_json("metadata/root230-policy.json", {"schema": "ds02.f1.fresh086.root230-policy-binding.v1", "dispatch": root230_dispatch(), "root_dataset_inventory_profile": ROOT230["profile"], "root_gpu_selection_profile": ROOT230["gpu_profile"], "root_solver_concurrency_cap": 8, "root_effective_reservation_function_sha256": ROOT230["reservation_sha256"], "source_only": True, "disabled": True, "launch_allowed": False, "physical_and_solver_recipe_unchanged": True})
    readme = f"""# F1 fresh086: acyclic GenCase initial QA -> native -> frame-0 QA source

fresh085 is preserved as historical evidence at `{OLD}` (commit
`65220599bded147d4c0b3e32d119509b7faa76ae`). Its native/frame-0 dependency
cycle is recorded in `metadata/fresh085-circular-evidence.json` and no byte in
that package is edited here.

This package binds the eight actual Root283 GenCase completed/0 receipts and
their nested `prepared/prepared-input-report.json` files. Root receives eight
independent disabled CPU `audit` requests in `requests/*.initial-qa.request.json`.
The pre-native worker uses the official PartVTK binary to check dynamic counts,
Idp/Zone identity, Type/Mk partition, finite and unique coordinates, positive
mass/density, and genuine 3-D extent. It does not inspect or use the GenCase
velocity declaration as solver initial-state proof, and it has no native
receipt/data dependency.

After each GenCase audit is actually completed/0, Root may review the matching
`*.full-native-qualification.request.json`. These requests preserve the exact
Root230 solver command, source XML, DUAL 4.0 s / 401-frame or ECC 1.6 s /
161-frame windows, `-tout:0.01`, DP, geometry, and velocity. Their only QA gate
is the completed pre-native GenCase audit; native frame-0 QA is explicitly
represented by a separate downstream request and cannot gate solver launch.

The downstream `*.native-frame0-qa.request.json` depends only on its completed
native attempt and uses the existing official PartVTK native frame-0 worker.
All future receipts/digests are null, every request is disabled, no Q-N or
production approval is granted, and the package performs no GenCase, PartVTK,
solver, array, registry, or ledger operation.
"""
    (PACKAGE / "README.md").write_text(readme, encoding="utf-8")
    subprocess.run([str(PYTHON), str(PACKAGE / "validate_source_contract.py"), "--output", str(PACKAGE / "metadata/static-validation.json")], check=True)
    files = []
    for path in sorted(PACKAGE.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            files.append({"path": str(path.relative_to(PACKAGE)), "bytes": path.stat().st_size, "sha256": sha(path)})
    write_json("manifest.json", {
        "schema": "ds02.f1.fresh086-manifest.v1", "family_id": "F1", "fresh_id": "fresh086", "commit_scope": str(PACKAGE), "files": files, "actual_root283_count": 8, "gencase_initial_qa_request_count": 8, "native_request_count": 8, "native_frame0_qa_request_count": 8, "dependency_graph": "Root283 -> GenCase initial QA -> native solver -> native frame-0 QA", "arrays_read": False, "arrays_hashed": False, "execution_allowed": False, "launch_allowed": False, "shared_registry_or_ledger_modified": False,
    })
    print(json.dumps({"package": str(PACKAGE), "case_count": 8, "dependency_graph": "Root283 -> GenCase initial QA -> native solver -> native frame-0 QA", "manifest_files": len(files)}, indent=2, sort_keys=True))


if __name__ == "__main__":
    build()
