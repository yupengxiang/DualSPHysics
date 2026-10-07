from pathlib import Path
import json, hashlib, datetime, collections, subprocess, math

R = Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics')
H = R / 'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003'
root = lambda n: next(H.glob(f'root*_{n:03d}'))

def load(p):
    p = Path(p)
    assert p.suffix == '.json'
    return json.loads(p.read_text())

def sha(p):
    p = Path(p)
    assert p.suffix in {'.json', '.py', '.md'}
    return hashlib.sha256(p.read_bytes()).hexdigest()

def ref(p):
    return {'path': str(p), 'sha256': sha(p)}

def native_ref(s):
    if s.get('evidence', {}).get('receipt'):
        return s['evidence']['receipt']
    if s.get('actual_native_receipt_observation'):
        return s['actual_native_receipt_observation']['actual_native_receipt']
    return s['actual_native_receipt_observations'][0]['receipt']

def pinned_json(p, native):
    p = str(p)
    d = sha(p)
    assert native['input_hashes_at_launch'][p] == d, p
    assert native['input_hashes_after_run'][p] == d, p
    return load(p), {'path': p, 'sha256': d, 'actual_native_launch_and_after_run_pins_match': True}

cp = H / 'ROOT_LIVE_RESUMPTION_CHECKPOINT_333.json'
ip = root(1450) / 'full336-current336-actual-final48-delivery-progress-index.json'
idx = load(ip)
assert load(cp)['stage1_visual_accepted_complete_independent_cases'] == 336
rows = []
for case in idx['cases']:
    family = case['family_id']
    if family not in {'F2', 'F7'}:
        continue
    physical = case['physical_case_id']
    nr = native_ref(case['native_request_scope'])
    assert sha(nr['path']) == nr['sha256']
    n = load(nr['path'])
    assert n['status'] == 'completed' and n['returncode'] == 0
    req = n['request']
    case_id = req['case_id']
    pins = n['input_hashes_at_launch']
    evidence = []
    constraints = []
    if family == 'F2':
        candidates = [p for p in pins if Path(p).name.endswith('.metadata.json')]
        assert len(candidates) == 1, (physical, candidates)
        source, sr = pinned_json(candidates[0], n)
        assert source['physical_case_id'] == physical
        evidence.append(sr)
        if 'physical_geometry' in source:
            # The matched legacy mother has a different continuous fluid depth.
            # Its unknown RX/ROT fields are not used to manufacture uniqueness.
            height = source['physical_geometry']['continuous_fluid_size_m'][2]
            physical_tuple = {'fluid_height_m': height}
            fields = {'fluid_height_m': '/physical_geometry/continuous_fluid_size_m/2'}
            constraints.append('Legacy source has no parameter_values RX/ROT; the actual pinned continuous fluid height alone distinguishes it from every other F2 case.')
        else:
            pa = source['parameter_values']
            geometry = source['geometry']
            height = geometry.get('fluid_height_m')
            height_field = '/geometry/fluid_height_m'
            if height is None:
                height = geometry['fluid_source_size_m'][2]
                height_field = '/geometry/fluid_source_size_m/2'
            physical_tuple = {
                'fluid_height_m': height,
                'receiver_x_m': pa['receiver_x_m'],
                'receiver_y_m': pa['receiver_y_m'],
                'rotation_duration_s': pa['rotation_duration_s'],
            }
            fields = {'fluid_height_m': height_field, **{k: '/parameter_values/' + k for k in physical_tuple if k != 'fluid_height_m'}}
    else:
        actual_binding = req.get('actual_continuum_binding')
        candidates = [actual_binding] if actual_binding else [p for p in pins if Path(p).name == case_id + '.owner.json']
        if candidates:
            assert len(candidates) == 1
            source, sr = pinned_json(candidates[0], n)
            evidence.append(sr)
            binding = source.get('physical_binding', source.get('physical_condition', source))
            assert isinstance(binding, dict)
            amplitude = binding['parameters']['amplitude_deg']
            prefix = '/physical_binding' if 'physical_binding' in source else '/physical_condition' if 'physical_condition' in source else ''
            fields = {'amplitude_deg': prefix + '/parameters/amplitude_deg'}
        else:
            # Two historical endpoints use the exact QA binding, not a new owner.
            candidates = [p for p in pins if Path(p).name == 'binding.json' and 'root_followup_063_' in p]
            assert len(candidates) == 1, (physical, candidates)
            source, sr = pinned_json(candidates[0], n)
            evidence.append(sr)
            found = [(i, r) for i, r in enumerate(source['cases']) if r['case_id'] == case_id]
            assert len(found) == 1
            i, endpoint = found[0]
            amplitude = endpoint['amplitude_deg']
            fields = {'amplitude_deg': f'/cases/{i}/amplitude_deg'}
            gc = endpoint['gencase_receipt']
            assert sha(gc) == endpoint['gencase_receipt_sha256']
            gj = load(gc)
            assert gj['status'] == 'completed' and gj['returncode'] == 0
            # Compare producer declarations only; never open or hash the BI4.
            bi4 = endpoint['generated_bi4']
            assert pins[bi4] == endpoint['generated_bi4_sha256']
            assert n['input_hashes_after_run'][bi4] == pins[bi4]
            evidence.append({**ref(gc), 'actual_native_initial_BI4_declaration_matches_endpoint_GenCase_binding': True})
            constraints.append('Historical native physical_condition_sha256 field is absent; the actual launch-pinned QA binding and producer GenCase/initial-BI4 declaration establish the numeric endpoint. No absent native field is filled.')
        physical_tuple = {'amplitude_deg': amplitude}
    assert all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in physical_tuple.values())
    rows.append({
        'family_id': family, 'physical_case_id': physical, 'actual_native_request_case_id': case_id,
        'actual_native_receipt': nr, 'source_evidence': evidence,
        'physical_discriminators': physical_tuple, 'source_field_pointers': fields,
        'native_condition_field_present': 'physical_condition_sha256' in req,
        'native_condition_value': req.get('physical_condition_sha256'),
        'constraints': constraints, 'case_credit': 0, 'Q_N': 0, 'Q_E': 0,
    })
