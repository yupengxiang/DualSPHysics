#!/usr/bin/env python3
"""Fail-closed intake for real F8/R008 target-kernel provenance.

The intake accepts exactly one external JSON manifest and four small regular
files: a source-tree evidence artifact, a UAPI evidence artifact, a kernel
config, and a build evidence artifact.  It authenticates only bytes and
declared identities.  It never treats the repository's upstream Linux audit,
the host's Ubuntu headers, a synthetic digest, or an upstream tag as a target
kernel pin.

Every input is read through an O_NOFOLLOW descriptor, requires one hard-link,
is bounded by a fixed small-file limit, and is checked for descriptor/path
identity stability before the descriptor is closed.  JSON is UTF-8 strict and
rejects duplicate object keys and non-standard constants.  No kernel, native
binary, worker, GPU, queue, gate, ledger, registry, or PLAN operation is
performed by this module.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any


LAB_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = Path("external/f8-r008-target-kernel-evidence-manifest-v1.json")
DEFAULT_REPORT = Path("reports/F8-R008-TARGET-KERNEL-EVIDENCE-INTAKE-V1.json")

MANIFEST_SCHEMA = "core.cfd.f8.r008.target_kernel_evidence_manifest.v1"
REPORT_SCHEMA = "core.cfd.f8.r008.target_kernel_evidence_intake_report.v1"
MANIFEST_RECORD_ID = "f8-r008-target-kernel-evidence-manifest-v1"
REPORT_RECORD_ID = "f8-r008-target-kernel-evidence-intake-report-v1"
MANIFEST_ORIGIN = "external_target_kernel_evidence"
STATUS_BLOCKED_MISSING = "blocked_missing_external_target_evidence"
STATUS_BLOCKED_INVALID = "blocked_invalid_external_target_evidence"
STATUS_VALID_NON_AUTHORIZING = "external_target_evidence_intake_valid_non_authorizing"

MAX_MANIFEST_BYTES = 512 * 1024
MAX_SMALL_FILE_BYTES = 8 * 1024 * 1024
MAX_REFERENCE_LENGTH = 512
ARTIFACT_ROLES = ("source", "uapi", "config", "build")
MANIFEST_FIELDS = {
    "schema", "record_id", "evidence_origin", "synthetic", "target", "artifacts",
}
TARGET_FIELDS = {
    "kernel_release", "source_commit", "source_tree_sha256", "uapi_sha256",
    "build_id", "config_sha256", "required_options",
}
ARTIFACT_FIELDS = set(ARTIFACT_ROLES)
REFERENCE_FIELDS = {"path", "bytes", "sha256"}
PIN_FIELDS = {
    "kernel_release_pinned", "source_commit_pinned", "source_tree_pinned",
    "uapi_pinned", "config_pinned", "build_id_pinned",
}

SHA256 = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
SHA1 = re.compile(r"[0-9a-f]{40}\Z", re.ASCII)
BUILD_ID = re.compile(r"[0-9a-f]{16,128}\Z", re.ASCII)
OPTION_NAME = re.compile(r"CONFIG_[A-Z0-9_]+\Z", re.ASCII)
RELEASE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+:-]{0,127}\Z", re.ASCII)
REFERENCE = re.compile(r"[A-Za-z0-9._+@%=-]+(?:/[A-Za-z0-9._+@%=-]+)*\Z", re.ASCII)

# These are the minimum F8/R008 options that must be declared by an external
# target manifest.  The x32 ABI is intentionally required to be disabled for
# this contract's target syscall policy boundary.
REQUIRED_OPTION_VALUES = {
    "CONFIG_FANOTIFY": "y",
    "CONFIG_FANOTIFY_ACCESS_PERMISSIONS": "y",
    "CONFIG_SECCOMP": "y",
    "CONFIG_SECCOMP_FILTER": "y",
    "CONFIG_X86_X32_ABI": "n",
}

# The existing repository audit contains these upstream v6.8 object/commit
# identities.  They are reference-only and can never satisfy target pinning.
UPSTREAM_V6_8_IDENTITIES = {
    "90d1f30371ae3337beb01666b226320728d35c70",  # annotated tag object
    "e8f897f4afef0031fe618a8e94127a0934896aba",  # peeled commit
}
UPSTREAM_TAG_RELEASES = {"v6.8", "6.8", "linux-v6.8", "linux-6.8"}
PLACEHOLDER_WORDS = (
    "synthetic", "placeholder", "dummy", "example", "fake", "unknown",
    "todo", "pending", "test-only",
)
REPEATING_DIGEST_UNITS = (
    "0123456789abcdef", "abcdef", "deadbeef", "cafebabe", "feedface",
    "1234567890",
)

O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)


class TargetKernelEvidenceIntakeError(ValueError):
    """The external target-kernel evidence is missing, unsafe, or malformed."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "invalid_external_target_evidence",
        reference: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.reference = reference


