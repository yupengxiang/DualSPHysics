from pathlib import Path
import json,hashlib,subprocess,ast,runpy,io,contextlib,datetime
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';W=Path('/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics');D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');root=lambda n:next(H.glob(f'root*_{n:03d}'));load=lambda p:json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix.lower() not in {'.h5','.hdf5','.bi4','.ibi4','.obi4','.csv','.dat','.vtk','.vtu','.npy','.npz'};return hashlib.sha256(p.read_bytes()).hexdigest()
ref=lambda p:{'path':str(p),'sha256':sha(p)}
def put(p,v):Path(p).write_text(json.dumps(v,indent=2)+'\n')
O=H/'root_stage1_F5_source170_eleven_genuinely_unfinished_own848849_full801_native230_fair_GPU_CPU2_1017';O.mkdir(exist_ok=False)
prefix='lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_170_f5_pending_native_successors_v1';commit=subprocess.check_output(['git','rev-parse','aad7133a'],cwd=W,text=True).strip();names=subprocess.check_output(['git','ls-tree','-r','--name-only',commit,'--',prefix],cwd=W,text=True).splitlines();assert 20<len(names)<100;adopted=[]
for name in names:
 assert Path(name).suffix in {'.json','.py','.md'};raw=subprocess.check_output(['git','show',f'{commit}:{name}'],cwd=W);assert raw==(W/name).read_bytes();p=R/name;assert not p.exists() or p.read_bytes()==raw;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw);adopted.append(ref(p))
P=R/prefix;vld=P/'scripts/validate_fresh170.py';v=runpy.run_path(str(vld));rp=P/'metadata/fresh170-validator-report.json';before=ref(rp);write=Path.write_text
try:
 Path.write_text=lambda path,data,*a,**k:write(O/'actual-source170-original-validator-output.json' if path==rp else path,data,*a,**k)
 with contextlib.redirect_stdout(io.StringIO()):v['main']()
