from pathlib import Path
import json,hashlib,runpy,time
O=Path(__file__).parent;c=json.loads((O/'controller-config.json').read_text());assert hashlib.sha256(Path(c['fair_dispatch']['path']).read_bytes()).hexdigest()==c['fair_dispatch']['sha256'];dispatch=runpy.run_path(c['fair_dispatch']['path'])['dispatch'];results=[]
for qp in c['requests']:
 assert hashlib.sha256(Path(qp).read_bytes()).hexdigest()==c['request_sha256'][qp];q=json.loads(Path(qp).read_text());r=dispatch(qp,serial_conversion=True);rp=Path(q['attempt_root'])/'execution-receipt.json';a=json.loads(rp.read_text()) if rp.exists() else {};report=Path(q['attempt_root'])/'audit-output/c082s1-full-event-bed-footprint-audit.json';b=json.loads(report.read_text()) if report.exists() else {}
 actual0=r.returncode==0 and a.get('status')=='completed' and a.get('returncode')==0 and b.get('case_id')==q['case_id'] and b.get('physical_case_id')==q['physical_case_id']
 z={'tag':q['tag'],'case_id':q['case_id'],'request':qp,'actual_receipt':str(rp),'actual_report':str(report),'status':a.get('status'),'returncode':a.get('returncode'),'launcher_returncode':r.returncode,'actual_full801_bed_worker_output0':actual0,'physical_penetration_pass_not_inferred_from_exitcode':True,'stdout_tail':r.stdout[-1200:],'stderr_tail':r.stderr[-1200:],'case_credit':0};results.append(z);(O/'actual-progress.json').write_text(json.dumps({'results':results,'not_submitted':len(c['requests'])-len(results),'case_credit':0},indent=2)+'
')
 if not actual0:raise SystemExit(r.returncode or 1)
 time.sleep(4)
(O/'controller-result.json').write_text(json.dumps({'status':'completed','returncode':0,'actual_worker_completed0':len(results),'case_credit':0},indent=2)+'
')
