"""Record only current control metadata; never inspect scientific payloads."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess

S = Path(__file__).resolve().parents[2]
D = Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')


def load(path):
    assert path.stat().st_size <= 10485760
    return json.loads(path.read_text())


def ref(path):
    assert path.stat().st_size <= 10485760
    return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                bytes=path.stat().st_size)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--actual', type=int, required=True)
    parser.add_argument('--pending', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    plan_path = S / f'checkpoints/CURRENT336_TYPED_LIFECYCLE_AFTER_ROOT{args.actual}_V4.json'
    pending_path = S / f'checkpoints/CURRENT336_TYPED_LIFECYCLE_ROOT{args.pending}_PENDING_V4.json'
    plan, pending = load(plan_path), load(pending_path)
    assert plan['schema'] == pending['schema'] == 'ds02.stage2.typed-lifecycle-continuation-plan.v4'
    assert plan['coverage']['actual_saved_mask_cases'] == pending['coverage']['actual_saved_mask_cases']
    specs = [
        ('lifecycle', 3122380, 'root-owned-lifecycle-continuation-v1/recover301_then_resume_v1.py'),
        ('native', 3018600, 'root-owned-native-admission-v1/continue_after_serial_v1.py'),
        ('mass313', 3056671, 'root-owned-native-admission-v1/continue_mass_after_native_v2.py'),
        ('geometry-portable', 3084432, 'root-owned-portable-admission-v1/continue_after_mass_v2.py'),
        ('F6-support276', 3088756, 'root-owned-reference-admission-v1/continue_after_portable_v1.py'),
        ('frame0314', 3104941, 'root-owned-reference-admission-v1/continue_frame0_after_support_v1.py'),
        ('mass30', 3109511, 'root-owned-native-admission-v1/continue_mass30_after_frame0_v1.py'),
        ('missing-native-joins', 3169644, 'root-owned-missing-native-joins-v1/continue_after_mass30_v1.py'),
    ]
    processes = []
    for name, pid, relative in specs:
        code = S / 'governance' / relative
        proc = Path(f'/proc/{pid}')
        argv = proc.joinpath('cmdline').read_bytes().decode().split('\0')
        cwd = proc.joinpath('cwd').resolve(strict=True)
        assert any((cwd / item).resolve() == code for item in argv if item.endswith('.py'))
        processes.append(dict(name=name, pid=pid, process_present=True, source=ref(code),
                              dependent_parent_started=name == 'lifecycle'))
    unit = f'ds02-typed-lifecycle-batch-v1-f7-root-{args.pending}'
    text = subprocess.check_output(['systemctl', '--user', 'show', unit,
        '--property=ActiveState,SubState,MainPID,CPUUsageNSec,MemoryCurrent,Result,ControlGroup'], text=True)
    unit_state = dict(line.split('=', 1) for line in text.splitlines() if '=' in line)
    assert unit_state['ActiveState'] == 'active' and unit_state['ControlGroup']
    ledger = load(D / 'runtime/resource-ledger.json')
    disk = os.statvfs('/home/jade')
    native_path = S / 'checkpoints/ORIGINAL118_NATIVE_CAUSE_AFTER_ROOT268_ACTUAL_OVERLAY_V10.json'
    native = load(native_path)
    output = dict(schema='ds02.stage2.root-live-full-goal-task-graph.v1',
        utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        goal_status='ACTIVE_FULL_SEVEN_ITEMS', goal_complete=False,
        snapshot_source=ref(Path(__file__).resolve()), actual_plan=ref(plan_path),
        pending_plan=ref(pending_path), actual_coverage=plan['coverage'],
        pending_coverage=pending['coverage'], current_unit=dict(name=unit, **unit_state),
        live_processes=processes,
        serial_order=['307 lifecycle', '274 F6 native', '308 F4 native', '309 F6 native',
            '310 F1 snapshot', '313 mass17', '316 geometry', '242 portable', '276 F6 support',
            '314 frame0', '322-326 mass30', '312 unknown7 native', '315/317-321 missing46 joins'],
        actual_native_scope=dict(source=ref(native_path), historical=native['physical_case_count'],
            cause_bound=native['native_cause_bound_per_fluid_id_cases'],
            unknown=native['cause_not_located_after_completed_scan_cases'],
            typed_native_joins=native['actual_typed_native_saved_frame_join_physical_cases'],
            historical_alias_excluded_from_canonical_credit=True),
        resources=dict(CPU_core_hours=sum(c.get('cpu_core_seconds', 0) for c in ledger['charges']) / 3600,
            GPU_hours=sum(c.get('gpu_seconds', 0) for c in ledger['charges']) / 3600,
            reservation_count=len(ledger['reservations']), limits=ledger['limits'],
            deadline_utc=ledger['deadline_utc'], Home_free_bytes=disk.f_bavail * disk.f_frsize),
        source_branches=dict(raw_H5_audit='V1 diagnostic integrated; additive V2 repair pending; no pilot',
            owner_grid='F3 staged source preserved; actual staged worker and output rebind pending; no GenCase',
            consumer_roles='eventV6 and F6producerV2 exact real plan/registry ABI pending',
            ROOT279='tiny genuine native observer verified; actual310snapshot/runtime closure pending',
            fourteen_sentinels='source dimension catalog; numerical qualification UNKNOWN'),
        scientific_Q_credit=0, root_production_payload_content_read=False,
        next='Verify actual307 terminal independently, continue frozen native chain, integrate additive sources')
    with args.output.open('x') as stream:
        json.dump(output, stream, indent=2, sort_keys=True)
        stream.write('\n')
    print(json.dumps(dict(checkpoint=ref(args.output.resolve()), resources=output['resources'],
                          unit=unit_state)))


if __name__ == '__main__':
    main()
