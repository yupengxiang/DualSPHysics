#!/usr/bin/env python3
"""V64 raw-to-typed worker adapter.

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
import shutil
import stat
import subprocess
import sys
import tempfile
from types import ModuleType
from typing import Any, Callable, Iterable, Mapping


class V64WorkerError(RuntimeError):
    pass


def _tree_bytes(root: Path) -> int:
    """Return bytes below an attempt-owned directory without following links."""
    if not root.exists():
        return 0
    if root.is_symlink() or not root.is_dir():
        raise V64WorkerError(f"scratch root is not a regular directory: {root}")
    total = 0
    for item in root.rglob("*"):
        if item.is_symlink():
            raise V64WorkerError(f"scratch symlink is forbidden: {item}")
        if item.is_file():
            total += int(item.stat().st_size)
    return total


def _scratch_binding(request: Mapping[str, Any], output_dir: Path) -> dict[str, Any]:
    runtime = request.get("runtime")
    scratch = runtime.get("scratch") if isinstance(runtime, Mapping) else None
    if not isinstance(scratch, Mapping):
        raise V64WorkerError("runtime.scratch binding is required")
    root_value = scratch.get("root")
    external_value = scratch.get("external_root")
    if not isinstance(root_value, str) or not Path(root_value).is_absolute():
        raise V64WorkerError("runtime.scratch.root must be an absolute path")
    if not isinstance(external_value, str) or not Path(external_value).is_absolute():
        raise V64WorkerError("runtime.scratch.external_root must be an absolute path")
    root = Path(root_value).expanduser().resolve()
    external = Path(external_value).expanduser().resolve()
    if root == external or external not in root.parents:
        raise V64WorkerError("scratch root must be a child of the bound external filesystem")
    if root == output_dir.resolve() or root in output_dir.resolve().parents:
        raise V64WorkerError("scratch root may not be the product output or its parent")
    if output_dir.resolve() == external or external not in output_dir.resolve().parents:
        raise V64WorkerError("product output must be under the same external filesystem")
    # The shared mount may be the parent of a registered attempt namespace
    # (ROOT179 uses /var/tmp/ds02-stage2).  Reject only the default mount
    # itself; an exact fresh child is safe once its external parent is bound.
    if root in {Path("/tmp"), Path("/var/tmp")}:
        raise V64WorkerError("default or shared tmp scratch is forbidden")
    max_frame = scratch.get("max_frame_bytes")
    timeout = scratch.get("timeout_seconds")
    if isinstance(max_frame, bool) or not isinstance(max_frame, int) or max_frame <= 0:
        raise V64WorkerError("runtime.scratch.max_frame_bytes must be a positive integer")
    if max_frame > 1024 * 1024 * 1024:
        raise V64WorkerError("runtime.scratch.max_frame_bytes exceeds the V64 hard bound")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or float(timeout) <= 0:
        raise V64WorkerError("runtime.scratch.timeout_seconds must be positive")
    if root.exists():
        if root.is_symlink() or not root.is_dir() or any(root.iterdir()):
            raise V64WorkerError("attempt-owned scratch root must be fresh and empty")
    return {
        "root": root,
        "external_root": external,
        "max_frame_bytes": int(max_frame),
        "timeout_seconds": float(timeout),
        "attempt_id": str(scratch.get("attempt_id", "")),
    }


def _remove_frame_scratch(scratch_root: Path, index: int) -> None:
    prefix = scratch_root / f"frame_{index:04d}"
    if prefix.is_symlink():
        raise V64WorkerError(f"decoder frame scratch symlink is forbidden: {prefix}")
    if prefix.exists():
        shutil.rmtree(prefix, ignore_errors=False)
    xml = Path(str(prefix) + ".xml")
    try:
        xml.unlink()
    except FileNotFoundError:
        pass


def _configure_converter_scratch(converter: ModuleType, contract: dict[str, Any],
                                 output_dir: Path) -> None:
    """Bind decoder temp files to this attempt and clear them after every frame.

    ``ds_data02_f5_bi4.convert_direct`` owns the HDF5 stream but historically
    leaves every decoder frame below one mkdtemp directory until finalization.
    The wrapper keeps the pinned converter's array semantics while making the
    frame directory ephemeral and measuring the largest live external use.
    """
    scratch_root: Path = contract["root"]
    scratch_root.mkdir(parents=True, exist_ok=False)
    previous_tempdir = tempfile.tempdir
    previous_env = {key: os.environ.get(key) for key in ("TMPDIR", "TEMP", "TMP")}
    os.environ["TMPDIR"] = str(scratch_root)
    os.environ["TEMP"] = str(scratch_root)
    os.environ["TMP"] = str(scratch_root)
    tempfile.tempdir = str(scratch_root)
    # The converter module imported the same stdlib tempfile object.  Set the
    # cache explicitly so an earlier import cannot redirect mkdtemp to /tmp.
    module_tempfile = getattr(converter, "tempfile", None)
    if module_tempfile is not None:
        module_tempfile.tempdir = str(scratch_root)

    original_decode = converter.decode_frame
    original_subprocess_run = converter.subprocess.run
    max_frame = contract["max_frame_bytes"]
    timeout = contract["timeout_seconds"]
    peak_frame = 0
    peak_total = 0
    decoded_frames = 0
    cleaned_frames = 0

    def bounded_subprocess_run(*args: Any, **kwargs: Any) -> Any:
        requested = kwargs.get("timeout")
        effective_timeout = timeout if requested is None else min(float(requested), timeout)
        command = args[0] if args else kwargs.get("args")
        # The pinned decoder is the only child for which V64 owns a hard live
        # scratch cap.  Other small metadata helpers keep the converter's
        # original subprocess semantics.
        frame_root: Path | None = None
        if isinstance(command, (list, tuple)) and len(command) >= 3:
            try:
                candidate = Path(str(command[2])).expanduser().resolve()
                if candidate.parent.parent == scratch_root and candidate.name.startswith("frame_"):
                    frame_root = candidate.parent
            except (OSError, RuntimeError):
                frame_root = None
        if frame_root is None:
            kwargs["timeout"] = effective_timeout
            return original_subprocess_run(*args, **kwargs)
        check = bool(kwargs.pop("check", False))
        kwargs.pop("timeout", None)
        popen_kwargs = dict(kwargs)
        process = subprocess.Popen(command, **popen_kwargs)
        started = time.monotonic()
        limit_error: BaseException | None = None
        try:
            while process.poll() is None:
                if time.monotonic() - started >= effective_timeout:
                    limit_error = subprocess.TimeoutExpired(command, effective_timeout)
                    process.terminate()
                    break
                live_bytes = _tree_bytes(frame_root)
                if live_bytes > max_frame:
                    limit_error = V64WorkerError(
                        f"decoder frame scratch exceeded hard cap while decoding: {live_bytes} > {max_frame}")
                    process.terminate()
                    break
                time.sleep(0.02)
            try:
                stdout, stderr = process.communicate(timeout=1.0)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
        if limit_error is not None:
            raise limit_error
        completed = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
        if check and process.returncode:
            raise subprocess.CalledProcessError(process.returncode, command,
                                                 output=stdout, stderr=stderr)
        return completed

    def bounded_decode(frame_path: Path, decoder: Path, frame_scratch: Path, index: int) -> Any:
        nonlocal peak_frame, peak_total, decoded_frames, cleaned_frames
        resolved = Path(frame_scratch).expanduser().resolve()
        # The pinned converter creates one private mkdtemp directory below
        # ``TMPDIR`` and passes that directory to every frame.  The frame
        # payload itself is its ``frame_NNNN`` child.  Do not confuse the
        # converter's private child with the attempt root, and never accept a
        # frame scratch path outside that one child.
        if resolved.parent != scratch_root:
            raise V64WorkerError(f"decoder scratch escaped attempt root: {resolved}")
        frame_dir = resolved / f"frame_{index:04d}"
        try:
            frame = original_decode(frame_path, decoder, resolved, index)
            # Count the complete private decoder directory, not only the
            # expected frame child.  An upstream decoder adding an auxiliary
            # file must still hit the same hard per-frame cap.
            live_bytes = _tree_bytes(resolved)
            # At this point the output HDF5/partial and the decoder frame are
            # both external attempt bytes.  The two roots are siblings.
            peak_frame = max(peak_frame, live_bytes)
            peak_total = max(peak_total, live_bytes + _tree_bytes(output_dir))
            if live_bytes > max_frame:
                raise V64WorkerError(
                    f"decoder frame scratch exceeds V64 hard bound: {live_bytes} > {max_frame}")
            decoded_frames += 1
            return frame
        finally:
            _remove_frame_scratch(resolved, index)
            cleaned_frames += 1

    converter.decode_frame = bounded_decode
    converter.subprocess.run = bounded_subprocess_run
    contract["_restore"] = (original_decode, original_subprocess_run,
                              previous_tempdir, previous_env, module_tempfile)
    contract["_stats"] = {
        "peak_frame_bytes": lambda: peak_frame,
        "peak_external_bytes": lambda: peak_total,
        "decoded_frames": lambda: decoded_frames,
        "cleaned_frames": lambda: cleaned_frames,
    }


def _restore_converter_scratch(converter: ModuleType, contract: dict[str, Any]) -> dict[str, Any]:
    restore = contract.pop("_restore", None)
    stats = contract.pop("_stats", {})
    if restore is not None:
        original_decode, original_subprocess_run, previous_tempdir, previous_env, module_tempfile = restore
        converter.decode_frame = original_decode
        converter.subprocess.run = original_subprocess_run
        tempfile.tempdir = previous_tempdir
        if module_tempfile is not None:
            module_tempfile.tempdir = previous_tempdir
        for key, value in previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    return {
        "root": str(contract["root"]),
        "external_root": str(contract["external_root"]),
        "attempt_id": contract["attempt_id"],
        "max_frame_bytes": contract["max_frame_bytes"],
        "timeout_seconds": contract["timeout_seconds"],
        "peak_frame_bytes": int(stats.get("peak_frame_bytes", lambda: 0)()),
        "peak_external_bytes": int(stats.get("peak_external_bytes", lambda: 0)()),
        "decoded_frames": int(stats.get("decoded_frames", lambda: 0)()),
        "cleaned_frames": int(stats.get("cleaned_frames", lambda: 0)()),
        "per_frame_cleanup": True,
        "default_tmp_forbidden": True,
    }


def _install_canonical_sibling_bootstrap(modules: Mapping[str, Path], code_root: Path) -> None:
    """Make copied sibling imports explicit for ``python -I`` child runs."""
    resolved_root = code_root.expanduser().resolve()
    if not resolved_root.is_dir() or resolved_root.is_symlink():
        raise V64WorkerError(f"canonical sibling root is invalid: {resolved_root}")
    if str(resolved_root) not in sys.path:
        sys.path.insert(0, str(resolved_root))
    sibling = modules.get("v14_operator")
    if sibling is None or sibling.resolve().parent != resolved_root:
        raise V64WorkerError("V14 canonical sibling is not under the copied native root")
    canonical_name = sibling.stem
    old = sys.modules.get(canonical_name)
    if old is not None and Path(str(getattr(old, "__file__", ""))).resolve() != sibling.resolve():
        raise V64WorkerError(f"canonical sibling name is already bound to another file: {canonical_name}")
    if old is None:
        _load_module(sibling, canonical_name)


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise V64WorkerError(f"JSON object required: {path}")
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
    ``output_root``.  That is unsafe after relocation.  V64 therefore makes
    the copied metadata file an explicit input and rejects any attempt to
    derive a neighbouring/original path.
    """
    binding = request.get("run_out_binding")
    if not isinstance(binding, Mapping):
        raise V64WorkerError("run_out_binding is required; original Run.out fallback is forbidden")
    value = binding.get("path")
    expected = binding.get("expected_sha256")
    receipt_path = binding.get("solver_receipt_path")
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise V64WorkerError("run_out_binding.path must be an absolute copied path")
    if not isinstance(expected, str) or len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
        raise V64WorkerError("run_out_binding.expected_sha256 is malformed")
    if receipt_path is not None and str(solver_receipt) != str(receipt_path):
        raise V64WorkerError("Run.out solver receipt path is not the bound copied receipt")
    path = Path(value)
    if path.is_symlink() or not path.is_file():
        raise V64WorkerError(f"bound copied Run.out is not a regular file: {path}")
    if _sha256_file(path) != expected:
        raise V64WorkerError("bound copied Run.out SHA differs")
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
        raise V64WorkerError("v64_raw_scope.root is required")
    if not isinstance(paths, list) or not paths or not all(
        isinstance(item, str) and item for item in paths
    ):
        raise V64WorkerError("v64_raw_scope.paths must be a non-empty string list")
    if len(set(paths)) != len(paths):
        raise V64WorkerError("v64_raw_scope.paths contains duplicates")
    if paths != sorted(paths):
        raise V64WorkerError("v64_raw_scope.paths must be canonical sorted paths")
    if not isinstance(expected, str) or len(expected) != 64:
        raise V64WorkerError("v64_raw_scope.expected_tree_sha256 is required")
    root = Path(root_text)
    for relative in paths:
        candidate = Path(relative)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise V64WorkerError(f"raw scope escapes root: {relative}")
        if candidate.as_posix() != relative:
            raise V64WorkerError(f"raw scope path is not canonical: {relative}")
    return root, paths, expected


