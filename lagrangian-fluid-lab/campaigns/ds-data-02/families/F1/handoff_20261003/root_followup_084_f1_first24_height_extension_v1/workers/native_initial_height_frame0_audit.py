#!/usr/bin/env python3
"""Disabled Root-only native frame-0 audit for fresh084 height candidates.
The source turn never invokes this worker or opens BI4/H5/CSV arrays. Root enables it
only after actual GenCase and native completed/0 receipts. Counts come from the actual
prepared-input-report; solver-saved Part_0000.bi4 is read only through official PartVTK.
"""
from __future__ import annotations
import argparse,csv,hashlib,json,math,subprocess
from pathlib import Path
import xml.etree.ElementTree as ET

def load(p):
    v=json.loads(Path(p).read_text(encoding="utf-8")); assert isinstance(v,dict); return v
def sha(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b): h.update(b)
    return h.hexdigest()
def req(x,m):
    if not x: raise RuntimeError(m)
def num(x,m):
    v=float(x.strip()); req(math.isfinite(v),m); return v
def col(h,names):
    for n in names:
        if n in h:return h.index(n)
    raise RuntimeError("missing column "+str(names))
def frame_summary(summary,case):
    hi=None
    for i,row in enumerate(summary):
        labels={x.strip():j for j,x in enumerate(row) if x.strip()}
        if all(x in labels for x in ("TimeStep [s]","Np","Nfluid")):
            hi=(i,labels);break
    req(hi is not None,case["case_id"]+": missing named TimeStep header")
    i,l=hi; data=next((r for r in summary[i+1:] if any(x.strip() for x in r)),None)
    req(data is not None,case["case_id"]+": missing TimeStep row")
    t=num(data[l["TimeStep [s]"]],"TimeStep [s]"); req(abs(t)<=5e-5,case["case_id"]+": frame time not zero")
    return {"time_s":t,"np":int(num(data[l["Np"]],"Np")),"nfluid":int(num(data[l["Nfluid"]],"Nfluid")),"header":summary[i],"row":data}
def audit(case,out):
    r=load(case["native_solver_receipt"]); req(r.get("status")=="completed" and r.get("returncode")==0,case["case_id"]+": native not completed/0")
    prep=load(case["prepared_input_report"]); total=int(prep["actual_total_particles"]); fluid_expected=int(prep["actual_fluid_particles"])
    root=ET.parse(case["generated_xml"]).getroot(); d2=root.find("./execution/constants/data2d"); req(d2 is not None and str(d2.get("value","")).lower()=="false",case["case_id"]+": not 3-D")
    frame=Path(case["native_data_dir"])/"Part_0000.bi4"; req(frame.is_file(),case["case_id"]+": frame0 missing"); before=sha(frame)
    prefix=Path(out)/(case["case_id"]+"-frame0"); cmd=[case["partvtk"],"-dirdata",str(frame.parent),"-first:0","-last:0","-threads:4","-savecsv",str(prefix),"-onlytype:+all","-vars:-all,+idp,+vel,+rhop,+press,+type,+mk,+mass,+zone","-csvsep:1"]
    subprocess.run(cmd,cwd=out,check=True); csvs=sorted(Path(out).parent.glob(Path(prefix).name+"_*.csv")); req(csvs,case["case_id"]+": PartVTK CSV missing")
    summary=[]; header=None; rows=0; finite=0; fluid=0; ids=set(); coords=set(); levels=[set(),set(),set()]; maxerr=0.0; expected=tuple(float(x) for x in case["expected_velocity_m_per_s"])
    with csvs[0].open(newline="",encoding="utf-8") as f:
        for row in csv.reader(f):
            if header is None:
                if "Pos.x [m]" in row:header=row
                else:summary.append(row)
                continue
            if not any(x.strip() for x in row):continue
            ix={k:col(header,n) for k,n in {"x":("Pos.x [m]",),"y":("Pos.y [m]",),"z":("Pos.z [m]",),"id":("Idp","Idp [none]"),"zone":("Zone",),"type":("Type",),"mk":("Mk",),"mass":("Mass [kg]","Mass"),"vx":("Vel.x [m/s]",),"vy":("Vel.y [m/s]",),"vz":("Vel.z [m/s]",),"rho":("Rhop [kg/m^3]",)}.items()}
            vals=[num(row[ix[k]],k) for k in ("x","y","z","mass","vx","vy","vz","rho")]; rows+=1; finite+=int(all(math.isfinite(v) for v in vals))
            xyz=(vals[0],vals[1],vals[2]); coords.add(xyz); ids.add((int(float(row[ix["zone"]])),int(float(row[ix["id"]]))))
            for j,v in enumerate(xyz):levels[j].add(v)
            if int(float(row[ix["type"]]))==3 and int(float(row[ix["mk"]]))==1:
                fluid+=1; maxerr=max(maxerr,*(abs(a-b) for a,b in zip((vals[4],vals[5],vals[6]),expected)))
    req(header is not None,case["case_id"]+": particle header missing"); fs=frame_summary(summary,case)
    req(fs["np"]==total and fs["nfluid"]==fluid_expected,case["case_id"]+": summary counts mismatch"); req(rows==total and finite==rows,case["case_id"]+": finite/count mismatch"); req(fluid==fluid_expected,case["case_id"]+": Type3/Mk1 mismatch")
    req(len(ids)==rows and len(coords)==rows,case["case_id"]+": duplicate identity/coordinates"); req(all(len(x)>1 for x in levels),case["case_id"]+": not true 3-D"); req(maxerr<=1e-6,case["case_id"]+": frame0 velocity mismatch"); req(sha(frame)==before,case["case_id"]+": PartVTK mutated BI4")
    return {"case_id":case["case_id"],"passed":True,"actual_total_particles":total,"actual_fluid_particles":fluid_expected,"native_rows":rows,"fluid_rows":fluid,"finite_rows":finite,"unique_identity_count":len(ids),"unique_coordinate_count":len(coords),"fluid_3d_levels":[len(x) for x in levels],"frame_summary":fs,"max_abs_velocity_error_m_s":maxerr,"native_frame0_bi4_sha256_before_partvtk":before,"native_frame0_bi4_sha256_after_partvtk":sha(frame),"gencase_raw_velocity_evidence":"not_used","mass_rescaling":False}
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--binding",required=True,type=Path); ap.add_argument("--output-dir",required=True,type=Path); a=ap.parse_args()
    b=load(a.binding); req(b["source_only"] and not b["execution_allowed"],"binding enabled"); a.output_dir.mkdir(parents=True,exist_ok=True)
    results=[audit(c,a.output_dir) for c in b["cases"]]; out=a.output_dir/"native-initial-height-audit.json"; req(not out.exists(),"refusing overwrite")
    out.write_text(json.dumps({"schema":"ds02.f1.native-frame0-height-audit.v1","source_only_worker":True,"cases":results,"native_frame0_source":"official PartVTK on solver-saved Part_0000.bi4","gencase_raw_velocity_claim":"not_used","q_n":"not_assessed","production_approval":"none","independent_case_count_increment":0},indent=2,sort_keys=True)+"\n",encoding="utf-8")
if __name__=="__main__":main()
