#!/usr/bin/env python3
"""Freeze the authorized, read-only F3 material row-30 resource preflight.

The owner authorized this *preflight*, not an execution.  This module binds
the one canonical s4/4096/full-window candidate, checks the exact source and
the scheduler's current idle state, and records every blocker without
reserving a slot, mutating an old ledger, or creating a queue job.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
EVIDENCE = LAB / "campaigns/core-v1/material/evidence"
DECISION = EVIDENCE / "f3-material-row30-root-decision-v1/packet.json"
READINESS = EVIDENCE / "f3-material-t2-launch-readiness-v1/receipt.json"
LEDGER = LAB / "campaigns/l1-resume/continuation/RESOURCE-LEDGER.json"
LIMITS = LAB / "campaigns/l1-resume/continuation/RESOURCE-LIMITS.json"
RUNTIME_STATUS = LAB / "campaigns/core-v1/runtime/status.json"
SOURCE = LAB / "campaigns/l1-resume/data/continuation/F3_CELL3_LONG_dp0p0075_a1p000_noslip_visco1_nopen.h5"
PREPARED = LAB / "campaigns/l1-resume/continuation/F3_CELL3_LONG_dp0p0075_a1p000_noslip_visco1_nopen-PREPARED.json"
BACKEND = LAB / "scripts/f3_native_volume_mls.py"
OUTPUT = EVIDENCE / "f3-material-row30-resource-preflight-v1/receipt.json"

SOURCE_SHA256 = "fb304e0bc8e5d7f51eaab0af0d8dba8c928b8146e0bf5776002f83012e4480c4"
PREPARED_SHA256 = "23d151c07c53c83b3048be9b665722161baaef37fc31e6ce6ec42e4b26b36894"
OUTPUT_NAMESPACE = "campaigns/core-v1/material/attempts/f3-material-30-canonical-s4-r001"

# The retained s2 full-window run consumed 10,404.025 s at 4096 seeds.  s4
# has twice the RK reconstruction stages; this conservative 2x bound is a
# scheduler estimate only and cannot be substituted for an actual s4 result.
S2_WALL_SECONDS = 10404.025129585993
S4_ESTIMATED_WALL_SECONDS = 2.0 * S2_WALL_SECONDS
CPU_CORES = 2
RAM_MIB = 8192
IO_WEIGHT = 0.25
POSTPROCESS_SECONDS = 600.0


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            value.update(block)
    return value.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


def bind(path: Path, role: str, *, expected: str | None = None) -> dict[str, Any]:
    if not path.is_file():
        return {"path": str(path.relative_to(LAB)), "role": role, "exists": False}
    actual = digest(path)
    return {
        "path": str(path.relative_to(LAB)), "role": role, "exists": True,
        "bytes": path.stat().st_size, "sha256": actual,
        "expected_sha256": expected, "hash_matches_expected": expected is None or actual == expected,
    }


def _active_count(status: dict[str, Any]) -> int:
    counts = status.get("counts", {})
    if not isinstance(counts, dict):
        raise ValueError("runtime status has no count object")
    return sum(int(counts.get(name, 0)) for name in ("reserved", "launching", "running"))


def build() -> dict[str, Any]:
    decision = read_json(DECISION)
    readiness = read_json(READINESS)
    ledger = read_json(LEDGER)
    limits = read_json(LIMITS).get("limits", {})
    runtime = read_json(RUNTIME_STATUS)
    if decision.get("status") != "awaiting_user_root_decision_for_new_row30_attempt":
        raise ValueError("unexpected row30 root-decision state")
    candidate = decision.get("candidate", {})
    if candidate.get("configuration_id") != "F3-material-30" or candidate.get("seeds") != 4096 or candidate.get("substeps") != 4:
        raise ValueError("row30 decision does not bind the canonical s4/4096 candidate")
    if readiness.get("next_executable_step", {}).get("candidate_matrix_row") != 30:
        raise ValueError("launch readiness no longer selects matrix row 30")

    bindings = {
        "root_decision": bind(DECISION, "authorized root decision"),
        "launch_readiness": bind(READINESS, "row30 readiness audit"),
        "source_h5": bind(SOURCE, "read-only production CFD source", expected=SOURCE_SHA256),
        "prepared": bind(PREPARED, "production source preparation", expected=PREPARED_SHA256),
        "backend": bind(BACKEND, "current-frame MLS backend"),
        "resource_ledger": bind(LEDGER, "immutable historical resource ledger"),
        "resource_limits": bind(LIMITS, "historical limit record"),
        "runtime_status": bind(RUNTIME_STATUS, "scheduler observation"),
    }
    reserve_seconds = S4_ESTIMATED_WALL_SECONDS + POSTPROCESS_SECONDS
    reserve_core_hours = reserve_seconds * CPU_CORES / 3600.0
    cpu_used = float(ledger.get("cpu_core_hours_upper_bound", 0.0))
    cpu_limit = float(limits.get("cpu_core_hours", 0.0))
    material_used = int(ledger.get("material_configurations_used", 0))
    material_limit = int(limits.get("materials", 0))
    expiry_raw = ledger.get("conservative_expiry_utc")
    expiry = datetime.fromisoformat(expiry_raw) if isinstance(expiry_raw, str) else None
    now = datetime.now(timezone.utc)
    blockers: list[str] = []
    for name in ("source_h5", "prepared"):
        item = bindings[name]
        if not item.get("exists") or not item.get("hash_matches_expected"):
            blockers.append(f"{name} unavailable or hash mismatch")
    if expiry is None or now >= expiry:
        blockers.append("historical resource ledger has expired")
    if cpu_used + reserve_core_hours > cpu_limit:
        blockers.append("historical CPU core-hour cap is already exceeded before row30 reservation")
    if material_used + 1 > material_limit:
        blockers.append("historical material-configuration cap would be exceeded")
    active = _active_count(runtime)
    if active:
        blockers.append("scheduler has active owned jobs; no static idle admission")

    return {
        "schema": "core.material.f3.row30.resource_preflight.v1",
        "status": "blocked_no_worker_authorized" if blockers else "ready_for_separate_worker_authorization",
        "authorized_scope": "one fresh F3-material-30 resource/scheduler preflight only",
        "candidate": {
            "configuration_id": "F3-material-30", "matrix_row": 30, "q": 0.5,
            "source_role": "production", "seeds": 4096, "substeps": 4,
            "window": "full native 0--8.35 s", "backend": "f3_native_volume_mls_current_frame_rk4_v1",
        },
        "proposed_execution_contract": {
            "new_output_namespace": OUTPUT_NAMESPACE,
            "reuse_of_prior_s2_or_any_prior_output": "forbidden",
            "same_argv_resume_only": True,
            "argv_template": ["<python>", "<frozen-backend>", "--source", str(SOURCE.relative_to(LAB)), "--prepared", str(PREPARED.relative_to(LAB)), "--output", OUTPUT_NAMESPACE + "/trace.h5", "--audit-output", OUTPUT_NAMESPACE + "/source-preflight.json", "--seeds", "4096", "--substeps", "4"],
            "resource_request": {"cpu_cores": CPU_CORES, "ram_mib": RAM_MIB, "gpu_peak_mib": 0, "io_weight": IO_WEIGHT},
        },
        "resource_assessment": {
            "s2_observed_wall_seconds": S2_WALL_SECONDS,
            "s4_conservative_estimated_wall_seconds": S4_ESTIMATED_WALL_SECONDS,
            "postprocess_reserve_seconds": POSTPROCESS_SECONDS,
            "proposed_cpu_core_hours": reserve_core_hours,
            "historical_cpu_used_core_hours": cpu_used,
            "historical_cpu_limit_core_hours": cpu_limit,
            "historical_material_used": material_used,
            "historical_material_limit": material_limit,
            "historical_expiry_utc": expiry_raw,
            "runtime_active_owned_jobs": active,
        },
        "bindings": bindings,
        "blockers": blockers,
        "execution_controls": {"material_worker_started": False, "solver_started": False, "gpu_started": False, "queue_mutation": 0, "ledger_mutation": 0, "registry_mutation": 0, "T2_credit": 0},
        "next_required_authority": "A new root decision must establish a non-expired resource budget before any separate worker-launch authorization can be considered." if blockers else "A separate explicit one-attempt worker-launch authorization is required.",
    }


def write(path: Path = OUTPUT) -> dict[str, Any]:
    path = Path(path).resolve()
    if path.exists():
        raise FileExistsError(f"refusing to overwrite immutable row30 resource preflight: {path}")
    value = build()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    value = write(args.output)
    print(json.dumps({key: value[key] for key in ("status", "blockers")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
