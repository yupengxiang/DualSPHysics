#!/usr/bin/env python3
"""Root-registered full-time FloatingInfo worker for DS-DATA-02 F6.

The source package is disabled and never calls this worker.  Root142 may enable
one per-case request after the native receipt is terminal.  The worker then
runs the official FloatingInfo binary against that case's existing native data
root, parses every requested row (0..240), and writes a metadata report.  It
never substitutes PartVTK particle velocity for rigid-body fields.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

SCHEMA = "ds02.f6.fulltime-floatinginfo-worker-result.v1"
REQUEST_SCHEMA = "ds02.f6.fulltime-floatinginfo-request.v1"


class WorkerError(RuntimeError):
    """Fail-closed request, command, process, or CSV validation error."""


def _require_dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise WorkerError(f"{label} must be an object")
    return value


def _load_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise WorkerError(f"{label} is missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - exact parser exception is environment-specific
        raise WorkerError(f"{label} is not valid JSON: {path}") from exc
    return _require_dict(value, label)


def _absolute(raw: Any, label: str) -> Path:
    if not isinstance(raw, str) or not raw:
        raise WorkerError(f"{label} must be a non-empty absolute path")
    p = Path(raw)
    if not p.is_absolute():
        raise WorkerError(f"{label} is not absolute: {raw!r}")
    return p


def _finite(raw: Any, label: str) -> float:
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError) as exc:
        raise WorkerError(f"{label} is not numeric: {raw!r}") from exc
    if not math.isfinite(value):
        raise WorkerError(f"{label} is not finite: {raw!r}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _normalise(header: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(header).lower())


def _unit_marker(header: str, unit: str) -> bool:
    return f"[{unit}]" in str(header).lower().replace(" ", "")


# These are intentionally rigid fields.  A CSV that has only particle velocity
# or only a two-row state-zero prefix cannot satisfy this contract.
_REQUIRED_FIELDS: Mapping[str, tuple[tuple[str, ...], str | None]] = {
    "part": (("part",), None),
    "time_s": (("time [s]", "time", "times", "t"), "s"),
    "fvel_x": (("fvel.x [m/s]", "fvel.x", "fvelx"), "m/s"),
    "fvel_y": (("fvel.y [m/s]", "fvel.y", "fvely"), "m/s"),
    "fvel_z": (("fvel.z [m/s]", "fvel.z", "fvelz"), "m/s"),
    "fomega_x": (("fomega.x [rad/s]", "fomega.x", "fomegax"), "rad/s"),
    "fomega_y": (("fomega.y [rad/s]", "fomega.y", "fomegay"), "rad/s"),
    "fomega_z": (("fomega.z [rad/s]", "fomega.z", "fomegaz"), "rad/s"),
    "center_x": (("center.x [m]", "center.x", "centerx"), "m"),
    "center_y": (("center.y [m]", "center.y", "centery"), "m"),
    "center_z": (("center.z [m]", "center.z", "centerz"), "m"),
    "surge": (("surge [m]", "surge"), "m"),
    "sway": (("sway [m]", "sway"), "m"),
    "heave": (("heave [m]", "heave"), "m"),
    "roll": (("roll [deg]", "roll"), "deg"),
    "pitch": (("pitch [deg]", "pitch"), "deg"),
    "yaw": (("yaw [deg]", "yaw"), "deg"),
}


def _find_fields(headers: Sequence[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    normalised = [_normalise(x) for x in headers]
    for name, (aliases, unit) in _REQUIRED_FIELDS.items():
        alias_norm = {_normalise(alias) for alias in aliases}
        found: list[int] = []
        for index, (raw, norm) in enumerate(zip(headers, normalised)):
            if norm in alias_norm and (unit is None or _unit_marker(raw, unit)):
                found.append(index)
        if len(found) != 1:
            raise WorkerError(
                f"required field {name} must have exactly one header with units {unit!r}; "
                f"found={found!r}, headers={list(headers)!r}"
            )
        result[name] = found[0]
    return result


def _trim_trailing_empty(row: Sequence[str]) -> list[str]:
    values = list(row)
    while values and not str(values[-1]).strip():
        values.pop()
    return values


def _validate_part_contract(parts: Sequence[int], contract: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the opaque ``part`` column only after a registered pilot.

    FloatingInfo's official header names the column ``part`` but does not
    document whether a consumer should treat it as a marker or a frame index.
    The source package therefore leaves this binding null.  Root must bind a
    pilot-derived mode and values before a full export is allowed.
    """
    if not isinstance(contract, Mapping):
        raise WorkerError("part-column pilot contract is missing")
    if contract.get("pilot_required") is not True:
        raise WorkerError("part-column semantics must remain pilot-gated")
    mode = contract.get("mode")
    expected = contract.get("expected_values")
    if mode not in {"constant_marker", "frame_index"}:
        raise WorkerError("part-column pilot mode must be constant_marker or frame_index")
    if not isinstance(expected, list) or not expected:
        raise WorkerError("part-column pilot expected_values are missing")
    try:
        expected_ints = [int(value) for value in expected]
    except (TypeError, ValueError) as exc:
        raise WorkerError("part-column pilot expected_values must be integers") from exc
    if any(value != int(value) for value in expected):
        raise WorkerError("part-column pilot expected_values must be exact integers")
    if mode == "constant_marker":
        if len(expected_ints) != 1 or any(value != expected_ints[0] for value in parts):
            raise WorkerError(f"part column is not the pilot-bound constant marker: observed={sorted(set(parts))!r}")
    else:
        if len(expected_ints) != len(parts) or list(parts) != expected_ints or len(set(parts)) != len(parts):
            raise WorkerError("part column does not match the pilot-bound unique frame-index sequence")
    return {
        "pilot_required": True,
        "mode": mode,
        "expected_values": expected_ints,
        "observed_values": list(parts),
        "unique_observed_values": sorted(set(parts)),
        "frame_identity_from_part": mode == "frame_index",
        "no_part_value_inferred": False,
    }


