#!/usr/bin/env python3
"""Build a bounded, non-authorizing F4 Tallwall120 material readiness view.

The projection consumes exactly seven checked-in JSON receipts.  It never
follows a receipt's artifact references and never opens an HDF5, BI4, solver,
native, queue, registry, ledger, or runtime file.  The result is deliberately
fail-closed: it records the current source/path drift and missing authority,
but it can never mint launch authority, qualification, or credit.
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
import sys
from typing import Any, Mapping


LAB_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_INPUT_PATHS: dict[str, Path] = {
    "coarse_proposal": Path("reports/F4-TALLWALL120-MATERIAL-COARSE-PROPOSAL-2026-09-28.json"),
    "root_scheduler": Path("reports/F4-TALLWALL120-MATERIAL-ROOT-SCHEDULER-INTAKE-V1-2026-09-28.json"),
    "source_drift": Path("reports/F4-TALLWALL120-MATERIAL-SOURCE-DRIFT-RECONCILIATION-V1-2026-09-28.json"),
    "receipt_consistency": Path("reports/F4-TALLWALL120-MATERIAL-RECEIPT-CONSISTENCY-AUDIT-2026-09-28.json"),
    "terminal_evidence": Path("reports/F4-TALLWALL120-MATERIAL-TERMINAL-EVIDENCE-INTAKE-V1-2026-09-28.json"),
    "sidecar_matrix": Path("reports/F4-TALLWALL120-MATERIAL-SIDECAR-MATRIX-CONTRACT-V1-2026-09-28.json"),
    "t2_readiness": Path("reports/F4-TALLWALL120-T2-READINESS-AUDIT-2026-09-28.json"),
}

INPUT_RECORD_IDS = {
    "coarse_proposal": "f4-tallwall120-material-coarse-proposal-2026-09-28",
    "root_scheduler": "f4-tallwall120-material-root-scheduler-intake-v1",
    "source_drift": "f4-tallwall120-material-source-drift-reconciliation-v1",
    "receipt_consistency": "f4-tallwall120-material-receipt-consistency-audit-2026-09-28",
    "terminal_evidence": "f4-tallwall120-material-terminal-evidence-intake-v1",
    "sidecar_matrix": "f4-tallwall120-material-sidecar-matrix-contract-v1",
    "t2_readiness": "f4-tallwall120-t2-readiness-audit-2026-09-28",
}

INPUT_SCHEMAS = {
    "coarse_proposal": "core.material.f4.tallwall120.coarse_proposal.v1",
    "root_scheduler": "core.material.f4.tallwall120.root_scheduler_intake.v1",
    "source_drift": "core.material.f4.tallwall120.source_drift_reconciliation.v1",
    "receipt_consistency": "core.material.f4.tallwall120.receipt_consistency_audit.v1",
    "terminal_evidence": "core.material.f4.tallwall120.terminal_evidence_intake.v1",
    "sidecar_matrix": "core.material.f4.tallwall120.sidecar_matrix_contract.v1",
    "t2_readiness": "core.material.f4.tallwall120.t2_readiness_audit.v1",
}

DEFAULT_REPORT = Path(
    "reports/F4-TALLWALL120-MATERIAL-READINESS-PROJECTION-V1-2026-09-28.json"
)
DEFAULT_MARKDOWN = Path(
    "reports/F4-TALLWALL120-MATERIAL-READINESS-PROJECTION-V1-2026-09-28.zh-CN.md"
)

REPORT_SCHEMA = "core.material.f4.tallwall120.material_readiness_projection.v1"
REPORT_RECORD_ID = "f4-tallwall120-material-readiness-projection-v1-2026-09-28"
STATUS = "blocked_fail_closed"

COARSE_SCHEMA = "core.material.f4.tallwall120.coarse_proposal.v1"
ROOT_SCHEMA = "core.material.f4.tallwall120.root_scheduler_intake.v1"
DRIFT_SCHEMA = "core.material.f4.tallwall120.source_drift_reconciliation.v1"
CONSISTENCY_SCHEMA = "core.material.f4.tallwall120.receipt_consistency_audit.v1"
TERMINAL_SCHEMA = "core.material.f4.tallwall120.terminal_evidence_intake.v1"
MATRIX_SCHEMA = "core.material.f4.tallwall120.sidecar_matrix_contract.v1"
T2_SCHEMA = "core.material.f4.tallwall120.t2_readiness_audit.v1"

SCOPE_ID = "F4_resting_pool_laminar_tallwall120_x_v1"
CASE_ID = "F4_resting_pool_laminar_tallwall120_x_v1_DEV_07"
FAMILY = "F4"
CASE_LABEL = "Tallwall120"
TARGET_SOURCE_PATH = (
    "campaigns/core-v1/cfd/f4-tallwall120-production-archives-v2/"
    "f4-tallwall120-production-dev-07/product/trajectory.h5"
)
COLLECTION_SOURCE_PATH = (
    "campaigns/core-v1/cfd/f4-tallwall120-production-archives-v1/"
    "f4-tallwall120-production-dev-07/product/trajectory.h5"
)
SOURCE_SHA256 = "6ae8ca7062e1fa15779fc9ad491d1117455700315c6a1ef4a12326458f0976ae"
SOURCE_BYTES = 2_067_911_708
COLLECTION_MANIFEST_PATH = (
    "campaigns/core-v1/cfd/f4-tallwall120-production-root-v1/"
    "collection-refresh-terminal32-formal-v1.json"
)
COLLECTION_MANIFEST_SHA256 = "808fe201c4df28f2be9b48a514f338689c38bcb96db0b0c0590946b79fb9ad09"
FRAMES = 218
TRANSITIONS = 217
TIME_START_S = 0.0
NATIVE_WINDOW_S = 4.340002980805959
TIME_END_S = NATIVE_WINDOW_S
REQUIRED_EVENT_WINDOW_S = 8.68
Q = 0.23437500000000008
DP_M = 0.0075
NEIGHBOUR_VARIANT = "baseline24"
SEEDS = 512
SUBSTEPS = 2
DIAGNOSTIC_Q = 0.5
DIAGNOSTIC_UNKNOWN_FRACTION = 1.0
DIAGNOSTIC_RELIABLE_COVERAGE = 0.0
MATRIX_CASE_COUNT = 32

MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_JSON_DEPTH = 64
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
O_NOFOLLOW = getattr(os, "O_NOFOLLOW", None)
O_DIRECTORY = getattr(os, "O_DIRECTORY", None)
O_CLOEXEC = getattr(os, "O_CLOEXEC", None)

# These names are authorization or mutation boundaries.  The seven inputs are
# allowed to contain ordinary observations such as ``sidecar_present`` and
# ``mass_closed``; only a promoted authority flag or non-zero mutation is
# rejected here.
PROMOTION_BOOL_KEYS = {
    "formal",
    "formal_eligible",
    "formal_admission",
    "T1",
    "T2",
    "T2_macro",
    "T2_path",
    "qualification",
    "launch_admitted",
    "worker_launch_authorized",
    "runtime_authorized",
    "authorized_one_cpu_only",
    "actual_sidecar_execution_allowed",
    "sidecar_executed",
    "material_sidecar_present",
    "reader_formal_eligible",
    "readiness_pass",
    "matrix_ready",
}
PROMOTION_INT_KEYS = {
    "credit",
    "qualification_credit",
    "T2_credit",
    "formal_credit",
}


class F4MaterialReadinessProjectionError(ValueError):
    """A bounded input, report, or output boundary is invalid."""

    def __init__(self, message: str, *, code: str = "invalid_projection_input") -> None:
        super().__init__(message)
        self.code = code


def _fail(message: str, *, code: str = "invalid_projection_input") -> None:
    raise F4MaterialReadinessProjectionError(message, code=code)


def _require(condition: bool, message: str, *, code: str = "invalid_projection_input") -> None:
    if not condition:
        _fail(message, code=code)


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail(f"duplicate JSON object key: {key}", code="duplicate_json_key")
        result[key] = value
    return result


def _reject_constant(token: str) -> Any:
    _fail(f"non-standard JSON constant is not permitted: {token}", code="non_strict_json")


def _parse_float(token: str) -> float:
    value = float(token)
    if not math.isfinite(value):
        _fail(f"non-finite JSON number is not permitted: {token}", code="non_strict_json")
    return value


def _parse_int(token: str) -> int:
    digits = token[1:] if token.startswith("-") else token
    if len(digits) > 128:
        _fail("JSON integer exceeds the bounded precision limit", code="oversize_number")
    return int(token)


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


def _inode_identity(value: os.stat_result) -> tuple[int, int, int]:
    """Return the stable identity fields used while a descriptor is held."""

    return value.st_dev, value.st_ino, value.st_mode


def _display_path(path: Path) -> str:
    absolute = Path(os.path.abspath(os.fspath(path)))
    try:
        return absolute.relative_to(LAB_ROOT).as_posix()
    except ValueError:
        return absolute.as_posix()


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _canonical_path(
    value: str | Path,
    *,
    suffix: str | None = None,
    scope: str = "lab",
) -> Path:
    raw = os.fspath(value)
    _require(isinstance(raw, str) and raw and "\x00" not in raw, "path is malformed", code="path_traversal")
    path = Path(raw)
    _require(path.as_posix() == raw, "path must use canonical POSIX spelling", code="path_traversal")
    _require(not any(part in {"", ".", ".."} for part in path.parts), "path contains traversal components", code="path_traversal")
    lab_root = Path(os.path.abspath(os.fspath(LAB_ROOT)))
    target = path if path.is_absolute() else lab_root / path
    target = Path(os.path.abspath(os.fspath(target)))
    _require(_path_is_within(target, lab_root), "path is outside the checked-in lab root", code="path_scope")
    if scope == "reports":
        reports_root = lab_root / "reports"
        _require(_path_is_within(target, reports_root), "path is outside the fixed reports directory", code="path_scope")
    else:
        _require(scope == "lab", f"unknown path scope: {scope}", code="path_scope")
    if suffix is not None:
        _require(target.suffix == suffix, f"path must end in {suffix}", code="path_suffix")
    return target


def _safe_open_flags(base: int, *, directory: bool = False) -> int:
    _require(O_NOFOLLOW is not None, "platform lacks O_NOFOLLOW", code="unsupported_platform")
    _require(O_CLOEXEC is not None, "platform lacks O_CLOEXEC", code="unsupported_platform")
    flags = base | O_NOFOLLOW | O_CLOEXEC
    if directory:
        _require(O_DIRECTORY is not None, "platform lacks O_DIRECTORY", code="unsupported_platform")
        flags |= O_DIRECTORY
    return flags


def _open_directory_fd(path: Path, *, label: str) -> int:
    """Open every directory component from / with held no-follow descriptors."""

    absolute = Path(os.path.abspath(os.fspath(path)))
    _require(absolute.is_absolute(), f"{label} must be absolute", code="path_scope")
    descriptor: int | None = None
    success = False
    try:
        descriptor = os.open(os.sep, _safe_open_flags(os.O_RDONLY, directory=True))
        for component in absolute.parts[1:]:
            child = os.open(
                component,
                _safe_open_flags(os.O_RDONLY, directory=True),
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = child
            info = os.fstat(descriptor)
            _require(stat.S_ISDIR(info.st_mode), f"{label} contains a non-directory component", code="not_directory")
        success = True
        return descriptor
    except F4MaterialReadinessProjectionError:
        raise
    except OSError as error:
        _fail(f"{label} cannot be opened without following symlinks", code="safe_open")
        raise AssertionError from error
    finally:
        if descriptor is not None and not success:
            os.close(descriptor)


def _read_fd_bounded(descriptor: int, *, label: str, max_bytes: int = MAX_JSON_BYTES) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        block = os.read(descriptor, min(1024 * 1024, max_bytes + 1 - total))
        if not block:
            break
        total += len(block)
        _require(total <= max_bytes, f"{label} exceeds the bounded JSON limit", code="oversize")
        chunks.append(block)
    return b"".join(chunks)


def _check_json_depth(value: Any, *, label: str) -> None:
    pending: list[tuple[Any, int]] = [(value, 0)]
    while pending:
        current, depth = pending.pop()
        _require(depth <= MAX_JSON_DEPTH, f"{label} exceeds the JSON nesting limit", code="json_depth")
        if isinstance(current, dict):
            pending.extend((child, depth + 1) for child in current.values())
        elif isinstance(current, list):
            pending.extend((child, depth + 1) for child in current)


def _read_bounded_json(
    path: str | Path,
    *,
    label: str,
    scope: str = "lab",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read one regular JSON file with held no-follow descriptors and double-read binding."""

    target = _canonical_path(path, suffix=".json", scope=scope)
    parent_fd = _open_directory_fd(target.parent, label=f"{label} parent")
    descriptor: int | None = None

    try:
        before_named = os.stat(target.name, dir_fd=parent_fd, follow_symlinks=False)
        _require(stat.S_ISREG(before_named.st_mode), f"{label} must be a regular file", code="not_regular_file")
        _require(before_named.st_nlink == 1, f"{label} must have one hard link", code="hardlink")
        _require(before_named.st_size <= MAX_JSON_BYTES, f"{label} exceeds the bounded JSON limit", code="oversize")
        descriptor = os.open(
            target.name,
            _safe_open_flags(os.O_RDONLY),
            dir_fd=parent_fd,
        )
        before = os.fstat(descriptor)
        _require(
            _identity(before) == _identity(before_named),
            f"{label} changed before it was opened",
            code="input_drift",
        )
        raw = _read_fd_bounded(descriptor, label=label)
        after = os.fstat(descriptor)
        os.lseek(descriptor, 0, os.SEEK_SET)
        reread = _read_fd_bounded(descriptor, label=label)
        after_reread = os.fstat(descriptor)
        named = os.stat(target.name, dir_fd=parent_fd, follow_symlinks=False)
        raw_hash = hashlib.sha256(raw).digest()
        reread_hash = hashlib.sha256(reread).digest()
        _require(
            raw == reread
            and raw_hash == reread_hash
            and _identity(before) == _identity(after)
            and _identity(after) == _identity(after_reread)
            and _identity(after_reread) == _identity(named)
            and len(raw) == before.st_size,
            f"{label} changed while being read",
            code="input_drift",
        )
    except FileNotFoundError as error:
        _fail(f"{label} is missing: {_display_path(target)}", code="missing_input")
        raise AssertionError from error
    except F4MaterialReadinessProjectionError:
        raise
    except OSError as error:
        _fail(f"{label} could not be read safely", code="read_error")
        raise AssertionError from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(parent_fd)

    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
            parse_float=_parse_float,
            parse_int=_parse_int,
        )
    except F4MaterialReadinessProjectionError:
        raise
    except RecursionError as error:
        _fail(f"{label} exceeds the JSON nesting limit", code="json_depth")
        raise AssertionError from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        _fail(f"{label} is not strict UTF-8 JSON", code="invalid_json")
        raise AssertionError from error
    _require(isinstance(value, dict), f"{label} must be a JSON object", code="json_not_object")
    _check_json_depth(value, label=label)
    return value, {
        "path": _display_path(target),
        "bytes": len(raw),
        "sha256": raw_hash.hex(),
    }


