from pathlib import Path
import json,hashlib,sys,runpy,shutil,math
cfg=json.loads(Path(sys.argv[1]).read_text());out=Path(sys.argv[2]);out.mkdir(parents=True,exist_ok=False)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def put(p,d):Path(p).parent.mkdir(parents=True,exist_ok=True);Path(p).write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
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
 scaled=out/'motions'/('ROT'+f'{round(duration*100):03d}'+'.dat');scaled.write_text('#Time;Degrees\n'+''.join(f'{t!r};{values[t]!r}\n' for t in times))
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
