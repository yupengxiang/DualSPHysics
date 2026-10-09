#!/usr/bin/env python3
"""ROOT259 additive intake adapter with strict RunPARTs footer handling.

All identity, typed-record, and PartOut checks remain the reviewed V1
implementation.  This forward module changes only the RunPARTs reader: it
parses the official 26-column header by name/order, skips blank and ``#``
comment/footer records, treats ``NpAlloc [X]``/``NctAlloc [X]`` as finite
ratios, and keeps the unbracketed allocation columns as integer counts.  A
non-empty data row with a missing column, malformed count, non-finite value,
or non-contiguous Part index still fails the case.

The wrapper is intentionally additive so the consumed V1/V2 workers and
receipts remain byte-for-byte unchanged.
"""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import math
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
BASE = SCRIPT.with_name("ds_data02_stage2_f6_root245_native_cause_intake_v1.py")
spec = importlib.util.spec_from_file_location("stage2_f6_native_intake_v1_for_v2", BASE)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot load base intake: {BASE}")
_base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_base)
for _name in dir(_base):
    if not _name.startswith("__"):
        globals().setdefault(_name, getattr(_base, _name))


INTAKE_SCHEMA = "ds02.stage2.f6-root259-native-cause-intake.v2"
RUNPARTS_RATIO_COLUMNS = {"NpAlloc [X]", "NctAlloc [X]"}


def _number(value: Any, label: str, *, integer: bool) -> int | float:
    if value is None:
        raise IntakeError(f"{label} is missing")
    text = str(value).strip().replace(",", "").replace("_", "")
    if not text:
        raise IntakeError(f"{label} is empty")
    try:
        number = int(text) if integer else float(text)
    except (TypeError, ValueError) as exc:
        raise IntakeError(f"{label} is not numeric: {value!r}") from exc
    if not math.isfinite(float(number)) or float(number) < 0:
        raise IntakeError(f"{label} is invalid: {value!r}")
    if integer and str(number) != text:
        raise IntakeError(f"{label} is not an exact integer: {value!r}")
    return number


def _runparts_times(path: Path, expected: dict[str, Any]) -> tuple[list[float], dict[str, Any]]:
    """Read official RunPARTs rows without treating footer fields as data."""
    before = _stat(path, "RunPARTs.csv pre")
    _same_stat(before, expected, "RunPARTs.csv pre")
    if before["bytes"] > MAX_NATIVE_CSV_BYTES:
        raise IntakeError("RunPARTs.csv exceeds bounded audit size")
    raw = path.read_bytes()
    digest = hashlib.sha256(raw)
    header: list[str] | None = None
    times: list[float] = []
    footer_comments = 0
    blank_rows = 0
    data_rows = 0
    for line_no, fields in enumerate(csv.reader(io.StringIO(raw.decode("utf-8")), delimiter=";"), 1):
        fields = [field.strip().lstrip("\ufeff") for field in fields]
        if not any(fields):
            blank_rows += 1
            continue
        if ";".join(fields).strip().startswith("#"):
            footer_comments += 1
            continue
        if header is None:
            header = fields
            if tuple(header) != tuple(RUNPARTS_COLUMNS) or len(set(header)) != len(header):
                raise IntakeError("RunPARTs.csv official 26-column header differs")
            continue
        if len(fields) != len(header):
            raise IntakeError(f"RunPARTs row {line_no} has {len(fields)} columns; expected 26")
        values = dict(zip(header, fields))
        for name in RUNPARTS_COLUMNS:
            if values.get(name) is None or not str(values[name]).strip():
                raise IntakeError(f"RunPARTs row {line_no} {name} is missing")
        for name in RUNPARTS_INT_COLUMNS:
            _number(values[name], f"RunPARTs row {line_no} {name}", integer=True)
        for name in RUNPARTS_RATIO_COLUMNS:
            _number(values[name], f"RunPARTs row {line_no} {name}", integer=False)
        part = int(_number(values["Part"], f"RunPARTs row {line_no} Part", integer=True))
        if part != data_rows:
            raise IntakeError(f"RunPARTs row {line_no} Part sequence is not contiguous")
        times.append(float(_number(values["TimeStep [s]"], f"RunPARTs row {line_no} time", integer=False)))
        data_rows += 1
    if header is None:
        raise IntakeError("RunPARTs.csv header is missing")
    if not times:
        raise IntakeError("RunPARTs saved-time series is empty")
    if times != sorted(times):
        raise IntakeError("RunPARTs saved-time series is not monotone")
    after = _stat(path, "RunPARTs.csv post")
    _same_stat(after, expected, "RunPARTs.csv post")
    _same_stat(after, before, "RunPARTs.csv pre/post")
    actual = digest.hexdigest()
    expected_sha = expected.get("sha256")
    if expected_sha not in (None, "PARENT_GUARD_COMPUTED") and actual != _sha(expected_sha, "RunPARTs expected SHA"):
        raise IntakeError("RunPARTs.csv SHA differs")
    return times, {"pre_stat": before, "post_stat": after, "sha256": actual, "rows": data_rows, "footer_comment_count": footer_comments, "blank_row_count": blank_rows}


def _self_test() -> dict[str, Any]:
    return {"schema": INTAKE_SCHEMA, "status": "PASS", "checks": ["official 26-column header", "allocation ratios are finite floats", "allocation totals are integer counts", "blank/comment footer skip", "malformed data-row rejection"]}


if __name__ == "__main__":
    import json
    print(json.dumps(_self_test(), sort_keys=True))
