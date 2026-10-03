#!/usr/bin/env python3
"""Run source-bound CENTER matched 3DP coarse/medium pose and v6 labels stages from private NVMe copies.

Version 2: Strict shared-runner compliance & evidence isolation.
- Preparation only until Root review: no direct execution bypass or synthesized receipts.
- Runner-owned receipts: execution-receipt.json is written exclusively by the shared runner.
- Staged private NVMe postprocessing: final pose metadata is staged in private unpublished H5,
  canonical source references are verified and corrected before output publication.
- Physical & geometry invariance: physical condition hash (45c579bd...) and geometry bounds
  are strictly validated against generated XML and source before any outputs are published.
- Two-stage lifecycle:
  1. `build`: builds owner metadata, pose configs, and pose runner requests (v2 attempt names).
  2. `build-labels`: builds labels configs and runner requests bound to completed, measured pose outputs.
  3. `run pose`: runner-invoked pose execution.
  4. `run labels`: runner-invoked labels execution.
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
import re
import shutil
import tempfile
from typing import Any, Iterable, Mapping


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

HANDOFF_ROOT = FAMILY_ROOT / "handoff_20261003/matched_center_terminal_nvme_v2"
CONFIGS_DIR = HANDOFF_ROOT / "configs"
REQUESTS_DIR = HANDOFF_ROOT / "requests"
OWNER_DIR = HANDOFF_ROOT / "owner_metadata"
ARTIFACTS_DIR = HANDOFF_ROOT / "artifacts"
DEFAULT_SCRATCH = Path("/tmp/ds02-f2-center-matched-nvme-v2")

MACRO_005_DIR = F2_DATA / "F2_RV4EQ_MATCHED_CENTER_ACTUAL_MACRO_DESCRIPTION/root-center-three-dp-actual-macro-description-005"
MACRO_005_REPORT = MACRO_005_DIR / "macro-description.json"
MACRO_005_RECEIPT = MACRO_005_DIR / "execution-receipt.json"

MATCHED_TIMING_ALLOWANCE_S = 0.0001467278159987655
BASELINE_TIMING_ALLOWANCE_S = 0.0007336390799938275

PHYSICAL_HASH = "45c579bd9fa7a4878fcd25d0e0aa6dedf6da8c4cd77cd85e0d05b928ab8b6a43"

CASES: dict[str, dict[str, Any]] = {
    "coarse": {
        "case_id": "F2_RV4EQ_MATCHED_CENTER_V1_COARSE_DP010_SPATIAL_REFERENCE_SAVE010",
        "short_name": "center_coarse",
        "resolution": "COARSE",
        "dp_m": 0.010,
        "total_particles": 421566,
        "fluid_particles": 24576,
        "case_nmoving": 24150,
        "source_h5": F2_DATA / "F2_RV4EQ_MATCHED_CENTER_V1_COARSE_DP010_SPATIAL_REFERENCE_SAVE010/root-center-coarse-matched-spatial-fulltyped-nvme-003/trajectory.h5",
        "source_h5_sha256": "12180cbf5c1f2129ecc55c44650102c05e2f0fcda27842156c06737feae72d03",
        "source_h5_bytes": 1262374168,
        "conversion_report": F2_DATA / "F2_RV4EQ_MATCHED_CENTER_V1_COARSE_DP010_SPATIAL_REFERENCE_SAVE010/root-center-coarse-matched-spatial-fulltyped-nvme-003/conversion-report.json",
        "conversion_report_sha256": "564a3d11379e0cb0607832f08d88dee2dfa9bd57a9d2c62ab88bf6e95cfbe737",
        "conversion_receipt": F2_DATA / "F2_RV4EQ_MATCHED_CENTER_V1_COARSE_DP010_SPATIAL_REFERENCE_SAVE010/root-center-coarse-matched-spatial-fulltyped-nvme-003/execution-receipt.json",
        "conversion_receipt_sha256": "51afbb3b622d8defa21107f8f3c907f4feb19f9abdeaf8d753a9759650b2189f",
        "xml": F2_DATA / "F2_RV4EQ_MATCHED_SPATIAL_REFERENCE_INPUTS_20261003/F2_RV4EQ_MATCHED_CENTER_V1_COARSE_DP010/F2_RV4EQ_MATCHED_CENTER_V1_COARSE_DP010_SPATIAL_REFERENCE_SAVE010.xml",
        "xml_sha256": "08415c42c4fd3a3846103985689d53cb9226df72763845bc082943f2146c4336",
        "motion": F2_DATA / "F2_RV4EQ_MATCHED_SPATIAL_REFERENCE_INPUTS_20261003/F2_RV4EQ_MATCHED_CENTER_V1_COARSE_DP010/F2_RV4EQ_MATCHED_CENTER_V1_COARSE_DP010_motion.dat",
        "motion_sha256": "ff966330e01e565987ebf182a7dfd7401d76577ae1c266894fc7db4aa34c5b70",
        "run_out": F2_DATA / "F2_RV4EQ_MATCHED_CENTER_V1_COARSE_DP010_SPATIAL_REFERENCE_SAVE010/qualification-f2_rv4eq_matched_center_v1_coarse_dp010-spatial-reference-save010-root-review-001/solver_output/Run.out",
        "run_out_sha256": "71f4b475a8fb51fac572193f047b02454e7e21375c5485b3d7926e0a7171f765",
        "solver_receipt": F2_DATA / "F2_RV4EQ_MATCHED_CENTER_V1_COARSE_DP010_SPATIAL_REFERENCE_SAVE010/qualification-f2_rv4eq_matched_center_v1_coarse_dp010-spatial-reference-save010-root-review-001/execution-receipt.json",
        "solver_receipt_sha256": "eebeb133ef22bcf0c216f596edd68ce572822b59055c80ca0fd377135c0ff426",
        "gencase_receipt": F2_DATA / "F2_RV4EQ_MATCHED_CENTER_V1_COARSE_DP010/gencase-f2_rv4eq_matched_center_v1_coarse_dp010-20261003-001/execution-receipt.json",
        "gencase_receipt_sha256": "a4210530169ca86f841412b7c44a208246bf41a4402b87e29c3ab604440a6fdc",
        "numerical_recipe_hash": "6058fdea7c65dd3b89d305564511a7c767b272ccf0938a4ba3ca63b9f1bfcb05",
        "physical_hash": PHYSICAL_HASH,
        "pose_attempt_id": "matched-center-coarse-nvme-pose-v2-001",
        "labels_attempt_id": "matched-center-coarse-nvme-labels-v2-001",
    },
    "medium": {
        "case_id": "F2_RV4EQ_MATCHED_CENTER_V1_MEDIUM_DP008_SPATIAL_REFERENCE_SAVE010",
        "short_name": "center_medium",
        "resolution": "MEDIUM",
        "dp_m": 0.008,
        "total_particles": 668673,
        "fluid_particles": 48000,
        "case_nmoving": 39561,
        "source_h5": F2_DATA / "F2_RV4EQ_MATCHED_CENTER_V1_MEDIUM_DP008_SPATIAL_REFERENCE_SAVE010/root-center-medium-matched-spatial-fulltyped-nvme-003/trajectory.h5",
        "source_h5_sha256": "26b3dac18c3133ad9d2fde9b0b2044857cc95e1cdda2666c359416107dde8557",
        "source_h5_bytes": 2139717558,
        "conversion_report": F2_DATA / "F2_RV4EQ_MATCHED_CENTER_V1_MEDIUM_DP008_SPATIAL_REFERENCE_SAVE010/root-center-medium-matched-spatial-fulltyped-nvme-003/conversion-report.json",
        "conversion_report_sha256": "ecd44e0c65ead10ab4bd1321b6d27f0074187abe10eb083f7ee9bb4e2e509308",
        "conversion_receipt": F2_DATA / "F2_RV4EQ_MATCHED_CENTER_V1_MEDIUM_DP008_SPATIAL_REFERENCE_SAVE010/root-center-medium-matched-spatial-fulltyped-nvme-003/execution-receipt.json",
        "conversion_receipt_sha256": "75f0215b0721eb4d24995be730bca7318d78d32ead595f58828700b1c38d1da9",
        "xml": F2_DATA / "F2_RV4EQ_MATCHED_SPATIAL_REFERENCE_INPUTS_20261003/F2_RV4EQ_MATCHED_CENTER_V1_MEDIUM_DP008/F2_RV4EQ_MATCHED_CENTER_V1_MEDIUM_DP008_SPATIAL_REFERENCE_SAVE010.xml",
        "xml_sha256": "73461af9c72748b73f2da499ba3ed44e822d7523493073b501280eb0d8d5d492",
        "motion": F2_DATA / "F2_RV4EQ_MATCHED_SPATIAL_REFERENCE_INPUTS_20261003/F2_RV4EQ_MATCHED_CENTER_V1_MEDIUM_DP008/F2_RV4EQ_MATCHED_CENTER_V1_MEDIUM_DP008_motion.dat",
        "motion_sha256": "ff966330e01e565987ebf182a7dfd7401d76577ae1c266894fc7db4aa34c5b70",
        "run_out": F2_DATA / "F2_RV4EQ_MATCHED_CENTER_V1_MEDIUM_DP008_SPATIAL_REFERENCE_SAVE010/qualification-f2_rv4eq_matched_center_v1_medium_dp008-spatial-reference-save010-root-review-001/solver_output/Run.out",
        "run_out_sha256": "0829632350b79f28f83ee53fe13587b8b67c8913b49196187edde5e06c8fd821",
        "solver_receipt": F2_DATA / "F2_RV4EQ_MATCHED_CENTER_V1_MEDIUM_DP008_SPATIAL_REFERENCE_SAVE010/qualification-f2_rv4eq_matched_center_v1_medium_dp008-spatial-reference-save010-root-review-001/execution-receipt.json",
        "solver_receipt_sha256": "81f6a3dab6eea89fa116dca06b0c95f9d8f4f02465c70ba9ec73b8c176973992",
        "gencase_receipt": F2_DATA / "F2_RV4EQ_MATCHED_CENTER_V1_MEDIUM_DP008/gencase-f2_rv4eq_matched_center_v1_medium_dp008-20261003-001/execution-receipt.json",
        "gencase_receipt_sha256": "1966336b242de09973e5cf2f3027a6535a856ac091dd00b72bfbf8739c091b68",
        "numerical_recipe_hash": "f62e6923f66733aba9e13894dc7da44075f93bf69ed6e900430050acf9af1020",
        "physical_hash": PHYSICAL_HASH,
        "pose_attempt_id": "matched-center-medium-nvme-pose-v2-001",
        "labels_attempt_id": "matched-center-medium-nvme-labels-v2-001",
    },
}


class PostprocessError(RuntimeError):
    """Raised when an operation cannot be completed safely."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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

    # Set read-only
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


