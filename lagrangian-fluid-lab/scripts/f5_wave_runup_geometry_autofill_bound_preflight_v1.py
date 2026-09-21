#!/usr/bin/env python3
"""Run the one root-reviewed v4 CPU/native preflight.

This adapter reuses the single-decode and fluid-only geometry gate from the
v3 preflight runner while rebinding every path to the fresh v4 identity.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


LAB = Path(__file__).resolve().parents[1]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))
from scripts import f5_wave_runup_geometry_repair_preflight_v1 as shared  # noqa: E402


ROOT = LAB / "campaigns/core-v1/cfd/f5-wave-runup-third-t1/geometry-repair-audit-v1"
INPUT = ROOT / "v4-input"
REVIEW = ROOT / "autofill-bound-root-review-v1.json"
CONTRACT = INPUT / "geometry-autofill-bound-contract-v1.json"
DEFINITION = INPUT / "F5_wave_runup_q0p50_dp0p0075_geomrepair_v4_Def.xml"
MOTION = INPUT / "Mov_piston_q0p50_scaled_geomrepair_v4.dat"
SLOPE = INPUT / "Slope_geomrepair_v4.stl"
BLOCKS = INPUT / "Blocks_3D_scaled_geomrepair_v4.stl"
OUTPUT = ROOT / "preflight-v4"
CASE_ID = "F5_wave_runup_q0p50_dp0p0075_geomrepair_v4"
RUNNER = LAB / "scripts/f5_wave_runup_geometry_autofill_bound_preflight_v1.py"
ROOT_REVIEW_RUNNER = LAB / "scripts/f5_wave_runup_geometry_autofill_bound_root_review_v1.py"
WRITER = LAB / "scripts/f5_wave_runup_geometry_autofill_bound_writer_v1.py"
V3_PREFLIGHT = ROOT / "preflight-v3/preflight.json"


def _verify_contract() -> dict[str, Any]:
    review = shared.load(REVIEW)
    if review.get("schema") != "core.f5.third_t1.geometry_autofill_bound_root_review_receipt.v1":
        raise ValueError("wrong v4 root-review schema")
    decision = review.get("review_decision", {})
    if review.get("status") != "authorized_one_fresh_v4_cpu_native_preflight_only" or decision.get("authorized_cpu_native_preflight") is not True:
        raise ValueError("v4 preflight is not authorized")
    if any(decision.get(key) for key in ("authorized_solver", "authorized_gpu", "authorized_queue", "authorized_registry", "authorized_ledger", "authorized_matrix")):
        raise ValueError("v4 root review opens a forbidden path")
    contract = shared.load(CONTRACT)
    if contract.get("schema") != "core.f5.third_t1.geometry_autofill_bound_materialization.v1" or contract.get("qualification_claim") != "none":
        raise ValueError("wrong v4 contract or scientific credit")
    if contract.get("fixed_contract", {}).get("same_input_retry") is not False:
        raise ValueError("v4 retry policy is open")
    if contract.get("candidate", {}).get("case_id") != CASE_ID:
        raise ValueError("v4 case identity changed")
    root_binding = contract.get("repair_lineage", {}).get("root_review")
    if not root_binding or root_binding.get("path") != shared.rel(REVIEW) or root_binding.get("sha256") != shared.sha256(REVIEW):
        raise ValueError("v4 contract is not bound to root review")
    definition = contract.get("fresh_identity", {}).get("definition", {}).get("output")
    motion = contract.get("fresh_identity", {}).get("motion", {}).get("output")
    for item in [definition, motion, *contract.get("fresh_identity", {}).get("definition_adjacent_assets", [])]:
        path = LAB / item["path"]
        if not path.is_file() or path.stat().st_size != item.get("bytes") or shared.sha256(path) != item.get("sha256"):
            raise ValueError(f"stale v4 input binding: {path}")
    prior = shared.load(V3_PREFLIGHT)
    if prior.get("matrix_credit") != 0 or prior.get("qualified") is not False or prior.get("geometry_repair", {}).get("blocks_endpoint_inside_count") != 1:
        raise ValueError("v3 failure lineage changed")
    for path in (DEFINITION, MOTION, SLOPE, BLOCKS):
        if not path.is_file():
            raise FileNotFoundError(path)
    if not shared.GENCASE.is_file() or not shared.DECODER.is_file():
        raise FileNotFoundError("pinned GenCase or decoder missing")
    return {"review": review, "contract": contract}


# Rebind the shared runner's globals.  Its run_once function uses the module
# namespace in which it was defined, so these assignments are deliberate.
shared.ROOT = ROOT
shared.INPUT = INPUT
shared.REVIEW = REVIEW
shared.CONTRACT = CONTRACT
shared.DEFINITION = DEFINITION
shared.MOTION = MOTION
shared.SLOPE = SLOPE
shared.BLOCKS = BLOCKS
shared.OUTPUT = OUTPUT
shared.CASE_ID = CASE_ID
shared.RUNNER = RUNNER
shared.ROOT_REVIEW_RUNNER = ROOT_REVIEW_RUNNER
shared.WRITER = WRITER
shared._verify_contract = _verify_contract


def run_once() -> dict[str, Any]:
    return shared.run_once()


def verify_materialized() -> dict[str, Any]:
    return shared.verify_materialized()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run-once", "verify-preflight"))
    args = parser.parse_args()
    value = run_once() if args.command == "run-once" else verify_materialized()
    print(json.dumps({"status": value.get("status"), "preflight_pass": value.get("preflight_pass"),
                      "geometry_repair": value.get("geometry_repair"), "qualified": value.get("qualified"),
                      "matrix_credit": value.get("matrix_credit", 0), "output": shared.rel(OUTPUT / "preflight.json")}, indent=2, ensure_ascii=False))
    return 0 if args.command == "verify-preflight" or value.get("preflight_pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
