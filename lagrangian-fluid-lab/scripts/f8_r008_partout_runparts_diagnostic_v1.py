"""Synthetic-input-only diagnostic join for R008 RunPARTs and PartOut.

The parser verifies bounded file structure and per-PART count consistency. It
does not authenticate production provenance, output-mode activation, complete
execution through T_end, or terminal flush; its exclusion gate is therefore
permanently diagnostic-only (open/missing) and can never pass or fail here.
"""
from __future__ import annotations

from collections import Counter
import csv
from dataclasses import dataclass
import hashlib
import io
import math
import re
import struct
from typing import Any, Sequence

from scripts import f8_r008_runparts_timestep_diagnostic_v2 as runparts
from scripts import f8_r008_safe_bi4_decoder_v1 as bi4


SCHEMA = "core.cfd.f8.r008.partout_runparts_diagnostic.v1"
MAX_PARTOUT_BLOCKS = 128
MAX_PARTOUT_TOTAL_BYTES = 256 * 1024 * 1024
MAX_PARTOUT_RECORDS = runparts.MAX_RUNPARTS_ROWS
PARTOUT_FILE = re.compile(r"PartOut_([0-9]{3,})\.obi4\Z", re.ASCII)
PART_NAME = re.compile(r"PART_([0-9]{4,})\Z", re.ASCII)
PARTOUT_FILECODE = b"#FileJBD JPartOutBi4"

_COLUMN = {name: runparts.RUNPARTS_HEADER.index(name) for name in (
    "Part", "NpOut", "NpOutPos", "NpOutRho", "NpOutMov",
)}
_ARRAY_TYPES = {
    "Idp": 8,
    "Pos": 22,
    "Posd": 23,
    "Vel": 22,
    "Rhop": 11,
    "Motive": 4,
}


class PartOutDiagnosticError(ValueError):
    """An input is malformed or inconsistent with the bounded diagnostic contract."""


@dataclass(frozen=True)
class PartOutSource:
    filename: str
    fd: int
    expected_sha256: str


@dataclass(frozen=True)
class _ParsedPartOut:
    part: int
    nout: int
    fd: int
    arrays: dict[str, bi4.ArrayRecord]


def _fail(message: str) -> None:
    raise PartOutDiagnosticError(message)


def _uint(value: Any, label: str) -> int:
    if type(value) is not int or value < 0:
        _fail(f"{label} must be a nonnegative integer")
    return value


def _value_map(item: bi4.ItemRecord, label: str) -> dict[str, bi4.ValueRecord]:
    result = {entry.name: entry for entry in item.values}
    if len(result) != len(item.values):
        _fail(f"{label} contains duplicate values")
    return result


def _parse_runparts(payload: bytes) -> tuple[dict[str, Any], list[dict[str, int]]]:
    if not isinstance(payload, bytes):
        _fail("RunPARTs input must be immutable bytes")
    try:
        parsed = runparts.parse_runparts_csv(payload)
        text = payload.decode("utf-8", errors="strict")
        rows = csv.reader(io.StringIO(text, newline=""), delimiter=";", strict=True)
        header = next(rows)
        if tuple(header) != runparts.RUNPARTS_HEADER:
            _fail("RunPARTs header changed after its bounded validation")
        data: list[dict[str, int]] = []
        for cells in rows:
            if cells == []:
                break
            if len(cells) != len(runparts.RUNPARTS_HEADER):
                _fail("RunPARTs row width changed after its bounded validation")
            row = {
                name: int(cells[index].replace(",", ""))
                for name, index in _COLUMN.items()
            }
            if row["NpOut"] != row["NpOutPos"] + row["NpOutRho"] + row["NpOutMov"]:
                _fail(f"RunPARTs PART {row['Part']} reason counts do not sum to NpOut")
            data.append(row)
        if len(data) != parsed["data_row_count"]:
            _fail("RunPARTs row count changed between bounded parser passes")
        return parsed, data
    except PartOutDiagnosticError:
        raise
    except Exception as error:
        raise PartOutDiagnosticError(f"RunPARTs parse failed: {type(error).__name__}") from error


