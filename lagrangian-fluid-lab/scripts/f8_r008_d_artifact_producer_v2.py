"""Bounded additive synthetic D-stage artifact producer for F8 R008 v2.

The caller prepares a fresh, exclusively-created D root containing only its
trusted ``authorization.json``, ``one-shot-lock.json``, ``manifests/``, and
``outputs/``.  This module never creates or consumes an authorization or lock;
it treats the exact caller-supplied trust inputs as an external gate.  It adds
the successful D artifacts once, without replacement, and leaves a failed
target incomplete for the caller to preserve as terminal evidence.

This is a Python-only provenance/materialization operation.  It never invokes
GenCase, a native decoder, a solver, worker, GPU, or queue, and it grants no
readiness, numerical, or qualification credit.
"""
from __future__ import annotations

import ctypes
import hashlib
import math
import os
from pathlib import Path
import secrets
import stat
import struct
from typing import Any, Iterable, Mapping

from scripts import f8_r008_native_fluid_table_bundle_verifier_v1 as table_chain
from scripts import f8_r008_native_fluid_table_producer_v2 as table_producer
from scripts import f8_r008_native_fluid_table_v2 as table_v2
from scripts import f8_r008_per_case_bundle_verifier_v1 as bundle
from scripts import f8_r008_safe_bi4_decoder_v1 as decoder
from scripts import f8_r008_safe_bi4_metadata_binding_v1 as metadata_binding


SCHEMA = "core.cfd.f8.r008_d_artifact_producer.v2"
DECODE_RECEIPTS_DIR = "decode-receipts"
METADATA_BINDINGS_DIR = "metadata-bindings"
DECODED_DIR = "decoded"
DECODED_FRAME_MANIFEST = "decoded-frame-manifest.json"
OUTPUTS_MANIFEST = "outputs-manifest.json"
TABLE_RELATIVE = "native-fluid-frame-table-v2.h5"


