#!/usr/bin/env python3
"""Run the V64 terminal adapter with an explicit copied-script import root.

The adapter imports the bound runtime-v6 module, which in turn imports the
runtime-v2 sibling.  A direct ``python -I adapter.py`` invocation does not
make that sibling directory an import root.  This tiny bootstrap makes the
runtime closure explicit without using ``PYTHONPATH`` or the original
worktree as an ambient fallback; all adapter arguments after ``--`` are
forwarded unchanged.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import runpy
import sys


class AdapterBootstrapError(ValueError):
    pass


def _regular(path: str, role: str) -> Path:
    target = Path(path).expanduser()
    if not target.is_absolute() or target.is_symlink() or not target.is_file():
        raise AdapterBootstrapError(f"{role} must be an absolute regular file: {target}")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scripts-root", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("remainder", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        scripts_root = args.scripts_root.expanduser()
        if not scripts_root.is_absolute() or scripts_root.is_symlink() or not scripts_root.is_dir():
            raise AdapterBootstrapError(f"scripts root must be an absolute regular directory: {scripts_root}")
        adapter = _regular(str(args.adapter), "terminal adapter")
        try:
            adapter.relative_to(scripts_root.resolve())
        except ValueError as error:
            raise AdapterBootstrapError("terminal adapter is outside the explicit scripts root") from error
        remainder = list(args.remainder)
        if remainder[:1] == ["--"]:
            remainder = remainder[1:]
        # The explicit sibling directory is the only added import root.  Do
        # not restore PYTHONPATH/PYTHONHOME or search the caller's worktree.
        os.environ.pop("PYTHONPATH", None)
        os.environ.pop("PYTHONHOME", None)
        sys.path.insert(0, str(scripts_root.resolve()))
        sys.argv = [str(adapter), *remainder]
        runpy.run_path(str(adapter), run_name="__main__")
    except (AdapterBootstrapError, OSError, ImportError, SystemExit) as error:
        if isinstance(error, SystemExit):
            code = error.code
            return int(code) if isinstance(code, int) else 1
        print(f"V64 terminal adapter bootstrap: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
