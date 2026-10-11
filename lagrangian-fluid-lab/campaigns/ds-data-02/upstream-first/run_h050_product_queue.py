"""Root-authorized full-state handoff for the first actual M4 condition."""
import json,os,subprocess,sys,time
from pathlib import Path
P=Path(__file__).resolve().parent;ROOT=P.parents[3]
CASE='UF_F1_MDBC_DP010_H050'
RUN=Path('/data/nas/jade/Simulation/DualSPHysics/upstream-first/runs/F1')/CASE
PYTHON='/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python'
sys.path.insert(0,str(P/'batch2-runtime'))
from grant_request import grant
COMMON=[ROOT/'lagrangian-fluid-lab/scripts'/x for x in ['ds_data02_runtime_v2.py','ds_data02_runtime_v6.py','ds_data02_runtime_v6_batch2.py']]
M=P/'m4';OWNER=M/'owners'/f'{CASE}-owner-v1.json';XML=RUN/'gencase-001'/f'{CASE}.xml';MANIFEST=P/'m3/f1-fine-dp010-t025/manifests'/f'{CASE}.json';DIFF=P/'m3/f1-fine-dp010-t025/semantic-diff.json'

def receipt(attempt):return json.loads((RUN/attempt/'execution-receipt.json').read_text())
def execute(attempt,command,inputs):
 assert not (RUN/attempt).exists()
 inputs=list(dict.fromkeys(str(x) for x in inputs+COMMON+[Path(__file__)]))
 assert all(Path(x).is_file() for x in inputs)
 d={'schema':'ds-data-02.runner.request.v1','status':'root_authorized_actual_completed_source','family_id':'F1','case_id':CASE,'attempt_id':attempt,'kind':'cpu','cpu_task_kind':'conversion','cpu_threads':4,'max_wall_seconds':3600,'estimated_storage_bytes':12*1024**3,'estimated_temp_peak_bytes':1024**3,'output_storage':'upstream_nas','cwd':str(ROOT),'worktree_root':str(ROOT),'command':command,'input_files':inputs,'qualification':'diagnostic_fullstate_product_pipeline_pending_final_relocation'}
 rq=P/'requests'/f'{CASE}-{attempt}.json'
 with rq.open('x') as f:json.dump(d,f,indent=2);f.write('\n')
 granted=grant(rq);print('Launching '+CASE+'/'+attempt,flush=True)
 with open('/tmp/'+CASE+'-'+attempt+'-product-queue-summary.json','x') as out:
  subprocess.run([PYTHON,str(COMMON[-1]),'run','--request',str(rq),'--batch-admission',str(P/'batch2-runtime/root-batch-2-admission.json'),'--batch-grant',str(granted)],cwd=ROOT,stdout=out,check=True)
 assert receipt(attempt)['status']=='completed'

def main():
 deadline=time.monotonic()+3700
 while receipt('m4-direct-conversion-001')['status']=='running':
  l=json.load(open('/home/jade/Projects/DualSPHysics-data/ds-data-02/runtime/resource-ledger.json'))
  row=next((r for r in l['reservations'] if r['id']==f'F1/{CASE}/m4-direct-conversion-001'),None)
  if row:os.kill(row['launcher_pid'],0)
  elif time.monotonic()>deadline:raise TimeoutError('bounded direct conversion wait expired')
  if time.monotonic()>deadline:raise TimeoutError('bounded direct conversion wait expired')
  time.sleep(10)
 assert receipt('m4-direct-conversion-001')['status']=='completed'
 direct=RUN/'m4-direct-conversion-001';native=RUN/'native-integrity-001/integrity.json';scan=RUN/'native-frame-scan-001/frame-identity-scan.json'
 execute('m4-enrichment-001',[PYTHON,str(M/'m4_direct_enrich.py'),'enrich','--trajectory',str(direct/'trajectory.h5'),'--report',str(direct/'direct-conversion-report.json'),'--generated-xml',str(XML),'--owner-metadata',str(OWNER),'--native-integrity',str(native),'--frame-scan',str(scan),'--case-manifest',str(MANIFEST),'--semantic-diff',str(DIFF),'--output-dir','{attempt_root}/product'],[M/'m4_direct_enrich.py',M/'m4_portable_adapter.py',direct/'trajectory.h5',direct/'direct-conversion-report.json',direct/'execution-receipt.json',XML,OWNER,native,scan,MANIFEST,DIFF])
 product=RUN/'m4-enrichment-001/product'
 assert json.loads((product/'interface.json').read_text())['status']=='normalized_verified'
 execute('m4-portable-build-001',[PYTHON,str(M/'m4_portable_adapter.py'),'build','--interface',str(product/'interface.json'),'--output','{attempt_root}/bundle'],[M/'m4_portable_adapter.py',M/'native-conversion-interface.schema.json',ROOT/'lagrangian-fluid-lab/scripts/l2_reader.py',RUN/'m4-enrichment-001/execution-receipt.json']+list(product.iterdir()))
 print('First actual M4 bundle built; relocated replay and actual negatives remain pending.',flush=True)
if __name__=='__main__':main()
