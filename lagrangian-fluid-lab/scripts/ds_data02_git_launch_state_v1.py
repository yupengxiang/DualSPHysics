#!/usr/bin/env python3
"""Bounded, evidence-preserving Git launch snapshot.

This helper is deliberately independent of the consumed Stage2 runtimes.  A
plain ``git status`` can wait on an index lock for an unbounded amount of time;
the runtime must therefore treat Git provenance as a bounded observation.  A
timeout, failed command, or output limit is reported as an explicit failure
state and never converted into a clean or dirty worktree claim.

``input_paths`` provides an honest narrow scope for a future parent request.
When it is present, the report says ``INPUT_SCOPE_ONLY`` and lists the exact
repository-relative paths used for status and diff.  It does not claim that
the rest of the worktree is clean.  Scientific and external inputs remain
separately bound by their own path/stat/hash contracts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import time
from typing import Any, Iterable, Mapping, Sequence


SCHEMA = "ds02.stage2.git-launch-state.v1"
DEFAULT_TIMEOUT_SECONDS = 2.0
DEFAULT_MAX_OUTPUT_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_STDERR_BYTES = 64 * 1024


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _normalize_input_paths(input_paths: Iterable[str] | None) -> list[str] | None:
    if input_paths is None:
        return None
    result: list[str] = []
    seen: set[str] = set()
    for value in input_paths:
        if not isinstance(value, str) or not value or "\x00" in value:
            raise ValueError("input_paths must contain non-empty strings without NUL")
        path = Path(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("input_paths must be repository-relative and cannot contain '..'")
        normalized = path.as_posix()
        if normalized in {"", "."}:
            raise ValueError("input_paths cannot contain the repository root")
        if normalized in seen:
            raise ValueError("input_paths must not contain duplicates")
        seen.add(normalized)
        result.append(normalized)
    if not result:
        raise ValueError("input_paths must not be empty when supplied")
    return result


def _terminate_group(process: subprocess.Popen[bytes], *, grace_seconds: float = 0.10) -> None:
    """Stop the owned process group without waiting on an inherited pipe."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        process.wait(timeout=max(0.0, grace_seconds))
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            process.wait(timeout=max(0.2, grace_seconds * 4))
        except subprocess.TimeoutExpired:
            # The descriptor cleanup below still bounds this helper.  The
            # caller records the process as incomplete rather than claiming a
            # successful snapshot.
            pass


