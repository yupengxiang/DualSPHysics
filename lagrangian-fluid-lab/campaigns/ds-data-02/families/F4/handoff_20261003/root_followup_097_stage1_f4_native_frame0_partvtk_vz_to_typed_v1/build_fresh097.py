#!/usr/bin/env python3
"""Build the disabled F4 fresh097 frame-0 and typed handoff.

Only JSON/XML/Python metadata is consumed here.  Native BI4/VTK/H5/CSV/DAT
payloads are deferred to the Root-owned CPU worker.  The builder is
refreshable: rerunning it after Root515 closes a receipt changes only the
metadata snapshot and the matching receipt references, never a solver output.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


WORKTREE = Path("/home/jade/.codex/worktrees/ds-data-02-f4/DualSPHysics").resolve()
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics").resolve()
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02").resolve()
PACKAGE = Path(__file__).resolve().parent
FRESH096 = WORKTREE / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F4/handoff_20261003/root_followup_096_stage1_f4_root502_basicqa_to_root230_full1201_native_v1"
ROOT514 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f4_actual_basicQA502_Gen444_full1201_native24_514"
ROOT230 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_native_home_floor_eight_solver_dispatch_230"
ROOT134 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f3_first24_eight_solver_resource_policy_134"
RUNTIME = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
STRICT = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py"
RESOURCE = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json"
SOLVER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64").resolve()
PARTVTK = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64").resolve()
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump").resolve()
CONVERTER = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_nvme_convert_v1.py"
DIRECT_CONVERTER = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_direct_convert.py"
PYTHON = INTEGRATION / "lagrangian-fluid-lab/.venv/bin/python"
RAW_SUFFIXES = {".bi4", ".h5", ".vtk", ".vtu", ".vtp", ".csv", ".dat"}
STATIC_SUFFIXES = {".json", ".jsonl", ".xml", ".py", ".md", ".txt", ".log", ".linux64", ".10", ""}
HEX = set("0123456789abcdef")
FRESH_ID = "fresh097"
SCOPE_ID = "F4_STAGE1_ROOT514_NATIVE_FRAME0_PARTVTK_VZ_TO_TYPED_V1"
PARTVTK_SHA = "62630430902484f4aede017108313673fe6414f40fb59b6ae7f14ac23219db00"
DECODER_SHA = "b8ac8cf4aff68ffd089da6cf3ef19dfd0c6473121475f4c198b720a0ddaa8b2e"
CONVERTER_SHA = "b9904026a201ef271c5cb4a80a7707034a542e01883cece915abb30955c5bad3"
DIRECT_CONVERTER_SHA = "8ec204edb5ac20f2d83e2b9a3b5e70eb45cf1104fe0ee4bd8c3413a241c10ccd"
STRICT_SHA = "81bdd60e5de4fec362807043ab632864405f1667a0658560fb9349025aab75ec"


def load(path: Path) -> dict[str, Any]:
    path = Path(path).resolve()
    if path.suffix.lower() in RAW_SUFFIXES:
        raise ValueError(f"scientific payload cannot be loaded as source metadata: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def sha(path: Path) -> str:
    path = Path(path).resolve()
    if path.suffix.lower() in RAW_SUFFIXES:
        raise ValueError(f"scientific payload hash refused: {path}")
    if path.suffix.lower() not in STATIC_SUFFIXES:
        raise ValueError(f"non-static input cannot be hashed by source builder: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def valid_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value.lower()) <= HEX


def ref(path: Path) -> dict[str, str]:
    path = Path(path).resolve()
    return {"path": str(path), "sha256": sha(path)}


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def source_requests() -> dict[str, Path]:
    result: dict[str, Path] = {}
    for path in sorted((FRESH096 / "requests").glob("*-disabled.request.json")):
        request = load(path)
        case_id = str(request["case_id"])
        if case_id in result:
            raise ValueError(f"duplicate fresh096 case: {case_id}")
        result[case_id] = path.resolve()
    if len(result) != 24:
        raise ValueError(f"fresh096 must contain 24 cases, found {len(result)}")
    return result


def root514_request(case_id: str) -> Path:
    path = ROOT514 / f"{case_id}-native-request.json"
    if not path.is_file():
        raise FileNotFoundError(path)
    request = load(path)
    if request.get("case_id") != case_id or request.get("cpu_task_kind") != "native_solver":
        raise ValueError(f"Root514 request contract drift: {case_id}")
    if request.get("expected_native_frames") != 1201 or request.get("solver_recipe", {}).get("time_out_s") != 0.001:
        raise ValueError(f"Root514 recipe drift: {case_id}")
    return path.resolve()


def native_receipt(case_id: str) -> Path | None:
    root = DATA / "families/F4" / case_id
    matches = sorted(root.glob("*full1201-native-root230-fresh096-root502qa-root514/execution-receipt.json"))
    if len(matches) > 1:
        raise ValueError(f"multiple Root514 receipts for {case_id}")
    return matches[0].resolve() if matches else None


def native_state(case_id: str, request_path: Path) -> dict[str, Any]:
    request = load(request_path)
    receipt_path = native_receipt(case_id)
    receipt = load(receipt_path) if receipt_path else None
    attempt_id = str(request["attempt_id"])
    output_root = str(receipt.get("output_root")) if receipt and receipt.get("output_root") else str(DATA / "families/F4" / case_id / attempt_id)
    status = str(receipt.get("status")) if receipt else "WAIT"
    returncode = receipt.get("returncode") if receipt else None
    complete = status == "completed" and returncode == 0
    return {
        "case_id": case_id,
        "root514_request": ref(request_path),
        "root514_attempt_id": attempt_id,
        "root514_request_sha256": sha(request_path),
        "receipt": ref(receipt_path) if receipt_path else None,
        "receipt_status": status,
        "receipt_returncode": returncode,
        "native_status": "completed/0" if complete else "WAIT",
        "wait_reason": None if complete else ("receipt_not_completed0" if receipt_path else "receipt_not_yet_published"),
        "output_root": output_root,
        "data_root": str(Path(output_root) / "solver_output/data"),
        "frame0_bi4": str(Path(output_root) / "solver_output/data/Part_0000.bi4"),
    }


def actual_case(source_request_path: Path, state: dict[str, Any]) -> dict[str, Any]:
    source = load(source_request_path)
    owner_path = Path(source["physical_binding"]["path"]).resolve()
    owner = load(owner_path)
    evidence = source["gencase_actual_evidence"]
    prepared_xml = Path(evidence["prepared_xml"]["path"]).resolve()
    prepared_report = Path(evidence["prepared_report"]["path"]).resolve()
    generated_xml_sha = str(evidence["prepared_xml"]["sha256"])
    require_static = [owner_path, prepared_xml, prepared_report, Path(source["gencase_receipt"])]
    for path in require_static:
        if not path.is_file():
            raise FileNotFoundError(path)
    velocities = owner.get("initial_state", {}).get("velocities_m_per_s")
    if not isinstance(velocities, dict) or set(velocities) != {"mkfluid:0", "mkfluid:1"}:
        raise ValueError(f"F4 owner velocity contract drift: {source['case_id']}")
    counts = evidence
    return {
        "case_id": source["case_id"],
        "physical_case_id": source["physical_case_id"],
        "physical_condition_sha256": source["physical_condition_sha256"],
        "source_plan_condition_sha256": source["source_plan_condition_sha256"],
        "owner": ref(owner_path),
        "owner_velocity_by_mk": velocities,
        "generated_xml": str(prepared_xml),
        "generated_xml_sha256": generated_xml_sha,
        "prepared_input_report": str(prepared_report),
        "gencase_receipt": str(Path(source["gencase_receipt"]).resolve()),
        "gencase_receipt_sha256": source["gencase_receipt_sha256"],
        "actual_particle_counts": {
            "fixed": int(counts["fixed_particles"]),
            "moving": int(counts.get("moving_particles", 0)),
            "floating": int(counts.get("floating_particles", 0)),
            "fluid": int(counts["fluid_particles"]),
        },
        "actual_total_particles": int(counts["total_particles"]),
        "expected_native_types": source["solver_recipe"]["native_types"],
        "native_recipe": source["solver_recipe"],
        "native": state,
        "partvtk": str(PARTVTK),
        "partvtk_sha256": PARTVTK_SHA,
        "velocity_tolerance_m_per_s": 1e-6,
        "source_request": ref(source_request_path),
    }


def static_inputs(case: dict[str, Any], binding_path: Path, source_request_path: Path,
                  root514_path: Path, worker_path: Path, *, include_receipt: bool) -> list[Path]:
    paths = [
        worker_path, binding_path, source_request_path, root514_path,
        Path(case["owner"]["path"]), Path(case["generated_xml"]), Path(case["prepared_input_report"]),
        Path(case["gencase_receipt"]), RUNTIME, STRICT, RESOURCE,
        ROOT230 / "launch.py", ROOT230 / "root_native_home_floor_inventory_policy.py",
        ROOT230 / "source-policy-contract.json", ROOT134 / "ds02_root_all_idle_gpu_policy_v2.py",
        PARTVTK, DECODER, CONVERTER, DIRECT_CONVERTER, PYTHON,
    ]
    if include_receipt and case["native"].get("receipt"):
        paths.append(Path(case["native"]["receipt"]["path"]))
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        path = Path(path).resolve()
        if str(path) not in seen:
            if not path.is_file():
                raise FileNotFoundError(path)
            # This deliberately rejects any accidental native BI4/H5/CSV/DAT input.
            sha(path)
            seen.add(str(path))
            result.append(path)
    return result


def input_hashes(paths: list[Path]) -> dict[str, str]:
    return {str(path.resolve()): sha(path) for path in paths}


def frame0_binding(case: dict[str, Any], path: Path) -> dict[str, Any]:
    native = case["native"]
    return {
        "schema": "ds02.f4.fresh097.native-frame0-binding.v1",
        "fresh_id": FRESH_ID,
        "scope_id": SCOPE_ID,
        "family_id": "F4",
        "case_id": case["case_id"],
        "physical_case_id": case["physical_case_id"],
        "physical_condition_sha256": case["physical_condition_sha256"],
        "source_plan_condition_sha256": case["source_plan_condition_sha256"],
        "source_owner": case["owner"],
        "source_native_request": case["source_request"],
        "root514_request": native["root514_request"],
        "root514_attempt_id": native["root514_attempt_id"],
        "root514_request_sha256": native["root514_request_sha256"],
        "native_solver_status": native["native_status"],
        "native_solver_receipt": native["receipt"]["path"] if native.get("receipt") else None,
        "native_solver_receipt_sha256": native["receipt"]["sha256"] if native.get("receipt") else None,
        "native_output_root": native["output_root"],
        "native_data_dir": native["data_root"],
        "native_frame0_bi4": native["frame0_bi4"],
        "generated_xml": case["generated_xml"],
        "generated_xml_sha256": case["generated_xml_sha256"],
        "prepared_input_report": case["prepared_input_report"],
        "gencase_receipt": case["gencase_receipt"],
        "gencase_receipt_sha256": case["gencase_receipt_sha256"],
        "actual_particle_counts": case["actual_particle_counts"],
        "actual_total_particles": case["actual_total_particles"],
        "expected_native_types": case["expected_native_types"],
        "expected_velocity_by_mk": case["owner_velocity_by_mk"],
        "velocity_tolerance_m_per_s": case["velocity_tolerance_m_per_s"],
        "partvtk": case["partvtk"],
        "partvtk_sha256": case["partvtk_sha256"],
        "source_only": True,
        "execution_allowed": False,
        "raw_science_payload_read_by_builder": False,
        "future_report": None,
        "future_report_sha256": None,
        "report_contract": {
            "official_partvtk_raw_fields": ["Mk", "Type", "Idp", "Zone", "Pos.x [m]", "Pos.y [m]", "Pos.z [m]", "Vel.x [m/s]", "Vel.y [m/s]", "Vel.z [m/s]"],
            "native_velocity_source": "saved Part_0000 official PartVTK rows",
            "gencase_velocity_used_as_evidence": False,
            "frame0_count_policy": "report actual observed rows; never pad/exclude to GenCase count",
            "mass_rescaling": False,
            "q_n": "not_assessed",
            "production_approval": "none",
        },
    }


def frame0_request(case: dict[str, Any], binding_path: Path, source_request_path: Path,
                   root514_path: Path, worker_path: Path) -> dict[str, Any]:
    native = case["native"]
    attempt = f"root-stage1-f4-{case['case_id'].lower()}-native-frame0-partvtk-vz-fresh097"
    inputs = static_inputs(case, binding_path, source_request_path, root514_path, worker_path,
                           include_receipt=native["native_status"] == "completed/0")
    output = f"{DATA}/families/F4/{case['case_id']}/{attempt}"
    return {
        "schema": "ds02.runner-request.v2",
        "family_id": "F4",
        "case_id": case["case_id"],
        "attempt_id": attempt,
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 2,
        "command": [str(PYTHON), str(worker_path), "--binding", str(binding_path), "--output-dir", "{attempt_root}/audit"],
        "cwd": str(WORKTREE),
        "worktree_root": str(WORKTREE),
        "max_wall_seconds": 1800,
        "estimated_storage_bytes": 2 * 1024 ** 3,
        "input_files": [str(path) for path in inputs],
        "input_sha256": input_hashes(inputs),
        "disabled": True,
        "execution_allowed": False,
        "launch": False,
        "launch_allowed": False,
        "launch_owner": "root",
        "source_only": True,
        "status": "source_only_disabled_waiting_native_completed0" if native["native_status"] != "completed/0" else "source_only_disabled_ready_native_completed0",
        "disabled_reason": "Root must independently bind the matching Root514 completed/0 receipt and materialize the native BI4 input digest before enabling this CPU audit. No GenCase velocity declaration substitutes for this audit.",
        "depends_on_attempts": [case["source_request"]["path"], native["root514_attempt_id"]],
        "native_solver_gate": {
            "status": native["native_status"],
            "receipt": native["receipt"],
            "receipt_is_completed0": native["native_status"] == "completed/0",
        },
        "binding": {"path": str(binding_path.resolve()), "sha256": sha(binding_path)},
        "native_frame0_audit_contract": {
            "official_partvtk_only": True,
            "raw_mk_type_required": True,
            "raw_velocity_required": True,
            "expected_output": str(Path(output) / "audit/native-frame0-partvtk-vz-audit.json"),
            "future_report_sha256": None,
        },
        "physical_case_id": case["physical_case_id"],
        "physical_condition_sha256": case["physical_condition_sha256"],
        "native_recipe": case["native_recipe"],
        "expected_frames": 1201,
        "expected_particles_from_gencase": case["actual_total_particles"],
        "expected_fluid_particles_from_gencase": case["actual_particle_counts"]["fluid"],
        "root230_policy": {
            "profile": "root_live_all_idle_uuid_leased_eight_solver_v2",
            "foreign_gpu_protection": True,
            "home_free_gib_floor": 500,
            "nvme_free_gib_floor": 100,
            "nvme_peak_gib": 24,
        },
        "resource_contract": {
            "parent_gpu_hours": 512, "parent_cpu_core_hours": 3840,
            "qualification_slots": 1024, "production_slots": 720,
            "deadline": "2026-10-14T07:23:48+00:00",
        },
        "arrays_read_by_source": False,
        "jobs_started_by_source": False,
        "shared_registry_write_by_source": False,
        "q_n": "not_assessed",
        "production_approval": "none",
    }


def typed_binding(case: dict[str, Any], frame0_request_path: Path, frame0_request_sha: str,
                  path: Path) -> dict[str, Any]:
    native = case["native"]
    return {
        "schema": "ds02.f4.fresh097.typed-binding.v1",
        "fresh_id": FRESH_ID,
        "scope_id": SCOPE_ID,
        "family_id": "F4",
        "case_id": case["case_id"],
        "physical_case_id": case["physical_case_id"],
        "physical_condition_sha256": case["physical_condition_sha256"],
        "source_plan_condition_sha256": case["source_plan_condition_sha256"],
        "source_owner": case["owner"],
        "source_native_request": case["source_request"],
        "actual_converter_scope": {
            "status": "future_root_converter_physical_condition_scope_preflight",
            "canonical_hash": None,
            "legacy_scope_hash": None,
            "source_owner_sha256_must_not_be_reused_as_converter_scope": True,
        },
        "native_solver": {
            "status": native["native_status"],
            "attempt_id": native["root514_attempt_id"],
            "receipt": native["receipt"],
            "data_root": native["data_root"],
            "expected_frames": 1201,
            "time_window_s": 1.2,
            "save_interval_s": 0.001,
        },
        "frame0_velocity_audit": {
            "request": {"path": str(frame0_request_path.resolve()), "sha256": frame0_request_sha},
            "status": "WAIT",
            "report": None,
            "report_sha256": None,
            "raw_mk_type_required": True,
            "raw_velocity_required": True,
        },
        "gencase_actual_evidence": {
            "receipt": case["gencase_receipt"],
            "receipt_sha256": case["gencase_receipt_sha256"],
            "generated_xml": case["generated_xml"],
            "generated_xml_sha256": case["generated_xml_sha256"],
            "actual_particle_counts": case["actual_particle_counts"],
            "actual_total_particles": case["actual_total_particles"],
            "dimension": 3,
        },
        "source_only": True,
        "execution_allowed": False,
        "future_hashes": {
            "trajectory_h5_sha256": None,
            "conversion_report_sha256": None,
            "typed_partvtk_sha256": None,
            "execution_receipt_sha256": None,
        },
        "typed_contract": {
            "vector_semantic_type": "N3",
            "preserve_native_identity": "Idp/Zone/Type/Mk; no row padding or mass rescale",
            "full_native_frames": 1201,
            "full_time_window_s": 1.2,
            "output_timestep_s": 0.001,
            "expected_particles_from_gencase": case["actual_total_particles"],
            "expected_fluid_particles_from_gencase": case["actual_particle_counts"]["fluid"],
        },
        "path": str(path.resolve()),
    }


def typed_request(case: dict[str, Any], binding_path: Path, frame0_request_path: Path,
                  frame0_request_sha: str, source_request_path: Path, root514_path: Path,
                  worker_path: Path) -> dict[str, Any]:
    native = case["native"]
    attempt = f"root-stage1-f4-{case['case_id'].lower()}-full1201-typed-nvme-fresh097"
    typed_binding_path = binding_path
    native_receipt = native.get("receipt")
    receipt_arg = native_receipt["path"] if native_receipt else "{native_solver_receipt}"
    command = [
        str(PYTHON), str(CONVERTER), "--staging-root", "/tmp/ds02-nvme-conversion",
        "--staging-limit-bytes", str(24 * 1024 ** 3), "--", "--data-root", native["data_root"],
        "--generated-xml", case["generated_xml"], "--output", "{attempt_root}/trajectory.h5",
        "--report", "{attempt_root}/conversion-report.json", "--decoder", str(DECODER),
        "--partvtk", str(PARTVTK), "--validation-dir", "{attempt_root}/partvtk-validation",
        "--solver-log", str(Path(native["output_root"]) / "solver_output/Run.out"),
        "--solver-receipt", receipt_arg, "--gencase-receipt", case["gencase_receipt"],
        "--owner-metadata", str(typed_binding_path), "--keep-validation-csv", "--particle-chunk", "65536",
    ]
    inputs = static_inputs(case, typed_binding_path, source_request_path, root514_path, worker_path,
                           include_receipt=native["native_status"] == "completed/0")
    inputs.extend([frame0_request_path])
    seen = {str(path.resolve()) for path in inputs}
    inputs = [path for path in inputs if str(path.resolve()) in seen]
    return {
        "schema": "ds02.runner-request.v2",
        "family_id": "F4",
        "case_id": case["case_id"],
        "attempt_id": attempt,
        "kind": "cpu",
        "cpu_task_kind": "conversion",
        "cpu_threads": 2,
        "command": command,
        "cwd": str(WORKTREE),
        "worktree_root": str(WORKTREE),
        "max_wall_seconds": 14400,
        "estimated_storage_bytes": 24 * 1024 ** 3,
        "input_files": [str(path) for path in inputs],
        "input_sha256": input_hashes(inputs),
        "disabled": True,
        "execution_allowed": False,
        "launch": False,
        "launch_allowed": False,
        "launch_owner": "root",
        "source_only": True,
        "status": "source_only_disabled_waiting_frame0_velocity_audit",
        "disabled_reason": "Root may enable only after matching Root514 native completed/0 and an independent fresh097 official-PartVTK frame0 raw Mk/Type/vz report pass. Root must then derive and bind the actual converter physical-condition scope; source owner SHA is not a converter scope hash.",
        "depends_on_attempts": [native["root514_attempt_id"], f"{case['case_id']}-native-frame0-partvtk-vz-fresh097"],
        "native_receipt": native_receipt,
        "native_receipt_status": native["native_status"],
        "frame0_velocity_audit": {
            "request": {"path": str(frame0_request_path.resolve()), "sha256": frame0_request_sha},
            "report": None,
            "report_sha256": None,
            "status": "WAIT",
        },
        "typed_binding": {"path": str(typed_binding_path.resolve()), "sha256": sha(typed_binding_path)},
        "physical_case_id": case["physical_case_id"],
        "physical_condition_sha256": case["physical_condition_sha256"],
        "source_plan_condition_sha256": case["source_plan_condition_sha256"],
        "gencase_actual_evidence": {
            "receipt": case["gencase_receipt"],
            "receipt_sha256": case["gencase_receipt_sha256"],
            "generated_xml": case["generated_xml"],
            "generated_xml_sha256": case["generated_xml_sha256"],
            "actual_particle_counts": case["actual_particle_counts"],
            "actual_total_particles": case["actual_total_particles"],
            "dimension": 3,
        },
        "output_contract": {
            "full_native_frames": 1201,
            "time_window_s": 1.2,
            "output_timestep_s": 0.001,
            "expected_native_particles": case["actual_total_particles"],
            "expected_native_fluid_particles": case["actual_particle_counts"]["fluid"],
            "vector_semantic_type": "N3",
            "future_sha256_values": None,
            "typed_frames": None,
            "typed_particles": None,
            "typed_fluid_particles": None,
            "partvtk_all_passed": None,
        },
        "storage_contract": {
            "conversion_slots": 2,
            "staging_root": "/tmp/ds02-nvme-conversion",
            "staging_limit_bytes": 24 * 1024 ** 3,
            "nvme_free_space_floor_bytes": 100 * 1024 ** 3,
            "home_free_space_floor_gib": 500,
            "no_duplicate_source_or_solver": True,
        },
        "converter_provenance": {
            "converter": str(CONVERTER), "converter_sha256": CONVERTER_SHA,
            "direct_converter": str(DIRECT_CONVERTER), "direct_converter_sha256": DIRECT_CONVERTER_SHA,
            "official_decoder": str(DECODER), "official_decoder_sha256": DECODER_SHA,
            "official_partvtk": str(PARTVTK), "official_partvtk_sha256": PARTVTK_SHA,
            "physical_scope": "derive actual legacy/canonical scope with converter preflight; do not copy owner hash",
        },
        "root230_policy": {
            "profile": "root_live_all_idle_uuid_leased_eight_solver_v2",
            "foreign_gpu_protection": True,
            "home_free_gib_floor": 500,
            "nvme_free_gib_floor": 100,
            "nvme_peak_gib": 24,
        },
        "resource_contract": {
            "parent_gpu_hours": 512, "parent_cpu_core_hours": 3840,
            "qualification_slots": 1024, "production_slots": 720,
            "deadline": "2026-10-14T07:23:48+00:00",
        },
        "arrays_read_by_source": False,
        "jobs_started_by_source": False,
        "shared_registry_write_by_source": False,
        "q_n": "not_assessed",
        "production_approval": "none",
    }


def main() -> None:
    worker = PACKAGE / "workers/native_frame0_partvtk_vz_audit.py"
    source = source_requests()
    all_cases: list[dict[str, Any]] = []
    completed = 0
    waiting = 0
    for case_id, source_path in sorted(source.items()):
        root_path = root514_request(case_id)
        state = native_state(case_id, root_path)
        case = actual_case(source_path, state)
        all_cases.append(case)
        if state["native_status"] == "completed/0":
            completed += 1
        else:
            waiting += 1

    frame_requests: list[dict[str, Any]] = []
    typed_requests: list[dict[str, Any]] = []
    frame_refs: list[dict[str, str]] = []
    typed_refs: list[dict[str, str]] = []
    for case in all_cases:
        case_id = case["case_id"]
        safe = case_id
        frame_binding_path = PACKAGE / "metadata/bindings" / f"{safe}.native-frame0-binding.json"
        frame_request_path = PACKAGE / "requests" / f"{safe}.native-frame0-partvtk-vz-fresh097-disabled.request.json"
        root_path = Path(case["native"]["root514_request"]["path"])
        frame_binding = frame0_binding(case, frame_binding_path)
        dump(frame_binding_path, frame_binding)
        frame_req = frame0_request(case, frame_binding_path, Path(case["source_request"]["path"]), root_path, worker)
        dump(frame_request_path, frame_req)
        frame_requests.append(frame_req)
        frame_refs.append({"case_id": case_id, "path": str(frame_request_path.resolve()), "sha256": sha(frame_request_path), "binding": str(frame_binding_path.resolve()), "binding_sha256": sha(frame_binding_path)})

        typed_binding_path = PACKAGE / "metadata/bindings" / f"{safe}.typed-binding.json"
        typed_request_path = PACKAGE / "typed-requests" / f"{safe}.typed-nvme-fresh097-disabled.request.json"
        typed_bind = typed_binding(case, frame_request_path, sha(frame_request_path), typed_binding_path)
        dump(typed_binding_path, typed_bind)
        typed_req = typed_request(case, typed_binding_path, frame_request_path, sha(frame_request_path), Path(case["source_request"]["path"]), root_path, worker)
        dump(typed_request_path, typed_req)
        typed_requests.append(typed_req)
        typed_refs.append({"case_id": case_id, "path": str(typed_request_path.resolve()), "sha256": sha(typed_request_path), "binding": str(typed_binding_path.resolve()), "binding_sha256": sha(typed_binding_path)})

    snapshot = {
        "schema": "ds02.f4.fresh097.native-state-snapshot.v1",
        "fresh_id": FRESH_ID,
        "scope_id": SCOPE_ID,
        "source_only": True,
        "scientific_payloads_read_or_hashed": False,
        "case_count": len(all_cases),
        "native_completed0_count": completed,
        "native_wait_count": waiting,
        "cases": [{"case_id": c["case_id"], "native": c["native"]} for c in all_cases],
        "refresh_rule": "Rerun after Root515 receipt publication; only JSON receipt state and references change.",
    }
    dump(PACKAGE / "metadata/native-state-snapshot.json", snapshot)
    stage = {
        "schema": "ds02.f4.fresh097.stage-contract.v1",
        "fresh_id": FRESH_ID,
        "scope_id": SCOPE_ID,
        "family_id": "F4",
        "case_count": 24,
        "native_upstream": {"root514": str(ROOT514), "required": "matching completed/0 execution-receipt.json"},
        "frame0_phase": {"cpu_task_kind": "audit", "worker": str(worker.resolve()), "official_partvtk_raw_fields": ["Mk", "Type", "Vel.z [m/s]"], "status": "disabled_waiting_native_receipts_and_root_enablement"},
        "typed_phase": {"cpu_task_kind": "conversion", "converter": str(CONVERTER), "conversion_slots": 2, "status": "disabled_waiting_frame0_audit_pass"},
        "recipe": {"dp_m": 0.01, "frames": 1201, "time_window_s": 1.2, "tout_s": 0.001, "omp_threads": 2},
        "read_policy": {"bi4": "deferred Root-owned worker", "csv": "deferred Root-owned PartVTK worker", "h5": "deferred converter", "source_arrays": False},
        "future_hashes_null": True,
        "root471_negative_preserved": True,
        "root500_history_preserved": True,
        "shared_registry_write": False,
    }
    dump(PACKAGE / "metadata/fresh097-stage-contract.json", stage)
    dump(PACKAGE / "metadata/fresh097-root230-contract.json", {
        "schema": "ds02.f4.fresh097.root230-contract.v1",
        "root230_profile": "root_live_all_idle_uuid_leased_eight_solver_v2",
        "foreign_gpu_protection": True,
        "uuid_selection": "Root resolves live UUID and lease; source selects none",
        "home_free_gib_floor": 500,
        "nvme_free_gib_floor": 100,
        "nvme_peak_gib": 24,
        "conversion_slots": 2,
        "references": {"launch": ref(ROOT230 / "launch.py"), "home_policy": ref(ROOT230 / "root_native_home_floor_inventory_policy.py"), "contract": ref(ROOT230 / "source-policy-contract.json"), "strict_dispatch": ref(STRICT), "resource_window": ref(RESOURCE)},
    })
    dump(PACKAGE / "metadata/fresh097-manifest.json", {
        "schema": "ds02.f4.fresh097.manifest.v1",
        "fresh_id": FRESH_ID,
        "scope_id": SCOPE_ID,
        "family_id": "F4",
        "source_only": True,
        "case_count": 24,
        "native_completed0_count": completed,
        "native_wait_count": waiting,
        "frame0_requests": frame_refs,
        "typed_requests": typed_refs,
        "worker": ref(worker),
        "builder": ref(Path(__file__).resolve()),
        "root471_negative_preserved": True,
        "root500_history_preserved": True,
        "q_n": "not_assessed",
        "production_approval": "none",
        "scientific_payloads_read_or_hashed": False,
        "jobs_started_by_source": False,
        "shared_registry_write_by_source": False,
    })


if __name__ == "__main__":
    main()
