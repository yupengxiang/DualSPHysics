#!/usr/bin/env python3
"""Run the immutable V2 native worker with bounded, owned decoder scratch.

This is an additive wrapper for the already-bound V2 scientific converter.  It
keeps the V2 CLI and raw-tree contract, but makes the temporary decoder output
an attempt-owned resource with a finite per-frame byte budget and timeout.
The watchdog measures the directory while the decoder runs, terminates only
the decoder process group that it started when a limit is crossed, and records
the measured peak and cleanup result.  A post-call stat check closes the small
polling race.  The wrapper never owns the stage2 ledger; its parent guard owns
reservation, outer deadlines, and terminal accounting.
"""
from __future__ import annotations

import contextlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Iterator, MutableMapping, Sequence


SCHEMA = "ds02.stage2.f2-native-raw-to-typed-label-scratch-wrapper.v4"
WORKER_NAME = "ds_data02_stage2_f2_native_raw_to_typed_label_v2.py"
DEFAULT_MAX_FRAME_SCRATCH_BYTES = 512 * 1024 * 1024
DEFAULT_DECODER_TIMEOUT_SECONDS = 180.0
WATCH_INTERVAL_SECONDS = 0.02


class OwnedScratchError(RuntimeError):
    """Raised when the private decoder scratch contract cannot be enforced."""


class OwnedScratchLimitError(OwnedScratchError):
    """A frame exceeded its attempt-owned scratch byte budget."""


class OwnedDecoderTimeout(OwnedScratchError):
    """A frame exceeded the finite decoder callback deadline."""


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise OwnedScratchError(f"JSON object required: {path}")
    return value


