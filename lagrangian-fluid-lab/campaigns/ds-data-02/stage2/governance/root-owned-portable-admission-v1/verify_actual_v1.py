"""Independent metadata/stat check of the portable report and same-parent fees."""
from pathlib import Path
import hashlib
import importlib
import json
import subprocess
import sys

HERE = Path(__file__).resolve().parent
LAB = HERE.parents[4]
S = LAB / 'campaigns/ds-data-02/stage2'
from external_storage_v1 import small, snapshot


def sha(path):
    p = Path(path)
    assert p.suffix.lower() not in {'.h5','.hdf5','.bi4','.obi4','.ibi4','.vtk','.vtu','.jsonl'} and p.stat().st_size <= 10485760
    return hashlib.sha256(p.read_bytes()).hexdigest()


def current_stat(path):
    z = Path(path).stat()
    return {'bytes': z.st_size, 'mode_bits': z.st_mode & 0o7777, 'mtime_ns': z.st_mtime_ns,
            'ctime_ns': z.st_ctime_ns, 'st_dev': z.st_dev, 'st_ino': z.st_ino}


def main():
    qp = Path(sys.argv[1]).absolute()
    source = S / 'governance/root-owned-lifecycle-continuation-v1/root_common_verification.py'
    context = {'__file__': str(source), '__name__': 'root_portable_actual_v1'}
    exec(source.read_text(), context); context['sha'] = sha
    q, base, receipt, proof = context['common'](qp)
    root = Path(q['storage_scope']['external_filesystem'])
    report_path = root / 'reports/root242-v11-executor-report.json'
    report, report_sha = small(report_path)
    assert report['status'] == 'COMPLETE_RELOCATED_V11_DYNAMIC_OPEN_GUARD_V8_V12_TYPED_SCORER'
    assert report['schema'] == 'ds02.stage2.f2-root242-portable-typed-executor-report.v11'
    assert report['case_id'] == q['case_id'] and report['attempt_id'] == q['attempt_id']
    assert report['request']['path'] == str(qp) and report['request']['file_sha256'] == sha(qp)
    canonical = dict(report); canonical.pop('sha256')
    assert hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest() == report['sha256']
    contract, _ = small(q['root213_metadata_contract']['path'])
    assert report['contract']['canonical_sha256'] == contract['sha256'] == q['root213_metadata_contract']['sha256']
    roles = {r['logical_role']: r for r in contract['root242_source_binding']['roles']}
    audits = report['copy_audits']
    assert set(audits) == set(roles) and len(roles) == report['role_count'] == 49
    assert sum(r['bytes'] for r in audits.values()) == report['copy_bytes']
    for name, audit in audits.items():
        role = roles[name]
        assert audit['source_path'] == role['source_path_provenance']
        assert audit['target_relative_path'] == role['target_relative_path']
        assert audit['source_sha256'] == audit['target_sha256'] == role['source_sha256']
        assert audit['source_pre_stat'] == audit['source_post_stat'] == current_stat(audit['source_path'])
        assert all(audit['source_pre_stat'][k] == v for k, v in role['source_stat_provenance'].items())
        assert audit['bytes'] == role['source_stat_provenance']['bytes']
        assert audit['content_phase'] == 'AFTER_PARENT_RESERVATION' and audit['inode_distinct']
        target = root / audit['target_relative_path']
        assert target.is_relative_to(root) and not target.is_symlink() and target.is_file()
        # The relocation worker may rebind copied metadata; the sealed copy
        # audit records its original SHA. Large arrays/JSON remain stat-only.
        if role['deferred_content']:
            assert target.stat().st_size == audit['bytes']
    for key in ['manifest','inner_contract','overlay','runtime_open_policy','child_report']:
        edge = report[key]; path = root / edge['path']
        assert path.is_relative_to(root) and sha(path) == edge['sha256']
    child, _ = small(root / report['child_report']['path'])
    assert child['status'] == 'PASS_RELOCATED_V8_V12_TYPED_SCORER'
    audit = report['child_runtime_open_audit']
    assert audit == child['runtime_open_audit'] and audit['hook_installed'] and audit['blocked_events'] == 0
    assert audit['original_path_fallback'] == 'REJECT'
    execution = report['execution']
    assert execution['streamed_copy_hash_bytes'] == report['copy_bytes']
    h5bytes = sum(a['bytes'] for a in audits.values() if Path(a['target_relative_path']).suffix.lower() in {'.h5','.hdf5','.bi4'})
    assert execution['hdf5_or_bi4_bytes_streamed_for_copy_hash'] == h5bytes > 0
    assert not execution['scientific_H5_array_decode'] and not execution['scientific_BI4_array_decode']
    evidence_path = S / 'accounting/root242-external-storage-evidence-v1.json'
    evidence, evidence_sha = small(evidence_path)
    assert evidence['request_sha256'] == sha(qp) and evidence['receipt_sha256'] == proof['receipt_sha256']
    assert evidence['external_stat_snapshot'] == snapshot(root) and evidence['external_storage_within_reservation']
    ledger = context['load'](context['D'] / 'runtime/resource-ledger.json')
    feeid = proof['parent_charge']['id'] + '/same-parent-external-storage-v1'
    fees = [f for f in ledger['charges'] if f['id'] == feeid]
    assert len(fees) == 1 and fees[0]['evidence_sha256'] == evidence_sha
    assert fees[0]['new_storage_bytes'] == evidence['external_stat_snapshot']['bytes']
    proof.update(status='VERIFIED_ACTUAL_ROOT242_PORTABLE_V11_METADATA_RUNTIME_GUARD_NO_COLD_REPLAY_Q',
                 report=str(report_path), report_sha256=report_sha, selected_role_count=49,
                 source_copy_hash_bytes=report['copy_bytes'], external_actual_bytes=fees[0]['new_storage_bytes'],
                 external_storage_fee=fees[0], external_storage_evidence=str(evidence_path),
                 external_storage_evidence_sha256=evidence_sha, repeat_external_storage_fee_idempotent=True,
                 root_payload_content_read=False, scientific_H5_BI4_array_decode=False,
                 actual_runtime_open_guard_verified=True, portable_cold_replay_credit='NOT_CLAIMED')
    footer = (S / 'governance/root-owned-lifecycle-continuation-v1/root_cpu_verification_footer.py').read_text()
    footer = footer.replace('1073741824', str(q['max_memory_bytes'])).replace('F7_S1_SOURCE_SUPPORT_ACTUAL_SCOPE_ROOT_VERIFICATION_137.json', 'PORTABLE_TYPED_V11_ACTUAL_ROOT_VERIFICATION_242.json')
    context.update(q=q,b=base,r=receipt,p=proof,qp=qp,num='242',name='portable-typed-v11',subprocess=subprocess,importlib=importlib)
    exec(footer, context)


if __name__ == '__main__':
    main()
