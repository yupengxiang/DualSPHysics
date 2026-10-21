#!/usr/bin/env python3
"""One admitted, contract-bound CaseForces full-frame conversion child.

The parent runner owns admission, identity, limits, fees, and solver authority.
This child only consumes the already-closed solver/asset metadata and performs
read-only BI4 decoding, HDF publication, selected PartVTK QA, and factual
endpoint/history calculations.  It never grants scientific qualification.
"""
from __future__ import annotations
import argparse,gzip,hashlib,json,math,os,re,shutil,stat,sys,types,xml.etree.ElementTree as ET
from pathlib import Path
import numpy as np

SCHEMA="lfd01.Root.CaseForces.full5-child.v2"
MAX_FILE=512*1024*1024; MAX_DATA_BYTES=2*1024*1024*1024; MAX_FRAMES=512; MAX_PARTICLES=100000; MAX_REPORT=8*1024*1024
FRAME_RE=re.compile(r"^Part_(\d{4,})\.bi4$")
BAD_TAGS={"inout","inoutzone","periodic","adaptive","adaptative","birth","inlet","outlet"}

class ChildError(RuntimeError): pass

def _hfd(f,n):
    h=hashlib.sha256()
    for o in range(0,n,1<<20): h.update(os.pread(f,min(1<<20,n-o),o))
    return h.hexdigest()

def _q(st): return [st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns]

def _ident(f,p):
    a,b=os.fstat(f),os.lstat(p)
    if not stat.S_ISREG(a.st_mode) or not stat.S_ISREG(b.st_mode): raise ChildError("non-regular input: "+str(p))
    x,y=_q(a),_q(b)
    if x!=y: raise ChildError("open/path identity mismatch: "+str(p))
    return {"fd":x,"path":y}

def _bind(x,label):
    if not isinstance(x,dict): raise ChildError(label+" is not a file binding")
    try: p,n,h=Path(x["path"]),int(x["bytes"]),str(x["sha256"]).lower()
    except (KeyError,TypeError,ValueError) as e: raise ChildError("invalid "+label+" binding") from e
    if not p.is_absolute() or n<0 or n>MAX_FILE or len(h)!=64: raise ChildError("invalid "+label+" tuple")
    int(h,16); return p,n,h

def _open(x,label):
    s=_bind(x,label); f=os.open(s[0],os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW)
    try:
        b=_ident(f,s[0])
        if b["fd"][2]!=s[1] or _hfd(f,s[1])!=s[2]: raise ChildError(label+" pre-read tuple mismatch")
        raw=os.pread(f,s[1],0)
        if len(raw)!=s[1]: raise ChildError(label+" short read")
        return f,raw,b,s
    except Exception:
        os.close(f); raise

def _close(f,p,s,b):
    z=_ident(f,p)
    if z!=b or z["fd"][2]!=s[1] or _hfd(f,s[1])!=s[2]: raise ChildError("input changed: "+str(p))
    os.close(f)

def _scan(p):
    if p.is_symlink(): raise ChildError("symlink in BI4 tree: "+str(p))
    f=os.open(p,os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW)
    try:
        z=_ident(f,p); n=z["fd"][2]
        if n>MAX_FILE: raise ChildError("input exceeds bound: "+str(p))
        return {"path":p.name,"bytes":n,"sha256":_hfd(f,n)}
    finally: os.close(f)

