#!/usr/bin/env python3
"""Reparse bounded, caller-supplied Linux v6.8 x86-64 fanotify name events.

This is a structural diagnostic only. It does not authenticate the supplied
bytes, their kernel/runtime origin, or any object/PIDFD/cookie relationship.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import re
import struct
from typing import Any


PARSER_SCHEMA = "core.cfd.f8.r008_fanotify_raw_parse_diagnostic.v1"
PROFILE_ID = "linux-v6.8-x86_64-fanotify-name-single-path-v1"
MAX_RAW_EVENT_BYTES = 64 * 1024
MAX_FILE_HANDLE_BYTES = 128
MAX_NAME_BYTES = 255

METADATA_VERSION = 3
METADATA_LEN = 24
FAN_NOFD = -1
FAN_ACCESS = 0x00000001
FAN_MODIFY = 0x00000002
FAN_CLOSE_WRITE = 0x00000008
FAN_CLOSE_NOWRITE = 0x00000010
FAN_OPEN = 0x00000020
FAN_CREATE = 0x00000100
SUPPORTED_SINGLE_EVENT_MASKS = frozenset({
    FAN_ACCESS, FAN_MODIFY, FAN_CLOSE_WRITE, FAN_CLOSE_NOWRITE, FAN_OPEN, FAN_CREATE,
})

INFO_FID = 1
INFO_DFID_NAME = 2
INFO_PIDFD = 4
# Linux v6.8 fanotify_user.c emits directory/name, child FID, then PIDFD.
EXPECTED_INFO_ORDER = (INFO_DFID_NAME, INFO_FID, INFO_PIDFD)

_METADATA = struct.Struct("<IBBHQii")
_INFO_HEADER = struct.Struct("<BBH")
_U32_I32 = struct.Struct("<Ii")
_I32 = struct.Struct("<i")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class FanotifyRawParseError(ValueError):
    """The supplied event is malformed or disagrees with its declarations."""


def _exact_object(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise FanotifyRawParseError(f"{label} must be an exact object")
    if set(value) != keys:
        raise FanotifyRawParseError(f"{label} fields differ")
    return value


def _integer(value: Any, label: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise FanotifyRawParseError(f"{label} is outside its exact integer range")
    return value


def _decode_canonical_b64(value: Any, label: str, cap: int) -> bytes:
    if type(value) is not str or len(value) > 4 * ((cap + 2) // 3):
        raise FanotifyRawParseError(f"{label} exceeds its encoded-size bound")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as error:
        raise FanotifyRawParseError(f"{label} is not strict base64") from error
    if len(decoded) > cap or base64.b64encode(decoded).decode("ascii") != value:
        raise FanotifyRawParseError(f"{label} is non-canonical or exceeds its decoded-size bound")
    return decoded


def _round_up_4(value: int) -> int:
    return (value + 3) & ~3


def _parse_fid_record(record: bytes, expected_type: int, index: int) -> dict[str, Any]:
    label = f"info_records[{index}]"
    if len(record) < 20:
        raise FanotifyRawParseError(f"{label} FID record is shorter than its fixed payload")

    fsid = record[4:12]
    handle_bytes, handle_type = _U32_I32.unpack_from(record, 12)
    if not 1 <= handle_bytes <= MAX_FILE_HANDLE_BYTES:
        raise FanotifyRawParseError(f"{label} file-handle byte count is outside the profile bound")

    handle_end = 20 + handle_bytes
    if handle_end > len(record):
        raise FanotifyRawParseError(f"{label} file handle overruns its info record")
    handle = record[20:handle_end]

    name = b""
    payload_end = handle_end
    if expected_type == INFO_DFID_NAME:
        nul = record.find(b"\0", handle_end)
        if nul < 0:
            raise FanotifyRawParseError(f"{label} DFID_NAME lacks its terminal NUL")
        name = record[handle_end:nul]
        if not 1 <= len(name) <= MAX_NAME_BYTES:
            raise FanotifyRawParseError(f"{label} DFID_NAME length is outside the profile bound")
        payload_end = nul + 1

    if _round_up_4(payload_end) != len(record):
        raise FanotifyRawParseError(f"{label} length is not the exact four-byte aligned payload size")
    if any(record[payload_end:]):
        raise FanotifyRawParseError(f"{label} has non-zero alignment padding")

    return {
        "info_type": expected_type,
        "fsid_sha256": hashlib.sha256(fsid).hexdigest(),
        "handle_type": handle_type,
        "handle_bytes": len(handle),
        "handle_sha256": hashlib.sha256(handle).hexdigest(),
        "name_bytes": len(name),
        "name_sha256": hashlib.sha256(name).hexdigest() if name else None,
    }


def parse_declared_name_event(
    raw_record: Any,
    declared_metadata: Any,
    declared_info_records: Any,
) -> dict[str, Any]:
    """Parse raw bytes and require exact equality with the redundant declarations.

    Accepts only the V17 ordinary linked-file name-group event profile for the
    six single event masks listed above. Input is caller supplied and remains
    untrusted even when this function returns successfully.
    """
    raw_row = _exact_object(raw_record, {"bytes_b64", "byte_len", "sha256"}, "raw_record")
    raw = _decode_canonical_b64(raw_row["bytes_b64"], "raw_record.bytes_b64", MAX_RAW_EVENT_BYTES)
    if not METADATA_LEN + 3 * _INFO_HEADER.size <= len(raw) <= MAX_RAW_EVENT_BYTES:
        raise FanotifyRawParseError("raw event length is outside the fixed profile bound")
    byte_len = _integer(raw_row["byte_len"], "raw_record.byte_len", 1, MAX_RAW_EVENT_BYTES)
    if byte_len != len(raw):
        raise FanotifyRawParseError("raw_record.byte_len does not match decoded bytes")
    digest = raw_row["sha256"]
    if type(digest) is not str or _SHA256.fullmatch(digest) is None:
        raise FanotifyRawParseError("raw_record.sha256 is not lowercase SHA-256 hex")
    if hashlib.sha256(raw).hexdigest() != digest:
        raise FanotifyRawParseError("raw_record.sha256 does not match decoded bytes")

    event_len, version, reserved, metadata_len, mask, fd, pid = _METADATA.unpack_from(raw)
    parsed_metadata = {
        "event_len": event_len,
        "vers": version,
        "reserved": reserved,
        "metadata_len": metadata_len,
        "mask": mask,
        "fd": fd,
        "pid": pid,
    }
    declared = _exact_object(
        declared_metadata,
        {"event_len", "vers", "reserved", "metadata_len", "mask", "fd", "pid"},
        "declared_metadata",
    )
    for key, value in parsed_metadata.items():
        if type(declared[key]) is not int or declared[key] != value:
            raise FanotifyRawParseError(f"declared_metadata.{key} disagrees with raw bytes")

    if event_len != len(raw):
        raise FanotifyRawParseError("raw metadata event_len does not equal the bounded record size")
    if version != METADATA_VERSION or reserved != 0 or metadata_len != METADATA_LEN:
        raise FanotifyRawParseError("raw metadata version, reserved byte, or metadata_len is unsupported")
    if mask not in SUPPORTED_SINGLE_EVENT_MASKS:
        raise FanotifyRawParseError("raw metadata mask is unknown, combined, or outside this profile")
    if fd != FAN_NOFD:
        raise FanotifyRawParseError("FID/name metadata.fd must be FAN_NOFD")
    if pid <= 0:
        raise FanotifyRawParseError("FID/name metadata.pid must be a positive process ID")

    parsed_infos: list[dict[str, Any]] = []
    parsed_summaries: list[dict[str, Any]] = []
    cursor = metadata_len
    while cursor < event_len:
        if event_len - cursor < _INFO_HEADER.size:
            raise FanotifyRawParseError("truncated fanotify info-record header")
        info_type, pad, info_len = _INFO_HEADER.unpack_from(raw, cursor)
        if pad != 0:
            raise FanotifyRawParseError("fanotify info-record header pad is non-zero")
        if info_len < _INFO_HEADER.size or info_len % 4 != 0 or info_len > event_len - cursor:
            raise FanotifyRawParseError("fanotify info-record length is invalid or out of bounds")
        record = raw[cursor:cursor + info_len]
        parsed_infos.append({"type": info_type, "len": info_len, "bytes": record})
        cursor += info_len

    if cursor != event_len:
        raise FanotifyRawParseError("info records do not consume the event exactly")
    actual_types = tuple(item["type"] for item in parsed_infos)
    if actual_types != EXPECTED_INFO_ORDER:
        raise FanotifyRawParseError("info-record sequence differs from the pinned Linux v6.8 writer profile")

    if type(declared_info_records) is not list or len(declared_info_records) != len(parsed_infos):
        raise FanotifyRawParseError("declared info-record count is not exactly three")
    for index, (parsed, declared_info) in enumerate(zip(parsed_infos, declared_info_records, strict=True)):
        row = _exact_object(declared_info, {"type", "len", "bytes_b64"}, f"declared_info_records[{index}]")
        declared_type = _integer(row["type"], f"declared_info_records[{index}].type", 0, 255)
        declared_len = _integer(row["len"], f"declared_info_records[{index}].len", 1, MAX_RAW_EVENT_BYTES)
        declared_bytes = _decode_canonical_b64(
            row["bytes_b64"], f"declared_info_records[{index}].bytes_b64", MAX_RAW_EVENT_BYTES,
        )
        if declared_type != parsed["type"] or declared_len != parsed["len"]:
            raise FanotifyRawParseError(f"declared_info_records[{index}] type or length disagrees with raw bytes")
        if declared_bytes != parsed["bytes"]:
            raise FanotifyRawParseError(f"declared_info_records[{index}] bytes disagree with raw stream")

        if index < 2:
            parsed_summaries.append(_parse_fid_record(parsed["bytes"], parsed["type"], index))
        else:
            if parsed["len"] != 8:
                raise FanotifyRawParseError("PIDFD info record must have the exact eight-byte UAPI length")
            pidfd = _I32.unpack_from(parsed["bytes"], 4)[0]
            if pidfd < 0:
                raise FanotifyRawParseError("PIDFD info record contains FAN_NOFD/FAN_EPIDFD sentinel")
            parsed_summaries.append({"info_type": INFO_PIDFD, "pidfd_number": pidfd})

    return {
        "schema": PARSER_SCHEMA,
        "status": "raw_bytes_reparsed_and_declarations_match_untrusted",
        "profile_id": PROFILE_ID,
        "raw_bytes_reparsed": True,
        "declarations_match_raw_bytes": True,
        "input_origin_authenticated": False,
        "target_kernel_source_pinned": False,
        "runtime_event_authenticated": False,
        "pidfd_task_join_authenticated": False,
        "fid_object_join_authenticated": False,
        "close_token_cookie_bridge_authenticated": False,
        "readiness_or_qualification_claim": False,
        "qualification_credit": 0,
        "metadata": parsed_metadata,
        "info_record_summaries": parsed_summaries,
    }
