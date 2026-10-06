from pathlib import Path
import json,hashlib,ast,subprocess,datetime
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';O=H/'root_stage1_F3_next20_actual704_exact_initial_await_four_corner_visual_shared_native230_839';O.mkdir()
script=r'''from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
import json,hashlib,subprocess,time,sys,os,datetime
O=Path(__file__).parent;R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');sys.path[:0]=[str(L/'scripts'),str(H/'root_stage1_f3_first24_eight_solver_resource_policy_134')]
import ds_data02_runtime_v2 as rt,ds02_root_all_idle_gpu_policy_v2 as gpu
load=lambda p:json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix.lower() not in {'.h5','.hdf5','.bi4','.ibi4','.csv','.dat','.vtk','.vtu','.npy','.npz'};return hashlib.sha256(p.read_bytes()).hexdigest()
def ref(p):return {'path':str(p),'sha256':sha(p)}
def put(p,d):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n');tmp.replace(p)
def root(n):return next(H.glob(f'root*_{n}'))
corners={f'F3_STAGE1_DP006_P{p}_AY{a}' for p in ['0800','1200'] for a in ['0250','0750']}
# Root checkpoint records actual adopted delegated decisions. A renderer0,
# source plan, or agent intent cannot release this parameter rectangle.
while True:
 cp_path=max(H.glob('ROOT_LIVE_RESUMPTION_CHECKPOINT_*.json'),key=lambda p:int(p.stem.rsplit('_',1)[1]));cp=load(cp_path);approved={}
 if cp.get('accepted_per_family',{}).get('F3',0)>=12:
  for dp in cp['accepted_decisions']:
   if '/F3_' not in dp:continue
   d=load(dp)
   if d.get('case_id') in corners:approved[d['case_id']]=(dp,d)
 if set(approved)==corners:break
 time.sleep(10)
evidence=[]
for cid,(dp,d) in sorted(approved.items()):
 assert d['status']=='visual-approved-by-delegated-agent' and d['actual_frames']==836 and d['actual_particles']==179208 and d['actual_fluid_particles']==67500 and d['actual_last_time_s']>=8.35 and d['agent_personally_viewed_all_contacts_and_keys'] and not d['main_personally_viewed_pngs'];ev=d['actual_completed_metadata_evidence']
 for key in ['native_receipt','typed_receipt','xmf_receipt','render_receipt']:
  r=load(ev[key]['path']);assert sha(ev[key]['path'])==ev[key]['sha256'] and (r['status'],r['returncode'])==('completed',0)
 a=load(ev['render_report']['path']);assert sha(ev['render_report']['path'])==ev['render_report']['sha256'] and a['all_frames_rendered'] and a['frames']==836 and a['nonfinite_active_states']==0
 evidence.append({'case_id':cid,'root_visual_decision':ref(dp),'actual_render_receipt':ev['render_receipt'],'actual_render_report':ev['render_report']})
gate=O/'actual-four-corner-visual-range-release.json';put(gate,{'schema':'ds02.f3.actual-four-corner-visual-range.v1','status':'visual-range-released','accepted_checkpoint':ref(cp_path),'corners':evidence,'nominal_pitch_multiplier_range':[0.8,1.2],'transverse_amplitude_range_m_s2':[0.25,0.75],'full_window_s':[0,8.35],'expected_saved_frames':836,'precision_status':'视觉检查通过、数值精度未验收','q_n':'not_granted','independent_case_increment':0})
template_path=next(root(706).glob('*P0800_AY0250-native-request.json'));template=load(template_path);source=L/'campaigns/ds-data-02/families/F3/handoff_20261003/root_followup_065_stage1_first48_pitch_ay_source_v1';index_path=next(Path(x) for x in template['input_files'] if x.endswith('fresh065-prepared-index.json'));index=load(index_path);assert len(index['prepared_cases'])==24;review_path=root(705)/'actual-new24-exact-initial-forcing-independent-review.json';review=load(review_path);assert review['actual_input_hashes_before_after_equal'] and not review['main_scientific_payload_read_or_hash'];pr=load(template['actual_preparation_receipt']['path']);assert (pr['status'],pr['returncode'])==('completed',0)
baseprep=load(template['actual_preparation_report']['path']);base_dir=Path(baseprep['prepared_prefix']).parent;qs=[];unique=set();rows=[r for r in index['prepared_cases'] if r['case_id'] not in corners];assert len(rows)==20
solver=Path('/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64');assert sha(solver)=='0415b10e5e32af8b8b7ad2a703f9043dca67dfcf7626eb98f1c05a50856fde29'
for row in rows:
 cid=row['case_id'];prep_path=Path(row['prepared_input_report']['path']);p=load(prep_path);assert sha(prep_path)==row['prepared_input_report']['sha256'];assert p['case_id']==cid and p['xml_byte_identical_to_baseline'] and p['initial_bi4_byte_identical_to_baseline'] and p['initial_native_reference']['initial_native_verified']['passed'] and p['generated_particle_counts']=={'fixed':111708,'moving':0,'floating':0,'fluid':67500};assert p['expected_frames']==836 and p['physical_window_s']==[0,8.35] and p['save_interval_s']==.01
 assert .8<=p['nominal_pitch_multiplier']<=1.2 and .25<=p['transverse_amplitude_m_s2']<=.75;physical=p['physical_binding'];digest=hashlib.sha256(json.dumps(physical,sort_keys=True,separators=(',',':')).encode()).hexdigest();assert digest==p['physical_condition_sha256']==row['physical_condition_sha256'];assert digest not in unique;unique.add(digest)
 prefix=p['prepared_prefix'];xml=Path(prefix+'.xml');assert sha(xml)==p['xml_sha256']==row['generated_xml']['sha256'];assert p['bi4_sha256']==row['initial_bi4']['sha256']==p['initial_native_reference']['initial_native_verified']['native_initial_BI4_sha256'];assert row['forcing']['sha256']==p['forcing_sha256']
 md={}
 for x in template['input_files']:
  path=Path(x)
  if template['case_id'] in path.name or base_dir==path.parent:continue
  if path.suffix.lower() in {'.bi4','.csv','.dat'}:md[x]=template['input_sha256'][x]
  else:assert sha(path)==template['input_sha256'][x];md[x]=template['input_sha256'][x]
 for path in [source/'conditions'/(cid+'.json'),source/'owners'/(cid+'.json'),source/'requests'/(cid+'.json'),prep_path,xml,gate,cp_path,Path(__file__),template_path,review_path]:md[str(path)]=sha(path)
 md[prefix+'.bi4']=p['bi4_sha256'];md[p['forcing_path']]=p['forcing_sha256'];aid=f'root-stage1-f3-{cid.lower()}-next20-full836-native-visual-rectangle-root839';ap=D/'families/F3'/cid/aid;assert not ap.exists()
 q={k:v for k,v in template.items() if k not in ['command','input_files','input_sha256','source_owner','source_condition','source_request','actual_preparation_report','physical_binding']};q.update(case_id=cid,physical_case_id=p['physical_case_id'],physical_condition_sha256=digest,physical_binding=physical,attempt_id=aid,attempt_root=str(ap),command=[str(solver),'-mdbc_noslip:1',prefix,'{attempt_root}/solver_output','-tmax:8.35','-tout:0.01'],cwd=str(Path(prefix).parent),cpu_threads=2,omp_threads=2,estimated_storage_bytes=10*1024**3,root_domain_approval=True,root_visual_range_release=str(gate),root_solver_concurrency_cap=8,root_gpu_selection_profile='root_live_all_idle_uuid_leased_eight_solver_v2',root_dataset_inventory_profile='root_home_floor_no_legacy_dataset_walk_native_v1',source_owner=str(source/'owners'/(cid+'.json')),source_condition=str(source/'conditions'/(cid+'.json')),source_request=str(source/'requests'/(cid+'.json')),actual_preparation_report=ref(prep_path),nominal_pitch_multiplier=p['nominal_pitch_multiplier'],transverse_amplitude_m_s2=p['transverse_amplitude_m_s2'],production_approval='none',root_scope='own actual704 exact initial clone and forcing; released only by four actual full836 corner visual decisions; no precision certification',foreign_process_protection_required=True,shared_lease_required=True,input_files=sorted(md),input_sha256=md,source_scientific_digests_origin='registered704 producer metadata plus verified byte-identical parent native QA; no controller array reads or hashes');qp=O/'requests'/(cid+'-native-request.json');put(qp,q);qs.append(str(qp))
put(O/'actual-next20-native-enablement-review.json',{'requests':qs,'visual_range_release':ref(gate),'actual_source_preparation_receipt':template['actual_preparation_receipt'],'same_initial_particle_population_proven_by_registered_byte_identity':True,'own_forcing_digest_per_case':True,'maximum_parallel_native_jobs':7,'cpu_per_native_job':2,'independent_case_increment':0})
def run(qp):
 q=load(qp)
 while True:
  ledger=load(D/'runtime/resource-ledger.json');snap=rt.inventory();leased={load(p)['uuid'] for p in (D/'leases').glob('*.json')}
  if sum(x.get('cpu_threads',0) for x in ledger['reservations'])+2>64:time.sleep(3);continue
  try:gpu.choose_gpu(snap,leased,8192);break
  except RuntimeError:time.sleep(3)
 p=subprocess.run([str(L/'.venv/bin/python'),str(H/'root_stage1_native_home_floor_eight_solver_dispatch_230/launch.py'),qp],cwd=L,capture_output=True,text=True);rp=Path(q['attempt_root'])/'execution-receipt.json';r=load(rp) if rp.exists() else {};frames=len(list((Path(q['attempt_root'])/'solver_output/data').glob('Part_*.bi4')));passed=p.returncode==0 and (r.get('status'),r.get('returncode'))==('completed',0) and frames==836;out={'case_id':q['case_id'],'request':qp,'actual_receipt':str(rp),'status':r.get('status'),'returncode':r.get('returncode'),'launcher_returncode':p.returncode,'native_saved_frame_file_count':frames,'actual_full836_native_pass':passed,'independent_case_increment':0,'launcher_error':p.stderr[-1500:]};print(json.dumps(out),flush=True);return out
results=[run(qs[0])];failed=not results[0]['actual_full836_native_pass'];index=1
with ThreadPoolExecutor(max_workers=7) as pool:
 active={}
 while active or(index<len(qs) and not failed):
  while len(active)<7 and index<len(qs) and not failed:active[pool.submit(run,qs[index])]=qs[index];index+=1
  if not active:break
  done,_=wait(active,return_when=FIRST_COMPLETED)
  for f in done:
   active.pop(f);r=f.result();results.append(r);failed|=not r['actual_full836_native_pass'];put(O/'actual-progress.json',{'results':results,'pending_held':len(qs)-index,'independent_case_increment':0})
put(O/'controller-result.json',{'requested':20,'actual_full836_native_pass_count':sum(r['actual_full836_native_pass'] for r in results),'pending_held':len(qs)-index,'results':results,'independent_case_increment':0});raise SystemExit(1 if failed else 0)
'''
ast.parse(script);(O/'batch-controller.py').write_text(script);(O/'root-preparation-source.py').write_bytes(Path(__file__).read_bytes());(O/'controller-contract.json').write_text(json.dumps({'source_root':704,'registered_exact_initial_review_root':705,'case_count':20,'release_requires_four_actual836_corner_visual_decisions':True,'no_science_dispatch_from_renderer_status_alone':True,'native_dispatch_root':230,'shared_runtime_unmodified':True,'live_uuid_and_shared_lease_required':True,'cpu_per_job':2,'shared_CPU_reservation_cap':64,'maximum_parallel_jobs_after_first_pass':7,'Home_min_free_gib':500,'root_scientific_payload_reads_or_hashes':False,'independent_case_increment':0},indent=2)+'\n');assert not subprocess.check_output(['git','diff','--cached','--name-only'],cwd=R,text=True).strip();subprocess.run(['git','add','--',str(O.relative_to(R))],cwd=R,check=True);subprocess.run(['git','commit','-m','ds02: queue F3 next20 after actual four-corner visual range release'],cwd=R,check=True,stdout=subprocess.DEVNULL);commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()
with (O/'controller.log').open('ab') as log:p=subprocess.Popen([str(L/'.venv/bin/python'),str(O/'batch-controller.py')],cwd=L,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
f=(Path('/proc')/str(p.pid)/'stat').read_text().split(') ',1)[1].split();out={'pid':p.pid,'proc_start_ticks':f[19],'controller':str(O/'batch-controller.py'),'controller_sha256':hashlib.sha256((O/'batch-controller.py').read_bytes()).hexdigest(),'launch_commit':commit,'actual_launched_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()};(O/'controller-launch-process.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out))
