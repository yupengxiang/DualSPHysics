#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
from typing import Any

RAW={".bi4",".ibi4",".h5",".hdf5",".csv",".vtk",".vtu",".npy",".npz"}
HEX=set("0123456789abcdefABCDEF")
CASES=("S035","S045","S055","S065","S070","S080","S085","S095")
MEASURED=set(CASES)

def sha(p:Path)->str:
    if p.suffix.lower() in RAW:
        raise AssertionError(f"raw payload must not be read by source verifier: {p}")
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()

def load(p:Path)->Any:
    return json.loads(p.read_text(encoding="utf-8"))

def check_static_map(owner:Path,d:dict[str,Any],key:str="input")->None:
    files=d.get(f"{key}_files",[])
    digests=d.get(f"{key}_sha256",{})
    assert set(files)==set(digests), (owner,key,"set-closure")
    if key=="future_input":
        assert all(v is None for v in digests.values()), (owner,key,"future hash non-null")
        return
    for raw in files:
        p=Path(raw)
        assert p.suffix.lower() not in RAW, (owner,key,"raw",p)
        assert p.is_file(), (owner,key,"missing",p)
        assert sha(p)==digests[raw], (owner,key,"hash",p)

def walk_future(v:Any,owner:Path)->None:
    if isinstance(v,dict):
        for k,x in v.items():
            if k.endswith("sha256") and ("future" in k or "output" in k or "receipt" in k or "report" in k or "manifest" in k):
                assert x is None, (owner,k,x)
            walk_future(x,owner)
    elif isinstance(v,list):
        for x in v: walk_future(x,owner)

def check_request(p:Path)->dict[str,Any]:
    d=load(p)
    assert d["disabled"] is True and d["launch"] is False
    assert d["launch_allowed"] is False and d["execution_allowed"] is False
    assert d["source_only"] is True
    check_static_map(p,d,"input")
    check_static_map(p,d,"future_input")
    walk_future(d.get("future_outputs",{}),p)
    for raw,digest in d.get("producer_payload_sha256",{}).items():
        assert Path(raw).suffix.lower()==".h5" and isinstance(digest,str) and len(digest)==64 and set(digest)<=HEX
    assert d["expected_native_frames"]==241
    if "xmf_shape_contract" in d:
        assert d["xmf_shape_contract"]["dynamic_vector_dimensions"]=="417505 3"
        assert d["xmf_shape_contract"]["dynamic_scalar_dimensions"]=="417505"
    return d

def check_binding(p:Path)->dict[str,Any]:
    d=load(p)
    assert d["future_output_hashes_null"] is True
    assert d.get("expected_frames",d.get("expected_native_frames"))==241
    assert d.get("expected_particles",417505)==417505
    assert d.get("expected_dimension",3)==3
    if "xmf_shape_contract" in d:
        assert d["xmf_shape_contract"]["dynamic_vector_dimensions"]=="417505 3"
        assert d["xmf_shape_contract"]["dynamic_scalar_dimensions"]=="417505"
    for raw,digest in d.get("producer_payload_sha256",{}).items():
        assert Path(raw).suffix.lower()==".h5" and isinstance(digest,str) and len(digest)==64 and set(digest)<=HEX
    for raw,digest in d.get("bound_metadata_sha256",{}).items():
        pth=Path(raw)
        assert pth.suffix.lower() not in RAW and pth.is_file(), (p,pth)
        assert sha(pth)==digest, (p,pth,"metadata hash")
    return d

