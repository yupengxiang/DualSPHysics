from pathlib import Path
import json,hashlib,datetime,xml.etree.ElementTree as ET
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');H=R/'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
def load(p):return json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix in {'.json','.xmf','.xml','.md','.py'};return hashlib.sha256(p.read_bytes()).hexdigest()
def ref(p):return {'path':str(p),'sha256':sha(p)}
def root(n):return next(H.glob(f'root*_{n}'))
def completed(p):
 r=load(p);assert r['status']=='completed' and r.get('returncode')==0,(p,r.get('status'),r.get('returncode'));return ref(p)
def xmlshape(p,frames,N):
 gs=ET.parse(p).getroot().findall('.//Grid[@GridType="Uniform"]');assert len(gs)==frames
 assert all(g.find('Geometry/DataItem').get('Dimensions')==g.find('Attribute[@Name="velocity"]/DataItem').get('Dimensions')==f'{N} 3' for g in gs)
def checkrender(p,frames,N):
 r=load(p);assert r['frames']==r['source_frames']==frames and r['all_frames_rendered'] and r['actual_times_preserved_exactly'] and r['native_identity_axis_preserved'] and r['nonfinite_active_states']==0
 assert len(r['frame_diagnostics'])==frames
 assert all(f['finite_positions_active'] and f['identity_axis_preserved'] and all(v['finite_active'] for v in f['finite_fields'].values()) for f in r['frame_diagnostics'])
 return r
