from pathlib import Path
import json,hashlib,subprocess,datetime
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';old=next(H.glob('root*_1108'));D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');load=lambda p:json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix.lower() not in {'.h5','.bi4','.csv','.dat','.vtk','.vtu'};return hashlib.sha256(p.read_bytes()).hexdigest()
ref=lambda p:{'path':str(p),'sha256':sha(p)}
def put(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
j=load(old/'controller-launch-process.json');assert not Path(f"/proc/{j['pid']}").exists();err=(old/'controller.stderr.log').read_text();assert "KeyError: 'cpu_threads'" in err;c=load(old/'controller-config.json');assert len(c['requests'])==4 and all(not Path(load(p)['attempt_root']).exists() for p in c['requests'])
O=H/'root_stage1_actual1108_pre_admission_missing_CPU2_request_field_four_original138_bed_registered_repair1_1112';O.mkdir(exist_ok=False);(O/'requests').mkdir();controller=O/'batch-bed-controller.py';controller.write_bytes((old/'batch-bed-controller.py').read_bytes());compile(controller.read_text(),str(controller),'exec')
proof=O/'actual1108-controller-pre-admission-failure-no-worker-and-CPU2-field-repair.json';put(proof,{'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'original_launch':ref(old/'controller-launch-process.json'),'original_terminal_traceback':ref(old/'controller.stderr.log'),'original_requests':[ref(p) for p in c['requests']],'old_PID_missing':True,'all_four_attempt_roots_absent':True,'actual_failed_before_resource_admission':True,'root_cause':'Disabled source179 metadata omitted cpu_threads; Root1108 enabled request failed to add CPU2 runtime field.','bounded_metadata_repair_number':1,'new_requests_explicit_CPU2_audit':True,'original_controller_science_kernel_bindings_unchanged':True,'no_scientific_worker_restarted':True,'case_credit':0})
qs=[]
for p in c['requests']:
 q=load(p);assert 'cpu_threads' not in q and q['cpu_task_kind']=='audit' and q['kind']=='cpu';q['cpu_threads']=2;q['cpu_task_kind']='audit';q['attempt_id']=q['attempt_id'].replace('root1108','root1112');q['attempt_root']=str(Path(q['attempt_root']).parent/q['attempt_id']);assert not Path(q['attempt_root']).exists();md=q['input_sha256'].copy();md.pop(str(old/'batch-bed-controller.py'),None)
 for m,h in md.items():
  if Path(m).suffix.lower() not in {'.h5','.bi4','.csv','.dat','.vtk'}:assert sha(m)==h
 for f in [controller,proof,Path(p)]:md[str(f)]=sha(f)
 q.update(input_files=sorted(md),input_sha256=md,root_missing_CPU2_registration_metadata_repair_number=1,case_credit=0)
 qp=O/'requests'/Path(p).name;put(qp,q);qs.append(str(qp))
put(O/'controller-config.json',{'requests':qs,'request_sha256':{p:sha(p) for p in qs},'fair_dispatch':c['fair_dispatch'],'effective_shared_serial_conversion_concurrency':1,'case_credit':0});(O/'preparation-source.py').write_bytes(Path(__file__).read_bytes());paths=[str(p.relative_to(R)) for p in O.rglob('*') if p.is_file()];subprocess.run(['git','add','--',*paths],cwd=R,check=True);subprocess.run(['git','commit','-q','-m','ds02: repair missing CPU2 runtime field before four bed audits enter admission','--',*paths],cwd=R,check=True);print({'root':1112,'registered_CPU2_bed':4,'case_credit':0,'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()})
