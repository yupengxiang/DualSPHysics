"""Root-only bounded dispatch after actual F7 conversion and live scratch checks."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time

LAB = Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab')
DATA = Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
sys.path.insert(0, str(LAB / 'scripts'))
from ds_data02_strict_dispatch_v1 import run_request

REQUEST = Path(__file__).with_name('request.json')
EXPECTED_SHA = '15dbcd35ec24676a4e48f2468c0c6d1b09efcaded542207cba6ba8e717a19709'
DEPENDENCY = DATA / 'families/F7/F7_OBSTACLE_EXPLICIT_WET_CELLS_DP001_REFERENCE_001_HALF_DT_DENSE_SAVE002_FLOORSAFE001/root-floor-safe-half-dense-fullstate-nvme-conversion-002'
RECORD = DATA / 'runtime/root-queue-f1-fine-fulltyped-after-f7-005.json'
FLOOR = 100 * 1024**3


def bytes_in(path):
    return sum(p.stat().st_size for p in path.rglob('*') if p.is_file())


def run():
    if RECORD.exists():
        raise FileExistsError(RECORD)
    if hashlib.sha256(REQUEST.read_bytes()).hexdigest() != EXPECTED_SHA:
        raise ValueError('Root fine request differs from registered digest')
    req = json.loads(REQUEST.read_text())
    state = {'schema': 'ds02.root.bounded-terminal-and-scratch-watch.v1',
             'status': 'waiting_for_actual_F7_terminal_and_scratch',
             'request': str(REQUEST), 'expected_request_sha256': EXPECTED_SHA,
             'dependency': str(DEPENDENCY), 'watch_seconds': 7200,
             'qualification_claim': 'none', 'independent_case_count_increment': 0}
    def publish():
        RECORD.write_text(json.dumps(state, indent=2) + '\n')
    started = time.monotonic()
    while time.monotonic() - started < 7200:
        receipt = json.loads((DEPENDENCY / 'execution-receipt.json').read_text())
        state.update(dependency_status=receipt['status'],
                     dependency_pid=receipt.get('pid'),
                     dependency_process_alive=Path('/proc/' + str(receipt.get('pid'))).exists(),
                     waited_seconds=time.monotonic() - started)
        if receipt['status'] in ('failed', 'stopped'):
            state['status'] = 'dependency_failed_no_dispatch'
            publish()
            return
        report_path = DEPENDENCY / 'conversion-report.json'
        if receipt['status'] == 'completed' and receipt.get('returncode') == 0 and report_path.exists():
            report = json.loads(report_path.read_text())
            if (report['frames'] != 6001 or not report['partvtk_validation']['all_passed'] or
                    not report['storage_protocol']['private_staging_removed']):
                raise ValueError('F7 completed artifact does not satisfy actual source contract')
            ledger = json.loads((DATA / 'runtime/resource-ledger.json').read_text())
            active = ledger['reservations']
            conversions = sum(r.get('cpu_task_kind') == 'conversion' for r in active)
            free = shutil.disk_usage('/tmp').free
            drop_growth = max(0, 147276467386 - bytes_in(Path('/tmp/ds02-f4-contact-staging')))
            # Count the full medium cap conservatively even if partly allocated or completed.
            other_conversion_growth = 25741235808
            after = free - drop_growth - other_conversion_growth - req['estimated_storage_bytes']
            state.update(nvme_free_bytes=free, remaining_DROP_growth_bytes=drop_growth,
                         conservative_other_conversion_growth_bytes=other_conversion_growth,
                         free_after_new_peak_and_other_growth_bytes=after)
            if (conversions < 2 and after >= FLOOR and
                    sum(r.get('cpu_threads', 0) for r in active) + req['cpu_threads'] <= 64):
                if hashlib.sha256(REQUEST.read_bytes()).hexdigest() != EXPECTED_SHA:
                    raise ValueError('Root fine request changed while waiting')
                state['status'] = 'dispatching_once'
                publish()
                result = run_request(REQUEST)
                state.update(status='runner_terminal', receipt_status=result['status'],
                             returncode=result.get('returncode'), output_root=result['output_root'])
                publish()
                return
        publish()
        time.sleep(10)
    state['status'] = 'wait_window_exhausted_no_dispatch'
    publish()


if __name__ == '__main__':
    run()
