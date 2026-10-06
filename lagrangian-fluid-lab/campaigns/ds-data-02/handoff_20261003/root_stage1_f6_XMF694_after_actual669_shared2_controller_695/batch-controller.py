from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
import subprocess,json,time,xml.etree.ElementTree as ET
L=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab');H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
queue=sorted((H/'root_stage1_f6_actual607_658_full241_N3_XMF_required_field_repair1_694').glob('*-xmf-request.json'));assert len(queue)==24
upstream=H/'root_stage1_f4_XMF669_wait648_terminal_then_CPU2_cap2_controller_670'/'controller-result.json'
while not upstream.exists():time.sleep(10)
u=json.loads(upstream.read_text());assert u['completed0']==24 and u['actual_XMF_N3_pass_count']==24
print(json.dumps({'actual_F4_XMF669_all24completed0':True,'shared_conversion_handoff':'drained before first F6 XMF'}),flush=True)
def run(p):
 q=json.loads(p.read_text());r=subprocess.run([str(L/'.venv/bin/python'),str(H/'root_stage1_home_floor_inventory_dispatch_142/launch.py'),str(p)],cwd=L,text=True,capture_output=True)
 rp=D/'families'/q['family_id']/q['case_id']/q['attempt_id']/'execution-receipt.json';a=json.loads(rp.read_text()) if rp.is_file() else {}
 if (a.get('status'),a.get('returncode'))==('completed',0):
  m=json.loads((rp.parent/'xdmf/manifest.json').read_text());g=ET.parse(m['xdmf']).getroot().findall('.//Grid[@GridType="Uniform"]');assert m['frames']==241 and m['particles']==417505 and m['source_h5_read_only'] and len(g)==241;assert all(x.find('Geometry/DataItem').get('Dimensions')==x.find('Attribute[@Name="velocity"]/DataItem').get('Dimensions')=='417505 3' for x in g)
 row={'case_id':q['case_id'],'request':str(p),'launcher_returncode':r.returncode,'status':a.get('status'),'returncode':a.get('returncode'),'launcher_output':r.stdout[-1400:],'launcher_error':r.stderr[-1400:]};print(json.dumps(row),flush=True);return row
rows=[run(queue[0])];failed=rows[0]['launcher_returncode']!=0 or (rows[0]['status'],rows[0]['returncode'])!=('completed',0);index=1
with ThreadPoolExecutor(max_workers=2) as pool:
 active={}
 while active or (index<len(queue) and not failed):
  while len(active)<2 and index<len(queue) and not failed:active[pool.submit(run,queue[index])]=queue[index];index+=1
  done,_=wait(active,return_when=FIRST_COMPLETED)
  for f in done:
   active.pop(f);row=f.result();rows.append(row)
   if row['launcher_returncode']!=0 or (row['status'],row['returncode'])!=('completed',0):failed=True
summary={'requested':24,'finished':len(rows),'completed0':sum((r['status'],r['returncode'])==('completed',0) for r in rows),'pending_held':len(queue)-index,'parallel_cap':2,'first_failure_holds_pending':True,'results':rows}
(Path(__file__).parent/'controller-result.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps({k:v for k,v in summary.items() if k!='results'}),flush=True)
raise SystemExit(1 if failed else 0)
