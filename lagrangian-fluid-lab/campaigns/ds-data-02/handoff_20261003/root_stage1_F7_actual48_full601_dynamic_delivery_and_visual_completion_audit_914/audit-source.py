from pathlib import Path
import json,hashlib,datetime,xml.etree.ElementTree as ET
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');H=R/'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003';O=H/'root_stage1_F7_actual48_full601_dynamic_delivery_and_visual_completion_audit_914';O.mkdir(exist_ok=True)
load=lambda p:json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix.lower() in {'.json','.py','.md','.xml','.xmf','.png'};return hashlib.sha256(p.read_bytes()).hexdigest()
def ref(p):return {'path':str(p),'sha256':sha(p)}
cp=load(H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_119.json');accepted={}
fresh=load(next(H.glob('root*_913'))/'actual-integration-review.json')['decisions']
for p in cp['accepted_decisions']+fresh:
 d=load(p)
 if d['family_id']=='F7':accepted[d.get('physical_case_id',d['case_id'])]=(p,d)
assert len(accepted)==48
stockp=next(H.glob('root*_792'))/'actual-frontier-correction.json';stock=load(stockp)['F7_actual48_complete_pipeline_cases'];assert len(stock)==48;seen=set();digests=set();angles=set();cases=[]
for row in stock:
 cid=row['case_id'];assert cid not in seen;seen.add(cid);ev={}
 for stage,x in row['actual_completed_receipts'].items():
  assert sha(x['path'])==x['sha256'];r=load(x['path']);assert (r['status'],r.get('returncode'))==('completed',0);ev[stage]=ref(x['path'])
 if row.get('historical_mother_already_accepted'):
  dp,d=accepted[cid];b=d['bindings'];tp=b['conversion_report'];mp=b['dynamic_xdmf_manifest'];ap=b['animation_integrity_report']
 else:tp=row['typed_report'];mp=row['xmf_manifest'];ap=row['render_report']
 for x in [tp,mp,ap]:assert sha(x['path'])==x['sha256']
 t,m,a=[load(x['path']) for x in [tp,mp,ap]];scope=t['hash_scopes']['physical_condition'];digest=hashlib.sha256(json.dumps(scope,sort_keys=True,separators=(',',':')).encode()).hexdigest();assert digest==t['hash_scopes']['physical_condition_sha256']==m['physical_condition_sha256'] and digest not in digests;digests.add(digest)
 assert t['conversion_status']=='completed' and t['frames']==601 and t['particles']==70179 and t['solver_dimension']['solver_dimension']==3 and t['partvtk_validation']['all_passed'];assert t['time_evidence']['first_s']==0 and t['time_evidence']['last_s']>=12 and t['time_evidence']['strictly_increasing']
 xf=Path(m['xdmf']);assert sha(xf)==m['xdmf_sha256'];gs=ET.parse(xf).getroot().findall('.//Grid[@GridType="Uniform"]');assert len(gs)==601 and all(g.find('Geometry/DataItem').get('Dimensions')==g.find('Attribute[@Name="velocity"]/DataItem').get('Dimensions')=='70179 3' for g in gs)
 assert m['frames']==601 and m['particles']==70179 and m['source_h5_sha256']==t['output_sha256'];assert a['frames']==a['source_frames']==601 and a['all_frames_rendered'] and a['actual_times_preserved_exactly'] and a['native_identity_axis_preserved'] and a['nonfinite_active_states']==0 and a['manifest_sha256']==sha(mp['path']) and a['xdmf_sha256_before']==a['xdmf_sha256_after']==sha(xf) and a['source_h5_sha256']==t['output_sha256']
 fs=a['frame_diagnostics'];assert len(fs)==601 and all(f['active']==70179 and f['missing']==0 and f['finite_positions_active'] and f['identity_axis_preserved'] and all(v['finite_active'] and v['nonfinite_active']==0 for v in f['finite_fields'].values()) for f in fs)
 angle=scope['parameters']['amplitude_deg'];assert angle not in angles;angles.add(angle)
 v=None
 if cid in accepted:
  dp,d=accepted[cid];assert d['physical_condition_sha256']==digest;v=ref(dp)
 contacts=a['outputs']['contact_sheets'];assert len(contacts)==26 and all(Path(p).is_file() for p in contacts)
 cases.append({'case_id':cid,'physical_condition_sha256':digest,'amplitude_deg':angle,'visual_accepted':v is not None,'visual_decision':v,'precision_status':'视觉检查通过、数值精度未验收' if v else 'visual-review-pending; numerical precision unqualified','actual_completed_receipts':ev,'typed_report':tp,'xmf_manifest':mp,'render_report':ap,'paraview_open_file':ref(xf),'typed_trajectory':{'path':t['output_hdf5'],'sha256_from_producer':t['output_sha256'],'main_did_not_read_or_hash_payload':True},'full_animation_preview':a['outputs'].get('gif'),'paraview_state':a['outputs'].get('pvsm'),'contact_sheets':contacts,'frames':601,'particles':70179,'fluid_particles':40700,'last_time_s':t['time_evidence']['last_s'],'canonical_scope_recomputed_from_metadata_only':True,'native_motion_interpolation':'piecewise-linear; no native C2 claim'})
assert seen==set(x['case_id'] for x in stock) and set(accepted)<=seen
out={'schema':'ds02.f7.dynamic-delivery-and-visual-completion-audit.v1','at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'checkpoint':ref(H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_119.json'),'stock_source':ref(stockp),'new_visual_review_adoption':ref(next(H.glob('root*_913'))/'actual-integration-review.json'),'global_goal_complete':False,'global_case_total_after_adoption':195,'actual_complete_scientific_pipeline_cases':48,'visual_accepted_cases':48,'visual_pending_cases':[c['case_id'] for c in cases if not c['visual_accepted']],'family_stage1_complete':True,'case_increment':0,'unique_ids_and_canonical_binding_hashes':48,'distinct_target_amplitudes_deg':sorted(angles),'45_degree_mother_reused_without_duplicate':True,'native_payloads_read_copied_or_hashed_by_main':False,'strict_containment_and_individual_exit_routes_unqualified':True,'numerical_precision_not_granted':True,'cases':cases}
(O/'actual-delivery-and-completion-audit.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n');(O/'audit-source.py').write_bytes(Path(__file__).read_bytes());print(json.dumps({k:out[k] for k in ['actual_complete_scientific_pipeline_cases','visual_accepted_cases','visual_pending_cases','unique_ids_and_canonical_binding_hashes']}))