def _parse_part(raw: str, label: str) -> int:
    value = _finite(raw, label)
    if value != int(value):
        raise WorkerError(f"{label} is not an integer: {raw!r}")
    return int(value)


def _parse_full_csv(path: Path, expected: Mapping[str, Any]) -> dict[str, Any]:
    """Parse all rows from an official semicolon FloatingInfo output."""
    if not path.is_file():
        raise WorkerError(f"official FloatingInfo output is missing: {path}")
    delimiter = str(expected.get("delimiter", ";"))
    if delimiter != ";":
        raise WorkerError(f"only the official semicolon output is accepted, got {delimiter!r}")
    expected_rows = int(expected.get("expected_rows", 241))
    expected_first = int(expected.get("first_frame", 0))
    expected_last = int(expected.get("last_frame", expected_rows - 1))
    if expected_last - expected_first + 1 != expected_rows:
        raise WorkerError("frame contract is internally inconsistent")

    headers: list[str] | None = None
    indices: dict[str, int] | None = None
    rows: list[list[str]] = []
    with path.open("r", encoding="utf-8-sig", errors="strict", newline="") as stream:
        reader = csv.reader(stream, delimiter=delimiter)
        for raw_row in reader:
            row = _trim_trailing_empty(raw_row)
            if not row:
                continue
            if headers is None:
                try:
                    candidate_indices = _find_fields(row)
                except WorkerError:
                    # Official exporters may put a short preamble before the
                    # header.  Ignore only pre-header rows; after the header,
                    # malformed/unit rows are hard failures.
                    continue
                headers = [str(value).strip() for value in row]
                indices = candidate_indices
                continue
            if len(row) < len(headers):
                raise WorkerError(f"short CSV row after header: {len(row)} < {len(headers)}")
            if len(row) > len(headers):
                raise WorkerError(f"wide CSV row after header: {len(row)} > {len(headers)}")
            rows.append(row)
    if headers is None or indices is None:
        raise WorkerError("official FloatingInfo CSV header with required units was not found")
    if len(rows) != expected_rows:
        raise WorkerError(f"expected exactly {expected_rows} data rows, found {len(rows)}")

    parts: list[int] = []
    times: list[float] = []
    rigid_finite_rows = 0
    for row_index, row in enumerate(rows):
        parts.append(_parse_part(row[indices["part"]], f"row {row_index} part"))
        row_time = _finite(row[indices["time_s"]], f"row {row_index} time_s")
        times.append(row_time)
        for field, index in indices.items():
            if field == "part":
                continue
            _finite(row[index], f"row {row_index} {field}")
        rigid_finite_rows += 1
    if any(right <= left for left, right in zip(times, times[1:])):
        raise WorkerError("official FloatingInfo times are not strictly increasing")

    part_contract = expected.get("part_contract")
    part_validation = _validate_part_contract(parts, part_contract)

    expected_start = float(expected.get("expected_start_s", 0.0))
    expected_end = float(expected.get("expected_end_s", 12.0))
    terminal_tolerance = float(expected.get("terminal_tolerance_s", 0.2))
    if abs(times[0] - expected_start) > terminal_tolerance:
        raise WorkerError(f"first official time does not cover start: {times[0]} vs {expected_start}")
    if times[-1] < expected_end - terminal_tolerance or times[-1] > expected_end + terminal_tolerance:
        raise WorkerError(f"last official time does not cover terminal: {times[-1]} vs {expected_end}")

    nominal_step = float(expected.get("nominal_tout_s", 0.05))
    nominal_times = [expected_start + nominal_step * i for i in range(len(times))]
    nominal_delta = [actual - nominal for actual, nominal in zip(times, nominal_times)]
    native_times = expected.get("native_times_s")
    native_comparison: dict[str, Any]
    if native_times is None:
        if expected.get("require_native_times", True):
            raise WorkerError("241 native_times_s values are required before full-time export")
        native_comparison = {"provided": False, "status": "not_supplied_by_source_template", "source": expected.get("native_time_source"), "official_times_retained": True}
    else:
        if not isinstance(native_times, list) or len(native_times) != len(times):
            raise WorkerError("native_times_s must be a list with one entry per official row")
        parsed_native = [_finite(x, f"native_times_s[{i}]") for i, x in enumerate(native_times)]
        if any(value < 0 for value in parsed_native):
            raise WorkerError("native_times_s must be nonnegative")
        if any(right <= left for left, right in zip(parsed_native, parsed_native[1:])):
            raise WorkerError("native_times_s must be strictly increasing")
        native_delta = [actual - native for actual, native in zip(times, parsed_native)]
        native_tolerance = float(expected.get("native_time_tolerance_s", 1e-6))
        if not math.isfinite(native_tolerance) or native_tolerance < 0:
            raise WorkerError("native_time_tolerance_s must be finite and nonnegative")
        max_abs_delta = max(abs(x) for x in native_delta)
        if max_abs_delta > native_tolerance:
            raise WorkerError(f"official/native time mismatch exceeds tolerance: {max_abs_delta} > {native_tolerance}")
        native_comparison = {
            "provided": True,
            "status": "compared_by_frame_index_without_resampling",
            "native_time_source": expected.get("native_time_source"),
            "native_times_s": parsed_native,
            "official_minus_native_s": native_delta,
            "max_abs_delta_s": max_abs_delta,
            "tolerance_s": native_tolerance,
            "within_tolerance": True,
        }
    return {
        "csv_path": str(path),
        "delimiter": delimiter,
        "header_columns": headers,
        "header_indices": indices,
        "rows_examined": len(rows),
        "row_ordinals": list(range(expected_first, expected_last + 1)),
        "frame_index_source": "official -first/-last request and CSV row order; the opaque part column is not used as a frame index unless the pilot binds frame_index mode",
        "part_values_observed": sorted(set(parts)),
        "part_row_count": len(parts),
        "official_times_s": times,
        "nominal_times_s": nominal_times,
        "official_minus_nominal_s": nominal_delta,
        "max_abs_nominal_delta_s": max(abs(x) for x in nominal_delta),
        "first_time_s": times[0],
        "last_time_s": times[-1],
        "strictly_increasing_time": True,
        "terminal_coverage": {
            "expected_start_s": expected_start,
            "expected_end_s": expected_end,
            "tolerance_s": terminal_tolerance,
            "covered": times[0] >= expected_start - terminal_tolerance and times[-1] >= expected_end - terminal_tolerance,
        },
        "rigid_fields_finite_rows": rigid_finite_rows,
        "required_rigid_field_count": len(_REQUIRED_FIELDS),
        "native_time_comparison": native_comparison,
        "part_column_contract": {
            "official_only_mk": expected.get("only_mk"),
            "part_column_required": True,
            **part_validation,
        },
    }