def _write_new_regular_file(path: str | Path, payload: bytes, *, suffix: str) -> Path:
    target = _canonical_path(path, suffix=suffix, scope="reports")
    parent_fd = _open_directory_fd(target.parent, label="output parent")
    descriptor: int | None = None
    verifier: int | None = None
    try:
        descriptor = os.open(
            target.name,
            _safe_open_flags(os.O_WRONLY | os.O_CREAT | os.O_EXCL),
            0o644,
            dir_fd=parent_fd,
        )
        before = os.fstat(descriptor)
        _require(stat.S_ISREG(before.st_mode), "output is not a regular file", code="output_type")
        _require(before.st_nlink == 1, "output has multiple hard links", code="output_hardlink")
        written = 0
        while written < len(payload):
            written += os.write(descriptor, payload[written:])
        os.fsync(descriptor)
        after = os.fstat(descriptor)
        _require(after.st_nlink > 0, "output was unlinked or replaced while being written", code="output_drift")
        _require(after.st_nlink == 1, "output has multiple hard links", code="output_hardlink")
        named = os.stat(target.name, dir_fd=parent_fd, follow_symlinks=False)
        _require(
            written == len(payload)
            and _inode_identity(before) == _inode_identity(after)
            and after.st_size == len(payload)
            and _identity(after) == _identity(named),
            "output changed while being written",
            code="output_drift",
        )
        verifier = os.open(target.name, _safe_open_flags(os.O_RDONLY), dir_fd=parent_fd)
        verified = os.fstat(verifier)
        _require(
            _identity(verified) == _identity(after) and verified.st_nlink == 1,
            "output was replaced while being verified",
            code="output_drift",
        )
        verified_payload = _read_fd_bounded(verifier, label="output", max_bytes=max(MAX_JSON_BYTES, len(payload)))
        _require(
            verified_payload == payload
            and hashlib.sha256(verified_payload).digest() == hashlib.sha256(payload).digest(),
            "output content changed while being verified",
            code="output_drift",
        )
        verified_after = os.fstat(verifier)
        named_after = os.stat(target.name, dir_fd=parent_fd, follow_symlinks=False)
        _require(
            _identity(verified_after) == _identity(after)
            and _identity(verified_after) == _identity(named_after)
            and verified_after.st_nlink == 1,
            "output was replaced after verification",
            code="output_drift",
        )
    except FileExistsError as error:
        _fail(f"output already exists: {_display_path(target)}", code="output_exists")
        raise AssertionError from error
    except F4MaterialReadinessProjectionError:
        raise
    except OSError as error:
        _fail(f"output cannot be written safely: {_display_path(target)}", code="output_write")
        raise AssertionError from error
    finally:
        if verifier is not None:
            os.close(verifier)
        if descriptor is not None:
            os.close(descriptor)
        os.close(parent_fd)
    return target


def _get(value: Mapping[str, Any], path: str) -> Any:
    current: Any = value
    for component in path.split("."):
        if not isinstance(current, Mapping) or component not in current:
            _fail(f"missing field: {path}", code="schema_drift")
        current = current[component]
    return current


def _strict_equal(actual: Any, expected: Any) -> bool:
    if type(actual) is not type(expected):
        return False
    if isinstance(actual, dict):
        return (
            set(actual) == set(expected)
            and all(_strict_equal(actual[key], expected[key]) for key in expected)
        )
    if isinstance(actual, list):
        return len(actual) == len(expected) and all(
            _strict_equal(observed, reference)
            for observed, reference in zip(actual, expected)
        )
    return actual == expected


def _eq(value: Mapping[str, Any], path: str, expected: Any, *, code: str = "binding_drift") -> Any:
    actual = _get(value, path)
    _require(_strict_equal(actual, expected), f"{path} is not bound to the expected value", code=code)
    return actual


