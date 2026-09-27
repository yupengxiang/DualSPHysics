"""Bound a bounded synthetic F8 R008 attempt to an output-root file set.

This module is deliberately diagnostic-only.  It accepts one canonical JSON
manifest and one already-created output directory, then checks that the
manifest's attempt/process/hash/root/writer claims match the files currently
visible through no-follow file descriptors.  It never launches or inspects a
solver, native binary, GPU, queue, or production workload.

The manifest is a caller-supplied claim.  Consequently a successful result
means only that the claim is structurally and byte-consistently bound to the
synthetic directory at read time.  It does not authenticate the source,
creator, process, fresh-root history, runtime completion, native semantics,
T1, or qualification.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any

from scripts.core_strict_json import strict_json_object


INPUT_SCHEMA = "core.cfd.f8.r008_attempt_output_binding_input.v1"
SCHEMA = "core.cfd.f8.r008_attempt_output_binding_diagnostic.v1"
MAX_MANIFEST_BYTES = 1_048_576
MAX_WRITERS = 16
MAX_FILES = 64
MAX_FILE_BYTES = 16 * 1024 * 1024

_HEX16 = re.compile(r"[0-9a-f]{16}\Z", re.ASCII)
_HEX64 = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z", re.ASCII)
_FILE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z", re.ASCII)

_PROCESS_FIELDS = frozenset({
    "pid_namespace_inode_hex",
    "pid",
    "start_monotonic_ns_hex",
    "kernel_starttime_ticks_hex",
    "birth_seq_hex",
})
_CONTEXT_FIELDS = frozenset({"case_np", "root_metadata_sha256"})
_ROOT_FIELDS = frozenset({
    "dev_hex",
    "ino_hex",
    "preexisting",
    "created_by_attempt",
    "restart_declared",
    "append_declared",
})
_WRITER_FIELDS = frozenset({
    "writer_id",
    "writer_role",
    "attempt_id",
    "nonce_hex",
    "process_generation",
    "root_dev_hex",
    "root_ino_hex",
    "files",
})
_FILE_FIELDS = frozenset({
    "relative_path",
    "writer_id",
    "attempt_id",
    "nonce_hex",
    "process_generation",
    "dev_hex",
    "ino_hex",
    "bytes",
    "sha256",
})
_INPUT_FIELDS = frozenset({
    "schema",
    "attempt_id",
    "nonce_hex",
    "process_generation",
    "solver_binary_sha256",
    "config_sha256",
    "definition_sha256",
    "control_sha256",
    "initial_state_sha256",
    "context",
    "output_root",
    "writers",
})

_OUTPUT_ROOT_FIELDS = frozenset({
    "dev_hex",
    "ino_hex",
    "preexisting",
    "created_by_attempt",
    "restart_declared",
    "append_declared",
})
_OUTPUT_WRITER_FIELDS = frozenset({
    "writer_id",
    "writer_role",
    "attempt_id",
    "nonce_hex",
    "process_generation",
    "root_dev_hex",
    "root_ino_hex",
    "files",
})
_OUTPUT_ARTIFACT_FIELDS = frozenset({
    "relative_path",
    "writer_id",
    "dev_hex",
    "ino_hex",
    "bytes",
    "sha256",
})
_OUTPUT_FIELDS = frozenset({
    "schema",
    "input_schema",
    "binding_status",
    "rejection_reason",
    "attempt_id",
    "nonce_hex",
    "process_generation",
    "solver_binary_sha256",
    "config_sha256",
    "definition_sha256",
    "control_sha256",
    "initial_state_sha256",
    "case_np",
    "root_metadata_sha256",
    "output_root",
    "writers",
    "artifacts",
    "artifact_count",
    "artifact_bytes",
    "attempt_identity_bound",
    "process_generation_bound",
    "configuration_hashes_bound",
    "fresh_output_root_bound",
    "writer_identity_bound",
    "artifact_identity_bound",
    "artifact_bytes_bound",
    "artifact_sha256_bound",
    "source_authenticated",
    "runtime_authenticated",
    "native_integrity_evaluated",
    "T1_numerical",
    "gate_decision_eligible",
    "qualification_credit",
})


class AttemptOutputBindingError(ValueError):
    """The manifest or synthetic output root is malformed or inconsistent."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AttemptOutputBindingError(message)


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, OverflowError, RecursionError) as error:
        raise AttemptOutputBindingError("manifest is not canonical JSON") from error


