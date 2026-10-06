#!/usr/bin/env python3
"""Metadata/stat-only F3 failed-output cleanup audit.

This audit deliberately opens JSON metadata only.  Candidate directories are
walked with ``stat`` and their extension/count/size breakdown is recorded;
scientific files (BI4/H5/CSV/DAT/VTK/etc.) are never opened or hashed.  The
script never deletes or mutates campaign data, the ledger, or any receipt.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
FAMILY_ROOT = DATA_ROOT / "families" / "F3"
LEDGER_PATH = DATA_ROOT / "runtime" / "resource-ledger.json"
INTEGRATION_CAMPAIGN_ROOT = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02"
)
CHECKPOINT_PATH = INTEGRATION_CAMPAIGN_ROOT / "handoff_20261003" / "ROOT_LIVE_RESUMPTION_CHECKPOINT_127.json"

BAD_STATUSES = {"failed", "interrupted_unfinalized", "reserved"}
SUCCESS_STATUSES = {"completed", "success", "succeeded", "done"}
SOLVER_KINDS = {"qualification", "production"}
SCIENCE_EXTENSIONS = {
    ".bi4",
    ".ibi4",
    ".obi4",
    ".h5",
    ".hdf5",
    ".vtk",
    ".vtu",
    ".csv",
    ".dat",
}


def read_json(path: Path) -> Any:
    # JSON is the only non-stat external file type this script opens.
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def status_is_bad(receipt: dict[str, Any]) -> bool:
    status = str(receipt.get("status", "")).lower()
    return status in BAD_STATUSES or (
        isinstance(receipt.get("returncode"), int) and receipt["returncode"] != 0
    )


def command_is_solver(command: Any) -> bool:
    if isinstance(command, str):
        command = [command]
    if not isinstance(command, list):
        return False
    return any(
        "DualSPHysics" in str(arg) or "DualSPHysics5" in str(arg)
        for arg in command
    )


def is_solver_receipt(receipt: dict[str, Any]) -> bool:
    request = receipt.get("request")
    request = request if isinstance(request, dict) else {}
    kind = request.get("kind", receipt.get("kind"))
    command = request.get("command", receipt.get("command"))
    return kind in SOLVER_KINDS and command_is_solver(command)


def safe_stat(path: Path) -> dict[str, Any]:
    try:
        stat = path.stat(follow_symlinks=False)
    except OSError as exc:
        return {"path": str(path), "exists": False, "error": type(exc).__name__}
    return {
        "path": str(path),
        "exists": True,
        "is_dir": path.is_dir(),
        "is_file": path.is_file(),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def tree_stat(path_value: Any) -> dict[str, Any]:
    """Stat a candidate tree without opening any member file."""
    if not isinstance(path_value, str) or not path_value:
        return {"path": path_value, "exists": False, "reason": "no_output_root"}
    root = Path(path_value)
    if not root.exists():
        return {"path": str(root), "exists": False, "reason": "missing_output_root"}
    if not root.is_dir():
        return {"path": str(root), "exists": True, "file_count": 1, "bytes": root.stat().st_size}

    files = 0
    directories = 0
    total_bytes = 0
    stat_errors = 0
    by_extension: dict[str, dict[str, int]] = defaultdict(lambda: {"file_count": 0, "bytes": 0})
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        directories += len(dirnames)
        for filename in filenames:
            member = Path(dirpath) / filename
            try:
                st = member.stat(follow_symlinks=False)
            except OSError:
                stat_errors += 1
                continue
            files += 1
            total_bytes += st.st_size
            extension = member.suffix.lower() or "<none>"
            by_extension[extension]["file_count"] += 1
            by_extension[extension]["bytes"] += st.st_size

    science = {
        ext: value
        for ext, value in sorted(by_extension.items())
        if ext in SCIENCE_EXTENSIONS
    }
    return {
        "path": str(root),
        "exists": True,
        "file_count": files,
        "directory_count": directories,
        "bytes": total_bytes,
        "stat_errors": stat_errors,
        "by_extension": dict(sorted(by_extension.items())),
        "science_extensions": science,
        "bi4_file_count": science.get(".bi4", {}).get("file_count", 0),
        "bi4_bytes": science.get(".bi4", {}).get("bytes", 0),
        "science_file_count": sum(x["file_count"] for x in science.values()),
        "science_bytes": sum(x["bytes"] for x in science.values()),
    }


def exact_process_evidence(receipt: dict[str, Any]) -> dict[str, Any]:
    """Check only PIDs recorded in the receipt; never scan /proc globally."""
    pid = receipt.get("pid")
    result: dict[str, Any] = {"recorded_pid": pid, "process_status": "no_recorded_pid"}
    if not isinstance(pid, int) or pid <= 0:
        return result
    proc = Path("/proc") / str(pid)
    if not proc.exists():
        result["process_status"] = "recorded_pid_absent_at_audit"
        result["fd_count"] = 0
        return result
    result["process_status"] = "recorded_pid_present_at_audit"
    try:
        result["fd_count"] = len(list((proc / "fd").iterdir()))
    except OSError as exc:
        result["fd_count"] = None
        result["fd_error"] = type(exc).__name__
    try:
        # /proc/PID/stat is process metadata, not scientific payload.
        result["stat_prefix"] = (proc / "stat").read_text(encoding="utf-8", errors="replace")[:256]
    except OSError as exc:
        result["stat_error"] = type(exc).__name__
    return result


def compact_reservation(reservation: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "id",
        "kind",
        "cpu_task_kind",
        "cpu_threads",
        "cpu_core_seconds",
        "gpu_seconds",
        "new_storage_bytes",
        "reserved_at_utc",
        "launcher_pid",
        "host",
    )
    return {key: reservation.get(key) for key in keys if key in reservation}


def ledger_summary(ledger: dict[str, Any]) -> dict[str, Any]:
    attempts = [
        row for row in ledger.get("attempts", [])
        if isinstance(row, dict) and str(row.get("id", "")).startswith("F3/")
    ]
    charges = [
        row for row in ledger.get("charges", [])
        if isinstance(row, dict) and str(row.get("id", "")).startswith("F3/")
    ]
    attempt_counts = Counter((row.get("kind"), row.get("status")) for row in attempts)
    charge_counts = Counter(row.get("status") for row in charges)
    charge_totals = {
        key: sum(float(row.get(key, 0) or 0) for row in charges)
        for key in ("gpu_seconds", "cpu_core_seconds")
    }
    failed_qualification_attempts = [
        {"id": row.get("id"), "status": row.get("status")}
        for row in attempts
        if row.get("kind") == "qualification" and row.get("status") == "failed"
    ]
    nonterminal_production_attempts = [
        {"id": row.get("id"), "status": row.get("status")}
        for row in attempts
        if row.get("kind") == "production"
        and row.get("status") not in SUCCESS_STATUSES
    ]
    return {
        "path": str(LEDGER_PATH),
        "deadline_utc": ledger.get("deadline_utc"),
        "adopted_at_utc": ledger.get("adopted_at_utc"),
        "limits": ledger.get("limits"),
        "f3_attempt_count": len(attempts),
        "f3_attempt_counts_by_kind_status": {
            f"{kind}:{status}": count
            for (kind, status), count in sorted(attempt_counts.items(), key=lambda x: str(x[0]))
        },
        "f3_failed_qualification_attempts": failed_qualification_attempts,
        "f3_nonterminal_production_attempts": nonterminal_production_attempts,
        "f3_charge_count": len(charges),
        "f3_charge_counts_by_status": dict(sorted(charge_counts.items(), key=lambda x: str(x[0]))),
        "f3_charge_totals": charge_totals,
        "current_reservations": [
            compact_reservation(row)
            for row in ledger.get("reservations", [])
            if isinstance(row, dict)
        ],
    }


def collect_small_json_files(roots: Iterable[Path], max_bytes: int = 5_000_000) -> list[Path]:
    paths: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for dirpath, _, filenames in os.walk(root, followlinks=False):
            for filename in filenames:
                if not filename.lower().endswith(".json"):
                    continue
                path = Path(dirpath) / filename
                try:
                    if path.stat(follow_symlinks=False).st_size <= max_bytes:
                        paths.append(path)
                except OSError:
                    continue
    return sorted(set(paths))


def find_metadata_references(tokens: list[str], own_receipt: Path, json_files: list[Path]) -> list[str]:
    tokens = [token for token in tokens if token]
    if not tokens:
        return []
    refs: list[str] = []
    for path in json_files:
        if path == own_receipt:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if any(token in text for token in tokens):
            refs.append(str(path))
    return refs


def is_current_or_queue_reference(path_value: str) -> bool:
    """Separate live/queue evidence from historical ledger snapshots."""
    path = path_value.lower()
    if "/recovery_" in path or "resource-ledger.before" in path or "resource-ledger.after" in path:
        return False
    return any(
        marker in path
        for marker in (
            "execution_queue",
            "/qualification_requests/",
            "/production_requests/",
            "/requests/",
            "controller",
            "pending",
            "queue",
        )
    )


def accepted_metadata(checkpoint: dict[str, Any]) -> dict[str, Any]:
    paths = [
        str(item)
        for item in checkpoint.get("accepted_decisions", [])
        if isinstance(item, str) and "f3" in item.lower()
    ]
    tokens: set[str] = set()
    for value in paths:
        decision_path = Path(value)
        if not decision_path.exists() or decision_path.suffix.lower() != ".json":
            continue
        try:
            decision = read_json(decision_path)
        except (OSError, json.JSONDecodeError):
            continue

        def collect(value: Any) -> None:
            if isinstance(value, str):
                if any(marker in value.lower() for marker in ("case", "attempt", "physical", "output", "receipt")):
                    tokens.add(value)
            elif isinstance(value, dict):
                for child in value.values():
                    collect(child)
            elif isinstance(value, list):
                for child in value:
                    collect(child)

        collect(decision)
    return {
        "checkpoint_path": str(CHECKPOINT_PATH),
        "checkpoint_visual_accepted_total": checkpoint.get("stage1_visual_accepted_complete_independent_cases"),
        "accepted_per_family": checkpoint.get("accepted_per_family"),
        "f3_accepted_decision_paths": paths,
        "f3_accepted_token_count": len(tokens),
        "f3_accepted_tokens": sorted(tokens),
    }


def pending_130_131_paths() -> list[str]:
    paths: list[str] = []
    if not INTEGRATION_CAMPAIGN_ROOT.exists():
        return paths
    for path in INTEGRATION_CAMPAIGN_ROOT.rglob("*"):
        name = path.name.lower()
        if not path.is_file() and not path.is_dir():
            continue
        if "root_followup_130" in name or "root_followup_131" in name:
            paths.append(str(path))
    return sorted(paths)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    ledger = read_json(LEDGER_PATH)
    checkpoint = read_json(CHECKPOINT_PATH) if CHECKPOINT_PATH.exists() else {}
    json_files = collect_small_json_files(
        [INTEGRATION_CAMPAIGN_ROOT, FAMILY_ROOT], max_bytes=5_000_000
    )
    accepted = accepted_metadata(checkpoint)
    accepted_tokens = accepted["f3_accepted_tokens"]

    completed_native: list[dict[str, Any]] = []
    failed_receipts: list[dict[str, Any]] = []
    case_successes: defaultdict[str, list[str]] = defaultdict(list)
    receipt_paths = sorted(FAMILY_ROOT.rglob("execution-receipt.json"))
    # Build the completed-native map first so a failed attempt is correctly
    # marked as superseded even when its path sorts before its successor.
    parsed_receipts: list[tuple[Path, dict[str, Any], dict[str, Any], Any, bool]] = []
    for receipt_path in receipt_paths:
        try:
            receipt = read_json(receipt_path)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(receipt, dict):
            continue
        request = receipt.get("request") if isinstance(receipt.get("request"), dict) else {}
        kind = request.get("kind", receipt.get("kind"))
        solver = is_solver_receipt(receipt)
        status = str(receipt.get("status", ""))
        returncode = receipt.get("returncode")
        successful = status.lower() in SUCCESS_STATUSES and returncode in (0, None)
        parsed_receipts.append((receipt_path, receipt, request, kind, solver))
        if solver and successful:
            row = {
                "receipt_path": str(receipt_path),
                "case_id": request.get("case_id"),
                "attempt_id": request.get("attempt_id"),
                "status": status,
                "returncode": returncode,
                "output_root": receipt.get("output_root"),
                "receipt_reported_bytes": receipt.get("bytes"),
                "special_stock": any(tag in str(request.get("attempt_id", "")).lower() for tag in ("root884", "root948")),
            }
            completed_native.append(row)
            case_successes[str(request.get("case_id", ""))].append(str(request.get("attempt_id", "")))

    # Process failed/unfinalized receipts after the completed-native pre-pass.
    for receipt_path, receipt, request, kind, solver in parsed_receipts:
        if not status_is_bad(receipt):
            continue
        status = str(receipt.get("status", ""))
        returncode = receipt.get("returncode")
        output_root = receipt.get("output_root") or request.get("output_root")
        stats = tree_stat(output_root)
        refs = find_metadata_references(
            [str(request.get("attempt_id", "")), str(output_root or "")],
            receipt_path,
            json_files,
        )
        process = exact_process_evidence(receipt)
        kind_text = str(kind or "")
        science_bytes = stats.get("science_bytes", 0) if stats.get("exists") else 0
        if solver:
            if science_bytes:
                classification = "solver_raw_output_candidate"
                reason = "failed/nonzero native solver receipt with stat-visible scientific output files"
            else:
                classification = "solver_failed_no_raw_payload"
                reason = "failed/nonzero native solver receipt but output root has no BI4/H5/VTK/CSV/DAT payload by stat"
        elif science_bytes:
            classification = "non_solver_intermediate"
            reason = f"failed/nonzero {kind_text or 'non-solver'} receipt with stat-visible intermediate payload; not a solver raw output"
        else:
            classification = "metadata_only_failure"
            reason = f"failed/nonzero {kind_text or 'non-solver'} receipt with metadata/log-only output by stat"

        case_id = str(request.get("case_id", ""))
        accepted_match = any(token and (token in case_id or token in str(output_root or "") or token in str(request.get("attempt_id", ""))) for token in accepted_tokens)
        completed_siblings = case_successes.get(case_id, [])
        reservation_refs = []
        for reservation in ledger.get("reservations", []):
            if not isinstance(reservation, dict):
                continue
            reservation_text = json.dumps(reservation, sort_keys=True)
            if any(token and token in reservation_text for token in (str(request.get("attempt_id", "")), str(output_root or ""), case_id)):
                reservation_refs.append(compact_reservation(reservation))

        if classification == "solver_raw_output_candidate":
            if process.get("process_status") == "recorded_pid_present_at_audit":
                disposition = "hold_active_worker"
            elif reservation_refs:
                disposition = "hold_current_ledger_reservation"
            elif refs:
                disposition = "hold_metadata_dependency_review"
            elif accepted_match:
                disposition = "hold_accepted_decision"
            else:
                disposition = "root_may_review_for_cleanup"
        else:
            disposition = "not_a_solver_raw_cleanup_candidate"

        failed_receipts.append({
            "receipt_path": str(receipt_path),
            "case_id": request.get("case_id"),
            "physical_case_id": request.get("physical_case_id"),
            "attempt_id": request.get("attempt_id"),
            "kind": kind,
            "status": status,
            "returncode": returncode,
            "error": receipt.get("error"),
            "termination_reason": receipt.get("termination_reason"),
            "started_at_utc": receipt.get("started_at_utc"),
            "finished_at_utc": receipt.get("finished_at_utc"),
            "output_root": output_root,
            "receipt_reported_bytes": receipt.get("bytes"),
            "receipt_reported_bytes_note": "receipt metadata field; independently stat output_bytes below",
            "expected_frames": request.get("expected_saved_frames", request.get("expected_native_frames")),
            "classification": classification,
            "reason": reason,
            "stat": stats,
            "exact_recorded_process": process,
            "current_ledger_reservation_matches": reservation_refs,
            "metadata_reference_files": refs,
            "current_or_queue_reference_files": [ref for ref in refs if is_current_or_queue_reference(ref)],
            "metadata_reference_count": len(refs),
            "current_or_queue_reference_count": sum(is_current_or_queue_reference(ref) for ref in refs),
            "case_has_completed_native_sibling": bool(completed_siblings),
            "completed_native_sibling_attempts": completed_siblings,
            "accepted_decision_match": accepted_match,
            "disposition": disposition,
        })

    failed_receipts.sort(key=lambda row: (str(row.get("classification")), str(row.get("case_id")), str(row.get("attempt_id"))))
    completed_native.sort(key=lambda row: (str(row.get("case_id")), str(row.get("attempt_id"))))
    candidate_rows = [
        row for row in failed_receipts
        if row["classification"] == "solver_raw_output_candidate"
    ]
    report = {
        "schema": "ds02.f3.fresh119.cleanup-audit.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "family": "F3",
            "data_root": str(DATA_ROOT),
            "family_root": str(FAMILY_ROOT),
            "read_policy": "JSON receipt/ledger metadata plus stat-only directory walks",
            "scientific_payload_opened": False,
            "scientific_payload_hashed": False,
            "files_deleted": False,
            "shared_state_modified": False,
        },
        "ledger": ledger_summary(ledger),
        "preservation": {
            "accepted_checkpoint": accepted,
            "pending_130_131_paths": pending_130_131_paths(),
            "pending_130_131_f3_paths": [
                path for path in pending_130_131_paths() if "/f3/" in path.lower()
            ],
            "pending_130_131_note": "These paths are preserved as external pending-work sentinels; none is edited by this F3 package, and the audit does not infer that any pending work is disposable.",
            "completed_native_stock_count": len(completed_native),
            "completed_native_stock": completed_native,
            "root884_or_root948_stock": [row for row in completed_native if row["special_stock"]],
            "completed_native_stock_rule": "All successful native solver receipts are preserved, including QN/precision-negative cases; no cleanup decision is inferred from numerical quality.",
        },
        "failed_receipt_count": len(failed_receipts),
        "failed_receipts": failed_receipts,
        "solver_raw_cleanup_review_candidates": candidate_rows,
        "summary": {
            "failed_receipts_by_class": dict(Counter(row["classification"] for row in failed_receipts)),
            "solver_raw_candidates": len(candidate_rows),
            "solver_raw_candidates_root_may_review": sum(row["disposition"] == "root_may_review_for_cleanup" for row in candidate_rows),
            "solver_raw_candidates_held": sum(row["disposition"] != "root_may_review_for_cleanup" for row in candidate_rows),
            "failed_output_stat_bytes_total": sum(row.get("stat", {}).get("bytes", 0) for row in failed_receipts),
            "failed_solver_raw_stat_bytes_total": sum(row.get("stat", {}).get("bytes", 0) for row in candidate_rows),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "failed_receipts": len(failed_receipts),
        "completed_native_stock": len(completed_native),
        "solver_raw_candidates": len(candidate_rows),
        "root_may_review": report["summary"]["solver_raw_candidates_root_may_review"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
