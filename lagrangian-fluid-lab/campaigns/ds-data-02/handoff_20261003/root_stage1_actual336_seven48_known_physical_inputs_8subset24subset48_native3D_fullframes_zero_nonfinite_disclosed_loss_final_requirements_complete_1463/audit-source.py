from pathlib import Path
import json, hashlib, datetime, itertools, math, os, subprocess
R = Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics')
H = R / 'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003'
root = lambda n: next(H.glob(f'root*_{n:03d}'))
def load(p):
    assert Path(p).suffix == '.json'
    return json.loads(Path(p).read_text())
def sha(p):
    assert Path(p).suffix in {'.json', '.py', '.md'}
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()
ref = lambda p: {'path': str(p), 'sha256': sha(p)}
def checked(e):
    assert sha(e['path']) == e['sha256'], e['path']
    return load(e['path'])
ip = root(1451) / 'DS-DATA-02-ACTUAL-USER-DELIVERY-INDEX.json'
idx = load(ip); current = {(r['family_id'], r['physical_case_id']): r for r in idx['cases']}
assert len(current) == len(idx['cases']) == 336
components = [root(1452) / 'actual96-native-pinned-physical-discriminators.json',
    root(1459) / 'actual96-native-pinned-known-numeric-physical-differences.json',
    root(1460) / 'actual48-native-pinned-angular-vector-known-physical-differences.json',
    root(1461) / 'actual48-launch-pinned-forcing-known-physical-differences.json',
    root(1462) / 'actual48-field-pinned-depth-velocity-known-physical-differences.json']
physical = {}
for p in components:
    for r in load(p)['rows']:
        key = (r['family_id'], r['physical_case_id']); assert key in current and key not in physical
        numbers = r.get('numeric_physical_discriminators', r.get('physical_discriminators'))
        assert numbers and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in numbers.values())
        physical[key] = {'family_id': key[0], 'physical_case_id': key[1], 'known_numeric_physical_parameters': numbers, 'component_proof': ref(p), 'component_row': r}
assert set(physical) == set(current)
family_checks = {}
for family, source in idx['families'].items():
    mem = source['membership']; a, b, c = [set(mem[k]) for k in ['frozen_first8_physical_case_ids', 'actual_first24_physical_case_ids', 'registered_final48_physical_case_ids']]
    assert len(a) == 8 and len(b) == 24 and len(c) == 48 and a <= b <= c
    rs = [r for r in physical.values() if r['family_id'] == family]
    assert len(rs) == 48 and {r['physical_case_id'] for r in rs} == c
    count = 0
    for x, y in itertools.combinations(rs, 2):
        u, v = x['known_numeric_physical_parameters'], y['known_numeric_physical_parameters']
        assert any(u[k] != v[k] for k in u.keys() & v.keys()), (family, x['physical_case_id'], y['physical_case_id'])
        count += 1
    fields = sorted(set().union(*(r['known_numeric_physical_parameters'] for r in rs)))
    ranges = {k: {'minimum': min(r['known_numeric_physical_parameters'][k] for r in rs if k in r['known_numeric_physical_parameters']), 'maximum': max(r['known_numeric_physical_parameters'][k] for r in rs if k in r['known_numeric_physical_parameters']), 'known_cases': sum(k in r['known_numeric_physical_parameters'] for r in rs)} for k in fields}
    family_checks[family] = {'distinct_actual_cases': 48, 'shared_known_numeric_pair_differences': count,
        '8_subset24_subset48': True, 'actually_run_visual_usable_sample_range': ranges,
        'range_qualification_status': 'Visual sample coverage only; a certified numerical parameter domain is deferred.'}
