#!/usr/bin/env python3
"""Audit the completed F2 solver anchor without granting qualification.

This postrun reader checks the frozen runtime receipt, Run.out cadence/horizon,
the complete saved-frame index, and native identity/finite values on the first,
last, and fixed diagnostic sample frames.  A nonzero solver exclusion count is
retained as a hard scientific failure; no frame is deleted or renormalized.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
from typing import Any

import numpy as np

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts.core_cfd import native_frame  # noqa: E402
from scripts.f2_static_receiver_ballistic_catch_definition_writer_v1 import (  # noqa: E402
    BASE, CASE_ID, sha256,
)


ATTEMPT = LAB_ROOT / "campaigns/core-v1/runtime/attempts/f2-static-receiver-ballistic-catch-q05-anchor-infra-retry-v1/20260921T111854-b642c199de99"
PRODUCT = ATTEMPT / "product"
SOLVER_OUTPUT = PRODUCT / "solver"
RUN_OUT = SOLVER_OUTPUT / "Run.out"
PREFLIGHT = BASE / "preflight/preflight.json"
DECODER = LAB_ROOT / "campaigns/l1-resume/artifacts/bi4_dump"
OUTPUT = PRODUCT / "postrun-audit.json"
SCHEMA = "core.f2.static_receiver_ballistic_catch.solver_anchor_postrun_audit.v1"


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _ref(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def _generated_counts(preflight: dict[str, Any]) -> tuple[int, int, int]:
    counts = preflight["generated_counts"]
    return int(counts["total_particles"]), int(counts["boundary_particles"]), int(counts["fluid_particles"])


def _parse_run_out(text: str) -> dict[str, Any]:
    def number(pattern: str, cast=float, default=None):
        match = re.search(pattern, text)
        return cast(match.group(1)) if match else default
    return {
        "time_max_s": number(r"TimeMax=([0-9.eE+-]+)"),
        "output_interval_s": number(r"TimePart=([0-9.eE+-]+)"),
        "excluded_particles": number(r"Excluded particles\.*:\s*([0-9]+)", int, -1),
        "excluded_particles_density": number(r"Excluded particles due to Density\.*:\s*([0-9]+)", int, -1),
        "finished_code_zero": "Finished execution (code=0)" in text,
    }


def _frame_audit(path: Path, fluid_begin: int, fluid_count: int) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="f2-anchor-postrun-") as folder:
        ids, pos, vel, rho, metadata, info, arrays = native_frame(path, Path(folder) / "native", DECODER)
    finite = bool(np.isfinite(pos).all() and np.isfinite(vel).all() and np.isfinite(rho).all())
    unique = len(np.unique(ids)) == len(ids)
    fluid_mask = ids >= fluid_begin
    fluid_pos = pos[fluid_mask]
    outer_low = np.array([0.0, -0.45, 0.0])
    outer_high = outer_low + np.array([1.25, 0.90, 0.80])
    outside = (
        (fluid_pos[:, 0] < outer_low[0] - 1e-8) | (fluid_pos[:, 0] > outer_high[0] + 1e-8) |
        (fluid_pos[:, 1] < outer_low[1] - 1e-8) | (fluid_pos[:, 1] > outer_high[1] + 1e-8) |
        (fluid_pos[:, 2] < outer_low[2] - 1e-8)
    )
    return {
        "path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size,
        "native_particle_count": int(len(ids)), "fluid_particle_count_by_id": int(fluid_mask.sum()),
        "boundary_particle_count_by_id": int((~fluid_mask).sum()),
        "ids_unique": bool(unique), "arrays_finite": finite,
        "outer_closed_wall_endpoint_count": int(np.count_nonzero(outside)),
        "metadata": {key: value for key, value in metadata.items() if key in ("CaseNp", "CaseNfixed", "CaseNfluid", "MassFluid", "Dp")},
        "fluid_id_span_expected": [fluid_begin, fluid_begin + fluid_count - 1],
    }


def audit() -> dict[str, Any]:
    preflight = _json(PREFLIGHT)
    runtime = _json(ATTEMPT / "result.json")
    worker = _json(PRODUCT / "result.json")
    status = _json(PRODUCT / "worker-status.json")
    if runtime.get("execution_status") != "succeeded" or runtime.get("returncode") != 0:
        raise ValueError("retry runtime receipt is not successful")
    if worker.get("execution_status") != "raw_solver_complete_pending_scientific_audit":
        raise ValueError("worker raw result is not the expected completed anchor")
    text = RUN_OUT.read_text(encoding="utf-8", errors="replace")
    run = _parse_run_out(text)
    frames = sorted((SOLVER_OUTPUT / "data").glob("Part_*.bi4"))
    indices = [int(path.stem.split("_")[1]) for path in frames]
    total, boundary, fluid = _generated_counts(preflight)
    fluid_begin = int(preflight["generated_counts"]["fluid_begin"])
    expected_indices = list(range(len(frames)))
    sample_indices = sorted(set([0, len(frames) - 1, *range(0, len(frames), 60)]))
    samples = [_frame_audit(frames[index], fluid_begin, fluid) for index in sample_indices]
    all_frame_index = indices == expected_indices
    hard = {
        "runtime_success": runtime.get("execution_status") == "succeeded",
        "solver_finished_code_zero": run["finished_code_zero"],
        "requested_horizon_reached": run["time_max_s"] == 1.5,
        "native_output_cadence_registered": run["output_interval_s"] == 0.005,
        "saved_frame_index_complete": all_frame_index and len(frames) == 301,
        "sampled_identity_unique": all(item["ids_unique"] for item in samples),
        "sampled_arrays_finite": all(item["arrays_finite"] for item in samples),
        "sampled_outer_endpoints_zero": all(item["outer_closed_wall_endpoint_count"] == 0 for item in samples),
        "solver_excluded_particles_zero": run["excluded_particles"] == 0,
    }
    # The exclusion count is a scientific hard failure even though the raw
    # solver completed and all requested frames exist.
    hard_pass = bool(all(hard.values()))
    return {
        "schema": SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "raw_solver_complete_hard_integrity_pass" if hard_pass else "raw_solver_complete_scientific_hard_failure",
        "qualified": False, "qualification_claim": "none", "matrix_credit": 0,
        "runtime_receipt": _ref(ATTEMPT / "result.json", "runtime receipt"),
        "worker_result": _ref(PRODUCT / "result.json", "worker raw result"),
        "worker_status": _ref(PRODUCT / "worker-status.json", "worker status"),
        "run_out": _ref(RUN_OUT, "solver Run.out"),
        "preflight": _ref(PREFLIGHT, "CPU/native input preflight"),
        "generated_identity": {"total": total, "boundary": boundary, "fluid": fluid, "fluid_begin": fluid_begin},
        "run_out_summary": run,
        "frame_inventory": {"count": len(frames), "first": frames[0].name if frames else None,
                            "last": frames[-1].name if frames else None,
                            "indices_contiguous": all_frame_index,
                            "raw_bytes": int(sum(path.stat().st_size for path in frames))},
        "sample_indices": sample_indices, "sampled_frames": samples,
        "hard_gates": hard, "hard_integrity_pass": hard_pass,
        "event_window": {"status": "not_assessed_full_field", "qualification_credit": 0,
                         "note": "raw anchor only; exclusions must be resolved before any event or T1 claim"},
        "execution_controls": {"solver_invoked": True, "gpu_started": True, "native_postrun_decode": True,
                               "queue_mutation": 1, "ledger_mutation": 1, "registry_mutation": 0,
                               "matrix_submission": 0},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    value = audit()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
