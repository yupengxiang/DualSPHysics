"""Read-only structural verifier for one F8 R008 B/C/D evidence bundle.

This verifier closes bundle paths, detached-manifest hashes, file/directory
trees, prelaunch lock bindings, and externally supplied authorization bytes. It
does not authenticate a signer, launch tools, evaluate native integrity, compute
metrics, or grant qualification credit.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import struct
from typing import Any, Mapping

from scripts import f8_r008_safe_bi4_decoder_v1 as decoder
from scripts import f8_r008_safe_bi4_metadata_binding_v1 as metadata_binding


SCHEMA = "core.cfd.f8.r008_per_case_bundle_verifier.v1"
SCOPE_ID = "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R008"
LAB = Path(__file__).resolve().parents[1]
FROZEN_DEFINITION_PACK = LAB / "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/definition-control-pack-v1/receipt.json"
FROZEN_SCOPE_RECEIPT = LAB / "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/t1-scope-design-v1/receipt.json"
FROZEN_INPUT_SHA256 = {
    "definition_pack": "d5b657db398e0c0b102cdb84de8fe0a302c22c85d4bbf16bc0b6e6bf16065fcb",
    "scope": "65671b42523cd3a5f82338cc7e2d88890af634195d7013ad969311166ab36ac8",
}
AUTH_FIELDS = {
    "schema", "authority_id", "stage", "scope_id", "case_id", "attempt_id", "nonce",
    "exclusive_output_root", "executable_sha256", "wrapper_sha256", "argv", "input_bindings",
    "invocation_budget", "resource_limits", "issued_at_utc", "expires_at_utc",
}
LOCK_FIELDS = {
    "schema", "authority_sha256", "stage", "scope_id", "case_id", "attempt_id", "nonce",
    "exclusive_output_root", "created_at_utc", "exclusive_create_succeeded",
}
FORBIDDEN_AUTH_KEYS = {
    "receipt_sha256", "output_manifest_sha256", "raw_solver_manifest_sha256",
    "decoded_frame_manifest_sha256", "table_sha256", "downstream_output_digest",
}
STAGE_RECEIPT_SCHEMAS = {
    "B": "core.cfd.f8.r008_materialization_receipt.v1",
    "C": "core.cfd.f8.r008_solver_attempt_receipt.v1",
    "D": "core.cfd.f8.r008_decode_table_provenance.v1",
}
STAGE_MANIFEST_NAMES = {
    "B": ("materialization-output-manifest.json",),
    "C": ("raw-solver-manifest.json",),
    "D": ("decoded-frame-manifest.json", "outputs-manifest.json"),
}
STAGE_OUTPUT_MANIFESTS = {
    "B": ("output_manifest", "manifests/materialization-output-manifest.json",
          "core.cfd.f8.r008_materialization_output_manifest.v1"),
    "C": ("raw_output_manifest", "manifests/raw-solver-manifest.json",
          "core.cfd.f8.r008_raw_solver_manifest.v1"),
    "D": ("outputs_manifest_binding", "manifests/outputs-manifest.json",
          "core.cfd.f8.r008_decode_outputs_manifest.v1"),
}
STAGE_REQUIRED_FIELDS = {
    "B": {
        "schema", "scope_id", "case_id", "attempt_id", "nonce", "status", "started_at_utc",
        "ended_at_utc", "authorization_binding", "one_shot_lock_binding", "definition_binding",
        "control_binding", "gencase_execution", "generated_xml_path", "initial_bi4_path",
        "safe_decode_receipt", "metadata_binding", "particle_cohorts", "output_manifest",
        "execution_controls",
    },
    "C": {
        "schema", "scope_id", "case_id", "attempt_id", "nonce", "status", "started_at_utc",
        "ended_at_utc", "authorization_binding", "one_shot_lock_binding",
        "materialization_receipt_binding", "solver_execution", "raw_output_manifest",
        "execution_controls",
    },
    "D": {
        "schema", "scope_id", "case_id", "attempt_id", "nonce", "status", "started_at_utc",
        "ended_at_utc", "authorization_binding", "one_shot_lock_binding", "solver_receipt_binding",
        "decoder_code_binding", "decoded_frame_manifest_binding", "outputs_manifest_binding",
        "frame_mappings", "native_fluid_table_binding", "execution_controls",
    },
}
MANIFEST_DOCUMENT_FIELDS = {
    "B": {"schema", "stage", "files", "directories"},
    "C": {"schema", "stage", "files", "directories", "frames"},
    "D_outputs": {"schema", "stage", "files", "directories"},
    "D_frames": {"schema", "stage", "case_id", "attempt_id", "raw_solver_manifest_sha256", "frames"},
}
MANIFEST_FORBIDDEN_KEYS = {
    "all": {
        "receipt_sha256", "enclosing_receipt_sha256", "output_manifest_sha256",
        "decoded_frame_manifest_sha256", "table_sha256", "downstream_output_digest",
    },
    "B": {"solver_receipt_sha256", "raw_solver_manifest_sha256", "decoded_frame_manifest_sha256", "table_sha256"},
    "C": {"solver_receipt_sha256", "raw_solver_manifest_sha256", "decoded_frame_manifest_sha256",
          "decode_receipt_sha256", "table_sha256"},
    "D_frames": {"decode_table_receipt_sha256", "native_fluid_table_sha256"},
}
D_FRAME_FIELDS = {
    "ordinal", "expected_time_s_ieee754_hex", "parser_observed_time_s_ieee754_hex",
    "raw_solver_manifest_sha256", "raw_solver_ordinal", "raw_path", "raw_bytes", "raw_sha256",
    "safe_decode_input_sha256", "safe_decode_receipt_path", "safe_decode_receipt_bytes",
    "safe_decode_receipt_sha256", "metadata_binding_manifest_path",
    "metadata_binding_manifest_bytes", "metadata_binding_manifest_sha256",
    "decoded_output_parent_relative_path", "decoded_output_name",
}
SAFE_DECODE_RECEIPT_FIELDS = {
    "schema", "status", "input", "xml", "arrays", "array_file_count",
    "total_output_bytes", "tree_closed", "execution_authority",
}
SAFE_DECODE_INPUT_FIELDS = {"sha256", "bytes", "identity"}
SAFE_DECODE_XML_FIELDS = {"path", "bytes", "sha256", "regular_file", "link_count"}
SAFE_DECODE_ARRAY_FIELDS = {
    "path", "array_name", "type_code", "type_name", "dtype", "shape", "count",
    "bytes", "sha256", "regular_file", "link_count",
}
SAFE_DECODE_EXECUTION_AUTHORITY = {
    "native_binary_invoked": False,
    "gencase_invoked": False,
    "solver_invoked": False,
    "worker_started": False,
    "gpu_invoked": False,
    "queue_mutation": 0,
    "qualification_credit": 0,
}
CODE_SOURCE_PATHS = {
    "safe_bi4_decoder": "scripts/f8_r008_safe_bi4_decoder_v1.py",
    "metadata_binding_api": "scripts/f8_r008_safe_bi4_metadata_binding_v1.py",
    "per_case_bundle_verifier": "scripts/f8_r008_per_case_bundle_verifier_v1.py",
}
TRUSTED_CODE_BINDING_FIELDS = {
    "safe_bi4_decoder", "metadata_binding_api", "per_case_bundle_verifier",
    "independent_review_receipt_sha256",
}
CODE_SOURCE_BINDING_FIELDS = {"path", "bytes", "sha256"}
CODE_REVIEW_SCHEMA = "core.cfd.f8.r008_per_case_provenance_implementation_review.v1"
CODE_REVIEW_FIELDS = {
    "schema", "record_id", "status", "reviewer", "code_bindings", "review_boundary",
}
CODE_REVIEWER_FIELDS = {
    "model", "reasoning_effort", "agent_id", "verdict", "review_mode",
    "reviewer_ran_tests", "execution_or_evidence_mutation",
}
CODE_REVIEW_BOUNDARY = {
    "native_tools_invoked": False,
    "solver_or_worker_invoked": False,
    "gpu_or_queue_invoked": False,
    "production_evidence_mutated": False,
}
TRUSTED_RUNTIME_ASSUMPTION_FIELDS = {
    "interpreter_trusted", "fresh_process", "import_path_pinned", "preloaded_module_state_unmodified",
}
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
PATH_COMPONENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z", re.ASCII)
MAX_RECEIPT_BYTES = 8 * 1024 * 1024
MAX_FILE_COUNT = 20000
MAX_STAGE_BYTES = 64 * 1024**3
MAX_DEPTH = 16
READ_CHUNK = 1024 * 1024
O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)


class BundleVerificationError(ValueError):
    """A stage bundle is incomplete, inconsistent, unsafe, or untrusted."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise BundleVerificationError(message)


def _canonical_json(value: Any) -> bytes:
    try:
        return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise BundleVerificationError("JSON artifact is not canonically serializable") from error


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BundleVerificationError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise BundleVerificationError(f"non-finite JSON numeric constant is forbidden: {value}")


