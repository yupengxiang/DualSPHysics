"""Root-authorized continuation after the independent native audit queue."""
import json
import os
import subprocess
import time
from pathlib import Path

CAMPAIGN = Path(__file__).resolve().parents[1]
ROOT = CAMPAIGN.parents[3]
RUNS = Path('/data/nas/jade/Simulation/DualSPHysics/upstream-first/runs/F1')
PYTHON = '/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python'
RUNNER = ROOT / 'lagrangian-fluid-lab/scripts/ds_data02_runtime_v6.py'
COMPARISON = CAMPAIGN / 'm3/f1-fine-dp010-t025/comparison'
CASES = ['UF_F1_MDBC_DP010_H050', 'UF_F1_MDBC_DP010_H060']

def run(request):
    d = json.loads(request.read_text())
    target = RUNS / d['case_id'] / d['attempt_id']
    if target.exists():
        raise RuntimeError(f'refusing existing attempt {target}')
    print('Launching '+d['case_id']+'/'+d['attempt_id'], flush=True)
    with open('/tmp/'+d['case_id']+'-'+d['attempt_id']+'-observation-queue.json', 'x') as out:
        subprocess.run([PYTHON, str(RUNNER), 'run', '--request', str(request)], cwd=ROOT, stdout=out, check=True)
    receipt = json.loads((target/'execution-receipt.json').read_text())
    if receipt['status'] != 'completed':
        raise RuntimeError('noncompleted observation attempt')

def main():
    deadline = time.monotonic()+7500
    while True:
        ready = True
        for case in CASES:
            for attempt, report in [('native-integrity-001','integrity.json'), ('native-frame-scan-001','frame-identity-scan.json')]:
                path = RUNS/case/attempt/'execution-receipt.json'
                if not path.exists():
                    ready=False
                    continue
                receipt=json.loads(path.read_text())
                if receipt['status']=='running':
                    ready=False
                    continue
                if receipt['status']!='completed':
                    raise RuntimeError('native audit failed; no observation launch')
                evidence=json.loads((path.parent/report).read_text())
                if evidence['status']!='verified':
                    raise RuntimeError('native audit unverified')
        if ready:
            break
        os.kill(3691651, 0)  # confirmed owner of the existing audit queue
        if time.monotonic()>deadline:
            raise TimeoutError('bounded native audit wait expired')
        time.sleep(10)
    for case in CASES:
        run(CAMPAIGN/'requests'/f'{case}-postprocess-001.json')
        candidates=COMPARISON/'candidates-after-postprocess'/case
        subprocess.run([PYTHON,str(COMPARISON/'finalize_m3_requests_v1.py'),'--case',case.rsplit('_',1)[1],'--candidate-dir',str(candidates)],cwd=ROOT,check=True)
        candidate=candidates/f'{case}-comparison.ready.json'
        d=json.loads(candidate.read_text())
        d.update(status='root_authorized_receipt_bound',candidate_only=False,root_review_required=False,launch_authorization='User adopted goal; root reviewed comparator and receipt-bound finalizer before queue launch')
        for name in ['ds_data02_runtime_v2.py','ds_data02_runtime_v6.py']:
            path=str(ROOT/'lagrangian-fluid-lab/scripts'/name)
            if path not in d['input_files']:
                d['input_files'].append(path)
        request=CAMPAIGN/'requests'/f'{case}-comparison-001.json'
        with request.open('x') as out:
            json.dump(d,out,indent=2)
            out.write('\n')
        run(request)
    print('Both actual derivative observation comparisons completed.',flush=True)

if __name__=='__main__':
    main()
