#!/usr/bin/env python3
"""Root-owned R1 initial native QA; execution is disabled in this source pack.

The worker invokes the official QA helper with the active Python interpreter,
then independently validates the actual CSV.  It never predicts a particle
count from a mother case and never rescales mass.  The native bed marker is
Type 0/Mk50; source mkbound=40 is kept as a separate provenance fact.
"""
from __future__ import annotations
import argparse, csv, hashlib, json, subprocess, sys
import xml.etree.ElementTree as ET
from pathlib import Path
import numpy as np

FIELDS=["Pos.x [m]","Pos.y [m]","Pos.z [m]","Zone","Idp","Type","Mk","Mass [kg]","Vel.x [m/s]","Vel.y [m/s]","Vel.z [m/s]","Rhop [kg/m^3]","Press [Pa]"]
TYPE_FIXED,TYPE_MOVING,TYPE_FLUID=0,1,3
DP=0.02; POINTREF=np.asarray([0.01,0.0,0.01],dtype=np.float64)
PROFILE=np.asarray([[-0.2,0.0],[2.0,0.0],[3.0,0.28],[3.6,0.448],[3.9,0.448],[4.4,0.05],[4.8,0.05]],dtype=np.float64)
FLUID_Y=(-0.14,0.14); BED_Y=(-0.22,0.22); BED_MK=50
FLUID_BOX_MIN=np.asarray([0.01,-0.14,0.01],dtype=np.float64)
FLUID_BOX_MAX=np.asarray([3.43,0.14,0.39],dtype=np.float64)

def require(v,m):
    if not v: raise ValueError(m)
def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        while True:
            block=f.read(1024*1024)
            if not block: break
            h.update(block)
    return h.hexdigest()
def load(path,digest,label):
    p=Path(path); require(p.is_file(),f'{label} missing: {p}'); require(sha(p)==digest,f'{label} SHA mismatch')
    return json.loads(p.read_text(encoding='utf-8'))
def profile_z(x):
    x=np.asarray(x,dtype=np.float64); return np.interp(x,PROFILE[:,0],PROFILE[:,1])
def xml_meta(path):
    r=ET.parse(path).getroot(); require(r.tag=='case','generated XML root')
    d=r.find('./execution/constants/data2d'); require(d is not None and d.get('value','true').lower()=='false','R1 is not 3-D')
    p=r.find('./execution/particles'); require(p is not None,'particles metadata missing')
    counts={"fixed":0,"moving":0,"floating":0,"fluid":0}
    for n in p:
        if n.tag in {'fixed','moving','floating','fluid'}: counts[n.tag]=counts.get(n.tag,0)+int(n.get('count','-1'))
    total=int(p.get('np','-1')); require(total>0 and sum(counts.values())==total,'XML counts do not sum')
    return total,counts
def read_csv(path):
    header=None; line=-1
    with Path(path).open('r',encoding='utf-8',errors='replace',newline='') as f:
        for i,row in enumerate(csv.reader(f)):
            row=[x.strip() for x in row]
            if 'Pos.x [m]' in row and 'Idp' in row and 'Type' in row:
                header=row; line=i; break
    require(header is not None,'official CSV header missing')
    require(all(k in header for k in FIELDS),'official CSV fields incomplete')
    rows=np.loadtxt(path,delimiter=',',skiprows=line+1,usecols=[header.index(k) for k in FIELDS],ndmin=2)
    rows=np.asarray(rows,dtype=np.float64); require(rows.ndim==2 and rows.shape[1]==13,'CSV shape invalid')
    return rows

