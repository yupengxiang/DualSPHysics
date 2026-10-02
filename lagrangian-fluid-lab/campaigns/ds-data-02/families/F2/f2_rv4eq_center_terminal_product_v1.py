#!/usr/bin/env python3
"""Bind the completed CENTER baseline conversion to an additive label handoff.

This producer reads only terminal, immutable CENTER baseline bytes.  It checks
the converter report and HDF5 schema without loading the 6 GB state arrays,
binds the existing native typed-identity correction (mk=1/2/3), and writes a
root-dispatch-only CPU request.  The request fits rigid-body pose from actual
saved Type=1 moving nodes before applying the v6 finite-cup/receiver/tray
operator.  It never starts a solver, GenCase, conversion, or labels task.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
import re
from typing import Any
import xml.etree.ElementTree as ET


FAMILY_ROOT = Path(__file__).resolve().parent
WORKTREE_ROOT = FAMILY_ROOT.parents[4]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
F2_DATA = DATA_ROOT / "families/F2"
CASE_ID = "F2_RV4EQ_DP005_CENTER_V1_BASELINE_SAVE001"
PHYSICAL_CASE_ID = "F2_RV4EQ_DP005_CENTER_V1"
PHYSICAL_HASH = "45c579bd9fa7a4878fcd25d0e0aa6dedf6da8c4cd77cd85e0d05b928ab8b6a43"
CONVERSION_ATTEMPT = F2_DATA / CASE_ID / (
    "conversion-f2_rv4eq_dp005_center_v1_baseline_save001-fullstate-root-reviewed-004"
)
TRAJECTORY = CONVERSION_ATTEMPT / "trajectory.h5"
CONVERSION_REPORT = CONVERSION_ATTEMPT / "conversion-report.json"
CONVERSION_RECEIPT = CONVERSION_ATTEMPT / "execution-receipt.json"
NATIVE_ROOT = F2_DATA / CASE_ID / (
    "qualification-f2_rv4eq_dp005_center_v1-baseline-save001-native-fullstate-v1"
)
SOLVER_OUTPUT = NATIVE_ROOT / "solver_output"
DATA_DIR = SOLVER_OUTPUT / "data"
INPUT_ROOT = F2_DATA / "F2_RV4EQ_DP005_NATIVE_INPUTS_20261002" / CASE_ID
XML = INPUT_ROOT / f"{CASE_ID}.xml"
BI4 = INPUT_ROOT / f"{CASE_ID}.bi4"
MOTION = INPUT_ROOT / f"{CASE_ID}_motion.dat"
GENCASE_RECEIPT = F2_DATA / "F2_RV4EQ_DP005_CENTER_V1" / (
    "gencase-f2_rv4eq_dp005_center_v1-20261002-001/execution-receipt.json"
)
RUN_RECEIPT = NATIVE_ROOT / "execution-receipt.json"
RUN_OUT = SOLVER_OUTPUT / "Run.out"
RUN_CSV = SOLVER_OUTPUT / "Run.csv"
RUNPARTS = SOLVER_OUTPUT / "RunPARTs.csv"
PARTINFO = DATA_DIR / "PartInfo.ibi4"
PART_MOTION_REF = DATA_DIR / "PartMotionRef.ibi4"
PARTOUT = DATA_DIR / "PartOut_000.obi4"
PART_FIRST = DATA_DIR / "Part_0000.bi4"
PART_MIDDLE = DATA_DIR / "Part_0200.bi4"
PART_LAST = DATA_DIR / "Part_0400.bi4"

RAW_NATIVE_REPORT = F2_DATA / (
    "F2_RV4EQ_NATIVE_PARTVTKOUT_DIAGNOSTIC_20261003_V2/"
    "rv4-native-partvtkout-baseline-002/rv4-native-partvtkout-diagnostic.json"
)
CORRECTED_NATIVE_REPORT = F2_DATA / (
    "F2_RV4EQ_NATIVE_PARTVTKOUT_DIAGNOSTIC_20261003_V2/"
    "rv4-native-partvtkout-baseline-002/rv4-native-typed-identity-correction.json"
)
CORRECTED_RECORDS = F2_DATA / (
    "F2_RV4EQ_NATIVE_PARTVTKOUT_DIAGNOSTIC_20261003_V2/"
    "rv4-native-partvtkout-baseline-002/corrected_records/"
    f"{CASE_ID}.jsonl"
)
EXCLUSION_CSV = F2_DATA / (
    "F2_RV4EQ_NATIVE_PARTVTKOUT_DIAGNOSTIC_20261003_V2/"
    "rv4-native-partvtkout-baseline-002/artifacts/artifacts/partvtkout/"
    f"{CASE_ID}/excluded_particles.csv"
)
CORRECTION_SCRIPT = FAMILY_ROOT / "f2_rv4eq_native_typed_identity_correction_v1.py"
OLD_DEFERRED_OWNER = FAMILY_ROOT / (
    "handoff_20261003/rv4_fullstate_postprocess_v1/owner_metadata/"
    f"{CASE_ID}.owner.v1-deferred.json"
)
LABEL_IMPL = FAMILY_ROOT / "f2_handoff_20261002_v6_labels.py"
EVENT_OPERATOR = FAMILY_ROOT / "f2_handoff_20261002_event_semantics_v6.py"
EVENT_MANIFEST = FAMILY_ROOT / "handoff_20261002/event_semantics_v6/operator_manifest.json"
POSE_HELPER = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/scripts/ds_data02_convert.py"
)
CONVERTER = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/scripts/ds_data02_direct_convert.py"
)
RUNTIME = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
)
STRICT_DISPATCH = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py"
)
PYTHON = WORKTREE_ROOT / "lagrangian-fluid-lab/.venv/bin/python"
QUALITY = FAMILY_ROOT / "quality_contract.json"
EVENTS = FAMILY_ROOT / "event_definitions.json"
SAVE_PLAN = FAMILY_ROOT / "integration_save_plan.json"
CASE_REGISTRY = FAMILY_ROOT / "case_registry.jsonl"
REFERENCE_MATRIX = FAMILY_ROOT / "definitions/reference_matrix.json"
GOAL = FAMILY_ROOT.parents[1] / "GOAL_ZH.md"
OUTPUT_ROOT = FAMILY_ROOT / "handoff_20261003/center_baseline_terminal_v1"
OWNER_PATH = OUTPUT_ROOT / "owner_metadata" / f"{CASE_ID}.owner.v2-terminal-bound.json"
IDENTITY_PATH = OUTPUT_ROOT / "typed_identity" / f"{CASE_ID}.identity-correction-sidecar.v1.json"
LABEL_REQUEST_PATH = OUTPUT_ROOT / "labels_requests" / f"{CASE_ID}_labels_request_v2_terminal_ready.json"
MANIFEST_PATH = OUTPUT_ROOT / "center_baseline_terminal_manifest_v1.json"
SCHEMA = "ds-data-02.f2.rv4eq-center-baseline-terminal-product.v1"
EXPECTED_FRAMES = 401
EXPECTED_PARTICLES = 1_668_869
EXPECTED_FLUID = 196_608
CONTINUOUS_MASS_KG = Decimal("24.576")
EVENT_TIME_BUDGET_S = 0.0036681953999691376
SAVE_HALF_WIDTH_BUDGET_S = 0.0007336390799938275


def require(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} missing: {path}")
    return path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with require(path, "hash input").open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def binding(path: Path, role: str, *, known_sha256: str | None = None) -> dict[str, Any]:
    path = require(path, role)
    return {
        "path": str(path),
        "sha256": known_sha256 or sha256(path),
        "bytes": path.stat().st_size,
        "role": role,
        "hash_source": "terminal_report" if known_sha256 else "local_sha256",
    }


def load_json(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(require(path, label).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object: {path}")
    return value


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def parse_massfluid(xml_path: Path) -> str:
    text = require(xml_path, "generated XML").read_text(encoding="utf-8", errors="replace")
    match = re.search(r"<massfluid\b[^>]*\bvalue\s*=\s*[\"']([^\"']+)[\"']", text, flags=re.IGNORECASE)
    if match is None:
        raise ValueError("generated XML has no MassFluid value")
    return match.group(1)


def h5_metadata(path: Path) -> dict[str, Any]:
    import h5py

    required = (
        "time", "position", "velocity", "density", "mass", "pressure", "type", "mk",
        "valid", "particle_id", "particle_zone", "initial_type", "initial_mk", "initial_mass",
    )
    with h5py.File(require(path, "terminal trajectory H5"), "r") as handle:
        datasets: dict[str, Any] = {}
        for name in required:
            if name not in handle:
                raise ValueError(f"terminal H5 missing required dataset {name}")
            dataset = handle[name]
            datasets[name] = {
                "shape": [int(x) for x in dataset.shape],
                "dtype": str(dataset.dtype),
                "chunks": ([int(x) for x in dataset.chunks] if dataset.chunks else None),
            }
        attrs = {}
        for name in (
            "schema", "conversion_complete", "coordinate_frame", "identity_key", "lifecycle_semantics",
            "mass_semantics", "pressure_semantics", "physical_condition_sha256", "geometry_sha256",
            "control_sha256", "source_tree_unchanged", "q_i_status", "q_n_status", "units_json",
        ):
            if name in handle.attrs:
                value = handle.attrs[name]
                attrs[name] = value.item() if hasattr(value, "item") else value
        if "rigid_body_state" in handle:
            raise ValueError("terminal source unexpectedly already contains derived rigid_body_state")
    return {"required_datasets": datasets, "attrs": attrs, "has_rigid_body_state": False}


def source_paths() -> dict[str, Path]:
    return {
        "generated_xml": XML,
        "generated_bi4": BI4,
        "motion_control": MOTION,
        "gencase_receipt": GENCASE_RECEIPT,
        "solver_receipt": RUN_RECEIPT,
        "run_out": RUN_OUT,
        "run_csv": RUN_CSV,
        "runparts": RUNPARTS,
        "partinfo": PARTINFO,
        "part_motion_ref": PART_MOTION_REF,
        "partout": PARTOUT,
        "part_first": PART_FIRST,
        "part_middle": PART_MIDDLE,
        "part_last": PART_LAST,
    }


def validate_terminal(report: dict[str, Any], receipt: dict[str, Any], h5_info: dict[str, Any]) -> None:
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise ValueError("CENTER conversion receipt is not completed/code0")
    if report.get("conversion_status") != "completed":
        raise ValueError("CENTER conversion report is not completed")
    if report.get("q_i_status") != "not_granted; conversion evidence only":
        raise ValueError("unexpected conversion Q-I self status")
    if report.get("q_n_status") != "not_assessed":
        raise ValueError("unexpected conversion Q-N status")
    if int(report.get("frames", -1)) != EXPECTED_FRAMES or int(report.get("particles", -1)) != EXPECTED_PARTICLES:
        raise ValueError("terminal H5 dimensions differ from registered CENTER baseline")
    dimension = report.get("solver_dimension", {})
    if dimension.get("solver_dimension") != 3 or str(dimension.get("xml_data2d")).lower() == "true":
        raise ValueError("terminal conversion is not actual 3D")
    times = report.get("time_evidence", {})
    if times.get("first_s") != 0.0 or float(times.get("last_s", 0.0)) < 4.0 or not times.get("strictly_increasing"):
        raise ValueError("terminal conversion does not cover the full 4 s window")
    if report.get("output_hdf5") != str(TRAJECTORY):
        raise ValueError("conversion report H5 path mismatch")
    reported_h5_sha = str(report.get("output_sha256", ""))
    if len(reported_h5_sha) != 64 or not TRAJECTORY.stat().st_size > 5 * 1024**3:
        raise ValueError("terminal H5 does not have a valid report-bound hash/size")
    if h5_info["required_datasets"]["position"]["shape"] != [EXPECTED_FRAMES, EXPECTED_PARTICLES, 3]:
        raise ValueError("terminal position dataset is not a full 3D frame axis")
    if h5_info["required_datasets"]["initial_type"]["shape"] != [EXPECTED_PARTICLES]:
        raise ValueError("terminal initial type axis is not fixed to the particle population")
    after = receipt.get("input_hashes_after_run")
    launch = receipt.get("input_hashes_at_launch")
    if not isinstance(after, dict) or not isinstance(launch, dict) or after != launch:
        raise ValueError("terminal converter input hashes changed during conversion")


def corrected_center(correction: dict[str, Any]) -> dict[str, Any]:
    rows = [case for case in correction.get("cases", []) if case.get("background") == "CENTER"]
    if len(rows) != 1:
        raise ValueError("typed correction report must contain exactly one CENTER case")
    case = rows[0]
    exclusion = case.get("partvtkout_exclusions", {})
    timeline = case.get("native_timeline", {})
    if exclusion.get("row_count") != 2123 or timeline.get("NpOut_sum") != 2123:
        raise ValueError("CENTER typed correction does not retain the actual 2123 exclusions")
    if exclusion.get("typed_type_totals") != {"3": 2123}:
        raise ValueError("CENTER correction contains non-fluid native exclusion types")
    if exclusion.get("typed_mk_totals") != {"1": 929, "2": 296, "3": 898}:
        raise ValueError("CENTER correction does not expose actual mk=1/2/3 totals")
    if not exclusion.get("all_rows_are_native_numerical_unknown"):
        raise ValueError("CENTER correction relabelled a native exclusion")
    return case


def identity_sidecar(report: dict[str, Any], correction: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    typed = report["typed_identity"]
    header_mass = Decimal(str(report["hash_scopes"]["numerical_parameters"]["decoder_header_constants"]["MassFluid"]))
    unknown_count = 2123
    return {
        "schema": "ds-data-02.f2.native-typed-identity-correction-sidecar.v1",
        "status": "actual_native_typed_identity_corrected_unknown",
        "case_id": CASE_ID,
        "physical_condition_hash": PHYSICAL_HASH,
        "source_correction_report": binding(CORRECTED_NATIVE_REPORT, "actual typed identity correction report"),
        "source_raw_native_report": binding(RAW_NATIVE_REPORT, "immutable raw native PartVTKOut report"),
        "source_corrected_records": binding(CORRECTED_RECORDS, "actual corrected native records"),
        "source_exclusion_csv": binding(EXCLUSION_CSV, "actual native PartVTKOut exclusion CSV"),
        "correction_scope": correction.get("correction_scope"),
        "identity_rule": "generated XML child mk is authoritative; mkfluid source ordinal is not used as mk",
        "typed_identity_ranges": typed["blocks"],
        "unknown_native_exclusions": {
            "count": unknown_count,
            "type": 3,
            "motive_totals": case["partvtkout_exclusions"]["motive_totals"],
            "mk_counts": case["partvtkout_exclusions"]["typed_mk_totals"],
            "first_missing_frame_by_mk": report["lifecycle"]["first_missing_frame_by_mk"],
            "final_missing_count_by_mk": report["lifecycle"]["frame_summary"][-1]["missing_mk_counts"],
            "all_rows_are_native_numerical_unknown": True,
            "physical_spill_inference": False,
            "unknown_mass_kg_using_decoder_header_particle_mass": str(header_mass * unknown_count),
        },
        "mass_semantics": {
            "continuous_initial_mass_kg": str(CONTINUOUS_MASS_KG),
            "xml_massfluid_text": parse_massfluid(XML),
            "xml_massfluid_cohort_mass_kg": str(Decimal(parse_massfluid(XML)) * EXPECTED_FLUID),
            "decoder_header_massfluid_kg_per_particle": str(header_mass),
            "h5_initial_mass_is_float32_adapter": True,
            "no_mass_normalization_or_rescaling": True,
            "strict_threshold_remains_frozen": True,
        },
        "qualification_claim": "none; correction and native unknown accounting evidence only",
        "production_claim": "none",
    }


def terminal_owner(report: dict[str, Any], receipt: dict[str, Any], correction_case: dict[str, Any], h5_info: dict[str, Any], sidecar_path: Path) -> dict[str, Any]:
    old = load_json(OLD_DEFERRED_OWNER, "prior deferred owner metadata")
    physical = load_json(
        FAMILY_ROOT / "rv4_equivalent_dp005/postprocess_handoff_v3_terminal_bound/owner_metadata/"
        f"{CASE_ID}.owner.v3.json",
        "prior physical owner metadata",
    )["physical_binding"]
    contract = load_json(QUALITY, "F2 quality contract")
    pb_geometry = physical["geometry"]
    geometry = {
        f"{name}_low_m": pb_geometry[name]["low_m"]
        for name in ("cup", "receiver", "tray")
    }
    geometry.update({f"{name}_size_m": pb_geometry[name]["size_m"] for name in ("cup", "receiver", "tray")})
    paths = source_paths()
    source = {key: binding(path, f"terminal CENTER {key}") for key, path in paths.items()}
    report_binding = binding(CONVERSION_REPORT, "completed CENTER conversion report")
    receipt_binding = binding(CONVERSION_RECEIPT, "completed CENTER conversion receipt")
    h5_binding = binding(TRAJECTORY, "completed CENTER fullstate H5", known_sha256=report["output_sha256"])
    h5_attrs = h5_info["attrs"]
    lifecycle = report["lifecycle"]
    center_quality = contract["background_contracts"]["center_catch"]
    owner = {
        "schema": "ds-data-02.f2.rv4eq-center-baseline-terminal-owner.v2",
        "status": "terminal_source_bound_pose_labels_deferred",
        "q_i_status": "conversion_evidence_only; pose and typed lifecycle are bound for root CPU review",
        "q_n_status": "not_assessed",
        "family_id": "F2",
        "background": "CENTER",
        "case_id": CASE_ID,
        "source_case_id": PHYSICAL_CASE_ID,
        "physical_case_id": PHYSICAL_CASE_ID,
        "mechanism_id": "center_catch",
        "scope_id": "F2_SCOPE_RV4_EQUIVALENT_DP005_CENTER_BASELINE_TERMINAL_20261003",
        "resolution": "dp005",
        "physical_condition_hash_declared": PHYSICAL_HASH,
        "physical_binding_sha256": PHYSICAL_HASH,
        "numerical_recipe_hash_declared": report["hash_scopes"]["numerical_parameters_sha256"],
        "definition": source["generated_xml"],
        "motion": source["motion_control"],
        "geometry": geometry,
        "quality_contract": center_quality,
        "event_window": {**physical["event_window"], "hold_start_s": 0.5},
        "mass_reference": {
            "continuous_mass_kg": float(CONTINUOUS_MASS_KG),
            "native_header_is_authority": True,
            "adapter_float32_error_is_separate": True,
            "strict_relative_budget_fraction": 1e-12,
        },
        "physical_binding": physical,
        "source": source,
        "fullstate_terminal_binding": {
            "status": "completed_code0_terminal_bound",
            "trajectory_h5": h5_binding,
            "conversion_report": report_binding,
            "conversion_receipt": receipt_binding,
            "h5_schema_metadata": h5_info,
            "conversion_report_q_i_status": report["q_i_status"],
            "conversion_report_q_n_status": report["q_n_status"],
            "production_eligibility": report["production_eligibility"],
        },
        "moving_pose_contract": {
            "status": "ready_root_cpu_pose_fit; no rigid_body_state in source H5",
            "producer": binding(LABEL_IMPL, "pose/labels implementation"),
            "pose_dataset_after_stage": "rigid_body_state",
            "actual_saved_node_state": {
                "position_dataset": "position",
                "velocity_dataset": "velocity",
                "initial_type_dataset": "initial_type",
                "moving_type": 1,
                "moving_node_count": 76676,
                "frame_count": EXPECTED_FRAMES,
            },
            "control_comparison": source["motion_control"],
            "native_moving_reference": source["part_motion_ref"],
            "static_aabb_is_insufficient": True,
            "pose_must_be_derived_from_actual_saved_nodes": True,
        },
        "typed_lifecycle_contract": {
            "identity_key": ["particle_zone", "particle_id"],
            "required_datasets": [
                "time", "particle_id", "particle_zone", "valid", "position", "velocity", "density", "mass",
                "pressure", "type", "mk", "initial_type", "initial_mk", "initial_mass",
            ],
            "units": json.loads(h5_attrs["units_json"]),
            "fixed_initial_identity_axis": True,
            "introduced_ids_rejected": True,
            "type_change_rejected": True,
            "native_invalid_identity_is_unknown": True,
            "first_missing_frame_by_mk": lifecycle["first_missing_frame_by_mk"],
            "final_unknown_count": 2123,
            "identity_correction_sidecar": binding(sidecar_path, "CENTER typed identity correction sidecar"),
        },
        "native_exclusion_evidence": {
            "raw_report": binding(RAW_NATIVE_REPORT, "immutable raw PartVTKOut report"),
            "corrected_report": binding(CORRECTED_NATIVE_REPORT, "actual typed PartVTKOut correction report"),
            "exclusion_csv": binding(EXCLUSION_CSV, "actual native exclusion CSV"),
            "corrected_records": binding(CORRECTED_RECORDS, "actual corrected native records"),
            "NpOut_sum": correction_case["native_timeline"]["NpOut_sum"],
            "NpOutPos_sum": correction_case["native_timeline"]["NpOutPos_sum"],
            "NpOutRho_sum": correction_case["native_timeline"]["NpOutRho_sum"],
            "NpOutMov_sum": correction_case["native_timeline"]["NpOutMov_sum"],
            "typed_mk_totals": correction_case["partvtkout_exclusions"]["typed_mk_totals"],
            "all_fate_unknown": True,
            "physical_spill_inference": False,
            "position_or_motive_is_not_physical_destination": True,
        },
        "event_label_contract": {
            "operator": binding(EVENT_OPERATOR, "v6 event operator"),
            "operator_manifest": binding(EVENT_MANIFEST, "v6 operator manifest"),
            "destination_classes": ["cup_local_top_aperture", "receiver_finite_wall", "tray_finite_wall", "legal_open_domain_exit", "numerical_unknown"],
            "native_unknown_remains_separate": True,
            "event_time_budget_s": EVENT_TIME_BUDGET_S,
            "save_half_width_budget_s": SAVE_HALF_WIDTH_BUDGET_S,
        },
        "lineage": {
            "prior_deferred_owner": binding(OLD_DEFERRED_OWNER, "prior deferred owner metadata"),
            "conversion_report": report_binding,
            "conversion_receipt": receipt_binding,
            "typed_identity_sidecar": binding(sidecar_path, "typed identity sidecar"),
        },
        "qualification_claim": "none; terminal conversion and pose/label request evidence only",
        "production_claim": "none",
    }
    if h5_attrs.get("physical_condition_sha256") != PHYSICAL_HASH or h5_attrs.get("geometry_sha256") != report["source_provenance"]["geometry_sha256"]:
        raise ValueError("H5 physical/geometry attributes do not match frozen source hashes")
    return owner


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def labels_request(owner: dict[str, Any], sidecar_path: Path) -> dict[str, Any]:
    attempt_root = F2_DATA / CASE_ID / "labels-center-baseline-terminal-v2"
    output = attempt_root / "f2-v6-labels.h5"
    observations = attempt_root / "f2-v6-observations.json"
    augmented = attempt_root / "trajectory-with-actual-pose.h5"
    pose_report = attempt_root / "rigid-body-state.json"
    input_paths = [
        FAMILY_ROOT / Path(__file__).name, LABEL_IMPL, EVENT_OPERATOR, EVENT_MANIFEST, POSE_HELPER,
        RUNTIME, STRICT_DISPATCH, QUALITY, EVENTS, SAVE_PLAN, CASE_REGISTRY, REFERENCE_MATRIX, GOAL,
        OWNER_PATH, sidecar_path, TRAJECTORY, CONVERSION_REPORT, CONVERSION_RECEIPT,
        XML, MOTION, GENCASE_RECEIPT, RUN_RECEIPT, RUN_OUT, RUN_CSV, RUNPARTS,
        PARTINFO, PART_MOTION_REF, PARTOUT, EXCLUSION_CSV,
    ]
    paths = list(dict.fromkeys(Path(path).resolve() for path in input_paths))
    input_hashes: dict[str, str] = {}
    for path in paths:
        if path == TRAJECTORY:
            input_hashes[str(path)] = str(owner["fullstate_terminal_binding"]["trajectory_h5"]["sha256"])
        else:
            input_hashes[str(path)] = sha256(path)
    command = [
        str(PYTHON), str(FAMILY_ROOT / Path(__file__).name), "run",
        "--source-h5", str(TRAJECTORY), "--augmented-h5", "{attempt_root}/trajectory-with-actual-pose.h5",
        "--owner", str(OWNER_PATH), "--generated-xml", str(XML), "--motion", str(MOTION),
        "--run-out", str(RUN_OUT), "--conversion-report", str(CONVERSION_REPORT),
        "--solver-receipt", str(RUN_RECEIPT), "--gencase-receipt", str(GENCASE_RECEIPT),
        "--conversion-receipt", str(CONVERSION_RECEIPT), "--exclusion-csv", str(EXCLUSION_CSV),
        "--case-id", CASE_ID, "--numerical-recipe-hash", str(owner["numerical_recipe_hash_declared"]),
        "--output", "{attempt_root}/f2-v6-labels.h5", "--report", "{attempt_root}/f2-v6-observations.json",
        "--pose-report", "{attempt_root}/rigid-body-state.json",
    ]
    return {
        "schema": "ds-data-02.f2.center-baseline-labels-request.v2-terminal-bound",
        "family_id": "F2",
        "case_id": CASE_ID,
        "attempt_id": "labels-f2-rv4eq-center-v1-baseline-save001-pose-v2",
        "status": "ready_root_cpu_labels_after_review",
        "kind": "cpu",
        "cpu_task_kind": "actual_saved_moving_pose_and_v6_event_labels",
        "cpu_threads": 4,
        "max_wall_seconds": 1800,
        "estimated_storage_bytes": 16 * 1024**3,
        "runnable": True,
        "launch_allowed": False,
        "root_only": True,
        "solver_launch_forbidden": True,
        "conversion_launch_forbidden": True,
        "gpu_launch": {"family_owner_launch": False, "primary_process_gpu_only": True},
        "command": command,
        "cwd": str(FAMILY_ROOT),
        "raw_output_root": str(F2_DATA / CASE_ID),
        "input_files": [str(path) for path in paths],
        "input_sha256": input_hashes,
        "source_bindings": {
            "trajectory_h5": owner["fullstate_terminal_binding"]["trajectory_h5"],
            "conversion_report": owner["fullstate_terminal_binding"]["conversion_report"],
            "conversion_receipt": owner["fullstate_terminal_binding"]["conversion_receipt"],
            "owner_metadata": binding(OWNER_PATH, "terminal owner metadata"),
            "typed_identity_sidecar": binding(sidecar_path, "typed identity sidecar"),
            "native_exclusion_csv": binding(EXCLUSION_CSV, "corrected native exclusion CSV"),
            "motion_control": binding(MOTION, "copied motion control"),
            "part_motion_ref": binding(PART_MOTION_REF, "actual native moving reference BI4"),
        },
        "physical_condition_hash": PHYSICAL_HASH,
        "numerical_recipe_hash": owner["numerical_recipe_hash_declared"],
        "pose_semantics": {
            "source_nodes": "actual source H5 position/velocity for initial_type=1",
            "derived_dataset": "rigid_body_state",
            "motion_control_is_comparison_only": True,
            "initial_aabb_not_used_as_pose": True,
        },
        "native_exclusion_semantics": {
            "unknown_count": 2123,
            "mk_counts": {"1": 929, "2": 296, "3": 898},
            "motive_is_not_spill": True,
            "unknown_mass_remains_in_denominator": True,
        },
        "expected_outputs": {
            "augmented_trajectory": str(augmented),
            "labels": str(output),
            "observations": str(observations),
            "pose_report": str(pose_report),
            "receipt": str(attempt_root / "execution-receipt.json"),
        },
        "contract_checks_before_launch": [
            "terminal H5/report/receipt hashes remain unchanged",
            "actual saved Type=1 nodes fit a finite rigid_body_state before event labeling",
            "corrected native exclusion CSV is passed explicitly to the event operator",
            "native exclusions remain numerical_unknown and are never promoted to spill",
            "Q-I/Q-N/production are not self-declared by this request",
        ],
        "qualification_claim": "none; root CPU pose/label evidence only",
        "production_claim": "none",
    }


def build() -> dict[str, Any]:
    report = load_json(CONVERSION_REPORT, "CENTER terminal conversion report")
    receipt = load_json(CONVERSION_RECEIPT, "CENTER terminal conversion receipt")
    h5_info = h5_metadata(TRAJECTORY)
    validate_terminal(report, receipt, h5_info)
    correction = load_json(CORRECTED_NATIVE_REPORT, "CENTER corrected native report")
    correction_case = corrected_center(correction)
    sidecar_value = identity_sidecar(report, correction, correction_case)
    dump(IDENTITY_PATH, sidecar_value)
    owner_value = terminal_owner(report, receipt, correction_case, h5_info, IDENTITY_PATH)
    dump(OWNER_PATH, owner_value)
    request_value = labels_request(owner_value, IDENTITY_PATH)
    dump(LABEL_REQUEST_PATH, request_value)
    manifest = {
        "schema": SCHEMA,
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "family_id": "F2",
        "case_id": CASE_ID,
        "scope_id": owner_value["scope_id"],
        "status": "terminal_source_bound_labels_root_review_pending",
        "source": {
            "trajectory_h5": owner_value["fullstate_terminal_binding"]["trajectory_h5"],
            "conversion_report": owner_value["fullstate_terminal_binding"]["conversion_report"],
            "conversion_receipt": owner_value["fullstate_terminal_binding"]["conversion_receipt"],
            "generated_xml": owner_value["source"]["generated_xml"],
            "motion_control": owner_value["source"]["motion_control"],
        },
        "typed_identity_sidecar": binding(IDENTITY_PATH, "actual typed identity correction sidecar"),
        "owner_metadata": binding(OWNER_PATH, "terminal CENTER owner metadata"),
        "labels_request": binding(LABEL_REQUEST_PATH, "root-only pose/labels request"),
        "native_unknown": {
            "count": 2123,
            "mk_counts": {"1": 929, "2": 296, "3": 898},
            "motive_totals": {"1": 2123},
            "physical_fate": "unknown",
        },
        "launch_policy": {"solver": False, "gencase": False, "conversion": False, "labels": False, "root_owns_dispatch": True},
        "qualification_claim": "none",
        "production_claim": "none",
        "q_i_status": "conversion_evidence_only",
        "q_n_status": "not_assessed",
    }
    dump(MANIFEST_PATH, manifest)
    return manifest


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_labels(args: argparse.Namespace) -> dict[str, Any]:
    source = require(args.source_h5, "source H5")
    augmented = args.augmented_h5.resolve()
    if augmented.exists() or augmented == source:
        raise ValueError("refusing to overwrite or alias source H5")
    augmented.parent.mkdir(parents=True, exist_ok=True)
    labels_impl = load_module(LABEL_IMPL, "f2_terminal_labels_impl")
    # ``augment_pose`` performs the single streaming copy itself while it
    # creates the derived H5 and appends the fitted rigid-body state.  Do not
    # copy the 6 GB source here as well: that would either double the I/O or
    # make the helper reject its already-existing destination.
    pose = labels_impl.augment_pose(
        source=source,
        augmented=augmented,
        generated_xml=require(args.generated_xml, "generated XML"),
        motion=require(args.motion, "motion control"),
        run_out=require(args.run_out, "Run.out"),
        pose_report=args.pose_report,
        conversion_report=require(args.conversion_report, "conversion report"),
        solver_receipt=require(args.solver_receipt, "solver receipt"),
        gencase_receipt=require(args.gencase_receipt, "GenCase receipt"),
        owner_metadata=require(args.owner, "owner metadata"),
    )
    event = load_module(EVENT_OPERATOR, "f2_terminal_event_operator")
    observations = event.observe(
        trajectory=augmented,
        owner_metadata=require(args.owner, "owner metadata"),
        exclusion_csv=require(args.exclusion_csv, "corrected exclusion CSV"),
        output=args.output.resolve(),
        report=args.report.resolve(),
        definition_override=require(args.generated_xml, "generated XML"),
        numerical_recipe_hash_override=args.numerical_recipe_hash,
        case_id_override=args.case_id,
    )
    return {
        "schema": "ds-data-02.f2.center-baseline-pose-labels.v1",
        "status": "completed_evidence_only",
        "pose_report": pose.get("pose_report"),
        "augmented_trajectory": {"path": str(augmented), "sha256": sha256(augmented)},
        "observations": observations,
        "q_i_status": "not_granted",
        "q_n_status": "not_assessed",
        "production_eligibility": "not_evaluated",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("build")
    run = sub.add_parser("run")
    run.add_argument("--source-h5", type=Path, required=True)
    run.add_argument("--augmented-h5", type=Path, required=True)
    run.add_argument("--owner", type=Path, required=True)
    run.add_argument("--generated-xml", type=Path, required=True)
    run.add_argument("--motion", type=Path, required=True)
    run.add_argument("--run-out", type=Path, required=True)
    run.add_argument("--conversion-report", type=Path, required=True)
    run.add_argument("--solver-receipt", type=Path, required=True)
    run.add_argument("--gencase-receipt", type=Path, required=True)
    run.add_argument("--conversion-receipt", type=Path, required=True)
    run.add_argument("--exclusion-csv", type=Path, required=True)
    run.add_argument("--case-id", required=True)
    run.add_argument("--numerical-recipe-hash", required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--report", type=Path, required=True)
    run.add_argument("--pose-report", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = build() if args.command == "build" else run_labels(args)
        print(json.dumps({"status": result.get("status"), "path": str(MANIFEST_PATH if args.command == "build" else args.report)}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, RuntimeError, ImportError) as error:
        print(f"f2_rv4eq_center_terminal_product_v1: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
