#!/usr/bin/env python3
"""Read-only frame-zero Type-0/native-Mk50 central bed coverage audit for R1.

The worker consumes the exact official CSV produced by the initial QA stage;
it does not launch PartVTK or accept an expected count by construction.  Its
support bins are evidence for Root review, not a dynamic acceptance claim.
"""
from __future__ import annotations
import argparse,csv,hashlib,json
from pathlib import Path
import numpy as np

FIELDS=["Pos.x [m]","Pos.y [m]","Pos.z [m]","Zone","Idp","Type","Mk","Mass [kg]","Vel.x [m/s]","Vel.y [m/s]","Vel.z [m/s]","Rhop [kg/m^3]","Press [Pa]"]
DP=0.02; BED_MK=50; TYPE_FIXED=0; TYPE_FLUID=3; FLUID_Y=(-0.14,0.14); BED_Y=(-0.22,0.22)
PROFILE=np.asarray([[-0.2,0.0],[2.0,0.0],[3.0,0.28],[3.6,0.448],[3.9,0.448],[4.4,0.05],[4.8,0.05]],dtype=np.float64)
SEGMENTS=[(-0.2,2.0),(2.0,3.0),(3.0,3.6),(3.6,3.9),(3.9,4.4),(4.4,4.8)]
def require(v,m):
    if not v: raise ValueError(m)
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        while True:
            b=f.read(1024*1024)
            if not b: break
            h.update(b)
    return h.hexdigest()
def load(p,d,label):
    p=Path(p); require(p.is_file(),f'{label} missing'); require(sha(p)==d,f'{label} SHA mismatch'); return json.loads(p.read_text())
def read_csv(p):
    header=None; line=-1
    with Path(p).open('r',encoding='utf-8',errors='replace',newline='') as f:
        for i,row in enumerate(csv.reader(f)):
            row=[x.strip() for x in row]
            if 'Pos.x [m]' in row and 'Idp' in row and 'Type' in row: header=row; line=i; break
    require(header is not None,'CSV header missing'); require(all(k in header for k in FIELDS),'CSV fields missing')
    rows=np.loadtxt(p,delimiter=',',skiprows=line+1,usecols=[header.index(k) for k in FIELDS],ndmin=2)
    return np.asarray(rows,dtype=np.float64)