def _parse_json(payload: bytes, label: str) -> Any:
    try:
        return json.loads(
            payload.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BundleVerificationError(f"invalid UTF-8 JSON artifact: {label}") from error


def _identity(st: os.stat_result) -> tuple[int, int, int, int, int]:
    return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns


def _open_absolute_directory(path: Path | str) -> tuple[int, str]:
    raw_path = os.fspath(path)
    _require(raw_path.startswith("/"), "bundle root must be an absolute path")
    components = raw_path.split("/")[1:]
    _require(all(part not in {"", ".", ".."} for part in components),
             "bundle root path must be normalized and contain no dot components")
    current_fd = os.open("/", os.O_RDONLY | O_DIRECTORY | O_CLOEXEC)
    try:
        for component in components:
            next_fd = os.open(
                component, os.O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC,
                dir_fd=current_fd,
            )
            os.close(current_fd)
            current_fd = next_fd
        absolute = "/" + "/".join(components)
        return current_fd, absolute
    except BaseException:
        os.close(current_fd)
        raise


def _validate_component(component: str) -> None:
    _require(bool(PATH_COMPONENT_RE.fullmatch(component)), f"unsafe path component: {component!r}")
    _require(component not in {".", ".."}, "dot path components are forbidden")


def _validate_relative_path(path: Any) -> str:
    _require(isinstance(path, str) and bool(path), "manifest path must be a non-empty string")
    _require(not path.startswith("/") and "\\" not in path, "manifest path must be relative POSIX")
    parts = path.split("/")
    _require(len(parts) <= MAX_DEPTH and all(parts), "manifest path has empty/over-depth components")
    for part in parts:
        _validate_component(part)
    return path


def _stable_read_file_at(parent_fd: int, name: str, max_bytes: int) -> tuple[bytes, os.stat_result]:
    _validate_component(name)
    fd = os.open(name, os.O_RDONLY | O_NOFOLLOW | O_CLOEXEC, dir_fd=parent_fd)
    try:
        before = os.fstat(fd)
        _require(stat.S_ISREG(before.st_mode), f"expected a regular file: {name}")
        _require(before.st_nlink == 1, f"file must have exactly one hard link: {name}")
        _require(0 <= before.st_size <= max_bytes, f"file exceeds its byte cap: {name}")
        named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        _require(stat.S_ISREG(named.st_mode) and (named.st_dev, named.st_ino) == (before.st_dev, before.st_ino),
                 f"file path changed while opening: {name}")
        payload = bytearray()
        while len(payload) < before.st_size:
            block = os.read(fd, min(READ_CHUNK, before.st_size - len(payload)))
            _require(bool(block), f"file was truncated while reading: {name}")
            payload.extend(block)
        _require(os.read(fd, 1) == b"", f"file grew while reading: {name}")
        after = os.fstat(fd)
        _require(_identity(before) == _identity(after) and before.st_nlink == after.st_nlink,
                 f"file changed while reading: {name}")
        return bytes(payload), after
    finally:
        os.close(fd)


def _stable_read_beneath(root_fd: int, relative_path: str, max_bytes: int) -> bytes:
    parts = _validate_relative_path(relative_path).split("/")
    parent_fd = os.dup(root_fd)
    try:
        for component in parts[:-1]:
            next_fd = _open_child_directory(parent_fd, component)
            os.close(parent_fd)
            parent_fd = next_fd
        return _stable_read_file_at(parent_fd, parts[-1], max_bytes)[0]
    finally:
        os.close(parent_fd)


def _hash_file_at(
    parent_fd: int, name: str, max_bytes: int, expected_stat: os.stat_result | None = None,
) -> dict[str, Any]:
    _validate_component(name)
    fd = os.open(name, os.O_RDONLY | O_NOFOLLOW | O_CLOEXEC, dir_fd=parent_fd)
    try:
        before = os.fstat(fd)
        _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1,
                 f"tree file is not a single-link regular file: {name}")
        _require(0 <= before.st_size <= max_bytes, f"tree file exceeds stage cap: {name}")
        named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        _require(stat.S_ISREG(named.st_mode) and (named.st_dev, named.st_ino) == (before.st_dev, before.st_ino),
                 f"tree file changed while opening: {name}")
        if expected_stat is not None:
            _require((expected_stat.st_dev, expected_stat.st_ino) == (before.st_dev, before.st_ino),
                     f"tree file changed between enumeration and opening: {name}")
        digest = hashlib.sha256()
        remaining = before.st_size
        while remaining:
            block = os.read(fd, min(READ_CHUNK, remaining))
            _require(bool(block), f"tree file was truncated while hashing: {name}")
            digest.update(block)
            remaining -= len(block)
        _require(os.read(fd, 1) == b"", f"tree file grew while hashing: {name}")
        after = os.fstat(fd)
        _require(_identity(before) == _identity(after) and before.st_nlink == after.st_nlink,
                 f"tree file changed while hashing: {name}")
        return {"bytes": before.st_size, "sha256": digest.hexdigest(), "regular_file": True, "link_count": 1}
    finally:
        os.close(fd)


def _open_child_directory(parent_fd: int, name: str) -> int:
    _validate_component(name)
    named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    _require(stat.S_ISDIR(named.st_mode), f"expected a real directory, not a symlink: {name}")
    child_fd = os.open(name, os.O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC, dir_fd=parent_fd)
    opened = os.fstat(child_fd)
    if not stat.S_ISDIR(opened.st_mode) or (named.st_dev, named.st_ino) != (opened.st_dev, opened.st_ino):
        os.close(child_fd)
        raise BundleVerificationError(f"directory path changed while opening: {name}")
    return child_fd


def _bounded_directory_names(directory_fd: int, max_entries: int, label: str) -> list[str]:
    names: list[str] = []
    with os.scandir(directory_fd) as entries:
        for entry in entries:
            names.append(entry.name)
            _require(len(names) <= max_entries, f"{label} exceeds its directory-entry cap")
    return names


def _inventory_tree(root_fd: int) -> tuple[dict[str, dict[str, Any]], list[str]]:
    files: dict[str, dict[str, Any]] = {}
    directories: list[str] = []
    total_bytes = 0
    total_entries = 0

    def walk(directory_fd: int, prefix: tuple[str, ...]) -> None:
        nonlocal total_bytes, total_entries
        before = os.fstat(directory_fd)
        _require(stat.S_ISDIR(before.st_mode), "tree descriptor is not a directory")
        with os.scandir(directory_fd) as entries:
            for entry in entries:
                name = entry.name
                total_entries += 1
                _require(total_entries <= MAX_FILE_COUNT,
                         "outputs exceed the combined per-stage file/directory entry cap")
                _validate_component(name)
                entry_stat = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                rel = "/".join(prefix + (name,))
                _validate_relative_path(rel)
                if stat.S_ISDIR(entry_stat.st_mode):
                    child_fd = _open_child_directory(directory_fd, name)
                    try:
                        directories.append(rel)
                        _require(len(directories) <= MAX_FILE_COUNT,
                                 "outputs exceed the per-stage directory-count cap")
                        walk(child_fd, prefix + (name,))
                        final_named = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                        final_open = os.fstat(child_fd)
                        _require(stat.S_ISDIR(final_named.st_mode)
                                 and (final_named.st_dev, final_named.st_ino) == (final_open.st_dev, final_open.st_ino)
                                 and (entry_stat.st_dev, entry_stat.st_ino) == (final_open.st_dev, final_open.st_ino),
                                 f"directory changed during inventory: {rel}")
                    finally:
                        os.close(child_fd)
                elif stat.S_ISREG(entry_stat.st_mode):
                    _require(entry_stat.st_nlink == 1, f"tree file has hard links: {rel}")
                    binding = _hash_file_at(directory_fd, name, MAX_STAGE_BYTES, entry_stat)
                    files[rel] = binding
                    total_bytes += binding["bytes"]
                    _require(total_bytes <= MAX_STAGE_BYTES, "outputs exceed the per-stage byte cap")
                    _require(len(files) <= MAX_FILE_COUNT, "outputs exceed the per-stage file-count cap")
                else:
                    raise BundleVerificationError(f"tree contains symlink or special object: {rel}")
        after = os.fstat(directory_fd)
        _require((before.st_dev, before.st_ino, before.st_mtime_ns, before.st_ctime_ns)
                 == (after.st_dev, after.st_ino, after.st_mtime_ns, after.st_ctime_ns),
                 "directory changed while enumerating the output tree")

    walk(root_fd, ())
    return files, sorted(directories)


def _validate_file_path_list(files: Any) -> tuple[dict[str, dict[str, Any]], list[str]]:
    _require(isinstance(files, list), "manifest files must be an array")
    _require(len(files) <= MAX_FILE_COUNT, "manifest exceeds the per-stage file-count cap")
    expected: dict[str, dict[str, Any]] = {}
    ordered: list[str] = []
    for entry in files:
        _require(isinstance(entry, dict) and set(entry) == {"path", "bytes", "sha256", "regular_file", "link_count"},
                 "file entry has unexpected/missing fields")
        path = _validate_relative_path(entry["path"])
        _require(path not in expected, f"duplicate manifest file path: {path}")
        _require(isinstance(entry["bytes"], int) and not isinstance(entry["bytes"], bool)
                 and 0 <= entry["bytes"] <= MAX_STAGE_BYTES, f"invalid manifest file byte count: {path}")
        _require(isinstance(entry["sha256"], str) and bool(SHA256_RE.fullmatch(entry["sha256"])),
                 f"invalid manifest file digest: {path}")
        _require(entry["regular_file"] is True and isinstance(entry["link_count"], int)
                 and not isinstance(entry["link_count"], bool) and entry["link_count"] == 1,
                 f"manifest file is not a closed single-link regular file: {path}")
        expected[path] = {
            "bytes": entry["bytes"], "sha256": entry["sha256"],
            "regular_file": True, "link_count": 1,
        }
        ordered.append(path)
    _require(ordered == sorted(ordered), "manifest files are not sorted by path")
    return expected, ordered


def _validate_directory_path_list(directories: Any) -> list[str]:
    _require(isinstance(directories, list), "manifest directories must be an array")
    checked = [_validate_relative_path(path) for path in directories]
    _require(len(checked) == len(set(checked)), "duplicate manifest directory path")
    _require(checked == sorted(checked), "manifest directories are not sorted by path")
    return checked


