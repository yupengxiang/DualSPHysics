"""Bounded synthetic RunPARTs/RealStr/OutputTime cadence diagnostic.

This module deliberately accepts a UTF-8 ``RunPARTs.csv`` payload rather than
opening a production path.  It keeps every CSV token, including the native
``RealStr(TimeStep)`` token, and evaluates the stateful ``JDsOutputTime``
recurrence with Python binary64 values.  The result is structural evidence for
synthetic fixtures only.  It is never source-, runtime-, native-integrity-, or
T1-authenticated evidence and can never grant gate credit.

The only supported OutputTime input forms are::

    {"mode": "simple", "time_part_token": "0.1"}
    {
        "mode": "special",
        "segments": [
            {"time_token": "0", "timeout_token": "0.1"},
            {"time_token": "0.5", "timeout_token": "0.2"},
        ],
    }

The ``*_token`` fields are retained verbatim.  ``time``/``timeout`` and
``time_part`` aliases are accepted for fixture ergonomics, but are copied into
the canonical token fields without formatting or re-serialization.
"""
from __future__ import annotations

import csv
import hashlib
import io
import math
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from scripts import f8_r008_runparts_timestep_diagnostic_v2 as runparts_v2


SCHEMA = "core.cfd.f8.r008_runparts_realstr_cadence_diagnostic.v1"
INPUT_SCOPE = "synthetic_bytes_only_no_production_path_io"

# These caps bound decoding, retained raw tokens, state transitions, and the
# intentionally literal OutputTime loops.  They are diagnostic limits, not a
# statement about arbitrary native solver outputs.
MAX_RUNPARTS_BYTES = 8 * 1024 * 1024
MAX_RUNPARTS_ROWS = 20_000
MAX_OUTPUTTIME_SEGMENTS = 64
MAX_OUTPUTTIME_CANDIDATES_PER_CALL = 4_096
MAX_SIMPLE_TOUT_NUM = 4_096
UINT32_MAX = (1 << 32) - 1

RUNPARTS_HEADER = runparts_v2.RUNPARTS_HEADER
RUNPARTS_FOOTER = runparts_v2.RUNPARTS_FOOTER
INTEGER_COLUMNS = runparts_v2.INTEGER_COLUMNS
FLOAT_COLUMNS = runparts_v2.FLOAT_COLUMNS
INTEGER_CELL = runparts_v2.INTEGER_CELL
RUNPARTS_FLOAT_CELL = runparts_v2.FLOAT_CELL
SIGNED_FLOAT_CELL = re.compile(
    r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z",
    re.ASCII,
)

TIME_STEP_COLUMN = RUNPARTS_HEADER.index("TimeStep [s]")
PART_COLUMN = RUNPARTS_HEADER.index("Part")
STEPS_COLUMN = RUNPARTS_HEADER.index("Steps")
DT_MIN_COLUMN = RUNPARTS_HEADER.index("DtMin [s]")
DT_MAX_COLUMN = RUNPARTS_HEADER.index("DtMax [s]")


class CadenceDiagnosticError(ValueError):
    """Input is outside the bounded synthetic diagnostic contract."""

    def __init__(self, message: str, code: str = "CADENCE_INPUT_REJECTED") -> None:
        super().__init__(message)
        self.code = code


def _require(condition: bool, message: str, code: str = "CADENCE_INPUT_REJECTED") -> None:
    if not condition:
        raise CadenceDiagnosticError(message, code)


def _raw_token(value: Any, label: str) -> str:
    _require(isinstance(value, str), f"{label} must be supplied as an unmodified string token")
    _require(bool(value) and value == value.strip(), f"{label} must be nonempty and unpadded")
    return value


def _parse_unsigned_integer(token: str, label: str) -> int:
    _require(bool(INTEGER_CELL.fullmatch(token)), f"{label} is not a canonical nonnegative integer")
    return int(token.replace(",", ""))


