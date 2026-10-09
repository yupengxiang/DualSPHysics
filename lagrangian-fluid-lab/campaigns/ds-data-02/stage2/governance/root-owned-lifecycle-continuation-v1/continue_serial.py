#!/usr/bin/env python3
"""Root-owned serial admission, independent metadata verification and accounting.
Scientific H5 processing stays in the immutable delegated batch worker. Each
batch gets a fresh exact CURRENT continuation join, one atomic parent resource
reservation, and independent terminal proof before another batch can launch.
This does not grant physical qualification, reset limits, or complete the goal.
"""
from pathlib import Path
import json,hashlib,subprocess,sys,os,time,datetime,collections
HERE=Path(__file__).resolve().parent;LAB=HERE.parents[4];S=LAB/'campaigns/ds-data-02/stage2';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');V='/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python';sys.path.insert(0,str(LAB/'scripts'))
from ds_data02_runtime_v8 import _light_validate
PAYLOAD={'.h5','.hdf5','.bi4','.ibi4','.obi4','.vtk','.jsonl'}
def sha(p):
 p=Path(p);assert p.suffix.lower() not in PAYLOAD and p.stat().st_size<=10485760;return hashlib.sha256(p.read_bytes()).hexdigest()
def load(p):
 p=Path(p);assert p.suffix.lower() not in PAYLOAD;return json.loads(p.read_text())
def ref(p):return {'path':str(p),'sha256':sha(p)}
def new(p,v):
 p=Path(p);assert not p.exists();p.write_text(json.dumps(v,indent=2,ensure_ascii=False)+'\n')
def state(unit):
 raw=subprocess.check_output(['systemctl','--user','show',unit,'-p','SubState','-p','MainPID','-p','Result','-p','ExecMainStatus','-p','CPUUsageNSec'],text=True);return dict(z.split('=',1) for z in raw.splitlines())
def plan(registry,out):
 r=load(registry);subprocess.run([V,'-B',str(LAB/'scripts/ds_data02_stage2_typed_lifecycle_continuation_plan_v4.py'),'prepare','--current',r['current']['path'],'--audit-verification',r['audit']['path'],'--evidence-registry',str(registry),'--expected-current-sha256',r['current']['sha256'],'--expected-audit-sha256',r['audit']['sha256'],'--output',str(out)],check=True)
