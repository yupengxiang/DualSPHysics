#!/usr/bin/env python3
"""V62 raw-to-typed worker adapter.

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
import stat
import sys
from types import ModuleType
from typing import Any, Callable, Iterable, Mapping


class V62WorkerError(RuntimeError):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise V62WorkerError(f"JSON object required: {path}")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                return digest.hexdigest()
            digest.update(block)


def _bound_run_out(request: Mapping[str, Any], solver_receipt: Path) -> Path:
    """Return only the parent-copied Run.out bound in this request.

    V2's historical resolver follows the solver receipt's original
    ``output_root``.  That is unsafe after relocation.  V62 therefore makes
    the copied metadata file an explicit input and rejects any attempt to
    derive a neighbouring/original path.
    """
    binding = request.get("run_out_binding")
    if not isinstance(binding, Mapping):
        raise V62WorkerError("run_out_binding is required; original Run.out fallback is forbidden")
    value = binding.get("path")
    expected = binding.get("expected_sha256")
    receipt_path = binding.get("solver_receipt_path")
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise V62WorkerError("run_out_binding.path must be an absolute copied path")
    if not isinstance(expected, str) or len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
        raise V62WorkerError("run_out_binding.expected_sha256 is malformed")
    if receipt_path is not None and str(solver_receipt) != str(receipt_path):
        raise V62WorkerError("Run.out solver receipt path is not the bound copied receipt")
    path = Path(value)
    if path.is_symlink() or not path.is_file():
        raise V62WorkerError(f"bound copied Run.out is not a regular file: {path}")
    if _sha256_file(path) != expected:
        raise V62WorkerError("bound copied Run.out SHA differs")
    return path


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
        raise V62WorkerError("v62_raw_scope.root is required")
    if not isinstance(paths, list) or not paths or not all(
        isinstance(item, str) and item for item in paths
    ):
        raise V62WorkerError("v62_raw_scope.paths must be a non-empty string list")
    if len(set(paths)) != len(paths):
        raise V62WorkerError("v62_raw_scope.paths contains duplicates")
    if paths != sorted(paths):
        raise V62WorkerError("v62_raw_scope.paths must be canonical sorted paths")
    if not isinstance(expected, str) or len(expected) != 64:
        raise V62WorkerError("v62_raw_scope.expected_tree_sha256 is required")
    root = Path(root_text)
    for relative in paths:
        candidate = Path(relative)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise V62WorkerError(f"raw scope escapes root: {relative}")
        if candidate.as_posix() != relative:
            raise V62WorkerError(f"raw scope path is not canonical: {relative}")
    return root, paths, expected


def scoped_raw_tree_manifest(root: Path, scope: dict[str, Any]) -> dict[str, Any]:
    """Hash exactly the producer raw scope, excluding copied code/metadata."""

    declared_root, paths, expected = _normalise_scope(scope)
    if root.resolve() != declared_root.resolve():
        raise V62WorkerError(
            f"raw manifest root differs from bound scope: {root} != {declared_root}"
        )
    if not root.is_dir():
        raise V62WorkerError(f"raw manifest root is not a directory: {root}")

    files: list[dict[str, Any]] = []
    for relative in paths:
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise V62WorkerError(f"raw scope member is not a regular file: {relative}")
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
        raise V62WorkerError(
            f"producer raw tree differs: observed={tree_sha256} expected={expected}"
        )
    return {
        "tree_sha256": tree_sha256,
        "file_count": len(files),
        "files": files,
        "scope": "TOP_LEVEL_PRODUCER_RAW_EXPLICIT_V62",
    }


def _load_module(path: Path, name: str) -> ModuleType:
    if not path.is_file():
        raise V62WorkerError(f"bound module is missing: {path}")
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise V62WorkerError(f"cannot load bound module: {path}")
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
        raise V62WorkerError("worker request modules object is missing")
    result: dict[str, Path] = {}
    for role in ("worker", "raw_converter", "v14_operator", "v15_operator", "v16_operator"):
        value = modules.get(role)
        if not isinstance(value, dict) or not isinstance(value.get("path"), str):
            raise V62WorkerError(f"worker module binding is missing: {role}")
        result[role] = Path(value["path"])
    return result


def _assert_actionable_modules(request: dict[str, Any], modules: dict[str, Path]) -> None:
    binding = request.get("v62_worker_binding")
    if not isinstance(binding, dict):
        raise V62WorkerError("v62_worker_binding is missing")
    root_text = binding.get("code_root")
    if not isinstance(root_text, str) or not root_text:
        raise V62WorkerError("v62_worker_binding.code_root is missing")
    code_root = Path(root_text).resolve()
    expected_sha = binding.get("module_sha256")
    if not isinstance(expected_sha, dict):
        raise V62WorkerError("v62_worker_binding.module_sha256 is missing")
    declared_modules = request.get("modules")
    if not isinstance(declared_modules, dict):
        raise V62WorkerError("worker request modules object is missing")
    for role, path in modules.items():
        expected = expected_sha.get(role)
        item = declared_modules.get(role)
        if (not isinstance(expected, str) or len(expected) != 64 or
                any(char not in "0123456789abcdef" for char in expected)):
            raise V62WorkerError(f"module expected SHA is missing or malformed for {role}")
        if not isinstance(item, dict) or item.get("sha256") != expected:
            raise V62WorkerError(
                f"embedded module SHA does not match expected binding for {role}")
        resolved = path.resolve()
        try:
            resolved.relative_to(code_root)
        except ValueError as exc:
            raise V62WorkerError(
                f"actionable module is outside copied worker directory: {path}"
            ) from exc
        observed = _sha256_file(resolved)
        if observed != expected:
            raise V62WorkerError(f"module SHA differs for {role}: {path}")


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
    scope = request.get("v62_raw_scope")
    if not isinstance(scope, dict):
        raise V62WorkerError("v62_raw_scope is required")
    raw_root, scope_paths, expected_tree = _normalise_scope(scope)
    raw_binding = request.get("raw_binding")
    if not isinstance(raw_binding, dict) or raw_binding.get("data_root") != str(raw_root):
        raise V62WorkerError("raw_binding.data_root is not the bound scope root")
    if raw_binding.get("expected_raw_tree_sha256") != expected_tree:
        raise V62WorkerError("raw binding expected tree is not the scoped producer tree")

    modules = _bound_module_paths(request)
    _assert_actionable_modules(request, modules)
    binding = request["v62_worker_binding"]
    v2_path_text = binding.get("v2_worker_path")
    if not isinstance(v2_path_text, str):
        raise V62WorkerError("v62_worker_binding.v2_worker_path is missing")
    v2_path = Path(v2_path_text)
    if v2_path.resolve() != modules["worker"].resolve():
        raise V62WorkerError("v2 worker path differs from modules.worker")

    # The V2 script is the scientific worker.  Only its converter manifest
    # callback is replaced; all typed/label calculations remain the pinned
    # implementation bound by the request.
    v2 = _load_module(v2_path, "ds_data02_bound_f2_native_raw_to_typed_label_v2_v62")
    original_loader: Callable[..., ModuleType] = v2._load_module
    original_run_out = v2._resolve_run_out
    converter_path = modules["raw_converter"].resolve()

    def scoped_loader(path: Path, name: str) -> ModuleType:
        module = original_loader(path, name)
        if Path(path).resolve() == converter_path:
            module.raw_tree_manifest = lambda root: scoped_raw_tree_manifest(Path(root), scope)  # type: ignore[attr-defined]
        return module

    v2._load_module = scoped_loader
    v2._resolve_run_out = _bound_run_out
    try:
        result = v2.run(
            request_path,
            output_dir,
            io_slot_approved=io_slot_approved,
            run_labels=run_labels,
        )
    finally:
        v2._load_module = original_loader
        v2._resolve_run_out = original_run_out

    if not isinstance(result, dict):
        raise V62WorkerError("V2 worker returned a non-object result")
    result = dict(result)
    raw_to_typed = result.get("raw_to_typed")
    evidence = raw_to_typed.get("raw_evidence") if isinstance(raw_to_typed, dict) else None
    if isinstance(evidence, dict):
        # Surface the producer-scope evidence for the parent guard without
        # changing the pinned V2 report schema.
        result["raw_tree_before_sha256"] = evidence.get("before_tree_sha256")
        result["raw_tree_after_sha256"] = evidence.get("after_tree_sha256")
        result["raw_tree_file_count"] = evidence.get("file_count")
    result["v62_raw_scope"] = {
        "file_count": len(scope_paths),
        "expected_tree_sha256": expected_tree,
        "scope": "TOP_LEVEL_PRODUCER_RAW_EXPLICIT_V62",
    }
    result["raw_copy_attempts"] = _count_raw_named_outputs(output_dir, scope_paths)
    if result["raw_copy_attempts"]:
        raise V62WorkerError("raw producer files appeared in generated product output")
    return result


def _worker_summary(result: Mapping[str, Any], output_dir: Path) -> dict[str, Any]:
    """Return the bounded parent-facing result, never the 401-frame report.

    The pinned V2 worker still writes its complete report on disk.  The V62
    command line carries only stable paths, hashes and scope evidence so a
    parent with a finite stdout tail can parse the terminal state.
    """
    raw_to_typed = result.get("raw_to_typed")
    typed_output = result.get("typed_output")
    raw_evidence = raw_to_typed.get("raw_evidence") if isinstance(raw_to_typed, Mapping) else {}
    if not isinstance(raw_evidence, Mapping):
        raw_evidence = {}
    if not isinstance(typed_output, Mapping):
        typed_output = {}
    boundary = result.get("execution_boundary")
    if not isinstance(boundary, Mapping):
        boundary = {}

    def _boundary_flag(name: str) -> bool:
        # The pinned V2 report is authoritative here.  The result-level
        # fallback keeps the adapter readable against older development
        # reports, but is never preferred when the boundary is present.
        value = boundary.get(name, result.get(name, False))
        return bool(value)

    typed_path = typed_output.get("path")
    typed_bytes: int | None = None
    typed_mode_bits: int | None = None
    if isinstance(typed_path, str):
        candidate = Path(typed_path)
        if candidate.is_file() and not candidate.is_symlink():
            typed_stat = candidate.stat()
            typed_bytes = int(typed_stat.st_size)
            typed_mode_bits = stat.S_IMODE(typed_stat.st_mode)
    report_path = output_dir / "raw-to-typed-to-label-report-v2.json"
    report_file_sha256 = _sha256_file(report_path) if report_path.is_file() else None
    summary: dict[str, Any] = {
        "schema": "ds02.stage2.f2-native-raw-to-typed-to-label-worker-summary.v62",
        "status": result.get("status", "UNKNOWN"),
        "report_path": str(report_path),
        "report_sha256": result.get("report_sha256"),
        "report_file_sha256": report_file_sha256,
        "converter_report_path": raw_to_typed.get("converter_report") if isinstance(raw_to_typed, Mapping) else None,
        "converter_report_sha256": raw_to_typed.get("converter_report_sha256") if isinstance(raw_to_typed, Mapping) else None,
        "typed_output_path": typed_output.get("path"),
        "typed_output_sha256": typed_output.get("sha256"),
        "raw_tree_before_sha256": result.get("raw_tree_before_sha256", raw_evidence.get("before_tree_sha256")),
        "raw_tree_after_sha256": result.get("raw_tree_after_sha256", raw_evidence.get("after_tree_sha256")),
        "raw_tree_file_count": result.get("raw_tree_file_count", raw_evidence.get("file_count")),
        "raw_copy_attempts": result.get("raw_copy_attempts", 0),
        "raw_opened": _boundary_flag("raw_opened"),
        "hdf5_opened": _boundary_flag("hdf5_opened"),
        "converter_invoked": _boundary_flag("converter_invoked"),
        "label_operator_invoked": _boundary_flag("label_operator_invoked"),
        "typed_output_bytes": typed_bytes,
        "typed_output_mode_bits": typed_mode_bits,
        "execution_boundary": {
            name: _boundary_flag(name) for name in (
                "raw_opened", "hdf5_opened", "converter_invoked",
                "label_operator_invoked", "model_invoked", "cfd_invoked")
        },
        "summary_path": str(output_dir / "v62-worker-summary.json"),
        "model_invoked": _boundary_flag("model_invoked"),
        "cfd_invoked": _boundary_flag("cfd_invoked"),
    }
    return summary


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
    summary = _worker_summary(result, args.output_dir)
    summary_path = args.output_dir / "v62-worker-summary.json"
    if summary_path.exists() or summary_path.is_symlink():
        raise V62WorkerError(f"refusing existing worker summary: {summary_path}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with summary_path.open("x", encoding="utf-8") as stream:
        json.dump(summary, stream, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        stream.write("\n")
    # Keep this one line small: the parent parses it from a bounded tail.
    print(json.dumps(summary, sort_keys=True, separators=(",", ":"), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
