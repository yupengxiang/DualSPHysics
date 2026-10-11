"""Root-issued forward-only admission after actual M1--M3 and cost review."""
import datetime,fcntl,json,sys
from pathlib import Path
P=Path(__file__).resolve().parent;ROOT=P.parents[3]
sys.path.insert(0,str(ROOT/'lagrangian-fluid-lab/scripts'))
import ds_data02_runtime_v6_batch2 as b
DATA=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
def binding(p):return {'path':str(p),'sha256':b._sha256_file(p),'status':'complete','acceptance_status':'accepted'}
def main():
 path=P/'batch2-runtime/root-batch-2-admission.json';assert not path.exists()
 with (DATA/'runtime/resource-ledger.lock').open('a+') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX);l=json.loads((DATA/'runtime/resource-ledger.json').read_text());assert not l['reservations']
  cost=P/'batch2-runtime/M1-M3-cost-audit-v1.json';audit=json.loads(cost.read_text());assert audit['prior_usage']==b._usage(l['charges']) and audit['charged_ids']==sorted(r['id'] for r in l['charges'])
  d={'schema':b.ADMISSION_SCHEMA,'status':'admitted','issuer':'root','immutable':True,'batch_index':2,'previous_batch_index':1,'admitted_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'evidence':{m:binding(P/'milestone-evidence'/f'{m}-complete-v1.json') for m in ['M1','M2','M3']},'cost_audit':binding(cost),'batch_limits':{'gpu_seconds':86400,'cpu_core_seconds':345600,'solver_attempts':24,'additional_storage_bytes':224*1024**3},'storage_allocation_basis':{'scope':'Exactly four own depthconditions .50/.52/.58/.60, mother stays reference-only native pack; no optional motherfullHDF conversion.','bound_each_full_state_copy_GiB':11,'copy_counts_per_condition':4,'copies':'direct fullstates + immutable enriched copy + portable bundle + relocated replay copy','four_conditions_fullstate_GiB':176,'two_additional_solver_reservations_GiB':18,'new_gencase_and_metadata_GiB':2,'temporary_and_semantic_negative_peak_GiB':16,'subtotal_GiB':212,'bounded_headroom_GiB':12,'incremental_GiB':224,'historical_bytes_never_reset':True},'parent_ledger_path':str(DATA/'runtime/resource-ledger.json'),'parent_limits':l['limits'],'parent_deadline_utc':l['deadline_utc'],'prior_charged_ids':sorted(r['id'] for r in l['charges']),'prior_charge_row_sha256':{r['id']:b._row_hash(r) for r in l['charges']},'prior_attempt_ids':sorted(r['id'] for r in l['attempts']),'prior_attempt_row_sha256':{r['id']:b._row_hash(r) for r in l['attempts']},'prior_reservation_ids':[],'prior_usage':b._usage(l['charges']),'prior_charges_sha256':b._rows_projection_hash(l['charges'])}
  d['payload_sha256']=b._payload_hash(d)
  with path.open('x') as f:json.dump(d,f,ensure_ascii=False,indent=2);f.write('\n')
  b.validate_admission(path,data_root=DATA);b._live_parent_limits_match(l,d);b._baseline_rows_match(l,d)
 print(json.dumps({'status':'admitted','path':str(path),'payload_sha256':d['payload_sha256'],'incremental_storage_GiB':224,'cumulative_parent_history_preserved':True}))
if __name__=='__main__':main()
