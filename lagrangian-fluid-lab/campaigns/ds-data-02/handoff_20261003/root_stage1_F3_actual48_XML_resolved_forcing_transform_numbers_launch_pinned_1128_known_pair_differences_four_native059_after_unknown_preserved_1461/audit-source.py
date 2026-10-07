from pathlib import Path
import json, hashlib, datetime, itertools, math, subprocess, xml.etree.ElementTree as ET
R = Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics')
H = R / 'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003'
S = Path('/home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/root_followup_211_f6_assigned_f3_actual_forcing_pairwise_provenance_v1/metadata/f3-actual-forcing-pairwise-provenance.json')
root = lambda n: next(H.glob(f'root*_{n:03d}'))
def load(p):
    assert Path(p).suffix == '.json'
    return json.loads(Path(p).read_text())
def sha(p):
    assert Path(p).suffix in {'.json', '.xml', '.py', '.md'}
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()
ref = lambda p: {'path': str(p), 'sha256': sha(p)}
ip = root(1450) / 'full336-current336-actual-final48-delivery-progress-index.json'
index = {r['physical_case_id']: r for r in load(ip)['cases'] if r['family_id'] == 'F3'}
cp = load(H / 'ROOT_LIVE_RESUMPTION_CHECKPOINT_334.json')
prodref = cp['actual_progress']['F3_final48_complete_actual_primary_delivery']
assert sha(prodref['path']) == prodref['sha256']
products = {r['physical_case_id']: r for r in load(prodref['path'])['accepted48_actual_primary_rows']}
rows = []; running = []
for r in load(S)['rows']:
    pid = r['physical_case_id']; rp = Path(r['native_receipt']['path']); n = load(rp)
    assert sha(rp) == r['native_receipt']['sha256']
    scope = index[pid]['native_request_scope']
    refs = [scope.get('actual_native_receipt'), scope.get('evidence', {}).get('receipt')]
    refs += [o['receipt'] for o in scope.get('actual_native_receipt_observations', [])]
    assert ref(rp) in refs
    sp = Path(r['producer_report']['path']); dg = sha(sp); report = load(sp)
    assert dg == r['producer_report']['sha256'] == n['input_hashes_at_launch'][str(sp)]
    xp = Path(r['metadata_sha_join']['native_xml']['path']); xd = sha(xp)
    assert xd == n['input_hashes_at_launch'][str(xp)]
    assert str(xp.with_suffix('')) in n['request']['command']
    tr = report['forcing_transform']; assert tr['status'] == 'success'
    numeric = {'forcing_amplitude_x_scale': tr['amplitude_x'], 'transverse_amplitude_m_s2': tr['amplitude_y']}
    assert all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in numeric.values())
    assert tr['amplitude_x'] == r['forcing_numeric_fields']['amplitude_x'] and tr['amplitude_y'] == r['forcing_numeric_fields']['amplitude_y']
    xml = ET.parse(xp); node = xml.find('.//acctimesfile'); assert node is not None
    value = node.get('value'); forcing = Path(value) if Path(value).is_absolute() else xp.parent / value
    assert str(forcing) == tr['output_file'] == r['producer_output']['path']
    fd = tr['output_sha256']; assert n['input_hashes_at_launch'][str(forcing)] == fd
    if n['status'] == 'completed':
        assert n['returncode'] == 0
        for path, digest in [(sp, dg), (xp, xd), (forcing, fd)]:
            assert n['input_hashes_after_run'][str(path)] == digest
        after_status = 'available; launch, after and current metadata agree'
    else:
        assert n['status'] == 'running' and n.get('returncode') is None
        assert not n.get('input_hashes_after_run')
        running.append(pid); after_status = 'unknown in original native059 receipt; launch attestation only; completion recovery is a separate role'
    rows.append({'family_id': 'F3', 'physical_case_id': pid, 'actual_native_receipt': ref(rp),
        'actual_preparation_report': ref(sp), 'actual_generated_XML': ref(xp),
        'numeric_physical_discriminators': numeric,
        'source_field_pointers': {'forcing_amplitude_x_scale': '/forcing_transform/amplitude_x', 'transverse_amplitude_m_s2': '/forcing_transform/amplitude_y'},
        'actual_forcing_file': {'path': str(forcing), 'producer_attested_SHA_matches_native_launch': fd, 'scientific_file_read_or_hashed': False},
        'original_native_status': n['status'], 'original_native_returncode': n.get('returncode'), 'native_after_pin_status': after_status,
        'registered_native_completion_recovery_separate_role': products[pid].get('registered_native_completion_recovery'),
        'old_typed_runtime_boundary_preserved': products[pid].get('actual_typed_runtime_boundary_inherited_from_same_case'),
        'request_declaration_absence_and_copied_nominal_metadata': r['request_forcing_declaration'],
        'missing_nominal_pitch_label_not_used_as_numeric_difference': True,
        'physical_comparison_basis': 'Actual case-resolved forcing transform numbers, not request field-set shape or identifiers.'})
assert len(rows) == 48 and len(running) == 4
pairs = []
for a, b in itertools.combinations(rows, 2):
    x, y = a['numeric_physical_discriminators'], b['numeric_physical_discriminators']
    diff = sorted(k for k in x.keys() & y.keys() if x[k] != y[k]); assert diff
    pairs.append({'case_a': a['physical_case_id'], 'case_b': b['physical_case_id'], 'known_numeric_difference_fields': diff})
O = H / 'root_stage1_F3_actual48_XML_resolved_forcing_transform_numbers_launch_pinned_1128_known_pair_differences_four_native059_after_unknown_preserved_1461'
O.mkdir(exist_ok=False)
lookup = root(1456) / 'actual-two-F3-endpoint-forcing-and-stale-request-binding-proof.json'
proof = {'schema': 'ds02.main.F3.actual48-forcing-distinction.v1', 'at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'source211': ref(S), 'actual_current_index': ref(ip), 'F3_actual_final48_product': prodref,
    'official_XML_relative_forcing_file_lookup_already_proved': ref(lookup), 'rows': rows,
    'families': {'F3': {'actual_cases': 48, 'pairwise_known_numeric_differences': 1128, 'unknown_used_as_difference': False, 'pair_evidence': pairs}},
    'original_native059_after_pins_unknown': running,
    'scientific_payload_IO': False, 'new_jobs': False, 'case_credit': 0, 'Q_N': 0, 'Q_E': 0}
(O / 'actual48-launch-pinned-forcing-known-physical-differences.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n')
(O / 'audit-source.py').write_bytes(Path(__file__).read_bytes())
rel = [str(p.relative_to(R)) for p in O.iterdir()]
subprocess.run(['git', 'add', '--', *rel], cwd=R, check=True)
subprocess.run(['git', 'commit', '-q', '-m', 'DS02: prove actual F3 forcing distinctions preserving original native059 after absence and stale nominal roles', '--', *rel], cwd=R, check=True)
print(json.dumps({'actual_cases': 48, 'pairwise_known_numeric_differences': 1128, 'native059_original_after_unknown': len(running), 'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=R, text=True).strip()}))
