#!/usr/bin/env python3
"""Prepare the bounded F7-S2 half-CFL native observer chain.

This module is a forward-only preparation entry point for the completed F7-S2
half-CFL NVMe run.  It writes a launch-disabled observer template and a
parent-guarded v2 selected-source snapshot request.  After the parent has
hashed the nine deferred ``Part_*.bi4`` files, the same entry point can bind
that immutable snapshot to an enforcer-v2 observer request.

The builder reads only small provenance files (RunPARTs, XML, receipts,
owner, motion and manifests).  It never opens, stats, or hashes a BI4 file.
The snapshot worker is the only stage that hashes the nine selected native
files, and the observer enforcer performs the pre/post complete-stat check
around the bounded decoder child.  No solver is launched here and no HDF5 is
read.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
from typing import Any


REQUEST_SCHEMA = "ds02.request.v1"
SNAPSHOT_SCHEMA = "ds02.stage2.native-source-snapshot.v2"
MANIFEST_SCHEMA = "ds02.stage2.native-observer-source-manifest.v1"
REPO = Path(__file__).resolve().parents[5]
REFERENCE = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
REQUEST_ROOT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
OBSERVER = REFERENCE / "stage2_native_physical_observer_v2.py"
ENFORCER = REFERENCE / "stage2_native_physical_observer_enforcer_v2.py"
SNAPSHOT_WORKER = REFERENCE / "stage2_native_source_snapshot_v2.py"
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
DECODER_SOURCE = REPO / "lagrangian-fluid-lab/scripts/native/bi4_dump.cpp"
MAIN = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
V8_RUNNER = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"
V8_STRICT = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"
V8_RUNTIME = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
V6_RUNTIME = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v6.py"
V2_RUNTIME = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"

REQUEST_DIR = REQUEST_ROOT / "stage2-f7-s2-half-native-observer-v1"
TEMPLATE = REQUEST_DIR / "f7_s2_a065_half_cfl_selected_native_observer_template_v1.json"
SNAPSHOT_REQUEST = REQUEST_DIR / "f7_s2_a065_half_cfl_selected_native_source_snapshot_v1.json"

FAMILY = "F7"
SENTINEL = "F7-S2"
PHYSICAL_CASE = "F7_OBSTACLE_QUINTIC_B08_A065"
SNAPSHOT_CASE = "F7_S2_A065_HALF_CFL_SELECTED_NATIVE_SOURCE_SNAPSHOT_V1"
SNAPSHOT_ATTEMPT = "f7-s2-a065-half-cfl-selected-native-source-snapshot-v1-root-001"
OBSERVER_CASE = "F7_S2_A065_HALF_CFL_SELECTED_NATIVE_OBSERVER_V1"
OBSERVER_ATTEMPT = "f7-s2-a065-half-cfl-selected-native-observer-v1-root-001"

ACTUAL_RECEIPT = DATA_ROOT / "families/F7/f7-obstacle-quintic-b08-a065/f7-s2-a065-half-cfl-savedt-v7-001-root-forward-001/execution-receipt.json"
RAW_ROOT = Path("/var/tmp/ds02-stage2/F7/F7_S2_HALF_CFL_SAVEDT_V7/f7-s2-a065-half-cfl-savedt-v7-001-root-forward-001/solver_output/data")
RUNPARTS = Path("/var/tmp/ds02-stage2/F7/F7_S2_HALF_CFL_SAVEDT_V7/f7-s2-a065-half-cfl-savedt-v7-001-root-forward-001/solver_output/RunPARTs.csv")
ACTUAL_REQUEST = MAIN / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/native-reconstruction/f7-half-cfl-v7-root-prepared-001/f7-s2-half-cfl-solver-v6-root-forward-001.json"
CURRENT_XML = DATA_ROOT / "families/F7/F7_OBSTACLE_QUINTIC_B08_A065/root-stage1-f7-angle065-genuine-gencase-085/prepared/F7_OBSTACLE_QUINTIC_B08_A065.xml"
GENCASE_RECEIPT = DATA_ROOT / "families/F7/F7_OBSTACLE_QUINTIC_B08_A065/f7-half-cfl-gencase-v8-001-root-001/execution-receipt.json"
OWNER = Path("/home/jade/.codex/worktrees/ds-data-02-f7/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F7/handoff_20261003/root_followup_064_stage1_target_angle_full601_native099_nvme_typed_v1/owners/F7_OBSTACLE_QUINTIC_B08_A065.owner.json")
OVERLAY_DIR = REFERENCE / "stage2_savedt_cfl_pair_inputs_v1/F7_S2/half_cfl"
GENERATED_XML = DATA_ROOT / "families/F7/F7_OBSTACLE_QUINTIC_B08_A065/f7-half-cfl-gencase-v8-001-root-001/prepared/F7_OBSTACLE_QUINTIC_B08_A065_half_cfl01.xml"
OVERLAY_MANIFEST = OVERLAY_DIR / "overlay-manifest.json"
MOTION = OVERLAY_DIR / "motion_obstacle_quintic.dat"

QUERY_TIMES = [0.0, 3.0, 6.0, 9.0, 12.0]
EXPECTED_FRAMES = [0, 299, 300, 599, 600, 899, 900, 1199, 1200]
PART_RE = re.compile(r"^Part_(\d+)\.bi4$")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular non-symlink file: {path}")
    return path


def record(path: Path, label: str) -> dict[str, Any]:
    path = regular(path, label)
    stat = path.stat()
    return {
        "path": str(path),
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "sha256": sha256(path),
    }


def atomic_json(path: Path, value: Any) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refuse to overwrite immutable artifact: {path}")
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def load_object(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(regular(path, label).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} is not a JSON object: {path}")
    return value


def parse_int(value: str) -> int:
    return int(value.strip().replace(",", ""))


def read_runparts(path: Path) -> list[dict[str, Any]]:
    """Read only the small saved-window summary, never a native Part file."""

    rows: list[dict[str, Any]] = []
    with regular(path, "RunPARTs") .open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        for raw in reader:
            if not raw or not raw.get("Part"):
                continue
            # RunPARTs appends human-readable ``# ...`` documentation after
            # the numeric table.  It is metadata, not a malformed numeric
            # row, and must not be allowed to change the registered frame
            # count.
            try:
                frame = parse_int(raw["Part"])
            except (TypeError, ValueError):
                continue
            rows.append(
                {
                    "frame": frame,
                    "time_s": float(raw["TimeStep [s]"]),
                    "steps": parse_int(raw["Steps"]),
                    "dtsmin_count": parse_int(raw["DTsMin"]),
                    "dtmin_s": float(raw["DtMin [s]"]),
                    "dtmax_s": float(raw["DtMax [s]"]),
                    "np_save": parse_int(raw["NpSave"]),
                    "np_fluid": parse_int(raw["NpfSim"]),
                    "np_fixed": parse_int(raw["NpbSim"]),
                }
            )
    if not rows or [row["frame"] for row in rows] != list(range(len(rows))):
        raise ValueError("RunPARTs frames are not a contiguous zero-based sequence")
    return rows


def bracket(rows: list[dict[str, Any]], query: float) -> dict[str, Any]:
    if not math.isfinite(query):
        raise ValueError(f"non-finite query time: {query}")
    if query < rows[0]["time_s"] or query > rows[-1]["time_s"]:
        raise ValueError(f"query {query} is outside saved window")
    if abs(query - rows[0]["time_s"]) <= 1e-10:
        row = rows[0]
        return {
            "query_time_s": query,
            "status": "EXACT_OR_LEFT",
            "lower_frame": 0,
            "upper_frame": 0,
            "lower_time_s": row["time_s"],
            "upper_time_s": row["time_s"],
            "field_interpolation": "NOT_PERFORMED_BY_WORKER",
        }
    for right in range(1, len(rows)):
        if rows[right]["time_s"] >= query:
            left = right - 1
            if abs(rows[right]["time_s"] - query) <= 1e-10:
                return {
                    "query_time_s": query,
                    "status": "EXACT",
                    "lower_frame": right,
                    "upper_frame": right,
                    "lower_time_s": rows[right]["time_s"],
                    "upper_time_s": rows[right]["time_s"],
                    "field_interpolation": "NOT_PERFORMED_BY_WORKER",
                }
            denominator = rows[right]["time_s"] - rows[left]["time_s"]
            return {
                "query_time_s": query,
                "status": "BRACKETED",
                "lower_frame": left,
                "upper_frame": right,
                "lower_time_s": rows[left]["time_s"],
                "upper_time_s": rows[right]["time_s"],
                "bracket_fraction": (query - rows[left]["time_s"]) / denominator,
                "field_interpolation": "NOT_PERFORMED_BY_WORKER",
            }
    raise AssertionError("query bracket search did not terminate")


def runparts_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "row_count": len(rows),
        "first_frame": rows[0]["frame"],
        "last_frame": rows[-1]["frame"],
        "first_saved_time_s": rows[0]["time_s"],
        "last_saved_time_s": rows[-1]["time_s"],
        "sum_saved_window_steps": sum(row["steps"] for row in rows),
        "sum_DTsMin_count": sum(row["dtsmin_count"] for row in rows),
        "positive_saved_window_dt_min_s": min(row["dtmin_s"] for row in rows[1:] if row["dtmin_s"] > 0),
        "positive_saved_window_dt_max_s": max(row["dtmax_s"] for row in rows[1:] if row["dtmax_s"] > 0),
        "np_save_values": sorted({row["np_save"] for row in rows}),
        "np_fluid_values": sorted({row["np_fluid"] for row in rows}),
        "np_fixed_values": sorted({row["np_fixed"] for row in rows}),
        "scope": "RunPARTs saved-window summary only; not a complete per-step dt trace",
    }


def calibration_contract() -> dict[str, Any]:
    return {
        "schema": "ds02.stage2.observer-calibration-contract.v2",
        "status": "PRE_REGISTERED_BEFORE_FIELD_DIFFERENCES",
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "position": {
            "relative_tolerance_fraction_of_characteristic_length": 0.02,
            "characteristic_length_source": "owner physical geometry/evaluator registration; scalar L not inferred by this worker",
        },
        "event_neighborhood": {
            "relative_tolerance_fraction_of_local_length": 0.05,
            "event_time_characteristic_s": "UNKNOWN_PENDING_CONSUMER_REGISTRATION",
        },
        "velocity": {"relative_tolerance_fraction_of_nonzero_scale": 0.05},
        "kinetic_energy": {"relative_tolerance_fraction_of_nonzero_scale": 0.05},
        "whole_initial_fluid_mass": {
            "fractional_budget": 0.03,
            "basis": "owner canonical continuum/source ledger; native particle sample mass remains a separate diagnostic",
        },
        "task_budget_shares": {
            "time": {"maximum_fraction_of_task_error_budget": 0.25, "meaning": "budget share, not a result pass gate"},
            "output": {"maximum_fraction_of_task_error_budget": 0.25, "meaning": "budget share, not a result pass gate"},
        },
        "alignment": {
            "query_times_s": QUERY_TIMES,
            "bracketed_queries_keep_actual_lower_upper_times": True,
            "particle_field_interpolation": "FORBIDDEN_BY_WORKER",
            "out_of_window": "UNKNOWN_NO_EXTRAPOLATION",
        },
    }


def source_paths() -> dict[str, Path]:
    return {
        "actual_half_v7_solver_receipt": ACTUAL_RECEIPT,
        "actual_half_v7_solver_request": ACTUAL_REQUEST,
        "runparts": RUNPARTS,
        "generated_xml": GENERATED_XML,
        "current_xml": CURRENT_XML,
        "source_gencase_receipt": GENCASE_RECEIPT,
        "source_owner": OWNER,
        "overlay_manifest": OVERLAY_MANIFEST,
        "motion": MOTION,
    }


def owner_summary(owner: dict[str, Any]) -> dict[str, Any]:
    recipe = owner.get("native_recipe", {})
    physical = owner.get("physical_binding", {})
    initial = physical.get("initial_state", {}) if isinstance(physical, dict) else {}
    return {
        "schema": owner.get("schema"),
        "case_id": owner.get("case_id"),
        "family_id": owner.get("family_id"),
        "physical_case_id": owner.get("physical_case_id"),
        "condition_id": owner.get("condition_id"),
        "condition_hash_semantics": owner.get("condition_hash_semantics"),
        "canonical_physical_binding_sha256": owner.get("canonical_physical_binding_sha256"),
        "physical_condition_sha256": owner.get("physical_condition_sha256"),
        "owner_scope": owner.get("owner_scope"),
        "q_n": owner.get("q_n"),
        "continuum_initial_mass_kg": initial.get("initial_mass_total_kg"),
        "native_recipe": {
            "dp_m": recipe.get("dp_m"),
            "time_max_s": recipe.get("time_max_s"),
            "save_interval_s": recipe.get("save_interval_s"),
            "native_frame_count": recipe.get("native_frame_count"),
            "native_fluid_mass_kg": recipe.get("native_fluid_mass_kg"),
            "native_particle_counts": recipe.get("native_particle_counts"),
            "mass_policy": recipe.get("mass_policy"),
        },
    }


def build_context() -> dict[str, Any]:
    paths = source_paths()
    # These are all small provenance/control files.  RAW_ROOT and Part files
    # are intentionally absent from this list and are never touched here.
    source_records = {key: record(path, key.replace("_", " ")) for key, path in paths.items()}
    current_owner = load_object(OWNER, "CURRENT F7 owner")
    overlay = load_object(OVERLAY_MANIFEST, "half-CFL overlay manifest")
    rows = read_runparts(RUNPARTS)
    if len(rows) != 1201 or rows[-1]["frame"] != 1200:
        raise ValueError(f"F7-S2 half-CFL RunPARTs expected 1201 rows through frame 1200, got {len(rows)}")
    if [row["frame"] for row in rows] != EXPECTED_FRAMES[:1] + [*range(1, 1201)]:
        raise ValueError("F7-S2 half-CFL RunPARTs frame sequence changed")
    brackets = [bracket(rows, query) for query in QUERY_TIMES]
    selected = sorted({int(item[key]) for item in brackets for key in ("lower_frame", "upper_frame")})
    if selected != EXPECTED_FRAMES:
        raise ValueError(f"F7-S2 selected bracket frames changed: {selected} != {EXPECTED_FRAMES}")
    if overlay.get("mode") != "half_cfl":
        raise ValueError("F7 half observer must bind the completed half-CFL overlay")
    binding = {
        "schema": "ds02.stage2.f7-s2-native-source-binding.v2",
        "family_id": FAMILY,
        "sentinel_id": SENTINEL,
        "physical_case_id": PHYSICAL_CASE,
        "raw_root": str(RAW_ROOT),
        "runparts": source_records["runparts"],
        "generated_xml": source_records["generated_xml"],
        "current_xml": source_records["current_xml"],
        "actual_half_v7_solver_receipt": source_records["actual_half_v7_solver_receipt"],
        "actual_half_v7_solver_request": source_records["actual_half_v7_solver_request"],
        "source_gencase_receipt": source_records["source_gencase_receipt"],
        "source_owner": source_records["source_owner"],
        "overlay_manifest": source_records["overlay_manifest"],
        "motion": source_records["motion"],
        "source_owner_summary": owner_summary(current_owner),
        "overlay_control_proof": overlay.get("xml_diff_proof"),
        "source_control": {
            "cfl": 0.1,
            "time_max_s": 12.0,
            "time_out_s": 0.01,
            "savedt": overlay.get("xml_diff_proof", {}).get("savedt_values", {}),
            "mode": "half_cfl",
            "motion_sha256": source_records["motion"]["sha256"],
            "control_source": "actual overlay XML + overlay manifest + CURRENT owner; no inferred half-CFL substitution",
        },
        "frame_count": len(rows),
        "last_saved_time_s": rows[-1]["time_s"],
        "runparts_summary": runparts_summary(rows),
        "query_brackets": {str(query): item for query, item in zip(QUERY_TIMES, brackets)},
        "selected_native_frame_ids": selected,
        "selected_native_paths": [str(RAW_ROOT / f"Part_{frame:04d}.bi4") for frame in selected],
    }
    return {
        "source_records": source_records,
        "owner": current_owner,
        "overlay": overlay,
        "rows": rows,
        "brackets": brackets,
        "selected": selected,
        "binding": binding,
    }


def build_template(output: Path = TEMPLATE) -> dict[str, Any]:
    context = build_context()
    source_records = context["source_records"]
    static_paths = [Path(__file__).resolve(), *source_paths().values(), OBSERVER, ENFORCER, SNAPSHOT_WORKER,
                    DECODER, DECODER_SOURCE, V8_RUNNER, V8_STRICT, V8_RUNTIME, V6_RUNTIME, V2_RUNTIME, PYTHON]
    static_paths = list(dict.fromkeys(path.resolve() for path in static_paths))
    # The template includes static provenance hashes but explicitly excludes
    # the raw root and all deferred Part files from input_files.
    static_records = {str(path): record(path, "template static dependency") for path in static_paths}
    deferred = [str(RAW_ROOT), *context["binding"]["selected_native_paths"]]
    template = {
        "schema": REQUEST_SCHEMA,
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "family_id": FAMILY,
        "sentinel_id": SENTINEL,
        "physical_case_id": PHYSICAL_CASE,
        "case_id": "F7_S2_A065_HALF_CFL_SELECTED_NATIVE_OBSERVER_TEMPLATE_V1",
        "attempt_id": "f7-s2-a065-half-cfl-selected-native-observer-template-v1",
        "command": ["PARENT_BUILDS_ENFORCER_REQUEST_AFTER_SNAPSHOT_V2"],
        "cwd": str(REPO),
        "worktree_root": str(REPO),
        "input_files": list(static_records),
        "input_hashes": {path: item["sha256"] for path, item in static_records.items()},
        "selected_native_frame_ids": context["selected"],
        "query_times_s": QUERY_TIMES,
        "query_brackets": {str(query): item for query, item in zip(QUERY_TIMES, context["brackets"])},
        "source_binding": context["binding"],
        "observer_calibration_contract": calibration_contract(),
        "field_contract": {
            "sample_mass": "native per-particle mass summed by decoded group; diagnostic only",
            "mkfluid_relative": "fluid group labels from XML mkfluid ranges, retained as relative namespace",
            "mk_absolute": "XML absolute MK block labels for fixed/moving ranges, retained separately",
            "centroid": "mass-weighted centroid from float64 accumulation over decoded native fields",
            "velocity": "mass-weighted velocity from decoded native fields",
            "kinetic_energy": "mass-weighted per-particle kinetic energy; exact numeric convention remains worker output",
            "pressure_eos": "UNKNOWN_NOT_DECODED_BY_WORKER",
            "rigid_body_mass_inertia": "UNKNOWN_NOT_INFERRED_FROM_PARTICLE_SAMPLE_SUM",
            "query_alignment": "actual lower/upper RunPARTs frames and times retained; no particle interpolation",
        },
        "deferred_input_files": deferred,
        "deferred_input_file_count": len(context["selected"]),
        "deferred_hash_policy": {
            "snapshot_worker": SNAPSHOT_SCHEMA,
            "selected_frames_only": True,
            "exact_selected_native_frame_ids": context["selected"],
            "builder_bi4_read": False,
            "builder_bi4_hash": False,
            "full_raw_tree_hash": "NOT_COMPUTED_BY_BUILDER",
            "snapshot_pre_post_stat": "REQUIRED; mutation rejects snapshot",
            "observer_enforcer_pre_post_stat": "REQUIRED; complete stat boundaries across child decode",
            "hdf5_read": False,
            "solver_launch": False,
        },
        "execution_allowed": False,
        "launch_disabled": True,
        "solver_started": False,
        "hdf5_read": False,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "qualification_stage": "stage2_f7_s2_half_cfl_native_observer_template_v1_pending_parent_snapshot",
        "source_provenance_scope": {
            "actual_half_cfl_v7_run": True,
            "half_cfl_evidence": "ACTUAL_COMPLETED_V7; no same-CFL substitution",
            "raw_part_content": "DEFERRED_TO_PARENT_SNAPSHOT_AND_OBSERVER_GUARDS",
            "full_raw_tree_hash": "NOT_COMPUTED_BY_BUILDER",
            "runparts_is_saved_window_summary_only": True,
        },
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    atomic_json(output, template)
    return template


def build_snapshot_request(output: Path = SNAPSHOT_REQUEST, template_path: Path = TEMPLATE) -> dict[str, Any]:
    template = load_object(template_path, "F7 observer template")
    if template.get("schema") != REQUEST_SCHEMA or template.get("physical_case_id") != PHYSICAL_CASE:
        raise ValueError("F7 observer template identity/schema changed")
    if template.get("selected_native_frame_ids") != EXPECTED_FRAMES:
        raise ValueError("F7 observer template selected frame contract changed")
    context = build_context()
    static_paths = [Path(__file__).resolve(), template_path.resolve(), SNAPSHOT_WORKER,
                    V8_RUNNER, V8_STRICT, V8_RUNTIME, V6_RUNTIME, V2_RUNTIME, PYTHON,
                    RUNPARTS, GENERATED_XML, CURRENT_XML, ACTUAL_RECEIPT, ACTUAL_REQUEST,
                    GENCASE_RECEIPT, OWNER, OVERLAY_MANIFEST, MOTION]
    static_paths = list(dict.fromkeys(path.resolve() for path in static_paths))
    input_files = [str(regular(path, "snapshot static dependency")) for path in static_paths]
    input_hashes = {path: sha256(Path(path)) for path in input_files}
    raw_root = str(RAW_ROOT)
    selected_paths = [str(RAW_ROOT / f"Part_{frame:04d}.bi4") for frame in EXPECTED_FRAMES]
    request = {
        "schema": REQUEST_SCHEMA,
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "family_id": FAMILY,
        "sentinel_id": SENTINEL,
        "physical_case_id": PHYSICAL_CASE,
        "case_id": SNAPSHOT_CASE,
        "attempt_id": SNAPSHOT_ATTEMPT,
        "command": [str(PYTHON), str(SNAPSHOT_WORKER), "--observer-request", str(template_path.resolve()),
                     "--output", "{attempt_root}/native_selected_source_snapshot_half_cfl_v1.json"],
        "cwd": str(REPO),
        "worktree_root": str(REPO),
        "input_files": input_files,
        "input_hashes": input_hashes,
        "selected_native_frame_ids": EXPECTED_FRAMES,
        "query_times_s": QUERY_TIMES,
        "query_brackets": context["binding"]["query_brackets"],
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 1800,
        "estimated_native_read_bytes": "PARENT_GUARD_MEASURE_EXACT_NINE_SELECTED_F7_S2_HALF_CFL_V7_PARTS",
        "estimated_storage_bytes": 1024 * 1024 * 1024,
        "estimated_peak_memory_bytes": 1024 * 1024 * 1024,
        "execution_allowed": True,
        "launch_disabled": False,
        "solver_started": False,
        "hdf5_read": False,
        "bi4_decode": False,
        "deferred_input_files": [raw_root, *selected_paths],
        "deferred_input_file_count": len(selected_paths),
        "deferred_hash_policy": {
            "worker_schema": SNAPSHOT_SCHEMA,
            "selected_frames_only": True,
            "exact_selected_native_frame_ids": EXPECTED_FRAMES,
            "pre_post_stat_consistency": "REQUIRED; worker rejects size/mtime/ctime/device/inode changes",
            "full_raw_tree_hash": "NOT_COMPUTED_BY_WORKER",
            "full_raw_tree_scan": "FORBIDDEN",
            "hdf5_read": False,
            "bi4_decode": False,
            "solver_launch": False,
        },
        "source_binding": {
            "template_request": record(template_path, "F7 observer template"),
            "raw_root": raw_root,
            "selected_native_frame_ids": EXPECTED_FRAMES,
            "selected_native_paths": selected_paths,
            "runparts": context["binding"]["runparts"],
            "generated_xml": context["binding"]["generated_xml"],
            "source_owner": context["binding"]["source_owner"],
            "actual_half_v7_solver_receipt": context["binding"]["actual_half_v7_solver_receipt"],
            "source_sha_before_after_required": True,
            "observer_calibration_contract": calibration_contract(),
        },
        "output": {
            "atomic": True,
            "refuse_overwrite": True,
            "path": "{attempt_root}/native_selected_source_snapshot_half_cfl_v1.json",
            "status": "PASS_SELECTED_NATIVE_SOURCE_HASHED_STABLE or explicit failure",
        },
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": str(V8_RUNNER),
            "strict_guard": str(V8_STRICT),
            "runtime": str(V8_RUNTIME),
            "cpu_parent_binding": "required",
            "gpu": "none",
            "solver_launch": "forbidden",
            "hdf5_read": "forbidden",
            "bi4_decode": "forbidden; hash-only selected deferred files",
            "launch_disabled": False,
            "parent_v8_review_required": True,
        },
        "output_root": str(DATA_ROOT / "families/F7" / SNAPSHOT_CASE / SNAPSHOT_ATTEMPT),
        "qualification_stage": "stage2_f7_s2_half_cfl_selected_native_source_snapshot_v1_pending_parent_v8_dispatch",
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    atomic_json(output, request)
    return request


def validate_snapshot(template: dict[str, Any], receipt: dict[str, Any], result: dict[str, Any],
                      receipt_path: Path, result_path: Path) -> list[dict[str, Any]]:
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise ValueError("F7 snapshot receipt is not a completed successful terminal")
    if result.get("schema") != SNAPSHOT_SCHEMA or result.get("status") != "PASS_SELECTED_NATIVE_SOURCE_HASHED_STABLE":
        raise ValueError("F7 snapshot result is not stable v2 success")
    scope = result.get("worker_scope")
    if not isinstance(scope, dict) or scope.get("selected_file_count") != 9 or scope.get("full_raw_tree_hash") != "NOT_COMPUTED_BY_WORKER":
        raise ValueError("F7 snapshot scope is not exactly nine selected files")
    entries = result.get("requests")
    if not isinstance(entries, list) or len(entries) != 1 or not isinstance(entries[0], dict):
        raise ValueError("F7 snapshot result must contain exactly one request entry")
    entry = entries[0]
    identity = (template.get("case_id"), template.get("sentinel_id"), template.get("family_id"), template.get("physical_case_id"))
    actual_identity = (entry.get("case_id"), entry.get("sentinel_id"), entry.get("family_id"), entry.get("physical_case_id"))
    if identity != actual_identity:
        raise ValueError(f"F7 snapshot identity differs from template: {identity} != {actual_identity}")
    frames = [int(value) for value in template.get("selected_native_frame_ids", [])]
    selected = entry.get("selected_native_files")
    if not isinstance(selected, list) or [int(item.get("frame", -1)) for item in selected] != frames:
        raise ValueError("F7 snapshot selected frame list differs from template")
    source = template.get("source_binding")
    if not isinstance(source, dict) or str(Path(str(entry.get("raw_root"))).resolve()) != str(Path(str(source.get("raw_root"))).resolve()):
        raise ValueError("F7 snapshot raw-root differs from template")
    expected_paths = {str(Path(value).resolve()) for value in template.get("deferred_input_files", [])
                      if PART_RE.fullmatch(Path(str(value)).name)}
    records: list[dict[str, Any]] = []
    for item in selected:
        if not isinstance(item, dict):
            raise ValueError("F7 snapshot selected file is not an object")
        path = str(Path(str(item.get("path"))).resolve())
        if path not in expected_paths:
            raise ValueError(f"F7 snapshot selected path differs from template: {path}")
        digest = item.get("sha256")
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ValueError("F7 snapshot selected file lacks a content SHA")
        if not isinstance(item.get("bytes"), int) or item["bytes"] <= 0:
            raise ValueError("F7 snapshot selected file lacks positive bytes")
        records.append({"frame": int(item["frame"]), "path": path, "bytes": int(item["bytes"]), "sha256": digest})
    if len(records) != 9 or len({item["path"] for item in records}) != 9:
        raise ValueError("F7 snapshot selected files are not nine unique records")
    if not isinstance(entry.get("selected_source_sha256"), str):
        raise ValueError("F7 snapshot entry lacks selected_source_sha256")
    return records


def build_observer_request(snapshot_receipt: Path, snapshot_result: Path, output_dir: Path) -> dict[str, Any]:
    template = load_object(TEMPLATE, "F7 observer template")
    receipt = load_object(snapshot_receipt, "F7 snapshot receipt")
    result = load_object(snapshot_result, "F7 snapshot result")
    records = validate_snapshot(template, receipt, result, snapshot_receipt, snapshot_result)
    output_dir = output_dir.expanduser().resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"refuse to populate non-empty observer request directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    context = build_context()
    source = template["source_binding"]
    manifest_path = output_dir / "f7_s2_a065_half_cfl_expected_source_manifest_v1.json"
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "snapshot_schema": SNAPSHOT_SCHEMA,
        "observer_request": record(TEMPLATE, "F7 observer template"),
        "case_id": template["case_id"],
        "family_id": FAMILY,
        "sentinel_id": SENTINEL,
        "physical_case_id": PHYSICAL_CASE,
        "raw_root": str(Path(str(source["raw_root"])).resolve()),
        "selected_native_frame_ids": EXPECTED_FRAMES,
        "selected_native_files": records,
        "selected_source_sha256": result["requests"][0]["selected_source_sha256"],
        "source_sha_policy": "snapshot v2 SHA; enforcer v2 compares complete selected-file stat boundaries before/after child decode",
        "observer_calibration_contract": calibration_contract(),
    }
    atomic_json(manifest_path, manifest)
    source_keys = ("runparts", "generated_xml", "current_xml", "actual_half_v7_solver_receipt", "actual_half_v7_solver_request",
                   "source_gencase_receipt", "source_owner", "overlay_manifest", "motion")
    static_paths: list[Path] = [Path(__file__).resolve(), TEMPLATE, snapshot_receipt, snapshot_result, manifest_path,
                                OBSERVER, ENFORCER, SNAPSHOT_WORKER, DECODER, DECODER_SOURCE,
                                V8_RUNNER, V8_STRICT, V8_RUNTIME, V6_RUNTIME, V2_RUNTIME, PYTHON]
    for key in source_keys:
        item = source.get(key)
        if isinstance(item, dict) and isinstance(item.get("path"), str):
            static_paths.append(Path(item["path"]))
    static_paths = list(dict.fromkeys(path.expanduser().resolve() for path in static_paths))
    input_files = [str(regular(path, "observer static dependency")) for path in static_paths]
    input_hashes = {path: sha256(Path(path)) for path in input_files}
    selected_paths = [item["path"] for item in records]
    query_times = [float(value) for value in template["query_times_s"]]
    output_name = "f7_s2_a065_half_cfl_selected_native_observer_v1.json"
    runparts = Path(str(source["runparts"]["path"])).resolve()
    generated_xml = Path(str(source["generated_xml"]["path"])).resolve()
    raw_root = str(Path(str(source["raw_root"])).resolve())
    command = [str(PYTHON), str(ENFORCER), "--observer-worker", str(OBSERVER),
               "--expected-source-manifest", str(manifest_path), "--raw-root", raw_root,
               "--runparts", str(runparts), "--generated-xml", str(generated_xml),
               "--decoder", str(DECODER), "--decoder-source", str(DECODER_SOURCE),
               "--output", f"{{attempt_root}}/observer/{output_name}",
               "--scratch-root", "{attempt_root}/scratch/bi4_decode", "--cwd", str(REPO),
               "--expected-frame-count", str(source["frame_count"]),
               "--expected-final-time-s", str(source["last_saved_time_s"]),
               "--final-time-tolerance-s", "1e-12", "--frames", *[str(frame) for frame in EXPECTED_FRAMES],
               "--query-times", *[str(value) for value in query_times]]
    request = {
        "schema": REQUEST_SCHEMA,
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "family_id": FAMILY,
        "sentinel_id": SENTINEL,
        "physical_case_id": PHYSICAL_CASE,
        "case_id": OBSERVER_CASE,
        "attempt_id": OBSERVER_ATTEMPT,
        "command": command,
        "cwd": str(REPO),
        "worktree_root": str(REPO),
        "input_files": input_files,
        "input_hashes": input_hashes,
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 1800,
        "estimated_native_read_bytes": sum(item["bytes"] for item in records),
        "estimated_storage_bytes": 1024 * 1024 * 1024,
        "estimated_peak_memory_bytes": 1024 * 1024 * 1024,
        "execution_allowed": True,
        "launch_disabled": False,
        "solver_started": False,
        "hdf5_read": False,
        "bi4_decode": True,
        "deferred_input_files": [raw_root, *selected_paths],
        "deferred_input_file_count": len(selected_paths),
        "deferred_hash_policy": {
            "snapshot_terminal_sha_source": record(snapshot_result, "F7 snapshot result"),
            "builder_bi4_read": False,
            "builder_bi4_hash": False,
            "full_raw_tree_hash": "NOT_COMPUTED_BY_BUILDER",
            "observer_runtime_scope": "exact nine selected native frames only; no full raw scan",
            "enforcer_v2_pre_decode_sha_and_complete_stat": "REQUIRED",
            "enforcer_v2_post_decode_sha_and_complete_stat": "REQUIRED",
            "cross_decode_stat_boundaries": "pre.stat_after == post.stat_before and pre.stat_before == post.stat_after",
            "unknown_child_status": "FAILURE",
            "hdf5_read": False,
            "particle_field_interpolation": "NOT_PERFORMED_BY_WORKER",
        },
        "source_snapshot_binding": {
            "snapshot_receipt": record(snapshot_receipt, "F7 snapshot receipt"),
            "snapshot_result": record(snapshot_result, "F7 snapshot result"),
            "expected_source_manifest": record(manifest_path, "F7 expected source manifest"),
            "selected_source_sha256": result["requests"][0]["selected_source_sha256"],
            "selected_native_files": records,
            "builder_did_not_read_bi4": True,
        },
        "source_binding": {
            "template_request": record(TEMPLATE, "F7 observer template"),
            "raw_root": raw_root,
            "runparts": source["runparts"],
            "generated_xml": source["generated_xml"],
            "current_xml": source["current_xml"],
            "actual_half_v7_solver_receipt": source["actual_half_v7_solver_receipt"],
            "actual_half_v7_solver_request": source["actual_half_v7_solver_request"],
            "source_owner": source["source_owner"],
            "selected_native_frame_ids": EXPECTED_FRAMES,
            "query_times_s": query_times,
            "query_brackets": template["query_brackets"],
            "last_saved_time_s": source["last_saved_time_s"],
            "source_control": source["source_control"],
            "source_owner_summary": source["source_owner_summary"],
            "overlay_control_proof": source["overlay_control_proof"],
        },
        "observer_calibration_contract": calibration_contract(),
        "field_contract": template["field_contract"],
        "output": {
            "atomic": True,
            "refuse_overwrite": True,
            "path": f"{{attempt_root}}/observer/{output_name}",
            "scratch_cleanup": "worker-owned temporary decoder tree",
        },
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": str(V8_RUNNER),
            "strict_guard": str(V8_STRICT),
            "runtime": str(V8_RUNTIME),
            "cpu_parent_binding": "required",
            "gpu": "none",
            "solver_launch": "forbidden",
            "hdf5_read": "forbidden",
            "parent_v8_review_required": True,
        },
        "output_root": str(DATA_ROOT / "families/F7" / OBSERVER_CASE / OBSERVER_ATTEMPT),
        "qualification_stage": "stage2_f7_s2_half_cfl_selected_native_observer_v1_enforcer_v2_pending_parent_v8_dispatch",
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    request_path = output_dir / f"{output_name.removesuffix('.json')}_request.json"
    atomic_json(request_path, request)
    manifest_value = {
        "schema": "ds02.stage2.f7-s2-half-cfl-native-observer-v1-prepared",
        "status": "PREPARED_SNAPSHOT_BOUND_ENFORCER_V2",
        "snapshot_receipt": record(snapshot_receipt, "F7 snapshot receipt"),
        "snapshot_result": record(snapshot_result, "F7 snapshot result"),
        "expected_source_manifest": record(manifest_path, "F7 expected source manifest"),
        "request_path": str(request_path),
        "selected_native_file_count": 9,
        "enforcer": {"path": str(ENFORCER), "schema": "ds02.stage2.native-physical-observer-enforcer.v2"},
        "bi4_read_by_builder": False,
        "hdf5_read": False,
        "solver_launch": False,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    atomic_json(output_dir / "f7_s2_half_cfl_native_observer_v1_manifest.json", manifest_value)
    return request


def self_test() -> dict[str, Any]:
    assert EXPECTED_FRAMES == [0, 299, 300, 599, 600, 899, 900, 1199, 1200]
    assert calibration_contract()["task_budget_shares"]["time"]["maximum_fraction_of_task_error_budget"] == 0.25
    assert OBSERVER.name.endswith("stage2_native_physical_observer_v2.py")
    assert ENFORCER.name.endswith("stage2_native_physical_observer_enforcer_v2.py")
    assert SNAPSHOT_WORKER.name.endswith("stage2_native_source_snapshot_v2.py")
    return {
        "status": "PASS",
        "selected_frame_count": len(EXPECTED_FRAMES),
        "query_count": len(QUERY_TIMES),
        "bi4_read": False,
        "hdf5_read": False,
        "solver_launch": False,
        "quarter_task_budget_registered_before_field_differences": True,
        "half_cfl_substitution": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--build-template", action="store_true")
    parser.add_argument("--build-snapshot-request", action="store_true")
    parser.add_argument("--build-observer-request", action="store_true")
    parser.add_argument("--snapshot-receipt", type=Path)
    parser.add_argument("--snapshot-result", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), indent=2))
        return 0
    selected = [args.build_template, args.build_snapshot_request, args.build_observer_request]
    if sum(selected) != 1:
        parser.error("choose exactly one build action or --self-test")
    if args.build_template:
        template = build_template()
        print(json.dumps({"status": "PASS_TEMPLATE_BUILT", "path": str(TEMPLATE),
                          "selected_frame_count": len(template["selected_native_frame_ids"]), "bi4_read": False}, indent=2))
        return 0
    if args.build_snapshot_request:
        if not TEMPLATE.is_file():
            build_template()
        request = build_snapshot_request()
        print(json.dumps({"status": "PASS_SNAPSHOT_REQUEST_BUILT", "path": str(SNAPSHOT_REQUEST),
                          "selected_frame_count": request["deferred_input_file_count"], "bi4_read": False}, indent=2))
        return 0
    if args.snapshot_receipt is None or args.snapshot_result is None:
        parser.error("--snapshot-receipt and --snapshot-result are required for --build-observer-request")
    output_dir = args.output_dir or (REQUEST_ROOT / "stage2-f7-s2-half-native-observer-v1-canonical")
    request = build_observer_request(args.snapshot_receipt, args.snapshot_result, output_dir)
    print(json.dumps({"status": "PASS_OBSERVER_REQUEST_BUILT", "output_dir": str(output_dir.resolve()),
                      "selected_frame_count": request["deferred_input_file_count"],
                      "estimated_native_read_bytes": request["estimated_native_read_bytes"], "bi4_read": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
