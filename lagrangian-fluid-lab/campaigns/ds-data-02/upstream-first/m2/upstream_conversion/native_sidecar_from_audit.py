#!/usr/bin/env python3
"""Project an existing official native-motive audit into the M4 sidecar.

The source audit is expected to have been produced by the already checked-in
official PartVTKOut/RunPARTs audit utility.  It accepts both the historical
DP0025 audit schema and the generalized M4
``ds-data-02.upstream-first.f1-native-integrity.v1`` evidence.  This adapter
reads only the small JSON result; it does not open PartOut, BI4, HDF5, or CSV
payloads and does not decode a native format.  The explicit zone argument
binds the audit's Idp-only rows to the direct converter's ``(Zone,Idp)`` key
(the official single-piece route uses zone 0).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping


SCHEMA = "ds-data-02.native-lifecycle-records.v1"
NATIVE_INTEGRITY_SCHEMA = "ds-data-02.upstream-first.f1-native-integrity.v1"


class NativeSidecarError(ValueError):
    """Raised when an existing native audit cannot be projected safely."""


def _regular(path: Path, label: str) -> Path:
    if not path.is_file() or path.is_symlink():
        raise NativeSidecarError(f"{label} is not a regular file: {path}")
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _number(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise NativeSidecarError(f"{label} is not numeric: {value!r}") from exc
    return result


def project(
    audit_path: Path,
    output: Path,
    *,
    zone: int,
    time_start_s: float,
    time_end_s: float,
) -> dict[str, Any]:
    _regular(audit_path, "native motive audit")
    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise NativeSidecarError(f"native motive audit is not valid JSON: {audit_path}") from exc
    if not isinstance(audit, Mapping):
        raise NativeSidecarError("native motive audit must be an object")
    status = str(audit.get("status", "")).upper()
    completed_legacy = status in {
        "COMPLETED_NATIVE_MOTIVE_AUDIT",
        "COMPLETED_NATIVE_MOTIVE_AUDIT_V2",
    }
    completed_general = (
        audit.get("schema") == NATIVE_INTEGRITY_SCHEMA and status == "VERIFIED"
    )
    if not (completed_legacy or completed_general):
        raise NativeSidecarError("native motive audit is not a completed source-closed result")
    rows = audit.get("native_rows")
    brackets = audit.get("saved_record_time_brackets_s")
    if not isinstance(rows, list) or not isinstance(brackets, Mapping):
        raise NativeSidecarError("native motive audit lacks native_rows or saved time brackets")
    if time_end_s <= time_start_s:
        raise NativeSidecarError("native sidecar event window is empty")
    records: list[dict[str, Any]] = []
    seen: set[int] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise NativeSidecarError(f"native row {index} is not an object")
        try:
            idp = int(row["idp"])
        except (KeyError, TypeError, ValueError) as exc:
            raise NativeSidecarError(f"native row {index} lacks integer idp") from exc
        if idp in seen:
            raise NativeSidecarError(f"native audit duplicates Idp {idp}")
        seen.add(idp)
        bracket = brackets.get(str(idp))
        if not isinstance(bracket, Mapping):
            raise NativeSidecarError(f"native audit lacks saved time bracket for Idp {idp}")
        time_s = _number(bracket.get("saved_time_s"), f"Idp {idp} saved_time_s")
        if not time_start_s - 1.0e-9 <= time_s <= time_end_s + 1.0e-9:
            continue
        reason = row.get("motive", row.get("reason"))
        if not isinstance(reason, str) or not reason.strip():
            raise NativeSidecarError(f"native row {index} lacks motive/reason")
        records.append(
            {
                "time_s": time_s,
                "particle_id": idp,
                "particle_zone": int(zone),
                "reason": reason,
                "motive_code": row.get("motive_code"),
                "native_part_out": bracket.get("part_out", row.get("part_out")),
                "valid_after": False,
                "censoring": "native numerical-node exclusion at saved PartOut time; physical fate UNKNOWN",
            }
        )
    source_bindings = {}
    for key, value in (audit.get("source_bindings") or {}).items():
        if isinstance(value, Mapping) and isinstance(value.get("sha256"), str):
            source_bindings[str(key)] = {
                "sha256": value["sha256"],
                "bytes": value.get("bytes"),
            }
    result = {
        "schema": SCHEMA,
        "source": {
            "audit": {
                "sha256": _sha256(audit_path),
                "bytes": audit_path.stat().st_size,
                "schema": audit.get("schema"),
            },
            "source_bindings": source_bindings,
            "partout": "bound through the source-closed official audit",
            "runparts": "bound through the source-closed official audit",
        },
        "identity_key": "(Zone,Idp)",
        "zone_binding": {
            "zone": int(zone),
            "reason": "official single-piece mDBC route; converter rejects multi-piece output",
        },
        "event_window_s": [time_start_s, time_end_s],
        "records": records,
        "fate_inference": "forbidden",
        "claim_boundary": {
            "native_reason": "source-bound motive/reason only",
            "physical_fate": "UNKNOWN",
            "continuous_event_time": "UNKNOWN; saved-record time only",
        },
    }
    if output.exists() or output.is_symlink():
        raise NativeSidecarError(f"refusing to overwrite {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--zone", required=True, type=int)
    parser.add_argument("--event-start-s", required=True, type=float)
    parser.add_argument("--event-end-s", required=True, type=float)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = project(
            args.audit,
            args.output,
            zone=args.zone,
            time_start_s=args.event_start_s,
            time_end_s=args.event_end_s,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (OSError, NativeSidecarError) as exc:
        print(f"native-sidecar: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