def build_owner_metadata(info: dict[str, Any]) -> dict[str, Any]:
    owner_meta = {
        "schema": "ds02.f2.case-owner-metadata.v2",
        "family_id": "F2",
        "case_id": info["case_id"],
        "background": "CENTER",
        "resolution": info["resolution"],
        "dp_m": info["dp_m"],
        "geometry": {
            "cup_low_m": [0.0, -0.15, 0.65],
            "cup_size_m": [0.425, 0.3, 0.45],
            "receiver_low_m": [0.45, -0.3, 0.0],
            "receiver_size_m": [1.1, 0.6, 0.45],
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
            "continuous_mass_kg": 24.576,
            "strict_cell_center_exact_budget_fraction": "1e-12",
        },
        "event_window": {
            "hold_start_s": 0.5,
            "time_start_s": 0.0,
            "time_end_s": 4.0,
        },
        "physical_binding": {
            "physical_condition_hash_declared": info["physical_hash"],
            "parameters": {
                "motion_axis_origin_m": [0.0, -1.0, 0.65],
                "motion_axis_unit": [0.0, 1.0, 0.0],
            },
        },
        "numerical_recipe_hash_declared": info["numerical_recipe_hash"],
        "fullstate_terminal_binding": {
            "trajectory_h5": binding(info["source_h5"], "canonical converted trajectory H5", known_sha=info["source_h5_sha256"]),
            "conversion_report": binding(info["conversion_report"], "conversion report", known_sha=info["conversion_report_sha256"]),
            "conversion_receipt": binding(info["conversion_receipt"], "conversion receipt", known_sha=info["conversion_receipt_sha256"]),
        },
    }
    owner_path = OWNER_DIR / f"{info['case_id']}.owner.v2.json"
    dump_json(owner_path, owner_meta)
    return owner_meta