def scoped_raw_tree_manifest(root: Path, scope: dict[str, Any]) -> dict[str, Any]:
    """Hash exactly the producer raw scope, excluding copied code/metadata."""

    declared_root, paths, expected = _normalise_scope(scope)
    if root.resolve() != declared_root.resolve():
        raise V64WorkerError(
            f"raw manifest root differs from bound scope: {root} != {declared_root}"
        )
    if not root.is_dir():
        raise V64WorkerError(f"raw manifest root is not a directory: {root}")

    files: list[dict[str, Any]] = []
    for relative in paths:
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise V64WorkerError(f"raw scope member is not a regular file: {relative}")
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
        raise V64WorkerError(
            f"producer raw tree differs: observed={tree_sha256} expected={expected}"
        )
    return {
        "tree_sha256": tree_sha256,
        "file_count": len(files),
        "files": files,
        "scope": "TOP_LEVEL_PRODUCER_RAW_EXPLICIT_V64",
    }


def _load_module(path: Path, name: str) -> ModuleType:
    if not path.is_file():
        raise V64WorkerError(f"bound module is missing: {path}")
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise V64WorkerError(f"cannot load bound module: {path}")
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
        raise V64WorkerError("worker request modules object is missing")
    result: dict[str, Path] = {}
    for role in ("worker", "raw_converter", "v14_operator", "v15_operator", "v16_operator"):
        value = modules.get(role)
        if not isinstance(value, dict) or not isinstance(value.get("path"), str):
            raise V64WorkerError(f"worker module binding is missing: {role}")
        result[role] = Path(value["path"])
    return result