def _validate_receipt(request: Mapping[str, Any]) -> dict[str, Any]:
    native = _require_dict(request.get("native"), "native")
    receipt_path = _absolute(native.get("receipt_path"), "native.receipt_path")
    receipt = _load_json(receipt_path, "native receipt")
    expected_sha = native.get("receipt_sha256")
    actual_sha = _sha256(receipt_path)
    if expected_sha and actual_sha != expected_sha:
        raise WorkerError(f"native receipt SHA mismatch: expected {expected_sha}, got {actual_sha}")
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise WorkerError(f"native receipt is not completed/0: {receipt.get('status')!r}/{receipt.get('returncode')!r}")
    req = receipt.get("request")
    if isinstance(req, dict):
        for key in ("case_id", "physical_case_id"):
            expected = native.get(key)
            if expected and req.get(key) not in (None, expected):
                raise WorkerError(f"native receipt {key} mismatch: {req.get(key)!r} != {expected!r}")
    command = receipt.get("command")
    if isinstance(command, list):
        options = [str(x) for x in command if str(x).startswith("-tmax:") or str(x).startswith("-tout:")]
        if options and options != ["-tmax:12", "-tout:0.05"]:
            raise WorkerError(f"native receipt time options differ: {options!r}")
    return {"path": str(receipt_path), "expected_sha256": expected_sha, "actual_sha256": actual_sha, "status": receipt.get("status"), "returncode": receipt.get("returncode"), "request_case_id": (req or {}).get("case_id") if isinstance(req, dict) else None, "request_physical_case_id": (req or {}).get("physical_case_id") if isinstance(req, dict) else None}


