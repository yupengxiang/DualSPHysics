from pathlib import Path
import json,hashlib,datetime,subprocess
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';old=next(H.glob('root*_1012'));load=lambda p:json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix.lower() in {'.json','.jsonl','.py','.md','.log','.xml','.xmf','.txt'};return hashlib.sha256(p.read_bytes()).hexdigest()
ref=lambda p:{'path':str(p),'sha256':sha(p)}
def put(p,v):Path(p).write_text(json.dumps(v,indent=2)+'\n')
c=load(old/'controller-config.json');lp=old/'controller-launch-process.json';launch=load(lp);st=Path(f"/proc/{launch['pid']}/stat")
if st.exists():
 f=st.read_text().split(') ',1)[1].split();assert f[0]=='Z' or f[19]!=str(launch['proc_start_ticks'])
assert 'SyntaxError: unterminated string literal' in (old/'controller.stderr.log').read_text()
for p in c['requests']:assert not Path(load(p)['attempt_root']).exists()
O=H/'root_stage1_F5_actual1012_controller_pre_dispatch_syntax_failure_preserved_three_original138_bed_repair1_1016';O.mkdir(exist_ok=False);(O/'requests').mkdir();controller=O/'batch-bed-controller.py';s=(old/'batch-bed-controller.py').read_text();assert s.count("+'\n')")==2;s=s.replace("+'\n')","+'\\n')");compile(s,str(controller),'exec');controller.write_text(s)
worker=Path(load(c['requests'][0])['command'][1]);compile(worker.read_text(),str(worker),'exec')
proof=O/'actual1012-pre-dispatch-terminal-failure-and-controller-only-repair.json';put(proof,{'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'failed_controller':ref(old/'batch-bed-controller.py'),'actual_launch_receipt':ref(lp),'actual_stderr':ref(old/'controller.stderr.log'),'classification':'Python controller syntax error before import or any dispatch; no scientific attempts or receipts created','original_attempt_roots_all_absent':True,'repair_number':1,'changes':['escape two generated newline string literals in new controller','supply tag from immutable registered source request filename to new enabled request'],'original_controller_requests_sources_and_logs_preserved':True,'original138_numerical_kernel_and_identity_adapter_and_bindings_byte_unchanged':True,'scientific_payload_IO':False,'case_credit':0})
qs=[]
for p in c['requests']:
 q=load(p);assert sha(p)==c['request_sha256'][p];q['attempt_id']=q['attempt_id'].replace('root1012','root1016-controller-repair1');q['attempt_root']=str(Path(q['attempt_root']).with_name(q['attempt_id']));assert not Path(q['attempt_root']).exists();q['tag']=Path(p).name.split('-enabled-bed-request.json')[0];assert q['tag'] in ['M086_T095','M088_T085','M088_T095'];md=q['input_sha256'].copy()
 for v in [controller,proof,Path(p)]:md[str(v)]=sha(v)
 q.update(input_files=sorted(md),input_sha256=md,root_controller_repair_classification=ref(proof),scientific_payload_IO_by_main=False)
 qp=O/'requests'/Path(p).name;put(qp,q);qs.append(str(qp))
put(O/'controller-config.json',{**c,'requests':qs,'request_sha256':{p:sha(p) for p in qs}});(O/'preparation-source.py').write_bytes(Path(__file__).read_bytes());paths=[str(p.relative_to(R)) for p in O.rglob('*') if p.is_file()]+[str(p.relative_to(R)) for p in old.glob('*launch*.json')]+[str((old/'controller.stderr.log').relative_to(R)),str((old/'controller.stdout.log').relative_to(R))]
subprocess.run(['git','add','--',*paths],cwd=R,check=True);subprocess.run(['git','commit','-q','-m','ds02: preserve pre-dispatch bed controller failure and register syntax-only successor','--',*paths],cwd=R,check=True);print({'root':str(O),'bed_requests':len(qs),'original_science_jobs_started':0,'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()})
