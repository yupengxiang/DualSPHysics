"""Synthetic-only tests for the non-authorizing V5 journal shape parser."""
import json
import math
import struct

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


def _journal_with_polls(specs):
    proc = _process()
    events = [
        _event("spawn", 0, process_generation_id=proc, supervisor_identity_binding={"synthetic": True}),
        _event(
            "exec", 1, process_generation_id=proc, executable_binding={"synthetic": True},
            argv_sha256="2" * 64, cwd_object_id="cwd-v1", environment_sha256="3" * 64,
        ),
    ]
    caches = {}
    observed_timesteps = []
    for iteration, spec in enumerate(specs):
        timestep_hex = spec.get("timestep", "0000000000000000")
        timestep = struct.unpack(">d", bytes.fromhex(timestep_hex))[0]
        time_max = math.nextafter(timestep, math.inf)
        if not math.isfinite(time_max):
            raise ValueError("synthetic true guard requires a finite next binary64 timestep")
        observed_timesteps.append(timestep)
        solver_instance_id = spec.get("solver_instance_id", "main")
        input_entry_index = spec.get("input_entry_index", 0)
        slot = caches.setdefault((solver_instance_id, input_entry_index), {
            "last_timestep": -1.0,
            "source_seq": None,
        })
        guard_seq = len(events)
        events.append(_event(
            "loop_guard", guard_seq, process_generation_id=proc, driver_id="main",
            loop_iteration_id=iteration, time_step_ieee754_hex=timestep_hex,
            time_max_ieee754_hex=struct.pack(">d", time_max).hex(), condition_result=True,
        ))
        begin_seq = len(events)
        is_hit = slot["last_timestep"] >= 0 and timestep == slot["last_timestep"]
        action = "hit" if is_hit else "miss"
        ref = slot["source_seq"] if is_hit else None
        action = spec.get("cache_action", action)
        ref = spec.get("cache_source_seq", ref)
        active = spec.get("active", False)
        events.append(_event(
            "poll_begin", begin_seq, poll_begin_id=begin_seq, process_generation_id=proc,
            solver_instance_id=solver_instance_id, driver_id="main", guard_seq=guard_seq,
            callsite_id="cpu.pre_interaction_forces.run_cpu", integrator="Verlet",
            interstep="INTERSTEP_Verlet", input_entry_index=input_entry_index,
            timestep_ieee754_hex=timestep_hex, active=active,
            cache_action=action, cache_source_seq=ref,
            table_raw_binding=spec.get(
                "table_raw_binding", {"synthetic": True} if active else None
            ),
        ))
        if not is_hit:
            slot["last_timestep"] = timestep
            slot["source_seq"] = begin_seq
        if spec.get("outcome", "returned") is not None:
            events.append(_event(
                "poll_end", len(events), poll_begin_id=begin_seq,
                process_generation_id=proc, outcome=spec.get("outcome", "returned"),
            ))

    all_polls_terminal = all(spec.get("outcome", "returned") is not None for spec in specs)
    if all_polls_terminal:
        terminal_step = math.nextafter(max(observed_timesteps, default=1.0), math.inf)
        if not math.isfinite(terminal_step):
            raise ValueError("synthetic terminal guard requires a finite next binary64 timestep")
        terminal_hex = struct.pack(">d", terminal_step).hex()
        terminal_seq = len(events)
        events.append(_event(
            "loop_guard", terminal_seq, process_generation_id=proc, driver_id="main",
            loop_iteration_id=len(specs), time_step_ieee754_hex=terminal_hex,
            time_max_ieee754_hex=terminal_hex, condition_result=False,
        ))
        events.extend([
            _event("exit", len(events), process_generation_id=proc, exit_code=0, signal=None),
            _event("reap", len(events) + 1, process_generation_id=proc),
        ])
    return _journal(events)


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
    assert result["query_guard_link_count"] == 1
    assert result["query_guard_links_observed_consistent"] is True
    assert result["cache_transitions_observed_consistent"] is True
    assert result["cache_replay_diagnostic_state"] == "journal_local_consistent_unverified"
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
    events = _main_events(poll_outcome="exception")
    events[3]["active"] = True
    events[3]["table_raw_binding"] = {"synthetic": True}
    result = inspect_untrusted_v5_journal(_journal(events))
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


