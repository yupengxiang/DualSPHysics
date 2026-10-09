#!/usr/bin/env python3
"""V59 parent-compatible direct recovery guard.

V58 proved the direct worker path, but its runner was only a direct recovery
command: it did not speak the existing parent-v3 ledger boundary and it kept
unbounded child output in memory.  V59 is the additive boundary for that
worker.  It uses the already deployed parent-v3 ``_reserve`` and ``_charge``
functions, keeps Home and external storage separate, and owns only a fresh
process group and fresh output namespace.

The raw ROOT145 tree is an immutable input.  V59 never copies it.  After the
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
import stat
import subprocess
import sys
import time
import resource
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
PARENT_V3_PATH = SCRIPT_DIR / "ds_data02_stage2_f2_portable_executor_parent_v3.py"
V21_PATH = SCRIPT_DIR / "ds_data02_stage2_f2_external_supervisor_v21.py"
RUNTIME_V6_DEFAULT = SCRIPT_DIR / "ds_data02_runtime_v6.py"
PINNED_PYTHON = "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python"
SCHEMA = "ds02.stage2.f2-root145-copied-recovery-parent-request.v59"
REPORT_SCHEMA = "ds02.stage2.f2-root145-copied-recovery-report.v59"
WORKER_SCHEMA = "ds02.stage2.f2-root145-copied-worker-request.v59"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")
PAYLOAD_SUFFIXES = {".bi4", ".obi4", ".h5", ".hdf5", ".xmf"}
MAX_METADATA_BYTES = 8 * 1024 * 1024
MAX_LOG_BYTES = 4 * 1024 * 1024
LOG_TAIL_BYTES = 64 * 1024
CHILD_CLEANUP_GRACE_SECONDS = 25.0
THREAD_ENV = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
}


class PortableV59Error(RuntimeError):
    pass


def _load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise PortableV59Error(f"cannot load bound module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PARENT_V3 = _load_module(PARENT_V3_PATH, "ds02_bound_parent_v3_for_v59")


def _canonical(value: Any) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"} if isinstance(value, Mapping) else value
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False, default=str).encode("utf-8")).hexdigest()


def _sha(path: Path | str, *, max_bytes: int | None = None) -> str:
    target = Path(path).expanduser()
    if max_bytes is not None and target.stat().st_size > max_bytes:
        raise PortableV59Error(f"metadata file exceeds bound: {target}")
    digest = hashlib.sha256()
    with target.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _absolute(value: Any, role: str) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not str(value):
        raise PortableV59Error(f"{role} path is missing")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise PortableV59Error(f"{role} must be absolute: {path}")
    return path.resolve()


def _load_json(path: Path | str, role: str, *, max_bytes: int = MAX_METADATA_BYTES) -> dict[str, Any]:
    target = _absolute(path, role)
    if target.is_symlink() or not target.is_file():
        raise PortableV59Error(f"{role} must be a regular non-symlink file: {target}")
    if target.stat().st_size > max_bytes:
        raise PortableV59Error(f"{role} exceeds metadata bound: {target}")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PortableV59Error(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise PortableV59Error(f"{role} must be a JSON object")
    return value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = _absolute(path, "output")
    if target.exists() or target.is_symlink():
        raise PortableV59Error(f"refusing existing output: {target}")
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
        raise PortableV59Error(f"symlink output component is forbidden: {current}")
    for name in reversed(missing):
        current = current / name
        if current.is_symlink():
            raise PortableV59Error(f"symlink output component is forbidden: {current}")
    if target.exists() and target.is_symlink():
        raise PortableV59Error(f"symlink output path is forbidden: {target}")


def _under(path: Path, root: Path) -> bool:
    path = path.expanduser().resolve()
    root = root.expanduser().resolve()
    return path == root or root in path.parents


def _require_sha(value: Any, role: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch not in HEX64 for ch in value):
        raise PortableV59Error(f"{role} must be a lowercase SHA-256")
    return value


def _cpu_seconds() -> float:
    own = resource.getrusage(resource.RUSAGE_SELF)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    return float(own.ru_utime + own.ru_stime + children.ru_utime + children.ru_stime)


def _stat_binding(path: Path, role: str, *, with_sha: bool = True) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise PortableV59Error(f"{role} must be a regular non-symlink file: {path}")
    value = {"role": role, "path": str(path), "bytes": int(path.stat().st_size),
             "mtime_ns": int(path.stat().st_mtime_ns),
             "mode_bits": stat.S_IMODE(path.stat().st_mode)}
    if with_sha:
        value["sha256"] = _sha(path)
    return value


def _replace_exact(value: Any, replacements: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        return replacements.get(value, value)
    if isinstance(value, list):
        return [_replace_exact(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: _replace_exact(item, replacements) for key, item in value.items()}
    return value


def _raw_tree_manifest(root: Path) -> dict[str, Any]:
    """Same canonical file-list hash as ``ds_data02_f5_bi4.raw_tree_manifest``."""
    if not root.is_dir() or root.is_symlink():
        raise PortableV59Error(f"raw root is not a regular directory: {root}")
    files: list[dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.is_symlink():
            raise PortableV59Error(f"raw tree contains a symlink: {path}")
        files.append({"path": path.relative_to(root).as_posix(),
                      "bytes": int(path.stat().st_size), "sha256": _sha(path)})
    tree = _canonical(files)
    frames = sorted(
        int(path.name[5:-4]) for path in root.glob("Part_*.bi4")
        if path.is_file() and path.name[5:-4].isdigit()
    )
    if not frames or frames != list(range(len(frames))):
        raise PortableV59Error("raw tree does not contain contiguous top-level Part_####.bi4 frames")
    return {"root": str(root), "file_count": len(files), "files": files,
            "frame_count": len(frames), "tree_sha256": tree}


def _old_namespace_stat(root: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for path in sorted(root.iterdir()) if root.is_dir() else []:
        if path.name.startswith("Part_") or path.name in {"PartInfo.ibi4", "PartMotionRef.ibi4"}:
            st = path.stat()
            rows.append({"name": path.name, "bytes": int(st.st_size),
                         "mtime_ns": int(st.st_mtime_ns), "st_dev": int(st.st_dev),
                         "st_ino": int(st.st_ino)})
    return {"root": str(root), "entries": rows}


def _payload_copy_count(*roots: Path) -> int:
    count = 0
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.name.startswith("Part_") or path.suffix.lower() in PAYLOAD_SUFFIXES:
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


def _copy_code(source: Path, target: Path, *, executable: bool = False) -> dict[str, Any]:
    if source.suffix.lower() in PAYLOAD_SUFFIXES or source.name.startswith("Part_"):
        raise PortableV59Error(f"payload copy is forbidden: {source}")
    if source.is_symlink() or not source.is_file() or source.stat().st_size > MAX_METADATA_BYTES:
        raise PortableV59Error(f"code source is not bounded regular file: {source}")
    if executable and not os.access(source, os.X_OK):
        raise PortableV59Error(f"bound executable is not executable: {source}")
    if target.exists() or target.is_symlink():
        raise PortableV59Error(f"refusing existing code target: {target}")
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
        raise PortableV59Error(f"code overlay SHA differs: {source}")
    if executable and not os.access(target, os.X_OK):
        raise PortableV59Error(f"executable mode was not preserved: {target}")
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
            if remaining <= 0 and proc.poll() is None:
                timed_out = True
                cleanup = _kill_owned_group(proc, cleanup_grace)
            events = selector.select(timeout=0.05 if remaining > 0 else 0.01)
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
                old_count = counts[role]
                counts[role] += len(data)
                if old_count < MAX_LOG_BYTES:
                    keep = data[:MAX_LOG_BYTES - old_count]
                    _tail_append(tails[role], 0, keep)
                discarded[role] += max(0, len(data) - max(0, MAX_LOG_BYTES - old_count))
            if proc.poll() is not None and not selector.get_map():
                break
    except BaseException as error:
        cleanup = _kill_owned_group(proc, cleanup_grace)
        setattr(error, "v59_cleanup", cleanup)
        raise
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


def _pinned_path(value: Any, role: str) -> Path:
    path = _absolute(value, role)
    if not path.is_file() or path.is_symlink():
        raise PortableV59Error(f"{role} must be a regular file: {path}")
    return path


def _build_worker_request(v58: Mapping[str, Any], *, raw_root: Path, target: Path,
                          output: Path) -> dict[str, Any]:
    embedded = v58.get("embedded_worker_request")
    if not isinstance(embedded, Mapping):
        raise PortableV59Error("V58 embedded worker request is missing")
    old_target = Path(str(v58.get("fresh_roots", {}).get("target_root", ""))).expanduser()
    old_output = Path(str(v58.get("fresh_roots", {}).get("output_root", ""))).expanduser()
    result = copy.deepcopy(dict(embedded))
    replacements = {str(old_target): str(target), str(old_output): str(output)}
    result = _replace_exact(result, replacements)
    raw = result.get("raw_binding")
    if not isinstance(raw, dict):
        raise PortableV59Error("V58 embedded raw binding is missing")
    raw["data_root"] = str(raw_root)
    frames = raw.get("frames")
    if not isinstance(frames, list) or not frames:
        raise PortableV59Error("V58 embedded frame records are missing")
    for index, item in enumerate(frames):
        if not isinstance(item, dict) or item.get("frame") != index:
            raise PortableV59Error("embedded frame records are not contiguous")
        item["path"] = str(raw_root / f"Part_{index:04d}.bi4")
        item["content_sha256_source"] = "V59_PARENT_AFTER_RESERVATION"
        item["sha256"] = "PENDING_PARENT_GUARD_CONTENT_SHA256"
    recovery = result.get("recovery_binding")
    if isinstance(recovery, dict):
        recovery["new_output_root"] = str(output)
        recovery["raw_copy_forbidden"] = True
        recovery["parent_content_verification"] = "AFTER_ATOMIC_PARENT_RESERVATION"
    result["schema"] = "ds02.stage2.f2-native-raw-to-typed-to-label-request.v2"
    result["status"] = "READY_FOR_PARENT_GUARD"
    result["source_hashes_preverified_by_parent"] = True
    return result


def _make_static_bindings(request: Mapping[str, Any], v58: Mapping[str, Any]) -> list[dict[str, Any]]:
    paths: list[tuple[str, Path]] = [("portable_executor_v59", SCRIPT),
                                     ("parent_executor_v3", PARENT_V3_PATH),
                                     ("shared_v21_accounting", V21_PATH)]
    runtime = _pinned_path(request["runtime_binding"]["path"], "runtime v6")
    paths.append(("shared_runtime_v6", runtime))
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
                raise PortableV59Error(
                    f"overlay source is missing and has no exact ROOT145 runtime alias: {role}: {source}")
            item["source_path_provenance"] = str(source)
            item["source_path"] = str(candidate)
            item["source_path_resolution"] = "ROOT145_RUNTIME_RUNTIME_NATIVE_EXACT_ALIAS"
        else:
            item["source_path_resolution"] = "RECORDED_SOURCE_PATH"
        result.append(item)
    return result


def build_request(*, v58_request: Path | str, output_request: Path | str,
                  target_root: Path | str, output_root: Path | str,
                  ledger: Path | str, external_filesystem: Path | str,
                  home: Path | str = "/home/jade", home_receipt: Path | str,
                  supervisor_root: Path | str | None = None,
                  max_wall_seconds: float = 6000.0,
                  external_bytes: int = 12 * 1024**3,
                  external_min_free_bytes: int = 20 * 1024**3,
                  attempt_id: str | None = None) -> dict[str, Any]:
    v58_path = _pinned_path(v58_request, "V58 request")
    v58 = _load_json(v58_path, "V58 request")
    if v58.get("schema") != "ds02.stage2.f2-root145-copied-recovery-v58.v1":
        raise PortableV59Error("input is not the frozen V58 request")
    if v58.get("sha256") != _canonical(v58):
        raise PortableV59Error("V58 request canonical SHA differs")
    target = _absolute(target_root, "target root")
    output = _absolute(output_root, "output root")
    if target.exists() or output.exists() or target == output or _under(target, output) or _under(output, target):
        raise PortableV59Error("V59 fresh target/output roots must be absent and distinct")
    external = _absolute(external_filesystem, "external filesystem")
    if not external.is_dir() or not _under(target, external) or not _under(output, external):
        raise PortableV59Error("V59 fresh roots must be under external filesystem")
    raw_root = _absolute(v58["reused_immutable_copy"]["bundle_root"], "reused raw root")
    if not raw_root.is_dir() or _under(target, raw_root) or _under(output, raw_root):
        raise PortableV59Error("reused raw root is invalid")
    embedded = _build_worker_request(v58, raw_root=raw_root, target=target, output=output)
    raw = embedded.get("raw_binding")
    if not isinstance(raw, Mapping):
        raise PortableV59Error("rebased V2 raw binding is missing")
    frames = raw.get("frames")
    if not isinstance(frames, list) or not frames:
        raise PortableV59Error("rebased V2 frame list is missing")
    attempt = str(attempt_id or "f2-s1-root145-v59-parent-recovery-20261009-001")
    receipt = _absolute(home_receipt, "Home receipt")
    if receipt.exists():
        raise PortableV59Error("Home receipt already exists")
    supervisor = _absolute(supervisor_root or output.parent / "supervisor", "supervisor root")
    if supervisor.exists() or not _under(supervisor, external):
        raise PortableV59Error("supervisor root must be a fresh external child")
    runtime_value = v58.get("runtime", {})
    bindings = {
        "code_overlay_bindings": _rebind_overlay_sources(
            copy.deepcopy(runtime_value.get("code_overlay_bindings", [])), raw_root),
        "worker_target": str(target / "runtime/native/ds_data02_stage2_f2_native_raw_to_typed_label_v2.py"),
        "worker_request_target": str(target / "runtime/native/f2-s1-v59-worker-request.json"),
        "pinned_python": PINNED_PYTHON,
    }
    old_target = str(v58.get("fresh_roots", {}).get("target_root", ""))
    old_output = str(v58.get("fresh_roots", {}).get("output_root", ""))
    bindings = _replace_exact(bindings, {old_target: str(target), old_output: str(output)})
    for item in bindings["code_overlay_bindings"]:
        if isinstance(item, Mapping):
            item["target_path"] = str(item.get("target_path", "")).replace(old_target, str(target))
    command = [PINNED_PYTHON, "-B", "-I", bindings["worker_target"], "run", "--request",
               bindings["worker_request_target"], "--output-dir", str(output),
               "--io-slot-approved", "--run-labels"]
    ledger_path = _pinned_path(ledger, "parent ledger")
    ledger_value = _load_json(ledger_path, "parent ledger")
    limits = ledger_value.get("limits", {})
    home_path = _absolute(home, "Home filesystem")
    if not home_path.is_dir():
        raise PortableV59Error("Home filesystem is missing")
    home_floor = int(limits.get("home_min_free_bytes", 0) or 0)
    if int(limits.get("home_min_free_bytes", 0) or 0) != home_floor:
        raise PortableV59Error("invalid live Home floor")
    if max_wall_seconds <= 0 or not math.isfinite(float(max_wall_seconds)):
        raise PortableV59Error("max wall must be finite and positive")
    if int(external_bytes) <= 0 or int(external_min_free_bytes) < 0:
        raise PortableV59Error("external reservation is invalid")
    runtime_path = _pinned_path(RUNTIME_V6_DEFAULT, "shared runtime v6")
    request: dict[str, Any] = {
        "schema": SCHEMA, "status": "READY_FOR_PARENT_GUARD", "role": "DEVELOPMENT",
        "family_id": "F2", "case_id": v58.get("case_id"), "request_id": attempt,
        "attempt_id": attempt, "worktree_root": str(SCRIPT_DIR.parent.parent),
        "parent_adapter": {"schema": "ds02.stage2.f2-portable-executor-parent-request.v3",
                            "implementation": str(PARENT_V3_PATH),
                            "apis": ["_reserve", "_charge", "_release", "ledger_locked"],
                            "same_parent_ledger": True},
        "v58_provenance": {"path": str(v58_path), "sha256": _sha(v58_path),
                           "schema": v58.get("schema"), "immutable": True},
        "raw_source": {
            "root": str(raw_root), "tree_sha256": str(v58["reused_immutable_copy"].get("raw_tree_sha256", "")),
            "file_count": int(v58["reused_immutable_copy"].get("raw_tree_file_count", 0)),
            "frame_count": len(frames), "copy_forbidden": True,
            "verification_phase": "AFTER_ATOMIC_PARENT_RESERVATION_BEFORE_WORKER",
            "prepost_required": True, "frames": [
                {"frame": int(item["frame"]), "path": str(item["path"]),
                 "bytes": int(item.get("bytes", -1)),
                 "sha256": item.get("sha256") if item.get("sha256") not in {None, "PENDING_PARENT_GUARD_CONTENT_SHA256"} else None}
                for item in frames if isinstance(item, Mapping)
            ]},
        "runtime": {"pinned_python": PINNED_PYTHON,
                    "worker_target": bindings["worker_target"],
                    "worker_request_target": bindings["worker_request_target"],
                    "code_overlay_bindings": bindings["code_overlay_bindings"],
                    "raw_copy_forbidden": True,
                    "scratch": {"attempt_owned": True, "default_tmp_forbidden": True,
                                 "max_frame_bytes": 512 * 1024**2, "timeout_seconds": 180}},
        "embedded_worker_request": embedded,
        "execution": {"command": command, "python": PINNED_PYTHON,
                       "max_wall_seconds": float(max_wall_seconds),
                       "cpu_reservation_seconds": float(max_wall_seconds),
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
                            "role": "shared_runtime_v6", "immutable": True},
        "storage_scope": {
            "external_filesystem": str(external), "external_output_root": str(output),
            "supervisor_output_root": str(supervisor), "home_receipt_path": str(receipt),
            "home_receipt_bytes": 64 * 1024, "external_reservation_bytes": int(external_bytes),
            "source_copy_bytes": 0, "reused_source_copy_bytes_not_recharged": True,
            "external_min_free_bytes": int(external_min_free_bytes),
            "home_min_free_bytes": home_floor, "two_filesystem_charge_required": True,
            "new_namespace_absent_before_run": True},
        "static_bindings": [],
        "model_invoked": False, "cfd_invoked": False, "raw_opened": False,
        "hdf5_opened": False, "fresh_cold_credit": False, "qualification": dict(UNKNOWN),
        "limitations": [
            "Development recovery over an immutable copied raw root; no fresh-cold credit.",
            "Parent-v3 reserve/charge are the only ledger mutations; no nested ledger owner.",
            "Raw content is read only after reservation and is verified before and after the child.",
            "Private interpreter environment remains an explicit bound external dependency; source fallback is forbidden.",
        ],
    }
    request["static_bindings"] = _make_static_bindings(request, v58)
    request["sha256"] = _canonical(request)
    out = _write_new(output_request, request)
    return {"schema": SCHEMA, "status": request["status"], "request": str(out),
            "request_sha256": _sha(out), "payload_read": False,
            "raw_copy_bytes": 0, "fresh_cold_credit": False, "qualification": dict(UNKNOWN)}


def _validate_request(path: Path, *, verify_static: bool = False) -> dict[str, Any]:
    request = _load_json(path, "V59 parent request")
    if request.get("schema") != SCHEMA or request.get("status") != "READY_FOR_PARENT_GUARD":
        raise PortableV59Error("unsupported or non-ready V59 parent request")
    if request.get("sha256") != _canonical(request):
        raise PortableV59Error("V59 request canonical SHA differs")
    if request.get("role") != "DEVELOPMENT" or request.get("qualification") != UNKNOWN:
        raise PortableV59Error("V59 must remain DEVELOPMENT/UNKNOWN")
    if request.get("model_invoked") is not False or request.get("cfd_invoked") is not False:
        raise PortableV59Error("V59 model/CFD invocation is forbidden")
    parent = request.get("parent_resource_binding")
    storage = request.get("storage_scope")
    execution = request.get("execution")
    runtime_binding = request.get("runtime_binding")
    if not all(isinstance(value, Mapping) for value in (parent, storage, execution, runtime_binding)):
        raise PortableV59Error("V59 parent/storage/execution binding is incomplete")
    ledger = _pinned_path(parent.get("ledger_path"), "parent ledger")
    external = _absolute(storage.get("external_filesystem"), "external filesystem")
    if not external.is_dir():
        raise PortableV59Error("external filesystem is missing")
    output = _absolute(storage.get("external_output_root"), "external output root")
    supervisor = _absolute(storage.get("supervisor_output_root"), "supervisor root")
    receipt = _absolute(storage.get("home_receipt_path"), "Home receipt")
    for item, name in ((output, "output"), (supervisor, "supervisor")):
        if item.exists() or not _under(item, external):
            raise PortableV59Error(f"{name} must be a fresh child of external filesystem")
        _no_symlink_components(item)
    if receipt.exists():
        raise PortableV59Error("Home receipt already exists")
    raw = request.get("raw_source")
    if not isinstance(raw, Mapping):
        raise PortableV59Error("raw_source is missing")
    raw_root = _absolute(raw.get("root"), "reused raw root")
    if not raw_root.is_dir() or raw_root == output or _under(output, raw_root):
        raise PortableV59Error("reused raw root/output relationship is invalid")
    expected_tree = _require_sha(raw.get("tree_sha256"), "raw_source.tree_sha256")
    frames = raw.get("frames")
    if not isinstance(frames, list) or int(raw.get("frame_count", 0)) != len(frames) or not frames:
        raise PortableV59Error("raw_source frame contract is incomplete")
    for index, item in enumerate(frames):
        if not isinstance(item, Mapping) or int(item.get("frame", -1)) != index:
            raise PortableV59Error("raw frames are not contiguous")
        frame_path = _absolute(item.get("path"), f"raw frame {index}")
        if frame_path != raw_root / f"Part_{index:04d}.bi4" or not frame_path.is_file() or frame_path.is_symlink():
            raise PortableV59Error(f"raw frame {index} is not the exact top-level Part path")
        if int(item.get("bytes", -1)) != frame_path.stat().st_size:
            raise PortableV59Error(f"raw frame {index} byte stat differs")
        if item.get("sha256") is not None:
            _require_sha(item.get("sha256"), f"raw frame {index} SHA")
    runtime = request.get("runtime")
    if not isinstance(runtime, Mapping):
        raise PortableV59Error("runtime binding is missing")
    worker_target = _absolute(runtime.get("worker_target"), "worker target")
    worker_request_target = _absolute(runtime.get("worker_request_target"), "worker request target")
    if not _under(worker_target, output.parent) or worker_target.suffix != ".py":
        raise PortableV59Error("worker target is outside fresh target namespace")
    if worker_request_target.exists():
        raise PortableV59Error("worker request target must be fresh")
    command = execution.get("command")
    if not isinstance(command, list) or not all(isinstance(item, str) for item in command):
        raise PortableV59Error("worker command is malformed")
    if not command or command[0] != str(_absolute(execution.get("python"), "pinned Python")):
        # A literal venv path is required.  _absolute does not resolve the symlink
        # in the value used for argv[0] because this is only a string comparison.
        if not command or command[0] != str(execution.get("python")):
            raise PortableV59Error("worker command does not preserve literal interpreter path")
    max_wall = float(execution.get("max_wall_seconds", 0.0) or 0.0)
    if not math.isfinite(max_wall) or max_wall <= 0:
        raise PortableV59Error("max wall is invalid")
    if abs(float(execution.get("cpu_reservation_seconds", -1.0)) - max_wall) > 1e-9:
        raise PortableV59Error("CPU reservation must equal max wall")
    if float(execution.get("child_cleanup_grace_seconds", 0.0)) < 20.0:
        raise PortableV59Error("cleanup grace must be at least 20 seconds")
    if int(execution.get("bounded_log_bytes_per_stream", 0)) <= 0:
        raise PortableV59Error("bounded log limit is missing")
    runtime_path = _pinned_path(runtime_binding.get("path"), "shared runtime v6")
    runtime_sha = _require_sha(runtime_binding.get("sha256"), "shared runtime SHA")
    static = request.get("static_bindings")
    if not isinstance(static, list) or not static:
        raise PortableV59Error("static source closure is missing")
    for item in static:
        if not isinstance(item, Mapping):
            raise PortableV59Error("static binding is malformed")
        source = _pinned_path(item.get("path"), str(item.get("role", "static")))
        if int(item.get("bytes", -1)) != source.stat().st_size:
            raise PortableV59Error(f"static byte stat differs: {source}")
        if verify_static and _sha(source) != _require_sha(item.get("sha256"), "static binding SHA"):
            raise PortableV59Error(f"static source SHA differs: {source}")
    if runtime_path.stat().st_size <= 0:
        raise PortableV59Error("runtime is empty")
    limits = _load_json(ledger, "parent ledger").get("limits", {})
    if str(parent.get("storage_policy")) != str(limits.get("storage_policy")):
        raise PortableV59Error("storage policy differs from live ledger")
    if int(parent.get("home_min_free_bytes", -1)) != int(limits.get("home_min_free_bytes", -2)):
        raise PortableV59Error("Home floor differs from live ledger")
    return {"path": path, "request": request, "ledger": ledger, "external": external,
            "output": output, "supervisor": supervisor, "receipt": receipt,
            "raw_root": raw_root, "expected_tree": expected_tree, "frames": frames,
            "runtime_path": runtime_path, "runtime_sha": runtime_sha,
            "worker_target": worker_target, "worker_request_target": worker_request_target,
            "max_wall": max_wall, "cleanup_grace": float(execution["child_cleanup_grace_seconds"]),
            "external_estimate": int(storage["external_reservation_bytes"]),
            "home_estimate": int(storage["home_receipt_bytes"]),
            "limits": limits, "parent_attempt_id": str(parent["attempt_id"]),
            "reservation_id": str(parent["reservation_id"]), "charge_id": str(parent["charge_id"]),
            "allow_missing_parent": bool(parent.get("allow_missing_parent", False))}


def _fill_worker_request(bound: Mapping[str, Any], target: Path, output: Path,
                         observed: Mapping[str, Any]) -> dict[str, Any]:
    request = copy.deepcopy(dict(bound["request"]["embedded_worker_request"]))
    raw = request.get("raw_binding")
    if not isinstance(raw, dict):
        raise PortableV59Error("embedded worker raw binding is missing")
    raw["data_root"] = str(bound["raw_root"])
    files = {str(bound["raw_root"] / str(item["path"])): item for item in observed["files"]}
    for item in raw.get("frames", []):
        path = str(item.get("path"))
        if path not in files:
            raise PortableV59Error(f"observed frame is absent from raw manifest: {path}")
        item["sha256"] = files[path]["sha256"]
        item["bytes"] = files[path]["bytes"]
        item["content_sha256_source"] = "V59_PARENT_OBSERVED_AFTER_RESERVATION"
    binding = request.get("recovery_binding")
    if isinstance(binding, dict):
        binding["new_output_root"] = str(output)
        binding["raw_tree_before_sha256"] = observed["tree_sha256"]
        binding["raw_copy_forbidden"] = True
    return request


def _run_child(bound: Mapping[str, Any], worker_request: Path, *, parent_pid: int) -> dict[str, Any]:
    execution = bound["request"]["execution"]
    command = [str(execution["python"]), "-B", "-I", str(bound["worker_target"]), "run",
               "--request", str(worker_request), "--output-dir", str(bound["output"]),
               "--io-slot-approved", "--run-labels"]
    env = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "PYTHONHOME"}}
    env.update({str(key): str(value) for key, value in execution.get("env", THREAD_ENV).items()})
    return _run_bounded(command, cwd=bound["worker_target"].parent, env=env,
                        timeout=bound["max_wall"], cleanup_grace=bound["cleanup_grace"],
                        parent_pid=parent_pid) | {"command": command}


def run(request_path: Path | str, *, io_slot_approved: bool,
        parent_pid: int | None = None) -> dict[str, Any]:
    entry_wall = time.monotonic()
    entry_cpu = _cpu_seconds()
    path = _absolute(request_path, "V59 request")
    raw_request = _load_json(path, "V59 request")
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
        raise PortableV59Error("actual V59 run requires its direct parent PID")
    if max_wall <= 0:
        raise PortableV59Error("max wall is missing")
    bound = _validate_request(path, verify_static=False)
    if abs(bound["max_wall"] - max_wall) > 1e-9:
        raise PortableV59Error("max wall changed during validation")
    PARENT_V3._pdeath(int(parent_pid))
    previous_signals = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGALRM)}
    previous_timer = signal.setitimer(signal.ITIMER_REAL, 0.0)

    def _interrupt(signum: int, _frame: Any) -> None:
        label = signal.Signals(signum).name
        raise PortableV59Error(f"V59 parent received {label}; owned worker cleanup required")

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
    observed_worker: dict[str, Any] | None = None
    code_rows: list[dict[str, Any]] = []
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
                raise PortableV59Error("malformed code overlay binding")
            source = _pinned_path(item.get("source_path"), str(item.get("role", "overlay")))
            destination = _absolute(item.get("target_path"), str(item.get("role", "overlay target")))
            if not _under(destination, target):
                raise PortableV59Error("code target escapes fresh target")
            code_rows.append(_copy_code(source, destination, executable=bool(item.get("required_executable"))))
        before = _raw_tree_manifest(bound["raw_root"])
        if before["tree_sha256"] != bound["expected_tree"]:
            raise PortableV59Error("raw source tree SHA differs from source-bound producer tree")
        worker_request = bound["worker_request_target"]
        worker_request.parent.mkdir(parents=True, exist_ok=True)
        worker_value = _fill_worker_request(bound, target, bound["output"], before)
        _write_new(worker_request, worker_value)
        child = _run_child(bound, worker_request, parent_pid=os.getpid())
        child_result = _extract_worker_result(str(child.get("stdout_tail", "")))
        if child.get("timed_out"):
            raise PortableV59Error("strict recovery worker exceeded parent deadline")
        if int(child.get("returncode", -1)) != 0:
            raise PortableV59Error(f"strict recovery worker returned {child.get('returncode')}: {child.get('stderr_tail', '')[-1200:]}")
        if not isinstance(child_result, Mapping) or str(child_result.get("status", "")).startswith("FAILED"):
            raise PortableV59Error("strict recovery worker did not report a successful status")
        after = _raw_tree_manifest(bound["raw_root"])
        if after["tree_sha256"] != before["tree_sha256"] or after["files"] != before["files"]:
            raise PortableV59Error("raw source tree changed during worker")
        worker_raw = child_result.get("raw_tree_before_sha256")
        if worker_raw is not None and worker_raw != before["tree_sha256"]:
            raise PortableV59Error("worker raw pre-tree SHA differs")
        worker_after = child_result.get("raw_tree_after_sha256")
        if worker_after is not None and worker_after != after["tree_sha256"]:
            raise PortableV59Error("worker raw post-tree SHA differs")
        status = "COMPLETED_PARENT_EXECUTOR_RAW_TYPED_LABEL_UNKNOWN"
    except BaseException as exc:
        error = f"{type(exc).__name__}: {exc}"
        status = "FAILED_PARENT_EXECUTOR"
        cleanup_from_error = getattr(exc, "v59_cleanup", None)
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
        if before is None and reservation_applied:
            try:
                before = _raw_tree_manifest(bound["raw_root"])
            except BaseException:
                before = None
        if after is None and reservation_applied:
            try:
                after = _raw_tree_manifest(bound["raw_root"])
            except BaseException:
                after = None
        signal.setitimer(signal.ITIMER_REAL, 0.0)
        for sig, previous in previous_signals.items():
            signal.signal(sig, previous)
        if previous_timer[0] > 0:
            signal.setitimer(signal.ITIMER_REAL, previous_timer[0], previous_timer[1])
    try:
        external_bytes = _new_namespace_bytes(bound)
        target_root = Path(bound["worker_target"]).parents[2]
        raw_copy_attempts = _payload_copy_count(target_root, bound["output"], bound["supervisor"])
        if isinstance(child_result, Mapping):
            try:
                raw_copy_attempts += max(0, int(child_result.get("raw_copy_attempts", 0) or 0))
            except (TypeError, ValueError):
                raise PortableV59Error("worker raw_copy_attempts is not an integer")
        if raw_copy_attempts:
            status = "FAILED_PARENT_EXECUTOR"
            error = error or "raw payload copy/attempt observed in new namespace"
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
                           "before": before, "after": after, "full_prepost_equal": bool(before and after and before["files"] == after["files"])},
            "copy_contract": {"raw_copy_attempts": raw_copy_attempts, "raw_source_copy_bytes": 0,
                              "new_code_overlay": code_rows, "old_namespace_write": "FORBIDDEN"},
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
                            "external_bytes": external_bytes, "home_receipt_path": str(bound["receipt"]),
                            "storage_filesystems": [str(bound["external"]), str(bound["limits"].get("home_path", "/home/jade"))]},
            "accounting": {"reservation_id": bound["reservation_id"], "charge_id": bound["charge_id"],
                           "reservation_applied": reservation_applied,
                           "charge_status_at_report_write": "pending_same_parent_charge",
                           "allow_missing_parent": bound["allow_missing_parent"]},
            "raw_opened": before is not None, "hdf5_opened": bool(child_result and child_result.get("hdf5_opened", False)),
            "model_invoked": False, "cfd_invoked": False,
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
                                   cpu_seconds=cpu, external_bytes=external_bytes, home_bytes=home_bytes,
                                   trace_bytes=0, copy_hash_bytes=sum(int(item.get("bytes", 0)) for item in code_rows),
                                   allow_missing_parent=bound["allow_missing_parent"])
        return {"schema": REPORT_SCHEMA, "status": status, "report_path": str(bound["receipt"]),
                "request_sha256": _sha(path), "ledger_mutated": bool(charge.get("ledger_mutated")),
                "charge": charge, "external_bytes": external_bytes, "home_bytes": home_bytes,
                "raw_copy_attempts": raw_copy_attempts, "raw_opened": before is not None,
                "hdf5_opened": bool(child_result and child_result.get("hdf5_opened", False)),
                "fresh_cold_credit": False, "qualification": dict(UNKNOWN)}
    except BaseException as final_error:
        if reservation_applied:
            try:
                external_bytes = _new_namespace_bytes(bound)
                PARENT_V3._charge({"runtime_path": bound["runtime_path"], "runtime_sha": bound["runtime_sha"],
                                   "ledger": bound["ledger"], "external": bound["external"],
                                   "limits": bound["limits"], "request": bound["request"],
                                   "reservation_id": bound["reservation_id"], "charge_id": bound["charge_id"],
                                   "parent_attempt_id": bound["parent_attempt_id"]},
                                  status="failed", cpu_seconds=max(0.0, _cpu_seconds() - entry_cpu),
                                  external_bytes=external_bytes,
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
                "fresh_cold_credit": False, "qualification": dict(UNKNOWN)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-request")
    build.add_argument("--v58-request", type=Path, required=True)
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
    preflight = sub.add_parser("preflight")
    preflight.add_argument("--request", type=Path, required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--request", type=Path, required=True)
    run_parser.add_argument("--io-slot-approved", action="store_true")
    run_parser.add_argument("--parent-pid", type=int)
    args = parser.parse_args(argv)
    try:
        if args.command == "build-request":
            result = build_request(v58_request=args.v58_request, output_request=args.output_request,
                                   target_root=args.target_root, output_root=args.output_root,
                                   ledger=args.ledger, external_filesystem=args.external_filesystem,
                                   home=args.home, home_receipt=args.home_receipt,
                                   supervisor_root=args.supervisor_root,
                                   max_wall_seconds=args.max_wall_seconds,
                                   external_bytes=args.external_bytes,
                                   external_min_free_bytes=args.external_min_free_bytes,
                                   attempt_id=args.attempt_id)
        elif args.command == "preflight":
            path = _absolute(args.request, "V59 request")
            result = _validate_request(path, verify_static=False)
            result = {"schema": REPORT_SCHEMA, "status": "READY_FOR_PARENT_IO_SLOT",
                      "request": str(path), "metadata_only": True, "payload_read": False}
        else:
            result = run(args.request, io_slot_approved=args.io_slot_approved,
                         parent_pid=args.parent_pid)
    except (PortableV59Error, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"f2 portable executor v59: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=True, default=str))
    return 1 if str(result.get("status", "")).startswith("FAILED") else 0


if __name__ == "__main__":
    raise SystemExit(main())
