#!/usr/bin/env python3
"""Audit the bounded join from formal release admission to observed T1 rows.

The existing T1 evidence intake projects 432 fixed F3/F4 model-case-run rows,
while the formal release/root adapter describes the nine model/seed runs.  A
small aggregate boundary was still missing: it must prove that the two
identities describe the same fixed target denominator and that every formal
run has exactly 32 F3 plus 16 F4 target rows.

This module only reads bounded JSON metadata and computes that identity join.
It does not copy the existing row inventory, reopen HDF5/checkpoints or
trajectories, verify a cryptographic root, admit an external scheduler, start
training, or mutate Core state.  The join is deliberately non-authorizing:
even a synthetic shape-complete fixture remains blocked with zero credit.
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Mapping, Sequence
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any


LAB_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = LAB_ROOT / (
    "campaigns/core-v1/cfd/t1-evidence/"
    "formal-release-observed-case-run-join-v1.json"
)
DEFAULT_REPORT = LAB_ROOT / (
    "reports/T1-FORMAL-RELEASE-OBSERVED-CASE-RUN-JOIN-GAP-V1-2026-09-29.json"
)
DEFAULT_MARKDOWN_REPORT = DEFAULT_REPORT.with_suffix(".zh-CN.md")

CONTRACT_SCHEMA = "core.t1.formal_release_observed_case_run_join_contract.v1"
REPORT_SCHEMA = "core.t1.formal_release_observed_case_run_join_gap.v1"
T1_SCHEMA = "core.t1.observed_model_case_run.evidence_binding.v1"
FORMAL_SCHEMA = "core.formal_training_release_root_admission_report.v1"

MODELS = ("graph_raw", "graph_residual", "mlp")
SEEDS = (17, 29, 43)
FAMILIES = ("F3", "F4")
F3_CASE_COUNT = 32
F4_EVALUATION_CASE_COUNT = 16
ROWS_PER_RUN = F3_CASE_COUNT + F4_EVALUATION_CASE_COUNT
EXPECTED_ROWS = ROWS_PER_RUN * len(MODELS) * len(SEEDS)
EXPECTED_FAMILY_COUNTS = {
    "F3": F3_CASE_COUNT * len(MODELS) * len(SEEDS),
    "F4": F4_EVALUATION_CASE_COUNT * len(MODELS) * len(SEEDS),
}
RUN_IDS = tuple(f"{model}-seed{seed}" for model in MODELS for seed in SEEDS)
MAX_JSON_BYTES = 2 * 1024 * 1024


class JoinError(ValueError):
    """Malformed input is never partially admitted by this aggregate audit."""


def _fail(message: str) -> None:
    raise JoinError(f"fail-closed: {message}")


def _reject_constant(token: str) -> None:
    _fail(f"non-finite JSON constant is not allowed: {token}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        _fail(f"{name} must be a non-empty string")
    return value


def _integer(value: Any, name: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        _fail(f"{name} must be an integer >= {minimum}")
    return value


def _boolean(value: Any, name: str) -> bool:
    if type(value) is not bool:
        _fail(f"{name} must be boolean")
    return value


def _object(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{name} must be an object")
    return value


def _exact(value: Mapping[str, Any], key: str, expected: Any, name: str) -> None:
    if key not in value:
        _fail(f"{name}.{key} is missing")
    actual = value[key]
    if type(expected) is bool and type(actual) is not bool:
        _fail(f"{name}.{key} must be boolean")
    if type(expected) is int and type(actual) is not int:
        _fail(f"{name}.{key} must be integer")
    if actual != expected:
        _fail(f"{name}.{key} must be {expected!r}")


def _resolve_input(root: Path, value: str | Path, name: str) -> Path:
    raw = os.fspath(value)
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        _fail(f"{name} must be a non-empty path")
    candidate = Path(raw)
    if ".." in candidate.parts:
        _fail(f"{name} contains a lexical parent alias")
    if candidate.is_absolute():
        path = candidate
        try:
            path.relative_to(root)
        except ValueError:
            _fail(f"{name} must remain inside the lab root")
    else:
        path = root / candidate
    current = Path(root.anchor or os.curdir)
    components = path.parts[1:] if path.is_absolute() else path.parts
    for component in components:
        current /= component
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            break
        if stat.S_ISLNK(info.st_mode):
            _fail(f"{name} contains a symlink component: {current}")
    return path


def _read_json(
    root: Path,
    value: str | Path,
    *,
    name: str,
    max_bytes: int = MAX_JSON_BYTES,
) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _resolve_input(root, value, name)
    if path.suffix.lower() != ".json":
        _fail(f"{name} must be a JSON file")
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
    except OSError as error:
        _fail(f"{name} cannot be opened: {error}")
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            _fail(f"{name} is not a regular file")
        if before.st_size > max_bytes:
            _fail(f"{name} exceeds the bounded JSON limit")
        payload = os.read(descriptor, before.st_size + 1)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    before_signature = (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    after_signature = (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )
    if before_signature != after_signature or len(payload) != before.st_size:
        _fail(f"{name} changed while being read")
    try:
        parsed = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        _fail(f"{name} is not strict JSON: {error}")
    if not isinstance(parsed, dict):
        _fail(f"{name} must contain a JSON object")
    return parsed, {
        "path": path.relative_to(root).as_posix(),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _input_ref(meta: Mapping[str, Any], role: str) -> dict[str, Any]:
    return {
        "role": role,
        "path": meta["path"],
        "bytes": meta["bytes"],
        "sha256": meta["sha256"],
    }


def _reference_matches(reference: Any, actual: Mapping[str, Any]) -> bool:
    return (
        isinstance(reference, Mapping)
        and reference.get("path") == actual.get("path")
        and reference.get("bytes") == actual.get("bytes")
        and reference.get("sha256") == actual.get("sha256")
    )


def _load_contract(root: Path, contract_path: str | Path) -> tuple[dict[str, Any], dict[str, Any]]:
    contract, meta = _read_json(root, contract_path, name="aggregate join contract")
    _exact(contract, "schema", CONTRACT_SCHEMA, "contract")
    _exact(contract, "version", 1, "contract")
    _exact(contract, "contract_id", "formal-release-observed-case-run-join-v1", "contract")
    input_reports = _object(contract.get("input_reports"), "contract.input_reports")
    expected_roles = {"t1_observed_case_run_binding", "formal_release_root_admission"}
    if set(input_reports) != expected_roles:
        _fail("contract.input_reports must contain the fixed two report roles")
    for role, schema, report_id in (
        (
            "t1_observed_case_run_binding",
            T1_SCHEMA,
            "t1-observed-model-case-run-evidence-binding-v1",
        ),
        (
            "formal_release_root_admission",
            FORMAL_SCHEMA,
            "core-formal-training-release-root-admission-gap-v1",
        ),
    ):
        entry = _object(input_reports.get(role), f"contract.input_reports.{role}")
        _exact(entry, "schema", schema, f"contract.input_reports.{role}")
        _exact(entry, "report_id", report_id, f"contract.input_reports.{role}")
        _string(entry.get("path"), f"contract.input_reports.{role}.path")
    scope = _object(contract.get("fixed_scope"), "contract.fixed_scope")
    _exact(scope, "models", list(MODELS), "contract.fixed_scope")
    _exact(scope, "seeds", list(SEEDS), "contract.fixed_scope")
    _exact(scope, "families", list(FAMILIES), "contract.fixed_scope")
    _exact(scope, "f3_case_count", F3_CASE_COUNT, "contract.fixed_scope")
    _exact(scope, "f4_evaluation_case_count", F4_EVALUATION_CASE_COUNT, "contract.fixed_scope")
    _exact(scope, "required_case_runs", EXPECTED_ROWS, "contract.fixed_scope")
    policy = _object(contract.get("policy"), "contract.policy")
    for key in (
        "bounded_json_only",
        "fail_closed",
        "external_authority_required_for_counting",
        "no_inventory_copy",
        "no_core_state_writes",
    ):
        _exact(policy, key, True, "contract.policy")
    return contract, meta


def _load_input_reports(
    root: Path, contract: Mapping[str, Any]
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    input_reports = _object(contract.get("input_reports"), "contract.input_reports")
    payloads: dict[str, dict[str, Any]] = {}
    references: dict[str, dict[str, Any]] = {}
    for role in ("t1_observed_case_run_binding", "formal_release_root_admission"):
        entry = _object(input_reports.get(role), f"contract.input_reports.{role}")
        payload, meta = _read_json(
            root,
            _string(entry.get("path"), f"contract.input_reports.{role}.path"),
            name=role,
        )
        _exact(payload, "schema", entry["schema"], role)
        _exact(payload, "report_id", entry["report_id"], role)
        payloads[role] = payload
        references[role] = _input_ref(meta, role)
    return payloads, references


def _expected_run_id(model: Any, seed: Any, name: str) -> str:
    _string(model, f"{name}.model_kind")
    _integer(seed, f"{name}.seed", minimum=1)
    return f"{model}-seed{seed}"


def _validate_t1_report(payload: Mapping[str, Any]) -> dict[str, Any]:
    _exact(payload, "schema", T1_SCHEMA, "T1 report")
    _exact(payload, "report_id", "t1-observed-model-case-run-evidence-binding-v1", "T1 report")
    _exact(payload, "status", "typed_evidence_gap_fail_closed", "T1 report")
    _exact(payload, "fail_closed", True, "T1 report")
    _exact(payload, "observed_case_runs", 0, "T1 report")
    _exact(payload, "required_case_runs", EXPECTED_ROWS, "T1 report")
    _exact(payload, "missing_case_runs", EXPECTED_ROWS, "T1 report")
    _exact(payload, "T1_numerical", False, "T1 report")
    _exact(payload, "credit", 0, "T1 report")
    formal_run_ids = payload.get("formal_run_ids")
    if formal_run_ids != sorted(RUN_IDS):
        _fail("T1 report formal_run_ids do not equal the fixed nine-run scope")
    projection = _object(payload.get("fixed_t1_projection"), "T1 report.fixed_t1_projection")
    _exact(projection, "expected_row_count", EXPECTED_ROWS, "T1 report.fixed_t1_projection")
    rows = projection.get("rows")
    if not isinstance(rows, list) or len(rows) != EXPECTED_ROWS:
        _fail("T1 report fixed projection must contain exactly 432 rows")

    family_counts: Counter[str] = Counter()
    run_counts: Counter[str] = Counter()
    family_run_counts: Counter[tuple[str, str]] = Counter()
    seen: set[tuple[str, str, str, str, int]] = set()
    for index, raw_row in enumerate(rows):
        row = _object(raw_row, f"T1 report.fixed_t1_projection.rows[{index}]")
        family = _string(row.get("family"), f"T1 row {index}.family")
        scope_id = _string(row.get("scope_id"), f"T1 row {index}.scope_id")
        case_id = _string(row.get("case_id"), f"T1 row {index}.case_id")
        model = _string(row.get("model_kind"), f"T1 row {index}.model_kind")
        seed = _integer(row.get("seed"), f"T1 row {index}.seed", minimum=1)
        if family not in FAMILIES:
            _fail(f"T1 row {index} has an unknown family")
        if model not in MODELS or seed not in SEEDS:
            _fail(f"T1 row {index} is outside the fixed model/seed scope")
        formal_run_id = _string(row.get("formal_run_id"), f"T1 row {index}.formal_run_id")
        expected_run_id = _expected_run_id(model, seed, f"T1 row {index}")
        if formal_run_id != expected_run_id:
            _fail(f"T1 row {index} formal_run_id is not derived from model/seed")
        key = (family, scope_id, case_id, model, seed)
        if key in seen:
            _fail(f"T1 projection repeats row identity at index {index}")
        seen.add(key)
        family_counts[family] += 1
        run_counts[formal_run_id] += 1
        family_run_counts[(family, formal_run_id)] += 1

    if dict(family_counts) != EXPECTED_FAMILY_COUNTS:
        _fail(f"T1 projection family counts drift: {dict(family_counts)!r}")
    if dict(run_counts) != {run_id: ROWS_PER_RUN for run_id in RUN_IDS}:
        _fail("T1 projection does not give every formal run exactly 48 target rows")
    expected_family_run = {
        (family, run_id): (F3_CASE_COUNT if family == "F3" else F4_EVALUATION_CASE_COUNT)
        for run_id in RUN_IDS
        for family in FAMILIES
    }
    if dict(family_run_counts) != expected_family_run:
        _fail("T1 projection does not give every run the fixed F3/F4 row split")
    return {
        "schema": payload["schema"],
        "report_id": payload["report_id"],
        "status": payload["status"],
        "fail_closed": payload["fail_closed"],
        "observed_case_runs": payload["observed_case_runs"],
        "required_case_runs": payload["required_case_runs"],
        "missing_case_runs": payload["missing_case_runs"],
        "T1_numerical": payload["T1_numerical"],
        "credit": payload["credit"],
        "formal_run_ids": list(sorted(RUN_IDS)),
        "projection": {
            "rows_checked": len(rows),
            "unique_row_identities": len(seen),
            "duplicate_row_identities": 0,
            "identity_valid": True,
            "family_counts": dict(sorted(family_counts.items())),
            "formal_run_counts": dict((run_id, run_counts[run_id]) for run_id in RUN_IDS),
            "formal_run_family_counts": {
                run_id: {
                    "F3": family_run_counts[("F3", run_id)],
                    "F4": family_run_counts[("F4", run_id)],
                }
                for run_id in RUN_IDS
            },
        },
    }


def _validate_formal_report(payload: Mapping[str, Any]) -> dict[str, Any]:
    _exact(payload, "schema", FORMAL_SCHEMA, "formal release report")
    _exact(payload, "report_id", "core-formal-training-release-root-admission-gap-v1", "formal release report")
    scope = _object(payload.get("scope"), "formal release report.scope")
    _exact(scope, "models", list(MODELS), "formal release report.scope")
    _exact(scope, "seeds", list(SEEDS), "formal release report.scope")
    _exact(scope, "run_count", len(RUN_IDS), "formal release report.scope")
    run_ids = scope.get("run_ids")
    if run_ids != list(RUN_IDS):
        _fail("formal release report scope run_ids drift")
    decision = _object(payload.get("decision"), "formal release report.decision")
    _exact(decision, "launch_allowed", False, "formal release report.decision")
    _exact(decision, "formal_eligible", False, "formal release report.decision")
    _exact(decision, "qualification_credit", 0, "formal release report.decision")
    _exact(decision, "credit", 0, "formal release report.decision")
    _exact(decision, "non_authorizing_adapter", True, "formal release report.decision")
    constraints = _object(payload.get("execution_constraints"), "formal release report.execution_constraints")
    for key, expected in (
        ("read_only", True),
        ("bounded_json_only", True),
        ("hdf5_opened", False),
        ("checkpoint_opened", False),
        ("training_started", False),
        ("gpu_started", False),
        ("worker_started", False),
        ("queue_submitted", False),
        ("registry_written", False),
        ("ledger_written", False),
        ("denominator_written", False),
        ("gate_written", False),
        ("completion_written", False),
        ("plan_written", False),
        ("historical_receipt_written", False),
    ):
        _exact(constraints, key, expected, "formal release report.execution_constraints")
    observations = _object(payload.get("observations"), "formal release report.observations")
    trusted_root = _object(observations.get("trusted_root"), "formal release report.observations.trusted_root")
    terminal = _object(observations.get("terminal_evidence"), "formal release report.observations.terminal_evidence")
    blockers = payload.get("missing_blockers")
    if not isinstance(blockers, list) or not blockers or any(not isinstance(item, str) for item in blockers):
        _fail("formal release report missing_blockers must be a non-empty string list")
    return {
        "schema": payload["schema"],
        "report_id": payload["report_id"],
        "scope": {
            "models": list(MODELS),
            "seeds": list(SEEDS),
            "run_count": len(RUN_IDS),
            "run_ids": list(RUN_IDS),
        },
        "decision": {
            "status": decision.get("status"),
            "launch_allowed": decision["launch_allowed"],
            "formal_eligible": decision["formal_eligible"],
            "credit": decision["credit"],
            "qualification_credit": decision["qualification_credit"],
            "non_authorizing_adapter": decision["non_authorizing_adapter"],
        },
        "root_authentication_integrated": trusted_root.get("trusted_root_authenticated") is True,
        "root_admission_ready": trusted_root.get("admission_ready") is True,
        "terminal_evidence_complete": terminal.get("complete") is True,
        "missing_blockers": list(dict.fromkeys(blockers)),
    }


def build_report(
    root: str | Path = LAB_ROOT,
    contract: str | Path = DEFAULT_CONTRACT,
    *,
    observed_at_utc: str = "2026-09-29T00:00:00Z",
) -> dict[str, Any]:
    root_path = Path(root).expanduser().resolve()
    contract_payload, contract_meta = _load_contract(root_path, contract)
    payloads, references = _load_input_reports(root_path, contract_payload)
    t1 = _validate_t1_report(payloads["t1_observed_case_run_binding"])
    formal = _validate_formal_report(payloads["formal_release_root_admission"])
    release_run_ids = set(formal["scope"]["run_ids"])
    t1_run_ids = set(t1["formal_run_ids"])
    if release_run_ids != t1_run_ids:
        _fail("formal release and T1 projection run identity sets do not match")

    projection = t1["projection"]
    mapping = {
        "formal_run_ids_exact": release_run_ids == set(RUN_IDS),
        "all_formal_runs_have_target_rows": all(
            projection["formal_run_counts"].get(run_id) == ROWS_PER_RUN
            for run_id in RUN_IDS
        ),
        "f3_rows_per_formal_run_exact": all(
            projection["formal_run_family_counts"][run_id]["F3"] == F3_CASE_COUNT
            for run_id in RUN_IDS
        ),
        "f4_rows_per_formal_run_exact": all(
            projection["formal_run_family_counts"][run_id]["F4"] == F4_EVALUATION_CASE_COUNT
            for run_id in RUN_IDS
        ),
        "target_denominator_exact": projection["rows_checked"] == EXPECTED_ROWS,
        "identity_join_valid": projection["identity_valid"] and release_run_ids == t1_run_ids,
    }
    join_valid = all(mapping.values())
    blockers = []
    if not join_valid:
        blockers.append("FIXED_RELEASE_TO_T1_IDENTITY_JOIN_INVALID")
    if not formal["decision"]["launch_allowed"] or not formal["decision"]["formal_eligible"]:
        blockers.append("FORMAL_RELEASE_ROOT_ADMISSION_NOT_READY")
    if not formal["root_authentication_integrated"]:
        blockers.append("EXTERNAL_ROOT_AUTHORITY_NOT_CONSUMABLE")
    if not formal["terminal_evidence_complete"]:
        blockers.append("FORMAL_TERMINAL_EVIDENCE_NOT_COMPLETE")
    if t1["observed_case_runs"] != EXPECTED_ROWS:
        blockers.append("NO_OBSERVED_T1_MODEL_CASE_RUN_RECEIPTS")
    blockers.append("AGGREGATE_JOIN_IS_NON_AUTHORIZING")
    blockers = list(dict.fromkeys(blockers))

    return {
        "schema": REPORT_SCHEMA,
        "contract_schema": CONTRACT_SCHEMA,
        "report_id": "t1-formal-release-observed-case-run-join-gap-v1",
        "observed_at_utc": observed_at_utc,
        "purpose": (
            "bounded aggregate join of the fixed formal model/seed release scope "
            "to the existing F3/F4 T1 target projection"
        ),
        "scope": {
            "families": list(FAMILIES),
            "models": list(MODELS),
            "seeds": list(SEEDS),
            "f3_case_count": F3_CASE_COUNT,
            "f4_evaluation_case_count": F4_EVALUATION_CASE_COUNT,
            "rows_per_formal_run": ROWS_PER_RUN,
            "required_case_runs": EXPECTED_ROWS,
        },
        "input_paths": {
            role: _object(contract_payload["input_reports"][role], f"contract.input_reports.{role}")["path"]
            for role in ("t1_observed_case_run_binding", "formal_release_root_admission")
        },
        "inputs": {
            role: {
                "reference": references[role],
                "schema": payloads[role]["schema"],
                "report_id": payloads[role]["report_id"],
            }
            for role in ("t1_observed_case_run_binding", "formal_release_root_admission")
        },
        "observations": {
            "t1_observed_case_run_binding": t1,
            "formal_release_root_admission": formal,
        },
        "aggregate_join": {
            "identity_mapping": mapping,
            "join_valid": join_valid,
            "target_denominator": {
                "required_case_runs": EXPECTED_ROWS,
                "family_counts": dict(sorted(EXPECTED_FAMILY_COUNTS.items())),
                "rows_per_formal_run": ROWS_PER_RUN,
                "f3_rows_per_formal_run": F3_CASE_COUNT,
                "f4_rows_per_formal_run": F4_EVALUATION_CASE_COUNT,
            },
            "formal_run_counts": projection["formal_run_counts"],
            "formal_run_family_counts": projection["formal_run_family_counts"],
            "observed_case_runs": 0,
            "missing_case_runs": EXPECTED_ROWS,
            "inventory_copied": False,
        },
        "decision": {
            "status": "blocked_fail_closed",
            "launch_allowed": False,
            "formal_eligible": False,
            "T1_numerical": False,
            "qualification_credit": 0,
            "credit": 0,
            "non_authorizing_adapter": True,
            "reason": (
                "identity shape is auditable, but formal release/root admission and "
                "authority-bound observed terminal receipts are not admitted"
            ),
        },
        "missing_blockers": blockers,
        "execution_constraints": {
            "read_only": True,
            "bounded_json_only": True,
            "hdf5_opened": False,
            "checkpoint_opened": False,
            "trajectory_opened": False,
            "trainer_imported": False,
            "training_started": False,
            "gpu_started": False,
            "worker_started": False,
            "queue_submitted": False,
            "registry_written": False,
            "ledger_written": False,
            "denominator_written": False,
            "gate_written": False,
            "completion_written": False,
            "plan_written": False,
            "historical_receipt_written": False,
        },
        "protected_state": {
            "registry_mutations": 0,
            "ledger_mutations": 0,
            "denominator_mutations": 0,
            "gate_mutations": 0,
            "completion_mutations": 0,
            "plan_mutations": 0,
        },
        "policy": {
            "subagent_model": "gpt-5.6-luna",
            "reasoning_effort": "max",
            "parallel": True,
            "coarse_to_fine": True,
            "external_authority_required_for_counting": True,
            "caller_claims_cannot_mint_trust": True,
        },
        "input_bindings": [
            _input_ref(contract_meta, "aggregate join campaign contract"),
            references["t1_observed_case_run_binding"],
            references["formal_release_root_admission"],
        ],
        "interpretation": (
            "The aggregate identity join closes only the metadata mapping gap. "
            "It does not promote planned rows to observed T1 evidence, does not "
            "admit formal training, and does not issue credit."
        ),
    }


def _reference_error(reference: Any, *, root: Path, label: str) -> str | None:
    if not isinstance(reference, Mapping):
        return f"{label} reference is not an object"
    try:
        _payload, actual = _read_json(root, reference.get("path", ""), name=label)
    except (JoinError, OSError, TypeError, ValueError) as error:
        return f"{label} reference cannot be read: {error}"
    if not _reference_matches(reference, actual):
        return f"{label} reference digest or byte count mismatch"
    return None


def validate_report(report: Mapping[str, Any], root: str | Path = LAB_ROOT) -> list[str]:
    errors: list[str] = []
    if not isinstance(report, Mapping):
        return ["report root is not an object"]
    if report.get("schema") != REPORT_SCHEMA:
        errors.append("schema mismatch")
    if report.get("contract_schema") != CONTRACT_SCHEMA:
        errors.append("contract_schema mismatch")
    if report.get("scope") != {
        "families": list(FAMILIES),
        "models": list(MODELS),
        "seeds": list(SEEDS),
        "f3_case_count": F3_CASE_COUNT,
        "f4_evaluation_case_count": F4_EVALUATION_CASE_COUNT,
        "rows_per_formal_run": ROWS_PER_RUN,
        "required_case_runs": EXPECTED_ROWS,
    }:
        errors.append("fixed scope mismatch")
    decision = _object(report.get("decision"), "report.decision") if isinstance(report.get("decision"), Mapping) else {}
    for key, expected in (
        ("launch_allowed", False),
        ("formal_eligible", False),
        ("T1_numerical", False),
        ("qualification_credit", 0),
        ("credit", 0),
        ("non_authorizing_adapter", True),
    ):
        if decision.get(key) != expected:
            errors.append(f"decision {key} is not fail-closed")
    join = report.get("aggregate_join")
    if not isinstance(join, Mapping):
        errors.append("aggregate_join missing")
    else:
        if join.get("join_valid") is not True:
            errors.append("aggregate identity join is not valid")
        for key, expected in (
            ("observed_case_runs", 0),
            ("missing_case_runs", EXPECTED_ROWS),
            ("inventory_copied", False),
        ):
            if join.get(key) != expected:
                errors.append(f"aggregate_join {key} drift")
    constraints = report.get("execution_constraints")
    if not isinstance(constraints, Mapping):
        errors.append("execution_constraints missing")
    else:
        for key, expected in (
            ("read_only", True),
            ("bounded_json_only", True),
            ("hdf5_opened", False),
            ("checkpoint_opened", False),
            ("trajectory_opened", False),
            ("training_started", False),
            ("gpu_started", False),
            ("worker_started", False),
            ("queue_submitted", False),
            ("registry_written", False),
            ("ledger_written", False),
            ("denominator_written", False),
            ("gate_written", False),
            ("completion_written", False),
            ("plan_written", False),
            ("historical_receipt_written", False),
        ):
            if constraints.get(key) != expected:
                errors.append(f"execution constraint {key} is not closed")
    protected = report.get("protected_state")
    if not isinstance(protected, Mapping):
        errors.append("protected_state missing")
    else:
        for key in (
            "registry_mutations",
            "ledger_mutations",
            "denominator_mutations",
            "gate_mutations",
            "completion_mutations",
            "plan_mutations",
        ):
            if protected.get(key) != 0:
                errors.append(f"protected state {key} is not zero")
    blockers = report.get("missing_blockers")
    if not isinstance(blockers, list) or not blockers or len(blockers) != len(set(blockers)):
        errors.append("missing_blockers must be a unique non-empty list")
    inputs = report.get("inputs")
    if not isinstance(inputs, Mapping) or set(inputs) != {
        "t1_observed_case_run_binding",
        "formal_release_root_admission",
    }:
        errors.append("inputs do not contain the fixed two roles")
    else:
        root_path = Path(root).expanduser().resolve()
        for role in inputs:
            entry = inputs[role]
            reference = entry.get("reference") if isinstance(entry, Mapping) else None
            error = _reference_error(reference, root=root_path, label=role)
            if error:
                errors.append(error)
    return errors


def _write_new(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0),
            0o644,
        )
    except OSError as error:
        raise JoinError(f"refusing to overwrite output {path}: {error}") from error
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def render_markdown(report: Mapping[str, Any]) -> str:
    join = _object(report["aggregate_join"], "report.aggregate_join")
    target = _object(join["target_denominator"], "report.aggregate_join.target_denominator")
    lines = [
        "# T1 formal release → observed case-run aggregate join gap",
        "",
        f"- 状态：`{report['decision']['status']}`；join identity valid：`{join['join_valid']}`",
        f"- 固定目标分母：`{join['observed_case_runs']}/{target['required_case_runs']}` observed；缺口：`{join['missing_case_runs']}`",
        "- formal：`false`；T1：`false`；credit：`0`；本报告不授权执行或计数。",
        "",
        "## 已闭合的元数据连接",
        "",
        f"- 每个 formal model×seed run：`{target['f3_rows_per_formal_run']}` 个 F3 + `{target['f4_rows_per_formal_run']}` 个 F4 = `{target['rows_per_formal_run']}` 行。",
        f"- F3/F4 总目标行：`{target['family_counts']['F3']}` / `{target['family_counts']['F4']}`；不复制既有 432 行 inventory。",
        "- formal release 的 9 个 run ID 与 T1 projection 的 model/seed identity 一一对应。",
        "",
        "## 仍然阻塞",
        "",
    ]
    for blocker in report["missing_blockers"]:
        lines.append(f"- `{blocker}`")
    lines.extend(
        [
            "",
            "## 边界",
            "",
            "只读取有界 JSON 元数据；没有打开/重哈希 HDF5、checkpoint 或 trajectory，没有启动 trainer、solver、worker、GPU、queue，也没有修改 registry、ledger、denominator、gate、completion 或 PLAN。外部 scheduler/root authority 与 authority-bound terminal receipt 仍未被消费。",
            "",
        ]
    )
    return "\n".join(lines)


def write_report(
    report: Mapping[str, Any],
    output: str | Path = DEFAULT_REPORT,
    markdown_output: str | Path = DEFAULT_MARKDOWN_REPORT,
) -> tuple[Path, Path]:
    errors = validate_report(report, LAB_ROOT)
    if errors:
        raise JoinError("report validation failed: " + "; ".join(errors))
    json_path = Path(output)
    markdown_path = Path(markdown_output)
    _write_new(
        json_path,
        (json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    _write_new(markdown_path, render_markdown(report).encode("utf-8"))
    return json_path, markdown_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_REPORT)
    args = parser.parse_args(argv)
    report = build_report(LAB_ROOT, args.contract)
    output, markdown = write_report(report, args.output, args.markdown_output)
    print(
        json.dumps(
            {
                "output": str(output),
                "markdown": str(markdown),
                "required_case_runs": EXPECTED_ROWS,
                "observed_case_runs": 0,
                "credit": 0,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