def main()->None:
    ap=argparse.ArgumentParser()
    ap.add_argument("--package",type=Path,default=Path(__file__).resolve().parents[1])
    ap.add_argument("--write",action="store_true")
    args=ap.parse_args()
    pkg=args.package.resolve()
    reg=load(pkg/"metadata/case-registry.json")
    assert reg["case_count"]==8 and len(reg["cases"])==8
    assert reg["canonical_vs_source_plan_separate"] is True
    assert reg["physical_mass_kg"]==128.0 and reg["native_support_mass_kg"]==256.0
    provenance=load(pkg/"metadata/root274-typed-decoder-repair-provenance.json")
    assert provenance["measured_cases"]==sorted(MEASURED)
    assert set(provenance["pending_cases"])==set(CASES)-MEASURED
    assert provenance["producer_h5_digests_adopted_from_conversion_reports"] is True
    for f in pkg.rglob("*"):
        if f.is_file():
            assert f.suffix.lower() not in RAW,(f,"raw package file")
    typed_reqs=[]; xmf_reqs=[]; render_reqs=[]
    for short in CASES:
        case=f"F6_STAGE1_ANGULAR_RELEASE_OMEGA_{short}_DP025"
        tb=check_binding(pkg/"typed/bindings"/f"{case}.typed-binding.json")
        xb=check_binding(pkg/"xmf/bindings"/f"{case}.xmf-binding.json")
        rb=check_binding(pkg/"render/bindings"/f"{case}.render-binding.json")
        tr=check_request(pkg/"typed/requests"/f"{case}-full241-typed-nvme-request.json")
        xr=check_request(pkg/"xmf/requests"/f"{case}-root-xmf-request.json")
        rr=check_request(pkg/"render/requests"/f"{case}-root-native023-render-request.json")
        typed_reqs.append(tr); xmf_reqs.append(xr); render_reqs.append(rr)
        measured=short in MEASURED
        assert (tb["typed_status"]=="completed") is measured
        assert (xb["conversion_report"] is not None) is measured
        assert (xb["trajectory_h5_sha256"] is not None) is measured
        assert (rb["conversion_report"] is not None) is measured
        if measured:
            assert len(tb["trajectory_h5_sha256"])==64
            assert xb["producer_payload_sha256"][xb["trajectory_h5"]]==xb["trajectory_h5_sha256"]
            assert xr["producer_payload_sha256"][xr["typed_dependency"]["trajectory_h5"]]==xr["typed_dependency"]["trajectory_h5_sha256"]
        else:
            assert tb["trajectory_h5_sha256"] is None and xb["trajectory_h5_sha256"] is None
            assert not xb["producer_payload_sha256"] and not xr["producer_payload_sha256"]
        assert xr["output_dir_contract"].endswith("empty child; runtime receipt remains in {attempt_root}")
        assert rr["output_dir_contract"].endswith("empty child; runtime receipt remains in {attempt_root}")
        assert "{attempt_root}/xdmf" in xr["command"][-1]
        assert "{attempt_root}/render" in rr["command"][-1]
        assert rr["camera_policy"]["camera_bounds_in_manifest"] is False
        assert rr["camera_policy"]["domain_bounds_in_manifest"] is False
    assert len(typed_reqs)==len(xmf_reqs)==len(render_reqs)==8
    result={
        "schema":"ds02.f6.fresh084.source-validation.v1","fresh_id":"fresh084",
        "passed":True,"case_count":8,"measured_typed_cases":sorted(MEASURED),
        "pending_typed_cases":[x for x in CASES if x not in MEASURED],
        "typed_request_count":8,"xmf_request_count":8,"render_request_count":8,
        "all_requests_disabled":True,"launch_allowed":False,"execution_allowed":False,
        "xmf_shape_contract":{"vector":"417505 3","scalar":"417505","implementation":"outshape = shape[1:]"},
        "native_counts":{"total":417505,"fluid":327680,"fixed":73441,"floating":16384,"moving":0,"dimension":3},
        "mass_semantics":{"physical_kg":128.0,"native_support_kg":256.0,"normalization":"none"},
        "future_hashes_null_for_pending":True,"arrays_read":False,"jobs_started":False,
        "shared_state_modified":False,"independent_case_increment":0,
        "q_n":"not_assessed","production_approval":"none",
        "claim_boundary":"Metadata closure only; no Q-N, precision, visual, production, or independent-case claim."
    }
    out=pkg/"metadata/static-validation.json"
    if args.write:
        out.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(result,indent=2,sort_keys=True))

if __name__=="__main__":
    main()
