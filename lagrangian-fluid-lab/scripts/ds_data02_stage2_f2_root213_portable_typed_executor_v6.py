#!/usr/bin/env python3
"""ROOT230 forward executor with recursive nested metadata closure.

ROOT228/V4 reached the copied V2 worker, but its target-side rebase failed on
``historical_provenance.root194_sidecar.path``.  That path is historical in
the outer contract yet is consumed by a nested V2 metadata walk, so treating
the whole context as non-actionable was unsound.

V6 keeps V4 and every consumed request immutable.  Before writing its fresh
manifest it walks the bounded JSON graph, adds every nested actionable file
to the sealed source map (including exact historical-sidecar paths), and
preflights each JSON through the real V2 rewriter.  A copied V6 child entry
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
import re
import sys
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
V4_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_root213_portable_typed_executor_v4.py"
V6_RUNTIME_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_typed_only_portable_rebind_v6.py"
V2_REBIND_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_typed_only_portable_rebind_v2.py"


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load dependency: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


V4 = _load(V4_SCRIPT, "ds02_root213_portable_typed_executor_v4_for_v6")
V2_EXECUTOR = V4.V2_EXECUTOR
EXECUTOR_V1 = V2_EXECUTOR.V1
REBIND_V1 = EXECUTOR_V1.V1
REBIND_V2 = EXECUTOR_V1.V2
REPORT_SCHEMA = "ds02.stage2.f2-root213-portable-typed-executor-report.v6"
MAX_METADATA_BYTES = int(EXECUTOR_V1.MAX_METADATA_BYTES)


class Root213ExecutorV6Error(RuntimeError):
    """A recursive source closure or strict copied-graph failure."""


# Exact annotations whose paths are not read by the V2 loader.  In
# particular, ``historical_provenance`` is deliberately *not* here: ROOT228
# proved that one of its paths is consumed by the nested sidecar rewriter.
NON_ACTIONABLE_CONTEXTS = frozenset({
    "original_roots", "source_provenance", "provenance", "old_absolute_paths",
    "source_path_provenance", "argv0_provenance", "resolved_provenance",
    "git_at_launch",
    # Evidence receipt pointers are administrative references.  Their
    # contents are already sealed as receipt roles; the nested V2 worker does
    # not consume these paths as scientific inputs.
    "receipt", "observed_receipt", "root397_observation", "report",
    "upstream_qa103_observation", "solver_log", "case_xmf", "trace",
    "expected_artifacts", "home_receipt",
})

# A nested report/receipt is a sealed evidence leaf.  Its own scientific
# payload inventory is not a contract that the V2 rewriter opens.  Contract
# sidecars, historical requests, and frozen views are the graph edges that
# must be recursively target-rebased.
RECURSIVE_CONTEXTS = frozenset({
    "historical_provenance", "source_metadata_provenance", "source_metadata",
    "v12_forward", "semantic_sidecar", "source_request", "replaces_request",
    "current_manifest", "frozen", "profile_rebind", "root194_sidecar",
    # CURRENT336 is an actionable metadata index.  Its cases[*].manifest
    # edges are consumed by the copied request and must be in the same
    # sealed map (V5 stopped before this edge).
    "cases", "manifest", "case", "source_binding", "source_bindings", "v12_forward",
})
LEAF_CONTEXTS = frozenset({
    "producer_nested_report", "producer_report", "worker_summary",
    "execution_receipt", "completed_receipt", "parent_report", "root_proof",
    "terminal_evidence", "terminal_delta",
})

_OLD_REPORT_SCHEMA: str | None = None
_KNOWN_PATH_SHAS: dict[str, str] = {}
_OLD_PROVENANCE_KEYS: set[str] | None = None


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


def _rebase_generated_outputs(value: Any, root: Path,
                              parts: tuple[str, ...] = ()) -> Any:
    """Rebind generated trace/finalization paths without source-copying them.

    Trace files are produced by the supervised attempt.  They have no
    pre-reservation content SHA and therefore must not become scientific
    source roles.  The copied request still needs a target-local path, so
    rewrite only the narrowly named generated-output fields to an
    attempt-owned runtime location.  This does not permit arbitrary absolute
    values or historical input paths.
    """
    if isinstance(value, Mapping):
        output: dict[str, Any] = {}
        for key, child in value.items():
            key_text = str(key)
            lower = {str(part).lower() for part in parts}
            generated_key = key_text.lower() in {"trace_path", "finalization_sidecar"}
            generated_path = (key_text == "path" and
                              ("trace" in lower or "expected_artifacts" in lower
                               or "home_receipt" in lower
                               or str(value.get("role", "")).lower() == "parent_os_open_trace"))
            if ((generated_key or generated_path) and isinstance(child, str)
                    and child.startswith("/")):
                output[key] = str(root / "runtime" / "generated" / Path(child).name)
            else:
                output[key] = _rebase_generated_outputs(child, root,
                                                        parts + (key_text,))
        return output
    if isinstance(value, list):
        return [_rebase_generated_outputs(child, root, parts + (str(index),))
                for index, child in enumerate(value)]
    return value


def _strict_path_records_v6(
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
                # The live resource ledger is an outer administrative input,
                # never a scientific/copied role.  Its path is rewritten to
                # the attempt's immutable reference sidecar below; do not
                # rediscover it as a normal JSON source.
                if _is_live_ledger(candidate):
                    records.extend(())
                    continue
                # CURRENT336 deliberately records unresolved XMF/QA
                # observations with status WAIT/UNKNOWN and no SHA.  Keep
                # those scientific unknowns as unknown; do not invent a
                # current-content hash merely to make the portable graph
                # appear closed.  A path with no such explicit status still
                # fails below in _add_recursive_role.
                status = str(value.get("status", "")).upper() if isinstance(value, Mapping) else ""
                declared = value.get("sha256") if isinstance(value, Mapping) else None
                if (declared is None and status in {"WAIT", "UNKNOWN", "UNRESOLVED", "PENDING"}):
                    continue
                # Generated trace paths are created by the parent/child
                # attempt.  With no declared content SHA they are output
                # anchors, not source roles; _rebase_generated_outputs maps
                # them to the fresh runtime namespace below.
                if (declared is None and (
                        any(str(part).lower() in {"trace", "stderr", "stdout",
                                                 "expected_artifacts", "home_receipt"}
                            for part in parts)
                        or (isinstance(value, Mapping) and
                            str(value.get("role", "")).lower() == "parent_os_open_trace"))):
                    continue
                # Existing directories are synthetic anchors handled by V2's
                # directory policy; files and declared-but-not-yet-present
                # paths are source roles and must be bound explicitly.
                if not candidate.exists() or candidate.is_file():
                    records.append((child, value, parts + (key_text,)))
            else:
                records.extend(_strict_path_records_v6(child, parts + (key_text,)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            records.extend(_strict_path_records_v6(child, parts + (str(index),)))
    return records


def _canonical(value: Mapping[str, Any]) -> str:
    return REBIND_V1._canonical(value)


def _write_new(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise Root213ExecutorV6Error(f"refusing to overwrite V6 metadata: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _source_key(path: Path) -> str:
    return os.path.abspath(str(path))


def _source_map(table: Any, root: Path) -> dict[str, tuple[Mapping[str, Any], Path]]:
    result: dict[str, tuple[Mapping[str, Any], Path]] = {}
    for item in table.items:
        target = root / EXECUTOR_V1._safe_relative(
            item["target_relative_path"], item["logical_role"])
        result[_source_key(Path(item["source_path_provenance"]))] = (item, target)
        # Recursive V6 views can legitimately point at an earlier target-local
        # JSON view.  The consumed V2 map is source-keyed, so add the sealed
        # target spelling as an alias as well; this remains closed to `root`.
        result[_source_key(target)] = (item, target)
        for alias in item.get("source_path_aliases", []):
            result[_source_key(Path(str(alias)))] = (item, target)
    return result


def _declared_sha(value: Mapping[str, Any]) -> str | None:
    """Accept the real request spellings without weakening SHA validation."""
    for key in (
        "file_sha256", "sha256", "expected_sha256", "producer_declared_sha256",
        "source_sha256", "producer_sha256", "content_sha256",
    ):
        candidate = value.get(key)
        if (isinstance(candidate, str) and len(candidate) == 64 and
                all(char in "0123456789abcdef" for char in candidate)):
            return candidate
    candidate = value.get("recomputed_sha256")
    if (isinstance(candidate, str) and len(candidate) == 64 and
            all(char in "0123456789abcdef" for char in candidate)):
        return candidate
    return None


def _is_live_ledger(path: Path) -> bool:
    return path.name == "resource-ledger.json" and "runtime" in {
        part.lower() for part in path.parts
    }


def _is_metadata_source(item: Mapping[str, Any], source: Path) -> bool:
    """Whether a role is safe to open as bounded request metadata."""
    if (item.get("deferred_content") or source.suffix.lower() != ".json" or
            source.name.lower().endswith("manifest.json")):
        return False
    role = str(item.get("logical_role", "")).lower()
    if any(token in role for token in (
        "report", "receipt", "proof", "terminal", "summary", "result",
    )):
        return False
    return source.is_file() and source.stat().st_size <= MAX_METADATA_BYTES


def _bounded_declared_sibling(source: Path, expected_sha: str | None) -> Path | None:
    """Resolve a missing *metadata* path across the frozen worktree views.

    Requests assembled in a different consumer checkout can retain that
    checkout's absolute path even though the immutable JSON is present in
    the primary stage2 worktree.  This is an explicit provenance alias, not
    an arbitrary latest/source fallback: only the known checkout pair is
    considered, only bounded JSON is opened, and the declared SHA must match
    before the candidate is admitted.
    """
    if source.exists() or source.suffix.lower() != ".json" or expected_sha is None:
        return None
    consumer_root = Path("/home/jade/.codex/worktrees/ds-data-02-stage2-consumers")
    primary_root = Path("/home/jade/.codex/worktrees/ds-data-02-stage2")
    try:
        relative = source.relative_to(consumer_root)
    except ValueError:
        return None
    candidate = primary_root / relative
    if (not candidate.is_file() or candidate.stat().st_size > MAX_METADATA_BYTES):
        return None
    actual = EXECUTOR_V1._sha(candidate, "V6 bounded worktree provenance alias")
    if actual != expected_sha:
        raise Root213ExecutorV6Error(
            f"bounded worktree alias SHA mismatch for {source}: "
            f"expected {expected_sha}, got {actual}")
    return candidate


def _add_recursive_role(table: Any, source: Path, parent: Mapping[str, Any],
                        root: Path, pointer: tuple[str, ...]) -> dict[str, Any]:
    source = source.expanduser()
    requested_source = source
    sibling = _bounded_declared_sibling(source, _declared_sha(parent))
    if sibling is not None:
        item = _add_recursive_role(table, sibling, parent, root, pointer)
        aliases = list(item.get("source_path_aliases", []))
        if str(requested_source) not in aliases:
            aliases.append(str(requested_source))
            item["source_path_aliases"] = aliases
        item.setdefault("source_path_alias_policy", "V6_EXPLICIT_PRIMARY_WORKTREE_SHA_ALIAS")
        return item
    # The approved interpreter is a literal venv argv path and is normally a
    # symlink to the pinned binary.  A nested request may carry the equivalent
    # path from another checkout.  Rebind only to the already sealed literal
    # interpreter role; do not resolve it to a system-Python argv or copy an
    # arbitrary executable.
    if source.is_symlink() and source.name in {"python", "python3"}:
        interpreter_roles = [item for item in table.items
                             if str(item.get("logical_role", "")).startswith("literal_")
                             and "python" in str(item.get("logical_role", "")).lower()]
        if len(interpreter_roles) == 1:
            item = interpreter_roles[0]
            aliases = list(item.get("source_path_aliases", []))
            if str(source) not in aliases:
                aliases.append(str(source))
                item["source_path_aliases"] = aliases
            return item
    # Some historical embedded worker requests retain an old attempt's
    # absolute decoder path.  If that path is absent and the path is exactly
    # a decoder executable basename, bind it to the one already sealed
    # decoder role.  The old source is never opened; the alias is recorded
    # and the copied target uses the current sealed SHA/mode.
    if (not source.exists() and source.name == "bi4_dump" and
            "decoder" in {str(part).lower() for part in pointer}):
        candidates = [item for item in table.items
                      if Path(str(item.get("source_path_provenance", ""))).name == "bi4_dump"
                      and item.get("source_sha256")]
        preferred = [item for item in candidates
                     if "/runtime/native/bi4_dump" in str(item.get("source_path_provenance", ""))]
        if len(preferred) == 1:
            item = preferred[0]
        elif candidates and len({str(item.get("source_sha256")) for item in candidates}) == 1:
            # Multiple immutable copies of the same decoder SHA are already
            # sealed; use the deterministic first role and record the alias.
            item = sorted(candidates, key=lambda value: str(value.get("target_relative_path")))[0]
        else:
            item = None
        if item is not None:
            aliases = list(item.get("source_path_aliases", []))
            if str(source) not in aliases:
                aliases.append(str(source))
                item["source_path_aliases"] = aliases
            return item
    if not source.exists() and _declared_sha(parent) is not None:
        expected = _declared_sha(parent)
        candidates = [item for item in table.items
                      if item.get("source_sha256") == expected
                      and Path(str(item.get("source_path_provenance", ""))).is_file()]
        same_name = [item for item in candidates
                     if Path(str(item.get("source_path_provenance", ""))).name == source.name]
        if same_name and len({str(item.get("source_sha256")) for item in same_name}) == 1:
            # Several sealed bundles can carry byte-identical copies of the
            # same module.  The content identity is unambiguous even though
            # the historical path is not; choose a stable target and retain
            # every old path as an explicit alias.
            item = sorted(same_name, key=lambda value: str(value.get("target_relative_path")))[0]
        elif len(candidates) == 1:
            item = candidates[0]
        else:
            item = None
        if item is not None:
            aliases = list(item.get("source_path_aliases", []))
            if str(source) not in aliases:
                aliases.append(str(source))
                item["source_path_aliases"] = aliases
            return item
    # CURRENT336 raw-frame entries sometimes carry only the path: the
    # immutable per-frame SHA/stat was sealed by the earlier V5 manifest under
    # its target-side Part_NNNN.bi4 role.  Match that exact frame basename,
    # and only when the sealed table has one content identity for it.  This is
    # an alias join; the frame is still deferred and is never opened here.
    if source.name.startswith("Part_") and source.suffix.lower() == ".bi4":
        frame_candidates = [item for item in table.items
                            if Path(str(item.get("source_path_provenance", ""))).name == source.name
                            and item.get("source_sha256")
                            and item.get("deferred_content")]
        if frame_candidates and len({str(item.get("source_sha256")) for item in frame_candidates}) == 1:
            item = sorted(frame_candidates,
                          key=lambda value: str(value.get("target_relative_path")))[0]
            aliases = list(item.get("source_path_aliases", []))
            if str(source) not in aliases:
                aliases.append(str(source))
                item["source_path_aliases"] = aliases
            return item
    payload = EXECUTOR_V1._payload_like(source, parent)
    # A few historical request records put the size of their deferred
    # *result* beside a small JSON request pointer.  V1 consequently labels
    # the pointer ``deferred`` even though the existing source file itself is
    # bounded metadata and must be traversed for its actionable child paths
    # (ROOT197 exposed this exact shape).  Trust the observed bounded JSON
    # file for traversal while retaining the declared SHA/stat contract; do
    # not apply this exception to non-JSON or oversized files.
    if (payload and source.suffix.lower() == ".json" and source.is_file()
            and source.stat().st_size <= MAX_METADATA_BYTES):
        payload = False
    sha = _declared_sha(parent)
    # CURRENT336 uses ``recomputed_sha256`` for its bounded manifest/XML/
    # receipt entries.  Accept that spelling only for a small metadata file;
    # payload roles still require their explicit producer SHA and remain
    # deferred.
    if (sha is None and not payload and source.suffix.lower() == ".json" and
            source.is_file() and source.stat().st_size <= MAX_METADATA_BYTES):
        candidate = parent.get("recomputed_sha256")
        if (isinstance(candidate, str) and len(candidate) == 64 and
                all(char in "0123456789abcdef" for char in candidate)):
            sha = candidate
    if sha is None:
        sha = _KNOWN_PATH_SHAS.get(_source_key(source))
    if sha is None and source.is_file() and not payload:
        sha = EXECUTOR_V1._sha(source, "V6 nested metadata")
    if sha is None:
        raise Root213ExecutorV6Error(
            f"nested actionable path has no declared SHA at {_pointer(pointer)}: {source}")
    target = EXECUTOR_V1._target_for_closure(source, sha, payload=payload)
    if table.get(source) is not None:
        return table.get(source)
    # Nested CURRENT336/sidecar entries often carry only a recomputed SHA;
    # they do not repeat the source stat contract.  For a bounded JSON file
    # it is safe to capture the current full stat at this metadata-only
    # preparation point.  Deferred payloads still require the parent's
    # explicit stat and never fall through to a content read here.
    stat = None
    if isinstance(parent, Mapping):
        for stat_key in ("stat", "source_stat_expected", "source_stat"):
            candidate_stat = parent.get(stat_key)
            if isinstance(candidate_stat, Mapping):
                stat = candidate_stat
                break
        if stat is None:
            # Some deferred solver logs put the stat fields beside ``path``
            # rather than under a ``stat`` object.  Preserve that declared
            # placeholder contract; do not open or synthesize the missing
            # Run.out content.
            inline_stat = {
                key: parent[key] for key in
                ("bytes", "mode_bits", "mtime_ns", "ctime_ns", "st_dev", "st_ino")
                if key in parent and isinstance(parent[key], (int, float))
                and not isinstance(parent[key], bool)
            }
            if {"bytes", "mode_bits", "mtime_ns"}.issubset(inline_stat):
                stat = inline_stat
    if stat is None and not payload and source.is_file() and source.stat().st_size <= MAX_METADATA_BYTES:
        stat = EXECUTOR_V1._full_stat(source, "V6 bounded nested metadata")
    role = f"recursive_metadata_{hashlib.sha256(_source_key(source).encode()).hexdigest()[:16]}"
    item = table.add(
        role=role, source=source, target=target, sha256=sha, stat=stat,
        kind="deferred_source_placeholder" if payload else "bounded_nested_metadata",
        deferred=payload, placeholder=payload,
    )
    item["nested_discovery_pointer"] = _pointer(pointer)
    item["nested_discovery_policy"] = "V6_RECURSIVE_ACTIONABLE_PATH"
    return item


def _collect_recursive_metadata(table: Any) -> list[dict[str, Any]]:
    """Expand the bounded JSON graph without opening payload roles."""
    global _KNOWN_PATH_SHAS
    queue: list[Path] = []
    _KNOWN_PATH_SHAS = {}
    # A producer request can intentionally carry PENDING for a deferred raw
    # frame.  Build a bounded metadata-only index first so the same frame's
    # producer/worker request (which has the immutable declared SHA) supplies
    # the binding.  We never hash the raw file here.
    def index(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                if (str(key) == "path" and isinstance(child, str) and
                        child.startswith("/")):
                    candidate = None
                    for sha_key in ("file_sha256", "sha256", "expected_sha256",
                                    "producer_declared_sha256", "source_sha256",
                                    "producer_sha256", "content_sha256",
                                    "recomputed_sha256"):
                        raw = value.get(sha_key)
                        if (isinstance(raw, str) and len(raw) == 64 and
                                all(c in "0123456789abcdef" for c in raw)):
                            candidate = raw
                            break
                    if candidate is not None and not _is_live_ledger(Path(child)):
                        _KNOWN_PATH_SHAS[_source_key(Path(child))] = candidate
                index(child)
        elif isinstance(value, list):
            for child in value:
                index(child)
    for item in list(table.items):
        source = Path(item["source_path_provenance"])
        if _is_metadata_source(item, source) and not _is_live_ledger(source):
            try:
                index(EXECUTOR_V1._json(source, "V6 SHA index"))
            except Exception:
                # The actual recursive pass below reports the bounded source
                # error with its exact role/path; do not hide it here.
                pass
    root_roles = {
        "root200_inner_request", "v12_semantic_sidecar", "frozen_v15_request",
        "current336_actionable_metadata", "producer_179c_request",
    }
    for item in list(table.items):
        source = Path(item["source_path_provenance"])
        role = str(item.get("logical_role", ""))
        if ((role in root_roles or role.startswith("closure_") or
             role.startswith("recursive_metadata_")) and
                _is_metadata_source(item, source) and not _is_live_ledger(source)):
            queue.append(source)
    # V5 can already contain a bounded JSON role before the recursive walk
    # discovers its parent (for example an initial geometry-evidence file).
    # Seed those predeclared metadata sources too; otherwise the walk only
    # visits newly-added children and misses actionable paths nested inside an
    # existing role.  This remains source-only and bounded by
    # ``_is_metadata_source``; payload/deferred roles and live ledger state
    # are excluded.
    for item in list(table.items):
        source = Path(item["source_path_provenance"])
        if _is_metadata_source(item, source) and not _is_live_ledger(source):
            queue.append(source)
    seen: set[str] = set()
    discoveries: list[dict[str, Any]] = []
    def queue_child(pointer: tuple[str, ...], child: Path, item: Mapping[str, Any]) -> bool:
        if (item.get("deferred_content") or child.suffix.lower() != ".json" or
                child.name.lower().endswith("manifest.json") or
                not child.is_file() or child.stat().st_size > MAX_METADATA_BYTES):
            return False
        lowered = {str(part).lower() for part in pointer}
        name = child.name.lower()
        # Embedded worker requests are the remaining V2 call-graph edge even
        # when their containing field is not named ``source_request``.
        return (_should_recurse(pointer) or "request" in name or
                "sidecar" in name or "embedded_worker_request" in lowered)
    while queue:
        source = queue.pop(0)
        key = _source_key(source)
        if key in seen:
            continue
        seen.add(key)
        if source.is_symlink() or not source.is_file():
            raise Root213ExecutorV6Error(f"nested metadata source is unavailable: {source}")
        if source.stat().st_size > MAX_METADATA_BYTES:
            continue
        value = EXECUTOR_V1._json(source, "V6 recursive metadata")
        for raw_path, parent, pointer in _strict_path_records_v6(value):
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
            # A nested metadata source may already be present in the
            # immutable V5 table.  It still has to be traversed: the
            # previous ``before is None`` gate silently skipped those
            # predeclared files, leaving their own actionable children
            # absent from the source map (ROOT230's E00864/F1 input
            # manifest failure exposed this case).  ``seen`` below keeps
            # this unconditional queueing bounded and deterministic.
            if (queue_child(pointer, child, item) and not _is_live_ledger(child)):
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
        raise Root213ExecutorV6Error("V2/V3 rewriters are not installed")
    checks: list[dict[str, Any]] = []
    for item in list(table.items):
        source = Path(item["source_path_provenance"])
        role = str(item.get("logical_role", ""))
        if (
            not (role in {"root200_inner_request", "v12_semantic_sidecar", "frozen_v15_request",
                          "current336_actionable_metadata", "producer_179c_request"}
                 or role.startswith("closure_") or role.startswith("recursive_metadata_"))
            or not _is_metadata_source(item, source) or _is_live_ledger(source)
        ):
            continue
        value = _rebase_generated_outputs(
            EXECUTOR_V1._json(source, "V6 preflight metadata"), root)
        bindings: list[dict[str, Any]] = []
        rewrite = top_level_rewrite if item.get("logical_role") == "root200_inner_request" else nested_rewrite
        # Normally collection has already sealed every nested path.  A
        # source may nevertheless be a predeclared table role whose parent
        # was not in the initial queue (or a missing sibling-worktree view).
        # On that precise V2 error, recover only the path and SHA-bearing
        # mapping from this bounded JSON value, then retry with the expanded
        # source map.  Unknown/no-SHA paths still fail closed.
        # A single metadata object can legitimately expose several nested
        # historical request edges.  Add one strictly bound edge per retry,
        # with a finite ceiling to prevent an accidental cycle from becoming
        # an unbounded preflight.
        for rewrite_attempt in range(256):
            try:
                rewritten = rewrite(
                    value, root=root, source_map=source_map, role_by_target={},
                    bindings=bindings, parts=())
                break
            except Exception as error:
                if rewrite_attempt >= 255:
                    raise
                match = re.search(r"unbound actionable request path at .*?:\s*(/.*)$",
                                  str(error))
                if match is None:
                    raise
                missing = Path(match.group(1).strip())
                candidates = [
                    (raw_path, parent, pointer)
                    for raw_path, parent, pointer in _strict_path_records_v6(value)
                    if Path(raw_path).expanduser() == missing
                ]
                if not candidates:
                    # V3's alias preparation can surface a nested path from
                    # a sibling metadata view rather than the object being
                    # rewritten.  Search the already bounded table sources
                    # for that exact path contract; never infer a SHA from a
                    # missing/large payload here.
                    for scan_item in list(table.items):
                        scan_source = Path(scan_item["source_path_provenance"])
                        if (not _is_metadata_source(scan_item, scan_source)
                                or _is_live_ledger(scan_source)):
                            continue
                        scan_value = EXECUTOR_V1._json(scan_source, "V6 path-contract scan")
                        candidates.extend(
                            (raw_path, parent, pointer)
                            for raw_path, parent, pointer in _strict_path_records_v6(scan_value)
                            if Path(raw_path).expanduser() == missing
                        )
                        if candidates:
                            break
                if not candidates:
                    raise
                # The same helper may be referenced by several nested roles.
                # They are safe to coalesce only when every occurrence names
                # the same file and does not disagree on an explicit SHA.
                raw_path, parent, pointer = candidates[0]
                declared_values = {
                    _declared_sha(candidate_parent)
                    for _, candidate_parent, _ in candidates
                }
                if len(declared_values - {None}) > 1:
                    raise
                _add_recursive_role(table, Path(raw_path), parent, root, pointer)
                source_map = _source_map(table, root)
                bindings.clear()
        if not isinstance(rewritten, dict):
            raise Root213ExecutorV6Error(f"rewritten metadata is not an object: {source}")
        # Every non-exempt path must be target-local after this exact rewrite.
        _assert_closed(rewritten, root)
        checks.append({
            "source_path": str(source), "source_sha256": EXECUTOR_V1._sha(source, "V6 preflight"),
            "binding_count": len(bindings), "status": "PASS_REWRITE_PREFLIGHT",
        })
    return checks


def _prepare_administrative_ledger_reference(table: Any, root: Path) -> dict[str, Any] | None:
    """Remove the mutable live ledger from the scientific copy set.

    The producer request carries ``parent_resource_binding.ledger_path`` for
    the outer parent.  Copying that file into the private bundle makes the
    input hash change as soon as the parent appends its terminal charge.  V6
    therefore replaces every live-ledger artifact with a target-local,
    immutable *reference* sidecar containing only the pre-reservation SHA and
    stat.  It is explicitly deferred/admin-only and is never presented as a
    scientific ledger snapshot or used to charge a second ledger owner.
    """
    live_items = [item for item in list(table.items)
                  if _is_live_ledger(Path(str(item.get("source_path_provenance", ""))))]
    if not live_items:
        return None
    first = live_items[0]
    source = Path(str(first["source_path_provenance"])).expanduser()
    source_sha = first.get("source_sha256")
    source_stat = dict(first.get("source_stat_provenance", {}))
    if not isinstance(source_sha, str) or len(source_sha) != 64:
        raise Root213ExecutorV6Error("live administrative ledger lacks a bound pre-reservation SHA")
    for item in live_items:
        table.items.remove(item)
        table.by_source.pop(_source_key(Path(str(item["source_path_provenance"]))), None)
        table.by_target.pop(str(item.get("target_relative_path")), None)
    target_rel = "runtime/administrative-ledger-reference-v6.json"
    if table.get(source) is not None:
        raise Root213ExecutorV6Error("live ledger remained in V6 source table")
    item = table.add(
        role="administrative_ledger_reference_v6", source=source,
        target=target_rel, sha256=source_sha, stat=source_stat,
        kind="administrative_provenance_reference", deferred=True, placeholder=True,
    )
    item.update({
        "administrative_provenance": True,
        "scientific_input": False,
        "content_read_by_manifest": False,
        "content_verification_phase": "OUTER_PARENT_LEDGER_ONLY",
        "mutable_source_policy": "NEVER_COPY_LIVE_LEDGER",
        "frozen_reference_sha256": source_sha,
        "frozen_reference_stat": source_stat,
    })
    reference = root / target_rel
    if reference.exists() or reference.is_symlink():
        raise Root213ExecutorV6Error(f"refusing existing administrative ledger reference: {reference}")
    reference.parent.mkdir(parents=True, exist_ok=True)
    reference.write_text(json.dumps({
        "schema": "ds02.stage2.administrative-ledger-reference.v1",
        "source_path_provenance": str(source),
        "source_sha256_pre_reservation": source_sha,
        "source_stat_pre_reservation": source_stat,
        "content_copied": False,
        "scientific_input": False,
        "outer_parent_ledger_owner": True,
        "terminal_ledger_mutation": "OUTER_PARENT_ONLY",
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    item["reference_target_stat"] = EXECUTOR_V1._full_stat(reference, "V6 ledger reference")
    item["reference_target_sha256"] = EXECUTOR_V1._sha(reference, "V6 ledger reference")
    return item


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
                    raise Root213ExecutorV6Error(
                        f"unbound nested metadata path at {_pointer(pointer)}: {child}") from error
            _assert_closed(child, root, pointer)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_closed(child, root, parts + (str(index),))


def _directory_rebind_v6(parts: tuple[str, ...], root: Path) -> Path | None:
    """Bind the decoder scratch directory declared by the copied worker.

    It is a directory anchor, not a source file.  The old V2 policy only
    knew proof/output roots; the actual V66 worker also records
    ``runtime.scratch.root``.  Keep the alias narrow and attempt-owned.
    """
    lower = [str(part).lower() for part in parts]
    if lower and lower[-1] == "root" and ("scratch" in lower or "decoder_scratch" in lower):
        return root / "runtime" / "scratch"
    if lower and lower[-1] == "root" and any(
            item.endswith("_raw_scope") for item in lower):
        return root / "evidence" / "raw-scope"
    if (lower and (lower[-1] in {"raw_root", "data_root", "raw_scope", "source_raw_root"}
                   or (lower[-1] == "root" and any(
                       item in {"raw_source", "raw_binding", "bundle_target"}
                       for item in lower)))):
        return root / "evidence" / "raw-scope"
    if lower and "filesystem_headroom" in lower:
        # The V2 generic ``path`` branch invokes this hook without the path
        # key; support both direct and omitted-key forms.
        label_parts = lower[:-1] if lower[-1] == "path" else lower
        label = next((item for item in reversed(label_parts)
                      if item in {"home", "external", "nvme", "scratch"}), "policy")
        return root / "runtime" / "filesystem-headroom" / label
    return V4.V3._directory_rebind_v3(parts, root)


def _replace_v2_entrypoint(table: Any) -> None:
    old = None
    for item in table.items:
        if item.get("logical_role") == "portable_rebind_v2_entrypoint":
            old = item
            break
    if old is None:
        raise Root213ExecutorV6Error("V4 manifest lacks portable V2 entrypoint role")
    old_source = _source_key(Path(old["source_path_provenance"]))
    old_target = old["target_relative_path"]
    table.by_source.pop(old_source, None)
    table.by_target.pop(old_target, None)
    old.update({
        "source_path_provenance": str(V6_RUNTIME_SCRIPT),
        "source_sha256": EXECUTOR_V1._sha(V6_RUNTIME_SCRIPT, "V6 runtime entrypoint"),
        "source_stat_provenance": EXECUTOR_V1._full_stat(V6_RUNTIME_SCRIPT, "V6 runtime entrypoint"),
        "target_relative_path": f"runtime/{V6_RUNTIME_SCRIPT.name}",
        "source_kind": "runtime_source_forward_v6",
        "content_read_by_manifest": True,
        "deferred_content": False,
        "placeholder_only": False,
    })
    table.by_source[_source_key(V6_RUNTIME_SCRIPT)] = old
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


def _make_manifest_v6(request: Mapping[str, Any], root: Path,
                      reservation_started: float):
    manifest_path, contract_path, built = V4._make_manifest_v4(
        request, root, reservation_started)
    table = built["table"]
    ledger_reference = _prepare_administrative_ledger_reference(table, root)
    _replace_v2_entrypoint(table)
    discoveries = _collect_recursive_metadata(table)
    preflight = _preflight_recursive_rewrites(table, root)
    manifest = copy.deepcopy(built["manifest"])
    manifest["artifacts"] = table.items
    manifest["forward_version"] = "ROOT230_V6_RECURSIVE_METADATA_CLOSURE"
    manifest["forward_of"] = {
        "manifest_path": str(manifest_path), "contract_path": str(contract_path),
        "manifest_sha256": EXECUTOR_V1._sha(Path(manifest_path), "V4 manifest"),
        "contract_sha256": EXECUTOR_V1._sha(Path(contract_path), "V4 contract"),
        "immutable": True,
    }
    manifest["recursive_metadata_closure"] = {
        "path_policy": "ALL_ACTIONABLE_PATHS_INCLUDING_CASE_MANIFESTS_AND_HISTORICAL_SIDECARS",
        "non_actionable_contexts": sorted(NON_ACTIONABLE_CONTEXTS),
        "discovered_roles": discoveries,
        "rewrite_preflight": preflight,
        "bounded_json_bytes": MAX_METADATA_BYTES,
        "payload_content_read": False,
        "administrative_ledger_reference": (
            {"logical_role": ledger_reference["logical_role"],
             "target_relative_path": ledger_reference["target_relative_path"],
             "source_sha256_pre_reservation": ledger_reference["source_sha256"],
             "source_stat_pre_reservation": ledger_reference["source_stat_provenance"],
             "content_copied": False,
             "scientific_input": False,
             "outer_parent_ledger_only": True}
            if ledger_reference is not None else None),
    }
    manifest["sha256"] = _canonical(manifest)
    v6_manifest = root / "metadata" / "root213-copy-manifest-v6.json"
    v6_contract = root / "metadata" / "root213-copy-contract-v6.json"
    _write_new(v6_manifest, manifest)
    contract = REBIND_V1.build_contract(
        manifest_path=v6_manifest, relocated_root=root, output=v6_contract,
        contract_id=request["attempt_id"])
    built["manifest"] = manifest
    built["contract"] = contract
    built["v4_manifest"] = str(manifest_path)
    built["v4_contract"] = str(contract_path)
    built["v6_manifest"] = str(v6_manifest)
    built["v6_contract"] = str(v6_contract)
    built["recursive_metadata_discoveries"] = discoveries
    built["recursive_rewrite_preflight"] = preflight
    return v6_manifest, v6_contract, built


def _install_hooks() -> None:
    global _OLD_REPORT_SCHEMA, _OLD_PROVENANCE_KEYS
    if _OLD_REPORT_SCHEMA is None:
        _OLD_REPORT_SCHEMA = str(V2_EXECUTOR.REPORT_SCHEMA)
    V4._install_hooks()
    V2_EXECUTOR.REPORT_SCHEMA = REPORT_SCHEMA
    if _OLD_PROVENANCE_KEYS is None:
        _OLD_PROVENANCE_KEYS = set(REBIND_V2.PROVENANCE_KEYS)
    REBIND_V2.PROVENANCE_KEYS.update(NON_ACTIONABLE_CONTEXTS)
    REBIND_V2._directory_rebind = _directory_rebind_v6
    EXECUTOR_V1._path_records = _strict_path_records_v6
    EXECUTOR_V1._make_manifest = _make_manifest_v6


def _restore_hooks() -> None:
    global _OLD_REPORT_SCHEMA, _OLD_PROVENANCE_KEYS
    V4._restore_hooks()
    if _OLD_REPORT_SCHEMA is not None:
        V2_EXECUTOR.REPORT_SCHEMA = _OLD_REPORT_SCHEMA
    if _OLD_PROVENANCE_KEYS is not None:
        REBIND_V2.PROVENANCE_KEYS.clear()
        REBIND_V2.PROVENANCE_KEYS.update(_OLD_PROVENANCE_KEYS)
    _OLD_PROVENANCE_KEYS = None
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
                V4.Root213ExecutorV4Error, Root213ExecutorV6Error,
                OSError, ValueError, KeyError) as error:
            print(f"ROOT213 portable typed executor V6: {error}", file=sys.stderr)
            return 2
    finally:
        _restore_hooks()


if __name__ == "__main__":
    raise SystemExit(main())
