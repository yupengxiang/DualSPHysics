"""Bounded continuation of the two actual derivatives through the shared runner."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from prepare_derivative_native_audits import CAMPAIGN, RUNS, prepare

ROOT = CAMPAIGN.parents[3]
PYTHON = '/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python'
RUNNER = ROOT / 'lagrangian-fluid-lab/scripts/ds_data02_runtime_v6.py'
CASES = ['UF_F1_MDBC_DP010_H050', 'UF_F1_MDBC_DP010_H060']

def main():
    deadline = time.monotonic() + 1900
    # The existing H060 process owns the sole heavy queue until its receipt closes.
    while True:
        receipt = json.loads((RUNS / CASES[1] / 'solver-001/execution-receipt.json').read_text())
        if receipt['status'] == 'completed':
            break
        if receipt['status'] != 'running':
            raise RuntimeError('H060 did not complete; no audit launched')
        os.kill(int(receipt['pid']), 0)
        if time.monotonic() >= deadline:
            raise TimeoutError('bounded H060 dependency wait expired')
        time.sleep(10)
    for case in CASES:
        for mode, attempt, report in [('exclusions', 'native-integrity-001', 'integrity.json'),
                                      ('frames', 'native-frame-scan-001', 'frame-identity-scan.json')]:
            out = RUNS / case / attempt
            if out.exists():
                raise RuntimeError(f'refusing existing attempt: {out}')
            request = CAMPAIGN / 'm3/f1-fine-dp010-t025/audits' / f'{case}-{attempt}-request.json'
            if not request.exists():
                request = Path(prepare(case, mode))
            print(f'Launching {case}/{attempt}', flush=True)
            with open(f'/tmp/{case}-{attempt}-queue-summary.json', 'x') as summary:
                subprocess.run([PYTHON, str(RUNNER), 'run', '--request', str(request)],
                               cwd=ROOT, stdout=summary, check=True)
            actual = json.loads((out / 'execution-receipt.json').read_text())
            evidence = json.loads((out / report).read_text())
            if actual['status'] != 'completed' or evidence['status'] != 'verified':
                raise RuntimeError(f'actual audit failed: {case}/{attempt}')
            print(f'Verified {case}/{attempt}', flush=True)
    print('Both derivative native audits verified; CSV comparisons remain separate.', flush=True)

if __name__ == '__main__':
    main()
