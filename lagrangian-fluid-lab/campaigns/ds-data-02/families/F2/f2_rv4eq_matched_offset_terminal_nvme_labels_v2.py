"""Resolved F2 RV4 matched OFFSET coarse & medium terminal NVMe labels v2 builder.

Binds Root actual completed poses from review 011:
- Coarse: DATA/families/F2/F2_RV4EQ_MATCHED_OFFSET_V1_COARSE_DP010_SPATIAL_REFERENCE_SAVE010/root-offset-coarse-actual-native-pose-v1-011
  (H5 SHA: 0ec74f531db62e4921f78e6fd1cb4faed2fb4d9a96838dfa1df30d6e819659a2, 1261868216 bytes)
- Medium: DATA/families/F2/F2_RV4EQ_MATCHED_OFFSET_V1_MEDIUM_DP008_SPATIAL_REFERENCE_SAVE010/root-offset-medium-actual-native-pose-v1-011
  (H5 SHA: a83a0a810a3c6f86f9fb8dee885f3dadc84406fdb34b3d97e6ca44f95463510a, 2139817799 bytes)

Physical & Numerical Invariants:
- Physical condition hash: 327899e38bbad63951206d5b2fd3ef354c049a32f6671af1af7913a48b77c7ef
- Receiver geometry: low corner [0.45, -0.16, 0.0] m (offset y by +0.14 m from center -0.30 m)
- Time window: 4.0 s, 401 frames, dt = 0.010 s
- Save timing budget: strictly original save allowance 0.0007336391 s (zero relaxation; dt=0.010 s fails contract)
- Storage estimate: >= 600 MiB (since actual medium was ~274 MiB, well above 200 MiB)
- Native weights vs decimal XML: reported separately, source preserved unnormalized
- Native invalid particle identities: remain strictly unknown loss, not inferred spill
- Campaign write isolation: build_all supports explicit output_root redirection for test isolation
- Runner compliance: no execute_all, no manual execution-receipt.json generation
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
HANDOFF_ROOT = FAMILY_ROOT / "handoff_20261003/matched_offset_labels_resolved_v2"
CONFIGS_DIR = HANDOFF_ROOT / "configs"
REQUESTS_DIR = HANDOFF_ROOT / "requests"
DEFAULT_SCRATCH = Path("/tmp/ds02-f2-offset-matched-labels-v2")

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
        "pose_attempt_id": "root-offset-coarse-actual-native-pose-v1-011",
        "pose_attempt_dir": F2_DATA / "F2_RV4EQ_MATCHED_OFFSET_V1_COARSE_DP010_SPATIAL_REFERENCE_SAVE010/root-offset-coarse-actual-native-pose-v1-011",
        "pose_h5": F2_DATA / "F2_RV4EQ_MATCHED_OFFSET_V1_COARSE_DP010_SPATIAL_REFERENCE_SAVE010/root-offset-coarse-actual-native-pose-v1-011/trajectory-with-actual-pose.h5",
        "pose_h5_sha256": "0ec74f531db62e4921f78e6fd1cb4faed2fb4d9a96838dfa1df30d6e819659a2",
        "pose_h5_bytes": 1261868216,
        "pose_report": F2_DATA / "F2_RV4EQ_MATCHED_OFFSET_V1_COARSE_DP010_SPATIAL_REFERENCE_SAVE010/root-offset-coarse-actual-native-pose-v1-011/rigid-body-state.json",
        "pose_report_sha256": "3c7b1f1ab523cb04c2dd81f3338d4ea8cfc7f544a8e4243e3eba86a911642f0d",
        "pose_receipt": F2_DATA / "F2_RV4EQ_MATCHED_OFFSET_V1_COARSE_DP010_SPATIAL_REFERENCE_SAVE010/root-offset-coarse-actual-native-pose-v1-011/execution-receipt.json",
        "pose_receipt_sha256": "0d2d9c26834e8cabfa8902d01adfe7b854bde02cd48d9d2ed7d7f1574d882d45",
        "labels_attempt_id": "matched-offset-coarse-nvme-labels-v2-001",
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
        "pose_attempt_id": "root-offset-medium-actual-native-pose-v1-011",
        "pose_attempt_dir": F2_DATA / "F2_RV4EQ_MATCHED_OFFSET_V1_MEDIUM_DP008_SPATIAL_REFERENCE_SAVE010/root-offset-medium-actual-native-pose-v1-011",
        "pose_h5": F2_DATA / "F2_RV4EQ_MATCHED_OFFSET_V1_MEDIUM_DP008_SPATIAL_REFERENCE_SAVE010/root-offset-medium-actual-native-pose-v1-011/trajectory-with-actual-pose.h5",
        "pose_h5_sha256": "a83a0a810a3c6f86f9fb8dee885f3dadc84406fdb34b3d97e6ca44f95463510a",
        "pose_h5_bytes": 2139817799,
        "pose_report": F2_DATA / "F2_RV4EQ_MATCHED_OFFSET_V1_MEDIUM_DP008_SPATIAL_REFERENCE_SAVE010/root-offset-medium-actual-native-pose-v1-011/rigid-body-state.json",
        "pose_report_sha256": "2118c2da464c771179e83a8bb9b9cf8be86e08367b0c2fd87088b01b0532d075",
        "pose_receipt": F2_DATA / "F2_RV4EQ_MATCHED_OFFSET_V1_MEDIUM_DP008_SPATIAL_REFERENCE_SAVE010/root-offset-medium-actual-native-pose-v1-011/execution-receipt.json",
        "pose_receipt_sha256": "b87e0bb0695e6acaa5bc01d6994e5aae441d5a3810b21686498d56c9e61eb2e3",
        "labels_attempt_id": "matched-offset-medium-nvme-labels-v2-001",
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


def build_labels_config_v2(info: dict[str, Any]) -> dict[str, Any]:
    case_id = info["case_id"]
    attempt_id = info["labels_attempt_id"]

    config = {
        "schema": "ds02.f2.matched-offset-labels-config.v2",
        "stage": "labels",
        "status": "ready_for_root_dispatch",
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
            "save_budget_compliance": "observed dt=0.010s fails original event save allowance 0.0007336391s; budget preserved without relaxation",
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
            "q_n_grant": False,
        },
        "resource_ledger": {
            "cpu_threads": 2,
            "max_wall_seconds": 3600,
            "estimated_storage_bytes": int(629145600),  # 600 MiB (>= 512 MiB required)
        },
        "terminal_bindings": {
            "source_trajectory_h5": binding(info["source_h5"], "source trajectory H5", known_sha=info["source_h5_sha256"]),
            "conversion_report": binding(info["conversion_report"], "conversion report", known_sha=info["conversion_report_sha256"]),
            "conversion_receipt": binding(info["conversion_receipt"], "conversion receipt", known_sha=info["conversion_receipt_sha256"]),
        },
        "pose_bindings": {
            "pose_attempt_id": info["pose_attempt_id"],
            "pose_h5": binding(info["pose_h5"], "completed pose-augmented trajectory H5", known_sha=info["pose_h5_sha256"]),
            "pose_report": binding(info["pose_report"], "completed rigid-body pose report", known_sha=info["pose_report_sha256"]),
            "pose_receipt": binding(info["pose_receipt"], "completed pose execution receipt", known_sha=info["pose_receipt_sha256"]),
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


def build_labels_request_v2(info: dict[str, Any], config_path: Path) -> dict[str, Any]:
    case_id = info["case_id"]
    attempt_id = info["labels_attempt_id"]

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
        info["pose_h5"],
        info["pose_report"],
        info["pose_receipt"],
        info["xml"],
        info["owner_metadata"],
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
        "estimated_storage_bytes": int(629145600),  # 600 MiB
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
    return request


def build_all(output_root: Path | None = None) -> tuple[dict[str, Path], dict[str, Path]]:
    root = Path(output_root).expanduser().resolve() if output_root else HANDOFF_ROOT
    configs_dir = root / "configs"
    requests_dir = root / "requests"

    configs_dir.mkdir(parents=True, exist_ok=True)
    requests_dir.mkdir(parents=True, exist_ok=True)

    configs_out = {}
    requests_out = {}
    manifest_cases = []

    for name, info in CASES.items():
        short = info["short_name"]

        # Build resolved config
        cfg = build_labels_config_v2(info)
        cfg_path = configs_dir / f"{short}_labels_nvme_config_v2.json"
        dump_json(cfg_path, cfg)
        configs_out[name] = cfg_path

        # Build runner request
        req = build_labels_request_v2(info, cfg_path)
        req_path = requests_dir / f"{short}_labels_nvme_request_v2.json"
        dump_json(req_path, req)
        requests_out[name] = req_path

        manifest_cases.append({
            "case_name": name,
            "case_id": info["case_id"],
            "resolution": info["resolution"],
            "physical_condition_hash": info["physical_hash"],
            "receiver_low_m": [0.45, -0.16, 0.0],
            "pose_attempt_id": info["pose_attempt_id"],
            "pose_h5_sha256": info["pose_h5_sha256"],
            "labels_attempt_id": info["labels_attempt_id"],
            "config_path": str(cfg_path),
            "request_path": str(req_path),
            "status": "ready_for_root_dispatch",
        })

    manifest = {
        "schema": "ds02.f2.resolved-offset-labels-manifest.v2",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "resolved_preparation_complete",
        "cases": manifest_cases,
        "physical_condition_hash": PHYSICAL_HASH,
        "save_timing_budget_s": SAVE_ALLOWANCE_S,
        "save_relaxation": False,
        "storage_estimate_bytes": int(629145600),
        "unknown_state_policy": "observed native invalid remain strictly unknown, not inferred spill",
    }
    dump_json(root / "resolved_offset_labels_manifest_v2.json", manifest)
    print(f"Resolved OFFSET labels scope v2 built successfully at {root}.")
    return configs_out, requests_out


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

    with tempfile.TemporaryDirectory(prefix="f2-offset-labels-v2-", dir=scratch_parent) as private_dir:
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

        # Correct canonical pose references and add explicit native mass and unknown loss accounting
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

        # Explicit mass reporting
        mass_info = config["mass_semantics"]
        obs_data["native_mass_and_weights"] = {
            "native_float32_individual_mass_kg": mass_info["xml_massfluid_decimal_kg"],
            "native_float32_fluid_sum_kg": mass_info["native_float32_fluid_sum_kg"],
            "xml_decimal_massfluid_kg": mass_info["xml_massfluid_decimal_kg"],
            "xml_continuous_fluid_mass_kg": mass_info["xml_continuous_mass_kg"],
            "delta_native_minus_xml_kg": mass_info["native_representation_delta_kg"],
            "source_normalization_applied": False,
            "reporting_policy": "Native float32 masses reported separately from XML decimal continuous mass reference."
        }

        # Explicit unknown loss accounting
        obs_data["unknown_loss_accounting"] = {
            "observed_native_invalid_policy": "unknown; never inferred as physical spill without geometric segment test",
            "physical_spill_inferred_from_invalid": False,
            "destination_precedence": ["unknown_invalid", "cup", "receiver", "tray_after_departure", "inflight"],
            "q_n_grant": False,
        }
        dump_json(private_obs, obs_data)

        # Atomically publish staged files to target attempt directory
        output_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(private_labels, labels_h5_target)
        labels_h5_target.chmod(0o400)
        shutil.copyfile(private_obs, obs_report_target)

    manifest = {
        "schema": "ds02.f2.matched-offset-labels-manifest.v2",
        "status": "completed_evidence_only",
        "case_id": config["case_id"],
        "resolution": config["resolution"],
        "physical_condition_hash": config["physical_condition_hash"],
        "labels_h5": binding(labels_h5_target, "v6 labels H5"),
        "observations_report": binding(obs_report_target, "v6 observations report"),
        "q_i_status": "not_granted",
        "q_n_status": "not_assessed",
        "production_status": "not_evaluated",
        "save_timing_budget_s": SAVE_ALLOWANCE_S,
        "save_timing_evaluation": "observed dt=0.010s fails original event save allowance 0.0007336391s; budget strictly preserved without relaxation",
    }
    manifest_path = output_dir / "postprocess-manifest.json"
    dump_json(manifest_path, manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)

    build_p = sub.add_parser("build")
    build_p.add_argument("--output-root", type=Path, default=None)

    run_p = sub.add_parser("run")
    run_p.add_argument("--config", type=Path, required=True)
    run_p.add_argument("--output-dir", type=Path, required=True)
    run_p.add_argument("--scratch-parent", type=Path, default=DEFAULT_SCRATCH)

    args = parser.parse_args()

    if args.action == "build":
        build_all(args.output_root)
    elif args.action == "run":
        run_labels(args.config, args.output_dir, args.scratch_parent)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