def _run_bounded(
    argv: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    deadline: float,
    max_output_bytes: int,
    max_stderr_bytes: int,
) -> dict[str, Any]:
    """Run one command while continuously draining both pipes.

    ``communicate(timeout=...)`` is insufficient here: a child that exits
    while a descendant keeps stdout open can leave the caller waiting, and a
    large stderr stream can block a child before communicate is reached.  The
    selector loop drains both streams and owns the process group on timeout.
    """
    started = time.monotonic()
    try:
        process = subprocess.Popen(
            list(argv),
            cwd=str(cwd),
            env=dict(env),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except (OSError, ValueError) as exc:
        return {
            "outcome": "ERROR",
            "returncode": None,
            "stdout": b"",
            "stderr_tail": b"",
            "stdout_bytes": 0,
            "stderr_bytes": 0,
            "stderr_truncated": False,
            "error": {"type": type(exc).__name__, "message": str(exc)},
            "elapsed_seconds": max(0.0, time.monotonic() - started),
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

    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                outcome = "TIMEOUT"
                failure = {"timeout_seconds": None}
                _terminate_group(process)
                break
            events = selector.select(min(remaining, 0.05))
            if not events:
                # A process may have exited while an owned descendant still
                # holds a pipe.  Keep draining until EOF or the same deadline.
                continue
            for key, _mask in events:
                fileobj = key.fileobj
                fd = fileobj.fileno()
                label = streams[fd][1]
                while True:
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
                            failure = {
                                "max_output_bytes": max_output_bytes,
                                "observed_output_bytes": stdout_bytes,
                            }
                            _terminate_group(process)
                            break
                        stdout.extend(chunk)
                    else:
                        stderr_bytes += len(chunk)
                        if len(stderr) < max_stderr_bytes:
                            take = min(len(chunk), max_stderr_bytes - len(stderr))
                            stderr.extend(chunk[:take])
                        if stderr_bytes > max_stderr_bytes:
                            stderr_truncated = True
                    if outcome != "OK":
                        break
                if outcome != "OK":
                    break
            if outcome != "OK":
                break
    finally:
        # On a normal path the selector has seen EOF.  On failure, close local
        # descriptors even if a non-cooperative external descendant remains.
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

    try:
        returncode = process.wait(timeout=max(0.0, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        if outcome == "OK":
            outcome = "TIMEOUT"
            failure = {"timeout_seconds": None, "process_wait": True}
        _terminate_group(process)
        returncode = process.poll()

    if outcome == "OK" and returncode != 0:
        outcome = "ERROR"
        failure = {"returncode": returncode}
    if failure is not None:
        failure["stderr_tail"] = bytes(stderr).decode("utf-8", "replace")[-4096:]

    return {
        "outcome": outcome,
        "returncode": returncode,
        "stdout": bytes(stdout),
        "stderr_tail": bytes(stderr),
        "stdout_bytes": stdout_bytes,
        "stderr_bytes": stderr_bytes,
        "stderr_truncated": stderr_truncated,
        "error": failure,
        "elapsed_seconds": max(0.0, time.monotonic() - started),
    }


def _base_report(root: Path, *, timeout_seconds: float, scope: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "status": "ERROR",
        "root": str(root),
        "scope": scope,
        "commit": None,
        "status_porcelain": None,
        "status_porcelain_sha256": None,
        "status_porcelain_bytes": None,
        "diff_sha256": None,
        "diff_bytes": None,
        "optional_locks": False,
        "timeout_seconds": float(timeout_seconds),
        "commands": [],
        "error": None,
    }


def bounded_git_launch_state(
    root: str | os.PathLike[str],
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    input_paths: Iterable[str] | None = None,
    git_executable: str | os.PathLike[str] = "git",
) -> dict[str, Any]:
    """Return a bounded Git snapshot or an explicit non-success state.

    All three commands share one deadline.  On any non-OK outcome, the
    scientific fields remain ``None``; command-level evidence still records
    which bounded observation failed.  The environment explicitly disables
    Git's optional index-lock writes.
    """
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
        raise ValueError("timeout_seconds must be numeric")
    if float(timeout_seconds) <= 0:
        raise ValueError("timeout_seconds must be positive")
    if isinstance(max_output_bytes, bool) or not isinstance(max_output_bytes, int) or max_output_bytes <= 0:
        raise ValueError("max_output_bytes must be a positive integer")
    paths = _normalize_input_paths(input_paths)
    path = Path(root).expanduser()
    if not path.is_dir():
        raise ValueError("Git root must be an existing directory")
    path = path.resolve()
    scope = {
        "mode": "INPUT_SCOPE_ONLY" if paths is not None else "FULL_WORKTREE",
        "input_paths": paths or [],
        "full_worktree_claim": paths is None,
    }
    report = _base_report(path, timeout_seconds=float(timeout_seconds), scope=scope)
    environment = os.environ.copy()
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    environment.setdefault("LC_ALL", "C")
    executable = os.fspath(git_executable)
    suffix = ["--"] + paths if paths is not None else []
    commands = [
        [executable, "rev-parse", "--verify", "HEAD"],
        [executable, "status", "--porcelain=v1", "--untracked-files=all", *suffix],
        [executable, "diff", "--no-ext-diff", "--unified=0", "HEAD", *suffix],
    ]
    deadline = time.monotonic() + float(timeout_seconds)
    results: list[dict[str, Any]] = []
    for argv in commands:
        result = _run_bounded(
            argv,
            cwd=path,
            env=environment,
            deadline=deadline,
            max_output_bytes=max_output_bytes,
            max_stderr_bytes=DEFAULT_MAX_STDERR_BYTES,
        )
        results.append({
            "argv": list(argv),
            "outcome": result["outcome"],
            "returncode": result["returncode"],
            "stdout_bytes": result["stdout_bytes"],
            "stderr_bytes": result["stderr_bytes"],
            "stderr_truncated": result["stderr_truncated"],
            "elapsed_seconds": result["elapsed_seconds"],
            "error": result["error"],
        })
        if result["outcome"] != "OK":
            report["commands"] = results
            report["status"] = result["outcome"]
            report["error"] = {
                "command_index": len(results) - 1,
                "argv": list(argv),
                "detail": result["error"],
            }
            return report
        report["commands"] = results
        if len(results) == 1:
            commit = result["stdout"].decode("utf-8", "replace").strip()
            if not commit or any(character.isspace() for character in commit):
                report["status"] = "ERROR"
                report["error"] = {"command_index": 0, "message": "rev-parse returned invalid HEAD"}
                return report
            report["commit"] = commit
        elif len(results) == 2:
            status_bytes = result["stdout"]
            report["status_porcelain"] = status_bytes.decode("utf-8", "replace")
            report["status_porcelain_sha256"] = _sha256_bytes(status_bytes)
            report["status_porcelain_bytes"] = len(status_bytes)
        else:
            diff_bytes = result["stdout"]
            report["diff_sha256"] = _sha256_bytes(diff_bytes)
            report["diff_bytes"] = len(diff_bytes)
    report["status"] = "OK"
    report["environment"] = {"GIT_OPTIONAL_LOCKS": "0", "LC_ALL": environment.get("LC_ALL")}
    return report


git_launch_state = bounded_git_launch_state


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--max-output-bytes", type=int, default=DEFAULT_MAX_OUTPUT_BYTES)
    parser.add_argument("--input-path", action="append", dest="input_paths")
    parser.add_argument("--git-executable", default="git")
    args = parser.parse_args(argv)
    try:
        result = bounded_git_launch_state(
            args.root,
            timeout_seconds=args.timeout_seconds,
            max_output_bytes=args.max_output_bytes,
            input_paths=args.input_paths,
            git_executable=args.git_executable,
        )
    except (OSError, ValueError) as exc:
        result = {
            "schema": SCHEMA,
            "status": "ERROR",
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("status") == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