def zbed(x): return np.interp(np.asarray(x,dtype=np.float64),PROFILE[:,0],PROFILE[:,1])
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--binding',type=Path,required=True); ap.add_argument('--output-dir',type=Path,required=True); a=ap.parse_args()
    b=json.loads(a.binding.read_text()); require(b.get('schema')=='ds02.f5.c082r1.initial-mk50-coverage-binding.v1','coverage binding schema mismatch')
    out=a.output_dir.resolve(); out.mkdir(parents=True,exist_ok=True); c=b['actual_counts']; files=b['files']
    receipt=load(files['gencase_receipt']['path'],files['gencase_receipt']['sha256'],'GenCase receipt'); report=load(files['prepared_input_report']['path'],files['prepared_input_report']['sha256'],'prepared report'); qa=load(files['qa_provenance']['path'],files['qa_provenance']['sha256'],'initial QA provenance')
    require(receipt.get('status')=='completed' and receipt.get('returncode')==0,'GenCase not complete'); require(receipt.get('total_particles')==c['total_particles'] and receipt.get('fluid_particles')==c['fluid_particles'],'actual count mismatch'); require(qa.get('all_actual_checks_pass') is True,'initial QA did not pass')
    csv_path=Path(files['official_csv']['path']); require(csv_path.is_file(),'official CSV missing'); rows=read_csv(csv_path); require(rows.shape==(c['total_particles'],13),'CSV axis differs from actual producer'); require(np.isfinite(rows).all(),'CSV nonfinite')
    require(int(np.sum(rows[:,5]==TYPE_FLUID))==c['fluid_particles'],'CSV fluid differs from receipt')
    ids=rows[:,4].astype(np.int64); require(np.array_equal(np.sort(ids),np.arange(c['total_particles'])),'CSV Idp not unique/consecutive')
    fixed=(rows[:,5]==TYPE_FIXED)&(np.rint(rows[:,6]).astype(np.int64)==BED_MK); fx,fy,fz=rows[fixed,0],rows[fixed,1],rows[fixed,2]; fzprof=zbed(np.clip(fx,PROFILE[0,0],PROFILE[-1,0]))
    bins=[]
    for lo,hi in SEGMENTS:
        seg=fixed&(rows[:,0]>=lo)&(rows[:,0]<=hi)&(np.abs(rows[:,1])<=BED_Y[1]+1e-9)
        surface=np.abs(rows[:,2]-zbed(np.clip(rows[:,0],PROFILE[0,0],PROFILE[-1,0])))<=0.5*DP+1e-8
        central=seg&(np.abs(rows[:,1])<=0.01)&surface
        one=seg&(np.abs(rows[:,2]-zbed(np.clip(rows[:,0],PROFILE[0,0],PROFILE[-1,0])))<=DP+1e-8)
        two=seg&(np.abs(rows[:,2]-zbed(np.clip(rows[:,0],PROFILE[0,0],PROFILE[-1,0])))<=2*DP+1e-8)
        bins.append({'x_bounds_m':[lo,hi],'fixed_native_mk50_count':int(seg.sum()),'central_surface_half_dp_count':int(central.sum()),'central_surface_one_dp_count':int(one.sum()),'central_surface_two_dp_count':int(two.sum())})
    fluid=rows[:,5]==TYPE_FLUID; x,y,z=rows[fluid,0],rows[fluid,1],rows[fluid,2]; footprint=(x>=PROFILE[0,0])&(x<=PROFILE[-1,0])&(y>=BED_Y[0])&(y<=BED_Y[1]); depth=zbed(np.clip(x,PROFILE[0,0],PROFILE[-1,0]))-z; below=footprint&(depth>2e-7)
    result={'schema':'ds02.f5.c082r1.initial-mk50-coverage.v1','status':'completed_initial_coverage_diagnostic','diagnostic_only':True,'full_solver_authorized':False,'full16_authorized':False,'q_n_status':'not_granted','source_marker_mapping':{'source_mkbound':40,'native_bed_mk':50,'native_filter':'Type==0 and Mk==50'},'actual_counts':c,'checks':{'actual_gencase_completed':True,'initial_qa_pass_bound':True,'csv_total_matches_actual_producer':True,'csv_fluid_matches_actual_producer':True,'all_rows_finite':True,'uid_unique_consecutive':True,'fluid_initial_below_profile_zero':bool(not below.any()),'support_marker_present':bool(fixed.any())},'support':{'native_type0_mk50_support_count':int(fixed.sum()),'six_segment_bins':bins,'central_half_dp_global_count':int(sum(x['central_surface_half_dp_count'] for x in bins)),'profile_nodes_xz_m':PROFILE.tolist(),'bed_y_bounds_m':list(BED_Y),'fluid_y_bounds_m':list(FLUID_Y),'support_is_patchiness_diagnostic':True},'fluid_initial_geometry':{'footprint_count':int(footprint.sum()),'below_profile_count':int(below.sum()),'below_profile_max_depth_m':float(depth[below].max()) if below.any() else 0.0,'all_fluid_below_profile_zero':bool(not below.any())},'review_boundary':{'short_event_may_only_be_considered_after_root_review':True,'no_uniform_dense_bed_claim':True,'no_dynamic_acceptance':True,'no_full801_authorization':True},'inputs':{'gencase_receipt':files['gencase_receipt'],'prepared_input_report':files['prepared_input_report'],'qa_provenance':files['qa_provenance'],'official_csv':files['official_csv']},'arrays_opened_by_source_agent':False}
    (out/'c082r1-direct-native-initial-fixed-bed-coverage.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    require(not below.any(),'initial fluid is below source bed profile')
    print(json.dumps({'status':'completed','native_type0_mk50_support_count':int(fixed.sum()),'fluid_initial_below_profile_count':int(below.sum())},sort_keys=True))
if __name__=='__main__': main()
