#!/usr/bin/env python3
"""Target-side V6 entrypoint for recursive metadata rebinding.

The V4 executor seals the source roles before this file is copied.  V6 keeps
the consumed V2 worker as a sibling, but replaces its two small-contract
views with a recursive target-side view.  This matters when a semantic
sidecar points at another request under a historical/provenance object: the
outer request can be target-relative while the nested request would otherwise
retain an original absolute path.

Only bounded JSON metadata is materialised here.  Payload roles keep their
parent-attested SHA/stat and remain deferred.  Every path that is not in the
explicit, non-actionable provenance allowlist is resolved through the sealed
source map; an unknown path fails closed.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping
import importlib.util
import sys


SCRIPT = Path(__file__).resolve()
V2_NAME = "ds_data02_stage2_f2_typed_only_portable_rebind_v2.py"
V2_PATH = SCRIPT.with_name(V2_NAME)


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load copied sibling: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


V2 = _load(V2_PATH, "ds02_relocated_portable_rebind_v2_for_v6")
MAX_METADATA_BYTES = int(V2.MAX_METADATA_BYTES)
_V2_ORIGINAL_DIRECTORY_REBIND = V2._directory_rebind

# These fields are historical annotations by contract.  The name
# ``historical_provenance`` is deliberately absent: ROOT228 demonstrated that
# its path is consumed by a nested V2 request and must be copied/rebound.
NON_ACTIONABLE_CONTEXTS = frozenset({
    "original_roots", "source_provenance", "provenance", "old_absolute_paths",
    "source_path_provenance", "argv0_provenance", "resolved_provenance",
    "git_at_launch",
    "receipt", "observed_receipt", "root397_observation", "report",
    "upstream_qa103_observation", "solver_log", "case_xmf", "trace",
    "expected_artifacts", "home_receipt",
})
RECURSIVE_CONTEXTS = frozenset({
    "historical_provenance", "source_metadata_provenance", "source_metadata",
    "v12_forward", "semantic_sidecar", "source_request", "replaces_request",
    "current_manifest", "frozen", "profile_rebind", "root194_sidecar",
    # CURRENT336 is a bounded metadata index whose case entries contain the
    # actual manifest/XMF/receipt paths.  V5 stopped one edge too early at
    # ``cases`` and therefore left E00864/manifest.json in the copied child.
    "cases", "manifest", "case", "source_binding", "source_bindings", "v12_forward",
})
LEAF_CONTEXTS = frozenset({
    "producer_nested_report", "producer_report", "worker_summary",
    "execution_receipt", "completed_receipt", "parent_report", "root_proof",
    "terminal_evidence", "terminal_delta",
})


def _pointer(parts: tuple[str, ...]) -> str:
    return "" if not parts else "".join(
        "/" + str(part).replace("~", "~0").replace("/", "~1") for part in parts
    )


def _context_is_non_actionable(parts: tuple[str, ...]) -> bool:
    return any(str(part).lower() in NON_ACTIONABLE_CONTEXTS for part in parts)


def _should_recurse(parts: tuple[str, ...]) -> bool:
    lowered = {str(part).lower() for part in parts}
    if lowered & LEAF_CONTEXTS:
        return False
    return bool(lowered & RECURSIVE_CONTEXTS)


def _closed(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def _rebase_generated_outputs(value: Any, root: Path,
                              parts: tuple[str, ...] = ()) -> Any:
    """Map attempt-created trace paths into the private runtime namespace."""
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


def _directory_rebind_v6(parts: tuple[str, ...], root: Path) -> Path | None:
    lower = [str(part).lower() for part in parts]
    if lower and lower[-1] == "root" and ("scratch" in lower or "decoder_scratch" in lower):
        return root / "runtime" / "scratch"
    if lower and lower[-1] == "root" and any(
            item.endswith("_raw_scope") for item in lower):
        return root / "evidence" / "raw-scope"
    # CURRENT336's raw_root/data_root entries are directory anchors.  They
    # are not files to copy and must resolve to the attempt-owned deferred
    # raw scope, otherwise the strict V2 rewriter reports them as unbound.
    if (lower and (lower[-1] in {"raw_root", "data_root", "raw_scope", "source_raw_root"}
                   or (lower[-1] == "root" and any(
                       item in {"raw_source", "raw_binding", "bundle_target"}
                       for item in lower)))):
        return root / "evidence" / "raw-scope"
    if lower and "filesystem_headroom" in lower:
        # V2 calls the directory hook from its generic ``path`` branch with
        # the path key omitted; accept both that shape and the direct
        # directory-key shape used by newer request wrappers.
        label_parts = lower[:-1] if lower[-1] == "path" else lower
        label = next((item for item in reversed(label_parts)
                      if item in {"home", "external", "nvme", "scratch"}), "policy")
        return root / "runtime" / "filesystem-headroom" / label
    return _V2_ORIGINAL_DIRECTORY_REBIND(parts, root)


def _assert_rewritten_paths_closed(value: Any, root: Path,
                                   parts: tuple[str, ...] = ()) -> None:
    """Check the same path classes that V2's rewriter can consume.

    Arbitrary strings are not interpreted as paths.  Absolute ``path`` values
    and directory anchors are checked because those are the only values the
    real V2 loader opens or turns into a target namespace.
    """
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
                if _context_is_non_actionable(parts):
                    continue
                if not _closed(Path(child), root):
                    raise V2.PortableRebindV2Error(
                        f"recursive V6 path escapes target root at {_pointer(pointer)}: {child}")
            _assert_rewritten_paths_closed(child, root, pointer)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_rewritten_paths_closed(child, root, parts + (str(index),))


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _target_view(root: Path, source: Path, label: str) -> Path:
    token = hashlib.sha256(str(source).encode("utf-8")).hexdigest()[:24]
    target = root / "runtime" / f".v6-rebased-{label}-{token}.json"
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise V2.PortableRebindV2Error(f"refusing non-file V6 nested view: {target}")
    return target


def _recursive_rebase(path: Path, *, root: Path,
                      source_map: Mapping[str, tuple[Mapping[str, Any], Path]],
                      label: str) -> tuple[Path, dict[str, Any], str]:
    """Rewrite a bounded JSON graph to target-local views.

    The source map is the sealed V1/V2 role map.  A nested JSON path is first
    materialised as a target-local view, then the parent view points at that
    view.  Thus every nested call to V2's ``_rewrite_request`` receives the
    same closed map and no original checkout path can survive accidentally.
    """
    cache: dict[str, Path] = {}
    in_progress: set[str] = set()
    rebased_map: dict[str, tuple[Mapping[str, Any], Path]] = dict(source_map)

    def materialise(source: Path, nested_label: str) -> Path:
        source_abs = os.path.abspath(str(source))
        if source_abs in cache:
            return cache[source_abs]
        if source_abs in in_progress:
            raise V2.PortableRebindV2Error(
                f"cyclic recursive metadata path at {source}")
        if source.is_symlink() or not source.is_file():
            raise V2.PortableRebindV2Error(
                f"recursive metadata source is not a regular file: {source}")
        if source.stat().st_size > MAX_METADATA_BYTES:
            raise V2.PortableRebindV2Error(
                f"recursive metadata exceeds bounded JSON limit: {source}")
        in_progress.add(source_abs)
        raw = V2._json(source, f"V6 nested {nested_label}")
        target = _target_view(root, source, nested_label)
        # Cache before walking children so a cycle is diagnosed rather than
        # causing unbounded recursion.
        cache[source_abs] = target
        role = source_map.get(source_abs)
        if role is not None:
            rebased_map[source_abs] = (role[0], target)

        # Discover JSON children before rewriting this parent.  A declared
        # target can be a deferred payload; only JSON metadata is opened.
        def children(value: Any, parts: tuple[str, ...] = ()):
            if isinstance(value, Mapping):
                for key, child in value.items():
                    pointer = parts + (str(key),)
                    if (str(key) == "path" and isinstance(child, str) and
                            child.startswith("/") and not _context_is_non_actionable(parts)):
                        mapped = source_map.get(os.path.abspath(child))
                        if mapped is not None:
                            child_source = Path(mapped[0].get("source_path_provenance", child))
                            if (_should_recurse(parts) and
                                    child_source.suffix.lower() == ".json" and
                                    child_source.is_file() and
                                    child_source.stat().st_size <= MAX_METADATA_BYTES):
                                child_target = materialise(child_source,
                                                           f"{nested_label}-{len(cache)}")
                                rebased_map[os.path.abspath(str(child_source))] = (
                                    mapped[0], child_target)
                    yield from children(child, pointer)
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    yield from children(child, parts + (str(index),))

        list(children(raw))
        # Use the byte-frozen V2 rewriter; its exact allowlist remains the
        # authority for non-actionable provenance fields.
        bindings: list[dict[str, Any]] = []
        rewritten = V2._rewrite_request(
            _rebase_generated_outputs(raw, root), root=root, source_map=rebased_map, role_by_target={},
            bindings=bindings, parts=())
        if not isinstance(rewritten, dict):
            raise V2.PortableRebindV2Error(
                f"recursive V6 view is not an object: {source}")
        _assert_rewritten_paths_closed(rewritten, root)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(rewritten, indent=2, sort_keys=True,
                                     ensure_ascii=True, allow_nan=False) + "\n",
                          encoding="utf-8")
        in_progress.remove(source_abs)
        return target

    target = materialise(path, label)
    value = V2._json(target, f"V6 rebased {label}")
    return target, value, _sha(path)


def _patched_rebase_runtime_json(path: Path, *, root: Path,
                                  source_map: Mapping[str, tuple[Mapping[str, Any], Path]],
                                  label: str) -> tuple[Path, dict[str, Any], str]:
    (root / "runtime" / "scratch").mkdir(parents=True, exist_ok=True)
    return _recursive_rebase(path, root=root, source_map=source_map, label=label)


def main(argv: list[str] | None = None) -> int:
    # The copied V2 CLI is authoritative for argument and worker semantics.
    # Patch only the nested metadata view before dispatch; all V8/V12/scorer
    # validation and pdeath/stream handling remains the consumed V2 code.
    V2._directory_rebind = _directory_rebind_v6
    V2.PROVENANCE_KEYS.update(NON_ACTIONABLE_CONTEXTS)
    V2._rebase_runtime_json = _patched_rebase_runtime_json
    return int(V2.main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
