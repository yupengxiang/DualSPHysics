#!/usr/bin/env python3
"""Receipt-bound seed17 diagnostic runner v2.

The default is a non-launching dry-run over an already issued admission
receipt.  Only ``--diagnostic-execute`` can consume the receipt and reach the
captured real ``subprocess.Popen``/``wait`` path.  No factory, fake process,
caller capability, alias flag, or self-declared terminal proof is accepted.

Every execution revalidates all receipt-bound files and the exact GPU-2
resource snapshot before Popen.  After a natural zero exit it securely reads
the evaluator artifacts, runs the independent F3 HDF5 validator and the
hardened HDF5 link/path boundary, then writes an exclusive zero-credit
diagnostic terminal receipt.  Any identity drift fails closed.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import secrets
from typing import Any

import h5py

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.dont_write_bytecode = True

from scripts import f3_graph_raw_hidden16_seed17_diagnostic_admission_v1 as admission
from scripts import f3_graph_terminal_validator_security_hardening_v1 as hardening


LAB_ROOT = Path(__file__).resolve().parents[1]
SEED = admission.SEED
GPU_INDEX = admission.GPU_INDEX
MODEL = admission.MODEL
HIDDEN = admission.HIDDEN
UPDATES = admission.UPDATES
CASE_ID = admission.CASE_ID
SPLIT = admission.SPLIT
TRANSITIONS = admission.TRANSITIONS
FRAMES = admission.FRAMES
SCHEMA = "core.f3.graph_raw.hidden16.seed17.diagnostic_runner.v2"
REPORT_SCHEMA = f"{SCHEMA}.report"
TERMINAL_RECEIPT_SCHEMA = f"{SCHEMA}.terminal_receipt"
REPORT_ID = "f3-graph-raw-hidden16-seed17-diagnostic-runner-v2"
DEFAULT_REPORT = LAB_ROOT / "reports" / "F3-GRAPH-RAW-HIDDEN16-SEED17-DIAGNOSTIC-RUNNER-V2-2026-09-29.json"
DEFAULT_MARKDOWN = DEFAULT_REPORT.with_suffix(".zh-CN.md")
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_HDF5_BYTES = 2 * 1024 * 1024 * 1024
MAX_EXECUTABLE_BYTES = 512 * 1024 * 1024
MAX_READ_CHUNK = 1024 * 1024
MAX_HDF5_LINKS = 8192
ARTIFACT_ROOT = Path(tempfile.gettempdir()).resolve()
EVALUATOR_OUTPUT_NAMES = ("evaluation", "trajectory", "progress", "log")
DESCRIPTOR_PUBLICATION_SCHEMA = f"{SCHEMA}.descriptor_publication.v1"
DESCRIPTOR_PUBLICATION_PROTOCOL = "sealed_pass_fds_inode_publication_v1"
DESCRIPTOR_PUBLICATION_ARGUMENT = "--descriptor-publication-contract"
DESCRIPTOR_PUBLICATION_FD_ARGUMENTS = {
    "evaluation": "--evaluation-fd",
    "trajectory": "--trajectory-fd",
    "progress": "--progress-fd",
    "log": "--log-fd",
}
TERMINAL_PROCESS_IDENTITY_SCHEMA = f"{TERMINAL_RECEIPT_SCHEMA}.process_identity"
NVIDIA_SMI_COMMAND = (
    "nvidia-smi",
    "--query-gpu=index,uuid,pci.bus_id,memory.total,memory.used,memory.free",
    "--format=csv,noheader,nounits",
)
NVIDIA_SMI_PROCESS_COMMAND = (
    "nvidia-smi",
    "--query-compute-apps=pid,gpu_uuid",
    "--format=csv,noheader,nounits",
)
GPU_UUID_RE = re.compile(r"^GPU-[0-9A-Fa-f-]{8,}$")
PCI_BUS_RE = re.compile(r"^[0-9A-Fa-f]{4}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}\.[0-7]$")

ZERO_CREDIT: dict[str, Any] = dict(admission.ZERO_CREDIT)

EXECUTION_BLOCKERS = (
    "P1 replay/one-shot capability is not independently sealed across consumers",
    "P1 path and artifact TOCTOU closure is not independently attested for this runner",
    "P1 HDF5 external/soft/VDS link closure is not granted as an execution authority",
    "P1 physical GPU2 UUID mapping is not externally attested",
    "P1 sealed real subprocess.Popen/wait witness is not independently granted",
    "P1 complete environment identity is not externally sealed at scheduler admission",
    "P1 formal isolation is diagnostic-only and has no independent scheduler attestation",
    "P1 terminal artifact identity closure is not authorized for a production execution",
)

# Capture the class and the witness secret once.  The runner has no injectable
# Popen seam.  ``_REAL_POPEN`` is retained as a compatibility-visible name for
# the older negative tests; the future path below uses ``_SEALED_POPEN`` so a
# caller cannot replace the module attribute and turn it into an injection
# point.
_REAL_POPEN = subprocess.Popen
_SEALED_POPEN = _REAL_POPEN
_PROCESS_WITNESS_SECRET = secrets.token_bytes(32)

# Deliberately absent.  Installing a capability is outside this change and
# cannot be done by a JSON field, a caller object, or a callback argument.
_DIAGNOSTIC_EXECUTION_CAPABILITY: object | None = None


class RunnerError(ValueError):
    """Malformed, drifting, unsafe, or non-authorizing execution input."""


def _fail(message: str) -> None:
    raise RunnerError(f"fail-closed: {message}")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{name} must be an object")
    return value


def _exact(value: Mapping[str, Any], key: str, expected: Any, name: str) -> None:
    if key not in value:
        _fail(f"{name}.{key} is missing")
    observed = value[key]
    if type(expected) is bool and type(observed) is not bool:
        _fail(f"{name}.{key} must be boolean")
    if type(expected) is int and type(observed) is not int:
        _fail(f"{name}.{key} must be integer")
    if observed != expected:
        _fail(f"{name}.{key} must be {expected!r}; observed {observed!r}")


def _reject_unknown(value: Mapping[str, Any], allowed: set[str] | frozenset[str], name: str) -> None:
    unknown = sorted(set(value) - set(allowed))
    if unknown:
        _fail(f"{name} contains unknown fields: {unknown}")


def _sha256_hex(value: Any, name: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        _fail(f"{name} must be a lowercase SHA-256")
    return value


def _absolute(value: Path | str, name: str) -> Path:
    try:
        path = Path(os.fspath(value))
    except TypeError:
        _fail(f"{name} is not a path")
    if not path.is_absolute() or any(part in {".", ".."} for part in path.parts):
        _fail(f"{name} must be absolute and lexical-alias free")
    if Path(os.path.normpath(str(path))) != path:
        _fail(f"{name} uses a lexical path alias")
    return path


def _under(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _reject_symlink_components(path: Path, name: str) -> None:
    """Reject every existing component of an absolute path that is a link."""

    current = Path(path.anchor or os.sep)
    parts = path.parts[1:] if path.is_absolute() else path.parts
    for part in parts:
        current /= part
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            _fail(f"{name} has a missing component: {current}")
        except OSError as error:
            _fail(f"cannot inspect {name}: {error}")
        if stat.S_ISLNK(info.st_mode):
            _fail(f"{name} contains a symlink component: {current}")


def _fd_identity(info: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        int(info.st_dev),
        int(info.st_ino),
        int(info.st_mode),
        int(info.st_nlink),
        int(info.st_size),
        int(info.st_mtime_ns),
    )


def _directory_flags() -> int:
    required = getattr(os, "O_DIRECTORY", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if required == 0 or nofollow == 0:
        _fail("platform lacks O_DIRECTORY/O_NOFOLLOW for stable directory binding")
    return os.O_RDONLY | required | nofollow | getattr(os, "O_CLOEXEC", 0)


def _read_flags() -> int:
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if nofollow == 0:
        _fail("platform lacks O_NOFOLLOW for stable artifact binding")
    return os.O_RDONLY | nofollow | getattr(os, "O_CLOEXEC", 0)


def _open_directory(path: Path, name: str) -> int:
    """Open a directory chain without following any component symlink."""

    candidate = _absolute(path, name)
    flags = _directory_flags()
    try:
        current = os.open(os.sep, flags)
    except OSError as error:
        _fail(f"cannot open filesystem root for {name}: {error}")
    try:
        for component in candidate.parts[1:]:
            try:
                child = os.open(component, flags, dir_fd=current)
            except OSError as error:
                _fail(f"cannot open {name} directory component {component!r}: {error}")
            os.close(current)
            current = child
        info = os.fstat(current)
        if not stat.S_ISDIR(info.st_mode) or info.st_nlink < 1:
            _fail(f"{name} is not a stable directory")
        return current
    except BaseException:
        try:
            os.close(current)
        except OSError:
            pass
        raise


def _artifact_root(path: Path, root: Path, name: str) -> tuple[Path, Path]:
    candidate = _absolute(path, name)
    scope = _absolute(root, f"{name} root")
    if candidate == scope or not _under(candidate, scope):
        _fail(f"{name} escapes its bound root")
    _reject_symlink_components(scope, f"{name} root")
    _reject_symlink_components(candidate.parent, f"{name} parent")
    return candidate, scope


def _stable_artifact(
    path: Path | str,
    root: Path | str,
    name: str,
    *,
    max_bytes: int,
    allow_leaf_symlink: bool = False,
    read_content: bool = True,
) -> tuple[dict[str, Any], bytes]:
    """Read/hash one regular file from one held descriptor, exactly once.

    The content parser receives the bytes read from this descriptor.  It never
    reopens the pathname.  The final identity check uses ``fstat`` and a
    ``stat(..., dir_fd=...)`` on the already-held parent directory; it does not
    perform a second content open.  Output artifacts reject leaf symlinks and
    hardlinks, and callers that allow an executable symlink bind both the link
    spelling and its resolved regular target.
    """

    candidate, scope = _artifact_root(Path(path), Path(root), name)
    if type(max_bytes) is not int or max_bytes < 1:
        _fail(f"{name} max_bytes must be positive")
    resolved = candidate
    leaf_info = os.lstat(candidate)
    leaf_symlink = stat.S_ISLNK(leaf_info.st_mode)
    if leaf_symlink:
        if not allow_leaf_symlink:
            _fail(f"{name} is a symlink")
        try:
            resolved = _absolute(candidate.resolve(strict=True), f"{name} resolved target")
        except OSError as error:
            _fail(f"cannot resolve {name}: {error}")
        if not _under(resolved, scope):
            _fail(f"{name} resolved target escapes its bound root")
        _reject_symlink_components(resolved.parent, f"{name} resolved parent")
    elif not stat.S_ISREG(leaf_info.st_mode):
        _fail(f"{name} must be a regular file")

    relative = resolved.relative_to(scope)
    parent_fd = _open_directory(scope, f"{name} root")
    leaf_fd: int | None = None
    chunks: list[bytes] = []
    hasher = hashlib.sha256()
    total = 0
    before: os.stat_result | None = None
    parent_info: os.stat_result | None = None
    try:
        for component in relative.parts[:-1]:
            try:
                child = os.open(component, _directory_flags(), dir_fd=parent_fd)
            except OSError as error:
                _fail(f"{name} parent component {component!r} is unsafe: {error}")
            os.close(parent_fd)
            parent_fd = child
        try:
            leaf_fd = os.open(relative.parts[-1], _read_flags(), dir_fd=parent_fd)
        except OSError as error:
            _fail(f"cannot open {name} without following a link: {error}")
        before = os.fstat(leaf_fd)
        if not stat.S_ISREG(before.st_mode):
            _fail(f"{name} must be a regular file")
        if before.st_nlink != 1:
            _fail(f"{name} must have exactly one hard link")
        if before.st_size < 1 or before.st_size > max_bytes:
            _fail(f"{name} is outside the bounded size")
        expected_identity = _fd_identity(before)
        while total <= max_bytes:
            block = os.read(leaf_fd, min(MAX_READ_CHUNK, max_bytes + 1 - total))
            if not block:
                break
            total += len(block)
            hasher.update(block)
            if read_content:
                chunks.append(block)
            if total > max_bytes:
                _fail(f"{name} exceeds the bounded read size")
        after = os.fstat(leaf_fd)
        if _fd_identity(after) != expected_identity or total != before.st_size:
            _fail(f"{name} changed during stable descriptor read")
        # This is a metadata check through the held parent fd, never a content
        # reopen.  It catches replacement by a symlink/hardlink while reading.
        path_identity = os.stat(relative.parts[-1], dir_fd=parent_fd, follow_symlinks=False)
        if _fd_identity(path_identity) != expected_identity:
            _fail(f"{name} path identity changed during stable descriptor read")
        parent_info = os.fstat(parent_fd)
        if leaf_symlink:
            try:
                if candidate.resolve(strict=True) != resolved:
                    _fail(f"{name} symlink target changed during stable descriptor read")
            except OSError as error:
                _fail(f"cannot revalidate {name} symlink target: {error}")
    except OSError as error:
        _fail(f"cannot read {name} from stable descriptor: {error}")
    finally:
        if leaf_fd is not None:
            try:
                os.close(leaf_fd)
            except OSError:
                pass
        try:
            os.close(parent_fd)
        except OSError:
            pass
    if before is None:
        _fail(f"{name} did not produce a descriptor")
    if parent_info is None:
        _fail(f"{name} did not produce a parent descriptor")
    raw = b"".join(chunks) if read_content else b""
    descriptor = {
        "path": str(candidate),
        "resolved_path": str(resolved),
        "dev": int(before.st_dev),
        "ino": int(before.st_ino),
        "bytes": int(total),
        "mode": int(stat.S_IMODE(before.st_mode)),
        "uid": int(before.st_uid),
        "gid": int(before.st_gid),
        "nlink": int(before.st_nlink),
        "mtime_ns": int(before.st_mtime_ns),
        "parent_dev": int(parent_info.st_dev),
        "parent_ino": int(parent_info.st_ino),
        "sha256": hasher.hexdigest(),
        "leaf_symlink": bool(leaf_symlink),
        "stable_fd": True,
        "fd_identity_stable": True,
        "path_reopened": False,
        "content_opened": bool(read_content),
    }
    return descriptor, raw


def _descriptor_matches(observed: Mapping[str, Any], expected: Mapping[str, Any], name: str) -> None:
    keys = ("path", "dev", "ino", "bytes", "mode", "uid", "gid", "nlink", "mtime_ns", "sha256")
    if "parent_dev" in expected:
        keys += ("parent_dev", "parent_ino")
    for key in keys:
        if observed.get(key) != expected.get(key):
            _fail(f"{name} descriptor field {key} drifted")


def _walk_json(value: Any, name: str = "value", depth: int = 0) -> None:
    if depth > admission.MAX_JSON_DEPTH:
        _fail(f"{name} exceeds maximum JSON depth")
    if value is None or isinstance(value, (bool, str, int)):
        return
    if isinstance(value, float):
        if not __import__("math").isfinite(value):
            _fail(f"{name} contains a non-finite number")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                _fail(f"{name} contains a non-string key")
            _walk_json(item, f"{name}.{key}", depth + 1)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if len(value) > admission.MAX_ARRAY_ITEMS:
            _fail(f"{name} contains too many items")
        for index, item in enumerate(value):
            _walk_json(item, f"{name}[{index}]", depth + 1)
        return
    _fail(f"{name} contains unsupported type {type(value).__name__}")


def _read_json(path: Path, name: str) -> dict[str, Any]:
    raw, _descriptor, payload = admission._read_file(path, name, max_bytes=MAX_JSON_BYTES, parse_json=True)
    del raw
    if payload is None:
        _fail(f"{name} is not a JSON object")
    return payload


def _secure_artifact(path: Path, root: Path, name: str, *, max_bytes: int) -> tuple[dict[str, Any], bytes]:
    # ``root`` is the namespace parent because the launcher deliberately
    # places the output files beside the reserved namespace directory.  The
    # local reader is used instead of the common validator's pathname API so
    # HDF5/JSON consumers receive the bytes from one stable FD only.
    return _stable_artifact(path, root, name, max_bytes=max_bytes)


def _write_exclusive(path: Path, raw: bytes, mode: int = 0o600) -> dict[str, Any]:
    path = _absolute(path, "exclusive output")
    _reject_symlink_components(path.parent, "exclusive output parent")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    parent_fd = _open_directory(path.parent, "exclusive output parent")
    fd: int | None = None
    try:
        fd = os.open(path.name, flags, mode, dir_fd=parent_fd)
        with os.fdopen(fd, "wb", closefd=True) as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
            info = os.fstat(handle.fileno())
            if stat.S_IMODE(info.st_mode) != mode or info.st_nlink != 1:
                _fail(f"exclusive output identity drifted before close: {path}")
        fd = None
    except FileExistsError:
        _fail(f"refusing to reuse existing output: {path}")
    except OSError as error:
        _fail(f"cannot write exclusive output {path}: {error}")
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            os.close(parent_fd)
        except OSError:
            pass
    # ``info`` came from the same write FD.  Do not reopen the output in order
    # to manufacture its descriptor; only metadata is checked through the
    # held parent directory fd before it is closed above.
    if "info" not in locals():
        _fail(f"exclusive output descriptor was not captured: {path}")
    if info.st_uid != os.getuid() or info.st_gid != os.getgid():
        _fail(f"output owner drifted: {path}")
    return {
        "path": str(path),
        "dev": int(info.st_dev),
        "ino": int(info.st_ino),
        "bytes": int(info.st_size),
        "mode": int(stat.S_IMODE(info.st_mode)),
        "uid": int(info.st_uid),
        "gid": int(info.st_gid),
        "nlink": int(info.st_nlink),
        "mtime_ns": int(info.st_mtime_ns),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "stable_fd": True,
        "fd_identity_stable": True,
        "path_reopened": False,
        "content_opened": True,
    }


def _json_bytes(raw: bytes, name: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=admission._reject_duplicate_keys, parse_constant=admission._reject_constant)
    except Exception as error:
        _fail(f"invalid {name}: {error}")
    _walk_json(value, name)
    return dict(_mapping(value, name))


def _outputs(namespace: Path) -> dict[str, Path]:
    prefix = str(namespace)
    return {
        "evaluation": Path(prefix + "-evaluation.json"),
        "trajectory": Path(prefix + "-trajectory.h5"),
        "progress": Path(prefix + "-evaluation-progress.json"),
        "log": Path(prefix + "-evaluation.log"),
        "validator": Path(prefix + "-hdf5-validation.json"),
        "terminal_receipt": Path(prefix + "-terminal-receipt.json"),
    }


@dataclass(frozen=True)
class _ReservedOutput:
    name: str
    path: Path
    fd: int
    descriptor: Mapping[str, Any]


@dataclass(frozen=True)
class _OutputReservations:
    parent_fd: int
    outputs: Mapping[str, _ReservedOutput]
    publication_contract: Mapping[str, Any]

    @property
    def pass_fds(self) -> tuple[int, ...]:
        return tuple(item.fd for item in self.outputs.values())


def _publication_fd_identity(
    item: _ReservedOutput,
    parent_info: os.stat_result,
    name: str,
) -> dict[str, Any]:
    """Return the immutable identity that a child is allowed to publish to."""

    try:
        info = os.fstat(item.fd)
    except OSError as error:
        _fail(f"cannot inspect reserved {name} descriptor: {error}")
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or info.st_uid != os.getuid()
        or info.st_gid != os.getgid()
    ):
        _fail(f"reserved {name} descriptor is not an owner-only regular inode")
    return {
        "path": str(item.path),
        "fd": int(item.fd),
        "dev": int(info.st_dev),
        "ino": int(info.st_ino),
        "mode": int(stat.S_IMODE(info.st_mode)),
        "uid": int(info.st_uid),
        "gid": int(info.st_gid),
        "nlink": int(info.st_nlink),
        "parent_dev": int(parent_info.st_dev),
        "parent_ino": int(parent_info.st_ino),
        "stable_fd": True,
        "fd_identity_stable": True,
        "path_reopened": False,
        "publication": "inherited_fd_write_no_replace",
    }


def _plan_receipt_field(plan: Any, key: str) -> str:
    receipt = getattr(plan, "receipt", None)
    if isinstance(receipt, Mapping) and key in receipt:
        return str(receipt[key])
    # The isolated reservation tests intentionally use a minimal plan object;
    # this sentinel can never authorize a real launch because the child support
    # contract remains explicitly absent.
    return "0" * 64


def _plan_binding_value(plan: Any) -> str:
    value = getattr(plan, "binding_sha256", None)
    return str(value) if isinstance(value, str) else "0" * 64


def _descriptor_publication_contract(
    plan: DiagnosticPlan,
    reservations: _OutputReservations,
) -> dict[str, Any]:
    """Build the explicit child-side FD/inode publication contract.

    The contract is deliberately separate from the pathname arguments accepted
    by ``core_learning``.  A supporting child must receive the exact inherited
    descriptors, write the final bytes to those descriptors, and never unlink,
    replace, or reopen the bound output path.  The current core child does not
    advertise these arguments, so the contract is present for verification but
    remains non-authorizing and is rejected before Popen.
    """

    _validate_output_reservations(reservations)
    try:
        parent_info = os.fstat(reservations.parent_fd)
    except OSError as error:
        _fail(f"cannot inspect descriptor publication parent: {error}")
    if not stat.S_ISDIR(parent_info.st_mode):
        _fail("descriptor publication parent is not a directory")
    outputs: dict[str, Any] = {}
    for name in EVALUATOR_OUTPUT_NAMES:
        item = reservations.outputs.get(name)
        if item is None:
            _fail(f"descriptor publication output {name!r} is missing")
        outputs[name] = _publication_fd_identity(item, parent_info, name)
    core = {
        "schema": DESCRIPTOR_PUBLICATION_SCHEMA,
        "protocol": DESCRIPTOR_PUBLICATION_PROTOCOL,
        "namespace": str(plan.namespace),
        "namespace_parent": {
            "dev": int(parent_info.st_dev),
            "ino": int(parent_info.st_ino),
        },
        "receipt_sha256": _plan_receipt_field(plan, "receipt_sha256"),
        "identity_sha256": _plan_receipt_field(plan, "identity_sha256"),
        "binding_sha256": _plan_binding_value(plan),
        "outputs": outputs,
        "pass_fds": list(reservations.pass_fds),
        "publication_rule": "child_must_write_inherited_fd_without_path_reopen_or_replace",
    }
    contract_sha256 = canonical_digest(core)
    required_suffix: list[str] = [DESCRIPTOR_PUBLICATION_ARGUMENT, contract_sha256]
    for name in EVALUATOR_OUTPUT_NAMES:
        required_suffix.extend(
            [DESCRIPTOR_PUBLICATION_FD_ARGUMENTS[name], str(outputs[name]["fd"])]
        )
    command = tuple(getattr(plan, "command", ()))
    supported = len(command) >= len(required_suffix) and tuple(command[-len(required_suffix):]) == tuple(required_suffix)
    return {
        **core,
        "contract_sha256": contract_sha256,
        "required_argv_suffix": required_suffix,
        "child_contract_supported": bool(supported),
    }


def _validate_descriptor_publication_contract(
    plan: DiagnosticPlan,
    reservations: _OutputReservations,
    contract: Mapping[str, Any],
    *,
    child_pid: int | None = None,
) -> dict[str, Any]:
    """Verify the contract and, when a child is live, its inherited FD map."""

    contract = _mapping(contract, "descriptor publication contract")
    _validate_output_reservations(reservations)
    allowed = {
        "schema", "protocol", "namespace", "namespace_parent", "receipt_sha256",
        "identity_sha256", "binding_sha256", "outputs", "pass_fds",
        "publication_rule", "contract_sha256", "required_argv_suffix",
        "child_contract_supported",
    }
    _reject_unknown(contract, allowed, "descriptor publication contract")
    _exact(contract, "schema", DESCRIPTOR_PUBLICATION_SCHEMA, "descriptor publication contract")
    _exact(contract, "protocol", DESCRIPTOR_PUBLICATION_PROTOCOL, "descriptor publication contract")
    _exact(contract, "namespace", str(plan.namespace), "descriptor publication contract")
    _exact(contract, "receipt_sha256", _plan_receipt_field(plan, "receipt_sha256"), "descriptor publication contract")
    _exact(contract, "identity_sha256", _plan_receipt_field(plan, "identity_sha256"), "descriptor publication contract")
    _exact(contract, "binding_sha256", _plan_binding_value(plan), "descriptor publication contract")
    _exact(contract, "publication_rule", "child_must_write_inherited_fd_without_path_reopen_or_replace", "descriptor publication contract")
    _sha256_hex(contract.get("contract_sha256"), "descriptor publication contract.contract_sha256")
    parent = _mapping(contract.get("namespace_parent"), "descriptor publication contract.namespace_parent")
    _reject_unknown(parent, {"dev", "ino"}, "descriptor publication contract.namespace_parent")
    if type(parent.get("dev")) is not int or type(parent.get("ino")) is not int:
        _fail("descriptor publication parent identity must be integer-valued")
    outputs = _mapping(contract.get("outputs"), "descriptor publication contract.outputs")
    if set(outputs) != set(EVALUATOR_OUTPUT_NAMES):
        _fail("descriptor publication contract.outputs must cover every evaluator output")
    pass_fds = contract.get("pass_fds")
    if not isinstance(pass_fds, list) or pass_fds != list(reservations.pass_fds):
        _fail("descriptor publication pass_fds drifted")
    for name in EVALUATOR_OUTPUT_NAMES:
        observed = _mapping(outputs.get(name), f"descriptor publication contract.outputs.{name}")
        _reject_unknown(
            observed,
            {
                "path", "fd", "dev", "ino", "mode", "uid", "gid", "nlink",
                "parent_dev", "parent_ino", "stable_fd", "fd_identity_stable",
                "path_reopened", "publication",
            },
            f"descriptor publication contract.outputs.{name}",
        )
        item = reservations.outputs[name]
        expected = dict(_publication_fd_identity(item, os.fstat(reservations.parent_fd), name))
        if dict(observed) != expected:
            _fail(f"descriptor publication contract output {name!r} drifted")
    core = {key: contract[key] for key in (
        "schema", "protocol", "namespace", "namespace_parent", "receipt_sha256",
        "identity_sha256", "binding_sha256", "outputs", "pass_fds", "publication_rule",
    )}
    if contract.get("contract_sha256") != canonical_digest(core):
        _fail("descriptor publication contract digest drifted")
    required_suffix = contract.get("required_argv_suffix")
    if not isinstance(required_suffix, list) or any(not isinstance(item, str) for item in required_suffix):
        _fail("descriptor publication contract required_argv_suffix is malformed")
    expected_suffix = [DESCRIPTOR_PUBLICATION_ARGUMENT, str(contract["contract_sha256"])]
    for name in EVALUATOR_OUTPUT_NAMES:
        expected_suffix.extend([DESCRIPTOR_PUBLICATION_FD_ARGUMENTS[name], str(reservations.outputs[name].fd)])
    if required_suffix != expected_suffix:
        _fail("descriptor publication contract argv suffix drifted")
    command = tuple(getattr(plan, "command", ()))
    supported = tuple(command[-len(expected_suffix):]) == tuple(expected_suffix)
    if contract.get("child_contract_supported") is not supported:
        _fail("descriptor publication child support attestation drifted")
    result = {
        "schema": DESCRIPTOR_PUBLICATION_SCHEMA,
        "protocol": DESCRIPTOR_PUBLICATION_PROTOCOL,
        "contract_sha256": str(contract["contract_sha256"]),
        "contract": dict(contract),
        "child_pid": child_pid,
        "publication_attested": False,
        "fd_bindings": {},
    }
    if child_pid is not None:
        if type(child_pid) is not int or child_pid <= 0:
            _fail("descriptor publication child PID must be positive")
        for name in EVALUATOR_OUTPUT_NAMES:
            item = reservations.outputs[name]
            proc_fd = Path(f"/proc/{child_pid}/fd/{item.fd}")
            try:
                target = os.readlink(proc_fd)
                info = os.stat(proc_fd)
            except OSError as error:
                _fail(f"child descriptor publication for {name!r} is unavailable: {error}")
            expected = _mapping(outputs[name], f"descriptor publication contract.outputs.{name}")
            if target != str(item.path):
                _fail(f"child descriptor publication for {name!r} reopened or replaced the path")
            observed_identity = {
                "dev": int(info.st_dev),
                "ino": int(info.st_ino),
                "mode": int(stat.S_IMODE(info.st_mode)),
                "uid": int(info.st_uid),
                "gid": int(info.st_gid),
                "nlink": int(info.st_nlink),
            }
            for key, observed_value in observed_identity.items():
                if observed_value != int(expected[key]):
                    _fail(f"child descriptor publication for {name!r} drifted at {key}")
            result["fd_bindings"][name] = {
                "fd": int(item.fd),
                "path": target,
                **observed_identity,
            }
        result["publication_attested"] = True
    return result


def _reject_unsupported_descriptor_publication(contract: Mapping[str, Any]) -> None:
    del contract
    _fail("evaluator output publication is pathname-only; descriptor-bound child attestation is absent")


def _assert_path_absent(parent_fd: int, path: Path, name: str) -> None:
    """Check one output leaf through its already-open parent directory."""

    try:
        os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    except OSError as error:
        _fail(f"cannot inspect fresh {name} output: {error}")
    _fail(f"fresh {name} output already exists: {path}")


def _assert_outputs_absent(namespace: Path, outputs: Mapping[str, Path]) -> None:
    for name, path in outputs.items():
        if path.parent != namespace.parent or not path.name.startswith(namespace.name + "-"):
            _fail(f"output.{name} is not beside the bound namespace")
    parent_fd = _open_directory(namespace.parent, "diagnostic output parent")
    try:
        for name, path in outputs.items():
            _assert_path_absent(parent_fd, path, name)
    finally:
        try:
            os.close(parent_fd)
        except OSError:
            pass


def _reserve_evaluator_outputs(plan: DiagnosticPlan) -> _OutputReservations:
    """Reserve evaluator leaves before Popen and retain their descriptors.

    A pathname-only child cannot consume this reservation safely: it can
    unlink/replace the leaf before opening it, and the current core evaluator
    publishes through its own pathname-based atomic publisher.  The caller
    must therefore pass these descriptors to an explicitly descriptor-bound
    child contract; otherwise ``_require_descriptor_bound_outputs`` rejects
    the launch before Popen.
    """

    for name in EVALUATOR_OUTPUT_NAMES:
        if name not in plan.outputs:
            _fail(f"evaluator output {name!r} is absent from the plan")
    for name, path in plan.outputs.items():
        _validate_output_shape(plan, path, f"output.{name}")
    parent_fd = _open_directory(plan.namespace.parent, "diagnostic output reservation parent")
    flags = (
        os.O_RDWR
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    opened: dict[str, _ReservedOutput] = {}
    try:
        for name in EVALUATOR_OUTPUT_NAMES:
            path = plan.outputs[name]
            try:
                fd = os.open(path.name, flags, 0o600, dir_fd=parent_fd)
            except FileExistsError:
                _fail(f"refusing to reserve reused evaluator output: {path}")
            except OSError as error:
                _fail(f"cannot reserve evaluator output {path}: {error}")
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_uid != os.getuid()
                or info.st_gid != os.getgid()
            ):
                os.close(fd)
                _fail(f"reserved evaluator output identity is unsafe: {path}")
            path_info = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
            if _fd_identity(path_info) != _fd_identity(info):
                os.close(fd)
                _fail(f"reserved evaluator output path changed: {path}")
            opened[name] = _ReservedOutput(
                name=name,
                path=path,
                fd=fd,
                descriptor={
                    "path": str(path),
                    "dev": int(info.st_dev),
                    "ino": int(info.st_ino),
                    "bytes": int(info.st_size),
                    "mode": int(stat.S_IMODE(info.st_mode)),
                    "uid": int(info.st_uid),
                    "gid": int(info.st_gid),
                    "nlink": int(info.st_nlink),
                    "mtime_ns": int(info.st_mtime_ns),
                    "stable_fd": True,
                    "fd_identity_stable": True,
                    "path_reopened": False,
                },
            )
        provisional = _OutputReservations(
            parent_fd=parent_fd,
            outputs=dict(opened),
            publication_contract={},
        )
        contract = _descriptor_publication_contract(plan, provisional)
        return _OutputReservations(
            parent_fd=parent_fd,
            outputs=dict(opened),
            publication_contract=contract,
        )
    except BaseException:
        for item in opened.values():
            try:
                os.close(item.fd)
            except OSError:
                pass
            try:
                current = os.stat(item.path.name, dir_fd=parent_fd, follow_symlinks=False)
                if _fd_identity(current) == (
                    item.descriptor["dev"], item.descriptor["ino"],
                    item.descriptor["mode"], item.descriptor["nlink"],
                    item.descriptor["bytes"], item.descriptor["mtime_ns"],
                ):
                    os.unlink(item.path.name, dir_fd=parent_fd)
            except (FileNotFoundError, OSError):
                pass
        try:
            os.close(parent_fd)
        except OSError:
            pass
        raise


def _validate_output_reservations(reservations: _OutputReservations) -> None:
    for name in EVALUATOR_OUTPUT_NAMES:
        item = reservations.outputs.get(name)
        if item is None:
            _fail(f"evaluator output reservation {name!r} is missing")
        info = os.fstat(item.fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_uid != os.getuid()
            or info.st_gid != os.getgid()
        ):
            _fail(f"evaluator output reservation {name!r} identity drifted")
        path_info = os.stat(item.path.name, dir_fd=reservations.parent_fd, follow_symlinks=False)
        if _fd_identity(path_info) != _fd_identity(info):
            _fail(f"evaluator output reservation {name!r} path identity drifted")


def _release_output_reservations(reservations: _OutputReservations, *, remove_unpublished: bool) -> None:
    """Close reservation descriptors; remove only an unchanged unpublished leaf."""

    if remove_unpublished:
        for item in reservations.outputs.values():
            try:
                path_info = os.stat(item.path.name, dir_fd=reservations.parent_fd, follow_symlinks=False)
                info = os.fstat(item.fd)
                if _fd_identity(path_info) == _fd_identity(info):
                    os.unlink(item.path.name, dir_fd=reservations.parent_fd)
            except (FileNotFoundError, OSError):
                pass
    for item in reservations.outputs.values():
        try:
            os.close(item.fd)
        except OSError:
            pass
    try:
        os.close(reservations.parent_fd)
    except OSError:
        pass


def _require_descriptor_bound_outputs(
    plan: DiagnosticPlan,
    reservations: _OutputReservations,
) -> Mapping[str, Any]:
    """Require an explicit inherited-FD/inode contract before Popen."""

    _validate_output_reservations(reservations)
    contract = _validate_descriptor_publication_contract(
        plan,
        reservations,
        reservations.publication_contract,
    )
    if contract["publication_attested"] or bool(reservations.publication_contract.get("child_contract_supported")):
        return reservations.publication_contract
    _reject_unsupported_descriptor_publication(reservations.publication_contract)
    return reservations.publication_contract


def _validate_command(identity: Mapping[str, Any], outputs: Mapping[str, Path]) -> tuple[tuple[str, ...], dict[str, str]]:
    command = _mapping(identity.get("command"), "identity.command")
    argv_value = command.get("argv")
    if not isinstance(argv_value, list) or not argv_value or any(not isinstance(item, str) for item in argv_value):
        _fail("identity.command.argv must be a non-empty string list")
    argv = tuple(argv_value)
    if any(not item or "\x00" in item for item in argv):
        _fail("identity.command.argv contains an empty or NUL-containing argument")
    root = _absolute(identity.get("root"), "identity.root")
    if _absolute(command.get("cwd"), "identity.command.cwd") != root:
        _fail("identity command cwd is not the bound lab root")
    env = dict(_mapping(command.get("env_overrides"), "identity.command.env_overrides"))
    expected_env = {
        "CUDA_VISIBLE_DEVICES": str(GPU_INDEX),
        "CUDA_DEVICE_ORDER": str(getattr(admission, "CUDA_DEVICE_ORDER", "PCI_BUS_ID")),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    if env != expected_env:
        _fail("identity command environment drifted")
    environment_record = _mapping(identity.get("environment"), "identity.environment")
    _exact(environment_record, "policy", "allowlist_only_no_ambient_inheritance", "identity.environment")
    _exact(environment_record, "inherit", False, "identity.environment")
    if dict(_mapping(environment_record.get("variables"), "identity.environment.variables")) != env:
        _fail("identity environment allowlist differs from command environment")
    environment_core = {key: value for key, value in environment_record.items() if key != "sha256"}
    if environment_record.get("sha256") != canonical_digest(environment_core):
        _fail("identity environment digest drifted")
    if command.get("sha256") != admission._command_digest(argv, str(command.get("cwd")), env):
        _fail("identity command digest drifted")
    expected_options = {
        "--manifest": str(_mapping(identity["manifest"], "identity.manifest")["path"]),
        "--data-root": str(identity["root"]),
        "--checkpoint": str(_mapping(identity["checkpoint"], "identity.checkpoint")["path"]),
        "--case-id": CASE_ID,
        "--split": SPLIT,
        "--maximum-steps": str(TRANSITIONS),
        "--device": "cuda:0",
        "--trajectory-output": str(outputs["trajectory"]),
        "--progress-output": str(outputs["progress"]),
        "--output": str(outputs["evaluation"]),
    }
    for option, expected in expected_options.items():
        positions = [i for i, item in enumerate(argv) if item == option]
        if len(positions) != 1 or positions[0] + 1 >= len(argv) or argv[positions[0] + 1] != expected:
            _fail(f"exact command is not bound to {option}={expected}")
    expected_argv = (
        argv[0],
        "-u",
        str(root / "scripts" / "core_learning.py"),
        "evaluate",
        "--manifest",
        str(_mapping(identity["manifest"], "identity.manifest")["path"]),
        "--data-root",
        str(root),
        "--checkpoint",
        str(_mapping(identity["checkpoint"], "identity.checkpoint")["path"]),
        "--case-id",
        CASE_ID,
        "--split",
        SPLIT,
        "--maximum-steps",
        str(TRANSITIONS),
        "--chunk-size",
        str(admission.launcher.CHUNK_SIZE),
        "--device",
        "cuda:0",
        "--progress-every",
        str(admission.launcher.PROGRESS_EVERY),
        "--trajectory-output",
        str(outputs["trajectory"]),
        "--progress-output",
        str(outputs["progress"]),
        "--output",
        str(outputs["evaluation"]),
        "--diagnostic",
    )
    if argv != expected_argv:
        # A future descriptor-aware child may append only this fixed contract
        # suffix.  The current core child has no such suffix and is therefore
        # still rejected by _require_descriptor_bound_outputs after planning.
        suffix = argv[len(expected_argv):] if argv[:len(expected_argv)] == expected_argv else ()
        expected_suffix_length = 2 + 2 * len(EVALUATOR_OUTPUT_NAMES)
        if len(suffix) != expected_suffix_length or suffix[0] != DESCRIPTOR_PUBLICATION_ARGUMENT:
            _fail("identity command is not the exact current-manifest evaluator argv")
        _sha256_hex(suffix[1], "identity command descriptor contract digest")
        for offset, name in enumerate(EVALUATOR_OUTPUT_NAMES):
            flag = suffix[2 + 2 * offset]
            raw_fd = suffix[3 + 2 * offset]
            if flag != DESCRIPTOR_PUBLICATION_FD_ARGUMENTS[name] or not raw_fd.isdigit() or int(raw_fd) < 0:
                _fail("identity command descriptor publication FD mapping drifted")
    return argv, env


@dataclass(frozen=True)
class DiagnosticPlan:
    receipt_path: Path
    receipt: Mapping[str, Any]
    namespace: Path
    outputs: Mapping[str, Path]
    command: tuple[str, ...]
    env: Mapping[str, str]
    root: Path
    static_validation: Mapping[str, Any]
    input_descriptors: Mapping[str, Mapping[str, Any]]
    executable_descriptor: Mapping[str, Any]
    cwd_descriptor: Mapping[str, Any]
    gpu_identity: Mapping[str, Any]
    effective_env_sha256: str
    effective_env_keys: tuple[str, ...]
    binding_sha256: str

    @property
    def identity(self) -> Mapping[str, Any]:
        return _mapping(self.receipt["identity"], "identity")


def _directory_descriptor(path: Path, name: str) -> dict[str, Any]:
    fd = _open_directory(path, name)
    parent_fd = _open_directory(path.parent, f"{name} parent")
    try:
        info = os.fstat(fd)
        parent_info = os.fstat(parent_fd)
        if not stat.S_ISDIR(info.st_mode):
            _fail(f"{name} is not a directory")
        return {
            "path": str(_absolute(path, name)),
            "dev": int(info.st_dev),
            "ino": int(info.st_ino),
            "mode": int(stat.S_IMODE(info.st_mode)),
            "uid": int(info.st_uid),
            "gid": int(info.st_gid),
            "nlink": int(info.st_nlink),
            "mtime_ns": int(info.st_mtime_ns),
            "parent_dev": int(parent_info.st_dev),
            "parent_ino": int(parent_info.st_ino),
            "stable_fd": True,
            "fd_identity_stable": True,
            "path_reopened": False,
        }
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.close(parent_fd)
        except OSError:
            pass


def _bounded_scope(path: Path, root: Path, name: str) -> Path:
    if _under(path, root):
        return root
    tmp_root = ARTIFACT_ROOT
    if _under(path, tmp_root):
        return tmp_root
    _fail(f"{name} escapes the lab and /tmp roots")


def _effective_environment(overrides: Mapping[str, str]) -> dict[str, str]:
    if any(not isinstance(key, str) or not isinstance(value, str) for key, value in overrides.items()):
        _fail("command environment overrides must be string-to-string")
    # The admission contract is an allowlist-only environment.  Inheriting
    # ambient variables would make the Popen identity incomplete.
    environment = {str(key): str(value) for key, value in overrides.items()}
    if any("\x00" in key or "\x00" in value or "=" in key for key, value in environment.items()):
        _fail("effective environment contains an invalid NUL or key")
    return environment


def _environment_digest(environment: Mapping[str, str]) -> str:
    return canonical_digest({"entries": [[key, environment[key]] for key in sorted(environment)]})


def _validate_gpu_identity(value: Mapping[str, Any], name: str = "resource_admission.gpu") -> dict[str, Any]:
    """Validate the physical/logical GPU mapping without treating it as live proof."""

    gpu = dict(_mapping(value, name))
    required = (
        "physical_index", "uuid", "pci_bus_id", "logical_index",
        "cuda_visible_devices", "cuda_device", "cuda_device_order",
        "identity_source", "identity_attested", "identity_sha256",
    )
    for key in required:
        if key not in gpu:
            _fail(f"{name}.{key} is missing")
    if type(gpu["physical_index"]) is not int or gpu["physical_index"] != GPU_INDEX:
        _fail(f"{name}.physical_index is not bound to GPU{GPU_INDEX}")
    uuid = gpu["uuid"]
    if not isinstance(uuid, str) or GPU_UUID_RE.fullmatch(uuid) is None:
        _fail(f"{name}.uuid is not a canonical GPU UUID")
    pci = gpu["pci_bus_id"]
    if not isinstance(pci, str) or PCI_BUS_RE.fullmatch(pci) is None:
        _fail(f"{name}.pci_bus_id is not canonical")
    if type(gpu["logical_index"]) is not int or gpu["logical_index"] != 0:
        _fail(f"{name}.logical_index is not cuda:0")
    _exact(gpu, "cuda_visible_devices", str(GPU_INDEX), name)
    _exact(gpu, "cuda_device", "cuda:0", name)
    _exact(gpu, "cuda_device_order", getattr(admission, "CUDA_DEVICE_ORDER", "PCI_BUS_ID"), name)
    _exact(gpu, "identity_source", "scheduler_owned_snapshot", name)
    _exact(gpu, "identity_attested", True, name)
    expected_digest = admission.canonical_digest(admission._gpu_identity(gpu))
    _exact(gpu, "identity_sha256", expected_digest, name)
    return {
        key: gpu[key]
        for key in (
            "physical_index", "uuid", "pci_bus_id", "logical_index",
            "cuda_visible_devices", "cuda_device", "cuda_device_order",
            "identity_source", "identity_attested", "identity_sha256",
        )
    }


def _snapshot_bound_inputs(
    root: Path,
    identity: Mapping[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any], dict[str, Any], str, tuple[str, ...], dict[str, Any]]:
    manifest_record = _mapping(identity["manifest"], "identity.manifest")
    training_record = _mapping(identity["training_receipt"], "identity.training_receipt")
    checkpoint_record = _mapping(identity["checkpoint"], "identity.checkpoint")
    manifest = _absolute(manifest_record["path"], "manifest")
    training = _absolute(training_record["path"], "training receipt")
    checkpoint = _absolute(checkpoint_record["path"], "checkpoint")

    manifest_desc, manifest_raw = _stable_artifact(
        manifest,
        _bounded_scope(manifest, root, "manifest"),
        "manifest",
        max_bytes=MAX_JSON_BYTES,
    )
    training_desc, training_raw = _stable_artifact(
        training,
        _bounded_scope(training, root, "training receipt"),
        "training receipt",
        max_bytes=MAX_JSON_BYTES,
    )
    checkpoint_desc, _checkpoint_raw = _stable_artifact(
        checkpoint,
        _bounded_scope(checkpoint, root, "checkpoint"),
        "checkpoint",
        max_bytes=admission.MAX_CHECKPOINT_BYTES,
        read_content=False,
    )
    _descriptor_matches(manifest_desc, _mapping(manifest_record["file"], "identity.manifest.file"), "manifest")
    _descriptor_matches(training_desc, _mapping(training_record["file"], "identity.training_receipt.file"), "training receipt")
    _descriptor_matches(checkpoint_desc, _mapping(checkpoint_record["file"], "identity.checkpoint.file"), "checkpoint")
    if checkpoint_desc["sha256"] != checkpoint_record["sha256"] or checkpoint_desc["bytes"] != checkpoint_record["bytes"]:
        _fail("checkpoint content identity differs from the admission receipt")

    manifest_payload = _json_bytes(manifest_raw, "manifest")
    training_payload = _json_bytes(training_raw, "training receipt")
    _exact(manifest_payload, "schema", admission.MANIFEST_SCHEMA, "manifest")
    _exact(training_payload, "schema", admission.TRAINING_SCHEMA, "training receipt")
    manifest_canonical = canonical_digest(manifest_payload)
    if manifest_canonical != manifest_record["canonical_sha256"]:
        _fail("manifest canonical content SHA differs from the admission receipt")

    sources = _mapping(identity["source_sha256"], "identity.source_sha256")
    executable = _absolute(_mapping(identity["command"], "identity.command")["argv"][0], "executable")
    core_learning = root / "scripts" / "core_learning.py"
    executable_desc, _ = _stable_artifact(
        executable,
        root,
        "executable",
        max_bytes=MAX_EXECUTABLE_BYTES,
        allow_leaf_symlink=True,
        read_content=False,
    )
    executable_record = identity.get("executable")
    if isinstance(executable_record, Mapping):
        _descriptor_matches(executable_desc, _mapping(executable_record.get("file"), "identity.executable.file"), "executable")
        _exact(executable_record, "path", str(executable), "identity.executable")
        _exact(executable_record, "sha256", executable_desc["sha256"], "identity.executable")
    core_desc, _ = _stable_artifact(
        core_learning,
        root,
        "core_learning executable script",
        max_bytes=admission.MAX_SOURCE_BYTES,
        read_content=False,
    )
    _descriptor_matches(core_desc, _mapping(sources["core_learning"], "identity.source_sha256.core_learning"), "core_learning")

    namespace_path = _absolute(identity["namespace"], "identity.namespace")
    namespace_desc = _directory_descriptor(namespace_path, "namespace")
    namespace_record = identity.get("namespace_descriptor")
    if isinstance(namespace_record, Mapping):
        for key in ("path", "dev", "ino", "mode", "uid", "gid", "nlink", "parent_dev", "parent_ino"):
            if namespace_desc.get(key) != namespace_record.get(key):
                _fail(f"namespace descriptor field {key} drifted")
    input_descriptors = {
        "manifest": manifest_desc,
        "training_receipt": training_desc,
        "checkpoint": checkpoint_desc,
        "core_learning": core_desc,
        "namespace": namespace_desc,
    }
    environment = _effective_environment(_mapping(identity["command"], "identity.command")["env_overrides"])
    environment_sha256 = _environment_digest(environment)
    cwd_desc = _directory_descriptor(root, "command cwd")
    binding_core = {
        "receipt_sha256": identity.get("receipt_sha256"),
        "identity_sha256": identity.get("identity_sha256"),
        "root": str(root),
        "namespace": str(identity["namespace"]),
        "nonce": identity["nonce"],
        "command": dict(identity["command"]),
        "input_descriptors": input_descriptors,
        "executable": executable_desc,
        "cwd": cwd_desc,
        "effective_env_sha256": environment_sha256,
    }
    return input_descriptors, executable_desc, cwd_desc, environment_sha256, tuple(sorted(environment)), binding_core


def _binding_digest(plan: DiagnosticPlan) -> str:
    return canonical_digest({
        "receipt_sha256": plan.receipt["receipt_sha256"],
        "identity_sha256": plan.receipt["identity_sha256"],
        "input_descriptors": dict(plan.input_descriptors),
        "executable_descriptor": dict(plan.executable_descriptor),
        "cwd_descriptor": dict(plan.cwd_descriptor),
        "gpu_identity": dict(plan.gpu_identity),
        "effective_env_sha256": plan.effective_env_sha256,
        "command": list(plan.command),
        "env_overrides": dict(plan.env),
        "root": str(plan.root),
        "namespace": str(plan.namespace),
        "nonce": plan.identity["nonce"],
    })


def build_plan(receipt_path: Path | str, *, resource_admission: Mapping[str, Any] | None = None) -> DiagnosticPlan:
    path = _absolute(receipt_path, "admission receipt")
    receipt = admission.load_receipt(path, allow_consumed=False)
    identity = _mapping(receipt["identity"], "identity")
    root = _absolute(identity["root"], "identity.root")
    namespace = _absolute(identity["namespace"], "identity.namespace")
    _directory_descriptor(namespace, "receipt namespace")
    outputs = _outputs(namespace)
    command, env = _validate_command(identity, outputs)
    _assert_outputs_absent(namespace, outputs)
    static_resource = resource_admission if resource_admission is not None else identity["resource_snapshot"]
    revalidated = admission.revalidate_receipt(receipt, resource_admission=static_resource, check_files=True)
    revalidated_resource = _mapping(revalidated.get("resource_snapshot"), "revalidated.resource_snapshot")
    gpu_identity = _validate_gpu_identity(_mapping(revalidated_resource.get("gpu"), "revalidated.resource_snapshot.gpu"))
    input_descriptors, executable_descriptor, cwd_descriptor, env_sha256, env_keys, _binding_core = _snapshot_bound_inputs(root, identity)
    provisional = DiagnosticPlan(
        receipt_path=path,
        receipt=receipt,
        namespace=namespace,
        outputs=outputs,
        command=command,
        env=env,
        root=root,
        static_validation=revalidated,
        input_descriptors=input_descriptors,
        executable_descriptor=executable_descriptor,
        cwd_descriptor=cwd_descriptor,
        gpu_identity=gpu_identity,
        effective_env_sha256=env_sha256,
        effective_env_keys=env_keys,
        binding_sha256="",
    )
    return DiagnosticPlan(
        **{**provisional.__dict__, "binding_sha256": _binding_digest(provisional)},
    )


def _verify_consumed_capability(plan: DiagnosticPlan, capability: admission.AdmissionCapability) -> None:
    if type(capability) is not admission.AdmissionCapability:
        _fail("diagnostic execution requires the internal receipt-bound capability")
    if capability.receipt_path != plan.receipt_path or capability.receipt.get("receipt_sha256") != plan.receipt.get("receipt_sha256"):
        _fail("capability is bound to a different receipt")
    consumed = capability.consumed_marker
    if consumed != Path(_mapping(plan.receipt["consumption"], "consumption")["consumed_marker"]):
        _fail("capability consumed marker drifted")
    descriptor, raw = _stable_artifact(consumed, plan.namespace, "consumed marker", max_bytes=64 * 1024)
    if descriptor["mode"] != 0o600 or descriptor["uid"] != os.getuid() or descriptor["gid"] != os.getgid():
        _fail("one-shot consumed marker owner/mode identity drifted")
    payload = _json_bytes(raw, "consumed marker")
    _exact(payload, "schema", admission.CONSUMED_SCHEMA, "consumed marker")
    _exact(payload, "receipt_sha256", plan.receipt["receipt_sha256"], "consumed marker")
    _exact(payload, "receipt_path", str(plan.receipt_path), "consumed marker")
    _exact(payload, "namespace", str(plan.namespace), "consumed marker")
    _exact(payload, "nonce", plan.identity["nonce"], "consumed marker")
    _exact(payload, "diagnostic_only", True, "consumed marker")
    _exact(payload, "credit", 0, "consumed marker")
    expected_seal = admission._capability_seal(plan.receipt, {
        "path": str(consumed),
        "dev": int(descriptor["dev"]),
        "ino": int(descriptor["ino"]),
        "bytes": int(descriptor["bytes"]),
        "mode": int(descriptor["mode"]),
        "uid": int(descriptor["uid"]),
        "gid": int(descriptor["gid"]),
        "nlink": int(descriptor["nlink"]),
        "mtime_ns": int(descriptor["mtime_ns"]),
        "sha256": str(descriptor["sha256"]),
    })
    if capability.seal != expected_seal:
        _fail("receipt-bound capability seal drifted")


def _revalidate_bound_identity(plan: DiagnosticPlan, resource_snapshot: Mapping[str, Any]) -> None:
    current = admission.revalidate_receipt(plan.receipt, resource_admission=resource_snapshot, check_files=True)
    del current
    observed_gpu = _validate_gpu_identity(
        _mapping(_mapping(resource_snapshot, "resource_snapshot").get("gpu"), "resource_snapshot.gpu")
    )
    if observed_gpu != dict(plan.gpu_identity):
        _fail("live GPU UUID/PCI identity differs from the receipt-bound GPU identity")
    identity = plan.identity
    inputs, executable, cwd, environment_sha256, environment_keys, _binding_core = _snapshot_bound_inputs(plan.root, identity)
    for name, expected in plan.input_descriptors.items():
        observed = inputs.get(name)
        if observed is None or dict(observed) != dict(expected):
            _fail(f"bound input descriptor changed: {name}")
    if dict(executable) != dict(plan.executable_descriptor):
        _fail("bound executable descriptor changed")
    if dict(cwd) != dict(plan.cwd_descriptor):
        _fail("bound cwd descriptor changed")
    if environment_sha256 != plan.effective_env_sha256 or environment_keys != plan.effective_env_keys:
        _fail("complete effective environment identity changed")
    if _binding_digest(plan) != plan.binding_sha256:
        _fail("complete execution identity binding digest drifted")


def _revalidate_before_popen(
    plan: DiagnosticPlan,
    capability: admission.AdmissionCapability,
) -> tuple[Mapping[str, Any], _OutputReservations]:
    probed = admission.resource.probe_resource_admission(GPU_INDEX, root=plan.root)
    current, _live_gpu = _resource_with_live_gpu_identity(probed, plan.gpu_identity)
    _revalidate_bound_identity(plan, current)
    _verify_consumed_capability(plan, capability)
    reservations = _reserve_evaluator_outputs(plan)
    try:
        _require_descriptor_bound_outputs(plan, reservations)
    except BaseException:
        _release_output_reservations(reservations, remove_unpublished=True)
        raise
    return current, reservations


class _SealedProcessWitness:
    """An immutable witness minted only after the captured real lifecycle."""

    __slots__ = (
        "process", "pid", "pid_starttime", "returncode", "wait_returncode",
        "wait_observed", "command", "command_sha256", "cwd", "cwd_descriptor",
        "env_overrides", "effective_env_sha256", "executable_descriptor",
        "input_descriptors", "binding_sha256", "receipt_sha256", "identity_sha256",
        "namespace", "nonce", "runtime_identity", "_seal",
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("_SealedProcessWitness is an internal real-Popen witness")

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("_SealedProcessWitness is immutable")


def _runtime_payload(witness: _SealedProcessWitness) -> dict[str, Any]:
    return {
        "process_object_id": id(witness.process),
        "process_type": f"{type(witness.process).__module__}.{type(witness.process).__qualname__}",
        "pid": witness.pid,
        "pid_starttime": witness.pid_starttime,
        "returncode": witness.returncode,
        "wait_returncode": witness.wait_returncode,
        "wait_observed": witness.wait_observed,
        "command": list(witness.command),
        "command_sha256": witness.command_sha256,
        "cwd": witness.cwd,
        "cwd_descriptor": dict(witness.cwd_descriptor),
        "env_overrides": dict(witness.env_overrides),
        "effective_env_sha256": witness.effective_env_sha256,
        "executable_descriptor": dict(witness.executable_descriptor),
        "input_descriptors": {key: dict(value) for key, value in witness.input_descriptors.items()},
        "binding_sha256": witness.binding_sha256,
        "receipt_sha256": witness.receipt_sha256,
        "identity_sha256": witness.identity_sha256,
        "namespace": witness.namespace,
        "nonce": witness.nonce,
        "runtime_identity": dict(witness.runtime_identity),
    }


def _witness_seal(payload: Mapping[str, Any]) -> str:
    return hmac.new(
        _PROCESS_WITNESS_SECRET,
        canonical_json(dict(payload)).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _proc_starttime(pid: int) -> str:
    stat_path = Path("/proc") / str(pid) / "stat"
    try:
        raw = stat_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        _fail(f"cannot read sealed process starttime: {error}")
    closing = raw.rfind(")")
    if closing < 0:
        _fail("sealed process stat record is malformed")
    fields = raw[closing + 2 :].split()
    # The suffix starts at stat field 3; starttime is field 22.
    if len(fields) <= 19:
        _fail("sealed process stat record lacks starttime")
    return fields[19]


def _parse_nvidia_smi_gpu_rows(stdout: str) -> dict[int, dict[str, Any]]:
    if not isinstance(stdout, str):
        _fail("nvidia-smi GPU probe did not return text")
    rows: dict[int, dict[str, Any]] = {}
    for line in stdout.splitlines():
        if not line.strip():
            continue
        fields = [item.strip() for item in line.split(",")]
        if len(fields) != 6:
            _fail("nvidia-smi GPU probe returned a malformed row")
        try:
            index, total, used, free = (int(fields[item]) for item in (0, 3, 4, 5))
        except (TypeError, ValueError):
            _fail("nvidia-smi GPU probe returned a non-integer row")
        uuid = fields[1]
        pci = fields[2]
        if index < 0 or min(total, used, free) < 0 or used + free > total:
            _fail(f"nvidia-smi GPU probe returned invalid VRAM for index {index}")
        if GPU_UUID_RE.fullmatch(uuid) is None or PCI_BUS_RE.fullmatch(pci) is None:
            _fail(f"nvidia-smi GPU probe returned invalid identity for index {index}")
        if index in rows:
            _fail(f"nvidia-smi GPU probe returned duplicate index {index}")
        rows[index] = {
            "physical_index": index,
            "uuid": uuid,
            "pci_bus_id": pci,
            "total_mib": total,
            "used_mib": used,
            "free_mib": free,
        }
    if not rows:
        _fail("nvidia-smi GPU probe returned no usable rows")
    return rows


def _parse_nvidia_smi_process_rows(stdout: str) -> list[dict[str, Any]]:
    if not isinstance(stdout, str):
        _fail("nvidia-smi process probe did not return text")
    rows: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        fields = [item.strip() for item in line.split(",")]
        if len(fields) != 2:
            _fail("nvidia-smi process probe returned a malformed row")
        try:
            pid = int(fields[0])
        except (TypeError, ValueError):
            _fail("nvidia-smi process probe returned a non-integer PID")
        uuid = fields[1]
        if pid <= 0 or GPU_UUID_RE.fullmatch(uuid) is None:
            _fail("nvidia-smi process probe returned an invalid process identity")
        rows.append({"pid": pid, "gpu_uuid": uuid})
    return rows


def _nvidia_smi_query(command: Sequence[str], name: str) -> str:
    if tuple(command[:1]) != ("nvidia-smi",):
        _fail(f"{name} executable is not the fixed nvidia-smi command")
    try:
        result = subprocess.run(
            tuple(command),
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
            close_fds=True,
            env={"LC_ALL": "C", "LANG": "C"},
        )
    except (OSError, subprocess.SubprocessError) as error:
        _fail(f"{name} failed: {error}")
    if type(result.returncode) is not int or result.returncode != 0:
        _fail(f"{name} returned non-zero status {getattr(result, 'returncode', None)!r}")
    return result.stdout


def _probe_live_gpu_identity(
    expected: Mapping[str, Any],
    *,
    child_pid: int | None = None,
) -> dict[str, Any]:
    """Observe physical UUID/PCI and optionally bind a live child PID to it."""

    expected_identity = _validate_gpu_identity(expected, "expected GPU identity")
    gpu_rows = _parse_nvidia_smi_gpu_rows(
        _nvidia_smi_query(NVIDIA_SMI_COMMAND, "nvidia-smi GPU identity probe")
    )
    row = gpu_rows.get(int(expected_identity["physical_index"]))
    if row is None:
        _fail("live nvidia-smi probe did not expose the receipt-bound physical GPU")
    for key in ("uuid", "pci_bus_id"):
        if row[key] != expected_identity[key]:
            _fail(f"live GPU {key} differs from the receipt-bound identity")
    if child_pid is not None:
        if type(child_pid) is not int or child_pid <= 0:
            _fail("child GPU attestation requires a positive PID")
        process_rows = _parse_nvidia_smi_process_rows(
            _nvidia_smi_query(NVIDIA_SMI_PROCESS_COMMAND, "nvidia-smi child GPU probe")
        )
        matches = [item for item in process_rows if item["pid"] == child_pid]
        if len(matches) != 1 or matches[0]["gpu_uuid"] != expected_identity["uuid"]:
            _fail("child PID is not live on the receipt-bound GPU UUID")
    return {
        **row,
        **expected_identity,
        "live_probe": True,
        "child_runtime_attested": child_pid is not None,
        "child_pid": child_pid,
        "probe_tool": "nvidia-smi",
        "process_query_required": child_pid is not None,
    }


def _resource_with_live_gpu_identity(
    resource_snapshot: Mapping[str, Any],
    expected: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Merge a live UUID/PCI/VRAM observation into the admission shape."""

    live = _probe_live_gpu_identity(expected)
    current = dict(resource_snapshot)
    gpu = dict(_mapping(current.get("gpu"), "resource_snapshot.gpu"))
    gpu.update({key: live[key] for key in ("total_mib", "used_mib", "free_mib")})
    gpu.update(_validate_gpu_identity(expected, "expected GPU identity"))
    current["gpu"] = gpu
    return current, live


