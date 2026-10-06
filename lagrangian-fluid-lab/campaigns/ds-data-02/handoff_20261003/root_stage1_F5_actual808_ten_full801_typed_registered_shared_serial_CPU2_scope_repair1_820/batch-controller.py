from pathlib import Path
import json,subprocess,time,fcntl,datetime
O=Path(__file__).parent;R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');load=lambda p:json.loads(Path(p).read_text());cfg=load(O/'controller-config.json');results=[]
for row in cfg['rows']:
 q=load(row['actual_request']);ap=Path(q['attempt_root']);nr=load(row['actual_native_receipt']);assert (nr['status'],nr['returncode'])==('completed',0)
 with Path(cfg['shared_conversion_dispatch_lock']).open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  print(json.dumps({'tag':row['tag'],'state':'acquired shared conversion lock','at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}),flush=True)
  while sum(x.get('cpu_threads',0) for x in load(D/'runtime/resource-ledger.json')['reservations'])+2>64:time.sleep(3)
  p=subprocess.run([str(L/'.venv/bin/python'),str(H/'root_stage1_home_floor_inventory_dispatch_142/launch.py'),row['actual_request']],cwd=L,capture_output=True,text=True)
 rp=ap/'execution-receipt.json';cp=ap/'typed/conversion-report.json';r=load(rp) if rp.exists() else {};c=load(cp) if cp.exists() else {};passed=(r.get('status'),r.get('returncode'))==('completed',0) and p.returncode==0 and c.get('conversion_status')=='completed' and c.get('frames')==801 and c.get('particles')==194427 and c['solver_dimension']['solver_dimension']==3 and c['partvtk_validation']['all_passed'] and c['hash_scopes']['physical_condition_sha256']==row['prospective_legacy_scope_sha256'] and c['time_evidence']['last_s']>=16
 result={'tag':row['tag'],'request':row['actual_request'],'actual_receipt':str(rp),'actual_conversion_report':str(cp),'status':r.get('status'),'returncode':r.get('returncode'),'launcher_returncode':p.returncode,'actual_full801_typed_pass':passed,'independent_case_increment':0,'launcher_error':p.stderr[-1500:]};results.append(result);print(json.dumps(result),flush=True)
 if not passed:break
(O/'controller-result.json').write_text(json.dumps({'requested':10,'actual_full801_typed_pass_count':sum(x['actual_full801_typed_pass'] for x in results),'pending_held':10-len(results),'results':results,'science_payload_read_or_hashed_by_controller':False,'independent_case_increment':0},indent=2)+'\n')
raise SystemExit(0 if len(results)==10 and all(x['actual_full801_typed_pass'] for x in results) else 1)
