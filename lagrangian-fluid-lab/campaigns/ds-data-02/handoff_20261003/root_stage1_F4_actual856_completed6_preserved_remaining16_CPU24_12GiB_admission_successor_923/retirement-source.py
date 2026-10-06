from pathlib import Path
import json,hashlib,os,signal,time,datetime
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');H=R/'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003';old=next(H.glob('root*_856'));O=next(H.glob('root*_923'));load=lambda p:json.loads(Path(p).read_text());sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest();c=load(old/'controller-launch-process.json');pid=c['pid'];pr=Path('/proc')/str(pid);cfg=load(O/'controller-config.json')
def fields():return (pr/'stat').read_text().split(') ',1)[1].split()
def children():return sorted({int(x) for t in (pr/'task').iterdir() for x in (t/'children').read_text().split()})
def prove():
 f=fields();assert f[19]==c['proc_start_ticks'] and c['controller'].encode() in (pr/'cmdline').read_bytes() and sha(c['controller'])==c['controller_sha256'] and not children(); qs=[]
 for qp in old.glob('*render-request.json'):
  q=load(qp);rp=Path(q['attempt_root'])/'execution-receipt.json';r=load(rp) if rp.exists() else None
  if r:assert (r['status'],r['returncode'])==('completed',0) and q['case_id'] in cfg['preserved_actual856_completed6']
  else:assert not Path(q['attempt_root']).exists()
  qs.append({'request':str(qp),'sha256':sha(qp),'case_id':q['case_id'],'receipt':str(rp),'status':r['status'] if r else 'not_launched','receipt_sha256':sha(rp) if r else None,'attempt_id':q['attempt_id']})
 assert len(qs)==8 and sum(x['status']=='completed' for x in qs)==6
 ledger=load('/home/jade/Projects/DualSPHysics-data/ds-data-02/runtime/resource-ledger.json');attempts={x['attempt_id'] for x in qs};assert not any(x.get('attempt_id') in attempts for x in ledger['reservations'])
 return f,qs,ledger
prove();os.kill(pid,signal.SIGSTOP)
try:
 for _ in range(30):
  if fields()[0] in ['T','t']:break
  time.sleep(.05)
 f,qs,l=prove();assert f[0] in ['T','t'];proof={'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'pid':pid,'proc_start_ticks':c['proc_start_ticks'],'controller_sha256':c['controller_sha256'],'frozen_state':f[0],'actual_children':[],'request_status_inventory':qs,'preserved_actual_completed0':6,'own_scientific_reservations_at_handoff':0,'other_scientific_reservations_preserved':l['reservations'],'reason':'Original856 holds shared render lock while waiting12GiB+16GiB discretionary margin; Home523GiB permits independentF6 16GiB+2GiB. DistinctF4 successor retains12GiB/full1201 and skips6 actual0; shared500GiB floor/cap2/CPU24/env2 unchanged.','scientific_worker_terminated_or_restarted':False,'original_request_receipt_or_source_bytes_changed':False,'case_increment':0};os.kill(pid,signal.SIGTERM);os.kill(pid,signal.SIGCONT)
except BaseException:
 os.kill(pid,signal.SIGCONT);raise
for _ in range(50):
 if not pr.exists() or fields()[0]=='Z':break
 time.sleep(.1)
assert not pr.exists() or fields()[0]=='Z';proof['same_metadata_handle_retired']=True;proof['terminal_state']='missing' if not pr.exists() else fields()[0];(O/'metadata-only-original856-retirement-proof.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n');(O/'retirement-source.py').write_bytes(Path(__file__).read_bytes());print({'metadata_pid_retired':pid,'actual_completed6_preserved':True,'scientific_workers_touched':0})