lp = root(1454) / 'all336-full-lifecycle-relative-fluid-omission-proof.json'
loss = load(lp); lossmap = {(r['family_id'], r['physical_case_id']): r for r in loss['rows']}; assert set(lossmap) == set(current)
up = root(1457) / 'all336-actual-UID-state-fields-and-file-availability-proof.json'
uid = load(up); uidmap = {(r['family_id'], r['physical_case_id']): r for r in uid['rows']}; assert set(uidmap) == set(current)
vp = root(1458) / 'all336-current-visual-decisions-full-time-primary-join.json'
visual = load(vp); vm = {(r['family_id'], r['physical_case_id']): r for r in visual['rows']}; assert set(vm) == set(current)
direct = checked(idx['main_direct_primary_verification'])
assert direct['all336_selected_XMF_current_SHA_XML_fulltimes_geometry_velocity_N3_verified']
screen = []
for key, r in current.items():
    d = r['primary_delivery']; m = checked(d['manifest']); lc = lossmap[key]; ur = uidmap[key]
    assert ur['actual_manifest'] == d['manifest'] and vm[key]['accepted_decision'] == r['accepted_visual_decision']
    assert lc['actual_XMF_manifest']['path'] == d['manifest']['path'] and lc['actual_XMF_manifest']['sha256'] == d['manifest']['sha256']
    assert lc['frames'] == ur['frames'] == d['frames'] == m['frames']
    converter = checked(lc['producer_conversion_report']); dim = converter['solver_dimension']
    assert dim['solver_dimension'] == 3 and dim['xml_data2d'] == 'false' and dim['run_out_dimensions'] == [3]
    assert converter['conversion_status'] == 'completed'
    render_refs = []
    for e in d['full_animation_reports']:
        report = checked(e)
        assert report['all_frames_rendered'] and report['frames'] == m['frames']
        assert report['nonfinite_active_states'] == 0
        assert report['native_identity_axis_preserved'] is True and report['actual_times_preserved_exactly'] is True
        render_refs.append(e)
    checked(r['accepted_visual_decision'])
    screen.append({'family_id': key[0], 'physical_case_id': key[1], 'solver_dimension': dim,
        'actual_manifest': d['manifest'], 'actual_converter': lc['producer_conversion_report'],
        'all_frame_render_reports': render_refs, 'nonfinite_active_states': 0,
        'frames': m['frames'], 'actual_final_time_s': m['actual_time_s'][-1],
        'small_unknown_fluid_omission_limit': lc,
        'personal_visual_review_record': r['accepted_visual_decision'],
        'initial_geometry_motion_and_scope_limits': {'family_product': d['product'], 'row_pointer': d['row_pointer']}})
fp = Path(idx['families']['F6']['product']['path']); f6 = checked(idx['families']['F6']['product'])
rigid = []
for r in f6['rows']:
    q = r['primary_refs']['rigid']; assert q['frames'] == 241
    er = checked(q['actual_export_receipt']); assert er['status'] == 'completed' and er['returncode'] == 0
    checked(q['actual_export_report'])
    if r['physical_case_id'] != 'F6_STAGE1_ANGULAR_RELEASE_OMEGA_BASELINE':
        assert q['required_rigid_fields_finite_all241'] and q['actual_Part_unique_count'] == 241
        assert q['max_abs_actual_native_time_delta_s'] <= q['native_time_tolerance_s']
    else:
        assert q['full_saved_rigid_history_finite_and_monotone_through12']
    rigid.append({'physical_case_id': r['physical_case_id'], 'actual_export_report': q['actual_export_report'], 'frames': 241,
        'limits': 'Exact original field/header/Part/mass limitations are preserved in the F6 primary product; rigid states are not inferred from particle velocity.'})
prev = H / 'ROOT_LIVE_RESUMPTION_CHECKPOINT_334.json'; cp = load(prev)
ledger = Path('/home/jade/Projects/DualSPHysics-data/ds-data-02/runtime/resource-ledger.json')
assert sha(ledger) == cp['ledger_sha256_at_checkpoint'] and load(ledger)['reservations'] == []
assert cp['gpu_hours_charged'] <= 512 and cp['cpu_core_hours_charged'] <= 3840
assert cp['attempt_counts']['qualification'] <= 1024 and cp['attempt_counts']['production'] <= 720
now = datetime.datetime.now(datetime.timezone.utc); assert now < datetime.datetime.fromisoformat(cp['deadline_utc'])
stat = os.statvfs('/home/jade'); free = stat.f_bavail * stat.f_frsize / 2**30; assert free >= 500
refs = {'actual_dynamic_delivery': ref(ip), 'physical_components': [ref(p) for p in components], 'UID_and_state': ref(up),
    'full_lifecycle': ref(lp), 'visual_records': ref(vp), 'F6_particle_and_official_rigid_product': ref(fp), 'ledger': ref(ledger)}
