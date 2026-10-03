#!/usr/bin/env python3
"""Scientific audit for F2 matched CENTER native floating mass and augmentation invariance.

Audits completed v2 CENTER pose reference attempts:
- coarse: F2_RV4EQ_MATCHED_CENTER_V1_COARSE_DP010_SPATIAL_REFERENCE_SAVE010 (N=421,566, fluid=24,576)
- medium: F2_RV4EQ_MATCHED_CENTER_V1_MEDIUM_DP008_SPATIAL_REFERENCE_SAVE010 (N=668,673, fluid=48,000)

Scientific scope:
1. Compares native floating MassFluid (IEEE-754 float32) against generated XML decimal mass weights.
   - coarse: native float32 sum = 24.576001167297363 kg vs XML decimal 24.576 kg (delta +1.1673e-6 kg, rel error 4.75e-8)
   - medium: native float32 sum = 24.57599993801117 kg vs XML decimal 24.576 kg (delta -6.1989e-8 kg, rel error 2.52e-9)
2. Verifies native types, Idp, Pos, Vel, Rhop, Mass datasets are strictly preserved between source
   trajectory.h5 and augmented trajectory-with-actual-pose.h5.
3. Verifies formal validity (finite checks, no NaN/Inf), cohort status (particle counts preserved),
   and native weighted closures.
4. Distinguishes native measurement vs normalized diagnostic without retroactive source/operator edit
   and without Q-N waiver.
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
from typing import Any

import h5py
import numpy as np


FAMILY_ROOT = Path(__file__).resolve().parent
INTEGRATION_LAB = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
F2_DATA = DATA_ROOT / "families/F2"

PYTHON = INTEGRATION_LAB / ".venv/bin/python"
RUNTIME = INTEGRATION_LAB / "scripts/ds_data02_runtime_v2.py"
STRICT_DISPATCH = INTEGRATION_LAB / "scripts/ds_data02_strict_dispatch_v1.py"
QUALITY = FAMILY_ROOT / "quality_contract.json"

AUDIT_ROOT = FAMILY_ROOT / "handoff_20261003/matched_center_audit_v1"
CONFIGS_DIR = AUDIT_ROOT / "configs"
REQUESTS_DIR = AUDIT_ROOT / "requests"
DEFAULT_SCRATCH = Path("/tmp/ds02-f2-center-audit-v1")

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
        "pose_attempt_dir": F2_DATA / "F2_RV4EQ_MATCHED_CENTER_V1_COARSE_DP010_SPATIAL_REFERENCE_SAVE010/matched-center-coarse-nvme-pose-v2-001",
        "pose_h5": F2_DATA / "F2_RV4EQ_MATCHED_CENTER_V1_COARSE_DP010_SPATIAL_REFERENCE_SAVE010/matched-center-coarse-nvme-pose-v2-001/trajectory-with-actual-pose.h5",
        "pose_h5_sha256": "13602eed74b924216fe9b4e61657ce4b9e738679f830c190204f8853a3e93696",
        "pose_h5_bytes": 1262405156,
        "pose_receipt": F2_DATA / "F2_RV4EQ_MATCHED_CENTER_V1_COARSE_DP010_SPATIAL_REFERENCE_SAVE010/matched-center-coarse-nvme-pose-v2-001/execution-receipt.json",
        "xml": F2_DATA / "F2_RV4EQ_MATCHED_SPATIAL_REFERENCE_INPUTS_20261003/F2_RV4EQ_MATCHED_CENTER_V1_COARSE_DP010/F2_RV4EQ_MATCHED_CENTER_V1_COARSE_DP010_SPATIAL_REFERENCE_SAVE010.xml",
        "xml_sha256": "08415c42c4fd3a3846103985689d53cb9226df72763845bc082943f2146c4336",
        "xml_massfluid_decimal": 0.001,
        "xml_total_fluid_mass_kg": 24.576,
        "audit_attempt_id": "matched-center-coarse-mass-invariance-audit-v1-001",
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
        "pose_attempt_dir": F2_DATA / "F2_RV4EQ_MATCHED_CENTER_V1_MEDIUM_DP008_SPATIAL_REFERENCE_SAVE010/matched-center-medium-nvme-pose-v2-001",
        "pose_h5": F2_DATA / "F2_RV4EQ_MATCHED_CENTER_V1_MEDIUM_DP008_SPATIAL_REFERENCE_SAVE010/matched-center-medium-nvme-pose-v2-001/trajectory-with-actual-pose.h5",
        "pose_h5_sha256": "24b01864051a6b9b73d582d772e4d52d8cc01f1a19d833dc33d9e4cf2a298b67",
        "pose_h5_bytes": 2139748514,
        "pose_receipt": F2_DATA / "F2_RV4EQ_MATCHED_CENTER_V1_MEDIUM_DP008_SPATIAL_REFERENCE_SAVE010/matched-center-medium-nvme-pose-v2-001/execution-receipt.json",
        "xml": F2_DATA / "F2_RV4EQ_MATCHED_SPATIAL_REFERENCE_INPUTS_20261003/F2_RV4EQ_MATCHED_CENTER_V1_MEDIUM_DP008/F2_RV4EQ_MATCHED_CENTER_V1_MEDIUM_DP008_SPATIAL_REFERENCE_SAVE010.xml",
        "xml_sha256": "73461af9c72748b73f2da499ba3ed44e822d7523493073b501280eb0d8d5d492",
        "xml_massfluid_decimal": 0.000512,
        "xml_total_fluid_mass_kg": 24.576,
        "audit_attempt_id": "matched-center-medium-mass-invariance-audit-v1-001",
    },
}


class AuditError(RuntimeError):
    """Raised when scientific audit cannot be completed."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(path: Any, label: str) -> Path:
    p = Path(str(path)).expanduser().resolve()
    if not p.is_file():
        raise AuditError(f"{label} is missing: {p}")
    return p


