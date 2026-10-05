#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES = ['F7_OBSTACLE_QUINTIC_B08_A035', 'F7_OBSTACLE_QUINTIC_B08_A040', 'F7_OBSTACLE_QUINTIC_B08_A050', 'F7_OBSTACLE_QUINTIC_B08_A055', 'F7_OBSTACLE_QUINTIC_B08_A060']

def j(path):
    return json.loads(path.read_text())

def test_fresh067():
    audit = j(ROOT / 'metadata/root117-runtime-field-audit.json')
    assert audit['metadata_only_qualified_input_preparation']['required'] is False
    assert audit['top_level_failure_preserved'] is True
    assert len(audit['cases']) == 5
    for row in audit['cases']:
        assert row['actual_runtime_fields'] == {'total_particles': 70179, 'fluid_particles': 40700, 'solver_dimension_from_gencase': 3}
    qa = j(ROOT / 'metadata/root126-initial-qa-binding.json')
    assert len(qa['cases']) == 5
    assert all(row['report_all_cases_passed'] is True and row['report_case_passed'] is True for row in qa['cases'])
    for case in CASES:
        req = j(ROOT / 'requests' / f'{case}.full601-native-qualification-request.json')
        assert req['launch'] is False and req['launch_allowed'] is False and req['execution_allowed'] is False
        assert req['scope_id'].startswith('root_followup_067_')
        assert req['initial_qa_required']['status'] == 'completed_actual_root126'
        assert req['initial_qa_required']['receipt_sha256'] is not None
        assert req['initial_qa_required']['report_sha256'] is not None
        assert req['future_outputs']['solver_execution_receipt_sha256'] is None
        assert req['future_outputs']['trajectory_h5_sha256'] is None
        assert '-tmax:12' in req['command'] and '-tout:0.02' in req['command']
        assert req['cwd'].endswith(case)
        assert (Path(req['cwd']) / 'motion_obstacle_quintic.dat').is_file()
        assert req['root117_runtime_contract']['actual_solver_dimension'] == 3
        for needle in ('.xml', '.bi4', '_Def.xml', 'motion_obstacle_quintic.dat'):
            assert any(needle in value for value in req['input_files'])
    assert j(ROOT / 'manifest.json')['handoff_id'].startswith('root_followup_067_')

if __name__ == '__main__':
    test_fresh067()
    print('fresh067 contract: PASS')
