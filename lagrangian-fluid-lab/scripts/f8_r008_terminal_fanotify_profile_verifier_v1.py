#!/usr/bin/env python3
"""Validate the proposal-only, static F8 R008 fanotify profile manifest."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any

LAB = Path(__file__).resolve().parents[1]
MANIFEST = Path("reports/F8-R008-TERMINAL-FANOTIFY-PROFILES-V1-2026-09-27.json")
V17 = Path("reports/F8-R008-TERMINAL-COMPLETION-EVIDENCE-CONTRACT-V17-2026-09-26.zh-CN.md")
V18 = Path("reports/F8-R008-TERMINAL-COMPLETION-EVIDENCE-CONTRACT-V18-2026-09-26.zh-CN.md")
MAX_BYTES = 2 * 1024 * 1024
O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
V17_SHA256 = "5cf9e082765081582163e4d7f88b7900657c9436c3263b6552be6f4bcf5a6111"
V18_SHA256 = "7d479bb012c3846eee51e29ed7bd822cde14ff34e225e445d65dd1e62b99c87f"
V17_REQUIRED_FRAGMENTS = (
    "| init flags | `FAN_CLASS_CONTENT|FAN_REPORT_PIDFD|FAN_CLOEXEC|FAN_NONBLOCK`，无 FID/TID report | `FAN_CLASS_NOTIF|FAN_REPORT_PIDFD|FAN_REPORT_DFID_NAME_TARGET|FAN_CLOEXEC|FAN_NONBLOCK`，无 permission/TID bits |",
    "`group_kind=permission`：`metadata.fd >= 0` 且 `event_fd_ref` 非 null；恰有一个 PIDFD info row",
    "`group_kind=name`：`metadata.fd == FAN_NOFD` 且 `event_fd_ref == null`；恰有一个 PIDFD info row",
    "`actor_pidfd_ref` 必须非 null",
)
V18_REQUIRED_FRAGMENTS = (
    "| permission | `CAP_SYS_ADMIN` 在 `init_user_ns` 中对真实 supervisor 有效",
    "| name/FID | `CAP_SYS_ADMIN` 在 `init_user_ns` 中对真实 supervisor 有效（因 `FAN_REPORT_PIDFD`）",
    "精确 V17 name/FID flags `0x1e83`",
    "精确 V17 permission flags `0x0087`",
    "event_f_flags` 为 `O_RDONLY|O_CLOEXEC|O_LARGEFILE=0x80000`",
    "不得将本节本机 x86-64 glibc 的 `event_f_flags=0x80000` 直接移植到另一 ABI",
)


class ProfileVerificationError(ValueError):
    """The static fanotify profile manifest or its bound contracts drifted."""


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProfileVerificationError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _read_beneath(root: Path, relative: str | Path) -> tuple[bytes, dict[str, Any]]:
    raw_path = str(relative)
    path = Path(raw_path)
    if path.is_absolute() or path.as_posix() != raw_path or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ProfileVerificationError("profile evidence path must be canonical and beneath the lab root")
    opened: list[int] = []
    try:
        root_fd = os.open(root, os.O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        opened.append(root_fd)
        parent_fd = root_fd
        for component in path.parts[:-1]:
            parent_fd = os.open(component, os.O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC, dir_fd=parent_fd)
            opened.append(parent_fd)
        descriptor = os.open(path.parts[-1], os.O_RDONLY | O_NOFOLLOW | O_CLOEXEC, dir_fd=parent_fd)
        opened.append(descriptor)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ProfileVerificationError(f"profile evidence must be a single-link regular file: {path}")
        if before.st_size > MAX_BYTES:
            raise ProfileVerificationError(f"profile evidence exceeds the byte limit: {path}")
        chunks: list[bytes] = []
        size = 0
        while True:
            block = os.read(descriptor, min(64 * 1024, MAX_BYTES + 1 - size))
            if not block:
                break
            size += len(block)
            if size > MAX_BYTES:
                raise ProfileVerificationError(f"profile evidence exceeds the byte limit: {path}")
            chunks.append(block)
        after = os.fstat(descriptor)
        named = os.stat(path.parts[-1], dir_fd=parent_fd, follow_symlinks=False)
        identity = lambda item: (
            item.st_dev, item.st_ino, item.st_mode, item.st_size,
            item.st_mtime_ns, item.st_ctime_ns, item.st_nlink,
        )
        if identity(before) != identity(after) or identity(after) != identity(named) or size != before.st_size:
            raise ProfileVerificationError(f"profile evidence changed while being read: {path}")
        payload = b"".join(chunks)
        return payload, {
            "path": path.as_posix(),
            "bytes": size,
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    except OSError as error:
        raise ProfileVerificationError(f"cannot safely open profile evidence beneath lab root: {path}") from error
    finally:
        for fd in reversed(opened):
            os.close(fd)


def _read_regular(relative: Path) -> tuple[bytes, dict[str, Any]]:
    return _read_beneath(LAB, relative)


def _keys(value: Any, expected: set[str], where: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise ProfileVerificationError(f"{where} must contain exactly the frozen keys")
    return value


def validate_manifest(value: Any) -> dict[str, Any]:
    root = _keys(value, {"schema", "record_id", "status", "contract_bindings", "profiles", "non_claims"}, "manifest")
    if root["schema"] != "core.cfd.f8.r008_terminal_fanotify_profiles.v1":
        raise ProfileVerificationError("unexpected terminal fanotify profile schema")
    if root["record_id"] != "f8-r008-terminal-fanotify-profiles-v1":
        raise ProfileVerificationError("unexpected terminal fanotify profile record id")
    if root["status"] != "proposal_only_static_profile_not_runtime_evidence":
        raise ProfileVerificationError("profile manifest must remain proposal-only")
    bindings = root.get("contract_bindings")
    expected_bindings = [
        {"path": V17.as_posix(), "sha256": V17_SHA256, "canonical_fragment_sha256": _fragment_digest(V17_REQUIRED_FRAGMENTS)},
        {"path": V18.as_posix(), "sha256": V18_SHA256, "canonical_fragment_sha256": _fragment_digest(V18_REQUIRED_FRAGMENTS)},
    ]
    if bindings != expected_bindings:
        raise ProfileVerificationError("V17/V18 contract hash and canonical-fragment pins are stale")
    if not isinstance(root["profiles"], list) or len(root["profiles"]) != 2:
        raise ProfileVerificationError("exactly two terminal fanotify profiles are required")

    profile_keys = {
        "group_kind", "init_flags_symbolic", "observed_linux_v6_8_x86_64_init_flags_hex",
        "target_abi_raw_init_flags_hex", "event_f_flags_symbolic",
        "observed_linux_v6_8_x86_64_glibc_event_f_flags_hex", "target_abi_raw_event_f_flags_hex",
        "capability_prerequisite", "permission_event_support_required", "metadata_fd_rule",
        "event_fd_ref_rule", "required_info_record_types", "forbidden_info_record_types",
        "actor_pidfd_ref_required",
    }
    common_event_flags = ["O_RDONLY", "O_CLOEXEC", "O_LARGEFILE"]
    cap = {"capability": "CAP_SYS_ADMIN", "user_namespace": "init_user_ns"}
    expected = {
        "permission": {
            "init_flags_symbolic": ["FAN_CLASS_CONTENT", "FAN_REPORT_PIDFD", "FAN_CLOEXEC", "FAN_NONBLOCK"],
            "observed_linux_v6_8_x86_64_init_flags_hex": "0x0087",
            "permission_event_support_required": True,
            "metadata_fd_rule": "nonnegative",
            "event_fd_ref_rule": "required",
            "required_info_record_types": ["PIDFD"],
            "forbidden_info_record_types": ["FID", "DFID", "DFID_NAME", "DFID_NAME_TARGET"],
        },
        "name": {
            "init_flags_symbolic": ["FAN_CLASS_NOTIF", "FAN_REPORT_PIDFD", "FAN_REPORT_DFID_NAME_TARGET", "FAN_CLOEXEC", "FAN_NONBLOCK"],
            "observed_linux_v6_8_x86_64_init_flags_hex": "0x1e83",
            "permission_event_support_required": False,
            "metadata_fd_rule": "FAN_NOFD",
            "event_fd_ref_rule": "null",
            "required_info_record_types": ["PIDFD", "FID", "DFID_NAME"],
            "forbidden_info_record_types": [],
            "name_info_grammar": "exactly_one_of_each_required_type_per_supported_event_bit",
        },
    }
    seen: set[str] = set()
    for index, raw_profile in enumerate(root["profiles"]):
        kind = raw_profile.get("group_kind") if isinstance(raw_profile, dict) else None
        if not isinstance(kind, str) or kind not in expected or kind in seen:
            raise ProfileVerificationError("profiles must contain one permission and one name group")
        seen.add(kind)
        fields = set(profile_keys)
        if kind == "name":
            fields.add("name_info_grammar")
        profile = _keys(raw_profile, fields, f"profiles[{index}]")
        target = expected[kind]
        for field, required in target.items():
            if field == "permission_event_support_required" and type(profile.get(field)) is not bool:
                raise ProfileVerificationError(f"{kind} profile {field} must be a JSON boolean")
            if profile.get(field) != required:
                raise ProfileVerificationError(f"{kind} profile violates frozen {field}")
        if profile["event_f_flags_symbolic"] != common_event_flags:
            raise ProfileVerificationError(f"{kind} profile changes the event_f_flags symbolic profile")
        if profile["observed_linux_v6_8_x86_64_glibc_event_f_flags_hex"] != "0x80000":
            raise ProfileVerificationError(f"{kind} profile changes the ABI-scoped observation")
        if profile["target_abi_raw_init_flags_hex"] is not None or profile["target_abi_raw_event_f_flags_hex"] is not None:
            raise ProfileVerificationError("un-pinned target ABI raw flag values must remain null")
        if profile["capability_prerequisite"] != cap:
            raise ProfileVerificationError(f"{kind} profile lacks the init_user_ns CAP_SYS_ADMIN prerequisite")
        if profile["actor_pidfd_ref_required"] is not True:
            raise ProfileVerificationError(f"{kind} profile must retain actor_pidfd_ref")
        if "FAN_REPORT_PIDFD" not in profile["init_flags_symbolic"]:
            raise ProfileVerificationError(f"{kind} profile cannot downgrade PIDFD")

    if seen != {"permission", "name"}:
        raise ProfileVerificationError("permission and name groups must both be present")
    non_claims = _keys(root["non_claims"], {
        "readiness_pass", "qualification_credit", "fanotify_init_called", "fanotify_mark_called",
        "host_capability_probed", "host_filesystem_probed", "pinned_kernel_conformance_passed",
        "nonprivileged_pidfd_downgrade_allowed",
    }, "non_claims")
    boolean_non_claims = set(non_claims) - {"qualification_credit"}
    if any(type(non_claims[key]) is not bool for key in boolean_non_claims):
        raise ProfileVerificationError("manifest boolean non-claims must use JSON booleans")
    if type(non_claims["qualification_credit"]) is not int:
        raise ProfileVerificationError("qualification_credit must be a JSON integer")
    required_non_claims = {
        "readiness_pass": False,
        "qualification_credit": 0,
        "fanotify_init_called": False,
        "fanotify_mark_called": False,
        "host_capability_probed": False,
        "host_filesystem_probed": False,
        "pinned_kernel_conformance_passed": False,
        "nonprivileged_pidfd_downgrade_allowed": False,
    }
    if non_claims != required_non_claims:
        raise ProfileVerificationError("manifest may not claim runtime readiness, probe success, or PIDFD downgrade")
    return root


def _fragment_digest(fragments: tuple[str, ...]) -> str:
    canonical = json.dumps(list(fragments), ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_contract_texts(manifest: dict[str, Any], v17: str, v18: str) -> None:
    permission = next(item for item in manifest["profiles"] if item["group_kind"] == "permission")
    name = next(item for item in manifest["profiles"] if item["group_kind"] == "name")
    permission_flags = "`FAN_CLASS_CONTENT|FAN_REPORT_PIDFD|FAN_CLOEXEC|FAN_NONBLOCK`"
    name_flags = "`FAN_CLASS_NOTIF|FAN_REPORT_PIDFD|FAN_REPORT_DFID_NAME_TARGET|FAN_CLOEXEC|FAN_NONBLOCK`"
    init_rows = [line for line in v17.splitlines() if line.startswith("| init flags |")]
    if len(init_rows) != 1 or permission_flags not in init_rows[0] or name_flags not in init_rows[0]:
        raise ProfileVerificationError("V17 init-flags row no longer binds the exact permission and name profiles")
    if not all(fragment in v17 for fragment in V17_REQUIRED_FRAGMENTS[1:]):
        raise ProfileVerificationError("V17 event-schema canonical fragment no longer matches")
    if permission["init_flags_symbolic"] != permission_flags.strip("`").split("|"):
        raise ProfileVerificationError("permission manifest flags do not match the frozen V17 flags")
    if name["init_flags_symbolic"] != name_flags.strip("`").split("|"):
        raise ProfileVerificationError("name manifest flags do not match the frozen V17 flags")
    for token in ("actor_pidfd_ref", "FAN_NOFD", "DFID_NAME", "PIDFD info row"):
        if token not in v17:
            raise ProfileVerificationError(f"V17 no longer binds required event schema token: {token}")
    for phrase in V18_REQUIRED_FRAGMENTS:
        if phrase not in v18:
            raise ProfileVerificationError(f"V18 no longer contains required capability/ABI contract: {phrase}")


def verify_profiles() -> dict[str, Any]:
    manifest_raw, manifest_ref = _read_regular(MANIFEST)
    try:
        manifest_value = json.loads(manifest_raw.decode("utf-8"), object_pairs_hook=_strict_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProfileVerificationError("fanotify profile manifest is not strict UTF-8 JSON") from error
    manifest = validate_manifest(manifest_value)

    v17_raw, v17_ref = _read_regular(V17)
    v18_raw, v18_ref = _read_regular(V18)
    if v17_ref["sha256"] != V17_SHA256 or v18_ref["sha256"] != V18_SHA256:
        raise ProfileVerificationError("V17/V18 contract source hash does not match the pinned revision")
    try:
        v17_text = v17_raw.decode("utf-8", errors="strict")
        v18_text = v18_raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise ProfileVerificationError("fanotify contract is not strict UTF-8") from error
    validate_contract_texts(manifest, v17_text, v18_text)
    observed_fragments = {
        V17.as_posix(): _fragment_digest(V17_REQUIRED_FRAGMENTS),
        V18.as_posix(): _fragment_digest(V18_REQUIRED_FRAGMENTS),
    }
    profiles_digest = hashlib.sha256(
        json.dumps(manifest["profiles"], sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    return {
        "schema": "core.cfd.f8.r008_terminal_fanotify_profile_verification.v1",
        "status": "static_profile_schema_pass_no_runtime_conformance",
        "profile_sha256": profiles_digest,
        "manifest": manifest_ref,
        "contract_bindings": [v17_ref, v18_ref],
        "canonical_fragment_sha256": observed_fragments,
        "group_kinds": ["permission", "name"],
        "capability_prerequisite": "CAP_SYS_ADMIN in init_user_ns for both groups",
        "pidfd_required_for_both_groups": True,
        "target_abi_raw_values_pinned": False,
        "pinned_kernel_conformance_passed": False,
        "fanotify_syscall_invoked": False,
        "host_capability_or_filesystem_probed": False,
        "readiness_pass": False,
        "qualification_credit": 0,
    }


if __name__ == "__main__":
    print(json.dumps(verify_profiles(), indent=2, sort_keys=True))
