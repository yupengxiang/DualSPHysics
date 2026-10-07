from pathlib import Path
import json, hashlib, datetime, itertools, math, subprocess
R = Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics')
H = R / 'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003'
S = Path('/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_234_f5_f1_field_provenance_pin_audit_v1/f1-field-provenance-report.json')
root = lambda n: next(H.glob(f'root*_{n:03d}'))
def load(p):
    assert Path(p).suffix == '.json'
    return json.loads(Path(p).read_text())
def sha(p):
    assert Path(p).suffix in {'.json', '.py', '.md'}
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()
ref = lambda p: {'path': str(p), 'sha256': sha(p)}
def pointer(doc, path):
    for part in path.lstrip('/').split('/'):
        key = part.replace('~1', '/').replace('~0', '~')
        doc = doc[int(key)] if isinstance(doc, list) else doc[key]
    return doc
ip = root(1450) / 'full336-current336-actual-final48-delivery-progress-index.json'
index = {r['physical_case_id']: r for r in load(ip)['cases'] if r['family_id'] == 'F1'}
rows = []
for r in load(S)['rows']:
    pid = r['case_ref']; rp = Path(r['native_pin']['receipt_path']); n = load(rp)
    scope = index[pid]['native_request_scope']
    refs = [scope.get('actual_native_receipt'), scope.get('evidence', {}).get('receipt')]
    refs += [o['receipt'] for o in scope.get('actual_native_receipt_observations', [])]
    assert ref(rp) in refs and n['status'] == 'completed' and n['returncode'] == 0
    numeric = {}; fields = {}
    for name, evidence in r['field_provenance'].items():
        sp = Path(evidence['path']); digest = sha(sp)
        assert digest == evidence['sha256'] == n['input_hashes_at_launch'][str(sp)] == n['input_hashes_after_run'][str(sp)]
        value = pointer(load(sp), evidence['json_pointer'])
        assert value == evidence['value'] == r['numeric_tuple'][name]
        assert isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        numeric[name] = value; fields[name] = {'source': ref(sp), 'json_pointer': evidence['json_pointer'], 'value': value, 'launch_after_current_metadata_SHA_match': True}
    assert set(numeric) == {'fluid_depth_m', 'initial_fluid_vx_m_s'}
    rows.append({'family_id': 'F1', 'physical_case_id': pid, 'actual_native_receipt': ref(rp),
        'numeric_physical_discriminators': numeric, 'field_provenance': fields,
        'depth_and_velocity_can_have_separate_actual_pinned_sources': True,
        'scope': 'Source-plan grid is used only where the field actually exists. Parent owner geometry metadata supplies old VX-plan liquid depth through an independent native-pinned field.'})
assert len(rows) == 48
pairs = []
for a, b in itertools.combinations(rows, 2):
    x, y = a['numeric_physical_discriminators'], b['numeric_physical_discriminators']
    diff = sorted(k for k in x.keys() & y.keys() if x[k] != y[k]); assert diff
    pairs.append({'case_a': a['physical_case_id'], 'case_b': b['physical_case_id'], 'known_numeric_difference_fields': diff})
O = H / 'root_stage1_F1_actual48_separate_liquid_depth_initial_velocity_JSON_field_pins_1128_known_pair_differences_no_ID_or_geometry_tree_counting_1462'
O.mkdir(exist_ok=False)
proof = {'schema': 'ds02.main.F1.actual48-field-pinned-distinction.v1', 'at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'source234': ref(S), 'actual_current_index': ref(ip), 'rows': rows,
    'families': {'F1': {'actual_cases': 48, 'pairwise_known_numeric_differences': 1128, 'unknown_used_as_difference': False, 'pair_evidence': pairs}},
    'scientific_payload_IO': False, 'new_jobs': False, 'case_credit': 0, 'Q_N': 0, 'Q_E': 0}
(O / 'actual48-field-pinned-depth-velocity-known-physical-differences.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n')
(O / 'audit-source.py').write_bytes(Path(__file__).read_bytes())
rel = [str(p.relative_to(R)) for p in O.iterdir()]
subprocess.run(['git', 'add', '--', *rel], cwd=R, check=True)
subprocess.run(['git', 'commit', '-q', '-m', 'DS02: prove F1 actual48 distinctions with separate current depth velocity field pins', '--', *rel], cwd=R, check=True)
print(json.dumps({'actual_cases': 48, 'pairwise_known_numeric_differences': 1128, 'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=R, text=True).strip()}))
