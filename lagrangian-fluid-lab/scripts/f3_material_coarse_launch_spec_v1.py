#!/usr/bin/env python3
"""Build a canonical, non-executing launch projection for F3 coarse material.

The root/scheduler intake validates the fresh root authorization and the
scheduler-owned host-I/O reservation, but intentionally leaves the result as
a non-authorizing observation.  This sidecar is the next, still read-only
boundary: it converts a *complete* intake observation into an auditable dry
run specification with the fresh attempt namespace substituted into argv.

This module accepts only the intake's bounded strict-JSON/metadata inputs.  It
never opens, reads, or hashes the production HDF5; it never imports or calls a
worker, solver, GPU, queue, or runtime; and it never writes a registry,
ledger, denominator, gate, or PLAN.  A missing or invalid fresh receipt pair
is always returned as ``blocked_fail_closed`` with no canonical launch spec.
Even the ready projection remains dry-run-only and does not mint launch
authority or qualification credit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import f3_material_coarse_root_scheduler_intake_v1 as intake


LAB_ROOT = Path(__file__).resolve().parents[1]
CREATED_AT = "2026-09-29"

SCHEMA = "core.material.f3.coarse.canonical_dry_run_launch_spec.v1"
RECORD_ID = "f3-material-coarse-canonical-dry-run-launch-spec-v1"
LAUNCH_SCHEMA = "core.material.f3.coarse.dry_run_launch_projection.v1"
STATUS_BLOCKED = "blocked_fail_closed"
STATUS_READY = "canonical_dry_run_ready"

EXPECTED_CANDIDATE = {
    "configuration_id": "CORE-F3-MATERIAL-COARSE-s2",
    "job_id": "core-f3-material-coarse-s2",
    "family": "F3",
    "source_role": "coarse",
    "substeps": 2,
    "seeds": 512,
    "neighbour_variant": "baseline24",
}


class LaunchSpecError(ValueError):
    """Raised only when a serialized launch-spec boundary is malformed."""


def _mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    return {}


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _dedupe(values: Sequence[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value)
        if text and text not in result:
            result.append(text)
    return result


def _authorization(*, receipts_verified: bool) -> dict[str, Any]:
    return {
        "diagnostic_only": True,
        "formal": False,
        "formal_eligible": False,
        "T2_macro": False,
        "T2_path": False,
        "qualification": False,
        "credit": 0,
        "launch_admitted": False,
        "worker_launch_authorized": False,
        "root_authorization_receipt_verified": receipts_verified,
        "scheduler_host_io_reservation_verified": receipts_verified,
    }


def _execution_controls() -> dict[str, Any]:
    return {
        "sidecar_only": True,
        "dry_run_only": True,
        "source_hdf5_opened": False,
        "source_hdf5_read": False,
        "source_hdf5_hash_recomputed": False,
        "worker_started": False,
        "solver_started": False,
        "gpu_started": False,
        "queue_started": False,
        "registry_mutations": 0,
        "ledger_mutations": 0,
        "denominator_mutations": 0,
        "gate_mutations": 0,
        "plan_mutations": 0,
    }


def _dry_run_execution() -> dict[str, Any]:
    return {
        "dry_run": True,
        "would_execute": False,
        "execution_allowed": False,
        "worker_started": False,
        "solver_started": False,
        "gpu_started": False,
        "queue_mutations": 0,
        "registry_mutations": 0,
        "ledger_mutations": 0,
        "denominator_mutations": 0,
        "gate_mutations": 0,
        "plan_mutations": 0,
    }


def _intake_observation(report: Mapping[str, Any], report_errors: Sequence[str]) -> dict[str, Any]:
    validation = _mapping(report.get("validation"))
    checks = _mapping(validation.get("checks"))
    return {
        "schema": report.get("schema"),
        "record_id": report.get("record_id"),
        "status": report.get("status"),
        "checks": dict(checks),
        "blockers": list(validation.get("blockers", []))
        if isinstance(validation.get("blockers"), list)
        else [],
        "report_validation_errors": list(report_errors),
    }


def _blocked(
    report: Mapping[str, Any] | None,
    *,
    blockers: Sequence[Any],
    report_errors: Sequence[str] = (),
) -> dict[str, Any]:
    report = report if isinstance(report, Mapping) else {}
    observation = _intake_observation(report, report_errors)
    report_bindings = report.get("input_bindings")
    input_bindings = dict(report_bindings) if isinstance(report_bindings, Mapping) else {}
    validation = _mapping(report.get("validation"))
    checks = _mapping(validation.get("checks"))
    root_verified = checks.get("future_root_receipt_valid") is True
    scheduler_verified = checks.get("future_scheduler_receipt_valid") is True
    reasons = list(blockers)
    reasons.extend(validation.get("blockers", []))
    reasons.extend(report_errors)
    if not root_verified:
        reasons.append("fresh_root_authorization_receipt_not_verified")
    if not scheduler_verified:
        reasons.append("scheduler_owned_host_io_reservation_not_verified")
    return {
        "schema": SCHEMA,
        "record_id": RECORD_ID,
        "created_at": CREATED_AT,
        "status": STATUS_BLOCKED,
        "candidate": dict(_mapping(report.get("candidate"))) or dict(EXPECTED_CANDIDATE),
        "diagnostic_only": True,
        "dry_run": True,
        "canonical_dry_run_launch": None,
        "canonical_dry_run_launch_sha256": None,
        "verified_receipts": {
            "root_authorization": root_verified,
            "scheduler_owned_host_io_reservation": scheduler_verified,
            "pair_cross_binding": checks.get("receipt_pair_cross_binding_valid") is True,
        },
        "input_bindings": input_bindings,
        "intake_observation": observation,
        "authorization": _authorization(receipts_verified=False),
        "execution_controls": _execution_controls(),
        "blocking_reasons": _dedupe(reasons),
    }


def _relative_attempt_path(root: Path, namespace: Mapping[str, Any]) -> tuple[str, Path]:
    attempt_path = namespace.get("attempt_path")
    if not isinstance(attempt_path, str) or not attempt_path:
        raise LaunchSpecError("fresh attempt path is missing")
    relative = Path(attempt_path)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise LaunchSpecError("fresh attempt path is not canonical relative POSIX metadata")
    absolute_root = Path(os.path.abspath(os.fspath(root)))
    absolute = Path(os.path.abspath(os.fspath(absolute_root / relative)))
    try:
        absolute.relative_to(absolute_root)
    except ValueError as error:
        raise LaunchSpecError("fresh attempt path escapes the lab root") from error
    return attempt_path, absolute


def _expand_attempt(value: Any, attempt_dir: Path, label: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise LaunchSpecError(f"{label} is not a bounded string")
    return value.replace("{attempt_dir}", str(attempt_dir))


def _ready_projection(root: Path, report: Mapping[str, Any]) -> dict[str, Any]:
    projection = _mapping(report.get("binding_projection"))
    normalized = _mapping(projection.get("normalized_launch"))
    namespace = _mapping(projection.get("fresh_attempt_namespace"))
    observations = _mapping(report.get("receipt_observations"))
    fresh_root = _mapping(observations.get("fresh_root"))
    scheduler = _mapping(observations.get("scheduler"))
    root_authorization = _mapping(fresh_root.get("root_authorization"))
    scheduler_reservation = _mapping(scheduler.get("scheduler_reservation"))
    candidate = _mapping(report.get("candidate"))
    hashes = _mapping(projection.get("hashes"))

    if dict(candidate) != EXPECTED_CANDIDATE:
        raise LaunchSpecError("candidate projection drifted")
    if not isinstance(normalized.get("argv"), list) or not all(
        isinstance(item, str) for item in normalized["argv"]
    ):
        raise LaunchSpecError("normalized argv is not a string vector")
    if not isinstance(normalized.get("resume_argv_same_attempt"), list) or not all(
        isinstance(item, str) for item in normalized["resume_argv_same_attempt"]
    ):
        raise LaunchSpecError("normalized resume argv is not a string vector")
    if not isinstance(normalized.get("cwd"), str) or normalized["cwd"] != str(root):
        raise LaunchSpecError("normalized cwd does not match the selected lab root")
    if namespace.get("fresh") is not True or namespace.get("reused") is not False:
        raise LaunchSpecError("fresh namespace flags are not closed")
    attempt_path, attempt_dir = _relative_attempt_path(root, namespace)

    argv = [_expand_attempt(item, attempt_dir, "normalized argv item") for item in normalized["argv"]]
    resume_argv = [
        _expand_attempt(item, attempt_dir, "normalized resume argv item")
        for item in normalized["resume_argv_same_attempt"]
    ]
    output = _expand_attempt(normalized.get("output"), attempt_dir, "normalized output")
    if any("{attempt_dir}" in item for item in (*argv, *resume_argv, output)):
        raise LaunchSpecError("canonical launch projection retained an attempt placeholder")

    pair_id = projection.get("root_scheduler_pair_id")
    authorization_id = root_authorization.get("authorization_id")
    reservation_id = scheduler_reservation.get("reservation_id")
    if not all(isinstance(item, str) and item for item in (pair_id, authorization_id, reservation_id)):
        raise LaunchSpecError("receipt identity fields are missing")
    if projection.get("scheduler_owned_host_io_verified") is not True:
        raise LaunchSpecError("scheduler-owned host-I/O reservation is not verified")
    if not all(isinstance(hashes.get(key), str) for key in intake.HASH_KEYS):
        raise LaunchSpecError("current hash projection is incomplete")

    namespace_projection = dict(namespace)
    namespace_projection["attempt_path_absolute"] = str(attempt_dir)
    namespace_projection["attempt_path"] = attempt_path
    namespace_projection["namespace_sha256"] = projection.get("fresh_attempt_namespace_sha256")

    identity_core = {
        "family": candidate["family"],
        "configuration_id": candidate["configuration_id"],
        "job_id": candidate["job_id"],
        "source_role": candidate["source_role"],
        "pair_id": pair_id,
        "root_authorization_id": authorization_id,
        "scheduler_reservation_id": reservation_id,
        "attempt_id": namespace["attempt_id"],
        "namespace_nonce": namespace["namespace_nonce"],
        "normalized_launch_sha256": projection.get("normalized_launch_sha256"),
        "fresh_attempt_namespace_sha256": projection.get("fresh_attempt_namespace_sha256"),
        "root_receipt_sha256": _mapping(_mapping(report.get("input_bindings")).get("fresh_root_receipt")).get("sha256"),
        "scheduler_receipt_sha256": _mapping(_mapping(report.get("input_bindings")).get("scheduler_host_io_reservation")).get("sha256"),
    }
    if not all(isinstance(identity_core[key], str) for key in (
        "normalized_launch_sha256",
        "fresh_attempt_namespace_sha256",
        "root_receipt_sha256",
        "scheduler_receipt_sha256",
    )):
        raise LaunchSpecError("receipt and launch identity digests are incomplete")
    identity = dict(identity_core)
    identity["identity_sha256"] = _canonical_digest(identity_core)

    launch = {
        "schema": LAUNCH_SCHEMA,
        "candidate": dict(candidate),
        "mode": "dry_run",
        "dry_run": True,
        "would_execute": False,
        "execution_allowed": False,
        "cwd": normalized["cwd"],
        "argv": argv,
        "resume_argv_same_attempt": resume_argv,
        "output": output,
        "namespace": namespace_projection,
        "identity": identity,
        "resource_request": dict(scheduler_reservation.get("resource_request", {})),
        "host_io_reservation": dict(scheduler_reservation.get("host_io_reservation", {})),
        "source": {
            "path": next((item for index, item in enumerate(argv) if index and argv[index - 1] == "--source"), None),
            "sha256": hashes["source_sha256"],
            "opened_as_hdf5": False,
            "content_read": False,
            "hash_recomputed": False,
        },
        "execution": _dry_run_execution(),
    }
    return launch


def build_launch_spec(
    root: str | Path = LAB_ROOT,
    *,
    proposal_path: str | Path | None = None,
    host_io_admission_path: str | Path | None = None,
    root_receipt_path: str | Path | None = None,
    scheduler_receipt_path: str | Path | None = None,
) -> dict[str, Any]:
    """Build a bounded canonical dry-run projection without executing anything."""

    root_path = Path(os.path.abspath(os.fspath(root)))
    report: Mapping[str, Any] | None = None
    report_errors: list[str] = []
    try:
        report = intake.build_report(
            root_path,
            proposal_path=proposal_path,
            host_io_admission_path=host_io_admission_path,
            root_receipt_path=root_receipt_path,
            scheduler_receipt_path=scheduler_receipt_path,
        )
        report_errors = list(intake.validate_report(report))
    except Exception as error:  # fail closed for malformed bounded input or drift
        return _blocked(
            report,
            blockers=[f"intake_error:{type(error).__name__}:{error}"],
            report_errors=report_errors,
        )

    validation = _mapping(report.get("validation"))
    checks = _mapping(validation.get("checks"))
    if (
        report.get("status") != intake.STATUS_BOUND
        or checks.get("intake_contract_valid") is not True
        or validation.get("blockers") != []
        or report_errors
    ):
        return _blocked(report, blockers=[], report_errors=report_errors)

    try:
        launch = _ready_projection(root_path, report)
    except (LaunchSpecError, KeyError, TypeError, ValueError) as error:
        return _blocked(
            report,
            blockers=[f"canonical_projection_error:{type(error).__name__}:{error}"],
            report_errors=report_errors,
        )

    input_bindings = dict(_mapping(report.get("input_bindings")))
    result = {
        "schema": SCHEMA,
        "record_id": RECORD_ID,
        "created_at": CREATED_AT,
        "status": STATUS_READY,
        "candidate": dict(_mapping(report.get("candidate"))),
        "diagnostic_only": True,
        "dry_run": True,
        "canonical_dry_run_launch": launch,
        "canonical_dry_run_launch_sha256": _canonical_digest(launch),
        "verified_receipts": {
            "root_authorization": True,
            "scheduler_owned_host_io_reservation": True,
            "pair_cross_binding": True,
        },
        "input_bindings": input_bindings,
        "intake_observation": _intake_observation(report, report_errors),
        "authorization": _authorization(receipts_verified=True),
        "execution_controls": _execution_controls(),
        "blocking_reasons": [],
    }
    errors = validate_launch_spec(result)
    if errors:
        return _blocked(
            report,
            blockers=[f"serialized_spec_validation:{item}" for item in errors],
            report_errors=report_errors,
        )
    return result


def validate_launch_spec(value: Mapping[str, Any]) -> list[str]:
    """Validate the serialized sidecar envelope without reading campaign state."""

    errors: list[str] = []
    expected_top = {
        "schema",
        "record_id",
        "created_at",
        "status",
        "candidate",
        "diagnostic_only",
        "dry_run",
        "canonical_dry_run_launch",
        "canonical_dry_run_launch_sha256",
        "verified_receipts",
        "input_bindings",
        "intake_observation",
        "authorization",
        "execution_controls",
        "blocking_reasons",
    }
    if not isinstance(value, Mapping) or set(value) != expected_top:
        return ["spec.fields"]
    for key, expected in (
        ("schema", SCHEMA),
        ("record_id", RECORD_ID),
        ("created_at", CREATED_AT),
        ("diagnostic_only", True),
        ("dry_run", True),
    ):
        if value.get(key) != expected:
            errors.append(key)
    candidate = _mapping(value.get("candidate"))
    if dict(candidate) != EXPECTED_CANDIDATE:
        errors.append("candidate")
    if not isinstance(value.get("input_bindings"), Mapping):
        errors.append("input_bindings")
    if not isinstance(value.get("intake_observation"), Mapping):
        errors.append("intake_observation")
    if dict(_mapping(value.get("execution_controls"))) != _execution_controls():
        errors.append("execution_controls")
    if not isinstance(value.get("blocking_reasons"), list) or any(
        not isinstance(item, str) for item in value.get("blocking_reasons", [])
    ):
        errors.append("blocking_reasons")

    verified = _mapping(value.get("verified_receipts"))
    if set(verified) != {"root_authorization", "scheduler_owned_host_io_reservation", "pair_cross_binding"}:
        errors.append("verified_receipts.fields")
    elif any(type(verified.get(key)) is not bool for key in verified):
        errors.append("verified_receipts.types")

    status = value.get("status")
    launch = value.get("canonical_dry_run_launch")
    if status == STATUS_BLOCKED:
        if launch is not None:
            errors.append("blocked.launch_present")
        if value.get("canonical_dry_run_launch_sha256") is not None:
            errors.append("blocked.launch_digest")
        if not value.get("blocking_reasons"):
            errors.append("blocked.blocking_reasons")
        if dict(_mapping(value.get("authorization"))) != _authorization(receipts_verified=False):
            errors.append("blocked.authorization")
        if any(verified.get(key) is True for key in verified):
            # A partial observation may be present, but a blocked spec must
            # never claim that the complete receipt pair was verified.
            if all(verified.get(key) is True for key in verified):
                errors.append("blocked.receipts_complete")
        return errors

    if status != STATUS_READY:
        errors.append("status")
        return errors
    if value.get("blocking_reasons") != []:
        errors.append("ready.blocking_reasons")
    if dict(_mapping(value.get("authorization"))) != _authorization(receipts_verified=True):
        errors.append("ready.authorization")
    if not all(verified.get(key) is True for key in verified):
        errors.append("ready.receipts")
    if not isinstance(launch, Mapping):
        errors.append("ready.launch")
        return errors
    if launch.get("schema") != LAUNCH_SCHEMA:
        errors.append("launch.schema")
    if launch.get("mode") != "dry_run" or launch.get("dry_run") is not True:
        errors.append("launch.mode")
    for key in ("would_execute", "execution_allowed"):
        if launch.get(key) is not False:
            errors.append(f"launch.{key}")
    if not isinstance(launch.get("cwd"), str) or not isinstance(launch.get("output"), str):
        errors.append("launch.paths")
    for key in ("argv", "resume_argv_same_attempt"):
        vector = launch.get(key)
        if not isinstance(vector, list) or not vector or any(not isinstance(item, str) for item in vector):
            errors.append(f"launch.{key}")
        elif any("{attempt_dir}" in item for item in vector):
            errors.append(f"launch.{key}.placeholder")
    if "{attempt_dir}" in str(launch.get("output")):
        errors.append("launch.output.placeholder")
    if dict(_mapping(launch.get("execution"))) != _dry_run_execution():
        errors.append("launch.execution")
    identity = _mapping(launch.get("identity"))
    identity_digest = identity.get("identity_sha256")
    identity_core = {key: item for key, item in identity.items() if key != "identity_sha256"}
    if not isinstance(identity_digest, str) or identity_digest != _canonical_digest(identity_core):
        errors.append("launch.identity_sha256")
    digest = value.get("canonical_dry_run_launch_sha256")
    if not isinstance(digest, str) or digest != _canonical_digest(launch):
        errors.append("canonical_dry_run_launch_sha256")
    return errors


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=LAB_ROOT)
    parser.add_argument("--proposal", type=Path, default=None)
    parser.add_argument("--host-io-admission", type=Path, default=None)
    parser.add_argument("--root-receipt", type=Path, default=None)
    parser.add_argument("--scheduler-receipt", type=Path, default=None)
    args = parser.parse_args(argv)
    result = build_launch_spec(
        args.root,
        proposal_path=args.proposal,
        host_io_admission_path=args.host_io_admission,
        root_receipt_path=args.root_receipt,
        scheduler_receipt_path=args.scheduler_receipt,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False))
    return 0 if result["status"] == STATUS_READY else 2


if __name__ == "__main__":
    raise SystemExit(main())
