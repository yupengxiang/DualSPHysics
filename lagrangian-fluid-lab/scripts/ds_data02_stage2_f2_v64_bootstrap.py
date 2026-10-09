#!/usr/bin/env python3
"""Private ``-I`` bootstrap for the V64 copied worker.

The literal venv interpreter is an approved external ABI dependency.  This
file is copied into the attempt overlay and is the only code that adds the
copied sibling directory to ``sys.path``.  It never derives a path from the
source worktree or from the current working directory.
"""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import sys


class BootstrapError(RuntimeError):
    pass


def _load(path: Path, name: str):
    if path.is_symlink() or not path.is_file():
        raise BootstrapError(f"bound bootstrap module is not a regular file: {path}")
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise BootstrapError(f"cannot load bound bootstrap module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", required=True, type=Path)
    parser.add_argument("--worker", required=True, type=Path)
    parser.add_argument("remainder", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    root_literal = args.runtime_root.expanduser()
    worker_literal = args.worker.expanduser()
    if root_literal.is_symlink() or worker_literal.is_symlink():
        raise BootstrapError("bootstrap paths may not be symlinks")
    root = root_literal.resolve()
    worker = worker_literal.resolve()
    if not root.is_dir() or root.is_symlink() or worker.parent != root:
        raise BootstrapError("worker is outside the copied canonical sibling root")
    if not args.remainder or args.remainder[0] != "--":
        raise BootstrapError("bootstrap arguments must end with -- and worker argv")
    sys.path.insert(0, str(root))
    # V15 imports V14 by its canonical basename.  Register that exact copied
    # sibling before V64/V2 dynamically imports V15 under its bound name.
    v14 = root / "ds_data02_stage2_f2_replay_v14.py"
    if v14.is_file() and not v14.is_symlink():
        _load(v14, v14.stem)
    module = _load(worker, "ds_data02_bound_f2_native_raw_to_typed_label_v64_entry")
    return int(module.main(args.remainder[1:]))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BootstrapError as error:
        print(f"v64 bootstrap: {error}", file=sys.stderr)
        raise SystemExit(2)
