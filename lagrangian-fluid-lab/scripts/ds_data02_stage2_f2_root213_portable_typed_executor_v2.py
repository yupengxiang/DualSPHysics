#!/usr/bin/env python3
"""Forward ROOT213 executor with strict nested provenance closure.

ROOT213 executor V1 deliberately ignored every path below a key containing
``provenance``.  That was too broad: the real ROOT200 inner request has a
``source_metadata_provenance`` object whose ``path`` is a bounded source
contract.  V2 keeps the historical, explicitly non-actionable provenance
fields narrow and copies every other absolute path as a source role.  The
consumed V1 executor and V2 rebind helper remain byte-for-byte unchanged.

This module is a small forward adapter around the V1 executor.  It changes
only the manifest path walk and report schema; all parent supervision,
copy/seal, V8/V12/scorer, pdeath, bounded child stream, and no-ledger rules
continue to come from the consumed implementation.  In particular, an
unknown ``*_provenance`` field is actionable and must have a declared SHA (or
be a bounded readable file); it is never silently exempted.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
V1_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_root213_portable_typed_executor_v1.py"


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load dependency: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


V1 = _load(V1_SCRIPT, "ds02_root213_portable_typed_executor_v1_for_v2")

REPORT_SCHEMA = "ds02.stage2.f2-root213-portable-typed-executor-report.v2"

# These are the only historical path contexts that are explicitly
# non-actionable.  ``source_metadata_provenance`` is intentionally absent:
# the ROOT200 request gives it a schema and SHA, so the file is copied and
# rebound like every other source contract.
NON_ACTIONABLE_PROVENANCE_KEYS = frozenset({
    "historical_provenance",
    "source_provenance",
    "provenance",
    "original_roots",
    "old_absolute_paths",
    "source_path_provenance",
    "argv0_provenance",
    "resolved_provenance",
})


def _is_explicit_non_actionable(parts: Sequence[str]) -> bool:
    return any(str(part).lower() in NON_ACTIONABLE_PROVENANCE_KEYS for part in parts)


def _strict_path_records(
    value: Any, parts: tuple[str, ...] = ()
) -> list[tuple[str, Mapping[str, Any], tuple[str, ...]]]:
    """Walk request JSON and retain all paths outside the exact allowlist.

    This intentionally mirrors the consumed V1 walk, but replaces its
    substring test (``"provenance" in key``) with an exact field allowlist.
    The returned parent mapping carries the declared file SHA/stat used by
    the existing artifact table.  Directory roots continue to be handled by
    the V2 synthetic-directory policy.
    """
    records: list[tuple[str, Mapping[str, Any], tuple[str, ...]]] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            if key_text == "path" and isinstance(child, str) and child.startswith("/"):
                if not _is_explicit_non_actionable(parts):
                    candidate = Path(child).expanduser()
                    if not candidate.exists() or candidate.is_file():
                        records.append((child, value, parts + (key_text,)))
            else:
                records.extend(_strict_path_records(child, parts + (key_text,)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            records.extend(_strict_path_records(child, parts + (str(index),)))
    return records


def _install_forward_hooks() -> None:
    # V1._make_manifest resolves _path_records through its module globals.
    # Replacing that one callable preserves every other consumed V1 behavior.
    V1._path_records = _strict_path_records
    V1.REPORT_SCHEMA = REPORT_SCHEMA


def run(*, request_path: Path | str, output_root: Path | str, parent_pid: int,
        max_wall_seconds: float) -> dict[str, Any]:
    _install_forward_hooks()
    return V1.run(request_path=request_path, output_root=output_root,
                  parent_pid=parent_pid, max_wall_seconds=max_wall_seconds)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--request", type=Path, required=True)
    run_parser.add_argument("--output-root", type=Path, required=True)
    run_parser.add_argument("--parent-pid", type=int, required=True)
    run_parser.add_argument("--max-wall-seconds", type=float, default=900.0)
    check = sub.add_parser("validate")
    check.add_argument("--request", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _install_forward_hooks()
    args = _parser().parse_args(argv)
    try:
        if args.command == "validate":
            value = V1.ROOT213.validate_request(args.request)
        else:
            value = V1.run(request_path=args.request, output_root=args.output_root,
                           parent_pid=args.parent_pid,
                           max_wall_seconds=args.max_wall_seconds)
        print(json.dumps(value, sort_keys=True, ensure_ascii=True, default=str))
        return 0
    except (V1.Root213ExecutorError, V1.ROOT213.Root213Error,
            V1.V1.PortableRebindError, V1.V2.PortableRebindV2Error,
            OSError, ValueError, KeyError) as error:
        print(f"ROOT213 portable typed executor V2: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
