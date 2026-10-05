#!/usr/bin/env python3
"""Metadata-only verifier for the fresh073 promotion pack.

It hashes registered source/request inputs and checks launch gates. It does not
open BI4/H5/CSV arrays and does not start any process.
"""
import hashlib, json
from pathlib import Path

root = Path(__file__).resolve().parents[1]

def sha(p):
    h = hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()

req = json.loads((root / 'request.json').read_text())
bind = json.loads((root / 'gencase-binding.json').read_text())
down = json.loads((root / 'downstream-disabled.json').read_text())
assert req['schema'] == 'ds02.runner-request.v2'
assert req['attempt_id'] == 'root-stage1-f5-b071-genuine-gencase-163'
assert req['launch_owner'] == 'root' and req['launch_allowed'] is True and req['execution_allowed'] is True
assert req['root_dataset_inventory_profile'] == 'root_home_floor_no_legacy_dataset_walk_v1'
assert req['cpu_task_kind'] == 'gencase' and req['kind'] == 'cpu'
assert req['genuine_gencase'] is True and req['solver_allowed'] is False and req['conversion_allowed'] is False
assert req['full16_authorized'] is False and req['independent_case_count_increment'] == 0
assert not any('resource-ledger.json' in p for p in req['input_files'])
assert not any('resource-ledger.json' in p for p in req['input_sha256'])
assert bind['schema'] == 'ds02.f5.stage1.fresh073.genuine-gencase-binding.v1'
assert bind['case_id'] == 'F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_B071'
assert bind['threads'] == 2 and bind['dp_m'] == 0.02
assert bind['definition_sha256'] == 'e912c12cc6cf9d3e754cba69a307f47588e717a8a4717f1ed190c63443cc3e72'
assert bind['definition_sha256'] == sha(bind['definition'])
assert req['binding_requirements']['threads'] == 2
assert req['binding_requirements']['dp_m'] == 0.02
assert req['binding_requirements']['definition_sha256'] == bind['definition_sha256']
assert req['binding_requirements']['gencase_sha256'] == 'a1b6414e0f716669363d1a80a05e133085c04995e15716e3c1f0406e0d023226'
for asset in bind['assets']:
    assert sha(asset['source']) == asset['sha256']
for p, expected in req['input_sha256'].items():
    assert Path(p).is_file(), p
    assert sha(p) == expected, p
assert down['all_downstream_disabled'] is True
for stage in down['stages'].values():
    assert stage['launch_allowed'] is False and stage['execution_allowed'] is False
print(json.dumps({'status': 'metadata_pass', 'inputs_checked': len(req['input_sha256']), 'live_ledger_registered': False, 'arrays_opened': False, 'jobs_started': False}, sort_keys=True))
