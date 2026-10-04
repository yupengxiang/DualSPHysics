#!/usr/bin/env python3
"""request_builder_cli.py

DS-DATA-02 Family F7: Request Builder and Binding CLI for the Three-DP
Frozen Macro and Moving Paddle Actual Pose Study (Round 046).

Usage:
    python request_builder_cli.py build-binding --output binding.json
    python request_builder_cli.py build-request --binding binding.json --output request.json
    python request_builder_cli.py validate-inputs [--binding binding.json]
    python request_builder_cli.py inspect
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any

# Pinned integration root and paths
INTEGRATION_WT = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
F7_INTEGRATION_ROOT = INTEGRATION_WT / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F7"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7")

# Pinned normalizers and budget files
FROZEN_NORMALIZERS_PATH = (
    F7_INTEGRATION_ROOT / "handoff_20261002/root_native_observation_001/frozen_macro_normalizers_001.json"
)
FROZEN_BUDGET_PATH = (
    F7_INTEGRATION_ROOT / "handoff_20261002/root_native_observation_001/frozen_reference_budget_001.json"
)
ORIGINAL_SCALE_REFERENCE_PATH = (
    DATA_ROOT / "F7_OBSTACLE_EXPLICIT_WET_CELLS_001_FINE/root-native-macro-series-001/macro-series.json"
)
MOTION_DAT_PATH = (
    DATA_ROOT / "F7_QUINTIC_TARGET_VERIFIED_RECIPE_ACTUAL_SOURCE"
    / "root-obstacle-quintic-target-verified-native-recipe-preparation-020/prepared/motion_obstacle_quintic.dat"
)

# Standard python interpreter in integration venv
VENV_PYTHON = INTEGRATION_WT / "lagrangian-fluid-lab/.venv/bin/python"

# Pinned cases configuration
THREE_DP_CASES = {
    "coarse": {
        "role": "coarse",
        "case_id": "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_COARSE",
        "dp_m": 0.020,
        "trajectory_h5": (
            DATA_ROOT / "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_COARSE"
            / "root-quintic-target-coarse-full601-typed-026/trajectory.h5"
        ),
        "conversion_report": (
            DATA_ROOT / "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_COARSE"
            / "root-quintic-target-coarse-full601-typed-026/conversion-report.json"
        ),
        "typed_receipt": (
            DATA_ROOT / "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_COARSE"
            / "root-quintic-target-coarse-full601-typed-026/execution-receipt.json"
        ),
        "native_solver_receipt": (
            DATA_ROOT / "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_COARSE"
            / "root-obstacle-quintic-restored-motion-coarse-full601-native-025/execution-receipt.json"
        ),
        "gencase_receipt": (
            DATA_ROOT / "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_COARSE"
            / "root-obstacle-quintic-verified-recipe-coarse-actual-gencase-021/execution-receipt.json"
        ),
        "owner_metadata": (
            F7_INTEGRATION_ROOT
            / "handoff_20261003/root_actual_quintic_complete_typed_026/coarse/owner.json"
        ),
        "xml": (
            DATA_ROOT / "F7_QUINTIC_VERIFIED_MOTION_ASSET_CLONES"
            / "root-quintic-verified-three-dp-actual-motion-asset-clones-024/prepared/coarse"
            / "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_COARSE.xml"
        ),
        "motion_dat": (
            DATA_ROOT / "F7_QUINTIC_VERIFIED_MOTION_ASSET_CLONES"
            / "root-quintic-verified-three-dp-actual-motion-asset-clones-024/prepared/coarse/motion_obstacle_quintic.dat"
        ),
        "expected_particles": {
            "total": 70179,
            "fluid": 40700,
            "type1_moving": 1984,
            "type0_fixed": 27495,
        },
    },
    "medium": {
        "role": "medium",
        "case_id": "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_MEDIUM",
        "dp_m": 0.016,
        "trajectory_h5": (
            DATA_ROOT / "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_MEDIUM"
            / "root-quintic-target-medium-full601-typed-026/trajectory.h5"
        ),
        "conversion_report": (
            DATA_ROOT / "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_MEDIUM"
            / "root-quintic-target-medium-full601-typed-026/conversion-report.json"
        ),
        "typed_receipt": (
            DATA_ROOT / "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_MEDIUM"
            / "root-quintic-target-medium-full601-typed-026/execution-receipt.json"
        ),
        "native_solver_receipt": (
            DATA_ROOT / "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_MEDIUM"
            / "root-obstacle-quintic-restored-motion-medium-full601-native-025/execution-receipt.json"
        ),
        "gencase_receipt": (
            DATA_ROOT / "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_MEDIUM"
            / "root-obstacle-quintic-verified-recipe-medium-actual-gencase-021/execution-receipt.json"
        ),
        "owner_metadata": (
            F7_INTEGRATION_ROOT
            / "handoff_20261003/root_actual_quintic_complete_typed_026/medium/owner.json"
        ),
        "xml": (
            DATA_ROOT / "F7_QUINTIC_VERIFIED_MOTION_ASSET_CLONES"
            / "root-quintic-verified-three-dp-actual-motion-asset-clones-024/prepared/medium"
            / "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_MEDIUM.xml"
        ),
        "motion_dat": (
            DATA_ROOT / "F7_QUINTIC_VERIFIED_MOTION_ASSET_CLONES"
            / "root-quintic-verified-three-dp-actual-motion-asset-clones-024/prepared/medium/motion_obstacle_quintic.dat"
        ),
        "expected_particles": {
            "total": 125142,
            "fluid": 78732,
            "type1_moving": 3798,
            "type0_fixed": 42612,
        },
    },
    "fine": {
        "role": "fine",
        "case_id": "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_FINE",
        "dp_m": 0.010,
        "trajectory_h5": (
            DATA_ROOT / "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_FINE"
            / "root-quintic-target-fine-full601-typed-026/trajectory.h5"
        ),
        "conversion_report": (
            DATA_ROOT / "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_FINE"
            / "root-quintic-target-fine-full601-typed-026/conversion-report.json"
        ),
        "typed_receipt": (
            DATA_ROOT / "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_FINE"
            / "root-quintic-target-fine-full601-typed-026/execution-receipt.json"
        ),
        "native_solver_receipt": (
            DATA_ROOT / "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_FINE"
            / "root-obstacle-quintic-restored-motion-fine-full601-native-025/execution-receipt.json"
        ),
        "gencase_receipt": (
            DATA_ROOT / "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_FINE"
            / "root-obstacle-quintic-verified-recipe-fine-actual-gencase-021/execution-receipt.json"
        ),
        "owner_metadata": (
            F7_INTEGRATION_ROOT
            / "handoff_20261003/root_actual_quintic_complete_typed_026/fine/owner.json"
        ),
        "xml": (
            DATA_ROOT / "F7_QUINTIC_VERIFIED_MOTION_ASSET_CLONES"
            / "root-quintic-verified-three-dp-actual-motion-asset-clones-024/prepared/fine"
            / "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_FINE.xml"
        ),
        "motion_dat": (
            DATA_ROOT / "F7_QUINTIC_VERIFIED_MOTION_ASSET_CLONES"
            / "root-quintic-verified-three-dp-actual-motion-asset-clones-024/prepared/fine/motion_obstacle_quintic.dat"
        ),
        "expected_particles": {
            "total": 424277,
            "fluid": 318716,
            "type1_moving": 4899,
            "type0_fixed": 100662,
        },
    },
}


def sha256_file(path: Path | str) -> str:
    """Computes SHA256 hex digest of a file in chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def build_binding() -> dict[str, Any]:
    """Builds the comprehensive three-DP binding dictionary."""
    cases_dict: dict[str, Any] = {}
    for role, c in THREE_DP_CASES.items():
        cases_dict[role] = {
            "role": role,
            "case_id": c["case_id"],
            "dp_m": c["dp_m"],
            "trajectory_h5": str(c["trajectory_h5"]),
            "conversion_report": str(c["conversion_report"]),
            "typed_receipt": str(c["typed_receipt"]),
            "native_solver_receipt": str(c["native_solver_receipt"]),
            "gencase_receipt": str(c["gencase_receipt"]),
            "owner_metadata": str(c["owner_metadata"]),
            "xml": str(c["xml"]),
            "motion_dat": str(c["motion_dat"]),
            "expected_particles": c["expected_particles"],
        }

    return {
        "schema": "ds02.f7.three-dp-binding.v1",
        "family_id": "F7",
        "physical_mother_id": "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_BASE_V1",
        "lineage_group_id": "F7_OBSTACLE_REFERENCE_BASE_AND_QUINTIC_SHARED_GEOMETRY_NO_LEAK",
        "physical_condition_sha256": "512cb217f29e716346c249339545ed2599e7cb1aeb8e81fe7f1c0cf7f341c34c",
        "cases": cases_dict,
        "motion_dat": str(MOTION_DAT_PATH),
        "normalizers": str(FROZEN_NORMALIZERS_PATH),
        "budget": str(FROZEN_BUDGET_PATH),
        "original_scale_reference": str(ORIGINAL_SCALE_REFERENCE_PATH),
        "governance_claim": {
            "q_n": "not_granted",
            "production_approval": "none",
            "spatial_ke_negative_evidence_persists": True,
            "ke_5pct_failure_preserved": True,
            "constant_refinement_ratio_claim": False,
            "uid_match_across_dp": False,
            "native_exclusions_fate": "unknown",
            "independent_studies_required": "time/save and motion cadence/protocol sensitivity",
        },
    }


