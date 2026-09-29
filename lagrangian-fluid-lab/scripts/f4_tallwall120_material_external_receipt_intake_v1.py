#!/usr/bin/env python3
"""Read-only external receipt intake for the F4 Tallwall120 material attempt.

The older F4 receipt contract checks a pair of bounded JSON documents, but its
``scheduler_owned_host_io`` and snapshot fields are still claims made by the
documents themselves.  This additive contract closes that intake gap without
changing the older contract: receipts must come from an external path, carry
an independently supplied Ed25519 producer signature, reference immutable
one-use replay guards, and bind an externally captured host/resource snapshot.

This module never creates a namespace, reservation, receipt, replay token, or
signature.  It only reads bounded inputs and writes its own diagnostic report.
Even a fully verified pair remains non-authorizing: no worker, native solver,
GPU, queue, registry, ledger, denominator, gate, completion, or PLAN action is
performed.
"""

from __future__ import annotations

import argparse
import base64
import binascii
from copy import deepcopy
import errno
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

from scripts import f4_tallwall120_material_fresh_root_scheduler_receipt_contract_v1 as prior_contract  # noqa: E402
from scripts import f4_tallwall120_material_root_scheduler_intake_v1 as root_intake  # noqa: E402
from scripts.core_strict_json import strict_json_object  # noqa: E402


SCHEMA = "core.material.f4.tallwall120.external_receipt_intake.v1"
RECORD_ID = "f4-tallwall120-material-external-receipt-intake-v1"
CREATED_AT = "2026-09-29"
OBSERVED_AT = "2026-09-29T00:00:00Z"

FAMILY = "F4"
SCOPE_ID = "F4_resting_pool_laminar_tallwall120_x_v1"
CASE_ID = f"{SCOPE_ID}_DEV_07"
JOB_ID = "f4-tallwall120-production-dev-07"
ATTEMPT_ID = "f4-tallwall120-production-dev-07-coarse-baseline24-s2-r001"

ANCHOR_REPORT = prior_contract.ANCHOR_REPORT
DEFAULT_OUTPUT_NAMESPACE = prior_contract.DEFAULT_OUTPUT_NAMESPACE
DEFAULT_ROOT_RECEIPT = Path(
    "/run/f4/tallwall120/material/dev-07/fresh-root-receipt.json"
)
DEFAULT_SCHEDULER_RECEIPT = Path(
    "/run/f4/tallwall120/material/dev-07/scheduler-host-io-receipt.json"
)
DEFAULT_REPORT = Path(
    "reports/F4-TALLWALL120-MATERIAL-EXTERNAL-RECEIPT-INTAKE-V1-2026-09-29.json"
)
DEFAULT_ZH_REPORT = Path(
    "reports/F4-TALLWALL120-MATERIAL-EXTERNAL-RECEIPT-INTAKE-V1-2026-09-29.zh-CN.md"
)

ROOT_RECEIPT_SCHEMA = (
    "core.material.f4.tallwall120.external.fresh_root_receipt.v1"
)
SCHEDULER_RECEIPT_SCHEMA = (
    "core.material.f4.tallwall120.external.scheduler_host_io_receipt.v1"
)
ROOT_RECEIPT_ID = "f4-tallwall120-external-fresh-root-receipt-v1"
SCHEDULER_RECEIPT_ID = "f4-tallwall120-external-scheduler-host-io-receipt-v1"
HOST_SNAPSHOT_SCHEMA = "core.f4.tallwall120.external.host_resource_snapshot.v1"
HOST_SNAPSHOT_ID = "f4-tallwall120-external-host-resource-snapshot-v1"
REPLAY_GUARD_SCHEMA = "core.f4.tallwall120.external.one_use_replay_guard.v1"
REPLAY_GUARD_ID = "f4-tallwall120-external-one-use-replay-guard-v1"

ROOT_ISSUER = "f4-tallwall120-root-namespace-producer"
SCHEDULER_ISSUER = "f4-tallwall120-scheduler-host-io-producer"
ROOT_KEY_ID = "f4-tallwall120-root-producer-ed25519-v1"
SCHEDULER_KEY_ID = "f4-tallwall120-scheduler-producer-ed25519-v1"

STATUS_ANCHOR_BLOCKED = "blocked_anchor_contract_invalid"
STATUS_MISSING = "blocked_missing_external_receipts"
STATUS_INVALID = "blocked_invalid_external_receipts"
STATUS_VERIFIED = "external_receipts_verified_non_authorizing"

MAX_JSON_BYTES = 1 * 1024 * 1024
MAX_SMALL_FILE_BYTES = 8 * 1024 * 1024
MAX_KEY_BYTES = 64 * 1024
MIN_FREE_DISK_BYTES = 20 * 1024**3
SHA256 = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
NONCE = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,191}\Z", re.ASCII)
SAFE_HOST = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,254}\Z", re.ASCII)
ISO_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\Z")
O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
O_NONBLOCK = getattr(os, "O_NONBLOCK", 0)
O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
O_PATH = getattr(os, "O_PATH", 0)

