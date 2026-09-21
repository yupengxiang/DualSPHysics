#!/usr/bin/env python3
"""Prepare the F6 explicit-body v9 support-volume Definition.

The v3--v8 iterations established the explicit rigid-body metadata but left a
GenCase endpoint convention unresolved: a drawbox includes both endpoint
support centres, so a continuous box of size ``n * dp`` creates ``n + 1``
centres.  v9 keeps the continuous fluid volume in the immutable contract and
uses ``size - dp`` only for the fresh GenCase drawbox.  The mass gate is still
computed from the continuous box, and every generated centre must remain
inside it.  This is a new CPU/native preflight input; it does not authorize a
solver or GPU run.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

LAB = Path(__file__).resolve().parents[1]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts import f6_physical_anchor_explicit_body_root_review_v3 as v3  # noqa: E402


ROOT = LAB / "campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-explicit-body-root-review-v9-20260921"
IDENTITY = "CORE_F6_physical_anchor_single_body_gravity_explicit_body_v9_20260921"
BODY_ID = "F6_physical_anchor_body_kappa_20260921"
REVISION = "F6_gravity_single_body_entry_buoyancy_explicit_body_support_volume_v9"
SCRIPT = Path(__file__).resolve()


def _sampling_contract() -> dict[str, object]:
    continuous = tuple(float(value) for value in v3.v2.base.FLUID_SIZE)
    drawbox = tuple(value - v3.v2.base.DP_M for value in continuous)
    return {
        "mode": "endpoint_safe_support_centres",
        "dp_m": v3.v2.base.DP_M,
        "continuous_box_size_m": list(continuous),
        "drawbox_size_m": list(drawbox),
        "drawbox_high_m": [v3.v2.base.FLUID_LOW[i] + drawbox[i] for i in range(3)],
        "endpoint_rule": "GenCase includes both endpoint support centres; drawbox size is continuous_size_minus_dp",
        "continuous_volume_mass_gate": True,
        "particle_centres_inside_continuous_box": True,
        "mass_gate_definition": "MassFluid * native fluid particle count versus density * continuous_box_volume",
    }


def configure() -> None:
    v3.ROOT = ROOT
    v3.IDENTITY = IDENTITY
    v3.BODY_ID = BODY_ID
    v3.REVISION = REVISION
    v3.SCRIPT = SCRIPT
    v3.configure_base()
    v3.v2.base.FLUID_LOW = (0.18, 0.08, 0.04)
    v3.v2.base.FLUID_SIZE = (1.14, 0.44, 0.24)

    # v3 removes rhopbody and adds explicit mass/COM/inertia.  Add only the
    # support-volume drawbox adjustment on top of that fresh writer.
    original_write_definition = v3.write_definition

    def write_definition(path: Path) -> None:
        original_write_definition(path)
        tree = ET.parse(path)
        node = tree.getroot().find("./casedef/geometry/commands/mainlist/drawbox")
        if node is None:
            raise ValueError("v9 Definition has no fluid drawbox")
        size = node.find("size")
        if size is None:
            raise ValueError("v9 fluid drawbox has no size")
        drawbox = [value - v3.v2.base.DP_M for value in v3.v2.base.FLUID_SIZE]
        for axis, value in zip("xyz", drawbox):
            size.set(axis, f"{value:.17g}")
        ET.indent(tree.getroot(), space="    ")
        tree.write(path, encoding="utf-8", xml_declaration=True)

    v3.v2.write_definition = write_definition

    # The contract retains the continuous volume while registering the exact
    # drawbox convention consumed by static and native preflight.
    original_fluid_model = v3.v2.base.fluid_model

    def fluid_model() -> dict[str, object]:
        value = original_fluid_model()
        value["sampling_contract"] = _sampling_contract()
        return value

    v3.v2.base.fluid_model = fluid_model


def main() -> int:
    configure()
    v3.v2.create(ROOT)
    proposal_path = ROOT / "proposal.json"
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    proposal["proposal_id"] = "F6_explicit_body_support_volume_v9_root_review_only_20260921"
    proposal["revision_id"] = REVISION
    proposal["support_volume_contract"] = _sampling_contract()
    proposal_path.write_text(json.dumps(proposal, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    preflight_path = ROOT / "preflight.json"
    receipt = json.loads(preflight_path.read_text(encoding="utf-8"))
    receipt["proposal"] = {
        "path": str(proposal_path.relative_to(LAB)).replace("\\", "/"),
        "sha256": v3.v2.base.sha256(proposal_path),
        "bytes": proposal_path.stat().st_size,
        "role": "v9 explicit-body support-volume root-review proposal",
    }
    receipt["revision_id"] = REVISION
    receipt["support_volume_contract"] = _sampling_contract()
    preflight_path.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": receipt["status"], "gate_passed": receipt["gate_passed"], "root": str(ROOT)}, ensure_ascii=False))
    return 0 if receipt["gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
