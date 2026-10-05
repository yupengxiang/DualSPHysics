#!/usr/bin/env python3
"""Static source-only preflight for F7 fresh072.

Reads request JSON and source metadata only; it never opens BI4/CSV/H5/motion bytes.
"""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path

CASES = [f"F7_OBSTACLE_QUINTIC_B08_A{x:03d}" for x in (31,32,33,34,36,37,38,39,41,42,43,44,46,47,48,49)]
RAW_SUFFIXES = (".bi4",".csv",".h5",".dat",".ibi4")

def sha(p: Path) -> str:
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()

def load(p: Path): return json.loads(p.read_text())

def fail(msg): raise SystemExit("fresh072 preflight failed: "+msg)

def check_request(p: Path, kind: str):
    d=load(p)
    if d.get("launch") is not False or d.get("launch_allowed") is not False or d.get("execution_allowed") is not False or d.get("disabled") is not True:
        fail(f"{p}: request is enabled")
    if d.get("future_hashes_null") is not True: fail(f"{p}: future_hashes_null missing")
    if d.get("source_only") is not True: fail(f"{p}: source_only missing")
    if d.get("model_profile") != "gpt-5.6-luna/max": fail(f"{p}: model profile")
    if d.get("expected_frames") != 601 or d.get("expected_native_frames") != 601: fail(f"{p}: frame contract")
    if d.get("producer_scope_schema") != "ds-data-02.physical-binding.v1": fail(f"{p}: producer_scope_schema")
    counts=d.get("expected_counts")
    if counts != {"total":70179,"fixed":27495,"moving":1984,"fluid":40700,"floating":0,"dimension":3}: fail(f"{p}: dynamic counts {counts}")
    files=[str(x) for x in d.get("input_files",[])]
    hashes=d.get("input_sha256",{})
    if set(files) != set(hashes): fail(f"{p}: input_files/input_sha256 not closed")
    if len(files) != len(set(files)): fail(f"{p}: duplicate input")
    for s in files:
        q=Path(s)
        if not q.is_absolute() or not q.is_file(): fail(f"{p}: missing input {s}")
        if any(s.lower().endswith(x) for x in RAW_SUFFIXES) or "/solver_output/data/" in s:
            fail(f"{p}: scientific payload registered {s}")
        if sha(q) != hashes[s]: fail(f"{p}: input hash mismatch {s}")
    if kind == "xmf":
        if d.get("actual_sidecar_output_subdirectory") != "xdmf": fail(f"{p}: xdmf sidecar")
        c=d.get("xmf_shape_contract",{})
        if c.get("implementation") != "outshape = shape[1:]": fail(f"{p}: vector shape implementation")
        if c.get("dynamic_vector_dimensions") != "70179 3": fail(f"{p}: vector dimensions")
        if c.get("dynamic_scalar_dimensions") != "70179": fail(f"{p}: scalar dimensions")
        if "/xdmf" not in json.dumps(d.get("command",[])): fail(f"{p}: xdmf output")
    if kind == "render":
        if d.get("actual_sidecar_output_subdirectory") != "render": fail(f"{p}: render sidecar")
        if "/render" not in json.dumps(d.get("command",[])): fail(f"{p}: render output")
        if d.get("renderer_contract",{}).get("fixed_camera_bounds_forbidden") is not True: fail(f"{p}: fixed bounds")
        if d.get("renderer_contract",{}).get("expected_contact_pages") != 26: fail(f"{p}: page contract")
    return {"case_id":d.get("case_id"),"kind":kind,"input_count":len(files),"native_status":d.get("native_dependency",{}).get("status")}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--root",type=Path,required=True); ap.add_argument("--write-report",action="store_true")
    a=ap.parse_args(); root=a.root.resolve()
    out=[]
    for case in CASES:
        out.append(check_request(root/"requests/typed"/f"{case}.full601-nvme-typed-072.disabled-request.json","typed"))
        out.append(check_request(root/"requests/xmf"/f"{case}.full601-normal-xmf-072.disabled-request.json","xmf"))
        out.append(check_request(root/"requests/render"/f"{case}.full601-native023-render-072.disabled-request.json","render"))
    for p in root.rglob("*"):
        if p.is_file() and any(p.name.lower().endswith(x) for x in RAW_SUFFIXES):
            fail(f"raw payload file in source package: {p}")
    manifest=load(root/"metadata/manifest.json")
    if manifest.get("case_count") != 16 or manifest.get("arrays_read") is not False or manifest.get("jobs_started") is not False:
        fail("manifest source-only flags")
    report={"schema":"ds02.f7.fresh072.source-validation-report.v1","scope_id":"root_followup_072_stage1_actualQA310_full601_typed_xmf_render_v1","request_count":len(out),"requests":out,"all_passed":True,"arrays_read":False,"jobs_started":False,"shared_registry_write":False,"future_hashes_null":True}
    if a.write_report:
        p=root/"metadata/source-validation-report.json"; p.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print(json.dumps(report,indent=2,sort_keys=True))
if __name__=="__main__": main()
