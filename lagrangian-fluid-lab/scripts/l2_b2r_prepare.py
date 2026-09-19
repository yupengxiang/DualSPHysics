#!/usr/bin/env python3
"""Standalone B2R preparation/recording entrypoint.

Examples (all commands are bounded metadata operations):

``python scripts/l2_b2r_prepare.py prepare --output /tmp/b2r.json``
    Writes a non-terminal study contract whose status is ``waiting_for_R2``.

``python scripts/l2_b2r_prepare.py register-attempt ...``
    Writes one immutable-shaped pre-run attempt record.  It does not launch a
    worker or update the shared resume state.

``python scripts/l2_b2r_prepare.py denominator --study ...``
    Computes a denominator including not-started, failed, incomplete and
    physical-failure rows.  Missing evaluation rows are retained explicitly.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from scripts.l2_b2r_contract import (
        DEFAULT_CASE_REGISTRY,
        B2RContractError,
        StudySpec,
        build_study_spec,
        load_evaluation_case_registry,
        validate_preparation_manifest,
    )
    from scripts.l2_b2r_records import (
        build_failure_denominator,
        create_attempt_record,
        validate_failure_denominator,
        write_attempt_record,
    )
except ModuleNotFoundError:  # direct ``python scripts/l2_b2r_prepare.py``
    from l2_b2r_contract import (
        DEFAULT_CASE_REGISTRY,
        B2RContractError,
        StudySpec,
        build_study_spec,
        load_evaluation_case_registry,
        validate_preparation_manifest,
    )
    from l2_b2r_records import (
        build_failure_denominator,
        create_attempt_record,
        validate_failure_denominator,
        write_attempt_record,
    )


def _read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text())


def _write_json(path: str | Path, payload: Any, *, overwrite: bool = False) -> dict[str, Any]:
    destination = Path(path)
    if destination.exists() and not overwrite:
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False).encode() + b"\n"
    temporary = destination.with_name(destination.name + ".partial")
    temporary.write_bytes(raw)
    temporary.replace(destination)
    return {"path": str(destination), "bytes": len(raw)}


def _spec_from_manifest(manifest: dict[str, Any]) -> StudySpec:
    validate_preparation_manifest(manifest)
    registry = manifest.get("data_contract", {}).get("evaluation_case_registry", {})
    rows = registry.get("physical_case_ids", [])
    if not isinstance(rows, list) or not rows:
        raise B2RContractError("study manifest has no physical-case denominator")
    # CLI denominator work deliberately reconstructs the design-only spec with
    # the gate closed.  An attempt ledger cannot open B2R or infer R2 completion.
    return StudySpec(evaluation_case_ids=tuple(rows))


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    r2_evidence = _read_json(args.r2_report) if args.r2_report else None
    _, manifest = build_study_spec(
        registry_path=args.registry,
        r2_evidence=r2_evidence,
        r0_verified=args.r0_verified,
    )
    validate_preparation_manifest(manifest)
    written = _write_json(args.output, manifest, overwrite=args.overwrite)
    return {
        "status": manifest["status"],
        "launch_allowed": manifest["launch_allowed"],
        "waiting_for_R2": manifest["status"] == "waiting_for_R2",
        "logical_run_count": manifest["study_design"]["logical_run_count"],
        "evaluation_case_count": manifest["data_contract"]["evaluation_case_registry"]["case_count"],
        "output": written,
    }


def register_attempt(args: argparse.Namespace) -> dict[str, Any]:
    registry = load_evaluation_case_registry(args.registry)
    record = create_attempt_record(
        logical_run_id=args.logical_run_id,
        route=args.route,
        seed=args.seed,
        physical_case_ids=registry["physical_case_ids"],
        execution_attempt_id=args.execution_attempt_id,
        status=args.status,
        worker_exit_status=args.worker_exit_status,
        training_completed=args.training_completed,
        evaluation_completed=args.evaluation_completed,
        model_physical_pass=args.model_physical_pass,
        retry_of=args.retry_of,
        data_contract_sha256=args.data_contract_sha256,
        model_contract_sha256=args.model_contract_sha256,
        r2_evidence_sha256=args.r2_evidence_sha256,
        failure_reason=args.failure_reason,
    )
    written = write_attempt_record(args.output, record, overwrite=args.overwrite)
    return {"status": "recorded", "execution_attempt_id": record["execution_attempt_id"], "output": written}


def denominator(args: argparse.Namespace) -> dict[str, Any]:
    manifest = _read_json(args.study)
    spec = _spec_from_manifest(manifest)
    records = [_read_json(path) for path in args.attempt]
    evaluations = [_read_json(path) for path in args.evaluation] if args.evaluation else None
    report = build_failure_denominator(spec, records, evaluation_results=evaluations)
    validate_failure_denominator(report)
    written = _write_json(args.output, report, overwrite=args.overwrite)
    return {
        "status": report["status"],
        "logical_run_denominator": report["logical_run_denominator"]["planned"],
        "logical_failures": report["logical_run_denominator"]["failure_count"],
        "evaluation_case_runs": report["evaluation_case_denominator"]["planned_case_run_count"],
        "evaluation_missing": report["evaluation_case_denominator"]["status_counts"]["missing"],
        "output": written,
    }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)

    prepare_parser = sub.add_parser("prepare", help="write the independent non-terminal B2R study contract")
    prepare_parser.add_argument("--registry", default=str(DEFAULT_CASE_REGISTRY))
    prepare_parser.add_argument("--r2-report", help="optional explicit R2 evidence; never reads shared resume state")
    prepare_parser.add_argument("--r0-verified", action="store_true")
    prepare_parser.add_argument("--output", required=True)
    prepare_parser.add_argument("--overwrite", action="store_true")
    prepare_parser.set_defaults(handler=prepare)

    attempt_parser = sub.add_parser("register-attempt", help="write one metadata-only training attempt record")
    attempt_parser.add_argument("--registry", default=str(DEFAULT_CASE_REGISTRY))
    attempt_parser.add_argument("--logical-run-id", required=True)
    attempt_parser.add_argument("--route", choices=("raw", "hybrid"), required=True)
    attempt_parser.add_argument("--seed", type=int, required=True)
    attempt_parser.add_argument("--execution-attempt-id")
    attempt_parser.add_argument("--status", choices=("not_started", "running", "completed", "failed"), default="not_started")
    attempt_parser.add_argument("--worker-exit-status", choices=("not_started", "running", "zero", "nonzero", "exception", "timeout", "guard_terminated"), default="not_started")
    attempt_parser.add_argument("--training-completed", action="store_true")
    attempt_parser.add_argument("--evaluation-completed", action="store_true")
    attempt_parser.add_argument("--model-physical-pass", choices=("not_evaluated", "pass", "fail", "unknown"), default="not_evaluated")
    attempt_parser.add_argument("--retry-of")
    attempt_parser.add_argument("--data-contract-sha256")
    attempt_parser.add_argument("--model-contract-sha256")
    attempt_parser.add_argument("--r2-evidence-sha256")
    attempt_parser.add_argument("--failure-reason")
    attempt_parser.add_argument("--output", required=True)
    attempt_parser.add_argument("--overwrite", action="store_true")
    attempt_parser.set_defaults(handler=register_attempt)

    denominator_parser = sub.add_parser("denominator", help="compute the full logical/case failure denominator")
    denominator_parser.add_argument("--study", required=True)
    denominator_parser.add_argument("--attempt", action="append", default=[])
    denominator_parser.add_argument("--evaluation", action="append", default=[])
    denominator_parser.add_argument("--output", required=True)
    denominator_parser.add_argument("--overwrite", action="store_true")
    denominator_parser.set_defaults(handler=denominator)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    result = args.handler(args)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
