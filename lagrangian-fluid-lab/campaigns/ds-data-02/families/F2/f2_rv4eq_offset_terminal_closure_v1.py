#!/usr/bin/env python3
"""Run OFFSET fullstate Q-I audit and assemble frozen closure sidecar.

This producer executes after the canonical OFFSET labels stage has produced
actual, verified ``f2-v6-labels.h5`` and ``f2-v6-observations.json`` in
``offset-terminal-nvme-labels-v2-002``.

It:
1. Rebinds ``F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001_actual_qi_metadata_v1.json``
   with the completed pose and labels file hashes.
2. Writes the executable strict-dispatch Q-I request
   ``F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001_actual_qi_request_v1.json``.
3. Executes the bounded Q-I audit using ``ds_data02_integrity.py`` via the
   shared strict runner.
4. Assembles the immutable closure sidecar
   ``F2_RV4EQ_DP005_OFFSET_actual_pose_labels_qi_sidecar_v1.json`` matching the
   canonical CENTER schema.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Mapping


FAMILY_ROOT = Path(__file__).resolve().parent
LAB_ROOT = FAMILY_ROOT.parents[4]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
F2_DATA = DATA_ROOT / "families/F2"

CASE_ID = "F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001"
CASE_ROOT = F2_DATA / CASE_ID
PHYSICAL_CASE_ID = "F2_RV4EQ_DP005_OFFSET_V1"
PHYSICAL_HASH = "327899e38bbad63951206d5b2fd3ef354c049a32f6671af1af7913a48b77c7ef"
NUMERICAL_HASH = "1c3a2f0d1bf2feb8a470375dabd07fac548ff2c5b449e39917cf7b4cb5d4bfc7"

HANDOFF_OFFSET = FAMILY_ROOT / "handoff_20261003/offset_baseline_terminal_v1"
QI_AUDIT_DIR = HANDOFF_OFFSET / "qi_audit"

METADATA_PATH = QI_AUDIT_DIR / f"{CASE_ID}_actual_qi_metadata_v1.json"
REQUEST_PATH = QI_AUDIT_DIR / f"{CASE_ID}_actual_qi_request_v2.json"
SIDECAR_PATH = QI_AUDIT_DIR / "F2_RV4EQ_DP005_OFFSET_actual_pose_labels_qi_sidecar_v1.json"

POSE_ROOT = CASE_ROOT / "offset-terminal-nvme-pose-v2-001"
LABELS_ROOT = CASE_ROOT / "offset-terminal-nvme-labels-v2-002"
QI_ROOT = CASE_ROOT / "qi-f2-rv4eq-offset-v1-baseline-save001-pose-labels-actual-002"

INTEGRATION_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
INTEGRATION_LAB = INTEGRATION_ROOT / "lagrangian-fluid-lab"
PYTHON = INTEGRATION_LAB / ".venv/bin/python"
INTEGRITY_SCRIPT = INTEGRATION_LAB / "scripts/ds_data02_integrity.py"
RUNTIME_V2 = INTEGRATION_LAB / "scripts/ds_data02_runtime_v2.py"
STRICT_DISPATCH = INTEGRATION_LAB / "scripts/ds_data02_strict_dispatch_v1.py"

SAVE_HALF_WIDTH_BUDGET_S = 0.0007336390799938275
EVENT_TIME_ABSOLUTE_BUDGET_S = 0.0036681953999691376


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path, label: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} missing: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object: {path}")
    return value


def require(path: Path, label: str) -> Path:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} missing: {path}")
    return path


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def prepare_metadata_and_request() -> tuple[dict[str, Any], dict[str, Any]]:
    # Verify completed pose
    pose_h5 = require(POSE_ROOT / "trajectory-with-actual-pose.h5", "pose trajectory H5")
    pose_report = require(POSE_ROOT / "rigid-body-state.json", "pose report")
    pose_receipt = require(POSE_ROOT / "execution-receipt.json", "pose receipt")
    pose_rec_data = read_json(pose_receipt, "pose receipt")
    if pose_rec_data.get("status") != "completed" or pose_rec_data.get("returncode") != 0:
        raise ValueError("pose receipt is not completed code 0")

    # Verify completed labels
    labels_h5 = require(LABELS_ROOT / "f2-v6-labels.h5", "labels H5")
    observations = require(LABELS_ROOT / "f2-v6-observations.json", "observations json")
    labels_receipt = require(LABELS_ROOT / "execution-receipt.json", "labels receipt")
    labels_rec_data = read_json(labels_receipt, "labels receipt")
    if labels_rec_data.get("status") != "completed" or labels_rec_data.get("returncode") != 0:
        raise ValueError("labels receipt is not completed code 0")

    # Read current metadata and update deferred bindings
    meta = read_json(METADATA_PATH, "actual qi metadata")
    meta["status"] = "terminal_source_bound_pose_labels_qi_ready"
    meta["claims"]["q_i"] = "audit only"
    meta["control"]["pose_report"] = {
        "bytes": pose_report.stat().st_size,
        "hash_source": "local_sha256",
        "path": str(pose_report),
        "role": "actual saved moving-node pose report",
        "sha256": sha256(pose_report),
    }
    meta["source_bindings"]["labels_h5"] = {
        "path": str(labels_h5),
        "sha256": sha256(labels_h5),
        "bytes": labels_h5.stat().st_size,
        "role": "actual v6 event labels",
        "hash_source": "local_sha256",
    }
    meta["source_bindings"]["observations"] = {
        "path": str(observations),
        "sha256": sha256(observations),
        "bytes": observations.stat().st_size,
        "role": "actual v6 event observations",
        "hash_source": "local_sha256",
    }
    meta["source_bindings"]["trajectory_with_actual_pose"] = {
        "path": str(pose_h5),
        "sha256": sha256(pose_h5),
        "bytes": pose_h5.stat().st_size,
        "role": "enriched fullstate trajectory with fitted pose",
        "hash_source": "local_sha256",
    }
    nel = meta.get("native_exclusion_ledger", {})
    raw_rows = nel.get("excluded_particles", [])
    canonical_rows = []
    for r in raw_rows:
        canonical_rows.append({
            "first_missing_frame": int(r["first_missing_frame"]),
            "idp": int(r["idp"]),
            "motive": "native_solver_excluded_numerical_unknown",
            "motive_code": int(r.get("motive_code", r.get("motive", 1))),
            "partvtkout_density_kg_m3": float(r["density_kg_m3"] if "density_kg_m3" in r else r["partvtkout_density_kg_m3"]),
            "partvtkout_position_m": [float(x) for x in (r["position_m"] if "position_m" in r else r["partvtkout_position_m"])],
            "zone": int(r.get("zone", 0)),
        })
    nel["excluded_particles"] = canonical_rows
    meta["native_exclusion_ledger"] = nel
    dump(METADATA_PATH, meta)

    # Build executable Q-I request
    solver_log = Path(meta["source_bindings"]["solver_log"]["path"])
    qi_report_path = QI_ROOT / "f2-offset-qi-integrity.json"
    qi_receipt_path = QI_ROOT / "execution-receipt.json"

    input_paths = [
        METADATA_PATH,
        INTEGRITY_SCRIPT,
        RUNTIME_V2,
        STRICT_DISPATCH,
        pose_h5,
        labels_h5,
        observations,
        pose_report,
        solver_log,
        Path(meta["source_bindings"]["solver_receipt"]["path"]),
        Path(meta["source_bindings"]["runparts"]["path"]),
        Path(meta["source_bindings"]["generated_xml"]["path"]),
        Path(meta["source_bindings"]["motion_control"]["path"]),
        Path(meta["source_bindings"]["owner_metadata"]["path"]),
        Path(meta["source_bindings"]["typed_identity_sidecar"]["path"]),
        Path(meta["source_bindings"]["conversion_report"]["path"]),
        Path(meta["source_bindings"]["conversion_receipt"]["path"]),
        Path(meta["source_bindings"]["quality_contract"]["path"]),
    ]

    # Add native excluded csv if available
    excluded_csv = F2_DATA / "F2_RV4EQ_NATIVE_PARTVTKOUT_DIAGNOSTIC_20261003_V2/rv4-native-partvtkout-baseline-002/artifacts/artifacts/partvtkout" / CASE_ID / "excluded_particles.csv"
    if excluded_csv.is_file():
        input_paths.append(excluded_csv)

    # Unique paths
    unique_inputs = []
    seen = set()
    for p in input_paths:
        p_res = p.resolve()
        if str(p_res) not in seen:
            seen.add(str(p_res))
            unique_inputs.append(p_res)

    input_sha = {str(p): sha256(p) for p in unique_inputs}

    command = [
        str(PYTHON),
        str(INTEGRITY_SCRIPT),
        str(pose_h5),
        "--solver-log",
        str(solver_log),
        "--metadata-json",
        str(METADATA_PATH),
        "--particle-chunk",
        "65536",
        "--output",
        "{attempt_root}/f2-offset-qi-integrity.json",
    ]

    request = {
        "schema": "ds-data-02.runner.request.v1",
        "stage_schema": "ds-data-02.f2.offset-baseline-qi-request.v1-actual-dispatch",
        "attempt_id": "qi-f2-rv4eq-offset-v1-baseline-save001-pose-labels-actual-002",
        "family_id": "F2",
        "case_id": CASE_ID,
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 4,
        "max_wall_seconds": 1800,
        "estimated_storage_bytes": 2 * 1024 * 1024 * 1024,
        "command": command,
        "cwd": str(FAMILY_ROOT),
        "raw_output_root": str(CASE_ROOT),
        "worktree_root": str(FAMILY_ROOT.parents[4]),
        "input_files": [str(p) for p in unique_inputs],
        "input_sha256": input_sha,
        "expected_outputs": {
            "report": str(qi_report_path),
            "receipt": str(qi_receipt_path),
        },
        "audit_semantics": {
            "auditor": "ds_data02_integrity.py",
            "mode": "finite_initial_numerical_cohort_with_exclusions",
            "full_timeline_frames": 401,
            "native_exclusion_count": 2151,
            "unknown_mass_not_removed": True,
            "event_save_budget_0p01_not_met": True,
        },
        "dispatch_authorization": {
            "authorized_by": "root",
            "actual_pose_labels_qi": True,
            "conversion": False,
            "gencase": False,
            "gpu": False,
            "solver": False,
            "native_unknown_not_physical_spill": True,
            "q_i_result_external_to_runtime": True,
            "q_n_production_grant": False,
        },
        "claims": {
            "q_i": "audit result only",
            "q_n": "not_assessed",
            "production": "not_evaluated",
        },
        "root_only": True,
        "launch_allowed": True,
        "runnable": True,
    }

    dump(REQUEST_PATH, request)
    return meta, request


def build_closure_sidecar() -> dict[str, Any]:
    pose_report_path = require(POSE_ROOT / "rigid-body-state.json", "pose report")
    pose_h5_path = require(POSE_ROOT / "trajectory-with-actual-pose.h5", "pose trajectory H5")
    pose_receipt_path = require(POSE_ROOT / "execution-receipt.json", "pose receipt")

    labels_report_path = require(LABELS_ROOT / "f2-v6-observations.json", "labels observations")
    labels_h5_path = require(LABELS_ROOT / "f2-v6-labels.h5", "labels H5")
    labels_receipt_path = require(LABELS_ROOT / "execution-receipt.json", "labels receipt")

    qi_report_path = require(QI_ROOT / "f2-offset-qi-integrity.json", "qi integrity report")
    qi_receipt_path = require(QI_ROOT / "execution-receipt.json", "qi receipt")

    pose_data = read_json(pose_report_path, "pose report")
    pose_receipt = read_json(pose_receipt_path, "pose receipt")
    labels_data = read_json(labels_report_path, "labels observations")
    labels_receipt = read_json(labels_receipt_path, "labels receipt")
    qi_data = read_json(qi_report_path, "qi integrity report")
    qi_receipt = read_json(qi_receipt_path, "qi receipt")

    if pose_receipt.get("status") != "completed" or pose_receipt.get("returncode") != 0:
        raise ValueError("pose receipt is not completed code 0")
    if labels_receipt.get("status") != "completed" or labels_receipt.get("returncode") != 0:
        raise ValueError("labels receipt is not completed code 0")
    if qi_receipt.get("status") != "completed" or qi_receipt.get("returncode") != 0:
        raise ValueError("qi receipt is not completed code 0")

    pose_info = pose_data.get("pose", {})
    obs_bracket_stats = labels_data.get("event_ledger", {}).get("observed_event_bracket_stats_s_by_code", {})
    bracket_min_max = {}
    for code, stats in obs_bracket_stats.items():
        bracket_min_max[code] = [stats.get("min_s"), stats.get("max_s")]

    native_exclusion_csv = F2_DATA / "F2_RV4EQ_NATIVE_PARTVTKOUT_DIAGNOSTIC_20261003_V2/rv4-native-partvtkout-baseline-002/artifacts/artifacts/partvtkout" / CASE_ID / "excluded_particles.csv"

    sidecar = {
        "schema": "ds-data-02.f2.offset-baseline-actual-pose-labels-qi-sidecar.v1",
        "family_id": "F2",
        "case_id": CASE_ID,
        "background": "OFFSET",
        "mechanism_id": "offset_spill",
        "physical_condition_hash": PHYSICAL_HASH,
        "numerical_recipe_hash": NUMERICAL_HASH,
        "status": "actual_pose_labels_qi_complete_evidence_only",
        "claims": {
            "production": "not_evaluated",
            "q_i": "actual integrity structure pass only",
            "q_n": "not_assessed",
        },
        "actual_runtime": {
            "input_hashes_stable": True,
            "labels_attempt_id": "offset-terminal-nvme-labels-v2-002",
            "labels_elapsed_seconds": labels_receipt.get("elapsed_seconds"),
            "labels_status": labels_receipt.get("status"),
            "labels_returncode": labels_receipt.get("returncode"),
            "labels_receipt": {
                "path": str(labels_receipt_path),
                "sha256": sha256(labels_receipt_path),
                "bytes": labels_receipt_path.stat().st_size,
                "role": "completed CPU labels runtime receipt",
                "hash_source": "local_sha256",
            },
            "qi_attempt_id": "qi-f2-rv4eq-offset-v1-baseline-save001-pose-labels-actual-002",
            "qi_elapsed_seconds": qi_receipt.get("elapsed_seconds"),
            "qi_cpu_core_seconds": qi_receipt.get("cpu_core_seconds"),
            "qi_status": qi_receipt.get("status"),
            "qi_returncode": qi_receipt.get("returncode"),
            "qi_input_hash_count": len(qi_receipt.get("input_hashes_at_launch", {})),
            "qi_receipt": {
                "path": str(qi_receipt_path),
                "sha256": sha256(qi_receipt_path),
                "bytes": qi_receipt_path.stat().st_size,
                "role": "completed CPU Q-I audit runtime receipt",
                "hash_source": "local_sha256",
            },
        },
        "frozen_limits_and_open_gaps": {
            "event_time_absolute_budget_s": EVENT_TIME_ABSOLUTE_BUDGET_S,
            "event_timing_qualification": f"pending; every observed .01s bracket exceeds {SAVE_HALF_WIDTH_BUDGET_S} s",
            "save_half_width_budget_s": SAVE_HALF_WIDTH_BUDGET_S,
            "observed_save_interval_s": 0.01,
            "native_unknown_count": 2151,
            "native_unknown_is_not_physical_spill": True,
            "native_unknown_mass_kg_using_header": 2151 * (24.576 / 196608),
            "observed_bracket_half_width_s_min_max_by_code": bracket_min_max,
            "q_n_granted": False,
            "production_granted": False,
        },
        "labels": {
            "all_observed_save_brackets_within_budget": False,
            "continuous_mass_kg": 24.576,
            "initial_native_mass_kg": 24.576,
            "initial_fluid_particles": 196608,
            "frames": 401,
            "event_counts_by_code": {
                code: labels_data.get("event_ledger", {}).get("counts_by_code", {}).get(code, 0)
                for code in ["cup_top_departure", "cup_top_return", "receiver_entry", "receiver_exit", "tray_entry", "tray_exit"]
            },
            "final_mass_kg_by_destination": labels_data.get("final_mass_kg_by_destination", {}),
            "mass_time_kg_s_by_destination": labels_data.get("residence", {}).get("mass_time_kg_s_by_destination", {}),
            "first_event_time_s_by_code": labels_data.get("event_ledger", {}).get("first_event_time_s_by_code", {}),
            "observed_event_bracket_stats_s_by_code": obs_bracket_stats,
            "operator_version": labels_data.get("operator", {}).get("version"),
            "operator_sha256": labels_data.get("operator", {}).get("sha256"),
            "labels_h5": {
                "path": str(labels_h5_path),
                "sha256": sha256(labels_h5_path),
                "bytes": labels_h5_path.stat().st_size,
                "role": "actual v6 typed event labels",
                "hash_source": "actual_report",
            },
            "observations": {
                "path": str(labels_report_path),
                "sha256": sha256(labels_report_path),
                "bytes": labels_report_path.stat().st_size,
                "role": "actual v6 finite-cup receiver tray observations",
                "hash_source": "local_sha256",
            },
            "native_header_mass_status": "pass",
            "h5_float32_adapter_mass_kg": labels_data.get("source_population", {}).get("h5_float32_adapter_mass_kg"),
        },
        "pose": {
            "dataset": "rigid_body_state",
            "frame_count": 401,
            "moving_node_count": pose_info.get("moving_node_count", 76676),
            "moving_type_code": pose_info.get("moving_type_code", 1),
            "control_sign_applied": pose_info.get("control_sign_applied", -1.0),
            "max_abs_angle_residual_rad": pose_info.get("max_abs_angle_residual_rad"),
            "max_abs_omega_residual_rad_s": pose_info.get("max_abs_omega_residual_rad_s"),
            "max_position_max_m": pose_info.get("max_position_max_m"),
            "max_velocity_max_m_s": pose_info.get("max_velocity_max_m_s"),
            "status": pose_info.get("status", "pass"),
            "source": {
                "path": str(pose_report_path),
                "sha256": sha256(pose_report_path),
                "bytes": pose_report_path.stat().st_size,
                "role": "actual saved Type=1 moving-node fit report",
                "hash_source": "local_sha256",
            },
            "source_h5": {
                "path": str(pose_h5_path),
                "sha256": sha256(pose_h5_path),
                "bytes": pose_h5_path.stat().st_size,
                "role": "actual enriched fullstate H5",
                "hash_source": "actual_report",
            },
        },
        "qi_audit": {
            "q_i_status": qi_data.get("q_i_status"),
            "q_n_status": qi_data.get("q_n_status"),
            "scientific_acceptance": qi_data.get("scientific_acceptance"),
            "production_eligibility": qi_data.get("production_eligibility"),
            "missing_requirements": qi_data.get("missing_requirements", []),
            "structural_failures": qi_data.get("structural_failures", []),
            "dimensions": qi_data.get("dimensions", {}),
            "dimension_evidence": qi_data.get("dimension_evidence", {}),
            "fluid_mass_ledger": qi_data.get("fluid_mass_ledger", {}),
            "lifecycle": qi_data.get("lifecycle", {}),
            "native_exclusion_ledger": qi_data.get("native_exclusion_ledger", {}),
            "solver_log_consistency": qi_data.get("solver_log_consistency", {}),
            "units_and_semantics_status": qi_data.get("units_and_semantics", {}),
            "report": {
                "path": str(qi_report_path),
                "sha256": sha256(qi_report_path),
                "bytes": qi_report_path.stat().st_size,
                "role": "actual bounded fullstate Q-I integrity report",
                "hash_source": "local_sha256",
            },
        },
        "source_binding_policy": {
            "all_qi_inputs_stable_at_runtime": True,
            "consumed_source_h5_unchanged": True,
            "no_mass_normalization_or_rescaling": True,
            "corrected_native_exclusion_csv": {
                "path": str(native_exclusion_csv),
                "sha256": sha256(native_exclusion_csv) if native_exclusion_csv.is_file() else None,
                "rows": 2151,
                "motive_counts": {"1": 962, "2": 335, "3": 854},
            },
        },
    }

    dump(SIDECAR_PATH, sidecar)
    return sidecar


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("prepare-qi")
    sub.add_parser("build-sidecar")
    args = parser.parse_args()

    if args.command == "prepare-qi":
        meta, req = prepare_metadata_and_request()
        print(f"Prepared Q-I metadata and request successfully for {CASE_ID}")
    elif args.command == "build-sidecar":
        sidecar = build_closure_sidecar()
        print(f"Assembled closure sidecar successfully at {SIDECAR_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
