from pathlib import Path
import json,subprocess,hashlib,time,sys
L=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab');H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');sys.path[:0]=[str(L/'scripts'),str(H/'root_stage1_f3_first24_eight_solver_resource_policy_134')]
import ds_data02_runtime_v2 as rt,ds02_root_all_idle_gpu_policy_v2 as gpu
O=H/'root_stage1_f5_actual640_661_two_endpoints_full801_native_738';rows=[];failed=False;queue=[O/(tag+'-full801-native-request.json') for tag in ['M085_T080','M115_T100']]
for qp in queue:
 if failed:break
 while True:
  snap=rt.inventory();leased={json.loads(p.read_text())['uuid'] for p in (D/'leases').glob('*.json')}
  try:gpu.choose_gpu(snap,leased,4096);break
  except RuntimeError:time.sleep(10)
 q=json.loads(qp.read_text());p=subprocess.run([str(L/'.venv/bin/python'),str(H/'root_stage1_native_home_floor_eight_solver_dispatch_230/launch.py'),str(qp)],cwd=L,text=True,capture_output=True);rp=Path(q['attempt_root'])/'execution-receipt.json';r=json.loads(rp.read_text()) if rp.exists() else {};assert not r or r['request_sha256']==hashlib.sha256(qp.read_bytes()).hexdigest();row={'request':str(qp),'physical_case_id':q['physical_case_id'],'actual_receipt':str(rp),'launcher_returncode':p.returncode,'status':r.get('status'),'returncode':r.get('returncode'),'launcher_output':p.stdout[-1500:],'launcher_error':p.stderr[-2000:]};rows.append(row);print(json.dumps(row),flush=True);failed=p.returncode!=0 or (r.get('status'),r.get('returncode'))!=('completed',0)
result={'requested':2,'finished':len(rows),'completed0':sum((x['status'],x['returncode'])==('completed',0) for x in rows),'pending_held':2-len(rows),'first_completed0_before_second_launch':True,'live230_idle_UUID_sharedleases_each_launch':True,'results':rows};cp=Path(__file__).parent/'controller-result.json';assert not cp.exists();cp.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k!='results'}),flush=True);raise SystemExit(1 if failed else 0)
