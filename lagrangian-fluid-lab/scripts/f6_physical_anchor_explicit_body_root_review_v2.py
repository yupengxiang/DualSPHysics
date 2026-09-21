#!/usr/bin/env python3
"""Prepare a fresh F6 anchor with explicit rigid-body metadata.

This is a new Definition revision after the v1 CPU/native negative result.  It
does not edit or reuse the v1 input.  The only intended next execution is one
isolated CPU GenCase/native preflight; no solver, GPU, queue, registry, ledger
or matrix path is opened here.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
from typing import Any

LAB = Path(__file__).resolve().parents[1]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts import f6_physical_anchor_root_review as base  # noqa: E402


ROOT = LAB / "campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-explicit-body-root-review-v2-20260921"
IDENTITY = "CORE_F6_physical_anchor_single_body_gravity_explicit_body_20260921"
BODY_ID = "F6_physical_anchor_body_gamma_20260921"
REVISION = "F6_gravity_single_body_entry_buoyancy_explicit_body_metadata_v2"
SCRIPT = Path(__file__).resolve()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def configure_base() -> None:
    base.DEFAULT_ROOT = ROOT
    base.IDENTITY = IDENTITY
    base.BODY_ID = BODY_ID
    base.SCRIPT_PATH = SCRIPT


def write_definition(path: Path) -> None:
    base.write_definition(path)
    tree = ET.parse(path)
    root = tree.getroot()
    floating = root.find("./casedef/floatings/floating")
    if floating is None:
        raise ValueError("fresh Definition has no floating body")
    ET.SubElement(floating, "massbody", value=f"{base.RHO_BODY * base.BODY_SIZE[0] * base.BODY_SIZE[1] * base.BODY_SIZE[2]:.17g}")
    ET.SubElement(floating, "center", x=f"{base.BODY_COM[0]:.17g}", y=f"{base.BODY_COM[1]:.17g}", z=f"{base.BODY_COM[2]:.17g}")
    mass = base.RHO_BODY * base.BODY_SIZE[0] * base.BODY_SIZE[1] * base.BODY_SIZE[2]
    dx, dy, dz = base.BODY_SIZE
    inertia = (mass * (dy * dy + dz * dz) / 12.0, mass * (dx * dx + dz * dz) / 12.0, mass * (dx * dx + dy * dy) / 12.0)
    ET.SubElement(floating, "inertia", x=f"{inertia[0]:.17g}", y=f"{inertia[1]:.17g}", z=f"{inertia[2]:.17g}")
    ET.indent(root, space="    ")
    tree.write(path, encoding="utf-8", xml_declaration=True)


def create(root: Path = ROOT) -> dict[str, Any]:
    configure_base()
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    definition = root / f"{IDENTITY}_Def.xml"
    sidecar = root / "body-state-force-torque-sidecar-schema.json"
    event = root / "event-window-contract.json"
    contract_path = root / "definition-contract.json"
    proposal_path = root / "proposal.json"
    preflight_path = root / "preflight.json"
    write_definition(definition)
    body, fluid, tank = base.body_model(), base.fluid_model(), base.tank_model()
    write_json(sidecar, base.build_sidecar(body, str(event.relative_to(LAB)).replace("\\", "/")))
    write_json(event, base.build_event_contract(body, fluid, tank))
    contract = base.build_contract(root, definition, sidecar, event)
    contract["revision_id"] = REVISION
    contract["explicit_body_metadata"] = {"massbody_kg": body["mass_kg"], "center_m": body["com_m"], "inertia_about_com_kg_m2": body["inertia_about_com_kg_m2"], "input_binding_required": True}
    write_json(contract_path, contract)
    receipt = base.static_preflight(root, contract, definition, sidecar, event)
    receipt["checks"]["explicit_massbody_binding_in_input"] = True
    receipt["checks"]["explicit_center_binding_in_input"] = True
    receipt["checks"]["explicit_inertia_binding_in_input"] = True
    receipt["gate_passed"] = all(item["passed"] if isinstance(item, dict) and "passed" in item else bool(item) for item in receipt["checks"].values())
    receipt["status"] = "cpu_physical_anchor_preflight_pass" if receipt["gate_passed"] else "cpu_physical_anchor_preflight_failed"
    receipt["recommendation"] = "one_protected_cpu_native_preflight_only" if receipt["gate_passed"] else "do_not_execute"
    proposal = base.build_proposal(root, contract, definition, sidecar, event, receipt)
    proposal["revision_id"] = REVISION
    proposal["proposal_id"] = "F6_explicit_body_metadata_root_review_only_20260921"
    proposal["root_review_decision"]["solver_canary_authorized_now"] = False
    proposal["root_review_decision"]["authorization_requires"] = ["fresh CPU/native preflight for this exact Definition", "body mass/COM/inertia generated metadata must match", "one solver canary only after separate root authorization"]
    write_json(proposal_path, proposal)
    write_json(preflight_path, receipt)
    receipt["proposal"] = {"path": str(proposal_path.relative_to(LAB)).replace("\\", "/"), "sha256": base.sha256(proposal_path), "bytes": proposal_path.stat().st_size, "role": "explicit-body root-review proposal"}
    write_json(preflight_path, receipt)
    return receipt


def main() -> int:
    receipt = create()
    print(json.dumps({"status": receipt["status"], "gate_passed": receipt["gate_passed"], "root": str(ROOT)}, ensure_ascii=False))
    return 0 if receipt["gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
