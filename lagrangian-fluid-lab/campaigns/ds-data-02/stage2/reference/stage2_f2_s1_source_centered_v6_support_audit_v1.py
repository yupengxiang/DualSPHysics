#!/usr/bin/env python3
"""Audit the parent-guarded V6 F2-S1 GenCase product.

This is a forward, additive consumer for the V6 ``actual | fluid`` support
probe.  It reads only the terminal generated XML, generated fluid VTK, and
GenCase receipt.  It verifies the candidate/source SHA and full stat before
and after the read, then delegates the binary VTK Idp decoding and per-MK
support/mass arithmetic to the already reviewed V4 parser.  It never opens
BI4/HDF5 or starts a solver.  A generated result that misses the mass or
support gate is recorded as a diagnostic failure; it is never converted to a
scientific qualification.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
from typing import Any


REPO = Path(__file__).resolve().parents[5]
REFERENCE = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
V4_WORKER = REFERENCE / "stage2_f2_s1_inner_native_geometry_audit_v4.py"
OWNER_MASS_KG = 18.876
EXPECTED_DP_M = 0.0088
EXPECTED_POINTREF = (0.0013, 0.0, 0.0004)
EXPECTED_MASS_FRACTION = 0.02


def load_v4_worker():
    spec = importlib.util.spec_from_file_location("ds02_f2_v4_geometry_audit_for_v6", V4_WORKER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load reviewed V4 parser: {V4_WORKER}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    stat = path.stat()
    return {
        "path": str(path),
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "sha256": sha256(path),
    }


def write_new(path: Path, value: Any) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise FileExistsError(f"refuse to overwrite audit output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def verify_static(path: Path, expected_sha256: str, label: str) -> dict[str, Any]:
    before = record(path)
    if before["sha256"] != expected_sha256:
        raise ValueError(f"{label} SHA mismatch before decode")
    return before


def parse_candidate_contract(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    definition = root.find("./casedef/geometry/definition")
    if definition is None:
        raise ValueError("candidate is missing casedef/geometry/definition")
    dp = float(definition.attrib["dp"])
    pointref = definition.find("pointref")
    if pointref is None:
        raise ValueError("candidate is missing pointref")
    point = tuple(float(pointref.attrib[axis]) for axis in "xyz")
    if not math.isfinite(dp) or not all(math.isfinite(v) for v in point):
        raise ValueError("candidate definition is non-finite")
    if abs(dp - EXPECTED_DP_M) > 1e-12 or any(abs(point[i] - EXPECTED_POINTREF[i]) > 1e-12 for i in range(3)):
        raise ValueError(f"unexpected candidate phase: dp={dp}, pointref={point}")
    mainlist = root.find("./casedef/geometry/commands/mainlist")
    if mainlist is None:
        raise ValueError("candidate is missing geometry mainlist")
    modes = [(node.text or "").strip() for node in mainlist.findall("setshapemode")]
    limits = [node.attrib.get("mode") for node in mainlist.findall("setboxlimitmode")]
    if modes != ["dp | bound", "actual | fluid", "dp | bound"]:
        raise ValueError(f"unexpected candidate shape-mode sequence: {modes}")
    if limits != ["inner", "full"]:
        raise ValueError(f"unexpected candidate box-limit sequence: {limits}")
    return {"dp_m": dp, "pointref_m": list(point), "shape_mode_sequence": modes, "box_limit_sequence": limits}


def parse_source_contract(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    definition = root.find("./casedef/geometry/definition")
    if definition is None or abs(float(definition.attrib["dp"]) - 0.01) > 1e-12:
        raise ValueError("unexpected frozen source definition")
    if definition.find("pointref") is not None:
        raise ValueError("frozen source unexpectedly has pointref")
    mainlist = root.find("./casedef/geometry/commands/mainlist")
    if mainlist is None:
        raise ValueError("frozen source is missing geometry mainlist")
    if [(node.text or "").strip() for node in mainlist.findall("setshapemode")] != ["dp | bound"]:
        raise ValueError("frozen source shape mode changed")
    return {"dp_m": 0.01, "pointref_m": None, "shape_mode_sequence": ["dp | bound"]}


def build_report(
    generated_xml: Path,
    fluid_vtk: Path,
    receipt_path: Path,
    candidate_def: Path,
    source_def: Path,
    source_motion: Path,
    expected: dict[str, str],
) -> dict[str, Any]:
    static_before = {
        "candidate_def": verify_static(candidate_def, expected["candidate_def"], "candidate Def"),
        "source_def": verify_static(source_def, expected["source_def"], "source Def"),
        "source_motion": verify_static(source_motion, expected["source_motion"], "source motion"),
    }
    candidate_contract = parse_candidate_contract(candidate_def)
    source_contract = parse_source_contract(source_def)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt_status = str(receipt.get("status", "")).lower()
    returncode = receipt.get("returncode", receipt.get("execution", {}).get("returncode"))
    if receipt_status not in {"completed", "complete", "success", "completed0"} or (returncode is not None and int(returncode) != 0):
        static_after = {
            key: record(Path(value["path"])) for key, value in static_before.items()
        }
        if static_before != static_after:
            raise RuntimeError("source changed while recording failed GenCase receipt")
        return {
            "schema": "ds02.stage2.f2-s1.source-centered-v6-support-audit.v1",
            "status": "GENCASE_RECEIPT_FAILED",
            "scope": {"generated_xml_read": False, "fluid_vtk_read": False, "receipt_read": True, "bi4_read": False, "hdf5_read": False, "solver_started": False},
            "receipt_scope": {"status": receipt.get("status"), "returncode": returncode, "output_root": receipt.get("output_root")},
            "inputs": {"receipt": record(receipt_path), "static_before": static_before, "static_after": static_after, "static_pre_post_equal": True},
            "candidate_contract": candidate_contract,
            "source_contract": source_contract,
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        }

    v4 = load_v4_worker()
    xml_record = record(generated_xml)
    vtk_record = record(fluid_vtk)
    # Let the reviewed parser derive the actual count from generated.xml.  A
    # count mismatch against the prediction is recorded, never treated as a
    # worker error, so a wrong candidate still leaves auditable evidence.
    xml_meta = v4.parse_definition(generated_xml)
    actual_count = int(xml_meta["fluid_count"])
    report = v4.build_report(generated_xml, fluid_vtk, receipt_path, actual_count, OWNER_MASS_KG)
    static_after = {
        key: record(Path(value["path"])) for key, value in static_before.items()
    }
    if static_before != static_after:
        raise RuntimeError("candidate/source changed during XML/VTK audit")
    if report["inputs"]["pre"] != report["inputs"]["post"]:
        raise RuntimeError("generated XML/VTK/receipt changed during audit")
    outside = [block["box_relation"]["outside_closed_count"] for block in report["fluid_blocks"]]
    total_mass = float(report["mass_audit"]["actual_sample_mass_kg"])
    relative = total_mass / OWNER_MASS_KG - 1.0
    report.update({
        "schema": "ds02.stage2.f2-s1.source-centered-v6-support-audit.v1",
        "status": "COMPLETED_V6_SUPPORT_MASS_AUDIT",
        "candidate_contract": candidate_contract,
        "source_contract": source_contract,
        "inputs": {
            **report["inputs"],
            "static_before": static_before,
            "static_after": static_after,
            "static_pre_post_equal": True,
        },
        "support_mass_gate": {
            "predicted_count": 27750,
            "actual_count": actual_count,
            "count_delta_from_prediction": actual_count - 27750,
            "actual_mass_kg": total_mass,
            "whole_initial_relative_error_fraction": relative,
            "whole_initial_relative_error_percent": 100.0 * relative,
            "outside_closed_box_counts": outside,
            "support_gate": "PASS" if sum(outside) == 0 else "FAIL_OUTSIDE_FROZEN_BOX",
            "mass_gate": report["mass_audit"]["classification"],
            "overall_initial_state_diagnostic": "PASS" if sum(outside) == 0 and abs(relative) <= 0.01 else "MARGINAL_OR_FAIL",
            "mass_rescale": False,
            "continuous_boxes_unchanged": True,
        },
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "reason": "GenCase support/mass audit only; no solver or observer qualification"},
    })
    return report


def self_test() -> dict[str, Any]:
    # Keep this test independent of campaign outputs and native payloads.
    candidate = REFERENCE / "stage2_f2_s1_source_centered_v6_support_repair_inputs/F2_S1/dp0p0088/F2_S1_SOURCE_CENTERED_V6_ACTUAL_FLUID_DP0P0088_Def.xml"
    source = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010/root-stage1-f2-f2_stage1_first48_expansion_rx056_ry014_fill080_rot090_dp010_spatial_reference_save010-actual-gencase-source801-root804/prepared/F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010_Def.xml")
    return {"status": "PASS", "candidate": parse_candidate_contract(candidate), "source": parse_source_contract(source), "native_payload_read": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--generated-xml", type=Path)
    parser.add_argument("--fluid-vtk", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--candidate-def", type=Path)
    parser.add_argument("--source-def", type=Path)
    parser.add_argument("--source-motion", type=Path)
    parser.add_argument("--expected-candidate-sha", required=False)
    parser.add_argument("--expected-source-def-sha", required=False)
    parser.add_argument("--expected-source-motion-sha", required=False)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2))
        return 0
    required = (args.generated_xml, args.fluid_vtk, args.receipt, args.candidate_def, args.source_def, args.source_motion, args.output)
    if any(value is None for value in required):
        parser.error("all generated/static paths and --output are required unless --self-test")
    if not all((args.expected_candidate_sha, args.expected_source_def_sha, args.expected_source_motion_sha)):
        parser.error("expected SHA arguments are required for source immutability")
    expected = {"candidate_def": args.expected_candidate_sha, "source_def": args.expected_source_def_sha, "source_motion": args.expected_source_motion_sha}
    report = build_report(args.generated_xml.resolve(), args.fluid_vtk.resolve(), args.receipt.resolve(), args.candidate_def.resolve(), args.source_def.resolve(), args.source_motion.resolve(), expected)
    write_new(args.output, report)
    print(json.dumps({"status": report["status"], "support_mass_gate": report.get("support_mass_gate"), "output": str(args.output.resolve())}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