def _write_new(path: Path, value: MutableMapping[str, Any]) -> None:
    if path.exists():
        raise OwnedScratchError(f"refusing to overwrite scratch report: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=True)
        stream.write("\n")


def _directory_bytes(root: Path) -> tuple[int, int]:
    """Return regular-file bytes/count, rejecting links that escape the root."""
    if not root.exists():
        return 0, 0
    if not root.is_dir():
        raise OwnedScratchError(f"scratch root is not a directory: {root}")
    total = 0
    files = 0
    for directory, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        directory_path = Path(directory)
        for dirname in list(dirnames):
            path = directory_path / dirname
            if path.is_symlink():
                raise OwnedScratchError(f"scratch directory contains a symlink: {path}")
        for filename in filenames:
            path = directory_path / filename
            if path.is_symlink():
                raise OwnedScratchError(f"scratch file is a symlink: {path}")
            try:
                size = path.stat(follow_symlinks=False).st_size
            except FileNotFoundError:
                # The decoder may replace a file between directory enumeration
                # and stat.  The next poll/post-call check closes the race.
                continue
            total += int(size)
            files += 1
    return total, files


def _terminate_owned_group(pid: int | None, *, grace_seconds: float = 0.25) -> None:
    """Terminate only the decoder process group created by this wrapper."""
    if pid is None or pid <= 0:
        return
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except PermissionError as error:
        raise OwnedScratchError(f"cannot terminate owned decoder group {pid}: {error}") from error
    deadline = time.monotonic() + max(0.0, float(grace_seconds))
    while time.monotonic() < deadline:
        try:
            os.killpg(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.01)
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


class _SubprocessProxy:
    """Give the copied converter a guarded ``run`` without global patching."""

    def __init__(self, real: Any, run: Any) -> None:
        self._real = real
        self.run = run

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


@contextlib.contextmanager
def owned_tempdir(root: Path, state: MutableMapping[str, Any] | None = None) -> Iterator[Path]:
    """Make ``tempfile`` resolve only below a fresh attempt directory."""
    root = root.expanduser().resolve()
    if root.exists():
        raise OwnedScratchError(f"attempt scratch already exists: {root}")
    root.mkdir(parents=True, exist_ok=False)
    previous = tempfile.tempdir
    tempfile.tempdir = str(root)
    try:
        yield root
    finally:
        tempfile.tempdir = previous
        try:
            if root.exists():
                shutil.rmtree(root)
        except Exception as error:
            if state is not None:
                state["attempt_cleanup_error"] = f"{type(error).__name__}: {error}"
            raise
        finally:
            if state is not None:
                state["attempt_scratch_removed"] = not root.exists()
                if root.exists() and "attempt_cleanup_error" not in state:
                    state["attempt_cleanup_error"] = "scratch root remained after cleanup"


@contextlib.contextmanager
def _frame_guard(frame_dir: Path, state: MutableMapping[str, Any]) -> Iterator[None]:
    """Watch one frame, with a bounded timeout and an interruptible byte cap."""
    stop = threading.Event()
    main_thread = threading.current_thread() is threading.main_thread()
    old_usr1: Any = None
    old_alarm: Any = None
    old_timer: tuple[float, float] = (0.0, 0.0)
    started = time.monotonic()

    def fail_signal(_signum: int, _frame: Any) -> None:
        if _signum == signal.SIGALRM and "guard_reason" not in state:
            state["guard_reason"] = (
                f"decoder callback exceeded {float(state['decoder_timeout_seconds']):.3f}s"
            )
        reason = str(state.get("guard_reason") or "decoder watchdog interrupted")
        if reason.startswith("scratch byte budget"):
            raise OwnedScratchLimitError(reason)
        raise OwnedDecoderTimeout(reason)

    def monitor() -> None:
        while not stop.wait(WATCH_INTERVAL_SECONDS):
            try:
                current, files = _directory_bytes(frame_dir)
            except BaseException as error:
                state.setdefault("guard_reason", f"scratch measurement failed: {error}")
                stop.set()
                pid = state.get("decoder_pid")
                if isinstance(pid, int):
                    try:
                        _terminate_owned_group(pid)
                    except BaseException:
                        pass
                if main_thread:
                    try:
                        os.kill(os.getpid(), signal.SIGUSR1)
                    except ProcessLookupError:
                        pass
                return
            state["scratch_bytes_current"] = current
            state["scratch_files_current"] = files
            state["scratch_bytes_peak"] = max(int(state.get("scratch_bytes_peak", 0)), current)
            state["scratch_files_peak"] = max(int(state.get("scratch_files_peak", 0)), files)
            limit = int(state["max_frame_scratch_bytes"])
            if current > limit and "guard_reason" not in state:
                state["guard_reason"] = (
                    f"scratch byte budget exceeded: {current} > {limit} bytes"
                )
                pid = state.get("decoder_pid")
                if isinstance(pid, int):
                    try:
                        _terminate_owned_group(pid)
                    except BaseException:
                        pass
                if main_thread:
                    try:
                        os.kill(os.getpid(), signal.SIGUSR1)
                    except ProcessLookupError:
                        pass
                return

    if main_thread:
        old_usr1 = signal.getsignal(signal.SIGUSR1)
        old_alarm = signal.getsignal(signal.SIGALRM)
        old_timer = signal.getitimer(signal.ITIMER_REAL)
        signal.signal(signal.SIGUSR1, fail_signal)
        signal.signal(signal.SIGALRM, fail_signal)
        signal.setitimer(signal.ITIMER_REAL, float(state["decoder_timeout_seconds"]))
    watcher = threading.Thread(target=monitor, name="ds02-decoder-scratch-watch", daemon=True)
    watcher.start()
    try:
        yield
    finally:
        elapsed = time.monotonic() - started
        state["decoder_elapsed_seconds"] = float(elapsed)
        stop.set()
        watcher.join(timeout=2.0)
        state["scratch_watchdog_stopped"] = not watcher.is_alive()
        try:
            current, files = _directory_bytes(frame_dir)
        except Exception as error:
            state["scratch_measurement_error"] = f"{type(error).__name__}: {error}"
            current, files = 0, 0
        state["scratch_bytes_current"] = current
        state["scratch_files_current"] = files
        state["scratch_bytes_peak"] = max(int(state.get("scratch_bytes_peak", 0)), current)
        state["scratch_files_peak"] = max(int(state.get("scratch_files_peak", 0)), files)
        if current > int(state["max_frame_scratch_bytes"]):
            state.setdefault(
                "guard_reason",
                f"scratch byte budget exceeded after decode: {current} > {state['max_frame_scratch_bytes']} bytes",
            )
        if main_thread:
            signal.setitimer(signal.ITIMER_REAL, 0.0)
            signal.signal(signal.SIGUSR1, old_usr1)
            signal.signal(signal.SIGALRM, old_alarm)
            # Do not consume an outer timer silently.  In normal parent-guard
            # launches there is no Python timer; this preserves one if a caller
            # installed it before entering the wrapper.
            if old_timer[0] > 0.0:
                remaining = max(0.0, old_timer[0] - elapsed)
                signal.setitimer(signal.ITIMER_REAL, remaining, old_timer[1])


def _guarded_run(real_subprocess: Any, state: MutableMapping[str, Any], command: Any,
                 *args: Any, **kwargs: Any) -> Any:
    """Run only the native decoder in an owned process group."""
    timeout = kwargs.pop("timeout", None)
    maximum = float(state["decoder_timeout_seconds"])
    effective_timeout = maximum if timeout is None else min(float(timeout), maximum)
    check = bool(kwargs.pop("check", False))
    input_data = kwargs.pop("input", None)
    capture_output = bool(kwargs.pop("capture_output", False))
    if capture_output:
        if "stdout" in kwargs or "stderr" in kwargs:
            raise OwnedScratchError("capture_output conflicts with stdout/stderr")
        kwargs["stdout"] = real_subprocess.PIPE
        kwargs["stderr"] = real_subprocess.PIPE
    if kwargs.get("shell", False):
        raise OwnedScratchError("shell decoder command is forbidden")
    kwargs["start_new_session"] = True
    process = real_subprocess.Popen(command, *args, **kwargs)
    state["decoder_pid"] = int(process.pid)
    state["decoder_pgid"] = int(process.pid)
    stdout: Any = None
    stderr: Any = None
    try:
        try:
            stdout, stderr = process.communicate(input=input_data, timeout=effective_timeout)
        except real_subprocess.TimeoutExpired as error:
            _terminate_owned_group(process.pid)
            stdout, stderr = process.communicate()
            raise OwnedDecoderTimeout(
                f"decoder subprocess exceeded {effective_timeout:.3f}s"
            ) from error
        reason = state.get("guard_reason")
        if reason:
            _terminate_owned_group(process.pid)
            process.wait()
            if str(reason).startswith("scratch byte budget"):
                raise OwnedScratchLimitError(str(reason))
            raise OwnedScratchError(str(reason))
    except BaseException:
        if process.poll() is None:
            try:
                _terminate_owned_group(process.pid)
                process.wait(timeout=1.0)
            except BaseException:
                try:
                    process.kill()
                except BaseException:
                    pass
        raise
    finally:
        state.pop("decoder_pid", None)
        state.pop("decoder_pgid", None)
    completed = real_subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    if check and completed.returncode:
        raise real_subprocess.CalledProcessError(
            completed.returncode, command, output=stdout, stderr=stderr
        )
    return completed


def install_decoder_scratch(loader: Any, state: MutableMapping[str, Any]) -> tuple[Any, Any]:
    """Install V4 scratch/byte/timeout guards into the copied V2 loader."""
    original_loader = loader._load_module
    patched: list[tuple[Any, Any]] = []

    def load_module(path: Path, name: str) -> Any:
        module = original_loader(path, name)
        if name != "_ds02_bound_converter_v2":
            return module
        original_decode = getattr(module, "decode_frame", None)
        if not callable(original_decode):
            raise OwnedScratchError("bound converter has no decode_frame callback")
        real_subprocess = getattr(module, "subprocess", None)
        if real_subprocess is None or not callable(getattr(real_subprocess, "Popen", None)):
            raise OwnedScratchError("bound converter has no subprocess module")

        def guarded_run(command: Any, *args: Any, **kwargs: Any) -> Any:
            return _guarded_run(real_subprocess, state, command, *args, **kwargs)

        module.subprocess = _SubprocessProxy(real_subprocess, guarded_run)
        patched.append((module, real_subprocess))
        state["converter_subprocess_guard_installed"] = True

        def decode_frame(frame_path: Path, decoder: Path, scratch_root: Path, index: int) -> Any:
            shared = Path(scratch_root).expanduser().resolve()
            if not shared.is_dir():
                raise OwnedScratchError(f"converter scratch is not a directory: {shared}")
            frame_dir = shared / f"owned-frame-{int(index):04d}"
            if frame_dir.exists():
                raise OwnedScratchError(f"decoder frame scratch already exists: {frame_dir}")
            frame_dir.mkdir()
            active = int(state.get("active_frame_directories", 0)) + 1
            state["active_frame_directories"] = active
            state["max_live_frame_directories"] = max(
                int(state.get("max_live_frame_directories", 0)), active
            )
            state["frames_started"] = int(state.get("frames_started", 0)) + 1
            state.pop("guard_reason", None)
            state["scratch_bytes_current"] = 0
            state["scratch_files_current"] = 0
            state["scratch_bytes_peak"] = 0
            state["scratch_files_peak"] = 0
            primary: BaseException | None = None
            result: Any = None
            cleanup_error: BaseException | None = None
            try:
                with _frame_guard(frame_dir, state):
                    result = original_decode(frame_path, decoder, frame_dir, int(index))
            except BaseException as error:
                primary = error
            finally:
                state["active_frame_directories"] = max(
                    0, int(state.get("active_frame_directories", 1)) - 1
                )
                frame_bytes = 0
                frame_files = 0
                try:
                    frame_bytes, frame_files = _directory_bytes(frame_dir)
                    if frame_bytes > int(state["max_frame_scratch_bytes"]):
                        state.setdefault(
                            "guard_reason",
                            f"scratch byte budget exceeded after decode: {frame_bytes} > {state['max_frame_scratch_bytes']} bytes",
                        )
                    shutil.rmtree(frame_dir)
                    if frame_dir.exists():
                        raise OwnedScratchError(f"frame scratch remained: {frame_dir}")
                except BaseException as error:
                    cleanup_error = error
                    state.setdefault("cleanup_failures", []).append({
                        "frame": int(index), "path": str(frame_dir),
                        "error": f"{type(error).__name__}: {error}",
                    })
                state["frames_cleaned"] = int(state.get("frames_cleaned", 0)) + (0 if cleanup_error else 1)
                state.setdefault("frame_records", []).append({
                    "frame": int(index), "path": str(frame_dir),
                    "bytes_at_cleanup": int(frame_bytes), "files_at_cleanup": int(frame_files),
                    "peak_bytes": int(state.get("scratch_bytes_peak", frame_bytes)),
                    "peak_files": int(state.get("scratch_files_peak", frame_files)),
                    "elapsed_seconds": float(state.get("decoder_elapsed_seconds", 0.0)),
                    "guard_reason": state.get("guard_reason"),
                    "cleanup": "FAILED" if cleanup_error else "PASS",
                })
            if primary is not None:
                raise primary
            if cleanup_error is not None:
                raise cleanup_error
            reason = state.get("guard_reason")
            if reason:
                if str(reason).startswith("scratch byte budget"):
                    raise OwnedScratchLimitError(str(reason))
                raise OwnedScratchError(str(reason))
            return result

        module.decode_frame = decode_frame
        state["converter_wrapper_installed"] = True
        return module

    loader._load_module = load_module

    def restore() -> None:
        loader._load_module = original_loader
        for module, original_subprocess in patched:
            module.subprocess = original_subprocess
        patched.clear()

    return original_loader, restore


def _worker_path() -> Path:
    target_root = Path(__file__).resolve().parents[1]
    worker = target_root / "runtime" / "native" / WORKER_NAME
    if not worker.is_file():
        raise OwnedScratchError(f"copied V2 worker is missing: {worker}")
    return worker


def _load_worker() -> Any:
    path = _worker_path()
    spec = importlib.util.spec_from_file_location("_ds02_bound_worker_v2_for_v4", path)
    if spec is None or spec.loader is None:
        raise OwnedScratchError(f"cannot load copied V2 worker: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _option(argv: Sequence[str], name: str) -> Path | None:
    try:
        value = argv[list(argv).index(name) + 1]
    except (ValueError, IndexError):
        return None
    return Path(value).expanduser().resolve()


def _scratch_report_path(output_dir: Path | None, scratch_parent: Path) -> Path:
    if output_dir is not None and output_dir.is_dir():
        return output_dir / "owned-decoder-scratch-v4.json"
    return scratch_parent / f"{(output_dir or scratch_parent).name}.owned-decoder-scratch-v4.json"


def run(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    output_dir = _option(args, "--output-dir")
    if output_dir is None:
        raise OwnedScratchError("V2-compatible --output-dir is required")
    scratch_parent = output_dir.parent
    scratch_root = scratch_parent / f".owned-decoder-scratch-v4-{os.getpid()}"
    state: dict[str, Any] = {
        "schema": SCHEMA,
        "wrapper_version": "v4",
        "worker_command_compatibility": "ds_data02_stage2_f2_native_raw_to_typed_label_v2.py",
        "attempt_scratch_path": str(scratch_root),
        "scratch_scope": "parent-approved-attempt-owned",
        "per_frame_directory": True,
        "cleanup_after_each_frame": True,
        "default_tmp_forbidden": True,
        "max_frame_scratch_bytes": int(DEFAULT_MAX_FRAME_SCRATCH_BYTES),
        "decoder_timeout_seconds": float(DEFAULT_DECODER_TIMEOUT_SECONDS),
        "watch_interval_seconds": float(WATCH_INTERVAL_SECONDS),
        "byte_guard_enforcement": "polling watchdog plus owned decoder process-group termination and post-call stat",
        "timeout_enforcement": "finite decoder subprocess timeout plus callback alarm",
        "cleanup_failure_is_error": True,
        "status": "RUNNING",
        "frames_started": 0,
        "frames_cleaned": 0,
        "active_frame_directories": 0,
        "max_live_frame_directories": 0,
        "scratch_bytes_peak": 0,
        "scratch_files_peak": 0,
        "frame_records": [],
        "cleanup_failures": [],
        "module_fallback": "FORBIDDEN",
    }
    worker = _load_worker()
    restore: Any = None
    exit_code = 1
    try:
        with owned_tempdir(scratch_root, state):
            _original_loader, restore = install_decoder_scratch(worker, state)
            state["tempfile_gettempdir"] = tempfile.gettempdir()
            value = worker.main(args)
            exit_code = int(value or 0)
            state["status"] = "PASS_WORKER_RETURNED"
    except SystemExit as error:
        exit_code = int(error.code or 0)
        state["status"] = "WORKER_SYSTEM_EXIT" if exit_code == 0 else "FAILED_WORKER_SYSTEM_EXIT"
        state["error_code"] = exit_code
        raise
    except BaseException as error:
        state["status"] = "FAILED_SCRATCH_WRAPPER"
        state["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        if restore is not None:
            try:
                restore()
            except BaseException as error:
                state["restore_error"] = f"{type(error).__name__}: {error}"
        state["active_frame_directories"] = 0
        report_path = _scratch_report_path(output_dir, scratch_parent)
        try:
            _write_new(report_path, state)
        except Exception as error:
            state["report_write_error"] = f"{type(error).__name__}: {error}"
    return exit_code


def main(argv: Sequence[str] | None = None) -> int:
    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
