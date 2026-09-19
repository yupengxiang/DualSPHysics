#!/usr/bin/env python3
"""Execute bounded L2-R family canaries for F1R, F2R, or F3R.

Each invocation owns one task namespace and runs two paired backgrounds at the
nominal 0.0075 m spacing.  The outputs are evidence for the next matrix, not
family qualification receipts.  The wrapper deliberately does not mutate the
shared L2-R state while heavy jobs are running; the dispatcher marks the task
after inspecting this report so concurrent invocations cannot clobber state.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import xml.etree.ElementTree as ET

try:
    from scripts import l2_c1_canary as base
    from scripts.l2_campaign import CAMPAIGN, LAB, atomic_json, repo_relative, sha256_file, utc_now
    from scripts.l2_resume import RESUME_ROOT, load_state
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    import l2_c1_canary as base
    from l2_campaign import CAMPAIGN, LAB, atomic_json, repo_relative, sha256_file, utc_now
    from l2_resume import RESUME_ROOT, load_state


NOMINAL_DP = 0.0075
TASKS = {"F1R", "F2R", "F3R"}
TASK_ROOT = RESUME_ROOT / "family-canaries"
REPORTS = {task: RESUME_ROOT / f"{task.lower()}-family-canaries.json" for task in TASKS}

TANK = {
    "xmin": 0.0,
    "xmax": 1.2,
    "ymin": 0.0,
    "ymax": 0.4,
    "zmin": 0.0,
    "zmax": 0.6,
    "closed_faces": ["bottom", "left", "right", "front", "back"],
    "open_faces": ["top"],
}


def _mainlist(root: ET.Element) -> ET.Element:
    value = root.find(".//geometry/commands/mainlist")
    if value is None:
        raise RuntimeError("case definition has no geometry mainlist")
    return value


def _drawboxes(root: ET.Element) -> list[ET.Element]:
    return _mainlist(root).findall("drawbox")


def _set_point(box: ET.Element, **values: str) -> None:
    point = box.find("point")
    if point is None:
        raise RuntimeError("drawbox has no point")
    for key, value in values.items():
        point.set(key, value)


def _set_size(box: ET.Element, **values: str) -> None:
    size = box.find("size")
    if size is None:
        raise RuntimeError("drawbox has no size")
    for key, value in values.items():
        size.set(key, value)


def _write_variant(task: str, variant: str) -> tuple[Path, Path]:
    if task == "F1R":
        source = LAB / "cases/F1/F1_center_obstacle/F1_center_obstacle_Def.xml"
    elif task == "F2R":
        source = LAB / "campaigns/v0.1-candidate/cases/w06/W06_standard_slow_center_Def.xml"
    else:
        source = LAB / "cases/F3/F3_baffled_slosh/F3_baffled_slosh_Def.xml"
    if not source.is_file():
        raise FileNotFoundError(source)
    destination = TASK_ROOT / task.lower() / "cases" / f"{task}_{variant}_Def.xml"
    destination.parent.mkdir(parents=True, exist_ok=True)
    tree = ET.parse(source)
    root = tree.getroot()
    boxes = _drawboxes(root)

    if task == "F1R":
        # drawboxes 2 and 3 are the finite obstacle void and its boundary.
        # The offset background changes obstacle placement but preserves the
        # tank, initial liquid column and native solver semantics.
        if len(boxes) < 4:
            raise RuntimeError("F1 geometry changed; expected tank and obstacle boxes")
        x = "0.68" if variant == "center" else "0.82"
        for box in boxes[2:4]:
            _set_point(box, x=x)
    elif task == "F2R":
        # The three fluid layers are boxes 3..5.  Shift only the initial
        # source layer in y; the prescribed cup motion remains explicit and
        # replayable, giving a paired centered/off-center catch background.
        if len(boxes) < 6:
            raise RuntimeError("F2 geometry changed; expected three fluid layers")
        y = "-0.11" if variant == "center" else "-0.02"
        for box in boxes[3:6]:
            _set_point(box, y=y)
    else:
        # Convert the full-width baffle into a finite lower baffle with an
        # upper connected passage.  The second background adds a known y
        # impulse while retaining no future fluid state as an input.
        if len(boxes) < 4:
            raise RuntimeError("F3 geometry changed; expected four drawboxes")
        for box in boxes[2:4]:
            _set_point(box, y="0.04")
            _set_size(box, y="0.10")
        velocity = root.find(".//initials/velocity")
        if variant == "multi_axis":
            if velocity is None:
                raise RuntimeError("F3 multi-axis variant has no initial velocity")
            velocity.set("y", "0.25")

    ET.indent(tree, space="    ")
    tree.write(destination, encoding="utf-8", xml_declaration=True)
    return source, destination


def configs(task: str, gpu: int) -> list[dict]:
    if task == "F1R":
        variants = ("center", "offset")
        common = {
            "family": "F1",
            "mechanism": "resolved-obstacle-collapse-split-return",
            "recipe_prefix": "L2R_F1_obstacle",
            "time_max_s": 0.6,
            "time_out_s": 0.02,
            "control_semantics": "known initial liquid column and gravity; no future fluid state",
            "wall_bounds": {
                **TANK,
                "obstacles": [{"id": "center_or_offset_obstacle", "xmin": 0.68, "xmax": 0.80, "ymin": 0.15, "ymax": 0.25, "zmin": 0.0, "zmax": 0.34}],
            },
        }
    elif task == "F2R":
        variants = ("center", "offcenter")
        common = {
            "family": "F2",
            "mechanism": "real-rotating-cup-centered-versus-offcenter-catch",
            "recipe_prefix": "L2R_F2_rotation_cup",
            "time_max_s": 2.5,
            "time_out_s": 0.02,
            "control_semantics": "known prescribed cup rotation; no future fluid state",
            "wall_bounds": {"moving_geometry_required": True, "geometry_mode": "moving"},
        }
    else:
        variants = ("offaxis", "multi_axis")
        common = {
            "family": "F3",
            "mechanism": "off-axis-connected-passage-transverse-exchange",
            "recipe_prefix": "L2R_F3_connected_passage",
            "time_max_s": 0.9,
            "time_out_s": 0.02,
            "control_semantics": "known initial x/y impulse and gravity; no future fluid state",
            "wall_bounds": TANK,
        }
    result = []
    for variant in variants:
        source, destination = _write_variant(task, variant)
        wall_bounds = dict(common["wall_bounds"])
        if task == "F1R":
            obstacle = dict(wall_bounds["obstacles"][0])
            if variant == "offset":
                obstacle.update(xmin=0.82, xmax=0.94)
            wall_bounds["obstacles"] = [obstacle]
        result.append({
            "case_id": f"{task}_{variant}_dp0075",
            "family": common["family"],
            "mechanism": common["mechanism"],
            "source_definition": destination,
            "original_definition": source,
            "recipe_id": f"{common['recipe_prefix']}_{variant}_dbc_native_v1_dp0p0075",
            "physical_case_id": f"physical_{task}_{variant}_v1",
            "lineage_group_id": f"lineage_{task}_{variant}_v1",
            "paired_background_id": f"paired_{task}_center_vs_variant_v1",
            "view_id": "world_fluid_particle_v1",
            "resolution_m": NOMINAL_DP,
            "time_max_s": common["time_max_s"],
            "time_out_s": common["time_out_s"],
            "gpu": gpu,
            "wall_bounds": wall_bounds,
            "control_semantics": common["control_semantics"],
            "variant": variant,
        })
    return result


def run(task: str, gpu: int) -> dict:
    if task not in TASKS:
        raise ValueError(f"unknown task {task!r}; choose one of {sorted(TASKS)}")
    state = load_state()
    resume_task = next(item for item in state["tasks"] if item["task_id"] == task)
    if resume_task["status"] not in {"ready", "running"}:
        raise RuntimeError(f"{task} is not dispatchable: {resume_task['status']}")

    root = TASK_ROOT / task.lower()
    base.CASE_ROOT = root / "cases"
    base.ARTIFACT_ROOT = root / "artifacts"
    base.DATA_ROOT = root / "data"
    base.RUN_ROOT = CAMPAIGN / "runs"
    allowed = base.inventory_allowlist()
    prepared = [base.prepare_case(item) for item in configs(task, gpu)]
    attempts = []
    audits = []
    stop_reason = None
    for item in prepared:
        attempt = base.run_case(item, allowed, cuda_visible_devices=str(gpu), solver_gpu=0)
        attempts.append({
            "case_id": item["case_id"],
            "variant": item["variant"],
            "attempt": attempt,
            "source_definition": repo_relative(item["original_definition"]),
            "source_definition_sha256": sha256_file(item["original_definition"])[0],
            "definition": repo_relative(item["definition"]),
            "definition_sha256": item["definition_sha256"],
            "generated_xml": repo_relative(item["generated_xml"]),
            "generated_xml_sha256": item["generated_xml_sha256"],
            "recipe_id": item["recipe_id"],
        })
        if attempt["status"] != "completed":
            stop_reason = "first paired canary did not complete; second background was not admitted"
            break
        audit = base.audit_case(item, attempt)
        audits.append(audit)
        if not audit.get("canary_hard_integrity_pass"):
            stop_reason = "paired canary reached a bounded structural finding; no qualification claim"
            break

    report = {
        "schema": "l2r.family_canaries.v1",
        "task": task,
        "created_at_utc": utc_now(),
        "resume_id": state["resume_id"],
        "baseline_commit": state["baseline_commit"],
        "current_commit": state.get("current_commit"),
        "scope": {
            "paired_backgrounds": [item["variant"] for item in prepared],
            "resolution_m": NOMINAL_DP,
            "new_execution_required": True,
            "legacy_canaries_not_reused_as_new_attempts": True,
        },
        "prepared_cases": [
            {
                "case_id": item["case_id"],
                "variant": item["variant"],
                "recipe_id": item["recipe_id"],
                "source_definition": repo_relative(item["original_definition"]),
                "source_definition_sha256": sha256_file(item["original_definition"])[0],
                "definition": repo_relative(item["definition"]),
                "definition_sha256": item["definition_sha256"],
                "resolution_m": item["resolution_m"],
            }
            for item in prepared
        ],
        "attempts": attempts,
        "audits": audits,
        "status": "complete_with_findings",
        "decision": "new paired canary evidence recorded; family qualification not claimed",
        "stop_reason": stop_reason,
        "qualification_claim": "none; bounded L2-R canary evidence only",
        "T2_macro": "not_assessed",
        "T2_path": "not_assessed",
        "gpu_policy": {
            "physical_gpu": gpu,
            "cuda_visible_devices": str(gpu),
            "solver_gpu_argument": 0,
            "isolation": "single visible GPU with solver-local index 0",
        },
        "acceptance": {
            "two_background_records_or_bounded_stop": bool(attempts),
            "actual_new_execution": bool(attempts and all(item["attempt"].get("status") == "completed" for item in attempts)),
            "structural_audits_recorded": len(audits) == len(attempts),
            "no_family_qualification_claim": True,
            "moving_geometry_unknown_is_explicit": task != "F2R" or any(
                audit.get("independent_audit", {}).get("wall_status") == "unknown" for audit in audits
            ),
        },
    }
    report_path = REPORTS[task]
    atomic_json(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", choices=sorted(TASKS))
    parser.add_argument("--gpu", type=int, required=True)
    args = parser.parse_args()
    report = run(args.task, args.gpu)
    print(json.dumps({
        "task": report["task"],
        "status": report["status"],
        "decision": report["decision"],
        "attempts": [(item["variant"], item["attempt"]["status"]) for item in report["attempts"]],
        "audits": [(item["family"], item["canary_hard_integrity_pass"]) for item in report["audits"]],
        "report": str(REPORTS[report["task"]]),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