def _root_identity(root: bi4.ItemRecord, block: int) -> tuple[tuple[str, int, Any], ...]:
    values = _value_map(root, "PartOut root")
    for name in ("Piece", "Npiece", "Block"):
        value = values.get(name)
        if value is None or value.type_code != 8:
            _fail(f"PartOut root lacks uint {name}")
    if (
        values["Piece"].value != 0
        or values["Npiece"].value != 1
        or values["Block"].value != block
    ):
        _fail("PartOut root piece/block metadata disagrees with the CPU single-piece filename")
    return tuple(sorted(
        (entry.name, entry.type_code, entry.value)
        for entry in root.values if entry.name != "Block"
    ))


def _scan_partout_source(
    source: PartOutSource,
) -> tuple[
    int,
    tuple[tuple[str, int, Any], ...],
    list[_ParsedPartOut],
    dict[str, Any],
    tuple[int, int, int, int, int],
]:
    match = PARTOUT_FILE.fullmatch(source.filename)
    if match is None:
        _fail("only single-piece PartOut_<block>.obi4 filenames are supported")
    block = int(match.group(1))
    if not isinstance(source.expected_sha256, str) or not re.fullmatch(
        r"[0-9a-f]{64}", source.expected_sha256, re.ASCII
    ):
        _fail("each PartOut source requires a lowercase SHA-256 binding")
    try:
        before = bi4._check_input_stat(source.fd)
        input_identity = bi4._identity(before)
        raw_hash = bi4._hash_fd(source.fd, before.st_size)
        if raw_hash != source.expected_sha256:
            _fail(f"{source.filename} hash does not match its expected binding")
        header = bi4._pread_exact(source.fd, bi4.HEADER_BYTES, 0, before.st_size)
        title = header[:60]
        if not title.startswith(PARTOUT_FILECODE):
            _fail(f"{source.filename} BI4 filecode is not JPartOutBi4")
        if title[len(PARTOUT_FILECODE):58] != b" " * (58 - len(PARTOUT_FILECODE)):
            _fail(f"{source.filename} BI4 filecode padding is malformed")
        if (
            title[58:] != b"\n\0"
            or header[60] != 0
            or header[61] != 0
            or header[62:64] != b"\0\0"
        ):
            _fail(f"{source.filename} BI4 fixed header is unsupported")

        items: list[bi4.ItemRecord] = []
        position = bi4.HEADER_BYTES
        while position < before.st_size:
            if len(items) >= MAX_PARTOUT_RECORDS + 1:
                _fail(f"{source.filename} top-level item count exceeds the diagnostic cap")
            scanner = bi4._Scanner(source.fd, before.st_size)
            scanner.pos = position
            item = scanner._item(1, ())
            if scanner.pos <= position:
                _fail(f"{source.filename} BI4 item parser made no forward progress")
            if len(scanner.all_arrays) > 5:
                _fail(f"{source.filename} has more than five arrays in one top-level item")
            items.append(item)
            position = scanner.pos
        if position != before.st_size or not items:
            _fail(f"{source.filename} BI4 item stream is empty or has trailing bytes")
        after_parse = bi4._check_input_stat(source.fd)
        if not bi4._same_stat(before, after_parse):
            _fail(f"{source.filename} identity changed during parsing")
        if bi4._hash_fd(source.fd, before.st_size) != raw_hash:
            _fail(f"{source.filename} bytes changed during parsing")
    except PartOutDiagnosticError:
        raise
    except Exception as error:
        raise PartOutDiagnosticError(
            f"{source.filename} BI4 stream rejected: {type(error).__name__}: {error}"
        ) from error
    root = items[0]
    if root.name != "JPartOutBi4" or root.arrays or root.children:
        _fail(f"{source.filename} does not start with a leaf JPartOutBi4 root item")
    root_identity = _root_identity(root, block)
    records: list[_ParsedPartOut] = []
    last_part = -1
    for item in items[1:]:
        name_match = PART_NAME.fullmatch(item.name)
        if name_match is None or item.children:
            _fail(f"{source.filename} contains a non-leaf or misnamed PART record")
        values = _value_map(item, item.name)
        if set(values) != {"Cpart", "TimeStep", "Nout"}:
            _fail(f"{item.name} does not have the exact PartOut value schema")
        if values["Cpart"].type_code != 8 or values["Nout"].type_code != 8:
            _fail(f"{item.name} Cpart/Nout values are not uint")
        if values["TimeStep"].type_code != 12 or not math.isfinite(values["TimeStep"].value):
            _fail(f"{item.name} TimeStep is not a finite double")
        if values["TimeStep"].value < 0:
            _fail(f"{item.name} TimeStep is negative")
        part = _uint(values["Cpart"].value, f"{item.name}.Cpart")
        nout = _uint(values["Nout"].value, f"{item.name}.Nout")
        if part != int(name_match.group(1)) or item.name != f"PART_{part:04d}":
            _fail(f"{item.name} name and Cpart identity disagree")
        if part <= last_part:
            _fail(f"{source.filename} PART records are not in strictly increasing order")
        last_part = part
        if nout == 0:
            _fail(f"{item.name} has Nout=0 although the native writer omits zero-event items")
        if nout > bi4.MAX_ARRAY_COUNT:
            _fail(f"{item.name}.Nout exceeds the bounded native array count")

        arrays = {entry.name: entry for entry in item.arrays}
        if len(arrays) != len(item.arrays):
            _fail(f"{item.name} contains duplicate array names")
        position_names = {"Pos", "Posd"}.intersection(arrays)
        id_names = {"Idp"}.intersection(arrays)
        expected_names = {"Vel", "Rhop", "Motive"} | position_names | id_names
        if (
            len(position_names) != 1
            or len(id_names) != 1
            or set(arrays) != expected_names
            or len(arrays) != 5
        ):
            _fail(f"{item.name} arrays are not exactly ID/position/velocity/density/motive")
        for array_name, array in arrays.items():
            if array.type_code != _ARRAY_TYPES[array_name] or array.count != nout:
                _fail(f"{item.name}.{array_name} type/count does not match Nout")
        records.append(_ParsedPartOut(
            part=part,
            nout=nout,
            fd=source.fd,
            arrays=arrays,
        ))
    return block, root_identity, records, {
        "filename": source.filename,
        "bytes": before.st_size,
        "sha256": raw_hash,
        "block": block,
        "part_record_count": len(records),
    }, input_identity


