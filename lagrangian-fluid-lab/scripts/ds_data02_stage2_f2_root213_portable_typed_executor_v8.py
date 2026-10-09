#!/usr/bin/env python3
"""ROOT242 narrow single-consumer executor.

The V7 closure is retained as an audit artefact, but its recursive walk also
turns the CURRENT336 inventory and every historical report path into sparse
target files.  That is a valid provenance inventory and an invalid single
case reservation: the logical target tree is hundreds of GiB while the
typed-only consumer needs only the sealed metadata roles and the deferred
V16 result.  V8 keeps the parent/copy/seal/V8/V12/scorer implementation and
narrows only the source graph used for the executable attempt.

The narrowing is explicit and fail-closed.  It does not reinterpret a missing
source as a basename/latest fallback.  CURRENT336, frozen replay input
inventories, nested producer reports, and historical source-request edges are
sealed as provenance by the V8 request builder; an unexpected child open of
one of those original paths is left for the parent's OS-open poison audit to
reject.  No H5, BI4, native frame, or raw payload is opened by this module's
metadata phase.
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
V7_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_root213_portable_typed_executor_v7.py"


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load dependency: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


V7 = _load(V7_SCRIPT, "ds02_root242_executor_v7_for_v8")
V2_EXECUTOR = V7.V2_EXECUTOR
EXECUTOR_V1 = V7.EXECUTOR_V1
REBIND_V1 = V7.REBIND_V1
REBIND_V2 = V7.REBIND_V2
REPORT_SCHEMA = "ds02.stage2.f2-root242-portable-typed-executor-report.v8"


class Root242ExecutorV8Error(RuntimeError):
    """A strict single-consumer closure or copied-graph failure."""


# These roles are the graph roots which the typed-only consumer actually
# opens.  The V7 table still records CURRENT336 and all historical edges for
# audit, but V8 does not copy their recursively enumerated scientific files.
# The explicit base role itself remains copied and SHA/stat checked.
_QUEUEABLE_ROLES = frozenset({
    "root200_inner_request",
    "v12_semantic_sidecar",
})


def _narrow_metadata_source(item: Mapping[str, Any], source: Path) -> bool:
    # During an installed hook V7._is_metadata_source points back to this
    # function.  Keep the captured callable as the delegation target so a
    # real V2 copy walk cannot recurse indefinitely.
    original = _OLD_IS_METADATA_SOURCE or V7._is_metadata_source
    if not original(item, source):
        return False
    return str(item.get("logical_role", "")) in _QUEUEABLE_ROLES


def _strict_paths_without_historical_edges(
    value: Any, parts: tuple[str, ...] = ()
) -> list[tuple[str, Mapping[str, Any], tuple[str, ...]]]:
    """Use V7's strict path walker but omit explicit provenance-only edges."""
    # As above, V7's global is replaced while the V8 hook is active.
    original = _OLD_STRICT_PATHS or V7._strict_path_records_v7
    records = original(value, parts)
    filtered: list[tuple[str, Mapping[str, Any], tuple[str, ...]]] = []
    for path, parent, pointer in records:
        lowered = {str(part).lower() for part in pointer}
        role = str(parent.get("role", "")).upper()
        # ROOT200 labels this old request as a failed historical provenance
        # source.  A generic source_request elsewhere remains actionable.
        if "source_request" in lowered and (
                "v12_forward" in lowered
                or "historical_provenance" in lowered
                or "PROVENANCE_ONLY" in role):
            continue
        filtered.append((path, parent, pointer))
    return filtered


_OLD_IS_METADATA_SOURCE: Any = None
_OLD_STRICT_PATHS: Any = None
_OLD_REPORT_SCHEMA: str | None = None


def _install_hooks() -> None:
    global _OLD_IS_METADATA_SOURCE, _OLD_STRICT_PATHS, _OLD_REPORT_SCHEMA
    if _OLD_IS_METADATA_SOURCE is not None:
        return
    V7._install_hooks()
    _OLD_IS_METADATA_SOURCE = V7._is_metadata_source
    _OLD_STRICT_PATHS = V7._strict_path_records_v7
    _OLD_REPORT_SCHEMA = str(V2_EXECUTOR.REPORT_SCHEMA)
    V7._is_metadata_source = _narrow_metadata_source
    V7._strict_path_records_v7 = _strict_paths_without_historical_edges
    V2_EXECUTOR.REPORT_SCHEMA = REPORT_SCHEMA


def _restore_hooks() -> None:
    global _OLD_IS_METADATA_SOURCE, _OLD_STRICT_PATHS, _OLD_REPORT_SCHEMA
    if _OLD_IS_METADATA_SOURCE is None:
        return
    V7._is_metadata_source = _OLD_IS_METADATA_SOURCE
    V7._strict_path_records_v7 = _OLD_STRICT_PATHS
    if _OLD_REPORT_SCHEMA is not None:
        V2_EXECUTOR.REPORT_SCHEMA = _OLD_REPORT_SCHEMA
    _OLD_IS_METADATA_SOURCE = None
    _OLD_STRICT_PATHS = None
    _OLD_REPORT_SCHEMA = None
    V7._restore_hooks()


def run(*, request_path: Path | str, output_root: Path | str,
        parent_pid: int, max_wall_seconds: float) -> dict[str, Any]:
    _install_hooks()
    try:
        # V7's run installs its own hooks; call the inherited V2 runner after
        # our narrow globals are in place so the copy manifest sees only the
        # queueable graph roots above.
        return V2_EXECUTOR.run(request_path=request_path, output_root=output_root,
                               parent_pid=parent_pid,
                               max_wall_seconds=max_wall_seconds)
    finally:
        _restore_hooks()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--request", type=Path, required=True)
    run.add_argument("--output-root", type=Path, required=True)
    run.add_argument("--parent-pid", type=int, required=True)
    run.add_argument("--max-wall-seconds", type=float, default=900.0)
    check = sub.add_parser("validate")
    check.add_argument("--request", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _install_hooks()
    try:
        args = _parser().parse_args(argv)
        try:
            if args.command == "validate":
                value = EXECUTOR_V1.ROOT213.validate_request(args.request)
            else:
                value = V2_EXECUTOR.run(
                    request_path=args.request, output_root=args.output_root,
                    parent_pid=args.parent_pid,
                    max_wall_seconds=args.max_wall_seconds)
            print(json.dumps(value, sort_keys=True, ensure_ascii=True, default=str))
            return 0
        except (V7.Root213ExecutorV7Error, EXECUTOR_V1.Root213ExecutorError,
                EXECUTOR_V1.ROOT213.Root213Error,
                REBIND_V1.PortableRebindError,
                REBIND_V2.PortableRebindV2Error, OSError, ValueError, KeyError,
                Root242ExecutorV8Error) as error:
            print(f"ROOT242 portable typed executor V8: {error}", file=sys.stderr)
            return 2
    finally:
        _restore_hooks()


if __name__ == "__main__":
    raise SystemExit(main())
