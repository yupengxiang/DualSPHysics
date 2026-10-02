"""Bound and adopt the exact interrupted F4 conversion, then dispatch F7."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone

LAB = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(LAB/'scripts'))
import ds_data02_runtime_v2 as rt

PACK = Path(__file__).resolve().parent
IDENTITY = 'F4/F4_COL_CENTERED_REFERENCE_001_DP0025/root-centered-fullstate-conversion-001'
ROOT = rt.DATA_ROOT/'families'/IDENTITY
ORIGINAL = ROOT/'execution-receipt.json'
original_bytes = ORIGINAL.read_bytes()
receipt = json.loads(original_bytes)
assert receipt['pid'] == 4085499 and receipt['status'] == 'running'
pid = receipt['pid']
duration = receipt['request']['max_wall_seconds']
started = datetime.fromisoformat(receipt['started_at_utc'])
assert duration == 7200


def process_rows():
    return [line.split(None, 3) for line in subprocess.check_output(
        ['ps', '-e', '-o', 'pid=,pgid=,etimes=,args='], text=True).splitlines()]


def own_group():
    rows = [r for r in process_rows() if len(r) == 4 and int(r[1]) == pid]
    leader = [r for r in rows if int(r[0]) == pid]
    if rows:
        assert leader, 'Cannot safely identify orphan group without original leader'
        assert 'ds_data02_direct_convert.py' in leader[0][3] and str(ROOT) in leader[0][3]
        elapsed = (datetime.now(timezone.utc)-started).total_seconds()
        assert abs(elapsed-int(leader[0][2])) < 30, 'Process start does not match original receipt'
    return rows


reason = None
while own_group():
    elapsed = (datetime.now(timezone.utc)-started).total_seconds()
    limits = json.loads((rt.DATA_ROOT/'runtime/resource-ledger.json').read_text())['limits']
    filesystem = os.statvfs('/home/jade')
    if elapsed >= duration:
        reason = 'reserved_wall_time_exceeded_after_launcher_loss'
    elif filesystem.f_bavail*filesystem.f_frsize < limits['home_min_free_bytes']:
        reason = 'home_free_floor_exceeded'
    elif rt.tree_bytes(ROOT) > receipt['request']['estimated_storage_bytes']:
        reason = 'reserved_storage_exceeded'
    if reason:
        own_group()  # Verify exact leader and group immediately before signalling.
        os.killpg(pid, signal.SIGTERM)
        time.sleep(5)
        if own_group():
            os.killpg(pid, signal.SIGKILL)
        break
    time.sleep(15)

assert not own_group()
assert ORIGINAL.read_bytes() == original_bytes
(PACK/'original-execution-receipt.json').write_bytes(original_bytes)
report_path = ROOT/'conversion-report.json'
status = 'failed'
evidence = {'termination_reason': reason, 'terminal_report_present': report_path.exists()}
if report_path.exists():
    report = json.loads(report_path.read_text())
    assert report['conversion_status'] == 'completed'
    assert report['frames'] == 1201 and report['particles'] == 1195649
    assert report['partvtk_validation']['all_passed'] is True
    assert report['output_sha256'] == rt.sha256(ROOT/'trajectory.h5')
    status = 'completed'
    evidence.update(frames=report['frames'], particles=report['particles'], output_sha256=report['output_sha256'], report_sha256=rt.sha256(report_path))
actual = {p: rt.sha256(p) for p in receipt['input_hashes_at_launch']}
assert actual == receipt['input_hashes_at_launch']
recovered = dict(receipt)
recovered.update(schema='ds02.recovered-execution-receipt.v1', status=status,
                 returncode=None, finished_at_utc=rt.now(), input_hashes_after_run=actual,
                 termination_reason=reason, recovery={
                     'original_receipt': str(ORIGINAL), 'original_sha256': rt.sha256(ORIGINAL),
                     'completion_semantics': 'Full terminal conversion report, official validation and final HDF5 hash; original wait returncode unavailable',
                     'evidence': evidence, 'usage_semantics': 'Conservative full original reservation charged',
                     'signals': 'Only exact verified original process group if original resource bound exceeded'})
new_receipt = PACK/'recovered-execution-receipt.json'
assert not new_receipt.exists()
new_receipt.write_text(json.dumps(recovered, indent=2)+'\n')
with rt.ledger_locked(rt.DATA_ROOT) as ledger:
    row = next(x for x in ledger['reservations'] if x['id'] == IDENTITY)
    assert row['launcher_pid'] == 4085086
    assert not any(int(r[0]) == row['launcher_pid'] for r in process_rows())
    ledger['reservations'] = [x for x in ledger['reservations'] if x['id'] != IDENTITY]
    ledger['charges'].append({'id': IDENTITY, 'gpu_seconds': 0,
                             'cpu_core_seconds': row['cpu_core_seconds'],
                             'new_storage_bytes': rt.tree_bytes(ROOT), 'status': status,
                             'finished_at_utc': rt.now(), 'recovered_receipt': str(new_receipt),
                             'recovered_receipt_sha256': rt.sha256(new_receipt),
                             'usage_semantics': 'Conservative full original reservation after launcher loss'})
    for x in ledger['attempts']:
        if x['id'] == IDENTITY:
            x.update(status=status, finished_at_utc=rt.now(), terminal_receipt=str(new_receipt), recovered=True)
print(json.dumps({'recovered': IDENTITY, 'status': status}), flush=True)

request = LAB/'campaigns/ds-data-02/families/F7/handoff_20261002/finer_dp001_reference_001/independent_time_save_001/fullstate_conversion_001/half_dt_request.json'
q = json.loads(request.read_text())
assert all(rt.sha256(p) == h for p, h in q['input_sha256'].items())
result = rt.run_request(request)
print(json.dumps({k: result.get(k) for k in ('status', 'returncode', 'output_root', 'termination_reason')}), flush=True)
