#!/usr/bin/env python3
"""Run the M4 bundle validator with source paths masked in bubblewrap.

The child imports the validator from ``bundle/runtime`` and receives only the
relocated bundle plus the selected Python installation.  No M2 module, native
decoder, solver tree, or raw source directory is an input to the child.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any


SCHEMA = "ds-data-02.m4.isolated-validation-wrapper.v1"
DEFAULT_DENIED_PATHS = (
    "/home/jade/Projects/DualSPHysics-data/ds-data-02",
    "/home/jade/.codex/worktrees/ds-data-02-stage2",
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab",
    "/home/jade/Projects/DualSPHysics-data/CURRENT",
)
DEFAULT_MASK_PATHS = (
    "/home/jade/Projects/DualSPHysics-data",
    "/home/jade/.codex/worktrees",
    "/home/jade/Projects/DualSPHysics",
)


class IsolationError(RuntimeError):
    pass


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise IsolationError(f"refusing to overwrite validation report: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    if partial.exists() or partial.is_symlink():
        raise IsolationError(f"stale partial validation report exists: {partial}")
    with partial.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(partial, path)


def _run(args: argparse.Namespace) -> dict[str, Any]:
    if shutil.which("bwrap") is None:
        raise IsolationError("bubblewrap (bwrap) is required for isolated M4 validation")
    bundle_root = args.bundle_root.resolve()
    python_path = args.python.absolute()
    if bundle_root.is_symlink() or not bundle_root.is_dir():
        raise IsolationError(f"bundle root is not a regular directory: {bundle_root}")
    # Keep the venv's symlink layout intact; the mounted parent provides the
    # interpreter and site-packages exactly as the M2 wrapper does.
    if not python_path.is_file():
        raise IsolationError(f"Python runtime is not a regular file: {python_path}")
    runtime_adapter = bundle_root / "runtime" / "m4_portable_adapter.py"
    if runtime_adapter.is_symlink() or not runtime_adapter.is_file():
        raise IsolationError(f"bundled M4 adapter is missing: {runtime_adapter}")
    denied_paths = tuple(Path(value) for value in (args.denied_path or DEFAULT_DENIED_PATHS))
    mask_paths = tuple(Path(value) for value in DEFAULT_MASK_PATHS)
    command = [
        "bwrap",
        "--die-with-parent",
        "--new-session",
        "--unshare-user-try",
        "--unshare-pid",
        "--unshare-net",
        "--ro-bind",
        "/",
        "/",
        "--ro-bind",
        str(bundle_root),
        "/srv",
        "--ro-bind",
        str(python_path.parent.parent),
        "/run",
    ]
    for masked in mask_paths:
        command.extend(("--tmpfs", str(masked)))
    command.extend(
        (
            "--clearenv",
            "--setenv",
            "PATH",
            "/run/bin:/usr/bin:/bin",
            "--setenv",
            "PYTHONNOUSERSITE",
            "1",
            "/run/bin/python",
            "/srv/runtime/m4_portable_adapter.py",
            "validate",
            "--bundle-root",
            "/srv",
        )
    )
    for denied in denied_paths:
        command.extend(("--probe-denied-path", str(denied)))
    started = time.monotonic()
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=args.max_wall_seconds,
    )
    elapsed = time.monotonic() - started
    if completed.returncode != 0:
        raise IsolationError(
            f"isolated M4 validation failed with exit {completed.returncode}: "
            f"{completed.stderr.strip()[-2000:]}"
        )
    try:
        validation = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise IsolationError("isolated M4 validator did not emit JSON") from exc
    if validation.get("portable") is not True or validation.get("source_paths_redacted") is not True:
        raise IsolationError("isolated M4 validator did not prove portability")
    return {
        "schema": SCHEMA,
        "status": "completed",
        "elapsed_seconds": elapsed,
        "namespace": {
            "backend": "bubblewrap",
            "bundle_mount": "/srv",
            "runtime_from_bundle": "/srv/runtime",
            "python_mount": "/run",
            "network_unshared": True,
            "masked_paths": [str(path) for path in mask_paths],
            "denied_paths": [str(path) for path in denied_paths],
            "denied_probes_passed": True,
        },
        "validation": validation,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-root", required=True, type=Path)
    parser.add_argument("--python", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--max-wall-seconds", type=float, default=1800.0)
    parser.add_argument("--denied-path", action="append", default=[])
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        _write_json(args.output, _run(args))
    except (OSError, subprocess.SubprocessError, IsolationError, ValueError) as exc:
        print(f"m4-isolated-validation: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
