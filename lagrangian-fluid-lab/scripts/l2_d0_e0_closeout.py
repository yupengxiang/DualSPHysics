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
    from scripts.l2_resume import (
        RECIPE_REGISTRY,
        RESUME_ROOT,
        RESUME_STATE,
        load_state as load_resume_state,
        mark_task,
        terminal_predicate,
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
    from l2_resume import (
        RECIPE_REGISTRY,
        RESUME_ROOT,
        RESUME_STATE,
        load_state as load_resume_state,
        mark_task,
        terminal_predicate,
    )


REPORT_ROOT = CAMPAIGN / "reports"
D0_REPORT = REPORT_ROOT / "d0-production-gate.json"
D0_MARKDOWN = REPORT_ROOT / "d0-production-gate.md"
D0R_REPORT = RESUME_ROOT / "d0-r-production-gate.json"
D0R_MARKDOWN = RESUME_ROOT / "d0-r-production-gate.md"
E0_REPORT = REPORT_ROOT / "e0-campaign-closeout.json"
E0_MARKDOWN = REPORT_ROOT / "e0-campaign-closeout.md"
E0R_REPORT = RESUME_ROOT / "e0-r-checkpoint.json"
E0R_MARKDOWN = RESUME_ROOT / "e0-r-checkpoint.md"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def report_ref(name: str) -> dict:
    path = REPORT_ROOT / name
    return {"path": f"reports/{name}", "exists": path.is_file(), "sha256": sha256(path) if path.is_file() else None}


def _read_optional(name: str) -> dict:
    path = REPORT_ROOT / name
    return read_json(path) if path.is_file() else {}


def _receipt_valid(receipt: dict) -> tuple[bool, str]:
    """Validate a scoped T1 receipt without accepting a canary or old report."""

    if (
        receipt.get("canary") is True
        or receipt.get("role") in {"canary", "canary_only"}
        or receipt.get("qualification_claim") == "canary_only"
    ):
        return False, "canary_not_qualification"
    scope = receipt.get("scope")
    evidence = receipt.get("evidence")
    if receipt.get("status") not in {"accepted", "qualified", "passed"}:
        return False, "status_not_accepted"
    if receipt.get("verdict") not in {None, "qualified_t1", "accepted_t1", "passed"}:
        return False, "verdict_not_t1"
    if not isinstance(scope, dict) or not scope.get("family") or not scope.get("subdomain"):
        return False, "missing_scoped_family_or_subdomain"
    if not receipt.get("recipe_id") or not isinstance(receipt.get("case_ids"), list) or not receipt["case_ids"]:
        return False, "missing_recipe_or_cases"
    if not isinstance(evidence, dict):
        return False, "missing_evidence"
    source_hashes = evidence.get("source_hashes") or receipt.get("source_hashes")
    if not isinstance(source_hashes, list) or not source_hashes or not all(isinstance(value, str) and value for value in source_hashes):
        return False, "missing_source_hashes"
    linked_hash = (
        receipt.get("source_hash")
        or receipt.get("source_sha256")
        or evidence.get("source_hash")
        or evidence.get("source_sha256")
    )
    if linked_hash is not None and linked_hash not in source_hashes:
        return False, "source_hash_mismatch"
    split_check = evidence.get("split_check", evidence.get("split_input_check"))
    input_check = evidence.get("input_check", evidence.get("input_contract"))
    if not (isinstance(split_check, dict) and split_check.get("passed") is True):
        return False, "split_check_failed"
    if not (isinstance(input_check, dict) and input_check.get("passed") is True):
        return False, "input_check_failed"
    metrics = evidence.get("spatiotemporal_metrics", evidence.get("metrics"))
    if not isinstance(metrics, dict) or not metrics:
        return False, "missing_spatiotemporal_metrics"
    expected_hash = receipt.get("expected_source_hash")
    if expected_hash is not None and expected_hash not in source_hashes:
        return False, "source_hash_mismatch"
    return True, "accepted"


def load_qualified_receipts(path: Path | None = None) -> tuple[list[dict], list[dict]]:
    """Read real recipe receipts; legacy reports and canaries are never promoted."""

    # Resolve the registry at call time.  A default argument bound to
    # ``RECIPE_REGISTRY`` at import would make a resumed/moved namespace read
    # a stale path and could silently ignore a newly written receipt.
    registry_path = Path(RECIPE_REGISTRY if path is None else path)
    if not registry_path.is_file():
        return [], [{"reason": "registry_missing", "path": str(registry_path.resolve())}]
    try:
        payload = read_json(registry_path)
    except (OSError, json.JSONDecodeError):
        return [], [{"reason": "registry_unreadable", "path": str(registry_path.resolve())}]
    if not isinstance(payload, dict):
        return [], [{"reason": "registry_not_object"}]
    raw = payload.get("receipts", payload.get("recipes", []))
    if not isinstance(raw, list):
        return [], [{"reason": "registry_receipts_not_list"}]
    accepted: list[dict] = []
    rejected: list[dict] = []
    for receipt in raw:
        if not isinstance(receipt, dict):
            rejected.append({"reason": "receipt_not_object"})
            continue
        okay, reason = _receipt_valid(receipt)
        if okay:
            accepted.append(receipt)
        else:
            rejected.append({"receipt_id": receipt.get("receipt_id"), "reason": reason})
    return accepted, rejected


def _canary_failures(*reports: dict) -> list[dict]:
    failures: list[dict] = []
    for report_index, report in enumerate(reports):
        if not isinstance(report, dict) or not report:
            continue
        label = report.get("stage") or report.get("family") or f"canary_{report_index}"
        for key in ("canary_pass", "hard_canary_pass", "canary_hard_integrity_pass"):
            if report.get(key) is False:
                failures.append({"source": label, "reason": f"{key}=false"})
        for key, value in report.items():
            if key.endswith("_canary_pass") and value is False:
                failures.append({"source": label, "reason": f"{key}=false"})
        for audit_index, audit in enumerate(report.get("audits", [])):
            if isinstance(audit, dict) and audit.get("canary_hard_integrity_pass") is False:
                failures.append({
                    "source": label,
                    "audit_index": audit_index,
                    "family": audit.get("family"),
                    "reason": "canary_hard_integrity_pass=false",
                })
    return failures


def _new_receipts(receipts: list[dict], manifest: dict) -> tuple[list[dict], list[dict]]:
    """Exclude re-registered legacy recipe IDs from the D0 new-recipe gate."""

    legacy_recipe_ids = {
        case.get("recipe_id") for case in manifest.get("cases", [])
        if isinstance(case, dict) and case.get("recipe_id")
    }
    fresh: list[dict] = []
    rejected: list[dict] = []
    for receipt in receipts:
        explicitly_new = any(receipt.get(key) is True for key in ("new_recipe", "is_new", "new_subdomain"))
        if receipt.get("recipe_id") in legacy_recipe_ids and not explicitly_new:
            rejected.append({
                "receipt_id": receipt.get("receipt_id"),
                "reason": "legacy_recipe_not_new",
            })
            continue
        fresh.append(receipt)
    return fresh, rejected


def d0(*, registry_path: Path | None = None) -> dict:
    state = require_adopted()
    if state["stages"]["A0"]["status"] not in {"complete", "complete_with_findings"}:
        raise RuntimeError("D0 requires A0")
    c0 = _read_optional("c0-family-hypotheses.json")
    c1 = _read_optional("c1-canary.json")
    c2 = _read_optional("c2-f3-canary.json")
    c3 = _read_optional("c3-bounded-anchors.json")
    b2 = _read_optional("b2-learning-baseline.json")
    manifest_path = CAMPAIGN / "evidence" / "f3-canonical-manifest.json"
    manifest = read_json(manifest_path) if manifest_path.is_file() else {}

    canary_passes = []
    for audit in c1.get("audits", []):
        if audit.get("canary_hard_integrity_pass"):
            canary_passes.append({"stage": "C1", "family": audit.get("family"), "role": "canary_only"})
    if c2.get("canary_pass"):
        canary_passes.append({"stage": "C2", "family": "F3", "role": "canary_only"})
    for audit in c3.get("audits", []):
        if audit.get("canary_hard_integrity_pass"):
            canary_passes.append({"stage": "C3", "family": audit.get("family"), "role": "canary_only"})

    active_registry = Path(RECIPE_REGISTRY if registry_path is None else registry_path)
    qualified_receipts, rejected_receipts = load_qualified_receipts(active_registry)
    new_qualified, legacy_rejections = _new_receipts(qualified_receipts, manifest)
    rejected_receipts.extend(legacy_rejections)
    canary_failures = _canary_failures(c1, c2, c3)
    canary_gate = not canary_failures
    split_input_gate = bool(
        c0.get("acceptance", {}).get("priority_reference_cells_are_2x3")
        and c0.get("acceptance", {}).get("legacy_assets_not_reclassified")
        and b2.get("acceptance", {}).get("causal_input_contract_checked")
    )
    batch_gate = bool(new_qualified and split_input_gate and canary_gate)
    qualified_families = sorted({item["scope"]["family"] for item in new_qualified})
    if not new_qualified:
        decision = "waiting_for_scoped_t1_receipt_or_split_input_gate"
    elif not split_input_gate:
        decision = "waiting_for_split_or_input_gate"
    elif not canary_gate:
        decision = "blocked_canary_failure"
    else:
        decision = "ready_scoped_internal_batch"
    report = {
        "schema": "l2.d0.production_gate.v1",
        "stage": "D0",
        "created_at_utc": utc_now(),
        "baseline_commit": state["baseline_commit"],
        "status": "ready" if batch_gate else "blocked_upstream",
        "decision": decision,
        "runtime_gate": {
            "required": "at least one newly qualified T1 recipe/subdomain and split/input gates",
            "new_qualified_t1_recipe_count": len(new_qualified),
            "new_qualified_t1_recipes": new_qualified,
            "new_qualified_family_count": len(qualified_families),
            "new_qualified_families": qualified_families,
            "rejected_receipts": rejected_receipts,
            "registry": {
                "path": str(active_registry.resolve()),
                "exists": active_registry.is_file(),
                "sha256": sha256(active_registry) if active_registry.is_file() else None,
            },
            "split_input_gate_pass": split_input_gate,
            "canary_gate_pass": canary_gate,
            "canary_failures": canary_failures,
            "canary_passes_not_promoted": canary_passes,
            "registered_legacy_f3_case_count": len(manifest.get("cases", [])),
            "registered_legacy_f3_is_new_l2_qualification": False,
        },
        "production_batch": {
            "launched": False,
            "status": "ready" if batch_gate else "not_ready",
            "accepted_cases": 8 if batch_gate else 0,
            "new_solver_attempts": 0,
            "reason": "scoped receipt, canary, and split/input gates accepted; first internal batch is ready" if batch_gate else "runtime gate is false; upstream research remains executable",
        },
        "evidence": {
            "C0": report_ref("c0-family-hypotheses.json"),
            "C1": report_ref("c1-canary.json"),
            "C2": report_ref("c2-f3-canary.json"),
            "C3": report_ref("c3-bounded-anchors.json"),
            "B2": report_ref("b2-learning-baseline.json"),
            "F3_manifest": {"path": "evidence/f3-canonical-manifest.json", "sha256": sha256(manifest_path) if manifest_path.is_file() else None},
        },
        "authorization": {
            "public_release_authorized": False,
            "hidden_test_generation_authorized": False,
            "legacy_campaign_reopened": False,
        },
        "conclusion": "Only a validated family-scoped receipt with passing split/input and canary gates can admit an internal batch; old reports and canaries remain non-promoting.",
    }
    return report


def d0_markdown(report: dict) -> str:
    gate = report["runtime_gate"]
    return "\n".join([
        "# D0 生产门禁",
        "",
        f"结论：`{report['decision']}`。",
        "",
        f"- 新晋 T1 recipe：`{gate['new_qualified_t1_recipe_count']}`",
        f"- split/input gate：`{gate['split_input_gate_pass']}`",
        f"- canary 通过但未升级为资格：`{len(gate['canary_passes_not_promoted'])}`",
        f"- 生产批次：`{report['production_batch']['status']}`，首批预留 `{report['production_batch']['accepted_cases']}` 例；没有把已有 F3 登记数据或 bounded canary 冒充新资格。",
        "",
    ])


def run_d0() -> None:
    if not RESUME_STATE.is_file():
        raise RuntimeError("historical D0 is immutable; bootstrap L2-R before running the dynamic gate")
    resume = load_resume_state()
    d0_task = next(task for task in resume["tasks"] if task["task_id"] == "D0R")
    if d0_task["status"] not in {"ready", "running"}:
        raise RuntimeError(f"D0R is not dispatchable yet: {d0_task['status']}")
    report = d0()
    atomic_json(D0R_REPORT, report)
    D0R_MARKDOWN.write_text(d0_markdown(report))
    mark_task("D0R", "complete_with_findings", artifacts=[
        "resume-c6b28c8/d0-r-production-gate.json",
        "resume-c6b28c8/d0-r-production-gate.md",
    ], next_action="launch_scoped_internal_batch" if report["production_batch"]["status"] == "ready" else "continue_upstream_research")
    print(json.dumps({"status": report["status"], "decision": report["decision"], "report": str(D0R_REPORT)}, ensure_ascii=False, indent=2))


def e0() -> dict:
    state = require_adopted()
    if not RESUME_STATE.is_file():
        raise RuntimeError("L2-R is not bootstrapped; historical E0 cannot be used as a terminal predicate")
    resume = load_resume_state()
    predicate = terminal_predicate(resume)
    ledger = read_json(CAMPAIGN / "ledger.json")
    usage = ledger["usage"]
    disk = shutil.disk_usage(CAMPAIGN)
    task_outcomes = {task["task_id"]: {key: task.get(key) for key in (
        "status", "implementation_status", "execution_status", "acceptance_status",
        "evidence_origin", "requires", "artifacts", "next_action", "blocker",
    )} for task in resume["tasks"]}
    report = {
        "schema": "l2r.e0.checkpoint.v1",
        "stage": "E0R",
        "created_at_utc": utc_now(),
        "baseline_commit": resume["baseline_commit"],
        "status": "complete_with_findings" if predicate["can_finalize"] else "checkpoint",
        "decision": "terminal_predicate_satisfied" if predicate["can_finalize"] else "continue_l2r_ready_work",
        "terminal_predicate": {
            **predicate,
            "public_release_ready": False,
        },
        "task_outcomes": task_outcomes,
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
        "remaining_work": predicate["unfinished_tasks"] + predicate["ready_or_running_tasks"],
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
        "# E0-R L2 连续执行 checkpoint",
        "",
        "该文件是产物驱动 checkpoint；只有机器化 terminal predicate 满足时才允许活动结案。",
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
        f"terminal predicate：`{report['terminal_predicate']['can_finalize']}`；剩余任务：`{len(report['remaining_work'])}`。",
        "",
    ])


