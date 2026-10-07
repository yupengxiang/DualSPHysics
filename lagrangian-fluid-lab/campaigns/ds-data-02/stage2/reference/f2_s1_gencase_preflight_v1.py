#!/usr/bin/env python3
"""Prepare bounded F2-S1 GenCase-only preflight inputs and requests.

The source Def/motion pair is the exact CURRENT336 F2-S1 continuous recipe.
This module creates new derived input files for a small spatial/time matrix and
emits CPU-only GenCase requests.  It never starts GenCase itself, never starts
the solver, and never edits the consumed source or historical receipts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
from typing import Any


SCHEMA = "ds02.stage2.f2-s1.gencase-preflight.v1"
REQUEST_SCHEMA = "ds02.request.v1"
REPO = Path(__file__).resolve().parents[5]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
GENCASE = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64")
TEMPLATE_DEF = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/"
    "F2_FIRST48_REMAINING24_SOURCE_ROOT801/"
    "root-stage1-f2-first48-remaining24-registered-source-generation-root801/source/source/"
    "F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010_Def.xml"
)
TEMPLATE_MOTION = TEMPLATE_DEF.with_name(TEMPLATE_DEF.name.replace("_Def.xml", "_motion.dat"))
INPUT_ROOT = Path(__file__).with_name("f2_s1_preflight_inputs")
TARGET_DP = 0.01
TARGET_CFL = 0.2
TARGET_PARTICLES = 418104
TARGET_NATIVE_BYTES = 18398632

CASES: tuple[dict[str, Any], ...] = (
    {
        "case_id": "F2_S1_PREFLIGHT_COARSE_DP0125",
        "label": "coarse_dp0125",
        "dp_m": 0.0125,
        "cfl": 0.2,
        "save_interval_s": 0.01,
        "purpose": "same F2-S1 continuous draw/fill/motion recipe at coarse spatial grid",
    },
    {
        "case_id": "F2_S1_PREFLIGHT_FINE_DP008",
        "label": "fine_dp008",
        "dp_m": 0.008,
        "cfl": 0.2,
        "save_interval_s": 0.01,
        "purpose": "same F2-S1 continuous draw/fill/motion recipe at fine spatial grid",
    },
    {
        "case_id": "F2_S1_PREFLIGHT_NATIVE_DP010_DENSE_CFL020",
        "label": "native_dp010_dense_cfl020",
        "dp_m": 0.01,
        "cfl": 0.2,
        "save_interval_s": 0.001,
        "purpose": "same original dp and CFL with dense output for time/output separation",
    },
    {
        "case_id": "F2_S1_PREFLIGHT_NATIVE_DP010_DENSE_CFL010",
        "label": "native_dp010_dense_cfl010",
        "dp_m": 0.01,
        "cfl": 0.1,
        "save_interval_s": 0.001,
        "purpose": "same original dp with half CFL and dense output for time/output separation",
    },
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {"path": str(path), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": sha256_file(path)}


def atomic_write(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(f"refuse to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def git_commit() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True).stdout.strip()


def derive_case(case: dict[str, Any], output_root: Path = INPUT_ROOT) -> dict[str, Any]:
    if not TEMPLATE_DEF.is_file() or not TEMPLATE_MOTION.is_file():
        raise FileNotFoundError("CURRENT F2-S1 Def/motion template is unavailable")
    dp = float(case["dp_m"])
    cfl = float(case["cfl"])
    if dp <= 0 or cfl <= 0:
        raise ValueError("dp and CFL must be positive")
    case_dir = output_root / case["label"]
    case_dir.mkdir(parents=True, exist_ok=True)
    def_name = f"{case['case_id']}_Def.xml"
    motion_name = f"{case['case_id']}_motion.dat"
    def_path = case_dir / def_name
    motion_path = case_dir / motion_name
    source = TEMPLATE_DEF.read_text(encoding="utf-8")
    source_dp = '<definition dp="0.01">'
    if source.count(source_dp) != 1:
        raise ValueError("template definition dp marker is not unique")
    source = source.replace(source_dp, f'<definition dp="{dp:g}">', 1)
    source_cfl = '<cflnumber value="0.2" />'
    if source.count(source_cfl) != 1:
        raise ValueError("template CFL marker is not unique")
    source = source.replace(source_cfl, f'<cflnumber value="{cfl:g}" />', 1)
    source_file_marker = '<file name="F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010_motion.dat" />'
    if source.count(source_file_marker) != 1:
        raise ValueError("template motion filename marker is not unique")
    source = source.replace(source_file_marker, f'<file name="{motion_name}" />', 1)
    source = source.replace("resolution=coarse_dp010", f"resolution={case['label']}", 1)
    if def_path.exists() or motion_path.exists():
        raise FileExistsError(f"refuse to overwrite derived input: {case_dir}")
    def_path.write_text(source, encoding="utf-8")
    motion_path.write_bytes(TEMPLATE_MOTION.read_bytes())
    expected_particles = int(round(TARGET_PARTICLES * (TARGET_DP / dp) ** 3))
    estimated_bytes = max(16 * 1024 * 1024, int(math.ceil(TARGET_NATIVE_BYTES * (TARGET_DP / dp) ** 3 * 1.5)))
    return {
        "case_id": case["case_id"],
        "label": case["label"],
        "purpose": case["purpose"],
        "physical_case_id": "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090",
        "dp_m": dp,
        "cfl": cfl,
        "requested_save_interval_s": case["save_interval_s"],
        "source_template": {"definition": file_record(TEMPLATE_DEF), "motion": file_record(TEMPLATE_MOTION)},
        "derived_inputs": {"definition": file_record(def_path), "motion": file_record(motion_path)},
        "expected_particle_count_estimate": expected_particles,
        "estimated_native_output_bytes": estimated_bytes,
        "estimate_policy": "target Part_0000 bytes scaled by (0.01/dp)^3 with 1.5 margin; actual GenCase receipt controls final count",
    }


def prepare(output_root: Path = INPUT_ROOT) -> dict[str, Any]:
    records = [derive_case(case, output_root) for case in CASES]
    manifest = {
        "schema": SCHEMA,
        "status": "PREPARED_INPUTS_NOT_RUN",
        "physical_case_id": "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090",
        "source_template": {"definition": file_record(TEMPLATE_DEF), "motion": file_record(TEMPLATE_MOTION)},
        "continuous_recipe_rule": "copy CURRENT336 geometry draw/fill, rotation axis/duration, gravity and solver control recipe; vary only dp/CFL and later solver save cadence",
        "cases": records,
        "solver_started": False,
        "gencase_started": False,
    }
    atomic_write(output_root / "manifest.json", manifest)
    return manifest


def request_for(record: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    root = REPO.resolve()
    definition = Path(record["derived_inputs"]["definition"]["path"]).resolve()
    motion = Path(record["derived_inputs"]["motion"]["path"]).resolve()
    request_path = output_dir / f"{record['case_id'].lower()}.json"
    estimate = int(record["estimated_native_output_bytes"])
    input_files = [
        root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch.py",
        root / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py",
        root / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py",
        Path(__file__).resolve(),
        GENCASE.resolve(),
        definition,
        motion,
        (INPUT_ROOT / "manifest.json").resolve(),
    ]
    return {
        "schema": REQUEST_SCHEMA,
        "family_id": "F2",
        "case_id": record["case_id"],
        "attempt_id": f"{record['case_id'].lower()}-003",
        "kind": "cpu",
        "cpu_task_kind": "gencase",
        "cpu_threads": 2,
        "max_wall_seconds": 300,
        "estimated_storage_bytes": estimate,
        "worktree_root": str(root),
        "cwd": str(definition.parent),
        "command": [str(GENCASE), str(definition.with_suffix("")), "{attempt_root}/generated", "-save:all"],
        "input_files": [str(path) for path in input_files],
        "input_hashes": {str(path): sha256_file(path) for path in input_files},
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": "ds_data02_stage2_dispatch.py",
            "strict_guard": "ds_data02_strict_dispatch_v1.py",
            "runtime": "ds_data02_runtime_v2.py",
            "launch_commit": git_commit(),
            "cpu_parent_binding": "required",
            "gpu": "none",
            "solver_launch": "forbidden",
            "estimated_cpu_core_hours": 2 * 300 / 3600,
            "estimated_new_storage_bytes": estimate,
        },
        "scope": {
            "physical_case_id": record["physical_case_id"],
            "continuous_recipe_source": "CURRENT336 F2-S1 exact Def/motion template",
            "dp_m": record["dp_m"],
            "cfl": record["cfl"],
            "requested_save_interval_s": record["requested_save_interval_s"],
            "gencase_only": True,
            "solver_started": False,
            "full_time_hdf5_read": False,
            "gpu_uuid_lease": "none",
        },
    }


def emit_requests(manifest: dict[str, Any], output_dir: Path) -> list[dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    requests = []
    for record in manifest["cases"]:
        request = request_for(record, output_dir)
        atomic_write(output_dir / f"{record['case_id'].lower()}.json", request)
        requests.append(request)
    return requests


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--emit-requests-dir", type=Path)
    parser.add_argument("--input-root", type=Path, default=INPUT_ROOT)
    args = parser.parse_args()
    if not args.prepare and args.emit_requests_dir is None:
        raise SystemExit("choose --prepare and/or --emit-requests-dir")
    manifest = prepare(args.input_root) if args.prepare else json.loads((args.input_root / "manifest.json").read_text(encoding="utf-8"))
    if args.emit_requests_dir is None:
        print(json.dumps({"status": "PASS", "manifest": str(args.input_root / 'manifest.json'), "cases": len(manifest['cases'])}, ensure_ascii=False))
        return 0
    requests = emit_requests(manifest, args.emit_requests_dir)
    print(json.dumps({"status": "PASS", "requests": len(requests), "output_dir": str(args.emit_requests_dir)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
