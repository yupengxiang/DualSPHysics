from pathlib import Path
import runpy,json
O=Path(__file__).parent
c=json.loads((O/'controller-config.json').read_text())
r=runpy.run_path(c['fair_dispatch'])['dispatch'](c['request'],serial_conversion=True)
q=json.loads(Path(c['request']).read_text())
rp=Path(q['attempt_root'])/'execution-receipt.json'
a=json.loads(rp.read_text()) if rp.exists() else {}
v={'launcher_returncode':r.returncode,'status':a.get('status'),'returncode':a.get('returncode'),'actual_receipt':str(rp),'stdout_tail':r.stdout[-3000:],'stderr_tail':r.stderr[-3000:],'case_credit':0}
(O/'controller-result.json').write_text(json.dumps(v,indent=2)+'\n')
print(json.dumps(v),flush=True)
raise SystemExit(r.returncode)
