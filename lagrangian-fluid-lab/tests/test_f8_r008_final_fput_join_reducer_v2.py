from __future__ import annotations

import base64
import copy
import hashlib
import struct

import pytest

from scripts import f8_r008_final_fput_join_reducer_v2 as reducer_v2
from test_f8_r008_final_fput_join_reducer_v1 import _fixture, _sha


_METADATA = struct.Struct("<IBBHQii")
_HEADER = struct.Struct("<BBH")


def _fid_record(info_type: int, fsid: bytes, handle: bytes, name: bytes | None = None) -> bytes:
    payload = fsid + struct.pack("<Ii", len(handle), 17) + handle
    if name is not None:
        payload += name + b"\0"
    padding = b"\0" * ((-len(payload)) % 4)
    length = _HEADER.size + len(payload) + len(padding)
    return _HEADER.pack(info_type, 0, length) + payload + padding


def _event_bytes(mask: int, fsid: bytes, target_handle: bytes, pidfd: int = 9) -> bytes:
    records = (
        _fid_record(2, fsid, b"parent-handle", b"result.bin"),
        _fid_record(1, fsid, target_handle),
        _HEADER.pack(4, 0, 8) + struct.pack("<i", pidfd),
    )
    event_len = 24 + sum(map(len, records))
    return _METADATA.pack(event_len, 3, 0, 24, mask, -1, 1001) + b"".join(records)


