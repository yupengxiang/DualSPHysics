#!/usr/bin/env python3
"""Artifact-driven continuation state for the L2-R review resume.

The original L2 ``state.json`` and E0 report are historical evidence.  This
module creates a separate resume namespace so a new controller cannot silently
rewrite that checkpoint or infer completion from old stage labels.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

try:
    from scripts.l2_campaign import (
        CAMPAIGN,
        LAB,
        REPO,
        atomic_json,
        git_head,
        read_json,
        require_adopted,
        sha256_file,
        external_blocker_error,
        utc_now,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from l2_campaign import (
        CAMPAIGN,
        LAB,
        REPO,
        atomic_json,
        git_head,
        read_json,
        require_adopted,
        sha256_file,
        external_blocker_error,
        utc_now,
    )


RESUME_ID = "L2R_c6b28c8"
RESUME_ROOT = CAMPAIGN / "resume-c6b28c8"
RESUME_STATE = RESUME_ROOT / "state.json"
RESUME_EVENTS = RESUME_ROOT / "events.json"
RECIPE_REGISTRY = RESUME_ROOT / "recipe-registry.json"
R0_VERIFICATION = RESUME_ROOT / "r0-controller-verification.json"
TERMINAL_STATUSES = frozenset({"complete", "complete_with_findings", "blocked_external"})
EVIDENCE_TERMINAL_STATUSES = frozenset({"complete", "complete_with_findings"})

TASK_DEFINITIONS = (
    ("R0", [], ["controller_negative_closeout_tests", "artifact_registry_reader", "resume_event", "reconciled_ledger"]),
    ("R1", ["R0"], ["five_reaudited_canaries", "native_loss_join", "mask_and_finite_wall_regression"]),
    ("R2", ["R0", "R1"], ["current_f3_contract", "actual_oracle_runs", "legacy_reuse_manifest"]),
    ("F3R", ["R0", "R1"], ["qualified_recipe_or_bounded_rejection", "background_resolution_coverage", "new_control_geometry_evidence"]),
    ("F4R", ["R0", "R1"], ["drop_pool_reference_matrix", "event_and_budget_report", "qualified_scope_or_bounded_rejection"]),
    ("F1R", ["R0", "R1"], ["native_failure_hypotheses", "implemented_repair_and_alternative", "two_background_reference_evidence_or_blocker"]),
    ("F2R", ["R0", "R1"], ["static_and_moving_cup_checks", "motion_and_capture_geometry", "two_background_reference_evidence_or_blocker"]),
    ("B1R", ["R0", "R1"], ["changed_material_execution_path", "profiling_and_restart_comparison", "new_material_runs", "separate_macro_path_verdicts"]),
    ("B2R", ["R0", "R2"], ["new_graph_model", "raw_hybrid_controlled_study", "new_training_attempt_records", "full_failure_denominator"]),
    ("C3R", ["R0", "R1"], ["f5_loss_root_cause", "bounded_f5_f6_actual_evidence_or_specific_external_blocker"]),
    ("D0R", ["R0", "R1"], ["dynamic_scope_gate", "new_independent_batches_if_qualified", "all_attempts_and_duplicates_manifest"]),
    ("E0R", ["R0"], ["coverage_fact_table", "local_import_bundle", "end_to_end_replay", "machine_checked_terminal_predicate"]),
)


def _file_ref(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "exists": path.is_file(),
        "sha256": sha256_file(path)[0] if path.is_file() else None,
    }


def _task_records() -> list[dict[str, Any]]:
    records = []
    for index, (task_id, requires, outputs) in enumerate(TASK_DEFINITIONS):
        records.append({
            "task_id": task_id,
            "requirement_id": task_id,
            "implementation_status": "ready" if task_id == "R0" else "pending",
            "execution_status": "ready" if task_id == "R0" else "pending",
            "acceptance_status": "pending",
            "status": "ready" if task_id == "R0" else "pending",
            "evidence_origin": "new_execution_required",
            "requires": list(requires),
            "required_outputs": list(outputs),
            "artifacts": [],
            "next_action": "implement_and_test" if task_id == "R0" else "wait_for_dependencies",
            "budget_reservation": {},
            "blocker": None,
            "ordinal": index,
        })
    return records


def _terminal_evidence_error(task: dict[str, Any]) -> str | None:
    """Validate the evidence contract for a terminal L2-R task.

    A bounded finding is terminal only with concrete artifact references.  An
    external block is a different contract: it needs a structured blocker
    statement with evidence and release conditions, and cannot be represented
    by an arbitrary non-empty value.
    """

    status = task.get("status")
    if status in EVIDENCE_TERMINAL_STATUSES:
        if task.get("blocker") is not None:
            return "complete_status_cannot_carry_external_blocker"
        artifacts = task.get("artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            return "complete_status_requires_artifacts"
        if not all(isinstance(path, str) and path for path in artifacts):
            return "complete_status_has_invalid_artifact_reference"
    elif status == "blocked_external":
        error = external_blocker_error(task.get("blocker"))
        if error:
            return f"blocked_external:{error}"
    return None


def _artifact_payloads(task: dict[str, Any]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for reference in task.get("artifacts", []):
        path = _artifact_path(reference)
        if path.suffix != ".json" or not path.is_file():
            continue
        try:
            payload = read_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            payloads.append(payload)
    return payloads


def _task_specific_terminal_error(task: dict[str, Any]) -> str | None:
    """Keep known false-terminal shortcuts out of the generic predicate."""

    if task.get("status") not in EVIDENCE_TERMINAL_STATUSES:
        return None
    if task.get("task_id") != "B2R":
        return None
    # B2R's preparation contract explicitly records zero launches.  It is not
    # enough to make that preparation file terminal; at least one persisted
    # training-attempt record must exist, including a failed attempt.
    for payload in _artifact_payloads(task):
        schema = payload.get("schema")
        if schema == "l2r.b2r.training_attempt.v1" and payload.get("execution_attempt_id"):
            return None
        if schema == "l2r.b2r.bounded_attempt_report.v1" and payload.get("execution_attempt_id"):
            return None
    return "B2R_requires_a_new_training_attempt_record"


def _task_is_terminal(task: dict[str, Any], *, require_artifacts: bool = False) -> bool:
    if task.get("status") not in TERMINAL_STATUSES:
        return False
    if _terminal_evidence_error(task) or _task_specific_terminal_error(task):
        return False
    if require_artifacts and task.get("status") in EVIDENCE_TERMINAL_STATUSES:
        return all(_artifact_exists(path) for path in task.get("artifacts", []))
    return True


def _refresh_ready(state: dict[str, Any]) -> dict[str, Any]:
    by_id = {task["task_id"]: task for task in state["tasks"]}
    for task in state["tasks"]:
        if task["status"] in TERMINAL_STATUSES or task["status"] == "running":
            continue
        dependencies_terminal = all(
            _task_is_terminal(by_id[requirement], require_artifacts=True)
            for requirement in task["requires"]
        )
        if dependencies_terminal and task["status"] in {"pending", "blocked_upstream"}:
            task["status"] = "ready"
            task["execution_status"] = "ready"
            task["next_action"] = "execute"
        elif not dependencies_terminal and task["status"] not in {"pending", "blocked_upstream", "blocked"}:
            task["status"] = "blocked_upstream"
            task["execution_status"] = "blocked_upstream"
            task["next_action"] = "wait_for_dependencies"
    return state


def reconcile_ledger() -> dict[str, Any]:
    """Count immutable attempt UUIDs without changing historical usage."""

    old_state = read_json(CAMPAIGN / "state.json")
    ledger = read_json(CAMPAIGN / "ledger.json")
    attempts: dict[str, dict[str, Any]] = {}
    duplicate_ids: list[str] = []
    for path in CAMPAIGN.rglob("attempt.json"):
        if RESUME_ROOT in path.parents:
            continue
        try:
            payload = read_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        attempt_id = payload.get("attempt_id")
        if not attempt_id:
            continue
        if attempt_id in attempts:
            duplicate_ids.append(str(attempt_id))
            continue
        attempts[str(attempt_id)] = {
            "path": str(path.resolve()),
            "status": payload.get("status"),
            "resource_category": payload.get("resource_category"),
            "case_id": payload.get("case_id"),
        }
    counts = Counter(
        (record.get("resource_category") or "unknown", record.get("status") or "unknown")
        for record in attempts.values()
    )
    return {
        "schema": "l2r.reconciled.ledger.v1",
        "created_at_utc": utc_now(),
        "historical_usage_snapshot": dict(old_state.get("resource_usage", ledger.get("usage", {}))),
        "attempt_uuid_count": len(attempts),
        "duplicate_attempt_uuid_count": len(duplicate_ids),
        "duplicate_attempt_uuids": sorted(set(duplicate_ids)),
        "attempt_counts_by_category_and_status": {
            f"{category}:{status}": count for (category, status), count in sorted(counts.items())
        },
        "attempts": attempts,
        "policy": "deduplicate by immutable attempt_id; do not reduce historical usage or count unknowns as free budget",
    }


def bootstrap() -> dict[str, Any]:
    """Create the separate resume namespace and preserve old E0 by hash."""

    old_state = require_adopted()
    RESUME_ROOT.mkdir(parents=True, exist_ok=True)
    old_e0 = CAMPAIGN / "reports" / "e0-campaign-closeout.json"
    state = {
        "schema": "l2r.resume.state.v1",
        "resume_id": RESUME_ID,
        "campaign_id": old_state.get("campaign_id"),
        "baseline_commit": "c6b28c86704e1cc62fc02aa27413855ef5a9a502",
        "current_commit": git_head(),
        "created_at_utc": utc_now(),
        "deadline_utc": "2026-09-23T16:29:26.402244+00:00",
        "old_state": _file_ref(CAMPAIGN / "state.json"),
        "old_e0_checkpoint": _file_ref(old_e0),
        "public_release_authorized": False,
        "hidden_test_generation_authorized": False,
        "parent_limits": old_state.get("limits", {}),
        "observed_usage": old_state.get("resource_usage", {}),
        "tasks": _task_records(),
        "terminal_predicate": {
            "can_finalize": False,
            "reason": "resume_bootstrapped; mandatory research outputs are not yet terminal",
        },
    }
    reconciled = reconcile_ledger()
    atomic_json(RESUME_ROOT / "reconciled-ledger.json", reconciled)
    state["tasks"][0]["artifacts"] = [
        "resume-c6b28c8/reconciled-ledger.json",
        "resume-c6b28c8/events.json",
    ]
    _refresh_ready(state)
    atomic_json(RESUME_STATE, state)
    event = {
        "schema": "l2r.resume.event.v1",
        "event": "resume-c6b28c8",
        "at_utc": state["created_at_utc"],
        "baseline_commit": state["baseline_commit"],
        "old_e0_policy": "immutable_checkpoint",
        "parent_budget_changed": False,
        "public_release_authorized": False,
        "hidden_test_generation_authorized": False,
        "source": "cloud-review attachment supplied by owner",
    }
    atomic_json(RESUME_ROOT / "resume-event.json", event)
    atomic_json(RESUME_EVENTS, [event])
    return state


def load_state() -> dict[str, Any]:
    if not RESUME_STATE.is_file():
        raise RuntimeError("L2-R is not bootstrapped; run l2_resume.py bootstrap")
    return read_json(RESUME_STATE)


def mark_task(task_id: str, status: str, *, artifacts: list[str] | None = None,
              next_action: str | None = None, blocker: dict[str, Any] | None = None,
              evidence_origin: str | None = None) -> dict[str, Any]:
    if status not in {"pending", "ready", "running", "complete", "complete_with_findings", "blocked_upstream", "blocked_external"}:
        raise ValueError(f"invalid resume task status: {status}")
    state = load_state()
    task = next((item for item in state["tasks"] if item["task_id"] == task_id), None)
    if task is None:
        raise KeyError(task_id)
    if status in TERMINAL_STATUSES:
        by_id = {item["task_id"]: item for item in state["tasks"]}
        unmet = [
            requirement for requirement in task.get("requires", [])
            if not _task_is_terminal(by_id[requirement], require_artifacts=True)
        ]
        if unmet:
            raise RuntimeError(f"cannot mark {task_id} terminal before dependencies: {unmet}")

    candidate = dict(task)
    candidate["status"] = status
    if artifacts is not None:
        candidate["artifacts"] = list(artifacts)
    if status == "blocked_external":
        if blocker is not None:
            candidate["blocker"] = blocker
    else:
        # Do not let a stale blocker survive a transition back to a normal
        # evidence state; the two terminal contracts are mutually exclusive.
        candidate["blocker"] = None
    if status in TERMINAL_STATUSES:
        error = _terminal_evidence_error(candidate)
        if error:
            raise ValueError(f"invalid terminal evidence for {task_id}: {error}")
        if status in EVIDENCE_TERMINAL_STATUSES and not all(
            _artifact_exists(path) for path in candidate.get("artifacts", [])
        ):
            raise ValueError(f"terminal task {task_id} requires all artifacts to exist")
        specific_error = _task_specific_terminal_error(candidate)
        if specific_error:
            raise ValueError(f"invalid terminal evidence for {task_id}: {specific_error}")

    task.update(candidate)
    task["execution_status"] = status
    task["acceptance_status"] = (
        "blocked_external" if status == "blocked_external"
        else "accepted" if status in TERMINAL_STATUSES
        else "pending"
    )
    if next_action is not None:
        task["next_action"] = next_action
    if evidence_origin is not None:
        task["evidence_origin"] = evidence_origin
    elif status == "blocked_external":
        task["evidence_origin"] = "external_blocker_evidence"
    task["updated_at_utc"] = utc_now()
    _refresh_ready(state)
    state["terminal_predicate"] = terminal_predicate(state)
    atomic_json(RESUME_STATE, state)
    return state


def verify_r0() -> dict[str, Any]:
    """Run the controller negative tests and close only the dependency-free R0."""

    state = load_state()
    r0 = next(task for task in state["tasks"] if task["task_id"] == "R0")
    if r0["status"] in TERMINAL_STATUSES:
        return {"status": r0["status"], "artifact": str(R0_VERIFICATION)}
    command = [
        sys.executable, "-m", "pytest", "-q",
        "tests/test_l2_campaign.py", "tests/test_l2_resume.py",
    ]
    completed = subprocess.run(
        command, cwd=LAB, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, check=False,
    )
    verification = {
        "schema": "l2r.r0.controller.verification.v1",
        "resume_id": RESUME_ID,
        "commit": git_head(),
        "command": command,
        "returncode": completed.returncode,
        "test_output_tail": completed.stdout[-4000:],
        "negative_controller_cases": [
            "blocked_dependency_does_not_release_downstream",
            "terminal_task_requires_real_artifacts",
            "changed_source_hash_rejects_receipt",
        ],
        "artifact_registry_reader": "load_qualified_receipts",
        "resume_event_exists": (RESUME_ROOT / "resume-event.json").is_file(),
        "reconciled_ledger_exists": (RESUME_ROOT / "reconciled-ledger.json").is_file(),
    }
    verification["passed"] = bool(
        completed.returncode == 0
        and verification["resume_event_exists"]
        and verification["reconciled_ledger_exists"]
    )
    atomic_json(R0_VERIFICATION, verification)
    if not verification["passed"]:
        raise RuntimeError("R0 controller verification failed; see r0-controller-verification.json")
    mark_task("R0", "complete_with_findings", artifacts=[
        "resume-c6b28c8/r0-controller-verification.json",
        "resume-c6b28c8/reconciled-ledger.json",
        "resume-c6b28c8/resume-event.json",
        "resume-c6b28c8/events.json",
    ], next_action="execute_R1")
    return verification


def _artifact_path(reference: str) -> Path:
    path = Path(reference)
    if not path.is_absolute():
        path = RESUME_ROOT / path if not reference.startswith("resume-c6b28c8/") else CAMPAIGN / reference
    return path


def _artifact_exists(reference: str) -> bool:
    return _artifact_path(reference).is_file()


def terminal_predicate(state: dict[str, Any] | None = None) -> dict[str, Any]:
    state = state or load_state()
    mandatory = list(state["tasks"])
    unfinished = [task["task_id"] for task in mandatory if task["status"] not in TERMINAL_STATUSES]
    ready = [task["task_id"] for task in mandatory if task["status"] in {"ready", "running"}]
    invalid_terminal_evidence = {
        task["task_id"]: error
        for task in mandatory
        if task["status"] in TERMINAL_STATUSES
        for error in [_terminal_evidence_error(task) or _task_specific_terminal_error(task)]
        if error
    }
    missing_artifacts = [
        task["task_id"] for task in mandatory
        if task["status"] in EVIDENCE_TERMINAL_STATUSES
        and (
            not task.get("artifacts")
            or not all(_artifact_exists(path) for path in task["artifacts"])
        )
    ]
    invalid_external_blocks = [task_id for task_id, error in invalid_terminal_evidence.items()
                               if error.startswith("blocked_external:")]
    result = {
        "all_mandatory_tasks_terminal": not unfinished,
        "no_ready_or_running_work": not ready,
        "all_terminal_artifacts_present": not missing_artifacts,
        "external_blockers_evidenced": not invalid_external_blocks,
        "terminal_evidence_contract_valid": not invalid_terminal_evidence,
        "unfinished_tasks": unfinished,
        "ready_or_running_tasks": ready,
        "missing_artifacts": missing_artifacts,
        "invalid_external_blocks": invalid_external_blocks,
        "invalid_terminal_evidence": invalid_terminal_evidence,
    }
    result["can_finalize"] = all(result[key] for key in (
        "all_mandatory_tasks_terminal", "no_ready_or_running_work",
        "all_terminal_artifacts_present", "external_blockers_evidenced",
        "terminal_evidence_contract_valid",
    ))
    return result


def status() -> dict[str, Any]:
    state = load_state()
    predicate = terminal_predicate(state)
    return {
        "resume_id": state["resume_id"],
        "current_commit": state.get("current_commit"),
        "ready_tasks": [task["task_id"] for task in state["tasks"] if task["status"] == "ready"],
        "task_statuses": {task["task_id"]: task["status"] for task in state["tasks"]},
        "terminal_predicate": predicate,
    }


def refresh_commit() -> dict[str, Any]:
    """Update only the resume metadata after a code commit; preserve task state."""

    state = load_state()
    state["current_commit"] = git_head()
    state["updated_at_utc"] = utc_now()
    state["terminal_predicate"] = terminal_predicate(state)
    atomic_json(RESUME_STATE, state)
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("bootstrap")
    subparsers.add_parser("status")
    subparsers.add_parser("verify-r0")
    subparsers.add_parser("refresh-commit")
    mark = subparsers.add_parser("mark")
    mark.add_argument("task")
    mark.add_argument("status", choices=("pending", "ready", "running", "complete", "complete_with_findings", "blocked_upstream", "blocked_external"))
    mark.add_argument("--artifact", action="append", default=[])
    mark.add_argument("--next-action")
    args = parser.parse_args()
    if args.command == "bootstrap":
        print(json.dumps(bootstrap(), ensure_ascii=False, indent=2))
    elif args.command == "status":
        print(json.dumps(status(), ensure_ascii=False, indent=2))
    elif args.command == "verify-r0":
        print(json.dumps(verify_r0(), ensure_ascii=False, indent=2))
    elif args.command == "refresh-commit":
        print(json.dumps(refresh_commit(), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(mark_task(args.task, args.status, artifacts=args.artifact or None, next_action=args.next_action), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
