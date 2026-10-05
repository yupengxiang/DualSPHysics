#!/usr/bin/env python3
"""Root-only B071 initial native QA wrapper; source preparation is read-only.

The wrapper validates the completed B071 GenCase receipt, generated XML and
prepared report before invoking the unchanged QA054 native CSV helper. It
never launches GenCase/solver/conversion itself and never changes the BI4.
The worker derives total/fluid counts from the actual receipt; no mother case
or expected-fluid substitution is used.
"""
from __future__ import annotations
import argparse, csv, hashlib, json, subprocess, sys, xml.etree.ElementTree as ET
from pathlib import Path
import numpy as np

CSV_FIELDS = ["Pos.x [m]", "Pos.y [m]", "Pos.z [m]", "Zone", "Idp", "Type", "Mk", "Mass [kg]", "Vel.x [m/s]", "Vel.y [m/s]", "Vel.z [m/s]", "Rhop [kg/m^3]", "Press [Pa]"]

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def req(v,msg):
    if not v: raise ValueError(msg)

def load(path, digest, label):
    req(Path(path).is_file(), f'{label} missing: {path}')
    req(sha(path)==digest, f'{label} SHA mismatch')
    return json.loads(Path(path).read_text())

def xml_counts(path):
    root=ET.parse(path).getroot()
    req(root.tag=='case','generated XML root is not case')
    data2d=root.find('./execution/constants/data2d')
    req(data2d is not None and data2d.get('value','true').lower()=='false','B071 XML is not 3-D')
    particles=root.find('./execution/particles'); req(particles is not None,'particles block missing')
    blocks=[]
    for n in particles:
        if n.tag in {'fixed','moving','floating','fluid'}:
            blocks.append({'kind':n.tag,'begin':int(n.get('begin','-1')),'count':int(n.get('count','-1')),'mk':int(n.get('mk','-1'))})
    req(int(particles.get('np','-1'))>0,'XML np missing')
    req(sum(x['count'] for x in blocks)==int(particles.get('np','-1')),'XML blocks do not sum to np')
    return root, int(particles.get('np','-1')), blocks