def support_summary(rows):
    bed=(rows[:,5]==TYPE_FIXED)&(np.rint(rows[:,6]).astype(np.int64)==BED_MK)
    x=rows[:,0]; z=rows[:,2]; y=rows[:,1]; zz=profile_z(np.clip(x,PROFILE[0,0],PROFILE[-1,0]));
    segments=[(-0.2,2.0),(2.0,3.0),(3.0,3.6),(3.6,3.9),(3.9,4.4),(4.4,4.8)]
    per=[]
    for lo,hi in segments:
        m=bed&(x>=lo)&(x<=hi)&(np.abs(y)<=0.01)&(np.abs(z-zz)<=0.5*DP+1e-8)
        per.append({'x_bounds_m':[lo,hi],'central_surface_half_dp_count':int(m.sum())})
    return {'native_mk50_count':int(bed.sum()),'native_mk50_central_surface_half_dp_by_segment':per,'source_mkbound':40,'native_bed_marker':50}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--binding',type=Path,required=True); ap.add_argument('--output-dir',type=Path,required=True); a=ap.parse_args()
    b=json.loads(a.binding.read_text(encoding='utf-8')); require(b.get('schema')=='ds02.f5.c082r1.actual-initial-qa-binding.v1','R1 binding schema mismatch')
    out=a.output_dir.resolve(); out.mkdir(parents=True,exist_ok=True); files=b['files']; counts=b['actual_counts']
    receipt_path=Path(files['gencase_receipt']['path']); report_path=Path(files['prepared_input_report']['path']); xml_path=Path(files['generated_xml']['path']); bi4_path=Path(files['generated_bi4']['path'])
    receipt=load(receipt_path,files['gencase_receipt']['sha256'],'R1 GenCase receipt'); report=load(report_path,files['prepared_input_report']['sha256'],'R1 prepared report')
    require(receipt.get('status')=='completed' and receipt.get('returncode')==0,'R1 GenCase receipt not completed/zero')
    require(receipt.get('request',{}).get('case_id')==b['case_id'],'nested receipt case mismatch'); require(receipt.get('request',{}).get('attempt_id')==b['attempt_id'],'nested receipt attempt mismatch')
    require(receipt.get('solver_dimension_from_gencase')==3,'R1 receipt not 3-D'); total=int(receipt['total_particles']); fluid=int(receipt['fluid_particles'])
    require(total==counts['total_particles'] and fluid==counts['fluid_particles'],'binding does not match actual receipt')
    require(Path(receipt.get('output_root','')).resolve()==Path(files['gencase_output_root']['path']).resolve(),'actual receipt output root mismatch')
    report_counts=report.get('generated_xml_particle_counts',{}); require(report.get('actual_total_particles')==total,'prepared total mismatch')
    xml_total,xml_counts=xml_meta(xml_path); require(sha(xml_path)==files['generated_xml']['sha256'],'generated XML SHA mismatch'); require(xml_total==total,'XML total mismatch'); require(xml_counts==report_counts,'XML/report counts mismatch'); require(xml_counts.get('fluid')==fluid,'XML fluid mismatch')
    runtime={'partvtk':b['partvtk'],'cases':[{'role':'R1','receipt':str(receipt_path),'prefix':str(xml_path.with_suffix('')),'expected_total':total,'expected_fluid':fluid,'expected_types':[0,1,3],'compact_f5_geometry':True,'cells_y':15}]}
    runtime_path=out/'qa054-runtime-binding.json'; runtime_path.write_text(json.dumps(runtime,indent=2,sort_keys=True)+'\n')
    proc=subprocess.run([sys.executable,str(b['qa054_tool']),'--binding',str(runtime_path),'--output-dir',str(out)],cwd=str(out),check=False)
    require(proc.returncode==0,'official QA helper failed')
    csv_path=out/'R1-initial-all.csv'; require(csv_path.is_file(),'official R1 CSV missing')
    rows=read_csv(csv_path); require(rows.shape==(total,13),f'CSV shape {rows.shape} != ({total},13)'); require(np.isfinite(rows).all(),'CSV contains nonfinite values')
    # The density column is real-valued; only Zone/Idp/Type/Mk are categorical.
    require(np.equal(rows[:,3:7],np.rint(rows[:,3:7])).all(),'categorical CSV fields nonintegral')
    require(np.all(rows[:,3]==0),'native Zone is not zero'); ids=rows[:,4].astype(np.int64); require(np.array_equal(np.sort(ids),np.arange(total)),'Idp is not unique/consecutive')
    require(set(int(v) for v in np.unique(rows[:,5]))=={0,1,3},'native Type set differs from XML'); require(int(np.sum(rows[:,5]==3))==fluid,'actual fluid count mismatch')
    require(np.all(rows[:,7]>0) and np.all(rows[:,11]>0),'mass/density not positive'); require(float(np.max(np.abs(rows[:,8:11])))<=1e-8,'initial velocity nonzero')
    coords=rows[:,:3]; require(np.unique(coords,axis=0).shape[0]==total,'native coordinates duplicate')
    sets={t:{tuple(float(v) for v in row) for row in rows[rows[:,5]==t,:3]} for t in (0,1,3)}
    overlap={'fixed_moving':len(sets[0]&sets[1]),'fixed_fluid':len(sets[0]&sets[3]),'moving_fluid':len(sets[1]&sets[3])}; require(not any(overlap.values()),f'fixed/moving/fluid spatial overlap {overlap}')
    fluid_mask=rows[:,5]==TYPE_FLUID; fxyz=rows[fluid_mask,:3]; fx,fy,fz=fxyz.T; fbed=profile_z(fx)
    outside=((fxyz<FLUID_BOX_MIN-1e-8)|(fxyz>FLUID_BOX_MAX+1e-8)).any(axis=1)
    below=fz < fbed-2e-7; require(not outside.any(),'initial fluid outside source clip/box'); require(not below.any(),'initial fluid below exact source bed profile')
    ys=np.unique(np.round(fy,10)); require(len(ys)==15,'fluid y lattice has unexpected number of levels')
    lattice=(fxyz-POINTREF)/DP; residual=np.max(np.abs(lattice-np.rint(lattice)),axis=1); require(float(residual.max())<=1e-6,'fluid coordinates are not dp lattice aligned')
    support=support_summary(rows); require(support['native_mk50_count']>0,'no Type0/native Mk50 bed marker exists')
    fluid_mass=float(rows[fluid_mask,7].sum()); continuum=float(b['continuum_mass_kg']); require(np.isfinite(fluid_mass-continuum),'fluid mass difference is nonfinite')
    qa_report=out/'native-initial-qa.json'; require(qa_report.is_file(),'official QA report missing')
    result={'schema':'ds02.f5.c082r1.actual-initial-qa.v1','status':'actual_native_qa','all_actual_checks_pass':True,'diagnostic_only':True,'q_n_status':'not_granted','full_solver_authorized':False,'actual_counts':{'total_particles':total,'fixed_particles':int(np.sum(rows[:,5]==0)),'moving_particles':int(np.sum(rows[:,5]==1)),'fluid_particles':fluid,'solver_dimension':3,'xml_particle_counts':xml_counts},'checks':{'actual_gencase_receipt_completed':True,'actual_xml_total_and_3d':True,'all_native_rows_finite':True,'categorical_columns_integral_density_real_valued':True,'mass_density_positive':True,'idp_unique_consecutive':True,'native_type_codes_match_actual_contract':True,'zero_initial_velocity':True,'fixed_moving_fluid_spatial_no_overlap':True,'fluid_inside_exact_source_profile_and_box':True,'fluid_initial_below_profile_zero':True,'fluid_dp_lattice_aligned':True,'native_type0_mk50_bed_marker_present':True,'native_fluid_mass_difference_reported_without_rescale':True},'source_marker_mapping':{'source_mkbound':40,'native_bed_mk':50},'support_diagnostic':support,'fluid_geometry':{'source_fluid_box_min_m':FLUID_BOX_MIN.tolist(),'source_fluid_box_max_m':FLUID_BOX_MAX.tolist(),'x_bounds_m':[float(fx.min()),float(fx.max())],'y_bounds_m':[float(fy.min()),float(fy.max())],'z_bounds_m':[float(fz.min()),float(fz.max())],'unique_y_levels':ys.tolist(),'below_profile_count':int(below.sum()),'outside_source_box_or_profile_count':int(outside.sum()),'max_fluid_lattice_residual':float(residual.max())},'native_fluid_mass':{'csv_mass_kg':fluid_mass,'continuum_mass_kg':continuum,'difference_kg':fluid_mass-continuum,'mass_rescaled':False},'genuine_gencase':{'receipt':str(receipt_path),'receipt_sha256':files['gencase_receipt']['sha256'],'prepared_input_report':str(report_path),'prepared_input_report_sha256':files['prepared_input_report']['sha256'],'generated_xml':str(xml_path),'generated_xml_sha256':files['generated_xml']['sha256'],'generated_bi4':str(bi4_path),'generated_bi4_sha256':files['generated_bi4']['sha256']},'official_qa_report':str(qa_report),'official_qa_report_sha256':sha(qa_report),'interpretation':'step-zero native structural/initial geometry evidence only; central support remains a diagnostic report and no dynamic/full16/full801 authorization is granted','arrays_opened_by_source_agent':False}
    (out/'r1-initial-qa-provenance.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'status':'completed','actual_total_particles':total,'actual_fluid_particles':fluid,'all_actual_checks_pass':True},sort_keys=True))
if __name__=='__main__': main()
