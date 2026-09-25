"""Parse a bounded DualSPHysics RunPARTs.csv as an untrusted diagnostic.

This parser validates the native CSV structure and recomputes the maximum
recorded PART ``DtMax``. It cannot establish which attempt produced the file,
whether execution reached the frozen end time, or whether the solver exited
normally; every returned receipt keeps those claims explicitly false.
"""
from __future__ import annotations

import csv
import hashlib
import io
import math
import os
from pathlib import Path
import re
import stat
from typing import Any

from scripts import f8_r008_per_case_bundle_verifier_v1 as bundle_v1


SCHEMA = "core.cfd.f8.r008_runparts_timestep_diagnostic.v1"
# The frozen R008 Definition/control pack peaks at 1,497 full native time-axis
# rows. 20,000 rows gives >13x headroom; 8 MiB also bounds whole-buffer decode
# and StringIO parsing. These are conservative diagnostic caps, not a promise
# for arbitrary RunPARTs files; increasing either requires a reviewed version.
MAX_RUNPARTS_BYTES = 8 * 1024 * 1024
MAX_RUNPARTS_ROWS = 20_000
RUNPARTS_HEADER = (
    "Part", "TimeStep [s]", "Steps", "DTsMin", "PartRuntime [s]",
    "NpSave", "NpSim", "NpNew", "NpOut", "NctSim", "NpAlloc [X]",
    "NctAlloc [X]", "SimRuntime [s]", "NpbSim", "NpfSim", "NpNormal",
    "NpOutPos", "NpOutRho", "NpOutMov", "DtMin [s]", "DtMax [s]",
    "MemCPU [MiB]", "MemGPU [MiB]", "MemGPU_Cells [MiB]", "NpAlloc", "NctAlloc",
)
RUNPARTS_FOOTER = (
    "# Part:  Number of output file with particles data.",
    "# TimeStep [s]:  Physical time of simulation.",
    "# Steps:  Number of calculation steps since the previous PART.",
    "# DTsMin:  Number of times the Dt is updated with the minimum allowed value (can be 2 times per step when Symplectic is used).",
    "# PartRuntime [s]:  Runtime of last PART simulation.",
    "# NpSave:  Number of selected particles to save.",
    "# NpSim:  Number of particles used in simulation (normal + periodic particles).",
    "# NpNew:  Number of new fluid particles created by inlet conditions since the previous PART.",
    "# NpOut:  Number of excluded fluid particles since the previous PART.",
    "# NctSim:  Number of cells used in simulation for particle search.",
    "# NpAlloc [X]:  Over-allocation memory for particles NpAlloc/NpSim.",
    "# NctAlloc [X]:  Over-allocation memory for cells NctAlloc/NctSim.",
    "# SimRuntime [s]:  Total runtime of simulation (initialisation tasks not included).",
    "# NpbSim:  Number of fixed and moving particles (includes periodic particles).",
    "# NpfSim:  Number of fluid and floating particles (includes periodic particles).",
    "# NpNormal:  Total number of particles without periodic particles.",
    "# NpOutPos:  Number of excluded particles due to invalid position.",
    "# NpOutRho:  Number of excluded particles due to invalid density.",
    "# NpOutMov:  Number of excluded particles due to invalid movement.",
    "# DtMin [s]:  Minimum value of Dt since the previous PART.",
    "# DtMax [s]:  Maximum value of Dt since the previous PART.",
    "# MemCPU [MiB]:  Current CPU memory allocated (only includes the most memory intensive objects).",
    "# MemGPU [MiB]:  Current GPU memory allocated (only includes the most memory intensive objects).",
    "# MemGPU_Cells [MiB]:  Current GPU memory allocated for cells according to NctAlloc.",
    "# NpAlloc:  Number of supported particles with memory allocated.",
    "# NctAlloc:  Number of supported cells with memory allocated.",
)
FLOAT_CELL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z", re.ASCII)
INTEGER_CELL = re.compile(r"(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)\Z", re.ASCII)


