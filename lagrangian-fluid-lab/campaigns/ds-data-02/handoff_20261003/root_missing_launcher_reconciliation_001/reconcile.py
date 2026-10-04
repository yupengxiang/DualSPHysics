import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess


p = argparse.ArgumentParser()
p.add_argument('--binding', required=True)
p.add_argument('--report', required=True)
a = p.parse_args()
b = json.loads(Path(a.binding).read_text())
data = Path(b['data_root'])
runtime = data / 'runtime'
report = Path(a.report)
assert not report.exists()
snapshot = subprocess.check_output(['nvidia-smi', '--query-compute-apps=pid,gpu_uuid',
                                    '--format=csv,noheader'], text=True)
gpu_pids = {int(line.split(',')[0]) for line in snapshot.splitlines() if line.strip()}
rows = []
with (runtime / 'resource-ledger.lock').open('a+') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    ledger_path = runtime / 'resource-ledger.json'
    ledger = json.loads(ledger_path.read_text())
    for attempt in b['attempts']:
        reservation = next(x for x in ledger['reservations'] if x['id'] == attempt)
        assert reservation['host'] == socket.gethostname()
        receipt_path = data / 'families' / attempt / 'execution-receipt.json'
        receipt_bytes = receipt_path.read_bytes()
        receipt = json.loads(receipt_bytes)
        assert receipt['status'] == 'running'
        for pid in [reservation['launcher_pid'], receipt['pid']]:
            assert not Path('/proc', str(pid)).exists() and pid not in gpu_pids
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                pass
            else:
                raise RuntimeError('Cannot release reservation of a live process')
        stamp = datetime.now(timezone.utc).isoformat()
        charge = {'id': attempt, 'gpu_seconds': reservation['gpu_seconds'],
                  'cpu_core_seconds': reservation['cpu_core_seconds'],
                  'new_storage_bytes': reservation['new_storage_bytes'],
                  'status': 'launcher_missing_conservative_full_reservation_charge',
                  'finished_at_utc': stamp,
                  'accounting_policy': 'Full reserved upper bounds; actual terminal wait status and rusage unavailable',
                  'original_running_receipt_unchanged': str(receipt_path)}
        assert not any(x['id'] == attempt for x in ledger['charges'])
        lease = None
        if reservation.get('gpu_uuid'):
            lease = data / 'leases' / (reservation['gpu_uuid'] + '.json')
            if lease.exists():
                value = json.loads(lease.read_text())
                assert value['attempt_id'] == attempt and value['launcher_pid'] == reservation['launcher_pid']
                lease.unlink()
        ledger['reservations'] = [x for x in ledger['reservations'] if x['id'] != attempt]
        ledger['charges'].append(charge)
        entry = next(x for x in ledger['attempts'] if x['id'] == attempt)
        entry.update(status='launcher_missing_unfinalized', finished_at_utc=stamp,
                     recovery_report=str(report))
        rows.append({'attempt': attempt, 'source_receipt': str(receipt_path),
                     'source_receipt_sha256': hashlib.sha256(receipt_bytes).hexdigest(),
                     'launcher_pid_absent': reservation['launcher_pid'],
                     'child_pid_absent': receipt['pid'], 'gpu_process_absent': True,
                     'released_own_lease': None if lease is None else str(lease),
                     'charge': charge, 'original_process_returncode': 'unknown',
                     'product_acceptance': 'pending separately dispatched artifact verification'})
    result = {'schema':'ds02.root.missing-launcher-reconciliation.v1', 'at_utc':stamp,
              'attempts':rows, 'actual_process_observation':'/proc absence, kill(pid,0) ESRCH and actual nvidia-smi',
              'original_receipts_preserved':True, 'no_solver_or_converter_relaunch':True,
              'qualification_or_product_success_claim':'none', 'foreign_processes_changed':False}
    with report.open('x') as f:
        json.dump(result,f,indent=2)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    temp = ledger_path.with_name(ledger_path.name + '.' + str(os.getpid()) + '.tmp')
    with temp.open('x') as f:
        json.dump(ledger,f,indent=2)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp,ledger_path)
print('Reconciled',len(rows),'absent own launchers; original receipts preserved; full reservation charged')
