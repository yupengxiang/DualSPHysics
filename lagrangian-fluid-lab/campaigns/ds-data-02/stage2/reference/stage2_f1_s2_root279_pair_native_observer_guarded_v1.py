#!/usr/bin/env python3
"""Guard and run the ROOT279 F1-S2 matched native observer.

This is an additive, parameterized wrapper around the consumed ROOT204/V4
guard.  ROOT279 has ten selected ``Part_*.bi4`` files (five from each of the
same-CFL and half-CFL members), whereas the older wrapper is deliberately
fixed at 25 files.  The wrapper changes only that count and result schema;
all source pre/post SHA/stat, bounded-child, cancellation, log, and scratch
checks remain in the immutable V4 implementation.

The parent must supply concrete SHA/stat records after reservation.  This
wrapper never turns ``PARENT_AFTER_RESERVATION_REQUIRED`` into a guessed
hash, and it does not read production files during import or self-test.
"""

from __future__ import annotations

import argparse
import importlib.util
import tempfile
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
V4_PATH = HERE / "stage2_f1_native_selected_observer_guarded_v4.py"
V4_SPEC = importlib.util.spec_from_file_location("stage2_root279_guarded_v4", V4_PATH)
if V4_SPEC is None or V4_SPEC.loader is None:  # pragma: no cover - import failure
    raise RuntimeError(f"cannot load ROOT204 V4 wrapper: {V4_PATH}")
V4 = importlib.util.module_from_spec(V4_SPEC)
V4_SPEC.loader.exec_module(V4)


SCHEMA = "ds02.stage2.f1-s2.root279-native-observer-guarded.v1"
EXPECTED_DEFERRED_COUNT = 10


def _configure() -> None:
    # The V4 implementation consults these globals in _load_deferred and in
    # its result accounting.  No V4 source is modified; the additive wrapper
    # supplies the ROOT279 cardinality and schema at runtime.
    V4.EXPECTED_DEFERRED_COUNT = EXPECTED_DEFERRED_COUNT
    V4.SCHEMA = SCHEMA


def self_test() -> dict[str, Any]:
    _configure()
    # Invoke the inherited guard directly so the fixture child does not
    # re-import the V4 module with its historical 25-file default.  This
    # exercises the actual ten-file pre/post guard and V1 child boundary.
    with tempfile.TemporaryDirectory(prefix="root279-guard-selftest-") as directory:
        root = Path(directory)
        manifest, worker = V4._fixture_manifest(root / "good")
        output = root / "good" / "attempt" / "observer" / "result.json"
        args = argparse.Namespace(
            manifest=manifest,
            attempt_root=root / "good" / "attempt",
            output=output,
            log_path=root / "good" / "attempt" / "observer" / "child.log",
            v1_worker=worker,
            python=Path(V4.PYTHON),
            cwd=root,
            max_scratch_bytes=V4.SCRATCH_CAP_BYTES,
            max_log_bytes=V4.DEFAULT_MAX_LOG_BYTES,
            timeout_seconds=10.0,
        )
        result = V4.run_guard(args)
        if not result.get("status", "").startswith("PASS"):
            raise RuntimeError(f"ROOT279 ten-file guard fixture failed: {result}")
        if int(result.get("scope", {}).get("deferred_native_count", -1)) != EXPECTED_DEFERRED_COUNT:
            raise RuntimeError("ROOT279 fixture did not exercise ten deferred files")
    return {
        "status": "PASS",
        "schema": SCHEMA,
        "expected_deferred_count": EXPECTED_DEFERRED_COUNT,
        "guard_scope": result.get("scope"),
        "production_payload_read": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--attempt-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--log-path", type=Path)
    parser.add_argument("--v1-worker", type=Path, default=V4.V1_WORKER)
    parser.add_argument("--python", type=Path, default=V4.PYTHON)
    parser.add_argument("--cwd", type=Path, default=V4.V1_WORKER.parents[5])
    parser.add_argument("--max-scratch-bytes", type=int, default=V4.SCRATCH_CAP_BYTES)
    parser.add_argument("--max-log-bytes", type=int, default=V4.DEFAULT_MAX_LOG_BYTES)
    parser.add_argument("--timeout-seconds", type=float, default=V4.DEFAULT_TIMEOUT_SECONDS)
    args = parser.parse_args()
    _configure()
    if args.self_test:
        result = self_test()
        import json
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    if args.manifest is None or args.attempt_root is None or args.output is None:
        parser.error("--manifest, --attempt-root and --output are required for --run")
    if args.log_path is None:
        args.log_path = args.attempt_root / "observer" / "f1_s2_root279_native_observer_child.log"
    if args.max_scratch_bytes > V4.SCRATCH_CAP_BYTES or args.max_scratch_bytes <= 0:
        parser.error("--max-scratch-bytes must be in (0, 256MiB]")
    if args.max_log_bytes <= 0 or args.max_log_bytes > V4.MAX_LOG_BYTES:
        parser.error("--max-log-bytes must be in (0, 8MiB]")
    try:
        result = V4.run_guard(args)
    except Exception as exc:
        import json
        print(json.dumps({"schema": SCHEMA, "status": "FAILED_WRAPPER_BEFORE_OUTPUT", "error": {"type": type(exc).__name__, "message": str(exc)}}, sort_keys=True))
        return 2
    import json
    print(json.dumps({"schema": SCHEMA, "status": result["status"], "output": str(args.output.expanduser().resolve())}, sort_keys=True))
    return 0 if result["status"].startswith("PASS") else 2


if __name__ == "__main__":
    raise SystemExit(main())
