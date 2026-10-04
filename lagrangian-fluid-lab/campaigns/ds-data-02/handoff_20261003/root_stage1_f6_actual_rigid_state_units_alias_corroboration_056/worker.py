#!/usr/bin/env python3
"""Successor 061 wrapper for the F6 semicolon FloatingInfo decoder.

The immutable 059 worker owns the bounded H5/XML audit.  This successor loads
that worker and replaces only its FloatingInfo field decoder with aliases for
the exact normalized unit-bearing columns emitted by the genuine CSV:
``fomegaxrads``, ``fvelxms``, and ``centerxm`` (and their y/z siblings).
The source request remains disabled.  Running it later preserves the bounded
Type2 frame-zero/first-saved fits and adds correctly decoded CSV rows; this
module itself reads no data during source preparation.
"""

from __future__ import annotations

import csv
import importlib.util
import math
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


CURRENT_SCOPE = Path(__file__).resolve().parents[1]
PREVIOUS_WORKER = (
    CURRENT_SCOPE.parent
    / "root_followup_059_stage1_frame0_omega_csv_decoder_audit_v1"
    / "workers"
    / "audit_frame0_omega_csv.py"
).resolve()


def _load_previous() -> Any:
    spec = importlib.util.spec_from_file_location("f6_immutable_059_worker", PREVIOUS_WORKER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load immutable 059 worker: {PREVIOUS_WORKER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PREVIOUS = _load_previous()
SCHEMA = "ds02.f6.frame0-omega-csv-alias-fix-audit-result.v1"


def _field_index(headers: Sequence[str], aliases: Iterable[str]) -> Optional[int]:
    normalized = [PREVIOUS._normalise(header) for header in headers]
    lookup = {value: index for index, value in enumerate(normalized)}
    for alias in aliases:
        normalized_alias = PREVIOUS._normalise(alias)
        if normalized_alias in lookup:
            return lookup[normalized_alias]
    return None


def _field_value(row: Sequence[str], index: Optional[int]) -> Optional[float]:
    if index is None or index >= len(row):
        return None
    return PREVIOUS._parse_number(row[index])


def _vector_from_row(
    row: Sequence[str],
    headers: Sequence[str],
    aliases: Mapping[str, Iterable[str]],
) -> Tuple[Optional[List[float]], List[bool]]:
    indices = [_field_index(headers, aliases[axis]) for axis in ("x", "y", "z")]
    values = [_field_value(row, index) for index in indices]
    present = [value is not None for value in values]
    return ([float(value) for value in values] if all(present) else None), present


def _floatinginfo_summary(path: Path, max_rows: int) -> Dict[str, Any]:
    """Decode a bounded semicolon prefix with exact unit-bearing aliases."""
    summary: Dict[str, Any] = {
        "path": str(path),
        "delimiter": ";",
        "decoder": "explicit_semicolon_alias_fix_061",
        "header_normalization": "lowercase and remove punctuation/whitespace",
        "alias_revision": "unit-bearing normalized fields: fomegaxrads, fvelxms, centerxm and y/z siblings",
        "read_policy": "bounded prefix only; no full CSV materialisation",
        "max_rows": int(max_rows),
    }
    if not path.exists():
        summary.update({"status": "unavailable", "error": "file does not exist"})
        return summary
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            raw_header = handle.readline()
            if not raw_header:
                summary.update({"status": "empty"})
                return summary
            headers = next(csv.reader([raw_header], delimiter=";"))
            reader = csv.reader(handle, delimiter=";")
            rows: List[List[str]] = []
            for row_index, row in enumerate(reader):
                if row_index >= max_rows:
                    break
                rows.append(row)
    except OSError as exc:
        summary.update({"status": "unavailable", "error": str(exc)})
        return summary
    summary["header_columns"] = headers
    summary["normalized_headers"] = [PREVIOUS._normalise(header) for header in headers]
    summary["rows_examined"] = len(rows)
    if not rows:
        summary["status"] = "header_only"
        return summary

    time_aliases = ("time", "times", "t", "timestamp", "time_s", "f.time")
    omega_aliases = {
        "x": ("fomega.x", "fomegaxrads", "fomegax", "omega.x", "omegax", "angularvelocityx", "angvelx", "wx"),
        "y": ("fomega.y", "fomegayrads", "fomegay", "omega.y", "omegay", "angularvelocityy", "angvely", "wy"),
        "z": ("fomega.z", "fomegazrads", "fomegaz", "omega.z", "omegaz", "angularvelocityz", "angvelz", "wz"),
    }
    velocity_aliases = {
        "x": ("fvel.x", "fvelxms", "fvelx", "fvelocityx", "velocityx", "velx", "vcmx"),
        "y": ("fvel.y", "fvelyms", "fvely", "fvelocityy", "velocityy", "vely", "vcmy"),
        "z": ("fvel.z", "fvelzms", "fvelz", "fvelocityz", "velocityz", "velz", "vcmz"),
    }
    center_aliases = {
        "x": ("fcenter.x", "centerxm", "fcenterx", "center.x", "centerx", "fpos.x", "fposx"),
        "y": ("fcenter.y", "centerym", "fcentery", "center.y", "centery", "fpos.y", "fposy"),
        "z": ("fcenter.z", "centerzm", "fcenterz", "center.z", "centerz", "fpos.z", "fposz"),
    }
    time_index = _field_index(headers, time_aliases)
    parsed_times = [_field_value(row, time_index) for row in rows]
    timed = [(index, value) for index, value in enumerate(parsed_times) if value is not None]
    if timed:
        zero_index = min(timed, key=lambda item: abs(float(item[1])))[0]
        positive = [item for item in timed if float(item[1]) > 1.0e-12]
        first_positive_index = min(positive, key=lambda item: float(item[1]))[0] if positive else None
    else:
        zero_index = 0
        first_positive_index = 1 if len(rows) > 1 else None

    def selected_record(index: Optional[int], role: str) -> Dict[str, Any]:
        if index is None:
            return {"role": role, "status": "unresolved", "reason": "no bounded row selected"}
        row = rows[index]
        omega, omega_presence = _vector_from_row(row, headers, omega_aliases)
        velocity, velocity_presence = _vector_from_row(row, headers, velocity_aliases)
        center, center_presence = _vector_from_row(row, headers, center_aliases)
        if omega is not None and velocity is not None and center is not None:
            status = "ok"
        elif any(omega_presence) or any(velocity_presence) or any(center_presence):
            status = "partial"
        else:
            status = "unresolved"
        return {
            "role": role,
            "row_index_in_bounded_data": int(index),
            "time_s": parsed_times[index],
            "omega_rad_s": omega,
            "omega_field_presence": omega_presence,
            "linear_velocity_m_per_s": velocity,
            "linear_velocity_field_presence": velocity_presence,
            "center_m": center,
            "center_field_presence": center_presence,
            "status": status,
            "raw_row_written": False,
        }

    summary["selected_rows"] = {
        "frame_zero": selected_record(zero_index, "closest_to_time_zero"),
        "first_positive_saved": selected_record(first_positive_index, "first_positive_saved_time"),
    }
    selected_statuses = [item["status"] for item in summary["selected_rows"].values()]
    if selected_statuses and all(status == "ok" for status in selected_statuses):
        summary["status"] = "ok"
    elif any(status in {"ok", "partial"} for status in selected_statuses):
        summary["status"] = "partial"
    else:
        summary["status"] = "unresolved"
    summary["interpretation"] = "FloatingInfo corroboration only; H5 Type2 fit is primary and unresolved fields remain unresolved"
    return summary


# The previous worker's _run resolves _floatinginfo_summary in its own module
# namespace. Replacing that binding keeps every H5/XML bound and audit rule
# immutable while correcting only this decoder.
PREVIOUS._floatinginfo_summary = _floatinginfo_summary
PREVIOUS.SCHEMA = SCHEMA


def main(argv: Optional[Sequence[str]] = None) -> int:
    return int(PREVIOUS.main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
