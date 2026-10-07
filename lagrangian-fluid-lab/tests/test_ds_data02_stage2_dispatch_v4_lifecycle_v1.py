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
import ds_data02_batch_runner_v4 as batch
import ds_data02_stage2_dispatch_v4 as guard


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

    def request(name, payload=32, estimated=65_536):
        worker = tmp_path / (name + '.py')
        worker.write_text('from pathlib import Path\nimport sys\n'
                          'Path(sys.argv[1], "payload.bin").write_bytes(b"x" * '
                          + str(payload) + ')\n')
        inputs = [*guard.BOUND_RUNNER_FILES, str(worker), sys.executable]
        inputs = list(dict.fromkeys(str(Path(path).resolve()) for path in inputs))
        row = dict(family_id='infra', case_id='integration-v4-lifecycle', attempt_id=name,
                   kind='cpu', cpu_task_kind='tests', max_wall_seconds=20, cpu_threads=1,
                   estimated_storage_bytes=estimated,
                   command=[sys.executable, str(worker), '{attempt_root}'],
                   cwd=str(tmp_path), worktree_root=str(REPO), input_files=inputs,
                   input_sha256={path: digest(path) for path in inputs})
        path = tmp_path / (name + '.json')
        path.write_text(json.dumps(row))
        return path

    return root, request


def receipt(root, name):
    return root / 'families/infra/integration-v4-lifecycle' / name / 'execution-receipt.json'


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


def test_v4_oversize_charges_post_receipt_tree(setup, tmp_path):
    root, request = setup
    path = request('over', payload=16_384, estimated=1_024)
    batch.base.RUNTIME_SCRIPT = batch.DISPATCH
    assert batch.run_batch([path], max_concurrency=1, data_root=root,
                           output_dir=tmp_path / 'batch') != 0
    terminal = json.loads(receipt(root, 'over').read_text())
    actual = guard.runtime.base.tree_bytes(Path(terminal['output_root']))
    assert terminal['status'] == 'failed'
    assert terminal['termination_reason'] == 'terminal_storage_reservation_exceeded'
    assert terminal['bytes'] == actual > terminal['request']['estimated_storage_bytes']
    assert terminal['terminal_storage_guard']['measurement'] == 'fixed_point_including_final_receipt'
    state = json.loads((root / 'runtime/resource-ledger.json').read_text())
    assert state['reservations'] == []
    assert state['charges'][-1]['new_storage_bytes'] == actual


def test_v4_floor_rejection_has_no_attempt_or_charge(setup, tmp_path):
    root, request = setup
    state_path = root / 'runtime/resource-ledger.json'
    state = json.loads(state_path.read_text())
    state['limits']['home_min_free_bytes'] = 10 ** 18
    state_path.write_text(json.dumps(state))
    path = request('floor')
    batch.base.RUNTIME_SCRIPT = batch.DISPATCH
    assert batch.run_batch([path], max_concurrency=1, data_root=root,
                           output_dir=tmp_path / 'batch') != 0
    terminal = json.loads(receipt(root, 'floor').read_text())
    assert terminal['status'] == 'failed'
    assert 'floor' in terminal['error']
    assert terminal['started_at_utc'] is None
    state = json.loads(state_path.read_text())
    assert state['attempts'] == [] and state['reservations'] == [] and state['charges'] == []


def test_v4_parent_cancel_releases_lease_and_charges_failed(setup, tmp_path):
    root, request = setup
    path = request('cancel', payload=0)
    payload = json.loads(path.read_text())
    worker = Path(payload['command'][1])
    worker.write_text('import time\ntime.sleep(45)\n')
    payload['input_sha256'][str(worker.resolve())] = digest(worker)
    path.write_text(json.dumps(payload))
    proc = subprocess.Popen([sys.executable, str(batch.__file__), str(path),
                             '--concurrency', '1', '--data-root', str(root),
                             '--output-dir', str(tmp_path / 'batch')])
    running = wait_for(lambda: (r if (r := json.loads(receipt(root, 'cancel').read_text()))['status'] == 'running' else None))
    os.kill(proc.pid, signal.SIGTERM)
    proc.wait(timeout=18)
    terminal = wait_for(lambda: (r if (r := json.loads(receipt(root, 'cancel').read_text()))['status'] == 'failed' else None))
    wait_for(lambda: not Path('/proc', str(running['pid'])).exists())
    assert terminal['interrupted']
    assert guard.runtime.base.tree_bytes(Path(terminal['output_root'])) == terminal['bytes']
    state = json.loads((root / 'runtime/resource-ledger.json').read_text())
    assert state['reservations'] == [] and state['charges'][-1]['status'] == 'failed'
