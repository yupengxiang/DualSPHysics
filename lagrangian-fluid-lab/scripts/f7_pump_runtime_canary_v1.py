#!/usr/bin/env python3
"""Prepare, but never execute, an isolated official Pump runtime canary.

The official example wrapper is intentionally not used: it recursively deletes
its output directory and prompts interactively.  This module only validates
the immutable Pump sources and emits a direct-command plan for a future,
separately authorized canary.  It never invokes GenCase, the solver, native
decoding, GPU work, the queue, or any Core registry/ledger mutation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from scripts.f7_pump_geometry_adapter_v1 import (
    DEFAULT_DEFINITION,
    DEFAULT_FIXED,
    DEFAULT_MOVING,
    OFFICIAL_SOURCE_SHA256,
    parse_pump_definition,
)


LAB = Path(__file__).resolve().parents[1]
BIN_DIR = LAB / "vendor/official/DualSPHysics_v5.4/bin/linux"
GENCASE = BIN_DIR / "GenCase_linux64"
SOLVER_CPU = BIN_DIR / "DualSPHysics5.4CPU_linux64"
DECODER = LAB / "campaigns/l1-resume/artifacts/bi4_dump"
SCHEMA = "core.f7.pump.runtime_canary_plan.v1"
OFFICIAL_DP_M = 0.004


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _binding(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": str(path), "sha256": sha256_file(path), "bytes": path.stat().st_size, "role": role}


def _safe_output_root(path: Path) -> Path:
    path = Path(path).expanduser().resolve()
    if path == LAB or LAB in path.parents:
        raise ValueError("runtime canary output must not be inside the source lab")
    if path.exists() and any(path.iterdir()):
        raise ValueError("runtime canary output must be a fresh or empty directory")
    return path


def prepare_plan(output_root: str | Path, *, time_max_s: float | None = None,
                 time_out_s: float | None = None, dp_m: float = OFFICIAL_DP_M) -> dict[str, Any]:
    """Return a hash-bound direct-command plan without executing anything."""
    output_root = _safe_output_root(Path(output_root))
    contract = parse_pump_definition(DEFAULT_DEFINITION)
    requested_time_max = contract["time_max_s"] if time_max_s is None else float(time_max_s)
    requested_time_out = contract["time_out_s"] if time_out_s is None else float(time_out_s)
    dp_m = float(dp_m)
    if not math.isfinite(dp_m) or dp_m <= 0:
        raise ValueError("canary dp_m must be positive and finite")
    if requested_time_max <= 0 or requested_time_max > contract["time_max_s"]:
        raise ValueError("canary time_max_s must be positive and no greater than the official TimeMax")
    if requested_time_out <= 0 or requested_time_out > requested_time_max:
        raise ValueError("canary time_out_s must be positive and no greater than time_max_s")

    source_paths = {
        "definition": DEFAULT_DEFINITION,
        "fixed_geometry": DEFAULT_FIXED,
        "moving_geometry": DEFAULT_MOVING,
    }
    source_bindings = []
    for key, path in source_paths.items():
        binding = _binding(path, f"immutable official Pump {key} source")
        expected = OFFICIAL_SOURCE_SHA256[path.name]
        if binding["sha256"] != expected:
            raise ValueError(f"official Pump source hash mismatch: {path.name}")
        source_bindings.append(binding)
    binaries = [
        _binding(GENCASE, "direct GenCase executable; not invoked by this plan"),
        _binding(SOLVER_CPU, "direct CPU solver executable; not invoked by this plan"),
        _binding(DECODER, "native BI4 decoder; not invoked by this plan"),
    ]
    generated_prefix = output_root / "generated" / "CasePump"
    solver_output = output_root / "solver"
    return {
        "schema": SCHEMA,
        "status": "prepared_only_not_executed",
        "source_contract": {
            "official_source_hashes_verified": True,
            "definition": str(DEFAULT_DEFINITION.resolve()),
            "fixed_geometry": str(DEFAULT_FIXED.resolve()),
            "moving_geometry": str(DEFAULT_MOVING.resolve()),
            "fluid_mk": contract["fluid_mk"],
            "moving_boundary_mk": contract["moving_mk"],
            "motion_sha256": contract["motion_sha256"],
            "time_max_s": requested_time_max,
            "time_out_s": requested_time_out,
            "dp_m": dp_m,
        },
        "source_bindings": source_bindings,
        "binary_bindings": binaries,
        "execution_plan": {
            "working_directory": str(output_root),
            "generated_prefix": str(generated_prefix),
            "solver_output": str(solver_output),
            "gencase_argv": [str(GENCASE), str(DEFAULT_DEFINITION.with_suffix("")), str(generated_prefix), "-save:all"],
            "solver_cpu_argv": [str(SOLVER_CPU), str(generated_prefix), str(solver_output)],
            "native_decode_input": str(solver_output / "data"),
            "native_decode_executable": str(DECODER),
            "destructive_wrapper_used": False,
            "recursive_cleanup_requested": False,
            "interactive_wrapper_used": False,
        },
        "execution_boundary": {
            "prepare_invoked": True,
            "gencase_invoked": False,
            "solver_invoked": False,
            "native_decoder_invoked": False,
            "gpu_started": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "qualification_credit": 0,
            "runtime_evidence": False,
        },
        "required_future_evidence": [
            "fresh generated XML and BI4 output hash-bound to this plan",
            "decoded fluid identity and finite-array audit",
            "trajectory time axis covering the declared canary window",
            "explicit control sidecar and observer result bound to the trajectory",
            "root review of any solver result before Core admission",
        ],
    }


def write_plan(path: str | Path, *, output_root: str | Path,
               time_max_s: float | None = None, time_out_s: float | None = None,
               dp_m: float = OFFICIAL_DP_M) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise FileExistsError(f"refusing to overwrite runtime plan: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = prepare_plan(output_root, time_max_s=time_max_s, time_out_s=time_out_s, dp_m=dp_m)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-plan", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--time-max", type=float)
    parser.add_argument("--time-out", type=float)
    parser.add_argument("--dp", type=float, default=OFFICIAL_DP_M)
    args = parser.parse_args()
    payload = write_plan(args.output_plan, output_root=args.output_root,
                         time_max_s=args.time_max, time_out_s=args.time_out, dp_m=args.dp)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
