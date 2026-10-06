from pathlib import Path
import json,hashlib,datetime,subprocess
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
def load(p):return json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix.lower() not in {'.dat','.h5','.hdf5','.bi4','.csv','.vtk','.vtu','.npy','.npz'};return hashlib.sha256(p.read_bytes()).hexdigest()
def put(p,d):Path(p).write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
def root(n):return next(H.glob(f'root*_{n}'))
O=H/'root_stage1_f2_first48_remaining24_registered_source_generation_801';O.mkdir(exist_ok=False)
base=L/'campaigns/ds-data-02/families/F2/handoff_20261003/root_followup_099_f2_stage1_first24_domain_expansion_v1';builder=base/'build_fresh099.py'
tq=load(next(root(434).glob('*RX046*ROT065*typed-request.json')));prep=load(tq['prepared_input_report']);asset=next(x for x in prep['assets'] if x['role']=='official GenCase mvrotfile control asset');assert asset['sha256']==asset['verified_post_gencase_sha256']=='ff966330e01e565987ebf182a7dfd7401d76577ae1c266894fc7db4aa34c5b70'
motion=Path(asset['copied_to']);assert motion.is_file() # No source-table bytes read or hashed by Root.
config={'source_builder':str(builder),'actual_registered_motion_asset':str(motion),'actual_registered_motion_sha256':asset['verified_post_gencase_sha256'],'actual_motion_prepared_report':tq['prepared_input_report'],'motion_hash_origin':'actual registered GenCase preparation/restoration report; not rehashed by Root','receiver_x_values_m':[.47,.49,.51,.53,.56,.58,.61,.63],'rotation_duration_s':[.75,.90,1.05],'old_rotation_duration_s':.65,'hold_start_s':.5,'final_angle_deg':-105,'window_s':4,'frames':401,'resolution_dp_m':.01,'source_QA_worker':str(base/'workers/f2_stage1_initial_qa_worker.py'),'range_visual_release_gate':'F2 actual RX046/RX064 rotation065/120 completed401 PNG visual decisions integrated by Root before release','native_counts':None,'qualification_or_precision_approval':False,'no_production_enabled_by_source_generation':True,'existing_24_conditions_preserved':True,'canonical_binding_uses_source_definition_and_control_table':True}
cfgp=O/'generation-config.json';put(cfgp,config)
worker='''from pathlib import Path
import json,hashlib,sys,runpy,shutil,math
cfg=json.loads(Path(sys.argv[1]).read_text());out=Path(sys.argv[2]);out.mkdir(parents=True,exist_ok=False)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def put(p,d):Path(p).parent.mkdir(parents=True,exist_ok=True);Path(p).write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\\n')
motion=Path(cfg['actual_registered_motion_asset']);assert sha(motion)==cfg['actual_registered_motion_sha256']
raw=[]
for line in motion.read_text().splitlines()[1:]:
 if line.strip():t,a=line.split(';',1);raw.append((float(t),float(a)))
assert dict(raw)[0.0]==0 and dict(raw)[.5]==0 and dict(raw)[1.15]==-105 and dict(raw)[4.0]==-105
source=Path(cfg['source_builder']).read_text();source=source.replace('FIRST24','FIRST48').replace('first24','first48')
ns={'__file__':str(out/'registered_source_builder.py'),'__name__':'ds02_registered_source_generation'};exec(compile(source,str(out/'registered_source_builder.py'),'exec'),ns);ns['HERE']=out
for d in ['source','owners','workers','motions','requests']: (out/d).mkdir()
worker=out/'workers/f2_stage1_initial_qa_worker.py';shutil.copyfile(cfg['source_QA_worker'],worker)
records=[]
for duration in cfg['rotation_duration_s']:
 values={}
 for t,a in raw:
  if t<=.5:nt=t
  elif t<1.15:nt=.5+(t-.5)*duration/.65
  else:nt=t+duration-.65
  if nt<=4:values[nt]=a
 values[0.0]=0.;values[.5]=0.;values[.5+duration]=-105.;values[4.0]=-105.
 times=sorted(values);assert times[0]==0 and times[-1]==4 and all(b>a for a,b in zip(times,times[1:]))
 scaled=out/'motions'/('ROT'+f'{round(duration*100):03d}'+'.dat');scaled.write_text('#Time;Degrees\\n'+''.join(f'{t!r};{values[t]!r}\\n' for t in times))
 for x in cfg['receiver_x_values_m']:
  spec=ns['case_spec'](x,duration,f'{round(duration*100):03d}',scaled,'Time-scaled reviewed angular table; native piecewise-linear; visual pending')
  definition,mot,metap,meta=ns['materialize_source'](spec)
  meta['motion'].update(source_bytes_equal_to_reviewed_template=False,original_registered_motion_sha256=cfg['actual_registered_motion_sha256'],time_scaling_method='Hold 0..0.5 unchanged; rotation sample times scaled by duration/0.65 with angles preserved; final hold extended to4; no continuous-C2 claim')
  meta['physical_condition']['native_forcing']='official mvrotfile; time-scaled reviewed angular samples, native piecewise-linear, final -105degrees and full4s post-stop hold; candidate visual pending'
  meta['physical_condition_sha256']=meta['source_plan_physical_condition_sha256']=ns['canonical_sha'](meta['physical_condition'])
  meta['domain_basis']['range_visual_release_gate']=cfg['range_visual_release_gate'];meta['production_status']='disabled candidate; actual GenCase/QA/native/full401 visual evidence required';meta['actual_counts']=None;meta['actual_mass_kg']=None;put(metap,meta)
  cid=meta['case_id'];ownerp=out/'owners'/(cid+'.owner.json');owner=ns['make_owner'](meta,definition,mot,metap,{},worker);put(ownerp,owner)
  descriptor={'schema':'ds02.f2.first48.prospective-disabled-job-plan.v1','case_id':cid,'physical_case_id':meta['physical_case_id'],'physical_condition_sha256':meta['physical_condition_sha256'],'source_definition':str(definition),'motion_file':str(mot),'metadata':str(metap),'owner':str(ownerp),'disabled':True,'execution_allowed':False,'launch':False,'actual_counts':None,'future_hashes':{'gencase':None,'native_frame0_qa':None,'full401_native':None,'typed':None,'xmf':None,'render':None},'gate':cfg['range_visual_release_gate'],'precision_status':'not_accepted','production_approval':'none','independent_case_increment':0};put(out/'requests'/(cid+'-disabled-job-plan.json'),descriptor)
  records.append({'case_id':cid,'physical_case_id':meta['physical_case_id'],'physical_condition_sha256':meta['physical_condition_sha256'],'receiver_x_m':x,'rotation_duration_s':duration,'definition':{'path':str(definition),'sha256':sha(definition)},'motion':{'path':str(mot),'sha256':sha(mot),'hash_origin':'actual registered source generation worker'},'metadata':{'path':str(metap),'sha256':sha(metap)},'owner':{'path':str(ownerp),'sha256':sha(ownerp)},'native_counts':None,'source_only':True,'independent_case_increment':0})
assert len(records)==24 and len({r['physical_case_id'] for r in records})==24 and len({r['physical_condition_sha256'] for r in records})==24
report={'schema':'ds02.f2.actual-registered-first48-source-generation.v1','cases':records,'generated_source_conditions':24,'counts_not_measured_or_fabricated':True,'scientific_motion_tables_read_only_inside_registered_shared_job':True,'source_input_motion_sha256':cfg['actual_registered_motion_sha256'],'actual_physical_cases_completed':0,'independent_case_increment':0,'new_conditions_not_qualified_or_visual_accepted':True,'range_visual_release_gate':cfg['range_visual_release_gate'],'expected_native_frames':401,'time_window_s':4.0,'native_piecewise_linear_control_declared':True};put(out.parent/'source-generation-report.json',report);print(json.dumps({'generated_sources':24,'independent_case_increment':0}),flush=True)
'''
wp=O/'registered-source-generation-worker.py';wp.write_text(worker)
template=load(next(root(777).glob('*request.json')));keys=['root_dataset_inventory_profile','root_inventory_profile','root_inventory_policy_source','root_inventory_policy_source_sha256','root_inventory_policy_sha256','root_actual_launch_source','root_actual_launch_source_sha256','resource_window']
q={k:template[k] for k in keys if k in template};q.update(schema='ds02.runner-request.v2',family_id='F2',case_id='F2_FIRST48_REMAINING24_SOURCE_ROOT801',attempt_id='root-stage1-f2-first48-remaining24-registered-source-generation-root801',kind='cpu',cpu_task_kind='audit',cpu_threads=4,launch_owner='root',worktree_root=str(R),cwd=str(L),source_only=False,disabled=False,launch=True,launch_allowed=True,execution_allowed=True,max_wall_seconds=600,estimated_storage_bytes=512*1024**2,command=[str(L/'.venv/bin/python'),str(wp),str(cfgp),'{attempt_root}/source'],independent_case_increment=0,production_approval='none',numerical_precision_status='not_accepted')
files=[wp,cfgp,builder,Path(tq['prepared_input_report']),Path(tq['gencase_receipt']),Path(config['source_QA_worker']),L/'.venv/bin/python',L/'scripts/ds_data02_runtime_v2.py',L/'scripts/ds_data02_strict_dispatch_v1.py',H/'root_stage1_home_floor_inventory_dispatch_142/launch.py',H/'root_stage1_home_floor_inventory_dispatch_142/root_home_floor_inventory_policy.py',H/'root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json']
# XML and JSON template files read by the builder, bound without reading motion tables here.
f2=Path('/home/jade/.codex/worktrees/ds-data-02-f2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02')
files += [f2/'families/F2/handoff_20261003/root_followup_090_f2_stage1_production_endpoints_v1/source/F2_STAGE1_OFFSET_P01_DP010_SPATIAL_REFERENCE_SAVE010_Def.xml',H/'root_stage1_f2_rx047_full401_visual_acceptance_326/rx047-root-visual-decision.json']
q['input_sha256']={str(p):sha(p) for p in files};q['input_sha256'][str(motion)]=asset['verified_post_gencase_sha256'];q['input_files']=sorted(q['input_sha256']);qp=O/'registered-source-generation-request.json';put(qp,q)
ar=D/'families/F2'/q['case_id']/q['attempt_id'];assert not ar.exists()
p=subprocess.run([str(L/'.venv/bin/python'),str(H/'root_stage1_home_floor_inventory_dispatch_142/launch.py'),str(qp)],cwd=L,text=True,capture_output=True)
rp=ar/'execution-receipt.json';r=load(rp) if rp.exists() else {};reportp=ar/'source-generation-report.json';report=load(reportp) if reportp.exists() else {};passed=r.get('status')=='completed' and r.get('returncode')==0 and report.get('generated_source_conditions')==24
put(O/'actual-source-generation-review.json',{'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'request':str(qp),'actual_receipt':str(rp),'status':r.get('status'),'returncode':r.get('returncode'),'launcher_returncode':p.returncode,'actual_report':str(reportp),'actual_report_sha256':sha(reportp) if reportp.exists() else None,'actual_registered_source_generation_pass':passed,'scientific_motion_not_read_or_hashed_by_main':True,'only_registered_worker_read_source_motion':True,'no_native_solver_started':True,'independent_case_increment':0,'launcher_error':p.stderr[-2500:]})
print(json.dumps({'status':r.get('status'),'returncode':r.get('returncode'),'actual_registered_source_generation_pass':passed,'launcher_error':p.stderr[-1800:]}));raise SystemExit(0 if passed else 1)
