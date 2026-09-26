#!/usr/bin/env python3
"""Validate a synthetic, untrusted F8 final-fput evidence join.

This is a pure diagnostic reducer. It does not collect, authenticate, or
independently decode kernel/fanotify evidence and can never establish a final
close, readiness, execution authority, or qualification credit.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from typing import Any


INPUT_SCHEMA = "core.cfd.f8.r008_final_fput_join_input.v1"
RESULT_SCHEMA = "core.cfd.f8.r008_final_fput_join_diagnostic.v1"
OBSERVER_ROW_SCHEMA = "f8-final-fput-observer-row-v1"
LOSS_EPOCH_SCHEMA = "f8-final-fput-loss-epoch-v1"
CLOSE_CONTEXT_SCHEMA = "f8-final-fput-close-context-v1"
CGROUP_EMPTY_SCHEMA = "f8-cgroup-empty-ref-v1"
NAME_GROUP_SCHEMA = "f8-fanotify-name-group-drain-input-v1"
FANOTIFY_RAW_SCHEMA = "f8-fanotify-raw-v1"
FANOTIFY_OBJECT_JOIN_SCHEMA = "f8-fanotify-object-join-v1"

EXPECTED_OBSERVER_EVENTS = (
    "fd_install_entry",
    "__fput_entry",
    "fsnotify_close",
    "__fput_return",
)
FAN_NOFD = -1
FAN_ACCESS = 0x00000001
FAN_MODIFY = 0x00000002
FAN_CLOSE_WRITE = 0x00000008
FAN_CLOSE_NOWRITE = 0x00000010
FAN_OPEN = 0x00000020
FAN_CREATE = 0x00000100
FANOTIFY_METADATA_VERSION = 3
FANOTIFY_METADATA_SIZE_X86_64 = 24
ALLOWED_NAME_EVENT_MASKS = {
    FAN_ACCESS,
    FAN_MODIFY,
    FAN_CLOSE_WRITE,
    FAN_CLOSE_NOWRITE,
    FAN_OPEN,
    FAN_CREATE,
}
EXPECTED_INFO_TYPES = (1, 2, 4)  # FID, DFID_NAME, PIDFD in Linux fanotify UAPI.
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
MAX_TEXT_UTF8_BYTES = 1024
MAX_RAW_EVENT_BYTES = 64 * 1024
MAX_FDINFO_BYTES = 16 * 1024
MAX_NAME_GROUP_EVENTS = 4096
MAX_NAME_GROUP_BYTES = 16 * 1024 * 1024
MAX_LOSS_EPOCHS = 4096
_LOSS_COUNTERS = (
    "producer_lost",
    "buffer_overrun",
    "sequence_gap",
    "reader_lag",
)


class FinalFputJoinError(ValueError):
    """Input does not satisfy the strict diagnostic join contract."""


def _exact_object(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise FinalFputJoinError(f"{label} must be an exact JSON object")
    if any(type(key) is not str for key in value):
        raise FinalFputJoinError(f"{label} keys must be strings")
    actual = set(value)
    if actual != fields:
        missing = sorted(fields - actual)
        extra = sorted(actual - fields)
        raise FinalFputJoinError(f"{label} fields differ (missing={missing}, extra={extra})")
    return value


def _text(value: Any, label: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise FinalFputJoinError(f"{label} must be a non-empty canonical string")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise FinalFputJoinError(f"{label} is not valid UTF-8 text") from error
    if len(encoded) > MAX_TEXT_UTF8_BYTES:
        raise FinalFputJoinError(f"{label} exceeds the fixed text-size bound")
    return value


def _uint(value: Any, label: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise FinalFputJoinError(f"{label} must be an exact integer >= {minimum}")
    return value


def _sha256(value: Any, label: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise FinalFputJoinError(f"{label} must be lowercase SHA-256 hex")
    return value


def _decode_b64(value: Any, label: str, *, max_bytes: int = MAX_RAW_EVENT_BYTES) -> bytes:
    if type(value) is not str:
        raise FinalFputJoinError(f"{label} must be base64 text")
    if len(value) > 4 * ((max_bytes + 2) // 3):
        raise FinalFputJoinError(f"{label} exceeds the fixed encoded-size bound")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as error:
        raise FinalFputJoinError(f"{label} is not strict base64") from error
    if len(decoded) > max_bytes:
        raise FinalFputJoinError(f"{label} exceeds the fixed decoded-size bound")
    return decoded


def _validate_ref(value: Any, expected_kind: str, label: str) -> dict[str, str]:
    ref = _exact_object(value, {"ref_kind", "ref_id"}, label)
    if _text(ref["ref_kind"], f"{label}.ref_kind") != expected_kind:
        raise FinalFputJoinError(f"{label} has the wrong ref_kind")
    _text(ref["ref_id"], f"{label}.ref_id")
    return ref


def _validate_object_ref(value: Any, label: str) -> dict[str, Any]:
    ref = _exact_object(
        value,
        {"object_id", "mount_id", "fsid_sha256", "file_handle_sha256", "generation"},
        label,
    )
    _text(ref["object_id"], f"{label}.object_id")
    _uint(ref["mount_id"], f"{label}.mount_id", minimum=1)
    _sha256(ref["fsid_sha256"], f"{label}.fsid_sha256")
    _sha256(ref["file_handle_sha256"], f"{label}.file_handle_sha256")
    _text(ref["generation"], f"{label}.generation")
    return ref


def _validate_loss_epoch(value: Any, label: str) -> tuple[tuple[str, int, str], ...]:
    loss = _exact_object(value, {"schema", "epochs"}, label)
    if (
        loss["schema"] != LOSS_EPOCH_SCHEMA
        or type(loss["epochs"]) is not list
        or not loss["epochs"]
        or len(loss["epochs"]) > MAX_LOSS_EPOCHS
    ):
        raise FinalFputJoinError(f"{label} must contain a non-empty {LOSS_EPOCH_SCHEMA} roster")

    epoch_fields = {
        "producer_id", "cpu_id", "epoch_id", "producer_lost",
        "buffer_overrun", "sequence_gap", "reader_lag",
    }
    roster: list[tuple[str, int, str]] = []
    for index, item in enumerate(loss["epochs"]):
        row = _exact_object(item, epoch_fields, f"{label}.epochs[{index}]")
        producer = _text(row["producer_id"], f"{label}.epochs[{index}].producer_id")
        cpu = _uint(row["cpu_id"], f"{label}.epochs[{index}].cpu_id")
        epoch = _text(row["epoch_id"], f"{label}.epochs[{index}].epoch_id")
        roster.append((producer, cpu, epoch))
        for counter in _LOSS_COUNTERS:
            if _uint(row[counter], f"{label}.epochs[{index}].{counter}") != 0:
                raise FinalFputJoinError(f"{label} reports non-zero {counter}")

    if roster != sorted(roster) or len(set(roster)) != len(roster):
        raise FinalFputJoinError(f"{label} epoch roster must be sorted and unique")
    return tuple(roster)


def validate_observer_row(value: Any) -> dict[str, Any]:
    """Validate one exact V17 observer row without authenticating its source."""
    fields = {
        "schema", "attempt_id", "observer_profile_id", "kernel_build_id",
        "kernel_source_commit", "hook_id", "hook_seq", "monotonic_ns",
        "task_generation", "fd_number", "fd_generation", "open_token_ref",
        "file_cookie_digest", "object_ref", "event_kind", "raw_args_digest",
        "raw_return", "loss_epoch", "producer_lost", "buffer_overrun",
        "sequence_gap", "reader_lag",
    }
    row = _exact_object(value, fields, "observer row")
    if row["schema"] != OBSERVER_ROW_SCHEMA:
        raise FinalFputJoinError("observer row has an unsupported schema")
    for name in (
        "attempt_id", "observer_profile_id", "kernel_build_id",
        "kernel_source_commit", "hook_id", "task_generation", "open_token_ref",
        "object_ref",
    ):
        _text(row[name], f"observer row {name}")
    _uint(row["hook_seq"], "observer row hook_seq", minimum=1)
    _uint(row["monotonic_ns"], "observer row monotonic_ns", minimum=1)
    _uint(row["fd_number"], "observer row fd_number")
    _uint(row["fd_generation"], "observer row fd_generation", minimum=1)
    _sha256(row["file_cookie_digest"], "observer row file_cookie_digest")
    _sha256(row["raw_args_digest"], "observer row raw_args_digest")
    if row["event_kind"] not in EXPECTED_OBSERVER_EVENTS:
        raise FinalFputJoinError("observer row has an unsupported event_kind")
    if row["raw_return"] is not None and type(row["raw_return"]) is not int:
        raise FinalFputJoinError("observer row raw_return must be an exact integer or null")

    _validate_loss_epoch(row["loss_epoch"], "observer row loss_epoch")
    for counter in _LOSS_COUNTERS:
        if _uint(row[counter], f"observer row {counter}") != 0:
            raise FinalFputJoinError(f"observer row reports non-zero {counter}")
    return row


def _validate_terminal_exit_ref(value: Any, attempt_id: str) -> dict[str, Any]:
    ref = _exact_object(
        value,
        {"ref_kind", "ref_id", "attempt_id", "record_seq"},
        "close_context.terminal_exit_ref",
    )
    if ref["ref_kind"] != "terminal_exit" or ref["attempt_id"] != attempt_id:
        raise FinalFputJoinError("terminal_exit_ref kind or attempt does not match")
    _text(ref["ref_id"], "terminal_exit_ref.ref_id")
    _uint(ref["record_seq"], "terminal_exit_ref.record_seq", minimum=1)
    return ref


def _validate_cgroup_empty_ref(value: Any, attempt_id: str) -> dict[str, Any]:
    fields = {
        "schema", "ref_kind", "ref_id", "attempt_id", "cgroup_id", "cgroup_inode",
        "epoch_id", "freeze_readback_bytes", "procs_before_digest", "procs_after_digest",
        "populated_readback_bytes", "task_inventory_digest", "observed_empty", "record_seq",
    }
    ref = _exact_object(value, fields, "close_context.cgroup_empty_ref")
    if ref["schema"] != CGROUP_EMPTY_SCHEMA or ref["ref_kind"] != "cgroup_empty":
        raise FinalFputJoinError("cgroup_empty_ref has the wrong schema or ref_kind")
    if ref["attempt_id"] != attempt_id:
        raise FinalFputJoinError("cgroup_empty_ref attempt does not match")
    for name in ("ref_id", "cgroup_id", "epoch_id"):
        _text(ref[name], f"cgroup_empty_ref.{name}")
    _uint(ref["cgroup_inode"], "cgroup_empty_ref.cgroup_inode", minimum=1)
    if ref["freeze_readback_bytes"] != "1\n":
        raise FinalFputJoinError("cgroup freeze readback is not the exact frozen value")
    if ref["populated_readback_bytes"] != "populated 0\n":
        raise FinalFputJoinError("cgroup populated readback is not exactly empty")
    for name in ("procs_before_digest", "procs_after_digest", "task_inventory_digest"):
        _sha256(ref[name], f"cgroup_empty_ref.{name}")
    if ref["observed_empty"] is not True:
        raise FinalFputJoinError("cgroup_empty_ref does not assert observed_empty=true")
    _uint(ref["record_seq"], "cgroup_empty_ref.record_seq", minimum=1)
    return ref


def _validate_close_context(value: Any, attempt_id: str) -> dict[str, Any]:
    fields = {
        "schema", "attempt_id", "terminal_exit_ref", "cgroup_empty_ref", "object_ref",
        "supervisor_task_generation",
        "open_token_ref", "close_token_ref", "final_write_token_refs", "fd_number",
        "fd_generation", "operation_seq", "close_entry_seq", "close_exit_seq",
        "close_ret", "close_errno", "causal_parent_refs",
    }
    context = _exact_object(value, fields, "close_context")
    if context["schema"] != CLOSE_CONTEXT_SCHEMA or context["attempt_id"] != attempt_id:
        raise FinalFputJoinError("close_context schema or attempt does not match")
    terminal = _validate_terminal_exit_ref(context["terminal_exit_ref"], attempt_id)
    cgroup = _validate_cgroup_empty_ref(context["cgroup_empty_ref"], attempt_id)
    object_ref = _validate_object_ref(context["object_ref"], "close_context.object_ref")
    _text(context["supervisor_task_generation"], "close_context.supervisor_task_generation")
    _text(context["open_token_ref"], "close_context.open_token_ref")
    _text(context["close_token_ref"], "close_context.close_token_ref")
    if type(context["final_write_token_refs"]) is not list or not context["final_write_token_refs"]:
        raise FinalFputJoinError("close_context must name at least one final-write token")
    if len(context["final_write_token_refs"]) > MAX_NAME_GROUP_EVENTS:
        raise FinalFputJoinError("close_context final-write token count exceeds the fixed bound")
    final_writes = [_text(item, "final_write_token_ref") for item in context["final_write_token_refs"]]
    if final_writes != sorted(set(final_writes)):
        raise FinalFputJoinError("final-write token refs must be sorted and unique")
    _uint(context["fd_number"], "close_context.fd_number")
    _uint(context["fd_generation"], "close_context.fd_generation", minimum=1)
    _uint(context["operation_seq"], "close_context.operation_seq", minimum=1)
    _uint(context["close_entry_seq"], "close_context.close_entry_seq", minimum=1)
    _uint(context["close_exit_seq"], "close_context.close_exit_seq", minimum=1)
    if context["close_entry_seq"] >= context["close_exit_seq"]:
        raise FinalFputJoinError("close syscall entry/exit sequence is not increasing")
    if context["close_ret"] != 0 or type(context["close_ret"]) is not int or context["close_errno"] != 0 or type(context["close_errno"]) is not int:
        raise FinalFputJoinError("backing close must have exact ret=0 and errno=0")

    if type(context["causal_parent_refs"]) is not list:
        raise FinalFputJoinError("close_context.causal_parent_refs must be a list")
    if len(context["causal_parent_refs"]) > MAX_NAME_GROUP_EVENTS + 2:
        raise FinalFputJoinError("close_context causal-parent count exceeds the fixed bound")
    expected_parents = [
        {"ref_kind": "terminal_exit", "ref_id": terminal["ref_id"]},
        {"ref_kind": "cgroup_empty", "ref_id": cgroup["ref_id"]},
        *({"ref_kind": "supervisor_operation", "ref_id": item} for item in final_writes),
    ]
    expected_parents.sort(key=lambda item: (item["ref_kind"], item["ref_id"]))
    for index, parent in enumerate(context["causal_parent_refs"]):
        if type(parent) is not dict or parent.get("ref_kind") not in {
            "terminal_exit", "cgroup_empty", "supervisor_operation",
        }:
            raise FinalFputJoinError(f"causal_parent_refs[{index}] has an unsupported ref_kind")
        _validate_ref(parent, parent["ref_kind"], f"causal_parent_refs[{index}]")
    if context["causal_parent_refs"] != expected_parents:
        raise FinalFputJoinError("close causal parents are missing, extra, duplicate, or non-canonical")
    return {**context, "object_ref": object_ref, "terminal_exit_ref": terminal, "cgroup_empty_ref": cgroup}


def _validate_fanotify_raw_row(value: Any, attempt_id: str, group_id: str) -> tuple[dict[str, Any], int]:
    fields = {
        "schema", "attempt_id", "group_id", "group_kind", "group_seq", "read_seq",
        "raw_record", "metadata", "info_records", "mark_inventory_digest",
        "actor_pidfd_ref", "event_fd_ref",
    }
    row = _exact_object(value, fields, "fanotify raw row")
    if row["schema"] != FANOTIFY_RAW_SCHEMA or row["attempt_id"] != attempt_id or row["group_id"] != group_id:
        raise FinalFputJoinError("fanotify raw row schema, attempt, or group does not match")
    if row["group_kind"] != "name":
        raise FinalFputJoinError("final-close event must come from the name group")
    _uint(row["group_seq"], "fanotify group_seq", minimum=1)
    _uint(row["read_seq"], "fanotify read_seq", minimum=1)

    raw_record = _exact_object(row["raw_record"], {"bytes_b64", "byte_len", "sha256"}, "fanotify raw_record")
    raw = _decode_b64(
        raw_record["bytes_b64"], "fanotify raw_record.bytes_b64", max_bytes=MAX_RAW_EVENT_BYTES,
    )
    if _uint(raw_record["byte_len"], "fanotify raw_record.byte_len", minimum=1) != len(raw):
        raise FinalFputJoinError("fanotify raw_record byte length does not match bytes")
    if _sha256(raw_record["sha256"], "fanotify raw_record.sha256") != hashlib.sha256(raw).hexdigest():
        raise FinalFputJoinError("fanotify raw_record digest does not match bytes")

    metadata = _exact_object(
        row["metadata"],
        {"event_len", "vers", "reserved", "metadata_len", "mask", "fd", "pid"},
        "fanotify metadata",
    )
    event_len = _uint(metadata["event_len"], "fanotify metadata.event_len", minimum=1)
    if metadata["vers"] != FANOTIFY_METADATA_VERSION or type(metadata["vers"]) is not int:
        raise FinalFputJoinError("fanotify metadata version differs from this diagnostic x86-64 ABI profile")
    if metadata["reserved"] != 0 or type(metadata["reserved"]) is not int:
        raise FinalFputJoinError("fanotify metadata reserved must be zero")
    metadata_len = _uint(metadata["metadata_len"], "fanotify metadata.metadata_len", minimum=1)
    if metadata_len != FANOTIFY_METADATA_SIZE_X86_64 or metadata_len > event_len or event_len != len(raw):
        raise FinalFputJoinError("fanotify metadata and raw event lengths disagree")
    mask = _uint(metadata["mask"], "fanotify metadata.mask", minimum=1)
    if mask not in ALLOWED_NAME_EVENT_MASKS:
        raise FinalFputJoinError("fanotify name event has an unsupported or combined mask")
    if type(metadata["fd"]) is not int or metadata["fd"] != FAN_NOFD:
        raise FinalFputJoinError("name/FID event metadata.fd must be FAN_NOFD")
    _uint(metadata["pid"], "fanotify metadata.pid", minimum=1)

    if type(row["info_records"]) is not list:
        raise FinalFputJoinError("fanotify info_records must be a list")
    types: list[int] = []
    row_byte_count = len(raw)
    for index, item in enumerate(row["info_records"]):
        info = _exact_object(item, {"type", "len", "bytes_b64"}, f"fanotify info_records[{index}]")
        types.append(_uint(info["type"], f"fanotify info_records[{index}].type"))
        info_bytes = _decode_b64(
            info["bytes_b64"], f"fanotify info_records[{index}].bytes_b64", max_bytes=MAX_RAW_EVENT_BYTES,
        )
        row_byte_count += len(info_bytes)
        if _uint(info["len"], f"fanotify info_records[{index}].len", minimum=1) != len(info_bytes):
            raise FinalFputJoinError("fanotify info-record length does not match bytes")
    if sorted(types) != list(EXPECTED_INFO_TYPES):
        raise FinalFputJoinError("name/FID event must declare exactly one PIDFD, FID, and DFID_NAME row")

    _sha256(row["mark_inventory_digest"], "fanotify mark_inventory_digest")
    _text(row["actor_pidfd_ref"], "fanotify actor_pidfd_ref")
    if row["event_fd_ref"] is not None:
        raise FinalFputJoinError("name/FID event must not have an event_fd_ref")
    return row, row_byte_count


def _validate_pidfd_action(value: Any, raw_row: dict[str, Any], context: dict[str, Any]) -> tuple[str, int]:
    fields = {
        "schema", "attempt_id", "group_id", "group_seq", "pidfd_info_index",
        "pidfd_number", "fdinfo_raw_bytes_b64", "metadata_pid", "task_generation_ref",
        "held_pidfd_ref", "close_ret", "close_errno",
    }
    action = _exact_object(value, fields, "fanotify PIDFD action")
    if (
        action["schema"] != "f8-fanotify-pidfd-action-v1"
        or action["attempt_id"] != raw_row["attempt_id"]
        or action["group_id"] != raw_row["group_id"]
        or action["group_seq"] != raw_row["group_seq"]
    ):
        raise FinalFputJoinError("PIDFD action does not reference its raw fanotify row")
    _uint(action["pidfd_info_index"], "PIDFD action pidfd_info_index")
    if action["pidfd_info_index"] >= len(raw_row["info_records"]) or raw_row["info_records"][action["pidfd_info_index"]]["type"] != 4:
        raise FinalFputJoinError("PIDFD action index does not identify the PIDFD info record")
    _uint(action["pidfd_number"], "PIDFD action pidfd_number")
    fdinfo = _decode_b64(
        action["fdinfo_raw_bytes_b64"], "PIDFD action fdinfo_raw_bytes_b64", max_bytes=MAX_FDINFO_BYTES,
    )
    if not fdinfo:
        raise FinalFputJoinError("PIDFD action fdinfo bytes must be non-empty")
    if _uint(action["metadata_pid"], "PIDFD action metadata_pid", minimum=1) != raw_row["metadata"]["pid"]:
        raise FinalFputJoinError("PIDFD action metadata PID differs from raw fanotify metadata")
    if _text(action["task_generation_ref"], "PIDFD action task_generation_ref") != context["supervisor_task_generation"]:
        raise FinalFputJoinError("PIDFD actor generation differs from terminal close actor")
    held_ref = _text(action["held_pidfd_ref"], "PIDFD action held_pidfd_ref")
    if raw_row["actor_pidfd_ref"] != held_ref:
        raise FinalFputJoinError("raw fanotify actor_pidfd_ref does not reference its action row")
    if type(action["close_ret"]) is not int or action["close_ret"] != 0:
        raise FinalFputJoinError("PIDFD action descriptor close did not succeed")
    if type(action["close_errno"]) is not int or action["close_errno"] != 0:
        raise FinalFputJoinError("PIDFD action descriptor close errno is non-zero")
    return held_ref, len(fdinfo)


def _validate_fanotify_object_join(value: Any, raw_row: dict[str, Any]) -> dict[str, Any]:
    fields = {
        "schema", "attempt_id", "group_id", "group_seq", "object_ref",
        "marked_parent_refs", "join_basis",
    }
    join = _exact_object(value, fields, "fanotify object join")
    if (
        join["schema"] != FANOTIFY_OBJECT_JOIN_SCHEMA
        or join["attempt_id"] != raw_row["attempt_id"]
        or join["group_id"] != raw_row["group_id"]
        or join["group_seq"] != raw_row["group_seq"]
    ):
        raise FinalFputJoinError("fanotify object join does not reference its raw row")
    actual_object = _validate_object_ref(join["object_ref"], "fanotify object_join.object_ref")
    parents = join["marked_parent_refs"]
    if type(parents) is not list or len(parents) != 1:
        raise FinalFputJoinError("name/FID object join requires exactly one marked parent ref")
    _text(parents[0], "fanotify marked_parent_ref")
    _text(join["join_basis"], "fanotify join_basis")
    return actual_object


def _validate_name_group(value: Any, attempt_id: str, context: dict[str, Any]) -> dict[str, Any]:
    fields = {
        "schema", "attempt_id", "group_id", "first_group_seq", "last_group_seq",
        "drained_to_eagain", "loss_count", "overflow_count", "short_read_count", "events",
    }
    group = _exact_object(value, fields, "name_group")
    if group["schema"] != NAME_GROUP_SCHEMA or group["attempt_id"] != attempt_id:
        raise FinalFputJoinError("name_group schema or attempt does not match")
    group_id = _text(group["group_id"], "name_group.group_id")
    first = _uint(group["first_group_seq"], "name_group.first_group_seq", minimum=1)
    last = _uint(group["last_group_seq"], "name_group.last_group_seq", minimum=1)
    if first > last:
        raise FinalFputJoinError("name_group sequence range is reversed")
    if group["drained_to_eagain"] is not True:
        raise FinalFputJoinError("name_group was not drained to EAGAIN")
    for counter in ("loss_count", "overflow_count", "short_read_count"):
        if _uint(group[counter], f"name_group.{counter}") != 0:
            raise FinalFputJoinError(f"name_group reports non-zero {counter}")
    if (
        type(group["events"]) is not list
        or len(group["events"]) > MAX_NAME_GROUP_EVENTS
        or len(group["events"]) != last - first + 1
    ):
        raise FinalFputJoinError("name_group does not contain its complete sequence interval")

    close_matches: list[dict[str, Any]] = []
    seen_marks: set[str] = set()
    seen_pidfd_refs: set[str] = set()
    total_group_bytes = 0
    for offset, event in enumerate(group["events"]):
        event = _exact_object(
            event,
            {"raw_row", "object_join", "pidfd_action", "close_token_ref"},
            f"name_group.events[{offset}]",
        )
        raw_row, raw_bytes = _validate_fanotify_raw_row(event["raw_row"], attempt_id, group_id)
        expected_seq = first + offset
        if raw_row["group_seq"] != expected_seq:
            raise FinalFputJoinError("name_group has a gap, duplicate, or reordered group_seq")
        pidfd_ref, fdinfo_bytes = _validate_pidfd_action(event["pidfd_action"], raw_row, context)
        total_group_bytes += raw_bytes + fdinfo_bytes
        if total_group_bytes > MAX_NAME_GROUP_BYTES:
            raise FinalFputJoinError("name_group decoded evidence exceeds the fixed total byte bound")
        if pidfd_ref in seen_pidfd_refs:
            raise FinalFputJoinError("PIDFD action reference is duplicated")
        seen_pidfd_refs.add(pidfd_ref)
        mark_digest = raw_row["mark_inventory_digest"]
        if seen_marks and mark_digest not in seen_marks:
            raise FinalFputJoinError("name_group mark inventory changed within the drain window")
        seen_marks.add(mark_digest)
        event_object = _validate_fanotify_object_join(event["object_join"], raw_row)
        token_ref = event["close_token_ref"]
        if raw_row["metadata"]["mask"] == FAN_CLOSE_WRITE:
            _text(token_ref, "fanotify FAN_CLOSE_WRITE close_token_ref")
            if event_object == context["object_ref"]:
                close_matches.append(event)
        elif token_ref is not None:
            raise FinalFputJoinError("non-close event unexpectedly claims a close token")

    if len(close_matches) != 1:
        raise FinalFputJoinError("target output must have exactly one FAN_CLOSE_WRITE join")
    close_event = close_matches[0]
    if close_event["close_token_ref"] != context["close_token_ref"]:
        raise FinalFputJoinError("FAN_CLOSE_WRITE does not match the terminal close token")
    return {**group, "matched_close_write_group_seq": close_event["raw_row"]["group_seq"]}


def reconcile_final_close(value: Any) -> dict[str, Any]:
    """Return an untrusted consistency diagnostic; never a final-close claim."""
    top = _exact_object(value, {"schema", "attempt_id", "close_context", "observer_rows", "name_group"}, "join input")
    if top["schema"] != INPUT_SCHEMA:
        raise FinalFputJoinError("join input schema is unsupported")
    attempt_id = _text(top["attempt_id"], "join input attempt_id")
    context = _validate_close_context(top["close_context"], attempt_id)

    if type(top["observer_rows"]) is not list or len(top["observer_rows"]) != len(EXPECTED_OBSERVER_EVENTS):
        raise FinalFputJoinError("observer_rows must contain exactly the four required lifecycle rows")
    rows = [validate_observer_row(row) for row in top["observer_rows"]]
    if tuple(row["event_kind"] for row in rows) != EXPECTED_OBSERVER_EVENTS:
        raise FinalFputJoinError("observer rows are missing, duplicated, or out of lifecycle order")

    first = rows[0]
    invariant_fields = (
        "attempt_id", "observer_profile_id", "kernel_build_id", "kernel_source_commit",
        "task_generation", "fd_number", "fd_generation", "open_token_ref",
        "file_cookie_digest", "object_ref",
    )
    for row in rows:
        if row["attempt_id"] != attempt_id:
            raise FinalFputJoinError("observer row attempt does not match join input")
        if any(row[field] != first[field] for field in invariant_fields):
            raise FinalFputJoinError("observer lifecycle rows disagree on attempt/file/task identity")
        if row["fd_number"] != context["fd_number"] or row["fd_generation"] != context["fd_generation"]:
            raise FinalFputJoinError("observer FD generation differs from terminal close")
        if row["open_token_ref"] != context["open_token_ref"]:
            raise FinalFputJoinError("observer open-token lineage differs from close context")
        if row["object_ref"] != context["object_ref"]["object_id"]:
            raise FinalFputJoinError("observer object differs from close context")
        if row["task_generation"] != context["supervisor_task_generation"]:
            raise FinalFputJoinError("observer task generation differs from close actor")
    if [row["monotonic_ns"] for row in rows] != sorted({row["monotonic_ns"] for row in rows}):
        raise FinalFputJoinError("observer lifecycle timestamps are not strictly increasing")
    last_seq_by_hook: dict[str, int] = {}
    for row in rows:
        previous = last_seq_by_hook.get(row["hook_id"])
        if previous is not None and row["hook_seq"] <= previous:
            raise FinalFputJoinError("observer hook sequence is duplicated or regressed")
        last_seq_by_hook[row["hook_id"]] = row["hook_seq"]
    rosters = [_validate_loss_epoch(row["loss_epoch"], "observer row loss_epoch") for row in rows]
    if any(roster != rosters[0] for roster in rosters[1:]):
        raise FinalFputJoinError("observer loss-epoch roster changed during the lifecycle window")

    group = _validate_name_group(top["name_group"], attempt_id, context)
    return {
        "schema": RESULT_SCHEMA,
        "status": "diagnostic_declared_links_consistent_untrusted",
        "attempt_id": attempt_id,
        "close_token_ref": context["close_token_ref"],
        "object_id": context["object_ref"]["object_id"],
        "file_cookie_digest": first["file_cookie_digest"],
        "observer_event_order": list(EXPECTED_OBSERVER_EVENTS),
        "fanotify_name_group_seq_range": [group["first_group_seq"], group["last_group_seq"]],
        "fanotify_close_write_group_seq": group["matched_close_write_group_seq"],
        "final_close_claim": False,
        "trusted_observation": False,
        "kernel_source_pinned": False,
        "observer_runtime_authenticated": False,
        "fanotify_raw_bytes_reparsed": False,
        "cgroup_empty_reread": False,
        "close_syscall_to_fput_order_checked": False,
        "readiness_pass": False,
        "T1_numerical": False,
        "execution_authority": False,
        "qualification_credit": 0,
    }


def build_diagnostic_receipt(value: Any) -> dict[str, Any]:
    """Build a deterministic receipt that is permanently non-authorizing."""
    result = reconcile_final_close(value)
    try:
        canonical = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8", errors="strict")
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise FinalFputJoinError("join input is not canonicalizable JSON data") from error
    return {**result, "input_sha256": hashlib.sha256(canonical).hexdigest()}