def _parse_runparts_float(token: str, label: str) -> float:
    _require(bool(RUNPARTS_FLOAT_CELL.fullmatch(token)),
             f"{label} is not a supported nonnegative decimal token")
    value = float(token)
    _require(math.isfinite(value), f"{label} is not finite")
    return value


def _parse_time_token(token: Any, label: str, *, positive: bool = False) -> tuple[str, float]:
    raw = _raw_token(token, label)
    _require(bool(SIGNED_FLOAT_CELL.fullmatch(raw)),
             f"{label} is not a finite decimal token (NaN/Inf are rejected)",
             "NONFINITE_TIME_TOKEN")
    value = float(raw)
    _require(math.isfinite(value), f"{label} is not finite", "NONFINITE_TIME_TOKEN")
    _require(value >= 0.0, f"{label} must be nonnegative", "NEGATIVE_TIME_TOKEN")
    if positive:
        _require(value > 0.0, f"{label} must be greater than zero", "NONPOSITIVE_TIMEOUT")
    return raw, value


def _binary64(value: float) -> dict[str, Any]:
    """Expose the exact Python/C++-double value without changing its token."""
    return {"value": value, "hex": value.hex()}


def parse_raw_runparts_csv(payload: bytes) -> dict[str, Any]:
    """Parse a bounded native-shaped CSV while retaining every raw token.

    This is intentionally stricter than a generic CSV reader.  It accepts the
    fresh Part-0/time-0 segment used by this diagnostic and rejects duplicate,
    non-increasing, appended, NaN, or nonfinite records.
    """
    _require(isinstance(payload, bytes), "RunPARTs payload must be bytes")
    _require(0 < len(payload) <= MAX_RUNPARTS_BYTES,
             "RunPARTs payload is empty or exceeds the fixed byte limit",
             "RUNPARTS_BOUNDS_REJECTED")
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise CadenceDiagnosticError("RunPARTs payload is not strict UTF-8",
                                     "RUNPARTS_ENCODING_REJECTED") from error
    _require(not text.startswith("\ufeff"), "RunPARTs payload must not contain a UTF-8 BOM",
             "RUNPARTS_ENCODING_REJECTED")
    _require(payload.endswith(b"\n") and b"\r" not in payload and b'"' not in payload,
             "RunPARTs payload must use the native unquoted LF format",
             "RUNPARTS_SHAPE_REJECTED")

    raw_rows: list[dict[str, Any]] = []
    footer_rows: list[list[str]] = []
    in_footer = False
    previous_part = -1
    previous_time = -math.inf
    maximum_dtmax = 0.0

    try:
        rows = csv.reader(io.StringIO(text, newline=""), delimiter=";", strict=True)
        header = next(rows, None)
        _require(header == list(RUNPARTS_HEADER),
                 "RunPARTs header is not the exact 26-column native schema",
                 "RUNPARTS_HEADER_REJECTED")
        for row in rows:
            if not in_footer:
                if row == []:
                    _require(bool(raw_rows), "RunPARTs footer appeared before data rows",
                             "RUNPARTS_FOOTER_REJECTED")
                    in_footer = True
                    continue
                _require(row and not row[0].startswith("#"),
                         "RunPARTs footer must follow one blank line",
                         "RUNPARTS_FOOTER_REJECTED")
                _require(len(row) == len(RUNPARTS_HEADER),
                         "RunPARTs data row has an unexpected field count",
                         "RUNPARTS_ROW_REJECTED")
                _require(len(raw_rows) < MAX_RUNPARTS_ROWS,
                         "RunPARTs payload exceeds the fixed data-row limit",
                         "RUNPARTS_BOUNDS_REJECTED")
                _require(all(cell and cell == cell.strip() for cell in row),
                         "RunPARTs data cells must be nonempty and unpadded",
                         "RUNPARTS_ROW_REJECTED")

                part = _parse_unsigned_integer(row[PART_COLUMN], "RunPARTs Part")
                time_token = row[TIME_STEP_COLUMN]
                _, time_value = _parse_time_token(
                    time_token, "RunPARTs TimeStep [s]"
                )
                steps = _parse_unsigned_integer(row[STEPS_COLUMN], "RunPARTs Steps")
                dt_min = _parse_runparts_float(row[DT_MIN_COLUMN], "RunPARTs DtMin [s]")
                dt_max = _parse_runparts_float(row[DT_MAX_COLUMN], "RunPARTs DtMax [s]")
                for index in INTEGER_COLUMNS:
                    _parse_unsigned_integer(row[index], RUNPARTS_HEADER[index])
                for index in FLOAT_COLUMNS:
                    if index != TIME_STEP_COLUMN:
                        _parse_runparts_float(row[index], RUNPARTS_HEADER[index])

                if not raw_rows:
                    _require(part == 0 and time_value == 0.0 and steps == 0
                             and dt_min == 0.0 and dt_max == 0.0,
                             "fresh synthetic RunPARTs input must begin at Part 0/time 0",
                             "FRESH_SEGMENT_REJECTED")
                else:
                    _require(part == previous_part + 1,
                             "RunPARTs Part sequence is duplicate, gapped, or cross-attempt appended",
                             "PART_SEQUENCE_REJECTED")
                    _require(time_value > previous_time,
                             "RunPARTs TimeStep sequence is duplicate or non-increasing",
                             "TIME_SEQUENCE_REJECTED")
                    _require(steps > 0 and dt_min > 0.0 and dt_max > 0.0 and dt_min <= dt_max,
                             "noninitial RunPARTs row has invalid steps or DtMin/DtMax",
                             "RUNPARTS_ROW_REJECTED")
                    maximum_dtmax = max(maximum_dtmax, dt_max)

                # ``tokens`` is deliberately a list of the exact CSV cells;
                # do not replace the RealStr token with repr(float(token)).
                raw_rows.append({
                    "row_index": len(raw_rows),
                    "tokens": list(row),
                    "part_token": row[PART_COLUMN],
                    "part": part,
                    "time_step_token": time_token,
                    "realstr_time_step_token": time_token,
                    "time_step_binary64": _binary64(time_value),
                    "steps_token": row[STEPS_COLUMN],
                    "steps": steps,
                    "dt_min_token": row[DT_MIN_COLUMN],
                    "dt_max_token": row[DT_MAX_COLUMN],
                })
                previous_part = part
                previous_time = time_value
                continue

            _require(len(footer_rows) < len(RUNPARTS_HEADER),
                     "RunPARTs has extra rows after its native footer",
                     "RUNPARTS_FOOTER_REJECTED")
            expected = RUNPARTS_FOOTER[len(footer_rows)]
            _require(row == [expected],
                     "RunPARTs footer is incomplete, reordered, or malformed",
                     "RUNPARTS_FOOTER_REJECTED")
            footer_rows.append(row)
    except csv.Error as error:
        raise CadenceDiagnosticError("RunPARTs payload has malformed delimited text",
                                     "RUNPARTS_CSV_REJECTED") from error

    _require(in_footer and len(footer_rows) == len(RUNPARTS_HEADER),
             "RunPARTs payload lacks the exact final native footer",
             "RUNPARTS_FOOTER_REJECTED")
    _require(len(raw_rows) >= 2 and maximum_dtmax > 0.0,
             "RunPARTs payload needs an initial row and at least one advancing row",
             "RUNPARTS_ROW_REJECTED")
    return {
        "raw_rows": raw_rows,
        "data_row_count": len(raw_rows),
        "first_part": raw_rows[0]["part"],
        "last_part": raw_rows[-1]["part"],
        "last_recorded_time_s": raw_rows[-1]["time_step_binary64"]["value"],
        "last_recorded_time_token": raw_rows[-1]["time_step_token"],
        "footer_present": True,
        "maximum_recorded_part_dtmax_s": maximum_dtmax,
        "raw_payload_sha256": hashlib.sha256(payload).hexdigest(),
        "raw_payload_bytes": len(payload),
        "realstr_time_step_tokens_preserved": True,
    }


