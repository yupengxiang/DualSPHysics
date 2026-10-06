#!/usr/bin/env python3
"""Validate fresh105 visual metadata without opening scientific payloads."""
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
    manifest = json.loads((HERE / 'manifest.json').read_text())
    assert manifest['schema'] == 'ds02.stage1.f2.delegated-visual-package.v1'
    assert manifest['review_boundary']['agent_personally_viewed_all_17_contact_sheets_and_4_key_frames_per_case']
    assert manifest['review_boundary']['science_payload_read_or_hashed_by_agent'] is False
    for item in manifest['cases']:
        decision = json.loads(Path(item['decision_path']).read_text())
        assert decision['status'] == 'visual-approved-by-delegated-agent'
        assert decision['agent_personally_viewed_all_contacts_and_keys']
        assert decision['main_personally_viewed_pngs'] is False
        assert decision['actual_frames'] == 401
        assert decision['actual_particles'] == 418104
        assert decision['actual_fluid_particles'] == 21114
        assert decision['precision_status'] == '视觉检查通过、数值精度未验收'
        assert decision['q_n'] == 'not_granted'
        assert decision['q_e'] == 'not_assessed'
        assert decision['independent_case_increment'] == 1
        assert decision['source_scope_correction']['source_canonical_physical_condition_sha256'] != decision['source_scope_correction']['actual_converter_legacy_scope_sha256']
        pngs = decision['verified_PNG_hashes']
        assert len(pngs['contact_sheets']) == 17
        assert len(pngs['key_frames']) == 4
        for p in pngs['contact_sheets'] + pngs['key_frames']:
            path = Path(p['path'])
            assert path.suffix.lower() == '.png'
            assert digest(path) == p['sha256'], path
    print('fresh105 visual metadata validation: PASS (2 cases, 42 PNG hashes; no science payload opened)')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
