#!/usr/bin/env python3
"""Fail-closed intake for an externally trusted F8/R008 pin attestation.

This additive contract is deliberately separate from the existing target-kernel
evidence intake.  It consumes two explicitly supplied bounded JSON documents:
an attestation carrying the target-kernel/source/build/runtime-ABI pins and a
trust-root record carrying the public key that is allowed to sign it.  The
caller must also provide that public key through an independent trust channel;
the anchor document alone is never allowed to establish its own trust root.
The attestation also carries an externally recorded, consumed one-shot receipt.

The verifier checks exact schemas, canonical JSON bytes, all cross-domain SHA
bindings, host identity, Ed25519 trust-root/key binding, and the one-shot
receipt transition.  It does not read the pinned source tree, kernel, build,
runtime, procfs/sysfs, or any solver artifact.  A cryptographically consistent
external attestation is still non-authorizing: live runtime measurement,
replay-ledger observation, production admission, and T1 credit remain false.
Synthetic fixtures, self-attested keys, missing anchors, and partial evidence
always remain blocked/untrusted.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))
from scripts.core_strict_json import strict_json_object

DEFAULT_ATTESTATION = Path(
    "external/f8-r008-trusted-target-pin-attestation-v1.json"
)
DEFAULT_TRUST_ANCHOR = Path(
    "external/f8-r008-trusted-target-pin-trust-anchor-v1.json"
)
DEFAULT_REPORT = Path("reports/F8-R008-TRUSTED-TARGET-PIN-INTAKE-V1.json")

SCOPE_ID = "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R008"
SCHEMA = "core.cfd.f8.r008.trusted_target_pin_attestation.v1"
ANCHOR_SCHEMA = "core.cfd.f8.r008.trusted_target_pin_anchor.v1"
RECEIPT_SCHEMA = "core.cfd.f8.r008.trusted_target_pin_one_shot_receipt.v1"
REPORT_SCHEMA = "core.cfd.f8.r008.trusted_target_pin_intake_report.v1"
RECORD_ID = "f8-r008-trusted-target-pin-attestation-v1"
ANCHOR_RECORD_ID = "f8-r008-trusted-target-pin-anchor-v1"
RECEIPT_RECORD_ID = "f8-r008-trusted-target-pin-one-shot-receipt-v1"
REPORT_RECORD_ID = "f8-r008-trusted-target-pin-intake-report-v1"

ATTESTATION_ORIGIN = "external_trusted_target_runtime_attestation"
ANCHOR_ORIGIN = "external_trusted_root_registry"
ANCHOR_SOURCE = "out_of_band_trust_registry"
SIGNING_DOMAIN = "CORE-F8-R008-TRUSTED-TARGET-PIN-ATTESTATION-V1"
RECEIPT_DOMAIN = "CORE-F8-R008-TRUSTED-TARGET-PIN-RECEIPT-CONSUMPTION-V1"
ALGORITHM = "ed25519"
ABI_SCHEMA = "core.cfd.f8.r008.target_runtime_abi.v1"

MAX_JSON_BYTES = 512 * 1024
O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
O_NONBLOCK = getattr(os, "O_NONBLOCK", 0)
O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)

SHA256_RE = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
SHA1_RE = re.compile(r"[0-9a-f]{40}\Z", re.ASCII)
BUILD_ID_RE = re.compile(r"[0-9a-f]{16,128}\Z", re.ASCII)
NONCE_RE = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)
UUID4_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z",
    re.ASCII,
)
PUBLIC_KEY_HEX_RE = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
IDENTIFIER_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}\Z", re.ASCII)
RELEASE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+:-]{0,127}\Z", re.ASCII)
ARCH_RE = re.compile(r"[a-z0-9_+.-]{1,32}\Z", re.ASCII)

TARGET_ARCH = "x86_64"

ATTESTATION_FIELDS = frozenset(
    {
        "schema",
        "record_id",
        "scope_id",
        "evidence_origin",
        "synthetic",
        "target_kernel",
        "source",
        "build",
        "runtime_abi",
        "host_identity",
        "trust_root_ref",
        "one_shot_receipt",
        "signature",
    }
)
ANCHOR_FIELDS = frozenset(
    {
        "schema",
        "record_id",
        "evidence_origin",
        "synthetic",
        "root_id",
        "key_id",
        "algorithm",
        "public_key_base64",
        "public_key_sha256",
        "registry_sha256",
        "epoch",
        "revoked",
        "source",
    }
)
TARGET_KERNEL_FIELDS = frozenset(
    {
        "kernel_release",
        "arch",
        "source_commit",
        "source_tree_sha256",
        "uapi_sha256",
        "config_sha256",
        "build_id",
        "kernel_image_sha256",
        "config_options_sha256",
        "syscall_policy_sha256",
    }
)
SOURCE_FIELDS = frozenset(
    {
        "source_commit",
        "source_tree_sha256",
        "uapi_sha256",
        "source_manifest_sha256",
        "callgraph_sha256",
        "patchset_sha256",
    }
)
BUILD_FIELDS = frozenset(
    {
        "arch",
        "build_id",
        "build_closure_sha256",
        "compiler_identity_sha256",
        "linker_identity_sha256",
        "binary_sha256",
        "config_sha256",
        "build_manifest_sha256",
    }
)
RUNTIME_ABI_FIELDS = frozenset(
    {
        "abi_schema",
        "kernel_release",
        "arch",
        "build_id",
        "config_sha256",
        "host_identity_sha256",
        "runtime_image_sha256",
        "loaded_modules_sha256",
        "syscall_policy_sha256",
        "fanotify_abi_sha256",
        "fid_abi_sha256",
        "pidfd_abi_sha256",
        "seccomp_abi_sha256",
        "selector_min",
        "selector_max",
        "abi_payload_sha256",
    }
)
HOST_FIELDS = frozenset(
    {
        "host_id",
        "machine_id_sha256",
        "boot_id_sha256",
        "host_attestation_sha256",
        "host_profile_sha256",
    }
)
TRUST_ROOT_REF_FIELDS = frozenset(
    {
        "root_id",
        "key_id",
        "algorithm",
        "public_key_sha256",
        "registry_sha256",
        "epoch",
    }
)
RECEIPT_FIELDS = frozenset(
    {
        "schema",
        "record_id",
        "receipt_id",
        "scope_id",
        "pin_set_sha256",
        "host_identity_sha256",
        "root_id",
        "key_id",
        "nonce_hex",
        "generation",
        "state",
        "single_use",
        "replay_policy",
        "issued_epoch",
        "consumed_epoch",
        "expires_epoch",
        "consumption_binding_sha256",
    }
)
SIGNATURE_FIELDS = frozenset(
    {"algorithm", "key_id", "signed_payload_sha256", "signature_base64"}
)

STATUS_BLOCKED_MISSING = "blocked_missing_external_trusted_pin_attestation"
STATUS_BLOCKED_INVALID = "blocked_invalid_external_trusted_pin_attestation"
STATUS_VALID_NON_AUTHORIZING = (
    "external_trusted_pin_attestation_cryptographically_verified_non_authorizing"
)

PIN_NAMES = (
    "target_kernel",
    "source",
    "build",
    "runtime_abi",
    "host_identity",
)


class TrustedTargetPinIntakeError(ValueError):
    """The supplied trusted pin documents are missing, unsafe, or malformed."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "invalid_external_trusted_pin_attestation",
        reference: Mapping[str, Any] | None = None,
        input_label: str | None = None,
        attestation_ref: Mapping[str, Any] | None = None,
        anchor_ref: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.reference = dict(reference) if reference is not None else None
        self.input_label = input_label
        self.attestation_ref = dict(attestation_ref) if attestation_ref is not None else None
        self.anchor_ref = dict(anchor_ref) if anchor_ref is not None else None