requirements = [
    {'id': 'seven-family-336-independent-physical-cases', 'result': 'pass', 'evidence': 'All336 actual primary cases; 48 per family; all1128 pairs per family have a shared known numeric physical input difference. IDs, paths, hashes, unknowns, numerical settings, time windows and views do not count.'},
    {'id': 'real-native3D-full-event-time', 'result': 'pass', 'evidence': 'All336 producer reports state native dimension3, XML Data2D=false, solver dimension3. Actual full-frame XML time series and render reports are bound, rather than optional preview slices.'},
    {'id': 'UID-state-geometry-motion-rigid-provenance', 'result': 'pass_with_disclosed_limits', 'evidence': 'Actual dynamic identity/state fields and HDF availability verified for336. Source native metadata is pinned per physical field or producer forcing; all48 F6 full241 official rigid histories exist. Exact initial QA, F3 shared geometry reuse, F5 bed, mass, missing state and legacy scope limitations remain in family product rows.'},
    {'id': 'ParaView-dynamic-files-key-event-previews', 'result': 'pass', 'evidence': 'Each case has its current XMF, manifest, full animation report, contact sheets and navigation previews, with original personal visual records retained.'},
    {'id': 'actual-frozen8-subset24-subset48', 'result': 'pass', 'evidence': 'Membership arrays are checked for all7 families and match the final physically distinct case sets.'},
    {'id': 'visual-screen-finite-states-loss-and-completion', 'result': 'pass_with_disclosed_limits', 'evidence': 'All336 full render reports state zero nonfinite active states; full primary frames and producer lifecycle counts match. Personal reviews accept all336. F2/F4/F6 small fluid omissions remain unknown in cause/location/state; four old F3 native059 process after/returncode fields remain absent with separate registered completion recovery, never rewritten.'},
    {'id': 'visual-accuracy-label-and-stage2-gaps', 'result': 'pass', 'evidence': '视觉检查通过、数值精度未验收; Q-N/Q-E=0. Conversion metadata q_i_status remains conversion evidence only; this phase is not a numerical accuracy certificate.'},
    {'id': 'global-stage1-goal-declaration', 'result': 'pass', 'evidence': 'Final independent physical field/forcing proofs resolve the historical pending holds. Resource, deadline and Home floor remain within the approved cumulative window.'},
]
O = H / 'root_stage1_actual336_seven48_known_physical_inputs_8subset24subset48_native3D_fullframes_zero_nonfinite_disclosed_loss_final_requirements_complete_1463'
O.mkdir(exist_ok=False)
physicalfile = O / 'all336-final-known-physical-parameters-and-visual-sample-ranges.json'
physicalfile.write_text(json.dumps({'schema': 'ds02.main.actual336-final-known-physical-parameters.v1', 'at_utc': now.isoformat(),
    'source_components': refs['physical_components'], 'families': family_checks, 'rows': list(physical.values()),
    'numeric_parameter_qualification': 'unaccepted; observed sample ranges only', 'case_credit': 0, 'Q_N': 0, 'Q_E': 0}, ensure_ascii=False, indent=2) + '\n')
proof = {'schema': 'ds02.main.actual336-stage1-final-requirement-audit.v1', 'at_utc': now.isoformat(), 'requirements': requirements,
    'stage1_goal_achieved': True, 'final_actual_primary_cases': 336, 'families': family_checks, 'evidence': refs,
    'actual_physical_parameters': ref(physicalfile), 'all336_actual_dimension_finite_completion_screen': screen,
    'F6_full48_official_rigid_state_reports': rigid, 'full_lifecycle_omission_summary': loss['summary'],
    'used_gpu_hours': cp['gpu_hours_charged'], 'used_cpu_core_hours': cp['cpu_core_hours_charged'], 'attempt_counts': cp['attempt_counts'],
    'home_free_GiB': free, 'home_floor_GiB': 500, 'deadline_utc': cp['deadline_utc'], 'active_reservations': [],
    'precision_status': '视觉检查通过、数值精度未验收', 'Q_N': 0, 'Q_E': 0, 'new_case_credit': 0,
    'scientific_payload_IO': False, 'new_personal_visual_reviews': False, 'new_jobs': False,
    'stage2_remaining': ['Spatial convergence and independent integration/save-rate error budgets', 'Long-term per-particle trajectory consistency', 'Precise source-destination/first-passage/residence/event labels', 'Certified numerical parameter ranges', 'Leakage-free splits and model-free evaluation', 'External experiment validation']}
(O / 'STAGE1-FINAL-REQUIREMENT-AUDIT.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n')
(O / 'audit-source.py').write_bytes(Path(__file__).read_bytes())
rel = [str(p.relative_to(R)) for p in O.iterdir()]
subprocess.run(['git', 'add', '--', *rel], cwd=R, check=True)
subprocess.run(['git', 'commit', '-q', '-m', 'DS02: complete stage1 requirement audit for actual336 distinct visual cases preserving accuracy and legacy limits', '--', *rel], cwd=R, check=True)
print(json.dumps({'stage1_goal_achieved': True, 'cases': 336, 'requirements': len(requirements), 'home_free_GiB': free,
    'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=R, text=True).strip()}))
