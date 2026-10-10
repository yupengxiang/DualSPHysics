#!/usr/bin/env python3
"""Additive V3 bounded Git snapshot with whole-lifecycle cleanup.

``ds_data02_git_launch_state_v1`` and V2 are already consumed by earlier
runtime receipts and remain immutable.  V3 is a narrow forward adapter for a
new runtime which needs two extra guarantees:

* the owned process group is cleaned up when a signal arrives during the
  final ``wait`` as well as during pipe draining; and
* a fast leader exit cannot leave an owned descendant alive while a pipe is
  still open.

The report remains compatible with V2 and adds an explicit lifecycle cleanup
record.  A timeout or cancellation is always a failed observation; it is
never converted into a clean/dirty Git claim.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import time
from typing import Any, Mapping, Sequence

import ds_data02_git_launch_state_v2 as v2


SCHEMA = "ds02.stage2.git-launch-state.v3"
_cleanup_records: list[dict[str, Any]] = []


def _group_exists(pgid: int) -> bool:
    """Return whether a non-zombie member remains in the owned process group."""
    saw_procfs = False
    proc_root = Path("/proc")
    if proc_root.is_dir():
        try:
            entries = list(proc_root.iterdir())
        except OSError:
            entries = []
        for entry in entries:
            if not entry.name.isdigit():
                continue
            try:
                fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
                if len(fields) >= 3 and int(fields[2]) == pgid:
                    saw_procfs = True
                    if fields[0] != "Z":
                        return True
            except (FileNotFoundError, PermissionError, ValueError, OSError):
                continue
        if saw_procfs:
            return False
    try:
        os.killpg(pgid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def _terminate_group(process: subprocess.Popen[bytes], *, grace_seconds: float = 0.10) -> dict[str, Any]:
    """Terminate the process group even after its leader has exited."""
    pgid = int(process.pid)
    before = process.poll()
    term_sent = False
    kill_sent = False
    try:
        os.killpg(pgid, signal.SIGTERM)
        term_sent = True
    except (ProcessLookupError, PermissionError):
        pass
    try:
        process.wait(timeout=max(0.0, grace_seconds))
    except subprocess.TimeoutExpired:
        pass
    # ``poll()`` is deliberately not used as a gate.  A leader can exit while
    # a descendant in the same session ignores SIGTERM and holds a pipe.
    if _group_exists(pgid):
        try:
            os.killpg(pgid, signal.SIGKILL)
            kill_sent = True
        except (ProcessLookupError, PermissionError):
            pass
    try:
        process.wait(timeout=max(0.2, grace_seconds * 4))
    except subprocess.TimeoutExpired:
        pass
    record = {
        "owned_pgid": pgid,
        "sigterm_sent": term_sent,
        "sigkill_sent": kill_sent,
        "leader_returncode_before_cleanup": before,
        "leader_returncode_after_cleanup": process.poll(),
        "group_alive_after_cleanup": _group_exists(pgid),
    }
    _cleanup_records.append(record)
    return record


def _close_selector(selector: selectors.BaseSelector) -> None:
    for key in list(selector.get_map().values()):
        try:
            selector.unregister(key.fileobj)
        except (KeyError, ValueError):
            pass
        try:
            key.fileobj.close()
        except OSError:
            pass
    selector.close()


def _run_bounded(
    argv: Sequence[str], *, cwd: Path, env: Mapping[str, str], deadline: float,
    max_output_bytes: int, max_stderr_bytes: int,
) -> dict[str, Any]:
    """Run a bounded command and clean its owned group on every exit path."""
    started = time.monotonic()
    try:
        process = subprocess.Popen(
            list(argv), cwd=str(cwd), env=dict(env), stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, start_new_session=True,
        )
    except (OSError, ValueError) as exc:
        return {
            "outcome": "ERROR", "returncode": None, "stdout": b"", "stderr_tail": b"",
            "stdout_bytes": 0, "stderr_bytes": 0, "stderr_truncated": False,
            "error": {"type": type(exc).__name__, "message": str(exc)},
            "elapsed_seconds": max(0.0, time.monotonic() - started), "cleanup": None,
        }

    assert process.stdout is not None and process.stderr is not None
    selector = selectors.DefaultSelector()
    streams = {
        process.stdout.fileno(): (process.stdout, "stdout"),
        process.stderr.fileno(): (process.stderr, "stderr"),
    }
    for fileobj in (process.stdout, process.stderr):
        os.set_blocking(fileobj.fileno(), False)
        selector.register(fileobj, selectors.EVENT_READ)

    stdout = bytearray()
    stderr = bytearray()
    stdout_bytes = 0
    stderr_bytes = 0
    stderr_truncated = False
    outcome = "OK"
    failure: dict[str, Any] | None = None
    cleanup: dict[str, Any] | None = None
    try:
        while selector.get_map() and outcome == "OK":
            if time.monotonic() >= deadline:
                outcome = "TIMEOUT"
                failure = {"timeout_seconds": None}
                cleanup = _terminate_group(process)
                break
            events = selector.select(min(max(0.0, deadline - time.monotonic()), 0.05))
            if not events:
                continue
            for key, _mask in events:
                fileobj = key.fileobj
                fd = fileobj.fileno()
                label = streams[fd][1]
                while outcome == "OK":
                    if time.monotonic() >= deadline:
                        outcome = "TIMEOUT"
                        failure = {"timeout_seconds": None, "during_pipe_drain": True}
                        cleanup = _terminate_group(process)
                        break
                    try:
                        chunk = os.read(fd, 64 * 1024)
                    except BlockingIOError:
                        break
                    except OSError:
                        chunk = b""
                    if not chunk:
                        try:
                            selector.unregister(fileobj)
                        except (KeyError, ValueError):
                            pass
                        try:
                            fileobj.close()
                        except OSError:
                            pass
                        break
                    if label == "stdout":
                        stdout_bytes += len(chunk)
                        if stdout_bytes > max_output_bytes:
                            outcome = "OUTPUT_LIMIT"
                            failure = {"max_output_bytes": max_output_bytes,
                                       "observed_output_bytes": stdout_bytes}
                            cleanup = _terminate_group(process)
                            break
                        stdout.extend(chunk)
                    else:
                        stderr_bytes += len(chunk)
                        if len(stderr) < max_stderr_bytes:
                            stderr.extend(chunk[:max_stderr_bytes - len(stderr)])
                        if stderr_bytes > max_stderr_bytes:
                            stderr_truncated = True
                if outcome != "OK":
                    break
    except BaseException:
        # This covers SIGTERM/KeyboardInterrupt arriving in selector.select,
        # os.read, and the inner drain loop.  Do not let an owned descendant
        # survive merely because the parent got interrupted.
        cleanup = cleanup or _terminate_group(process)
        raise
    finally:
        _close_selector(selector)

    try:
        # ``wait`` is also inside the cleanup boundary.  A cancellation here
        # must terminate the group before the exception is propagated.
        returncode = process.wait(timeout=max(0.0, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        if outcome == "OK":
            outcome = "TIMEOUT"
            failure = {"timeout_seconds": None, "process_wait": True}
        cleanup = cleanup or _terminate_group(process)
        returncode = process.poll()
    except BaseException:
        cleanup = cleanup or _terminate_group(process)
        raise

    if outcome == "OK" and returncode != 0:
        outcome = "ERROR"
        failure = {"returncode": returncode}
    if failure is not None:
        failure["stderr_tail"] = bytes(stderr).decode("utf-8", "replace")[-4096:]
    return {
        "outcome": outcome, "returncode": returncode, "stdout": bytes(stdout),
        "stderr_tail": bytes(stderr), "stdout_bytes": stdout_bytes,
        "stderr_bytes": stderr_bytes, "stderr_truncated": stderr_truncated,
        "error": failure, "elapsed_seconds": max(0.0, time.monotonic() - started),
        "cleanup": cleanup,
    }


def bounded_git_launch_state(
    root: str | os.PathLike[str], *, timeout_seconds: float = v2.v1.DEFAULT_TIMEOUT_SECONDS,
    max_output_bytes: int = v2.v1.DEFAULT_MAX_OUTPUT_BYTES,
    input_paths=None, git_executable: str | os.PathLike[str] = "git",
) -> dict[str, Any]:
    """Run the immutable V1 report assembly with the V3 subprocess primitive."""
    global _cleanup_records
    _cleanup_records = []
    old_runner = v2.v1._run_bounded
    old_terminator = v2.v1._terminate_group
    v2.v1._run_bounded = _run_bounded
    v2.v1._terminate_group = _terminate_group
    try:
        report = v2.v1.bounded_git_launch_state(
            root, timeout_seconds=timeout_seconds, max_output_bytes=max_output_bytes,
            input_paths=input_paths, git_executable=git_executable,
        )
    finally:
        v2.v1._run_bounded = old_runner
        v2.v1._terminate_group = old_terminator
    report["schema"] = SCHEMA
    report["cleanup"] = list(_cleanup_records)
    commit = report.get("commit")
    if report.get("status") == "OK" and (
        not isinstance(commit, str) or re.fullmatch(r"[0-9a-f]{40,64}", commit) is None
    ):
        report["status"] = "ERROR"
        report["commit"] = None
        report["status_porcelain"] = None
        report["status_porcelain_sha256"] = None
        report["status_porcelain_bytes"] = None
        report["diff_sha256"] = None
        report["diff_bytes"] = None
        report["error"] = {"message": "rev-parse returned a non-hex HEAD"}
    return report


git_launch_state = bounded_git_launch_state
