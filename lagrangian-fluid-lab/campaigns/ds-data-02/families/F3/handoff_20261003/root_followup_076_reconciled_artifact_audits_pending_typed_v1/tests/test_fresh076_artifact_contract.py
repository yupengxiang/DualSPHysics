#!/usr/bin/env python3
"""Fresh076 semantic tests; no production receipt or payload is read."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile

HERE = Path(__file__).resolve().parents[1]

def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

W = load_module('fresh076_worker', HERE / 'artifact_integrity_worker.py')
G = load_module('fresh076_gate', HERE / 'recovery_aware_pipeline_gate.py')

def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, sort_keys=True) + '\n', encoding='utf-8')

def fixture(root: Path) -> dict:
    h5 = root / 'trajectory.h5'; h5.write_bytes(b'opaque synthetic bytes; no decoder')
    out = digest(h5)
    physical = 'F3_TWOAXIS_PITCH1000_AY0270_STAGE1_FIRST24_NEW'
    condition = 'a6a7dfcc6a3c45b895ae096d652c4bf4d203b6b3b9d228e40c7c7518e8d109e9'
    report_condition = '217fbe56b0a884a75199c2aabef347872558260395688dcaee30c0c9a3719413'
    receipt = root/'execution-receipt.json'; report=root/'conversion-report.json'; stdout=root/'stdout.log'; native=root/'native-receipt.json'
    write_json(receipt, {'status':'running','returncode':None,'request':{'attempt_id':'typed-154','physical_case_id':physical,'physical_condition_sha256':condition,'expected_saved_frames':836}})
    write_json(report, {'conversion_status':'completed','frames':836,'particles':179208,'output_sha256':out,'output_hdf5':str(h5),'partvtk_validation':{'all_passed':True},'storage_protocol':{'verified_published_output_sha256':out},'hash_scopes':{'physical_condition':{'physical_case_id':physical},'physical_condition_sha256':report_condition}})
    stdout.write_text(f'published output sha256={out}\n', encoding='utf-8')
    write_json(native, {'status':'completed','returncode':0,'request':{'physical_case_id':physical,'physical_condition_sha256':condition,'expected_saved_frames':836}})
    return {'receipt':receipt,'report':report,'stdout':stdout,'h5':h5,'native':native,'physical_case':physical,'physical_condition':condition,'report_condition':report_condition,'frames':836,'particles':179208,'output_hash':out}

def test_worker_and_gate():
    with tempfile.TemporaryDirectory() as td:
        f=fixture(Path(td))
        audit=W.audit(receipt_path=f['receipt'],report_path=f['report'],stdout_path=f['stdout'],trajectory_path=f['h5'],native_receipt_path=f['native'],expected_receipt_sha256=digest(f['receipt']),expected_report_sha256=digest(f['report']),expected_native_receipt_sha256=digest(f['native']),expected_output_sha256=f['output_hash'],expected_report_physical_condition_sha256=f['report_condition'],expected_frames=f['frames'],expected_particles=f['particles'],physical_case_id=f['physical_case'],physical_condition_sha256=f['physical_condition'],old_tool_status=143)
        assert audit['worker_returncode']==0 and audit['source_conversion_lifecycle']['receipt_returncode'] is None
        assert audit['source_receipt_edited'] is False and audit['source_conversion_reclassified'] is False
        ap=Path(td)/'audit.json'; write_json(ap,audit)
        for stage in ('normal','export','render'):
            result=G.prepare(stage=stage,source_receipt_path=f['receipt'],report_path=f['report'],audit_path=ap,native_receipt_path=f['native'],physical_case_id=f['physical_case'],physical_condition_sha256=f['physical_condition'],expected_frames=f['frames'],expected_particles=f['particles'])
            assert result['schema']=='ds02.fresh076.recovery-aware-pipeline-binding.v1'
            assert result['output_contract']['status']=='prepared_disabled'
        src=json.loads(f['receipt'].read_text()); src['status']='completed'; src['returncode']=0; write_json(f['receipt'],src)
        try: G.prepare(stage='normal',source_receipt_path=f['receipt'],report_path=f['report'],audit_path=ap,native_receipt_path=f['native'],physical_case_id=f['physical_case'],physical_condition_sha256=f['physical_condition'],expected_frames=f['frames'],expected_particles=f['particles'])
        except G.PipelineGateError: pass
        else: raise AssertionError('completed/0 source receipt was accepted')

def test_package_contracts():
    settlement=json.loads((HERE/'evidence/root184-reconciliation-settlement-binding.json').read_text())
    assert settlement['aggregate_charge']['cpu_core_seconds']==32400
    assert settlement['aggregate_charge']['cpu_core_hours']==9.0
    assert all(c['original_receipt']['source_returncode_observed'] is None for c in settlement['cases'])
    for name in ('p03_artifact_integrity_request.json','ay0270_artifact_integrity_request.json'):
        d=json.loads((HERE/'requests'/name).read_text()); assert d['cpu_task_kind']=='audit'; assert d['execution_allowed'] is False; assert d['output_contract']['sha256'] is None; assert d['source_conversion_returncode'] is None; assert d['source_conversion_tool_status']==143; assert d['opaque_h5_input_sha256'] is None
    pending=json.loads((HERE/'requests/pending_native_typed_bindings.json').read_text()); assert pending['case_count']==14
    assert pending['cpu_threads_per_request']==2 and pending['nvme_concurrency_cap']==2
    for c in pending['cases']:
        q=json.loads(Path(c['request']['path']).read_text()); assert q['execution_allowed'] is False; assert q['cpu_threads']==2; assert q['future_typed_outputs']['trajectory_h5']['sha256'] is None; assert q['native_full836_binding']['receipt']['status']=='completed'
    render=json.loads((HERE/'requests/actual_typed_ay0290_ay0300_xmf_render_bindings.json').read_text()); assert render['case_count']==2
    for c in render['cases']:
        x=json.loads(Path(c['normal_xmf_request']['path']).read_text()); r=json.loads(Path(c['render_request']['path']).read_text()); assert x['execution_allowed'] is False and r['execution_allowed'] is False; assert r['renderer_contract']['frames']==836; assert r['future_outputs']['full_saved_animation_sha256'] is None
    assert not any(p.is_file() and p.suffix.lower() in {'.h5','.hdf5','.bi4','.csv','.npy','.npz'} for p in HERE.rglob('*'))

def main():
    test_worker_and_gate(); test_package_contracts(); print('fresh076 semantic contract: PASS')

if __name__=='__main__': main()
