#!/usr/bin/env python3
"""Build the source-only F2 Stage1 offset endpoint package.

The builder imports the existing F2 batch generator only to materialize XML and
native motion source.  It never invokes GenCase, PartVTK, DualSPHysics, a
runner, or an array reader.  All requests emitted here are disabled until Root
reviews and enables fresh actual executions.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, Mapping

INFRA = Path("/home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics")
HERE = INFRA / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/handoff_20261003/root_followup_089_f2_stage1_production_endpoints_v1"
SOURCE_DIR = HERE / "source"
REQUEST_DIR = HERE / "requests"
OWNER_DIR = HERE / "owners"
EVIDENCE_DIR = HERE / "evidence"
WORKER = HERE / "workers/f2_stage1_endpoint_worker.py"
QA_WORKER = HERE / "workers/f2_stage1_initial_qa_worker.py"
BATCH_SOURCE = INFRA / "../../ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_f2.py"
BATCH_STAGE8 = INFRA / "../../ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_f2_stage8_production.py"
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
INTEGRATION_LAB = INTEGRATION / "lagrangian-fluid-lab"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2")
GENCASE = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64")
PARTVTK = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64")
SOLVER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64")
ROOT_VISUAL = INTEGRATION_LAB / "campaigns/ds-data-02/handoff_20261003/root_stage1_f2_full401_visual_acceptance_061/root-visual-decision.json"
ROOT_AUDIT_REQUEST = INTEGRATION_LAB / "campaigns/ds-data-02/handoff_20261003/root_stage1_f2_actual_initial_support_and_first51_states_051/request.json"
MOTHER_AUDIT = DATA_ROOT / "F2_RV4EQ_MATCHED_OFFSET_V1_COARSE_DP010_SPATIAL_REFERENCE_SAVE010/root-stage1-f2-initial-wall-and-first51-native-states-audit-051/frame0-wall-frames50-audit.json"
MOTHER_AUDIT_RECEIPT = MOTHER_AUDIT.parent / "execution-receipt.json"
MOTHER_TYPED_RECEIPT = DATA_ROOT / "F2_RV4EQ_MATCHED_OFFSET_V1_COARSE_DP010_SPATIAL_REFERENCE_SAVE010/root-offset-coarse-matched-spatial-fulltyped-nvme-003/execution-receipt.json"
MOTHER_CONVERSION = MOTHER_TYPED_RECEIPT.parent / "conversion-report.json"
MOTHER_NATIVE_RECEIPT = DATA_ROOT / "F2_RV4EQ_MATCHED_OFFSET_V1_COARSE_DP010_SPATIAL_REFERENCE_SAVE010/qualification-f2_rv4eq_matched_offset_v1_coarse_dp010-spatial-reference-save010-root-review-001/execution-receipt.json"
MOTHER_GENCASE_RECEIPT = DATA_ROOT / "F2_RV4EQ_MATCHED_OFFSET_V1_COARSE_DP010/gencase-f2_rv4eq_matched_offset_v1_coarse_dp010-20261003-001/execution-receipt.json"
MOTHER_OWNER = INTEGRATION_LAB / "campaigns/ds-data-02/families/F2/handoff_20261003/rv4_matched_three_dp_init_v1/root_fulltyped_macro_review_002/offset-coarse-owner.json"
GOAL = INTEGRATION_LAB / "campaigns/ds-data-02/GOAL_STAGE1_VISUAL_GPT56LUNA_20261004_ZH.md"

SCOPE_ID = "F2_STAGE1_OFFSET_FIRST_TWO_NATIVE_V1"
MOTHER_CASE_ID = "F2_RV4EQ_MATCHED_OFFSET_V1_COARSE_DP010_SPATIAL_REFERENCE_SAVE010"
MOTHER_PHYSICAL_HASH = "327899e38bbad63951206d5b2fd3ef354c049a32f6671af1af7913a48b77c7ef"
MOTHER_TRAJECTORY_SHA = "4e1611b03650b2db1964a0f8dcac9c55d84da9d0a3da3b3df71e95da2165618c"
MOTHER_TYPED_RECEIPT_SHA = "06f8232ae0fdcc2df2335f612cba17ce3e25dc2573d0562703fbc5cbd4284fc2"
MOTHER_AUDIT_SHA = "240c6c751261108e476d302cebfe441820dc4d48454e197073ddc4bdfc53012a"
MOTHER_AUDIT_RECEIPT_SHA = "ca5e45f2d69a52bbc847d96213fe3d9675f2045a9b33fb29fbe8b4c858c79842"
MOTHER_GENCASE_RECEIPT_SHA = "7b948163ef985a35f3c52ad85fd07b2102827ae0476b8e1650e397b60af5f57f"
MOTHER_NATIVE_RECEIPT_SHA = "e514dda08dc620b4ccf4fb5a4f253634e60f3c90bab26c7bb9f446cbbb2645c8"

CASES = (
    {
        "case_id": "F2_STAGE1_OFFSET_P01_DP010_SPATIAL_REFERENCE_SAVE010",
        "source_batch_case_id": "F2_OFFSET_P01",
        "physical_case_id": "F2_STAGE1_OFFSET_P01_OPEN_RIM_RX045_RY014_FILL080",
        "receiver_x_m": 0.45,
        "receiver_y_m": 0.14,
        "fill_ratio": 0.8,
        "rotation_duration_s": 0.65,
        "pair_id": "F2_STAGE1_OFFSET_PAIR_P01",
    },
    {
        "case_id": "F2_STAGE1_OFFSET_P03_DP010_SPATIAL_REFERENCE_SAVE010",
        "source_batch_case_id": "F2_OFFSET_P03",
        "physical_case_id": "F2_STAGE1_OFFSET_P03_OPEN_RIM_RX065_RY014_FILL080",
        "receiver_x_m": 0.65,
        "receiver_y_m": 0.14,
        "fill_ratio": 0.8,
        "rotation_duration_s": 0.65,
        "pair_id": "F2_STAGE1_OFFSET_PAIR_P03",
    },
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value: Mapping[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def binding(path: Path, *, required: bool = True) -> dict[str, Any]:
    path = Path(path).resolve()
    if required and not path.is_file():
        raise FileNotFoundError(path)
    if not path.is_file():
        return {"path": str(path), "sha256": None, "exists": False}
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size, "exists": True}


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_batch_source() -> Any:
    if not BATCH_SOURCE.is_file():
        raise FileNotFoundError(f"existing F2 batch generator missing: {BATCH_SOURCE}")
    spec = importlib.util.spec_from_file_location("ds02_f2_batch_source", BATCH_SOURCE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {BATCH_SOURCE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def physical_condition(case: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "family_id": "F2",
        "mechanism_id": "offset_spill",
        "geometry_family_id": "F2_GEOM_CUP_RECEIVER_OFFSET_V1",
        "control_family_id": "F2_CTRL_SMOOTH_ROTATE_Y_V1",
        "cup_low_m": [0.0, -0.15, 0.65],
        "cup_size_m": [0.425, 0.30, 0.45],
        "receiver_low_m": [case["receiver_x_m"], case["receiver_y_m"] - 0.30, 0.0],
        "receiver_size_m": [1.10, 0.60, 0.45],
        "tray_low_m": [-1.20, -1.00, -0.20],
        "tray_size_m": [4.00, 2.00, 0.15],
        "fluid_low_m": [0.05, -0.11, 0.70],
        "fluid_source_size_m": [0.325, 0.22, 0.33 * case["fill_ratio"]],
        "source_layer_count": 3,
        "source_mk_values": [0, 1, 2],
        "initial_velocity_m_per_s": [0.0, 0.0, 0.0],
        "fill_ratio": case["fill_ratio"],
        "receiver_x_m": case["receiver_x_m"],
        "receiver_y_m": case["receiver_y_m"],
        "mouth_geometry": "open_rim",
        "rotation_duration_s": case["rotation_duration_s"],
        "rotation_hold_start_s": 0.5,
        "rotation_final_angle_deg": -105.0,
        "motion_file_sha256": "ff966330e01e565987ebf182a7dfd7401d76577ae1c266894fc7db4aa34c5b70",
        "native_forcing": "official mvrotfile; static 0.5 s, cosine ramp, final -105 degrees, post-stop hold",
    }


def numerical_recipe(case: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "dp_m": 0.01,
        "time_max_s": 4.0,
        "time_out_s": 0.01,
        "expected_saved_frames": 401,
        "solver_dimension": 3,
        "native_forcing_file_format": "#Time;Degrees",
        "recipe_role": "Stage1 visual production candidate; no precision/Q-N claim",
    }


def support_bindings() -> dict[str, Any]:
    return {
        "accepted_mother_visual_decision": binding(ROOT_VISUAL),
        "mother_initial_audit_request": binding(ROOT_AUDIT_REQUEST),
        "mother_initial_audit": binding(MOTHER_AUDIT),
        "mother_initial_audit_receipt": binding(MOTHER_AUDIT_RECEIPT),
        "mother_typed_receipt": binding(MOTHER_TYPED_RECEIPT),
        "mother_conversion_report": binding(MOTHER_CONVERSION),
        "mother_native_solver_receipt": binding(MOTHER_NATIVE_RECEIPT),
        "mother_gencase_receipt": binding(MOTHER_GENCASE_RECEIPT),
        "mother_owner_metadata": binding(MOTHER_OWNER),
        "goal": binding(GOAL),
        "mother_declared_values": {
            "case_id": MOTHER_CASE_ID,
            "physical_condition_sha256": MOTHER_PHYSICAL_HASH,
            "trajectory_sha256": MOTHER_TRAJECTORY_SHA,
            "frames": 401,
            "physical_window_s": [0.0, 4.0],
            "native_fluid_particles": 24576,
            "root_visual_status": "visual-approved-by-root; numerical precision unaccepted",
            "support_role": "read-only provenance; no mother rerun and no alias count",
        },
    }


def source_provenance() -> dict[str, Any]:
    return {
        "existing_f2_batch_generator": binding(BATCH_SOURCE),
        "existing_f2_batch_production_builder": binding(BATCH_STAGE8),
        "existing_batch_endpoint_p01_definition": binding(INTEGRATION_LAB / "campaigns/ds-data-02/families/F2/production/definitions/F2_OFFSET_P01_Def.xml"),
        "existing_batch_endpoint_p03_definition": binding(INTEGRATION_LAB / "campaigns/ds-data-02/families/F2/production/definitions/F2_OFFSET_P03_Def.xml"),
        "existing_batch_endpoint_p01_motion": binding(INTEGRATION_LAB / "campaigns/ds-data-02/families/F2/production/definitions/F2_OFFSET_P01_motion.dat"),
        "existing_batch_endpoint_p03_motion": binding(INTEGRATION_LAB / "campaigns/ds-data-02/families/F2/production/definitions/F2_OFFSET_P03_motion.dat"),
        "reuse_contract": {
            "reuse": "F2 batch offset_spill source generator and native mvrotfile forcing",
            "new_source_changes": ["case identity", "receiver_x endpoint parameter", "dp=.01", "TimeOut=.01", "source-only request bindings"],
            "unchanged_controls": ["gravity", "DBC Boundary/SlipMode", "StepAlgorithm", "Kernel", "Visco", "DensityDT", "rotation angle", "rotation timing", "TimeMax=4"],
            "no_mother_reuse": "accepted mother is support only; these two IDs are independent prospective physical conditions",
        },
    }


def materialize_cases(module: Any) -> list[dict[str, Any]]:
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for spec in CASES:
        case = module.make_case(
            "offset_spill",
            "medium",
            case_id=spec["case_id"],
            physical_case_id=spec["physical_case_id"],
            paired_background_id=spec["pair_id"],
            values={
                "fill_ratio": spec["fill_ratio"],
                "receiver_x_m": spec["receiver_x_m"],
                "receiver_y_m": spec["receiver_y_m"],
                "rotation_duration_s": spec["rotation_duration_s"],
                "mouth_geometry": "open_rim",
            },
            strict_source=True,
        )
        case["resolution"] = "coarse_dp010"
        case["dp_m"] = 0.01
        case["motion_filename"] = f"{spec['case_id']}_motion.dat"
        case["lineage_group_id"] = "F2_STAGE1_OFFSET_OPEN_RIM_MINIMAL_VARIATION_V1"
        case["generation_status"] = "source_fixture_only_not_gencase_run"
        case["production_status"] = "prospective_pending_root_actual_lifecycle"
        result = module.write_case(case, SOURCE_DIR)
        definition = Path(result["definition_path"]).resolve()
        motion = Path(result["motion_path"]).resolve()
        metadata_path = SOURCE_DIR / f"{spec['case_id']}.metadata.json"
        physical = physical_condition(spec)
        numerical = numerical_recipe(spec)
        metadata = dict(result)
        metadata.update(
            {
                "case_id": spec["case_id"],
                "physical_case_id": spec["physical_case_id"],
                "source_batch_case_id": spec["source_batch_case_id"],
                "definition_path": str(definition),
                "motion_path": str(motion),
                "metadata_path": str(metadata_path.resolve()),
                "dp_m": 0.01,
                "time_max_s": 4.0,
                "time_out_s": 0.01,
                "expected_saved_frames": 401,
                "physical_condition": physical,
                "physical_condition_sha256": canonical_sha(physical),
                "numerical_recipe": numerical,
                "numerical_recipe_sha256": canonical_sha(numerical),
                "native_mass_policy": "Root actual GenCase/BI4/XML/QA only; no source-side particle or mass count",
                "source_only": True,
                "production_claim": "none",
                "qualification_claim": "none",
                "mother_support_only": True,
                "independent_case_count_increment": 1,
            }
        )
        metadata.pop("metadata_sha256", None)
        dump(metadata_path, metadata)
        metadata["metadata_sha256"] = sha256(metadata_path)
        dump(metadata_path, metadata)
        rows.append(metadata)
    return rows


def request_inputs(row: Mapping[str, Any]) -> tuple[list[str], dict[str, str]]:
    paths = [
        BATCH_SOURCE,
        BATCH_STAGE8,
        HERE / "build_f2_stage1_endpoints.py",
        WORKER,
        QA_WORKER,
        Path(str(row["definition_path"])),
        Path(str(row["motion_path"])),
        Path(str(row["metadata_path"])),
        ROOT_VISUAL,
        ROOT_AUDIT_REQUEST,
        MOTHER_AUDIT,
        MOTHER_AUDIT_RECEIPT,
        MOTHER_TYPED_RECEIPT,
        MOTHER_CONVERSION,
        MOTHER_NATIVE_RECEIPT,
        MOTHER_GENCASE_RECEIPT,
        MOTHER_OWNER,
        GOAL,
    ]
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        path = Path(path).resolve()
        if path in seen:
            continue
        if not path.is_file():
            raise FileNotFoundError(path)
        seen.add(path)
        unique.append(path)
    return [str(path) for path in unique], {str(path): sha256(path) for path in unique}


def make_requests(row: Mapping[str, Any]) -> dict[str, Any]:
    case_id = str(row["case_id"])
    definition = Path(str(row["definition_path"])).resolve()
    motion = Path(str(row["motion_path"])).resolve()
    metadata = Path(str(row["metadata_path"])).resolve()
    files, hashes = request_inputs(row)
    raw_root = DATA_ROOT / case_id
    gencase_attempt = f"root-stage1-f2-{case_id.lower()}-gencase"
    qa_attempt = f"root-stage1-f2-{case_id.lower()}-actual-initial-qa"
    solver_attempt = f"root-stage1-f2-{case_id.lower()}-full401-native"
    common = {
        "family_id": "F2",
        "case_id": case_id,
        "physical_case_id": row["physical_case_id"],
        "physical_condition_sha256": row["physical_condition_sha256"],
        "numerical_recipe_sha256": row["numerical_recipe_sha256"],
        "worktree_root": str(INFRA),
        "raw_output_root": str(raw_root),
        "source_only": True,
        "launch_allowed": False,
        "execution_allowed": False,
        "root_review_required": True,
        "production_claim": "none",
        "qualification_claim": "none",
        "input_files": files,
        "input_sha256": hashes,
    }
    gencase = {
        **common,
        "schema": "ds02.runner-request.v2",
        "attempt_id": gencase_attempt,
        "kind": "cpu",
        "cpu_task_kind": "gencase",
        "cpu_threads": 4,
        "max_wall_seconds": 600,
        "estimated_storage_bytes": 512 * 1024 * 1024,
        "command": [str(GENCASE), str(definition.with_suffix("")), "{attempt_root}/" + case_id, "-save:all", "-threads:4"],
        "cwd": str(definition.parent),
        "raw_output_policy": "all GenCase output stays under external DS-DATA-02 raw root; no output is written by this package",
        "expected_checks": {
            "dimension": 3,
            "dp_m": 0.01,
            "time_max_s": 4.0,
            "time_out_s": 0.01,
            "expected_frames_if_solver_runs": 401,
            "positive_fluid_required": True,
            "counts": "read from actual GenCase receipt; no fabricated expected particle count",
        },
        "disabled_reason": "Root must review source hashes and enable a fresh bounded GenCase request; this handoff did not run it",
    }
    qa = {
        **common,
        "schema": "ds02.runner-request.v2",
        "attempt_id": qa_attempt,
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 2,
        "max_wall_seconds": 1800,
        "estimated_storage_bytes": 256 * 1024 * 1024,
        "command": [
            str(INTEGRATION_LAB / ".venv/bin/python"),
            str(QA_WORKER),
            "--case-id", case_id,
            "--definition", str(definition),
            "--gencase-receipt", "{gencase_attempt_root}/execution-receipt.json",
            "--partvtk", str(PARTVTK),
            "--partvtk-output-dir", "{attempt_root}/partvtk",
            "--output", "{attempt_root}/actual-initial-qa.json",
        ],
        "cwd": str(INFRA / "lagrangian-fluid-lab"),
        "depends_on_attempt": gencase_attempt,
        "bounded_output": "JSON summary only; PartVTK CSV remains external raw attempt evidence",
        "required_checks": ["actual GenCase receipt success", "actual 3D XML contract", "finite initial fields", "positive Type3 fluid", "native IDs unique in QA rows"],
        "disabled_reason": "QA runs only after Root enables the matching actual GenCase receipt; no QA/CSV was created in this source handoff",
    }
    solver = {
        **common,
        "schema": "ds02.runner-request.v2",
        "attempt_id": solver_attempt,
        "kind": "qualification",
        "cpu_task_kind": "solver",
        "cpu_threads": 2,
        "target_gpu_index": None,
        "max_wall_seconds": 3600,
        "estimated_peak_gpu_mib": 8192,
        "estimated_storage_bytes": 8 * 1024**3,
        "command": [str(SOLVER), "{gencase_prefix}", "{attempt_root}/solver_output", "-tmax:4.0", "-tout:0.01"],
        "cwd": "{gencase_output_root}",
        "gencase_receipt": "{gencase_attempt_root}/execution-receipt.json",
        "solver_options_policy": "native command only; no added forcing/no-slip flag; XML mvrotfile is authoritative",
        "expected_output": {"full_window_s": 4.0, "save_interval_s": 0.01, "frame_count": 401, "solver_dimension": 3},
        "solver_launch_forbidden": True,
        "disabled_reason": "Source-only endpoint declaration; Root must separately reserve resources and enable after actual GenCase+QA pass",
    }
    lifecycle = {
        **common,
        "schema": "ds02.runner-request.v2",
        "attempt_id": f"root-stage1-f2-{case_id.lower()}-lifecycle-audit",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 1,
        "max_wall_seconds": 300,
        "estimated_storage_bytes": 16 * 1024 * 1024,
        "command": [
            str(INTEGRATION_LAB / ".venv/bin/python"),
            str(WORKER),
            "--case-id", case_id,
            "--metadata", str(metadata),
            "--gencase-receipt", "{gencase_attempt_root}/execution-receipt.json",
            "--qa-report", "{qa_attempt_root}/actual-initial-qa.json",
            "--solver-receipt", "{solver_attempt_root}/execution-receipt.json",
            "--output", "{attempt_root}/lifecycle-audit.json",
        ],
        "cwd": str(INFRA / "lagrangian-fluid-lab"),
        "depends_on_attempts": [gencase_attempt, qa_attempt, solver_attempt],
        "bounded_output": "receipt identity summary only; worker never launches and never reads particle arrays",
        "disabled_reason": "Enable only after Root records fresh terminal GenCase, actual initial QA, and full native solver receipts",
    }
    return {"gencase": gencase, "actual_qa": qa, "solver": solver, "lifecycle_audit": lifecycle}


def write_package() -> None:
    for directory in (SOURCE_DIR, REQUEST_DIR, OWNER_DIR, EVIDENCE_DIR):
        directory.mkdir(parents=True, exist_ok=True)
    module = load_batch_source()
    rows = materialize_cases(module)
    source = source_provenance()
    support = support_bindings()
    dump(EVIDENCE_DIR / "source-provenance.json", source)
    dump(EVIDENCE_DIR / "mother-support-bindings.json", support)
    case_manifest: list[dict[str, Any]] = []
    for row in rows:
        requests = make_requests(row)
        case_id = str(row["case_id"])
        for kind, document in requests.items():
            dump(REQUEST_DIR / f"{case_id}-{kind}-disabled.json", document)
        owner = {
            "schema": "ds02.f2.stage1.prospective-owner.v1",
            "family_id": "F2",
            "scope_id": SCOPE_ID,
            "case_id": case_id,
            "source_batch_case_id": row["source_batch_case_id"],
            "physical_case_id": row["physical_case_id"],
            "physical_condition_sha256": row["physical_condition_sha256"],
            "numerical_recipe_sha256": row["numerical_recipe_sha256"],
            "role": "prospective_independent_physical_endpoint",
            "mother_case_id": MOTHER_CASE_ID,
            "mother_support_only": True,
            "canonical_identity": {
                "condition_id": f"{row['physical_case_id']}::{row['physical_condition_sha256']}",
                "recipe_id": f"{case_id}::{row['numerical_recipe_sha256']}",
                "alias_counting": "one only after actual complete native lifecycle; source fixtures and views count zero",
            },
            "source": {
                "definition": binding(Path(str(row["definition_path"]))),
                "motion": binding(Path(str(row["motion_path"]))),
                "metadata": binding(Path(str(row["metadata_path"]))),
                "batch_generator": source["existing_f2_batch_generator"],
                "batch_source_case": row["source_batch_case_id"],
            },
            "recipe": row["numerical_recipe"],
            "actual_evidence": {
                "gencase": "pending_root_actual_execution",
                "initial_qa": "pending_root_actual_execution",
                "solver": "pending_root_actual_execution",
                "visual_acceptance": "none_for_new_endpoint",
            },
            "mass_policy": "No native mass/count is asserted here. Root reads actual GenCase/BI4/XML/QA outputs.",
            "production_approval": "none",
            "qualification": "none",
            "execution_allowed": False,
            "independent_case_count_increment": 1,
        }
        dump(OWNER_DIR / f"{case_id}.owner.json", owner)
        case_manifest.append(
            {
                "case_id": case_id,
                "source_batch_case_id": row["source_batch_case_id"],
                "physical_case_id": row["physical_case_id"],
                "physical_condition_sha256": row["physical_condition_sha256"],
                "numerical_recipe_sha256": row["numerical_recipe_sha256"],
                "definition": binding(Path(str(row["definition_path"]))),
                "motion": binding(Path(str(row["motion_path"]))),
                "metadata": binding(Path(str(row["metadata_path"]))),
                "requests": {
                    "gencase": str((REQUEST_DIR / f"{case_id}-gencase-disabled.json").resolve()),
                    "actual_qa": str((REQUEST_DIR / f"{case_id}-actual_qa-disabled.json").resolve()),
                    "solver": str((REQUEST_DIR / f"{case_id}-solver-disabled.json").resolve()),
                    "lifecycle_audit": str((REQUEST_DIR / f"{case_id}-lifecycle_audit-disabled.json").resolve()),
                },
                "owner": str((OWNER_DIR / f"{case_id}.owner.json").resolve()),
                "source_fixture_only": True,
            }
        )
    manifest = {
        "schema": "ds02.f2.stage1.source-only-endpoint-manifest.v1",
        "family_id": "F2",
        "scope_id": SCOPE_ID,
        "status": "source_fixture_only_pending_root_review",
        "source_only": True,
        "execution_allowed": False,
        "production_approval": "none",
        "qualification": "none",
        "mother_support": support,
        "source_provenance": source,
        "recipe_contract": {
            "dp_m": 0.01,
            "time_max_s": 4.0,
            "time_out_s": 0.01,
            "expected_saved_frames": 401,
            "native_forcing": "official mvrotfile motion bytes; static hold + cosine ramp to -105 degrees + post-stop hold",
            "solver_command": "DualSPHysics5.4_linux64 {gencase_prefix} {attempt_root}/solver_output -tmax:4.0 -tout:0.01",
        },
        "cases": case_manifest,
        "counting_policy": "The accepted mother is not repeated; neither prospective endpoint counts until Root records fresh actual GenCase, QA, full native solver, and visual review.",
        "disabled_requests": True,
        "no_numeric_execution_in_build": True,
    }
    dump(HERE / "F2_STAGE1_OFFSET_ENDPOINT_MANIFEST.json", manifest)


if __name__ == "__main__":
    write_package()