def _is_hex16(value: Any) -> bool:
    return type(value) is str and bool(_HEX16.fullmatch(value))


def _is_sha256(value: Any) -> bool:
    return type(value) is str and bool(_HEX64.fullmatch(value))


def _is_identifier(value: Any) -> bool:
    return type(value) is str and bool(_IDENTIFIER.fullmatch(value))


def _validate_process_generation(value: Any, *, label: str) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == _PROCESS_FIELDS,
             f"{label} has an unexpected process-generation schema")
    for field in (
        "pid_namespace_inode_hex",
        "start_monotonic_ns_hex",
        "kernel_starttime_ticks_hex",
        "birth_seq_hex",
    ):
        _require(_is_hex16(value[field]), f"{label}.{field} is not lowercase 16-hex")
    _require(type(value["pid"]) is int and 0 < value["pid"] <= 2**31 - 1,
             f"{label}.pid is not a bounded positive integer")
    return dict(value)


def _validate_root(value: Any) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == _ROOT_FIELDS,
             "output_root has an unexpected schema")
    _require(_is_hex16(value["dev_hex"]), "output_root.dev_hex is not lowercase 16-hex")
    _require(_is_hex16(value["ino_hex"]), "output_root.ino_hex is not lowercase 16-hex")
    for field in ("preexisting", "created_by_attempt", "restart_declared", "append_declared"):
        _require(type(value[field]) is bool, f"output_root.{field} must be a boolean")
    _require(value["preexisting"] is False,
             "output_root.preexisting is rejected")
    _require(value["created_by_attempt"] is True,
             "output_root.created_by_attempt must be true")
    _require(value["restart_declared"] is False,
             "output_root.restart_declared is rejected")
    _require(value["append_declared"] is False,
             "output_root.append_declared is rejected")
    return dict(value)


