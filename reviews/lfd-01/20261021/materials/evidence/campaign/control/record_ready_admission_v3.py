#!/usr/bin/python3.10
"""Read real predecessor settlement and write one root admission observation."""
import argparse
import datetime
import fcntl
import hashlib
import json
import resource
import subprocess
from pathlib import Path

ROOT = Path('/data/nas/jade/Simulation/DualSPHysics/lfd-01')
P = ROOT / 'worktree/lagrangian-fluid-lab/campaigns/ds-data-02/lfd-01'
DATA = Path('/data/nas/jade/Simulation/DualSPHysics-data/ds-data-02')


def read(path):
    assert path.is_file() and not path.is_symlink() and path.stat().st_size < 8 * 1024**2
    return json.loads(path.read_bytes())


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def binding(path):
    raw = path.read_bytes()
    assert len(raw) < 8 * 1024**2 and not path.is_symlink()
    return dict(path=str(path), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--grant', type=Path, required=True)
    parser.add_argument('--decision', type=Path, required=True)
    parser.add_argument('--predecessor', action='append', default=[])
    parser.add_argument('--gpu', action='store_true')
    args = parser.parse_args()
    for path in (args.request, args.grant, args.decision):
        assert path.is_absolute() and path.resolve() == path and path.is_relative_to(P)
    assert not args.decision.exists()
    request = read(args.request)
    grant = read(args.grant)
    # Early compatibility observation only; immutable shared runner repeats admission.
    if request.get("execution_class") == "heavy":
        assert request.get("ram_limit_bytes") in {64 * 1024**3, 128 * 1024**3, 256 * 1024**3}, "immutable S01/v14 heavy RAM tier mismatch"
    adoption = read(P / 'control/ADOPTION.json')
    now = datetime.datetime.now(datetime.timezone.utc)
    assert now < datetime.datetime.fromisoformat(adoption['deadline_utc'])
    assert grant['request_sha256'] == binding(args.request)['sha256']
    assert grant['payload_sha256'] == digest({k: v for k, v in grant.items() if k != 'payload_sha256'})
    aid = '/'.join(request[k] for k in ('family_id', 'case_id', 'attempt_id'))
    assert grant['attempt_id'] == aid and request['reservation_id'] == aid
    assert request['owner_id'] == 'LFD-01/root' and grant['issuer'] == 'root' and grant['immutable'] is True
    assert read(P / 'control/M0_ACCEPTANCE.json')['status'] == 'accepted'
    with (DATA / 'runtime/resource-ledger.lock').open('r') as lock:
        fcntl.flock(lock, fcntl.LOCK_SH)
        ledger = read(DATA / 'runtime/resource-ledger.json')
        baseline = read(P / 'control/BASELINE.json')
        for key, prior_key in (('charges', 'prior_charge_rows'), ('attempts', 'prior_attempt_rows')):
            prior = baseline[prior_key]
            assert len(ledger[key]) >= len(prior)
            assert all(row['id'] == expected['id'] and digest(row) == expected['sha256']
                for row, expected in zip(ledger[key][:len(prior)], prior))
        assert not any(r.get('lfd01_class') == 'heavy' for r in ledger['reservations'])
        assert not any(r['id'] == aid for r in ledger['charges'] + ledger['reservations'] + ledger['attempts'])
        predecessors = []
        for before in args.predecessor:
            parts = before.split('/')
            assert len(parts) == 3 and all('/' not in p and p not in ('', '.', '..') for p in parts)
            rp = ROOT / 'runs' / before / 'execution-receipt.json'
            receipt = read(rp)
            rows = [r for r in ledger['charges'] if r['id'] == before]
            assert len(rows) == 1 and not any(r['id'] == before for r in ledger['reservations'])
            assert receipt['status'] == 'completed' and receipt['returncode'] == 0
            rt = receipt['lfd01_runtime']
            assert rt['child_exit_confirmed'] is True and not rt.get('unreaped_branch_unknown') and not rt.get('terminal_settlement_blocked')
            for lp in (DATA / 'leases').glob('*.json'):
                assert read(lp).get('attempt_id') != before
            predecessors.append(dict(receipt=binding(rp), unique_parent_charge=rows[0],
                child_exit_confirmed=True, final_reap=rt.get('final_reap'), old_reservation_and_lease_absent=True))
        usage = {k: sum(float(r.get(k, 0)) for r in ledger['charges'] if r.get('campaign_id') == 'LFD-01')
            for k in ('gpu_seconds', 'cpu_core_seconds', 'new_storage_bytes')}
    gpu_snapshot = None
    if args.gpu:
        result = subprocess.run(['/usr/bin/nvidia-smi', '--query-compute-apps=pid,gpu_uuid,used_gpu_memory', '--format=csv,noheader,nounits'],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=20, check=True)
        gpu_snapshot = result.stdout.strip()
    for path, floor in ((ROOT, 2 * 1024**4), (Path('/home/jade'), 500 * 1024**3)):
        import os
        stat = os.statvfs(path)
        assert stat.f_bavail * stat.f_frsize >= floor
    decision = dict(schema='lfd01.root.admission-decision.v1', campaign_id='LFD-01',
        status='admitted_for_shared_runner_only', issued_at_utc=now.isoformat(), request=binding(args.request), grant=binding(args.grant),
        predecessors=predecessors, old_charge_and_attempt_prefix_sha_unchanged=True,
        single_heavy_clear_at_observation=True, actual_lfd01_usage=usage, foreign_gpu_process_snapshot=gpu_snapshot,
        resource_admission='Existing shared runner must repeat current UUID lease and atomic parent pool/tranche/global admission; this observation does not reserve resources.',
        reservation_envelope=dict(gpu_seconds=request['max_wall_seconds'] if request['kind'] in ('qualification', 'production') else 0,
            cpu_core_seconds=request['max_wall_seconds'] * request['cpu_threads'],
            new_storage_bytes=request['estimated_storage_bytes'], nas_peak_bytes=request['nas_peak_bytes']),
        scope=request.get('purpose'), frozen_method_review=grant.get('non_author_payload_review'),
        core_credit=0, source_or_actual_validation_claim=False)
    with args.decision.open('x') as stream:
        json.dump(decision, stream, indent=2, ensure_ascii=False)
        stream.write('\n')
    u = resource.getrusage(resource.RUSAGE_SELF)
    c = resource.getrusage(resource.RUSAGE_CHILDREN)
    cost = dict(schema='lfd01.root.admission-cost.v1', cpu_core_seconds=u.ru_utime + u.ru_stime + c.ru_utime + c.ru_stime,
        scope='This process SELF plus uniquely waited nvidia-smi child only; ledger read-only and small predecessor metadata; detached science excluded',
        accounting='pending_next_unique_incremental_infrastructure_settlement', decision=binding(args.decision))
    with (args.request.parent / 'admission-cpu.json').open('x') as stream:
        json.dump(cost, stream, indent=2)
        stream.write('\n')
    print(json.dumps(dict(decision=binding(args.decision), predecessors=predecessors, actual_lfd01_usage=usage, cpu_core_seconds=cost['cpu_core_seconds'])))


if __name__ == '__main__':
    main()
