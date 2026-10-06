from pathlib import Path
import json,runpy,hashlib,time
O=Path(__file__).parent;c=json.loads((O/'controller-config.json').read_text());assert hashlib.sha256(Path(c['fair_dispatch']['path']).read_bytes()).hexdigest()==c['fair_dispatch']['sha256'];dispatch=runpy.run_path(c['fair_dispatch']['path'])['dispatch'];results=[]
for qp in c['requests']:
 assert hashlib.sha256(Path(qp).read_bytes()).hexdigest()==c['request_sha256'][qp]
 q=json.loads(Path(qp).read_text());r=dispatch(qp,serial_conversion=True);rp=Path(q['attempt_root'])/'execution-receipt.json';a=json.loads(rp.read_text()) if rp.exists() else {};mp=Path(q['attempt_root'])/'xdmf/manifest.json';m=json.loads(mp.read_text()) if mp.exists() else {}
 passed=r.returncode==0 and a.get('status')=='completed' and a.get('returncode')==0 and m.get('frames')==401 and m.get('particles')==418104 and m.get('physical_case_id')==q['physical_case_id'] and m.get('physical_condition_sha256')==q['physical_condition_sha256'] and m.get('source_h5_sha256')==q['actual_typed_H5_SHA_from_producer_only']
 z={'case_id':q['case_id'],'physical_case_id':q['physical_case_id'],'request':qp,'actual_receipt':str(rp),'actual_manifest':str(mp),'status':a.get('status'),'returncode':a.get('returncode'),'launcher_returncode':r.returncode,'actual_full401_N3_XMF_pass':passed,'stdout_tail':r.stdout[-1800:],'stderr_tail':r.stderr[-1800:],'case_credit':0};results.append(z);(O/'actual-progress.json').write_text(json.dumps({'results':results,'not_submitted':len(c['requests'])-len(results),'case_credit':0},indent=2)+'\n');print(json.dumps(z),flush=True)
 if not passed:
  (O/'controller-result.json').write_text(json.dumps({'status':'stopped_for_primary_failure_classification','returncode':r.returncode or 1,'case_credit':0},indent=2)+'\n');raise SystemExit(r.returncode or 1)
 time.sleep(4)
(O/'controller-result.json').write_text(json.dumps({'status':'completed','returncode':0,'actual_completed_XMF':len(results),'case_credit':0},indent=2)+'\n')
