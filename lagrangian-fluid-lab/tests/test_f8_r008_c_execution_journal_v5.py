"""Synthetic-only tests for the non-authorizing V5 journal shape parser."""
import json

import pytest

from scripts.f8_r008_c_execution_journal_v5 import (
    JOURNAL_SCHEMA,
    JournalV5Error,
    inspect_untrusted_v5_journal,
)


NONCE = "a" * 32
MONO = "00000000000003e8"


def _process(birth_seq=0, *, pid=42):
    return {
        "pid_namespace_inode_hex": "0000000000000001",
        "pid": pid,
        "start_monotonic_ns_hex": "0000000000000002",
        "kernel_starttime_ticks_hex": "0000000000000003",
        "birth_seq_hex": f"{birth_seq:016x}",
    }


def _thread(birth_seq=0, *, tid=43):
    return {
        "tid": tid,
        "start_monotonic_ns_hex": "0000000000000002",
        "kernel_starttime_ticks_hex": "0000000000000003",
        "birth_seq_hex": f"{birth_seq:016x}",
    }


def _event(kind, seq, **fields):
    return {
        "seq": seq,
        "mono_ns_hex": MONO,
        "kind": kind,
        "attempt_nonce_hex": NONCE,
        **fields,
    }


def _main_events(*, poll_outcome="returned", include_poll_end=True):
    proc = _process()
    events = [
        _event("spawn", 0, process_generation_id=proc, supervisor_identity_binding={"synthetic": True}),
        _event(
            "exec", 1, process_generation_id=proc, executable_binding={"synthetic": True},
            argv_sha256="2" * 64, cwd_object_id="cwd-v1", environment_sha256="3" * 64,
        ),
        _event(
            "loop_guard", 2, process_generation_id=proc, driver_id="main",
            loop_iteration_id=0, time_step_ieee754_hex="0000000000000000",
            time_max_ieee754_hex="3ff0000000000000", condition_result=True,
        ),
        _event(
            "poll_begin", 3, poll_begin_id=3, process_generation_id=proc,
            solver_instance_id="main", driver_id="main", guard_seq=2,
            callsite_id="cpu.pre_interaction_forces.run_cpu", integrator="Verlet",
            interstep="INTERSTEP_Verlet", input_entry_index=0,
            timestep_ieee754_hex="0000000000000000", active=False,
            cache_action="miss", cache_source_seq=None, table_raw_binding=None,
        ),
    ]
    if include_poll_end:
        events.append(_event(
            "poll_end", 4, poll_begin_id=3, process_generation_id=proc,
            outcome=poll_outcome,
        ))
        events.extend([
            _event("exit", 5, process_generation_id=proc, exit_code=0, signal=None),
            _event("reap", 6, process_generation_id=proc),
        ])
    return events


def _journal(events, **updates):
    value = {
        "schema": JOURNAL_SCHEMA,
        "attempt_nonce_hex": NONCE,
        "source_id": "runtime-image-v5",
        "source_binary_sha256": "b" * 64,
        "coverage_start_ns_hex": MONO,
        "coverage_end_ns_hex": MONO,
        "event_count": len(events),
        "overflow": False,
        "lost_count": 0,
        "events": events,
    }
    value.update(updates)
    return json.dumps(value, separators=(",", ":")).encode()


def test_valid_synthetic_journal_remains_open_and_non_authorizing():
    result = inspect_untrusted_v5_journal(_journal(_main_events()))
    assert result["status"] == "untrusted_v5_journal_shape_consistent"
    assert result["event_count"] == 7
    assert result["all_polls_terminal"] is True
    assert result["observed_process_lifecycle_complete"] is True
    assert result["process_generation_count"] == 1
    assert result["all_polls_returned"] is True
    assert result["gate_state"] == "open"
    assert result["event_source_completeness_verified"] is False
    assert result["process_lifecycle_verified"] is False
    assert result["query_causality_verified"] is False
    assert result["cache_replay_verified"] is False
    assert result["execution_semantics_verified"] is False
    assert result["qualification_adjudicated"] is False
    assert result["T1_numerical"] is False
    assert result["qualification_credit"] == 0