def _tree(root):
    root=Path(root)
    if not root.is_absolute() or root.is_symlink() or not root.is_dir(): raise ChildError("unsafe BI4 root")
    rows=[]; total=0
    for base,dirs,files in os.walk(root,followlinks=False):
        for d in dirs:
            if (Path(base)/d).is_symlink(): raise ChildError("symlink directory in BI4 tree")
        for name in files:
            p=Path(base)/name
            if p.is_symlink(): raise ChildError("symlink file in BI4 tree")
            r=_scan(p); total+=r["bytes"]
            if total>MAX_DATA_BYTES: raise ChildError("BI4 tree exceeds total bound")
            r["path"]=p.relative_to(root).as_posix(); rows.append(r)
    rows.sort(key=lambda x:x["path"])
    idx=[]
    for r in rows:
        m=FRAME_RE.match(Path(r["path"]).name)
        if m and Path(r["path"]).parent==Path("."): idx.append(int(m.group(1)))
    if not idx or sorted(idx)!=list(range(len(idx))): raise ChildError("BI4 frames are not contiguous from zero")
    digest=hashlib.sha256(json.dumps(rows,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
    return {"root":str(root),"file_count":len(rows),"files":rows,"tree_sha256":digest}

def _read_json(x,label):
    f,raw,b,s=_open(x,label)
    try: value=json.loads(raw)
    finally: _close(f,s[0],s,b)
    if not isinstance(value,dict): raise ChildError(label+" is not an object")
    return value

def _same_ref(a,b,label):
    try: aa=_bind(a,label+" lhs"); bb=_bind(b,label+" rhs")
    except ChildError: raise
    if aa!=bb: raise ChildError(label+" reference mismatch")

def _solver_join(c,auth):
    cl=auth["solver_closure"]
    if cl.get("status")!="completed_solver_pending_actual_G1_G2": raise ChildError("solver terminal closure status is not the actual completed state")
    for key,contract_key in (("request","solver_request"),("grant","solver_grant"),("receipt","solver_receipt")):
        if not isinstance(cl.get(key),dict): raise ChildError("solver closure lacks "+key+" reference")
        _same_ref(cl[key],c[contract_key],"solver closure "+key)
    req=auth["solver_request"]; grant=auth["solver_grant"]; receipt=auth["solver_receipt"]
    rq=cl["request"]
    if req.get("request_path")!=rq["path"] or req.get("request_sha256")!=rq["sha256"]: raise ChildError("solver request self binding mismatch")
    if grant.get("request_path")!=rq["path"] or grant.get("request_sha256")!=rq["sha256"]: raise ChildError("solver grant request join mismatch")
    if receipt.get("request_sha256")!=rq["sha256"] or receipt.get("request")!=req: raise ChildError("solver receipt request join mismatch")
    if receipt.get("status")!="completed" or receipt.get("returncode")!=0: raise ChildError("solver receipt is not completed successfully")
    if not all(cl.get(k) is True for k in ("normal_source_posthash_exact","deferred_native_XML_forcing_binary_posthash_exact","owned_tree_reaped","reservation_and_lease_absent","old_parent_prefix_unchanged")): raise ChildError("solver terminal lifecycle closure is incomplete")
    if cl.get("unique_parent_charge",{}).get("status")!="completed" or cl.get("unique_parent_attempt",{}).get("status")!="completed": raise ChildError("solver terminal financial closure is incomplete")
    if cl.get("root_native_ELF_generatedXML_or_array_read") is not False or cl.get("science_credit")!=0 or cl.get("core_credit")!=0: raise ChildError("solver terminal closure has forbidden credit or root payload read")
    return {"status":cl["status"],"request":rq,"grant":cl["grant"],"receipt":cl["receipt"],"output_root":receipt.get("output_root"),"receipt_status":receipt.get("status"),"returncode":receipt.get("returncode")}

def _load_source(x):
    f,raw,b,s=_open(x,"legacy_source"); name="_lfd01_caseforces_"+s[2][:16]; m=types.ModuleType(name); m.__file__=str(s[0]); sys.modules[name]=m
    try:
        exec(compile(raw,str(s[0]),"exec"),m.__dict__)
        for n in ("decode_frame","parse_particle_blocks","_assign_types","_mass_for_types","_create_h5","_write_frame","compare_partvtk_frame","_run_partvtk_frame"):
            if not callable(getattr(m,n,None)): raise ChildError("legacy helper missing "+n)
        return m,f,s[0],s,b
    except Exception:
        sys.modules.pop(name,None); os.close(f); raise

def _outpath(x,label,root):
    if not isinstance(x,dict) or "path" not in x: raise ChildError(label+" output path missing")
    p=Path(x["path"])
    if not p.is_absolute() or root not in p.parents: raise ChildError(label+" is outside output root")
    if os.path.lexists(p) or os.path.lexists(str(p)+".partial"): raise ChildError(label+" already exists")
    return p

def _ref(x,label):
    p,n,h=_bind(x,label); return {"path":str(p),"bytes":n,"sha256":h}

def _atomic_json(p,value):
    raw=json.dumps(value,indent=2,sort_keys=True,allow_nan=False).encode()+b"\n"
    if len(raw)>MAX_REPORT: raise ChildError("report exceeds bound")
    q=Path(str(p)+".partial")
    f=os.open(q,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    try:
        for o in range(0,len(raw),1<<16):
            z=raw[o:o+(1<<16)]
            if os.write(f,z)!=len(z): raise ChildError("short JSON write")
        os.fsync(f)
    finally: os.close(f)
    try: os.link(q,p,follow_symlinks=False)
    except FileExistsError as exc: raise ChildError("output already exists: "+str(p)) from exc
    os.unlink(q)

def _publish(src,dst):
    try: os.link(src,dst,follow_symlinks=False)
    except FileExistsError as exc: raise ChildError("output already exists: "+str(dst)) from exc
    os.unlink(src)

def _sha_path(p):
    f=os.open(p,os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW)
    try:
        z=_ident(f,p); return {"path":str(p),"bytes":z["fd"][2],"sha256":_hfd(f,z["fd"][2])}
    finally: os.close(f)

def _xml_gate(raw):
    root=ET.fromstring(raw); d=root.find(".//data2d")
    if d is None or str(d.get("value","")).lower()!="false": raise ChildError("generated XML is not explicit Data2d=false")
    bad={x.tag.rsplit("}",1)[-1].lower() for x in root.iter()}&BAD_TAGS
    if bad: raise ChildError("unsupported open/dynamic XML tags: "+repr(sorted(bad)))
    return {"Data2d":False,"blocked_tags":sorted(bad)}

def _runtime(m,meta,first):
    for k,v in (("Npiece",1),("Piece",0),("NpDynamic",0),("ReuseIds",0),("PeriMode",0)):
        if m._as_int(meta,k) != v: raise ChildError("runtime "+k+" is not closed value")
    if meta.get("Data2d") is not False: raise ChildError("runtime Data2d is not explicit false")
    for k in ("Dp","B","Rhop0","Gamma","MassFluid","MassBound"):
        a,b=m._as_float(first,k),m._as_float(meta,k)
        if a is None or b is None or not math.isclose(float(a),float(b),rel_tol=0,abs_tol=1e-12): raise ChildError("runtime constant changed/missing: "+k)
    return {k:meta.get(k) for k in ("Npiece","Piece","NpDynamic","ReuseIds","PeriMode","Data2d","MassFluid","MassBound")}

def _states(frame,base,types,mks,cohorts):
    ids=np.asarray(frame.ids); pos=np.asarray(frame.position)
    ix=np.searchsorted(base,ids)
    if np.any(ix>=base.size) or not np.array_equal(base[ix],ids) or np.unique(ix).size!=ix.size: raise ChildError("introduced/duplicated Idp")
    if pos.ndim!=2 or pos.shape!=(ids.size,3): raise ChildError("position shape mismatch")
    finite=np.isfinite(pos).all(axis=1)
    allstate=np.full(base.size,-1,dtype=np.int8)
    ok=finite
    rx=np.digitize(pos[ok,0],[-.15,.15]); rz=np.digitize(pos[ok,2],[-.15,.15])
    allstate[ix[ok]]=rx*3+rz
    return [allstate[c["ids"]] for c in cohorts]

def _geometry(frame,base,cohorts,geom):
    ids=np.asarray(frame.ids); pos=np.asarray(frame.position); ix=np.searchsorted(base,ids); by=np.full(base.size,-1,dtype=np.int64); by[ix]=np.arange(ids.size)
    for c,g in zip(cohorts,geom):
        j=by[c["ids"]]; p=pos[j[j>=0]]; p=p[np.isfinite(p).all(axis=1)]
        if not p.size: continue
        g["min"]=np.minimum(g["min"],np.min(p,axis=0)); g["max"]=np.maximum(g["max"],np.max(p,axis=0)); g["sites"]=np.maximum(g["sites"],[np.unique(p[:,i]).size for i in range(3)])

def _quantile(times,mass,q):
    good=np.isfinite(times)
    if not np.any(good): return None
    order=np.argsort(times[good]); t=times[good][order]; w=mass[good][order]; total=float(np.sum(w,dtype=np.float64)); target=q*float(np.sum(mass,dtype=np.float64))
    if total<target: return None
    return float(t[np.flatnonzero(np.cumsum(w,dtype=np.float64)>=target)[0]])

def _cohort_task(co):
    m0=float(np.sum(co["mass"],dtype=np.float64)); t=co["last_time"]-co["first_time"]
    if t<=0: raise ChildError("saved horizon is not positive")
    if not np.array_equal(np.sum(co["cat_count"],axis=0),np.full(9,co["ids"].size,dtype=np.int64)): raise ChildError("first-detection categories do not partition the cohort")
    if not np.all(np.abs(np.sum(co["cat_mass"],axis=0)-m0)<=1e-12+1e-10*m0): raise ChildError("first-detection mass does not close the cohort")
    endpoint=[]; residence=[]; detect=[]; observed_total=float(np.sum(co["final_obs"],dtype=np.float64)); global_closure=(observed_total+float(co["final_unknown"]))-m0
    names=("present_at_initial","observed_bracket","prior_censor","not_observed","unknown")
    for r in range(9):
        obs=float(co["final_obs"][r]); unk=float(co["final_unknown"]); other=observed_total-obs; endpoint.append({"region":r,"observed_kg":obs,"unknown_kg":unk,"other_known_complement_kg":other,"observed_fraction":obs/m0,"unknown_fraction":unk/m0,"closure_kg":global_closure,"region_closure_kg":(obs+other+unk)-m0})
        residence.append({"region":r,"lower":co["res_l"][r]/(m0*t),"upper":co["res_u"][r]/(m0*t),"horizon_s":t})
        rows=[]
        for k,n in enumerate(names): rows.append({"category":n,"count":int(co["cat_count"][k,r]),"mass_kg":float(co["cat_mass"][k,r]),"fraction":float(co["cat_mass"][k,r]/m0)})
        detect.append({"region":r,"categories":rows})
    censored=bool(np.any(co["arrival_censored"]))
    if censored: protection={"status":"unavailable_prior_censor","arrival_q10_s":None,"arrival_q50_s":None,"arrival_q90_s":None,"never_observed_arrival_mass_kg":float(np.sum(co["mass"][~np.isfinite(co["arrival"])],dtype=np.float64))}
    else:
        q=[_quantile(co["arrival"],co["mass"],x) for x in (.1,.5,.9)]; protection={"status":"available" if all(x is not None for x in q) else "unavailable_never_observed_mass","arrival_q10_s":q[0],"arrival_q50_s":q[1],"arrival_q90_s":q[2],"never_observed_arrival_mass_kg":float(np.sum(co["mass"][~np.isfinite(co["arrival"])],dtype=np.float64))}
    return {"mkfluid":co["mk"],"initial_mass_kg":m0,"endpoint":endpoint,"endpoint_global_closure_kg":global_closure,"residence":residence,"first_detection":detect,
      "protection":protection,
      "g2_status":"pending accepted-step trace, controls, replay, and full product predicates"}

def _inputs(c):
    opened=[]
    try:
        sf,src,sb,ss=_open(c["generated_xml"],"generated_xml"); opened.append(sf)
        df,_,db,ds=_open(c["decoder"],"decoder"); opened.append(df)
        pf,_,pb,ps=_open(c["partvtk"],"partvtk"); opened.append(pf)
        m,lf,lp,ls,lb=_load_source(c["legacy_source"]); opened.append(lf)
        return sf,src,sb,ss,df,db,ds,pf,pb,ps,m,lf,lp,ls,lb
    except Exception:
        for f in reversed(opened):
            try: os.close(f)
            except OSError: pass
        raise

def _run(c,output_root):
    if c.get("schema")!=SCHEMA or str(c.get("output_root"))!=str(output_root): raise ChildError("contract schema/output_root mismatch")
    refs=("science_contract","protocol_adoption","initial_facts_closure","source_preflight","asset_closure","gencase_closure","solver_request","solver_grant","solver_receipt","solver_closure")
    auth={k:_read_json(c[k],k) for k in refs}
    if auth["science_contract"].get("schema")!="lfd01.Root.CaseForces.full5-science-contract.v1": raise ChildError("wrong science contract")
    if auth["protocol_adoption"].get("status") not in {"adopted_one_baseline_eligible_for_live_shared_admission","adopted"}: raise ChildError("protocol not adopted")
    if auth["initial_facts_closure"].get("status")!="completed_initial_factual_observation_no_qualification": raise ChildError("initial facts closure is not factual completed")
    solver_join=_solver_join(c,auth)
    if not isinstance(auth["asset_closure"].get("status"),str) or not isinstance(auth["gencase_closure"].get("status"),str): raise ChildError("asset/GenCase closure lacks status")
    for k in ("legacy_source","decoder","generated_xml","partvtk"): _bind(c[k],k)
    root=Path(output_root)
    if root.is_symlink() or not root.is_dir() or not (root/".tmp").is_dir(): raise ChildError("canonical output root/.tmp missing")
    oh=_outpath(c["outputs"]["hdf5"],"hdf5",root); orp=_outpath(c["outputs"]["report"],"report",root); his=_outpath(c["outputs"]["history"],"history",root)
    dr=c["data_root"]
    if not isinstance(dr,dict) or not Path(dr.get("path","")).is_absolute(): raise ChildError("data_root binding missing")
    data_path=Path(dr["path"]); solver_root=Path(str(solver_join.get("output_root","")))
    if not solver_root.is_absolute() or data_path!=solver_root/"data": raise ChildError("data_root is not the exact deferred solver output/data target")
    if dr.get("inspection_only") is not True or ("sha256" in dr and dr.get("sha256") is not None) or ("bytes" in dr and dr.get("bytes") is not None) or dr.get("manifest") not in (None,{}): raise ChildError("data_root must be an un-hashed inspection-only target")
    before=_tree(data_path)
    paths=[Path(dr["path"])/r["path"] for r in before["files"] if FRAME_RE.match(Path(r["path"]).name) and Path(r["path"]).parent==Path(".")]
    exp=c.get("expected",{}); nframes=len(paths); 
    if nframes>MAX_FRAMES or int(exp.get("frames",nframes))!=nframes: raise ChildError("unexpected frame count")
    scratch=root/".tmp"/"full5-existing"; os.mkdir(scratch,0o700)
    sf,src,sb,ss,df,db,ds,pf,pb,ps,m,lf,lp,ls,lb=_inputs(c)
    h5=None; h5tmp=scratch/"full5.h5.partial"; historytmp=Path(str(his)+".partial")
    if os.path.lexists(h5tmp) or os.path.lexists(historytmp): raise ChildError("partial output collision")
    try:
        xgate=_xml_gate(src); blocks=m.parse_particle_blocks(ss[0])
        if blocks.get("xml_sha256")!=ss[2]: raise ChildError("generated XML parser hash mismatch")
        npart=int(blocks["np"])
        if npart>MAX_PARTICLES or int(exp.get("particles",npart))!=npart: raise ChildError("unexpected particle count")
        base=np.arange(npart,dtype=np.uint32); types,mks=m._assign_types(base,blocks); fluid_by_mk={}
        for block in blocks["blocks"]:
            if block["type"]!=3: continue
            mkfluid=block.get("mkfluid")
            if mkfluid not in (0,1) or mkfluid in fluid_by_mk: raise ChildError("generated XML fluid cohort mapping is not unique")
            ids=np.arange(block["begin"],block["begin"]+block["count"],dtype=np.uint32)
            if not np.all(types[ids]==3): raise ChildError("fluid block type mapping mismatch")
            fluid_by_mk[mkfluid]=ids
        if sorted(fluid_by_mk)!=[0,1]: raise ChildError("generated XML lacks exactly MKfluid0/MKfluid1")
        first_path=paths[0]; row=next(r for r in before["files"] if r["path"]==first_path.relative_to(Path(dr["path"])).as_posix()); ff,_,fb,fs=_open({"path":str(first_path),"bytes":row["bytes"],"sha256":row["sha256"]},"frame0")
        try: first=m.decode_frame(first_path,ds[0],scratch,0)
        finally: _close(ff,fs[0],fs,fb)
        if not math.isclose(float(first.time),0.0,rel_tol=0,abs_tol=1e-12): raise ChildError("first BI4 time is not zero")
        initial_mass=m._mass_for_types(types,first.metadata).astype(np.float32); _runtime(m,first.metadata,first.metadata)
        cohorts=[]
        for mk in (0,1):
            ids=fluid_by_mk[mk]; mass=initial_mass[ids].astype(np.float64)
            cohorts.append({"mk":mk,"ids":ids,"mass":mass,"first_time":float(first.time),"last_time":float(first.time),"prev":None,"res_l":np.zeros(9),"res_u":np.zeros(9),"final_obs":np.zeros(9),"final_unknown":0.0,"detected":np.zeros((9,ids.size),bool),"missing":np.zeros(ids.size,bool),"cat_mass":np.zeros((5,9)),"cat_count":np.zeros((5,9),dtype=np.int64),"arrival":np.full(ids.size,np.nan),"arrival_censored":np.zeros(ids.size,bool)})
        geom=[{"mk":c["mk"],"min":np.full(3,np.inf),"max":np.full(3,-np.inf),"sites":np.zeros(3,dtype=np.int64)} for c in cohorts]
        h5=m._create_h5(h5tmp,nframes,npart)
        h5["particle_id"][:]=base; h5["particle_zone"][:]=int(m._as_int(first.metadata,"Piece",default=0)); h5["initial_type"][:]=types; h5["initial_mk"][:]=mks; h5["initial_mass"][:]=initial_mass
        h5.attrs["source_raw_tree_sha256_before"]=before["tree_sha256"]; h5.attrs["source_tree_unchanged"]=False; h5.attrs["conversion_complete"]=False; h5.attrs["q_i_status"]="conversion evidence only; scientific qualification external"; h5.attrs["q_n_status"]="not_assessed"; h5.attrs["production_eligibility"]="not_evaluated"
        summaries=[]; runtime=[]; history=[]; previous_time=None
        for i,path in enumerate(paths):
            frame=first if i==0 else None; fd=fb0=None; fs0=None
            if frame is None:
                row=next(r for r in before["files"] if r["path"]==path.relative_to(Path(dr["path"])).as_posix()); fd,_,fb0,fs0=_open({"path":str(path),"bytes":row["bytes"],"sha256":row["sha256"]},f"frame{i}")
                try: frame=m.decode_frame(path,ds[0],scratch,i)
                except Exception:
                    _close(fd,fs0[0],fs0,fb0); raise
            try:
                if previous_time is not None and not float(frame.time)>previous_time: raise ChildError("BI4 time is not strictly increasing")
                previous_time=float(frame.time); runtime.append(_runtime(m,frame.metadata,first.metadata))
                mass=m._mass_for_types(types,frame.metadata).astype(np.float32)
                if not np.array_equal(mass,initial_mass): raise ChildError("operative native mass changed")
                summaries.append(m._write_frame(h5,i,frame,base,types,mks,mass))
                states=_states(frame,base,types,mks,cohorts)
                _geometry(frame,base,cohorts,geom)
                rowhist={"frame":i,"time":float(frame.time),"cohorts":[]}
                for ci,co in enumerate(cohorts):
                    s=states[ci]; m0=co["mass"]; obs=np.zeros(9); unk=float(np.sum(m0[s<0],dtype=np.float64));
                    for r in range(9):
                        hit=s==r; obs[r]=float(np.sum(m0[hit],dtype=np.float64))
                        if co["prev"] is not None:
                            pl=(co["prev"]==r); pu=pl|(co["prev"]<0); cl=hit; cu=hit|(s<0); dt=float(frame.time-co["last_time"])
                            co["res_l"][r]+=.5*dt*float(np.sum(m0[pl],dtype=np.float64)+np.sum(m0[cl],dtype=np.float64)); co["res_u"][r]+=.5*dt*float(np.sum(m0[pu],dtype=np.float64)+np.sum(m0[cu],dtype=np.float64))
                        new=hit&~co["detected"][r]; cat=np.where(i==0,0,np.where(co["missing"],2,1));
                        for k in range(3):
                            z=new&(cat==k); co["cat_count"][k,r]+=int(z.sum()); co["cat_mass"][k,r]+=float(np.sum(m0[z],dtype=np.float64))
                        co["detected"][r,new]=True
                    if co["prev"] is None: co["first_time"]=float(frame.time)
                    co["missing"]|=s<0; co["prev"]=s.copy(); co["last_time"]=float(frame.time); co["final_obs"]=obs; co["final_unknown"]=unk
                    co["arrival_censored"]|=(~np.isfinite(co["arrival"]))&(s<0)
                    arr=(s>=0)&np.isin(s,[2,5,8])&~np.isfinite(co["arrival"]); co["arrival"][arr]=float(frame.time)
                    rowhist["cohorts"].append({"mkfluid":co["mk"],"observed_kg":obs.tolist(),"unknown_kg":unk,"observed_count":[int(np.sum(s==r)) for r in range(9)]})
                history.append(rowhist)
            finally:
                if fd is not None: _close(fd,fs0[0],fs0,fb0)
                shutil.rmtree(scratch/f"frame_{i:04d}",ignore_errors=True)
        for co in cohorts:
            for r in range(9):
                never=~co["detected"][r]; clean=never&~co["missing"]; unknown=never&co["missing"]
                co["cat_count"][3,r]+=int(clean.sum()); co["cat_mass"][3,r]+=float(np.sum(co["mass"][clean],dtype=np.float64))
                co["cat_count"][4,r]+=int(unknown.sum()); co["cat_mass"][4,r]+=float(np.sum(co["mass"][unknown],dtype=np.float64))
        geometry_report=[]
        for g in geom:
            if not np.isfinite(g["min"]).all() or not np.isfinite(g["max"]).all() or np.any(g["sites"]<3): raise ChildError("fluid cohort lacks finite three-axis evidence")
            span=g["max"]-g["min"]
            geometry_report.append({"mkfluid":int(g["mk"]),"min_m":g["min"].tolist(),"max_m":g["max"].tolist(),"span_m":span.tolist(),"axis_sites":g["sites"].astype(int).tolist()})
        h5.flush(); h5.close(); h5=None
        qa=[]; selected=sorted(set((0,nframes//2,nframes-1))); vd=scratch/"partvtk"; os.mkdir(vd,0o700)
        try:
            for i in selected:
                csvp=m._run_partvtk_frame(ps[0],Path(dr["path"]),i,vd); q=m.compare_partvtk_frame(h5tmp,csvp,i); qa.append(q); csvp.unlink(missing_ok=True)
                if not q["passed"]: raise ChildError("selected PartVTK QA failed")
        finally: shutil.rmtree(vd,ignore_errors=True)
        after=_tree(Path(dr["path"]));
        if after!=before: raise ChildError("BI4 raw tree changed during conversion")
        with m.h5py.File(h5tmp,"r+") as z: z.attrs["source_raw_tree_sha256_after"]=after["tree_sha256"]; z.attrs["source_tree_unchanged"]=True; z.attrs["conversion_complete"]=True; z.flush()
        tasks={"endpoint_and_residence":[_cohort_task(c) for c in cohorts],"history_rows":len(history),"regions":{"axes":["x","z"],"thresholds_m":[-.15,.15],"count":9},"accepted_trace":"not_read; exact seven-column trace and endpoint closure remain a required external gate","g2_status":"pending controls, accepted-step trace, replay, and remaining product predicates"}
        _atomic_json(his,{"schema":"lfd01.Root.CaseForces.full5-history.v1","status":"observed_pending_qualification","rows":history,"tasks":tasks})
        _publish(h5tmp,oh)
        result={"schema":"lfd01.Root.CaseForces.full5-result.v1","status":"conversion_and_g1_evidence_pending_trace_tasks","candidate":0,"science_credit":0,"core_credit":0,"case_id":c.get("case_id"),"inputs":{"data_tree_before":before,"data_tree_after":after,"generated_xml":_ref(c["generated_xml"],"generated_xml"),"decoder":_ref(c["decoder"],"decoder"),"legacy_source":_ref(c["legacy_source"],"legacy_source")},"authority":{"solver_request_status":auth["solver_request"].get("status"),"solver_grant_status":auth["solver_grant"].get("status"),"solver_receipt_status":auth["solver_receipt"].get("status"),"solver_closure_status":auth["solver_closure"].get("status"),"gencase_closure_status":auth["gencase_closure"].get("status"),"asset_closure_status":auth["asset_closure"].get("status"),"initial_facts_status":auth["initial_facts_closure"].get("status")},"source_xml":{"blocks":blocks["blocks"],"np":npart,"Data2d":xgate["Data2d"]},"runtime_g1":{"flags":runtime,"all_frames":nframes,"particles":npart,"identity":"fixed generated XML axis; introduced/duplicate IDs rejected","missing":"retained as unknown, never survivor-renormalized","mass":"operative float32 native header/source values required equal across frames","true3d":{"cohorts":geometry_report,"credit":0}},"frames":{"count":nframes,"summary":summaries,"first_s":float(history[0]["time"]),"last_s":float(history[-1]["time"]),"terminal_overshoot_retained":True},"qa":{"scope":"all frames decoded into HDF; PartVTK selected first/middle/terminal","selected":qa,"all_selected_passed":bool(all(x["passed"] for x in qa))},"outputs":{"hdf5":_sha_path(oh),"history":_sha_path(his)},"tasks":tasks,"g2":"pending; no control/threshold/denominator/window tuning"}
        _atomic_json(orp,result); result["outputs"]["report"]=_sha_path(orp); shutil.rmtree(scratch,ignore_errors=True); return result
    except Exception:
        if h5 is not None: h5.close()
        if os.path.lexists(h5tmp): h5tmp.unlink()
        if os.path.lexists(historytmp): historytmp.unlink()
        shutil.rmtree(scratch,ignore_errors=True)
        raise
    finally:
        _close(pf,ps[0],ps,pb); _close(df,ds[0],ds,db); _close(sf,ss[0],ss,sb); _close(lf,lp,ls,lb); sys.modules.pop(m.__name__,None)

def main(argv=None):
    ap=argparse.ArgumentParser(); ap.add_argument("--contract",required=True); ap.add_argument("--contract-bytes",required=True,type=int); ap.add_argument("--contract-sha256",required=True); ap.add_argument("--output-root",required=True); a=ap.parse_args(argv); out=Path(a.output_root); result={"schema":SCHEMA,"status":"failed","candidate":0,"science_credit":0,"core_credit":0}
    try:
        f,raw,b,s=_open({"path":a.contract,"bytes":a.contract_bytes,"sha256":a.contract_sha256},"child_contract"); c=json.loads(raw); _close(f,s[0],s,b); result=_run(c,out)
    except Exception as e:
        result.update({"error":{"type":type(e).__name__,"detail":str(e)[:2000]}})
        try: _atomic_json(out/"child-failure.json",result)
        except Exception: return 2
    return 0 if result.get("status","").startswith("conversion") else 1

if __name__=="__main__": raise SystemExit(main())
