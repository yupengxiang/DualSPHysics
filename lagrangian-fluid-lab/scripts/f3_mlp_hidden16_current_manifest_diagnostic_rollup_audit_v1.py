#!/usr/bin/env python3
"""Read-only aggregate audit for the F3 MLP current-manifest batch reports.

The batch runner emits one JSON/Markdown report pair for each bounded batch.
This tool audits only those report files.  It never follows paths embedded in
the reports, so HDF5 inputs, checkpoints, evaluator receipts, registries,
ledgers, denominators, gates, PLAN, and running processes are outside its
input boundary.

The fixed rollout envelope is 32 current-manifest cases multiplied by seeds
17, 29, and 43.  A row is only fully auditable when the report itself carries
835 transitions, finite-rollout evidence, a passed validator, and both the
process and terminal receipt bindings.  Missing receipts are deliberately
diagnostic-only and retain zero credit; no positive credit is ever assigned by
this aggregate tool.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import sys
from typing import Any, Mapping, Sequence


LAB_ROOT = Path(__file__).resolve().parents[1]
REPORT_PREFIX = "F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-"
REPORT_JSON_SUFFIX = ".json"
REPORT_MARKDOWN_SUFFIX = ".zh-CN.md"
RUNNER_SCHEMA = "core.f3.mlp.hidden16.current_manifest.diagnostic_batch.v1"
REPORT_ID = "f3-mlp-hidden16-current-manifest-diagnostic-rollup-audit-v1"
SCHEMA = "core.f3.mlp.hidden16.current_manifest.diagnostic_batch.rollup_audit.v1"

SEEDS = (17, 29, 43)
EXPECTED_CASE_COUNT = 32
EXPECTED_TRANSITIONS = 835
EXPECTED_FRAMES = EXPECTED_TRANSITIONS + 1
ALLOWED_REPORT_STATUSES = frozenset(
    {"dry_run_ready", "completed_diagnostic_batch", "blocked_diagnostic_batch"}
)
ALLOWED_RESULT_STATUSES = frozenset(
    {
        "dry_run_ready",
        "exited_successfully",
        "blocked_worker_fail_closed",
        "blocked_fail_closed",
    }
)

MAX_REPORT_JSON_BYTES = 64 * 1024 * 1024
MAX_MARKDOWN_BYTES = 8 * 1024 * 1024
MAX_JSON_DEPTH = 64
MAX_ARRAY_ITEMS = 8192

ZERO_CREDIT = {
    "diagnostic_only": True,
    "formal": False,
    "formal_eligible": False,
    "T1_numerical": False,
    "T2_macro": False,
    "T2_path": False,
    "qualification": False,
    "qualification_credit": 0,
    "credit": 0,
}


class AuditError(ValueError):
    """A fail-closed input or output error."""


def _make_case_id(index: int) -> str:
    # The current F3 development matrix starts at a=0.903125 and advances by
    # 0.00625 per case.  Integer micro-units avoid floating-point formatting.
    micro_units = 903125 + index * 6250
    return f"F3_DEV_{index:02d}_a{micro_units // 1_000_000}p{micro_units % 1_000_000:06d}"


EXPECTED_CASE_IDS = tuple(_make_case_id(index) for index in range(EXPECTED_CASE_COUNT))
EXPECTED_CASE_ID_SET = frozenset(EXPECTED_CASE_IDS)
EXPECTED_PAIRS = frozenset((case_id, seed) for case_id in EXPECTED_CASE_IDS for seed in SEEDS)


def _issue(code: str, message: str, **details: Any) -> dict[str, Any]:
    value: dict[str, Any] = {"code": code, "message": message}
    value.update(details)
    return value


def _absolute_path(value: Path | str, name: str) -> Path:
    raw = os.fspath(value)
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise AuditError(f"{name} must be a non-empty path")
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    normalized = Path(os.path.normpath(str(candidate)))
    return normalized


def _path_identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size)


def _reject_symlink_components(path: Path, name: str) -> None:
    current = Path(path.anchor or "/")
    for part in path.parts[1:]:
        current /= part
        try:
            info = os.lstat(current)
        except OSError as error:
            raise AuditError(f"cannot inspect {name}: {error}") from error
        if stat.S_ISLNK(info.st_mode):
            raise AuditError(f"{name} contains a symlink component")


def _read_bounded_bytes(path: Path, *, name: str, max_bytes: int) -> tuple[bytes, dict[str, Any]]:
    """Read an immutable, regular, single-link report file with a size bound."""

    _reject_symlink_components(path, name)
    try:
        before = os.lstat(path)
    except OSError as error:
        raise AuditError(f"cannot inspect {name}: {error}") from error
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise AuditError(f"{name} must be a regular single-link file")
    if before.st_size > max_bytes:
        raise AuditError(f"{name} exceeds bounded size {max_bytes}")

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise AuditError(f"cannot open {name}: {error}") from error

    chunks: list[bytes] = []
    total = 0
    expected = _path_identity(before)
    try:
        opened = os.fstat(descriptor)
        if _path_identity(opened) != expected:
            raise AuditError(f"{name} changed before bounded read")
        while total <= max_bytes:
            block = os.read(descriptor, min(1024 * 1024, max_bytes + 1 - total))
            if not block:
                break
            chunks.append(block)
            total += len(block)
        closed = os.fstat(descriptor)
        if _path_identity(closed) != expected or total != before.st_size:
            raise AuditError(f"{name} changed during bounded read")
    except OSError as error:
        raise AuditError(f"cannot read {name}: {error}") from error
    finally:
        os.close(descriptor)

    try:
        after = os.lstat(path)
    except OSError as error:
        raise AuditError(f"cannot inspect {name} after read: {error}") from error
    if _path_identity(after) != expected:
        raise AuditError(f"{name} changed after bounded read")

    raw = b"".join(chunks)
    return raw, {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def _reject_constant(token: str) -> None:
    raise AuditError(f"non-finite JSON constant is not allowed: {token}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise AuditError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _walk_json(value: Any, name: str = "value", depth: int = 0) -> None:
    if depth > MAX_JSON_DEPTH:
        raise AuditError(f"{name} exceeds maximum JSON depth")
    if value is None or isinstance(value, (bool, str, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise AuditError(f"{name} contains a non-finite number")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise AuditError(f"{name} contains a non-string key")
            _walk_json(item, f"{name}.{key}", depth + 1)
        return
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        if len(value) > MAX_ARRAY_ITEMS:
            raise AuditError(f"{name} contains too many array items")
        for index, item in enumerate(value):
            _walk_json(item, f"{name}[{index}]", depth + 1)
        return
    raise AuditError(f"{name} contains unsupported type {type(value).__name__}")


def _read_json_report(path: Path) -> tuple[Mapping[str, Any], dict[str, Any]]:
    raw, identity = _read_bounded_bytes(path, name=f"JSON report {path.name}", max_bytes=MAX_REPORT_JSON_BYTES)
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError, AuditError, RecursionError) as error:
        raise AuditError(f"invalid JSON report {path.name}: {error}") from error
    if not isinstance(payload, Mapping):
        raise AuditError(f"JSON report {path.name} must contain an object")
    _walk_json(payload, f"JSON report {path.name}")
    return payload, identity


def _read_markdown(path: Path) -> tuple[str, dict[str, Any]]:
    raw, identity = _read_bounded_bytes(
        path, name=f"Markdown report {path.name}", max_bytes=MAX_MARKDOWN_BYTES
    )
    try:
        text = raw.decode("utf-8")
    except UnicodeError as error:
        raise AuditError(f"invalid UTF-8 Markdown report {path.name}: {error}") from error
    if not text.strip():
        raise AuditError(f"Markdown report {path.name} is empty")
    return text, identity


def _string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _pair(value: Mapping[str, Any]) -> tuple[str, int] | None:
    case_id = value.get("case_id")
    seed = value.get("seed")
    if not isinstance(case_id, str) or type(seed) is not int:
        return None
    return case_id, seed


def _zero_credit_check(value: Any, name: str, *, require_all: bool = True) -> tuple[bool, list[dict[str, Any]]]:
    if not isinstance(value, Mapping):
        return False, [_issue("zero_credit_not_object", f"{name} is not an object")]
    issues: list[dict[str, Any]] = []
    for key, expected in ZERO_CREDIT.items():
        if key not in value:
            if require_all:
                issues.append(_issue("zero_credit_field_missing", f"{name}.{key} is missing", field=key))
            continue
        if value[key] != expected or (isinstance(expected, bool) and type(value[key]) is not bool):
            issues.append(
                _issue(
                    "positive_or_drifted_credit",
                    f"{name}.{key} must remain {expected!r}",
                    field=key,
                    observed=value[key],
                )
            )
    return not issues, issues


def _first_present(value: Mapping[str, Any], keys: Sequence[str]) -> list[Any]:
    return [value[key] for key in keys if key in value]


def _extract_bool(value: Mapping[str, Any], keys: Sequence[str], nested_keys: Sequence[str] = ()) -> bool | None:
    candidates: list[Any] = _first_present(value, keys)
    for nested_name in ("evaluation", "validator", "validator_receipt", "hdf5_validator", "checks"):
        nested = value.get(nested_name)
        if isinstance(nested, Mapping):
            candidates.extend(_first_present(nested, nested_keys))
    observed = [item for item in candidates if type(item) is bool]
    if not observed:
        return None
    return all(observed)


def _extract_ints(value: Mapping[str, Any], keys: Sequence[str], nested_keys: Sequence[str] = ()) -> list[int]:
    candidates: list[Any] = _first_present(value, keys)
    for nested_name in ("evaluation", "validator", "validator_receipt", "hdf5_validator", "checks"):
        nested = value.get(nested_name)
        if isinstance(nested, Mapping):
            candidates.extend(_first_present(nested, nested_keys))
    return [item for item in candidates if type(item) is int]


def _validate_markdown_pair(text: str, batch_id: str | None) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if "# F3 MLP hidden16 current-manifest diagnostic batch" not in text:
        issues.append(_issue("markdown_header_missing", "Markdown report lacks the runner header"))
    if "diagnostic" not in text.lower() or "credit" not in text.lower():
        issues.append(_issue("markdown_zero_credit_statement_missing", "Markdown report lacks diagnostic/credit wording"))
    if batch_id is not None and f"batch=`{batch_id}`" not in text:
        issues.append(_issue("markdown_batch_binding_missing", "Markdown report is not bound to the JSON batch_id"))
    return issues


def _terminal_pairs(payload: Mapping[str, Any], issues: list[dict[str, Any]]) -> tuple[set[tuple[str, int]], bool]:
    value = payload.get("terminal_receipts")
    if not isinstance(value, Mapping):
        issues.append(_issue("terminal_receipts_missing", "report.terminal_receipts is missing"))
        return set(), False
    status = value.get("status")
    paths = value.get("paths")
    if not isinstance(paths, list):
        issues.append(_issue("terminal_receipt_paths_missing", "report.terminal_receipts.paths is not a list"))
        paths = []
    pairs: set[tuple[str, int]] = set()
    for index, item in enumerate(paths):
        if not isinstance(item, Mapping):
            issues.append(_issue("terminal_receipt_row_invalid", "terminal receipt row is not an object", index=index))
            continue
        pair = _pair(item)
        if pair is None:
            issues.append(_issue("terminal_receipt_binding_missing", "terminal receipt row lacks case_id/seed", index=index))
            continue
        if pair in pairs:
            issues.append(_issue("duplicate_terminal_receipt_pair", "terminal receipt pair is duplicated", pair=list(pair)))
        pairs.add(pair)
    complete = status == "complete" and bool(paths)
    return pairs, complete


def _row_audit(
    *,
    batch_id: str,
    json_name: str,
    plan: Mapping[str, Any],
    result: Mapping[str, Any] | None,
    terminal_pairs: set[tuple[str, int]],
    terminal_complete: bool,
    report_zero_credit: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    plan_pair = _pair(plan)
    case_id = plan_pair[0] if plan_pair else _string(plan.get("case_id"))
    seed = plan_pair[1] if plan_pair else plan.get("seed")
    pair_label = [case_id, seed]
    if case_id not in EXPECTED_CASE_ID_SET:
        issues.append(_issue("unexpected_case_id", "plan case_id is outside the fixed 32-case plan", pair=pair_label))
    if seed not in SEEDS:
        issues.append(_issue("unexpected_seed", "plan seed is outside the fixed seed set", pair=pair_label))

    planned_transitions = plan.get("transitions") == EXPECTED_TRANSITIONS
    planned_frames = plan.get("frames") == EXPECTED_FRAMES
    if not planned_transitions:
        issues.append(_issue("plan_transitions_not_835", "plan row does not declare 835 transitions", pair=pair_label))
    if not planned_frames:
        issues.append(_issue("plan_frames_not_836", "plan row does not declare 836 frames", pair=pair_label))

    result_zero_credit = False
    result_status: str | None = None
    observed_transitions: int | None = None
    finite_rollout: bool | None = None
    validator_passed: bool | None = None
    process_receipt = False
    result_binding = False
    if result is None:
        issues.append(_issue("result_row_missing", "plan row has no matching result row", pair=pair_label))
    else:
        result_pair = _pair(result)
        result_binding = result_pair == plan_pair
        if not result_binding:
            issues.append(_issue("result_binding_mismatch", "result row case_id/seed differs from plan row", pair=pair_label))
        result_status = _string(result.get("status"))
        if result_status not in ALLOWED_RESULT_STATUSES:
            issues.append(_issue("illegal_result_status", "result status is not emitted by the runner", status=result_status, pair=pair_label))
        result_zero_credit, result_issues = _zero_credit_check(result, "result")
        issues.extend(result_issues)

        transition_values = _extract_ints(
            result,
            ("transitions", "transitions_executed", "trajectory_transitions"),
            ("transitions_executed", "trajectory_transitions"),
        )
        if transition_values:
            observed_transitions = transition_values[-1]
            if any(item != EXPECTED_TRANSITIONS for item in transition_values):
                issues.append(_issue("observed_transitions_not_835", "result row reports a transition count other than 835", pair=pair_label))
        else:
            issues.append(_issue("observed_transitions_missing", "result row has no finite execution transition count", pair=pair_label))

        finite_rollout = _extract_bool(
            result,
            ("finite", "finite_rollout_complete", "finite_complete"),
            ("finite", "finite_rollout_complete", "finite_complete"),
        )
        if finite_rollout is not True:
            issues.append(_issue("finite_rollout_missing_or_false", "result row does not attest a finite complete rollout", pair=pair_label))

        validator_passed = _extract_bool(
            result,
            ("validator_passed", "terminal_validator_passed"),
            ("passed", "validator_passed", "terminal_validator_passed"),
        )
        if validator_passed is not True:
            issues.append(_issue("validator_pass_missing_or_false", "result row does not attest validator passed=true", pair=pair_label))

        proof_written = result.get("proof_written") is True
        proof_path = _string(result.get("proof_path")) or _string(result.get("process_proof"))
        process_receipt = result_status == "exited_successfully" and proof_written and proof_path is not None
        if not process_receipt:
            issues.append(_issue("process_receipt_missing", "process exit proof is absent or result is not successful", pair=pair_label))

    terminal_receipt = plan_pair in terminal_pairs and terminal_complete
    if not terminal_receipt:
        issues.append(_issue("terminal_receipt_missing", "matching terminal receipt is absent", pair=pair_label))

    row_zero_credit = report_zero_credit and result_zero_credit
    if not row_zero_credit:
        issues.append(_issue("missing_receipt_not_zero_credit", "missing receipt path is not explicitly diagnostic zero-credit", pair=pair_label))

    checks = {
        "plan_transitions_835": planned_transitions,
        "plan_frames_836": planned_frames,
        "result_binding": result_binding,
        "observed_transitions_835": observed_transitions == EXPECTED_TRANSITIONS,
        "finite_rollout_complete": finite_rollout is True,
        "validator_passed": validator_passed is True,
        "process_receipt_present": process_receipt,
        "terminal_receipt_present": terminal_receipt,
        "diagnostic_zero_credit": row_zero_credit,
        "missing_receipts_remain_zero_credit": row_zero_credit if not (process_receipt and terminal_receipt) else True,
    }
    fully_auditable = all(
        checks[key]
        for key in (
            "plan_transitions_835",
            "plan_frames_836",
            "result_binding",
            "observed_transitions_835",
            "finite_rollout_complete",
            "validator_passed",
            "process_receipt_present",
            "terminal_receipt_present",
            "diagnostic_zero_credit",
        )
    )
    return (
        {
            "batch_id": batch_id,
            "json_report": json_name,
            "case_id": case_id,
            "seed": seed,
            "result_status": result_status,
            "observed_transitions": observed_transitions,
            "finite_rollout": finite_rollout,
            "validator_passed": validator_passed,
            "checks": checks,
            "fully_auditable_diagnostic_row": fully_auditable,
            "credit_assigned": 0,
            "issues": issues,
        },
        issues,
    )


def _audit_runner_report(
    payload: Mapping[str, Any],
    *,
    json_path: Path,
    markdown_path: Path | None,
    markdown_text: str | None,
    json_identity: Mapping[str, Any],
    markdown_identity: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    batch_id = _string(payload.get("batch_id"))
    if payload.get("schema") != RUNNER_SCHEMA:
        issues.append(_issue("runner_schema_mismatch", "JSON is not a current-manifest diagnostic batch report"))
    if payload.get("report_id") != "f3-mlp-hidden16-current-manifest-diagnostic-batch-v1":
        issues.append(_issue("runner_report_id_mismatch", "report_id does not match the current batch runner"))
    status = _string(payload.get("status"))
    if status not in ALLOWED_REPORT_STATUSES:
        issues.append(_issue("illegal_report_status", "report status is not emitted by the runner", status=status))
    if batch_id is None:
        issues.append(_issue("batch_id_missing", "batch_id is missing or empty"))
        batch_id = f"<missing:{json_path.name}>"

    top_zero_credit, zero_issues = _zero_credit_check(payload, "report")
    issues.extend(zero_issues)
    if payload.get("source_bound") is not True:
        issues.append(_issue("source_binding_missing", "report.source_bound must be true"))

    if markdown_path is None:
        issues.append(_issue("markdown_pair_missing", "JSON report has no matching Markdown report"))
    elif markdown_text is not None:
        issues.extend(_validate_markdown_pair(markdown_text, batch_id))

    plans_value = payload.get("plans")
    results_value = payload.get("results")
    plans = plans_value if isinstance(plans_value, list) else []
    results = results_value if isinstance(results_value, list) else []
    if not isinstance(plans_value, list) or not plans:
        issues.append(_issue("plans_missing_or_empty", "report.plans must be a non-empty list"))
    if not isinstance(results_value, list):
        issues.append(_issue("results_missing_or_invalid", "report.results must be a list"))

    plan_pairs = [_pair(item) for item in plans if isinstance(item, Mapping)]
    result_pairs = [_pair(item) for item in results if isinstance(item, Mapping)]
    if any(pair is None for pair in plan_pairs):
        issues.append(_issue("plan_binding_missing", "one or more plan rows lack case_id/seed"))
    if any(pair is None for pair in result_pairs):
        issues.append(_issue("result_binding_missing", "one or more result rows lack case_id/seed"))
    valid_plan_pairs = [pair for pair in plan_pairs if pair is not None]
    valid_result_pairs = [pair for pair in result_pairs if pair is not None]
    duplicate_plan_pairs = sorted(pair for pair, count in Counter(valid_plan_pairs).items() if count > 1)
    duplicate_result_pairs = sorted(pair for pair, count in Counter(valid_result_pairs).items() if count > 1)
    if duplicate_plan_pairs:
        issues.append(_issue("duplicate_plan_case_seed", "plan case/seed pair is duplicated within a report", pairs=[list(pair) for pair in duplicate_plan_pairs]))
    if duplicate_result_pairs:
        issues.append(_issue("duplicate_result_case_seed", "result case/seed pair is duplicated within a report", pairs=[list(pair) for pair in duplicate_result_pairs]))

    result_by_pair: dict[tuple[str, int], Mapping[str, Any]] = {}
    for item in results:
        if not isinstance(item, Mapping):
            continue
        pair = _pair(item)
        if pair is not None and pair not in result_by_pair:
            result_by_pair[pair] = item

    terminal_pairs, terminal_complete = _terminal_pairs(payload, issues)
    row_audits: list[dict[str, Any]] = []
    for plan in plans:
        if not isinstance(plan, Mapping):
            issues.append(_issue("plan_row_invalid", "plan row is not an object"))
            continue
        pair = _pair(plan)
        row, row_issues = _row_audit(
            batch_id=batch_id,
            json_name=json_path.name,
            plan=plan,
            result=result_by_pair.get(pair) if pair is not None else None,
            terminal_pairs=terminal_pairs,
            terminal_complete=terminal_complete,
            report_zero_credit=top_zero_credit,
        )
        row_audits.append(row)
        issues.extend(row_issues)

    extra_result_pairs = sorted(set(valid_result_pairs) - set(valid_plan_pairs))
    if extra_result_pairs:
        issues.append(_issue("result_pair_without_plan", "result contains case/seed pairs absent from plans", pairs=[list(pair) for pair in extra_result_pairs]))

    coverage = payload.get("coverage")
    if not isinstance(coverage, Mapping):
        issues.append(_issue("coverage_missing", "report.coverage is missing"))
    else:
        expected_coverage = {
            "selected_case_count": len(valid_plan_pairs),
            "terminal_receipts_required": len(valid_plan_pairs),
            "terminal_receipts_observed": sum(pair in terminal_pairs for pair in valid_plan_pairs),
        }
        for key, expected in expected_coverage.items():
            if key in coverage and coverage[key] != expected:
                issues.append(_issue("coverage_drift", f"report.coverage.{key} differs from report rows", field=key, expected=expected, observed=coverage[key]))

    side_effects = payload.get("side_effects")
    if not isinstance(side_effects, Mapping):
        issues.append(_issue("side_effects_missing", "report.side_effects is missing"))
    else:
        for key in ("processes_stopped", "processes_restarted", "registry_writes", "ledger_writes", "denominator_writes", "gate_writes", "plan_writes"):
            if side_effects.get(key) != 0:
                issues.append(_issue("formal_side_effect_detected", f"report.side_effects.{key} must be zero", field=key, observed=side_effects.get(key)))

    scheduler = payload.get("scheduler")
    if not isinstance(scheduler, Mapping):
        issues.append(_issue("scheduler_missing", "report.scheduler is missing"))
    else:
        for key in ("existing_processes_killed", "existing_processes_restarted"):
            if scheduler.get(key) != 0:
                issues.append(_issue("existing_process_touched", f"report.scheduler.{key} must be zero", field=key, observed=scheduler.get(key)))

    if status == "completed_diagnostic_batch" and any(row.get("result_status") != "exited_successfully" for row in row_audits):
        issues.append(_issue("completed_status_with_nonterminal_rows", "completed report contains a non-success result row"))
    if status == "blocked_diagnostic_batch" and not any(row.get("result_status") != "exited_successfully" for row in row_audits):
        issues.append(_issue("blocked_status_without_blocked_rows", "blocked report has no blocked result row"))

    return (
        {
            "json_report": json_path.name,
            "markdown_report": markdown_path.name if markdown_path is not None else None,
            "json_identity": dict(json_identity),
            "markdown_identity": dict(markdown_identity) if markdown_identity is not None else None,
            "batch_id": batch_id,
            "status": status,
            "status_legal": status in ALLOWED_REPORT_STATUSES,
            "plan_pairs": [list(pair) for pair in valid_plan_pairs],
            "result_pairs": [list(pair) for pair in valid_result_pairs],
            "duplicate_plan_pairs": [list(pair) for pair in duplicate_plan_pairs],
            "duplicate_result_pairs": [list(pair) for pair in duplicate_result_pairs],
            "terminal_receipt_pairs": [list(pair) for pair in sorted(terminal_pairs)],
            "terminal_receipts_complete": terminal_complete,
            "top_level_diagnostic_zero_credit": top_zero_credit,
            "rows": row_audits,
            "issues": issues,
        },
        issues,
    )


def _candidate_files(reports_dir: Path) -> tuple[list[Path], list[Path]]:
    _reject_symlink_components(reports_dir, "reports directory")
    try:
        info = os.lstat(reports_dir)
    except OSError as error:
        raise AuditError(f"cannot inspect reports directory: {error}") from error
    if not stat.S_ISDIR(info.st_mode):
        raise AuditError("reports directory must be a directory")
    json_files: list[Path] = []
    markdown_files: list[Path] = []
    try:
        with os.scandir(reports_dir) as entries:
            for entry in entries:
                name = entry.name
                if not name.startswith(REPORT_PREFIX):
                    continue
                if name.endswith(REPORT_JSON_SUFFIX):
                    json_files.append(reports_dir / name)
                elif name.endswith(REPORT_MARKDOWN_SUFFIX):
                    markdown_files.append(reports_dir / name)
    except OSError as error:
        raise AuditError(f"cannot scan reports directory: {error}") from error
    return sorted(json_files), sorted(markdown_files)


def _base_report(
    *,
    reports_dir: Path,
    json_files: Sequence[Path],
    markdown_files: Sequence[Path],
) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "report_id": REPORT_ID,
        "status": "incomplete_diagnostic_rollup",
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": {
            "reports_directory": str(reports_dir),
            "json_candidate_count": len(json_files),
            "markdown_candidate_count": len(markdown_files),
            "runner_schema": RUNNER_SCHEMA,
            "filename_prefix": REPORT_PREFIX,
        },
        "fixed_plan": {
            "case_count": EXPECTED_CASE_COUNT,
            "case_ids": list(EXPECTED_CASE_IDS),
            "seeds": list(SEEDS),
            "expected_case_seed_count": len(EXPECTED_PAIRS),
            "expected_transitions": EXPECTED_TRANSITIONS,
            "expected_frames": EXPECTED_FRAMES,
        },
        "input_boundary": {
            "batch_json_reports_opened": True,
            "batch_markdown_reports_opened": True,
            "hdf5_opened": False,
            "checkpoint_opened": False,
            "embedded_receipts_opened": False,
            "processes_contacted": False,
            "registry_read": False,
            "ledger_read": False,
            "denominator_read": False,
            "gate_read": False,
            "plan_read": False,
        },
        "side_effects": {
            "processes_started": 0,
            "processes_stopped": 0,
            "processes_restarted": 0,
            "registry_writes": 0,
            "ledger_writes": 0,
            "denominator_writes": 0,
            "gate_writes": 0,
            "plan_writes": 0,
        },
        "batches": [],
        "ignored_non_runner_json": [],
        "invalid_json_reports": [],
        "orphan_markdown_reports": [],
        "pair_issues": [],
        "coverage": {},
        "issues": [],
        **ZERO_CREDIT,
    }


def build_audit(reports_dir: Path | str = LAB_ROOT / "reports") -> dict[str, Any]:
    """Build an aggregate report without reading any referenced artifact path."""

    directory = _absolute_path(reports_dir, "reports_dir")
    json_files, markdown_files = _candidate_files(directory)
    report = _base_report(reports_dir=directory, json_files=json_files, markdown_files=markdown_files)
    markdown_by_name = {path.name: path for path in markdown_files}
    runner_stems: set[str] = set()
    batch_reports: list[dict[str, Any]] = []

    for json_path in json_files:
        try:
            payload, identity = _read_json_report(json_path)
        except AuditError as error:
            report["invalid_json_reports"].append({"json_report": json_path.name, "error": str(error)})
            continue
        if payload.get("schema") != RUNNER_SCHEMA:
            report["ignored_non_runner_json"].append(
                {"json_report": json_path.name, "schema": payload.get("schema"), "report_id": payload.get("report_id")}
            )
            continue

        stem = json_path.name[: -len(REPORT_JSON_SUFFIX)]
        runner_stems.add(stem)
        markdown_path = markdown_by_name.get(stem + REPORT_MARKDOWN_SUFFIX)
        markdown_text: str | None = None
        markdown_identity: dict[str, Any] | None = None
        if markdown_path is not None:
            try:
                markdown_text, markdown_identity = _read_markdown(markdown_path)
            except AuditError as error:
                report["pair_issues"].append({"json_report": json_path.name, "markdown_report": markdown_path.name, "error": str(error)})
                markdown_text = None
                markdown_identity = None
        batch_report, _ = _audit_runner_report(
            payload,
            json_path=json_path,
            markdown_path=markdown_path,
            markdown_text=markdown_text,
            json_identity=identity,
            markdown_identity=markdown_identity,
        )
        batch_reports.append(batch_report)

    all_markdown_stems = {path.name[: -len(REPORT_MARKDOWN_SUFFIX)] for path in markdown_files}
    for stem in sorted(all_markdown_stems - runner_stems - {path.name[: -len(REPORT_JSON_SUFFIX)] for path in json_files}):
        report["orphan_markdown_reports"].append({"markdown_report": stem + REPORT_MARKDOWN_SUFFIX})

    report["batches"] = batch_reports
    report["pair_issues"].extend(
        {
            "json_report": batch["json_report"],
            "markdown_report": batch["markdown_report"],
            "issues": [item for item in batch["issues"] if item["code"].startswith("markdown_") or item["code"] == "markdown_pair_missing"],
        }
        for batch in batch_reports
        if any(item["code"].startswith("markdown_") or item["code"] == "markdown_pair_missing" for item in batch["issues"])
    )

    batch_ids = [batch["batch_id"] for batch in batch_reports]
    duplicate_batch_ids = sorted(batch_id for batch_id, count in Counter(batch_ids).items() if count > 1)
    if duplicate_batch_ids:
        report["issues"].append(_issue("duplicate_batch_id", "batch_id is duplicated across report files", batch_ids=duplicate_batch_ids))

    planned_occurrences: list[tuple[str, int]] = []
    result_occurrences: list[tuple[str, int]] = []
    all_rows: list[dict[str, Any]] = []
    for batch in batch_reports:
        planned_occurrences.extend(tuple(pair) for pair in batch["plan_pairs"])
        result_occurrences.extend(tuple(pair) for pair in batch["result_pairs"])
        all_rows.extend(batch["rows"])

    planned_counter = Counter(planned_occurrences)
    result_counter = Counter(result_occurrences)
    planned_pairs = set(planned_counter)
    result_pairs = set(result_counter)
    duplicate_planned_pairs = sorted(pair for pair, count in planned_counter.items() if count > 1)
    duplicate_result_pairs = sorted(pair for pair, count in result_counter.items() if count > 1)
    unexpected_planned_pairs = sorted(planned_pairs - EXPECTED_PAIRS)
    unexpected_result_pairs = sorted(result_pairs - EXPECTED_PAIRS)
    missing_planned_pairs = sorted(EXPECTED_PAIRS - planned_pairs)
    missing_result_pairs = sorted(EXPECTED_PAIRS - result_pairs)
    fully_auditable_rows = sum(row["fully_auditable_diagnostic_row"] for row in all_rows)
    row_failures = sum(not row["fully_auditable_diagnostic_row"] for row in all_rows)
    row_issue_codes = Counter(
        issue["code"]
        for row in all_rows
        for issue in row["issues"]
        if isinstance(issue, Mapping) and isinstance(issue.get("code"), str)
    )

    if duplicate_planned_pairs:
        report["issues"].append(_issue("duplicate_case_seed_pair", "case/seed pair is duplicated across batch plans", pairs=[list(pair) for pair in duplicate_planned_pairs]))
    if duplicate_result_pairs:
        report["issues"].append(_issue("duplicate_result_case_seed_pair", "case/seed pair is duplicated across batch results", pairs=[list(pair) for pair in duplicate_result_pairs]))
    if unexpected_planned_pairs or unexpected_result_pairs:
        report["issues"].append(_issue("unexpected_case_seed_pair", "observed case/seed pair is outside the fixed 96-pair plan", planned=[list(pair) for pair in unexpected_planned_pairs], results=[list(pair) for pair in unexpected_result_pairs]))
    if missing_planned_pairs:
        report["issues"].append(_issue("missing_case_seed_pair", "fixed plan case/seed pairs are missing from batch plans", pairs=[list(pair) for pair in missing_planned_pairs]))
    if missing_result_pairs:
        report["issues"].append(_issue("missing_result_case_seed_pair", "fixed plan case/seed pairs are missing from batch results", pairs=[list(pair) for pair in missing_result_pairs]))
    if report["invalid_json_reports"]:
        report["issues"].append(_issue("invalid_json_report", "one or more candidate JSON reports could not be read"))
    if report["orphan_markdown_reports"]:
        report["issues"].append(_issue("orphan_markdown_report", "one or more Markdown reports lack a runner JSON pair"))
    report["issues"].extend(
        _issue("batch_report_invalid", "batch report contains one or more audit issues", json_report=batch["json_report"])
        for batch in batch_reports
        if batch["issues"]
    )

    report["coverage"] = {
        "expected_case_seed_count": len(EXPECTED_PAIRS),
        "batch_reports_observed": len(batch_reports),
        "unique_batch_ids": len(set(batch_ids)),
        "duplicate_batch_ids": duplicate_batch_ids,
        "planned_case_seed_rows_observed": len(planned_occurrences),
        "unique_planned_case_seed_pairs": len(planned_pairs),
        "duplicate_planned_case_seed_pairs": [list(pair) for pair in duplicate_planned_pairs],
        "unexpected_planned_case_seed_pairs": [list(pair) for pair in unexpected_planned_pairs],
        "missing_planned_case_seed_pairs": [list(pair) for pair in missing_planned_pairs],
        "result_case_seed_rows_observed": len(result_occurrences),
        "unique_result_case_seed_pairs": len(result_pairs),
        "duplicate_result_case_seed_pairs": [list(pair) for pair in duplicate_result_pairs],
        "unexpected_result_case_seed_pairs": [list(pair) for pair in unexpected_result_pairs],
        "missing_result_case_seed_pairs": [list(pair) for pair in missing_result_pairs],
        "fully_auditable_diagnostic_rows": fully_auditable_rows,
        "row_failures": row_failures,
        "row_issue_code_counts": dict(sorted(row_issue_codes.items())),
        "json_markdown_pair_failures": len(report["pair_issues"]),
        "exact_fixed_plan_coverage": not missing_planned_pairs and not unexpected_planned_pairs and not duplicate_planned_pairs,
        "exact_result_coverage": not missing_result_pairs and not unexpected_result_pairs and not duplicate_result_pairs,
    }
    report["row_audits"] = all_rows
    report["issues"].extend(
        _issue(
            "row_check_failure",
            "one or more rows failed a diagnostic evidence check",
            issue_code=code,
            count=count,
        )
        for code, count in sorted(row_issue_codes.items())
    )

    structurally_clean = not (
        report["issues"]
        or report["invalid_json_reports"]
        or report["orphan_markdown_reports"]
        or report["pair_issues"]
    )
    complete = structurally_clean and report["coverage"]["exact_fixed_plan_coverage"] and report["coverage"]["exact_result_coverage"] and row_failures == 0
    report["status"] = "complete_diagnostic_rollup" if complete else "incomplete_diagnostic_rollup"
    return report


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode("utf-8") + b"\n"


def _exclusive_write(path: Path, content: bytes) -> None:
    candidate = _absolute_path(path, "output")
    candidate.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(candidate, flags, 0o644)
    except OSError as error:
        raise AuditError(f"cannot create output {candidate}: {error}") from error
    try:
        offset = 0
        while offset < len(content):
            offset += os.write(descriptor, content[offset:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _format_pairs(pairs: Sequence[Sequence[Any]], limit: int = 8) -> str:
    values = [f"{pair[0]}/seed{pair[1]}" for pair in pairs[:limit]]
    if len(pairs) > limit:
        values.append(f"… (+{len(pairs) - limit})")
    return ", ".join(values) if values else "—"


def render_markdown(report: Mapping[str, Any]) -> str:
    coverage = report["coverage"]
    lines = [
        "# F3 MLP hidden16 current-manifest diagnostic rollup audit",
        "",
        f"- 状态：`{report['status']}`",
        f"- 固定计划：`{report['fixed_plan']['case_count']} cases × seeds {', '.join(str(seed) for seed in report['fixed_plan']['seeds'])}` = `{report['fixed_plan']['expected_case_seed_count']}` pairs",
        f"- JSON/Markdown batch 对：`{coverage['batch_reports_observed']}`；pair failures：`{coverage['json_markdown_pair_failures']}`",
        f"- 计划覆盖：`{coverage['unique_planned_case_seed_pairs']}/{coverage['expected_case_seed_count']}`；结果覆盖：`{coverage['unique_result_case_seed_pairs']}/{coverage['expected_case_seed_count']}`",
        f"- fully auditable rows：`{coverage['fully_auditable_diagnostic_rows']}`；row failures：`{coverage['row_failures']}`",
        "- 所有聚合结果固定 `diagnostic_only=true`、formal/T1/T2/qualification=`false`、`credit=0`",
        "",
        "## Uniqueness and gaps",
        "",
        f"- duplicate batch IDs：`{len(coverage['duplicate_batch_ids'])}`",
        f"- duplicate planned case/seed：`{len(coverage['duplicate_planned_case_seed_pairs'])}`",
        f"- duplicate result case/seed：`{len(coverage['duplicate_result_case_seed_pairs'])}`",
        f"- missing planned：`{_format_pairs(coverage['missing_planned_case_seed_pairs'])}`",
        f"- missing result：`{_format_pairs(coverage['missing_result_case_seed_pairs'])}`",
        f"- unexpected planned：`{_format_pairs(coverage['unexpected_planned_case_seed_pairs'])}`",
        f"- unexpected result：`{_format_pairs(coverage['unexpected_result_case_seed_pairs'])}`",
        "",
        "## Batch reports",
        "",
        "| JSON | Markdown | batch | status | rows | issues |",
        "|---|---|---|---|---:|---:|",
    ]
    for batch in report["batches"]:
        lines.append(
            f"| `{batch['json_report']}` | `{batch['markdown_report'] or '—'}` | `{batch['batch_id']}` | `{batch['status']}` | {len(batch['rows'])} | {len(batch['issues'])} |"
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "本审计器只读取目标 batch JSON/Markdown 报告；不打开 HDF5、checkpoint、嵌入式 receipt，不接触进程，不修改 formal registry、ledger、denominator、gate 或 PLAN。缺失 process/terminal receipt 的行保持 diagnostic zero-credit，不能被聚合器晋级为 formal evidence。",
            "",
        ]
    )
    return "\n".join(lines)


def validate_audit_report(report: Mapping[str, Any]) -> None:
    if report.get("schema") != SCHEMA:
        raise AuditError("audit report schema mismatch")
    if report.get("report_id") != REPORT_ID:
        raise AuditError("audit report_id mismatch")
    if report.get("status") not in {"complete_diagnostic_rollup", "incomplete_diagnostic_rollup"}:
        raise AuditError("audit report status is invalid")
    zero_ok, zero_issues = _zero_credit_check(report, "audit report")
    if not zero_ok:
        raise AuditError(f"audit report is not zero-credit: {zero_issues[0]['message']}")
    boundary = report.get("input_boundary")
    if not isinstance(boundary, Mapping) or any(boundary.get(key) is not expected for key, expected in {
        "hdf5_opened": False,
        "checkpoint_opened": False,
        "embedded_receipts_opened": False,
        "processes_contacted": False,
        "registry_read": False,
        "ledger_read": False,
        "denominator_read": False,
        "gate_read": False,
        "plan_read": False,
    }.items()):
        raise AuditError("audit input boundary is not read-only")
    side_effects = report.get("side_effects")
    if not isinstance(side_effects, Mapping) or any(value != 0 for value in side_effects.values()):
        raise AuditError("audit side effects are not all zero")
    fixed_plan = report.get("fixed_plan")
    if not isinstance(fixed_plan, Mapping) or fixed_plan.get("expected_case_seed_count") != len(EXPECTED_PAIRS):
        raise AuditError("audit fixed plan is not 96 case/seed pairs")
    coverage = report.get("coverage")
    if not isinstance(coverage, Mapping):
        raise AuditError("audit coverage is missing")
    if coverage.get("expected_case_seed_count") != len(EXPECTED_PAIRS):
        raise AuditError("audit coverage target is not 96")


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports-dir", type=Path, default=LAB_ROOT / "reports")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--markdown-output", type=Path, default=None)
    parser.add_argument("--verify-report", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        if args.verify_report is not None:
            payload, _ = _read_json_report(_absolute_path(args.verify_report, "verify_report"))
            validate_audit_report(payload)
            print(json.dumps({"status": "verified", "report_id": payload["report_id"]}, ensure_ascii=False, sort_keys=True))
            return 0

        report = build_audit(args.reports_dir)
        if args.output is not None:
            _exclusive_write(args.output, _json_bytes(report))
        if args.markdown_output is not None:
            _exclusive_write(args.markdown_output, render_markdown(report).encode("utf-8"))
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "batch_reports": report["coverage"]["batch_reports_observed"],
                    "planned_pairs": report["coverage"]["unique_planned_case_seed_pairs"],
                    "result_pairs": report["coverage"]["unique_result_case_seed_pairs"],
                    "row_failures": report["coverage"]["row_failures"],
                    "credit": report["credit"],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0 if report["status"] == "complete_diagnostic_rollup" else 1
    except (AuditError, OSError, ValueError, RecursionError) as error:
        print(json.dumps({"schema": SCHEMA, "status": "blocked_fail_closed", "error": f"{type(error).__name__}: {error}", **ZERO_CREDIT}, ensure_ascii=False, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
