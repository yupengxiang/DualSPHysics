#!/usr/bin/env python3
"""V60 raw-to-typed worker adapter.

The native V2 converter was written for a directory containing only the raw
Part files.  A relocated bundle also contains the copied runtime and request
metadata, so passing the bundle root to its recursive tree manifest changes
the producer identity.  This adapter keeps the V2 converter and label code
unchanged and narrows only the manifest callback to the frozen producer raw
file list supplied by the parent guard.

The adapter is deliberately fail-closed.  It never searches the original
worktree and it will not infer a raw scope from a glob.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import ModuleType
from typing import Any, Callable, Iterable


class V60WorkerError(RuntimeError):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise V60WorkerError(f"JSON object required: {path}")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                return digest.hexdigest()
            digest.update(block)


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _normalise_scope(scope: dict[str, Any]) -> tuple[Path, list[str], str]:
    root_text = scope.get("root")
    paths = scope.get("paths")
    expected = scope.get("expected_tree_sha256")
    if not isinstance(root_text, str) or not root_text:
        raise V60WorkerError("v60_raw_scope.root is required")
    if not isinstance(paths, list) or not paths or not all(
        isinstance(item, str) and item for item in paths
    ):
        raise V60WorkerError("v60_raw_scope.paths must be a non-empty string list")
    if len(set(paths)) != len(paths):
        raise V60WorkerError("v60_raw_scope.paths contains duplicates")
    if paths != sorted(paths):
        raise V60WorkerError("v60_raw_scope.paths must be canonical sorted paths")
    if not isinstance(expected, str) or len(expected) != 64:
        raise V60WorkerError("v60_raw_scope.expected_tree_sha256 is required")
    root = Path(root_text)
    for relative in paths:
        candidate = Path(relative)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise V60WorkerError(f"raw scope escapes root: {relative}")
        if candidate.as_posix() != relative:
            raise V60WorkerError(f"raw scope path is not canonical: {relative}")
    return root, paths, expected


def scoped_raw_tree_manifest(root: Path, scope: dict[str, Any]) -> dict[str, Any]:
    """Hash exactly the producer raw scope, excluding copied code/metadata."""

    declared_root, paths, expected = _normalise_scope(scope)
    if root.resolve() != declared_root.resolve():
        raise V60WorkerError(
            f"raw manifest root differs from bound scope: {root} != {declared_root}"
        )
    if not root.is_dir():
        raise V60WorkerError(f"raw manifest root is not a directory: {root}")

    files: list[dict[str, Any]] = []
    for relative in paths:
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise V60WorkerError(f"raw scope member is not a regular file: {relative}")
        stat = path.stat()
        files.append(
            {
                "path": relative,
                "bytes": int(stat.st_size),
                "sha256": _sha256_file(path),
            }
        )
    tree_sha256 = _canonical_sha256(files)
    if tree_sha256 != expected:
        raise V60WorkerError(
            f"producer raw tree differs: observed={tree_sha256} expected={expected}"
        )
    return {
        "tree_sha256": tree_sha256,
        "file_count": len(files),
        "files": files,
        "scope": "TOP_LEVEL_PRODUCER_RAW_EXPLICIT_V60",
    }


def _load_module(path: Path, name: str) -> ModuleType:
    if not path.is_file():
        raise V60WorkerError(f"bound module is missing: {path}")
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise V60WorkerError(f"cannot load bound module: {path}")
    module = importlib.util.module_from_spec(spec)
    # The V2 worker dynamically imports siblings by the module names recorded
    # in its request.  Registering this module is required; no sys.path or
    # original-worktree fallback is permitted.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _bound_module_paths(request: dict[str, Any]) -> dict[str, Path]:
    modules = request.get("modules")
    if not isinstance(modules, dict):
        raise V60WorkerError("worker request modules object is missing")
    result: dict[str, Path] = {}
    for role in ("worker", "raw_converter", "v14_operator", "v15_operator", "v16_operator"):
        value = modules.get(role)
        if not isinstance(value, dict) or not isinstance(value.get("path"), str):
            raise V60WorkerError(f"worker module binding is missing: {role}")
        result[role] = Path(value["path"])
    return result


def _assert_actionable_modules(request: dict[str, Any], modules: dict[str, Path]) -> None:
    binding = request.get("v60_worker_binding")
    if not isinstance(binding, dict):
        raise V60WorkerError("v60_worker_binding is missing")
    root_text = binding.get("code_root")
    if not isinstance(root_text, str) or not root_text:
        raise V60WorkerError("v60_worker_binding.code_root is missing")
    code_root = Path(root_text).resolve()
    expected_sha = binding.get("module_sha256")
    if not isinstance(expected_sha, dict):
        raise V60WorkerError("v60_worker_binding.module_sha256 is missing")
    for role, path in modules.items():
        resolved = path.resolve()
        try:
            resolved.relative_to(code_root)
        except ValueError as exc:
            raise V60WorkerError(
                f"actionable module is outside copied worker directory: {path}"
            ) from exc
        observed = _sha256_file(resolved)
        if observed != expected_sha.get(role):
            raise V60WorkerError(f"module SHA differs for {role}: {path}")


def _count_raw_named_outputs(output_dir: Path, scope_paths: Iterable[str]) -> int:
    """Count only raw-role names copied into the product output tree.

    Generated ``.h5``/``.xmf`` products are intentionally excluded.  A raw
    copy is evidence only when the exact producer-relative raw name appears
    under the child output directory.
    """

    names = {Path(item).name for item in scope_paths}
    count = 0
    if not output_dir.is_dir():
        return count
    for path in output_dir.rglob("*"):
        if path.is_file() and path.name in names:
            count += 1
    return count


def run(request_path: Path, output_dir: Path, *, io_slot_approved: bool = False, run_labels: bool = True) -> dict[str, Any]:
    request = _read_json(request_path)
    scope = request.get("v60_raw_scope")
    if not isinstance(scope, dict):
        raise V60WorkerError("v60_raw_scope is required")
    raw_root, scope_paths, expected_tree = _normalise_scope(scope)
    raw_binding = request.get("raw_binding")
    if not isinstance(raw_binding, dict) or raw_binding.get("data_root") != str(raw_root):
        raise V60WorkerError("raw_binding.data_root is not the bound scope root")
    if raw_binding.get("expected_raw_tree_sha256") != expected_tree:
        raise V60WorkerError("raw binding expected tree is not the scoped producer tree")

    modules = _bound_module_paths(request)
    _assert_actionable_modules(request, modules)
    binding = request["v60_worker_binding"]
    v2_path_text = binding.get("v2_worker_path")
    if not isinstance(v2_path_text, str):
        raise V60WorkerError("v60_worker_binding.v2_worker_path is missing")
    v2_path = Path(v2_path_text)
    if v2_path.resolve() != modules["worker"].resolve():
        raise V60WorkerError("v2 worker path differs from modules.worker")

    # The V2 script is the scientific worker.  Only its converter manifest
    # callback is replaced; all typed/label calculations remain the pinned
    # implementation bound by the request.
    v2 = _load_module(v2_path, "ds_data02_bound_f2_native_raw_to_typed_label_v2_v60")
    original_loader: Callable[..., ModuleType] = v2._load_module
    converter_path = modules["raw_converter"].resolve()

    def scoped_loader(path: Path, name: str) -> ModuleType:
        module = original_loader(path, name)
        if Path(path).resolve() == converter_path:
            module.raw_tree_manifest = lambda root: scoped_raw_tree_manifest(Path(root), scope)  # type: ignore[attr-defined]
        return module

    v2._load_module = scoped_loader
    try:
        result = v2.run(
            request_path,
            output_dir,
            io_slot_approved=io_slot_approved,
            run_labels=run_labels,
        )
    finally:
        v2._load_module = original_loader

    if not isinstance(result, dict):
        raise V60WorkerError("V2 worker returned a non-object result")
    result = dict(result)
    result["v60_raw_scope"] = {
        "file_count": len(scope_paths),
        "expected_tree_sha256": expected_tree,
        "scope": "TOP_LEVEL_PRODUCER_RAW_EXPLICIT_V60",
    }
    result["raw_copy_attempts"] = _count_raw_named_outputs(output_dir, scope_paths)
    if result["raw_copy_attempts"]:
        raise V60WorkerError("raw producer files appeared in generated product output")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run", choices=["run"])
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--io-slot-approved", action="store_true")
    parser.add_argument("--run-labels", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args(argv)
    try:
        result = run(
            args.request,
            args.output_dir,
            io_slot_approved=args.io_slot_approved,
            run_labels=args.run_labels,
        )
    except Exception as exc:  # CLI status is consumed by the parent guard.
        print(json.dumps({"status": "FAILED", "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