def test_poll_must_match_true_guard_generation_driver_iteration_and_exact_time():
    raw = _journal_with_polls([{"timestep": "3ff0000000000000"}])
    journal = json.loads(raw)
    poll = next(event for event in journal["events"] if event["kind"] == "poll_begin")
    guard = next(event for event in journal["events"] if event["kind"] == "loop_guard")
    guard["condition_result"] = False
    with pytest.raises(JournalV5Error, match="condition_result differs"):
        inspect_untrusted_v5_journal(json.dumps(journal).encode())

    journal = json.loads(raw)
    poll = next(event for event in journal["events"] if event["kind"] == "poll_begin")
    poll["timestep_ieee754_hex"] = "0000000000000000"
    with pytest.raises(JournalV5Error, match="same-generation driver/iteration guard"):
        inspect_untrusted_v5_journal(json.dumps(journal).encode())


def test_observed_driver_loop_requires_one_terminal_false_guard():
    proc = _process()
    events = [
        _event("spawn", 0, process_generation_id=proc, supervisor_identity_binding={}),
        _event("exec", 1, process_generation_id=proc, executable_binding={}, argv_sha256="2" * 64, cwd_object_id="cwd-v1", environment_sha256="3" * 64),
        _event("loop_guard", 2, process_generation_id=proc, driver_id="main", loop_iteration_id=0, time_step_ieee754_hex="0000000000000000", time_max_ieee754_hex="3ff0000000000000", condition_result=True),
        _event("loop_guard", 3, process_generation_id=proc, driver_id="main", loop_iteration_id=1, time_step_ieee754_hex="3ff0000000000000", time_max_ieee754_hex="3ff0000000000000", condition_result=False),
        _event("exit", 4, process_generation_id=proc, exit_code=0, signal=None),
        _event("reap", 5, process_generation_id=proc),
    ]
    result = inspect_untrusted_v5_journal(_journal(events))
    assert result["observed_driver_loop_count"] == 1
    assert result["observed_driver_loop_termination_guard_count"] == 1
    assert result["observed_driver_loops_complete"] is True
    assert result["driver_loop_termination_verified"] is False

    incomplete = inspect_untrusted_v5_journal(_journal(_main_events()))
    assert incomplete["observed_driver_loops_complete"] is False


def test_driver_guard_after_false_termination_is_rejected():
    proc = _process()
    events = [
        _event("spawn", 0, process_generation_id=proc, supervisor_identity_binding={}),
        _event("exec", 1, process_generation_id=proc, executable_binding={}, argv_sha256="2" * 64, cwd_object_id="cwd-v1", environment_sha256="3" * 64),
        _event("loop_guard", 2, process_generation_id=proc, driver_id="main", loop_iteration_id=0, time_step_ieee754_hex="3ff0000000000000", time_max_ieee754_hex="3ff0000000000000", condition_result=False),
        _event("loop_guard", 3, process_generation_id=proc, driver_id="main", loop_iteration_id=1, time_step_ieee754_hex="0000000000000000", time_max_ieee754_hex="3ff0000000000000", condition_result=True),
        _event("exit", 4, process_generation_id=proc, exit_code=0, signal=None),
        _event("reap", 5, process_generation_id=proc),
    ]
    with pytest.raises(JournalV5Error, match="after its terminal false guard"):
        inspect_untrusted_v5_journal(_journal(events))