def _validate_manifest(raw: bytes) -> dict[str, Any]:
    if type(raw) is not bytes:
        raise AttemptOutputBindingError("manifest must be exact bytes")
    _require(0 < len(raw) <= MAX_MANIFEST_BYTES,
             "manifest is outside the bounded byte limit")
    try:
        value = strict_json_object(
            raw,
            label="F8 R008 attempt/output binding manifest",
            max_bytes=MAX_MANIFEST_BYTES,
        )
    except ValueError as error:
        raise AttemptOutputBindingError(str(error)) from error
    _require(set(value) == _INPUT_FIELDS,
             "manifest fields do not match the exact input schema")
    _require(_canonical_json(value) == raw,
             "manifest bytes are not exact canonical JSON")
    _require(value["schema"] == INPUT_SCHEMA, "manifest schema is unsupported")
    _require(_is_identifier(value["attempt_id"]), "attempt_id is malformed")
    _require(type(value["nonce_hex"]) is str and bool(_HEX64.fullmatch(value["nonce_hex"])),
             "nonce_hex is not lowercase 64-hex")
    process_generation = _validate_process_generation(
        value["process_generation"], label="manifest.process_generation")
    for field in (
        "solver_binary_sha256",
        "config_sha256",
        "definition_sha256",
        "control_sha256",
        "initial_state_sha256",
    ):
        _require(_is_sha256(value[field]), f"{field} is not lowercase SHA-256")

    context = value["context"]
    _require(type(context) is dict and set(context) == _CONTEXT_FIELDS,
             "context fields do not match the exact schema")
    _require(type(context["case_np"]) is int and 0 <= context["case_np"] <= 2**64 - 1,
             "context.case_np is not a bounded unsigned integer")
    _require(_is_sha256(context["root_metadata_sha256"]),
             "context.root_metadata_sha256 is not lowercase SHA-256")

    root = _validate_root(value["output_root"])
    writers = value["writers"]
    _require(type(writers) is list and 0 < len(writers) <= MAX_WRITERS,
             "writers must be a bounded non-empty list")
    writer_ids: list[str] = []
    expected_paths: list[str] = []
    seen_paths: set[str] = set()
    normalized_writers: list[dict[str, Any]] = []
    for writer_index, writer in enumerate(writers):
        _require(type(writer) is dict and set(writer) == _WRITER_FIELDS,
                 f"writer {writer_index} fields do not match the exact schema")
        writer_id = writer["writer_id"]
        _require(_is_identifier(writer_id), f"writer {writer_index} has a malformed writer_id")
        _require(writer_id not in writer_ids, f"writer {writer_id} is repeated")
        writer_ids.append(writer_id)
        _require(_is_identifier(writer["writer_role"]),
                 f"writer {writer_id} has a malformed writer_role")
        _require(writer["attempt_id"] == value["attempt_id"],
                 f"writer {writer_id} crosses attempt_id")
        _require(writer["nonce_hex"] == value["nonce_hex"],
                 f"writer {writer_id} crosses attempt nonce")
        writer_process = _validate_process_generation(
            writer["process_generation"], label=f"writer {writer_id}.process_generation")
        _require(writer_process == process_generation,
                 f"writer {writer_id} crosses process generation")
        _require(writer["root_dev_hex"] == root["dev_hex"]
                 and writer["root_ino_hex"] == root["ino_hex"],
                 f"writer {writer_id} has an inconsistent output-root identity")
        files = writer["files"]
        _require(type(files) is list and 0 < len(files) <= MAX_FILES,
                 f"writer {writer_id} must have a bounded non-empty file list")
        file_names: list[str] = []
        normalized_files: list[dict[str, Any]] = []
        for file_index, artifact in enumerate(files):
            _require(type(artifact) is dict and set(artifact) == _FILE_FIELDS,
                     f"writer {writer_id} file {file_index} fields do not match the exact schema")
            name = artifact["relative_path"]
            _require(type(name) is str and bool(_FILE_NAME.fullmatch(name)),
                     f"writer {writer_id} has an unsafe relative_path")
            _require(name not in file_names and name not in seen_paths,
                     f"relative_path {name} is repeated")
            file_names.append(name)
            seen_paths.add(name)
            expected_paths.append(name)
            _require(artifact["writer_id"] == writer_id,
                     f"file {name} has an inconsistent writer identity")
            _require(artifact["attempt_id"] == value["attempt_id"],
                     f"file {name} crosses attempt_id")
            _require(artifact["nonce_hex"] == value["nonce_hex"],
                     f"file {name} crosses attempt nonce")
            artifact_process = _validate_process_generation(
                artifact["process_generation"], label=f"file {name}.process_generation")
            _require(artifact_process == process_generation,
                     f"file {name} crosses process generation")
            _require(_is_hex16(artifact["dev_hex"])
                     and _is_hex16(artifact["ino_hex"]),
                     f"file {name} has an invalid file identity")
            _require(type(artifact["bytes"]) is int
                     and 0 <= artifact["bytes"] <= MAX_FILE_BYTES,
                     f"file {name} has an invalid bounded byte count")
            _require(_is_sha256(artifact["sha256"]),
                     f"file {name} has an invalid SHA-256")
            normalized_files.append(dict(artifact))
        _require(file_names == sorted(file_names),
                 f"writer {writer_id} files are not in canonical path order")
        normalized_writer = dict(writer)
        normalized_writer["process_generation"] = writer_process
        normalized_writer["files"] = normalized_files
        normalized_writers.append(normalized_writer)
    _require(writer_ids == sorted(writer_ids), "writers are not in canonical writer_id order")
    _require(len(expected_paths) <= MAX_FILES,
             "manifest file inventory exceeds the bounded file limit")
    return {
        **value,
        "process_generation": process_generation,
        "context": dict(context),
        "output_root": root,
        "writers": normalized_writers,
    }


def _identity_hex(value: int) -> str:
    _require(type(value) is int and 0 <= value <= 0xFFFFFFFFFFFFFFFF,
             "filesystem identity is outside the fixed 64-bit schema")
    return f"{value:016x}"


def _root_stat(root_path: Path) -> os.stat_result:
    _require(root_path.is_absolute(), "output_root path must be absolute")
    try:
        path_stat = os.stat(root_path, follow_symlinks=False)
    except OSError as error:
        raise AttemptOutputBindingError("output root cannot be stat'ed") from error
    _require(not stat.S_ISLNK(path_stat.st_mode), "output root symlink is rejected")
    _require(stat.S_ISDIR(path_stat.st_mode), "output root is not a directory")
    return path_stat


def _open_root(root_path: Path) -> tuple[int, os.stat_result]:
    _root_stat(root_path)
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise AttemptOutputBindingError("platform lacks O_NOFOLLOW")
    flags = os.O_RDONLY | os.O_DIRECTORY | nofollow | getattr(os, "O_CLOEXEC", 0)
    try:
        root_fd = os.open(root_path, flags)
    except OSError as error:
        raise AttemptOutputBindingError("output root cannot be opened safely") from error
    try:
        descriptor_stat = os.fstat(root_fd)
        _require(stat.S_ISDIR(descriptor_stat.st_mode), "opened output root is not a directory")
        path_stat = _root_stat(root_path)
        _require(
            (descriptor_stat.st_dev, descriptor_stat.st_ino)
            == (path_stat.st_dev, path_stat.st_ino),
            "output root changed during no-follow open",
        )
        return root_fd, descriptor_stat
    except Exception:
        os.close(root_fd)
        raise


