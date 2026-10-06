#!/usr/bin/env python3
"""Metadata-only validator for F5 fresh173.

It may read JSON/XML/Python/source metadata and stat producer payload paths.  It
never opens or hashes BI4/DAT/CSV/H5/VTK/science payloads.
"""
from __future__ import annotations
import hashlib, json, runpy, sys
from pathlib import Path

PKG=Path(__file__).resolve().parents[0].parent
INTEGRATION=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics')
VENV=INTEGRATION/'lagrangian-fluid-lab/.venv/bin/python'
CONVERTER=INTEGRATION/'lagrangian-fluid-lab/scripts/ds_data02_direct_convert.py'
TAGS=['M110_T095','M112_T085','M112_T095','M114_T085','M114_T095','M110_T100']
SAFE={'.json','.xml','.py','.md','.sh','.toml','.ini','.yaml','.yml'}
SCI={'.bi4','.dat','.csv','.h5','.vtk','.vtu','.pvtu','.npy','.npz','.png','.jpg','.jpeg'}
EXPECTED={'total_particles':194427,'fixed_particles':158559,'moving_particles':4210,'floating_particles':0,'fluid_particles':31658,'solver_dimension':3,'data2d':False}
SCOPE_KEYS={'schema','semantic_binding_status','continuum_geometry','gravity_m_s2','initial_state','geometry','parameters'}

def load(p): return json.loads(Path(p).read_text())
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()
def assert_file(p):
    p=Path(p); assert p.is_file(), f'not a regular file: {p}'
def metadata_status(path):
    d=load(path)
    status=d.get('status',d.get('state',d.get('result')))
    rc=d.get('returncode',d.get('return_code',d.get('exit_code')))
    return d,status,rc