def test_poll_cannot_reuse_a_guard_after_terminal_false_or_newer_iteration():
    proc = _process()
    base = [
        _event("spawn", 0, process_generation_id=proc, supervisor_identity_binding={}),
        _event("exec", 1, process_generation_id=proc, executable_binding={}, argv_sha256="2" * 64, cwd_object_id="cwd-v1", environment_sha256="3" * 64),
        _event("loop_guard", 2, process_generation_id=proc, driver_id="main", loop_iteration_id=0, time_step_ieee754_hex="0000000000000000", time_max_ieee754_hex="3ff0000000000000", condition_result=True),
    ]
    old_guard_poll = _event(
        "poll_begin", 4, poll_begin_id=4, process_generation_id=proc,
        solver_instance_id="main", driver_id="main", guard_seq=2,
        callsite_id="cpu.pre_interaction_forces.run_cpu", integrator="Verlet",
        interstep="INTERSTEP_Verlet", input_entry_index=0,
        timestep_ieee754_hex="0000000000000000", active=False,
        cache_action="miss", cache_source_seq=None, table_raw_binding=None,
    )
    terminal_then_poll = base + [
        _event("loop_guard", 3, process_generation_id=proc, driver_id="main", loop_iteration_id=1, time_step_ieee754_hex="3ff0000000000000", time_max_ieee754_hex="3ff0000000000000", condition_result=False),
        old_guard_poll,
        _event("poll_end", 5, poll_begin_id=4, process_generation_id=proc, outcome="returned"),
        _event("exit", 6, process_generation_id=proc, exit_code=0, signal=None),
        _event("reap", 7, process_generation_id=proc),
    ]
    with pytest.raises(JournalV5Error, match="outside an active observed driver loop"):
        inspect_untrusted_v5_journal(_journal(terminal_then_poll))

    next_iteration_then_stale_poll = base + [
        _event("loop_guard", 3, process_generation_id=proc, driver_id="main", loop_iteration_id=1, time_step_ieee754_hex="0000000000000000", time_max_ieee754_hex="3ff0000000000000", condition_result=True),
        old_guard_poll,
        _event("poll_end", 5, poll_begin_id=4, process_generation_id=proc, outcome="returned"),
        _event("exit", 6, process_generation_id=proc, exit_code=0, signal=None),
        _event("reap", 7, process_generation_id=proc),
    ]
    with pytest.raises(JournalV5Error, match="stale driver loop guard"):
        inspect_untrusted_v5_journal(_journal(next_iteration_then_stale_poll))


def test_one_vres_driver_guard_can_serve_ordered_multiple_instances():
    proc = _process()
    events = [
        _event("spawn", 0, process_generation_id=proc, supervisor_identity_binding={}),
        _event("exec", 1, process_generation_id=proc, executable_binding={}, argv_sha256="2" * 64, cwd_object_id="cwd-v1", environment_sha256="3" * 64),
        _event("loop_guard", 2, process_generation_id=proc, driver_id="vres", loop_iteration_id=0, time_step_ieee754_hex="0000000000000000", time_max_ieee754_hex="3ff0000000000000", condition_result=True),
    ]
    for instance, interstep, action, source in [
        ("vres.00", "INTERSTEP_SymPredictor", "miss", None),
        ("vres.00", "INTERSTEP_SymCorrector", "hit", 3),
        ("vres.01", "INTERSTEP_SymPredictor", "miss", None),
        ("vres.01", "INTERSTEP_SymCorrector", "hit", 7),
    ]:
        seq = len(events)
        events.append(_event(
            "poll_begin", seq, poll_begin_id=seq, process_generation_id=proc,
            solver_instance_id=instance, driver_id="vres", guard_seq=2,
            callsite_id="cpu.pre_interaction_forces.run_cpu", integrator="VRes",
            interstep=interstep, input_entry_index=0,
            timestep_ieee754_hex="0000000000000000", active=False,
            cache_action=action, cache_source_seq=source, table_raw_binding=None,
        ))
        events.append(_event(
            "poll_end", len(events), poll_begin_id=seq,
            process_generation_id=proc, outcome="returned",
        ))
    events.extend([
        _event("loop_guard", len(events), process_generation_id=proc, driver_id="vres", loop_iteration_id=1, time_step_ieee754_hex="3ff0000000000000", time_max_ieee754_hex="3ff0000000000000", condition_result=False),
        _event("exit", len(events) + 1, process_generation_id=proc, exit_code=0, signal=None),
        _event("reap", len(events) + 2, process_generation_id=proc),
    ])
    result = inspect_untrusted_v5_journal(_journal(events))
    assert result["query_guard_link_count"] == 4
    assert result["observed_driver_loops_complete"] is True


