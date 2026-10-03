#!/usr/bin/env python3
"""Source-bound fine-resolution ($dp=0.005$ m) native OFFSET pose and labels pipeline.

Preparation-only runner for matched fine OFFSET reference:
- Case ID: F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001
- Geometry: OFFSET receiver (low corner [0.45, -0.16, 0.0] m, offset y by +0.14 m)
- Physical Condition Hash: 327899e38bbad63951206d5b2fd3ef354c049a32f6671af1af7913a48b77c7ef
- Numerical Recipe Hash: 10ce34f8b4d0b9e42c605e2a96da1bc031c669f6413b325a12dc31fbd0a22b65
- Timing Window: [0.0, 4.0] s, 401 frames, dt=0.010 s
- Timing Budget: Original save allowance 0.0007336390799938275 s preserved without waiver

Operational and scientific boundaries:
1. Strict shared-runner compliance: execution receipts are written exclusively by the shared runner.
2. Verified private NVMe copies with streaming SHA-256 verification and 0400 read-only permissions.
3. Staged private scratch storage: canonical source references are rebound before publication.
4. Heavy fine case storage ledger: source H5 is ~6.06 GB (6,063,678,335 bytes).
   - Pose stage peak: ~14.0 GiB (15,032,385,536 bytes) bounded to 2 CPU threads / 3600 s.
   - Labels stage peak: ~8.0 GiB (8,589,934,592 bytes) bounded to 2 CPU threads / 3600 s.
   - Root ledger cost review note explicitly recorded for > 5 GiB footprint.
5. Binding to actual closed converter attempt:
   conversion-f2_rv4eq_dp005_offset_v1_baseline_save001-fullstate-root-reviewed-005.
6. Downstream labels stage uses fresh deferred pose markers until Root executes pose stage.
7. Separate native float32 mass (24.5760011673 kg) vs continuous decimal XML reference (24.576 kg).
   Observed native invalid particles (2,151 particles) remain strictly classified as unknown loss.
   Zero physical defect not claimed; no Q-N grant.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any


FAMILY_ROOT = Path(__file__).resolve().parent
INTEGRATION_LAB = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
F2_DATA = DATA_ROOT / "families/F2"

PYTHON = INTEGRATION_LAB / ".venv/bin/python"
RUNTIME = INTEGRATION_LAB / "scripts/ds_data02_runtime_v2.py"
STRICT_DISPATCH = INTEGRATION_LAB / "scripts/ds_data02_strict_dispatch_v1.py"
POSE_HELPER = INTEGRATION_LAB / "scripts/ds_data02_convert.py"

V6_LABELS = FAMILY_ROOT / "f2_handoff_20261002_v6_labels.py"
EVENT_OPERATOR = FAMILY_ROOT / "f2_handoff_20261002_event_semantics_v6.py"
EVENT_MANIFEST = FAMILY_ROOT / "handoff_20261002/event_semantics_v6/operator_manifest.json"
QUALITY = FAMILY_ROOT / "quality_contract.json"
EVENTS = FAMILY_ROOT / "event_definitions.json"

DEFAULT_HANDOFF_ROOT = FAMILY_ROOT / "handoff_20261003/matched_offset_fine_pipeline_v1"
DEFAULT_SCRATCH = Path("/tmp/ds02-f2-offset-fine-nvme-v1")

PHYSICAL_HASH = "327899e38bbad63951206d5b2fd3ef354c049a32f6671af1af7913a48b77c7ef"
NUMERICAL_RECIPE_HASH = "10ce34f8b4d0b9e42c605e2a96da1bc031c669f6413b325a12dc31fbd0a22b65"
SAVE_ALLOWANCE_S = 0.0007336390799938275

FINE_CASE_INFO: dict[str, Any] = {
    "case_id": "F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001",
    "short_name": "offset_fine",
    "resolution": "FINE",
    "dp_m": 0.005,
    "total_particles": 1667249,
    "fluid_particles": 196608,
    "moving_particles": 76676,
    "fixed_particles": 1393965,
    "case_nmoving": 76676,
    "source_invalid_particles_npout": 2151,
    "final_fluid_particles": 194457,
    "xml_massfluid_decimal": 0.000125,
    "xml_total_fluid_mass_kg": 24.576,
    "native_float32_fluid_sum_kg": 24.576001167297363,
    "source_h5": F2_DATA / "F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001/conversion-f2_rv4eq_dp005_offset_v1_baseline_save001-fullstate-root-reviewed-005/trajectory.h5",
    "source_h5_sha256": "e76eb883c22c06d2eeb498e7cd6aa3b254e4755488f0ef651caa35b2c8b07c96",
    "source_h5_bytes": 6063678335,
    "conversion_report": F2_DATA / "F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001/conversion-f2_rv4eq_dp005_offset_v1_baseline_save001-fullstate-root-reviewed-005/conversion-report.json",
    "conversion_report_sha256": "4533df13c520bcd4868b2b9f6ea76896475fde095fc70ed8e3adeb34242d2389",
    "conversion_receipt": F2_DATA / "F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001/conversion-f2_rv4eq_dp005_offset_v1_baseline_save001-fullstate-root-reviewed-005/execution-receipt.json",
    "conversion_receipt_sha256": "77cd462910b053f31687cfa5f02ce9e43920d8f84a2bf845b75d89d833957883",
    "xml": F2_DATA / "F2_RV4EQ_DP005_NATIVE_INPUTS_20261002/F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001/F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001.xml",
    "xml_sha256": "f57c5e5fcf6c7c374ae14a8b28ae40b9e080554e2dfae8824253ae32e42b49cd",
    "motion": F2_DATA / "F2_RV4EQ_DP005_NATIVE_INPUTS_20261002/F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001/F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001_motion.dat",
    "motion_sha256": "ff966330e01e565987ebf182a7dfd7401d76577ae1c266894fc7db4aa34c5b70",
    "run_out": F2_DATA / "F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001/qualification-f2_rv4eq_dp005_offset_v1-baseline-save001-native-fullstate-v1/solver_output/Run.out",
    "run_out_sha256": "ffcd392114bf768869165588d6645d66f6bc7a9599195d8fec366e584688a08d",
    "solver_receipt": F2_DATA / "F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001/qualification-f2_rv4eq_dp005_offset_v1-baseline-save001-native-fullstate-v1/execution-receipt.json",
    "solver_receipt_sha256": "ad826271229884cc0ecc7245d6fc4f97a888d799fa3596d806ba3e4587b5c9a7",
    "gencase_receipt": F2_DATA / "F2_RV4EQ_DP005_OFFSET_V1/gencase-f2_rv4eq_dp005_offset_v1-20261002-001/execution-receipt.json",
    "gencase_receipt_sha256": "f973b151cadea0d97b1f6c0726dec27490764fb91d9855e95fd8483eb9513ac7",
    "numerical_recipe_hash": NUMERICAL_RECIPE_HASH,
    "physical_hash": PHYSICAL_HASH,
    "pose_attempt_id": "matched-offset-fine-nvme-pose-v1-001",
    "labels_attempt_id": "matched-offset-fine-nvme-labels-v1-001",
    "estimated_pose_storage_bytes": 15032385536,  # ~14.0 GiB peak (source copy + augmented H5)
    "estimated_labels_storage_bytes": 8589934592,  # ~8.0 GiB peak (pose copy + labels H5)
}


class PostprocessError(RuntimeError):
    """Raised when an operation cannot be completed safely."""


_SHA_CACHE: dict[tuple[str, int, int], str] = {}


def sha256_file(path: Path) -> str:
    resolved = Path(path).resolve()
    try:
        st = resolved.stat()
        cache_key = (str(resolved), st.st_size, st.st_mtime_ns)
        if cache_key in _SHA_CACHE:
            return _SHA_CACHE[cache_key]
    except OSError:
        cache_key = None

    digest = hashlib.sha256()
    with resolved.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    val = digest.hexdigest()
    if cache_key is not None:
        _SHA_CACHE[cache_key] = val
    return val


def require_file(path: Any, label: str) -> Path:
    p = Path(str(path)).expanduser().resolve()
    if not p.is_file():
        raise PostprocessError(f"{label} is missing: {p}")
    return p


def load_json(path: Any, label: str) -> dict[str, Any]:
    p = require_file(path, label)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        raise PostprocessError(f"{label} is invalid JSON: {p} ({exc})") from exc
    if not isinstance(data, dict):
        raise PostprocessError(f"{label} is not a JSON object: {p}")
    return data


def dump_json(path: Any, data: Any) -> None:
    p = Path(str(path)).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def binding(path: Any, role: str, *, known_sha: str | None = None) -> dict[str, Any]:
    p = require_file(path, role)
    actual_sha = sha256_file(p)
    if known_sha and actual_sha != known_sha:
        raise PostprocessError(f"SHA mismatch for {role}: expected {known_sha}, got {actual_sha}")
    return {
        "path": str(p),
        "sha256": actual_sha,
        "bytes": int(p.stat().st_size),
        "role": role,
    }


def verified_copy(source: Path, target: Path, expected_sha: str, expected_bytes: int) -> dict[str, Any]:
    source = require_file(source, "source for copy")
    if target.exists():
        raise PostprocessError(f"refusing to overwrite existing target: {target}")
    before_stat = source.stat()
    if int(before_stat.st_size) != int(expected_bytes):
        raise PostprocessError(f"source byte size {before_stat.st_size} != expected {expected_bytes}")

    target.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    with source.open("rb") as reader, target.open("xb") as writer:
        for block in iter(lambda: reader.read(8 * 1024 * 1024), b""):
            digest.update(block)
            writer.write(block)
        writer.flush()
        os.fsync(writer.fileno())

    actual_sha = digest.hexdigest()
    if actual_sha != expected_sha:
        target.unlink(missing_ok=True)
        raise PostprocessError(f"SHA mismatch during streaming copy: {actual_sha} != {expected_sha}")

    # Set read-only permissions
    target.chmod(0o400)
    return {
        "canonical_source_path": str(source),
        "canonical_source_sha256": expected_sha,
        "canonical_source_bytes": int(before_stat.st_size),
        "private_reader_path": str(target),
        "private_reader_sha256": actual_sha,
        "private_reader_bytes": int(target.stat().st_size),
        "copy_verified_during_stream": True,
        "private_reader_deleted_before_publish": True,
    }


def load_module(path: Path, module_name: str) -> Any:
    require_file(path, f"module {module_name}")
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise PostprocessError(f"could not load spec for {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_owner_metadata(info: dict[str, Any], owner_dir: Path) -> dict[str, Any]:
    owner_meta = {
        "schema": "ds02.f2.case-owner-metadata.v1",
        "family_id": "F2",
        "case_id": info["case_id"],
        "background": "OFFSET",
        "resolution": info["resolution"],
        "dp_m": info["dp_m"],
        "particle_counts": {
            "total_particles": info["total_particles"],
            "fluid_particles": info["fluid_particles"],
            "moving_particles": info["moving_particles"],
            "fixed_particles": info["fixed_particles"],
            "source_invalid_particles_npout": info["source_invalid_particles_npout"],
            "final_fluid_particles": info["final_fluid_particles"],
        },
        "geometry": {
            "cup_low_m": [0.0, -0.15, 0.65],
            "cup_size_m": [0.425, 0.3, 0.45],
            "receiver_low_m": [0.45, -0.16, 0.0],
            "receiver_size_m": [1.1, 0.6, 0.45],
            "receiver_offset_y_m": 0.14,
            "tray_low_m": [-1.2, -1.0, -0.2],
            "tray_size_m": [4.0, 2.0, 0.15],
        },
        "definition": {
            "path": str(info["xml"]),
            "sha256": info["xml_sha256"],
            "role": "generated XML",
        },
        "motion": {
            "path": str(info["motion"]),
            "sha256": info["motion_sha256"],
            "role": "motion control",
        },
        "mass_reference": {
            "xml_massfluid_decimal_kg": info["xml_massfluid_decimal"],
            "continuous_mass_kg": info["xml_total_fluid_mass_kg"],
            "native_float32_fluid_sum_kg": info["native_float32_fluid_sum_kg"],
            "native_representation_delta_kg": info["native_float32_fluid_sum_kg"] - info["xml_total_fluid_mass_kg"],
            "strict_cell_center_exact_budget_fraction": "1e-12",
        },
        "event_window": {
            "hold_start_s": 0.5,
            "time_start_s": 0.0,
            "time_end_s": 4.0,
            "frames": 401,
            "dt_s": 0.010,
            "save_allowance_s": SAVE_ALLOWANCE_S,
            "save_budget_relaxation_applied": False,
        },
        "unknown_loss_semantics": {
            "observed_native_invalid_policy": "unknown; never inferred as physical spill without geometric segment test",
            "destination_precedence": ["unknown_invalid", "cup", "receiver", "tray_after_departure", "inflight"],
            "physical_spill_inferred_from_invalid": False,
        },
        "physical_binding": {
            "physical_condition_hash_declared": info["physical_hash"],
            "parameters": {
                "motion_axis_origin_m": [0.0, -1.0, 0.65],
                "motion_axis_unit": [0.0, 1.0, 0.0],
                "receiver_x_m": 0.45,
                "receiver_y_m": 0.14,
            },
        },
        "numerical_recipe_hash_declared": info["numerical_recipe_hash"],
        "fullstate_terminal_binding": {
            "trajectory_h5": binding(info["source_h5"], "canonical converted trajectory H5", known_sha=info["source_h5_sha256"]),
            "conversion_report": binding(info["conversion_report"], "conversion report", known_sha=info["conversion_report_sha256"]),
            "conversion_receipt": binding(info["conversion_receipt"], "conversion receipt", known_sha=info["conversion_receipt_sha256"]),
        },
        "resource_review": {
            "oversize_fine_resolution": True,
            "source_h5_bytes": info["source_h5_bytes"],
            "pose_peak_storage_bytes": info["estimated_pose_storage_bytes"],
            "labels_peak_storage_bytes": info["estimated_labels_storage_bytes"],
            "cost_review_note": (
                "Fine case with N=1,667,249 particles and ~6.06 GB trajectory requires explicit "
                "ledger review and reservation prior to root launch."
            ),
        },
    }
    owner_path = owner_dir / f"{info['case_id']}.owner.v1.json"
    dump_json(owner_path, owner_meta)
    return owner_meta


def build_pose_stage(info: dict[str, Any], owner_meta_path: Path, configs_dir: Path, requests_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    case_id = info["case_id"]
    attempt_id = info["pose_attempt_id"]

    config = {
        "schema": "ds02.f2.matched-offset-fine-pose-config.v1",
        "stage": "pose",
        "case_id": case_id,
        "resolution": info["resolution"],
        "dp_m": info["dp_m"],
        "attempt_id": attempt_id,
        "physical_condition_hash": info["physical_hash"],
        "numerical_recipe_hash": info["numerical_recipe_hash"],
        "geometry": {
            "cup_low_m": [0.0, -0.15, 0.65],
            "cup_size_m": [0.425, 0.3, 0.45],
            "receiver_low_m": [0.45, -0.16, 0.0],
            "receiver_size_m": [1.1, 0.6, 0.45],
            "receiver_offset_y_m": 0.14,
            "tray_low_m": [-1.2, -1.0, -0.2],
            "tray_size_m": [4.0, 2.0, 0.15],
            "motion_axis_origin_m": [0.0, -1.0, 0.65],
            "motion_axis_unit": [0.0, 1.0, 0.0],
        },
        "terminal_bindings": {
            "source_trajectory_h5": binding(info["source_h5"], "source trajectory H5", known_sha=info["source_h5_sha256"]),
            "conversion_report": binding(info["conversion_report"], "conversion report", known_sha=info["conversion_report_sha256"]),
            "conversion_receipt": binding(info["conversion_receipt"], "conversion receipt", known_sha=info["conversion_receipt_sha256"]),
        },
        "inputs": {
            "xml": binding(info["xml"], "generated XML", known_sha=info["xml_sha256"]),
            "motion": binding(info["motion"], "motion control", known_sha=info["motion_sha256"]),
            "run_out": binding(info["run_out"], "solver Run.out", known_sha=info["run_out_sha256"]),
            "solver_receipt": binding(info["solver_receipt"], "solver execution receipt", known_sha=info["solver_receipt_sha256"]),
            "gencase_receipt": binding(info["gencase_receipt"], "GenCase execution receipt", known_sha=info["gencase_receipt_sha256"]),
            "owner_metadata": binding(owner_meta_path, "owner metadata"),
        },
        "nvme_policy": {
            "scratch_parent": str(DEFAULT_SCRATCH),
            "stage_in_private_dir": True,
            "rebind_canonical_before_publish": True,
            "private_copy_deleted_after_stage": True,
        },
        "resource_ledger": {
            "cpu_threads": 2,
            "max_wall_seconds": 3600,
            "estimated_storage_bytes": info["estimated_pose_storage_bytes"],
            "root_cost_review_required": True,
            "review_rationale": "Source trajectory is 6.06 GB; private copy + augmented output peak is ~14.0 GiB.",
        },
        "claim_boundary": {
            "q_i": "not_granted; pose enrichment evidence only",
            "q_n": "not_assessed",
            "production": "not_evaluated",
        },
    }
    config_path = configs_dir / "offset_fine_pose_nvme_config_v1.json"
    dump_json(config_path, config)

    request_inputs = [
        Path(__file__).resolve(),
        PYTHON,
        RUNTIME,
        STRICT_DISPATCH,
        POSE_HELPER,
        V6_LABELS,
        EVENT_OPERATOR,
        EVENT_MANIFEST,
        QUALITY,
        EVENTS,
        config_path,
        info["source_h5"],
        info["conversion_report"],
        info["conversion_receipt"],
        info["xml"],
        info["motion"],
        info["run_out"],
        info["solver_receipt"],
        info["gencase_receipt"],
        owner_meta_path,
    ]
    unique_inputs = []
    seen = set()
    for p in request_inputs:
        resolved = Path(p).resolve()
        if str(resolved) not in seen and resolved.is_file():
            seen.add(str(resolved))
            unique_inputs.append(resolved)

    request = {
        "schema": "ds02.runner-request.v2",
        "family_id": "F2",
        "case_id": case_id,
        "attempt_id": attempt_id,
        "kind": "cpu",
        "cpu_task_kind": "labels",
        "cpu_threads": 2,
        "max_wall_seconds": 3600,
        "estimated_storage_bytes": info["estimated_pose_storage_bytes"],
        "cwd": str(FAMILY_ROOT),
        "worktree_root": str(FAMILY_ROOT.parents[4]),
        "command": [
            str(PYTHON),
            str(Path(__file__).resolve()),
            "run",
            "pose",
            "--config",
            str(config_path),
            "--output-dir",
            "{attempt_root}",
            "--scratch-parent",
            str(DEFAULT_SCRATCH),
        ],
        "input_files": [str(p) for p in unique_inputs],
        "input_sha256": {str(p): sha256_file(p) for p in unique_inputs},
        "claim_boundary": {
            "q_i": "not_granted; pose enrichment evidence only",
            "q_n": "not_assessed",
            "production": "not_evaluated",
        },
        "independent_case_count_increment": 0,
        "conversion_launch_forbidden": True,
        "oversize_cost_review": {
            "particle_count": info["total_particles"],
            "fluid_particles": info["fluid_particles"],
            "moving_particles": info["moving_particles"],
            "fixed_particles": info["fixed_particles"],
            "source_h5_bytes": info["source_h5_bytes"],
            "estimated_peak_scratch_bytes": 13000000000,
            "estimated_output_h5_bytes": 6064000000,
            "ledger_storage_approved_fraction": "fine case requires explicit root cost review and ledger allocation prior to launch",
            "cpu_threads_bounded": 2,
            "max_wall_seconds": 3600,
        },
    }
    request_path = requests_dir / "offset_fine_pose_nvme_request_v1.json"
    dump_json(request_path, request)
    return config, request


def build_prospective_labels_stage(
    info: dict[str, Any],
    owner_meta_path: Path,
    configs_dir: Path,
    requests_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    case_id = info["case_id"]
    attempt_id = info["labels_attempt_id"]
    pose_attempt_id = info["pose_attempt_id"]
    pose_attempt_dir = F2_DATA / case_id / pose_attempt_id

    config = {
        "schema": "ds02.f2.matched-offset-fine-labels-config.v1",
        "stage": "labels",
        "status": "prospective_pose_binding_deferred",
        "case_id": case_id,
        "resolution": info["resolution"],
        "dp_m": info["dp_m"],
        "attempt_id": attempt_id,
        "physical_condition_hash": info["physical_hash"],
        "numerical_recipe_hash": info["numerical_recipe_hash"],
        "geometry": {
            "cup_low_m": [0.0, -0.15, 0.65],
            "cup_size_m": [0.425, 0.3, 0.45],
            "receiver_low_m": [0.45, -0.16, 0.0],
            "receiver_size_m": [1.1, 0.6, 0.45],
            "receiver_offset_y_m": 0.14,
            "tray_low_m": [-1.2, -1.0, -0.2],
            "tray_size_m": [4.0, 2.0, 0.15],
            "motion_axis_origin_m": [0.0, -1.0, 0.65],
            "motion_axis_unit": [0.0, 1.0, 0.0],
        },
        "timing": {
            "event_window_s": 4.0,
            "frames": 401,
            "dt_s": 0.010,
            "save_allowance_s": SAVE_ALLOWANCE_S,
            "save_budget_relaxation_applied": False,
        },
        "mass_semantics": {
            "xml_massfluid_decimal_kg": info["xml_massfluid_decimal"],
            "xml_continuous_mass_kg": info["xml_total_fluid_mass_kg"],
            "native_float32_fluid_sum_kg": info["native_float32_fluid_sum_kg"],
            "native_representation_delta_kg": info["native_float32_fluid_sum_kg"] - info["xml_total_fluid_mass_kg"],
            "source_normalization_applied": False,
            "interpretation": (
                "Native float32 mass values are preserved unnormalized; difference from XML continuous 24.576 kg "
                "is strictly arithmetic IEEE-754 summation tolerance. Observed invalid native particles remain "
                "scientifically classified as unknown loss."
            ),
        },
        "unknown_loss_semantics": {
            "observed_native_invalid_policy": "unknown; never inferred as physical spill without geometric segment test",
            "destination_precedence": ["unknown_invalid", "cup", "receiver", "tray_after_departure", "inflight"],
            "physical_spill_inferred_from_invalid": False,
        },
        "resource_ledger": {
            "cpu_threads": 2,
            "max_wall_seconds": 3600,
            "estimated_storage_bytes": info["estimated_labels_storage_bytes"],
            "heavy_fine_cost_review_required": True,
            "root_ledger_review_note": (
                "Fine resolution dp=0.005 m with 1.67M particles and ~6.06 GB trajectory requires explicit "
                "root cost review and storage allocation before launch."
            ),
        },
        "terminal_bindings": {
            "source_trajectory_h5": binding(info["source_h5"], "source trajectory H5", known_sha=info["source_h5_sha256"]),
            "conversion_report": binding(info["conversion_report"], "conversion report", known_sha=info["conversion_report_sha256"]),
            "conversion_receipt": binding(info["conversion_receipt"], "conversion receipt", known_sha=info["conversion_receipt_sha256"]),
        },
        "deferred_pose_bindings": {
            "binding_status": "deferred_until_root_execution",
            "pose_attempt_id": pose_attempt_id,
            "pose_attempt_dir": str(pose_attempt_dir),
            "pose_h5_target": str(pose_attempt_dir / "trajectory-with-actual-pose.h5"),
            "pose_report_target": str(pose_attempt_dir / "rigid-body-state.json"),
            "pose_receipt_target": str(pose_attempt_dir / "execution-receipt.json"),
        },
        "inputs": {
            "xml": binding(info["xml"], "generated XML", known_sha=info["xml_sha256"]),
            "owner_metadata": binding(owner_meta_path, "owner metadata"),
        },
        "nvme_policy": {
            "scratch_parent": str(DEFAULT_SCRATCH),
            "stage_in_private_dir": True,
            "rebind_canonical_before_publish": True,
            "private_copy_deleted_after_stage": True,
        },
        "claim_boundary": {
            "q_i": "not_granted; labels evidence only",
            "q_n": "not_assessed",
            "production": "not_evaluated",
        },
        "independent_case_count_increment": 0,
        "conversion_launch_forbidden": True,
    }
    config_path = configs_dir / "offset_fine_labels_nvme_config_v1.json"
    dump_json(config_path, config)

    static_inputs = [
        Path(__file__).resolve(),
        PYTHON,
        RUNTIME,
        STRICT_DISPATCH,
        POSE_HELPER,
        V6_LABELS,
        EVENT_OPERATOR,
        EVENT_MANIFEST,
        QUALITY,
        EVENTS,
        config_path,
        info["xml"],
        owner_meta_path,
    ]
    unique_static = []
    seen = set()
    for p in static_inputs:
        res = Path(p).resolve()
        if str(res) not in seen and res.is_file():
            seen.add(str(res))
            unique_static.append(res)

    template = {
        "schema": "ds02.f2.prospective-labels-request-template.v1",
        "family_id": "F2",
        "case_id": case_id,
        "attempt_id": attempt_id,
        "kind": "cpu",
        "cpu_task_kind": "labels",
        "cpu_threads": 2,
        "max_wall_seconds": 3600,
        "estimated_storage_bytes": info["estimated_labels_storage_bytes"],
        "cwd": str(FAMILY_ROOT),
        "worktree_root": str(FAMILY_ROOT.parents[4]),
        "command": [
            str(PYTHON),
            str(Path(__file__).resolve()),
            "run",
            "labels",
            "--config",
            str(config_path),
            "--output-dir",
            "{attempt_root}",
            "--scratch-parent",
            str(DEFAULT_SCRATCH),
        ],
        "static_input_files": [str(p) for p in unique_static],
        "static_input_sha256": {str(p): sha256_file(p) for p in unique_static},
        "deferred_inputs": [
            str(pose_attempt_dir / "trajectory-with-actual-pose.h5"),
            str(pose_attempt_dir / "rigid-body-state.json"),
            str(pose_attempt_dir / "execution-receipt.json"),
        ],
        "status": "prospective_awaiting_root_pose_execution",
        "claim_boundary": {
            "q_i": "not_granted; labels evidence only",
            "q_n": "not_assessed",
            "production": "not_evaluated",
        },
        "independent_case_count_increment": 0,
        "conversion_launch_forbidden": True,
        "oversize_cost_review": {
            "particle_count": info["total_particles"],
            "fluid_particles": info["fluid_particles"],
            "moving_particles": info["moving_particles"],
            "fixed_particles": info["fixed_particles"],
            "source_h5_bytes": info["source_h5_bytes"],
            "estimated_labels_h5_bytes": 850000000,
            "ledger_storage_approved_fraction": "fine labels stage requires explicit root cost review and ledger allocation prior to launch",
            "cpu_threads_bounded": 2,
            "max_wall_seconds": 3600,
        },
    }
    template_path = requests_dir / "offset_fine_labels_prospective_template_v1.json"
    dump_json(template_path, template)
    return config, template


def resolve_labels_request_after_pose(
    pose_attempt_dir: Path | None = None,
    *,
    output_root: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve prospective labels config into a runnable shared-runner request after Root executes pose."""
    info = FINE_CASE_INFO
    case_id = info["case_id"]
    attempt_id = info["labels_attempt_id"]

    if pose_attempt_dir is None:
        pose_attempt_dir = F2_DATA / case_id / info["pose_attempt_id"]
    else:
        pose_attempt_dir = Path(pose_attempt_dir).expanduser().resolve()

    pose_receipt_path = pose_attempt_dir / "execution-receipt.json"
    pose_report_path = pose_attempt_dir / "rigid-body-state.json"
    pose_h5_path = pose_attempt_dir / "trajectory-with-actual-pose.h5"

    for path, label in [
        (pose_receipt_path, "pose execution receipt"),
        (pose_report_path, "pose report"),
        (pose_h5_path, "pose-augmented trajectory H5"),
    ]:
        if not path.is_file():
            raise PostprocessError(f"cannot resolve labels request: {label} is missing (pose stage has not yet executed): {path}")

    pose_receipt = load_json(pose_receipt_path, "pose execution receipt")
    if pose_receipt.get("status") != "completed" or pose_receipt.get("returncode") != 0:
        raise PostprocessError(f"cannot resolve labels request: pose execution receipt not completed with returncode 0: {pose_receipt_path}")

    pose_report = load_json(pose_report_path, "pose report")
    pose_row = pose_report.get("augmented_trajectory")
    if not isinstance(pose_row, dict) or len(str(pose_row.get("sha256", ""))) != 64:
        raise PostprocessError("cannot resolve labels request: pose report lacks valid augmented_trajectory SHA-256")

    actual_pose_h5_sha = sha256_file(pose_h5_path)
    if actual_pose_h5_sha != pose_row["sha256"]:
        raise PostprocessError(f"cannot resolve labels request: pose report SHA {pose_row['sha256']} differs from file {actual_pose_h5_sha}")

    root_dir = (output_root or DEFAULT_HANDOFF_ROOT).resolve()
    configs_dir = root_dir / "configs"
    requests_dir = root_dir / "requests"
    owner_dir = root_dir / "owner_metadata"
    owner_meta_path = owner_dir / f"{case_id}.owner.v1.json"

    resolved_config = {
        "schema": "ds02.f2.matched-offset-fine-labels-config.v1",
        "stage": "labels",
        "status": "resolved_ready_for_root_execution",
        "case_id": case_id,
        "resolution": info["resolution"],
        "dp_m": info["dp_m"],
        "attempt_id": attempt_id,
        "physical_condition_hash": info["physical_hash"],
        "numerical_recipe_hash": info["numerical_recipe_hash"],
        "geometry": {
            "cup_low_m": [0.0, -0.15, 0.65],
            "cup_size_m": [0.425, 0.3, 0.45],
            "receiver_low_m": [0.45, -0.16, 0.0],
            "receiver_size_m": [1.1, 0.6, 0.45],
            "receiver_offset_y_m": 0.14,
            "tray_low_m": [-1.2, -1.0, -0.2],
            "tray_size_m": [4.0, 2.0, 0.15],
            "motion_axis_origin_m": [0.0, -1.0, 0.65],
            "motion_axis_unit": [0.0, 1.0, 0.0],
        },
        "timing": {
            "event_window_s": 4.0,
            "frames": 401,
            "dt_s": 0.010,
            "save_allowance_s": SAVE_ALLOWANCE_S,
            "save_budget_relaxation_applied": False,
        },
        "mass_semantics": {
            "xml_massfluid_decimal_kg": info["xml_massfluid_decimal"],
            "xml_continuous_mass_kg": info["xml_total_fluid_mass_kg"],
            "native_float32_fluid_sum_kg": info["native_float32_fluid_sum_kg"],
            "native_representation_delta_kg": info["native_float32_fluid_sum_kg"] - info["xml_total_fluid_mass_kg"],
            "source_normalization_applied": False,
            "interpretation": (
                "Native float32 mass values are preserved unnormalized; difference from XML continuous 24.576 kg "
                "is strictly arithmetic IEEE-754 summation tolerance. Observed invalid native particles remain "
                "scientifically classified as unknown loss."
            ),
        },
        "unknown_loss_semantics": {
            "observed_native_invalid_policy": "unknown; never inferred as physical spill without geometric segment test",
            "destination_precedence": ["unknown_invalid", "cup", "receiver", "tray_after_departure", "inflight"],
            "physical_spill_inferred_from_invalid": False,
        },
        "resource_ledger": {
            "cpu_threads": 2,
            "max_wall_seconds": 3600,
            "estimated_storage_bytes": info["estimated_labels_storage_bytes"],
            "heavy_fine_cost_review_required": True,
            "root_ledger_review_note": (
                "Fine resolution dp=0.005 m with 1.67M particles and ~6.06 GB trajectory requires explicit "
                "root cost review and storage allocation before launch."
            ),
        },
        "terminal_bindings": {
            "source_trajectory_h5": binding(info["source_h5"], "source trajectory H5", known_sha=info["source_h5_sha256"]),
            "conversion_report": binding(info["conversion_report"], "conversion report", known_sha=info["conversion_report_sha256"]),
            "conversion_receipt": binding(info["conversion_receipt"], "conversion receipt", known_sha=info["conversion_receipt_sha256"]),
        },
        "pose_bindings": {
            "pose_h5": binding(pose_h5_path, "completed pose-augmented trajectory H5", known_sha=actual_pose_h5_sha),
            "pose_report": binding(pose_report_path, "completed rigid-body pose report"),
            "pose_receipt": binding(pose_receipt_path, "completed pose execution receipt"),
        },
        "inputs": {
            "xml": binding(info["xml"], "generated XML", known_sha=info["xml_sha256"]),
            "owner_metadata": binding(owner_meta_path, "owner metadata"),
        },
        "nvme_policy": {
            "scratch_parent": str(DEFAULT_SCRATCH),
            "stage_in_private_dir": True,
            "rebind_canonical_before_publish": True,
            "private_copy_deleted_after_stage": True,
        },
        "claim_boundary": {
            "q_i": "not_granted; labels evidence only",
            "q_n": "not_assessed",
            "production": "not_evaluated",
        },
        "independent_case_count_increment": 0,
        "conversion_launch_forbidden": True,
    }
    resolved_config_path = configs_dir / "offset_fine_labels_nvme_config_v1.json"
    dump_json(resolved_config_path, resolved_config)

    request_inputs = [
        Path(__file__).resolve(),
        PYTHON,
        RUNTIME,
        STRICT_DISPATCH,
        POSE_HELPER,
        V6_LABELS,
        EVENT_OPERATOR,
        EVENT_MANIFEST,
        QUALITY,
        EVENTS,
        resolved_config_path,
        pose_h5_path,
        pose_report_path,
        pose_receipt_path,
        info["xml"],
        owner_meta_path,
    ]
    unique_inputs = []
    seen = set()
    for p in request_inputs:
        res = Path(p).resolve()
        if str(res) not in seen and res.is_file():
            seen.add(str(res))
            unique_inputs.append(res)

    resolved_request = {
        "schema": "ds02.runner-request.v2",
        "family_id": "F2",
        "case_id": case_id,
        "attempt_id": attempt_id,
        "kind": "cpu",
        "cpu_task_kind": "labels",
        "cpu_threads": 2,
        "max_wall_seconds": 3600,
        "estimated_storage_bytes": info["estimated_labels_storage_bytes"],
        "cwd": str(FAMILY_ROOT),
        "worktree_root": str(FAMILY_ROOT.parents[4]),
        "command": [
            str(PYTHON),
            str(Path(__file__).resolve()),
            "run",
            "labels",
            "--config",
            str(resolved_config_path),
            "--output-dir",
            "{attempt_root}",
            "--scratch-parent",
            str(DEFAULT_SCRATCH),
        ],
        "input_files": [str(p) for p in unique_inputs],
        "input_sha256": {str(p): sha256_file(p) for p in unique_inputs},
        "claim_boundary": {
            "q_i": "not_granted; labels evidence only",
            "q_n": "not_assessed",
            "production": "not_evaluated",
        },
        "independent_case_count_increment": 0,
        "conversion_launch_forbidden": True,
        "oversize_cost_review": {
            "particle_count": info["total_particles"],
            "fluid_particles": info["fluid_particles"],
            "moving_particles": info["moving_particles"],
            "fixed_particles": info["fixed_particles"],
            "source_h5_bytes": info["source_h5_bytes"],
            "estimated_labels_h5_bytes": 850000000,
            "ledger_storage_approved_fraction": "fine labels stage requires explicit root cost review and ledger allocation prior to launch",
            "cpu_threads_bounded": 2,
            "max_wall_seconds": 3600,
        },
    }
    resolved_request_path = requests_dir / "offset_fine_labels_nvme_request_v1.json"
    dump_json(resolved_request_path, resolved_request)
    return resolved_config, resolved_request


