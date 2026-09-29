#!/usr/bin/env python3
"""Audit and propose a fresh Core formal source closure without admitting it.

The current required source closure is recomputed from disk and compared with a
previous formal-release snapshot.  The resulting JSON is a proposal-only
observation: it records the exact current hashes and the checks still needed
before a planner may admit a nine-run matrix.  It never changes the source
snapshot, registry, ledger, or execution state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts.core_formal_planner import materialize_formal_source_closure
from scripts.core_formal_launch_contract import _load_json, _reference


SCHEMA = "core.formal_source_closure_audit.v1"
PROPOSAL_SCHEMA = "core.formal_source_closure_proposal.v1"


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _resolve(value: str | Path, root: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def _current_source_reference(root: Path) -> dict[str, Any]:
    path = (root / "scripts/core_formal_source_closure_audit.py").resolve()
    return _reference(path, root)


def _historical_rows(snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = snapshot.get("files")
    if not isinstance(rows, list):
        rows = []
    return [dict(row) for row in rows if isinstance(row, Mapping)]


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdefABCDEF" for char in value)
    )


def _closure_digest(rows: Sequence[Mapping[str, Any]]) -> str:
    encoded = json.dumps([
        {"relative_path": row["relative_path"], "sha256": row["sha256"]}
        for row in rows
    ], sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def _normalized_closure_rows(payload: Mapping[str, Any], required: Sequence[str], *,
                             snapshot: bool) -> tuple[list[dict[str, Any]], list[str]]:
    expected = list(required)
    errors: list[str] = []
    if payload.get("required_files") != expected:
        errors.append("required_files")
    if snapshot:
        if not isinstance(payload.get("schema"), str) or not payload["schema"].startswith(
                "core.formal_source_closure."):
            errors.append("schema")
        if not isinstance(payload.get("closure_version"), str) or not payload["closure_version"]:
            errors.append("closure_version")
        if payload.get("hash_algorithm") != "sha256":
            errors.append("hash_algorithm")
        if payload.get("complete") is not True:
            errors.append("complete")
        if payload.get("missing_files") != []:
            errors.append("missing_files")
        if "required_file_count" in payload and payload.get("required_file_count") != len(expected):
            errors.append("required_file_count")
    rows = payload.get("files")
    normalized: list[dict[str, Any]] = []
    if not isinstance(rows, list):
        errors.append("files")
        return normalized, errors
    if len(rows) != len(expected):
        errors.append("file_count")
    for index, expected_name in enumerate(expected):
        if index >= len(rows):
            break
        row = rows[index]
        if not isinstance(row, Mapping):
            errors.append(f"files[{index}]")
            continue
        if row.get("relative_path") != expected_name:
            errors.append(f"files[{index}].relative_path")
        sha256 = row.get("sha256")
        byte_count = row.get("bytes")
        if not _valid_sha256(sha256):
            errors.append(f"files[{index}].sha256")
        if type(byte_count) is not int or byte_count < 0:
            errors.append(f"files[{index}].bytes")
        normalized.append({
            "relative_path": row.get("relative_path"),
            "sha256": sha256.lower() if isinstance(sha256, str) else sha256,
            "bytes": byte_count,
        })
    if snapshot:
        declared_closure = payload.get("closure_sha256")
        if not _valid_sha256(declared_closure):
            errors.append("closure_sha256")
        elif not errors and declared_closure.lower() != _closure_digest(normalized):
            errors.append("closure_sha256")
    return normalized, errors


def _snapshot_comparison(current: Mapping[str, Any], snapshot: Mapping[str, Any],
                         reference: Mapping[str, Any]) -> dict[str, Any]:
    """Compare live closure data with a named historical baseline only."""
    historical_rows = _historical_rows(snapshot)
    required = current.get("required_files")
    required = list(required) if isinstance(required, list) else []
    historical_required_for_validation = snapshot.get("required_files")
    historical_required_for_validation = (
        list(historical_required_for_validation)
        if isinstance(historical_required_for_validation, list) else []
    )
    historical_normalized, snapshot_errors = _normalized_closure_rows(
        snapshot, historical_required_for_validation, snapshot=True
    )
    live_normalized, current_errors = _normalized_closure_rows(
        current, required, snapshot=False
    )
    historical_by_name = {row["relative_path"]: row["sha256"]
                          for row in historical_normalized
                          if isinstance(row.get("relative_path"), str)}
    live_by_name = {row["relative_path"]: row["sha256"]
                    for row in live_normalized
                    if isinstance(row.get("relative_path"), str)}
    mismatch = sorted(
        name for name in set(historical_by_name) | set(live_by_name)
        if historical_by_name.get(name) != live_by_name.get(name)
    )
    snapshot_closure = snapshot.get("closure_sha256")
    current_closure = current.get("closure_sha256")
    matches_current = (
        not snapshot_errors
        and not current_errors
        and historical_required_for_validation == required
        and historical_normalized == live_normalized
        and isinstance(snapshot_closure, str)
        and isinstance(current_closure, str)
        and snapshot_closure.lower() == current_closure.lower()
    )
    historical_required = snapshot.get("required_files")
    if not isinstance(historical_required, list):
        historical_required = [row["relative_path"] for row in historical_rows
                               if isinstance(row.get("relative_path"), str)]
    historical_baseline = {
        "reference": dict(reference),
        "schema": snapshot.get("schema"),
        "closure_version": snapshot.get("closure_version"),
        "closure_sha256": snapshot.get("closure_sha256"),
        "required_files": list(historical_required),
        "required_file_count": len(historical_required),
        "files": historical_rows,
    }
    return {
        "snapshot": dict(reference),
        "snapshot_version": snapshot.get("closure_version"),
        "snapshot_closure_sha256": snapshot.get("closure_sha256"),
        "current_closure_sha256": current.get("closure_sha256"),
        "live_required_files": list(current.get("required_files", ())),
        "live_required_file_count": int(current.get("required_file_count", 0)),
        "historical_required_files": list(historical_required),
        "historical_required_file_count": len(historical_required),
        "mismatch_files": mismatch,
        "snapshot_integrity_valid": not snapshot_errors,
        "snapshot_integrity_errors": snapshot_errors,
        "matches_current": matches_current,
        "fresh_snapshot_required": not matches_current,
        "comparison_type": "historical_baseline_only",
        "mismatch_semantics": (
            "mismatch_files compare the named historical baseline with the live workspace; "
            "they are not a failure of the freshly rehashed live file set"
        ),
        "historical_baseline": historical_baseline,
        "live_closure_is_not_historical_baseline": True,
    }


def build_audit(*, data_root: str | Path, historical_snapshot: str | Path,
                readiness: str | Path, launch_contract: str | Path) -> dict[str, Any]:
    root = Path(data_root).expanduser().resolve()
    snapshot_payload, _, snapshot_ref = _load_json(
        historical_snapshot, root=root, role="historical source closure")
    readiness_payload, _, readiness_ref = _load_json(
        readiness, root=root, role="formal readiness")
    launch_payload, _, launch_ref = _load_json(
        launch_contract, root=root, role="formal launch contract")
    closure = materialize_formal_source_closure(root)
    comparison = _snapshot_comparison(closure, snapshot_payload, snapshot_ref)
    mismatch_files = list(comparison["mismatch_files"])
    readiness_blockers = list(readiness_payload.get("upstream_admission_blockers", ()))
    readiness_blockers.extend(
        item.get("code") for item in readiness_payload.get("blockers", ())
        if isinstance(item, Mapping) and item.get("code")
    )
    readiness_blockers = sorted(set(readiness_blockers))
    exact_next_checks = [
        {
            "check": "materialize_fresh_source_closure",
            "required_artifact": (
                "a new source-closure JSON containing all "
                f"{closure['required_file_count']} current required file hashes and closure_sha256"
            ),
            "observed": False,
            "why": "the current audit is a proposal and must not silently become the admitted planner snapshot",
        },
        {
            "check": "rebind_formal_admission_and_readiness",
            "required_artifact": "new formal admission/readiness receipt bound to the fresh closure hash",
            "observed": False,
            "why": "the existing readiness chain still carries STALE_SOURCE_CLOSURE",
        },
        {
            "check": "formal_manifest_release",
            "required_artifact": "three-family reader manifest with formal_release=true and SHA binding",
            "observed": False,
            "why": "the current F3 source manifest remains formal_release=false",
        },
        {
            "check": "third_t1_and_validation_gate",
            "required_artifact": "third T1 family with 32 production cases and four validation cases",
            "observed": False,
            "why": "current admission observes 2 T1 families and 8 validation cases",
        },
        {
            "check": "evaluator_denominator_and_failure_penalty",
            "required_artifact": "phase-plan/evaluator contract remains fixed and unit-penalizes failed frames",
            "observed": readiness_payload.get("checks", {}).get(
                "evaluator_failure_penalty_contract") is True,
            "why": "a failed rollout must retain every registered future frame",
        },
        {
            "check": "resource_and_same_card_admission",
            "required_artifact": "fresh live free-GPU/free-RAM/PSI/process observation for each host/card",
            "observed": False,
            "why": "single-worker 16-update measurements do not prove co-location safety",
        },
        {
            "check": "planner_reopen",
            "required_artifact": "core_formal_planner hold report with nine jobs only after all prior checks pass",
            "observed": False,
            "why": "the current launch contract explicitly emits zero formal jobs",
        },
    ]
    checks = {
        "required_file_set_complete": closure["complete"],
        "current_hashes_are_sha256": all(
            isinstance(item.get("sha256"), str) and len(item["sha256"]) == 64
            for item in closure["files"]
        ),
        "historical_snapshot_matches_current": comparison["matches_current"],
        "fresh_source_closure_admitted": False,
        "formal_readiness_unblocked": readiness_payload.get("status") == "ready",
        "launch_contract_unblocked": launch_payload.get("launch_allowed") is True,
        "launch_contract_emits_zero_jobs": launch_payload.get("formal_job_count") == 0,
    }
    blockers = []
    if mismatch_files:
        blockers.append({
            "code": "STALE_SOURCE_CLOSURE",
            "message": "historical formal source snapshot does not match current required files",
            "observed": {"mismatch_files": mismatch_files,
                         "historical_closure_sha256": comparison["snapshot_closure_sha256"],
                         "current_closure_sha256": comparison["current_closure_sha256"]},
            "required": "fresh source closure proposal admitted by root",
        })
    if not comparison["snapshot_integrity_valid"]:
        blockers.append({
            "code": "INVALID_SOURCE_CLOSURE_SNAPSHOT",
            "message": "historical source snapshot failed structural or closure-hash validation",
            "observed": comparison["snapshot_integrity_errors"],
            "required": "a structurally valid source closure snapshot",
        })
    if not checks["required_file_set_complete"]:
        blockers.append({"code": "SOURCE_CLOSURE_INCOMPLETE",
                         "message": "one or more required source files are missing",
                         "observed": closure["missing_files"],
                         "required": closure["required_files"]})
    if not checks["formal_readiness_unblocked"]:
        blockers.append({"code": "FORMAL_READINESS_BLOCKED",
                         "message": "formal readiness remains blocked",
                         "observed": readiness_blockers,
                         "required": "all formal readiness gates pass"})
    blockers.append({"code": "FRESH_CLOSURE_NOT_ADMITTED",
                     "message": "this artifact proposes hashes but does not admit a training source snapshot",
                     "observed": False, "required": True})
    return {
        "schema": SCHEMA,
        "record_id": "core-formal-source-closure-audit-20260921",
        "status": "proposal_only_blocked",
        "proposal_only": True,
        "formal_release": False,
        "formal_training_allowed": False,
        "formal_job_count": 0,
        "launch_allowed": False,
        "root_admission_granted": False,
        "inputs": {
            "historical_snapshot": snapshot_ref,
            "formal_readiness": readiness_ref,
            "formal_launch_contract": launch_ref,
        },
        "live_source_closure": closure,
        "current_source_closure": closure,
        "historical_baseline": comparison["historical_baseline"],
        "historical_comparison": comparison,
        "fresh_source_closure_proposal": {
            "schema": PROPOSAL_SCHEMA,
            "closure_sha256": closure["closure_sha256"],
            "files": closure["files"],
            "formal_release": False,
            "admitted": False,
            "used_for_formal_training": False,
            "requires_root_admission": True,
            "source_audit_implementation": _current_source_reference(root),
        },
        "checks": checks,
        "readiness_blockers": readiness_blockers,
        "exact_next_checks": exact_next_checks,
        "blockers": blockers,
        "nine_run_launch_contract": {
            "required_formal_job_count": 9,
            "observed_formal_job_count": launch_payload.get("formal_job_count"),
            "launch_allowed": launch_payload.get("launch_allowed"),
            "run_ids": [row.get("run_id") for row in launch_payload.get("run_matrix", ())
                        if isinstance(row, Mapping)],
        },
        "execution_constraints": {
            "read_only": True,
            "source_snapshot_written": False,
            "formal_job_specs_written": False,
            "formal_jobs_submitted": False,
            "formal_runs_started": 0,
            "optimizer_started": False,
            "gpu_started": False,
            "solver_started": False,
            "registry_written": False,
            "ledger_written": False,
        },
        "admission_next_step": (
            "root reviews the exact current required-file hashes, materializes/adopts the fresh closure, "
            "rebinds formal readiness, and only then re-runs core_formal_planner; no training is authorized by this audit"
        ),
    }


def write_json(path: str | Path, payload: Mapping[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True,
                                    ensure_ascii=False, allow_nan=False) + "\n",
                          encoding="utf-8")
    temporary.replace(target)


def write_sha256(path: str | Path, *, source: str | Path) -> None:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    source_path = Path(source).expanduser().resolve()
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(f"{sha256_file(source_path)}  {source_path.name}\n", encoding="utf-8")
    temporary.replace(target)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--historical-snapshot", type=Path, required=True)
    parser.add_argument("--readiness", type=Path, required=True)
    parser.add_argument("--launch-contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sha256-output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = build_audit(
        data_root=args.data_root,
        historical_snapshot=args.historical_snapshot,
        readiness=args.readiness,
        launch_contract=args.launch_contract,
    )
    write_json(args.output, report)
    if args.sha256_output is not None:
        write_sha256(args.sha256_output, source=args.output)
    print(json.dumps({
        "status": report["status"],
        "formal_job_count": report["formal_job_count"],
        "mismatch_files": report["historical_comparison"]["mismatch_files"],
        "current_closure_sha256": report["current_source_closure"]["closure_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