O=H/'root_stage1_F2_actual16_and_F7_actual48_existing_pipeline_frontier_correction_792';O.mkdir(exist_ok=True);assert not (O/'actual-frontier-correction.json').exists()
accepted=load(H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_101.json')['accepted_decisions'];used={load(p).get('physical_case_id',load(p)['case_id']) for p in accepted}|{load(p)['case_id'] for p in accepted};f2=[];f7=[]
for qp in sorted(root(434).glob('*typed-request.json')):
 q=load(qp);cid=q['case_id'];renderqp=root(462)/(cid+'-render-request.json');rq=load(renderqp);ar=D/'families/F2'/cid/rq['attempt_id'];rp=ar/'execution-receipt.json';reportp=ar/'render/paraview-full-animation-report.json'
 ev={'gencase':completed(q['gencase_receipt']),'initial_qa':completed(q['initial_qa_execution_receipt']),'native':completed(q['native_receipt']),'typed':completed(q['typed_receipt']),'render':completed(rp)}
 tp=Path(q['conversion_report']);t=load(tp);assert t['conversion_status']=='completed' and t['frames']==401 and t['particles']==q['expected_particles'] and t['solver_dimension']['solver_dimension']==3 and t['partvtk_validation']['all_passed']
 assert t['time_evidence']['first_s']==0 and t['time_evidence']['last_s']>=4 and t['time_evidence']['strictly_increasing']
 mp=Path(rq['xmf_manifest']);m=load(mp);assert m['frames']==401 and m['particles']==t['particles'] and m['source_h5_sha256']==t['output_sha256']
 xp=Path(m['xdmf']);assert sha(xp)==m['xdmf_sha256'];xmlshape(xp,401,t['particles']);xrp=D/'families/F2'/cid/rq['xmf_attempt']/'execution-receipt.json';ev['xmf']=completed(xrp)
 rr=checkrender(reportp,401,t['particles']);assert rr['manifest_sha256']==sha(mp) and rr['source_h5_sha256']==t['output_sha256']
 f2.append({'case_id':cid,'physical_case_id':rq['physical_case_id'],'canonical_physical_condition_sha256':rq['physical_condition_sha256'],'actual_converter_physical_condition_sha256':t['hash_scopes']['physical_condition_sha256'],'canonical_and_actual_scope_kept_separate':True,'frames':401,'particles':t['particles'],'actual_last_time_s':t['time_evidence']['last_s'],'actual_completed_receipts':ev,'typed_report':ref(tp),'xmf_manifest':ref(mp),'render_report':ref(reportp),'render_request':ref(renderqp),'already_accepted':cid in used or rq['physical_case_id'] in used,'next_action':'delegated full-window PNG visual review; do not rerun completed native/typed pipeline','independent_case_increment':0})
assert len(f2)==16
idxp=R/'lagrangian-fluid-lab/campaigns/ds-data-02/families/F7/handoff_20261003/root_followup_080_actual_48_readiness_view_index_v1/metadata/family48-readiness-index.json';idx=load(idxp);requests={}
for qp in root(413).glob('*render-request.json'):
 q=load(qp);requests[q['case_id']]=(qp,q)
assert len(requests)==24
for row in idx['cases']:
 cid=row['case_id'];st=row['stages'];ev={}
 for k in ['gencase','native_full601','typed_full601','xmf_full601']:ev[k]=completed(st[k]['receipt']['path'])
 if st['native_initial_qa']['receipt']['path']:ev['native_initial_qa']=completed(st['native_initial_qa']['receipt']['path'])
 else:assert cid=='F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_BASE_V1' and cid in used
 if cid in requests:
  qp,q=requests[cid];ar=D/'families/F7'/cid/q['attempt_id'];rp=ar/'execution-receipt.json';reportp=ar/'render/paraview-full-animation-report.json';mp=Path(q['render_manifest']);render_request=ref(qp)
 else:
  rp=Path(st['render_full601']['receipt']['path']);reportp=Path(st['render_full601']['report']['path']);render_request=row.get('render_request');mp=None
 ev['render_full601']=completed(rp)
 # Historical mother is an already accepted product with an earlier renderer schema.
 if cid=='F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_BASE_V1':
  f7.append({'case_id':cid,'historical_mother_already_accepted':True,'actual_completed_receipts':ev,'independent_case_increment':0});continue
 t=load(st['typed_full601']['report']['path']);assert t['conversion_status']=='completed' and t['frames']==601 and t['particles']==70179 and t['solver_dimension']['solver_dimension']==3 and t['partvtk_validation']['all_passed']
 assert t['time_evidence']['first_s']==0 and t['time_evidence']['last_s']>=12 and t['time_evidence']['strictly_increasing']
 rr=checkrender(reportp,601,70179)
 if mp is None:mp=Path(rr['input_manifest'])
 m=load(mp);assert m['frames']==601 and m['particles']==70179 and m['source_h5_sha256']==t['output_sha256'] and rr['manifest_sha256']==sha(mp)
 xp=Path(m['xdmf']);assert sha(xp)==m['xdmf_sha256'];xmlshape(xp,601,70179)
 f7.append({'case_id':cid,'physical_case_id':row.get('physical_case_id',cid),'actual_completed_receipts':ev,'typed_report':ref(st['typed_full601']['report']['path']),'xmf_manifest':ref(mp),'render_report':ref(reportp),'render_request':render_request,'frames':601,'particles':70179,'actual_last_time_s':t['time_evidence']['last_s'],'canonical_and_legacy_scopes_kept_separate':True,'actual_converter_physical_condition_sha256':t['hash_scopes']['physical_condition_sha256'],'already_accepted':cid in used,'source080_old_render_status_not_authoritative':True,'independent_case_increment':0,'next_action':'delegated full-window PNG review; no duplicate native solve'})
assert len(f7)==48 and len({r['case_id'] for r in f7})==48
out={'schema':'ds02.actual.pipeline-frontier-correction.v1','at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'F2_actual16_complete_pipeline_cases':f2,'F7_actual48_complete_pipeline_cases':f7,'F2_unaccepted_expansion_visual_frontier':sum(not x['already_accepted'] for x in f2),'F7_unaccepted_visual_frontier':sum(not x.get('already_accepted',x.get('historical_mother_already_accepted',False)) for x in f7),'old_source082_F2_owner_digest_blocker_is_historical':True,'F7_source080_16_unregistered_render_rows_corrected_by_actual413_414_receipts':True,'historical_source_packages_preserved':True,'science_payload_read_or_hashed':False,'jobs_started':0,'independent_case_increment':0,'main_personally_viewed_PNGs':False,'accepted_count_unchanged_by_frontier':True}
(O/'actual-frontier-correction.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'F2_complete':len(f2),'F7_complete':len(f7),'F2_unaccepted_expansion_visual_frontier':out['F2_unaccepted_expansion_visual_frontier'],'F7_unaccepted_visual_frontier':out['F7_unaccepted_visual_frontier']}))