finally:Path.write_text=write
assert ref(rp)==before
# Reuse the actual complete original848 GenCase/849 QA metadata contract,
# not source170's abbreviated QA summary or guessed scientific attestations.
s=(root(850)/'batch-controller.py').read_text();core=s.split('\ndef run(c):')[0];core=core.replace("O=Path(__file__).parent;",f"O=Path({str(O)!r});");core=core.replace("'-own848849-full801-native-root850'","'-own848849-full801-native-source170-root1017'")
controller=O/'fair-native-controller.py';cs=(root(948)/'fair-native-controller.py').read_text();cs=cs.replace('import json,fcntl,subprocess,time,shutil,sys,hashlib','import json,fcntl,subprocess,time,shutil,sys,hashlib\nfrom concurrent.futures import ThreadPoolExecutor,as_completed');cs=cs.replace('frames==836','frames==801').replace('actual_full836_native_pass','actual_full801_native_pass')
start=cs.index("for qp in cfg['requests']:");cs=cs[:start]+'''def run(qp):
 assert hashlib.sha256(Path(qp).read_bytes()).hexdigest()==cfg['request_sha256'][qp]
 (stdout,stderr),rc=dispatch(qp);q=load(qp);rp=Path(q['attempt_root'])/'execution-receipt.json';r=load(rp) if rp.exists() else {};frames=len(list((rp.parent/'solver_output/data').glob('Part_*.bi4')));passed=rc==0 and (r.get('status'),r.get('returncode'))==('completed',0) and frames==801
 return {'tag':q['source_condition']['tag'],'case_id':q['case_id'],'physical_case_id':q['physical_case_id'],'request':qp,'actual_receipt':str(rp),'status':r.get('status'),'returncode':r.get('returncode'),'launcher_returncode':rc,'native_saved_frame_file_count':frames,'actual_full801_native_pass':passed,'stdout_tail':stdout[-1500:],'stderr_tail':stderr[-1500:],'case_credit':0}
with ThreadPoolExecutor(max_workers=7) as pool:
 pending={pool.submit(run,qp):qp for qp in cfg['requests']}
 for f in as_completed(pending):
  z=f.result();results.append(z);(O/'actual-progress.json').write_text(json.dumps({'results':results,'not_submitted_or_running':len(cfg['requests'])-len(results),'case_credit':0},indent=2)+'\\n');print(json.dumps(z),flush=True)
(O/'controller-result.json').write_text(json.dumps({'requested':len(cfg['requests']),'results':results,'actual_native_completed0':sum(x['actual_full801_native_pass'] for x in results),'case_credit':0},indent=2)+'\\n')
raise SystemExit(0 if len(results)==len(cfg['requests']) and all(x['actual_full801_native_pass'] for x in results) else 1)
'''
compile(cs,str(controller),'exec');controller.write_text(cs)
put(O/'controller-contract.json',{'source170_disabled_bytes_preserved':True,'original850_metadata_preparation_recipe_unchanged':True,'actual_own_GenCase848_and_QA849_required':True,'only_truly_unfinished11':True,'parallel_native_workers_max':7,'actual_idle_GPU_UUID_shared230_lease_and_foreign_protection':True,'atomic_registration_lock_released_after_running_receipt':True,'cpu_per_job':2,'shared_CPU_cap':64,'Home_floor_GiB':500,'reserved_native_storage_GiB_per_job':10,'headroom_GiB':2,'scientific_payload_IO_by_main':False,'Q_N_granted':False,'case_credit':0})
# Core stops before any launch function; only metadata checks and request preparation.
ns={'__file__':str(controller),'__name__':'metadata_only_preparation'};exec(compile(core,'original850-metadata-only','exec'),ns)
plan=load(P/'metadata/fresh170-source-plan.json');candidates={c['tag']:c for c in ns['plan']['candidates']};assert len(set(plan['pending_tags']))==11
accepted=load(H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_144.json');ids={load(p).get('physical_case_id',load(p)['case_id']) for p in accepted['accepted_decisions']};qs=[];proofs=[]
for tag in plan['pending_tags']:
 c=candidates[tag];sq=P/f'requests/{tag}-native-successor-request.json';sb=P/f'bindings/{tag}-native-successor-binding.json';src=load(sq);binding=load(sb);assert src['disabled'] and src['source_only'] and src['expected_frames']==801 and c['case_id']==src['case_id'] and c['physical_case_id']==src['physical_case_id'] not in ids
 # Independently exclude a live, complete, failed or partial native attempt of
 # the same actual physical identity. GenCase/QA and diagnostic CPUs are retained.
 rows=[]
 for ar in (D/'families/F5'/c['case_id']).iterdir():
  rp=ar/'execution-receipt.json'
  if rp.exists():
   rec=load(rp);q=rec.get('request',{})
   if q.get('cpu_task_kind')=='solver' and q.get('physical_case_id')==c['physical_case_id'] and q.get('expected_frames',q.get('expected_native_frames'))==801:
    rows.append({'receipt':str(rp),'status':rec.get('status'),'returncode':rec.get('returncode')})
 assert not rows,(tag,rows)
 qp=ns['make_request'](c);q=load(qp);assert q['physical_condition_sha256']==src['physical_condition_sha256'] and q['actual_counts']['total_particles']==194427 and q['expected_native_frames']==801
 # Source170 informational plan scope is actual definition XML SHA; the
 # original848 physical condition canonical and native scope remain unchanged.
 source_definition=Path(binding['source_provenance']['gencase_binding']);gb=load(source_definition);assert sha(source_definition)==binding['source_provenance']['gencase_binding_sha256'];actual_def=Path(gb['source_definition']);assert sha(actual_def)==src['source_plan_physical_condition_sha256']
 md=q['input_sha256'].copy()
 for p in [sq,sb,vld,O/'actual-source170-original-validator-output.json',controller,actual_def]:md[str(p)]=sha(p)
 q.update(estimated_storage_bytes=10*1024**3,input_files=sorted(md),input_sha256=md,root_original_source170_request=ref(sq),source170_plan_scope_definition_XML_digest=ref(actual_def),full801_authorized=True,source170_future_native_hashes_null=True,case_credit=0)
 assert '-tmax:16' in q['command'] and '-tout:0.02' in q['command'] and q['cpu_threads']==2 and q['shared_lease_required']
 put(qp,q);qs.append(str(qp));proofs.append({'tag':tag,'source_request':ref(sq),'enabled_request':ref(qp),'actual_GenCase_receipt':ref(q['gencase_receipt']),'actual_initial_QA_receipt':ref(q['initial_qa_receipt']),'actual_initial_QA_placement_report':ref(q['initial_qa_report']),'independently_no_existing_native_receipt_or_partial':True,'source170_plan_scope_actual_definition_XML':ref(actual_def),'canonical_physical_condition_sha256':q['physical_condition_sha256'],'actual_source_scientific_hashes_producer_only':True,'case_credit':0})
put(O/'controller-config.json',{'requests':qs,'request_sha256':{p:sha(p) for p in qs},'native230_launch':str(root(230)/'launch.py'),'native230_sha256':sha(root(230)/'launch.py'),'maximum_parallel_native_jobs':7,'case_credit':0})
put(O/'source170-adoption-independent11-native-absence-and-own-input-review.json',{'source_commit':commit,'adopted_files':adopted,'original_validator_report_unchanged':before,'actual_scientific_payload_IO_by_primary':False,'cases':proofs,'no_duplicate_completed_native':True,'source_future_hashes_preserved_null':True,'case_credit':0});(O/'preparation-source.py').write_bytes(Path(__file__).read_bytes());paths=[str(Path(x['path']).relative_to(R)) for x in adopted]+[str(p.relative_to(R)) for p in O.rglob('*') if p.is_file()];subprocess.run(['git','add','--',*paths],cwd=R,check=True);subprocess.run(['git','commit','-q','-m','ds02: register11 remaining F5 full801 native cases with fair idle GPU admission and original producer scopes','--',*paths],cwd=R,check=True);print({'root':str(O),'registered_native11':len(qs),'source_commit':commit,'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()})
