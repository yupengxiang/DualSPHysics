#!/usr/bin/env python3
from __future__ import annotations
import hashlib, importlib.util, json
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
REQ = HERE / 'requests/initial-native-qa-196.request.json'
BIND = HERE / 'source-binding.json'
EVID = HERE / 'evidence/root195-gencase-evidence-binding.json'
VALIDATOR = HERE / 'workers/validate_f4_initial_native_v4.py'

def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()

def load_module(path: Path):
    spec = importlib.util.spec_from_file_location('fresh082_validator_test', path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def test_request():
    d=json.loads(REQ.read_text())
    assert d['kind']=='cpu' and d['cpu_task_kind']=='audit'
    assert d['estimated_storage_bytes'] > 0 and d['cpu_threads']==2
    assert d['launch'] is False and d['launch_allowed'] is False and d['status']=='source_only_disabled'
    assert d['independent_case_count_increment']==0
    assert not any(Path(f).suffix.lower() in {'.bi4','.h5','.csv','.vtk'} for f in d['input_files'])
    assert len(d['input_files']) == len(d['input_sha256'])
    for f,h in d['input_sha256'].items():
        assert sha(Path(f)) == h, f
    assert any(Path(f).suffix.lower()=='.bi4' for f in d['deferred_input_files'])
    assert d['deferred_input_sha256'][next(f for f in d['deferred_input_files'] if f.endswith('.bi4'))] is None

def test_root195_binding():
    b=json.loads(BIND.read_text()); e=json.loads(EVID.read_text())
    assert b['upstream_adopted_commit']=='ae0d8a25'
    assert e['aggregate_execution_receipt']['status']=='failed'
    assert e['aggregate_execution_receipt']['returncode']==0
    assert e['aggregate_execution_receipt']['error']=='GenCase actual particle count missing'
    assert e['aggregate_execution_receipt']['preserved_without_promotion'] is True
    rows=e['per_case_actual_gencase_receipts']
    assert len(rows)==8 and all(r['gencase_receipt_status']=='completed' and r['per_case_os_returncode']==0 for r in rows)
    assert all(r['solver_dimension_from_gencase']==3 for r in rows)
    assert all(r['generated_xml']['sha256']==r['generated_xml']['observed_xml_sha256'] for r in rows)
    assert all(r['generated_bi4']['content_rehashed_by_source'] is False for r in rows)

def test_dynamic_xml_and_native_aliases():
    mod=load_module(VALIDATOR)
    evidence=json.loads(EVID.read_text())
    row=evidence['per_case_actual_gencase_receipts'][0]
    receipt=json.loads(Path(row['gencase_receipt']).read_text())
    endpoint={'endpoint_id':row['endpoint_id']}
    parsed=mod.parse_generated_xml(Path(row['generated_xml']['path']), endpoint, receipt)
    assert parsed['total_particles']==receipt['total_particles']
    assert parsed['fluid_particles']==receipt['fluid_particles']
    assert parsed['fixed_particles']==receipt['fixed_particles']
    assert parsed['solver_dimension_from_gencase']==3
    source=VALIDATOR.read_text()
    for forbidden in ('83233','59072','24161'):
        assert forbidden not in source, forbidden
    native={
      'pass':True,'native_audit_returncode':0,
      'checks':{
        'finite_tank_face_coverage':True,
        'drop_and_pool_bounds_are_separated':True,
        'complete_type_partition':True,
        'positive_drop_and_pool_source_rows':True,
        'finite_unique_complete_ids':True,
        'true_3d':True,
        'all_source_population_checks':True,
      },
      'source_rows':[
        {'source':'drop','fluid_count':1,'bounds_m':[[0,0,1],[1,1,2]],'checks':{'finite':True}},
        {'source':'pool','fluid_count':1,'bounds_m':[[0,0,0],[1,1,1]],'checks':{'finite':True}},
      ],
    }
    checked=mod.native_checks(native,'synthetic-case')
    assert checked['pass'] is True

if __name__ == '__main__':
    test_request(); test_root195_binding(); test_dynamic_xml_and_native_aliases(); print('fresh082 contract: PASS')
