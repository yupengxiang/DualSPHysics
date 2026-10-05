#!/usr/bin/env python3
"""Build the F7 fresh071 actual GenCase -> native QA metadata binding.

This script is metadata-only. It reads bounded JSON/XML, checks Root003 receipt
and XML/report contracts, and hashes receipt/report/XML/Def metadata. It never
opens BI4, CSV, H5, or motion payload bytes. PartVTK is invoked only by the
separate disabled runtime worker after Root enables the request.
"""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
import xml.etree.ElementTree as ET

CASES = [
    'F7_OBSTACLE_QUINTIC_B08_A031','F7_OBSTACLE_QUINTIC_B08_A032',
    'F7_OBSTACLE_QUINTIC_B08_A033','F7_OBSTACLE_QUINTIC_B08_A034',
    'F7_OBSTACLE_QUINTIC_B08_A036','F7_OBSTACLE_QUINTIC_B08_A037',
    'F7_OBSTACLE_QUINTIC_B08_A038','F7_OBSTACLE_QUINTIC_B08_A039',
    'F7_OBSTACLE_QUINTIC_B08_A041','F7_OBSTACLE_QUINTIC_B08_A042',
    'F7_OBSTACLE_QUINTIC_B08_A043','F7_OBSTACLE_QUINTIC_B08_A044',
    'F7_OBSTACLE_QUINTIC_B08_A046','F7_OBSTACLE_QUINTIC_B08_A047',
    'F7_OBSTACLE_QUINTIC_B08_A048','F7_OBSTACLE_QUINTIC_B08_A049',
]
DATA = Path('/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7')
OUT = Path(__file__).resolve().parents[1]

def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def load(p): return json.loads(Path(p).read_text())
def dump(p,v): Path(p).parent.mkdir(parents=True,exist_ok=True); Path(p).write_text(json.dumps(v,indent=2,sort_keys=True)+'\n')
def req(ok,msg):
    if not ok: raise RuntimeError(msg)
