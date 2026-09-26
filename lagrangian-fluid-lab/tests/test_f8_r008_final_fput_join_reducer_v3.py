from __future__ import annotations

import copy

import pytest

from scripts import f8_r008_final_fput_join_reducer_v3 as reducer_v3
from test_f8_r008_final_fput_join_reducer_v2 import _valid_input


def _timeline_row(
    journal_seq: int,
    kind: str,
    *,
    ref_id: str | None = None,
    group_seq: int | None = None,
    raw_event_sha256: str | None = None,
    syscall_seq: int | None = None,
    drained_to_eagain: bool | None = None,
    loss_count: int | None = None,
    overflow_count: int | None = None,
    short_read_count: int | None = None,
) -> dict:
    return {
        "journal_seq": journal_seq,
        "kind": kind,
        "ref_id": ref_id,
        "group_seq": group_seq,
        "raw_event_sha256": raw_event_sha256,
        "syscall_seq": syscall_seq,
        "drained_to_eagain": drained_to_eagain,
        "loss_count": loss_count,
        "overflow_count": overflow_count,
        "short_read_count": short_read_count,
    }


def _fixture() -> dict:
    diagnostic_input = _valid_input()
    context = diagnostic_input["close_context"]
    name_group = diagnostic_input["name_group"]
    first_event, close_event = name_group["events"]
    group_id = name_group["group_id"]
    rows = [
        _timeline_row(1, "cgroup_empty", ref_id=context["cgroup_empty_ref"]["ref_id"]),
        _timeline_row(
            2,
            "fanotify_event",
            group_seq=first_event["raw_row"]["group_seq"],
            raw_event_sha256=first_event["raw_row"]["raw_record"]["sha256"],
        ),
        _timeline_row(
            3,
            "pre_close_drain_eagain",
            ref_id="pre-close-eagain-1",
            group_seq=first_event["raw_row"]["group_seq"],
            drained_to_eagain=True,
            loss_count=0,
            overflow_count=0,
            short_read_count=0,
        ),
        _timeline_row(
            4,
            "close_entry",
            ref_id=context["close_token_ref"],
            syscall_seq=context["close_entry_seq"],
        ),
        # The reader may dequeue CLOSE_WRITE while close() is still in flight.
        _timeline_row(
            5,
            "fanotify_event",
            group_seq=close_event["raw_row"]["group_seq"],
            raw_event_sha256=close_event["raw_row"]["raw_record"]["sha256"],
        ),
        _timeline_row(
            6,
            "close_exit",
            ref_id=context["close_token_ref"],
            syscall_seq=context["close_exit_seq"],
        ),
        _timeline_row(
            7,
            "post_close_drain_eagain",
            ref_id="post-close-eagain-1",
            group_seq=name_group["last_group_seq"],
            drained_to_eagain=True,
            loss_count=0,
            overflow_count=0,
            short_read_count=0,
        ),
    ]
    return {
        "schema": reducer_v3.INPUT_SCHEMA,
        "diagnostic_input": diagnostic_input,
        "queue_journal": {
            "schema": reducer_v3.QUEUE_JOURNAL_SCHEMA,
            "attempt_id": diagnostic_input["attempt_id"],
            "journal_id": "attempt-journal-1",
            "group_id": group_id,
            "timeline_rows": rows,
        },
    }


def _resequence(value: dict, updates: dict[str, int]) -> None:
    rows = value["queue_journal"]["timeline_rows"]
    for row in rows:
        if row["kind"] in updates:
            row["journal_seq"] = updates[row["kind"]]
    rows.sort(key=lambda row: row["journal_seq"])


def _insert_journal_gap(value: dict) -> None:
    for row in value["queue_journal"]["timeline_rows"][2:]:
        row["journal_seq"] += 1


def test_v3_checks_declared_barrier_order_but_never_authenticates_it() -> None:
    result = reducer_v3.build_diagnostic_receipt(_fixture())

    assert result["schema"] == reducer_v3.RESULT_SCHEMA
    assert result["status"] == "diagnostic_raw_bytes_and_declared_queue_barrier_order_consistent_untrusted"
    assert result["pre_close_barrier_group_seq"] == 7
    assert result["post_close_barrier_group_seq"] == 8
    assert result["fanotify_close_write_group_seq"] == 8
    assert result["pre_close_event_count"] == 1
    assert result["post_barrier_event_count"] == 1
    assert result["queue_barrier_declared_order_consistent"] is True
    assert result["queue_barrier_source_authenticated"] is False
    assert result["shared_journal_contract_implemented"] is False
    assert result["fanotify_raw_bytes_reparsed"] is True
    assert result["final_close_claim"] is False
    assert result["trusted_observation"] is False
    assert result["observer_runtime_authenticated"] is False
    assert result["close_token_cookie_bridge_authenticated"] is False
    assert result["runtime_observation_authenticated"] is False
    assert result["readiness_pass"] is False
    assert result["T1_numerical"] is False
    assert result["execution_authority"] is False
    assert result["qualification_credit"] == 0


