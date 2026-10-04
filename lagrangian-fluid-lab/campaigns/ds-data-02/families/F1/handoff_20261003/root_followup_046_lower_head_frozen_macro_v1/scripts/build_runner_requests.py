#!/usr/bin/env python3
"""Bounded Runner Request Builder for F1 Lower-Head Three-DP Macro Review.

Generates ds02.runner-request.v2 requests for Root review before execution:
- ECC lower-head three-DP all-pair macro evaluation
- DUAL lower-head three-DP all-pair macro evaluation

Pins exact source files, input hashes, and scope limits.
Sets launch_allowed=false (Root review required before execution).
Leaves numerical results strictly pending until Root dispatches the queued conversions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT_INTEGRATION_WT = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
F1_HANDOFF_DIR = Path(__file__).resolve().parents[1]
INTEGRATION_F1_HANDOFF = (
    ROOT_INTEGRATION_WT
    / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F1/handoff_20261003/root_followup_046_lower_head_frozen_macro_v1"
)


def sha256_file(path: Path | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def build_request(
    mother_id: str,
    binding_local_path: Path,
    output_request_path: Path,
) -> dict[str, Any]:
    binding = json.loads(binding_local_path.read_text(encoding="utf-8"))
    scale_reg_local = Path(binding["scale_registration"])
    scale_reg = json.loads(scale_reg_local.read_text(encoding="utf-8"))

    is_ecc = mother_id == "F1_ECC_THICK_DBC_LOWER_HEAD_V1"
    token = "ecc" if is_ecc else "dual"
    frames = 161 if is_ecc else 401

    case_id = f"F1_{token.upper()}_THICK_DBC_LOWER_HEAD_THREE_DP_MACRO"
    attempt_id = f"root-{token}-thick-dbc-lower-head-full{frames}-three-dp-frozen-macro-046"

    # Worker script path in integration WT
    worker_script = (
        INTEGRATION_F1_HANDOFF / "scripts/ds_data02_f1_lower_head_macro_worker.py"
    )
    binding_integration = INTEGRATION_F1_HANDOFF / f"bindings/{binding_local_path.name}"

    python_bin = ROOT_INTEGRATION_WT / "lagrangian-fluid-lab/.venv/bin/python"

    command = [
        str(python_bin),
        str(worker_script),
        "--binding",
        str(binding_integration),
        "--output",
        "{attempt_root}/macro-comparison.json",
        "--allow-pending",
    ]

    # Collect existing input files to hash
    inputs_to_hash = [
        python_bin,
        F1_HANDOFF_DIR / "scripts/ds_data02_f1_lower_head_macro_worker.py",
        binding_local_path,
        scale_reg_local,
        Path(binding["canonical_physical_binding"]),
        Path(binding["initial_qa"]["receipt"]),
    ]

    for c in binding["cases"]:
        inputs_to_hash.append(Path(c["solver_receipt"]))
        inputs_to_hash.append(Path(c["gencase_xml"]))
        if "conversion_request" in c and Path(c["conversion_request"]).is_file():
            inputs_to_hash.append(Path(c["conversion_request"]))

    for exc in binding.get("excluded_historical_attempts", []):
        if Path(exc["receipt"]).is_file():
            inputs_to_hash.append(Path(exc["receipt"]))

    input_sha256 = {}
    input_files_list = []
    for p in sorted(set(inputs_to_hash)):
        if p.is_file():
            input_files_list.append(str(p))
            input_sha256[str(p)] = sha256_file(p)

    req = {
        "schema": "ds02.runner-request.v2",
        "family_id": "F1",
        "case_id": case_id,
        "attempt_id": attempt_id,
        "kind": "cpu",
        "cpu_task_kind": "evaluator",
        "cpu_threads": 1,
        "max_wall_seconds": 180,
        "estimated_storage_bytes": 16777216,
        "cwd": str(ROOT_INTEGRATION_WT / "lagrangian-fluid-lab"),
        "worktree_root": str(ROOT_INTEGRATION_WT),
        "command": command,
        "independent_case_count_increment": 0,
        "production_approval": "none",
        "launch_allowed": False,
        "launch_owner": "root",
        "root_review_before_execution": True,
        "claim": (
            f"Full three-DP all-pair frozen macro evaluator for {mother_id}. "
            "Reuses exact frozen F1 compare_pair operator with lower-head scale factors. "
            "No particle UID matching across DP. Q-N not granted; production approval none; "
            "numerical results pending Root execution of queued converter jobs."
        ),
        "input_files": input_files_list,
        "input_sha256": input_sha256,
        "scale_parameters": {
            "H0_m": scale_reg["H0_m"],
            "continuous_initial_mass_kg": scale_reg["continuous_initial_mass_kg"],
            "energy_scale_J": scale_reg["continuous_energy_scale_J"],
            "full_window_s": scale_reg["full_window_s"],
            "expected_frames": scale_reg["expected_frames"],
            "macro_budget_fraction": scale_reg["macro_budget_fraction"],
            "initial_mass_budget_fraction": scale_reg["initial_mass_budget_fraction"],
        },
        "historical_exclusion_enforced": [
            exc["attempt_id"] for exc in binding.get("excluded_historical_attempts", [])
        ],
    }

    output_request_path.parent.mkdir(parents=True, exist_ok=True)
    output_request_path.write_text(json.dumps(req, indent=2) + "\n", encoding="utf-8")
    return req


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=F1_HANDOFF_DIR / "requests",
        help="Directory to write runner request JSONs",
    )
    args = parser.parse_args()

    ecc_binding = F1_HANDOFF_DIR / "bindings/ecc-lower-head-macro-binding.json"
    dual_binding = F1_HANDOFF_DIR / "bindings/dual-lower-head-macro-binding.json"

    ecc_req = build_request(
        "F1_ECC_THICK_DBC_LOWER_HEAD_V1",
        ecc_binding,
        args.output_dir / "ecc-lower-head-three-dp-macro-request.json",
    )
    print(f"Generated ECC runner request: {ecc_req['attempt_id']}")

    dual_req = build_request(
        "F1_DUAL_THICK_DBC_LOWER_HEAD_V1",
        dual_binding,
        args.output_dir / "dual-lower-head-three-dp-macro-request.json",
    )
    print(f"Generated DUAL runner request: {dual_req['attempt_id']}")


if __name__ == "__main__":
    main()
