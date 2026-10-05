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
    worker=root/"workers/export_xmf.py"; text=worker.read_text(); ast.parse(text)
    for token in ("typed_receipt","native_receipt","bound_metadata_sha256","conversion_report","physical_condition_sha256","producer_scope_schema","physical_case_id","trajectory_h5","expected_frames","shape[1:]","--output-dir"):
        if token not in text: errors.append("worker missing "+token)
    for p in reqs:
        d=load(p); bpath=Path(d["binding"]); b=load(bpath)
        if not d.get("disabled") or d.get("execution_allowed") or d.get("launch_allowed"): errors.append(f"request not disabled {p.name}")
        if d.get("expected_frames") != d.get("expected_native_frames"): errors.append(f"frame alias mismatch {p.name}")
        if d.get("future_outputs",{}).get("xdmf_sha256") is not None or d.get("future_outputs",{}).get("manifest_sha256") is not None: errors.append(f"future hash nonnull {p.name}")
        if "--binding" not in d.get("command",[]) or "--output-dir" not in d.get("command",[]) or "{attempt_root}/xdmf" not in d.get("command",[]): errors.append(f"command contract {p.name}")
        if set(d.get("input_files",[])) != set(d.get("input_sha256",{})): errors.append(f"input closure {p.name}")
        for path, expected in d.get("input_sha256",{}).items():
            q=Path(path)
            if q.suffix.lower() in FORBIDDEN: errors.append(f"payload in input hash map {q}")
            elif not q.is_file(): errors.append(f"missing input metadata {q}")
            elif sha(q)!=expected: errors.append(f"input sha {q}")
        for k in ("typed_receipt","native_receipt","conversion_report","trajectory_h5","physical_condition_sha256","producer_scope_schema","physical_case_id","expected_frames"):
            if k not in b: errors.append(f"binding key {k} {p.name}")
        if not b.get("canonical_source_scope_is_separate_from_legacy_report_scope"): errors.append(f"legacy separation {p.name}")
        if not b.get("canonical_source_scope_is_separate_from_actual_converter_scope"): errors.append(f"converter separation {p.name}")
        for path, expected in b.get("bound_metadata_sha256",{}).items():
            q=Path(path)
            if q.suffix.lower() in FORBIDDEN: errors.append(f"payload in metadata hash map {q}")
            elif not q.is_file(): errors.append(f"missing metadata {q}")
            elif sha(q)!=expected: errors.append(f"metadata sha {q}")
        rp=Path(b["conversion_report"]); tp=Path(b["typed_receipt"])
        if d.get("status")!="ready_actual_conversion_bound": errors.append(f"not actual-bound {p.name}")
        if not rp.is_file() or not tp.is_file(): errors.append(f"actual conversion metadata missing {p.name}")
        else:
            r=load(rp); t=load(tp)
            if r.get("conversion_status")!="completed" or t.get("status")!="completed" or t.get("returncode")!=0: errors.append(f"actual completion {p.name}")
            dim=r.get("solver_dimension"); dim=dim.get("solver_dimension") if isinstance(dim,dict) else dim
            if dim!=b.get("expected_dimension") or r.get("frames")!=b.get("expected_frames") or r.get("particles")!=b.get("expected_particles"): errors.append(f"actual dimensions/counts {p.name}")
            if not r.get("partvtk_validation",{}).get("all_passed"): errors.append(f"producer PartVTK validation {p.name}")
            scope=r.get("hash_scopes",{}).get("physical_condition_sha256")
            schema=r.get("hash_scopes",{}).get("physical_condition",{}).get("schema")
            if scope!=b.get("physical_condition_sha256") or scope!=b.get("actual_converter_physical_condition_sha256"): errors.append(f"scope {p.name}")
            if schema!=b.get("producer_scope_schema"): errors.append(f"scope schema {p.name}")
            if r.get("output_sha256")!=b.get("actual_h5_producer_sha256"): errors.append(f"producer H5 attestation {p.name}")
            if sha(rp)!=b.get("conversion_report_sha256") or sha(tp)!=b.get("typed_receipt_sha256"): errors.append(f"producer metadata sha {p.name}")
    for p in renders:
        d=load(p)
        if not d.get("disabled") or d.get("execution_allowed") or d.get("launch_allowed"): errors.append(f"render not disabled {p.name}")
        if d.get("future_outputs",{}).get("report_sha256") is not None or d.get("future_outputs",{}).get("frames_sha256") is not None: errors.append(f"render future hash {p.name}")
        if "--manifest" not in d.get("command",[]) or "--output-dir" not in d.get("command",[]): errors.append(f"render command contract {p.name}")
        if set(d.get("input_files",[])) != set(d.get("input_sha256",{})): errors.append(f"render input closure {p.name}")
        for path, expected in d.get("input_sha256",{}).items():
            q=Path(path)
            if q.suffix.lower() in FORBIDDEN: errors.append(f"payload in render hash map {q}")
            elif not q.is_file(): errors.append(f"missing render metadata {q}")
            elif sha(q)!=expected: errors.append(f"render input sha {q}")
    manifest=load(root/"manifest.json")
    controller=Path(manifest["root498_controller_result"])
    if not controller.is_file() or sha(controller)!=manifest.get("root498_controller_result_sha256"): errors.append("Root498 controller metadata closure")
    else:
        c=load(controller)
        if (c.get("requested"),c.get("finished"),c.get("completed0"),c.get("pending_held"))!=(24,24,24,0): errors.append("Root498 controller terminal summary")
    result={"schema":"ds02.f1.fresh100.metadata-verification.v1","case_count":len(reqs),"completed_conversion_count":sum(load(p).get("status")=="ready_actual_conversion_bound" for p in reqs),"errors":errors,"passed":not errors,"scientific_payload_read":False}
    print(json.dumps(result,indent=2,sort_keys=True)); return 0 if not errors else 1
if __name__=="__main__": raise SystemExit(main(Path(sys.argv[1])))
