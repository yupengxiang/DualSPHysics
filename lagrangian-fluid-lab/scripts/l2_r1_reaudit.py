#!/usr/bin/env python3
"""Re-audit the five retained L2 canaries without launching new CFD jobs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from scripts.l2_campaign import CAMPAIGN, atomic_json, inspect_hdf5, read_json, sha256_file, utc_now
    from scripts.l2_resume import RESUME_ROOT, load_state, mark_task
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from l2_campaign import CAMPAIGN, atomic_json, inspect_hdf5, read_json, sha256_file, utc_now
    from l2_resume import RESUME_ROOT, load_state, mark_task


REPORT = RESUME_ROOT / "r1-reaudit.json"
MARKDOWN = RESUME_ROOT / "r1-reaudit.md"

STATIC_TANK = {
    "xmin": 0.0,
    "xmax": 1.2,
    "ymin": 0.0,
    "ymax": 0.4,
    "zmin": 0.0,
    "zmax": 0.6,
    "closed_faces": ["bottom", "left", "right", "front", "back"],
    "open_faces": ["top"],
}

CASE_SPECS: tuple[dict[str, Any], ...] = (
    {
        "case_id": "L2_C1_F1_obstacle_nominal",
        "family": "F1",
        "hdf5": "c1-canary/data/L2_C1_F1_obstacle_nominal.h5",
        "definition": "c1-canary/cases/L2_C1_F1_obstacle_nominal_Def.xml",
        "wall_spec": {
            **STATIC_TANK,
            "obstacles": [{"id": "center_obstacle", "xmin": 0.68, "xmax": 0.80, "ymin": 0.15, "ymax": 0.25, "zmin": 0.0, "zmax": 0.34}],
        },
    },
    {
        "case_id": "L2_C1_F2_rotation_center_nominal",
        "family": "F2",
        "hdf5": "c1-canary/data/L2_C1_F2_rotation_center_nominal.h5",
        "definition": "c1-canary/cases/L2_C1_F2_rotation_center_nominal_Def.xml",
        "wall_spec": {
            "container_interior": {"xmin": -0.60, "xmax": 2.0, "ymin": -0.55, "ymax": 0.55, "zmin": -0.25, "zmax": 1.40},
            "closed_faces": ["bottom", "left", "right", "front", "back"],
            "open_faces": ["top"],
            "moving_geometry_required": True,
        },
    },
    {
        "case_id": "L2_C2_F3_offaxis_baffle_nominal",
        "family": "F3",
        "hdf5": "c2-canary/data/L2_C2_F3_offaxis_baffle_nominal.h5",
        "definition": "c2-canary/cases/L2_C2_F3_offaxis_baffle_nominal_Def.xml",
        "wall_spec": {
            **STATIC_TANK,
            "obstacles": [{"id": "offaxis_baffle", "xmin": 0.58, "xmax": 0.62, "ymin": 0.04, "ymax": 0.14, "zmin": 0.0, "zmax": 0.19}],
        },
    },
    {
        "case_id": "L2_C3_F4_drop_pool_nominal",
        "family": "F4",
        "hdf5": "c3-canary/data/L2_C3_F4_drop_pool_nominal.h5",
        "definition": "c3-canary/cases/L2_C3_F4_drop_pool_nominal_Def.xml",
        "wall_spec": STATIC_TANK,
    },
    {
        "case_id": "L2_C3_F5_low_weir_nominal",
        "family": "F5",
        "hdf5": "c3-canary/data/L2_C3_F5_low_weir_nominal.h5",
        "definition": "c3-canary/cases/L2_C3_F5_low_weir_nominal_Def.xml",
        "wall_spec": {
            **STATIC_TANK,
            "obstacles": [{"id": "low_weir", "xmin": 0.64, "xmax": 0.74, "ymin": 0.04, "ymax": 0.36, "zmin": 0.0, "zmax": 0.23}],
        },
    },
)


def _legacy_records() -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for name in ("c1-canary.json", "c2-f3-canary.json", "c3-bounded-anchors.json"):
        path = CAMPAIGN / "reports" / name
        if not path.is_file():
            continue
        payload = read_json(path)

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                case_id = value.get("case_id")
                if case_id and any(key in value for key in ("initial_mass_kg", "missing_initial_identities_at_final", "independent_audit")):
                    records[str(case_id)] = value
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(payload)
    return records


def _attempt_join(case_id: str, attempt_id: str | None) -> dict[str, Any]:
    root = CAMPAIGN / "runs" / case_id / "attempts"
    candidates = sorted(root.glob("*/attempt.json")) if root.is_dir() else []
    matching = []
    for path in candidates:
        try:
            payload = read_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if attempt_id is None or payload.get("attempt_id") == attempt_id:
            matching.append((path, payload))
    if not matching:
        return {"status": "missing_raw_attempt", "attempt_id": attempt_id, "candidate_count": len(candidates)}
    path, payload = matching[0]
    return {
        "status": "joined_attempt_manifest",
        "attempt_id": payload.get("attempt_id"),
        "attempt_manifest": str(path.resolve()),
        "attempt_status": payload.get("status"),
        "raw_data_directory": str(path.parent / "data"),
        "raw_bi4_count": len(list((path.parent / "data").glob("*.bi4"))),
        "raw_csv_count": len(list((path.parent / "csv").glob("*.csv"))),
    }


def run() -> dict[str, Any]:
    resume = load_state()
    task = next(item for item in resume["tasks"] if item["task_id"] == "R1")
    if task["status"] not in {"ready", "running"}:
        raise RuntimeError(f"R1 is not dispatchable: {task['status']}")
    legacy = _legacy_records()
    cases: list[dict[str, Any]] = []
    for spec in CASE_SPECS:
        hdf5 = CAMPAIGN / spec["hdf5"]
        definition = CAMPAIGN / spec["definition"]
        audit = inspect_hdf5(hdf5, full_scan=True, wall_spec=spec["wall_spec"])
        attempt_join = _attempt_join(spec["case_id"], audit.get("attrs", {}).get("attempt_id"))
        old = legacy.get(spec["case_id"], {})
        cases.append({
            "case_id": spec["case_id"],
            "family": spec["family"],
            "hdf5": {"path": str(hdf5.resolve()), "sha256": sha256_file(hdf5)[0] if hdf5.is_file() else None},
            "definition": {"path": str(definition.resolve()), "sha256": sha256_file(definition)[0] if definition.is_file() else None},
            "audit": audit,
            "native_loss_join": attempt_join,
            "legacy_denominator": {
                "initial_mass_kg": old.get("initial_mass_kg"),
                "final_mass_kg": old.get("final_mass_kg"),
                "missing_initial_identities_at_final": old.get("missing_initial_identities_at_final"),
                "source_report": old.get("source_report"),
            },
            "promotion": "audit_only; no canary or legacy record is promoted to T1",
        })
    all_joined = all(item["native_loss_join"]["status"] == "joined_attempt_manifest" for item in cases)
    report = {
        "schema": "l2r.r1.zero_cfd_reaudit.v1",
        "stage": "R1",
        "created_at_utc": utc_now(),
        "baseline_commit": resume["baseline_commit"],
        "current_commit": resume.get("current_commit"),
        "new_cfd_jobs": 0,
        "retained_canary_count": len(cases),
        "cases": cases,
        "acceptance": {
            "five_canaries_reaudited": len(cases) == 5,
            "active_finite_and_positive_mass_reported": all("finite_active" in item["audit"] and item["audit"]["active_mass_positive"] for item in cases),
            "native_loss_join_manifest_present": all_joined,
            "inactive_mask_and_lifecycle_separated": all("inactive_nonfinite_counts" in item["audit"] and "lifecycle_model" in item["audit"] for item in cases),
            "finite_wall_unknown_is_retained": any(item["audit"].get("wall_status") == "unknown" for item in cases),
            "old_reports_immutable": True,
        },
        "interpretation": {
            "structural_pass_count": sum(item["audit"].get("structural_pass", False) for item in cases),
            "finite_wall_checked_count": sum(item["audit"].get("wall_status") == "checked" for item in cases),
            "finite_wall_unknown_count": sum(item["audit"].get("wall_status") == "unknown" for item in cases),
            "lifecycle_failure_count": sum("lifecycle:closed_transition" in item["audit"].get("errors", []) for item in cases),
            "mass_failure_count": sum(any(error.startswith("mass:") for error in item["audit"].get("errors", [])) for item in cases),
            "wall_failure_count": sum(item["audit"].get("wall_violation_count", 0) > 0 for item in cases),
        },
        "resource_observation": {"gpu_hours": 0.0, "new_storage_bytes": 0},
    }
    report["status"] = "complete_with_findings" if all(report["acceptance"].values()) else "blocked_upstream"
    atomic_json(REPORT, report)
    MARKDOWN.write_text(
        "# R1 零新增 CFD 重审\n\n"
        f"- 重审 canary：`{len(cases)}`\n"
        f"- 新 CFD：`0`\n"
        f"- structural pass：`{report['interpretation']['structural_pass_count']}`\n"
        f"- 有限壁面已知/未知：`{report['interpretation']['finite_wall_checked_count']}/{report['interpretation']['finite_wall_unknown_count']}`\n"
        f"- 结论：`{report['status']}`；旧报告保持只读。\n"
    )
    if report["status"] == "complete_with_findings":
        mark_task("R1", "complete_with_findings", artifacts=[
            "resume-c6b28c8/r1-reaudit.json",
            "resume-c6b28c8/r1-reaudit.md",
        ], next_action="execute_R2_and_family_research")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    report = run()
    print(json.dumps({"status": report["status"], "cases": report["retained_canary_count"], "report": str(REPORT)}, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "complete_with_findings" else 2


if __name__ == "__main__":
    raise SystemExit(main())
