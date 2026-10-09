#!/usr/bin/env python3
"""ROOT228 forward executor with an immutable V1/V2 manifest boundary.

V3 normalised the two scorer role names after calling the V1 manifest
builder, but wrote that normalisation back to ``root213-copy-manifest.json``.
That made the already written V1 contract point at a manifest whose bytes no
longer matched the contract's manifest digest.  V4 keeps the V1 manifest and
contract as an audit trail and writes the normalised pair under new names.

The directory-alias and strict path rules are inherited from the consumed V3
adapter.  This module only changes the manifest hand-off and report version;
it does not relax source closure, parent supervision, or the deferred result
boundary.
"""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
V3_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_root213_portable_typed_executor_v3.py"


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load dependency: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


V3 = _load(V3_SCRIPT, "ds02_root213_portable_typed_executor_v3_for_v4")
V2_EXECUTOR = V3.V2_EXECUTOR
REPORT_SCHEMA = "ds02.stage2.f2-root213-portable-typed-executor-report.v4"


class Root213ExecutorV4Error(RuntimeError):
    """An immutable manifest/contract or inherited strict-closure failure."""


_OLD_REPORT_SCHEMA: str | None = None


def _write_new(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise Root213ExecutorV4Error(f"refusing to overwrite V4 metadata: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _make_manifest_v4(request: Mapping[str, Any], root: Path,
                      reservation_started: float):
    """Build a fresh normalised manifest without mutating V1's pair.

    The inherited builder is intentionally called first: it creates the
    original V1 manifest/contract and performs all source-role discovery.
    V4 then copies the in-memory artifact table, changes only the two logical
    aliases required by V2, and asks the existing contract builder to seal a
    new manifest path.  The original files are never reopened for writing.
    """
    original_builder = V3._ORIGINAL_MAKE_MANIFEST
    if original_builder is None:
        raise Root213ExecutorV4Error("V3 original manifest builder is not installed")
    manifest_path, contract_path, built = original_builder(
        request, root, reservation_started)
    original_manifest_path = Path(manifest_path)
    original_contract_path = Path(contract_path)
    if not original_manifest_path.is_file() or not original_contract_path.is_file():
        raise Root213ExecutorV4Error("V1 manifest/contract was not written")

    normalized = json.loads(original_manifest_path.read_text(encoding="utf-8"))
    if not isinstance(normalized, dict) or not isinstance(normalized.get("artifacts"), list):
        raise Root213ExecutorV4Error("V1 manifest has no artifact table")
    aliases = {
        "typed_scorer_v2": "typed_only_evaluator_v2",
        "typed_scorer_v3": "typed_only_evaluator_v3",
    }
    changed = False
    for item in normalized["artifacts"]:
        if not isinstance(item, dict):
            raise Root213ExecutorV4Error("V1 manifest contains a non-object artifact")
        replacement = aliases.get(str(item.get("logical_role")))
        if replacement is not None:
            item["logical_role"] = replacement
            changed = True
    if not changed:
        raise Root213ExecutorV4Error("V1 manifest has no scorer aliases to normalise")
    normalized["forward_version"] = "ROOT228_V4_IMMUTABLE_MANIFEST_CONTRACT"
    normalized["forward_of"] = {
        "manifest_path": str(original_manifest_path),
        "contract_path": str(original_contract_path),
        "manifest_sha256": V3.V2_EXECUTOR.V1._sha(
            original_manifest_path, "V1 manifest"),
        "contract_sha256": V3.V2_EXECUTOR.V1._sha(
            original_contract_path, "V1 contract"),
        "immutable": True,
    }
    normalized["sha256"] = V3.V2_EXECUTOR.V1._canonical(normalized)

    v3_manifest_path = original_manifest_path.with_name("root213-copy-manifest-v3.json")
    v3_contract_path = original_contract_path.with_name("root213-copy-contract-v3.json")
    _write_new(v3_manifest_path, normalized)
    contract = V3.V2_EXECUTOR.V1.V1.build_contract(
        manifest_path=v3_manifest_path, relocated_root=root,
        output=v3_contract_path, contract_id=request["attempt_id"])

    # Keep the table used by the inherited copy phase in sync with the fresh
    # manifest.  This is an in-memory object owned by this attempt; no V1
    # output is altered.
    table = built.get("table")
    if table is not None:
        for item in table.items:
            replacement = aliases.get(str(item.get("logical_role")))
            if replacement is not None:
                item["logical_role"] = replacement
    built["manifest"] = normalized
    built["contract"] = contract
    built["v1_manifest"] = str(original_manifest_path)
    built["v1_contract"] = str(original_contract_path)
    built["v4_manifest"] = str(v3_manifest_path)
    built["v4_contract"] = str(v3_contract_path)
    return v3_manifest_path, v3_contract_path, built


def _install_hooks() -> None:
    global _OLD_REPORT_SCHEMA
    if _OLD_REPORT_SCHEMA is None:
        _OLD_REPORT_SCHEMA = str(V2_EXECUTOR.REPORT_SCHEMA)
    V3._install_hooks()
    V2_EXECUTOR.REPORT_SCHEMA = REPORT_SCHEMA
    V2_EXECUTOR.V1._make_manifest = _make_manifest_v4


def _restore_hooks() -> None:
    global _OLD_REPORT_SCHEMA
    V3._restore_hooks()
    if _OLD_REPORT_SCHEMA is not None:
        V2_EXECUTOR.REPORT_SCHEMA = _OLD_REPORT_SCHEMA
    _OLD_REPORT_SCHEMA = None


def run(*, request_path: Path | str, output_root: Path | str, parent_pid: int,
        max_wall_seconds: float) -> dict[str, Any]:
    _install_hooks()
    try:
        return V2_EXECUTOR.run(request_path=request_path, output_root=output_root,
                               parent_pid=parent_pid, max_wall_seconds=max_wall_seconds)
    finally:
        _restore_hooks()


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
    _install_hooks()
    try:
        args = _parser().parse_args(argv)
        try:
            if args.command == "validate":
                value = V2_EXECUTOR.V1.ROOT213.validate_request(args.request)
            else:
                value = V2_EXECUTOR.V1.run(
                    request_path=args.request, output_root=args.output_root,
                    parent_pid=args.parent_pid, max_wall_seconds=args.max_wall_seconds)
            print(json.dumps(value, sort_keys=True, ensure_ascii=True, default=str))
            return 0
        except (V3.V2_EXECUTOR.V1.Root213ExecutorError,
                V3.V2_EXECUTOR.V1.ROOT213.Root213Error,
                V3.V2_EXECUTOR.V1.V1.PortableRebindError,
                V3.V2_EXECUTOR.V1.V2.PortableRebindV2Error,
                V3.Root213ExecutorV3Error, Root213ExecutorV4Error,
                OSError, ValueError, KeyError) as error:
            print(f"ROOT213 portable typed executor V4: {error}", file=sys.stderr)
            return 2
    finally:
        _restore_hooks()


if __name__ == "__main__":
    raise SystemExit(main())
