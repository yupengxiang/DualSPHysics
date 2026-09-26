from __future__ import annotations

import base64
import hashlib
import struct

import pytest

from scripts import f8_r008_fanotify_raw_parser_v1 as parser


_METADATA = struct.Struct("<IBBHQii")
_HEADER = struct.Struct("<BBH")


def _align4(data: bytes) -> bytes:
    return data + b"\0" * ((-len(data)) % 4)


def _fid_record(info_type: int, name: bytes | None = None) -> bytes:
    fsid = b"FSID0001"
    handle = b"\x12\x34\x56\x78"
    payload = fsid + struct.pack("<Ii", len(handle), 17) + handle
    if name is not None:
        payload += name + b"\0"
    record_len = 4 + len(_align4(payload))
    return _HEADER.pack(info_type, 0, record_len) + _align4(payload)


def _pidfd_record(pidfd: int = 9) -> bytes:
    return _HEADER.pack(parser.INFO_PIDFD, 0, 8) + struct.pack("<i", pidfd)


def _valid_raw(mask: int = parser.FAN_CLOSE_WRITE) -> bytes:
    infos = (
        _fid_record(parser.INFO_DFID_NAME, b"x.bin"),
        _fid_record(parser.INFO_FID),
        _pidfd_record(),
    )
    event_len = parser.METADATA_LEN + sum(map(len, infos))
    metadata = _METADATA.pack(event_len, 3, 0, 24, mask, -1, 1001)
    return metadata + b"".join(infos)


