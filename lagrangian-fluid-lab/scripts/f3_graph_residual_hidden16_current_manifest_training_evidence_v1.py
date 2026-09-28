#!/usr/bin/env python3
"""Intake current-manifest F3 graph_residual/hidden16 training evidence.

This is an additive, non-authorizing intake boundary for the three current v3
training receipts.  It reads one bounded canonical manifest JSON and at most
three bounded training-receipt JSON files.  Checkpoints, HDF5, trajectory,
evaluation, progress, solver, and GPU artifacts are never opened, stat-ed, or
hashed.  The residual-specific evidence rules are reused from the existing
current-manifest case-matrix validator; this report intentionally does not
plan or launch the 32 x 3 rollout matrix.

An accepted report is still diagnostic-only and zero-credit.  Missing,
running, partial, drifting, path-aliased, unknown-field, or non-zero-authority
inputs remain ``blocked_fail_closed``.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any


LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts import f3_graph_residual_hidden16_current_manifest_case_matrix_v1 as matrix


SEEDS = tuple(matrix.SEEDS)
MODEL = matrix.MODEL
HIDDEN = matrix.HIDDEN
UPDATES = matrix.UPDATES
PARAMETER_COUNT = matrix.PARAMETER_COUNT
NORMALIZATION_TRANSITIONS = matrix.NORMALIZATION_TRANSITIONS
PRIOR_ROWS = matrix.PRIOR_ROWS
TRAINING_SCHEMA = matrix.TRAINING_SCHEMA
CHECKPOINT_SCHEMA = matrix.CHECKPOINT_SCHEMA
EVIDENCE_SCHEMA = matrix.EVIDENCE_SCHEMA
INITIALIZATION_SCHEMA = matrix.INITIALIZATION_SCHEMA
NORMALIZATION_SCHEMA = matrix.NORMALIZATION_SCHEMA
PRIOR_SCHEMA = matrix.PRIOR_SCHEMA
SCHEMA = "core.f3.graph_residual.hidden16.current_manifest_training_evidence.v1"
REPORT_ID = "f3-graph-residual-hidden16-current-manifest-training-evidence-v1"
PLAN_DATE = "20260929"
MAX_REPORT_BYTES = 2 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

DEFAULT_MANIFEST = LAB_ROOT / "campaigns/core-v1/f3-dataset-v2.json"
DEFAULT_OUTPUT = (
    LAB_ROOT
    / "reports/F3-GRAPH-RESIDUAL-HIDDEN16-CURRENT-MANIFEST-TRAINING-EVIDENCE-2026-09-29.json"
)
DEFAULT_MARKDOWN_OUTPUT = DEFAULT_OUTPUT.with_suffix(".zh-CN.md")

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

TOP_LEVEL_KEYS = frozenset(
    {
        "checkpoint",
        "checkpoint_verified",
        "completed_updates",
        "config",
        "evidence",
        "evidence_status",
        "model_kind",
        "parameter_count",
        "run_id",
        "schema",
        "seed",
        "status",
        "diagnostic_only",
        "formal",
        "formal_eligible",
        "qualification",
        "T1_numerical",
        "T2_macro",
        "T2_path",
        "credit",
        "qualification_credit",
    }
)
CONFIG_KEYS = frozenset(matrix.STATIC_CONFIG) | {
    "manifest_sha256",
    "paired_seed",
    "run_id",
    "sampler_seed",
    "seed",
}
EVIDENCE_KEYS = frozenset({"initialization", "normalization", "residual_prior", "schema", "status"})
INITIALIZATION_KEYS = frozenset(
    {
        "constructed_before_first_update",
        "construction_update",
        "hidden",
        "model_kind",
        "parameter_count",
        "parameter_digest",
        "schema",
        "seed",
        "status",
    }
)
NORMALIZATION_KEYS = frozenset(
    {
        "available_transition_count",
        "requested_maximum_transitions",
        "schema",
        "selected_transition_count",
        "selection_policy",
        "selection_seed",
        "source_split",
        "target_reference",
    }
)
PRIOR_KEYS = frozenset(
    {
        "dv_abs_max_mps",
        "dv_abs_sum_mps",
        "dx_abs_max_m",
        "dx_abs_sum_m",
        "enabled",
        "execution_calls",
        "finite",
        "history_complete",
        "last_update",
        "rows",
        "schema",
        "semantic",
        "units",
    }
)
LAST_UPDATE_KEYS = frozenset({"case_id", "frame", "update"})
CHECKPOINT_KEYS = frozenset({"bytes", "path", "schema", "sha256", "update"})


class IntakeError(ValueError):
    """Malformed, unsafe, incomplete, drifting, or non-authorizing input."""


def _fail(message: str) -> None:
    raise IntakeError(f"fail-closed: {message}")


def _reject_unknown(value: Mapping[str, Any], allowed: frozenset[str], name: str) -> None:
    unknown = sorted(set(value) - set(allowed))
    if unknown:
        _fail(f"{name} contains unknown fields: {unknown}")


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{name} must be an object")
    return value


def _string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        _fail(f"{name} must be a non-empty string")
    return value


def _strict_int(value: Any, name: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        _fail(f"{name} must be an integer >= {minimum}")
    return value


def _sha256(value: Any, name: str) -> str:
    text = _string(value, name)
    if SHA256_RE.fullmatch(text) is None or len(set(text)) == 1 or text.startswith("0" * 48):
        _fail(f"{name} must be a non-placeholder lowercase SHA-256")
    return text


def _exact(value: Mapping[str, Any], key: str, expected: Any, name: str) -> None:
    if key not in value:
        _fail(f"{name}.{key} is missing")
    observed = value[key]
    if isinstance(expected, bool) and type(observed) is not bool:
        _fail(f"{name}.{key} must be boolean")
    if type(expected) is int and type(observed) is not int:
        _fail(f"{name}.{key} must be integer")
    if observed != expected:
        _fail(f"{name}.{key} must be {expected!r}")


def _zero_credit(value: Mapping[str, Any], name: str) -> None:
    for key in (
        "diagnostic_only",
        "formal",
        "formal_eligible",
        "qualification",
        "T1_numerical",
        "T2_macro",
        "T2_path",
    ):
        if key in value:
            _exact(value, key, ZERO_CREDIT[key], name)
    for key in ("credit", "qualification_credit"):
        if key in value:
            _exact(value, key, 0, name)


def _expected_run_id(seed: int, plan_date: str) -> str:
    return f"f3-graph_residual500-hidden16-currentmanifest-seed{seed}-{plan_date}-v3"


def _empty_source(value: Path | str | None, *, error: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": str(value) if value is not None else "<missing>",
        "exists": False,
        "opened": False,
        "bytes": None,
        "sha256": None,
        "schema": None,
    }
    if error:
        result["error"] = error
    return result


def _status_source(value: Path | str | None, status: str) -> dict[str, Any]:
    result = _empty_source(value)
    result["status_hint"] = status
    return result


def _safe_receipt_path(value: Path | str, *, seed: int, plan_date: str) -> Path:
    try:
        candidate = matrix._absolute_path(value, f"seed{seed}.training_receipt")
    except matrix.MatrixError as error:
        _fail(str(error))
    expected_name = f"{_expected_run_id(seed, plan_date)}-training.json"
    if candidate.name != expected_name or candidate.suffix != ".json":
        _fail(f"seed{seed}.training_receipt path does not bind current v3 run_id")
    return candidate


def _expected_checkpoint_path(receipt_path: Path, *, seed: int, plan_date: str) -> Path:
    expected = receipt_path.with_name(f"{_expected_run_id(seed, plan_date)}-checkpoint.pt")
    return expected


def _strict_receipt_shape(payload: Mapping[str, Any], *, seed: int) -> None:
    name = f"seed{seed}.receipt"
    _reject_unknown(payload, TOP_LEVEL_KEYS, name)
    _zero_credit(payload, name)
    config = _mapping(payload.get("config"), f"{name}.config")
    _reject_unknown(config, CONFIG_KEYS, f"{name}.config")
    evidence = _mapping(payload.get("evidence"), f"{name}.evidence")
    _reject_unknown(evidence, EVIDENCE_KEYS, f"{name}.evidence")
    initialization = _mapping(evidence.get("initialization"), f"{name}.evidence.initialization")
    _reject_unknown(initialization, INITIALIZATION_KEYS, f"{name}.initialization")
    normalization = _mapping(evidence.get("normalization"), f"{name}.evidence.normalization")
    _reject_unknown(normalization, NORMALIZATION_KEYS, f"{name}.evidence.normalization")
    prior = _mapping(evidence.get("residual_prior"), f"{name}.evidence.residual_prior")
    _reject_unknown(prior, PRIOR_KEYS, f"{name}.evidence.residual_prior")
    last_update = _mapping(prior.get("last_update"), f"{name}.evidence.residual_prior.last_update")
    _reject_unknown(last_update, LAST_UPDATE_KEYS, f"{name}.evidence.residual_prior.last_update")
    checkpoint = _mapping(payload.get("checkpoint"), f"{name}.checkpoint")
    _reject_unknown(checkpoint, CHECKPOINT_KEYS, f"{name}.checkpoint")
    _sha256(initialization.get("parameter_digest"), f"{name}.initialization.parameter_digest")
    _sha256(checkpoint.get("sha256"), f"{name}.checkpoint.sha256")


def _build_plan(
    *,
    receipt_path: Path,
    manifest_sha256: str,
    seed: int,
    plan_date: str,
) -> dict[str, Any]:
    run_id = _expected_run_id(seed, plan_date)
    checkpoint = _expected_checkpoint_path(receipt_path, seed=seed, plan_date=plan_date)
    return {
        "seed": seed,
        "run_id": run_id,
        "manifest_sha256": manifest_sha256,
        "launch_config": matrix._launch_config(
            manifest_sha256,
            seed,
            run_id,
            deferred_validation=True,
        ),
        "outputs": {
            "training_receipt": str(receipt_path),
            "checkpoint": str(checkpoint),
        },
    }


def _validate_receipt(
    payload: Mapping[str, Any],
    source: Mapping[str, Any],
    *,
    receipt_path: Path,
    seed: int,
    manifest_sha256: str,
    plan_date: str,
) -> dict[str, Any]:
    _strict_receipt_shape(payload, seed=seed)
    plan = _build_plan(
        receipt_path=receipt_path,
        manifest_sha256=manifest_sha256,
        seed=seed,
        plan_date=plan_date,
    )
    try:
        identity = matrix._validate_training_receipt(payload, source, plan=plan)
    except matrix.MatrixError as error:
        _fail(str(error))
    if identity["run_id"] != _expected_run_id(seed, plan_date):
        _fail(f"seed{seed}.run_id does not bind the current v3 plan")
    checkpoint = identity["checkpoint"]
    expected_checkpoint = _expected_checkpoint_path(receipt_path, seed=seed, plan_date=plan_date)
    if checkpoint["path"] != str(expected_checkpoint):
        _fail(f"seed{seed}.checkpoint.path drifts from the receipt namespace")
    source_path = _string(source.get("path"), f"seed{seed}.source.path")
    if source_path != str(receipt_path):
        _fail(f"seed{seed}.receipt path drifted while being read")
    result = dict(identity)
    result["model_kind"] = MODEL
    result["shared_config"] = {
        key: value
        for key, value in plan["launch_config"].items()
        if key not in {"manifest_sha256", "paired_seed", "run_id", "sampler_seed", "seed"}
    }
    result["formal_eligible"] = False
    result["qualification_credit"] = 0
    result["receipt"] = {
        "path": source_path,
        "bytes": _strict_int(source.get("bytes"), f"seed{seed}.source.bytes", 1),
        "sha256": _sha256(source.get("sha256"), f"seed{seed}.source.sha256"),
        "opened": True,
    }
    result["manifest_file_sha256"] = None
    return result


def _check(name: str, passed: bool, reason: str, observed: Any = None, expected: Any = None) -> dict[str, Any]:
    return {
        "check": name,
        "passed": bool(passed),
        "reason": reason,
        "observed": observed,
        "expected": expected,
    }


def _read_manifest(path: Path | str) -> tuple[Mapping[str, Any] | None, dict[str, Any], str | None, str | None, list[str], list[dict[str, Any]]]:
    errors: list[str] = []
    checks: list[dict[str, Any]] = []
    try:
        payload, source = matrix._read_bounded_json(path, name="manifest", max_bytes=matrix.MAX_MANIFEST_BYTES)
        if payload.get("schema") != "core.dataset.v2":
            _fail("manifest.schema must be core.dataset.v2")
        if payload.get("formal_release") is not False:
            _fail("manifest.formal_release must be false")
        canonical = matrix._canonical_sha(payload)
        checks.append(_check("manifest_raw_identity", True, "raw manifest bytes were bounded-read and hashed", source["sha256"], "SHA-256 of the explicit manifest file"))
        checks.append(_check("manifest_canonical_identity", True, "canonical manifest payload identity was computed", canonical, "SHA-256 of canonical manifest JSON"))
        return payload, source, str(source["sha256"]), canonical, errors, checks
    except (matrix.MatrixError, IntakeError, OSError, TypeError, ValueError) as error:
        errors.append(str(error))
        checks.extend(
            [
                _check("manifest_raw_identity", False, "explicit manifest could not be bounded-read", None, "readable JSON manifest"),
                _check("manifest_canonical_identity", False, "canonical manifest identity is unavailable", None, "canonical SHA-256"),
            ]
        )
        return None, _empty_source(path, error=str(error)), None, None, errors, checks


def build_report(
    manifest_path: Path | str,
    training_receipts: Mapping[int, Path | str] | None = None,
    *,
    seed_statuses: Mapping[int, str] | None = None,
    root: Path | str = LAB_ROOT,
    plan_date: str = PLAN_DATE,
    observed_at_utc: str | None = None,
) -> dict[str, Any]:
    """Build a bounded current-manifest training-evidence report."""

    del root  # Input paths are intentionally absolute; root is for API symmetry only.
    if not re.fullmatch(r"20[0-9]{6}", plan_date):
        _fail("plan_date must be YYYYMMDD")
    supplied = {} if training_receipts is None else dict(training_receipts)
    unknown_seeds = set(supplied) - set(SEEDS)
    if unknown_seeds:
        _fail(f"training receipt map contains unsupported seeds: {sorted(unknown_seeds)}")
    statuses = {} if seed_statuses is None else dict(seed_statuses)
    unknown_status_seeds = set(statuses) - set(SEEDS)
    if unknown_status_seeds:
        _fail(f"seed status map contains unsupported seeds: {sorted(unknown_status_seeds)}")
    invalid_statuses = set(statuses.values()) - {"running", "missing", "terminal"}
    if invalid_statuses:
        _fail(f"seed status map contains unsupported states: {sorted(invalid_statuses)}")

    manifest_payload, manifest_source, manifest_raw_sha, manifest_canonical_sha, errors, checks = _read_manifest(manifest_path)
    manifest_ok = manifest_payload is not None and manifest_raw_sha is not None and manifest_canonical_sha is not None
    exact_seed_set = set(supplied) == set(SEEDS)
    checks.insert(0, _check("exact_seed_set", exact_seed_set, "receipt paths must contain exactly seeds 17, 29, and 43", sorted(supplied), list(SEEDS)))
    if not exact_seed_set:
        errors.append(f"fail-closed: receipt path seed set is {sorted(supplied)}, expected {list(SEEDS)}")

    rows: list[dict[str, Any]] = []
    projections: dict[int, dict[str, Any]] = {}
    for seed in SEEDS:
        supplied_path = supplied.get(seed)
        status_hint = statuses.get(seed, "terminal" if supplied_path is not None else "missing")
        row: dict[str, Any] = {
            "seed": seed,
            "status": status_hint,
            "source": _status_source(supplied_path, status_hint) if status_hint != "terminal" else _empty_source(supplied_path),
            "blocked_reasons": [],
        }
        if supplied_path is None:
            row["status"] = "missing"
            row["blocked_reasons"].append(f"fail-closed: missing training receipt path for seed {seed}")
            errors.append(f"seed{seed}: missing training receipt path")
            rows.append(row)
            continue
        if status_hint in {"running", "missing"}:
            row["blocked_reasons"].append(f"fail-closed: seed{seed} receipt explicitly marked {status_hint}; it was not opened")
            errors.append(f"seed{seed}: receipt explicitly marked {status_hint}")
            rows.append(row)
            continue
        try:
            receipt_path = _safe_receipt_path(supplied_path, seed=seed, plan_date=plan_date)
            payload, source = matrix._read_bounded_json(receipt_path, name=f"seed{seed}.training_receipt", max_bytes=matrix.MAX_JSON_BYTES)
            row["source"] = source
            if not manifest_ok or manifest_canonical_sha is None:
                _fail("current canonical manifest identity is unavailable")
            projection = _validate_receipt(
                payload,
                source,
                receipt_path=receipt_path,
                seed=seed,
                manifest_sha256=manifest_canonical_sha,
                plan_date=plan_date,
            )
            projection["manifest_file_sha256"] = manifest_raw_sha
            row["status"] = "bound"
            row["evidence"] = projection
            projections[seed] = projection
        except (matrix.MatrixError, IntakeError, OSError, TypeError, ValueError) as error:
            row["status"] = "rejected"
            row["blocked_reasons"].append(str(error))
            errors.append(f"seed{seed}: {error}")
        rows.append(row)

    manifest_matches = (
        manifest_ok
        and len(projections) == len(SEEDS)
        and all(item["manifest_sha256"] == manifest_canonical_sha for item in projections.values())
    )
    checks.append(_check("manifest_canonical_sha_matches_receipts", manifest_matches, "each receipt config.manifest_sha256 equals the current canonical manifest identity", sorted({item["manifest_sha256"] for item in projections.values()}), [manifest_canonical_sha] if manifest_canonical_sha else None))
    if not manifest_matches:
        errors.append("fail-closed: receipt canonical manifest identity does not match the current manifest")

    common_config = len(projections) == len(SEEDS) and len({json.dumps(item["shared_config"], sort_keys=True, separators=(",", ":")) for item in projections.values()}) == 1
    checks.append(_check("common_graph_residual_config", common_config, "all accepted receipts share one graph_residual hidden16 v3 configuration", common_config, True))
    if not common_config:
        errors.append("fail-closed: accepted receipts do not provide one common graph_residual configuration")

    receipt_ids = [item["receipt"]["sha256"] for item in projections.values()]
    checkpoint_ids = [(item["checkpoint"]["path"], item["checkpoint"]["sha256"]) for item in projections.values()]
    run_ids = [item["run_id"] for item in projections.values()]
    identity_unique = (
        len(projections) == len(SEEDS)
        and len(set(receipt_ids)) == len(SEEDS)
        and len(set(checkpoint_ids)) == len(SEEDS)
        and len(set(run_ids)) == len(SEEDS)
    )
    checks.append(_check("identity_unique_per_seed", identity_unique, "run, receipt, and declared checkpoint identities are unique per seed", {"run_ids": run_ids, "receipt_sha256": receipt_ids, "checkpoint_path_sha256": checkpoint_ids}, "three unique seed identities"))
    if not identity_unique:
        errors.append("fail-closed: run, receipt, or checkpoint identity is duplicated")

    zero_credit_ok = True
    for row in rows:
        evidence = row.get("evidence")
        if evidence is not None and (evidence.get("formal_eligible") is not False or evidence.get("qualification_credit") != 0):
            zero_credit_ok = False
    checks.append(_check("zero_credit_non_authorizing", zero_credit_ok, "all accepted training metadata remains diagnostic-only and zero-credit", zero_credit_ok, True))
    if not zero_credit_ok:
        errors.append("fail-closed: accepted training metadata contains non-zero authority")

    errors = list(dict.fromkeys(errors))
    all_bound = manifest_ok and exact_seed_set and len(projections) == len(SEEDS) and manifest_matches and common_config and identity_unique and zero_credit_ok and not errors
    if not all_bound:
        for row in rows:
            if row["status"] == "bound":
                row["status"] = "blocked"
                row["blocked_reasons"].append("fail-closed: current-manifest training intake did not bind as one complete set")

    report: dict[str, Any] = {
        "schema": SCHEMA,
        "report_id": REPORT_ID,
        "observed_at_utc": observed_at_utc or datetime.now(timezone.utc).isoformat(),
        "status": "diagnostic_bound" if all_bound else "blocked_fail_closed",
        "fail_closed": not all_bound,
        "source_bound": all_bound,
        **ZERO_CREDIT,
        "formal_training_runs_counted": 0,
        "t1_case_runs_counted": 0,
        "t2_macro_families_counted": 0,
        "expected_contract": {
            "model_kind": MODEL,
            "hidden": HIDDEN,
            "updates": UPDATES,
            "parameter_count": PARAMETER_COUNT,
            "seeds": list(SEEDS),
            "plan_date": plan_date,
            "v3_run_id_suffix": "-v3",
            "bounded_manifest_and_receipt_json_only": True,
            "checkpoint_declared_identity_only": True,
            "zero_credit_only": True,
        },
        "manifest": {
            "schema": manifest_source.get("schema"),
            "path": manifest_source.get("path"),
            "bytes": manifest_source.get("bytes"),
            "raw_sha256": manifest_raw_sha,
            "canonical_sha256": manifest_canonical_sha,
            "opened": bool(manifest_source.get("opened")),
            "formal_release": manifest_payload.get("formal_release") if manifest_payload else None,
        },
        "runs": rows,
        "checks": checks,
        "errors": errors,
        "authorization": dict(ZERO_CREDIT),
        "input_boundary": {
            "bounded_manifest_json_opened": bool(manifest_source.get("opened")),
            "bounded_training_receipt_json_opened": sum(row["source"].get("opened") is True for row in rows),
            "checkpoint_content_opened": False,
            "checkpoint_lstat_performed": False,
            "hdf5_content_opened": False,
            "trajectory_content_opened": False,
            "evaluation_content_opened": False,
            "progress_content_opened": False,
            "gpu_started": False,
            "queue_started": False,
            "runtime_started": False,
        },
        "side_effects": {
            "processes_started": 0,
            "processes_stopped": 0,
            "processes_restarted": 0,
            "registry_writes": 0,
            "ledger_writes": 0,
            "denominator_writes": 0,
            "gate_writes": 0,
            "completion_writes": 0,
        },
        "scope_note": "bounded current manifest and training receipt metadata only; checkpoint/HDF5/trajectory/progress are never opened; diagnostic-only and zero-credit",
    }
    validate_report(report)
    return report


def _validate_source(source: Mapping[str, Any], name: str, *, opened: bool) -> None:
    expected = {"path", "exists", "opened", "bytes", "sha256", "schema"}
    if set(source) - expected - {"error", "status_hint"}:
        _fail(f"{name} source metadata contains unknown fields")
    _string(source.get("path"), f"{name}.path")
    if type(source.get("opened")) is not bool or source.get("opened") is not opened:
        _fail(f"{name}.opened drifts")
    if opened:
        _exact(source, "exists", True, name)
        _strict_int(source.get("bytes"), f"{name}.bytes", 1)
        _sha256(source.get("sha256"), f"{name}.sha256")
    elif source.get("bytes") is not None or source.get("sha256") is not None:
        _fail(f"{name} unopened source contains observed identity")


def validate_report(report: Mapping[str, Any]) -> list[str]:
    """Validate a generated report without opening any source artifact."""

    errors: list[str] = []
    try:
        _exact(report, "schema", SCHEMA, "report")
        _exact(report, "report_id", REPORT_ID, "report")
        status = report.get("status")
        if status not in {"diagnostic_bound", "blocked_fail_closed"}:
            _fail("report.status is invalid")
        source_bound = report.get("source_bound")
        if type(source_bound) is not bool:
            _fail("report.source_bound must be boolean")
        _exact(report, "fail_closed", not source_bound, "report")
        _exact(report, "status", "diagnostic_bound" if source_bound else "blocked_fail_closed", "report")
        _zero_credit(report, "report")
        _string(report.get("observed_at_utc"), "report.observed_at_utc")
        expected = _mapping(report.get("expected_contract"), "report.expected_contract")
        for key, value in (("model_kind", MODEL), ("hidden", HIDDEN), ("updates", UPDATES), ("parameter_count", PARAMETER_COUNT), ("seeds", list(SEEDS)), ("v3_run_id_suffix", "-v3"), ("zero_credit_only", True)):
            _exact(expected, key, value, "report.expected_contract")
        manifest = _mapping(report.get("manifest"), "report.manifest")
        _exact(manifest, "schema", "core.dataset.v2", "report.manifest")
        _string(manifest.get("path"), "report.manifest.path")
        _strict_int(manifest.get("bytes"), "report.manifest.bytes", 1) if manifest.get("opened") else None
        if manifest.get("opened"):
            _exact(manifest, "opened", True, "report.manifest")
            _sha256(manifest.get("raw_sha256"), "report.manifest.raw_sha256")
            _sha256(manifest.get("canonical_sha256"), "report.manifest.canonical_sha256")
        _exact(manifest, "formal_release", False, "report.manifest")
        runs = report.get("runs")
        if not isinstance(runs, list) or len(runs) != len(SEEDS):
            _fail("report.runs must contain exactly three seed rows")
        observed_seeds = set()
        opened_count = 0
        for row_value in runs:
            row = _mapping(row_value, "report.runs[]")
            seed = _strict_int(row.get("seed"), "report.runs[].seed")
            if seed not in SEEDS or seed in observed_seeds:
                _fail("report.runs seed coverage is invalid")
            observed_seeds.add(seed)
            row_status = row.get("status")
            if row_status not in {"missing", "running", "rejected", "bound", "blocked"}:
                _fail("report.runs[].status is invalid")
            source = _mapping(row.get("source"), "report.runs[].source")
            opened = bool(source.get("opened"))
            _validate_source(source, f"report.runs[{seed}].source", opened=opened)
            opened_count += int(opened)
            if row_status in {"bound", "blocked"}:
                if "evidence" not in row:
                    _fail(f"report.runs[{seed}] is bound/blocked without evidence")
                evidence = _mapping(row["evidence"], f"report.runs[{seed}].evidence")
                _exact(evidence, "model_kind", MODEL, f"report.runs[{seed}].evidence")
                _exact(evidence, "hidden", HIDDEN, f"report.runs[{seed}].evidence")
                _exact(evidence, "updates", UPDATES, f"report.runs[{seed}].evidence")
                _sha256(evidence.get("manifest_sha256"), f"report.runs[{seed}].evidence.manifest_sha256")
                _mapping(evidence.get("checkpoint"), f"report.runs[{seed}].evidence.checkpoint")
                _sha256(evidence["checkpoint"].get("sha256"), f"report.runs[{seed}].evidence.checkpoint.sha256")
                _sha256(evidence.get("manifest_file_sha256"), f"report.runs[{seed}].evidence.manifest_file_sha256")
        if observed_seeds != set(SEEDS):
            _fail("report.runs does not cover exactly seeds 17, 29, and 43")
        boundary = _mapping(report.get("input_boundary"), "report.input_boundary")
        _exact(boundary, "bounded_training_receipt_json_opened", opened_count, "report.input_boundary")
        for key in ("checkpoint_content_opened", "checkpoint_lstat_performed", "hdf5_content_opened", "trajectory_content_opened", "evaluation_content_opened", "progress_content_opened", "gpu_started", "queue_started", "runtime_started"):
            _exact(boundary, key, False, "report.input_boundary")
        _mapping(report.get("side_effects"), "report.side_effects")
        checks = report.get("checks")
        if not isinstance(checks, list) or not checks:
            _fail("report.checks must be a non-empty array")
        report_errors = report.get("errors")
        if not isinstance(report_errors, list) or any(not isinstance(item, str) for item in report_errors):
            _fail("report.errors must be an array of strings")
        if source_bound and report_errors:
            _fail("bound report cannot contain errors")
        if not source_bound and not report_errors:
            _fail("blocked report must contain errors")
    except (IntakeError, KeyError, TypeError, ValueError) as error:
        errors.append(str(error))
    return errors


def _safe_output(path: Path | str, *, root: Path, suffix: str) -> Path:
    try:
        candidate = matrix._absolute_path(path, "output")
    except matrix.MatrixError as error:
        _fail(str(error))
    reports = (root / "reports").resolve()
    if candidate.parent != reports:
        _fail("output must stay in the graph_residual reports directory")
    if candidate.suffix != suffix or not candidate.name.startswith("F3-GRAPH-RESIDUAL-HIDDEN16-CURRENT-MANIFEST-TRAINING-EVIDENCE-"):
        _fail("output name/suffix is outside the graph_residual training-evidence scope")
    return candidate


def _write_text(text: str, output: Path, *, root: Path, suffix: str) -> None:
    candidate = _safe_output(output, root=root, suffix=suffix)
    if candidate.exists():
        _fail(f"refuses overwrite of existing report: {candidate}")
    candidate.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{candidate.name}.", suffix=".tmp", dir=candidate.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, candidate)
    except Exception:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def write_report(report: Mapping[str, Any], output: Path | str, *, root: Path | str = LAB_ROOT) -> Path:
    validation_errors = validate_report(report)
    if validation_errors:
        _fail(f"refuses to write invalid report: {validation_errors}")
    root_path = Path(root).resolve()
    candidate = _safe_output(output, root=root_path, suffix=".json")
    _write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", candidate, root=root_path, suffix=".json")
    return candidate


def render_markdown(report: Mapping[str, Any]) -> str:
    rows = report["runs"]
    lines = [
        "# F3 graph_residual hidden16 current-manifest training evidence",
        "",
        f"- 状态：`{report['status']}`；source-bound=`{report['source_bound']}`；fail-closed=`{report['fail_closed']}`",
        f"- model/config：`{MODEL}` / hidden `{HIDDEN}` / updates `{UPDATES}` / seeds `{','.join(map(str, SEEDS))}`",
        "- 权限边界：diagnostic-only；formal/T1/T2/qualification=false；credit=0；未启动或控制 GPU",
        f"- canonical manifest SHA：`{report['manifest']['canonical_sha256']}`",
        f"- raw manifest SHA：`{report['manifest']['raw_sha256']}`",
        f"- bounded receipt JSON opened：`{report['input_boundary']['bounded_training_receipt_json_opened']}/3`；checkpoint/HDF5/trajectory/progress 未打开",
        "",
        "## Training receipts",
        "",
        "| seed | status | run_id | receipt | checkpoint |",
        "|---:|---|---|---|---|",
    ]
    for row in rows:
        evidence = row.get("evidence") or {}
        checkpoint = evidence.get("checkpoint") or {}
        lines.append(
            f"| {row['seed']} | `{row['status']}` | `{evidence.get('run_id', '—')}` | `{row['source'].get('path', '—')}` | `{checkpoint.get('path', '—')}` |"
        )
    lines.extend(
        [
            "",
            "## 边界",
            "",
            "本 intake 只消费 bounded manifest/receipt JSON 元数据，并复用现有 graph_residual current-manifest matrix 的 residual evidence validator；不读取 checkpoint 内容，不读取 HDF5、trajectory、evaluation、progress，不规划或启动 rollout。正向绑定也不产生 Core formal、T1/T2、qualification、denominator、registry、ledger、gate 或 completion credit。",
            "",
        ]
    )
    return "\n".join(lines)


def _parse_seed_values(values: Sequence[str], *, label: str) -> dict[int, str]:
    result: dict[int, str] = {}
    for item in values:
        if "=" not in item:
            raise ValueError(f"--{label} must use SEED=VALUE")
        seed_text, value = item.split("=", 1)
        seed = int(seed_text)
        if seed not in SEEDS:
            raise ValueError(f"unsupported seed for --{label}: {seed}")
        if seed in result:
            raise ValueError(f"duplicate seed for --{label}: {seed}")
        result[seed] = value
    return result


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="explicit current canonical manifest JSON path")
    parser.add_argument("--seed-receipt", action="append", default=[], metavar="SEED=PATH", help="current v3 training receipt path; repeat for seeds 17/29/43")
    parser.add_argument("--seed-status", action="append", default=[], metavar="SEED=running|missing|terminal", help="optional status hint; running/missing receipts are not opened")
    parser.add_argument("--plan-date", default=PLAN_DATE)
    parser.add_argument("--root", default=str(LAB_ROOT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT))
    parser.add_argument("--verify-report")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        root = Path(args.root).resolve()
        if args.verify_report:
            report_path = matrix._absolute_path(args.verify_report, "verify_report")
            payload, source = matrix._read_bounded_json(report_path, name="training_evidence_report", max_bytes=MAX_REPORT_BYTES)
            validation_errors = validate_report(payload)
            if validation_errors:
                raise IntakeError("; ".join(validation_errors))
            print(json.dumps({"status": "verified", "report": source["path"], "report_sha256": source["sha256"]}, sort_keys=True))
            return 0
        receipt_values = _parse_seed_values(args.seed_receipt, label="seed-receipt")
        status_values = _parse_seed_values(args.seed_status, label="seed-status")
        report = build_report(
            args.manifest,
            receipt_values,
            seed_statuses=status_values,
            root=root,
            plan_date=args.plan_date,
        )
        output = write_report(report, args.output, root=root)
        markdown = _safe_output(args.markdown_output, root=root, suffix=".md")
        _write_text(render_markdown(report), markdown, root=root, suffix=".md")
        print(json.dumps({"status": report["status"], "source_bound": report["source_bound"], "output": str(output), "markdown_output": str(markdown), "receipts_opened": report["input_boundary"]["bounded_training_receipt_json_opened"], "credit": report["credit"]}, sort_keys=True))
        return 0
    except (IntakeError, matrix.MatrixError, OSError, TypeError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
