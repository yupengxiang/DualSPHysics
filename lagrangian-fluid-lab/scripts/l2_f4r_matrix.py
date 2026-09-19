#!/usr/bin/env python3
"""Run and aggregate the bounded L2-R F4 two-background/three-resolution matrix.

The matrix is intentionally cell-oriented: each invocation owns one physical
GPU and writes one immutable cell report, so up to four cells can run in
parallel without racing the shared resume state.  The aggregate command is
the only path that closes F4R, and it never emits a qualification receipt.
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


SOURCE = LAB / "cases/F4/F4_drop_onto_pool/F4_drop_onto_pool_Def.xml"
ROOT = RESUME_ROOT / "f4r-matrix"
CASE_ROOT = ROOT / "cases"
ARTIFACT_ROOT = ROOT / "artifacts"
DATA_ROOT = ROOT / "data"
RUN_ROOT = CAMPAIGN / "runs"
CELL_ROOT = RESUME_ROOT / "f4r-matrix-cells"
AGGREGATE = RESUME_ROOT / "f4r-matrix.json"
RESOLUTIONS = (0.00818181818181818, 0.0075, 0.006)
BACKGROUNDS = ("center", "offset")
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


def resolution_tag(value: float) -> str:
    return {RESOLUTIONS[0]: "dp0081818", RESOLUTIONS[1]: "dp0075", RESOLUTIONS[2]: "dp006"}[value]


def case_id(background: str, resolution: float) -> str:
    return f"F4R_{background}_drop_pool_{resolution_tag(resolution)}"


def _offset_source(background: str, resolution: float) -> tuple[Path, Path]:
    if not SOURCE.is_file():
        raise FileNotFoundError(SOURCE)
    destination = CASE_ROOT / f"{case_id(background, resolution)}_Def.xml"
    destination.parent.mkdir(parents=True, exist_ok=True)
    tree = ET.parse(SOURCE)
    root = tree.getroot()
    boxes = root.findall(".//geometry/commands/mainlist/drawbox")
    if len(boxes) < 3:
        raise RuntimeError("F4 source geometry does not contain pool, drop, and tank drawboxes")
    if background == "offset":
        point = boxes[1].find("point")
        if point is None:
            raise RuntimeError("F4 drop drawbox has no point")
        point.set("x", "0.25")
    ET.indent(tree, space="    ")
    tree.write(destination, encoding="utf-8", xml_declaration=True)
    return SOURCE, destination


def _live_gpu_allowlist(gpu: int) -> tuple[list[str], dict]:
    records = query_gpus()
    selected = next((row for row in records if row["index"] == gpu), None)
    if selected is None:
        raise RuntimeError(f"GPU {gpu} is not visible")
    return [row["uuid"] for row in records if 0 <= row["index"] <= 7], selected


def run_cell(background: str, resolution: float, gpu: int) -> dict:
    if background not in BACKGROUNDS or resolution not in RESOLUTIONS:
        raise ValueError("cell is outside the frozen F4R matrix")
    state = load_state()
    task = next(item for item in state["tasks"] if item["task_id"] == "F4R")
    if task["status"] not in {"ready", "running"}:
        raise RuntimeError(f"F4R is not dispatchable: {task['status']}")
    allowed, gpu_record = _live_gpu_allowlist(gpu)
    base.CASE_ROOT = CASE_ROOT
    base.ARTIFACT_ROOT = ARTIFACT_ROOT
    base.DATA_ROOT = DATA_ROOT
    base.RUN_ROOT = RUN_ROOT
    source, definition = _offset_source(background, resolution)
    item = {
        "case_id": case_id(background, resolution),
        "family": "F4",
        "mechanism": "finite-drop-pool-impact-reentry",
        "source_definition": definition,
        "recipe_id": f"L2R_F4_drop_pool_{background}_dbc_native_v1_{resolution_tag(resolution)}",
        "physical_case_id": f"physical_L2R_F4_drop_pool_{background}_v1",
        "lineage_group_id": f"lineage_L2R_F4_drop_pool_{background}_v1",
        "paired_background_id": "paired_F4_center_vs_offset_v1",
        "view_id": "world_fluid_particle_v1",
        "resolution_m": resolution,
        "time_max_s": 0.6,
        "time_out_s": 0.02,
        "gpu": gpu,
        "wall_bounds": WALL_BOUNDS,
        "control_semantics": "known initial liquid-column position and gravity; no future fluid state",
    }
    prepared = base.prepare_case(item)
    attempt = base.run_case(prepared, allowed, cuda_visible_devices=str(gpu), solver_gpu=0)
    audit = base.audit_case(prepared, attempt) if attempt["status"] == "completed" else None
    report = {
        "schema": "l2r.f4r.matrix.cell.v1",
        "task": "F4R",
        "created_at_utc": utc_now(),
        "resume_id": state["resume_id"],
        "baseline_commit": state["baseline_commit"],
        "current_commit": state.get("current_commit"),
        "cell": {"background": background, "resolution_m": resolution, "case_id": item["case_id"]},
        "input": {
            "original_source": repo_relative(source),
            "original_source_sha256": sha256_file(source)[0],
            "definition": repo_relative(prepared["definition"]),
            "definition_sha256": prepared["definition_sha256"],
            "generated_xml": repo_relative(prepared["generated_xml"]),
            "generated_xml_sha256": prepared["generated_xml_sha256"],
            "recipe_id": prepared["recipe_id"],
            "wall_bounds": WALL_BOUNDS,
        },
        "attempt": attempt,
        "audit": audit,
        "gpu_policy": {
            "physical_gpu": gpu,
            "live_uuid": gpu_record["uuid"],
            "live_allowlist_indices": list(range(8)),
            "cuda_visible_devices": attempt.get("cuda_visible_devices"),
            "solver_gpu_argument": attempt.get("solver_gpu_argument"),
            "historical_inventory_not_reused": True,
        },
        "qualification_claim": "none; F4R matrix cell evidence only",
        "receipt_emitted": False,
        "status": "complete_with_findings" if audit and audit.get("canary_hard_integrity_pass") else (
            "complete_with_findings" if attempt["status"] == "completed" else "blocked_external"
        ),
    }
    path = CELL_ROOT / f"{item['case_id']}.json"
    atomic_json(path, report)
    return report


def aggregate() -> dict:
    state = load_state()
    cells = []
    missing = []
    for background in BACKGROUNDS:
        for resolution in RESOLUTIONS:
            path = CELL_ROOT / f"{case_id(background, resolution)}.json"
            if not path.is_file():
                missing.append(str(path))
            else:
                cells.append(json.loads(path.read_text()))
    completed = [cell for cell in cells if cell.get("attempt", {}).get("status") == "completed"]
    structural = [cell for cell in completed if (cell.get("audit") or {}).get("canary_hard_integrity_pass")]
    report = {
        "schema": "l2r.f4r.matrix.v1",
        "task": "F4R",
        "created_at_utc": utc_now(),
        "resume_id": state["resume_id"],
        "baseline_commit": state["baseline_commit"],
        "current_commit": state.get("current_commit"),
        "matrix": {
            "backgrounds": list(BACKGROUNDS),
            "resolutions_m": list(RESOLUTIONS),
            "expected_cell_count": len(BACKGROUNDS) * len(RESOLUTIONS),
            "cell_count": len(cells),
            "completed_solver_count": len(completed),
            "structural_pass_count": len(structural),
            "missing_cells": missing,
        },
        "cells": cells,
        "qualification_claim": "none; bounded F4R matrix evidence only",
        "receipt_emitted": False,
        "decision": "matrix closed with findings; no F4 family qualification",
        "acceptance": {
            "all_six_cells_present": not missing and len(cells) == 6,
            "all_solver_attempts_recorded": len(completed) == 6,
            "finite_wall_audit_recorded_for_each": all(cell.get("audit", {}).get("independent_audit", {}).get("wall_status") == "checked" for cell in completed),
            "no_qualification_claim": True,
            "no_receipt_emitted": True,
        },
        "next_action": "retain bounded F4 scope; do not admit D0 without a separate qualified receipt",
    }
    atomic_json(AGGREGATE, report)
    if report["acceptance"]["all_six_cells_present"] and report["acceptance"]["all_solver_attempts_recorded"]:
        mark_task("F4R", "complete_with_findings", artifacts=["resume-c6b28c8/f4r-matrix.json"], next_action=report["next_action"])
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    cell = sub.add_parser("cell")
    cell.add_argument("background", choices=BACKGROUNDS)
    cell.add_argument("resolution", type=float, choices=RESOLUTIONS)
    cell.add_argument("--gpu", type=int, required=True)
    sub.add_parser("aggregate")
    args = parser.parse_args()
    if args.command == "cell":
        report = run_cell(args.background, args.resolution, args.gpu)
        print(json.dumps({
            "case_id": report["cell"]["case_id"],
            "attempt_status": report["attempt"]["status"],
            "audit_pass": (report.get("audit") or {}).get("canary_hard_integrity_pass"),
            "report": str(CELL_ROOT / f"{report['cell']['case_id']}.json"),
        }, ensure_ascii=False, indent=2))
    else:
        report = aggregate()
        print(json.dumps({
            "status": report["matrix"],
            "acceptance": report["acceptance"],
            "report": str(AGGREGATE),
        }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
