from pathlib import Path
import json,ast,subprocess,hashlib,datetime
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';O=H/'root_stage1_F2_F5_actual827832855865_full_event_render_after860_CPU_capacity_866';O.mkdir()
s=r'''from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
import json,hashlib,subprocess,time,fcntl,shutil,xml.etree.ElementTree as ET
O=Path(__file__).parent;R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');load=lambda p:json.loads(Path(p).read_text())
def root(n):return next(H.glob(f'root*_{n}'))
SCI={'.h5','.hdf5','.bi4','.ibi4','.csv','.dat','.vtk','.vtu','.npy','.npz'}
def sha(p):
 p=Path(p);assert p.suffix.lower() not in SCI;return hashlib.sha256(p.read_bytes()).hexdigest()
def put(p,d):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n');t.replace(p)
def ref(p):return {'path':str(p),'sha256':sha(p)}
def live(n):
 c=load(root(n)/'controller-launch-process.json');p=Path('/proc')/str(c['pid'])
 if not p.exists():return False
 f=(p/'stat').read_text().split(') ',1)[1].split();return f[0]!='Z' and f[19]==c['proc_start_ticks'] and c['controller'].encode() in (p/'cmdline').read_bytes()
# Priority handoff preserves already-authorized F4 then F6 queue rather than competing for renderer slots.
gate=root(860)/'controller-result.json'
while not gate.exists():
 assert live(860),'Own F6 predecessor missing without terminal proof; no restart or substitute'
 time.sleep(5)
g=load(gate);assert g['completed0']==g['actual_full241_render_pass_count']==24 and g['pending_held']==0
for row in g['results']:
 r=load(row['actual_receipt']);assert (r['status'],r.get('returncode'))==('completed',0)
put(O/'actual-F6-render-drain-gate.json',{'source':ref(gate),'actual24_completed0':True,'case_credit':0});base=load(next(root(856).glob('*render-request.json')));profile={k:v for k,v in base.items() if k.startswith('root_') or k=='resource_window'};worker=root(23)/'render.py';assert sha(worker)=='5e78f7b92ad7c6f1d15902e3ccacc9099affb04b1b992a42f540eb88241bde66';rows=[];done=set();failed_sources=set();claimed=set();active={};source_sizes={827:24,832:1,855:9,865:34};terminal_checked=set()
def dispatch(qp,q):
 with (D/'runtime/stage1-fullnative-render-registration.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  while True:
   ledger=load(D/'runtime/resource-ledger.json');cpu=sum(x.get('cpu_threads',0) for x in ledger['reservations']);storage=sum(x.get('new_storage_bytes',0) for x in ledger['reservations']);renders=sum(x.get('cpu_threads',0)==24 for x in ledger['reservations'])
   if cpu+24+2<=64 and renders<2 and shutil.disk_usage('/home/jade').free-storage-q['estimated_storage_bytes']-16*1024**3>=ledger['limits']['home_min_free_bytes']:break
   time.sleep(3)
  p=subprocess.Popen([str(L/'.venv/bin/python'),str(root(142)/'launch.py'),str(qp)],cwd=L,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE);rp=Path(q['attempt_root'])/'execution-receipt.json'
  while p.poll() is None:
   if rp.exists() and load(rp)['status']=='running':break
   time.sleep(.2)
 stdout,stderr=p.communicate();return subprocess.CompletedProcess(p.args,p.returncode,stdout,stderr)
def run(n,xqp):
 cid=None
 try:
  xq=load(xqp);cid=xq['case_id'];xa=Path(xq['attempt_root']);xr=xa/'execution-receipt.json';rr=load(xr);assert (rr['status'],rr.get('returncode'))==('completed',0) and rr['request_sha256']==sha(xqp);mp=xa/'xdmf/manifest.json';m=load(mp);family=m['family_id'];assert family in ['F2','F5'] and family==xq['family_id'] and cid==m['case_id'];frames,N,last=(401,418104,4) if family=='F2' else (801,194427,16);cp=Path(m['conversion_report']);c=load(cp);tr=Path(m['typed_receipt']);nr=Path(m['native_receipt']);assert all((load(p)['status'],load(p).get('returncode'))==('completed',0) for p in [tr,nr]);assert c['conversion_status']=='completed' and c['frames']==frames and c['particles']==N and c['solver_dimension']['solver_dimension']==3 and c['partvtk_validation']['all_passed'] and c['time_evidence']['last_s']>=last;assert m['frames']==frames and m['particles']==N and m['source_h5_read_only'] and m['source_h5_sha256']==c['output_sha256'] and m['trajectory_h5']==c['output_hdf5'];legacy=c['hash_scopes']['physical_condition_sha256'];canonical=m['canonical_source_physical_condition_sha256'] if family=='F2' else m['physical_condition_sha256'];assert (m['physical_condition_sha256'] if family=='F2' else m['source_h5_physical_condition_sha256'])==legacy;assert canonical!=legacy and xq['physical_condition_sha256']==m['physical_condition_sha256'];xf=Path(m['xdmf']);assert sha(xf)==m['xdmf_sha256'];gs=ET.parse(xf).getroot().findall('.//Grid[@GridType="Uniform"]');assert len(gs)==frames and all(g.find('Geometry/DataItem').get('Dimensions')==g.find('Attribute[@Name="velocity"]/DataItem').get('Dimensions')==f'{N} 3' for g in gs);bed=[]
  if family=='F5':
   bqp=xqp.with_name(xqp.name.replace('-xmf-request.json','-bed-request.json'));bq=load(bqp);br=Path(bq['attempt_root'])/'execution-receipt.json';brr=load(br);assert (brr['status'],brr.get('returncode'))==('completed',0) and brr['request_sha256']==sha(bqp);bp=Path(bq['attempt_root'])/'audit-output/c082s1-full-event-bed-footprint-audit.json';b=load(bp);assert len(b['frame_reports'])==801 and b['physical_condition_sha256']==canonical and b['source_h5_physical_condition_sha256']==legacy;bed=[bqp,br,bp];assert bq['physical_case_id']==m['physical_case_id']
  proof={'family_id':family,'case_id':cid,'physical_case_id':m['physical_case_id'],'source_consumer':n,'actual_xmf_request':ref(xqp),'actual_xmf_receipt':ref(xr),'actual_manifest':ref(mp),'actual_conversion_report':ref(cp),'actual_typed_receipt':ref(tr),'actual_native_receipt':ref(nr),'frames':frames,'particles':N,'actual_N3_grid_count':len(gs),'canonical_source_physical_condition_sha256':canonical,'actual_converter_legacy_scope_sha256':legacy,'scope_equality_not_claimed':True,'bed_evidence':[ref(p) for p in bed],'bed_diagnostics_preserved_without_numeric_precision_approval':bool(bed),'no_scientific_payload_read_or_hash_by_root':True,'case_credit':0};pp=O/'bindings'/(m['physical_case_id']+'-actual-full-event-render-proof.json');put(pp,proof);paths=[xqp,xr,mp,xf,cp,tr,nr,pp,*bed,Path(__file__),O/'controller-contract.json',O/'actual-F6-render-drain-gate.json',gate,worker,L/'.venv/bin/python',L/'scripts/ds_data02_runtime_v2.py',L/'scripts/ds_data02_strict_dispatch_v1.py',root(142)/'launch.py',root(142)/'root_home_floor_inventory_policy.py',next(H.glob('root*064'))/'resource-window-approval.json',Path('/home/jade/ParaView-6.1.1-MPI-Linux-Python3.12-x86_64/bin/pvpython'),Path('/usr/bin/env'),Path('/usr/share/glvnd/egl_vendor.d/50_mesa.json')];xb=Path(xq['command'][xq['command'].index('--binding')+1]);paths.append(xb);md={str(p):sha(p) for p in paths};md[m['trajectory_h5']]=c['output_sha256'];aid='root-stage1-'+family.lower()+'-'+m['physical_case_id'].lower()+'-actual'+str(n)+'-full'+str(frames)+'-render-root866';ap=D/'families'/family/cid/aid;assert not ap.exists();cmd=list(base['command']);cmd[cmd.index('--manifest')+1]=str(mp);cmd[cmd.index('--output-dir')+1]='{attempt_root}/render';assert cmd[cmd.index('--force-offscreen-rendering')+1]==str(worker);q={**profile,'schema':'ds02.runner-request.v2','family_id':family,'case_id':cid,'physical_case_id':m['physical_case_id'],'physical_condition_sha256':canonical,'actual_converter_legacy_scope_sha256':legacy,'attempt_id':aid,'attempt_root':str(ap),'kind':'cpu','cpu_task_kind':'audit','cpu_threads':24,'max_wall_seconds':14400,'estimated_storage_bytes':base['estimated_storage_bytes'],'launch_owner':'root','worktree_root':str(R),'cwd':str(L),'command':cmd,'input_files':sorted(md),'input_sha256':md,'manifest':str(mp),'actual_renderer_binding':str(pp),'disabled':False,'source_only':False,'launch':True,'launch_allowed':True,'execution_allowed':True,'root_review_required':False,'q_n_granted':False,'production_approval':'none','independent_case_count_increment':0};qp=O/'requests'/(m['physical_case_id']+'-render-request.json');put(qp,q);p=dispatch(qp,q);rp=ap/'execution-receipt.json';r=load(rp) if rp.exists() else {};passed=False
  if (r.get('status'),r.get('returncode'))==('completed',0):
   v=load(ap/'render/paraview-full-animation-report.json');passed=v['frames']==v['source_frames']==frames and v['all_frames_rendered'] and v['native_identity_axis_preserved'] and v['actual_times_preserved_exactly'] and v['nonfinite_active_states']==0 and len(v['outputs']['contact_sheets'])==(frames+23)//24
  return {'source_consumer':n,'case_id':cid,'physical_case_id':m['physical_case_id'],'request':str(qp),'actual_receipt':str(rp),'status':r.get('status'),'returncode':r.get('returncode'),'launcher_returncode':p.returncode,'actual_full_event_render_pass':passed,'launcher_error':p.stderr[-1500:],'case_credit':0}
 except Exception as e:return {'source_consumer':n,'case_id':cid,'status':'controller_preflight_failed','returncode':None,'actual_full_event_render_pass':False,'error':str(e),'case_credit':0}
def ready_items():
 ready=[]
 for n,expected in source_sizes.items():
  if n in failed_sources:continue
  parent=root(n)
  for qp in (parent/'requests').glob('*-xmf-request.json'):
   q=load(qp);key=(n,q['physical_case_id']);rp=Path(q['attempt_root'])/'execution-receipt.json'
   if key in claimed or not rp.exists():continue
   r=load(rp)
   if (r['status'],r.get('returncode'))!=('completed',0):continue
   if n!=827:
    bp=qp.with_name(qp.name.replace('-xmf-request.json','-bed-request.json'))
    if not bp.exists():continue
    bq=load(bp);br=Path(bq['attempt_root'])/'execution-receipt.json'
    if not br.exists() or (load(br)['status'],load(br).get('returncode'))!=('completed',0):continue
   ready.append((n,qp,key))
  terminal=parent/'controller-result.json'
  if terminal.exists() and n not in terminal_checked:
   terminal_checked.add(n);put(O/'upstream-terminal-observations'/f'{n}.json',{'terminal':ref(terminal),'original_result_preserved':True,'no_partial_batch_completion_claim':True})
  elif not terminal.exists():assert live(n),'Owned upstream handle missing without terminal result'
 return sorted(ready,key=lambda x:(x[0],x[1].name))
with ThreadPoolExecutor(max_workers=2) as pool:
 while True:
  for n,qp,key in ready_items():
   if len(active)==2:break
   claimed.add(key);active[pool.submit(run,n,qp)]=key
  if active:
   finished,_=wait(active,timeout=3,return_when=FIRST_COMPLETED)
   for f in finished:
    key=active.pop(f);row=f.result();rows.append(row);done.add(key);print(json.dumps(row),flush=True)
    if not row['actual_full_event_render_pass']:failed_sources.add(key[0])
    put(O/'actual-progress.json',{'requested_max':68,'actual_full_event_render_pass_count':sum(x['actual_full_event_render_pass'] for x in rows),'results':rows,'failed_sources_held':sorted(failed_sources),'case_credit':0})
  elif all(n in terminal_checked or n in failed_sources for n in source_sizes):break
  else:time.sleep(3)
put(O/'controller-result.json',{'requested_max':68,'actual_full_event_render_pass_count':sum(x['actual_full_event_render_pass'] for x in rows),'pending_held_or_upstream_incomplete':68-len(rows),'failed_sources_held':sorted(failed_sources),'results':rows,'case_credit':0});raise SystemExit(0 if len(rows)==68 and not failed_sources else 1)
'''
ast.parse(s);(O/'batch-controller.py').write_text(s);(O/'controller-contract.json').write_text(json.dumps({'sources':{'827':'F2 new24 actual full401 XMF','832':'F5 old first actual801 XMF+bed only','855':'F5 remaining9 actual801 XMF+bed','865':'F5 next34 actual801 XMF+bed'},'requested_max':68,'predecessor860_actual24_completed0_required':True,'unchanged_root023_renderer_sha256':'5e78f7b92ad7c6f1d15902e3ccacc9099affb04b1b992a42f540eb88241bde66','atomic_registration_lock_shared_with_856_860':True,'global_render_cap':2,'reserved_CPU_threads':24,'actual_thread_env':2,'Home_floor_GiB':500,'CPU_reservation_cap':64,'source_canonical_and_actual_legacy_hashes_distinct':True,'future_input_hashes_only_bound_after_own_actual_producers_completed0':True,'scientific_payload_reads_or_hashes_by_root':False,'numerical_precision_not_accepted':True,'full_window_visual_review_by_children_still_required':True,'case_credit':0},indent=2)+'\n');(O/'root-preparation-source.py').write_bytes(Path(__file__).read_bytes());assert not subprocess.check_output(['git','diff','--cached','--name-only'],cwd=R,text=True).strip();subprocess.run(['git','add','--',str(O.relative_to(R))],cwd=R,check=True);subprocess.run(['git','commit','-m','ds02: queue F2 and F5 full-event renders after actual F6 drain'],cwd=R,check=True,stdout=subprocess.DEVNULL);commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()
with (O/'controller.log').open('ab') as log:p=subprocess.Popen([str(L/'.venv/bin/python'),str(O/'batch-controller.py')],cwd=L,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
f=(Path('/proc')/str(p.pid)/'stat').read_text().split(') ',1)[1].split();out={'pid':p.pid,'proc_start_ticks':f[19],'controller':str(O/'batch-controller.py'),'controller_sha256':hashlib.sha256((O/'batch-controller.py').read_bytes()).hexdigest(),'launch_commit':commit,'actual_launched_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()};(O/'controller-launch-process.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out))
