from pathlib import Path
import json,runpy,hashlib
O=Path(__file__).parent;c=json.loads((O/'controller-config.json').read_text());assert hashlib.sha256(Path(c['fair_dispatch']['path']).read_bytes()).hexdigest()==c['fair_dispatch']['sha256'];dispatch=runpy.run_path(c['fair_dispatch']['path'])['dispatch'];results=[]
for qp in c['requests']:
 assert hashlib.sha256(Path(qp).read_bytes()).hexdigest()==c['request_sha256'][qp]
 q=json.loads(Path(qp).read_text());r=dispatch(qp,serial_conversion=True);ar=Path(q['attempt_root']);rp=ar/'execution-receipt.json';mp=ar/'xdmf/manifest.json';a=json.loads(rp.read_text()) if rp.exists() else {};m=json.loads(mp.read_text()) if mp.exists() else {}
 passed=r.returncode==0 and a.get('status')=='completed' and a.get('returncode')==0 and m.get('frames')==836 and m.get('particles')==179208 and m.get('fields',{}).get('position',{}).get('shape')==[836,179208,3] and m.get('physical_case_id')==q['physical_case_id'] and m.get('physical_condition_sha256')==q['physical_condition_sha256'] and m.get('actual_converter_scope_sha256')==q['actual_converter_scope_sha256'] and m.get('source_h5_sha256')==q['expected_h5_sha256_from_audit_attestation']
 z={'case_id':q['case_id'],'physical_case_id':q['physical_case_id'],'request':qp,'actual_receipt':str(rp),'actual_manifest':str(mp),'status':a.get('status'),'returncode':a.get('returncode'),'launcher_returncode':r.returncode,'actual_full836_audit_qualified_XMF_output0':passed,'stdout_tail':r.stdout[-1600:],'stderr_tail':r.stderr[-1600:],'case_credit':0};results.append(z);(O/'actual-progress.json').write_text(json.dumps({'results':results,'case_credit':0},indent=2)+'\n');print(json.dumps(z),flush=True)
 if not passed:
  (O/'controller-result.json').write_text(json.dumps({'status':'stopped_for_primary_failure_classification','returncode':r.returncode or 1,'case_credit':0},indent=2)+'\n');raise SystemExit(r.returncode or 1)
(O/'controller-result.json').write_text(json.dumps({'status':'completed','returncode':0,'actual_full836_XMF_completed0':len(results),'case_credit':0},indent=2)+'\n')
