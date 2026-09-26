from __future__ import annotations

import base64
import copy
import hashlib

import pytest

from scripts import f8_r008_final_fput_join_reducer_v1 as reducer


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _object_ref(object_id: str = "output-object-1", *, generation: str = "inode-generation-1") -> dict:
    return {
        "object_id": object_id,
        "mount_id": 41,
        "fsid_sha256": _sha(b"fsid-1"),
        "file_handle_sha256": _sha(object_id.encode()),
        "generation": generation,
    }


def _loss_epoch(epoch_id: str = "epoch-1") -> dict:
    return {
        "schema": reducer.LOSS_EPOCH_SCHEMA,
        "epochs": [{
            "producer_id": "observer-producer-0",
            "cpu_id": 0,
            "epoch_id": epoch_id,
            "producer_lost": 0,
            "buffer_overrun": 0,
            "sequence_gap": 0,
            "reader_lag": 0,
        }],
    }


def _observer_row(event_kind: str, hook_seq: int, monotonic_ns: int) -> dict:
    return {
        "schema": reducer.OBSERVER_ROW_SCHEMA,
        "attempt_id": "attempt-1",
        "observer_profile_id": "profile-1",
        "kernel_build_id": "build-id-1",
        "kernel_source_commit": "source-commit-1",
        "hook_id": f"hook-{event_kind}",
        "hook_seq": hook_seq,
        "monotonic_ns": monotonic_ns,
        "task_generation": "task-generation-1",
        "fd_number": 17,
        "fd_generation": 3,
        "open_token_ref": "open-token-1",
        "file_cookie_digest": _sha(b"opaque-file-cookie"),
        "object_ref": "output-object-1",
        "event_kind": event_kind,
        "raw_args_digest": _sha(event_kind.encode()),
        "raw_return": None,
        "loss_epoch": _loss_epoch(),
        "producer_lost": 0,
        "buffer_overrun": 0,
        "sequence_gap": 0,
        "reader_lag": 0,
    }


def _info_records() -> list[dict]:
    return [
        {"type": event_type, "len": 8, "bytes_b64": base64.b64encode(bytes([event_type]) * 8).decode("ascii")}
        for event_type in (1, 2, 4)
    ]


def _fanotify_event(group_seq: int, mask: int, object_id: str, close_token_ref: str | None) -> dict:
    raw = f"synthetic-event-{group_seq}".encode("ascii").ljust(64, b"\0")
    object_ref = _object_ref(object_id)
    return {
        "raw_row": {
        "schema": reducer.FANOTIFY_RAW_SCHEMA,
            "attempt_id": "attempt-1",
            "group_id": "name-group-1",
            "group_kind": "name",
            "group_seq": group_seq,
            "read_seq": 5,
            "raw_record": {
                "bytes_b64": base64.b64encode(raw).decode("ascii"),
                "byte_len": len(raw),
                "sha256": _sha(raw),
            },
            "metadata": {
                "event_len": len(raw),
                "vers": 3,
                "reserved": 0,
                "metadata_len": reducer.FANOTIFY_METADATA_SIZE_X86_64,
                "mask": mask,
                "fd": reducer.FAN_NOFD,
                "pid": 1001,
            },
            "info_records": _info_records(),
            "mark_inventory_digest": _sha(b"marks-1"),
            "actor_pidfd_ref": f"held-pidfd-{group_seq}",
            "event_fd_ref": None,
        },
        "object_join": {
            "schema": reducer.FANOTIFY_OBJECT_JOIN_SCHEMA,
            "attempt_id": "attempt-1",
            "group_id": "name-group-1",
            "group_seq": group_seq,
            "object_ref": object_ref,
            "marked_parent_refs": ["parent-directory-1"],
            "join_basis": "synthetic-fid-fsid-handle-generation-and-dfid-name",
        },
        "pidfd_action": {
            "schema": "f8-fanotify-pidfd-action-v1",
            "attempt_id": "attempt-1",
            "group_id": "name-group-1",
            "group_seq": group_seq,
            "pidfd_info_index": 2,
            "pidfd_number": 61 + group_seq,
            "fdinfo_raw_bytes_b64": base64.b64encode(b"Pid:\t1001\n").decode("ascii"),
            "metadata_pid": 1001,
            "task_generation_ref": "task-generation-1",
            "held_pidfd_ref": f"held-pidfd-{group_seq}",
            "close_ret": 0,
            "close_errno": 0,
        },
        "close_token_ref": close_token_ref,
    }


