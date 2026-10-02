#!/usr/bin/env python3
"""Audit the generated rigid contract after F6 phase-aligned PartVTK QA.

The CPU PartVTK receipts and typed/mass audit are already immutable.  This
additive sidecar reads the corresponding generated XML files and checks the
actual serialized aggregate mass, center, inertia, and wave-piston controls.
It keeps the type-2 particle MassBound sum separate from the explicit
aggregate ``massbody`` value and grants no solver qualification.
"""

from __future__ import annotations

import importlib.util
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
V2 = SCRIPT.with_name("ds_data02_f6_handoff_20261002_dp020_dp0125_partvtk_v2.py")
SPEC = importlib.util.spec_from_file_location("f6_dp020_dp0125_partvtk_v2_for_rigid_audit", V2)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load PartVTK v2 sidecar: {V2}")
BASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BASE)
MODULE = BASE.MODULE

ROOT = MODULE.FAMILY_ROOT
AUDIT_INPUT = ROOT / "strict_partvtk_audit_002.json"
MANIFEST = ROOT / "manifest.json"
PARTVTK_MANIFEST = ROOT / "partvtk_request_manifest_002.json"
OUTPUT = ROOT / "strict_partvtk_rigid_audit_003.json"
EXPECTED_CENTER = [2.4, 1.2, 1.08]
EXPECTED_INERTIA = [8.533333333333335, 8.533333333333335, 13.653333333333336]
EXPECTED_MASSBODY = 128.0


def _float_attr(node: ET.Element, name: str) -> float:
    value = node.attrib.get(name)
    if value is None:
        raise ValueError(f"missing XML attribute {name} on <{node.tag}>")
    return float(value)


def _generated_xml_contract(xml_path: Path, mechanism: str) -> dict[str, Any]:
    root = ET.parse(xml_path).getroot()
    floating = next(
        (node for node in root.iter("floating") if node.attrib.get("mk") == "60" and node.find("center") is not None),
        None,
    )
    if floating is None:
        raise ValueError(f"actual generated floating mk=60 contract missing: {xml_path}")
    massbody = floating.find("massbody")
    center = floating.find("center")
    inertia = floating.find("inertia")
    if massbody is None or center is None or inertia is None:
        raise ValueError(f"actual generated floating contract incomplete: {xml_path}")
    actual_center = [_float_attr(center, axis) for axis in ("x", "y", "z")]
    actual_inertia = [_float_attr(inertia, axis) for axis in ("x", "y", "z")]
    actual_massbody = _float_attr(massbody, "value")

    piston = next(iter(root.iter("piston")), None)
    motion_obj = next((node for node in root.iter("objreal") if node.attrib.get("ref") == "10"), None)
    if mechanism == "wave_no_contact":
        if piston is None:
            raise ValueError(f"wave piston block missing: {xml_path}")
        piston_values = {
            "mkbound": int(float(piston.find("mkbound").attrib["value"])),
            "depth_m": float(piston.find("depth").attrib["value"]),
            "waveheight_m": float(piston.find("waveheight").attrib["value"]),
            "waveperiod_s": float(piston.find("waveperiod").attrib["value"]),
            "ramp_periods": float(piston.find("ramp").attrib["value"]),
        }
        control_checks = {
            "piston_mk10": piston_values["mkbound"] == 10,
            "piston_depth_0p84": abs(piston_values["depth_m"] - 0.84) <= 1.0e-12,
            "piston_waveheight_0p12": abs(piston_values["waveheight_m"] - 0.12) <= 1.0e-12,
            "piston_waveperiod_1p6": abs(piston_values["waveperiod_s"] - 1.6) <= 1.0e-12,
            "piston_ramp_3": abs(piston_values["ramp_periods"] - 3.0) <= 1.0e-12,
            "moving_object_ref10": motion_obj is not None,
        }
    else:
        piston_values = None
        control_checks = {"no_wave_piston_for_simple": piston is None}

    # GenCase serializes the generated native XML with fewer digits than the
    # source Definition (for example 13.6533333333 -> 13.6533).  Keep the
    # source contract hash in the request lineage and audit this native
    # round-trip against a documented 5e-5 kg*m^2 serialization tolerance.
    contract_checks = {
        "aggregate_massbody_128kg": abs(actual_massbody - EXPECTED_MASSBODY) <= 1.0e-12,
        "aggregate_center_exact": all(abs(a - b) <= 1.0e-12 for a, b in zip(actual_center, EXPECTED_CENTER)),
        "aggregate_inertia_positive": all(value > 0.0 for value in actual_inertia),
        "aggregate_inertia_matches_frozen_contract": all(abs(a - b) <= 5.0e-5 for a, b in zip(actual_inertia, EXPECTED_INERTIA)),
    }
    return {
        "xml": str(xml_path.resolve()),
        "xml_sha256": MODULE.sha256(xml_path),
        "aggregate_massbody_kg": actual_massbody,
        "aggregate_center_m": actual_center,
        "aggregate_inertia_diag_kg_m2": actual_inertia,
        "native_xml_inertia_serialization_tolerance_kg_m2": 5.0e-5,
        "native_xml_inertia_abs_error_kg_m2": [abs(a - b) for a, b in zip(actual_inertia, EXPECTED_INERTIA)],
        "piston_controls": piston_values,
        "checks": {**contract_checks, **control_checks},
        "pass": all(contract_checks.values()) and all(control_checks.values()),
        "aggregate_massbody_is_separate_from_type2_massbound_sum": True,
    }


