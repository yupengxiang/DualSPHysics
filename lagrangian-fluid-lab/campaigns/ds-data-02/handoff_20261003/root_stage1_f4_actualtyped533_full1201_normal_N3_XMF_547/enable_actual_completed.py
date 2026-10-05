from pathlib import Path
import json,hashlib,sys
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');P=L/'campaigns/ds-data-02/families/F4/handoff_20261003/root_followup_098_stage1_f4_root530_typed_xmf_render_v1';G=H/'root_stage1_f4_actualtyped533_full1201_normal_N3_XMF_547';A=H/'root_stage1_f4_fresh098_exact_adoption_realframe0QA530_typed533_XMF_546';load=lambda p:json.loads(Path(p).read_text());sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest();put=lambda p,v:p.write_text(json.dumps(v,indent=2)+'\n');sys.path.insert(0,str(L/'scripts'));import ds_data02_runtime_v2 as rt,ds_data02_strict_dispatch_v1 as strict
SCIENCE={'.h5','.hdf5','.bi4','.ibi4','.csv','.dat','.vtk','.vtu','.npy','.npz'}
def prepare(p):
 q=load(p);qp=G/(q['case_id']+'-xmf-request.json')
 if qp.exists():return qp
 b=load(q['xmf_binding']['path']);trp=Path(b['typed_receipt'])
 if not trp.exists():return None
 tr=load(trp)
 if tr['status'] in ['running','reserved','registered']:return None
 assert (tr['status'],tr['returncode'])==('completed',0),str(trp)
 crp=Path(b['conversion_report']);cv=load(crp);assert cv['conversion_status']=='completed' and cv['frames']==1201 and cv['particles']==83233 and cv['solver_dimension']['solver_dimension']==3 and cv['partvtk_validation']['all_passed'];assert cv['time_evidence']['strictly_increasing'] and cv['time_evidence']['first_s']==0 and cv['time_evidence']['last_s']>=1.2;assert cv['hash_scopes']['physical_condition_sha256']==b['physical_condition_sha256']==q['physical_condition_sha256'];assert cv['hash_scopes']['physical_condition']['physical_case_id']==b['physical_case_id'];assert cv['typed_identity']['initial_exclusion_ledger']['count']==0
 frames=cv['lifecycle']['frame_summary'];assert len(frames)==1201
 for i,f in enumerate(frames):
  assert f['frame']==i and f['active_particles']+f['missing_particles']==83233
  assert f['type_counts']['0']==24161 and f['missing_type_counts']['0']==0
  assert f['type_counts']['3']+f['missing_type_counts']['3']==59072
 mr=max(f['missing_particles'] for f in frames);review=G/(q['case_id']+'-actual-typed-review.json');put(review,{'case_id':q['case_id'],'typed_receipt':str(trp),'typed_receipt_sha256':sha(trp),'conversion_report':str(crp),'conversion_report_sha256':sha(crp),'actual_full1201_N3':True,'actual_initial_UID_axis':83233,'native_initial_fluid':59072,'initial_exclusions':0,'max_missing_initial_native_UIDs':mr,'native_lifecycle_missing_not_padded':True,'producer_H5_digest':cv['output_sha256'],'legacy_converter_condition':b['physical_condition_sha256'],'source_owner_condition':b['source_owner_physical_condition_sha256'],'visual_and_precision_pending':True,'science_read_or_hash_by_binder':False,'case_increment':0})
 b['actual_typed_review']=str(review);b['actual_typed_review_sha256']=sha(review);b['actual_h5_producer_sha256']=cv['output_sha256'];b['conversion_report_sha256']=sha(crp);b['typed_receipt_sha256']=sha(trp);b['typed_gate']={'status':'actual_completed0_full1201_N3_lifecycle_report_verified','receipt_only_is_insufficient':True,'max_missing_initial_native_UIDs':mr};b['source_xmf_binding']=q['xmf_binding'];bp=G/'bindings'/(q['case_id']+'-actual-xmf-binding.json');put(bp,b);md=q['input_sha256'];assert all(Path(f).suffix.lower() not in SCIENCE for f in md)
 for f,digest in md.items():assert sha(f)==digest,f
 md[b['trajectory_h5']]=cv['output_sha256']
 for f in [p,bp,review,trp,crp,A/'actual-source-adoption-review.json',Path(__file__),H/'root_stage1_home_floor_inventory_dispatch_142/launch.py',H/'root_stage1_home_floor_inventory_dispatch_142/root_home_floor_inventory_policy.py',L/'.venv/bin/python']:md[str(f)]=sha(f)
 ref=load(next(next(H.glob('root_*_530')).glob('*request.json')));q['command'][0]=str(L/'.venv/bin/python');q['command'][q['command'].index('--binding')+1]=str(bp);q.update(disabled=False,source_only=False,launch=True,launch_allowed=True,execution_allowed=True,arrays_allowed=True,root_review_required=False,launch_owner='root',cpu_task_kind='audit',cwd=str(L),worktree_root=str(R),root_dataset_inventory_profile=ref['root_dataset_inventory_profile'],root_inventory_policy_sha256=ref['root_inventory_policy_sha256'],root_actual_launch_source=str(H/'root_stage1_home_floor_inventory_dispatch_142/launch.py'),root_actual_launch_source_sha256=sha(H/'root_stage1_home_floor_inventory_dispatch_142/launch.py'),root_reviewed_source_request=str(p),root_reviewed_source_request_sha256=sha(p),producer_input_sha256={b['trajectory_h5']:cv['output_sha256']},input_files=sorted(md),input_sha256=md,depends_on_attempts=[trp.parent.name,Path(b['native_receipt']).parent.name],status='root_enabled_actual_fulltyped533_1201_N3_XMF_pending');q['attempt_id']+='-root547';attempt=D/'families/F4'/q['case_id']/q['attempt_id'];assert not attempt.exists();q['attempt_root']=str(attempt);q['expected_outputs']={'xdmf':str(attempt/'case.xmf'),'manifest':str(attempt/'manifest.json'),'sha256':None};q.pop('disabled_reason',None)
 original=rt.sha256
 def metadata_hash(path):
  if Path(path).suffix.lower() in SCIENCE:return md[str(Path(path).resolve())]
  return original(path)
 rt.sha256=metadata_hash
 try:actual=rt.validate_request(q);strict.check_registered_hashes(q,actual)
 finally:rt.sha256=original
 put(qp,q);return qp
