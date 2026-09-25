"""Non-authorizing parser for the synthetic F8 R008 C journal V5.

This parser checks serialization, exact event field sets, primitive domains,
journal-local sequence/clock and process/thread state, guard links, and a
single-slot cache replay over caller-provided events. It does not establish
that the journal is complete or truthful, validate the source callgraph,
recompute active windows/table provenance, attest runtime identity, or
authorize execution/qualification.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import struct
from typing import Any


JOURNAL_SCHEMA = "core.cfd.f8.r008_c_execution_journal.synthetic.v5"
MAX_RAW_BYTES = 1_073_741_824
MAX_EVENT_COUNT = 100_000_000
_HEX16 = re.compile(r"^[0-9a-f]{16}$")
_HEX32 = re.compile(r"^[0-9a-f]{32}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_TOP_KEYS = frozenset({
    "schema", "attempt_nonce_hex", "source_id", "source_binary_sha256",
    "coverage_start_ns_hex", "coverage_end_ns_hex", "event_count", "overflow",
    "lost_count", "events",
})
_COMMON_EVENT_KEYS = frozenset({"seq", "mono_ns_hex", "kind", "attempt_nonce_hex"})
_PROCESS_EVENT_KEYS = {
    "spawn": frozenset({"process_generation_id", "supervisor_identity_binding"}),
    "fork": frozenset({"parent_generation_id", "process_generation_id"}),
    "clone_process": frozenset({"parent_generation_id", "process_generation_id", "clone_flags_hex"}),
    "thread_create": frozenset({"process_generation_id", "thread_generation_id", "clone_flags_hex"}),
    "thread_exit": frozenset({"process_generation_id", "thread_generation_id"}),
    "exec": frozenset({
        "process_generation_id", "executable_binding", "argv_sha256", "cwd_object_id",
        "environment_sha256",
    }),
    "exit": frozenset({"process_generation_id", "exit_code", "signal"}),
    "reap": frozenset({"process_generation_id"}),
    "load": frozenset({"process_generation_id", "object_binding", "object_kind"}),
    "cgroup": frozenset({"process_generation_id", "action", "cgroup_id"}),
}
_EVENT_KEYS = {
    **{kind: _COMMON_EVENT_KEYS | fields for kind, fields in _PROCESS_EVENT_KEYS.items()},
    "loop_guard": _COMMON_EVENT_KEYS | frozenset({
        "process_generation_id", "driver_id", "loop_iteration_id", "time_step_ieee754_hex",
        "time_max_ieee754_hex", "condition_result",
    }),
    "poll_begin": _COMMON_EVENT_KEYS | frozenset({
        "poll_begin_id", "process_generation_id", "solver_instance_id", "driver_id", "guard_seq",
        "callsite_id", "integrator", "interstep", "input_entry_index", "timestep_ieee754_hex",
        "active", "cache_action", "cache_source_seq", "table_raw_binding",
    }),
    "poll_end": _COMMON_EVENT_KEYS | frozenset({
        "poll_begin_id", "process_generation_id", "outcome",
    }),
}
_GENERATION_KEYS = frozenset({
    "pid_namespace_inode_hex", "pid", "start_monotonic_ns_hex",
    "kernel_starttime_ticks_hex", "birth_seq_hex",
})
_THREAD_GENERATION_KEYS = frozenset({
    "tid", "start_monotonic_ns_hex", "kernel_starttime_ticks_hex", "birth_seq_hex",
})
_REFERENCE_KEYS = frozenset({"stage", "role", "object_id", "bytes", "sha256"})
_CALLSITES = frozenset({
    "cpu.pre_interaction_forces.run_cpu", "gpu.pre_interaction_forces.run_gpu",
})
_INTEGRATORS = frozenset({"Verlet", "Symplectic", "VRes"})
_INTERSTEPS = frozenset({
    "INTERSTEP_Verlet", "INTERSTEP_SymPredictor", "INTERSTEP_SymCorrector",
})


class JournalV5Error(ValueError):
    """Raw journal bytes or fields violate the synthetic V5 structural contract."""


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise JournalV5Error(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise JournalV5Error(f"non-finite JSON constant is forbidden: {value}")


def _parse_finite_float(token: str) -> float:
    value = float(token)
    if not math.isfinite(value):
        raise JournalV5Error("JSON float is outside the finite domain")
    return value


def _parse_json(raw: bytes) -> dict[str, Any]:
    if type(raw) is not bytes:
        raise JournalV5Error("journal must be exact bytes")
    if len(raw) > MAX_RAW_BYTES:
        raise JournalV5Error("journal exceeds the V4-inherited raw byte limit")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise JournalV5Error("journal is not strict UTF-8") from error
    try:
        value = json.loads(
            text,
            strict=True,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_constant,
            parse_float=_parse_finite_float,
        )
    except JournalV5Error:
        raise
    except (json.JSONDecodeError, ValueError, OverflowError, RecursionError) as error:
        raise JournalV5Error("journal is not valid strict JSON") from error
    if type(value) is not dict:
        raise JournalV5Error("journal top level must be an object")
    return value


def _exact_object(value: Any, keys: frozenset[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise JournalV5Error(f"{label} fields do not match the exact schema")
    return value


def _builtin_int(value: Any, label: str, *, minimum: int = 0, maximum: int = MAX_EVENT_COUNT) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise JournalV5Error(f"{label} must be an exact builtin integer in range")
    return value


def _identifier(value: Any, label: str) -> str:
    if type(value) is not str or not _IDENTIFIER.fullmatch(value):
        raise JournalV5Error(f"{label} is outside the fixed ASCII identifier domain")
    return value


def _hex(value: Any, label: str, pattern: re.Pattern[str]) -> str:
    if type(value) is not str or not pattern.fullmatch(value):
        raise JournalV5Error(f"{label} has an invalid lowercase-hex encoding")
    return value


def _generation(value: Any, label: str, *, created_seq: int | None = None) -> dict[str, Any]:
    generation = _exact_object(value, _GENERATION_KEYS, label)
    for key in (
        "pid_namespace_inode_hex", "start_monotonic_ns_hex", "kernel_starttime_ticks_hex",
        "birth_seq_hex",
    ):
        _hex(generation[key], f"{label}.{key}", _HEX16)
    _builtin_int(generation["pid"], f"{label}.pid", minimum=1)
    if created_seq is not None and generation["birth_seq_hex"] != f"{created_seq:016x}":
        raise JournalV5Error(f"{label}.birth_seq_hex does not match its creation event")
    return generation


def _thread_generation(value: Any, label: str, *, created_seq: int | None = None) -> dict[str, Any]:
    generation = _exact_object(value, _THREAD_GENERATION_KEYS, label)
    _builtin_int(generation["tid"], f"{label}.tid", minimum=1)
    for key in ("start_monotonic_ns_hex", "kernel_starttime_ticks_hex", "birth_seq_hex"):
        _hex(generation[key], f"{label}.{key}", _HEX16)
    if created_seq is not None and generation["birth_seq_hex"] != f"{created_seq:016x}":
        raise JournalV5Error(f"{label}.birth_seq_hex does not match its creation event")
    return generation


def _binding_object(value: Any, label: str) -> None:
    if type(value) is not dict:
        raise JournalV5Error(f"{label} must be an object")


def _finite_binary64_hex(value: Any, label: str) -> str:
    encoded = _hex(value, label, _HEX16)
    if not math.isfinite(struct.unpack(">d", bytes.fromhex(encoded))[0]):
        raise JournalV5Error(f"{label} must encode a finite binary64 value")
    return encoded


def _table_binding(value: Any, label: str) -> None:
    if value is None:
        return
    if type(value) is not dict:
        raise JournalV5Error(f"{label} must be null or an object")


def _same_json_value(left: Any, right: Any) -> bool:
    """Compare parsed JSON values without Python's bool/int equivalence."""
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        return (set(left) == set(right)
                and all(_same_json_value(left[key], right[key]) for key in left))
    if type(left) is list:
        return (len(left) == len(right)
                and all(_same_json_value(a, b) for a, b in zip(left, right)))
    return left == right