def test_driver_guard_cannot_overtake_a_poll_end():
    proc = _process()
    events = [
        _event("spawn", 0, process_generation_id=proc, supervisor_identity_binding={}),
        _event("exec", 1, process_generation_id=proc, executable_binding={}, argv_sha256="2" * 64, cwd_object_id="cwd-v1", environment_sha256="3" * 64),
        _event("loop_guard", 2, process_generation_id=proc, driver_id="main", loop_iteration_id=0, time_step_ieee754_hex="0000000000000000", time_max_ieee754_hex="3ff0000000000000", condition_result=True),
        _event("poll_begin", 3, poll_begin_id=3, process_generation_id=proc, solver_instance_id="main", driver_id="main", guard_seq=2, callsite_id="cpu.pre_interaction_forces.run_cpu", integrator="Verlet", interstep="INTERSTEP_Verlet", input_entry_index=0, timestep_ieee754_hex="0000000000000000", active=False, cache_action="miss", cache_source_seq=None, table_raw_binding=None),
        _event("loop_guard", 4, process_generation_id=proc, driver_id="main", loop_iteration_id=1, time_step_ieee754_hex="3ff0000000000000", time_max_ieee754_hex="3ff0000000000000", condition_result=False),
        _event("poll_end", 5, poll_begin_id=3, process_generation_id=proc, outcome="returned"),
        _event("exit", 6, process_generation_id=proc, exit_code=0, signal=None),
        _event("reap", 7, process_generation_id=proc),
    ]
    with pytest.raises(JournalV5Error, match="driver loop event occurs before a prior poll_end"):
        inspect_untrusted_v5_journal(_journal(events))


def test_missing_poll_end_before_next_guard_marks_loop_incomplete():
    proc = _process()
    events = [
        _event("spawn", 0, process_generation_id=proc, supervisor_identity_binding={}),
        _event("exec", 1, process_generation_id=proc, executable_binding={}, argv_sha256="2" * 64, cwd_object_id="cwd-v1", environment_sha256="3" * 64),
        _event("loop_guard", 2, process_generation_id=proc, driver_id="main", loop_iteration_id=0, time_step_ieee754_hex="0000000000000000", time_max_ieee754_hex="3ff0000000000000", condition_result=True),
        _event("poll_begin", 3, poll_begin_id=3, process_generation_id=proc, solver_instance_id="main", driver_id="main", guard_seq=2, callsite_id="cpu.pre_interaction_forces.run_cpu", integrator="Verlet", interstep="INTERSTEP_Verlet", input_entry_index=0, timestep_ieee754_hex="0000000000000000", active=False, cache_action="miss", cache_source_seq=None, table_raw_binding=None),
        _event("loop_guard", 4, process_generation_id=proc, driver_id="main", loop_iteration_id=1, time_step_ieee754_hex="3ff0000000000000", time_max_ieee754_hex="3ff0000000000000", condition_result=False),
        _event("exit", 5, process_generation_id=proc, exit_code=0, signal=None),
        _event("reap", 6, process_generation_id=proc),
    ]
    result = inspect_untrusted_v5_journal(_journal(events))
    assert result["all_polls_terminal"] is False
    assert result["driver_unclosed_poll_count"] == 1
    assert result["observed_driver_loops_complete"] is False
    assert result["cache_replay_diagnostic_state"] == "unresolved_call_order"


