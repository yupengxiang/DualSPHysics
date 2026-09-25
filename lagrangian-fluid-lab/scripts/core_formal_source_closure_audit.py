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

from scripts.core_formal_launch_contract import (
    _code_closure,
    _load_json,
    _reference,
    _snapshot_comparison,
)


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


def build_audit(*, data_root: str | Path, historical_snapshot: str | Path,
                readiness: str | Path, launch_contract: str | Path) -> dict[str, Any]:
    root = Path(data_root).expanduser().resolve()
    snapshot_payload, _, snapshot_ref = _load_json(
        historical_snapshot, root=root, role="historical source closure")
    readiness_payload, _, readiness_ref = _load_json(
        readiness, root=root, role="formal readiness")
    launch_payload, _, launch_ref = _load_json(
        launch_contract, root=root, role="formal launch contract")
    closure = _code_closure(root, root)
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
            "required_artifact": "a new source-closure JSON containing all eight current file hashes and closure_sha256",
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
        "formal_job_count": 0,
        "launch_allowed": False,
        "inputs": {
            "historical_snapshot": snapshot_ref,
            "formal_readiness": readiness_ref,
            "formal_launch_contract": launch_ref,
        },
        "current_source_closure": closure,
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
