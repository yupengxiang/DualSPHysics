#!/usr/bin/env python3
"""Bounded JSON-only intake for the F3 coarse material launch boundary.

This module joins the committed coarse proposal and the committed diagnostic
host-I/O admission with two *future* receipts: a fresh root admission receipt
and a scheduler-owned host-I/O reservation.  The receipts must bind the exact
proposal/adapter bytes, current ``core_material.py``/``core_runtime.py`` and
runtime-spec/job-spec hashes, the already frozen source HDF5 hash claim, the
normalized module argv/cwd, and one new attempt namespace.  The two future
receipts also cross-bind one another.

The intake is deliberately non-authorizing.  It only accepts bounded strict
JSON and small source/job-spec/runtime metadata.  The source HDF5 is inspected
with ``lstat`` for metadata only: it is never opened, read, or hashed here.
The intake never starts, stops, restarts, or queues a worker, solver, GPU, or
runtime, and it never writes a registry, ledger, denominator, gate, or PLAN.
Even a structurally complete pair of receipts remains diagnostic-only and
cannot mint launch authority or qualification credit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
from typing import Any, Mapping, Sequence


LAB_ROOT = Path(__file__).resolve().parents[1]
CREATED_AT = "2026-09-28"

SCHEMA = "core.material.f3.coarse.root_scheduler_intake.v1"
RECORD_ID = "f3-material-coarse-root-scheduler-intake-v1"
ROOT_RECEIPT_SCHEMA = "core.material.f3.coarse.fresh_root_admission_receipt.v1"
ROOT_RECEIPT_ID = "f3-material-coarse-fresh-root-admission-receipt-v1"
SCHEDULER_RECEIPT_SCHEMA = "core.material.f3.coarse.scheduler_host_io_reservation.v1"
SCHEDULER_RECEIPT_ID = "f3-material-coarse-scheduler-host-io-reservation-v1"

CANDIDATE_ID = "CORE-F3-MATERIAL-COARSE-s2"
JOB_ID = "core-f3-material-coarse-s2"

PROPOSAL = Path("reports/F3-MATERIAL-COARSE-PROPOSAL-2026-09-28.json")
HOST_IO_ADMISSION = Path("reports/F3-MATERIAL-COARSE-HOST-IO-ADMISSION-2026-09-28.json")
CORE_MATERIAL = Path("scripts/core_material.py")
CORE_RUNTIME = Path("scripts/core_runtime.py")
SOURCE_H5 = Path("campaigns/l1-resume/data/continuation/R0081818-NOMINAL.h5")
JOB_SPEC = Path("campaigns/core-v1/material/jobs/core-f3-material-coarse-s2.json")
RUNTIME_SPEC = Path(
    "campaigns/core-v1/material/evidence/"
    "f3-qualification-diagnostic-runtime-spec-2026-09-19.json"
)

ROOT_RECEIPT = Path(
    "campaigns/core-v1/material/evidence/"
    "f3-material-coarse-root-scheduler-intake-v1/fresh-root-receipt.json"
)
SCHEDULER_RECEIPT = Path(
    "campaigns/core-v1/material/evidence/"
    "f3-material-coarse-root-scheduler-intake-v1/"
    "scheduler-host-io-reservation.json"
)

DEFAULT_REPORT = Path("reports/F3-MATERIAL-COARSE-ROOT-SCHEDULER-INTAKE-V1-2026-09-28.json")
DEFAULT_ZH_CN = Path(
    "reports/F3-MATERIAL-COARSE-ROOT-SCHEDULER-INTAKE-V1-2026-09-28.zh-CN.md"
)

STATUS_MISSING = "blocked_missing_fresh_root_scheduler_receipts"
STATUS_INVALID = "blocked_invalid_fresh_root_scheduler_receipts"
STATUS_BOUND = "fresh_root_scheduler_receipts_bound_non_authorizing"

MAX_JSON_BYTES = 256 * 1024
MAX_SMALL_FILE_BYTES = 8 * 1024 * 1024
MAX_REFERENCE_LENGTH = 512

HASH_KEYS = (
    "core_material_sha256",
    "source_sha256",
    "job_spec_sha256",
    "core_runtime_sha256",
    "runtime_spec_sha256",
)

ROOT_RECEIPT_FIELDS = {
    "schema",
    "record_id",
    "status",
    "pair_id",
    "synthetic",
    "binding",
    "counterparty",
    "fresh_root",
    "root_authorization",
    "side_effects",
}
SCHEDULER_RECEIPT_FIELDS = {
    "schema",
    "record_id",
    "status",
    "pair_id",
    "synthetic",
    "binding",
    "counterparty",
    "scheduler_reservation",
    "side_effects",
}
BINDING_FIELDS = {
    "proposal",
    "host_io_admission",
    "hashes",
    "normalized_launch",
    "normalized_launch_sha256",
    "fresh_attempt_namespace",
    "fresh_attempt_namespace_sha256",
}
COUNTERPARTY_FIELDS = {"path", "binding_sha256", "pair_id"}
FRESH_NAMESPACE_FIELDS = {
    "attempt_root",
    "attempt_id",
    "attempt_path",
    "namespace_template",
    "namespace_nonce",
    "fresh",
    "reused",
    "same_attempt_resume_only",
    "historical_attempt_reuse_forbidden",
}
ROOT_AUTHORIZATION_FIELDS = {
    "authorization_id",
    "root_authorized",
    "single_use",
    "consumed",
}
FRESH_ROOT_FIELDS = {"attempt_id", "attempt_path", "created", "reused", "root_owned"}
SCHEDULER_RESERVATION_FIELDS = {
    "reservation_id",
    "reservation_active",
    "scheduler_owned_host_io_verified",
    "resource_request",
    "host_io_reservation",
    "single_use",
    "consumed",
}
HOST_IO_RESERVATION_FIELDS = {
    "io_weight",
    "owned_io_weight",
    "io_capacity",
    "filesystem",
    "snapshot_id",
}
SIDE_EFFECT_FIELDS = {
    "worker_started",
    "solver_started",
    "gpu_started",
    "queue_mutations",
    "registry_mutations",
    "ledger_mutations",
    "denominator_mutations",
    "gate_mutations",
    "plan_mutations",
}

SHA256 = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z", re.ASCII)
ATTEMPT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z", re.ASCII)
NAMESPACE_NONCE = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)

O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)


class IntakeError(ValueError):
    """A missing, unsafe, malformed, or drifted bounded input."""

    def __init__(self, message: str, *, code: str = "invalid_input") -> None:
        super().__init__(message)
        self.code = code


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise IntakeError(f"duplicate JSON object key: {key}", code="duplicate_json_key")
        result[key] = value
    return result


def _reject_constant(token: str) -> Any:
    raise IntakeError(f"non-standard JSON constant is not permitted: {token}", code="non_strict_json")


def _identity(value: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
        value.st_nlink,
    )


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _display_path(root: Path, path: Path) -> str:
    absolute = _absolute(path)
    try:
        return absolute.relative_to(_absolute(root)).as_posix()
    except ValueError:
        return absolute.as_posix()


def _resolve(root: Path, value: str | Path) -> Path:
    path = Path(value)
    return _absolute(path if path.is_absolute() else root / path)


def _assert_no_symlink_components(path: Path, label: str) -> None:
    absolute = _absolute(path)
    current = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        current /= component
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            continue
        except OSError as error:
            raise IntakeError(f"could not inspect {label} path", code="path_inspection") from error
        if stat.S_ISLNK(info.st_mode):
            raise IntakeError(f"{label} path contains a symlink", code="symlink_path")


def _read_bounded(path: Path, *, label: str, limit: int) -> tuple[bytes, dict[str, Any]]:
    """Read one stable, bounded regular file without following links."""

    _assert_no_symlink_components(path, label)
    descriptor: int | None = None
    try:
        descriptor = os.open(os.fspath(path), os.O_RDONLY | O_NOFOLLOW | O_CLOEXEC)
    except FileNotFoundError as error:
        raise IntakeError(f"{label} is missing: {_display_path(LAB_ROOT, path)}", code="missing_file") from error
    except OSError as error:
        raise IntakeError(f"{label} cannot be opened safely", code="open_failed") from error

    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise IntakeError(f"{label} is not a regular file", code="not_regular_file")
        if before.st_nlink != 1:
            raise IntakeError(f"{label} must have exactly one hard link", code="hardlink")
        if before.st_size > limit:
            raise IntakeError(f"{label} exceeds the bounded input limit", code="oversize")

        chunks: list[bytes] = []
        total = 0
        while True:
            block = os.read(descriptor, min(1024 * 1024, limit + 1 - total))
            if not block:
                break
            total += len(block)
            if total > limit:
                raise IntakeError(f"{label} exceeds the bounded input limit", code="oversize")
            chunks.append(block)

        after = os.fstat(descriptor)
        named = os.stat(path, follow_symlinks=False)
        if _identity(before) != _identity(after) or _identity(after) != _identity(named) or total != before.st_size:
            raise IntakeError(f"{label} changed while being read", code="drift")
        payload = b"".join(chunks)
        return payload, {"bytes": total, "sha256": hashlib.sha256(payload).hexdigest()}
    except IntakeError:
        raise
    except OSError as error:
        raise IntakeError(f"{label} could not be read safely", code="read_failed") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _empty_ref(root: Path, path: Path, role: str, mode: str) -> dict[str, Any]:
    return {
        "path": _display_path(root, path),
        "role": role,
        "mode": mode,
        "exists": False,
        "bytes": None,
        "sha256": None,
        "error": "missing_file",
    }


def _read_json_document(root: Path, path: Path, *, role: str) -> tuple[dict[str, Any] | None, dict[str, Any], str | None]:
    reference = _empty_ref(root, path, role, "bounded_strict_json")
    try:
        raw, metadata = _read_bounded(path, label=role, limit=MAX_JSON_BYTES)
    except IntakeError as error:
        reference["error"] = error.code
        return None, reference, str(error)
    reference.update({"exists": True, **metadata})
    reference.pop("error", None)
    try:
        decoded = raw.decode("utf-8", errors="strict")
        value = json.loads(decoded, object_pairs_hook=_strict_object, parse_constant=_reject_constant)
    except IntakeError as error:
        reference["error"] = error.code
        return None, reference, str(error)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        reference["error"] = "invalid_json"
        return None, reference, f"{role} is not strict UTF-8 JSON"
    if not isinstance(value, dict):
        reference["error"] = "json_not_object"
        return None, reference, f"{role} must be a JSON object"
    return value, reference, None


def _read_small_file(root: Path, path: Path, *, role: str) -> tuple[dict[str, Any], str | None]:
    reference = _empty_ref(root, path, role, "bounded_small_file")
    try:
        _, metadata = _read_bounded(path, label=role, limit=MAX_SMALL_FILE_BYTES)
    except IntakeError as error:
        reference["error"] = error.code
        return reference, str(error)
    reference.update({"exists": True, **metadata})
    reference.pop("error", None)
    return reference, None


def _source_metadata(root: Path, path: Path, *, claimed_sha256: Any) -> tuple[dict[str, Any], str | None]:
    """Collect source metadata only; never opens or hashes the HDF5."""

    reference: dict[str, Any] = {
        "path": _display_path(root, path),
        "role": "read-only coarse native source; prior hash claim only",
        "mode": "lstat_metadata_only",
        "exists": False,
        "regular_file": False,
        "symlink": False,
        "bytes": None,
        "sha256": claimed_sha256 if isinstance(claimed_sha256, str) else None,
        "hash_recomputed": False,
        "opened_as_hdf5": False,
        "read": False,
    }
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        reference["error"] = "missing_file"
        return reference, "source HDF5 metadata is missing"
    except OSError as error:
        reference["error"] = "metadata_failed"
        return reference, f"source HDF5 metadata failed: {type(error).__name__}"
    reference["exists"] = True
    reference["regular_file"] = stat.S_ISREG(info.st_mode)
    reference["symlink"] = stat.S_ISLNK(info.st_mode)
    reference["bytes"] = info.st_size
    if not reference["regular_file"] or reference["symlink"]:
        reference["error"] = "source_not_regular_file"
        return reference, "source HDF5 is not a regular non-symlink file"
    return reference, None


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_keys(value: Any, expected: set[str], label: str, errors: list[str]) -> bool:
    if not isinstance(value, Mapping) or set(value) != expected:
        errors.append(f"{label}.fields")
        return False
    return True


def _exact(value: Any, expected: Any, label: str, errors: list[str]) -> bool:
    ok = value == expected
    if not ok:
        errors.append(label)
    return ok


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _load_host_io_admission_validator() -> Any:
    """Load the validator from either supported CLI/module entry point."""

    if __package__:
        from scripts import f3_material_coarse_host_io_admission_v1 as host_adapter
    else:
        import f3_material_coarse_host_io_admission_v1 as host_adapter
    return host_adapter


def _expected_candidate() -> dict[str, Any]:
    return {
        "configuration_id": CANDIDATE_ID,
        "job_id": JOB_ID,
        "family": "F3",
        "source_role": "coarse",
        "substeps": 2,
        "seeds": 512,
        "neighbour_variant": "baseline24",
    }


def _expected_normalized_launch(root: Path) -> dict[str, Any]:
    source = _resolve(root, SOURCE_H5)
    argv = [
        str(root / ".venv/bin/python"),
        "-m",
        "scripts.core_material",
        "--source",
        str(source),
        "--output",
        "{attempt_dir}/material.h5",
        "--seeds",
        "512",
        "--substeps",
        "2",
        "--neighbour-variant",
        "baseline24",
    ]
    return {
        "cwd": str(root),
        "argv": argv,
        "resume_argv_same_attempt": [*argv, "--resume"],
        "full_native_window": True,
        "stop_after": None,
        "output": "{attempt_dir}/material.h5",
    }


def _expected_proposal_namespace() -> dict[str, Any]:
    attempt_root = f"campaigns/core-v1/runtime/attempts/{JOB_ID}"
    return {
        "created": False,
        "attempt_root": attempt_root,
        "namespace_template": attempt_root + "/<fresh-attempt-id>",
        "attempt_id_policy": "new scheduler-generated identity; never reuse a historical attempt directory",
        "same_attempt_resume_only": True,
        "historical_attempt_reuse_forbidden": True,
        "proposal_created_path": None,
    }


def _resource_request(job: Mapping[str, Any]) -> dict[str, Any]:
    resources = _mapping(job.get("resources"))
    return {
        "cpu_cores": resources.get("cpu_cores"),
        "ram_mib": resources.get("ram_mib"),
        "gpu_peak_mib": resources.get("gpu_peak_mib"),
        "io_weight": resources.get("io_weight"),
    }


def _proposal_and_host_checks(
    root: Path,
    proposal: Mapping[str, Any] | None,
    host: Mapping[str, Any] | None,
    proposal_ref: Mapping[str, Any],
    host_ref: Mapping[str, Any],
    current_refs: Mapping[str, Mapping[str, Any]],
    job: Mapping[str, Any] | None,
    runtime_spec: Mapping[str, Any] | None,
    source_ref: Mapping[str, Any],
) -> tuple[dict[str, bool], list[str], dict[str, Any]]:
    checks: dict[str, bool] = {}
    errors: list[str] = []
    proposal = proposal if isinstance(proposal, Mapping) else {}
    host = host if isinstance(host, Mapping) else {}
    job = job if isinstance(job, Mapping) else {}
    runtime_spec = runtime_spec if isinstance(runtime_spec, Mapping) else {}

    candidate = _mapping(proposal.get("candidate"))
    proposal_state = _mapping(proposal.get("proposal_state"))
    expected_candidate = _expected_candidate()
    expected_state = {
        "proposal_only": True,
        "diagnostic_only": True,
        "formal": False,
        "formal_eligible": False,
        "qualification_claim": "none",
        "qualification_credit": 0,
        "T2_credit": 0,
        "T2_macro": False,
        "T2_path": False,
        "launch_admitted": False,
    }
    proposal_checks = [
        _exact(proposal.get("schema"), "core.material.f3.coarse.proposal.v1", "proposal.schema", errors),
        _exact(proposal.get("status"), "proposal_only_fail_closed", "proposal.status", errors),
        _exact(dict(candidate), expected_candidate, "proposal.candidate", errors),
        _exact(dict(proposal_state), expected_state, "proposal.proposal_state", errors),
    ]
    proposal_bindings = _mapping(proposal.get("input_bindings"))
    expected_binding_paths = {
        "core_material": str(CORE_MATERIAL),
        "source_h5": str(SOURCE_H5),
        "job_spec": str(JOB_SPEC),
        "current_frozen_worker": str(CORE_RUNTIME),
        "runtime_spec": str(RUNTIME_SPEC),
    }
    for name, expected_path in expected_binding_paths.items():
        binding = _mapping(proposal_bindings.get(name))
        proposal_checks.append(_exact(binding.get("path"), expected_path, f"proposal.input_bindings.{name}.path", errors))
    source_binding = _mapping(proposal_bindings.get("source_h5"))
    proposal_checks.extend(
        [
            _exact(source_binding.get("hash_only"), True, "proposal.source_h5.hash_only", errors),
            _exact(source_binding.get("opened_as_hdf5"), False, "proposal.source_h5.opened_as_hdf5", errors),
        ]
    )

    normalized = _mapping(proposal.get("normalized_launch"))
    expected_launch = _expected_normalized_launch(root)
    proposal_checks.append(_exact(dict(normalized), expected_launch, "proposal.normalized_launch", errors))
    proposal_namespace = _mapping(proposal.get("fresh_attempt_namespace"))
    expected_namespace = _expected_proposal_namespace()
    proposal_checks.append(_exact(dict(proposal_namespace), expected_namespace, "proposal.fresh_attempt_namespace", errors))
    resources = _resource_request(job)
    resource_admission = _mapping(proposal.get("resource_admission"))
    proposal_checks.extend(
        [
            _exact(resource_admission.get("resource_request"), resources, "proposal.resource_request", errors),
            _exact(resource_admission.get("cpu_only"), True, "proposal.cpu_only", errors),
            _exact(resource_admission.get("gpu_forbidden"), True, "proposal.gpu_forbidden", errors),
            _exact(resource_admission.get("gpu_vram_headroom_is_not_admission"), True, "proposal.gpu_headroom_boundary", errors),
            _exact(resource_admission.get("snapshot_collected_by_proposal"), False, "proposal.snapshot_collected", errors),
        ]
    )
    proposal_auth = _mapping(proposal.get("authorization"))
    proposal_checks.extend(
        [
            _exact(proposal_auth.get("status"), "not_granted", "proposal.authorization.status", errors),
            _exact(proposal_auth.get("fresh_root_authorization_required"), True, "proposal.root_authorization_required", errors),
            _exact(proposal_auth.get("measured_host_io_receipt_required"), True, "proposal.host_io_receipt_required", errors),
        ]
    )
    job_checks = [
        _exact(job.get("job_id"), JOB_ID, "job_spec.job_id", errors),
        _exact(job.get("logical_id"), CANDIDATE_ID, "job_spec.logical_id", errors),
        _exact(job.get("cwd"), str(root), "job_spec.cwd", errors),
        _exact(job.get("resources"), resources, "job_spec.resources", errors),
    ]
    runtime_checks = [
        _exact(runtime_spec.get("schema"), "core.material.qualification_runtime_spec.v1", "runtime_spec.schema", errors),
        _exact(runtime_spec.get("status"), "ready_for_root_queue", "runtime_spec.status", errors),
        _exact(_mapping(runtime_spec.get("runtime")).get("module"), "scripts.core_material", "runtime_spec.module", errors),
        _exact(_mapping(runtime_spec.get("runtime")).get("working_directory"), str(root), "runtime_spec.working_directory", errors),
        _exact(_mapping(runtime_spec.get("runtime")).get("cpu_only"), True, "runtime_spec.cpu_only", errors),
        _exact(_mapping(runtime_spec.get("runtime")).get("gpu_forbidden"), True, "runtime_spec.gpu_forbidden", errors),
    ]
    checks["proposal_contract_valid"] = all(proposal_checks) and bool(proposal)
    checks["job_spec_contract_valid"] = all(job_checks) and bool(job)
    checks["runtime_spec_contract_valid"] = all(runtime_checks) and bool(runtime_spec)

    host_checks = [
        _exact(host.get("schema"), "core.material.f3.coarse.host_io_admission.v1", "host_io_admission.schema", errors),
        _exact(host.get("status"), "diagnostic_admission_blocked", "host_io_admission.status", errors),
        _exact(_mapping(host.get("checks")).get("admission_contract_valid"), True, "host_io_admission.contract", errors),
        _exact(_mapping(host.get("checks")).get("normalized_argv"), True, "host_io_admission.normalized_argv", errors),
        _exact(_mapping(host.get("checks")).get("launch_cwd"), True, "host_io_admission.launch_cwd", errors),
        _exact(_mapping(host.get("checks")).get("fresh_attempt_namespace"), True, "host_io_admission.fresh_namespace", errors),
        _exact(_mapping(host.get("checks")).get("resource_request_matches_job_spec"), True, "host_io_admission.resource_request", errors),
        _exact(_mapping(host.get("checks")).get("resource_projection_shape"), True, "host_io_admission.resource_projection", errors),
        _exact(_mapping(host.get("checks")).get("probe_pass"), True, "host_io_admission.probe_pass", errors),
        _exact(_mapping(host.get("checks")).get("measurement_complete"), True, "host_io_admission.measurement_complete", errors),
        _exact(_mapping(host.get("checks")).get("probe_is_not_authorization"), True, "host_io_admission.probe_boundary", errors),
        _exact(_mapping(host.get("decision")).get("argv_valid"), True, "host_io_admission.decision.argv", errors),
        _exact(_mapping(host.get("decision")).get("cwd_valid"), True, "host_io_admission.decision.cwd", errors),
        _exact(_mapping(host.get("decision")).get("fresh_namespace_valid"), True, "host_io_admission.decision.namespace", errors),
        _exact(_mapping(host.get("decision")).get("resource_projection_valid"), True, "host_io_admission.decision.resource", errors),
        _exact(_mapping(host.get("decision")).get("launch_admitted"), False, "host_io_admission.launch_admitted", errors),
        _exact(_mapping(host.get("decision")).get("worker_launch_authorized"), False, "host_io_admission.worker_authorized", errors),
        _exact(_mapping(host.get("resource_projection")).get("scheduler_owned_io_verified"), False, "host_io_admission.scheduler_io_unverified", errors),
    ]
    host_observation = _mapping(host.get("proposal_observation"))
    host_projection = _mapping(host.get("resource_projection"))
    host_checks.extend(
        [
            _exact(host_observation.get("normalized_launch"), expected_launch, "host.proposal_observation.normalized_launch", errors),
            _exact(host_observation.get("fresh_attempt_namespace"), expected_namespace, "host.proposal_observation.fresh_namespace", errors),
            _exact(host_observation.get("resource_request"), resources, "host.proposal_observation.resource_request", errors),
            _exact(host_projection.get("proposal_request"), resources, "host.resource_projection.proposal_request", errors),
            _exact(host_projection.get("job_spec_request"), resources, "host.resource_projection.job_spec_request", errors),
            _exact(host_projection.get("cpu_only"), True, "host.resource_projection.cpu_only", errors),
            _exact(host_projection.get("gpu_forbidden"), True, "host.resource_projection.gpu_forbidden", errors),
        ]
    )
    host_source = _mapping(_mapping(host.get("input_bindings")).get("source_h5"))
    host_checks.extend(
        [
            _exact(host_source.get("hash_only"), True, "host_io_admission.source_h5.hash_only", errors),
            _exact(host_source.get("opened_as_hdf5"), False, "host_io_admission.source_h5.opened_as_hdf5", errors),
        ]
    )
    host_validator_errors: list[str] = []
    if host:
        try:
            host_adapter = _load_host_io_admission_validator()
            host_validator_errors = list(host_adapter.validate_admission(host))
        except (ImportError, AttributeError, TypeError, ValueError) as error:
            host_validator_errors = [f"validator_error:{type(error).__name__}"]
    if host_validator_errors:
        errors.extend(f"host_io_admission.validator:{item}" for item in host_validator_errors)
    host_checks.append(not host_validator_errors and bool(host))
    checks["host_io_admission_contract_valid"] = all(host_checks)

    expected_proposal_sha = proposal_ref.get("sha256")
    host_bindings = _mapping(host.get("input_bindings"))
    host_checks_for_refs = [
        _exact(_mapping(host_bindings.get("proposal")).get("path"), _display_path(root, _resolve(root, PROPOSAL)), "host.proposal.path", errors),
        _exact(_mapping(host_bindings.get("proposal")).get("sha256"), expected_proposal_sha, "host.proposal.sha256", errors),
        _exact(_mapping(host_bindings.get("host_io_receipt")).get("path"), "reports/CORE-MATERIAL-HOST-IO-PROBE-2026-09-28.json", "host.probe.path", errors),
        _exact(_mapping(host_bindings.get("source_h5")).get("path"), str(SOURCE_H5), "host.source.path", errors),
        _exact(_mapping(host_bindings.get("source_h5")).get("sha256"), source_ref.get("sha256"), "host.source.sha256", errors),
    ]
    for name, ref_key in (
        ("core_material", "core_material"),
        ("core_runtime", "core_runtime"),
        ("job_spec", "job_spec"),
    ):
        host_checks_for_refs.append(
            _exact(_mapping(host_bindings.get(name)).get("sha256"), current_refs[ref_key].get("sha256"), f"host.{name}.sha256", errors)
        )
    checks["proposal_host_io_binding_valid"] = all(host_checks_for_refs) and bool(host)
    checks["source_hash_only_boundary_valid"] = (
        source_ref.get("hash_recomputed") is False
        and source_ref.get("opened_as_hdf5") is False
        and source_ref.get("read") is False
        and isinstance(source_ref.get("sha256"), str)
        and SHA256.fullmatch(str(source_ref.get("sha256"))) is not None
        and _mapping(proposal_bindings.get("source_h5")).get("sha256") == source_ref.get("sha256")
        and host_source.get("sha256") == source_ref.get("sha256")
        and host_source.get("bytes") == source_ref.get("bytes")
    )
    checks["current_hashes_valid"] = all(
        isinstance(current_refs.get(name, {}).get("sha256"), str)
        for name in ("core_material", "job_spec", "core_runtime", "runtime_spec")
    ) and all(
        _mapping(proposal_bindings.get(proposal_name)).get("sha256") == current_refs[ref_name].get("sha256")
        for proposal_name, ref_name in (
            ("core_material", "core_material"),
            ("job_spec", "job_spec"),
            ("current_frozen_worker", "core_runtime"),
            ("runtime_spec", "runtime_spec"),
        )
    )
    checks["normalized_argv_cwd_valid"] = checks["proposal_contract_valid"] and dict(normalized) == expected_launch

    projection = {
        "candidate": dict(candidate),
        "proposal_state": dict(proposal_state),
        "resource_request": resources,
        "proposal_namespace": dict(proposal_namespace),
        "normalized_launch": dict(normalized),
        "expected_normalized_launch": expected_launch,
        "proposal_blocking_reasons": list(proposal.get("blocking_reasons", [])) if isinstance(proposal.get("blocking_reasons"), list) else [],
        "host_io_status": host.get("status"),
        "host_io_checks": dict(_mapping(host.get("checks"))),
        "host_validator_errors": host_validator_errors,
    }
    return checks, errors, projection


def _validate_namespace(value: Any, proposal_namespace: Mapping[str, Any], errors: list[str]) -> dict[str, Any] | None:
    if not _require_keys(value, FRESH_NAMESPACE_FIELDS, "receipt.binding.fresh_attempt_namespace", errors):
        return None
    value = _mapping(value)
    attempt_id = value.get("attempt_id")
    attempt_root = proposal_namespace.get("attempt_root")
    expected_template = proposal_namespace.get("namespace_template")
    if not isinstance(attempt_id, str) or ATTEMPT_ID.fullmatch(attempt_id) is None:
        errors.append("fresh_namespace.attempt_id")
    if value.get("attempt_root") != attempt_root:
        errors.append("fresh_namespace.attempt_root")
    if value.get("namespace_template") != expected_template:
        errors.append("fresh_namespace.namespace_template")
    expected_path = f"{attempt_root}/{attempt_id}" if isinstance(attempt_id, str) else None
    if value.get("attempt_path") != expected_path:
        errors.append("fresh_namespace.attempt_path")
    if not isinstance(value.get("namespace_nonce"), str) or NAMESPACE_NONCE.fullmatch(str(value.get("namespace_nonce"))) is None:
        errors.append("fresh_namespace.namespace_nonce")
    for key, expected in (("fresh", True), ("reused", False), ("same_attempt_resume_only", True), ("historical_attempt_reuse_forbidden", True)):
        if value.get(key) is not expected:
            errors.append(f"fresh_namespace.{key}")
    return dict(value)


def _validate_common_binding(
    value: Any,
    *,
    root: Path,
    expected: Mapping[str, Any],
    proposal_namespace: Mapping[str, Any],
    errors: list[str],
) -> dict[str, Any] | None:
    if not _require_keys(value, BINDING_FIELDS, "receipt.binding", errors):
        return None
    binding = _mapping(value)
    for name, expected_ref in (
        ("proposal", expected["proposal_ref"]),
        ("host_io_admission", expected["host_ref"]),
    ):
        ref = _mapping(binding.get(name))
        if not _require_keys(ref, {"path", "sha256"}, f"receipt.binding.{name}", errors):
            continue
        if ref.get("path") != expected_ref.get("path"):
            errors.append(f"receipt.binding.{name}.path")
        if ref.get("sha256") != expected_ref.get("sha256"):
            errors.append(f"receipt.binding.{name}.sha256")
    hashes = binding.get("hashes")
    if _require_keys(hashes, set(HASH_KEYS), "receipt.binding.hashes", errors):
        if dict(hashes) != dict(expected["hashes"]):
            errors.append("receipt.binding.hashes.value")
    if binding.get("normalized_launch") != expected["normalized_launch"]:
        errors.append("receipt.binding.normalized_launch")
    if binding.get("normalized_launch_sha256") != _canonical_digest(expected["normalized_launch"]):
        errors.append("receipt.binding.normalized_launch_sha256")
    namespace = _validate_namespace(binding.get("fresh_attempt_namespace"), proposal_namespace, errors)
    if namespace is not None and binding.get("fresh_attempt_namespace_sha256") != _canonical_digest(namespace):
        errors.append("receipt.binding.fresh_attempt_namespace_sha256")
    return dict(binding)


def _validate_counterparty(value: Any, *, expected_path: str, expected_sha256: Any, expected_pair_id: Any, label: str, errors: list[str]) -> bool:
    if not _require_keys(value, COUNTERPARTY_FIELDS, label, errors):
        return False
    value = _mapping(value)
    result = True
    for key, expected in (("path", expected_path), ("binding_sha256", expected_sha256), ("pair_id", expected_pair_id)):
        if value.get(key) != expected:
            errors.append(f"{label}.{key}")
            result = False
    return result


def _validate_side_effects(value: Any, label: str, errors: list[str]) -> bool:
    if not _require_keys(value, SIDE_EFFECT_FIELDS, label, errors):
        return False
    value = _mapping(value)
    for key in ("worker_started", "solver_started", "gpu_started"):
        if value.get(key) is not False:
            errors.append(f"{label}.{key}")
    for key in ("queue_mutations", "registry_mutations", "ledger_mutations", "denominator_mutations", "gate_mutations", "plan_mutations"):
        if value.get(key) != 0:
            errors.append(f"{label}.{key}")
    return True


def _validate_root_receipt(
    value: Mapping[str, Any] | None,
    *,
    root: Path,
    expected: Mapping[str, Any],
    proposal_namespace: Mapping[str, Any],
    scheduler_ref: Mapping[str, Any],
    scheduler_binding_sha256: str,
    errors: list[str],
) -> tuple[bool, dict[str, Any]]:
    error_start = len(errors)
    if not isinstance(value, Mapping):
        errors.append("root_receipt.missing_or_not_object")
        return False, {}
    valid = True
    valid &= _require_keys(value, ROOT_RECEIPT_FIELDS, "root_receipt", errors)
    valid &= _exact(value.get("schema"), ROOT_RECEIPT_SCHEMA, "root_receipt.schema", errors)
    valid &= _exact(value.get("record_id"), ROOT_RECEIPT_ID, "root_receipt.record_id", errors)
    valid &= _exact(value.get("status"), "root_authorization_issued", "root_receipt.status", errors)
    valid &= _exact(value.get("synthetic"), False, "root_receipt.synthetic", errors)
    pair_id = value.get("pair_id")
    if not isinstance(pair_id, str) or SAFE_ID.fullmatch(pair_id) is None:
        errors.append("root_receipt.pair_id")
        valid = False
    binding = _validate_common_binding(value.get("binding"), root=root, expected=expected, proposal_namespace=proposal_namespace, errors=errors)
    valid &= binding is not None
    valid &= _validate_counterparty(
        value.get("counterparty"),
        expected_path=str(scheduler_ref.get("path")),
        expected_sha256=scheduler_binding_sha256,
        expected_pair_id=pair_id,
        label="root_receipt.counterparty",
        errors=errors,
    )
    fresh_root = value.get("fresh_root")
    if _require_keys(fresh_root, FRESH_ROOT_FIELDS, "root_receipt.fresh_root", errors):
        fresh_root = _mapping(fresh_root)
        namespace = _mapping(binding or {}).get("fresh_attempt_namespace", {})
        for key in ("attempt_id", "attempt_path"):
            if fresh_root.get(key) != namespace.get(key):
                errors.append(f"root_receipt.fresh_root.{key}")
        for key, expected_value in (("created", True), ("reused", False), ("root_owned", True)):
            if fresh_root.get(key) is not expected_value:
                errors.append(f"root_receipt.fresh_root.{key}")
    auth = value.get("root_authorization")
    if _require_keys(auth, ROOT_AUTHORIZATION_FIELDS, "root_receipt.root_authorization", errors):
        auth = _mapping(auth)
        if not isinstance(auth.get("authorization_id"), str) or SAFE_ID.fullmatch(auth.get("authorization_id")) is None:
            errors.append("root_receipt.root_authorization.authorization_id")
        for key, expected_value in (("root_authorized", True), ("single_use", True), ("consumed", False)):
            if auth.get(key) is not expected_value:
                errors.append(f"root_receipt.root_authorization.{key}")
    valid &= _validate_side_effects(value.get("side_effects"), "root_receipt.side_effects", errors)
    return bool(valid and len(errors) == error_start), {
        "pair_id": pair_id,
        "binding": binding or {},
        "fresh_root": dict(_mapping(value.get("fresh_root"))),
        "root_authorization": dict(_mapping(value.get("root_authorization"))),
    }


def _validate_scheduler_receipt(
    value: Mapping[str, Any] | None,
    *,
    root: Path,
    expected: Mapping[str, Any],
    proposal_namespace: Mapping[str, Any],
    root_ref: Mapping[str, Any],
    root_binding_sha256: str,
    expected_resources: Mapping[str, Any],
    errors: list[str],
) -> tuple[bool, dict[str, Any]]:
    error_start = len(errors)
    if not isinstance(value, Mapping):
        errors.append("scheduler_receipt.missing_or_not_object")
        return False, {}
    valid = True
    valid &= _require_keys(value, SCHEDULER_RECEIPT_FIELDS, "scheduler_receipt", errors)
    valid &= _exact(value.get("schema"), SCHEDULER_RECEIPT_SCHEMA, "scheduler_receipt.schema", errors)
    valid &= _exact(value.get("record_id"), SCHEDULER_RECEIPT_ID, "scheduler_receipt.record_id", errors)
    valid &= _exact(value.get("status"), "scheduler_host_io_reserved", "scheduler_receipt.status", errors)
    valid &= _exact(value.get("synthetic"), False, "scheduler_receipt.synthetic", errors)
    pair_id = value.get("pair_id")
    if not isinstance(pair_id, str) or SAFE_ID.fullmatch(pair_id) is None:
        errors.append("scheduler_receipt.pair_id")
        valid = False
    binding = _validate_common_binding(value.get("binding"), root=root, expected=expected, proposal_namespace=proposal_namespace, errors=errors)
    valid &= binding is not None
    valid &= _validate_counterparty(
        value.get("counterparty"),
        expected_path=str(root_ref.get("path")),
        expected_sha256=root_binding_sha256,
        expected_pair_id=pair_id,
        label="scheduler_receipt.counterparty",
        errors=errors,
    )
    reservation = value.get("scheduler_reservation")
    if _require_keys(reservation, SCHEDULER_RESERVATION_FIELDS, "scheduler_receipt.scheduler_reservation", errors):
        reservation = _mapping(reservation)
        if not isinstance(reservation.get("reservation_id"), str) or SAFE_ID.fullmatch(reservation.get("reservation_id")) is None:
            errors.append("scheduler_receipt.reservation_id")
        for key, expected_value in (("reservation_active", True), ("scheduler_owned_host_io_verified", True), ("single_use", True), ("consumed", False)):
            if reservation.get(key) is not expected_value:
                errors.append(f"scheduler_receipt.scheduler_reservation.{key}")
        if reservation.get("resource_request") != dict(expected_resources):
            errors.append("scheduler_receipt.resource_request")
        host_io = reservation.get("host_io_reservation")
        if _require_keys(host_io, HOST_IO_RESERVATION_FIELDS, "scheduler_receipt.host_io_reservation", errors):
            host_io = _mapping(host_io)
            if host_io.get("io_weight") != expected_resources.get("io_weight"):
                errors.append("scheduler_receipt.host_io_reservation.io_weight")
            expected_io_weight = expected_resources.get("io_weight")
            owned_io_weight = host_io.get("owned_io_weight")
            if (
                isinstance(expected_io_weight, (int, float))
                and not isinstance(expected_io_weight, bool)
                and math.isfinite(float(expected_io_weight))
                and (
                    not isinstance(owned_io_weight, (int, float))
                    or isinstance(owned_io_weight, bool)
                    or not math.isfinite(float(owned_io_weight))
                    or float(owned_io_weight) < float(expected_io_weight)
                )
            ):
                errors.append("scheduler_receipt.host_io_reservation.owned_io_weight")
            if not all(
                isinstance(host_io.get(key), (int, float))
                and not isinstance(host_io.get(key), bool)
                and math.isfinite(float(host_io.get(key)))
                and float(host_io.get(key)) >= 0
                for key in ("owned_io_weight", "io_capacity")
            ):
                errors.append("scheduler_receipt.host_io_reservation.capacity")
            elif float(host_io["io_capacity"]) < float(host_io["owned_io_weight"]):
                errors.append("scheduler_receipt.host_io_reservation.capacity_headroom")
            for key in ("filesystem", "snapshot_id"):
                if not isinstance(host_io.get(key), str) or not host_io.get(key):
                    errors.append(f"scheduler_receipt.host_io_reservation.{key}")
    valid &= _validate_side_effects(value.get("side_effects"), "scheduler_receipt.side_effects", errors)
    return bool(valid and len(errors) == error_start), {
        "pair_id": pair_id,
        "binding": binding or {},
        "scheduler_reservation": dict(_mapping(value.get("scheduler_reservation"))),
    }


def _authorization() -> dict[str, Any]:
    return {
        "diagnostic_only": True,
        "formal": False,
        "formal_eligible": False,
        "T2_macro": False,
        "T2_path": False,
        "qualification": False,
        "launch_admitted": False,
        "worker_launch_authorized": False,
        "root_authorization_intake_bound": False,
        "scheduler_host_io_reservation_bound": False,
        "scheduler_owned_io_verified": False,
        "qualification_credit": 0,
        "T2_credit": 0,
        "credit": 0,
    }


def _execution_controls() -> dict[str, Any]:
    return {
        "bounded_json_only": True,
        "small_file_metadata_only": True,
        "source_hdf5_opened": False,
        "source_hdf5_read": False,
        "source_hdf5_hash_recomputed": False,
        "worker_started": False,
        "solver_started": False,
        "gpu_started": False,
        "queue_started": False,
        "root_receipt_written": False,
        "scheduler_receipt_written": False,
        "registry_mutations": 0,
        "ledger_mutations": 0,
        "denominator_mutations": 0,
        "gate_mutations": 0,
        "plan_mutations": 0,
    }


def _empty_receipt_projection() -> dict[str, Any]:
    return {
        "present": False,
        "valid": False,
        "path": None,
        "sha256": None,
        "pair_id": None,
        "binding": {},
        "fresh_root": {},
        "root_authorization": {},
        "scheduler_reservation": {},
    }


def build_report(
    root: str | Path = LAB_ROOT,
    *,
    proposal_path: str | Path | None = None,
    host_io_admission_path: str | Path | None = None,
    root_receipt_path: str | Path | None = None,
    scheduler_receipt_path: str | Path | None = None,
) -> dict[str, Any]:
    """Build the bounded, non-authorizing F3 root/scheduler intake report."""

    root = _absolute(Path(root))
    proposal_file = _resolve(root, proposal_path or PROPOSAL)
    host_file = _resolve(root, host_io_admission_path or HOST_IO_ADMISSION)
    root_file = _resolve(root, root_receipt_path or ROOT_RECEIPT)
    scheduler_file = _resolve(root, scheduler_receipt_path or SCHEDULER_RECEIPT)

    proposal, proposal_ref, proposal_error = _read_json_document(root, proposal_file, role="committed F3 coarse proposal")
    host, host_ref, host_error = _read_json_document(root, host_file, role="committed F3 coarse host-I/O admission")
    root_receipt, root_ref, root_error = _read_json_document(root, root_file, role="future fresh root admission receipt")
    scheduler_receipt, scheduler_ref, scheduler_error = _read_json_document(root, scheduler_file, role="future scheduler-owned host-I/O reservation")

    current_refs: dict[str, dict[str, Any]] = {}
    current_errors: list[str] = []
    for key, relative, role in (
        ("core_material", CORE_MATERIAL, "current scripts/core_material.py"),
        ("core_runtime", CORE_RUNTIME, "current scripts/core_runtime.py"),
        ("job_spec", JOB_SPEC, "current F3 coarse job specification"),
        ("runtime_spec", RUNTIME_SPEC, "current F3 material runtime specification"),
    ):
        if key in {"job_spec", "runtime_spec"}:
            _, ref, error = _read_json_document(root, _resolve(root, relative), role=role)
        else:
            ref, error = _read_small_file(root, _resolve(root, relative), role=role)
        current_refs[key] = ref
        if error:
            current_errors.append(f"{key}:{error}")

    proposal_bindings = _mapping(_mapping(proposal).get("input_bindings"))
    claimed_source_sha = _mapping(proposal_bindings.get("source_h5")).get("sha256")
    source_ref, source_error = _source_metadata(root, _resolve(root, SOURCE_H5), claimed_sha256=claimed_source_sha)
    if source_error:
        current_errors.append(source_error)

    job_value: Mapping[str, Any] | None = None
    runtime_value: Mapping[str, Any] | None = None
    if current_refs["job_spec"].get("exists"):
        job_value, _, _ = _read_json_document(root, _resolve(root, JOB_SPEC), role="current F3 coarse job specification")
    if current_refs["runtime_spec"].get("exists"):
        runtime_value, _, _ = _read_json_document(root, _resolve(root, RUNTIME_SPEC), role="current F3 material runtime specification")

    checks, blockers, projection = _proposal_and_host_checks(
        root,
        proposal,
        host,
        proposal_ref,
        host_ref,
        current_refs,
        job_value,
        runtime_value,
        source_ref,
    )
    blockers.extend(current_errors)
    for label, error in (
        ("proposal", proposal_error),
        ("host_io_admission", host_error),
        ("root_receipt", root_error),
        ("scheduler_receipt", scheduler_error),
    ):
        if error:
            blockers.append(f"{label}:{error}")

    hashes = {
        "core_material_sha256": current_refs["core_material"].get("sha256"),
        "source_sha256": source_ref.get("sha256"),
        "job_spec_sha256": current_refs["job_spec"].get("sha256"),
        "core_runtime_sha256": current_refs["core_runtime"].get("sha256"),
        "runtime_spec_sha256": current_refs["runtime_spec"].get("sha256"),
    }
    expected_resources = _resource_request(job_value or {})
    proposal_namespace = _mapping(projection.get("proposal_namespace"))
    expected_context = {
        "proposal_ref": proposal_ref,
        "host_ref": host_ref,
        "hashes": hashes,
        "normalized_launch": projection.get("expected_normalized_launch", {}),
    }

    root_errors: list[str] = []
    scheduler_errors: list[str] = []
    root_valid, root_projection = _validate_root_receipt(
        root_receipt,
        root=root,
        expected=expected_context,
        proposal_namespace=proposal_namespace,
        scheduler_ref=scheduler_ref,
        scheduler_binding_sha256=_canonical_digest(_mapping(scheduler_receipt).get("binding")),
        errors=root_errors,
    )
    scheduler_valid, scheduler_projection = _validate_scheduler_receipt(
        scheduler_receipt,
        root=root,
        expected=expected_context,
        proposal_namespace=proposal_namespace,
        root_ref=root_ref,
        root_binding_sha256=_canonical_digest(_mapping(root_receipt).get("binding")),
        expected_resources=expected_resources,
        errors=scheduler_errors,
    )
    blockers.extend(f"root_receipt:{item}" for item in root_errors)
    blockers.extend(f"scheduler_receipt:{item}" for item in scheduler_errors)
    # A present-but-malformed JSON file is an invalid receipt, not a missing
    # receipt.  Keep presence tied to filesystem metadata rather than decode
    # success so the status remains diagnostic and precise.
    root_present = root_ref.get("exists") is True
    scheduler_present = scheduler_ref.get("exists") is True
    checks["future_root_receipt_present"] = root_present
    checks["future_scheduler_receipt_present"] = scheduler_present
    checks["future_root_receipt_valid"] = root_valid
    checks["future_scheduler_receipt_valid"] = scheduler_valid

    root_pair_id = root_projection.get("pair_id")
    scheduler_pair_id = scheduler_projection.get("pair_id")
    pair_valid = bool(root_valid and scheduler_valid and root_pair_id and root_pair_id == scheduler_pair_id)
    if not pair_valid:
        blockers.append("root_scheduler_pair_cross_binding_invalid")
    checks["receipt_pair_cross_binding_valid"] = pair_valid
    namespace_root = _mapping(root_projection.get("binding")).get("fresh_attempt_namespace")
    namespace_scheduler = _mapping(scheduler_projection.get("binding")).get("fresh_attempt_namespace")
    namespace_valid = bool(
        root_valid
        and scheduler_valid
        and isinstance(namespace_root, Mapping)
        and dict(namespace_root) == dict(namespace_scheduler)
    )
    checks["fresh_attempt_namespace_valid"] = namespace_valid
    if not namespace_valid:
        blockers.append("fresh_attempt_namespace_missing_or_cross_receipt_drift")
    reservation = scheduler_projection.get("scheduler_reservation", {})
    reservation_valid = bool(
        scheduler_valid
        and _mapping(reservation).get("scheduler_owned_host_io_verified") is True
        and _mapping(reservation).get("resource_request") == expected_resources
    )
    checks["scheduler_owned_host_io_reservation_valid"] = reservation_valid
    if not reservation_valid:
        blockers.append("scheduler_owned_host_io_reservation_missing_or_mismatched")

    contract_names = (
        "proposal_contract_valid",
        "job_spec_contract_valid",
        "runtime_spec_contract_valid",
        "host_io_admission_contract_valid",
        "proposal_host_io_binding_valid",
        "current_hashes_valid",
        "source_hash_only_boundary_valid",
        "normalized_argv_cwd_valid",
        "future_root_receipt_present",
        "future_root_receipt_valid",
        "future_scheduler_receipt_present",
        "future_scheduler_receipt_valid",
        "receipt_pair_cross_binding_valid",
        "fresh_attempt_namespace_valid",
        "scheduler_owned_host_io_reservation_valid",
    )
    contract_valid = all(checks.get(name) is True for name in contract_names)
    checks["intake_contract_valid"] = contract_valid
    if contract_valid:
        blockers = []
        status = STATUS_BOUND
    elif not root_present or not scheduler_present:
        status = STATUS_MISSING
    else:
        status = STATUS_INVALID
    blockers = list(dict.fromkeys(str(item) for item in blockers if item))

    # Receipt binding is an observation of supplied evidence, not an
    # authorization mutation.  Keep the authorization envelope identical in
    # both the missing and structurally complete cases.
    authorization = _authorization()
    return {
        "schema": SCHEMA,
        "record_id": RECORD_ID,
        "created_at": CREATED_AT,
        "status": status,
        "candidate": _expected_candidate(),
        # Stable top-level aliases keep simple consumers from accidentally
        # treating a receipt-bound diagnostic observation as a launch result.
        "diagnostic_only": True,
        "formal": False,
        "formal_eligible": False,
        "T2_macro": False,
        "T2_path": False,
        "qualification": False,
        "qualification_credit": 0,
        "T2_credit": 0,
        "credit": 0,
        "launch_admitted": False,
        "worker_launch_authorized": False,
        "input_bindings": {
            "proposal": dict(proposal_ref),
            "host_io_admission": dict(host_ref),
            "fresh_root_receipt": dict(root_ref),
            "scheduler_host_io_reservation": dict(scheduler_ref),
            "current_core_material": dict(current_refs["core_material"]),
            "source_h5": dict(source_ref),
            "current_job_spec": dict(current_refs["job_spec"]),
            "current_core_runtime": dict(current_refs["core_runtime"]),
            "current_runtime_spec": dict(current_refs["runtime_spec"]),
        },
        "binding_projection": {
            "hashes": hashes,
            "normalized_launch": projection.get("expected_normalized_launch", {}),
            "normalized_launch_sha256": _canonical_digest(projection.get("expected_normalized_launch", {})),
            "proposal_namespace_contract": proposal_namespace,
            "fresh_attempt_namespace": dict(namespace_root) if namespace_valid else {},
            "fresh_attempt_namespace_sha256": _canonical_digest(namespace_root) if namespace_valid else None,
            "proposal_sha256": proposal_ref.get("sha256"),
            "host_io_admission_sha256": host_ref.get("sha256"),
            "root_scheduler_pair_id": root_pair_id if pair_valid else None,
            "scheduler_owned_host_io_verified": reservation_valid,
        },
        "validation": {
            "checks": checks,
            "blockers": blockers,
            "root_receipt_errors": root_errors,
            "scheduler_receipt_errors": scheduler_errors,
            "proposal_error": proposal_error,
            "host_io_admission_error": host_error,
        },
        "receipt_observations": {
            "fresh_root": {
                "present": root_present,
                "valid": root_valid,
                "pair_id": root_pair_id,
                "binding": root_projection.get("binding", {}),
                "fresh_root": root_projection.get("fresh_root", {}),
                "root_authorization": root_projection.get("root_authorization", {}),
            },
            "scheduler": {
                "present": scheduler_present,
                "valid": scheduler_valid,
                "pair_id": scheduler_pair_id,
                "binding": scheduler_projection.get("binding", {}),
                "scheduler_reservation": scheduler_projection.get("scheduler_reservation", {}),
            },
        },
        "authorization": authorization,
        "execution_controls": _execution_controls(),
        "next_safe_action": (
            "Obtain both bounded fresh root and scheduler-owned host-I/O receipts using the exact current hashes, "
            "normalized module argv/cwd, proposal/host-admission digests, and one new attempt namespace; then "
            "re-run this non-authorizing intake. This report itself must never be used as a launch capability."
        ),
    }


def _validate_ref(value: Any, label: str, errors: list[str], *, allow_claim_only: bool = False) -> None:
    if not isinstance(value, Mapping):
        errors.append(label)
        return
    for key in ("path", "exists", "bytes", "sha256"):
        if key not in value:
            errors.append(f"{label}.{key}")
    if not isinstance(value.get("path"), str) or not value.get("path"):
        errors.append(f"{label}.path")
    if type(value.get("exists")) is not bool:
        errors.append(f"{label}.exists")
    if value.get("exists"):
        if type(value.get("bytes")) is not int or value.get("bytes") < 1:
            errors.append(f"{label}.bytes")
        if not isinstance(value.get("sha256"), str) or SHA256.fullmatch(value.get("sha256")) is None:
            errors.append(f"{label}.sha256")
    elif value.get("bytes") is not None or value.get("sha256") is not None:
        if allow_claim_only and isinstance(value.get("sha256"), str) and value.get("bytes") is not None:
            pass
        else:
            errors.append(f"{label}.missing_partial")


def validate_report(value: Mapping[str, Any]) -> list[str]:
    """Validate serialized report markers without reading campaign state."""

    errors: list[str] = []
    expected_top = {
        "schema", "record_id", "created_at", "status", "candidate", "input_bindings",
        "binding_projection", "validation", "receipt_observations", "authorization",
        "execution_controls", "next_safe_action", "diagnostic_only", "formal",
        "formal_eligible", "T2_macro", "T2_path", "qualification", "qualification_credit",
        "T2_credit", "credit", "launch_admitted", "worker_launch_authorized",
    }
    if not isinstance(value, Mapping) or set(value) != expected_top:
        return ["report.fields"]
    if value.get("schema") != SCHEMA:
        errors.append("schema")
    if value.get("record_id") != RECORD_ID:
        errors.append("record_id")
    if value.get("created_at") != CREATED_AT:
        errors.append("created_at")
    if value.get("status") not in {STATUS_MISSING, STATUS_INVALID, STATUS_BOUND}:
        errors.append("status")
    if dict(_mapping(value.get("candidate"))) != _expected_candidate():
        errors.append("candidate")
    for key, expected in (
        ("diagnostic_only", True),
        ("formal", False),
        ("formal_eligible", False),
        ("T2_macro", False),
        ("T2_path", False),
        ("qualification", False),
        ("qualification_credit", 0),
        ("T2_credit", 0),
        ("credit", 0),
        ("launch_admitted", False),
        ("worker_launch_authorized", False),
    ):
        if value.get(key) != expected:
            errors.append(key)

    bindings = _mapping(value.get("input_bindings"))
    expected_binding_names = {
        "proposal", "host_io_admission", "fresh_root_receipt", "scheduler_host_io_reservation",
        "current_core_material", "source_h5", "current_job_spec", "current_core_runtime", "current_runtime_spec",
    }
    if set(bindings) != expected_binding_names:
        errors.append("input_bindings.fields")
    for name in expected_binding_names - {"source_h5"}:
        _validate_ref(bindings.get(name), f"input_bindings.{name}", errors)
    source = _mapping(bindings.get("source_h5"))
    for key, expected in (("hash_recomputed", False), ("opened_as_hdf5", False), ("read", False)):
        if source.get(key) is not expected:
            errors.append(f"input_bindings.source_h5.{key}")
    if source.get("sha256") is not None and (not isinstance(source.get("sha256"), str) or SHA256.fullmatch(source.get("sha256")) is None):
        errors.append("input_bindings.source_h5.sha256")
    if source.get("exists") is not True:
        errors.append("input_bindings.source_h5.exists")
    if type(source.get("bytes")) is not int or source.get("bytes") < 1:
        errors.append("input_bindings.source_h5.bytes")

    projection = _mapping(value.get("binding_projection"))
    for key in ("hashes", "normalized_launch", "normalized_launch_sha256", "proposal_namespace_contract", "fresh_attempt_namespace", "fresh_attempt_namespace_sha256", "proposal_sha256", "host_io_admission_sha256", "root_scheduler_pair_id", "scheduler_owned_host_io_verified"):
        if key not in projection:
            errors.append(f"binding_projection.{key}")
    hashes = _mapping(projection.get("hashes"))
    if set(hashes) != set(HASH_KEYS):
        errors.append("binding_projection.hashes.fields")
    for key in HASH_KEYS:
        if not isinstance(hashes.get(key), str) or SHA256.fullmatch(hashes.get(key)) is None:
            errors.append(f"binding_projection.hashes.{key}")
    if not isinstance(projection.get("normalized_launch_sha256"), str) or SHA256.fullmatch(projection.get("normalized_launch_sha256")) is None:
        errors.append("binding_projection.normalized_launch_sha256")
    if type(projection.get("scheduler_owned_host_io_verified")) is not bool:
        errors.append("binding_projection.scheduler_owned_host_io_verified")

    validation = _mapping(value.get("validation"))
    if set(validation) != {"checks", "blockers", "root_receipt_errors", "scheduler_receipt_errors", "proposal_error", "host_io_admission_error"}:
        errors.append("validation.fields")
    checks = _mapping(validation.get("checks"))
    required_checks = {
        "proposal_contract_valid", "job_spec_contract_valid", "runtime_spec_contract_valid",
        "host_io_admission_contract_valid", "proposal_host_io_binding_valid", "current_hashes_valid",
        "source_hash_only_boundary_valid", "normalized_argv_cwd_valid", "future_root_receipt_present",
        "future_root_receipt_valid", "future_scheduler_receipt_present", "future_scheduler_receipt_valid",
        "receipt_pair_cross_binding_valid", "fresh_attempt_namespace_valid",
        "scheduler_owned_host_io_reservation_valid", "intake_contract_valid",
    }
    if set(checks) != required_checks or any(type(checks.get(key)) is not bool for key in required_checks):
        errors.append("validation.checks")
    for key in ("blockers", "root_receipt_errors", "scheduler_receipt_errors"):
        if not isinstance(validation.get(key), list) or any(not isinstance(item, str) for item in validation.get(key, [])):
            errors.append(f"validation.{key}")
    if value.get("status") == STATUS_BOUND:
        if checks.get("intake_contract_valid") is not True or validation.get("blockers") != []:
            errors.append("status.bound_contract")
    else:
        if checks.get("intake_contract_valid") is not False or not validation.get("blockers"):
            errors.append("status.blocked_contract")

    authorization = value.get("authorization")
    if dict(_mapping(authorization)) != _authorization():
        errors.append("authorization.fail_closed_boundary")
    controls = value.get("execution_controls")
    if dict(_mapping(controls)) != _execution_controls():
        errors.append("execution_controls.fail_closed_boundary")
    observations = _mapping(value.get("receipt_observations"))
    if set(observations) != {"fresh_root", "scheduler"}:
        errors.append("receipt_observations.fields")
    if value.get("status") != STATUS_BOUND and (
        _mapping(observations.get("fresh_root")).get("valid") is True
        or _mapping(observations.get("scheduler")).get("valid") is True
    ):
        errors.append("blocked_receipt_observation")
    return errors


def write_report(value: Mapping[str, Any], output: str | Path) -> Path:
    errors = validate_report(value)
    if errors:
        raise ValueError("refusing to write invalid intake report: " + ", ".join(errors))
    path = Path(output).resolve()
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return path


def render_zh_cn(value: Mapping[str, Any]) -> str:
    checks = _mapping(_mapping(value.get("validation")).get("checks"))
    blockers = _mapping(value.get("validation")).get("blockers", [])
    authorization = _mapping(value.get("authorization"))
    bindings = _mapping(value.get("input_bindings"))
    lines = [
        "# F3 coarse material fresh root/scheduler receipt intake",
        "",
        f"- Schema：`{value.get('schema')}`",
        f"- 状态：`{value.get('status')}`",
        f"- 候选：`{_mapping(value.get('candidate')).get('configuration_id')}`",
        "",
        "## 绑定与决策",
        "",
        f"- proposal contract：`{checks.get('proposal_contract_valid')}`",
        f"- host-I/O admission contract：`{checks.get('host_io_admission_contract_valid')}`",
        f"- current hash binding：`{checks.get('current_hashes_valid')}`",
        f"- normalized argv/cwd：`{checks.get('normalized_argv_cwd_valid')}`",
        f"- fresh root receipt：present=`{checks.get('future_root_receipt_present')}`, valid=`{checks.get('future_root_receipt_valid')}`",
        f"- scheduler host-I/O reservation：present=`{checks.get('future_scheduler_receipt_present')}`, valid=`{checks.get('future_scheduler_receipt_valid')}`",
        f"- pair/namespace cross-binding：`{checks.get('receipt_pair_cross_binding_valid')}` / `{checks.get('fresh_attempt_namespace_valid')}`",
        "",
        "无论 receipt 是否完整，本 intake 都不铸造 launch capability：",
        f"`diagnostic_only={authorization.get('diagnostic_only')}`、`formal={authorization.get('formal')}`、",
        f"`T2_macro={authorization.get('T2_macro')}`、`T2_path={authorization.get('T2_path')}`、",
        f"`qualification={authorization.get('qualification')}`、`credit={authorization.get('credit')}`。",
        "",
        "## 输入边界",
        "",
    ]
    for name in (
        "proposal", "host_io_admission", "fresh_root_receipt", "scheduler_host_io_reservation",
        "current_core_material", "source_h5", "current_job_spec", "current_core_runtime", "current_runtime_spec",
    ):
        ref = _mapping(bindings.get(name))
        lines.append(
            f"- `{name}`：`{ref.get('path')}`，exists=`{ref.get('exists')}`，"
            f"bytes=`{ref.get('bytes')}`，sha256=`{ref.get('sha256')}`"
        )
    lines.extend(
        [
            "",
            "source HDF5 只继承已有 proposal/host-admission 的 hash claim；本 intake 只做 lstat 元数据，",
            "`opened_as_hdf5=false`、`read=false`、`hash_recomputed=false`。",
            "",
            "## 阻塞原因",
            "",
        ]
    )
    lines.extend(f"- `{item}`" for item in blockers)
    lines.extend(
        [
            "",
            "未启动、停止或重启 worker/solver/GPU/queue；未写 registry、ledger、denominator、gate 或 PLAN。",
            "",
        ]
    )
    return "\n".join(lines)


def write_zh_cn(value: Mapping[str, Any], output: str | Path) -> Path:
    errors = validate_report(value)
    if errors:
        raise ValueError("refusing to write invalid intake report: " + ", ".join(errors))
    path = Path(output).resolve()
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_zh_cn(value), encoding="utf-8")
    return path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=LAB_ROOT)
    parser.add_argument("--proposal", type=Path, default=None)
    parser.add_argument("--host-io-admission", type=Path, default=None)
    parser.add_argument("--root-receipt", type=Path, default=None)
    parser.add_argument("--scheduler-receipt", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--zh-cn-output", type=Path, default=DEFAULT_ZH_CN)
    args = parser.parse_args(argv)
    report = build_report(
        args.root,
        proposal_path=args.proposal,
        host_io_admission_path=args.host_io_admission,
        root_receipt_path=args.root_receipt,
        scheduler_receipt_path=args.scheduler_receipt,
    )
    write_report(report, args.output)
    write_zh_cn(report, args.zh_cn_output)
    print(json.dumps({"status": report["status"], "report": str(args.output)}, sort_keys=True))
    return 0 if report["status"] == STATUS_BOUND else 2


if __name__ == "__main__":
    raise SystemExit(main())
