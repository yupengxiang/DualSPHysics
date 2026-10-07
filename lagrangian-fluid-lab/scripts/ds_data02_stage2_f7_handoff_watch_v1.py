"""Root scheduling only: wait for the exact F5 batch to exit, then run F7.

The waiting process reads no scientific arrays. Each subsequent F7 attempt
uses the existing strict dispatcher, immutable request, and original ledger.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time


def process_start(pid):
    try:
        raw = (Path('/proc') / str(pid) / 'stat').read_text()
    except FileNotFoundError:
        return None
    return int(raw[raw.rfind(')') + 2:].split()[19])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binding', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    binding = json.loads(args.binding.read_text())
    if binding['role'] != 'ROOT_SCHEDULING_ONLY' or binding['concurrency'] != 1:
        raise ValueError('Unexpected scheduling scope')
    rows = binding['request_sha256']
    if len(rows) != 48:
        raise ValueError('Exactly 48 F7 requests required')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({'status': 'WAITING_EXACT_F5_PARENT_EXIT',
        'predecessor': binding['predecessor'], 'H5_opened': False,
        'model_invoked': False}, indent=2) + '\n')
    predecessor = binding['predecessor']
    while process_start(predecessor['pid']) == predecessor['starttime_ticks']:
        time.sleep(15)
    # Recheck frozen scheduling inputs after waiting, before any new batch.
    for path, expected in binding['frozen_input_sha256'].items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != expected:
            raise ValueError('Scheduling input changed: ' + path)
    for path in rows:
        request = json.loads(Path(path).read_text())
        if request['family_id'] != 'F7' or request['kind'] != 'cpu' or request['cpu_task_kind'] != 'audit':
            raise ValueError('Request outside F7 science audit scope')
        output = Path(binding['data_root']) / 'families' / request['family_id'] / request['case_id'] / request['attempt_id']
        if output.exists():
            raise FileExistsError('F7 attempt already exists: ' + str(output))
    if Path(binding['batch_output']).exists():
        raise FileExistsError('F7 batch already exists')
    args.output.write_text(json.dumps({'status': 'EXACT_F5_PARENT_EXIT_CONFIRMED_F7_BATCH_EXEC',
        'predecessor': predecessor, 'H5_opened_by_watch': False,
        'model_invoked': False, 'request_count': 48}, indent=2) + '\n')
    command = [binding['python'], '-B', binding['batch_runner'], *sorted(rows),
        '--concurrency', '1', '--label', 'stage2-F7-science-v4-001',
        '--data-root', binding['data_root'], '--output-dir', binding['batch_output']]
    os.chdir(binding['cwd'])
    os.execv(command[0], command)


if __name__ == '__main__':
    main()
