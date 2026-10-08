#!/usr/bin/env python3
"""Batch launcher bound to the forward Stage2 v5 shared guard."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import ds_data02_batch_runner as base


SCRIPTS = Path(__file__).resolve().parent
DISPATCH = (SCRIPTS / "ds_data02_stage2_dispatch_v5.py").resolve()
BOUND_RUNNER_FILES = (
    DISPATCH,
    (SCRIPTS / "ds_data02_strict_dispatch_v5.py").resolve(),
    (SCRIPTS / "ds_data02_runtime_v5.py").resolve(),
    (SCRIPTS / "ds_data02_runtime_v2.py").resolve(),
)
base.RUNTIME_SCRIPT = DISPATCH
run_batch_base = base.run_batch


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _preflight_request(path: Path) -> dict:
    value = json.loads(path.read_text())
    inputs = [str(Path(item).expanduser().resolve()) for item in value.get("input_files", [])]
    hashes = value.get("input_sha256")
    if not isinstance(hashes, dict):
        raise ValueError("v5 request lacks input_sha256")
    for bound in BOUND_RUNNER_FILES:
        key = str(bound)
        if key not in inputs or hashes.get(key) != _sha(bound):
            raise ValueError(f"v5 request does not bind current guard closure: {bound}")
    return value


def run_batch(request_paths, max_concurrency=2, label="batch-v5", *, data_root=base.DATA_ROOT,
              output_dir=None):
    checked = []
    for raw in request_paths:
        path = Path(raw).expanduser().resolve()
        _preflight_request(path)
        checked.append(path)
    return run_batch_base(checked, max_concurrency, label, data_root=data_root,
                          output_dir=output_dir)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("requests", nargs="+", type=Path)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--label", default="batch-v5")
    parser.add_argument("--data-root", type=Path, default=base.DATA_ROOT)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if args.concurrency <= 0:
        parser.error("concurrency must be a positive integer")
    return run_batch(args.requests, args.concurrency, args.label,
                     data_root=args.data_root, output_dir=args.output_dir)


if __name__ == "__main__":
    raise SystemExit(main())