def _validate_child_gpu_attestation(
    plan: DiagnosticPlan,
    runtime_identity: Mapping[str, Any],
    pid: int,
) -> None:
    attestation = _mapping(runtime_identity.get("gpu"), "runtime_identity.gpu")
    _exact(attestation, "live_probe", True, "runtime_identity.gpu")
    _exact(attestation, "child_runtime_attested", True, "runtime_identity.gpu")
    _exact(attestation, "child_pid", pid, "runtime_identity.gpu")
    _exact(attestation, "probe_tool", "nvidia-smi", "runtime_identity.gpu")
    for key, expected in plan.gpu_identity.items():
        _exact(attestation, key, expected, "runtime_identity.gpu")


def _capture_runtime_identity(
    process: subprocess.Popen[Any],
    plan: DiagnosticPlan,
    environment: Mapping[str, str],
    reservations: _OutputReservations,
) -> tuple[int, str, dict[str, Any]]:
    if type(process) is not _SEALED_POPEN:
        _fail("Popen did not return the captured real subprocess.Popen type")
    if process.args != list(plan.command):
        _fail("real Popen args differ from the exact receipt-bound command")
    pid = process.pid
    if type(pid) is not int or pid <= 0 or pid == os.getpid():
        _fail("real Popen returned an invalid or caller PID")
    proc_root = Path("/proc") / str(pid)
    try:
        cmdline = (proc_root / "cmdline").read_bytes().rstrip(b"\0").split(b"\0")
        expected_cmdline = [os.fsencode(item) for item in plan.command]
        if cmdline != expected_cmdline:
            _fail("sealed process command line differs from the exact command")
        executable = os.path.realpath(os.readlink(proc_root / "exe"))
        expected_executable = os.path.realpath(str(plan.executable_descriptor["resolved_path"]))
        if executable != expected_executable:
            _fail("sealed process executable differs from the bound executable")
        cwd = os.path.realpath(os.readlink(proc_root / "cwd"))
        if cwd != os.path.realpath(str(plan.root)):
            _fail("sealed process cwd differs from the bound cwd")
        raw_env = (proc_root / "environ").read_bytes().rstrip(b"\0").split(b"\0")
        expected_env = {os.fsencode(f"{key}={value}") for key, value in environment.items()}
        if set(raw_env) != expected_env:
            _fail("sealed process environment differs from the complete bound environment")
        if os.getsid(pid) != pid:
            _fail("sealed process was not created in its own session")
        starttime = _proc_starttime(pid)
    except RunnerError:
        raise
    except (OSError, UnicodeError) as error:
        _fail(f"cannot capture sealed process identity: {error}")
    publication = _validate_descriptor_publication_contract(
        plan,
        reservations,
        reservations.publication_contract,
        child_pid=pid,
    )
    child_gpu = _probe_live_gpu_identity(plan.gpu_identity, child_pid=pid)
    return pid, starttime, {
        "cmdline_sha256": hashlib.sha256(b"\0".join(cmdline)).hexdigest(),
        "executable": executable,
        "cwd": cwd,
        "environment_sha256": _environment_digest(environment),
        "session_leader": True,
        "procfs_starttime": starttime,
        "gpu": child_gpu,
        "child_runtime_gpu_attestation": True,
        "descriptor_publication": publication,
    }


