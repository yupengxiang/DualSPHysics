#!/usr/bin/env python3
"""Run one real 3-D F3 off-axis connected-passage canary for C2."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import xml.etree.ElementTree as ET

try:
    from scripts import l2_c1_canary as base
    from scripts.l2_campaign import (
        CAMPAIGN,
        LAB,
        atomic_json,
        repo_relative,
        require_adopted,
        sha256_file,
        update_stage,
        update_usage,
        utc_now,
    )
except ModuleNotFoundError:  # direct invocation from scripts/
    import l2_c1_canary as base
    from l2_campaign import (
        CAMPAIGN,
        LAB,
        atomic_json,
        repo_relative,
        require_adopted,
        sha256_file,
        update_stage,
        update_usage,
        utc_now,
    )


C2_ROOT = CAMPAIGN / "c2-canary"
ORIGINAL_DEFINITION = LAB / "cases/F3/F3_baffled_slosh/F3_baffled_slosh_Def.xml"
TEMPLATE_DEFINITION = C2_ROOT / "cases" / "L2_C2_F3_offaxis_baffle_nominal_Template.xml"
REPORT_PATH = CAMPAIGN / "reports" / "c2-f3-canary.json"


def make_offaxis_template() -> Path:
    TEMPLATE_DEFINITION.parent.mkdir(parents=True, exist_ok=True)
    tree = ET.parse(ORIGINAL_DEFINITION)
    root = tree.getroot()
    mainlist = root.find(".//geometry/commands/mainlist")
    if mainlist is None:
        raise RuntimeError("F3 template has no geometry mainlist")
    drawboxes = mainlist.findall("drawbox")
    if len(drawboxes) < 4:
        raise RuntimeError("F3 baffled template geometry changed; expected four boxes")
    # The third and fourth boxes are the void and boundary faces of the old
    # full-width baffle.  Move them to the lower side, leaving a connected
    # upper passage instead of turning the case into an AABB proxy.
    for box in drawboxes[2:4]:
        point = box.find("point")
        size = box.find("size")
        if point is None or size is None:
            raise RuntimeError("F3 baffle box is missing point/size")
        point.set("y", "0.04")
        size.set("y", "0.10")
    ET.indent(tree, space="    ")
    tree.write(TEMPLATE_DEFINITION, encoding="utf-8", xml_declaration=True)
    return TEMPLATE_DEFINITION


def config(gpu: int) -> dict:
    template = make_offaxis_template()
    return {
        "case_id": "L2_C2_F3_offaxis_baffle_nominal",
        "family": "F3",
        "mechanism": "off-axis-baffle-connected-passage-transverse-exchange",
        "source_definition": template,
        "original_definition": ORIGINAL_DEFINITION,
        "recipe_id": "L2_F3_C2_offaxis_connected_passage_dbc_native_v1_dp0p0075",
        "physical_case_id": "physical_L2_F3_offaxis_baffle_nominal_v1",
        "lineage_group_id": "lineage_L2_F3_offaxis_baffle_nominal_v1",
        "paired_background_id": "paired_L2_F3_offaxis_baffle_v1",
        "view_id": "world_fluid_particle_v1",
        "resolution_m": 0.0075,
        "time_max_s": 0.9,
        "time_out_s": 0.02,
        "gpu": gpu,
        "wall_bounds": {"xmin": 0.0, "xmax": 1.2, "ymin": 0.0, "ymax": 0.4, "zmin": 0.0},
        "control_semantics": "known initial x impulse; no future fluid state",
    }


def run(gpu: int) -> dict:
    state = require_adopted()
    if state["stages"]["C0"]["status"] not in {"complete", "complete_with_findings"}:
        raise RuntimeError("C2 requires C0 to be complete")
    if state["stages"]["C2"]["status"] not in {"ready", "pending"}:
        raise RuntimeError("C2 already has a terminal status; refusing an untracked rerun")
    # Reuse the tested C1 prepare/run/audit primitives, but bind every write
    # to the C2 namespace before invoking them.
    base.CASE_ROOT = C2_ROOT / "cases"
    base.ARTIFACT_ROOT = C2_ROOT / "artifacts"
    base.DATA_ROOT = C2_ROOT / "data"
    base.RUN_ROOT = CAMPAIGN / "runs"
    before_bytes = sum(base.directory_bytes(path) for path in (C2_ROOT, base.RUN_ROOT / "L2_C2_F3_offaxis_baffle_nominal"))
    started_wall = time.perf_counter()
    child_before = base.child_cpu_seconds()
    item = config(gpu)
    prepared = base.prepare_case(item)
    item["original_definition_sha256"] = sha256_file(ORIGINAL_DEFINITION)[0]
    allowed = base.inventory_allowlist()
    attempt = base.run_case(item, allowed)
    audit = None
    stop_reason = None
    if attempt["status"] == "completed":
        audit = base.audit_case(item, attempt)
        if not audit["canary_hard_integrity_pass"]:
            stop_reason = "canary completed but failed a hard structural/source gate"
    else:
        stop_reason = "solver attempt failed; no derived HDF5 was promoted"
    child_after = base.child_cpu_seconds()
    used_bytes = sum(base.directory_bytes(path) for path in (C2_ROOT, base.RUN_ROOT / "L2_C2_F3_offaxis_baffle_nominal"))
    report = {
        "schema": "l2.c2.f3_geometry_control_canary.v1",
        "stage": "C2",
        "created_at_utc": utc_now(),
        "baseline_commit": state["baseline_commit"],
        "status": "complete" if audit and audit["canary_hard_integrity_pass"] else "complete_with_findings",
        "decision": "canary_integrity_passed; F3 extension qualification not yet claimed" if audit and audit["canary_hard_integrity_pass"] else "bounded_canary_finding; F3 extension not qualified",
        "stop_reason": stop_reason,
        "design": {
            "background": "off-axis baffle connected passage",
            "lagrangian_tasks": ["transverse exchange", "repeated crossing", "residence"],
            "connected_passage_semantics": "baffle occupies y=0.04..0.14 while fluid domain continues to y=0.40; upper passage is part of the geometry",
            "reference_resolution_m": item["resolution_m"],
            "paired_background_reserved": "multi-axis prescribed drive; not executed by this canary",
        },
        "input": {
            "original_definition": repo_relative(ORIGINAL_DEFINITION),
            "original_definition_sha256": item["original_definition_sha256"],
            "template_definition": repo_relative(TEMPLATE_DEFINITION),
            "template_definition_sha256": item["source_definition_sha256"],
            "generated_xml": repo_relative(item["generated_xml"]),
            "generated_xml_sha256": item["generated_xml_sha256"],
            "recipe_id": item["recipe_id"],
            "solver_binary_sha256": sha256_file(base.SOLVER)[0],
        },
        "attempt": attempt,
        "audit": audit,
        "qualification_claim": "none; canary structural evidence only",
        "T2_macro": "not_assessed",
        "T2_path": "not_assessed",
        "resource_observation": {
            "controller_wall_seconds": time.perf_counter() - started_wall,
            "solver_wall_seconds": attempt.get("elapsed_seconds", 0.0),
            "child_cpu_seconds": max(0.0, child_after - child_before),
            "gpu_hours": attempt.get("elapsed_seconds", 0.0) / 3600.0,
            "cpu_core_hours_actual": max(0.0, child_after - child_before) / 3600.0,
            "cpu_core_hours_conservative": attempt.get("elapsed_seconds", 0.0) / 3600.0,
            "qualification_solver_attempts": 1,
            "new_storage_bytes": max(0, used_bytes - before_bytes),
        },
        "acceptance": {
            "offaxis_geometry_template_recorded": True,
            "nominal_spacing_used": item["resolution_m"] == 0.0075,
            "solver_attempt_recorded": True,
            "hard_canary_pass": bool(audit and audit["canary_hard_integrity_pass"]),
            "no_family_qualification_claim": True,
            "T2_axes_separate": True,
        },
    }
    atomic_json(REPORT_PATH, report)
    report["resource_observation"]["new_storage_bytes"] += REPORT_PATH.stat().st_size
    atomic_json(REPORT_PATH, report)
    update_usage(
        gpu_hours=report["resource_observation"]["gpu_hours"],
        cpu_core_hours_actual=report["resource_observation"]["cpu_core_hours_actual"],
        cpu_core_hours_conservative=report["resource_observation"]["cpu_core_hours_conservative"],
        qualification_solver_attempts=1,
        new_storage_bytes=report["resource_observation"]["new_storage_bytes"],
    )
    update_stage("C2", "complete", facts={
        "report": "reports/c2-f3-canary.json",
        "decision": report["decision"],
        "canary_pass": bool(audit and audit["canary_hard_integrity_pass"]),
    })
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gpu", type=int, default=6, help="allowlisted physical GPU index")
    args = parser.parse_args()
    report = run(args.gpu)
    print(json.dumps({
        "status": report["status"],
        "decision": report["decision"],
        "attempt_status": report["attempt"]["status"],
        "canary_pass": report["acceptance"]["hard_canary_pass"],
        "report": str(REPORT_PATH),
    }, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