def _stable_after_payload_reads(
    source: PartOutSource,
    expected_identity: tuple[int, int, int, int, int],
) -> None:
    try:
        before = bi4._check_input_stat(source.fd)
        if bi4._identity(before) != expected_identity:
            _fail(f"{source.filename} identity changed before array verification")
        digest = bi4._hash_fd(source.fd, before.st_size)
        after = bi4._check_input_stat(source.fd)
        if not bi4._same_stat(before, after):
            _fail(f"{source.filename} identity changed during array verification")
        if digest != source.expected_sha256:
            _fail(f"{source.filename} bytes changed before array verification")
    except PartOutDiagnosticError:
        raise
    except Exception as error:
        raise PartOutDiagnosticError(
            f"{source.filename} stability check failed: {type(error).__name__}"
        ) from error


def _event_payload_check(
    record: _ParsedPartOut,
    *,
    expected_counts: dict[str, int],
    expected_pos_double: bool | None,
) -> dict[str, Any]:
    arrays = record.arrays
    id_name = "Idp"
    pos_name = "Posd" if "Posd" in arrays else "Pos"
    if expected_pos_double is not None and (pos_name == "Posd") != expected_pos_double:
        _fail(f"PartOut PART {record.part} position precision disagrees with the supplied expectation")
    try:
        id_bytes = bi4._pread_exact(
            record.fd, arrays[id_name].byte_count, arrays[id_name].offset,
            bi4._check_input_stat(record.fd).st_size,
        )
        motive_bytes = bi4._pread_exact(
            record.fd, arrays["Motive"].byte_count, arrays["Motive"].offset,
            bi4._check_input_stat(record.fd).st_size,
        )
    except Exception as error:
        raise PartOutDiagnosticError(
            f"PartOut PART {record.part} array payload read failed: {type(error).__name__}"
        ) from error
    ids = struct.unpack("<" + "I" * record.nout, id_bytes)
    if len(set(ids)) != record.nout:
        _fail(f"PartOut PART {record.part} has duplicate particle IDs")
    histogram = Counter(motive_bytes)
    if set(histogram) - {1, 2, 3}:
        _fail(f"PartOut PART {record.part} contains an unknown Motive code")
    actual = {
        "NpOutPos": histogram.get(1, 0),
        "NpOutRho": histogram.get(2, 0),
        "NpOutMov": histogram.get(3, 0),
    }
    if actual != {key: expected_counts[key] for key in actual}:
        _fail(f"PartOut PART {record.part} Motive histogram disagrees with RunPARTs")
    if record.nout != expected_counts["NpOut"]:
        _fail(f"PartOut PART {record.part} Nout disagrees with RunPARTs NpOut")
    return {
        "part": record.part,
        "runparts_npout": expected_counts["NpOut"],
        "partout_nout": record.nout,
        "id_count": len(ids),
        "ids_unique_within_part": True,
        "position_array": pos_name,
        "motive_histogram": {str(key): histogram.get(key, 0) for key in (1, 2, 3)},
        "reason_counts_match": True,
    }


