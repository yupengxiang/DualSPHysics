#!/usr/bin/env python3
"""Evaluate the completed seven-family label-quality product by task scope.

This is an additive metadata evaluator.  It reads the exact quality manifest,
the completed v3 JSON report, and optionally its execution receipt.  It does
not reopen any materialized label H5 or source trajectory.  The output grants
only source-role/mass-ledger/saved-frame-censoring development usability;
continuous arrival, hidden recrossings, physical fate, dynamics, recovery
transfer, and effective split safety remain unknown.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
SCHEMA = "ds02.stage2.family-label-quality-evaluator.v1"
REPORT_SCHEMA = "ds02.stage2.family-label-quality.v3"
FAMILIES = [f"F{i}" for i in range(1, 8)]
ROLES = {"native_initial_mk", "initial_spatial_region"}


class EvaluationError(RuntimeError):
    pass


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise EvaluationError(f"{label} must be a non-empty path")
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise EvaluationError(f"{label} is missing: {path}")
    return path


def read_json(value: Path | str, label: str) -> tuple[Path, dict[str, Any]]:
    path = require_file(str(value), label)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EvaluationError(f"{label} is invalid JSON: {path}") from error
    if not isinstance(payload, dict):
        raise EvaluationError(f"{label} must be an object")
    return path, payload


def _validate_report(manifest_path: Path, manifest: dict[str, Any],
                     report_path: Path, report: dict[str, Any]) -> list[dict[str, Any]]:
    if report.get("schema") != REPORT_SCHEMA or report.get("status") != "FAMILY_LABEL_QUALITY_V3_PASS_MASS_CENSOR_ARTIFACT_SOURCE_BOUND":
        raise EvaluationError("quality report is not the completed source-bound v3 product")
    if report.get("manifest", {}).get("sha256") != sha256_file(manifest_path):
        raise EvaluationError("quality report does not bind this manifest")
    if report.get("read_policy", {}).get("original_trajectory_h5_opened") is not False:
        raise EvaluationError("quality report did not prove original trajectory H5 exclusion")
    if report.get("read_policy", {}).get("part_bi4_opened") is not False:
        raise EvaluationError("quality report did not prove BI4 exclusion")
    boundary = report.get("claim_boundary", {})
    if any(boundary.get(key) != "UNKNOWN" for key in ("physical_fate", "dynamical_impact", "continuous_first_arrival", "hidden_recrossings")):
        raise EvaluationError("quality report has an overclaiming boundary")
    entries = manifest.get("entries")
    cases = report.get("cases")
    if not isinstance(entries, list) or len(entries) != 7 or not isinstance(cases, list) or len(cases) != 7:
        raise EvaluationError("evaluator requires exactly seven quality cases")
    manifest_by_key = {(e.get("family_id"), e.get("physical_case_id")): e for e in entries}
    report_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for case in cases:
        identity = case.get("normalized_identity")
        if not isinstance(identity, dict):
            raise EvaluationError("quality case lacks normalized identity")
        key = (identity.get("family_id"), identity.get("physical_case_id"))
        if key in report_by_key or key not in manifest_by_key:
            raise EvaluationError("quality case identity differs from manifest")
        role = case.get("source_role")
        if role not in ROLES or manifest_by_key[key].get("source_role") != role:
            raise EvaluationError("quality case source role differs from producer manifest")
        if case.get("split") != manifest_by_key[key].get("split"):
            raise EvaluationError("quality case split differs from manifest")
        checks = case.get("quality_checks")
        if not isinstance(checks, dict) or not checks or not all(value is True for value in checks.values()):
            raise EvaluationError("quality case artifact checks are not all closed")
        if case.get("mass_weighted_scope", {}).get("qualification_credit") != "none":
            raise EvaluationError("quality case mass screen grants qualification credit")
        if case.get("censoring_scope", {}).get("first_passage") != "first observed saved-frame chord bracket only":
            raise EvaluationError("quality case first-passage scope is not saved-frame limited")
        report_by_key[key] = case
    if set(report_by_key) != set(manifest_by_key) or sorted(key[0] for key in report_by_key) != FAMILIES:
        raise EvaluationError("quality report does not cover F1-F7 exactly")
    return [report_by_key[(family, next(key[1] for key in report_by_key if key[0] == family))] for family in FAMILIES]


def evaluate(manifest_path: Path | str, quality_report_path: Path | str,
             output: Path | str, receipt_path: Path | str | None = None) -> dict[str, Any]:
    manifest_path, manifest = read_json(manifest_path, "seven-family quality manifest")
    quality_report_path, report = read_json(quality_report_path, "seven-family quality report")
    cases = _validate_report(manifest_path, manifest, quality_report_path, report)
    receipt_binding = None
    if receipt_path is not None:
        receipt = require_file(str(receipt_path), "quality execution receipt")
        receipt_binding = {"path": str(receipt), "sha256": sha256_file(receipt)}
    cards = []
    for case in cases:
        identity = case["normalized_identity"]
        cards.append({
            "family_id": identity["family_id"],
            "physical_case_id": identity["physical_case_id"],
            "source_role": case["source_role"],
            "source_role_basis": case["source_role_basis"],
            "split": case["split"],
            "task_eligibility": {
                "materialized_label_mass_source_closure": "ELIGIBLE_DEVELOPMENT_AUDIT",
                "source_role_diagnostic": "ELIGIBLE_DEVELOPMENT_AUDIT",
                "saved_frame_chord_censoring": "ELIGIBLE_LIMITED_DEVELOPMENT",
                "continuous_first_arrival": "UNKNOWN",
                "hidden_recrossings": "UNKNOWN",
                "physical_fate": "UNKNOWN",
                "dynamical_impact": "UNKNOWN",
                "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
                "effective_split": "UNRESOLVED_EXCLUDED",
                "recovery_window_transfer": "UNKNOWN",
                "qualification_credit": "NONE",
            },
            "quality_checks_closed": True,
            "read_policy": case["read_policy"],
        })
    result = {
        "schema": SCHEMA,
        "status": "PASS_SEVEN_FAMILY_TASK_SCOPE_NO_QUALIFICATION",
        "inputs": {
            "manifest": {"path": str(manifest_path), "sha256": sha256_file(manifest_path)},
            "quality_report": {"path": str(quality_report_path), "sha256": sha256_file(quality_report_path)},
            "quality_execution_receipt": receipt_binding,
        },
        "family_count": 7,
        "family_cards": cards,
        "evaluator_contract": {
            "allowed_scope": ["source-role diagnostics", "materialized-label mass closure", "saved-frame chord censor brackets"],
            "continuous_first_arrival": "UNKNOWN",
            "hidden_recrossings": "UNKNOWN",
            "physical_fate": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
            "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
            "effective_split_safe": False,
            "recovery_safe": False,
            "qualification_credit": "NONE",
        },
        "read_policy": {
            "manifest_json_opened": True,
            "quality_report_json_opened": True,
            "execution_receipt_json_opened": receipt_binding is not None,
            "materialized_label_h5_opened": False,
            "original_trajectory_h5_opened": False,
            "part_bi4_opened": False,
            "solver_started": False,
            "model_invoked": False,
        },
    }
    output = Path(output).expanduser().resolve()
    if output.exists():
        raise EvaluationError(f"refusing to overwrite evaluator output: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def make_request(manifest_path: Path | str, quality_report_path: Path | str,
                 output: Path | str, worktree_root: Path | str,
                 receipt_path: Path | str | None = None,
                 worker_root: Path | str | None = None) -> dict[str, Any]:
    """Build an infra/v8 CPU request for the JSON-only evaluator."""
    manifest_path = require_file(str(manifest_path), "quality manifest")
    quality_report_path = require_file(str(quality_report_path), "quality report")
    receipt = require_file(str(receipt_path), "quality receipt") if receipt_path is not None else None
    runtime_root = Path(worktree_root).expanduser().resolve()
    script_root = Path(worker_root).expanduser().resolve() if worker_root is not None else runtime_root
    worker = script_root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_family_label_quality_evaluator_v1.py"
    runtime = [runtime_root / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v6.py",
               runtime_root / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py",
               runtime_root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py",
               runtime_root / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"]
    inputs = [manifest_path, quality_report_path, worker, *runtime]
    if receipt is not None:
        inputs.append(receipt)
    unique = []
    seen: set[str] = set()
    for path in inputs:
        path = Path(path).resolve()
        if str(path) not in seen:
            unique.append(path); seen.add(str(path))
    missing = [str(path) for path in unique if not path.is_file()]
    hashes = {str(path): sha256_file(path) for path in unique if path.is_file()}
    request = {
        "schema": "ds02.runner-request.v1",
        "request_schema": "ds02.stage2.family-label-quality-evaluator-request.v1",
        "attempt_id": "seven-family-label-quality-evaluator-v1-forward-001",
        "case_id": "DS02_STAGE2_SEVEN_FAMILY_LABEL_QUALITY_EVALUATOR_V1",
        "family_id": "infra", "dataset_families": FAMILIES,
        "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 1,
        "max_wall_seconds": 300, "estimated_storage_bytes": 16 * 1024 * 1024,
        "cwd": str(runtime_root / "lagrangian-fluid-lab/scripts"), "worktree_root": str(runtime_root),
        "command": ["/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python", str(worker),
                     "evaluate", "--manifest", str(manifest_path), "--quality-report", str(quality_report_path),
                     *(["--receipt", str(receipt)] if receipt is not None else []),
                     "--output", "{attempt_root}/seven-family-label-quality-evaluator-v1.json"],
        "input_files": [str(path) for path in unique], "input_sha256": hashes,
        "launch_allowed": not missing, "primary_launch_owner": "root",
        "status": "prepared_guard_pending_actual_CPU" if not missing else "prepared_missing_guard_sources",
        "source_cost": {"small_json_bytes_read": sum(path.stat().st_size for path in unique if path.is_file()),
                        "original_trajectory_h5_bytes_read": 0, "part_bi4_bytes_read": 0,
                        "solver_started": False, "cfd_or_model_run": False},
        "claim_boundary": {"physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN",
                            "continuous_first_arrival": "UNKNOWN", "hidden_recrossings": "UNKNOWN",
                            "split_safe": "UNKNOWN", "recovery_safe": "UNKNOWN", "qualification_credit": "none"},
        "missing_guard_sources": missing,
    }
    output = Path(output).expanduser().resolve()
    if output.exists():
        raise EvaluationError(f"refusing to overwrite evaluator request: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return request


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    ev = sub.add_parser("evaluate")
    ev.add_argument("--manifest", type=Path, required=True); ev.add_argument("--quality-report", type=Path, required=True)
    ev.add_argument("--receipt", type=Path); ev.add_argument("--output", type=Path, required=True)
    req = sub.add_parser("make-request")
    req.add_argument("--manifest", type=Path, required=True); req.add_argument("--quality-report", type=Path, required=True)
    req.add_argument("--receipt", type=Path); req.add_argument("--output", type=Path, required=True)
    req.add_argument("--worktree-root", type=Path, required=True); req.add_argument("--worker-root", type=Path)
    args = parser.parse_args(argv)
    if args.command == "evaluate":
        evaluate(args.manifest, args.quality_report, args.output, args.receipt)
    else:
        make_request(args.manifest, args.quality_report, args.output, args.worktree_root, args.receipt, args.worker_root)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
