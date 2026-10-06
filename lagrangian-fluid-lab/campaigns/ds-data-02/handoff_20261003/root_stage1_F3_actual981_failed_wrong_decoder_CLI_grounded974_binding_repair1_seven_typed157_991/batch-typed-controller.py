from pathlib import Path
import json,runpy,time,hashlib,datetime
O=Path(__file__).parent
c=json.loads((O/'controller-config.json').read_text())
assert hashlib.sha256(Path(c['fair_dispatch']['path']).read_bytes()).hexdigest()==c['fair_dispatch']['sha256']
dispatch=runpy.run_path(c['fair_dispatch']['path'])['dispatch']
results=[]
for i,qp in enumerate(c['requests']):
 q=json.loads(Path(qp).read_text())
 assert hashlib.sha256(Path(qp).read_bytes()).hexdigest()==c['request_sha256'][qp]
 r=dispatch(qp,serial_conversion=True)
 rp=Path(q['attempt_root'])/'execution-receipt.json'
 a=json.loads(rp.read_text()) if rp.exists() else {}
 report=Path(q['attempt_root'])/'conversion-report.json'
 t=json.loads(report.read_text()) if report.exists() else {}
 passed=(r.returncode==0 and a.get('status')=='completed' and a.get('returncode')==0 and t.get('frames')==836 and t.get('particles')==179208 and t.get('partvtk_validation',{}).get('all_passed') is True and t.get('hash_scopes',{}).get('physical_condition_sha256')==q['actual_converter_scope_sha256'])
 result={'case_id':q['case_id'],'physical_case_id':q['physical_case_id'],'request':qp,'actual_receipt':str(rp),'status':a.get('status'),'returncode':a.get('returncode'),'launcher_returncode':r.returncode,'actual_full836_conversion_pass':passed,'stdout_tail':r.stdout[-1800:],'stderr_tail':r.stderr[-1800:],'case_credit':0}
 results.append(result)
 progress={'results':results,'not_submitted':len(c['requests'])-len(results),'case_credit':0,'source_and_science_recipe_unchanged':True}
 (O/'actual-progress.json').write_text(json.dumps(progress,indent=2)+'\n')
 print(json.dumps(result),flush=True)
 if not passed:
  (O/'controller-result.json').write_text(json.dumps({'status':'stopped_for_primary_failure_classification','failed_case':q['case_id'],'not_submitted':progress['not_submitted'],'returncode':r.returncode or 1,'case_credit':0},indent=2)+'\n')
  raise SystemExit(r.returncode or 1)
 time.sleep(4)
(O/'controller-result.json').write_text(json.dumps({'status':'completed','returncode':0,'actual_completed_conversions':len(results),'case_credit':0},indent=2)+'\n')