def _validate_event(event: Any, *, expected_seq: int, nonce: str) -> dict[str, Any]:
    if type(event) is not dict:
        raise JournalV5Error("event must be an object")
    kind = event.get("kind")
    if type(kind) is not str or kind not in _EVENT_KEYS:
        raise JournalV5Error("event kind is not in the V5 event union")
    event = _exact_object(event, _EVENT_KEYS[kind], f"{kind} event")
    if _builtin_int(event["seq"], f"{kind}.seq") != expected_seq:
        raise JournalV5Error("event seq values must be exactly contiguous from zero")
    _hex(event["mono_ns_hex"], f"{kind}.mono_ns_hex", _HEX16)
    if _hex(event["attempt_nonce_hex"], f"{kind}.attempt_nonce_hex", _HEX32) != nonce:
        raise JournalV5Error("event attempt nonce differs from journal nonce")

    if kind in {"spawn", "fork", "clone_process"}:
        _generation(event["process_generation_id"], f"{kind}.process_generation_id", created_seq=expected_seq)
    if kind in {"fork", "clone_process"}:
        _generation(event["parent_generation_id"], f"{kind}.parent_generation_id")
    if kind == "spawn":
        _binding_object(event["supervisor_identity_binding"], "spawn.supervisor_identity_binding")
    elif kind == "clone_process":
        _hex(event["clone_flags_hex"], "clone_process.clone_flags_hex", _HEX16)
    elif kind == "thread_create":
        _generation(event["process_generation_id"], "thread_create.process_generation_id")
        _thread_generation(event["thread_generation_id"], "thread_create.thread_generation_id", created_seq=expected_seq)
        _hex(event["clone_flags_hex"], "thread_create.clone_flags_hex", _HEX16)
    elif kind == "thread_exit":
        _generation(event["process_generation_id"], "thread_exit.process_generation_id")
        _thread_generation(event["thread_generation_id"], "thread_exit.thread_generation_id")
    elif kind == "exec":
        _generation(event["process_generation_id"], "exec.process_generation_id")
        _binding_object(event["executable_binding"], "exec.executable_binding")
        _hex(event["argv_sha256"], "exec.argv_sha256", _SHA256)
        _identifier(event["cwd_object_id"], "exec.cwd_object_id")
        _hex(event["environment_sha256"], "exec.environment_sha256", _SHA256)
    elif kind in {"exit", "reap", "load", "cgroup"}:
        _generation(event["process_generation_id"], f"{kind}.process_generation_id")
        if kind == "exit":
            exit_code, signal = event["exit_code"], event["signal"]
            valid_exit = type(exit_code) is int and 0 <= exit_code <= 255 and signal is None
            valid_signal = exit_code is None and type(signal) is int and signal > 0
            if not (valid_exit or valid_signal):
                raise JournalV5Error("exit must contain either an exact exit code or positive signal")
        elif kind == "load":
            _binding_object(event["object_binding"], "load.object_binding")
            _identifier(event["object_kind"], "load.object_kind")
        elif kind == "cgroup":
            _identifier(event["action"], "cgroup.action")
            _identifier(event["cgroup_id"], "cgroup.cgroup_id")
    elif kind == "loop_guard":
        _generation(event["process_generation_id"], "loop_guard.process_generation_id")
        _identifier(event["driver_id"], "loop_guard.driver_id")
        _builtin_int(event["loop_iteration_id"], "loop_guard.loop_iteration_id")
        _finite_binary64_hex(event["time_step_ieee754_hex"], "loop_guard.time_step_ieee754_hex")
        _finite_binary64_hex(event["time_max_ieee754_hex"], "loop_guard.time_max_ieee754_hex")
        if type(event["condition_result"]) is not bool:
            raise JournalV5Error("loop_guard.condition_result must be an exact boolean")
        time_step = struct.unpack(">d", bytes.fromhex(event["time_step_ieee754_hex"]))[0]
        time_max = struct.unpack(">d", bytes.fromhex(event["time_max_ieee754_hex"]))[0]
        if event["condition_result"] is not (time_step < time_max):
            raise JournalV5Error("loop_guard.condition_result differs from strict binary64 time comparison")
    elif kind == "poll_begin":
        if _builtin_int(event["poll_begin_id"], "poll_begin.poll_begin_id") != expected_seq:
            raise JournalV5Error("poll_begin_id must equal its event seq")
        _generation(event["process_generation_id"], "poll_begin.process_generation_id")
        _identifier(event["solver_instance_id"], "poll_begin.solver_instance_id")
        _identifier(event["driver_id"], "poll_begin.driver_id")
        _builtin_int(event["guard_seq"], "poll_begin.guard_seq")
        if event["guard_seq"] >= expected_seq:
            raise JournalV5Error("poll_begin.guard_seq must precede the poll")
        if type(event["callsite_id"]) is not str or event["callsite_id"] not in _CALLSITES:
            raise JournalV5Error("poll_begin.callsite_id is outside the frozen enum")
        if type(event["integrator"]) is not str or event["integrator"] not in _INTEGRATORS:
            raise JournalV5Error("poll_begin.integrator is outside the frozen enum")
        if type(event["interstep"]) is not str or event["interstep"] not in _INTERSTEPS:
            raise JournalV5Error("poll_begin.interstep is outside the frozen enum")
        _builtin_int(event["input_entry_index"], "poll_begin.input_entry_index", maximum=65_535)
        _finite_binary64_hex(event["timestep_ieee754_hex"], "poll_begin.timestep_ieee754_hex")
        if type(event["active"]) is not bool:
            raise JournalV5Error("poll_begin.active must be an exact boolean")
        if type(event["cache_action"]) is not str or event["cache_action"] not in {"miss", "hit"}:
            raise JournalV5Error("poll_begin.cache_action is outside the frozen enum")
        source_seq = event["cache_source_seq"]
        if event["cache_action"] == "miss":
            if source_seq is not None:
                raise JournalV5Error("cache miss must have a null cache_source_seq")
        elif _builtin_int(source_seq, "poll_begin.cache_source_seq") >= expected_seq:
            raise JournalV5Error("cache hit source seq must precede the poll")
        _table_binding(event["table_raw_binding"], "poll_begin.table_raw_binding")
        if not event["active"] and event["table_raw_binding"] is not None:
            raise JournalV5Error("inactive poll must have a null table binding")
        if event["active"] and event["table_raw_binding"] is None:
            raise JournalV5Error("active poll must have an object table binding")
    elif kind == "poll_end":
        _builtin_int(event["poll_begin_id"], "poll_end.poll_begin_id")
        if event["poll_begin_id"] >= expected_seq:
            raise JournalV5Error("poll_end must follow its poll_begin")
        _generation(event["process_generation_id"], "poll_end.process_generation_id")
        if type(event["outcome"]) is not str or event["outcome"] not in {"returned", "exception"}:
            raise JournalV5Error("poll_end.outcome is outside the frozen enum")
    return event