def _new_sealed_witness(
    plan: DiagnosticPlan,
    process: subprocess.Popen[Any],
    wait_returncode: int,
    environment: Mapping[str, str],
    pid: int,
    pid_starttime: str,
    runtime_identity: Mapping[str, Any],
) -> _SealedProcessWitness:
    if type(process) is not _SEALED_POPEN:
        _fail("only the captured real subprocess.Popen type can mint a witness")
    if type(wait_returncode) is not int or wait_returncode != 0:
        _fail("only a natural returncode-zero wait can mint a witness")
    _validate_child_gpu_attestation(plan, runtime_identity, pid)
    returncode = _SEALED_POPEN.poll(process)
    if type(returncode) is not int or returncode != wait_returncode:
        _fail("Popen.poll differs from the observed wait return code")
    witness = object.__new__(_SealedProcessWitness)
    values = {
        "process": process,
        "pid": int(pid),
        "pid_starttime": str(pid_starttime),
        "returncode": int(returncode),
        "wait_returncode": int(wait_returncode),
        "wait_observed": True,
        "command": tuple(plan.command),
        "command_sha256": str(plan.identity["command"]["sha256"]),
        "cwd": str(plan.root),
        "cwd_descriptor": dict(plan.cwd_descriptor),
        "env_overrides": dict(plan.env),
        "effective_env_sha256": _environment_digest(environment),
        "executable_descriptor": dict(plan.executable_descriptor),
        "input_descriptors": {key: dict(value) for key, value in plan.input_descriptors.items()},
        "binding_sha256": plan.binding_sha256,
        "receipt_sha256": plan.receipt["receipt_sha256"],
        "identity_sha256": plan.receipt["identity_sha256"],
        "namespace": str(plan.namespace),
        "nonce": str(plan.identity["nonce"]),
        "runtime_identity": dict(runtime_identity),
    }
    for name, value in values.items():
        object.__setattr__(witness, name, value)
    object.__setattr__(witness, "_seal", _witness_seal(_runtime_payload(witness)))
    return witness


