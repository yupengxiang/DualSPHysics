#!/usr/bin/env python3
"""Metadata-only validator for fresh142; never opens scientific payloads."""
from __future__ import annotations
import argparse,hashlib,json,sys
from pathlib import Path
PKG=Path(__file__).resolve().parents[1]
DECODER=Path('/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump')
WRONG=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump')
PARTVTK='/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64'
KNOWN={
 '/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python':'a2f33a6e006989270f4340528eb61f8f97366e00a5d1b602ac8672ea44fc56ae',
 '/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_157_nvme_typed_home_cap_publish_cleanup_fix_v1/scripts/home_publish_math.py':'89f57c71f29bb8c47f5949aa7e5902e16378cf75a2ae8338cabc019ee3ffc268',
 '/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_157_nvme_typed_home_cap_publish_cleanup_fix_v1/scripts/nvme_convert_home_capped_v2.py':'37fe7eaff4405e9ba6d9b7f666a53d7c02ee65fc6f30992fc1a8fdb0d8a61b11',
 '/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py':'5098262e26dc5560487760181466b0a93a0e66239e5e54047dce5e761ae67a60',
 '/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py':'81bdd60e5de4fec362807043ab632864405f1667a0658560fb9349025aab75ec',
 '/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_home_floor_inventory_dispatch_142/launch.py':'708c4c83d22257f7b59bad93cd19915fb66a199a2a5b1291d6ada71bb467ea76',
 '/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_home_floor_inventory_dispatch_142/root_home_floor_inventory_policy.py':'2649eedbcf4816f8d2fa7b2182828ea8b3ce107ef47f25c56780d29c5138def5',
 str(DECODER):'b8ac8cf4aff68ffd089da6cf3ef19dfd0c6473121475f4c198b720a0ddaa8b2e',
 PARTVTK:'62630430902484f4aede017108313673fe6414f40fb59b6ae7f14ac23219db00',
}
FORBIDDEN={'.h5','.bi4','.csv','.dat','.vtk','.vtu'}; SAFE={'.json','.xml','.py','.md'}
def load(p): return json.loads(Path(p).read_text())
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()
def check(v,msg):
 if not v: raise AssertionError(msg)
def done0(p):
 o=load(p); check(o.get('status')=='completed' and o.get('returncode')==0,f'not completed/0 {p}'); return o

