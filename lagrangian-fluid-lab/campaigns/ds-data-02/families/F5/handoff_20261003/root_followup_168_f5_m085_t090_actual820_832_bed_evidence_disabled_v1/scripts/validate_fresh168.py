#!/usr/bin/env python3
"""Metadata-only validator for fresh168; never opens H5/BI4/CSV/DAT/VTK."""
from __future__ import annotations
import hashlib, json
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
ALLOWED = {'.json', '.xml', '.xmf', '.py', '.md'}
FORBIDDEN = {'.h5', '.bi4', '.csv', '.dat', '.vtk'}

def sha256_file(path: Path) -> str:
    if path.suffix.lower() not in ALLOWED:
        raise AssertionError(f'forbidden source hash: {path}')
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            if not block:
                break
            h.update(block)
    return h.hexdigest()

def load(path: str | Path):
    return json.loads(Path(path).read_text())

def get(obj, *keys):
    for key in keys:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj

def main() -> int:
    binding = load(PKG / 'bindings/M085_T090-actual820-832-bed-evidence-binding.json')
    request = load(PKG / 'requests/M085_T090-actual820-832-bed-evidence-disabled-request.json')
    evidence = load(PKG / 'metadata/m085-t090-actual-bed-evidence.json')
    manifest = load(PKG / 'manifest.json')
    assert binding['disabled'] and not binding['execution_allowed'] and not binding['conversion_allowed'] and not binding['solver_allowed']
    assert request['disabled'] and not request['launch'] and not request['execution_allowed'] and not request['arrays_allowed']
    assert request['cpu_task_kind'] == 'audit' and request['kind'] == 'cpu'
    assert request['actual_bed_evidence']['rerun_required'] is False
    assert request['future_output_hashes']['bed_audit_report_sha256'] is None
    for p in request['input_files']:
        path = Path(p)
        assert path.is_file(), p
        assert path.suffix.lower() in ALLOWED, p
    for path, digest in request['input_sha256'].items():
        assert sha256_file(Path(path)) == digest, path
    worker = Path(binding['original138_worker']['path'])
    assert sha256_file(worker) == '89be048da1df6bae49627308edb35a8a1936bc0888259cb5ab3d195307b550e2'
    bed_receipt = load(evidence['actual_producers']['bed_audit']['receipt'])
    bed = load(evidence['actual_producers']['bed_audit']['report'])
    xmf_receipt = load(evidence['actual_producers']['xmf']['receipt'])
    xmf = load(evidence['actual_producers']['xmf']['manifest'])
    typed = load(evidence['actual_producers']['typed']['report'])
    native = load(evidence['actual_producers']['native']['receipt'])
    qa = load(evidence['actual_producers']['initial_qa']['report'])
    for receipt in (bed_receipt, xmf_receipt, native):
        assert receipt['status'] == 'completed' and receipt['returncode'] == 0
    assert bed['schema'] == 'ds02.f5.c082s1.full-event-bed-footprint-audit.fresh138.v1'
    assert bed['status'] == 'completed_worker_output_pending_root_review'
    assert bed['scan']['frames_scanned'] == 801 and bed['scan']['particle_axis_count'] == 194427 and bed['scan']['initial_fluid_uid_count'] == 31658
    assert bed['source_arrays_modified'] is False and bed['source_arrays_dropped_or_masked'] is False
    assert bed['repair_success'] == 'unknown_until_full_event_bed_audit_review'
    assert bed['production_approval'] == 'none' and bed['q_n_status'] == 'not_granted'
    assert bed['native_identity_contract']['native_bed_marker_mk'] == 50 and bed['native_identity_contract']['source_bed_marker_mkbound'] == 40
    assert typed['conversion_status'] == 'completed' and typed['frames'] == 801 and typed['particles'] == 194427
    assert xmf['frames'] == 801 and xmf['particles'] == 194427
    assert qa['all_basic_placement_checks_pass'] is True and qa['mk50_coverage']['native_bed_mk'] == 50
    assert evidence['physical_scope']['canonical_physical_condition_sha256'] != evidence['physical_scope']['source_h5_legacy_scope_sha256']
    assert evidence['source_file_access_policy']['science_suffixes_not_read_or_hashed'] == ['.h5', '.bi4', '.csv', '.dat', '.vtk']
    expected = {item['path']: item['sha256'] for item in manifest['files']}
    for path, digest in expected.items():
        assert sha256_file(Path(path)) == digest, path
    report = {'schema': 'ds02.f5.c082s1.fresh168-validator-report.v1', 'status': 'pass-disabled-metadata-only', 'actual_bed_status': 'completed/0', 'actual_bed_rerun_required': False, 'frames': 801, 'particle_axis': 194427, 'initial_fluid_uid_denominator': 31658, 'source_arrays_read_or_hashed': False, 'source_science_payloads_read_or_hashed': False, 'visual_acceptance': 'pending_root_review', 'q_n_granted': False, 'case_credit': 0}
    (PKG / 'metadata/fresh168-validator-report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps(report, sort_keys=True))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
