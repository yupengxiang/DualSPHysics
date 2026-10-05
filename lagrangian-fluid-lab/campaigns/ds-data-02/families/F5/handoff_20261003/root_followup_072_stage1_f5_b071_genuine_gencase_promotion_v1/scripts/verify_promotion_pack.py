#!/usr/bin/env python3
"""Metadata-only verifier for the fresh072 promotion pack.

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
assert req['attempt_id'] == 'root-stage1-f5-b071-genuine-gencase-157'
assert req['launch_owner'] == 'root' and req['launch_allowed'] is True and req['execution_allowed'] is True
assert req['root_dataset_inventory_profile'] == 'root_home_floor_no_legacy_dataset_walk_v1'
assert req['cpu_task_kind'] == 'gencase' and req['kind'] == 'cpu'
assert req['genuine_gencase'] is True and req['solver_allowed'] is False and req['conversion_allowed'] is False
assert req['full16_authorized'] is False and req['independent_case_count_increment'] == 0
assert bind['definition_sha256'] == sha(bind['definition'])
for asset in bind['assets']:
    assert sha(asset['source']) == asset['sha256']
for p, expected in req['input_sha256'].items():
    assert Path(p).is_file(), p
    assert sha(p) == expected, p
assert down['all_downstream_disabled'] is True
for stage in down['stages'].values():
    assert stage['launch_allowed'] is False and stage['execution_allowed'] is False
print(json.dumps({'status': 'metadata_pass', 'inputs_checked': len(req['input_sha256']), 'arrays_opened': False, 'jobs_started': False}, sort_keys=True))
