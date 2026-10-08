#!/usr/bin/env python3
"""Keep the typed evaluator's direct-parent contract under ``strace``.

``strace -- python evaluator`` makes the evaluator's direct parent the
tracer, while the old parent passed its own PID.  That is a real ownership
failure, not a reason to disable the parent check.  This tiny bound shim is
the traced child: it execs the evaluator and passes the actual direct parent
(the strace process) as the parent PID.  The literal virtual-environment
path is preserved in the exec argv.  It does not read HDF5, BI4, or any
scientific payload.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Sequence


class ChildShimError(RuntimeError):
    pass


def run(*, evaluator: Path, request: Path, output: Path, python: Path,
        max_wall_seconds: float) -> None:
    evaluator = Path(evaluator).expanduser()
    request = Path(request).expanduser()
    output = Path(output).expanduser()
    python = Path(python).expanduser()
    if not evaluator.is_file() or evaluator.is_symlink():
        raise ChildShimError(f"evaluator is not a regular file: {evaluator}")
    if not request.is_file() or request.is_symlink():
        raise ChildShimError(f"request is not a regular file: {request}")
    if not python.is_file() or not (python.stat().st_mode & 0o111):
        raise ChildShimError(f"literal Python executable is missing: {python}")
    # Under -ff strace this process is the direct child of strace.  After
    # execve the evaluator keeps that same parent, so its own direct-parent
    # check can remain strict.
    direct_parent = os.getppid()
    argv = [str(python), "-B", "-I", str(evaluator), "run",
            "--request", str(request), "--output", str(output),
            "--parent-pid", str(direct_parent),
            "--max-wall-seconds", str(float(max_wall_seconds))]
    os.execv(str(python), argv)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", nargs="?")
    parser.add_argument("--evaluator", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--max-wall-seconds", type=float, required=True)
    args = parser.parse_args(argv)
    try:
        run(evaluator=args.evaluator, request=args.request, output=args.output,
            python=args.python, max_wall_seconds=args.max_wall_seconds)
    except (ChildShimError, OSError, ValueError, TypeError) as error:
        print(f"typed-only child shim: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
