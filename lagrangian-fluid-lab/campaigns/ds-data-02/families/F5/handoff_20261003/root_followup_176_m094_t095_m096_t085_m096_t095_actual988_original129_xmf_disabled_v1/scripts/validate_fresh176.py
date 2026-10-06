#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
PKG=Path(__file__).resolve().parents[1]
SCIENCE_SUFFIXES={'.h5','.hdf5','.bi4','.ibi4','.csv','.dat','.vtk','.vtu','.npy','.npz'}
def require(ok,msg):
    if not ok: raise ValueError(msg)
def sha(path:Path):
    require(path.suffix.lower() not in SCIENCE_SUFFIXES, f'science hash forbidden: {path}')
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()
def load(path):
    d=json.loads(Path(path).read_text(encoding='utf-8')); require(isinstance(d,dict),f'JSON object expected: {path}'); return d
def check_case(binding_path):
    b=load(binding_path); tag=b['tag']; require(b['schema']=='ds02.f5.actual988-full801-typed-to-N3-XMF-binding.fresh176.v1',f'{tag}: schema'); require(b['disabled'] is True and b['execution_allowed'] is False and b['launch_allowed'] is False and b['solver_allowed'] is False,f'{tag}: disabled flags'); require(b['xmf_manifest_sha256'] is None and b['xdmf_sha256'] is None and b['xmf_receipt_sha256'] is None,f'{tag}: future hash bound'); require(b['expected_counts']['total_particles']==194427 and b['expected_counts']['fluid_particles']==31658,f'{tag}: counts')
    for pk,hk in [('source_owner','owner_metadata_sha256'),('source_definition','source_definition_sha256'),('source_plan','source_plan_sha256'),('source_generation_report','source_generation_report_sha256'),('gencase_receipt','gencase_receipt_sha256'),('gencase_prepared_report','gencase_prepared_report_sha256'),('generated_xml','generated_xml_sha256'),('initial_qa_receipt','initial_qa_receipt_sha256'),('initial_qa_report','initial_qa_report_sha256'),('actual_initial_qa_producer_metadata','actual_initial_qa_producer_metadata_sha256'),('native_receipt','native_receipt_sha256'),('native_request','native_request_sha256'),('typed_receipt','typed_receipt_sha256'),('typed_request','typed_request_sha256'),('conversion_report','conversion_report_sha256')]:
        p=Path(b[pk]); require(p.is_file(),f'{tag}: missing {pk}'); require(sha(p)==b[hk],f'{tag}: {pk} SHA')
    gen=load(b['gencase_receipt']); qa_receipt=load(b['initial_qa_receipt']); native=load(b['native_receipt']); typed=load(b['typed_receipt']); prep=load(b['gencase_prepared_report']); qa=load(b['initial_qa_report']); conv=load(b['conversion_report']); owner=load(b['source_owner'])
    for name,r in [('GenCase',gen),('QA',qa_receipt),('native',native),('typed',typed)]: require(r.get('status')=='completed' and r.get('returncode')==0,f'{tag}: {name} receipt')
    require(prep.get('actual_total_particles')==194427 and prep.get('generated_xml_particle_counts')=={'fixed':158559,'moving':4210,'floating':0,'fluid':31658},f'{tag}: prepared counts')
    require(qa.get('all_basic_placement_checks_pass') is True and qa.get('stage1_basic_placement_proof')=='pass_excluding_numerical_precision' and qa.get('numerical_precision_result_accepted') is False,f'{tag}: QA')
    require(len(qa.get('mk50_coverage',{}).get('six_segment_bins',[]))==6 and all(int(x.get('central_abs_y_le_0p01_surface_half_dp_count',0))>0 for x in qa['mk50_coverage']['six_segment_bins']),f'{tag}: Mk50')
    require(conv.get('conversion_status')=='completed' and conv.get('frames')==801 and conv.get('particles')==194427 and conv.get('solver_dimension',{}).get('solver_dimension')==3,f'{tag}: typed')
    actual_scope=conv.get('hash_scopes',{}).get('physical_condition_sha256'); require(isinstance(actual_scope,str) and len(actual_scope)==64 and b['source_h5_physical_condition_sha256']==actual_scope,f'{tag}: typed scope')
    require(b['physical_condition_sha256']==native.get('request',{}).get('physical_condition_sha256'),f'{tag}: native canonical')
    require(b['source_plan_physical_condition_sha256']==native.get('request',{}).get('source_plan_physical_condition_sha256'),f'{tag}: native plan')
    require(owner.get('physical_condition_sha256')==b['owner_physical_condition_sha256']==b['physical_condition_sha256'],f'{tag}: owner/native role')
    h5=Path(b['trajectory_h5']); require(h5.is_file() and h5.suffix.lower()=='.h5',f'{tag}: H5 path'); require(isinstance(b['trajectory_h5_sha256'],str) and len(b['trajectory_h5_sha256'])==64,f'{tag}: H5 attestation'); require(b['trajectory_h5_read_or_rehashed_by_source_agent'] is False,f'{tag}: H5 source claim')
    return {'tag':tag,'case_id':b['case_id'],'physical_case_id':b['physical_case_id'],'metadata_gate':'passed','actual_converter_scope_sha256':actual_scope,'native_canonical_scope_sha256':b['physical_condition_sha256'],'future_xmf_hashes_null':True,'science_payload_opened_or_hashed':False}
def main():
    p=argparse.ArgumentParser(); p.add_argument('--check',action='store_true'); p.add_argument('--report',type=Path); a=p.parse_args(); require(a.check,'--check required')
    rows=[check_case(p) for p in sorted((PKG/'bindings').glob('*.json'))]
    out={'schema':'ds02.f5.fresh176.validator-report.v1','status':'passed','source_only':True,'science_payload_opened_or_hashed':False,'manifest_excludes_this_report':True,'checks':rows}; text=json.dumps(out,ensure_ascii=False,indent=2,sort_keys=True)+'\n'; print(text,end='');
    if a.report: a.report.write_text(text,encoding='utf-8')
    return 0
if __name__=='__main__': raise SystemExit(main())
