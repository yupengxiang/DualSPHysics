#!/usr/bin/env python3
"""Generate the disabled F7 fresh075 adapter and native request package."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


PACKAGE = Path(__file__).resolve().parents[1]
FRESH074 = PACKAGE.parent / "root_followup_074_stage1_next24_target_angles_v1"
PLAN = FRESH074 / "metadata" / "next24-plan.json"
OWNERS = FRESH074 / "owners"
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
ILAB = INTEGRATION / "lagrangian-fluid-lab"
HANDOFF = ILAB / "campaigns/ds-data-02/handoff_20261003"
VENV = ILAB / ".venv/bin/python"
PARTVTK = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64")
SOLVER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64")
RUNTIME = ILAB / "scripts/ds_data02_runtime_v2.py"
STRICT = ILAB / "scripts/ds_data02_strict_dispatch_v1.py"
GOAL = ILAB / "campaigns/ds-data-02/GOAL_STAGE1_VISUAL_GPT56LUNA_20261004_ZH.md"
GPU_POLICY = HANDOFF / "root_stage1_f3_first24_eight_solver_resource_policy_134/ds02_root_all_idle_gpu_policy_v2.py"
HOME_POLICY = HANDOFF / "root_stage1_native_home_floor_eight_solver_dispatch_230/root_native_home_floor_inventory_policy.py"
ROOT230 = HANDOFF / "root_stage1_native_home_floor_eight_solver_dispatch_230/launch.py"
RESOURCE = HANDOFF / "root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json"
GENCASE_TOOL = HANDOFF / "root_native_source_preflight_tools_003/gencase.py"
GENCASE_BINDER = FRESH074 / "scripts/bind_next24_gencase.py"

GROUP = "F7_STAGE1_NEXT24_TARGET_ANGLES"
MOTION_ATTEMPT = "root-stage1-f7-next24-motion-preparation-074"
GENCASE_BIND_ATTEMPT = "root-stage1-f7-next24-gencase-binding-074"
ADAPTER_ATTEMPT = "root-stage1-f7-next24-gencase-native-metadata-adapter-075"
QA_ATTEMPT = "root-stage1-f7-next24-native-initial-qa-075"
NATIVE_SUFFIX = "full601-native-qualification-075"
ADAPTER = PACKAGE / "scripts/bind_fresh075_actual_gencase_metadata.py"
WORKER = PACKAGE / "workers/run_f7_fresh075_native_initial_qa.py"
CONTRACT = PACKAGE / "metadata/adapter-contract.json"
REVIEW = PACKAGE / "metadata/worker-contract-review.json"
PREFLIGHT = PACKAGE / "scripts/preflight_fresh075.py"

EXPECTED = {"total": 70179, "fixed": 27495, "moving": 1984, "floating": 0, "fluid": 40700, "dimension": 3}
PARTVTK_SHA = "62630430902484f4aede017108313673fe6414f40fb59b6ae7f14ac23219db00"
SOLVER_SHA = "0415b10e5e32af8b8b7ad2a703f9043dca67dfcf7626eb98f1c05a50856fde29"
RUNTIME_SHA = "5098262e26dc5560487760181466b0a93a0e66239e5e54047dce5e761ae67a60"
STRICT_SHA = "81bdd60e5de4fec362807043ab632864405f1667a0658560fb9349025aab75ec"
GPU_POLICY_SHA = "4e6f340222f7823ae9df1a145ccda884dcf401c9740fc78c51a88066ae1c88cd"
HOME_POLICY_SHA = "c9103e306f87bb5af871c5de28d9939aa05f0c95c72e1630778f4bcf50e91ab5"
ROOT230_SHA = "7f703fb94e17c2e2800873f4fcc021f9cd5f8201076afd8e10e3bc6a2d03396e"
RESOURCE_SHA = "2a35e26e36920d8ca40001fd7f28416f27bcf371b8b882eca37868f4a15152b8"


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def unique(paths: list[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key not in seen:
            result.append(path)
            seen.add(key)
    return result


def source_inputs() -> list[Path]:
    plan = load(PLAN)
    owners = [OWNERS / f"{row['endpoint_id']}.owner.json" for row in plan["endpoints"]]
    definitions = [FRESH074 / "source" / f"{row['endpoint_id']}_Def.xml" for row in plan["endpoints"]]
    return unique([
        PLAN, *owners, *definitions, GENCASE_BINDER, GENCASE_TOOL,
        ADAPTER, WORKER, CONTRACT, REVIEW, PREFLIGHT,
        VENV, PARTVTK, SOLVER, RUNTIME, STRICT, GPU_POLICY, HOME_POLICY,
        ROOT230, RESOURCE, GOAL,
    ])


def closure(paths: list[Path]) -> tuple[list[str], dict[str, str]]:
    files = []
    hashes = {}
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(path)
        key = str(path.resolve())
        files.append(key)
        hashes[key] = sha(path)
    return files, hashes


def gencase_paths(case_id: str) -> dict[str, str]:
    attempt = DATA / "families" / "F7" / case_id / f"root-stage1-f7-{case_id.lower()}-genuine-gencase-074"
    prepared = attempt / "prepared"
    return {
        "attempt": str(attempt),
        "receipt": str(attempt / "execution-receipt.json"),
        "report": str(prepared / "prepared-input-report.json"),
        "xml": str(prepared / f"{case_id}.xml"),
        "bi4": str(prepared / f"{case_id}.bi4"),
        "definition": str(prepared / f"{case_id}_Def.xml"),
        "motion": str(prepared / "motion_obstacle_quintic.dat"),
        "runtime_evidence": str(DATA / "families" / "F7" / GROUP / ADAPTER_ATTEMPT / "binding" / "cases" / f"{case_id}.gencase-runtime-evidence.json"),
    }


def metadata_future_inputs(plan: dict[str, Any]) -> list[str]:
    rows: list[str] = [
        str(DATA / "families" / "F7" / GROUP / MOTION_ATTEMPT / "execution-receipt.json"),
        str(DATA / "families" / "F7" / GROUP / MOTION_ATTEMPT / "prepared/motion-source-preparation.json"),
        str(DATA / "families" / "F7" / GROUP / GENCASE_BIND_ATTEMPT / "bindings/gencase-bindings.json"),
    ]
    for endpoint in plan["endpoints"]:
        paths = gencase_paths(endpoint["endpoint_id"])
        rows.extend(paths[key] for key in ("receipt", "report", "xml", "bi4", "definition", "motion"))
    return rows


def common(request: dict[str, Any], inputs: list[Path]) -> dict[str, Any]:
    files, hashes = closure(unique(inputs))
    request.update({
        "schema": "ds02.runner-request.v2",
        "family_id": "F7",
        "worktree_root": str(INTEGRATION),
        "cwd": request.get("cwd", str(ILAB)),
        "input_files": files,
        "input_sha256": hashes,
        "future_hashes_null": True,
        "launch": False,
        "launch_allowed": False,
        "execution_allowed": False,
        "disabled": True,
        "launch_owner": "root",
        "no_arrays_read": True,
        "no_jobs_started": True,
        "no_shared_registry_write": True,
        "root_review_required": True,
        "strict_dispatch_entrypoint": str(STRICT),
        "strict_dispatch_sha256": STRICT_SHA,
        "runtime_entrypoint": str(RUNTIME),
        "runtime_sha256": RUNTIME_SHA,
        "root230_entrypoint": str(ROOT230),
        "root230_entrypoint_sha256": ROOT230_SHA,
        "root_inventory_policy": str(HOME_POLICY),
        "root_inventory_policy_sha256": HOME_POLICY_SHA,
        "gpu_policy": str(GPU_POLICY),
        "gpu_policy_sha256": GPU_POLICY_SHA,
        "resource_approval": str(RESOURCE),
        "resource_approval_sha256": RESOURCE_SHA,
        "resource_window": {
            "gpu_hours_total": 512,
            "cpu_core_hours_total": 3840,
            "qualification_hours": 1024,
            "production_hours": 720,
            "home_floor_gib": 500,
            "nvme_floor_gib": 100,
            "shared_gpu_lease": "Root230 eight-live-UUID lease; foreign-process protection required",
        },
        "physical_mass_kg": 320.1984,
        "native_support_mass_kg": 325.60001628,
        "mass_policy": "native and continuum masses remain separate; no rescale",
        "precision_status": "not_accepted",
        "q_n_status": "not_assessed",
        "production_approval": "none",
    })
    return request


def main() -> int:
    plan = load(PLAN)
    endpoints = plan["endpoints"]
    source = source_inputs()
    future = metadata_future_inputs(plan)
    future_hashes = {path: None for path in future}
    motion_receipt = DATA / "families" / "F7" / GROUP / MOTION_ATTEMPT / "execution-receipt.json"
    motion_report = DATA / "families" / "F7" / GROUP / MOTION_ATTEMPT / "prepared/motion-source-preparation.json"
    group_path = DATA / "families" / "F7" / GROUP / GENCASE_BIND_ATTEMPT / "bindings/gencase-bindings.json"
    adapter_output = DATA / "families" / "F7" / GROUP / ADAPTER_ATTEMPT / "binding/binding.json"
    adapter_evidence = [
        DATA / "families" / "F7" / GROUP / ADAPTER_ATTEMPT / "binding" / "cases" / f"{row['endpoint_id']}.gencase-runtime-evidence.json"
        for row in endpoints
    ]
    qa_root = DATA / "families" / "F7" / GROUP / QA_ATTEMPT
    qa_report = qa_root / "initial-qa/native-initial-qa.json"
    qa_receipt = qa_root / "execution-receipt.json"

    adapter_command = [
        str(VENV), str(ADAPTER), "--plan", str(PLAN), "--owners-root", str(OWNERS),
        "--motion-receipt", str(motion_receipt), "--motion-report", str(motion_report),
        "--gencase-bindings", str(group_path), "--data-root", str(DATA),
        "--gencase-attempt-suffix", "074", "--output", "{attempt_root}/binding/binding.json",
    ]
    adapter_request = common({
        "attempt_id": ADAPTER_ATTEMPT,
        "case_id": GROUP,
        "scope_id": "root_followup_075_actual_gencase_native_metadata_adapter_v1",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 2,
        "max_wall_seconds": 7200,
        "estimated_storage_bytes": 1073741824,
        "command": adapter_command,
        "depends_on_attempts": [MOTION_ATTEMPT, GENCASE_BIND_ATTEMPT],
        "future_input_files": future,
        "future_input_sha256": future_hashes,
        "output_contract": {
            "binding": "{attempt_root}/binding/binding.json",
            "case_count": 24,
        },
        "expected_counts": EXPECTED,
        "disabled_reason": "Root-only metadata adapter. Enable only after Root343 motion/GenCase receipts are completed/0; it must consume flat prepared/{case}.xml and prepared/{case}.bi4 paths.",
        "status": "source_only_disabled_pending_root_review",
        "source_plan": str(PLAN),
        "source_plan_sha256": sha(PLAN),
    }, source)
    write_json(PACKAGE / "requests/actual-gencase-metadata-adapter-request.json", adapter_request)

    qa_command = [
        str(VENV), str(WORKER), "--binding", str(adapter_output),
        "--output-dir", "{attempt_root}/initial-qa",
    ]
    qa_request = common({
        "attempt_id": QA_ATTEMPT,
        "case_id": GROUP,
        "scope_id": "root_followup_075_actual_gencase_native_metadata_adapter_v1",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 2,
        "max_wall_seconds": 7200,
        "estimated_storage_bytes": 96636764160,
        "command": qa_command,
        "depends_on_attempts": [ADAPTER_ATTEMPT],
        "future_input_files": [str(adapter_output), *(str(path) for path in adapter_evidence), *future[3:]],
        "future_input_sha256": {path: None for path in [str(adapter_output), *(str(path) for path in adapter_evidence), *future[3:]]},
        "output_contract": {
            "initial_qa_report": "{attempt_root}/initial-qa/native-initial-qa.json",
            "per_case_official_csv": "{attempt_root}/initial-qa/{case}-initial-all.csv",
            "case_count": 24,
        },
        "expected_counts": EXPECTED,
        "partvtk": str(PARTVTK),
        "partvtk_sha256": PARTVTK_SHA,
        "disabled_reason": "Root-only CPU PartVTK/NumPy audit. Enable after the fresh075 adapter has completed/0 and every actual GenCase receipt/report/XML/BI4 is bound; the source agent never runs this worker.",
        "status": "source_only_disabled_pending_actual_metadata_adapter",
        "source_plan": str(PLAN),
        "source_plan_sha256": sha(PLAN),
    }, [*source, PARTVTK])
    write_json(PACKAGE / "requests/native-initial-qa-execution-request.json", qa_request)

    for endpoint in endpoints:
        case = endpoint["endpoint_id"]
        paths = gencase_paths(case)
        attempt_id = f"root-stage1-f7-{case.lower()}-{NATIVE_SUFFIX}"
        solver_prefix = str(Path(paths["attempt"]) / "prepared" / case)
        native_command = [str(SOLVER), solver_prefix, "{attempt_root}/solver_output", "-tmax:12", "-tout:0.02"]
        future_case = [paths[key] for key in ("receipt", "report", "xml", "bi4", "definition", "motion", "runtime_evidence")]
        native_future = [*future_case, str(adapter_output), str(qa_report), str(qa_receipt)]
        request = common({
            "attempt_id": attempt_id,
            "case_id": case,
            "physical_case_id": case,
            "scope_id": "root_followup_075_actual_gencase_native_metadata_adapter_v1",
            "kind": "qualification",
            "cpu_task_kind": "solver",
            "cpu_threads": 4,
            "max_wall_seconds": 14400,
            "estimated_storage_bytes": 17179869184,
            "estimated_peak_gpu_mib": 4096,
            "command": native_command,
            "cwd": str(Path(paths["attempt"]) / "prepared"),
            "gencase_receipt": paths["runtime_evidence"],
            "gencase_receipt_sha256": None,
            "gencase_execution_receipt": paths["receipt"],
            "gencase_execution_receipt_sha256": None,
            "gencase_report": paths["report"],
            "gencase_report_sha256": None,
            "generated_xml": paths["xml"],
            "generated_xml_sha256": None,
            "generated_definition": paths["definition"],
            "generated_definition_sha256": None,
            "generated_bi4": paths["bi4"],
            "generated_bi4_sha256": None,
            "generated_motion": paths["motion"],
            "generated_motion_sha256": None,
            "initial_qa_binding": str(adapter_output),
            "initial_qa_binding_sha256": None,
            "initial_typed_qa": str(qa_report),
            "initial_typed_qa_sha256": None,
            "initial_typed_qa_receipt": str(qa_receipt),
            "initial_typed_qa_receipt_sha256": None,
            "physical_condition_sha256": endpoint["physical_condition_sha256"],
            "canonical_physical_binding_sha256": endpoint["canonical_physical_binding_sha256"],
            "source_plan_sha256": sha(PLAN),
            "future_input_files": native_future,
            "future_input_sha256": {path: None for path in native_future},
            "depends_on_attempts": [QA_ATTEMPT],
            "output_contract": {
                "frames": 601,
                "save_interval_s": 0.02,
                "time_window_s": [0.0, 12.0],
                "solver_output": "{attempt_root}/solver_output",
            },
            "expected_counts": EXPECTED,
            "disabled_reason": "Root-only native qualification. Enable only after Root's actual fresh075 adapter and PartVTK initial-QA report/receipt are completed/0 and review passes; all future receipts and solver outputs stay null in this source package.",
            "status": "source_only_disabled_pending_initial_native_qa",
        }, [*source, SOLVER])
        write_json(PACKAGE / "requests/native" / f"{case}.full601-native-qualification-075.disabled-request.json", request)

    manifest = {
        "schema": "ds02.f7.fresh075.manifest.v1",
        "scope_id": "root_followup_075_actual_gencase_native_metadata_adapter_v1",
        "family_id": "F7",
        "model_profile": "gpt-5.6-luna/max",
        "case_count": len(endpoints),
        "cases": [row["endpoint_id"] for row in endpoints],
        "source_plan": str(PLAN),
        "source_plan_sha256": sha(PLAN),
        "requests": {
            "gencase_metadata_adapter": "requests/actual-gencase-metadata-adapter-request.json",
            "native_initial_qa": "requests/native-initial-qa-execution-request.json",
            "native_qualification_directory": "requests/native",
        },
        "attempts": {"adapter": ADAPTER_ATTEMPT, "initial_qa": QA_ATTEMPT, "native_suffix": NATIVE_SUFFIX},
        "flat_prepared_layout": True,
        "expected_counts": EXPECTED,
        "arrays_read": False,
        "jobs_started": False,
        "shared_state_written": False,
        "future_hashes_null": True,
        "launch_allowed": False,
        "visual_acceptance": "not_assessed",
        "q_n": "not_granted",
        "precision_status": "not_accepted",
        "claim_boundary": "Fresh075 supplies metadata-only binding and disabled requests; no new GenCase/QA/native/visual/production result is claimed by this package.",
    }
    write_json(PACKAGE / "manifest.json", manifest)
    print(json.dumps({"package": str(PACKAGE), "case_count": len(endpoints), "requests_written": 26}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