def _process_key(generation: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(generation[key] for key in (
        "pid_namespace_inode_hex", "pid", "start_monotonic_ns_hex",
        "kernel_starttime_ticks_hex", "birth_seq_hex",
    ))


def _thread_key(generation: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(generation[key] for key in (
        "tid", "start_monotonic_ns_hex", "kernel_starttime_ticks_hex", "birth_seq_hex",
    ))


def _observe_process_lifecycle(events: list[dict[str, Any]]) -> dict[str, int | bool]:
    """Recompute journal-local process/thread transitions without attesting them."""
    processes: dict[tuple[Any, ...], dict[str, Any]] = {}
    pid_generations: dict[tuple[str, int], tuple[Any, ...]] = {}
    threads: dict[tuple[Any, ...], dict[str, Any]] = {}
    active_tids: dict[tuple[str, int], tuple[Any, ...]] = {}
    roots = 0

    for event in events:
        kind = event["kind"]
        if kind in {"spawn", "fork", "clone_process"}:
            generation = event["process_generation_id"]
            generation_key = _process_key(generation)
            if generation_key in processes:
                raise JournalV5Error("process generation was created more than once")
            pid_key = (generation["pid_namespace_inode_hex"], generation["pid"])
            previous_generation = pid_generations.get(pid_key)
            if (previous_generation is not None
                    and processes[previous_generation]["state"] != "reaped"):
                raise JournalV5Error("PID reuse occurred before the previous generation was reaped")

            if kind == "spawn":
                roots += 1
                if roots != 1:
                    raise JournalV5Error("journal must not create multiple solver root generations")
                parent_key = None
                state = "created"
            else:
                parent_key = _process_key(event["parent_generation_id"])
                parent = processes.get(parent_key)
                if parent is None or parent["state"] != "running":
                    raise JournalV5Error(f"{kind} parent must be a running known generation")
                state = "running"
            processes[generation_key] = {
                "generation": generation,
                "parent_key": parent_key,
                "state": state,
            }
            pid_generations[pid_key] = generation_key
            continue

        if kind == "thread_create":
            owner_key = _process_key(event["process_generation_id"])
            owner = processes.get(owner_key)
            if owner is None or owner["state"] != "running":
                raise JournalV5Error("thread_create owner must be a running known process")
            generation = event["thread_generation_id"]
            generation_key = _thread_key(generation)
            if generation_key in threads:
                raise JournalV5Error("thread generation was created more than once")
            owner_generation = owner["generation"]
            tid_key = (owner_generation["pid_namespace_inode_hex"], generation["tid"])
            previous_thread = active_tids.get(tid_key)
            if previous_thread is not None and threads[previous_thread]["state"] != "thread_exited":
                raise JournalV5Error("TID reuse occurred before the previous thread exited")
            threads[generation_key] = {"owner_key": owner_key, "state": "running"}
            active_tids[tid_key] = generation_key
            continue

        if kind == "thread_exit":
            owner_key = _process_key(event["process_generation_id"])
            owner = processes.get(owner_key)
            thread_key = _thread_key(event["thread_generation_id"])
            thread = threads.get(thread_key)
            if (owner is None or owner["state"] in {"exited", "reaped"}
                    or thread is None or thread["owner_key"] != owner_key
                    or thread["state"] != "running"):
                raise JournalV5Error("thread_exit does not match a live owned thread generation")
            thread["state"] = "thread_exited"
            continue

        if kind not in {"exec", "load", "cgroup", "loop_guard", "poll_begin", "poll_end", "exit", "reap"}:
            continue
        generation_key = _process_key(event["process_generation_id"])
        process = processes.get(generation_key)
        if process is None:
            raise JournalV5Error(f"{kind} references an unknown process generation")
        state = process["state"]
        if kind == "exec":
            if state not in {"created", "running"}:
                raise JournalV5Error("exec occurred after process exit or reap")
            process["state"] = "running"
        elif kind in {"loop_guard", "poll_begin", "poll_end"}:
            if state != "running":
                raise JournalV5Error(f"{kind} requires a running process generation")
        elif kind in {"load", "cgroup"}:
            if state in {"exited", "reaped"}:
                raise JournalV5Error(f"{kind} occurred after process exit or reap")
        elif kind == "exit":
            if state != "running":
                raise JournalV5Error("process exit requires a running generation")
            if any(
                thread["owner_key"] == generation_key and thread["state"] == "running"
                for thread in threads.values()
            ):
                raise JournalV5Error("process exited before its threads terminated")
            process["state"] = "exited"
        elif kind == "reap":
            if state != "exited":
                raise JournalV5Error("process reap must follow exactly one exit")
            process["state"] = "reaped"

    reaped_count = sum(process["state"] == "reaped" for process in processes.values())
    exited_threads = sum(thread["state"] == "thread_exited" for thread in threads.values())
    complete = (
        roots == 1
        and reaped_count == len(processes)
        and exited_threads == len(threads)
    )
    return {
        "process_root_count": roots,
        "process_generation_count": len(processes),
        "process_reaped_count": reaped_count,
        "thread_generation_count": len(threads),
        "thread_exited_count": exited_threads,
        "observed_process_lifecycle_complete": complete,
    }


def _observe_query_and_cache(
    events: list[dict[str, Any]], ends: dict[int, dict[str, Any]],
) -> dict[str, int | bool | str]:
    """Replay guard links and the journal-local LastTimestepInput slot."""
    guards = {event["seq"]: event for event in events if event["kind"] == "loop_guard"}
    end_seq_by_begin = {begin_seq: end["seq"] for begin_seq, end in ends.items()}
    begins = {event["seq"]: event for event in events if event["kind"] == "poll_begin"}
    for begin_seq, begin in begins.items():
        end_seq = end_seq_by_begin.get(begin_seq)
        upper = end_seq if end_seq is not None else len(events)
        for candidate in events[begin_seq + 1:upper]:
            if (candidate.get("process_generation_id") == begin["process_generation_id"]
                    and candidate["kind"] == "exec"):
                raise JournalV5Error("poll_end must precede a later exec in the same process generation")

    cache: dict[tuple[Any, ...], dict[str, Any]] = {}
    last_begin_by_slot: dict[tuple[Any, ...], int] = {}
    process_exec_epoch: dict[tuple[Any, ...], int] = {}
    guard_exec_epoch: dict[int, int] = {}
    clone_cache_unknown: set[tuple[Any, ...]] = set()
    driver_loops: dict[tuple[Any, ...], dict[str, Any]] = {}
    latest_guard_by_driver: dict[tuple[Any, ...], int] = {}
    polls_by_driver: dict[tuple[Any, ...], list[int]] = {}
    reported_unclosed_driver_polls: set[int] = set()
    linked_query_count = 0
    unknown_cache_source_count = 0
    hit_with_unknown_source_count = 0
    unterminated_hit_count = 0
    exec_epoch_reset_count = 0
    unresolved_clone_poll_count = 0
    unclosed_prior_poll_count = 0
    driver_unclosed_poll_count = 0

    def check_prior_driver_polls(driver_key: tuple[Any, ...], boundary_seq: int) -> None:
        nonlocal driver_unclosed_poll_count
        for begin_seq in polls_by_driver.get(driver_key, []):
            if begin_seq >= boundary_seq:
                continue
            end_seq = end_seq_by_begin.get(begin_seq)
            if end_seq is not None:
                if end_seq > boundary_seq:
                    raise JournalV5Error("driver loop event occurs before a prior poll_end")
            elif begin_seq not in reported_unclosed_driver_polls:
                reported_unclosed_driver_polls.add(begin_seq)
                driver_unclosed_poll_count += 1
                driver_state = driver_loops.get(driver_key)
                if driver_state is not None:
                    driver_state["unclosed_poll_count"] += 1

    for event in events:
        kind = event["kind"]
        if kind == "spawn":
            process_exec_epoch[_process_key(event["process_generation_id"])] = 0
            continue
        if kind in {"fork", "clone_process"}:
            parent_key = _process_key(event["parent_generation_id"])
            child_key = _process_key(event["process_generation_id"])
            process_exec_epoch[child_key] = process_exec_epoch.get(parent_key, 0)
            # A fork/clone may inherit the parent's live C++ object/cache
            # memory. Until exec or a source-bound reconstruction proves a
            # fresh JDsAccInputMk, the child's initial cache cannot be assumed.
            clone_cache_unknown.add(child_key)
            continue
        if kind == "exec":
            process_key = _process_key(event["process_generation_id"])
            stale_keys = [key for key in cache if key[0] == process_key]
            if stale_keys or process_key in clone_cache_unknown:
                exec_epoch_reset_count += 1
                for key in stale_keys:
                    del cache[key]
            clone_cache_unknown.discard(process_key)
            process_exec_epoch[process_key] = process_exec_epoch.get(process_key, 0) + 1
            continue
        if kind == "loop_guard":
            process_key = _process_key(event["process_generation_id"])
            epoch = process_exec_epoch.get(process_key, 0)
            guard_exec_epoch[event["seq"]] = epoch
            driver_key = (process_key, epoch, event["driver_id"])
            check_prior_driver_polls(driver_key, event["seq"])
            driver_state = driver_loops.setdefault(driver_key, {
                "iteration_ids": set(),
                "termination_guard_count": 0,
                "terminated": False,
                "unclosed_poll_count": 0,
            })
            if driver_state["terminated"]:
                raise JournalV5Error("driver loop guard occurred after its terminal false guard")
            iteration_id = event["loop_iteration_id"]
            if iteration_id in driver_state["iteration_ids"]:
                raise JournalV5Error("driver loop iteration id is duplicated within one exec epoch")
            driver_state["iteration_ids"].add(iteration_id)
            latest_guard_by_driver[driver_key] = event["seq"]
            if event["condition_result"] is False:
                driver_state["termination_guard_count"] += 1
                driver_state["terminated"] = True
            continue
        if kind != "poll_begin":
            continue

        process_key = _process_key(event["process_generation_id"])
        guard = guards.get(event["guard_seq"])
        if (guard is None
                or guard["process_generation_id"] != event["process_generation_id"]
                or guard["driver_id"] != event["driver_id"]
                or guard["condition_result"] is not True
                or guard["time_step_ieee754_hex"] != event["timestep_ieee754_hex"]
                or guard_exec_epoch.get(event["guard_seq"]) != process_exec_epoch.get(process_key, 0)):
            raise JournalV5Error("poll_begin does not match its true same-generation driver/iteration guard")
        linked_query_count += 1
        driver_key = (process_key, process_exec_epoch.get(process_key, 0), event["driver_id"])
        driver_state = driver_loops.get(driver_key)
        if driver_state is None or driver_state["terminated"]:
            raise JournalV5Error("poll_begin occurs outside an active observed driver loop")
        if latest_guard_by_driver.get(driver_key) != event["guard_seq"]:
            raise JournalV5Error("poll_begin references a stale driver loop guard")
        check_prior_driver_polls(driver_key, event["seq"])
        polls_by_driver.setdefault(driver_key, []).append(event["seq"])

        instance_key = (
            process_key,
            event["solver_instance_id"],
            event["input_entry_index"],
        )
        previous_begin_seq = last_begin_by_slot.get(instance_key)
        previous_end_seq = end_seq_by_begin.get(previous_begin_seq)
        if previous_end_seq is not None and previous_end_seq > event["seq"]:
            raise JournalV5Error("poll calls overlap for the same cache slot")
        if previous_begin_seq is not None and previous_end_seq is None:
            # The previous call may have returned with a lost terminal record
            # or may still be in flight; neither permits complete replay.
            unclosed_prior_poll_count += 1
        last_begin_by_slot[instance_key] = event["seq"]

        if process_key in clone_cache_unknown:
            unresolved_clone_poll_count += 1
            continue

        slot = cache.setdefault(instance_key, {
            "last_timestep": -1.0,
            "source_seq": None,
            "output_known": True,
        })
        timestep = struct.unpack(">d", bytes.fromhex(event["timestep_ieee754_hex"]))[0]
        is_hit = slot["last_timestep"] >= 0 and timestep == slot["last_timestep"]
        expected_action = "hit" if is_hit else "miss"
        if event["cache_action"] != expected_action:
            raise JournalV5Error("poll cache_action differs from the source single-slot numeric comparison")

        end = ends.get(event["seq"])
        if is_hit:
            if slot["source_seq"] is None or event["cache_source_seq"] != slot["source_seq"]:
                raise JournalV5Error("cache hit does not reference the current same-slot miss")
            if event["active"]:
                source_begin = begins[slot["source_seq"]]
                if (not source_begin["active"]
                        or not _same_json_value(
                            event["table_raw_binding"], source_begin["table_raw_binding"]
                        )):
                    raise JournalV5Error("active cache-hit table binding differs from its current miss")
            if not slot["output_known"]:
                hit_with_unknown_source_count += 1
            if end is not None and end["outcome"] == "exception":
                raise JournalV5Error("source cache-hit branch cannot produce a table-read exception")
            if end is None:
                # A hit returns early without mutating LastTimestepInput or
                # LastOutput. It is still an incomplete poll, but does not
                # poison the prior successful miss's cached value.
                unterminated_hit_count += 1
        else:
            if event["cache_source_seq"] is not None:
                raise JournalV5Error("cache miss unexpectedly references an older cache source")
            # The C++ method writes LastTimestepInput before table reads. An
            # exception or absent end therefore poisons only the cached value,
            # not the new timestamp/source slot.
            slot["last_timestep"] = timestep
            slot["source_seq"] = event["seq"]
            slot["output_known"] = end is not None and end["outcome"] == "returned"
            if end is not None and end["outcome"] == "exception" and not event["active"]:
                raise JournalV5Error("inactive source branch cannot produce a table-read exception")
            if not slot["output_known"]:
                unknown_cache_source_count += 1

    has_unknown_state = (
        unknown_cache_source_count > 0
        or hit_with_unknown_source_count > 0
        or exec_epoch_reset_count > 0
        or unresolved_clone_poll_count > 0
        or unclosed_prior_poll_count > 0
        or driver_unclosed_poll_count > 0
        or unterminated_hit_count > 0
    )
    terminated_driver_loop_count = sum(state["terminated"] for state in driver_loops.values())
    observed_driver_loops_complete = bool(driver_loops) and (
        terminated_driver_loop_count == len(driver_loops)
        and all(state["unclosed_poll_count"] == 0 for state in driver_loops.values())
    )
    return {
        "query_guard_link_count": linked_query_count,
        "cache_unknown_source_count": unknown_cache_source_count,
        "cache_hit_with_unknown_source_count": hit_with_unknown_source_count,
        "cache_unterminated_hit_count": unterminated_hit_count,
        "cache_exec_epoch_reset_count": exec_epoch_reset_count,
        "cache_fork_unresolved_poll_count": unresolved_clone_poll_count,
        "cache_unclosed_prior_poll_count": unclosed_prior_poll_count,
        "driver_unclosed_poll_count": driver_unclosed_poll_count,
        "observed_driver_loop_count": len(driver_loops),
        "observed_driver_loop_termination_guard_count": sum(
            state["termination_guard_count"] for state in driver_loops.values()
        ),
        "observed_driver_loops_complete": observed_driver_loops_complete,
        "driver_loop_termination_verified": False,
        "query_guard_links_observed_consistent": True,
        "cache_transitions_observed_consistent": (
            unresolved_clone_poll_count == 0
            and unclosed_prior_poll_count == 0
            and driver_unclosed_poll_count == 0
        ),
        "cache_replay_diagnostic_state": (
            "unresolved_fork_cache_state" if unresolved_clone_poll_count > 0
            else "unresolved_call_order" if unclosed_prior_poll_count > 0 or driver_unclosed_poll_count > 0
            else "incomplete_poll_state" if unterminated_hit_count > 0
            else "unresolved_output_state" if has_unknown_state
            else "journal_local_consistent_unverified"
        ),
    }


def inspect_untrusted_v5_journal(raw: bytes) -> dict[str, Any]:
    """Inspect journal bytes and return only a non-authorizing diagnostic."""
    journal = _parse_json(raw)
    journal = _exact_object(journal, _TOP_KEYS, "journal")
    if type(journal["schema"]) is not str or journal["schema"] != JOURNAL_SCHEMA:
        raise JournalV5Error("journal schema mismatch")
    nonce = _hex(journal["attempt_nonce_hex"], "journal.attempt_nonce_hex", _HEX32)
    source_id = _identifier(journal["source_id"], "journal.source_id")
    _hex(journal["source_binary_sha256"], "journal.source_binary_sha256", _SHA256)
    coverage_start = int(_hex(journal["coverage_start_ns_hex"], "journal.coverage_start_ns_hex", _HEX16), 16)
    coverage_end = int(_hex(journal["coverage_end_ns_hex"], "journal.coverage_end_ns_hex", _HEX16), 16)
    if coverage_start > coverage_end:
        raise JournalV5Error("journal coverage start must not exceed end")
    event_count = _builtin_int(journal["event_count"], "journal.event_count")
    if event_count > MAX_EVENT_COUNT:
        raise JournalV5Error("journal event_count exceeds the inherited limit")
    if type(journal["events"]) is not list or event_count != len(journal["events"]):
        raise JournalV5Error("journal event_count must equal events length")
    if type(journal["overflow"]) is not bool:
        raise JournalV5Error("journal.overflow must be an exact boolean")
    lost_count = _builtin_int(journal["lost_count"], "journal.lost_count")
    if journal["overflow"] or lost_count != 0:
        raise JournalV5Error("overflowed or lossy journals are not structurally admissible")

    begins: dict[int, dict[str, Any]] = {}
    ends: dict[int, dict[str, Any]] = {}
    validated_events: list[dict[str, Any]] = []
    poll_exceptions = 0
    previous_mono = coverage_start
    for seq, raw_event in enumerate(journal["events"]):
        event = _validate_event(raw_event, expected_seq=seq, nonce=nonce)
        validated_events.append(event)
        mono = int(event["mono_ns_hex"], 16)
        if mono < coverage_start or mono > coverage_end:
            raise JournalV5Error("event monotonic time falls outside journal coverage")
        if mono < previous_mono:
            raise JournalV5Error("event monotonic times must be nondecreasing")
        previous_mono = mono
        if event["kind"] == "poll_begin":
            begins[seq] = event
        elif event["kind"] == "poll_end":
            begin_seq = event["poll_begin_id"]
            begin = begins.get(begin_seq)
            if begin is None or begin_seq in ends:
                raise JournalV5Error("poll_end must match one earlier, not-yet-ended poll_begin")
            if event["process_generation_id"] != begin["process_generation_id"]:
                raise JournalV5Error("poll_end process generation differs from its begin")
            ends[begin_seq] = event
            poll_exceptions += event["outcome"] == "exception"

    lifecycle = _observe_process_lifecycle(validated_events)
    query_cache = _observe_query_and_cache(validated_events, ends)
    return {
        "status": "untrusted_v5_journal_shape_consistent",
        "journal_raw_sha256": hashlib.sha256(raw).hexdigest(),
        "source_id_observed": source_id,
        "event_count": event_count,
        "poll_begin_count": len(begins),
        "poll_end_count": len(ends),
        "unterminated_poll_count": len(begins) - len(ends),
        "poll_exception_count": poll_exceptions,
        "all_polls_terminal": len(begins) == len(ends),
        "all_polls_returned": len(begins) == len(ends) and poll_exceptions == 0,
        **lifecycle,
        **query_cache,
        "gate_state": "open",
        "event_source_completeness_verified": False,
        "runtime_identity_verified": False,
        "process_lifecycle_verified": False,
        "query_causality_verified": False,
        "cache_replay_verified": False,
        "execution_semantics_verified": False,
        "qualification_adjudicated": False,
        "T1_numerical": False,
        "qualification_credit": 0,
    }