def _raw_record(raw: bytes) -> dict:
    return {
        "bytes_b64": base64.b64encode(raw).decode("ascii"),
        "byte_len": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _info_rows(raw: bytes) -> list[dict]:
    result = []
    cursor = 24
    while cursor < len(raw):
        _, _, size = _HEADER.unpack_from(raw, cursor)
        record = raw[cursor:cursor + size]
        result.append({
            "type": record[0],
            "len": len(record),
            "bytes_b64": base64.b64encode(record).decode("ascii"),
        })
        cursor += size
    return result


def _valid_input() -> dict:
    value = copy.deepcopy(_fixture())
    object_id = value["close_context"]["object_ref"]["object_id"]
    fsid = b"fsid-v2!"
    target_handle = f"handle:{object_id}".encode("ascii")
    fsid_digest = _sha(fsid)
    handle_digest = _sha(target_handle)

    value["close_context"]["object_ref"]["fsid_sha256"] = fsid_digest
    value["close_context"]["object_ref"]["file_handle_sha256"] = handle_digest
    for event in value["name_group"]["events"]:
        raw_row = event["raw_row"]
        raw = _event_bytes(raw_row["metadata"]["mask"], fsid, target_handle)
        event_len, version, reserved, metadata_len, mask, fd, pid = _METADATA.unpack_from(raw)
        raw_row["raw_record"] = _raw_record(raw)
        raw_row["metadata"] = {
            "event_len": event_len,
            "vers": version,
            "reserved": reserved,
            "metadata_len": metadata_len,
            "mask": mask,
            "fd": fd,
            "pid": pid,
        }
        raw_row["info_records"] = _info_rows(raw)
        event["object_join"]["object_ref"]["fsid_sha256"] = fsid_digest
        event["object_join"]["object_ref"]["file_handle_sha256"] = handle_digest
        event["pidfd_action"]["pidfd_info_index"] = 2
        event["pidfd_action"]["pidfd_number"] = 9
        event["pidfd_action"]["metadata_pid"] = pid
    return value


def test_v2_reparses_all_events_and_keeps_authority_false() -> None:
    result = reducer_v2.build_diagnostic_receipt(_valid_input())
    assert result["schema"] == reducer_v2.RESULT_SCHEMA
    assert result["status"] == "diagnostic_raw_bytes_and_declared_links_consistent_untrusted"
    assert result["fanotify_raw_bytes_reparsed"] is True
    assert len(result["fanotify_raw_parse_event_summaries"]) == 2
    assert [row["mask"] for row in result["fanotify_raw_parse_event_summaries"]] == [2, 8]
    assert all(row["target_fid_digests_match_declared_object_claim"] for row in result["fanotify_raw_parse_event_summaries"])
    assert all(row["pidfd_value_matches_action_claim"] for row in result["fanotify_raw_parse_event_summaries"])
    assert result["fid_object_join_authenticated"] is False
    assert result["parent_mark_identity_join_authenticated"] is False
    assert result["pidfd_task_join_authenticated"] is False
    assert result["close_token_cookie_bridge_authenticated"] is False
    assert result["runtime_observation_authenticated"] is False
    assert result["final_close_claim"] is False
    assert result["readiness_pass"] is False
    assert result["T1_numerical"] is False
    assert result["execution_authority"] is False
    assert result["qualification_credit"] == 0
    assert len(result["input_sha256"]) == 64


def test_v2_rejects_raw_payload_that_v1_only_checks_by_declaration() -> None:
    value = _valid_input()
    raw_row = value["name_group"]["events"][1]["raw_row"]
    raw = bytearray(base64.b64decode(raw_row["raw_record"]["bytes_b64"]))
    raw[-1] ^= 1  # PIDFD byte changes; raw digest follows, declared row bytes do not.
    raw_row["raw_record"] = _raw_record(bytes(raw))
    with pytest.raises(reducer_v2.FinalFputJoinV2Error, match="bytes disagree with raw stream"):
        reducer_v2.build_diagnostic_receipt(value)


def test_v2_binds_target_fid_digests_to_object_claim_but_not_object_identity() -> None:
    value = _valid_input()
    wrong_digest = _sha(b"not-the-raw-fsid")
    value["close_context"]["object_ref"]["fsid_sha256"] = wrong_digest
    for event in value["name_group"]["events"]:
        event["object_join"]["object_ref"]["fsid_sha256"] = wrong_digest
    with pytest.raises(reducer_v2.FinalFputJoinV2Error, match="target FID bytes differ"):
        reducer_v2.build_diagnostic_receipt(value)


def test_v2_requires_parent_and_target_fids_to_share_fsid_bytes() -> None:
    value = _valid_input()
    raw_row = value["name_group"]["events"][1]["raw_row"]
    raw = bytearray(base64.b64decode(raw_row["raw_record"]["bytes_b64"]))
    raw[24 + 4:24 + 12] = b"other-fs"
    raw_row["raw_record"] = _raw_record(bytes(raw))
    raw_row["info_records"] = _info_rows(bytes(raw))
    with pytest.raises(reducer_v2.FinalFputJoinV2Error, match="parent and target FID FSID"):
        reducer_v2.build_diagnostic_receipt(value)


def test_v2_binds_raw_pidfd_number_to_action_declaration() -> None:
    value = _valid_input()
    value["name_group"]["events"][1]["pidfd_action"]["pidfd_number"] = 10
    with pytest.raises(reducer_v2.FinalFputJoinV2Error, match="PIDFD action differs"):
        reducer_v2.build_diagnostic_receipt(value)


def test_v2_rejects_reordered_wire_info_even_if_v1_multiset_accepts() -> None:
    value = _valid_input()
    raw_row = value["name_group"]["events"][0]["raw_row"]
    raw = base64.b64decode(raw_row["raw_record"]["bytes_b64"])
    first_size = _HEADER.unpack_from(raw, 24)[2]
    second_start = 24 + first_size
    second_size = _HEADER.unpack_from(raw, second_start)[2]
    reordered = raw[:24] + raw[second_start:second_start + second_size] + raw[24:24 + first_size] + raw[second_start + second_size:]
    raw_row["raw_record"] = _raw_record(reordered)
    raw_row["info_records"] = _info_rows(reordered)
    with pytest.raises(reducer_v2.FinalFputJoinV2Error, match="sequence differs"):
        reducer_v2.build_diagnostic_receipt(value)


def test_v2_preserves_v1_strict_rejection() -> None:
    with pytest.raises(reducer_v2.FinalFputJoinV2Error, match="observer_rows"):
        reducer_v2.build_diagnostic_receipt({"schema": "wrong"})
