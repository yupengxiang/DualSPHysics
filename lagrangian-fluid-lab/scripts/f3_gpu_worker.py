"""Run one NoPen qualification worker with the verified private NVIDIA runtime."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import uuid

from scripts.l1r_continuation_evidence import LAB, OUT, begin_activity_window, finish_activity_window, ledger
from scripts import l1r_q2_mdbc_bridge as q2


def runtime_environment():
    evidence = json.loads((OUT / 'F3-GPU-RUNTIME-RECOVERY.json').read_text())
    root = Path(evidence['root'])
    if Path('/proc/driver/nvidia/version').read_text() != evidence['kernel_version']:
        raise RuntimeError('loaded NVIDIA kernel changed; revalidate private runtime')
    for relative, digest in evidence['library_hashes'].items():
        if q2.sha256(root / relative) != digest:
            raise RuntimeError('private NVIDIA library changed: ' + relative)
    target = root / '595.71.05'
    if q2.sha256(target / 'usr/bin/nvidia-smi') != evidence['nvidia_smi_sha256']:
        raise RuntimeError('private NVIDIA utility changed')
    env = os.environ.copy()
    env['PATH'] = str(target / 'usr/bin') + ':' + env['PATH']
    env['LD_LIBRARY_PATH'] = str(target / 'usr/lib/x86_64-linux-gnu')
    env['OPENBLAS_NUM_THREADS'] = '1'
    env['OMP_NUM_THREADS'] = '8'
    return env


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('entry', choices=[f'NP{i:02}' for i in range(2, 15)])
    args = p.parse_args()
    env = runtime_environment()
    command = [str(LAB / '.venv/bin/python'), '-u', '-m', 'scripts.f3_nopen_qualification', 'run', args.entry]
    lifecycle = OUT / f'F3-{args.entry}-WORKER-{uuid.uuid4().hex[:12]}.json'
    state = dict(entry=args.entry, status='starting', started_at_utc=q2.utc_now(),
                 wrapper_pid=os.getpid(), command=command,
                 runtime_evidence_sha256=q2.sha256(OUT / 'F3-GPU-RUNTIME-RECOVERY.json'),
                 wrapper_sha256=q2.sha256(Path(__file__)))
    begin_activity_window()
    q2.atomic_json(lifecycle, state)
    print('lifecycle=' + str(lifecycle), flush=True)
    worker = None
    try:
        worker = subprocess.Popen(command, cwd=LAB, env=env)
        state.update(worker_pid=worker.pid, status='running')
        q2.atomic_json(lifecycle, state)
        code = worker.wait()
        state.update(status='completed' if code == 0 else 'failed', returncode=code)
        return code
    except BaseException as error:
        state.update(status='wrapper_error', error=repr(error))
        raise
    finally:
        # Do not close accounting if an interrupted wrapper still owns a live child.
        if worker is None or worker.poll() is not None:
            state['finished_at_utc'] = q2.utc_now()
            q2.atomic_json(lifecycle, state)
            finish_activity_window()
            ledger()
        else:
            state['child_may_still_be_running'] = True
            q2.atomic_json(lifecycle, state)


if __name__ == '__main__':
    raise SystemExit(main())