def _type(value: Any, expected: type, label: str) -> Any:
    _require(type(value) is expected, f"{label} has the wrong type", code="schema_drift")
    return value


def _sha(value: Any, label: str) -> str:
    _require(isinstance(value, str) and SHA256_RE.fullmatch(value) is not None, f"{label} is not lowercase SHA-256", code="schema_drift")
    return value


def _metadata_path(value: Any, label: str, *, suffix: str | None = None) -> str:
    _require(isinstance(value, str) and value and "\x00" not in value, f"{label} is malformed", code="path_binding")
    path = Path(value)
    _require(not path.is_absolute(), f"{label} must be repository-relative metadata", code="path_binding")
    _require(path.as_posix() == value and not any(part in {"", ".", ".."} for part in path.parts), f"{label} contains path traversal", code="path_binding")
    if suffix is not None:
        _require(path.suffix == suffix, f"{label} must end in {suffix}", code="path_binding")
    return value


def _string_list(value: Any, label: str, *, nonempty: bool = False) -> list[str]:
    _require(type(value) is list, f"{label} must be a list", code="schema_drift")
    _require(all(type(item) is str for item in value), f"{label} must contain strings", code="schema_drift")
    _require(not nonempty or bool(value), f"{label} must not be empty", code="schema_drift")
    return value