def _parse_utc(value: Any, label: str) -> datetime:
    _require(isinstance(value, str) and value.endswith("Z"), f"{label} must be an RFC3339 UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise BundleVerificationError(f"invalid UTC timestamp: {label}") from error
    _require(parsed.tzinfo is not None and parsed.utcoffset() == timezone.utc.utcoffset(parsed),
             f"{label} is not UTC")
    return parsed


def _reject_forbidden_digest_keys(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            _require(key not in FORBIDDEN_AUTH_KEYS, f"prelaunch authorization/lock contains forbidden downstream digest field: {key}")
            _reject_forbidden_digest_keys(item)
    elif isinstance(value, list):
        for item in value:
            _reject_forbidden_digest_keys(item)


def _reject_manifest_cycle_keys(value: Any, kind: str) -> None:
    forbidden = MANIFEST_FORBIDDEN_KEYS["all"] | MANIFEST_FORBIDDEN_KEYS.get(kind, set())
    if isinstance(value, dict):
        for key, item in value.items():
            _require(key not in forbidden, f"manifest contains forbidden self/enclosing/downstream digest field: {key}")
            _reject_manifest_cycle_keys(item, kind)
    elif isinstance(value, list):
        for item in value:
            _reject_manifest_cycle_keys(item, kind)


def _read_root_json(root_fd: int, filename: str, max_bytes: int) -> tuple[dict[str, Any], bytes]:
    payload, _st = _stable_read_file_at(root_fd, filename, max_bytes)
    value = _parse_json(payload, filename)
    _require(isinstance(value, dict), f"{filename} must contain a JSON object")
    return value, payload


def _read_manifest_file(manifests_fd: int, filename: str) -> tuple[dict[str, Any], bytes]:
    payload, _st = _stable_read_file_at(manifests_fd, filename, MAX_RECEIPT_BYTES)
    value = _parse_json(payload, filename)
    _require(isinstance(value, dict), f"{filename} must contain a JSON object")
    _require(_canonical_json(value) == payload, f"detached manifest is not in the frozen canonical JSON encoding: {filename}")
    return value, payload


def _binding_matches(binding: Any, path: str, payload: bytes, label: str) -> None:
    _require(isinstance(binding, dict) and set(binding) == {"path", "bytes", "sha256"},
             f"{label} reference has unexpected/missing fields")
    _require(binding["path"] == path, f"{label} reference path mismatch")
    _require(isinstance(binding["bytes"], int) and not isinstance(binding["bytes"], bool)
             and binding["bytes"] == len(payload), f"{label} reference byte count mismatch")
    _require(binding["sha256"] == hashlib.sha256(payload).hexdigest(), f"{label} reference SHA-256 mismatch")


def _frozen_qualification_row(case_id: str) -> dict[str, Any]:
    pack_path = FROZEN_DEFINITION_PACK
    scope_path = FROZEN_SCOPE_RECEIPT
    lab_fd, _lab_path = _open_absolute_directory(LAB)
    try:
        pack_bytes = _stable_read_beneath(lab_fd, pack_path.relative_to(LAB).as_posix(), MAX_RECEIPT_BYTES)
        scope_bytes = _stable_read_beneath(lab_fd, scope_path.relative_to(LAB).as_posix(), MAX_RECEIPT_BYTES)
    finally:
        os.close(lab_fd)
    _require(hashlib.sha256(pack_bytes).hexdigest() == FROZEN_INPUT_SHA256["definition_pack"],
             "frozen definition-control pack hash changed")
    _require(hashlib.sha256(scope_bytes).hexdigest() == FROZEN_INPUT_SHA256["scope"],
             "frozen R008 scope receipt hash changed")
    pack = _parse_json(pack_bytes, "frozen definition-control pack")
    scope = _parse_json(scope_bytes, "frozen R008 scope receipt")
    pack_rows = [row for row in pack.get("cases", []) if row.get("case_id") == case_id]
    scope_rows = [row for row in scope.get("matrix", {}).get("rows", []) if row.get("case_id") == case_id]
    qualified_rows = [row for row in scope.get("matrix", {}).get("rows", []) if row.get("qualification_only") is True]
    _require(len(qualified_rows) == 15, "frozen scope no longer has exactly 15 qualification rows")
    _require(len(pack_rows) == 1 and pack_rows[0].get("qualification_only") is True,
             "case is not exactly one frozen qualification-only Definition/control row")
    _require(len(scope_rows) == 1 and scope_rows[0].get("qualification_only") is True,
             "case is not exactly one frozen qualification-only scope row")
    _require(pack_rows[0]["case_id"] == scope_rows[0]["case_id"], "frozen pack/scope case identity mismatch")
    return pack_rows[0]


def expected_time_axis_hex(case_row: Mapping[str, Any]) -> list[str]:
    """Build the frozen full native axis without cumulative floating addition."""
    try:
        count = case_row["full_native_output_rows_to_timemax"]
        dt = float(case_row["native_output_dt_s"])
        endpoint = float(case_row["observation_end_s"])
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        raise BundleVerificationError("frozen row has invalid full-output cadence fields") from error
    _require(isinstance(count, int) and not isinstance(count, bool) and 2 <= count <= 20000,
             "frozen full-output row count is outside the bundle cap")
    _require(math.isfinite(dt) and dt > 0.0 and math.isfinite(endpoint) and endpoint > 0.0,
             "frozen output cadence or endpoint is non-positive/non-finite")
    times = [0.0]
    times.extend(float(index) * dt for index in range(1, count - 1))
    times.append(endpoint)
    _require(all(math.isfinite(value) for value in times), "constructed frozen output axis is non-finite")
    _require(all(left < right for left, right in zip(times, times[1:])),
             "constructed frozen output axis is not strictly increasing")
    _require(times[-1] == endpoint, "constructed frozen output axis misses its exact endpoint")
    return [value.hex() for value in times]


def _validate_tree_manifest(
    outputs_fd: int,
    manifest: Mapping[str, Any],
    expected_schema: str,
    expected_stage: str,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    kind = "D_outputs" if expected_stage == "D" else expected_stage
    _require(set(manifest) == MANIFEST_DOCUMENT_FIELDS[kind],
             f"{expected_stage} output manifest top-level fields are not exact")
    _reject_manifest_cycle_keys(manifest, kind)
    _require(manifest.get("schema") == expected_schema and manifest.get("stage") == expected_stage,
             "output manifest schema/stage mismatch")
    expected_files, _ordered = _validate_file_path_list(manifest.get("files"))
    expected_directories = _validate_directory_path_list(manifest.get("directories"))
    _require(not (set(expected_files) & set(expected_directories)), "manifest path is both a file and directory")
    for path in expected_files:
        parts = path.split("/")
        _require(not any("/".join(parts[:index]) in expected_files for index in range(1, len(parts))),
                 f"manifest file is a parent of another path: {path}")
        _require(all("/".join(parts[:index]) in expected_directories for index in range(1, len(parts))),
                 f"manifest file is missing a parent directory: {path}")
    for path in expected_directories:
        parts = path.split("/")
        _require(all("/".join(parts[:index]) in expected_directories for index in range(1, len(parts))),
                 f"manifest directory is missing a parent directory: {path}")
        _require(not any("/".join(parts[:index]) in expected_files for index in range(1, len(parts) + 1)),
                 f"manifest directory is beneath a file: {path}")
    actual_files, actual_directories = _inventory_tree(outputs_fd)
    _require(actual_files == expected_files, "detached manifest files do not equal the recursive outputs file tree")
    _require(actual_directories == expected_directories,
             "detached manifest directories do not equal the recursive outputs directory tree")
    return expected_files, expected_directories


def _verify_bound_output(
    outputs_fd: int,
    output_files: Mapping[str, Mapping[str, Any]],
    path: Any,
    byte_count: Any,
    digest: Any,
    label: str,
) -> str:
    relative = _validate_relative_path(path)
    _require(isinstance(byte_count, int) and not isinstance(byte_count, bool) and byte_count >= 0,
             f"{label} byte count is invalid")
    _require(isinstance(digest, str) and bool(SHA256_RE.fullmatch(digest)),
             f"{label} SHA-256 is malformed")
    entry = output_files.get(relative)
    _require(entry is not None and entry["bytes"] == byte_count and entry["sha256"] == digest,
             f"{label} does not bind an exact file in the closed D outputs manifest")
    parts = relative.split("/")
    parent_fd = os.dup(outputs_fd)
    try:
        for component in parts[:-1]:
            child_fd = _open_child_directory(parent_fd, component)
            os.close(parent_fd)
            parent_fd = child_fd
        observed = _hash_file_at(parent_fd, parts[-1], MAX_STAGE_BYTES)
    finally:
        os.close(parent_fd)
    _require(observed["bytes"] == byte_count and observed["sha256"] == digest,
             f"{label} changed after outputs-tree inventory")
    return relative


def _read_bound_output(
    outputs_fd: int,
    output_files: Mapping[str, Mapping[str, Any]],
    path: Any,
    byte_count: Any,
    digest: Any,
    label: str,
) -> tuple[str, bytes]:
    relative = _verify_bound_output(outputs_fd, output_files, path, byte_count, digest, label)
    payload = _stable_read_beneath(outputs_fd, relative, MAX_RECEIPT_BYTES)
    _require(len(payload) == byte_count and hashlib.sha256(payload).hexdigest() == digest,
             f"{label} changed after outputs-tree inventory")
    return relative, payload


def _metadata_record_index(document: Mapping[str, Any]) -> dict[tuple[tuple[str, ...], str], Mapping[str, Any]]:
    _require(set(document) == {
        "schema", "input_sha256", "input_bytes", "metadata_records", "required_semantics",
    }, "metadata-binding manifest fields are not exact")
    _require(document.get("schema") == metadata_binding.SCHEMA,
             "metadata-binding manifest schema mismatch")
    records = document.get("metadata_records")
    _require(isinstance(records, list), "metadata-binding records must be an array")
    result: dict[tuple[tuple[str, ...], str], Mapping[str, Any]] = {}
    record_fields = {
        "item_path", "metadata_name", "type_code", "type_name", "raw_value_bytes_hex",
        "canonical_value", "float_hex_components",
    }
    for record in records:
        _require(isinstance(record, dict) and set(record) == record_fields,
                 "metadata-binding record fields are not exact")
        item_path = record.get("item_path")
        name = record.get("metadata_name")
        _require(isinstance(item_path, list) and item_path and all(isinstance(item, str) for item in item_path)
                 and isinstance(name, str) and name, "metadata-binding record identity is malformed")
        key = (tuple(item_path), name)
        _require(key not in result, "metadata-binding records contain a duplicate value")
        type_code = record.get("type_code")
        _require(isinstance(type_code, int) and not isinstance(type_code, bool),
                 "metadata-binding type code is malformed")
        raw_hex = record.get("raw_value_bytes_hex")
        _require(isinstance(raw_hex, str) and len(raw_hex) % 2 == 0
                 and all(character in "0123456789abcdef" for character in raw_hex),
                 "metadata-binding raw value bytes are malformed")
        components = record.get("float_hex_components")
        _require(isinstance(components, list) and all(isinstance(value, str) for value in components),
                 "metadata-binding floating components are malformed")
        for component in components:
            try:
                number = float.fromhex(component)
            except ValueError as error:
                raise BundleVerificationError("metadata-binding floating component is invalid hex") from error
            _require(math.isfinite(number) and number.hex() == component,
                     "metadata-binding floating component is non-finite or noncanonical")
        result[key] = record
    required_semantics = {
        "MassFluid": "root/global positive finite binary64 kg per particle",
        "TimeStep": "selected PART non-negative finite binary64 seconds; negative zero rejected",
        "Npok": "selected PART positive uint32 particle count",
    }
    _require(document.get("required_semantics") == required_semantics,
             "metadata-binding semantic declarations differ from the frozen API contract")
    return result


def _verify_d_code_binding(
    receipt_binding: Any,
    trusted_review_receipt_bytes: bytes | None,
) -> None:
    _require(isinstance(trusted_review_receipt_bytes, bytes)
             and 0 < len(trusted_review_receipt_bytes) <= MAX_RECEIPT_BYTES,
             "D verification requires exact caller-trusted independent code review receipt bytes")
    review_sha = hashlib.sha256(trusted_review_receipt_bytes).hexdigest()
    review = _parse_json(trusted_review_receipt_bytes, "trusted independent code review receipt")
    _require(isinstance(review, dict) and set(review) == CODE_REVIEW_FIELDS
             and review.get("schema") == CODE_REVIEW_SCHEMA
             and review.get("record_id") == "f8-r008-per-case-provenance-implementation-review-v1"
             and review.get("status") == "PASS",
             "caller-trusted code review receipt is not the exact expected PASS record")
    reviewer = review.get("reviewer")
    _require(isinstance(reviewer, dict) and set(reviewer) == CODE_REVIEWER_FIELDS
             and reviewer.get("model") == "gpt-5.6-terra"
             and reviewer.get("reasoning_effort") == "high"
             and reviewer.get("agent_id") == "01a0d167-4db5-7f90-aee2-94547602a273"
             and reviewer.get("verdict") == "PASS"
             and reviewer.get("review_mode") == "read_only_static_implementation_review"
             and reviewer.get("reviewer_ran_tests") is False
             and reviewer.get("execution_or_evidence_mutation") is False
             and review.get("review_boundary") == CODE_REVIEW_BOUNDARY,
             "caller-trusted code review receipt is not a Terra High static implementation PASS")
    reviewed_sources = review.get("code_bindings")
    _require(isinstance(reviewed_sources, dict) and set(reviewed_sources) == set(CODE_SOURCE_PATHS),
             "independent review receipt does not bind all decoder/API/verifier sources")
    expected_binding = {
        **reviewed_sources,
        "independent_review_receipt_sha256": review_sha,
    }
    _require(isinstance(receipt_binding, dict)
             and set(receipt_binding) == TRUSTED_CODE_BINDING_FIELDS
             and receipt_binding == expected_binding,
             "D decoder/API code binding differs from caller-trusted independent review receipt")
    lab_fd, _lab_path = _open_absolute_directory(LAB)
    try:
        for key, expected_path in CODE_SOURCE_PATHS.items():
            binding = reviewed_sources.get(key)
            _require(isinstance(binding, Mapping) and set(binding) == CODE_SOURCE_BINDING_FIELDS,
                     f"trusted {key} binding fields are not exact")
            _require(binding.get("path") == expected_path,
                     f"trusted {key} path differs from its frozen source path")
            _require(isinstance(binding.get("bytes"), int) and not isinstance(binding.get("bytes"), bool)
                     and binding["bytes"] > 0
                     and isinstance(binding.get("sha256"), str)
                     and bool(SHA256_RE.fullmatch(binding["sha256"])),
                     f"trusted {key} byte/hash binding is malformed")
            payload = _stable_read_beneath(lab_fd, expected_path, MAX_RECEIPT_BYTES)
            _require(len(payload) == binding["bytes"]
                     and hashlib.sha256(payload).hexdigest() == binding["sha256"],
                     f"local reviewed source file {key} differs from its caller-trusted independent review binding")
    finally:
        os.close(lab_fd)


def _verify_runtime_assumption(value: Mapping[str, Any] | None) -> None:
    _require(isinstance(value, Mapping) and set(value) == TRUSTED_RUNTIME_ASSUMPTION_FIELDS
             and all(value.get(key) is True for key in TRUSTED_RUNTIME_ASSUMPTION_FIELDS),
             "D verification requires explicit caller attestation of the trusted Python runtime/module-state TCB")


def _check_d_frame_artifacts(
    outputs_fd: int,
    output_files: Mapping[str, Mapping[str, Any]],
    frame: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    safe_path, safe_payload = _read_bound_output(
        outputs_fd, output_files, frame["safe_decode_receipt_path"],
        frame["safe_decode_receipt_bytes"], frame["safe_decode_receipt_sha256"],
        "safe-decode receipt",
    )
    safe_receipt = _parse_json(safe_payload, "safe-decode receipt")
    _require(isinstance(safe_receipt, dict) and set(safe_receipt) == SAFE_DECODE_RECEIPT_FIELDS
             and _canonical_json(safe_receipt) == safe_payload,
             "safe-decode receipt is not an exact canonical document")
    _require(safe_receipt.get("schema") == decoder.SCHEMA
             and safe_receipt.get("status") == "safe_decode_complete"
             and safe_receipt.get("tree_closed") is True,
             "safe-decode receipt does not record a completed closed safe decode")
    input_binding = safe_receipt.get("input")
    _require(isinstance(input_binding, dict) and set(input_binding) == SAFE_DECODE_INPUT_FIELDS,
             "safe-decode receipt input binding fields are not exact")
    _require(input_binding.get("sha256") == frame["raw_sha256"]
             and input_binding.get("bytes") == frame["raw_bytes"],
             "safe-decode receipt input differs from C manifest raw-frame binding")
    identity = input_binding.get("identity")
    _require(isinstance(identity, list) and len(identity) == 5
             and all(isinstance(value, int) and not isinstance(value, bool) for value in identity),
             "safe-decode receipt input identity is malformed")
    _require(safe_receipt.get("execution_authority") == SAFE_DECODE_EXECUTION_AUTHORITY,
             "safe-decode receipt claims an unexpected execution authority")

    parent = _validate_relative_path(frame["decoded_output_parent_relative_path"])
    output_name = frame["decoded_output_name"]
    _validate_component(output_name)
    output_prefix = f"{parent}/{output_name}"
    xml_record = safe_receipt.get("xml")
    _require(isinstance(xml_record, dict) and set(xml_record) == SAFE_DECODE_XML_FIELDS,
             "safe-decode XML binding fields are not exact")
    _require(xml_record.get("path") == f"{output_name}.xml"
             and isinstance(xml_record.get("bytes"), int) and not isinstance(xml_record.get("bytes"), bool)
             and isinstance(xml_record.get("sha256"), str)
             and bool(SHA256_RE.fullmatch(xml_record["sha256"]))
             and xml_record.get("regular_file") is True
             and isinstance(xml_record.get("link_count"), int)
             and not isinstance(xml_record.get("link_count"), bool)
             and xml_record["link_count"] == 1,
             "safe-decode XML binding path or file type is invalid")
    xml_relative = _verify_bound_output(
        outputs_fd, output_files, f"{parent}/{xml_record['path']}",
        xml_record.get("bytes"), xml_record.get("sha256"), "safe-decode XML",
    )

    array_records = safe_receipt.get("arrays")
    _require(isinstance(array_records, list), "safe-decode array manifest is not an array")
    expected_output_files: set[str] = set()
    aggregate_bytes = xml_record["bytes"]
    for record in array_records:
        _require(isinstance(record, dict) and set(record) == SAFE_DECODE_ARRAY_FIELDS,
                 "safe-decode array entry fields are not exact")
        relative_array = _validate_relative_path(record.get("path"))
        _require(relative_array not in expected_output_files,
                 "safe-decode array manifest contains a duplicate output path")
        _require(isinstance(record.get("array_name"), str) and bool(record["array_name"])
                 and isinstance(record.get("type_code"), int) and not isinstance(record.get("type_code"), bool)
                 and isinstance(record.get("type_name"), str) and isinstance(record.get("dtype"), str)
                 and record.get("regular_file") is True
                 and isinstance(record.get("link_count"), int)
                 and not isinstance(record.get("link_count"), bool) and record["link_count"] == 1,
                 "safe-decode array is not a single-link regular file")
        _require(isinstance(record.get("bytes"), int) and not isinstance(record.get("bytes"), bool)
                 and record["bytes"] >= 0 and isinstance(record.get("count"), int)
                 and not isinstance(record.get("count"), bool) and record["count"] >= 0,
                 "safe-decode array size/count is invalid")
        _require(isinstance(record.get("sha256"), str)
                 and bool(SHA256_RE.fullmatch(record["sha256"])),
                 "safe-decode array SHA-256 is malformed")
        shape = record.get("shape")
        _require(isinstance(shape, list) and shape and all(isinstance(value, int)
                 and not isinstance(value, bool) and value >= 0 for value in shape),
                 "safe-decode array shape is malformed")
        expected_array_path = f"{output_prefix}/{relative_array}"
        _verify_bound_output(outputs_fd, output_files, expected_array_path,
                             record["bytes"], record.get("sha256"), "safe-decoded array")
        expected_output_files.add(expected_array_path)
        aggregate_bytes += record["bytes"]
    _require(isinstance(safe_receipt.get("array_file_count"), int)
             and not isinstance(safe_receipt.get("array_file_count"), bool)
             and safe_receipt["array_file_count"] == len(array_records)
             and isinstance(safe_receipt.get("total_output_bytes"), int)
             and not isinstance(safe_receipt.get("total_output_bytes"), bool)
             and safe_receipt["total_output_bytes"] == aggregate_bytes,
             "safe-decode receipt aggregate counts/bytes are inconsistent")
    actual_subtree_files = {path for path in output_files if path.startswith(output_prefix + "/")}
    _require(actual_subtree_files == expected_output_files,
             "safe-decode array receipt does not cover the exact decoded output file subtree")
    metadata_path, metadata_payload = _read_bound_output(
        outputs_fd, output_files, frame["metadata_binding_manifest_path"],
        frame["metadata_binding_manifest_bytes"], frame["metadata_binding_manifest_sha256"],
        "metadata-binding manifest",
    )
    metadata_document = _parse_json(metadata_payload, "metadata-binding manifest")
    _require(isinstance(metadata_document, dict)
             and _canonical_json(metadata_document) == metadata_payload,
             "metadata-binding manifest is not canonical JSON")
    records = _metadata_record_index(metadata_document)
    _require(metadata_document.get("input_sha256") == frame["raw_sha256"]
             and metadata_document.get("input_bytes") == frame["raw_bytes"],
             "metadata-binding manifest input differs from its C raw-frame binding")
    time_records = [record for (item_path, name), record in records.items()
                    if len(item_path) == 2 and item_path[0] == "JPartDataBi4" and name == "TimeStep"]
    time_record = time_records[0] if len(time_records) == 1 else None
    _require(time_record is not None and time_record.get("type_code") == 12
             and time_record.get("float_hex_components") == [frame["parser_observed_time_s_ieee754_hex"]],
             "D observed TimeStep differs from metadata-bound raw BI4 binary64 axis")
    mass_record = records.get((("JPartDataBi4",), "MassFluid"))
    _require(mass_record is not None and mass_record.get("type_code") == 12
             and len(mass_record.get("raw_value_bytes_hex", "")) == 16
             and len(mass_record.get("float_hex_components", [])) == 1,
             "metadata-binding manifest lacks the exact root MassFluid double")
    try:
        mass_value = float.fromhex(mass_record["float_hex_components"][0])
    except ValueError as error:
        raise BundleVerificationError("metadata-binding MassFluid binary64 hex is malformed") from error
    _require(math.isfinite(mass_value) and mass_value > 0.0,
             "metadata-binding MassFluid is not positive finite binary64")
    return safe_receipt, metadata_document


def verify_stage_bundle(
    bundle_root: Path | str,
    stage: str,
    *,
    trusted_authorization_bytes: bytes,
    trusted_authorization_sha256: str,
    expected_authorization_envelope: Mapping[str, Any],
    trusted_code_review_receipt_bytes: bytes | None = None,
    trusted_runtime_assumption: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify one stage's immutable bundle against caller-supplied trust inputs.

    ``trusted_authorization_bytes`` and ``expected_authorization_envelope`` must
    come from a caller-controlled trust store/signature check. This function
    checks byte/hash/envelope equality but deliberately does not authenticate
    the external authority itself. For D, ``trusted_code_review_receipt_bytes``
    must come from a caller-verified independent code-review record; this
    verifier checks its declared verdict, digest, and current source bytes but
    does not authenticate the independent reviewer or receipt. D additionally
    requires a caller assertion that the Python interpreter, import path, and
    already-loaded module objects are trusted; this function cannot attest that
    in-memory runtime state from source-file hashes alone.
    """
    _require(stage in STAGE_RECEIPT_SCHEMAS, "stage must be B, C, or D")
    _require(isinstance(trusted_authorization_bytes, bytes), "trusted authorization must be exact bytes")
    _require(bool(SHA256_RE.fullmatch(trusted_authorization_sha256)), "trusted authorization SHA-256 is malformed")
    _require(hashlib.sha256(trusted_authorization_bytes).hexdigest() == trusted_authorization_sha256,
             "caller-supplied trusted authorization bytes do not match its SHA-256")
    _require(isinstance(expected_authorization_envelope, Mapping)
             and set(expected_authorization_envelope) == AUTH_FIELDS,
             "caller-supplied trusted authorization envelope has unexpected/missing fields")

    root_fd, absolute_root = _open_absolute_directory(bundle_root)
    try:
        root_stat = os.fstat(root_fd)
        root_identity = (root_stat.st_dev, root_stat.st_ino)
        root_entries = set(_bounded_directory_names(root_fd, 5, "bundle root"))
        _require(root_entries == {"authorization.json", "one-shot-lock.json", "receipt.json", "manifests", "outputs"},
                 "bundle root entries are not exact")
        manifests_fd = _open_child_directory(root_fd, "manifests")
        outputs_fd = _open_child_directory(root_fd, "outputs")
        try:
            outputs_identity = (os.fstat(outputs_fd).st_dev, os.fstat(outputs_fd).st_ino)
            manifest_names = tuple(sorted(_bounded_directory_names(
                manifests_fd, len(STAGE_MANIFEST_NAMES[stage]), "bundle manifests directory",
            )))
            _require(manifest_names == tuple(sorted(STAGE_MANIFEST_NAMES[stage])),
                     "manifest directory entries are not exact for this stage")

            auth_obj, auth_bytes = _read_root_json(root_fd, "authorization.json", MAX_RECEIPT_BYTES)
            _require(auth_bytes == trusted_authorization_bytes, "bundle authorization differs from caller-trusted bytes")
            _require(_canonical_json(auth_obj) == auth_bytes, "authorization is not canonical JSON")
            _require(auth_obj == dict(expected_authorization_envelope),
                     "bundle authorization does not match caller-supplied exact envelope")
            _require(set(auth_obj) == AUTH_FIELDS, "authorization fields are not exact")
            _reject_forbidden_digest_keys(auth_obj)
            _require(auth_obj.get("stage") == stage and auth_obj.get("scope_id") == SCOPE_ID,
                     "authorization stage/scope mismatch")
            _require(auth_obj.get("exclusive_output_root") == absolute_root,
                     "authorization output root does not identify this bundle")
            _require(auth_obj.get("invocation_budget") == 1, "authorization invocation budget must be exactly one")
            _require(isinstance(auth_obj.get("argv"), list) and all(isinstance(item, str) for item in auth_obj["argv"]),
                     "authorization argv must be an exact string array")
            for key in ("executable_sha256", "wrapper_sha256"):
                _require(isinstance(auth_obj.get(key), str) and bool(SHA256_RE.fullmatch(auth_obj[key])),
                         f"authorization {key} is malformed")
            issued = _parse_utc(auth_obj.get("issued_at_utc"), "authorization issued_at_utc")
            expires = _parse_utc(auth_obj.get("expires_at_utc"), "authorization expires_at_utc")
            _require(issued < expires, "authorization validity interval is empty")

            lock, lock_bytes = _read_root_json(root_fd, "one-shot-lock.json", MAX_RECEIPT_BYTES)
            _require(_canonical_json(lock) == lock_bytes, "one-shot lock is not canonical JSON")
            _reject_forbidden_digest_keys(lock)
            _require(set(lock) == LOCK_FIELDS, "one-shot lock fields are not exact")
            _require(lock.get("schema") == "core.cfd.f8.r008_one_shot_lock.v1",
                     "unexpected one-shot lock schema")
            _require(lock.get("authority_sha256") == trusted_authorization_sha256,
                     "one-shot lock does not bind caller-trusted authorization")
            for key in ("stage", "scope_id", "case_id", "attempt_id", "nonce", "exclusive_output_root"):
                _require(lock.get(key) == auth_obj.get(key), f"one-shot lock {key} differs from authorization")
            _require(lock.get("exclusive_create_succeeded") is True, "one-shot lock was not exclusively created")
            lock_created = _parse_utc(lock.get("created_at_utc"), "one-shot lock created_at_utc")
            _require(issued <= lock_created < expires, "one-shot lock was not consumed within authority validity")

            receipt, receipt_bytes = _read_root_json(root_fd, "receipt.json", MAX_RECEIPT_BYTES)
            _require(receipt.get("schema") == STAGE_RECEIPT_SCHEMAS[stage], "unexpected stage receipt schema")
            _require(STAGE_REQUIRED_FIELDS[stage].issubset(receipt), "stage receipt is missing required fields")
            _require(receipt.get("scope_id") == SCOPE_ID, "stage receipt scope mismatch")
            for key in ("case_id", "attempt_id", "nonce"):
                _require(receipt.get(key) == auth_obj.get(key), f"stage receipt {key} differs from authorization")
            _require(receipt.get("status") in {"passed", "failed", "incomplete", "timeout", "oom", "signaled"},
                     "stage receipt status is outside the frozen enum")
            started = _parse_utc(receipt.get("started_at_utc"), "receipt started_at_utc")
            ended = _parse_utc(receipt.get("ended_at_utc"), "receipt ended_at_utc")
            _require(ended >= started, "stage receipt end precedes its start")
            if receipt["status"] == "passed":
                _require(ended <= expires, "successful stage completion exceeded the authorization expiry")
            _require(issued <= lock_created < started < expires,
                     "one-shot lock was not created strictly before stage start within authority validity")

            _binding_matches(receipt.get("authorization_binding"), "authorization.json", auth_bytes,
                             "authorization")
            _binding_matches(receipt.get("one_shot_lock_binding"), "one-shot-lock.json", lock_bytes,
                             "one-shot lock")

            manifest_binding_field, manifest_path, manifest_schema = STAGE_OUTPUT_MANIFESTS[stage]
            manifest_name = manifest_path.split("/")[-1]
            manifest, manifest_bytes = _read_manifest_file(manifests_fd, manifest_name)
            _binding_matches(receipt.get(manifest_binding_field), manifest_path, manifest_bytes,
                             "stage output manifest")
            output_files, output_directories = _validate_tree_manifest(
                outputs_fd, manifest, manifest_schema, stage,
            )

            extra_manifest_values: dict[str, Any] = {}
            decoded_frame_manifest: dict[str, Any] | None = None
            code_bindings_verified = False
            if stage == "B":
                for field in ("generated_xml_path", "initial_bi4_path"):
                    binding = receipt.get(field)
                    _require(isinstance(binding, dict) and set(binding) == {"path", "bytes", "sha256"},
                             f"B {field} binding fields are not exact")
                    bound_path = binding.get("path")
                    _require(isinstance(bound_path, str) and bound_path.startswith("outputs/"),
                             f"B {field} path must have the literal outputs/ prefix")
                    _require(isinstance(binding.get("bytes"), int)
                             and not isinstance(binding.get("bytes"), bool)
                             and binding["bytes"] >= 0
                             and isinstance(binding.get("sha256"), str)
                             and bool(SHA256_RE.fullmatch(binding["sha256"])),
                             f"B {field} byte/hash binding is malformed")
                    relative = _validate_relative_path(bound_path[len("outputs/"):])
                    _require(relative in output_files
                             and output_files[relative]["bytes"] == binding["bytes"]
                             and output_files[relative]["sha256"] == binding["sha256"],
                             f"B {field} does not match the closed output tree")
                metadata = receipt.get("metadata_binding")
                _require(isinstance(metadata, dict) and set(metadata) == {"manifest", "manifest_sha256"}
                         and isinstance(metadata.get("manifest"), dict),
                         "B metadata-binding fields are not exact")
                metadata_payload = _canonical_json(metadata["manifest"])
                _require(isinstance(metadata.get("manifest_sha256"), str)
                         and metadata["manifest_sha256"] == hashlib.sha256(metadata_payload).hexdigest(),
                         "B embedded metadata-binding manifest SHA-256 mismatch")
                b_initial = receipt["initial_bi4_path"]
                b_metadata = metadata["manifest"]
                _metadata_record_index(b_metadata)
                _require(b_metadata.get("input_sha256") == b_initial["sha256"]
                         and b_metadata.get("input_bytes") == b_initial["bytes"],
                         "B metadata-binding input differs from the initial BI4 binding")

            if stage == "C":
                case_row = _frozen_qualification_row(receipt["case_id"])
                axis = expected_time_axis_hex(case_row)
                frames = manifest.get("frames")
                _require(isinstance(frames, list) and len(frames) == len(axis),
                         "raw solver frame count differs from the frozen full native axis")
                _require(manifest.get("schema") == "core.cfd.f8.r008_raw_solver_manifest.v1",
                         "raw solver manifest schema mismatch")
                frame_paths: set[str] = set()
                for ordinal, (frame, expected_time) in enumerate(zip(frames, axis)):
                    _require(isinstance(frame, dict)
                             and set(frame) == {"ordinal", "expected_time_s_ieee754_hex", "path", "bytes", "sha256"},
                             "raw solver frame entry fields are not exact")
                    _require(isinstance(frame["ordinal"], int) and not isinstance(frame["ordinal"], bool)
                             and frame["ordinal"] == ordinal
                             and frame["expected_time_s_ieee754_hex"] == expected_time,
                             "raw solver frame ordinal/time differs from the frozen expected axis")
                    frame_path = _validate_relative_path(frame["path"])
                    _require(frame_path not in frame_paths, "duplicate raw solver frame path")
                    frame_paths.add(frame_path)
                    file_entry = next((item for item in manifest["files"] if item["path"] == frame_path), None)
                    _require(file_entry is not None and file_entry["bytes"] == frame["bytes"]
                             and file_entry["sha256"] == frame["sha256"],
                             "raw solver frame does not match its files-tree manifest entry")
                    _require(isinstance(frame["bytes"], int) and not isinstance(frame["bytes"], bool)
                             and frame["bytes"] > 0, "raw solver frame file is empty")
                extra_manifest_values["expected_frame_count"] = len(axis)

            if stage == "D":
                _verify_d_code_binding(
                    receipt.get("decoder_code_binding"), trusted_code_review_receipt_bytes,
                )
                _verify_runtime_assumption(trusted_runtime_assumption)
                code_bindings_verified = True
                frame_manifest, frame_manifest_bytes = _read_manifest_file(manifests_fd, "decoded-frame-manifest.json")
                decoded_frame_manifest = frame_manifest
                _binding_matches(receipt.get("decoded_frame_manifest_binding"),
                                 "manifests/decoded-frame-manifest.json", frame_manifest_bytes,
                                 "decoded-frame manifest")
                _require(set(frame_manifest) == MANIFEST_DOCUMENT_FIELDS["D_frames"],
                         "D decoded-frame manifest top-level fields are not exact")
                _reject_manifest_cycle_keys(frame_manifest, "D_frames")
                _require(frame_manifest.get("schema") == "core.cfd.f8.r008_decoded_frame_manifest.v1"
                         and frame_manifest.get("stage") == "D", "decoded-frame manifest schema/stage mismatch")
                _require(frame_manifest.get("case_id") == receipt["case_id"]
                         and frame_manifest.get("attempt_id") == receipt["attempt_id"],
                         "decoded-frame manifest case/attempt mismatch")
                frames = frame_manifest.get("frames")
                _require(isinstance(frames, list), "decoded-frame manifest frames must be an array")
                ordinals = [entry.get("ordinal") for entry in frames if isinstance(entry, dict)]
                _require(len(ordinals) == len(frames)
                         and all(isinstance(value, int) and not isinstance(value, bool) for value in ordinals)
                         and ordinals == list(range(len(frames))),
                         "decoded-frame manifest ordinals are not complete and ordered")
                case_row = _frozen_qualification_row(receipt["case_id"])
                expected_axis = expected_time_axis_hex(case_row)
                _require(len(frames) <= len(expected_axis), "decoded-frame manifest exceeds the frozen full axis")
                if receipt["status"] == "passed":
                    _require(len(frames) == len(expected_axis),
                             "passed D receipt does not contain the full frozen native frame axis")
                raw_manifest_sha = frame_manifest.get("raw_solver_manifest_sha256")
                _require(isinstance(raw_manifest_sha, str) and bool(SHA256_RE.fullmatch(raw_manifest_sha)),
                         "D frame manifest raw C-manifest SHA-256 is malformed")
                seen_artifact_paths: set[str] = set()
                for ordinal, frame in enumerate(frames):
                    _require(isinstance(frame, dict) and set(frame) == D_FRAME_FIELDS,
                             "decoded-frame entry fields are not exact")
                    _require(isinstance(frame["raw_solver_ordinal"], int)
                             and not isinstance(frame["raw_solver_ordinal"], bool)
                             and frame["ordinal"] == ordinal and frame["raw_solver_ordinal"] == ordinal,
                             "decoded-frame raw ordinal is not one-to-one")
                    _require(frame["expected_time_s_ieee754_hex"] == expected_axis[ordinal]
                             and frame["raw_solver_manifest_sha256"] == raw_manifest_sha,
                             "decoded-frame expected time or C-manifest binding changed")
                    _validate_relative_path(frame["raw_path"])
                    _require(isinstance(frame["raw_bytes"], int) and not isinstance(frame["raw_bytes"], bool)
                             and frame["raw_bytes"] > 0, "decoded-frame raw file byte count is invalid")
                    _require(isinstance(frame["raw_sha256"], str) and bool(SHA256_RE.fullmatch(frame["raw_sha256"])),
                             "decoded-frame raw file SHA-256 is malformed")
                    _require(frame["safe_decode_input_sha256"] == frame["raw_sha256"],
                             "decoded-frame safe-decode input hash differs from its raw hash")
                    for key in ("safe_decode_receipt_sha256", "metadata_binding_manifest_sha256"):
                        _require(isinstance(frame[key], str) and bool(SHA256_RE.fullmatch(frame[key])),
                                 f"decoded-frame {key} is malformed")
                    output_prefix = (
                        _validate_relative_path(frame["decoded_output_parent_relative_path"])
                        + "/" + frame["decoded_output_name"]
                    )
                    _validate_component(frame["decoded_output_name"])
                    artifact_paths = {
                        _validate_relative_path(frame["safe_decode_receipt_path"]),
                        _validate_relative_path(frame["metadata_binding_manifest_path"]),
                        output_prefix,
                    }
                    _require(not (seen_artifact_paths & artifact_paths),
                             "D frame artifact paths are reused across frames")
                    seen_artifact_paths.update(artifact_paths)
                    _check_d_frame_artifacts(outputs_fd, output_files, frame)
                    for key in ("expected_time_s_ieee754_hex", "parser_observed_time_s_ieee754_hex"):
                        value = frame[key]
                        _require(isinstance(value, str), f"decoded-frame {key} is not a string")
                        try:
                            number = float.fromhex(value)
                        except ValueError as error:
                            raise BundleVerificationError(f"decoded-frame {key} is invalid binary64 hex") from error
                        _require(math.isfinite(number) and number.hex() == value,
                                 f"decoded-frame {key} is non-finite or noncanonical")
                    observed = float.fromhex(frame["parser_observed_time_s_ieee754_hex"])
                    expected = float.fromhex(frame["expected_time_s_ieee754_hex"])
                    _require(not (observed == 0.0 and math.copysign(1.0, observed) < 0.0)
                             and struct.pack("<d", observed) == struct.pack("<d", expected),
                             "decoded-frame observed TimeStep differs from the expected binary64 axis")
                _require(receipt.get("frame_mappings") == frames,
                         "D receipt frame mappings do not exactly equal the detached decoded-frame manifest")
                output_manifest_binding = receipt.get("outputs_manifest_binding")
                _binding_matches(output_manifest_binding, "manifests/outputs-manifest.json",
                                 manifest_bytes,
                                 "D outputs manifest")
                table_binding = receipt.get("native_fluid_table_binding")
                _require(isinstance(table_binding, dict)
                         and set(table_binding) == {"path", "bytes", "sha256"}
                         and table_binding.get("path") == "outputs/native-fluid-frame-table-v2.h5",
                         "D native table binding path/fields mismatch")
                _require(any(item["path"] == "native-fluid-frame-table-v2.h5"
                             and item["bytes"] == table_binding["bytes"]
                             and item["sha256"] == table_binding["sha256"]
                             for item in manifest["files"]),
                         "D table receipt binding does not equal the detached outputs manifest")
                extra_manifest_values["decoded_frame_count"] = len(frames)

            case_row = _frozen_qualification_row(receipt["case_id"])
            return {
                "schema": SCHEMA,
                "stage": stage,
                "bundle_root": absolute_root,
                "case_id": receipt["case_id"],
                "attempt_id": receipt["attempt_id"],
                "status": receipt["status"],
                "receipt_sha256": hashlib.sha256(receipt_bytes).hexdigest(),
                "receipt_bytes": len(receipt_bytes),
                "receipt_path": f"{absolute_root}/receipt.json",
                "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                "files_verified": len(manifest["files"]),
                "directories_verified": len(manifest["directories"]),
                **extra_manifest_values,
                "case_is_frozen_qualification_only": case_row["qualification_only"] is True,
                "bundle_structure_closed": True,
                "authority_bytes_match_caller_trusted_binding": True,
                "authority_authenticity": "external_gate_not_checked_here",
                "lock_exclusive_creation_attestation": "executor_self_asserted_not_independently_proven",
                "native_integrity_evaluated": False,
                "metrics_evaluated": False,
                "readiness_pass": False,
                "qualification_credit": 0,
                "_receipt_document": receipt,
                "_receipt_bytes": receipt_bytes,
                "_authorization_bytes": auth_bytes,
                "_one_shot_lock_bytes": lock_bytes,
                "_manifest_document": manifest,
                "_decoded_frame_manifest_document": decoded_frame_manifest,
                "_output_file_manifest": output_files,
                "_output_directories": output_directories,
                "_root_identity": root_identity,
                "_outputs_identity": outputs_identity,
                "code_bindings_match_caller_trusted_review": code_bindings_verified,
                "loaded_module_code_identity_verified": False,
                "runtime_environment_assumption": (
                    "caller_attested_not_independently_verified" if stage == "D" else "not_applicable"
                ),
            }
        finally:
            os.close(manifests_fd)
            os.close(outputs_fd)
    finally:
        os.close(root_fd)


def _hash_fd_range(fd: int, offset: int, byte_count: int) -> str:
    digest = hashlib.sha256()
    remaining = byte_count
    position = offset
    while remaining:
        block = os.pread(fd, min(READ_CHUNK, remaining), position)
        _require(bool(block), "raw BI4 array range was truncated during provenance verification")
        digest.update(block)
        position += len(block)
        remaining -= len(block)
    return digest.hexdigest()


def _metadata_record(
    document: Mapping[str, Any], item_path: tuple[str, ...], name: str,
) -> Mapping[str, Any]:
    records = _metadata_record_index(document)
    value = records.get((item_path, name))
    _require(value is not None, f"required raw BI4 metadata record is absent: {'.'.join(item_path)}.{name}")
    return value


def _metadata_mass_bits(document: Mapping[str, Any]) -> str:
    record = _metadata_record(document, ("JPartDataBi4",), "MassFluid")
    _require(record.get("type_code") == 12 and len(record.get("raw_value_bytes_hex", "")) == 16,
             "raw BI4 MassFluid is not an exact little-endian binary64 value")
    try:
        value = float.fromhex(record["float_hex_components"][0])
    except (IndexError, TypeError, ValueError) as error:
        raise BundleVerificationError("raw BI4 MassFluid binary64 value is malformed") from error
    _require(math.isfinite(value) and value > 0.0,
             "raw BI4 MassFluid is not positive finite binary64")
    return record["raw_value_bytes_hex"]


def _require_native_arrays(scan: decoder.ScanResult, metadata_document: Mapping[str, Any]) -> None:
    records = _metadata_record_index(metadata_document)
    part_paths = {item_path for item_path, name in records if name == "TimeStep"}
    _require(len(part_paths) == 1 and len(next(iter(part_paths))) == 2,
             "raw BI4 must contain exactly one selected PART TimeStep")
    npok_record = records.get((next(iter(part_paths)), "Npok"))
    _require(npok_record is not None and npok_record.get("type_code") == 8
             and isinstance(npok_record.get("canonical_value"), int)
             and not isinstance(npok_record.get("canonical_value"), bool)
             and npok_record["canonical_value"] > 0,
             "raw BI4 PART Npok is not a positive uint32")
    npok = npok_record["canonical_value"]
    case_np = records.get((("JPartDataBi4",), "CaseNp"))
    _require(case_np is not None and case_np.get("type_code") == 10
             and case_np.get("canonical_value") == npok,
             "raw BI4 CaseNp differs from PART Npok")
    by_name: dict[str, list[decoder.ArrayRecord]] = {}
    for array in scan.arrays:
        by_name.setdefault(array.name, []).append(array)
    _require(all(len(by_name.get(name, [])) == 1 for name in ("Idp", "Vel", "Rhop")),
             "raw BI4 lacks a unique required Idp/Vel/Rhop array")
    _require((len(by_name.get("Pos", [])), len(by_name.get("Posd", []))) in {(1, 0), (0, 1)},
             "raw BI4 must contain exactly one Pos or Posd array")
    required = [by_name[name][0] for name in ("Idp", "Vel", "Rhop")]
    required.append(by_name["Pos"][0] if "Pos" in by_name else by_name["Posd"][0])
    _require(all(array.count == npok for array in required),
             "raw BI4 required array counts differ from PART Npok")
    _require(by_name["Idp"][0].type_code == 8 and by_name["Vel"][0].type_code == 22
             and by_name["Rhop"][0].type_code == 11
             and (("Pos" in by_name and by_name["Pos"][0].type_code == 22)
                  or ("Posd" in by_name and by_name["Posd"][0].type_code == 23)),
             "raw BI4 required arrays have unexpected native element types")


def _verify_safe_decode_against_scan(
    raw_fd: int,
    scan: decoder.ScanResult,
    safe_receipt: Mapping[str, Any],
    frame: Mapping[str, Any],
    d_outputs_fd: int,
    d_output_files: Mapping[str, Mapping[str, Any]],
    d_output_directories: list[str],
) -> None:
    parent = frame["decoded_output_parent_relative_path"]
    output_name = frame["decoded_output_name"]
    output_prefix = f"{parent}/{output_name}"
    expected_arrays: list[dict[str, Any]] = []
    expected_array_files: set[str] = set()
    for array in scan.arrays:
        type_name, dtype, _element_bytes, triple = decoder.TYPE_INFO[array.type_code]
        digest = _hash_fd_range(raw_fd, array.offset, array.byte_count)
        relative_array = "/".join(array.item_path[1:] + (f"{array.name}.bin",))
        output_path = f"{output_prefix}/{relative_array}"
        expected_arrays.append({
            "path": relative_array,
            "array_name": array.name,
            "type_code": array.type_code,
            "type_name": type_name,
            "dtype": dtype,
            "shape": [array.count, 3] if triple else [array.count],
            "count": array.count,
            "bytes": array.byte_count,
            "sha256": digest,
            "regular_file": True,
            "link_count": 1,
        })
        expected_array_files.add(output_path)
        _verify_bound_output(d_outputs_fd, d_output_files, output_path,
                             array.byte_count, digest, "raw-to-decoded array")

    xml_bytes = decoder._xml_document(scan)
    xml_digest = hashlib.sha256(xml_bytes).hexdigest()
    xml_path = f"{parent}/{output_name}.xml"
    _verify_bound_output(d_outputs_fd, d_output_files, xml_path,
                         len(xml_bytes), xml_digest, "raw-to-decoded XML")
    _require(safe_receipt.get("xml") == {
        "path": f"{output_name}.xml", "bytes": len(xml_bytes), "sha256": xml_digest,
        "regular_file": True, "link_count": 1,
    }, "safe-decode receipt XML differs from deterministic BI4 XML materialization")
    _require(safe_receipt.get("arrays") == expected_arrays,
             "safe-decode receipt arrays differ from the bounded raw BI4 scan")
    actual_array_files = {path for path in d_output_files if path.startswith(output_prefix + "/")}
    _require(actual_array_files == expected_array_files,
             "decoded array files do not exactly cover the bounded raw BI4 arrays")

    expected_directories = {output_prefix}

    def add_child_directories(item: decoder.ItemRecord, parts: tuple[str, ...]) -> None:
        for child in item.children:
            child_parts = parts + (child.name,)
            expected_directories.add("/".join((output_prefix, *child_parts)))
            add_child_directories(child, child_parts)

    add_child_directories(scan.root, ())
    actual_directories = {path for path in d_output_directories
                          if path == output_prefix or path.startswith(output_prefix + "/")}
    _require(actual_directories == expected_directories,
             "decoded output directories do not exactly cover the bounded raw BI4 item tree")
    _require(safe_receipt.get("total_output_bytes") == len(xml_bytes)
             + sum(array.byte_count for array in scan.arrays),
             "safe-decode receipt total bytes differ from its raw BI4 materialization")


def _open_verified_outputs(stage_result: Mapping[str, Any]) -> tuple[int, int]:
    root_fd, _absolute = _open_absolute_directory(stage_result["bundle_root"])
    root_stat = os.fstat(root_fd)
    if (root_stat.st_dev, root_stat.st_ino) != stage_result["_root_identity"]:
        os.close(root_fd)
        raise BundleVerificationError("stage bundle root changed after its structural verification")
    try:
        outputs_fd = _open_child_directory(root_fd, "outputs")
    except BaseException:
        os.close(root_fd)
        raise
    outputs_stat = os.fstat(outputs_fd)
    if (outputs_stat.st_dev, outputs_stat.st_ino) != stage_result["_outputs_identity"]:
        os.close(outputs_fd)
        os.close(root_fd)
        raise BundleVerificationError("stage outputs directory changed after structural verification")
    return root_fd, outputs_fd


def verify_provenance_chain(
    bundle_roots: Mapping[str, Path | str],
    *,
    trusted_authorization_bytes: Mapping[str, bytes],
    trusted_authorization_sha256: Mapping[str, str],
    expected_authorization_envelopes: Mapping[str, Mapping[str, Any]],
    trusted_code_review_receipt_bytes: bytes,
    trusted_runtime_assumption: Mapping[str, Any],
) -> dict[str, Any]:
    """Verify B→C→D receipt/manifest references without elevating qualification.

    Each bundle is independently closed first. The chain then binds the B
    receipt into C, the C receipt into D, and pairs each D-decoded frame with
    the corresponding raw C output and frozen/observed binary64 time.
    """
    stages = {"B", "C", "D"}
    _require(set(bundle_roots) == stages, "provenance chain requires exactly B, C, and D bundles")
    _require(set(trusted_authorization_bytes) == stages
             and set(trusted_authorization_sha256) == stages
             and set(expected_authorization_envelopes) == stages,
             "provenance chain requires one caller-trusted authority per stage")
    checked = {
        stage: verify_stage_bundle(
            bundle_roots[stage], stage,
            trusted_authorization_bytes=trusted_authorization_bytes[stage],
            trusted_authorization_sha256=trusted_authorization_sha256[stage],
            expected_authorization_envelope=expected_authorization_envelopes[stage],
            trusted_code_review_receipt_bytes=(
                trusted_code_review_receipt_bytes if stage == "D" else None
            ),
            trusted_runtime_assumption=(
                trusted_runtime_assumption if stage == "D" else None
            ),
        )
        for stage in ("B", "C", "D")
    }
    b_receipt = checked["B"]["_receipt_document"]
    c_receipt = checked["C"]["_receipt_document"]
    d_receipt = checked["D"]["_receipt_document"]
    c_manifest = checked["C"]["_manifest_document"]
    d_manifest = checked["D"]["_decoded_frame_manifest_document"]
    _require(d_manifest is not None, "D decoded-frame manifest was not verified")
    case_ids = {checked[stage]["case_id"] for stage in ("B", "C", "D")}
    _require(len(case_ids) == 1, "B/C/D case identities differ")
    case_id = next(iter(case_ids))
    _frozen_qualification_row(case_id)
    b_root_fd, b_outputs_fd = _open_verified_outputs(checked["B"])
    c_root_fd, c_outputs_fd = _open_verified_outputs(checked["C"])
    d_root_fd, d_outputs_fd = _open_verified_outputs(checked["D"])
    try:
        root_fds = {"B": b_root_fd, "C": c_root_fd, "D": d_root_fd}
        for stage, root_fd in root_fds.items():
            stage_result = checked[stage]
            _require(_stable_read_beneath(root_fd, "authorization.json", MAX_RECEIPT_BYTES)
                     == stage_result["_authorization_bytes"],
                     f"{stage} authorization changed after structural verification")
            _require(_stable_read_beneath(root_fd, "one-shot-lock.json", MAX_RECEIPT_BYTES)
                     == stage_result["_one_shot_lock_bytes"],
                     f"{stage} one-shot lock changed after structural verification")
            _require(_stable_read_beneath(root_fd, "receipt.json", MAX_RECEIPT_BYTES)
                     == stage_result["_receipt_bytes"],
                     f"{stage} receipt changed after structural verification")
        for stage, root_fd, manifest_name in (
            ("B", b_root_fd, "materialization-output-manifest.json"),
            ("C", c_root_fd, "raw-solver-manifest.json"),
            ("D", d_root_fd, "outputs-manifest.json"),
        ):
            payload = _stable_read_beneath(root_fd, f"manifests/{manifest_name}", MAX_RECEIPT_BYTES)
            _require(hashlib.sha256(payload).hexdigest() == checked[stage]["manifest_sha256"]
                     and _parse_json(payload, f"reopened {stage} manifest")
                     == checked[stage]["_manifest_document"],
                     f"{stage} detached manifest changed after structural verification")
        d_frame_payload = _stable_read_beneath(
            d_root_fd, "manifests/decoded-frame-manifest.json", MAX_RECEIPT_BYTES,
        )
        _require(_canonical_json(d_manifest) == d_frame_payload,
                 "D decoded-frame manifest changed after structural verification")

        _binding_matches(
            c_receipt.get("materialization_receipt_binding"),
            checked["B"]["receipt_path"], checked["B"]["_receipt_bytes"],
            "C→B materialization receipt",
        )
        _binding_matches(
            d_receipt.get("solver_receipt_binding"),
            checked["C"]["receipt_path"], checked["C"]["_receipt_bytes"],
            "D→C solver receipt",
        )
        raw_manifest_sha = checked["C"]["manifest_sha256"]
        raw_manifest_bytes = _stable_read_beneath(c_root_fd, "manifests/raw-solver-manifest.json",
                                                   MAX_RECEIPT_BYTES)
        _require(hashlib.sha256(raw_manifest_bytes).hexdigest() == raw_manifest_sha
                 and _parse_json(raw_manifest_bytes, "reopened C raw solver manifest") == c_manifest
                 and _canonical_json(c_manifest) == raw_manifest_bytes,
                 "C raw solver manifest changed after structural verification")
        _require(d_manifest.get("raw_solver_manifest_sha256") == raw_manifest_sha,
                 "D frame manifest does not bind the exact detached C raw solver manifest")
        c_frames = c_manifest.get("frames")
        d_frames = d_manifest.get("frames")
        _require(isinstance(c_frames, list) and isinstance(d_frames, list)
                 and len(c_frames) == len(d_frames), "C/D frame counts differ")

        b_initial = b_receipt.get("initial_bi4_path")
        b_metadata_binding = b_receipt.get("metadata_binding")
        _require(isinstance(b_initial, dict) and isinstance(b_metadata_binding, dict),
                 "B initial BI4 or metadata binding is absent")
        b_relative = _validate_relative_path(b_initial["path"][len("outputs/"):])
        _verify_bound_output(b_outputs_fd, checked["B"]["_output_file_manifest"], b_relative,
                             b_initial["bytes"], b_initial["sha256"], "B initial BI4")
        b_generated = b_receipt["generated_xml_path"]
        _verify_bound_output(
            b_outputs_fd, checked["B"]["_output_file_manifest"],
            b_generated["path"][len("outputs/"):], b_generated["bytes"],
            b_generated["sha256"], "B generated XML",
        )
        b_raw_fd = decoder.open_regular_beneath(b_outputs_fd, b_relative)
        try:
            b_metadata_result = metadata_binding.bind_metadata_fd(b_raw_fd, b_initial["sha256"])
            _require(b_metadata_result["manifest"] == b_metadata_binding["manifest"]
                     and b_metadata_result["manifest_sha256"] == b_metadata_binding["manifest_sha256"],
                     "B embedded metadata manifest does not recompute from the bound initial BI4")
            _require(b_metadata_result["scan"].input_bytes == b_initial["bytes"],
                     "B initial BI4 byte count differs from its exact input")
            _require_native_arrays(b_metadata_result["scan"], b_metadata_result["manifest"])
            initial_mass_bits = _metadata_mass_bits(b_metadata_result["manifest"])
        finally:
            os.close(b_raw_fd)

        recomputed_mass_bits: set[str] = set()
        for ordinal, (raw_frame, decoded_frame) in enumerate(zip(c_frames, d_frames)):
            _require(isinstance(decoded_frame, dict) and set(decoded_frame) == D_FRAME_FIELDS,
                     "decoded-frame manifest entry fields are not exact")
            for key, value in (("ordinal", ordinal), ("raw_solver_ordinal", ordinal)):
                _require(isinstance(decoded_frame[key], int) and not isinstance(decoded_frame[key], bool)
                         and decoded_frame[key] == value, "C/D frame ordinal mapping is not one-to-one")
            _require(raw_frame.get("ordinal") == ordinal, "C raw frame ordinal is not ordered")
            _require(decoded_frame["raw_solver_manifest_sha256"] == raw_manifest_sha,
                     "decoded frame references the wrong C raw manifest")
            _require(decoded_frame["expected_time_s_ieee754_hex"] == raw_frame["expected_time_s_ieee754_hex"],
                     "D expected time differs from the C frozen expected axis")
            for decoded_key, raw_key in (("raw_path", "path"), ("raw_bytes", "bytes"), ("raw_sha256", "sha256")):
                _require(decoded_frame[decoded_key] == raw_frame[raw_key],
                         f"decoded frame raw binding differs from C manifest field {raw_key}")
            _require(decoded_frame["safe_decode_input_sha256"] == raw_frame["sha256"],
                     "safe decoder input hash differs from C raw frame hash")

            raw_fd = decoder.open_regular_beneath(c_outputs_fd, raw_frame["path"])
            try:
                metadata_result = metadata_binding.bind_metadata_fd(raw_fd, raw_frame["sha256"])
                scan = metadata_result["scan"]
                _require(scan.input_bytes == raw_frame["bytes"],
                         "C raw frame byte count differs from its parsed input")
                _require_native_arrays(scan, metadata_result["manifest"])
                metadata_relative, metadata_payload = _read_bound_output(
                    d_outputs_fd, checked["D"]["_output_file_manifest"],
                    decoded_frame["metadata_binding_manifest_path"],
                    decoded_frame["metadata_binding_manifest_bytes"],
                    decoded_frame["metadata_binding_manifest_sha256"],
                    "D metadata-binding manifest",
                )
                _require(metadata_payload == metadata_result["manifest_bytes"],
                         "D metadata-binding artifact does not exactly recompute from its C raw BI4")
                raw_part_path = ("JPartDataBi4", scan.root.children[0].name)
                time_record = _metadata_record(metadata_result["manifest"], raw_part_path, "TimeStep")
                observed_components = time_record.get("float_hex_components")
                _require(time_record.get("type_code") == 12 and isinstance(observed_components, list)
                         and len(observed_components) == 1
                         and decoded_frame["parser_observed_time_s_ieee754_hex"] == observed_components[0],
                         "D observed TimeStep does not recompute from raw BI4 metadata")
                mass_bits = _metadata_mass_bits(metadata_result["manifest"])
                _require(mass_bits == initial_mass_bits,
                         "D frame MassFluid binary64 differs from the exact B initial reference")
                recomputed_mass_bits.add(mass_bits)

                expected_hex = raw_frame["expected_time_s_ieee754_hex"]
                observed_hex = decoded_frame["parser_observed_time_s_ieee754_hex"]
                try:
                    expected = float.fromhex(expected_hex)
                    observed = float.fromhex(observed_hex)
                except ValueError as error:
                    raise BundleVerificationError("C/D time value is not valid binary64 hexadecimal") from error
                _require(math.isfinite(expected) and expected.hex() == expected_hex,
                         "C expected time is non-finite or noncanonical")
                _require(math.isfinite(observed) and observed.hex() == observed_hex,
                         "D observed time is non-finite or noncanonical")
                _require(not (observed == 0.0 and math.copysign(1.0, observed) < 0.0),
                         "D observed time uses negative zero")
                _require(struct.pack("<d", observed) == struct.pack("<d", expected),
                         "D observed TimeStep bits differ from the frozen expected cadence")

                safe_relative, safe_payload = _read_bound_output(
                    d_outputs_fd, checked["D"]["_output_file_manifest"],
                    decoded_frame["safe_decode_receipt_path"],
                    decoded_frame["safe_decode_receipt_bytes"],
                    decoded_frame["safe_decode_receipt_sha256"], "D safe-decode receipt",
                )
                safe_receipt = _parse_json(safe_payload, "reopened D safe-decode receipt")
                _verify_safe_decode_against_scan(
                    raw_fd, scan, safe_receipt, decoded_frame, d_outputs_fd,
                    checked["D"]["_output_file_manifest"], checked["D"]["_output_directories"],
                )
                raw_stat = os.fstat(raw_fd)
                _require(_identity(raw_stat) == scan.input_identity
                         and decoder._hash_fd(raw_fd, scan.input_bytes) == raw_frame["sha256"],
                         "C raw BI4 changed during D metadata/array verification")
            finally:
                os.close(raw_fd)

        _require(recomputed_mass_bits == {initial_mass_bits},
                 "B/C/D MassFluid provenance is not a single exact binary64 value")
        table_binding = d_receipt["native_fluid_table_binding"]
        _verify_bound_output(
            d_outputs_fd, checked["D"]["_output_file_manifest"],
            table_binding["path"][len("outputs/"):], table_binding["bytes"],
            table_binding["sha256"], "D native fluid table",
        )
        _require(d_receipt.get("frame_mappings") == d_frames,
                 "D receipt frame mappings do not exactly equal the detached decoded-frame manifest")
    finally:
        for descriptor in (b_outputs_fd, b_root_fd, c_outputs_fd, c_root_fd, d_outputs_fd, d_root_fd):
            os.close(descriptor)
    statuses = {stage: checked[stage]["status"] for stage in ("B", "C", "D")}
    return {
        "schema": SCHEMA,
        "scope_id": SCOPE_ID,
        "case_id": case_id,
        "stage_statuses": statuses,
        "receipt_sha256": {stage: checked[stage]["receipt_sha256"] for stage in ("B", "C", "D")},
        "manifest_sha256": {stage: checked[stage]["manifest_sha256"] for stage in ("B", "C", "D")},
        "frames_paired": len(c_frames),
        "provenance_chain_references_closed": True,
        "safe_decode_receipts_and_metadata_artifacts_rehashed": True,
        "raw_metadata_and_decoded_arrays_recomputed": True,
        "massfluid_matches_B_initial_binary64": True,
        "code_bindings_match_caller_trusted_independent_review": True,
        "loaded_module_code_identity_verified": False,
        "runtime_environment_assumption": "caller_attested_not_independently_verified",
        "all_stages_passed": all(status == "passed" for status in statuses.values()),
        "authority_authenticity": "external_gate_not_checked_here",
        "code_review_authenticity": "caller_supplied_trust_not_authenticated_here",
        "lock_exclusive_creation_attestation": "executor_self_asserted_not_independently_proven",
        "native_integrity_evaluated": False,
        "metrics_evaluated": False,
        "readiness_pass": False,
        "qualification_credit": 0,
    }


__all__ = [
    "BundleVerificationError", "SCHEMA", "expected_time_axis_hex",
    "verify_provenance_chain", "verify_stage_bundle",
]