def _mapping_token(mapping: Mapping[str, Any], *names: str, label: str) -> str:
    for name in names:
        if name in mapping:
            return _raw_token(mapping[name], label)
    raise CadenceDiagnosticError(
        f"{label} is missing (accepted keys: {', '.join(names)})",
        "OUTPUTTIME_CONFIG_REJECTED",
    )


def _parse_output_time_config(config: Mapping[str, Any]) -> dict[str, Any]:
    _require(isinstance(config, Mapping), "OutputTime configuration must be a mapping",
             "OUTPUTTIME_CONFIG_REJECTED")
    mode = config.get("mode")
    _require(isinstance(mode, str) and mode in {"simple", "special"},
             "OutputTime mode must be exactly simple or special",
             "OUTPUTTIME_CONFIG_REJECTED")
    if mode == "simple":
        token = _mapping_token(config, "time_part_token", "time_part", label="time_part")
        raw, value = _parse_time_token(token, "OutputTime time_part", positive=True)
        return {
            "mode": "simple",
            "time_part_token": raw,
            "time_part_binary64": _binary64(value),
        }

    segments = config.get("segments")
    _require(isinstance(segments, (list, tuple)) and 0 < len(segments) <= MAX_OUTPUTTIME_SEGMENTS,
             "special OutputTime segments are empty or exceed the fixed limit",
             "OUTPUTTIME_BOUNDS_REJECTED")
    parsed_segments: list[dict[str, Any]] = []
    previous_time = -math.inf
    for index, segment in enumerate(segments):
        _require(isinstance(segment, Mapping),
                 f"OutputTime segment {index} must be a mapping",
                 "OUTPUTTIME_CONFIG_REJECTED")
        time_token = _mapping_token(segment, "time_token", "time",
                                    label=f"OutputTime segment {index} time")
        timeout_token = _mapping_token(segment, "timeout_token", "timeout",
                                       label=f"OutputTime segment {index} timeout")
        time_raw, time_value = _parse_time_token(time_token,
                                                  f"OutputTime segment {index} time")
        timeout_raw, timeout_value = _parse_time_token(timeout_token,
                                                       f"OutputTime segment {index} timeout",
                                                       positive=True)
        _require(time_value > previous_time,
                 "special OutputTime segment times must be strictly increasing",
                 "OUTPUTTIME_NONINCREASING_REJECTED")
        previous_time = time_value
        parsed_segments.append({
            "time_token": time_raw,
            "timeout_token": timeout_raw,
            "time_binary64": _binary64(time_value),
            "timeout_binary64": _binary64(timeout_value),
        })
    return {"mode": "special", "segments": parsed_segments}


