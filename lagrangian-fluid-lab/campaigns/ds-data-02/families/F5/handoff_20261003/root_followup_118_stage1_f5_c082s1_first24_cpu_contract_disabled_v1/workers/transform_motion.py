#!/usr/bin/env python3
"""Root-registered future worker for the sixteen fresh117 motion controls.

At execution time this worker reads the registered two-column C082S1 motion
table, validates its 641-row 0..16 s contract, scales x by one bounded
amplitude and scales t about zero by one bounded time factor.  It writes a
fresh table and JSON receipt.  Source preparation never invokes this worker;
the worker is the only place that may read/hash the base or transformed DAT.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from decimal import Decimal, InvalidOperation
from pathlib import Path

ALLOWED_AMPLITUDE_SCALES = {Decimal("0.85"), Decimal("0.95"), Decimal("1.05"), Decimal("1.15")}
ALLOWED_TIME_SCALES = {Decimal("0.8"), Decimal("0.9"), Decimal("1.0"), Decimal("1.2")}
EXPECTED_ROWS = 641
START_S = Decimal("0")
END_S = Decimal("16")


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_motion(path: Path):
    rows = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        text = raw.strip()
        if not text or text.startswith("#") or text.startswith(";"):
            continue
        fields = text.replace(",", " ").split()
        if len(fields) != 2:
            raise ValueError(f"motion row {lineno} must have exactly two fields")
        try:
            t = Decimal(fields[0])
            x = Decimal(fields[1])
        except InvalidOperation as exc:
            raise ValueError(f"non-numeric motion row {lineno}") from exc
        if not t.is_finite() or not x.is_finite():
            raise ValueError(f"non-finite motion row {lineno}")
        rows.append((fields[0], t, x))
    if len(rows) != EXPECTED_ROWS:
        raise ValueError(f"expected {EXPECTED_ROWS} motion rows, got {len(rows)}")
    if rows[0][1] != START_S or rows[-1][1] != END_S:
        raise ValueError("motion time endpoints must be 0 and 16 seconds")
    if any(a[1] >= b[1] for a, b in zip(rows, rows[1:])):
        raise ValueError("motion time must be strictly increasing")
    return rows


def parse_scale(raw: str, allowed: set[Decimal], label: str) -> Decimal:
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise SystemExit(f"{label} must be a decimal in {sorted(map(str, allowed))}") from exc
    if value not in allowed:
        raise SystemExit(f"{label} is outside the frozen fresh117 candidate set")
    return value


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-motion", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--receipt", type=Path, required=True)
    ap.add_argument("--amplitude-scale", required=True)
    ap.add_argument("--time-scale", required=True)
    args = ap.parse_args()

    amplitude = parse_scale(args.amplitude_scale, ALLOWED_AMPLITUDE_SCALES, "amplitude-scale")
    time_scale = parse_scale(args.time_scale, ALLOWED_TIME_SCALES, "time-scale")
    rows = read_motion(args.base_motion)
    if args.output.exists():
        raise SystemExit(f"refusing to overwrite existing output: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=False)

    output_lines = []
    for _, t, x in rows:
        output_t = t * time_scale
        output_x = x * amplitude
        if not output_t.is_finite() or not output_x.is_finite():
            raise ValueError("non-finite transformed motion value")
        output_lines.append(f"{format(output_t, 'f')}\t{format(output_x, 'f')}")
    payload = ("\n".join(output_lines) + "\n").encode("utf-8")
    tmp = args.output.with_name(args.output.name + ".tmp")
    tmp.write_bytes(payload)
    os.replace(tmp, args.output)

    report = {
        "schema": "ds02.f5.c082s1.motion-transform-receipt.fresh117.v1",
        "status": "completed",
        "base_motion": str(args.base_motion),
        "base_motion_sha256": digest(args.base_motion),
        "output_motion": str(args.output),
        "output_motion_sha256": digest(args.output),
        "amplitude_scale": str(amplitude),
        "time_scale": str(time_scale),
        "rows": len(rows),
        "source_time_start_s": float(rows[0][1]),
        "source_time_end_s": float(rows[-1][1]),
        "output_time_start_s": float(rows[0][1] * time_scale),
        "output_time_end_s": float(rows[-1][1] * time_scale),
        "source_agent_did_not_run_worker": False,
        "solver_started": False,
    }
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