def checkpoint(num,registry,planp,request,unit,terminal_proof=None):
 l=load(D/'runtime/resource-ledger.json');out=S/f'checkpoints/ROOT{num}_LIFECYCLE_SERIAL_{"ACTUAL" if terminal_proof else "PENDING"}_FULL_GOAL_CONTINUATION_V1.json';v={'schema':'ds02.stage2.root-lifecycle-serial-governance-checkpoint.v1','utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'goal_status':'ACTIVE_FULL_SEVEN_ITEMS','goal_complete':False,'supersedes_full_checkpoint':ref(S/'checkpoints/ROOT280_PENDING_ACTUAL123_CAUSE94_JOIN47_F1_PAIR_ACTUAL_FULL_GOAL_CONTINUATION_V1.json'),'current_registry':ref(registry),'strict_current_plan':ref(planp),'coverage':load(planp)['coverage'],'batch_request':ref(request),'unit':unit,'unit_state_at_snapshot':state(unit),'terminal_proof':ref(terminal_proof) if terminal_proof else None,'pending_credit':0,'root_payload_content_read':False,'native_cause_scope':ref(S/'checkpoints/ORIGINAL118_NATIVE_CAUSE_AFTER_ROOT268_ACTUAL_OVERLAY_V10.json'),'native_cause_credit':94,'native_cause_unknown':24,'native_typed_join_credit':47,'Q_I_Q_N_Q_E':'UNKNOWN','remaining_full_goal_tasks':['original118 native cause joins and physical fate UNKNOWN recovery','14 sentinels scientific reference terminal studies including actual F1 matched pair native observer','material provenance/arrival/residence/flux labels with error and censoring','physical-condition leakage-safe splits and seven family cards','portable internal product independent replay and license/access','bounded conditional mechanism coverage expansion'],'resources':{'CPU_core_hours':sum(x.get('cpu_core_seconds',0) for x in l['charges'])/3600,'GPU_hours':sum(x.get('gpu_seconds',0) for x in l['charges'])/3600,'attempt_counts':dict(collections.Counter(x['kind'] for x in l['attempts'])),'reservations':l['reservations'],'limits':l['limits'],'deadline_utc':l['deadline_utc'],'free_bytes':{p:os.statvfs(p).f_bavail*os.statvfs(p).f_frsize for p in ['/home/jade','/var/tmp']}}};new(out,v)
 nextp=S/'NEXT_READY_TASKS.md';nextp.write_text('最新串行实际恢复检查点：`'+str(out)+'`（SHA256 '+sha(out)+'）。完整七项目标 ACTIVE；覆盖以该检查点绑定的实际registry/plan为准，运行批次不记完成；科学Q仍UNKNOWN。每批终态必须完成独立核验、完整CPU重复结账、release和unitdead，才调度下一批。\n\n'+nextp.read_text());print(json.dumps({'event':'CHECKPOINT','namespace':num,'path':str(out),'coverage':v['coverage'],'goal_complete':False}),flush=True)
def close(num,family,request,old_registry):
 unit=f'ds02-typed-lifecycle-batch-v1-{family.lower()}-root-{num}'
 while True:
  u=state(unit)
  if u['SubState']!='running':break
  print(json.dumps({'event':'RUNNING','namespace':num,'CPU_core_seconds':int(u['CPUUsageNSec'])/1e9}),flush=True);time.sleep(30)
 assert u['SubState']=='exited' and u['MainPID']=='0' and u['Result']=='success',u
 subprocess.run([V,'-B',str(HERE/'verify_actual_lifecycle.py'),str(num),family],cwd=LAB,check=True)
 proof=S/f'checkpoints/TYPED_LIFECYCLE_BATCH_{family}_ACTUAL_ROOT_VERIFICATION_{num}.json';p=load(proof);q=load(request);assert p['parent_reservation_released'] and p['repeat_fee_idempotent'];assert not p['failed_cases'];assert len(p['case_verifications'])==len(q['physical_case_ids']);assert state(unit)['SubState']=='dead';assert not load(D/'runtime/resource-ledger.json')['reservations']
 r=load(old_registry);z=next(x for x in r['producers'] if x['producer_id']==f'ROOT{num}');assert z['status']=='RUNNING_NO_CREDIT';z['status']='COMPLETED';z['proof']=ref(proof);r['supersedes_registry']=ref(old_registry);registry=S/f'requests/typed-lifecycle-evidence-registry-v4-after-root{num}-001.json';new(registry,r);pp=S/f'checkpoints/CURRENT336_TYPED_LIFECYCLE_AFTER_ROOT{num}_V4.json';plan(registry,pp);checkpoint(num,registry,pp,request,unit,proof);return registry,pp

def admit(num,source,old_registry,old_plan):
 src=load(source);family=src['family_id'];assert family in [f'F{i}' for i in range(1,8)];assert src['cpu_threads']==1 and src['max_memory_bytes']==4294967296 and src['max_wall_seconds']==3600
 rows=load(old_plan)['case_records'];selected=set(src['physical_case_ids']);assert 0<len(selected)<=8;assert selected<={x['physical_case_id'] for x in rows if x['status']=='UNSCHEDULED_EXACT_CURRENT_AUDIT'};assert not selected&{x['physical_case_id'] for x in rows if x['status']=='ACTUAL_SAVED_MASK_COMPLETED'}
 # Source requests keep their frozen discovery plan; fresh root sidecar binds actual current eligibility.
 q=src;q['command'].insert(1,'-B');q.update(cwd=str(LAB),shared_runtime_version='v8',kind='cpu',cpu_task_kind='audit',launch_allowed=True,execution_allowed=True,qualification={'QI':'UNKNOWN','QN':'UNKNOWN','QE':'UNKNOWN'});assert q['estimated_deferred_read_bytes']==3*q['estimated_deferred_source_bytes'];q['estimated_hdf5_read_bytes']=q['estimated_deferred_read_bytes'];q['root_latest_actual_nonoverlap']={'plan':ref(old_plan),'registry':ref(old_registry),'selected_count':len(selected),'strict_selected_all_unscheduled':True,'actual_count':load(old_plan)['coverage']['actual_saved_mask_cases'],'source_only_request_does_not_grant_actual_credit':True}
 assert 0<q['estimated_storage_bytes']<6*1024**3
 context={'__name__':'root_forward','__file__':str(HERE/'root_forward_metadata.py')};exec((HERE/'root_forward_metadata.py').read_text(),context);context['sha']=sha
 extra=[old_plan,old_registry,S/'checkpoints/ORIGINAL118_NATIVE_CAUSE_AFTER_ROOT268_ACTUAL_OVERLAY_V10.json']+list(HERE.glob('*.py'))
 name=f'typed-lifecycle-batch-v1-{family.lower()}-root-forward-{num}-001.json';context['write'](q,source,name,extra=extra);request=S/'requests'/name;q=load(request);_light_validate(q,data_root=D)
 for path,h in q['input_sha256'].items():assert sha(path)==h
 total=0
 for z in q['deferred_input_records']:
  p=Path(z['path']);assert p.suffix.lower() in {'.h5','.hdf5'} and p.stat().st_size==z['bytes'] and len(z['sha256'])==64 and str(p) not in q['input_files'];total+=z['bytes']
 assert total==q['estimated_deferred_source_bytes'];l=load(D/'runtime/resource-ledger.json');assert not l['reservations'];assert datetime.datetime.now(datetime.timezone.utc)<datetime.datetime.fromisoformat(l['deadline_utc']);assert sum(x.get('cpu_core_seconds',0) for x in l['charges'])+q['max_wall_seconds']<l['limits']['cpu_core_seconds'];assert os.statvfs('/home/jade').f_bavail*os.statvfs('/home/jade').f_frsize-q['estimated_storage_bytes']>=l['limits']['home_min_free_bytes'];assert not (D/'families'/family/q['case_id']/q['attempt_id']).exists()
 code='import sys,os,json;sys.path.insert(0,'+repr(str(LAB/'scripts'))+');from ds_data02_runtime_v8 import run_request;r=run_request('+repr(str(request))+',data_root='+repr(str(D))+',parent_pid=os.getppid());print(json.dumps(r));raise SystemExit(0 if r["status"]=="completed" else 1)';unit=f'ds02-typed-lifecycle-batch-v1-{family.lower()}-root-{num}';cmd=['systemd-run','--user','--unit='+unit,'--property=Type=exec','--property=RemainAfterExit=yes','--property=RuntimeMaxSec=3630','--property=TimeoutStopSec=45','--property=KillMode=mixed','--property=CPUAccounting=yes','--property=MemoryAccounting=yes','--property=MemoryMax=4294967296']+['--setenv='+k+'=1' for k in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS']]+[V,'-B','-I','-c',code];subprocess.run(cmd,check=True)
 r=load(old_registry);r['supersedes_registry']=ref(old_registry);r['producers'].append({'producer_id':f'ROOT{num}','kind':'typed_lifecycle_batch','status':'RUNNING_NO_CREDIT','case_ids':q['physical_case_ids'],'request':ref(request),'manifest':q['manifest_contract']});registry=S/f'requests/typed-lifecycle-evidence-registry-v4-root{num}-pending-001.json';new(registry,r);pp=S/f'checkpoints/CURRENT336_TYPED_LIFECYCLE_ROOT{num}_PENDING_V4.json';plan(registry,pp);checkpoint(num,registry,pp,request,unit);return close(num,family,request,registry)

def main():
 assert LAB.name=='lagrangian-fluid-lab',str(LAB)
 registry,pp=close(280,'F4',S/'requests/typed-lifecycle-batch-v1-f4-root-forward-280-001.json',S/'requests/typed-lifecycle-evidence-registry-v4-root280-pending-001.json')
 registry,pp=admit(281,S/'requests/root281-f6-lifecycle-prepared-001/root281-request.json',registry,pp)
 queuep=S/'requests/root282-root307-lifecycle-source-queue-001/root282-root307-source-queue.json';assert sha(queuep)=='a3d1b8e864d886633d470fe1b456baad433190ba853bef0be73afbff1d897f14';queue=load(queuep);assert queue['batch_count']==26
 for b in queue['batches']:
  source=Path(b['request']);assert sha(source)==b['request_sha256'];registry,pp=admit(int(b['namespace'][4:]),source,registry,pp)
 print(json.dumps({'event':'SERIAL_QUEUE_TERMINAL','coverage':load(pp)['coverage'],'registry':ref(registry),'plan':ref(pp),'goal_complete':False}),flush=True)
if __name__=='__main__':main()