def test_v3_accepts_empty_preclose_queue_with_explicit_previous_watermark() -> None:
    value = _fixture()
    diagnostic_input = value["diagnostic_input"]
    name_group = diagnostic_input["name_group"]
    name_group["events"] = name_group["events"][1:]
    name_group["first_group_seq"] = 8
    name_group["last_group_seq"] = 8
    rows = value["queue_journal"]["timeline_rows"]
    rows[:] = [row for row in rows if row["kind"] != "fanotify_event" or row["group_seq"] == 8]
    for row in rows:
        if row["kind"] == "pre_close_drain_eagain":
            row["journal_seq"] = 2
            row["group_seq"] = 7
        elif row["kind"] == "close_entry":
            row["journal_seq"] = 3
        elif row["kind"] == "fanotify_event":
            row["journal_seq"] = 4
        elif row["kind"] == "close_exit":
            row["journal_seq"] = 5
        elif row["kind"] == "post_close_drain_eagain":
            row["journal_seq"] = 6
    rows.sort(key=lambda row: row["journal_seq"])

    result = reducer_v3.build_diagnostic_receipt(value)
    assert result["pre_close_barrier_group_seq"] == 7
    assert result["pre_close_event_count"] == 0
    assert result["post_barrier_event_count"] == 1


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda value: value["queue_journal"]["timeline_rows"][2].update(drained_to_eagain=False),
            "does not assert drain-to-EAGAIN",
        ),
        (
            lambda value: value["queue_journal"]["timeline_rows"][2].update(loss_count=1),
            "non-zero loss_count",
        ),
        (
            lambda value: value["queue_journal"]["timeline_rows"][1].update(raw_event_sha256="0" * 64),
            "digest differs",
        ),
        (
            lambda value: value["queue_journal"]["timeline_rows"].pop(1),
            "five lifecycle markers",
        ),
        (
            lambda value: value["queue_journal"].update(attempt_id="other-attempt"),
            "attempt does not match",
        ),
        (
            _insert_journal_gap,
            "gap, duplicate, or reordered",
        ),
        (
            lambda value: _resequence(value, {"close_entry": 3, "pre_close_drain_eagain": 4}),
            "lifecycle journal order is invalid",
        ),
        (
            lambda value: value["queue_journal"]["timeline_rows"][2].update(group_seq=8),
            "watermark does not match",
        ),
        (
            lambda value: value["queue_journal"]["timeline_rows"][6].update(group_seq=7),
            "watermark differs from the name-group end",
        ),
    ],
)
def test_v3_fails_closed_on_barrier_or_journal_mutations(mutate, message: str) -> None:
    value = copy.deepcopy(_fixture())
    mutate(value)
    with pytest.raises(reducer_v3.FinalFputJoinV3Error, match=message):
        reducer_v3.build_diagnostic_receipt(value)


def test_v3_rejects_target_close_write_ordered_before_close_entry() -> None:
    value = _fixture()
    rows = value["queue_journal"]["timeline_rows"]
    close_event = next(row for row in rows if row["kind"] == "fanotify_event" and row["group_seq"] == 8)
    close_entry = next(row for row in rows if row["kind"] == "close_entry")
    close_event["journal_seq"], close_entry["journal_seq"] = close_entry["journal_seq"], close_event["journal_seq"]
    rows.sort(key=lambda row: row["journal_seq"])
    with pytest.raises(reducer_v3.FinalFputJoinV3Error, match="disagrees with the name-group sequence|pre-barrier|precedes close entry"):
        reducer_v3.build_diagnostic_receipt(value)


def test_v3_accepts_close_event_dequeued_after_close_exit() -> None:
    value = _fixture()
    rows = value["queue_journal"]["timeline_rows"]
    close_event = next(row for row in rows if row["kind"] == "fanotify_event" and row["group_seq"] == 8)
    close_exit = next(row for row in rows if row["kind"] == "close_exit")
    close_event["journal_seq"], close_exit["journal_seq"] = close_exit["journal_seq"], close_event["journal_seq"]
    rows.sort(key=lambda row: row["journal_seq"])

    result = reducer_v3.build_diagnostic_receipt(value)
    assert result["fanotify_close_write_group_seq"] == 8
    assert result["queue_barrier_source_authenticated"] is False
