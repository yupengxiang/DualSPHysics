#!/usr/bin/env python3
"""Run bounded F4/F5 anchor canaries; F6 remains design-only in C3."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

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
except ModuleNotFoundError:
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


C3_ROOT = CAMPAIGN / "c3-canary"
REPORT_PATH = CAMPAIGN / "reports" / "c3-bounded-anchors.json"


def configs(gpus: list[int]) -> list[dict]:
    common = [
        ("F4", "L2_C3_F4_drop_pool_nominal", "drop-pool-impact-reentry",
         LAB / "cases/F4/F4_drop_onto_pool/F4_drop_onto_pool_Def.xml",
         "L2_F4_C3_drop_pool_dbc_v1_dp0p0075",
         {"xmin": 0.0, "xmax": 1.2, "ymin": 0.0, "ymax": 0.4, "zmin": 0.0}),
        ("F5", "L2_C3_F5_low_weir_nominal", "runup-overtop-return",
         LAB / "cases/F5/F5_low_weir/F5_low_weir_Def.xml",
         "L2_F5_C3_low_weir_dbc_v1_dp0p0075",
         {"xmin": 0.0, "xmax": 1.2, "ymin": 0.0, "ymax": 0.4, "zmin": 0.0}),
    ]
    result = []
    for index, (family, case_id, mechanism, source, recipe, bounds) in enumerate(common):
        result.append({
            "case_id": case_id,
            "family": family,
            "mechanism": mechanism,
            "source_definition": source,
            "recipe_id": recipe,
            "physical_case_id": f"physical_{case_id}",
            "lineage_group_id": f"lineage_{case_id}",
            "paired_background_id": f"paired_{family}_bounded_anchor_v1",
            "view_id": "world_fluid_particle_v1",
            "resolution_m": 0.0075,
            "time_max_s": 0.6 if family == "F4" else 0.75,
            "time_out_s": 0.02,
            "gpu": gpus[index],
            "wall_bounds": bounds,
            "control_semantics": "known initial condition and gravity; no future fluid state",
        })
    return result


def run(gpus: list[int]) -> dict:
    state = require_adopted()
    if state["stages"]["C0"]["status"] not in {"complete", "complete_with_findings"}:
        raise RuntimeError("C3 requires C0 to be complete")
    if state["stages"]["C3"]["status"] not in {"ready", "pending"}:
        raise RuntimeError("C3 already has a terminal status; refusing an untracked rerun")
    if len(gpus) < 2:
        raise ValueError("C3 needs two allowlisted physical GPU indices")
    base.CASE_ROOT = C3_ROOT / "cases"
    base.ARTIFACT_ROOT = C3_ROOT / "artifacts"
    base.DATA_ROOT = C3_ROOT / "data"
    base.RUN_ROOT = CAMPAIGN / "runs"
    before_bytes = sum(base.directory_bytes(path) for path in (C3_ROOT, base.RUN_ROOT / "L2_C3_F4_drop_pool_nominal", base.RUN_ROOT / "L2_C3_F5_low_weir_nominal"))
    started_wall = time.perf_counter()
    child_before = base.child_cpu_seconds()
    allowed = base.inventory_allowlist()
    attempts = []
    audits = []
    stop_reason = None
    prepared = []
    for item in configs(gpus):
        prepared.append(base.prepare_case(item))
    for item in prepared:
        attempt = base.run_case(item, allowed)
        attempt_record = {
            "case_id": item["case_id"],
            "family": item["family"],
            "attempt": attempt,
            "definition": repo_relative(item["definition"]),
            "definition_sha256": item["definition_sha256"],
            "generated_xml": repo_relative(item["generated_xml"]),
            "generated_xml_sha256": item["generated_xml_sha256"],
            "recipe_id": item["recipe_id"],
        }
        attempts.append(attempt_record)
        if attempt["status"] != "completed":
            stop_reason = "first bounded anchor solver attempt failed; cohort stopped"
            break
        audit = base.audit_case(item, attempt)
        audits.append(audit)
        if not audit["canary_hard_integrity_pass"]:
            stop_reason = "first bounded anchor failed hard structural/source gate; cohort stopped"
            break
    child_after = base.child_cpu_seconds()
    used_bytes = sum(base.directory_bytes(path) for path in (C3_ROOT, base.RUN_ROOT / "L2_C3_F4_drop_pool_nominal", base.RUN_ROOT / "L2_C3_F5_low_weir_nominal"))
    report = {
        "schema": "l2.c3.bounded_anchors.v1",
        "stage": "C3",
        "created_at_utc": utc_now(),
        "baseline_commit": state["baseline_commit"],
        "status": "complete_with_findings",
        "decision": "bounded_capability_map_with_no_qualification_claim",
        "stop_reason": stop_reason,
        "scope": {
            "F4": "finite jet/liquid-column deflection anchor",
            "F5": "single run-up/overtopping anchor",
            "F6": "design-only; no solver attempt in this bounded tranche",
            "resolution_m": 0.0075,
            "attempt_cap_policy": "at most four qualification solver attempts per bounded family; this run uses at most one per F4/F5",
        },
        "prepared_cases": [
            {
                "case_id": item["case_id"],
                "family": item["family"],
                "recipe_id": item["recipe_id"],
                "source_definition": repo_relative(item["source_definition"]),
                "source_definition_sha256": item["source_definition_sha256"],
                "definition": repo_relative(item["definition"]),
                "definition_sha256": item["definition_sha256"],
                "resolution_m": item["resolution_m"],
            }
            for item in prepared
        ],
        "attempts": attempts,
        "audits": audits,
        "F6_status": "not_executed_design_only",
        "qualification_claim": "none; bounded canary evidence only",
        "T2_macro": "not_assessed",
        "T2_path": "not_assessed",
        "acceptance": {
            "F4_or_F5_attempt_recorded": bool(attempts),
            "F6_not_silently_qualified": True,
            "no_family_qualification_claim": True,
            "attempt_caps_respected": len(attempts) <= 2,
        },
        "resource_observation": {
            "controller_wall_seconds": time.perf_counter() - started_wall,
            "solver_wall_seconds_sum": sum(item["attempt"].get("elapsed_seconds", 0.0) for item in attempts),
            "child_cpu_seconds": max(0.0, child_after - child_before),
            "gpu_hours": sum(item["attempt"].get("elapsed_seconds", 0.0) for item in attempts) / 3600.0,
            "cpu_core_hours_actual": max(0.0, child_after - child_before) / 3600.0,
            "cpu_core_hours_conservative": sum(item["attempt"].get("elapsed_seconds", 0.0) for item in attempts) / 3600.0,
            "qualification_solver_attempts": len(attempts),
            "new_storage_bytes": max(0, used_bytes - before_bytes),
        },
    }
    atomic_json(REPORT_PATH, report)
    report["resource_observation"]["new_storage_bytes"] += REPORT_PATH.stat().st_size
    atomic_json(REPORT_PATH, report)
    update_usage(
        gpu_hours=report["resource_observation"]["gpu_hours"],
        cpu_core_hours_actual=report["resource_observation"]["cpu_core_hours_actual"],
        cpu_core_hours_conservative=report["resource_observation"]["cpu_core_hours_conservative"],
        qualification_solver_attempts=report["resource_observation"]["qualification_solver_attempts"],
        new_storage_bytes=report["resource_observation"]["new_storage_bytes"],
    )
    update_stage("C3", "complete", facts={
        "report": "reports/c3-bounded-anchors.json",
        "decision": report["decision"],
        "attempt_count": len(attempts),
        "F6_status": report["F6_status"],
    })
    return report


def repair_audit_and_continue(gpus: list[int]) -> dict:
    """Re-audit the existing F4 result after an audit-rule correction.

    The original C3 controller stopped after a false-negative semantic check.
    This path never reruns F4: it replaces only that audit record, and admits
    the prepared F5 canary only if the corrected F4 hard gate passes.
    """

    state = require_adopted()
    if state["stages"]["C3"]["status"] != "complete":
        raise RuntimeError("C3 repair requires the original bounded run to be complete")
    if not REPORT_PATH.is_file():
        raise FileNotFoundError(f"missing prior C3 report: {REPORT_PATH}")
    prior = json.loads(REPORT_PATH.read_text())
    if len(prior.get("attempts", [])) != 1 or prior["attempts"][0].get("family") != "F4":
        raise RuntimeError("repair path expects exactly one prior F4 attempt")
    if len(gpus) < 2:
        raise ValueError("C3 repair needs two allowlisted physical GPU indices")

    base.CASE_ROOT = C3_ROOT / "cases"
    base.ARTIFACT_ROOT = C3_ROOT / "artifacts"
    base.DATA_ROOT = C3_ROOT / "data"
    base.RUN_ROOT = CAMPAIGN / "runs"
    before_bytes = sum(
        base.directory_bytes(path)
        for path in (
            C3_ROOT,
            base.RUN_ROOT / "L2_C3_F4_drop_pool_nominal",
            base.RUN_ROOT / "L2_C3_F5_low_weir_nominal",
        )
    )
    started_wall = time.perf_counter()
    child_before = base.child_cpu_seconds()
    prepared = []
    for item in configs(gpus):
        prepared.append(base.prepare_case(item))

    corrected_f4 = base.audit_case(prepared[0], prior["attempts"][0]["attempt"])
    attempts = list(prior["attempts"])
    audits = [corrected_f4]
    stop_reason = None
    if not corrected_f4["canary_hard_integrity_pass"]:
        stop_reason = "corrected F4 audit still failed; F5 remained gated"
    else:
        allowed = base.inventory_allowlist()
        item = prepared[1]
        attempt = base.run_case(item, allowed)
        attempt_record = {
            "case_id": item["case_id"],
            "family": item["family"],
            "attempt": attempt,
            "definition": repo_relative(item["definition"]),
            "definition_sha256": item["definition_sha256"],
            "generated_xml": repo_relative(item["generated_xml"]),
            "generated_xml_sha256": item["generated_xml_sha256"],
            "recipe_id": item["recipe_id"],
        }
        attempts.append(attempt_record)
        if attempt["status"] != "completed":
            stop_reason = "F5 bounded anchor solver attempt failed; cohort stopped"
        else:
            audit = base.audit_case(item, attempt)
            audits.append(audit)
            if not audit["canary_hard_integrity_pass"]:
                stop_reason = "F5 bounded anchor failed hard structural/source gate"
            else:
                stop_reason = "F4 audit repaired and F5 bounded canary completed; no qualification claim"

    child_after = base.child_cpu_seconds()
    used_bytes = sum(
        base.directory_bytes(path)
        for path in (
            C3_ROOT,
            base.RUN_ROOT / "L2_C3_F4_drop_pool_nominal",
            base.RUN_ROOT / "L2_C3_F5_low_weir_nominal",
        )
    )
    prior_observation = prior.get("resource_observation", {})
    new_attempts = attempts[len(prior["attempts"]):]
    followup_child_cpu_seconds = max(0.0, child_after - child_before)
    new_storage_bytes = max(0, used_bytes - before_bytes)
    report = dict(prior)
    report["updated_at_utc"] = utc_now()
    report["stop_reason"] = stop_reason
    report["attempts"] = attempts
    report["audits"] = audits
    report["reassessment"] = {
        "reason": "fixed C3 control-semantics audit predicate",
        "prior_f4_solver_rerun": False,
        "corrected_f4_hard_integrity_pass": corrected_f4["canary_hard_integrity_pass"],
        "f5_admitted_after_corrected_f4": bool(new_attempts),
    }
    report["acceptance"] = {
        "F4_or_F5_attempt_recorded": bool(attempts),
        "F6_not_silently_qualified": True,
        "no_family_qualification_claim": True,
        "attempt_caps_respected": len(attempts) <= 2,
    }
    report["resource_observation"] = {
        "controller_wall_seconds": prior_observation.get("controller_wall_seconds", 0.0) + (time.perf_counter() - started_wall),
        "solver_wall_seconds_sum": prior_observation.get("solver_wall_seconds_sum", 0.0) + sum(item["attempt"].get("elapsed_seconds", 0.0) for item in new_attempts),
        "child_cpu_seconds": prior_observation.get("child_cpu_seconds", 0.0) + followup_child_cpu_seconds,
        "gpu_hours": prior_observation.get("gpu_hours", 0.0) + sum(item["attempt"].get("elapsed_seconds", 0.0) for item in new_attempts) / 3600.0,
        "cpu_core_hours_actual": prior_observation.get("cpu_core_hours_actual", 0.0) + followup_child_cpu_seconds / 3600.0,
        "cpu_core_hours_conservative": prior_observation.get("cpu_core_hours_conservative", 0.0) + sum(item["attempt"].get("elapsed_seconds", 0.0) for item in new_attempts) / 3600.0,
        "qualification_solver_attempts": len(attempts),
        "new_storage_bytes": prior_observation.get("new_storage_bytes", 0) + new_storage_bytes,
    }
    atomic_json(REPORT_PATH, report)
    report["resource_observation"]["new_storage_bytes"] += REPORT_PATH.stat().st_size
    atomic_json(REPORT_PATH, report)
    update_usage(
        gpu_hours=sum(item["attempt"].get("elapsed_seconds", 0.0) for item in new_attempts) / 3600.0,
        cpu_core_hours_actual=followup_child_cpu_seconds / 3600.0,
        cpu_core_hours_conservative=sum(item["attempt"].get("elapsed_seconds", 0.0) for item in new_attempts) / 3600.0,
        qualification_solver_attempts=len(new_attempts),
        new_storage_bytes=new_storage_bytes + REPORT_PATH.stat().st_size,
    )
    update_stage("C3", "complete", facts={
        "report": "reports/c3-bounded-anchors.json",
        "decision": report["decision"],
        "attempt_count": len(attempts),
        "F6_status": report["F6_status"],
        "audit_repaired": True,
    })
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gpus", default="4,5", help="allowlisted physical GPU indices for F4,F5")
    parser.add_argument(
        "--repair-and-continue",
        action="store_true",
        help="re-audit the existing F4 result after an audit-rule fix, then admit F5 if F4 passes",
    )
    args = parser.parse_args()
    gpus = [int(value.strip()) for value in args.gpus.split(",") if value.strip()]
    report = repair_audit_and_continue(gpus) if args.repair_and_continue else run(gpus)
    print(json.dumps({
        "status": report["status"],
        "decision": report["decision"],
        "attempts": [(item["family"], item["attempt"]["status"]) for item in report["attempts"]],
        "report": str(REPORT_PATH),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
