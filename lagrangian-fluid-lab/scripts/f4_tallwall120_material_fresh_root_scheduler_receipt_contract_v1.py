#!/usr/bin/env python3
"""Bounded, non-authorizing F4 Tallwall120 receipt-pair contract.

This contract complements the existing F4 root/scheduler intake.  It does
not issue, write, consume, or promote either receipt.  It reads bounded
strict JSON only and, when a candidate pair is supplied, checks the pair's
one-use nonce, file/path ownership and inode identity, normalized argv and
input hashes, capability closure, and a canonical pair commitment.

The default paths are the future receipt paths already named by the F4 v1
intake.  They are intentionally absent in the checked-in report.  A complete
pair remains diagnostic evidence only: no native, solver, worker, GPU, queue,
registry, ledger, denominator, gate, completion, or PLAN action is performed.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import pwd
import re
import stat
import sys
from typing import Any, Mapping, Sequence


LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts.core_strict_json import (  # noqa: E402
    read_bounded_raw_json,
    strict_json_object,
)


SCHEMA = "core.material.f4.tallwall120.fresh_root_scheduler_receipt_contract.v1"
RECORD_ID = "f4-tallwall120-material-fresh-root-scheduler-receipt-contract-v1"
CREATED_AT = "2026-09-29"
OBSERVED_AT = "2026-09-29T00:00:00Z"

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
ANCHOR_REPORT = Path(
    "reports/F4-TALLWALL120-MATERIAL-ROOT-SCHEDULER-INTAKE-V1-2026-09-28.json"
)
DEFAULT_REPORT = Path(
    "reports/F4-TALLWALL120-MATERIAL-FRESH-ROOT-SCHEDULER-RECEIPT-CONTRACT-V1-2026-09-29.json"
)

ROOT_RECEIPT_SCHEMA = (
    "core.material.f4.tallwall120.fresh_root_admission_receipt.v2-contract"
)
SCHEDULER_RECEIPT_SCHEMA = (
    "core.material.f4.tallwall120.scheduler_host_io_reservation.v2-contract"
)

STATUS_ANCHOR_BLOCKED = "blocked_anchor_contract_invalid"
STATUS_MISSING = "blocked_missing_fresh_root_scheduler_receipts"
STATUS_INVALID = "blocked_invalid_fresh_root_scheduler_receipts"
STATUS_BOUND = "fresh_root_scheduler_receipts_structurally_bound_non_authorizing"

MAX_JSON_BYTES = 1 * 1024 * 1024
SHA256 = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
NONCE = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z", re.ASCII)
O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)

ANCHOR_FIELDS = {
    "scope",
    "source",
    "input_hashes",
    "normalized_launch",
    "normalized_launch_sha256",
    "output_namespace",
    "resource_request",
    "capability",
}
BINDING_FIELDS = ANCHOR_FIELDS | {"namespace_nonce"}
PATH_IDENTITY_FIELDS = {
    "path",
    "device",
    "inode",
    "owner_uid",
    "owner_name",
    "nlink",
    "mode",
    "kind",
}
RECEIPT_IDENTITY_FIELDS = PATH_IDENTITY_FIELDS
ROOT_FIELDS = {
    "schema",
    "receipt_id",
    "kind",
    "status",
    "synthetic",
    "pair_id",
    "nonce",
    "binding_sha256",
    "pair_commitment_sha256",
    "binding",
    "receipt_identity",
    "fresh_root",
    "capability",
    "counterparty",
    "side_effects",
}
SCHEDULER_FIELDS = {
    "schema",
    "receipt_id",
    "kind",
    "status",
    "synthetic",
    "pair_id",
    "nonce",
    "binding_sha256",
    "pair_commitment_sha256",
    "binding",
    "receipt_identity",
    "host_io_reservation",
    "capability",
    "counterparty",
    "side_effects",
}
FRESH_ROOT_FIELDS = {
    "namespace",
    "namespace_path",
    "path_identity",
    "fresh",
    "reused",
    "overwrite_allowed",
    "resume_allowed",
    "single_use",
    "consumed",
}
HOST_IO_FIELDS = {
    "reservation_id",
    "reservation_path",
    "path_identity",
    "owner_role",
    "reservation_active",
    "scheduler_owned_host_io_verified",
    "resource_request",
    "io_weight",
    "owned_io_weight",
    "io_capacity",
    "filesystem",
    "snapshot_id",
    "single_use",
    "consumed",
}
CAPABILITY_FIELDS = {
    "role",
    "fresh_namespace_observed",
    "root_owned_verified",
    "scheduler_owned_host_io_verified",
    "single_use",
    "consumed",
    "launch_authorized",
    "worker_launch_authorized",
    "solver_authorized",
    "native_authorized",
    "gpu_authorized",
    "queue_authorized",
    "formal_eligible",
    "credit",
}
COUNTERPARTY_FIELDS = {
    "path",
    "pair_id",
    "nonce",
    "binding_sha256",
    "receipt_identity",
    "pair_commitment_sha256",
}
SIDE_EFFECT_FIELDS = {
    "worker_started",
    "solver_started",
    "native_started",
    "gpu_started",
    "queue_started",
    "registry_mutations",
    "ledger_mutations",
    "denominator_mutations",
    "gate_mutations",
    "completion_mutations",
    "plan_mutations",
}

CAPABILITY = {
    "role": "non_authorizing_diagnostic_only",
    "fresh_namespace_observed": False,
    "root_owned_verified": False,
    "scheduler_owned_host_io_verified": False,
    "single_use": True,
    "consumed": False,
    "launch_authorized": False,
    "worker_launch_authorized": False,
    "solver_authorized": False,
    "native_authorized": False,
    "gpu_authorized": False,
    "queue_authorized": False,
    "formal_eligible": False,
    "credit": 0,
}


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON object key: {key}")
        value[key] = item
    return value


def _absolute(path: str | Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _display(root: Path, path: Path) -> str:
    absolute = _absolute(path)
    try:
        return absolute.relative_to(_absolute(root)).as_posix()
    except ValueError:
        return absolute.as_posix()


def _resolve(root: Path, value: str | Path) -> Path:
    candidate = Path(value)
    return _absolute(candidate if candidate.is_absolute() else root / candidate)


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
            raise ValueError(f"{label} path inspection failed") from error
        if stat.S_ISLNK(info.st_mode):
            raise ValueError(f"{label} path contains a symlink")


def _owner_name(uid: int) -> str:
    try:
        return pwd.getpwuid(uid).pw_name
    except (KeyError, OverflowError):
        return str(uid)


def _kind(mode: int) -> str:
    if stat.S_ISREG(mode):
        return "file"
    if stat.S_ISDIR(mode):
        return "directory"
    if stat.S_ISLNK(mode):
        return "symlink"
    return "other"


def _identity_from_stat(path: Path, info: os.stat_result) -> dict[str, Any]:
    return {
        "path": str(_absolute(path)),
        "device": info.st_dev,
        "inode": info.st_ino,
        "owner_uid": info.st_uid,
        "owner_name": _owner_name(info.st_uid),
        "nlink": info.st_nlink,
        "mode": info.st_mode,
        "kind": _kind(info.st_mode),
    }


def _lstat_identity(path: Path, *, label: str, require_kind: set[str] | None = None) -> tuple[dict[str, Any] | None, str | None]:
    try:
        _assert_no_symlink_components(path, label)
        info = os.lstat(path)
    except FileNotFoundError:
        return None, "missing"
    except OSError as error:
        return None, type(error).__name__
    identity = _identity_from_stat(path, info)
    if stat.S_ISLNK(info.st_mode):
        return identity, "symlink"
    if require_kind is not None and identity["kind"] not in require_kind:
        return identity, "wrong_kind"
    return identity, None


def _read_json(path: Path, *, root: Path, role: str) -> tuple[dict[str, Any], dict[str, Any], str | None]:
    reference: dict[str, Any] = {
        "role": role,
        "path": _display(root, path),
        "absolute_path": str(_absolute(path)),
        "exists": False,
        "bounded": True,
        "content_read": False,
        "sha256": None,
        "bytes": None,
        "identity": None,
        "error": None,
    }
    try:
        _assert_no_symlink_components(path, role)
        raw = read_bounded_raw_json(path, max_bytes=MAX_JSON_BYTES, label=role)
        payload = strict_json_object(raw, label=role, max_bytes=MAX_JSON_BYTES)
        info = os.lstat(path)
    except FileNotFoundError:
        reference["error"] = "missing"
        return {}, reference, "missing"
    except (OSError, ValueError, UnicodeError, json.JSONDecodeError) as error:
        reference["error"] = type(error).__name__
        return {}, reference, type(error).__name__
    reference.update(
        {
            "exists": True,
            "content_read": True,
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "identity": _identity_from_stat(path, info),
        }
    )
    return payload, reference, None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sha(value: Any) -> bool:
    return isinstance(value, str) and SHA256.fullmatch(value) is not None


def _nonce(value: Any) -> bool:
    return isinstance(value, str) and NONCE.fullmatch(value) is not None


def _safe_id(value: Any) -> bool:
    return isinstance(value, str) and SAFE_ID.fullmatch(value) is not None


def _bools_closed(value: Mapping[str, Any], label: str, errors: list[str]) -> bool:
    start = len(errors)
    if set(value) != SIDE_EFFECT_FIELDS:
        errors.append(f"{label}.fields")
    for key in ("worker_started", "solver_started", "native_started", "gpu_started", "queue_started"):
        if value.get(key) is not False:
            errors.append(f"{label}.{key}")
    for key in (
        "registry_mutations",
        "ledger_mutations",
        "denominator_mutations",
        "gate_mutations",
        "completion_mutations",
        "plan_mutations",
    ):
        if value.get(key) != 0:
            errors.append(f"{label}.{key}")
    return len(errors) == start


def _capability_closed(value: Any, *, role: str, root_observed: bool, scheduler_observed: bool, errors: list[str]) -> bool:
    start = len(errors)
    if not isinstance(value, Mapping) or set(value) != CAPABILITY_FIELDS:
        errors.append("capability.fields")
        return False
    expected = dict(CAPABILITY)
    expected["role"] = role
    expected["fresh_namespace_observed"] = root_observed
    expected["root_owned_verified"] = root_observed
    expected["scheduler_owned_host_io_verified"] = scheduler_observed
    for key, expected_value in expected.items():
        if value.get(key) != expected_value:
            errors.append(f"capability.{key}")
    return len(errors) == start


def _validate_identity(
    value: Any,
    *,
    actual: Mapping[str, Any] | None,
    label: str,
    expected_path: Path | None,
    expected_kind: set[str] | None,
    owner_uid: int | None,
    owner_name: str | None,
    errors: list[str],
) -> bool:
    start = len(errors)
    if not isinstance(value, Mapping) or set(value) != PATH_IDENTITY_FIELDS:
        errors.append(f"{label}.fields")
        return False
    if not isinstance(value.get("path"), str) or not os.path.isabs(value["path"]):
        errors.append(f"{label}.path")
    for key in ("device", "inode", "owner_uid", "nlink", "mode"):
        if type(value.get(key)) is not int or value.get(key) < 0:
            errors.append(f"{label}.{key}")
    if not isinstance(value.get("owner_name"), str) or not value.get("owner_name"):
        errors.append(f"{label}.owner_name")
    if value.get("kind") not in {"file", "directory"}:
        errors.append(f"{label}.kind")
    if expected_path is not None and value.get("path") != str(_absolute(expected_path)):
        errors.append(f"{label}.expected_path")
    if expected_kind is not None and value.get("kind") not in expected_kind:
        errors.append(f"{label}.expected_kind")
    if owner_uid is not None and value.get("owner_uid") != owner_uid:
        errors.append(f"{label}.owner_uid_expected")
    if owner_name is not None and value.get("owner_name") != owner_name:
        errors.append(f"{label}.owner_name_expected")
    if actual is None:
        errors.append(f"{label}.actual_missing")
    elif dict(value) != dict(actual):
        errors.append(f"{label}.actual_mismatch")
    return len(errors) == start


def _validate_receipt_identity(
    value: Any,
    *,
    actual: Mapping[str, Any] | None,
    label: str,
    errors: list[str],
) -> bool:
    start = len(errors)
    valid = _validate_identity(
        value,
        actual=actual,
        label=label,
        expected_path=None,
        expected_kind={"file"},
        owner_uid=None,
        owner_name=None,
        errors=errors,
    )
    if isinstance(value, Mapping) and value.get("nlink") != 1:
        errors.append(f"{label}.nlink_single_link")
    return valid and len(errors) == start


def _anchor_binding(anchor: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    if set(anchor) != ANCHOR_FIELDS:
        errors.append("anchor.binding.fields")
    scope = _mapping(anchor.get("scope"))
    expected_scope = {
        "family": FAMILY,
        "scope_id": SCOPE_ID,
        "case_id": CASE_ID,
        "job_id": JOB_ID,
    }
    if dict(scope) != expected_scope:
        errors.append("anchor.binding.scope")
    source = _mapping(anchor.get("source"))
    expected_source = {
        "path": SOURCE_HDF5,
        "sha256": SOURCE_SHA256,
        "bytes": SOURCE_BYTES,
    }
    if dict(source) != expected_source:
        errors.append("anchor.binding.source")
    input_hashes = anchor.get("input_hashes")
    if not isinstance(input_hashes, Mapping) or not input_hashes or any(not _sha(v) for v in input_hashes.values()):
        errors.append("anchor.binding.input_hashes")
    normalized = _mapping(anchor.get("normalized_launch"))
    if not normalized or anchor.get("normalized_launch_sha256") != canonical_digest(normalized):
        errors.append("anchor.binding.normalized_launch")
    output = _mapping(anchor.get("output_namespace"))
    expected_output = {
        "namespace": DEFAULT_OUTPUT_NAMESPACE,
        "namespace_path_exists": False,
        "overwrite_allowed": False,
        "resume_allowed": False,
        "historical_trace_reuse": False,
    }
    if dict(output) != expected_output:
        errors.append("anchor.binding.output_namespace")
    resources = _mapping(anchor.get("resource_request"))
    if dict(resources) != {"cpu_cores": 2, "ram_mib": 24576, "gpu_peak_mib": 6144, "io_weight": 2}:
        errors.append("anchor.binding.resource_request")
    if dict(anchor.get("capability", {})) != CAPABILITY:
        errors.append("anchor.binding.capability")
    return {
        "scope": dict(scope),
        "source": dict(source),
        "input_hashes": dict(input_hashes) if isinstance(input_hashes, Mapping) else {},
        "normalized_launch": deepcopy(dict(normalized)),
        "normalized_launch_sha256": anchor.get("normalized_launch_sha256"),
        "output_namespace": dict(output),
        "resource_request": dict(resources),
        "capability": deepcopy(dict(anchor.get("capability", {}))),
    }, errors


def _load_anchor(root: Path, path: Path) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    anchor, reference, error = _read_json(path, root=root, role="F4 v1 root/scheduler anchor report")
    errors: list[str] = []
    if error:
        errors.append(f"anchor.read:{error}")
        return {}, reference, errors
    if anchor.get("schema") != "core.material.f4.tallwall120.root_scheduler_intake.v1":
        errors.append("anchor.schema")
    if anchor.get("record_id") != "f4-tallwall120-material-root-scheduler-intake-v1":
        errors.append("anchor.record_id")
    if anchor.get("status") not in {"blocked_missing_fresh_root_scheduler_receipts", "blocked_invalid_fresh_root_scheduler_receipts"}:
        errors.append("anchor.status")
    if anchor.get("diagnostic_only") is not True or anchor.get("formal") is not False or anchor.get("formal_eligible") is not False:
        errors.append("anchor.authorization")
    if any(anchor.get(key) is not False for key in ("T1", "T2", "T2_macro", "T2_path")) or anchor.get("credit") != 0:
        errors.append("anchor.qualification")
    if anchor.get("scope") != {
        "family": FAMILY,
        "scope_id": SCOPE_ID,
        "case_id": CASE_ID,
        "job_id": JOB_ID,
    }:
        errors.append("anchor.scope")
    authorization = _mapping(anchor.get("authorization"))
    for key in ("launch_admitted", "worker_launch_authorized", "root_authorization_intake_bound", "scheduler_host_io_reservation_bound", "scheduler_owned_io_verified"):
        if authorization.get(key) is not False:
            errors.append(f"anchor.authorization.{key}")
    projection = _mapping(anchor.get("binding_projection"))
    source_identity = _mapping(projection.get("source_identity"))
    proposal_source = _mapping(source_identity.get("proposal_source"))
    normalized = _mapping(projection.get("normalized_launch"))
    output = _mapping(projection.get("fresh_output_namespace"))
    anchor_value = {
        "scope": {
            "family": FAMILY,
            "scope_id": SCOPE_ID,
            "case_id": CASE_ID,
            "job_id": JOB_ID,
        },
        "source": {
            "path": proposal_source.get("path"),
            "sha256": proposal_source.get("sha256"),
            "bytes": proposal_source.get("bytes"),
        },
        "input_hashes": projection.get("hashes"),
        "normalized_launch": dict(normalized),
        "normalized_launch_sha256": projection.get("normalized_launch_sha256"),
        "output_namespace": {
            "namespace": output.get("namespace"),
            "namespace_path_exists": output.get("namespace_path_exists"),
            "overwrite_allowed": output.get("overwrite_allowed"),
            "resume_allowed": output.get("resume_allowed"),
            "historical_trace_reuse": output.get("historical_trace_reuse"),
        },
        "resource_request": projection.get("resource_request"),
        "capability": dict(CAPABILITY),
    }
    binding, binding_errors = _anchor_binding(anchor_value)
    errors.extend(binding_errors)
    return binding, reference, errors


def _binding_for_nonce(anchor: Mapping[str, Any], nonce: str) -> dict[str, Any]:
    binding = deepcopy(dict(anchor))
    binding["namespace_nonce"] = nonce
    return binding


def _side_effects() -> dict[str, Any]:
    return {
        "worker_started": False,
        "solver_started": False,
        "native_started": False,
        "gpu_started": False,
        "queue_started": False,
        "registry_mutations": 0,
        "ledger_mutations": 0,
        "denominator_mutations": 0,
        "gate_mutations": 0,
        "completion_mutations": 0,
        "plan_mutations": 0,
    }


def _validate_binding(value: Any, expected: Mapping[str, Any], label: str, errors: list[str]) -> tuple[bool, dict[str, Any]]:
    start = len(errors)
    if not isinstance(value, Mapping) or set(value) != BINDING_FIELDS:
        errors.append(f"{label}.fields")
        return False, {}
    if dict(value) != dict(expected):
        errors.append(f"{label}.value")
    if not _nonce(value.get("namespace_nonce")):
        errors.append(f"{label}.namespace_nonce")
    return len(errors) == start, dict(value)


def _validate_counterparty(value: Any, *, expected_path: Path, expected_identity: Mapping[str, Any] | None, pair_id: Any, nonce: Any, binding_sha256: Any, pair_commitment: Any, label: str, errors: list[str]) -> bool:
    start = len(errors)
    if not isinstance(value, Mapping) or set(value) != COUNTERPARTY_FIELDS:
        errors.append(f"{label}.fields")
        return False
    checks = {
        "path": value.get("path") == str(_absolute(expected_path)),
        "pair_id": value.get("pair_id") == pair_id,
        "nonce": value.get("nonce") == nonce,
        "binding_sha256": value.get("binding_sha256") == binding_sha256,
        "receipt_identity": expected_identity is not None and value.get("receipt_identity") == dict(expected_identity),
        "pair_commitment_sha256": value.get("pair_commitment_sha256") == pair_commitment,
    }
    for name, passed in checks.items():
        if not passed:
            errors.append(f"{label}.{name}")
    return len(errors) == start


def _validate_root(
    value: Mapping[str, Any] | None,
    *,
    root: Path,
    path: Path,
    actual_identity: Mapping[str, Any] | None,
    anchor: Mapping[str, Any],
    scheduler_path: Path,
    scheduler_identity: Mapping[str, Any] | None,
    scheduler_binding_sha256: Any,
    errors: list[str],
) -> dict[str, Any]:
    start = len(errors)
    if not isinstance(value, Mapping):
        errors.append("root.missing_or_not_object")
        return {"valid": False, "binding": {}, "identity": actual_identity}
    if set(value) != ROOT_FIELDS:
        errors.append("root.fields")
    for key, expected in {
        "schema": ROOT_RECEIPT_SCHEMA,
        "receipt_id": "f4-tallwall120-material-fresh-root-receipt-contract-v1",
        "kind": "fresh_root",
        "status": "fresh_root_observed",
        "synthetic": False,
    }.items():
        if value.get(key) != expected:
            errors.append(f"root.{key}")
    pair_id = value.get("pair_id")
    nonce = value.get("nonce")
    if not _safe_id(pair_id):
        errors.append("root.pair_id")
    if not _nonce(nonce):
        errors.append("root.nonce")
    expected_binding = _binding_for_nonce(anchor, nonce) if _nonce(nonce) else {}
    binding_ok, binding = _validate_binding(value.get("binding"), expected_binding, "root.binding", errors)
    if value.get("binding_sha256") != canonical_digest(binding) or not _sha(value.get("binding_sha256")):
        errors.append("root.binding_sha256")
    receipt_identity_ok = _validate_receipt_identity(value.get("receipt_identity"), actual=actual_identity, label="root.receipt_identity", errors=errors)
    fresh = value.get("fresh_root")
    namespace_path = _resolve(root, DEFAULT_OUTPUT_NAMESPACE)
    if not isinstance(fresh, Mapping) or set(fresh) != FRESH_ROOT_FIELDS:
        errors.append("root.fresh_root.fields")
    else:
        for key, expected in {
            "namespace": DEFAULT_OUTPUT_NAMESPACE,
            "namespace_path": str(namespace_path),
            "fresh": True,
            "reused": False,
            "overwrite_allowed": False,
            "resume_allowed": False,
            "single_use": True,
            "consumed": False,
        }.items():
            if fresh.get(key) != expected:
                errors.append(f"root.fresh_root.{key}")
        namespace_identity, namespace_error = _lstat_identity(namespace_path, label="fresh root namespace", require_kind={"directory"})
        if namespace_error:
            errors.append(f"root.fresh_root.namespace_path.{namespace_error}")
        _validate_identity(
            fresh.get("path_identity"),
            actual=namespace_identity,
            label="root.fresh_root.path_identity",
            expected_path=namespace_path,
            expected_kind={"directory"},
            owner_uid=0,
            owner_name="root",
            errors=errors,
        )
    capability_ok = _capability_closed(value.get("capability"), role="fresh_root", root_observed=True, scheduler_observed=False, errors=errors)
    _validate_counterparty(
        value.get("counterparty"),
        expected_path=scheduler_path,
        expected_identity=scheduler_identity,
        pair_id=pair_id,
        nonce=nonce,
        binding_sha256=scheduler_binding_sha256,
        pair_commitment=value.get("pair_commitment_sha256"),
        label="root.counterparty",
        errors=errors,
    )
    _bools_closed(_mapping(value.get("side_effects")), "root.side_effects", errors)
    return {
        "valid": len(errors) == start,
        "binding": binding,
        "binding_sha256": value.get("binding_sha256"),
        "pair_id": pair_id,
        "nonce": nonce,
        "identity": dict(actual_identity or {}),
        "capability_closed": capability_ok,
        "receipt_identity_valid": receipt_identity_ok,
        "fresh_root": dict(_mapping(fresh)),
        "path_identity": dict(_mapping(_mapping(fresh).get("path_identity"))),
    }


def _finite_nonnegative(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)) and float(value) >= 0


def _validate_scheduler(
    value: Mapping[str, Any] | None,
    *,
    root: Path,
    path: Path,
    actual_identity: Mapping[str, Any] | None,
    anchor: Mapping[str, Any],
    root_path: Path,
    root_identity: Mapping[str, Any] | None,
    root_binding_sha256: Any,
    errors: list[str],
) -> dict[str, Any]:
    start = len(errors)
    if not isinstance(value, Mapping):
        errors.append("scheduler.missing_or_not_object")
        return {"valid": False, "binding": {}, "identity": actual_identity}
    if set(value) != SCHEDULER_FIELDS:
        errors.append("scheduler.fields")
    for key, expected in {
        "schema": SCHEDULER_RECEIPT_SCHEMA,
        "receipt_id": "f4-tallwall120-material-scheduler-receipt-contract-v1",
        "kind": "scheduler_host_io_reservation",
        "status": "scheduler_host_io_reservation_observed",
        "synthetic": False,
    }.items():
        if value.get(key) != expected:
            errors.append(f"scheduler.{key}")
    pair_id = value.get("pair_id")
    nonce = value.get("nonce")
    if not _safe_id(pair_id):
        errors.append("scheduler.pair_id")
    if not _nonce(nonce):
        errors.append("scheduler.nonce")
    expected_binding = _binding_for_nonce(anchor, nonce) if _nonce(nonce) else {}
    _, binding = _validate_binding(value.get("binding"), expected_binding, "scheduler.binding", errors)
    if value.get("binding_sha256") != canonical_digest(binding) or not _sha(value.get("binding_sha256")):
        errors.append("scheduler.binding_sha256")
    receipt_identity_ok = _validate_receipt_identity(value.get("receipt_identity"), actual=actual_identity, label="scheduler.receipt_identity", errors=errors)
    reservation = value.get("host_io_reservation")
    expected_resources = dict(_mapping(anchor.get("resource_request")))
    if not isinstance(reservation, Mapping) or set(reservation) != HOST_IO_FIELDS:
        errors.append("scheduler.host_io_reservation.fields")
    else:
        if not _safe_id(reservation.get("reservation_id")):
            errors.append("scheduler.host_io_reservation.reservation_id")
        reservation_path = Path(str(reservation.get("reservation_path"))) if isinstance(reservation.get("reservation_path"), str) else Path(".")
        if not reservation_path.is_absolute() or _absolute(reservation_path).is_relative_to(_absolute(root)) is False:
            errors.append("scheduler.host_io_reservation.reservation_path")
        if reservation.get("owner_role") != "scheduler":
            errors.append("scheduler.host_io_reservation.owner_role")
        for key, expected in {
            "reservation_active": True,
            "scheduler_owned_host_io_verified": True,
            "io_weight": expected_resources.get("io_weight"),
            "single_use": True,
            "consumed": False,
        }.items():
            if reservation.get(key) != expected:
                errors.append(f"scheduler.host_io_reservation.{key}")
        if reservation.get("resource_request") != expected_resources:
            errors.append("scheduler.host_io_reservation.resource_request")
        if not _finite_nonnegative(reservation.get("owned_io_weight")) or not _finite_nonnegative(reservation.get("io_capacity")):
            errors.append("scheduler.host_io_reservation.capacity")
        elif float(reservation["owned_io_weight"]) < float(expected_resources.get("io_weight") or 0) or float(reservation["io_capacity"]) < float(reservation["owned_io_weight"]):
            errors.append("scheduler.host_io_reservation.capacity_headroom")
        for key in ("filesystem", "snapshot_id"):
            if not isinstance(reservation.get(key), str) or not reservation.get(key):
                errors.append(f"scheduler.host_io_reservation.{key}")
        reservation_identity, reservation_error = _lstat_identity(reservation_path, label="scheduler reservation", require_kind={"file", "directory"})
        if reservation_error:
            errors.append(f"scheduler.host_io_reservation.path.{reservation_error}")
        _validate_identity(
            reservation.get("path_identity"),
            actual=reservation_identity,
            label="scheduler.host_io_reservation.path_identity",
            expected_path=reservation_path,
            expected_kind={"file", "directory"},
            owner_uid=None,
            owner_name=None,
            errors=errors,
        )
    _capability_closed(value.get("capability"), role="scheduler", root_observed=False, scheduler_observed=True, errors=errors)
    _validate_counterparty(
        value.get("counterparty"),
        expected_path=root_path,
        expected_identity=root_identity,
        pair_id=pair_id,
        nonce=nonce,
        binding_sha256=root_binding_sha256,
        pair_commitment=value.get("pair_commitment_sha256"),
        label="scheduler.counterparty",
        errors=errors,
    )
    _bools_closed(_mapping(value.get("side_effects")), "scheduler.side_effects", errors)
    return {
        "valid": len(errors) == start,
        "binding": binding,
        "binding_sha256": value.get("binding_sha256"),
        "pair_id": pair_id,
        "nonce": nonce,
        "identity": dict(actual_identity or {}),
        "receipt_identity_valid": receipt_identity_ok,
        "host_io_reservation": dict(_mapping(reservation)),
        "path_identity": dict(_mapping(_mapping(reservation).get("path_identity"))),
    }


def _pair_commitment(root_projection: Mapping[str, Any], scheduler_projection: Mapping[str, Any]) -> str:
    root_path_identity = _mapping(root_projection.get("fresh_root")).get("path_identity", {})
    scheduler_path_identity = _mapping(scheduler_projection.get("host_io_reservation")).get("path_identity", {})
    payload = {
        "pair_id": root_projection.get("pair_id"),
        "nonce": root_projection.get("nonce"),
        "root_binding_sha256": root_projection.get("binding_sha256"),
        "scheduler_binding_sha256": scheduler_projection.get("binding_sha256"),
        "root_receipt_identity": root_projection.get("identity", {}),
        "scheduler_receipt_identity": scheduler_projection.get("identity", {}),
        "root_namespace_identity": root_path_identity,
        "scheduler_reservation_identity": scheduler_path_identity,
        "argv_sha256": _mapping(root_projection.get("binding", {})).get("normalized_launch_sha256"),
        "source_sha256": _mapping(_mapping(root_projection.get("binding", {})).get("source")).get("sha256"),
        "capability_sha256": canonical_digest(CAPABILITY),
    }
    return canonical_digest(payload)


def _authorization() -> dict[str, Any]:
    return {
        "diagnostic_only": True,
        "non_authorizing_contract": True,
        "formal": False,
        "formal_eligible": False,
        "T1": False,
        "T2": False,
        "launch_allowed": False,
        "worker_launch_authorized": False,
        "native_authorized": False,
        "solver_authorized": False,
        "gpu_authorized": False,
        "queue_authorized": False,
        "qualification_credit": 0,
        "credit": 0,
    }


def _execution_controls() -> dict[str, Any]:
    return {
        "bounded_json_only": True,
        "receipt_files_written": False,
        "fresh_namespace_created": False,
        "scheduler_reservation_created": False,
        "native_started": False,
        "solver_started": False,
        "worker_started": False,
        "gpu_started": False,
        "queue_started": False,
        "registry_mutations": 0,
        "ledger_mutations": 0,
        "denominator_mutations": 0,
        "gate_mutations": 0,
        "completion_mutations": 0,
        "plan_mutations": 0,
    }


def build_report(
    root: str | Path = LAB_ROOT,
    *,
    anchor_path: str | Path | None = None,
    root_receipt_path: str | Path | None = None,
    scheduler_receipt_path: str | Path | None = None,
) -> dict[str, Any]:
    root = _absolute(root)
    anchor_file = _resolve(root, anchor_path or ANCHOR_REPORT)
    root_file = _resolve(root, root_receipt_path or ROOT_RECEIPT)
    scheduler_file = _resolve(root, scheduler_receipt_path or SCHEDULER_RECEIPT)
    anchor, anchor_ref, anchor_errors = _load_anchor(root, anchor_file)
    root_receipt, root_ref, root_error = _read_json(root_file, root=root, role="F4 fresh-root receipt candidate")
    scheduler_receipt, scheduler_ref, scheduler_error = _read_json(scheduler_file, root=root, role="F4 scheduler host-I/O receipt candidate")
    anchor_valid = not anchor_errors
    binding_anchor = anchor if anchor_valid else {}
    root_identity = root_ref.get("identity") if root_ref.get("exists") else None
    scheduler_identity = scheduler_ref.get("identity") if scheduler_ref.get("exists") else None
    errors: list[str] = list(anchor_errors)
    root_projection = _validate_root(
        root_receipt if root_ref.get("exists") else None,
        root=root,
        path=root_file,
        actual_identity=root_identity,
        anchor=binding_anchor,
        scheduler_path=scheduler_file,
        scheduler_identity=scheduler_identity,
        scheduler_binding_sha256=_mapping(scheduler_receipt).get("binding_sha256"),
        errors=errors,
    )
    scheduler_projection = _validate_scheduler(
        scheduler_receipt if scheduler_ref.get("exists") else None,
        root=root,
        path=scheduler_file,
        actual_identity=scheduler_identity,
        anchor=binding_anchor,
        root_path=root_file,
        root_identity=root_identity,
        root_binding_sha256=_mapping(root_receipt).get("binding_sha256"),
        errors=errors,
    )
    pair_checks = {
        "pair_id_equal": bool(root_projection.get("pair_id") and root_projection.get("pair_id") == scheduler_projection.get("pair_id")),
        "nonce_equal": bool(root_projection.get("nonce") and root_projection.get("nonce") == scheduler_projection.get("nonce") and _nonce(root_projection.get("nonce"))),
        "binding_sha_equal": bool(root_projection.get("binding_sha256") and root_projection.get("binding_sha256") == scheduler_projection.get("binding_sha256")),
        "pair_commitment_equal": bool(_mapping(root_receipt).get("pair_commitment_sha256") and _mapping(root_receipt).get("pair_commitment_sha256") == _mapping(scheduler_receipt).get("pair_commitment_sha256")),
        "pair_commitment_recomputed": False,
        "capability_cross_binding": _mapping(root_receipt).get("capability") == {**CAPABILITY, "role": "fresh_root", "fresh_namespace_observed": True, "root_owned_verified": True} and _mapping(scheduler_receipt).get("capability") == {**CAPABILITY, "role": "scheduler", "scheduler_owned_host_io_verified": True},
    }
    recomputed = _pair_commitment(root_projection, scheduler_projection)
    pair_checks["pair_commitment_recomputed"] = bool(
        root_projection.get("valid") and scheduler_projection.get("valid") and
        _mapping(root_receipt).get("pair_commitment_sha256") == recomputed and
        _mapping(scheduler_receipt).get("pair_commitment_sha256") == recomputed
    )
    if root_error:
        errors.append(f"root_receipt:{root_error}")
    if scheduler_error:
        errors.append(f"scheduler_receipt:{scheduler_error}")
    for name, passed in pair_checks.items():
        if not passed:
            errors.append(f"pair.{name}")
    root_present = bool(root_ref.get("exists"))
    scheduler_present = bool(scheduler_ref.get("exists"))
    if not anchor_valid:
        status = STATUS_ANCHOR_BLOCKED
    elif not root_present or not scheduler_present:
        status = STATUS_MISSING
    elif errors:
        status = STATUS_INVALID
    else:
        status = STATUS_BOUND
    blockers = list(dict.fromkeys(errors))
    checks = {
        "anchor_contract_valid": anchor_valid,
        "root_receipt_present": root_present,
        "scheduler_receipt_present": scheduler_present,
        "root_receipt_bounded_strict_json": root_ref.get("exists") is True and root_ref.get("bounded") is True and root_error is None,
        "scheduler_receipt_bounded_strict_json": scheduler_ref.get("exists") is True and scheduler_ref.get("bounded") is True and scheduler_error is None,
        "root_receipt_contract_valid": bool(root_projection.get("valid")),
        "scheduler_receipt_contract_valid": bool(scheduler_projection.get("valid")),
        "root_owner_inode_path_bound": bool(
            root_present
            and root_projection.get("fresh_root", {}).get("path_identity")
            and "root.fresh_root.namespace_path.missing" not in blockers
            and "root.fresh_root.path_identity.actual_missing" not in blockers
            and "root.fresh_root.path_identity.actual_mismatch" not in blockers
        ),
        "scheduler_owner_inode_path_bound": bool(
            scheduler_present
            and scheduler_projection.get("host_io_reservation", {}).get("path_identity")
            and "scheduler.host_io_reservation.path.missing" not in blockers
            and "scheduler.host_io_reservation.path_identity.actual_missing" not in blockers
            and "scheduler.host_io_reservation.path_identity.actual_mismatch" not in blockers
        ),
        "argv_hash_bound": bool(root_projection.get("binding", {}).get("normalized_launch_sha256") == scheduler_projection.get("binding", {}).get("normalized_launch_sha256") and root_projection.get("binding", {}).get("normalized_launch_sha256")),
        **pair_checks,
    }
    checks["contract_valid"] = bool(anchor_valid and root_present and scheduler_present and not blockers)
    return {
        "schema": SCHEMA,
        "record_id": RECORD_ID,
        "created_at": CREATED_AT,
        "observed_at": OBSERVED_AT,
        "status": status,
        "diagnostic_only": True,
        "non_authorizing": True,
        "readiness_pass": False,
        "T1": False,
        "T2": False,
        "qualification_credit": 0,
        "credit": 0,
        "anchor": anchor_ref,
        "binding_contract": binding_anchor,
        "receipts": {
            "fresh_root": root_ref,
            "scheduler_host_io": scheduler_ref,
        },
        "receipt_projection": {
            "fresh_root": root_projection,
            "scheduler_host_io": scheduler_projection,
        },
        "validation": {
            "checks": checks,
            "blockers": blockers,
            "anchor_errors": anchor_errors,
        },
        "authorization": _authorization(),
        "execution_controls": _execution_controls(),
        "next_safe_action": "Obtain real root-owned fresh namespace and scheduler-owned reservation receipts from their producers, then re-run this read-only contract; do not hand-edit or synthesize receipts.",
    }


def validate_report(value: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    required = {
        "schema",
        "record_id",
        "created_at",
        "observed_at",
        "status",
        "diagnostic_only",
        "non_authorizing",
        "readiness_pass",
        "T1",
        "T2",
        "qualification_credit",
        "credit",
        "anchor",
        "binding_contract",
        "receipts",
        "receipt_projection",
        "validation",
        "authorization",
        "execution_controls",
        "next_safe_action",
    }
    if set(value) != required:
        errors.append("report.fields")
    for key, expected in {
        "schema": SCHEMA,
        "record_id": RECORD_ID,
        "created_at": CREATED_AT,
        "observed_at": OBSERVED_AT,
        "diagnostic_only": True,
        "non_authorizing": True,
        "readiness_pass": False,
        "T1": False,
        "T2": False,
        "qualification_credit": 0,
        "credit": 0,
    }.items():
        if value.get(key) != expected:
            errors.append(f"report.{key}")
    if value.get("status") not in {STATUS_ANCHOR_BLOCKED, STATUS_MISSING, STATUS_INVALID, STATUS_BOUND}:
        errors.append("report.status")
    authorization = _mapping(value.get("authorization"))
    if authorization != _authorization():
        errors.append("report.authorization")
    controls = _mapping(value.get("execution_controls"))
    if controls != _execution_controls():
        errors.append("report.execution_controls")
    validation = _mapping(value.get("validation"))
    if set(validation) != {"checks", "blockers", "anchor_errors"}:
        errors.append("report.validation.fields")
    if not isinstance(validation.get("blockers"), list) or not all(isinstance(item, str) for item in validation.get("blockers", [])):
        errors.append("report.validation.blockers")
    checks = _mapping(validation.get("checks"))
    if checks.get("contract_valid") is not True and value.get("status") == STATUS_BOUND:
        errors.append("report.bound_status_without_contract")
    if checks.get("contract_valid") is True and value.get("status") != STATUS_BOUND:
        errors.append("report.contract_status_mismatch")
    for key in ("diagnostic_only", "non_authorizing", "readiness_pass", "T1", "T2"):
        if value.get(key) is not ({"diagnostic_only": True, "non_authorizing": True, "readiness_pass": False, "T1": False, "T2": False}[key]):
            errors.append(f"report.closed.{key}")
    return errors


def write_report(value: Mapping[str, Any], output: str | Path) -> Path:
    errors = validate_report(value)
    if errors:
        raise ValueError("refusing to write invalid F4 receipt contract report: " + ", ".join(errors))
    path = Path(output).resolve()
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return path


def _load_report(path: Path) -> dict[str, Any]:
    raw = read_bounded_raw_json(path, max_bytes=MAX_JSON_BYTES, label="F4 receipt contract report")
    return strict_json_object(raw, label="F4 receipt contract report", max_bytes=MAX_JSON_BYTES)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=LAB_ROOT)
    parser.add_argument("--anchor", type=Path, default=None)
    parser.add_argument("--root-receipt", type=Path, default=None)
    parser.add_argument("--scheduler-receipt", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--verify-report", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.verify_report is not None:
        report = _load_report(args.verify_report)
        errors = validate_report(report)
        print(json.dumps({"valid": not errors, "errors": errors}, sort_keys=True))
        return 0 if not errors else 1
    report = build_report(
        args.root,
        anchor_path=args.anchor,
        root_receipt_path=args.root_receipt,
        scheduler_receipt_path=args.scheduler_receipt,
    )
    write_report(report, args.output)
    print(json.dumps({"status": report["status"], "report": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