def test_cache_single_slot_replay_uses_numeric_binary64_equality_and_current_source():
    raw = _journal_with_polls([
        {"timestep": "0000000000000000"},
        {"timestep": "8000000000000000"},  # -0.0 compares equal to +0.0 in C++.
    ])
    result = inspect_untrusted_v5_journal(raw)
    begins = [event for event in json.loads(raw)["events"] if event["kind"] == "poll_begin"]
    assert begins[0]["cache_action"] == "miss"
    assert begins[1]["cache_action"] == "hit"
    assert begins[1]["cache_source_seq"] == begins[0]["seq"]
    assert result["cache_unknown_source_count"] == 0
    assert result["cache_hit_with_unknown_source_count"] == 0


def test_negative_timestep_repeats_are_misses_under_source_guard():
    raw = _journal_with_polls([
        {"timestep": "c000000000000000"},
        {"timestep": "c000000000000000"},
    ])
    result = inspect_untrusted_v5_journal(raw)
    begins = [event for event in json.loads(raw)["events"] if event["kind"] == "poll_begin"]
    assert [event["cache_action"] for event in begins] == ["miss", "miss"]
    assert [event["cache_source_seq"] for event in begins] == [None, None]
    assert result["cache_replay_diagnostic_state"] == "journal_local_consistent_unverified"


def test_cache_slots_are_isolated_by_solver_instance_and_input_entry():
    raw = _journal_with_polls([
        {"input_entry_index": 0},
        {"input_entry_index": 1},
        {"input_entry_index": 0},
        {"solver_instance_id": "other", "input_entry_index": 0},
    ])
    inspect_untrusted_v5_journal(raw)
    begins = [event for event in json.loads(raw)["events"] if event["kind"] == "poll_begin"]
    assert [event["cache_action"] for event in begins] == ["miss", "miss", "hit", "miss"]
    assert [event["cache_source_seq"] for event in begins] == [None, None, begins[0]["seq"], None]


def test_cache_slot_does_not_cross_process_generation():
    root = _process()
    child = _process(5, pid=43)
    events = [
        _event("spawn", 0, process_generation_id=root, supervisor_identity_binding={"synthetic": True}),
        _event("exec", 1, process_generation_id=root, executable_binding={}, argv_sha256="2" * 64, cwd_object_id="cwd-v1", environment_sha256="3" * 64),
        _event("loop_guard", 2, process_generation_id=root, driver_id="main", loop_iteration_id=0, time_step_ieee754_hex="0000000000000000", time_max_ieee754_hex="3ff0000000000000", condition_result=True),
        _event("poll_begin", 3, poll_begin_id=3, process_generation_id=root, solver_instance_id="main", driver_id="main", guard_seq=2, callsite_id="cpu.pre_interaction_forces.run_cpu", integrator="Verlet", interstep="INTERSTEP_Verlet", input_entry_index=0, timestep_ieee754_hex="0000000000000000", active=False, cache_action="miss", cache_source_seq=None, table_raw_binding=None),
        _event("poll_end", 4, poll_begin_id=3, process_generation_id=root, outcome="returned"),
        _event("fork", 5, parent_generation_id=root, process_generation_id=child),
        _event("loop_guard", 6, process_generation_id=child, driver_id="main", loop_iteration_id=0, time_step_ieee754_hex="0000000000000000", time_max_ieee754_hex="3ff0000000000000", condition_result=True),
        _event("poll_begin", 7, poll_begin_id=7, process_generation_id=child, solver_instance_id="main", driver_id="main", guard_seq=6, callsite_id="cpu.pre_interaction_forces.run_cpu", integrator="Verlet", interstep="INTERSTEP_Verlet", input_entry_index=0, timestep_ieee754_hex="0000000000000000", active=False, cache_action="miss", cache_source_seq=None, table_raw_binding=None),
        _event("poll_end", 8, poll_begin_id=7, process_generation_id=child, outcome="returned"),
        _event("exit", 9, process_generation_id=child, exit_code=0, signal=None),
        _event("reap", 10, process_generation_id=child),
        _event("exit", 11, process_generation_id=root, exit_code=0, signal=None),
        _event("reap", 12, process_generation_id=root),
    ]
    result = inspect_untrusted_v5_journal(_journal(events))
    assert result["poll_begin_count"] == 2
    assert result["cache_fork_unresolved_poll_count"] == 1
    assert result["cache_transitions_observed_consistent"] is False
    assert result["cache_replay_diagnostic_state"] == "unresolved_fork_cache_state"


