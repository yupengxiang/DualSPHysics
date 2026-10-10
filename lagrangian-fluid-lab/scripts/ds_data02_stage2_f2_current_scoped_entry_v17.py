#!/usr/bin/env python3
"""Copied V17 entrypoint for a sealed CURRENT leaf.

This module is intentionally small and has no import path back to the source
checkout.  The V11 worker copies it beside the copied V15 and V2 modules and
invokes its real ``main``.  It validates the additive V17 runtime contract,
installs the CURRENT leaf recursion boundary in the copied V15 rebinder, and
then dispatches to the copied V2 ``main``.  V2 remains the authority for the
V8/V12/scorer and result semantics; this entrypoint only supplies the scoped
relocation boundary.

The source and target stat records are kept separate.  Device/inode and times
are expected to change during a copy, while bytes, SHA, regular-file status,
and mode are checked.  No source path is opened by this module.  A target
whose real path escapes the fresh namespace or is a symlink is rejected.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


MAX_METADATA_BYTES = 32 * 1024 * 1024
CONTRACT_SCHEMA = "ds02.stage2.f2-current-scoped-runtime-contract.v17"
REQUEST_MARKER = "v17_scoped_runtime"
HEX = frozenset("0123456789abcdef")


class CurrentScopedEntryError(RuntimeError):
    pass


def _safe_relative(value: Any, role: str) -> str:
    if not isinstance(value, str) or not value or value.startswith("/"):
        raise CurrentScopedEntryError(f"{role} must be relative")
    path = Path(value)
    if ".." in path.parts or path == Path("."):
        raise CurrentScopedEntryError(f"{role} escapes the copied root")
    return value


def _under(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def _target(root: Path, value: Any, role: str) -> Path:
    relative = _safe_relative(value, role)
    path = root / relative
    if not _under(path, root) or path.is_symlink() or not path.is_file():
        raise CurrentScopedEntryError(f"{role} is not a regular copied file: {path}")
    return path


def _stat(path: Path) -> dict[str, int]:
    if path.is_symlink() or not path.is_file():
        raise CurrentScopedEntryError(f"target is not a regular file: {path}")
    value = path.stat()
    return {
        "bytes": int(value.st_size),
        "mode_bits": int(value.st_mode & 0o7777),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
        "st_dev": int(value.st_dev),
        "st_ino": int(value.st_ino),
    }


def _sha(path: Path, *, maximum: int = MAX_METADATA_BYTES) -> str:
    stat = _stat(path)
    if stat["bytes"] > maximum:
        raise CurrentScopedEntryError(f"bounded copied file is too large: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path: Path, role: str) -> dict[str, Any]:
    stat = _stat(path)
    if stat["bytes"] > MAX_METADATA_BYTES:
        raise CurrentScopedEntryError(f"{role} exceeds metadata limit")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CurrentScopedEntryError(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise CurrentScopedEntryError(f"{role} must be an object")
    return value


def _load(path: Path, name: str) -> Any:
    if path.is_symlink() or not path.is_file():
        raise CurrentScopedEntryError(f"copied module is unavailable: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise CurrentScopedEntryError(f"cannot load copied module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _sha_value(value: Any, role: str) -> str:
    if (not isinstance(value, str) or len(value) != 64 or
            value != value.lower() or any(item not in HEX for item in value)):
        raise CurrentScopedEntryError(f"{role} is not a lowercase SHA-256")
    return value


def _canonical(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False, default=str).encode("utf-8")).hexdigest()


def _runtime_descriptor(inner: Mapping[str, Any]) -> Mapping[str, Any]:
    value = inner.get(REQUEST_MARKER)
    if not isinstance(value, Mapping):
        raise CurrentScopedEntryError("copied inner request lacks v17_scoped_runtime")
    if value.get("schema") != CONTRACT_SCHEMA:
        raise CurrentScopedEntryError("V17 runtime contract schema differs")
    if value.get("original_path_fallback") != "REJECT":
        raise CurrentScopedEntryError("V17 runtime permits original-path fallback")
    if value.get("nested_manifest_paths", {}).get("opened") is not False:
        raise CurrentScopedEntryError("V17 CURRENT leaf is not sealed")
    if value.get("nested_manifest_paths", {}).get("allowlist") != []:
        raise CurrentScopedEntryError("V17 CURRENT nested-path allowlist is not empty")
    return value


def _check_binding(root: Path, descriptor: Mapping[str, Any], key: str,
                   *, maximum: int = MAX_METADATA_BYTES) -> tuple[Path, dict[str, int]]:
    relative = descriptor.get(f"{key}_target_relative_path")
    if relative is None:
        relative = descriptor.get("target_relative_paths", {}).get(key)
    target = _target(root, relative, f"{key} target")
    expected = _sha_value(
        descriptor.get(f"{key}_sha256", descriptor.get("expected_sha256", {}).get(key)),
        f"{key} source SHA",
    )
    observed = _sha(target, maximum=maximum)
    if observed != expected:
        raise CurrentScopedEntryError(f"{key} copied SHA differs from sealed binding")
    source_stat = descriptor.get(f"{key}_source_stat", descriptor.get("source_stat", {}).get(key))
    if not isinstance(source_stat, Mapping):
        raise CurrentScopedEntryError(f"{key} lacks source stat provenance")
    source_bytes = int(source_stat.get("bytes", -1))
    source_mode = int(source_stat.get("mode_bits", -1))
    actual = _stat(target)
    if actual["bytes"] != source_bytes:
        raise CurrentScopedEntryError(f"{key} copied byte count differs from source stat")
    if actual["mode_bits"] != source_mode:
        raise CurrentScopedEntryError(f"{key} copied mode differs from source stat")
    # A target copy must not be a hardlink to a source path.  We do not stat or
    # open the source path here (that would violate the copied-runtime open
    # policy); the builder/parent records this as a post-copy identity check.
    return target, actual


def _validate_scoped_runtime(root: Path, inner: Mapping[str, Any]) -> dict[str, Any]:
    descriptor = _runtime_descriptor(inner)
    paths: dict[str, Path] = {}
    stats: dict[str, dict[str, int]] = {}
    # The real V2 imports this exact basename at module import time.  Validate
    # and load the genuine V1 sibling before importing V15/V2; a V15 alias in
    # this slot passes shallow fixtures but fails the copied production graph.
    for key in ("entrypoint", "v1", "v2", "v15", "leaf_module", "contract", "current"):
        target, actual = _check_binding(root, descriptor, key)
        paths[key] = target
        stats[key] = actual
    contract = _json(paths["contract"], "scoped V17 contract")
    if contract.get("schema") != CONTRACT_SCHEMA:
        raise CurrentScopedEntryError("copied V17 contract schema differs")
    if contract.get("sha256") != _canonical(contract):
        raise CurrentScopedEntryError("copied V17 contract canonical SHA differs")
    current_binding = contract.get("current_binding")
    if not isinstance(current_binding, Mapping):
        raise CurrentScopedEntryError("copied V17 contract lacks CURRENT binding")
    if current_binding.get("target_relative_path") != descriptor.get("current_target_relative_path"):
        raise CurrentScopedEntryError("CURRENT target differs between contract and runtime binding")
    if _sha(paths["current"]) != _sha_value(current_binding.get("sha256"), "CURRENT contract SHA"):
        raise CurrentScopedEntryError("copied CURRENT differs from sealed contract")
    target_stat = current_binding.get("target_stat")
    if isinstance(target_stat, Mapping) and dict(target_stat) != stats["current"]:
        raise CurrentScopedEntryError("copied CURRENT stat differs from sealed contract")
    return {"descriptor": descriptor, "paths": paths, "stats": stats,
            "contract": contract, "target_root": str(root)}


def _install_scoped_v2(v2: Any, v15: Any, runtime: Mapping[str, Any]) -> None:
    """Patch only the copied V2 rebasing hooks, preserving V2's real main."""
    original_rebase = getattr(v2, "_rebase_runtime_json", None)
    original_directory = getattr(v2, "_directory_rebind", None)
    if not callable(original_rebase) or not callable(original_directory):
        raise CurrentScopedEntryError("copied V2 lacks real rebasing hooks")
    scoped_should_recurse = getattr(v15, "_should_recurse", None)
    recursive_rebase = getattr(v15, "_recursive_rebase", None)
    v15_directory = getattr(v15, "_directory_rebind_v5", None)
    if not callable(scoped_should_recurse) or not callable(recursive_rebase):
        raise CurrentScopedEntryError("copied V15 lacks real recursive rebinder")

    def rebased(path: Path, *, root: Path, source_map: Mapping[str, tuple[Mapping[str, Any], Path]],
                label: str):
        old = getattr(v15, "_should_recurse")
        def scoped(parts: tuple[str, ...]) -> bool:
            lowered = {str(item).lower() for item in parts}
            if "current_manifest" in lowered or "current_manifest_binding" in lowered:
                return False
            return bool(old(parts))
        v15._should_recurse = scoped
        try:
            return recursive_rebase(path, root=root, source_map=source_map, label=label)
        finally:
            v15._should_recurse = old

    def directory(parts: tuple[str, ...], root: Path) -> Path | None:
        # Only this exact marker is the V12 output slot.  A nested or similarly
        # named marker is not silently redirected to the products directory.
        if tuple(str(item) for item in parts) == ("v12_forward", "output_root_rebind_v14"):
            return root / "products"
        if callable(v15_directory):
            return v15_directory(parts, root)
        return original_directory(parts, root)

    v2._rebase_runtime_json = rebased
    v2._directory_rebind = directory


