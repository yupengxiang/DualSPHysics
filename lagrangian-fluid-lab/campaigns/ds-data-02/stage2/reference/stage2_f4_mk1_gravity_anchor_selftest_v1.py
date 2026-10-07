#!/usr/bin/env python3
"""Manufactured reject tests for the bounded F4 gravity-anchor contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from stage2_f4_mk1_gravity_anchor_v1 import evaluate_preconditions


def base_kwargs() -> dict[str, object]:
    return {
        "mass_kg": 1.0,
        "particle_count": 2,
        "gravity": (0.0, 0.0, -9.81),
        "external_motion_status": "PASS_EMPTY_EXECUTION_MOTION_AND_NO_MOVING_FLOATING_BLOCK",
        "shifting_status": "PASS_PARAMETER_Shifting_0",
        "id_status": "PASS_NO_ID_EXCLUSION_OR_REUSE",
        "internal_pair_force_status": "PAIRWISE_INTERNAL_FORCE_COM_CANCELLATION_SOURCE_CONTRACT",
        "separation_records": [
            {"status": "PASS_FARTHER_THAN_TWO_SUPPORT_RADII"},
            {"status": "PASS_FARTHER_THAN_TWO_SUPPORT_RADII"},
        ],
    }


def run_case(name: str, **updates: object) -> dict[str, object]:
    values = base_kwargs()
    values.update(updates)
    result = evaluate_preconditions(**values)
    return {"name": name, "status": result["status"], "reasons": result["reasons"], "pass": result["status"].startswith("REJECT")}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cases = [
        run_case("zero_or_nonpositive_mass_rejected", mass_kg=0.0),
        run_case("multiple_particles_with_nonzero_internal_pair_force_rejected", internal_pair_force_status="NONZERO_INTERNAL_PAIR_FORCE"),
        run_case("contact_within_support_rejected", separation_records=[{"status": "FAIL_WITHIN_TWO_SUPPORT_RADII"}]),
        run_case("nonuniform_gravity_rejected", gravity_uniform=False),
        run_case("id_exclusion_rejected", id_status="FAIL_ID_EXCLUSION"),
    ]
    passed = all(bool(case["pass"]) for case in cases)
    value = {
        "schema": "ds02.stage2.f4-mk1-gravity-anchor-selftest.v1",
        "status": "PASS_ALL_MANUFACTURED_REJECTS" if passed else "FAIL_MANUFACTURED_REJECT",
        "cases": cases,
        "uses_native_or_h5": False,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": value["status"], "output": str(args.output)}, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
