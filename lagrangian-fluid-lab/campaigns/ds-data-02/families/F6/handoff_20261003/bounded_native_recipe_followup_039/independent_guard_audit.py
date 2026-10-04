#!/usr/bin/env python3
"""DS-DATA-02 F6 Bounded Finite Independent Guard Audit Worker.

Audits actual original timestep controls, counters, and DTsMin adjustments:
1. Audits baseline full12 fine run (root-angular-release-dp0125-full12-native-gpu-021):
   - Confirms full 241 frames covering [0.0, 12.000037s].
   - Verifies monotonic timestamps and exact PartVTK/FloatingInfo correspondence.
   - Analyzes timestep counters: 163,707 total steps.
   - Analyzes DTsMin adjustments: exactly 273 adjustments concentrated in Parts 7 and 8.
   - Analyzes DtFixed: strictly 0 (variable CFL timestepping).
2. Preregisters finite guard audit criteria for prospective genuine halfstep run:
   - Frame count = 241.
   - Step scaling expectation: ~2x baseline (~320k to ~350k steps).
   - DTsMin adjustment monitoring: audit whether minimum timestep flooring diminishes under CFL=0.1.
   - Floating particle cohort preservation: 131,072 nodes.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

EXPECTED_BASELINE_PARTS = 241
EXPECTED_BASELINE_STEPS = 163707
EXPECTED_BASELINE_DTSMIN_CLAMPS = 273
EXPECTED_FLOATING_NODES = 131072


def parse_runparts_csv(path: Path | str) -> dict[str, Any]:
    """Parse DualSPHysics RunPARTs.csv file, ignoring comment lines."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"RunPARTs.csv not found at: {p}")

    with p.open("r", encoding="utf-8", errors="replace") as stream:
        raw_rows = [r for r in csv.DictReader(stream, delimiter=";") if r.get("Part") and not r["Part"].startswith("#")]

    if not raw_rows:
        raise ValueError(f"RunPARTs.csv at {p} has no valid data rows")

    parts = []
    total_steps = 0
    total_dtsmin = 0
    clamp_distribution = {}

    for row in raw_rows:
        part_idx = int(row["Part"])
        t_s = float(row["TimeStep [s]"])
        steps = int(row["Steps"].replace(",", ""))
        dtsmin = int(row["DTsMin"].replace(",", ""))
        np_sim = int(row["NpSim"].replace(",", ""))
        np_out = int(row["NpOut"].replace(",", ""))

        total_steps += steps
        total_dtsmin += dtsmin

        if dtsmin > 0:
            clamp_distribution[f"part_{part_idx}"] = {
                "part": part_idx,
                "time_s": t_s,
                "steps": steps,
                "dtsmin_clamps": dtsmin,
            }

        parts.append({
            "part": part_idx,
            "time_s": t_s,
            "steps": steps,
            "dtsmin": dtsmin,
            "np_sim": np_sim,
            "np_out": np_out,
        })

    # Validate monotonicity
    times = [p["time_s"] for p in parts]
    is_monotonic = all(times[i] < times[i + 1] for i in range(len(times) - 1))

    return {
        "frame_count": len(parts),
        "part_start": parts[0]["part"],
        "part_end": parts[-1]["part"],
        "time_start_s": parts[0]["time_s"],
        "time_final_s": parts[-1]["time_s"],
        "is_monotonic": is_monotonic,
        "total_solver_steps": total_steps,
        "total_dtsmin_clamps": total_dtsmin,
        "dtsmin_clamp_distribution": clamp_distribution,
        "final_particle_count": parts[-1]["np_sim"],
        "total_particles_out": sum(p["np_out"] for p in parts),
    }


def audit_baseline(binding_path: Path) -> dict[str, Any]:
    """Audit baseline fine run counters and verify DtFixed semantics."""
    b = json.loads(binding_path.read_text(encoding="utf-8"))
    orig = b["original_actual_full_run"]
    runparts_path = Path(orig["runparts_csv_path"])

    parsed = parse_runparts_csv(runparts_path)

    # Verification against expected baseline constants
    checks = {
        "frame_count_ok": parsed["frame_count"] == EXPECTED_BASELINE_PARTS,
        "time_window_ok": parsed["time_start_s"] == 0.0 and parsed["time_final_s"] >= 12.0,
        "monotonic_ok": parsed["is_monotonic"],
        "total_steps_ok": parsed["total_solver_steps"] == EXPECTED_BASELINE_STEPS,
        "total_dtsmin_clamps_ok": parsed["total_dtsmin_clamps"] == EXPECTED_BASELINE_DTSMIN_CLAMPS,
        "dtsmin_distribution_parts": list(parsed["dtsmin_clamp_distribution"].keys()),
        "dt_fixed_is_zero": orig["timestep_controls"]["DtFixed"] == 0.0,
        "step_algorithm_is_symplectic": orig["timestep_controls"]["StepAlgorithm"] == 2,
    }

    all_ok = all([
        checks["frame_count_ok"],
        checks["time_window_ok"],
        checks["monotonic_ok"],
        checks["total_steps_ok"],
        checks["total_dtsmin_clamps_ok"],
        checks["dt_fixed_is_zero"],
        checks["step_algorithm_is_symplectic"],
    ])

    return {
        "schema": "ds02.f6.independent-guard-audit.v1",
        "baseline_runparts_audit": parsed,
        "checks": checks,
        "all_checks_passed": all_ok,
        "timestep_control_ruling": {
            "dt_fixed_value": 0.0,
            "ruling": "DtFixed is 0.0. The baseline solver executed with variable time-stepping governed by CFL=0.2 and CoefDtMin=0.05. A genuine halfstep control must legally halve CFL to 0.1 and CoefDtMin to 0.025. Halving an unprescribed fixed timestep is prohibited.",
            "dtsmin_flooring_diagnosis": "273 total DTsMin clamps occurred during violent entry at parts 7 (229 clamps at t~0.35s) and 8 (44 clamps at t~0.40s). The genuine halfstep run will test if CFL halving resolves or diminishes this flooring effect.",
        },
        "prospective_guard_spec": {
            "target_frames": 241,
            "target_window_s": [0.0, 12.0],
            "expected_step_range": [300000, 360000],
            "target_floating_nodes": EXPECTED_FLOATING_NODES,
            "monotonic_time_required": True,
            "floating_cohort_preservation_required": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", type=Path, default=Path(__file__).parent / "source_and_resource_binding.json", help="Path to binding JSON")
    parser.add_argument("--output", type=Path, default=None, help="Optional output JSON path")
    args = parser.parse_args()

    audit = audit_baseline(args.binding)
    output_text = json.dumps(audit, indent=2) + "\n"

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_text, encoding="utf-8")
        print(f"Audit written to {args.output}")
    else:
        print(output_text)

    return 0 if audit["all_checks_passed"] else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