def run(argv: Sequence[str]) -> dict[str, Any]:
    if not argv or argv[0] != "worker":
        raise CurrentScopedEntryError("V17 entry only supports the copied worker command")
    try:
        overlay_index = argv.index("--request")
        overlay_path = Path(argv[overlay_index + 1]).absolute()
    except (ValueError, IndexError) as error:
        raise CurrentScopedEntryError("worker command lacks --request") from error
    overlay = _json(overlay_path, "copied V2 overlay")
    root_value = overlay.get("relocated_root")
    if not isinstance(root_value, str) or not root_value.startswith("/"):
        raise CurrentScopedEntryError("copied overlay lacks absolute relocated root")
    root = Path(root_value).absolute()
    if root.is_symlink() or not root.is_dir():
        raise CurrentScopedEntryError("copied relocated root is unavailable")
    generated = overlay.get("request_binding", {}).get("generated_target_relative_path")
    inner_path = _target(root, generated, "generated V2 inner request")
    inner = _json(inner_path, "generated V2 inner request")
    checked = _validate_scoped_runtime(root, inner)
    paths = checked["paths"]
    # Import only target-side siblings.  The copied V15 import resolves its V2
    # sibling by filename, so the source builder places both beside each other.
    _load(paths["v1"], "ds02_copied_v17_v1")
    v15 = _load(paths["v15"], "ds02_copied_v17_v15")
    v2 = _load(paths["v2"], "ds02_copied_v17_v2")
    _install_scoped_v2(v2, v15, checked["descriptor"])
    result = int(v2.main(list(argv)))
    if result != 0:
        raise CurrentScopedEntryError(f"copied V2 main returned {result}")
    return {
        "schema": "ds02.stage2.f2-current-scoped-entry-result.v17",
        "status": "PASS_V17_SCOPED_ENTRY_DISPATCHED_V2_MAIN",
        "entrypoint": "CURRENT_SCOPED_V17",
        "v2_main_called": True,
        "current_leaf_sealed": True,
        "runtime_paths": {key: str(value.relative_to(root)) for key, value in paths.items()},
        "target_stats": checked["stats"],
        "payload_read": False,
        "original_path_fallback": "REJECT",
        "ledger_mutated": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("worker",))
    parser.add_argument("rest", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        result = run([args.command, *args.rest])
        print(json.dumps(result, sort_keys=True, ensure_ascii=True, default=str))
        return 0
    except (CurrentScopedEntryError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"V17 copied entry: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
