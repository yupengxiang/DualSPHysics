#!/usr/bin/env python3
"""Build a metadata-only F2 first48 pipeline census.

This script reads only JSON metadata, receipt/config/log filenames and owner
metadata. It never opens BI4/H5/CSV/DAT/VTK scientific payloads and never
launches or mutates a runner.
"""
from __future__ import annotations

import json
import os
import pathlib
from datetime import datetime, timezone

DATA = pathlib.Path('/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2')
H = pathlib.Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003')
F6 = pathlib.Path('/home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003')
CHECKPOINT = H / 'ROOT_LIVE_RESUMPTION_CHECKPOINT_172.json'
OUT = pathlib.Path(__file__).resolve().parents[1] / 'metadata' / 'f2-first48-census.json'

FRESH140 = F6 / 'root_followup_140_f2_actual_native_typed157_home4gib_v1'
FRESH142 = F6 / 'root_followup_142_f2_actual_native_typed157_home4gib_v2'


def read_json(path: pathlib.Path):
    # This function is only called for explicitly allowed JSON metadata files.
    with path.open(encoding='utf-8') as fh:
        return json.load(fh)


def first48_cases():
    return [
        f'F2_STAGE1_FIRST48_EXPANSION_RX{rx:03d}_RY014_FILL080_ROT{rot:03d}_DP010_SPATIAL_REFERENCE_SAVE010'
        for rx in (47, 49, 51, 53, 56, 58, 61, 63)
        for rot in (75, 90, 105)
    ]


def classify_receipt(rel: pathlib.Path):
    s = str(rel).lower()
    # Check the most specific stage names first.
    if 'gencase' in s:
        return 'gencase'
    if 'initial-qa' in s or 'initialqa' in s or 'initial_qa' in s:
        return 'initial_qa'
    if 'typed' in s or 'conversion' in s:
        return 'typed'
    if 'xmf' in s or 'xdmf' in s:
        return 'xmf'
    if 'render' in s or 'paraview' in s:
        return 'render'
    if 'native' in s or 'full401' in s:
        return 'native'
    return None


def receipt_status(obj):
    status = obj.get('status')
    rc = obj.get('returncode')
    if status in {'completed', 'success', 'succeeded'} and rc in (None, 0):
        return 'completed0'
    if status in {'running', 'started', 'queued', 'pending', 'live'}:
        return 'live'
    if rc not in (None, 0):
        return f'failed_rc_{rc}'
    return str(status) if status is not None else 'unknown'


def metadata_names():
    return {
        'conversion-report.json',
        'prepared-input-report.json',
        'initial-native-qa.json',
        'paraview-full-animation-report.json',
        'render-report.json',
        'manifest.json',
    }


def data_stage_scan(case_id):
    case_root = DATA / case_id
    stages = {k: {'receipts': [], 'metadata': []} for k in
              ('gencase', 'initial_qa', 'native', 'typed', 'xmf', 'render')}
    if not case_root.exists():
        return stages
    for receipt in case_root.rglob('execution-receipt.json'):
        stage = classify_receipt(receipt.relative_to(case_root))
        if stage is None:
            continue
        try:
            obj = read_json(receipt)
        except (OSError, ValueError):
            continue
        stages[stage]['receipts'].append({
            'status': receipt_status(obj),
            'returncode': obj.get('returncode'),
            'receipt': str(receipt),
            'attempt_root': str(receipt.parent),
            'output_root': obj.get('output_root'),
            'started_at_utc': obj.get('started_at_utc'),
            'finished_at_utc': obj.get('finished_at_utc'),
        })
    # Filename-only inventory of small metadata products. Their contents are
    # intentionally not loaded here; scientific payloads are never traversed.
    allowed = metadata_names()
    for path in case_root.rglob('*'):
        if path.is_file() and path.name.lower() in allowed:
            stage = classify_receipt(path.relative_to(case_root))
            if stage is not None:
                stages[stage]['metadata'].append(str(path))
    for stage in stages:
        stages[stage]['receipts'].sort(key=lambda x: x['receipt'])
        stages[stage]['metadata'].sort()
    return stages


def summary(receipts):
    rs = receipts.get('receipts', [])
    if any(x['status'] == 'completed0' for x in rs):
        state = 'completed0'
    elif any(x['status'] == 'live' for x in rs):
        state = 'live'
    elif any(x['status'].startswith('failed') for x in rs):
        state = 'failed'
    elif rs:
        state = 'unknown'
    else:
        state = 'missing'
    return {'status': state, **receipts}


