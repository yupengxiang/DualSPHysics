#!/usr/bin/env python3
"""Execute the v2 F5 CPU/native preflight through a fresh output stem.

The audited v1 runner is reused as code, while all v2 input, receipt and
output paths are rebound below.  The v1 input/output is never opened for
execution; it remains immutable failure evidence.
"""

from __future__ import annotations

import argparse
import importlib
from pathlib import Path
import sys


LAB = Path(__file__).resolve().parents[1]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))
from scripts import f5_wave_runup_preflight_v1 as base  # noqa: E402


ROOT = LAB / "campaigns/core-v1/cfd/f5-wave-runup-third-t1/fresh-definition-v2"
base.ROOT = ROOT
base.REVIEW = ROOT / "preflight-root-review-v2.json"
base.DEFINITION = ROOT / "F5_wave_runup_q0p50_dp0p0075_Def.xml"
base.OUTPUT = ROOT / "preflight-v2"
base.CASE_ID = "F5_wave_runup_q0p50_dp0p0075_v2"


def _verify_v2_receipt():
    review = base.load(base.REVIEW)
    if review["schema"] != "core.f5.third_t1.preflight_root_review_receipt.v2":
        raise ValueError("wrong F5 v2 preflight root review schema")
    if review["status"] != "authorized_one_fresh_cpu_native_preflight_only":
        raise ValueError("F5 v2 preflight is not authorized")
    if review["review_decision"]["authorized_action"] != "run_exactly_one_fresh_v2_cpu_gencase_native_decode":
        raise ValueError("wrong F5 v2 preflight action")
    if any(review["review_decision"].get(key) for key in ("authorized_solver", "authorized_gpu", "authorized_queue", "authorized_matrix")):
        raise ValueError("F5 v2 preflight receipt opens a forbidden path")
    for item in review["repair_review"].values():
        if isinstance(item, dict) and {"path", "sha256"} <= set(item):
            path = LAB / item["path"]
            if not path.is_file() or base.sha256(path) != item["sha256"]:
                raise ValueError(f"F5 v2 input hash mismatch: {path}")
    if not base.GENCASE.is_file() or not base.DECODER.is_file():
        raise FileNotFoundError("pinned GenCase or native decoder missing")
    return review


base._verify_receipt = _verify_v2_receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run-once", "verify-preflight"))
    args = parser.parse_args()
    if args.command == "run-once":
        result = base.run_once()
        print({"status": result.get("status"), "preflight_pass": result.get("preflight_pass"),
               "qualified": result.get("qualified"), "matrix_credit": result.get("matrix_credit", 0),
               "output": str(base.OUTPUT / "preflight.json")})
        return 0 if result.get("preflight_pass") else 1
    result = base.verify_materialized()
    print({"status": result.get("status"), "preflight_pass": result.get("preflight_pass"),
           "qualified": result.get("qualified"), "matrix_credit": result.get("matrix_credit", 0),
           "output": str(base.OUTPUT / "preflight.json")})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