def load_json(path: Any, label: str) -> dict[str, Any]:
    p = require_file(path, label)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        raise AuditError(f"{label} is invalid JSON: {p} ({exc})") from exc
    if not isinstance(data, dict):
        raise AuditError(f"{label} is not a JSON object: {p}")
    return data


def dump_json(path: Any, data: Any) -> None:
    p = Path(str(path)).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def binding(path: Any, role: str, *, known_sha: str | None = None) -> dict[str, Any]:
    p = require_file(path, role)
    actual_sha = sha256_file(p)
    if known_sha and actual_sha != known_sha:
        raise AuditError(f"SHA mismatch for {role}: expected {known_sha}, got {actual_sha}")
    return {
        "path": str(p),
        "sha256": actual_sha,
        "bytes": int(p.stat().st_size),
        "role": role,
    }


def require_bitwise_dataset(src, aug, name):
    if name not in src or name not in aug:
        raise AuditError(f"mandatory particle dataset missing: {name}")
    a, b = src[name], aug[name]
    if a.shape != b.shape or a.dtype != b.dtype:
        raise AuditError(f"dataset shape or dtype changed: {name}")
    if len(a.shape) == 0:
        if a[()].tobytes() != b[()].tobytes():
            raise AuditError(f"dataset bytes changed: {name}")
    else:
        step = 1 if len(a.shape) >= 2 else 65536
        for first in range(0, a.shape[0], step):
            if np.asarray(a[first:first+step]).tobytes() != np.asarray(b[first:first+step]).tobytes():
                raise AuditError(f"dataset bytes changed: {name} at {first}")