def _read_file(root_fd: int, name: str, expected: dict[str, Any]) -> dict[str, Any]:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise AttemptOutputBindingError("platform lacks O_NOFOLLOW")
    try:
        before_path = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
    except OSError as error:
        raise AttemptOutputBindingError(f"artifact {name} cannot be stat'ed") from error
    _require(not stat.S_ISLNK(before_path.st_mode), f"artifact {name} symlink is rejected")
    _require(stat.S_ISREG(before_path.st_mode), f"artifact {name} is not a regular file")
    _require(before_path.st_nlink == 1, f"artifact {name} is not single-link")
    flags = os.O_RDONLY | nofollow | getattr(os, "O_CLOEXEC", 0)
    try:
        file_fd = os.open(name, flags, dir_fd=root_fd)
    except OSError as error:
        raise AttemptOutputBindingError(f"artifact {name} cannot be opened safely") from error
    try:
        before = os.fstat(file_fd)
        _require(stat.S_ISREG(before.st_mode), f"artifact {name} is not a regular file")
        _require(before.st_nlink == 1, f"artifact {name} is not single-link")
        _require(before.st_size <= MAX_FILE_BYTES,
                 f"artifact {name} exceeds the bounded byte limit")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(file_fd, min(1 << 20, remaining))
            _require(chunk != b"", f"artifact {name} ended during bounded read")
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(file_fd)
        after_path = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
    except OSError as error:
        raise AttemptOutputBindingError(f"artifact {name} failed during bounded read") from error
    finally:
        os.close(file_fd)

    before_identity = (
        before.st_dev, before.st_ino, before.st_size,
        before.st_mtime_ns, before.st_ctime_ns, before.st_nlink,
    )
    after_identity = (
        after.st_dev, after.st_ino, after.st_size,
        after.st_mtime_ns, after.st_ctime_ns, after.st_nlink,
    )
    path_identity = (
        after_path.st_dev, after_path.st_ino, after_path.st_size,
        after_path.st_mtime_ns, after_path.st_ctime_ns, after_path.st_nlink,
    )
    _require(after.st_nlink == 1 and after_path.st_nlink == 1,
             f"artifact {name} is not single-link")
    _require(before_identity == after_identity == path_identity,
             f"artifact {name} changed during bounded read")
    raw = b"".join(chunks)
    _require(len(raw) == before.st_size, f"artifact {name} byte count changed")
    observed = {
        "relative_path": name,
        "dev_hex": _identity_hex(before.st_dev),
        "ino_hex": _identity_hex(before.st_ino),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    _require(observed["dev_hex"] == expected["dev_hex"],
             f"artifact {name} device identity differs from manifest")
    _require(observed["ino_hex"] == expected["ino_hex"],
             f"artifact {name} inode identity differs from manifest")
    _require(observed["bytes"] == expected["bytes"],
             f"artifact {name} byte count differs from manifest")
    _require(observed["sha256"] == expected["sha256"],
             f"artifact {name} SHA-256 differs from manifest")
    return observed


def _base_result() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "input_schema": INPUT_SCHEMA,
        "binding_status": "rejected",
        "rejection_reason": None,
        "attempt_id": None,
        "nonce_hex": None,
        "process_generation": None,
        "solver_binary_sha256": None,
        "config_sha256": None,
        "definition_sha256": None,
        "control_sha256": None,
        "initial_state_sha256": None,
        "case_np": None,
        "root_metadata_sha256": None,
        "output_root": None,
        "writers": [],
        "artifacts": [],
        "artifact_count": 0,
        "artifact_bytes": 0,
        "attempt_identity_bound": False,
        "process_generation_bound": False,
        "configuration_hashes_bound": False,
        "fresh_output_root_bound": False,
        "writer_identity_bound": False,
        "artifact_identity_bound": False,
        "artifact_bytes_bound": False,
        "artifact_sha256_bound": False,
        "source_authenticated": False,
        "runtime_authenticated": False,
        "native_integrity_evaluated": False,
        "T1_numerical": False,
        "gate_decision_eligible": False,
        "qualification_credit": 0,
    }


