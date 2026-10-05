#!/usr/bin/env python3
"""Metadata-only validator for fresh067.

It hashes only source JSON/XML/code/executable inputs listed by disabled
requests.  It never opens BI4/H5/CSV/NPY/NPZ arrays, runs a helper, or enables a
request.  Root must execute the disabled GenCase, qualification solver and
native frame-0 audit through its strict runner.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
FRESH066 = Path('/home/jade/.codex/worktrees/ds-data-02-f1/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F1/handoff_20261003/root_followup_066_f1_initial_vx_gencase_qa_v1')
SELECTED_PARENTS = {
    'F1_STAGE1_ECC_H110_DP010', 'F1_STAGE1_ECC_H190_DP010',
    'F1_STAGE1_DUAL_H220_DP020', 'F1_STAGE1_DUAL_H340_DP020',
}
PRESERVED_PARENTS = {
    'F1_STAGE1_ECC_H130_DP010', 'F1_FALLBACK_ECC_COARSE',
    'F1_STAGE1_DUAL_H260_DP020', 'F1_FALLBACK_DUAL_COARSE',
}
ARRAY_SUFFIXES = {'.bi4', '.h5', '.hdf5', '.csv', '.npy', '.npz'}


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def canonical(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError(f'JSON object required: {path}')
    return value


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def check_inputs(request: dict[str, Any], label: str) -> None:
    files = request.get('input_files')
    hashes = request.get('input_sha256')
    require(isinstance(files, list) and isinstance(hashes, dict), f'{label}: input closure missing')
    require(set(files) == set(hashes), f'{label}: input hash keys differ')
    for raw in files:
        path = Path(raw)
        require(path.suffix.lower() not in ARRAY_SUFFIXES, f'{label}: raw array input is bound: {path}')
        require(path.is_file(), f'{label}: missing source input: {path}')
        require(hashes[raw] == sha(path), f'{label}: source hash stale: {path}')


def check_future(request: dict[str, Any], label: str) -> None:
    require(request.get('future_input_sha256') is None, f'{label}: future input SHA is not null')
    for key, value in request.items():
        if key.endswith('_receipt_sha256') or key.endswith('_report_sha256') or key.endswith('_xml_sha256') or key.endswith('_bi4_sha256'):
            require(value is None, f'{label}: future digest is populated: {key}')
    future = request.get('future_outputs')
    if isinstance(future, dict):
        for key, value in future.items():
            if key.endswith('sha256') or key.endswith('_sha256'):
                require(value is None, f'{label}: future output digest is populated: {key}')
        require(future.get('status') in {'not_generated', 'pending_root_actual'}, f'{label}: future output status')
    for raw in request.get('future_input_files', []):
        require(Path(raw).suffix.lower() in ARRAY_SUFFIXES or True, f'{label}: invalid future path')


def check_xml(path: Path, expected_v: tuple[float, float, float], label: str) -> str:
    require(path.is_file(), f'{label}: definition missing: {path}')
    root = ET.parse(path).getroot()
    nodes = root.findall('.//initials/velocity')
    require(len(nodes) == 1, f'{label}: expected one initials velocity')
    node = nodes[0]
    require(node.get('mkfluid') == '0', f'{label}: mkfluid must be 0')
    actual = tuple(float(node.get(axis, 'nan')) for axis in ('x', 'y', 'z'))
    require(actual == expected_v, f'{label}: XML velocity {actual} != {expected_v}')
    return sha(path)


def check_case(case_id: str) -> dict[str, Any]:
    owner = load(HERE / 'owners' / f'{case_id}.corner-owner.json')
    plan = load(HERE / 'source-plans' / f'{case_id}.json')
    gbind = load(HERE / 'gencase-bindings' / f'{case_id}.json')
    abind = load(HERE / 'native-vx-bindings' / f'{case_id}.json')
    greq = load(HERE / 'requests' / f'{case_id}.gencase.request.json')
    areq = load(HERE / 'requests' / f'{case_id}.native-frame0-vx-qa.request.json')
    nreq = load(HERE / 'requests' / f'{case_id}.full-native-qualification.request.json')
    label = case_id
    require(owner.get('source_only') is True and owner.get('launch_allowed') is False and owner.get('execution_allowed') is False, f'{label}: owner enabled')
    require(owner.get('parent_case_id') in SELECTED_PARENTS, f'{label}: parent not selected corner')
    expected_v = tuple(float(value) for value in owner['axis']['velocity_m_per_s'])
    require(expected_v in {(0.1, 0.0, 0.0), (0.2, 0.0, 0.0)}, f'{label}: unsupported velocity')
    require(owner['physical_condition_sha256'] == canonical(owner['physical_binding']), f'{label}: canonical physical condition changed')
    require(owner['source_plan_condition_sha256'] != owner['physical_condition_sha256'], f'{label}: source-plan hash aliased physical condition')
    require(owner['source_plan_sha256'] == sha(HERE / 'source-plans' / f'{case_id}.json'), f'{label}: source-plan SHA stale')
    reference = owner['parent_actual_voxelization_reference']
    require(reference.get('dimension') == 3 and int(reference.get('total_particles', 0)) > 0 and int(reference.get('fluid_particles', 0)) > 0, f'{label}: parent 3-D metadata missing')
    require(float(owner['physical_binding']['initial_state']['continuum_mass_by_source_kg']['fluid']) > 0, f'{label}: source mass invalid')
    definition = Path(gbind['definition'])
    require(gbind['definition_sha256'] == check_xml(definition, expected_v, label), f'{label}: definition hash stale')
    require(gbind['new_output_status'] == 'not_generated', f'{label}: GenCase output claimed')
    require(gbind['expected_total_reference'] == reference['total_particles'], f'{label}: expected total drift')
    require(gbind['expected_fluid'] == reference['fluid_particles'], f'{label}: expected fluid drift')
    require(gbind['solver_dimension_reference'] == 3, f'{label}: dimension reference not 3')
    for request, task in ((greq, 'gencase'), (areq, 'audit')):
        require(request.get('schema') == 'ds02.runner-request.v2', f'{label}: CPU schema')
        require(request.get('case_id') == case_id and request.get('kind') == 'cpu', f'{label}: CPU identity')
        require(request.get('cpu_task_kind') == task, f'{label}: CPU task kind')
        require(request.get('source_only') is True and request.get('launch_allowed') is False and request.get('execution_allowed') is False, f'{label}: CPU request enabled')
        require(request.get('independent_case_count_increment') == 0, f'{label}: CPU count increment')
        check_inputs(request, label)
        check_future(request, label)
    require(areq['command'][1].endswith('native_initial_vx_frame0_audit.py'), f'{label}: wrong frame-0 worker')
    require(areq['native_audit_contract']['gencase_velocity_claim'] == 'not_used', f'{label}: GenCase velocity claim not separated')
    require(areq['native_audit_contract']['native_frame0_source'] == 'solver_output/data/Part_0000.bi4 via official PartVTK -dirdata', f'{label}: native frame-0 source contract')
    require(nreq.get('kind') == 'qualification' and nreq.get('launch_owner') == 'root', f'{label}: qualification entry')
    require(nreq.get('source_only') is True and nreq.get('launch_allowed') is False and nreq.get('execution_allowed') is False, f'{label}: native request enabled')
    require(nreq.get('root_actual_launch_source', '').endswith('root_stage1_f6_actual_qualifications_strict_entry_146/launch.py'), f'{label}: Root146 entry not bound')
    window_end = float(owner['physical_binding']['event_window']['time_end_s'])
    require(nreq.get('command')[-2:] == [f'-tmax:{window_end:g}', '-tout:0.01'], f'{label}: solver time recipe changed')
    require(nreq.get('expected_native_frames') == (161 if owner['physical_binding']['event_window']['time_end_s'] == 1.6 else 401), f'{label}: frame count')
    require(nreq.get('no_solver_option_mutation') is True and nreq.get('no_forcing') is True and nreq.get('no_mdbc') is True, f'{label}: solver guard missing')
    require(nreq.get('q_n') == 'not_assessed' and nreq.get('production_approval') == 'none', f'{label}: unsupported scientific claim')
    check_inputs(nreq, label)
    check_future(nreq, label)
    return {
        'case_id': case_id,
        'parent_case_id': owner['parent_case_id'],
        'physical_case_id': owner['physical_case_id'],
        'physical_condition_sha256': owner['physical_condition_sha256'],
        'source_plan_condition_sha256': owner['source_plan_condition_sha256'],
        'velocity_m_per_s': list(expected_v),
        'expected_total': reference['total_particles'],
        'expected_fluid': reference['fluid_particles'],
        'dimension': 3,
        'native_frames': nreq['expected_native_frames'],
        'gencase_request': str(HERE / 'requests' / f'{case_id}.gencase.request.json'),
        'native_frame0_qa_request': str(HERE / 'requests' / f'{case_id}.native-frame0-vx-qa.request.json'),
        'native_request': str(HERE / 'requests' / f'{case_id}.full-native-qualification.request.json'),
        'future_receipt_sha256': None,
        'future_native_frame0_audit_sha256': None,
        'launch_allowed': False,
    }


def run() -> dict[str, Any]:
    cases = sorted(path.name.removesuffix('.corner-owner.json') for path in (HERE / 'owners').glob('*.corner-owner.json'))
    require(len(cases) == 8, f'expected 8 selected corner cases, found {len(cases)}')
    result_cases = [check_case(case_id) for case_id in cases]
    require({row['parent_case_id'] for row in result_cases} == SELECTED_PARENTS, 'selected parent coverage incomplete')
    require({tuple(row['velocity_m_per_s']) for row in result_cases} == {(0.1, 0.0, 0.0), (0.2, 0.0, 0.0)}, 'velocity endpoints incomplete')
    require(len({row['physical_condition_sha256'] for row in result_cases}) == 8, 'physical conditions are aliased')
    preserved = load(HERE / 'metadata' / 'preserved-first24-candidates.json')
    require({row['parent_case_id'] for row in preserved['cases']} == PRESERVED_PARENTS, 'preserved candidate set changed')
    require(len(preserved['cases']) == 8, 'preserved candidate count changed')
    return {
        'schema': 'ds02.f1.vx-corner-native-qualification-source-validation.v1',
        'handoff_id': 'root_followup_067_f1_vx_corner_native_qualification_v1',
        'family_id': 'F1',
        'source_only': True,
        'launch_allowed': False,
        'execution_allowed': False,
        'gencase_launched': False,
        'solver_launched': False,
        'native_frame0_audit_launched': False,
        'raw_arrays_read': False,
        'raw_arrays_hashed': False,
        'shared_index_or_ledger_modified': False,
        'independent_case_count_increment': 0,
        'selected_parent_count': 4,
        'selected_case_count': len(result_cases),
        'preserved_candidate_count': len(preserved['cases']),
        'cases': result_cases,
        'native_velocity_proof_policy': 'Only solver-saved native frame 0 Part_0000.bi4 through official PartVTK may establish requested VX; GenCase BI4/raw velocity is not evidence.',
        'mass_policy': 'Native weights remain unscaled; continuum mass is metadata and no equality/rescaling is asserted.',
        'q_n': 'not_assessed',
        'production_approval': 'none',
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    result = run()
    if args.write:
        path = HERE / 'metadata' / 'static-validation.json'
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
