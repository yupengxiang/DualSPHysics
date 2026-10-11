#!/usr/bin/env python3
"""Run portable bundle validation in a source-denying bubblewrap namespace.

The validation process receives only a read-only bind of the relocated bundle
and the code worktree.  The original source roots are over-mounted with empty
tmpfs mounts, and their exact paths are probed from inside the namespace.  A
successful report therefore records a real access denial rather than merely a
different working directory or a hash comparison.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


SCHEMA = "ds-data-02.m2.isolated-validation-wrapper.v1"
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
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise IsolationError(f"refusing to overwrite validation report: {path}")
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
    if not shutil_which("bwrap"):
        raise IsolationError("bubblewrap (bwrap) is required for source-denying validation")
    bundle_root = Path(args.bundle_root).resolve()
    worktree_root = Path(args.worktree_root).resolve()
    # Keep the venv symlink layout intact: resolving ``.venv/bin/python`` to
    # /usr/bin/python would bind the system tree at /run and lose site-packages.
    python_path = Path(args.python).absolute()
    if not bundle_root.is_dir() or bundle_root.is_symlink():
        raise IsolationError(f"bundle root is not a regular directory: {bundle_root}")
    if not worktree_root.is_dir() or worktree_root.is_symlink():
        raise IsolationError(f"worktree root is not a regular directory: {worktree_root}")
    if not python_path.is_file():
        raise IsolationError(f"Python runtime is not a regular file: {python_path}")
    portable_script = worktree_root / "lagrangian-fluid-lab/campaigns/ds-data-02/upstream-first/m2/portable_bundle.py"
    if not portable_script.is_file():
        raise IsolationError(f"portable validator is missing: {portable_script}")
    denied_paths = tuple(Path(value) for value in (args.denied_path or DEFAULT_DENIED_PATHS))
    mask_paths = tuple(Path(value) for value in DEFAULT_MASK_PATHS)
    # /mnt, /srv, and /run exist in the base image, so bwrap can bind over
    # them without creating writable host-side staging directories.
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
        str(worktree_root),
        "/mnt",
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
            "/mnt/lagrangian-fluid-lab/campaigns/ds-data-02/upstream-first/m2/portable_bundle.py",
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
            f"isolated validation failed with exit {completed.returncode}: "
            f"{completed.stderr.strip()[-2000:]}"
        )
    try:
        validation = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise IsolationError("isolated validator did not emit JSON") from exc
    if not validation.get("portable") or not validation.get("denied_probe_passed"):
        raise IsolationError("isolated validator did not prove portability and denial")
    result = {
        "schema": SCHEMA,
        "status": "completed",
        "elapsed_seconds": elapsed,
        "namespace": {
            "backend": "bubblewrap",
            "bundle_mount": "/srv",
            "worktree_mount": "/mnt",
            "python_mount": "/run",
            "network_unshared": True,
            "masked_paths": [str(path) for path in mask_paths],
            "denied_paths": [str(path) for path in denied_paths],
            "denied_probes_passed": True,
        },
        "validation": validation,
    }
    return result


def shutil_which(command: str) -> str | None:
    # Keep this wrapper standard-library-only and avoid importing the larger
    # data-product module before entering the isolated process.
    for directory in os.environ.get("PATH", "/usr/bin:/bin").split(os.pathsep):
        candidate = Path(directory) / command
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-root", required=True, type=Path)
    parser.add_argument("--worktree-root", required=True, type=Path)
    parser.add_argument("--python", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--max-wall-seconds", type=float, default=1800)
    parser.add_argument("--denied-path", action="append", default=[])
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        _write_json(args.output, _run(args))
    except (OSError, subprocess.SubprocessError, IsolationError, ValueError) as exc:
        print(f"isolated-validation: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
