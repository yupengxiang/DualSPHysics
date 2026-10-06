from pathlib import Path
import json,hashlib,time,subprocess,fcntl,shutil,xml.etree.ElementTree as ET,sys
O=Path(__file__).parent;R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');P=Path('/home/jade/.codex/worktrees/ds-data-02-f3/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/root_followup_104_f3_next20_typed_xmf_render_source_v1');load=lambda p:json.loads(Path(p).read_text());sys.path.insert(0,str(L/'scripts'))
from ds_data02_direct_convert import _physical_condition_scope
SCI={'.h5','.hdf5','.bi4','.ibi4','.dat','.csv','.vtk','.vtu','.npy','.npz'}
def root(n):return next(H.glob(f'root*_{n}'))
def sha(p):
 p=Path(p);assert p.suffix.lower() not in SCI;return hashlib.sha256(p.read_bytes()).hexdigest()
def ref(p):return {'path':str(p),'sha256':sha(p)}
def put(p,d):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(d,indent=2)+'\n');t.replace(p)
remaining_ids={load(qp)['case_id'] for qp in (root(880)/'requests').glob('*request.json')};assert len(remaining_ids)==13;rows=[r for r in load(P/'metadata/source-index.json')['cases'] if r['case_id'] in remaining_ids];assert len(rows)==13;base=load(next((root(827)/'requests').glob('*request.json')));profile={k:v for k,v in base.items() if k.startswith('root_') or k=='resource_window'};exporter=P/'workers/export_xmf.py';done=set();results=[];partial=False
for row in rows:
 own=load(row['converter_owner']['path']);scope=_physical_condition_scope(own);assert hashlib.sha256(json.dumps(scope,sort_keys=True,separators=(',',':')).encode()).hexdigest()==row['physical_condition_sha256'] and scope['schema']=='ds-data-02.physical-binding.v1'
