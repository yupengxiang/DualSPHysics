from pathlib import Path
import json,hashlib,subprocess,datetime,xml.etree.ElementTree as ET
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');H=R/'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003'
W=Path('/home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics')
O=H/'root_stage1_f4_delegated_visual110_exact_adoption_and_metadata_integration_789';O.mkdir(exist_ok=True)
def load(p):return json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix in {'.json','.md','.py','.xml','.xmf','.png'};return hashlib.sha256(p.read_bytes()).hexdigest()
def ref(p):return {'path':str(p),'sha256':sha(p)}
def put(p,d):Path(p).write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
assert not (O/'actual-integration-review.json').exists(),'already adopted'
commit=subprocess.run(['git','rev-parse','0c87f1b7'],cwd=W,capture_output=True,text=True,check=True).stdout.strip()
src=next((W/'lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003').glob('root_followup_110_*'));rel=src.relative_to(W)
files=subprocess.run(['git','ls-tree','-r','--name-only',commit,'--',str(rel)],cwd=W,capture_output=True,text=True,check=True).stdout.splitlines();assert files
adopted=[]
for name in files:
 p=W/name;assert p.suffix in {'.json','.md','.py'}
 blob=subprocess.run(['git','show',f'{commit}:{name}'],cwd=W,capture_output=True,check=True).stdout;assert p.read_bytes()==blob
 dst=R/name;dst.parent.mkdir(parents=True,exist_ok=True)
 if dst.exists():assert dst.read_bytes()==blob
 else:dst.write_bytes(blob)
 adopted.append(ref(dst))
