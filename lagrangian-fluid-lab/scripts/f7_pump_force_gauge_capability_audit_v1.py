#!/usr/bin/env python3
"""Audit the official force-gauge capability for the F7 Pump proposal.

The audit is static and read-only.  It binds the official gauge implementation
and the Pump source, but never edits a Definition, runs GenCase/solver, or
changes Core state.  Its purpose is to distinguish an aggregate boundary-force
output from the direct torque provenance required by the F7 root gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
PUMP_XML = LAB / "vendor/official/DualSPHysics_v5.4/examples/main/13_Pump/CasePump_Def.xml"
GAUGE_SYSTEM = LAB / "vendor/official/DualSPHysics_v5.4/src/source/JDsGaugeSystem.cpp"
GAUGE_ITEM = LAB / "vendor/official/DualSPHysics_v5.4/src/source/JDsGaugeItem.cpp"
GAUGE_HEADER = LAB / "vendor/official/DualSPHysics_v5.4/src/source/JDsGaugeItem.h"
ROOT_REVIEW = LAB / "campaigns/core-v1/cfd/f7-pump-recirculation-root-review-20260922/root-review-receipt-v1.json"
OUTPUT = LAB / "campaigns/core-v1/cfd/f7-pump-recirculation-root-review-20260922/force-gauge-capability-audit-v1.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def bind(path: Path, role: str) -> dict[str, Any]:
    return {"path": str(path.relative_to(LAB)), "sha256": sha256(path),
            "bytes": path.stat().st_size, "role": role}


def contains(text: str, needle: str) -> bool:
    return needle in text


def build_audit() -> dict[str, Any]:
    gauge_system = GAUGE_SYSTEM.read_text(encoding="utf-8")
    gauge_item = GAUGE_ITEM.read_text(encoding="utf-8")
    gauge_header = GAUGE_HEADER.read_text(encoding="utf-8")
    pump_xml = PUMP_XML.read_text(encoding="utf-8")
    root_review = json.loads(ROOT_REVIEW.read_text(encoding="utf-8"))

    checks = {
        "force_gauge_xml_dispatch_present": contains(gauge_system, 'cmd=="force"'),
        "force_gauge_accepts_moving_boundary": contains(gauge_system, "TpPartMoving"),
        "force_gauge_reads_target_mkbound": contains(gauge_system, '"target","mkbound"'),
        "force_result_has_vector": contains(gauge_header, "tfloat3 force"),
        "force_csv_output_present": contains(gauge_item, "forcex [N];forcey [N];forcez [N]"),
        "force_vtk_output_present": contains(gauge_item, 'AddArray("Force"'),
        "force_vtk_particle_distribution_present": contains(gauge_item, "PartAcec"),
        "torque_result_field_present": contains(gauge_header, "torque") or contains(gauge_item, "torque"),
        "torque_cross_product_in_gauge": contains(gauge_item, "cross(") and contains(gauge_item, "Result"),
        "pump_moving_mk2_present": 'setmkbound mk="2"' in pump_xml,
    }
    if not all(checks[key] for key in (
        "force_gauge_xml_dispatch_present", "force_gauge_accepts_moving_boundary",
        "force_gauge_reads_target_mkbound", "force_result_has_vector",
        "force_csv_output_present", "pump_moving_mk2_present")):
        raise AssertionError("official force-gauge capability assumptions changed")

    return {
        "schema": "core.f7.pump.force_gauge_capability_audit.v1",
        "status": "root_review_only_instrumentation_gap",
        "candidate_id": "F7_pump_prescribed_internal_rotor_recirculation_v1",
        "qualification_claim": "none",
        "T1_numerical": False,
        "T2_macro": False,
        "T2_path": False,
        "qualification_credit": 0,
        "protected_state_mutation": {
            "definition": 0, "gencase": 0, "native_decode": 0, "solver": 0,
            "gpu": 0, "queue": 0, "registry": 0, "ledger": 0,
            "matrix": 0, "denominator": 0,
        },
        "official_capability": {
            "aggregate_force_on_moving_mkbound": True,
            "pump_moving_mkbound": 2,
            "force_csv_vector": True,
            "force_vtk_is_center_aggregate": True,
            "per_boundary_particle_force_output": False,
            "direct_torque_output": False,
            "torque_provenance_available": False,
        },
        "checks": checks,
        "interpretation": [
            "The official gauge can measure an aggregate force vector on moving mkbound=2 particles.",
            "The saved CSV contains only force magnitude and xyz components; the VTK result contains only the initial center and aggregate force.",
            "A fluid angular-momentum finite difference remains a response proxy, not a wall-reaction torque.",
            "F7 cannot pass its independence gate without a new solver instrumentation or geometry/force partition contract and a fresh root review.",
        ],
        "required_next_contract": {
            "new_scope_or_revision": True,
            "fresh_output_namespace": True,
            "direct_torque_source_required": True,
            "acceptable_options": [
                "instrument the moving-boundary interaction to emit per-particle force and r-cross-F torque with source hashes",
                "materialize independently labeled moving-boundary sectors and prove their force sums and torque reconstruction",
            ],
            "not_acceptable": [
                "renaming fluid angular-momentum finite differences as torque",
                "reusing the existing coarse canary as direct torque evidence",
                "starting solver/GPU/queue before root admission",
            ],
        },
        "bindings": {
            "pump_definition": bind(PUMP_XML, "official Pump definition source"),
            "gauge_system": bind(GAUGE_SYSTEM, "official force-gauge XML dispatch"),
            "gauge_item": bind(GAUGE_ITEM, "official force-gauge implementation"),
            "gauge_header": bind(GAUGE_HEADER, "official force-gauge result schema"),
            "root_review": bind(ROOT_REVIEW, "current F7 root review receipt"),
        },
        "root_review_state": {
            "admission_granted": root_review.get("admission_granted"),
            "definition_authorized": root_review.get("definition_authorized"),
            "preflight_authorized": root_review.get("preflight_authorized"),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    result = build_audit()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("schema", "status", "official_capability", "protected_state_mutation")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
