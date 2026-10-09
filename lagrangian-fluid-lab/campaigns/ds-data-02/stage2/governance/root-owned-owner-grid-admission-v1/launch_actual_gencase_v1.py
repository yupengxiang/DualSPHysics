"""Launch one reserved GenCase task with stat-only root forcing checks."""
from pathlib import Path
import datetime
import importlib.util
import json
import os
import subprocess
import time

HERE = Path(__file__).resolve().parent
LAB = HERE.parents[4]
S = LAB / 'campaigns/ds-data-02/stage2'
D = Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
PYTHON = '/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python'


def launch_and_wait(request, namespace):
    spec = importlib.util.spec_from_file_location('owner_grid_launch_admission', S / 'governance/root-owned-native-admission-v1/continue_after_serial_v1.py')
    admission = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(admission)
    spec = importlib.util.spec_from_file_location('owner_grid_exact_auxiliary_preparation', HERE / 'prepare_actual_gencase_v1.py')
    preparation = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(preparation)
    q = admission.load(request)
    assert q['status'] == 'READY_ROOT_EXACT_AUXILIARY_RUNTIME_CLOSURE'
    assert q['execution_allowed'] and not q['source_only'] and not q['launch_disabled']
    assert q['command'][0] == '/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64'
    assert q['command'][2:] == ['{attempt_root}/generated', '-save:all', '-threads:1']
    assert q['cpu_threads'] == 1 and q['max_memory_bytes'] == 4294967296
    controls = {row['path']: row for row in q['root_exact_auxiliary_closure']}
    for path, expected in q['input_sha256'].items():
        if path in controls and not controls[path]['root_content_read']:
            assert preparation.stat_record(path) == controls[path]['stat']
            assert expected == controls[path]['sha256']
            assert path in q['input_files'] and Path(path).stat().st_size == 14919771
        else:
            assert admission.sha(path) == expected, path
    ledger = admission.load(D / 'runtime/resource-ledger.json')
    assert not ledger['reservations']
    now = datetime.datetime.now(datetime.timezone.utc)
    assert now + datetime.timedelta(seconds=q['max_wall_seconds'] + 45) < datetime.datetime.fromisoformat(ledger['deadline_utc'])
    assert sum(row.get('cpu_core_seconds', 0) for row in ledger['charges']) + q['max_wall_seconds'] < ledger['limits']['cpu_core_seconds']
    disk = os.statvfs(ledger['limits']['home_path'])
    assert disk.f_bavail * disk.f_frsize - q['estimated_storage_bytes'] >= ledger['limits']['home_min_free_bytes']
    assert not Path(q['output_root']).exists()
    code = ('import sys,os,json;sys.path.insert(0,' + repr(str(LAB / 'scripts')) + ');'
            'from ds_data02_runtime_v8 import run_request;r=run_request(' + repr(str(request)) +
            ',data_root=' + repr(str(D)) + ',parent_pid=os.getppid());print(json.dumps(r));'
            'raise SystemExit(0 if r["status"]=="completed" else 1)')
    unit = f'ds02-owner-grid-gencase-v2-root-{namespace}'
    command = ['systemd-run', '--user', '--unit=' + unit, '--property=Type=exec',
               '--property=RemainAfterExit=yes', '--property=RuntimeMaxSec=' + str(q['max_wall_seconds'] + 30),
               '--property=TimeoutStopSec=45', '--property=KillMode=mixed', '--property=CPUAccounting=yes',
               '--property=MemoryAccounting=yes', '--property=MemoryMax=' + str(q['max_memory_bytes'])]
    command += ['--setenv=' + name + '=1' for name in ['OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS']]
    command += [PYTHON, '-B', '-I', '-c', code]
    subprocess.run(command, check=True)
    while True:
        current = admission.state(unit)
        if current['SubState'] != 'running':
            break
        print(json.dumps(dict(event='RUNNING_OWNER_GRID_GENCASE', namespace=namespace, unit=unit,
                              CPU_core_seconds=int(current['CPUUsageNSec']) / 1e9)), flush=True)
        time.sleep(30)
    assert current['SubState'] == 'exited' and current['MainPID'] == '0' and current['Result'] == 'success', current
    return unit
