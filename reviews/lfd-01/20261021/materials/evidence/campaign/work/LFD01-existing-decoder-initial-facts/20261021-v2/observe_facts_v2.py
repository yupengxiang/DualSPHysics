#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json,os,stat,sys,types,xml.etree.ElementTree as ET
from pathlib import Path
import numpy as np

SCHEMA="lfd01.Root.existing-decoder.initial-facts.v1"; LIM=64*1024*1024; RIM=64*1024

def _hash(f,n):
    h=hashlib.sha256()
    for o in range(0,n,1<<20): h.update(os.pread(f,min(1<<20,n-o),o))
    return h.hexdigest()

def _id(f,p):
    a,b=os.fstat(f),os.lstat(p)
    if not stat.S_ISREG(a.st_mode) or not stat.S_ISREG(b.st_mode): raise RuntimeError("non-regular binding: "+str(p))
    q=lambda x:[x.st_dev,x.st_ino,x.st_size,x.st_mtime_ns,x.st_ctime_ns]
    x,y=q(a),q(b)
    if x!=y: raise RuntimeError("open/path identity mismatch: "+str(p))
    return {"fd":x,"path":y}

def _bind(x,l):
    if not isinstance(x,dict): raise RuntimeError(l+" is not a binding")
    try: p,n,h=Path(x["path"]),int(x["bytes"]),str(x["sha256"]).lower()
    except (KeyError,TypeError,ValueError) as e: raise RuntimeError("invalid "+l+" binding") from e
    if not p.is_absolute() or n<0 or n>LIM or len(h)!=64: raise RuntimeError("invalid "+l+" tuple")
    int(h,16); return p,n,h

def _open(x,l):
    s=_bind(x,l); f=os.open(s[0],os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW)
    try:
        z=_id(f,s[0])
        if z["fd"][2]!=s[1] or _hash(f,s[1])!=s[2]: raise RuntimeError(l+" pre-read tuple mismatch")
        raw=os.pread(f,s[1],0)
        if len(raw)!=s[1]: raise RuntimeError(l+" short read")
        return f,raw,z,s
    except Exception:
        os.close(f); raise

def _close(f,p,s,b):
    z=_id(f,p)
    if z!=b or z["fd"][2]!=s[1] or _hash(f,s[1])!=s[2]: raise RuntimeError("binding changed during decode: "+str(p))
    os.close(f)

def _load(x):
    f,raw,b,s=_open(x,"legacy_source"); name="_lfd01_decoder_"+s[2][:16]; m=types.ModuleType(name); m.__file__=str(s[0]); sys.modules[name]=m
    try:
        exec(compile(raw,str(s[0]),"exec"),m.__dict__)
        if not callable(getattr(m,"decode_frame",None)): raise RuntimeError("legacy source has no decode_frame API")
        return m,f,s[0],s,b
    except Exception:
        sys.modules.pop(name,None); os.close(f); raise

def _raw(n):
    return [] if n is None else [{"name":x.get("name"),"tag":x.tag.rsplit("}",1)[-1],"raw_v":x.get("v"),"attrs":dict(x.attrib)} for x in n if x.tag.rsplit("}",1)[-1]!="item" and x.get("name")]

def _stats(v):
    a=np.asarray(v); q=np.isfinite(a); o={"shape":list(a.shape),"dtype":str(a.dtype),"finite":bool(np.all(q)),"count":int(a.size)}
    if a.size and np.any(q): o.update(min=float(np.min(a[q])),max=float(np.max(a[q])))
    else: o.update(min=None,max=None)
    return o

def _facts(fr,xm,sc):
    r=ET.parse(xm).getroot(); outer,node=r.find("item"),r.find(".//item/item"); name=None if node is None else node.get("name")
    if not name or name in {".",".."} or Path(name).name!=name: raise RuntimeError("unsafe or absent decoder particle item")
    dr=sc/"frame_0000"/name; files={}
    for n in ("Idp.bin","Pos.bin","Posd.bin","Vel.bin","Rhop.bin"):
        p=dr/n
        try:
            z=os.lstat(p); files[n]={"path":str(p),"bytes":int(z.st_size),"regular":stat.S_ISREG(z.st_mode),"symlink":stat.S_ISLNK(z.st_mode)}
        except FileNotFoundError: files[n]={"path":str(p),"exists":False}
    ids=np.asarray(fr.ids); u=np.unique(ids); pos=np.asarray(fr.position); axis=[]
    if pos.ndim==2 and pos.shape[1]==3: axis=[{"unique":int(np.unique(pos[:,i]).size),"min":float(np.min(pos[:,i])),"max":float(np.max(pos[:,i])),"span":float(np.ptp(pos[:,i]))} for i in range(3)]
    return {"schema":SCHEMA,"status":"observed","candidate":0,"science_credit":0,"core_credit":0,
      "frame":{"index":0,"time":float(fr.time),"ids":{"count":int(ids.size),"unique":int(u.size),"min":int(np.min(ids)) if ids.size else None,"max":int(np.max(ids)) if ids.size else None,"contiguous":bool(u.size and np.array_equal(u,np.arange(int(u[0]),int(u[-1])+1))) }},
      "arrays":{"position":_stats(pos),"velocity":_stats(fr.velocity),"density":_stats(fr.density),"zero_velocity_count":int(np.sum(np.all(np.asarray(fr.velocity)==0,axis=1))),"positive_density_count":int(np.sum(np.asarray(fr.density)>0)),"axis":axis},
      "header_metadata":{"typed_fields":_raw(outer),"values":fr.metadata,"MassFluid":fr.metadata.get("MassFluid")},"particle_metadata":{"typed_fields":_raw(node),"values":fr.info},
      "decoder_xml":{"path":str(xm),"bytes":int(xm.stat().st_size),"sha256":str(fr.decoder_xml_sha256)},"decoder_arrays":files,
      "type_mk_source":"no independent native type/MK arrays were read; XML/header observations remain separate"}

