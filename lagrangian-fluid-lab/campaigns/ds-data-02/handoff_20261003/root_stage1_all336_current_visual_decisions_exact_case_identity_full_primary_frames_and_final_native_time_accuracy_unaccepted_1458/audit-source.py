from pathlib import Path
import json, hashlib, datetime, subprocess
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
ip = root(1451) / 'DS-DATA-02-ACTUAL-USER-DELIVERY-INDEX.json'
idx = load(ip); rows = []; counts = {}
for r in idx['cases']:
    dr = r['accepted_visual_decision']; assert sha(dr['path']) == dr['sha256']
    d = load(dr['path']); delivery = r['primary_delivery']
    assert d['family_id'] == r['family_id'] and d['physical_case_id'] == r['physical_case_id']
    assert d['status'] in {'visual-approved-by-root', 'visual-approved-by-delegated-agent'}
    frames = d.get('frames', d.get('actual_frames', d.get('full_native_frames')))
    assert frames is None or frames == delivery['frames'], (r['physical_case_id'], frames, delivery['frames'])
    last = d.get('actual_last_time_s', d.get('actual_final_time_s')); expected = delivery['actual_time_window_s'][-1]
    recorded_time_delta = None if last is None else last - expected
    mr = delivery['manifest']; assert sha(mr['path']) == mr['sha256']
    manifest = load(mr['path'])
    window = manifest.get('physical_window_s')
    if isinstance(window, list): assert expected >= window[-1]
    for k in ['q_n', 'q_e', 'Q_N', 'Q_E']:
        assert k not in d or d[k] in {False, 0, 'not_granted', 'not_assessed'}
    assert r['precision_status'] == '视觉检查通过、数值精度未验收'
    counts[d['status']] = counts.get(d['status'], 0) + 1
    rows.append({'family_id': r['family_id'], 'physical_case_id': r['physical_case_id'],
        'accepted_decision': dr, 'recorded_visual_status': d['status'], 'actual_primary_frames': delivery['frames'],
        'decision_recorded_frames': frames, 'decision_recorded_final_time_s': last,
        'decision_frame_time_field_absence_preserved': frames is None or last is None,
        'decision_recorded_final_time_minus_actual_primary_s': recorded_time_delta,
        'actual_time_authority': delivery['manifest'],
        'time_metadata_policy': 'Original rounded/copied final-time declarations are preserved. The directly verified case-bound XMF manifest supplies actual times; this is not a time precision certificate.',
        'actual_last_time_s': expected, 'raw_decision_limits_remain_in_original_record': True,
        'reviewer': d.get('visual_reviewer', 'historical root review'),
        'new_personal_visual_review': False, 'Q_N': 0, 'Q_E': 0})
assert len(rows) == 336
O = H / 'root_stage1_all336_current_visual_decisions_exact_case_identity_full_primary_frames_and_final_native_time_accuracy_unaccepted_1458'
O.mkdir(exist_ok=False)
proof = {'schema': 'ds02.main.actual336-visual-decision-time-join.v1', 'at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'delivery_index': ref(ip), 'rows': rows, 'current_accepted_visual_records': 336, 'status_counts': counts,
    'source_personal_reviews_inherited': True, 'new_personal_reviews': False,
    'scientific_payload_IO': False, 'PNG_IO_or_hash': False, 'case_credit': 0, 'Q_N': 0, 'Q_E': 0,
    'goal_complete_claim': False}
(O / 'all336-current-visual-decisions-full-time-primary-join.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n')
(O / 'audit-source.py').write_bytes(Path(__file__).read_bytes())
rel = [str(p.relative_to(R)) for p in O.iterdir()]
subprocess.run(['git', 'add', '--', *rel], cwd=R, check=True)
subprocess.run(['git', 'commit', '-q', '-m', 'DS02: bind current336 visual decisions to exact full-time actual primary products', '--', *rel], cwd=R, check=True)
print(json.dumps({'current_visual_records': 336, 'status_counts': counts, 'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=R, text=True).strip()}))
