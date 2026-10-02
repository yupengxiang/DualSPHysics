#!/usr/bin/env python3
"""Register the completed F3 quarter-dt run for later CPU postprocessing.

This producer is registration-only.  It reads the already completed root-owned
quarter-dt solver receipt and RunPARTs ledger, then writes an additive owner,
conversion request, deferred native-label request, and deferred quarter-vs-
HALF_DT comparison request.  It never starts a converter, labels job, solver,
or GPU run.  All future HDF5/report/receipt hashes remain unresolved until a
terminal conversion receipt exists.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import Any


HANDOFF_ROOT = Path(__file__).resolve().parent
F3_ROOT = HANDOFF_ROOT.parents[1]
WORKTREE_ROOT = F3_ROOT.parents[4]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
DATA_F3 = DATA_ROOT / "families/F3"
INTEGRATION_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
INFRA_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics")
OFFICIAL_LAB = Path("/home/jade/Projects/DualSPHysics") / "lagrangian-fluid-lab"
BIN_ROOT = OFFICIAL_LAB / "vendor/official/DualSPHysics_v5.4/bin/linux"
PYTHON = INFRA_ROOT / "lagrangian-fluid-lab/.venv/bin/python"

CASE_ID = "F3_DUAL_AXIS_WEAK_006G_004G_QUARTER_DT"
PHYSICAL_CASE_ID = "F3_DUAL_AXIS_WEAK_006G_004G"
HALF_CASE_ID = "F3_DUAL_AXIS_WEAK_006G_004G_HALF_DT"
PHYSICAL_BINDING_SHA = "fdb645e24952ed2f41225ca537d067d0233c9a94746fd4af0c390205736c9b10"
CONTROL_SHA = "98cb5a00395301e4e5561d57b8d56189686f468a16f0b4420c6f96c3e4995e6b"
QUARTER_DT_S = 5.53067421676747e-06
HALF_DT_S = 1.106134843353494e-05
BASELINE_DT_S = 2.212269686706988e-05
SAVE_INTERVAL_S = 0.0025
WINDOW_S = [0.0, 10.0]
FLUID_PARTICLES = 34560
TOTAL_PARTICLES = 108000
INITIAL_FLUID_MASS_KG = 14.58
EXPECTED_FRAMES = 4001
SCHEMA = "ds02.f3.quarter-dt-postprocess-registration.v1"

QUARTER_ROOT = DATA_F3 / CASE_ID
QUARTER_PREP_ROOT = QUARTER_ROOT / "prepare-solver-input-quarter_dt-20261002-002"
QUARTER_SOLVER_ROOT = QUARTER_ROOT / "qualification-weak-dual-quarter_dt-root-reviewed-20261002-002"
QUARTER_XML = QUARTER_PREP_ROOT / "prepared/F3_DUAL_AXIS_WEAK_006G_004G_QUARTER_DT.xml"
QUARTER_BI4 = QUARTER_PREP_ROOT / "prepared/F3_DUAL_AXIS_WEAK_006G_004G_QUARTER_DT.bi4"
QUARTER_CONTROL = QUARTER_PREP_ROOT / "prepared/F3_DualAxisPhase_WeakControl.csv"
QUARTER_PREP_REPORT = QUARTER_PREP_ROOT / "prepared/prepared-quarter-dt-report.json"
QUARTER_PREP_RECEIPT = QUARTER_PREP_ROOT / "execution-receipt.json"
QUARTER_SOLVER_RECEIPT = QUARTER_SOLVER_ROOT / "execution-receipt.json"
QUARTER_RUN_OUT = QUARTER_SOLVER_ROOT / "solver_output/Run.out"
QUARTER_RUN_CSV = QUARTER_SOLVER_ROOT / "solver_output/Run.csv"
QUARTER_RUNPARTS = QUARTER_SOLVER_ROOT / "solver_output/RunPARTs.csv"
QUARTER_DATA = QUARTER_SOLVER_ROOT / "solver_output/data"

HALF_ROOT = DATA_F3 / HALF_CASE_ID
HALF_XML = HALF_ROOT / "prepare-solver-input-half_dt-20261002-002/prepared/F3_DUAL_AXIS_WEAK_006G_004G_HALF_DT.xml"
HALF_BI4 = HALF_ROOT / "prepare-solver-input-half_dt-20261002-002/prepared/F3_DUAL_AXIS_WEAK_006G_004G_HALF_DT.bi4"
HALF_CONTROL = HALF_ROOT / "prepare-solver-input-half_dt-20261002-002/prepared/F3_DualAxisPhase_WeakControl.csv"
HALF_SOLVER_RECEIPT = HALF_ROOT / "qualification-weak-dual-half_dt-20261002-002/execution-receipt.json"
HALF_GENCAS_RECEIPT = HALF_ROOT / "gencase-weak-dual-half_dt-20261002-001/execution-receipt.json"
HALF_LABELS = HALF_ROOT / "native-labels-half_dt-20261002-005/typed-transport-labels.h5"
HALF_LABEL_RECEIPT = HALF_ROOT / "native-labels-half_dt-20261002-005/execution-receipt.json"
HALF_CONVERSION_REPORT = HALF_ROOT / "direct-half_dt-20261002-004/direct-conversion-report.json"
HALF_CONVERSION_RECEIPT = HALF_ROOT / "direct-half_dt-20261002-004/execution-receipt.json"
HALF_ACCOUNTING = HALF_ROOT / "native-accounting-half_dt-20261002-003/native-accounting.json"
HALF_RAW_MANIFEST = HALF_ROOT / "raw-manifest-half_dt-20261002-002/raw-frame-manifest.json"

DIRECT_CONVERTER = INFRA_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_direct_convert.py"
NATIVE_LABELS = INTEGRATION_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_native_labels.py"
TRANSPORT_COMPARE = INTEGRATION_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_f3_transport_compare.py"
TRANSPORT_CONFIG = INTEGRATION_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/f3_weak_full_transport_config.v1.json"
OPERATORS = INFRA_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/f3_weak_operators.v1.json"
BASE_OWNER = INFRA_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/weak_dual_scope_001/f3_weak_owner_metadata.json"
HALF_DIRECT_REQUEST = INTEGRATION_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261002/requests/half_dt-direct-conversion-request-004.json"
HALF_LABEL_REQUEST = INTEGRATION_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261002/requests/half_dt-native-labels-request-004.json"
HALF_COMPARISON_REQUEST = INTEGRATION_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261002/requests/half_dt-transport-comparison-request-002.json"
TEMPORAL_ASSESSMENT = INTEGRATION_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261002/f3_weak_dual_temporal_budget_assessment_001.json"
QUARTER_ROOT_REVIEW_REQUEST = INTEGRATION_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261002/root_quarter_dt_review_002/solver_request.json"
QUARTER_ROOT_PREFLIGHT = INTEGRATION_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261002/root_quarter_dt_review_002/root_preflight.json"
QUARTER_PREP_SCRIPT = INFRA_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_f3_quarter_dt_prepare.py"
RUNTIME = INTEGRATION_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
PARTVTK = BIN_ROOT / "PartVTK_linux64"
DECODER = OFFICIAL_LAB / "campaigns/l1-resume/artifacts/bi4_dump"

CONVERSION_ATTEMPT_ID = "direct-quarter_dt-20261003-001"
LABEL_ATTEMPT_ID = "native-labels-quarter_dt-20261003-001"
COMPARISON_ATTEMPT_ID = "quarter-vs-half-transport-20261003-001"
CONVERSION_ROOT = QUARTER_ROOT / CONVERSION_ATTEMPT_ID
LABEL_ROOT = QUARTER_ROOT / LABEL_ATTEMPT_ID
COMPARISON_ROOT = QUARTER_ROOT / COMPARISON_ATTEMPT_ID


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def require(path: Path, label: str) -> Path:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} missing: {path}")
    return path


def binding(path: Path, role: str) -> dict[str, Any]:
    path = require(path, role)
    return {"path": str(path), "sha256": digest(path), "bytes": path.stat().st_size, "role": role}


def deferred(path: Path, role: str) -> dict[str, Any]:
    return {
        "path": str(path),
        "sha256": None,
        "bytes": None,
        "role": role,
        "status": "awaiting_terminal_converter_receipt",
        "required_status": "completed",
        "must_bind_actual_hash_before_dispatch": True,
    }


def load_json(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(require(path, label).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object: {path}")
    return value


def runparts_summary(path: Path) -> dict[str, Any]:
    rows: list[dict[str, str]] = []
    with require(path, "quarter RunPARTs") .open(newline="") as handle:
        for row in csv.DictReader(handle, delimiter=";"):
            try:
                int(row.get("Part", ""))
            except (TypeError, ValueError):
                continue
            rows.append(row)
    if not rows:
        raise ValueError("quarter RunPARTs has no numeric rows")

    def number(row: dict[str, str], key: str) -> float:
        return float(row[key].replace(",", ""))

    def series(key: str) -> list[float]:
        return [number(row, key) for row in rows]

    dtmin = series("DtMin [s]")
    dtmax = series("DtMax [s]")
    # Part 0 is the initial state and reports zero before the first advance;
    # the fixed-step claim is about the actual integration rows that follow.
    post_initial_dtmin = dtmin[1:]
    post_initial_dtmax = dtmax[1:]

    return {
        "rows": len(rows),
        "first_time_s": number(rows[0], "TimeStep [s]"),
        "last_time_s": number(rows[-1], "TimeStep [s]"),
        "NpOut_sum": int(round(sum(series("NpOut")))),
        "NpOutPos_sum": int(round(sum(series("NpOutPos")))),
        "NpOutRho_sum": int(round(sum(series("NpOutRho")))),
        "NpOutMov_sum": int(round(sum(series("NpOutMov")))),
        "NpSim_min": int(round(min(series("NpSim")))),
        "NpSim_max": int(round(max(series("NpSim")))),
        "NpfSim_min": int(round(min(series("NpfSim")))),
        "NpfSim_max": int(round(max(series("NpfSim")))),
        "NpbSim_min": int(round(min(series("NpbSim")))),
        "NpbSim_max": int(round(max(series("NpbSim")))),
        "DtMin_min_s": min(dtmin),
        "DtMin_max_s": max(dtmin),
        "DtMax_min_s": min(dtmax),
        "DtMax_max_s": max(dtmax),
        "post_initial_DtMin_min_s": min(post_initial_dtmin),
        "post_initial_DtMin_max_s": max(post_initial_dtmin),
        "post_initial_DtMax_min_s": min(post_initial_dtmax),
        "post_initial_DtMax_max_s": max(post_initial_dtmax),
        "post_initial_fixed_step_exact": all(abs(value - QUARTER_DT_S) <= 1e-18 for value in post_initial_dtmin + post_initial_dtmax),
        "full_window_completed": number(rows[-1], "TimeStep [s]") >= WINDOW_S[1],
        "identity_loss_claim": "none from RunPARTs NpOut fields; H5 lifecycle/Q-I still pending",
    }


def physical_projection(path: Path) -> str:
    root = ET.parse(require(path, "generated XML")).getroot()
    for node in root.findall(".//parameter"):
        if node.attrib.get("key") in {"DtIni", "DtMin", "DtFixed"}:
            node.set("value", "<time-study-variant>")
    return hashlib.sha256(ET.tostring(root, encoding="utf-8")).hexdigest()


def source_bindings() -> dict[str, dict[str, Any]]:
    return {
        "quarter_xml": binding(QUARTER_XML, "quarter generated XML"),
        "quarter_bi4": binding(QUARTER_BI4, "quarter native BI4"),
        "quarter_control": binding(QUARTER_CONTROL, "quarter copied control CSV"),
        "quarter_prepare_report": binding(QUARTER_PREP_REPORT, "quarter preparation report"),
        "quarter_prepare_receipt": binding(QUARTER_PREP_RECEIPT, "quarter preparation receipt"),
        "quarter_solver_receipt": binding(QUARTER_SOLVER_RECEIPT, "completed quarter solver receipt"),
        "quarter_run_out": binding(QUARTER_RUN_OUT, "quarter Run.out"),
        "quarter_run_csv": binding(QUARTER_RUN_CSV, "quarter Run.csv"),
        "quarter_runparts": binding(QUARTER_RUNPARTS, "quarter RunPARTs.csv"),
        "half_xml": binding(HALF_XML, "immutable HALF_DT XML"),
        "half_bi4": binding(HALF_BI4, "immutable HALF_DT BI4"),
        "half_control": binding(HALF_CONTROL, "immutable HALF_DT control CSV"),
        "half_solver_receipt": binding(HALF_SOLVER_RECEIPT, "completed HALF_DT solver receipt"),
        "half_gencase_receipt": binding(HALF_GENCAS_RECEIPT, "reused HALF_DT GenCase receipt"),
        "half_labels": binding(HALF_LABELS, "completed HALF_DT native labels"),
        "half_label_receipt": binding(HALF_LABEL_RECEIPT, "completed HALF_DT labels receipt"),
        "half_conversion_report": binding(HALF_CONVERSION_REPORT, "completed HALF_DT conversion report"),
        "half_conversion_receipt": binding(HALF_CONVERSION_RECEIPT, "completed HALF_DT conversion receipt"),
        "half_accounting": binding(HALF_ACCOUNTING, "HALF_DT native accounting"),
        "half_raw_manifest": binding(HALF_RAW_MANIFEST, "HALF_DT raw frame manifest"),
        "base_owner": binding(BASE_OWNER, "frozen F3 physical owner"),
        "half_direct_request": binding(HALF_DIRECT_REQUEST, "consumed HALF_DT conversion request"),
        "half_label_request": binding(HALF_LABEL_REQUEST, "consumed HALF_DT labels request"),
        "half_comparison_request": binding(HALF_COMPARISON_REQUEST, "consumed HALF_DT comparison request"),
        "temporal_assessment": binding(TEMPORAL_ASSESSMENT, "frozen temporal budget assessment"),
        "quarter_root_request": binding(QUARTER_ROOT_REVIEW_REQUEST, "root quarter solver request"),
        "quarter_root_preflight": binding(QUARTER_ROOT_PREFLIGHT, "root quarter solver preflight"),
        "quarter_prepare_script": binding(QUARTER_PREP_SCRIPT, "quarter input preparation script"),
        "direct_converter": binding(DIRECT_CONVERTER, "direct converter"),
        "native_labels": binding(NATIVE_LABELS, "native labels producer"),
        "transport_compare": binding(TRANSPORT_COMPARE, "transport comparison reducer"),
        "transport_config": binding(TRANSPORT_CONFIG, "frozen transport config"),
        "operators": binding(OPERATORS, "frozen F3 operators"),
        "runtime": binding(RUNTIME, "shared runtime v2"),
        "partvtk": binding(PARTVTK, "official PartVTK decoder"),
        "decoder": binding(DECODER, "official BI4 decoder"),
        "registration_script": binding(Path(__file__), "quarter registration producer"),
    }


def owner_payload(bindings: dict[str, dict[str, Any]], timeline: dict[str, Any], projection: str) -> dict[str, Any]:
    solver = load_json(QUARTER_SOLVER_RECEIPT, "quarter solver receipt")
    return {
        "schema": "ds02.f3.quarter-dt-fullstate-owner.v1-deferred",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "deferred_until_root_conversion_terminal",
        "family_id": "F3",
        "case_id": CASE_ID,
        "physical_case_id": PHYSICAL_CASE_ID,
        "study_role": "quarter_dt_same_save",
        "scope_id": "F3_WEAK_DUAL_FIXED_WINDOW_TEMPORAL_SENSITIVITY_20261002",
        "physical_binding_sha256": PHYSICAL_BINDING_SHA,
        "physical_geometry_control_contract": {
            "same_physical_case_as": HALF_CASE_ID,
            "changed_solver_keys_only": ["DtIni", "DtMin", "DtFixed"],
            "generated_xml_physical_projection_sha256": projection,
            "half_dt_generated_xml_physical_projection_sha256": physical_projection(HALF_XML),
            "bi4_same_sha256": bindings["quarter_bi4"]["sha256"] == bindings["half_bi4"]["sha256"],
            "control_same_sha256": bindings["quarter_control"]["sha256"] == CONTROL_SHA,
            "motion_or_forcing_source": bindings["quarter_control"],
        },
        "initial_condition": {
            "dimension": 3,
            "fluid_particles": FLUID_PARTICLES,
            "total_particles": TOTAL_PARTICLES,
            "continuous_initial_fluid_mass_kg": INITIAL_FLUID_MASS_KG,
            "run_out_mass_fluid_per_particle_kg": 0.000421875,
            "runparts_initial_NpfSim": timeline["NpfSim_min"],
            "runparts_initial_NpbSim": timeline["NpbSim_min"],
        },
        "numerical_recipe": {
            "DtFixed_s": QUARTER_DT_S,
            "DtIni_s": QUARTER_DT_S,
            "DtMin_s": QUARTER_DT_S,
            "DtFixedFile": "NONE",
            "TimeOut_s": SAVE_INTERVAL_S,
            "TimeMax_s": WINDOW_S[1],
            "expected_saved_frames": EXPECTED_FRAMES,
            "expected_steps": 1808098,
            "actual_runparts_dt_min_s": [timeline["DtMin_min_s"], timeline["DtMin_max_s"]],
            "actual_runparts_dt_max_s": [timeline["DtMax_min_s"], timeline["DtMax_max_s"]],
            "post_initial_fixed_dt_min_s": [timeline["post_initial_DtMin_min_s"], timeline["post_initial_DtMin_max_s"]],
            "post_initial_fixed_dt_max_s": [timeline["post_initial_DtMax_min_s"], timeline["post_initial_DtMax_max_s"]],
            "post_initial_fixed_step_exact": timeline["post_initial_fixed_step_exact"],
        },
        "source": bindings,
        "actual_solver": {
            "receipt_status": solver.get("status"),
            "returncode": solver.get("returncode"),
            "elapsed_seconds": solver.get("elapsed_seconds"),
            "gpu_seconds": solver.get("gpu_seconds"),
            "timeline": timeline,
            "native_exclusion_semantics": "RunPARTs NpOut/NpOutPos/NpOutRho/NpOutMov all zero; full typed H5 lifecycle still requires conversion and Q-I audit",
        },
        "terminal_conversion_binding": {
            "status": "deferred_until_root_conversion_terminal",
            "attempt_root": str(CONVERSION_ROOT),
            "trajectory_h5": deferred(CONVERSION_ROOT / "trajectory.h5", "quarter full typed trajectory H5"),
            "conversion_report": deferred(CONVERSION_ROOT / "direct-conversion-report.json", "quarter conversion report"),
            "conversion_receipt": deferred(CONVERSION_ROOT / "execution-receipt.json", "quarter terminal conversion receipt"),
            "required_before_labels_or_QI": True,
        },
        "lifecycle_contract": {
            "identity_key": ["particle_zone", "particle_id"],
            "required_datasets": ["time", "particle_id", "particle_zone", "valid", "position", "velocity", "density", "mass", "pressure", "type", "mk", "initial_type", "initial_mk", "initial_mass"],
            "valid_false_is_numerical_unknown": True,
            "birth_reuse_type_change_forbidden": True,
            "units_required": True,
            "no_QI_before_actual_H5_report": True,
        },
        "comparison_contract": {
            "comparison_variant": "quarter_dt_vs_HALF_DT",
            "fixed_window_s": WINDOW_S,
            "same_save_interval_s": SAVE_INTERVAL_S,
            "event_time_relative_starting_budget": 0.02,
            "macro_relative_starting_budget": 0.05,
            "save_or_integration_share_cap": 0.20,
            "derived_save_or_integration_fraction_of_event_time": 0.004,
            "residence_time_budget_registered": False,
            "status": "not_assessed_until_actual_quarter_labels_and_comparison",
        },
        "qualification_claim": "none",
        "q_n_status": "not_assessed",
        "production_status": "not_accepted",
    }


def conversion_request(owner_path: Path, bindings: dict[str, dict[str, Any]], timeline: dict[str, Any]) -> dict[str, Any]:
    input_paths = [
        DIRECT_CONVERTER, DECODER, PARTVTK, QUARTER_XML, QUARTER_BI4, QUARTER_CONTROL,
        QUARTER_PREP_REPORT, QUARTER_PREP_RECEIPT, QUARTER_SOLVER_RECEIPT,
        QUARTER_RUN_OUT, QUARTER_RUN_CSV, QUARTER_RUNPARTS, HALF_GENCAS_RECEIPT,
        BASE_OWNER, OPERATORS, TRANSPORT_CONFIG, RUNTIME, QUARTER_PREP_SCRIPT,
        QUARTER_ROOT_REVIEW_REQUEST, QUARTER_ROOT_PREFLIGHT, TEMPORAL_ASSESSMENT,
        owner_path, Path(__file__),
    ]
    input_files = [str(require(path, "conversion input")) for path in input_paths]
    input_hashes = {path: digest(Path(path)) for path in input_files}
    return {
        "schema": "ds02.runner-request.v2",
        "family_id": "F3",
        "case_id": CASE_ID,
        "physical_case_id": PHYSICAL_CASE_ID,
        "attempt_id": CONVERSION_ATTEMPT_ID,
        "kind": "cpu",
        "cpu_task_kind": "conversion",
        "cpu_threads": 4,
        "max_wall_seconds": 7200,
        "estimated_storage_bytes": 64 * 1024**3,
        "root_only": True,
        "launch_authority": "root-only via shared runtime v2; this registration does not launch conversion",
        "status": "root_review_ready",
        "runnable": True,
        "ready_for_root_dispatch": True,
        "launch_allowed_by_this_agent": False,
        "command": [
            str(PYTHON), str(DIRECT_CONVERTER),
            "--data-root", str(QUARTER_DATA),
            "--generated-xml", str(QUARTER_XML),
            "--output", "{attempt_root}/trajectory.h5",
            "--report", "{attempt_root}/direct-conversion-report.json",
            "--decoder", str(DECODER),
            "--partvtk", str(PARTVTK),
            "--validation-dir", "{attempt_root}/partvtk-validation",
            "--solver-log", str(QUARTER_RUN_OUT),
            "--solver-receipt", str(QUARTER_SOLVER_RECEIPT),
            "--gencase-receipt", str(HALF_GENCAS_RECEIPT),
            "--owner-metadata", str(owner_path),
            "--particle-chunk", "65536",
            "--keep-validation-csv",
        ],
        "cwd": str(INFRA_ROOT / "lagrangian-fluid-lab"),
        "worktree_root": str(WORKTREE_ROOT),
        "solver_launch_forbidden": True,
        "gpu_launch": {"allowed": False, "owner": "root"},
        "window_s": WINDOW_S,
        "output_interval_s": SAVE_INTERVAL_S,
        "expected_native": {
            "dimension": 3,
            "fluid_particles": FLUID_PARTICLES,
            "total_particles": TOTAL_PARTICLES,
            "saved_frames": EXPECTED_FRAMES,
            "initial_fluid_mass_kg": INITIAL_FLUID_MASS_KG,
            "window_s": WINDOW_S,
            "official_partvtk_validation_frames": ["first", "middle", "final"],
            "runparts_rows": timeline["rows"],
            "native_exclusions": {"NpOut_sum": timeline["NpOut_sum"], "NpOutPos_sum": timeline["NpOutPos_sum"], "NpOutRho_sum": timeline["NpOutRho_sum"], "NpOutMov_sum": timeline["NpOutMov_sum"]},
        },
        "physical_binding_sha256": PHYSICAL_BINDING_SHA,
        "numerical_parameters": {"DtFixed": QUARTER_DT_S, "DtIni": QUARTER_DT_S, "DtMin": QUARTER_DT_S, "DtFixedFile": "NONE", "TimeMax": WINDOW_S[1], "TimeOut": SAVE_INTERVAL_S},
        "input_files": input_files,
        "input_hashes": input_hashes,
        "source_immutability": True,
        "hdf5_binding_policy": "new quarter HDF5 is additive; no solver output, HALF_DT HDF5, request, or receipt is overwritten",
        "gencase_reuse": {"receipt": str(HALF_GENCAS_RECEIPT), "semantics": "BI4 is byte-identical to the frozen HALF_DT GenCase product; quarter changes XML time parameters only"},
        "deferred_stages": ["full typed Q-I audit", "native labels and lifecycle/units review", "quarter-vs-HALF_DT frozen budget comparison"],
        "qualification_claim": "none; conversion request only",
        "q_n_status": "not_assessed",
        "production_status": "not_accepted",
    }


def labels_request(owner_path: Path, conversion_path: Path, bindings: dict[str, dict[str, Any]]) -> dict[str, Any]:
    input_paths = [NATIVE_LABELS, TRANSPORT_CONFIG, OPERATORS, owner_path, conversion_path, QUARTER_SOLVER_RECEIPT, QUARTER_RUNPARTS, QUARTER_RUN_OUT, QUARTER_XML, QUARTER_CONTROL, TEMPORAL_ASSESSMENT]
    input_files = [str(require(path, "labels input")) for path in input_paths]
    return {
        "schema": "ds02.runner-request.v2",
        "family_id": "F3",
        "case_id": CASE_ID,
        "physical_case_id": PHYSICAL_CASE_ID,
        "attempt_id": LABEL_ATTEMPT_ID,
        "kind": "cpu",
        "cpu_task_kind": "labels",
        "cpu_threads": 4,
        "max_wall_seconds": 3000,
        "estimated_storage_bytes": 8 * 1024**3,
        "status": "deferred_until_terminal_conversion",
        "runnable": False,
        "launch_allowed": False,
        "root_only": True,
        "command": [
            str(PYTHON), str(NATIVE_LABELS),
            "--source", str(CONVERSION_ROOT / "trajectory.h5"),
            "--output", "{attempt_root}/typed-transport-labels.h5",
            "--config", str(TRANSPORT_CONFIG),
            "--particle-chunk", "65536",
        ],
        "cwd": str(INTEGRATION_ROOT / "lagrangian-fluid-lab"),
        "worktree_root": str(WORKTREE_ROOT),
        "input_files": input_files,
        "input_hashes": {path: digest(Path(path)) for path in input_files},
        "deferred_input_bindings": {
            "source_hdf5": deferred(CONVERSION_ROOT / "trajectory.h5", "terminal quarter trajectory H5"),
            "conversion_report": deferred(CONVERSION_ROOT / "direct-conversion-report.json", "terminal quarter conversion report"),
            "conversion_receipt": deferred(CONVERSION_ROOT / "execution-receipt.json", "terminal quarter conversion receipt"),
        },
        "expected_native": {"dimension": 3, "fluid_particles": FLUID_PARTICLES, "total_particles": TOTAL_PARTICLES, "saved_frames": EXPECTED_FRAMES, "window_s": WINDOW_S, "coordinate_frame": "DualSPHysics case Cartesian coordinates (x,y,z)"},
        "source_hdf5_binding_policy": "bind H5/report/receipt SHA and completed status from actual conversion before dispatch; runner must not infer Q-I from labels status",
        "fixed_window_contract": {"window_s": WINDOW_S, "save_interval_s": SAVE_INTERVAL_S, "events": ["left_right_exchange", "front_back_exchange", "top_open_exit"], "unknown_censored_preserved": True},
        "physical_binding_sha256": PHYSICAL_BINDING_SHA,
        "owner_metadata": str(owner_path),
        "direct_conversion_request": str(conversion_path),
        "qualification_claim": "none; deferred labels request",
        "q_n_status": "not_assessed",
        "production_status": "not_accepted",
    }


def comparison_request(labels_path: Path, labels_value: dict[str, Any], owner_path: Path, bindings: dict[str, dict[str, Any]]) -> dict[str, Any]:
    input_paths = [TRANSPORT_COMPARE, TRANSPORT_CONFIG, OPERATORS, TEMPORAL_ASSESSMENT, HALF_COMPARISON_REQUEST, HALF_LABEL_REQUEST, HALF_LABELS, labels_path, owner_path]
    input_files = [str(require(path, "comparison input")) for path in input_paths]
    half_label = bindings["half_labels"]
    return {
        "schema": "ds02.runner-request.v2",
        "family_id": "F3",
        "case_id": f"{PHYSICAL_CASE_ID}_QUARTER_VS_HALF_DT",
        "physical_case_id": PHYSICAL_CASE_ID,
        "attempt_id": COMPARISON_ATTEMPT_ID,
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 2,
        "max_wall_seconds": 1200,
        "estimated_storage_bytes": 512 * 1024**2,
        "status": "deferred_until_quarter_labels_terminal",
        "runnable": False,
        "launch_allowed": False,
        "root_only": True,
        "command": [
            str(PYTHON), str(TRANSPORT_COMPARE),
            "--baseline", str(HALF_LABELS),
            "--variant", str(LABEL_ROOT / "typed-transport-labels.h5"),
            "--particle-chunk", "65536",
            "--output", "{attempt_root}/quarter-vs-half-transport-comparison.json",
        ],
        "cwd": str(INTEGRATION_ROOT / "lagrangian-fluid-lab"),
        "worktree_root": str(WORKTREE_ROOT),
        "input_files": input_files,
        "input_hashes": {path: digest(Path(path)) for path in input_files if Path(path).is_file()},
        "baseline_label_binding": half_label,
        "quarter_label_binding": deferred(LABEL_ROOT / "typed-transport-labels.h5", "terminal quarter native labels H5"),
        "fixed_window_s": WINDOW_S,
        "physical_binding_sha256": PHYSICAL_BINDING_SHA,
        "budget_contract": {
            "macro_relative": 0.05,
            "event_time_relative": 0.02,
            "save_or_integration_share": 0.20,
            "derived_save_or_integration_fraction_of_event_time": 0.004,
            "residence_time_budget_registered": False,
            "status": "not_assessed",
            "source_assessment": binding(TEMPORAL_ASSESSMENT, "frozen temporal budget assessment"),
        },
        "operators": {"events": ["left_right_exchange", "front_back_exchange", "top_open_exit"], "unknown_censoring": "retain censored identities; never infer physical exit"},
        "owner_metadata": str(owner_path),
        "comparison_role": "quarter integration sensitivity at same 0.0025 s save cadence against completed HALF_DT labels",
        "qualification_claim": "none; comparison request only",
        "q_n_status": "not_assessed",
        "production_status": "not_accepted",
    }


def build(output_root: Path = HANDOFF_ROOT) -> dict[str, Any]:
    output_root = Path(output_root).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    bindings = source_bindings()
    timeline = runparts_summary(QUARTER_RUNPARTS)
    if timeline["rows"] != EXPECTED_FRAMES or not timeline["full_window_completed"]:
        raise ValueError(f"quarter timeline is not complete: {timeline}")
    if any(timeline[key] != 0 for key in ("NpOut_sum", "NpOutPos_sum", "NpOutRho_sum", "NpOutMov_sum")):
        raise ValueError(f"quarter native exclusion ledger is nonzero: {timeline}")
    projection = physical_projection(QUARTER_XML)
    if projection != physical_projection(HALF_XML):
        raise ValueError("quarter and HALF_DT physical XML projections differ")

    owner_path = output_root / "F3_DUAL_AXIS_WEAK_006G_004G_QUARTER_DT.owner.v1-deferred.json"
    owner = owner_payload(bindings, timeline, projection)
    owner_path.write_text(json.dumps(owner, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    conversion_path = output_root / "quarter_dt_conversion_request_v1.json"
    conversion = conversion_request(owner_path, bindings, timeline)
    conversion_path.write_text(json.dumps(conversion, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    labels_path = output_root / "quarter_dt_labels_request_v1_deferred.json"
    labels = labels_request(owner_path, conversion_path, bindings)
    labels_path.write_text(json.dumps(labels, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    comparison_path = output_root / "quarter_vs_half_comparison_request_v1_deferred.json"
    comparison = comparison_request(labels_path, labels, owner_path, bindings)
    comparison_path.write_text(json.dumps(comparison, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    manifest = {
        "schema": SCHEMA,
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "family_id": "F3",
        "case_id": CASE_ID,
        "physical_case_id": PHYSICAL_CASE_ID,
        "physical_binding_sha256": PHYSICAL_BINDING_SHA,
        "study_role": "quarter_dt_same_save",
        "actual_solver_evidence": {"receipt": bindings["quarter_solver_receipt"], "runparts": bindings["quarter_runparts"], "timeline": timeline},
        "source_bindings": bindings,
        "files": {
            "owner": binding(owner_path, "quarter deferred owner"),
            "conversion_request": binding(conversion_path, "quarter root-only conversion request"),
            "labels_request": binding(labels_path, "quarter deferred labels request"),
            "comparison_request": binding(comparison_path, "quarter-vs-HALF_DT deferred comparison request"),
        },
        "launch_policy": {"solver": False, "gpu": False, "conversion": False, "labels": False, "root_binds_terminal_hashes_before_dispatch": True},
        "qualification_claim": "none",
        "q_n_status": "not_assessed",
        "production_status": "not_accepted",
    }
    manifest_path = output_root / "quarter_dt_postprocess_manifest_v1.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"manifest": str(manifest_path), "owner": str(owner_path), "conversion": str(conversion_path), "labels": str(labels_path), "comparison": str(comparison_path), "timeline": timeline}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=HANDOFF_ROOT)
    args = parser.parse_args()
    result = build(args.output_root)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
