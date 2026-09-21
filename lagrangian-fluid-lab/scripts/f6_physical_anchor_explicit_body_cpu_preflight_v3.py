#!/usr/bin/env python3
"""Run one CPU/native preflight for the F6 explicit-body v3 Definition."""

from __future__ import annotations

import json
from pathlib import Path
import sys

LAB = Path(__file__).resolve().parents[1]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts import f6_physical_anchor_cpu_native_preflight_v1 as runner  # noqa: E402
from scripts import f6_physical_anchor_explicit_body_root_review_v3 as review  # noqa: E402


ROOT = review.ROOT
OUTPUT = LAB / "campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-explicit-body-cpu-native-preflight-v3-20260921"


def configure() -> None:
    review.configure_base()
    runner.DEFINITION_ID = review.IDENTITY
    runner.BODY_ID = review.BODY_ID
    runner.CASE_ID = "F6_physical_anchor_explicit_body_v3_cpu_native_preflight_20260921"
    runner.AUTHORIZATION_ID = "F6_physical_anchor_explicit_body_v3_cpu_native_preflight_authorization_20260921"
    runner.OUTPUT_DIR = OUTPUT
    runner.SOURCE_DIR = ROOT
    runner.DEFINITION = ROOT / f"{review.IDENTITY}_Def.xml"
    runner.CONTRACT = ROOT / "definition-contract.json"
    runner.SIDECAR = ROOT / "body-state-force-torque-sidecar-schema.json"
    runner.EVENT = ROOT / "event-window-contract.json"
    runner.STATIC_PREFLIGHT = ROOT / "preflight.json"
    runner.PROPOSAL = ROOT / "proposal.json"


def main() -> int:
    configure()
    receipt = runner.run(OUTPUT)
    runner.verify_receipt(OUTPUT / "preflight.json")
    print(json.dumps({"status": receipt["status"], "preflight_pass": receipt.get("preflight_pass", False), "output": str(OUTPUT / "preflight.json")}, ensure_ascii=False))
    return 0 if receipt.get("status") == "cpu_native_preflight_pass_exact_one" else 1


if __name__ == "__main__":
    raise SystemExit(main())
