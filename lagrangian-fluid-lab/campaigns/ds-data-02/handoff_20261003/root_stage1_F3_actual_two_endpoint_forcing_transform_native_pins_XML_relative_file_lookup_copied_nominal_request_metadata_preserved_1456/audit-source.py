from pathlib import Path
import json, hashlib, datetime, subprocess, xml.etree.ElementTree as ET
R = Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics')
H = R / 'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003'
D = Path('/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3')
S = Path('/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/src/source')

def sha(p):
    p = Path(p)
    assert p.suffix in {'.json', '.xml', '.cpp', '.py', '.md'}
    return hashlib.sha256(p.read_bytes()).hexdigest()

def ref(p):
    return {'path': str(p), 'sha256': sha(p)}

def load(p):
    assert Path(p).suffix == '.json'
    return json.loads(Path(p).read_text())

# Inspect the official case-relative lookup, not the scientific table itself.
jsph = (S / 'JSph.cpp').read_text()
acc = (S / 'JDsAccInput.cpp').read_text()
assert 'DirCase=fun::GetDirWithSlash(fun::GetDirParent(CaseName))' in jsph
assert 'AccInput=new JDsAccInput(DirCase,&xml,"case.execution.special.accinputs")' in jsph
assert 'DirData(dirdata)' in acc
assert 'acedata.LoadFile(DirData+sxml->ReadElementStr(ele,"acctimesfile","value"))' in acc
rows = []
for role, suffix in [('lower', '0250'), ('upper', '0750')]:
    nr = D / f'F3_STAGE1_DP006_P1000_AY{suffix}' / f'root-stage1-twoaxis-{role}-physical-endpoint-full836-native-009/execution-receipt.json'
    n = load(nr)
    assert n['status'] == 'completed' and n['returncode'] == 0
    req = n['request']
    prefix = Path(req['gencase_prefix'])
    assert str(prefix) in n['command']
    xml = prefix.with_suffix('.xml')
    xp = sha(xml)
    assert n['input_hashes_at_launch'][str(xml)] == xp == n['input_hashes_after_run'][str(xml)]
    external = ET.parse(xml).findall('.//acctimesfile')
    assert len(external) == 1
    forcing_path = prefix.parent / external[0].get('value')
    mp = prefix.parent / 'prepared-input-report.json'
    mh = sha(mp)
    assert n['input_hashes_at_launch'][str(mp)] == mh == n['input_hashes_after_run'][str(mp)]
    m = load(mp)
    t = m['forcing_transform']
    assert m['case_id'] == req['case_id'] and m['physical_case_id'] == req['physical_case_id']
    assert str(forcing_path) == t['output_file'] == m['forcing_path']
    assert t['status'] == 'success' and t['amplitude_y'] == m['transverse_amplitude_m_s2']
    assert t['amplitude_x'] == 1.0
    assert t['output_sha256'] == m['forcing_sha256']
    # Producer declarations establish the native input join; do not open CSV.
    assert n['input_hashes_at_launch'][str(forcing_path)] == t['output_sha256'] == n['input_hashes_after_run'][str(forcing_path)]
    assert req['physical_condition_sha256'] == m['physical_condition_sha256']
    assert abs(t['column_min'][1] + t['amplitude_y']) < 1e-8
    assert abs(t['column_max'][1] - t['amplitude_y']) < 1e-8
    rows.append({
        'physical_case_id': req['physical_case_id'], 'actual_native_receipt': ref(nr),
        'actual_native_command': n['command'], 'actual_generated_XML': ref(xml),
        'actual_launch_after_pinned_forcing_transform_report': ref(mp),
        'physical_discriminators': {'nominal_pitch_multiplier': t['amplitude_x'], 'transverse_amplitude_m_s2': t['amplitude_y']},
        'source_field_pointers': {'nominal_pitch_multiplier': '/forcing_transform/amplitude_x', 'transverse_amplitude_m_s2': '/forcing_transform/amplitude_y'},
        'actual_forcing_path_resolved_by_XML_and_solver_case_directory': str(forcing_path),
        'actual_forcing_SHA_producer_attested_and_native_launch_after_equal': t['output_sha256'],
        'scientific_forcing_table_read_or_hashed_by_main': False,
        'producer_report_transverse_column_range': [t['column_min'][1], t['column_max'][1]],
        'copied_request_physical_binding_parameters': req['physical_binding']['parameters'],
        'copied_request_binding_is_nominal_and_inconsistent_with_actual_forcing': True,
        'original_copied_binding_bytes_preserved_not_rewritten': True,
        'same_XML_and_initial_BI4_are_geometry_reuse_not_same_external_forcing': True,
        'case_credit': 0, 'Q_N': 0, 'Q_E': 0,
    })
assert len({r['physical_discriminators']['transverse_amplitude_m_s2'] for r in rows}) == 2
O = H / 'root_stage1_F3_actual_two_endpoint_forcing_transform_native_pins_XML_relative_file_lookup_copied_nominal_request_metadata_preserved_1456'
O.mkdir(exist_ok=False)
p = {'schema': 'ds02.main.actual-endpoint-external-forcing-proof.v1', 'at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
     'official_solver_source': {'JSph_case_directory': ref(S / 'JSph.cpp'), 'JDsAccInput_relative_file_lookup': ref(S / 'JDsAccInput.cpp')},
     'rows': rows, 'scientific_payload_IO': False, 'goal_completion_claim': False,
     'scope': 'Actual native command, launch/after pinned XML and numeric transform report, and declaration-only forcing output/native input SHA join prove different .25/.75 forcing. The copied nominal request binding is retained as a metadata inconsistency, not treated as the actual external forcing value.',
     'case_credit': 0, 'Q_N': 0, 'Q_E': 0}
(O / 'actual-two-F3-endpoint-forcing-and-stale-request-binding-proof.json').write_text(json.dumps(p, ensure_ascii=False, indent=2) + '\n')
(O / 'audit-source.py').write_bytes(Path(__file__).read_bytes())
rel = [str(p.relative_to(R)) for p in O.iterdir()]
subprocess.run(['git', 'add', '--', *rel], cwd=R, check=True)
subprocess.run(['git', 'commit', '-q', '-m', 'DS02: prove actual F3 endpoint forcing input joins and preserve copied nominal binding inconsistency', '--', *rel], cwd=R, check=True)
print(json.dumps({'output': str(O), 'physical_discriminators': [r['physical_discriminators'] for r in rows], 'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=R, text=True).strip()}))
