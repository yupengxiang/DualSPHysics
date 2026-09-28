#!/usr/bin/env python3
"""Bounded JSON-only F4 Tallwall120 material root/scheduler admission intake.

This module is an evidence intake boundary, not a launcher.  It binds the
source-bound DEV_07 proposal to the existing host-I/O projection, collection,
reader, archive, consistency, runtime, and collector identities.  It also
binds the current material/diagnosis/collector/runtime source hashes, the
normalized argv/cwd, and a future fresh output namespace.

Two future receipts are accepted only as bounded strict JSON: a root-owned
fresh-output authorization and a scheduler-owned host-I/O reservation.  They
cross-bind one another and remain diagnostic-only.  Missing receipts are
fail-closed.  The trajectory HDF5 is inspected with ``lstat`` only; it is
never opened, read, or re-hashed here.  This module never starts or controls a
solver, worker, native process, GPU, or queue and never writes campaign state,
registry, ledger, denominator, gate, or PLAN.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import re
import sys
from typing import Any, Mapping, Sequence


LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))
CREATED_AT = "2026-09-28"

SCHEMA = "core.material.f4.tallwall120.root_scheduler_intake.v1"
RECORD_ID = "f4-tallwall120-material-root-scheduler-intake-v1"
ROOT_RECEIPT_SCHEMA = "core.material.f4.tallwall120.fresh_root_admission_receipt.v1"
ROOT_RECEIPT_ID = "f4-tallwall120-material-fresh-root-admission-receipt-v1"
SCHEDULER_RECEIPT_SCHEMA = "core.material.f4.tallwall120.scheduler_host_io_reservation.v1"
SCHEDULER_RECEIPT_ID = "f4-tallwall120-material-scheduler-host-io-reservation-v1"

FAMILY = "F4"
SCOPE_ID = "F4_resting_pool_laminar_tallwall120_x_v1"
CASE_ID = f"{SCOPE_ID}_DEV_07"
JOB_ID = "f4-tallwall120-production-dev-07"

SOURCE_HDF5 = (
    "campaigns/core-v1/cfd/f4-tallwall120-production-archives-v2/"
    "f4-tallwall120-production-dev-07/product/trajectory.h5"
)
SOURCE_SHA256 = "6ae8ca7062e1fa15779fc9ad491d1117455700315c6a1ef4a12326458f0976ae"
SOURCE_BYTES = 2_067_911_708

PROPOSAL = Path("reports/F4-TALLWALL120-MATERIAL-COARSE-PROPOSAL-2026-09-28.json")
HOST_IO_PROJECTION = Path(
    "reports/F4-TALLWALL120-COARSE-HOST-IO-ADMISSION-PROJECTION-2026-09-28.json"
)
CASE_SIDECAR_INTAKE = Path(
    "reports/F4-TALLWALL120-MATERIAL-CASE-SIDECAR-INTAKE-V1-2026-09-28.json"
)
COLLECTION = Path(
    "campaigns/core-v1/cfd/f4-tallwall120-production-root-v1/"
    "collection-refresh-terminal32-formal-v1.json"
)
READER = Path("reports/F4-TALLWALL120-CORE-READER-SMOKE-2026-09-28.json")
ARCHIVE_READER_RECONCILIATION = Path(
    "reports/F4-TALLWALL120-MATERIAL-ARCHIVE-READER-RECONCILIATION-V1-2026-09-29.json"
)
SOURCE_ARCHIVE = Path(
    "campaigns/core-v1/cfd/f4-tallwall120-production-archives-v2/"
    "f4-tallwall120-production-dev-07/archive.json"
)
SOURCE_ARCHIVE_V1 = Path(
    "campaigns/core-v1/cfd/f4-tallwall120-production-archives-v1/"
    "f4-tallwall120-production-dev-07/archive.json"
)
CONSISTENCY = Path(
    "reports/F4-TALLWALL120-MATERIAL-RECEIPT-CONSISTENCY-AUDIT-2026-09-28.json"
)
JOB_SPEC = Path(
    "campaigns/core-v1/cfd/f4-tallwall120-production-root-v1/remaining-24/"
    "f4-tallwall120-production-dev-07.json"
)
RUNTIME_STATUS = Path(
    "campaigns/core-v1/cfd/f4-tallwall120-production-root-v1/"
    "runtime-status-luna-cfd2-v1.json"
)

CURRENT_CODE = {
    "material": Path("scripts/f4_tallwall120_material.py"),
    "material_diagnosis": Path("scripts/f4_tallwall120_material_diagnosis.py"),
    "collector": Path("scripts/core_f4_tallwall120_production_collector.py"),
    "runtime": Path("scripts/core_runtime.py"),
    "cfd_runner": Path("scripts/core_cfd.py"),
}

DEFAULT_OUTPUT_NAMESPACE = (
    "campaigns/core-v1/material/proposals/"
    "f4-tallwall120-production-dev-07/coarse-baseline24-s2-r001-source-6ae8ca70"
)
ROOT_RECEIPT = Path(
    "campaigns/core-v1/material/evidence/"
    "f4-tallwall120-material-root-scheduler-intake-v1/fresh-root-receipt.json"
)
SCHEDULER_RECEIPT = Path(
    "campaigns/core-v1/material/evidence/"
    "f4-tallwall120-material-root-scheduler-intake-v1/"
    "scheduler-host-io-reservation.json"
)

DEFAULT_REPORT = Path(
    "reports/F4-TALLWALL120-MATERIAL-ROOT-SCHEDULER-INTAKE-V1-2026-09-28.json"
)
DEFAULT_ZH_REPORT = Path(
    "reports/F4-TALLWALL120-MATERIAL-ROOT-SCHEDULER-INTAKE-V1-2026-09-28.zh-CN.md"
)

STATUS_MISSING = "blocked_missing_fresh_root_scheduler_receipts"
STATUS_INVALID = "blocked_invalid_fresh_root_scheduler_receipts"
STATUS_BOUND = "fresh_root_scheduler_receipts_bound_non_authorizing"

MAX_JSON_BYTES = 1 * 1024 * 1024
MAX_SMALL_FILE_BYTES = 8 * 1024 * 1024
HDF5_SUFFIXES = {".h5", ".hdf5"}
SHA256 = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z", re.ASCII)
NONCE = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)

HASH_KEYS = (
    "source_sha256",
    "proposal_sha256",
    "host_io_projection_sha256",
    "case_sidecar_intake_sha256",
    "collection_manifest_sha256",
    "reader_smoke_sha256",
    "archive_reader_reconciliation_sha256",
    "source_archive_v1_sha256",
    "source_archive_sha256",
    "consistency_audit_sha256",
    "job_spec_sha256",
    "runtime_status_sha256",
    "material_sha256",
    "material_diagnosis_sha256",
    "collector_sha256",
    "runtime_sha256",
    "cfd_runner_sha256",
)

CHECK_NAMES = (
    "proposal_contract_valid",
    "host_io_projection_contract_valid",
    "case_sidecar_intake_contract_valid",
    "collection_identity_bound",
    "reader_identity_bound",
    "archive_identity_bound",
    "archive_reader_reconciliation_bound",
    "consistency_identity_bound",
    "source_hdf5_metadata_only_valid",
    "source_identity_contract_valid",
    "job_runtime_contract_valid",
    "current_code_hashes_valid",
    "normalized_argv_cwd_valid",
    "fresh_output_namespace_valid",
    "future_root_receipt_present",
    "future_root_receipt_valid",
    "future_scheduler_receipt_present",
    "future_scheduler_receipt_valid",
    "receipt_pair_cross_binding_valid",
    "scheduler_owned_host_io_reservation_valid",
    "intake_contract_valid",
)

SIDE_EFFECT_FIELDS = {
    "worker_started",
    "solver_started",
    "native_started",
    "gpu_started",
    "queue_mutations",
    "registry_mutations",
    "ledger_mutations",
    "denominator_mutations",
    "gate_mutations",
    "plan_mutations",
    "production_hdf5_mutations",
}
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
    "input_refs",
    "hashes",
    "source_identity",
    "normalized_launch",
    "normalized_launch_sha256",
    "fresh_output_namespace",
    "fresh_output_namespace_sha256",
}
FRESH_NAMESPACE_FIELDS = {
    "namespace",
    "namespace_path",
    "namespace_nonce",
    "fresh",
    "reused",
    "same_attempt_resume_only",
    "historical_trace_reuse_forbidden",
}
ROOT_AUTHORIZATION_FIELDS = {
    "authorization_id",
    "root_authorized",
    "single_use",
    "consumed",
}
FRESH_ROOT_FIELDS = {"namespace", "created", "reused", "root_owned"}
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


class IntakeError(ValueError):
    """Raised for an unsafe or malformed bounded input."""

    def __init__(self, message: str, *, code: str = "invalid_input") -> None:
        super().__init__(message)
        self.code = code


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _canonical_digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise IntakeError(f"duplicate JSON object key: {key}", code="duplicate_json_key")
        value[key] = item
    return value


def _reject_constant(token: str) -> Any:
    raise IntakeError(f"non-standard JSON constant is not permitted: {token}", code="non_strict_json")


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _display_path(root: Path, path: Path) -> str:
    path = _absolute(path)
    try:
        return path.relative_to(_absolute(root)).as_posix()
    except ValueError:
        return path.as_posix()


def _resolve(root: Path, value: str | Path) -> Path:
    path = Path(value)
    return _absolute(path if path.is_absolute() else root / path)


def _identity(info: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
        info.st_nlink,
    )


def _assert_no_symlink_components(path: Path, label: str) -> None:
    current = Path(_absolute(path).anchor)
    for component in _absolute(path).parts[1:]:
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
    """Read/hash one stable bounded non-HDF5 regular file."""

    if path.suffix.lower() in HDF5_SUFFIXES:
        raise IntakeError(f"{label} is HDF5 and outside the JSON boundary", code="hdf5_forbidden")
    _assert_no_symlink_components(path, label)
    descriptor: int | None = None
    try:
        descriptor = os.open(os.fspath(path), os.O_RDONLY | O_NOFOLLOW | O_CLOEXEC)
    except FileNotFoundError as error:
        raise IntakeError(f"{label} is missing", code="missing_file") from error
    except OSError as error:
        raise IntakeError(f"{label} cannot be opened safely", code="open_failed") from error
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise IntakeError(f"{label} is not a single-link regular file", code="not_regular_file")
        if before.st_size > limit:
            raise IntakeError(f"{label} exceeds the bounded input limit", code="oversize")
        blocks: list[bytes] = []
        total = 0
        while True:
            block = os.read(descriptor, min(1024 * 1024, limit + 1 - total))
            if not block:
                break
            total += len(block)
            if total > limit:
                raise IntakeError(f"{label} exceeds the bounded input limit", code="oversize")
            blocks.append(block)
        after = os.fstat(descriptor)
        named = os.stat(path, follow_symlinks=False)
        if _identity(before) != _identity(after) or _identity(after) != _identity(named) or total != before.st_size:
            raise IntakeError(f"{label} changed while being read", code="drift")
        payload = b"".join(blocks)
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
        "content_read": False,
        "content_hash_recomputed": False,
        "error": "missing_file",
    }


def _read_json_document(root: Path, path: Path, *, role: str) -> tuple[dict[str, Any] | None, dict[str, Any], str | None]:
    reference = _empty_ref(root, path, role, "bounded_strict_json")
    try:
        raw, metadata = _read_bounded(path, label=role, limit=MAX_JSON_BYTES)
    except IntakeError as error:
        reference["error"] = error.code
        return None, reference, str(error)
    reference.update({"exists": True, **metadata, "content_read": True, "content_hash_recomputed": True})
    reference.pop("error", None)
    try:
        decoded = raw.decode("utf-8", errors="strict")
        value = json.loads(decoded, object_pairs_hook=_strict_object, parse_constant=_reject_constant)
    except IntakeError as error:
        reference["error"] = error.code
        return None, reference, str(error)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        reference["error"] = "invalid_json"
        return None, reference, f"{role} is not strict UTF-8 JSON: {error}"
    if not isinstance(value, dict):
        reference["error"] = "json_not_object"
        return None, reference, f"{role} must be a JSON object"
    return value, reference, None


def _read_small(root: Path, path: Path, *, role: str) -> tuple[dict[str, Any], str | None]:
    reference = _empty_ref(root, path, role, "bounded_small_file")
    try:
        _, metadata = _read_bounded(path, label=role, limit=MAX_SMALL_FILE_BYTES)
    except IntakeError as error:
        reference["error"] = error.code
        return reference, str(error)
    reference.update({"exists": True, **metadata, "content_read": True, "content_hash_recomputed": True})
    reference.pop("error", None)
    return reference, None


def _source_metadata(root: Path, path: Path, *, declared_sha256: Any, declared_bytes: Any) -> tuple[dict[str, Any], str | None]:
    """Stat the trajectory only; do not open, read, or hash it."""

    result: dict[str, Any] = {
        "path": _display_path(root, path),
        "role": "DEV_07 trajectory; prior source hash claim only",
        "mode": "lstat_metadata_only",
        "exists": False,
        "regular_file": False,
        "symlink": False,
        "bytes": None,
        "sha256": declared_sha256 if isinstance(declared_sha256, str) else None,
        "declared_sha256": declared_sha256,
        "declared_bytes": declared_bytes,
        "byte_size_match": False,
        "hash_recomputed": False,
        "opened_as_hdf5": False,
        "read": False,
    }
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        result["error"] = "missing_file"
        return result, "source HDF5 metadata is missing"
    except OSError as error:
        result["error"] = "metadata_failed"
        return result, f"source HDF5 metadata failed: {type(error).__name__}"
    result.update(
        {
            "exists": True,
            "regular_file": stat.S_ISREG(info.st_mode),
            "symlink": stat.S_ISLNK(info.st_mode),
            "bytes": info.st_size,
            "byte_size_match": info.st_size == declared_bytes,
        }
    )
    if not result["regular_file"] or result["symlink"]:
        result["error"] = "source_not_regular_file"
        return result, "source HDF5 is not a regular non-symlink file"
    return result, None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _exact(value: Any, expected: Any, label: str, errors: list[str]) -> bool:
    passed = value == expected
    if not passed:
        errors.append(label)
    return passed


def _ref_pair(reference: Mapping[str, Any]) -> dict[str, Any]:
    return {"path": reference.get("path"), "sha256": reference.get("sha256")}


def _safe_namespace(value: Any) -> bool:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        return False
    return "." not in Path(value).parts and ".." not in Path(value).parts


def _expected_material_argv() -> dict[str, Any]:
    source = f"{{lab_root}}/{SOURCE_HDF5}"
    output = "{fresh_output_namespace}/product/tallwall120_material.h5"
    diagnosis = "{fresh_output_namespace}/product/tallwall120_material_diagnosis.json"
    return {
        "material_trace": [
            "{lab_root}/.venv/bin/python",
            "{lab_root}/scripts/f4_tallwall120_material.py",
            "--source", source,
            "--output", output,
            "--q", "0.23437500000000008",
            "--dp-m", "0.0075",
            "--seeds", "512",
            "--substeps", "2",
            "--neighbour-variant", "baseline24",
            "--stop-after", "217",
        ],
        "diagnosis": [
            "{lab_root}/.venv/bin/python",
            "{lab_root}/scripts/f4_tallwall120_material_diagnosis.py",
            "--source", source,
            "--trace", output,
            "--output", diagnosis,
            "--q", "0.23437500000000008",
            "--dp-m", "0.0075",
            "--substeps", "2",
        ],
        "execution_order": ["material_trace", "diagnosis"],
    }


def _normalize_job_argv(root: Path, value: Any) -> list[str] | None:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return None
    root_text = str(root)
    result: list[str] = []
    for item in value:
        if item == root_text:
            result.append("{lab_root}")
        elif item.startswith(root_text + "/"):
            result.append("{lab_root}" + item[len(root_text):])
        else:
            result.append(item)
    return result


def _expected_job_argv() -> list[str]:
    return [
        "{lab_root}/.venv/bin/python",
        "{lab_root}/scripts/core_cfd.py",
        "--lab-root", "{lab_root}",
        "run", "--prepared",
        "{lab_root}/campaigns/core-v1/cfd/f4-tallwall120-production-root-v1/remaining-24/case-07/prepared.json",
        "--output", "{attempt_dir}/product",
    ]


def _expected_resources(job: Mapping[str, Any]) -> dict[str, Any]:
    resources = _mapping(job.get("resources"))
    return {
        "cpu_cores": resources.get("cpu_cores"),
        "ram_mib": resources.get("ram_mib"),
        "gpu_peak_mib": resources.get("gpu_peak_mib"),
        "io_weight": resources.get("io_weight"),
    }


def _proposal_observation(root: Path, proposal: Mapping[str, Any], namespace_exists: bool, errors: list[str]) -> tuple[bool, dict[str, Any]]:
    target = _mapping(proposal.get("target"))
    params = _mapping(proposal.get("parameter_contract"))
    planned = _mapping(proposal.get("planned_output_namespace"))
    argv = _mapping(proposal.get("argv_contract"))
    qualification = _mapping(proposal.get("qualification"))
    expected_argv = _expected_material_argv()
    target_expected = {
        "family": FAMILY,
        "case_id": CASE_ID,
        "physical_case_id": CASE_ID,
        "lineage_group_id": CASE_ID,
        "source_hdf5": SOURCE_HDF5,
        "source_sha256": SOURCE_SHA256,
        "source_bytes": SOURCE_BYTES,
        "scope_id": SCOPE_ID,
    }
    target_ok = all(target.get(key) == value for key, value in target_expected.items())
    param_ok = all(
        params.get(key) == value
        for key, value in {
            "q": 0.23437500000000008,
            "dp_m": 0.0075,
            "seeds": 512,
            "substeps": 2,
            "neighbour_variant": "baseline24",
            "stop_after_frame": 217,
            "native_frame_count": 218,
            "native_transition_count": 217,
            "extension_window_s": 8.68,
        }.items()
    )
    proposal_state_ok = (
        proposal.get("schema") == "core.material.f4.tallwall120.coarse_proposal.v1"
        and proposal.get("status") == "blocked_fail_closed"
        and proposal.get("proposal_only") is True
        and proposal.get("diagnostic_only") is True
        and proposal.get("formal_eligible") is False
    )
    qualification_closed = (
        qualification.get("T1") is False
        and qualification.get("T2") is False
        and qualification.get("credit") == 0
        and qualification.get("qualification_credit") == 0
        and qualification.get("material_labels_created") is False
        and all(qualification.get(key) == 0 for key in (
            "registry_mutation", "completion_mutation", "ledger_mutation",
            "denominator_mutation", "gate_mutation",
        ))
    )
    namespace_ok = (
        planned.get("namespace") == DEFAULT_OUTPUT_NAMESPACE
        and planned.get("material_h5") == f"{DEFAULT_OUTPUT_NAMESPACE}/product/tallwall120_material.h5"
        and planned.get("diagnosis_json") == f"{DEFAULT_OUTPUT_NAMESPACE}/product/tallwall120_material_diagnosis.json"
        and planned.get("must_be_absent_before_admission") is True
        and planned.get("overwrite_allowed") is False
        and planned.get("resume_allowed") is False
        and planned.get("historical_trace_reuse") is False
        and _safe_namespace(planned.get("namespace"))
        and not namespace_exists
    )
    argv_ok = (
        argv.get("material_trace") == expected_argv["material_trace"]
        and argv.get("diagnosis") == expected_argv["diagnosis"]
        and argv.get("execution_order") == expected_argv["execution_order"]
        and isinstance(argv.get("forbidden_mutations"), list)
        and len(argv.get("forbidden_mutations", [])) >= 3
    )
    checks = {
        "state": proposal_state_ok,
        "target": target_ok,
        "parameters": param_ok,
        "qualification_closed": qualification_closed,
        "fresh_namespace": namespace_ok,
        "normalized_argv": argv_ok,
    }
    if not proposal_state_ok:
        errors.append("proposal_state_invalid")
    if not target_ok:
        errors.append("proposal_DEV07_source_binding_invalid")
    if not param_ok:
        errors.append("proposal_material_parameters_invalid")
    if not qualification_closed:
        errors.append("proposal_qualification_boundary_invalid")
    if not namespace_ok:
        errors.append("proposal_fresh_output_namespace_invalid")
    if not argv_ok:
        errors.append("proposal_normalized_material_argv_invalid")
    checks["contract_valid"] = all(checks.values())
    return checks["contract_valid"], {
        "checks": checks,
        "target": {key: target.get(key) for key in target_expected},
        "parameter_contract": {
            key: params.get(key)
            for key in ("q", "dp_m", "seeds", "substeps", "neighbour_variant", "stop_after_frame", "native_frame_count", "native_transition_count", "extension_window_s")
        },
        "normalized_argv": {
            "observed": {key: argv.get(key) for key in ("material_trace", "diagnosis", "execution_order")},
            "expected": expected_argv,
        },
        "fresh_output_namespace": {
            "namespace": planned.get("namespace"),
            "exists": namespace_exists,
            "must_be_absent_before_admission": planned.get("must_be_absent_before_admission"),
            "overwrite_allowed": planned.get("overwrite_allowed"),
            "resume_allowed": planned.get("resume_allowed"),
            "historical_trace_reuse": planned.get("historical_trace_reuse"),
        },
    }


def _host_observation(root: Path, host: Mapping[str, Any], proposal: Mapping[str, Any], proposal_ref: Mapping[str, Any], job: Mapping[str, Any], job_ref: Mapping[str, Any], errors: list[str]) -> tuple[bool, dict[str, Any]]:
    validation_errors: list[str] = []
    try:
        from scripts import f4_tallwall120_coarse_host_io_admission_v1 as adapter

        validation_errors = list(adapter.validate_projection(host))
    except (ImportError, AttributeError, TypeError, ValueError) as error:
        validation_errors = [f"validator_error:{type(error).__name__}"]
    scope = _mapping(host.get("scope"))
    bindings = _mapping(host.get("input_bindings"))
    fresh = _mapping(host.get("fresh_output_namespace"))
    normalized = _mapping(host.get("normalized_launch"))
    material_stage = _mapping(normalized.get("proposal_material_stage"))
    job_stage = _mapping(normalized.get("f4_job_stage"))
    projection = _mapping(host.get("resource_projection"))
    auth = _mapping(host.get("authorization_boundary"))
    boundary = _mapping(host.get("input_boundary"))
    controls = _mapping(host.get("execution_controls"))
    resources = _expected_resources(job)
    expected_material = _expected_material_argv()
    expected_job = _expected_job_argv()
    checks = {
        "validator": not validation_errors,
        "schema_status": host.get("schema") == "core.material.f4.tallwall120.coarse.host_io_admission_projection.v1" and host.get("status") == "diagnostic_admission_blocked",
        "scope": scope == {"family": FAMILY, "scope_id": SCOPE_ID, "case_id": CASE_ID, "job_id": JOB_ID},
        "proposal_binding": _mapping(bindings.get("proposal")).get("path") == proposal_ref.get("path") and _mapping(bindings.get("proposal")).get("sha256") == proposal_ref.get("sha256"),
        "job_binding": _mapping(bindings.get("job_spec")).get("path") == job_ref.get("path") and _mapping(bindings.get("job_spec")).get("sha256") == job_ref.get("sha256"),
        "material_argv": material_stage.get("observed") == expected_material["material_trace"] and material_stage.get("diagnosis_observed") == expected_material["diagnosis"] and material_stage.get("execution_order") == expected_material["execution_order"],
        "job_argv": job_stage.get("observed") == expected_job,
        "cwd": normalized.get("cwd") == str(root) and job.get("cwd") == str(root),
        "fresh_namespace": fresh.get("namespace") == DEFAULT_OUTPUT_NAMESPACE and fresh.get("namespace_path_exists") is False and fresh.get("overwrite_allowed") is False and fresh.get("resume_allowed") is False and fresh.get("historical_trace_reuse") is False,
        "resources": projection.get("job_resources") == resources and projection.get("ram_mib") == resources.get("ram_mib") and projection.get("io_weight") == resources.get("io_weight") and projection.get("gpu", {}).get("declared_peak_mib") == resources.get("gpu_peak_mib"),
        "projection_not_authorization": projection.get("capacity_or_authorization_claim") is False and projection.get("declared_io_projection", {}).get("scheduler_owned_io_verified") is False,
        "authorization_absent": auth.get("root_authorization_required") is True and auth.get("scheduler_authorization_required") is True and auth.get("root_authorization_present") is False and auth.get("scheduler_authorization_present") is False and auth.get("launch_admitted") is False and auth.get("worker_launch_authorized") is False,
        "boundary_closed": boundary.get("json_only") is True and boundary.get("large_hdf5_opened") is False and boundary.get("large_hdf5_hashed") is False and boundary.get("large_hdf5_content_read") is False and boundary.get("worker_solver_native_gpu_queue_started") is False,
        "controls_closed": controls.get("worker_started") is False and controls.get("solver_started") is False and controls.get("native_started") is False and controls.get("gpu_initialized") is False and controls.get("queue_or_scheduler_started") is False and all(controls.get(key) == 0 for key in ("registry_mutations", "completion_mutations", "ledger_mutations", "denominator_mutations", "gate_mutations")),
    }
    for name, passed in checks.items():
        if not passed:
            errors.append(f"host_io_projection_{name}_invalid")
    checks["contract_valid"] = all(checks.values())
    return checks["contract_valid"], {
        "checks": checks,
        "validation_errors": validation_errors,
        "scope": dict(scope),
        "fresh_output_namespace": dict(fresh),
        "normalized_launch": {
            "cwd": normalized.get("cwd"),
            "material_stage": dict(material_stage),
            "job_stage": dict(job_stage),
        },
        "resource_projection": {
            "job_resources": projection.get("job_resources"),
            "declared_io_projection": projection.get("declared_io_projection"),
            "gpu": projection.get("gpu"),
            "scheduler_owned_io_verified": projection.get("declared_io_projection", {}).get("scheduler_owned_io_verified"),
        },
        "authorization_boundary": dict(auth),
    }


def _sidecar_observation(sidecar: Mapping[str, Any], sidecar_ref: Mapping[str, Any], refs: Mapping[str, Mapping[str, Any]], errors: list[str]) -> tuple[bool, dict[str, Any]]:
    validation_errors: list[str] = []
    try:
        from scripts import f4_tallwall120_material_case_sidecar_intake_v1 as adapter

        validation_errors = list(adapter.validate_report(sidecar))
    except (ImportError, AttributeError, TypeError, ValueError) as error:
        validation_errors = [f"validator_error:{type(error).__name__}"]
    scope = _mapping(sidecar.get("scope"))
    qualification = _mapping(sidecar.get("qualification"))
    boundary = _mapping(sidecar.get("input_boundary"))
    source = _mapping(sidecar.get("source_binding"))
    target = _mapping(source.get("proposal_target"))
    input_bindings = _mapping(sidecar.get("input_bindings"))
    ref_checks: dict[str, bool] = {}
    for name, source_name in (
        ("proposal", "proposal"),
        ("collection_manifest", "collection"),
        ("reader_smoke", "reader"),
        ("source_archive", "archive"),
        ("consistency_audit", "consistency"),
    ):
        observed = _mapping(input_bindings.get(name))
        expected = refs[source_name]
        ref_checks[name] = observed.get("path") == expected.get("path") and observed.get("sha256") == expected.get("sha256")
    checks = {
        "validator": not validation_errors,
        "schema": sidecar.get("schema") == "core.material.f4.tallwall120.case_sidecar_intake.v1",
        "scope": scope.get("family") == FAMILY and scope.get("scope_id") == SCOPE_ID and scope.get("case_id") == CASE_ID,
        "source_target": target.get("family") == FAMILY and target.get("scope_id") == SCOPE_ID and target.get("case_id") == CASE_ID and target.get("source_hdf5") == SOURCE_HDF5 and target.get("source_sha256") == SOURCE_SHA256,
        "input_refs": all(ref_checks.values()),
        "qualification_closed": qualification.get("diagnostic_only") is True and qualification.get("contract_only") is True and qualification.get("formal") is False and qualification.get("formal_eligible") is False and qualification.get("T1") is False and qualification.get("T2") is False and qualification.get("credit") == 0 and qualification.get("qualification_credit") == 0,
        "boundary_closed": boundary.get("bounded_json_only") is True and boundary.get("hdf5_metadata_only") is True and boundary.get("hdf5_content_read") is False and boundary.get("hdf5_hash_recomputed") is False and boundary.get("solver_started") is False and boundary.get("worker_started") is False and boundary.get("gpu_started") is False and boundary.get("queue_started") is False,
    }
    for name, passed in checks.items():
        if not passed:
            errors.append(f"case_sidecar_{name}_invalid")
    checks["contract_valid"] = all(checks.values())
    return checks["contract_valid"], {
        "checks": checks,
        "validation_errors": validation_errors,
        "status": sidecar.get("status"),
        "input_ref_checks": ref_checks,
        "source_target": dict(target),
        "qualification": {key: qualification.get(key) for key in ("diagnostic_only", "formal", "formal_eligible", "T1", "T2", "credit", "qualification_credit")},
        "sidecar_present": sidecar_ref.get("exists") is True,
    }


def _case_row(collection: Mapping[str, Any]) -> Mapping[str, Any]:
    rows = collection.get("cases")
    if not isinstance(rows, list):
        return {}
    matches = [row for row in rows if isinstance(row, Mapping) and row.get("case_id") == CASE_ID]
    return matches[0] if len(matches) == 1 else {}


def _archive_trajectory(archive: Mapping[str, Any]) -> Mapping[str, Any]:
    outputs = archive.get("outputs")
    if not isinstance(outputs, list):
        return {}
    for row in outputs:
        if isinstance(row, Mapping) and row.get("path") == "product/trajectory.h5":
            return row
    return {}


def _source_observation(collection: Mapping[str, Any], reader: Mapping[str, Any], archive: Mapping[str, Any], consistency: Mapping[str, Any], refs: Mapping[str, Mapping[str, Any]], source_ref: Mapping[str, Any], errors: list[str]) -> tuple[dict[str, bool], dict[str, Any]]:
    row = _case_row(collection)
    trajectory = _mapping(row.get("trajectory"))
    archive_trajectory = _archive_trajectory(archive)
    reader_result = _mapping(reader.get("reader_result"))
    collection_binding = _mapping(consistency.get("collection_manifest_binding"))
    reader_binding = _mapping(consistency.get("reader_smoke_binding"))
    archive_binding = _mapping(consistency.get("archives_path_binding"))
    scope = _mapping(consistency.get("scope"))
    collection_identity = (
        collection.get("schema") == "core.f4.tallwall120.production_collection.v1"
        and collection.get("family") == FAMILY
        and collection.get("scope_id") == SCOPE_ID
        and row.get("case_id") == CASE_ID
        and row.get("family") == FAMILY
        and row.get("split") == "train"
        and trajectory.get("sha256") == SOURCE_SHA256
    )
    collection_path_exact = trajectory.get("path") == SOURCE_HDF5
    reader_identity = (
        reader.get("schema") == "local.f4.core_reader_smoke.stdout.v1"
        and reader.get("family") == FAMILY
        and reader.get("scope_id") == SCOPE_ID
        and reader.get("manifest") == refs["collection"]["path"]
        and reader_result.get("diagnostic_only") is True
        and reader_result.get("reader_formal_eligible") is False
        and reader_result.get("formal_credit_granted_by_this_smoke") is False
        and reader_result.get("t2_credit_granted_by_this_smoke") is False
        and reader_result.get("qualification_credit") == 0
    )
    reader_sha_exact = reader.get("manifest_sha256") == refs["collection"].get("sha256")
    archive_identity = (
        archive.get("schema") == "core.verified_archive.v1"
        and archive.get("execution_status") == "succeeded"
        and archive.get("job_id") == JOB_ID
        and archive_trajectory.get("path") == "product/trajectory.h5"
        and archive_trajectory.get("sha256") == SOURCE_SHA256
        and archive_trajectory.get("bytes") == SOURCE_BYTES
    )
    consistency_identity = (
        consistency.get("schema") == "core.material.f4.tallwall120.receipt_consistency_audit.v1"
        and consistency.get("status") == "blocked_fail_closed"
        and consistency.get("diagnostic_only") is True
        and consistency.get("formal_eligible") is False
        and scope.get("family") == FAMILY
        and scope.get("proposal_scope") == SCOPE_ID
        and scope.get("case_id") == CASE_ID
        and scope.get("target_hdf5") == SOURCE_HDF5
        and scope.get("target_hdf5_sha256") == SOURCE_SHA256
        and archive_binding.get("source_sha256_match") is True
        and _mapping(consistency.get("execution_controls")).get("root_authorization") is False
        and _mapping(consistency.get("execution_controls")).get("scheduler_authorization") is False
    )
    source_metadata_valid = (
        source_ref.get("exists") is True
        and source_ref.get("regular_file") is True
        and source_ref.get("symlink") is False
        and source_ref.get("bytes") == SOURCE_BYTES
        and source_ref.get("sha256") == SOURCE_SHA256
        and source_ref.get("hash_recomputed") is False
        and source_ref.get("opened_as_hdf5") is False
        and source_ref.get("read") is False
    )
    source_contract = collection_identity and collection_path_exact and reader_identity and reader_sha_exact and archive_identity and consistency_identity and source_metadata_valid
    checks = {
        "collection_identity_bound": collection_identity,
        "reader_identity_bound": reader_identity and reader_sha_exact,
        "archive_identity_bound": archive_identity,
        "consistency_identity_bound": consistency_identity,
        "source_hdf5_metadata_only_valid": source_metadata_valid,
        "source_identity_contract_valid": source_contract,
    }
    for name, passed in checks.items():
        if not passed:
            errors.append(f"{name}_false")
    return checks, {
        "proposal_source": {"path": SOURCE_HDF5, "sha256": SOURCE_SHA256, "bytes": SOURCE_BYTES},
        "collection": {
            "path": refs["collection"].get("path"),
            "sha256": refs["collection"].get("sha256"),
            "schema": collection.get("schema"),
            "case_id": row.get("case_id"),
            "declared_hdf5": trajectory.get("path"),
            "declared_sha256": trajectory.get("sha256"),
            "path_exact": collection_path_exact,
            "identity_bound": collection_identity,
        },
        "reader": {
            "path": refs["reader"].get("path"),
            "sha256": refs["reader"].get("sha256"),
            "manifest": reader.get("manifest"),
            "manifest_sha256": reader.get("manifest_sha256"),
            "current_manifest_sha256": refs["collection"].get("sha256"),
            "manifest_sha_exact": reader_sha_exact,
            "diagnostic_only": reader_result.get("diagnostic_only"),
            "formal_eligible": reader_result.get("reader_formal_eligible"),
        },
        "archive": {
            "path": refs["archive"].get("path"),
            "sha256": refs["archive"].get("sha256"),
            "trajectory": dict(archive_trajectory),
            "identity_bound": archive_identity,
        },
        "consistency": {
            "path": refs["consistency"].get("path"),
            "sha256": refs["consistency"].get("sha256"),
            "status": consistency.get("status"),
            "scope": dict(scope),
            "archives_path_binding": dict(archive_binding),
            "collection_manifest_binding": dict(collection_binding),
            "reader_smoke_binding": dict(reader_binding),
            "identity_bound": consistency_identity,
        },
        "trajectory_hdf5": dict(source_ref),
    }


def _archive_reader_reconciliation_observation(
    report: Mapping[str, Any] | None,
    report_ref: Mapping[str, Any],
    refs: Mapping[str, Mapping[str, Any]],
    errors: list[str],
) -> tuple[bool, dict[str, Any]]:
    """Bind the checked-in archive/reader reconciliation to current refs.

    The reconciliation report is itself diagnostic evidence.  This observer
    accepts it only when its bounded input references and fail-closed markers
    match the current root intake inputs; it never turns that report into
    launch authority.
    """

    from scripts import f4_tallwall120_material_archive_reader_reconciliation_v1 as contract

    observed_errors: list[str] = []
    if not isinstance(report, Mapping):
        observed_errors.append("report_missing_or_not_object")
    else:
        observed_errors.extend(contract.validate_report(report))
    report_inputs = _mapping(report.get("inputs")) if isinstance(report, Mapping) else {}
    expected_inputs = {
        "proposal": refs.get("proposal", {}),
        "archive_v1": refs.get("archive_v1", {}),
        "archive_v2": refs.get("archive", {}),
        "collection": refs.get("collection", {}),
        "reader": refs.get("reader", {}),
    }
    input_bindings: dict[str, dict[str, Any]] = {}
    for name, expected in expected_inputs.items():
        observed = _mapping(report_inputs.get(name))
        input_bindings[name] = {
            "path": observed.get("path"),
            "sha256": observed.get("sha256"),
            "expected_path": expected.get("path"),
            "expected_sha256": expected.get("sha256"),
            "exact": observed.get("path") == expected.get("path") and observed.get("sha256") == expected.get("sha256"),
        }
        if not input_bindings[name]["exact"]:
            observed_errors.append(f"input_binding_{name}_drift")

    checks = _mapping(report.get("checks")) if isinstance(report, Mapping) else {}
    required_true = (
        "proposal_target_exact",
        "proposal_direct_archive_v2_exact",
        "archive_v1_manifest_contract_valid",
        "archive_v2_manifest_contract_valid",
        "archive_v1_v2_artifact_identity_exact",
        "collection_manifest_current_sha_bound",
        "collection_case_unique",
        "collection_case_source_sha_exact",
        "reader_manifest_path_exact",
        "reader_formal_gate_closed",
    )
    required_false = ("collection_case_source_path_exact", "reader_manifest_sha_exact")
    for name in required_true:
        if checks.get(name) is not True:
            observed_errors.append(f"check_{name}_false")
    for name in required_false:
        if checks.get(name) is not False:
            observed_errors.append(f"check_{name}_not_blocking")
    source_reconciliation = _mapping(report.get("source_reconciliation")) if isinstance(report, Mapping) else {}
    authority = _mapping(report.get("authority")) if isinstance(report, Mapping) else {}
    if source_reconciliation.get("ready") is not False:
        observed_errors.append("source_reconciliation_must_remain_blocked")
    if authority.get("launch_allowed") is not False or authority.get("worker_launch_authorized") is not False or authority.get("credit") != 0:
        observed_errors.append("archive_reader_authority_promoted")

    if observed_errors:
        errors.extend(f"archive_reader_reconciliation:{item}" for item in observed_errors)
    return not observed_errors, {
        "path": report_ref.get("path"),
        "sha256": report_ref.get("sha256"),
        "schema": report.get("schema") if isinstance(report, Mapping) else None,
        "record_id": report.get("record_id") if isinstance(report, Mapping) else None,
        "status": report.get("status") if isinstance(report, Mapping) else None,
        "source_reconciliation_ready": source_reconciliation.get("ready"),
        "authority": {
            "launch_allowed": authority.get("launch_allowed"),
            "worker_launch_authorized": authority.get("worker_launch_authorized"),
            "credit": authority.get("credit"),
        },
        "input_bindings": input_bindings,
        "contract_errors": observed_errors,
        "identity_bound": not observed_errors,
    }


def _job_runtime_observation(root: Path, job: Mapping[str, Any], runtime_status: Mapping[str, Any], errors: list[str]) -> tuple[bool, dict[str, Any]]:
    resources = _expected_resources(job)
    normalized = _normalize_job_argv(root, job.get("argv"))
    job_ok = (
        job.get("schema") == "core.cfd.job.v1"
        and job.get("job_id") == JOB_ID
        and job.get("logical_id") == JOB_ID
        and job.get("family") == FAMILY
        and job.get("scope_id") == SCOPE_ID
        and job.get("prepared_case_id") == CASE_ID
        and job.get("production_index") == 7
        and job.get("batch_status") == "remaining_24"
        and job.get("split") == "train"
        and job.get("qualification_only") is False
        and job.get("qualification_claim") == "none; production evidence pending"
        and resources == {"cpu_cores": 2, "ram_mib": 24576, "gpu_peak_mib": 6144, "io_weight": 2}
        and normalized == _expected_job_argv()
        and job.get("cwd") == str(root)
        and job.get("source_lab") == str(root)
    )
    runtime_ok = (
        runtime_status.get("schema") == "core.f4.tallwall120.production_runtime_status.v1"
        and runtime_status.get("scope_id") == SCOPE_ID
        and runtime_status.get("revision_id") == "F4_tallwall120_13plus2_v2"
        and runtime_status.get("central_ledger_written_by_this_audit") is False
        and runtime_status.get("central_queue_mutated_by_this_audit") is False
    )
    checks = {"job": job_ok, "runtime_status": runtime_ok, "contract_valid": job_ok and runtime_ok}
    for name, passed in checks.items():
        if name != "contract_valid" and not passed:
            errors.append(f"job_runtime_{name}_invalid")
    return checks["contract_valid"], {
        "checks": checks,
        "job": {
            "schema": job.get("schema"),
            "job_id": job.get("job_id"),
            "scope_id": job.get("scope_id"),
            "cwd": job.get("cwd"),
            "resources": resources,
            "normalized_argv": normalized,
        },
        "runtime_status": {
            "schema": runtime_status.get("schema"),
            "scope_id": runtime_status.get("scope_id"),
            "revision_id": runtime_status.get("revision_id"),
            "status_counts": runtime_status.get("status_counts"),
            "central_queue_mutated_by_this_audit": runtime_status.get("central_queue_mutated_by_this_audit"),
            "central_ledger_written_by_this_audit": runtime_status.get("central_ledger_written_by_this_audit"),
        },
    }


def _side_effects_closed(value: Any, label: str, errors: list[str]) -> bool:
    if not isinstance(value, Mapping) or set(value) != SIDE_EFFECT_FIELDS:
        errors.append(f"{label}.fields")
        return False
    passed = True
    for key in ("worker_started", "solver_started", "native_started", "gpu_started"):
        if value.get(key) is not False:
            errors.append(f"{label}.{key}")
            passed = False
    for key in ("queue_mutations", "registry_mutations", "ledger_mutations", "denominator_mutations", "gate_mutations", "plan_mutations", "production_hdf5_mutations"):
        if value.get(key) != 0:
            errors.append(f"{label}.{key}")
            passed = False
    return passed


def _validate_namespace(value: Any, expected_namespace: str, errors: list[str]) -> dict[str, Any] | None:
    if not isinstance(value, Mapping) or set(value) != FRESH_NAMESPACE_FIELDS:
        errors.append("binding.fresh_output_namespace.fields")
        return None
    if value.get("namespace") != expected_namespace or value.get("namespace_path") != expected_namespace:
        errors.append("binding.fresh_output_namespace.namespace")
    if not isinstance(value.get("namespace_nonce"), str) or NONCE.fullmatch(str(value.get("namespace_nonce"))) is None:
        errors.append("binding.fresh_output_namespace.namespace_nonce")
    for key, expected in (("fresh", True), ("reused", False), ("same_attempt_resume_only", True), ("historical_trace_reuse_forbidden", True)):
        if value.get(key) is not expected:
            errors.append(f"binding.fresh_output_namespace.{key}")
    return dict(value)


def _validate_binding(value: Any, expected: Mapping[str, Any], errors: list[str]) -> tuple[bool, dict[str, Any]]:
    start = len(errors)
    if not isinstance(value, Mapping) or set(value) != BINDING_FIELDS:
        errors.append("receipt.binding.fields")
        return False, {}
    input_refs = value.get("input_refs")
    if not isinstance(input_refs, Mapping) or set(input_refs) != set(expected["input_refs"]):
        errors.append("receipt.binding.input_refs.fields")
    else:
        for name, ref in expected["input_refs"].items():
            observed = _mapping(input_refs.get(name))
            if observed.get("path") != ref.get("path") or observed.get("sha256") != ref.get("sha256"):
                errors.append(f"receipt.binding.input_refs.{name}")
    if value.get("hashes") != expected["hashes"]:
        errors.append("receipt.binding.hashes")
    if value.get("source_identity") != expected["source_identity"]:
        errors.append("receipt.binding.source_identity")
    if value.get("normalized_launch") != expected["normalized_launch"]:
        errors.append("receipt.binding.normalized_launch")
    if value.get("normalized_launch_sha256") != _canonical_digest(expected["normalized_launch"]):
        errors.append("receipt.binding.normalized_launch_sha256")
    namespace = _validate_namespace(value.get("fresh_output_namespace"), expected["namespace"], errors)
    if namespace is not None and value.get("fresh_output_namespace_sha256") != _canonical_digest(namespace):
        errors.append("receipt.binding.fresh_output_namespace_sha256")
    return len(errors) == start, dict(value)


def _counterparty(value: Any, *, path: Any, binding_sha256: str, pair_id: Any, label: str, errors: list[str]) -> bool:
    if not isinstance(value, Mapping) or set(value) != {"path", "binding_sha256", "pair_id"}:
        errors.append(f"{label}.fields")
        return False
    passed = value.get("path") == path and value.get("binding_sha256") == binding_sha256 and value.get("pair_id") == pair_id
    if not passed:
        errors.append(f"{label}.value")
    return passed


def _validate_root_receipt(value: Mapping[str, Any] | None, expected: Mapping[str, Any], scheduler_ref: Mapping[str, Any], scheduler_binding_sha256: str, errors: list[str]) -> tuple[bool, dict[str, Any]]:
    start = len(errors)
    if not isinstance(value, Mapping):
        errors.append("root_receipt.missing_or_not_object")
        return False, {}
    if set(value) != ROOT_RECEIPT_FIELDS:
        errors.append("root_receipt.fields")
    _exact(value.get("schema"), ROOT_RECEIPT_SCHEMA, "root_receipt.schema", errors)
    _exact(value.get("record_id"), ROOT_RECEIPT_ID, "root_receipt.record_id", errors)
    _exact(value.get("status"), "root_authorization_issued", "root_receipt.status", errors)
    _exact(value.get("synthetic"), False, "root_receipt.synthetic", errors)
    pair_id = value.get("pair_id")
    if not isinstance(pair_id, str) or SAFE_ID.fullmatch(pair_id) is None:
        errors.append("root_receipt.pair_id")
    binding_ok, binding = _validate_binding(value.get("binding"), expected, errors)
    _counterparty(value.get("counterparty"), path=scheduler_ref.get("path"), binding_sha256=scheduler_binding_sha256, pair_id=pair_id, label="root_receipt.counterparty", errors=errors)
    fresh_root = value.get("fresh_root")
    if not isinstance(fresh_root, Mapping) or set(fresh_root) != FRESH_ROOT_FIELDS:
        errors.append("root_receipt.fresh_root.fields")
    else:
        _exact(fresh_root.get("namespace"), expected["namespace"], "root_receipt.fresh_root.namespace", errors)
        for key, expected_value in (("created", True), ("reused", False), ("root_owned", True)):
            _exact(fresh_root.get(key), expected_value, f"root_receipt.fresh_root.{key}", errors)
    authorization = value.get("root_authorization")
    if not isinstance(authorization, Mapping) or set(authorization) != ROOT_AUTHORIZATION_FIELDS:
        errors.append("root_receipt.root_authorization.fields")
    else:
        if not isinstance(authorization.get("authorization_id"), str) or SAFE_ID.fullmatch(authorization.get("authorization_id")) is None:
            errors.append("root_receipt.root_authorization.authorization_id")
        for key, expected_value in (("root_authorized", True), ("single_use", True), ("consumed", False)):
            _exact(authorization.get(key), expected_value, f"root_receipt.root_authorization.{key}", errors)
    _side_effects_closed(value.get("side_effects"), "root_receipt.side_effects", errors)
    return len(errors) == start, {"pair_id": pair_id, "binding": binding, "fresh_root": dict(_mapping(fresh_root)), "root_authorization": dict(_mapping(authorization))}


def _finite_nonnegative(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)) and float(value) >= 0


def _validate_scheduler_receipt(value: Mapping[str, Any] | None, expected: Mapping[str, Any], root_ref: Mapping[str, Any], root_binding_sha256: str, expected_resources: Mapping[str, Any], errors: list[str]) -> tuple[bool, dict[str, Any]]:
    start = len(errors)
    if not isinstance(value, Mapping):
        errors.append("scheduler_receipt.missing_or_not_object")
        return False, {}
    if set(value) != SCHEDULER_RECEIPT_FIELDS:
        errors.append("scheduler_receipt.fields")
    _exact(value.get("schema"), SCHEDULER_RECEIPT_SCHEMA, "scheduler_receipt.schema", errors)
    _exact(value.get("record_id"), SCHEDULER_RECEIPT_ID, "scheduler_receipt.record_id", errors)
    _exact(value.get("status"), "scheduler_host_io_reserved", "scheduler_receipt.status", errors)
    _exact(value.get("synthetic"), False, "scheduler_receipt.synthetic", errors)
    pair_id = value.get("pair_id")
    if not isinstance(pair_id, str) or SAFE_ID.fullmatch(pair_id) is None:
        errors.append("scheduler_receipt.pair_id")
    binding_ok, binding = _validate_binding(value.get("binding"), expected, errors)
    _counterparty(value.get("counterparty"), path=root_ref.get("path"), binding_sha256=root_binding_sha256, pair_id=pair_id, label="scheduler_receipt.counterparty", errors=errors)
    reservation = value.get("scheduler_reservation")
    if not isinstance(reservation, Mapping) or set(reservation) != SCHEDULER_RESERVATION_FIELDS:
        errors.append("scheduler_receipt.scheduler_reservation.fields")
    else:
        if not isinstance(reservation.get("reservation_id"), str) or SAFE_ID.fullmatch(reservation.get("reservation_id")) is None:
            errors.append("scheduler_receipt.scheduler_reservation.reservation_id")
        for key, expected_value in (("reservation_active", True), ("scheduler_owned_host_io_verified", True), ("single_use", True), ("consumed", False)):
            _exact(reservation.get(key), expected_value, f"scheduler_receipt.scheduler_reservation.{key}", errors)
        _exact(reservation.get("resource_request"), dict(expected_resources), "scheduler_receipt.scheduler_reservation.resource_request", errors)
        host_io = reservation.get("host_io_reservation")
        if not isinstance(host_io, Mapping) or set(host_io) != HOST_IO_RESERVATION_FIELDS:
            errors.append("scheduler_receipt.host_io_reservation.fields")
        else:
            _exact(host_io.get("io_weight"), expected_resources.get("io_weight"), "scheduler_receipt.host_io_reservation.io_weight", errors)
            if not _finite_nonnegative(host_io.get("owned_io_weight")) or not _finite_nonnegative(host_io.get("io_capacity")):
                errors.append("scheduler_receipt.host_io_reservation.capacity")
            elif float(host_io["owned_io_weight"]) < float(expected_resources.get("io_weight") or 0) or float(host_io["io_capacity"]) < float(host_io["owned_io_weight"]):
                errors.append("scheduler_receipt.host_io_reservation.capacity_headroom")
            for key in ("filesystem", "snapshot_id"):
                if not isinstance(host_io.get(key), str) or not host_io.get(key):
                    errors.append(f"scheduler_receipt.host_io_reservation.{key}")
    _side_effects_closed(value.get("side_effects"), "scheduler_receipt.side_effects", errors)
    return len(errors) == start, {"pair_id": pair_id, "binding": binding, "scheduler_reservation": dict(_mapping(reservation))}


def _authorization() -> dict[str, Any]:
    return {
        "diagnostic_only": True,
        "formal": False,
        "formal_eligible": False,
        "T1": False,
        "T2": False,
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
        "native_started": False,
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


def _input_ref_map(refs: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    return {name: _ref_pair(refs[name]) for name in ("proposal", "host_io_projection", "case_sidecar_intake", "collection", "reader", "archive_v1", "archive", "archive_reader_reconciliation", "consistency", "job_spec", "runtime_status", "material", "material_diagnosis", "collector", "runtime", "cfd_runner")}


def build_report(
    root: str | Path = LAB_ROOT,
    *,
    proposal_path: str | Path | None = None,
    host_io_projection_path: str | Path | None = None,
    host_io_admission_path: str | Path | None = None,
    case_sidecar_intake_path: str | Path | None = None,
    sidecar_intake_path: str | Path | None = None,
    collection_path: str | Path | None = None,
    reader_path: str | Path | None = None,
    archive_reader_reconciliation_path: str | Path | None = None,
    source_archive_v1_path: str | Path | None = None,
    source_archive_path: str | Path | None = None,
    consistency_path: str | Path | None = None,
    job_spec_path: str | Path | None = None,
    runtime_status_path: str | Path | None = None,
    root_receipt_path: str | Path | None = None,
    scheduler_receipt_path: str | Path | None = None,
) -> dict[str, Any]:
    root = _absolute(Path(root))
    proposal_file = _resolve(root, proposal_path or PROPOSAL)
    host_file = _resolve(root, host_io_projection_path or host_io_admission_path or HOST_IO_PROJECTION)
    sidecar_file = _resolve(root, case_sidecar_intake_path or sidecar_intake_path or CASE_SIDECAR_INTAKE)
    collection_file = _resolve(root, collection_path or COLLECTION)
    reader_file = _resolve(root, reader_path or READER)
    archive_reader_file = _resolve(root, archive_reader_reconciliation_path or ARCHIVE_READER_RECONCILIATION)
    archive_v1_file = _resolve(root, source_archive_v1_path or SOURCE_ARCHIVE_V1)
    archive_file = _resolve(root, source_archive_path or SOURCE_ARCHIVE)
    consistency_file = _resolve(root, consistency_path or CONSISTENCY)
    job_file = _resolve(root, job_spec_path or JOB_SPEC)
    runtime_status_file = _resolve(root, runtime_status_path or RUNTIME_STATUS)
    root_file = _resolve(root, root_receipt_path or ROOT_RECEIPT)
    scheduler_file = _resolve(root, scheduler_receipt_path or SCHEDULER_RECEIPT)

    proposal, proposal_ref, proposal_error = _read_json_document(root, proposal_file, role="F4 coarse material proposal")
    host, host_ref, host_error = _read_json_document(root, host_file, role="F4 coarse host-I/O projection")
    sidecar, sidecar_ref, sidecar_error = _read_json_document(root, sidecar_file, role="F4 material case-sidecar intake")
    collection, collection_ref, collection_error = _read_json_document(root, collection_file, role="F4 collection manifest")
    reader, reader_ref, reader_error = _read_json_document(root, reader_file, role="F4 reader smoke")
    archive_reader, archive_reader_ref, archive_reader_error = _read_json_document(root, archive_reader_file, role="F4 archive/reader reconciliation")
    archive_v1, archive_v1_ref, archive_v1_error = _read_json_document(root, archive_v1_file, role="F4 archives-v1 source archive manifest")
    archive, archive_ref, archive_error = _read_json_document(root, archive_file, role="F4 source archive manifest")
    consistency, consistency_ref, consistency_error = _read_json_document(root, consistency_file, role="F4 receipt consistency audit")
    job, job_ref, job_error = _read_json_document(root, job_file, role="F4 DEV_07 job specification")
    runtime_status, runtime_status_ref, runtime_status_error = _read_json_document(root, runtime_status_file, role="F4 runtime status")
    root_receipt, root_ref, root_error = _read_json_document(root, root_file, role="future F4 fresh root receipt")
    scheduler_receipt, scheduler_ref, scheduler_error = _read_json_document(root, scheduler_file, role="future F4 scheduler host-I/O receipt")

    code_refs: dict[str, dict[str, Any]] = {}
    input_errors: list[str] = []
    for name, relative in CURRENT_CODE.items():
        reference, error = _read_small(root, _resolve(root, relative), role=f"current {name} source")
        code_refs[name] = reference
        if error:
            input_errors.append(f"{name}:{error}")
    for label, error in (
        ("proposal", proposal_error), ("host_io_projection", host_error), ("case_sidecar_intake", sidecar_error),
        ("collection", collection_error), ("reader", reader_error), ("archive_reader_reconciliation", archive_reader_error), ("archive_v1", archive_v1_error), ("archive", archive_error),
        ("consistency", consistency_error), ("job_spec", job_error), ("runtime_status", runtime_status_error),
        ("root_receipt", root_error), ("scheduler_receipt", scheduler_error),
    ):
        if error:
            input_errors.append(f"{label}:{error}")

    proposal = proposal if isinstance(proposal, Mapping) else {}
    host = host if isinstance(host, Mapping) else {}
    sidecar = sidecar if isinstance(sidecar, Mapping) else {}
    collection = collection if isinstance(collection, Mapping) else {}
    reader = reader if isinstance(reader, Mapping) else {}
    archive_reader = archive_reader if isinstance(archive_reader, Mapping) else {}
    archive_v1 = archive_v1 if isinstance(archive_v1, Mapping) else {}
    archive = archive if isinstance(archive, Mapping) else {}
    consistency = consistency if isinstance(consistency, Mapping) else {}
    job = job if isinstance(job, Mapping) else {}
    runtime_status = runtime_status if isinstance(runtime_status, Mapping) else {}
    target = _mapping(proposal.get("target"))
    source_ref, source_error = _source_metadata(root, _resolve(root, SOURCE_HDF5), declared_sha256=target.get("source_sha256", SOURCE_SHA256), declared_bytes=target.get("source_bytes", SOURCE_BYTES))
    if source_error:
        input_errors.append(source_error)

    namespace_path = _resolve(root, DEFAULT_OUTPUT_NAMESPACE)
    errors: list[str] = []
    proposal_valid, proposal_observation = _proposal_observation(root, proposal, namespace_path.exists(), errors)
    host_valid, host_observation = _host_observation(root, host, proposal, proposal_ref, job, job_ref, errors)
    refs_for_sidecar = {
        "proposal": proposal_ref,
        "collection": collection_ref,
        "reader": reader_ref,
        "archive": archive_ref,
        "consistency": consistency_ref,
    }
    sidecar_valid, sidecar_observation = _sidecar_observation(sidecar, sidecar_ref, refs_for_sidecar, errors)
    source_checks, source_observation = _source_observation(collection, reader, archive, consistency, {"collection": collection_ref, "reader": reader_ref, "archive": archive_ref, "consistency": consistency_ref}, source_ref, errors)
    archive_reader_valid, archive_reader_observation = _archive_reader_reconciliation_observation(
        archive_reader,
        archive_reader_ref,
        {"proposal": proposal_ref, "archive_v1": archive_v1_ref, "archive": archive_ref, "collection": collection_ref, "reader": reader_ref},
        errors,
    )
    job_runtime_valid, job_runtime_observation = _job_runtime_observation(root, job, runtime_status, errors)

    all_refs: dict[str, dict[str, Any]] = {
        "proposal": proposal_ref,
        "host_io_projection": host_ref,
        "case_sidecar_intake": sidecar_ref,
        "collection": collection_ref,
        "reader": reader_ref,
        "archive_v1": archive_v1_ref,
        "archive": archive_ref,
        "archive_reader_reconciliation": archive_reader_ref,
        "consistency": consistency_ref,
        "job_spec": job_ref,
        "runtime_status": runtime_status_ref,
        "material": code_refs["material"],
        "material_diagnosis": code_refs["material_diagnosis"],
        "collector": code_refs["collector"],
        "runtime": code_refs["runtime"],
        "cfd_runner": code_refs["cfd_runner"],
    }
    input_refs = _input_ref_map(all_refs)
    hashes = {
        "source_sha256": source_ref.get("sha256"),
        "proposal_sha256": proposal_ref.get("sha256"),
        "host_io_projection_sha256": host_ref.get("sha256"),
        "case_sidecar_intake_sha256": sidecar_ref.get("sha256"),
        "collection_manifest_sha256": collection_ref.get("sha256"),
        "reader_smoke_sha256": reader_ref.get("sha256"),
        "archive_reader_reconciliation_sha256": archive_reader_ref.get("sha256"),
        "source_archive_v1_sha256": archive_v1_ref.get("sha256"),
        "source_archive_sha256": archive_ref.get("sha256"),
        "consistency_audit_sha256": consistency_ref.get("sha256"),
        "job_spec_sha256": job_ref.get("sha256"),
        "runtime_status_sha256": runtime_status_ref.get("sha256"),
        "material_sha256": code_refs["material"].get("sha256"),
        "material_diagnosis_sha256": code_refs["material_diagnosis"].get("sha256"),
        "collector_sha256": code_refs["collector"].get("sha256"),
        "runtime_sha256": code_refs["runtime"].get("sha256"),
        "cfd_runner_sha256": code_refs["cfd_runner"].get("sha256"),
    }
    current_code_valid = all(isinstance(code_refs[name].get("sha256"), str) and SHA256.fullmatch(code_refs[name]["sha256"]) for name in CURRENT_CODE)
    if not current_code_valid:
        errors.append("current_code_hashes_missing_or_invalid")
    normalized_launch = {
        "cwd": str(root),
        "material_trace": _mapping(proposal.get("argv_contract")).get("material_trace", []),
        "diagnosis": _mapping(proposal.get("argv_contract")).get("diagnosis", []),
        "execution_order": _mapping(proposal.get("argv_contract")).get("execution_order", []),
        "production_job": _normalize_job_argv(root, job.get("argv")),
        "output_namespace": DEFAULT_OUTPUT_NAMESPACE,
        "shell": False,
        "resume_allowed": False,
    }
    normalized_valid = proposal_observation["checks"]["normalized_argv"] and host_observation["checks"]["material_argv"] and host_observation["checks"]["job_argv"] and normalized_launch["cwd"] == str(root) and normalized_launch["production_job"] == _expected_job_argv()
    if not normalized_valid:
        errors.append("normalized_argv_cwd_binding_invalid")
    namespace_contract = {
        "namespace": DEFAULT_OUTPUT_NAMESPACE,
        "namespace_path": DEFAULT_OUTPUT_NAMESPACE,
        "namespace_path_exists": namespace_path.exists(),
        "must_be_absent_before_admission": True,
        "overwrite_allowed": False,
        "resume_allowed": False,
        "historical_trace_reuse": False,
    }
    namespace_valid = proposal_observation["checks"]["fresh_namespace"] and host_observation["checks"]["fresh_namespace"]
    if not namespace_valid:
        errors.append("fresh_output_namespace_invalid")

    source_identity = dict(source_observation)
    source_identity["archive_reader_reconciliation"] = archive_reader_observation
    job_runtime_valid = job_runtime_valid and current_code_valid
    binding_expected = {
        "input_refs": input_refs,
        "hashes": hashes,
        "source_identity": source_identity,
        "normalized_launch": normalized_launch,
        "namespace": DEFAULT_OUTPUT_NAMESPACE,
    }
    root_errors: list[str] = []
    scheduler_errors: list[str] = []
    root_valid, root_projection = _validate_root_receipt(root_receipt, binding_expected, scheduler_ref, _canonical_digest(_mapping(scheduler_receipt).get("binding")), root_errors)
    scheduler_valid, scheduler_projection = _validate_scheduler_receipt(scheduler_receipt, binding_expected, root_ref, _canonical_digest(_mapping(root_receipt).get("binding")), _expected_resources(job), scheduler_errors)
    root_present = root_ref.get("exists") is True
    scheduler_present = scheduler_ref.get("exists") is True
    pair_id = root_projection.get("pair_id")
    scheduler_pair_id = scheduler_projection.get("pair_id")
    pair_valid = bool(root_valid and scheduler_valid and pair_id and pair_id == scheduler_pair_id)
    namespace_receipt_root = _mapping(root_projection.get("binding")).get("fresh_output_namespace")
    namespace_receipt_scheduler = _mapping(scheduler_projection.get("binding")).get("fresh_output_namespace")
    receipt_namespace_valid = bool(root_valid and scheduler_valid and namespace_receipt_root == namespace_receipt_scheduler)
    reservation = _mapping(scheduler_projection.get("scheduler_reservation"))
    reservation_valid = bool(scheduler_valid and reservation.get("scheduler_owned_host_io_verified") is True and reservation.get("resource_request") == _expected_resources(job))
    if not pair_valid:
        errors.append("root_scheduler_pair_cross_binding_invalid")
    if not receipt_namespace_valid:
        errors.append("fresh_output_namespace_receipt_cross_binding_invalid")
    if not reservation_valid:
        errors.append("scheduler_owned_host_io_reservation_missing_or_mismatched")
    checks: dict[str, bool] = {
        "proposal_contract_valid": proposal_valid,
        "host_io_projection_contract_valid": host_valid,
        "case_sidecar_intake_contract_valid": sidecar_valid,
        **source_checks,
        "archive_reader_reconciliation_bound": archive_reader_valid,
        "job_runtime_contract_valid": job_runtime_valid,
        "current_code_hashes_valid": current_code_valid,
        "normalized_argv_cwd_valid": normalized_valid,
        "fresh_output_namespace_valid": namespace_valid,
        "future_root_receipt_present": root_present,
        "future_root_receipt_valid": root_valid,
        "future_scheduler_receipt_present": scheduler_present,
        "future_scheduler_receipt_valid": scheduler_valid,
        "receipt_pair_cross_binding_valid": pair_valid and receipt_namespace_valid,
        "scheduler_owned_host_io_reservation_valid": reservation_valid,
    }
    checks["intake_contract_valid"] = all(checks.get(name) is True for name in CHECK_NAMES[:-1])
    if checks["intake_contract_valid"]:
        status = STATUS_BOUND
        blockers: list[str] = []
    elif not root_present or not scheduler_present:
        status = STATUS_MISSING
        blockers = errors + input_errors
    else:
        status = STATUS_INVALID
        blockers = errors + input_errors + [f"root_receipt:{item}" for item in root_errors] + [f"scheduler_receipt:{item}" for item in scheduler_errors]
    blockers = list(dict.fromkeys(str(item) for item in blockers if item))
    if not checks["future_root_receipt_valid"]:
        blockers.extend(f"root_receipt:{item}" for item in root_errors if item not in blockers)
    if not checks["future_scheduler_receipt_valid"]:
        blockers.extend(f"scheduler_receipt:{item}" for item in scheduler_errors if item not in blockers)
    blockers = list(dict.fromkeys(blockers))

    return {
        "schema": SCHEMA,
        "record_id": RECORD_ID,
        "created_at": CREATED_AT,
        "status": status,
        "scope": {"family": FAMILY, "scope_id": SCOPE_ID, "case_id": CASE_ID, "job_id": JOB_ID},
        "diagnostic_only": True,
        "formal": False,
        "formal_eligible": False,
        "T1": False,
        "T2": False,
        "T2_macro": False,
        "T2_path": False,
        "qualification": False,
        "qualification_credit": 0,
        "T2_credit": 0,
        "credit": 0,
        "launch_admitted": False,
        "worker_launch_authorized": False,
        "input_bindings": {
            **{name: dict(all_refs[name]) for name in all_refs},
            "source_hdf5": dict(source_ref),
            "fresh_root_receipt": dict(root_ref),
            "scheduler_host_io_reservation": dict(scheduler_ref),
        },
        "current_code_hashes": {name: {"path": code_refs[name].get("path"), "sha256": code_refs[name].get("sha256"), "bytes": code_refs[name].get("bytes")} for name in CURRENT_CODE},
        "binding_projection": {
            "hashes": hashes,
            "source_identity": source_identity,
            "normalized_launch": normalized_launch,
            "normalized_launch_sha256": _canonical_digest(normalized_launch),
            "fresh_output_namespace": namespace_contract,
            "scheduler_owned_host_io_verified": reservation_valid,
            "resource_request": _expected_resources(job),
        },
        "proposal_observation": proposal_observation,
        "host_io_observation": host_observation,
        "case_sidecar_observation": sidecar_observation,
        "job_runtime_observation": job_runtime_observation,
        "receipt_observations": {
            "fresh_root": {
                "present": root_present,
                "valid": root_valid,
                "pair_id": pair_id,
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
        "validation": {
            "checks": checks,
            "blockers": blockers,
            "input_errors": input_errors,
            "root_receipt_errors": root_errors,
            "scheduler_receipt_errors": scheduler_errors,
            "proposal_error": proposal_error,
            "host_io_projection_error": host_error,
            "case_sidecar_intake_error": sidecar_error,
        },
        "authorization": _authorization(),
        "execution_controls": _execution_controls(),
        "next_safe_action": (
            "Obtain a fresh root-owned namespace authorization and a separate scheduler-owned host-I/O reservation, "
            "each bound to the exact current JSON/source hashes, DEV_07 identity, normalized argv/cwd, and one-use "
            "namespace nonce; then re-run this diagnostic intake. This report is never a launch capability."
        ),
    }


def _validate_ref(value: Any, label: str, errors: list[str]) -> None:
    if not isinstance(value, Mapping):
        errors.append(label)
        return
    if not isinstance(value.get("path"), str) or not value.get("path"):
        errors.append(f"{label}.path")
    if type(value.get("exists")) is not bool:
        errors.append(f"{label}.exists")
    if value.get("exists") is True and (type(value.get("bytes")) is not int or value.get("bytes") < 1):
        errors.append(f"{label}.bytes")
    if value.get("exists") is True and (not isinstance(value.get("sha256"), str) or SHA256.fullmatch(value.get("sha256")) is None):
        errors.append(f"{label}.sha256")


def validate_report(report: Mapping[str, Any]) -> list[str]:
    """Validate serialized report markers without reading campaign state."""

    errors: list[str] = []
    expected_top = {
        "schema", "record_id", "created_at", "status", "scope", "diagnostic_only", "formal", "formal_eligible", "T1", "T2", "T2_macro", "T2_path", "qualification", "qualification_credit", "T2_credit", "credit", "launch_admitted", "worker_launch_authorized", "input_bindings", "current_code_hashes", "binding_projection", "proposal_observation", "host_io_observation", "case_sidecar_observation", "job_runtime_observation", "receipt_observations", "validation", "authorization", "execution_controls", "next_safe_action",
    }
    if not isinstance(report, Mapping) or set(report) != expected_top:
        return ["report.fields"]
    if report.get("schema") != SCHEMA:
        errors.append("schema")
    if report.get("record_id") != RECORD_ID:
        errors.append("record_id")
    if report.get("created_at") != CREATED_AT:
        errors.append("created_at")
    if report.get("status") not in {STATUS_MISSING, STATUS_INVALID, STATUS_BOUND}:
        errors.append("status")
    if report.get("scope") != {"family": FAMILY, "scope_id": SCOPE_ID, "case_id": CASE_ID, "job_id": JOB_ID}:
        errors.append("scope")
    for key, expected in (("diagnostic_only", True), ("formal", False), ("formal_eligible", False), ("T1", False), ("T2", False), ("T2_macro", False), ("T2_path", False), ("qualification", False), ("qualification_credit", 0), ("T2_credit", 0), ("credit", 0), ("launch_admitted", False), ("worker_launch_authorized", False)):
        if report.get(key) != expected:
            errors.append(key)
    bindings = _mapping(report.get("input_bindings"))
    expected_binding_names = set(CURRENT_CODE) | {"proposal", "host_io_projection", "case_sidecar_intake", "collection", "reader", "archive_v1", "archive", "archive_reader_reconciliation", "consistency", "job_spec", "runtime_status", "source_hdf5", "fresh_root_receipt", "scheduler_host_io_reservation"}
    if set(bindings) != expected_binding_names:
        errors.append("input_bindings.fields")
    for name in expected_binding_names - {"source_hdf5", "fresh_root_receipt", "scheduler_host_io_reservation"}:
        _validate_ref(bindings.get(name), f"input_bindings.{name}", errors)
    source = _mapping(bindings.get("source_hdf5"))
    for key in ("hash_recomputed", "opened_as_hdf5", "read"):
        if source.get(key) is not False:
            errors.append(f"input_bindings.source_hdf5.{key}")
    if source.get("exists") is not True or source.get("bytes") != SOURCE_BYTES or source.get("sha256") != SOURCE_SHA256:
        errors.append("input_bindings.source_hdf5.identity")
    projection = _mapping(report.get("binding_projection"))
    hashes = _mapping(projection.get("hashes"))
    if set(hashes) != set(HASH_KEYS):
        errors.append("binding_projection.hashes.fields")
    for key in HASH_KEYS:
        if hashes.get(key) is not None and (not isinstance(hashes.get(key), str) or SHA256.fullmatch(hashes.get(key)) is None):
            errors.append(f"binding_projection.hashes.{key}")
    if not isinstance(projection.get("normalized_launch_sha256"), str) or SHA256.fullmatch(projection.get("normalized_launch_sha256")) is None:
        errors.append("binding_projection.normalized_launch_sha256")
    if not isinstance(projection.get("fresh_output_namespace"), Mapping):
        errors.append("binding_projection.fresh_output_namespace")
    if type(projection.get("scheduler_owned_host_io_verified")) is not bool:
        errors.append("binding_projection.scheduler_owned_host_io_verified")
    validation = _mapping(report.get("validation"))
    if set(validation) != {"checks", "blockers", "input_errors", "root_receipt_errors", "scheduler_receipt_errors", "proposal_error", "host_io_projection_error", "case_sidecar_intake_error"}:
        errors.append("validation.fields")
    checks = _mapping(validation.get("checks"))
    if set(checks) != set(CHECK_NAMES) or any(type(checks.get(name)) is not bool for name in CHECK_NAMES):
        errors.append("validation.checks")
    for key in ("blockers", "input_errors", "root_receipt_errors", "scheduler_receipt_errors"):
        if not isinstance(validation.get(key), list) or any(not isinstance(item, str) for item in validation.get(key, [])):
            errors.append(f"validation.{key}")
    if report.get("status") == STATUS_BOUND:
        if checks.get("intake_contract_valid") is not True or validation.get("blockers") != []:
            errors.append("status.bound_contract")
    elif checks.get("intake_contract_valid") is not False or not validation.get("blockers"):
        errors.append("status.blocked_contract")
    if dict(_mapping(report.get("authorization"))) != _authorization():
        errors.append("authorization.fail_closed_boundary")
    if dict(_mapping(report.get("execution_controls"))) != _execution_controls():
        errors.append("execution_controls.fail_closed_boundary")
    observations = _mapping(report.get("receipt_observations"))
    if set(observations) != {"fresh_root", "scheduler"}:
        errors.append("receipt_observations.fields")
    return errors


def write_report(value: Mapping[str, Any], output: str | Path) -> Path:
    errors = validate_report(value)
    if errors:
        raise ValueError("refusing to write invalid F4 intake report: " + ", ".join(errors))
    path = Path(output).resolve()
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return path


def render_zh_cn(value: Mapping[str, Any]) -> str:
    checks = _mapping(_mapping(value.get("validation")).get("checks"))
    blockers = _mapping(value.get("validation")).get("blockers", [])
    source = _mapping(value.get("binding_projection")).get("source_identity", {})
    lines = [
        "# F4 Tallwall120 DEV_07 material root/scheduler admission intake V1",
        "",
        f"- 状态：`{value.get('status')}`",
        f"- scope/case：`{SCOPE_ID}` / `{CASE_ID}`",
        f"- proposal/host/sidecar：`{checks.get('proposal_contract_valid')}` / `{checks.get('host_io_projection_contract_valid')}` / `{checks.get('case_sidecar_intake_contract_valid')}`",
        f"- source identity：`{checks.get('source_identity_contract_valid')}`；collection path exact=`{_mapping(source.get('collection')).get('path_exact')}`；reader SHA exact=`{_mapping(source.get('reader')).get('manifest_sha_exact')}`",
        f"- current material/collector/runtime hashes：`{checks.get('current_code_hashes_valid')}`",
        f"- normalized argv/cwd：`{checks.get('normalized_argv_cwd_valid')}`；fresh namespace：`{checks.get('fresh_output_namespace_valid')}`",
        f"- root receipt：present=`{checks.get('future_root_receipt_present')}` valid=`{checks.get('future_root_receipt_valid')}`",
        f"- scheduler receipt：present=`{checks.get('future_scheduler_receipt_present')}` valid=`{checks.get('future_scheduler_receipt_valid')}`",
        "",
        "## Fail-closed 边界",
        "",
        "本 intake 只读取 bounded strict JSON 与小型源码文件。DEV_07 trajectory HDF5 只做 lstat 元数据检查，未打开、未读取、未重哈希；未启动/停止 solver、worker、native、GPU 或 queue。",
        "",
        f"`diagnostic_only={value.get('diagnostic_only')}`、`formal={value.get('formal')}`、`T1={value.get('T1')}`、`T2={value.get('T2')}`、`credit={value.get('credit')}`。",
        "",
        "## 阻塞原因",
        "",
    ]
    lines.extend(f"- `{item}`" for item in blockers)
    lines.extend(["", "未写 registry、ledger、denominator、gate 或 PLAN；完整 receipt pair 也不会被本 intake 晋升为 launch capability。", ""])
    return "\n".join(lines)


def write_zh_cn(value: Mapping[str, Any], output: str | Path) -> Path:
    errors = validate_report(value)
    if errors:
        raise ValueError("refusing to write invalid F4 Chinese report: " + ", ".join(errors))
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
    parser.add_argument("--host-io-projection", type=Path, default=None)
    parser.add_argument("--case-sidecar-intake", type=Path, default=None)
    parser.add_argument("--archive-reader-reconciliation", type=Path, default=None)
    parser.add_argument("--source-archive-v1", type=Path, default=None)
    parser.add_argument("--root-receipt", type=Path, default=None)
    parser.add_argument("--scheduler-receipt", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--zh-cn-output", type=Path, default=DEFAULT_ZH_REPORT)
    args = parser.parse_args(argv)
    report = build_report(args.root, proposal_path=args.proposal, host_io_projection_path=args.host_io_projection, case_sidecar_intake_path=args.case_sidecar_intake, archive_reader_reconciliation_path=args.archive_reader_reconciliation, source_archive_v1_path=args.source_archive_v1, root_receipt_path=args.root_receipt, scheduler_receipt_path=args.scheduler_receipt)
    write_report(report, args.output)
    write_zh_cn(report, args.zh_cn_output)
    print(json.dumps({"status": report["status"], "report": str(args.output)}, sort_keys=True))
    return 0 if report["status"] == STATUS_BOUND else 2


if __name__ == "__main__":
    raise SystemExit(main())
