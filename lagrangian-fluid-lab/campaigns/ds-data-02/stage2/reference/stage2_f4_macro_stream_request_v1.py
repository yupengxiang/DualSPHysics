#!/usr/bin/env python3
"""Register the parent-dispatch request for the complete F4 macro stream."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile


REPO = Path(__file__).resolve().parents[5]
REQUEST_DIR = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-f4-macro-stream-v1"
WORKER = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f4_macro_stream_observer_v1.py"
FIELD_WORKER = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f4_physical_observer_v1.py"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
DISPATCH = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v4.py")
STRICT = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v4.py")
RUNTIME = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_runtime_v4.py")
RAW = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F4/F4_S1_FULL_WINDOW_CANARY_COARSE_DP01230_T1P2/f4-s1-full-window-coarse-dp01230-v4-primary-001/solver_output/data")
RUNPARTS = RAW.parent / "RunPARTs.csv"
RUNOUT = RAW.parent / "Run.out"
XML = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F4/F4_S1_MASSFIT_V3_COARSE_DP0p012300/f4_s1_massfit_v3_coarse_dp0p012300-001/generated.xml")
SOLVER_RECEIPT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F4/F4_S1_FULL_WINDOW_CANARY_COARSE_DP01230_T1P2/f4-s1-full-window-coarse-dp01230-v4-primary-001/execution-receipt.json")
GENCASE_RECEIPT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F4/F4_S1_MASSFIT_V3_COARSE_DP0p012300/f4_s1_massfit_v3_coarse_dp0p012300-001/execution-receipt.json")
CANARY_REQUEST = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-full-window-canary-v1/f4_s1_coarse_dp00123_same_cfl_dense.json"
OUT = REQUEST_DIR / "f4_s1_full_window_macro_stream_observer.json"
RAW_BYTES = 3649738491
FRAME_COUNT = 2401
FINAL_TIME = 1.200061449336894
PHYSICAL_CASE_ID = "F4_DROP_gap0p22000_xoff0p00000_yoff0p00000_uz0p50000"


def sha256(path: Path) -> str:
    d = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            d.update(block)
    return d.hexdigest()


def rec(path: Path, digest: bool = True) -> dict[str, object]:
    s = path.stat()
    return {"path": str(path.resolve()), "bytes": s.st_size, "mtime_ns": s.st_mtime_ns, "sha256": sha256(path) if digest else "PARENT_V4_GUARD_REQUIRED_BEFORE_DISPATCH"}


def atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(path)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def build() -> Path:
    attempt_root = "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F4/F4_S1_FULL_WINDOW_MACRO_STREAM_OBSERVER_V1/f4-s1-full-window-macro-stream-observer-v1-root-001"
    inputs = [WORKER, FIELD_WORKER, PYTHON, DECODER, DISPATCH, STRICT, RUNTIME, RUNPARTS, RUNOUT, XML, SOLVER_RECEIPT, GENCASE_RECEIPT, CANARY_REQUEST]
    result = {
        "schema": "ds02.request.v1",
        "family_id": "F4",
        "case_id": "F4_S1_FULL_WINDOW_MACRO_STREAM_OBSERVER_V1",
        "sentinel_id": "F4-S1",
        "physical_case_id": PHYSICAL_CASE_ID,
        "attempt_id": "f4-s1-full-window-macro-stream-observer-v1-root-001",
        "kind": "cpu",
        "qualification_stage": "stage2_full_native_macro_observer_pending_parent_cpu_guard",
        "cpu_task_kind": "conversion",
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 3600,
        "estimated_storage_bytes": 536870912,
        "estimated_peak_memory_bytes": 536870912,
        "estimated_raw_read_bytes": RAW_BYTES,
        "estimated_decode_read_bytes": RAW_BYTES,
        "worktree_root": str(REPO),
        "cwd": str(REPO),
        "command": [str(PYTHON), str(WORKER), "--raw-root", str(RAW), "--runparts", str(RUNPARTS), "--generated-xml", str(XML), "--decoder", str(DECODER), "--output", "{attempt_root}/observer/f4_s1_macro_stream_observables.jsonl", "--scratch-root", "{attempt_root}/scratch/bi4_decode", "--expected-frame-count", str(FRAME_COUNT), "--expected-raw-bytes", str(RAW_BYTES), "--expected-final-time-s", f"{FINAL_TIME:.15f}", "--query-times", "0.0", "0.3", "0.6", "0.9", "1.2"],
        "source_binding": {
            "schema": "ds02.stage2.f4-macro-stream-binding.v1",
            "raw_root": rec(RAW, digest=False),
            "raw_tree_contract": {"frame_count": FRAME_COUNT, "raw_part_bytes": RAW_BYTES, "first": rec(RAW / "Part_0000.bi4", digest=False), "last": rec(RAW / "Part_2400.bi4", digest=False), "full_tree_hash": "COMPUTED_BY_WORKER_AND_PARENT_GUARD"},
            "runparts": rec(RUNPARTS), "runout": rec(RUNOUT), "generated_xml": rec(XML),
            "solver_receipt": rec(SOLVER_RECEIPT), "gencase_receipt": rec(GENCASE_RECEIPT),
            "physical_window_s": [0.0, FINAL_TIME],
            "query_times_s": [0.0, 0.3, 0.6, 0.9, 1.2],
            "query_sampling": "exact/bracketed statuses retained; no interpolation or extrapolation",
            "decoded_fields": ["Idp", "Pos/Posd", "Vel", "Rhop"],
            "observables": ["fluid sample mass", "whole-fluid centroid", "whole-fluid mean velocity", "whole-fluid kinetic energy", "density mean", "per-MK region count/mass/centroid/velocity/kinetic energy"],
            "mass_semantics": "native particle sample mass only; not continuum or rigid body mass",
            "scientific_status": "UNKNOWN_UNTIL_CONSUMER_CALIBRATION",
        },
        "input_files": [str(x) for x in inputs],
        "input_hashes": {str(x): sha256(x) for x in inputs},
        "native_payload_hash_policy": "worker streams and hashes each Part; parent v4 guard must verify source pre/post and terminal combined digest; no source copy or deletion",
        "output_plan": {"format": "JSONL", "manifest_line": 1, "frame_lines": FRAME_COUNT, "summary_line": 1, "native_source_retained": True, "typed_conversion": "NOT_PERFORMED", "hdf5": "NOT_READ_OR_CREATED"},
        "resource_guard": {"owner": "stage2-reference-preparation", "runner": str(DISPATCH), "strict_guard": str(STRICT), "runtime": str(RUNTIME), "cpu_parent_binding": "required", "gpu": "none", "gpu_uuid": "none", "solver_launch": "forbidden", "hdf5_read": "forbidden", "launch_disabled": True, "parent_cpu_guard_required": True},
        "output_protection": {"refuse_overwrite": True, "atomic_output": True, "scratch_cleanup_per_frame": True},
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    atomic(OUT, result)
    return OUT


if __name__ == "__main__":
    print(json.dumps({"request": str(build())}, indent=2))
