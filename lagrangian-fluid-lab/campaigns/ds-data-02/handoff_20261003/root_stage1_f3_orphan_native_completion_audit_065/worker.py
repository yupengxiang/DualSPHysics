import argparse,csv,json,hashlib,os
from pathlib import Path
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def main():
 a=argparse.ArgumentParser();a.add_argument('--binding',required=True);a.add_argument('--output',required=True);x=a.parse_args();binding=json.loads(Path(x.binding).read_text());out=[]
 for row in binding['cases']:
  root=Path(row['attempt_root']);receipt_path=root/'execution-receipt.json';receipt=json.loads(receipt_path.read_text());
  for pid in [row['launcher_pid'],receipt['pid']]:
   if Path('/proc/'+str(pid)).exists():raise RuntimeError('bound process still exists '+str(pid))
  log=root/'stdout.log';text=log.read_text();run=root/'solver_output/Run.csv';
  with run.open() as f:
   lines=list(csv.reader(f,delimiter=';'))
  if len(lines)!=2:raise ValueError('unexpected nativeRun schema')
  fields=dict(zip([c.lstrip('#') for c in lines[0]],lines[1]));
  if fields['RunName']!=receipt['request']['case_id']:raise ValueError('native case mismatch')
  if int(fields['PartFiles'])!=836 or float(fields['PhysicalTime'])<8.35 or 'Finished execution (code=0).' not in text:raise ValueError('native full completion not proven')
  frames=sorted((root/'solver_output/data').glob('Part_*.bi4'));expected=['Part_'+str(i).zfill(4)+'.bi4' for i in range(836)]
  if [f.name for f in frames]!=expected:raise ValueError('incomplete native frame sequence')
  before=receipt['input_hashes_at_launch'];after={p:sha(p) for p in before}
  if before!=after:raise ValueError('launch input bytes changed')
  out.append({'case_id':receipt['request']['case_id'],'physical_case_id':receipt['request']['physical_case_id'],'physical_condition_sha256':receipt['request']['physical_condition_sha256'],'attempt_root':str(root),'runtime_receipt':{'path':str(receipt_path),'sha256':sha(receipt_path),'status':receipt['status'],'returncode':None,'preserved':True},'native_log_finish_code':0,'native_solver_completed_evidence':True,'actual_native_frames':836,'actual_last_time_s':float(fields['PhysicalTime']),'native_total_particles':int(fields['Np'].replace(',','')),'native_parts_out':int(fields['PartsOut'].replace(',','')),'source_inputs_verified':len(after),'source_inputs_unchanged':True,'nativeRun':{'path':str(run),'sha256':sha(run)},'stdout':{'path':str(log),'sha256':sha(log)},'processes_absent':True,'runtime_finalization':'interrupted_or_unavailable','runtime_process_returncode_unobserved':True,'q_n':'not_granted','visual_review':'pending full-state conversion and complete animation review','independent_case_increment':0})
 Path(x.output).write_text(json.dumps({'schema':'ds02.stage1.native-orphan-completion-recovery.v1','status':'native-completion-verified-runtime-finalization-unavailable','cases':out,'count_increment':0,'runtime_receipts_modified':False,'resource_accounting':'separate conservative reservation upper-bound reconciliation required'},ensure_ascii=False,indent=2)+'\n')
if __name__=='__main__':main()