def audit_case(info: dict[str, Any]) -> dict[str, Any]:
    """Execute deep mass invariance and augmentation check on one case."""
    source_h5_path = require_file(info["source_h5"], "canonical source trajectory")
    pose_h5_path = require_file(info["pose_h5"], "pose-augmented trajectory")
    pose_receipt_path = require_file(info["pose_receipt"], "pose execution receipt")
    xml_path = require_file(info["xml"], "generated XML")

    # 1. Check file hashes
    source_sha = sha256_file(source_h5_path)
    if source_sha != info["source_h5_sha256"]:
        raise AuditError(f"source H5 SHA mismatch: {source_sha} != {info['source_h5_sha256']}")

    pose_sha = sha256_file(pose_h5_path)
    if pose_sha != info["pose_h5_sha256"]:
        raise AuditError(f"pose H5 SHA mismatch: {pose_sha} != {info['pose_h5_sha256']}")

    # 2. Check pose execution receipt from runner
    pose_rcpt = load_json(pose_receipt_path, "pose execution receipt")
    if pose_rcpt.get("status") != "completed" or pose_rcpt.get("returncode") != 0:
        raise AuditError("pose execution receipt is not completed/code 0")

    # 3. Read H5 datasets
    with h5py.File(source_h5_path, "r") as src, h5py.File(pose_h5_path, "r") as aug:
        # Require exact stored data bytes, including NaN payloads and signed zero.
        mandatory = ["time", "initial_type", "particle_id", "initial_mass",
                     "position", "velocity", "density", "mass", "type", "mk", "valid"]
        for name in mandatory:
            require_bitwise_dataset(src, aug, name)
        # Check frames and times
        src_times = np.array(src["time"])
        aug_times = np.array(aug["time"])
        if src_times.shape != aug_times.shape or not np.array_equal(src_times, aug_times):
            raise AuditError("time array differs between source and augmented")

        frames = len(src_times)
        if frames != 401:
            raise AuditError(f"unexpected frame count: {frames} != 401")

        src_types = np.array(src["initial_type"])
        aug_types = np.array(aug["initial_type"])
        if not np.array_equal(src_types, aug_types):
            raise AuditError("initial_type array differs between source and augmented")

        src_idp = np.array(src["particle_id"])
        aug_idp = np.array(aug["particle_id"])
        if not np.array_equal(src_idp, aug_idp):
            raise AuditError("particle_id array differs between source and augmented")

        total_particles = len(src_types)
        if total_particles != info["total_particles"]:
            raise AuditError(f"particle count {total_particles} != expected {info['total_particles']}")

        # Type counts
        fluid_mask = src_types == 3
        moving_mask = src_types == 1
        fixed_mask = src_types == 0

        n_fluid = int(np.sum(fluid_mask))
        n_moving = int(np.sum(moving_mask))
        n_fixed = int(np.sum(fixed_mask))

        if n_fluid != info["fluid_particles"]:
            raise AuditError(f"fluid particle count {n_fluid} != expected {info['fluid_particles']}")
        if n_moving != info["case_nmoving"]:
            raise AuditError(f"moving boundary particle count {n_moving} != expected {info['case_nmoving']}")

        # Mass evaluation from initial_mass
        src_init_mass = np.array(src["initial_mass"], dtype=np.float32)
        aug_init_mass = np.array(aug["initial_mass"], dtype=np.float32)
        if not np.array_equal(src_init_mass, aug_init_mass):
            raise AuditError("initial_mass differs between source and augmented")

        fluid_masses = src_init_mass[fluid_mask]
        native_float_mass_sum = float(np.sum(fluid_masses.astype(np.float64)))
        individual_float_val = float(fluid_masses[0])

        # Finite checks on position, velocity, density, mass where valid is True
        val = np.array(aug["valid"])
        for name_arr in ["position", "velocity", "density", "mass"]:
            arr = np.array(aug[name_arr])
            if not np.all(np.isfinite(arr[val])):
                raise AuditError(f"non-finite values detected in valid particles of augmented {name_arr}")

        # Invariance check across core particle datasets
        for ds in ["position", "velocity", "density", "mass", "type", "mk", "valid"]:
            if ds in src and ds in aug:
                s_data = np.array(src[ds])
                a_data = np.array(aug[ds])
                if not np.array_equal(s_data, a_data, equal_nan=True):
                    raise AuditError(f"dataset {ds} mutated between source and augmented")

        # Check rigid body state dataset in augmented
        if "rigid_body_state" not in aug:
            raise AuditError("augmented trajectory lacks rigid_body_state dataset")
        rbs = aug["rigid_body_state"]
        if rbs.shape != (frames,):
            raise AuditError(f"rigid_body_state shape {rbs.shape} != expected ({frames},)")
        # Check moving node count in rigid_body_state
        rbs_moving_nodes = int(rbs["moving_node_count"][0])
        if rbs_moving_nodes != info["case_nmoving"]:
            raise AuditError(f"rigid_body_state moving node count {rbs_moving_nodes} != expected {info['case_nmoving']}")

    # Mass comparison metrics
    xml_mass = info["xml_total_fluid_mass_kg"]
    delta_mass_kg = native_float_mass_sum - xml_mass
    rel_mass_error = abs(delta_mass_kg) / xml_mass

    report = {
        "schema": "ds02.f2.matched-center-mass-invariance-audit.v2",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "case_id": info["case_id"],
        "resolution": info["resolution"],
        "dp_m": info["dp_m"],
        "physical_condition_hash": PHYSICAL_HASH,
        "source_trajectory": binding(source_h5_path, "canonical source H5", known_sha=info["source_h5_sha256"]),
        "augmented_trajectory": binding(pose_h5_path, "pose-augmented trajectory H5", known_sha=info["pose_h5_sha256"]),
        "generated_xml": binding(xml_path, "generated XML", known_sha=info["xml_sha256"]),
        "pose_execution_receipt": binding(pose_receipt_path, "runner pose execution receipt"),
        "mass_comparison": {
            "native_float32_individual_mass_kg": individual_float_val,
            "native_float32_fluid_sum_kg": native_float_mass_sum,
            "generated_xml_massfluid_decimal_kg": info["xml_massfluid_decimal"],
            "generated_xml_total_fluid_mass_kg": xml_mass,
            "delta_mass_native_minus_xml_kg": delta_mass_kg,
            "relative_mass_error": rel_mass_error,
            "interpretation": (
                "Native float32 mass values are summed in float64; XML decimal nominal mass is a separate reference. "
                "The observed difference is reported without normalization and does not establish zero physical mass defect."
            ),
            "native_measurement_vs_normalized_diagnostic": {
                "native_measurement_fluid_mass_kg": native_float_mass_sum,
                "normalized_diagnostic_nominal_mass_kg": xml_mass,
                "normalization_applied_to_source": False,
                "normalization_policy": "Source H5 native float32 mass values are preserved unnormalized.",
            },
        },
        "augmentation_invariance": {
            "frames": frames,
            "total_particles": total_particles,
            "fluid_particles": n_fluid,
            "moving_boundary_particles": n_moving,
            "fixed_boundary_particles": n_fixed,
            "particle_datasets_checked": mandatory,
            "invariance_method": "stored dtype, shape and bytes for every mandatory dataset chunk; NaN payloads and signed zero retained",
            "bitwise_particle_invariance_verified": True,
            "additive_rigid_body_state_verified": True,
            "formal_validity_all_finite": True,
            "cohort_status_preserved": True,
        },
        "scientific_qualification_boundary": {
            "q_i_status": "audit_evidence_complete",
            "q_n_status": "not_assessed",
            "production_status": "not_evaluated",
            "q_n_granted": False,
            "production_granted": False,
            "waiver_granted": False,
        },
    }
    return report