def _validate_inventory_binding(
    request: Mapping[str, Any], case: Mapping[str, Any], rigid_path: Path, rigid_size: int
) -> dict[str, Any]:
    """Require a separately registered, immutable PartFloatInfo SHA inventory.

    The full-time exporter itself only consumes the inventory report's digest;
    it does not hash the scientific input a second time.  Root must run the
    dedicated inventory worker first and bind its completed report into the
    enabled copy of this request.
    """
    rigid_input = _require_dict(_require_dict(request.get("native"), "native").get("rigid_state_input"), "native.rigid_state_input")
    binding = _require_dict(rigid_input.get("inventory_binding"), "native.rigid_state_input.inventory_binding")
    if binding.get("required_before_official_export") is not True:
        raise WorkerError("PartFloatInfo inventory is required before official export")
    if binding.get("inventory_request_id") != "fresh168-partfloatinfo-inventory-v1":
        raise WorkerError("unexpected PartFloatInfo inventory request id")
    report_path = _absolute(binding.get("report_path"), "inventory_binding.report_path")
    report = _load_json(report_path, "PartFloatInfo inventory report")
    report_sha = _sha256(report_path)
    expected_report_sha = binding.get("report_sha256")
    if not isinstance(expected_report_sha, str) or len(expected_report_sha) != 64:
        raise WorkerError("inventory_binding.report_sha256 must be bound by Root")
    if report_sha != expected_report_sha:
        raise WorkerError(f"PartFloatInfo inventory report SHA mismatch: expected {expected_report_sha}, got {report_sha}")
    if report.get("schema") != "ds02.f6.partfloatinfo-inventory-result.v1" or report.get("status") != "completed" or report.get("returncode") != 0:
        raise WorkerError("PartFloatInfo inventory report is not completed/0")
    if report.get("request_id") != binding.get("inventory_request_id"):
        raise WorkerError("PartFloatInfo inventory request identity mismatch")
    entries = report.get("entries")
    if not isinstance(entries, list):
        raise WorkerError("PartFloatInfo inventory report entries are missing")
    matching = [entry for entry in entries if isinstance(entry, dict) and entry.get("physical_case_id") == case.get("physical_case_id")]
    if len(matching) != 1:
        raise WorkerError("PartFloatInfo inventory has no unique matching physical case")
    entry = matching[0]
    if entry.get("path") != str(rigid_path) or entry.get("relative_path") != "PartFloatInfo.ibi4":
        raise WorkerError("PartFloatInfo inventory path does not match this native input")
    if entry.get("bytes_before") != rigid_size or entry.get("bytes_after") != rigid_size:
        raise WorkerError("PartFloatInfo inventory byte count does not match stat-only request binding")
    entry_sha = entry.get("sha256")
    if not isinstance(entry_sha, str) or len(entry_sha) != 64:
        raise WorkerError("PartFloatInfo inventory entry SHA is missing")
    expected_entry_sha = binding.get("entry_source_sha256")
    if expected_entry_sha != entry_sha:
        raise WorkerError("PartFloatInfo inventory entry SHA is not closed in the enabled request")
    return {
        "report_path": str(report_path),
        "report_sha256": report_sha,
        "request_id": report.get("request_id"),
        "entry": entry,
    }


