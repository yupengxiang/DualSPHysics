import json,pathlib,hashlib,datetime,sys,socket,os
R=pathlib.Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');sys.path.insert(0,str(R/'lagrangian-fluid-lab/scripts'));import ds_data02_runtime_v2 as rt
D=rt.DATA_ROOT;H=R/'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f3_orphan_accounting_reconciliation_070'
a=D/'families/F3/F3_FOUR_ORPHAN_NATIVE_COMPLETION_AUDIT/root-stage1-f3-four-orphan-native-completion-audit-065'
def sha(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
r=json.loads((a/'execution-receipt.json').read_text());assert r['status']=='completed' and r['returncode']==0
e=json.loads((a/'native-completion-recovery.json').read_text());assert len(e['cases'])==4
assert not (H/'accounting-reconciliation.json').exists()
with rt.ledger_locked(D) as ledger:
 before_sha=sha(D/'runtime/resource-ledger.json');items=[]
 for x in e['cases']:
  assert x['native_solver_completed_evidence'] and x['source_inputs_unchanged'] and x['runtime_process_returncode_unobserved']
  assert x['actual_native_frames']==836 and x['native_parts_out']==0
  p=pathlib.Path(x['runtime_receipt']['path']);assert sha(p)==x['runtime_receipt']['sha256'];old=json.loads(p.read_text());assert old['status']=='running' and old.get('returncode') is None
  ident='F3/'+x['case_id']+'/'+p.parent.name;rows=[z for z in ledger['reservations'] if z['id']==ident];assert len(rows)==1;z=rows[0];assert z['host']==socket.gethostname();assert not any(t['id']==ident for t in ledger['charges']);assert z['gpu_seconds']==7200 and z['cpu_core_seconds']==28800
  lease=D/'leases'/(z['gpu_uuid']+'.json');l=json.loads(lease.read_text());assert l['attempt_id']==ident and l['launcher_pid']==z['launcher_pid'] and l['pid']==old['pid'] and l['host']==z['host']
  for pid in [z['launcher_pid'],l['pid']]:assert not pathlib.Path('/proc/'+str(pid)).exists(),pid
  items.append({'id':ident,'reservation':dict(z),'lease':{'path':str(lease),'sha256':sha(lease),'value':l},'runtime_receipt_preserved':x['runtime_receipt'],'charge_gpu_seconds_upper_bound':z['gpu_seconds'],'charge_cpu_core_seconds_upper_bound':z['cpu_core_seconds']})
 stamp=datetime.datetime.now(datetime.timezone.utc).isoformat();report={'schema':'ds02.root.orphan-resource-reconciliation.v1','at_utc':stamp,'ledger_before_sha256':before_sha,'actual_native_completion_audit':{'path':str(a/'native-completion-recovery.json'),'sha256':sha(a/'native-completion-recovery.json')},'items':items,'accounting':'Full reserved GPU and CPU upper bounds, not observed duration or measured CPU use. Original runtime process returncode remains unobserved; source receipts preserved.','gpu_hours_charged_upper_bound':8,'cpu_core_hours_charged_upper_bound':32,'independent_case_count_increment':0,'q_n':'not_granted','original_receipts_modified':False}
 rt.atomic_json(H/'accounting-reconciliation.json',report)
 ids={x['id'] for x in items};ledger['reservations']=[z for z in ledger['reservations'] if z['id'] not in ids]
 for item in items:
  z=item['reservation'];ledger['charges'].append({'id':item['id'],'gpu_seconds':z['gpu_seconds'],'cpu_core_seconds':z['cpu_core_seconds'],'new_storage_bytes':z['new_storage_bytes'],'status':'native-output-recovered-runtime-finalization-unavailable','finished_at_utc':stamp,'accounting':'conservative full reservation upper bound; actual runtime duration/returncode unavailable','reconciliation':str(H/'accounting-reconciliation.json')})
 for z in ledger['attempts']:
  if z['id'] in ids:z.update(status='native-output-recovered-runtime-finalization-unavailable',finished_at_utc=stamp,reconciliation=str(H/'accounting-reconciliation.json'))
 # Persist before deleting only the verified owned leases; no foreign lease is changed.
 rt.atomic_json(D/'runtime/resource-ledger.json',ledger)
 for item in items:
  p=pathlib.Path(item['lease']['path']);assert sha(p)==item['lease']['sha256'];p.unlink()
print('reconciled 4 native cases; charged full upper bounds 8 GPUh/32 CPUcoreh; exact owned leases released')
