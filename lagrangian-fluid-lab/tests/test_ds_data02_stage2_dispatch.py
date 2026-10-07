"""Exercise the actual batch -> guard -> runtime -> CPU worker chain."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
REPO = SCRIPTS.parents[1]
sys.path.insert(0, str(SCRIPTS))
import ds_data02_batch_runner as batch
import ds_data02_stage2_dispatch as guard


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture
def setup(tmp_path):
    root = tmp_path / 'data'
    (root / 'runtime').mkdir(parents=True)
    ledger = dict(deadline_utc=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
                  limits=dict(gpu_seconds=100, cpu_core_seconds=500, new_storage_bytes=100_000_000,
                              qualification_attempts=2, production_attempts=2,
                              storage_policy='home_free_floor', home_min_free_bytes=1),
                  attempts=[], reservations=[], charges=[])
    (root / 'runtime/resource-ledger.json').write_text(json.dumps(ledger))

    def request(name, code='print("ok")', **updates):
        worker = tmp_path / (name + '.py')
        worker.write_text(code)
        inputs = [*guard.BOUND_RUNNER_FILES, str(worker), sys.executable]
        row = dict(family_id='infra', case_id='integration', attempt_id=name, kind='cpu',
                   cpu_task_kind='tests', max_wall_seconds=60, cpu_threads=1,
                   estimated_storage_bytes=20_000_000, command=[sys.executable, str(worker)],
                   cwd=str(tmp_path), worktree_root=str(REPO), input_files=inputs,
                   input_sha256={str(Path(p).resolve()): digest(p) for p in inputs})
        row.update(updates)
        path = tmp_path / (name + '.json')
        path.write_text(json.dumps(row))
        return path

    return root, request


def launch(root, requests, output, concurrency=1):
    return subprocess.Popen([sys.executable, str(SCRIPTS / 'ds_data02_batch_runner.py'),
                             *map(str, requests), '--concurrency', str(concurrency),
                             '--data-root', str(root), '--output-dir', str(output)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ledger(root):
    return json.loads((root / 'runtime/resource-ledger.json').read_text())


def receipt(root, name):
    return root / 'families/infra/integration' / name / 'execution-receipt.json'


def wait_for(predicate, timeout=18):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            result = predicate()
            if result:
                return result
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        time.sleep(0.05)
    raise AssertionError('Timed out waiting for actual process/receipt state')


def test_eight_mib_log_has_no_pipe_backpressure(setup, tmp_path):
    root, request = setup
    path = request('large', 'import sys\nsys.stdout.write("x" * (8 * 1024 * 1024))')
    proc = launch(root, [path], tmp_path / 'batch')
    assert proc.wait(timeout=15) == 0
    assert json.loads(receipt(root, 'large').read_text())['status'] == 'completed'
    assert (receipt(root, 'large').parent / 'stdout.log').stat().st_size == 8 * 1024 * 1024
    assert ledger(root)['reservations'] == []
    assert len(ledger(root)['charges']) == 1


@pytest.mark.parametrize('sig', [signal.SIGTERM, signal.SIGKILL])
def test_killing_batch_closes_worker_and_accounting(setup, tmp_path, sig):
    root, request = setup
    path = request('cancel', 'import time\ntime.sleep(45)')
    proc = launch(root, [path], tmp_path / 'batch')
    running = wait_for(lambda: (r if (r := json.loads(receipt(root, 'cancel').read_text()))['status'] == 'running' else None))
    os.kill(proc.pid, sig)
    proc.wait(timeout=18)
    terminal = wait_for(lambda: (r if (r := json.loads(receipt(root, 'cancel').read_text()))['status'] == 'failed' else None))
    wait_for(lambda: not Path('/proc', str(running['pid'])).exists())
    wait_for(lambda: ledger(root)['reservations'] == [])
    assert terminal['interrupted']
    assert len(ledger(root)['charges']) == 1


@pytest.mark.parametrize('updates', [dict(max_wall_seconds=float('nan')),
                                    dict(estimated_storage_bytes=float('inf')),
                                    dict(cpu_threads=0), dict(cpu_threads=1.5)])
def test_invalid_resources_rejected_before_reservation(setup, tmp_path, updates):
    root, request = setup
    proc = launch(root, [request('invalid', **updates)], tmp_path / 'batch')
    assert proc.wait(timeout=12) != 0
    assert ledger(root)['attempts'] == []
    assert ledger(root)['charges'] == []


def test_mutated_input_stops_pending_homogeneous_requests(setup, tmp_path):
    root, request = setup
    first = request('mutated')
    (tmp_path / 'mutated.py').write_text('print("changed")')
    second = request('next')
    proc = launch(root, [first, second], tmp_path / 'batch')
    assert proc.wait(timeout=12) != 0
    summary = json.loads((tmp_path / 'batch/batch-receipt.json').read_text())
    assert len(summary['failed']) == 1
    assert len(summary['skipped']) == 1
    assert ledger(root)['attempts'] == []


def test_attempt_cannot_be_restarted(setup, tmp_path):
    root, request = setup
    path = request('once')
    assert launch(root, [path], tmp_path / 'first').wait(timeout=12) == 0
    assert launch(root, [path], tmp_path / 'second').wait(timeout=12) != 0
    assert len(ledger(root)['attempts']) == 1
    assert len(ledger(root)['charges']) == 1


def test_duplicate_batch_attempt_rejected_before_launch(setup, tmp_path):
    root, request = setup
    path = request('duplicate')
    with pytest.raises(ValueError, match='Duplicate attempt'):
        batch.run_batch([path, path], data_root=root, output_dir=tmp_path / 'batch')
    assert ledger(root)['attempts'] == []


@pytest.mark.parametrize('concurrency', [0, -1, 1.5, True])
def test_invalid_concurrency_cannot_hang(setup, concurrency):
    root, request = setup
    with pytest.raises(ValueError, match='positive integer'):
        batch.run_batch([request('concurrency')], concurrency, data_root=root)


def test_disk_floor_prevents_worker_start(setup, tmp_path):
    root, request = setup
    d = ledger(root)
    d['limits']['home_min_free_bytes'] = 10**18
    (root / 'runtime/resource-ledger.json').write_text(json.dumps(d))
    assert launch(root, [request('disk')], tmp_path / 'batch').wait(timeout=12) != 0
    assert ledger(root)['attempts'] == []
    r = json.loads(receipt(root, 'disk').read_text())
    assert 'floor' in r['error']
    assert r['started_at_utc'] is None


def test_nonfinite_ledger_cannot_bypass_parent_budget(setup, tmp_path):
    root, request = setup
    d = ledger(root)
    d['limits']['cpu_core_seconds'] = float('nan')
    (root / 'runtime/resource-ledger.json').write_text(json.dumps(d))
    assert launch(root, [request('ledger')], tmp_path / 'batch').wait(timeout=12) != 0
    assert ledger(root)['attempts'] == []


def test_half_written_receipt_is_failure_not_stdout_success(setup, tmp_path, monkeypatch):
    root, request = setup
    path = request('partial')
    fake = tmp_path / 'partial-dispatch.py'
    target = receipt(root, 'partial')
    fake.write_text(f'from pathlib import Path\np=Path({str(target)!r})\np.parent.mkdir(parents=True)\np.write_text("{{")\nprint("completed")\n')
    monkeypatch.setattr(batch, 'RUNTIME_SCRIPT', fake)
    assert batch.run_batch([path], data_root=root, output_dir=tmp_path / 'batch') != 0
    summary = json.loads((tmp_path / 'batch/batch-receipt.json').read_text())
    assert summary['failed'][0]['status'] == 'failed'


def test_gpu_lease_conflict_excludes_all_eligible_uuids():
    devices = [dict(index=i, uuid=f'uuid{i}', total_mib=49000, used_mib=0) for i in [2, 5, 6, 7]]
    with pytest.raises(RuntimeError, match='no eligible'):
        guard.runtime.choose_gpu(dict(devices=devices, processes=[]), {d['uuid'] for d in devices}, 1000)
