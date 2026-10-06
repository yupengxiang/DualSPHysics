from pathlib import Path
import json,hashlib,subprocess,datetime
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');H=R/'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');root=lambda n:next(H.glob(f'root*_{n:03d}'));load=lambda p:json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix in {'.json','.py','.md','.log','.xml','.xmf','.jsonl'};return hashlib.sha256(p.read_bytes()).hexdigest()
ref=lambda p:{'path':str(p),'sha256':sha(p)}
def put(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
old=root(1016);c=load(old/'controller-config.json');launch=load(old/'controller-launch-process.json');st=Path(f"/proc/{launch['pid']}/stat")
if st.exists():
 s=st.read_text().split(') ',1)[1].split();assert s[0]=='Z' or s[19]!=str(launch['proc_start_ticks'])
a=load(old/'actual-progress.json');assert len(a['results'])==1 and a['not_submitted']==2
z=a['results'][0];assert z['tag']=='M086_T095' and z['returncode']==z['launcher_returncode']==0 and not z['actual_full801_bed_worker_output0'];receipt=load(z['actual_receipt']);b=load(z['actual_report']);qfirst=load(z['request'])
assert receipt['status']=='completed' and receipt['returncode']==0 and b['status']=='completed_worker_output_pending_root_review' and b['bound_actual_inputs']['case_id']==qfirst['case_id'] and b['bound_actual_inputs']['physical_case_id']==qfirst['physical_case_id'] and len(b['frame_reports'])==801
assert b['bound_actual_inputs']['full_native_solver']['saved_state_count']==801
remaining=[p for p in c['requests'] if load(p)['tag'] in ['M088_T085','M088_T095']];assert len(remaining)==2
ledger=load(D/'runtime/resource-ledger.json')
for p in remaining:
 q=load(p);assert not Path(q['attempt_root']).exists();assert not any(x.get('attempt_id')==q['attempt_id'] for x in ledger['attempts'])
O=H/'root_stage1_actual1016_completed_first_bed_preserved_remaining_two_original138_nested_identity_observer_repair1_1058';O.mkdir(exist_ok=False);(O/'requests').mkdir();controller=O/'batch-bed-controller.py';controller.write_bytes((root(1055)/'batch-bed-controller.py').read_bytes());compile(controller.read_text(),str(controller),'exec')
proof=O/'actual1016-observer-only-failure-independent-classification.json';put(proof,{'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'original_controller':ref(old/'batch-bed-controller.py'),'original_launch':ref(old/'controller-launch-process.json'),'original_progress':ref(old/'actual-progress.json'),'actual_first_worker_receipt':ref(z['actual_receipt']),'actual_first_worker_report':ref(z['actual_report']),'actual_first_completed801_nested_identity_verified':True,'first_worker_will_not_be_rerun':True,'classification':'observer checked nonexistent flat case_id/physical_case_id instead of actual bound_actual_inputs, causing controller exit1 after true worker0; remaining2 never submitted','controller_observer_repair_number':1,'remaining_attempts_absent_and_not_in_actual_ledger':True,'scientific_kernel_adapter_bindings_inputs_byte_unchanged':True,'main_scientific_payload_IO':False,'case_credit':0})
qs=[]
for p in remaining:
 q=load(p);assert sha(p)==c['request_sha256'][p];original_command=q['command'].copy();md=q['input_sha256'].copy()
 worker=Path(q['command'][1]);assert sha(worker)==md[str(worker)]
 for item in [controller,proof,Path(p)]:md[str(item)]=sha(item)
 q['attempt_id']=q['attempt_id'].replace('root1016-controller-repair1','root1058-observer-repair1');q['attempt_root']=str(Path(q['attempt_root']).with_name(q['attempt_id']));assert not Path(q['attempt_root']).exists()
 q.update(input_files=sorted(md),input_sha256=md,root_observer_only_repair=ref(proof));assert q['command']==original_command
 qp=O/'requests'/Path(p).name;put(qp,q);qs.append(str(qp))
put(O/'controller-config.json',{**c,'requests':qs,'request_sha256':{p:sha(p) for p in qs}});(O/'preparation-source.py').write_bytes(Path(__file__).read_bytes());paths=[str(p.relative_to(R)) for p in O.rglob('*') if p.is_file()]+[str((old/f).relative_to(R)) for f in ['actual-progress.json','controller.stderr.log','controller.stdout.log','controller-launch-process.json']]
subprocess.run(['git','add','--',*paths],cwd=R,check=True);subprocess.run(['git','commit','-q','-m','ds02: preserve true first bed worker0 and repair observer only for two unsubmitted cases','--',*paths],cwd=R,check=True);print({'root':str(O),'new_bed_requests':2,'completed_first_worker_rerun':False,'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()})