class DArtifactProducerError(ValueError):
    """The caller context, source bundle, or fresh D target is unsafe."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DArtifactProducerError(message)


def _canonical_json(value: Any) -> bytes:
    try:
        return bundle._canonical_json(value)
    except bundle.BundleVerificationError as error:
        raise DArtifactProducerError("artifact is not canonically serializable") from error


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _binding(path: str, payload: bytes) -> dict[str, Any]:
    return {"path": path, "bytes": len(payload), "sha256": _sha256(payload)}


def _open_new_directory(parent_fd: int, name: str, mode: int) -> int:
    bundle._validate_component(name)
    os.mkdir(name, mode=mode, dir_fd=parent_fd)
    return os.open(
        name,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
        dir_fd=parent_fd,
    )


def _write_new_file(parent_fd: int, name: str, payload: bytes, *, mode: int = 0o600) -> None:
    """Write one canonical artifact once; never replace or remove it."""
    bundle._validate_component(name)
    fd = os.open(
        name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
        mode,
        dir_fd=parent_fd,
    )
    try:
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("short write while creating D artifact")
            view = view[written:]
        os.fsync(fd)
        current = os.fstat(fd)
        _require(stat.S_ISREG(current.st_mode) and current.st_nlink == 1
                 and current.st_size == len(payload),
                 f"new D artifact is not a closed single-link regular file: {name}")
    finally:
        os.close(fd)
    os.fsync(parent_fd)


def _require_current_user_nonshared_regular(stat_result: os.stat_result, label: str) -> None:
    _require(stat.S_ISREG(stat_result.st_mode) and stat_result.st_nlink == 1
             and stat_result.st_uid == os.geteuid()
             and not (stat_result.st_mode & (stat.S_IWGRP | stat.S_IWOTH)),
             f"{label} must be a current-user-owned single-link regular file that is not group/world-writable")


def _read_current_user_nonshared_json(root_fd: int, name: str, label: str) -> tuple[dict[str, Any], bytes]:
    payload, stat_result = bundle._stable_read_file_at(root_fd, name, bundle.MAX_RECEIPT_BYTES)
    _require_current_user_nonshared_regular(stat_result, label)
    document = bundle._parse_json(payload, label)
    _require(isinstance(document, dict), f"{label} must be a JSON object")
    return document, payload


def _require_current_user_nonshared_directory(stat_result: os.stat_result, label: str) -> None:
    _require(stat.S_ISDIR(stat_result.st_mode) and stat_result.st_uid == os.geteuid()
             and not (stat_result.st_mode & (stat.S_IWGRP | stat.S_IWOTH)),
             f"{label} must be a current-user-owned directory that is not group/world-writable")


def _open_directory_beneath(root_fd: int, relative: str) -> int:
    parts = bundle._validate_relative_path(relative)
    current_fd = os.dup(root_fd)
    try:
        for component in parts.split("/"):
            child_fd = bundle._open_child_directory(current_fd, component)
            os.close(current_fd)
            current_fd = child_fd
        return current_fd
    except BaseException:
        _close_quietly(current_fd)
        raise


def _verify_output_tree_permissions(
    outputs_fd: int,
    output_files: Mapping[str, Mapping[str, Any]],
    output_directories: Iterable[str],
) -> None:
    """Require every D output file/directory to remain owner-controlled."""
    for relative in output_directories:
        directory_fd = _open_directory_beneath(outputs_fd, relative)
        try:
            _require_current_user_nonshared_directory(os.fstat(directory_fd), f"D output directory {relative}")
        finally:
            os.close(directory_fd)

    for relative in output_files:
        parts = bundle._validate_relative_path(relative).split("/")
        parent_fd = os.dup(outputs_fd)
        try:
            for component in parts[:-1]:
                child_fd = bundle._open_child_directory(parent_fd, component)
                os.close(parent_fd)
                parent_fd = child_fd
            name = parts[-1]
            before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            file_fd = os.open(
                name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NONBLOCK", 0), dir_fd=parent_fd,
            )
            try:
                opened = os.fstat(file_fd)
                _require_current_user_nonshared_regular(opened, f"D output file {relative}")
                after = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                _require((before.st_dev, before.st_ino) == (opened.st_dev, opened.st_ino)
                         == (after.st_dev, after.st_ino),
                         f"D output file changed during permission verification: {relative}")
            finally:
                os.close(file_fd)
        finally:
            os.close(parent_fd)


def _validate_v1_d_authorization_and_lock(
    auth: Mapping[str, Any], lock: Mapping[str, Any], *, trusted_authorization_sha256: str,
    absolute_root: str,
) -> None:
    """Apply every v1 D-prelude rule that does not require receipt.json."""
    bundle._reject_forbidden_digest_keys(auth)
    _require(set(auth) == bundle.AUTH_FIELDS and auth.get("stage") == "D"
             and auth.get("scope_id") == bundle.SCOPE_ID
             and auth.get("exclusive_output_root") == absolute_root
             and auth.get("invocation_budget") == 1
             and isinstance(auth.get("argv"), list)
             and all(isinstance(item, str) for item in auth["argv"]),
             "D authorization does not satisfy the exact v1 prelude contract")
    for key in ("executable_sha256", "wrapper_sha256"):
        _require(isinstance(auth.get(key), str) and bool(bundle.SHA256_RE.fullmatch(auth[key])),
                 f"D authorization {key} is malformed")
    issued = bundle._parse_utc(auth.get("issued_at_utc"), "D authorization issued_at_utc")
    expires = bundle._parse_utc(auth.get("expires_at_utc"), "D authorization expires_at_utc")
    _require(issued < expires, "D authorization validity interval is empty")

    bundle._reject_forbidden_digest_keys(lock)
    _require(set(lock) == bundle.LOCK_FIELDS
             and lock.get("schema") == "core.cfd.f8.r008_one_shot_lock.v1"
             and lock.get("authority_sha256") == trusted_authorization_sha256
             and all(lock.get(key) == auth.get(key) for key in
                     ("stage", "scope_id", "case_id", "attempt_id", "nonce", "exclusive_output_root"))
             and lock.get("exclusive_create_succeeded") is True,
             "D one-shot lock does not satisfy the exact v1 prelude contract")
    created = bundle._parse_utc(lock.get("created_at_utc"), "D one-shot lock created_at_utc")
    _require(issued <= created < expires,
             "D one-shot lock was not created within the authorization validity interval")


def _rename_noreplace_at(directory_fd: int, source: str, destination: str) -> None:
    """Atomically rename two children of one directory without replacement."""
    bundle._validate_component(source)
    bundle._validate_component(destination)
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise DArtifactProducerError("atomic no-replace renameat2 is unavailable on this platform")
    renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    renameat2.restype = ctypes.c_int
    result = renameat2(
        directory_fd, os.fsencode(source), directory_fd, os.fsencode(destination), 1,  # RENAME_NOREPLACE
    )
    if result != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number), destination)


def _publish_passed_receipt(root_fd: int, payload: bytes) -> dict[str, bool]:
    """Atomically publish a complete, fsynced commit record exactly once.

    The final basename is absent until a complete temporary file has been
    written and fsynced. The no-replace rename is the one-shot commit point.
    Pre-commit failures leave no ``receipt.json``; post-commit parent-sync and
    close outcomes are returned as flags instead of raising after publication.
    """
    temporary_name = f"receipt-pending-{secrets.token_hex(16)}"
    fd = os.open(
        temporary_name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
        0o600,
        dir_fd=root_fd,
    )
    file_close_succeeded = True
    try:
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("short write while preparing passed D receipt")
            view = view[written:]
        os.fsync(fd)
        current = os.fstat(fd)
        _require_current_user_nonshared_regular(current, "prepared D receipt")
        _require(current.st_size == len(payload), "prepared D receipt size differs from its canonical payload")
    finally:
        try:
            os.close(fd)
        except OSError:
            file_close_succeeded = False

    # Persist the completed temporary directory entry before atomically moving
    # it to the frozen receipt basename. A failure here is still pre-commit.
    os.fsync(root_fd)
    _rename_noreplace_at(root_fd, temporary_name, "receipt.json")
    try:
        os.fsync(root_fd)
        parent_fsync_succeeded = True
    except OSError:
        parent_fsync_succeeded = False
    return {
        "receipt_file_close_succeeded": file_close_succeeded,
        "receipt_parent_directory_fsync_succeeded": parent_fsync_succeeded,
    }


def _close_quietly(fd: int) -> None:
    try:
        os.close(fd)
    except OSError:
        pass


def _read_target_prelude(
    d_root: Path | str,
    *,
    trusted_authorization_bytes: bytes,
    trusted_authorization_sha256: str,
    expected_authorization_envelope: Mapping[str, Any],
) -> tuple[int, int, int, dict[str, Any], bytes, bytes]:
    """Open an untouched caller-prepared D target and validate its prelude.

    This deliberately validates only the pre-receipt state. The established D
    verifier requires receipt.json and therefore is not invoked here; callers
    must run its final bundle/provenance pass after this producer publishes.
    """
    _require(isinstance(trusted_authorization_bytes, bytes), "D trusted authorization must be exact bytes")
    _require(isinstance(trusted_authorization_sha256, str)
             and _sha256(trusted_authorization_bytes) == trusted_authorization_sha256,
             "D trusted authorization SHA-256 does not match its exact bytes")
    _require(isinstance(expected_authorization_envelope, Mapping)
             and set(expected_authorization_envelope) == bundle.AUTH_FIELDS,
             "D caller authorization envelope fields are not exact")
    root_fd, absolute = bundle._open_absolute_directory(d_root)
    try:
        root_stat = os.fstat(root_fd)
        _require(stat.S_ISDIR(root_stat.st_mode) and root_stat.st_uid == os.geteuid()
                 and not (root_stat.st_mode & (stat.S_IWGRP | stat.S_IWOTH)),
                 "D bundle root must be current-user-owned and not group/world-writable")
        _require(set(bundle._bounded_directory_names(root_fd, 4, "fresh D bundle root"))
                 == {"authorization.json", "one-shot-lock.json", "manifests", "outputs"},
                 "D target is not an untouched caller-prepared one-shot root")
        manifests_fd = bundle._open_child_directory(root_fd, "manifests")
        outputs_fd = bundle._open_child_directory(root_fd, "outputs")
        try:
            for label, fd in (("manifests", manifests_fd), ("outputs", outputs_fd)):
                directory_stat = os.fstat(fd)
                _require(stat.S_ISDIR(directory_stat.st_mode)
                         and directory_stat.st_uid == os.geteuid()
                         and not (directory_stat.st_mode & (stat.S_IWGRP | stat.S_IWOTH)),
                         f"D {label} directory must be current-user-owned and not group/world-writable")
            _require(not bundle._bounded_directory_names(manifests_fd, 1, "fresh D manifests"),
                     "D target manifests directory is not empty")
            _require(not bundle._bounded_directory_names(outputs_fd, 1, "fresh D outputs"),
                     "D target outputs directory is not empty")
            auth, auth_bytes = _read_current_user_nonshared_json(root_fd, "authorization.json", "D authorization")
            _require(auth_bytes == trusted_authorization_bytes and _canonical_json(auth) == auth_bytes
                     and auth == dict(expected_authorization_envelope)
                     and set(auth) == bundle.AUTH_FIELDS and auth.get("stage") == "D"
                     and auth.get("scope_id") == bundle.SCOPE_ID
                     and auth.get("exclusive_output_root") == absolute,
                     "D target authorization differs from caller-supplied exact trust input")
            lock, lock_bytes = _read_current_user_nonshared_json(root_fd, "one-shot-lock.json", "D one-shot lock")
            _require(_canonical_json(lock) == lock_bytes,
                     "D one-shot lock is not canonical JSON")
            _validate_v1_d_authorization_and_lock(
                auth, lock, trusted_authorization_sha256=trusted_authorization_sha256,
                absolute_root=absolute,
            )
            # Transfer ownership only after all preconditions pass.
            return root_fd, manifests_fd, outputs_fd, auth, auth_bytes, lock_bytes
        except BaseException:
            os.close(manifests_fd)
            os.close(outputs_fd)
            raise
    except BaseException:
        os.close(root_fd)
        raise


def _require_receipt_times(
    auth: Mapping[str, Any], lock_bytes: bytes, started_at_utc: str, ended_at_utc: str,
) -> None:
    lock = bundle._parse_json(lock_bytes, "D one-shot lock")
    _require(isinstance(lock, Mapping), "D one-shot lock is not an object")
    issued = bundle._parse_utc(auth.get("issued_at_utc"), "D authorization issued_at_utc")
    expires = bundle._parse_utc(auth.get("expires_at_utc"), "D authorization expires_at_utc")
    lock_created = bundle._parse_utc(lock.get("created_at_utc"), "D one-shot lock created_at_utc")
    started = bundle._parse_utc(started_at_utc, "D receipt started_at_utc")
    ended = bundle._parse_utc(ended_at_utc, "D receipt ended_at_utc")
    _require(issued <= lock_created < started < expires and started <= ended <= expires,
             "D receipt timestamps are outside caller authorization/lock validity")


def _verified_b_c_context(
    b_root: Path | str,
    c_root: Path | str,
    *,
    trusted_authorization_bytes: Mapping[str, bytes],
    trusted_authorization_sha256: Mapping[str, str],
    expected_authorization_envelopes: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[str], Any, bytes, dict[str, Any]]:
    _require(set(trusted_authorization_bytes) == {"B", "C", "D"}
             and set(trusted_authorization_sha256) == {"B", "C", "D"}
             and set(expected_authorization_envelopes) == {"B", "C", "D"},
             "caller trust inputs must be exactly the B/C/D stage set")
    checked = {
        stage: bundle.verify_stage_bundle(
            root, stage,
            trusted_authorization_bytes=trusted_authorization_bytes[stage],
            trusted_authorization_sha256=trusted_authorization_sha256[stage],
            expected_authorization_envelope=expected_authorization_envelopes[stage],
        )
        for stage, root in (("B", b_root), ("C", c_root))
    }
    _require(checked["B"]["status"] == "passed" and checked["C"]["status"] == "passed",
             "D producer requires already-passed B and C bundles")
    _require(checked["B"]["case_id"] == checked["C"]["case_id"], "B/C case identities differ")
    bundle._binding_matches(
        checked["C"]["_receipt_document"].get("materialization_receipt_binding"),
        checked["B"]["receipt_path"], checked["B"]["_receipt_bytes"], "C→B materialization receipt",
    )
    row = bundle._frozen_qualification_row(checked["B"]["case_id"])
    axis = bundle.expected_time_axis_hex(row)
    frames = checked["C"]["_manifest_document"].get("frames")
    _require(isinstance(frames, list) and len(frames) == len(axis),
             "verified C frames do not cover the frozen full native axis")
    for ordinal, (frame, expected) in enumerate(zip(frames, axis)):
        _require(isinstance(frame, dict) and frame.get("ordinal") == ordinal
                 and frame.get("expected_time_s_ieee754_hex") == expected,
                 "verified C frame ordering or frozen time axis changed")

    b_root_fd, b_outputs_fd = bundle._open_verified_outputs(checked["B"])
    try:
        cohorts, mass_bits_hex = bundle._verify_b_materialization_semantics(
            b_outputs_fd, checked["B"]["_output_file_manifest"], checked["B"]["_receipt_document"],
        )
    finally:
        os.close(b_outputs_fd)
        os.close(b_root_fd)
    fluid_ids = table_chain._fluid_ids_from_cohorts(cohorts)
    _require(isinstance(mass_bits_hex, str) and len(mass_bits_hex) == 16,
             "verified B MassFluid is not exact binary64")

    lab_fd, _absolute = bundle._open_absolute_directory(bundle.LAB)
    try:
        definition = table_chain._check_frozen_source_binding(
            checked["B"]["_receipt_document"], row, "definition", lab_fd,
        )
        table_chain._check_frozen_source_binding(
            checked["B"]["_receipt_document"], row, "control", lab_fd,
        )
        parameter_contract = bundle._stable_read_beneath(
            lab_fd, table_chain.PARAMETER_CONTRACT_RELATIVE, bundle.MAX_RECEIPT_BYTES,
        )
        _require(_sha256(parameter_contract) == table_chain.PARAMETER_CONTRACT_SHA256,
                 "pinned F8 parameter contract changed")
    finally:
        os.close(lab_fd)
    b_receipt = checked["B"]["_receipt_document"]
    attrs = table_v2.expected_root_attributes(
        case_id=checked["B"]["case_id"],
        generated_xml_sha256=b_receipt["generated_xml_path"]["sha256"],
        definition_sha256=definition["sha256"],
        materialization_receipt_sha256=checked["B"]["receipt_sha256"],
        raw_solver_manifest_sha256=checked["C"]["manifest_sha256"],
        scope_receipt_sha256=bundle.FROZEN_INPUT_SHA256["scope"],
        parameter_contract_sha256=table_chain.PARAMETER_CONTRACT_SHA256,
    )
    return checked["B"], checked["C"], frames, axis, fluid_ids, bytes.fromhex(mass_bits_hex), attrs


def _observed_time_hex(metadata: Mapping[str, Any], expected_hex: str) -> str:
    records = bundle._metadata_record_index(metadata)
    matches = [record for (path, name), record in records.items()
               if path and path[0] == "JPartDataBi4" and len(path) == 2 and name == "TimeStep"]
    _require(len(matches) == 1 and matches[0].get("type_code") == 12,
             "raw frame does not contain one exact PART TimeStep")
    values = matches[0].get("float_hex_components")
    _require(isinstance(values, list) and len(values) == 1 and isinstance(values[0], str),
             "raw frame TimeStep does not expose one binary64 value")
    try:
        observed = float.fromhex(values[0])
        expected = float.fromhex(expected_hex)
    except ValueError as error:
        raise DArtifactProducerError("raw frame TimeStep hexadecimal is malformed") from error
    _require(math.isfinite(observed) and observed.hex() == values[0]
             and not (observed == 0.0 and math.copysign(1.0, observed) < 0.0)
             and struct.pack("<d", observed) == struct.pack("<d", expected),
             "raw frame observed TimeStep differs from frozen binary64 axis")
    return values[0]


def _source_factory(c_outputs_fd: int, frames: Iterable[Mapping[str, Any]], axis: Iterable[str]):
    """Return a factory whose each pass reopens/hash-checks every raw C frame."""
    frozen_frames = tuple(frames)
    frozen_axis = tuple(axis)

    def iterate():
        for ordinal, (entry, expected_time) in enumerate(zip(frozen_frames, frozen_axis)):
            _require(entry.get("ordinal") == ordinal
                     and entry.get("expected_time_s_ieee754_hex") == expected_time,
                     "C raw frame changed before independent table-source reopening")
            raw_fd = decoder.open_regular_beneath(c_outputs_fd, entry["path"])
            try:
                yield table_v2.read_native_source_frame_fd(
                    raw_fd, entry["sha256"], expected_bytes=entry["bytes"],
                )
            finally:
                os.close(raw_fd)
    return iterate


def _validate_candidate_before_receipt(
    *,
    root_fd: int,
    manifests_fd: int,
    outputs_fd: int,
    auth: Mapping[str, Any],
    auth_bytes: bytes,
    lock_bytes: bytes,
    receipt: Mapping[str, Any],
    outputs_manifest: Mapping[str, Any],
    decoded_manifest: Mapping[str, Any],
    outputs_payload: bytes,
    decoded_payload: bytes,
    b_result: Mapping[str, Any],
    c_result: Mapping[str, Any],
    c_outputs_fd: int,
    mappings: list[dict[str, Any]],
    frames: Iterable[Mapping[str, Any]],
    axis: Iterable[str],
    expected_fluid_ids: Any,
    initial_massfluid_binary64_le: bytes,
    expected_table_attributes: Mapping[str, Any],
    decoder_code_binding: Mapping[str, Any],
    trusted_code_review_receipt_bytes: bytes,
    trusted_runtime_assumption: Mapping[str, Any],
    started_at_utc: str,
    ended_at_utc: str,
) -> None:
    """Independently close all D artifacts before publishing a passed receipt.

    The established v1 verifier requires receipt.json to exist, so it cannot
    validate a not-yet-published receipt in place. This precommit check reuses
    its stable manifest/tree/frame validators and independently reopens the C
    raw frames before the final O_EXCL receipt write. This producer does not
    claim that the post-publication v1 bundle/provenance verifiers were run;
    callers and tests must run those independent consumers after publication.
    """
    _require(set(receipt) == bundle.STAGE_REQUIRED_FIELDS["D"],
             "candidate D receipt fields differ from the exact v1 contract")
    _require(receipt.get("schema") == bundle.STAGE_RECEIPT_SCHEMAS["D"]
             and receipt.get("status") == "passed"
             and receipt.get("scope_id") == bundle.SCOPE_ID
             and receipt.get("case_id") == auth.get("case_id")
             and receipt.get("attempt_id") == auth.get("attempt_id")
             and receipt.get("nonce") == auth.get("nonce"),
             "candidate D receipt schema/status/identity is not exact")
    reread_auth, reread_auth_bytes = _read_current_user_nonshared_json(
        root_fd, "authorization.json", "precommit D authorization",
    )
    reread_lock, reread_lock_bytes = _read_current_user_nonshared_json(
        root_fd, "one-shot-lock.json", "precommit D one-shot lock",
    )
    _require(reread_auth == dict(auth) and reread_auth_bytes == auth_bytes
             and reread_lock_bytes == lock_bytes,
             "D prelude bytes changed before receipt publication")
    _validate_v1_d_authorization_and_lock(
        reread_auth, reread_lock,
        trusted_authorization_sha256=_sha256(auth_bytes),
        absolute_root=str(auth["exclusive_output_root"]),
    )
    _require_receipt_times(auth, lock_bytes, started_at_utc, ended_at_utc)
    bundle._verify_d_code_binding(decoder_code_binding, trusted_code_review_receipt_bytes)
    bundle._verify_runtime_assumption(trusted_runtime_assumption)
    bundle._binding_matches(receipt.get("authorization_binding"), "authorization.json",
                            auth_bytes, "candidate D authorization")
    bundle._binding_matches(receipt.get("one_shot_lock_binding"), "one-shot-lock.json",
                            lock_bytes, "candidate D one-shot lock")
    bundle._binding_matches(
        receipt.get("solver_receipt_binding"), c_result["receipt_path"],
        c_result["_receipt_bytes"], "candidate D→C solver receipt",
    )
    _require(receipt.get("decoder_code_binding") == dict(decoder_code_binding),
             "candidate D receipt code binding differs from the reviewed caller input")
    bundle._binding_matches(receipt.get("decoded_frame_manifest_binding"),
                            f"manifests/{DECODED_FRAME_MANIFEST}", decoded_payload,
                            "candidate decoded-frame manifest")
    bundle._binding_matches(receipt.get("outputs_manifest_binding"),
                            f"manifests/{OUTPUTS_MANIFEST}", outputs_payload,
                            "candidate D outputs manifest")
    _require(receipt.get("frame_mappings") == mappings
             and decoded_manifest.get("frames") == mappings
             and decoded_manifest.get("schema") == "core.cfd.f8.r008_decoded_frame_manifest.v1"
             and decoded_manifest.get("stage") == "D"
             and decoded_manifest.get("case_id") == auth.get("case_id")
             and decoded_manifest.get("attempt_id") == auth.get("attempt_id")
             and decoded_manifest.get("raw_solver_manifest_sha256") == c_result["manifest_sha256"]
             and set(decoded_manifest) == bundle.MANIFEST_DOCUMENT_FIELDS["D_frames"]
             and _canonical_json(decoded_manifest) == decoded_payload,
             "candidate decoded-frame manifest differs from its exact v1 contract")
    bundle._reject_manifest_cycle_keys(decoded_manifest, "D_frames")
    _require(set(outputs_manifest) == bundle.MANIFEST_DOCUMENT_FIELDS["D_outputs"]
             and outputs_manifest.get("schema") == "core.cfd.f8.r008_decode_outputs_manifest.v1"
             and outputs_manifest.get("stage") == "D"
             and _canonical_json(outputs_manifest) == outputs_payload,
             "candidate D outputs manifest differs from its exact v1 contract")
    _require(set(bundle._bounded_directory_names(root_fd, 4, "precommit D bundle root"))
             == {"authorization.json", "one-shot-lock.json", "manifests", "outputs"},
             "D root changed before receipt publication")
    for label, fd in (("bundle root", root_fd), ("manifests", manifests_fd), ("outputs", outputs_fd)):
        directory_stat = os.fstat(fd)
        _require(stat.S_ISDIR(directory_stat.st_mode) and directory_stat.st_uid == os.geteuid()
                 and not (directory_stat.st_mode & (stat.S_IWGRP | stat.S_IWOTH)),
                 f"D {label} directory permissions changed before receipt publication")
    _require(set(bundle._bounded_directory_names(manifests_fd, 2, "precommit D manifests"))
             == {OUTPUTS_MANIFEST, DECODED_FRAME_MANIFEST},
             "D manifests directory changed before receipt publication")
    on_disk_outputs_manifest, manifest_bytes = _read_current_user_nonshared_json(
        manifests_fd, OUTPUTS_MANIFEST, "D outputs manifest",
    )
    on_disk_decoded_manifest, decoded_bytes = _read_current_user_nonshared_json(
        manifests_fd, DECODED_FRAME_MANIFEST, "D decoded-frame manifest",
    )
    _require(manifest_bytes == outputs_payload and decoded_bytes == decoded_payload
             and on_disk_outputs_manifest == dict(outputs_manifest)
             and on_disk_decoded_manifest == dict(decoded_manifest),
             "written candidate D manifests differ from their precommit payloads")
    _require(_canonical_json(on_disk_outputs_manifest) == manifest_bytes
             and _canonical_json(on_disk_decoded_manifest) == decoded_bytes,
             "written candidate D manifests are not canonical JSON")
    files, directories = bundle._validate_tree_manifest(
        outputs_fd, outputs_manifest, "core.cfd.f8.r008_decode_outputs_manifest.v1", "D",
    )
    _require(directories == outputs_manifest["directories"],
             "candidate D outputs tree differs from its exact directory inventory")
    _verify_output_tree_permissions(outputs_fd, files, directories)

    c_manifest = c_result["_manifest_document"]
    raw_frames = c_manifest.get("frames")
    frozen_frames = tuple(frames)
    frozen_axis = tuple(axis)
    _require(isinstance(raw_frames, list) and len(raw_frames) == len(frozen_frames) == len(frozen_axis)
             and len(mappings) == len(frozen_axis),
             "candidate D frame count differs from the complete C/frozen axis")
    _require(decoded_manifest.get("raw_solver_manifest_sha256") == c_result["manifest_sha256"],
             "candidate D frame manifest does not bind the verified C manifest")

    b_root_fd, b_outputs_fd = bundle._open_verified_outputs(b_result)
    try:
        cohorts, initial_mass_hex = bundle._verify_b_materialization_semantics(
            b_outputs_fd, b_result["_output_file_manifest"], b_result["_receipt_document"],
        )
    finally:
        os.close(b_outputs_fd)
        os.close(b_root_fd)

    for ordinal, (raw_entry, frame, expected_time) in enumerate(
        zip(raw_frames, mappings, frozen_axis),
    ):
        _require(isinstance(frame, dict) and set(frame) == bundle.D_FRAME_FIELDS
                 and isinstance(raw_entry, dict)
                 and frame.get("ordinal") == ordinal
                 and frame.get("raw_solver_ordinal") == ordinal
                 and raw_entry.get("ordinal") == ordinal
                 and frame.get("raw_solver_manifest_sha256") == c_result["manifest_sha256"]
                 and frame.get("expected_time_s_ieee754_hex") == expected_time
                 and frame.get("expected_time_s_ieee754_hex") == raw_entry.get("expected_time_s_ieee754_hex")
                 and frame.get("raw_path") == raw_entry.get("path")
                 and frame.get("raw_bytes") == raw_entry.get("bytes")
                 and frame.get("raw_sha256") == raw_entry.get("sha256")
                 and frame.get("safe_decode_input_sha256") == raw_entry.get("sha256"),
                 "candidate D mapping does not exactly bind the C raw-frame entry")
        safe_receipt, d_metadata = bundle._check_d_frame_artifacts(outputs_fd, files, frame)
        raw_fd = decoder.open_regular_beneath(c_outputs_fd, raw_entry["path"])
        try:
            metadata_result = metadata_binding.bind_metadata_fd(raw_fd, raw_entry["sha256"])
            scan = metadata_result["scan"]
            _require(scan.input_bytes == raw_entry["bytes"]
                     and metadata_result["manifest_bytes"]
                     == bundle._canonical_json(d_metadata),
                     "candidate D metadata manifest differs from the held C raw frame")
            bundle._require_native_arrays(scan, metadata_result["manifest"])
            case_np, group_counts = bundle._bi4_case_counts(metadata_result["manifest"])
            _require(case_np == cohorts["case_np"] and group_counts == cohorts["group_counts"],
                     "candidate C BI4 particle cohorts differ from verified B materialization")
            bundle._verify_raw_particle_ids(
                raw_fd, scan, cohorts, raw_entry["sha256"], f"precommit C frame {ordinal}",
            )
            observed = _observed_time_hex(metadata_result["manifest"], expected_time)
            _require(frame.get("parser_observed_time_s_ieee754_hex") == observed
                     and bundle._metadata_mass_bits(metadata_result["manifest"]) == initial_mass_hex,
                     "candidate D time or MassFluid differs from raw C bytes and B reference")
            bundle._verify_safe_decode_against_scan(
                raw_fd, scan, safe_receipt, frame, outputs_fd, files, directories,
            )
            after = os.fstat(raw_fd)
            _require(decoder._identity(after) == scan.input_identity and after.st_nlink == 1
                     and decoder._hash_fd(raw_fd, scan.input_bytes) == raw_entry["sha256"],
                     "C raw frame changed during D candidate precommit verification")
        finally:
            os.close(raw_fd)

    table_binding = receipt.get("native_fluid_table_binding")
    _require(isinstance(table_binding, dict)
             and set(table_binding) == {"path", "bytes", "sha256"}
             and table_binding.get("path") == f"outputs/{TABLE_RELATIVE}",
             "candidate D table binding fields or path are invalid")
    bundle._verify_bound_output(outputs_fd, files, TABLE_RELATIVE,
                                table_binding.get("bytes"), table_binding.get("sha256"),
                                "candidate D v2 native-fluid table")
    table_fd = decoder.open_regular_beneath(outputs_fd, TABLE_RELATIVE)
    source_frames = _source_factory(c_outputs_fd, frozen_frames, frozen_axis)()
    try:
        table_v2.verify_native_fluid_table_fd(
            table_fd,
            expected_table_bytes=table_binding["bytes"],
            expected_table_sha256=table_binding["sha256"],
            expected_attributes=expected_table_attributes,
            expected_time_axis_hex=frozen_axis,
            expected_fluid_ids=expected_fluid_ids,
            expected_case_np=cohorts["case_np"],
            initial_massfluid_binary64_le=initial_massfluid_binary64_le,
            source_frames=source_frames,
        )
    finally:
        source_frames.close()
        os.close(table_fd)
    _require(receipt.get("execution_controls") == {
        "native_binary_invoked": False, "gencase_invoked": False, "solver_invoked": False,
        "worker_started": False, "gpu_invoked": False, "queue_mutation": 0,
        "qualification_credit": 0,
    }, "candidate D receipt execution-control boundary is not exact")


def produce_d_artifacts_v2(
    *,
    b_bundle_root: Path | str,
    c_bundle_root: Path | str,
    d_target_root: Path | str,
    trusted_authorization_bytes: Mapping[str, bytes],
    trusted_authorization_sha256: Mapping[str, str],
    expected_authorization_envelopes: Mapping[str, Mapping[str, Any]],
    decoder_code_binding: Mapping[str, Any],
    trusted_code_review_receipt_bytes: bytes,
    trusted_runtime_assumption: Mapping[str, Any],
    started_at_utc: str,
    ended_at_utc: str,
) -> dict[str, Any]:
    """Add one complete D attempt from verified B/C inputs to a fresh D root.

    Caller-supplied B/C/D authorization bytes/envelopes, the reviewed decoder
    binding, and runtime attestation are trust inputs.  No authorization or
    one-shot lock is created, consumed, or authenticated here.  On any error
    this routine deliberately performs no rollback: previously written D
    artifacts remain in the fresh target and the target must not be retried.
    """
    _require(set(trusted_authorization_bytes) == {"B", "C", "D"}
             and set(trusted_authorization_sha256) == {"B", "C", "D"}
             and set(expected_authorization_envelopes) == {"B", "C", "D"},
             "caller trust inputs must be exactly the B/C/D stage set")
    # Fail before touching the new D namespace if the caller's reviewed-code
    # binding or runtime TCB attestation cannot satisfy the established v1 API.
    bundle._verify_d_code_binding(decoder_code_binding, trusted_code_review_receipt_bytes)
    bundle._verify_runtime_assumption(trusted_runtime_assumption)
    b_result, c_result, frames, axis, fluid_ids, mass_bits, attributes = _verified_b_c_context(
        b_bundle_root, c_bundle_root,
        trusted_authorization_bytes=trusted_authorization_bytes,
        trusted_authorization_sha256=trusted_authorization_sha256,
        expected_authorization_envelopes=expected_authorization_envelopes,
    )
    root_fd, manifests_fd, outputs_fd, d_auth, auth_bytes, lock_bytes = _read_target_prelude(
        d_target_root,
        trusted_authorization_bytes=trusted_authorization_bytes["D"],
        trusted_authorization_sha256=trusted_authorization_sha256["D"],
        expected_authorization_envelope=expected_authorization_envelopes["D"],
    )
    c_root_fd, c_outputs_fd = bundle._open_verified_outputs(c_result)
    try:
        _require(d_auth["case_id"] == b_result["case_id"] == c_result["case_id"],
                 "D target case differs from verified B/C context")
        _require_receipt_times(d_auth, lock_bytes, started_at_utc, ended_at_utc)
        receipt_dirs: dict[str, int] = {}
        try:
            receipt_dirs[DECODE_RECEIPTS_DIR] = _open_new_directory(outputs_fd, DECODE_RECEIPTS_DIR, 0o700)
            receipt_dirs[METADATA_BINDINGS_DIR] = _open_new_directory(outputs_fd, METADATA_BINDINGS_DIR, 0o700)
            receipt_dirs[DECODED_DIR] = _open_new_directory(outputs_fd, DECODED_DIR, 0o700)
            os.fsync(outputs_fd)
            mappings: list[dict[str, Any]] = []
            for ordinal, (entry, expected_time) in enumerate(zip(frames, axis)):
                raw_fd = decoder.open_regular_beneath(c_outputs_fd, entry["path"])
                try:
                    metadata = metadata_binding.bind_metadata_fd(raw_fd, entry["sha256"])
                    _require(metadata["scan"].input_bytes == entry["bytes"],
                             "C raw frame byte count changed during D metadata binding")
                    observed_time = _observed_time_hex(metadata["manifest"], expected_time)
                    safe_receipt = decoder.decode_bi4_fd(
                        raw_fd, entry["sha256"], receipt_dirs[DECODED_DIR], f"frame-{ordinal:04d}",
                    )
                    current = os.fstat(raw_fd)
                    _require(current.st_size == entry["bytes"]
                             and decoder._hash_fd(raw_fd, current.st_size) == entry["sha256"],
                             "C raw frame changed during D safe decode")
                finally:
                    os.close(raw_fd)
                safe_payload = _canonical_json(safe_receipt)
                safe_name = f"frame-{ordinal:04d}.json"
                metadata_name = f"frame-{ordinal:04d}.json"
                _write_new_file(receipt_dirs[DECODE_RECEIPTS_DIR], safe_name, safe_payload)
                _write_new_file(receipt_dirs[METADATA_BINDINGS_DIR], metadata_name, metadata["manifest_bytes"])
                mappings.append({
                    "ordinal": ordinal,
                    "expected_time_s_ieee754_hex": expected_time,
                    "parser_observed_time_s_ieee754_hex": observed_time,
                    "raw_solver_manifest_sha256": c_result["manifest_sha256"],
                    "raw_solver_ordinal": ordinal,
                    "raw_path": entry["path"], "raw_bytes": entry["bytes"], "raw_sha256": entry["sha256"],
                    "safe_decode_input_sha256": entry["sha256"],
                    "safe_decode_receipt_path": f"{DECODE_RECEIPTS_DIR}/{safe_name}",
                    "safe_decode_receipt_bytes": len(safe_payload), "safe_decode_receipt_sha256": _sha256(safe_payload),
                    "metadata_binding_manifest_path": f"{METADATA_BINDINGS_DIR}/{metadata_name}",
                    "metadata_binding_manifest_bytes": len(metadata["manifest_bytes"]),
                    "metadata_binding_manifest_sha256": metadata["manifest_sha256"],
                    "decoded_output_parent_relative_path": DECODED_DIR,
                    "decoded_output_name": f"frame-{ordinal:04d}",
                })
            table_result = table_producer.produce_native_fluid_table_v2_at(
                outputs_fd, expected_attributes=attributes, expected_time_axis_hex=axis,
                expected_fluid_ids=fluid_ids, expected_case_np=b_result["particle_count"],
                initial_massfluid_binary64_le=mass_bits,
                source_frames_factory=_source_factory(c_outputs_fd, frames, axis),
            )
            table_binding = table_result["table_binding"]
            _require(table_binding["path"] == TABLE_RELATIVE, "v2 producer returned an unexpected table basename")
            files, directories = bundle._inventory_tree(outputs_fd)
            outputs_manifest = {
                "schema": "core.cfd.f8.r008_decode_outputs_manifest.v1", "stage": "D",
                "files": [{"path": path, **files[path]} for path in sorted(files)],
                "directories": directories,
            }
            decoded_manifest = {
                "schema": "core.cfd.f8.r008_decoded_frame_manifest.v1", "stage": "D",
                "case_id": d_auth["case_id"], "attempt_id": d_auth["attempt_id"],
                "raw_solver_manifest_sha256": c_result["manifest_sha256"], "frames": mappings,
            }
            decoded_payload = _canonical_json(decoded_manifest)
            outputs_payload = _canonical_json(outputs_manifest)
            _write_new_file(manifests_fd, DECODED_FRAME_MANIFEST, decoded_payload)
            _write_new_file(manifests_fd, OUTPUTS_MANIFEST, outputs_payload)
            receipt = {
                "schema": "core.cfd.f8.r008_decode_table_provenance.v1", "scope_id": bundle.SCOPE_ID,
                "case_id": d_auth["case_id"], "attempt_id": d_auth["attempt_id"], "nonce": d_auth["nonce"],
                "status": "passed", "started_at_utc": started_at_utc, "ended_at_utc": ended_at_utc,
                "authorization_binding": _binding("authorization.json", auth_bytes),
                "one_shot_lock_binding": _binding("one-shot-lock.json", lock_bytes),
                "solver_receipt_binding": _binding(c_result["receipt_path"], c_result["_receipt_bytes"]),
                "decoder_code_binding": dict(decoder_code_binding),
                "decoded_frame_manifest_binding": _binding(f"manifests/{DECODED_FRAME_MANIFEST}", decoded_payload),
                "outputs_manifest_binding": _binding(f"manifests/{OUTPUTS_MANIFEST}", outputs_payload),
                "frame_mappings": mappings,
                "native_fluid_table_binding": {
                    "path": f"outputs/{TABLE_RELATIVE}",
                    "bytes": table_binding["bytes"], "sha256": table_binding["sha256"],
                },
                "execution_controls": {
                    "native_binary_invoked": False, "gencase_invoked": False, "solver_invoked": False,
                    "worker_started": False, "gpu_invoked": False, "queue_mutation": 0,
                    "qualification_credit": 0,
                },
            }
            receipt_payload = _canonical_json(receipt)
            _validate_candidate_before_receipt(
                root_fd=root_fd, manifests_fd=manifests_fd, outputs_fd=outputs_fd,
                auth=d_auth, auth_bytes=auth_bytes, lock_bytes=lock_bytes,
                receipt=receipt, outputs_manifest=outputs_manifest,
                decoded_manifest=decoded_manifest, outputs_payload=outputs_payload,
                decoded_payload=decoded_payload, b_result=b_result, c_result=c_result,
                c_outputs_fd=c_outputs_fd, mappings=mappings, frames=frames, axis=axis,
                expected_fluid_ids=fluid_ids, initial_massfluid_binary64_le=mass_bits,
                expected_table_attributes=attributes,
                decoder_code_binding=decoder_code_binding,
                trusted_code_review_receipt_bytes=trusted_code_review_receipt_bytes,
                trusted_runtime_assumption=trusted_runtime_assumption,
                started_at_utc=started_at_utc, ended_at_utc=ended_at_utc,
            )
            # The passed receipt is the commit record: publish it only after the
            # in-memory candidate and all on-disk D artifacts passed precommit.
            publication = _publish_passed_receipt(root_fd, receipt_payload)
        finally:
            for fd in receipt_dirs.values():
                _close_quietly(fd)
        return {
            "schema": SCHEMA, "status": "D_candidate_precommit_validated_and_receipt_published_once",
            "d_receipt_sha256": _sha256(receipt_payload), "frame_count": len(mappings),
            "native_fluid_table_binding": receipt["native_fluid_table_binding"],
            "D_candidate_precommit_validated": True,
            "independent_postpublication_bundle_verification_performed": False,
            **publication,
            "native_integrity_evaluated": False, "T1_numerical": False,
            "readiness_pass": False, "qualification_credit": 0,
        }
    finally:
        _close_quietly(c_outputs_fd)
        _close_quietly(c_root_fd)
        _close_quietly(outputs_fd)
        _close_quietly(manifests_fd)
        _close_quietly(root_fd)


__all__ = ["DArtifactProducerError", "SCHEMA", "produce_d_artifacts_v2"]
