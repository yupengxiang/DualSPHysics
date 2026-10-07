#!/usr/bin/env python3
"""Build launch-disabled bounded F4 MK1 gravity-anchor requests."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

from stage2_f4_mk1_gravity_anchor_v2 import (
    ANCHOR_FRAMES,
    ANCHOR_MAX_TIME_S,
    parse_anchor_source,
    read_runparts,
    verify_source_contract,
)


REPO = Path(__file__).resolve().parents[5]
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
DISPATCH = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v4.py")
STRICT = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v4.py")
RUNTIME = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_runtime_v4.py")
WORKER = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f4_mk1_gravity_anchor_v2.py"
FIELD_WORKER = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f4_physical_observer_v1.py"
SOURCE_JSPH = REPO / "src/source/JSph.cpp"
SOURCE_GPU = REPO / "src/source/JSphGpuSingle.cpp"
SOURCE_KERNEL = REPO / "src/source/FunSphKernel.h"
OUT_ROOT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-f4-mk1-gravity-anchor-v2"
PHYSICAL_CASE_ID = "F4_DROP_gap0p22000_xoff0p00000_yoff0p00000_uz0p50000"
FRAMES = list(ANCHOR_FRAMES)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rec(path: Path, *, digest: bool = True) -> dict[str, object]:
    path = path.resolve()
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(path)
    stat = path.stat()
    value: dict[str, object] = {"path": str(path), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    value["sha256"] = sha256(path) if digest else "PARENT_V4_GUARD_REQUIRED"
    return value


def atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(path)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def git_head() -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def build_one(
    *,
    key: str,
    case_id: str,
    attempt_id: str,
    raw: Path,
    runparts: Path,
    runout: Path,
    xml: Path,
    solver_receipt: Path,
    output_root: Path,
    output_name: str,
) -> Path:
    source = parse_anchor_source(xml)
    source_contract = verify_source_contract(SOURCE_JSPH, SOURCE_GPU, SOURCE_KERNEL)
    rows = read_runparts(runparts)
    selected_rows = [rows[frame] for frame in FRAMES]
    raw_parts = [raw / f"Part_{frame:04d}.bi4" for frame in FRAMES]
    raw_records = [rec(path, digest=False) for path in raw_parts]
    selected_raw_bytes = sum(int(record["bytes"]) for record in raw_records)
    inputs = [
        WORKER, FIELD_WORKER, PYTHON, DECODER, DISPATCH, STRICT, RUNTIME,
        SOURCE_JSPH, SOURCE_GPU, SOURCE_KERNEL, xml, runparts, runout, solver_receipt,
        *raw_parts,
    ]
    input_hashes: dict[str, str] = {}
    for path in inputs:
        input_hashes[str(path.resolve())] = sha256(path) if path not in raw_parts else "PARENT_V4_GUARD_REQUIRED"
    command = [
        str(PYTHON), str(WORKER),
        "--raw-root", str(raw),
        "--runparts", str(runparts),
        "--generated-xml", str(xml),
        "--decoder", str(DECODER),
        "--output", "{attempt_root}/anchor/f4_s1_mk1_gravity_anchor.json",
        "--scratch-root", "{attempt_root}/scratch/bi4_decode",
        "--solver-source-jsph", str(SOURCE_JSPH),
        "--solver-source-gpu", str(SOURCE_GPU),
        "--solver-source-kernel", str(SOURCE_KERNEL),
        "--expected-frame-count", str(len(rows)),
        "--expected-final-time-s", f"{rows[-1]['time_s']:.15f}",
        "--anchor-max-time-s", f"{ANCHOR_MAX_TIME_S:.12f}",
        "--frames", *(str(frame) for frame in FRAMES),
        "--internal-pair-force-status", "UNKNOWN_NOT_DIRECTLY_OBSERVED",
    ]
    value = {
        "schema": "ds02.request.v1",
        "family_id": "F4",
        "sentinel_id": "F4-S1",
        "physical_case_id": PHYSICAL_CASE_ID,
        "case_id": case_id,
        "attempt_id": attempt_id,
        "kind": "cpu",
        "qualification_stage": "stage2_bounded_precontact_gravity_anchor_v2_pending_parent_v4_guard",
        "cpu_task_kind": "native_selected_frame_observer",
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 1800,
        "estimated_storage_bytes": 67108864,
        "estimated_peak_memory_bytes": 536870912,
        "estimated_raw_read_bytes": selected_raw_bytes,
        "estimated_selected_frame_count": len(FRAMES),
        "worktree_root": str(REPO),
        "cwd": str(REPO),
        "command": command,
        "source_binding": {
            "schema": "ds02.stage2.f4-mk1-gravity-anchor-binding.v2",
            "sentinel_id": "F4-S1",
            "physical_case_id": PHYSICAL_CASE_ID,
            "variant": key,
            "raw_root": {"path": str(raw.resolve()), "tree_scan": "FORBIDDEN", "tree_hash": "NOT_COMPUTED_BY_WORKER"},
            "selected_part_records": raw_records,
            "runparts": rec(runparts),
            "runout": rec(runout),
            "generated_xml": rec(xml),
            "solver_receipt": rec(solver_receipt),
            "solver_receipt_status": "PARENT_MUST_VERIFY_COMPLETED_RECEIPT_AND_SOURCE_POSTHASH",
            "selected_frames": FRAMES,
            "selected_times_s": [float(row["time_s"]) for row in selected_rows],
            "selected_time_brackets": [[float(row["time_s"]), float(row["time_s"])] for row in selected_rows],
            "window_policy": "0 through approximately 0.05 s; no post-contact extrapolation",
            "source_semantics": source,
            "solver_source_contract": source_contract,
            "solver_source_git_head_at_request": git_head(),
            "internal_pair_force_policy": (
                "conditional pairwise COM cancellation source contract; residual internal "
                "force is not directly present in native selected fields"
            ),
        },
        "input_files": [str(path.resolve()) for path in inputs],
        "input_hashes": input_hashes,
        "output_plan": {
            "format": "JSON",
            "fields": [
                "MK1 count/sample mass", "MK1 COM", "MK1 mean velocity",
                "exact RunPARTs timestamp", "gravity prediction/error",
                "drop-vs-pool/fixed nearest distance", "ID/mass/control gates",
            ],
            "selected_native_frames_only": True,
            "full_native_tree_scanned": False,
            "hdf5_read": False,
            "typed_conversion": "NOT_PERFORMED",
            "native_source_retained": True,
            "scientific_qualification": "UNKNOWN_LOCAL_DIAGNOSTIC_ONLY",
        },
        "frozen_tolerances": {
            "position_fraction_of_initial_domain_extent": 0.02,
            "position_scaled_nonzero_fraction": 0.05,
            "position_floor_m": 1.0e-6,
            "velocity_scaled_nonzero_fraction": 0.05,
            "velocity_scale_floor_m_per_s": 1.0e-3,
            "separation_required_factor_times_2h": 2.0,
            "decoded_time_tolerance_s": 1.0e-10,
        },
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": str(DISPATCH),
            "strict_guard": str(STRICT),
            "runtime": str(RUNTIME),
            "cpu_parent_binding": "required",
            "gpu": "none",
            "gpu_uuid": "none",
            "solver_launch": "forbidden",
            "hdf5_read": "forbidden",
            "full_native_tree_scan": "forbidden",
            "launch_disabled": True,
            "parent_v4_review_required": True,
        },
        "output_protection": {"refuse_overwrite": True, "atomic_output": True, "scratch_cleanup_per_frame": True},
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    path = OUT_ROOT / output_name
    atomic(path, value)
    return path


def build() -> list[Path]:
    configs = [
        {
            "key": "dp0_same_cfl",
            "case_id": "F4_S1_MK1_GRAVITY_ANCHOR_V2_DP0_SAME_CFL",
            "attempt_id": "f4-s1-mk1-gravity-anchor-dp0-same-cfl-v4-root-002",
            "raw": DATA / "families/F4/F4_S1_DP0_SAVEDT_SAME_CFL_DENSE_T1P2/f4-s1-dp0-savedt-same_cfl-primary-001/solver_output/data",
            "runparts": DATA / "families/F4/F4_S1_DP0_SAVEDT_SAME_CFL_DENSE_T1P2/f4-s1-dp0-savedt-same_cfl-primary-001/solver_output/RunPARTs.csv",
            "runout": DATA / "families/F4/F4_S1_DP0_SAVEDT_SAME_CFL_DENSE_T1P2/f4-s1-dp0-savedt-same_cfl-primary-001/solver_output/Run.out",
            "xml": REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f4_dp0_savedt_pair_inputs_v1/same_cfl/F4_DROP_CENTERED_REFERENCE_001_DP010_same_cfl_savedt.xml",
            "solver_receipt": DATA / "families/F4/F4_S1_DP0_SAVEDT_SAME_CFL_DENSE_T1P2/f4-s1-dp0-savedt-same_cfl-primary-001/execution-receipt.json",
            "output_root": DATA / "families/F4/F4_S1_MK1_GRAVITY_ANCHOR_V2_DP0_SAME_CFL/f4-s1-mk1-gravity-anchor-dp0-same-cfl-v4-root-002",
            "output_name": "f4_s1_dp0_same_cfl_mk1_gravity_anchor_v2.json",
        },
        {
            "key": "dp0_half_cfl",
            "case_id": "F4_S1_MK1_GRAVITY_ANCHOR_V2_DP0_HALF_CFL",
            "attempt_id": "f4-s1-mk1-gravity-anchor-dp0-half-cfl-v4-root-002",
            "raw": DATA / "families/F4/F4_S1_DP0_SAVEDT_HALF_CFL_DENSE_T1P2/f4-s1-dp0-savedt-half_cfl-primary-001/solver_output/data",
            "runparts": DATA / "families/F4/F4_S1_DP0_SAVEDT_HALF_CFL_DENSE_T1P2/f4-s1-dp0-savedt-half_cfl-primary-001/solver_output/RunPARTs.csv",
            "runout": DATA / "families/F4/F4_S1_DP0_SAVEDT_HALF_CFL_DENSE_T1P2/f4-s1-dp0-savedt-half_cfl-primary-001/solver_output/Run.out",
            "xml": REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f4_dp0_savedt_pair_inputs_v1/half_cfl/F4_DROP_CENTERED_REFERENCE_001_DP010_half_cfl_savedt.xml",
            "solver_receipt": DATA / "families/F4/F4_S1_DP0_SAVEDT_HALF_CFL_DENSE_T1P2/f4-s1-dp0-savedt-half_cfl-primary-001/execution-receipt.json",
            "output_root": DATA / "families/F4/F4_S1_MK1_GRAVITY_ANCHOR_V2_DP0_HALF_CFL/f4-s1-mk1-gravity-anchor-dp0-half-cfl-v4-root-002",
            "output_name": "f4_s1_dp0_half_cfl_mk1_gravity_anchor_v2.json",
        },
        {
            "key": "coarse_dp0123",
            "case_id": "F4_S1_MK1_GRAVITY_ANCHOR_V2_COARSE_DP01230",
            "attempt_id": "f4-s1-mk1-gravity-anchor-coarse-dp01230-v4-root-002",
            "raw": DATA / "families/F4/F4_S1_FULL_WINDOW_CANARY_COARSE_DP01230_T1P2/f4-s1-full-window-coarse-dp01230-v4-primary-001/solver_output/data",
            "runparts": DATA / "families/F4/F4_S1_FULL_WINDOW_CANARY_COARSE_DP01230_T1P2/f4-s1-full-window-coarse-dp01230-v4-primary-001/solver_output/RunPARTs.csv",
            "runout": DATA / "families/F4/F4_S1_FULL_WINDOW_CANARY_COARSE_DP01230_T1P2/f4-s1-full-window-coarse-dp01230-v4-primary-001/solver_output/Run.out",
            "xml": DATA / "families/F4/F4_S1_MASSFIT_V3_COARSE_DP0p012300/f4_s1_massfit_v3_coarse_dp0p012300-001/generated.xml",
            "solver_receipt": DATA / "families/F4/F4_S1_FULL_WINDOW_CANARY_COARSE_DP01230_T1P2/f4-s1-full-window-coarse-dp01230-v4-primary-001/execution-receipt.json",
            "output_root": DATA / "families/F4/F4_S1_MK1_GRAVITY_ANCHOR_V2_COARSE_DP01230/f4-s1-mk1-gravity-anchor-coarse-dp01230-v4-root-002",
            "output_name": "f4_s1_coarse_dp01230_mk1_gravity_anchor_v2.json",
        },
    ]
    paths: list[Path] = []
    for config in configs:
        paths.append(build_one(**config))
    return paths


if __name__ == "__main__":
    print(json.dumps({"requests": [str(path) for path in build()]}, indent=2))
