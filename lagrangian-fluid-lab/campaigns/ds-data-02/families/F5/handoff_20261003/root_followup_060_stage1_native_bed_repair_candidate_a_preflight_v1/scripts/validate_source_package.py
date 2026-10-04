#!/usr/bin/env python3
"""Validate the disabled F5 candidate-A source package without native arrays."""
from __future__ import annotations
import argparse, hashlib, json, re
from pathlib import Path
import xml.etree.ElementTree as ET

def sha(p: Path) -> str:
    h=hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024), b""): h.update(chunk)
    return h.hexdigest()

def load(p): return json.loads(Path(p).read_text(encoding="utf-8"))

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--scope", type=Path, default=Path(__file__).resolve().parents[1]); a=ap.parse_args(); s=a.scope
    patch=load(s/"candidate_a_patch.json"); assert patch["candidate_id"]=="A_explicit_closed_mesh_only"
    src=Path(patch["immutable_source"]["path"]); dst=Path(patch["derived_definition"]["path"]); assert sha(src)==patch["immutable_source"]["sha256"]; assert sha(dst)==patch["derived_definition"]["sha256"]
    raw=src.read_text(encoding="utf-8").splitlines(); derived=dst.read_text(encoding="utf-8").splitlines()
    assert len(raw)-len(derived)==3
    assert all(x in raw[268] + raw[269] + raw[270] for x in ["setmkbound", "drawfilestl", "shapeout"])
    assert "drawfilestl" not in dst.read_text(encoding="utf-8") and "shapeout file=\"continuous_bed\"" not in dst.read_text(encoding="utf-8")
    root=ET.parse(dst).getroot(); tri=root.find(".//drawtriangles"); assert tri is not None and len(tri.findall("./points/point"))==156 and len(tri.findall("./triangles/triangle"))==52
    assert root.find(".//clipplane") is not None and root.find(".//drawbox[@cmt=\"initial_fluid_equilibrium_cell_centres_dp020\"]") is not None
    assert root.find(".//motion//mvpredef/file") is not None
    evidence=load(s/"audit_057_bounded_summary.json"); assert evidence["native_identity"]["native_mk40_matches_xml_all_frames"]
    assert all(len(fr["bed_segment_bins"])==6 and fr["near_mid_y_strip_count"]==0 for fr in evidence["frame_reports"])
    assert evidence["frame_reports"][0]["relative_layer_summary"]["evaluated_layer_min"]==-32
    for name in ("gencase-request.json","initial-qa-request.json","short-event-solver-request.json"):
        req=load(s/name); assert req["launch_allowed"] is False
    assert load(s/"gencase-request.json")["cpu_task_kind"]=="gencase"
    assert load(s/"initial-qa-request.json")["cpu_task_kind"]=="audit"
    assert load(s/"short-event-solver-request.json")["kind"]=="qualification"
    assert not load(s/"manifest.json")["source_files_modified"]
    report={"schema":"ds02.f5.stage1.native-bed-repair-candidate-a-source-review.v1","status":"completed_static_source_review","scope":str(s),"source_arrays_opened":False,"source_files_modified":False,"gencase_invoked":False,"solver_invoked":False,"conversion_invoked":False,"paraview_invoked":False,"candidate_id":patch["candidate_id"],"candidate_a_definition_sha256":sha(dst),"explicit_mesh_points":156,"explicit_mesh_triangles":52,"removed_source_lines":[269,270,271],"audit_report_sha256":evidence["source_report_sha256"],"disabled_requests":[name for name in ("gencase-request.json","initial-qa-request.json","short-event-solver-request.json")],"interpretation_boundary":load(s/"manifest.json")["claim_boundary"]}
    (s/"source-review.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print("source package validation passed: candidate A, bounded 057 summary, three disabled stages")
if __name__=="__main__": main()
