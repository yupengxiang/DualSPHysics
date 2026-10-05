#!/usr/bin/env python3
"""Metadata/XML-only validation for F5 fresh082; no arrays or jobs."""
from __future__ import annotations
import ast, hashlib, json
import xml.etree.ElementTree as ET
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
CASE = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082"

def sha(p: Path) -> str:
    h=hashlib.sha256()
    with p.open("rb") as f:
        while True:
            b=f.read(1024*1024)
            if not b: break
            h.update(b)
    return h.hexdigest()

def load(rel): return json.loads((PKG/rel).read_text())

def main():
    root=ET.parse(PKG/f"candidate_source/{CASE}_Def.xml").getroot()
    assert root.tag == "case"
    xml_text=(PKG/f"candidate_source/{CASE}_Def.xml").read_text()
    assert "<drawextrude closed=\"true\"" in xml_text
    # Reject the actual STL/autofill commands while allowing provenance prose
    # to mention the failed STL mechanism that this fallback replaces.
    assert "<drawfilestl" not in xml_text and 'autofill="' not in xml_text
    assert xml_text.count("<point x=") >= 14
    assert "<extrude x=\"0\" y=\"0.44\" z=\"0\" />" in xml_text
    assert "<setmkbound mk=\"40\"" in xml_text
    assert "<layers vdp=\"0,1,2,3,4\"" in xml_text
    assert "assets/f5_compact_packet_motion.dat" in xml_text
    assert "TimeMax\" value=\"16.0\"" in xml_text and "TimeOut\" value=\"0.02\"" in xml_text
    recipe=load("canonical-physical-recipe.json")
    assert recipe["bed"]["closed"] is True and recipe["bed"]["stl_dependency"] is False
    assert recipe["bed"]["bed_y_bounds_m"] == [-0.22,0.22]
    assert recipe["support_geometry_basis"]["vertical_thickness_at_least_two_h"] is True
    for rel in ("gencase-request.json","initial-qa-request.json","initial-bed-coverage-request.json","short-native-qualification-request.json","typed-conversion-request-template.json","xmf-request-template.json","short-bed-audit-request.json"):
        obj=load(rel)
        assert obj["execution_allowed"] is False and obj["launch_allowed"] is False and obj.get("solver_allowed",False) is False
        assert obj.get("full801_authorized") is False
    bed=load("short-bed-audit-binding-template.json")
    assert bed["native_bed_marker_mk"] == 50 and bed["source_bed_marker_mkbound"] == 40
    assert bed["bed_y_bounds_m"] == [-0.22,0.22]
    assert bed["penetration_bins_m"] == [0.02,0.04]
    for rel in ("workers/initial_qa_worker.py","workers/direct_native_initial_fixed_bed_coverage.py","workers/bed_audit.py","scripts/verify_fresh082.py"):
        ast.parse((PKG/rel).read_text(), filename=str(PKG/rel))
    manifest=load("manifest.json")
    assert manifest["arrays_opened_by_source_agent"] is False and manifest["jobs_started"] is False
    assert manifest["full801_authorized"] is False
    print("fresh082 metadata/XML/source checks passed")

if __name__ == "__main__": main()
