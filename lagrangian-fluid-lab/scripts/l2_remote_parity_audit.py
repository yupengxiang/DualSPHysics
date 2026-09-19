#!/usr/bin/env python3
"""Read-only local/H200 parity and GPU availability audit.

The audit is intentionally an observation boundary.  It reads local Git
metadata, asks the configured SSH host for Git metadata and ``nvidia-smi``
inventory, and emits a standalone report.  It never runs a solver, changes a
remote checkout, or updates the L2-R resume state.

The remote probe contains only ``cd``, ``git rev-parse``, ``git status``, and
read-only ``nvidia-smi --query-*`` commands.  A follow-up synchronization plan
is included in the report, but those commands are advisory and are never
executed by this module.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shlex
import subprocess
import sys
from typing import Any, Callable, Iterable, Sequence


SCHEMA = "l2r.remote-parity-audit.v1"
DEFAULT_ALIAS = "h200-deepdebris"
DEFAULT_REMOTE_ROOT = "/home/jade/Projects/DualSPHysics"
REQUIRED_GPU_INDICES = (0, 2, 3)
PROTECTED_GPU_INDEX = 1
DEFAULT_CONNECT_TIMEOUT_S = 10
DEFAULT_COMMAND_TIMEOUT_S = 30
DEFAULT_IDLE_MEMORY_MIB = 1024

_PROBE_MARKERS = {
    "probe": ("__L2R_REMOTE_PROBE_V1__", "__L2R_REMOTE_PROBE_END__"),
    "head": ("__L2R_GIT_HEAD_BEGIN__", "__L2R_GIT_HEAD_END__"),
    "branch": ("__L2R_GIT_BRANCH_BEGIN__", "__L2R_GIT_BRANCH_END__"),
    "status": ("__L2R_GIT_STATUS_BEGIN__", "__L2R_GIT_STATUS_END__"),
    "gpu": ("__L2R_GPU_BEGIN__", "__L2R_GPU_END__"),
    "process": ("__L2R_PROCESS_BEGIN__", "__L2R_PROCESS_END__"),
}


@dataclass(frozen=True)
class CommandResult:
    """Small subprocess result used to keep collection functions mockable."""

    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


Runner = Callable[..., CommandResult]


def _run_command(
    args: Sequence[str],
    *,
    cwd: Path | None = None,
    timeout_s: int = DEFAULT_COMMAND_TIMEOUT_S,
) -> CommandResult:
    """Run one command without a shell and return its captured output."""

    normalized = tuple(str(item) for item in args)
    try:
        completed = subprocess.run(
            list(normalized),
            cwd=str(cwd) if cwd is not None else None,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode(errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="replace")
        return CommandResult(normalized, 124, stdout, stderr, timed_out=True)
    except OSError as exc:
        return CommandResult(normalized, 127, "", str(exc), timed_out=False)
    return CommandResult(normalized, completed.returncode, completed.stdout, completed.stderr)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _clean_lines(text: str) -> list[str]:
    return [line.rstrip("\r") for line in text.splitlines()]


def _first_nonempty(text: str) -> str | None:
    for line in _clean_lines(text):
        if line.strip():
            return line.strip()
    return None


def _parse_status_porcelain(status_text: str) -> dict[str, Any]:
    """Parse ``git status --porcelain=v1 --branch`` without losing paths."""

    lines = _clean_lines(status_text)
    branch_line = next((line for line in lines if line.startswith("## ")), None)
    changes = [line for line in lines if line and not line.startswith("## ")]
    branch: str | None = None
    if branch_line is not None:
        branch = branch_line[3:].strip() or None
        # Keep only the local branch identity before upstream/ahead metadata.
        branch = branch.split("...", 1)[0]
        branch = branch.split(" [", 1)[0]
    return {
        "branch_line": branch_line,
        "branch": branch,
        "changes": changes,
        "dirty": bool(changes),
    }


def _git_snapshot(repo_root: Path, *, runner: Runner = _run_command) -> dict[str, Any]:
    """Collect local or remote-style Git identity and cleanliness metadata."""

    head_result = runner(("git", "rev-parse", "HEAD"), cwd=repo_root, timeout_s=DEFAULT_COMMAND_TIMEOUT_S)
    branch_result = runner(
        ("git", "symbolic-ref", "--quiet", "--short", "HEAD"),
        cwd=repo_root,
        timeout_s=DEFAULT_COMMAND_TIMEOUT_S,
    )
    status_result = runner(
        ("git", "status", "--porcelain=v1", "--branch"),
        cwd=repo_root,
        timeout_s=DEFAULT_COMMAND_TIMEOUT_S,
    )
    status = _parse_status_porcelain(status_result.stdout)
    branch = _first_nonempty(branch_result.stdout) if branch_result.returncode == 0 else None
    if branch is None:
        branch = status.get("branch")
    if branch is None and branch_result.returncode != 0:
        branch = "(detached-or-unavailable)"
    head = _first_nonempty(head_result.stdout) if head_result.returncode == 0 else None
    return {
        "head": head,
        "branch": branch,
        "clean": not status["dirty"] and status_result.returncode == 0,
        "status": status,
        "commands": {
            "head": list(head_result.args),
            "branch": list(branch_result.args),
            "status": list(status_result.args),
        },
        "command_errors": [
            {
                "command": list(result.args),
                "returncode": result.returncode,
                "stderr": result.stderr.strip(),
                "timed_out": result.timed_out,
            }
            for result in (head_result, branch_result, status_result)
            if result.returncode != 0 and not (result is branch_result and result.returncode == 1)
        ],
    }


def parse_gpu_inventory(text: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Parse the no-header ``nvidia-smi --query-gpu`` CSV output."""

    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for line_number, raw in enumerate(_clean_lines(text), start=1):
        if not raw.strip() or raw.lower().startswith("no running"):
            continue
        try:
            fields = next(csv.reader([raw]))
        except csv.Error as exc:
            errors.append(f"gpu_csv_line_{line_number}:{exc}")
            continue
        fields = [field.strip() for field in fields]
        if len(fields) < 6:
            errors.append(f"gpu_csv_line_{line_number}:expected_6_fields_got_{len(fields)}")
            continue
        try:
            index = int(fields[0])
        except ValueError:
            errors.append(f"gpu_csv_line_{line_number}:invalid_index:{fields[0]}")
            continue
        rows.append(
            {
                "index": index,
                "uuid": fields[1],
                "name": fields[2],
                "memory_total_mib": _number_or_none(fields[3]),
                "memory_used_mib": _number_or_none(fields[4]),
                "utilization_gpu_percent": _number_or_none(fields[5]),
            }
        )
    return rows, errors