def test_missing_poll_end_is_retained_as_incomplete_not_passed():
    result = inspect_untrusted_v5_journal(_journal(_main_events(include_poll_end=False)))
    assert result["poll_begin_count"] == 1
    assert result["poll_end_count"] == 0
    assert result["unterminated_poll_count"] == 1
    assert result["all_polls_terminal"] is False
    assert result["gate_state"] == "open"


def test_exception_poll_end_is_terminal_but_never_execution_success():
    result = inspect_untrusted_v5_journal(_journal(_main_events(poll_outcome="exception")))
    assert result["all_polls_terminal"] is True
    assert result["poll_exception_count"] == 1
    assert result["all_polls_returned"] is False
    assert result["execution_semantics_verified"] is False


def test_exact_process_event_union_branches_are_structurally_accepted():
    parent = _process(0)
    events = [
        _event("spawn", 0, process_generation_id=parent, supervisor_identity_binding={"synthetic": True}),
        _event("exec", 1, process_generation_id=parent, executable_binding={"synthetic": True}, argv_sha256="2" * 64, cwd_object_id="cwd-v1", environment_sha256="3" * 64),
        _event("fork", 2, parent_generation_id=parent, process_generation_id=_process(2, pid=44)),
        _event("clone_process", 3, parent_generation_id=parent, process_generation_id=_process(3, pid=45), clone_flags_hex="0000000000000000"),
        _event("thread_create", 4, process_generation_id=parent, thread_generation_id=_thread(4), clone_flags_hex="0000000000000000"),
        _event("thread_exit", 5, process_generation_id=parent, thread_generation_id=_thread(4)),
        _event("load", 6, process_generation_id=parent, object_binding={"synthetic": True}, object_kind="library"),
        _event("cgroup", 7, process_generation_id=parent, action="attach", cgroup_id="cg-v1"),
        _event("exit", 8, process_generation_id=_process(2, pid=44), exit_code=0, signal=None),
        _event("reap", 9, process_generation_id=_process(2, pid=44)),
        _event("exit", 10, process_generation_id=_process(3, pid=45), exit_code=0, signal=None),
        _event("reap", 11, process_generation_id=_process(3, pid=45)),
        _event("exit", 12, process_generation_id=parent, exit_code=0, signal=None),
        _event("reap", 13, process_generation_id=parent),
    ]
    result = inspect_untrusted_v5_journal(_journal(events))
    assert result["event_count"] == 14
    assert result["process_generation_count"] == 3
    assert result["thread_generation_count"] == 1
    assert result["observed_process_lifecycle_complete"] is True
    assert result["gate_state"] == "open"


def test_unknown_event_fields_and_unmatched_poll_end_are_rejected():
    events = _main_events()
    events[0]["surprise"] = True
    with pytest.raises(JournalV5Error, match="exact schema"):
        inspect_untrusted_v5_journal(_journal(events))

    proc = _process()
    events = [
        _event("spawn", 0, process_generation_id=proc, supervisor_identity_binding={"synthetic": True}),
        _event("poll_end", 1, poll_begin_id=0, process_generation_id=proc, outcome="returned"),
    ]
    with pytest.raises(JournalV5Error, match="must match one earlier"):
        inspect_untrusted_v5_journal(_journal(events))


@pytest.mark.parametrize("updates", [
    {"event_count": True},
    {"lost_count": True},
    {"overflow": 0},
    {"overflow": True},
    {"lost_count": 1},
])
def test_loss_overflow_and_bool_as_integer_are_rejected(updates):
    with pytest.raises(JournalV5Error):
        inspect_untrusted_v5_journal(_journal([], **updates))


