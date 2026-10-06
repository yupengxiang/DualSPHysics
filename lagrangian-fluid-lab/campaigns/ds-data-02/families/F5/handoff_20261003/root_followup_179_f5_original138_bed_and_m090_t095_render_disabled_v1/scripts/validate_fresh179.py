#!/usr/bin/env python3
"""Metadata-only validator for F5 fresh179.

It hashes only package JSON/XML/Python/Markdown files and producer JSON/XML
metadata. It never opens or hashes H5, BI4, CSV, DAT, VTK, or other payloads.
"""
from __future__ import annotations
import hashlib, json
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
worker=PKG/'workers/identity_bound_bed_audit_fresh179.py'
check(worker.is_file(),'worker missing')
check(sha(worker)==load(PKG/'metadata/worker-contract.json')['adapter_sha256'],'worker hash')
source=load(PKG/'metadata/fresh179-source-plan.json'); check(source['execution_allowed'] is False and source['launch_allowed'] is False,'source enabled')
for case in source['cases']:
 b=load(case['binding']); q=load(case['request']); c=load(case['chain'])
 check(b['execution_allowed'] is False and b['disabled'] is True and b['full801_authorized'] is False,'bed binding enabled')
 check(q['execution_allowed'] is False and q['disabled'] is True and q['full801_authorized'] is False,'bed request enabled')
 check(b['case_id']==case['case_id'] and q['case_id']==case['case_id'] and c['case_id']==case['case_id'],'identity')
 check(b['physical_case_id']==case['physical_case_id'],'physical identity')
 check(b['expected_frames']==801 and b['expected_dimension']==3 and b['expected_particle_axis']==194427,'axis')
 check(b['expected_fluid_particles']==31658 and b['expected_fixed_particles']==158559 and b['expected_moving_particles']==4210,'counts')
 check(b['native_bed_marker_mk']==50 and b['source_bed_marker_mkbound']==40,'Mk mapping')
 check(len({b['physical_condition_sha256'],b['source_plan_physical_condition_sha256'],b['source_h5_physical_condition_sha256']})==3,'scope collapse')
 check(b['actual_initial_qa_basic_placement_pass'] is True and b['actual_initial_qa_precision_check']['accepted'] is False,'QA gate')
 check(b['bed_audit_receipt'] is None and b['bed_audit_report'] is None,'future bed not null')
 for key,hkey in [('source_definition','source_definition_sha256'),('source_plan_file','source_plan_file_sha256'),('owner_metadata','owner_metadata_sha256'),('source_generation_report','source_generation_report_sha256'),('gencase_receipt','gencase_receipt_sha256'),('gencase_prepared_report','gencase_prepared_report_sha256'),('canonical_generated_xml','canonical_generated_xml_sha256'),('initial_qa_receipt','initial_qa_receipt_sha256'),('initial_qa_report','initial_qa_report_sha256'),('actual_initial_qa_producer_metadata','actual_initial_qa_producer_metadata_sha256'),('full_native_receipt','full_native_receipt_sha256'),('full_typed_receipt','full_typed_receipt_sha256'),('full_typed_conversion_report','full_typed_conversion_report_sha256'),('xmf_manifest','xmf_manifest_sha256'),('xmf_receipt','xmf_receipt_sha256'),('xdmf','xdmf_sha256')]:
  p=path(b[key]); check(p.is_file(),f'metadata path {key}'); check(sha(p)==b[hkey],f'metadata hash {key}')
 for p,h in q['input_sha256'].items():
  pp=path(p); check(pp.suffix.lower() not in SCIENCE,'bed request science input'); check(pp.is_file() and sha(pp)==h,'bed request input closure')
 xmf=load(b['xmf_manifest']); check(xmf['case_id']==case['case_id'] and xmf['frames']==801 and xmf['particles']==194427,'XMF dimensions')
 gen=load(b['gencase_prepared_report']); check(gen['case_id']==case['case_id'] and gen['actual_total_particles']==194427,'GenCase report')
 qa=load(b['initial_qa_report']); check(qa['all_basic_placement_checks_pass'] is True and qa['numerical_precision_result_accepted'] is False,'QA report')
 for receipt_key in ['gencase_receipt','initial_qa_receipt','full_native_receipt','full_typed_receipt','xmf_receipt']:
  d=load(b[receipt_key]); check(d.get('status')=='completed' and d.get('returncode')==0,f'{receipt_key} status')
rb=load(PKG/'bindings/M090_T095-full801-original116-023-944-render-binding.json'); rr=load(PKG/'requests/M090_T095-disabled-original116-023-944-render-request.json'); rc=load(PKG/'metadata/M090_T095-actual1055-bed-render-chain.json')
check(rb['disabled'] is True and rb['execution_allowed'] is False and rr['disabled'] is True and rr['execution_allowed'] is False,'render enabled')
check(rr['expected_contact_sheets']==34 and rr['expected_frames']==801 and rr['expected_particles']==194427,'render shape')
check(rb['actual_bound_inputs']['case_id']==rr['case_id'] and rb['bed_gate']['all801_frame_records_present'] is True,'render bed identity')
check(rb['renderer_gate']['future_manifest_sha256'] is None and rr['future_output_hashes']['png_sha256'] is None,'future render hashes')
check(rb['bed_gate']['physical_pass_not_inferred_from_exit0'] is True,'exit0 overclaim')
check(rc['actual_bed']['summary']['frames_scanned']==801,'actual1055 bed frames')
for p,h in rr['input_sha256'].items():
 pp=path(p)
 if pp.suffix.lower() in SCIENCE:
  check(p==rr['trajectory_h5'] and h==rr['trajectory_h5_sha256_producer_attested'],'only producer H5 attestation')
 else:
  check(pp.is_file() and sha(pp)==h,'render input closure')
print('PASS fresh179 metadata-only contract')
print(f'{len(source["cases"])} disabled original138 bed bindings + 1 disabled M090_T095 34-contact render gate')
print('all actual upstream statuses completed/0; future bed/render outputs remain null')