def _error(
    message: str,
    *,
    code: str = "invalid_external_target_evidence",
    reference: dict[str, Any] | None = None,
) -> TargetKernelEvidenceIntakeError:
    return TargetKernelEvidenceIntakeError(message, code=code, reference=reference)


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _error(f"duplicate JSON object key: {key}", code="duplicate_json_key")
        result[key] = value
    return result


def _reject_constant(token: str) -> Any:
    raise _error(
        f"non-standard JSON constant is not permitted: {token}",
        code="non_strict_json",
    )


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


def _assert_no_symlink_components(path: Path, label: str) -> None:
    """Reject symlinks in every existing component without resolving them."""

    absolute = Path(os.path.abspath(os.fspath(path)))
    current = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        current /= component
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            # A missing parent will make the eventual open fail closed.  There
            # cannot be a reachable child below a missing component.
            continue
        except OSError as error:
            raise _error(f"could not inspect {label} path components: {path}") from error
        if stat.S_ISLNK(info.st_mode):
            raise _error(f"{label} path contains a symlink: {path}", code="symlink_path")


def _read_bounded(path: Path, *, label: str, limit: int) -> tuple[bytes, dict[str, Any]]:
    """Read one small, single-link regular file through a stable FD."""

    _assert_no_symlink_components(path, label)
    descriptor: int | None = None
    try:
        descriptor = os.open(os.fspath(path), os.O_RDONLY | O_NOFOLLOW | O_CLOEXEC)
    except FileNotFoundError as error:
        raise _error(f"{label} is missing: {_display_path(path)}", code="missing_file") from error
    except OSError as error:
        raise _error(f"{label} cannot be opened safely: {_display_path(path)}") from error

    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise _error(f"{label} must be a regular file: {_display_path(path)}", code="not_regular_file")
        if before.st_nlink != 1:
            raise _error(f"{label} must have exactly one hard link: {_display_path(path)}", code="hardlink")
        if before.st_size > limit:
            raise _error(f"{label} exceeds the {limit}-byte bound: {_display_path(path)}", code="oversize")

        chunks: list[bytes] = []
        total = 0
        while True:
            remaining = limit + 1 - total
            block = os.read(descriptor, min(1024 * 1024, remaining))
            if not block:
                break
            total += len(block)
            if total > limit:
                raise _error(f"{label} exceeds the {limit}-byte bound: {_display_path(path)}", code="oversize")
            chunks.append(block)

        after = os.fstat(descriptor)
        try:
            named = os.stat(path, follow_symlinks=False)
        except OSError as error:
            raise _error(f"{label} disappeared while being read: {_display_path(path)}", code="drift") from error
        if (
            _identity(before) != _identity(after)
            or _identity(after) != _identity(named)
            or total != before.st_size
        ):
            raise _error(f"{label} changed while being read: {_display_path(path)}", code="drift")

        payload = b"".join(chunks)
        return payload, {
            "bytes": total,
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    except TargetKernelEvidenceIntakeError:
        raise
    except OSError as error:
        raise _error(f"{label} could not be read safely: {_display_path(path)}") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _read_json(path: Path, *, label: str, limit: int) -> tuple[dict[str, Any], dict[str, Any]]:
    raw, reference = _read_bounded(path, label=label, limit=limit)
    try:
        decoded = raw.decode("utf-8", errors="strict")
        value = json.loads(
            decoded,
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except TargetKernelEvidenceIntakeError as error:
        raise _error(str(error), code=error.code, reference=reference) from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _error(
            f"{label} is not strict UTF-8 JSON: {path}",
            code="invalid_json",
            reference=reference,
        ) from error
    if not isinstance(value, dict):
        raise _error(
            f"{label} must be a JSON object: {path}",
            code="json_not_object",
            reference=reference,
        )
    return value, reference


def _display_path(path: Path) -> str:
    absolute = Path(os.path.abspath(os.fspath(path)))
    try:
        return absolute.relative_to(LAB_ROOT).as_posix()
    except ValueError:
        return absolute.as_posix()


def _manifest_path(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        if any(part in {"", ".", ".."} for part in path.parts):
            raise _error("manifest path must not contain traversal components", code="path_traversal")
        path = LAB_ROOT / path
    return path


def _require_keys(value: Any, expected: set[str], label: str) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise _error(f"{label} must contain exactly {sorted(expected)}")


def _reject_placeholder_text(value: str, label: str) -> None:
    lowered = value.casefold()
    if any(token in lowered for token in PLACEHOLDER_WORDS):
        raise _error(f"{label} contains a synthetic/placeholder marker", code="placeholder")


def _is_repeating_digest(value: str) -> bool:
    if len(set(value)) == 1:
        return True
    for unit in REPEATING_DIGEST_UNITS:
        candidate = (unit * ((len(value) // len(unit)) + 1))[: len(value)]
        if candidate == value:
            return True
    return False


def _digest(value: Any, label: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise _error(f"{label} must be a lowercase hexadecimal digest")
    if _is_repeating_digest(value):
        raise _error(f"{label} is a synthetic/placeholder digest", code="placeholder_hash")
    return value


def _reference_path(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= MAX_REFERENCE_LENGTH
        or "\\" in value
        or "\x00" in value
        or value.startswith("/")
        or "//" in value
        or REFERENCE.fullmatch(value) is None
    ):
        raise _error(f"{label} must be a canonical relative reference", code="path_traversal")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise _error(f"{label} must be a canonical relative reference without traversal", code="path_traversal")
    _reject_placeholder_text(value, label)
    return value


def _validate_artifact_reference(value: Any, role: str) -> dict[str, Any]:
    _require_keys(value, REFERENCE_FIELDS, f"{role} artifact reference")
    path = _reference_path(value["path"], f"{role} artifact path")
    byte_count = value["bytes"]
    if type(byte_count) is not int or not 1 <= byte_count <= MAX_SMALL_FILE_BYTES:
        raise _error(f"{role} artifact bytes are outside the bounded domain")
    digest = _digest(value["sha256"], f"{role} artifact sha256", SHA256)
    return {"path": path, "bytes": byte_count, "sha256": digest}


def _validate_required_options(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list) or not 1 <= len(value) <= 128:
        raise _error("required_options must be a bounded non-empty list")
    names: list[str] = []
    normalized: list[dict[str, str]] = []
    for index, item in enumerate(value):
        _require_keys(item, {"name", "value"}, f"required_options[{index}]")
        name = item["name"]
        option_value = item["value"]
        if not isinstance(name, str) or OPTION_NAME.fullmatch(name) is None:
            raise _error(f"required_options[{index}].name is malformed")
        if option_value not in {"y", "m", "n"}:
            raise _error(f"required_options[{index}].value must be y, m, or n")
        names.append(name)
        normalized.append({"name": name, "value": option_value})
    if names != sorted(names) or len(set(names)) != len(names):
        raise _error("required_options must be sorted and unique")
    observed = {item["name"]: item["value"] for item in normalized}
    missing = sorted(set(REQUIRED_OPTION_VALUES) - set(observed))
    if missing:
        raise _error(f"required_options omit mandatory F8/R008 options: {missing}")
    mismatched = {
        name: (observed[name], expected)
        for name, expected in REQUIRED_OPTION_VALUES.items()
        if observed[name] != expected
    }
    if mismatched:
        raise _error(f"required_options have unsafe mandatory values: {mismatched}")
    return normalized


def _validate_target(value: Any) -> dict[str, Any]:
    _require_keys(value, TARGET_FIELDS, "target")
    release = value["kernel_release"]
    if not isinstance(release, str) or RELEASE.fullmatch(release) is None:
        raise _error("target.kernel_release is malformed")
    _reject_placeholder_text(release, "target.kernel_release")
    if release in UPSTREAM_TAG_RELEASES:
        raise _error("an upstream v6.8 tag cannot masquerade as the target release", code="upstream_tag")

    source_commit = _digest(value["source_commit"], "target.source_commit", SHA1)
    if source_commit in UPSTREAM_V6_8_IDENTITIES:
        raise _error("an upstream v6.8 object cannot masquerade as the target source commit", code="upstream_tag")
    source_tree = _digest(value["source_tree_sha256"], "target.source_tree_sha256", SHA256)
    uapi = _digest(value["uapi_sha256"], "target.uapi_sha256", SHA256)
    config = _digest(value["config_sha256"], "target.config_sha256", SHA256)
    build_id = value["build_id"]
    if not isinstance(build_id, str) or BUILD_ID.fullmatch(build_id) is None:
        raise _error("target.build_id must be lowercase hexadecimal")
    if _is_repeating_digest(build_id):
        raise _error("target.build_id is a synthetic/placeholder digest", code="placeholder_hash")

    return {
        "kernel_release": release,
        "source_commit": source_commit,
        "source_tree_sha256": source_tree,
        "uapi_sha256": uapi,
        "build_id": build_id,
        "config_sha256": config,
        "required_options": _validate_required_options(value["required_options"]),
    }


def _validate_manifest(value: Any) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    _require_keys(value, MANIFEST_FIELDS, "evidence manifest")
    if value["schema"] != MANIFEST_SCHEMA or value["record_id"] != MANIFEST_RECORD_ID:
        raise _error("evidence manifest identity is not the pinned V1 contract")
    if value["evidence_origin"] != MANIFEST_ORIGIN:
        raise _error("evidence manifest origin is not external target-kernel evidence")
    if value["synthetic"] is not False:
        raise _error("synthetic evidence is never admissible", code="synthetic_evidence")
    target = _validate_target(value["target"])
    _require_keys(value["artifacts"], ARTIFACT_FIELDS, "artifacts")
    artifacts = {
        role: _validate_artifact_reference(value["artifacts"][role], role)
        for role in ARTIFACT_ROLES
    }
    paths = [item["path"] for item in artifacts.values()]
    if len(set(paths)) != len(paths):
        raise _error("source/UAPI/config/build artifact paths must be distinct", code="duplicate_artifact")
    return target, artifacts


def _safe_artifact_path(manifest_path: Path, relative: str) -> Path:
    candidate = manifest_path.parent / Path(relative)
    if os.path.normpath(os.fspath(candidate)) == os.path.normpath(os.fspath(manifest_path)):
        raise _error("an artifact reference may not point to the evidence manifest", code="duplicate_artifact")
    return candidate


def _parse_config(raw: bytes, target: dict[str, Any]) -> None:
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise _error("config artifact is not strict UTF-8 text", code="invalid_config") from error
    found: dict[str, str] = {}
    assignment = re.compile(r"(CONFIG_[A-Z0-9_]+)=(y|m|n)\Z")
    unset = re.compile(r"# (CONFIG_[A-Z0-9_]+) is not set\Z")
    for line in text.splitlines():
        match = assignment.fullmatch(line) or unset.fullmatch(line)
        if match is None:
            continue
        name = match.group(1)
        option_value = match.group(2) if "=" in line else "n"
        if name in found:
            raise _error(f"config artifact repeats {name}", code="duplicate_config_option")
        found[name] = option_value
    for option in target["required_options"]:
        name = option["name"]
        expected = option["value"]
        if found.get(name) != expected:
            raise _error(
                f"config artifact does not prove {name}={expected}",
                code="config_option_mismatch",
            )


def _strict_json_artifact_check(raw: bytes, path: str) -> None:
    if not path.casefold().endswith(".json"):
        return
    try:
        json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except TargetKernelEvidenceIntakeError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _error(f"JSON-named artifact is not strict JSON: {path}", code="invalid_json") from error


def _empty_artifact_report() -> dict[str, Any]:
    return {
        "path": None,
        "declared_bytes": None,
        "declared_sha256": None,
        "observed_bytes": None,
        "observed_sha256": None,
        "verified": False,
    }


def _empty_target() -> dict[str, Any]:
    return {
        "kernel_release": None,
        "source_commit": None,
        "source_tree_sha256": None,
        "uapi_sha256": None,
        "build_id": None,
        "config_sha256": None,
        "required_options": [],
    }


def _empty_pins() -> dict[str, bool]:
    return {field: False for field in sorted(PIN_FIELDS)}


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
        "kernel_started": False,
        "native_started": False,
        "worker_started": False,
        "gpu_started": False,
        "queue_started": False,
        "gate_mutation": 0,
        "ledger_mutation": 0,
        "registry_mutation": 0,
        "plan_mutation": 0,
    }


def _manifest_ref(path: Path, reference: dict[str, Any] | None = None) -> dict[str, Any]:
    if reference is None:
        return {"path": _display_path(path), "exists": False, "bytes": None, "sha256": None}
    return {
        "path": _display_path(path),
        "exists": True,
        "bytes": reference["bytes"],
        "sha256": reference["sha256"],
    }


def _blocked_report(
    manifest_path: Path,
    *,
    status: str,
    blocker: str,
    manifest_reference: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema": REPORT_SCHEMA,
        "record_id": REPORT_RECORD_ID,
        "status": status,
        "manifest": _manifest_ref(manifest_path, manifest_reference),
        "declared_target": _empty_target(),
        "artifacts": {role: _empty_artifact_report() for role in ARTIFACT_ROLES},
        "validation": {
            "manifest_present": manifest_reference is not None,
            "manifest_valid": False,
            "artifact_files_verified": False,
            "external_target_evidence_complete": False,
            "blockers": [blocker],
        },
        "pins": _empty_pins(),
        "authorization": _authorization(),
        "side_effects": _side_effects(),
    }


def _valid_report(
    manifest_path: Path,
    manifest_reference: dict[str, Any],
    target: dict[str, Any],
    artifacts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    artifact_projection: dict[str, dict[str, Any]] = {}
    for role in ARTIFACT_ROLES:
        declared = artifacts[role]["declared"]
        observed = artifacts[role]["observed"]
        artifact_projection[role] = {
            "path": declared["path"],
            "declared_bytes": declared["bytes"],
            "declared_sha256": declared["sha256"],
            "observed_bytes": observed["bytes"],
            "observed_sha256": observed["sha256"],
            "verified": True,
        }
    return {
        "schema": REPORT_SCHEMA,
        "record_id": REPORT_RECORD_ID,
        "status": STATUS_VALID_NON_AUTHORIZING,
        "manifest": _manifest_ref(manifest_path, manifest_reference),
        "declared_target": target,
        "artifacts": artifact_projection,
        "validation": {
            "manifest_present": True,
            "manifest_valid": True,
            "artifact_files_verified": True,
            "external_target_evidence_complete": True,
            "blockers": [],
        },
        "pins": {field: True for field in sorted(PIN_FIELDS)},
        "authorization": _authorization(),
        "side_effects": _side_effects(),
    }


def intake_manifest(path: str | Path) -> dict[str, Any]:
    """Validate one external manifest and all four referenced artifacts."""

    manifest_path = _manifest_path(path)
    manifest, manifest_reference = _read_json(
        manifest_path,
        label="external evidence manifest",
        limit=MAX_MANIFEST_BYTES,
    )
    try:
        target, artifacts = _validate_manifest(manifest)
        artifact_results: dict[str, dict[str, Any]] = {}
        for role in ARTIFACT_ROLES:
            declared = artifacts[role]
            artifact_path = _safe_artifact_path(manifest_path, declared["path"])
            raw, observed = _read_bounded(
                artifact_path,
                label=f"{role} evidence artifact",
                limit=MAX_SMALL_FILE_BYTES,
            )
            if observed["bytes"] != declared["bytes"] or observed["sha256"] != declared["sha256"]:
                raise _error(
                    f"{role} evidence artifact bytes/SHA drift from the manifest",
                    code="drift",
                )
            if role == "config":
                _parse_config(raw, target)
            _strict_json_artifact_check(raw, declared["path"])
            artifact_results[role] = {"declared": declared, "observed": observed}

        # These three identity fields are intentionally tied to the bytes that
        # were actually read.  The build ID is declared independently because
        # the build evidence artifact may be an external provenance record
        # rather than an executable image; it is still byte/SHA verified above.
        for role, target_key in (
            ("source", "source_tree_sha256"),
            ("uapi", "uapi_sha256"),
            ("config", "config_sha256"),
        ):
            if target[target_key] != artifact_results[role]["observed"]["sha256"]:
                raise _error(
                    f"target.{target_key} does not match the verified {role} artifact",
                    code="identity_mismatch",
                )
    except TargetKernelEvidenceIntakeError as error:
        if error.reference is None:
            raise _error(str(error), code=error.code, reference=manifest_reference) from error
        raise
    return {
        "manifest_path": manifest_path,
        "manifest_reference": manifest_reference,
        "target": target,
        "artifacts": artifact_results,
    }


def build_report(path: str | Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    """Build a deterministic non-authorizing report for the supplied manifest."""

    manifest_path = _manifest_path(path)
    try:
        result = intake_manifest(manifest_path)
    except TargetKernelEvidenceIntakeError as error:
        status = (
            STATUS_BLOCKED_MISSING
            if error.code in {"missing_file", "missing_artifact", "partial_evidence"}
            else STATUS_BLOCKED_INVALID
        )
        return _blocked_report(
            manifest_path,
            status=status,
            blocker=str(error),
            manifest_reference=error.reference,
        )
    return _valid_report(
        manifest_path,
        result["manifest_reference"],
        result["target"],
        result["artifacts"],
    )


def _validate_report(value: Any) -> dict[str, Any]:
    expected = {
        "schema", "record_id", "status", "manifest", "declared_target", "artifacts",
        "validation", "pins", "authorization", "side_effects",
    }
    _require_keys(value, expected, "intake report")
    if value["schema"] != REPORT_SCHEMA or value["record_id"] != REPORT_RECORD_ID:
        raise _error("intake report identity is malformed")
    if value["status"] not in {STATUS_BLOCKED_MISSING, STATUS_BLOCKED_INVALID, STATUS_VALID_NON_AUTHORIZING}:
        raise _error("intake report status is not recognized")

    _require_keys(value["manifest"], {"path", "exists", "bytes", "sha256"}, "report manifest")
    if not isinstance(value["manifest"]["path"], str) or not value["manifest"]["path"]:
        raise _error("report manifest path is malformed")
    if type(value["manifest"]["exists"]) is not bool:
        raise _error("report manifest exists must be boolean")
    if value["manifest"]["exists"]:
        if type(value["manifest"]["bytes"]) is not int or value["manifest"]["bytes"] < 1:
            raise _error("present report manifest must declare bounded bytes")
        _digest(value["manifest"]["sha256"], "report manifest sha256", SHA256)
    elif value["manifest"]["bytes"] is not None or value["manifest"]["sha256"] is not None:
        raise _error("missing report manifest must not contain partial metadata")

    _require_keys(value["declared_target"], TARGET_FIELDS, "report declared_target")
    if value["status"] != STATUS_VALID_NON_AUTHORIZING and value["declared_target"] != _empty_target():
        raise _error("blocked report cannot retain partial target identity")
    _require_keys(value["artifacts"], ARTIFACT_FIELDS, "report artifacts")
    for role in ARTIFACT_ROLES:
        _require_keys(
            value["artifacts"][role],
            {"path", "declared_bytes", "declared_sha256", "observed_bytes", "observed_sha256", "verified"},
            f"report artifact {role}",
        )
        item = value["artifacts"][role]
        if type(item["verified"]) is not bool:
            raise _error(f"report artifact {role}.verified must be boolean")
        if item["verified"]:
            _reference_path(item["path"], f"report artifact {role}.path")
            if type(item["declared_bytes"]) is not int or not 1 <= item["declared_bytes"] <= MAX_SMALL_FILE_BYTES:
                raise _error(f"report artifact {role} declared bytes are malformed")
            if type(item["observed_bytes"]) is not int or item["observed_bytes"] != item["declared_bytes"]:
                raise _error(f"report artifact {role} observed bytes are not bound")
            declared_hash = _digest(item["declared_sha256"], f"report artifact {role} declared sha256", SHA256)
            observed_hash = _digest(item["observed_sha256"], f"report artifact {role} observed sha256", SHA256)
            if declared_hash != observed_hash:
                raise _error(f"report artifact {role} SHA is not bound")
        elif any(item[field] is not None for field in ("path", "declared_bytes", "declared_sha256", "observed_bytes", "observed_sha256")):
            raise _error(f"blocked report artifact {role} contains partial evidence")

    _require_keys(
        value["validation"],
        {"manifest_present", "manifest_valid", "artifact_files_verified", "external_target_evidence_complete", "blockers"},
        "report validation",
    )
    validation = value["validation"]
    if not all(type(validation[field]) is bool for field in (
        "manifest_present", "manifest_valid", "artifact_files_verified", "external_target_evidence_complete",
    )):
        raise _error("report validation flags must be boolean")
    if not isinstance(validation["blockers"], list) or any(not isinstance(item, str) or not item for item in validation["blockers"]):
        raise _error("report blockers must be a list of non-empty strings")

    _require_keys(value["pins"], PIN_FIELDS, "report pins")
    if any(type(value["pins"][field]) is not bool for field in PIN_FIELDS):
        raise _error("report pins must be boolean")
    _require_keys(value["authorization"], set(_authorization()), "report authorization")
    if value["authorization"] != _authorization():
        raise _error("report authorization boundary was promoted")
    _require_keys(value["side_effects"], set(_side_effects()), "report side effects")
    if value["side_effects"] != _side_effects():
        raise _error("report side effects show an unauthorized operation")

    if value["status"] == STATUS_VALID_NON_AUTHORIZING:
        normalized_target = _validate_target(value["declared_target"])
        if not (
            validation["manifest_present"]
            and validation["manifest_valid"]
            and validation["artifact_files_verified"]
            and validation["external_target_evidence_complete"]
            and validation["blockers"] == []
            and all(value["pins"].values())
        ):
            raise _error("valid intake report is not complete")
        for role, target_key in (
            ("source", "source_tree_sha256"),
            ("uapi", "uapi_sha256"),
            ("config", "config_sha256"),
        ):
            if value["artifacts"][role]["observed_sha256"] != normalized_target[target_key]:
                raise _error(f"valid report {role} artifact is not bound to the target identity")
    else:
        if validation["external_target_evidence_complete"] or any(value["pins"].values()):
            raise _error("blocked report cannot claim complete evidence or target pins")
        if not validation["blockers"]:
            raise _error("blocked report must explain its blocker")
    if value["authorization"]["readiness_pass"] or value["authorization"]["T1_numerical"] or value["authorization"]["qualification_credit"] != 0:
        raise _error("intake report cannot mint readiness, T1, or credit")
    return value


def verify_report(path: str | Path = DEFAULT_REPORT) -> dict[str, Any]:
    report_path = Path(path)
    if not report_path.is_absolute():
        report_path = LAB_ROOT / report_path
    value, _ = _read_json(report_path, label="machine intake report", limit=MAX_MANIFEST_BYTES)
    return _validate_report(value)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--print-report", action="store_true", help="print the current default intake report")
    group.add_argument("--intake", metavar="MANIFEST", help="intake a supplied external evidence manifest")
    group.add_argument(
        "--verify-report",
        nargs="?",
        const=DEFAULT_REPORT.as_posix(),
        metavar="REPORT",
        help="verify the checked-in machine report or a supplied report",
    )
    args = parser.parse_args()
    if args.print_report:
        value = build_report()
    elif args.intake:
        value = build_report(args.intake)
    else:
        value = verify_report(args.verify_report)
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