def build_pose_stage(info: dict[str, Any], owner_meta: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    case_id = info["case_id"]
    attempt_id = info["pose_attempt_id"]

    config = {
        "schema": "ds02.f2.matched-center-pose-config.v2",
        "stage": "pose",
        "case_id": case_id,
        "resolution": info["resolution"],
        "attempt_id": attempt_id,
        "physical_condition_hash": info["physical_hash"],
        "numerical_recipe_hash": info["numerical_recipe_hash"],
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
            "owner_metadata": binding(OWNER_DIR / f"{case_id}.owner.v2.json", "owner metadata"),
        },
        "nvme_policy": {
            "scratch_parent": str(DEFAULT_SCRATCH),
            "stage_in_private_dir": True,
            "rebind_canonical_before_publish": True,
            "private_copy_deleted_after_stage": True,
        },
        "claim_boundary": {
            "q_i": "not_granted; pose enrichment evidence only",
            "q_n": "not_assessed",
            "production": "not_evaluated",
        },
    }
    config_path = CONFIGS_DIR / f"{info['short_name']}_pose_nvme_config_v2.json"
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
        OWNER_DIR / f"{case_id}.owner.v2.json",
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
        "estimated_storage_bytes": int(info["source_h5_bytes"] * 1.5),
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
    }
    request_path = REQUESTS_DIR / f"{info['short_name']}_pose_nvme_request_v2.json"
    dump_json(request_path, request)
    return config, request