def _missing_result(
    code: str,
    detail: str,
    runparts_input: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = {
        "schema": SCHEMA,
        "status": "diagnostic_only_missing_or_inconsistent",
        "excluded_fluid_particles_zero": "missing",
        "diagnostic_findings": [{"code": code, "detail": detail[:512]}],
        "source_attempt_identity_verified": False,
        "output_mode_verified": False,
        "execution_horizon_verified": False,
        "terminal_flush_verified": False,
        "gate_decision_eligible": False,
        "qualification_credit": 0,
        "execution_authority": {
            "solver_started": False,
            "worker_started": False,
            "gpu_started": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
        },
    }
    if runparts_input is not None:
        result["runparts_input"] = runparts_input
    return result


def diagnose(
    runparts_payload: bytes,
    partout_sources: Sequence[PartOutSource] = (),
    *,
    expected_pos_double: bool | None = None,
) -> dict[str, Any]:
    """Return diagnostic-only per-PART consistency for supplied held inputs.

    Only synthetic inputs are in scope for this initial implementation. Each
    PartOut source must be an already-held regular-file descriptor opened by
    the caller; this function does not resolve or open a path.
    """
    runparts_input: dict[str, Any] | None = None
    try:
        if not isinstance(runparts_payload, bytes):
            _fail("RunPARTs input must be immutable bytes")
        if len(runparts_payload) > runparts.MAX_RUNPARTS_BYTES:
            _fail("RunPARTs byte length exceeds the frozen diagnostic cap")
        runparts_input = {
            "bytes": len(runparts_payload),
            "sha256": hashlib.sha256(runparts_payload).hexdigest(),
            "provenance_verified": False,
        }
        if expected_pos_double is not None and type(expected_pos_double) is not bool:
            _fail("expected_pos_double must be bool or None")
        if not isinstance(partout_sources, Sequence) or isinstance(partout_sources, (str, bytes)):
            _fail("PartOut sources must be a bounded sequence of held descriptors")
        if len(partout_sources) > MAX_PARTOUT_BLOCKS:
            _fail("PartOut block count exceeds the diagnostic cap")
        parsed_runparts, rows = _parse_runparts(runparts_payload)
        source_specs = list(partout_sources)
        if any(not isinstance(source, PartOutSource) for source in source_specs):
            _fail("every PartOut source must use the PartOutSource descriptor contract")
        blocks = [PARTOUT_FILE.fullmatch(source.filename) for source in source_specs]
        if any(match is None for match in blocks):
            _fail("only single-piece PartOut_<block>.obi4 filenames are supported")
        block_numbers = [int(match.group(1)) for match in blocks if match is not None]
        if len(set(block_numbers)) != len(block_numbers):
            _fail("PartOut block filenames are duplicated")
        ordered_sources = [source for _, source in sorted(zip(block_numbers, source_specs))]
        ordered_blocks = sorted(block_numbers)
        if ordered_blocks and ordered_blocks != list(range(len(ordered_blocks))):
            _fail("PartOut block sequence must begin at zero and be contiguous")

        total_bytes = 0
        for source in ordered_sources:
            try:
                size = bi4._check_input_stat(source.fd).st_size
            except Exception as error:
                raise PartOutDiagnosticError(
                    f"{source.filename} is not a bounded regular BI4 file: {type(error).__name__}"
                ) from error
            total_bytes += size
        if total_bytes > MAX_PARTOUT_TOTAL_BYTES:
            _fail("aggregate PartOut input bytes exceed the diagnostic cap")

        events: dict[int, _ParsedPartOut] = {}
        file_refs: list[dict[str, Any]] = []
        source_identities: list[tuple[PartOutSource, tuple[int, int, int, int, int]]] = []
        common_root_identity: tuple[tuple[str, int, Any], ...] | None = None
        last_event_part = -1
        for source in ordered_sources:
            block, root_identity, records, file_ref, source_identity = _scan_partout_source(source)
            if common_root_identity is None:
                common_root_identity = root_identity
            elif root_identity != common_root_identity:
                _fail("PartOut root metadata changed between block files")
            if int(PARTOUT_FILE.fullmatch(source.filename).group(1)) != block:
                _fail("PartOut filename/block identity changed during validation")
            for record in records:
                if record.part in events:
                    _fail(f"PartOut PART {record.part} is duplicated across block files")
                if record.part <= last_event_part:
                    _fail("PartOut PART records are not increasing across block files")
                last_event_part = record.part
                events[record.part] = record
                if len(events) > MAX_PARTOUT_RECORDS:
                    _fail("aggregate PartOut PART count exceeds the diagnostic cap")
            file_refs.append(file_ref)
            source_identities.append((source, source_identity))

        details: list[dict[str, Any]] = []
        for row in rows:
            part = row["Part"]
            event = events.pop(part, None)
            if row["NpOut"] == 0:
                if event is not None:
                    _fail(f"PartOut PART {part} exists although RunPARTs NpOut is zero")
                details.append({
                    "part": part,
                    "runparts_npout": 0,
                    "partout_record_present": False,
                })
                continue
            if event is None:
                _fail(f"RunPARTs PART {part} has NpOut>0 but no matching PartOut payload")
            details.append(_event_payload_check(
                event,
                expected_counts=row,
                expected_pos_double=expected_pos_double,
            ))
        if events:
            _fail(f"PartOut contains PART {min(events)} absent from RunPARTs")

        for source, source_identity in source_identities:
            _stable_after_payload_reads(source, source_identity)

        files_absent = not ordered_sources
        nonzero_runparts_parts = sum(row["NpOut"] > 0 for row in rows)
        if files_absent and nonzero_runparts_parts:
            _fail("PartOut files are absent while RunPARTs reports excluded particles")
        if files_absent:
            finding = {
                "code": "PARTOUT_ABSENCE_NOT_ZERO_EVIDENCE",
                "detail": "No PartOut file was supplied; this cannot establish zero excluded-fluid particles.",
            }
        else:
            finding = {
                "code": "SOURCE_AND_TERMINAL_EVIDENCE_UNAUTHENTICATED",
                "detail": "Structural joins agree, but source, output mode, full T_end coverage, and final flush remain unverified.",
            }
        return {
            "schema": SCHEMA,
            "status": "diagnostic_only_consistent_inputs_gate_open",
            "excluded_fluid_particles_zero": "open",
            "diagnostic_findings": [finding],
            "checks": {
                "runparts_v2_structure_passed": True,
                "runparts_per_part_reason_sum_checked": True,
                "partout_filelist_blocks_contiguous": bool(ordered_sources),
                "partout_root_piece_block_identity_checked": bool(ordered_sources),
                "nonzero_part_payloads_joined_exactly_once": True,
                "partout_id_and_array_counts_match_nout": True,
                "particle_ids_unique_within_each_part": True,
                "motive_histograms_match_runparts": True,
                "position_precision_expectation_supplied": expected_pos_double is not None,
                "position_precision_expected_value": expected_pos_double,
                "partout_absence_treated_as_zero": False,
            },
            "summary": {
                "runparts_data_rows": parsed_runparts["data_row_count"],
                "runparts_parts_with_nonzero_npout": nonzero_runparts_parts,
                "partout_blocks": len(ordered_sources),
                "partout_part_records": sum(ref["part_record_count"] for ref in file_refs),
                "matched_nonzero_parts": sum(row["NpOut"] > 0 for row in rows),
            },
            "part_diagnostics": details,
            "runparts_input": runparts_input,
            "partout_inputs": file_refs,
            "source_attempt_identity_verified": False,
            "output_mode_verified": False,
            "execution_horizon_verified": False,
            "terminal_flush_verified": False,
            "gate_decision_eligible": False,
            "qualification_credit": 0,
            "execution_authority": {
                "solver_started": False,
                "worker_started": False,
                "gpu_started": False,
                "queue_mutation": 0,
                "registry_mutation": 0,
                "ledger_mutation": 0,
            },
        }
    except Exception as error:
        return _missing_result(
            "PARTOUT_RUNPARTS_DIAGNOSTIC_INCOMPLETE", str(error), runparts_input
        )


__all__ = ["PartOutDiagnosticError", "PartOutSource", "SCHEMA", "diagnose"]
