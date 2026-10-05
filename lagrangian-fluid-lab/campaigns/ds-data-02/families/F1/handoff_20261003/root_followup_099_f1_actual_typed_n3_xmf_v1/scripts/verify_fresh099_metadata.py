from __future__ import annotations
import ast, hashlib, json, sys
from pathlib import Path
FORBIDDEN={".bi4",".ibi4",".h5",".csv",".dat",".vtk",".vtu",".pvtu"}
def sha(p):
    if p.suffix.lower() in FORBIDDEN: raise AssertionError(f"payload hash forbidden: {p}")
    h=hashlib.sha256(); h.update(p.read_bytes()); return h.hexdigest()
def load(p): return json.loads(p.read_text())
def main(root):
    root=Path(root); errors=[]
    reqs=sorted((root/"xmf/requests").glob("*.json")); binds=sorted((root/"xmf/bindings").glob("*.json")); renders=sorted((root/"render/requests").glob("*.json"))
    if len(reqs)!=24: errors.append(f"xmf request count {len(reqs)}")
    if len(binds)!=24: errors.append(f"binding count {len(binds)}")
    if len(renders)!=24: errors.append(f"render request count {len(renders)}")
    worker=root/"workers/export_xmf.py"; text=worker.read_text(); tree=ast.parse(text)
    for token in ("typed_receipt","native_receipt","bound_metadata_sha256","conversion_report","physical_condition_sha256","producer_scope_schema","physical_case_id","trajectory_h5","expected_frames","shape[1:]","--output-dir"):
        if token not in text: errors.append("worker missing "+token)
    for p in reqs:
        d=load(p); b=load(Path(d["binding"]))
        if not d.get("disabled") or d.get("execution_allowed") or d.get("launch_allowed"): errors.append(f"request not disabled {p.name}")
        if d.get("expected_frames") != d.get("expected_native_frames"): errors.append(f"frame alias mismatch {p.name}")
        if d.get("future_outputs",{}).get("xdmf_sha256") is not None or d.get("future_outputs",{}).get("manifest_sha256") is not None: errors.append(f"future hash nonnull {p.name}")
        if "--binding" not in d.get("command",[]) or "--output-dir" not in d.get("command",[]) or "{attempt_root}/xdmf" not in d.get("command",[]): errors.append(f"command contract {p.name}")
        if set(d.get("input_files",[])) != set(d.get("input_sha256",{})): errors.append(f"input closure {p.name}")
        for k in ("typed_receipt","native_receipt","conversion_report","trajectory_h5","physical_condition_sha256","producer_scope_schema","physical_case_id","expected_frames"):
            if k not in b: errors.append(f"binding key {k} {p.name}")
        if not b.get("canonical_source_scope_is_separate_from_legacy_report_scope"): errors.append(f"legacy separation {p.name}")
        if not b.get("canonical_source_scope_is_separate_from_actual_converter_scope"): errors.append(f"converter separation {p.name}")
        for path in b.get("bound_metadata_sha256",{}):
            q=Path(path)
            if q.suffix.lower() in FORBIDDEN: errors.append(f"payload in metadata hash map {q}")
            elif not q.is_file(): errors.append(f"missing metadata {q}")
            elif sha(q)!=b["bound_metadata_sha256"][path]: errors.append(f"metadata sha {q}")
        if d.get("status")=="ready_actual_conversion_bound":
            rp=Path(b["conversion_report"]); tp=Path(b["typed_receipt"])
            if not rp.is_file() or not tp.is_file(): errors.append(f"actual conversion metadata missing {p.name}")
            else:
                r=load(rp); t=load(tp)
                if r.get("conversion_status")!="completed" or t.get("status")!="completed" or t.get("returncode")!=0: errors.append(f"actual completion {p.name}")
                if r.get("hash_scopes",{}).get("physical_condition_sha256") != b.get("physical_condition_sha256"): errors.append(f"scope {p.name}")
                if r.get("hash_scopes",{}).get("physical_condition",{}).get("schema") != b.get("producer_scope_schema"): errors.append(f"scope schema {p.name}")
        else:
            if b.get("physical_condition_sha256") is not None or b.get("conversion_report_sha256") is not None or b.get("trajectory_h5_sha256") is not None: errors.append(f"future value asserted {p.name}")
    for p in renders:
        d=load(p)
        if not d.get("disabled") or d.get("execution_allowed") or d.get("launch_allowed"): errors.append(f"render not disabled {p.name}")
        if d.get("future_outputs",{}).get("report_sha256") is not None or d.get("future_outputs",{}).get("frames_sha256") is not None: errors.append(f"render future hash {p.name}")
        if "--manifest" not in d.get("command",[]) or "--output-dir" not in d.get("command",[]) or "{attempt_root}/render" not in d.get("command",[]): errors.append(f"render command contract {p.name}")
    result={"schema":"ds02.f1.fresh099.metadata-verification.v1","case_count":len(reqs),"completed_conversion_count":sum(load(p).get("status")=="ready_actual_conversion_bound" for p in reqs),"errors":errors,"passed":not errors,"scientific_payload_read":False}
    print(json.dumps(result,indent=2,sort_keys=True)); return 0 if not errors else 1
if __name__=="__main__": raise SystemExit(main(Path(sys.argv[1])))