def build_runner_request(
    binding_path: Path,
    worker_script_path: Path,
    attempt_id: str = "root-quintic-target-three-dp-macro-audit-046",
) -> dict[str, Any]:
    """Builds runner request JSON adhering to ds02.runner-request.v2."""
    input_files = [
        str(VENV_PYTHON),
        str(worker_script_path),
        str(binding_path),
        str(FROZEN_NORMALIZERS_PATH),
        str(FROZEN_BUDGET_PATH),
    ]

    # Add available cases and reports to input_files
    for c in THREE_DP_CASES.values():
        for key in ["owner_metadata", "xml", "motion_dat", "native_solver_receipt", "gencase_receipt"]:
            p = c[key]
            if p.is_file() and str(p) not in input_files:
                input_files.append(str(p))
        # Add typed receipts and reports if they exist
        for key in ["typed_receipt", "conversion_report", "trajectory_h5"]:
            p = c[key]
            if p.is_file() and str(p) not in input_files:
                input_files.append(str(p))

    if ORIGINAL_SCALE_REFERENCE_PATH.is_file():
        input_files.append(str(ORIGINAL_SCALE_REFERENCE_PATH))
    if MOTION_DAT_PATH.is_file() and str(MOTION_DAT_PATH) not in input_files:
        input_files.append(str(MOTION_DAT_PATH))

    # Compute sha256 for all existing non-H5 input files (source-only: do NOT read .h5 files)
    input_sha256 = {}
    for path_str in input_files:
        p = Path(path_str)
        if p.suffix == ".h5":
            # Guarded compute boundary: Root alone processes H5 files
            continue
        if p.is_file():
            input_sha256[path_str] = sha256_file(p)

    return {
        "schema": "ds02.runner-request.v2",
        "family_id": "F7",
        "case_id": "F7_OBSTACLE_QUINTIC_TARGET_THREE_DP_MACRO_STUDY_001",
        "attempt_id": attempt_id,
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 2,
        "max_wall_seconds": 300,
        "estimated_storage_bytes": 67108864,
        "cwd": str(INTEGRATION_WT / "lagrangian-fluid-lab"),
        "worktree_root": str(INTEGRATION_WT),
        "command": [
            str(VENV_PYTHON),
            str(worker_script_path),
            "--binding",
            str(binding_path),
            "--output",
            "{attempt_root}/three-dp-macro-review.json",
        ],
        "input_files": input_files,
        "input_sha256": input_sha256,
        "independent_case_count_increment": 0,
        "production_approval": "none",
        "launch_allowed": True,
        "launch_owner": "root",
        "claim": "Binding-driven 3DP/allpairs macro & actual moving Type1 pose worker; Q-N not granted",
    }


