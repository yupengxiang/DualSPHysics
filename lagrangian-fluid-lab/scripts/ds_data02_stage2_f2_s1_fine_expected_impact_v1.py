#!/usr/bin/env python3
"""Prepare the source-bound expectation sidecar for F2 fine native impact.

This metadata-only report freezes the exact whole-fluid denominator, native
type/MK XML ranges, original three x-low IDs, and the diagnostics that must be
joined from the new primary002 decoder and the x-low paired control. It reads
small completed solver/RunPARTs/Run.out/XML evidence only; it does not open H5,
trajectory BI4, or start a solver. Dynamical fate and impact remain UNKNOWN.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

SCRIPT = Path(__file__).resolve()
V1_SCRIPT_DEFAULT = SCRIPT.parent / "ds_data02_stage2_f2_s1_fine_native_impact_v1.py"
FINE_REQUEST_DEFAULT = SCRIPT.parents[1] / "campaigns/ds-data-02/stage2/requests/f2-s1-fine-native-impact-v2/decode-f2-s1-fine.json"
FINE_SCOPE_DEFAULT = SCRIPT.parents[1] / "campaigns/ds-data-02/stage2/evidence/f2-s1-fine-native-input-scope-v1.json"
DOMAIN_FINDING_DEFAULT = SCRIPT.parents[1] / "campaigns/ds-data-02/stage2/checkpoints/F2_S1_DOMAIN_FINDING_001.json"
DOMAIN_CONTROL_REQUEST_DEFAULT = SCRIPT.parents[1] / "campaigns/ds-data-02/stage2/requests/f2-s1-domain-extension-v2/f2_s1_original_dp010_domain_xlow_extended.json"
DOMAIN_CONTROL_EVIDENCE_DEFAULT = SCRIPT.parents[1] / "campaigns/ds-data-02/stage2/evidence/f2-s1-domain-extension-canonical-v2.json"
SCHEMA = "ds02.stage2.f2-s1-fine-native-expected-impact.v1"
PHYSICAL_CASE_ID = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090"
FINE_CASE_ID = "F2_S1_FINE_FULL_REFERENCE_DP00855_T4_SAME_CFL_DENSE"
MOTHER_INITIAL_FLUID_MASS_KG = 21.060888732
EXPECTED_MASSFLUID_KG = 0.000625026375
EXPECTED_FLUID_COUNT = 33696
PRIMARY002_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_S1_FINE_NATIVE_IMPACT_AUDIT_V2/f2-s1-fine-partvtkout-v2-primary-002")
PRIMARY002_RECEIPT = PRIMARY002_ROOT / "execution-receipt.json"


class ExpectedReportError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(value: str | Path, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise ExpectedReportError(f"{label} is missing: {path}")
    return path


def read_json(value: str | Path, label: str) -> tuple[Path, dict[str, Any]]:
    path = require_file(value, label)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExpectedReportError(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ExpectedReportError(f"{label} is not an object: {path}")
    return path, payload


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def load_v1(path: Path):
    spec = importlib.util.spec_from_file_location("ds02_f2_fine_impact_v1_for_expected", path)
    if spec is None or spec.loader is None:
        raise ExpectedReportError(f"cannot load v1 parser: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def descendants(root: ET.Element, tag: str):
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] == tag:
            yield node


def parse_xml(path: Path) -> dict[str, Any]:
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise ExpectedReportError(f"fine generated XML is invalid: {path}") from exc
    particles = next(descendants(root, "particles"), None)
    constants = next(descendants(root, "constants"), None)
    if particles is None or constants is None:
        raise ExpectedReportError("fine XML lacks particles/constants")
    groups = []
    for node in particles:
        tag = node.tag.rsplit("}", 1)[-1]
        if tag not in {"fluid", "floating", "fixed", "moving"} or node.get("begin") is None:
            continue
        groups.append({
            "role": tag, "type": {"fluid": 3, "floating": 2, "fixed": 0, "moving": 1}[tag],
            "mk": int(node.get("mk", "0")), "begin": int(node.get("begin", "0")),
            "count": int(node.get("count", "0")),
        })
    fluid = [row for row in groups if row["type"] == 3]
    mass_node = next((node for node in descendants(root, "massfluid") if node.get("value") is not None), None)
    if not fluid or mass_node is None:
        raise ExpectedReportError("fine XML lacks fluid ranges or MassFluid")
    massfluid = float(mass_node.get("value", "nan"))
    count = sum(row["count"] for row in fluid)
    if count != EXPECTED_FLUID_COUNT or not math.isclose(massfluid, EXPECTED_MASSFLUID_KG, rel_tol=0, abs_tol=1e-15):
        raise ExpectedReportError(f"fine XML changed fluid identity: count={count}, mass={massfluid}")
    calculated = count * massfluid
    if not math.isclose(calculated, MOTHER_INITIAL_FLUID_MASS_KG, rel_tol=0, abs_tol=1e-12):
        raise ExpectedReportError("XML diagnostic sum does not match frozen mother denominator")
    domain = next(descendants(root, "simulationdomain"), None)
    if domain is None:
        raise ExpectedReportError("fine XML lacks simulationdomain")
    bounds = {}
    for key in ("posmin", "posmax"):
        node = next((item for item in domain if item.tag.rsplit("}", 1)[-1] == key), None)
        if node is None:
            raise ExpectedReportError(f"fine XML lacks {key}")
        bounds[key] = [float(node.get(axis)) for axis in "xyz"]
    return {
        "path": str(path.resolve()), "sha256": sha256(path),
        "fluid_count": count, "massfluid_kg": massfluid,
        "xml_product_mass_kg": calculated, "simulationdomain": bounds,
        "all_typed_ranges": groups, "fluid_mk_type_ranges": fluid,
    }


def main_report(fine_request_path: Path, scope_path: Path, domain_path: Path,
                control_request_path: Path, control_evidence_path: Path,
                v1_script_path: Path, output: Path) -> dict[str, Any]:
    v1 = load_v1(require_file(v1_script_path, "fine v1 parser"))
    fine_req_path, fine_request = read_json(fine_request_path, "fine native v2 request")
    scope_path, scope = read_json(scope_path, "fine native scope")
    domain_path, domain = read_json(domain_path, "original domain finding")
    control_req_path, control_req = read_json(control_request_path, "x-low control request")
    control_ev_path, control_ev = read_json(control_evidence_path, "x-low control evidence")
    if fine_request.get("case_id") != "F2_S1_FINE_NATIVE_IMPACT_AUDIT_V2":
        raise ExpectedReportError("fine request is not canonical v2")
    solver_path = require_file(fine_request.get("source_solver_receipt", ""), "fine source solver receipt")
    solver = read_json(solver_path, "fine source solver receipt")[1]
    source = v1._solver_sources(solver_path, solver)
    xml = parse_xml(source["generated_xml"])
    runparts = v1.parse_runparts(source["runparts"])
    runout = v1.parse_run_out(source["run_out"])
    if runparts["totals"]["NpOut"] != 175 or runparts["totals"]["NpOutPos"] != 175 or runparts["totals"]["NpOutRho"] != 0 or runparts["totals"]["NpOutMov"] != 0:
        raise ExpectedReportError(f"fine RunPARTs totals changed: {runparts['totals']}")
    exclusions = domain.get("exclusions", [])
    if domain.get("physical_case_id") != PHYSICAL_CASE_ID or len(exclusions) != 3:
        raise ExpectedReportError("original three-ID domain finding identity changed")
    original_three = []
    for item in exclusions:
        original_three.append({
            "idp": int(item["idp"]), "native_position_m": item["native_position_m"],
            "outside_axes": item.get("outside_axes", []),
        })
    if {row["idp"] for row in original_three} != {397194, 403829, 404024}:
        raise ExpectedReportError("original three IDs changed")
    if control_req.get("case_id") != "F2_S1_ORIGINAL_DP010_DOMAIN_XLOW_EXTENDED_V2" or control_ev.get("schema") != "ds02.stage2.f2-s1-domain-extension-canonical-v2.v1":
        raise ExpectedReportError("x-low control source identity changed")
    report = {
        "schema": SCHEMA, "status": "EXPECTED_PENDING_PRIMARY002_AUDIT",
        "family_id": "F2", "physical_case_id": PHYSICAL_CASE_ID,
        "fine_reference_case_id": FINE_CASE_ID,
        "mother_initial_wholefluid_mass_kg": MOTHER_INITIAL_FLUID_MASS_KG,
        "mass_denominator_policy": (
            "Frozen mother denominator is actual fine XML fluid count times MassFluid "
            "and is recorded as a diagnostic cross-check; native typed source mass "
            "from a completed decoder join is required before any per-MK impact claim."
        ),
        "source": {
            "fine_request": {"path": str(fine_req_path), "sha256": sha256(fine_req_path)},
            "fine_scope": {"path": str(scope_path), "sha256": sha256(scope_path)},
            "solver_receipt": {"path": str(solver_path), "sha256": sha256(solver_path)},
            "generated_xml": xml,
            "runparts": {"path": str(source["runparts"]), "sha256": sha256(source["runparts"]), "rows": len(runparts["rows"]), "terminal_time_s": runparts["rows"][-1]["time_s"], "totals": runparts["totals"]},
            "runout": runout,
            "domain_finding": {"path": str(domain_path), "sha256": sha256(domain_path)},
        },
        "native_mk_type_xml_ranges": {
            "fluid_ranges": xml["fluid_mk_type_ranges"],
            "all_typed_ranges": xml["all_typed_ranges"],
            "fluid_count": xml["fluid_count"], "massfluid_kg": xml["massfluid_kg"],
            "xml_product_mass_kg": xml["xml_product_mass_kg"],
        },
        "original_three_ids": {
            "source": {"path": str(domain_path), "sha256": sha256(domain_path)},
            "records": original_three,
            "interpretation": "Original native x-low position evidence; not assumed to be the fine175 missing set until primary002 CSV proves exact IDs."
        },
        "fine_primary002_native_observation": {
            "status": "PENDING_PRIMARY002_AND_AUDIT",
            "expected_decoder_receipt": {"path": str(PRIMARY002_RECEIPT)},
            "expected_decoder_attempt_id": "f2-s1-fine-partvtkout-v2-primary-002",
            "required_join_fields": ["Idp", "PartOut", "Motive", "Pos.x [m]", "Pos.y [m]", "Pos.z [m]", "Vel.x [m/s]", "Vel.y [m/s]", "Vel.z [m/s]", "Rhop [kg/m^3]"],
            "first_gap_policy": "Use RunPARTs previous normal Part and first native PartOut Part; do not infer endpoint from expected 802.",
            "source_closure_required": ["official PartVTKOut", "DsphConfig.xml", "strace open trace", "PartOut_000.obi4", "RunPARTs.csv", "Run.out", "completed decoder receipt"],
            "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN",
        },
        "xlow_control_diagnosis": {
            "original_xlow_m": xml["simulationdomain"]["posmin"][0],
            "control_xlow_m": -1.60,
            "control_request": {"path": str(control_req_path), "sha256": sha256(control_req_path)},
            "control_evidence": {"path": str(control_ev_path), "sha256": sha256(control_ev_path)},
            "immutable_reuse": control_ev.get("immutable_reuse", {}),
            "domain_semantic_diff": control_ev.get("domain_semantic_diff", {}),
            "source_solver_receipt": control_ev.get("source_solver_receipt", {}),
            "factor_policy": "Only numerical x-low domain bound changes; XML, initial BI4, and motion source are required identical.",
            "required_observations": ["PartOut exact IDs/motives/positions", "RunPARTs first-gap/time totals", "Run.out MapRealPos", "native typed mass per MK"],
            "diagnosis": "NOT_YET_OBSERVED; no claim that x-low extension fixes or changes the exclusion mechanism.",
        },
        "interpretation": {
            "mass_fraction": "Report missing mass only after exact native IDs are joined to typed MK/mass; no XML mass is added to missing mass.",
            "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QN": "NOT_ASSESSED", "QE": "NOT_ASSESSED",
        },
        "read_policy": {"h5_opened": False, "trajectory_content_opened": False, "solver_started": False, "partvtkout_started": False},
    }
    atomic_json(output, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fine-request", type=Path, default=FINE_REQUEST_DEFAULT)
    parser.add_argument("--scope", type=Path, default=FINE_SCOPE_DEFAULT)
    parser.add_argument("--domain-finding", type=Path, default=DOMAIN_FINDING_DEFAULT)
    parser.add_argument("--control-request", type=Path, default=DOMAIN_CONTROL_REQUEST_DEFAULT)
    parser.add_argument("--control-evidence", type=Path, default=DOMAIN_CONTROL_EVIDENCE_DEFAULT)
    parser.add_argument("--v1-script", type=Path, default=V1_SCRIPT_DEFAULT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = main_report(args.fine_request, args.scope, args.domain_finding,
                             args.control_request, args.control_evidence,
                             args.v1_script, args.output)
    except ExpectedReportError as exc:
        raise SystemExit(f"ExpectedReportError: {exc}")
    print(json.dumps({"status": result["status"], "output": str(args.output.resolve())}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