def _populate_claim_projection(result: dict[str, Any], manifest: dict[str, Any]) -> None:
    result.update({
        "attempt_id": manifest["attempt_id"],
        "nonce_hex": manifest["nonce_hex"],
        "process_generation": manifest["process_generation"],
        "solver_binary_sha256": manifest["solver_binary_sha256"],
        "config_sha256": manifest["config_sha256"],
        "definition_sha256": manifest["definition_sha256"],
        "control_sha256": manifest["control_sha256"],
        "initial_state_sha256": manifest["initial_state_sha256"],
        "case_np": manifest["context"]["case_np"],
        "root_metadata_sha256": manifest["context"]["root_metadata_sha256"],
    })


def diagnose_synthetic_attempt_output_binding_v1(
    manifest_raw: bytes,
    output_root: str | os.PathLike[str],
) -> dict[str, Any]:
    """Return a fail-closed diagnostic for one synthetic output directory.

    The function never writes to ``output_root``.  The caller must provide an
    absolute directory and a canonical manifest.  A successful structural
    result still has ``source_authenticated=False``,
    ``gate_decision_eligible=False``, and ``qualification_credit=0``.
    """
    result = _base_result()
    try:
        manifest = _validate_manifest(manifest_raw)
        _populate_claim_projection(result, manifest)
        root_path = Path(os.fspath(output_root))
        root_fd, root_stat = _open_root(root_path)
        try:
            expected_root = manifest["output_root"]
            _require(_identity_hex(root_stat.st_dev) == expected_root["dev_hex"]
                     and _identity_hex(root_stat.st_ino) == expected_root["ino_hex"],
                     "output root device/inode differs from manifest")
            names = os.listdir(root_fd)
            _require(all(type(name) is str for name in names),
                     "output root contains a non-text directory entry")
            expected_by_name: dict[str, dict[str, Any]] = {}
            for writer in manifest["writers"]:
                for artifact in writer["files"]:
                    expected_by_name[artifact["relative_path"]] = artifact
            _require(set(names) == set(expected_by_name),
                     "output root file inventory differs from manifest")
            observed_artifacts: list[dict[str, Any]] = []
            observed_identities: set[tuple[str, str]] = set()
            for name in sorted(expected_by_name):
                observed = _read_file(root_fd, name, expected_by_name[name])
                identity = (observed["dev_hex"], observed["ino_hex"])
                _require(identity not in observed_identities,
                         f"artifact {name} aliases another manifest file identity")
                observed_identities.add(identity)
                observed["writer_id"] = expected_by_name[name]["writer_id"]
                observed_artifacts.append(observed)
            final_root = os.fstat(root_fd)
            path_root = _root_stat(root_path)
            _require(
                (final_root.st_dev, final_root.st_ino)
                == (path_root.st_dev, path_root.st_ino)
                == (root_stat.st_dev, root_stat.st_ino),
                "output root identity changed during binding",
            )
        finally:
            os.close(root_fd)

        output_writers = []
        for writer in manifest["writers"]:
            output_writers.append({
                "writer_id": writer["writer_id"],
                "writer_role": writer["writer_role"],
                "attempt_id": writer["attempt_id"],
                "nonce_hex": writer["nonce_hex"],
                "process_generation": writer["process_generation"],
                "root_dev_hex": writer["root_dev_hex"],
                "root_ino_hex": writer["root_ino_hex"],
                "files": [artifact["relative_path"] for artifact in writer["files"]],
            })
        result.update({
            "binding_status": "synthetic_structural_binding_verified",
            "output_root": dict(manifest["output_root"]),
            "writers": output_writers,
            "artifacts": observed_artifacts,
            "artifact_count": len(observed_artifacts),
            "artifact_bytes": sum(item["bytes"] for item in observed_artifacts),
            "attempt_identity_bound": True,
            "process_generation_bound": True,
            "configuration_hashes_bound": True,
            "fresh_output_root_bound": True,
            "writer_identity_bound": True,
            "artifact_identity_bound": True,
            "artifact_bytes_bound": True,
            "artifact_sha256_bound": True,
        })
    except (AttemptOutputBindingError, OSError, TypeError, ValueError) as error:
        result["rejection_reason"] = str(error)
    _require(set(result) == _OUTPUT_FIELDS, "internal output schema drift")
    return result


__all__ = [
    "INPUT_SCHEMA",
    "SCHEMA",
    "AttemptOutputBindingError",
    "diagnose_synthetic_attempt_output_binding_v1",
]