def _source_definition_contract(definition_path: Path) -> dict[str, Any]:
    root = ET.parse(definition_path).getroot()
    floating = next((node for node in root.iter("floating") if node.attrib.get("mkbound") == "50"), None)
    if floating is None:
        raise ValueError(f"source Definition floating contract missing: {definition_path}")
    massbody = floating.find("massbody")
    center = floating.find("center")
    inertia = floating.find("inertia")
    if massbody is None or center is None or inertia is None:
        raise ValueError(f"source Definition rigid contract incomplete: {definition_path}")
    source_center = [_float_attr(center, axis) for axis in ("x", "y", "z")]
    source_inertia = [_float_attr(inertia, axis) for axis in ("x", "y", "z")]
    checks = {
        "source_massbody_128kg": abs(_float_attr(massbody, "value") - EXPECTED_MASSBODY) <= 1.0e-12,
        "source_center_exact": all(abs(a - b) <= 1.0e-12 for a, b in zip(source_center, EXPECTED_CENTER)),
        "source_inertia_exact": all(abs(a - b) <= 5.0e-10 for a, b in zip(source_inertia, EXPECTED_INERTIA)),
    }
    return {
        "definition": str(definition_path.resolve()),
        "definition_sha256": MODULE.sha256(definition_path),
        "massbody_kg": _float_attr(massbody, "value"),
        "center_m": source_center,
        "inertia_diag_kg_m2": source_inertia,
        "source_inertia_serialization_tolerance_kg_m2": 5.0e-10,
        "checks": checks,
        "pass": all(checks.values()),
    }


def audit() -> dict[str, Any]:
    base = MODULE.read_json(AUDIT_INPUT)
    manifest = MODULE.read_json(MANIFEST)
    by_case = {str(row["case_id"]): row for row in manifest["cases"]}
    rows: list[dict[str, Any]] = []
    for row in base["cases"]:
        cid = str(row["case_id"])
        case = by_case[cid]
        attempt = str(case["request"]["attempt_id"])
        xml_path = MODULE._attempt_root(cid, attempt) / f"{cid}.xml"
        contract = _generated_xml_contract(xml_path, str(case["mechanism_id"]))
        source_contract = _source_definition_contract(Path(case["definition"]["path"]))
        contract["source_definition_contract"] = source_contract
        contract["checks"]["source_definition_contract_exact"] = bool(source_contract["pass"])
        contract["pass"] = bool(contract["pass"]) and bool(source_contract["pass"])
        enriched = dict(row)
        enriched["generated_xml_rigid_contract"] = contract
        enriched["preflight_pass"] = bool(row.get("preflight_pass")) and bool(contract["pass"])
        rows.append(enriched)

    result = {
        "schema": "ds-data-02.f6.rigid_contract_003.dp020-dp0125.partvtk_rigid_audit.v3",
        "family_id": "F6",
        "status": "all_four_generated_rigid_contracts_pass" if all(row["preflight_pass"] for row in rows) else "generated_rigid_contract_audit_failed",
        "source_partvtk_audit": str(AUDIT_INPUT.resolve()),
        "source_partvtk_audit_sha256": MODULE.sha256(AUDIT_INPUT),
        "source_partvtk_manifest": str(PARTVTK_MANIFEST.resolve()),
        "source_partvtk_manifest_sha256": MODULE.sha256(PARTVTK_MANIFEST),
        "phase_aligned_gencase_source": str(V2.resolve()),
        "phase_aligned_gencase_source_sha256": MODULE.sha256(V2),
        "frozen_rigid_contract": {"massbody_kg": EXPECTED_MASSBODY, "center_m": EXPECTED_CENTER, "inertia_diag_kg_m2": EXPECTED_INERTIA},
        "cases": rows,
        "gpu_launch": False,
        "qualification_claim": "none",
        "q_i_status": "typed_initial_state_and_generated_xml_rigid_contract_preflight_only",
        "q_n_status": "pending_root_review_and_solver_three_resolution_reference",
    }
    MODULE.write_json(OUTPUT, result)
    return result


def main() -> int:
    print(json.dumps(audit(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
