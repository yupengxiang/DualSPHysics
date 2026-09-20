#!/usr/bin/env python3
"""Read-only cadence parser for a completed F5 solver ``Run.out``.

The protected runtime worker predates the DualSPHysics log format used by the
anchor.  Its ``TimeOut=`` lookup cannot see the solver's actual output cadence,
which is recorded as ``Output.....: ... dt:...``.  This follow-up parser is
deliberately independent of that hash-bound worker: it reads one closed log,
does not start a solver, and does not write queue, job, review, or audit state.

After the anchor exits, run for example::

    python scripts/f5_wave_runup_solver_anchor_cadence_parser_v1.py \
        --run-out campaigns/core-v1/runtime/attempts/<attempt>/product/solver/Run.out

The JSON result is a read-only reconciliation input for the post-run review.
It does not promote the anchor or award qualification/matrix credit.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
from typing import Any


_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_TIMEMAX = re.compile(rf"^\s*TimeMax\s*=\s*({_NUMBER})\s*$", re.MULTILINE)
_OUTPUT_DT = re.compile(
    rf"^\s*Output\.{{5,}}:\s*[^\n]*?\bdt\s*:\s*({_NUMBER})\s*$",
    re.MULTILINE,
)


def _finite(value: str) -> float | None:
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


def parse_run_out(path: Path) -> dict[str, Any]:
    """Parse registered ``TimeMax`` and native ``Output ... dt:`` records.

    The output cadence is taken from the solver's ``Output`` records.  A
    ``TimeOut=`` token by itself is intentionally ignored because it was the
    stale source of the runtime worker's false hard-gate failure.
    """

    path = Path(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    timemax_values = [value for raw in _TIMEMAX.findall(text) if (value := _finite(raw)) is not None]
    output_dt_values = [value for raw in _OUTPUT_DT.findall(text) if (value := _finite(raw)) is not None]
    unique_dt = sorted(set(output_dt_values))
    return {
        "path": str(path),
        "timemax_s": timemax_values[-1] if timemax_values else None,
        "timemax_values_s": timemax_values,
        "output_dt_values_s": unique_dt,
        "output_record_count": len(output_dt_values),
        "cadence_s": unique_dt[0] if len(unique_dt) == 1 else None,
        "native_output_records_present": bool(output_dt_values),
    }


def cadence_gate(parsed: dict[str, Any], *, expected_tmax_s: float, expected_dt_s: float) -> bool:
    """Return whether one unambiguous native cadence matches the contract."""

    timemax = parsed.get("timemax_s")
    cadence = parsed.get("cadence_s")
    return bool(
        isinstance(timemax, (int, float))
        and isinstance(cadence, (int, float))
        and math.isclose(float(timemax), expected_tmax_s, rel_tol=0.0, abs_tol=1e-9)
        and math.isclose(float(cadence), expected_dt_s, rel_tol=0.0, abs_tol=1e-9)
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-out", type=Path, required=True)
    parser.add_argument("--expected-tmax", type=float, default=16.0)
    parser.add_argument("--expected-output-dt", type=float, default=0.02)
    args = parser.parse_args()
    parsed = parse_run_out(args.run_out)
    result = {
        "schema": "core.f5.third_t1.solver_anchor_cadence_parser.v1",
        "read_only": True,
        "qualification_claim": "none",
        "matrix_credit": 0,
        "expected_tmax_s": args.expected_tmax,
        "expected_output_dt_s": args.expected_output_dt,
        "cadence_pass": cadence_gate(
            parsed,
            expected_tmax_s=args.expected_tmax,
            expected_dt_s=args.expected_output_dt,
        ),
        "run": parsed,
    }
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
    return 0 if result["cadence_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
