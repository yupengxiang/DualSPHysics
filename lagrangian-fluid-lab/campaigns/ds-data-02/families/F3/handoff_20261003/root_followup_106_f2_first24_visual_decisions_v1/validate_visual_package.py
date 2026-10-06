#!/usr/bin/env python3
"""Validate fresh106 visual metadata without opening scientific payloads."""
from __future__ import annotations
import hashlib, json
from pathlib import Path
HERE = Path(__file__).resolve().parent

def digest(p: Path) -> str:
    h = hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def main() -> int:
    m = json.loads((HERE/'manifest.json').read_text())
    assert m['schema'] == 'ds02.stage1.f2.delegated-visual-package.v1'
    assert m['review_boundary']['agent_personally_viewed_all_17_contact_sheets_and_4_key_frames_per_case']
    assert m['review_boundary']['science_payload_read_or_hashed_by_agent'] is False
    assert len(m['cases']) == 1
    item = m['cases'][0]
    d = json.loads(Path(item['decision_path']).read_text())
    assert d['status'] == 'visual-approved-by-delegated-agent'
    assert d['agent_personally_viewed_all_contacts_and_keys']
    assert d['main_personally_viewed_pngs'] is False
    assert d['actual_frames'] == 401
    assert d['actual_particles'] == 418104
    assert d['actual_fluid_particles'] == 21114
    assert d['precision_status'] == '视觉检查通过、数值精度未验收'
    assert d['q_n'] == 'not_granted' and d['q_e'] == 'not_assessed'
    assert d['independent_case_increment'] == 1
    sc = d['source_scope_correction']
    assert sc['source_canonical_physical_condition_sha256'] == d['physical_condition_sha256']
    assert sc['source_canonical_physical_condition_sha256'] != sc['actual_converter_legacy_scope_sha256']
    assert len(d['verified_PNG_hashes']['contact_sheets']) == 17
    assert len(d['verified_PNG_hashes']['key_frames']) == 4
    for p in d['verified_PNG_hashes']['contact_sheets'] + d['verified_PNG_hashes']['key_frames']:
        path = Path(p['path'])
        assert path.suffix.lower() == '.png'
        assert digest(path) == p['sha256'], path
    print('fresh106 visual metadata validation: PASS (1 case, 21 PNG hashes; no science payload opened)')
    return 0
if __name__ == '__main__':
    raise SystemExit(main())