def paths(case):
    a=DATA/case/f'root-stage1-f7-{case.lower()}-genuine-gencase-070'; q=a/'prepared'
    return {'attempt':a,'receipt':a/'execution-receipt.json','report':q/'prepared-input-report.json','xml':q/f'{case}.xml','bi4':q/f'{case}.bi4','definition':q/f'{case}_Def.xml','motion':q/'motion_obstacle_quintic.dat'}
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--plan',type=Path,default=OUT/'metadata/first24-plan.json'); ap.add_argument('--gencase-bindings',type=Path,required=True); ap.add_argument('--output',type=Path,default=OUT/'metadata/actual-native-qa-binding.json'); args=ap.parse_args()
    plan=load(args.plan); group=load(args.gencase_bindings); req(group.get('schema')=='ds02.f7.first24.gencase-bindings.v1','group schema mismatch'); req(len(group.get('bindings',[]))==16,'expected 16 group bindings')
    planby={x['endpoint_id']:x for x in plan['endpoints']}; cases=[]
    for ge in group['bindings']:
        b=load(ge['binding']); case=b['case_id']; req(case in CASES and case in planby,'case not in first24 scope'); p=paths(case)
        for k in ('receipt','report','xml','bi4','definition','motion'): req(p[k].is_file(),f'{case}: missing {k}')
        rec=load(p['receipt']); req(rec.get('status')=='completed' and rec.get('returncode')==0,f'{case}: GenCase not completed/0')
        report=load(p['report']); req(report.get('schema')=='ds02.root.actual-native-source-preflight.v1','report schema mismatch')
        root=ET.parse(p['xml']).getroot(); c=root.find('./execution/constants'); particles=root.find('./execution/particles'); d=root.find('./casedef/geometry/definition'); req(c is not None and particles is not None and d is not None,'XML sections missing')
        req(c.find('data2d') is not None and c.find('data2d').get('value')=='false','not 3D'); params={x.get('key'):x.get('value') for x in root.findall('./execution/parameters/parameter')}; req(d.get('dp')=='0.02' and params.get('TimeMax')=='12' and params.get('TimeOut')=='0.02','recipe changed')
        counts={n:sum(int(x.get('count')) for x in particles.findall(n)) for n in ('fixed','moving','floating','fluid')}; req(int(particles.get('np'))==int(rec['total_particles'])==int(report['actual_total_particles']),'total mismatch'); req(counts==report.get('generated_xml_particle_counts'),'report/XML mismatch'); req(counts=={'fixed':27495,'moving':1984,'floating':0,'fluid':40700},f'{case}: counts differ')
        blocks=[]
        for name,typ,mk in (('fixed',0,10),('moving',1,12),('fluid',3,2)):
            node=particles.find(name); ident=node.get('id',''); begin=int(ident.split('-',1)[0]) if '-' in ident else sum(x['count'] for x in blocks); blocks.append({'name':name,'begin':begin,'count':int(node.get('count')),'type':typ,'mk':mk})
        source_def=OUT/'source'/f'{case}_Def.xml'; req(source_def.is_file(),'source Def missing'); owner=load(OUT/'owners'/f'{case}.owner.json')
        cases.append({'case_id':case,'physical_case_id':case,'amplitude_deg':planby[case]['amplitude_deg'],'physical_condition_sha256':b['physical_condition_sha256'],'canonical_physical_binding_sha256':owner['canonical_physical_binding_sha256'],'gencase_receipt':str(p['receipt']),'gencase_receipt_sha256':sha(p['receipt']),'prepared_input_report':str(p['report']),'prepared_input_report_sha256':sha(p['report']),'generated_xml':str(p['xml']),'generated_xml_sha256':sha(p['xml']),'generated_bi4':str(p['bi4']),'generated_bi4_sha256':None,'generated_definition':str(p['definition']),'generated_definition_sha256':sha(p['definition']),'generated_motion':str(p['motion']),'generated_motion_sha256':None,'source_motion':str(DATA/'F7_STAGE1_FIRST24_TARGET_ANGLES/root-stage1-f7-first24-motion-preparation-070/prepared'/case/'motion_obstacle_quintic.dat'),'source_motion_sha256':None,'source_definition':str(source_def),'source_definition_sha256':sha(source_def),'prepared_definition':str(p['definition']),'prepared_definition_sha256':sha(p['definition']),'actual_counts':{'total':int(rec['total_particles']),'fixed':counts['fixed'],'moving':counts['moving'],'floating':counts['floating'],'fluid':counts['fluid'],'dimension':int(rec['solver_dimension_from_gencase'])},'expected':{'total_particles':int(rec['total_particles']),'fixed_particles':counts['fixed'],'moving_particles':counts['moving'],'fluid_particles':counts['fluid'],'solver_dimension':3,'dp_m':0.02,'time_max_s':12.0,'time_out_s':0.02,'motion_rows':12001,'type_mk_blocks':blocks,'velocity_zero_tolerance_m_per_s':1e-12,'native_fluid_mass_kg':325.60001628,'continuum_envelope_mass_kg':320.1984,'mass_tolerance_kg':1e-8}})
    out={'schema':'ds02.f7.first24.actual-gencase-native-qa-binding.v1','scope_id':'root_followup_071_stage1_first24_actual_gencase_qa_native_v1','partvtk':'/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64','partvtk_sha256':'62630430902484f4aede017108313673fe6414f40fb59b6ae7f14ac23219db00','source_plan':{'source_absolute_path':str(args.plan),'source_sha256':sha(args.plan)},'gencase_binding_group':{'source_absolute_path':str(args.gencase_bindings),'source_sha256':sha(args.gencase_bindings)},'cases':cases,'launch_allowed':False,'execution_allowed':False,'arrays_read_by_binder':False,'raw_payload_policy':{'bi4':'presence checked only; no source hash/read','motion_dat':'presence checked only; no source hash/read','csv':'not read','h5':'not read'},'claim_boundary':'Actual Root003 GenCase receipt/report/XML metadata is bound. Official PartVTK initial UID/type/Mk/mass/3D/no-overlap QA remains disabled and pending a Root CPU audit.'}
    dump(args.output,out)
if __name__=='__main__': main()
