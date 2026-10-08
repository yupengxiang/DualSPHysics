#!/usr/bin/env python3
"""Strict JSON-only consumer for the seven-family quality product.

The v1 evaluator treated an optional completed receipt as an unverified file
hash.  This forward version requires the receipt's exact output root,
attempt/case identity, command output target, manifest/current input hashes,
and producer worker binding to agree with the quality report.  A completed
receipt from another run therefore cannot confer source credit merely by
having a plausible JSON shape.  No label H5 or trajectory H5 is opened.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
SCHEMA = "ds02.stage2.family-label-quality-evaluator.v2-strict"
REPORT_SCHEMA = "ds02.stage2.family-label-quality.v3"
FAMILIES = [f"F{i}" for i in range(1, 8)]
ROLES = {"native_initial_mk", "initial_spatial_region"}


class EvaluationError(RuntimeError):
    pass


def copy_json(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(value: Any, label: str) -> Path:
    if isinstance(value, Path):
        path = value.expanduser().resolve()
    elif isinstance(value, str) and value:
        path = Path(value).expanduser().resolve()
    else:
        raise EvaluationError(f"{label} must be a non-empty path")
    if not path.is_file():
        raise EvaluationError(f"{label} is missing: {path}")
    return path


def read_json(value: Path | str, label: str) -> tuple[Path, dict[str, Any]]:
    path = require_file(value, label)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise EvaluationError(f"{label} is invalid JSON: {path}") from error
    if not isinstance(payload, dict):
        raise EvaluationError(f"{label} must be an object")
    return path, payload


def _hash_map(request: dict[str, Any]) -> dict[str, str]:
    value = request.get("input_hashes") or request.get("input_sha256")
    if not isinstance(value, dict):
        raise EvaluationError("producer request has no input hash map")
    return {str(Path(key).expanduser().resolve()): str(digest) for key, digest in value.items()}


def _request_input_files(request: dict[str, Any]) -> list[Path]:
    values = request.get("input_files")
    if not isinstance(values, list) or not values or not all(isinstance(value, str) and value for value in values):
        raise EvaluationError("producer request has no concrete input_files")
    return [Path(value).expanduser().resolve() for value in values]


def _strict_receipt(report_path: Path, report: dict[str, Any], manifest_path: Path,
                    receipt_path: Path, receipt: dict[str, Any]) -> dict[str, Any]:
    if receipt.get("schema") != "ds02.execution-receipt.v1" or receipt.get("status") != "completed" or receipt.get("returncode") not in (None, 0):
        raise EvaluationError("quality receipt is not a completed successful execution-receipt.v1")
    output_root_value = receipt.get("output_root")
    if not isinstance(output_root_value, str) or Path(output_root_value).expanduser().resolve() != report_path.parent:
        raise EvaluationError("quality receipt output_root is not the quality report parent")
    request = receipt.get("request")
    if not isinstance(request, dict):
        raise EvaluationError("quality receipt lacks its embedded producer request")
    attempt_id = receipt_path.parent.name
    if request.get("attempt_id") != attempt_id:
        raise EvaluationError("quality receipt request attempt_id is not its output directory")
    if request.get("case_id") != "DS02_STAGE2_SEVEN_ACTUAL_FAMILY_LABEL_QUALITY_V3":
        raise EvaluationError("quality receipt belongs to another producer case")
    if request.get("family_id") != "infra" or request.get("cpu_task_kind") != "audit":
        raise EvaluationError("quality receipt producer scope is not the seven-family quality audit")
    command = request.get("command")
    if not isinstance(command, list) or not all(isinstance(value, str) for value in command):
        raise EvaluationError("quality receipt producer command is missing")
    worker_indices = [index for index, value in enumerate(command) if value.endswith("ds_data02_stage2_family_label_quality_v3.py")]
    if len(worker_indices) != 1:
        raise EvaluationError("quality receipt command does not identify exactly one v3 quality worker")
    output_indices = [index for index, value in enumerate(command) if value == "--output"]
    if len(output_indices) != 1 or output_indices[0] + 1 >= len(command):
        raise EvaluationError("quality receipt command has no unique output target")
    target = command[output_indices[0] + 1]
    if not target.endswith(report_path.name) or "{attempt_root}" not in target:
        raise EvaluationError("quality receipt command output target does not name the quality report")
    manifest_indices = [index for index, value in enumerate(command) if value == "--manifest"]
    if len(manifest_indices) != 1 or manifest_indices[0] + 1 >= len(command):
        raise EvaluationError("quality receipt command has no unique manifest target")
    if Path(command[manifest_indices[0] + 1]).expanduser().resolve() != manifest_path:
        raise EvaluationError("quality receipt command manifest differs from quality report manifest")
    files = _request_input_files(request)
    hashes = _hash_map(request)
    if manifest_path not in files or hashes.get(str(manifest_path)) != sha256_file(manifest_path):
        raise EvaluationError("producer request does not hash the exact quality manifest")
    current_candidates = [path for path in files if path.name == "CURRENT336.json"]
    if len(current_candidates) != 1 or hashes.get(str(current_candidates[0])) != sha256_file(current_candidates[0]):
        raise EvaluationError("producer request does not hash exactly one stable CURRENT336")
    worker_path = Path(command[worker_indices[0]]).expanduser().resolve()
    if worker_path not in files or hashes.get(str(worker_path)) != sha256_file(worker_path):
        raise EvaluationError("producer request does not hash its exact v3 worker")
    launch_hashes = receipt.get("input_hashes_at_launch")
    after_hashes = receipt.get("input_hashes_after_run")
    if not isinstance(launch_hashes, dict) or not isinstance(after_hashes, dict):
        raise EvaluationError("quality receipt lacks launch/end input hash maps")
    launch = {str(Path(key).expanduser().resolve()): str(value) for key, value in launch_hashes.items()}
    after = {str(Path(key).expanduser().resolve()): str(value) for key, value in after_hashes.items()}
    for path in (manifest_path, current_candidates[0], worker_path):
        key = str(path); observed = sha256_file(path)
        if launch.get(key) != observed or after.get(key) != observed:
            raise EvaluationError(f"quality receipt launch/end hash mismatch for {path}")
    if not isinstance(receipt.get("request_sha256"), str) or not receipt["request_sha256"]:
        raise EvaluationError("quality receipt has no request digest")
    report_manifest = report.get("manifest") if isinstance(report.get("manifest"), dict) else {}
    if report_manifest.get("path") != str(manifest_path) or report_manifest.get("sha256") != sha256_file(manifest_path):
        raise EvaluationError("quality report manifest identity differs from strict receipt binding")
    return {
        "path": str(receipt_path), "sha256": sha256_file(receipt_path), "status": receipt.get("status"),
        "output_root": output_root_value, "attempt_id": attempt_id, "case_id": request.get("case_id"),
        "request_sha256": receipt.get("request_sha256"), "worker_path": str(worker_path),
        "manifest_path": str(manifest_path), "current_path": str(current_candidates[0]),
        "launch_end_hashes_closed": True,
    }


def _validate_report(manifest_path: Path, manifest: dict[str, Any], report_path: Path,
                     report: dict[str, Any]) -> list[dict[str, Any]]:
    if report.get("schema") != REPORT_SCHEMA or report.get("status") != "FAMILY_LABEL_QUALITY_V3_PASS_MASS_CENSOR_ARTIFACT_SOURCE_BOUND":
        raise EvaluationError("quality report is not the completed source-bound v3 product")
    if report.get("manifest", {}).get("sha256") != sha256_file(manifest_path):
        raise EvaluationError("quality report does not bind this manifest")
    policy = report.get("read_policy") or {}
    if policy.get("original_trajectory_h5_opened") is not False or policy.get("part_bi4_opened") is not False or policy.get("solver_started") is not False or policy.get("model_invoked") is not False:
        raise EvaluationError("quality report does not close trajectory/BI4/solver/model scope")
    boundary = report.get("claim_boundary") or {}
    for key in ("physical_fate", "dynamical_impact", "continuous_first_arrival", "hidden_recrossings"):
        if boundary.get(key) != "UNKNOWN":
            raise EvaluationError(f"quality report grants an unsupported claim: {key}")
    entries = manifest.get("entries"); cases = report.get("cases")
    if not isinstance(entries, list) or len(entries) != 7 or not isinstance(cases, list) or len(cases) != 7:
        raise EvaluationError("strict evaluator requires seven manifest entries and seven report cases")
    entry_by_key = {(entry.get("family_id"), entry.get("physical_case_id")): entry for entry in entries}
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for case in cases:
        identity = case.get("normalized_identity")
        if not isinstance(identity, dict):
            raise EvaluationError("quality case lacks normalized identity")
        key = (identity.get("family_id"), identity.get("physical_case_id"))
        if key in result or key not in entry_by_key:
            raise EvaluationError("quality case identity differs from its manifest")
        role = case.get("source_role")
        if role not in ROLES or entry_by_key[key].get("source_role") != role:
            raise EvaluationError("quality case source role differs from its producer manifest")
        if case.get("split") != entry_by_key[key].get("split"):
            raise EvaluationError("quality case split differs from its producer manifest")
        checks = case.get("quality_checks")
        if not isinstance(checks, dict) or not checks or not all(value is True for value in checks.values()):
            raise EvaluationError("quality case checks are not fully closed")
        scope = case.get("mass_weighted_scope") or {}
        if scope.get("qualification_credit") != "none":
            raise EvaluationError("quality case mass screen grants qualification credit")
        censor = case.get("censoring_scope") or {}
        if censor.get("first_passage") != "first observed saved-frame chord bracket only":
            raise EvaluationError("quality case first-passage scope is not saved-frame limited")
        source = case.get("source") or {}
        report_value = source.get("report_path")
        if not isinstance(report_value, str) or not report_value:
            raise EvaluationError("quality case lacks its small report path")
        small_report = require_file(report_value, "quality case small report")
        if source.get("report_sha256") != sha256_file(small_report):
            raise EvaluationError("quality case small report digest mismatch")
        result[key] = case
    if set(result) != set(entry_by_key) or sorted(key[0] for key in result) != FAMILIES:
        raise EvaluationError("quality product does not cover F1-F7 exactly")
    return [result[next(key for key in result if key[0] == family)] for family in FAMILIES]


def evaluate(manifest_path: Path | str, quality_report_path: Path | str, receipt_path: Path | str,
             output: Path | str) -> dict[str, Any]:
    manifest_path, manifest = read_json(manifest_path, "seven-family quality manifest")
    quality_report_path, report = read_json(quality_report_path, "seven-family quality report")
    receipt_path, receipt = read_json(receipt_path, "seven-family quality execution receipt")
    cases = _validate_report(manifest_path, manifest, quality_report_path, report)
    receipt_binding = _strict_receipt(quality_report_path, report, manifest_path, receipt_path, receipt)
    cards = []
    for case in cases:
        identity = case["normalized_identity"]
        cards.append({
            "family_id": identity["family_id"], "physical_case_id": identity["physical_case_id"],
            "source_role": case["source_role"], "source_role_basis": case.get("source_role_basis"),
            "split": case.get("split"), "quality_checks_closed": True,
            "task_eligibility": {
                "materialized_label_mass_source_closure": "ELIGIBLE_DEVELOPMENT_AUDIT",
                "source_role_diagnostic": "ELIGIBLE_DEVELOPMENT_AUDIT",
                "saved_frame_chord_censoring": "ELIGIBLE_LIMITED_DEVELOPMENT",
                "continuous_first_arrival": "UNKNOWN", "hidden_recrossings": "UNKNOWN",
                "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN",
                "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
                "effective_split": "UNKNOWN", "recovery_window_transfer": "UNKNOWN", "qualification_credit": "NONE",
            },
            "read_policy": copy_json(case.get("read_policy") or {}),
        })
    result = {
        "schema": SCHEMA, "status": "PASS_SEVEN_FAMILY_TASK_SCOPE_STRICT_PRODUCER_BOUND_NO_QUALIFICATION",
        "inputs": {
            "manifest": {"path": str(manifest_path), "sha256": sha256_file(manifest_path)},
            "quality_report": {"path": str(quality_report_path), "sha256": sha256_file(quality_report_path)},
            "quality_execution_receipt": receipt_binding,
        },
        "family_count": 7, "family_cards": cards,
        "evaluator_contract": {
            "producer_receipt_identity": "exact output_root/attempt/case/command/manifest/current/worker launch-end hashes",
            "allowed_scope": ["source-role diagnostics", "materialized-label mass closure", "saved-frame chord censor brackets"],
            "continuous_first_arrival": "UNKNOWN", "hidden_recrossings": "UNKNOWN", "physical_fate": "UNKNOWN",
            "dynamical_impact": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
            "effective_split_safe": False, "recovery_safe": False, "qualification_credit": "NONE",
        },
        "read_policy": {
            "manifest_json_opened": True, "quality_report_json_opened": True, "execution_receipt_json_opened": True,
            "small_case_reports_opened": True, "materialized_label_h5_opened_by_this_worker": False,
            "original_trajectory_h5_opened": False, "part_bi4_opened": False, "solver_started": False, "model_invoked": False,
            "upstream_quality_materialized_label_h5_read": "as declared by upstream product; not reopened here",
        },
    }
    output = Path(output).expanduser().resolve()
    if output.exists():
        raise EvaluationError(f"refusing to overwrite strict evaluator output: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def make_request(manifest_path: Path | str, quality_report_path: Path | str, receipt_path: Path | str,
                 output: Path | str, runtime_root: Path | str, worker_root: Path | str,
                 attempt_id: str = "seven-family-label-quality-evaluator-v2-strict-forward-001") -> dict[str, Any]:
    manifest_path = require_file(manifest_path, "quality manifest")
    quality_report_path = require_file(quality_report_path, "quality report")
    receipt_path = require_file(receipt_path, "quality receipt")
    runtime_root = Path(runtime_root).expanduser().resolve(); worker_root = Path(worker_root).expanduser().resolve()
    worker = worker_root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_family_label_quality_evaluator_v2_strict.py"
    runtime_paths = [runtime_root / "lagrangian-fluid-lab/scripts" / name for name in (
        "ds_data02_runtime_v8.py", "ds_data02_stage2_dispatch_v8.py", "ds_data02_strict_dispatch_v8.py")]
    inputs = [manifest_path, quality_report_path, receipt_path, worker, *runtime_paths]
    unique: list[Path] = []; seen: set[str] = set()
    for path in inputs:
        path = Path(path).expanduser().resolve()
        if not path.is_file():
            raise EvaluationError(f"strict evaluator request input is missing: {path}")
        if str(path) not in seen:
            unique.append(path); seen.add(str(path))
    hashes = {str(path): sha256_file(path) for path in unique}
    request = {
        "schema": "ds02.runner-request.v1", "request_schema": "ds02.stage2.family-label-quality-evaluator-v2-strict-request.v1",
        "attempt_id": attempt_id, "case_id": "DS02_STAGE2_SEVEN_FAMILY_LABEL_QUALITY_EVALUATOR_V2_STRICT", "family_id": "infra",
        "dataset_families": FAMILIES, "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 1,
        "max_wall_seconds": 300, "estimated_storage_bytes": 16 * 1024 * 1024,
        "cwd": str(worker_root / "lagrangian-fluid-lab/scripts"), "worktree_root": str(worker_root),
        "command": ["/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python", str(worker), "evaluate",
                     "--manifest", str(manifest_path), "--quality-report", str(quality_report_path), "--receipt", str(receipt_path),
                     "--output", "{attempt_root}/seven-family-label-quality-evaluator-v2-strict.json"],
        "input_files": [str(path) for path in unique], "input_sha256": hashes,
        "launch_allowed": True, "primary_launch_owner": "root", "status": "prepared_guard_pending_actual_CPU",
        "source_cost": {"small_json_bytes_read": sum(path.stat().st_size for path in unique), "materialized_label_h5_bytes_read": 0,
                        "original_trajectory_h5_bytes_read": 0, "part_bi4_bytes_read": 0, "solver_started": False, "cfd_or_model_run": False},
        "claim_boundary": {"physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "continuous_first_arrival": "UNKNOWN",
                            "hidden_recrossings": "UNKNOWN", "effective_split_safe": "UNKNOWN", "recovery_safe": "UNKNOWN",
                            "QN": "UNKNOWN", "QE": "UNKNOWN", "QI": "UNKNOWN", "qualification_credit": "none"},
        "strict_receipt_contract": "completed producer must bind exact report parent, attempt/case, output target, manifest/current/worker launch-end hashes",
    }
    output = Path(output).expanduser().resolve()
    if output.exists():
        raise EvaluationError(f"refusing to overwrite strict evaluator request: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return request


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    ev = sub.add_parser("evaluate")
    ev.add_argument("--manifest", type=Path, required=True); ev.add_argument("--quality-report", type=Path, required=True)
    ev.add_argument("--receipt", type=Path, required=True); ev.add_argument("--output", type=Path, required=True)
    req = sub.add_parser("make-request")
    req.add_argument("--manifest", type=Path, required=True); req.add_argument("--quality-report", type=Path, required=True)
    req.add_argument("--receipt", type=Path, required=True); req.add_argument("--output", type=Path, required=True)
    req.add_argument("--runtime-root", type=Path, required=True); req.add_argument("--worker-root", type=Path, required=True)
    req.add_argument("--attempt-id", default="seven-family-label-quality-evaluator-v2-strict-forward-001")
    args = parser.parse_args(argv)
    if args.command == "evaluate":
        evaluate(args.manifest, args.quality_report, args.receipt, args.output)
    else:
        make_request(args.manifest, args.quality_report, args.receipt, args.output, args.runtime_root, args.worker_root, args.attempt_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
