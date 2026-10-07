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
import ds_data02_batch_runner_v3 as batch
import ds_data02_stage2_dispatch_v3 as guard


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

    def request(name, payload=0, estimated=65_536, code=None, **updates):
        worker = tmp_path / (name + '.py')
        if code is None:
            code = ('from pathlib import Path\n'
                    'import sys\n'
                    'Path(sys.argv[1], "payload.bin").write_bytes(b"x" * ' + str(payload) + ')\n')
        worker.write_text(code)
        imported = [
            *guard.BOUND_RUNNER_FILES,
            str(Path(batch.__file__).resolve()),
            str(Path(batch.base.__file__).resolve()),
            str(worker),
            sys.executable,
        ]
        inputs = []
        for path in imported:
            path = str(Path(path).resolve())
            if path not in inputs:
                inputs.append(path)
        row = dict(family_id='infra', case_id='integration-v3', attempt_id=name,
                   kind='cpu', cpu_task_kind='tests', max_wall_seconds=20, cpu_threads=1,
                   estimated_storage_bytes=estimated,
                   command=[sys.executable, str(worker), '{attempt_root}'],
                   cwd=str(tmp_path), worktree_root=str(REPO), input_files=inputs,
                   input_sha256={path: digest(path) for path in inputs})
        row.update(updates)
        path = tmp_path / (name + '.json')
        path.write_text(json.dumps(row))
        return path

    return root, request


def receipt(root, name):
    return root / 'families/infra/integration-v3' / name / 'execution-receipt.json'


def ledger(root):
    return json.loads((root / 'runtime/resource-ledger.json').read_text())


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


def test_fast_worker_over_reservation_fails_terminally_and_charges_actual_bytes(setup, tmp_path):
    root, request = setup
    path = request('over', payload=16_384, estimated=1_024)
    assert batch.run_batch([path], max_concurrency=1, data_root=root, output_dir=tmp_path / 'batch') != 0
    terminal = json.loads(receipt(root, 'over').read_text())
    assert terminal['status'] == 'failed'
    assert terminal['termination_reason'] == 'terminal_storage_reservation_exceeded'
    assert terminal['terminal_storage_guard']['status'] == 'failed'
    assert terminal['bytes'] > terminal['request']['estimated_storage_bytes']
    assert terminal['runner_source'] == guard.runtime.RUNTIME_PATH
    assert ledger(root)['reservations'] == []
    assert ledger(root)['charges'][0]['status'] == 'failed'
    assert ledger(root)['charges'][0]['new_storage_bytes'] == terminal['bytes']


def test_fast_worker_within_reservation_completes_and_passes_terminal_check(setup, tmp_path):
    root, request = setup
    path = request('under', payload=32, estimated=65_536)
    assert batch.run_batch([path], max_concurrency=1, data_root=root, output_dir=tmp_path / 'batch') == 0
    terminal = json.loads(receipt(root, 'under').read_text())
    assert terminal['status'] == 'completed'
    assert terminal['terminal_storage_guard']['status'] == 'passed'
    assert terminal['bytes'] <= terminal['request']['estimated_storage_bytes']
    assert ledger(root)['reservations'] == []
    assert ledger(root)['charges'][0]['status'] == 'completed'


def test_resource_floor_rejection_keeps_accounting_clean(setup, tmp_path):
    root, request = setup
    state = ledger(root)
    state['limits']['home_min_free_bytes'] = 10 ** 18
    (root / 'runtime/resource-ledger.json').write_text(json.dumps(state))
    assert batch.run_batch([request('floor')], max_concurrency=1, data_root=root,
                           output_dir=tmp_path / 'batch') != 0
    terminal = json.loads(receipt(root, 'floor').read_text())
    assert terminal['status'] == 'failed'
    assert 'floor' in terminal['error']
    assert terminal['started_at_utc'] is None
    assert ledger(root)['attempts'] == []
    assert ledger(root)['reservations'] == []
    assert ledger(root)['charges'] == []


def test_parent_cancellation_waits_and_releases_reservation(setup, tmp_path):
    root, request = setup
    path = request('cancel', code='import time\ntime.sleep(45)\n')
    proc = subprocess.Popen([sys.executable, str(batch.__file__), str(path),
                             '--concurrency', '1', '--data-root', str(root),
                             '--output-dir', str(tmp_path / 'batch')])
    running = wait_for(lambda: (r if (r := json.loads(receipt(root, 'cancel').read_text()))['status'] == 'running' else None))
    os.kill(proc.pid, signal.SIGTERM)
    proc.wait(timeout=18)
    terminal = wait_for(lambda: (r if (r := json.loads(receipt(root, 'cancel').read_text()))['status'] == 'failed' else None))
    wait_for(lambda: not Path('/proc', str(running['pid'])).exists())
    assert terminal['interrupted']
    assert ledger(root)['reservations'] == []
    assert len(ledger(root)['charges']) == 1
    assert ledger(root)['charges'][0]['status'] == 'failed'