def test_intervening_miss_invalidates_older_same_time_cache_source():
    raw = _journal_with_polls([
        {"timestep": "0000000000000000"},
        {"timestep": "3ff0000000000000"},
        {"timestep": "0000000000000000"},
    ])
    journal = json.loads(raw)
    begins = [event for event in journal["events"] if event["kind"] == "poll_begin"]
    begins[2]["cache_action"] = "hit"
    begins[2]["cache_source_seq"] = begins[0]["seq"]
    with pytest.raises(JournalV5Error, match="cache_action differs"):
        inspect_untrusted_v5_journal(json.dumps(journal).encode())


@pytest.mark.parametrize("first_outcome", ["exception", None])
def test_unknown_miss_output_poisoning_is_not_backfilled_by_same_time_hit(first_outcome):
    result = inspect_untrusted_v5_journal(_journal_with_polls([
        {"active": True, "outcome": first_outcome},
        {"timestep": "0000000000000000"},
    ]))
    assert result["cache_unknown_source_count"] == 1
    assert result["cache_hit_with_unknown_source_count"] == 1
    assert result["cache_replay_diagnostic_state"] == (
        "unresolved_call_order" if first_outcome is None else "unresolved_output_state"
    )
    assert result["cache_unclosed_prior_poll_count"] == (1 if first_outcome is None else 0)
    assert result["cache_replay_verified"] is False


def test_unterminated_cache_hit_keeps_later_same_time_hit_unverified():
    result = inspect_untrusted_v5_journal(_journal_with_polls([
        {}, {"outcome": None}, {},
    ]))
    assert result["unterminated_poll_count"] == 1
    assert result["cache_unterminated_hit_count"] == 1
    assert result["cache_hit_with_unknown_source_count"] == 0
    assert result["cache_unclosed_prior_poll_count"] == 1
    assert result["cache_replay_diagnostic_state"] == "unresolved_call_order"
    assert result["all_polls_terminal"] is False


def test_terminal_unterminated_hit_gets_incomplete_cache_diagnostic():
    result = inspect_untrusted_v5_journal(_journal_with_polls([
        {}, {"outcome": None},
    ]))
    assert result["all_polls_terminal"] is False
    assert result["gate_state"] == "open"
    assert result["cache_unterminated_hit_count"] == 1
    assert result["cache_replay_diagnostic_state"] == "incomplete_poll_state"


def test_exception_on_inactive_or_cache_hit_branch_is_rejected():
    with pytest.raises(JournalV5Error, match="inactive source branch"):
        inspect_untrusted_v5_journal(_journal_with_polls([
            {"outcome": "exception"},
        ]))
    with pytest.raises(JournalV5Error, match="cache-hit branch"):
        inspect_untrusted_v5_journal(_journal_with_polls([
            {}, {"outcome": "exception"},
        ]))


def test_cache_hit_must_reference_the_current_miss_event():
    raw = _journal_with_polls([
        {"timestep": "0000000000000000"},
        {"timestep": "0000000000000000"},
    ])
    journal = json.loads(raw)
    begins = [event for event in journal["events"] if event["kind"] == "poll_begin"]
    begins[1]["cache_source_seq"] = begins[1]["seq"] - 1
    with pytest.raises(JournalV5Error, match="current same-slot miss"):
        inspect_untrusted_v5_journal(json.dumps(journal).encode())


