"""Stat-only, idempotent external storage fee under the existing parent ledger."""
from pathlib import Path
import hashlib
import json
import os

PAYLOAD = {'.h5', '.hdf5', '.bi4', '.obi4', '.ibi4', '.vtk', '.jsonl'}
TERMINAL = {'completed', 'failed', 'cancelled', 'canceled', 'timeout'}


def small(path):
    p = Path(path)
    assert p.suffix.lower() not in PAYLOAD and p.stat().st_size <= 10485760
    raw = p.read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def snapshot(root):
    root = Path(root)
    assert root.is_absolute() and not root.is_symlink()
    rows = []
    if root.exists():
        assert root.is_dir()
        for base, dirs, files in os.walk(root, followlinks=False):
            for name in dirs:
                assert not (Path(base) / name).is_symlink()
            for name in files:
                p = Path(base) / name
                assert not p.is_symlink() and p.is_file()
                z = p.stat()
                rows.append({'relative_path': str(p.relative_to(root)), 'bytes': z.st_size,
                             'mtime_ns': z.st_mtime_ns, 'ctime_ns': z.st_ctime_ns,
                             'st_dev': z.st_dev, 'st_ino': z.st_ino})
    rows.sort(key=lambda x: x['relative_path'])
    raw = json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()
    return {'root': str(root), 'files': rows, 'file_count': len(rows),
            'bytes': sum(x['bytes'] for x in rows),
            'stat_manifest_sha256': hashlib.sha256(raw).hexdigest(), 'payload_content_read': False}


def reconcile(request_path, data_root, ledger_locked, output):
    q, qsha = small(request_path)
    ident = '/'.join(q[k] for k in ('family_id', 'case_id', 'attempt_id'))
    receipt_path = Path(data_root) / 'families' / ident / 'execution-receipt.json'
    receipt, rsha = small(receipt_path)
    assert receipt['request'] == q and receipt['request_sha256'] == qsha
    assert receipt['status'] in TERMINAL
    accounting = q['root_external_storage_accounting']
    assert accounting['same_parent_atomic_reservation_bytes'] == q['estimated_storage_bytes']
    assert accounting['external_reserved_bytes'] + accounting['home_reserved_bytes'] <= q['estimated_storage_bytes']
    root = Path(q['storage_scope']['external_filesystem'])
    assert str(root).startswith('/var/tmp/STAGE2_F2_ROOT242_')
    tree = snapshot(root)
    evidence = {'schema': 'ds02.stage2.same-parent-external-storage-evidence.v1',
                'parent_id': ident, 'request': str(request_path), 'request_sha256': qsha,
                'receipt': str(receipt_path), 'receipt_sha256': rsha,
                'terminal_status': receipt['status'], 'external_stat_snapshot': tree,
                'reservation_bytes': q['estimated_storage_bytes'],
                'external_storage_within_reservation': tree['bytes'] <= accounting['external_reserved_bytes'],
                'scientific_Q': 'UNKNOWN'}
    out = Path(output)
    if out.exists():
        prior, _ = small(out)
        assert prior == evidence, 'external evidence changed after terminal reconciliation'
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open('x') as f:
            json.dump(evidence, f, indent=2, sort_keys=True); f.write('\n')
    _, esha = small(out)
    fee_id = ident + '/same-parent-external-storage-v1'
    fee = {'id': fee_id, 'parent_id': ident, 'kind': 'supplemental_external_storage',
           'gpu_seconds': 0.0, 'cpu_core_seconds': 0.0,
           'new_storage_bytes': tree['bytes'], 'status': receipt['status'],
           'evidence_path': str(out), 'evidence_sha256': esha,
           'request_sha256': qsha, 'receipt_sha256': rsha}
    with ledger_locked(Path(data_root)) as ledger:
        parents = [c for c in ledger['charges'] if c['id'] == ident]
        assert len(parents) == 1 and parents[0]['status'] == receipt['status']
        assert parents[0]['new_storage_bytes'] == receipt['bytes']
        assert not any(c['id'] == ident for c in ledger['reservations'])
        prior = [c for c in ledger['charges'] if c['id'] == fee_id]
        if prior:
            assert len(prior) == 1 and prior[0] == fee
            status = 'ALREADY_APPLIED_SAME_PARENT_EXTERNAL_STORAGE'
        else:
            ledger['charges'].append(fee)
            status = 'APPENDED_SAME_PARENT_EXTERNAL_STORAGE'
    return {'status': status, 'charge': fee, 'evidence': evidence}
