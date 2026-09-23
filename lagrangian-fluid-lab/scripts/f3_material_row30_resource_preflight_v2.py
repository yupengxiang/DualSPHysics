#!/usr/bin/env python3
"""Run one fresh read-only F3 material row-30 resource/scheduler preflight.

This v2 refreshes the already-consumed v1 observation.  It checks current
host/scheduler state before any expensive source hashing and never launches a
worker or reserves a queue/ledger slot.  A blocked observation remains a
terminal immutable receipt; it is not retried in place.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
from typing import Any


LAB = Path(__file__).resolve().parents[1]
EVIDENCE = LAB / "campaigns/core-v1/material/evidence"
V1 = EVIDENCE / "f3-material-row30-resource-preflight-v1/receipt.json"
DECISION = EVIDENCE / "f3-material-row30-root-decision-v1/packet.json"
READINESS = EVIDENCE / "f3-material-t2-launch-readiness-v1/receipt.json"
LEDGER = LAB / "campaigns/l1-resume/continuation/RESOURCE-LEDGER.json"
LIMITS = LAB / "campaigns/l1-resume/continuation/RESOURCE-LIMITS.json"
RUNTIME_STATUS = LAB / "campaigns/core-v1/runtime/status.json"
SOURCE = LAB / "campaigns/l1-resume/data/continuation/F3_CELL3_LONG_dp0p0075_a1p000_noslip_visco1_nopen.h5"
PREPARED = LAB / "campaigns/l1-resume/continuation/F3_CELL3_LONG_dp0p0075_a1p000_noslip_visco1_nopen-PREPARED.json"
OUTPUT = EVIDENCE / "f3-material-row30-resource-preflight-v2/receipt.json"
CPU_CORES = 2
RAM_MIB = 8192
MIN_DISK_BYTES = 8 * 1024**3


def _read_regular(path: Path) -> bytes:
    path = Path(path)
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError(f"expected regular file: {path}")
        payload = stream.read()
        after = os.fstat(stream.fileno())
    before_sig = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
    after_sig = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
    if before_sig != after_sig or len(payload) != before.st_size:
        raise RuntimeError(f"file changed while being read: {path}")
    return payload


def _json(path: Path) -> tuple[dict[str, Any], bytes]:
    payload = _read_regular(path)
    value = json.loads(payload.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value, payload


def _binding(path: Path, role: str, payload: bytes) -> dict[str, Any]:
    relative = path.relative_to(LAB) if path.is_absolute() else path
    return {
        "path": relative.as_posix(),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "role": role,
    }


def _mem_available_bytes() -> int:
    for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) * 1024
    raise RuntimeError("/proc/meminfo has no MemAvailable")


def environment_snapshot(*, lab: Path = LAB) -> dict[str, Any]:
    cpus = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else (os.cpu_count() or 1)
    load = list(os.getloadavg())
    disk_free = shutil.disk_usage(lab).free
    return {
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "available_cpu_count": cpus,
        "load_average_1_5_15_min": load,
        "available_ram_bytes": _mem_available_bytes(),
        "filesystem_free_bytes": disk_free,
    }


def active_f3_row30_workers(*, proc: Path = Path("/proc")) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            argv = (entry / "cmdline").read_bytes().split(b"\0")
            stat_line = (entry / "stat").read_text(encoding="utf-8")
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if not any(b"f3_native_volume_mls.py" in arg for arg in argv):
            continue
        joined = b" ".join(argv)
        if b"f3-material-30-canonical-s4-" not in joined:
            continue
        closing = stat_line.rfind(")")
        fields = stat_line[closing + 2 :].split() if closing >= 0 else []
        matches.append({"pid": int(entry.name), "process_state": fields[0] if fields else "unknown"})
    return sorted(matches, key=lambda item: item["pid"])


def _active_scheduler_count(runtime: dict[str, Any]) -> int:
    counts = runtime.get("counts", {})
    if not isinstance(counts, dict):
        raise ValueError("runtime status has no count object")
    return sum(int(counts.get(name, 0)) for name in ("reserved", "launching", "running"))


def assess_blockers(
    *,
    environment: dict[str, Any],
    active_workers: list[dict[str, Any]],
    scheduler_active_count: int,
    ledger: dict[str, Any],
    limits: dict[str, Any],
    proposed_cpu_core_hours: float,
    proposed_materials: int = 1,
    now: datetime | None = None,
) -> list[str]:
    blockers: list[str] = []
    loads = environment["load_average_1_5_15_min"]
    if loads[0] > environment["available_cpu_count"]:
        blockers.append("one-minute host load exceeds the CPUs available to this task")
    if active_workers:
        blockers.append("an F3 material row-30 worker is already active; do not schedule a competing worker")
    if scheduler_active_count:
        blockers.append("scheduler has reserved, launching, or running jobs")
    if environment["available_ram_bytes"] < RAM_MIB * 1024**2:
        blockers.append("available RAM is below the 8 GiB row-30 request")
    if environment["filesystem_free_bytes"] < MIN_DISK_BYTES:
        blockers.append("free filesystem capacity is below the 8 GiB floor")

    expiry_raw = ledger.get("conservative_expiry_utc")
    expiry = datetime.fromisoformat(expiry_raw) if isinstance(expiry_raw, str) else None
    current_time = now or datetime.now(timezone.utc)
    if expiry is None or current_time >= expiry:
        blockers.append("historical resource ledger has expired")
    cpu_used = float(ledger.get("cpu_core_hours_upper_bound", 0.0))
    cpu_limit = float(limits.get("cpu_core_hours", 0.0))
    if cpu_used + proposed_cpu_core_hours > cpu_limit:
        blockers.append("historical CPU core-hour cap would be exceeded by row30")
    material_used = int(ledger.get("material_configurations_used", 0))
    material_limit = int(limits.get("materials", 0))
    if material_used + proposed_materials > material_limit:
        blockers.append("historical material-configuration cap would be exceeded by row30")
    return blockers


def _sha256_stable(path: Path) -> tuple[int, str]:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    digest = hashlib.sha256()
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError(f"expected regular source file: {path}")
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
        after = os.fstat(stream.fileno())
    sig_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
    sig_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
    if sig_before != sig_after:
        raise RuntimeError(f"source changed while hashing: {path}")
    return before.st_size, digest.hexdigest()


def build(
    *,
    environment_probe=environment_snapshot,
    process_probe=active_f3_row30_workers,
    now: datetime | None = None,
) -> dict[str, Any]:
    v1, v1_bytes = _json(V1)
    decision, decision_bytes = _json(DECISION)
    readiness, readiness_bytes = _json(READINESS)
    ledger, ledger_bytes = _json(LEDGER)
    limits_document, limits_bytes = _json(LIMITS)
    runtime, runtime_bytes = _json(RUNTIME_STATUS)
    limits = limits_document.get("limits", {})
    if v1.get("schema") != "core.material.f3.row30.resource_preflight.v1":
        raise ValueError("prior row30 preflight receipt schema changed")
    if decision.get("candidate", {}).get("configuration_id") != "F3-material-30":
        raise ValueError("root decision no longer selects F3 material row 30")
    if readiness.get("next_executable_step", {}).get("candidate_matrix_row") != 30:
        raise ValueError("launch readiness no longer selects row 30")
    if v1.get("status") != "blocked_no_worker_authorized":
        raise ValueError("prior row30 resource preflight is not the expected blocked v1")

    environment = environment_probe()
    workers = process_probe()
    scheduler_active = _active_scheduler_count(runtime)
    resource = v1["resource_assessment"]
    proposed_cpu = float(resource["proposed_cpu_core_hours"])
    blockers = assess_blockers(
        environment=environment,
        active_workers=workers,
        scheduler_active_count=scheduler_active,
        ledger=ledger,
        limits=limits,
        proposed_cpu_core_hours=proposed_cpu,
        now=now,
    )

    old_source_binding = v1["bindings"]["source_h5"]
    old_prepared_binding = v1["bindings"]["prepared"]
    source_identity: dict[str, Any] = {
        "path": old_source_binding["path"],
        "expected_sha256_from_v1": old_source_binding.get("sha256"),
        "source_hash_revalidation_performed": False,
        "prepared_hash_revalidation_performed": False,
        "reason": "short-circuited because current scheduler/resource blockers already deny admission",
    }
    if not blockers:
        source_size, source_hash = _sha256_stable(SOURCE)
        prepared_size, prepared_hash = _sha256_stable(PREPARED)
        source_identity.update({
            "bytes": source_size,
            "observed_sha256": source_hash,
            "source_hash_revalidation_performed": True,
            "prepared_bytes": prepared_size,
            "prepared_sha256": prepared_hash,
            "prepared_hash_revalidation_performed": True,
        })
        if source_hash != old_source_binding.get("sha256") or source_size != old_source_binding.get("bytes"):
            blockers.append("production source hash/size changed since the prior preflight")
        if prepared_hash != old_prepared_binding.get("sha256") or prepared_size != old_prepared_binding.get("bytes"):
            blockers.append("prepared-source hash/size changed since the prior preflight")

    bindings = [
        _binding(V1.relative_to(LAB), "prior blocked row30 resource preflight", v1_bytes),
        _binding(DECISION.relative_to(LAB), "row30 root decision packet", decision_bytes),
        _binding(READINESS.relative_to(LAB), "row30 launch-readiness receipt", readiness_bytes),
        _binding(LEDGER.relative_to(LAB), "current historical resource ledger", ledger_bytes),
        _binding(LIMITS.relative_to(LAB), "current historical resource limits", limits_bytes),
        _binding(RUNTIME_STATUS.relative_to(LAB), "current scheduler status snapshot", runtime_bytes),
        _binding(Path("scripts/f3_material_row30_resource_preflight_v2.py"), "v2 one-shot preflight builder", _read_regular(LAB / "scripts/f3_material_row30_resource_preflight_v2.py")),
        _binding(Path("tests/test_f3_material_row30_resource_preflight_v2.py"), "v2 preflight tests", _read_regular(LAB / "tests/test_f3_material_row30_resource_preflight_v2.py")),
    ]
    status = "blocked_no_worker_authorized" if blockers else "resource_preflight_passed_worker_still_not_authorized"
    return {
        "schema": "core.material.f3.row30.resource_preflight.v2",
        "record_id": "f3-material-row30-resource-preflight-v2",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "authorized_scope": "exactly one fresh F3 material row-30 resource/scheduler preflight; no worker launch",
        "candidate": v1["candidate"],
        "current_environment": environment,
        "active_f3_row30_workers": workers,
        "scheduler_active_job_count": scheduler_active,
        "resource_assessment": {
            "proposed_cpu_core_hours": proposed_cpu,
            "current_cpu_core_hours_upper_bound": ledger.get("cpu_core_hours_upper_bound"),
            "historical_cpu_core_hour_limit": limits.get("cpu_core_hours"),
            "current_material_configurations_used": ledger.get("material_configurations_used"),
            "historical_material_configuration_limit": limits.get("materials"),
            "historical_expiry_utc": ledger.get("conservative_expiry_utc"),
            "source_identity": source_identity,
        },
        "blockers": blockers,
        "execution_controls": {
            "material_worker_started": False,
            "solver_started": False,
            "gpu_started": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "T2_credit": 0,
        },
        "worker_launch_authorized": False,
        "next_required_authority": "A fresh root resource decision and separate worker-launch authorization are required; this preflight grants neither.",
        "bindings": bindings,
    }


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write(path: Path = OUTPUT) -> dict[str, Any]:
    target = Path(path).absolute()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".partial")
    value = build()
    payload = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.link(temporary, target)
    except FileExistsError:
        raise FileExistsError(f"refusing to overwrite immutable row30 resource preflight v2: {target}")
    finally:
        os.unlink(temporary)
    _fsync_directory(target.parent)
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    value = write(parser.parse_args(argv).output)
    print(json.dumps({key: value[key] for key in ("status", "active_f3_row30_workers", "scheduler_active_job_count", "blockers")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
