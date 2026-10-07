from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
REPO = SCRIPTS.parents[1]
sys.path.insert(0, str(SCRIPTS))
import ds_data02_batch_runner_v3 as batch_v3
import ds_data02_stage2_dispatch_v3 as guard_v3
import ds_data02_batch_runner_v4 as batch_v4
import ds_data02_stage2_dispatch_v4 as guard_v4


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

    def request(name, runner, payload=32, estimated=7_000):
        worker = tmp_path / (name + '.py')
        worker.write_text('from pathlib import Path\nimport sys\n'
                          'Path(sys.argv[1], "payload.bin").write_bytes(b"x" * '
                          + str(payload) + ')\n')
        imported = [*runner.BOUND_RUNNER_FILES, str(worker), sys.executable]
        inputs = []
        for path in imported:
            path = str(Path(path).resolve())
            if path not in inputs:
                inputs.append(path)
        row = dict(family_id='infra', case_id='integration-v4', attempt_id=name,
                   kind='cpu', cpu_task_kind='tests', max_wall_seconds=20, cpu_threads=1,
                   estimated_storage_bytes=estimated,
                   command=[sys.executable, str(worker), '{attempt_root}'],
                   cwd=str(tmp_path), worktree_root=str(REPO), input_files=inputs,
                   input_sha256={path: digest(path) for path in inputs})
        path = tmp_path / (name + '.json')
        path.write_text(json.dumps(row))
        return path

    return root, request


def receipt(root, case, name):
    return root / 'families/infra' / case / name / 'execution-receipt.json'


def test_v4_counts_final_receipt_and_catches_v3_boundary(setup, tmp_path):
    root, request = setup
    # The v3 running receipt is below this value in both clean and dirty
    # worktree states, while its final receipt can push the directory over it.
    estimate = 6_200
    path3 = request('v3-boundary', guard_v3, payload=32, estimated=estimate)
    batch_v3.base.RUNTIME_SCRIPT = batch_v3.DISPATCH
    assert batch_v3.run_batch([path3], max_concurrency=1, data_root=root,
                              output_dir=tmp_path / 'batch-v3') == 0
    old = json.loads(receipt(root, 'integration-v4', 'v3-boundary').read_text())
    old_tree = guard_v3.runtime.base.tree_bytes(Path(old['output_root']))
    assert 32 < estimate
    assert old['bytes'] <= estimate
    assert old_tree > estimate
    assert old_tree > old['bytes']

    path4 = request('v4-boundary', guard_v4, payload=32, estimated=estimate)
    batch_v4.base.RUNTIME_SCRIPT = batch_v4.DISPATCH
    assert batch_v4.run_batch([path4], max_concurrency=1, data_root=root,
                              output_dir=tmp_path / 'batch-v4') != 0
    fixed = json.loads(receipt(root, 'integration-v4', 'v4-boundary').read_text())
    fixed_tree = guard_v4.runtime.base.tree_bytes(Path(fixed['output_root']))
    assert fixed['status'] == 'failed'
    assert fixed['termination_reason'] == 'terminal_storage_reservation_exceeded'
    assert fixed['bytes'] == fixed_tree > estimate
    assert fixed['terminal_storage_guard']['status'] == 'failed'
    assert fixed['terminal_storage_guard']['measurement'] == 'fixed_point_including_final_receipt'
    assert fixed['terminal_storage_guard']['non_receipt_bytes'] < fixed['bytes']
    state = json.loads((root / 'runtime/resource-ledger.json').read_text())
    assert state['reservations'] == []
    assert state['charges'][-1]['status'] == 'failed'
    assert state['charges'][-1]['new_storage_bytes'] == fixed_tree


def test_v4_fast_under_reservation_passes_with_exact_tree_bytes(setup, tmp_path):
    root, request = setup
    path = request('under', guard_v4, payload=32, estimated=65_536)
    batch_v4.base.RUNTIME_SCRIPT = batch_v4.DISPATCH
    assert batch_v4.run_batch([path], max_concurrency=1, data_root=root,
                              output_dir=tmp_path / 'batch') == 0
    terminal = json.loads(receipt(root, 'integration-v4', 'under').read_text())
    actual = guard_v4.runtime.base.tree_bytes(Path(terminal['output_root']))
    assert terminal['status'] == 'completed'
    assert terminal['bytes'] == actual <= terminal['request']['estimated_storage_bytes']
    assert terminal['terminal_storage_guard']['status'] == 'passed'
