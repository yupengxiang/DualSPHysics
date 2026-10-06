from pathlib import Path
import json, hashlib, subprocess, datetime, xml.etree.ElementTree as ET
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics')
W=Path('/home/jade/.codex/worktrees/ds-data-02-f3/DualSPHysics')
H=R/'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003'
O=H/'root_stage1_f1_delegated_visual083084085_exact_adoption_and_metadata_integration_784'
O.mkdir(exist_ok=True)
def load(p):
 p=Path(p); assert p.suffix in {'.json','.xmf','.xml','.png','.py','.md'},p
 return json.loads(p.read_text())
def sha(p):
 p=Path(p); assert p.suffix in {'.json','.xmf','.xml','.png','.py','.md'},p
 return hashlib.sha256(p.read_bytes()).hexdigest()
def put(p,d):Path(p).write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
def ref(p):return {'path':str(p),'sha256':sha(p)}
def receipt(p):
 x=load(p);assert x['status']=='completed' and x['returncode']==0,(p,x['status'],x['returncode']);return ref(p)
cp=load(H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_100.json')
previous=cp['accepted_decisions']+load(next(H.glob('root*_780'))/'actual-first2-integration-review.json')['decisions']
ids={load(p).get('physical_case_id',load(p)['case_id']) for p in previous}
hashes={load(p)['physical_condition_sha256'] for p in previous}
runtimeids={load(p)['case_id'] for p in previous}
assert len(previous)==92 and len(ids)==92
assert not (O/'actual-integration-review.json').exists(),'already adopted; never increment again'
sources=[]; decisions=[]
for number,commit in [(83,'4b3d01889d6c82143cfa41251a4ddb1651af8338'),(84,'80aa7ea969cf2207fd66d39cd45a242a1e9a1c3f'),(85,'1c0556a8835cb070aebed3ea4adaeb40bc88d314')]:
 commit=subprocess.run(['git','rev-parse',commit],cwd=W,capture_output=True,text=True,check=True).stdout.strip()
 src=next((W/'lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003').glob(f'root_followup_{number:03d}_f1_dual_visual_decisions_v1'))
 rel=src.relative_to(W)
 files=subprocess.run(['git','ls-tree','-r','--name-only',commit,'--',str(rel)],cwd=W,capture_output=True,text=True,check=True).stdout.splitlines();assert files
 adopted=[]
 for name in files:
  p=W/name;assert p.suffix in {'.json','.py','.md'},p
  blob=subprocess.run(['git','show',f'{commit}:{name}'],cwd=W,capture_output=True,check=True).stdout
  assert p.read_bytes()==blob,('source changed',p)
  dest=R/name;dest.parent.mkdir(parents=True,exist_ok=True)
  if dest.exists():assert dest.read_bytes()==blob
  else:dest.write_bytes(blob)
  adopted.append(ref(dest))
 sources.append({'source_commit':commit,'source_package':str(src),'adopted_files':adopted,'source_adopted_byte_exact':True})
 for p in sorted((R/rel/'decisions').glob('*.json')):
  d=load(p);b=d['bindings'];N=d['actual_counts_and_window']['gencase_total_particles'];nf=d['actual_counts_and_window']['gencase_fluid_particles']
  assert d['family_id']=='F1' and d['status']=='visual-approved-by-delegated-agent'
  assert d['physical_case_id'] not in ids and d['case_id'] not in runtimeids and d['physical_condition_sha256'] not in hashes
  assert d['reviewer']['agent']=='/root/production_recovery'
  assert d['review_method']['contact_sheets_reviewed']==17 and d['review_method']['fullsize_keyframes_reviewed']==[0,65,115,400]
  evidence={k:receipt(b[k]['execution_receipt']['path']) for k in ['gencase','native_solver','native_frame0_qa','typed_nvme','normal_xmf','render']}
  owner=load(b['canonical_owner']['path']);assert sha(b['canonical_owner']['path'])==b['canonical_owner']['sha256']
  assert owner['physical_case_id']==d['physical_case_id'] and owner['physical_condition_sha256']==d['physical_condition_sha256']
  prep=load(b['gencase']['prepared_input_report']);assert prep['actual_total_particles']==N and prep['actual_generated_constants']['data2d']['value']=='false'
  assert prep['generated_xml_particle_counts']['fluid']==nf
  assert sha(b['source_definition']['path'])==prep['definition_sha256']==b['source_definition']['sha256_from_actual_prepared_report']
  assert sha(b['gencase']['generated_xml'])==prep['xml_sha256']
  qa=load(b['native_frame0_qa']['audit_report']);q=[q for q in qa['cases'] if q['case_id']==d['case_id']];assert len(q)==1;q=q[0]
  assert q['passed'] and q['native_particles']==N and q['native_fluid_particles']==nf and q['finite_row_count']==N and q['unique_identity_count']==N
  assert q['expected_fluid_velocity_m_per_s']==d['physical_scope']['initial_velocity_m_per_s'] and q['max_abs_fluid_velocity_error_m_s']<=q['velocity_tolerance_m_s']
  assert all(x>1 for x in q['fluid_unique_coordinate_levels'].values())
  conv=load(b['typed_nvme']['conversion_report']);assert conv['conversion_status']=='completed' and conv['frames']==401 and conv['particles']==N and conv['partvtk_validation']['all_passed'] and conv['solver_dimension']['solver_dimension']==3
  assert conv['time_evidence']['first_s']==0 and conv['time_evidence']['last_s']>=4 and conv['time_evidence']['strictly_increasing']
  m=load(b['normal_xmf']['manifest']);assert m['frames']==401 and m['particles']==N and m['physical_case_id']==d['physical_case_id']
  assert m['physical_condition_sha256']==conv['hash_scopes']['physical_condition_sha256']==d['physical_condition_sha256']
  assert sha(b['source_plan']['path'])==m['source_plan_sha256']==b['source_plan']['sha256_from_actual_xmf_manifest']
  assert m['source_h5_sha256']==conv['output_sha256']
  grids=ET.parse(b['normal_xmf']['case_xmf']).getroot().findall('.//Grid[@GridType="Uniform"]');assert len(grids)==401
  for g in grids:
   geom=g.find('Geometry/DataItem');assert geom is not None and geom.get('Dimensions')==f'{N} 3'
   vel=g.find('Attribute[@Name="velocity"]/DataItem');assert vel is not None and vel.get('Dimensions')==f'{N} 3'
  a=load(b['render']['animation_report']);assert a['frames']==a['source_frames']==401 and a['all_frames_rendered'] and a['actual_times_preserved_exactly'] and a['native_identity_axis_preserved'] and a['nonfinite_active_states']==0
  assert a['manifest_sha256']==sha(b['normal_xmf']['manifest']) and a['source_h5_sha256']==conv['output_sha256']
  assert a['xdmf_sha256_before']==a['xdmf_sha256_after']==sha(b['normal_xmf']['case_xmf'])
  frames=a['frame_diagnostics'];assert len(frames)==401 and frames[0]['actual_time_s']==0 and frames[-1]['actual_time_s']>=4
  for i,f in enumerate(frames):
   assert f['frame']==i and f['active']==N and f['missing']==0 and f['finite_positions_active'] and f['identity_axis_preserved']
   assert all(v['finite_active'] and v['nonfinite_active']==0 for v in f['finite_fields'].values())
  pngs=b['render']['contact_sheets']+b['render']['keyframes'];assert len(pngs)==21
  assert [x['page'] for x in b['render']['contact_sheets']]==list(range(17))
  assert [x['frame'] for x in b['render']['keyframes']]==[0,65,115,400]
  for x in pngs:assert Path(x['path']).suffix=='.png' and sha(x['path'])==x['sha256']
  for name,path in [('owner',b['canonical_owner']['path']),('prepared',b['gencase']['prepared_input_report']),('native_qa',b['native_frame0_qa']['audit_report']),('conversion',b['typed_nvme']['conversion_report']),('manifest',b['normal_xmf']['manifest']),('xmf',b['normal_xmf']['case_xmf']),('render_report',b['render']['animation_report'])]: evidence[name]=ref(path)
  target=O/(d['case_id']+'-delegated-visual-decision.json')
  out={**d,'schema':'ds02.stage1.delegated-visual-metadata-integration.v1','at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source_review_commit':commit,'source_review_decision':ref(p),'root_metadata_evidence':evidence,'main_role':'immutable metadata, PNG hash and unique physical case integration','main_personally_viewed_pngs':False,'agent_personally_viewed_all_contacts_and_keys':True,'independent_case_increment':1,'independent_physical_case_count_increment':1,'global_count_update':'metadata integration by Root','previous_count':len(previous)+len(decisions),'resulting_count':len(previous)+len(decisions)+1,'PNG_hash_check_is_not_Root_visual_review':True,'scientific_payload_not_read_or_hashed_by_Root':True,'producer_H5_hash_verified_from_metadata_only':True}
  put(target,out);decisions.append(str(target));ids.add(d['physical_case_id']);hashes.add(d['physical_condition_sha256']);runtimeids.add(d['case_id'])
put(O/'actual-integration-review.json',{'source_adoptions':sources,'previous_count':92,'resulting_count':92+len(decisions),'independent_case_increment':len(decisions),'decisions':decisions,'scientific_payload_not_read_or_hashed_by_main':True,'root_personally_viewed_pngs':False,'precision_status':'视觉检查通过、数值精度未验收'})
print(json.dumps({'decisions':len(decisions),'resulting_count':92+len(decisions),'report':str(O/'actual-integration-review.json')}))