PATH_IDENTITY_FIELDS = {
    "path",
    "device",
    "inode",
    "owner_uid",
    "owner_name",
    "nlink",
    "mode",
    "kind",
    "size",
    "mtime_ns",
    "ctime_ns",
}
RECEIPT_FIELDS = {
    "schema",
    "receipt_id",
    "kind",
    "status",
    "synthetic",
    "pair_id",
    "attempt_id",
    "nonce",
    "binding",
    "binding_sha256",
    "receipt_digest_sha256",
    "pair_commitment_sha256",
    "receipt_identity",
    "producer_attestation",
    "replay_guard",
    "counterparty",
    "fresh_root",
    "host_io_reservation",
    "host_resource_snapshot",
    "side_effects",
}
BINDING_FIELDS = {
    "scope",
    "source",
    "input_hashes",
    "code_hashes",
    "normalized_launch",
    "normalized_launch_sha256",
    "cwd",
    "attempt_namespace",
    "manifest",
    "resource_request",
}
ATTEMPT_NAMESPACE_FIELDS = {
    "attempt_id",
    "namespace",
    "namespace_path",
    "namespace_nonce",
    "fresh",
    "reused",
    "overwrite_allowed",
    "resume_allowed",
    "historical_trace_reuse",
}
ROOT_NAMESPACE_FIELDS = {
    "namespace",
    "namespace_path",
    "path_identity",
    "fresh",
    "reused",
    "overwrite_allowed",
    "resume_allowed",
    "historical_trace_reuse",
    "entry_count",
    "single_use",
    "consumed",
}
RESERVATION_FIELDS = {
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
    "selected_gpu_uuid",
    "single_use",
    "consumed",
}
SNAPSHOT_REF_FIELDS = {
    "schema",
    "record_id",
    "path",
    "sha256",
    "identity",
    "snapshot_id",
    "pair_id",
    "attempt_id",
    "nonce",
}
SNAPSHOT_FIELDS = {
    "schema",
    "record_id",
    "synthetic",
    "snapshot_id",
    "pair_id",
    "attempt_id",
    "nonce",
    "host",
    "resources",
}
HOST_FIELDS = {"hostname", "boot_id", "captured_at_utc"}
RESOURCE_FIELDS = {
    "cpu_count",
    "ram_total_mib",
    "ram_available_mib",
    "disk_free_bytes",
    "io_capacity",
    "filesystem",
    "gpus",
    "gpu_processes",
}
GPU_FIELDS = {
    "index",
    "uuid",
    "pci_bus_id",
    "name",
    "total_mib",
    "used_mib",
    "free_mib",
    "utilization",
}
GPU_PROCESS_FIELDS = {"uuid", "pid", "used_mib"}
PRODUCER_FIELDS = {
    "issuer",
    "key_id",
    "algorithm",
    "public_key_sha256",
    "producer_uid",
    "producer_gid",
    "producer_pid",
    "producer_start_ticks",
    "boot_id",
    "external",
    "synthetic",
    "signed_payload_sha256",
    "signature_base64",
}
REPLAY_REF_FIELDS = {
    "schema",
    "record_id",
    "path",
    "sha256",
    "identity",
    "role",
    "pair_id",
    "attempt_id",
    "nonce",
    "lease_id",
    "state",
    "single_use",
    "consumed",
    "producer_uid",
}
REPLAY_FILE_FIELDS = {
    "schema",
    "record_id",
    "role",
    "pair_id",
    "attempt_id",
    "nonce",
    "lease_id",
    "state",
    "single_use",
    "consumed",
    "producer_uid",
}
COUNTERPARTY_FIELDS = {
    "path",
    "identity",
    "pair_id",
    "attempt_id",
    "nonce",
    "binding_sha256",
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

CHECK_NAMES = (
    "anchor_contract_valid",
    "source_claim_bound",
    "source_metadata_valid",
    "current_code_hashes_valid",
    "manifest_sha_valid",
    "argv_sha_bound",
    "cwd_bound",
    "attempt_namespace_template_bound",
    "root_receipt_present",
    "scheduler_receipt_present",
    "root_receipt_external_path",
    "scheduler_receipt_external_path",
    "root_receipt_contract_valid",
    "scheduler_receipt_contract_valid",
    "root_producer_authenticated",
    "scheduler_producer_authenticated",
    "root_replay_guard_valid",
    "scheduler_replay_guard_valid",
    "root_namespace_owner_inode_bound",
    "scheduler_reservation_owner_inode_bound",
    "host_resource_snapshot_valid",
    "resource_capacity_sufficient",
    "pair_id_equal",
    "attempt_id_equal",
    "nonce_equal",
    "binding_sha_equal",
    "pair_commitment_equal",
    "counterparty_cross_bound",
    "pair_commitment_recomputed",
    "external_intake_valid",
)


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


def _absolute(path: str | Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _resolve(root: Path, value: str | Path) -> Path:
    candidate = Path(value)
    return _absolute(candidate if candidate.is_absolute() else root / candidate)


def _under(path: Path, parent: Path) -> bool:
    try:
        _absolute(path).relative_to(_absolute(parent))
        return True
    except ValueError:
        return False


def _external(path: Path) -> bool:
    return path.is_absolute() and not _under(path, LAB_ROOT)


def _assert_no_symlink_components(path: Path, label: str) -> None:
    current = Path(_absolute(path).anchor)
    for component in _absolute(path).parts[1:]:
        current /= component
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            continue
        except OSError as error:
            raise ValueError(f"{label} path inspection failed") from error
        if stat.S_ISLNK(info.st_mode):
            raise ValueError(f"{label} path contains a symlink")


def _open_directory_chain(path: Path, label: str) -> int:
    """Open every directory component without following a pathname alias."""

    if not O_NOFOLLOW or not O_DIRECTORY or not O_CLOEXEC:
        raise ValueError(f"{label} safe directory open is unavailable")
    absolute = _absolute(path)
    flags = os.O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC
    descriptor: int | None = None
    try:
        descriptor = os.open(Path(absolute.anchor or "/"), flags)
        for component in absolute.parts[1:]:
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except BaseException:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise


def _stat_signature(info: os.stat_result) -> tuple[int, ...]:
    return (
        int(info.st_dev),
        int(info.st_ino),
        int(info.st_mode),
        int(info.st_nlink),
        int(info.st_size),
        int(info.st_mtime_ns),
        int(info.st_ctime_ns),
    )


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


def _identity(path: Path, info: os.stat_result) -> dict[str, Any]:
    return {
        "path": str(_absolute(path)),
        "device": info.st_dev,
        "inode": info.st_ino,
        "owner_uid": info.st_uid,
        "owner_name": _owner_name(info.st_uid),
        "nlink": info.st_nlink,
        "mode": info.st_mode,
        "kind": _kind(info.st_mode),
        "size": info.st_size,
        "mtime_ns": info.st_mtime_ns,
        "ctime_ns": info.st_ctime_ns,
    }


def _lstat_identity(
    path: Path,
    *,
    label: str,
    kinds: set[str] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    parent_descriptor: int | None = None
    descriptor: int | None = None
    try:
        _assert_no_symlink_components(path, label)
        if not O_PATH or not O_NOFOLLOW or not O_CLOEXEC or not O_DIRECTORY:
            return None, "safe_open_unavailable"
        parent_descriptor = _open_directory_chain(path.parent, f"{label} parent")
        descriptor = os.open(path.name, O_PATH | O_NOFOLLOW | O_CLOEXEC, dir_fd=parent_descriptor)
        info = os.fstat(descriptor)
        named = os.stat(path.name, dir_fd=parent_descriptor, follow_symlinks=False)
        if _stat_signature(info) != _stat_signature(named):
            return None, "changed"
    except FileNotFoundError:
        return None, "missing"
    except ValueError:
        return None, "symlink_path"
    except OSError as error:
        return None, "symlink_path" if error.errno == errno.ELOOP else type(error).__name__
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if parent_descriptor is not None:
            os.close(parent_descriptor)
    value = _identity(path, info)
    if value["kind"] == "symlink":
        return value, "symlink"
    if kinds is not None and value["kind"] not in kinds:
        return value, "wrong_kind"
    return value, None


def _stable_bytes(
    path: Path,
    *,
    label: str,
    limit: int,
) -> tuple[bytes | None, dict[str, Any] | None, str | None]:
    if not O_NOFOLLOW or not O_NONBLOCK or not O_CLOEXEC or not O_DIRECTORY:
        return None, None, "safe_open_unavailable"
    parent_descriptor: int | None = None
    descriptor: int | None = None
    try:
        _assert_no_symlink_components(path, label)
        parent_descriptor = _open_directory_chain(path.parent, f"{label} parent")
        descriptor = os.open(
            path.name,
            O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC | os.O_RDONLY,
            dir_fd=parent_descriptor,
        )
    except FileNotFoundError:
        return None, None, "missing"
    except ValueError:
        return None, None, "symlink_path"
    except OSError as error:
        return None, None, "symlink_path" if error.errno == errno.ELOOP else type(error).__name__
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            return None, None, "not_single_link_regular_file"
        if before.st_size > limit:
            return None, None, "oversize"
        blocks: list[bytes] = []
        total = 0
        while True:
            block = os.read(descriptor, min(1024 * 1024, limit + 1 - total))
            if not block:
                break
            blocks.append(block)
            total += len(block)
            if total > limit:
                return None, None, "oversize"
        after = os.fstat(descriptor)
        named = os.stat(path.name, dir_fd=parent_descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return None, None, "changed_during_read"
    except OSError as error:
        return None, None, type(error).__name__
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if parent_descriptor is not None:
            os.close(parent_descriptor)
    try:
        raw = b"".join(blocks)
        if total != before.st_size or _stat_signature(before) != _stat_signature(after) or _stat_signature(after) != _stat_signature(named):
            return None, None, "changed_during_read"
        _assert_no_symlink_components(path, label)
    except FileNotFoundError:
        return None, None, "changed_during_read"
    except ValueError:
        return None, None, "symlink_path"
    except OSError:
        return None, None, "changed_during_read"
    return raw, _identity(path, after), None


def _directory_entry_count(
    path: Path,
    expected: Mapping[str, Any],
    *,
    label: str,
) -> tuple[int | None, str | None]:
    """Count entries through a held directory descriptor and bind its identity."""

    descriptor: int | None = None
    try:
        _assert_no_symlink_components(path, label)
        descriptor = _open_directory_chain(path, label)
        before = os.fstat(descriptor)
        named = os.stat(path, follow_symlinks=False)
        if _stat_signature(before) != _stat_signature(named) or dict(expected) != _identity(path, before):
            return None, "changed"
        count = len(os.listdir(descriptor))
        after = os.fstat(descriptor)
        if _stat_signature(before) != _stat_signature(after) or dict(expected) != _identity(path, after):
            return None, "changed"
        _assert_no_symlink_components(path, label)
        return count, None
    except FileNotFoundError:
        return None, "missing"
    except ValueError:
        return None, "symlink_path"
    except OSError as error:
        return None, "symlink_path" if error.errno == errno.ELOOP else type(error).__name__
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _read_json(
    path: Path,
    *,
    root: Path,
    label: str,
) -> tuple[dict[str, Any], dict[str, Any], str | None]:
    ref: dict[str, Any] = {
        "role": label,
        "path": str(_absolute(path)),
        "external_path": _external(path),
        "exists": False,
        "bounded": True,
        "content_read": False,
        "bytes": None,
        "sha256": None,
        "identity": None,
        "error": None,
    }
    raw, identity, error = _stable_bytes(path, label=label, limit=MAX_JSON_BYTES)
    if error is not None or raw is None or identity is None:
        ref["error"] = error or "read_failed"
        return {}, ref, error or "read_failed"
    ref.update(
        {
            "exists": True,
            "content_read": True,
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "identity": identity,
        }
    )
    try:
        value = strict_json_object(raw, label=label, max_bytes=MAX_JSON_BYTES)
    except (ValueError, UnicodeError, json.JSONDecodeError, RecursionError) as error:
        ref["error"] = type(error).__name__
        return {}, ref, type(error).__name__
    return value, ref, None


def _read_key(path: Path) -> tuple[bytes | None, dict[str, Any], str | None]:
    raw, identity, error = _stable_bytes(path, label="trusted producer public key", limit=MAX_KEY_BYTES)
    ref: dict[str, Any] = {
        "path": str(_absolute(path)),
        "external_path": _external(path),
        "exists": raw is not None,
        "bytes": len(raw) if raw is not None else None,
        "sha256": hashlib.sha256(raw).hexdigest() if raw is not None else None,
        "identity": identity,
        "error": error,
    }
    return raw, ref, error


def _safe_id(value: Any) -> bool:
    return isinstance(value, str) and SAFE_ID.fullmatch(value) is not None


def _safe_host(value: Any) -> bool:
    return isinstance(value, str) and SAFE_HOST.fullmatch(value) is not None


def _sha(value: Any) -> bool:
    return isinstance(value, str) and SHA256.fullmatch(value) is not None


def _nonce(value: Any) -> bool:
    return isinstance(value, str) and NONCE.fullmatch(value) is not None


def _finite_nonnegative(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) >= 0
    )


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _same_identity(value: Any, actual: Mapping[str, Any] | None, label: str, errors: list[str]) -> bool:
    start = len(errors)
    if not isinstance(value, Mapping) or set(value) != PATH_IDENTITY_FIELDS:
        errors.append(f"{label}.fields")
        return False
    if actual is None:
        errors.append(f"{label}.actual_missing")
    elif dict(value) != dict(actual):
        errors.append(f"{label}.actual_mismatch")
    if value.get("kind") not in {"file", "directory"}:
        errors.append(f"{label}.kind")
    for key in ("device", "inode", "owner_uid", "nlink", "mode", "size", "mtime_ns", "ctime_ns"):
        if type(value.get(key)) is not int or value.get(key) < 0:
            errors.append(f"{label}.{key}")
    if not isinstance(value.get("path"), str) or not os.path.isabs(value["path"]):
        errors.append(f"{label}.path")
    if not isinstance(value.get("owner_name"), str) or not value.get("owner_name"):
        errors.append(f"{label}.owner_name")
    return len(errors) == start


def _external_path(value: Any, *, expected: Path, label: str, errors: list[str]) -> bool:
    if not isinstance(value, str) or value != str(_absolute(expected)):
        errors.append(f"{label}.path")
        return False
    if not _external(expected):
        errors.append(f"{label}.not_external")
        return False
    return True


def _side_effects_closed(value: Any, label: str, errors: list[str]) -> bool:
    start = len(errors)
    if not isinstance(value, Mapping) or set(value) != SIDE_EFFECT_FIELDS:
        errors.append(f"{label}.fields")
        return False
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


def _receipt_core(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: deepcopy(item)
        for key, item in value.items()
        if key not in {"producer_attestation", "receipt_digest_sha256"}
    }


def _expected_binding(
    anchor: Mapping[str, Any],
    details: Mapping[str, Any],
    root: Path,
    nonce: str,
) -> dict[str, Any]:
    output = _mapping(anchor["output_namespace"])
    namespace = str(output["namespace"])
    return {
        "scope": deepcopy(dict(anchor["scope"])),
        "source": deepcopy(dict(anchor["source"])),
        "input_hashes": deepcopy(dict(anchor["input_hashes"])),
        "code_hashes": deepcopy(dict(details["expected_code_hashes"])),
        "normalized_launch": deepcopy(dict(anchor["normalized_launch"])),
        "normalized_launch_sha256": anchor["normalized_launch_sha256"],
        "cwd": anchor["normalized_launch"]["cwd"],
        "attempt_namespace": {
            "attempt_id": ATTEMPT_ID,
            "namespace": namespace,
            "namespace_path": str(_resolve(root, namespace)),
            "namespace_nonce": nonce,
            "fresh": True,
            "reused": False,
            "overwrite_allowed": False,
            "resume_allowed": False,
            "historical_trace_reuse": False,
        },
        "manifest": deepcopy(dict(details["expected_manifest"])),
        "resource_request": deepcopy(dict(anchor["resource_request"])),
    }


def _load_anchor(
    root: Path,
    anchor_path: str | Path | None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], list[str]]:
    anchor_file = _resolve(root, anchor_path or ANCHOR_REPORT)
    payload, ref, error = _read_json(
        anchor_file,
        root=root,
        label="F4 v1 root/scheduler anchor report",
    )
    errors: list[str] = []
    if anchor_file != _resolve(root, ANCHOR_REPORT):
        errors.append("anchor.path")
    if error:
        errors.append(f"anchor.read:{error}")
        return {}, ref, {}, {}, errors
    binding, _, prior_errors = prior_contract._load_anchor(
        root,
        anchor_file,
        loaded_anchor=payload,
        loaded_reference=ref,
    )
    errors.extend(prior_errors)
    current_code: dict[str, Any] = {}
    expected_code: dict[str, Any] = {}
    code_hashes = _mapping(payload.get("current_code_hashes"))
    expected_code_names = set(root_intake.CURRENT_CODE)
    if set(code_hashes) != expected_code_names:
        errors.append("anchor.current_code_hashes.fields")
    for name in sorted(expected_code_names):
        item = code_hashes.get(name)
        if not isinstance(item, Mapping):
            errors.append(f"anchor.current_code_hashes.{name}.fields")
            continue
        path_value = item.get("path")
        expected_sha = item.get("sha256")
        expected_bytes = item.get("bytes")
        expected_code[name] = {
            "path": path_value,
            "sha256": expected_sha,
            "bytes": expected_bytes,
        }
        expected_path = root_intake.CURRENT_CODE[name].as_posix()
        if path_value != expected_path:
            errors.append(f"anchor.current_code_hashes.{name}.path")
            continue
        if not isinstance(path_value, str) or not _sha(expected_sha) or type(expected_bytes) is not int:
            errors.append(f"anchor.current_code_hashes.{name}.shape")
            continue
        path = _resolve(root, path_value)
        raw, identity, read_error = _stable_bytes(
            path,
            label=f"current F4 code {name}",
            limit=MAX_SMALL_FILE_BYTES,
        )
        actual_sha = hashlib.sha256(raw).hexdigest() if raw is not None else None
        current_code[name] = {
            "path": path_value,
            "expected_sha256": expected_sha,
            "actual_sha256": actual_sha,
            "expected_bytes": expected_bytes,
            "actual_bytes": len(raw) if raw is not None else None,
            "identity": identity,
            "error": read_error,
        }
        if read_error or actual_sha != expected_sha or len(raw or b"") != expected_bytes:
            errors.append(f"anchor.current_code_hashes.{name}.mismatch")

    input_bindings = _mapping(payload.get("input_bindings"))
    collection = _mapping(input_bindings.get("collection"))
    manifest_path_value = collection.get("path")
    manifest_sha = collection.get("sha256")
    expected_manifest = {
        "path": manifest_path_value,
        "sha256": manifest_sha,
        "bytes": collection.get("bytes"),
    }
    manifest_raw: bytes | None = None
    manifest_identity: dict[str, Any] | None = None
    manifest_error: str | None = None
    expected_manifest_path = root_intake.COLLECTION.as_posix()
    if manifest_path_value != expected_manifest_path:
        errors.append("anchor.manifest.path")
    if not isinstance(manifest_path_value, str) or manifest_path_value != expected_manifest_path or not _sha(manifest_sha):
        errors.append("anchor.manifest.shape")
    else:
        manifest_raw, manifest_identity, manifest_error = _stable_bytes(
            _resolve(root, manifest_path_value),
            label="current F4 collection manifest",
            limit=MAX_SMALL_FILE_BYTES,
        )
        if manifest_error or hashlib.sha256(manifest_raw or b"").hexdigest() != manifest_sha:
            errors.append("anchor.manifest.sha256_mismatch")
    manifest_observation = {
        "path": manifest_path_value,
        "expected_sha256": manifest_sha,
        "actual_sha256": hashlib.sha256(manifest_raw).hexdigest() if manifest_raw is not None else None,
        "expected_bytes": collection.get("bytes"),
        "actual_bytes": len(manifest_raw) if manifest_raw is not None else None,
        "identity": manifest_identity,
        "error": manifest_error,
    }

    source = _mapping(binding.get("source"))
    source_path = _resolve(root, str(source.get("path", "")))
    source_identity, source_error = _lstat_identity(
        source_path,
        label="F4 source trajectory",
        kinds={"file"},
    )
    source_observation = {
        "path": source.get("path"),
        "declared_sha256": source.get("sha256"),
        "declared_bytes": source.get("bytes"),
        "actual_bytes": source_identity.get("size") if source_identity else None,
        "exists": source_identity is not None,
        "regular_file": bool(source_identity and source_identity.get("kind") == "file"),
        "symlink": bool(source_error == "symlink"),
        "read": False,
        "hash_recomputed": False,
        "mode": "lstat_metadata_only",
        "error": source_error,
    }
    if (
        source_error
        or source_identity is None
        or source_identity.get("size") != source.get("bytes")
        or source_identity.get("nlink") != 1
    ):
        errors.append("anchor.source.metadata_mismatch")

    details = {
        "current_code": current_code,
        "expected_code_hashes": expected_code,
        "manifest": manifest_observation,
        "expected_manifest": expected_manifest,
        "source": source_observation,
        "cwd": _mapping(binding.get("normalized_launch")).get("cwd"),
        "code_hashes_valid": not any(item.startswith("anchor.current_code_hashes.") for item in errors),
        "manifest_sha_valid": not any(item.startswith("anchor.manifest.") for item in errors),
        "source_metadata_valid": not any(item.startswith("anchor.source.") for item in errors),
    }
    return binding, ref, details, payload, errors


def _validate_binding(
    value: Any,
    expected: Mapping[str, Any],
    label: str,
    errors: list[str],
) -> tuple[bool, dict[str, Any]]:
    start = len(errors)
    if not isinstance(value, Mapping) or set(value) != BINDING_FIELDS:
        errors.append(f"{label}.fields")
        return False, {}
    if dict(value) != dict(expected):
        errors.append(f"{label}.value")
    return len(errors) == start, dict(value)


def _validate_identity_owner(
    value: Any,
    actual: Mapping[str, Any] | None,
    *,
    label: str,
    expected_kind: str,
    expected_owner_uid: int | None,
    errors: list[str],
) -> bool:
    start = len(errors)
    _same_identity(value, actual, label, errors)
    if isinstance(value, Mapping):
        if value.get("kind") != expected_kind:
            errors.append(f"{label}.expected_kind")
        if expected_owner_uid is not None and value.get("owner_uid") != expected_owner_uid:
            errors.append(f"{label}.expected_owner_uid")
    return len(errors) == start


def _validate_producer(
    value: Any,
    *,
    role: str,
    receipt_identity: Mapping[str, Any] | None,
    core: Mapping[str, Any],
    trusted_key_path: Path | None,
    key_ref: dict[str, Any],
    errors: list[str],
) -> tuple[bool, dict[str, Any]]:
    start = len(errors)
    expected_issuer = ROOT_ISSUER if role == "root" else SCHEDULER_ISSUER
    expected_key_id = ROOT_KEY_ID if role == "root" else SCHEDULER_KEY_ID
    if not isinstance(value, Mapping) or set(value) != PRODUCER_FIELDS:
        errors.append(f"{role}.producer_attestation.fields")
        return False, {}
    for key, expected in {
        "issuer": expected_issuer,
        "key_id": expected_key_id,
        "algorithm": "ed25519",
        "external": True,
        "synthetic": False,
    }.items():
        if value.get(key) != expected:
            errors.append(f"{role}.producer_attestation.{key}")
    for key in ("producer_uid", "producer_gid", "producer_pid", "producer_start_ticks"):
        if type(value.get(key)) is not int or value.get(key) < 0:
            errors.append(f"{role}.producer_attestation.{key}")
    if not isinstance(value.get("boot_id"), str) or not value.get("boot_id"):
        errors.append(f"{role}.producer_attestation.boot_id")
    if not _sha(value.get("public_key_sha256")):
        errors.append(f"{role}.producer_attestation.public_key_sha256")
    signed_payload_sha = canonical_digest(core)
    if value.get("signed_payload_sha256") != signed_payload_sha:
        errors.append(f"{role}.producer_attestation.signed_payload_sha256")
    try:
        signature = base64.b64decode(value.get("signature_base64", ""), validate=True)
    except (ValueError, binascii.Error):
        signature = b""
    if len(signature) != 64:
        errors.append(f"{role}.producer_attestation.signature_base64")
    if receipt_identity is None:
        errors.append(f"{role}.producer_attestation.receipt_identity_missing")
    elif value.get("producer_uid") != receipt_identity.get("owner_uid"):
        errors.append(f"{role}.producer_attestation.receipt_owner_mismatch")
    if role == "root" and value.get("producer_uid") != 0:
        errors.append("root.producer_attestation.root_uid_required")
    authenticated = False
    if trusted_key_path is None:
        errors.append(f"{role}.producer_attestation.trusted_key_missing")
        key_ref["error"] = "trusted_key_not_configured"
    else:
        key_bytes, loaded_ref, key_error = _read_key(trusted_key_path)
        key_ref.update(loaded_ref)
        if key_error or key_bytes is None:
            errors.append(f"{role}.producer_attestation.trusted_key_{key_error or 'read_failed'}")
        elif not _external(trusted_key_path):
            errors.append(f"{role}.producer_attestation.trusted_key_not_external")
        elif hashlib.sha256(key_bytes).hexdigest() != value.get("public_key_sha256"):
            errors.append(f"{role}.producer_attestation.trusted_key_sha256_mismatch")
        else:
            try:
                from cryptography.hazmat.primitives import serialization
                from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

                public_key = serialization.load_pem_public_key(key_bytes)
                if not isinstance(public_key, Ed25519PublicKey):
                    raise ValueError("trusted key is not Ed25519")
                public_key.verify(signature, _canonical(core))
                authenticated = True
            except Exception as error:  # cryptography is deliberately optional at import time
                errors.append(f"{role}.producer_attestation.signature_invalid:{type(error).__name__}")
    return authenticated and len(errors) == start, dict(value)


def _validate_replay_guard(
    value: Any,
    *,
    role: str,
    pair_id: Any,
    attempt_id: Any,
    nonce: Any,
    producer_uid: Any,
    errors: list[str],
) -> tuple[bool, dict[str, Any]]:
    start = len(errors)
    if not isinstance(value, Mapping) or set(value) != REPLAY_REF_FIELDS:
        errors.append(f"{role}.replay_guard.fields")
        return False, {}
    path = Path(str(value.get("path"))) if isinstance(value.get("path"), str) else Path(".")
    _external_path(value.get("path"), expected=path, label=f"{role}.replay_guard", errors=errors)
    if value.get("schema") != REPLAY_GUARD_SCHEMA or value.get("record_id") != REPLAY_GUARD_ID:
        errors.append(f"{role}.replay_guard.schema")
    if value.get("role") != role or value.get("pair_id") != pair_id or value.get("attempt_id") != attempt_id or value.get("nonce") != nonce:
        errors.append(f"{role}.replay_guard.binding")
    if not _safe_id(value.get("lease_id")):
        errors.append(f"{role}.replay_guard.lease_id")
    if value.get("state") != "unconsumed" or value.get("single_use") is not True or value.get("consumed") is not False:
        errors.append(f"{role}.replay_guard.reuse_or_consumed")
    if value.get("producer_uid") != producer_uid:
        errors.append(f"{role}.replay_guard.producer_uid")
    actual, path_error = _lstat_identity(path, label=f"{role} replay guard", kinds={"file"})
    if path_error:
        errors.append(f"{role}.replay_guard.path.{path_error}")
    _validate_identity_owner(
        value.get("identity"),
        actual,
        label=f"{role}.replay_guard.identity",
        expected_kind="file",
        expected_owner_uid=producer_uid if isinstance(producer_uid, int) else None,
        errors=errors,
    )
    raw, stable_identity, read_error = _stable_bytes(path, label=f"{role} replay guard", limit=MAX_JSON_BYTES)
    if read_error or raw is None:
        errors.append(f"{role}.replay_guard.read.{read_error or 'failed'}")
        return False, {}
    if actual is None or stable_identity is None or dict(stable_identity) != dict(actual):
        errors.append(f"{role}.replay_guard.path_identity_changed_during_read")
    if not _sha(value.get("sha256")) or value.get("sha256") != hashlib.sha256(raw).hexdigest():
        errors.append(f"{role}.replay_guard.sha256")
    try:
        guard = strict_json_object(raw, label=f"{role} replay guard", max_bytes=MAX_JSON_BYTES)
    except (ValueError, UnicodeError, json.JSONDecodeError, RecursionError) as error:
        errors.append(f"{role}.replay_guard.json:{type(error).__name__}")
        return False, {}
    if set(guard) != REPLAY_FILE_FIELDS:
        errors.append(f"{role}.replay_guard.document.fields")
    expected_guard = {
        "schema": REPLAY_GUARD_SCHEMA,
        "record_id": REPLAY_GUARD_ID,
        "role": role,
        "pair_id": pair_id,
        "attempt_id": attempt_id,
        "nonce": nonce,
        "lease_id": value.get("lease_id"),
        "state": "unconsumed",
        "single_use": True,
        "consumed": False,
        "producer_uid": producer_uid,
    }
    if guard != expected_guard:
        errors.append(f"{role}.replay_guard.document.binding")
    return len(errors) == start, {
        "path": str(_absolute(path)),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "identity": actual or {},
        "lease_id": value.get("lease_id"),
        "state": guard.get("state"),
        "consumed": guard.get("consumed"),
    }


def _validate_snapshot(
    value: Any,
    *,
    pair_id: Any,
    attempt_id: Any,
    nonce: Any,
    reservation: Mapping[str, Any],
    expected_resources: Mapping[str, Any],
    errors: list[str],
) -> tuple[bool, dict[str, Any], dict[str, Any]]:
    start = len(errors)
    if not isinstance(value, Mapping) or set(value) != SNAPSHOT_REF_FIELDS:
        errors.append("scheduler.host_resource_snapshot.fields")
        return False, {}, {}
    path = Path(str(value.get("path"))) if isinstance(value.get("path"), str) else Path(".")
    _external_path(value.get("path"), expected=path, label="scheduler.host_resource_snapshot", errors=errors)
    if value.get("schema") != HOST_SNAPSHOT_SCHEMA or value.get("record_id") != HOST_SNAPSHOT_ID:
        errors.append("scheduler.host_resource_snapshot.schema")
    if value.get("pair_id") != pair_id or value.get("attempt_id") != attempt_id or value.get("nonce") != nonce:
        errors.append("scheduler.host_resource_snapshot.binding")
    if value.get("snapshot_id") != reservation.get("snapshot_id") or not _safe_id(value.get("snapshot_id")):
        errors.append("scheduler.host_resource_snapshot.snapshot_id")
    actual, path_error = _lstat_identity(path, label="scheduler host/resource snapshot", kinds={"file"})
    if path_error:
        errors.append(f"scheduler.host_resource_snapshot.path.{path_error}")
    _validate_identity_owner(
        value.get("identity"),
        actual,
        label="scheduler.host_resource_snapshot.identity",
        expected_kind="file",
        expected_owner_uid=None,
        errors=errors,
    )
    raw, stable_identity, read_error = _stable_bytes(path, label="scheduler host/resource snapshot", limit=MAX_JSON_BYTES)
    if read_error or raw is None:
        errors.append(f"scheduler.host_resource_snapshot.read.{read_error or 'failed'}")
        return False, {}, {}
    if actual is None or stable_identity is None or dict(stable_identity) != dict(actual):
        errors.append("scheduler.host_resource_snapshot.path_identity_changed_during_read")
    digest = hashlib.sha256(raw).hexdigest()
    if value.get("sha256") != digest or not _sha(value.get("sha256")):
        errors.append("scheduler.host_resource_snapshot.sha256")
    try:
        snapshot = strict_json_object(raw, label="scheduler host/resource snapshot", max_bytes=MAX_JSON_BYTES)
    except (ValueError, UnicodeError, json.JSONDecodeError, RecursionError) as error:
        errors.append(f"scheduler.host_resource_snapshot.json:{type(error).__name__}")
        return False, {}, {}
    if set(snapshot) != SNAPSHOT_FIELDS:
        errors.append("scheduler.host_resource_snapshot.document.fields")
    for key, expected in {
        "schema": HOST_SNAPSHOT_SCHEMA,
        "record_id": HOST_SNAPSHOT_ID,
        "synthetic": False,
        "snapshot_id": value.get("snapshot_id"),
        "pair_id": pair_id,
        "attempt_id": attempt_id,
        "nonce": nonce,
    }.items():
        if snapshot.get(key) != expected:
            errors.append(f"scheduler.host_resource_snapshot.document.{key}")
    host = _mapping(snapshot.get("host"))
    if set(host) != HOST_FIELDS:
        errors.append("scheduler.host_resource_snapshot.host.fields")
    if not _safe_host(host.get("hostname")) or not isinstance(host.get("boot_id"), str) or not host.get("boot_id"):
        errors.append("scheduler.host_resource_snapshot.host.identity")
    if not isinstance(host.get("captured_at_utc"), str) or ISO_UTC.fullmatch(host.get("captured_at_utc", "")) is None:
        errors.append("scheduler.host_resource_snapshot.host.captured_at_utc")
    resources = _mapping(snapshot.get("resources"))
    if set(resources) != RESOURCE_FIELDS:
        errors.append("scheduler.host_resource_snapshot.resources.fields")
    for key in ("cpu_count", "ram_total_mib", "ram_available_mib", "disk_free_bytes"):
        if type(resources.get(key)) is not int or resources.get(key) < 0:
            errors.append(f"scheduler.host_resource_snapshot.resources.{key}")
    if resources.get("cpu_count", 0) < 1 or resources.get("ram_total_mib", 0) < 1:
        errors.append("scheduler.host_resource_snapshot.resources.host_capacity")
    if not _finite_nonnegative(resources.get("io_capacity")):
        errors.append("scheduler.host_resource_snapshot.resources.io_capacity")
    if resources.get("filesystem") != reservation.get("filesystem"):
        errors.append("scheduler.host_resource_snapshot.resources.filesystem")
    gpus = resources.get("gpus")
    gpu_by_uuid: dict[str, Mapping[str, Any]] = {}
    if not isinstance(gpus, list) or not gpus:
        errors.append("scheduler.host_resource_snapshot.resources.gpus")
        gpus = []
    for index, gpu in enumerate(gpus):
        if not isinstance(gpu, Mapping) or set(gpu) != GPU_FIELDS:
            errors.append(f"scheduler.host_resource_snapshot.gpu[{index}].fields")
            continue
        if not _safe_id(gpu.get("uuid")) or not _safe_id(gpu.get("pci_bus_id")) or not isinstance(gpu.get("name"), str) or not gpu.get("name"):
            errors.append(f"scheduler.host_resource_snapshot.gpu[{index}].identity")
        for key in ("index", "total_mib", "used_mib", "free_mib"):
            if type(gpu.get(key)) is not int or gpu.get(key) < 0:
                errors.append(f"scheduler.host_resource_snapshot.gpu[{index}].{key}")
        if type(gpu.get("utilization")) not in {int, float} or not math.isfinite(float(gpu.get("utilization", -1))) or not 0 <= float(gpu.get("utilization", -1)) <= 100:
            errors.append(f"scheduler.host_resource_snapshot.gpu[{index}].utilization")
        if gpu.get("free_mib") != gpu.get("total_mib", 0) - gpu.get("used_mib", 0):
            errors.append(f"scheduler.host_resource_snapshot.gpu[{index}].free_mib")
        if isinstance(gpu.get("uuid"), str):
            if gpu["uuid"] in gpu_by_uuid:
                errors.append(f"scheduler.host_resource_snapshot.gpu[{index}].duplicate_uuid")
            gpu_by_uuid[gpu["uuid"]] = gpu
    processes = resources.get("gpu_processes")
    if not isinstance(processes, list):
        errors.append("scheduler.host_resource_snapshot.resources.gpu_processes")
        processes = []
    for index, process in enumerate(processes):
        if not isinstance(process, Mapping) or set(process) != GPU_PROCESS_FIELDS:
            errors.append(f"scheduler.host_resource_snapshot.gpu_process[{index}].fields")
            continue
        if process.get("uuid") not in gpu_by_uuid or type(process.get("pid")) is not int or process.get("pid") < 1 or not _finite_nonnegative(process.get("used_mib")):
            errors.append(f"scheduler.host_resource_snapshot.gpu_process[{index}].binding")

    request = expected_resources
    cpu_ok = resources.get("cpu_count", 0) >= 1 and request.get("cpu_cores", 0) <= max(1, math.floor(resources.get("cpu_count", 0) * 0.8))
    ram_ok = resources.get("ram_available_mib", 0) >= request.get("ram_mib", 0)
    io_ok = float(resources.get("io_capacity", 0)) >= float(request.get("io_weight", 0))
    disk_ok = resources.get("disk_free_bytes", 0) >= MIN_FREE_DISK_BYTES
    selected_uuid = reservation.get("selected_gpu_uuid")
    if request.get("gpu_peak_mib", 0):
        gpu_ok = selected_uuid in gpu_by_uuid and gpu_by_uuid[selected_uuid].get("free_mib", -1) >= request.get("gpu_peak_mib", 0)
    else:
        gpu_ok = selected_uuid is None
    capacity = {
        "cpu": cpu_ok,
        "ram": ram_ok,
        "io": io_ok,
        "disk": disk_ok,
        "gpu": gpu_ok,
        "pass": bool(cpu_ok and ram_ok and io_ok and disk_ok and gpu_ok),
        "selected_gpu_uuid": selected_uuid,
    }
    if not capacity["pass"]:
        errors.append("scheduler.host_resource_snapshot.capacity_insufficient")
    return len(errors) == start, {
        "path": str(_absolute(path)),
        "sha256": digest,
        "identity": actual or {},
        "snapshot_id": value.get("snapshot_id"),
        "host": dict(host),
        "resources": dict(resources),
    }, capacity


def _validate_counterparty(
    value: Any,
    *,
    role: str,
    expected_path: Path,
    expected_identity: Mapping[str, Any] | None,
    pair_id: Any,
    attempt_id: Any,
    nonce: Any,
    binding_sha256: Any,
    pair_commitment_sha256: Any,
    errors: list[str],
) -> bool:
    start = len(errors)
    if not isinstance(value, Mapping) or set(value) != COUNTERPARTY_FIELDS:
        errors.append(f"{role}.counterparty.fields")
        return False
    expected = {
        "path": str(_absolute(expected_path)),
        "identity": dict(expected_identity or {}),
        "pair_id": pair_id,
        "attempt_id": attempt_id,
        "nonce": nonce,
        "binding_sha256": binding_sha256,
        "pair_commitment_sha256": pair_commitment_sha256,
    }
    if dict(value) != expected:
        errors.append(f"{role}.counterparty.value")
    return len(errors) == start


def _validate_root(
    value: Mapping[str, Any] | None,
    *,
    root: Path,
    path: Path,
    actual_identity: Mapping[str, Any] | None,
    anchor: Mapping[str, Any],
    details: Mapping[str, Any],
    scheduler_path: Path,
    scheduler_identity: Mapping[str, Any] | None,
    trusted_key_path: Path | None,
    key_ref: dict[str, Any],
    errors: list[str],
) -> dict[str, Any]:
    start = len(errors)
    if not isinstance(value, Mapping):
        errors.append("root.missing_or_not_object")
        return {"valid": False, "identity": actual_identity}
    if set(value) != RECEIPT_FIELDS:
        errors.append("root.fields")
    for key, expected in {
        "schema": ROOT_RECEIPT_SCHEMA,
        "receipt_id": ROOT_RECEIPT_ID,
        "kind": "fresh_root",
        "status": "fresh_root_issued",
        "synthetic": False,
        "attempt_id": ATTEMPT_ID,
    }.items():
        if value.get(key) != expected:
            errors.append(f"root.{key}")
    pair_id = value.get("pair_id")
    nonce = value.get("nonce")
    if not _safe_id(pair_id):
        errors.append("root.pair_id")
    if not _nonce(nonce):
        errors.append("root.nonce")
    expected_binding = _expected_binding(anchor, details, root, nonce) if _nonce(nonce) else {}
    binding_ok, binding = _validate_binding(value.get("binding"), expected_binding, "root.binding", errors)
    if value.get("binding_sha256") != canonical_digest(binding) or not _sha(value.get("binding_sha256")):
        errors.append("root.binding_sha256")
    _external_path(value.get("receipt_identity", {}).get("path") if isinstance(value.get("receipt_identity"), Mapping) else None, expected=path, label="root.receipt", errors=errors)
    _validate_identity_owner(
        value.get("receipt_identity"),
        actual_identity,
        label="root.receipt_identity",
        expected_kind="file",
        expected_owner_uid=0,
        errors=errors,
    )
    namespace = value.get("fresh_root")
    if not isinstance(namespace, Mapping) or set(namespace) != ROOT_NAMESPACE_FIELDS:
        errors.append("root.fresh_root.fields")
    else:
        expected_namespace = _mapping(expected_binding.get("attempt_namespace"))
        for key, expected in {
            "namespace": expected_namespace.get("namespace"),
            "namespace_path": expected_namespace.get("namespace_path"),
            "fresh": True,
            "reused": False,
            "overwrite_allowed": False,
            "resume_allowed": False,
            "historical_trace_reuse": False,
            "entry_count": 0,
            "single_use": True,
            "consumed": False,
        }.items():
            if namespace.get(key) != expected:
                errors.append(f"root.fresh_root.{key}")
        namespace_path = Path(str(namespace.get("namespace_path")))
        actual_namespace, namespace_error = _lstat_identity(namespace_path, label="F4 fresh attempt namespace", kinds={"directory"})
        if namespace_error:
            errors.append(f"root.fresh_root.namespace_path.{namespace_error}")
        _validate_identity_owner(
            namespace.get("path_identity"),
            actual_namespace,
            label="root.fresh_root.path_identity",
            expected_kind="directory",
            expected_owner_uid=0,
            errors=errors,
        )
        if actual_namespace is not None:
            entry_count, entry_error = _directory_entry_count(
                namespace_path,
                actual_namespace,
                label="F4 fresh attempt namespace",
            )
            if entry_error:
                errors.append(f"root.fresh_root.namespace_path.{entry_error}")
            elif entry_count != 0:
                errors.append("root.fresh_root.namespace_not_empty")
    core = _receipt_core(value)
    receipt_digest = canonical_digest(core)
    if value.get("receipt_digest_sha256") != receipt_digest or not _sha(value.get("receipt_digest_sha256")):
        errors.append("root.receipt_digest_sha256")
    producer_ok, producer = _validate_producer(
        value.get("producer_attestation"),
        role="root",
        receipt_identity=actual_identity,
        core=core,
        trusted_key_path=trusted_key_path,
        key_ref=key_ref,
        errors=errors,
    )
    replay_ok, replay = _validate_replay_guard(
        value.get("replay_guard"),
        role="root",
        pair_id=pair_id,
        attempt_id=value.get("attempt_id"),
        nonce=nonce,
        producer_uid=producer.get("producer_uid"),
        errors=errors,
    )
    _side_effects_closed(value.get("side_effects"), "root.side_effects", errors)
    return {
        "valid": len(errors) == start,
        "binding": binding,
        "binding_sha256": value.get("binding_sha256"),
        "receipt_digest_sha256": value.get("receipt_digest_sha256"),
        "pair_id": pair_id,
        "attempt_id": value.get("attempt_id"),
        "nonce": nonce,
        "identity": dict(actual_identity or {}),
        "producer_authenticated": producer_ok,
        "producer": producer,
        "replay_guard_valid": replay_ok,
        "replay_guard": replay,
        "fresh_root": dict(_mapping(namespace)),
        "counterparty": dict(_mapping(value.get("counterparty"))),
        "pair_commitment_sha256": value.get("pair_commitment_sha256"),
        "binding_ok": binding_ok,
    }


def _validate_scheduler(
    value: Mapping[str, Any] | None,
    *,
    root: Path,
    path: Path,
    actual_identity: Mapping[str, Any] | None,
    anchor: Mapping[str, Any],
    details: Mapping[str, Any],
    root_path: Path,
    root_identity: Mapping[str, Any] | None,
    trusted_key_path: Path | None,
    key_ref: dict[str, Any],
    errors: list[str],
) -> dict[str, Any]:
    start = len(errors)
    if not isinstance(value, Mapping):
        errors.append("scheduler.missing_or_not_object")
        return {"valid": False, "identity": actual_identity}
    if set(value) != RECEIPT_FIELDS:
        errors.append("scheduler.fields")
    for key, expected in {
        "schema": SCHEDULER_RECEIPT_SCHEMA,
        "receipt_id": SCHEDULER_RECEIPT_ID,
        "kind": "scheduler_host_io",
        "status": "scheduler_host_io_reserved",
        "synthetic": False,
        "attempt_id": ATTEMPT_ID,
    }.items():
        if value.get(key) != expected:
            errors.append(f"scheduler.{key}")
    pair_id = value.get("pair_id")
    nonce = value.get("nonce")
    if not _safe_id(pair_id):
        errors.append("scheduler.pair_id")
    if not _nonce(nonce):
        errors.append("scheduler.nonce")
    expected_binding = _expected_binding(anchor, details, root, nonce) if _nonce(nonce) else {}
    binding_ok, binding = _validate_binding(value.get("binding"), expected_binding, "scheduler.binding", errors)
    if value.get("binding_sha256") != canonical_digest(binding) or not _sha(value.get("binding_sha256")):
        errors.append("scheduler.binding_sha256")
    _external_path(value.get("receipt_identity", {}).get("path") if isinstance(value.get("receipt_identity"), Mapping) else None, expected=path, label="scheduler.receipt", errors=errors)
    _validate_identity_owner(
        value.get("receipt_identity"),
        actual_identity,
        label="scheduler.receipt_identity",
        expected_kind="file",
        expected_owner_uid=None,
        errors=errors,
    )
    core = _receipt_core(value)
    receipt_digest = canonical_digest(core)
    if value.get("receipt_digest_sha256") != receipt_digest or not _sha(value.get("receipt_digest_sha256")):
        errors.append("scheduler.receipt_digest_sha256")
    producer_ok, producer = _validate_producer(
        value.get("producer_attestation"),
        role="scheduler",
        receipt_identity=actual_identity,
        core=core,
        trusted_key_path=trusted_key_path,
        key_ref=key_ref,
        errors=errors,
    )
    reservation = value.get("host_io_reservation")
    expected_resources = _mapping(anchor.get("resource_request"))
    if not isinstance(reservation, Mapping) or set(reservation) != RESERVATION_FIELDS:
        errors.append("scheduler.host_io_reservation.fields")
        reservation = {}
    else:
        for key, expected in {
            "owner_role": "scheduler",
            "reservation_active": True,
            "scheduler_owned_host_io_verified": True,
            "resource_request": dict(expected_resources),
            "io_weight": expected_resources.get("io_weight"),
            "single_use": True,
            "consumed": False,
        }.items():
            if reservation.get(key) != expected:
                errors.append(f"scheduler.host_io_reservation.{key}")
        if not _safe_id(reservation.get("reservation_id")) or not _safe_id(reservation.get("snapshot_id")):
            errors.append("scheduler.host_io_reservation.identifiers")
        if not _finite_nonnegative(reservation.get("owned_io_weight")) or not _finite_nonnegative(reservation.get("io_capacity")):
            errors.append("scheduler.host_io_reservation.capacity")
        elif float(reservation["owned_io_weight"]) < float(expected_resources.get("io_weight") or 0) or float(reservation["io_capacity"]) < float(reservation["owned_io_weight"]):
            errors.append("scheduler.host_io_reservation.capacity_headroom")
        if not isinstance(reservation.get("filesystem"), str) or not reservation.get("filesystem"):
            errors.append("scheduler.host_io_reservation.filesystem")
        reservation_path = Path(str(reservation.get("reservation_path"))) if isinstance(reservation.get("reservation_path"), str) else Path(".")
        _external_path(value=reservation.get("reservation_path"), expected=reservation_path, label="scheduler.reservation", errors=errors)
        actual_reservation, reservation_error = _lstat_identity(reservation_path, label="scheduler reservation", kinds={"file"})
        if reservation_error:
            errors.append(f"scheduler.host_io_reservation.path.{reservation_error}")
        _validate_identity_owner(
            reservation.get("path_identity"),
            actual_reservation,
            label="scheduler.host_io_reservation.path_identity",
            expected_kind="file",
            expected_owner_uid=producer.get("producer_uid") if isinstance(producer.get("producer_uid"), int) else None,
            errors=errors,
        )
    replay_ok, replay = _validate_replay_guard(
        value.get("replay_guard"),
        role="scheduler",
        pair_id=pair_id,
        attempt_id=value.get("attempt_id"),
        nonce=nonce,
        producer_uid=producer.get("producer_uid"),
        errors=errors,
    )
    snapshot_ok, snapshot, capacity = _validate_snapshot(
        value.get("host_resource_snapshot"),
        pair_id=pair_id,
        attempt_id=value.get("attempt_id"),
        nonce=nonce,
        reservation=reservation,
        expected_resources=expected_resources,
        errors=errors,
    )
    _side_effects_closed(value.get("side_effects"), "scheduler.side_effects", errors)
    return {
        "valid": len(errors) == start,
        "binding": binding,
        "binding_sha256": value.get("binding_sha256"),
        "receipt_digest_sha256": value.get("receipt_digest_sha256"),
        "pair_id": pair_id,
        "attempt_id": value.get("attempt_id"),
        "nonce": nonce,
        "identity": dict(actual_identity or {}),
        "producer_authenticated": producer_ok,
        "producer": producer,
        "replay_guard_valid": replay_ok,
        "replay_guard": replay,
        "host_resource_snapshot_valid": snapshot_ok,
        "host_resource_snapshot": snapshot,
        "capacity": capacity,
        "host_io_reservation": dict(reservation),
        "counterparty": dict(_mapping(value.get("counterparty"))),
        "pair_commitment_sha256": value.get("pair_commitment_sha256"),
        "binding_ok": binding_ok,
    }


def _pair_commitment(root_projection: Mapping[str, Any], scheduler_projection: Mapping[str, Any]) -> str:
    reservation = _mapping(scheduler_projection.get("host_io_reservation"))
    snapshot = _mapping(scheduler_projection.get("host_resource_snapshot"))
    return canonical_digest(
        {
            "pair_id": root_projection.get("pair_id"),
            "attempt_id": root_projection.get("attempt_id"),
            "nonce": root_projection.get("nonce"),
            "root_binding_sha256": root_projection.get("binding_sha256"),
            "scheduler_binding_sha256": scheduler_projection.get("binding_sha256"),
            "binding": root_projection.get("binding", {}),
            "root_receipt_identity": root_projection.get("identity", {}),
            "scheduler_receipt_identity": scheduler_projection.get("identity", {}),
            "root_namespace_identity": _mapping(root_projection.get("fresh_root")).get("path_identity", {}),
            "scheduler_reservation_identity": reservation.get("path_identity", {}),
            "root_replay_guard_sha256": _mapping(root_projection.get("replay_guard")).get("sha256"),
            "scheduler_replay_guard_sha256": _mapping(scheduler_projection.get("replay_guard")).get("sha256"),
            "host_resource_snapshot_sha256": snapshot.get("sha256"),
            "resource_request": reservation.get("resource_request"),
            "selected_gpu_uuid": reservation.get("selected_gpu_uuid"),
        }
    )


def _authorization() -> dict[str, Any]:
    return {
        "diagnostic_only": True,
        "non_authorizing": True,
        "external_receipts_verified": False,
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
        "replay_guard_consumed": False,
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
    root_key_path: str | Path | None = None,
    scheduler_key_path: str | Path | None = None,
) -> dict[str, Any]:
    root = _absolute(root)
    anchor, anchor_ref, anchor_details, anchor_payload, anchor_errors = _load_anchor(root, anchor_path)
    root_file = _absolute(root_receipt_path or DEFAULT_ROOT_RECEIPT)
    scheduler_file = _absolute(scheduler_receipt_path or DEFAULT_SCHEDULER_RECEIPT)
    root_key = _absolute(root_key_path) if root_key_path is not None else None
    scheduler_key = _absolute(scheduler_key_path) if scheduler_key_path is not None else None
    root_receipt, root_ref, root_error = _read_json(root_file, root=root, label="F4 external fresh-root receipt")
    scheduler_receipt, scheduler_ref, scheduler_error = _read_json(scheduler_file, root=root, label="F4 external scheduler receipt")
    root_identity = root_ref.get("identity") if root_ref.get("exists") else None
    scheduler_identity = scheduler_ref.get("identity") if scheduler_ref.get("exists") else None
    errors: list[str] = list(anchor_errors)
    root_key_ref = {"configured": root_key is not None, "path": str(root_key) if root_key else None, "exists": False, "sha256": None, "error": "not_configured" if root_key is None else None}
    scheduler_key_ref = {"configured": scheduler_key is not None, "path": str(scheduler_key) if scheduler_key else None, "exists": False, "sha256": None, "error": "not_configured" if scheduler_key is None else None}
    root_projection = _validate_root(
        root_receipt if root_ref.get("exists") else None,
        root=root,
        path=root_file,
        actual_identity=root_identity,
        anchor=anchor,
        details=anchor_details,
        scheduler_path=scheduler_file,
        scheduler_identity=scheduler_identity,
        trusted_key_path=root_key,
        key_ref=root_key_ref,
        errors=errors,
    )
    scheduler_projection = _validate_scheduler(
        scheduler_receipt if scheduler_ref.get("exists") else None,
        root=root,
        path=scheduler_file,
        actual_identity=scheduler_identity,
        anchor=anchor,
        details=anchor_details,
        root_path=root_file,
        root_identity=root_identity,
        trusted_key_path=scheduler_key,
        key_ref=scheduler_key_ref,
        errors=errors,
    )
    pair_checks = {
        "pair_id_equal": bool(root_projection.get("pair_id") and root_projection.get("pair_id") == scheduler_projection.get("pair_id")),
        "attempt_id_equal": bool(root_projection.get("attempt_id") and root_projection.get("attempt_id") == scheduler_projection.get("attempt_id") == ATTEMPT_ID),
        "nonce_equal": bool(root_projection.get("nonce") and root_projection.get("nonce") == scheduler_projection.get("nonce") and _nonce(root_projection.get("nonce"))),
        "binding_sha_equal": bool(root_projection.get("binding_sha256") and root_projection.get("binding_sha256") == scheduler_projection.get("binding_sha256")),
        "pair_commitment_equal": bool(root_projection.get("pair_commitment_sha256") and root_projection.get("pair_commitment_sha256") == scheduler_projection.get("pair_commitment_sha256")),
        "counterparty_cross_bound": False,
        "pair_commitment_recomputed": False,
    }
    if pair_checks["pair_id_equal"] and pair_checks["attempt_id_equal"] and pair_checks["nonce_equal"]:
        counterparty_root = _validate_counterparty(
            root_projection.get("counterparty"),
            role="root",
            expected_path=scheduler_file,
            expected_identity=scheduler_identity,
            pair_id=root_projection.get("pair_id"),
            attempt_id=root_projection.get("attempt_id"),
            nonce=root_projection.get("nonce"),
            binding_sha256=scheduler_projection.get("binding_sha256"),
            pair_commitment_sha256=root_projection.get("pair_commitment_sha256"),
            errors=errors,
        )
        counterparty_scheduler = _validate_counterparty(
            scheduler_projection.get("counterparty"),
            role="scheduler",
            expected_path=root_file,
            expected_identity=root_identity,
            pair_id=scheduler_projection.get("pair_id"),
            attempt_id=scheduler_projection.get("attempt_id"),
            nonce=scheduler_projection.get("nonce"),
            binding_sha256=root_projection.get("binding_sha256"),
            pair_commitment_sha256=scheduler_projection.get("pair_commitment_sha256"),
            errors=errors,
        )
        pair_checks["counterparty_cross_bound"] = bool(counterparty_root and counterparty_scheduler)
    if root_projection.get("valid") and scheduler_projection.get("valid"):
        recomputed = _pair_commitment(root_projection, scheduler_projection)
        pair_checks["pair_commitment_recomputed"] = bool(
            root_projection.get("pair_commitment_sha256") == recomputed
            and scheduler_projection.get("pair_commitment_sha256") == recomputed
        )
    for name, passed in pair_checks.items():
        if not passed:
            errors.append(f"pair.{name}")
    if root_error:
        errors.append(f"root_receipt:{root_error}")
    if scheduler_error:
        errors.append(f"scheduler_receipt:{scheduler_error}")
    root_present = root_ref.get("exists") is True
    scheduler_present = scheduler_ref.get("exists") is True
    if not anchor_errors and root_present and scheduler_present and not errors:
        status = STATUS_VERIFIED
    elif anchor_errors:
        status = STATUS_ANCHOR_BLOCKED
    elif not root_present or not scheduler_present:
        status = STATUS_MISSING
    else:
        status = STATUS_INVALID
    blockers = list(dict.fromkeys(errors))
    checks = {
        "anchor_contract_valid": not anchor_errors,
        "source_claim_bound": bool(_mapping(anchor.get("source")).get("sha256")) if anchor else False,
        "source_metadata_valid": anchor_details.get("source_metadata_valid") is True,
        "current_code_hashes_valid": anchor_details.get("code_hashes_valid") is True,
        "manifest_sha_valid": anchor_details.get("manifest_sha_valid") is True,
        "argv_sha_bound": bool(
            anchor
            and _sha(anchor.get("normalized_launch_sha256"))
            and anchor.get("normalized_launch_sha256")
            == canonical_digest(anchor.get("normalized_launch"))
        ),
        "cwd_bound": bool(anchor_details.get("cwd") == str(root)),
        "attempt_namespace_template_bound": bool(anchor and _mapping(anchor.get("output_namespace")).get("namespace") == DEFAULT_OUTPUT_NAMESPACE),
        "root_receipt_present": root_present,
        "scheduler_receipt_present": scheduler_present,
        "root_receipt_external_path": bool(_external(root_file)),
        "scheduler_receipt_external_path": bool(_external(scheduler_file)),
        "root_receipt_contract_valid": bool(root_projection.get("valid")),
        "scheduler_receipt_contract_valid": bool(scheduler_projection.get("valid")),
        "root_producer_authenticated": bool(root_projection.get("producer_authenticated")),
        "scheduler_producer_authenticated": bool(scheduler_projection.get("producer_authenticated")),
        "root_replay_guard_valid": bool(root_projection.get("replay_guard_valid")),
        "scheduler_replay_guard_valid": bool(scheduler_projection.get("replay_guard_valid")),
        "root_namespace_owner_inode_bound": bool(
            root_projection.get("valid")
            and root_projection.get("fresh_root", {}).get("path_identity")
        ),
        "scheduler_reservation_owner_inode_bound": bool(
            scheduler_projection.get("valid")
            and scheduler_projection.get("host_io_reservation", {}).get("path_identity")
        ),
        "host_resource_snapshot_valid": bool(scheduler_projection.get("host_resource_snapshot_valid")),
        "resource_capacity_sufficient": bool(_mapping(scheduler_projection.get("capacity")).get("pass")),
        **pair_checks,
    }
    checks["external_intake_valid"] = bool(
        status == STATUS_VERIFIED
        and not blockers
        and all(checks[name] for name in CHECK_NAMES[:-1])
    )
    authorization = _authorization()
    authorization["external_receipts_verified"] = checks["external_intake_valid"]
    report = {
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
        "binding_contract": {
            "scope": deepcopy(_mapping(anchor.get("scope"))),
            "source": deepcopy(_mapping(anchor.get("source"))),
            "code_hashes": deepcopy(anchor_details.get("expected_code_hashes", {})),
            "normalized_launch": deepcopy(_mapping(anchor.get("normalized_launch"))),
            "normalized_launch_sha256": anchor.get("normalized_launch_sha256"),
            "cwd": anchor_details.get("cwd"),
            "attempt_id": ATTEMPT_ID,
            "attempt_namespace": DEFAULT_OUTPUT_NAMESPACE,
            "attempt_namespace_path": str(_resolve(root, DEFAULT_OUTPUT_NAMESPACE)),
            "manifest": deepcopy(anchor_details.get("expected_manifest", {})),
            "resource_request": deepcopy(_mapping(anchor.get("resource_request"))),
        },
        "current_input_observation": {
            "source": anchor_details.get("source", {}),
            "code": anchor_details.get("current_code", {}),
            "manifest": anchor_details.get("manifest", {}),
        },
        "receipts": {
            "fresh_root": root_ref,
            "scheduler_host_io": scheduler_ref,
        },
        "trusted_key_observation": {
            "root": root_key_ref,
            "scheduler": scheduler_key_ref,
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
        "authorization": authorization,
        "execution_controls": _execution_controls(),
        "next_safe_action": (
            "Keep execution blocked. Obtain producer-signed external root/scheduler receipts, one-use replay guards, trusted public keys, and a scheduler host/resource snapshot; then re-run this read-only intake. Do not hand-edit, reuse, or synthesize receipts."
        ),
    }
    return report


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
        "current_input_observation",
        "receipts",
        "trusted_key_observation",
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
    if value.get("status") not in {STATUS_ANCHOR_BLOCKED, STATUS_MISSING, STATUS_INVALID, STATUS_VERIFIED}:
        errors.append("report.status")
    authorization = _mapping(value.get("authorization"))
    expected_authorization = _authorization()
    expected_authorization["external_receipts_verified"] = bool(
        _mapping(_mapping(value.get("validation")).get("checks")).get("external_intake_valid") is True
        and value.get("status") == STATUS_VERIFIED
    )
    for key, expected in expected_authorization.items():
        if authorization.get(key) != expected:
            errors.append(f"report.authorization.{key}")
    controls = _mapping(value.get("execution_controls"))
    if controls != _execution_controls():
        errors.append("report.execution_controls")
    validation = _mapping(value.get("validation"))
    if set(validation) != {"checks", "blockers", "anchor_errors"}:
        errors.append("report.validation.fields")
    if not isinstance(validation.get("blockers"), list) or not all(isinstance(item, str) for item in validation.get("blockers", [])):
        errors.append("report.validation.blockers")
    checks = _mapping(validation.get("checks"))
    if set(checks) != set(CHECK_NAMES) or any(type(checks.get(name)) is not bool for name in CHECK_NAMES):
        errors.append("report.validation.checks")
    elif checks.get("external_intake_valid") is not bool(
        value.get("status") == STATUS_VERIFIED
        and not validation.get("blockers")
        and all(checks[name] for name in CHECK_NAMES[:-1])
    ):
        errors.append("report.validation.checks.contract_derivation")
    if value.get("status") == STATUS_VERIFIED and checks.get("external_intake_valid") is not True:
        errors.append("report.verified_without_external_intake")
    if checks.get("external_intake_valid") is True and value.get("status") != STATUS_VERIFIED:
        errors.append("report.external_intake_status_mismatch")
    if value.get("status") != STATUS_VERIFIED and not validation.get("blockers"):
        errors.append("report.blocked_without_blocker")
    if value.get("status") == STATUS_VERIFIED and validation.get("blockers"):
        errors.append("report.verified_with_blockers")
    if authorization.get("launch_allowed") is not False or authorization.get("solver_authorized") is not False or authorization.get("gpu_authorized") is not False:
        errors.append("report.authorization.execution_closed")
    return errors


def write_report(value: Mapping[str, Any], output: str | Path) -> Path:
    errors = validate_report(value)
    if errors:
        raise ValueError("refusing to write invalid F4 external receipt intake report: " + ", ".join(errors))
    path = Path(output).resolve()
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return path


def write_zh_cn(value: Mapping[str, Any], output: str | Path) -> Path:
    errors = validate_report(value)
    if errors:
        raise ValueError("refusing to write invalid F4 external receipt intake markdown: " + ", ".join(errors))
    path = Path(output).resolve()
    if path.exists():
        raise FileExistsError(path)
    blockers = value["validation"]["blockers"]
    lines = [
        "# F4 Tallwall120 material external receipt intake v1",
        "",
        f"- 状态：`{value['status']}`",
        "- 诊断性、非授权；`launch_allowed=false`、`solver_authorized=false`、`gpu_authorized=false`、`credit=0`。",
        "- 本 intake 只验证外部 producer 签名、单次 replay guard、root fresh namespace、scheduler host-I/O reservation 及 host/resource snapshot；不创建或消费任何资源。",
        "",
        "## 当前 blocker",
        "",
    ]
    lines.extend(f"- `{item}`" for item in blockers)
    lines.extend(
        [
            "",
            "## 安全边界",
            "",
            "- 当前没有真实 external receipt、trusted producer public key 或 replay guard，因此保持 fail-closed。",
            "- 不启动 solver、worker、native、GPU 或 queue；不修改 registry、ledger、denominator、gate、completion、PLAN 或历史 receipt。",
            "",
            "## 下一步",
            "",
            "请由真实 root namespace producer 与 scheduler producer 写出带签名、一次性 replay guard 和 host/resource snapshot 的 receipt；禁止手工编辑、复用或合成 receipt，然后重新运行只读 intake。",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _load_report(path: Path) -> dict[str, Any]:
    raw, _, error = _stable_bytes(path, label="F4 external receipt intake report", limit=MAX_JSON_BYTES)
    if error or raw is None:
        raise ValueError(f"cannot read report: {error or 'missing'}")
    return strict_json_object(raw, label="F4 external receipt intake report", max_bytes=MAX_JSON_BYTES)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=LAB_ROOT)
    parser.add_argument("--anchor", type=Path, default=None)
    parser.add_argument("--root-receipt", type=Path, default=None)
    parser.add_argument("--scheduler-receipt", type=Path, default=None)
    parser.add_argument("--root-key", type=Path, default=None)
    parser.add_argument("--scheduler-key", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--zh-output", type=Path, default=DEFAULT_ZH_REPORT)
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
        root_key_path=args.root_key,
        scheduler_key_path=args.scheduler_key,
    )
    write_report(report, args.output)
    write_zh_cn(report, args.zh_output)
    print(json.dumps({"status": report["status"], "report": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