def owner_for(case_id):
    candidates = list((FRESH140 / 'owners').glob(case_id + '-actual-native-typed157-owner.json'))
    candidates += list((FRESH142 / 'owners').glob(case_id + '-actual-native-typed157-owner.json'))
    if not candidates:
        return None
    path = sorted(candidates)[-1]
    obj = read_json(path)
    scalar_keys = (
        'schema', 'family_id', 'fresh_id', 'case_id', 'physical_case_id',
        'physical_condition_sha256', 'source_plan_physical_condition_sha256',
        'canonical_physical_binding_sha256',
        'prospective_legacy_converter_scope_sha256',
        'actual_converter_physical_condition_scope_sha256',
        'actual_converter_scope_sha256_prospective',
        'mechanism_id', 'control_family_id', 'geometry_family_id',
        'lineage_group_id', 'density_kg_m3', 'disabled', 'execution_allowed',
        'source_only', 'no_new_case_credit',
    )
    result = {'path': str(path)}
    for key in scalar_keys:
        value = obj.get(key)
        if isinstance(value, (str, int, float, bool)) or value is None:
            result[key] = value
    return result


def load_request(path):
    try:
        return read_json(path)
    except (OSError, ValueError):
        return {}


def process_alive(pid):
    return bool(pid and os.path.exists('/proc/' + str(pid)))


def registration_inventory(case_id, kind):
    """Read Root handoff registrations, without opening scientific outputs."""
    request_name = 'enabled-full401-xmf-request.json' if kind == 'xmf' else 'enabled-full401-render-request.json'
    entries = []
    for directory in sorted(H.glob('root_stage1_F2_RX*')):
        request_paths = sorted(directory.rglob(('*' + request_name) if kind == 'xmf' else request_name))
        if not request_paths:
            continue
        request_path = request_paths[0]
        request = load_request(request_path)
        if request.get('case_id') != case_id:
            continue
        physical = request.get('physical_case_id')
        launch_path = directory / 'controller-launch-process.json'
        result_path = directory / 'controller-result.json'
        launch = load_request(launch_path) if launch_path.exists() else {}
        result = load_request(result_path) if result_path.exists() else {}
        pid = launch.get('pid')
        result_status = result.get('status')
        result_rc = result.get('returncode')
        actual_receipt = result.get('actual_receipt')
        if actual_receipt and pathlib.Path(actual_receipt).exists():
            state = 'completed0' if result_status == 'completed' and result_rc in (None, 0) else 'unknown'
        elif result_status == 'completed' and result_rc in (None, 0):
            state = 'completed0'
        elif result_status == 'failed' or result_rc not in (None, 0):
            state = 'failed'
        elif process_alive(pid):
            state = 'registered_live'
        else:
            state = 'registered_no_terminal'
        sidecars = []
        sidecar_scopes = {}
        for sidecar in sorted(directory.glob('actual*registration*.json')):
            sidecars.append(str(sidecar))
            try:
                sobj = read_json(sidecar)
            except (OSError, ValueError):
                continue
            for key in ('actual_converter_legacy_scope', 'actual_converter_physical_condition_scope_sha256',
                        'source_canonical_and_plan_scope', 'physical_condition_sha256',
                        'actual_converter_scope_sha256'):
                value = sobj.get(key)
                if isinstance(value, (str, int, float, bool)) or value is None:
                    sidecar_scopes[key] = value
        entry = {
            'registration_dir': str(directory),
            'request': str(request_path),
            'wrapper': str(directory / ('enabled-render-wrapper.json' if kind == 'render' else '')) if kind == 'render' else None,
            'registration_sidecars': sidecars,
            'registration_sidecar_scopes': sidecar_scopes,
            'controller_launch_process': str(launch_path) if launch_path.exists() else None,
            'controller_result': str(result_path) if result_path.exists() else None,
            'controller_pid': pid,
            'pid_alive_snapshot': process_alive(pid),
            'status': state,
            'actual_receipt': actual_receipt,
            'physical_case_id': physical,
        }
        # Keep only scalar request identity and expected dimensions.
        for key in ('attempt_id', 'physical_condition_sha256', 'actual_converter_scope_sha256', 'expected_frames', 'expected_particles'):
            value = request.get(key)
            if isinstance(value, (str, int, float, bool)) or value is None:
                entry[key] = value
        entries.append(entry)
    return entries


def merge_stage(case_id, data_summary, registrations, stage):
    data_state = data_summary[stage]['status']
    reg_state = 'missing'
    if registrations:
        states = {x['status'] for x in registrations}
        if 'completed0' in states:
            reg_state = 'completed0'
        elif 'registered_live' in states:
            reg_state = 'registered_live'
        elif 'registered_no_terminal' in states:
            reg_state = 'registered_no_terminal'
        elif 'failed' in states:
            reg_state = 'failed'
    if data_state == 'completed0':
        state = 'completed0'
    elif data_state == 'live':
        state = 'live'
    elif reg_state != 'missing':
        state = reg_state
    else:
        state = data_state
    return {'status': state, 'data': data_summary[stage], 'registrations': registrations}