@dataclass
class _OutputTimeState:
    """Literal bounded state corresponding to JDsOutputTime's mutable fields."""

    config: dict[str, Any]
    last_time_input: float | None = None
    last_time_output: float = -1.0
    simple_tout_num: int = 0
    time_base: int = 0

    def _candidate(self, value: float, candidates: list[float]) -> None:
        _require(len(candidates) < MAX_OUTPUTTIME_CANDIDATES_PER_CALL,
                 "OutputTime crossing exceeds the fixed per-call candidate limit",
                 "OUTPUTTIME_BOUNDS_REJECTED")
        _require(math.isfinite(value), "OutputTime produced a nonfinite candidate",
                 "OUTPUTTIME_NONFINITE_REJECTED")
        candidates.append(value)

    def get_next(self, time_value: float, time_token: str) -> dict[str, Any]:
        _require(math.isfinite(time_value) and time_value >= 0.0,
                 "OutputTime input time must be finite and nonnegative",
                 "NONFINITE_TIME_TOKEN")
        base_before = self.time_base
        if self.last_time_input is not None and time_value == self.last_time_input:
            return {
                "input_time_token": time_token,
                "input_time_binary64": _binary64(time_value),
                "last_input_reused": True,
                "time_base_before": base_before,
                "time_base_after": self.time_base,
                "schedule_boundaries_crossed": [],
                "candidate_times_at_or_before_input": [],
                "returned_next_time": _binary64(self.last_time_output),
                "candidate_count": 0,
                "returned_from_cached_input": True,
            }

        self.last_time_input = time_value
        candidates: list[float] = []
        boundaries: list[float] = []
        if self.config["mode"] == "simple":
            timeout = self.config["time_part_binary64"]["value"]
            next_time = self.last_time_output
            while time_value >= next_time:
                self.simple_tout_num += 1
                _require(self.simple_tout_num <= MAX_SIMPLE_TOUT_NUM,
                         "simple OutputTime crossing exceeds the fixed counter limit",
                         "OUTPUTTIME_BOUNDS_REJECTED")
                next_time = timeout * self.simple_tout_num
                self._candidate(next_time, candidates)
            self.last_time_output = next_time
        else:
            segments = self.config["segments"]
            while self.time_base + 1 < len(segments):
                next_boundary = segments[self.time_base + 1]["time_binary64"]["value"]
                if time_value < next_boundary:
                    break
                self.time_base += 1
                boundaries.append(next_boundary)
            segment = segments[self.time_base]
            base_time = segment["time_binary64"]["value"]
            timeout = segment["timeout_binary64"]["value"]
            next_boundary = (
                segments[self.time_base + 1]["time_binary64"]["value"]
                if self.time_base + 1 < len(segments) else math.inf
            )
            if time_value < base_time:
                next_time = base_time
                self._candidate(next_time, candidates)
            else:
                ratio = (time_value - base_time) / timeout
                _require(math.isfinite(ratio) and 0.0 <= ratio <= UINT32_MAX,
                         "special OutputTime interval index is outside native unsigned range",
                         "OUTPUTTIME_BOUNDS_REJECTED")
                interval = int(ratio)  # positive C++ double-to-unsigned truncation
                next_time = base_time + timeout * interval
                self._candidate(next_time, candidates)
                while next_time <= time_value:
                    interval += 1
                    _require(interval <= UINT32_MAX,
                             "special OutputTime interval index exceeded native unsigned range",
                             "OUTPUTTIME_BOUNDS_REJECTED")
                    next_time = base_time + timeout * interval
                    self._candidate(next_time, candidates)
                if next_time > next_boundary:
                    next_time = next_boundary
            self.last_time_output = next_time

        crossed = [candidate for candidate in candidates if candidate <= time_value]
        return {
            "input_time_token": time_token,
            "input_time_binary64": _binary64(time_value),
            "last_input_reused": False,
            "time_base_before": base_before,
            "time_base_after": self.time_base,
            "schedule_boundaries_crossed": [_binary64(value) for value in boundaries],
            "candidate_times_at_or_before_input": [_binary64(value) for value in crossed],
            "candidate_count": len(candidates),
            "returned_next_time": _binary64(self.last_time_output),
            "returned_from_cached_input": False,
        }