def _validate_request(request: Mapping[str, Any]) -> dict[str, Any]:
    if request.get("schema") != REQUEST_SCHEMA:
        raise WorkerError(f"unexpected request schema: {request.get('schema')!r}")
    if request.get("disabled") is True or request.get("source_only") is True or request.get("execution_allowed") is not True:
        raise WorkerError("source-disabled request cannot execute; Root must make an enabled copy")
    if request.get("launch_owner") != "root" or int(request.get("cpu_threads", 0)) != 2:
        raise WorkerError("request is not Root-owned CPU2")
    if int(request.get("max_wall_seconds", 0)) != 600:
        raise WorkerError("max_wall_seconds must be the bounded 600-second contract")
    if int(request.get("estimated_storage_bytes", 0)) != 536870912:
        raise WorkerError("estimated storage must remain the fresh167 512 MiB estimate")
    case = _require_dict(request.get("case"), "case")
    for key in ("case_id", "physical_case_id", "physical_condition_sha256"):
        if not isinstance(case.get(key), str) or not case[key]:
            raise WorkerError(f"case.{key} is required")
    native = _require_dict(request.get("native"), "native")
    native_root = _absolute(native.get("data_root"), "native.data_root")
    if not native_root.is_dir():
        raise WorkerError(f"native data root is not a directory: {native_root}")
    rigid_input = _require_dict(native.get("rigid_state_input"), "native.rigid_state_input")
    if rigid_input.get("source_stat_only") is not True:
        raise WorkerError("native.rigid_state_input must be a stat-only source binding")
    if rigid_input.get("state0_is_not_full_time") is not True:
        raise WorkerError("state-zero evidence must not be promoted to full-time evidence")
    relative_rigid = rigid_input.get("relative_path")
    if not isinstance(relative_rigid, str) or not relative_rigid or Path(relative_rigid).is_absolute() or ".." in Path(relative_rigid).parts:
        raise WorkerError("native.rigid_state_input.relative_path must be a safe relative filename")
    rigid_path = native_root / relative_rigid
    if not rigid_path.is_file():
        raise WorkerError(f"native embedded rigid-state file is missing: {rigid_path}")
    rigid_size = rigid_path.stat().st_size
    snapshot_size = rigid_input.get("source_stat_bytes")
    if snapshot_size is not None and int(snapshot_size) != rigid_size:
        raise WorkerError(f"native embedded rigid-state stat changed: expected {snapshot_size}, got {rigid_size}")
    receipt_meta = _validate_receipt(request)
    inventory_meta = _validate_inventory_binding(request, case, rigid_path, rigid_size)
    official = _require_dict(request.get("official_export"), "official_export")
    binary = _absolute(official.get("binary_path"), "official_export.binary_path")
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise WorkerError(f"official FloatingInfo binary is not executable: {binary}")
    binary_sha = _sha256(binary)
    if official.get("binary_sha256") and binary_sha != official["binary_sha256"]:
        raise WorkerError(f"official FloatingInfo binary SHA mismatch: expected {official['binary_sha256']}, got {binary_sha}")
    frame = _require_dict(request.get("frame_contract"), "frame_contract")
    if int(frame.get("first", -1)) != 0 or int(frame.get("last", -1)) != 240 or int(frame.get("expected_count", -1)) != 241:
        raise WorkerError("full-time frame contract must be 0..240 (241 rows)")
    if int(official.get("first", -1)) != 0 or int(official.get("last", -1)) != 240 or int(official.get("only_mk", -1)) != 60:
        raise WorkerError("official command marker/frame contract is not 0..240/-onlymk:60")
    time_contract = _require_dict(request.get("time_contract"), "time_contract")
    native_times = time_contract.get("native_times_s")
    if not isinstance(native_times, list) or len(native_times) != 241:
        raise WorkerError("enabled request must bind exactly 241 native_times_s values")
    native_tolerance = float(time_contract.get("native_time_tolerance_s", -1.0))
    if not math.isfinite(native_tolerance) or native_tolerance < 0:
        raise WorkerError("native_time_tolerance_s must be finite and nonnegative")
    parsed_native_times = [_finite(value, f"time_contract.native_times_s[{index}]") for index, value in enumerate(native_times)]
    if any(value < 0 for value in parsed_native_times) or any(right <= left for left, right in zip(parsed_native_times, parsed_native_times[1:])):
        raise WorkerError("enabled native_times_s must be nonnegative and strictly increasing")
    part_contract = _require_dict(official.get("part_contract"), "official_export.part_contract")
    expected_part_values = part_contract.get("expected_values")
    if part_contract.get("mode") not in {"constant_marker", "frame_index"} or not isinstance(expected_part_values, list) or not expected_part_values:
        raise WorkerError("enabled request must bind part-column pilot semantics")
    if part_contract.get("mode") == "constant_marker" and len(expected_part_values) != 1:
        raise WorkerError("constant-marker pilot must bind one expected value")
    if part_contract.get("mode") == "frame_index" and len(expected_part_values) != 241:
        raise WorkerError("frame-index pilot must bind 241 expected values")
    output = _require_dict(request.get("output"), "output")
    output_dir = _absolute(output.get("directory"), "output.directory")
    if output_dir == native_root or native_root in output_dir.parents:
        raise WorkerError("private output directory may not be inside native data root")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise WorkerError(f"private output directory is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = _absolute(output.get("report_path"), "output.report_path")
    if report_path.parent != output_dir and output_dir not in report_path.parents:
        raise WorkerError("report must be inside the private output directory")
    rigid_locator = {
        "path": str(rigid_path),
        "relative_path": relative_rigid,
        "exists": True,
        "bytes": rigid_size,
        "source_stat_bytes": snapshot_size,
        "stat_only_before_official_export": True,
        "state0_audit_status": rigid_input.get("state0_audit_status"),
        "state0_rows_examined": rigid_input.get("state0_rows_examined"),
        "state0_is_not_full_time": rigid_input.get("state0_is_not_full_time") is True,
    }
    return {"case": case, "native": native, "native_receipt": receipt_meta, "inventory": inventory_meta, "rigid_locator": rigid_locator, "native_root": native_root, "official": official, "binary": binary, "binary_sha256": binary_sha, "frame": frame, "output": output, "output_dir": output_dir, "report_path": report_path}


def _command(parts: Mapping[str, Any]) -> list[str]:
    o = parts["official"]
    out = parts["output_dir"] / "FloatingInfo"
    return [str(parts["binary"]), "-dirdata", str(parts["native_root"]), "-first:0", "-last:240", "-onlymk:60", "-savemotion:1", "-csvsep:0", "-savedata", str(out), "-createdirs:1"]


def _terminate_group(proc: subprocess.Popen[str]) -> None:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait(timeout=5)


def _run_official(command: list[str], output_dir: Path, timeout_s: int) -> dict[str, Any]:
    stdout_path = output_dir / "official-floatinginfo.stdout.log"
    stderr_path = output_dir / "official-floatinginfo.stderr.log"
    started = time.time()
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        proc: subprocess.Popen[str] | None = None
        try:
            proc = subprocess.Popen(command, stdout=stdout, stderr=stderr, start_new_session=True)
            try:
                returncode = proc.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired as exc:
                _terminate_group(proc)
                raise WorkerError(f"official FloatingInfo timed out after {timeout_s}s") from exc
        except OSError as exc:
            if proc is not None:
                _terminate_group(proc)
            raise WorkerError(f"could not start official FloatingInfo: {exc}") from exc
    return {"returncode": returncode, "elapsed_seconds": time.time() - started, "stdout": str(stdout_path), "stderr": str(stderr_path)}


def _write_report(path: Path, report: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def execute(request_path: Path, report_override: Path | None = None) -> int:
    request = _load_json(request_path, "worker request")
    report_path: Path | None = report_override
    base: dict[str, Any] = {"schema": SCHEMA, "request": str(request_path), "future_hashes_null": False}
    try:
        parts = _validate_request(request)
        report_path = report_path or parts["report_path"]
        command = _command(parts)
        run = _run_official(command, parts["output_dir"], int(request["max_wall_seconds"]))
        if run["returncode"] != 0:
            raise WorkerError(f"official FloatingInfo returned {run['returncode']}")
        output_csv = parts["output_dir"] / "FloatingInfo_mk60.csv"
        parsed = _parse_full_csv(output_csv, {
            "delimiter": ";", "expected_rows": 241, "first_frame": 0, "last_frame": 240,
            "only_mk": 60, "expected_start_s": request["time_contract"]["expected_start_s"],
            "expected_end_s": request["time_contract"]["expected_end_s"],
            "terminal_tolerance_s": request["time_contract"]["terminal_tolerance_s"],
            "nominal_tout_s": request["time_contract"]["nominal_tout_s"],
            "native_times_s": request["time_contract"].get("native_times_s"),
            "native_time_source": request["time_contract"].get("native_time_source"),
            "native_time_tolerance_s": request["time_contract"].get("native_time_tolerance_s"),
            "require_native_times": True,
            "part_contract": request["official_export"].get("part_contract"),
        })
        report = {
            **base, "status": "completed", "returncode": 0, "case": parts["case"],
            "native_receipt": parts["native_receipt"], "partfloatinfo_inventory": parts["inventory"], "official_command": command,
            "official_binary_sha256": parts["binary_sha256"], "runner": {"cpu_threads": 2, "max_wall_seconds": 600},
            "process": run, "output": {"csv": str(output_csv), "bytes": output_csv.stat().st_size, "sha256": _sha256(output_csv)},
            "parse": parsed,
            "native_embedded_rigid_state_locator": {**parts["rigid_locator"], "request_metadata": request.get("native_embedded_rigid_state_locator")},
            "time_policy": "Official FloatingInfo times are retained; nominal 0.05s differences are reported and no resampling or exact-equality claim is made.",
            "scientific_payload_hash_policy": "The registered worker hashes its produced official CSV only; it does not hash H5/BI4/native particle payloads.",
        }
        _write_report(report_path, report)
        return 0
    except Exception as exc:
        if report_path is None:
            report_path = report_override or request_path.with_name(request_path.stem + ".failure.json")
        _write_report(report_path, {**base, "status": "failed", "returncode": 1, "error_type": type(exc).__name__, "error": str(exc), "output_sha256": None})
        return 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    return execute(args.request, args.report)


if __name__ == "__main__":
    raise SystemExit(main())