def _fixture() -> dict:
    final_write_refs = ["last-write-1", "last-write-2"]
    terminal_exit_ref = {
        "ref_kind": "terminal_exit",
        "ref_id": "terminal-exit-1",
        "attempt_id": "attempt-1",
        "record_seq": 31,
    }
    cgroup_empty_ref = {
        "schema": reducer.CGROUP_EMPTY_SCHEMA,
        "ref_kind": "cgroup_empty",
        "ref_id": "cgroup-empty-1",
        "attempt_id": "attempt-1",
        "cgroup_id": "cgroup-1",
        "cgroup_inode": 5001,
        "epoch_id": "census-epoch-4",
        "freeze_readback_bytes": "1\n",
        "procs_before_digest": _sha(b"procs-before"),
        "procs_after_digest": _sha(b"procs-after"),
        "populated_readback_bytes": "populated 0\n",
        "task_inventory_digest": _sha(b"task-inventory"),
        "observed_empty": True,
        "record_seq": 32,
    }
    parents = [
        {"ref_kind": "terminal_exit", "ref_id": terminal_exit_ref["ref_id"]},
        {"ref_kind": "cgroup_empty", "ref_id": cgroup_empty_ref["ref_id"]},
        *({"ref_kind": "supervisor_operation", "ref_id": item} for item in final_write_refs),
    ]
    parents.sort(key=lambda item: (item["ref_kind"], item["ref_id"]))
    return {
        "schema": reducer.INPUT_SCHEMA,
        "attempt_id": "attempt-1",
        "close_context": {
            "schema": reducer.CLOSE_CONTEXT_SCHEMA,
            "attempt_id": "attempt-1",
            "terminal_exit_ref": terminal_exit_ref,
            "cgroup_empty_ref": cgroup_empty_ref,
            "object_ref": _object_ref(),
            "supervisor_task_generation": "task-generation-1",
            "open_token_ref": "open-token-1",
            "close_token_ref": "close-token-1",
            "final_write_token_refs": final_write_refs,
            "fd_number": 17,
            "fd_generation": 3,
            "operation_seq": 18,
            "close_entry_seq": 44,
            "close_exit_seq": 45,
            "close_ret": 0,
            "close_errno": 0,
            "causal_parent_refs": parents,
        },
        "observer_rows": [
            _observer_row(event_kind, seq, timestamp)
            for event_kind, seq, timestamp in zip(
                reducer.EXPECTED_OBSERVER_EVENTS,
                (10, 11, 12, 13),
                (100, 200, 300, 400),
                strict=True,
            )
        ],
        "name_group": {
            "schema": reducer.NAME_GROUP_SCHEMA,
            "attempt_id": "attempt-1",
            "group_id": "name-group-1",
            "first_group_seq": 7,
            "last_group_seq": 8,
            "drained_to_eagain": True,
            "loss_count": 0,
            "overflow_count": 0,
            "short_read_count": 0,
            "events": [
                _fanotify_event(7, reducer.FAN_MODIFY, "output-object-1", None),
                _fanotify_event(8, reducer.FAN_CLOSE_WRITE, "output-object-1", "close-token-1"),
            ],
        },
    }


def _assert_rejected(value: dict, message: str) -> None:
    with pytest.raises(reducer.FinalFputJoinError, match=message):
        reducer.build_diagnostic_receipt(value)


