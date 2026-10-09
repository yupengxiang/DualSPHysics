#!/usr/bin/env python3
"""V64 parent-compatible direct recovery guard.

V58 proved the direct worker path, but its runner was only a direct recovery
command: it did not speak the existing parent-v3 ledger boundary and it kept
unbounded child output in memory.  V64 is the additive boundary for that
worker.  It uses the already deployed parent-v3 ``_reserve`` and ``_charge``
functions, keeps Home and external storage separate, and owns only a fresh
process group and fresh output namespace.

The raw ROOT145 tree is an immutable input.  V64 never copies it.  After the
same-parent reservation it computes the producer converter's canonical raw
tree manifest and every bound frame SHA, writes those observed SHAs into a
new derived worker request, and verifies the tree again after the worker.  A
worker report can add a copy-attempt count; the runner also scans the new
namespaces for payload copies.  ``raw_copy_attempts`` is therefore measured,
not a constant assertion.

The builder is metadata/stat-only.  It reads the small V58 request and its
embedded worker JSON, but does not hash or open raw, BI4, HDF5, or result
payloads.  Scientific qualification remains UNKNOWN.
"""
from __future__ import annotations

import argparse
from collections import deque
from datetime import datetime, timezone
import copy
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import selectors
import signal
import shutil
import stat
import subprocess
import sys
import time
import resource
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
WORKER_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_native_raw_to_typed_label_v64.py"
BOOTSTRAP_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_v64_bootstrap.py"
# V64 uses the additive terminal-delta adapter V3.  The consumed V63 adapter
# remains immutable and is not treated as a V64 dependency.  V3 preserves the
# same-parent, opaque-charge contract while explicitly accepting V64
# request/report schemas.
TERMINAL_DELTA_ADAPTER = SCRIPT_DIR / "ds_data02_stage2_f2_v64_terminal_cpu_delta_adapter_v3.py"
PARENT_V3_PATH = SCRIPT_DIR / "ds_data02_stage2_f2_portable_executor_parent_v3.py"
V21_PATH = SCRIPT_DIR / "ds_data02_stage2_f2_external_supervisor_v21.py"
RUNTIME_V6_DEFAULT = SCRIPT_DIR / "ds_data02_runtime_v6.py"
# ``runtime_v6`` imports this module as ``base``.  Keep the import dependency
# explicit in the request instead of relying on an ambient PYTHONPATH or on a
# copied runtime directory happening to contain the sibling.
RUNTIME_V2_DEFAULT = SCRIPT_DIR / "ds_data02_runtime_v2.py"
PINNED_PYTHON = "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python"
# The venv path is deliberately retained literally for argv[0].  These two
# paths are only the immutable provenance/content bindings for the external
# interpreter selected by that literal invocation.
PINNED_PYTHON_PATH = Path(PINNED_PYTHON)
PINNED_PYTHON_RESOLVED = PINNED_PYTHON_PATH.resolve()
PINNED_PYVENV_CFG = PINNED_PYTHON_PATH.parent.parent / "pyvenv.cfg"
SCHEMA = "ds02.stage2.f2-root145-copied-recovery-parent-request.v64"
REPORT_SCHEMA = "ds02.stage2.f2-root145-copied-recovery-report.v64"
WORKER_SCHEMA = "ds02.stage2.f2-root145-copied-worker-request.v64"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")
PAYLOAD_SUFFIXES = {".bi4", ".obi4", ".h5", ".hdf5", ".xmf"}
RAW_AUXILIARY_NAMES = ("PartInfo.ibi4", "PartMotionRef.ibi4", "PartOut_000.obi4", "Part_Head.ibi4")
MAX_METADATA_BYTES = 8 * 1024 * 1024
# ``MAX_LOG_BYTES`` is retained as the accounting/diagnostic upper bound for
# compatibility with V61.  The child reader never stores that much: it keeps
# only a rolling terminal tail and records every byte read.
MAX_LOG_BYTES = 4 * 1024 * 1024
LOG_TAIL_BYTES = 64 * 1024
MIN_HOME_RECEIPT_BYTES = 1 * 1024 * 1024
CHILD_CLEANUP_GRACE_SECONDS = 25.0
DEFAULT_MAX_FRAME_SCRATCH_BYTES = 512 * 1024 * 1024
DEFAULT_DECODER_TIMEOUT_SECONDS = 180.0
THREAD_ENV = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
}


class PortableV64Error(RuntimeError):
    pass


def _load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise PortableV64Error(f"cannot load bound module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PARENT_V3 = _load_module(PARENT_V3_PATH, "ds02_bound_parent_v3_for_v64")


def _canonical(value: Any) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"} if isinstance(value, Mapping) else value
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False, default=str).encode("utf-8")).hexdigest()


def _sha(path: Path | str, *, max_bytes: int | None = None) -> str:
    target = Path(path).expanduser()
    if max_bytes is not None and target.stat().st_size > max_bytes:
        raise PortableV64Error(f"metadata file exceeds bound: {target}")
    digest = hashlib.sha256()
    with target.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _absolute(value: Any, role: str) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not str(value):
        raise PortableV64Error(f"{role} path is missing")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise PortableV64Error(f"{role} must be absolute: {path}")
    return path.resolve()


