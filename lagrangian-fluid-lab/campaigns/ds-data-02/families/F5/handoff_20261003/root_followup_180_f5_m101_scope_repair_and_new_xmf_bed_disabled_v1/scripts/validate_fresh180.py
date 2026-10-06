#!/usr/bin/env python3
'Metadata-only validator for F5 fresh180.'
from __future__ import annotations
import hashlib,json,subprocess,sys
from pathlib import Path
PKG=Path(__file__).resolve().parents[0].parent
SCIENCE={'.h5','.hdf5','.bi4','.ibi4','.csv','.dat','.vtk','.vtu','.npy','.npz'}
def load(p): return json.loads(Path(p).read_text(encoding='utf-8'))
def sha(p):
 p=Path(p)
 if p.suffix.lower() in SCIENCE: raise AssertionError(f'science payload hash forbidden: {p}')
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()
def check(x,m):
 if not x: raise SystemExit('FAIL: '+m)
def path(x): return Path(str(x))
source=load(PKG/'metadata/fresh180-source-plan.json'); check(source['execution_allowed'] is False and len(source['cases'])==6,'source plan')
worker=PKG/'workers/identity_bound_bed_audit_fresh180.py'; check(worker.is_file(),'worker')
check(sha(worker)==load(PKG/'metadata/worker-contract.json')['adapter_sha256'],'worker hash')
for case in source['cases']:
 b=load(case['binding']); q=load(case['request']); c=load(case['chain'])
 check(b['execution_allowed'] is False and b['disabled'] is True and q['execution_allowed'] is False and q['disabled'] is True,'disabled')
 check(b['case_id']==case['case_id'] and q['case_id']==case['case_id'] and c['case_id']==case['case_id'],'identity')
 check(b['expected_frames']==801 and b['expected_dimension']==3 and b['expected_particle_axis']==194427,'axis')
 check(b['expected_fluid_particles']==31658 and b['expected_fixed_particles']==158559 and b['expected_moving_particles']==4210,'counts')
 check(b['native_bed_marker_mk']==50 and b['source_bed_marker_mkbound']==40,'Mk')
 check(len({b['physical_condition_sha256'],b['source_plan_physical_condition_sha256'],b['source_h5_physical_condition_sha256']})==3,'scope collapse')
 check(b['source_h5_physical_condition_sha256']==b['typed_report_physical_condition_sha256'],'typed scope binding')
 check(isinstance(b.get('producer_xmf_historical_legacy_scope_sha256'),str) and b.get('historical_scope_not_used_for_actual_binding') is True,'historical scope role')
 check(b['bed_audit_receipt'] is None and b['bed_audit_report'] is None,'future bed')
 for key,hkey in [('source_definition','source_definition_sha256'),('source_plan_file','source_plan_file_sha256'),('owner_metadata','owner_metadata_sha256'),('source_generation_report','source_generation_report_sha256'),('gencase_receipt','gencase_receipt_sha256'),('gencase_prepared_report','gencase_prepared_report_sha256'),('canonical_generated_xml','canonical_generated_xml_sha256'),('initial_qa_receipt','initial_qa_receipt_sha256'),('initial_qa_report','initial_qa_report_sha256'),('actual_initial_qa_producer_metadata','actual_initial_qa_producer_metadata_sha256'),('full_native_receipt','full_native_receipt_sha256'),('full_typed_receipt','full_typed_receipt_sha256'),('full_typed_conversion_report','full_typed_conversion_report_sha256'),('xmf_manifest','xmf_manifest_sha256'),('xmf_receipt','xmf_receipt_sha256'),('xdmf','xdmf_sha256')]:
  p=path(b[key]); check(p.is_file(),f'path {key}'); check(sha(p)==b[hkey],f'hash {key}')
 for p,h in q['input_sha256'].items():
  pp=path(p); check(pp.suffix.lower() not in SCIENCE and pp.is_file() and sha(pp)==h,'request input closure')
 xmf=load(b['xmf_manifest']); check(xmf['case_id']==case['case_id'] and xmf['frames']==801 and xmf['particles']==194427,'XMF shape')
 check(xmf.get('source_h5_physical_condition_sha256')==b['source_h5_physical_condition_sha256'],'XMF actual producer scope')
 check(xmf.get('source_h5_legacy_scope_sha256')==b['producer_xmf_historical_legacy_scope_sha256'],'historical producer scope')
 gen=load(b['gencase_prepared_report']); check(gen['case_id']==case['case_id'] and gen['actual_total_particles']==194427,'GenCase')
 qa=load(b['initial_qa_report']); check(qa['all_basic_placement_checks_pass'] is True and qa['numerical_precision_result_accepted'] is False,'QA')
 for k in ['gencase_receipt','initial_qa_receipt','full_native_receipt','full_typed_receipt','xmf_receipt']:
  d=load(b[k]); check(d.get('status')=='completed' and d.get('returncode')==0,k)
m101=next(c for c in source['cases'] if c['tag']=='M101_T100'); mb=load(m101['binding']); mc=load(m101['chain'])
check(mb['source_h5_physical_condition_sha256']=='80039c17cc7a088b7bc0fdc5c7a74d9051aa72763652261e2823635fcd5ad93d','M101 actual scope')
check(mc['physical_scopes']['producer_xmf_historical_legacy_scope_sha256']=='37c47df9bf900444e6d0dafcb41af77a8a0d9ff9e777fbf8c3cd056512642235','M101 old scope retained')
run=subprocess.run([sys.executable,str(worker),'--check'],check=False,text=True,capture_output=True)
check(run.returncode==0,'original138 metadata gate: '+run.stdout[-500:]+run.stderr[-500:])
print('PASS fresh180 metadata-only contract: M101 scope repair + 5 new disabled bed bindings')
print('original138 pre-array metadata gate passed; future bed receipts/reports remain null')
