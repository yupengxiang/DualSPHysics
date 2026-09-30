#!/usr/bin/env python3
"""Run the cheap closed-stream/3-D F3 conversion preflight."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import resource
from typing import Sequence

try:
    from .ds_data02_direct_convert import audit_conversion_contract
except ImportError:  # pragma: no cover
    from ds_data02_direct_convert import audit_conversion_contract


def _usage() -> dict[str, float]:
    result = {}
    for who, label in ((resource.RUSAGE_SELF, "self"), (resource.RUSAGE_CHILDREN, "children")):
        value = resource.getrusage(who)
        result[f"{label}_user_seconds"] = float(value.ru_utime)
        result[f"{label}_system_seconds"] = float(value.ru_stime)
        result[f"{label}_max_rss_kib"] = float(value.ru_maxrss)
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--generated-xml", type=Path, required=True)
    parser.add_argument("--decoder", type=Path, required=True)
    parser.add_argument("--solver-log", type=Path, required=True)
    parser.add_argument("--solver-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    before = _usage()
    result = audit_conversion_contract(
        data_root=args.data_root,
        generated_xml=args.generated_xml,
        decoder=args.decoder,
        solver_log=args.solver_log,
        solver_receipt=args.solver_receipt,
    )
    after = _usage()
    result.update({"schema": "ds02.f3.weak-conversion-preflight.v1", "resource_usage": {key: after[key] - before[key] for key in after}})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

