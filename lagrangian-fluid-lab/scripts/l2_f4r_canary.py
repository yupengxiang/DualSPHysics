#!/usr/bin/env python3
"""Launch one new F4R offset-drop canary on an explicitly selected GPU.

This is a resumable first step of the F4 two-background/three-resolution
matrix.  It deliberately remains a canary: no recipe receipt or family
qualification is produced by this command.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import xml.etree.ElementTree as ET

try:
    from scripts import l2_c1_canary as base
    from scripts.campaign_runner import query_gpus
    from scripts.l2_campaign import CAMPAIGN, LAB, atomic_json, repo_relative, sha256_file, utc_now
    from scripts.l2_resume import RESUME_ROOT, load_state, mark_task
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    import l2_c1_canary as base
    from campaign_runner import query_gpus
    from l2_campaign import CAMPAIGN, LAB, atomic_json, repo_relative, sha256_file, utc_now
    from l2_resume import RESUME_ROOT, load_state, mark_task


F4R_ROOT = RESUME_ROOT / "f4r"
CASE_ROOT = F4R_ROOT / "cases"
ARTIFACT_ROOT = F4R_ROOT / "artifacts"
DATA_ROOT = F4R_ROOT / "data"
RUN_ROOT = CAMPAIGN / "runs"
REPORT = RESUME_ROOT / "f4r-offset-canary.json"
SOURCE = LAB / "cases/F4/F4_drop_onto_pool/F4_drop_onto_pool_Def.xml"
WALL_BOUNDS = {
    "xmin": 0.0,
    "xmax": 1.2,
    "ymin": 0.0,
    "ymax": 0.4,
    "zmin": 0.0,
    "zmax": 0.6,
    "closed_faces": ["bottom", "left", "right", "front", "back"],
    "open_faces": ["top"],
}


def live_allowed_uuids(index: int) -> tuple[list[str], dict]:
    records = query_gpus()
    selected = next((item for item in records if item["index"] == index), None)
    if selected is None:
        raise RuntimeError(f"GPU {index} is not visible")
    # The old A6000 inventory is retained as historical evidence.  This new
    # remote launch uses the owner's explicit H200 index and live UUID.
    return [item["uuid"] for item in records if item["index"] in {0, 2, 3}], selected


def make_offset_source() -> Path:
    if not SOURCE.is_file():
        raise FileNotFoundError(SOURCE)
    destination = CASE_ROOT / "L2R_F4_offset_drop_pool_dp0075_Def.xml"
    destination.parent.mkdir(parents=True, exist_ok=True)
    tree = ET.parse(SOURCE)
    root = tree.getroot()
    drawboxes = root.findall(".//geometry/commands/mainlist/drawbox")
    if len(drawboxes) < 3:
        raise RuntimeError("F4 source geometry does not contain pool, drop, and tank drawboxes")
    drop_point = drawboxes[1].find("point")
    if drop_point is None:
        raise RuntimeError("F4 drop drawbox has no point")
    # The legacy center drop starts at x=0.47.  Move the same finite liquid
    # column left while retaining the pool, tank and all solver semantics.
    drop_point.set("x", "0.25")
    ET.indent(tree, space="    ")
    tree.write(destination, encoding="utf-8", xml_declaration=True)
    return destination


def config(gpu: int) -> dict:
    return {
        "case_id": "L2R_F4_offset_drop_pool_dp0075_canary",
        "family": "F4",
        "mechanism": "offset-drop-pool-impact-reentry",
        "source_definition": make_offset_source(),
        "recipe_id": "L2R_F4_offset_drop_pool_dbc_v1_dp0p0075_canary",
        "physical_case_id": "physical_L2R_F4_offset_drop_pool_v1",
        "lineage_group_id": "lineage_L2R_F4_offset_drop_pool_v1",
        "paired_background_id": "paired_F4_center_vs_offset_v1",
        "view_id": "world_fluid_particle_v1",
        "resolution_m": 0.0075,
        "time_max_s": 0.6,
        "time_out_s": 0.02,
        "gpu": gpu,
        "wall_bounds": WALL_BOUNDS,
        "control_semantics": "known initial liquid-column offset and gravity; no future fluid state",
    }


def run(gpu: int) -> dict:
    resume = load_state()
    task = next(item for item in resume["tasks"] if item["task_id"] == "F4R")
    if task["status"] not in {"ready", "running"}:
        raise RuntimeError(f"F4R is not dispatchable: {task['status']}")
    if gpu not in {0, 2, 3}:
        raise ValueError("F4R remote canary is restricted to owner-approved H200 GPUs 0, 2, and 3")
    allowed_uuids, launch_gpu = live_allowed_uuids(gpu)
    base.CASE_ROOT = CASE_ROOT
    base.ARTIFACT_ROOT = ARTIFACT_ROOT
    base.DATA_ROOT = DATA_ROOT
    base.RUN_ROOT = RUN_ROOT
    item = config(gpu)
    mark_task("F4R", "running", next_action="complete_two_background_three_resolution_matrix")
    prepared = base.prepare_case(item)
    attempt = base.run_case(prepared, allowed_uuids)
    audit = None
    if attempt["status"] == "completed":
        audit = base.audit_case(prepared, attempt)
    report = {
        "schema": "l2r.f4r.offset_canary.v1",
        "stage": "F4R",
        "created_at_utc": utc_now(),
        "baseline_commit": resume["baseline_commit"],
        "current_commit": resume.get("current_commit"),
        "scope": {
            "background": "offset_drop_left_x0p25",
            "paired_background": "center_drop_legacy_canary_not_promoted",
            "resolution_m": prepared["resolution_m"],
            "time_max_s": prepared["time_max_s"],
            "new_control_or_geometry": True,
        },
        "input": {
            "source_definition": repo_relative(SOURCE),
            "source_definition_sha256": sha256_file(SOURCE)[0],
            "offset_definition": repo_relative(prepared["source_definition"]),
            "offset_definition_sha256": prepared["source_definition_sha256"],
            "generated_xml": repo_relative(prepared["generated_xml"]),
            "generated_xml_sha256": prepared["generated_xml_sha256"],
            "recipe_id": prepared["recipe_id"],
            "wall_bounds": WALL_BOUNDS,
        },
        "attempt": attempt,
        "audit": audit,
        "gpu_policy": {
            "requested_index": gpu,
            "launch_record": launch_gpu,
            "live_allowed_indices": [0, 2, 3],
            "live_allowed_uuids": allowed_uuids,
            "historical_a6000_inventory_not_reused": True,
        },
        "qualification_claim": "none; first F4R canary only",
        "receipt_emitted": False,
        "next_action": "run_center_and_offset_reference_matrix_at_three_resolutions",
        "resource_observation": {
            "gpu_hours": attempt.get("elapsed_seconds", 0.0) / 3600.0,
            "qualification_solver_attempts": 1,
            "new_storage_bytes": 0,
        },
    }
    atomic_json(REPORT, report)
    report["resource_observation"]["new_storage_bytes"] = REPORT.stat().st_size
    atomic_json(REPORT, report)
    # Keep F4R running: one canary is evidence for the next matrix, not a
    # terminal qualification or a D0 receipt.
    mark_task("F4R", "running", artifacts=["resume-c6b28c8/f4r-offset-canary.json"], next_action=report["next_action"])
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gpu", type=int, default=2)
    args = parser.parse_args()
    report = run(args.gpu)
    print(json.dumps({
        "status": report["attempt"]["status"],
        "audit_structural_pass": report["audit"].get("structural_pass") if report["audit"] else None,
        "gpu": report["gpu_policy"]["requested_index"],
        "report": str(REPORT),
    }, ensure_ascii=False, indent=2))
    return 0 if report["attempt"]["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