def accepted_records():
    checkpoint = read_json(CHECKPOINT)
    records = []
    seen = set()
    for decision_path in checkpoint.get('accepted_decisions', []):
        if not isinstance(decision_path, str) or ('/F2' not in decision_path and '/f2' not in decision_path):
            continue
        path = pathlib.Path(decision_path)
        if not path.exists():
            continue
        try:
            decision = read_json(path)
        except (OSError, ValueError):
            continue
        if decision.get('family_id') != 'F2':
            continue
        physical = decision.get('physical_case_id')
        if not physical or physical in seen:
            continue
        seen.add(physical)
        records.append({
            'case_id': decision.get('case_id'),
            'physical_case_id': physical,
            'physical_condition_sha256': decision.get('physical_condition_sha256'),
            'decision_path': str(path),
            'status': decision.get('status'),
        })
    return checkpoint, records


def build():
    checkpoint, accepted = accepted_records()
    accepted_ids = {x['physical_case_id'] for x in accepted}
    cases = []
    for case_id in first48_cases():
        rx = int(case_id.split('_RX', 1)[1][:3])
        rot = int(case_id.split('_ROT', 1)[1][:3])
        physical = f'F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX{rx:03d}_RY014_FILL080_ROT{rot:03d}'
        raw = data_stage_scan(case_id)
        data_summary = {k: summary(raw[k]) for k in raw}
        stage = {k: data_summary[k] for k in ('gencase', 'initial_qa', 'native', 'typed')}
        stage['xmf'] = merge_stage(case_id, data_summary, registration_inventory(case_id, 'xmf'), 'xmf')
        stage['render'] = merge_stage(case_id, data_summary, registration_inventory(case_id, 'render'), 'render')
        cases.append({
            'case_id': case_id,
            'physical_case_id': physical,
            'rotation_deg': rot,
            'accepted_at_checkpoint': physical in accepted_ids,
            'owner_metadata': owner_for(case_id),
            'stages': stage,
        })

    def data_receipts(stage_obj):
        payload = stage_obj.get('data', stage_obj)
        return payload.get('receipts', [])

    def data_metadata(stage_obj):
        payload = stage_obj.get('data', stage_obj)
        return payload.get('metadata', [])

    # Strictly actionable missing-stage criteria. Live work is recorded but is
    # not promoted to a new gap or failure.
    selected = []
    deferred = []
    for case in cases:
        st = case['stages']
        if st['xmf']['status'] == 'missing' and st['typed']['status'] in {'completed0', 'missing'} and not case['accepted_at_checkpoint']:
            gap_kind = 'typed157_completed_without_xmf_registration' if st['typed']['status'] == 'completed0' else 'typed157_missing_before_xmf'
            reason = (
                'actual typed157 producer is completed/0, but no XMF registration exists; Root can register the normal XMF request.'
                if gap_kind == 'typed157_completed_without_xmf_registration' else
                'actual native/QA metadata is present, but no terminal typed157 producer receipt and no XMF registration exists; Root must register the existing typed request first.'
            )
            selected.append({
                'case_id': case['case_id'],
                'physical_case_id': case['physical_case_id'],
                'gap_kind': gap_kind,
                'reason': reason,
                'producer_refs': {
                    'native_receipts': [x['receipt'] for x in data_receipts(st['native'])],
                    'typed_receipts': [x['receipt'] for x in data_receipts(st['typed'])],
                    'typed_reports': data_metadata(st['typed']),
                    'owner_metadata': case['owner_metadata']['path'] if case['owner_metadata'] else None,
                },
                'physical_scope': case['owner_metadata'],
            })
        elif st['xmf']['status'] == 'completed0' and st['render']['status'] == 'missing' and not case['accepted_at_checkpoint']:
            selected.append({
                'case_id': case['case_id'],
                'physical_case_id': case['physical_case_id'],
                'gap_kind': 'xmf_completed_without_render_registration',
                'reason': 'actual XMF completed/0, but no render request registration is present in the handoff snapshot.',
                'producer_refs': {
                    'xmf_receipts': [x['receipt'] for x in data_receipts(st['xmf'])],
                    'xmf_metadata': data_metadata(st['xmf']),
                    'xmf_registrations': [x['registration_dir'] for x in st['xmf']['registrations']],
                    'xmf_registration_scopes': [x.get('registration_sidecar_scopes', {}) for x in st['xmf']['registrations']],
                    'typed_receipts': [x['receipt'] for x in data_receipts(st['typed'])],
                    'typed_reports': data_metadata(st['typed']),
                    'owner_metadata': case['owner_metadata']['path'] if case['owner_metadata'] else None,
                },
                'physical_scope': case['owner_metadata'],
            })
        elif st['typed']['status'] == 'live' or st['xmf']['status'] in {'live', 'registered_live'}:
            deferred.append({
                'case_id': case['case_id'],
                'physical_case_id': case['physical_case_id'],
                'status': 'wait_for_existing_live_registration',
                'typed_status': st['typed']['status'],
                'xmf_status': st['xmf']['status'],
                'render_status': st['render']['status'],
                'note': 'Existing live producer/registration is preserved; no duplicate request is proposed by fresh154.',
            })

    selected.sort(key=lambda x: x['case_id'])
    # A bounded handoff may name at most five executable gaps.
    selected = selected[:5]

    checkpoint_summary = {
        'path': str(CHECKPOINT),
        'checkpoint': checkpoint.get('checkpoint'),
        'at_utc': checkpoint.get('at_utc'),
        'accepted_per_family': checkpoint.get('accepted_per_family'),
        'f2_accepted_count': checkpoint.get('accepted_per_family', {}).get('F2'),
    }
    explicit_recent = {}
    for ident in (1116, 1117, 1118, 1119, 1120):
        dirs = sorted(H.glob(f'*_{ident}'))
        explicit_recent[str(ident)] = []
        for d in dirs:
            # This keeps only the registration metadata; no scientific output.
            reqs = [p for p in d.glob('*.json') if 'request' in p.name or p.name in {'controller-result.json', 'controller-launch-process.json', 'actual-progress.json'}]
            explicit_recent[str(ident)].append({'directory': str(d), 'metadata_files': [str(p) for p in sorted(reqs)]})

    result = {
        'schema': 'ds02.f6.fresh154.f2-full48-pipeline-census.v1',
        'fresh_id': 'fresh154',
        'snapshot_at_utc': datetime.now(timezone.utc).isoformat(),
        'family_id': 'F6',
        'census_family': 'F2',
        'purpose': 'Bounded metadata-only census of the F2 first48 physical pipeline; no jobs or case credit.',
        'source_inputs': {
            'fresh140_manifest': str(FRESH140 / 'F2_STAGE1_FRESH140_ACTUAL_NATIVE_TYPED157_MANIFEST.json'),
            'fresh142_manifest': str(FRESH142 / 'F2_STAGE1_FRESH142_ACTUAL_NATIVE_TYPED157_MANIFEST.json'),
            'checkpoint': checkpoint_summary,
            'recent_root_registrations': explicit_recent,
        },
        'policy': {
            'scientific_payloads_read_or_hashed': False,
            'forbidden_payload_extensions': ['.bi4', '.h5', '.csv', '.dat', '.vtk'],
            'jobs_started': False,
            'shared_state_modified': False,
            'new_case_credit': 0,
            'live_registrations_are_not_promoted': True,
            'source_plan_canonical_and_actual_converter_scopes_kept_separate': True,
        },
        'accepted_f2_physical_ids': accepted,
        'first48_total': len(cases),
        'first48_accepted_count': sum(1 for c in cases if c['accepted_at_checkpoint']),
        'first48_unaccepted_count': sum(1 for c in cases if not c['accepted_at_checkpoint']),
        'stage_counts': {
            stage: {state: sum(1 for c in cases if c['stages'][stage]['status'] == state)
                    for state in sorted({c['stages'][stage]['status'] for c in cases})}
            for stage in ('gencase', 'initial_qa', 'native', 'typed', 'xmf', 'render')
        },
        'cases': cases,
        'selected_gaps': selected,
        'deferred_live_cases': deferred,
        'strict_gap_counts': {
            'typed_completed_without_registered_xmf': sum(1 for c in cases if c['stages']['typed']['status'] == 'completed0' and c['stages']['xmf']['status'] == 'missing'),
            'xmf_completed_without_registered_render': sum(1 for c in cases if c['stages']['xmf']['status'] == 'completed0' and c['stages']['render']['status'] == 'missing' and not c['accepted_at_checkpoint']),
            'typed_missing_without_xmf': sum(1 for c in cases if c['stages']['typed']['status'] == 'missing' and c['stages']['xmf']['status'] == 'missing' and not c['accepted_at_checkpoint']),
        },
    }
    OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + '\n', encoding='utf-8')
    print(OUT)
    print('cases', len(cases), 'accepted', result['first48_accepted_count'], 'unaccepted', result['first48_unaccepted_count'], 'selected', len(selected))
    print('stage_counts', result['stage_counts'])
    print('selected', [(x['physical_case_id'], x['gap_kind']) for x in selected])


if __name__ == '__main__':
    build()