def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--report'); a=ap.parse_args()
 man=load(PKG/'F2_STAGE1_FRESH142_ACTUAL_NATIVE_TYPED157_MANIFEST.json'); sel=load(PKG/'metadata/selection-frozen.json')['selected_cases']
 check(man['fresh_id']=='fresh142' and man['family_id']=='F2' and len(sel)==8,'manifest')
 rc=load(PKG/'metadata/root974-tool-contract.json')
 check(rc['decoder']==str(DECODER) and rc['decoder_path_exists'] is True and DECODER.is_file(),'actual decoder missing')
 check(rc['decoder_wrong_path_exists'] is False and not WRONG.exists(),'wrong decoder path exists')
 results=[]
 exp_counts={'data2d':False,'solver_dimension':3,'total_particles':418104,'fixed_particles':372840,'moving_particles':24150,'floating_particles':0,'fluid_particles':21114,'xml_particle_counts':{'fixed':372840,'moving':24150,'floating':0,'fluid':21114}}
 for c in sel:
  rp=PKG/'requests/typed'/(c+'-typed157-home4gib-disabled.json'); op=PKG/'owners'/(c+'-actual-native-typed157-owner.json')
  check(rp.is_file() and op.is_file(),f'missing {c}')
  r=load(rp); o=load(op)
  check(r['schema']=='ds02.runner-request.v2' and r['case_id']==c and r['fresh_id']=='fresh142','identity '+c)
  for k in ('disabled','source_only','no_new_case_credit'): check(r.get(k) is True,c+' '+k)
  for k in ('launch','launch_allowed','execution_allowed','solver_allowed','conversion_allowed','arrays_allowed','array_edit_allowed'): check(r.get(k) is False,c+' '+k)
  check(r['kind']=='cpu' and r['cpu_task_kind']=='conversion' and r['cpu_threads']==2,c+' cpu')
  check(r['estimated_storage_bytes']==4294967296 and r['home_publish_cap_bytes']==4294967296 and r['home_min_free_bytes']==536870912000,c+' home')
  check(r['nvme_staging_limit_bytes']==25769803776 and r['nvme_free_reserve_bytes']==107374182400,c+' nvme')
  check(r['expected_frames']==401 and r['expected_native_frames']==401 and r['expected_dimension']==3 and r['expected_particles']==418104 and r['expected_counts']==exp_counts,c+' recipe')
  check(r['physical_condition_sha256']==o['physical_condition_sha256'] and r['source_plan_physical_condition_sha256']==o['source_plan_physical_condition_sha256'],c+' source scopes')
  check(r['canonical_physical_binding_sha256'] is None and r['actual_converter_physical_condition_scope_sha256'] is None and r['actual_converter_scope_sha256_prospective'] is None,c+' future scope')
  check(all(v is None for v in r['future_output_hashes'].values()) and all(v is None for v in r['future_input_sha256'].values()),c+' future null')
  check(str(DECODER) in r['command'] and str(WRONG) not in r['command'] and r['decoder']['path']==str(DECODER),c+' command decoder')
  check(r['owner_metadata']==str(op) and r['owner_metadata_sha256']==sha(op),c+' owner')
  check(set(r['input_files'])==set(r['input_sha256'])==set(r['input_sha256_categories'])==set(r['input_sha256_provenance']),c+' input key closure')
  for s in r['input_files']:
   check(Path(s).suffix.lower() not in FORBIDDEN,c+' scientific input leaked')
   if s in KNOWN:
    check(Path(s).exists(),c+' missing attested tool '+s); check(r['input_sha256'][s]==KNOWN[s],c+' stale tool '+s)
   else:
    p=Path(s); check(p.suffix.lower() in SAFE and p.is_file(),c+' missing metadata '+s); check(sha(p)==r['input_sha256'][s],c+' stale metadata '+s)
  for e in r['future_input_files']: check(e.get('producer_only') is True and e.get('sha256') is None,c+' future input')
  check(o['source_only'] is True and o['execution_allowed'] is False and o['canonical_physical_binding_sha256'] is None and o['actual_converter_physical_condition_scope_sha256'] is None,c+' owner policy')
  check(o['geometry']['dimension']==3 and o['density_kg_m3']==1000 and o['gravity_m_s2']==[0,0,-9.81],c+' owner geometry')
  done0(r['actual_gencase_dependency']['receipt']); done0(r['actual_initial_qa_dependency']['receipt']); done0(r['actual_native_dependency']['receipt'])
  check(sha(r['actual_gencase_dependency']['receipt'])==r['actual_gencase_dependency']['receipt_sha256'],c+' Gen sha')
  check(sha(r['actual_initial_qa_dependency']['receipt'])==r['actual_initial_qa_dependency']['receipt_sha256'],c+' QA sha')
  check(sha(r['actual_native_dependency']['receipt'])==r['actual_native_dependency']['receipt_sha256'],c+' native sha')
  q=load(r['actual_initial_qa_dependency']['report']); check(q['status']=='pass' and all(bool(v) for v in q['checks'].values()),c+' QA report')
  check(r['actual_initial_qa_dependency']['csv_sha256'] is None and r['actual_initial_qa_dependency']['csv_read_or_hashed_here'] is False,c+' CSV policy')
  prep=load(r['prepared_input_report']); check(prep['actual_total_particles']==418104 and prep['generated_xml_particle_counts']=={'fixed':372840,'moving':24150,'floating':0,'fluid':21114},c+' prepared report')
  check(Path(r['generated_xml']).is_file() and sha(r['generated_xml'])==r['generated_xml_sha256'],c+' XML')
  results.append({'case_id':c,'status':'pass','actual_native':'completed/0','actual_initial_qa':'pass','input_count':len(r['input_files']),'future_input_count':len(r['future_input_files'])})
 out={'schema':'ds02.f2.fresh142.validation.v1','status':'pass','fresh_id':'fresh142','selected_count':8,'cases':results,'actual_decoder_path':str(DECODER),'actual_decoder_exists':True,'wrong_decoder_exists':False,'scientific_payload_read_or_hashed':False,'future_hashes_all_null':True,'disabled_all':True}
 if a.report: Path(a.report).write_text(json.dumps(out,indent=2,sort_keys=True)+'\n')
 print(json.dumps(out,indent=2,sort_keys=True)); return 0
if __name__=='__main__':
 try: raise SystemExit(main())
 except Exception as e:
  print(f'fresh142 validation FAILED: {e}',file=sys.stderr); raise