def _validate_recorded_descriptor_publication(
    plan: DiagnosticPlan,
    runtime_identity: Mapping[str, Any],
    pid: int,
) -> Mapping[str, Any]:
    """Validate the serialized child FD publication witness after wait."""

    publication = _mapping(runtime_identity.get("descriptor_publication"), "runtime_identity.descriptor_publication")
    _reject_unknown(
        publication,
        {"schema", "protocol", "contract_sha256", "contract", "child_pid", "publication_attested", "fd_bindings"},
        "runtime_identity.descriptor_publication",
    )
    _exact(publication, "schema", DESCRIPTOR_PUBLICATION_SCHEMA, "runtime_identity.descriptor_publication")
    _exact(publication, "protocol", DESCRIPTOR_PUBLICATION_PROTOCOL, "runtime_identity.descriptor_publication")
    _exact(publication, "contract_sha256", _mapping(publication.get("contract"), "runtime_identity.descriptor_publication.contract").get("contract_sha256"), "runtime_identity.descriptor_publication")
    _exact(publication, "child_pid", pid, "runtime_identity.descriptor_publication")
    _exact(publication, "publication_attested", True, "runtime_identity.descriptor_publication")
    contract = _mapping(publication.get("contract"), "runtime_identity.descriptor_publication.contract")
    allowed_contract = {
        "schema", "protocol", "namespace", "namespace_parent", "receipt_sha256",
        "identity_sha256", "binding_sha256", "outputs", "pass_fds",
        "publication_rule", "contract_sha256", "required_argv_suffix",
        "child_contract_supported",
    }
    _reject_unknown(contract, allowed_contract, "runtime_identity.descriptor_publication.contract")
    _exact(contract, "schema", DESCRIPTOR_PUBLICATION_SCHEMA, "runtime_identity.descriptor_publication.contract")
    _exact(contract, "protocol", DESCRIPTOR_PUBLICATION_PROTOCOL, "runtime_identity.descriptor_publication.contract")
    _exact(contract, "namespace", str(plan.namespace), "runtime_identity.descriptor_publication.contract")
    _exact(contract, "receipt_sha256", plan.receipt["receipt_sha256"], "runtime_identity.descriptor_publication.contract")
    _exact(contract, "identity_sha256", plan.receipt["identity_sha256"], "runtime_identity.descriptor_publication.contract")
    _exact(contract, "binding_sha256", plan.binding_sha256, "runtime_identity.descriptor_publication.contract")
    _exact(contract, "publication_rule", "child_must_write_inherited_fd_without_path_reopen_or_replace", "runtime_identity.descriptor_publication.contract")
    _exact(contract, "child_contract_supported", True, "runtime_identity.descriptor_publication.contract")
    _sha256_hex(contract.get("contract_sha256"), "runtime_identity.descriptor_publication.contract.contract_sha256")
    core = {key: contract[key] for key in (
        "schema", "protocol", "namespace", "namespace_parent", "receipt_sha256",
        "identity_sha256", "binding_sha256", "outputs", "pass_fds", "publication_rule",
    )}
    if contract["contract_sha256"] != canonical_digest(core):
        _fail("serialized descriptor publication contract digest drifted")
    if publication["contract_sha256"] != contract["contract_sha256"]:
        _fail("serialized descriptor publication contract reference drifted")
    outputs = _mapping(contract.get("outputs"), "runtime_identity.descriptor_publication.contract.outputs")
    if set(outputs) != set(EVALUATOR_OUTPUT_NAMES):
        _fail("serialized descriptor publication contract does not cover every output")
    pass_fds = contract.get("pass_fds")
    if not isinstance(pass_fds, list) or any(type(fd) is not int or fd < 0 for fd in pass_fds):
        _fail("serialized descriptor publication pass_fds is malformed")
    required_suffix = contract.get("required_argv_suffix")
    expected_suffix = [DESCRIPTOR_PUBLICATION_ARGUMENT, str(contract["contract_sha256"])]
    for name in EVALUATOR_OUTPUT_NAMES:
        expected_suffix.extend([DESCRIPTOR_PUBLICATION_FD_ARGUMENTS[name], str(_mapping(outputs[name], f"output {name}")["fd"])])
    if required_suffix != expected_suffix or tuple(plan.command[-len(expected_suffix):]) != tuple(expected_suffix):
        _fail("serialized descriptor publication command binding drifted")
    bindings = _mapping(publication.get("fd_bindings"), "runtime_identity.descriptor_publication.fd_bindings")
    if set(bindings) != set(EVALUATOR_OUTPUT_NAMES):
        _fail("serialized descriptor publication fd_bindings are incomplete")
    for name in EVALUATOR_OUTPUT_NAMES:
        expected = _mapping(outputs[name], f"runtime contract output {name}")
        observed = _mapping(bindings[name], f"runtime descriptor publication {name}")
        _reject_unknown(observed, {"fd", "path", "dev", "ino", "mode", "uid", "gid", "nlink"}, f"runtime descriptor publication {name}")
        for key in ("fd", "path", "dev", "ino", "mode", "uid", "gid", "nlink"):
            _exact(observed, key, expected[key], f"runtime descriptor publication {name}")
    return publication