def _attempt_metadata(labels: Sequence[str] | None, row_count: int) -> dict[str, Any]:
    if labels is None:
        return {
            "labels_supplied": False,
            "labels_consistent": None,
            "cross_attempt_detected": False,
            "labels_untrusted": True,
        }
    _require(isinstance(labels, (list, tuple)) and len(labels) == row_count,
             "attempt labels must have exactly one untrusted label per raw row",
             "ATTEMPT_LABELS_REJECTED")
    _require(all(isinstance(label, str) and bool(label) for label in labels),
             "attempt labels must be nonempty strings",
             "ATTEMPT_LABELS_REJECTED")
    unique = set(labels)
    if len(unique) != 1:
        raise CadenceDiagnosticError(
            "raw rows carry more than one untrusted attempt label",
            "CROSS_ATTEMPT_REJECTED",
        )
    return {
        "labels_supplied": True,
        "labels_consistent": True,
        "cross_attempt_detected": False,
        "labels_untrusted": True,
    }


def _base_receipt(payload: Any, case_id: Any) -> dict[str, Any]:
    if isinstance(payload, bytes):
        source = {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
    else:
        source = {"bytes": None, "sha256": None}
    return {
        "schema": SCHEMA,
        "status": "synthetic_structural_untrusted_rejected",
        "input_scope": INPUT_SCOPE,
        "case_id_claim": case_id if isinstance(case_id, str) else None,
        "source_runparts": source,
        "source_authenticated": False,
        "source_attempt_identity_verified": False,
        "runtime_authenticated": False,
        "runtime_configuration_verified": False,
        "normal_completion_verified": False,
        "output_mode_verified": False,
        "execution_horizon_verified": False,
        "terminal_flush_verified": False,
        "native_integrity_evaluated": False,
        "T1_numerical": False,
        "gate_decision_eligible": False,
        "qualification_credit": 0,
        "execution_authority": {
            "native_solver_started": False,
            "worker_started": False,
            "gpu_started": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
        },
        "checks": {
            "synthetic_only": True,
            "production_hdf5_read": False,
            "native_solver_or_worker_run": False,
            "raw_csv_shape": False,
            "raw_realstr_tokens_preserved": False,
            "realstr_emission_proven": False,
            "binary64_stateful_outputtime_evaluated": False,
            "cadence_consistent": False,
            "t_end_reached": False,
            "final_savedata_observed": False,
            "no_final_savedata_detected": False,
            "single_attempt_label_consistent": False,
        },
        "diagnostic_findings": [],
    }


def build_diagnostic_receipt(
    payload: bytes,
    *,
    case_id: str,
    t_end_token: str,
    output_time: Mapping[str, Any],
    attempt_labels: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Build a bounded synthetic receipt without opening any repository path.

    A row in ``RunPARTs.csv`` represents a completed ``SaveData`` call.  The
    initial Part 0 row is unconditional in ``JSphCpuSingle::Run``; every later
    row must cross the stateful ``TimePartNext`` returned by OutputTime.  The
    final row is considered terminally observed only when its binary64 time is
    at or beyond the supplied ``T_end`` token.  Overshoot is retained as a
    separate fact because the native loop tests ``TimeStep < TimeMax`` and can
    step past the horizon.
    """
    receipt = _base_receipt(payload, case_id)
    try:
        _require(isinstance(case_id, str) and bool(case_id),
                 "case_id must be a nonempty string", "CASE_ID_REJECTED")
        parsed = parse_raw_runparts_csv(payload)
        end_token, end_value = _parse_time_token(t_end_token, "T_end", positive=True)
        config = _parse_output_time_config(output_time)
        attempt = _attempt_metadata(attempt_labels, parsed["data_row_count"])
        receipt["attempt_input"] = attempt
        receipt["output_time_config"] = config
        receipt["T_end"] = {"raw_token": end_token, **_binary64(end_value)}
        receipt["runparts"] = parsed

        state = _OutputTimeState(config)
        first = parsed["raw_rows"][0]
        initial_transition = state.get_next(
            first["time_step_binary64"]["value"], first["time_step_token"]
        )
        next_time = initial_transition["returned_next_time"]["value"]
        cadence_trace: list[dict[str, Any]] = [{
            "part_token": first["part_token"],
            "time_step_token": first["time_step_token"],
            "initial_savedata_unconditional": True,
            "save_due_to_outputtime": False,
            "next_time_after_initial_call": initial_transition["returned_next_time"],
            "outputtime_transition": initial_transition,
        }]
        findings: list[dict[str, Any]] = []
        cadence_consistent = True
        for row in parsed["raw_rows"][1:]:
            time_value = row["time_step_binary64"]["value"]
            due = time_value >= next_time
            next_time_before_call = _binary64(next_time)
            if not due:
                cadence_consistent = False
                findings.append({
                    "code": "SAVEDATA_BEFORE_OUTPUTTIME_CROSSING",
                    "detail": (
                        f"Part {row['part_token']} at raw token {row['time_step_token']} "
                        f"is below stateful next output time {next_time.hex()}"
                    ),
                })
                cadence_trace.append({
                    "part_token": row["part_token"],
                    "time_step_token": row["time_step_token"],
                    "initial_savedata_unconditional": False,
                    "save_due_to_outputtime": False,
                    "next_time_before_call": next_time_before_call,
                    "outputtime_transition": None,
                })
                continue
            transition = state.get_next(time_value, row["time_step_token"])
            next_time = transition["returned_next_time"]["value"]
            cadence_trace.append({
                "part_token": row["part_token"],
                "time_step_token": row["time_step_token"],
                "initial_savedata_unconditional": False,
                "save_due_to_outputtime": True,
                "next_time_before_call": next_time_before_call,
                "crossed_target_count_lower_bound": (
                    len(transition["candidate_times_at_or_before_input"])
                    + len(transition["schedule_boundaries_crossed"])
                ),
                "outputtime_transition": transition,
            })

        last_time = parsed["last_recorded_time_s"]
        t_end_reached = last_time >= end_value
        final_savedata_observed = t_end_reached
        if not final_savedata_observed:
            findings.append({
                "code": "FINAL_SAVEDATA_MISSING",
                "detail": (
                    f"last raw RunPARTs time {parsed['last_recorded_time_token']} "
                    f"is below T_end token {end_token}; a final SaveData is not observed"
                ),
            })
        if not cadence_consistent:
            findings.insert(0, {
                "code": "OUTPUTTIME_CADENCE_MISMATCH",
                "detail": "one or more raw saved PARTs precede their stateful OutputTime crossing",
            })

        receipt["checks"].update({
            "raw_csv_shape": True,
            "raw_realstr_tokens_preserved": True,
            "binary64_stateful_outputtime_evaluated": True,
            "cadence_consistent": cadence_consistent,
            "t_end_reached": t_end_reached,
            "final_savedata_observed": final_savedata_observed,
            "no_final_savedata_detected": not final_savedata_observed,
            "single_attempt_label_consistent": attempt["labels_consistent"] is True,
        })
        receipt["cadence_trace"] = cadence_trace
        receipt["cadence_summary"] = {
            "output_time_mode": config["mode"],
            "initial_next_time": initial_transition["returned_next_time"],
            "transition_count": len(cadence_trace) - 1,
            "multi_target_crossing_observed": any(
                item.get("crossed_target_count_lower_bound", 0) > 1
                for item in cadence_trace
            ),
            "last_recorded_time": _binary64(last_time),
            "t_end": _binary64(end_value),
            "overshot_t_end": last_time > end_value,
            "final_savedata_observed": final_savedata_observed,
        }
        receipt["diagnostic_findings"] = findings
        receipt["status"] = (
            "synthetic_structural_untrusted"
            if not findings and cadence_consistent and final_savedata_observed
            else "synthetic_structural_untrusted_rejected"
        )
        return receipt
    except CadenceDiagnosticError as error:
        receipt["diagnostic_findings"] = [{"code": error.code, "detail": str(error)}]
        return receipt


diagnose = build_diagnostic_receipt


__all__ = [
    "CadenceDiagnosticError",
    "INPUT_SCOPE",
    "MAX_OUTPUTTIME_CANDIDATES_PER_CALL",
    "MAX_OUTPUTTIME_SEGMENTS",
    "MAX_RUNPARTS_BYTES",
    "MAX_RUNPARTS_ROWS",
    "RUNPARTS_FOOTER",
    "RUNPARTS_HEADER",
    "SCHEMA",
    "build_diagnostic_receipt",
    "diagnose",
    "parse_raw_runparts_csv",
]
