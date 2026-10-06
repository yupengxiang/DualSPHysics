#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BAD = {'.bi4', '.ibi4', '.csv', '.dat', '.h5', '.hdf5', '.vtk', '.npy', '.npz'}

def load(p): return json.loads(Path(p).read_text(encoding='utf-8'))
def sha(p):
    p = Path(p)
    if p.suffix.lower() in BAD: raise AssertionError(f'raw payload hash in source validator: {p}')
    h = hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda: f.read(1048576), b''): h.update(b)
    return h.hexdigest()
def canonical(v):
    return hashlib.sha256(json.dumps(v, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()

m = load(ROOT/'manifest.json')
assert m['case_count'] == 20 and m['source_only'] and m['jobs_started'] is False
idx = load(ROOT/'metadata/source-index.json')
assert len(idx['cases']) == 20 and idx['independent_case_count_increment'] == 0
seen = set()
for row in idx['cases']:
    case = row['case_id']; assert case not in seen; seen.add(case)
    assert row['physical_condition_sha256'] == row['converter_owner']['scope_sha256_expected']
    owner = load(row['converter_owner']['path'])
    assert canonical(owner['physical_binding']) == row['physical_condition_sha256']
    assert owner['actual_converter_scope']['expected_sha256'] == row['physical_condition_sha256']
    assert owner['source_agent_read_science_payloads'] is False
    assert row['native839']['receipt_sha256'] is None
    assert row['future_hashes_null'] is True
    typed = load(row['typed']['request']); tb = load(row['typed']['binding'])
    xmf = load(row['xmf']['request']); xb = load(row['xmf']['binding'])
    rr = load(row['render']['request']); rb = load(row['render']['binding'])
    for req in (typed, xmf, rr):
        assert req['disabled'] is True and req['execution_allowed'] is False and req['launch_allowed'] is False
        assert req['launch_owner'] == 'root' and req['worktree_root'].endswith('/ds-data-02-f3/DualSPHysics')
        assert req['physical_condition_sha256'] == row['physical_condition_sha256']
        for path in req['input_sha256']:
            assert Path(path).suffix.lower() not in BAD, path
            assert Path(path).is_file(), path
        for path, value in req.get('future_input_sha256', {}).items(): assert value is None
    assert tb['native_receipt_sha256'] is None and tb['typed_receipt_sha256'] is None
    assert tb['conversion_report_sha256'] is None and tb['trajectory_h5_sha256'] is None
    assert tb['physical_condition_sha256'] == row['physical_condition_sha256']
    assert tb['producer_scope_schema'] == 'ds-data-02.physical-binding.v1'
    assert xb['native_receipt_sha256'] is None and xb['typed_receipt_sha256'] is None
    assert xb['conversion_report_sha256'] is None and xb['trajectory_h5_sha256'] is None
    assert xb['physical_condition_sha256'] == row['physical_condition_sha256']
    assert rb['native_receipt_sha256'] is None and rb['typed_receipt_sha256'] is None
    assert rb['conversion_report_sha256'] is None and rb['trajectory_h5_sha256'] is None
    assert all(value is None for key, value in rb['future_outputs'].items() if key.endswith('_sha256') or key == 'visual_decision')
print('fresh104 F3 Root839 next20 typed/XMF/render source contract: PASS')