def _validate_process_witness(plan: DiagnosticPlan, witness: Any) -> _SealedProcessWitness:
    if type(witness) is not _SealedProcessWitness:
        _fail("process evidence requires an internal sealed real Popen/wait witness")
    try:
        if not hmac.compare_digest(witness._seal, _witness_seal(_runtime_payload(witness))):
            _fail("sealed real Popen/wait witness integrity check failed")
    except (AttributeError, KeyError, TypeError, ValueError):
        _fail("sealed real Popen/wait witness is malformed")
    if type(witness.process) is not _SEALED_POPEN:
        _fail("process evidence process is not the captured real subprocess.Popen type")
    if witness.process.args != list(plan.command) or witness.process.pid != witness.pid:
        _fail("process evidence command or PID is not bound to the receipt")
    if _SEALED_POPEN.poll(witness.process) != witness.returncode:
        _fail("process evidence PID does not report the sealed return code")
    expected = {
        "command": tuple(plan.command),
        "command_sha256": plan.identity["command"]["sha256"],
        "cwd": str(plan.root),
        "cwd_descriptor": dict(plan.cwd_descriptor),
        "env_overrides": dict(plan.env),
        "effective_env_sha256": plan.effective_env_sha256,
        "executable_descriptor": dict(plan.executable_descriptor),
        "input_descriptors": {key: dict(value) for key, value in plan.input_descriptors.items()},
        "binding_sha256": plan.binding_sha256,
        "receipt_sha256": plan.receipt["receipt_sha256"],
        "identity_sha256": plan.receipt["identity_sha256"],
        "namespace": str(plan.namespace),
        "nonce": str(plan.identity["nonce"]),
        "returncode": 0,
        "wait_returncode": 0,
        "wait_observed": True,
    }
    for field, expected_value in expected.items():
        if getattr(witness, field) != expected_value:
            _fail(f"process evidence {field} drifted from the complete execution identity")
    _validate_child_gpu_attestation(plan, witness.runtime_identity, witness.pid)
    if witness.runtime_identity.get("child_runtime_gpu_attestation") is not True:
        _fail("process evidence lacks a sealed child GPU runtime attestation")
    _validate_recorded_descriptor_publication(plan, witness.runtime_identity, witness.pid)
    return witness


def _run_real_popen_wait(
    plan: DiagnosticPlan,
    capability: admission.AdmissionCapability,
    *,
    prevalidated: tuple[Mapping[str, Any], _OutputReservations] | None = None,
) -> _SealedProcessWitness:
    _fail("diagnostic execute capability is not admitted; audited Popen path is unreachable")
    # The code below is intentionally unreachable in the current checkout.
    # It is nevertheless the only permitted future lifecycle: a captured
    # real Popen class, exact receipt-bound argv/env/cwd, a direct wait, and an
    # internal sealed witness.  No caller factory, PID, return code, or JSON
    # proof can enter this path.
    current, reservations = (
        _revalidate_before_popen(plan, capability)
        if prevalidated is None
        else prevalidated
    )
    del current
    environment = _effective_environment(plan.env)
    if _environment_digest(environment) != plan.effective_env_sha256:
        _release_output_reservations(reservations, remove_unpublished=True)
        _fail("effective environment changed before Popen")
    log_file = None
    try:
        _validate_output_reservations(reservations)
        log_file = os.fdopen(os.dup(reservations.outputs["log"].fd), "wb", closefd=True)
        process = _SEALED_POPEN(
            list(plan.command), cwd=str(plan.root), env=environment,
            stdin=subprocess.DEVNULL, stdout=log_file, stderr=subprocess.STDOUT,
            close_fds=True, pass_fds=reservations.pass_fds, start_new_session=True,
        )
        pid, starttime, runtime_identity = _capture_runtime_identity(
            process,
            plan,
            environment,
            reservations,
        )
        wait_returncode = _SEALED_POPEN.wait(process)
        _validate_descriptor_publication_contract(
            plan,
            reservations,
            reservations.publication_contract,
        )
        witness = _new_sealed_witness(plan, process, wait_returncode, environment, pid, starttime, runtime_identity)
        return _validate_process_witness(plan, witness)
    finally:
        if log_file is not None:
            log_file.close()
        _release_output_reservations(reservations, remove_unpublished=False)


def _validate_output_shape(plan: DiagnosticPlan, path: Path, name: str) -> None:
    if path.parent != plan.namespace.parent:
        _fail(f"{name} is not beside the bound namespace")
    if not path.name.startswith(plan.namespace.name + "-"):
        _fail(f"{name} is not namespace-prefixed")


