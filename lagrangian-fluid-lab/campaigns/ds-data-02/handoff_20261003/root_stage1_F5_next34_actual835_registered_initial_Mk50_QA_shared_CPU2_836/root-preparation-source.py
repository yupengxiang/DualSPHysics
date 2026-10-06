from pathlib import Path
import json,hashlib,subprocess,ast,datetime
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';O=H/'root_stage1_F5_next34_actual835_registered_initial_Mk50_QA_shared_CPU2_836';O.mkdir()
original=L/'campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_103_stage1_f5_c082s1_typed_xmf_bed_binding_disabled_v1/workers/initial_placement_mk50_audit.py';assert hashlib.sha256(original.read_bytes()).hexdigest()=='105ce558f345fda553f5e659e3d1af3ae7addd5a960f25f8f9622abbb8e7503d'
adapter=r'''from pathlib import Path
import sys,json,hashlib,importlib.util
SOURCE=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_103_stage1_f5_c082s1_typed_xmf_bed_binding_disabled_v1/workers/initial_placement_mk50_audit.py')
assert hashlib.sha256(SOURCE.read_bytes()).hexdigest()=='105ce558f345fda553f5e659e3d1af3ae7addd5a960f25f8f9622abbb8e7503d'
spec=importlib.util.spec_from_file_location('f5_original_placement_audit',SOURCE);audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)
if '--check' not in sys.argv:
 assert '--binding' in sys.argv
 b=json.loads(Path(sys.argv[sys.argv.index('--binding')+1]).read_text())
 plan=json.loads(Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_F5_next34_distinct_inside_visual_range_source_preparation_823/source-plan.json').read_text())
 cases={c['case_id']:c for c in plan['candidates']};assert len(cases)==34 and b['case_id'] in cases
 c=cases[b['case_id']];assert b['physical_case_id']==c['physical_case_id'] and b['physical_condition_sha256']==c['physical_condition_sha256']
 audit.CASE=b['case_id']
raise SystemExit(audit.main())
'''
ast.parse(adapter);(O/'next34_identity_bound_original_placement_audit.py').write_text(adapter)
controller=r'''from pathlib import Path
import json,hashlib,time,subprocess,fcntl
O=Path(__file__).parent;R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');load=lambda p:json.loads(Path(p).read_text())
def root(n):return next(H.glob(f'root*_{n}'))
def put(p,d):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n');tmp.replace(p)
def sha(p):
 p=Path(p);assert p.suffix in {'.json','.py','.md','.xml'};return hashlib.sha256(p.read_bytes()).hexdigest()
def ref(p):return {'path':str(p),'sha256':sha(p)}
plan_path=root(823)/'source-plan.json';plan=load(plan_path);G=root(835);E=root(441)/'export_then_fresh103_placement_qa.py';original=L/'campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_103_stage1_f5_c082s1_typed_xmf_bed_binding_disabled_v1/workers/initial_placement_mk50_audit.py';A=O/'next34_identity_bound_original_placement_audit.py';assert sha(E)=='b74de4ee73cafb8188ac8f7daeef40b37b6ece00efea177d2f0390dc12304309';python=str(L/'.venv/bin/python');partvtk='/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64';results=[]
for c in plan['candidates']:
 gp=G/'requests'/(c['tag']+'-gencase-request.json')
 while True:
  if gp.exists():
   gq=load(gp);gr=Path(gq['attempt_root'])/'execution-receipt.json'
   if gr.exists():
    r=load(gr)
    if r['status']=='completed':assert r['returncode']==0;break
    assert r['status'] in ['reserved','running'],f'GenCase terminal {r["status"]}'
  launch=load(G/'controller-launch-process.json');proc=Path('/proc')/str(launch['pid']);assert proc.exists(),'GenCase controller missing';f=(proc/'stat').read_text().split(') ',1)[1].split();assert f[0]!='Z' and f[19]==launch['proc_start_ticks'];time.sleep(3)
 pp=Path(gq['attempt_root'])/'prepared/prepared-input-report.json';p=load(pp);assert p['case_id']==c['case_id'] and p['actual_generated_constants']['data2d']['value']=='false';counts={'total_particles':p['actual_total_particles'],**{k+'_particles':v for k,v in p['generated_xml_particle_counts'].items()}};assert counts=={'total_particles':194427,'fixed_particles':158559,'moving_particles':4210,'floating_particles':0,'fluid_particles':31658}
 xml=Path(p['prefix']).with_suffix('.xml');bi4=Path(p['prefix']).with_suffix('.bi4');assert sha(xml)==p['xml_sha256'];ap=D/'families/F5'/c['case_id']/f'root-stage1-f5-next34-{c["tag"].lower()}-own835-initial-placement-mk50-root836';assert not ap.exists();aid=ap.name
 producer=O/'bindings'/(c['tag']+'-actual-Gencase-producer.json');put(producer,{'case_id':c['case_id'],'attempt_id':gq['attempt_id'],'actual_counts':counts,'own_request':ref(gp),'prepared_input_report':ref(pp),'actual_counts_provenance':'own Root835 official GenCase report; no inherited producer counts'})
 bp=O/'bindings'/(c['tag']+'-initial-QA-binding.json');b={'schema':'ds02.f5.c082s1.stage1-placement-mk50-binding.fresh103.v1','case_id':c['case_id'],'physical_case_id':c['physical_case_id'],'physical_condition_sha256':c['physical_condition_sha256'],'qa_attempt_id':aid,'gencase_attempt_id':gq['attempt_id'],'dimension':3,'actual_counts':counts,'source_mkbound':40,'native_bed_mk':50,'numerical_precision':{'diagnostic_only':True,'accepted_as_stage1_placement_gate':False,'exact_dp_lattice_threshold':1e-6},'files':{'actual_gencase_binding':ref(producer),'gencase_receipt':ref(gr),'prepared_input_report':ref(pp),'generated_xml':{'path':str(xml),'sha256':p['xml_sha256']},'generated_bi4':{'path':str(bi4),'sha256':p['bi4_sha256']},'official_particle_csv':{'path':'<inside registered exporter>','sha256':None},'gencase_output_root':{'path':gq['attempt_root'],'sha256':None}},'q_n_granted':False,'independent_case_count_increment':0};put(bp,b)
 q={k:v for k,v in load(root(824)/'registered-source-generation-request.json').items() if k not in ['input_files','input_sha256','input_sha256_provenance','command']};q.update(case_id=c['case_id'],physical_case_id=c['physical_case_id'],physical_condition_sha256=c['physical_condition_sha256'],attempt_id=aid,attempt_root=str(ap),cpu_task_kind='audit',cpu_threads=2,max_wall_seconds=3600,estimated_storage_bytes=2*1024**3,binding=str(bp),binding_sha256=sha(bp),command=[python,str(E),'--binding',str(bp),'--partvtk',partvtk,'--audit-worker',str(A),'--output-dir','{attempt_root}/initial-qa'])
 paths=[bp,producer,gp,gr,pp,xml,plan_path,E,A,original,Path(gq['binding']),H/'root_stage1_home_floor_inventory_dispatch_142/launch.py',Path(q['root_inventory_policy_source']),L/'scripts/ds_data02_runtime_v2.py',L/'scripts/ds_data02_strict_dispatch_v1.py'];q['input_files']=[str(p) for p in paths]+[python,partvtk,str(bi4)];q['input_sha256']={str(p):sha(p) for p in paths};q['input_sha256'].update({python:'a2f33a6e006989270f4340528eb61f8f97366e00a5d1b602ac8672ea44fc56ae',partvtk:'62630430902484f4aede017108313673fe6414f40fb59b6ae7f14ac23219db00',str(bi4):p['bi4_sha256']});q['input_sha256_provenance']={str(bi4):'own Root835 GenCase producer report; no root payload read or hash'};qp=O/'requests'/(c['tag']+'-initial-QA-request.json');put(qp,q)
 with (D/'runtime/stage1-fullnative-conversion-dispatch.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  while sum(x.get('cpu_threads',0) for x in load(D/'runtime/resource-ledger.json')['reservations'])+2>64:time.sleep(3)
  run=subprocess.run([python,str(H/'root_stage1_home_floor_inventory_dispatch_142/launch.py'),str(qp)],cwd=L,capture_output=True,text=True)
 rr=ap/'execution-receipt.json';ar=ap/'initial-qa/placement/c082s1-stage1-placement-mk50-audit.json';r=load(rr) if rr.exists() else {};a=load(ar) if ar.exists() else {};passed=run.returncode==0 and (r.get('status'),r.get('returncode'))==('completed',0) and a.get('stage1_basic_placement_proof')=='pass_excluding_numerical_precision' and a.get('all_basic_placement_checks_pass') and a['actual_counts']['total_particles']==counts['total_particles'];out={'tag':c['tag'],'case_id':c['case_id'],'request':ref(qp),'actual_receipt':str(rr),'actual_initial_QA_report':str(ar),'status':r.get('status'),'returncode':r.get('returncode'),'launcher_returncode':run.returncode,'initial_placement_Mk50_pass':bool(passed),'numerical_precision':a.get('numerical_precision'),'numerical_precision_accepted':False,'independent_case_count_increment':0,'launcher_error':run.stderr[-1500:]};results.append(out);put(O/'actual-progress.json',{'cases':results,'independent_case_count_increment':0});print(json.dumps(out),flush=True);assert passed,out
put(O/'controller-result.json',{'status':'completed','actual_own_initial_QA_count':len(results),'cases':results,'independent_case_count_increment':0,'full_native_request_still_requires_actual_each_QA_and_storage_guard':True})
'''
ast.parse(controller);(O/'batch-controller.py').write_text(controller);(O/'root-preparation-source.py').write_bytes(Path(__file__).read_bytes());(O/'identity-adapter-scope-review.json').write_text(json.dumps({'original_worker':str(original),'original_worker_sha256':'105ce558f345fda553f5e659e3d1af3ae7addd5a960f25f8f9622abbb8e7503d','change':'Set original worker CASE to one of the exact34 source-plan case IDs only after matching physical ID and canonical condition digest; original audit.main and all geometric, numeric and identity checks are unchanged.','shared_runtime_changed':False,'array_thresholds_changed':False,'native_counts_prospective_until_own_GenCase':True,'first_failure_stops_this_controller':True,'Home_min_free_gib':500,'cpu_threads':2,'shared_reservation_cap':64,'independent_case_increment':0},indent=2)+'\n');assert not subprocess.check_output(['git','diff','--cached','--name-only'],cwd=R,text=True).strip();subprocess.run(['git','add','--',str(O.relative_to(R))],cwd=R,check=True);subprocess.run(['git','commit','-m','ds02: bind each next34 initial placement audit to own GenCase'],cwd=R,check=True,stdout=subprocess.DEVNULL);commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()
with (O/'controller.log').open('ab') as log:p=subprocess.Popen([str(L/'.venv/bin/python'),str(O/'batch-controller.py')],cwd=L,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
f=(Path('/proc')/str(p.pid)/'stat').read_text().split(') ',1)[1].split();out={'pid':p.pid,'proc_start_ticks':f[19],'controller':str(O/'batch-controller.py'),'controller_sha256':hashlib.sha256((O/'batch-controller.py').read_bytes()).hexdigest(),'launch_commit':commit,'actual_launched_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()};(O/'controller-launch-process.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out))
