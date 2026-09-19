#!/usr/bin/env python3
"""Close the L2-R R2 F3 contract with source-only oracle evidence.

R2 is deliberately separate from the historical L2 stage labels.  It records
the current F3 recipe contract, runs the repository's source-only oracle on
retained trajectories, and makes the legacy-only reuse boundary explicit.  A
source trajectory oracle is not a model qualification or an external-validity
claim.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

try:
    from scripts.l2_campaign import (
        CAMPAIGN,
        LAB,
        atomic_json,
        file_evidence,
        oracle_for_hdf5,
        read_json,
        repo_relative,
        sha256_file,
        utc_now,
    )
    from scripts.l2_resume import RESUME_ROOT, load_state, mark_task
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from l2_campaign import (
        CAMPAIGN,
        LAB,
        atomic_json,
        file_evidence,
        oracle_for_hdf5,
        read_json,
        repo_relative,
        sha256_file,
        utc_now,
    )
    from l2_resume import RESUME_ROOT, load_state, mark_task


MANIFEST = CAMPAIGN / "evidence" / "f3-canonical-manifest.json"
REPORT = RESUME_ROOT / "r2-f3-contract.json"

# These are the three retained numerical references used by the prior A1
# oracle diagnostics.  They are intentionally read-only inputs to R2; none is
# promoted into a newly qualified family or production receipt.
ORACLE_CASES = (
    ("legacy_endpoint_low", LAB / "campaigns/l1-resume/data/continuation/R0081818-ENDPOINT-LOW.h5"),
    ("legacy_nominal", LAB / "campaigns/l1-resume/data/continuation/R0081818-NOMINAL.h5"),
    ("legacy_endpoint_high", LAB / "campaigns/l1-resume/data/continuation/R0081818-ENDPOINT-HIGH.h5"),
)


def current_contract(manifest: dict) -> dict:
    recipe = manifest.get("recipe", {})
    required = {
        "recipe_id",
        "production_resolution_m",
        "reference_resolutions_m",
        "solver_mode",
        "boundary",
        "slip_mode",
        "no_penetration",
        "visco",
        "visco_bound_factor",
        "shifting",
        "native_velocity_displacement_correction",
        "posthoc_particle_projection",
        "time_window_s",
        "output_interval_s",
        "control_domain",
        "coordinate_frame",
        "trajectory_semantics",
    }
    missing = sorted(required - set(recipe))
    values_ok = (
        recipe.get("production_resolution_m") == 0.0075
        and recipe.get("reference_resolutions_m") == [0.00818181818181818, 0.0075, 0.006]
        and recipe.get("native_velocity_displacement_correction") is True
        and recipe.get("posthoc_particle_projection") is False
        and recipe.get("no_penetration") is True
        and recipe.get("coordinate_frame") == "fixed tank computational coordinates"
        and "numerical SPH particle identity" in str(recipe.get("trajectory_semantics"))
    )
    return {
        "recipe": recipe,
        "required_fields_present": not missing,
        "missing_fields": missing,
        "values_match_locked_recipe": bool(values_ok),
        "legacy_historical_resolution_m": recipe.get("historical_resolution_m"),
        "manifest_status": manifest.get("status"),
        "qualification_axes": manifest.get("qualification_axes", {}),
    }


def run() -> dict:
    state = load_state()
    task = next(item for item in state["tasks"] if item["task_id"] == "R2")
    if task["status"] not in {"ready", "running"}:
        raise RuntimeError(f"R2 is not dispatchable: {task['status']}")
    if not MANIFEST.is_file():
        raise FileNotFoundError(MANIFEST)

    manifest = read_json(MANIFEST)
    contract = current_contract(manifest)
    oracle_runs = []
    for label, path in ORACLE_CASES:
        oracle_runs.append({
            "label": label,
            "source": file_evidence(path),
            "source_sha256": sha256_file(path)[0] if path.is_file() else None,
            "oracle": oracle_for_hdf5(path),
            "scope": "source trajectory only; no model or external validation",
        })

    all_sources_present = all(item["source"].get("exists") for item in oracle_runs)
    report = {
        "schema": "l2r.r2.f3_contract.v1",
        "task": "R2",
        "created_at_utc": utc_now(),
        "resume_id": state["resume_id"],
        "baseline_commit": state["baseline_commit"],
        "current_commit": state.get("current_commit"),
        "contract": {
            **contract,
            "manifest": {
                "path": repo_relative(MANIFEST),
                "sha256": sha256_file(MANIFEST)[0],
            },
        },
        "actual_oracle_runs": oracle_runs,
        "legacy_reuse_manifest": {
            "policy": "retained F3 references are legacy numerical evidence only",
            "promotion_to_new_family_receipt": False,
            "promotion_to_D0_production": False,
            "promotion_to_new_split": False,
            "source_manifest_baseline_commit": manifest.get("baseline_commit"),
            "referenced_cases": [
                {"label": label, "path": repo_relative(path), "sha256": sha256_file(path)[0] if path.is_file() else None}
                for label, path in ORACLE_CASES
            ],
        },
        "acceptance": {
            "current_f3_contract_recorded": bool(contract["required_fields_present"] and contract["values_match_locked_recipe"]),
            "actual_oracle_runs_recorded": bool(all_sources_present and len(oracle_runs) == len(ORACLE_CASES)),
            "legacy_reuse_boundary_explicit": True,
            "model_and_external_qualification_separate": True,
        },
        "status": "complete_with_findings",
        "decision": "current_contract_and_source_oracles_closed; legacy references remain non-promotable",
        "next_action": "execute_B2R_after_R2; continue family research independently",
    }
    atomic_json(REPORT, report)
    mark_task(
        "R2",
        "complete_with_findings",
        artifacts=["resume-c6b28c8/r2-f3-contract.json"],
        next_action=report["next_action"],
    )
    return report


def main() -> int:
    report = run()
    print(json.dumps({
        "status": report["status"],
        "decision": report["decision"],
        "oracle_count": len(report["actual_oracle_runs"]),
        "acceptance": report["acceptance"],
        "report": str(REPORT),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