P=R/rel;ip=P/'metadata/review-index.json';idx=load(ip);assert idx['reviewer']=='/root/f6_endpoint_initial_qa'
cp=load(H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_100.json');prev=cp['accepted_decisions']
for n,name in [(780,'actual-first2-integration-review.json'),(784,'actual-integration-review.json'),(788,'actual-integration-review.json')]:prev+=load(next(H.glob(f'root*_{n}'))/name)['decisions']
assert len(prev)==100
ids={load(p).get('physical_case_id',load(p)['case_id']) for p in prev};hashes={load(p)['physical_condition_sha256'] for p in prev};decisions=[]
for row in idx['cases']:
 cid=row['case_id'];assert cid not in ids and row['physical_condition_sha256'] not in hashes and row['status']=='visual-approved-by-delegated-agent'
 cl=P/'metadata'/Path(row['metadata_closure_path']).name;c=load(cl);vr=c['visual_review']
 assert c['case_id']==cid and vr['reviewer']==idx['reviewer'] and vr['status']==row['status'] and vr['all_contact_sheets_and_keys_viewed'] and vr['view_method']=='view_image'
 evidence={}
 for k in ['gencase','initial_metadata_qa','full_native','native_frame0_qa','typed_conversion','normal_xmf','render']:
  rp=c[k]['receipt']['path'];r=load(rp);assert r['status']=='completed' and r['returncode']==0 and r['request']['case_id']==cid;evidence[k]=ref(rp)
 prep=load(c['gencase']['prepared_input_report_path']);assert prep['actual_total_particles']==83233 and prep['actual_generated_constants']['data2d']['value']=='false'
 qa=load(c['native_frame0_qa']['report_path']);q=next(q for q in qa['cases'] if q['case_id']==cid);assert q['pass'] and q['actual_total_particles']==83233 and q['actual_particle_counts']=={'fixed':24161,'moving':0,'floating':0,'fluid':59072}
 t=load(c['typed_conversion']['report_path']);assert t['conversion_status']=='completed' and t['frames']==1201 and t['particles']==83233 and t['solver_dimension']['solver_dimension']==3 and t['partvtk_validation']['all_passed']
 assert sha(c['typed_conversion']['report_path'])==c['typed_conversion']['report_sha256'] and t['hash_scopes']['physical_condition_sha256']==row['physical_condition_sha256']
 assert t['time_evidence']['first_s']==0 and t['time_evidence']['last_s']>=1.2 and t['time_evidence']['strictly_increasing']
 m=load(c['normal_xmf']['manifest_path']);assert m['frames']==1201 and m['particles']==83233 and m['physical_condition_sha256']==row['physical_condition_sha256'] and m['source_h5_sha256']==t['output_sha256']
 xf=m['xdmf'];assert sha(xf)==m['xdmf_sha256']
 grids=ET.parse(xf).getroot().findall('.//Grid[@GridType="Uniform"]');assert len(grids)==1201
 assert all(g.find('Geometry/DataItem').get('Dimensions')==g.find('Attribute[@Name="velocity"]/DataItem').get('Dimensions')=='83233 3' for g in grids)
 a=load(c['render']['report_path']);assert sha(c['render']['report_path'])==c['render']['report_sha256'] and a['frames']==a['source_frames']==1201 and a['all_frames_rendered'] and a['actual_times_preserved_exactly'] and a['native_identity_axis_preserved'] and a['nonfinite_active_states']==0
 assert a['manifest_sha256']==sha(c['normal_xmf']['manifest_path']) and a['source_h5_sha256']==t['output_sha256'] and a['xdmf_sha256_before']==a['xdmf_sha256_after']==sha(xf)
 fs=t['lifecycle']['frame_summary'];assert len(fs)==1201 and t['lifecycle']['introduced_ids']=='rejected' and t['lifecycle']['contract']=='closed fixed identity axis'
 maximum_missing=max(f['missing_particles'] for f in fs);assert maximum_missing in [0,6],'new lifecycle discrepancy needs explicit review'
 ads=a['frame_diagnostics'];assert len(ads)==1201
 assert all(f['finite_positions_active'] and f['identity_axis_preserved'] and all(v['finite_active'] and v['nonfinite_active']==0 for v in f['finite_fields'].values()) for f in ads)
 png=row['png_hashes'];assert png['computed_after_view_image'] and len(png['contact_sheets'])==51 and len(png['key_frames'])==9
 assert [x['path'] for x in png['contact_sheets']]==row['contact_sheet_paths'] and [x['path'] for x in png['key_frames']]==row['key_frame_paths']
 for x in png['contact_sheets']+png['key_frames']:assert Path(x['path']).suffix=='.png' and sha(x['path'])==x['sha256']
 for k,path in [('prepared',c['gencase']['prepared_input_report_path']),('native_qa',c['native_frame0_qa']['report_path']),('typed_report',c['typed_conversion']['report_path']),('xmf_manifest',c['normal_xmf']['manifest_path']),('xmf',xf),('render_report',c['render']['report_path'])]:evidence[k]=ref(path)
 decision={'schema':'ds02.stage1.delegated-visual-metadata-integration.v1','at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'status':row['status'],'family_id':'F4','case_id':cid,'physical_case_id':cid,'physical_condition_sha256':row['physical_condition_sha256'],'source_review_commit':commit,'source_review_index':ref(ip),'source_metadata_closure':ref(cl),'source_scope_separation':c['source_scope_separation'],'actual_completed_metadata_evidence':evidence,'visual_reviewer':idx['reviewer'],'main_personally_viewed_pngs':False,'agent_personally_viewed_all_contacts_and_keys':True,'agent_observations':vr['observations'],'agent_limitations':vr['limitations'],'verified_PNG_hashes':png,'actual_frames':1201,'actual_particles':83233,'actual_fluid_particles':59072,'actual_last_time_s':t['time_evidence']['last_s'],'maximum_missing_particles':maximum_missing,'final_missing_UIDs':fs[-1]['missing_id_first'],'first_missing_frame_by_type':t['lifecycle']['first_missing_frame_by_type'],'lifecycle_limitation':'Six late fluid exclusions, cause unknown and preserved unfilled; no visually missing bulk reported' if maximum_missing else 'No native UID exclusions observed','scientific_payload_not_read_or_hashed_by_main':True,'producer_h5_hash_verified_from_metadata_only':True,'precision_status':'视觉检查通过、数值精度未验收','q_n':'not_granted','q_e':'not_assessed','independent_case_increment':1,'previous_count':100+len(decisions),'resulting_count':101+len(decisions)}
 dp=O/(cid+'-delegated-visual-decision.json');put(dp,decision);decisions.append(str(dp));ids.add(cid);hashes.add(row['physical_condition_sha256'])
put(O/'actual-integration-review.json',{'source_commit':commit,'source_adopted_byte_exact':True,'adopted_files':adopted,'previous_count':100,'resulting_count':100+len(decisions),'independent_case_increment':len(decisions),'decisions':decisions,'root_only_metadata_integration':True,'late_six_UID_exclusions_retained_no_invented_cause_or_repair':True})
print(json.dumps({'resulting_count':100+len(decisions),'new_cases':len(decisions)}))
