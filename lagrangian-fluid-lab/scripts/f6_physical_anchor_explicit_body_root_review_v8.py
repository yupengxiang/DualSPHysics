#!/usr/bin/env python3
"""Prepare F6 explicit-body v8 without nested wrapper reconfiguration."""

from __future__ import annotations

import json
from pathlib import Path
import sys

LAB = Path(__file__).resolve().parents[1]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts import f6_physical_anchor_explicit_body_root_review_v3 as v3  # noqa: E402


ROOT = LAB / "campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-explicit-body-root-review-v8-20260921"
IDENTITY = "CORE_F6_physical_anchor_single_body_gravity_explicit_body_v8_20260921"
BODY_ID = "F6_physical_anchor_body_iota_20260921"
REVISION = "F6_gravity_single_body_entry_buoyancy_explicit_body_endpoint_safe_fluid_v8"
SCRIPT = Path(__file__).resolve()


def configure() -> None:
    v3.ROOT = ROOT
    v3.IDENTITY = IDENTITY
    v3.BODY_ID = BODY_ID
    v3.REVISION = REVISION
    v3.SCRIPT = SCRIPT
    v3.configure_base()
    v3.v2.base.FLUID_LOW = (0.18, 0.08, 0.04)
    v3.v2.base.FLUID_SIZE = (1.1399, 0.4399, 0.2399)
    v3.v2.write_definition = v3.write_definition


def main() -> int:
    configure()
    receipt = v3.v2.create(ROOT)
    proposal_path = ROOT / "proposal.json"
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    proposal["proposal_id"] = "F6_explicit_body_metadata_v8_root_review_only_20260921"
    proposal["revision_id"] = REVISION
    proposal_path.write_text(json.dumps(proposal, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    preflight_path = ROOT / "preflight.json"
    receipt = json.loads(preflight_path.read_text(encoding="utf-8"))
    receipt["proposal"] = {"path": str(proposal_path.relative_to(LAB)).replace("\\", "/"), "sha256": v3.v2.base.sha256(proposal_path), "bytes": proposal_path.stat().st_size, "role": "v8 explicit-body root-review proposal"}
    receipt["revision_id"] = REVISION
    preflight_path.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": receipt["status"], "gate_passed": receipt["gate_passed"], "root": str(ROOT)}, ensure_ascii=False))
    return 0 if receipt["gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