def test_complete_synthetic_chain_is_consistent_but_never_authorizing() -> None:
    result = reducer.build_diagnostic_receipt(_fixture())

    assert result["schema"] == reducer.RESULT_SCHEMA
    assert result["status"] == "diagnostic_declared_links_consistent_untrusted"
    assert result["observer_event_order"] == list(reducer.EXPECTED_OBSERVER_EVENTS)
    assert result["fanotify_name_group_seq_range"] == [7, 8]
    assert result["fanotify_close_write_group_seq"] == 8
    assert len(result["input_sha256"]) == 64
    assert result["final_close_claim"] is False
    assert result["trusted_observation"] is False
    assert result["kernel_source_pinned"] is False
    assert result["observer_runtime_authenticated"] is False
    assert result["fanotify_raw_bytes_reparsed"] is False
    assert result["cgroup_empty_reread"] is False
    assert result["close_syscall_to_fput_order_checked"] is False
    assert result["readiness_pass"] is False
    assert result["T1_numerical"] is False
    assert result["execution_authority"] is False
    assert result["qualification_credit"] == 0


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda x: x["observer_rows"].pop(), "exactly the four required"),
        (lambda x: x["observer_rows"].__setitem__(1, copy.deepcopy(x["observer_rows"][0])), "missing, duplicated, or out of lifecycle"),
        (lambda x: x["observer_rows"].reverse(), "missing, duplicated, or out of lifecycle"),
        (lambda x: x["observer_rows"][2].update(attempt_id="other-attempt"), "attempt does not match"),
        (lambda x: x["observer_rows"][1].update(file_cookie_digest=_sha(b"other-cookie")), "disagree on attempt/file/task identity"),
        (lambda x: x["observer_rows"][2].update(fd_generation=4), "disagree on attempt/file/task identity"),
        (lambda x: x["observer_rows"][3].update(object_ref="other-object"), "disagree on attempt/file/task identity"),
        (lambda x: x["observer_rows"][2].update(monotonic_ns=150), "timestamps are not strictly increasing"),
        (lambda x: (x["observer_rows"][1].update(hook_id=x["observer_rows"][0]["hook_id"], hook_seq=x["observer_rows"][0]["hook_seq"])), "hook sequence is duplicated or regressed"),
        (lambda x: x["observer_rows"][1].update(producer_lost=1), "non-zero producer_lost"),
        (lambda x: x["observer_rows"][1]["loss_epoch"]["epochs"][0].update(sequence_gap=1), "non-zero sequence_gap"),
        (lambda x: x["observer_rows"][1]["loss_epoch"]["epochs"][0].update(epoch_id="epoch-2"), "roster changed"),
        (lambda x: x["observer_rows"][0].update(unreviewed_field=True), "fields differ"),
        (lambda x: x["close_context"]["causal_parent_refs"].pop(), "causal parents are missing"),
        (lambda x: x["close_context"].update(close_ret=-1), "backing close must have exact"),
        (lambda x: x["close_context"]["cgroup_empty_ref"].update(observed_empty=False), "does not assert observed_empty"),
        (lambda x: x["close_context"]["cgroup_empty_ref"].update(attempt_id="other-attempt"), "attempt does not match"),
        (lambda x: x["close_context"].update(close_entry_seq=45), "entry/exit sequence is not increasing"),
        (lambda x: x["name_group"].update(drained_to_eagain=False), "not drained to EAGAIN"),
        (lambda x: x["name_group"].update(overflow_count=1), "non-zero overflow_count"),
        (lambda x: x["name_group"]["events"][1]["raw_row"]["raw_record"].update(sha256=_sha(b"wrong")), "digest does not match bytes"),
        (lambda x: x["name_group"]["events"][1]["raw_row"]["info_records"].__setitem__(2, copy.deepcopy(x["name_group"]["events"][1]["raw_row"]["info_records"][1])), "exactly one PIDFD, FID, and DFID_NAME"),
        (lambda x: x["name_group"]["events"][1]["raw_row"].update(group_kind="permission"), "must come from the name group"),
        (lambda x: x["name_group"]["events"][1]["pidfd_action"].update(metadata_pid=1002), "differs from raw fanotify metadata"),
        (lambda x: x["name_group"]["events"][1]["pidfd_action"].update(task_generation_ref="other-task"), "generation differs from terminal close actor"),
        (lambda x: x["name_group"]["events"][1]["pidfd_action"].update(close_ret=-1), "descriptor close did not succeed"),
        (lambda x: x["name_group"]["events"][1]["pidfd_action"].update(pidfd_info_index=1), "does not identify the PIDFD info record"),
        (lambda x: x["name_group"]["events"][1]["object_join"].update(group_seq=9), "does not reference its raw row"),
        (lambda x: x["name_group"]["events"][1]["object_join"]["object_ref"].update(generation="reused"), "exactly one FAN_CLOSE_WRITE"),
        (lambda x: x["name_group"]["events"][1].update(close_token_ref="wrong-token"), "does not match the terminal close token"),
        (lambda x: x["name_group"]["events"][0]["raw_row"].update(group_seq=8), "gap, duplicate, or reordered group_seq"),
        (lambda x: x["name_group"]["events"].append(copy.deepcopy(x["name_group"]["events"][1])), "complete sequence interval"),
        (lambda x: x["name_group"].update(short_read_count=1), "non-zero short_read_count"),
        (lambda x: x["name_group"]["events"][1]["raw_row"].update(attempt_id="other-attempt"), "attempt, or group does not match"),
        (lambda x: x["name_group"]["events"][1]["raw_row"]["metadata"].update(fd=9), "metadata.fd must be FAN_NOFD"),
    ],
)
def test_rejects_incomplete_ambiguous_or_lossy_join(mutation, message: str) -> None:
    value = _fixture()
    mutation(value)
    _assert_rejected(value, message)


