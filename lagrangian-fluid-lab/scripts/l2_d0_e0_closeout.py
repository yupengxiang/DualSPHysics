#!/usr/bin/env python3
"""Close the evidence-complete D0/E0 branches without inventing release status."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

try:
    from scripts.l2_campaign import (
        CAMPAIGN,
        LAB,
        atomic_json,
        read_json,
        require_adopted,
        update_stage,
        update_usage,
        utc_now,
    )
except ModuleNotFoundError:
    from l2_campaign import (
        CAMPAIGN,
        LAB,
        atomic_json,
        read_json,
        require_adopted,
        update_stage,
        update_usage,
        utc_now,
    )


REPORT_ROOT = CAMPAIGN / "reports"
D0_REPORT = REPORT_ROOT / "d0-production-gate.json"
D0_MARKDOWN = REPORT_ROOT / "d0-production-gate.md"
E0_REPORT = REPORT_ROOT / "e0-campaign-closeout.json"
E0_MARKDOWN = REPORT_ROOT / "e0-campaign-closeout.md"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def report_ref(name: str) -> dict:
    path = REPORT_ROOT / name
    return {"path": f"reports/{name}", "exists": path.is_file(), "sha256": sha256(path) if path.is_file() else None}


def d0() -> dict:
    state = require_adopted()
    if state["stages"]["A0"]["status"] not in {"complete", "complete_with_findings"}:
        raise RuntimeError("D0 requires A0")
    if state["stages"]["D0"]["status"] not in {"ready", "pending"}:
        raise RuntimeError("D0 already has a terminal status")
    c0 = read_json(REPORT_ROOT / "c0-family-hypotheses.json")
    c1 = read_json(REPORT_ROOT / "c1-canary.json")
    c2 = read_json(REPORT_ROOT / "c2-f3-canary.json")
    c3 = read_json(REPORT_ROOT / "c3-bounded-anchors.json")
    b2 = read_json(REPORT_ROOT / "b2-learning-baseline.json")
    manifest = read_json(CAMPAIGN / "evidence" / "f3-canonical-manifest.json")

    canary_passes = []
    for audit in c1.get("audits", []):
        if audit.get("canary_hard_integrity_pass"):
            canary_passes.append({"stage": "C1", "family": audit.get("family"), "role": "canary_only"})
    if c2.get("canary_pass"):
        canary_passes.append({"stage": "C2", "family": "F3", "role": "canary_only"})
    for audit in c3.get("audits", []):
        if audit.get("canary_hard_integrity_pass"):
            canary_passes.append({"stage": "C3", "family": audit.get("family"), "role": "canary_only"})

    # A canary is not a qualified recipe.  Only an explicit family-scoped
    # qualification record may populate this list; none exists in L2.
    new_qualified = []
    split_input_gate = bool(
        c0.get("acceptance", {}).get("priority_reference_cells_are_2x3")
        and c0.get("acceptance", {}).get("legacy_assets_not_reclassified")
        and b2.get("acceptance", {}).get("causal_input_contract_checked")
    )
    report = {
        "schema": "l2.d0.production_gate.v1",
        "stage": "D0",
        "created_at_utc": utc_now(),
        "baseline_commit": state["baseline_commit"],
        "status": "blocked",
        "decision": "blocked_runtime_gate_no_new_qualified_t1_recipe",
        "runtime_gate": {
            "required": "at least one newly qualified T1 recipe/subdomain and split/input gates",
            "new_qualified_t1_recipe_count": len(new_qualified),
            "new_qualified_t1_recipes": new_qualified,
            "split_input_gate_pass": split_input_gate,
            "canary_passes_not_promoted": canary_passes,
            "registered_legacy_f3_case_count": len(manifest.get("cases", [])),
            "registered_legacy_f3_is_new_l2_qualification": False,
        },
        "production_batch": {
            "launched": False,
            "accepted_cases": 0,
            "new_solver_attempts": 0,
            "reason": "D0 runtime gate is false; no production or pilot batch admitted",
        },
        "evidence": {
            "C0": report_ref("c0-family-hypotheses.json"),
            "C1": report_ref("c1-canary.json"),
            "C2": report_ref("c2-f3-canary.json"),
            "C3": report_ref("c3-bounded-anchors.json"),
            "B2": report_ref("b2-learning-baseline.json"),
            "F3_manifest": {"path": "evidence/f3-canonical-manifest.json", "sha256": sha256(CAMPAIGN / "evidence/f3-canonical-manifest.json")},
        },
        "authorization": {
            "public_release_authorized": False,
            "hidden_test_generation_authorized": False,
            "legacy_campaign_reopened": False,
        },
        "conclusion": "The branch is evidence-complete but cannot enter D0 production until a family-scoped L2 T1 qualification exists.",
    }
    return report


def d0_markdown(report: dict) -> str:
    gate = report["runtime_gate"]
    return "\n".join([
        "# D0 生产门禁",
        "",
        "结论：`blocked_runtime_gate_no_new_qualified_t1_recipe`。",
        "",
        f"- 新晋 T1 recipe：`{gate['new_qualified_t1_recipe_count']}`",
        f"- split/input gate：`{gate['split_input_gate_pass']}`",
        f"- canary 通过但未升级为资格：`{len(gate['canary_passes_not_promoted'])}`",
        "- 生产批次：未启动；没有把已有 F3 登记数据或 bounded canary 冒充新资格。",
        "",
    ])


def run_d0() -> None:
    report = d0()
    atomic_json(D0_REPORT, report)
    D0_MARKDOWN.write_text(d0_markdown(report))
    bytes_added = D0_REPORT.stat().st_size + D0_MARKDOWN.stat().st_size
    update_usage(new_storage_bytes=bytes_added)
    update_stage("D0", "blocked", facts={
        "report": "reports/d0-production-gate.json",
        "markdown": "reports/d0-production-gate.md",
        "decision": report["decision"],
        "new_qualified_t1_recipe_count": 0,
        "production_batch_launched": False,
    })
    print(json.dumps({"status": report["status"], "decision": report["decision"], "report": str(D0_REPORT)}, ensure_ascii=False, indent=2))


def e0() -> dict:
    state = require_adopted()
    required = ["A0", "A1", "B1", "B2", "C0", "C1", "C2", "C3", "D0"]
    if any(state["stages"][stage]["status"] not in {"complete", "complete_with_findings", "blocked"} for stage in required):
        raise RuntimeError("E0 requires all applicable branches to be terminal")
    ledger = read_json(CAMPAIGN / "ledger.json")
    usage = ledger["usage"]
    disk = shutil.disk_usage(CAMPAIGN)
    stage_outcomes = {
        stage: {
            "status": state["stages"][stage]["status"],
            "facts": state["stages"][stage].get("facts", {}),
        }
        for stage in required + ["E0"]
        if stage in state["stages"]
    }
    report = {
        "schema": "l2.e0.campaign_closeout.v1",
        "stage": "E0",
        "created_at_utc": utc_now(),
        "baseline_commit": state["baseline_commit"],
        "status": "complete_with_findings",
        "decision": "evidence_complete_internal_development_product; no_public_release",
        "terminal_predicate": {
            "all_applicable_branches_terminal": True,
            "evidence_complete": True,
            "new_t1_family_qualification_exists": False,
            "public_release_ready": False,
        },
        "stage_outcomes": stage_outcomes,
        "product_boundary": {
            "existing_f3_registered_numerical_cases": 32,
            "new_l2_qualified_families": 0,
            "bounded_families_with_evidence": ["F1", "F2", "F3", "F4", "F5"],
            "F6": "design_only_not_executed",
            "t2_macro_qualified": False,
            "t2_path_qualified": False,
            "model_physical_pass_count": 0,
            "candidate_learning_tracks": 2,
            "public_release_authorized": False,
        },
        "resource_usage": {
            **usage,
            "limits": ledger["limits"],
            "gpu_budget_fraction": usage["gpu_hours"] / ledger["limits"]["gpu_hours"],
            "cpu_budget_fraction": usage["cpu_core_hours_actual"] / ledger["limits"]["cpu_core_hours"],
            "storage_budget_fraction": usage["new_storage_bytes"] / (ledger["limits"]["new_storage_gib"] * 1024**3),
            "free_bytes_at_closeout": disk.free,
            "free_fraction_at_closeout": disk.free / disk.total,
            "minimum_free_gate_pass": disk.free >= ledger["limits"]["min_free_gib"] * 1024**3 and disk.free / disk.total >= ledger["limits"]["min_free_fraction"],
        },
        "remaining_work": [
            "qualify at least one new family-scoped T1 recipe before any D0 production batch",
            "run independent accepted/rejected cases only after split and input gates are frozen",
            "keep T2 material/path claims separate from T1 numerical evidence",
            "replace candidate-only learning diagnostics with a new registered GNS/hybrid study if model qualification is desired",
        ],
        "authorization_boundary": {
            "no_public_release": True,
            "no_hidden_test_generation": True,
            "no_vendor_writes": True,
            "legacy_l1_read_only": True,
        },
    }
    return report


def e0_markdown(report: dict) -> str:
    product = report["product_boundary"]
    resources = report["resource_usage"]
    return "\n".join([
        "# E0 L2 活动结案",
        "",
        "本地证据分支已闭合；交付物是内部 development/candidate 产品，不是公开 release。",
        "",
        "| 项目 | 结果 |",
        "|---|---:|",
        f"| 既有 F3 T1 登记案例 | {product['existing_f3_registered_numerical_cases']} |",
        f"| 新晋 T1 family | {product['new_l2_qualified_families']} |",
        f"| 学习开发轨道 | {product['candidate_learning_tracks']} |",
        f"| T2 macro/path | {product['t2_macro_qualified']}/{product['t2_path_qualified']} |",
        f"| 模型物理通过 | {product['model_physical_pass_count']} |",
        "",
        f"资源：GPU `{resources['gpu_hours']:.4f} h`，CPU `{resources['cpu_core_hours_actual']:.4f} core-h`，新增存储 `{resources['new_storage_bytes'] / 1024**3:.3f} GiB`。",
        "",
        "D0 因没有新晋 T1 recipe 保持 blocked；该阻塞是科学运行门禁，不是资源耗尽。",
        "",
    ])


def run_e0() -> None:
    report = e0()
    atomic_json(E0_REPORT, report)
    E0_MARKDOWN.write_text(e0_markdown(report))
    update_usage(new_storage_bytes=E0_REPORT.stat().st_size + E0_MARKDOWN.stat().st_size)
    update_stage("E0", "complete", facts={
        "report": "reports/e0-campaign-closeout.json",
        "markdown": "reports/e0-campaign-closeout.md",
        "decision": report["decision"],
        "evidence_complete": True,
        "public_release_ready": False,
    })
    print(json.dumps({"status": report["status"], "decision": report["decision"], "report": str(E0_REPORT)}, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("d0", "e0"))
    args = parser.parse_args()
    if args.stage == "d0":
        run_d0()
    else:
        run_e0()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
