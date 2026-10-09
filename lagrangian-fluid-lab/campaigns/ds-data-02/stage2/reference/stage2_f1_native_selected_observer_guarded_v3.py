#!/usr/bin/env python3
"""Guard the deferred native inputs before invoking the immutable V1 worker.

The generic v8 runtime validates and hashes ``input_files`` only.  Its
``deferred_input_records`` field is metadata, so this wrapper is the actual
source guard for the 25 selected ``Part_*.bi4`` files.  It performs, in this
order:

* a full SHA/stat pass over every declared deferred Part before the decoder;
* the unchanged V1 worker (which performs one decoder input read and its own
  ``sha256_file`` pass);
* a second full SHA/stat pass and exact identity/stat comparison after the
  worker;
* bounded child logging, parent-death/cancellation handling, and a 256 MiB
  scratch-tree cap with cleanup.

The wrapper creates an ephemeral V1-compatible manifest in the reserved
attempt directory.  It never edits the consumed V1 or V2 manifests.  The
four-pass accounting is therefore explicit: wrapper pre-hash, decoder input,
V1 worker hash, wrapper post-hash.  The v8 parent still does not hash deferred
inputs; only this child wrapper does so after the parent reservation.

``--self-test`` uses only temporary manufactured source and decoder fixtures.
It does not open, stat, or hash a production native file.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any, Iterable


SCHEMA = "ds02.stage2.f1.native-selected-observer-guarded-wrapper.v3"
V2_MANIFEST_SCHEMA = "ds02.stage2.f1.native-selected-observer-manifest.v2"
V1_MANIFEST_SCHEMA = "ds02.stage2.f1.native-selected-observer-manifest.v1"
V1_WORKER = Path(
    "/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/"
    "stage2_f1_native_selected_observer_v1.py"
)
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
CHUNK = 1024 * 1024
EXPECTED_DEFERRED_COUNT = 25
SCRATCH_CAP_BYTES = 256 * 1024 * 1024
DEFAULT_MAX_LOG_BYTES = 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 1800.0
MAX_CHILD_RESULT_BYTES = 64 * 1024 * 1024


class GuardFailure(RuntimeError):
    """A source, child, scratch, or cancellation condition that blocks credit."""


def _json_load(path: Path, *, maximum: int = 16 * 1024 * 1024) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise GuardFailure(f"JSON source is not a regular file: {path}")
    if path.stat().st_size > maximum:
        raise GuardFailure(f"JSON source exceeds bounded read limit: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GuardFailure(f"cannot read JSON source {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise GuardFailure(f"JSON source is not an object: {path}")
    return value


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise GuardFailure(f"refusing to overwrite wrapper output: {path}")
    payload = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _regular(path: Path, label: str) -> os.stat_result:
    try:
        value = path.lstat()
    except OSError as exc:
        raise GuardFailure(f"{label} cannot be stat'ed: {path}: {exc}") from exc
    if stat.S_ISLNK(value.st_mode) or not stat.S_ISREG(value.st_mode):
        raise GuardFailure(f"{label} is not a regular non-symlink file: {path}")
    return value


def _stat_record(path: Path, label: str) -> dict[str, int]:
    value = _regular(path, label)
    return {
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
        "device": int(value.st_dev),
        "inode": int(value.st_ino),
    }


def _sha_and_stat(path: Path, label: str) -> tuple[str, dict[str, int]]:
    """Read one native source pass, rejecting replacement during the pass."""

    before = _stat_record(path, label)
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(CHUNK), b""):
                digest.update(block)
                size += len(block)
    except OSError as exc:
        raise GuardFailure(f"{label} cannot be read: {path}: {exc}") from exc
    after = _stat_record(path, label)
    if before != after or size != before["bytes"]:
        raise GuardFailure(f"{label} changed during guarded SHA pass: {path}")
    return digest.hexdigest(), after


def _expected_stat(record: dict[str, Any]) -> dict[str, int]:
    candidate = record.get("stat_at_prepare")
    if not isinstance(candidate, dict):
        candidate = record
    fields: dict[str, int] = {}
    for key in ("bytes", "mtime_ns", "ctime_ns", "device", "inode"):
        if key in candidate:
            try:
                fields[key] = int(candidate[key])
            except (TypeError, ValueError) as exc:
                raise GuardFailure(f"deferred record has non-integer {key}") from exc
    if "bytes" not in fields or "mtime_ns" not in fields:
        raise GuardFailure("deferred record lacks known bytes/mtime_ns")
    return fields


def _expected_sha(record: dict[str, Any], path: Path) -> str:
    value = record.get("known_sha256", record.get("sha256"))
    if not isinstance(value, str) or len(value) != 64:
        raise GuardFailure(f"deferred record has unknown/invalid SHA: {path}")
    try:
        int(value, 16)
    except ValueError as exc:
        raise GuardFailure(f"deferred record has non-hex SHA: {path}") from exc
    return value.lower()


def _record_path(record: Any, label: str) -> Path:
    if not isinstance(record, dict) or not isinstance(record.get("path"), str):
        raise GuardFailure(f"{label} has no path")
    path = Path(record["path"]).expanduser().resolve()
    if path.suffix.lower() != ".bi4":
        raise GuardFailure(f"{label} is not a BI4 Part file: {path}")
    return path


def _load_deferred(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    if manifest.get("schema") != V2_MANIFEST_SCHEMA:
        raise GuardFailure(f"wrapper requires V2 manifest, got {manifest.get('schema')!r}")
    records = manifest.get("native_deferred_records")
    if not isinstance(records, dict) or len(records) != EXPECTED_DEFERRED_COUNT:
        raise GuardFailure("V2 manifest does not contain exactly 25 deferred records")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_key, raw_record in records.items():
        if not isinstance(raw_record, dict):
            raise GuardFailure(f"deferred record {raw_key!r} is not an object")
        path = _record_path(raw_record, f"deferred record {raw_key!r}")
        if str(path) in seen or str(path) != str(Path(str(raw_key)).expanduser().resolve()):
            raise GuardFailure(f"deferred record key/path mismatch: {raw_key!r} vs {path}")
        seen.add(str(path))
        result.append({"path": path, "record": raw_record})
    result.sort(key=lambda item: (str(item["path"]), int(item["record"].get("frame", -1))))
    return result


def _validate_expected(path: Path, record: dict[str, Any], sha: str, stat_value: dict[str, int]) -> None:
    expected_sha = _expected_sha(record, path)
    if sha != expected_sha:
        raise GuardFailure(f"known SHA mismatch before/after child: {path}")
    expected = _expected_stat(record)
    for key, value in expected.items():
        if stat_value[key] != value:
            raise GuardFailure(f"known {key} mismatch for deferred source: {path}")


def _precheck(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    checked: list[dict[str, Any]] = []
    for item in records:
        path = item["path"]
        record = item["record"]
        sha, stat_value = _sha_and_stat(path, f"deferred precheck {path}")
        _validate_expected(path, record, sha, stat_value)
        checked.append({"path": str(path), "sha256": sha, "stat": stat_value, "frame": int(record.get("frame", -1))})
    return checked


def _postcheck(records: list[dict[str, Any]], before: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(records) != len(before):
        raise GuardFailure("deferred record count changed between pre/post checks")
    checked: list[dict[str, Any]] = []
    for item, prior in zip(records, before):
        path = item["path"]
        record = item["record"]
        sha, stat_value = _sha_and_stat(path, f"deferred postcheck {path}")
        _validate_expected(path, record, sha, stat_value)
        if sha != prior["sha256"] or stat_value != prior["stat"]:
            raise GuardFailure(f"deferred source changed during child: {path}")
        checked.append({"path": str(path), "sha256": sha, "stat": stat_value, "frame": int(record.get("frame", -1))})
    return checked


def _under(root: Path, path: Path, label: str) -> Path:
    root = root.resolve()
    path = path.expanduser().resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise GuardFailure(f"{label} escapes attempt root: {path}") from exc
    return path


def _scratch_roots(manifest: dict[str, Any], attempt_root: Path) -> list[Path]:
    roots: list[Path] = []
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        raise GuardFailure("V2 manifest has no cases for scratch binding")
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("scratch_root"), str):
            raise GuardFailure("V2 case lacks scratch_root")
        raw = case["scratch_root"].replace("{attempt_root}", str(attempt_root.resolve()), 1)
        root = _under(attempt_root, Path(raw), "scratch root")
        if root == attempt_root:
            raise GuardFailure("scratch root may not be the attempt root itself")
        if root.is_symlink():
            raise GuardFailure(f"scratch root is symlinked: {root}")
        root.mkdir(parents=True, exist_ok=True)
        roots.append(root)
    return sorted(set(roots), key=str)


def _tree_bytes(roots: Iterable[Path]) -> int:
    total = 0
    for root in roots:
        if root.is_symlink():
            raise GuardFailure(f"scratch root became symlinked: {root}")
        if not root.exists():
            continue
        for current, directories, files in os.walk(root, followlinks=False):
            current_path = Path(current)
            for directory in directories:
                if (current_path / directory).is_symlink():
                    raise GuardFailure(f"scratch contains symlink directory: {current_path / directory}")
            for name in files:
                path = current_path / name
                if path.is_symlink():
                    raise GuardFailure(f"scratch contains symlink file: {path}")
                try:
                    total += int(path.stat().st_size)
                except OSError as exc:
                    raise GuardFailure(f"cannot stat scratch file: {path}: {exc}") from exc
    return total


def _cleanup_scratch(roots: Iterable[Path]) -> tuple[bool, str | None]:
    try:
        for root in roots:
            if root.is_symlink():
                root.unlink()
            elif root.exists():
                shutil.rmtree(root)
        return True, None
    except OSError as exc:
        return False, str(exc)


class _BoundedLog:
    def __init__(self, limit: int) -> None:
        self.limit = int(limit)
        self.total = 0
        self.tail = bytearray()

    def add(self, chunk: bytes) -> None:
        self.total += len(chunk)
        if self.limit <= 0:
            return
        self.tail.extend(chunk)
        if len(self.tail) > self.limit:
            del self.tail[: len(self.tail) - self.limit]

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() or path.is_symlink():
            raise GuardFailure(f"refusing to overwrite child log: {path}")
        path.write_bytes(bytes(self.tail))


def _stop_group(process: subprocess.Popen[bytes], *, grace: float = 1.0) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=grace)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=grace)
    except subprocess.TimeoutExpired as exc:
        raise GuardFailure("child process group did not terminate after SIGKILL") from exc


def _run_child(
    command: list[str],
    *,
    cwd: Path,
    scratch_roots: list[Path],
    scratch_cap_bytes: int,
    log_limit: int,
    timeout_seconds: float,
    parent_pid: int | None = None,
) -> dict[str, Any]:
    """Run V1 in a new process group while continuously draining its log pipe."""

    if not command:
        raise GuardFailure("empty child command")
    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        bufsize=0,
    )
    bounded = _BoundedLog(log_limit)
    selector = selectors.DefaultSelector()
    assert process.stdout is not None
    selector.register(process.stdout, selectors.EVENT_READ)
    started = time.monotonic()
    original_parent = os.getppid() if parent_pid is None else int(parent_pid)
    cancellation: str | None = None
    signal_seen: list[int] = []

    def request_stop(signum: int, _frame: Any) -> None:
        signal_seen.append(int(signum))

    old_term = signal.signal(signal.SIGTERM, request_stop)
    old_int = signal.signal(signal.SIGINT, request_stop)
    try:
        while True:
            if signal_seen:
                cancellation = f"signal_{signal_seen[-1]}"
            elif os.getppid() != original_parent:
                cancellation = "parent_died"
            elif time.monotonic() - started > timeout_seconds:
                cancellation = "child_timeout"
            try:
                current_scratch = _tree_bytes(scratch_roots)
            except GuardFailure:
                cancellation = "scratch_invalid"
                current_scratch = SCRATCH_CAP_BYTES + 1
            if current_scratch > scratch_cap_bytes:
                cancellation = "scratch_cap_exceeded"
            if cancellation and process.poll() is None:
                _stop_group(process)
            events = selector.select(0.05)
            for key, _ in events:
                try:
                    chunk = os.read(key.fileobj.fileno(), 65536)
                except OSError:
                    chunk = b""
                if chunk:
                    bounded.add(chunk)
                else:
                    try:
                        selector.unregister(key.fileobj)
                    except Exception:
                        pass
            if process.poll() is not None and not selector.get_map():
                break
            if process.poll() is not None and selector.get_map():
                # Drain EOF without waiting for another polling interval.
                for key in list(selector.get_map().values()):
                    try:
                        chunk = os.read(key.fileobj.fileno(), 65536)
                    except OSError:
                        chunk = b""
                    if chunk:
                        bounded.add(chunk)
                    else:
                        try:
                            selector.unregister(key.fileobj)
                        except Exception:
                            pass
        # A very short child can create and close a scratch file between the
        # last poll and process exit.  Perform one final bounded-tree check so
        # that such a child cannot evade the cap merely by exiting quickly.
        final_scratch = _tree_bytes(scratch_roots)
        if final_scratch > scratch_cap_bytes and cancellation is None:
            cancellation = "scratch_cap_exceeded"
        return {
            "returncode": int(process.returncode if process.returncode is not None else -1),
            "elapsed_seconds": time.monotonic() - started,
            "cancellation": cancellation,
            "log_total_bytes": bounded.total,
            "log_retained_bytes": len(bounded.tail),
            "log_truncated": bounded.total > len(bounded.tail),
            "log_tail": bytes(bounded.tail),
        }
    finally:
        try:
            selector.close()
        finally:
            signal.signal(signal.SIGTERM, old_term)
            signal.signal(signal.SIGINT, old_int)


def _make_v1_manifest(v2: dict[str, Any], attempt_root: Path) -> Path:
    value = copy.deepcopy(v2)
    value["schema"] = V1_MANIFEST_SCHEMA
    for key in (
        "native_deferred_records",
        "native_deferred_policy",
        "native_read_accounting",
        "scratch_policy",
        "memory_policy",
        "preparation_scope",
    ):
        value.pop(key, None)
    cases = value.get("cases")
    if not isinstance(cases, list) or not cases:
        raise GuardFailure("V2 manifest has no cases for V1 adapter")
    for case in cases:
        if not isinstance(case, dict):
            raise GuardFailure("V2 manifest has malformed case")
        case.pop("selected_native_frame_records", None)
    manifest_path = _under(attempt_root, attempt_root / "guarded-inputs" / "v1-manifest.json", "temporary V1 manifest")
    _atomic_json(manifest_path, value)
    return manifest_path


def _child_result(path: Path) -> dict[str, Any] | None:
    if not path.exists() or path.is_symlink() or path.stat().st_size > MAX_CHILD_RESULT_BYTES:
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def run_guard(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = args.manifest.expanduser().resolve()
    manifest = _json_load(manifest_path)
    records = _load_deferred(manifest)
    attempt_root = args.attempt_root.expanduser().resolve()
    attempt_root.mkdir(parents=True, exist_ok=True)
    output = _under(attempt_root, args.output.expanduser().resolve(), "wrapper output")
    log_path = _under(attempt_root, args.log_path.expanduser().resolve(), "wrapper child log")
    scratch_roots = _scratch_roots(manifest, attempt_root)
    before: list[dict[str, Any]] = []
    child_info: dict[str, Any] | None = None
    post: list[dict[str, Any]] | None = None
    cleanup_ok = False
    cleanup_error: str | None = None
    status = "FAILED_SOURCE_PRECHECK"
    reason: str | None = None
    child_output = _under(attempt_root, attempt_root / "observer" / ".v1-result.json", "V1 child output")
    try:
        before = _precheck(records)
        v1_manifest = _make_v1_manifest(manifest, attempt_root)
        python = args.python.expanduser().resolve()
        worker = args.v1_worker.expanduser().resolve()
        _regular(python, "V1 Python")
        _regular(worker, "V1 worker")
        command = [str(python), str(worker), "--manifest", str(v1_manifest), "--attempt-root", str(attempt_root), "--output", str(child_output)]
        child_info = _run_child(
            command,
            cwd=args.cwd.expanduser().resolve(),
            scratch_roots=scratch_roots,
            scratch_cap_bytes=int(args.max_scratch_bytes),
            log_limit=int(args.max_log_bytes),
            timeout_seconds=float(args.timeout_seconds),
        )
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        # _run_child owns a bounded tail in memory; write it only after the
        # process has ended so the child pipe is always drained.
        if log_path.exists() or log_path.is_symlink():
            raise GuardFailure(f"wrapper log already exists: {log_path}")
        log_path.write_bytes(child_info.pop("log_tail", b""))
        post = _postcheck(records, before)
        if child_info["cancellation"] is not None:
            status = "FAILED_CHILD_CANCELLED"
            reason = str(child_info["cancellation"])
        elif child_info["returncode"] != 0:
            status = "FAILED_CHILD"
            reason = f"V1 worker returned {child_info['returncode']}"
        else:
            status = "PASS_GUARDED_V1_NATIVE_SELECTED_OBSERVABLES"
    except GuardFailure as exc:
        reason = str(exc)
        if before and post is None:
            status = "FAILED_SOURCE_POSTCHECK"
        elif not before:
            status = "FAILED_SOURCE_PRECHECK"
        else:
            status = "FAILED_GUARD"
    finally:
        cleanup_ok, cleanup_error = _cleanup_scratch(scratch_roots)
        if not cleanup_ok and status.startswith("PASS"):
            status = "FAILED_SCRATCH_CLEANUP"
            reason = cleanup_error
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "status": status,
        "reason": reason,
        "scope": {
            "deferred_native_count": len(records),
            "v2_runtime_deferred_hashing": "NOT_PERFORMED_BY_RUNTIME_V8",
            "source_guard_owner": "this wrapper after parent reservation",
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
        "native_read_accounting": {
            "selected_frame_count": len(records),
            "logical_passes_per_native_source": 4,
            "pass_semantics": [
                "wrapper_pre_sha256_and_full_stat",
                "official_decoder_input_read_inside_immutable_v1_worker",
                "v1_worker_base_sha256_file_pass",
                "wrapper_post_sha256_and_full_stat",
            ],
            "native_source_bytes": sum(int(item["record"].get("bytes", 0)) for item in records),
            "v8_parent_deferred_hashing": False,
        },
        "source_integrity": {
            "pre": before,
            "post": post,
            "pre_post_exact_sha_and_stat": bool(before and post and before == post),
            "required_stat_fields": ["bytes", "mtime_ns", "ctime_ns", "device", "inode"],
        },
        "child": child_info,
        "child_output": {
            "path": str(child_output),
            "exists": child_output.exists(),
            "parsed_status": (_child_result(child_output) or {}).get("status") if child_output.exists() else None,
        },
        "scratch": {
            "cap_bytes": int(args.max_scratch_bytes),
            "roots": [str(path) for path in scratch_roots],
            "cleanup_ok": cleanup_ok,
            "cleanup_error": cleanup_error,
            "peak_observed_bytes": "NOT_MEASURED_EXACTLY; POLL_MAXIMUM_RECORDED_BY_GUARD",
        },
        "log": {
            "path": str(log_path),
            "max_bytes": int(args.max_log_bytes),
            "exists": log_path.exists(),
            "bytes": int(log_path.stat().st_size) if log_path.exists() else 0,
            "bounded": True,
        },
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    _atomic_json(output, result)
    return result


def _fixture_v1_worker(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env python3\nimport argparse, json, pathlib, time\np=argparse.ArgumentParser(); p.add_argument('--manifest'); p.add_argument('--attempt-root'); p.add_argument('--output'); a=p.parse_args()\nmanifest=json.loads(pathlib.Path(a.manifest).read_text())\ncase=manifest['cases'][0]\nscratch=pathlib.Path(case['scratch_root'].replace('{attempt_root}', a.attempt_root)); scratch.mkdir(parents=True, exist_ok=True)\nmode=__import__('os').environ.get('ROOT204_V3_FIXTURE_MODE','good')\nif mode=='oversize': (scratch/'oversize.bin').write_bytes(b'x'*(1024*1024+1))\nif mode=='mutate': pathlib.Path(case['raw_root'],'Part_0000.bi4').write_bytes(b'changed')\nif mode=='sleep': time.sleep(30)\nif mode=='spam': print('log-line-' + ('x'*8192)*32, flush=True)\npathlib.Path(a.output).parent.mkdir(parents=True, exist_ok=True)\npathlib.Path(a.output).write_text(json.dumps({'schema':'fixture-v1','status':'PASS_F1_NATIVE_HEADER_SELECTED_OBSERVABLES'}))\n""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _fixture_manifest(root: Path) -> tuple[Path, Path]:
    native = root / "native"
    native.mkdir(parents=True)
    parts: list[tuple[Path, str, dict[str, int]]] = []
    for frame in range(EXPECTED_DEFERRED_COUNT):
        part = native / f"Part_{frame:04d}.bi4"
        part.write_bytes(f"manufactured-decoder-source-{frame}".encode("ascii"))
        sha, stat_value = _sha_and_stat(part, f"fixture source {frame}")
        parts.append((part, sha, stat_value))
    decoder = root / "fixture_decoder.py"
    decoder.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    decoder.chmod(0o755)
    worker = root / "fixture_v1.py"
    _fixture_v1_worker(worker)
    scratch = root / "scratch" / "case"
    v2 = {
        "schema": V2_MANIFEST_SCHEMA,
        "axis_authority": {"coordinate_contract": {}},
        "cases": [{"label": "fixture", "raw_root": str(native), "scratch_root": "{attempt_root}/scratch/case"}],
        "native_deferred_records": {
            str(part): {
                "path": str(part),
                "frame": frame,
                "bytes": stat_value["bytes"],
                "mtime_ns": stat_value["mtime_ns"],
                "sha256": sha,
                "known_sha256": sha,
                "stat_at_prepare": stat_value,
            }
            for frame, (part, sha, stat_value) in enumerate(parts)
        },
    }
    manifest = root / "manifest.json"
    manifest.write_text(json.dumps(v2), encoding="utf-8")
    return manifest, worker


def self_test() -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="root204-v3-selftest-") as directory:
        root = Path(directory)
        manifest, worker = _fixture_manifest(root / "good")
        output = root / "good" / "attempt" / "observer" / "result.json"
        base_cmd = [sys.executable, "-B", str(Path(__file__).resolve()), "--run", "--manifest", str(manifest), "--attempt-root", str(root / "good" / "attempt"), "--output", str(output), "--v1-worker", str(worker), "--python", sys.executable, "--cwd", str(root), "--timeout-seconds", "10"]
        good = subprocess.run(base_cmd, capture_output=True, text=True, timeout=20)
        good_value = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {}
        results.append({"name": "manufactured_decoder_source_guard_pass", "status": "PASS" if good.returncode == 0 and good_value.get("status", "").startswith("PASS") else "FAIL"})

        mutate_manifest, mutate_worker = _fixture_manifest(root / "mutate")
        mutate_output = root / "mutate" / "attempt" / "observer" / "result.json"
        mutate_cmd = [*base_cmd[:2], str(Path(__file__).resolve()), "--run", "--manifest", str(mutate_manifest), "--attempt-root", str(root / "mutate" / "attempt"), "--output", str(mutate_output), "--v1-worker", str(mutate_worker), "--python", sys.executable, "--cwd", str(root), "--timeout-seconds", "10"]
        mutate = subprocess.run(mutate_cmd, env={**os.environ, "ROOT204_V3_FIXTURE_MODE": "mutate"}, capture_output=True, text=True, timeout=20)
        mutate_value = json.loads(mutate_output.read_text(encoding="utf-8")) if mutate_output.exists() else {}
        results.append({"name": "changed_native_rejected_at_postcheck", "status": "PASS" if mutate.returncode != 0 and mutate_value.get("status") == "FAILED_SOURCE_POSTCHECK" else "FAIL"})

        unknown_manifest, unknown_worker = _fixture_manifest(root / "unknown")
        unknown_value = _json_load(unknown_manifest)
        only = next(iter(unknown_value["native_deferred_records"].values()))
        only["sha256"] = "UNKNOWN"
        only["known_sha256"] = "UNKNOWN"
        unknown_manifest.write_text(json.dumps(unknown_value), encoding="utf-8")
        unknown_output = root / "unknown" / "attempt" / "observer" / "result.json"
        unknown_cmd = [*base_cmd[:2], str(Path(__file__).resolve()), "--run", "--manifest", str(unknown_manifest), "--attempt-root", str(root / "unknown" / "attempt"), "--output", str(unknown_output), "--v1-worker", str(unknown_worker), "--python", sys.executable, "--cwd", str(root), "--timeout-seconds", "10"]
        unknown = subprocess.run(unknown_cmd, capture_output=True, text=True, timeout=20)
        unknown_value_out = json.loads(unknown_output.read_text(encoding="utf-8")) if unknown_output.exists() else {}
        results.append({"name": "unknown_sha_rejected_before_child", "status": "PASS" if unknown.returncode != 0 and unknown_value_out.get("status") == "FAILED_SOURCE_PRECHECK" else "FAIL"})

        cap_manifest, cap_worker = _fixture_manifest(root / "cap")
        cap_output = root / "cap" / "attempt" / "observer" / "result.json"
        cap_cmd = [*base_cmd[:2], str(Path(__file__).resolve()), "--run", "--manifest", str(cap_manifest), "--attempt-root", str(root / "cap" / "attempt"), "--output", str(cap_output), "--v1-worker", str(cap_worker), "--python", sys.executable, "--cwd", str(root), "--timeout-seconds", "10", "--max-scratch-bytes", "1024"]
        cap = subprocess.run(cap_cmd, env={**os.environ, "ROOT204_V3_FIXTURE_MODE": "oversize"}, capture_output=True, text=True, timeout=20)
        cap_value = json.loads(cap_output.read_text(encoding="utf-8")) if cap_output.exists() else {}
        cap_scratch = root / "cap" / "attempt" / "scratch" / "case"
        results.append({"name": "scratch_cap_terminates_and_cleans_child", "status": "PASS" if cap.returncode != 0 and cap_value.get("status") == "FAILED_CHILD_CANCELLED" and not cap_scratch.exists() else "FAIL"})

        sleep_manifest, sleep_worker = _fixture_manifest(root / "sleep")
        sleep_output = root / "sleep" / "attempt" / "observer" / "result.json"
        sleep_cmd = [*base_cmd[:2], str(Path(__file__).resolve()), "--run", "--manifest", str(sleep_manifest), "--attempt-root", str(root / "sleep" / "attempt"), "--output", str(sleep_output), "--v1-worker", str(sleep_worker), "--python", sys.executable, "--cwd", str(root), "--timeout-seconds", "0.1"]
        sleep = subprocess.run(sleep_cmd, env={**os.environ, "ROOT204_V3_FIXTURE_MODE": "sleep"}, capture_output=True, text=True, timeout=20)
        sleep_value = json.loads(sleep_output.read_text(encoding="utf-8")) if sleep_output.exists() else {}
        results.append({"name": "child_timeout_group_reaped", "status": "PASS" if sleep.returncode != 0 and sleep_value.get("status") == "FAILED_CHILD_CANCELLED" else "FAIL"})

        spam_manifest, spam_worker = _fixture_manifest(root / "spam")
        spam_output = root / "spam" / "attempt" / "observer" / "result.json"
        spam_cmd = [*base_cmd[:2], str(Path(__file__).resolve()), "--run", "--manifest", str(spam_manifest), "--attempt-root", str(root / "spam" / "attempt"), "--output", str(spam_output), "--v1-worker", str(spam_worker), "--python", sys.executable, "--cwd", str(root), "--timeout-seconds", "10", "--max-log-bytes", "1024"]
        spam = subprocess.run(spam_cmd, env={**os.environ, "ROOT204_V3_FIXTURE_MODE": "spam"}, capture_output=True, text=True, timeout=20)
        spam_value = json.loads(spam_output.read_text(encoding="utf-8")) if spam_output.exists() else {}
        spam_log = spam_value.get("log", {})
        results.append({"name": "child_log_pipe_drained_with_bounded_tail", "status": "PASS" if spam.returncode == 0 and spam_log.get("bounded") is True and int(spam_log.get("bytes", 0)) <= 1024 else "FAIL"})
    return {"schema": SCHEMA, "status": "PASS" if all(item["status"] == "PASS" for item in results) else "FAIL", "cases": results, "scope": "temporary source/decoder/child fixtures only; no production native read"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--attempt-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--log-path", type=Path)
    parser.add_argument("--v1-worker", type=Path, default=V1_WORKER)
    parser.add_argument("--python", type=Path, default=PYTHON)
    parser.add_argument("--cwd", type=Path, default=V1_WORKER.parents[5])
    parser.add_argument("--max-scratch-bytes", type=int, default=SCRATCH_CAP_BYTES)
    parser.add_argument("--max-log-bytes", type=int, default=DEFAULT_MAX_LOG_BYTES)
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    args = parser.parse_args()
    if args.self_test:
        result = self_test()
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if result["status"] == "PASS" else 2
    if args.manifest is None or args.attempt_root is None or args.output is None:
        parser.error("--manifest, --attempt-root and --output are required for --run")
    if args.log_path is None:
        args.log_path = args.attempt_root / "observer" / "f1_native_selected_observer_v3_child.log"
    # The default cap is part of the contract.  A smaller cap is useful for
    # a parent-reviewed fixture; increasing it at runtime is forbidden.
    if args.max_scratch_bytes > SCRATCH_CAP_BYTES or args.max_scratch_bytes <= 0:
        parser.error("--max-scratch-bytes must be in (0, 256MiB]")
    try:
        result = run_guard(args)
    except Exception as exc:
        print(json.dumps({"schema": SCHEMA, "status": "FAILED_WRAPPER_BEFORE_OUTPUT", "error": {"type": type(exc).__name__, "message": str(exc)}}, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps({"schema": SCHEMA, "status": result["status"], "output": str(args.output.expanduser().resolve())}, sort_keys=True))
    return 0 if result["status"].startswith("PASS") else 2


if __name__ == "__main__":
    raise SystemExit(main())
