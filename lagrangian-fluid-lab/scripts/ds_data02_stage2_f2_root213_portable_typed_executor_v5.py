#!/usr/bin/env python3
"""ROOT230 forward executor with recursive nested metadata closure.

ROOT228/V4 reached the copied V2 worker, but its target-side rebase failed on
``historical_provenance.root194_sidecar.path``.  That path is historical in
the outer contract yet is consumed by a nested V2 metadata walk, so treating
the whole context as non-actionable was unsound.

V5 keeps V4 and every consumed request immutable.  Before writing its fresh
manifest it walks the bounded JSON graph, adds every nested actionable file
to the sealed source map (including exact historical-sidecar paths), and
preflights each JSON through the real V2 rewriter.  A copied V5 child entry
point then materialises the same graph as target-local JSON views before the
existing V8/V12/scorer call.  Payloads remain deferred and are never opened
by this source-only preparation path.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
V4_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_root213_portable_typed_executor_v4.py"
V5_RUNTIME_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_typed_only_portable_rebind_v5.py"
V2_REBIND_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_typed_only_portable_rebind_v2.py"


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load dependency: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


V4 = _load(V4_SCRIPT, "ds02_root213_portable_typed_executor_v4_for_v5")
V2_EXECUTOR = V4.V2_EXECUTOR
EXECUTOR_V1 = V2_EXECUTOR.V1
REBIND_V1 = EXECUTOR_V1.V1
REBIND_V2 = EXECUTOR_V1.V2
REPORT_SCHEMA = "ds02.stage2.f2-root213-portable-typed-executor-report.v5"
MAX_METADATA_BYTES = int(EXECUTOR_V1.MAX_METADATA_BYTES)


class Root213ExecutorV5Error(RuntimeError):
    """A recursive source closure or strict copied-graph failure."""


# Exact annotations whose paths are not read by the V2 loader.  In
# particular, ``historical_provenance`` is deliberately *not* here: ROOT228
# proved that one of its paths is consumed by the nested sidecar rewriter.
NON_ACTIONABLE_CONTEXTS = frozenset({
    "original_roots", "source_provenance", "provenance", "old_absolute_paths",
    "source_path_provenance", "argv0_provenance", "resolved_provenance",
})

# A nested report/receipt is a sealed evidence leaf.  Its own scientific
# payload inventory is not a contract that the V2 rewriter opens.  Contract
# sidecars, historical requests, and frozen views are the graph edges that
# must be recursively target-rebased.
RECURSIVE_CONTEXTS = frozenset({
    "historical_provenance", "source_metadata_provenance", "source_metadata",
    "v12_forward", "semantic_sidecar", "source_request", "replaces_request",
    "current_manifest", "frozen", "profile_rebind", "root194_sidecar",
})
LEAF_CONTEXTS = frozenset({
    "producer_nested_report", "producer_report", "worker_summary",
    "execution_receipt", "completed_receipt", "parent_report", "root_proof",
    "terminal_evidence", "terminal_delta",
})

_OLD_REPORT_SCHEMA: str | None = None


def _pointer(parts: Sequence[str]) -> str:
    return "" if not parts else "".join(
        "/" + str(part).replace("~", "~0").replace("/", "~1") for part in parts
    )


def _is_non_actionable(parts: Sequence[str]) -> bool:
    return any(str(part).lower() in NON_ACTIONABLE_CONTEXTS for part in parts)


def _should_recurse(parts: Sequence[str]) -> bool:
    lowered = {str(part).lower() for part in parts}
    if lowered & LEAF_CONTEXTS:
        return False
    return bool(lowered & RECURSIVE_CONTEXTS)


def _strict_path_records_v5(
    value: Any, parts: tuple[str, ...] = ()
) -> list[tuple[str, Mapping[str, Any], tuple[str, ...]]]:
    """Collect all V2-consumed absolute ``path`` records.

    This is intentionally stricter than the V1 walk and differs from V2 only
    in one important way: historical provenance is not an automatic escape.
    The parent mapping supplies the declared SHA/stat for a small file or a
    deferred payload placeholder.
    """
    records: list[tuple[str, Mapping[str, Any], tuple[str, ...]]] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            if (key_text == "path" and isinstance(child, str) and
                    child.startswith("/") and not _is_non_actionable(parts)):
                candidate = Path(child).expanduser()
                # Existing directories are synthetic anchors handled by V2's
                # directory policy; files and declared-but-not-yet-present
                # paths are source roles and must be bound explicitly.
                if not candidate.exists() or candidate.is_file():
                    records.append((child, value, parts + (key_text,)))
            else:
                records.extend(_strict_path_records_v5(child, parts + (key_text,)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            records.extend(_strict_path_records_v5(child, parts + (str(index),)))
    return records


def _canonical(value: Mapping[str, Any]) -> str:
    return REBIND_V1._canonical(value)


def _write_new(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise Root213ExecutorV5Error(f"refusing to overwrite V5 metadata: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _source_key(path: Path) -> str:
    return os.path.abspath(str(path))


def _source_map(table: Any, root: Path) -> dict[str, tuple[Mapping[str, Any], Path]]:
    result: dict[str, tuple[Mapping[str, Any], Path]] = {}
    for item in table.items:
        result[_source_key(Path(item["source_path_provenance"]))] = (
            item, root / EXECUTOR_V1._safe_relative(item["target_relative_path"], item["logical_role"])
        )
    return result


def _declared_sha(value: Mapping[str, Any]) -> str | None:
    """Accept the real request spellings without weakening SHA validation."""
    for key in (
        "file_sha256", "sha256", "expected_sha256", "producer_declared_sha256",
        "source_sha256",
    ):
        candidate = value.get(key)
        if (isinstance(candidate, str) and len(candidate) == 64 and
                all(char in "0123456789abcdef" for char in candidate)):
            return candidate
    return None


def _add_recursive_role(table: Any, source: Path, parent: Mapping[str, Any],
                        root: Path, pointer: tuple[str, ...]) -> dict[str, Any]:
    source = source.expanduser()
    payload = EXECUTOR_V1._payload_like(source, parent)
    sha = _declared_sha(parent)
    if sha is None and source.is_file() and not payload:
        sha = EXECUTOR_V1._sha(source, "V5 nested metadata")
    if sha is None:
        raise Root213ExecutorV5Error(
            f"nested actionable path has no declared SHA at {_pointer(pointer)}: {source}")
    target = EXECUTOR_V1._target_for_closure(source, sha, payload=payload)
    if table.get(source) is not None:
        return table.get(source)
    stat = parent.get("stat") if isinstance(parent, Mapping) else None
    role = f"recursive_metadata_{hashlib.sha256(_source_key(source).encode()).hexdigest()[:16]}"
    item = table.add(
        role=role, source=source, target=target, sha256=sha, stat=stat,
        kind="deferred_source_placeholder" if payload else "bounded_nested_metadata",
        deferred=payload, placeholder=payload,
    )
    item["nested_discovery_pointer"] = _pointer(pointer)
    item["nested_discovery_policy"] = "V5_RECURSIVE_ACTIONABLE_PATH"
    return item


def _collect_recursive_metadata(table: Any) -> list[dict[str, Any]]:
    """Expand the bounded JSON graph without opening payload roles."""
    queue: list[Path] = []
    root_roles = {
        "root200_inner_request", "v12_semantic_sidecar", "frozen_v15_request",
    }
    for item in list(table.items):
        source = Path(item["source_path_provenance"])
        role = str(item.get("logical_role", ""))
        if ((role in root_roles or role.startswith("closure_")) and
                source.suffix.lower() == ".json" and
                not item.get("deferred_content") and
                source.is_file() and source.stat().st_size <= MAX_METADATA_BYTES):
            queue.append(source)
    seen: set[str] = set()
    discoveries: list[dict[str, Any]] = []
    while queue:
        source = queue.pop(0)
        key = _source_key(source)
        if key in seen:
            continue
        seen.add(key)
        if source.is_symlink() or not source.is_file():
            raise Root213ExecutorV5Error(f"nested metadata source is unavailable: {source}")
        if source.stat().st_size > MAX_METADATA_BYTES:
            continue
        value = EXECUTOR_V1._json(source, "V5 recursive metadata")
        for raw_path, parent, pointer in _strict_path_records_v5(value):
            child = Path(raw_path).expanduser()
            before = table.get(child)
            item = _add_recursive_role(table, child, parent, source.parent, pointer)
            if before is None:
                discoveries.append({
                    "source_path": str(child), "source_role": item["logical_role"],
                    "declared_source_sha256": item["source_sha256"],
                    "pointer": _pointer(pointer),
                    "deferred_content": bool(item.get("deferred_content")),
                })
                if (_should_recurse(pointer) and child.suffix.lower() == ".json" and
                        not item.get("deferred_content") and
                        child.is_file() and child.stat().st_size <= MAX_METADATA_BYTES):
                    queue.append(child)
    return discoveries


def _preflight_recursive_rewrites(table: Any, root: Path) -> list[dict[str, Any]]:
    """Run the real V2 rewrite over every bounded JSON source before copy."""
    source_map = _source_map(table, root)
    # The outer ROOT200 inner request needs V3's exact V14 directory alias.
    # Nested sidecars use the byte-frozen V2 rewriter directly; V3's
    # top-level absolute-value audit would incorrectly treat their cwd and
    # interpreter provenance strings as actionable paths.
    top_level_rewrite = REBIND_V2._rewrite_request
    nested_rewrite = V4.V3._ORIGINAL_REWRITE
    if top_level_rewrite is None or nested_rewrite is None:
        raise Root213ExecutorV5Error("V2/V3 rewriters are not installed")
    checks: list[dict[str, Any]] = []
    for item in list(table.items):
        source = Path(item["source_path_provenance"])
        role = str(item.get("logical_role", ""))
        if ((role not in {"root200_inner_request", "v12_semantic_sidecar", "frozen_v15_request"}
             and not (role.startswith("closure_") and
                      "root194-proof-request.json" not in source.name)) or
                source.suffix.lower() != ".json" or item.get("deferred_content") or
                not source.is_file() or source.stat().st_size > MAX_METADATA_BYTES):
            continue
        value = EXECUTOR_V1._json(source, "V5 preflight metadata")
        bindings: list[dict[str, Any]] = []
        rewrite = top_level_rewrite if item.get("logical_role") == "root200_inner_request" else nested_rewrite
        rewritten = rewrite(
            value, root=root, source_map=source_map, role_by_target={},
            bindings=bindings, parts=())
        if not isinstance(rewritten, dict):
            raise Root213ExecutorV5Error(f"rewritten metadata is not an object: {source}")
        # Every non-exempt path must be target-local after this exact rewrite.
        _assert_closed(rewritten, root)
        checks.append({
            "source_path": str(source), "source_sha256": EXECUTOR_V1._sha(source, "V5 preflight"),
            "binding_count": len(bindings), "status": "PASS_REWRITE_PREFLIGHT",
        })
    return checks


def _assert_closed(value: Any, root: Path, parts: tuple[str, ...] = ()) -> None:
    directory_keys = {
        "root", "target_root", "output_root", "runtime_root",
        "runtime_target_root", "fresh_output_root", "fresh_output_namespace",
        "fresh_proof_namespace", "proof_namespace",
    }
    if isinstance(value, Mapping):
        for key, child in value.items():
            text = str(key)
            pointer = parts + (text,)
            if (isinstance(child, str) and child.startswith("/") and
                    (text == "path" or text.lower() in directory_keys)):
                if _is_non_actionable(parts):
                    continue
                try:
                    Path(child).resolve(strict=False).relative_to(root.resolve(strict=False))
                except ValueError as error:
                    raise Root213ExecutorV5Error(
                        f"unbound nested metadata path at {_pointer(pointer)}: {child}") from error
            _assert_closed(child, root, pointer)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_closed(child, root, parts + (str(index),))


def _directory_rebind_v5(parts: tuple[str, ...], root: Path) -> Path | None:
    """Bind the decoder scratch directory declared by the copied worker.

    It is a directory anchor, not a source file.  The old V2 policy only
    knew proof/output roots; the actual V66 worker also records
    ``runtime.scratch.root``.  Keep the alias narrow and attempt-owned.
    """
    lower = [str(part).lower() for part in parts]
    if lower and lower[-1] == "root" and ("scratch" in lower or "decoder_scratch" in lower):
        return root / "runtime" / "scratch"
    if lower and lower[-1] == "root" and "v64_raw_scope" in lower:
        return root / "evidence" / "raw-scope"
    return V4.V3._directory_rebind_v3(parts, root)


def _replace_v2_entrypoint(table: Any) -> None:
    old = None
    for item in table.items:
        if item.get("logical_role") == "portable_rebind_v2_entrypoint":
            old = item
            break
    if old is None:
        raise Root213ExecutorV5Error("V4 manifest lacks portable V2 entrypoint role")
    old_source = _source_key(Path(old["source_path_provenance"]))
    old_target = old["target_relative_path"]
    table.by_source.pop(old_source, None)
    table.by_target.pop(old_target, None)
    old.update({
        "source_path_provenance": str(V5_RUNTIME_SCRIPT),
        "source_sha256": EXECUTOR_V1._sha(V5_RUNTIME_SCRIPT, "V5 runtime entrypoint"),
        "source_stat_provenance": EXECUTOR_V1._full_stat(V5_RUNTIME_SCRIPT, "V5 runtime entrypoint"),
        "target_relative_path": f"runtime/{V5_RUNTIME_SCRIPT.name}",
        "source_kind": "runtime_source_forward_v5",
        "content_read_by_manifest": True,
        "deferred_content": False,
        "placeholder_only": False,
    })
    table.by_source[_source_key(V5_RUNTIME_SCRIPT)] = old
    table.by_target[old["target_relative_path"]] = old
    if table.get(V2_REBIND_SCRIPT) is None:
        table.add(
            role="portable_rebind_v2_core",
            source=V2_REBIND_SCRIPT,
            target=f"runtime/{V2_REBIND_SCRIPT.name}",
            sha256=EXECUTOR_V1._sha(V2_REBIND_SCRIPT, "V2 runtime core"),
            stat=EXECUTOR_V1._full_stat(V2_REBIND_SCRIPT, "V2 runtime core"),
            kind="runtime_source_sibling", deferred=False,
        )


def _make_manifest_v5(request: Mapping[str, Any], root: Path,
                      reservation_started: float):
    manifest_path, contract_path, built = V4._make_manifest_v4(
        request, root, reservation_started)
    table = built["table"]
    _replace_v2_entrypoint(table)
    discoveries = _collect_recursive_metadata(table)
    preflight = _preflight_recursive_rewrites(table, root)
    manifest = copy.deepcopy(built["manifest"])
    manifest["artifacts"] = table.items
    manifest["forward_version"] = "ROOT230_V5_RECURSIVE_METADATA_CLOSURE"
    manifest["forward_of"] = {
        "manifest_path": str(manifest_path), "contract_path": str(contract_path),
        "manifest_sha256": EXECUTOR_V1._sha(Path(manifest_path), "V4 manifest"),
        "contract_sha256": EXECUTOR_V1._sha(Path(contract_path), "V4 contract"),
        "immutable": True,
    }
    manifest["recursive_metadata_closure"] = {
        "path_policy": "ALL_ACTIONABLE_PATHS_INCLUDING_HISTORICAL_SIDECARS",
        "non_actionable_contexts": sorted(NON_ACTIONABLE_CONTEXTS),
        "discovered_roles": discoveries,
        "rewrite_preflight": preflight,
        "bounded_json_bytes": MAX_METADATA_BYTES,
        "payload_content_read": False,
    }
    manifest["sha256"] = _canonical(manifest)
    v5_manifest = root / "metadata" / "root213-copy-manifest-v5.json"
    v5_contract = root / "metadata" / "root213-copy-contract-v5.json"
    _write_new(v5_manifest, manifest)
    contract = REBIND_V1.build_contract(
        manifest_path=v5_manifest, relocated_root=root, output=v5_contract,
        contract_id=request["attempt_id"])
    built["manifest"] = manifest
    built["contract"] = contract
    built["v4_manifest"] = str(manifest_path)
    built["v4_contract"] = str(contract_path)
    built["v5_manifest"] = str(v5_manifest)
    built["v5_contract"] = str(v5_contract)
    built["recursive_metadata_discoveries"] = discoveries
    built["recursive_rewrite_preflight"] = preflight
    return v5_manifest, v5_contract, built


def _install_hooks() -> None:
    global _OLD_REPORT_SCHEMA
    if _OLD_REPORT_SCHEMA is None:
        _OLD_REPORT_SCHEMA = str(V2_EXECUTOR.REPORT_SCHEMA)
    V4._install_hooks()
    V2_EXECUTOR.REPORT_SCHEMA = REPORT_SCHEMA
    REBIND_V2._directory_rebind = _directory_rebind_v5
    EXECUTOR_V1._path_records = _strict_path_records_v5
    EXECUTOR_V1._make_manifest = _make_manifest_v5


def _restore_hooks() -> None:
    global _OLD_REPORT_SCHEMA
    V4._restore_hooks()
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
                value = EXECUTOR_V1.ROOT213.validate_request(args.request)
            else:
                # Hooks are already installed by this CLI's outer finally;
                # call the inherited runner directly so installation and
                # restoration are not nested around the same module globals.
                value = V2_EXECUTOR.run(
                    request_path=args.request, output_root=args.output_root,
                    parent_pid=args.parent_pid, max_wall_seconds=args.max_wall_seconds)
            print(json.dumps(value, sort_keys=True, ensure_ascii=True, default=str))
            return 0
        except (EXECUTOR_V1.Root213ExecutorError, EXECUTOR_V1.ROOT213.Root213Error,
                REBIND_V1.PortableRebindError, REBIND_V2.PortableRebindV2Error,
                V4.Root213ExecutorV4Error, Root213ExecutorV5Error,
                OSError, ValueError, KeyError) as error:
            print(f"ROOT213 portable typed executor V5: {error}", file=sys.stderr)
            return 2
    finally:
        _restore_hooks()


if __name__ == "__main__":
    raise SystemExit(main())