def test_active_cache_hit_binding_matches_current_miss_with_exact_json_types():
    raw = _journal_with_polls([
        {"active": True, "table_raw_binding": {"table": {"id": 1}}},
        {"active": True, "table_raw_binding": {"table": {"id": 1}}},
    ])
    inspect_untrusted_v5_journal(raw)
    journal = json.loads(raw)
    begins = [event for event in journal["events"] if event["kind"] == "poll_begin"]
    begins[1]["table_raw_binding"] = {"table": {"id": True}}
    with pytest.raises(JournalV5Error, match="table binding differs"):
        inspect_untrusted_v5_journal(json.dumps(journal).encode())

    begins[1]["table_raw_binding"] = {"table": {"id": 1}}
    begins[0]["table_raw_binding"] = None
    with pytest.raises(JournalV5Error, match="active poll must have an object"):
        inspect_untrusted_v5_journal(json.dumps(journal).encode())


def test_poll_end_must_precede_exec_and_exec_starts_a_fresh_cache_epoch():
    proc = _process()
    guard = lambda seq: _event(
        "loop_guard", seq, process_generation_id=proc, driver_id="main",
        loop_iteration_id=seq, time_step_ieee754_hex="0000000000000000",
        time_max_ieee754_hex="3ff0000000000000", condition_result=True,
    )
    poll = lambda seq, guard_seq, action, source: _event(
        "poll_begin", seq, poll_begin_id=seq, process_generation_id=proc,
        solver_instance_id="main", driver_id="main", guard_seq=guard_seq,
        callsite_id="cpu.pre_interaction_forces.run_cpu", integrator="Verlet",
        interstep="INTERSTEP_Verlet", input_entry_index=0,
        timestep_ieee754_hex="0000000000000000", active=False,
        cache_action=action, cache_source_seq=source, table_raw_binding=None,
    )
    exec_event = lambda seq: _event(
        "exec", seq, process_generation_id=proc, executable_binding={},
        argv_sha256="4" * 64, cwd_object_id="cwd-v2", environment_sha256="5" * 64,
    )
    events = [
        _event("spawn", 0, process_generation_id=proc, supervisor_identity_binding={}),
        _event("exec", 1, process_generation_id=proc, executable_binding={}, argv_sha256="2" * 64, cwd_object_id="cwd-v1", environment_sha256="3" * 64),
        guard(2), poll(3, 2, "miss", None), exec_event(4),
        _event("poll_end", 5, poll_begin_id=3, process_generation_id=proc, outcome="returned"),
        _event("exit", 6, process_generation_id=proc, exit_code=0, signal=None),
        _event("reap", 7, process_generation_id=proc),
    ]
    with pytest.raises(JournalV5Error, match="poll_end must precede a later exec"):
        inspect_untrusted_v5_journal(_journal(events))

    events = [
        _event("spawn", 0, process_generation_id=proc, supervisor_identity_binding={}),
        _event("exec", 1, process_generation_id=proc, executable_binding={}, argv_sha256="2" * 64, cwd_object_id="cwd-v1", environment_sha256="3" * 64),
        guard(2), poll(3, 2, "miss", None),
        _event("poll_end", 4, poll_begin_id=3, process_generation_id=proc, outcome="returned"),
        exec_event(5), guard(6), poll(7, 6, "hit", 3),
        _event("poll_end", 8, poll_begin_id=7, process_generation_id=proc, outcome="returned"),
        _event("exit", 9, process_generation_id=proc, exit_code=0, signal=None),
        _event("reap", 10, process_generation_id=proc),
    ]
    with pytest.raises(JournalV5Error, match="cache_action differs"):
        inspect_untrusted_v5_journal(_journal(events))

    events = [
        _event("spawn", 0, process_generation_id=proc, supervisor_identity_binding={}),
        _event("exec", 1, process_generation_id=proc, executable_binding={}, argv_sha256="2" * 64, cwd_object_id="cwd-v1", environment_sha256="3" * 64),
        guard(2), poll(3, 2, "miss", None),
        _event("poll_end", 4, poll_begin_id=3, process_generation_id=proc, outcome="returned"),
        exec_event(5), guard(6), poll(7, 6, "miss", None),
        _event("poll_end", 8, poll_begin_id=7, process_generation_id=proc, outcome="returned"),
        _event("exit", 9, process_generation_id=proc, exit_code=0, signal=None),
        _event("reap", 10, process_generation_id=proc),
    ]
    result = inspect_untrusted_v5_journal(_journal(events))
    assert result["cache_exec_epoch_reset_count"] == 1
    assert result["cache_replay_diagnostic_state"] == "unresolved_output_state"

    events = [
        _event("spawn", 0, process_generation_id=proc, supervisor_identity_binding={}),
        _event("exec", 1, process_generation_id=proc, executable_binding={}, argv_sha256="2" * 64, cwd_object_id="cwd-v1", environment_sha256="3" * 64),
        guard(2), exec_event(3), poll(4, 2, "miss", None),
        _event("poll_end", 5, poll_begin_id=4, process_generation_id=proc, outcome="returned"),
        _event("exit", 6, process_generation_id=proc, exit_code=0, signal=None),
        _event("reap", 7, process_generation_id=proc),
    ]
    with pytest.raises(JournalV5Error, match="same-generation driver/iteration guard"):
        inspect_untrusted_v5_journal(_journal(events))


