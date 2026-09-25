"""Non-authorizing parser for the synthetic F8 R008 C journal V5.

This parser checks serialization, exact event field sets, primitive domains,
journal-local sequence/clock and process/thread state, guard links, and a
single-slot cache replay over caller-provided events. Its optional source-
callgraph inspector checks only declared structure and observed schedule
consistency; it does not reparse source or runtime configuration, establish
journal completeness/truth, recompute active windows/table provenance, attest
runtime identity, or authorize execution/qualification.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import struct
import subprocess
from pathlib import Path
from typing import Any


JOURNAL_SCHEMA = "core.cfd.f8.r008_c_execution_journal.synthetic.v5"
SOURCE_CALLGRAPH_SCHEMA = "core.cfd.f8.r008_c_execution_source_callgraph.synthetic.v5"
SOURCE_CALLGRAPH_OBJECT_ID = "f8-r008-source-callgraph-v5"
MAX_RAW_BYTES = 1_073_741_824
MAX_EVENT_COUNT = 100_000_000
MAX_SOURCE_FILE_BYTES = 1_048_576
MAX_SOURCE_TOTAL_BYTES = 2_097_152
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
_SOURCE_FUNCTIONS = {
    "main.dispatch": "source.main_cpp",
    "jsph.load_case_config": "source.jsph_cpp",
    "accinput.load_xml": "source.accinput_cpp",
    "accinput.read_xml": "source.accinput_cpp",
    "accinput.run_cpu": "source.accinput_cpp",
    "accinput.run_gpu": "source.accinput_cpp",
    "accinput.get_acc_values": "source.accinput_cpp",
    "accinput_mk.get_acc_values": "source.accinput_cpp",
    "cpu.pre_interaction_forces": "source.cpu_cpp",
    "gpu.pre_interaction_forces": "source.gpu_cpp",
    "cpu.compute_step_verlet": "source.cpu_single_cpp",
    "cpu.compute_step_symplectic": "source.cpu_single_cpp",
    "cpu.run_loop": "source.cpu_single_cpp",
    "gpu.compute_step_verlet": "source.gpu_single_cpp",
    "gpu.compute_step_symplectic": "source.gpu_single_cpp",
    "gpu.run_loop": "source.gpu_single_cpp",
    "vres.driver_loop": "source.vres_driver_h",
    "cpu_vres.compute_step": "source.cpu_vres_cpp",
    "gpu_vres.compute_step": "source.gpu_vres_cpp",
    "linear_value.get_value3d3d": "source.linear_value_cpp",
    "linear_value.find_time": "source.linear_value_cpp",
}
_SOURCE_FILES = {
    "source.main_cpp": "src/source/main.cpp",
    "source.jsph_cpp": "src/source/JSph.cpp",
    "source.accinput_cpp": "src/source/JDsAccInput.cpp",
    "source.cpu_cpp": "src/source/JSphCpu.cpp",
    "source.gpu_cpp": "src/source/JSphGpu.cpp",
    "source.cpu_single_cpp": "src/source/JSphCpuSingle.cpp",
    "source.gpu_single_cpp": "src/source/JSphGpuSingle.cpp",
    "source.vres_driver_h": "src/source/JSphVResDriver.h",
    "source.cpu_vres_cpp": "src/source/JSphCpuSingle_VRes.cpp",
    "source.gpu_vres_cpp": "src/source/JSphGpuSingle_VRes.cpp",
    "source.linear_value_cpp": "src/source/JLinearValue.cpp",
}
_SOURCE_FRAGMENT_KEYS = frozenset({
    "function_id", "source_file_object_id", "byte_start", "byte_end",
    "fragment_raw_sha256", "normalized_ast_sha256", "ordered_call_edges",
})
_CALL_EDGE_KEYS = frozenset({
    "ordinal", "callsite_id", "target_function_id", "active_preprocessor_condition",
})
_SOURCE_CALLGRAPH_TOP_KEYS = frozenset({
    "schema", "source_id", "source_binary_sha256", "source_tree_sha256",
    "build_provenance_ref", "runtime_image_ref", "source_fragments", "drivers", "instances",
})
_DRIVER_KEYS = frozenset({"driver_id", "loop_model", "solver_instance_ids"})
_INSTANCE_KEYS = frozenset({
    "solver_instance_id", "driver_id", "input_count", "callsite_id", "integrator", "intersteps",
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


def _parse_json(raw: bytes, *, label: str = "journal") -> dict[str, Any]:
    if type(raw) is not bytes:
        raise JournalV5Error(f"{label} must be exact bytes")
    if len(raw) > MAX_RAW_BYTES:
        raise JournalV5Error(f"{label} exceeds the V4-inherited raw byte limit")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise JournalV5Error(f"{label} is not strict UTF-8") from error
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
        raise JournalV5Error(f"{label} is not valid strict JSON") from error
    if type(value) is not dict:
        raise JournalV5Error(f"{label} top level must be an object")
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


def _inspect_untrusted_v5_journal(raw: bytes) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Internal inspector retaining validated events for combined replay."""
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
    result = {
        "status": "untrusted_v5_journal_shape_consistent",
        "journal_raw_sha256": hashlib.sha256(raw).hexdigest(),
        "source_id_observed": source_id,
        "source_binary_sha256_observed": journal["source_binary_sha256"],
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
    return result, validated_events


def inspect_untrusted_v5_journal(raw: bytes) -> dict[str, Any]:
    """Inspect journal bytes and return only a non-authorizing diagnostic."""
    result, _ = _inspect_untrusted_v5_journal(raw)
    return result


def _validate_callgraph_reference(value: Any, label: str, *, stage: str, role: str) -> dict[str, Any]:
    ref = _exact_object(value, _REFERENCE_KEYS, label)
    if ref["stage"] != stage or ref["role"] != role:
        raise JournalV5Error(f"{label} has an unexpected stage or role")
    _identifier(ref["object_id"], f"{label}.object_id")
    _builtin_int(ref["bytes"], f"{label}.bytes", minimum=1, maximum=MAX_RAW_BYTES)
    _hex(ref["sha256"], f"{label}.sha256", _SHA256)
    return ref


def inspect_untrusted_v5_source_callgraph(
    raw: bytes,
    *,
    source_callgraph_binding: Any = None,
    _include_topology: bool = False,
) -> dict[str, Any]:
    """Check declared V5 source-callgraph shape without trusting its claims.

    If supplied, ``source_callgraph_binding`` is checked against the raw bytes;
    this local hash comparison is not descriptor-root or evidence-payload trust.
    """
    graph = _parse_json(raw, label="source callgraph")
    graph = _exact_object(graph, _SOURCE_CALLGRAPH_TOP_KEYS, "source callgraph")
    if type(graph["schema"]) is not str or graph["schema"] != SOURCE_CALLGRAPH_SCHEMA:
        raise JournalV5Error("source callgraph schema mismatch")

    source_id = _identifier(graph["source_id"], "source_callgraph.source_id")
    binary_sha256 = _hex(graph["source_binary_sha256"], "source_callgraph.source_binary_sha256", _SHA256)
    _hex(graph["source_tree_sha256"], "source_callgraph.source_tree_sha256", _SHA256)
    build_ref = _validate_callgraph_reference(
        graph["build_provenance_ref"], "source_callgraph.build_provenance_ref",
        stage="build", role="build_attestation",
    )
    runtime_ref = _validate_callgraph_reference(
        graph["runtime_image_ref"], "source_callgraph.runtime_image_ref",
        stage="runtime", role="runtime_image",
    )
    if source_id != runtime_ref["object_id"] or binary_sha256 != runtime_ref["sha256"]:
        raise JournalV5Error("source callgraph identity copies disagree with runtime_image_ref")

    binding_hash_verified = False
    if source_callgraph_binding is not None:
        binding = _validate_callgraph_reference(
            source_callgraph_binding, "source_callgraph_binding",
            stage="build", role="source_callgraph",
        )
        if binding["object_id"] != SOURCE_CALLGRAPH_OBJECT_ID:
            raise JournalV5Error("source_callgraph_binding.object_id is not the frozen V5 object ID")
        if binding["bytes"] != len(raw) or binding["sha256"] != hashlib.sha256(raw).hexdigest():
            raise JournalV5Error("source callgraph raw bytes do not match the supplied descriptor ref")
        binding_hash_verified = True

    fragments = graph["source_fragments"]
    if type(fragments) is not list or not 1 <= len(fragments) <= len(_SOURCE_FUNCTIONS):
        raise JournalV5Error("source_fragments must be a nonempty bounded array")
    seen_functions: set[str] = set()
    call_edge_count = 0
    for index, fragment_value in enumerate(fragments):
        fragment = _exact_object(fragment_value, _SOURCE_FRAGMENT_KEYS, f"source_fragments[{index}]")
        function_id = fragment["function_id"]
        if type(function_id) is not str or function_id not in _SOURCE_FUNCTIONS:
            raise JournalV5Error(f"source_fragments[{index}].function_id is not allowlisted")
        if function_id in seen_functions:
            raise JournalV5Error("source fragment function IDs must be unique")
        seen_functions.add(function_id)
        if fragment["source_file_object_id"] != _SOURCE_FUNCTIONS[function_id]:
            raise JournalV5Error(f"source fragment {function_id} has the wrong source-file object ID")
        start = _builtin_int(fragment["byte_start"], f"source_fragments[{index}].byte_start", maximum=2**63 - 1)
        end = _builtin_int(fragment["byte_end"], f"source_fragments[{index}].byte_end", maximum=2**63 - 1)
        if end <= start:
            raise JournalV5Error("source fragment byte range must be nonempty and half-open")
        _hex(fragment["fragment_raw_sha256"], f"source_fragments[{index}].fragment_raw_sha256", _SHA256)
        _hex(fragment["normalized_ast_sha256"], f"source_fragments[{index}].normalized_ast_sha256", _SHA256)
        edges = fragment["ordered_call_edges"]
        if type(edges) is not list or len(edges) > MAX_EVENT_COUNT:
            raise JournalV5Error(f"source_fragments[{index}].ordered_call_edges must be a bounded array")
        seen_callsites: set[str] = set()
        for ordinal, edge_value in enumerate(edges):
            edge = _exact_object(edge_value, _CALL_EDGE_KEYS, f"source_fragments[{index}].ordered_call_edges[{ordinal}]")
            if _builtin_int(edge["ordinal"], "call edge ordinal") != ordinal:
                raise JournalV5Error("call-edge ordinals must be contiguous in declared source order")
            callsite_id = _identifier(edge["callsite_id"], "call edge callsite_id")
            if callsite_id in seen_callsites:
                raise JournalV5Error("callsite IDs must be unique within a source fragment")
            seen_callsites.add(callsite_id)
            target = edge["target_function_id"]
            if type(target) is not str or target not in _SOURCE_FUNCTIONS:
                raise JournalV5Error("call edge target_function_id is not allowlisted")
            if type(edge["active_preprocessor_condition"]) is not str or edge["active_preprocessor_condition"] != "active":
                raise JournalV5Error("call edge preprocessor condition must be the fixed active marker")
        call_edge_count += len(edges)

    drivers = graph["drivers"]
    if type(drivers) is not list or len(drivers) != 1:
        raise JournalV5Error("R008 source callgraph must declare exactly one driver")
    driver = _exact_object(drivers[0], _DRIVER_KEYS, "drivers[0]")
    driver_id = _identifier(driver["driver_id"], "drivers[0].driver_id")
    loop_model = driver["loop_model"]
    if type(loop_model) is not str or loop_model not in {"single_solver_loop", "vres_driver_loop"}:
        raise JournalV5Error("driver loop_model is not allowlisted")
    solver_ids = driver["solver_instance_ids"]
    if type(solver_ids) is not list or not 1 <= len(solver_ids) <= 65536:
        raise JournalV5Error("driver solver_instance_ids must be a nonempty bounded array")
    normalized_solver_ids = [_identifier(value, "driver solver_instance_id") for value in solver_ids]
    if len(set(normalized_solver_ids)) != len(normalized_solver_ids):
        raise JournalV5Error("driver solver_instance_ids must be unique")
    if loop_model == "single_solver_loop":
        if driver_id != "main" or normalized_solver_ids != ["main"]:
            raise JournalV5Error("single_solver_loop must map exactly the main driver and instance")
    else:
        expected_vres_ids = [f"vres.{index:02d}" for index in range(len(normalized_solver_ids))]
        if driver_id != "vres" or normalized_solver_ids != expected_vres_ids:
            raise JournalV5Error("VRes driver IDs must follow zero-based VResObj vector order")

    instances_value = graph["instances"]
    if type(instances_value) is not list or not 1 <= len(instances_value) <= 65536:
        raise JournalV5Error("instances must be a nonempty bounded array")
    instance_by_id: dict[str, dict[str, Any]] = {}
    instance_ids_in_order: list[str] = []
    input_entry_count = 0
    for index, instance_value in enumerate(instances_value):
        instance = _exact_object(instance_value, _INSTANCE_KEYS, f"instances[{index}]")
        instance_id = _identifier(instance["solver_instance_id"], f"instances[{index}].solver_instance_id")
        if instance_id in instance_by_id:
            raise JournalV5Error("solver_instance_ids must be unique")
        if instance["driver_id"] != driver_id:
            raise JournalV5Error("instance driver_id differs from the sole declared driver")
        input_count = _builtin_int(instance["input_count"], f"instances[{index}].input_count", maximum=65536)
        callsite_id = instance["callsite_id"]
        if type(callsite_id) is not str or callsite_id not in _CALLSITES:
            raise JournalV5Error("instance callsite_id is not allowlisted")
        integrator = instance["integrator"]
        if type(integrator) is not str or integrator not in _INTEGRATORS:
            raise JournalV5Error("instance integrator is not allowlisted")
        intersteps = instance["intersteps"]
        if type(intersteps) is not list or any(type(step) is not str for step in intersteps):
            raise JournalV5Error("instance intersteps must be a string array")
        expected_intersteps = (
            ["INTERSTEP_Verlet"] if integrator == "Verlet"
            else ["INTERSTEP_SymPredictor", "INTERSTEP_SymCorrector"]
        )
        if intersteps != expected_intersteps:
            raise JournalV5Error("instance intersteps do not match its integrator")
        if loop_model == "vres_driver_loop" and integrator != "VRes":
            raise JournalV5Error("all instances in a VRes driver must use the VRes integrator")
        if loop_model == "single_solver_loop" and integrator == "VRes":
            raise JournalV5Error("a single_solver_loop cannot declare the VRes integrator")
        instance_by_id[instance_id] = instance
        instance_ids_in_order.append(instance_id)
        input_entry_count += input_count
    if instance_ids_in_order != sorted(instance_ids_in_order):
        raise JournalV5Error("instances must be sorted by solver_instance_id")
    if set(instance_ids_in_order) != set(normalized_solver_ids):
        raise JournalV5Error("driver and instance IDs must form an exact partition")

    result = {
        "status": "untrusted_v5_source_callgraph_declared_shape_consistent",
        "source_callgraph_raw_sha256": hashlib.sha256(raw).hexdigest(),
        "source_callgraph_binding_raw_hash_verified": binding_hash_verified,
        "source_id_observed": source_id,
        "source_binary_sha256_observed": binary_sha256,
        "source_fragment_count": len(fragments),
        "source_call_edge_count_declared": call_edge_count,
        "source_fragment_ids_allowlisted": True,
        "source_callgraph_complete_declaration_verified": False,
        "source_fragment_feature_coverage_verified": False,
        "source_fragments_reparsed_from_source": False,
        "driver_count_declared": len(drivers),
        "driver_id_declared": driver_id,
        "loop_model_declared": loop_model,
        "solver_instance_ids_in_driver_order": normalized_solver_ids,
        "instance_count_declared": len(instance_by_id),
        "input_entry_count_declared": input_entry_count,
        "instances_in_solver_id_order": [instance_by_id[key] for key in instance_ids_in_order],
        "_driver_records": [driver],
        "_instances_by_id": instance_by_id,
        "_source_fragments": fragments,
    }
    if not _include_topology:
        result.pop("_driver_records")
        result.pop("_instances_by_id")
        result.pop("_source_fragments")
    return result


def _controlled_git_environment() -> dict[str, str]:
    """Isolate reads from inherited config, replacement refs, and lazy fetches."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update({
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_NO_LAZY_FETCH": "1",
    })
    return env


def _git_read(
    root: Path | int,
    args: list[str],
    label: str,
    *,
    env: dict[str, str] | None = None,
) -> bytes:
    if isinstance(root, int):
        cwd: str | Path = f"/proc/self/fd/{root}"
        pass_fds = (root,)
    else:
        cwd = root
        pass_fds = ()
    try:
        completed = subprocess.run(
            [
                "git", "--no-pager", "--no-optional-locks",
                "--no-replace-objects",
                "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null",
                *args,
            ],
            cwd=cwd, pass_fds=pass_fds,
            env=env if env is not None else _controlled_git_environment(),
            stdin=subprocess.DEVNULL, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise JournalV5Error(f"cannot inspect pinned Git source snapshot: {label}") from error
    return completed.stdout


def _worktree_source_matches_blob(repository_fd: int, relative_path: str, expected_bytes: bytes) -> None:
    """Compare a no-follow worktree read with one already bounded Git blob."""
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if not nofollow or not getattr(os, "O_DIRECTORY", 0):
        raise JournalV5Error("platform lacks no-follow directory-FD source inspection")
    source_root_fd: int | None = None
    parent_fd: int | None = None
    file_fd: int | None = None
    try:
        source_root_fd = os.dup(repository_fd)
        if not stat.S_ISDIR(os.fstat(source_root_fd).st_mode):
            raise JournalV5Error("pinned repository descriptor is not a directory")
        parent_fd = source_root_fd
        parts = relative_path.split("/")
        for part in parts[:-1]:
            child_fd = os.open(part, directory_flags | nofollow, dir_fd=parent_fd)
            if parent_fd != source_root_fd:
                os.close(parent_fd)
            parent_fd = child_fd
        file_fd = os.open(
            parts[-1], os.O_RDONLY | os.O_CLOEXEC | nofollow, dir_fd=parent_fd,
        )
        before = os.fstat(file_fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_size != len(expected_bytes)
            or before.st_size > MAX_SOURCE_FILE_BYTES
        ):
            raise JournalV5Error("allowlisted worktree source is not the bounded Git blob size")
        offset = 0
        bytes_match = True
        while offset < len(expected_bytes):
            chunk = os.read(file_fd, min(65_536, len(expected_bytes) - offset))
            if not chunk:
                break
            if chunk != memoryview(expected_bytes)[offset:offset + len(chunk)]:
                bytes_match = False
            offset += len(chunk)
        trailing = os.read(file_fd, 1)
        after = os.fstat(file_fd)
        stable_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
        stable_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
        if offset != len(expected_bytes) or trailing or stable_before != stable_after:
            raise JournalV5Error("allowlisted worktree source changed during snapshot read")
        if not bytes_match:
            raise JournalV5Error(f"worktree source bytes differ from pinned Git blob: {relative_path}")
    except OSError as error:
        raise JournalV5Error(f"cannot safely read allowlisted source path: {relative_path}") from error
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if parent_fd is not None and parent_fd != source_root_fd:
            os.close(parent_fd)
        if source_root_fd is not None:
            os.close(source_root_fd)


def _open_repository_root(root: Path) -> tuple[int, tuple[int, int]]:
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if not nofollow or not getattr(os, "O_DIRECTORY", 0):
        raise JournalV5Error("platform lacks no-follow directory-FD repository inspection")
    repository_fd: int | None = None
    try:
        repository_fd = os.open(root, directory_flags | nofollow)
        opened = os.fstat(repository_fd)
        named = os.stat(root, follow_symlinks=False)
    except OSError as error:
        if repository_fd is not None:
            os.close(repository_fd)
        raise JournalV5Error("cannot pin repository root directory") from error
    assert repository_fd is not None
    identity = (opened.st_dev, opened.st_ino)
    if (
        not stat.S_ISDIR(opened.st_mode)
        or not stat.S_ISDIR(named.st_mode)
        or identity != (named.st_dev, named.st_ino)
    ):
        os.close(repository_fd)
        raise JournalV5Error("repository root path changed while pinning its directory")
    return repository_fd, identity


def _verify_repository_root_identity(
    root: Path,
    repository_fd: int,
    expected_identity: tuple[int, int],
) -> None:
    try:
        opened = os.fstat(repository_fd)
        named = os.stat(root, follow_symlinks=False)
    except OSError as error:
        raise JournalV5Error("repository root path changed during source inspection") from error
    if (
        not stat.S_ISDIR(opened.st_mode)
        or not stat.S_ISDIR(named.st_mode)
        or (opened.st_dev, opened.st_ino) != expected_identity
        or (named.st_dev, named.st_ino) != expected_identity
    ):
        raise JournalV5Error("repository root path changed during source inspection")


def inspect_untrusted_v5_source_callgraph_against_git_head(
    raw: bytes,
    repository_root: str | Path,
    *,
    source_callgraph_binding: Any = None,
) -> dict[str, Any]:
    """Compare declared fragment raw hashes with bounded blobs at one Git HEAD.

    This verifies byte-slice equality only. It does not prove that offsets span
    the named C++ function, recompute AST/call edges, or bind HEAD to a build.
    Referenced worktree files must match the pinned blobs; the index need not be clean.
    """
    graph_result = inspect_untrusted_v5_source_callgraph(
        raw, source_callgraph_binding=source_callgraph_binding, _include_topology=True,
    )
    try:
        root = Path(repository_root).resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise JournalV5Error("repository_root is not an existing directory") from error
    if not root.is_dir():
        raise JournalV5Error("repository_root is not a directory")
    repository_fd, root_identity = _open_repository_root(root)
    try:
        return _inspect_untrusted_v5_source_callgraph_at_root_fd(
            graph_result, root, repository_fd, root_identity,
        )
    finally:
        os.close(repository_fd)


def _inspect_untrusted_v5_source_callgraph_at_root_fd(
    graph_result: dict[str, Any],
    root: Path,
    repository_fd: int,
    root_identity: tuple[int, int],
) -> dict[str, Any]:
    git_env = _controlled_git_environment()
    top = _git_read(
        repository_fd, ["rev-parse", "--show-toplevel"], "repository root", env=git_env,
    )
    try:
        git_root = Path(top.decode("utf-8", errors="strict").strip()).resolve(strict=True)
    except (UnicodeDecodeError, OSError, RuntimeError) as error:
        raise JournalV5Error("Git reported an invalid repository root") from error
    if git_root != root:
        raise JournalV5Error("repository_root must be the exact Git worktree root")
    _verify_repository_root_identity(root, repository_fd, root_identity)

    fragments = graph_result["_source_fragments"]
    fragments_by_object_id: dict[str, list[dict[str, Any]]] = {}
    for fragment in fragments:
        fragments_by_object_id.setdefault(fragment["source_file_object_id"], []).append(fragment)
    used_object_ids = sorted(fragments_by_object_id)

    head_raw = _git_read(
        repository_fd, ["rev-parse", "--verify", "HEAD^{commit}"], "HEAD commit", env=git_env,
    )
    try:
        head_commit = head_raw.decode("ascii", errors="strict").strip()
    except UnicodeDecodeError as error:
        raise JournalV5Error("Git HEAD commit ID is not ASCII") from error
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", head_commit):
        raise JournalV5Error("Git HEAD commit ID has an unsupported object format")

    blob_metadata: list[tuple[str, str, str, int]] = []
    total_source_size = 0
    for object_id in used_object_ids:
        path = _SOURCE_FILES[object_id]
        tree_entry = _git_read(
            repository_fd, ["ls-tree", head_commit, "--", path],
            f"tracked source {path}", env=git_env,
        )
        lines = tree_entry.splitlines()
        if len(lines) != 1 or b"\t" not in lines[0]:
            raise JournalV5Error(f"allowlisted source is not a unique Git HEAD entry: {path}")
        metadata, listed_path = lines[0].split(b"\t", 1)
        try:
            mode, object_type, blob_oid = metadata.decode("ascii", errors="strict").split(" ")
            listed_path_text = listed_path.decode("utf-8", errors="strict")
        except (UnicodeDecodeError, ValueError) as error:
            raise JournalV5Error(f"Git tree entry is malformed: {path}") from error
        if (
            mode not in {"100644", "100755"} or object_type != "blob"
            or listed_path_text != path
            or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", blob_oid)
            or len(blob_oid) != len(head_commit)
        ):
            raise JournalV5Error(f"allowlisted source is not a regular tracked file: {path}")
        size_raw = _git_read(
            repository_fd, ["cat-file", "-s", blob_oid], f"source size {path}", env=git_env,
        )
        try:
            source_size = int(size_raw.decode("ascii", errors="strict").strip())
        except (UnicodeDecodeError, ValueError) as error:
            raise JournalV5Error(f"Git source size is malformed: {path}") from error
        if not 0 <= source_size <= MAX_SOURCE_FILE_BYTES:
            raise JournalV5Error(f"allowlisted source exceeds the per-file inspection cap: {path}")
        total_source_size += source_size
        if total_source_size > MAX_SOURCE_TOTAL_BYTES:
            raise JournalV5Error("allowlisted sources exceed the aggregate inspection cap")
        blob_metadata.append((object_id, path, blob_oid, source_size))

    source_blobs: list[dict[str, Any]] = []
    mismatched_function_ids: list[str] = []
    for object_id, path, blob_oid, source_size in blob_metadata:
        source_bytes = _git_read(
            repository_fd, ["cat-file", "blob", blob_oid],
            f"source blob {path}", env=git_env,
        )
        if len(source_bytes) != source_size:
            raise JournalV5Error(f"Git source blob length changed while reading: {path}")
        object_hash = hashlib.new("sha1" if len(blob_oid) == 40 else "sha256")
        object_hash.update(b"blob " + str(source_size).encode("ascii") + b"\0")
        object_hash.update(source_bytes)
        if object_hash.hexdigest() != blob_oid:
            raise JournalV5Error(f"Git blob object ID does not match its bytes: {path}")
        _worktree_source_matches_blob(repository_fd, path, source_bytes)
        source_blobs.append({
            "source_file_object_id": object_id,
            "path": path,
            "git_blob_oid": blob_oid,
            "bytes": source_size,
            "raw_sha256": hashlib.sha256(source_bytes).hexdigest(),
        })
        for fragment in fragments_by_object_id[object_id]:
            start = fragment["byte_start"]
            end = fragment["byte_end"]
            if end > len(source_bytes):
                mismatched_function_ids.append(fragment["function_id"])
                continue
            actual_sha256 = hashlib.sha256(memoryview(source_bytes)[start:end]).hexdigest()
            if actual_sha256 != fragment["fragment_raw_sha256"]:
                mismatched_function_ids.append(fragment["function_id"])

    final_head_raw = _git_read(
        repository_fd, ["rev-parse", "--verify", "HEAD^{commit}"],
        "final HEAD commit", env=git_env,
    )
    try:
        final_head_commit = final_head_raw.decode("ascii", errors="strict").strip()
    except UnicodeDecodeError as error:
        raise JournalV5Error("Git final HEAD commit ID is not ASCII") from error
    if final_head_commit != head_commit:
        raise JournalV5Error("Git HEAD moved during source inspection")
    _verify_repository_root_identity(root, repository_fd, root_identity)

    raw_hashes_match = not mismatched_function_ids
    return {
        "status": (
            "untrusted_v5_source_fragment_bytes_match_git_head_snapshot"
            if raw_hashes_match else "untrusted_v5_source_fragment_bytes_mismatch"
        ),
        "source_callgraph_raw_sha256": graph_result["source_callgraph_raw_sha256"],
        "source_callgraph_binding_raw_hash_verified": graph_result["source_callgraph_binding_raw_hash_verified"],
        "git_head_commit_observed": head_commit,
        "source_blobs_observed": source_blobs,
        "source_fragment_count": graph_result["source_fragment_count"],
        "git_head_commit_at_start_and_end_matched": True,
        "source_fragment_raw_hashes_match_git_head_snapshot": raw_hashes_match,
        "source_fragment_mismatch_function_ids": mismatched_function_ids,
        "source_function_definition_ranges_verified": False,
        "source_fragments_reparsed_from_source": False,
        "source_tree_sha256_matched_build_attestation": False,
        "source_callgraph_verified": False,
        "gate_state": "open",
        "qualification_credit": 0,
    }


def inspect_untrusted_v5_journal_with_source_callgraph(
    journal_raw: bytes,
    source_callgraph_raw: bytes,
    *,
    source_callgraph_binding: Any = None,
) -> dict[str, Any]:
    """Replay declared host-call × entry schedules against observed true guards.

    A complete match is only consistency among caller-provided bytes. It cannot
    prove source/configuration closure, event-source completeness, or execution.
    """
    journal_result, events = _inspect_untrusted_v5_journal(journal_raw)
    graph_result = inspect_untrusted_v5_source_callgraph(
        source_callgraph_raw, source_callgraph_binding=source_callgraph_binding,
        _include_topology=True,
    )
    driver = graph_result["_driver_records"][0]
    instances = graph_result["_instances_by_id"]
    expected_driver_ids = {driver["driver_id"]}
    observed_driver_ids: set[str] = set()
    guards: dict[int, dict[str, Any]] = {}
    polls_by_guard: dict[int, list[dict[str, Any]]] = {}
    for event in events:
        if event["kind"] == "loop_guard":
            guards[event["seq"]] = event
            observed_driver_ids.add(event["driver_id"])
        elif event["kind"] == "poll_begin":
            polls_by_guard.setdefault(event["guard_seq"], []).append(event)

    schedule_mismatch_guard_count = 0
    schedule_content_mismatch_count = 0
    expected_poll_count = 0
    for guard_seq, guard in guards.items():
        actual = polls_by_guard.get(guard_seq, [])
        if not guard["condition_result"]:
            if actual:
                schedule_mismatch_guard_count += 1
                schedule_content_mismatch_count += len(actual)
            continue
        if guard["driver_id"] != driver["driver_id"]:
            schedule_mismatch_guard_count += 1
            schedule_content_mismatch_count += len(actual)
            continue
        expected_count = sum(
            instances[instance_id]["input_count"] * len(instances[instance_id]["intersteps"])
            for instance_id in driver["solver_instance_ids"]
        )
        expected_poll_count += expected_count
        if len(actual) != expected_count:
            schedule_mismatch_guard_count += 1
            schedule_content_mismatch_count += abs(len(actual) - expected_count)
            continue

        actual_index = 0
        guard_matches = True
        for instance_id in driver["solver_instance_ids"]:
            instance = instances[instance_id]
            for interstep in instance["intersteps"]:
                for input_index in range(instance["input_count"]):
                    poll = actual[actual_index]
                    expected_fields = (
                        instance_id,
                        driver["driver_id"],
                        instance["callsite_id"],
                        instance["integrator"],
                        interstep,
                        input_index,
                    )
                    observed_fields = (
                        poll["solver_instance_id"],
                        poll["driver_id"],
                        poll["callsite_id"],
                        poll["integrator"],
                        poll["interstep"],
                        poll["input_entry_index"],
                    )
                    if observed_fields != expected_fields:
                        guard_matches = False
                        schedule_content_mismatch_count += 1
                    actual_index += 1
        if not guard_matches:
            schedule_mismatch_guard_count += 1

    driver_ids_match = observed_driver_ids == expected_driver_ids
    identity_copy_matches = (
        journal_result["source_id_observed"] == graph_result["source_id_observed"]
        and journal_result["source_binary_sha256_observed"] == graph_result["source_binary_sha256_observed"]
    )
    schedule_matches = schedule_mismatch_guard_count == 0 and driver_ids_match
    return {
        **journal_result,
        "source_callgraph_shape_status": graph_result["status"],
        "source_callgraph_raw_sha256": graph_result["source_callgraph_raw_sha256"],
        "source_callgraph_binding_raw_hash_verified": graph_result["source_callgraph_binding_raw_hash_verified"],
        "source_callgraph_identity_copies_match_journal": identity_copy_matches,
        "source_callgraph_verified": False,
        "source_callgraph_complete_declaration_verified": False,
        "source_fragment_feature_coverage_verified": False,
        "source_fragments_reparsed_from_source": False,
        "source_callgraph_fragment_count_declared": graph_result["source_fragment_count"],
        "source_callgraph_edge_count_declared": graph_result["source_call_edge_count_declared"],
        "source_callgraph_instance_count_declared": graph_result["instance_count_declared"],
        "source_callgraph_entry_count_declared": graph_result["input_entry_count_declared"],
        "observed_driver_ids": sorted(observed_driver_ids),
        "callgraph_driver_id_set_matches_observed": driver_ids_match,
        "observed_guard_count": len(guards),
        "observed_true_guard_count": sum(guard["condition_result"] for guard in guards.values()),
        "observed_false_guard_count": sum(not guard["condition_result"] for guard in guards.values()),
        "expected_poll_count_for_observed_true_guards": expected_poll_count,
        "poll_schedule_mismatch_guard_count": schedule_mismatch_guard_count,
        "poll_schedule_content_mismatch_count": schedule_content_mismatch_count,
        "expected_poll_schedule_matches_observed": schedule_matches,
        "expected_query_completeness_verified": False,
        "combined_untrusted_consistency": (
            schedule_matches
            and identity_copy_matches
            and graph_result["source_callgraph_binding_raw_hash_verified"]
            and journal_result["all_polls_returned"]
            and journal_result["observed_driver_loops_complete"]
            and journal_result["cache_transitions_observed_consistent"]
            and journal_result["cache_replay_diagnostic_state"] == "journal_local_consistent_unverified"
            and journal_result["observed_process_lifecycle_complete"]
        ),
        "gate_state": "open",
        "execution_semantics_verified": False,
        "qualification_credit": 0,
    }
