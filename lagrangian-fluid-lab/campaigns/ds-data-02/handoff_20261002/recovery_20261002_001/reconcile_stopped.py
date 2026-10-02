"""Preserve interrupted receipts; reconcile only absent launcher and child groups."""
import csv,json,os,sys,subprocess,hashlib
from pathlib import Path
from datetime import datetime,timezone
sys.path.insert(0,str(Path.cwd()/'scripts'));import ds_data02_runtime_v2 as rt
DATA=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');PACK=Path(__file__).resolve().parent
stamp=lambda:datetime.now(timezone.utc).isoformat()
def groups():
 rows=subprocess.check_output(['ps','-e','-o','pid=,pgid=,args='],text=True).splitlines();return [tuple(x.strip().split(None,2)) for x in rows if len(x.strip().split(None,2))==3]
record=[];snapshot=(DATA/'runtime/resource-ledger.json').read_bytes();(PACK/'resource-ledger.before.json').write_bytes(snapshot)
for row in json.loads(snapshot)['reservations']:
 root=DATA/'families'/row['id'];original=root/'execution-receipt.json';r=json.load(open(original));pid=r['pid'];launcher=row['launcher_pid']
 if Path('/proc',str(pid)).exists() or Path('/proc',str(launcher)).exists() or any(int(g)==pid for p,g,a in groups()):
  record.append({'id':row['id'],'action':'retained live reservation','pid':pid,'launcher_pid':launcher});continue
 name=row['id'].replace('/','__');dest=PACK/name;dest.mkdir(exist_ok=False);(dest/'original-execution-receipt.json').write_bytes(original.read_bytes());sources={str(original):rt.sha256(original)}
 status='failed';observed=None;semantic='Stopped without terminal scientific output; original bytes preserved'
 if row['kind']=='qualification':
  stdout=root/'stdout.log';runparts=root/'solver_output/RunPARTs.csv';text=stdout.read_text(errors='replace');rows=[x for x in csv.DictReader(runparts.open(),delimiter=';') if x.get('Part','').isdigit()];last=float(rows[-1]['TimeStep [s]']);window=float(next(x.split(':')[1] for x in r['command'] if x.startswith('-tmax:')))
  assert 'Finished execution (code=0).' in text and last>=window
  sources.update({str(stdout):rt.sha256(stdout),str(runparts):rt.sha256(runparts)});status='completed';observed=0;semantic='Completion reconstructed from native successful termination log plus full increasing native saved timeline; original process wait returncode unavailable'
  evidence={'frames':len(rows),'last_native_time_s':last,'physical_window_s':window,'observed_native_termination_code':0,'interval_exclusions':{k:sum(int(x[k].replace(',','')) for x in rows if x[k]) for k in ['NpOutPos','NpOutRho','NpOutMov']}}
 elif row.get('cpu_task_kind')=='conversion':
  report=root/'conversion-report.json';h5=root/'trajectory.h5';assert report.exists() and h5.exists();data=json.load(open(report));assert data['conversion_status']=='completed' and data['output_sha256']==rt.sha256(h5)
  sources.update({str(report):rt.sha256(report),str(h5):data['output_sha256']});status='completed';semantic='Completion reconstructed from terminal full conversion report plus matching final HDF5 hash; process wait returncode unavailable';evidence={k:data[k] for k in ['frames','particles','conversion_status','output_sha256','time_evidence']}
 else:evidence={'completed_scientific_report_present':False}
 expected=r['input_hashes_at_launch'];actual={p:rt.sha256(p) if Path(p).is_file() else None for p in expected};assert actual==expected
 recovered=dict(r);recovered.update(schema='ds02.recovered-execution-receipt.v1',status=status,returncode=None,observed_native_termination_code=observed,termination_reason=None if status=='completed' else 'launcher_and_child_absent_without_terminal_report',finished_at_utc=stamp(),input_hashes_after_run=actual,recovery={'original_receipt':str(original),'original_sha256':sources[str(original)],'process_wait_returncode':'unavailable; never synthesized','completion_semantics':semantic,'evidence':evidence,'source_sha256':sources,'launcher_and_child_and_group_absent':True,'observed_at_utc':stamp(),'resource_charge_policy':'Conservative full reserved GPU/CPU budget; exact child resource usage unavailable after launcher loss'})
 receipt=dest/'recovered-execution-receipt.json';receipt.write_text(json.dumps(recovered,indent=2)+'\n')
 with rt.ledger_locked(DATA) as ledger:
  present=[x for x in ledger['reservations'] if x['id']==row['id']];assert len(present)==1 and present[0]==row
  assert not Path('/proc',str(pid)).exists() and not Path('/proc',str(launcher)).exists();assert not any(int(g)==pid for p,g,a in groups())
  ledger['reservations']=[x for x in ledger['reservations'] if x['id']!=row['id']];ledger['charges'].append({'id':row['id'],'gpu_seconds':row.get('gpu_seconds',0),'cpu_core_seconds':row['cpu_core_seconds'],'new_storage_bytes':rt.tree_bytes(root),'status':status,'finished_at_utc':stamp(),'usage_semantics':'conservative full reservation after absent launcher','recovered_receipt':str(receipt),'recovered_receipt_sha256':rt.sha256(receipt)})
  for x in ledger['attempts']:
   if x['id']==row['id']:x.update(status=status,finished_at_utc=stamp(),terminal_receipt=str(receipt),recovered=True)
  if row.get('gpu_uuid'):
   lease=DATA/'leases'/(row['gpu_uuid']+'.json');value=json.load(open(lease));assert value['attempt_id']==row['id'] and value['pid']==pid;(dest/'original-gpu-lease.json').write_bytes(lease.read_bytes());lease.unlink()
 record.append({'id':row['id'],'action':'Recovered stopped terminal evidence and released stale reservation','status':status,'recovered_receipt':str(receipt),'receipt_sha256':rt.sha256(receipt),'budget_policy':'full reserved upper bound charged'})
(PACK/'recovery-manifest.json').write_text(json.dumps({'observed_at_utc':stamp(),'original_running_receipt_bytes_untouched':True,'no_foreign_process_signals':True,'records':record},indent=2)+'\n');print(json.dumps(record,indent=2))
