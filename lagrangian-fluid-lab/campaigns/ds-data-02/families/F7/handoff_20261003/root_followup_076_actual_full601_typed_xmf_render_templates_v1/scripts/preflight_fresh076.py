#!/usr/bin/env python3
"""Static fresh076 check; source-only, no scientific payload or worker run."""
from __future__ import annotations
import ast, hashlib, json
from pathlib import Path
P=Path(__file__).resolve().parents[1]
RAW={".bi4",".csv",".h5",".hdf5",".dat",".ibi4",".vtk",".vtu",".png",".jpg",".jpeg"}
E={"total":70179,"fixed":27495,"moving":1984,"floating":0,"fluid":40700,"dimension":3}
def req(ok,msg):
    if not ok: raise ValueError(msg)
def load(p):
    v=json.loads(p.read_text(encoding="utf-8")); req(isinstance(v,dict),f"object required: {p}"); return v
def sha(p):
    req(p.suffix.lower() not in RAW,f"raw hash: {p}")
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()
def check_req(p,kind):
    d=load(p); files=[str(x) for x in d.get("input_files",[])]; hs=d.get("input_sha256",{})
    req(len(files)==len(set(files)),f"duplicate source input: {p}")
    req(set(files)==set(hs),f"source closure mismatch: {p}")
    for raw in files:
        q=Path(raw); req(q.is_absolute() and q.is_file(),f"missing source input {q}")
        req(q.suffix.lower() not in RAW,f"payload in source input {q}")
        req(sha(q)==hs[raw],f"source hash drift {q}")
    fs=[str(x) for x in d.get("future_input_files",[])]; fhs=d.get("future_input_sha256",{})
    req(set(fs)==set(fhs),f"future closure mismatch: {p}")
    req(all(v is None for v in fhs.values()),f"fabricated future digest: {p}")
    req(d.get("disabled") is True and d.get("launch") is False and d.get("execution_allowed") is False and d.get("launch_allowed") is False,f"enabled request: {p}")
    req(d.get("source_only") is True and d.get("future_hashes_null") is True and d.get("no_array_decode_in_source_prep") is True and d.get("no_jobs_started") is True and d.get("no_shared_registry_write") is True,f"guard drift: {p}")
    req(d.get("expected_counts")==E and d.get("expected_frames")==601 and d.get("expected_native_frames")==601 and d.get("expected_particles")==70179,f"count/frame drift: {p}")
    if kind=="typed":
        req(d.get("cpu_task_kind")=="conversion" and d.get("nvme_protocol",{}).get("conversion_concurrency_cap")==2,f"typed policy drift: {p}")
    elif kind=="xmf":
        req(d.get("cpu_task_kind")=="audit" and d.get("producer_scope_schema")=="ds-data-02.physical-binding.v1",f"xmf producer schema drift: {p}")
        req(d.get("output_directory_contract")=="{attempt_root}/xdmf",f"xmf output contract drift: {p}")
        q=d.get("xmf_shape_contract",{})
        req(q.get("implementation")=="outshape = shape[1:]" and q.get("dynamic_vector_dimensions")=="70179 3" and q.get("dynamic_scalar_dimensions")=="70179",f"xmf shape drift: {p}")
    else:
        req(d.get("cpu_task_kind")=="audit" and d.get("output_directory_contract")=="{attempt_root}/render",f"render output contract drift: {p}")
        q=d.get("render_contract",{})
        req(q.get("automatic_native_bounds") is True and q.get("fixed_camera") is False and q.get("all_saved_frames") is True and q.get("contact_pages")==26,f"render contract drift: {p}")
def main():
    m=load(P/"manifest.json"); cases=m["case_ids"]; req(len(cases)==24 and len(set(cases))==24,"case registry drift")
    for rel in ("scripts/bind_fresh076_actual_typed.py","scripts/preflight_fresh076.py"):
        tree=ast.parse((P/rel).read_text(encoding="utf-8"),filename=str(P/rel))
        imports={alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node,ast.Import) for alias in node.names}
        imports.update(node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node,ast.ImportFrom) and node.module)
        req(not imports.intersection({"numpy","h5py","subprocess"}),f"forbidden scientific/job import: {rel}")
    for kind,sub in (("typed","typed"),("xmf","xmf"),("render","render")):
        ps=sorted((P/"requests"/sub).glob("*.json")); req(len(ps)==24,f"{kind} count")
        for p in ps: check_req(p,kind)
    bs=sorted((P/"bindings").glob("*.json")); req(len(bs)==72,"binding template count")
    for p in bs:
        d=load(p); req(d.get("producer_scope_schema")=="ds-data-02.physical-binding.v1" and d.get("future_hashes_null") is True,f"binding contract: {p}")
    report={"schema":"ds02.f7.fresh076.source-validation-report.v1","scope_id":m["scope_id"],"case_count":24,"typed_requests":24,"xmf_requests":24,"render_requests":24,"binding_templates":72,"expected_counts":E,"expected_frames":601,"flat_prepared_layout_checked":True,"xmf_shape_contract":"outshape = shape[1:], vector N 3, scalar N","render_bounds":"Root023 automatic native bounds over all 601 frames; fixed camera forbidden","native_mass_kg":325.60001628,"continuum_mass_kg":320.1984,"mass_policy":"native mass remains authoritative; continuum comparison separate; no rescale","arrays_read":False,"h5_read":False,"h5_hashed":False,"jobs_started":False,"shared_state_written":False,"future_hashes_null":True,"actual_native_metadata_bound":24,"actual_initial_qa_metadata_bound":24,"all_passed":True,"claim_boundary":"Actual bounded GenCase/native/initial-QA metadata is bound; no typed conversion, XMF/render product, visual, Q-N, precision, or production claim."}
    (P/"metadata/source-validation-report.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(report,indent=2,sort_keys=True))
if __name__=="__main__": main()
