from pathlib import Path
import json,hashlib,time,subprocess,fcntl,shutil,xml.etree.ElementTree as ET
O=Path(__file__).parent;R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');load=lambda p:json.loads(Path(p).read_text())
def root(n):return next(H.glob(f'root*_{n}'))
SCIENCE={'.h5','.hdf5','.bi4','.ibi4','.csv','.dat','.vtk','.vtu','.npy','.npz'}
def sha(p):
 p=Path(p);assert p.suffix.lower() not in SCIENCE;return hashlib.sha256(p.read_bytes()).hexdigest()
def ref(p):return {'path':str(p),'sha256':sha(p)}
def put(p,d):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n');t.replace(p)
source=root(823)/'source-plan.json';plan=load(source);byid={c['case_id']:c for c in plan['candidates']};assert len(byid)==34;profilepath=next((root(854)/'requests').glob('*typed-request.json'));template=load(profilepath);profile={k:v for k,v in template.items() if (k.startswith('root_') and k not in ['root_compatibility_owner','root_compatibility_owner_sha256','root_prospective_legacy_scope_sha256','root_original_prelaunch_request','root_storage_estimate_review','root_scope','root_reviewed_source_request','root_reviewed_source_request_sha256']) or k=='resource_window'};schema_bound=root(854)/'storage-estimate-and-prelaunch-failure-review.json';assert load(schema_bound)['expected_frames']==801 and load(schema_bound)['expected_particles']==194427
script=L/'scripts/ds_data02_nvme_convert_v1.py';direct=L/'scripts/ds_data02_direct_convert.py';decoder=Path(template['command'][template['command'].index('--decoder')+1]);partvtk=Path(template['command'][template['command'].index('--partvtk')+1]);profile_paths=[Path(x) for x in template['input_sha256'] if x in [str(script),str(direct),str(decoder),str(partvtk)]];assert len(profile_paths)==4
for p in profile_paths:assert sha(p)==template['input_sha256'][str(p)]
legacy_keys=('family_id','physical_case_id','lineage_group_id','paired_background_id','mechanism_id','geometry_family_id','geometry','control_family_id','gravity_m_s2','density_kg_m3','parameters','initial_state','continuum_geometry')
results=[];done=set();upstream_partial=False
while len(done)<34:
 ready=[]
 for np in (root(850)/'requests').glob('*native-request.json'):
  nq=load(np);cid=nq['case_id'];nr=Path(nq['attempt_root'])/'execution-receipt.json'
  if cid in done or not nr.exists():continue
  r=load(nr)
  if (r['status'],r.get('returncode'))==('completed',0):ready.append((np,nq,nr))
  elif r['status'] in ['failed','terminated','aborted']:
   put(O/'actual-native-failure-hold.json',{'request':ref(np),'receipt':ref(nr),'status':r['status'],'no_native_or_GenCase_rerun':True});upstream_partial=True
 if not ready:
  terminal=root(850)/'controller-result.json'
  if terminal.exists():
   r=load(terminal)
   if r['actual_full801_native_pass_count']<34:upstream_partial=True;break
   assert len(done)==34,'Full native batch complete but consumer requests unavailable'
  else:
   c=load(root(850)/'controller-launch-process.json');p=Path('/proc')/str(c['pid']);assert p.exists(),'Owned native controller missing without terminal evidence';f=(p/'stat').read_text().split(') ',1)[1].split();assert f[0]!='Z' and f[19]==c['proc_start_ticks']
  time.sleep(3);continue
 np,nq,nr=sorted(ready,key=lambda x:x[1]['case_id'])[0];cid=nq['case_id'];c=byid[cid];tag=c['tag'];assert nq['physical_case_id']==c['physical_case_id'] and nq['physical_condition_sha256']==c['physical_condition_sha256'];raw=Path(nq['attempt_root'])/'solver_output/data';assert len(list(raw.glob('Part_*.bi4')))==801
 gp=root(848)/'requests'/(tag+'-gencase-request.json');gq=load(gp);gr=Path(gq['attempt_root'])/'execution-receipt.json';pp=Path(gq['attempt_root'])/'prepared/prepared-input-report.json';p=load(pp);qr=Path(nq['initial_qa_receipt']);ar=Path(nq['initial_qa_report']);a=load(ar);assert (load(gr)['status'],load(gr)['returncode'])==(load(qr)['status'],load(qr)['returncode'])==('completed',0);assert p['actual_total_particles']==194427 and p['generated_xml_particle_counts']=={'fixed':158559,'moving':4210,'floating':0,'fluid':31658} and p['actual_generated_constants']['data2d']['value']=='false';assert a['stage1_basic_placement_proof']=='pass_excluding_numerical_precision' and a['all_basic_placement_checks_pass'] and not a['numerical_precision_result_accepted']
 owner=Path(c['source_owner']);assert sha(owner)==c['source_owner_sha256'];own=load(owner);physical=own['source_canonical_physical_condition'];canonical=hashlib.sha256(json.dumps(physical,sort_keys=True,separators=(',',':')).encode()).hexdigest();assert canonical==c['physical_condition_sha256']==own['physical_condition_sha256'];assert own['physical_case_id']==c['physical_case_id'] and 'physical_binding' not in own;legacy_scope={'schema':'legacy-owner-scope.v0','semantic_binding_status':'legacy_incomplete; no cross-resolution physical claim',**{k:own[k] for k in legacy_keys if k in own}};legacy=hashlib.sha256(json.dumps(legacy_scope,sort_keys=True,separators=(',',':')).encode()).hexdigest();assert canonical!=legacy
 bp=O/'bindings'/(tag+'-own848849850-full801-typed-binding.json');binding={'case_id':cid,'physical_case_id':c['physical_case_id'],'canonical_source_physical_condition_sha256':canonical,'actual_converter_legacy_scope_sha256_prospective':legacy,'legacy_scope_preserved':legacy_scope,'canonical_original_source_owner':ref(owner),'own_native_request':ref(np),'own_native_receipt':ref(nr),'own_GenCase_request':ref(gp),'own_GenCase_receipt':ref(gr),'own_prepared_input_report':ref(pp),'own_initial_QA_receipt':ref(qr),'own_initial_QA_report':ref(ar),'actual_counts':p['generated_xml_particle_counts'],'total_particles':194427,'full_native_saved_frame_count':801,'physical_window_s':[0,16],'different_scopes_not_equated':True,'precision_status':'not_accepted','Q_N_granted':False,'case_credit':0};put(bp,binding)
 xml=Path(p['prefix']+'.xml');assert sha(xml)==p['xml_sha256'];cmd=list(template['command'])
 for flag,value in {'--data-root':str(raw),'--generated-xml':str(xml),'--solver-log':str(Path(nq['attempt_root'])/'stdout.log'),'--solver-receipt':str(nr),'--gencase-receipt':str(gr),'--owner-metadata':str(owner)}.items():cmd[cmd.index(flag)+1]=value
 paths=[np,nr,gp,gr,pp,qr,ar,xml,owner,source,profilepath,schema_bound,bp,O/'controller-contract.json',Path(__file__),script,direct,decoder,partvtk,L/'.venv/bin/python',L/'scripts/ds_data02_runtime_v2.py',L/'scripts/ds_data02_strict_dispatch_v1.py',root(142)/'launch.py',root(142)/'root_home_floor_inventory_policy.py',next(H.glob('root*064'))/'resource-window-approval.json'];md={str(p):sha(p) for p in paths};aid='root-stage1-f5-next34-'+tag.lower()+'-own850-full801-typed-nvme-root864';ap=D/'families/F5'/cid/aid;assert not ap.exists()
 q={**profile,'schema':'ds02.runner-request.v2','family_id':'F5','case_id':cid,'physical_case_id':c['physical_case_id'],'physical_condition_sha256':canonical,'canonical_source_physical_condition_sha256':canonical,'actual_converter_scope_sha256_prospective':legacy,'root_prospective_legacy_scope_sha256':legacy,'attempt_id':aid,'attempt_root':str(ap),'kind':'cpu','cpu_task_kind':'conversion','cpu_threads':2,'launch_owner':'root','worktree_root':str(R),'cwd':str(L),'max_wall_seconds':7200,'estimated_storage_bytes':32*1024**3,'command':cmd,'tag':tag,'owner_metadata':str(owner),'binding':str(bp),'binding_sha256':sha(bp),'native_request':str(np),'native_receipt':str(nr),'gencase_receipt':str(gr),'gencase_prepared_report':str(pp),'initial_qa_receipt':str(qr),'initial_qa_report':str(ar),'expected_frames':801,'expected_particles':194427,'expected_fluid_particles':31658,'expected_dimension':3,'physical_window_s':[0,16],'input_files':sorted(md),'input_sha256':md,'disabled':False,'source_only':False,'launch':True,'launch_allowed':True,'execution_allowed':True,'root_review_required':False,'production_approval':'none','independent_case_increment':0,'q_n':'not_granted','precision_status':'not_accepted','scientific_payload_not_read_or_hashed_by_controller':True};qp=O/'requests'/(tag+'-typed-request.json');put(qp,q)
 with (D/'runtime/stage1-fullnative-conversion-dispatch.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  while True:
   ledger=load(D/'runtime/resource-ledger.json');reserved=sum(x.get('new_storage_bytes',0) for x in ledger['reservations'])
   if sum(x.get('cpu_threads',0) for x in ledger['reservations'])+4<=64 and shutil.disk_usage('/home/jade').free-reserved-q['estimated_storage_bytes']-16*1024**3>=ledger['limits']['home_min_free_bytes']:break
   time.sleep(3)
  run=subprocess.run([str(L/'.venv/bin/python'),str(root(142)/'launch.py'),str(qp)],cwd=L,capture_output=True,text=True)
 rp=ap/'execution-receipt.json';cp=ap/'typed/conversion-report.json';r=load(rp) if rp.exists() else {};t=load(cp) if cp.exists() else {};passed=run.returncode==0 and (r.get('status'),r.get('returncode'))==('completed',0) and t.get('conversion_status')=='completed' and t.get('frames')==801 and t.get('particles')==194427 and t['solver_dimension']['solver_dimension']==3 and t['partvtk_validation']['all_passed'] and t['hash_scopes']['physical_condition_sha256']==legacy and t['time_evidence']['last_s']>=16
 out={'tag':tag,'case_id':cid,'request':str(qp),'actual_receipt':str(rp),'actual_conversion_report':str(cp),'status':r.get('status'),'returncode':r.get('returncode'),'launcher_returncode':run.returncode,'actual_full801_typed_pass':passed,'canonical_source_scope_sha256':canonical,'actual_converter_legacy_scope_sha256':legacy,'case_credit':0,'launcher_error':run.stderr[-1500:]};results.append(out);done.add(cid);put(O/'actual-progress.json',{'results':results,'remaining':34-len(done),'case_credit':0});print(json.dumps(out),flush=True)
 if not passed:upstream_partial=True;break
put(O/'controller-result.json',{'requested':34,'actual_full801_typed_pass_count':sum(x['actual_full801_typed_pass'] for x in results),'remaining_not_completed':34-len(done),'upstream_partial_or_capacity_hold':upstream_partial,'results':results,'case_credit':0});raise SystemExit(0 if len(done)==34 and not upstream_partial else 1)