def run_pose(config_path: Path, output_dir: Path, scratch_parent: Path) -> dict[str, Any]:
    config = load_json(config_path, "pose NVMe config")
    if config.get("stage") != "pose":
        raise PostprocessError("expected pose stage config")

    output_dir = output_dir.resolve()
    augmented_target = output_dir / "trajectory-with-actual-pose.h5"
    pose_report_target = output_dir / "rigid-body-state.json"
    if augmented_target.exists() or pose_report_target.exists():
        raise PostprocessError("pose outputs already exist; attempt directory is immutable")

    source_binding = config["terminal_bindings"]["source_trajectory_h5"]
    scratch_parent = scratch_parent.resolve()
    scratch_parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="f2-offset-fine-pose-", dir=scratch_parent) as private_dir:
        private_source = Path(private_dir) / "terminal-trajectory.h5"
        copy_evidence = verified_copy(
            Path(source_binding["path"]),
            private_source,
            str(source_binding["sha256"]),
            int(source_binding["bytes"]),
        )

        private_augmented = Path(private_dir) / "trajectory-with-actual-pose.h5"
        private_report = Path(private_dir) / "rigid-body-state.json"

        labels_mod = load_module(V6_LABELS, "f2_v6_labels_impl")
        pose_res = labels_mod.augment_pose(
            source=private_source,
            augmented=private_augmented,
            generated_xml=require_file(config["inputs"]["xml"]["path"], "generated XML"),
            motion=require_file(config["inputs"]["motion"]["path"], "motion control"),
            run_out=require_file(config["inputs"]["run_out"]["path"], "solver Run.out"),
            pose_report=private_report,
            conversion_report=require_file(config["terminal_bindings"]["conversion_report"]["path"], "conversion report"),
            solver_receipt=require_file(config["inputs"]["solver_receipt"]["path"], "solver receipt"),
            gencase_receipt=require_file(config["inputs"]["gencase_receipt"]["path"], "GenCase receipt"),
            owner_metadata=require_file(config["inputs"]["owner_metadata"]["path"], "owner metadata"),
        )
        if pose_res.get("status") != "actual_saved_moving_node_pose_complete":
            raise PostprocessError(f"pose fitter did not report complete: {pose_res}")

        # Correct immutable canonical source references in private report BEFORE publish
        report_data = load_json(private_report, "staged pose report")
        report_data["source_trajectory"] = {
            "path": source_binding["path"],
            "sha256": source_binding["sha256"],
            "bytes": source_binding["bytes"],
            "path_rebound_from_private_reader": True,
        }
        report_data["augmented_trajectory"] = {
            "path": str(augmented_target),
            "sha256": sha256_file(private_augmented),
            "bytes": int(private_augmented.stat().st_size),
        }
        report_data["nvme_source_copy"] = copy_evidence
        dump_json(private_report, report_data)

        # Publish staged files to target attempt directory atomically
        output_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(private_augmented, augmented_target)
        augmented_target.chmod(0o400)
        shutil.copyfile(private_report, pose_report_target)

    aug_binding = binding(augmented_target, "pose-augmented trajectory H5")
    manifest = {
        "schema": "ds02.f2.matched-offset-fine-pose-manifest.v1",
        "status": "completed_evidence_only",
        "case_id": config["case_id"],
        "resolution": config["resolution"],
        "physical_condition_hash": config["physical_condition_hash"],
        "numerical_recipe_hash": config["numerical_recipe_hash"],
        "pose_report": binding(pose_report_target, "rigid-body pose report"),
        "pose_h5": aug_binding,
        "q_i_status": "not_granted",
        "q_n_status": "not_assessed",
        "production_status": "not_evaluated",
    }
    manifest_path = output_dir / "postprocess-manifest.json"
    dump_json(manifest_path, manifest)
    return manifest


