#!/usr/bin/env python3
"""Fresh127 metadata-only validator; never opens scientific payloads."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
FORBIDDEN = {'.bi4', '.ibi4', '.obi4', '.h5', '.hdf5', '.csv', '.dat', '.vtk', '.vtu', '.npy', '.npz', '.raw'}
CASES = [
    'F3_STAGE1_DP006_P0800_AY0460',
    'F3_STAGE1_DP006_P0800_AY0500',
    'F3_STAGE1_DP006_P0800_AY0640',
]
DATA_ROOT = Path('/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3')


def digest(path: Path) -> str:
    assert path.suffix.lower() not in FORBIDDEN, f'forbidden hash: {path}'
    h = hashlib.sha256()
    with path.open('rb') as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def load(path: Path):
    assert path.suffix.lower() not in FORBIDDEN, f'forbidden read: {path}'
    return json.loads(path.read_text())


def check_map(mapping, label):
    assert isinstance(mapping, dict), label
    for text, expected in mapping.items():
        path = Path(text)
        assert path.is_file(), (label, 'missing', path)
        assert path.suffix.lower() not in FORBIDDEN, (label, 'forbidden', path)
        actual = digest(path)
        assert actual == expected, (label, path, expected, actual)


def check_request(path: Path):
    data = load(path)
    assert data.get('disabled') is True and data.get('execution_allowed') is False, path
    assert data.get('source_only') is True and data.get('case_credit', 0) == 0, path
    assert data.get('launch_allowed') is False and data.get('launch_owner') == 'root', path
    assert data.get('fresh_id') == 'fresh127', path
    if 'bound_metadata_sha256' in data:
        check_map(data['bound_metadata_sha256'], f'{path}:bound_metadata_sha256')
    if 'input_files' in data:
        files = data['input_files']; hashes = data.get('input_sha256', {})
        assert set(files) == set(hashes), (path, 'input closure keys')
        check_map(hashes, f'{path}:input_sha256')
    if 'future_input_sha256' in data:
        assert all(v is None for v in data['future_input_sha256'].values()), path
    for key, value in data.get('future_outputs', {}).items():
        if key.endswith('sha256'):
            assert value is None, (path, key, value)
    return data


def main():
    # Package itself must contain metadata/code only.
    for path in HERE.rglob('*'):
        if path.is_file():
            assert path.suffix.lower() not in FORBIDDEN, f'forbidden package file: {path}'
            assert '__pycache__' not in path.parts, path

    alias = load(HERE / 'metadata/alias/alias-correction.json')
    assert alias['census_token'] == 'F3_STAGE1_DP006_P1000_AY0500'
    assert alias['resolution']['resolved_case_id'] == 'F3_CELL3_LONG_DP006_AY0P50_ADAPTIVE_CFL05_COEF005'
    assert alias['resolution']['resolved_physical_case_id'] == 'F3_TWOAXIS_AY0P50_PITCH_NOMINAL'
    assert alias['resolution']['resolved_physical_condition_sha256'] == '49e319c0a874733707a028e916362e74e2301d6681e34bc6b717581dbd7edaeb'
    assert alias['directory_probe']['expected_token_directory_exists'] is False
    assert alias['directory_probe']['resolved_mother_directory_exists'] is True
    assert alias['resolution']['independent_case_count_increment'] == 0
    assert alias['resolution']['no_new_gencase_or_native_request'] is True

    accepted = load(HERE / 'metadata/accepted-scope/accepted-f3-scope.json')
    assert accepted['accepted_f3_count'] == 12
    accepted_ids = {row['case_id'] for row in accepted['accepted_f3_decisions']}
    assert 'F3_CELL3_LONG_DP006_AY0P50_ADAPTIVE_CFL05_COEF005' in accepted_ids
    assert 'F3_STAGE1_DP006_P1000_AY0250' in accepted_ids
    assert 'F3_STAGE1_DP006_P1000_AY0750' in accepted_ids
    census = load(HERE / 'metadata/full48-source-census-alias-corrected.json')
    assert census['missing_directory_is_alias'] is True
    assert census['global_case_credit_updated'] is False
    selection = load(HERE / 'metadata/selection-snapshot.json')
    assert selection['selected_case_ids'] == CASES
    assert selection['case_credit'] == 0 and selection['future_xmf_render_hashes'] is None

    for case in CASES:
        owner = load(HERE / f'metadata/owners/{case}.actual-native-physical-scope.owner.json')
        snap = load(HERE / f'metadata/case-snapshots/{case}.json')
        evidence = load(HERE / f'metadata/typed-terminal-evidence/{case}.json')
        assert owner['case_id'] == case and owner['family_id'] == 'F3'
        assert owner['source_agent_read_science_payloads'] is False
        assert owner['source_agent_hashed_science_payloads'] is False
        assert owner['fresh127_typed_terminal_provenance']['status'] == 'completed/0'
        typed_path = Path(owner['fresh127_typed_terminal_provenance']['typed_receipt_path'])
        report_path = Path(owner['fresh127_typed_terminal_provenance']['conversion_report_path'])
        native_path = Path(owner['fresh127_native_terminal_provenance']['receipt_path'])
        receipt = load(typed_path); report = load(report_path); native = load(native_path)
        assert receipt.get('status') == 'completed' and receipt.get('returncode') == 0
        assert native.get('status') == 'completed' and native.get('returncode') == 0
        assert report.get('conversion_status') == 'completed'
        assert report.get('frames') == 836 and report.get('particles') == 179208
        assert report.get('solver_dimension', {}).get('solver_dimension') == 3
        assert report.get('partvtk_validation', {}).get('all_passed') is True
        assert report.get('output_sha256'), 'producer H5 digest must be present; source does not recompute it'
        assert evidence['status'] == 'completed/0'
        assert evidence['conversion_report']['frames'] == 836 and evidence['conversion_report']['particles'] == 179208
        assert evidence['conversion_report']['solver_dimension'] == 3
        assert evidence['conversion_report']['partvtk_all_passed'] is True
        assert evidence['trajectory_h5_sha256'] is None
        assert snap['source_typed_status_at_snapshot']['terminal_completed0'] is True
        assert snap['typed_producer_evidence']['frames'] == 836
        assert snap['typed_producer_evidence']['particles'] == 179208
        assert snap['typed_producer_evidence']['solver_dimension']['solver_dimension'] == 3
        assert snap['typed_producer_evidence']['partvtk_all_passed'] is True
        assert snap['typed_producer_evidence']['trajectory_h5_sha256_reported_by_typed_producer'] == report['output_sha256']
        assert snap['source_agent_read_science_payloads'] is False
        assert snap['source_agent_hashed_science_payloads'] is False

        files = [
            HERE / f'requests/xmf/{case}-xmf-binding.json',
            HERE / f'requests/xmf/{case}-xmf-request.json',
            HERE / f'requests/render/{case}-render-binding.json',
            HERE / f'requests/render/{case}-wrapper-request.json',
            HERE / f'requests/render/{case}-root023-render-request.json',
        ]
        parsed = [check_request(p) for p in files]
        xb, xr, rb, rw, rr = parsed
        assert xb['bound_metadata_sha256'][str(HERE / f'metadata/case-snapshots/{case}.json')] == digest(HERE / f'metadata/case-snapshots/{case}.json')
        assert xb['bound_metadata_sha256'][str(HERE / f'metadata/owners/{case}.actual-native-physical-scope.owner.json')] == digest(HERE / f'metadata/owners/{case}.actual-native-physical-scope.owner.json')
        assert xb['typed_receipt_sha256'] == digest(typed_path)
        assert xb['conversion_report_sha256'] == digest(report_path)
        assert xb['native_receipt_sha256'] == digest(native_path)
        assert xr['depends_on_typed']['terminal_completed0'] is True
        assert xr['depends_on_typed']['typed_receipt_sha256'] == digest(typed_path)
        assert rb['normal_xmf_binding_sha256'] == digest(HERE / f'requests/xmf/{case}-xmf-binding.json')
        assert rr['binding_sha256'] == digest(HERE / f'requests/render/{case}-render-binding.json')
        assert rr['wrapper_request_sha256'] == digest(HERE / f'requests/render/{case}-wrapper-request.json')
        assert all(o['physical_case_id'] == owner['physical_case_id'] for o in [xb, xr, rb, rw, rr])
        assert all(o['physical_condition_sha256'] == owner['physical_condition_sha256'] for o in [xb, xr, rb, rw, rr])
        assert xb.get('expected_frames') == 836 and rb.get('expected_frames') == 836 and rw.get('expected_frames') == 836
        assert xb.get('expected_particles') == 179208 and rb.get('expected_particles') == 179208 and rw.get('expected_particles') == 179208
        # Render future hashes must remain null; no visual status is granted here.
        assert rb['xdmf_sha256'] is None and rb['manifest_sha256'] is None
        assert rw['future_input_hashes_null'] is True

    # No fresh127 request may be created for the alias token.
    assert not list((HERE / 'requests').rglob('*P1000_AY0500*'))
    print(json.dumps({
        'schema': 'ds02.stage1.f3.fresh127.validator-report.v1',
        'status': 'pass', 'selected_case_count': len(CASES),
        'selected_terminal_typed_completed0': CASES,
        'accepted_f3_scope_count': accepted['accepted_f3_count'],
        'p1000_ay0500_resolution': 'existing accepted mother alias; no new physical case',
        'source_only': True, 'jobs_started': False, 'shared_state_modified': False,
        'science_payload_opened_or_hashed': False,
    }, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
