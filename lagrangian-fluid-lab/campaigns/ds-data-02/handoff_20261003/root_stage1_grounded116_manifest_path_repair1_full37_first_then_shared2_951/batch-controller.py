from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
import json,runpy
O=Path(__file__).parent;load=lambda p:json.loads(Path(p).read_text());cfg=load(O/'controller-config.json');dispatch=runpy.run_path(cfg['fair_dispatch_source']['path'])['dispatch']
def run(qp):
 q=load(qp);result=dispatch(qp);rp=Path(q['attempt_root'])/'execution-receipt.json';r=load(rp) if rp.exists() else {};passed=False;error=result.stderr[-2000:]
 if (r.get('status'),r.get('returncode'))==('completed',0):
  a=load(Path(q['attempt_root'])/'render/paraview-full-animation-report.json');pub=load(Path(q['attempt_root'])/'render/render-publish-receipt.json');expected=q['expected_frames'];passed=a['frames']==a['source_frames']==expected and a['all_frames_rendered'] and a['native_identity_axis_preserved'] and a['actual_times_preserved_exactly'] and a['nonfinite_active_states']==0 and a['source_h5_sha256']==q['source_h5_producer_sha256'] and pub['published_bytes_total']<=q['estimated_storage_bytes'] and len(a['outputs']['contact_sheets'])==q['expected_contact_sheets']
 row={'family_id':q['family_id'],'case_id':q['case_id'],'physical_case_id':q['physical_case_id'],'request':str(qp),'actual_receipt':str(rp),'status':r.get('status'),'returncode':r.get('returncode'),'launcher_returncode':result.returncode,'actual_fullnative_render_pass':passed,'launcher_error':error,'case_credit':0};print(json.dumps(row),flush=True);return row
qs=cfg['outer_requests'];rows=[run(qs[0])];failed=not rows[0]['actual_fullnative_render_pass'];index=1
with ThreadPoolExecutor(max_workers=2) as pool:
 active={}
 while active or(index<len(qs) and not failed):
  while len(active)<2 and index<len(qs) and not failed:active[pool.submit(run,qs[index])]=qs[index];index+=1
  done,_=wait(active,return_when=FIRST_COMPLETED)
  for f in done:
   active.pop(f);row=f.result();rows.append(row);failed|=not row['actual_fullnative_render_pass'];(O/'actual-progress.json').write_text(json.dumps({'results':rows,'pending_not_submitted':len(qs)-index,'case_credit':0},indent=2)+'\n')
summary={'requested':37,'actual_fullnative_completed0':sum(r['actual_fullnative_render_pass'] for r in rows),'pending_held':len(qs)-index,'results':rows,'case_credit':0};(O/'controller-result.json').write_text(json.dumps(summary,indent=2)+'\n');raise SystemExit(1 if failed else 0)
