from pathlib import Path
import json,hashlib,subprocess,datetime,xml.etree.ElementTree as ET,re
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');W=Path('/home/jade/.codex/worktrees/ds-data-02-f3/DualSPHysics');H=R/'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003'
O=H/'root_stage1_f1_original_inventory_delegated089090_exact_adoption_and_metadata_integration_800';O.mkdir(exist_ok=True)
def path(x):return Path(x['path'] if isinstance(x,dict) else x)
def load(x):return json.loads(path(x).read_text())
def sha(x):
 p=path(x);assert p.suffix in {'.json','.py','.md','.xml','.xmf','.png'};return hashlib.sha256(p.read_bytes()).hexdigest()
def ref(x):return {'path':str(path(x)),'sha256':sha(x)}
def checked(x):
 if isinstance(x,dict) and x.get('metadata_sha256'):assert sha(x)==x['metadata_sha256']
 return path(x)
def receipt(x):
 p=checked(x);r=load(p);assert r['status']=='completed' and r.get('returncode')==0;return ref(p)
def put(p,d):path(p).write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
def tuple_for(cid):
 m=re.fullmatch(r'F1_STAGE1_DUAL_H(\d+)_DP\d+(?:_VX(\d+))?',cid)
 return (int(m[1]),int(m[2] or 0)) if m else None