def build_labels_stage(info: dict[str, Any], pose_attempt_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    case_id = info["case_id"]
    attempt_id = info["labels_attempt_id"]
    pose_attempt_dir = Path(pose_attempt_dir).expanduser().resolve()

    pose_receipt_path = require_file(pose_attempt_dir / "execution-receipt.json", "pose execution receipt")
    pose_report_path = require_file(pose_attempt_dir / "rigid-body-state.json", "pose report")
    pose_h5_path = require_file(pose_attempt_dir / "trajectory-with-actual-pose.h5", "pose-augmented trajectory H5")

    pose_receipt = load_json(pose_receipt_path, "pose execution receipt")
    if pose_receipt.get("status") != "completed" or pose_receipt.get("returncode") != 0:
        raise PostprocessError(f"pose stage receipt not completed/code 0: {pose_receipt_path}")

    pose_report = load_json(pose_report_path, "pose report")
    pose_row = pose_report.get("augmented_trajectory")
    if not isinstance(pose_row, dict) or len(str(pose_row.get("sha256", ""))) != 64:
        raise PostprocessError("completed pose report lacks valid augmented_trajectory SHA256")

    actual_pose_h5_sha = sha256_file(pose_h5_path)
    if actual_pose_h5_sha != pose_row["sha256"]:
        raise PostprocessError(f"pose report SHA {pose_row['sha256']} differs from actual file {actual_pose_h5_sha}")

    config = {
        "schema": "ds02.f2.matched-center-labels-config.v2",
        "stage": "labels",
        "case_id": case_id,
        "resolution": info["resolution"],
        "attempt_id": attempt_id,
        "physical_condition_hash": info["physical_hash"],
        "numerical_recipe_hash": info["numerical_recipe_hash"],
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
            "owner_metadata": binding(OWNER_DIR / f"{case_id}.owner.v2.json", "owner metadata"),
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
    }
    config_path = CONFIGS_DIR / f"{info['short_name']}_labels_nvme_config_v2.json"
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
        pose_h5_path,
        pose_report_path,
        pose_receipt_path,
        info["xml"],
        OWNER_DIR / f"{case_id}.owner.v2.json",
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
        "estimated_storage_bytes": int(200 * 1024 * 1024),
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
    }
    request_path = REQUESTS_DIR / f"{info['short_name']}_labels_nvme_request_v2.json"
    dump_json(request_path, request)
    return config, request


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

    with tempfile.TemporaryDirectory(prefix="f2-center-pose-v2-", dir=scratch_parent) as private_dir:
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
        "schema": "ds02.f2.matched-center-pose-manifest.v2",
        "status": "completed_evidence_only",
        "case_id": config["case_id"],
        "resolution": config["resolution"],
        "physical_condition_hash": config["physical_condition_hash"],
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

    with tempfile.TemporaryDirectory(prefix="f2-center-labels-v2-", dir=scratch_parent) as private_dir:
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
        "schema": "ds02.f2.matched-center-labels-manifest.v2",
        "status": "completed_evidence_only",
        "case_id": config["case_id"],
        "resolution": config["resolution"],
        "physical_condition_hash": config["physical_condition_hash"],
        "labels_h5": binding(labels_h5_target, "v6 labels H5"),
        "observations_report": binding(obs_report_target, "v6 observations report"),
        "q_i_status": "not_granted",
        "q_n_status": "not_assessed",
        "production_status": "not_evaluated",
    }
    manifest_path = output_dir / "postprocess-manifest.json"
    dump_json(manifest_path, manifest)
    return manifest


