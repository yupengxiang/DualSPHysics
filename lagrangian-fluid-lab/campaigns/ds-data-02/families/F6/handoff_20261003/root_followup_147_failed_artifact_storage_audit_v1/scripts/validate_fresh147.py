"""Validate fresh147 package metadata only; never accesses DATA scientific payloads."""
from __future__ import annotations
import json, pathlib
PKG=pathlib.Path(__file__).resolve().parents[1]
def load(name): return json.loads((PKG/'metadata'/name).read_text())
def main():
 inv=load('failure-artifact-reference-audit.json'); base=load('root965-cleanup-baseline.json'); large=load('large-failure-review.json'); summary=load('receipt-inventory-summary.json')
 assert inv['schema']=='ds02.failed-artifact-storage-audit.fresh147.v1'
 assert base['failed_attempts_cleaned']==14 and base['deleted_files']==15995
 assert abs(base['deleted_payload_GiB']-439.00610971078277)<1e-9
 assert base['main_and_cleanup_worker_scientific_payload_contents_IO'] is False
 assert large['safe_deletion_candidates']==[] and large['root965_not_repeated'] is True
 assert len(large['f6_domain_audit_attempts_retained'])==2
 f5=[x for x in large['selected_large_and_downstream_failures'] if 'native-render-590-root610' in x['attempt_dir']]
 assert len(f5)==2 and all(x['returncode']==-15 and x['termination_reason']=='reserved_cpu_budget_exceeded' and x['metadata_reference_count']>0 for x in f5)
 root981=[x for x in large['selected_large_and_downstream_failures'] if 'root981' in x['attempt_dir']]
 assert len(root981)==1 and root981[0]['metadata_reference_count']>0
 assert inv['policy']['scientific_payloads_opened'] is False and inv['policy']['scientific_payloads_hashed'] is False and inv['policy']['deletion_performed'] is False
 assert summary['read_policy'].startswith('execution-receipt.json')
 forbidden={'.bi4','.h5','.csv','.dat','.vtk','.vtu','.jsonl','.ibi4','.obi4'}
 assert not [str(p) for p in PKG.rglob('*') if p.is_file() and p.suffix.lower() in forbidden]
 print('fresh147 validator PASS: no deletion; root965 baseline and F5 downstream references closed; F6 domain-audit dependencies retained')
if __name__=='__main__': main()
