#!/usr/bin/env python3
"""Run one native preflight command inside an already-created systemd scope.

The wrapper stays in the transient scope after its child exits so it can record
the scope's cgroup-v2 peak, OOM counters, and sampled aggregate RSS before the
scope disappears. It has no solver, queue, training, or retry behavior.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Any


def cgroup_v2_directory(
    proc_cgroup: Path = Path("/proc/self/cgroup"),
    cgroup_root: Path = Path("/sys/fs/cgroup"),
) -> Path:
    lines = Path(proc_cgroup).read_text(encoding="utf-8").splitlines()
    unified = [line[3:] for line in lines if line.startswith("0::")]
    if len(unified) != 1:
        raise RuntimeError("process is not in one unified cgroup-v2 hierarchy")
    relative = Path(unified[0].lstrip("/"))
    if relative.is_absolute() or ".." in relative.parts:
        raise RuntimeError("process cgroup path is not a safe relative path")
    root = Path(cgroup_root).resolve()
    directory = (root / relative).resolve()
    try:
        directory.relative_to(root)
    except ValueError as error:
        raise RuntimeError("process cgroup path escapes the cgroup-v2 mount") from error
    return directory


def _read_int(path: Path) -> int:
    value = Path(path).read_text(encoding="ascii").strip()
    if not value.isdecimal():
        raise RuntimeError(f"expected an integer cgroup value: {path}")
    return int(value)


def _read_events(path: Path) -> dict[str, int]:
    result: dict[str, int] = {}
    for line in Path(path).read_text(encoding="ascii").splitlines():
        name, value = line.split()
        if not value.isdecimal() or name in result:
            raise RuntimeError("cgroup memory.events is malformed")
        result[name] = int(value)
    required = {"low", "high", "max", "oom", "oom_kill"}
    if not required.issubset(result):
        raise RuntimeError("cgroup memory.events lacks required counters")
    return result


def _cgroup_pids(cgroup: Path) -> list[int]:
    pids: list[int] = []
    for line in (cgroup / "cgroup.procs").read_text(encoding="ascii").splitlines():
        if not line.isdecimal() or int(line) <= 0:
            raise RuntimeError("cgroup.procs contains a malformed PID")
        pids.append(int(line))
    return pids


def _sample_cgroup_rss(cgroup: Path, proc_root: Path = Path("/proc")) -> int:
    total_pages = 0
    for pid in _cgroup_pids(cgroup):
        try:
            fields = (Path(proc_root) / str(pid) / "statm").read_text().split()
            resident_pages = int(fields[1])
        except (FileNotFoundError, ProcessLookupError):
            continue
        except (IndexError, ValueError) as error:
            raise RuntimeError(f"cannot parse RSS for cgroup process {pid}") from error
        if resident_pages < 0:
            raise RuntimeError("process RSS page count is negative")
        total_pages += resident_pages
    return total_pages * os.sysconf("SC_PAGE_SIZE")


def collect_metrics(
    cgroup: Path,
    *,
    sampled_peak_rss_bytes: int,
    sample_count: int,
    expected_memory_max_bytes: int,
    cgroup_root: Path = Path("/sys/fs/cgroup"),
) -> dict[str, Any]:
    memory_max = _read_int(cgroup / "memory.max")
    memory_peak = _read_int(cgroup / "memory.peak")
    memory_current = _read_int(cgroup / "memory.current")
    events = _read_events(cgroup / "memory.events")
    if memory_max != expected_memory_max_bytes:
        raise RuntimeError(
            f"cgroup memory.max mismatch: expected {expected_memory_max_bytes}, observed {memory_max}"
        )
    if memory_peak > memory_max:
        raise RuntimeError("cgroup memory.peak exceeds the registered MemoryMax")
    root = Path(cgroup_root).resolve()
    try:
        relative_cgroup = Path(cgroup).resolve().relative_to(root)
    except ValueError as error:
        raise RuntimeError("cgroup path is outside the cgroup-v2 mount") from error
    pressure = events["high"] > 0 or events["max"] > 0
    return {
        "cgroup_v2": True,
        "cgroup_path": "/" + str(relative_cgroup),
        "memory_max_bytes": memory_max,
        "memory_peak_bytes": memory_peak,
        "memory_current_bytes_at_exit": memory_current,
        "memory_events": events,
        "sampled_cgroup_process_rss_peak_bytes": sampled_peak_rss_bytes,
        "rss_sample_count": sample_count,
        "cap_pressure_observed": pressure,
        "oom_observed": events["oom"] > 0 or events["oom_kill"] > 0 or events.get("oom_group_kill", 0) > 0,
    }


def _write_exclusive(path: Path, value: dict[str, Any]) -> None:
    path = Path(path)
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable scoped-command receipt: {path}")
    partial = path.with_name(path.name + ".partial")
    payload = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    descriptor = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(partial, path)
    directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _terminate_process_group(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def _terminate_residual_scope_processes(cgroup: Path) -> list[int]:
    """Stop payload descendants that outlive their direct parent, never this wrapper."""
    own_pid = os.getpid()
    residual = [pid for pid in _cgroup_pids(cgroup) if pid != own_pid]
    for pid in residual:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        residual = [pid for pid in _cgroup_pids(cgroup) if pid != own_pid]
        if not residual:
            return []
        time.sleep(0.05)
    for pid in residual:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        residual = [pid for pid in _cgroup_pids(cgroup) if pid != own_pid]
        if not residual:
            return []
        time.sleep(0.05)
    return residual


def run_payload(
    argv: list[str],
    *,
    cwd: Path,
    metrics_json: Path,
    timeout_seconds: float,
    expected_memory_max_bytes: int,
    sample_interval_seconds: float = 0.2,
    cgroup_root: Path = Path("/sys/fs/cgroup"),
) -> dict[str, Any]:
    if not argv or any(not isinstance(item, str) for item in argv):
        raise ValueError("native payload argv must be a nonempty string list")
    if timeout_seconds <= 0 or sample_interval_seconds <= 0:
        raise ValueError("timeout and sample interval must be positive")
    if Path(metrics_json).exists() or Path(metrics_json).is_symlink():
        raise FileExistsError("refusing to overwrite scoped-command metrics")
    cgroup = cgroup_v2_directory()
    initial_max = _read_int(cgroup / "memory.max")
    if initial_max != expected_memory_max_bytes:
        raise RuntimeError("native payload is not in the exact registered MemoryMax scope")

    environment = os.environ.copy()
    environment.update({
        "CUDA_VISIBLE_DEVICES": "",
        "NVIDIA_VISIBLE_DEVICES": "void",
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
    })
    available_cpus = sorted(os.sched_getaffinity(0))
    if not available_cpus:
        raise RuntimeError("no CPU is available for the native child")
    assigned_cpu = available_cpus[0]

    def pin_native_child() -> None:
        os.sched_setaffinity(0, {assigned_cpu})

    process = subprocess.Popen(
        argv, cwd=str(cwd), env=environment, start_new_session=True,
        preexec_fn=pin_native_child,
    )
    sampled_peak = 0
    samples = 0
    timed_out = False
    start = time.monotonic()
    try:
        while process.poll() is None:
            sampled_peak = max(sampled_peak, _sample_cgroup_rss(cgroup))
            samples += 1
            if time.monotonic() - start >= timeout_seconds:
                timed_out = True
                _terminate_process_group(process)
                break
            time.sleep(sample_interval_seconds)
        return_code = int(process.wait())
    except BaseException:
        _terminate_process_group(process)
        _terminate_residual_scope_processes(cgroup)
        raise
    residual_pids = _terminate_residual_scope_processes(cgroup)
    sampled_peak = max(sampled_peak, _sample_cgroup_rss(cgroup))
    samples += 1
    metrics = collect_metrics(
        cgroup,
        sampled_peak_rss_bytes=sampled_peak,
        sample_count=samples,
        expected_memory_max_bytes=expected_memory_max_bytes,
        cgroup_root=cgroup_root,
    )
    result = {
        "schema": "core.cfd.f8.r008_scoped_native_command.v1",
        "child_argv": argv,
        "working_directory": str(Path(cwd).resolve()),
        "child_return_code": return_code,
        "timed_out": timed_out,
        "native_child_single_cpu_affinity_requested": True,
        "native_child_cpu_id": assigned_cpu,
        "residual_scope_pids_after_cleanup": residual_pids,
        "scope_process_tree_clean": not residual_pids,
        "wall_seconds": time.monotonic() - start,
        "metrics": metrics,
    }
    _write_exclusive(Path(metrics_json), result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metrics-json", type=Path, required=True)
    parser.add_argument("--working-directory", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, required=True)
    parser.add_argument("--memory-max-bytes", type=int, required=True)
    parser.add_argument("payload", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    payload = list(args.payload)
    if payload and payload[0] == "--":
        payload = payload[1:]
    result = run_payload(
        payload,
        cwd=args.working_directory,
        metrics_json=args.metrics_json,
        timeout_seconds=args.timeout_seconds,
        expected_memory_max_bytes=args.memory_max_bytes,
    )
    print(json.dumps({"child_return_code": result["child_return_code"], "metrics": result["metrics"]}, sort_keys=True))
    return int(result["child_return_code"] if not result["timed_out"] else 124)


if __name__ == "__main__":
    raise SystemExit(main())
