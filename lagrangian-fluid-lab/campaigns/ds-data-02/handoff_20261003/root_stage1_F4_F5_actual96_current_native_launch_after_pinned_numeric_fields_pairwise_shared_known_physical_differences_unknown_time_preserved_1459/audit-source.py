from pathlib import Path
import json, hashlib, datetime, itertools, math, subprocess
R = Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics')
H = R / 'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003'
S = Path('/home/jade/.codex/worktrees/ds-data-02-f3/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/root_followup_195_f3_assigned_f4_f5_actual96_native_pinned_physical_tuples_v1/metadata/f4-f5-actual96-native-pinned-tuples.json')
root = lambda n: next(H.glob(f'root*_{n:03d}'))
def load(p):
    assert Path(p).suffix == '.json'
    return json.loads(Path(p).read_text())
def sha(p):
    assert Path(p).suffix in {'.json', '.py', '.md'}
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()
ref = lambda p: {'path': str(p), 'sha256': sha(p)}
def walk(x, path=''):
    if isinstance(x, dict):
        for k, v in x.items():
            q = f'{path}.{k}' if path else k
            yield q, v; yield from walk(v, q)
    elif isinstance(x, list):
        for i, v in enumerate(x):
            q = f'{path}[{i}]'; yield q, v; yield from walk(v, q)
ip = root(1450) / 'full336-current336-actual-final48-delivery-progress-index.json'
index = {(r['family_id'], r['physical_case_id']): r for r in load(ip)['cases']}
source = load(S); rows = []
for r in source['rows']:
    native = r['native_receipt']; p = Path(native['path'])
    scope = index[(r['family_id'], r['physical_case_id'])]['native_request_scope']
    expected_native_refs = [scope.get('actual_native_receipt'), scope.get('evidence', {}).get('receipt')]
    expected_native_refs += [o['receipt'] for o in scope.get('actual_native_receipt_observations', [])]
    assert ref(p) in expected_native_refs
    assert sha(p) == native['sha256']
    n = load(p); assert n['status'] == 'completed' and n['returncode'] == 0
    sp = Path(r['selected_native_input']['path']); digest = sha(sp)
    assert str(sp) in n['request']['input_files']
    assert n['input_hashes_at_launch'][str(sp)] == n['input_hashes_after_run'][str(sp)] == digest
    doc = load(sp); values = dict(walk(doc)); numeric = {}
    for name, info in r['field_provenance'].items():
        value = values[info['json_pointer']]
        assert value == info['value'] == r['normalized_tuple'][name]
        assert isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        numeric[name] = value
    assert set(numeric) == set(r['normalized_tuple'])
    allowed = {'gap_m', 'x_offset_m', 'y_offset_m', 'speed_m_per_s'} if r['family_id'] == 'F4' else {'amplitude_scale', 'time_scale'}
    assert set(numeric) <= allowed
    rows.append({'family_id': r['family_id'], 'physical_case_id': r['physical_case_id'],
        'actual_native_receipt': ref(p), 'actual_case_input': ref(sp), 'numeric_physical_discriminators': numeric,
        'field_provenance': r['field_provenance'], 'missing_physical_fields': r['missing_known_fields'],
        'launch_after_current_metadata_SHA_match': True,
        'native_condition_and_typed_legacy_roles_preserved': r['native_condition_role_preserved']})
families = {}
for f in ['F4', 'F5']:
    rs = [r for r in rows if r['family_id'] == f]; assert len(rs) == 48
    examples = []
    for a, b in itertools.combinations(rs, 2):
        x, y = a['numeric_physical_discriminators'], b['numeric_physical_discriminators']
        differences = [k for k in x.keys() & y.keys() if x[k] != y[k]]
        assert differences, (f, a['physical_case_id'], b['physical_case_id'])
        examples.append({'case_a': a['physical_case_id'], 'case_b': b['physical_case_id'], 'known_numeric_difference_fields': sorted(differences)})
    families[f] = {'actual_cases': 48, 'pairwise_known_numeric_differences': 1128, 'unknown_used_as_difference': False, 'pair_evidence': examples}
assert len(rows) == 96
O = H / 'root_stage1_F4_F5_actual96_current_native_launch_after_pinned_numeric_fields_pairwise_shared_known_physical_differences_unknown_time_preserved_1459'
O.mkdir(exist_ok=False)
proof = {'schema': 'ds02.main.F4-F5.actual96-known-numeric-physical-distinction.v1', 'at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'source195': ref(S), 'actual_current_index': ref(ip), 'rows': rows, 'families': families,
    'scientific_payload_IO': False, 'new_jobs': False, 'case_credit': 0, 'Q_N': 0, 'Q_E': 0}
(O / 'actual96-native-pinned-known-numeric-physical-differences.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n')
(O / 'audit-source.py').write_bytes(Path(__file__).read_bytes())
rel = [str(p.relative_to(R)) for p in O.iterdir()]
subprocess.run(['git', 'add', '--', *rel], cwd=R, check=True)
subprocess.run(['git', 'commit', '-q', '-m', 'DS02: independently prove actual96 F4 F5 known numeric physical differences from current launch after pinned inputs', '--', *rel], cwd=R, check=True)
print(json.dumps({'actual_cases': 96, 'pairwise_known_numeric_differences': 2256, 'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=R, text=True).strip()}))
