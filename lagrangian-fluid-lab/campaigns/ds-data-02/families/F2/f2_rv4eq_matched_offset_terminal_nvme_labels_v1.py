"""Prospective F2 RV4 matched OFFSET coarse & medium terminal NVMe labels v1 builder.

Scope:
- Prospective preparation only for matched OFFSET labels postprocess.
- Defers pose H5 and receipt SHA binding until Root executes the upstream pose requests:
  - matched-offset-coarse-nvme-pose-v1-001
  - matched-offset-medium-nvme-pose-v1-001
- Matches CENTER formal v2 approach:
  - Physical condition hash: 327899e38bbad63951206d5b2fd3ef354c049a32f6671af1af7913a48b77c7ef
  - Receiver geometry: low corner [0.45, -0.16, 0.0] m (offset y by +0.14 m from center -0.30 m)
  - Time window: 4.0 s, 401 frames, dt = 0.010 s
  - Timing budget: strictly original save allowance 0.0007336391 s, zero relaxation
  - Storage estimate: >= 512 MiB (600 MiB configured)
  - Native weights vs decimal XML explicitly preserved unnormalized
  - Native invalid particle identities remain strictly unknown (never inferred spill)
- Shared runner compliance: no execute_all, no manual execution-receipt.json generation.
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

OFFSET_OWNER_DIR = FAMILY_ROOT / "handoff_20261003/matched_offset_terminal_nvme_v1/owner_metadata"
HANDOFF_ROOT = FAMILY_ROOT / "handoff_20261003/matched_offset_labels_prospective_v1"
CONFIGS_DIR = HANDOFF_ROOT / "configs"
REQUESTS_DIR = HANDOFF_ROOT / "requests"
TEMPLATES_DIR = HANDOFF_ROOT / "templates"
DEFAULT_SCRATCH = Path("/tmp/ds02-f2-offset-matched-nvme-v1")

PHYSICAL_HASH = "327899e38bbad63951206d5b2fd3ef354c049a32f6671af1af7913a48b77c7ef"
SAVE_ALLOWANCE_S = 0.0007336390799938275

CASES: dict[str, dict[str, Any]] = {
    "coarse": {
        "case_id": "F2_RV4EQ_MATCHED_OFFSET_V1_COARSE_DP010_SPATIAL_REFERENCE_SAVE010",
        "short_name": "offset_coarse",
        "resolution": "COARSE",
        "dp_m": 0.010,
        "total_particles": 421566,
        "fluid_particles": 24576,
        "case_nmoving": 24150,
        "xml_massfluid_decimal": 0.001,
        "xml_total_fluid_mass_kg": 24.576,
        "native_float32_fluid_sum_kg": 24.576001167297363,
        "source_h5": F2_DATA / "F2_RV4EQ_MATCHED_OFFSET_V1_COARSE_DP010_SPATIAL_REFERENCE_SAVE010/root-offset-coarse-matched-spatial-fulltyped-nvme-003/trajectory.h5",
        "source_h5_sha256": "4e1611b03650b2db1964a0f8dcac9c55d84da9d0a3da3b3df71e95da2165618c",
        "source_h5_bytes": 1261837248,
        "conversion_report": F2_DATA / "F2_RV4EQ_MATCHED_OFFSET_V1_COARSE_DP010_SPATIAL_REFERENCE_SAVE010/root-offset-coarse-matched-spatial-fulltyped-nvme-003/conversion-report.json",
        "conversion_report_sha256": "566adbc00378b739d02424667fb5fa9eb04a6b3f98b2641fdc89d6393836cf2b",
        "conversion_receipt": F2_DATA / "F2_RV4EQ_MATCHED_OFFSET_V1_COARSE_DP010_SPATIAL_REFERENCE_SAVE010/root-offset-coarse-matched-spatial-fulltyped-nvme-003/execution-receipt.json",
        "conversion_receipt_sha256": "06f8232ae0fdcc2df2335f612cba17ce3e25dc2573d0562703fbc5cbd4284fc2",
        "xml": F2_DATA / "F2_RV4EQ_MATCHED_SPATIAL_REFERENCE_INPUTS_20261003/F2_RV4EQ_MATCHED_OFFSET_V1_COARSE_DP010/F2_RV4EQ_MATCHED_OFFSET_V1_COARSE_DP010_SPATIAL_REFERENCE_SAVE010.xml",
        "xml_sha256": "ec821fd843fe7eae962e61673e137fa46f10924b5f7100c9e5c8ee272966de6c",
        "owner_metadata": OFFSET_OWNER_DIR / "F2_RV4EQ_MATCHED_OFFSET_V1_COARSE_DP010_SPATIAL_REFERENCE_SAVE010.owner.v1.json",
        "owner_metadata_sha256": "b5ecca3294345bcccf1ee2fc590926eda490182712b5c9c5c4959496789736f2",
        "numerical_recipe_hash": "071faa386a5191f6adba5c30bff1281f88dafc48055de7351d740a5c61ba02d8",
        "physical_hash": PHYSICAL_HASH,
        "pose_attempt_id": "matched-offset-coarse-nvme-pose-v1-001",
        "labels_attempt_id": "matched-offset-coarse-nvme-labels-v1-001",
    },
    "medium": {
        "case_id": "F2_RV4EQ_MATCHED_OFFSET_V1_MEDIUM_DP008_SPATIAL_REFERENCE_SAVE010",
        "short_name": "offset_medium",
        "resolution": "MEDIUM",
        "dp_m": 0.008,
        "total_particles": 668673,
        "fluid_particles": 48000,
        "case_nmoving": 39561,
        "xml_massfluid_decimal": 0.000512,
        "xml_total_fluid_mass_kg": 24.576,
        "native_float32_fluid_sum_kg": 24.575999937951565,
        "source_h5": F2_DATA / "F2_RV4EQ_MATCHED_OFFSET_V1_MEDIUM_DP008_SPATIAL_REFERENCE_SAVE010/root-offset-medium-matched-spatial-fulltyped-nvme-003/trajectory.h5",
        "source_h5_sha256": "1bc9f9f956bf791ccdac15e67b5dd5bad76201ebeb302371fae98d5ff069b500",
        "source_h5_bytes": 2139786859,
        "conversion_report": F2_DATA / "F2_RV4EQ_MATCHED_OFFSET_V1_MEDIUM_DP008_SPATIAL_REFERENCE_SAVE010/root-offset-medium-matched-spatial-fulltyped-nvme-003/conversion-report.json",
        "conversion_report_sha256": "74d1d5938e69fc8d42ffa349156bb899f90acce8929b727c0fd24f9fc7739ab5",
        "conversion_receipt": F2_DATA / "F2_RV4EQ_MATCHED_OFFSET_V1_MEDIUM_DP008_SPATIAL_REFERENCE_SAVE010/root-offset-medium-matched-spatial-fulltyped-nvme-003/execution-receipt.json",
        "conversion_receipt_sha256": "dbd2e0616319b415a702e5ef82900e2d72a5699fac8660e66f970524e3ed6397",
        "xml": F2_DATA / "F2_RV4EQ_MATCHED_SPATIAL_REFERENCE_INPUTS_20261003/F2_RV4EQ_MATCHED_OFFSET_V1_MEDIUM_DP008/F2_RV4EQ_MATCHED_OFFSET_V1_MEDIUM_DP008_SPATIAL_REFERENCE_SAVE010.xml",
        "xml_sha256": "e8a7aa98bdd50dfc97068a28f15e52b96914a05cfb91305f1bbb29154570c692",
        "owner_metadata": OFFSET_OWNER_DIR / "F2_RV4EQ_MATCHED_OFFSET_V1_MEDIUM_DP008_SPATIAL_REFERENCE_SAVE010.owner.v1.json",
        "owner_metadata_sha256": "ccb307cb0e2aeec92bd20e91b8b73b560b8db0c69d6c760a8bf1bed42aec0c90",
        "numerical_recipe_hash": "c1b14253746739e8dbdf30d51bf073e40d1a14beb6a14feb517d9d6d765b6d4c",
        "physical_hash": PHYSICAL_HASH,
        "pose_attempt_id": "matched-offset-medium-nvme-pose-v1-001",
        "labels_attempt_id": "matched-offset-medium-nvme-labels-v1-001",
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

    target.chmod(0o400)
    return {
        "source": str(source),
        "target": str(target),
        "copy_verified_during_stream": True,
        "private_reader_sha256": actual_sha,
        "private_reader_bytes": int(expected_bytes),
        "mode": "0400",
    }


def load_module(path: Path, name: str) -> Any:
    require_file(path, f"module {name}")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise PostprocessError(f"cannot load module from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def build_prospective_config(info: dict[str, Any]) -> dict[str, Any]:
    case_id = info["case_id"]
    attempt_id = info["labels_attempt_id"]
    pose_attempt_id = info["pose_attempt_id"]
    pose_attempt_dir = F2_DATA / case_id / pose_attempt_id

    config = {
        "schema": "ds02.f2.prospective-offset-labels-config.v1",
        "stage": "labels",
        "status": "prospective_pose_binding_deferred",
        "case_id": case_id,
        "resolution": info["resolution"],
        "attempt_id": attempt_id,
        "physical_condition_hash": info["physical_hash"],
        "numerical_recipe_hash": info["numerical_recipe_hash"],
        "geometry": {
            "cup_low_m": [0.0, -0.15, 0.65],
            "cup_size_m": [0.425, 0.3, 0.45],
            "receiver_low_m": [0.45, -0.16, 0.0],
            "receiver_size_m": [1.1, 0.6, 0.45],
            "tray_low_m": [-1.2, -1.0, -0.2],
            "tray_size_m": [4.0, 2.0, 0.15],
            "motion_axis_origin_m": [0.0, -1.0, 0.65],
            "motion_axis_unit": [0.0, 1.0, 0.0],
            "receiver_offset_y_m": 0.14,
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
            "estimated_storage_bytes": int(600 * 1024 * 1024),  # 600 MiB (>= 512 MiB required)
        },
        "terminal_bindings": {
            "source_trajectory_h5": binding(info["source_h5"], "source trajectory H5", known_sha=info["source_h5_sha256"]),
            "conversion_report": binding(info["conversion_report"], "conversion report", known_sha=info["conversion_report_sha256"]),
            "conversion_receipt": binding(info["conversion_receipt"], "conversion receipt", known_sha=info["conversion_receipt_sha256"]),
        },
        "deferred_pose_bindings": {
            "pose_attempt_id": pose_attempt_id,
            "pose_attempt_dir": str(pose_attempt_dir),
            "pose_h5_target": str(pose_attempt_dir / "trajectory-with-actual-pose.h5"),
            "pose_report_target": str(pose_attempt_dir / "rigid-body-state.json"),
            "pose_receipt_target": str(pose_attempt_dir / "execution-receipt.json"),
            "binding_status": "deferred_until_root_execution",
        },
        "inputs": {
            "xml": binding(info["xml"], "generated XML", known_sha=info["xml_sha256"]),
            "owner_metadata": binding(info["owner_metadata"], "owner metadata", known_sha=info["owner_metadata_sha256"]),
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
    return config


def build_prospective_template(info: dict[str, Any], config_path: Path) -> dict[str, Any]:
    case_id = info["case_id"]
    attempt_id = info["labels_attempt_id"]
    pose_attempt_id = info["pose_attempt_id"]
    pose_attempt_dir = F2_DATA / case_id / pose_attempt_id

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
        info["owner_metadata"],
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
        "estimated_storage_bytes": int(600 * 1024 * 1024),
        "cwd": str(FAMILY_ROOT),
        "worktree_root": str(FAMILY_ROOT.parents[4]),
        "command": [
            str(PYTHON),
            str(Path(__file__).resolve()),
            "run",
            "--config",
            str(config_path),
            "--output-dir",
            "{attempt_root}",
            "--scratch-parent",
            str(DEFAULT_SCRATCH),
        ],
        "static_input_files": [str(p) for p in unique_static],
        "static_input_sha256": {str(p): sha256_file(p) for p in unique_static},
        "deferred_pose_inputs": [
            str(pose_attempt_dir / "trajectory-with-actual-pose.h5"),
            str(pose_attempt_dir / "rigid-body-state.json"),
            str(pose_attempt_dir / "execution-receipt.json"),
        ],
        "claim_boundary": {
            "q_i": "not_granted; labels evidence only",
            "q_n": "not_assessed",
            "production": "not_evaluated",
        },
        "independent_case_count_increment": 0,
        "conversion_launch_forbidden": True,
        "status": "prospective_awaiting_root_pose_execution",
    }
    return template


def build_prospective_all() -> None:
    CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    REQUESTS_DIR.mkdir(parents=True, exist_ok=True)

    manifest_cases = []
    for name, info in CASES.items():
        short = info["short_name"]
        cfg = build_prospective_config(info)
        cfg_path = CONFIGS_DIR / f"{short}_labels_nvme_config_v1.json"
        dump_json(cfg_path, cfg)

        template = build_prospective_template(info, cfg_path)
        tmpl_path = TEMPLATES_DIR / f"{short}_labels_prospective_template_v1.json"
        dump_json(tmpl_path, template)

        manifest_cases.append({
            "case_name": name,
            "case_id": info["case_id"],
            "resolution": info["resolution"],
            "physical_condition_hash": info["physical_hash"],
            "receiver_low_m": [0.45, -0.16, 0.0],
            "labels_attempt_id": info["labels_attempt_id"],
            "pose_attempt_id": info["pose_attempt_id"],
            "config_path": str(cfg_path),
            "template_path": str(tmpl_path),
            "binding_status": "deferred_until_root_pose_execution",
        })

    manifest = {
        "schema": "ds02.f2.prospective-offset-labels-manifest.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "prospective_preparation_complete",
        "binding_policy": "pose receipt and H5 SHA deferred until Root executes pose requests",
        "cases": manifest_cases,
        "physical_condition_hash": PHYSICAL_HASH,
        "save_timing_budget_s": SAVE_ALLOWANCE_S,
        "save_relaxation": False,
        "storage_estimate_bytes": int(600 * 1024 * 1024),
        "unknown_state_policy": "observed native invalid remain strictly unknown, not inferred spill",
    }
    dump_json(HANDOFF_ROOT / "prospective_offset_labels_manifest_v1.json", manifest)
    print("Prospective OFFSET labels configs and templates built successfully.")


def resolve_labels_request_after_pose(
    case_name: str,
    pose_attempt_dir: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if case_name not in CASES:
        raise PostprocessError(f"unknown case {case_name}; must be 'coarse' or 'medium'")
    info = CASES[case_name]
    case_id = info["case_id"]
    attempt_id = info["labels_attempt_id"]

    if pose_attempt_dir is None:
        pose_attempt_dir = F2_DATA / case_id / info["pose_attempt_id"]
    pose_attempt_dir = Path(pose_attempt_dir).expanduser().resolve()

    pose_receipt_path = pose_attempt_dir / "execution-receipt.json"
    pose_report_path = pose_attempt_dir / "rigid-body-state.json"
    pose_h5_path = pose_attempt_dir / "trajectory-with-actual-pose.h5"

    if not pose_receipt_path.is_file():
        raise PostprocessError(
            f"Cannot resolve labels request: pose execution receipt missing at {pose_receipt_path}; "
            "labels request generation is strictly deferred pending Root dispatch of pose stage."
        )

    pose_receipt = load_json(pose_receipt_path, "pose execution receipt")
    if pose_receipt.get("status") != "completed" or pose_receipt.get("returncode") != 0:
        raise PostprocessError(f"pose stage receipt not completed code 0: {pose_receipt_path}")

    require_file(pose_report_path, "pose report")
    require_file(pose_h5_path, "pose trajectory H5")

    pose_report = load_json(pose_report_path, "pose report")
    pose_row = pose_report.get("augmented_trajectory")
    if not isinstance(pose_row, dict) or len(str(pose_row.get("sha256", ""))) != 64:
        raise PostprocessError("completed pose report lacks valid augmented_trajectory SHA256")

    actual_pose_h5_sha = sha256_file(pose_h5_path)
    if actual_pose_h5_sha != pose_row["sha256"]:
        raise PostprocessError(f"pose report SHA {pose_row['sha256']} differs from file {actual_pose_h5_sha}")

    cfg = build_prospective_config(info)
    cfg["status"] = "ready_for_dispatch"
    cfg["pose_bindings"] = {
        "pose_h5": binding(pose_h5_path, "completed pose-augmented trajectory H5", known_sha=actual_pose_h5_sha),
        "pose_report": binding(pose_report_path, "completed rigid-body pose report"),
        "pose_receipt": binding(pose_receipt_path, "completed pose execution receipt"),
    }
    cfg.pop("deferred_pose_bindings", None)

    cfg_path = CONFIGS_DIR / f"{info['short_name']}_labels_nvme_config_v1.json"
    dump_json(cfg_path, cfg)

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
        cfg_path,
        pose_h5_path,
        pose_report_path,
        pose_receipt_path,
        info["xml"],
        info["owner_metadata"],
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
        "estimated_storage_bytes": int(600 * 1024 * 1024),
        "cwd": str(FAMILY_ROOT),
        "worktree_root": str(FAMILY_ROOT.parents[4]),
        "command": [
            str(PYTHON),
            str(Path(__file__).resolve()),
            "run",
            "--config",
            str(cfg_path),
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
    request_path = REQUESTS_DIR / f"{info['short_name']}_labels_nvme_request_v1.json"
    dump_json(request_path, request)
    return cfg, request


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

    with tempfile.TemporaryDirectory(prefix="f2-offset-labels-v1-", dir=scratch_parent) as private_dir:
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

        # Atomically publish staged files
        output_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(private_labels, labels_h5_target)
        labels_h5_target.chmod(0o400)
        shutil.copyfile(private_obs, obs_report_target)

    manifest = {
        "schema": "ds02.f2.matched-offset-labels-manifest.v1",
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)

    sub.add_parser("build")

    resolve_p = sub.add_parser("resolve")
    resolve_p.add_argument("--case", choices=["coarse", "medium"], required=True)
    resolve_p.add_argument("--pose-attempt-dir", type=Path, default=None)

    run_p = sub.add_parser("run")
    run_p.add_argument("--config", type=Path, required=True)
    run_p.add_argument("--output-dir", type=Path, required=True)
    run_p.add_argument("--scratch-parent", type=Path, default=DEFAULT_SCRATCH)

    args = parser.parse_args()

    if args.action == "build":
        build_prospective_all()
    elif args.action == "resolve":
        resolve_labels_request_after_pose(args.case, args.pose_attempt_dir)
    elif args.action == "run":
        run_labels(args.config, args.output_dir, args.scratch_parent)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
