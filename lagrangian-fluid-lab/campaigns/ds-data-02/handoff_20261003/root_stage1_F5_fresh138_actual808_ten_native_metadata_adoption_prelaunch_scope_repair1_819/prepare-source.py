from pathlib import Path
import json,hashlib,shutil,subprocess,ast
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');W=Path('/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics');S=W/'lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_138_stage1_f5_remaining10_full801_downstream_disabled_v1';A=L/'campaigns/ds-data-02/families/F5/handoff_20261003'/S.name;O=H/'root_stage1_F5_fresh138_actual808_ten_native_metadata_adoption_prelaunch_scope_repair1_819';B=H/'root_stage1_F5_actual808_ten_full801_typed_registered_shared_serial_CPU2_scope_repair1_820';load=lambda p:json.loads(Path(p).read_text());SCI={'.h5','.hdf5','.bi4','.ibi4','.csv','.dat','.vtk','.vtu','.npy','.npz'}
def sha(p):
 p=Path(p);assert p.suffix.lower() not in SCI;return hashlib.sha256(p.read_bytes()).hexdigest()
def put(p,v):Path(p).write_text(json.dumps(v,indent=2)+'\n')
assert not O.exists() and A.exists() and not B.exists();O.mkdir();B.mkdir();(B/'owners').mkdir();(B/'requests').mkdir()
commit='94761db5beb441645051fbfe6093318f953adaf1';tracked=subprocess.check_output(['git','ls-tree','-r','--name-only',commit,'--',str(S.relative_to(W))],cwd=W,text=True).splitlines();assert tracked
files=[]
for f in tracked:
 sp=W/f;assert sp.suffix.lower() in {'.json','.py','.md'};dst=A/sp.relative_to(S);dst.parent.mkdir(parents=True,exist_ok=True);assert dst.is_file() and sha(sp)==sha(dst);files.append({'source':str(sp),'adopted':str(dst),'sha256':sha(dst)})