def test_duplicate_keys_invalid_time_order_and_nonce_copy_are_rejected():
    with pytest.raises(JournalV5Error, match="duplicate JSON key"):
        inspect_untrusted_v5_journal(b'{"schema":"a","schema":"b"}')

    events = _main_events()
    events[2]["mono_ns_hex"] = "00000000000003e7"
    with pytest.raises(JournalV5Error, match="nondecreasing"):
        inspect_untrusted_v5_journal(_journal(
            events, coverage_start_ns_hex="00000000000003e7"
        ))

    events = _main_events()
    events[0]["attempt_nonce_hex"] = "c" * 32
    with pytest.raises(JournalV5Error, match="nonce differs"):
        inspect_untrusted_v5_journal(_journal(events))


@pytest.mark.parametrize("bad_value", [[], {}])
def test_malformed_poll_enum_values_raise_contract_error_not_typeerror(bad_value):
    events = _main_events()
    events[3]["callsite_id"] = bad_value
    with pytest.raises(JournalV5Error, match="callsite_id"):
        inspect_untrusted_v5_journal(_journal(events))


@pytest.mark.parametrize("field", ["integrator", "interstep", "cache_action"])
def test_all_poll_string_enums_reject_unhashable_json_values(field):
    events = _main_events()
    events[3][field] = []
    with pytest.raises(JournalV5Error):
        inspect_untrusted_v5_journal(_journal(events))


def test_coverage_and_exact_integer_index_rules_are_enforced():
    with pytest.raises(JournalV5Error, match="coverage start"):
        inspect_untrusted_v5_journal(_journal([], coverage_start_ns_hex="00000000000003e9"))

    events = _main_events()
    events[3]["input_entry_index"] = True
    with pytest.raises(JournalV5Error, match="builtin integer"):
        inspect_untrusted_v5_journal(_journal(events))


@pytest.mark.parametrize("bad_exit_code", [-1, 256, True])
def test_exit_code_must_be_exact_builtin_8_bit_value(bad_exit_code):
    events = _main_events()
    events[5]["exit_code"] = bad_exit_code
    with pytest.raises(JournalV5Error, match="exit code"):
        inspect_untrusted_v5_journal(_journal(events))


def test_process_query_before_root_exec_is_rejected():
    proc = _process()
    events = [
        _event("spawn", 0, process_generation_id=proc, supervisor_identity_binding={"synthetic": True}),
        _event(
            "loop_guard", 1, process_generation_id=proc, driver_id="main",
            loop_iteration_id=0, time_step_ieee754_hex="0000000000000000",
            time_max_ieee754_hex="3ff0000000000000", condition_result=True,
        ),
    ]
    with pytest.raises(JournalV5Error, match="requires a running process"):
        inspect_untrusted_v5_journal(_journal(events))


def test_fork_from_created_root_and_multiple_root_spawn_are_rejected():
    root = _process()
    events = [
        _event("spawn", 0, process_generation_id=root, supervisor_identity_binding={"synthetic": True}),
        _event("fork", 1, parent_generation_id=root, process_generation_id=_process(1, pid=44)),
    ]
    with pytest.raises(JournalV5Error, match="parent must be a running"):
        inspect_untrusted_v5_journal(_journal(events))

    events = [
        _event("spawn", 0, process_generation_id=root, supervisor_identity_binding={"synthetic": True}),
        _event("spawn", 1, process_generation_id=_process(1, pid=44), supervisor_identity_binding={"synthetic": True}),
    ]
    with pytest.raises(JournalV5Error, match="multiple solver root"):
        inspect_untrusted_v5_journal(_journal(events))


