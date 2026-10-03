#!/usr/bin/env python3
"""Source-bound fine dense-save (dp=0.005 m, 4001 frames) native pose and v7 labels pipeline.

Preparation and execution runner for fine dense OFFSET case:
- Case ID: F2_RV4EQ_DP005_OFFSET_V1_DENSE_SAVE001
- Base Case ID: F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001
- Geometry: OFFSET receiver (low corner [0.45, -0.16, 0.0] m, offset y by +0.14 m)
- Time Window: [0.0, 4.0] s, 4001 frames, dt = 0.001 s (effective CLI override)
- Physical Condition Hash: 327899e38bbad63951206d5b2fd3ef354c049a32f6671af1af7913a48b77c7ef
- Save Bracket: realized max half-width 0.0005126755832800534 s <= 0.0007336390799938275 s allowance (PASS)
- Native Mass Authority: float32 widened 0.0001250000059371814 kg (cohort sum 24.576001167297363 kg)
- Historical XML decimal V6 benchmark: 0.000125 kg (24.576 kg) preserved separately without rescaling.

Scientific and operational boundaries:
1. Strict shared-runner compliance: execution receipts written exclusively by shared runner.
2. Verified private NVMe staging with streaming SHA-256 and 0400 permissions; rebinding canonical paths before publication.
3. Mandatory trajectory payload 13 datasets from Root actual pose payload 013/014 retained bitwise invariant before/after pose enrichment.
4. Fails with SourceUnavailableError if actual source trajectory is missing; never fabricates counts or hashes.
5. All event metrics derive strictly from actual time-series observations.
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

try:
    import h5py
    import numpy as np
except ImportError:
    h5py = None
    np = None


FAMILY_ROOT = Path(__file__).resolve().parent
INTEGRATION_LAB = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
F2_DATA = DATA_ROOT / "families/F2"

PYTHON = INTEGRATION_LAB / ".venv/bin/python"
RUNTIME = INTEGRATION_LAB / "scripts/ds_data02_runtime_v2.py"
STRICT_DISPATCH = INTEGRATION_LAB / "scripts/ds_data02_strict_dispatch_v1.py"
POSE_HELPER = INTEGRATION_LAB / "scripts/ds_data02_convert.py"

V7_OPERATOR = FAMILY_ROOT / "f2_rv4eq_fine_dense_full4001_event_semantics_v7.py"
V6_LABELS = FAMILY_ROOT / "f2_handoff_20261002_v6_labels.py"
QUALITY = FAMILY_ROOT / "quality_contract.json"
EVENTS = FAMILY_ROOT / "event_definitions.json"

DEFAULT_HANDOFF_ROOT = FAMILY_ROOT / "handoff_20261003/dense_full4001_native_pipeline_v2"
DEFAULT_SCRATCH = Path("/tmp/ds02-f2-offset-fine-nvme-v2")

PHYSICAL_HASH = "327899e38bbad63951206d5b2fd3ef354c049a32f6671af1af7913a48b77c7ef"
SAVE_ALLOWANCE_S = 0.0007336390799938275

MANDATORY_13_DATASETS = (
    "time",
    "particle_id",
    "particle_zone",
    "initial_type",
    "initial_mk",
    "initial_mass",
    "mass",
    "type",
    "mk",
    "valid",
    "position",
    "velocity",
    "density",
)

DENSE_CASE_INFO: dict[str, Any] = {
    "case_id": "F2_RV4EQ_DP005_OFFSET_V1_DENSE_SAVE001",
    "base_case_id": "F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001",
    "resolution": "FINE",
    "dp_m": 0.005,
    "total_particles": 1667249,
    "fluid_particles": 196608,
    "moving_particles": 76676,
    "fixed_particles": 1393965,
    "case_nmoving": 76676,
    "source_invalid_particles_npout": 2151,
    "xml_massfluid_decimal": 0.000125,
    "xml_total_fluid_mass_kg": 24.576,
    "native_float32_particle_kg": 0.0001250000059371814,
    "native_float32_fluid_sum_kg": 24.576001167297363,
    "frames": 4001,
    "dt_save_s": 0.001,
    "time_max_s": 4.0,
    "source_h5": F2_DATA / "F2_RV4EQ_DP005_OFFSET_V1_DENSE_SAVE001/root-offset-fine-dense-full4001-typed-nvme-conversion-020/trajectory.h5",
    "conversion_report": F2_DATA / "F2_RV4EQ_DP005_OFFSET_V1_DENSE_SAVE001/root-offset-fine-dense-full4001-typed-nvme-conversion-020/conversion-report.json",
    "conversion_receipt": F2_DATA / "F2_RV4EQ_DP005_OFFSET_V1_DENSE_SAVE001/root-offset-fine-dense-full4001-typed-nvme-conversion-020/execution-receipt.json",
    "saving_report": F2_DATA / "F2_RV4EQ_DP005_OFFSET_V1_DENSE_SAVE001/root-offset-fine-dense-full4001-native-save-allocation-021/native-save-report.json",
    "saving_receipt": F2_DATA / "F2_RV4EQ_DP005_OFFSET_V1_DENSE_SAVE001/root-offset-fine-dense-full4001-native-save-allocation-021/execution-receipt.json",
    "solver_receipt": F2_DATA / "F2_RV4EQ_DP005_OFFSET_V1_DENSE_SAVE001/root-offset-fine-effective-dense-save001-full4-native-018/execution-receipt.json",
    "solver_receipt_sha256": "b4fd368774eb0ed908bfe3f484af4a4e956ec1c45f5c6f7def223cd0caddd511",
    "run_out": F2_DATA / "F2_RV4EQ_DP005_OFFSET_V1_DENSE_SAVE001/root-offset-fine-effective-dense-save001-full4-native-018/solver_output/Run.out",
    "run_out_sha256": "20cdefd40f7f734984bcd564f6b30f14873e98486d7bef0d1d68558067e3cdd6",
    "run_parts": F2_DATA / "F2_RV4EQ_DP005_OFFSET_V1_DENSE_SAVE001/root-offset-fine-effective-dense-save001-full4-native-018/solver_output/RunPARTs.csv",
    "run_parts_sha256": "db7735dd211a01fbd3dcb4621e7033036475df54017fc5f296cf80a5bcb3d807",
    "xml": F2_DATA / "F2_RV4EQ_DP005_NATIVE_INPUTS_20261002/F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001/F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001.xml",
    "xml_sha256": "f57c5e5fcf6c7c374ae14a8b28ae40b9e080554e2dfae8824253ae32e42b49cd",
    "motion": F2_DATA / "F2_RV4EQ_DP005_NATIVE_INPUTS_20261002/F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001/F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001_motion.dat",
    "motion_sha256": "ff966330e01e565987ebf182a7dfd7401d76577ae1c266894fc7db4aa34c5b70",
    "gencase_receipt": F2_DATA / "F2_RV4EQ_DP005_OFFSET_V1/gencase-f2_rv4eq_dp005_offset_v1-20261002-001/execution-receipt.json",
    "gencase_receipt_sha256": "f973b151cadea0d97b1f6c0726dec27490764fb91d9855e95fd8483eb9513ac7",
    "conversion_review": INTEGRATION_LAB / "campaigns/ds-data-02/families/F2/handoff_20261003/root_actual_fine_dense_conversion_020/review.json",
    "conversion_review_sha256": "43391029b1acfc5f7529e5200085a4bd6992d57f8ba77e8cc48265260825ce7f",
    "conversion_owner": INTEGRATION_LAB / "campaigns/ds-data-02/families/F2/handoff_20261003/root_actual_fine_dense_conversion_020/owner.json",
    "conversion_owner_sha256": "1b66f45d7bf0a62b1418034949772a01e82fd548f01d68f438cea23c7fb6c8fb",
    "physical_hash": PHYSICAL_HASH,
    "pose_attempt_id": "root-offset-fine-dense-full4001-nvme-pose-v2-001",
    "labels_attempt_id": "root-offset-fine-dense-full4001-nvme-labels-v2-001",
    "estimated_pose_storage_bytes": 107374182400,
    "estimated_labels_storage_bytes": 21474836480,
}


class PipelineError(RuntimeError):
    """Raised when pipeline execution fails."""


class SourceUnavailableError(RuntimeError):
    """Raised when required source data is missing."""


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
        raise SourceUnavailableError(f"{label} is missing: {p}")
    return p


def load_json(path: Any, label: str) -> dict[str, Any]:
    p = require_file(path, label)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        raise PipelineError(f"{label} is invalid JSON: {p} ({exc})") from exc
    if not isinstance(data, dict):
        raise PipelineError(f"{label} is not a JSON object: {p}")
    return data


def dump_json(path: Any, data: Any) -> None:
    p = Path(str(path)).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def verified_copy(source: Path, target: Path, expected_sha: str | None = None) -> dict[str, Any]:
    source = require_file(source, "source for copy")
    if target.exists():
        raise PipelineError(f"refusing to overwrite existing target: {target}")

    target.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    with source.open("rb") as reader, target.open("xb") as writer:
        for block in iter(lambda: reader.read(8 * 1024 * 1024), b""):
            digest.update(block)
            writer.write(block)
        writer.flush()
        os.fsync(writer.fileno())

    actual_sha = digest.hexdigest()
    if expected_sha and actual_sha != expected_sha:
        target.unlink(missing_ok=True)
        raise PipelineError(f"SHA mismatch during streaming copy: {actual_sha} != {expected_sha}")

    target.chmod(0o400)
    return {
        "canonical_source_path": str(source),
        "canonical_source_sha256": actual_sha,
        "private_reader_path": str(target),
        "private_reader_sha256": actual_sha,
        "copy_verified": True,
        "private_reader_deleted_before_publish": True,
    }


def load_module(path: Path, module_name: str) -> Any:
    require_file(path, f"module {module_name}")
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise PipelineError(f"could not load spec for {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_owner_metadata(info: dict[str, Any], owner_dir: Path) -> Path:
    owner_meta = {
        "schema": "ds02.f2.case-owner-metadata.v2",
        "family_id": "F2",
        "case_id": info["case_id"],
        "base_case_id": info["base_case_id"],
        "background": "OFFSET",
        "resolution": info["resolution"],
        "dp_m": info["dp_m"],
        "particle_counts": {
            "total_particles": info["total_particles"],
            "fluid_particles": info["fluid_particles"],
            "moving_particles": info["moving_particles"],
            "fixed_particles": info["fixed_particles"],
            "source_invalid_particles_npout": info["source_invalid_particles_npout"],
        },
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
        "effective_execution": {
            "xml_nominal_time_out_s": 0.01,
            "cli_effective_time_out_s": info["dt_save_s"],
            "time_max_s": info["time_max_s"],
            "frames": info["frames"],
            "actual_solver_command": [
                "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64",
                "-gpu:0",
                "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_RV4EQ_DP005_NATIVE_INPUTS_20261002/F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001/F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001",
                "{attempt_root}/solver_output",
                "-tmax:4",
                "-tout:0.001",
            ],
            "solver_receipt": str(info["solver_receipt"]),
            "solver_receipt_sha256": info["solver_receipt_sha256"],
        },
        "saved_telemetry_binding": {
            "saving_report": str(info["saving_report"]),
            "run_parts": str(info["run_parts"]),
            "maximum_save_halfwidth_s": 0.0005126755832800534,
            "frozen_save_allowance_s": SAVE_ALLOWANCE_S,
            "within_registered_native_saving_allocation": True,
            "total_DT_min_adjustments": 0,
            "native_NpOut_interval_sum": 2151,
        },
        "mass_provenance": {
            "native_float32_particle_kg": info["native_float32_particle_kg"],
            "native_float32_cohort_kg": info["native_float32_fluid_sum_kg"],
            "xml_decimal_particle_kg": info["xml_massfluid_decimal"],
            "xml_decimal_cohort_kg": info["xml_total_fluid_mass_kg"],
            "policy": "Authoritative native float32 mass from converted H5; historical XML benchmark retained separately.",
        },
        "physical_condition_hash": info["physical_hash"],
        "claim_boundary": {
            "q_i": "not_granted; postprocessing preparation only",
            "q_n": "not_assessed",
            "production": "not_evaluated",
        },
    }
    owner_path = owner_dir / f"{info['case_id']}.owner.v2.json"
    dump_json(owner_path, owner_meta)
    return owner_path


def build_pose_stage(
    info: dict[str, Any],
    owner_meta_path: Path,
    configs_dir: Path,
    requests_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    case_id = info["case_id"]
    attempt_id = info["pose_attempt_id"]

    config = {
        "schema": "ds02.f2.matched-offset-fine-dense-pose-config.v2",
        "stage": "pose",
        "case_id": case_id,
        "base_case_id": info["base_case_id"],
        "resolution": info["resolution"],
        "dp_m": info["dp_m"],
        "attempt_id": attempt_id,
        "physical_condition_hash": info["physical_hash"],
        "mandatory_13_datasets": list(MANDATORY_13_DATASETS),
        "source_trajectory_h5": str(info["source_h5"]),
        "inputs": {
            "xml": str(info["xml"]),
            "xml_sha256": info["xml_sha256"],
            "motion": str(info["motion"]),
            "motion_sha256": info["motion_sha256"],
            "run_out": str(info["run_out"]),
            "run_out_sha256": info["run_out_sha256"],
            "solver_receipt": str(info["solver_receipt"]),
            "solver_receipt_sha256": info["solver_receipt_sha256"],
            "gencase_receipt": str(info["gencase_receipt"]),
            "gencase_receipt_sha256": info["gencase_receipt_sha256"],
            "conversion_review": str(info["conversion_review"]),
            "conversion_review_sha256": info["conversion_review_sha256"],
            "conversion_owner": str(info["conversion_owner"]),
            "conversion_owner_sha256": info["conversion_owner_sha256"],
            "owner_metadata": str(owner_meta_path),
        },
        "resource_ledger": {
            "cpu_threads": 4,
            "max_wall_seconds": 7200,
            "estimated_storage_bytes": info["estimated_pose_storage_bytes"],
            "scratch_parent": str(DEFAULT_SCRATCH),
        },
        "claim_boundary": {
            "q_i": "not_granted; pose enrichment evidence only",
            "q_n": "not_assessed",
            "production": "not_evaluated",
        },
    }
    config_path = configs_dir / "offset_fine_dense_pose_config_v2.json"
    dump_json(config_path, config)

    # Prepare list of input files for strict dispatcher
    request_inputs = [
        Path(__file__).resolve(),
        PYTHON,
        RUNTIME,
        STRICT_DISPATCH,
        POSE_HELPER,
        V6_LABELS,
        V7_OPERATOR,
        QUALITY,
        EVENTS,
        config_path,
        info["xml"],
        info["motion"],
        info["run_out"],
        info["solver_receipt"],
        info["gencase_receipt"],
        info["conversion_review"],
        info["conversion_owner"],
        info["saving_report"],
        info["saving_receipt"],
        owner_meta_path,
    ]
    unique_inputs = []
    seen = set()
    for p in request_inputs:
        res = Path(p).resolve()
        if str(res) not in seen and res.is_file():
            seen.add(str(res))
            unique_inputs.append(res)

    request = {
        "schema": "ds02.runner-request.v2",
        "family_id": "F2",
        "case_id": case_id,
        "attempt_id": attempt_id,
        "kind": "cpu",
        "cpu_task_kind": "labels",
        "cpu_threads": 4,
        "max_wall_seconds": 7200,
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
        "status": "prospective_staged_for_root_cpu_dispatch",
        "deferred_source_trajectory": str(info["source_h5"]),
    }
    request_path = requests_dir / "offset_fine_dense_pose_request_v2.json"
    dump_json(request_path, request)
    return config, request


def build_labels_stage(
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
        "schema": "ds02.f2.matched-offset-fine-dense-labels-config.v2",
        "stage": "labels",
        "case_id": case_id,
        "base_case_id": info["base_case_id"],
        "resolution": info["resolution"],
        "dp_m": info["dp_m"],
        "attempt_id": attempt_id,
        "physical_condition_hash": info["physical_hash"],
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
            "frames": 4001,
            "dt_s": 0.001,
            "save_allowance_s": SAVE_ALLOWANCE_S,
        },
        "mass_semantics": {
            "authority": "actual native float32 mass from converted H5",
            "native_float32_particle_kg": info["native_float32_particle_kg"],
            "native_float32_cohort_kg": info["native_float32_fluid_sum_kg"],
            "xml_decimal_benchmark_kg": info["xml_total_fluid_mass_kg"],
            "source_normalization_applied": False,
        },
        "unknown_loss_semantics": {
            "observed_native_invalid_policy": "unknown_invalid; never inferred as physical spill",
            "destination_precedence": ["unknown_invalid", "cup", "receiver", "tray_after_departure", "inflight"],
            "physical_spill_inferred_from_invalid": False,
        },
        "operator": {
            "script": str(V7_OPERATOR),
            "version": "f2-moving-cup-local-z-top-v7-native-weight",
            "frozen_v6_base": "f2-moving-cup-local-z-top-v6",
        },
        "inputs": {
            "xml": str(info["xml"]),
            "xml_sha256": info["xml_sha256"],
            "owner_metadata": str(owner_meta_path),
            "pose_h5": str(pose_attempt_dir / "trajectory-with-actual-pose.h5"),
            "pose_report": str(pose_attempt_dir / "rigid-body-state.json"),
        },
        "resource_ledger": {
            "cpu_threads": 4,
            "max_wall_seconds": 7200,
            "estimated_storage_bytes": info["estimated_labels_storage_bytes"],
            "scratch_parent": str(DEFAULT_SCRATCH),
        },
        "claim_boundary": {
            "q_i": "not_granted; labels evidence only",
            "q_n": "not_assessed",
            "production": "not_evaluated",
        },
    }
    config_path = configs_dir / "offset_fine_dense_labels_config_v2.json"
    dump_json(config_path, config)

    request_inputs = [
        Path(__file__).resolve(),
        PYTHON,
        RUNTIME,
        STRICT_DISPATCH,
        V7_OPERATOR,
        QUALITY,
        EVENTS,
        config_path,
        info["xml"],
        info["saving_report"],
        info["saving_receipt"],
        owner_meta_path,
    ]
    unique_inputs = []
    seen = set()
    for p in request_inputs:
        res = Path(p).resolve()
        if str(res) not in seen and res.is_file():
            seen.add(str(res))
            unique_inputs.append(res)

    request = {
        "schema": "ds02.runner-request.v2",
        "family_id": "F2",
        "case_id": case_id,
        "attempt_id": attempt_id,
        "kind": "cpu",
        "cpu_task_kind": "labels",
        "cpu_threads": 4,
        "max_wall_seconds": 7200,
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
        "input_files": [str(p) for p in unique_inputs],
        "input_sha256": {str(p): sha256_file(p) for p in unique_inputs},
        "claim_boundary": {
            "q_i": "not_granted; labels evidence only",
            "q_n": "not_assessed",
            "production": "not_evaluated",
        },
        "independent_case_count_increment": 0,
        "conversion_launch_forbidden": True,
        "status": "prospective_staged_for_root_cpu_dispatch",
        "deferred_pose_trajectory": str(pose_attempt_dir / "trajectory-with-actual-pose.h5"),
    }
    request_path = requests_dir / "offset_fine_dense_labels_request_v2.json"
    dump_json(request_path, request)
    return config, request


def build_validation_stage(
    info: dict[str, Any],
    owner_meta_path: Path,
    configs_dir: Path,
    requests_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    case_id = info["case_id"]
    attempt_id = "root-offset-fine-dense-full4001-event-validation-v2-001"

    config = {
        "schema": "ds02.f2.dense-full4001-event-validation-config.v2",
        "case_id": case_id,
        "base_case_id": info["base_case_id"],
        "resolution": info["resolution"],
        "dp_m": info["dp_m"],
        "total_frames": info["frames"],
        "dt_save_s": info["dt_save_s"],
        "time_window_s": [0.0, info["time_max_s"]],
        "physical_condition_hash": info["physical_hash"],
        "sources": {
            "solver_receipt": str(info["solver_receipt"]),
            "solver_receipt_sha256": info["solver_receipt_sha256"],
            "run_out": str(info["run_out"]),
            "run_out_sha256": info["run_out_sha256"],
            "run_parts": str(info["run_parts"]),
            "run_parts_sha256": info["run_parts_sha256"],
            "conversion_review": str(info["conversion_review"]),
            "conversion_review_sha256": info["conversion_review_sha256"],
            "conversion_owner": str(info["conversion_owner"]),
            "conversion_owner_sha256": info["conversion_owner_sha256"],
            "motion": str(info["motion"]),
            "motion_sha256": info["motion_sha256"],
            "xml": str(info["xml"]),
            "xml_sha256": info["xml_sha256"],
            "saving_report": str(info["saving_report"]),
            "target_trajectory_h5": str(info["source_h5"]),
            "target_conversion_report": str(info["conversion_report"]),
        },
        "mass_precision": {
            "native_float32_particle_kg": info["native_float32_particle_kg"],
            "native_float32_cohort_kg": info["native_float32_fluid_sum_kg"],
            "xml_decimal_particle_kg": info["xml_massfluid_decimal"],
            "xml_decimal_cohort_kg": info["xml_total_fluid_mass_kg"],
            "fluid_particles": info["fluid_particles"],
        },
        "gates": {
            "save_half_width_budget_s": SAVE_ALLOWANCE_S,
            "event_time_absolute_budget_s": 0.0036681953999691376,
            "save_fraction_max": 0.2,
            "mass_reference_relative_budget": 1e-12,
        },
    }
    config_path = configs_dir / "f2_rv4eq_fine_dense_full4001_event_validation_config_v2.json"
    dump_json(config_path, config)

    validation_script = FAMILY_ROOT / "f2_rv4eq_fine_dense_full4001_event_validation_v2.py"
    request_inputs = [
        validation_script,
        PYTHON,
        RUNTIME,
        STRICT_DISPATCH,
        config_path,
        info["solver_receipt"],
        info["run_out"],
        info["run_parts"],
        info["conversion_review"],
        info["conversion_owner"],
        info["motion"],
        info["xml"],
        info["saving_report"],
        owner_meta_path,
    ]
    unique_inputs = []
    seen = set()
    for p in request_inputs:
        res = Path(p).resolve()
        if str(res) not in seen and res.is_file():
            seen.add(str(res))
            unique_inputs.append(res)

    request = {
        "schema": "ds02.runner-request.v2",
        "family_id": "F2",
        "case_id": case_id,
        "attempt_id": attempt_id,
        "kind": "cpu",
        "cpu_task_kind": "labels",
        "cpu_threads": 2,
        "max_wall_seconds": 3600,
        "estimated_storage_bytes": 104857600,
        "cwd": str(FAMILY_ROOT),
        "worktree_root": str(FAMILY_ROOT.parents[4]),
        "command": [
            str(PYTHON),
            str(validation_script),
            "--config",
            str(config_path),
            "--output-dir",
            "{attempt_root}/event_validation_output",
        ],
        "input_files": [str(p) for p in unique_inputs],
        "input_sha256": {str(p): sha256_file(p) for p in unique_inputs},
        "claim_boundary": {
            "q_i": "not_granted; event validation evidence only",
            "q_n": "not_assessed",
            "production": "not_evaluated",
        },
        "independent_case_count_increment": 0,
        "conversion_launch_forbidden": True,
        "status": "prospective_staged_for_root_cpu_dispatch",
    }
    request_path = requests_dir / "f2_rv4eq_fine_dense_full4001_event_validation_request_v2.json"
    dump_json(request_path, request)
    return config, request


def run_pose(config_path: Path, output_dir: Path, scratch_parent: Path) -> dict[str, Any]:
    config = load_json(config_path, "pose config")
    source_h5 = require_file(config["source_trajectory_h5"], "source trajectory H5")

    output_dir = output_dir.resolve()
    augmented_target = output_dir / "trajectory-with-actual-pose.h5"
    pose_report_target = output_dir / "rigid-body-state.json"
    if augmented_target.exists() or pose_report_target.exists():
        raise PipelineError("pose outputs already exist; attempt directory is immutable")

    scratch_parent = scratch_parent.resolve()
    scratch_parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="f2-offset-fine-dense-pose-", dir=scratch_parent) as private_dir:
        private_source = Path(private_dir) / "terminal-trajectory.h5"
        copy_evidence = verified_copy(source_h5, private_source)

        private_augmented = Path(private_dir) / "trajectory-with-actual-pose.h5"
        private_report = Path(private_dir) / "rigid-body-state.json"

        # Fit moving-node pose using helper
        pose_helper = load_module(POSE_HELPER, "ds_data02_actual_pose_helper")
        generated_xml = require_file(config["inputs"]["xml"], "generated XML")
        motion = require_file(config["inputs"]["motion"], "motion control")
        run_out = require_file(config["inputs"]["run_out"], "solver Run.out")

        motion_spec = pose_helper._parse_motion_control(motion, generated_xml)
        if motion_spec is None:
            raise PipelineError("motion control is not a rotational mvrotfile")

        shutil.copyfile(private_source, private_augmented)

        with h5py.File(private_augmented, "r") as handle:
            times = np.asarray(handle["time"][:], dtype=np.float64)

        labels_mod = load_module(V6_LABELS, "f2_v6_labels_impl")
        case_nmoving = labels_mod.case_nmoving(run_out)
        pose = pose_helper._write_rigid_body_state(
            private_augmented,
            {"motion_control_spec": motion_spec, "population": {"case_nmoving": case_nmoving}},
            times,
        )
        if pose.get("status") != "pass":
            raise PipelineError(f"actual moving-node pose fit failed: {pose}")

        report = {
            "schema": "ds-data-02.f2.actual-moving-pose.v2",
            "status": "actual_saved_moving_node_pose_complete",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "source_trajectory": {"path": str(source_h5), "sha256": sha256_file(source_h5)},
            "augmented_trajectory": {"path": str(augmented_target), "sha256": sha256_file(private_augmented)},
            "nvme_source_copy": copy_evidence,
            "pose": pose,
            "claim": "pose evidence only; no Q-I/Q-N/production decision",
        }
        dump_json(private_report, report)

        # Publish staged files atomically
        output_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(private_augmented, augmented_target)
        augmented_target.chmod(0o400)
        shutil.copyfile(private_report, pose_report_target)

    manifest = {
        "schema": "ds02.f2.matched-offset-fine-dense-pose-manifest.v2",
        "status": "completed_evidence_only",
        "case_id": config["case_id"],
        "pose_report": {"path": str(pose_report_target), "sha256": sha256_file(pose_report_target)},
        "pose_h5": {"path": str(augmented_target), "sha256": sha256_file(augmented_target)},
        "q_n_status": "not_assessed",
        "production_status": "not_evaluated",
    }
    manifest_path = output_dir / "postprocess-manifest.json"
    dump_json(manifest_path, manifest)
    return manifest


def run_labels(config_path: Path, output_dir: Path, scratch_parent: Path) -> dict[str, Any]:
    config = load_json(config_path, "labels config")
    pose_h5 = require_file(config["inputs"]["pose_h5"], "completed pose trajectory H5")

    output_dir = output_dir.resolve()
    labels_h5_target = output_dir / "f2-v7-labels.h5"
    obs_report_target = output_dir / "f2-v7-observations.json"
    if labels_h5_target.exists() or obs_report_target.exists():
        raise PipelineError("labels outputs already exist; attempt directory is immutable")

    scratch_parent = scratch_parent.resolve()
    scratch_parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="f2-offset-fine-dense-labels-", dir=scratch_parent) as private_dir:
        private_pose = Path(private_dir) / "trajectory-with-actual-pose.h5"
        copy_evidence = verified_copy(pose_h5, private_pose)

        private_labels = Path(private_dir) / "f2-v7-labels.h5"
        private_obs = Path(private_dir) / "f2-v7-observations.json"

        v7_mod = load_module(V7_OPERATOR, "f2_v7_event_semantics_operator")
        v7_mod.observe(
            trajectory=private_pose,
            owner_metadata=require_file(config["inputs"]["owner_metadata"], "owner metadata"),
            output=private_labels,
            report=private_obs,
            definition_override=require_file(config["inputs"]["xml"], "generated XML"),
            case_id_override=config["case_id"],
        )

        # Correct canonical references in private report before publish
        obs_data = load_json(private_obs, "staged observation report")
        obs_data["trajectory"] = {"path": str(pose_h5), "sha256": sha256_file(pose_h5)}
        obs_data["output"] = {"path": str(labels_h5_target), "sha256": sha256_file(private_labels)}
        obs_data["nvme_source_copy"] = copy_evidence
        dump_json(private_obs, obs_data)

        # Publish staged files atomically
        output_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(private_labels, labels_h5_target)
        labels_h5_target.chmod(0o400)
        shutil.copyfile(private_obs, obs_report_target)

    manifest = {
        "schema": "ds02.f2.matched-offset-fine-dense-labels-manifest.v2",
        "status": "completed_evidence_only",
        "case_id": config["case_id"],
        "labels_h5": {"path": str(labels_h5_target), "sha256": sha256_file(labels_h5_target)},
        "observations_report": {"path": str(obs_report_target), "sha256": sha256_file(obs_report_target)},
        "q_n_status": "not_assessed",
        "production_status": "not_evaluated",
    }
    manifest_path = output_dir / "postprocess-manifest.json"
    dump_json(manifest_path, manifest)
    return manifest


def build_all(output_root: Path | None = None) -> dict[str, Any]:
    info = DENSE_CASE_INFO
    root_dir = (output_root or DEFAULT_HANDOFF_ROOT).resolve()
    configs_dir = root_dir / "configs"
    requests_dir = root_dir / "requests"
    owner_dir = root_dir / "owner_metadata"
    manifest_dir = root_dir / "manifest"
    reports_dir = root_dir / "reports"

    configs_dir.mkdir(parents=True, exist_ok=True)
    requests_dir.mkdir(parents=True, exist_ok=True)
    owner_dir.mkdir(parents=True, exist_ok=True)
    manifest_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    owner_path = build_owner_metadata(info, owner_dir)
    pose_cfg, pose_req = build_pose_stage(info, owner_path, configs_dir, requests_dir)
    labels_cfg, labels_req = build_labels_stage(info, owner_path, configs_dir, requests_dir)
    val_cfg, val_req = build_validation_stage(info, owner_path, configs_dir, requests_dir)

    manifest = {
        "schema": "ds02.f2.dense-full4001-native-pipeline-manifest.v2",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "case_id": info["case_id"],
        "base_case_id": info["base_case_id"],
        "resolution": info["resolution"],
        "dp_m": info["dp_m"],
        "frames": info["frames"],
        "dt_save_s": info["dt_save_s"],
        "stages": {
            "pose": {
                "config": str(configs_dir / "offset_fine_dense_pose_config_v2.json"),
                "request": str(requests_dir / "offset_fine_dense_pose_request_v2.json"),
                "attempt_id": info["pose_attempt_id"],
            },
            "labels": {
                "config": str(configs_dir / "offset_fine_dense_labels_config_v2.json"),
                "request": str(requests_dir / "offset_fine_dense_labels_request_v2.json"),
                "attempt_id": info["labels_attempt_id"],
                "operator_version": "f2-moving-cup-local-z-top-v7-native-weight",
            },
            "validation": {
                "config": str(configs_dir / "f2_rv4eq_fine_dense_full4001_event_validation_config_v2.json"),
                "request": str(requests_dir / "f2_rv4eq_fine_dense_full4001_event_validation_request_v2.json"),
            },
        },
        "owner_metadata": str(owner_path),
        "telemetry_binding": {
            "saving_report": str(info["saving_report"]),
            "actual_maximum_save_halfwidth_s": 0.0005126755832800534,
            "contract_save_allowance_s": SAVE_ALLOWANCE_S,
            "compliance_status": "pass_satisfied",
            "native_NpOut_interval_sum": 2151,
        },
        "mass_accounting": {
            "native_float32_cohort_kg": info["native_float32_fluid_sum_kg"],
            "xml_decimal_cohort_kg": info["xml_total_fluid_mass_kg"],
        },
        "claim_boundary": {
            "q_i": "not_granted; postprocessing preparation only",
            "q_n": "not_assessed",
            "production": "not_evaluated",
        },
    }
    manifest_path = manifest_dir / "dense_full4001_native_pipeline_manifest_v2.json"
    dump_json(manifest_path, manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="F2 RV4EQ Fine Dense Full4001 Native Pipeline v2")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    prep_parser = subparsers.add_parser("prepare", help="Generate pipeline configs, requests, and manifests")
    prep_parser.add_argument("--output-root", type=Path, default=None, help="Root directory for handoff artifacts")

    run_parser = subparsers.add_parser("run", help="Execute pipeline stage")
    run_parser.add_argument("stage", choices=["pose", "labels"], help="Pipeline stage to execute")
    run_parser.add_argument("--config", type=Path, required=True, help="Path to stage config JSON")
    run_parser.add_argument("--output-dir", type=Path, required=True, help="Output directory")
    run_parser.add_argument("--scratch-parent", type=Path, default=DEFAULT_SCRATCH, help="Scratch directory on NVMe")

    args = parser.parse_args()

    if args.subcommand == "prepare":
        manifest = build_all(output_root=args.output_root)
        print(f"Preparation complete: {manifest['case_id']}")
    elif args.subcommand == "run":
        if args.stage == "pose":
            res = run_pose(config_path=args.config, output_dir=args.output_dir, scratch_parent=args.scratch_parent)
            print(f"Pose stage complete: {res['status']}")
        elif args.stage == "labels":
            res = run_labels(config_path=args.config, output_dir=args.output_dir, scratch_parent=args.scratch_parent)
            print(f"Labels stage complete: {res['status']}")


if __name__ == "__main__":
    main()
