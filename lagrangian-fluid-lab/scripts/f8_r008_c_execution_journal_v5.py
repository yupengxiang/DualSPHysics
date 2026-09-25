"""Non-authorizing structural parser for the synthetic F8 R008 C journal V5.

This parser checks serialization, exact event field sets, primitive domains,
and journal-local sequence/clock consistency. It does not establish that the
journal is complete or truthful, validate process/query causality or cache
replay, attest runtime identity, or authorize execution/qualification.
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
    elif kind == "poll_end":
        _builtin_int(event["poll_begin_id"], "poll_end.poll_begin_id")
        if event["poll_begin_id"] >= expected_seq:
            raise JournalV5Error("poll_end must follow its poll_begin")
        _generation(event["process_generation_id"], "poll_end.process_generation_id")
        if type(event["outcome"]) is not str or event["outcome"] not in {"returned", "exception"}:
            raise JournalV5Error("poll_end.outcome is outside the frozen enum")
    return event


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
    poll_exceptions = 0
    previous_mono = coverage_start
    for seq, raw_event in enumerate(journal["events"]):
        event = _validate_event(raw_event, expected_seq=seq, nonce=nonce)
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
