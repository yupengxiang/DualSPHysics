#!/usr/bin/env python3
"""Stream one completed F4 native output tree and register temporal anchors.

The worker is intentionally a low-storage provenance/temporal observer.  It
reads each immutable native ``Part_####.bi4`` byte stream once, records a
per-frame SHA-256 and the saved time from ``RunPARTs.csv``, and writes only a
small JSON sidecar plus per-frame digest records.  It does not decode BI4
fields, create HDF5, interpolate particle values, or infer a physical
observable.  Therefore field observables and scientific qualification remain
``UNKNOWN``.  A query is a frame-time bracket, never an extrapolation.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any


SCHEMA = "ds02.stage2.f4-canary-stream-observer.v1"
CHUNK = 1024 * 1024


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def record(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"required regular file is missing or symlinked: {path}")
    stat = path.stat()
    return {"path": str(path.resolve()), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def read_rows(path: Path) -> list[dict[str, str]]:
    lines = [line for line in path.read_text(encoding="utf-8").splitlines()
             if line.strip() and not line.startswith("#")]
    rows = [row for row in csv.DictReader(lines, delimiter=";") if row.get("Part", "").isdigit()]
    if not rows:
        raise ValueError(f"RunPARTs has no numeric rows: {path}")
    return rows


def bracket(times: list[float], query: float, parts: list[int]) -> dict[str, Any]:
    if not math.isfinite(query):
        raise ValueError(f"query time is not finite: {query}")
    if query < times[0] or query > times[-1]:
        return {"query_time_s": query, "status": "OUTSIDE_SAVED_WINDOW",
                "reason": "no extrapolation beyond actual native saved interval"}
    right = bisect.bisect_left(times, query)
    if right == 0:
        return {"query_time_s": query, "status": "EXACT_OR_LEFT",
                "lower_frame": parts[0], "upper_frame": parts[0],
                "lower_time_s": times[0], "upper_time_s": times[0]}
    if right == len(times):
        right -= 1
    if times[right] == query:
        return {"query_time_s": query, "status": "EXACT",
                "lower_frame": parts[right], "upper_frame": parts[right],
                "lower_time_s": times[right], "upper_time_s": times[right]}
    left = right - 1
    fraction = (query - times[left]) / (times[right] - times[left])
    return {"query_time_s": query, "status": "BRACKETED",
            "lower_frame": parts[left], "upper_frame": parts[right],
            "lower_time_s": times[left], "upper_time_s": times[right],
            "interpolation_fraction": fraction}


def atomic_write(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(f"refuse to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def run(args: argparse.Namespace) -> dict[str, Any]:
    raw_root = args.raw_root.resolve()
    runparts = args.runparts.resolve()
    runout = args.runout.resolve()
    if not raw_root.is_dir():
        raise ValueError(f"native raw root is missing: {raw_root}")
    rows = read_rows(runparts)
    frame_count = int(args.expected_frame_count)
    if len(rows) != frame_count:
        raise ValueError(f"RunPARTs rows {len(rows)} != expected {frame_count}")
    parts = [int(row["Part"]) for row in rows]
    if parts != list(range(frame_count)):
        raise ValueError("RunPARTs frame numbering is not contiguous from zero")
    times = [float(row["TimeStep [s]"]) for row in rows]
    if any(not math.isfinite(value) for value in times) or any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError("RunPARTs times are not finite and strictly increasing")
    if abs(times[-1] - args.expected_final_time_s) > args.final_time_tolerance_s:
        raise ValueError(f"actual final time {times[-1]} differs from expected {args.expected_final_time_s}")

    expected_bytes = int(args.expected_raw_bytes)
    expected_names = [f"Part_{index:04d}.bi4" for index in range(frame_count)]
    actual_paths = sorted(raw_root.glob("Part_*.bi4"), key=lambda path: path.name)
    if [path.name for path in actual_paths] != expected_names:
        raise ValueError("native Part file list differs from expected contiguous source")

    digest_lines: list[dict[str, Any]] = []
    source_bytes = 0
    combined = hashlib.sha256()
    for index, path in enumerate(actual_paths):
        if path.is_symlink():
            raise ValueError(f"source Part must not be a symlink: {path}")
        digest, size = sha256_file(path)
        source_bytes += size
        # The combined digest is order-bound and includes the file name, so
        # renaming or reordering a frame cannot silently preserve the sidecar.
        combined.update(path.name.encode("ascii"))
        combined.update(size.to_bytes(8, "big"))
        combined.update(bytes.fromhex(digest))
        digest_lines.append({
            "frame": index,
            "file": record(path),
            "sha256": digest,
            "saved_time_s": times[index],
        })
    if source_bytes != expected_bytes:
        raise ValueError(f"native Part bytes {source_bytes} != expected {expected_bytes}")

    queries = [float(value) for value in args.query_times]
    anchors = [bracket(times, query, parts) for query in queries]
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "PASS_NATIVE_STREAM_AND_TEMPORAL_BRACKETS",
        "source": {
            "raw_root": str(raw_root),
            "runparts": record(runparts),
            "runout": record(runout),
            "frame_count": frame_count,
            "raw_part_bytes": source_bytes,
            "combined_ordered_part_digest": combined.hexdigest(),
            "first_part": digest_lines[0],
            "last_part": digest_lines[-1],
        },
        "time_window": {
            "first_time_s": times[0],
            "last_time_s": times[-1],
            "actual_saved_frame_count": frame_count,
            "outside_nominal_endpoint_queries_are_rejected": True,
        },
        "anchors": anchors,
        "frame_digest_records": digest_lines,
        "field_observables": "UNKNOWN_NOT_DECODED_BY_THIS_WORKER",
        "typed_conversion": "NOT_PERFORMED",
        "hdf5_read": False,
        "scientific_qualification": "UNKNOWN",
        "source_deleted": False,
    }
    atomic_write(args.output.resolve(), result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--runparts", type=Path, required=True)
    parser.add_argument("--runout", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-frame-count", type=int, required=True)
    parser.add_argument("--expected-raw-bytes", type=int, required=True)
    parser.add_argument("--expected-final-time-s", type=float, required=True)
    parser.add_argument("--final-time-tolerance-s", type=float, default=1e-12)
    parser.add_argument("--query-times", type=float, nargs="+", required=True)
    args = parser.parse_args()
    result = run(args)
    print(json.dumps({"status": result["status"], "output": str(args.output.resolve()),
                      "frames": result["source"]["frame_count"],
                      "raw_part_bytes": result["source"]["raw_part_bytes"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
