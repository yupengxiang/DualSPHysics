#!/usr/bin/env python3
"""Prepare the ROOT139 manifest, then exec the existing observer enforcer.

The ROOT144 request passed the producer wrapper directly as
``--expected-source-manifest``.  This runner is a forward-only bridge: it
adapts the already hashed ROOT139 JSON into the exact v1 manifest accepted by
the consumed enforcer, then replaces itself with that enforcer.  The adapter
reads only the small snapshot JSON; the enforcer remains the component that
hashes and decodes the ten selected BI4 files after the parent guard.

The ``--enforcer-argv`` remainder is intentionally explicit.  The runner
requires its expected-manifest argument to point at the manifest it just
created, preventing a request from silently adapting one source and checking
another.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any

import stage2_f3_s2_native_source_manifest_adapter_v1 as adapter


SCHEMA = "ds02.stage2.f3-s2.native-header-root147-runner.v1"


def _enforcer_manifest_argument(argv: list[str], expected: Path) -> None:
    try:
        index = argv.index("--expected-source-manifest")
    except ValueError as exc:
        raise ValueError("enforcer argv lacks --expected-source-manifest") from exc
    if index + 1 >= len(argv):
        raise ValueError("--expected-source-manifest has no path")
    if argv[index + 1] != str(expected):
        raise ValueError(
            "enforcer expected-manifest path is not the adapter output: "
            f"{argv[index + 1]!r} != {str(expected)!r}"
        )


def exec_enforcer(args: argparse.Namespace) -> None:
    manifest = args.manifest_output.expanduser().resolve()
    enforcer = args.enforcer.expanduser().resolve()
    if enforcer.is_symlink() or not enforcer.is_file():
        raise FileNotFoundError(f"enforcer is missing or symlinked: {enforcer}")
    enforcer_argv = list(args.enforcer_argv or [])
    if enforcer_argv and enforcer_argv[0] == "--":
        enforcer_argv.pop(0)
    _enforcer_manifest_argument(enforcer_argv, manifest)
    value = adapter.build_manifest(
        args.snapshot,
        expected_snapshot_sha=args.expected_snapshot_sha,
        strict_actual_identity=True,
    )
    adapter.write_new(manifest, value)
    # The request's first argv is the literal venv Python.  Replacing this
    # process avoids a second unmanaged child and preserves the parent's
    # cancellation/lease accounting around the existing enforcer.
    os.execv(sys.executable, [sys.executable, str(enforcer), *enforcer_argv])


def self_test() -> dict[str, Any]:
    """Check command-path binding without invoking the enforcer or BI4."""

    expected = Path("{attempt_root}/source-manifest/root139-compatible-manifest-v1.json")
    good = ["--expected-source-manifest", str(expected), "--frames", "0"]
    _enforcer_manifest_argument(good, expected)
    try:
        _enforcer_manifest_argument(
            ["--expected-source-manifest", "{attempt_root}/wrong-manifest.json"], expected
        )
    except ValueError:
        mismatch_rejected = True
    else:
        mismatch_rejected = False
    assert mismatch_rejected
    return {
        "status": "PASS",
        "schema": SCHEMA,
        "adapter_executes_before_enforcer": True,
        "manifest_path_binding_checked": True,
        "wrong_manifest_path_rejected": mismatch_rejected,
        "native_payload_read": False,
        "solver_launch": False,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--snapshot", type=Path, default=adapter.SNAPSHOT)
    parser.add_argument("--manifest-output", type=Path)
    parser.add_argument("--expected-snapshot-sha", default=adapter.SNAPSHOT_SHA256)
    parser.add_argument("--enforcer", type=Path)
    parser.add_argument("--enforcer-argv", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.self_test:
        import json

        print(json.dumps(self_test(), ensure_ascii=False, indent=2))
        return 0
    required = (args.manifest_output, args.enforcer, args.enforcer_argv)
    if any(value is None for value in required):
        parser.error("--manifest-output, --enforcer, and --enforcer-argv are required unless --self-test is used")
    exec_enforcer(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
