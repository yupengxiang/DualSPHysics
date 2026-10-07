from pathlib import Path
import json,runpy,hashlib,datetime
O=Path(__file__).parent
c=json.loads((O/'controller-config.json').read_text())
dispatch=runpy.run_path(c['fair_dispatch'])['dispatch']
results=[]
for item in c['requests']:
 p=Path(item['path']);assert hashlib.sha256(p.read_bytes()).hexdigest()==item['sha256']
 q=json.loads(p.read_text());r=dispatch(p,serial_conversion=True)
 rp=Path(q['attempt_root'])/'execution-receipt.json';a=json.loads(rp.read_text()) if rp.exists() else {}
 z={'physical_case_id':q['physical_case_id'],'request':item,'launcher_returncode':r.returncode,'status':a.get('status'),'returncode':a.get('returncode'),'actual_receipt':str(rp),'stdout_tail':r.stdout[-1500:],'stderr_tail':r.stderr[-1500:]}
 results.append(z)
 v={'schema':'ds02.F6.fulltime.remaining46.batch-result.v1','at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'status':'completed' if len(results)==len(c['requests']) else 'running','requests':len(c['requests']),'processed':len(results),'completed_zero':sum(x['status']=='completed' and x['returncode']==0 for x in results),'results':results,'case_credit':0}
 t=O/'batch-result.json.tmp';t.write_text(json.dumps(v,indent=2)+'\n');t.replace(O/'batch-result.json')
 print(json.dumps({'processed':v['processed'],'completed_zero':v['completed_zero'],'physical_case_id':z['physical_case_id'],'status':z['status']}),flush=True)
raise SystemExit(0 if all(x['status']=='completed' and x['returncode']==0 for x in results) else 1)