def load_csv(path):
    with Path(path).open('r',encoding='utf-8',errors='replace',newline='') as f:
        reader=csv.reader(f); header=None
        for row in reader:
            if 'Pos.x [m]' in row and 'Idp' in row: header=[x.strip() for x in row]; break
        req(header is not None,'official CSV header missing')
        req(all(k in header for k in CSV_FIELDS),'official CSV fields incomplete')
        rows=np.loadtxt(f,delimiter=',',usecols=[header.index(k) for k in CSV_FIELDS],ndmin=2)
    return np.asarray(rows,dtype=np.float64)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--binding',type=Path,required=True); ap.add_argument('--output-dir',type=Path,required=True); args=ap.parse_args()
    b=json.loads(args.binding.read_text()); out=args.output_dir.resolve(); out.mkdir(parents=True,exist_ok=True)
    req(b.get('schema')=='ds02.f5.b071.actual-initial-qa-binding.v1','unexpected B071 QA binding schema')
    files=b['files']; receipt_path=Path(files['gencase_receipt']['path']); report_path=Path(files['prepared_input_report']['path']); xml_path=Path(files['generated_xml']['path']); bi4_path=Path(files['generated_bi4']['path'])
    receipt=load(receipt_path,files['gencase_receipt']['sha256'],'genuine B071 receipt')
    report=load(report_path,files['prepared_input_report']['sha256'],'B071 prepared report')
    req(receipt.get('status')=='completed' and receipt.get('returncode')==0,'B071 GenCase receipt not completed/zero')
    actual_total=int(receipt['total_particles']); actual_fluid=int(receipt['fluid_particles']); req(receipt.get('solver_dimension_from_gencase')==3,'B071 GenCase is not 3-D')
    req(actual_total==int(b['actual_counts']['total_particles']) and actual_fluid==int(b['actual_counts']['fluid_particles']),'binding counts differ from actual receipt')
    req(report.get('actual_total_particles')==actual_total and report.get('generated_xml_particle_counts',{}).get('fluid')==actual_fluid,'prepared report differs from actual receipt')
    root,np_total,blocks=xml_counts(xml_path); req(sha(xml_path)==files['generated_xml']['sha256'],'generated XML SHA mismatch'); req(np_total==actual_total,'XML np differs from receipt')
    req(Path(receipt.get('output_root','')).resolve()==Path(files['gencase_output_root']['path']).resolve(),'receipt output root mismatch')
    req(Path(b['root_inventory_policy_source']).is_file() and sha(b['root_inventory_policy_source'])==b['root_inventory_policy_source_sha256'],'Root inventory policy source mismatch')
    runtime_binding={'partvtk':b['partvtk'],'cases':[{'role':'B071','receipt':str(receipt_path),'prefix':str(xml_path.with_suffix('')),'expected_total':actual_total,'expected_fluid':actual_fluid,'expected_types':[0,1,3]}]}
    runtime_binding_path=out/'qa054-runtime-binding.json'; runtime_binding_path.write_text(json.dumps(runtime_binding,indent=2,sort_keys=True)+'\n')
    proc=subprocess.run([sys.executable,b['qa054_tool'],'--binding',str(runtime_binding_path),'--output-dir',str(out)],cwd=out,check=False)
    req(proc.returncode==0,'QA054 helper failed')
    csv_path=out/'B071-initial-all.csv'; req(csv_path.is_file(),'QA054 CSV missing')
    rows=load_csv(csv_path); req(rows.shape==(actual_total,13),'native CSV shape differs from actual XML total'); req(np.isfinite(rows).all(),'native rows contain nonfinite values')
    req(np.equal(rows[:,3:7],np.rint(rows[:,3:7])).all(),'native categorical columns nonintegral')
    req(np.all(rows[:,3]==0),'native Zone is not zero'); ids=rows[:,4].astype(np.int64); req(np.array_equal(np.sort(ids),np.arange(actual_total)),'native Idp is not consecutive/unique')
    req(set(int(x) for x in np.unique(rows[:,5]))=={0,1,3},'native type set differs from XML contract'); fluid=rows[:,5]==3; req(int(fluid.sum())==actual_fluid,'native fluid count differs from actual receipt')
    req(np.all(rows[:,7]>0) and np.all(rows[:,11]>0),'native mass/density not positive'); max_vel=float(np.abs(rows[:,8:11]).max()); req(max_vel<=1e-8,'nonzero initial velocity')
    coords=rows[:,:3]; req(len(np.unique(coords,axis=0))==actual_total,'native coordinates duplicated')
    sets={code:{tuple(float(v) for v in row) for row in rows[rows[:,5]==code,:3]} for code in (0,1,3)}
    overlap={'fixed_moving':len(sets[0]&sets[1]),'fixed_fluid':len(sets[0]&sets[3]),'moving_fluid':len(sets[1]&sets[3])}; req(not any(overlap.values()),f'spatial overlap: {overlap}')
    fluid_mass=float(rows[fluid,7].sum()); continuum=float(b['continuum_mass_kg']); diff=fluid_mass-continuum
    req(np.isfinite(diff),'fluid mass difference nonfinite')
    qareport=json.loads((out/'native-initial-qa.json').read_text())
    result={'schema':'ds02.f5.b071.actual-initial-qa.v1','status':'actual_native_qa','all_actual_checks_pass':True,'diagnostic_only':True,'q_n_status':'not_granted','full_solver_authorized':False,'actual_counts':{'total_particles':actual_total,'fixed_particles':int((rows[:,5]==0).sum()),'moving_particles':int((rows[:,5]==1).sum()),'fluid_particles':actual_fluid,'solver_dimension':3},'checks':{'actual_gencase_receipt_completed':True,'actual_xml_total_and_3d':True,'all_native_rows_finite':True,'mass_density_positive':True,'idp_unique_consecutive':True,'native_type_codes_match_actual_contract':True,'zero_initial_velocity':True,'fixed_moving_fluid_spatial_no_overlap':True,'native_fluid_mass_difference_reported_without_rescale':True,'source_and_actual_outputs_read_only':True},'genuine_gencase':{'receipt':str(receipt_path),'receipt_sha256':files['gencase_receipt']['sha256'],'prepared_input_report':str(report_path),'prepared_input_report_sha256':files['prepared_input_report']['sha256'],'generated_xml':str(xml_path),'generated_xml_sha256':files['generated_xml']['sha256'],'generated_bi4':str(bi4_path),'generated_bi4_sha256':files['generated_bi4']['sha256']},'native_fluid_mass':{'csv_mass_kg':fluid_mass,'continuum_mass_kg':continuum,'difference_kg':diff,'mass_rescaled':False},'spatial_overlap':overlap,'maximum_initial_velocity_m_s':max_vel,'qa054_report':str(out/'native-initial-qa.json'),'qa054_report_sha256':sha(out/'native-initial-qa.json'),'actual_fluid_count_source':'genuine B071 GenCase receipt; no expected-fluid substitution','root_inventory_policy_source_sha256':b['root_inventory_policy_source_sha256'],'interpretation':'initial native structural QA only; no bed coverage or dynamic acceptance'}
    (out/'b071-initial-qa-provenance.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'status':'completed','actual_total_particles':actual_total,'actual_fluid_particles':actual_fluid,'all_actual_checks_pass':True},sort_keys=True))
if __name__=='__main__': main()
