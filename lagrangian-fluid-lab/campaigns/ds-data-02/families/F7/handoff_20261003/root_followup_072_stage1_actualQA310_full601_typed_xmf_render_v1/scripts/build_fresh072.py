#!/usr/bin/env python3
"""Build F7 fresh072 typed/XMF/render source-only handoff.

This builder reads bounded JSON/XML/source metadata only. It never opens BI4,
CSV, H5, or motion payload bytes and never starts a job.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7")
INT = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
F7WT = Path("/home/jade/.codex/worktrees/ds-data-02-f7/DualSPHysics")
F071 = F7WT / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F7/handoff_20261003/root_followup_071_stage1_first24_actual_gencase_qa_native_v1"
F069 = F7WT / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F7/handoff_20261003/root_followup_069_stage1_actual_native156_full601_typed_xmf_render_v1"
R313 = INT / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f7_actualQA310_sixteen_full601_native_313"
QA_ROOT = DATA / "F7_STAGE1_FIRST24_TARGET_ANGLES/root-stage1-f7-first24-native-initial-qa-071"
QA_REPORT = QA_ROOT / "initial-qa/native-initial-qa.json"
QA_RECEIPT = QA_ROOT / "execution-receipt.json"
CASES = [f"F7_OBSTACLE_QUINTIC_B08_A{x:03d}" for x in (31, 32, 33, 34, 36, 37, 38, 39, 41, 42, 43, 44, 46, 47, 48, 49)]
SCOPE = "root_followup_072_stage1_actualQA310_full601_typed_xmf_render_v1"
RAW_SUFFIXES = (".bi4", ".csv", ".h5", ".dat", ".ibi4")


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load(path: Path) -> Any:
    return json.loads(path.read_text())


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def must_file(path: Path) -> Path:
    if not path.is_file():
        raise SystemExit(f"missing source metadata file: {path}")
    return path


def safe_hash(path: Path) -> str:
    s = str(path)
    if any(s.lower().endswith(x) for x in RAW_SUFFIXES) or "/solver_output/data/" in s:
        raise SystemExit(f"raw payload was selected as a source hash: {path}")
    return sha(must_file(path))


def input_hashes(paths: list[Path]) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in paths:
        path = path.resolve()
        if any(str(path).lower().endswith(x) for x in RAW_SUFFIXES) or "/solver_output/data/" in str(path):
            raise SystemExit(f"raw payload selected as request input: {path}")
        result[str(path)] = safe_hash(path)
    return result


def json_path(root: Path, rel: str) -> str:
    return str((root / rel).resolve())


def compact_owner(owner: dict[str, Any], owner_path: Path) -> dict[str, Any]:
    binding = owner["physical_binding"]
    source = owner["source"]
    recipe = owner["native_recipe_expected"]
    return {
        "owner_path": str(owner_path.resolve()),
        "owner_sha256": safe_hash(owner_path),
        "canonical_physical_binding_sha256": owner["canonical_physical_binding_sha256"],
        "physical_condition_sha256": owner["physical_condition_sha256"],
        "condition_hash_semantics": owner["condition_hash_semantics"],
        "physical_binding_schema": binding["schema"],
        "physical_binding": binding,
        "source": {
            "source_definition": source["source_definition"],
            "source_definition_sha256": source["source_definition_sha256"],
            "source_plan": source["source_plan"],
            "source_plan_sha256": source["source_plan_sha256"],
            "selected_motion_module": source["selected_motion_module"],
            "selected_motion_module_sha256": source["selected_motion_module_sha256"],
            "native_motion_reader": source["motion_reader"],
            "native_sampled_regular": source["native_sampled_regular"],
        },
        "native_recipe_expected": recipe,
    }


def make_source_control(owner: dict[str, Any], plan: dict[str, Any], case: str) -> dict[str, Any]:
    params = owner["physical_binding"]["parameters"]
    payload = plan["physical_condition_payload"]
    return {
        "case_id": case,
        "amplitude_deg": params["amplitude_deg"],
        "axis": plan["axis"],
        "source_plan_condition_sha256": owner["condition_hash_semantics"]["declared_source_hash"],
        "source_plan_sha256": owner["source"]["source_plan_sha256"],
        "source_definition_sha256": owner["source"]["source_definition_sha256"],
        "selected_motion_module_sha256": owner["source"]["selected_motion_module_sha256"],
        "physical_tuple": {
            "dp_m": payload["dp_m"],
            "time_max_s": payload["time_max_s"],
            "time_out_s": payload["time_out_s"],
            "mother": payload["mother"],
            "pivot_p1_m": payload["pivot_p1_m"],
            "pivot_p2_m": payload["pivot_p2_m"],
            "axis": payload["axis"],
            "amplitude_deg": payload["amplitude_deg"],
        },
        "hash_equality_claim": "none; source plan and canonical physical binding remain distinct",
    }


def build(root: Path) -> None:
    root = root.resolve()
    if root.exists() and any(root.iterdir()):
        raise SystemExit(f"fresh072 destination is non-empty: {root}")
    (root / "metadata").mkdir(parents=True, exist_ok=True)
    for sub in ("bindings", "requests/typed", "requests/xmf", "requests/render", "scripts"):
        (root / sub).mkdir(parents=True, exist_ok=True)

    source_plan_path = F071 / "metadata/first24-plan.json"
    source_plan = load(source_plan_path)
    source_plan_sha = safe_hash(source_plan_path)
    plan_by_case = {x["physical_case_id"]: x for x in source_plan["endpoints"]}
    qa_report = load(QA_REPORT)
    qa_by_case = {x["case_id"]: x for x in qa_report["cases"]}
    if set(qa_by_case) != set(CASES) or not all(x.get("passed") is True for x in qa_by_case.values()):
        raise SystemExit("Root310 aggregate QA is not a complete 16-case pass")
    if qa_report.get("schema") != "ds02.f7.first24.actual-native-initial-qa.v1":
        raise SystemExit("unexpected Root310 QA schema")

    # Copy only non-payload bounded source artifacts. Raw payloads remain outside the package.
    shutil.copy2(Path(__file__), root / "scripts/build_fresh072.py")
    preflight_src = Path("/tmp/preflight_f7_fresh072.py")
    post_src = Path("/tmp/post_typed_f7_fresh072.py")
    if preflight_src.is_file():
        shutil.copy2(preflight_src, root / "scripts/preflight_fresh072.py")
    if post_src.is_file():
        shutil.copy2(post_src, root / "scripts/post_typed_fresh072.py")

    static = {
        "python": INT / "lagrangian-fluid-lab/.venv/bin/python",
        "nvme_wrapper": INT / "lagrangian-fluid-lab/scripts/ds_data02_nvme_convert_v1.py",
        "direct_converter": INT / "lagrangian-fluid-lab/scripts/ds_data02_direct_convert.py",
        "runtime": INT / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py",
        "strict_dispatch": INT / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py",
        "goal": INT / "lagrangian-fluid-lab/campaigns/ds-data-02/GOAL_STAGE1_VISUAL_GPT56LUNA_20261004_ZH.md",
        "queue": INT / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f1_f6_f7_actual_full_native_typed_queue_110/queue.json",
        "queue_launch": INT / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f1_f6_f7_actual_full_native_typed_queue_110/launch.py",
        "export_xmf": INT / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f5_repair_a_short51_actual_typed_bed_pipeline_105/workers/export_xmf.py",
        "renderer": INT / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_native_renderer_proxy_lifetime_diagnostic_023/render.py",
        "root142_launch": INT / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_home_floor_inventory_dispatch_142/launch.py",
        "root142_policy": INT / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_home_floor_inventory_dispatch_142/root_home_floor_inventory_policy.py",
        "root142_check": INT / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_home_floor_inventory_dispatch_142/policy-check.json",
        "root142_contract": INT / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_home_floor_inventory_dispatch_142/source-policy-contract.json",
        "resource_window": INT / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json",
        "decoder": Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump"),
        "partvtk": Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64"),
        "solver_binary": Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64"),
        "paraview": Path("/home/jade/ParaView-6.1.1-MPI-Linux-Python3.12-x86_64/bin/pvpython"),
        "env": Path("/usr/bin/env"),
        "egl_vendor": Path("/usr/share/glvnd/egl_vendor.d/50_mesa.json"),
    }
    for p in static.values():
        must_file(p)

    # Keep a small, bounded metadata record for the source package.
    resource_contract = {
        "schema": "ds02.f7.fresh072.resource-contract.v1",
        "scope_id": SCOPE,
        "model_profile": "gpt-5.6-luna/max",
        "owner": "root",
        "launch_allowed": False,
        "source_only": True,
        "no_ledger_write": True,
        "no_array_decode_in_source_prep": True,
        "no_payload_hash_in_source_prep": True,
        "typed_conversion_policy": {
            "cpu_task_kind": "conversion",
            "cpu_threads": 2,
            "conversion_concurrency_cap": 2,
            "estimated_output_storage_bytes": 34359738368,
            "free_floor_gib": 100,
            "input_native_frames": 601,
            "staging_root": "/tmp/ds02-nvme-conversion",
            "staging_limit_bytes": 25769803776,
            "root142_profile": str(static["root142_policy"].resolve()),
        },
        "root142_profile": {
            "launch": str(static["root142_launch"].resolve()),
            "policy_sha256": safe_hash(static["root142_policy"]),
            "policy_check": str(static["root142_check"].resolve()),
            "source_contract": str(static["root142_contract"].resolve()),
        },
        "xmf_render_policy": {
            "cpu_threads": 2,
            "output_subdirectories": ["xdmf", "render"],
            "fixed_camera_bounds_forbidden": True,
            "native_bounds": "scan valid native positions over every saved XDMF time step",
            "renderer": str(static["renderer"].resolve()),
            "renderer_sha256": safe_hash(static["renderer"]),
        },
        "decoder": {
            "path": str(static["decoder"].resolve()),
            "sha256": safe_hash(static["decoder"]),
            "same_bytes_as_approved_base_lab_decoder": True,
        },
        "renderer": {
            "path": str(static["renderer"].resolve()),
            "sha256": safe_hash(static["renderer"]),
        },
    }
    dump(root / "metadata/resource-contract.json", resource_contract)

    qa_evidence = {
        "schema": "ds02.f7.fresh072.actualQA310-evidence.v1",
        "scope_id": SCOPE,
        "report": str(QA_REPORT.resolve()),
        "report_sha256": safe_hash(QA_REPORT),
        "receipt": str(QA_RECEIPT.resolve()),
        "receipt_sha256": safe_hash(QA_RECEIPT),
        "report_schema": qa_report["schema"],
        "case_count": len(CASES),
        "all_cases_passed": True,
        "arrays_read_by_source": False,
        "raw_payload_policy": "Root310 report is adopted as registered evidence; source package does not read CSV/BI4 bytes.",
    }
    dump(root / "metadata/qa-evidence.json", qa_evidence)

    statuses: list[dict[str, Any]] = []
    case_records: dict[str, dict[str, Any]] = {}
    common_input = [
        static["python"], static["nvme_wrapper"], static["direct_converter"],
        static["runtime"], static["strict_dispatch"], static["goal"], static["queue"],
        static["queue_launch"], static["export_xmf"], static["renderer"],
        static["root142_launch"], static["root142_policy"], static["root142_check"],
        static["root142_contract"], static["resource_window"], static["decoder"],
        static["partvtk"], static["solver_binary"], static["paraview"],
        static["env"], static["egl_vendor"], root / "metadata/resource-contract.json",
        root / "metadata/qa-evidence.json", source_plan_path,
    ]

    for case in CASES:
        owner_path = F071 / "owners" / f"{case}.owner.json"
        owner = load(owner_path)
        plan = plan_by_case[case]
        qa_case = qa_by_case[case]
        gencase_receipt = Path(owner["actual_gencase_evidence"]["receipt"])
        prepared_report = Path(owner["actual_gencase_evidence"]["prepared_input_report"])
        generated_xml = Path(owner["actual_gencase_evidence"]["generated_xml"])
        generated_def = Path(owner["actual_gencase_evidence"]["prepared_input_report"]).parent / f"{case}_Def.xml"
        # The owner contains the authoritative Def path; use it instead of a guessed sibling.
        generated_def = Path(owner["planned_execution"]["prepared_definition"])
        gencase_report = prepared_report
        report_data = load(gencase_report)
        assets = report_data.get("assets", [])
        motion_asset = next((a for a in assets if a.get("relative_name") == "motion_obstacle_quintic.dat"), None)
        if not motion_asset or not motion_asset.get("verified_post_gencase_sha256"):
            raise SystemExit(f"{case}: producer motion SHA missing from prepared-input-report")
        motion_sha = motion_asset["verified_post_gencase_sha256"]

        native_req_path = R313 / f"{case}-native-request.json"
        native_req = load(native_req_path)
        native_attempt = str(native_req["attempt_id"])
        case_dir = DATA / case
        native_attempt_root = case_dir / native_attempt
        native_receipt = native_attempt_root / "execution-receipt.json"
        native_data_root = native_attempt_root / "solver_output/data"
        native_status = "pending"
        native_returncode = None
        native_receipt_sha = None
        if native_receipt.is_file():
            native_receipt_data = load(native_receipt)
            native_returncode = native_receipt_data.get("returncode")
            if native_receipt_data.get("status") == "completed" and native_returncode == 0:
                native_status = "completed"
                native_receipt_sha = safe_hash(native_receipt)
            elif native_receipt_data.get("status") in ("running", "started"):
                native_status = "running"
            else:
                native_status = str(native_receipt_data.get("status") or "pending")
        native_request_sha = safe_hash(native_req_path)

        checks = qa_case["checks"]
        blocks = checks["blocks"]
        counts = {
            "total": int(qa_case["native_particles"]),
            "fixed": int(blocks["fixed"]["count"]),
            "moving": int(blocks["moving"]["count"]),
            "fluid": int(blocks["fluid"]["count"]),
            "floating": 0,
            "dimension": 3,
        }
        if counts != {"total": 70179, "fixed": 27495, "moving": 1984, "fluid": 40700, "floating": 0, "dimension": 3}:
            raise SystemExit(f"{case}: unexpected actual QA counts {counts}")

        owner_compact = compact_owner(owner, owner_path)
        source_control = make_source_control(owner, plan, case)
        gencase_meta = {
            "receipt": str(gencase_receipt.resolve()),
            "receipt_sha256": safe_hash(gencase_receipt),
            "prepared_input_report": str(prepared_report.resolve()),
            "prepared_input_report_sha256": safe_hash(prepared_report),
            "generated_xml": str(generated_xml.resolve()),
            "generated_xml_sha256": safe_hash(generated_xml),
            "generated_definition": str(generated_def.resolve()),
            "generated_definition_sha256": safe_hash(generated_def),
            "generated_bi4": str(Path(owner["actual_gencase_evidence"]["generated_bi4"]).resolve()),
            "generated_bi4_sha256": None,
            "generated_motion": str(Path(owner["planned_execution"]["prepared_motion"]).resolve()),
            "generated_motion_sha256": None,
            "motion_producer_sha256": motion_sha,
            "motion_sha_source": "prepared-input-report.assets[].verified_post_gencase_sha256",
            "status": "completed",
            "returncode": 0,
            "counts": counts,
            "dimension": 3,
        }
        qa_meta = {
            "aggregate_report": str(QA_REPORT.resolve()),
            "aggregate_report_sha256": safe_hash(QA_REPORT),
            "aggregate_receipt": str(QA_RECEIPT.resolve()),
            "aggregate_receipt_sha256": safe_hash(QA_RECEIPT),
            "case_passed": True,
            "case_native_particles": int(qa_case["native_particles"]),
            "report_physical_condition_sha256": qa_case.get("physical_condition_sha256"),
            "report_check_names": sorted(qa_case["checks"]),
            "producer_scope_schema": owner["physical_binding"]["schema"],
        }

        typed_attempt = f"root-stage1-f7-{case.split('_')[-1].lower()}-full601-native-typed-nvme-072"
        xmf_attempt = f"root-stage1-f7-{case.split('_')[-1].lower()}-full601-normal-dynamic-072"
        render_attempt = f"root-stage1-f7-{case.split('_')[-1].lower()}-full601-native023-render-072"
        typed_root = case_dir / typed_attempt
        xmf_root = case_dir / xmf_attempt
        render_root = case_dir / render_attempt
        typed_binding_path = root / "bindings" / f"{case}.full601-typed-binding.json"
        xmf_binding_path = root / "bindings" / f"{case}.full601-xmf-binding.json"
        render_binding_path = root / "bindings" / f"{case}.full601-render-binding.json"
        typed_receipt_path = typed_root / "execution-receipt.json"
        conversion_report_path = typed_root / "conversion-report.json"
        trajectory_path = typed_root / "trajectory.h5"
        manifest_path = xmf_root / "xdmf/manifest.json"
        xdmf_path = xmf_root / "xdmf/case.xmf"

        actual_native = {
            "case_id": case,
            "request": str(native_req_path.resolve()),
            "request_sha256": native_request_sha,
            "attempt_id": native_attempt,
            "attempt_root": str(native_attempt_root.resolve()),
            "solver_output": str((native_attempt_root / "solver_output").resolve()),
            "data_root": str(native_data_root.resolve()),
            "receipt": str(native_receipt.resolve()),
            "receipt_sha256": native_receipt_sha,
            "status": native_status,
            "returncode": native_returncode,
            "raw_payload_policy": "native solver payload remains Root-owned; source package never reads or hashes H5/BI4/CSV",
        }
        statuses.append({
            "case_id": case, "native_status": native_status,
            "native_returncode": native_returncode,
            "native_receipt": str(native_receipt.resolve()),
            "native_receipt_sha256": native_receipt_sha,
            "typed_status": "disabled_pending_root142_conversion",
            "xmf_status": "disabled_pending_actual_typed_conversion",
            "render_status": "disabled_pending_actual_xmf",
        })

        typed_binding = {
            "schema": "ds02.f7.fresh072.full601.typed-binding.v1",
            "scope_id": SCOPE,
            "family_id": "F7",
            "case_id": case,
            "physical_case_id": case,
            "model_profile": "gpt-5.6-luna/max",
            "canonical_owner": owner_compact,
            "source_control": source_control,
            "producer_scope_schema": owner["physical_binding"]["schema"],
            "actual_counts": counts,
            "expected_frames": 601,
            "expected_native_frames": 601,
            "time_window_s": [0.0, 12.0],
            "save_interval_s": 0.02,
            "gencase_actual": gencase_meta,
            "initial_qa_actual": qa_meta,
            "native_actual": actual_native,
            "conversion_contract": {
                "expected_dimension": 3,
                "expected_particles": counts["total"],
                "expected_fixed_particles": counts["fixed"],
                "expected_moving_particles": counts["moving"],
                "expected_fluid_particles": counts["fluid"],
                "expected_floating_particles": counts["floating"],
                "native_type_mk_blocks": {
                    "fixed": {"type": 0, "mk": 10, "count": counts["fixed"]},
                    "moving": {"type": 1, "mk": 12, "count": counts["moving"]},
                    "fluid": {"type": 3, "mk": 2, "count": counts["fluid"]},
                },
                "native_fluid_mass_kg": 325.60001628,
                "continuum_fluid_mass_kg": 320.1984,
                "mass_policy": "native mass remains authoritative; continuum comparison separately reported; no rescale",
                "full_native_window": True,
                "motion_reader": owner["source"]["motion_reader"],
                "native_sampled_regular": owner["source"]["native_sampled_regular"],
                "official_partvtk_validation_required": True,
            },
            "motion_provenance": {
                "path": gencase_meta["generated_motion"],
                "producer_report": gencase_meta["prepared_input_report"],
                "producer_report_sha256": gencase_meta["prepared_input_report_sha256"],
                "producer_attested_sha256": motion_sha,
                "source_read_or_hashed_here": False,
            },
            "typed_outputs": {
                "trajectory_h5": str(trajectory_path.resolve()),
                "trajectory_h5_sha256": None,
                "conversion_report": str(conversion_report_path.resolve()),
                "conversion_report_sha256": None,
                "typed_receipt": str(typed_receipt_path.resolve()),
                "typed_receipt_sha256": None,
                "partvtk_validation_dir": str((typed_root / "partvtk-validation").resolve()),
            },
            "xmf_shape_contract": {
                "source_shape": "(frames, particles, 3) for position/velocity; (frames, particles) for scalar fields",
                "implementation": "outshape = shape[1:]",
                "particle_axis_preserved": True,
                "dynamic_vector_dimensions": f"{counts['total']} 3",
                "dynamic_scalar_dimensions": str(counts["total"]),
            },
            "status": "source_only_disabled_pending_root142_typed_conversion",
            "launch_allowed": False,
            "future_hashes_null": True,
            "source_only": True,
            "arrays_read_by_source": False,
            "jobs_started": False,
            "claim_boundary": "GenCase, Root310 initial native QA, and Root313 full601 native receipt are actual metadata evidence. Typed H5, XMF, rendering, Q-N, precision, and production remain future.",
        }
        dump(typed_binding_path, typed_binding)

        # Safe runtime inputs. The raw native data root, BI4, CSV, H5 and motion DAT are
        # command/future provenance only and are deliberately absent from input_files.
        case_safe = list(common_input) + [
            root / "metadata/qa-evidence.json",
            root / "scripts/preflight_fresh072.py",
            owner_path,
            source_plan_path,
            F071 / "metadata/actual-native-qa-binding.json",
            R313 / "actual-qa-launch-review.json",
            native_req_path,
            gencase_receipt,
            prepared_report,
            generated_xml,
            generated_def,
            Path(owner["source"]["source_definition"]),
            QA_REPORT,
            QA_RECEIPT,
            typed_binding_path,
        ]
        case_safe = list(dict.fromkeys(p.resolve() for p in case_safe))

        typed_cmd = [
            str(static["python"].resolve()),
            str(static["nvme_wrapper"].resolve()),
            "--staging-root", "/tmp/ds02-nvme-conversion",
            "--staging-limit-bytes", "25769803776", "--",
            "--data-root", str(native_data_root.resolve()),
            "--generated-xml", str(generated_xml.resolve()),
            "--output", "{attempt_root}/trajectory.h5",
            "--report", "{attempt_root}/conversion-report.json",
            "--decoder", str(static["decoder"].resolve()),
            "--partvtk", str(static["partvtk"].resolve()),
            "--validation-dir", "{attempt_root}/partvtk-validation",
            "--solver-log", str((native_attempt_root / "solver_output/Run.out").resolve()),
            "--solver-receipt", str(native_receipt.resolve()),
            "--gencase-receipt", str(gencase_receipt.resolve()),
            "--owner-metadata", str(owner_path.resolve()),
            "--particle-chunk", "65536",
        ]
        typed_request = {
            "schema": "ds02.runner-request.v2",
            "scope_id": SCOPE,
            "family_id": "F7",
            "case_id": case,
            "physical_case_id": case,
            "attempt_id": typed_attempt,
            "kind": "cpu",
            "cpu_task_kind": "conversion",
            "cpu_threads": 2,
            "max_wall_seconds": 5400,
            "estimated_storage_bytes": 34359738368,
            "worktree_root": str(INT.resolve()),
            "cwd": str((INT / "lagrangian-fluid-lab").resolve()),
            "command": typed_cmd,
            "launch_owner": "root",
            "launch": False,
            "launch_allowed": False,
            "execution_allowed": False,
            "disabled": True,
            "disabled_reason": "Disabled source template; Root142 must choose the conversion slot and revalidate the actual Root313 native receipt. No source package launch.",
            "source_only": True,
            "future_hashes_null": True,
            "model_profile": "gpt-5.6-luna/max",
            "root_review_required": True,
            "root142_profile": {
                "policy": str(static["root142_policy"].resolve()),
                "policy_sha256": safe_hash(static["root142_policy"]),
                "launch": str(static["root142_launch"].resolve()),
            },
            "nvme_protocol": {
                "conversion_concurrency_cap": 2,
                "cpu_threads": 2,
                "free_floor_gib": 100,
                "estimated_output_storage_bytes": 34359738368,
                "staging_root": "/tmp/ds02-nvme-conversion",
                "staging_limit_bytes": 25769803776,
                "direct_converter": str(static["direct_converter"].resolve()),
                "wrapper": str(static["nvme_wrapper"].resolve()),
            },
            "producer_scope_schema": owner["physical_binding"]["schema"],
            "producer_scope": {
                "schema": owner["physical_binding"]["schema"],
                "actual_counts": counts,
                "expected_frames": 601,
                "source_control_sha256": owner["source"]["selected_motion_module_sha256"],
                "canonical_physical_binding_sha256": owner["canonical_physical_binding_sha256"],
                "source_plan_condition_sha256": owner["condition_hash_semantics"]["declared_source_hash"],
            },
            "expected_frames": 601,
            "expected_native_frames": 601,
            "expected_particles": counts["total"],
            "expected_counts": counts,
            "canonical_owner": owner_compact,
            "source_control": source_control,
            "gencase_actual": gencase_meta,
            "initial_qa_actual": qa_meta,
            "native_dependency": actual_native,
            "input_files": [str(p) for p in case_safe],
            "input_sha256": input_hashes(case_safe),
            "future_outputs": {
                "trajectory_h5": str(trajectory_path.resolve()),
                "trajectory_h5_sha256": None,
                "conversion_report": str(conversion_report_path.resolve()),
                "conversion_report_sha256": None,
                "typed_receipt": str(typed_receipt_path.resolve()),
                "typed_receipt_sha256": None,
                "partvtk_validation_dir": str((typed_root / "partvtk-validation").resolve()),
            },
            "no_array_decode_in_source_prep": True,
            "no_converter_in_source_prep": True,
            "no_jobs_started": True,
            "production_approval": "none",
            "q_n": "not_granted",
            "precision_status": "not_accepted",
            "visual_acceptance": "not_assessed",
            "independent_case_count_increment": 0,
            "claim_boundary": "Typed conversion is a derived evidence step. No Q-N, precision, production, or visual acceptance is granted by this disabled request.",
        }
        dump(root / "requests/typed" / f"{case}.full601-nvme-typed-072.disabled-request.json", typed_request)

        xmf_binding = {
            "schema": "ds02.f7.fresh072.full601.xmf-binding.v1",
            "scope_id": SCOPE,
            "family_id": "F7",
            "case_id": case,
            "physical_case_id": case,
            "model_profile": "gpt-5.6-luna/max",
            "canonical_owner": owner_compact,
            "source_control": source_control,
            "producer_scope_schema": owner["physical_binding"]["schema"],
            "producer_conversion_schema_expected": "ds-data-02.bi4-direct-conversion.v1",
            "actual_counts": counts,
            "expected_frames": 601,
            "expected_particles": counts["total"],
            "physical_window_s": [0.0, 12.0],
            "save_interval_s": 0.02,
            "native_receipt": str(native_receipt.resolve()),
            "native_receipt_sha256": native_receipt_sha,
            "native_status": native_status,
            "typed_receipt": str(typed_receipt_path.resolve()),
            "typed_receipt_sha256": None,
            "conversion_report": str(conversion_report_path.resolve()),
            "conversion_report_sha256": None,
            "trajectory_h5": str(trajectory_path.resolve()),
            "trajectory_h5_sha256": None,
            "xmf_shape_contract": {
                "source_shape": "(frames, particles, 3) for position/velocity; (frames, particles) for scalar fields",
                "implementation": "outshape = shape[1:]",
                "particle_axis_preserved": True,
                "dynamic_vector_dimensions": f"{counts['total']} 3",
                "dynamic_scalar_dimensions": str(counts["total"]),
            },
            "all_native_fields_retained": ["valid", "initial_type", "initial_mk", "type", "mk", "idp", "zone", "position", "velocity", "density", "pressure"],
            "actual_sidecar_output_subdirectory": "xdmf",
            "output_path_contract": "{attempt_root}/xdmf/case.xmf and {attempt_root}/xdmf/manifest.json",
            "future_hashes_null": True,
            "launch_allowed": False,
            "source_only": True,
            "source_h5_read_only": True,
            "claim_boundary": "XMF is a derived temporal view after typed completion; no Q-N, precision, production, or visual acceptance claim.",
        }
        dump(xmf_binding_path, xmf_binding)

        xmf_safe = list(dict.fromkeys(case_safe + [typed_binding_path, xmf_binding_path, root / "requests/typed" / f"{case}.full601-nvme-typed-072.disabled-request.json"]))
        xmf_cmd = [
            str(static["python"].resolve()),
            str(static["export_xmf"].resolve()),
            "--binding", str(xmf_binding_path.resolve()),
            "--output-dir", "{attempt_root}/xdmf",
        ]
        xmf_request = {
            "schema": "ds02.runner-request.v2",
            "scope_id": SCOPE,
            "family_id": "F7",
            "case_id": case,
            "physical_case_id": case,
            "attempt_id": xmf_attempt,
            "kind": "cpu",
            "cpu_task_kind": "audit",
            "cpu_threads": 2,
            "max_wall_seconds": 7200,
            "estimated_storage_bytes": 8589934592,
            "worktree_root": str(INT.resolve()),
            "cwd": str((INT / "lagrangian-fluid-lab").resolve()),
            "command": xmf_cmd,
            "launch_owner": "root",
            "launch": False,
            "launch_allowed": False,
            "execution_allowed": False,
            "disabled": True,
            "disabled_reason": "Disabled until the actual Root142 typed conversion completes/0 and a producer report/H5 SHA is bound by metadata-only postprocessing. Output must be the independent xdmf child directory.",
            "source_only": True,
            "future_hashes_null": True,
            "model_profile": "gpt-5.6-luna/max",
            "root_review_required": True,
            "producer_scope_schema": owner["physical_binding"]["schema"],
            "producer_scope": {"schema": owner["physical_binding"]["schema"], "actual_counts": counts, "expected_frames": 601},
            "expected_frames": 601,
            "expected_native_frames": 601,
            "expected_particles": counts["total"],
            "expected_counts": counts,
            "xmf_shape_contract": xmf_binding["xmf_shape_contract"],
            "actual_sidecar_output_subdirectory": "xdmf",
            "output_directory_contract": "{attempt_root}/xdmf",
            "input_files": [str(p) for p in xmf_safe],
            "input_sha256": input_hashes(xmf_safe),
            "future_outputs": {
                "execution_receipt": "{attempt_root}/execution-receipt.json",
                "execution_receipt_sha256": None,
                "manifest": "{attempt_root}/xdmf/manifest.json",
                "manifest_sha256": None,
                "xdmf": "{attempt_root}/xdmf/case.xmf",
                "xdmf_sha256": None,
            },
            "typed_dependency": {
                "request": str((root / "requests/typed" / f"{case}.full601-nvme-typed-072.disabled-request.json").resolve()),
                "receipt": str(typed_receipt_path.resolve()),
                "receipt_sha256": None,
                "conversion_report": str(conversion_report_path.resolve()),
                "conversion_report_sha256": None,
                "trajectory_h5": str(trajectory_path.resolve()),
                "trajectory_h5_sha256": None,
            },
            "native_dependency": actual_native,
            "canonical_owner": owner_compact,
            "source_control": source_control,
            "claim_boundary": "XMF is only a derived temporal index and does not create visual, Q-N, precision, production, or case-count credit.",
            "independent_case_count_increment": 0,
            "precision_status": "not_accepted",
            "production_approval": "none",
            "q_n": "not_granted",
        }
        dump(root / "requests/xmf" / f"{case}.full601-normal-xmf-072.disabled-request.json", xmf_request)

        render_binding = {
            "schema": "ds02.f7.fresh072.full601.native023-render-binding.v1",
            "scope_id": SCOPE,
            "family_id": "F7",
            "case_id": case,
            "physical_case_id": case,
            "model_profile": "gpt-5.6-luna/max",
            "canonical_owner": owner_compact,
            "source_control": source_control,
            "producer_scope_schema": owner["physical_binding"]["schema"],
            "actual_counts": counts,
            "expected_frames": 601,
            "expected_particles": counts["total"],
            "native_receipt": str(native_receipt.resolve()),
            "native_receipt_sha256": native_receipt_sha,
            "native_status": native_status,
            "typed_receipt": str(typed_receipt_path.resolve()),
            "typed_receipt_sha256": None,
            "conversion_report": str(conversion_report_path.resolve()),
            "conversion_report_sha256": None,
            "trajectory_h5": str(trajectory_path.resolve()),
            "trajectory_h5_sha256": None,
            "xmf_binding": str(xmf_binding_path.resolve()),
            "xmf_binding_sha256": safe_hash(xmf_binding_path),
            "xdmf": str(xdmf_path.resolve()),
            "xdmf_sha256": None,
            "manifest": str(manifest_path.resolve()),
            "manifest_sha256": None,
            "renderer_source": str(static["renderer"].resolve()),
            "renderer_sha256": safe_hash(static["renderer"]),
            "paraview": str(static["paraview"].resolve()),
            "software_offscreen": True,
            "automatic_native_bounds": "scan valid native positions over every saved XDMF time step",
            "fixed_camera_bounds_forbidden": True,
            "source_reader_unclipped": True,
            "all_native_fields_retained": True,
            "identity_axis_preserved": True,
            "frame_selection": "0..last inclusive",
            "expected_contact_pages": 26,
            "diagnostic_frames_forbidden": True,
            "output_path_contract": "{attempt_root}/render",
            "future_hashes_null": True,
            "launch_allowed": False,
            "source_only": True,
            "claim_boundary": "Root023 output is a derived visual audit; it does not grant visual acceptance, Q-N, precision, production, or a new case.",
        }
        dump(render_binding_path, render_binding)

        render_safe = list(dict.fromkeys(xmf_safe + [render_binding_path, xmf_binding_path, root / "requests/xmf" / f"{case}.full601-normal-xmf-072.disabled-request.json"]))
        render_cmd = [
            str(static["env"].resolve()),
            "VTK_SMP_MAX_THREADS=2", "LP_NUM_THREADS=2", "LIBGL_ALWAYS_SOFTWARE=1",
            "MESA_LOADER_DRIVER_OVERRIDE=llvmpipe", "__EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/50_mesa.json",
            "VTK_DEFAULT_OPENGL_WINDOW=vtkEGLRenderWindow", "QT_QPA_PLATFORM=offscreen", "OMP_NUM_THREADS=2",
            str(static["paraview"].resolve()), "--force-offscreen-rendering",
            str(static["renderer"].resolve()), "--manifest", str(manifest_path.resolve()),
            "--output-dir", "{attempt_root}/render",
        ]
        render_request = {
            "schema": "ds02.runner-request.v2",
            "scope_id": SCOPE,
            "family_id": "F7",
            "case_id": case,
            "physical_case_id": case,
            "attempt_id": render_attempt,
            "kind": "cpu",
            "cpu_task_kind": "audit",
            "cpu_threads": 2,
            "max_wall_seconds": 14400,
            "estimated_storage_bytes": 8589934592,
            "worktree_root": str(INT.resolve()),
            "cwd": str((INT / "lagrangian-fluid-lab").resolve()),
            "command": render_cmd,
            "launch_owner": "root",
            "launch": False,
            "launch_allowed": False,
            "execution_allowed": False,
            "disabled": True,
            "disabled_reason": "Disabled until actual Root142 typed conversion and isolated xdmf export complete/0. Renderer must consume the real full601 manifest and write only to the independent render child directory.",
            "source_only": True,
            "future_hashes_null": True,
            "model_profile": "gpt-5.6-luna/max",
            "root_review_required": True,
            "producer_scope_schema": owner["physical_binding"]["schema"],
            "producer_scope": {"schema": owner["physical_binding"]["schema"], "actual_counts": counts, "expected_frames": 601},
            "expected_frames": 601,
            "expected_native_frames": 601,
            "expected_particles": counts["total"],
            "expected_counts": counts,
            "renderer_contract": {
                "renderer_revision": "f2-root-followup-053-stage1-visual-renderer-v2",
                "renderer_sha256": safe_hash(static["renderer"]),
                "renderer_source": str(static["renderer"].resolve()),
                "software_offscreen": True,
                "automatic_native_bounds": "scan valid native positions over every saved XDMF time step",
                "fixed_camera_bounds_forbidden": True,
                "source_reader_unclipped": True,
                "full_saved_frames_required": True,
                "expected_contact_pages": 26,
                "chronological_order": True,
                "actual_time_annotations": True,
                "all_native_fields_retained": True,
            },
            "output_directory_contract": "{attempt_root}/render",
            "actual_sidecar_output_subdirectory": "render",
            "input_files": [str(p) for p in render_safe],
            "input_sha256": input_hashes(render_safe),
            "future_outputs": {
                "execution_receipt": "{attempt_root}/execution-receipt.json",
                "execution_receipt_sha256": None,
                "render_manifest": "{attempt_root}/render/render-manifest.json",
                "render_manifest_sha256": None,
                "contact_pages": "{attempt_root}/render/contact-page-*.png",
            },
            "typed_dependency": {
                "request": str((root / "requests/typed" / f"{case}.full601-nvme-typed-072.disabled-request.json").resolve()),
                "receipt": str(typed_receipt_path.resolve()),
                "receipt_sha256": None,
                "conversion_report": str(conversion_report_path.resolve()),
                "conversion_report_sha256": None,
                "trajectory_h5": str(trajectory_path.resolve()),
                "trajectory_h5_sha256": None,
            },
            "xmf_dependency": {
                "request": str((root / "requests/xmf" / f"{case}.full601-normal-xmf-072.disabled-request.json").resolve()),
                "manifest": str(manifest_path.resolve()),
                "manifest_sha256": None,
                "xdmf": str(xdmf_path.resolve()),
                "xdmf_sha256": None,
            },
            "native_dependency": actual_native,
            "canonical_owner": owner_compact,
            "source_control": source_control,
            "claim_boundary": "Rendering is metadata-only source preparation here and does not grant visual acceptance or Q-N.",
            "independent_case_count_increment": 0,
            "precision_status": "not_accepted",
            "production_approval": "none",
            "q_n": "not_granted",
        }
        dump(root / "requests/render" / f"{case}.full601-native023-render-072.disabled-request.json", render_request)

        case_records[case] = {
            "case_id": case,
            "amplitude_deg": owner["physical_binding"]["parameters"]["amplitude_deg"],
            "canonical_physical_binding_sha256": owner["canonical_physical_binding_sha256"],
            "source_plan_condition_sha256": owner["condition_hash_semantics"]["declared_source_hash"],
            "physical_condition_sha256": owner["physical_condition_sha256"],
            "source_control": source_control,
            "actual_counts": counts,
            "motion_producer_sha256": motion_sha,
            "gencase_receipt_sha256": gencase_meta["receipt_sha256"],
            "prepared_input_report_sha256": gencase_meta["prepared_input_report_sha256"],
            "generated_xml_sha256": gencase_meta["generated_xml_sha256"],
            "native_status": native_status,
            "native_receipt_sha256": native_receipt_sha,
            "qa_case_passed": True,
        }

    manifest = {
        "schema": "ds02.f7.fresh072.manifest.v1",
        "scope_id": SCOPE,
        "family": "F7",
        "model_profile": "gpt-5.6-luna/max",
        "cases": CASES,
        "case_count": len(CASES),
        "native_root313": str(R313.resolve()),
        "native_status_snapshot": statuses,
        "typed_request_count": len(CASES),
        "xmf_request_count": len(CASES),
        "render_request_count": len(CASES),
        "metadata_only": True,
        "arrays_read": False,
        "jobs_started": False,
        "shared_registry_write": False,
        "future_outputs_sha256_null": True,
        "raw_payload_policy": {
            "bi4": "producer/root evidence only; never read or source-hashed here",
            "csv": "Root310 evidence only; never read here",
            "h5": "future converter/renderer input; never read or source-hashed here",
            "motion_dat": "producer verified SHA adopted from prepared-input-report JSON; motion bytes never read here",
        },
        "actual_initial_qa": {
            "report": str(QA_REPORT.resolve()),
            "report_sha256": safe_hash(QA_REPORT),
            "receipt": str(QA_RECEIPT.resolve()),
            "receipt_sha256": safe_hash(QA_RECEIPT),
            "all_cases_passed": True,
        },
        "cases_metadata": case_records,
    }
    dump(root / "metadata/manifest.json", manifest)
    dump(root / "metadata/actual-native-status.json", {"schema": "ds02.f7.fresh072.actual-native-status.v1", "scope_id": SCOPE, "cases": statuses, "arrays_read": False, "jobs_started": False})
    dump(root / "metadata/source-review.json", {
        "schema": "ds02.f7.fresh072.source-review.v1",
        "scope_id": SCOPE,
        "source_plan": str(source_plan_path.resolve()),
        "source_plan_sha256": source_plan_sha,
        "root310_qa": str(QA_REPORT.resolve()),
        "root313_native_handoff": str(R313.resolve()),
        "consumer_scope_schema": "ds-data-02.physical-binding.v1",
        "expected_native_counts": {"total": 70179, "fixed": 27495, "moving": 1984, "fluid": 40700, "floating": 0, "dimension": 3},
        "mass_semantics": "native fluid mass 325.60001628 kg and continuum envelope 320.1984 kg retained separately; no rescale",
        "motion_semantics": "motion SHA is adopted from GenCase prepared-input-report assets; motion payload not read here",
        "xmf_shape_semantics": "vectors use shape[1:] and therefore N 3; scalars use N; all 601 frames",
        "claim_boundary": "No Q-N, precision, visual acceptance, production credit, or new case count is granted.",
    })
    print(json.dumps({"package_root": str(root), "cases": len(CASES), "native_status_counts": {s: sum(x["native_status"] == s for x in statuses) for s in sorted({x["native_status"] for x in statuses})}}, indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    build(ap.parse_args().root)
