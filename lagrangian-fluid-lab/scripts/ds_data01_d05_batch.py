#!/usr/bin/env python3
"""Plan and run the DS-DATA-01 internal exploration batch.

The batch is deliberately marked ``internal_development_only`` because D03
has not bound external ground truth and D04 has no production split
assignments.  The runner never touches the legacy queue or learning paths.
Solver cases are independent and use a dynamically preflighted GPU from
GPU1--GPU7; GPU0 is reserved for pre-existing activity.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from typing import Any


LAB_ROOT = Path(__file__).resolve().parents[1]
OFFICIAL_ROOT = LAB_ROOT / "vendor" / "official" / "DualSPHysics_v5.4"
EXAMPLES_ROOT = OFFICIAL_ROOT / "examples"
BIN_ROOT = OFFICIAL_ROOT / "bin" / "linux"
GENCASE = BIN_ROOT / "GenCase_linux64"
SOLVER = BIN_ROOT / "DualSPHysics5.4_linux64"
CAMPAIGN_ROOT = LAB_ROOT / "campaigns" / "ds-data-01" / "d05"
PLAN_PATH = LAB_ROOT / "campaigns" / "ds-data-01" / "D05_BATCH_PLAN.json"
POOL_DEFAULT = tuple(range(1, 8))


SPECS: dict[str, dict[str, Any]] = {
    "B05_F1_main_dambreak3d_dp030": {
        "family": "F1",
        "mechanism": "3D single-phase dam-break free-surface propagation",
        "source": "main/01_DamBreak",
        "base": "CaseDambreak",
        "parent_case_id": "F1_main_dambreak3d",
        "dp": 0.030,
        "tmax": 0.60,
        "tout": 0.10,
        "dimension": "3D",
        "d04_role": "candidate",
        "action": "solver_reproduction",
    },
    "B05_F1_mdbc_dambreak3d_dp030": {
        "family": "F1",
        "mechanism": "3D mDBC dam-break obstacle/reconnection",
        "source": "mdbc/04_Dambreak",
        "base": "CaseDamBreak3D",
        "parent_case_id": "F1_mdbc_dambreak3d",
        "dp": 0.030,
        "tmax": 0.60,
        "tout": 0.10,
        "dimension": "3D",
        "d04_role": "candidate",
        "action": "solver_reproduction",
    },
    "B05_F2_w06_candidate_bundle": {
        "family": "F2",
        "mechanism": "derived rotating-cup pour/catch",
        "source": "campaigns/v0.1-candidate/data/w06",
        "base": None,
        "parent_case_id": "W06_narrow_fast_center;W06_narrow_slow_center;W06_standard_fast_center;W06_standard_slow_center;W06_wide_slow_center",
        "dp": None,
        "tmax": None,
        "tout": None,
        "dimension": "3D",
        "d04_role": "candidate",
        "action": "reference_reuse_only",
    },
    "B05_F3_sloshing_motion_dp030": {
        "family": "F3",
        "mechanism": "prescribed-moving-tank sloshing",
        "source": "main/05_SloshingTank",
        "base": "CaseSloshingMotion",
        "parent_case_id": "O3_sloshing_motion",
        "dp": 0.030,
        "tmax": 1.00,
        "tout": 0.10,
        "dimension": "3D",
        "d04_role": "candidate",
        "action": "solver_reproduction",
    },
    "B05_F4_shapes_inlet3d_dp030": {
        "family": "F4",
        "mechanism": "3D shapes inlet liquid-column collision",
        "source": "inletoutlet/05_ShapesInlet3D",
        "base": "CaseShapesInlet3D",
        "parent_case_id": "F4_shapes_inlet3d",
        "dp": 0.030,
        "tmax": 0.40,
        "tout": 0.10,
        "dimension": "3D",
        "d04_role": "diagnostic",
        "action": "solver_reproduction",
    },
    "B05_F5_solitary_wave_kdv_dp030": {
        "family": "F5",
        "mechanism": "solitary-wave propagation KdV recipe",
        "source": "main/16_SolitaryWaves",
        "base": "CaseSolitaryWave_KdV",
        "parent_case_id": "O5_solitary_wave",
        "dp": 0.030,
        "tmax": 1.00,
        "tout": 0.10,
        "dimension": "3D",
        "d04_role": "candidate",
        "action": "solver_reproduction",
    },
    "B05_F6_floating_box_dp030": {
        "family": "F6",
        "mechanism": "free-floating body six-DoF",
        "source": "main/11_Floating",
        "base": "CaseFloating",
        "parent_case_id": "O6_floating_box",
        "dp": 0.030,
        "tmax": 0.80,
        "tout": 0.10,
        "dimension": "3D",
        "d04_role": "candidate",
        "action": "solver_reproduction",
    },
    "B05_F7_pump3d_dp030": {
        "family": "F7",
        "mechanism": "prescribed rotating pump transport",
        "source": "main/13_Pump",
        "base": "CasePump",
        "parent_case_id": "F7_official_pump3d",
        "dp": 0.030,
        "tmax": 0.60,
        "tout": 0.10,
        "dimension": "3D",
        "d04_role": "candidate",
        "action": "solver_reproduction",
    },
}


def digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def tree_digest(root: Path) -> tuple[str | None, int, int]:
    if not root.exists():
        return None, 0, 0
    value = hashlib.sha256()
    count = 0
    size = 0
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        value.update(path.relative_to(root).as_posix().encode())
        value.update(b"\0")
        value.update((digest(path) or "").encode())
        count += 1
        size += path.stat().st_size
    return value.hexdigest(), count, size


def environment() -> dict[str, str]:
    value = os.environ.copy()
    value["LD_LIBRARY_PATH"] = f"{BIN_ROOT}:{value.get('LD_LIBRARY_PATH', '')}"
    return value


def selected_specs(case_ids: list[str] | None) -> list[tuple[str, dict[str, Any]]]:
    selected = list(SPECS) if not case_ids else case_ids
    unknown = sorted(set(selected) - SPECS.keys())
    if unknown:
        raise SystemExit(f"unknown D05 batch case(s): {', '.join(unknown)}")
    return [(case_id, SPECS[case_id]) for case_id in selected]


def plan_payload() -> dict[str, Any]:
    cases = []
    for case_id, spec in SPECS.items():
        cases.append({
            "case_id": case_id,
            **spec,
            "release_role": "internal_development_only",
            "split": "unassigned",
            "scientific_acceptance": "not_assessed",
            "production_eligible": False,
            "learning_attempts": 0,
        })
    return {
        "schema": "ds-data-01.d05.batch-plan.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "internal dataset exploration only; no scientific acceptance and no production split materialization",
        "learning_attempts": 0,
        "execution_policy": {
            "default_stage": "plan",
            "run_requires_explicit_allow_internal_batch": True,
            "gpu_pool_default": list(POOL_DEFAULT),
            "gpu0_policy": "reserved_for_pre-existing_activity; never allocated",
            "parallel_policy": "independent cases may run concurrently after a fresh per-GPU memory preflight",
            "legacy_queue": "never touched",
        },
        "parameter_contract": {
            "parameter_axis": "resolution_variant_dp",
            "parent_case_required": True,
            "new_cases_must_not_enter_D04_split_without_registry_refresh": True,
            "open_lifecycle_cases_remain_diagnostic": True,
        },
        "cases": cases,
    }


def write_plan() -> dict[str, Any]:
    payload = plan_payload()
    PLAN_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def prepare_one(case_id: str, spec: dict[str, Any]) -> dict[str, Any]:
    case_root = CAMPAIGN_ROOT / case_id
    case_root.mkdir(parents=True, exist_ok=True)
    if spec["action"] == "reference_reuse_only":
        result = {
            "schema": "ds-data-01.d05.prepare.v1",
            "case_id": case_id,
            **spec,
            "release_role": "internal_development_only",
            "status": "reference_reuse_only",
            "learning_attempts": 0,
        }
        (case_root / "prepare-receipt.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return result
    source = EXAMPLES_ROOT / spec["source"]
    if not source.is_dir():
        raise FileNotFoundError(source)
    generated = case_root / "generated"
    if generated.exists() and any(generated.iterdir()):
        raise FileExistsError(f"refusing to overwrite prepared D05 case: {generated}")
    generated.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, generated, dirs_exist_ok=True)
    target = generated / case_id
    command = [str(GENCASE), str(generated / f"{spec['base']}_Def"), str(target), f"-dp:{spec['dp']}", "-save:all"]
    started = time.monotonic()
    proc = subprocess.run(command, cwd=generated, env=environment(), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    elapsed = time.monotonic() - started
    stdout_path = case_root / "gencase.stdout.log"
    stdout_path.write_text(proc.stdout, encoding="utf-8")
    for source_file in source.rglob("*"):
        if source_file.is_file():
            destination = generated / source_file.relative_to(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, destination)
    fluid = re.search(r"Fluid\.\.\.\.:\s*([0-9,]+)", proc.stdout)
    total = re.search(r"Total particles:\s*([0-9,]+)", proc.stdout)
    result = {
        "schema": "ds-data-01.d05.prepare.v1",
        "case_id": case_id,
        **spec,
        "release_role": "internal_development_only",
        "source_root": str(source.relative_to(LAB_ROOT)),
        "source_tree_sha256": tree_digest(source)[0],
        "generated_prefix": str(target.relative_to(LAB_ROOT)),
        "gencase_command": command,
        "gencase_returncode": proc.returncode,
        "gencase_elapsed_seconds": round(elapsed, 4),
        "fluid_particles": int(fluid.group(1).replace(",", "")) if fluid else None,
        "total_particles": int(total.group(1).replace(",", "")) if total else None,
        "gencase_stdout_sha256": digest(stdout_path),
        "status": "prepared" if proc.returncode == 0 and target.with_suffix(".xml").is_file() else "prepare_failed",
        "learning_attempts": 0,
    }
    (case_root / "prepare-receipt.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def gpu_snapshot() -> dict[int, tuple[int, int]]:
    proc = subprocess.run(
        ["nvidia-smi", "--query-gpu=index,memory.used,memory.total", "--format=csv,noheader"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    result: dict[int, tuple[int, int]] = {}
    for line in proc.stdout.splitlines():
        values = [part.strip() for part in line.split(",")]
        if len(values) < 3:
            continue
        try:
            index = int(values[0])
            used = int(re.sub(r"[^0-9]", "", values[1]))
            total = int(re.sub(r"[^0-9]", "", values[2]))
        except ValueError:
            continue
        result[index] = (used, total)
    return result


def preflight_gpu(gpu: int) -> str:
    if gpu == 0:
        raise RuntimeError("GPU0 is reserved and cannot be allocated by D05")
    snapshot = gpu_snapshot()
    if gpu not in snapshot:
        raise RuntimeError(f"GPU{gpu} is not visible in fresh nvidia-smi preflight")
    used, total = snapshot[gpu]
    if used >= 500:
        raise RuntimeError(f"GPU{gpu} is not idle enough: {used} MiB used of {total} MiB")
    return f"gpu={gpu} used_mib={used} total_mib={total}"


def run_one(case_id: str, spec: dict[str, Any], prepared: dict[str, Any], gpu: int) -> dict[str, Any]:
    if spec["action"] == "reference_reuse_only":
        result = {
            "schema": "ds-data-01.d05.run.v1",
            "case_id": case_id,
            "release_role": "internal_development_only",
            "action": spec["action"],
            "status": "reference_reuse_only",
            "gpu": None,
            "learning_attempts": 0,
        }
        (CAMPAIGN_ROOT / case_id / "run-receipt.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return result
    observation = preflight_gpu(gpu)
    case_root = CAMPAIGN_ROOT / case_id
    output = case_root / "attempt-001"
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"refusing to overwrite D05 run attempt: {output}")
    output.mkdir(parents=True, exist_ok=True)
    prefix = LAB_ROOT / prepared["generated_prefix"]
    command = [str(SOLVER), f"-gpu:{gpu}", str(prefix), str(output), f"-tmax:{spec['tmax']}", f"-tout:{spec['tout']}"]
    log_path = case_root / "solver.stdout.log"
    started_at = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    with log_path.open("w", encoding="utf-8") as log:
        proc = subprocess.run(command, cwd=prefix.parent, env=environment(), stdout=log, stderr=subprocess.STDOUT, check=False)
    elapsed = time.monotonic() - started
    text = log_path.read_text(encoding="utf-8", errors="replace")
    parts = sorted(output.glob("data*/Part_*.bi4"))
    completed = proc.returncode == 0 and "Finished execution (code=0)" in text and bool(parts)
    raw_hash, raw_count, raw_bytes = tree_digest(output)
    result = {
        "schema": "ds-data-01.d05.run.v1",
        "case_id": case_id,
        **spec,
        "release_role": "internal_development_only",
        "gpu": gpu,
        "gpu_observation_before_launch": observation,
        "command": command,
        "started_at_utc": started_at,
        "returncode": proc.returncode,
        "elapsed_seconds": round(elapsed, 4),
        "raw_output_root": str(output.relative_to(LAB_ROOT)),
        "frames": len(parts),
        "raw_tree_sha256": raw_hash,
        "raw_file_count": raw_count,
        "raw_bytes": raw_bytes,
        "solver_stdout_sha256": digest(log_path),
        "status": "completed" if completed else "run_failed",
        "scientific_acceptance": "not_assessed",
        "split": "unassigned",
        "learning_attempts": 0,
    }
    (case_root / "run-receipt.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def receipts(kind: str) -> list[dict[str, Any]]:
    result = []
    for case_id in SPECS:
        path = CAMPAIGN_ROOT / case_id / f"{kind}-receipt.json"
        if path.is_file():
            result.append(json.loads(path.read_text(encoding="utf-8")))
    return result


def write_summary(stage: str, items: list[dict[str, Any]]) -> Path:
    output = CAMPAIGN_ROOT / f"{stage}-summary.json"
    payload = {
        "schema": f"ds-data-01.d05.{stage}.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "internal_development_only",
        "learning_attempts": 0,
        "cases": sorted(items, key=lambda value: value["case_id"]),
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def parse_pool(value: str) -> tuple[int, ...]:
    try:
        pool = tuple(sorted({int(item.strip()) for item in value.split(",") if item.strip()}))
    except ValueError as exc:
        raise SystemExit(f"invalid GPU pool: {value}") from exc
    if not pool or any(gpu == 0 or gpu < 0 for gpu in pool):
        raise SystemExit("D05 GPU pool must contain only positive GPU indices; GPU0 is forbidden")
    return pool


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("plan", "prepare", "run", "rebuild"))
    parser.add_argument("--cases", nargs="*", default=None)
    parser.add_argument("--gpu-pool", default=",".join(str(value) for value in POOL_DEFAULT))
    parser.add_argument("--allow-internal-batch", action="store_true")
    args = parser.parse_args()
    items = selected_specs(args.cases)
    CAMPAIGN_ROOT.mkdir(parents=True, exist_ok=True)
    if args.stage == "plan":
        payload = write_plan()
        print(json.dumps({"output": str(PLAN_PATH), "cases": len(payload["cases"]), "gpu_pool": list(POOL_DEFAULT), "solver_started": False}, ensure_ascii=False, indent=2))
        return 0
    if not PLAN_PATH.is_file():
        write_plan()
    if args.stage == "prepare":
        results = []
        with ThreadPoolExecutor(max_workers=len(items)) as pool:
            futures = {pool.submit(prepare_one, case_id, spec): case_id for case_id, spec in items}
            for future in as_completed(futures):
                results.append(future.result())
        summary = write_summary("prepare", receipts("prepare"))
        print(json.dumps({"output": str(summary), "cases": len(results), "statuses": {item["case_id"]: item["status"] for item in results}, "gpu_started": False}, ensure_ascii=False, indent=2))
        return 0 if all(item["status"] in {"prepared", "reference_reuse_only"} for item in results) else 1
    if args.stage == "run" and not args.allow_internal_batch:
        raise SystemExit("refusing solver launch: pass --allow-internal-batch; D05 is not scientific production")
    prepared = {}
    for case_id, spec in items:
        receipt_path = CAMPAIGN_ROOT / case_id / "prepare-receipt.json"
        if not receipt_path.is_file():
            raise SystemExit(f"missing preparation receipt: {receipt_path}")
        prepared[case_id] = json.loads(receipt_path.read_text(encoding="utf-8"))
    if args.stage == "run":
        pool_ids = parse_pool(args.gpu_pool)
        solver_items = [(case_id, spec) for case_id, spec in items if spec["action"] != "reference_reuse_only"]
        if len(solver_items) > len(pool_ids):
            raise SystemExit(f"{len(solver_items)} solver cases exceed GPU pool size {len(pool_ids)}; use a bounded subset")
        assignments = {case_id: pool_ids[index] for index, (case_id, _) in enumerate(solver_items)}
        results = []
        with ThreadPoolExecutor(max_workers=len(items)) as executor:
            futures = {
                executor.submit(run_one, case_id, spec, prepared[case_id], assignments.get(case_id, -1)): case_id
                for case_id, spec in items
            }
            for future in as_completed(futures):
                results.append(future.result())
        summary = write_summary("run", receipts("run"))
        print(json.dumps({"output": str(summary), "cases": len(results), "gpu_assignments": assignments, "statuses": {item["case_id"]: item["status"] for item in results}, "scientific_acceptance": "not_assessed"}, ensure_ascii=False, indent=2))
        return 0 if all(item["status"] in {"completed", "reference_reuse_only"} for item in results) else 1
    prepare_summary = write_summary("prepare", receipts("prepare"))
    run_summary = write_summary("run", receipts("run"))
    print(json.dumps({"prepare_summary": str(prepare_summary), "run_summary": str(run_summary), "solver_started": False}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
