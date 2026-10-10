#!/usr/bin/env python3
"""Independent small-report verifier for the canonical65 V10 execution.

The executor owns reservation and child execution.  This entry point is kept
as a separate, hash-bound source so a caller can verify a completed receipt,
worker summary, and native report without importing or rerunning the worker.
It performs no scientific payload reads beyond the bounded native report and
typed-output stat/hash checks already required by the executor contract.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
from typing import Sequence


SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
EXECUTOR_PATH = SCRIPT_DIR / "ds_data02_stage2_f2_canonical65_executor_v1.py"
SPEC = importlib.util.spec_from_file_location("ds02_canonical65_executor_for_verifier", EXECUTOR_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load canonical65 executor: {EXECUTOR_PATH}")
EXECUTOR = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = EXECUTOR
SPEC.loader.exec_module(EXECUTOR)


def verify(*, runtime_request: Path | str, runtime_receipt: Path | str,
           summary: Path | str, output: Path | str) -> dict[str, object]:
    """Verify one completed canonical65 attempt through the executor contract."""
    return EXECUTOR.verify(runtime_request=runtime_request,
                           runtime_receipt=runtime_receipt,
                           summary_path=summary, output=output)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-request", type=Path, required=True)
    parser.add_argument("--runtime-receipt", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = verify(runtime_request=args.runtime_request,
                        runtime_receipt=args.runtime_receipt,
                        summary=args.summary, output=args.output)
    except (EXECUTOR.Canonical65Error, OSError, ValueError, TypeError,
            json.JSONDecodeError) as error:
        print(json.dumps({"schema": EXECUTOR.VERIFY_SCHEMA,
                          "status": "REJECTED", "error": str(error)},
                         sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
