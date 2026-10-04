"""Accept only strictly audited recovered native completion; preserve original runtime status/returncode."""
import argparse,json,hashlib,sys
from pathlib import Path
sys.path.insert(0,'/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts')
import ds_data02_nvme_convert_v1 as nvme
import ds_data02_direct_convert as converter

def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for block in iter(lambda:f.read(1048576),b''):h.update(block)
 return h.hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--recovery',type=Path,required=True);p.add_argument('--recovery-runtime-receipt',type=Path,required=True);p.add_argument('--reconciliation',type=Path,required=True);p.add_argument('--expected-case',required=True);p.add_argument('--staging-root',type=Path,required=True);p.add_argument('--staging-limit-bytes',type=int,required=True);p.add_argument('converter_args',nargs=argparse.REMAINDER);x=p.parse_args();argv=x.converter_args
 if argv and argv[0]=='--':argv=argv[1:]
 args=converter._build_parser().parse_args(argv);audit=json.loads(x.recovery_runtime_receipt.read_text());assert audit['status']=='completed' and audit['returncode']==0
 recovery=json.loads(x.recovery.read_text());rows=[z for z in recovery['cases'] if z['case_id']==x.expected_case];assert len(rows)==1;row=rows[0]
 assert row['native_solver_completed_evidence'] and row['runtime_process_returncode_unobserved'] and row['source_inputs_unchanged'] and row['actual_native_frames']==836 and row['native_parts_out']==0
 assert Path(row['runtime_receipt']['path']).resolve()==args.solver_receipt.resolve();assert sha(args.solver_receipt)==row['runtime_receipt']['sha256']
 for key in ['nativeRun','stdout']:assert sha(row[key]['path'])==row[key]['sha256']
 recon=json.loads(x.reconciliation.read_text());assert recon['actual_native_completion_audit']['sha256']==sha(x.recovery);ident='F3/'+x.expected_case+'/'+Path(row['attempt_root']).name;assert len([z for z in recon['items'] if z['id']==ident])==1
 owner=json.loads(args.owner_metadata.read_text());assert owner['case_id']==row['case_id'] and owner['physical_case_id']==row['physical_case_id'];assert owner['physical_condition_sha256']==row['physical_condition_sha256']
 assert args.data_root.resolve()==(Path(row['attempt_root'])/'solver_output/data').resolve()
 original=converter._verify_receipt;observed=[]
 def verify(path,label):
  if label!='solver' or Path(path).resolve()!=args.solver_receipt.resolve():return original(path,label)
  assert sha(path)==row['runtime_receipt']['sha256'];value=json.loads(Path(path).read_text());assert value['status']=='running' and value.get('returncode') is None
  # The exact original receipt is returned, without changing status or inventing a process returncode.
  observed.append({'native_completion':row,'original_runtime_receipt_status':value['status'],'original_runtime_process_returncode':value.get('returncode'),'observed_native_log_finish_code':row['native_log_finish_code']});return value
 converter._verify_receipt=verify
 try:result=nvme.run(args,x.staging_root,x.staging_limit_bytes)
 finally:converter._verify_receipt=original
 assert observed
 out=args.output.parent/'native-completion-recovery-conversion-sidecar.json';assert not out.exists();out.write_text(json.dumps({'schema':'ds02.stage1.recovered-native-conversion-provenance.v1','recovery':{'path':str(x.recovery),'sha256':sha(x.recovery)},'reconciliation':{'path':str(x.reconciliation),'sha256':sha(x.reconciliation)},'original_runtime_receipts_modified':False,'runtime_returncode_unobserved':True,'observations':observed,'converted_all_frames':result['frames'],'output_sha256':result['output_sha256'],'q_n':'not_granted','visual_review':'pending','independent_case_increment':0},ensure_ascii=False,indent=2)+'\n');print(json.dumps({'frames':result['frames'],'particles':result['particles'],'partvtk_all_passed':result['partvtk_validation']['all_passed'],'output_sha256':result['output_sha256'],'native_runtime_finalization':'unknown and preserved'}),flush=True)
if __name__=='__main__':main()