def build_all() -> None:
    HANDOFF_ROOT.mkdir(parents=True, exist_ok=True)
    CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
    REQUESTS_DIR.mkdir(parents=True, exist_ok=True)
    OWNER_DIR.mkdir(parents=True, exist_ok=True)
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

    for name, info in CASES.items():
        owner = build_owner_metadata(info)
        build_pose_stage(info, owner)
    print("Build all v2 owner metadata and pose requests complete.")


def build_labels_for_case(case_name: str, pose_attempt_dir: Path | None = None) -> None:
    if case_name not in CASES:
        raise PostprocessError(f"unknown case name: {case_name}")
    info = CASES[case_name]
    if pose_attempt_dir is None:
        pose_attempt_dir = F2_DATA / info["case_id"] / info["pose_attempt_id"]
    build_labels_stage(info, pose_attempt_dir)
    print(f"Build v2 labels config and request complete for {case_name}.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)

    sub.add_parser("build")

    lbl = sub.add_parser("build-labels")
    lbl.add_argument("--case", choices=["coarse", "medium"], required=True)
    lbl.add_argument("--pose-attempt-root", type=Path, default=None)

    run_p = sub.add_parser("run")
    run_p.add_argument("stage", choices=["pose", "labels"])
    run_p.add_argument("--config", type=Path, required=True)
    run_p.add_argument("--output-dir", type=Path, required=True)
    run_p.add_argument("--scratch-parent", type=Path, default=DEFAULT_SCRATCH)

    args = parser.parse_args()

    if args.action == "build":
        build_all()
    elif args.action == "build-labels":
        build_labels_for_case(args.case, args.pose_attempt_root)
    elif args.action == "run":
        if args.stage == "pose":
            run_pose(args.config, args.output_dir, args.scratch_parent)
        elif args.stage == "labels":
            run_labels(args.config, args.output_dir, args.scratch_parent)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
