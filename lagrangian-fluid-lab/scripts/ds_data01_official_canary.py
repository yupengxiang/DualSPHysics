#!/usr/bin/env python3
"""Prepare and run isolated dataset-only official-example canaries.

The canaries use official XML/assets with an explicitly recorded coarse
resolution and short observation window. They write only under
campaigns/ds-data-01/d02/canaries and never touch the legacy queue or any
learning entrypoint.
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
CAMPAIGN_ROOT = LAB_ROOT / "campaigns" / "ds-data-01" / "d02" / "canaries"

SPECS: dict[str, dict[str, Any]] = {
    "F1_main_dambreak3d": {
        "family": "F1",
        "mechanism": "3D single-phase dam-break free-surface propagation anchor",
        "source": "main/01_DamBreak",
        "base": "CaseDambreak",
        "dp": 0.020,
        "tmax": 0.60,
        "tout": 0.10,
        "gpu": 7,
        "dimension": "3D",
        "resolution_role": "coarse_canary_only",
    },
    "F1_mdbc_dambreak3d": {
        "family": "F1",
        "mechanism": "3D mDBC dam-break obstacle/reconnection anchor",
        "source": "mdbc/04_Dambreak",
        "base": "CaseDamBreak3D",
        "dp": 0.020,
        "tmax": 0.60,
        "tout": 0.10,
        "gpu": 4,
        "dimension": "3D",
        "resolution_role": "coarse_canary_only",
    },
    "F4_shapes_inlet3d": {
        "family": "F4",
        "mechanism": "3D shapes inlet liquid-column collision anchor",
        "source": "inletoutlet/05_ShapesInlet3D",
        "base": "CaseShapesInlet3D",
        "dp": 0.020,
        "tmax": 0.40,
        "tout": 0.10,
        "gpu": 5,
        "dimension": "3D",
        "resolution_role": "coarse_canary_only",
    },
    "F7_official_pump3d": {
        "family": "F7",
        "mechanism": "3D prescribed rotating pump transport anchor",
        "source": "main/13_Pump",
        "base": "CasePump",
        "dp": 0.020,
        "tmax": 0.50,
        "tout": 0.10,
        "gpu": 6,
        "dimension": "3D",
        "resolution_role": "coarse_canary_only",
    },
    "F7_moving_square2d": {
        "family": "F7",
        "mechanism": "2D prescribed moving obstacle control contrast",
        "source": "main/03_MovingSquare",
        "base": "CaseMovingSquare",
        "dp": 0.020,
        "tmax": 0.50,
        "tout": 0.10,
        "gpu": 4,
        "dimension": "2D",
        "resolution_role": "2D_calibration_contrast",
    },
}


def digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def tree_digest(root: Path) -> tuple[str | None, int, int]:
    if not root.exists():
        return None, 0, 0
    h = hashlib.sha256()
    count = 0
    total = 0
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        h.update(path.relative_to(root).as_posix().encode())
        h.update(b"\0")
        h.update((digest(path) or "").encode())
        count += 1
        total += path.stat().st_size
    return h.hexdigest(), count, total


def env() -> dict[str, str]:
    value = os.environ.copy()
    value["LD_LIBRARY_PATH"] = f"{BIN_ROOT}:{value.get('LD_LIBRARY_PATH', '')}"
    return value


def selected_specs(ids: list[str] | None) -> list[tuple[str, dict[str, Any]]]:
    if not ids:
        ids = list(SPECS)
    unknown = sorted(set(ids) - SPECS.keys())
    if unknown:
        raise SystemExit(f"unknown canary ids: {', '.join(unknown)}")
    return [(case_id, SPECS[case_id]) for case_id in ids]


def prepare(case_id: str, spec: dict[str, Any]) -> dict[str, Any]:
    case_root = CAMPAIGN_ROOT / case_id
    source = EXAMPLES_ROOT / spec["source"]
    generated = case_root / "generated"
    if not source.is_dir():
        raise FileNotFoundError(source)
    if generated.exists() and any(generated.iterdir()):
        raise FileExistsError(f"refusing to overwrite prepared canary: {generated}")
    generated.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, generated, dirs_exist_ok=True)
    target = generated / case_id
    command = [str(GENCASE), str(generated / f"{spec['base']}_Def"), str(target), f"-dp:{spec['dp']}", "-save:all"]
    started = time.monotonic()
    proc = subprocess.run(command, cwd=generated, env=env(), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    elapsed = time.monotonic() - started
    (case_root / "gencase.stdout.log").write_text(proc.stdout, encoding="utf-8")
    # Some GenCase versions create empty placeholders for external controls;
    # restore every original source asset after generation.
    for source_file in source.rglob("*"):
        if source_file.is_file():
            destination = generated / source_file.relative_to(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, destination)
    fluid = re.search(r"Fluid\.\.\.\.:\s*([0-9,]+)", proc.stdout)
    total = re.search(r"Total particles:\s*([0-9,]+)", proc.stdout)
    result = {
        "schema": "ds-data-01.d02.canary-preparation.v1",
        "case_id": case_id,
        **spec,
        "source_root": str(source.relative_to(LAB_ROOT)),
        "source_tree_sha256": tree_digest(source)[0],
        "generated_prefix": str(target.relative_to(LAB_ROOT)),
        "gencase_command": command,
        "gencase_returncode": proc.returncode,
        "gencase_elapsed_seconds": round(elapsed, 4),
        "fluid_particles": int(fluid.group(1).replace(",", "")) if fluid else None,
        "total_particles": int(total.group(1).replace(",", "")) if total else None,
        "gencase_stdout_sha256": digest(case_root / "gencase.stdout.log"),
        "status": "prepared" if proc.returncode == 0 and target.with_suffix(".xml").is_file() else "prepare_failed",
        "learning_attempts": 0,
    }
    (case_root / "prepare-receipt.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def gpu_free(index: int) -> tuple[bool, str]:
    proc = subprocess.run(
        ["nvidia-smi", "--query-gpu=index,memory.used,memory.total", "--format=csv,noheader"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    for line in proc.stdout.splitlines():
        values = [part.strip() for part in line.split(",")]
        if len(values) < 3 or values[0] != str(index):
            continue
        used = int(re.sub(r"[^0-9]", "", values[1]))
        total = int(re.sub(r"[^0-9]", "", values[2]))
        return used < 500, f"gpu={index} used_mib={used} total_mib={total}"
    return False, f"gpu={index} not visible; nvidia-smi={proc.returncode} {proc.stdout.strip()}"


def run_one(case_id: str, spec: dict[str, Any], prepared: dict[str, Any]) -> dict[str, Any]:
    allowed, gpu_observation = gpu_free(int(spec["gpu"]))
    if not allowed:
        raise RuntimeError(f"refusing launch: {gpu_observation}")
    case_root = CAMPAIGN_ROOT / case_id
    output = case_root / "attempt-001"
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"refusing to overwrite run attempt: {output}")
    output.mkdir(parents=True, exist_ok=True)
    prefix = LAB_ROOT / prepared["generated_prefix"]
    command = [
        str(SOLVER),
        f"-gpu:{spec['gpu']}",
        str(prefix),
        str(output),
        f"-tmax:{spec['tmax']}",
        f"-tout:{spec['tout']}",
    ]
    log_path = case_root / "solver.stdout.log"
    started_at = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    with log_path.open("w", encoding="utf-8") as log:
        proc = subprocess.run(command, cwd=prefix.parent, env=env(), stdout=log, stderr=subprocess.STDOUT, check=False)
    elapsed = time.monotonic() - started
    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    parts = sorted(output.glob("data*/Part_*.bi4"))
    completed = proc.returncode == 0 and "Finished execution (code=0)" in log_text and bool(parts)
    raw_hash, raw_count, raw_bytes = tree_digest(output)
    result = {
        "schema": "ds-data-01.d02.canary-run.v1",
        "case_id": case_id,
        **spec,
        "prepared_prefix": prepared["generated_prefix"],
        "command": command,
        "gpu_observation_before_launch": gpu_observation,
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
        "learning_attempts": 0,
        "source_reproduction": "official_recipe_with_recorded_coarse_canary_override",
    }
    (case_root / "run-receipt.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def all_receipts(kind: str) -> list[dict[str, Any]]:
    records = []
    for case_root in sorted(path for path in CAMPAIGN_ROOT.iterdir() if path.is_dir()):
        receipt = case_root / f"{kind}-receipt.json"
        if receipt.is_file():
            records.append(json.loads(receipt.read_text(encoding="utf-8")))
    return records


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("prepare", "run", "rebuild"))
    parser.add_argument("--cases", nargs="*", choices=sorted(SPECS), default=None)
    args = parser.parse_args()
    items = selected_specs(args.cases)
    if args.stage == "prepare":
        results = [prepare(case_id, spec) for case_id, spec in items]
        summary_cases = all_receipts("prepare")
    elif args.stage == "run":
        prepared = {}
        for case_id, _ in items:
            receipt = CAMPAIGN_ROOT / case_id / "prepare-receipt.json"
            if not receipt.is_file():
                raise SystemExit(f"missing preparation receipt: {receipt}")
            prepared[case_id] = json.loads(receipt.read_text(encoding="utf-8"))
        results = []
        with ThreadPoolExecutor(max_workers=len(items)) as pool:
            futures = {pool.submit(run_one, case_id, spec, prepared[case_id]): case_id for case_id, spec in items}
            for future in as_completed(futures):
                results.append(future.result())
        results.sort(key=lambda result: result["case_id"])
        summary_cases = all_receipts("run")
    else:
        summary_cases = all_receipts("run")
        results = summary_cases
    summary = {
        "schema": f"ds-data-01.d02.canary-{args.stage}.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "learning_attempts": 0,
        "cases": sorted(summary_cases, key=lambda result: result["case_id"]),
    }
    out = CAMPAIGN_ROOT / f"{args.stage}-summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    outputs = [out]
    if args.stage == "rebuild":
        prepare_summary = {**summary, "schema": "ds-data-01.d02.canary-prepare.v1", "cases": all_receipts("prepare")}
        run_summary = {**summary, "schema": "ds-data-01.d02.canary-run.v1", "cases": all_receipts("run")}
        prepare_out = CAMPAIGN_ROOT / "prepare-summary.json"
        run_out = CAMPAIGN_ROOT / "run-summary.json"
        prepare_out.write_text(json.dumps(prepare_summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        run_out.write_text(json.dumps(run_summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        outputs = [prepare_out, run_out]
    else:
        out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"stage": args.stage, "cases": [r["case_id"] for r in summary["cases"]], "outputs": [str(path) for path in outputs], "statuses": {r["case_id"]: r["status"] for r in summary["cases"]}}, ensure_ascii=False, indent=2))
    return 0 if all(r["status"] in ("prepared", "completed") for r in summary["cases"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
