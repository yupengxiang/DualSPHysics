from pathlib import Path
import json, hashlib, datetime, os, subprocess

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
prev = H / 'ROOT_LIVE_RESUMPTION_CHECKPOINT_333.json'
cp = load(prev)
delivery = root(1451) / 'DS-DATA-02-ACTUAL-USER-DELIVERY-INDEX.json'
physical = root(1452) / 'actual96-native-pinned-physical-discriminators.json'
loss = root(1454) / 'all336-full-lifecycle-relative-fluid-omission-proof.json'
di, ph, lo = map(load, [delivery, physical, loss])
assert di['accepted_actual_primary_cases'] == 336 and len(di['cases']) == 336
assert all(len(f['membership']['registered_final48_physical_case_ids']) == 48 for f in di['families'].values())
assert len(ph['rows']) == 96 and all(f['distinct_actual_physical_parameter_groups'] == 48 for f in ph['families'].values())
assert len(lo['rows']) == 336 and all(f['cases_checked'] == 48 for f in lo['summary'].values())
ledger = Path('/home/jade/Projects/DualSPHysics-data/ds-data-02/runtime/resource-ledger.json')
assert sha(ledger) == cp['ledger_sha256_at_checkpoint']
assert load(ledger)['reservations'] == []
now = datetime.datetime.now(datetime.timezone.utc).isoformat()
cp.update(checkpoint=334, at_utc=now, predecessor=str(prev), predecessor_sha256=sha(prev))
cp['previous_goal_turn_classification'] = 'progress: all336 actual dynamic entry points directly verified; F2/F7 actual native input-pinned numeric physical distinctions proved; all336 actual lifecycle frames independently quantified'
cp['authorized_work_state'] = 'Active: all336 personal visual records, seven final48 actual primary products, direct XMF/animation/navigation entries, and full336 lifecycle evidence are available. Actual F2/F7 physical distinctions are proved through real launch/after pinned numeric values. Final independent numeric physical distinctions for the other five families remain pending. Numerical accuracy is unaccepted; do not declare the full goal complete yet.'
cp['goal_completion_audit_status'] = 'unproven: true physical discriminators F1/F3/F4/F5/F6 and final requirement-by-requirement integration remain pending; all336 dynamic file and lifecycle bindings have been directly verified'
cp['actual_progress']['all336_actual_direct_user_ParaView_delivery'] = ref(delivery)
cp['actual_progress']['F2_F7_actual96_native_pinned_numeric_physical_distinction'] = ref(physical)
cp['actual_progress']['all336_actual_full_lifecycle_fluid_omission_scale'] = ref(loss)
cp['actual_progress']['full_lifecycle_omission_summary'] = lo['summary']
cp['actual_progress']['small_fluid_omission_policy'] = 'Unknown omission locations, states and causes remain disclosed in every affected case. This audit neither invents replacement states nor grants numerical accuracy or a new numerical loss threshold.'
cp['next_executable_tasks'] = [
    'Integrate committed fresh232 actual native/source-bound numeric physical discriminators for F1 and F6, including real legacy mother and rigid-baseline values; do not infer uniqueness from IDs, paths, missing values or resolution.',
    'Integrate committed fresh207 actual forcing/motion/source-bound numeric physical discriminators for F3/F4/F5, including true AY025/075 endpoint bindings and thin legacy piston sources.',
    'Have fresh194 combine those 240 cases with main Root1452 F2/F7 numeric96 evidence; verify all336 actual physical distinctions and explicit 8-subset24-subset48 membership, then complete the final stage1 requirement audit with Root1451 dynamic and Root1454 lifecycle evidence before marking the goal complete.',
]
cp['source_agents'] = {
    'production_recovery': 'fresh194 full336 physical role/membership audit, final actual numeric discrimination integration pending',
    'f5_bed_recovery': 'fresh231 explicit requirements snapshot completed; fresh232 F1/F6 actual physical discriminators pending',
    'f6_endpoint_initial_qa': 'fresh207 F3/F4/F5 actual physical discriminators pending',
}
v = os.statvfs('/home/jade')
cp['home_free_gib'] = v.f_bavail * v.f_frsize / 2**30
assert cp['home_free_gib'] >= 500
O = H / 'root_stage1_actual336_direct_delivery_and_full_lifecycle_F2F7_numeric96_distinction_five_families_final_parameter_audit_pending_1455'
O.mkdir(exist_ok=False)
proof = {'schema': 'ds02.main.current336-delivery-progress.v1', 'at_utc': now,
         'predecessor_checkpoint': ref(prev), 'direct_dynamic_delivery': ref(delivery),
         'actual_numeric_physical96': ref(physical), 'actual_full_lifecycle336': ref(loss),
         'physical_discrimination_remaining_families': ['F1', 'F3', 'F4', 'F5', 'F6'],
         'resource_ledger': ref(ledger), 'reservations': [], 'home_available_GiB': cp['home_free_gib'],
         'goal_complete_claim': False, 'case_credit': 0, 'Q_N': 0, 'Q_E': 0,
         'scientific_payload_IO': False}
(O / 'current336-delivery-and-final-physical-audit-progress.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n')
(O / 'audit-source.py').write_bytes(Path(__file__).read_bytes())
outfile = H / 'ROOT_LIVE_RESUMPTION_CHECKPOINT_334.json'
with outfile.open('x') as f:
    json.dump(cp, f, ensure_ascii=False, indent=2)
    f.write('\n')
rel = [str(p.relative_to(R)) for p in O.iterdir()] + [str(outfile.relative_to(R))]
subprocess.run(['git', 'add', '--', *rel], cwd=R, check=True)
subprocess.run(['git', 'commit', '-q', '-m', 'DS02: checkpoint334 actual336 files lifecycle and numeric96 distinction with remaining true parameter audit', '--', *rel], cwd=R, check=True)
print(json.dumps({'checkpoint': str(outfile), 'home_free_GiB': cp['home_free_gib'], 'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=R, text=True).strip()}))
