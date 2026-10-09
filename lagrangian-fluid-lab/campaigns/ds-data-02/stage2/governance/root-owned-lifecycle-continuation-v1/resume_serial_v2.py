#!/usr/bin/env python3
"""Resume the root-owned queue from an explicitly SHA-bound checkpoint.

Use only after the prior orchestrator has exited. This preserves V1 and all
consumed requests. One already-running systemd batch may be adopted; completed
case selections are rejected by the unchanged V1 admission guard. No arrays
are read here. A checkpoint, queue source and live parent limits are required.
"""
from pathlib import Path
import argparse,importlib.util,subprocess,os,json
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('root_serial_governance_v1',HERE/'continue_serial.py');V1=importlib.util.module_from_spec(spec);spec.loader.exec_module(V1)

def main():
 p=argparse.ArgumentParser();p.add_argument('--checkpoint',type=Path,required=True);p.add_argument('--checkpoint-sha256',required=True);args=p.parse_args();cp=args.checkpoint.resolve();assert cp.is_relative_to(V1.S/'checkpoints') and V1.sha(cp)==args.checkpoint_sha256;c=V1.load(cp);assert c['goal_status']=='ACTIVE_FULL_SEVEN_ITEMS' and c['goal_complete'] is False
 # Avoid two monitor/admission processes scheduling the same serial queue.
 me=os.getpid();processes=subprocess.check_output(['ps','-eo','pid,args'],text=True)
 for row in processes.splitlines():
  parts=row.strip().split(None,1)
  if len(parts)!=2 or not parts[0].isdigit():continue
  pid=int(parts[0]);command=parts[1]
  if pid!=me and command.startswith((V1.V,'python3 ','/usr/bin/python3')) and (str(HERE/'continue_serial.py') in command or str(Path(__file__).resolve()) in command):raise RuntimeError('another root queue orchestrator is still active')
 regref=c['current_registry'];planref=c['strict_current_plan'];registry=Path(regref['path']);plan=Path(planref['path']);assert V1.sha(registry)==regref['sha256'] and V1.sha(plan)==planref['sha256'];r=V1.load(registry);assert r['current']['sha256']=='df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b';assert V1.sha(r['current']['path'])==r['current']['sha256'];assert V1.sha(r['audit']['path'])==r['audit']['sha256'];running=[z for z in r['producers'] if z['status']=='RUNNING_NO_CREDIT'];assert len(running)<=1
 if running:
  z=running[0];num=int(z['producer_id'][4:]);qref=z['request'];qpath=Path(qref['path']);assert V1.sha(qpath)==qref['sha256'];q=V1.load(qpath);family=q['family_id'];proof=V1.S/f'checkpoints/TYPED_LIFECYCLE_BATCH_{family}_ACTUAL_ROOT_VERIFICATION_{num}.json';assert not proof.exists(),'terminal proof already exists: finalize existing immutable registry manually before resume';registry,plan=V1.close(num,family,qpath,registry)
 # All subsequent selections are compared to this freshly actual registry.
 remaining={z['physical_case_id'] for z in V1.load(plan)['case_records'] if z['status']=='UNSCHEDULED_EXACT_CURRENT_AUDIT'}
 q281=V1.S/'requests/root281-f6-lifecycle-prepared-001/root281-request.json';s281=V1.load(q281);selected=set(s281['physical_case_ids'])
 if selected&remaining:
  assert selected<=remaining;registry,plan=V1.admit(281,q281,registry,plan)
 queuep=V1.S/'requests/root282-root307-lifecycle-source-queue-001/root282-root307-source-queue.json';assert V1.sha(queuep)=='a3d1b8e864d886633d470fe1b456baad433190ba853bef0be73afbff1d897f14'
 for batch in V1.load(queuep)['batches']:
  remaining={z['physical_case_id'] for z in V1.load(plan)['case_records'] if z['status']=='UNSCHEDULED_EXACT_CURRENT_AUDIT'};selected=set(batch['case_ids'])
  if not selected&remaining:continue
  assert selected<=remaining,'partial source selection requires an additive exact-subset request';source=Path(batch['request']);assert V1.sha(source)==batch['request_sha256'];registry,plan=V1.admit(int(batch['namespace'][4:]),source,registry,plan)
 print(json.dumps({'event':'RESUMED_QUEUE_TERMINAL','coverage':V1.load(plan)['coverage'],'registry':V1.ref(registry),'plan':V1.ref(plan),'goal_complete':False}),flush=True)
if __name__=='__main__':main()
