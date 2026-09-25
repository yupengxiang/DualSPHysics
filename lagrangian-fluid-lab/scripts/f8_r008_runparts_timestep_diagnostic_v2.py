"""Parse only the chosen fresh, single-segment R008 diagnostic input shape.

The parser checks all 26 numeric CSV fields and recomputes the maximum
recorded PART ``DtMax``. Its input policy requires Part 0 / time 0 and rejects
restart/append segments; it does not prove that a solver invocation followed
this policy. It also does not verify cross-column solver accounting semantics,
attempt identity, runtime configuration, or normal completion, so it never
grants T1 credit.
"""
from __future__ import annotations

import csv
import hashlib
import io
import math
import os
from pathlib import Path
import re
from typing import Any

from scripts import f8_r008_per_case_bundle_verifier_v1 as bundle_v1
from scripts import f8_r008_runparts_timestep_diagnostic_v1 as runparts_v1


SCHEMA = "core.cfd.f8.r008_runparts_timestep_diagnostic.v2"
INPUT_SCOPE = "fresh_single_segment_part0_time0_only"
MAX_RUNPARTS_BYTES = runparts_v1.MAX_RUNPARTS_BYTES
MAX_RUNPARTS_ROWS = runparts_v1.MAX_RUNPARTS_ROWS
RUNPARTS_HEADER = runparts_v1.RUNPARTS_HEADER
RUNPARTS_FOOTER = runparts_v1.RUNPARTS_FOOTER
INTEGER_COLUMNS = (0, 2, 3, 5, 6, 7, 8, 9, 13, 14, 15, 16, 17, 18, 24, 25)
FLOAT_COLUMNS = (1, 4, 10, 11, 12, 19, 20, 21, 22, 23)
INTEGER_CELL = runparts_v1.INTEGER_CELL
FLOAT_CELL = re.compile(
    r"(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z",
    re.ASCII,
)


class RunPartsDiagnosticError(ValueError):
    """The R008 diagnostic input is unsafe or outside the chosen input policy."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RunPartsDiagnosticError(message)


def _nonnegative_integer(value: str, label: str) -> int:
    _require(bool(INTEGER_CELL.fullmatch(value)),
             f"RunPARTs {label} is not a supported nonnegative integer")
    return int(value.replace(",", ""))


def _nonnegative_float(value: str, label: str) -> float:
    _require(bool(FLOAT_CELL.fullmatch(value)),
             f"RunPARTs {label} is not a supported unsigned decimal representation")
    number = float(value)
    _require(math.isfinite(number) and number >= 0.0,
             f"RunPARTs {label} must be finite and nonnegative")
    return number


def parse_runparts_csv(payload: bytes) -> dict[str, Any]:
    """Validate all fields in one fresh R008 segment and recompute recorded max DtMax."""
    try:
        legacy_shape = runparts_v1.parse_runparts_csv(payload)
    except runparts_v1.RunPartsDiagnosticError as error:
        raise RunPartsDiagnosticError(str(error)) from error

    _require(legacy_shape["first_part"] == 0 and legacy_shape["data_row_count"] >= 2,
             "R008 diagnostic input policy requires one segment beginning at Part 0")
    rows = csv.reader(io.StringIO(payload.decode("utf-8"), newline=""), delimiter=";", strict=True)
    next(rows, None)
    data_row_count = 0
    for row in rows:
        if row == []:
            break
        _require(len(row) == len(RUNPARTS_HEADER),
                 "RunPARTs data row does not match the exact 26-column schema")
        for index in INTEGER_COLUMNS:
            _nonnegative_integer(row[index], RUNPARTS_HEADER[index])
        for index in FLOAT_COLUMNS:
            _nonnegative_float(row[index], RUNPARTS_HEADER[index])
        if data_row_count == 0:
            _require(float(row[1]) == 0.0 and int(row[2].replace(",", "")) == 0
                     and float(row[19]) == 0.0 and float(row[20]) == 0.0,
                     "R008 diagnostic input policy requires time zero and a zero-step initial PART")
        data_row_count += 1

    _require(data_row_count == legacy_shape["data_row_count"],
             "RunPARTs data rows changed between the bounded structural passes")
    return {
        **legacy_shape,
        "input_scope": INPUT_SCOPE,
        "all_26_fields_type_and_range_checked": True,
        "cross_field_native_semantics_verified": False,
    }


def build_diagnostic_receipt(path: Path | str, case_id: str) -> dict[str, Any]:
    """Safely read and parse one bounded fresh-segment R008 RunPARTs.csv."""
    source_path = Path(path)
    if not source_path.is_absolute():
        source_path = Path.cwd() / source_path
    _require(".." not in source_path.parts and source_path.name == "RunPARTs.csv",
             "RunPARTs input path must end in a sibling basename RunPARTs.csv")
    try:
        parent_fd, _parent_path = bundle_v1._open_absolute_directory(source_path.parent)
    except (OSError, ValueError) as error:
        raise RunPartsDiagnosticError("RunPARTs parent must be a real no-follow directory path") from error
    try:
        try:
            payload = runparts_v1._stable_read_at(parent_fd, source_path.name)
        except runparts_v1.RunPartsDiagnosticError as error:
            raise RunPartsDiagnosticError(str(error)) from error
    finally:
        os.close(parent_fd)

    parsed = parse_runparts_csv(payload)
    return {
        "schema": SCHEMA,
        "status": "diagnostic_only_fresh_segment_execution_unverified",
        "input_scope": INPUT_SCOPE,
        "case_id_claim": case_id,
        "maximum_recorded_part_dtmax_s": parsed["maximum_recorded_part_dtmax_s"],
        "checks": {
            "all_26_fields_type_and_range_checked": True,
            "single_segment_part0_time0_input_policy": True,
        },
        "source_runparts": {
            "path": "RunPARTs.csv",
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        },
        "parse_summary": parsed,
        "attempt_identity_verified": False,
        "runtime_configuration_verified": False,
        "cross_field_native_semantics_verified": False,
        "normal_completion_verified": False,
        "qualification_credit": 0,
    }


__all__ = [
    "FLOAT_COLUMNS", "INPUT_SCOPE", "INTEGER_COLUMNS", "MAX_RUNPARTS_BYTES", "MAX_RUNPARTS_ROWS",
    "RUNPARTS_FOOTER", "RUNPARTS_HEADER", "RunPartsDiagnosticError", "SCHEMA",
    "build_diagnostic_receipt", "parse_runparts_csv",
]