def validate_pinned_inputs(binding_path: Path | None = None) -> dict[str, Any]:
    """Audits the presence and SHA256 integrity of all pinned files."""
    results: dict[str, Any] = {"existing": {}, "pending_root_compute": {}}

    check_files = [
        ("frozen_normalizers", FROZEN_NORMALIZERS_PATH),
        ("frozen_budget", FROZEN_BUDGET_PATH),
        ("motion_dat", MOTION_DAT_PATH),
        ("original_scale_reference", ORIGINAL_SCALE_REFERENCE_PATH),
    ]

    for role, c in THREE_DP_CASES.items():
        check_files.append((f"{role}_xml", c["xml"]))
        check_files.append((f"{role}_motion_dat", c["motion_dat"]))
        check_files.append((f"{role}_owner_metadata", c["owner_metadata"]))
        check_files.append((f"{role}_native_solver_receipt", c["native_solver_receipt"]))
        check_files.append((f"{role}_gencase_receipt", c["gencase_receipt"]))
        check_files.append((f"{role}_typed_receipt", c["typed_receipt"]))
        check_files.append((f"{role}_conversion_report", c["conversion_report"]))
        check_files.append((f"{role}_trajectory_h5", c["trajectory_h5"]))

    if binding_path is not None and binding_path.is_file():
        check_files.append(("binding_json", binding_path))

    for label, path in check_files:
        if path.is_file():
            results["existing"][label] = {
                "path": str(path),
                "sha256": (
                    sha256_file(path)
                    if path.suffix != ".h5"
                    else "omitted_source_only_h5_reading_prohibited"
                ),
                "size_bytes": path.stat().st_size,
            }
        else:
            results["pending_root_compute"][label] = {
                "path": str(path),
                "status": "pending_or_missing",
            }

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    # Subcommand: build-binding
    b_p = sub.add_parser("build-binding", help="Builds binding.json connecting coarse, medium, fine cases")
    b_p.add_argument("--output", type=Path, default=Path("binding.json"), help="Output path for binding.json")

    # Subcommand: build-request
    r_p = sub.add_parser("build-request", help="Builds runner request.json for Root runner dispatch")
    r_p.add_argument("--binding", type=Path, default=Path("binding.json"), help="Path to binding.json")
    r_p.add_argument("--worker", type=Path, default=Path("f7_three_dp_frozen_macro_worker.py"), help="Worker script path")
    r_p.add_argument("--attempt-id", type=str, default="root-quintic-target-three-dp-macro-audit-046")
    r_p.add_argument("--output", type=Path, default=Path("request.json"), help="Output path for request.json")

    # Subcommand: validate-inputs
    v_p = sub.add_parser("validate-inputs", help="Validates availability and integrity of pinned files")
    v_p.add_argument("--binding", type=Path, default=None, help="Optional binding.json path to validate")

    # Subcommand: inspect
    sub.add_parser("inspect", help="Displays summary of cases, equations, and governance")

    args = parser.parse_args()

    if args.command == "build-binding":
        binding = build_binding()
        with args.output.open("w") as f:
            json.dump(binding, f, indent=2)
            f.write("\n")
        print(json.dumps({"action": "build-binding", "output": str(args.output), "cases": list(binding["cases"].keys())}))

    elif args.command == "build-request":
        req = build_runner_request(args.binding.resolve(), args.worker.resolve(), attempt_id=args.attempt_id)
        with args.output.open("w") as f:
            json.dump(req, f, indent=2)
            f.write("\n")
        print(json.dumps({
            "action": "build-request",
            "output": str(args.output),
            "attempt_id": req["attempt_id"],
            "input_files_count": len(req["input_files"]),
        }))

    elif args.command == "validate-inputs":
        status = validate_pinned_inputs(binding_path=args.binding)
        print(json.dumps({
            "action": "validate-inputs",
            "existing_count": len(status["existing"]),
            "pending_count": len(status["pending_root_compute"]),
            "pending_details": status["pending_root_compute"],
        }, indent=2))

    elif args.command == "inspect":
        info = {
            "family": "F7",
            "physical_mother": "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_BASE_V1",
            "lineage": "F7_OBSTACLE_REFERENCE_BASE_AND_QUINTIC_SHARED_GEOMETRY_NO_LEAK",
            "dp_resolutions": {k: v["dp_m"] for k, v in THREE_DP_CASES.items()},
            "refinement_ratios": {"coarse_to_medium": 1.25, "medium_to_fine": 1.6, "constant": False},
            "governance": {
                "q_n": "not_granted",
                "production_approval": "none",
                "historical_spatial_ke_discrepancy": "retained (~43%)",
                "macro_budget": "5%",
            },
        }
        print(json.dumps(info, indent=2))


if __name__ == "__main__":
    main()