def _xml_facts(raw,blocks,digest):
    r=ET.fromstring(raw); d=r.find(".//data2d"); mass=[]
    for x in r.iter():
        if x.get("name")=="MassFluid" or x.tag.rsplit("}",1)[-1].lower()=="massfluid": mass.append({"tag":x.tag.rsplit("}",1)[-1],"raw_v":x.get("v"),"attrs":dict(x.attrib)})
    return {"np":int(blocks["np"]),"blocks":blocks["blocks"],"xml_sha256":str(digest),"Data2d":None if d is None else dict(d.attrib),"MassFluid":mass}

def _put(out,v):
    if out.is_symlink(): raise RuntimeError("output root is symlink")
    out.mkdir(parents=True,exist_ok=True); raw=json.dumps(v,sort_keys=True,separators=(",",":"),allow_nan=False).encode()+b"\n"
    if len(raw)>RIM: raise RuntimeError("bounded report exceeds 64 KiB")
    f=os.open(out/"initial-facts.json",os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    try:
        for o in range(0,len(raw),1<<16):
            x=raw[o:o+(1<<16)]
            if os.write(f,x)!=len(x): raise RuntimeError("short report write")
        os.fsync(f)
    finally: os.close(f)

def _ref(x):
    p,n,h=_bind(x,"reference"); return {"path":str(p),"bytes":n,"sha256":h}

def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument("--contract",required=True); p.add_argument("--contract-bytes",required=True,type=int); p.add_argument("--contract-sha256",required=True); p.add_argument("--output-root",required=True); a=p.parse_args(argv); out=Path(a.output_root)
    result={"schema":SCHEMA,"status":"failed","candidate":0,"science_credit":0,"core_credit":0}
    try:
        cf,cr,cb,cs=_open({"path":a.contract,"bytes":a.contract_bytes,"sha256":a.contract_sha256},"contract")
        c=json.loads(cr); _close(cf,cs[0],cs,cb)
        if c.get("schema")!="lfd01.Root.existing-decoder.initial-facts-contract.v1" or str(c.get("output_root"))!=str(out): raise RuntimeError("contract schema/output_root mismatch")
        for k in ("initial_bi4","decoder","legacy_source","generated_xml","producer_closure","producer_report"): _bind(c.get(k),k)
        tp=out/".tmp"
        if tp.is_symlink() or not tp.is_dir(): raise RuntimeError("canonical OUT/.tmp is absent or unsafe")
        sc=tp/"initial-facts"; os.mkdir(sc,0o700)
        m,sf,sp,ss,sb=_load(c["legacy_source"])
        try:
            bf,_,bb,bs=_open(c["initial_bi4"],"initial_bi4")
            try: df,_,db,ds=_open(c["decoder"],"decoder")
            except Exception: _close(bf,bs[0],bs,bb); raise
            try: gf,gr,gb,gs=_open(c["generated_xml"],"generated_xml")
            except Exception: _close(df,ds[0],ds,db); _close(bf,bs[0],bs,bb); raise
            try:
                blocks=m.parse_particle_blocks(gs[0])
                if blocks.get("xml_sha256")!=gs[2]: raise RuntimeError("generated_xml parser hash mismatch")
                fr=m.decode_frame(bs[0],ds[0],sc,0); xp=sc/"frame_0000.xml"; result=_facts(fr,xp,sc); result.update({"case_id":c.get("case_id"),"generated_xml_facts":_xml_facts(gr,blocks,gs[2]),"bindings":{k:_ref(c[k]) for k in ("initial_bi4","decoder","legacy_source","generated_xml")},"producer_refs":{"producer_closure":c["producer_closure"],"producer_report":c["producer_report"]}})
            finally: _close(gf,gs[0],gs,gb); _close(df,ds[0],ds,db); _close(bf,bs[0],bs,bb)
        finally: _close(sf,sp,ss,sb); sys.modules.pop(m.__name__,None)
    except Exception as e: result["error"]={"type":type(e).__name__,"detail":str(e)[:1000]}
    try: _put(out,result)
    except Exception: return 2
    return 0 if result.get("status")=="observed" else 1

if __name__=="__main__": raise SystemExit(main())
