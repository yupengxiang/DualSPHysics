#!/usr/bin/env python3
"""Plan bounded F3 diagnostic rollouts using shared GPU VRAM.

The planner treats GPU memory as a shareable resource.  It never assumes that
an occupied device is unavailable: a job is admitted when its declared peak
VRAM plus the reserved safety headroom fits in the observed free memory.  The
default command is a dry-run.  An explicit execute mode starts only jobs in a
fresh output namespace and always injects ``--diagnostic`` into the recorded
command contract.

This module is a launch planner, not a qualification path.  It does not open
Core HDF5, manifests, checkpoints, trajectories, or progress files; the
source and output paths are declarations bound by the caller.  It never writes
registry, completion, denominator, ledger, or gate state.  Every plan is
permanently diagnostic-only with zero formal credit.
"""
from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any


SCHEMA = "core.f3.vram_batch_plan.v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CSV_QUERY = (
    "index,memory.used,memory.free,memory.total,utilization.gpu"
)
EXPECTED_TRANSITIONS = 835


class PlannerError(ValueError):
    """A malformed or unsafe diagnostic planning input."""


def _fail(message: str) -> None:
    raise PlannerError(f"fail-closed: {message}")


def _reject_json_constant(token: str) -> None:
    _fail(f"non-finite JSON constant is not allowed: {token}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _check_finite_json(value: Any, *, name: str = "value") -> None:
    if value is None or isinstance(value, (bool, str, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            _fail(f"{name} contains a non-finite number")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                _fail(f"{name} contains a non-string object key")
            _check_finite_json(item, name=f"{name}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _check_finite_json(item, name=f"{name}[{index}]")
        return
    _fail(f"{name} contains unsupported value {type(value).__name__}")


def canonical_json(value: Any) -> str:
    """Return deterministic JSON while rejecting non-finite values."""
    _check_finite_json(value)
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{name} must be an object")
    return value


def _string(value: Any, name: str, *, nonempty: bool = True) -> str:
    if not isinstance(value, str) or "\x00" in value or (nonempty and not value):
        _fail(f"{name} must be a {'non-empty ' if nonempty else ''}string without NUL")
    return value


def _integer(value: Any, name: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        _fail(f"{name} must be an integer >= {minimum}")
    return value


def _sha256(value: Any, name: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        _fail(f"{name} must be 64 lowercase hexadecimal characters")
    return value


def _absolute_path(value: Any, name: str) -> str:
    path = _string(value, name)
    if not os.path.isabs(path):
        _fail(f"{name} must be absolute")
    if any(part == ".." for part in Path(path).parts):
        _fail(f"{name} must not contain a parent traversal")
    return path


@dataclass(frozen=True)
class GpuSnapshot:
    index: int
    memory_used_mib: int
    memory_free_mib: int
    memory_total_mib: int
    utilization_gpu_pct: int

    @property
    def stable_free_mib(self) -> int:
        return self.memory_free_mib

    def as_dict(self) -> dict[str, int]:
        return {
            "index": self.index,
            "memory_used_mib": self.memory_used_mib,
            "memory_free_mib": self.memory_free_mib,
            "memory_total_mib": self.memory_total_mib,
            "utilization_gpu_pct": self.utilization_gpu_pct,
        }


def parse_nvidia_smi_csv(text: str) -> tuple[GpuSnapshot, ...]:
    """Parse the fixed nvidia-smi CSV query used by the launcher."""
    snapshots: list[GpuSnapshot] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        fields = [field.strip() for field in line.split(",")]
        if len(fields) != 5:
            _fail(f"nvidia-smi line {line_number} must contain five fields")
        try:
            values = [int(field) for field in fields]
        except ValueError as error:
            _fail(f"nvidia-smi line {line_number} has non-integer fields: {error}")
        index, used, free, total, utilization = values
        if index < 0 or used < 0 or free < 0 or total <= 0 or utilization < 0 or utilization > 100:
            _fail(f"nvidia-smi line {line_number} has invalid resource values")
        if used + free > total:
            _fail(f"nvidia-smi line {line_number} used+free exceeds total")
        snapshots.append(GpuSnapshot(index, used, free, total, utilization))
    if not snapshots:
        _fail("nvidia-smi returned no GPUs")
    if len({snapshot.index for snapshot in snapshots}) != len(snapshots):
        _fail("nvidia-smi returned duplicate GPU indices")
    return tuple(sorted(snapshots, key=lambda snapshot: snapshot.index))


def query_nvidia_smi(*, runner=subprocess.run) -> tuple[GpuSnapshot, ...]:
    """Read one atomic GPU memory snapshot without changing process state."""
    try:
        completed = runner(
            [
                "nvidia-smi",
                f"--query-gpu={CSV_QUERY}",
                "--format=csv,noheader,nounits",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        _fail(f"nvidia-smi query failed: {error}")
    return parse_nvidia_smi_csv(completed.stdout)


def _validate_argv(argv: Any, name: str) -> tuple[str, ...]:
    if not isinstance(argv, Sequence) or isinstance(argv, (str, bytes)) or not argv:
        _fail(f"{name} must be a non-empty string array")
    result = tuple(_string(item, f"{name}[{index}]") for index, item in enumerate(argv))
    if "--diagnostic" not in result:
        _fail(f"{name} must include --diagnostic")
    if "--maximum-steps" in result:
        position = result.index("--maximum-steps")
        if position + 1 >= len(result) or result[position + 1] != str(EXPECTED_TRANSITIONS):
            _fail(f"{name} must bind --maximum-steps {EXPECTED_TRANSITIONS}")
    return result


def validate_job(job: Mapping[str, Any], *, index: int = 0) -> dict[str, Any]:
    """Validate and normalize one source-bound diagnostic launch declaration."""
    job_name = f"jobs[{index}]"
    job_id = _string(job.get("job_id"), f"{job_name}.job_id")
    if "/" in job_id or "\\" in job_id:
        _fail(f"{job_name}.job_id must not contain path separators")
    model = _string(job.get("model"), f"{job_name}.model")
    case_id = _string(job.get("case_id"), f"{job_name}.case_id")
    seed = _integer(job.get("seed"), f"{job_name}.seed")
    manifest_path = _absolute_path(job.get("manifest_path"), f"{job_name}.manifest_path")
    checkpoint_path = _absolute_path(
        job.get("checkpoint_path"), f"{job_name}.checkpoint_path"
    )
    cwd = _absolute_path(job.get("cwd"), f"{job_name}.cwd")
    manifest_sha256 = _sha256(job.get("manifest_sha256"), f"{job_name}.manifest_sha256")
    checkpoint_sha256 = _sha256(
        job.get("checkpoint_sha256"), f"{job_name}.checkpoint_sha256"
    )
    argv = _validate_argv(job.get("argv"), f"{job_name}.argv")
    output_paths_value = job.get("output_paths")
    if (
        not isinstance(output_paths_value, Sequence)
        or isinstance(output_paths_value, (str, bytes))
        or not output_paths_value
    ):
        _fail(f"{job_name}.output_paths must be a non-empty string array")
    output_paths = tuple(
        _absolute_path(value, f"{job_name}.output_paths[{path_index}]")
        for path_index, value in enumerate(output_paths_value)
    )
    estimated_vram_mib = _integer(
        job.get("estimated_vram_mib"), f"{job_name}.estimated_vram_mib", minimum=1
    )
    cpu_slots = _integer(job.get("cpu_slots", 1), f"{job_name}.cpu_slots", minimum=1)
    normalized = {
        "job_id": job_id,
        "model": model,
        "seed": seed,
        "case_id": case_id,
        "manifest_path": manifest_path,
        "manifest_sha256": manifest_sha256,
        "checkpoint_path": checkpoint_path,
        "checkpoint_sha256": checkpoint_sha256,
        "cwd": cwd,
        "argv": list(argv),
        "output_paths": list(output_paths),
        "estimated_vram_mib": estimated_vram_mib,
        "cpu_slots": cpu_slots,
    }
    return normalized


def _validate_jobs(jobs: Any) -> list[dict[str, Any]]:
    if not isinstance(jobs, Sequence) or isinstance(jobs, (str, bytes)) or not jobs:
        _fail("jobs must be a non-empty array")
    normalized = [validate_job(_mapping(job, f"jobs[{index}]"), index=index)
                  for index, job in enumerate(jobs)]
    ids = [job["job_id"] for job in normalized]
    if len(set(ids)) != len(ids):
        _fail("job_id values must be unique")
    output_paths = [path for job in normalized for path in job["output_paths"]]
    if len(set(output_paths)) != len(output_paths):
        _fail("output_paths must be globally unique")
    pairs = [(job["model"], job["seed"], job["case_id"]) for job in normalized]
    if len(set(pairs)) != len(pairs):
        _fail("model/seed/case combinations must be unique")
    return sorted(normalized, key=lambda job: job["job_id"])


def plan_jobs(
    jobs: Sequence[Mapping[str, Any]],
    gpus: Sequence[GpuSnapshot],
    *,
    min_free_mib: int = 8192,
    max_cpu_slots: int | None = None,
) -> dict[str, Any]:
    """Assign jobs to shared GPUs using reserved VRAM and CPU headroom."""
    min_free_mib = _integer(min_free_mib, "min_free_mib", minimum=1)
    if not gpus:
        _fail("at least one GPU snapshot is required")
    if max_cpu_slots is not None:
        max_cpu_slots = _integer(max_cpu_slots, "max_cpu_slots", minimum=1)
    normalized_jobs = _validate_jobs(list(jobs))
    snapshots = sorted(gpus, key=lambda snapshot: snapshot.index)
    if len({snapshot.index for snapshot in snapshots}) != len(snapshots):
        _fail("GPU snapshot indices must be unique")
    reservations = {snapshot.index: 0 for snapshot in snapshots}
    cpu_reserved = 0
    planned: list[dict[str, Any]] = []
    for job in normalized_jobs:
        candidates = []
        for snapshot in snapshots:
            remaining = snapshot.stable_free_mib - reservations[snapshot.index]
            if remaining < min_free_mib + job["estimated_vram_mib"]:
                continue
            if max_cpu_slots is not None and cpu_reserved + job["cpu_slots"] > max_cpu_slots:
                continue
            candidates.append((remaining, snapshot.index))
        if not candidates:
            planned.append({
                **job,
                "status": "blocked_resource_headroom",
                "gpu_index": None,
                "reserved_after_mib": None,
                "reason": "no GPU/CPU assignment satisfies the frozen headroom policy",
            })
            continue
        _, gpu_index = max(candidates, key=lambda item: (item[0], -item[1]))
        reservations[gpu_index] += job["estimated_vram_mib"]
        cpu_reserved += job["cpu_slots"]
        planned.append({
            **job,
            "status": "planned",
            "gpu_index": gpu_index,
            "reserved_after_mib": reservations[gpu_index],
            "reason": "declared peak VRAM fits observed free memory and headroom",
        })
    return {
        "schema": SCHEMA,
        "planner_policy": {
            "min_free_mib": min_free_mib,
            "max_cpu_slots": max_cpu_slots,
            "gpu_is_shareable": True,
            "assignment_uses_free_memory_not_idle_state": True,
            "default_mode": "dry_run",
        },
        "gpu_snapshot": [snapshot.as_dict() for snapshot in snapshots],
        "jobs": planned,
        "summary": {
            "job_count": len(planned),
            "planned_count": sum(job["status"] == "planned" for job in planned),
            "blocked_count": sum(job["status"] != "planned" for job in planned),
            "reserved_vram_mib_by_gpu": {
                str(index): reservations[index] for index in sorted(reservations)
            },
            "reserved_cpu_slots": cpu_reserved,
        },
        "diagnostic_only": True,
        "formal_eligible": False,
        "formal": False,
        "qualification": False,
        "qualification_credit": 0,
        "credit": 0,
        "registry_mutation": 0,
        "ledger_mutation": 0,
        "gate_mutation": 0,
    }


def _safe_output_paths(job: Mapping[str, Any]) -> None:
    for path_value in job["output_paths"]:
        path = Path(path_value)
        if path.exists():
            _fail(f"refusing to overwrite existing output: {path}")


def execute_plan(plan: Mapping[str, Any], *, allow_diagnostic_execute: bool = False) -> list[dict[str, Any]]:
    """Start only explicitly admitted jobs, returning process metadata.

    The caller must opt in with ``allow_diagnostic_execute``.  This function
    still refuses blocked jobs, formal-looking commands, duplicate namespaces,
    and existing output paths.
    """
    if not allow_diagnostic_execute:
        _fail("execution requires explicit diagnostic opt-in")
    if plan.get("diagnostic_only") is not True or plan.get("formal") is not False:
        _fail("plan is not permanently diagnostic-only")
    results: list[dict[str, Any]] = []
    for job in plan.get("jobs", []):
        if job.get("status") != "planned":
            continue
        argv = _validate_argv(job.get("argv"), f"job {job.get('job_id')}.argv")
        _safe_output_paths(job)
        if "--diagnostic" not in argv:
            _fail(f"job {job.get('job_id')} lost --diagnostic before launch")
        log_path = Path(job["output_paths"][0]).with_suffix(".launch.log")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        environment = os.environ.copy()
        environment.update({
            "CUDA_VISIBLE_DEVICES": str(job["gpu_index"]),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUNBUFFERED": "1",
        })
        with log_path.open("xb") as log_file:
            process = subprocess.Popen(
                list(argv),
                cwd=job["cwd"],
                env=environment,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        results.append({
            "job_id": job["job_id"],
            "gpu_index": job["gpu_index"],
            "pid": process.pid,
            "log_path": str(log_path),
            "diagnostic_only": True,
        })
    return results


def _read_json(path: str | Path) -> Any:
    report_path = Path(path)
    try:
        raw = report_path.read_bytes()
        value = json.loads(
            raw.decode("utf-8"),
            parse_constant=_reject_json_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, PlannerError) as error:
        _fail(f"cannot read strict JSON {report_path}: {error}")
    _check_finite_json(value, name="input")
    return value


def _write_canonical(path: str | Path, value: Mapping[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(canonical_json(value) + "\n", encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", required=True, help="JSON object or array containing launch declarations")
    parser.add_argument("--gpu-snapshot", help="JSON array of GPU snapshot objects; defaults to nvidia-smi")
    parser.add_argument("--min-free-mib", type=int, default=8192)
    parser.add_argument("--max-cpu-slots", type=int)
    parser.add_argument("--output", required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--allow-diagnostic-execute", action="store_true")
    return parser


def _snapshots_from_json(value: Any) -> tuple[GpuSnapshot, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        _fail("gpu snapshot JSON must be an array")
    snapshots = []
    for index, raw in enumerate(value):
        mapping = _mapping(raw, f"gpu_snapshot[{index}]")
        snapshots.append(GpuSnapshot(
            _integer(mapping.get("index"), f"gpu_snapshot[{index}].index"),
            _integer(mapping.get("memory_used_mib"), f"gpu_snapshot[{index}].memory_used_mib"),
            _integer(mapping.get("memory_free_mib"), f"gpu_snapshot[{index}].memory_free_mib"),
            _integer(mapping.get("memory_total_mib"), f"gpu_snapshot[{index}].memory_total_mib", minimum=1),
            _integer(mapping.get("utilization_gpu_pct"), f"gpu_snapshot[{index}].utilization_gpu_pct"),
        ))
    return tuple(snapshots)


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        raw_jobs = _read_json(args.jobs)
        if isinstance(raw_jobs, Mapping):
            raw_jobs = raw_jobs.get("jobs")
        if args.gpu_snapshot:
            snapshots = _snapshots_from_json(_read_json(args.gpu_snapshot))
        else:
            snapshots = query_nvidia_smi()
        plan = plan_jobs(
            raw_jobs,
            snapshots,
            min_free_mib=args.min_free_mib,
            max_cpu_slots=args.max_cpu_slots,
        )
        if args.execute:
            if not args.allow_diagnostic_execute:
                _fail("--execute requires --allow-diagnostic-execute")
            plan = dict(plan)
            plan["launches"] = execute_plan(
                plan, allow_diagnostic_execute=args.allow_diagnostic_execute
            )
        _write_canonical(args.output, plan)
    except PlannerError as error:
        print(str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