def _scan_boundary(value: Any, *, path: str = "root") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in PROMOTION_BOOL_KEYS:
                # Some historical receipts use ``qualification`` as a
                # structured zero-credit section; validate that section below
                # instead of mistaking its mapping for a promoted boolean.
                if key == "qualification" and isinstance(child, Mapping):
                    pass
                elif type(child) in {bool, int, float}:
                    _require(type(child) is bool, f"promoted boolean type: {child_path}", code="schema_drift")
                    _require(child is False, f"promoted boolean boundary: {child_path}", code="authorization_drift")
            is_credit_boundary = key in PROMOTION_INT_KEYS
            is_mutation_boundary = (
                (key.endswith("_mutation") or key.endswith("_mutations"))
                and type(child) in {int, bool, float}
            )
            if is_credit_boundary or is_mutation_boundary:
                _require(
                    (type(child) is int and child == 0)
                    if is_credit_boundary
                    else ((type(child) is int and child == 0) or (type(child) is bool and child is False)),
                    f"non-zero credit/mutation boundary: {child_path}",
                    code="schema_drift" if type(child) not in {int, bool} else ("authorization_drift" if is_credit_boundary else "side_effect_drift"),
                )
            _scan_boundary(child, path=child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _scan_boundary(child, path=f"{path}[{index}]")
    elif isinstance(value, float):
        _require(math.isfinite(value), f"non-finite value at {path}", code="non_strict_json")


def _validate_coarse(value: dict[str, Any]) -> dict[str, Any]:
    _eq(value, "schema", COARSE_SCHEMA, code="schema_drift")
    _eq(value, "status", "blocked_fail_closed", code="authorization_drift")
    _eq(value, "proposal_only", True)
    _eq(value, "diagnostic_only", True)
    _eq(value, "formal_eligible", False, code="authorization_drift")
    target = _get(value, "target")
    _type(target, dict, "coarse target")
    for path, expected in {
        "target.family": FAMILY,
        "target.case_id": CASE_ID,
        "target.physical_case_id": CASE_ID,
        "target.lineage_group_id": CASE_ID,
        "target.scope_id": SCOPE_ID,
        "target.source_hdf5": TARGET_SOURCE_PATH,
        "target.source_sha256": SOURCE_SHA256,
        "target.source_bytes": SOURCE_BYTES,
        "target.frames": FRAMES,
        "target.transitions": TRANSITIONS,
        "target.time_start_s": TIME_START_S,
        "target.time_end_s": TIME_END_S,
        "target.split": "train",
        "target.recipe_id": "F4_mdbc_laminar_nu1e6_tallwall120_v1",
        "parameter_contract.q": Q,
        "parameter_contract.dp_m": DP_M,
        "parameter_contract.native_frame_count": FRAMES,
        "parameter_contract.native_transition_count": TRANSITIONS,
        "parameter_contract.native_window_s": NATIVE_WINDOW_S,
        "parameter_contract.extension_window_s": REQUIRED_EVENT_WINDOW_S,
        "source_manifest_contract.core_collection_manifest.path": COLLECTION_MANIFEST_PATH,
        "source_manifest_contract.core_collection_manifest.sha256": COLLECTION_MANIFEST_SHA256,
        "source_manifest_contract.core_collection_manifest.case_row_declared_hdf5": COLLECTION_SOURCE_PATH,
        "source_manifest_contract.core_collection_manifest.case_row_source_sha256": SOURCE_SHA256,
        "source_manifest_contract.core_collection_manifest.requested_hdf5": TARGET_SOURCE_PATH,
        "source_manifest_contract.core_collection_manifest.exact_path_match": False,
    }.items():
        _eq(value, path, expected)
    _metadata_path(_get(value, "target.source_hdf5"), "coarse target source", suffix=".h5")
    _sha(_get(value, "target.source_sha256"), "coarse target source SHA")
    return {
        "target": target,
        "q": Q,
        "dp_m": DP_M,
        "collection_manifest_path": COLLECTION_MANIFEST_PATH,
        "collection_manifest_sha256": COLLECTION_MANIFEST_SHA256,
    }


def _validate_root(value: dict[str, Any]) -> dict[str, Any]:
    _eq(value, "schema", ROOT_SCHEMA, code="schema_drift")
    _eq(value, "status", "blocked_missing_fresh_root_scheduler_receipts", code="authorization_drift")
    for path, expected in {
        "scope.scope_id": SCOPE_ID,
        "scope.case_id": CASE_ID,
        "scope.family": FAMILY,
        "authorization.root_authorization_intake_bound": False,
        "authorization.scheduler_host_io_reservation_bound": False,
        "authorization.scheduler_owned_io_verified": False,
        "authorization.worker_launch_authorized": False,
        "authorization.formal": False,
        "authorization.T1": False,
        "authorization.T2": False,
        "authorization.qualification": False,
        "authorization.credit": 0,
        "authorization.qualification_credit": 0,
        "launch_admitted": False,
        "formal": False,
        "T1": False,
        "T2": False,
        "T2_macro": False,
        "T2_path": False,
        "qualification": False,
        "credit": 0,
        "qualification_credit": 0,
        "proposal_observation.target.source_hdf5": TARGET_SOURCE_PATH,
        "proposal_observation.target.source_sha256": SOURCE_SHA256,
        "proposal_observation.target.case_id": CASE_ID,
        "proposal_observation.target.scope_id": SCOPE_ID,
        "proposal_observation.parameter_contract.q": Q,
        "proposal_observation.parameter_contract.dp_m": DP_M,
        "proposal_observation.parameter_contract.native_frame_count": FRAMES,
        "proposal_observation.parameter_contract.native_transition_count": TRANSITIONS,
        "proposal_observation.parameter_contract.extension_window_s": REQUIRED_EVENT_WINDOW_S,
        "case_sidecar_observation.source_target.source_hdf5": TARGET_SOURCE_PATH,
        "case_sidecar_observation.source_target.source_sha256": SOURCE_SHA256,
        "case_sidecar_observation.source_target.case_id": CASE_ID,
        "case_sidecar_observation.source_target.scope_id": SCOPE_ID,
        "case_sidecar_observation.source_target.frames": FRAMES,
        "case_sidecar_observation.source_target.transitions": TRANSITIONS,
        "binding_projection.source_identity.collection.path": COLLECTION_MANIFEST_PATH,
        "binding_projection.source_identity.collection.sha256": COLLECTION_MANIFEST_SHA256,
        "binding_projection.source_identity.collection.case_id": CASE_ID,
        "binding_projection.source_identity.collection.declared_hdf5": COLLECTION_SOURCE_PATH,
        "binding_projection.source_identity.collection.declared_sha256": SOURCE_SHA256,
        "binding_projection.source_identity.archive.trajectory.path": "product/trajectory.h5",
        "binding_projection.source_identity.archive.trajectory.sha256": SOURCE_SHA256,
        "binding_projection.source_identity.archive.trajectory.bytes": SOURCE_BYTES,
        "binding_projection.source_identity.archive.identity_bound": True,
        "binding_projection.source_identity.collection.identity_bound": True,
        "binding_projection.source_identity.consistency.archives_path_binding.exact_path_match": False,
        "binding_projection.source_identity.consistency.archives_path_binding.source_sha256_match": True,
    }.items():
        _eq(value, path, expected)
    _metadata_path(_get(value, "proposal_observation.target.source_hdf5"), "root target source", suffix=".h5")
    _metadata_path(
        _get(value, "binding_projection.fresh_output_namespace.namespace"),
        "root fresh output namespace",
    )
    return {
        "status": value["status"],
        "root_authorization_intake_bound": False,
        "scheduler_host_io_reservation_bound": False,
        "scheduler_owned_io_verified": False,
        "worker_launch_authorized": False,
        "launch_admitted": False,
        "fresh_namespace": _get(value, "binding_projection.fresh_output_namespace.namespace"),
    }


def _validate_drift(value: dict[str, Any]) -> dict[str, Any]:
    _eq(value, "schema", DRIFT_SCHEMA, code="schema_drift")
    _eq(value, "status", "blocked_fail_closed", code="authorization_drift")
    _eq(value, "decision", "diagnostic_only_source_drift_reconciliation", code="authorization_drift")
    _eq(value, "scope.scope_id", SCOPE_ID)
    _eq(value, "scope.case_id", CASE_ID)
    _eq(value, "scope.family", FAMILY)
    checks = {
        "collection_row_path_exact": False,
        "collection_row_source_sha_exact": True,
        "proposal_target_exact": True,
        "reader_manifest_path_exact": True,
        "reader_manifest_sha_exact": False,
        "receipt_pair_cross_bound": False,
        "root_receipt_credible": False,
        "scheduler_receipt_credible": False,
        "diagnostic_full_event_window": False,
        "diagnostic_parameter_binding": False,
        "diagnostic_unknown_gate": False,
        "diagnostic_reliable_coverage": False,
        "diagnostic_source_path_exact": True,
        "fresh_namespace_absent": True,
        "source_sha_consistent_without_hdf5_rehash": True,
    }
    for key, expected in checks.items():
        _eq(value, f"checks.{key}", expected, code="source_drift")
    _eq(value, "authority.actual_sidecar_execution_allowed", False, code="authorization_drift")
    _eq(value, "authority.credible_fresh_root_receipt", False, code="authorization_drift")
    _eq(value, "authority.credible_scheduler_owned_io_receipt", False, code="authorization_drift")
    _eq(value, "authority.material_sidecar_present", False, code="authorization_drift")
    _eq(value, "authority.sidecar_executed", False, code="authorization_drift")
    diagnostic = _get(value, "existing_diagnostic")
    for path, expected in {
        "existing_diagnostic.case_identity.case_id": CASE_ID,
        "existing_diagnostic.case_identity.frames": FRAMES,
        "existing_diagnostic.case_identity.transitions": TRANSITIONS,
        "existing_diagnostic.case_identity.time_end_s": TIME_END_S,
        "existing_diagnostic.source.repo_relative_path": TARGET_SOURCE_PATH,
        "existing_diagnostic.source.before_sha256": SOURCE_SHA256,
        "existing_diagnostic.source.after_sha256": SOURCE_SHA256,
        "existing_diagnostic.source.before_after_match": True,
        "existing_diagnostic.parameters.q": DIAGNOSTIC_Q,
        "existing_diagnostic.parameters.dp_m": DP_M,
        "existing_diagnostic.parameters.neighbour_variant": NEIGHBOUR_VARIANT,
        "existing_diagnostic.parameters.seeds": SEEDS,
        "existing_diagnostic.parameters.substeps": SUBSTEPS,
        "existing_diagnostic.trace.frame_count": FRAMES,
        "existing_diagnostic.trace.transition_count": TRANSITIONS,
        "existing_diagnostic.trace.event_window_complete": False,
        "existing_diagnostic.trace.event_window_status": "right_censored_or_unresolved",
        "existing_diagnostic.trace.unknown_fraction_max": DIAGNOSTIC_UNKNOWN_FRACTION,
        "existing_diagnostic.trace.common_reliable_path_coverage": DIAGNOSTIC_RELIABLE_COVERAGE,
        "existing_diagnostic.trace.unknown_gate_pass": False,
        "existing_diagnostic.decision.T1": False,
        "existing_diagnostic.decision.T2": False,
        "existing_diagnostic.decision.credit": 0,
        "existing_diagnostic.decision.formal_admission": False,
    }.items():
        _eq(value, path, expected, code="source_drift")
    _string_list(_get(value, "blockers"), "source-drift blockers", nonempty=True)
    return {
        "checks": checks,
        "blockers": list(_get(value, "blockers")),
        "diagnostic_q": DIAGNOSTIC_Q,
        "diagnostic_event_window_complete": False,
        "diagnostic_event_window_status": "right_censored_or_unresolved",
        "diagnostic_unknown_fraction_max": DIAGNOSTIC_UNKNOWN_FRACTION,
        "diagnostic_reliable_path_coverage": DIAGNOSTIC_RELIABLE_COVERAGE,
    }


def _validate_consistency(value: dict[str, Any]) -> dict[str, Any]:
    _eq(value, "schema", CONSISTENCY_SCHEMA, code="schema_drift")
    _eq(value, "status", "blocked_fail_closed", code="authorization_drift")
    _eq(value, "audit_only", True)
    _eq(value, "diagnostic_only", True)
    _eq(value, "formal_eligible", False, code="authorization_drift")
    for path, expected in {
        "scope.case_id": CASE_ID,
        "scope.family": FAMILY,
        "scope.proposal_scope": SCOPE_ID,
        "scope.target_hdf5": TARGET_SOURCE_PATH,
        "scope.target_hdf5_sha256": SOURCE_SHA256,
        "archives_path_binding.collection_case_declared_hdf5": COLLECTION_SOURCE_PATH,
        "archives_path_binding.proposal_target_hdf5": TARGET_SOURCE_PATH,
        "archives_path_binding.exact_path_match": False,
        "archives_path_binding.source_sha256_match": True,
        "archives_path_binding.mismatch_class": "archives-v1_vs_archives-v2",
        "collection_manifest_binding.path": COLLECTION_MANIFEST_PATH,
        "collection_manifest_binding.current_sha256": COLLECTION_MANIFEST_SHA256,
        "collection_manifest_binding.reader_smoke_path": COLLECTION_MANIFEST_PATH,
        "collection_manifest_binding.reader_smoke_recorded_sha256": "86100523e66202f567ee29da6e178702f0e3ab19c63bd0cf861ff8a5fa0f86b4",
        "collection_manifest_binding.trusted_reader_formal_eligible": False,
        "dev07_diagnostic_binding.source_path_matches_target": True,
        "dev07_diagnostic_binding.source_sha256_matches_target": True,
        "dev07_diagnostic_binding.event_window_complete": False,
        "dev07_diagnostic_binding.event_window_status": "right_censored_or_unresolved",
        "dev07_diagnostic_binding.common_reliable_path_coverage": DIAGNOSTIC_RELIABLE_COVERAGE,
        "dev07_diagnostic_binding.unknown_fraction_max": DIAGNOSTIC_UNKNOWN_FRACTION,
        "dev07_diagnostic_binding.unknown_gate_pass": False,
        "dev07_diagnostic_binding.credit": 0,
        "dev07_diagnostic_binding.formal_admission": False,
        "planner_binding.build_proposal_formal_eligible": False,
        "planner_binding.build_proposal_status": "blocked_fail_closed",
        "planner_binding.semantic_projection_match": True,
        "input_boundary.hdf5_content_read": False,
        "input_boundary.hdf5_hash_recomputed": False,
        "input_boundary.hdf5_opened": False,
        "qualification.T1": False,
        "qualification.T2": False,
        "qualification.credit": 0,
        "qualification.qualification_credit": 0,
    }.items():
        _eq(value, path, expected, code="source_drift")
    checks = _get(value, "checks")
    _require(type(checks) is list, "consistency checks must be a list", code="schema_drift")
    parameter_check = next(
        (
            item
            for item in checks
            if isinstance(item, dict)
            and item.get("check") == "planner_parameter_contract_matches_committed_receipt"
        ),
        None,
    )
    _require(parameter_check is not None, "planner parameter contract check is missing", code="schema_drift")
    observed = _get(parameter_check, "observed")
    for path, expected in {
        "q": Q,
        "dp_m": DP_M,
        "native_frame_count": FRAMES,
        "native_transition_count": TRANSITIONS,
        "native_window_s": NATIVE_WINDOW_S,
        "extension_window_s": REQUIRED_EVENT_WINDOW_S,
        "neighbour_variant": NEIGHBOUR_VARIANT,
        "seeds": SEEDS,
        "substeps": SUBSTEPS,
    }.items():
        _eq(observed, path, expected, code="binding_drift")
    return {
        "collection_manifest_reader_sha": _get(value, "collection_manifest_binding.reader_smoke_recorded_sha256"),
        "path_exact": False,
        "sha_exact": True,
        "diagnostic_parameter_binding": False,
    }


def _validate_terminal(value: dict[str, Any]) -> dict[str, Any]:
    _eq(value, "schema", TERMINAL_SCHEMA, code="schema_drift")
    _eq(value, "status", "blocked_fail_closed", code="authorization_drift")
    for path, expected in {
        "scope.case_id": CASE_ID,
        "scope.family": FAMILY,
        "scope.scope_id": SCOPE_ID,
        "scope.source_hdf5": TARGET_SOURCE_PATH,
        "scope.source_sha256": SOURCE_SHA256,
        "source_ref_consistency.all_declared_source_sha256_match": True,
        "source_ref_consistency.collection_sha256": SOURCE_SHA256,
        "source_ref_consistency.diagnostic_before_sha256": SOURCE_SHA256,
        "source_ref_consistency.diagnostic_after_sha256": SOURCE_SHA256,
        "source_ref_consistency.proposal_sha256": SOURCE_SHA256,
        "source_ref_consistency.target_hdf5_metadata.bytes": SOURCE_BYTES,
        "source_ref_consistency.target_hdf5_metadata.declared_sha256": SOURCE_SHA256,
        "source_ref_consistency.target_hdf5_metadata.path": TARGET_SOURCE_PATH,
        "source_ref_consistency.target_hdf5_metadata.exists": True,
        "source_ref_consistency.target_hdf5_metadata.metadata_only": True,
        "source_ref_consistency.target_hdf5_metadata.content_read": False,
        "source_ref_consistency.target_hdf5_metadata.content_hash_recomputed": False,
        "material_config_contract.q": Q,
        "material_config_contract.dp_m": DP_M,
        "material_config_contract.neighbour_variant": NEIGHBOUR_VARIANT,
        "material_config_contract.seeds": SEEDS,
        "material_config_contract.substeps": SUBSTEPS,
        "material_config_contract.native_source_window_s": NATIVE_WINDOW_S,
        "material_config_contract.required_event_window_s": REQUIRED_EVENT_WINDOW_S,
        "material_config_contract.required_source_frames": FRAMES,
        "material_config_contract.required_source_transitions": TRANSITIONS,
        "proposal_collection_reader_diagnostic_projection.collection_case.case_id": CASE_ID,
        "proposal_collection_reader_diagnostic_projection.collection_case.trajectory_path": COLLECTION_SOURCE_PATH,
        "proposal_collection_reader_diagnostic_projection.collection_case.trajectory_sha256": SOURCE_SHA256,
        "proposal_collection_reader_diagnostic_projection.diagnostic_trace.frame_count": FRAMES,
        "proposal_collection_reader_diagnostic_projection.diagnostic_trace.transition_count": TRANSITIONS,
        "proposal_collection_reader_diagnostic_projection.diagnostic_trace.event_window_complete": False,
        "proposal_collection_reader_diagnostic_projection.diagnostic_trace.event_window_status": "right_censored_or_unresolved",
        "proposal_collection_reader_diagnostic_projection.diagnostic_trace.unknown_fraction_max": DIAGNOSTIC_UNKNOWN_FRACTION,
        "proposal_collection_reader_diagnostic_projection.diagnostic_trace.common_reliable_path_coverage": DIAGNOSTIC_RELIABLE_COVERAGE,
        "proposal_collection_reader_diagnostic_projection.diagnostic_trace.mass_closed": True,
        "proposal_collection_reader_diagnostic_projection.proposal_config.q": Q,
        "proposal_collection_reader_diagnostic_projection.proposal_config.dp_m": DP_M,
        "proposal_collection_reader_diagnostic_projection.proposal_config.required_event_window_s": REQUIRED_EVENT_WINDOW_S,
        "proposal_collection_reader_diagnostic_projection.proposal_config.source_frames": FRAMES,
        "proposal_collection_reader_diagnostic_projection.proposal_config.source_transitions": TRANSITIONS,
        "terminal_evidence_intake.present": False,
        "terminal_evidence_intake.status": "missing",
        "terminal_evidence_intake.gate_projection.event_window_complete": False,
        "terminal_evidence_intake.gate_projection.mass_closure": False,
        "terminal_evidence_intake.gate_projection.unknown_gate": False,
        "fresh_attempt_contract.fresh_attempt_required": True,
        "fresh_attempt_contract.historical_trace_reuse": False,
        "fresh_attempt_contract.namespace_must_be_absent_before_attempt": True,
        "fresh_attempt_contract.overwrite_allowed": False,
        "fresh_attempt_contract.terminal_evidence_ref.exists": False,
        "fresh_attempt_contract.terminal_evidence_ref.content_read": False,
        "fresh_attempt_contract.terminal_evidence_ref.error": "missing_file",
        "qualification.T1": False,
        "qualification.T2": False,
        "qualification.credit": 0,
        "qualification.qualification_credit": 0,
        "input_boundary.bounded_json_only": True,
        "input_boundary.hdf5_content_read": False,
        "input_boundary.hdf5_hash_recomputed": False,
        "input_boundary.hdf5_metadata_only": True,
    }.items():
        _eq(value, path, expected, code="terminal_boundary")
    terminal_ref_path = _metadata_path(
        _get(value, "fresh_attempt_contract.terminal_evidence_ref.path"),
        "fresh terminal evidence path",
        suffix=".json",
    )
    _string_list(_get(value, "blocking_reasons"), "terminal blocking reasons", nonempty=True)
    return {
        "present": False,
        "status": "missing",
        "path": terminal_ref_path,
        "event_window_complete": False,
        "event_window_status": "right_censored_or_unresolved",
        "unknown_fraction_max": DIAGNOSTIC_UNKNOWN_FRACTION,
        "reliable_path_coverage": DIAGNOSTIC_RELIABLE_COVERAGE,
    }


def _validate_matrix(value: dict[str, Any]) -> dict[str, Any]:
    _eq(value, "schema", MATRIX_SCHEMA, code="schema_drift")
    _eq(value, "status", "blocked_fail_closed", code="authorization_drift")
    _eq(value, "scope.scope_id", SCOPE_ID)
    _eq(value, "scope.family", FAMILY)
    _eq(value, "scope.case_count", MATRIX_CASE_COUNT)
    _eq(value, "fixed_matrix.case_count", MATRIX_CASE_COUNT)
    _eq(value, "material_sidecars.sidecar_count_supplied", 0)
    _eq(value, "material_sidecars.duplicate_case_ids", [])
    _eq(value, "material_sidecars.extra_case_ids", [])
    expected_cases = [f"{SCOPE_ID}_DEV_{index:02d}" for index in range(MATRIX_CASE_COUNT)]
    _eq(value, "material_sidecars.missing_case_ids", expected_cases)
    for path, expected in {
        "matrix_summary.complete_sidecar_count": 0,
        "matrix_summary.full_event_window_complete_count": 0,
        "matrix_summary.mass_closed_count": 0,
        "matrix_summary.expected_case_count": MATRIX_CASE_COUNT,
        "matrix_summary.observed_sidecar_count": 0,
        "matrix_summary.formal_acceptance_receipt_count": 0,
        "matrix_summary.matrix_ready": False,
        "matrix_summary.qualification_credit": 0,
        "fresh_output_namespace.execution_authorized": False,
        "fresh_output_namespace.exists": False,
        "fresh_output_namespace.solver_worker_gpu_queue_started": False,
        "source_binding.dev07.collection_source_hdf5": COLLECTION_SOURCE_PATH,
        "source_binding.dev07.collection_source_sha256": SOURCE_SHA256,
        "source_binding.dev07.proposal_source_hdf5": TARGET_SOURCE_PATH,
        "source_binding.dev07.proposal_source_sha256": SOURCE_SHA256,
        "source_binding.dev07.source_sha256_match": True,
        "source_binding.dev07.archives_v1_v2_drift": True,
        "source_binding.receipt_consistency.archives_path_exact": False,
        "source_binding.receipt_consistency.source_sha256_exact": True,
        "qualification.T1": False,
        "qualification.T2": False,
        "qualification.T2_macro": False,
        "qualification.T2_path": False,
        "qualification.credit": 0,
        "qualification.qualification_credit": 0,
        "execution_controls.production_hdf5_content_read": False,
        "execution_controls.production_hdf5_opened": False,
        "execution_controls.gpu_started": False,
        "execution_controls.solver_started": False,
        "execution_controls.worker_started": False,
        "execution_controls.queue_started": False,
        "execution_controls.registry_mutation": 0,
        "execution_controls.ledger_mutation": 0,
        "execution_controls.denominator_mutation": 0,
        "execution_controls.gate_mutation": 0,
    }.items():
        _eq(value, path, expected, code="matrix_boundary")
    _string_list(_get(value, "blocking_reasons"), "matrix blocking reasons", nonempty=True)
    return {
        "expected_case_count": MATRIX_CASE_COUNT,
        "sidecar_count_supplied": 0,
        "missing_case_count": len(expected_cases),
        "missing_case_ids": expected_cases,
        "matrix_ready": False,
    }


def _validate_t2(value: dict[str, Any]) -> dict[str, Any]:
    _eq(value, "schema", T2_SCHEMA, code="schema_drift")
    _eq(value, "scope.scope_id", SCOPE_ID)
    _eq(value, "scope.case", CASE_LABEL)
    _eq(value, "scope.family", FAMILY)
    for path, expected in {
        "decision.readiness_status": "blocked_fail_closed",
        "decision.coarse_material_path_legally_launchable": False,
        "decision.formal_T2_macro": False,
        "decision.formal_T2_path": False,
        "decision.qualification_claim": "none",
        "decision.qualification_credit": 0,
        "plan_contract.F4_full_event_window_required": True,
        "plan_contract.accepted_32_case_sidecars_required": True,
        "plan_contract.exact_material_path_is_independent": True,
        "plan_contract.old_short_window_is_diagnostic_only": True,
        "plan_contract.two_macro_material_T2_families_required": True,
        "current_acceptance_bridge.T2_macro": False,
        "current_acceptance_bridge.T2_path": False,
        "current_acceptance_bridge.formal_credit": 0,
        "macro_sidecar_preflight.T2_macro": False,
        "macro_sidecar_preflight.T2_path": False,
        "macro_sidecar_preflight.formal_acceptance_receipt_count": 0,
        "macro_sidecar_preflight.passed_case_count": 0,
        "macro_sidecar_preflight.registered_case_count": 6,
        "macro_sidecar_preflight.gate_summary.event_window_pass": False,
        "macro_sidecar_preflight.gate_summary.material_matrix_ready": False,
        "registry_ledger_and_runtime.F4_scope_case_count": MATRIX_CASE_COUNT,
        "registry_ledger_and_runtime.observed_material_case_runs": 0,
        "registry_ledger_and_runtime.required_material_case_runs": 0,
        "registry_ledger_and_runtime.missing_material_case_runs": 288,
        "registry_ledger_and_runtime.missing_target_material_case_runs": 288,
        "source_and_trajectory_evidence.dev07_source_bound_diagnostic.source_path": TARGET_SOURCE_PATH,
        "source_and_trajectory_evidence.dev07_source_bound_diagnostic.source_sha256": SOURCE_SHA256,
        "source_and_trajectory_evidence.dev07_source_bound_diagnostic.trace_frames": FRAMES,
        "source_and_trajectory_evidence.dev07_source_bound_diagnostic.trace_transitions": TRANSITIONS,
        "source_and_trajectory_evidence.dev07_source_bound_diagnostic.event_window_complete": False,
        "source_and_trajectory_evidence.dev07_source_bound_diagnostic.event_window_status": "right_censored_or_unresolved",
        "source_and_trajectory_evidence.dev07_source_bound_diagnostic.mass_closed": True,
        "source_and_trajectory_evidence.dev07_source_bound_diagnostic.unknown_gate_pass": False,
        "source_and_trajectory_evidence.dev07_source_bound_diagnostic.unknown_fraction_max": DIAGNOSTIC_UNKNOWN_FRACTION,
        "source_and_trajectory_evidence.dev07_source_bound_diagnostic.common_reliable_path_coverage": DIAGNOSTIC_RELIABLE_COVERAGE,
        "source_and_trajectory_evidence.completed_reader_smoke.frames_per_case": FRAMES,
        "source_and_trajectory_evidence.completed_reader_smoke.transitions_per_case": TRANSITIONS,
        "source_and_trajectory_evidence.completed_reader_smoke.cases_opened": "32/32",
        "source_and_trajectory_evidence.completed_reader_smoke.source_hashes_verified": "32/32",
        "source_and_trajectory_evidence.completed_reader_smoke.reader_formal_eligible": False,
        "source_and_trajectory_evidence.completed_reader_smoke.diagnostic_only": True,
        "execution_controls.gpu_started": False,
        "execution_controls.native_started": False,
        "execution_controls.solver_started": False,
        "execution_controls.worker_started": False,
        "execution_controls.queue_started": False,
        "execution_controls.registry_mutations": 0,
        "execution_controls.ledger_mutations": 0,
        "execution_controls.denominator_mutations": 0,
        "execution_controls.gate_mutations": 0,
    }.items():
        _eq(value, path, expected, code="t2_boundary")
    _eq(value, "source_and_trajectory_evidence.completed_reader_smoke.time_window_s", [TIME_START_S, TIME_END_S])
    return {
        "readiness_status": "blocked_fail_closed",
        "formal_T2_macro": False,
        "formal_T2_path": False,
        "missing_target_material_case_runs": 288,
    }


def _load_and_validate(input_paths: Mapping[str, str | Path] | None) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    paths = dict(DEFAULT_INPUT_PATHS if input_paths is None else input_paths)
    _require(set(paths) == set(DEFAULT_INPUT_PATHS), "input path set differs from the seven-file contract", code="input_set")
    values: dict[str, dict[str, Any]] = {}
    metas: dict[str, dict[str, Any]] = {}
    for name in DEFAULT_INPUT_PATHS:
        value, meta = _read_bounded_json(paths[name], label=name)
        _scan_boundary(value, path=name)
        values[name] = value
        metas[name] = meta
    _validate_coarse(values["coarse_proposal"])
    _validate_root(values["root_scheduler"])
    _validate_drift(values["source_drift"])
    _validate_consistency(values["receipt_consistency"])
    _validate_terminal(values["terminal_evidence"])
    _validate_matrix(values["sidecar_matrix"])
    _validate_t2(values["t2_readiness"])
    root_namespace = _metadata_path(
        _get(values["root_scheduler"], "binding_projection.fresh_output_namespace.namespace"),
        "root fresh output namespace",
    ).rstrip("/")
    terminal_path = _metadata_path(
        _get(values["terminal_evidence"], "fresh_attempt_contract.terminal_evidence_ref.path"),
        "fresh terminal evidence path",
        suffix=".json",
    )
    _require(
        terminal_path.startswith(root_namespace + "/"),
        "terminal evidence path is outside the root fresh namespace",
        code="binding_drift",
    )
    return values, metas


def _input_ref(name: str, value: Mapping[str, Any], meta: Mapping[str, Any]) -> dict[str, Any]:
    present = [field for field in ("record_id", "audit_id") if field in value]
    _require(len(present) <= 1, f"{name} has ambiguous record identity fields", code="schema_drift")
    record_id = value.get(present[0]) if present else INPUT_RECORD_IDS[name]
    _require(
        type(record_id) is str and record_id == INPUT_RECORD_IDS[name],
        f"{name} record identity is not the expected value",
        code="binding_drift",
    )
    return {
        "path": meta["path"],
        "bytes": meta["bytes"],
        "sha256": meta["sha256"],
        "schema": value["schema"],
        "record_id": record_id,
    }


def _build_report_from_loaded(values: Mapping[str, dict[str, Any]], metas: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
    coarse = values["coarse_proposal"]
    root = values["root_scheduler"]
    drift = values["source_drift"]
    consistency = values["receipt_consistency"]
    terminal = values["terminal_evidence"]
    matrix = values["sidecar_matrix"]
    t2 = values["t2_readiness"]
    drift_summary = _validate_drift(drift)
    consistency_summary = _validate_consistency(consistency)
    terminal_summary = _validate_terminal(terminal)
    matrix_summary = _validate_matrix(matrix)
    _validate_coarse(coarse)
    root_summary = _validate_root(root)
    t2_summary = _validate_t2(t2)

    blockers = [
        "collection_source_path_archives_v1_vs_archives_v2_drift",
        "reader_manifest_sha_stale",
        "diagnostic_material_parameter_drift",
        "missing_fresh_root_authorization",
        "missing_scheduler_owned_host_io_reservation",
        "missing_fresh_terminal_evidence",
        "diagnostic_event_window_incomplete_or_right_censored",
        "diagnostic_unknown_gate_failed",
        "material_sidecar_matrix_zero_of_32",
        "t2_readiness_blocked",
    ]
    source_drift_blockers = list(drift_summary["blockers"])
    terminal_blockers = list(_get(terminal, "blocking_reasons"))
    matrix_blockers = list(_get(matrix, "blocking_reasons"))

    return {
        "schema": REPORT_SCHEMA,
        "record_id": REPORT_RECORD_ID,
        "status": STATUS,
        "diagnostic_only": True,
        "launch_admitted": False,
        "formal": False,
        "T1": False,
        "T2": False,
        "qualification": False,
        "credit": 0,
        "qualification_credit": 0,
        "scope": {
            "scope_id": SCOPE_ID,
            "family": FAMILY,
            "case": CASE_LABEL,
            "case_id": CASE_ID,
            "lineage_group_id": CASE_ID,
        },
        "source": {
            "target_path": TARGET_SOURCE_PATH,
            "target_sha256": SOURCE_SHA256,
            "target_bytes": SOURCE_BYTES,
            "collection_declared_path": COLLECTION_SOURCE_PATH,
            "collection_declared_sha256": SOURCE_SHA256,
            "collection_path_exact": False,
            "collection_sha256_exact": True,
            "collection_manifest_path": COLLECTION_MANIFEST_PATH,
            "collection_manifest_sha256": COLLECTION_MANIFEST_SHA256,
            "reader_manifest_path_exact": True,
            "reader_manifest_sha256_recorded": consistency_summary["collection_manifest_reader_sha"],
            "reader_manifest_sha256_exact": False,
        },
        "parameters": {
            "q": Q,
            "dp_m": DP_M,
            "neighbour_variant": NEIGHBOUR_VARIANT,
            "seeds": SEEDS,
            "substeps": SUBSTEPS,
            "diagnostic_q": DIAGNOSTIC_Q,
            "diagnostic_parameter_binding": False,
        },
        "event_window": {
            "native_frames": FRAMES,
            "native_transitions": TRANSITIONS,
            "native_window_s": NATIVE_WINDOW_S,
            "required_window_s": REQUIRED_EVENT_WINDOW_S,
            "time_start_s": TIME_START_S,
            "time_end_s": TIME_END_S,
            "diagnostic_event_window_complete": False,
            "diagnostic_status": "right_censored_or_unresolved",
            "diagnostic_unknown_fraction_max": DIAGNOSTIC_UNKNOWN_FRACTION,
            "diagnostic_reliable_path_coverage": DIAGNOSTIC_RELIABLE_COVERAGE,
            "right_censor_policy": "fail closed; no event imputation or partial credit",
        },
        "root_scheduler_authorization": {
            "status": root_summary["status"],
            "root_authorization_intake_bound": False,
            "scheduler_host_io_reservation_bound": False,
            "scheduler_owned_io_verified": False,
            "worker_launch_authorized": False,
            "launch_admitted": False,
            "fresh_namespace": root_summary["fresh_namespace"],
        },
        "terminal_evidence": {
            "present": terminal_summary["present"],
            "status": terminal_summary["status"],
            "path": terminal_summary["path"],
            "event_window_complete": terminal_summary["event_window_complete"],
            "event_window_status": terminal_summary["event_window_status"],
            "unknown_fraction_max": terminal_summary["unknown_fraction_max"],
            "reliable_path_coverage": terminal_summary["reliable_path_coverage"],
        },
        "sidecar_matrix": {
            "expected_case_count": matrix_summary["expected_case_count"],
            "sidecar_count_supplied": matrix_summary["sidecar_count_supplied"],
            "missing_case_count": matrix_summary["missing_case_count"],
            "missing_case_ids": matrix_summary["missing_case_ids"],
            "matrix_ready": matrix_summary["matrix_ready"],
            "formal_acceptance_receipt_count": 0,
        },
        "source_drift": {
            "collection_path_exact": False,
            "collection_sha256_exact": True,
            "reader_manifest_path_exact": True,
            "reader_manifest_sha256_exact": False,
            "diagnostic_parameter_binding": False,
            "blocking_reasons": source_drift_blockers,
        },
        "t2_readiness": {
            "status": t2_summary["readiness_status"],
            "formal_T2_macro": False,
            "formal_T2_path": False,
            "missing_target_material_case_runs": t2_summary["missing_target_material_case_runs"],
        },
        "blockers": blockers,
        "input_refs": {
            name: _input_ref(name, values[name], metas[name]) for name in DEFAULT_INPUT_PATHS
        },
        "input_boundary": {
            "bounded_json_only": True,
            "max_json_bytes": MAX_JSON_BYTES,
            "max_json_depth": MAX_JSON_DEPTH,
            "duplicate_keys_rejected": True,
            "nonfinite_numbers_rejected": True,
            "missing_inputs_fail_closed": True,
            "path_traversal_rejected": True,
            "lab_root_scope_restricted": True,
            "reports_output_scope_restricted": True,
            "symlink_paths_rejected": True,
            "hardlink_paths_rejected": True,
            "held_directory_fd_no_follow": True,
            "read_toctou_rechecked": True,
            "read_inode_rechecked": True,
            "read_hash_rechecked": True,
            "output_inode_rechecked": True,
            "record_ids_exact": True,
            "schemas_exact": True,
            "hdf5_opened": False,
            "hdf5_content_read": False,
            "hdf5_hash_recomputed": False,
        },
        "execution_controls": {
            "gpu_started": False,
            "native_started": False,
            "solver_started": False,
            "worker_started": False,
            "queue_started": False,
            "source_hdf5_opened": False,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
            "gate_mutation": 0,
            "completion_mutation": 0,
            "plan_mutation": 0,
        },
        "mutations": {
            "registry": 0,
            "ledger": 0,
            "denominator": 0,
            "gate": 0,
            "completion": 0,
            "plan": 0,
            "queue": 0,
            "material_labels": 0,
        },
        "report_contract": {
            "builder": "scripts/f4_tallwall120_material_readiness_projection_v1.py",
            "bounded_json_inputs": list(DEFAULT_INPUT_PATHS),
            "recomputed_from_bounded_json": True,
            "exact_build_report_binding_required": True,
            "diagnostic_only_non_authorizing": True,
            "hdf5_paths_are_metadata_only": True,
        },
        "evidence_detail": {
            "terminal_blocking_reasons": terminal_blockers,
            "matrix_blocking_reasons": matrix_blockers,
            "source_drift_report_status": _get(drift, "status"),
            "consistency_audit_status": _get(consistency, "status"),
            "root_scheduler_status": _get(root, "status"),
            "sidecar_matrix_status": _get(matrix, "status"),
        },
    }


def build_report(input_paths: Mapping[str, str | Path] | None = None) -> dict[str, Any]:
    """Build the deterministic projection from exactly seven bounded JSON files."""

    values, metas = _load_and_validate(input_paths)
    report = _build_report_from_loaded(values, metas)
    validate_report(report)
    return report


def _validate_input_ref(value: Any, *, name: str, input_name: str) -> None:
    label = name
    _require(isinstance(value, dict), f"{label} is malformed", code="report_schema")
    _require(set(value) == {"path", "bytes", "sha256", "schema", "record_id"}, f"{label} fields differ", code="report_schema")
    _canonical_path(value["path"], suffix=".json", scope="lab")
    _require(type(value["bytes"]) is int and value["bytes"] > 0, f"{label} bytes are malformed", code="report_schema")
    _sha(value["sha256"], f"{label} SHA")
    _require(
        type(value["schema"]) is str and value["schema"] == INPUT_SCHEMAS[input_name],
        f"{label} schema is not the expected value",
        code="report_binding",
    )
    _require(
        type(value["record_id"]) is str and value["record_id"] == INPUT_RECORD_IDS[input_name],
        f"{label} record is not the expected value",
        code="report_binding",
    )


def validate_report(value: Any) -> dict[str, Any]:
    """Validate the non-authorizing report structure and immutable boundary."""

    _require(isinstance(value, dict), "projection report must be an object", code="report_schema")
    expected_keys = {
        "schema", "record_id", "status", "diagnostic_only", "launch_admitted", "formal", "T1", "T2",
        "qualification", "credit", "qualification_credit", "scope", "source", "parameters", "event_window",
        "root_scheduler_authorization", "terminal_evidence", "sidecar_matrix", "source_drift", "t2_readiness",
        "blockers", "input_refs", "input_boundary", "execution_controls", "mutations", "report_contract",
        "evidence_detail",
    }
    _require(set(value) == expected_keys, "projection report fields differ", code="report_schema")
    for path, expected in {
        "schema": REPORT_SCHEMA,
        "record_id": REPORT_RECORD_ID,
        "status": STATUS,
        "diagnostic_only": True,
        "launch_admitted": False,
        "formal": False,
        "T1": False,
        "T2": False,
        "qualification": False,
        "credit": 0,
        "qualification_credit": 0,
    }.items():
        _eq(value, path, expected, code="authorization_drift" if path not in {"schema", "record_id", "status"} else "report_schema")
    _eq(value, "scope.scope_id", SCOPE_ID)
    _eq(value, "scope.family", FAMILY)
    _eq(value, "scope.case", CASE_LABEL)
    _eq(value, "scope.case_id", CASE_ID)
    _eq(value, "scope.lineage_group_id", CASE_ID)
    for path, expected in {
        "source.target_path": TARGET_SOURCE_PATH,
        "source.target_sha256": SOURCE_SHA256,
        "source.target_bytes": SOURCE_BYTES,
        "source.collection_declared_path": COLLECTION_SOURCE_PATH,
        "source.collection_declared_sha256": SOURCE_SHA256,
        "source.collection_path_exact": False,
        "source.collection_sha256_exact": True,
        "source.collection_manifest_path": COLLECTION_MANIFEST_PATH,
        "source.collection_manifest_sha256": COLLECTION_MANIFEST_SHA256,
        "source.reader_manifest_path_exact": True,
        "source.reader_manifest_sha256_exact": False,
        "parameters.q": Q,
        "parameters.dp_m": DP_M,
        "parameters.neighbour_variant": NEIGHBOUR_VARIANT,
        "parameters.seeds": SEEDS,
        "parameters.substeps": SUBSTEPS,
        "parameters.diagnostic_q": DIAGNOSTIC_Q,
        "parameters.diagnostic_parameter_binding": False,
        "event_window.native_frames": FRAMES,
        "event_window.native_transitions": TRANSITIONS,
        "event_window.native_window_s": NATIVE_WINDOW_S,
        "event_window.required_window_s": REQUIRED_EVENT_WINDOW_S,
        "event_window.time_start_s": TIME_START_S,
        "event_window.time_end_s": TIME_END_S,
        "event_window.diagnostic_event_window_complete": False,
        "event_window.diagnostic_status": "right_censored_or_unresolved",
        "event_window.diagnostic_unknown_fraction_max": DIAGNOSTIC_UNKNOWN_FRACTION,
        "event_window.diagnostic_reliable_path_coverage": DIAGNOSTIC_RELIABLE_COVERAGE,
        "root_scheduler_authorization.root_authorization_intake_bound": False,
        "root_scheduler_authorization.scheduler_host_io_reservation_bound": False,
        "root_scheduler_authorization.scheduler_owned_io_verified": False,
        "root_scheduler_authorization.worker_launch_authorized": False,
        "root_scheduler_authorization.launch_admitted": False,
        "terminal_evidence.present": False,
        "terminal_evidence.status": "missing",
        "terminal_evidence.event_window_complete": False,
        "terminal_evidence.event_window_status": "right_censored_or_unresolved",
        "sidecar_matrix.expected_case_count": MATRIX_CASE_COUNT,
        "sidecar_matrix.sidecar_count_supplied": 0,
        "sidecar_matrix.missing_case_count": MATRIX_CASE_COUNT,
        "sidecar_matrix.matrix_ready": False,
        "sidecar_matrix.formal_acceptance_receipt_count": 0,
        "source_drift.collection_path_exact": False,
        "source_drift.collection_sha256_exact": True,
        "source_drift.reader_manifest_path_exact": True,
        "source_drift.reader_manifest_sha256_exact": False,
        "source_drift.diagnostic_parameter_binding": False,
        "t2_readiness.status": "blocked_fail_closed",
        "t2_readiness.formal_T2_macro": False,
        "t2_readiness.formal_T2_path": False,
        "t2_readiness.missing_target_material_case_runs": 288,
    }.items():
        _eq(value, path, expected, code="report_binding")
    _metadata_path(_get(value, "source.target_path"), "report target HDF5 metadata", suffix=".h5")
    _metadata_path(_get(value, "source.collection_declared_path"), "report collection HDF5 metadata", suffix=".h5")
    _metadata_path(_get(value, "source.collection_manifest_path"), "report collection manifest", suffix=".json")
    root_namespace = _metadata_path(
        _get(value, "root_scheduler_authorization.fresh_namespace"),
        "report fresh output namespace",
    ).rstrip("/")
    terminal_path = _metadata_path(
        _get(value, "terminal_evidence.path"),
        "report terminal evidence path",
        suffix=".json",
    )
    _require(
        terminal_path.startswith(root_namespace + "/"),
        "report terminal evidence path is outside the root fresh namespace",
        code="report_binding",
    )
    for name, ref in value["input_refs"].items():
        _require(name in DEFAULT_INPUT_PATHS, f"unexpected report input ref: {name}", code="report_schema")
        _validate_input_ref(ref, name=f"report input ref {name}", input_name=name)
    _require(set(value["input_refs"]) == set(DEFAULT_INPUT_PATHS), "report input refs differ", code="report_schema")
    _require(isinstance(value["sidecar_matrix"]["missing_case_ids"], list), "missing sidecar list is malformed", code="report_schema")
    _require(
        _strict_equal(
            value["sidecar_matrix"]["missing_case_ids"],
            [f"{SCOPE_ID}_DEV_{i:02d}" for i in range(MATRIX_CASE_COUNT)],
        ),
        "missing sidecar list drift",
        code="report_binding",
    )
    _string_list(value["source_drift"]["blocking_reasons"], "report source drift blockers", nonempty=True)
    _string_list(value["blockers"], "projection blockers", nonempty=True)
    _string_list(value["evidence_detail"]["terminal_blocking_reasons"], "report terminal blockers", nonempty=True)
    _string_list(value["evidence_detail"]["matrix_blocking_reasons"], "report matrix blockers", nonempty=True)
    _require(_strict_equal(value["input_boundary"], {
        "bounded_json_only": True,
        "max_json_bytes": MAX_JSON_BYTES,
        "max_json_depth": MAX_JSON_DEPTH,
        "duplicate_keys_rejected": True,
        "nonfinite_numbers_rejected": True,
        "missing_inputs_fail_closed": True,
        "path_traversal_rejected": True,
        "lab_root_scope_restricted": True,
        "reports_output_scope_restricted": True,
        "symlink_paths_rejected": True,
        "hardlink_paths_rejected": True,
        "held_directory_fd_no_follow": True,
        "read_toctou_rechecked": True,
        "read_inode_rechecked": True,
        "read_hash_rechecked": True,
        "output_inode_rechecked": True,
        "record_ids_exact": True,
        "schemas_exact": True,
        "hdf5_opened": False,
        "hdf5_content_read": False,
        "hdf5_hash_recomputed": False,
    }), "input boundary drift", code="authorization_drift")
    _require(_strict_equal(value["execution_controls"], {
        "gpu_started": False,
        "native_started": False,
        "solver_started": False,
        "worker_started": False,
        "queue_started": False,
        "source_hdf5_opened": False,
        "registry_mutation": 0,
        "ledger_mutation": 0,
        "denominator_mutation": 0,
        "gate_mutation": 0,
        "completion_mutation": 0,
        "plan_mutation": 0,
    }), "execution boundary drift", code="side_effect_drift")
    _require(_strict_equal(value["mutations"], {
        "registry": 0,
        "ledger": 0,
        "denominator": 0,
        "gate": 0,
        "completion": 0,
        "plan": 0,
        "queue": 0,
        "material_labels": 0,
    }), "mutation boundary drift", code="side_effect_drift")
    _require(_strict_equal(value["report_contract"], {
        "builder": "scripts/f4_tallwall120_material_readiness_projection_v1.py",
        "bounded_json_inputs": list(DEFAULT_INPUT_PATHS),
        "recomputed_from_bounded_json": True,
        "exact_build_report_binding_required": True,
        "diagnostic_only_non_authorizing": True,
        "hdf5_paths_are_metadata_only": True,
    }), "report contract drift", code="report_schema")
    _require(value["evidence_detail"]["source_drift_report_status"] == "blocked_fail_closed", "source drift status drift", code="report_binding")
    _require(value["evidence_detail"]["consistency_audit_status"] == "blocked_fail_closed", "consistency status drift", code="report_binding")
    _require(value["evidence_detail"]["root_scheduler_status"] == "blocked_missing_fresh_root_scheduler_receipts", "root status drift", code="report_binding")
    _require(value["evidence_detail"]["sidecar_matrix_status"] == "blocked_fail_closed", "matrix status drift", code="report_binding")
    return value


def verify_report(
    report_path: str | Path = DEFAULT_REPORT,
    *,
    input_paths: Mapping[str, str | Path] | None = None,
) -> dict[str, Any]:
    """Verify a report against a fresh bounded read of its seven inputs."""

    value, _ = _read_bounded_json(
        report_path,
        label="F4 material readiness projection report",
        scope="reports",
    )
    validate_report(value)
    expected = build_report(input_paths)
    _require(_strict_equal(value, expected), "projection report does not match its bound inputs", code="report_binding_drift")
    return value


def render_markdown(report: Mapping[str, Any]) -> str:
    """Render the checked-in Chinese companion from the validated report."""

    validate_report(dict(report))
    missing = report["sidecar_matrix"]["missing_case_count"]
    return "\n".join(
        [
            "# F4 Tallwall120 material readiness projection v1",
            "",
            "本报告只消费七份 bounded JSON receipt；不打开或读取 HDF5，也不授予任何运行权、正式资格或 credit。",
            "",
            f"- 状态：`{report['status']}`",
            "- `diagnostic_only=true`，`launch_admitted=false`，`formal=false`，`T1=false`，`T2=false`，`qualification=false`。",
            "- `credit=0`、`qualification_credit=0`；registry、ledger、denominator、gate、completion、PLAN 和 queue mutation 全部为 `0`。",
            "",
            "## 绑定范围",
            "",
            f"- scope：`{report['scope']['scope_id']}`；case：`{report['scope']['case_id']}`。",
            f"- source：`{report['source']['target_path']}`；SHA-256：`{report['source']['target_sha256']}`。",
            f"- q：`{report['parameters']['q']}`；dp：`{report['parameters']['dp_m']}`；native window：`{report['event_window']['native_window_s']} s`；required event window：`{report['event_window']['required_window_s']} s`。",
            "",
            "## 当前阻塞",
            "",
            f"- root/scheduler authorization：未闭合；`launch_admitted=false`。",
            f"- terminal evidence：`{report['terminal_evidence']['status']}`；event window 为 `{report['event_window']['diagnostic_status']}`。",
            f"- material sidecar：`{report['sidecar_matrix']['sidecar_count_supplied']}/{report['sidecar_matrix']['expected_case_count']}`，缺失 `{missing}` 个。",
            f"- collection source path 仍为 archives-v1，而 proposal target 为 archives-v2；reader manifest SHA 仍未精确绑定。",
            "",
            "## 安全边界",
            "",
            "输入读取拒绝 duplicate key、非 finite 数值、越界大小、路径 traversal、symlink 和读时 TOCTOU 变化；报告验证会重新从七份输入构建并逐字节绑定 SHA。",
            "",
            "该 projection 是 readiness 记录，不是实际 material trace、terminal evidence、T2 acceptance 或 launch authorization。",
            "",
        ]
    )


def write_outputs(
    report_path: str | Path = DEFAULT_REPORT,
    markdown_path: str | Path = DEFAULT_MARKDOWN,
    *,
    input_paths: Mapping[str, str | Path] | None = None,
) -> tuple[Path, Path]:
    """Build once and create the JSON/Chinese reports without overwriting."""

    report = build_report(input_paths)
    json_payload = (json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    markdown_payload = render_markdown(report).encode("utf-8")
    written_report = _write_new_regular_file(report_path, json_payload, suffix=".json")
    written_markdown = _write_new_regular_file(markdown_path, markdown_payload, suffix=".md")
    return written_report, written_markdown


def _parse_input_overrides(items: list[str]) -> dict[str, str | Path] | None:
    if not items:
        return None
    result = dict(DEFAULT_INPUT_PATHS)
    for item in items:
        name, separator, path = item.partition("=")
        _require(separator == "=" and name in DEFAULT_INPUT_PATHS and path, f"invalid --input override: {item}", code="input_set")
        result[name] = path
    return result


# Adjacent evidence contracts use both names; keeping aliases makes this
# projection easy to exercise without importing any production module.
build_projection = build_report
validate_projection = validate_report
verify_projection = verify_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--write", action="store_true", help="write the JSON and Chinese reports")
    group.add_argument("--verify", action="store_true", help="verify the JSON report against all seven inputs")
    parser.add_argument("--report", default=str(DEFAULT_REPORT), help="JSON report path")
    parser.add_argument("--markdown", default=str(DEFAULT_MARKDOWN), help="Chinese report path for --write")
    parser.add_argument("--input", action="append", default=[], metavar="NAME=PATH", help="override one bounded JSON input")
    args = parser.parse_args(argv)
    input_paths = _parse_input_overrides(args.input)
    if args.write:
        report_path, markdown_path = write_outputs(args.report, args.markdown, input_paths=input_paths)
        print(f"json={_display_path(report_path)}")
        print(f"markdown={_display_path(markdown_path)}")
        return 0
    if args.verify:
        result = verify_report(args.report, input_paths=input_paths)
    else:
        result = build_report(input_paths)
    print(json.dumps({
        "schema": result["schema"],
        "status": result["status"],
        "scope": result["scope"],
        "launch_admitted": result["launch_admitted"],
        "formal": result["formal"],
        "T1": result["T1"],
        "T2": result["T2"],
        "qualification": result["qualification"],
        "credit": result["credit"],
        "blockers": result["blockers"],
    }, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except F4MaterialReadinessProjectionError as error:
        print(f"ERROR[{error.code}]: {error}", file=sys.stderr)
        sys.exit(2)