def _assert_actionable_modules(request: dict[str, Any], modules: dict[str, Path]) -> None:
    binding = request.get("v64_worker_binding")
    if not isinstance(binding, dict):
        raise V64WorkerError("v64_worker_binding is missing")
    root_text = binding.get("code_root")
    if not isinstance(root_text, str) or not root_text:
        raise V64WorkerError("v64_worker_binding.code_root is missing")
    code_root = Path(root_text).resolve()
    expected_sha = binding.get("module_sha256")
    if not isinstance(expected_sha, dict):
        raise V64WorkerError("v64_worker_binding.module_sha256 is missing")
    declared_modules = request.get("modules")
    if not isinstance(declared_modules, dict):
        raise V64WorkerError("worker request modules object is missing")
    for role, path in modules.items():
        expected = expected_sha.get(role)
        item = declared_modules.get(role)
        if (not isinstance(expected, str) or len(expected) != 64 or
                any(char not in "0123456789abcdef" for char in expected)):
            raise V64WorkerError(f"module expected SHA is missing or malformed for {role}")
        if not isinstance(item, dict) or item.get("sha256") != expected:
            raise V64WorkerError(
                f"embedded module SHA does not match expected binding for {role}")
        resolved = path.resolve()
        try:
            resolved.relative_to(code_root)
        except ValueError as exc:
            raise V64WorkerError(
                f"actionable module is outside copied worker directory: {path}"
            ) from exc
        observed = _sha256_file(resolved)
        if observed != expected:
            raise V64WorkerError(f"module SHA differs for {role}: {path}")


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
    output_dir = output_dir.expanduser().resolve()
    scope = request.get("v64_raw_scope")
    if not isinstance(scope, dict):
        raise V64WorkerError("v64_raw_scope is required")
    raw_root, scope_paths, expected_tree = _normalise_scope(scope)
    raw_binding = request.get("raw_binding")
    if not isinstance(raw_binding, dict) or raw_binding.get("data_root") != str(raw_root):
        raise V64WorkerError("raw_binding.data_root is not the bound scope root")
    if raw_binding.get("expected_raw_tree_sha256") != expected_tree:
        raise V64WorkerError("raw binding expected tree is not the scoped producer tree")

    modules = _bound_module_paths(request)
    _assert_actionable_modules(request, modules)
    scratch = _scratch_binding(request, output_dir)
    worker_binding = request.get("v64_worker_binding")
    if not isinstance(worker_binding, Mapping):
        raise V64WorkerError("v64_worker_binding is required")
    _install_canonical_sibling_bootstrap(modules, Path(str(worker_binding["code_root"])))
    binding = request["v64_worker_binding"]
    v2_path_text = binding.get("v2_worker_path")
    if not isinstance(v2_path_text, str):
        raise V64WorkerError("v64_worker_binding.v2_worker_path is missing")
    v2_path = Path(v2_path_text)
    if v2_path.resolve() != modules["worker"].resolve():
        raise V64WorkerError("v2 worker path differs from modules.worker")

    # The V2 script is the scientific worker.  Only its converter manifest
    # callback is replaced; all typed/label calculations remain the pinned
    # implementation bound by the request.
    v2 = _load_module(v2_path, "ds_data02_bound_f2_native_raw_to_typed_label_v2_v64")
    original_loader: Callable[..., ModuleType] = v2._load_module
    original_run_out = v2._resolve_run_out
    converter_path = modules["raw_converter"].resolve()
    scratch_contract: dict[str, Any] = dict(scratch)
    converter_module: ModuleType | None = None
    scratch_report: dict[str, Any] | None = None

    def scoped_loader(path: Path, name: str) -> ModuleType:
        module = original_loader(path, name)
        if Path(path).resolve() == converter_path:
            module.raw_tree_manifest = lambda root: scoped_raw_tree_manifest(Path(root), scope)  # type: ignore[attr-defined]
            _configure_converter_scratch(module, scratch_contract, output_dir)
            nonlocal converter_module
            converter_module = module
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
        if converter_module is not None and "_restore" in scratch_contract:
            scratch_report = _restore_converter_scratch(converter_module, scratch_contract)
        elif "_restore" in scratch_contract:
            raise V64WorkerError("converter scratch hook was not restored")
        try:
            shutil.rmtree(scratch["root"], ignore_errors=False)
        except FileNotFoundError:
            pass
        except OSError as error:
            raise V64WorkerError(f"attempt-owned scratch cleanup failed: {error}") from error

    if not isinstance(result, dict):
        raise V64WorkerError("V2 worker returned a non-object result")
    result = dict(result)
    raw_to_typed = result.get("raw_to_typed")
    evidence = raw_to_typed.get("raw_evidence") if isinstance(raw_to_typed, dict) else None
    if isinstance(evidence, dict):
        # Surface the producer-scope evidence for the parent guard without
        # changing the pinned V2 report schema.
        result["raw_tree_before_sha256"] = evidence.get("before_tree_sha256")
        result["raw_tree_after_sha256"] = evidence.get("after_tree_sha256")
        result["raw_tree_file_count"] = evidence.get("file_count")
    result["v64_raw_scope"] = {
        "file_count": len(scope_paths),
        "expected_tree_sha256": expected_tree,
        "scope": "TOP_LEVEL_PRODUCER_RAW_EXPLICIT_V64",
    }
    result["raw_copy_attempts"] = _count_raw_named_outputs(output_dir, scope_paths)
    if result["raw_copy_attempts"]:
        raise V64WorkerError("raw producer files appeared in generated product output")
    if scratch_report is None:
        raise V64WorkerError("scratch contract was not observed by the converter")
    result["decoder_scratch"] = scratch_report
    result["external_peak_bytes"] = max(
        int(scratch_report["peak_external_bytes"]),
        int(scratch_report["peak_frame_bytes"]) + _tree_bytes(output_dir),
    )
    return result