def run_labels(config_path: Path, output_dir: Path, scratch_parent: Path) -> dict[str, Any]:
    config = load_json(config_path, "labels NVMe config")
    if config.get("stage") != "labels":
        raise PostprocessError("expected labels stage config")

    output_dir = output_dir.resolve()
    labels_h5_target = output_dir / "f2-v6-labels.h5"
    obs_report_target = output_dir / "f2-v6-observations.json"
    if labels_h5_target.exists() or obs_report_target.exists():
        raise PostprocessError("labels outputs already exist; attempt directory is immutable")

    pose_binding = config["pose_bindings"]["pose_h5"]
    scratch_parent = scratch_parent.resolve()
    scratch_parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="f2-offset-fine-labels-", dir=scratch_parent) as private_dir:
        private_pose = Path(private_dir) / "trajectory-with-actual-pose.h5"
        copy_evidence = verified_copy(
            Path(pose_binding["path"]),
            private_pose,
            str(pose_binding["sha256"]),
            int(pose_binding["bytes"]),
        )

        private_labels = Path(private_dir) / "f2-v6-labels.h5"
        private_obs = Path(private_dir) / "f2-v6-observations.json"

        event_mod = load_module(EVENT_OPERATOR, "f2_v6_event_operator")
        obs_res = event_mod.observe(
            trajectory=private_pose,
            owner_metadata=require_file(config["inputs"]["owner_metadata"]["path"], "owner metadata"),
            output=private_labels,
            report=private_obs,
            definition_override=require_file(config["inputs"]["xml"]["path"], "generated XML"),
            numerical_recipe_hash_override=config["numerical_recipe_hash"],
            case_id_override=config["case_id"],
        )

        # Correct canonical pose references in private observation report BEFORE publish
        obs_data = load_json(private_obs, "staged observation report")
        obs_data["trajectory"] = {
            "path": pose_binding["path"],
            "sha256": pose_binding["sha256"],
            "bytes": pose_binding["bytes"],
            "path_rebound_from_private_reader": True,
        }
        obs_data["output"] = {
            "path": str(labels_h5_target),
            "sha256": sha256_file(private_labels),
            "bytes": int(private_labels.stat().st_size),
        }
        obs_data["nvme_source_copy"] = copy_evidence
        dump_json(private_obs, obs_data)

        # Publish staged files to target attempt directory atomically
        output_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(private_labels, labels_h5_target)
        labels_h5_target.chmod(0o400)
        shutil.copyfile(private_obs, obs_report_target)

    manifest = {
        "schema": "ds02.f2.matched-offset-fine-labels-manifest.v1",
        "status": "completed_evidence_only",
        "case_id": config["case_id"],
        "resolution": config["resolution"],
        "physical_condition_hash": config["physical_condition_hash"],
        "numerical_recipe_hash": config["numerical_recipe_hash"],
        "labels_h5": binding(labels_h5_target, "v6 labels H5"),
        "observations_report": binding(obs_report_target, "v6 observations report"),
        "q_i_status": "not_granted",
        "q_n_status": "not_assessed",
        "production_status": "not_evaluated",
    }
    manifest_path = output_dir / "postprocess-manifest.json"
    dump_json(manifest_path, manifest)
    return manifest


