from pathlib import Path
import json, hashlib, datetime, xml.etree.ElementTree as ET, subprocess

R = Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics')
H = R / 'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003'
D = Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
root = lambda n: next(H.glob(f'root*_{n:03d}'))
def load(p):
    assert Path(p).suffix == '.json'
    return json.loads(Path(p).read_text())
def sha(p):
    assert Path(p).suffix in {'.json', '.xmf', '.py', '.md'}
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def checked(e):
    assert sha(e['path']) == e['sha256'], e['path']
    return load(e['path'])
ref = lambda p: {'path': str(p), 'sha256': sha(p)}
ip = root(1451) / 'DS-DATA-02-ACTUAL-USER-DELIVERY-INDEX.json'
idx = load(ip)
lossfile = root(1454) / 'all336-full-lifecycle-relative-fluid-omission-proof.json'
loss = load(lossfile)
lm = {(r['family_id'], r['physical_case_id']): r for r in loss['rows']}
required = ['valid', 'particle_id', 'particle_zone', 'initial_type', 'initial_mk', 'initial_mass', 'mass', 'velocity', 'density', 'pressure', 'type']
rows = []
for row in idx['cases']:
    d = row['primary_delivery']; m = checked(d['manifest'])
    xr = d['open_with_ParaView_XMF']; assert sha(xr['path']) == xr['sha256']
    grids = ET.parse(xr['path']).findall('.//Grid[@GridType="Uniform"]')
    nt, np = m['frames'], m['particles']; assert len(grids) == nt
    expected = {'time': [nt], 'position': [nt, np, 3]}
    for name in required:
        expected[name] = [np] if name.startswith('initial_') or name in {'particle_id', 'particle_zone'} else [nt, np, 3] if name == 'velocity' else [nt, np]
    for name, shape in expected.items():
        assert m['fields'][name]['shape'] == shape, (row['physical_case_id'], name)
    paths = set()
    for g in grids:
        assert int(g.find('Topology').get('NumberOfElements')) == np
        attrs = {a.get('Name'): a for a in g.findall('Attribute')}
        assert set(required) <= set(attrs)
        for name in required:
            a = attrs[name]; item = a.find('DataItem')
            assert a.get('Center') == 'Node'
            assert [int(x) for x in item.get('Dimensions').split()] == ([np, 3] if name == 'velocity' else [np])
        for item in g.findall('.//DataItem[@Format="HDF"]'):
            raw = item.text.strip(); path, dataset = raw.rsplit(':', 1)
            p = Path(path)
            if not p.is_absolute(): p = Path(xr['path']).parent / p
            p = p.resolve(); assert p.is_relative_to(D) and p.suffix == '.h5' and dataset.startswith('/')
            paths.add(str(p))
    assert len(paths) == 1
    path = Path(next(iter(paths))); stat = path.stat(); assert path.is_file() and stat.st_size > 0
    omission = lm[(row['family_id'], row['physical_case_id'])]
    declared_paths = {Path(m[k]).resolve() for k in ['trajectory_h5', 'typed_output_h5', 'source_h5'] if k in m}
    if not declared_paths:
        producer = checked(omission['producer_conversion_report'])
        declared_paths = {Path(producer['output_hdf5']).resolve()}
    assert declared_paths == {path}, (row['physical_case_id'], declared_paths)
    assert omission['actual_XMF_manifest']['path'] == d['manifest']['path']
    assert omission['actual_XMF_manifest']['sha256'] == d['manifest']['sha256']
    assert omission['frames'] == nt and omission['all_fixed_moving_floating_particles_active_every_frame']
    rows.append({'family_id': row['family_id'], 'physical_case_id': row['physical_case_id'],
        'actual_XMF': xr, 'actual_manifest': d['manifest'], 'frames': nt, 'particles': np,
        'identity_state_fields': required, 'actual_HDF_reference_stat_only': {'path': str(path), 'bytes': stat.st_size},
        'producer_lifecycle_report': omission['producer_conversion_report'],
        'maximum_missing_fluid': omission['maximum_missing_fluid_at_any_frame'],
        'omission_locations_states_causes': omission['missing_fluid_locations_states_causes'],
        'limits': 'UID and state fields are available in the actual dynamic files; long-term trajectory accuracy is unaccepted. Missing states are masked, never invented.'})
assert len(rows) == 336 and all(sum(r['family_id'] == f for r in rows) == 48 for f in idx['families'])
O = H / 'root_stage1_all336_actual_UID_state_native_types_geometry_HDF_reference_stat_only_full_lifecycle_unknowns_preserved_1457'
O.mkdir(exist_ok=False)
proof = {'schema': 'ds02.main.actual336-uid-state-availability.v1', 'at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'delivery_index': ref(ip), 'lifecycle_proof': ref(lossfile), 'cases_checked': 336, 'rows': rows,
    'all_actual_dynamic_frames_identity_state_shape_and_HDF_file_availability_verified': True,
    'HDF_read_or_hashed': False, 'other_scientific_payload_IO': False, 'new_jobs': False,
    'case_credit': 0, 'Q_N': 0, 'Q_E': 0, 'goal_complete_claim': False}
(O / 'all336-actual-UID-state-fields-and-file-availability-proof.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n')
(O / 'audit-source.py').write_bytes(Path(__file__).read_bytes())
(O / 'README.md').write_text('全336例实际XMF每帧均含粒子ID、初始类型/标记/质量、动态valid/type/mass/velocity/density/pressure，维度与实际manifest一致，所指H5文件存在且非空（只stat，不读取或哈希）。完整生命周期的缺失掩码和未知原因继续引用Root1454；不制造缺失状态、不认证长期轨迹数值精度。\n')
rel = [str(p.relative_to(R)) for p in O.iterdir()]
subprocess.run(['git', 'add', '--', *rel], cwd=R, check=True)
subprocess.run(['git', 'commit', '-q', '-m', 'DS02: verify actual336 UID state fields and primary HDF availability without science IO', '--', *rel], cwd=R, check=True)
print(json.dumps({'cases_checked': 336, 'proof': str(O), 'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=R, text=True).strip()}))