base=load(H/'root_stage1_f2_first48_remaining24_registered_source_generation_801/registered-source-generation-request.json');profile={k:v for k,v in base.items() if k.startswith('root_') or k=='resource_window'};rows=[];keys=('family_id','physical_case_id','lineage_group_id','paired_background_id','mechanism_id','geometry_family_id','geometry','control_family_id','gravity_m_s2','density_kg_m3','parameters','initial_state','continuum_geometry')
for sp in sorted(S.glob('requests/*-full801-typed-nvme-request.json')):
 q=load(sp);tag=q['tag'];assert 'T120' not in tag and q['expected_frames']==801;bp=Path(q['binding']);b=load(bp);ng=b['native_dependency'];gp=b['actual_gencase'];iq=b['actual_initial_qa']
 for dep in [ng,gp,iq]:
  assert sha(dep['receipt'])==dep['receipt_sha256'];r=load(dep['receipt']);assert (r['status'],r['returncode'])==('completed',0)
  if 'request' in dep:assert sha(dep['request'])==dep['request_sha256']
 assert len(list(Path(ng['data_root']).glob('Part_*.bi4')))==801
 for fk in ['generated_xml','prepared_report']:assert sha(gp[fk])==gp[fk+'_sha256']
 assert sha(iq['report'])==iq['report_sha256'];assert q['actual_counts']['total_particles']==194427 and q['actual_counts']['fluid_particles']==31658 and q['actual_counts']['solver_dimension']==3
 assert iq['basic_placement_checks_pass'] and iq['central_mk50_support'];assert b['historical_precision_negative_retained'];assert all(v is None for k,v in b['future_typed_outputs'].items() if k!='attempt_id')
 md={};removed=[]
 for path,expected in q['input_sha256'].items():
  if Path(path).name=='bed_audit_full801_fresh138.py':
   removed.append({'path':path,'reason':'unused future bed-stage worker; stale source hash preserved in Root817 failure evidence; not invoked by unchanged typed converter'});continue
  if expected is None:removed.append({'path':path,'reason':'nonfile directory or future unknown digest; no hash bypass'});continue
  if Path(path).suffix.lower() in SCI:md[path]=expected;continue
  assert Path(path).is_file() and sha(path)==expected,(tag,path,'metadata/source digest mismatch');md[path]=expected
 original_owner=Path(b['source_owner']);assert sha(original_owner)==b['source_owner_sha256'];owner=load(original_owner);fresh=load(S/'owners'/(tag+'-fresh138-owner.json'))
 # Keep this condition's original legacy converter keys and add provenance outside those keys.
 owner.update({'root820_fresh138_source_owner':str(S/'owners'/(tag+'-fresh138-owner.json')),'root820_fresh138_source_owner_sha256':sha(S/'owners'/(tag+'-fresh138-owner.json')),'root820_actual_native':fresh['actual_root808_native'],'root820_actual_gencase_and_qa_attestation':fresh['actual_gencase_and_qa_attestation'],'root820_canonical_physical_scope':fresh['canonical_physical_scope'],'root820_scientific_payloads_accessed':False,'root820_q_n_granted':False})
 assert 'physical_binding' not in owner
 scope={'schema':'legacy-owner-scope.v0','semantic_binding_status':'legacy_incomplete; no cross-resolution physical claim',**{k:owner[k] for k in keys if k in owner}};legacy=hashlib.sha256(json.dumps(scope,sort_keys=True,separators=(',',':')).encode()).hexdigest();op=B/'owners'/(tag+'-actual808-provenance-owner.json');put(op,owner)
 cmd=q['command'][:];i=cmd.index('--owner-metadata')+1;cmd[i]=str(op);assert cmd[0]==str(L/'.venv/bin/python');assert cmd[cmd.index('--data-root')+1]==ng['data_root']
 old=q['attempt_id'];attempt=old+'-root820';ap=D/'families/F5'/q['case_id']/attempt;assert not ap.exists()
 for p in [sp,original_owner,op,O/'adoption-review.json',B/'controller-config.json',B/'batch-controller.py',L/'scripts/ds_data02_f3_nvme_input_audit_v1.py',L/'scripts/ds_data02_direct_convert.py',L/'scripts/ds_data02_nvme_convert_v1.py',L/'scripts/ds_data02_runtime_v2.py',L/'scripts/ds_data02_strict_dispatch_v1.py',H/'root_stage1_home_floor_inventory_dispatch_142/launch.py',H/'root_stage1_home_floor_inventory_dispatch_142/root_home_floor_inventory_policy.py',H/'root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json',Path('/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump')]:
  if p.exists():md[str(p)]=sha(p)
 md[str(op)]=sha(op)
 nq={**q,**profile,'attempt_id':attempt,'attempt_root':str(ap),'command':cmd,'kind':'cpu','cpu_task_kind':'conversion','cpu_threads':2,'estimated_storage_bytes':128*1024**3,'disabled':False,'source_only':False,'launch':True,'launch_allowed':True,'execution_allowed':True,'conversion_allowed':True,'status':'root_enabled_after_own_native_GenCase_QA_actual0_metadata_review','source_h5_legacy_scope_sha256':legacy,'source_h5_legacy_scope':{'schema':'legacy-owner-scope.v0','sha256':legacy,'status':'prospective from own compatible owner; actual producer report still required','cross_resolution_claim':False},'root_prospective_legacy_scope_sha256':legacy,'root_reviewed_source_request':str(sp),'root_reviewed_source_request_sha256':sha(sp),'root_compatibility_owner':str(op),'root_compatibility_owner_sha256':sha(op),'root_future_hash_claim':False,'root_dispatch_coordination_lock':str(D/'runtime/stage1-fullnative-conversion-dispatch.lock'),'input_sha256':md,'input_files':sorted(md),'independent_case_count_increment':0,'q_n_granted':False}
 qp=B/'requests'/(tag+'-typed-request.json');put(qp,nq);rows.append({'tag':tag,'actual_request':str(qp),'actual_native_receipt':ng['receipt'],'expected_frames':801,'prospective_legacy_scope_sha256':legacy,'canonical_physical_condition_sha256':q['physical_condition_sha256'],'source_request_preset_scope_sha256_retained_in_source':q['source_h5_legacy_scope_sha256'],'directory_future_declarations_removed_from_actual_hash_input':removed})