assert not (O/'actual-integration-review.json').exists(),'already adopted'
prev=load(H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_102.json')['accepted_decisions'].copy()
for n in [798,799]:prev+=load(next(H.glob(f'root*_{n}'))/'actual-integration-review.json')['decisions']
assert len(prev)==110;ids={load(p).get('physical_case_id',load(p)['case_id']) for p in prev};hashes={load(p)['physical_condition_sha256'] for p in prev};caseids={load(p)['case_id'] for p in prev};tuples={tuple_for(c) for c in caseids if tuple_for(c)};sources=[];decisions=[]
for n,commit in [(89,'272e9611d80fb0c54bc086b192784a5186693932'),(90,'1855c45d0db0a716460cb4e8a629b92878713b54')]:
 src=next((W/'lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003').glob(f'root_followup_{n:03d}_f1_original_inventory_visual_decisions_v1'));rel=src.relative_to(W)
 files=subprocess.run(['git','ls-tree','-r','--name-only',commit,'--',str(rel)],cwd=W,text=True,capture_output=True,check=True).stdout.splitlines();assert files;adopted=[]
 for name in files:
  sp=W/name;assert sp.suffix in {'.json','.md','.py'};blob=subprocess.run(['git','show',f'{commit}:{name}'],cwd=W,capture_output=True,check=True).stdout;assert sp.read_bytes()==blob;dst=R/name;dst.parent.mkdir(parents=True,exist_ok=True)
  if dst.exists():assert dst.read_bytes()==blob
  else:dst.write_bytes(blob)
  adopted.append(ref(dst))
 sources.append({'source_commit':commit,'source_package':str(src),'adopted_files':adopted,'source_adopted_byte_exact':True})
 for p in sorted((R/rel/'decisions').glob('*.json')):
  d=load(p);cid=d['case_id'];b=d['bindings'];N=d['actual_counts_and_window']['gencase_total_particles'];nf=d['actual_counts_and_window']['gencase_fluid_particles']
  assert d['status']=='visual-approved-by-delegated-agent' and d['reviewer']['agent']=='/root/production_recovery' and d['reviewer']['model']=='gpt-5.6-luna' and d['reviewer']['reasoning_effort']=='max'
  assert cid not in caseids and d['physical_case_id'] not in ids and d['physical_condition_sha256'] not in hashes and tuple_for(cid) not in tuples
  assert d['review_method']['contact_sheets_reviewed']==17 and d['review_method']['fullsize_keyframes_reviewed']==[0,65,115,400]
  ev={k:receipt(b[k]['execution_receipt']) for k in ['gencase','native_solver','native_frame0_qa','typed_nvme','normal_xmf','render']}
  inv=load(checked(b['root781_inventory_entry']));row=next(x for x in inv['cases'] if x['case_id']==cid);assert row['physical_case_id']==d['physical_case_id'] and row['physical_condition_sha256']==d['physical_condition_sha256']
  entry=load(row['request_entry']);ownerref=entry['source']['canonical_owner'];owner=load(ownerref);assert sha(ownerref)==ownerref['sha256']==d['physical_scope_provenance']['canonical_physical_case']['canonical_owner_sha256']
  assert entry['physical_case_id']==d['physical_case_id'] and entry['physical_condition_sha256']==d['physical_condition_sha256'] and owner['physical_condition_sha256']==d['physical_condition_sha256']
  pp=checked(b['gencase']['prepared_input_report']);prep=load(pp);assert prep['actual_total_particles']==N and prep['generated_xml_particle_counts']['fluid']==nf and prep['actual_generated_constants']['data2d']['value']=='false'
  assert sha(b['source_definition'])==b['source_definition']['sha256_from_prepared_report']==prep['definition_sha256']
  generated=pp.parent/(cid+'.xml');assert generated.exists() and sha(generated)==prep['xml_sha256']
  qa=load(checked(b['native_frame0_qa']['audit_report']));q=next(x for x in qa['cases'] if x['case_id']==cid);assert q['passed'] and q['unique_identity_count']==N
  if 'native_particles' in q:
   assert q['native_particles']==N and q['native_fluid_particles']==nf and q['finite_row_count']==N and all(x>1 for x in q['fluid_unique_coordinate_levels'].values())
   assert q['expected_fluid_velocity_m_per_s']==d['physical_scope']['initial_velocity_m_per_s'] and q['max_abs_fluid_velocity_error_m_s']<=q['velocity_tolerance_m_s']
  else:
   assert d['physical_scope']['initial_velocity_m_per_s']==[0,0,0] and q['actual_total_particles']==q['finite_rows']==q['native_rows']==N and q['fluid_rows']==nf and q['unique_coordinate_count']==N and all(x>1 for x in q['fluid_3d_levels']) and q['max_abs_velocity_error_m_per_s']<=1e-6 and q['mass_rescaling'] is False
  tp=checked(b['typed_nvme']['conversion_report']);c=load(tp);assert c['conversion_status']=='completed' and c['frames']==401 and c['particles']==N and c['solver_dimension']['solver_dimension']==3 and c['partvtk_validation']['all_passed']
  assert c['time_evidence']['first_s']==0 and c['time_evidence']['last_s']>=4 and c['time_evidence']['strictly_increasing']
  assert d['physical_scope_provenance']['actual_converter_scope']['physical_condition_sha256']==c['hash_scopes']['physical_condition_sha256']
  mp=checked(b['normal_xmf']['manifest']);m=load(mp);assert m['frames']==401 and m['particles']==N and m['source_h5_sha256']==c['output_sha256']
  if m.get('physical_condition_sha256'):assert m['physical_condition_sha256']==c['hash_scopes']['physical_condition_sha256']
  source_xmf_path=path(b['normal_xmf']['case_xmf_path']);xp=path(m['xdmf']);assert sha(xp)==m['xdmf_sha256'];gs=ET.parse(xp).getroot().findall('.//Grid[@GridType="Uniform"]');assert len(gs)==401 and all(g.find('Geometry/DataItem').get('Dimensions')==g.find('Attribute[@Name="velocity"]/DataItem').get('Dimensions')==f'{N} 3' for g in gs)
  ap=checked(b['render']['animation_report']);a=load(ap);assert a['frames']==a['source_frames']==401 and a['all_frames_rendered'] and a['native_identity_axis_preserved'] and a['actual_times_preserved_exactly'] and a['nonfinite_active_states']==0
  assert a['manifest_sha256']==sha(mp) and a['source_h5_sha256']==c['output_sha256'] and a['xdmf_sha256_before']==a['xdmf_sha256_after']==sha(xp) and path(a['xdmf'])==xp
  fs=a['frame_diagnostics'];assert len(fs)==401 and fs[0]['actual_time_s']==0 and fs[-1]['actual_time_s']>=4
  assert all(f['frame']==i and f['active']==N and f['missing']==0 and f['finite_positions_active'] and f['identity_axis_preserved'] and all(v['finite_active'] and v['nonfinite_active']==0 for v in f['finite_fields'].values()) for i,f in enumerate(fs))
  pngs=b['render']['contact_sheets']+b['render']['keyframes'];assert len(pngs)==21 and [x['page'] for x in b['render']['contact_sheets']]==list(range(17)) and [x['frame'] for x in b['render']['keyframes']]==[0,65,115,400]
  for x in pngs:assert path(x).suffix=='.png' and sha(x)==x['sha256']
  for name,v in [('canonical_owner',ownerref),('original_inventory',b['root781_inventory_entry']),('source_definition',b['source_definition']),('generated_xml',generated),('prepared',pp),('native_qa',b['native_frame0_qa']['audit_report']),('conversion',tp),('xmf_manifest',mp),('xmf',xp),('render_report',ap)]:ev[name]=ref(v)
  out={**d,'schema':'ds02.stage1.delegated-visual-metadata-integration.v1','at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source_review_commit':commit,'source_review_decision':ref(p),'root_metadata_evidence':ev,'actual_converter_scope_sha256':c['hash_scopes']['physical_condition_sha256'],'canonical_and_actual_scopes_kept_separate':True,'source_reported_case_xmf_path_preserved':str(source_xmf_path),'actual_consumed_XMF_manifest_and_render_binding':ref(xp),'source_case_xmf_path_matches_actual':source_xmf_path==xp,'source_path_claim_repaired_only_in_new_metadata_sidecar':source_xmf_path!=xp,'main_personally_viewed_pngs':False,'agent_personally_viewed_all_contacts_and_keys':True,'main_role':'canonical physical tuple, actual metadata lineage and PNG hashes only','independent_case_increment':1,'independent_physical_case_count_increment':1,'global_count_update':'Root metadata integration','previous_count':110+len(decisions),'resulting_count':111+len(decisions),'physical_tuple_duplicate_check':{'mechanism':'DUAL unchanged mother geometry','head_mm':tuple_for(cid)[0],'vx_code':tuple_for(cid)[1],'not_present_in_previous_case_tuples':True},'scientific_payload_not_read_or_hashed_by_main':True,'producer_H5_hash_verified_from_metadata_only':True}
  dp=O/(cid+'-delegated-visual-decision.json');put(dp,out);decisions.append(str(dp));ids.add(d['physical_case_id']);hashes.add(d['physical_condition_sha256']);caseids.add(cid);tuples.add(tuple_for(cid))
put(O/'actual-integration-review.json',{'source_adoptions':sources,'previous_count':110,'resulting_count':110+len(decisions),'independent_case_increment':len(decisions),'decisions':decisions,'root_personally_viewed_PNGs':False,'canonical_vs_legacy_scopes_kept_separate':True,'science_payload_not_read_or_hashed':True});print(json.dumps({'new_cases':len(decisions),'resulting_count':110+len(decisions)}))