def launch(row,stage,cmd,md,binding,estimated):
 aid='root-stage1-f3-'+row['case_id'].lower()+'-actual839-full836-'+stage+'-root885';ap=D/'families/F3'/row['case_id']/aid
 if stage=='typed':binding={**binding,'trajectory_h5':str(ap/'trajectory.h5'),'conversion_report':str(ap/'conversion-report.json'),'typed_receipt':str(ap/'execution-receipt.json'),'source_original_disabled_binding':ref(row['typed']['binding']),'source_future_namespace_preserved_without_output_claim':True}
 bp=O/'bindings'/(row['case_id']+'-'+stage+'-actual-ready-binding.json');put(bp,binding);md={**md,str(bp):sha(bp)};aid='root-stage1-f3-'+row['case_id'].lower()+'-actual839-full836-'+stage+'-root885';ap=D/'families/F3'/row['case_id']/aid;assert not ap.exists();q={**profile,'schema':'ds02.runner-request.v2','family_id':'F3','case_id':row['case_id'],'physical_case_id':row['physical_case_id'],'physical_condition_sha256':row['physical_condition_sha256'],'attempt_id':aid,'attempt_root':str(ap),'kind':'cpu','cpu_task_kind':'conversion' if stage=='typed' else 'audit','cpu_threads':2,'max_wall_seconds':14400 if stage=='typed' else 1800,'estimated_storage_bytes':estimated,'launch_owner':'root','worktree_root':str(R),'cwd':str(L),'command':cmd,'input_files':sorted(md),'input_sha256':md,'binding':str(bp),'expected_frames':836,'expected_particles':179208,'expected_dimension':3,'disabled':False,'source_only':False,'launch':True,'launch_allowed':True,'execution_allowed':True,'root_review_required':False,'q_n_granted':False,'production_approval':'none','case_credit':0};qp=O/'requests'/(row['case_id']+'-'+stage+'-request.json');put(qp,q)
 with (D/'runtime/stage1-fullnative-conversion-dispatch.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  while True:
   l=load(D/'runtime/resource-ledger.json');storage=sum(x.get('new_storage_bytes',0) for x in l['reservations'])
   if sum(x.get('cpu_threads',0) for x in l['reservations'])+4<=64 and shutil.disk_usage('/home/jade').free-storage-estimated-16*1024**3>=l['limits']['home_min_free_bytes']:break
   time.sleep(3)
  p=subprocess.run([str(L/'.venv/bin/python'),str(root(142)/'launch.py'),str(qp)],cwd=L,capture_output=True,text=True)
 rp=ap/'execution-receipt.json';r=load(rp) if rp.exists() else {};out={'request':str(qp),'actual_receipt':str(rp),'status':r.get('status'),'returncode':r.get('returncode'),'launcher_returncode':p.returncode,'actual_completed0':p.returncode==0 and (r.get('status'),r.get('returncode'))==('completed',0),'launcher_error':p.stderr[-1500:]};print(json.dumps(out),flush=True);return ap,out
while len(done)<13 and not partial:
 ready=[]
 for row in rows:
  if row['case_id'] in done:continue
  newqp=root(884)/'requests'/(row['case_id']+'-native-request.json');np=newqp if newqp.exists() else next(p for p in (root(839)/'requests').glob('*native-request.json') if load(p)['case_id']==row['case_id']);nq=load(np);nr=Path(nq['attempt_root'])/'execution-receipt.json'
  if not nr.exists():continue
  r=load(nr)
  if (r['status'],r.get('returncode'))==('completed',0):ready.append((row,np,nq,nr))
  elif r['status'] in ['failed','terminated','aborted']:
   if r.get('pid') is None and r.get('returncode') is None and r.get('error')=='RuntimeError: shared CPU thread reservation exceeded' and np.parent==root(839)/'requests':
    put(O/'original839-no-worker-capacity-refusal-preserved.json',{'receipt':ref(nr),'successor880_waited':True,'no_science_result_reinterpreted':True});continue
   put(O/'upstream-failure-hold.json',{'receipt':ref(nr),'no_restart':True});partial=True
 if partial:break
 if not ready:
  terminal=root(884)/'controller-result.json'
  if terminal.exists():partial=True;break
  c=load(root(884)/'controller-launch-process.json');p=Path('/proc')/str(c['pid']);assert p.exists(),'Own native839 missing without terminal evidence';f=(p/'stat').read_text().split(') ',1)[1].split();assert f[0]!='Z' and f[19]==c['proc_start_ticks'];time.sleep(3);continue
 row,np,nq,nr=sorted(ready,key=lambda x:x[0]['case_id'])[0];cid=row['case_id'];original=root(839)/'requests'/(cid+'-native-request.json');assert sha(original)==row['native839']['request_sha256'];
 assert nq['physical_condition_sha256']==row['physical_condition_sha256'] and nq['physical_case_id']==row['physical_case_id'] and nq['physical_binding']==load(row['converter_owner']['path'])['physical_binding'];assert len(list((nr.parent/'solver_output/data').glob('Part_*.bi4')))==836;sourceq=load(row['typed']['request']);md={}
 for raw,digest in sourceq['input_sha256'].items():assert sha(raw)==digest;md[raw]=digest
 xml=Path(sourceq['command'][sourceq['command'].index('--generated-xml')+1]);assert sha(xml)==row['root704_prepared']['xml_sha256'];paths=[np,nr,xml,Path(row['typed']['request']),Path(row['typed']['binding']),P/'metadata/source-index.json',root(868)/'actual-source-adoption-review.json',root(705)/'actual-new24-exact-initial-forcing-independent-review.json',Path(__file__),O/'controller-contract.json',root(142)/'launch.py',root(142)/'root_home_floor_inventory_policy.py']
 # Source839 itself binds exact per-case forcing and initialized704 BI4 via producer-attested digests.
 for key in ['--decoder','--partvtk','--gencase-receipt']:paths.append(Path(sourceq['command'][sourceq['command'].index(key)+1]))
 md.update({str(p):sha(p) for p in paths});b={**load(row['typed']['binding']),'source_only':False,'jobs_started_by_root_registered_runner':True,'native_receipt_sha256':sha(nr),'own_native_request':ref(np),'exact_initial_clone_evidence':nq['initial_QA_exact_clone_evidence'],'own_704_prepared_source':row['root704_prepared'],'future_output_hashes_not_claimed':True};ta,to=launch(row,'typed',sourceq['command'],md,b,32*1024**3);cp=ta/'conversion-report.json';t=load(cp) if cp.exists() else {};passed=to['actual_completed0'] and t.get('frames')==836 and t.get('particles')==179208 and t['solver_dimension']['solver_dimension']==3 and t['partvtk_validation']['all_passed'] and t['hash_scopes']['physical_condition_sha256']==row['physical_condition_sha256'] and t['hash_scopes']['physical_condition']['schema']=='ds-data-02.physical-binding.v1' and t['time_evidence']['last_s']>=8.35;out={'case_id':cid,'typed':to,'xmf':None,'actual_full836_typed_XMF_pass':False,'case_credit':0}
 if passed:
  tr=ta/'execution-receipt.json';h5=Path(t['output_hdf5']);assert h5==ta/'trajectory.h5';xb={**load(row['xmf']['binding']),'source_only':False,'trajectory_h5':str(h5),'trajectory_h5_sha256':t['output_sha256'],'typed_receipt':str(tr),'typed_receipt_sha256':sha(tr),'conversion_report':str(cp),'conversion_report_sha256':sha(cp),'native_receipt':str(nr),'native_receipt_sha256':sha(nr),'actual_converter_scope_sha256':row['physical_condition_sha256'],'actual_converter_scope_status':'actual producer confirmed true v1; no legacy realignment','bound_metadata_sha256':{str(p):sha(p) for p in [np,nr,tr,cp,Path(row['converter_owner']['path'])]}};xm={**md,**{str(p):sha(p) for p in [tr,cp,exporter]},str(h5):t['output_sha256']};xa,xo=launch(row,'xmf',[str(L/'.venv/bin/python'),str(exporter),'--binding',str(O/'bindings'/(cid+'-xmf-actual-ready-binding.json')),'--output-dir','{attempt_root}/xdmf'],xm,xb,1024**3);mp=xa/'xdmf/manifest.json';m=load(mp) if mp.exists() else {};xp=xo['actual_completed0'] and m.get('frames')==836 and m.get('particles')==179208 and m.get('physical_condition_sha256')==row['physical_condition_sha256'] and m.get('source_h5_sha256')==t['output_sha256']
  if xp:
   xf=Path(m['xdmf']);gs=ET.parse(xf).getroot().findall('.//Grid[@GridType="Uniform"]');xp=sha(xf)==m['xdmf_sha256'] and len(gs)==836 and all(g.find('Geometry/DataItem').get('Dimensions')==g.find('Attribute[@Name="velocity"]/DataItem').get('Dimensions')=='179208 3' for g in gs)
  xo.update(actual_manifest=str(mp));out['xmf']=xo;out['actual_full836_typed_XMF_pass']=xp
 results.append(out);done.add(cid);partial=not out['actual_full836_typed_XMF_pass'];put(O/'actual-progress.json',{'results':results,'remaining':13-len(done),'case_credit':0})
put(O/'controller-result.json',{'requested':13,'actual_full836_typed_XMF_pass_count':sum(x['actual_full836_typed_XMF_pass'] for x in results),'pending_held':13-len(done),'results':results,'case_credit':0});raise SystemExit(0 if len(done)==13 and not partial else 1)
