from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
import json,subprocess,time,datetime,hashlib,os
O=Path(__file__).parent;R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
load=lambda p:json.loads(Path(p).read_text())
def put(p,d):Path(p).write_text(json.dumps(d,indent=2)+'\n')
def live(pid,ticks=None):
 p=Path('/proc')/str(pid)
 if not p.exists():return False
 try:
  f=(p/'stat').read_text().split(') ',1)[1].split();return f[0]!='Z' and (ticks is None or f[19]==ticks)
 except FileNotFoundError:return False
c=load(O/'dispatch-config.json');pc=load(c['wait_priority_controller']);P=Path(c['wait_priority_directory']);gate=False
while not gate:
 for qp in P.glob('*-render-request.json'):
  q=load(qp);rp=Path(q['attempt_root'])/'execution-receipt.json'
  if rp.exists():
   r=load(rp)
   if r['status']=='running' and live(r.get('pid')):gate=True;put(O/'actual-priority-render-live-before-gencase.json',{'pid':r['pid'],'receipt':str(rp),'request':str(qp),'actual_live_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()});break
 if not gate and not live(pc['pid'],pc['proc_start_ticks']):
  assert (P/'controller-result.json').exists(),'Root796 handle absent without terminal evidence: no independent science dispatch'
  gate=True;put(O/'actual-priority-terminal-before-gencase.json',{'controller':pc,'result':str(P/'controller-result.json')})
 if not gate:time.sleep(3)
def run(qp):
 q=load(qp);ap=Path(q['attempt_root']);assert not ap.exists()
 while sum(x.get('cpu_threads',0) for x in load(D/'runtime/resource-ledger.json')['reservations'])+4>64:time.sleep(2)
 p=subprocess.run([str(L/'.venv/bin/python'),str(H/'root_stage1_home_floor_inventory_dispatch_142/launch.py'),qp],cwd=L,capture_output=True,text=True);rp=ap/'execution-receipt.json';r=load(rp) if rp.exists() else {};passed=False;prep={}
 if (r.get('status'),r.get('returncode'))==('completed',0):
  pp=ap/'prepared/prepared-input-report.json';prep=load(pp);passed=prep['case_id']==q['case_id'] and prep['actual_generated_constants']['data2d']['value']=='false' and prep['actual_total_particles']>0 and prep['generated_xml_particle_counts']['fluid']>0 and all(a['verified_post_gencase_sha256']==a['sha256'] for a in prep['assets'])
 row={'case_id':q['case_id'],'request':qp,'actual_receipt':str(rp),'status':r.get('status'),'returncode':r.get('returncode'),'launcher_returncode':p.returncode,'actual_GenCase_pass':passed,'prepared_input_report':str(ap/'prepared/prepared-input-report.json') if passed else None,'actual_total_particles':prep.get('actual_total_particles'),'actual_particle_counts':prep.get('generated_xml_particle_counts'),'independent_case_increment':0,'native_initial_qa_still_required':True,'launcher_error':p.stderr[-1500:]};print(json.dumps(row),flush=True);return row
qs=c['requests'];rows=[run(qs[0])];failed=not rows[0]['actual_GenCase_pass'];index=1
with ThreadPoolExecutor(max_workers=2) as pool:
 active={}
 while active or(index<len(qs) and not failed):
  while len(active)<2 and index<len(qs) and not failed:active[pool.submit(run,qs[index])]=qs[index];index+=1
  if not active:break
  done,_=wait(active,return_when=FIRST_COMPLETED)
  for f in done:
   active.pop(f);row=f.result();rows.append(row)
   if not row['actual_GenCase_pass']:failed=True
summary={'requested':24,'completed0':sum((r.get('status'),r.get('returncode'))==('completed',0) for r in rows),'actual_GenCase_pass_count':sum(r['actual_GenCase_pass'] for r in rows),'pending_held':len(qs)-index,'maximum_parallel_jobs':2,'CPU_threads_per_job':4,'independent_case_increment':0,'results':rows};put(O/'controller-result.json',summary);raise SystemExit(1 if failed else 0)
