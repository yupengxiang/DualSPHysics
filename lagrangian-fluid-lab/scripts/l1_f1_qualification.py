#!/usr/bin/env python3
"""Bounded L1 qualification runner for the F1 plain dam-break recipe.

This module deliberately keeps the L1 campaign separate from the historical
``v0.1-candidate`` campaigns.  It reuses the tested conversion and audit
implementations, but writes new immutable candidate definitions, attempts,
data, and reports under ``campaigns/l1-qualification``.

The command graph is intentionally explicit:

    prepare-time -> run-time -> normalize-time -> audit-time -> decide-time
    prepare-conditional (only after a failed time gate)
    prepare-space  (only after a qualified time policy)
    run-space -> normalize-space -> audit-space -> decide-space

No command changes the upstream/vendor tree, reuses an old attempt by file
existence alone, or authorizes a development tranche.  Raw run/data/artifact
directories are ignored by the lab policy; compact machine reports and case
definitions remain reviewable.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any, Iterable, Sequence
import xml.etree.ElementTree as ET

try:
    from scripts import r5_f1_solver_gate as r5_gate
    from scripts import r6_n2_campaign as r6
    from scripts.boundary_sidecars import read_binary_vtk_polydata, write_sidecar
    from scripts.campaign_runner import (
        execute_attempt,
    )
    from scripts.trajectory_io import convert_streaming
    from scripts.w02_semantics import partvtk_csv
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    import r5_f1_solver_gate as r5_gate
    import r6_n2_campaign as r6
    from boundary_sidecars import read_binary_vtk_polydata, write_sidecar
    from campaign_runner import execute_attempt
    from trajectory_io import convert_streaming
    from w02_semantics import partvtk_csv


LAB = Path(__file__).resolve().parents[1]
CAMPAIGN = LAB / "campaigns" / "l1-qualification"
CASE_ROOT = CAMPAIGN / "cases"
ARTIFACT_ROOT = CAMPAIGN / "artifacts"
RUN_ROOT = CAMPAIGN / "runs"
DATA_ROOT = CAMPAIGN / "data"
AUDIT_ROOT = CAMPAIGN / "audits"
REPORT = CAMPAIGN / "l1-f1-qualification.json"
PREFLIGHT_ROOT = CAMPAIGN / "preflight"

BIN = LAB / "vendor" / "official" / "DualSPHysics_v5.4" / "bin" / "linux"
GENCASE = BIN / "GenCase_linux64"
SOLVER = BIN / "DualSPHysics5.4_linux64"
PARTVTK = BIN / "PartVTK_linux64"
SOURCE_DEFINITION = LAB / "cases" / "F1" / "F1_dam_break_plain" / "F1_dam_break_plain_Def.xml"

SCHEMA_VERSION = "l1-f1-qualification.v1"
BRANCH = "codex/lagrangian-fluid-exploration"
BASELINE_COMMIT = "dc9533eecf7ee608a1db04ea4e26bb80cd2b456a"
HEIGHTS_M = {"h09": 0.414, "h10": 0.460, "h11": 0.506}
DP_SPACE_M = {"coarse": 0.020, "medium": 0.014, "fine": 0.010}
TIME_MAX_S = 1.5
TIME_OUT_S = 0.001
TIME_REFERENCE_CFL = 0.1
TIME_PRIMARY_CFL = 0.05
TIME_CONDITIONAL_CFL = 0.025
GPU_IDS = (4, 5, 6, 7)
PROTECTED_GPU_IDS = (0, 1, 2, 3)
DEFAULT_TIMEOUT_S = 1800
COHOST_MIN_FREE_MIB = 8192
MAX_COHOST_JOBS_PER_GPU = 1
REGISTERED_TIMES_S = [
    0.0, 0.075, 0.15, 0.225, 0.3, 0.375, 0.45, 0.525, 0.6,
    0.675, 0.75, 0.825, 0.9, 0.975, 1.05, 1.125, 1.2, 1.275,
    1.35, 1.425, 1.5,
]
TIME_GATE = {
    "distribution_tv": 0.01,
    "com_l2_m": 0.012,
    "front_q90_abs_delta_m": 0.012,
}
SPACE_GATE = {
    "distribution_tv": 0.05,
    "com_l2_m": 0.06,
    "front_q90_abs_delta_m": 0.06,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def relpath(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(LAB.resolve()))
    except ValueError:
        return str(path.resolve())


def lab_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else LAB / path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def environment(*, cpu: bool = False) -> dict[str, str]:
    value = os.environ.copy()
    value["LD_LIBRARY_PATH"] = f"{BIN}:{value.get('LD_LIBRARY_PATH', '')}"
    value["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
    if cpu:
        value["CUDA_VISIBLE_DEVICES"] = ""
        value["NVIDIA_VISIBLE_DEVICES"] = "void"
    return value


def cohost_gpu_snapshot() -> list[dict[str, Any]]:
    """Return memory-aware GPU state for the L1 co-run policy.

    The historical runner's idle guard is intentionally not changed.  L1 has
    an explicit owner amendment permitting co-running with the long-lived
    external job, so this namespace uses a stricter free-memory guard instead
    of requiring zero utilization.
    """
    output = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=index,uuid,memory.used,memory.total,memory.free,utilization.gpu",
            "--format=csv,noheader,nounits",
        ],
        cwd=LAB,
        text=True,
        check=True,
        stdout=subprocess.PIPE,
    ).stdout
    rows = []
    for line in output.splitlines():
        index, gpu_uuid, used, total, free, utilization = [value.strip() for value in line.split(",")]
        rows.append({
            "index": int(index),
            "uuid": gpu_uuid,
            "memory_used_mib": int(used),
            "memory_total_mib": int(total),
            "memory_free_mib": int(free),
            "utilization_percent": int(utilization),
            "cohost_safe_at_snapshot": int(free) >= COHOST_MIN_FREE_MIB,
        })
    return rows


def allowed_uuids() -> list[str]:
    inventory = CAMPAIGN / "L1-W00-INVENTORY.json"
    if not inventory.is_file():
        raise RuntimeError("L1-W00-INVENTORY.json is missing; run W0 inventory first")
    payload = json.loads(inventory.read_text(encoding="utf-8"))
    policy = payload.get("execution_policy") or payload.get("gpu_policy")
    if not policy or "allowed_gpu_uuids" not in policy:
        raise RuntimeError("L1-W00-INVENTORY.json has no allowlisted GPU UUIDs")
    return list(policy["allowed_gpu_uuids"])


def require_headroom_allowed_gpu(index: int, allowed: Sequence[str]) -> dict[str, Any]:
    rows = cohost_gpu_snapshot()
    record = next((row for row in rows if row["index"] == index), None)
    if record is None:
        raise RuntimeError(f"physical GPU {index} does not exist")
    if record["uuid"] not in set(allowed):
        raise RuntimeError(f"GPU {index} UUID {record['uuid']} is not in the L1 allowlist")
    if record["memory_free_mib"] < COHOST_MIN_FREE_MIB:
        raise RuntimeError(
            f"GPU {index} lacks L1 co-run headroom: {record}; "
            f"requires at least {COHOST_MIN_FREE_MIB} MiB free"
        )
    return {
        **record,
        "launch_policy": "cohost_headroom",
        "minimum_free_mib": COHOST_MIN_FREE_MIB,
        "max_l1_jobs_per_gpu": MAX_COHOST_JOBS_PER_GPU,
    }


def choose_headroom_gpu(record: dict[str, Any], snapshot: dict[str, Any], reserved: set[int]) -> int:
    allowed = set(GPU_IDS)
    allowlisted_uuids = set(allowed_uuids())
    candidates = [
        row for row in snapshot["gpu_snapshot"]
        if row["index"] in allowed
        and row["uuid"] in allowlisted_uuids
        and row["index"] not in reserved
        and int(row.get("memory_free_mib", 0)) >= COHOST_MIN_FREE_MIB
    ]
    if not candidates:
        raise RuntimeError(
            f"no allowed GPU has {COHOST_MIN_FREE_MIB} MiB free for L1 co-run; "
            f"snapshot={snapshot['gpu_snapshot']}"
        )
    # Prefer the largest live margin.  The record's GPU remains the declared
    # preference and is retained in the manifest, but maximizing free memory
    # is the safer choice while the external training job is active.
    return max(candidates, key=lambda row: int(row["memory_free_mib"]))["index"]


def _source_z_bounds(height: float) -> tuple[float, float]:
    return 0.04, height + 0.04


def _set_parameter(root: ET.Element, key: str, value: Any) -> None:
    r6._set_parameter(root, key, value)


def _fluid_drawbox(root: ET.Element) -> ET.Element:
    return r6._fluid_drawbox(root)


def _wall_spec() -> dict[str, Any]:
    return deepcopy(r5_gate.WALL_SPECS["plain_dam_break"])


def base_record(*, case_id: str, phase: str, height_label: str,
                resolution: str, dp_m: float, cfl_number: float,
                gpu: int, recipe_revision: str) -> dict[str, Any]:
    height = HEIGHTS_M[height_label]
    return {
        "id": case_id,
        "case_id": case_id,
        "campaign_id": "L1_AUTONOMOUS_FLUID_QUALIFICATION",
        "phase": phase,
        "family": "F1",
        "background_id": "plain_dam_break",
        "mechanism": "collapse-runup-return",
        "height_label": height_label,
        "height_m": height,
        "continuous_initial_fluid_z_bounds_m": list(_source_z_bounds(height)),
        "resolution": resolution,
        "dp_m": dp_m,
        "cfl_number": cfl_number,
        "time_max_s": TIME_MAX_S,
        "time_out_s": TIME_OUT_S,
        "recipe_revision": recipe_revision,
        "source_definition": relpath(SOURCE_DEFINITION),
        "gpu": gpu,
        "registered_absorbing_exit_faces": [],
        "wall_spec": _wall_spec(),
        "registered_times_s": REGISTERED_TIMES_S,
        "formal_release": False,
        "development_authorized": False,
    }


def time_records(cfl_number: float = TIME_PRIMARY_CFL) -> list[dict[str, Any]]:
    suffix = "cfl005" if cfl_number == 0.05 else "cfl0025" if cfl_number == 0.025 else "cfl010"
    revision = f"L1_F1_time_dp014_{suffix}_v1"
    return [
        base_record(
            case_id=f"L1_W1_TIME_h10_dp014_{suffix}", phase="W1_time",
            height_label="h10", resolution="fine", dp_m=0.014,
            cfl_number=cfl_number, gpu=4, recipe_revision=revision,
        ),
        base_record(
            case_id=f"L1_W1_TIME_h11_dp014_{suffix}", phase="W1_time",
            height_label="h11", resolution="fine", dp_m=0.014,
            cfl_number=cfl_number, gpu=5, recipe_revision=revision,
        ),
    ]


def space_records(cfl_number: float) -> list[dict[str, Any]]:
    suffix = "cfl005" if cfl_number == 0.05 else "cfl0025" if cfl_number == 0.025 else "cfl010"
    revision = f"L1_F1_space_020_014_010_{suffix}_v1"
    records = []
    for height_label in ("h09", "h10", "h11"):
        for index, (resolution, dp_m) in enumerate(DP_SPACE_M.items()):
            records.append(base_record(
                case_id=f"L1_W1_SPACE_{height_label}_{resolution}_dp{str(dp_m).replace('.', 'p')}_{suffix}",
                phase="W1_space", height_label=height_label,
                resolution=resolution, dp_m=dp_m, cfl_number=cfl_number,
                gpu=GPU_IDS[index], recipe_revision=revision,
            ))
    return records


def record_hash(record: dict[str, Any]) -> str:
    stable = {
        key: value for key, value in record.items()
        if key not in {
            "candidate_definition", "generated_prefix", "gencase",
            "candidate_definition_sha256", "generated_xml_sha256",
        }
    }
    stable["source_definition_sha256"] = sha256(SOURCE_DEFINITION)
    stable["solver_sha256"] = sha256(SOLVER)
    stable["gencase_sha256"] = sha256(GENCASE)
    return hashlib.sha256(json.dumps(stable, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def load_report() -> dict[str, Any]:
    if REPORT.is_file():
        try:
            payload = json.loads(REPORT.read_text(encoding="utf-8"))
            payload.setdefault("gpu_launch_policy", {
                "mode": "cohost_headroom",
                "minimum_free_mib": COHOST_MIN_FREE_MIB,
                "max_l1_jobs_per_gpu": MAX_COHOST_JOBS_PER_GPU,
                "external_jobs_may_continue": True,
                "protected_gpu_indices": list(PROTECTED_GPU_IDS),
            })
            return payload
        except json.JSONDecodeError:
            pass
    return {
        "schema_version": SCHEMA_VERSION,
        "campaign_id": "L1_AUTONOMOUS_FLUID_QUALIFICATION",
        "baseline_commit": BASELINE_COMMIT,
        "branch": BRANCH,
        "execution_status": "not_started",
        "evidence_status": "not_started",
        "acceptance_status": "pending",
        "validation_scope": [],
        "open_blockers": [],
        "formal_release": False,
        "development_authorized": False,
        "protected_gpu_indices": list(PROTECTED_GPU_IDS),
        "allowed_gpu_indices": list(GPU_IDS),
        "gpu_launch_policy": {
            "mode": "cohost_headroom",
            "minimum_free_mib": COHOST_MIN_FREE_MIB,
            "max_l1_jobs_per_gpu": MAX_COHOST_JOBS_PER_GPU,
            "external_jobs_may_continue": True,
            "protected_gpu_indices": list(PROTECTED_GPU_IDS),
        },
        "resource_budget": {
            "gpu_hours_total": 64.0,
            "cpu_core_hours_total": 512.0,
            "qualification_solver_attempts_max": 56,
            "development_solver_attempts_max": 40,
            "training_attempts_max": 12,
            "full_material_configurations_max": 32,
            "new_storage_gib_max": 512.0,
            "qualification_solver_attempts_used": 0,
            "development_solver_attempts_used": 0,
            "training_attempts_used": 0,
            "material_configurations_used": 0,
            "solver_elapsed_seconds": 0.0,
            "gpu_hours_used": 0.0,
            "gencase_cpu_seconds": 0.0,
            "normalization_cpu_seconds": 0.0,
            "audit_cpu_seconds": 0.0,
        },
        "prepared_cases": [],
        "solver_runs": [],
        "normalization": [],
        "audits": [],
        "attempts": [],
    }


def merge_by_id(rows: Iterable[dict[str, Any]], updates: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    result = {str(row.get("case_id", row.get("id"))): row for row in rows}
    for update in updates:
        key = str(update.get("case_id", update.get("id")))
        result[key] = {**result.get(key, {}), **update}
    return list(result.values())


def prepare_one(record: dict[str, Any]) -> dict[str, Any]:
    case_id = record["case_id"]
    case_dir = CASE_ROOT / case_id
    generated_dir = ARTIFACT_ROOT / case_id / "generated"
    case_dir.mkdir(parents=True, exist_ok=True)
    generated_dir.mkdir(parents=True, exist_ok=True)
    candidate = case_dir / f"{case_id}_Def.xml"
    tree = ET.parse(SOURCE_DEFINITION)
    root = tree.getroot()
    definition = root.find(".//geometry/definition")
    if definition is None:
        raise ValueError("source definition has no geometry definition")
    definition.set("dp", str(record["dp_m"]))
    _fluid_drawbox(root).find("./size").set("z", str(record["height_m"]))
    cfl = root.find(".//constantsdef/cflnumber")
    if cfl is None:
        raise ValueError("source definition has no cflnumber")
    cfl.set("value", str(record["cfl_number"]))
    for key, value in (
        ("SavePosDouble", 2), ("StepAlgorithm", 1), ("VerletSteps", 40),
        ("Boundary", 1), ("Shifting", 0), ("TimeMax", TIME_MAX_S),
        ("TimeOut", TIME_OUT_S),
    ):
        _set_parameter(root, key, value)
    ET.indent(tree, space="    ")
    tree.write(candidate, encoding="utf-8", xml_declaration=True)

    prefix = generated_dir / case_id
    started = time.perf_counter()
    process = subprocess.run(
        [str(GENCASE), str(candidate.with_suffix("")), str(prefix), "-save:all"],
        cwd=generated_dir, env=environment(cpu=True), text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
    )
    elapsed = time.perf_counter() - started
    stdout_path = generated_dir / "gencase.stdout.log"
    stdout_path.write_text(process.stdout, encoding="utf-8")
    if process.returncode != 0 or not prefix.with_suffix(".xml").is_file() or not prefix.with_suffix(".bi4").is_file():
        raise RuntimeError(f"GenCase failed for {case_id}: {process.stdout[-1500:]}")
    match = re.search(r"Fluid\.{3,}:\s*([0-9,]+)", process.stdout)
    prepared = {
        **record,
        "candidate_definition": relpath(candidate),
        "candidate_definition_sha256": sha256(candidate),
        "generated_prefix": relpath(prefix),
        "generated_xml_sha256": sha256(prefix.with_suffix(".xml")),
        "generated_bi4_sha256": sha256(prefix.with_suffix(".bi4")),
        "gencase": {
            "returncode": process.returncode,
            "fluid_particles": int(match.group(1).replace(",", "")) if match else None,
            "elapsed_seconds": elapsed,
            "stdout": relpath(stdout_path),
        },
    }
    prepared["record_hash"] = record_hash(prepared)
    return prepared


def prepare_records(records: Sequence[dict[str, Any]], *, label: str) -> list[dict[str, Any]]:
    prepared = [prepare_one(record) for record in records]
    report = load_report()
    report["prepared_cases"] = merge_by_id(report.get("prepared_cases", []), prepared)
    report.setdefault("preparation", []).append({
        "label": label,
        "prepared_at_utc": utc_now(),
        "case_ids": [item["case_id"] for item in prepared],
    })
    report["execution_status"] = "prepared_only"
    report["evidence_status"] = "inputs_prepared"
    report["resource_budget"]["gencase_cpu_seconds"] = float(report["resource_budget"].get("gencase_cpu_seconds", 0.0)) + sum(
        float(item["gencase"]["elapsed_seconds"]) for item in prepared
    )
    atomic_json(REPORT, report)
    return prepared


def latest_attempt(record: dict[str, Any]) -> Path | None:
    latest = RUN_ROOT / record["case_id"] / "latest.json"
    if not latest.is_file():
        return None
    try:
        path = Path(json.loads(latest.read_text(encoding="utf-8"))["attempt_directory"])
    except (KeyError, json.JSONDecodeError):
        return None
    return path if path.is_dir() else None


def latest_payload(record: dict[str, Any]) -> dict[str, Any] | None:
    latest = RUN_ROOT / record["case_id"] / "latest.json"
    if not latest.is_file():
        return None
    try:
        return json.loads(latest.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _attempt_rows() -> list[dict[str, Any]]:
    rows = []
    for path in sorted(RUN_ROOT.glob("*/attempts/*/attempt.json")):
        try:
            rows.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            rows.append({"path": relpath(path), "status": "invalid_attempt_manifest"})
    return rows


def run_one(record: dict[str, Any], *, runtime_gpu: int | None = None,
            rerun: bool = False) -> dict[str, Any]:
    expected_hash = record.get("record_hash") or record_hash(record)
    prior = latest_payload(record)
    if prior and not rerun and prior.get("record_hash") == expected_hash:
        if prior.get("status") == "completed":
            return {**prior, "execution_status": "reused_completed"}
        return {**prior, "execution_status": "existing_failed_not_retried"}
    declared_gpu = int(record["gpu"])
    gpu = declared_gpu if runtime_gpu is None else int(runtime_gpu)
    gpu_record = require_headroom_allowed_gpu(gpu, allowed_uuids())
    prefix = lab_path(record["generated_prefix"])
    result = execute_attempt(
        record["case_id"], [str(SOLVER), f"-gpu:{gpu}", str(prefix), "{output}"],
        RUN_ROOT, cwd=prefix.parent, env=environment(),
        evidence_glob="data/Part_*.bi4", required_text="Finished execution (code=0)",
        timeout_seconds=DEFAULT_TIMEOUT_S,
    )
    payload = {
        **result,
        "record_hash": expected_hash,
        "execution_status": "completed" if result.get("status") == "completed" else "solver_failed",
        "gpu_at_launch": gpu_record,
        "gpu_index_declared": declared_gpu,
        "gpu_index_requested": gpu,
        "gpu_launch_policy": "cohost_headroom",
        "protected_gpu_indices": list(PROTECTED_GPU_IDS),
        "input_generated_xml_sha256": sha256(prefix.with_suffix(".xml")),
        "input_generated_bi4_sha256": sha256(prefix.with_suffix(".bi4")),
        "solver_sha256": sha256(SOLVER),
        "phase": record["phase"],
        "recipe_revision": record["recipe_revision"],
    }
    atomic_json(RUN_ROOT / record["case_id"] / "latest.json", payload)
    return payload


def preflight(label: str, records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    snapshot = {
        "label": label,
        "captured_at_utc": utc_now(),
        "requested_gpu_indices": sorted({int(item["gpu"]) for item in records}),
        "protected_gpu_indices": list(PROTECTED_GPU_IDS),
        "gpu_snapshot": cohost_gpu_snapshot(),
        "disk_usage": {
            "total_bytes": os.statvfs(LAB).f_frsize * os.statvfs(LAB).f_blocks,
            "free_bytes": os.statvfs(LAB).f_frsize * os.statvfs(LAB).f_bavail,
        },
    }
    PREFLIGHT_ROOT.mkdir(parents=True, exist_ok=True)
    atomic_json(PREFLIGHT_ROOT / f"{label}.json", snapshot)
    return snapshot


def run_records(records: Sequence[dict[str, Any]], *, label: str, rerun: bool = False) -> list[dict[str, Any]]:
    records = list(records)
    if not records:
        raise ValueError(f"no records selected for {label}")
    if len(records) > len(GPU_IDS):
        raise ValueError("one batch may not exceed the four allowed GPUs")
    selected = {int(item["gpu"]) for item in records}
    if any(index not in GPU_IDS for index in selected):
        raise ValueError(f"records contain a protected or unsupported GPU: {sorted(selected)}")
    # Co-run permission is deliberately conservative: one L1 solver at a time
    # and a fresh memory snapshot before every launch.  The declared GPU is a
    # preference; a safe allow-listed GPU may be selected when the external
    # workload has filled that preferred card.
    pending = list(records)
    results = []
    preflight_snapshots = []
    batch_index = 0
    while pending:
        batch_index += 1
        snapshot = preflight(f"{label}-launch-{batch_index}", pending[:1])
        preflight_snapshots.append(snapshot)
        runtime_gpu = choose_headroom_gpu(pending[0], snapshot, set())
        record = pending.pop(0)
        results.append(run_one(record, runtime_gpu=runtime_gpu, rerun=rerun))
    report = load_report()
    report["solver_runs"] = merge_by_id(report.get("solver_runs", []), results)
    report["attempts"] = _attempt_rows()
    elapsed = sum(float(row.get("elapsed_seconds", 0.0)) for row in report["attempts"] if row.get("status") in {"completed", "failed"})
    report["resource_budget"]["solver_elapsed_seconds"] = elapsed
    report["resource_budget"]["gpu_hours_used"] = elapsed / 3600.0
    report["resource_budget"]["qualification_solver_attempts_used"] = len(report["attempts"])
    report["execution_status"] = "solver_completed" if all(
        item.get("execution_status") in {"completed", "reused_completed"} for item in results
    ) else "solver_completed_with_findings"
    report["evidence_status"] = "solver_outputs_available" if all(
        item.get("status") == "completed" for item in results
    ) else "solver_failure_recorded"
    report.setdefault("preflight", []).extend(preflight_snapshots)
    atomic_json(REPORT, report)
    return results


def normalize_one(record: dict[str, Any]) -> dict[str, Any]:
    attempt = latest_attempt(record)
    if attempt is None:
        return {"case_id": record["case_id"], "normalization_status": "blocked_missing_attempt"}
    output = DATA_ROOT / f"{record['case_id']}.h5"
    started = time.perf_counter()
    try:
        complete = False
        if output.is_file():
            import h5py
            with h5py.File(output, "r") as h5:
                complete = bool(h5.attrs.get("conversion_complete", False)) and h5.attrs.get("l1_record_hash") == record.get("record_hash")
        if not complete:
            csv_dir = attempt / "csv"
            csv_paths = partvtk_csv(attempt / "data", csv_dir, "-all,+fluid")
            convert_streaming(record, csv_paths, output)
        import h5py
        with h5py.File(output, "r+") as h5:
            h5.attrs["l1_record_hash"] = record.get("record_hash") or record_hash(record)
            h5.attrs["recipe_revision"] = record["recipe_revision"]
            h5.attrs["source_definition_sha256"] = sha256(SOURCE_DEFINITION)
            h5.attrs["solver_sha256"] = sha256(SOLVER)
            h5.attrs["cfl_number"] = float(record["cfl_number"])
            h5.attrs["height_m"] = float(record["height_m"])
            h5.attrs["dp_m"] = float(record["dp_m"])
            h5.attrs["time_out_s"] = float(record["time_out_s"])
        prefix = lab_path(record["generated_prefix"])
        vtk = prefix.with_name(prefix.name + "_MkCells.vtk")
        sidecar = CAMPAIGN / "sidecars" / f"{record['case_id']}.h5"
        sidecar_summary = write_sidecar(
            sidecar, record["case_id"], output,
            read_binary_vtk_polydata(vtk),
            source_vtk_label=relpath(vtk), source_hdf5_label=relpath(output),
        )
        return {
            "case_id": record["case_id"],
            "normalization_status": "completed",
            "elapsed_seconds": time.perf_counter() - started,
            "hdf5": relpath(output),
            "hdf5_sha256": sha256(output),
            "frames": len(csv_paths) if 'csv_paths' in locals() else None,
            "sidecar": relpath(sidecar),
            "sidecar_sha256": sha256(sidecar),
            "sidecar_audit": sidecar_summary,
        }
    except Exception as error:
        return {
            "case_id": record["case_id"],
            "normalization_status": "failed",
            "elapsed_seconds": time.perf_counter() - started,
            "error": repr(error),
        }


def normalize_records(records: Sequence[dict[str, Any]], *, label: str) -> list[dict[str, Any]]:
    started = time.perf_counter()
    results = [normalize_one(record) for record in records]
    report = load_report()
    report["normalization"] = merge_by_id(report.get("normalization", []), results)
    report["resource_budget"]["normalization_cpu_seconds"] = float(report["resource_budget"].get("normalization_cpu_seconds", 0.0)) + (time.perf_counter() - started)
    report["normalization_status"] = "completed" if all(item.get("normalization_status") == "completed" for item in results) else "completed_with_findings"
    report.setdefault("normalization_batches", []).append({"label": label, "case_ids": [item["case_id"] for item in records]})
    atomic_json(REPORT, report)
    return results


def compact_audit(audit: dict[str, Any]) -> dict[str, Any]:
    # The full saved-time audit is also written per case.  Keep the report
    # summary readable while retaining the 21 registered physical times and
    # all hard/unknown decisions.
    summary = dict(audit)
    summary.pop("mass_distribution_series", None)
    summary.pop("center_of_mass_series", None)
    summary.pop("fixed_time_grid", None)
    return summary


def audit_one(record: dict[str, Any]) -> dict[str, Any]:
    import h5py
    h5_path = DATA_ROOT / f"{record['case_id']}.h5"
    attempt = latest_attempt(record)
    if not h5_path.is_file():
        return {
            "case_id": record["case_id"],
            "r6_full_time_audit_status": "missing_input",
            "r6_hard_failures": ["normalized_hdf5_missing"],
        }
    started = time.perf_counter()
    try:
        audit = r6.full_time_audit(record, h5_path, attempt)
        audit["l1_case_id"] = record["case_id"]
        audit["l1_phase"] = record["phase"]
        audit["l1_recipe_revision"] = record["recipe_revision"]
        audit["l1_record_hash"] = record.get("record_hash") or record_hash(record)
        artifact = AUDIT_ROOT / f"{record['case_id']}.json"
        atomic_json(artifact, audit)
        summary = compact_audit(audit)
        summary.update({
            "case_id": record["case_id"],
            "phase": record["phase"],
            "height_label": record["height_label"],
            "height_m": record["height_m"],
            "resolution": record["resolution"],
            "dp_m": record["dp_m"],
            "cfl_number": record["cfl_number"],
            "recipe_revision": record["recipe_revision"],
            "record_hash": record.get("record_hash") or record_hash(record),
            "audit_artifact": relpath(artifact),
            "audit_elapsed_seconds": time.perf_counter() - started,
        })
        return summary
    except Exception as error:
        return {
            "case_id": record["case_id"],
            "r6_full_time_audit_status": "audit_exception",
            "r6_hard_failures": [repr(error)],
            "audit_elapsed_seconds": time.perf_counter() - started,
        }


def read_full_audit(summary: dict[str, Any]) -> dict[str, Any]:
    artifact = summary.get("audit_artifact")
    if not artifact:
        return summary
    path = lab_path(artifact)
    if not path.is_file():
        return summary
    return json.loads(path.read_text(encoding="utf-8"))


def audit_records(records: Sequence[dict[str, Any]], *, label: str) -> list[dict[str, Any]]:
    started = time.perf_counter()
    results = [audit_one(record) for record in records]
    report = load_report()
    report["audits"] = merge_by_id(report.get("audits", []), results)
    report["resource_budget"]["audit_cpu_seconds"] = float(report["resource_budget"].get("audit_cpu_seconds", 0.0)) + (time.perf_counter() - started)
    report.setdefault("audit_batches", []).append({"label": label, "case_ids": [item["case_id"] for item in records]})
    report["audit_status"] = "completed" if all(
        item.get("r6_full_time_audit_status") == "pass" for item in results
    ) else "completed_with_findings"
    atomic_json(REPORT, report)
    return results


def historical_reference_records() -> list[dict[str, Any]]:
    shared = {
        "family": "F1", "background_id": "plain_dam_break",
        "mechanism": "collapse-runup-return", "resolution": "fine",
        "dp_m": 0.014, "time_max_s": TIME_MAX_S, "time_out_s": TIME_OUT_S,
        "registered_absorbing_exit_faces": [], "wall_spec": _wall_spec(),
        "registered_times_s": REGISTERED_TIMES_S, "phase": "historical_reference",
        "recipe_revision": "historical_R6_N3_cfl010_reuse",
    }
    rows = []
    sources = {
        "h10": (
            "R6_N3_F1_plain_dam_break_h10_fine_cfl010",
            CAMPAIGN.parent / "v0.1-candidate/data/r6-n3-bridge-h10/R6_N3_F1_plain_dam_break_h10_fine_cfl010.h5",
            CAMPAIGN.parent / "v0.1-candidate/runs/r6-n3-bridge-h10/R6_N3_F1_plain_dam_break_h10_fine_cfl010/latest.json",
        ),
        "h11": (
            "R6_N3_F1_plain_dam_break_h11_fine_cfl010",
            CAMPAIGN.parent / "v0.1-candidate/data/r6-n3-endpoint-cfl/R6_N3_F1_plain_dam_break_h11_fine_cfl010.h5",
            CAMPAIGN.parent / "v0.1-candidate/runs/r6-n3-endpoint-cfl/R6_N3_F1_plain_dam_break_h11_fine_cfl010/latest.json",
        ),
    }
    for height_label, (case_id, h5_path, latest_path) in sources.items():
        if not h5_path.is_file() or not latest_path.is_file():
            raise RuntimeError(f"historical exact reuse evidence missing for {height_label}: {h5_path}")
        latest = json.loads(latest_path.read_text(encoding="utf-8"))
        row = {
            **shared,
            "id": case_id,
            "case_id": case_id,
            "height_label": height_label,
            "height_m": HEIGHTS_M[height_label],
            "continuous_initial_fluid_z_bounds_m": list(_source_z_bounds(HEIGHTS_M[height_label])),
            "cfl_number": TIME_REFERENCE_CFL,
            "source_definition": relpath(SOURCE_DEFINITION),
            "hdf5": relpath(h5_path),
            "attempt_path": latest.get("attempt_directory"),
            "historical_hdf5_sha256": sha256(h5_path),
            "historical_generated_xml_sha256": next((
                item.get("generated_xml_sha256") for report_name in (
                    CAMPAIGN.parent / "v0.1-candidate/r6-n3-bridge-h10.json",
                    CAMPAIGN.parent / "v0.1-candidate/r6-n3-endpoint-closure.json",
                ) if report_name.is_file()
                for item in json.loads(report_name.read_text(encoding="utf-8")).get("prepared_cases", [])
                if item.get("case_id") == case_id
            ), None),
        }
        rows.append(row)
    return rows


def ensure_reference_audits(report: dict[str, Any]) -> dict[str, Any]:
    existing = {item.get("case_id"): item for item in report.get("reference_audits", [])}
    for record in historical_reference_records():
        if record["case_id"] in existing and existing[record["case_id"]].get("audit_artifact"):
            continue
        h5_path = lab_path(record["hdf5"])
        attempt = Path(record["attempt_path"])
        audit = r6.full_time_audit(record, h5_path, attempt)
        audit["reference_reuse"] = True
        audit["historical_input_hdf5_sha256"] = record["historical_hdf5_sha256"]
        artifact = AUDIT_ROOT / f"reference-{record['height_label']}-cfl010.json"
        atomic_json(artifact, audit)
        existing[record["case_id"]] = {
            **compact_audit(audit),
            "case_id": record["case_id"],
            "height_label": record["height_label"],
            "cfl_number": TIME_REFERENCE_CFL,
            "hdf5": record["hdf5"],
            "audit_artifact": relpath(artifact),
            "execution_status": "reused_exact_historical_evidence",
        }
    report["reference_audits"] = list(existing.values())
    return report


def _metric_grid(audit: dict[str, Any]) -> dict[float, dict[str, Any]]:
    return {
        round(float(item["requested_time_s"]), 6): item
        for item in audit.get("fixed_time_grid", [])
    }


def compare_time(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    left, right = _metric_grid(a), _metric_grid(b)
    rows = []
    for requested in sorted(set(left) & set(right)):
        first, second = left[requested], right[requested]
        if first.get("distribution") is None or second.get("distribution") is None:
            continue
        first_distribution = r6._closed_distribution(first["distribution"])
        second_distribution = r6._closed_distribution(second["distribution"])
        com = float(__import__("numpy").linalg.norm(
            __import__("numpy").asarray(first["com_m"]) - __import__("numpy").asarray(second["com_m"])
        ))
        q90 = abs(float(first["front_quantiles_m"]["q90"]) - float(second["front_quantiles_m"]["q90"]))
        energy_left = float(first["kinetic_energy_proxy_j"])
        energy_right = float(second["kinetic_energy_proxy_j"])
        rows.append({
            "requested_time_s": requested,
            "left_actual_time_s": first.get("actual_time_s"),
            "right_actual_time_s": second.get("actual_time_s"),
            "actual_time_delta_s": abs(float(first.get("actual_time_s", requested)) - float(second.get("actual_time_s", requested))),
            "distribution_tv": float(r5_gate.mass_fraction_tv(first_distribution, second_distribution)),
            "com_l2_m": com,
            "front_q90_abs_delta_m": q90,
            "kinetic_energy_relative_delta": abs(energy_left - energy_right) / max(abs(energy_left), abs(energy_right), 1e-12),
        })
    maxima = {
        key: max((row[key] for row in rows), default=None)
        for key in (*TIME_GATE, "kinetic_energy_relative_delta", "actual_time_delta_s")
    }
    passed = bool(rows) and all(
        maxima[key] is not None and maxima[key] <= threshold
        for key, threshold in TIME_GATE.items()
    )
    return {
        "time_grid_count": len(rows),
        "thresholds": TIME_GATE,
        "maxima": maxima,
        "status": "pass" if passed else "fail",
        "series": rows,
    }


def time_decision() -> dict[str, Any]:
    report = ensure_reference_audits(load_report())
    summaries = {item["case_id"]: item for item in report.get("audits", [])}
    references = {item["height_label"]: item for item in report.get("reference_audits", [])}
    primary = {item["height_label"]: item for item in report.get("audits", []) if item.get("cfl_number") == TIME_PRIMARY_CFL}
    comparisons = {}
    for height_label in ("h10", "h11"):
        if height_label not in primary or height_label not in references:
            comparisons[height_label] = {"status": "unknown", "reason": "audit_missing"}
            continue
        comparisons[height_label] = compare_time(
            read_full_audit(references[height_label]), read_full_audit(primary[height_label])
        )
    primary_pass = all(item.get("status") == "pass" for item in comparisons.values()) and len(comparisons) == 2
    decision: dict[str, Any] = {
        "primary_cfl": TIME_PRIMARY_CFL,
        "reference_cfl": TIME_REFERENCE_CFL,
        "comparisons_reference_to_primary": comparisons,
        "conditional_cfl": None,
        "conditional_comparisons": {},
        "status": "qualified_for_space" if primary_pass else "conditional_required",
        "chosen_cfl": TIME_PRIMARY_CFL if primary_pass else None,
        "gate": TIME_GATE,
        "interpretation": (
            "CFL=0.05 is the declared time policy for the new space ladder; this is a numerical recipe decision."
            if primary_pass else
            "CFL=0.05 differs beyond the registered time budget; prepare the pre-registered CFL=0.025 pair before deciding."
        ),
    }
    conditional = {item["height_label"]: item for item in report.get("audits", []) if item.get("cfl_number") == TIME_CONDITIONAL_CFL}
    if conditional:
        conditional_comparisons = {}
        for height_label in ("h10", "h11"):
            if height_label not in conditional or height_label not in primary:
                conditional_comparisons[height_label] = {"status": "unknown", "reason": "audit_missing"}
            else:
                conditional_comparisons[height_label] = compare_time(
                    read_full_audit(primary[height_label]), read_full_audit(conditional[height_label])
                )
        conditional_pass = all(item.get("status") == "pass" for item in conditional_comparisons.values()) and len(conditional_comparisons) == 2
        decision["conditional_cfl"] = TIME_CONDITIONAL_CFL
        decision["conditional_comparisons"] = conditional_comparisons
        decision["status"] = "qualified_for_space" if conditional_pass else "negative_time_study"
        decision["chosen_cfl"] = TIME_CONDITIONAL_CFL if conditional_pass else None
        decision["interpretation"] = (
            "CFL=0.025 is the smallest pre-registered policy that meets the time gate against CFL=0.05."
            if conditional_pass else
            "The pre-registered CFL=0.025 comparison still exceeds the time budget; W1 time is negative and must transfer to W2 fallback."
        )
    report["time_decision"] = decision
    report["acceptance_status"] = decision["status"]
    report["validation_scope"] = ["21 registered physical times", "actual saved timestamps", "mass distribution TV", "mass-weighted COM", "front q90", "kinetic-energy proxy"]
    report["open_blockers"] = [] if decision["status"] == "qualified_for_space" else ["time sensitivity exceeds registered budget or conditional time study is incomplete"]
    atomic_json(REPORT, report)
    return decision


def space_decision() -> dict[str, Any]:
    report = load_report()
    time_gate = report.get("time_decision", {})
    chosen_cfl = time_gate.get("chosen_cfl")
    if chosen_cfl not in {TIME_PRIMARY_CFL, TIME_CONDITIONAL_CFL}:
        raise RuntimeError("space decision requires a qualified time policy")
    audits = [item for item in report.get("audits", []) if item.get("phase") == "W1_space" and item.get("cfl_number") == chosen_cfl]
    by_height: dict[str, dict[str, Any]] = {}
    qualified = []
    for height_label in ("h09", "h10", "h11"):
        rows = {item.get("resolution"): item for item in audits if item.get("height_label") == height_label}
        comparisons = {}
        for left, right, label in (("coarse", "medium", "coarse_to_medium"), ("medium", "fine", "medium_to_fine")):
            if left not in rows or right not in rows:
                comparisons[label] = {"status": "unknown", "reason": "resolution_missing"}
            else:
                comparisons[label] = r6._pair_comparison(read_full_audit(rows[left]), read_full_audit(rows[right]))
        case_ok = len(rows) == 3 and all(item.get("r6_full_time_audit_status") == "pass" for item in rows.values())
        comparison_ok = len(comparisons) == 2 and all(item.get("status") == "pass_diagnostic" for item in comparisons.values())
        status = "qualified_t1_height_candidate" if case_ok and comparison_ok else "blocked_t1_height_candidate"
        if status == "qualified_t1_height_candidate":
            qualified.append(height_label)
        by_height[height_label] = {
            "height_m": HEIGHTS_M[height_label],
            "resolution_status": {level: rows.get(level, {}).get("r6_full_time_audit_status", "missing") for level in DP_SPACE_M},
            "comparisons": comparisons,
            "status": status,
        }
    improvement_candidates = []
    for height_label, item in by_height.items():
        coarse = item["comparisons"].get("coarse_to_medium", {}).get("maxima", {}).get("distribution_tv")
        fine = item["comparisons"].get("medium_to_fine", {}).get("maxima", {}).get("distribution_tv")
        if coarse is not None and fine is not None and fine < coarse:
            improvement_candidates.append(height_label)
    decision = {
        "chosen_cfl": chosen_cfl,
        "by_height": by_height,
        "qualified_height_labels": qualified,
        "qualified_t1_recipe": len(qualified) >= 1,
        "improvement_candidates_for_conditional_007": improvement_candidates,
        "conditional_second_ladder_eligible": bool(improvement_candidates),
        "development_authorized": False,
        "formal_release": False,
        "interpretation": (
            "At least one height passed the first registered ladder; W4 internal-point qualification is still required before any development batch."
            if qualified else
            "No height passed the first registered ladder; continue only with the pre-registered 0.007 m test for improving heights or W2 fallback."
        ),
    }
    report["space_decision"] = decision
    report["acceptance_status"] = "candidate_t1_recipe_pending_domain" if qualified else "no_t1_height_qualified"
    report["development_authorized"] = False
    report["open_blockers"] = [] if qualified else ["no height passed the first L1 space ladder"]
    atomic_json(REPORT, report)
    return decision


def selected_prepared(report: dict[str, Any], phase: str, *, cfl: float | None = None) -> list[dict[str, Any]]:
    rows = [item for item in report.get("prepared_cases", []) if item.get("phase") == phase]
    if cfl is not None:
        rows = [item for item in rows if float(item.get("cfl_number")) == cfl]
    if not rows:
        raise RuntimeError(f"no prepared {phase} cases found")
    return rows


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=(
            "prepare-time", "run-time", "normalize-time", "audit-time", "decide-time",
            "prepare-conditional", "run-conditional", "normalize-conditional", "audit-conditional",
            "prepare-space", "run-space", "normalize-space", "audit-space", "decide-space", "status",
        ),
        nargs="?", default="status",
    )
    parser.add_argument("--rerun", action="store_true", help="make a new attempt after a prior failed attempt")
    args = parser.parse_args(argv)
    report = load_report()

    if args.action == "prepare-time":
        prepare_records(time_records(TIME_PRIMARY_CFL), label="primary-cfl005")
    elif args.action == "run-time":
        run_records(selected_prepared(report, "W1_time", cfl=TIME_PRIMARY_CFL), label="primary-cfl005", rerun=args.rerun)
    elif args.action == "normalize-time":
        normalize_records(selected_prepared(report, "W1_time", cfl=TIME_PRIMARY_CFL), label="primary-cfl005")
    elif args.action == "audit-time":
        audit_records(selected_prepared(report, "W1_time", cfl=TIME_PRIMARY_CFL), label="primary-cfl005")
    elif args.action == "decide-time":
        time_decision()
    elif args.action == "prepare-conditional":
        decision = report.get("time_decision") or time_decision()
        if decision.get("status") != "conditional_required":
            raise RuntimeError("conditional CFL=0.025 is only permitted after a failed primary time gate")
        prepare_records(time_records(TIME_CONDITIONAL_CFL), label="conditional-cfl0025")
    elif args.action == "run-conditional":
        run_records(selected_prepared(report, "W1_time", cfl=TIME_CONDITIONAL_CFL), label="conditional-cfl0025", rerun=args.rerun)
    elif args.action == "normalize-conditional":
        normalize_records(selected_prepared(report, "W1_time", cfl=TIME_CONDITIONAL_CFL), label="conditional-cfl0025")
    elif args.action == "audit-conditional":
        audit_records(selected_prepared(report, "W1_time", cfl=TIME_CONDITIONAL_CFL), label="conditional-cfl0025")
    elif args.action == "prepare-space":
        decision = report.get("time_decision") or time_decision()
        chosen = decision.get("chosen_cfl")
        if decision.get("status") != "qualified_for_space" or chosen not in {TIME_PRIMARY_CFL, TIME_CONDITIONAL_CFL}:
            raise RuntimeError("space ladder is not authorized until the time gate qualifies")
        prepare_records(space_records(float(chosen)), label=f"space-{chosen:g}")
    elif args.action == "run-space":
        rows = selected_prepared(report, "W1_space")
        for start in range(0, len(rows), len(GPU_IDS)):
            run_records(rows[start:start + len(GPU_IDS)], label=f"space-batch-{start // len(GPU_IDS) + 1}", rerun=args.rerun)
    elif args.action == "normalize-space":
        normalize_records(selected_prepared(report, "W1_space"), label="space")
    elif args.action == "audit-space":
        audit_records(selected_prepared(report, "W1_space"), label="space")
    elif args.action == "decide-space":
        space_decision()
    elif args.action == "status":
        report = load_report()
        print(json.dumps({
            "execution_status": report.get("execution_status"),
            "evidence_status": report.get("evidence_status"),
            "acceptance_status": report.get("acceptance_status"),
            "time_decision": report.get("time_decision"),
            "space_decision": report.get("space_decision"),
            "resource_budget": report.get("resource_budget"),
            "formal_release": report.get("formal_release"),
            "development_authorized": report.get("development_authorized"),
            "open_blockers": report.get("open_blockers"),
        }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