def _worker_summary(result: Mapping[str, Any], output_dir: Path) -> dict[str, Any]:
    """Return the bounded parent-facing result, never the 401-frame report.

    The pinned V2 worker still writes its complete report on disk.  The V64
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
    # The report file is independently SHA-attested above.  It is still a
    # small JSON contract, so join its typed-output path/SHA/bytes with the
    # summary rather than trusting either producer in isolation.  A parent
    # never re-hashes the generated HDF5 here.
    typed_report: dict[str, Any] = {}
    if report_path.is_file():
        if report_path.stat().st_size > 16 * 1024 * 1024:
            raise V64WorkerError("worker report is too large for typed-output JSON join")
        try:
            report_value = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise V64WorkerError(f"worker report cannot be read for typed-output join: {error}") from error
        candidate = report_value.get("typed_output") if isinstance(report_value, Mapping) else None
        if isinstance(candidate, Mapping):
            typed_report = {
                "path": candidate.get("path"),
                "sha256": candidate.get("sha256"),
                "bytes": candidate.get("bytes"),
            }
    if typed_report:
        if (typed_report.get("path") != typed_output.get("path") or
                typed_report.get("sha256") != typed_output.get("sha256") or
                typed_report.get("bytes") != typed_bytes):
            raise V64WorkerError("typed-output report contract differs from worker summary")
    summary: dict[str, Any] = {
        "schema": "ds02.stage2.f2-native-raw-to-typed-to-label-worker-summary.v64",
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
        "decoder_scratch": result.get("decoder_scratch", {"status": "UNKNOWN_SCRATCH_CONTRACT"}),
        "external_peak_bytes": result.get("external_peak_bytes"),
        "raw_opened": _boundary_flag("raw_opened"),
        "hdf5_opened": _boundary_flag("hdf5_opened"),
        "converter_invoked": _boundary_flag("converter_invoked"),
        "label_operator_invoked": _boundary_flag("label_operator_invoked"),
        "typed_output_bytes": typed_bytes,
        "typed_output_mode_bits": typed_mode_bits,
        "typed_output_report_contract": typed_report or {
            "status": "UNKNOWN_REPORT_TYPED_OUTPUT_CONTRACT"
        },
        "typed_output_report_sha256": report_file_sha256,
        "execution_boundary": {
            name: _boundary_flag(name) for name in (
                "raw_opened", "hdf5_opened", "converter_invoked",
                "label_operator_invoked", "model_invoked", "cfd_invoked")
        },
        "summary_path": str(output_dir / "v64-worker-summary.json"),
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
    summary_path = args.output_dir / "v64-worker-summary.json"
    if summary_path.exists() or summary_path.is_symlink():
        raise V64WorkerError(f"refusing existing worker summary: {summary_path}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with summary_path.open("x", encoding="utf-8") as stream:
        json.dump(summary, stream, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        stream.write("\n")
    # Keep this one line small: the parent parses it from a bounded tail.
    print(json.dumps(summary, sort_keys=True, separators=(",", ":"), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