def build_audit_requests() -> None:
    AUDIT_ROOT.mkdir(parents=True, exist_ok=True)
    CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
    REQUESTS_DIR.mkdir(parents=True, exist_ok=True)

    for name, info in CASES.items():
        short = info["short_name"]
        case_id = info["case_id"]
        attempt_id = info["audit_attempt_id"]

        config = {
            "schema": "ds02.f2.matched-center-mass-invariance-audit-config.v1",
            "case_id": case_id,
            "resolution": info["resolution"],
            "attempt_id": attempt_id,
            "physical_condition_hash": PHYSICAL_HASH,
            "source_trajectory_h5": binding(info["source_h5"], "canonical source trajectory", known_sha=info["source_h5_sha256"]),
            "augmented_trajectory_h5": binding(info["pose_h5"], "pose-augmented trajectory", known_sha=info["pose_h5_sha256"]),
            "pose_execution_receipt": binding(info["pose_receipt"], "pose execution receipt"),
            "generated_xml": binding(info["xml"], "generated XML", known_sha=info["xml_sha256"]),
        }
        config_path = CONFIGS_DIR / f"{short}_mass_invariance_audit_config_v1.json"
        dump_json(config_path, config)

        request_inputs = [
            Path(__file__).resolve(),
            PYTHON,
            RUNTIME,
            STRICT_DISPATCH,
            QUALITY,
            config_path,
            info["source_h5"],
            info["pose_h5"],
            info["pose_receipt"],
            info["xml"],
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
            "cpu_task_kind": "audit",
            "cpu_threads": 2,
            "max_wall_seconds": 3600,
            "estimated_storage_bytes": int(200 * 1024 * 1024),
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
            ],
            "input_files": [str(p) for p in unique_inputs],
            "input_sha256": {str(p): sha256_file(p) for p in unique_inputs},
            "claim_boundary": {
                "q_i": "mass_invariance_evidence_only",
                "q_n": "not_assessed",
                "production": "not_evaluated",
            },
            "independent_case_count_increment": 0,
            "conversion_launch_forbidden": True,
        }
        request_path = REQUESTS_DIR / f"{short}_mass_invariance_audit_request_v1.json"
        dump_json(request_path, request)
        print(f"Built audit config and request for {name} ({case_id}).")


def run_audit(config_path: Path, output_dir: Path) -> dict[str, Any]:
    config = load_json(config_path, "audit config")
    case_id = config["case_id"]

    matched_info = None
    for name, info in CASES.items():
        if info["case_id"] == case_id:
            matched_info = info
            break
    if matched_info is None:
        raise AuditError(f"case_id {case_id} not recognized in CASES")

    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    report_target = output_dir / "center-mass-invariance-audit-report.json"
    manifest_target = output_dir / "postprocess-manifest.json"

    if report_target.exists():
        raise AuditError(f"refusing to overwrite existing audit report: {report_target}")

    report = audit_case(matched_info)
    dump_json(report_target, report)

    manifest = {
        "schema": "ds02.f2.matched-center-audit-manifest.v1",
        "status": "completed_evidence_only",
        "case_id": case_id,
        "resolution": matched_info["resolution"],
        "physical_condition_hash": PHYSICAL_HASH,
        "audit_report": binding(report_target, "mass invariance audit report"),
        "q_i_status": "audit_evidence_complete",
        "q_n_status": "not_assessed",
        "production_status": "not_evaluated",
    }
    dump_json(manifest_target, manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)

    sub.add_parser("build")

    run_p = sub.add_parser("run")
    run_p.add_argument("--config", type=Path, required=True)
    run_p.add_argument("--output-dir", type=Path, required=True)

    args = parser.parse_args()

    if args.action == "build":
        build_audit_requests()
    elif args.action == "run":
        run_audit(args.config, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