assert len(rows) == 96
families = {}
for family in ['F2', 'F7']:
    selected = [r for r in rows if r['family_id'] == family]
    assert len(selected) == 48
    groups = collections.defaultdict(list)
    for row in selected:
        key = tuple(sorted(row['physical_discriminators'].items()))
        groups[key].append(row['physical_case_id'])
    assert len(groups) == 48, {str(k): v for k, v in groups.items() if len(v) > 1}
    if family == 'F2':
        mothers = [r for r in selected if len(r['physical_discriminators']) == 1]
        assert len(mothers) == 1
        mother_height = mothers[0]['physical_discriminators']['fluid_height_m']
        assert all(r is mothers[0] or r['physical_discriminators']['fluid_height_m'] != mother_height for r in selected)
    families[family] = {'cases': 48, 'distinct_actual_physical_parameter_groups': 48, 'actual_native_JSON_source_launch_and_after_pins_verified': 48}
O = H / 'root_stage1_F2_F7_actual96_native_launch_after_JSON_pinned_numeric_physical_discriminators_no_ID_path_recipe_uniqueness_1452'
O.mkdir(exist_ok=False)
proof = {
    'schema': 'ds02.main.physical-discriminators.actual-native-pinned.v1',
    'at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'checkpoint': ref(cp), 'current336_index': ref(ip), 'families': families, 'rows': rows,
    'comparison_policy': 'Only displayed finite numeric physical values distinguish cases. IDs, file paths, hashes, numerical recipe, resolution, time windows, saves, aliases and views never enter the comparison. F2 legacy mother is separated by its actual continuous liquid height; missing controls are not used as evidence.',
    'main_scientific_payload_IO': False, 'main_scientific_payload_hashing': False,
    'stage1_goal_completion_claim': False, 'case_credit': 0, 'Q_N': 0, 'Q_E': 0,
}
(O / 'actual96-native-pinned-physical-discriminators.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n')
(O / 'audit-source.py').write_bytes(Path(__file__).read_bytes())
(O / 'README.md').write_text('F2/F7各48例的实际原生启动/结束输入绑定和数值物理差异独立核查。F2按实际流体高度、接收槽坐标和转动时长区分；历史母例仅用真实连续液体高度区别，未填补未知控制。F7按真实输入幅值区分，包括两例历史原生条件字段真正缺失的端点，它们仍保持缺失。没有读取或哈希科学载荷，没有新模拟。此证据只证明这96例的物理变化；全目标完成仍需其他五族及首阶段要求审计。\n')
rel = [str(p.relative_to(R)) for p in O.iterdir()]
subprocess.run(['git', 'add', '--', *rel], cwd=R, check=True)
subprocess.run(['git', 'commit', '-q', '-m', 'DS02: prove actual numeric physical distinction for F2 and F7 through 96 native input pins', '--', *rel], cwd=R, check=True)
print(json.dumps({'output': str(O), 'families': families, 'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=R, text=True).strip()}))
