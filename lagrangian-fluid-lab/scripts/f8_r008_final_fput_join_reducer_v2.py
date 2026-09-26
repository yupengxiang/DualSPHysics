#!/usr/bin/env python3
"""Add bounded raw fanotify parsing to the v1 untrusted F8 join diagnostic.

This wrapper adds byte/declaration consistency only. It does not authenticate
any producer, runtime source, identity join, close/fput relation, or readiness.
"""
from __future__ import annotations

from typing import Any

from scripts import f8_r008_fanotify_raw_parser_v1 as raw_parser
from scripts import f8_r008_final_fput_join_reducer_v1 as declared_reducer


RESULT_SCHEMA = "core.cfd.f8.r008_final_fput_join_diagnostic.v2"


class FinalFputJoinV2Error(ValueError):
    """Input fails the v1 declared-link checks or v2 raw-byte checks."""


def build_diagnostic_receipt(value: Any) -> dict[str, Any]:
    """Reconcile a synthetic input and reparse every declared fanotify event."""
    try:
        base = declared_reducer.build_diagnostic_receipt(value)
    except declared_reducer.FinalFputJoinError as error:
        raise FinalFputJoinV2Error(str(error)) from error

    summaries: list[dict[str, Any]] = []
    for index, event in enumerate(value["name_group"]["events"]):
        raw_row = event["raw_row"]
        try:
            parsed = raw_parser.parse_declared_name_event(
                raw_row["raw_record"], raw_row["metadata"], raw_row["info_records"],
            )
        except raw_parser.FanotifyRawParseError as error:
            raise FinalFputJoinV2Error(
                f"name_group.events[{index}] raw UAPI parse failed: {error}"
            ) from error

        action = event["pidfd_action"]
        parsed_pidfd = parsed["info_record_summaries"][2]["pidfd_number"]
        if action["pidfd_info_index"] != 2 or action["pidfd_number"] != parsed_pidfd:
            raise FinalFputJoinV2Error(
                f"name_group.events[{index}] PIDFD action differs from raw PIDFD bytes"
            )
        if action["metadata_pid"] != parsed["metadata"]["pid"]:
            raise FinalFputJoinV2Error(
                f"name_group.events[{index}] PIDFD metadata PID differs from raw bytes"
            )

        parent_fid = parsed["info_record_summaries"][0]
        target_fid = parsed["info_record_summaries"][1]
        if parent_fid["fsid_sha256"] != target_fid["fsid_sha256"]:
            raise FinalFputJoinV2Error(
                f"name_group.events[{index}] parent and target FID FSID bytes differ"
            )
        claimed_object = event["object_join"]["object_ref"]
        if (
            claimed_object["fsid_sha256"] != target_fid["fsid_sha256"]
            or claimed_object["file_handle_sha256"] != target_fid["handle_sha256"]
        ):
            raise FinalFputJoinV2Error(
                f"name_group.events[{index}] target FID bytes differ from declared object digests"
            )

        summaries.append({
            "group_seq": raw_row["group_seq"],
            "mask": parsed["metadata"]["mask"],
            "metadata_pid": parsed["metadata"]["pid"],
            "parent_fid_summary": parent_fid,
            "target_fid_summary": target_fid,
            "pidfd_number": parsed_pidfd,
            "raw_bytes_reparsed": True,
            "declared_rows_match_raw_bytes": True,
            "target_fid_digests_match_declared_object_claim": True,
            "pidfd_value_matches_action_claim": True,
        })

    # Keep every authorization/trust field fail-closed; v2 only adds a
    # structural join over caller-supplied raw bytes and declared values.
    return {
        **base,
        "schema": RESULT_SCHEMA,
        "status": "diagnostic_raw_bytes_and_declared_links_consistent_untrusted",
        "fanotify_raw_bytes_reparsed": True,
        "fanotify_raw_parse_event_summaries": summaries,
        "fid_object_join_authenticated": False,
        "parent_mark_identity_join_authenticated": False,
        "pidfd_task_join_authenticated": False,
        "close_token_cookie_bridge_authenticated": False,
        "runtime_observation_authenticated": False,
        "readiness_pass": False,
        "T1_numerical": False,
        "execution_authority": False,
        "qualification_credit": 0,
    }
