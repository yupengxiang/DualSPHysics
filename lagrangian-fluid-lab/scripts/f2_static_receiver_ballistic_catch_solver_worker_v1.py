#!/usr/bin/env python3
"""Run one protected F2 solver anchor and retain raw output only.

The worker is intentionally narrower than a qualification runner.  It runs
DualSPHysics once on the already-passed fresh GenCase input, writes an
execution receipt, and does not register a scope, append a matrix row, or
interpret the trajectory scientifically.  Native conversion and event
auditing are separate post-run steps.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts.core_cfd import environment

SOLVER = LAB_ROOT / "vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64"


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def _inventory(root: Path) -> dict[str, Any]:
    files = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            files.append({"path": str(path.relative_to(root)), "bytes": path.stat().st_size, "sha256": sha256(path)})
    frames = sorted(root.glob("data/Part_*.bi4"))
    return {
        "files": files,
        "frame_count": len(frames),
        "frame_names": [path.name for path in frames],
        "total_bytes": int(sum(item["bytes"] for item in files)),
    }


def run(output: Path, generated_prefix: Path, time_max_s: float, output_interval_s: float) -> int:
    output = Path(output).resolve()
    generated_prefix = Path(generated_prefix).resolve()
    solver_output = output / "solver"
    stdout_path = output / "solver.stdout.log"
    result_path = output / "result.json"
    status_path = output / "worker-status.json"
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"anchor output is not fresh: {output}")
    if not generated_prefix.with_suffix(".xml").is_file() or not generated_prefix.with_suffix(".bi4").is_file():
        raise FileNotFoundError("fresh GenCase XML/BI4 input is missing")
    if not SOLVER.is_file():
        raise FileNotFoundError(SOLVER)
    visible = os.environ.get("CUDA_VISIBLE_DEVICES", "")
    if not visible or "," in visible:
        raise ValueError("runtime must supply exactly one CUDA_VISIBLE_DEVICES value")
    output.mkdir(parents=True, exist_ok=True)
    argv = [str(SOLVER), "-gpu:0", str(generated_prefix), str(solver_output)]
    started = time.monotonic()
    write_json(status_path, {
        "schema": "core.f2.static_receiver_ballistic_catch.worker_status.v1",
        "status": "running", "started_at": datetime.now(timezone.utc).isoformat(),
        "cuda_visible_devices": visible, "argv": argv,
        "time_max_s": time_max_s, "output_interval_s": output_interval_s,
        "qualification_claim": "none", "matrix_credit": 0,
    })
    # DualSPHysics is dynamically linked against the official binary
    # directory.  The first anchor attempt intentionally exposed this missing
    # runtime binding; the repaired worker preserves the same scientific
    # inputs and only fixes the execution environment.
    env = environment(LAB_ROOT)
    env["CUDA_VISIBLE_DEVICES"] = visible
    with stdout_path.open("w", encoding="utf-8") as log:
        process = subprocess.run(argv, cwd=output, env=env, stdout=log, stderr=subprocess.STDOUT)
    elapsed = time.monotonic() - started
    stdout = stdout_path.read_text(encoding="utf-8", errors="replace")
    run_out = solver_output / "Run.out"
    finished_marker = "Finished execution (code=0)" in stdout or (run_out.is_file() and "Finished execution (code=0)" in run_out.read_text(errors="replace"))
    inventory = _inventory(solver_output) if solver_output.exists() else {"files": [], "frame_count": 0, "total_bytes": 0}
    successful = process.returncode == 0 and finished_marker
    result = {
        "schema": "core.f2.static_receiver_ballistic_catch.solver_anchor_result.v1",
        "execution_status": "raw_solver_complete_pending_scientific_audit" if successful else "raw_solver_failed",
        "returncode": int(process.returncode), "finished_marker": bool(finished_marker),
        "elapsed_seconds": elapsed, "time_max_s": time_max_s,
        "output_interval_s": output_interval_s, "frame_inventory": inventory,
        "solver_binary": {"path": str(SOLVER), "sha256": sha256(SOLVER), "bytes": SOLVER.stat().st_size},
        "generated_prefix": str(generated_prefix),
        "generated_xml_sha256": sha256(generated_prefix.with_suffix(".xml")),
        "generated_bi4_sha256": sha256(generated_prefix.with_suffix(".bi4")),
        "qualification_claim": "none", "qualified": False, "matrix_credit": 0,
        "registry_mutation": 0, "ledger_mutation": 0, "matrix_submission": 0,
        "scientific_status": "pending_postrun_native_and_event_audit",
    }
    write_json(result_path, result)
    write_json(status_path, {
        "schema": "core.f2_static_receiver_ballistic_catch.worker_status.v1",
        "status": "complete_raw_anchor" if successful else "solver_failed",
        "returncode": int(process.returncode), "finished_marker": bool(finished_marker),
        "elapsed_seconds": elapsed, "frame_count": inventory.get("frame_count", 0),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "qualification_claim": "none", "matrix_credit": 0,
    })
    return 0 if successful else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--generated-prefix", type=Path, required=True)
    parser.add_argument("--time-max", type=float, default=1.5)
    parser.add_argument("--output-interval", type=float, default=0.005)
    args = parser.parse_args()
    return run(args.output, args.generated_prefix, args.time_max, args.output_interval)


if __name__ == "__main__":
    raise SystemExit(main())
