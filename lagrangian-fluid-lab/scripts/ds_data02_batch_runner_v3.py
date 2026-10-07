"""Batch launcher bound to the forward-only Stage2 dispatch v3."""
from __future__ import annotations

import argparse
from pathlib import Path

import ds_data02_batch_runner as base

DISPATCH = Path(__file__).with_name('ds_data02_stage2_dispatch_v3.py').resolve()
base.RUNTIME_SCRIPT = DISPATCH
run_batch = base.run_batch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('requests', nargs='+', type=Path)
    parser.add_argument('--concurrency', type=int, default=2)
    parser.add_argument('--label', default='batch-v3')
    parser.add_argument('--data-root', type=Path, default=base.DATA_ROOT)
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    if args.concurrency <= 0:
        parser.error('concurrency must be a positive integer')
    return base.run_batch(args.requests, args.concurrency, args.label,
                          data_root=args.data_root, output_dir=args.output_dir)


if __name__ == '__main__':
    raise SystemExit(main())