assert len(rows)==10
put(O/'adoption-review.json',{'schema':'ds02.f5.fresh138.root-adoption.v1','source_commit':commit,'source_package':str(S),'adopted_package':str(A),'files_byte_exact':files,'actual_completed0_native_GenCase_initial_QA_cases':rows,'source_files_immutable':True,'own_condition_original125_owner_legacy_keys_preserved':True,'future_H5_XMF_hashes_not_claimed':True,'root_read_or_hashed_science_payload':False,'independent_case_count_increment':0})
put(B/'controller-config.json',{'rows':rows,'shared_conversion_dispatch_lock':str(D/'runtime/stage1-fullnative-conversion-dispatch.lock'),'same_lock_as_root816':True,'maximum_parallel_new_conversions':1,'cpu_threads_per_job':2,'maximum_reserved_cpu':64,'guard_policy_unmodified':True,'first_actual0_before_next':True,'source_adoption_review':str(O/'adoption-review.json')})
controller=r'''from pathlib import Path
import json,subprocess,time,fcntl,datetime
O=Path(__file__).parent;R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');load=lambda p:json.loads(Path(p).read_text());cfg=load(O/'controller-config.json');results=[]
for row in cfg['rows']:
 q=load(row['actual_request']);ap=Path(q['attempt_root']);nr=load(row['actual_native_receipt']);assert (nr['status'],nr['returncode'])==('completed',0)
 with Path(cfg['shared_conversion_dispatch_lock']).open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  print(json.dumps({'tag':row['tag'],'state':'acquired shared conversion lock','at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}),flush=True)
  while sum(x.get('cpu_threads',0) for x in load(D/'runtime/resource-ledger.json')['reservations'])+2>64:time.sleep(3)
  p=subprocess.run([str(L/'.venv/bin/python'),str(H/'root_stage1_home_floor_inventory_dispatch_142/launch.py'),row['actual_request']],cwd=L,capture_output=True,text=True)
 rp=ap/'execution-receipt.json';cp=ap/'typed/conversion-report.json';r=load(rp) if rp.exists() else {};c=load(cp) if cp.exists() else {};passed=(r.get('status'),r.get('returncode'))==('completed',0) and p.returncode==0 and c.get('conversion_status')=='completed' and c.get('frames')==801 and c.get('particles')==194427 and c['solver_dimension']['solver_dimension']==3 and c['partvtk_validation']['all_passed'] and c['hash_scopes']['physical_condition_sha256']==row['prospective_legacy_scope_sha256'] and c['time_evidence']['last_s']>=16
 result={'tag':row['tag'],'request':row['actual_request'],'actual_receipt':str(rp),'actual_conversion_report':str(cp),'status':r.get('status'),'returncode':r.get('returncode'),'launcher_returncode':p.returncode,'actual_full801_typed_pass':passed,'independent_case_increment':0,'launcher_error':p.stderr[-1500:]};results.append(result);print(json.dumps(result),flush=True)
 if not passed:break
(O/'controller-result.json').write_text(json.dumps({'requested':10,'actual_full801_typed_pass_count':sum(x['actual_full801_typed_pass'] for x in results),'pending_held':10-len(results),'results':results,'science_payload_read_or_hashed_by_controller':False,'independent_case_increment':0},indent=2)+'\n')
raise SystemExit(0 if len(results)==10 and all(x['actual_full801_typed_pass'] for x in results) else 1)
'''
ast.parse(controller);(B/'batch-controller.py').write_text(controller)
for row in rows:
 qp=Path(row['actual_request']);q=load(qp)
 for p in [O/'adoption-review.json',B/'controller-config.json',B/'batch-controller.py']:q['input_sha256'][str(p)]=sha(p)
 q['input_files']=sorted(q['input_sha256']);put(qp,q)
(O/'prepare-source.py').write_bytes(Path(__file__).read_bytes());print(json.dumps({'source_files':len(files),'native_GenCase_QA_actual0_cases':len(rows),'controller':str(B/'batch-controller.py'),'count_increment':0}))