def _inspect_hdf5_snapshot(raw: bytes, *, required_datasets: Sequence[str]) -> dict[str, Any]:
    """Inspect HDF5 link and storage metadata without reading dataset values."""

    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_HDF5_BYTES:
        _fail("HDF5 snapshot is outside the bounded byte contract")
    if any(not isinstance(name, str) or not name or "\x00" in name for name in required_datasets):
        _fail("required HDF5 dataset names must be non-empty strings")
    inventory: list[dict[str, Any]] = []
    pending: list[tuple[str, h5py.Group]] = []
    try:
        with h5py.File(io.BytesIO(raw), "r") as handle:
            pending.append(("", handle))
            while pending:
                prefix, group = pending.pop()
                for name in group.keys():
                    if not isinstance(name, str) or not name or "\x00" in name:
                        _fail("HDF5 contains an invalid link name")
                    path = f"{prefix}/{name}" if prefix else name
                    link = group.get(name, getlink=True)
                    if not isinstance(link, h5py.HardLink):
                        _fail(f"HDF5 contains a non-hard link at {path!r}")
                    obj = group.get(name)
                    if isinstance(obj, h5py.Group):
                        inventory.append({
                            "path": path,
                            "link_type": "hard",
                            "object_type": "group",
                            "external_count": 0,
                            "virtual": False,
                        })
                        pending.append((path, obj))
                        if len(inventory) > MAX_HDF5_LINKS:
                            _fail("HDF5 link inventory exceeds the bounded limit")
                        continue
                    if not isinstance(obj, h5py.Dataset):
                        _fail(f"HDF5 contains an unsupported object at {path!r}")
                    if bool(getattr(obj, "is_virtual", False)):
                        _fail(f"HDF5 contains a virtual dataset at {path!r}")
                    try:
                        external_count = int(obj.id.get_create_plist().get_external_count())
                    except (AttributeError, OSError, RuntimeError, ValueError) as error:
                        _fail(f"cannot inspect HDF5 external-storage metadata at {path!r}: {error}")
                    if external_count != 0:
                        _fail(f"HDF5 dataset uses external storage at {path!r}")
                    inventory.append({
                        "path": path,
                        "link_type": "hard",
                        "object_type": "dataset",
                        "external_count": external_count,
                        "virtual": False,
                    })
                    if len(inventory) > MAX_HDF5_LINKS:
                        _fail("HDF5 link inventory exceeds the bounded limit")
            inventory_by_path = {item["path"]: item for item in inventory}
            for name in required_datasets:
                item = inventory_by_path.get(name)
                if item is None or item["object_type"] != "dataset":
                    _fail(f"required HDF5 dataset is missing or non-physical: {name}")
            inventory_sha256 = canonical_digest(inventory)
            return {
                "required_datasets": list(required_datasets),
                "hard_link_count": len(inventory),
                "link_inventory": inventory,
                "link_inventory_sha256": inventory_sha256,
                "external_storage_count": 0,
                "external_storage_rejected": True,
                "external_links_rejected": True,
                "soft_links_rejected": True,
                "virtual_datasets_rejected": True,
            }
    except RunnerError:
        raise
    except (OSError, KeyError, RuntimeError, ValueError) as error:
        _fail(f"cannot inspect bounded HDF5 link/storage metadata: {error}")


def _terminal_hdf5_receipt(
    plan: DiagnosticPlan,
    trajectory_path: Path,
    trajectory_descriptor: Mapping[str, Any],
    trajectory_raw: bytes,
) -> dict[str, Any]:
    hardened = hardening.inspect_hdf5_snapshot(
        trajectory_raw,
        required_datasets=("time", "position", "velocity", "particle_id", "particle_zone", "valid", "mass"),
        max_bytes=MAX_HDF5_BYTES,
    )
    if hardened.get("sha256") != trajectory_descriptor.get("sha256") or hardened.get("bytes") != trajectory_descriptor.get("bytes"):
        _fail("terminal HDF5 receipt disagrees with the stable trajectory descriptor")
    local_hdf5 = _inspect_hdf5_snapshot(
        trajectory_raw,
        required_datasets=("time", "position", "velocity", "particle_id", "particle_zone", "valid", "mass"),
    )
    receipt = {
        "schema": f"{TERMINAL_RECEIPT_SCHEMA}.hdf5",
        "status": "bounded_hdf5_terminal_receipt",
        "producer": "sealed_real_popen_wait_only",
        "synthetic_only": False,
        "path": str(trajectory_path),
        "descriptor": dict(trajectory_descriptor),
        "sha256": str(trajectory_descriptor["sha256"]),
        "bytes": int(trajectory_descriptor["bytes"]),
        "case_id": CASE_ID,
        "transitions": TRANSITIONS,
        "frames": FRAMES,
        "required_datasets": list(local_hdf5["required_datasets"]),
        "hard_link_count": int(local_hdf5["hard_link_count"]),
        "link_inventory": list(local_hdf5["link_inventory"]),
        "link_inventory_sha256": str(local_hdf5["link_inventory_sha256"]),
        "external_storage_count": int(local_hdf5["external_storage_count"]),
        "external_storage_rejected": True,
        "external_links_rejected": True,
        "soft_links_rejected": True,
        "virtual_datasets_rejected": True,
        "stable_fd": True,
        "path_reopened": False,
        **ZERO_CREDIT,
    }
    receipt["receipt_sha256"] = canonical_digest({key: value for key, value in receipt.items() if key != "receipt_sha256"})
    return receipt


def _validate_zero_credit_payload(value: Mapping[str, Any], name: str) -> None:
    for key, expected in ZERO_CREDIT.items():
        if key in value:
            _exact(value, key, expected, name)


def _validate_terminal_artifacts(plan: DiagnosticPlan) -> dict[str, Any]:
    outputs = plan.outputs
    for name in ("evaluation", "trajectory", "progress", "log", "validator", "terminal_receipt"):
        _validate_output_shape(plan, outputs[name], f"output.{name}")
    artifact_root = plan.namespace.parent
    evaluation_descriptor, evaluation_raw = _secure_artifact(outputs["evaluation"], artifact_root, "evaluation", max_bytes=MAX_JSON_BYTES)
    trajectory_descriptor, trajectory_raw = _secure_artifact(outputs["trajectory"], artifact_root, "trajectory", max_bytes=MAX_HDF5_BYTES)
    progress_descriptor, progress_raw = _secure_artifact(outputs["progress"], artifact_root, "progress", max_bytes=MAX_JSON_BYTES)
    evaluation = _json_bytes(evaluation_raw, "evaluation")
    progress = _json_bytes(progress_raw, "progress")
    _exact(evaluation, "schema", "core.evaluation.v1", "evaluation")
    _exact(evaluation, "evaluation_mode", "diagnostic", "evaluation")
    _exact(evaluation, "diagnostic", True, "evaluation")
    _exact(evaluation, "formal_eligible", False, "evaluation")
    _exact(evaluation, "model_kind", MODEL, "evaluation")
    _exact(evaluation, "requested_split", SPLIT, "evaluation")
    _exact(evaluation, "maximum_steps", TRANSITIONS, "evaluation")
    _exact(evaluation, "checkpoint", str(_mapping(plan.identity["checkpoint"], "identity.checkpoint")["path"]), "evaluation")
    _exact(evaluation, "trajectory_output", str(outputs["trajectory"]), "evaluation")
    _exact(evaluation, "progress_output", str(outputs["progress"]), "evaluation")
    _validate_zero_credit_payload(evaluation, "evaluation")
    _exact(progress, "schema", "core.rollout.progress.v1", "progress")
    _exact(progress, "case_id", CASE_ID, "progress")
    _exact(progress, "status", "completed", "progress")
    _exact(progress, "execution_complete", True, "progress")
    _exact(progress, "finite_rollout_complete", True, "progress")
    _exact(progress, "trajectory_output", str(outputs["trajectory"]), "progress")
    _validate_zero_credit_payload(progress, "progress")
    for key in ("completed_frames", "expected_frames", "frames_expected", "frames_executed"):
        _exact(progress, key, TRANSITIONS, "progress")
    terminal_hdf5 = _terminal_hdf5_receipt(plan, outputs["trajectory"], trajectory_descriptor, trajectory_raw)
    validator_core: dict[str, Any] = {
        "schema": f"{SCHEMA}.artifact_identity",
        "status": "validated",
        "receipt_sha256": plan.receipt["receipt_sha256"],
        "identity_sha256": plan.receipt["identity_sha256"],
        "model_kind": MODEL,
        "seed": SEED,
        "case_id": CASE_ID,
        "split": SPLIT,
        "transitions": TRANSITIONS,
        "frames": FRAMES,
        "artifacts": {
            "evaluation": evaluation_descriptor,
            "trajectory": trajectory_descriptor,
            "progress": progress_descriptor,
        },
        "terminal_hdf5_receipt": terminal_hdf5,
        **ZERO_CREDIT,
    }
    validator_core["artifact_identity_sha256"] = canonical_digest({key: validator_core[key] for key in ("schema", "receipt_sha256", "identity_sha256", "artifacts", "terminal_hdf5_receipt")})
    validator_raw = (canonical_json(validator_core) + "\n").encode()
    validator_descriptor = _write_exclusive(outputs["validator"], validator_raw, 0o600)
    return {
        "status": "terminal_artifacts_validated",
        "artifacts": {"evaluation": evaluation_descriptor, "trajectory": trajectory_descriptor, "progress": progress_descriptor, "validator": validator_descriptor},
        "terminal_hdf5_receipt": terminal_hdf5,
        "artifact_identity_sha256": canonical_digest({"evaluation": evaluation_descriptor, "trajectory": trajectory_descriptor, "progress": progress_descriptor, "validator": validator_descriptor, "terminal_hdf5_receipt": terminal_hdf5}),
        **ZERO_CREDIT,
    }


def _terminal_process_identity_core(process: Mapping[str, Any]) -> dict[str, Any]:
    """Return the portable process identity covered by the terminal seal."""

    return {
        key: process[key]
        for key in (
            "schema", "real_popen_wait", "sealed_witness", "process_type", "pid",
            "pid_starttime", "wait_observed", "returncode", "wait_returncode",
            "runtime_identity",
        )
    }


def _terminal_process_identity_sha256(process: Mapping[str, Any]) -> str:
    return canonical_digest(_terminal_process_identity_core(process))


