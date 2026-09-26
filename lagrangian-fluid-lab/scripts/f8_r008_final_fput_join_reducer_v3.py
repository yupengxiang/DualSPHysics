#!/usr/bin/env python3
"""Add a caller-declared shared-journal/barrier check to the v2 diagnostic.

This prototype does not define or authenticate a runtime journal.  It checks
only that an explicitly supplied, single sequence-domain declaration is
internally consistent with the v2 raw-event diagnostic input.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from scripts import f8_r008_final_fput_join_reducer_v2 as reducer_v2


INPUT_SCHEMA = "core.cfd.f8.r008_final_fput_join_barrier_input.v3"
QUEUE_JOURNAL_SCHEMA = "f8-final-fput-queue-journal-v1"
RESULT_SCHEMA = "core.cfd.f8.r008_final_fput_join_diagnostic.v3"
MAX_TIMELINE_ROWS = 4101  # v2 name-group maximum plus five lifecycle markers.
MAX_U64 = (1 << 64) - 1
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class FinalFputJoinV3Error(ValueError):
    """Input fails the v2 diagnostic or the declared queue-barrier checks."""


def _exact_object(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise FinalFputJoinV3Error(f"{label} must be an exact JSON object")
    actual = set(value)
    if actual != fields:
        raise FinalFputJoinV3Error(
            f"{label} fields differ (missing={sorted(fields - actual)}, extra={sorted(actual - fields)})"
        )
    return value


def _text(value: Any, label: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise FinalFputJoinV3Error(f"{label} must be a non-empty canonical string")
    try:
        size = len(value.encode("utf-8", errors="strict"))
    except UnicodeEncodeError as error:
        raise FinalFputJoinV3Error(f"{label} is not valid UTF-8") from error
    if size > 1024:
        raise FinalFputJoinV3Error(f"{label} exceeds the fixed text-size bound")
    return value


def _uint(value: Any, label: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise FinalFputJoinV3Error(f"{label} must be an exact integer >= {minimum}")
    if value > MAX_U64:
        raise FinalFputJoinV3Error(f"{label} exceeds the unsigned 64-bit bound")
    return value


def _sha256(value: Any, label: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise FinalFputJoinV3Error(f"{label} must be lowercase SHA-256 hex")
    return value


def _nulls(row: dict[str, Any], fields: tuple[str, ...], label: str) -> None:
    if any(row[field] is not None for field in fields):
        raise FinalFputJoinV3Error(f"{label} contains fields that are not valid for its row kind")


def _validate_queue_journal(
    value: Any,
    diagnostic_input: dict[str, Any],
    base_receipt: dict[str, Any],
) -> dict[str, Any]:
    journal = _exact_object(
        value,
        {"schema", "attempt_id", "journal_id", "group_id", "timeline_rows"},
        "queue_journal",
    )
    attempt_id = diagnostic_input["attempt_id"]
    name_group = diagnostic_input["name_group"]
    context = diagnostic_input["close_context"]
    if journal["schema"] != QUEUE_JOURNAL_SCHEMA or journal["attempt_id"] != attempt_id:
        raise FinalFputJoinV3Error("queue_journal schema or attempt does not match")
    _text(journal["journal_id"], "queue_journal.journal_id")
    if journal["group_id"] != name_group["group_id"]:
        raise FinalFputJoinV3Error("queue_journal group does not match the v2 name group")

    rows = journal["timeline_rows"]
    expected_count = len(name_group["events"]) + 5
    if type(rows) is not list or len(rows) != expected_count or len(rows) > MAX_TIMELINE_ROWS:
        raise FinalFputJoinV3Error("timeline_rows must cover each name event and five lifecycle markers")

    row_fields = {
        "journal_seq", "kind", "ref_id", "group_seq", "raw_event_sha256", "syscall_seq",
        "drained_to_eagain", "loss_count", "overflow_count", "short_read_count",
    }
    events_by_group_seq: dict[int, dict[str, Any]] = {}
    markers: dict[str, dict[str, Any]] = {}
    for index, candidate in enumerate(rows):
        row = _exact_object(candidate, row_fields, f"timeline_rows[{index}]")
        sequence = _uint(row["journal_seq"], f"timeline_rows[{index}].journal_seq", minimum=1)
        if sequence != index + 1:
            raise FinalFputJoinV3Error("timeline journal_seq has a gap, duplicate, or reordered row")
        kind = row["kind"]
        if type(kind) is not str:
            raise FinalFputJoinV3Error(f"timeline_rows[{index}].kind must be text")

        if kind == "fanotify_event":
            group_seq = _uint(row["group_seq"], f"timeline_rows[{index}].group_seq", minimum=1)
            raw_digest = _sha256(row["raw_event_sha256"], f"timeline_rows[{index}].raw_event_sha256")
            _nulls(row, ("ref_id", "syscall_seq", "drained_to_eagain", "loss_count", "overflow_count", "short_read_count"), "fanotify_event")
            if group_seq in events_by_group_seq:
                raise FinalFputJoinV3Error("timeline duplicates a fanotify group_seq")
            events_by_group_seq[group_seq] = {**row, "raw_event_sha256": raw_digest}
            continue

        if kind == "cgroup_empty":
            if "cgroup_empty" in markers:
                raise FinalFputJoinV3Error("timeline duplicates cgroup_empty")
            if row["ref_id"] != context["cgroup_empty_ref"]["ref_id"]:
                raise FinalFputJoinV3Error("timeline cgroup_empty ref differs from close context")
            _nulls(row, ("group_seq", "raw_event_sha256", "syscall_seq", "drained_to_eagain", "loss_count", "overflow_count", "short_read_count"), "cgroup_empty")
            markers[kind] = row
            continue

        if kind in {"pre_close_drain_eagain", "post_close_drain_eagain"}:
            if kind in markers:
                raise FinalFputJoinV3Error(f"timeline duplicates {kind}")
            _text(row["ref_id"], f"timeline_rows[{index}].ref_id")
            _uint(row["group_seq"], f"timeline_rows[{index}].group_seq")
            if row["raw_event_sha256"] is not None or row["syscall_seq"] is not None:
                raise FinalFputJoinV3Error(f"{kind} carries an invalid event/syscall reference")
            if row["drained_to_eagain"] is not True:
                raise FinalFputJoinV3Error(f"{kind} does not assert drain-to-EAGAIN")
            for counter in ("loss_count", "overflow_count", "short_read_count"):
                if _uint(row[counter], f"{kind}.{counter}") != 0:
                    raise FinalFputJoinV3Error(f"{kind} reports non-zero {counter}")
            markers[kind] = row
            continue

        if kind in {"close_entry", "close_exit"}:
            if kind in markers:
                raise FinalFputJoinV3Error(f"timeline duplicates {kind}")
            if row["ref_id"] != context["close_token_ref"]:
                raise FinalFputJoinV3Error(f"timeline {kind} token differs from close context")
            expected_syscall_seq = context["close_entry_seq" if kind == "close_entry" else "close_exit_seq"]
            if _uint(row["syscall_seq"], f"{kind}.syscall_seq", minimum=1) != expected_syscall_seq:
                raise FinalFputJoinV3Error(f"timeline {kind} syscall sequence differs from close context")
            _nulls(row, ("group_seq", "raw_event_sha256", "drained_to_eagain", "loss_count", "overflow_count", "short_read_count"), kind)
            markers[kind] = row
            continue

        raise FinalFputJoinV3Error(f"timeline_rows[{index}] has an unsupported kind")

    expected_marker_kinds = {
        "cgroup_empty", "pre_close_drain_eagain", "close_entry", "close_exit", "post_close_drain_eagain",
    }
    if set(markers) != expected_marker_kinds:
        raise FinalFputJoinV3Error("timeline is missing one or more lifecycle markers")

    expected_events = {
        event["raw_row"]["group_seq"]: event["raw_row"]["raw_record"]["sha256"]
        for event in name_group["events"]
    }
    if set(events_by_group_seq) != set(expected_events):
        raise FinalFputJoinV3Error("timeline fanotify rows do not exactly cover the v2 name-group events")
    for group_seq, raw_digest in expected_events.items():
        if events_by_group_seq[group_seq]["raw_event_sha256"] != raw_digest:
            raise FinalFputJoinV3Error("timeline fanotify row digest differs from its raw event")

    event_rows = sorted(events_by_group_seq.values(), key=lambda row: row["journal_seq"])
    group_sequences = [row["group_seq"] for row in event_rows]
    if group_sequences != sorted(group_sequences):
        raise FinalFputJoinV3Error("journal order disagrees with the name-group sequence")

    pre_barrier = markers["pre_close_drain_eagain"]
    post_barrier = markers["post_close_drain_eagain"]
    if pre_barrier["ref_id"] == post_barrier["ref_id"]:
        raise FinalFputJoinV3Error("pre-close and post-close drain refs must be distinct")
    close_entry = markers["close_entry"]
    close_exit = markers["close_exit"]
    cgroup_empty = markers["cgroup_empty"]
    first_group_seq = name_group["first_group_seq"]
    last_group_seq = name_group["last_group_seq"]
    pre_group_seq = pre_barrier["group_seq"]

    if not (
        cgroup_empty["journal_seq"] < pre_barrier["journal_seq"]
        < close_entry["journal_seq"] < close_exit["journal_seq"]
        < post_barrier["journal_seq"]
    ):
        raise FinalFputJoinV3Error("cgroup/barrier/close lifecycle journal order is invalid")
    pre_events = [row for row in event_rows if row["journal_seq"] < pre_barrier["journal_seq"]]
    post_events = [row for row in event_rows if row["journal_seq"] > pre_barrier["journal_seq"]]
    expected_pre_watermark = max((row["group_seq"] for row in pre_events), default=first_group_seq - 1)
    if pre_group_seq != expected_pre_watermark:
        raise FinalFputJoinV3Error("pre-close EAGAIN watermark does not match the drained event prefix")
    if any(row["group_seq"] > pre_group_seq for row in pre_events):
        raise FinalFputJoinV3Error("pre-close drain contains an event beyond its EAGAIN watermark")
    if any(row["group_seq"] <= pre_group_seq for row in post_events):
        raise FinalFputJoinV3Error("post-barrier journal contains an event at or before the EAGAIN watermark")
    if post_barrier["group_seq"] != last_group_seq:
        raise FinalFputJoinV3Error("post-close EAGAIN watermark differs from the name-group end")
    if any(row["journal_seq"] <= close_entry["journal_seq"] for row in post_events):
        raise FinalFputJoinV3Error("post-barrier event journal entry precedes close entry")
    if any(row["journal_seq"] >= post_barrier["journal_seq"] for row in event_rows):
        raise FinalFputJoinV3Error("post-close EAGAIN marker precedes a captured fanotify event")

    close_group_seq = base_receipt["fanotify_close_write_group_seq"]
    if close_group_seq <= pre_group_seq:
        raise FinalFputJoinV3Error("target FAN_CLOSE_WRITE is not after the pre-close barrier")
    if events_by_group_seq[close_group_seq]["journal_seq"] <= close_entry["journal_seq"]:
        raise FinalFputJoinV3Error("target FAN_CLOSE_WRITE journal row precedes close entry")

    return {
        "journal_id": journal["journal_id"],
        "pre_close_barrier_group_seq": pre_group_seq,
        "post_close_barrier_group_seq": post_barrier["group_seq"],
        "fanotify_close_write_group_seq": close_group_seq,
        "pre_close_event_count": len(pre_events),
        "post_barrier_event_count": len(post_events),
        "queue_barrier_declared_order_consistent": True,
        "queue_barrier_source_authenticated": False,
        "shared_journal_contract_implemented": False,
    }


def build_diagnostic_receipt(value: Any) -> dict[str, Any]:
    """Validate v2 byte consistency plus an untrusted shared-journal claim."""
    top = _exact_object(value, {"schema", "diagnostic_input", "queue_journal"}, "join input")
    if top["schema"] != INPUT_SCHEMA:
        raise FinalFputJoinV3Error("join input schema is unsupported")
    diagnostic_input = top["diagnostic_input"]
    try:
        base = reducer_v2.build_diagnostic_receipt(diagnostic_input)
    except reducer_v2.FinalFputJoinV2Error as error:
        raise FinalFputJoinV3Error(str(error)) from error
    journal_summary = _validate_queue_journal(top["queue_journal"], diagnostic_input, base)
    try:
        canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8", errors="strict")
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise FinalFputJoinV3Error("join input is not canonicalizable JSON data") from error
    result = {
        **base,
        "schema": RESULT_SCHEMA,
        "status": "diagnostic_raw_bytes_and_declared_queue_barrier_order_consistent_untrusted",
        **journal_summary,
    }
    result["input_sha256"] = hashlib.sha256(canonical).hexdigest()
    return result