def main():
    assert PKG.name=='root_followup_173_f5_native1017_remaining6_typed157_home4gib_disabled_v1'
    plan=load(PKG/'metadata/fresh173-source-plan.json')
    assert plan['schema']=='ds02.f5.fresh173.source-plan.v1'
    assert plan['selected_tags']==TAGS
    assert plan['direct_converter_scope_preflight']['python']==str(VENV)
    assert plan['direct_converter_scope_preflight']['script']==str(CONVERTER)
    assert plan['direct_converter_scope_preflight']['science_payloads_read_or_hashed'] is False
    # The exact producer helper is executed in the requested integration venv; owner files are metadata JSON.
    direct=runpy.run_path(str(CONVERTER))
    scope_fn=direct['_physical_condition_scope']; canonical_hash=direct['canonical_hash']
    reports=[]
    expected_native_prefix='root_stage1_F5_source170_eleven_genuinely_unfinished_own848849_full801_native230_fair_GPU_CPU2_1017'
    for tag in TAGS:
        req_path=PKG/'requests'/f'{tag}-typed157-home4gib-request.json'
        bind_path=PKG/'bindings'/f'{tag}-native-ready-typed157-binding.json'
        req=load(req_path); bind=load(bind_path)
        assert req['tag']==bind['tag']==tag
        assert req['package_id']==bind['package_id']==plan['package_id']
        assert req['physical_case_id']==bind['physical_case_id']
        assert req['physical_condition_sha256']==bind['physical_condition_sha256']
        assert req['source_plan_physical_condition_sha256']==bind['source_plan_physical_condition_sha256']
        assert req['binding']==str(bind_path) and req['binding_sha256']==sha(bind_path)
        assert bind.get('fresh173_source_plan_audit')=='metadata/fresh173-source-plan.json'
        assert 'fresh172' not in json.dumps(bind,sort_keys=True)
        for key in ('disabled','source_only'):
            assert req[key] is True and bind[key] is True
        for key in ('launch','launch_allowed','execution_allowed','conversion_allowed','solver_allowed','arrays_allowed','array_edit_allowed','full801_authorized','full_native_authorized'):
            assert req.get(key) is False, (tag,key,req.get(key))
        for key in ('launch_allowed','execution_allowed','conversion_allowed','solver_allowed'):
            assert bind.get(key) is False, (tag,key,bind.get(key))
        assert req['kind']=='cpu' and req['cpu_task_kind']=='conversion' and req['cpu_threads']==2
        assert req['omp_threads']==1 and req['shared_conversion_concurrency_cap']==1
        assert req['home_publish_cap_bytes']==4*1024**3
        assert req['home_min_free_bytes']==500*1024**3
        assert req['home_publish_headroom_bytes']==2*1024**3
        assert req['nvme_staging_limit_bytes']==24*1024**3
        assert req['nvme_free_reserve_bytes']==100*1024**3
        assert req['native_bed_marker_mk']==50 and req['source_bed_marker_mkbound']==40
        assert req['expected_frames']==req['expected_native_frames']==801
        assert req['expected_particle_axis']==194427 and req['expected_dimension']==3 and req['expected_data2d'] is False
        for k,v in EXPECTED.items(): assert req['actual_counts'][k]==v and bind['actual_counts'][k]==v,(tag,k)
        assert req['actual_counts']['xml_particle_counts']=={'fixed':158559,'moving':4210,'floating':0,'fluid':31658}
        assert req['typed_future']['attempt_id'] is None
        assert all(v is None for k,v in req['typed_future'].items() if k.endswith('_sha256'))
        assert all(v is None for k,v in req['future_output_hashes'].items())
        assert all(v is None for k,v in bind['future_output_hashes'].items())
        # Full native dependency is a completed producer metadata receipt, not a source-side rerun.
        native_req=Path(req['actual_native_request']); native_receipt=Path(req['actual_native_receipt'])
        assert_file(native_req); assert_file(native_receipt)
        assert native_req.name==f'{tag}-full801-native-request.json'
        assert native_req.parent.name=='requests' and expected_native_prefix in str(native_req)
        nr=load(native_req); nrm=load(native_receipt)
        assert nr['case_id']==req['case_id'] and nr['physical_case_id']==req['physical_case_id'] and nr['attempt_id']==req['depends_on_attempt']
        assert nrm.get('status')=='completed' and nrm.get('returncode')==0
        assert req['actual_native_receipt_sha256']==sha(native_receipt)
        assert req['actual_native_request_sha256']==sha(native_req)
        assert req['actual_native_request_producer_sha256']==sha(native_req)
        assert req['actual_native_status']=='completed' and req['actual_native_receipt_returncode']==0
        # GenCase and initial QA are real metadata receipts/reports and are not guessed counts.
        for field in ('gencase_receipt','prepared_input_report','actual_initial_qa_receipt','actual_initial_qa_report','source_owner','source_definition','source_plan'):
            assert_file(req[field])
        gr,gs,grc=metadata_status(req['gencase_receipt']); qr,qs,qrc=metadata_status(req['actual_initial_qa_receipt'])
        assert gs=='completed' and (grc in (0,None) or gr.get('returncode')==0), (tag,gs,grc)
        assert qs=='completed' and (qrc in (0,None) or qr.get('returncode')==0), (tag,qs,qrc)
        assert req['actual_initial_qa_basic_placement_pass'] is True
        assert req['actual_initial_qa_precision_check']['accepted_as_stage1_placement_gate'] is False
        # Exact helper scope: this checks the full scope fields, not a hand-picked subset.
        owner=load(req['source_owner']); expected_scope=scope_fn(owner); expected_scope_sha=canonical_hash(expected_scope)
        assert req['source_h5_legacy_scope']['sha256']==expected_scope_sha
        assert req['source_h5_legacy_scope_sha256']==expected_scope_sha==req['root_prospective_legacy_scope_sha256']
        assert set(expected_scope)>=SCOPE_KEYS
        assert req['source_h5_legacy_scope']['cross_resolution_claim'] is False
        assert req['canonical_physical_scope']['cross_resolution_claim'] is False
        assert req['canonical_physical_scope']['canonical_condition_sha256']==req['physical_condition_sha256']
        assert req['typed_future']['legacy_scope_sha256'] is None
        assert req['motion_asset']['source_did_not_read_or_hash'] is True
        motion=Path(req['motion_asset']['path']); assert_file(motion)
        # Registered input closure: safe metadata/code is current hashed; science/binary bytes are attested only.
        assert len(req['input_files'])==len(set(req['input_files']))
        assert set(req['input_files'])==set(req['input_sha256'])==set(req['input_sha256_categories'])==set(req['input_sha256_provenance'])
        for x,h in req['input_sha256'].items():
            p=Path(x); assert_file(p); assert isinstance(h,str) and len(h)==64 and all(c in '0123456789abcdef' for c in h)
            cat=req['input_sha256_categories'][x]
            if p.suffix.lower() in SAFE:
                assert cat=='metadata_current_hash' and sha(p)==h,(tag,x)
            elif p.suffix.lower() in SCI:
                assert cat=='producer_payload_attestation' and 'did not read/hash' in req['input_sha256_provenance'][x]
            else:
                assert cat in ('registered_binary_attestation','producer_payload_attestation'),(tag,x,cat)
        # No stale fresh172 identity or old target token remains in the serialized source binding/request.
        blob=json.dumps({'req':req,'bind':bind},sort_keys=True)
        assert 'fresh172' not in blob and 'M110_T080' not in blob
        reports.append({'tag':tag,'status':'pass','scope_sha256':expected_scope_sha,'actual_native_receipt':str(native_receipt),'input_count':len(req['input_files'])})
    # Plan and dedup sidecars are also metadata only.
    dd=load(PKG/'metadata/fresh173-dedup-audit.json')
    assert dd['selected_records'] and all(x['eligible_by_identity'] and not x['matches_in_checkpoint152'] for x in dd['selected_records'])
    live=load(PKG/'metadata/fresh173-root984-root1016-status.json')
    assert live['root984']['state'].startswith('WAIT') and live['root1016']['state'].startswith('WAIT')
    assert live['science_payloads_read_or_hashed_by_source_agent'] is False
    result={'schema':'ds02.f5.fresh173.validator-report.v1','status':'pass-disabled-metadata-only','package_id':plan['package_id'],'selected_tags':TAGS,'cases':reports,'science_payloads_read_or_hashed':False,'jobs_started':False,'future_science_hashes_claimed':False,'precision_negative_retained':True,'full_visual_gate_future':True}
    print(json.dumps(result,indent=2,sort_keys=True))
    return result
if __name__=='__main__': main()