def run_e0() -> None:
    if not RESUME_STATE.is_file():
        raise RuntimeError("historical E0 is immutable; bootstrap L2-R before writing a checkpoint")
    resume = load_resume_state()
    e0_task = next(task for task in resume["tasks"] if task["task_id"] == "E0R")
    if e0_task["status"] not in {"ready", "running", "complete_with_findings"}:
        raise RuntimeError(f"E0R is not dispatchable yet: {e0_task['status']}")
    # E0R itself is a required output.  Write a machine-checked checkpoint
    # before changing the task to terminal.  This keeps a report-generation
    # exception from leaving a terminal task backed only by a placeholder.
    RESUME_ROOT.mkdir(parents=True, exist_ok=True)
    report = e0()
    atomic_json(E0R_REPORT, report)
    E0R_MARKDOWN.write_text(e0_markdown(report))
    mark_task("E0R", "complete_with_findings", artifacts=[
        "resume-c6b28c8/e0-r-checkpoint.json",
        "resume-c6b28c8/e0-r-checkpoint.md",
    ], next_action="continue_ready_work")
    # Recompute after E0R is terminal so the persisted report describes the
    # actual final predicate rather than the pre-E0 checkpoint state.
    report = e0()
    atomic_json(E0R_REPORT, report)
    E0R_MARKDOWN.write_text(e0_markdown(report))
    print(json.dumps({"status": report["status"], "decision": report["decision"], "report": str(E0R_REPORT)}, ensure_ascii=False, indent=2))


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
