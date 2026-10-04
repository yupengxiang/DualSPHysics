#!/usr/bin/env python3
from __future__ import annotations
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FINAL = Path('/home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/root_followup_073_stage1_omega_full241_xmf_native023_render_v1')
CASES = ['F6_STAGE1_ANGULAR_RELEASE_OMEGA_S025_DP025', 'F6_STAGE1_ANGULAR_RELEASE_OMEGA_S200_DP025']

def j(path: Path):
    return json.loads(path.read_text())

def digest(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def test_fresh073_rebind_and_disabled():
    aggregate = j(ROOT / 'strict/aggregate-binding.json')
    assert aggregate['scope_id'].startswith('root_followup_073_')
    assert aggregate['launch'] is False and aggregate['launch_allowed'] is False
    assert len(aggregate['cases']) == 2
    for case in aggregate['cases']:
        cid = case['case_id']
        assert cid in CASES
        owner = Path(case['canonical_owner'])
        assert owner == FINAL / 'owners' / f'{cid}.canonical-owner.json'
        assert owner.is_file() and digest(owner) == case['canonical_owner_sha256']
        xmf_binding = j(ROOT / Path(case['xmf_binding']).relative_to(FINAL))
        render_binding = j(ROOT / Path(case['render_binding']).relative_to(FINAL))
        xmf_request = j(ROOT / Path(case['xmf_request']).relative_to(FINAL))
        render_request = j(ROOT / Path(case['render_request']).relative_to(FINAL))
        for d in [xmf_binding, render_binding, xmf_request, render_request]:
            assert d['launch'] is False and d['launch_allowed'] is False
            assert d['canonical_owner'] == str(owner)
        assert xmf_binding['expected_frames'] == 241
        assert render_binding['expected_frames'] == 241
        assert render_request['output_contract']['all_frames_rendered'] is True
        assert render_request['output_contract']['frame_count'] == 241
        assert render_request['output_contract']['camera_fixed_bounds_forbidden'] is True
        assert render_request['camera_bounds_policy'].startswith('omit fixed camera_bounds/domain_bounds')
        assert 'diagnostic-frames' not in render_request['command']
        assert all(v is None for v in case['xmf_output_hashes'].values())
        assert all(v is None for v in case['render_output_hashes'].values())
        assert xmf_request['output_contract']['xdmf_sha256'] is None
        assert xmf_request['output_contract']['manifest_sha256'] is None
        assert render_request['output_contract']['report_sha256'] is None
        assert render_request['output_contract']['execution_receipt_sha256'] is None
        for request in [xmf_request, render_request]:
            text = json.dumps(request)
            assert '/tmp/f6fresh071' not in text
            assert 'root_followup_071_stage1_omega_full241_xmf_native023_render_v1' not in text
            assert str(FINAL / 'workers') in text
    provenance = j(ROOT / 'provenance/xml-bounds-provenance.json')
    assert all(item['role'] == 'provenance_only' and item['used_for_camera'] is False for item in provenance['cases'])
    assert provenance['camera_policy']['fixed_bounds_in_manifest'] is False

if __name__ == '__main__':
    test_fresh073_rebind_and_disabled()
    print('fresh073 contract: PASS')