def _terminal_receipt(
    plan: DiagnosticPlan,
    witness: _SealedProcessWitness,
    terminal: Mapping[str, Any],
    resource_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    witness = _validate_process_witness(plan, witness)
    terminal_hdf5 = _mapping(terminal.get("terminal_hdf5_receipt"), "terminal.terminal_hdf5_receipt")
    receipt_core: dict[str, Any] = {
        "schema": TERMINAL_RECEIPT_SCHEMA,
        "status": "diagnostic_terminal_verified",
        "report_id": REPORT_ID,
        "seed": SEED,
        "model_kind": MODEL,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "case_id": CASE_ID,
        "split": SPLIT,
        "transitions": TRANSITIONS,
        "frames": FRAMES,
        "receipt_sha256": plan.receipt["receipt_sha256"],
        "identity_sha256": plan.receipt["identity_sha256"],
        "namespace": str(plan.namespace),
        "nonce": str(plan.identity["nonce"]),
        "binding_sha256": plan.binding_sha256,
        "manifest": dict(_mapping(plan.identity["manifest"], "identity.manifest")),
        "training_receipt": dict(_mapping(plan.identity["training_receipt"], "identity.training_receipt")),
        "checkpoint": dict(_mapping(plan.identity["checkpoint"], "identity.checkpoint")),
        "executable": dict(plan.executable_descriptor),
        "cwd": str(plan.root),
        "cwd_descriptor": dict(plan.cwd_descriptor),
        "command": list(plan.command),
        "command_sha256": plan.identity["command"]["sha256"],
        "env_overrides": dict(plan.env),
        "effective_env_sha256": plan.effective_env_sha256,
        "resource_snapshot": dict(resource_snapshot),
        "process": {
            "schema": TERMINAL_PROCESS_IDENTITY_SCHEMA,
            "real_popen_wait": True,
            "sealed_witness": True,
            "process_type": f"{type(witness.process).__module__}.{type(witness.process).__qualname__}",
            "pid": witness.pid,
            "pid_starttime": witness.pid_starttime,
            "wait_observed": True,
            "returncode": 0,
            "wait_returncode": 0,
            "runtime_identity": dict(witness.runtime_identity),
        },
        "artifacts": dict(terminal["artifacts"]),
        "artifact_identity_sha256": terminal["artifact_identity_sha256"],
        "terminal_hdf5_receipt": dict(terminal_hdf5),
        "side_effects": {
            "evaluator_started": True,
            "processes_started": 1,
            "processes_stopped": 0,
            "processes_restarted": 0,
            "solver_started": False,
            "worker_started": False,
            "queue_submissions": 0,
            "registry_writes": 0,
            "ledger_writes": 0,
            "denominator_writes": 0,
            "gate_writes": 0,
            "completion_writes": 0,
            "plan_writes": 0,
        },
        **ZERO_CREDIT,
    }
    process = receipt_core["process"]
    process["process_identity_sha256"] = _terminal_process_identity_sha256(process)
    process["witness_seal"] = str(witness._seal)
    process["witness_seal_sha256"] = hashlib.sha256(
        str(witness._seal).encode("utf-8")
    ).hexdigest()
    receipt_core["terminal_receipt_sha256"] = canonical_digest(receipt_core)
    return receipt_core


def execute_diagnostic(plan: DiagnosticPlan, capability: admission.AdmissionCapability) -> dict[str, Any]:
    """Remain denied; the sealed lifecycle is a reviewed future-only path."""

    if _DIAGNOSTIC_EXECUTION_CAPABILITY is None:
        _fail("diagnostic execute capability is not admitted; Popen was not attempted")
    if capability is not _DIAGNOSTIC_EXECUTION_CAPABILITY:
        _fail("caller-supplied capability cannot authorize sealed real Popen/wait")
    current = _revalidate_before_popen(plan, capability)
    witness = _run_real_popen_wait(plan, capability, prevalidated=current)
    terminal = _validate_terminal_artifacts(plan)
    receipt = _terminal_receipt(plan, witness, terminal, current[0])
    raw = (canonical_json(receipt) + "\n").encode("utf-8")
    descriptor = _write_exclusive(plan.outputs["terminal_receipt"], raw, 0o600)
    return {**receipt, "terminal_receipt_file": descriptor}


def _base_report(plan: DiagnosticPlan, *, execute_requested: bool, status: str, blocked: Sequence[str] = (), terminal: Mapping[str, Any] | None = None) -> dict[str, Any]:
    identity = plan.identity
    return {
        "schema": REPORT_SCHEMA,
        "report_id": REPORT_ID,
        "status": status,
        "mode": "diagnostic_execute" if execute_requested else "dry_run",
        "diagnostic_execute_only": True,
        "execute_requested": bool(execute_requested),
        "source_bound": True,
        "admission_receipt_valid": True,
        "diagnostic_execute_allowed": False,
        "execution_capability_admitted": False,
        "popen_capability_admitted": False,
        "launch_allowed": False,
        "seed": SEED,
        "model_kind": MODEL,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "case_id": CASE_ID,
        "split": SPLIT,
        "transitions": TRANSITIONS,
        "frames": FRAMES,
        "gpu_index": GPU_INDEX,
        "receipt_path": str(plan.receipt_path),
        "receipt_sha256": plan.receipt["receipt_sha256"],
        "identity_sha256": plan.receipt["identity_sha256"],
        "namespace": str(plan.namespace),
        "namespace_nonce": identity["nonce"],
        "resource_snapshot": identity["resource_snapshot"],
        "command": list(plan.command),
        "env_overrides": dict(plan.env),
        "effective_env_sha256": plan.effective_env_sha256,
        "effective_env_keys": list(plan.effective_env_keys),
        "cwd": str(plan.root),
        "cwd_descriptor": dict(plan.cwd_descriptor),
        "executable_descriptor": dict(plan.executable_descriptor),
        "input_descriptors": {key: dict(value) for key, value in plan.input_descriptors.items()},
        "binding_sha256": plan.binding_sha256,
        "command_sha256": identity["command"]["sha256"],
        "artifacts": {key: str(value) for key, value in plan.outputs.items()},
        "popen_attempted": bool(terminal is not None),
        "wait_attempted": bool(terminal is not None),
        "real_workload_started": 1 if terminal is not None else 0,
        "terminal_receipt": dict(terminal) if terminal is not None else None,
        "blocked_reasons": sorted(set(str(item) for item in blocked if item)),
        "side_effects": {
            "evaluator_started": terminal is not None,
            "processes_started": 1 if terminal is not None else 0,
            "processes_stopped": 0,
            "processes_restarted": 0,
            "solver_started": False,
            "worker_started": False,
            "queue_submissions": 0,
            "registry_writes": 0,
            "ledger_writes": 0,
            "denominator_writes": 0,
            "gate_writes": 0,
            "completion_writes": 0,
            "plan_writes": 0,
        },
        **ZERO_CREDIT,
    }


def build_report(receipt_path: Path | str | None, *, execute_requested: bool = False) -> dict[str, Any]:
    if receipt_path is None:
        return {
            "schema": REPORT_SCHEMA,
            "report_id": REPORT_ID,
            "status": "blocked_fail_closed",
            "mode": "diagnostic_execute" if execute_requested else "dry_run",
            "diagnostic_execute_only": True,
            "execute_requested": bool(execute_requested),
            "source_bound": False,
            "admission_receipt_valid": False,
            "diagnostic_execute_allowed": False,
            "execution_capability_admitted": False,
            "popen_capability_admitted": False,
            "launch_allowed": False,
            "popen_attempted": False,
            "wait_attempted": False,
            "real_workload_started": 0,
            "terminal_receipt": None,
            "blocked_reasons": ["--admission-receipt is required; no implicit admission is minted"],
            "side_effects": {"evaluator_started": False, "processes_started": 0, "processes_stopped": 0, "processes_restarted": 0, "solver_started": False, "worker_started": False, "queue_submissions": 0, "registry_writes": 0, "ledger_writes": 0, "denominator_writes": 0, "gate_writes": 0, "completion_writes": 0, "plan_writes": 0},
            **ZERO_CREDIT,
        }
    try:
        plan = build_plan(receipt_path)
        if not execute_requested:
            return _base_report(
                plan,
                execute_requested=False,
                status="blocked_fail_closed",
                blocked=("default dry-run performs no execution", *EXECUTION_BLOCKERS),
            )
        # The flag is parsed and reported, but execution remains deliberately
        # unavailable.  In particular, do not consume the receipt: an
        # unavailable capability must not burn a one-shot token or create any
        # runtime side effect.
        return _base_report(
            plan,
            execute_requested=True,
            status="blocked_fail_closed",
            blocked=EXECUTION_BLOCKERS,
        )
    except (RunnerError, admission.AdmissionError, OSError, ValueError) as error:
        return {
            "schema": REPORT_SCHEMA,
            "report_id": REPORT_ID,
            "status": "blocked_fail_closed",
            "mode": "diagnostic_execute" if execute_requested else "dry_run",
            "diagnostic_execute_only": True,
            "execute_requested": bool(execute_requested),
            "source_bound": False,
            "admission_receipt_valid": False,
            "diagnostic_execute_allowed": False,
            "execution_capability_admitted": False,
            "popen_capability_admitted": False,
            "launch_allowed": False,
            "popen_attempted": False,
            "wait_attempted": False,
            "real_workload_started": 0,
            "terminal_receipt": None,
            "blocked_reasons": [str(error)],
            "side_effects": {"evaluator_started": False, "processes_started": 0, "processes_stopped": 0, "processes_restarted": 0, "solver_started": False, "worker_started": False, "queue_submissions": 0, "registry_writes": 0, "ledger_writes": 0, "denominator_writes": 0, "gate_writes": 0, "completion_writes": 0, "plan_writes": 0},
            **ZERO_CREDIT,
        }


def _validate_terminal_artifact_descriptor(
    value: Any,
    name: str,
    expected_path: str,
) -> dict[str, Any]:
    descriptor = dict(_mapping(value, name))
    _reject_unknown(
        descriptor,
        {
            "path", "resolved_path", "dev", "ino", "bytes", "mode", "uid", "gid",
            "nlink", "mtime_ns", "parent_dev", "parent_ino", "sha256",
            "leaf_symlink", "stable_fd", "fd_identity_stable", "path_reopened",
            "content_opened",
        },
        name,
    )
    _exact(descriptor, "path", expected_path, name)
    _absolute(descriptor.get("path"), f"{name}.path")
    for key in ("dev", "ino", "bytes", "mode", "uid", "gid", "nlink", "mtime_ns"):
        if type(descriptor.get(key)) is not int:
            _fail(f"{name}.{key} must be an integer")
    if descriptor["bytes"] < 1 or descriptor["dev"] < 0 or descriptor["ino"] <= 0:
        _fail(f"{name} has an invalid file identity")
    _exact(descriptor, "mode", 0o600, name)
    _exact(descriptor, "uid", os.getuid(), name)
    _exact(descriptor, "gid", os.getgid(), name)
    _exact(descriptor, "nlink", 1, name)
    _sha256_hex(descriptor.get("sha256"), f"{name}.sha256")
    _exact(descriptor, "stable_fd", True, name)
    _exact(descriptor, "fd_identity_stable", True, name)
    _exact(descriptor, "path_reopened", False, name)
    if "resolved_path" in descriptor:
        _exact(descriptor, "resolved_path", expected_path, name)
    if "parent_dev" in descriptor and type(descriptor["parent_dev"]) is not int:
        _fail(f"{name}.parent_dev must be an integer")
    if "parent_ino" in descriptor and type(descriptor["parent_ino"]) is not int:
        _fail(f"{name}.parent_ino must be an integer")
    if "leaf_symlink" in descriptor:
        _exact(descriptor, "leaf_symlink", False, name)
    if "content_opened" in descriptor:
        _exact(descriptor, "content_opened", True, name)
    return descriptor


def _validate_terminal_hdf5_report_receipt(
    value: Any,
    trajectory_descriptor: Mapping[str, Any],
) -> dict[str, Any]:
    receipt = dict(_mapping(value, "terminal_receipt.terminal_hdf5_receipt"))
    allowed = set(ZERO_CREDIT) | {
        "schema", "status", "producer", "synthetic_only", "path", "descriptor",
        "sha256", "bytes", "case_id", "transitions", "frames", "required_datasets",
        "hard_link_count", "link_inventory", "link_inventory_sha256",
        "external_storage_count", "external_storage_rejected", "external_links_rejected",
        "soft_links_rejected", "virtual_datasets_rejected", "stable_fd", "path_reopened",
        "receipt_sha256",
    }
    _reject_unknown(receipt, allowed, "terminal_receipt.terminal_hdf5_receipt")
    _exact(receipt, "schema", f"{TERMINAL_RECEIPT_SCHEMA}.hdf5", "terminal HDF5 receipt")
    _exact(receipt, "status", "bounded_hdf5_terminal_receipt", "terminal HDF5 receipt")
    _exact(receipt, "producer", "sealed_real_popen_wait_only", "terminal HDF5 receipt")
    _exact(receipt, "synthetic_only", False, "terminal HDF5 receipt")
    _exact(receipt, "path", trajectory_descriptor["path"], "terminal HDF5 receipt")
    if dict(_mapping(receipt.get("descriptor"), "terminal HDF5 receipt.descriptor")) != dict(trajectory_descriptor):
        _fail("terminal HDF5 descriptor is not the bound trajectory descriptor")
    _exact(receipt, "sha256", trajectory_descriptor["sha256"], "terminal HDF5 receipt")
    _exact(receipt, "bytes", trajectory_descriptor["bytes"], "terminal HDF5 receipt")
    _exact(receipt, "case_id", CASE_ID, "terminal HDF5 receipt")
    _exact(receipt, "transitions", TRANSITIONS, "terminal HDF5 receipt")
    _exact(receipt, "frames", FRAMES, "terminal HDF5 receipt")
    _exact(
        receipt,
        "required_datasets",
        ["time", "position", "velocity", "particle_id", "particle_zone", "valid", "mass"],
        "terminal HDF5 receipt",
    )
    inventory = receipt.get("link_inventory")
    if not isinstance(inventory, list) or any(not isinstance(item, Mapping) for item in inventory):
        _fail("terminal HDF5 link_inventory must be a mapping list")
    if type(receipt.get("hard_link_count")) is not int or receipt["hard_link_count"] != len(inventory):
        _fail("terminal HDF5 hard_link_count is not bound to link_inventory")
    for index, item in enumerate(inventory):
        link = dict(item)
        _reject_unknown(link, {"path", "link_type", "object_type", "external_count", "virtual"}, f"terminal HDF5 link_inventory[{index}]")
        if not isinstance(link.get("path"), str) or not link["path"] or "\x00" in link["path"]:
            _fail(f"terminal HDF5 link_inventory[{index}].path is invalid")
        _exact(link, "link_type", "hard", f"terminal HDF5 link_inventory[{index}]")
        if link.get("object_type") not in {"group", "dataset"}:
            _fail(f"terminal HDF5 link_inventory[{index}].object_type is invalid")
        _exact(link, "external_count", 0, f"terminal HDF5 link_inventory[{index}]")
        _exact(link, "virtual", False, f"terminal HDF5 link_inventory[{index}]")
    _exact(receipt, "link_inventory_sha256", canonical_digest(inventory), "terminal HDF5 receipt")
    _exact(receipt, "external_storage_count", 0, "terminal HDF5 receipt")
    for key in ("external_storage_rejected", "external_links_rejected", "soft_links_rejected", "virtual_datasets_rejected", "stable_fd"):
        _exact(receipt, key, True, "terminal HDF5 receipt")
    _exact(receipt, "path_reopened", False, "terminal HDF5 receipt")
    for key, expected in ZERO_CREDIT.items():
        _exact(receipt, key, expected, "terminal HDF5 receipt")
    _sha256_hex(receipt.get("receipt_sha256"), "terminal HDF5 receipt.receipt_sha256")
    expected_digest = canonical_digest({key: value for key, value in receipt.items() if key != "receipt_sha256"})
    _exact(receipt, "receipt_sha256", expected_digest, "terminal HDF5 receipt")
    return receipt


def _validate_report_descriptor_publication(
    report: Mapping[str, Any],
    publication: Any,
    pid: int,
) -> Mapping[str, Any]:
    """Validate the descriptor publication witness carried by a terminal report."""

    publication = _mapping(publication, "terminal process descriptor_publication")
    _reject_unknown(
        publication,
        {"schema", "protocol", "contract_sha256", "contract", "child_pid", "publication_attested", "fd_bindings"},
        "terminal process descriptor_publication",
    )
    _exact(publication, "schema", DESCRIPTOR_PUBLICATION_SCHEMA, "terminal process descriptor_publication")
    _exact(publication, "protocol", DESCRIPTOR_PUBLICATION_PROTOCOL, "terminal process descriptor_publication")
    _exact(publication, "child_pid", pid, "terminal process descriptor_publication")
    _exact(publication, "publication_attested", True, "terminal process descriptor_publication")
    contract = _mapping(publication.get("contract"), "terminal process descriptor_publication.contract")
    _reject_unknown(
        contract,
        {
            "schema", "protocol", "namespace", "namespace_parent", "receipt_sha256",
            "identity_sha256", "binding_sha256", "outputs", "pass_fds",
            "publication_rule", "contract_sha256", "required_argv_suffix",
            "child_contract_supported",
        },
        "terminal process descriptor_publication.contract",
    )
    _exact(contract, "schema", DESCRIPTOR_PUBLICATION_SCHEMA, "terminal descriptor publication contract")
    _exact(contract, "protocol", DESCRIPTOR_PUBLICATION_PROTOCOL, "terminal descriptor publication contract")
    _exact(contract, "namespace", report["namespace"], "terminal descriptor publication contract")
    _exact(contract, "receipt_sha256", report["receipt_sha256"], "terminal descriptor publication contract")
    _exact(contract, "identity_sha256", report["identity_sha256"], "terminal descriptor publication contract")
    _exact(contract, "binding_sha256", report["binding_sha256"], "terminal descriptor publication contract")
    _exact(contract, "publication_rule", "child_must_write_inherited_fd_without_path_reopen_or_replace", "terminal descriptor publication contract")
    _exact(contract, "child_contract_supported", True, "terminal descriptor publication contract")
    _sha256_hex(contract.get("contract_sha256"), "terminal descriptor publication contract.contract_sha256")
    _exact(publication, "contract_sha256", contract["contract_sha256"], "terminal process descriptor_publication")
    core = {key: contract[key] for key in (
        "schema", "protocol", "namespace", "namespace_parent", "receipt_sha256",
        "identity_sha256", "binding_sha256", "outputs", "pass_fds", "publication_rule",
    )}
    _exact(contract, "contract_sha256", canonical_digest(core), "terminal descriptor publication contract")
    parent = _mapping(contract.get("namespace_parent"), "terminal descriptor publication contract.namespace_parent")
    _reject_unknown(parent, {"dev", "ino"}, "terminal descriptor publication contract.namespace_parent")
    if type(parent.get("dev")) is not int or type(parent.get("ino")) is not int:
        _fail("terminal descriptor publication parent identity is malformed")
    outputs = _mapping(contract.get("outputs"), "terminal descriptor publication contract.outputs")
    expected_output_paths = _mapping(report.get("artifacts"), "report.artifacts")
    if set(outputs) != set(EVALUATOR_OUTPUT_NAMES):
        _fail("terminal descriptor publication contract output set is incomplete")
    pass_fds = contract.get("pass_fds")
    if not isinstance(pass_fds, list) or any(type(fd) is not int or fd < 0 for fd in pass_fds):
        _fail("terminal descriptor publication pass_fds is malformed")
    for name in EVALUATOR_OUTPUT_NAMES:
        output = _mapping(outputs[name], f"terminal descriptor publication output {name}")
        _reject_unknown(
            output,
            {
                "path", "fd", "dev", "ino", "mode", "uid", "gid", "nlink",
                "parent_dev", "parent_ino", "stable_fd", "fd_identity_stable",
                "path_reopened", "publication",
            },
            f"terminal descriptor publication output {name}",
        )
        _exact(output, "path", expected_output_paths[name], f"terminal descriptor publication output {name}")
        if type(output.get("fd")) is not int or output["fd"] < 0:
            _fail(f"terminal descriptor publication output {name}.fd is invalid")
        for key in ("dev", "ino", "mode", "uid", "gid", "nlink", "parent_dev", "parent_ino"):
            if type(output.get(key)) is not int:
                _fail(f"terminal descriptor publication output {name}.{key} is invalid")
        _exact(output, "mode", 0o600, f"terminal descriptor publication output {name}")
        _exact(output, "uid", os.getuid(), f"terminal descriptor publication output {name}")
        _exact(output, "gid", os.getgid(), f"terminal descriptor publication output {name}")
        _exact(output, "nlink", 1, f"terminal descriptor publication output {name}")
        _exact(output, "stable_fd", True, f"terminal descriptor publication output {name}")
        _exact(output, "fd_identity_stable", True, f"terminal descriptor publication output {name}")
        _exact(output, "path_reopened", False, f"terminal descriptor publication output {name}")
        _exact(output, "publication", "inherited_fd_write_no_replace", f"terminal descriptor publication output {name}")
    if pass_fds != [outputs[name]["fd"] for name in EVALUATOR_OUTPUT_NAMES]:
        _fail("terminal descriptor publication pass_fds does not match output descriptors")
    required_suffix = contract.get("required_argv_suffix")
    expected_suffix = [DESCRIPTOR_PUBLICATION_ARGUMENT, str(contract["contract_sha256"])]
    for name in EVALUATOR_OUTPUT_NAMES:
        expected_suffix.extend([DESCRIPTOR_PUBLICATION_FD_ARGUMENTS[name], str(outputs[name]["fd"])])
    if required_suffix != expected_suffix or tuple(report["command"][-len(expected_suffix):]) != tuple(expected_suffix):
        _fail("terminal descriptor publication command suffix is not bound")
    bindings = _mapping(publication.get("fd_bindings"), "terminal process descriptor_publication.fd_bindings")
    if set(bindings) != set(EVALUATOR_OUTPUT_NAMES):
        _fail("terminal process descriptor_publication.fd_bindings is incomplete")
    for name in EVALUATOR_OUTPUT_NAMES:
        observed = _mapping(bindings[name], f"terminal process descriptor publication {name}")
        _reject_unknown(observed, {"fd", "path", "dev", "ino", "mode", "uid", "gid", "nlink"}, f"terminal process descriptor publication {name}")
        expected = outputs[name]
        for key in ("fd", "path", "dev", "ino", "mode", "uid", "gid", "nlink"):
            _exact(observed, key, expected[key], f"terminal process descriptor publication {name}")
    return publication


def _validate_terminal_receipt_binding(report: Mapping[str, Any], value: Any) -> None:
    """Reject any terminal claim that is not a complete bound projection."""

    receipt = dict(_mapping(value, "report.terminal_receipt"))
    allowed = set(ZERO_CREDIT) | {
        "schema", "status", "report_id", "seed", "model_kind", "hidden", "updates",
        "case_id", "split", "transitions", "frames", "receipt_sha256", "identity_sha256",
        "namespace", "nonce", "binding_sha256", "manifest", "training_receipt", "checkpoint",
        "executable", "cwd", "cwd_descriptor", "command", "command_sha256",
        "env_overrides", "effective_env_sha256", "resource_snapshot", "process", "artifacts",
        "artifact_identity_sha256", "terminal_hdf5_receipt", "side_effects",
        "terminal_receipt_sha256", "terminal_receipt_file",
    }
    _reject_unknown(receipt, allowed, "report.terminal_receipt")
    _exact(receipt, "schema", TERMINAL_RECEIPT_SCHEMA, "terminal receipt")
    _exact(receipt, "status", "diagnostic_terminal_verified", "terminal receipt")
    _exact(receipt, "report_id", REPORT_ID, "terminal receipt")
    for field in ("seed", "model_kind", "hidden", "updates", "case_id", "split", "transitions", "frames", "receipt_sha256", "identity_sha256", "namespace", "nonce", "binding_sha256", "command_sha256", "effective_env_sha256"):
        _exact(receipt, field, report[field] if field in report else receipt[field], "terminal receipt")
    for field in ("seed", "model_kind", "hidden", "updates", "case_id", "split", "transitions", "frames", "receipt_sha256", "identity_sha256", "namespace", "binding_sha256", "command_sha256", "effective_env_sha256"):
        _exact(receipt, field, report[field], "terminal receipt")
    _exact(receipt, "nonce", report["namespace_nonce"], "terminal receipt")
    _absolute(receipt["namespace"], "terminal receipt.namespace")
    if list(receipt.get("command", [])) != list(report["command"]):
        _fail("terminal receipt command is not report-bound")
    _exact(receipt, "cwd", report["cwd"], "terminal receipt")
    if dict(_mapping(receipt.get("cwd_descriptor"), "terminal receipt.cwd_descriptor")) != dict(report["cwd_descriptor"]):
        _fail("terminal receipt cwd descriptor is not report-bound")
    if dict(_mapping(receipt.get("executable"), "terminal receipt.executable")) != dict(report["executable_descriptor"]):
        _fail("terminal receipt executable descriptor is not report-bound")
    if dict(_mapping(receipt.get("env_overrides"), "terminal receipt.env_overrides")) != dict(report["env_overrides"]):
        _fail("terminal receipt environment is not report-bound")
    _exact(receipt, "effective_env_sha256", report["effective_env_sha256"], "terminal receipt")
    if dict(_mapping(receipt.get("resource_snapshot"), "terminal receipt.resource_snapshot")) != dict(report["resource_snapshot"]):
        _fail("terminal receipt resource snapshot is not report-bound")
    input_descriptors = _mapping(report.get("input_descriptors"), "report.input_descriptors")
    for identity_key, descriptor_key in (("manifest", "manifest"), ("training_receipt", "training_receipt"), ("checkpoint", "checkpoint")):
        identity_record = _mapping(receipt.get(identity_key), f"terminal receipt.{identity_key}")
        file_descriptor = _mapping(identity_record.get("file"), f"terminal receipt.{identity_key}.file")
        expected_descriptor = _mapping(input_descriptors.get(descriptor_key), f"report.input_descriptors.{descriptor_key}")
        for key in ("path", "dev", "ino", "bytes", "mode", "uid", "gid", "nlink", "mtime_ns", "sha256"):
            _exact(file_descriptor, key, expected_descriptor[key], f"terminal receipt.{identity_key}.file")
    _validate_terminal_artifact_descriptor(
        receipt["artifacts"]["evaluation"],
        "terminal receipt.artifacts.evaluation",
        report["artifacts"]["evaluation"],
    )
    _validate_terminal_artifact_descriptor(
        receipt["artifacts"]["trajectory"],
        "terminal receipt.artifacts.trajectory",
        report["artifacts"]["trajectory"],
    )
    _validate_terminal_artifact_descriptor(
        receipt["artifacts"]["progress"],
        "terminal receipt.artifacts.progress",
        report["artifacts"]["progress"],
    )
    _validate_terminal_artifact_descriptor(
        receipt["artifacts"]["validator"],
        "terminal receipt.artifacts.validator",
        report["artifacts"]["validator"],
    )
    artifacts = _mapping(receipt.get("artifacts"), "terminal receipt.artifacts")
    if set(artifacts) != {"evaluation", "trajectory", "progress", "validator"}:
        _fail("terminal receipt.artifacts must contain exactly the validated outputs")
    hdf5 = _validate_terminal_hdf5_report_receipt(
        receipt.get("terminal_hdf5_receipt"),
        _mapping(artifacts["trajectory"], "terminal receipt.artifacts.trajectory"),
    )
    expected_artifact_identity = canonical_digest({
        "evaluation": artifacts["evaluation"],
        "trajectory": artifacts["trajectory"],
        "progress": artifacts["progress"],
        "validator": artifacts["validator"],
        "terminal_hdf5_receipt": hdf5,
    })
    _exact(receipt, "artifact_identity_sha256", expected_artifact_identity, "terminal receipt")
    process = dict(_mapping(receipt.get("process"), "terminal receipt.process"))
    _reject_unknown(
        process,
        {
            "schema", "real_popen_wait", "sealed_witness", "process_type", "pid",
            "pid_starttime", "wait_observed", "returncode", "wait_returncode",
            "runtime_identity", "process_identity_sha256", "witness_seal", "witness_seal_sha256",
        },
        "terminal receipt.process",
    )
    _exact(process, "schema", TERMINAL_PROCESS_IDENTITY_SCHEMA, "terminal receipt.process")
    for key in ("real_popen_wait", "sealed_witness", "wait_observed"):
        _exact(process, key, True, "terminal receipt.process")
    _exact(process, "process_type", "subprocess.Popen", "terminal receipt.process")
    if type(process.get("pid")) is not int or process["pid"] <= 0:
        _fail("terminal receipt.process.pid is invalid")
    if not isinstance(process.get("pid_starttime"), str) or not process["pid_starttime"].isdigit():
        _fail("terminal receipt.process.pid_starttime is invalid")
    _exact(process, "returncode", 0, "terminal receipt.process")
    _exact(process, "wait_returncode", 0, "terminal receipt.process")
    runtime = dict(_mapping(process.get("runtime_identity"), "terminal receipt.process.runtime_identity"))
    _reject_unknown(
        runtime,
        {"cmdline_sha256", "executable", "cwd", "environment_sha256", "session_leader", "procfs_starttime", "gpu", "child_runtime_gpu_attestation", "descriptor_publication"},
        "terminal receipt.process.runtime_identity",
    )
    _sha256_hex(runtime.get("cmdline_sha256"), "terminal receipt.process.runtime_identity.cmdline_sha256")
    _exact(runtime, "executable", _mapping(receipt["executable"], "terminal receipt.executable")["resolved_path"], "terminal receipt.process.runtime_identity")
    _exact(runtime, "cwd", receipt["cwd"], "terminal receipt.process.runtime_identity")
    _exact(runtime, "environment_sha256", receipt["effective_env_sha256"], "terminal receipt.process.runtime_identity")
    _exact(runtime, "session_leader", True, "terminal receipt.process.runtime_identity")
    _exact(runtime, "procfs_starttime", process["pid_starttime"], "terminal receipt.process.runtime_identity")
    _exact(runtime, "child_runtime_gpu_attestation", True, "terminal receipt.process.runtime_identity")
    gpu = _mapping(runtime.get("gpu"), "terminal receipt.process.runtime_identity.gpu")
    expected_gpu = _validate_gpu_identity(_mapping(_mapping(receipt["resource_snapshot"], "terminal receipt.resource_snapshot")["gpu"], "terminal receipt.resource_snapshot.gpu"))
    for key, expected in expected_gpu.items():
        _exact(gpu, key, expected, "terminal receipt.process.runtime_identity.gpu")
    for key, expected in (("live_probe", True), ("child_runtime_attested", True), ("child_pid", process["pid"]), ("probe_tool", "nvidia-smi"), ("process_query_required", True)):
        _exact(gpu, key, expected, "terminal receipt.process.runtime_identity.gpu")
    _validate_report_descriptor_publication(report, runtime.get("descriptor_publication"), process["pid"])
    _sha256_hex(process.get("witness_seal"), "terminal receipt.process.witness_seal")
    _exact(process, "witness_seal_sha256", hashlib.sha256(process["witness_seal"].encode("utf-8")).hexdigest(), "terminal receipt.process")
    _exact(process, "process_identity_sha256", _terminal_process_identity_sha256(process), "terminal receipt.process")
    side_effects = _mapping(receipt.get("side_effects"), "terminal receipt.side_effects")
    if dict(side_effects) != dict(report["side_effects"]):
        _fail("terminal receipt side effects are not report-bound")
    for key, expected in ZERO_CREDIT.items():
        _exact(receipt, key, expected, "terminal receipt")
    if "terminal_receipt_file" not in receipt:
        _fail("terminal receipt file descriptor is missing")
    _validate_terminal_artifact_descriptor(
        receipt["terminal_receipt_file"],
        "terminal receipt.terminal_receipt_file",
        report["artifacts"]["terminal_receipt"],
    )
    _sha256_hex(receipt.get("terminal_receipt_sha256"), "terminal receipt.terminal_receipt_sha256")
    expected_receipt_digest = canonical_digest({key: value for key, value in receipt.items() if key != "terminal_receipt_sha256" and key != "terminal_receipt_file"})
    _exact(receipt, "terminal_receipt_sha256", expected_receipt_digest, "terminal receipt")


def validate_report(report: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    try:
        _walk_json(report, "report")
        allowed = set(ZERO_CREDIT) | {"schema", "report_id", "status", "mode", "diagnostic_execute_only", "execute_requested", "source_bound", "admission_receipt_valid", "diagnostic_execute_allowed", "execution_capability_admitted", "popen_capability_admitted", "launch_allowed", "seed", "model_kind", "hidden", "updates", "case_id", "split", "transitions", "frames", "gpu_index", "receipt_path", "receipt_sha256", "identity_sha256", "namespace", "namespace_nonce", "resource_snapshot", "command", "env_overrides", "effective_env_sha256", "effective_env_keys", "cwd", "cwd_descriptor", "executable_descriptor", "input_descriptors", "binding_sha256", "command_sha256", "artifacts", "popen_attempted", "wait_attempted", "real_workload_started", "terminal_receipt", "blocked_reasons", "side_effects"}
        _reject_unknown(report, allowed, "report")
        _exact(report, "schema", REPORT_SCHEMA, "report")
        _exact(report, "report_id", REPORT_ID, "report")
        _exact(report, "diagnostic_execute_only", True, "report")
        _exact(report, "diagnostic_execute_allowed", False, "report")
        _exact(report, "execution_capability_admitted", False, "report")
        _exact(report, "popen_capability_admitted", False, "report")
        _exact(report, "launch_allowed", False, "report")
        for key, expected in ZERO_CREDIT.items():
            _exact(report, key, expected, "report")
        status = report.get("status")
        if status not in {"dry_run_ready", "diagnostic_terminal_verified", "blocked_fail_closed"}:
            _fail("report.status is invalid")
        if status == "dry_run_ready":
            _exact(report, "execute_requested", False, "report")
            _exact(report, "popen_attempted", False, "report")
            _exact(report, "wait_attempted", False, "report")
            _exact(report, "real_workload_started", 0, "report")
            if report.get("terminal_receipt") is not None:
                _fail("dry-run report cannot contain terminal receipt")
        if status == "diagnostic_terminal_verified":
            _exact(report, "execute_requested", True, "report")
            _exact(report, "popen_attempted", True, "report")
            _exact(report, "wait_attempted", True, "report")
            _exact(report, "real_workload_started", 1, "report")
            terminal = _mapping(report.get("terminal_receipt"), "report.terminal_receipt")
            _exact(terminal, "schema", TERMINAL_RECEIPT_SCHEMA, "report.terminal_receipt")
            if "terminal_receipt_sha256" not in terminal:
                _fail("report.terminal_receipt.terminal_receipt_sha256 is missing")
            _validate_terminal_receipt_binding(report, terminal)
        if status == "blocked_fail_closed":
            reasons = report.get("blocked_reasons")
            if not isinstance(reasons, list) or not reasons or any(not isinstance(item, str) for item in reasons):
                _fail("blocked report requires non-empty string reasons")
        # Historical v2 reports predate the P1 binding projection and are
        # intentionally left immutable.  New source-bound reports must carry
        # the complete projection; old reports remain verifiable as history.
        if report.get("source_bound") is True and "binding_sha256" in report:
            for key in ("effective_env_sha256", "binding_sha256"):
                value = report.get(key)
                if not isinstance(value, str) or len(value) != 64:
                    _fail(f"report.{key} must be a bound SHA-256")
            keys = report.get("effective_env_keys")
            if not isinstance(keys, list) or any(not isinstance(item, str) for item in keys):
                _fail("report.effective_env_keys must be a string list")
            for field in ("cwd_descriptor", "executable_descriptor", "input_descriptors"):
                if not isinstance(report.get(field), Mapping):
                    _fail(f"report.{field} must be an identity object")
        side_effects = _mapping(report.get("side_effects"), "report.side_effects")
        for key in ("registry_writes", "ledger_writes", "denominator_writes", "gate_writes", "completion_writes", "plan_writes", "processes_stopped", "processes_restarted"):
            if side_effects.get(key) not in (False, 0):
                _fail(f"report.side_effects.{key} must remain false/zero")
    except (RunnerError, TypeError, AttributeError, KeyError) as error:
        errors.append(str(error))
    return errors


def render_markdown(report: Mapping[str, Any]) -> str:
    return "\n".join([
        "# F3 graph_raw seed17 diagnostic runner v2",
        "",
        f"- status: `{report.get('status')}`",
        f"- mode: `{report.get('mode')}`",
        f"- source bound: `{report.get('source_bound')}`",
        f"- admission receipt: `{report.get('receipt_path')}`",
        "- exact contract: graph_raw / hidden16 / seed17 / test / 835 transitions / 836 frames",
        "- execution gate: only `--diagnostic-execute`; no `--execute` alias",
        f"- Popen/wait attempted: `{report.get('popen_attempted')}/{report.get('wait_attempted')}`",
        "- validator: hardened descriptor/HDF5 boundary plus independent F3 HDF5 validator",
        "- formal/registry/ledger/denominator/gate/completion/PLAN writes: `0`; credit: `0`",
        "",
        "## Blockers",
        "",
        *[f"- {item}" for item in report.get("blocked_reasons", []) if isinstance(item, str)],
        "",
    ])


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admission-receipt", type=Path, default=None)
    parser.add_argument("--report-output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--verify-report", type=Path, default=None)
    # Deliberately no --execute compatibility alias.
    parser.add_argument("--diagnostic-execute", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        if args.verify_report is not None:
            payload = _read_json(_absolute(args.verify_report, "report"), "report")
            errors = validate_report(payload)
            print(canonical_json({"valid": not errors, "errors": errors, "schema": REPORT_SCHEMA}))
            return 0 if not errors else 1
        report = build_report(args.admission_receipt, execute_requested=args.diagnostic_execute)
        _write_exclusive(args.report_output, (json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(), 0o640)
        _write_exclusive(args.report_output.with_suffix(".zh-CN.md"), render_markdown(report).encode(), 0o640)
        print(canonical_json(report))
        return 0 if report["status"] in {"dry_run_ready", "diagnostic_terminal_verified"} else 2
    except (RunnerError, admission.AdmissionError, OSError, ValueError) as error:
        print(canonical_json({"status": "blocked_fail_closed", "error": str(error)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