def _error(
    message: str,
    *,
    code: str = "invalid_external_trusted_pin_attestation",
    reference: Mapping[str, Any] | None = None,
    input_label: str | None = None,
    attestation_ref: Mapping[str, Any] | None = None,
    anchor_ref: Mapping[str, Any] | None = None,
) -> TrustedTargetPinIntakeError:
    return TrustedTargetPinIntakeError(
        message,
        code=code,
        reference=reference,
        input_label=input_label,
        attestation_ref=attestation_ref,
        anchor_ref=anchor_ref,
    )


def _require(condition: bool, message: str, *, code: str = "invalid_external_trusted_pin_attestation") -> None:
    if not condition:
        raise _error(message, code=code)


def _canonical(value: Any, label: str = "value") -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, OverflowError, RecursionError) as error:
        raise _error(f"{label} is not canonical-JSON serializable") from error


def _require_keys(value: Any, expected: frozenset[str], label: str) -> None:
    _require(type(value) is dict and set(value) == set(expected), f"{label} fields are not exact")


def _digest(value: Any, label: str, pattern: re.Pattern[str]) -> str:
    _require(type(value) is str and pattern.fullmatch(value) is not None,
             f"{label} is not a lowercase hexadecimal digest")
    if len(set(value)) == 1:
        raise _error(f"{label} is a synthetic/placeholder digest", code="placeholder_digest")
    for unit in ("0123456789abcdef", "abcdef", "deadbeef", "cafebabe", "feedface"):
        if (unit * ((len(value) // len(unit)) + 1))[: len(value)] == value:
            raise _error(f"{label} is a synthetic/placeholder digest", code="placeholder_digest")
    return value


def _sha256(value: Any, label: str) -> str:
    return _digest(value, label, SHA256_RE)


def _sha1(value: Any, label: str) -> str:
    return _digest(value, label, SHA1_RE)


def _build_id(value: Any, label: str) -> str:
    return _digest(value, label, BUILD_ID_RE)


def _uuid4(value: Any, label: str) -> str:
    _require(type(value) is str and UUID4_RE.fullmatch(value) is not None,
             f"{label} is not a canonical lowercase UUIDv4")
    return value


def _identifier(value: Any, label: str) -> str:
    _require(type(value) is str and IDENTIFIER_RE.fullmatch(value) is not None,
             f"{label} is malformed")
    _require(value not in {"anonymous", "candidate", "default", "self", "localhost", "current-host"},
             f"{label} may not use a default/local identity")
    return value


def _release(value: Any, label: str) -> str:
    _require(type(value) is str and RELEASE_RE.fullmatch(value) is not None,
             f"{label} is malformed")
    lowered = value.casefold()
    _require(lowered not in {"v6.8", "6.8", "linux-v6.8", "linux-6.8"},
             f"{label} may not be an upstream tag-only identity")
    _require(not any(word in lowered for word in ("synthetic", "placeholder", "example", "unknown", "pending")),
             f"{label} contains a placeholder marker")
    return value


def _arch(value: Any, label: str) -> str:
    _require(type(value) is str and ARCH_RE.fullmatch(value) is not None,
             f"{label} is malformed")
    _require(value not in {"unknown", "synthetic", "test"}, f"{label} is not a target identity")
    return value


def _epoch(value: Any, label: str) -> int:
    _require(type(value) is int and not isinstance(value, bool)
             and 0 <= value <= (1 << 63) - 1,
             f"{label} is outside the bounded epoch domain")
    return value


def _decode_base64(value: Any, *, size: int, label: str) -> bytes:
    _require(type(value) is str, f"{label} must be strict Base64 text")
    try:
        decoded = base64.b64decode(value.encode("ascii"), validate=True)
    except (UnicodeEncodeError, ValueError) as error:
        raise _error(f"{label} is not strict Base64") from error
    _require(len(decoded) == size and base64.b64encode(decoded).decode("ascii") == value,
             f"{label} is not canonical {size}-byte Base64")
    return decoded


def _display_path(path: Path) -> str:
    absolute = Path(os.path.abspath(os.fspath(path)))
    try:
        return absolute.relative_to(LAB_ROOT).as_posix()
    except ValueError:
        return absolute.as_posix()


def _input_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        if path.as_posix() != str(path) or any(part in {"", ".", ".."} for part in path.parts):
            raise _error("input path is not canonical", code="path_traversal")
    else:
        if any(part in {"", ".", ".."} for part in path.parts):
            raise _error("input path contains traversal components", code="path_traversal")
        path = LAB_ROOT / path
    return Path(os.path.abspath(os.fspath(path)))


def _assert_no_symlink_components(path: Path, label: str) -> None:
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current /= component
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            continue
        except OSError as error:
            raise _error(f"could not inspect {label} path", code="path_io") from error
        if stat.S_ISLNK(info.st_mode):
            raise _error(f"{label} path contains a symlink", code="symlink_path")


def _read_bounded_json(
    path: Path,
    *,
    label: str,
    require_canonical: bool = True,
) -> tuple[dict[str, Any], dict[str, Any], bytes]:
    """Read one explicit regular file through a stable no-follow descriptor."""

    _assert_no_symlink_components(path, label)
    opened: list[int] = []
    try:
        parts = path.parts
        _require(bool(path.is_absolute() and len(parts) > 1),
                 f"{label} must name an absolute regular file", code="path_traversal")
        _require(O_DIRECTORY != 0,
                 f"{label} cannot be opened safely without directory no-follow support",
                 code="path_io")
        parent_fd = os.open(
            path.anchor,
            os.O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC,
        )
        opened.append(parent_fd)
        for component in parts[1:-1]:
            next_fd = os.open(
                component,
                os.O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC,
                dir_fd=parent_fd,
            )
            opened.append(next_fd)
            parent_fd = next_fd
        descriptor = os.open(
            parts[-1],
            os.O_RDONLY | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK,
            dir_fd=parent_fd,
        )
        opened.append(descriptor)
    except FileNotFoundError as error:
        raise _error(f"{label} is missing", code="missing_file") from error
    except OSError as error:
        raise _error(f"{label} cannot be opened safely", code="path_io") from error
    try:
        before = os.fstat(descriptor)
        _require(stat.S_ISREG(before.st_mode), f"{label} must be a regular file", code="not_regular_file")
        _require(before.st_nlink == 1, f"{label} must have exactly one hard link", code="hardlink")
        _require(0 < before.st_size <= MAX_JSON_BYTES,
                 f"{label} is outside the bounded byte limit", code="oversize")
        raw = b""
        while len(raw) <= MAX_JSON_BYTES:
            block = os.read(descriptor, min(64 * 1024, MAX_JSON_BYTES + 1 - len(raw)))
            if not block:
                break
            raw += block
        after = os.fstat(descriptor)
        named = os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False)
        identity = lambda item: (
            item.st_dev,
            item.st_ino,
            item.st_mode,
            item.st_nlink,
            item.st_size,
            item.st_mtime_ns,
            item.st_ctime_ns,
        )
        _require(len(raw) <= MAX_JSON_BYTES and len(raw) == before.st_size,
                 f"{label} exceeds the bounded byte limit", code="oversize")
        _require(identity(before) == identity(after) == identity(named),
                 f"{label} changed during bounded read", code="drift")
        reference = {
            "path": _display_path(path),
            "exists": True,
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
        try:
            value = strict_json_object(raw, label=label, max_bytes=MAX_JSON_BYTES)
        except ValueError as error:
            raise _error(
                str(error),
                code="invalid_json",
                reference=reference,
                input_label=label,
            ) from error
        if require_canonical and _canonical(value, label) != raw:
            raise _error(
                f"{label} is not exact canonical JSON",
                code="noncanonical_json",
                reference=reference,
                input_label=label,
            )
        return value, reference, raw
    except TrustedTargetPinIntakeError:
        raise
    except OSError as error:
        raise _error(f"{label} could not be read safely", code="path_io") from error
    finally:
        for descriptor in reversed(opened):
            os.close(descriptor)


def _missing_reference(path: Path) -> dict[str, Any]:
    return {"path": _display_path(path), "exists": False, "bytes": None, "sha256": None}


def _anchor_projection(anchor: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "root_id": anchor["root_id"],
        "key_id": anchor["key_id"],
        "algorithm": anchor["algorithm"],
        "public_key_sha256": anchor["public_key_sha256"],
        "registry_sha256": anchor["registry_sha256"],
        "epoch": anchor["epoch"],
    }


def _pin_payload(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "scope_id": value["scope_id"],
        "target_kernel": value["target_kernel"],
        "source": value["source"],
        "build": value["build"],
        "runtime_abi": value["runtime_abi"],
        "host_identity": value["host_identity"],
    }


def _pin_set_digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(_pin_payload(value), "pin set payload")).hexdigest()


def _runtime_abi_payload(runtime: Mapping[str, Any]) -> dict[str, Any]:
    return {key: runtime[key] for key in sorted(RUNTIME_ABI_FIELDS) if key != "abi_payload_sha256"}


def _receipt_consumption_payload(receipt: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "domain": RECEIPT_DOMAIN,
        "receipt_id": receipt["receipt_id"],
        "scope_id": receipt["scope_id"],
        "pin_set_sha256": receipt["pin_set_sha256"],
        "host_identity_sha256": receipt["host_identity_sha256"],
        "root_id": receipt["root_id"],
        "key_id": receipt["key_id"],
        "nonce_hex": receipt["nonce_hex"],
        "generation": receipt["generation"],
        "state": receipt["state"],
        "issued_epoch": receipt["issued_epoch"],
        "consumed_epoch": receipt["consumed_epoch"],
        "expires_epoch": receipt["expires_epoch"],
    }


def _attestation_signing_payload(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value[key] for key in sorted(ATTESTATION_FIELDS) if key != "signature"}


def signing_message(value: Mapping[str, Any]) -> bytes:
    """Return the exact bytes signed by the external target trust key."""

    return SIGNING_DOMAIN.encode("ascii") + b"\n" + _canonical(
        _attestation_signing_payload(value), "attestation signing payload"
    )


def _validate_anchor(
    value: Any,
    *,
    explicit_public_key: bytes | None,
) -> tuple[dict[str, Any], bytes]:
    _require_keys(value, ANCHOR_FIELDS, "trust anchor")
    _require(value["schema"] == ANCHOR_SCHEMA, "trust anchor schema is unsupported")
    _require(value["record_id"] == ANCHOR_RECORD_ID, "trust anchor record_id is unsupported")
    _require(value["evidence_origin"] == ANCHOR_ORIGIN,
             "trust anchor evidence origin is not external")
    _require(value["synthetic"] is False,
             "synthetic trust anchor is never admissible", code="synthetic_evidence")
    root_id = _identifier(value["root_id"], "trust anchor root_id")
    key_id = _identifier(value["key_id"], "trust anchor key_id")
    _require(root_id != key_id, "trust root and signing key identities must be distinct")
    _require(value["algorithm"] == ALGORITHM, "trust anchor algorithm is unsupported")
    _sha256(value["public_key_sha256"], "trust anchor public_key_sha256")
    _sha256(value["registry_sha256"], "trust anchor registry_sha256")
    public_key = _decode_base64(value["public_key_base64"], size=32,
                                label="trust anchor public key")
    _require(value["public_key_sha256"] == hashlib.sha256(public_key).hexdigest(),
             "trust anchor public key SHA does not match its bytes")
    _require(
        type(explicit_public_key) is bytes and len(explicit_public_key) == 32,
        "an explicit out-of-band trust-anchor public key is required",
        code="missing_explicit_trust_anchor",
    )
    _require(
        public_key == explicit_public_key,
        "trust anchor public key does not match the explicit out-of-band trust anchor",
        code="trust_anchor_mismatch",
    )
    _epoch(value["epoch"], "trust anchor epoch")
    _require(value["revoked"] is False, "trust anchor is revoked")
    _require(value["source"] == ANCHOR_SOURCE,
             "trust anchor source is not the external registry")
    return value, public_key


def _validate_target_kernel(value: Any) -> dict[str, Any]:
    _require_keys(value, TARGET_KERNEL_FIELDS, "target_kernel")
    normalized = dict(value)
    _release(normalized["kernel_release"], "target_kernel.kernel_release")
    _arch(normalized["arch"], "target_kernel.arch")
    _require(normalized["arch"] == TARGET_ARCH,
             "target_kernel.arch is outside the frozen R008 native ABI")
    _sha1(normalized["source_commit"], "target_kernel.source_commit")
    for field in (
        "source_tree_sha256",
        "uapi_sha256",
        "config_sha256",
        "kernel_image_sha256",
        "config_options_sha256",
        "syscall_policy_sha256",
    ):
        _sha256(normalized[field], f"target_kernel.{field}")
    _build_id(normalized["build_id"], "target_kernel.build_id")
    return normalized


def _validate_source(value: Any) -> dict[str, Any]:
    _require_keys(value, SOURCE_FIELDS, "source")
    normalized = dict(value)
    _sha1(normalized["source_commit"], "source.source_commit")
    for field in (
        "source_tree_sha256",
        "uapi_sha256",
        "source_manifest_sha256",
        "callgraph_sha256",
        "patchset_sha256",
    ):
        _sha256(normalized[field], f"source.{field}")
    return normalized


def _validate_build(value: Any) -> dict[str, Any]:
    _require_keys(value, BUILD_FIELDS, "build")
    normalized = dict(value)
    _arch(normalized["arch"], "build.arch")
    _build_id(normalized["build_id"], "build.build_id")
    for field in (
        "build_closure_sha256",
        "compiler_identity_sha256",
        "linker_identity_sha256",
        "binary_sha256",
        "config_sha256",
        "build_manifest_sha256",
    ):
        _sha256(normalized[field], f"build.{field}")
    return normalized


def _validate_host(value: Any) -> dict[str, Any]:
    _require_keys(value, HOST_FIELDS, "host_identity")
    normalized = dict(value)
    _identifier(normalized["host_id"], "host_identity.host_id")
    for field in (
        "machine_id_sha256",
        "boot_id_sha256",
        "host_attestation_sha256",
        "host_profile_sha256",
    ):
        _sha256(normalized[field], f"host_identity.{field}")
    return normalized


def _validate_runtime(value: Any) -> dict[str, Any]:
    _require_keys(value, RUNTIME_ABI_FIELDS, "runtime_abi")
    normalized = dict(value)
    _require(normalized["abi_schema"] == ABI_SCHEMA, "runtime_abi schema is unsupported")
    _release(normalized["kernel_release"], "runtime_abi.kernel_release")
    _arch(normalized["arch"], "runtime_abi.arch")
    _require(normalized["arch"] == TARGET_ARCH,
             "runtime_abi.arch is outside the frozen R008 native ABI")
    _build_id(normalized["build_id"], "runtime_abi.build_id")
    _sha256(normalized["host_identity_sha256"], "runtime_abi.host_identity_sha256")
    for field in (
        "config_sha256",
        "runtime_image_sha256",
        "loaded_modules_sha256",
        "syscall_policy_sha256",
        "fanotify_abi_sha256",
        "fid_abi_sha256",
        "pidfd_abi_sha256",
        "seccomp_abi_sha256",
    ):
        _sha256(normalized[field], f"runtime_abi.{field}")
    for field in ("selector_min", "selector_max"):
        _require(type(normalized[field]) is int and not isinstance(normalized[field], bool),
                 f"runtime_abi.{field} must be an exact integer")
    _require(normalized["selector_min"] == 0 and normalized["selector_max"] == 461,
             "runtime_abi selector range is not the frozen 0..461 domain")
    _sha256(normalized["abi_payload_sha256"], "runtime_abi.abi_payload_sha256")
    expected = hashlib.sha256(_canonical(_runtime_abi_payload(normalized), "runtime ABI payload")).hexdigest()
    _require(normalized["abi_payload_sha256"] == expected,
             "runtime_abi.abi_payload_sha256 does not bind its fields")
    return normalized


def _validate_trust_root_ref(value: Any) -> dict[str, Any]:
    _require_keys(value, TRUST_ROOT_REF_FIELDS, "trust_root_ref")
    normalized = dict(value)
    _identifier(normalized["root_id"], "trust_root_ref.root_id")
    _identifier(normalized["key_id"], "trust_root_ref.key_id")
    _require(normalized["root_id"] != normalized["key_id"],
             "trust_root_ref root and key identities must be distinct")
    _require(normalized["algorithm"] == ALGORITHM,
             "trust_root_ref algorithm is unsupported")
    _sha256(normalized["public_key_sha256"], "trust_root_ref.public_key_sha256")
    _sha256(normalized["registry_sha256"], "trust_root_ref.registry_sha256")
    _epoch(normalized["epoch"], "trust_root_ref.epoch")
    return normalized


def _validate_receipt(value: Any) -> dict[str, Any]:
    _require_keys(value, RECEIPT_FIELDS, "one_shot_receipt")
    normalized = dict(value)
    _require(normalized["schema"] == RECEIPT_SCHEMA, "one_shot_receipt schema is unsupported")
    _require(normalized["record_id"] == RECEIPT_RECORD_ID,
             "one_shot_receipt record_id is unsupported")
    _uuid4(normalized["receipt_id"], "one_shot_receipt.receipt_id")
    _require(normalized["scope_id"] == SCOPE_ID, "one_shot_receipt scope differs from F8 R008")
    for field in ("pin_set_sha256", "host_identity_sha256", "consumption_binding_sha256"):
        _sha256(normalized[field], f"one_shot_receipt.{field}")
    _identifier(normalized["root_id"], "one_shot_receipt.root_id")
    _identifier(normalized["key_id"], "one_shot_receipt.key_id")
    _require(type(normalized["nonce_hex"]) is str and NONCE_RE.fullmatch(normalized["nonce_hex"]) is not None,
             "one_shot_receipt.nonce_hex is not lowercase 128-bit hex")
    _require(normalized["generation"] == 1,
             "one_shot_receipt generation must be the first consumed generation")
    _require(normalized["state"] == "consumed",
             "one_shot_receipt must be an externally recorded consumed receipt")
    _require(normalized["single_use"] is True, "one_shot_receipt must be single-use")
    _require(normalized["replay_policy"] == "reject_replay",
             "one_shot_receipt replay policy is not fail-closed")
    for field in ("issued_epoch", "consumed_epoch", "expires_epoch"):
        _epoch(normalized[field], f"one_shot_receipt.{field}")
    _require(normalized["issued_epoch"] < normalized["consumed_epoch"] < normalized["expires_epoch"],
             "one_shot_receipt epoch window is not ordered")
    expected = hashlib.sha256(_canonical(
        _receipt_consumption_payload(normalized), "one-shot receipt consumption payload"
    )).hexdigest()
    _require(normalized["consumption_binding_sha256"] == expected,
             "one_shot_receipt consumption binding does not match its transition")
    return normalized


def _validate_signature(value: Any) -> dict[str, Any]:
    _require_keys(value, SIGNATURE_FIELDS, "signature")
    normalized = dict(value)
    _require(normalized["algorithm"] == ALGORITHM, "signature algorithm is unsupported")
    _identifier(normalized["key_id"], "signature.key_id")
    _sha256(normalized["signed_payload_sha256"], "signature.signed_payload_sha256")
    _decode_base64(normalized["signature_base64"], size=64, label="signature")
    return normalized


def _validate_cross_bindings(
    value: Mapping[str, Any],
    anchor: Mapping[str, Any],
    target: Mapping[str, Any],
    source: Mapping[str, Any],
    build: Mapping[str, Any],
    runtime: Mapping[str, Any],
    host: Mapping[str, Any],
    root_ref: Mapping[str, Any],
    receipt: Mapping[str, Any],
) -> None:
    _require(root_ref == _anchor_projection(anchor),
             "trust_root_ref does not exactly bind the supplied trust anchor")
    _require(target["source_commit"] == source["source_commit"],
             "source commit is not cross-bound")
    _require(target["source_tree_sha256"] == source["source_tree_sha256"],
             "source tree SHA is not cross-bound")
    _require(target["uapi_sha256"] == source["uapi_sha256"],
             "UAPI SHA is not cross-bound")
    _require(target["arch"] == build["arch"] == runtime["arch"],
             "target/build/runtime architecture is not cross-bound")
    _require(target["config_sha256"] == build["config_sha256"] == runtime["config_sha256"],
             "target/build/runtime config SHA is not cross-bound")
    _require(
        target["kernel_image_sha256"]
        == build["binary_sha256"]
        == runtime["runtime_image_sha256"],
        "target/build/runtime kernel image SHA is not cross-bound",
    )
    _require(target["build_id"] == build["build_id"] == runtime["build_id"],
             "build identity is not cross-bound")
    _require(target["kernel_release"] == runtime["kernel_release"],
             "kernel release is not runtime-bound")
    _require(target["arch"] == runtime["arch"], "target arch is not runtime-bound")
    _require(target["syscall_policy_sha256"] == runtime["syscall_policy_sha256"],
             "syscall policy SHA is not runtime-bound")
    host_hash = hashlib.sha256(_canonical(host, "host identity payload")).hexdigest()
    _require(runtime["host_identity_sha256"] == host_hash,
             "runtime host identity is not bound to host_identity")
    pin_hash = _pin_set_digest(value)
    _require(receipt["pin_set_sha256"] == pin_hash,
             "one-shot receipt does not bind the complete pin set")
    _require(receipt["host_identity_sha256"] == host_hash,
             "one-shot receipt does not bind the host identity")
    _require(receipt["root_id"] == root_ref["root_id"] and receipt["key_id"] == root_ref["key_id"],
             "one-shot receipt trust-root/key binding differs")


def verify_attestation(
    attestation_raw: bytes,
    anchor_raw: bytes,
    *,
    trust_anchor_public_key: bytes | None = None,
) -> dict[str, Any]:
    """Verify one externally supplied attestation without authorizing execution."""

    _require(type(attestation_raw) is bytes and 0 < len(attestation_raw) <= MAX_JSON_BYTES,
             "attestation bytes are outside the bounded input limit")
    _require(type(anchor_raw) is bytes and 0 < len(anchor_raw) <= MAX_JSON_BYTES,
             "trust anchor bytes are outside the bounded input limit")
    try:
        value = strict_json_object(attestation_raw, label="trusted pin attestation",
                                   max_bytes=MAX_JSON_BYTES)
        anchor = strict_json_object(anchor_raw, label="trusted pin anchor",
                                    max_bytes=MAX_JSON_BYTES)
    except ValueError as error:
        raise _error(str(error), code="invalid_json") from error
    _require(_canonical(value, "trusted pin attestation") == attestation_raw,
             "attestation bytes are not exact canonical JSON", code="noncanonical_json")
    _require(_canonical(anchor, "trusted pin anchor") == anchor_raw,
             "trust anchor bytes are not exact canonical JSON", code="noncanonical_json")
    anchor, public_key = _validate_anchor(
        anchor,
        explicit_public_key=trust_anchor_public_key,
    )
    _require_keys(value, ATTESTATION_FIELDS, "trusted pin attestation")
    _require(value["schema"] == SCHEMA, "trusted pin attestation schema is unsupported")
    _require(value["record_id"] == RECORD_ID, "trusted pin attestation record_id is unsupported")
    _require(value["scope_id"] == SCOPE_ID, "trusted pin attestation scope differs from F8 R008")
    _require(value["evidence_origin"] == ATTESTATION_ORIGIN,
             "trusted pin attestation origin is not external")
    _require(value["synthetic"] is False,
             "synthetic target pin attestation is never admissible", code="synthetic_evidence")

    target = _validate_target_kernel(value["target_kernel"])
    source = _validate_source(value["source"])
    build = _validate_build(value["build"])
    runtime = _validate_runtime(value["runtime_abi"])
    host = _validate_host(value["host_identity"])
    root_ref = _validate_trust_root_ref(value["trust_root_ref"])
    receipt = _validate_receipt(value["one_shot_receipt"])
    signature = _validate_signature(value["signature"])
    _validate_cross_bindings(value, anchor, target, source, build, runtime, host, root_ref, receipt)
    _require(signature["key_id"] == root_ref["key_id"],
             "signature key_id differs from the pinned trust root key")
    signed_payload = _attestation_signing_payload(value)
    signed_payload_hash = hashlib.sha256(_canonical(
        signed_payload, "attestation signing payload"
    )).hexdigest()
    _require(signature["signed_payload_sha256"] == signed_payload_hash,
             "signature signed_payload_sha256 does not bind the attestation")
    signature_bytes = _decode_base64(signature["signature_base64"], size=64,
                                     label="signature")
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(
            signature_bytes, signing_message(value)
        )
    except (InvalidSignature, TypeError, ValueError) as error:
        raise _error("attestation signature is invalid for the supplied trust anchor",
                     code="invalid_signature") from error

    pin_hash = _pin_set_digest(value)
    host_hash = hashlib.sha256(_canonical(host, "host identity payload")).hexdigest()
    return {
        "schema": SCHEMA,
        "record_id": RECORD_ID,
        "status": STATUS_VALID_NON_AUTHORIZING,
        "scope_id": SCOPE_ID,
        "attestation_sha256": hashlib.sha256(attestation_raw).hexdigest(),
        "anchor_sha256": hashlib.sha256(anchor_raw).hexdigest(),
        "pin_set_sha256": pin_hash,
        "host_identity_sha256": host_hash,
        "trust_root_id": root_ref["root_id"],
        "trust_key_id": root_ref["key_id"],
        "arch": target["arch"],
        "receipt_id": receipt["receipt_id"],
        "kernel_release": target["kernel_release"],
        "build_id": target["build_id"],
        "runtime_abi_sha256": runtime["abi_payload_sha256"],
        "target_kernel_pin_complete": True,
        "source_pin_complete": True,
        "build_pin_complete": True,
        "runtime_abi_pin_complete": True,
        "host_identity_bound": True,
        "trust_root_key_bound": True,
        "signature_valid": True,
        "one_shot_receipt_bound": True,
        "one_shot_generation": receipt["generation"],
        "one_shot_state": receipt["state"],
        "production_trust_authenticated": False,
        "target_runtime_measured": False,
        "replay_ledger_observed": False,
        "execution_authority": False,
        "formal_admission": False,
        "readiness_pass": False,
        "T1_numerical": False,
        "qualification_credit": 0,
        "native_started": False,
        "solver_started": False,
        "worker_started": False,
        "gpu_started": False,
        "queue_started": False,
        "registry_mutation": 0,
        "ledger_mutation": 0,
        "gate_mutation": 0,
        "completion_mutation": 0,
    }


def _authorization() -> dict[str, Any]:
    return {
        "diagnostic_only": True,
        "capability_minted": False,
        "execution_authority": False,
        "formal_admission": False,
        "readiness_pass": False,
        "T1_numerical": False,
        "qualification_credit": 0,
    }


def _side_effects() -> dict[str, Any]:
    return {
        "attestation_read": False,
        "trust_anchor_read": False,
        "target_kernel_read": False,
        "source_tree_read": False,
        "build_artifact_read": False,
        "runtime_probe_started": False,
        "privileged_probe_started": False,
        "native_started": False,
        "solver_started": False,
        "worker_started": False,
        "gpu_started": False,
        "queue_started": False,
        "registry_mutation": 0,
        "ledger_mutation": 0,
        "gate_mutation": 0,
        "completion_mutation": 0,
    }


def _empty_pins() -> dict[str, bool]:
    return {name: False for name in PIN_NAMES}


def _empty_trust() -> dict[str, Any]:
    return {
        "anchor_bound": False,
        "signature_valid": False,
        "one_shot_receipt_bound": False,
        "production_trust_authenticated": False,
        "target_runtime_measured": False,
        "replay_ledger_observed": False,
        "synthetic": False,
    }


def _empty_identity() -> dict[str, Any]:
    return {
        "kernel_release": None,
        "arch": None,
        "build_id": None,
        "receipt_id": None,
        "runtime_abi_sha256": None,
        "host_identity_sha256": None,
        "trust_root_id": None,
        "trust_key_id": None,
        "pin_set_sha256": None,
    }


def _reference(path: Path, metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    if metadata is None:
        return _missing_reference(path)
    return dict(metadata)


def _blocked_report(
    attestation_path: Path,
    anchor_path: Path,
    *,
    status: str,
    blocker: str,
    attestation_ref: Mapping[str, Any] | None = None,
    anchor_ref: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    effects = _side_effects()
    effects["attestation_read"] = attestation_ref is not None
    effects["trust_anchor_read"] = anchor_ref is not None
    return {
        "schema": REPORT_SCHEMA,
        "record_id": REPORT_RECORD_ID,
        "status": status,
        "scope_id": SCOPE_ID,
        "inputs": {
            "attestation": _reference(attestation_path, attestation_ref),
            "trust_anchor": _reference(anchor_path, anchor_ref),
        },
        "pins": _empty_pins(),
        "trust": _empty_trust(),
        "identity": _empty_identity(),
        "validation": {
            "attestation_present": attestation_ref is not None,
            "trust_anchor_present": anchor_ref is not None,
            "schema_valid": False,
            "cross_bindings_valid": False,
            "target_kernel_pin_complete": False,
            "source_pin_complete": False,
            "build_pin_complete": False,
            "runtime_abi_pin_complete": False,
            "host_identity_bound": False,
            "blockers": [blocker],
        },
        "authorization": _authorization(),
        "side_effects": effects,
        "prohibited_operations": [
            "current_host_kernel_or_procfs_probe",
            "source_tree_or_build_artifact_read",
            "privileged_probe_or_root_escalation",
            "native_or_solver",
            "worker_gpu_or_queue",
            "registry_ledger_gate_completion_mutation",
        ],
    }


def _valid_report(
    attestation_path: Path,
    anchor_path: Path,
    attestation_ref: Mapping[str, Any],
    anchor_ref: Mapping[str, Any],
    result: Mapping[str, Any],
) -> dict[str, Any]:
    effects = _side_effects()
    effects["attestation_read"] = True
    effects["trust_anchor_read"] = True
    return {
        "schema": REPORT_SCHEMA,
        "record_id": REPORT_RECORD_ID,
        "status": STATUS_VALID_NON_AUTHORIZING,
        "scope_id": SCOPE_ID,
        "inputs": {
            "attestation": dict(attestation_ref),
            "trust_anchor": dict(anchor_ref),
        },
        "pins": {
            "target_kernel": True,
            "source": True,
            "build": True,
            "runtime_abi": True,
            "host_identity": True,
        },
        "trust": {
            "anchor_bound": True,
            "signature_valid": True,
            "one_shot_receipt_bound": True,
            "production_trust_authenticated": False,
            "target_runtime_measured": False,
            "replay_ledger_observed": False,
            "synthetic": False,
        },
        "identity": {
            "kernel_release": result["kernel_release"],
            "arch": result["arch"],
            "build_id": result["build_id"],
            "receipt_id": result["receipt_id"],
            "runtime_abi_sha256": result["runtime_abi_sha256"],
            "host_identity_sha256": result["host_identity_sha256"],
            "trust_root_id": result["trust_root_id"],
            "trust_key_id": result["trust_key_id"],
            "pin_set_sha256": result["pin_set_sha256"],
        },
        "validation": {
            "attestation_present": True,
            "trust_anchor_present": True,
            "schema_valid": True,
            "cross_bindings_valid": True,
            "target_kernel_pin_complete": True,
            "source_pin_complete": True,
            "build_pin_complete": True,
            "runtime_abi_pin_complete": True,
            "host_identity_bound": True,
            "blockers": [
                "production_trust_root_not_authenticated_by_this_non_authorizing_intake",
                "target_runtime_measurement_missing",
                "replay_ledger_observation_not_performed",
            ],
        },
        "authorization": _authorization(),
        "side_effects": effects,
        "prohibited_operations": [
            "current_host_kernel_or_procfs_probe",
            "source_tree_or_build_artifact_read",
            "privileged_probe_or_root_escalation",
            "native_or_solver",
            "worker_gpu_or_queue",
            "registry_ledger_gate_completion_mutation",
        ],
    }


def intake_paths(
    attestation_path: str | Path,
    anchor_path: str | Path,
    *,
    trust_anchor_public_key: bytes | None = None,
) -> dict[str, Any]:
    """Read and verify explicit attestation/anchor files without side effects."""

    attestation = _input_path(attestation_path)
    anchor = _input_path(anchor_path)
    try:
        attestation_value, attestation_ref, attestation_raw = _read_bounded_json(
            attestation, label="trusted pin attestation"
        )
    except TrustedTargetPinIntakeError as error:
        raise _error(
            str(error),
            code=error.code,
            reference=error.reference,
            input_label=error.input_label,
            attestation_ref=error.attestation_ref,
            anchor_ref=error.anchor_ref,
        ) from error
    try:
        anchor_value, anchor_ref, anchor_raw = _read_bounded_json(
            anchor, label="trusted pin anchor"
        )
    except TrustedTargetPinIntakeError as error:
        raise _error(
            str(error),
            code=error.code,
            reference=error.reference,
            input_label=error.input_label,
            attestation_ref=attestation_ref,
            anchor_ref=error.anchor_ref,
        ) from error
    # The in-memory values are intentionally not used for verification.  This
    # reuses the exact raw bytes that crossed the stable-FD boundary and makes
    # the path digest and signature digest refer to the same bytes.
    del attestation_value, anchor_value
    try:
        result = verify_attestation(
            attestation_raw,
            anchor_raw,
            trust_anchor_public_key=trust_anchor_public_key,
        )
    except TrustedTargetPinIntakeError as error:
        raise _error(
            str(error),
            code=error.code,
            attestation_ref=attestation_ref,
            anchor_ref=anchor_ref,
        ) from error
    return {
        "attestation_path": attestation,
        "anchor_path": anchor,
        "attestation_ref": attestation_ref,
        "anchor_ref": anchor_ref,
        "result": result,
    }


def build_report(
    attestation_path: str | Path = DEFAULT_ATTESTATION,
    anchor_path: str | Path = DEFAULT_TRUST_ANCHOR,
    *,
    trust_anchor_public_key: bytes | None = None,
) -> dict[str, Any]:
    """Build a deterministic blocked or non-authorizing intake report."""

    attestation = _input_path(attestation_path)
    anchor = _input_path(anchor_path)
    attestation_ref: dict[str, Any] | None = None
    anchor_ref: dict[str, Any] | None = None
    try:
        outcome = intake_paths(
            attestation,
            anchor,
            trust_anchor_public_key=trust_anchor_public_key,
        )
    except TrustedTargetPinIntakeError as error:
        attestation_ref = error.attestation_ref
        anchor_ref = error.anchor_ref
        if error.input_label == "trusted pin attestation":
            attestation_ref = error.reference
        elif error.input_label == "trusted pin anchor":
            anchor_ref = error.reference
        status = STATUS_BLOCKED_MISSING if error.code == "missing_file" else STATUS_BLOCKED_INVALID
        return _blocked_report(
            attestation,
            anchor,
            status=status,
            blocker=str(error),
            attestation_ref=attestation_ref,
            anchor_ref=anchor_ref,
        )
    return _valid_report(
        attestation,
        anchor,
        outcome["attestation_ref"],
        outcome["anchor_ref"],
        outcome["result"],
    )


def _validate_reference(value: Any, label: str) -> None:
    _require_keys(value, frozenset({"path", "exists", "bytes", "sha256"}), label)
    _require(type(value["path"]) is str and value["path"], f"{label}.path is malformed")
    _require(type(value["exists"]) is bool, f"{label}.exists must be boolean")
    if value["exists"]:
        _require(type(value["bytes"]) is int and 0 < value["bytes"] <= MAX_JSON_BYTES,
                 f"{label}.bytes is malformed")
        _sha256(value["sha256"], f"{label}.sha256")
    else:
        _require(value["bytes"] is None and value["sha256"] is None,
                 f"{label} missing reference contains partial metadata")


def _validate_report(value: Any) -> dict[str, Any]:
    expected = frozenset({
        "schema", "record_id", "status", "scope_id", "inputs", "pins", "trust",
        "identity", "validation", "authorization", "side_effects",
        "prohibited_operations",
    })
    _require_keys(value, expected, "trusted pin intake report")
    _require(value["schema"] == REPORT_SCHEMA, "report schema is unsupported")
    _require(value["record_id"] == REPORT_RECORD_ID, "report record_id is unsupported")
    _require(value["scope_id"] == SCOPE_ID, "report scope differs from F8 R008")
    _require(value["status"] in {STATUS_BLOCKED_MISSING, STATUS_BLOCKED_INVALID,
                                  STATUS_VALID_NON_AUTHORIZING},
             "report status is unsupported")
    _require_keys(value["inputs"], frozenset({"attestation", "trust_anchor"}), "report inputs")
    _validate_reference(value["inputs"]["attestation"], "report attestation input")
    _validate_reference(value["inputs"]["trust_anchor"], "report trust anchor input")
    _require_keys(value["pins"], frozenset(PIN_NAMES), "report pins")
    _require(all(type(item) is bool for item in value["pins"].values()),
             "report pin values must be booleans")
    trust_fields = frozenset({
        "anchor_bound", "signature_valid", "one_shot_receipt_bound",
        "production_trust_authenticated", "target_runtime_measured",
        "replay_ledger_observed", "synthetic",
    })
    _require_keys(value["trust"], trust_fields, "report trust")
    _require(all(type(item) is bool for item in value["trust"].values()),
             "report trust values must be booleans")
    identity_fields = frozenset({
        "kernel_release", "arch", "build_id", "receipt_id", "runtime_abi_sha256",
        "host_identity_sha256", "trust_root_id", "trust_key_id", "pin_set_sha256",
    })
    _require_keys(value["identity"], identity_fields, "report identity")
    validation_fields = frozenset({
        "attestation_present", "trust_anchor_present", "schema_valid",
        "cross_bindings_valid", "target_kernel_pin_complete", "source_pin_complete",
        "build_pin_complete", "runtime_abi_pin_complete", "host_identity_bound",
        "blockers",
    })
    _require_keys(value["validation"], validation_fields, "report validation")
    _require(all(type(value["validation"][field]) is bool for field in validation_fields - {"blockers"}),
             "report validation flags must be booleans")
    _require(type(value["validation"]["blockers"]) is list
             and all(type(item) is str and item for item in value["validation"]["blockers"]),
             "report validation blockers must be non-empty strings")
    _require(value["authorization"] == _authorization(),
             "report authorization boundary was promoted")
    _require(value["side_effects"] == _side_effects(),
             "report side effects are not the fixed read-only boundary")
    _require(type(value["prohibited_operations"]) is list
             and value["prohibited_operations"] == [
                 "current_host_kernel_or_procfs_probe",
                 "source_tree_or_build_artifact_read",
                 "privileged_probe_or_root_escalation",
                 "native_or_solver",
                 "worker_gpu_or_queue",
                 "registry_ledger_gate_completion_mutation",
             ],
             "report prohibited operation set drifted")

    if value["status"] == STATUS_VALID_NON_AUTHORIZING:
        _require(value["pins"] == {name: True for name in PIN_NAMES},
                 "valid report does not close all pin domains")
        _require(value["trust"] == {
            "anchor_bound": True,
            "signature_valid": True,
            "one_shot_receipt_bound": True,
            "production_trust_authenticated": False,
            "target_runtime_measured": False,
            "replay_ledger_observed": False,
            "synthetic": False,
        }, "valid report trust projection is unsafe")
        _require(value["identity"]["kernel_release"] is not None
                 and value["identity"]["arch"] == TARGET_ARCH
                 and value["identity"]["build_id"] is not None
                 and value["identity"]["receipt_id"] is not None,
                 "valid report identity is incomplete")
        _require(all(value["validation"][field] for field in (
            "attestation_present", "trust_anchor_present", "schema_valid",
            "cross_bindings_valid", "target_kernel_pin_complete", "source_pin_complete",
            "build_pin_complete", "runtime_abi_pin_complete", "host_identity_bound",
        )), "valid report validation is incomplete")
        _require(value["authorization"]["qualification_credit"] == 0,
                 "valid intake report cannot mint credit")
    else:
        _require(value["pins"] == _empty_pins(), "blocked report contains promoted pins")
        _require(value["trust"] == _empty_trust(), "blocked report contains promoted trust")
        _require(value["identity"] == _empty_identity(), "blocked report contains promoted identity")
        _require(value["validation"]["blockers"], "blocked report must explain its blocker")
        _require(not any(value["validation"][field] for field in (
            "schema_valid", "cross_bindings_valid", "target_kernel_pin_complete",
            "source_pin_complete", "build_pin_complete", "runtime_abi_pin_complete",
            "host_identity_bound",
        )), "blocked report contains a closed validation field")
    return value


def verify_report(
    path: str | Path = DEFAULT_REPORT,
    *,
    trust_anchor_public_key: bytes | None = None,
) -> dict[str, Any]:
    report_path = _input_path(path)
    value, _reference_value, _raw = _read_bounded_json(
        report_path, label="trusted pin intake report", require_canonical=False
    )
    validated = _validate_report(value)
    expected = build_report(
        value["inputs"]["attestation"]["path"],
        value["inputs"]["trust_anchor"]["path"],
        trust_anchor_public_key=trust_anchor_public_key,
    )
    _require(
        validated == expected,
        "trusted pin intake report does not match its current bound inputs",
        code="report_binding_drift",
    )
    return validated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--print-report", action="store_true",
                       help="print the default blocked/non-authorizing report")
    group.add_argument("--intake", metavar="ATTESTATION",
                       help="intake an explicit external attestation")
    group.add_argument("--verify-report", nargs="?", const=DEFAULT_REPORT.as_posix(),
                       metavar="REPORT", help="verify a machine report")
    parser.add_argument("--trust-anchor", metavar="ANCHOR",
                        help="trust-root record used with --intake")
    parser.add_argument(
        "--trust-anchor-public-key-hex",
        metavar="HEX",
        help="explicit out-of-band raw Ed25519 trust-anchor public key (64 lowercase hex)",
    )
    args = parser.parse_args()
    explicit_key = None
    if args.trust_anchor_public_key_hex is not None:
        if PUBLIC_KEY_HEX_RE.fullmatch(args.trust_anchor_public_key_hex) is None:
            parser.error("--trust-anchor-public-key-hex must be exactly 64 lowercase hex characters")
        explicit_key = bytes.fromhex(args.trust_anchor_public_key_hex)
    if args.print_report:
        value = build_report()
    elif args.intake:
        if not args.trust_anchor:
            parser.error("--intake requires --trust-anchor")
        value = build_report(
            args.intake,
            args.trust_anchor,
            trust_anchor_public_key=explicit_key,
        )
    else:
        value = verify_report(
            args.verify_report,
            trust_anchor_public_key=explicit_key,
        )
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ABI_SCHEMA",
    "ANCHOR_SCHEMA",
    "DEFAULT_REPORT",
    "REPORT_SCHEMA",
    "SCHEMA",
    "SCOPE_ID",
    "STATUS_BLOCKED_INVALID",
    "STATUS_BLOCKED_MISSING",
    "STATUS_VALID_NON_AUTHORIZING",
    "TrustedTargetPinIntakeError",
    "build_report",
    "signing_message",
    "verify_attestation",
    "verify_report",
]