def test_pid_reuse_before_reap_is_rejected_but_lifecycle_truncation_is_open():
    root = _process()
    child = _process(2, pid=44)
    reused_child = _process(3, pid=44)
    events = [
        _event("spawn", 0, process_generation_id=root, supervisor_identity_binding={"synthetic": True}),
        _event("exec", 1, process_generation_id=root, executable_binding={}, argv_sha256="2" * 64, cwd_object_id="cwd-v1", environment_sha256="3" * 64),
        _event("fork", 2, parent_generation_id=root, process_generation_id=child),
        _event("clone_process", 3, parent_generation_id=root, process_generation_id=reused_child, clone_flags_hex="0000000000000000"),
    ]
    with pytest.raises(JournalV5Error, match="PID reuse"):
        inspect_untrusted_v5_journal(_journal(events))

    result = inspect_untrusted_v5_journal(_journal(_main_events()[:-1]))
    assert result["observed_process_lifecycle_complete"] is False
    assert result["gate_state"] == "open"


def test_pid_reuse_after_reap_is_accepted_as_a_new_generation():
    root = _process()
    first_child = _process(2, pid=44)
    second_child = _process(5, pid=44)
    events = [
        _event("spawn", 0, process_generation_id=root, supervisor_identity_binding={"synthetic": True}),
        _event("exec", 1, process_generation_id=root, executable_binding={}, argv_sha256="2" * 64, cwd_object_id="cwd-v1", environment_sha256="3" * 64),
        _event("fork", 2, parent_generation_id=root, process_generation_id=first_child),
        _event("exit", 3, process_generation_id=first_child, exit_code=0, signal=None),
        _event("reap", 4, process_generation_id=first_child),
        _event("clone_process", 5, parent_generation_id=root, process_generation_id=second_child, clone_flags_hex="0000000000000000"),
        _event("exit", 6, process_generation_id=second_child, exit_code=0, signal=None),
        _event("reap", 7, process_generation_id=second_child),
        _event("exit", 8, process_generation_id=root, exit_code=0, signal=None),
        _event("reap", 9, process_generation_id=root),
    ]
    result = inspect_untrusted_v5_journal(_journal(events))
    assert result["process_generation_count"] == 3
    assert result["observed_process_lifecycle_complete"] is True


def test_process_exit_before_owned_thread_exit_is_rejected():
    proc = _process()
    events = [
        _event("spawn", 0, process_generation_id=proc, supervisor_identity_binding={"synthetic": True}),
        _event("exec", 1, process_generation_id=proc, executable_binding={}, argv_sha256="2" * 64, cwd_object_id="cwd-v1", environment_sha256="3" * 64),
        _event("thread_create", 2, process_generation_id=proc, thread_generation_id=_thread(2), clone_flags_hex="0000000000000000"),
        _event("exit", 3, process_generation_id=proc, exit_code=0, signal=None),
    ]
    with pytest.raises(JournalV5Error, match="before its threads terminated"):
        inspect_untrusted_v5_journal(_journal(events))


def test_tid_reuse_across_processes_waits_for_prior_thread_exit():
    root = _process()
    child = _process(2, pid=44)
    events = [
        _event("spawn", 0, process_generation_id=root, supervisor_identity_binding={"synthetic": True}),
        _event("exec", 1, process_generation_id=root, executable_binding={}, argv_sha256="2" * 64, cwd_object_id="cwd-v1", environment_sha256="3" * 64),
        _event("fork", 2, parent_generation_id=root, process_generation_id=child),
        _event("thread_create", 3, process_generation_id=root, thread_generation_id=_thread(3, tid=43), clone_flags_hex="0000000000000000"),
        _event("thread_create", 4, process_generation_id=child, thread_generation_id=_thread(4, tid=43), clone_flags_hex="0000000000000000"),
    ]
    with pytest.raises(JournalV5Error, match="TID reuse"):
        inspect_untrusted_v5_journal(_journal(events))


def test_attempt_nonce_uses_the_frozen_exact_128_bit_hex_shape():
    bad = _journal([]).replace(NONCE.encode(), b"a" * 30)
    with pytest.raises(JournalV5Error, match="lowercase-hex"):
        inspect_untrusted_v5_journal(bad)
