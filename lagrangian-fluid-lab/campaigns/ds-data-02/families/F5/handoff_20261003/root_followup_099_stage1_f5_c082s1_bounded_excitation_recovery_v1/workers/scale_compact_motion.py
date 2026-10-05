#!/usr/bin/env python3
"""Root-registered, metadata-producing transform for the two bounded F5 controls.

This worker is intentionally not run during source preparation.  At execution time it
reads only the registered two-column compact-packet motion table, validates its time
axis, scales the prescribed x column by one of the pre-registered factors 0.8 or 1.2,
and writes a fresh table plus a receipt.  It does not touch BI4/CSV/H5/VTK data or
solver state.  The input SHA is computed by the registered CPU worker, never by this
source-only package.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from decimal import Decimal, InvalidOperation
from pathlib import Path

ALLOWED_SCALES = {Decimal("0.8"), Decimal("1.2")}
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

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-motion", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--receipt", type=Path, required=True)
    ap.add_argument("--scale", required=True)
    args = ap.parse_args()
    try:
        scale = Decimal(args.scale)
    except InvalidOperation as exc:
        raise SystemExit("scale must be decimal 0.8 or 1.2") from exc
    if scale not in ALLOWED_SCALES:
        raise SystemExit("scale is outside the frozen F5 legal candidate set")
    rows = read_motion(args.base_motion)
    args.output.parent.mkdir(parents=True, exist_ok=False)
    output_lines = []
    for original_time, _, x in rows:
        output_lines.append(f"{original_time}\t{format(x * scale, 'f')}")
    payload = ("\n".join(output_lines) + "\n").encode("utf-8")
    tmp = args.output.with_name(args.output.name + ".tmp")
    tmp.write_bytes(payload)
    os.replace(tmp, args.output)
    report = {
        "schema": "ds02.f5.c082s1.motion-transform-receipt.fresh099.v1",
        "status": "completed",
        "base_motion": str(args.base_motion),
        "base_motion_sha256": digest(args.base_motion),
        "output_motion": str(args.output),
        "output_motion_sha256": digest(args.output),
        "scale": str(scale),
        "rows": len(rows),
        "time_start_s": float(rows[0][1]),
        "time_end_s": float(rows[-1][1]),
        "source_agent_did_not_run_worker": False,
        "solver_started": False,
    }
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