def build_all(output_root: Path | None = None) -> dict[str, Any]:
    info = FINE_CASE_INFO
    root_dir = (output_root or DEFAULT_HANDOFF_ROOT).resolve()
    configs_dir = root_dir / "configs"
    requests_dir = root_dir / "requests"
    owner_dir = root_dir / "owner_metadata"
    manifest_dir = root_dir / "manifest"

    for d in [root_dir, configs_dir, requests_dir, owner_dir, manifest_dir]:
        d.mkdir(parents=True, exist_ok=True)

    owner = build_owner_metadata(info, owner_dir)
    owner_path = owner_dir / f"{info['case_id']}.owner.v1.json"

    pose_cfg, pose_req = build_pose_stage(info, owner_path, configs_dir, requests_dir)
    lbl_cfg, lbl_tmpl = build_prospective_labels_stage(info, owner_path, configs_dir, requests_dir)

    manifest = {
        "schema": "ds02.f2.matched-offset-fine-pipeline-manifest.v1",
        "case_id": info["case_id"],
        "resolution": info["resolution"],
        "dp_m": info["dp_m"],
        "status": "pose_ready_for_root_review_labels_deferred",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "physical_condition_hash": info["physical_hash"],
        "numerical_recipe_hash": info["numerical_recipe_hash"],
        "owner_metadata": binding(owner_path, "case owner metadata"),
        "pose_stage": {
            "attempt_id": info["pose_attempt_id"],
            "config": binding(configs_dir / "offset_fine_pose_nvme_config_v1.json", "pose NVMe config"),
            "request": binding(requests_dir / "offset_fine_pose_nvme_request_v1.json", "pose runner request"),
            "status": "ready_for_root_review_and_dispatch",
        },
        "labels_stage": {
            "attempt_id": info["labels_attempt_id"],
            "config": binding(configs_dir / "offset_fine_labels_nvme_config_v1.json", "prospective labels NVMe config"),
            "template": binding(requests_dir / "offset_fine_labels_prospective_template_v1.json", "prospective labels template"),
            "status": "prospective_awaiting_root_pose_execution",
            "deferred_markers": {
                "binding_status": "deferred_until_root_execution",
                "pose_attempt_id": info["pose_attempt_id"],
            },
        },
        "resource_review": {
            "oversize_cost_review_required": True,
            "source_h5_bytes": info["source_h5_bytes"],
            "pose_peak_storage_bytes": info["estimated_pose_storage_bytes"],
            "labels_peak_storage_bytes": info["estimated_labels_storage_bytes"],
            "root_cost_review_note": (
                "Fine case with N=1,667,249 particles and ~6.06 GB trajectory requires explicit "
                "ledger review and reservation prior to root launch."
            ),
        },
    }
    manifest_path = manifest_dir / "matched_offset_fine_pipeline_manifest_v1.json"
    dump_json(manifest_path, manifest)
    print(f"Build fine OFFSET pipeline complete: {root_dir}")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)

    bld = sub.add_parser("build")
    bld.add_argument("--output-root", type=Path, default=None, help="Root directory for generated configs and requests")

    res = sub.add_parser("resolve-labels")
    res.add_argument("--pose-attempt-root", type=Path, default=None, help="Directory containing completed pose attempt")
    res.add_argument("--output-root", type=Path, default=None, help="Root directory for generated configs and requests")

    run_p = sub.add_parser("run")
    run_p.add_argument("stage", choices=["pose", "labels"])
    run_p.add_argument("--config", type=Path, required=True)
    run_p.add_argument("--output-dir", type=Path, required=True)
    run_p.add_argument("--scratch-parent", type=Path, default=DEFAULT_SCRATCH)

    args = parser.parse_args()

    if args.action == "build":
        build_all(args.output_root)
    elif args.action == "resolve-labels":
        resolve_labels_request_after_pose(args.pose_attempt_root, output_root=args.output_root)
    elif args.action == "run":
        if args.stage == "pose":
            run_pose(args.config, args.output_dir, args.scratch_parent)
        elif args.stage == "labels":
            run_labels(args.config, args.output_dir, args.scratch_parent)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