def test_overlapping_poll_calls_for_one_cache_slot_are_rejected():
    proc = _process()
    events = [
        _event("spawn", 0, process_generation_id=proc, supervisor_identity_binding={}),
        _event("exec", 1, process_generation_id=proc, executable_binding={}, argv_sha256="2" * 64, cwd_object_id="cwd-v1", environment_sha256="3" * 64),
        _event("loop_guard", 2, process_generation_id=proc, driver_id="main", loop_iteration_id=0, time_step_ieee754_hex="0000000000000000", time_max_ieee754_hex="3ff0000000000000", condition_result=True),
        _event("poll_begin", 3, poll_begin_id=3, process_generation_id=proc, solver_instance_id="main", driver_id="main", guard_seq=2, callsite_id="cpu.pre_interaction_forces.run_cpu", integrator="Verlet", interstep="INTERSTEP_Verlet", input_entry_index=0, timestep_ieee754_hex="0000000000000000", active=True, cache_action="miss", cache_source_seq=None, table_raw_binding={}),
        _event("loop_guard", 4, process_generation_id=proc, driver_id="main", loop_iteration_id=1, time_step_ieee754_hex="0000000000000000", time_max_ieee754_hex="3ff0000000000000", condition_result=True),
        _event("poll_begin", 5, poll_begin_id=5, process_generation_id=proc, solver_instance_id="main", driver_id="main", guard_seq=4, callsite_id="cpu.pre_interaction_forces.run_cpu", integrator="Verlet", interstep="INTERSTEP_Verlet", input_entry_index=0, timestep_ieee754_hex="0000000000000000", active=True, cache_action="hit", cache_source_seq=3, table_raw_binding={}),
        _event("poll_end", 6, poll_begin_id=5, process_generation_id=proc, outcome="returned"),
        _event("poll_end", 7, poll_begin_id=3, process_generation_id=proc, outcome="returned"),
        _event("exit", 8, process_generation_id=proc, exit_code=0, signal=None),
        _event("reap", 9, process_generation_id=proc),
    ]
    with pytest.raises(JournalV5Error, match="driver loop event occurs before a prior poll_end"):
        inspect_untrusted_v5_journal(_journal(events))


def test_unclosed_same_slot_poll_followed_by_another_call_is_explicitly_unresolved():
    result = inspect_untrusted_v5_journal(_journal_with_polls([
        {"outcome": None}, {},
    ]))
    assert result["poll_begin_count"] == 2
    assert result["unterminated_poll_count"] == 1
    assert result["cache_unclosed_prior_poll_count"] == 1
    assert result["cache_transitions_observed_consistent"] is False
    assert result["cache_replay_diagnostic_state"] == "unresolved_call_order"
    assert result["gate_state"] == "open"


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
