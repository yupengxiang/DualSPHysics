#!/usr/bin/env python3
"""Prepare F6 explicit-body v3 after the v2 GenCase schema rejection.

v3 is a fresh input.  It removes ``rhopbody`` because GenCase accepts exactly
one of ``rhopbody`` and explicit ``massbody`` for a floating body.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

LAB = Path(__file__).resolve().parents[1]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts import f6_physical_anchor_explicit_body_root_review_v2 as v2  # noqa: E402


ROOT = LAB / "campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-explicit-body-root-review-v3-20260921"
IDENTITY = "CORE_F6_physical_anchor_single_body_gravity_explicit_body_v3_20260921"
BODY_ID = "F6_physical_anchor_body_delta_20260921"
REVISION = "F6_gravity_single_body_entry_buoyancy_explicit_body_metadata_v3"
SCRIPT = Path(__file__).resolve()
_V2_WRITE_DEFINITION = v2.write_definition


def configure_base() -> None:
    v2.ROOT = ROOT
    v2.IDENTITY = IDENTITY
    v2.BODY_ID = BODY_ID
    v2.REVISION = REVISION
    v2.SCRIPT = SCRIPT
    v2.configure_base()


def write_definition(path: Path) -> None:
    _V2_WRITE_DEFINITION(path)
    tree = ET.parse(path)
    floating = tree.getroot().find("./casedef/floatings/floating")
    if floating is None:
        raise ValueError("v3 Definition has no floating body")
    floating.attrib.pop("rhopbody", None)
    ET.indent(tree.getroot(), space="    ")
    tree.write(path, encoding="utf-8", xml_declaration=True)


def main() -> int:
    configure_base()
    v2.write_definition = write_definition
    receipt = v2.create(ROOT)
    proposal_path = ROOT / "proposal.json"
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    proposal["proposal_id"] = "F6_explicit_body_metadata_v3_root_review_only_20260921"
    proposal["revision_id"] = REVISION
    proposal_path.write_text(json.dumps(proposal, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    preflight_path = ROOT / "preflight.json"
    receipt = json.loads(preflight_path.read_text(encoding="utf-8"))
    receipt["proposal"] = {"path": str(proposal_path.relative_to(LAB)).replace("\\", "/"), "sha256": v2.base.sha256(proposal_path), "bytes": proposal_path.stat().st_size, "role": "v3 explicit-body root-review proposal"}
    receipt["revision_id"] = REVISION
    preflight_path.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": receipt["status"], "gate_passed": receipt["gate_passed"], "root": str(ROOT)}, ensure_ascii=False))
    return 0 if receipt["gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