class RunPartsDiagnosticError(ValueError):
    """The RunPARTs source is unsafe or violates the frozen native CSV shape."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RunPartsDiagnosticError(message)


def _integer_cell(value: str, label: str) -> int:
    text = value
    _require(bool(INTEGER_CELL.fullmatch(text)), f"RunPARTs {label} is not a canonical nonnegative integer")
    return int(text.replace(",", ""))


def _float_cell(value: str, label: str) -> float:
    text = value
    _require(bool(FLOAT_CELL.fullmatch(text)), f"RunPARTs {label} is not a canonical decimal")
    number = float(text)
    _require(math.isfinite(number), f"RunPARTs {label} is not finite")
    return number


def parse_runparts_csv(payload: bytes) -> dict[str, Any]:
    """Validate the bounded 26-column PART block/footer and recompute max DtMax."""
    _require(isinstance(payload, bytes) and 0 < len(payload) <= MAX_RUNPARTS_BYTES,
             "RunPARTs CSV is empty or exceeds its fixed byte limit")
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise RunPartsDiagnosticError("RunPARTs CSV is not strict UTF-8") from error
    _require(not text.startswith("\ufeff"), "RunPARTs CSV must not contain a UTF-8 BOM")
    _require(payload.endswith(b"\n") and b"\r" not in payload and b'"' not in payload,
             "RunPARTs CSV must use the native unquoted LF-terminated format")
    try:
        rows = csv.reader(io.StringIO(text, newline=""), delimiter=";", strict=True)
        header = next(rows, None)
        _require(header == list(RUNPARTS_HEADER), "RunPARTs CSV header is not the exact frozen 26-column schema")

        data_count = 0
        footer_rows: list[list[str]] = []
        in_footer = False
        maximum_dtmax = 0.0
        first_part = 0
        previous_part = -1
        previous_time = -math.inf
        for row in rows:
            if not in_footer:
                if row == []:
                    _require(data_count > 0, "RunPARTs CSV has no data rows before its footer")
                    in_footer = True
                    continue
                _require(row and not row[0].startswith("#"), "RunPARTs footer must follow one blank line")
                _require(len(row) == len(RUNPARTS_HEADER), "RunPARTs data row has an unexpected field count")
                _require(data_count < MAX_RUNPARTS_ROWS,
                         "RunPARTs CSV exceeds its fixed data-row limit")
                _require(all(cell and cell == cell.strip() for cell in row),
                         "RunPARTs data cells must be nonempty and unpadded")
                part = _integer_cell(row[0], "Part")
                time_s = _float_cell(row[1], "TimeStep [s]")
                steps = _integer_cell(row[2], "Steps")
                dtmin = _float_cell(row[19], "DtMin [s]")
                dtmax = _float_cell(row[20], "DtMax [s]")
                if data_count == 0:
                    _require(time_s >= 0.0 and steps == 0 and dtmin == 0.0 and dtmax == 0.0,
                             "RunPARTs first row must be a nonnegative zero-step initial/restart PART")
                    first_part = part
                else:
                    _require(part == previous_part + 1 and time_s > previous_time and steps > 0,
                             "RunPARTs PART/time/step sequence is not strictly advancing")
                    _require(dtmin > 0.0 and dtmax > 0.0 and dtmin <= dtmax,
                             "RunPARTs noninitial DtMin/DtMax must be positive and ordered")
                    maximum_dtmax = max(maximum_dtmax, dtmax)
                previous_part = part
                previous_time = time_s
                data_count += 1
                continue

            _require(len(footer_rows) < len(RUNPARTS_HEADER), "RunPARTs CSV has extra rows after its footer")
            expected_footer = RUNPARTS_FOOTER[len(footer_rows)]
            _require(row == [expected_footer],
                     "RunPARTs CSV footer is incomplete, reordered, or malformed")
            footer_rows.append(row)
    except csv.Error as error:
        raise RunPartsDiagnosticError("RunPARTs CSV has malformed delimited text") from error

    _require(in_footer and len(footer_rows) == len(RUNPARTS_HEADER),
             "RunPARTs CSV lacks the exact final footer emitted by FinishRun")
    _require(data_count >= 2 and maximum_dtmax > 0.0,
             "RunPARTs CSV has no positive noninitial recorded timestep")
    return {
        "data_row_count": data_count,
        "first_part": first_part,
        "last_part": previous_part,
        "last_recorded_time_s": previous_time,
        "maximum_recorded_part_dtmax_s": maximum_dtmax,
        "footer_present": True,
        "attempt_identity_verified": False,
        "normal_completion_verified": False,
        "frozen_end_time_reached": False,
        "qualification_credit": 0,
    }


def _file_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns, value.st_nlink)


def _stable_read_at(parent_fd: int, name: str) -> bytes:
    _require(name == "RunPARTs.csv", "source must be the exact RunPARTs.csv sibling filename")
    flags = (os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
             | getattr(os, "O_NONBLOCK", 0))
    try:
        descriptor = os.open(name, flags, dir_fd=parent_fd)
    except OSError as error:
        raise RunPartsDiagnosticError("RunPARTs.csv is not safely openable") from error
    try:
        before = os.fstat(descriptor)
        _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                 and 0 < before.st_size <= MAX_RUNPARTS_BYTES,
                 "RunPARTs.csv must be a bounded single-link regular file")
        named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        _require(_file_identity(before) == _file_identity(named),
                 "RunPARTs.csv path changed while opening")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            block = os.read(descriptor, min(1024 * 1024, remaining))
            _require(bool(block), "RunPARTs.csv was truncated while being read")
            chunks.append(block)
            remaining -= len(block)
        _require(os.read(descriptor, 1) == b"", "RunPARTs.csv grew while being read")
        after = os.fstat(descriptor)
        named_after = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        _require(_file_identity(before) == _file_identity(after) == _file_identity(named_after),
                 "RunPARTs.csv changed while being read")
        return b"".join(chunks)
    except OSError as error:
        raise RunPartsDiagnosticError("RunPARTs.csv could not be read as one stable file") from error
    finally:
        os.close(descriptor)


def build_diagnostic_receipt(path: Path | str, case_id: str) -> dict[str, Any]:
    """Safely parse one RunPARTs.csv and return an explicitly untrusted summary."""
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
        payload = _stable_read_at(parent_fd, source_path.name)
    finally:
        os.close(parent_fd)
    parsed = parse_runparts_csv(payload)
    return {
        "schema": SCHEMA,
        "status": "diagnostic_only_execution_unverified",
        "case_id_claim": case_id,
        "maximum_recorded_part_dtmax_s": parsed["maximum_recorded_part_dtmax_s"],
        "checks": {"strict_runparts_csv_structure": True},
        "source_runparts": {
            "path": "RunPARTs.csv",
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        },
        "parse_summary": parsed,
        "attempt_identity_verified": False,
        "runtime_configuration_verified": False,
        "normal_completion_verified": False,
        "qualification_credit": 0,
    }


__all__ = [
    "MAX_RUNPARTS_BYTES", "MAX_RUNPARTS_ROWS", "RUNPARTS_FOOTER", "RUNPARTS_HEADER",
    "RunPartsDiagnosticError", "SCHEMA",
    "build_diagnostic_receipt", "parse_runparts_csv",
]