def parse_process_inventory(
    text: str,
    *,
    uuid_to_index: dict[str, int] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Parse the no-header ``nvidia-smi --query-compute-apps`` CSV output."""

    uuid_to_index = uuid_to_index or {}
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for line_number, raw in enumerate(_clean_lines(text), start=1):
        if not raw.strip() or raw.lower().startswith("no running"):
            continue
        try:
            fields = next(csv.reader([raw]))
        except csv.Error as exc:
            errors.append(f"process_csv_line_{line_number}:{exc}")
            continue
        fields = [field.strip() for field in fields]
        if len(fields) < 4:
            errors.append(f"process_csv_line_{line_number}:expected_4_fields_got_{len(fields)}")
            continue
        pid: int | None
        try:
            pid = int(fields[1])
        except ValueError:
            pid = None
        uuid = fields[0]
        rows.append(
            {
                "gpu_uuid": uuid,
                "gpu_index": uuid_to_index.get(uuid),
                "pid": pid,
                "process_name": fields[2],
                "used_memory_mib": _number_or_none(fields[3]),
            }
        )
    return rows, errors


def _number_or_none(value: str) -> float | int | None:
    value = value.strip()
    if value in {"", "N/A", "Not Supported", "-"}:
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    if not math.isfinite(number):
        return None
    return int(number) if number.is_integer() else number


def assess_gpu_availability(
    gpus: Iterable[dict[str, Any]],
    processes: Iterable[dict[str, Any]],
    *,
    required_indices: Sequence[int] = REQUIRED_GPU_INDICES,
    protected_index: int = PROTECTED_GPU_INDEX,
    idle_memory_mib: int = DEFAULT_IDLE_MEMORY_MIB,
) -> dict[str, Any]:
    """Classify requested GPUs conservatively and protect the existing GPU1 job."""

    required = tuple(required_indices)
    gpu_by_index = {int(gpu["index"]): dict(gpu) for gpu in gpus}
    process_list = [dict(process) for process in processes]
    processes_by_index: dict[int, list[dict[str, Any]]] = {}
    unmapped_processes: list[dict[str, Any]] = []
    for process in process_list:
        index = process.get("gpu_index")
        if index is None:
            unmapped_processes.append(process)
        else:
            processes_by_index.setdefault(int(index), []).append(process)

    availability: dict[str, dict[str, Any]] = {}
    anomalies: list[str] = []
    for index in required:
        gpu = gpu_by_index.get(index)
        attached = processes_by_index.get(index, [])
        reasons: list[str] = []
        if gpu is None:
            reasons.append("gpu_missing_from_inventory")
        else:
            used = gpu.get("memory_used_mib")
            util = gpu.get("utilization_gpu_percent")
            if used is not None and float(used) > idle_memory_mib:
                reasons.append(f"memory_used_above_{idle_memory_mib}_MiB")
            if util is not None and float(util) > 0:
                reasons.append("nonzero_gpu_utilization")
        if attached:
            reasons.append("nvidia_smi_process_present")
        available = gpu is not None and not reasons
        record = {
            "index": index,
            "available_for_new_solver": available,
            "status": "available" if available else "occupied_or_unknown",
            "reasons": reasons,
            "gpu": gpu,
            "processes": attached,
        }
        availability[str(index)] = record
        if not available:
            anomalies.append(f"gpu{index}_not_available_for_new_solver:{','.join(reasons) or 'unknown'}")

    protected_processes = processes_by_index.get(protected_index, [])
    protected_gpu = gpu_by_index.get(protected_index)
    protected = {
        "index": protected_index,
        "must_not_touch": True,
        "existing_task_observed": bool(protected_processes),
        "gpu": protected_gpu,
        "processes": protected_processes,
        "status": "protected_existing_task" if protected_processes else "protected_idle_or_unobserved",
    }
    if not protected_processes:
        anomalies.append("gpu1_existing_task_not_observed; keep_gpu1_protected_anyway")
    if unmapped_processes:
        anomalies.append("nvidia_smi_process_gpu_uuid_unmapped")

    return {
        "required_indices": list(required),
        "availability": availability,
        "all_required_available": all(item["available_for_new_solver"] for item in availability.values())
        and len(availability) == len(required),
        "protected_gpu": protected,
        "all_processes": process_list,
        "unmapped_processes": unmapped_processes,
        "anomalies": anomalies,
        "policy": {
            "idle_memory_threshold_mib": idle_memory_mib,
            "any_nvidia_smi_process_blocks_new_solver": True,
            "gpu1_is_never_a_new_solver_target": True,
        },
    }


def build_remote_probe_command(remote_root: str = DEFAULT_REMOTE_ROOT) -> str:
    """Return the shell snippet used remotely; it performs read-only probes."""

    quoted_root = shlex.quote(remote_root)
    return "\n".join(
        (
            "printf '%s\\n' '__L2R_REMOTE_PROBE_V1__'",
            f"if ! cd -- {quoted_root}; then printf '%s\\n' '__L2R_REMOTE_CD_FAILED__'; exit 41; fi",
            "printf '%s\\n' '__L2R_GIT_HEAD_BEGIN__'",
            "git rev-parse HEAD 2>&1",
            "printf '%s\\n' '__L2R_GIT_HEAD_END__'",
            "printf '%s\\n' '__L2R_GIT_BRANCH_BEGIN__'",
            "git symbolic-ref --quiet --short HEAD 2>&1 || true",
            "printf '%s\\n' '__L2R_GIT_BRANCH_END__'",
            "printf '%s\\n' '__L2R_GIT_STATUS_BEGIN__'",
            "git status --porcelain=v1 --branch 2>&1",
            "printf '%s\\n' '__L2R_GIT_STATUS_END__'",
            "printf '%s\\n' '__L2R_GPU_BEGIN__'",
            "nvidia-smi --query-gpu=index,uuid,name,memory.total,memory.used,utilization.gpu --format=csv,noheader,nounits 2>&1",
            "printf '%s\\n' '__L2R_GPU_END__'",
            "printf '%s\\n' '__L2R_PROCESS_BEGIN__'",
            "nvidia-smi --query-compute-apps=gpu_uuid,pid,process_name,used_memory --format=csv,noheader,nounits 2>&1",
            "printf '%s\\n' '__L2R_PROCESS_END__'",
            "printf '%s\\n' '__L2R_REMOTE_PROBE_END__'",
        )
    )


def _section(text: str, name: str) -> str:
    begin, end = _PROBE_MARKERS[name]
    lines = _clean_lines(text)
    try:
        begin_index = lines.index(begin)
        end_index = lines.index(end, begin_index + 1)
    except ValueError:
        return ""
    return "\n".join(lines[begin_index + 1 : end_index])


def _probe_has_markers(text: str) -> bool:
    return _PROBE_MARKERS["probe"][0] in text and _PROBE_MARKERS["probe"][1] in text


def _ssh_snapshot(
    alias: str,
    remote_root: str,
    *,
    runner: Runner = _run_command,
    connect_timeout_s: int = DEFAULT_CONNECT_TIMEOUT_S,
) -> dict[str, Any]:
    if not alias or alias.startswith("-"):
        raise ValueError("SSH alias must be non-empty and must not start with '-'")
    probe = build_remote_probe_command(remote_root)
    result = runner(
        (
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            f"ConnectTimeout={connect_timeout_s}",
            "--",
            alias,
            probe,
        ),
        timeout_s=connect_timeout_s + DEFAULT_COMMAND_TIMEOUT_S,
    )
    output = result.stdout
    gpu_text = _section(output, "gpu")
    gpus, gpu_errors = parse_gpu_inventory(gpu_text)
    uuid_to_index = {str(gpu["uuid"]): int(gpu["index"]) for gpu in gpus}
    process_text = _section(output, "process")
    processes, process_errors = parse_process_inventory(process_text, uuid_to_index=uuid_to_index)
    status_text = _section(output, "status")
    status = _parse_status_porcelain(status_text)
    branch = _first_nonempty(_section(output, "branch")) or status.get("branch")
    head = _first_nonempty(_section(output, "head"))
    probe_ok = _probe_has_markers(output) and "__L2R_REMOTE_CD_FAILED__" not in output
    errors = list(gpu_errors) + list(process_errors)
    if not _probe_has_markers(output):
        errors.append("remote_probe_markers_missing")
    if "__L2R_REMOTE_CD_FAILED__" in output:
        errors.append("remote_checkout_cd_failed")
    if result.returncode != 0:
        errors.append(f"ssh_returncode_{result.returncode}")
    if result.timed_out:
        errors.append("ssh_probe_timed_out")
    return {
        "alias": alias,
        "root": remote_root,
        "probe_ok": probe_ok,
        "head": head,
        "branch": branch,
        "clean": not status["dirty"] and probe_ok,
        "status": status,
        "gpus": gpus,
        "processes": processes,
        "gpu_inventory_errors": gpu_errors,
        "process_inventory_errors": process_errors,
        "probe_command": list(result.args),
        "probe_returncode": result.returncode,
        "probe_stderr": result.stderr.strip(),
        "probe_errors": errors,
    }


def collect_local_snapshot(repo_root: Path, *, runner: Runner = _run_command) -> dict[str, Any]:
    snapshot = _git_snapshot(repo_root.resolve(), runner=runner)
    return {"root": str(repo_root.resolve()), "git": snapshot}


def collect_remote_snapshot(
    alias: str = DEFAULT_ALIAS,
    remote_root: str = DEFAULT_REMOTE_ROOT,
    *,
    runner: Runner = _run_command,
    connect_timeout_s: int = DEFAULT_CONNECT_TIMEOUT_S,
) -> dict[str, Any]:
    snapshot = _ssh_snapshot(
        alias,
        remote_root,
        runner=runner,
        connect_timeout_s=connect_timeout_s,
    )
    return {"alias": alias, "root": remote_root, "git": snapshot}


def _git_parity(local: dict[str, Any], remote: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    anomalies: list[str] = []
    local_head = local.get("head")
    remote_head = remote.get("head")
    local_branch = local.get("branch")
    remote_branch = remote.get("branch")
    commit_equal = bool(local_head and remote_head and local_head == remote_head)
    branch_equal = bool(local_branch and remote_branch and local_branch == remote_branch)
    clean_equal = bool(local.get("clean") and remote.get("clean"))
    if not commit_equal:
        anomalies.append(f"git_head_mismatch:local={local_head!r}:remote={remote_head!r}")
    if not branch_equal:
        anomalies.append(f"git_branch_mismatch:local={local_branch!r}:remote={remote_branch!r}")
    if not local.get("clean"):
        anomalies.append("local_worktree_dirty")
    if not remote.get("clean"):
        anomalies.append("remote_worktree_dirty_or_probe_failed")
    return (
        {
            "commit_equal": commit_equal,
            "branch_equal": branch_equal,
            "both_clean": clean_equal,
            "parity": commit_equal and branch_equal and clean_equal,
            "local": {
                "head": local_head,
                "branch": local_branch,
                "clean": local.get("clean"),
            },
            "remote": {
                "head": remote_head,
                "branch": remote_branch,
                "clean": remote.get("clean"),
            },
        },
        anomalies,
    )


def _sync_plan(alias: str, remote_root: str, parity: dict[str, Any]) -> dict[str, Any]:
    """Build advisory commands; this function never executes them."""

    commands = [
        "cd /home/jade/Projects/DualSPHysics",
        "git status --short --branch",
        "# Commit only the intended tracked files; do not stage unrelated agent work.",
        "git archive --format=tar HEAD | gzip -1 | ssh h200-deepdebris 'cd /home/jade/Projects/DualSPHysics && tar -xzf -'",
        "rsync -az --delete .git/ h200-deepdebris:/home/jade/Projects/DualSPHysics/.git/",
        "ssh h200-deepdebris 'cd /home/jade/Projects/DualSPHysics && git rev-parse HEAD && git branch --show-current && git status --short --branch'",
    ]
    return {
        "status": "manual_sync_required" if not parity["parity"] else "no_sync_required",
        "executed": False,
        "requires_local_clean_and_intended_commit": True,
        "preserve_gpu1": True,
        "commands": commands,
        "notes": [
            "The commands are advisory and were not run by this audit.",
            f"Use SSH alias {alias!r} and remote checkout {remote_root!r}; do not use another alias.",
            "Do not start a solver on GPU1; retain its existing process and schedule only an explicitly available GPU.",
            "Re-run this audit after synchronization and before any remote experiment.",
        ],
    }


def build_report(
    local: dict[str, Any],
    remote: dict[str, Any],
    *,
    alias: str = DEFAULT_ALIAS,
    remote_root: str = DEFAULT_REMOTE_ROOT,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    """Assemble a serializable report from already-collected snapshots."""

    local_git = local.get("git", {})
    remote_git = remote.get("git", {})
    parity, git_anomalies = _git_parity(local_git, remote_git)
    gpu = assess_gpu_availability(remote_git.get("gpus", []), remote_git.get("processes", []))
    anomalies = list(git_anomalies)
    anomalies.extend(f"remote:{item}" for item in remote_git.get("probe_errors", []))
    anomalies.extend(f"gpu:{item}" for item in gpu["anomalies"])
    return {
        "schema": SCHEMA,
        "generated_at_utc": generated_at_utc or _utc_now(),
        "scope": {
            "read_only": True,
            "remote_modified": False,
            "solver_started": False,
            "shared_resume_state_written": False,
            "local_report_output_is_opt_in": True,
        },
        "parity": parity,
        "local": local,
        "remote": remote,
        "gpu_policy": {
            "requested_indices": list(REQUIRED_GPU_INDICES),
            "protected_index": PROTECTED_GPU_INDEX,
            "protected_index_must_not_be_touched": True,
            "assessment": gpu,
        },
        "anomalies": anomalies,
        "follow_up_sync": _sync_plan(alias, remote_root, parity),
    }


def run_audit(
    repo_root: Path,
    *,
    alias: str = DEFAULT_ALIAS,
    remote_root: str = DEFAULT_REMOTE_ROOT,
    runner: Runner = _run_command,
    connect_timeout_s: int = DEFAULT_CONNECT_TIMEOUT_S,
) -> dict[str, Any]:
    local = collect_local_snapshot(repo_root, runner=runner)
    remote = collect_remote_snapshot(
        alias,
        remote_root,
        runner=runner,
        connect_timeout_s=connect_timeout_s,
    )
    return build_report(local, remote, alias=alias, remote_root=remote_root)


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audit", nargs="?", choices=("audit",), default="audit")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--alias", default=DEFAULT_ALIAS)
    parser.add_argument("--remote-root", default=DEFAULT_REMOTE_ROOT)
    parser.add_argument("--connect-timeout", type=int, default=DEFAULT_CONNECT_TIMEOUT_S)
    parser.add_argument("--output", type=Path, help="Optional standalone local JSON report path")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return 2 when parity or requested GPU availability is not clean",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = run_audit(
            args.repo_root,
            alias=args.alias,
            remote_root=args.remote_root,
            connect_timeout_s=args.connect_timeout,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({"schema": SCHEMA, "error": str(exc)}, indent=2), file=sys.stderr)
        return 2
    if args.output is not None:
        _write_report(args.output, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    if args.strict and (
        not report["parity"]["parity"]
        or not report["gpu_policy"]["assessment"]["all_required_available"]
    ):
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