def _raw_record(raw: bytes) -> dict:
    return {
        "bytes_b64": base64.b64encode(raw).decode("ascii"),
        "byte_len": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _metadata(raw: bytes) -> dict:
    event_len, version, reserved, metadata_len, mask, fd, pid = _METADATA.unpack_from(raw)
    return {
        "event_len": event_len,
        "vers": version,
        "reserved": reserved,
        "metadata_len": metadata_len,
        "mask": mask,
        "fd": fd,
        "pid": pid,
    }


def _info_rows(raw: bytes) -> list[dict]:
    rows = []
    cursor = parser.METADATA_LEN
    while cursor < len(raw):
        _, _, size = _HEADER.unpack_from(raw, cursor)
        data = raw[cursor:cursor + size]
        rows.append({
            "type": data[0],
            "len": len(data),
            "bytes_b64": base64.b64encode(data).decode("ascii"),
        })
        cursor += size
    return rows


def _input(raw: bytes | None = None) -> tuple[dict, dict, list[dict]]:
    raw = _valid_raw() if raw is None else raw
    return _raw_record(raw), _metadata(raw), _info_rows(raw)


def _rebuild(raw: bytes, *, metadata_updates: dict | None = None) -> tuple[dict, dict, list[dict]]:
    raw_record, metadata, rows = _input(raw)
    if metadata_updates:
        metadata.update(metadata_updates)
    return raw_record, metadata, rows


def test_reparses_v17_single_path_events_and_matches_redundant_fields() -> None:
    for mask in (
        parser.FAN_CREATE,
        parser.FAN_MODIFY,
        parser.FAN_CLOSE_WRITE,
        parser.FAN_OPEN,
        parser.FAN_ACCESS,
        parser.FAN_CLOSE_NOWRITE,
    ):
        raw_record, metadata, rows = _input(_valid_raw(mask))
        result = parser.parse_declared_name_event(raw_record, metadata, rows)
        assert result["status"] == "raw_bytes_reparsed_and_declarations_match_untrusted"
        assert result["metadata"]["mask"] == mask
        assert [row["info_type"] for row in result["info_record_summaries"]] == [2, 1, 4]
        assert result["info_record_summaries"][0]["name_bytes"] == len(b"x.bin")
        assert result["raw_bytes_reparsed"] is True
        assert result["input_origin_authenticated"] is False
        assert result["target_kernel_source_pinned"] is False
        assert result["runtime_event_authenticated"] is False
        assert result["fid_object_join_authenticated"] is False
        assert result["close_token_cookie_bridge_authenticated"] is False
        assert result["readiness_or_qualification_claim"] is False
        assert result["qualification_credit"] == 0


def test_rejects_forged_declared_metadata_and_info_bytes() -> None:
    raw_record, metadata, rows = _input()
    changed_metadata = dict(metadata, mask=parser.FAN_MODIFY)
    with pytest.raises(parser.FanotifyRawParseError, match="mask disagrees with raw bytes"):
        parser.parse_declared_name_event(raw_record, changed_metadata, rows)

    changed_rows = [dict(row) for row in rows]
    changed_rows[1]["bytes_b64"] = base64.b64encode(b"forged!!!").decode("ascii")
    with pytest.raises(parser.FanotifyRawParseError, match="bytes disagree with raw stream"):
        parser.parse_declared_name_event(raw_record, metadata, changed_rows)


@pytest.mark.parametrize(
    ("raw_mutator", "metadata_updates", "message"),
    [
        (lambda b: b.__setitem__(4, 2), None, "declarations match|version"),
        (lambda b: b.__setitem__(5, 1), {"reserved": 1}, "reserved byte"),
        (lambda b: b.__setitem__(6, 25), {"metadata_len": 25}, "metadata_len"),
        (lambda b: b.__setitem__(8, 4), {"mask": 4}, "mask is unknown"),
        (lambda b: b.__setitem__(8, 3), {"mask": 3}, "mask is unknown"),
        (lambda b: b.__setitem__(16, 8), {"fd": 8}, "metadata.fd"),
        (lambda b: b.__setitem__(20, 0), {"pid": 0}, "metadata.pid"),
    ],
)
def test_rejects_unsupported_raw_metadata(raw_mutator, metadata_updates, message: str) -> None:
    raw = bytearray(_valid_raw())
    raw_mutator(raw)
    raw_record, metadata, rows = _rebuild(bytes(raw), metadata_updates=metadata_updates)
    with pytest.raises(parser.FanotifyRawParseError, match=message):
        parser.parse_declared_name_event(raw_record, metadata, rows)


def test_rejects_raw_event_len_mismatch_and_digest_mismatch() -> None:
    raw_record, metadata, rows = _input()
    raw_record["byte_len"] += 1
    with pytest.raises(parser.FanotifyRawParseError, match="byte_len"):
        parser.parse_declared_name_event(raw_record, metadata, rows)

    raw_record, metadata, rows = _input()
    raw_record["sha256"] = "0" * 64
    with pytest.raises(parser.FanotifyRawParseError, match="sha256 does not match"):
        parser.parse_declared_name_event(raw_record, metadata, rows)


@pytest.mark.parametrize(
    ("offset", "value", "message"),
    [
        (25, 1, "header pad is non-zero"),
        (26, 7, "length is invalid"),
    ],
)
def test_rejects_malformed_info_headers(offset: int, value: int, message: str) -> None:
    raw = bytearray(_valid_raw())
    raw[offset] = value
    raw_record, metadata, rows = _rebuild(bytes(raw))
    with pytest.raises(parser.FanotifyRawParseError, match=message):
        parser.parse_declared_name_event(raw_record, metadata, rows)


def test_rejects_nonzero_fid_padding_and_invalid_file_handle_length() -> None:
    raw = bytearray(_valid_raw())
    raw[24 + 4 + 8 + 8 + 4 + 5 + 1] = 1  # non-zero alignment byte after "x.bin\\0"
    raw_record, metadata, rows = _rebuild(bytes(raw))
    with pytest.raises(parser.FanotifyRawParseError, match="non-zero alignment padding"):
        parser.parse_declared_name_event(raw_record, metadata, rows)

    raw = bytearray(_valid_raw())
    struct.pack_into("<I", raw, 24 + 12, 200)
    raw_record, metadata, rows = _rebuild(bytes(raw))
    with pytest.raises(parser.FanotifyRawParseError, match="outside the profile bound"):
        parser.parse_declared_name_event(raw_record, metadata, rows)


def test_rejects_invalid_pidfd_sentinel_and_non_v68_record_order() -> None:
    raw = bytearray(_valid_raw())
    raw[-4:] = struct.pack("<i", -2)
    raw_record, metadata, rows = _rebuild(bytes(raw))
    with pytest.raises(parser.FanotifyRawParseError, match="PIDFD.*sentinel"):
        parser.parse_declared_name_event(raw_record, metadata, rows)

    valid = _valid_raw()
    first_len = _HEADER.unpack_from(valid, 24)[2]
    second_offset = 24 + first_len
    second_len = _HEADER.unpack_from(valid, second_offset)[2]
    reordered = valid[:24] + valid[second_offset:second_offset + second_len] + valid[24:24 + first_len] + valid[second_offset + second_len:]
    raw_record, metadata, rows = _rebuild(reordered)
    with pytest.raises(parser.FanotifyRawParseError, match="sequence differs"):
        parser.parse_declared_name_event(raw_record, metadata, rows)


def test_rejects_invalid_base64_and_declared_schema_extensions() -> None:
    raw_record, metadata, rows = _input()
    raw_record["bytes_b64"] += "!"
    with pytest.raises(parser.FanotifyRawParseError, match="strict base64"):
        parser.parse_declared_name_event(raw_record, metadata, rows)

    raw_record, metadata, rows = _input()
    metadata["surprise"] = True
    with pytest.raises(parser.FanotifyRawParseError, match="fields differ"):
        parser.parse_declared_name_event(raw_record, metadata, rows)


def test_structural_parse_does_not_invent_filesystem_identity_semantics() -> None:
    raw = bytearray(_valid_raw())
    raw[24 + 4:24 + 12] = b"\0" * 8
    raw_record, metadata, rows = _rebuild(bytes(raw))
    result = parser.parse_declared_name_event(raw_record, metadata, rows)
    assert result["info_record_summaries"][0]["fsid_sha256"] == hashlib.sha256(b"\0" * 8).hexdigest()
    assert result["fid_object_join_authenticated"] is False

    raw_record, metadata, rows = _input()
    metadata["fd"] = True
    with pytest.raises(parser.FanotifyRawParseError, match="metadata.fd disagrees"):
        parser.parse_declared_name_event(raw_record, metadata, rows)


def test_rejects_oversized_event_before_parsing() -> None:
    raw = b"\0" * (parser.MAX_RAW_EVENT_BYTES + 1)
    raw_record = _raw_record(raw)
    with pytest.raises(parser.FanotifyRawParseError, match="size bound"):
        parser.parse_declared_name_event(raw_record, {}, [])