def _load_json(path: Path | str, role: str, *, max_bytes: int = MAX_METADATA_BYTES) -> dict[str, Any]:
    target = _absolute(path, role)
    if target.is_symlink() or not target.is_file():
        raise PortableV64Error(f"{role} must be a regular non-symlink file: {target}")
    if target.stat().st_size > max_bytes:
        raise PortableV64Error(f"{role} exceeds metadata bound: {target}")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PortableV64Error(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise PortableV64Error(f"{role} must be a JSON object")
    return value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = _absolute(path, "output")
    if target.exists() or target.is_symlink():
        raise PortableV64Error(f"refusing existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=True,
                  allow_nan=False, default=str)
        stream.write("\n")
    return target


def _no_symlink_components(path: Path) -> None:
    target = path.expanduser()
    current = target if target.exists() else target.parent
    missing: list[str] = []
    while not current.exists() and current != current.parent:
        missing.append(current.name)
        current = current.parent
    if current.is_symlink():
        raise PortableV64Error(f"symlink output component is forbidden: {current}")
    for name in reversed(missing):
        current = current / name
        if current.is_symlink():
            raise PortableV64Error(f"symlink output component is forbidden: {current}")
    if target.exists() and target.is_symlink():
        raise PortableV64Error(f"symlink output path is forbidden: {target}")


def _under(path: Path, root: Path) -> bool:
    path = path.expanduser().resolve()
    root = root.expanduser().resolve()
    return path == root or root in path.parents


def _require_sha(value: Any, role: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch not in HEX64 for ch in value):
        raise PortableV64Error(f"{role} must be a lowercase SHA-256")
    return value


def _cpu_seconds() -> float:
    own = resource.getrusage(resource.RUSAGE_SELF)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    return float(own.ru_utime + own.ru_stime + children.ru_utime + children.ru_stime)


def _stat_binding(path: Path, role: str, *, with_sha: bool = True) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise PortableV64Error(f"{role} must be a regular non-symlink file: {path}")
    value = {"role": role, "path": str(path), "bytes": int(path.stat().st_size),
             "mtime_ns": int(path.stat().st_mtime_ns),
             "mode_bits": stat.S_IMODE(path.stat().st_mode)}
    if with_sha:
        value["sha256"] = _sha(path)
    return value


def _run_out_from_solver_receipt(receipt_path: Path) -> tuple[Path, dict[str, Any]]:
    """Resolve the one solver Run.out named by the bound receipt.

    This is intentionally a bounded metadata operation performed by the
    builder.  It does not inspect the native Part tree or any typed output.
    The receipt's output directory and command arguments are the only
    admissible locations; a neighbouring/latest search is forbidden.
    """
    receipt = _load_json(receipt_path, "solver execution receipt")
    command = receipt.get("command")
    output_root_value = receipt.get("output_root")
    if not isinstance(command, list) or not command:
        raise PortableV64Error("solver receipt command is required for Run.out binding")
    if not isinstance(output_root_value, str) or not output_root_value:
        raise PortableV64Error("solver receipt output_root is required for Run.out binding")
    output_root = Path(output_root_value).expanduser().resolve()
    candidates: list[Path] = []
    for value in command:
        if isinstance(value, str) and ("solver_output" in value or value.endswith("output")):
            candidate = Path(value).expanduser()
            if candidate.is_dir():
                candidates.append(candidate / "Run.out")
    candidates.extend((output_root / "solver_output" / "Run.out", output_root / "Run.out"))
    unique: list[Path] = []
    for candidate in candidates:
        candidate = candidate.resolve()
        if candidate not in unique:
            unique.append(candidate)
    present = [candidate for candidate in unique
               if candidate.is_file() and not candidate.is_symlink()]
    if len(present) != 1:
        raise PortableV64Error(
            "exact solver command output Run.out is missing or ambiguous: "
            f"{[str(item) for item in unique]}"
        )
    source = present[0]
    if source.stat().st_size > MAX_METADATA_BYTES:
        raise PortableV64Error("bound Run.out exceeds metadata size limit")
    observed = _stat_binding(source, "solver Run.out", with_sha=True)
    observed["original_path_provenance"] = str(source)
    observed["solver_receipt_path"] = str(receipt_path)
    observed["solver_receipt_sha256"] = _sha(receipt_path)
    return source, observed


def _copy_bound_metadata(binding: Mapping[str, Any]) -> dict[str, Any]:
    """Copy a small bound metadata file only after parent reservation."""
    source = _pinned_path(binding.get("source_path"), "Run.out source")
    target = _absolute(binding.get("target_path"), "Run.out target")
    expected = _require_sha(binding.get("expected_sha256"), "Run.out expected SHA")
    solver_receipt = _pinned_path(binding.get("solver_receipt_path"), "Run.out solver receipt")
    solver_receipt_sha = _require_sha(binding.get("solver_receipt_sha256"), "solver receipt SHA")
    if target.exists() or target.is_symlink():
        raise PortableV64Error(f"refusing existing Run.out target: {target}")
    if source.stat().st_size > MAX_METADATA_BYTES:
        raise PortableV64Error("Run.out source exceeds metadata size limit")
    before = _stat_binding(source, "Run.out source", with_sha=True)
    if before["sha256"] != expected:
        raise PortableV64Error("Run.out source differs from its bound SHA")
    if _sha(solver_receipt) != solver_receipt_sha:
        raise PortableV64Error("solver receipt differs from its bound SHA")
    _no_symlink_components(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as src, target.open("xb") as dst:
        for block in iter(lambda: src.read(1024 * 1024), b""):
            dst.write(block)
    os.chmod(target, stat.S_IMODE(source.stat().st_mode))
    after = _stat_binding(target, "copied Run.out", with_sha=True)
    if after["sha256"] != expected or after["bytes"] != before["bytes"]:
        raise PortableV64Error("copied Run.out differs from the bound source")
    return {"source": before, "target": after, "phase": "AFTER_ATOMIC_PARENT_RESERVATION"}


def _verify_bound_metadata(binding: Mapping[str, Any], *, phase: str) -> dict[str, Any]:
    source = _pinned_path(binding.get("source_path"), "Run.out source")
    target = _absolute(binding.get("target_path"), "Run.out target")
    expected = _require_sha(binding.get("expected_sha256"), "Run.out expected SHA")
    solver_receipt = _pinned_path(binding.get("solver_receipt_path"), "Run.out solver receipt")
    solver_receipt_sha = _require_sha(binding.get("solver_receipt_sha256"), "solver receipt SHA")
    source_row = _stat_binding(source, "Run.out source", with_sha=True)
    target_row = _stat_binding(target, "copied Run.out", with_sha=True)
    if source_row["sha256"] != expected or target_row["sha256"] != expected:
        raise PortableV64Error(f"Run.out SHA differs during {phase}")
    if source_row["bytes"] != target_row["bytes"]:
        raise PortableV64Error(f"Run.out byte size differs during {phase}")
    if _sha(solver_receipt) != solver_receipt_sha:
        raise PortableV64Error(f"solver receipt differs during {phase}")
    return {"phase": phase, "source": source_row, "target": target_row,
            "solver_receipt_path": str(solver_receipt),
            "solver_receipt_sha256": solver_receipt_sha,
            "equal_sha256": True, "original_path_fallback": "FORBIDDEN"}


def _replace_exact(value: Any, replacements: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        return replacements.get(value, value)
    if isinstance(value, list):
        return [_replace_exact(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: _replace_exact(item, replacements) for key, item in value.items()}
    return value


def _raw_tree_manifest(root: Path, scope_paths: Sequence[str] | None = None,
                       expected_tree: str | None = None) -> dict[str, Any]:
    """Hash the producer raw role, never the relocated bundle root.

    V59 recursively hashed the bundle and therefore mixed 75 runtime/request
    files into the 405-file producer identity.  V64 takes an explicit sorted
    list of producer-relative paths.  The optional one-argument form is kept
    only for source compatibility and is intentionally rejected by the actual
    runner; tests may use it to demonstrate the old unsafe behaviour.
    """
    if scope_paths is None:
        raise PortableV64Error("V64 raw manifest requires an explicit producer scope")
    if not root.is_dir() or root.is_symlink():
        raise PortableV64Error(f"raw root is not a regular directory: {root}")
    paths = list(scope_paths)
    if not paths or paths != sorted(paths) or len(set(paths)) != len(paths):
        raise PortableV64Error("raw producer scope must be a non-empty sorted unique list")
    files: list[dict[str, Any]] = []
    for relative in paths:
        candidate = Path(relative)
        if candidate.is_absolute() or ".." in candidate.parts or candidate.as_posix() != relative:
            raise PortableV64Error(f"raw producer scope path escapes root: {relative}")
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise PortableV64Error(f"raw producer scope member is missing: {relative}")
        files.append({"path": relative, "bytes": int(path.stat().st_size), "sha256": _sha(path)})
    tree = _canonical(files)
    if expected_tree is not None and tree != expected_tree:
        raise PortableV64Error(f"raw producer tree SHA differs: {tree} != {expected_tree}")
    frames = [p for p in paths if p.startswith("Part_") and p.endswith(".bi4")
              and p[5:-4].isdigit()]
    frame_numbers = sorted(int(p[5:-4]) for p in frames)
    if frame_numbers != list(range(len(frame_numbers))):
        raise PortableV64Error("raw producer scope does not contain contiguous top-level frames")
    return {"root": str(root), "file_count": len(files), "files": files,
            "frame_count": len(frame_numbers), "tree_sha256": tree,
            "scope": "TOP_LEVEL_PRODUCER_RAW_EXPLICIT_V64"}


def _old_namespace_stat(root: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for path in sorted(root.iterdir()) if root.is_dir() else []:
        if path.name.startswith("Part_") or path.name in {"PartInfo.ibi4", "PartMotionRef.ibi4"}:
            st = path.stat()
            rows.append({"name": path.name, "bytes": int(st.st_size),
                         "mtime_ns": int(st.st_mtime_ns), "st_dev": int(st.st_dev),
                         "st_ino": int(st.st_ino)})
    return {"root": str(root), "entries": rows}


def _payload_copy_count(target_root: Path, output_root: Path, supervisor_root: Path,
                        raw_scope_paths: Sequence[str] = ()) -> int:
    """Count raw-role copies only; generated H5/XMF products are allowed."""
    del output_root, supervisor_root
    if not target_root.exists():
        return 0
    names = {Path(item).name for item in raw_scope_paths}
    count = 0
    for path in target_root.rglob("*"):
        if path.is_file() and path.name in names:
            count += 1
    return count


def _new_namespace_bytes(bound: Mapping[str, Any]) -> int:
    """Count only this attempt's fresh target/output/supervisor namespaces."""
    target = Path(str(bound["worker_target"])).parents[2]
    roots = [target, Path(bound["output"]), Path(bound["supervisor"])]
    total = 0
    seen: set[Path] = set()
    for root in roots:
        root = root.expanduser().resolve()
        if root in seen or not root.exists():
            continue
        seen.add(root)
        for item in root.rglob("*"):
            if item.is_file() and not item.is_symlink():
                total += int(item.stat().st_size)
    return total


def _cleanup_attempt_scratch(bound: Mapping[str, Any]) -> dict[str, Any]:
    """Remove only the scratch directory owned by this attempt.

    This runs after the worker process group has been reaped.  It is also
    called on failure/timeout, so a decoder killed in the middle of a frame
    cannot leave uncharged external files behind.  A missing directory is a
    valid terminal state; a symlink or a path outside the bound external
    filesystem is a hard failure.
    """
    root = Path(bound["scratch_root"]).expanduser()
    external = Path(bound["scratch_external"]).expanduser()
    result: dict[str, Any] = {"path": str(root), "attempt_owned": True,
                              "removed": False, "remaining_bytes": 0,
                              "bytes_before_removal": 0}
    if root.exists() or root.is_symlink():
        if root.is_symlink() or not _under(root, external):
            result["error"] = "scratch cleanup path is not an owned external child"
            return result
        result["bytes_before_removal"] = _tree_bytes(root)
        result["remaining_bytes"] = int(result["bytes_before_removal"])
        shutil.rmtree(root)
        result["removed"] = True
        result["remaining_bytes"] = 0
    else:
        result["removed"] = True
    return result


def _copy_code(source: Path, target: Path, *, executable: bool = False) -> dict[str, Any]:
    if source.suffix.lower() in PAYLOAD_SUFFIXES or source.name.startswith("Part_"):
        raise PortableV64Error(f"payload copy is forbidden: {source}")
    if source.is_symlink() or not source.is_file() or source.stat().st_size > MAX_METADATA_BYTES:
        raise PortableV64Error(f"code source is not bounded regular file: {source}")
    if executable and not os.access(source, os.X_OK):
        raise PortableV64Error(f"bound executable is not executable: {source}")
    if target.exists() or target.is_symlink():
        raise PortableV64Error(f"refusing existing code target: {target}")
    _no_symlink_components(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as src, target.open("xb") as dst:
        while True:
            block = src.read(1024 * 1024)
            if not block:
                break
            dst.write(block)
    os.chmod(target, stat.S_IMODE(source.stat().st_mode))
    if _sha(source) != _sha(target):
        raise PortableV64Error(f"code overlay SHA differs: {source}")
    if executable and not os.access(target, os.X_OK):
        raise PortableV64Error(f"executable mode was not preserved: {target}")
    return {"source": str(source), "target": str(target), "bytes": int(target.stat().st_size),
            "sha256": _sha(target), "mode_bits": stat.S_IMODE(target.stat().st_mode),
            "payload_copied": False}


def _tail_append(buffer: deque[bytes], current: int, data: bytes) -> int:
    if not data:
        return current
    current += len(data)
    buffer.append(data)
    total = sum(len(item) for item in buffer)
    while total > LOG_TAIL_BYTES and buffer:
        removed = buffer.popleft()
        total -= len(removed)
    return current


def _kill_owned_group(proc: subprocess.Popen[Any], grace: float) -> dict[str, Any]:
    pgid = int(proc.pid)
    result: dict[str, Any] = {"pgid": pgid, "sigterm_sent": False,
                              "sigkill_sent": False, "reaped": False,
                              "group_gone": False, "grace_seconds": float(grace)}
    try:
        os.killpg(pgid, signal.SIGTERM)
        result["sigterm_sent"] = True
    except ProcessLookupError:
        pass
    deadline = time.monotonic() + max(0.1, float(grace))
    while time.monotonic() < deadline:
        try:
            proc.wait(timeout=min(0.1, max(0.01, deadline - time.monotonic())))
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            result["group_gone"] = True
            break
    if not result["group_gone"]:
        try:
            os.killpg(pgid, signal.SIGKILL)
            result["sigkill_sent"] = True
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            result["group_gone"] = True
    result["reaped"] = proc.poll() is not None
    return result


def _run_bounded(command: Sequence[str], *, cwd: Path, env: Mapping[str, str], timeout: float,
                 cleanup_grace: float, parent_pid: int) -> dict[str, Any]:
    """Run the owned worker with bounded pipes and group cleanup."""
    wrapper_pid = os.getpid()
    proc = subprocess.Popen(list(command), cwd=str(cwd), env=dict(env),
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, start_new_session=True,
                            preexec_fn=lambda pid=wrapper_pid: PARENT_V3._pdeath(pid))
    assert proc.stdout is not None and proc.stderr is not None
    streams = {proc.stdout.fileno(): (proc.stdout, deque()),
               proc.stderr.fileno(): (proc.stderr, deque())}
    for fd in streams:
        os.set_blocking(fd, False)
    selector = selectors.DefaultSelector()
    for fd in streams:
        selector.register(fd, selectors.EVENT_READ)
    counts = {"stdout": 0, "stderr": 0}
    discarded = {"stdout": 0, "stderr": 0}
    tails: dict[str, deque[bytes]] = {"stdout": deque(), "stderr": deque()}
    started = time.monotonic()
    cleanup: dict[str, Any] = {}
    timed_out = False
    try:
        while selector.get_map() or proc.poll() is None:
            remaining = float(timeout) - (time.monotonic() - started)
            if remaining <= 0:
                # A leader may have exited while a descendant inherited its
                # pipe.  Cleanup is therefore based on the deadline, never
                # on ``proc.poll()`` alone; otherwise selector.select can
                # wait forever on that descendant.
                timed_out = True
                cleanup = _kill_owned_group(proc, cleanup_grace)
                try:
                    selector.close()
                finally:
                    for stream, _ in streams.values():
                        stream.close()
                break
            events = selector.select(timeout=min(0.05, max(0.01, remaining)))
            for key, _ in events:
                fd = int(key.fd)
                stream, _unused = streams[fd]
                role = "stdout" if stream is proc.stdout else "stderr"
                try:
                    data = os.read(fd, 64 * 1024)
                except BlockingIOError:
                    continue
                if not data:
                    try:
                        selector.unregister(fd)
                    except Exception:
                        pass
                    continue
                counts[role] = _tail_append(tails[role], counts[role], data)
                # The deque is a rolling terminal tail; bytes beyond it are
                # deliberately discarded but still counted for accounting.
                retained = sum(len(item) for item in tails[role])
                discarded[role] = max(0, counts[role] - retained)
            if proc.poll() is not None and not selector.get_map():
                break
    except BaseException as error:
        cleanup = _kill_owned_group(proc, cleanup_grace)
        setattr(error, "v64_cleanup", cleanup)
        raise
    if selector.get_map():
        try:
            selector.close()
        finally:
            for stream, _ in streams.values():
                stream.close()
    if proc.poll() is None:
        proc.wait(timeout=5.0)
    return {
        "returncode": proc.returncode, "elapsed_seconds": time.monotonic() - started,
        "timed_out": timed_out, "cleanup": cleanup,
        "stdout_bytes": counts["stdout"], "stderr_bytes": counts["stderr"],
        "stdout_discarded_bytes": discarded["stdout"],
        "stderr_discarded_bytes": discarded["stderr"],
        "stdout_tail": b"".join(tails["stdout"]).decode("utf-8", "replace"),
        "stderr_tail": b"".join(tails["stderr"]).decode("utf-8", "replace"),
    }


def _extract_worker_result(stdout_tail: str) -> dict[str, Any] | None:
    for line in reversed(stdout_tail.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _read_typed_report_contract(report_path: Path) -> dict[str, Any]:
    """Read the bounded typed-output object after the report SHA is known.

    The generated HDF5 is deliberately not opened or re-hashed.  The worker
    report is the producer's small path/SHA/byte attestation and is joined to
    the bounded stdout summary by the parent.
    """
    if report_path.stat().st_size > 16 * 1024 * 1024:
        raise PortableV64Error("worker report exceeds the typed-output JSON join bound")
    try:
        value = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PortableV64Error(f"worker report cannot be read for typed-output join: {error}") from error
    typed = value.get("typed_output") if isinstance(value, Mapping) else None
    if not isinstance(typed, Mapping):
        raise PortableV64Error("worker report has no typed_output metadata object")
    path = typed.get("path")
    sha = typed.get("sha256")
    bytes_value = typed.get("bytes")
    if not isinstance(path, str) or not isinstance(sha, str) or not isinstance(bytes_value, int) or bytes_value < 0:
        raise PortableV64Error("worker report typed_output metadata is incomplete")
    _require_sha(sha, "worker report typed output SHA")
    return {"path": path, "sha256": sha, "bytes": bytes_value}


def _execution_contract(*, parent_hash_before: Mapping[str, Any] | None,
                        child: Mapping[str, Any] | None,
                        child_result: Mapping[str, Any] | None) -> dict[str, Any]:
    """Separate parent hashing evidence from child execution evidence.

    A failed child may have performed unknown I/O.  It is therefore never
    converted to a false/zero child flag.  A completed parent pre-hash is
    independently sufficient to report ``raw_opened`` as true.
    """
    child_success = bool(
        isinstance(child, Mapping) and child.get("returncode") == 0 and
        isinstance(child_result, Mapping) and
        not str(child_result.get("status", "")).startswith("FAILED"))
    names = ("raw_opened", "hdf5_opened", "converter_invoked",
             "label_operator_invoked", "model_invoked", "cfd_invoked")
    if child_success and isinstance(child_result, Mapping):
        boundary: dict[str, Any] = {name: bool(child_result.get(name, False)) for name in names}
    else:
        boundary = {name: "UNKNOWN" for name in names}
    parent_hash_raw_opened = parent_hash_before is not None
    if parent_hash_raw_opened:
        combined_raw_opened: bool | str = True
    elif boundary["raw_opened"] == "UNKNOWN":
        combined_raw_opened = "UNKNOWN"
    else:
        combined_raw_opened = bool(boundary["raw_opened"])
    return {
        "child_success": child_success,
        "parent_hash_raw_opened": parent_hash_raw_opened,
        "child_raw_opened": boundary["raw_opened"],
        "raw_opened": combined_raw_opened,
        "hdf5_opened": boundary["hdf5_opened"],
        "execution_boundary": boundary,
        "model_invoked": boundary["model_invoked"],
        "cfd_invoked": boundary["cfd_invoked"],
    }


def _assert_no_stale_actionable_paths(value: Any, *, key: str = "") -> None:
    """Reject stale attempt paths in executable/source fields, preserving provenance."""
    if isinstance(value, str):
        if "provenance" in key or "original_path" in key:
            return
        if any(stale in value for stale in ("V58D", "V58C", "V58B", "V58", "V59D", "V59B", "V59")):
            if key in {"path", "source_path", "target_path", "worker_path", "module_path",
                       "decoder_path", "motion_path", "data_root", "output_dir", "new_output_root"}:
                raise PortableV64Error(f"stale actionable path remains in {key}: {value}")
        return
    if isinstance(value, Mapping):
        for name, item in value.items():
            _assert_no_stale_actionable_paths(item, key=str(name))
    elif isinstance(value, list):
        for item in value:
            _assert_no_stale_actionable_paths(item, key=key)


def _pinned_path(value: Any, role: str) -> Path:
    path = _absolute(value, role)
    if not path.is_file() or path.is_symlink():
        raise PortableV64Error(f"{role} must be a regular file: {path}")
    return path


def _rebase_actionable_paths(value: Any, old_roots: Sequence[Path], target: Path,
                             output: Path, *, key: str = "") -> Any:
    """Rebase actionable copied paths while preserving provenance strings."""
    if isinstance(value, str) and "provenance" not in key and "original_path" not in key:
        for old in old_roots:
            old_text = str(old)
            if value == old_text or value.startswith(old_text + os.sep):
                suffix = value[len(old_text):].lstrip("/")
                # Paths below a target root remain under the target overlay;
                # paths below an output root remain under the new product root.
                if "output" in key.lower() or "product" in key.lower():
                    return str(output / suffix)
                return str(target / suffix)
        return value
    if isinstance(value, list):
        return [_rebase_actionable_paths(item, old_roots, target, output, key=key) for item in value]
    if isinstance(value, dict):
        return {name: _rebase_actionable_paths(item, old_roots, target, output, key=str(name))
                for name, item in value.items()}
    return value


def _build_worker_request(v62: Mapping[str, Any], *, raw_root: Path, target: Path,
                          output: Path, scope_paths: Sequence[str],
                          v2_worker_target: Path,
                          run_out_binding: Mapping[str, Any]) -> dict[str, Any]:
    embedded = v62.get("embedded_worker_request")
    if not isinstance(embedded, Mapping):
        raise PortableV64Error("V62 embedded worker request is missing")
    old_roots: list[Path] = []
    for item in (embedded.get("modules", {}) if isinstance(embedded.get("modules", {}), Mapping) else {}).values():
        if isinstance(item, Mapping) and isinstance(item.get("path"), str):
            old_roots.append(Path(item["path"]).expanduser().parents[2])
    if isinstance(v62.get("runtime", {}).get("worker_target"), str):
        old_roots.append(Path(v62["runtime"]["worker_target"]).expanduser().parents[2])
    old_output = v62.get("storage_scope", {}).get("external_output_root")
    if isinstance(old_output, str):
        old_roots.append(Path(old_output).expanduser())
    old_roots = list(dict.fromkeys(old_roots))
    result = copy.deepcopy(dict(embedded))
    result = _rebase_actionable_paths(result, old_roots, target, output)
    # The inherited binding is provenance only and must not remain an
    # executable alternate path in the V64 copied request.
    result.pop("v60_worker_binding", None)
    result.pop("v60_raw_scope", None)
    result.pop("v61_worker_binding", None)
    result.pop("v61_raw_scope", None)
    result.pop("v62_worker_binding", None)
    result.pop("v62_raw_scope", None)
    raw = result.get("raw_binding")
    if not isinstance(raw, dict):
        raise PortableV64Error("V62 embedded raw binding is missing")
    raw["data_root"] = str(raw_root)
    frames = raw.get("frames")
    if not isinstance(frames, list) or not frames:
        raise PortableV64Error("V62 embedded frame records are missing")
    for index, item in enumerate(frames):
        if not isinstance(item, dict) or item.get("frame") != index:
            raise PortableV64Error("embedded frame records are not contiguous")
        item["path"] = str(raw_root / f"Part_{index:04d}.bi4")
        item["content_sha256_source"] = "V64_PARENT_AFTER_RESERVATION"
        item["sha256"] = "PENDING_PARENT_GUARD_CONTENT_SHA256"
    recovery = result.get("recovery_binding")
    if isinstance(recovery, dict):
        recovery["new_output_root"] = str(output)
        recovery["raw_copy_forbidden"] = True
        recovery["parent_content_verification"] = "AFTER_ATOMIC_PARENT_RESERVATION"
    # All module paths are actionable copied paths.  Set them by role rather
    # than trusting stale V58D/V59 target strings embedded in the old request.
    modules = result.get("modules")
    if not isinstance(modules, dict):
        raise PortableV64Error("embedded module graph is missing")
    for role, item in modules.items():
        if isinstance(item, dict) and isinstance(item.get("path"), str):
            item["path"] = str(target / "runtime/native" / Path(item["path"]).name)
    if "worker" not in modules:
        raise PortableV64Error("embedded worker module is missing")
    modules["worker"]["path"] = str(v2_worker_target)
    decoder = result.get("decoder")
    if isinstance(decoder, dict) and isinstance(decoder.get("path"), str):
        decoder["path"] = str(target / "runtime/native" / Path(decoder["path"]).name)
    # The frozen V62 request retains the original JMotion provenance path.
    # The executable relocated request must point at the copied overlay while
    # retaining the expected bytes SHA and provenance separately.
    v15 = result.get("v15_request")
    if isinstance(v15, dict) and isinstance(v15.get("motion_engine_sources"), dict):
        for item in v15["motion_engine_sources"].values():
            if isinstance(item, dict) and isinstance(item.get("path"), str):
                item["original_path_provenance"] = item.get(
                    "original_path_provenance", item["path"])
                item["path"] = str(target / "runtime/native" / Path(item["path"]).name)
    # motion_engine_sources and any nested path-bearing fields are rebased by
    # the explicit old-root map above; reject stale known target roots below.
    result["run_out_binding"] = copy.deepcopy(dict(run_out_binding))
    # The worker-side contract uses ``path`` for the copied target; the
    # parent-side contract keeps source/target distinct as ``source_path`` /
    # ``target_path``.
    result["run_out_binding"]["path"] = result["run_out_binding"].get("target_path")
    result["run_out_binding"]["verification_phase"] = "AFTER_ATOMIC_PARENT_RESERVATION_PRE_AND_POST"
    result["v64_raw_scope"] = {
        "root": str(raw_root), "paths": list(scope_paths),
        "expected_tree_sha256": str(raw.get("expected_raw_tree_sha256", "")),
    }
    result["v64_worker_binding"] = {
        "code_root": str(target / "runtime/native"),
        "v2_worker_path": str(v2_worker_target),
        "module_sha256": {},
        "source_path_fallback": "FORBIDDEN",
    }
    result["schema"] = "ds02.stage2.f2-native-raw-to-typed-to-label-request.v2"
    result["status"] = "READY_FOR_PARENT_GUARD"
    result["source_hashes_preverified_by_parent"] = True
    return result


def _source_closure_from_embedded(embedded: Mapping[str, Any], *, raw_root: Path,
                                  target: Path) -> list[dict[str, Any]]:
    """Build the actionable metadata/motion closure without reading payloads.

    The parent verifies these entries after reservation.  Keeping them out of
    ``static_bindings`` is deliberate: the builder must not hash the large
    initial CSV/native evidence before an atomic reservation exists.
    """
    v15 = embedded.get("v15_request")
    if not isinstance(v15, Mapping):
        raise PortableV64Error("embedded V15 request is missing")
    # The worker envelope's source_files includes the replay request itself;
    # the nested V15 list alone omits that actionable metadata input.
    source_files = embedded.get("source_files")
    if not isinstance(source_files, list) or not source_files:
        raise PortableV64Error("embedded V15 source_files closure is missing")
    rows: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for index, item in enumerate(source_files):
        if not isinstance(item, Mapping):
            raise PortableV64Error(f"embedded source file is malformed: {index}")
        path_text = item.get("path")
        expected = item.get("sha256")
        if not isinstance(path_text, str) or not Path(path_text).is_absolute():
            raise PortableV64Error(f"embedded source file path is not absolute: {index}")
        _require_sha(expected, f"embedded source file SHA {index}")
        path = Path(path_text).expanduser()
        # source_files are rebased into the copied raw metadata tree.  Do not
        # accept an original worktree path as an actionable closure member.
        if not _under(path, raw_root):
            raise PortableV64Error(
                f"embedded actionable source is outside copied source tree: {path}")
        resolved = path.resolve()
        if resolved in seen:
            raise PortableV64Error(f"duplicate embedded source closure path: {path}")
        seen.add(resolved)
        rows.append({
            "role": str(item.get("role", f"v15_source_{index:03d}")),
            "path": str(path), "expected_sha256": str(expected),
            "source_kind": "V15_EMBEDDED_SOURCE_FILE",
            "verification_phase": "AFTER_ATOMIC_PARENT_RESERVATION_PRE_AND_POST",
            "read_by_worker": True,
        })
    motion = v15.get("motion_engine_sources")
    if not isinstance(motion, Mapping) or not motion:
        raise PortableV64Error("embedded motion engine source closure is missing")
    for role, item in motion.items():
        if not isinstance(item, Mapping):
            raise PortableV64Error(f"motion source is malformed: {role}")
        path_text = item.get("path")
        expected = item.get("sha256")
        if not isinstance(path_text, str) or not Path(path_text).is_absolute():
            raise PortableV64Error(f"motion source path is not absolute: {role}")
        _require_sha(expected, f"motion source SHA {role}")
        path = Path(path_text).expanduser()
        if not _under(path, target):
            raise PortableV64Error(
                f"motion source is not in the copied runtime overlay: {role}: {path}")
        resolved = path.resolve()
        if resolved in seen:
            raise PortableV64Error(f"duplicate motion/source closure path: {path}")
        seen.add(resolved)
        rows.append({
            "role": str(role), "path": str(path), "expected_sha256": str(expected),
            "source_kind": "JMotion_ENGINE_SOURCE",
            "verification_phase": "AFTER_ATOMIC_PARENT_RESERVATION_PRE_AND_POST",
            "read_by_worker": True,
        })
    return rows


def _verify_source_closure(closure: Sequence[Mapping[str, Any]], *, phase: str) -> list[dict[str, Any]]:
    """Hash every actionable copied metadata/motion source at one phase."""
    rows: list[dict[str, Any]] = []
    for item in closure:
        role = str(item.get("role", "source closure"))
        literal = Path(str(item.get("path", ""))).expanduser()
        if literal.is_symlink() or literal.absolute() != literal.resolve():
            raise PortableV64Error(f"source closure path uses a symlink: {role}")
        path = _absolute(literal, role)
        expected = _require_sha(item.get("expected_sha256"), str(item.get("role", "source closure")))
        observed = _sha(path)
        if observed != expected:
            raise PortableV64Error(
                f"source closure SHA differs for {item.get('role')}: {path}")
        st = path.stat()
        rows.append({"role": str(item.get("role")), "path": str(path),
                     "source_kind": str(item.get("source_kind", "")),
                     "phase": phase, "bytes": int(st.st_size),
                     "mtime_ns": int(st.st_mtime_ns),
                     "mode_bits": stat.S_IMODE(st.st_mode),
                     "sha256": observed})
    return rows


def _make_static_bindings(request: Mapping[str, Any], v62: Mapping[str, Any]) -> list[dict[str, Any]]:
    paths: list[tuple[str, Path]] = [("portable_executor_v64", SCRIPT),
                                     ("v64_private_bootstrap", BOOTSTRAP_SCRIPT),
                                     ("parent_executor_v3", PARENT_V3_PATH),
                                     ("shared_v21_accounting", V21_PATH),
                                     # runtime_v6 imports runtime_v2 as its
                                     # accounting base; both are actionable
                                     # runtime sources and must be sealed.
                                     ("shared_runtime_v2", RUNTIME_V2_DEFAULT),
                                     # The command keeps PINNED_PYTHON as a
                                     # literal venv argv path.  Bind the
                                     # resolved interpreter and pyvenv.cfg as
                                     # content dependencies without replacing
                                     # that argv path with /usr/bin/python3.10.
                                     ("pinned_python_resolved_binary", PINNED_PYTHON_RESOLVED),
                                     ("pinned_python_pyvenv_cfg", PINNED_PYVENV_CFG)]
    runtime = _pinned_path(request["runtime_binding"]["path"], "runtime v6")
    paths.append(("shared_runtime_v6", runtime))
    paths.append(("terminal_cpu_delta_adapter_v3", TERMINAL_DELTA_ADAPTER))
    for item in request.get("runtime", {}).get("code_overlay_bindings", []):
        if isinstance(item, Mapping):
            paths.append((str(item.get("role", "overlay")), _pinned_path(item.get("source_path"), "overlay source")))
    # Deduplicate by path while keeping role names explicit.
    result: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for role, path in paths:
        if path in seen:
            continue
        seen.add(path)
        result.append(_stat_binding(path, role))
    return result


def _rebind_overlay_sources(bindings: list[dict[str, Any]], raw_root: Path) -> list[dict[str, Any]]:
    """Resolve the one recorded ROOT145 copied-tree layout, explicitly.

    V58 recorded ``runtime/native`` as the actionable source path, while the
    actual ROOT145 copied bundle has the runtime under
    ``runtime/runtime/native``.  A generic recursive search would make a
    relocated run depend on whichever file happened to be latest.  The only
    accepted migration is this role-preserving, basename-exact overlay.
    """
    result: list[dict[str, Any]] = []
    for raw_item in bindings:
        item = copy.deepcopy(raw_item)
        source = _absolute(item.get("source_path"), str(item.get("role", "overlay source")))
        if not source.is_file():
            role = str(item.get("role", ""))
            candidate = raw_root / "runtime" / "runtime" / "native" / source.name
            if not candidate.is_file() or candidate.is_symlink():
                raise PortableV64Error(
                    f"overlay source is missing and has no exact ROOT145 runtime alias: {role}: {source}")
            item["source_path_provenance"] = str(source)
            item["source_path"] = str(candidate)
            item["source_path_resolution"] = "ROOT145_RUNTIME_RUNTIME_NATIVE_EXACT_ALIAS"
        else:
            item["source_path_resolution"] = "RECORDED_SOURCE_PATH"
        result.append(item)
    return result


def build_request(*, v62_request: Path | str, output_request: Path | str,
                  target_root: Path | str, output_root: Path | str,
                  ledger: Path | str, external_filesystem: Path | str,
                  home: Path | str = "/home/jade", home_receipt: Path | str,
                  supervisor_root: Path | str | None = None,
                  max_wall_seconds: float = 6000.0,
                  external_bytes: int = 12 * 1024**3,
                  external_min_free_bytes: int = 20 * 1024**3,
                  attempt_id: str | None = None,
                  case_id: str | None = None) -> dict[str, Any]:
    v62_path = _pinned_path(v62_request, "V62 request")
    v62 = _load_json(v62_path, "V62 request")
    if v62.get("schema") != "ds02.stage2.f2-root145-copied-recovery-parent-request.v62":
        raise PortableV64Error("input is not the frozen V62 request")
    if v62.get("sha256") != _canonical(v62):
        raise PortableV64Error("V62 request canonical SHA differs")
    # A fresh ROOT namespace must never silently inherit the old V38 case
    # identity.  The old identity remains in v62_provenance below, while all
    # actionable request/attempt/receipt paths use this explicit new case.
    if not isinstance(case_id, str) or not case_id.strip():
        raise PortableV64Error("V64 build requires an explicit --case-id for the new namespace")
    new_case_id = case_id.strip()
    old_case_id = v62.get("case_id")
    if not isinstance(old_case_id, str) or not old_case_id:
        raise PortableV64Error("V62 provenance case_id is missing")
    target = _absolute(target_root, "target root")
    output = _absolute(output_root, "output root")
    if target.exists() or output.exists() or target == output or _under(target, output) or _under(output, target):
        raise PortableV64Error("V64 fresh target/output roots must be absent and distinct")
    external = _absolute(external_filesystem, "external filesystem")
    if not external.is_dir() or not _under(target, external) or not _under(output, external):
        raise PortableV64Error("V64 fresh roots must be under external filesystem")
    raw_root = _absolute(v62["raw_source"]["root"], "reused raw root")
    if not raw_root.is_dir() or _under(target, raw_root) or _under(output, raw_root):
        raise PortableV64Error("reused raw root is invalid")
    embedded_seed = v62.get("embedded_worker_request")
    if not isinstance(embedded_seed, Mapping):
        raise PortableV64Error("V62 embedded worker request is missing")
    seed_raw = embedded_seed.get("raw_binding")
    if not isinstance(seed_raw, Mapping):
        raise PortableV64Error("V62 embedded raw binding is missing")
    seed_frames = seed_raw.get("frames")
    if not isinstance(seed_frames, list) or not seed_frames:
        raise PortableV64Error("V62 embedded frame list is missing")
    scope_paths = sorted(
        [f"Part_{index:04d}.bi4" for index in range(len(seed_frames))]
        + list(RAW_AUXILIARY_NAMES)
    )
    if len(scope_paths) != int(v62.get("raw_source", {}).get("file_count", 0)):
        raise PortableV64Error("V62 raw file count does not match explicit 405-file scope")
    attempt = str(attempt_id or "f2-s1-root145-v64-parent-recovery-20261009-001")
    # The V61 copied V2 worker is retained as a sibling.  V64 is the wrapper
    # that intercepts its converter manifest; its own target is a separate
    # actionable module path.
    old_worker = Path(str(v62["runtime"].get(
        "v2_worker_target", v62["runtime"]["worker_target"])))
    v2_worker_target = target / "runtime/native" / old_worker.name
    wrapper_target = target / "runtime/native/ds_data02_stage2_f2_native_raw_to_typed_label_v64.py"
    bootstrap_target = target / "runtime/native/ds_data02_stage2_f2_v64_bootstrap.py"
    # This directory is a fresh sibling of the product/output namespaces.  It
    # is created only by the copied worker after the parent reservation.  The
    # builder records the exact path so the child cannot fall back to /tmp.
    scratch_root = output.parent / f"{attempt}-decoder-scratch"
    # Resolve the exact bounded solver log from the copied solver receipt.
    # This is the only metadata source that may identify Run.out; no latest or
    # neighbouring output search is permitted.
    solver_receipt_item = next(
        (item for item in embedded_seed.get("source_files", [])
         if isinstance(item, Mapping) and item.get("role") == "solver_receipt"),
        None,
    )
    if not isinstance(solver_receipt_item, Mapping):
        raise PortableV64Error("V62 solver_receipt source binding is missing")
    solver_receipt_path = _pinned_path(solver_receipt_item.get("path"), "V62 solver receipt")
    run_out_source, run_out_stat = _run_out_from_solver_receipt(solver_receipt_path)
    run_out_target = target / "sources/0020-solver-Run.out"
    run_out_binding = {
        "source_path": str(run_out_source),
        "original_path_provenance": str(run_out_source),
        "target_path": str(run_out_target),
        "target_relative_path": "sources/0020-solver-Run.out",
        "expected_sha256": str(run_out_stat["sha256"]),
        "bytes": int(run_out_stat["bytes"]),
        "mtime_ns": int(run_out_stat["mtime_ns"]),
        "mode_bits": int(run_out_stat["mode_bits"]),
        # The copied source receipt remains in the immutable ROOT145 raw
        # bundle.  Only Run.out is copied into the fresh target overlay.
        "solver_receipt_path": str(solver_receipt_path),
        "solver_receipt_source_path_provenance": str(solver_receipt_path),
        "solver_receipt_sha256": str(run_out_stat["solver_receipt_sha256"]),
        "verification_phase": "AFTER_ATOMIC_PARENT_RESERVATION_PRE_AND_POST",
        "fallback": "FORBIDDEN",
    }
    embedded = _build_worker_request(v62, raw_root=raw_root, target=target, output=output,
                                      scope_paths=scope_paths, v2_worker_target=v2_worker_target,
                                      run_out_binding=run_out_binding)
    raw = embedded.get("raw_binding")
    if not isinstance(raw, Mapping):
        raise PortableV64Error("rebased V2 raw binding is missing")
    frames = raw.get("frames")
    if not isinstance(frames, list) or not frames:
        raise PortableV64Error("rebased V2 frame list is missing")
    receipt = _absolute(home_receipt, "Home receipt")
    if receipt.exists():
        raise PortableV64Error("Home receipt already exists")
    supervisor = _absolute(supervisor_root or output.parent / "supervisor", "supervisor root")
    if supervisor.exists() or not _under(supervisor, external):
        raise PortableV64Error("supervisor root must be a fresh external child")
    runtime_value = v62.get("runtime", {})
    if not isinstance(runtime_value, Mapping):
        raise PortableV64Error("V62 runtime binding is missing")
    code_bindings = _rebind_overlay_sources(
        [item for item in copy.deepcopy(runtime_value.get("code_overlay_bindings", []))
         if not (isinstance(item, Mapping) and str(item.get("role", "")) in {"v60_worker_wrapper", "v61_worker_wrapper", "v62_worker_wrapper", "v64_worker_wrapper"})],
        raw_root)
    for item in code_bindings:
        if not isinstance(item, dict):
            raise PortableV64Error("malformed V62 code overlay binding")
        target_relative = item.get("target_relative_path")
        if not isinstance(target_relative, str) or not target_relative:
            target_relative = f"runtime/native/{Path(str(item.get('target_path', ''))).name}"
        item["target_path"] = str(target / target_relative)
    code_bindings.append({
        "role": "v64_worker_wrapper",
        "source_path": str(WORKER_SCRIPT),
        "target_path": str(wrapper_target),
        "target_relative_path": "runtime/native/ds_data02_stage2_f2_native_raw_to_typed_label_v64.py",
        "bytes": int(WORKER_SCRIPT.stat().st_size),
        "sha256": _sha(WORKER_SCRIPT),
        "mode_bits": stat.S_IMODE(WORKER_SCRIPT.stat().st_mode),
        "required_executable": False,
        "content_verification_phase": "AFTER_ATOMIC_PARENT_RESERVATION",
    })
    code_bindings.append({
        "role": "v64_private_bootstrap",
        "source_path": str(BOOTSTRAP_SCRIPT),
        "target_path": str(bootstrap_target),
        "target_relative_path": "runtime/native/ds_data02_stage2_f2_v64_bootstrap.py",
        "bytes": int(BOOTSTRAP_SCRIPT.stat().st_size),
        "sha256": _sha(BOOTSTRAP_SCRIPT),
        "mode_bits": stat.S_IMODE(BOOTSTRAP_SCRIPT.stat().st_mode),
        "required_executable": False,
        "content_verification_phase": "AFTER_ATOMIC_PARENT_RESERVATION",
    })
    bindings = {
        "code_overlay_bindings": code_bindings,
        "worker_target": str(wrapper_target),
        "v2_worker_target": str(v2_worker_target),
        "worker_request_target": str(target / "runtime/native/f2-s1-v64-worker-request.json"),
        "bootstrap_target": str(bootstrap_target),
        "canonical_sibling_root": str(target / "runtime/native"),
        "pinned_python": PINNED_PYTHON,
    }
    module_sha256: dict[str, str] = {}
    for role, module in embedded.get("modules", {}).items():
        if not isinstance(module, Mapping) or not isinstance(module.get("path"), str):
            continue
        name = Path(module["path"]).name
        candidates = [item for item in code_bindings
                      if isinstance(item, Mapping) and Path(str(item.get("target_path", ""))).name == name]
        if candidates:
            module_sha256[str(role)] = str(candidates[0].get("sha256", ""))
    embedded["v64_worker_binding"]["module_sha256"] = module_sha256
    embedded["v64_worker_binding"]["bootstrap_target"] = bindings["bootstrap_target"]
    embedded.setdefault("runtime", {})["canonical_sibling_root"] = bindings["canonical_sibling_root"]
    embedded["runtime"]["scratch"] = {
        "attempt_owned": True,
        "attempt_id": attempt,
        "root": str(scratch_root),
        "external_root": str(external),
        "default_tmp_forbidden": True,
        "max_frame_bytes": DEFAULT_MAX_FRAME_SCRATCH_BYTES,
        "timeout_seconds": DEFAULT_DECODER_TIMEOUT_SECONDS,
        "cleanup": "per-frame-and-terminal",
    }
    command = [PINNED_PYTHON, "-B", "-I", bindings["bootstrap_target"],
               "--runtime-root", bindings["canonical_sibling_root"],
               "--worker", bindings["worker_target"], "--", "run", "--request",
               bindings["worker_request_target"], "--output-dir", str(output),
               "--io-slot-approved", "--run-labels"]
    ledger_path = _pinned_path(ledger, "parent ledger")
    ledger_value = _load_json(ledger_path, "parent ledger")
    limits = ledger_value.get("limits", {})
    home_path = _absolute(home, "Home filesystem")
    if not home_path.is_dir():
        raise PortableV64Error("Home filesystem is missing")
    home_floor = int(limits.get("home_min_free_bytes", 0) or 0)
    if int(limits.get("home_min_free_bytes", 0) or 0) != home_floor:
        raise PortableV64Error("invalid live Home floor")
    if max_wall_seconds <= 0 or not math.isfinite(float(max_wall_seconds)):
        raise PortableV64Error("max wall must be finite and positive")
    if int(external_bytes) <= 0 or int(external_min_free_bytes) < 0:
        raise PortableV64Error("external reservation is invalid")
    runtime_path = _pinned_path(RUNTIME_V6_DEFAULT, "shared runtime v6")
    runtime_v2_path = _pinned_path(RUNTIME_V2_DEFAULT, "shared runtime v2")
    resolved_python_path = _pinned_path(PINNED_PYTHON_RESOLVED, "resolved pinned Python")
    pyvenv_cfg_path = _pinned_path(PINNED_PYVENV_CFG, "pinned Python pyvenv.cfg")
    if not PINNED_PYTHON_PATH.is_file():
        raise PortableV64Error(f"literal pinned Python path is missing: {PINNED_PYTHON}")
    request: dict[str, Any] = {
        "schema": SCHEMA, "status": "READY_FOR_PARENT_GUARD", "role": "DEVELOPMENT",
        "family_id": "F2", "case_id": new_case_id, "request_id": attempt,
        "attempt_id": attempt, "worktree_root": str(SCRIPT_DIR.parent.parent),
        "parent_adapter": {"schema": "ds02.stage2.f2-portable-executor-parent-request.v3",
                            "implementation": str(PARENT_V3_PATH),
                            "apis": ["_reserve", "_charge", "_release", "ledger_locked"],
                            "same_parent_ledger": True},
        "terminal_cpu_delta_contract": {
            "schema": "ds02.stage2.systemd-terminal-cpu-delta.v3",
            "adapter": {"path": str(TERMINAL_DELTA_ADAPTER),
                         "sha256": _sha(TERMINAL_DELTA_ADAPTER),
                         "inspect_cli": "inspect --request ... --report ... --receipt ... --evidence ... --ledger ...",
                         "apply_cli": "apply ... --allow-ledger-mutation",
                         "mutation_default": "FORBIDDEN"},
            "evidence_role": "post_return_systemd_cpu_evidence",
            "same_parent_ledger": True, "append_once": True,
            "no_reservation": True, "no_nested_ledger_owner": True,
            "required_fields": ["unit", "request_sha256", "receipt_sha256",
                                "charge_id", "CPUUsageNSec", "terminal_status"],
            "scientific_status": "operational_accounting_only",
        },
        "v62_provenance": {"path": str(v62_path), "sha256": _sha(v62_path),
                           "schema": v62.get("schema"), "case_id": old_case_id,
                           "immutable": True},
        "python_binding": {
            # This literal string is the actual argv[0] and must not be
            # replaced by its resolved /usr/bin/python3.10 path.
            "argv_path": PINNED_PYTHON,
            "argv_path_kind": "literal_venv_invocation",
            "resolved_path": str(resolved_python_path),
            "resolved_sha256": _sha(resolved_python_path),
            "pyvenv_cfg_path": str(pyvenv_cfg_path),
            "pyvenv_cfg_sha256": _sha(pyvenv_cfg_path),
            "source_fallback": "FORBIDDEN",
        },
        "run_out_binding": run_out_binding,
        "raw_source": {
            "root": str(raw_root), "tree_sha256": str(v62["raw_source"].get("tree_sha256", "")),
            "file_count": len(scope_paths),
            "frame_count": len(frames), "copy_forbidden": True,
            "scope": "TOP_LEVEL_PRODUCER_RAW_EXPLICIT_V64",
            "scope_paths": scope_paths,
            "auxiliary_paths": list(RAW_AUXILIARY_NAMES),
            "scope_file_count": len(scope_paths),
            "verification_phase": "AFTER_ATOMIC_PARENT_RESERVATION_BEFORE_WORKER",
            "prepost_required": True, "frames": [
                {"frame": int(item["frame"]), "path": str(item["path"]),
                 "bytes": int(item.get("bytes", -1)),
                 "sha256": item.get("sha256") if item.get("sha256") not in {None, "PENDING_PARENT_GUARD_CONTENT_SHA256"} else None}
                for item in frames if isinstance(item, Mapping)
            ]},
        "runtime": {"pinned_python": PINNED_PYTHON,
                    "worker_target": bindings["worker_target"],
                    "v2_worker_target": bindings["v2_worker_target"],
                    "worker_request_target": bindings["worker_request_target"],
                    "bootstrap_target": bindings["bootstrap_target"],
                    "canonical_sibling_root": bindings["canonical_sibling_root"],
                    "code_overlay_bindings": bindings["code_overlay_bindings"],
                    "raw_copy_forbidden": True,
                    "scratch": embedded["runtime"]["scratch"],
                    "decoder_scratch_scope": "external_attempt_owned_per_frame",
                    },
                "embedded_worker_request": embedded,
        "execution": {"command": command, "python": PINNED_PYTHON,
                       "max_wall_seconds": float(max_wall_seconds),
                       "cpu_reservation_seconds": float(max_wall_seconds),
                       "memory_max_bytes": 16 * 1024**3,
                       "memory_enforcement": "outer parent/systemd cgroup; worker reports observational RSS separately",
                       "child_cleanup_grace_seconds": CHILD_CLEANUP_GRACE_SECONDS,
                       "bounded_log_bytes_per_stream": MAX_LOG_BYTES,
                       "log_tail_bytes": LOG_TAIL_BYTES,
                       "process_group": "owned child PGID; TERM grace then KILL",
                       "parent_death_signal": "PR_SET_PDEATHSIG=SIGTERM",
                       "env": dict(THREAD_ENV),
                       "content_hash_scope": "raw full pre/post tree and every bound Part frame after reservation",
                       "original_path_fallback": "FORBIDDEN"},
        "parent_resource_binding": {
            "ledger_path": str(ledger_path), "attempt_id": attempt,
            "reservation_id": attempt + "::reservation", "charge_id": attempt + "::charge",
            "same_parent_ledger": True, "ledger_reset": False, "allow_missing_parent": True,
            "storage_policy": str(limits.get("storage_policy", "")),
            "deadline_utc": str(ledger_value.get("deadline_utc", "")),
            "home_path": str(home_path), "home_min_free_bytes": home_floor,
            "external_filesystem": str(external),
        },
        "runtime_binding": {"path": str(runtime_path), "sha256": _sha(runtime_path),
                            "role": "shared_runtime_v6", "immutable": True,
                            "base_import": "ds_data02_runtime_v2",
                            "base_path": str(runtime_v2_path),
                            "base_sha256": _sha(runtime_v2_path),
                            "base_role": "shared_runtime_v2"},
        "storage_scope": {
            "external_filesystem": str(external), "external_output_root": str(output),
            "supervisor_output_root": str(supervisor), "home_receipt_path": str(receipt),
            "home_receipt_bytes": MIN_HOME_RECEIPT_BYTES,
            "external_reservation_bytes": int(external_bytes),
            "source_copy_bytes": 0, "reused_source_copy_bytes_not_recharged": True,
            "external_min_free_bytes": int(external_min_free_bytes),
            "home_min_free_bytes": home_floor, "two_filesystem_charge_required": True,
            "decoder_scratch_peak_reservation_bytes": DEFAULT_MAX_FRAME_SCRATCH_BYTES,
            "external_peak_charge": "max(final_namespace_bytes, observed_output_plus_frame_scratch_plus_static_overlay)",
            "new_namespace_absent_before_run": True},
        "static_bindings": [],
        "model_invoked": False, "cfd_invoked": False, "raw_opened": False,
        "hdf5_opened": False, "fresh_cold_credit": False, "qualification": dict(UNKNOWN),
        "limitations": [
            "Development recovery over an immutable copied raw root; no fresh-cold credit.",
            "Parent-v3 reserve/charge are the only ledger mutations; no nested ledger owner.",
            "Raw content is read only after reservation and is verified before and after the child.",
            "Private interpreter environment remains an explicit bound external dependency; source fallback is forbidden.",
            "Decoder scratch is attempt-owned under the external filesystem, capped per frame, and removed after every frame and terminal path.",
            "The 12 GiB external estimate includes a 512 MiB decoder-scratch peak allowance; observed peak is charged conservatively after the child.",
        ],
    }
    request["resource_estimate"] = {
        "frames": len(frames),
        "particles_total": 418104,
        "selected_fluid_particles": 21114,
        "typed_logical_bytes": 6711826720,
        "typed_output_estimate_bytes": 1191110530,
        "replay_peak_memory_estimate_bytes": 1954047113,
        "memory_max_bytes": 16 * 1024**3,
        "decoder_max_frame_scratch_bytes": DEFAULT_MAX_FRAME_SCRATCH_BYTES,
        "external_reservation_bytes": int(external_bytes),
        "estimate_scope": "source-bound ROOT145 metadata estimate; actual peak is reported by V64 worker",
        "scientific_payload_read": False,
    }
    request["source_closure"] = _source_closure_from_embedded(
        embedded, raw_root=raw_root, target=target)
    request["static_bindings"] = _make_static_bindings(request, v62)
    request["sha256"] = _canonical(request)
    out = _write_new(output_request, request)
    return {"schema": SCHEMA, "status": request["status"], "request": str(out),
            "request_sha256": _sha(out), "payload_read": False,
            "raw_copy_bytes": 0, "fresh_cold_credit": False, "qualification": dict(UNKNOWN)}


def _validate_request(path: Path, *, verify_static: bool = False) -> dict[str, Any]:
    request = _load_json(path, "V64 parent request")
    if request.get("schema") != SCHEMA or request.get("status") != "READY_FOR_PARENT_GUARD":
        raise PortableV64Error("unsupported or non-ready V64 parent request")
    if request.get("sha256") != _canonical(request):
        raise PortableV64Error("V64 request canonical SHA differs")
    if request.get("role") != "DEVELOPMENT" or request.get("qualification") != UNKNOWN:
        raise PortableV64Error("V64 must remain DEVELOPMENT/UNKNOWN")
    case_id = request.get("case_id")
    provenance = request.get("v62_provenance")
    if not isinstance(case_id, str) or not case_id.strip():
        raise PortableV64Error("V64 case_id must identify the new namespace")
    if not isinstance(provenance, Mapping) or not isinstance(provenance.get("case_id"), str):
        raise PortableV64Error("V62 provenance case_id is required")
    if case_id == provenance.get("case_id"):
        raise PortableV64Error("new V64 case_id may not inherit the V62 provenance case")
    if request.get("model_invoked") is not False or request.get("cfd_invoked") is not False:
        raise PortableV64Error("V64 model/CFD invocation is forbidden")
    delta_contract = request.get("terminal_cpu_delta_contract")
    adapter = delta_contract.get("adapter") if isinstance(delta_contract, Mapping) else None
    if (not isinstance(delta_contract, Mapping) or
            delta_contract.get("schema") != "ds02.stage2.systemd-terminal-cpu-delta.v3" or
            delta_contract.get("same_parent_ledger") is not True or
            delta_contract.get("append_once") is not True or
            delta_contract.get("no_reservation") is not True or
            not isinstance(adapter, Mapping) or
            not isinstance(adapter.get("path"), str) or
            _require_sha(adapter.get("sha256"), "terminal delta adapter SHA") != _sha(_pinned_path(adapter.get("path"), "terminal delta adapter"))):
        raise PortableV64Error("V64 terminal CPU delta contract is incomplete")
    parent = request.get("parent_resource_binding")
    storage = request.get("storage_scope")
    execution = request.get("execution")
    runtime_binding = request.get("runtime_binding")
    if not all(isinstance(value, Mapping) for value in (parent, storage, execution, runtime_binding)):
        raise PortableV64Error("V64 parent/storage/execution binding is incomplete")
    ledger = _pinned_path(parent.get("ledger_path"), "parent ledger")
    external = _absolute(storage.get("external_filesystem"), "external filesystem")
    if not external.is_dir():
        raise PortableV64Error("external filesystem is missing")
    output = _absolute(storage.get("external_output_root"), "external output root")
    supervisor = _absolute(storage.get("supervisor_output_root"), "supervisor root")
    receipt = _absolute(storage.get("home_receipt_path"), "Home receipt")
    for item, name in ((output, "output"), (supervisor, "supervisor")):
        if item.exists() or not _under(item, external):
            raise PortableV64Error(f"{name} must be a fresh child of external filesystem")
        _no_symlink_components(item)
    if receipt.exists():
        raise PortableV64Error("Home receipt already exists")
    if int(storage.get("home_receipt_bytes", 0) or 0) < MIN_HOME_RECEIPT_BYTES:
        raise PortableV64Error("Home receipt reservation must cover at least 1 MiB of bounded metadata tails")
    run_out = request.get("run_out_binding")
    if not isinstance(run_out, Mapping):
        raise PortableV64Error("explicit Run.out binding is missing")
    run_out_source = _pinned_path(run_out.get("source_path"), "Run.out source")
    _pinned_path(run_out.get("solver_receipt_path"), "Run.out solver receipt")
    run_out_target = _absolute(run_out.get("target_path"), "Run.out target")
    run_out_expected = _require_sha(run_out.get("expected_sha256"), "Run.out expected SHA")
    _require_sha(run_out.get("solver_receipt_sha256"), "solver receipt SHA")
    if run_out_source.stat().st_size > MAX_METADATA_BYTES:
        raise PortableV64Error("Run.out source exceeds metadata size bound")
    if run_out_target.exists():
        raise PortableV64Error("Run.out target must be fresh")
    if run_out_target.name != "0020-solver-Run.out":
        raise PortableV64Error("Run.out target has an unexpected basename")
    raw = request.get("raw_source")
    if not isinstance(raw, Mapping):
        raise PortableV64Error("raw_source is missing")
    raw_root = _absolute(raw.get("root"), "reused raw root")
    if not raw_root.is_dir() or raw_root == output or _under(output, raw_root):
        raise PortableV64Error("reused raw root/output relationship is invalid")
    expected_tree = _require_sha(raw.get("tree_sha256"), "raw_source.tree_sha256")
    frames = raw.get("frames")
    if not isinstance(frames, list) or int(raw.get("frame_count", 0)) != len(frames) or not frames:
        raise PortableV64Error("raw_source frame contract is incomplete")
    for index, item in enumerate(frames):
        if not isinstance(item, Mapping) or int(item.get("frame", -1)) != index:
            raise PortableV64Error("raw frames are not contiguous")
        frame_path = _absolute(item.get("path"), f"raw frame {index}")
        if frame_path != raw_root / f"Part_{index:04d}.bi4" or not frame_path.is_file() or frame_path.is_symlink():
            raise PortableV64Error(f"raw frame {index} is not the exact top-level Part path")
        if int(item.get("bytes", -1)) != frame_path.stat().st_size:
            raise PortableV64Error(f"raw frame {index} byte stat differs")
        if item.get("sha256") is not None:
            _require_sha(item.get("sha256"), f"raw frame {index} SHA")
    scope_paths = raw.get("scope_paths")
    if (raw.get("scope") != "TOP_LEVEL_PRODUCER_RAW_EXPLICIT_V64" or
            not isinstance(scope_paths, list) or scope_paths != sorted(scope_paths) or
            len(scope_paths) != int(raw.get("scope_file_count", -1)) or
            len(scope_paths) != int(raw.get("file_count", -2))):
        raise PortableV64Error("explicit 405-file producer raw scope is incomplete")
    expected_scope = sorted(
        [f"Part_{index:04d}.bi4" for index in range(len(frames))]
        + list(RAW_AUXILIARY_NAMES)
    )
    if scope_paths != expected_scope:
        raise PortableV64Error("raw scope is not the exact frames plus four producer auxiliary files")
    for relative in scope_paths:
        candidate = Path(relative)
        if candidate.is_absolute() or ".." in candidate.parts or candidate.as_posix() != relative:
            raise PortableV64Error(f"raw scope path escapes root: {relative}")
    runtime = request.get("runtime")
    if not isinstance(runtime, Mapping):
        raise PortableV64Error("runtime binding is missing")
    worker_target = _absolute(runtime.get("worker_target"), "worker target")
    v2_worker_target = _absolute(runtime.get("v2_worker_target"), "V2 worker target")
    worker_request_target = _absolute(runtime.get("worker_request_target"), "worker request target")
    bootstrap_target = _absolute(runtime.get("bootstrap_target"), "V64 bootstrap target")
    canonical_sibling_root = _absolute(runtime.get("canonical_sibling_root"), "canonical sibling root")
    if not _under(worker_target, output.parent) or worker_target.suffix != ".py":
        raise PortableV64Error("worker target is outside fresh target namespace")
    if worker_request_target.exists():
        raise PortableV64Error("worker request target must be fresh")
    if worker_target.name != "ds_data02_stage2_f2_native_raw_to_typed_label_v64.py":
        raise PortableV64Error("worker target must be the V64 scoped-manifest wrapper")
    if not _under(v2_worker_target, worker_target.parent) or v2_worker_target.suffix != ".py":
        raise PortableV64Error("V2 worker target is outside the copied native module directory")
    if not _under(bootstrap_target, worker_target.parent) or bootstrap_target.suffix != ".py":
        raise PortableV64Error("V64 bootstrap target is outside the copied native module directory")
    if canonical_sibling_root != worker_target.parent:
        raise PortableV64Error("canonical sibling root does not equal the copied native module directory")
    if bootstrap_target.name != "ds_data02_stage2_f2_v64_bootstrap.py":
        raise PortableV64Error("V64 bootstrap target has an unexpected basename")
    for stale in ("V58", "V58D", "V59", "V59B", "V59D"):
        if stale in str(v2_worker_target):
            raise PortableV64Error("V2 worker target retains a stale attempt namespace")
    overlay = runtime.get("code_overlay_bindings")
    if not isinstance(overlay, list) or not overlay:
        raise PortableV64Error("V64 code overlay bindings are missing")
    target_root = worker_target.parents[2]
    bootstrap_rows = [item for item in overlay
                      if isinstance(item, Mapping) and item.get("target_path") == str(bootstrap_target)]
    if len(bootstrap_rows) != 1:
        raise PortableV64Error("V64 bootstrap is not represented exactly once in the code overlay")
    if not _under(run_out_target, target_root) or run_out_target != target_root / "sources/0020-solver-Run.out":
        raise PortableV64Error("Run.out target must be the bound fresh target/sources path")
    for item in overlay:
        if not isinstance(item, Mapping):
            raise PortableV64Error("V64 code overlay binding is malformed")
        source = _pinned_path(item.get("source_path"), str(item.get("role", "overlay source")))
        destination = _absolute(item.get("target_path"), str(item.get("role", "overlay target")))
        if not _under(destination, target_root) or destination == worker_target:
            # The wrapper is part of the overlay and is allowed to be the
            # command target; this check only forbids targets escaping it.
            if destination != worker_target:
                raise PortableV64Error("code overlay target escapes fresh target root")
        if int(item.get("bytes", -1)) != source.stat().st_size:
            raise PortableV64Error(f"code overlay source byte stat differs: {source}")
        target_relative = item.get("target_relative_path")
        if not isinstance(target_relative, str) or destination != target_root / target_relative:
            raise PortableV64Error(f"code overlay target does not match its relative path: {destination}")
    embedded = request.get("embedded_worker_request")
    if not isinstance(embedded, Mapping):
        raise PortableV64Error("embedded V2 request is missing")
    embedded_modules = embedded.get("modules")
    if not isinstance(embedded_modules, Mapping):
        raise PortableV64Error("embedded V2 module graph is missing")
    binding = embedded.get("v64_worker_binding")
    if (not isinstance(binding, Mapping) or
            binding.get("code_root") != str(worker_target.parent) or
            binding.get("bootstrap_target") != str(bootstrap_target)):
        raise PortableV64Error("embedded V64 worker binding is incomplete")
    module_shas = binding.get("module_sha256")
    if not isinstance(module_shas, Mapping):
        raise PortableV64Error("embedded module SHA graph is missing")
    for role, item in embedded_modules.items():
        if not isinstance(item, Mapping) or not isinstance(item.get("path"), str):
            raise PortableV64Error(f"embedded module path is missing: {role}")
        module_path = _absolute(item["path"], f"embedded module {role}")
        if not _under(module_path, worker_target.parent) or module_path.name == worker_target.name:
            raise PortableV64Error(f"embedded module is outside copied native module directory: {role}")
        if role in {"worker", "raw_converter", "v14_operator", "v15_operator", "v16_operator"}:
            declared_sha = _require_sha(item.get("sha256"), f"embedded module {role} SHA")
            expected_sha = _require_sha(module_shas.get(role), f"embedded module {role} expected SHA")
            if declared_sha != expected_sha:
                raise PortableV64Error(f"embedded module SHA does not match expected binding: {role}")
    embedded_raw = embedded.get("raw_binding")
    if not isinstance(embedded_raw, Mapping) or embedded_raw.get("data_root") != str(raw_root):
        raise PortableV64Error("embedded V2 raw root is not the producer scope root")
    embedded_scope = embedded.get("v64_raw_scope")
    if not isinstance(embedded_scope, Mapping) or embedded_scope.get("paths") != scope_paths:
        raise PortableV64Error("embedded V2 raw scope differs from parent scope")
    embedded_run_out = embedded.get("run_out_binding")
    if not isinstance(embedded_run_out, Mapping):
        raise PortableV64Error("embedded V2 Run.out binding is missing")
    if (embedded_run_out.get("path") != str(run_out_target) or
            embedded_run_out.get("expected_sha256") != run_out_expected):
        raise PortableV64Error("embedded V2 Run.out binding differs from parent binding")
    embedded_runtime = embedded.get("runtime")
    scratch = runtime.get("scratch")
    if not isinstance(scratch, Mapping) or not isinstance(embedded_runtime, Mapping):
        raise PortableV64Error("V64 decoder scratch binding is missing")
    scratch_root = _absolute(scratch.get("root"), "decoder scratch root")
    scratch_external = _absolute(scratch.get("external_root"), "decoder scratch external root")
    if scratch_root.exists() or not _under(scratch_root, scratch_external):
        raise PortableV64Error("decoder scratch root must be a fresh child of external storage")
    if scratch_external != external or scratch_root.parent != output.parent:
        raise PortableV64Error("decoder scratch is not the fresh attempt sibling of the product")
    if scratch_root == output or scratch_root in output.parents:
        raise PortableV64Error("decoder scratch may not be the product or its parent")
    if scratch_root in {Path("/tmp"), Path("/var/tmp")}:
        raise PortableV64Error("decoder scratch may not use shared temporary storage")
    max_frame = scratch.get("max_frame_bytes")
    timeout = scratch.get("timeout_seconds")
    if (isinstance(max_frame, bool) or not isinstance(max_frame, int) or
            max_frame <= 0 or max_frame > 1024 * 1024 * 1024):
        raise PortableV64Error("decoder scratch frame cap is invalid")
    if (isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or
            not math.isfinite(float(timeout)) or float(timeout) <= 0):
        raise PortableV64Error("decoder scratch timeout is invalid")
    if embedded_runtime.get("scratch") != dict(scratch):
        raise PortableV64Error("embedded decoder scratch binding differs from parent")
    source_closure = request.get("source_closure")
    if not isinstance(source_closure, list) or not source_closure:
        raise PortableV64Error("after-reservation source closure is missing")
    closure_seen: set[Path] = set()
    for item in source_closure:
        if not isinstance(item, Mapping):
            raise PortableV64Error("source closure entry is malformed")
        role = str(item.get("role", "source closure"))
        literal_source_path = Path(str(item.get("path", ""))).expanduser()
        if literal_source_path.is_symlink() or literal_source_path.absolute() != literal_source_path.resolve():
            raise PortableV64Error(f"source closure path uses a symlink: {role}")
        source_path = _absolute(literal_source_path, role)
        _require_sha(item.get("expected_sha256"), f"{role} expected SHA")
        if item.get("verification_phase") != "AFTER_ATOMIC_PARENT_RESERVATION_PRE_AND_POST":
            raise PortableV64Error(f"source closure phase is not after-reservation: {role}")
        if source_path in closure_seen:
            raise PortableV64Error(f"duplicate source closure path: {source_path}")
        closure_seen.add(source_path)
        kind = str(item.get("source_kind", ""))
        if kind == "V15_EMBEDDED_SOURCE_FILE":
            if not _under(source_path, raw_root):
                raise PortableV64Error(f"V15 source closure escapes copied source tree: {role}")
        elif kind == "JMotion_ENGINE_SOURCE":
            if not _under(source_path, target_root):
                raise PortableV64Error(f"motion source closure escapes copied target: {role}")
        else:
            raise PortableV64Error(f"unknown actionable source closure kind: {kind}")
    _assert_no_stale_actionable_paths(embedded)
    command = execution.get("command")
    if not isinstance(command, list) or not all(isinstance(item, str) for item in command):
        raise PortableV64Error("worker command is malformed")
    expected_command_prefix = [str(execution.get("python")), "-B", "-I", str(bootstrap_target),
                               "--runtime-root", str(canonical_sibling_root),
                               "--worker", str(worker_target), "--"]
    if command[:len(expected_command_prefix)] != expected_command_prefix:
        raise PortableV64Error("worker command does not use the copied V64 bootstrap")
    # Never normalize argv[0] through Path.resolve(): that would turn the
    # bound venv invocation into /usr/bin/python3.10 and reintroduce the
    # system NumPy/h5py ABI.  The resolved binary and pyvenv.cfg are checked
    # as separate static dependencies below.
    python_binding = request.get("python_binding")
    if (not isinstance(python_binding, Mapping) or
            python_binding.get("argv_path") != PINNED_PYTHON or
            python_binding.get("argv_path_kind") != "literal_venv_invocation" or
            execution.get("python") != PINNED_PYTHON or
            runtime.get("pinned_python") != PINNED_PYTHON or
            not command or command[0] != PINNED_PYTHON):
        raise PortableV64Error("worker command must preserve the literal pinned venv interpreter")
    resolved_python = _pinned_path(python_binding.get("resolved_path"),
                                    "resolved pinned Python")
    pyvenv_cfg = _pinned_path(python_binding.get("pyvenv_cfg_path"),
                              "pinned Python pyvenv.cfg")
    if resolved_python != PINNED_PYTHON_RESOLVED or pyvenv_cfg != PINNED_PYVENV_CFG:
        raise PortableV64Error("pinned Python resolver/cfg paths differ from the literal venv")
    if (_require_sha(python_binding.get("resolved_sha256"), "resolved pinned Python SHA") !=
            _sha(resolved_python) or
            _require_sha(python_binding.get("pyvenv_cfg_sha256"), "pyvenv.cfg SHA") !=
            _sha(pyvenv_cfg)):
        raise PortableV64Error("pinned Python resolver/cfg content differs")
    max_wall = float(execution.get("max_wall_seconds", 0.0) or 0.0)
    if not math.isfinite(max_wall) or max_wall <= 0:
        raise PortableV64Error("max wall is invalid")
    if abs(float(execution.get("cpu_reservation_seconds", -1.0)) - max_wall) > 1e-9:
        raise PortableV64Error("CPU reservation must equal max wall")
    if int(execution.get("memory_max_bytes", 0) or 0) < 16 * 1024**3:
        raise PortableV64Error("V64 memory cap must be at least 16 GiB")
    if float(execution.get("child_cleanup_grace_seconds", 0.0)) < 20.0:
        raise PortableV64Error("cleanup grace must be at least 20 seconds")
    if int(execution.get("bounded_log_bytes_per_stream", 0)) <= 0:
        raise PortableV64Error("bounded log limit is missing")
    runtime_path = _pinned_path(runtime_binding.get("path"), "shared runtime v6")
    runtime_sha = _require_sha(runtime_binding.get("sha256"), "shared runtime SHA")
    runtime_v2_path = _pinned_path(runtime_binding.get("base_path"), "shared runtime v2")
    runtime_v2_sha = _require_sha(runtime_binding.get("base_sha256"), "shared runtime v2 SHA")
    if (runtime_binding.get("role") != "shared_runtime_v6" or
            runtime_binding.get("base_role") != "shared_runtime_v2" or
            runtime_binding.get("base_import") != "ds_data02_runtime_v2" or
            runtime_v2_path != RUNTIME_V2_DEFAULT or
            runtime_v2_sha != _sha(runtime_v2_path)):
        raise PortableV64Error("runtime_v6 to runtime_v2 dependency binding is incomplete")
    static = request.get("static_bindings")
    if not isinstance(static, list) or not static:
        raise PortableV64Error("static source closure is missing")
    static_by_role: dict[str, Mapping[str, Any]] = {}
    for item in static:
        if not isinstance(item, Mapping):
            raise PortableV64Error("static binding is malformed")
        role = str(item.get("role", "static"))
        if role in static_by_role:
            raise PortableV64Error(f"duplicate static binding role: {role}")
        static_by_role[role] = item
        source = _pinned_path(item.get("path"), role)
        if int(item.get("bytes", -1)) != source.stat().st_size:
            raise PortableV64Error(f"static byte stat differs: {source}")
        declared_sha = _require_sha(item.get("sha256"), f"{role} static binding SHA")
        if verify_static and _sha(source) != declared_sha:
            raise PortableV64Error(f"static source SHA differs: {source}")
    required_static_roles = {
        "shared_runtime_v2", "shared_runtime_v6",
        "pinned_python_resolved_binary", "pinned_python_pyvenv_cfg",
    }
    missing_static = sorted(required_static_roles.difference(static_by_role))
    if missing_static:
        raise PortableV64Error(
            "V64 static closure is missing required runtime/interpreter roles: "
            + ", ".join(missing_static))
    if static_by_role["shared_runtime_v2"].get("path") != str(runtime_v2_path):
        raise PortableV64Error("shared runtime v2 static binding differs from runtime dependency")
    if static_by_role["shared_runtime_v2"].get("sha256") != runtime_v2_sha:
        raise PortableV64Error("shared runtime v2 static SHA differs from runtime dependency")
    if static_by_role["shared_runtime_v6"].get("path") != str(runtime_path):
        raise PortableV64Error("shared runtime v6 static binding differs from runtime dependency")
    if static_by_role["shared_runtime_v6"].get("sha256") != runtime_sha:
        raise PortableV64Error("shared runtime v6 static SHA differs from runtime dependency")
    if static_by_role["pinned_python_resolved_binary"].get("path") != str(resolved_python):
        raise PortableV64Error("resolved pinned Python is not in the static closure")
    if static_by_role["pinned_python_resolved_binary"].get("sha256") != python_binding.get("resolved_sha256"):
        raise PortableV64Error("resolved pinned Python static SHA differs from python binding")
    if static_by_role["pinned_python_pyvenv_cfg"].get("path") != str(pyvenv_cfg):
        raise PortableV64Error("pyvenv.cfg is not in the static closure")
    if static_by_role["pinned_python_pyvenv_cfg"].get("sha256") != python_binding.get("pyvenv_cfg_sha256"):
        raise PortableV64Error("pyvenv.cfg static SHA differs from python binding")
    if runtime_path.stat().st_size <= 0:
        raise PortableV64Error("runtime is empty")
    limits = _load_json(ledger, "parent ledger").get("limits", {})
    if str(parent.get("storage_policy")) != str(limits.get("storage_policy")):
        raise PortableV64Error("storage policy differs from live ledger")
    if int(parent.get("home_min_free_bytes", -1)) != int(limits.get("home_min_free_bytes", -2)):
        raise PortableV64Error("Home floor differs from live ledger")
    return {"path": path, "request": request, "ledger": ledger, "external": external,
            "output": output, "supervisor": supervisor, "receipt": receipt,
            "raw_root": raw_root, "expected_tree": expected_tree, "frames": frames,
            "scope_paths": scope_paths,
            "source_closure": source_closure,
            "runtime_path": runtime_path, "runtime_sha": runtime_sha,
            "worker_target": worker_target, "v2_worker_target": v2_worker_target,
            "bootstrap_target": bootstrap_target, "canonical_sibling_root": canonical_sibling_root,
            "scratch_root": scratch_root, "scratch_external": scratch_external,
            "scratch_max_frame_bytes": int(max_frame), "scratch_timeout_seconds": float(timeout),
            "worker_request_target": worker_request_target,
            "run_out_binding": run_out,
            "max_wall": max_wall, "cleanup_grace": float(execution["child_cleanup_grace_seconds"]),
            "external_estimate": int(storage["external_reservation_bytes"]),
            "home_estimate": int(storage["home_receipt_bytes"]),
            "limits": limits, "parent_attempt_id": str(parent["attempt_id"]),
            "reservation_id": str(parent["reservation_id"]), "charge_id": str(parent["charge_id"]),
            "allow_missing_parent": bool(parent.get("allow_missing_parent", False))}


def _fill_worker_request(bound: Mapping[str, Any], target: Path, output: Path,
                         observed: Mapping[str, Any]) -> dict[str, Any]:
    request = copy.deepcopy(dict(bound["request"]["embedded_worker_request"]))
    bound_run_out = bound.get("run_out_binding")
    embedded_run_out = request.get("run_out_binding")
    if not isinstance(bound_run_out, Mapping) or not isinstance(embedded_run_out, Mapping):
        raise PortableV64Error("Run.out binding is missing from worker request")
    if (embedded_run_out.get("path") != bound_run_out.get("target_path") or
            embedded_run_out.get("expected_sha256") != bound_run_out.get("expected_sha256")):
        raise PortableV64Error("worker Run.out binding differs from parent-copied metadata")
    raw = request.get("raw_binding")
    if not isinstance(raw, dict):
        raise PortableV64Error("embedded worker raw binding is missing")
    raw["data_root"] = str(bound["raw_root"])
    files = {str(bound["raw_root"] / str(item["path"])): item for item in observed["files"]}
    for item in raw.get("frames", []):
        path = str(item.get("path"))
        if path not in files:
            raise PortableV64Error(f"observed frame is absent from raw manifest: {path}")
        item["sha256"] = files[path]["sha256"]
        item["bytes"] = files[path]["bytes"]
        item["content_sha256_source"] = "V64_PARENT_OBSERVED_AFTER_RESERVATION"
    binding = request.get("recovery_binding")
    if isinstance(binding, dict):
        binding["new_output_root"] = str(output)
        binding["raw_tree_before_sha256"] = observed["tree_sha256"]
        binding["raw_copy_forbidden"] = True
    scope = request.get("v64_raw_scope")
    if not isinstance(scope, dict) or scope.get("paths") != list(bound["scope_paths"]):
        raise PortableV64Error("embedded worker scope was changed before execution")
    scope["root"] = str(bound["raw_root"])
    scope["expected_tree_sha256"] = observed["tree_sha256"]
    runtime = request.get("runtime")
    if not isinstance(runtime, dict):
        raise PortableV64Error("embedded V2 runtime binding is missing at fill")
    scratch = runtime.get("scratch")
    if not isinstance(scratch, dict) or str(scratch.get("root")) != str(bound["scratch_root"]):
        raise PortableV64Error("embedded V2 scratch path differs from parent binding")
    if str(runtime.get("canonical_sibling_root")) != str(bound["canonical_sibling_root"]):
        raise PortableV64Error("embedded canonical sibling root differs from parent binding")
    modules = request.get("modules")
    if not isinstance(modules, Mapping):
        raise PortableV64Error("embedded module graph is missing at fill")
    for item in modules.values():
        if isinstance(item, Mapping) and isinstance(item.get("path"), str):
            if any(stale in item["path"] for stale in ("V58", "V58D", "V59", "V59B", "V59D")):
                raise PortableV64Error("stale V58/V59 actionable module path remains")
    return request


def _run_child(bound: Mapping[str, Any], worker_request: Path, *, parent_pid: int,
               timeout_seconds: float | None = None) -> dict[str, Any]:
    execution = bound["request"]["execution"]
    command = [str(item) for item in execution.get("command", [])]
    if not command or "--request" not in command or "--output-dir" not in command:
        raise PortableV64Error("V64 execution command is incomplete")
    request_index = command.index("--request") + 1
    output_index = command.index("--output-dir") + 1
    if request_index >= len(command) or output_index >= len(command):
        raise PortableV64Error("V64 execution command has incomplete path arguments")
    if command[request_index] != str(worker_request) or command[output_index] != str(bound["output"]):
        raise PortableV64Error("V64 execution command is not bound to the fresh worker request/output")
    env = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "PYTHONHOME"}}
    env.update({str(key): str(value) for key, value in execution.get("env", THREAD_ENV).items()})
    env["TMPDIR"] = str(bound["scratch_root"])
    env["TEMP"] = str(bound["scratch_root"])
    env["TMP"] = str(bound["scratch_root"])
    return _run_bounded(command, cwd=bound["worker_target"].parent, env=env,
                        timeout=float(timeout_seconds if timeout_seconds is not None else bound["max_wall"]),
                        cleanup_grace=bound["cleanup_grace"],
                        parent_pid=parent_pid) | {"command": command}


def run(request_path: Path | str, *, io_slot_approved: bool,
        parent_pid: int | None = None) -> dict[str, Any]:
    entry_wall = time.monotonic()
    entry_cpu = _cpu_seconds()
    path = _absolute(request_path, "V64 request")
    raw_request = _load_json(path, "V64 request")
    max_wall = float(raw_request.get("execution", {}).get("max_wall_seconds", 0.0) or 0.0)
    if not io_slot_approved:
        bound = _validate_request(path, verify_static=False)
        preflight = {"schema": REPORT_SCHEMA, "status": "READY_FOR_PARENT_IO_SLOT",
                     "request": {"path": str(path), "sha256": _sha(path)},
                     "metadata_only": True, "reservation_applied": False,
                     "content_hash_read": False, "hdf5_or_bi4_read": False,
                     "model_invoked": False, "cfd_invoked": False, "qualification": dict(UNKNOWN)}
        preflight_path = path.with_suffix(".preflight.json")
        _write_new(preflight_path, {**preflight, "sha256": _canonical(preflight)})
        return preflight | {"preflight_path": str(preflight_path)}
    if parent_pid is None or int(parent_pid) <= 1 or os.getppid() != int(parent_pid):
        raise PortableV64Error("actual V64 run requires its direct parent PID")
    if max_wall <= 0:
        raise PortableV64Error("max wall is missing")
    bound = _validate_request(path, verify_static=False)
    if abs(bound["max_wall"] - max_wall) > 1e-9:
        raise PortableV64Error("max wall changed during validation")
    PARENT_V3._pdeath(int(parent_pid))
    previous_signals = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGALRM)}
    previous_timer = signal.setitimer(signal.ITIMER_REAL, 0.0)

    def _interrupt(signum: int, _frame: Any) -> None:
        label = signal.Signals(signum).name
        raise PortableV64Error(f"V64 parent received {label}; owned worker cleanup required")

    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGALRM):
        signal.signal(sig, _interrupt)
    signal.setitimer(signal.ITIMER_REAL, bound["max_wall"])
    reservation_applied = False
    child_result: dict[str, Any] | None = None
    child: dict[str, Any] | None = None
    status = "FAILED_PARENT_EXECUTOR"
    error: str | None = None
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    source_before: list[dict[str, Any]] | None = None
    source_after: list[dict[str, Any]] | None = None
    run_out_before: dict[str, Any] | None = None
    run_out_after: dict[str, Any] | None = None
    posthash_scope = "NOT_ATTEMPTED"
    observed_worker: dict[str, Any] | None = None
    code_rows: list[dict[str, Any]] = []
    typed_report_contract: dict[str, Any] | None = None
    scratch_cleanup: dict[str, Any] | None = None
    external_charge_bytes: int | None = None
    try:
        # This is the existing parent-v3 atomic reservation, not a second ledger.
        PARENT_V3._reserve({"runtime_path": bound["runtime_path"], "runtime_sha": bound["runtime_sha"],
                            "ledger": bound["ledger"], "external": bound["external"],
                            "limits": bound["limits"], "external_estimate": bound["external_estimate"],
                            "home_estimate": bound["home_estimate"], "max_wall": bound["max_wall"],
                            "reservation_id": bound["reservation_id"], "charge_id": bound["charge_id"],
                            "parent_attempt_id": bound["parent_attempt_id"],
                            "request": bound["request"]})
        reservation_applied = True
        _validate_request(path, verify_static=True)
        target = _absolute(bound["request"]["runtime"]["worker_target"], "target worker").parents[2]
        target.mkdir(parents=True, exist_ok=False)
        bound["output"].mkdir(parents=True, exist_ok=False)
        bound["supervisor"].mkdir(parents=True, exist_ok=False)
        for item in bound["request"]["runtime"].get("code_overlay_bindings", []):
            if not isinstance(item, Mapping):
                raise PortableV64Error("malformed code overlay binding")
            source = _pinned_path(item.get("source_path"), str(item.get("role", "overlay")))
            destination = _absolute(item.get("target_path"), str(item.get("role", "overlay target")))
            if not _under(destination, target):
                raise PortableV64Error("code target escapes fresh target")
            code_rows.append(_copy_code(source, destination, executable=bool(item.get("required_executable"))))
        # Run.out is a bounded solver metadata input, copied only after the
        # same-parent reservation.  The worker receives this target path and
        # cannot follow the original receipt's output_root.
        run_out_copy = _copy_bound_metadata(bound["run_out_binding"])
        run_out_before = _verify_bound_metadata(
            bound["run_out_binding"], phase="AFTER_RESERVATION_BEFORE_WORKER")
        run_out_before["copy"] = run_out_copy
        # These metadata and JMotion sources are explicitly actionable.  They
        # are verified only after the atomic reservation and after their code
        # overlay has been copied; builder/preflight never hashes them.
        source_before = _verify_source_closure(
            bound["source_closure"], phase="AFTER_RESERVATION_BEFORE_WORKER")
        before = _raw_tree_manifest(bound["raw_root"], bound["scope_paths"], bound["expected_tree"])
        posthash_scope = "PRE_AND_POST_REQUIRED"
        if before["tree_sha256"] != bound["expected_tree"]:
            raise PortableV64Error("raw source tree SHA differs from source-bound producer tree")
        worker_request = bound["worker_request_target"]
        worker_request.parent.mkdir(parents=True, exist_ok=True)
        worker_value = _fill_worker_request(bound, target, bound["output"], before)
        _write_new(worker_request, worker_value)
        child_remaining = entry_wall + bound["max_wall"] - time.monotonic()
        if child_remaining <= 0:
            raise PortableV64Error("parent deadline expired before child launch")
        child = _run_child(bound, worker_request, parent_pid=os.getpid(),
                           timeout_seconds=child_remaining)
        child_result = _extract_worker_result(str(child.get("stdout_tail", "")))
        if child.get("timed_out"):
            raise PortableV64Error("strict recovery worker exceeded parent deadline")
        if int(child.get("returncode", -1)) != 0:
            raise PortableV64Error(f"strict recovery worker returned {child.get('returncode')}: {child.get('stderr_tail', '')[-1200:]}")
        if not isinstance(child_result, Mapping) or str(child_result.get("status", "")).startswith("FAILED"):
            raise PortableV64Error("strict recovery worker did not report a successful status")
        if child_result.get("schema") != "ds02.stage2.f2-native-raw-to-typed-to-label-worker-summary.v64":
            raise PortableV64Error("worker did not return the bounded V64 summary schema")
        report_text = child_result.get("report_path")
        report_sha = child_result.get("report_file_sha256")
        if not isinstance(report_text, str) or not isinstance(report_sha, str):
            raise PortableV64Error("worker summary lacks bound report path/file SHA")
        report_path = _absolute(report_text, "worker report")
        if not _under(report_path, bound["output"]) or not report_path.is_file():
            raise PortableV64Error("worker report is outside the fresh output namespace")
        if _sha(report_path) != _require_sha(report_sha, "worker report file SHA"):
            raise PortableV64Error("worker report file SHA differs from its summary")
        typed_report_contract = _read_typed_report_contract(report_path)
        typed_text = child_result.get("typed_output_path")
        typed_sha = child_result.get("typed_output_sha256")
        typed_bytes = child_result.get("typed_output_bytes")
        if not isinstance(typed_text, str) or not isinstance(typed_sha, str):
            raise PortableV64Error("worker summary lacks bound typed output path/SHA")
        _require_sha(typed_sha, "typed output SHA")
        typed_path = _absolute(typed_text, "typed output")
        if typed_path.is_symlink() or not typed_path.is_file() or not _under(typed_path, bound["output"]):
            raise PortableV64Error("typed output is outside the fresh output namespace")
        if not isinstance(typed_bytes, int) or typed_bytes < 0 or typed_path.stat().st_size != typed_bytes:
            raise PortableV64Error("typed output stat is absent or differs from worker summary")
        if (typed_report_contract["path"] != typed_text or
                typed_report_contract["sha256"] != typed_sha or
                typed_report_contract["bytes"] != typed_bytes):
            raise PortableV64Error("typed output report contract differs from worker summary")
        after = _raw_tree_manifest(bound["raw_root"], bound["scope_paths"], bound["expected_tree"])
        if after["tree_sha256"] != before["tree_sha256"] or after["files"] != before["files"]:
            raise PortableV64Error("raw source tree changed during worker")
        worker_raw = child_result.get("raw_tree_before_sha256")
        if worker_raw is not None and worker_raw != before["tree_sha256"]:
            raise PortableV64Error("worker raw pre-tree SHA differs")
        worker_after = child_result.get("raw_tree_after_sha256")
        if worker_after is not None and worker_after != after["tree_sha256"]:
            raise PortableV64Error("worker raw post-tree SHA differs")
        source_after = _verify_source_closure(
            bound["source_closure"], phase="AFTER_WORKER_BEFORE_TERMINAL")
        run_out_after = _verify_bound_metadata(
            bound["run_out_binding"], phase="AFTER_WORKER_BEFORE_TERMINAL")
        status = "COMPLETED_PARENT_EXECUTOR_RAW_TYPED_LABEL_UNKNOWN"
    except BaseException as exc:
        error = f"{type(exc).__name__}: {exc}"
        status = "FAILED_PARENT_EXECUTOR"
        cleanup_from_error = getattr(exc, "v64_cleanup", None)
        if cleanup_from_error:
            child = {"returncode": None, "cleanup": cleanup_from_error,
                     "timed_out": True, "stdout_tail": "", "stderr_tail": "",
                     "stdout_bytes": 0, "stderr_bytes": 0,
                     "stdout_discarded_bytes": 0, "stderr_discarded_bytes": 0,
                     "command": None}
        if child and child.get("timed_out") is False and child.get("returncode") is None:
            # _run_bounded owns timeout cleanup; this branch covers a signal or
            # exception between Popen and its normal return.
            pass
    finally:
        deadline = entry_wall + bound["max_wall"] if "bound" in locals() else entry_wall
        remaining = deadline - time.monotonic()
        if before is None and reservation_applied and remaining > 0:
            try:
                before = _raw_tree_manifest(bound["raw_root"], bound["scope_paths"], bound["expected_tree"])
                posthash_scope = "PRE_ONLY_RECOVERED_AFTER_RESERVATION"
            except BaseException:
                before = None
        elif before is None and reservation_applied:
            posthash_scope = "SKIPPED_DEADLINE_EXPIRED"
        if after is None and reservation_applied:
            remaining = deadline - time.monotonic()
            if remaining > 0:
                try:
                    after = _raw_tree_manifest(bound["raw_root"], bound["scope_paths"], bound["expected_tree"])
                    posthash_scope = "PRE_AND_POST_COMPLETED"
                except BaseException:
                    after = None
                    posthash_scope = "POSTHASH_INTERRUPTED_OR_FAILED"
            else:
                posthash_scope = "SKIPPED_DEADLINE_EXPIRED"
        if source_after is None and source_before is not None and reservation_applied:
            remaining = deadline - time.monotonic()
            if remaining > 0:
                try:
                    source_after = _verify_source_closure(
                        bound["source_closure"], phase="POST_WORKER_FINALIZATION")
                except BaseException:
                    source_after = None
        if run_out_after is None and run_out_before is not None and reservation_applied:
            remaining = deadline - time.monotonic()
            if remaining > 0:
                try:
                    run_out_after = _verify_bound_metadata(
                        bound["run_out_binding"], phase="POST_WORKER_FINALIZATION")
                except BaseException:
                    run_out_after = None
        signal.setitimer(signal.ITIMER_REAL, 0.0)
        for sig, previous in previous_signals.items():
            signal.signal(sig, previous)
        if previous_timer[0] > 0:
            signal.setitimer(signal.ITIMER_REAL, previous_timer[0], previous_timer[1])
        if reservation_applied and "bound" in locals():
            try:
                scratch_cleanup = _cleanup_attempt_scratch(bound)
            except BaseException as cleanup_error:
                scratch_cleanup = {"path": str(bound.get("scratch_root")),
                                   "attempt_owned": True, "removed": False,
                                   "bytes_before_removal": 0,
                                   "error": f"{type(cleanup_error).__name__}: {cleanup_error}"}
    try:
        external_bytes = _new_namespace_bytes(bound)
        target_root = Path(bound["worker_target"]).parents[2]
        raw_copy_attempts = _payload_copy_count(
            target_root, bound["output"], bound["supervisor"], bound["scope_paths"])
        if isinstance(child_result, Mapping):
            try:
                raw_copy_attempts += max(0, int(child_result.get("raw_copy_attempts", 0) or 0))
            except (TypeError, ValueError):
                raise PortableV64Error("worker raw_copy_attempts is not an integer")
        if raw_copy_attempts:
            status = "FAILED_PARENT_EXECUTOR"
            error = error or "raw payload copy/attempt observed in new namespace"
        execution_contract = _execution_contract(
            parent_hash_before=before, child=child, child_result=child_result)
        child_success = bool(execution_contract["child_success"])
        child_boundary = execution_contract["execution_boundary"]
        parent_hash_raw_opened = bool(execution_contract["parent_hash_raw_opened"])
        raw_opened = execution_contract["raw_opened"]
        observed_worker_peak: int | None = None
        if child_success and isinstance(child_result, Mapping):
            observed_value = child_result.get("external_peak_bytes")
            if isinstance(observed_value, int) and observed_value >= 0:
                observed_worker_peak = int(observed_value)
        static_overlay_bytes = sum(int(item.get("bytes", 0)) for item in code_rows)
        if run_out_before and isinstance(run_out_before.get("target"), Mapping):
            static_overlay_bytes += int(run_out_before["target"].get("bytes", 0) or 0)
        if "worker_request" in locals() and worker_request.exists():
            static_overlay_bytes += int(worker_request.stat().st_size)
        if observed_worker_peak is not None:
            # The worker peak covers its product namespace plus the live
            # decoder frame.  Add the copied code/metadata namespace so the
            # single parent charge conservatively covers the true external
            # peak rather than charging only the final tree size.
            external_peak_bytes: int | None = max(
                int(external_bytes), observed_worker_peak + static_overlay_bytes)
            external_charge_bytes = int(external_peak_bytes)
            external_peak_status = "OBSERVED_WORKER_PEAK_PLUS_STATIC_OVERLAY"
        else:
            external_peak_bytes = None
            external_charge_bytes = int(external_bytes)
            external_peak_status = "UNKNOWN_CHILD_PEAK_FINAL_NAMESPACE_CHARGED"
        report = {
            "schema": REPORT_SCHEMA, "status": status,
            "error": error,
            "request": {"path": str(path), "sha256": _sha(path)},
            "parent": {"ledger_path": str(bound["ledger"]), "attempt_id": bound["parent_attempt_id"],
                       "same_parent_ledger": True, "ledger_reset": False, "parent_pid": parent_pid},
            "executor": {"worker_command": child.get("command") if child else None,
                         "returncode": child.get("returncode") if child else None,
                         "result": child_result},
            "raw_source": {"root": str(bound["raw_root"]), "expected_tree_sha256": bound["expected_tree"],
                           "scope": "TOP_LEVEL_PRODUCER_RAW_EXPLICIT_V64",
                           "scope_paths": list(bound["scope_paths"]),
                           "before": before, "after": after,
                           "posthash_scope": posthash_scope,
                           "full_prepost_equal": bool(before and after and before["files"] == after["files"])},
            "source_closure": {"declared": list(bound["source_closure"]),
                               "before": source_before, "after": source_after,
                               "prepost_equal": bool(
                                   source_before and source_after and
                                   [{k: row.get(k) for k in ("role", "path", "source_kind", "bytes", "mtime_ns", "mode_bits", "sha256")}
                                    for row in source_before] ==
                                   [{k: row.get(k) for k in ("role", "path", "source_kind", "bytes", "mtime_ns", "mode_bits", "sha256")}
                                    for row in source_after]),
                               "verification_phase": "AFTER_ATOMIC_PARENT_RESERVATION_PRE_AND_POST"},
            "copy_contract": {"raw_copy_attempts": raw_copy_attempts, "raw_source_copy_bytes": 0,
                              "new_code_overlay": code_rows, "old_namespace_write": "FORBIDDEN"},
            "decoder_scratch": {"declared": dict(bound["request"]["runtime"]["scratch"]),
                                 "worker_report": (child_result.get("decoder_scratch")
                                                    if isinstance(child_result, Mapping) else None),
                                 "cleanup": scratch_cleanup,
                                 "external_peak_bytes": external_peak_bytes,
                                 "external_peak_status": external_peak_status,
                                 "per_frame_cleanup_required": True},
            "run_out": {"declared": dict(bound["run_out_binding"]),
                        "before": run_out_before, "after": run_out_after,
                        "prepost_equal": bool(run_out_before and run_out_after and
                                              run_out_before.get("target", {}).get("sha256") ==
                                              run_out_after.get("target", {}).get("sha256")),
                        "copy_phase": "AFTER_ATOMIC_PARENT_RESERVATION",
                        "original_path_fallback": "FORBIDDEN"},
            "execution": {"entry_wall_seconds": time.monotonic() - entry_wall,
                           "entry_cpu_seconds": max(0.0, _cpu_seconds() - entry_cpu),
                           "max_wall_seconds": bound["max_wall"],
                           "bounded_logs": ({key: child.get(key) for key in (
                               "stdout_bytes", "stderr_bytes", "stdout_discarded_bytes", "stderr_discarded_bytes",
                               "stdout_tail", "stderr_tail")} if child else {}),
                           "cleanup": child.get("cleanup") if child else {},
                           "cancel_scope": "owned worker process group only"},
            "filesystem": {"external_output_root": str(bound["output"]),
                            "supervisor_root": str(bound["supervisor"]),
                            "external_bytes": external_bytes,
                            "external_peak_bytes": external_peak_bytes,
                            "external_charge_bytes": external_charge_bytes,
                            "home_receipt_path": str(bound["receipt"]),
                            "storage_filesystems": [str(bound["external"]), str(bound["limits"].get("home_path", "/home/jade"))]},
            "accounting": {"reservation_id": bound["reservation_id"], "charge_id": bound["charge_id"],
                           "reservation_applied": reservation_applied,
                           "charge_status_at_report_write": "pending_same_parent_charge",
                           "allow_missing_parent": bound["allow_missing_parent"]},
            "parent_hash_raw_opened": parent_hash_raw_opened,
            "child_raw_opened": child_boundary["raw_opened"],
            "raw_opened": raw_opened,
            "hdf5_opened": execution_contract["hdf5_opened"],
            "execution_boundary": child_boundary,
            "typed_output_contract": ({"path": child_result.get("typed_output_path"),
                                        "bytes": child_result.get("typed_output_bytes"),
                                        "sha256": child_result.get("typed_output_sha256"),
                                        "report": typed_report_contract,
                                        "join_status": "REPORT_SHA_AND_SUMMARY_MATCH",
                                        "verified_by_child_worker": True,
                                        "parent_rehashed": False} if child_success and child_result else {
                                            "join_status": "UNKNOWN_CHILD_NO_SUMMARY"}),
            "model_invoked": execution_contract["model_invoked"],
            "cfd_invoked": execution_contract["cfd_invoked"],
            "fresh_cold_credit": False, "qualification": dict(UNKNOWN),
            "original_path_fallback": "FORBIDDEN"}
        # The receipt is Home output and is written before the existing parent-v3
        # charge.  Its actual final stat, not a guessed fixed point, is charged.
        _write_new(bound["receipt"], report)
        home_bytes = int(bound["receipt"].stat().st_size)
        cpu = max(0.0, _cpu_seconds() - entry_cpu)
        charge = PARENT_V3._charge({"runtime_path": bound["runtime_path"], "runtime_sha": bound["runtime_sha"],
                                    "ledger": bound["ledger"], "external": bound["external"],
                                    "limits": bound["limits"], "request": bound["request"],
                                    "reservation_id": bound["reservation_id"], "charge_id": bound["charge_id"],
                                    "parent_attempt_id": bound["parent_attempt_id"]},
                                   status="completed" if status.startswith("COMPLETED") else "failed",
                                   cpu_seconds=cpu, external_bytes=external_charge_bytes, home_bytes=home_bytes,
                                   trace_bytes=0, copy_hash_bytes=sum(int(item.get("bytes", 0)) for item in code_rows),
                                   allow_missing_parent=bound["allow_missing_parent"])
        return {"schema": REPORT_SCHEMA, "status": status, "report_path": str(bound["receipt"]),
                "request_sha256": _sha(path), "ledger_mutated": bool(charge.get("ledger_mutated")),
                "charge": charge, "external_bytes": external_bytes,
                "external_peak_bytes": external_peak_bytes,
                "external_charge_bytes": external_charge_bytes,
                "home_bytes": home_bytes,
                "raw_copy_attempts": raw_copy_attempts,
                "parent_hash_raw_opened": parent_hash_raw_opened,
                "child_raw_opened": child_boundary["raw_opened"],
                "raw_opened": raw_opened,
                "hdf5_opened": execution_contract["hdf5_opened"],
                "fresh_cold_credit": False, "qualification": dict(UNKNOWN)}
    except BaseException as final_error:
        if reservation_applied:
            try:
                external_bytes = _new_namespace_bytes(bound)
                scratch_bytes = int((scratch_cleanup or {}).get("bytes_before_removal", 0) or 0)
                external_charge_bytes = int(external_bytes) + max(0, scratch_bytes)
                PARENT_V3._charge({"runtime_path": bound["runtime_path"], "runtime_sha": bound["runtime_sha"],
                                   "ledger": bound["ledger"], "external": bound["external"],
                                   "limits": bound["limits"], "request": bound["request"],
                                   "reservation_id": bound["reservation_id"], "charge_id": bound["charge_id"],
                                   "parent_attempt_id": bound["parent_attempt_id"]},
                                  status="failed", cpu_seconds=max(0.0, _cpu_seconds() - entry_cpu),
                                  external_bytes=external_charge_bytes,
                                  home_bytes=int(bound["receipt"].stat().st_size) if bound["receipt"].exists() else 0,
                                  trace_bytes=0, copy_hash_bytes=0,
                                  allow_missing_parent=bound["allow_missing_parent"])
            except BaseException:
                # Preserve the original failure; parent-v3 itself has the
                # release/charge policy and the caller must inspect this state.
                pass
        return {"schema": REPORT_SCHEMA, "status": "FAILED_PARENT_EXECUTOR_FINALIZATION",
                "error": f"{type(final_error).__name__}: {final_error}",
                "request_sha256": _sha(path), "ledger_mutated": False,
                "scratch_cleanup": scratch_cleanup,
                "external_charge_bytes": external_charge_bytes if reservation_applied else None,
                "fresh_cold_credit": False, "qualification": dict(UNKNOWN)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-request")
    build.add_argument("--v62-request", type=Path, required=True)
    build.add_argument("--output-request", type=Path, required=True)
    build.add_argument("--target-root", type=Path, required=True)
    build.add_argument("--output-root", type=Path, required=True)
    build.add_argument("--ledger", type=Path, required=True)
    build.add_argument("--external-filesystem", type=Path, required=True)
    build.add_argument("--home", type=Path, default=Path("/home/jade"))
    build.add_argument("--home-receipt", type=Path, required=True)
    build.add_argument("--supervisor-root", type=Path)
    build.add_argument("--max-wall-seconds", type=float, default=6000.0)
    build.add_argument("--external-bytes", type=int, default=12 * 1024**3)
    build.add_argument("--external-min-free-bytes", type=int, default=20 * 1024**3)
    build.add_argument("--attempt-id")
    build.add_argument("--case-id", required=True,
                       help="explicit new case identity; the V62 case is provenance only")
    preflight = sub.add_parser("preflight")
    preflight.add_argument("--request", type=Path, required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--request", type=Path, required=True)
    run_parser.add_argument("--io-slot-approved", action="store_true")
    run_parser.add_argument("--parent-pid", type=int)
    args = parser.parse_args(argv)
    try:
        if args.command == "build-request":
            result = build_request(v62_request=args.v62_request, output_request=args.output_request,
                                   target_root=args.target_root, output_root=args.output_root,
                                   ledger=args.ledger, external_filesystem=args.external_filesystem,
                                   home=args.home, home_receipt=args.home_receipt,
                                   supervisor_root=args.supervisor_root,
                                   max_wall_seconds=args.max_wall_seconds,
                                   external_bytes=args.external_bytes,
                                   external_min_free_bytes=args.external_min_free_bytes,
                                   attempt_id=args.attempt_id,
                                   case_id=args.case_id)
        elif args.command == "preflight":
            path = _absolute(args.request, "V64 request")
            result = _validate_request(path, verify_static=False)
            result = {"schema": REPORT_SCHEMA, "status": "READY_FOR_PARENT_IO_SLOT",
                      "request": str(path), "metadata_only": True, "payload_read": False}
        else:
            result = run(args.request, io_slot_approved=args.io_slot_approved,
                         parent_pid=args.parent_pid)
    except (PortableV64Error, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"f2 portable executor v64: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=True, default=str))
    return 1 if str(result.get("status", "")).startswith("FAILED") else 0


if __name__ == "__main__":
    raise SystemExit(main())
