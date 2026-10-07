from pathlib import Path
import json, hashlib, collections, datetime, subprocess

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

products = {
    'F2': root(1444) / 'F2-FINAL48-COMPLETE-ACTUAL401-PRIMARY-DELIVERY.json',
    'F6': root(1353) / 'F6-FINAL48-COMPLETE-PARTICLE-RIGID-ACTUAL-PRIMARY-DELIVERY.json',
}
rows = []
delivery_path = root(1451) / 'DS-DATA-02-ACTUAL-USER-DELIVERY-INDEX.json'
delivery = {(r['family_id'], r['physical_case_id']): r for r in load(delivery_path)['cases']}
for family, p in products.items():
    product = load(p)
    selected = product['accepted48_actual_primary_rows' if family == 'F2' else 'rows']
    assert len(selected) == 48
    for case in selected:
        physical = case['physical_case_id']
        if family == 'F2':
            rr = case['primary_metadata']['actual_producer_conversion_report']
            xr = case['primary_metadata']['XMF_manifest']
            declared = case['lifecycle_omission_metadata']
        else:
            candidates = [r for r in case['primary_refs']['typed'] if Path(r['path']).name == 'conversion-report.json']
            assert len(candidates) == 1
            rr = candidates[0]
            xr = case['accepted_visual_metadata']['actual_xmf_manifest']
            declared = None
        assert sha(rr['path']) == rr['sha256']
        canonical_xr = delivery[(family, physical)]['primary_delivery']['manifest']
        assert canonical_xr['path'] == xr['path']
        assert sha(xr['path']) == canonical_xr['sha256']
        if xr.get('sha256') or xr.get('declared_sha256'):
            assert (xr.get('sha256') or xr.get('declared_sha256')) == canonical_xr['sha256']
        report = load(rr['path'])
        manifest = load(xr['path'])
        life = report['lifecycle']['frame_summary']
        assert len(life) == report['frames'] == manifest['frames']
        assert report['particles'] == manifest['particles']
        assert [r['time'] for r in life] == manifest['actual_time_s']
        initial_fluid = sum(b['count'] for b in report['typed_identity']['blocks'] if b['type'] == 3)
        assert initial_fluid > 0
        assert life[0]['missing_particles'] == 0
        fluid_missing = []
        for i, frame in enumerate(life):
            assert frame['frame'] == i
            types = frame['missing_type_counts']
            nonfluid = sum(v for k, v in types.items() if str(k) != '3')
            assert nonfluid == 0, (physical, i, types)
            missing = types.get('3', 0)
            assert missing == frame['missing_particles']
            assert frame['active_particles'] + missing == report['particles']
            fluid_missing.append(missing)
        maximum, final, cumulative = max(fluid_missing), fluid_missing[-1], sum(fluid_missing)
        first = next((i for i, v in enumerate(fluid_missing) if v), None)
        if declared is not None:
            assert declared['final_missing_particles'] == final
            assert declared['max_missing_per_frame'] == maximum
            assert declared['cumulative_particle_frame_omissions'] == cumulative
            assert declared['first_missing_frame'] == first
        rows.append({
            'family_id': family, 'physical_case_id': physical,
            'producer_conversion_report': {'path': rr['path'], 'sha256': rr['sha256']},
            'actual_XMF_manifest': canonical_xr,
            'frames': len(life), 'initial_fluid_particles': initial_fluid,
            'first_missing_frame': first, 'final_missing_fluid': final,
            'maximum_missing_fluid_at_any_frame': maximum,
            'maximum_missing_fraction_initial_fluid': maximum / initial_fluid,
            'cumulative_particle_frame_omissions': cumulative,
            'all_fixed_moving_floating_particles_active_every_frame': True,
            'missing_fluid_locations_states_causes': 'unknown; no reconstruction or zero-loss claim' if maximum else 'no omissions in the actual producer lifecycle report',
            'case_credit': 0, 'Q_N': 0, 'Q_E': 0,
        })
summary = {}
for family in products:
    selected = [r for r in rows if r['family_id'] == family]
    maximum_row = max(selected, key=lambda r: r['maximum_missing_fraction_initial_fluid'])
    summary[family] = {
        'cases_checked': len(selected),
        'cases_with_fluid_omissions': sum(r['maximum_missing_fluid_at_any_frame'] > 0 for r in selected),
        'largest_relative_omission_case': maximum_row['physical_case_id'],
        'largest_missing_fluid_fraction': maximum_row['maximum_missing_fraction_initial_fluid'],
        'largest_missing_fluid_count_in_any_case': max(r['maximum_missing_fluid_at_any_frame'] for r in selected),
    }
O = H / 'root_stage1_F2_F6_actual96_full_lifecycle_omission_counts_relative_to_initial_fluid_unknown_causes_preserved_1453'
O.mkdir(exist_ok=False)
proof = {
    'schema': 'ds02.main.actual-lifecycle-omission-scale.v1',
    'at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'products': {f: ref(p) for f, p in products.items()},
    'direct_actual336_delivery': ref(delivery_path),
    'summary': summary, 'rows': rows,
    'purpose': 'Quantify the stage1 large-loss screen using every actual producer lifecycle frame and the generated fluid identity blocks. This does not identify causes, certify strict containment or numerical accuracy, or rewrite omitted states. Existing personal visual decisions remain the visual evidence.',
    'scientific_payload_IO': False, 'scientific_payload_hashing': False,
    'new_numerical_loss_threshold': None,
    'goal_completion_claim': False, 'case_credit': 0, 'Q_N': 0, 'Q_E': 0,
}
(O / 'actual96-full-lifecycle-relative-fluid-omission-proof.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n')
(O / 'audit-source.py').write_bytes(Path(__file__).read_bytes())
(O / 'README.md').write_text('F2/F6全部96例的实际生产者生命周期元数据复核：每个完整时间步的遗漏计数、初始fluid身份数、XMF真实时间和报告SHA逐项一致。遗漏的固定/运动/刚体粒子必须为零。流体遗漏原因与状态未知时完整保留，不设新的数值验收阈值，不读取科学载荷，不宣称零丢失、严格容器或精度通过。\n')
rel = [str(p.relative_to(R)) for p in O.iterdir()]
subprocess.run(['git', 'add', '--', *rel], cwd=R, check=True)
subprocess.run(['git', 'commit', '-q', '-m', 'DS02: quantify every F2 F6 fluid omission against actual initial fluid count', '--', *rel], cwd=R, check=True)
print(json.dumps({'output': str(O), 'summary': summary, 'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=R, text=True).strip()}))
