from pathlib import Path
import json,hashlib,os,signal,time,datetime
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');H=R/'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003';old=next(H.glob('root*_920'));O=H/'root_stage1_F6_actual920_first_full241_preserved_metadata_future23_handoff_929';O.mkdir(exist_ok=False);load=lambda p:json.loads(Path(p).read_text());sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest();c=load(old/'controller-launch-process.json');pid=c['pid'];pr=Path('/proc')/str(pid)
def fields():return (pr/'stat').read_text().split(') ',1)[1].split()
def children():return sorted({int(x) for t in (pr/'task').iterdir() for x in (t/'children').read_text().split()})
def prove():
 f=fields();assert f[0]!='Z' and f[19]==c['proc_start_ticks'] and c['controller'].encode() in (pr/'cmdline').read_bytes() and sha(c['controller'])==c['controller_sha256'] and not children();items=[]
 for qp in old.glob('*render-request.json'):
  q=load(qp);rp=Path(q['attempt_root'])/'execution-receipt.json';r=load(rp) if rp.exists() else None
  if r:
   assert (r['status'],r['returncode'])==('completed',0);report=rp.parent/'render/paraview-full-animation-report.json';a=load(report);assert a['frames']==a['source_frames']==241 and a['all_frames_rendered'] and a['actual_times_preserved_exactly'] and len(a['outputs']['contact_sheets'])==11
  else:assert not Path(q['attempt_root']).exists()
  items.append({'request':str(qp),'request_sha256':sha(qp),'case_id':q['case_id'],'attempt_root':q['attempt_root'],'attempt_id':q['attempt_id'],'actual_receipt':str(rp),'actual_receipt_sha256':sha(rp) if r else None,'status':r['status'] if r else 'unlaunched','returncode':r['returncode'] if r else None,'actual_report':str(report) if r else None,'actual_report_sha256':sha(report) if r else None})
 assert len(items)==3 and sum(x['status']=='completed' for x in items)==1;ledger=load('/home/jade/Projects/DualSPHysics-data/ds-data-02/runtime/resource-ledger.json');own={f"F6/{x['case_id']}/{x['attempt_id']}" for x in items};assert not any(x.get('id') in own for x in ledger['reservations']);return f,items,ledger
prove();os.kill(pid,signal.SIGSTOP)
try:
 for _ in range(30):
  if fields()[0] in ['T','t']:break
  time.sleep(.05)
 f,items,l=prove();assert f[0] in ['T','t'];proof={'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'pid':pid,'proc_start_ticks':c['proc_start_ticks'],'controller_sha256':c['controller_sha256'],'frozen_state':f[0],'all_task_children':[],'actual_requests':items,'actual_full241_completed0_preserved':1,'registered_future_without_scientific_attempt':2,'remaining_target_candidates':23,'own_scientific_reservations':0,'foreign_and_other_family_reservations_preserved':l['reservations'],'reason':'First full241 completed0 retained; future16GiB metadata waiters would hold renderregistrationlock during insufficient Home and starve reviewed smaller bounded worker requests. Distinct fair Root928 admission and reviewed NVMe renderer successor will continue only23 remaining own native722 cases; no completed renderer rerun. Original consumed920 source/q/receipt unchanged.','scientific_workers_terminated_or_restarted':False,'case_credit':0};os.kill(pid,signal.SIGTERM);os.kill(pid,signal.SIGCONT)
except BaseException:
 os.kill(pid,signal.SIGCONT);raise
for _ in range(50):
 if not pr.exists() or fields()[0]=='Z':break
 time.sleep(.1)
assert not pr.exists() or fields()[0]=='Z';proof['same_metadata_handle_retired']=True;proof['terminal_state']='missing' if not pr.exists() else fields()[0];(O/'metadata-only-original920-after1-retirement-proof.json').write_text(json.dumps(proof,indent=2)+'\n');(O/'retirement-source.py').write_bytes(Path(__file__).read_bytes());print({'retired_metadata_PID':pid,'actual_first0_preserved':True,'future23_only':True,'science_restart_or_termination':0})
