from pathlib import Path
import json, hashlib, datetime, itertools, math, subprocess, xml.etree.ElementTree as ET
R = Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics')
H = R / 'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003'
S = Path('/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_233_f5_f1_f6_numeric_tuple_pin_audit_v1/numeric-tuple-pin-report.json')
root = lambda n: next(H.glob(f'root*_{n:03d}'))
def load(p):
    assert Path(p).suffix == '.json'
    return json.loads(Path(p).read_text())
def sha(p):
    assert Path(p).suffix in {'.json', '.xml', '.py', '.md'}
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()
ref = lambda p: {'path': str(p), 'sha256': sha(p)}
ip = root(1450) / 'full336-current336-actual-final48-delivery-progress-index.json'
index = {r['physical_case_id']: r for r in load(ip)['cases'] if r['family_id'] == 'F6'}
rows = []
for r in load(S)['rows']:
    if r['family_id'] != 'F6': continue
    pid = r['case_ref']; rp = Path(r['native_pin']['receipt_path']); n = load(rp)
    scope = index[pid]['native_request_scope']
    refs = [scope.get('actual_native_receipt'), scope.get('evidence', {}).get('receipt'), scope.get('actual_native_receipt_observation', {}).get('actual_native_receipt')]
    refs += [o['receipt'] for o in scope.get('actual_native_receipt_observations', [])]
    assert ref(rp) in refs
    assert n['status'] == 'completed' and n['returncode'] == 0
    sp = Path(r['numeric_source']['path']); dg = sha(sp)
    assert n['input_hashes_at_launch'][str(sp)] == n['input_hashes_after_run'][str(sp)] == dg
    if sp.suffix == '.xml':
        assert pid == 'F6_STAGE1_ANGULAR_RELEASE_OMEGA_BASELINE'
        xml = ET.parse(sp); node = xml.find('./execution/particles/floating/angularvelini')
        vector = [float(node.get(a)) for a in ['x', 'y', 'z']]
        definition = xml.find('./casedef/floatings/floating/angularvelini')
        assert vector == [float(definition.get(a)) for a in ['x', 'y', 'z']] == [.08, .12, .06]
        assert 'initial_angular_velocity_rad_s' not in n['request']
        pointer = 'execution.particles.floating.angularvelini@x/y/z'
    else:
        d = load(sp); vector = d['physical_binding']['parameters']['initial_angular_velocity_rad_s']
        assert vector == n['request']['initial_angular_velocity_rad_s']
        pointer = '/physical_binding/parameters/initial_angular_velocity_rad_s'
    assert vector == r['numeric_tuple']['initial_angular_velocity_rad_s'] and len(vector) == 3
    assert all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in vector)
    rows.append({'family_id': 'F6', 'physical_case_id': pid, 'actual_native_receipt': ref(rp),
        'actual_numeric_source': ref(sp), 'source_field_pointer': pointer,
        'numeric_physical_discriminators': {f'initial_angular_velocity_{axis}_rad_s': v for axis, v in zip('xyz', vector)},
        'launch_after_current_metadata_SHA_match': True,
        'baseline_request_angular_field_absence_preserved': sp.suffix == '.xml',
        'unknown_yaw_not_used_as_difference': True, 'lifecycle_limits': 'Root1454 retains all small unknown-cause fluid omissions; numeric accuracy is unaccepted.'})
assert len(rows) == 48
pairs = []
for a, b in itertools.combinations(rows, 2):
    x, y = a['numeric_physical_discriminators'], b['numeric_physical_discriminators']
    diff = sorted(k for k in x.keys() & y.keys() if x[k] != y[k]); assert diff
    pairs.append({'case_a': a['physical_case_id'], 'case_b': b['physical_case_id'], 'known_numeric_difference_fields': diff})
O = H / 'root_stage1_F6_actual48_pinned_initial_angular_vectors_request_and_actual_baseline_XML_1128_known_pair_differences_yaw_absence_preserved_1460'
O.mkdir(exist_ok=False)
proof = {'schema': 'ds02.main.F6.actual48-angular-vector-distinction.v1', 'at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'source233': ref(S), 'actual_current_index': ref(ip), 'rows': rows,
    'families': {'F6': {'actual_cases': 48, 'pairwise_known_numeric_differences': 1128, 'unknown_used_as_difference': False, 'pair_evidence': pairs}},
    'scientific_payload_IO': False, 'new_jobs': False, 'case_credit': 0, 'Q_N': 0, 'Q_E': 0}
(O / 'actual48-native-pinned-angular-vector-known-physical-differences.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n')
(O / 'audit-source.py').write_bytes(Path(__file__).read_bytes())
rel = [str(p.relative_to(R)) for p in O.iterdir()]
subprocess.run(['git', 'add', '--', *rel], cwd=R, check=True)
subprocess.run(['git', 'commit', '-q', '-m', 'DS02: prove actual F6 angular vector distinctions with native XML baseline and preserved yaw absence', '--', *rel], cwd=R, check=True)
print(json.dumps({'actual_cases': 48, 'pairwise_known_numeric_differences': 1128, 'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=R, text=True).strip()}))