def test_rejects_duplicate_target_close_write() -> None:
    value = _fixture()
    duplicate = copy.deepcopy(value["name_group"]["events"][1])
    duplicate["raw_row"]["group_seq"] = 9
    duplicate["object_join"]["group_seq"] = 9
    duplicate["pidfd_action"]["group_seq"] = 9
    duplicate["pidfd_action"]["held_pidfd_ref"] = "held-pidfd-9"
    duplicate["raw_row"]["actor_pidfd_ref"] = "held-pidfd-9"
    value["name_group"]["events"].append(duplicate)
    value["name_group"]["last_group_seq"] = 9
    _assert_rejected(value, "exactly one FAN_CLOSE_WRITE")


def test_does_not_use_fanotify_timestamps_to_order_against_observer_rows() -> None:
    value = _fixture()
    # The fanotify schema carries no timestamp used by this reducer. Its event
    # is associated only by group sequence, object identity, and close-token ref.
    value["name_group"]["events"][1]["raw_row"]["read_seq"] = 1
    result = reducer.reconcile_final_close(value)
    assert result["fanotify_close_write_group_seq"] == 8


def test_raw_fanotify_bytes_are_hash_checked_but_not_reparsed() -> None:
    value = _fixture()
    raw = b"synthetic but not a serialized fanotify metadata struct".ljust(64, b"\0")
    raw_record = value["name_group"]["events"][1]["raw_row"]["raw_record"]
    raw_record.update(
        bytes_b64=base64.b64encode(raw).decode("ascii"),
        byte_len=len(raw),
        sha256=_sha(raw),
    )
    metadata = value["name_group"]["events"][1]["raw_row"]["metadata"]
    metadata["event_len"] = len(raw)

    result = reducer.reconcile_final_close(value)
    assert result["status"] == "diagnostic_declared_links_consistent_untrusted"
    assert result["fanotify_raw_bytes_reparsed"] is False


def test_rejects_raw_event_over_diagnostic_size_bound() -> None:
    value = _fixture()
    raw = b"x" * (reducer.MAX_RAW_EVENT_BYTES + 1)
    raw_record = value["name_group"]["events"][1]["raw_row"]["raw_record"]
    raw_record.update(
        bytes_b64=base64.b64encode(raw).decode("ascii"),
        byte_len=len(raw),
        sha256=_sha(raw),
    )
    value["name_group"]["events"][1]["raw_row"]["metadata"]["event_len"] = len(raw)
    _assert_rejected(value, "exceeds the fixed")


def test_full_name_group_may_contain_other_output_objects() -> None:
    value = _fixture()
    other_object = "output-object-2"
    value["name_group"]["events"][0] = _fanotify_event(
        7, reducer.FAN_CLOSE_WRITE, other_object, "other-close-token",
    )
    result = reducer.reconcile_final_close(value)
    assert result["fanotify_close_write_group_seq"] == 8
