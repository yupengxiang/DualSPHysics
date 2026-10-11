"""Root-controlled, charged preparation and actual M4 relocation handoff."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

P = Path(__file__).resolve().parent
ROOT = P.parents[3]
PYTHON = '/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python'
M4 = P / 'm4'
sys.path.insert(0, str(P / 'batch2-runtime'))
from grant_request import grant

RUNTIME = [ROOT / 'lagrangian-fluid-lab/scripts' / name for name in (
    'ds_data02_runtime_v2.py', 'ds_data02_runtime_v6.py', 'ds_data02_runtime_v6_batch2.py')]
WORKER = M4 / 'actual_validation/m4_actual_validation.py'
WRAPPER = M4 / 'm4_isolated_validate.py'
ADMISSION = P / 'batch2-runtime/root-batch-2-admission.json'


def load(path):
    return json.loads(path.read_text())


def completed(run, attempt):
    receipt = load(run / attempt / 'execution-receipt.json')
    if receipt['status'] != 'completed':
        raise RuntimeError(f'{attempt} is not actually completed')
    return receipt


def execute(run, request):
    attempt = request['attempt_id']
    if (run / attempt).exists():
        raise RuntimeError(f'fresh attempt required: {run / attempt}')
    request['input_files'] = list(dict.fromkeys(request['input_files'] + [
        str(path) for path in RUNTIME + [WORKER, WRAPPER, M4 / 'm4_portable_adapter.py', Path(__file__)]]))
    if not all(Path(path).is_file() for path in request['input_files']):
        raise RuntimeError('missing regular input')
    request_path = P / 'requests' / f"{request['case_id']}-{attempt}.json"
    with request_path.open('x') as stream:
        json.dump(request, stream, indent=2)
        stream.write('\n')
    granted = grant(request_path)
    print(f"Launching {request['case_id']}/{attempt}", flush=True)
    with (P / 'batch2-runtime' / f"{request['case_id']}-{attempt}-runner-summary.json").open('x') as output:
        subprocess.run([PYTHON, str(RUNTIME[-1]), 'run', '--request', str(request_path),
                        '--batch-admission', str(ADMISSION), '--batch-grant', str(granted)],
                       cwd=ROOT, stdout=output, check=True)
    return completed(run, attempt)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', required=True, choices=[f'UF_F1_MDBC_DP010_H{depth}' for depth in ('050', '052', '058', '060')])
    args = parser.parse_args()
    case = args.case
    run = Path('/data/nas/jade/Simulation/DualSPHysics/upstream-first/runs/F1') / case
    completed(run, 'm4-enrichment-001')
    completed(run, 'm4-portable-build-001')
    product = run / 'm4-enrichment-001/product'
    bundle = run / 'm4-portable-build-001/bundle'
    source_receipt = product / 'enrichment-receipt.json'
    receipt = load(source_receipt)
    if receipt['status'] != 'completed' or receipt['case_id'] != case:
        raise RuntimeError('wrong enrichment source')
    inputs = [str(source_receipt), str(product / 'interface.json'), str(product / 'enriched.h5'),
              str(run / 'm4-enrichment-001/execution-receipt.json'),
              str(run / 'm4-portable-build-001/execution-receipt.json')]
    inputs += [str(path) for path in sorted(bundle.rglob('*')) if path.is_file()]
    prep_attempt = 'm4-relocation-preparation-001'
    request = {
        'schema': 'ds-data-02.runner.request.v1', 'status': 'root_authorized_actual_completed_source',
        'family_id': 'F1', 'case_id': case, 'attempt_id': prep_attempt,
        'kind': 'cpu', 'cpu_task_kind': 'conversion', 'cpu_threads': 4,
        'max_wall_seconds': 3600, 'estimated_storage_bytes': 64 * 1024**2,
        'estimated_temp_peak_bytes': 64 * 1024**2, 'output_storage': 'upstream_nas',
        'cwd': str(ROOT), 'worktree_root': str(ROOT), 'input_files': inputs,
        'command': [PYTHON, str(WORKER), 'prepare-request', '--source-receipt', str(source_receipt),
                    '--source-bundle', str(bundle), '--output-request', '{attempt_root}/relocation-request.json',
                    '--relocated-bundle-template', '{attempt_root}/m4-actual-validation/relocated/' + case,
                    '--isolation-wrapper', str(WRAPPER), '--python', PYTHON, '--source-mask-root', str(run)],
        'qualification': 'heavy_actual_payload_preparation_charged_and_serialized',
    }
    execute(run, request)
    prepared_path = run / prep_attempt / 'relocation-request.json'
    prepared = load(prepared_path)
    if prepared['case_id'] != case or prepared['source_bundle']['production_validation']['portable'] is not True:
        raise RuntimeError('prepared source did not pass actual production validation')
    if '--source-mask-root' not in prepared['command'] or str(run) not in prepared['source_mask_roots']:
        raise RuntimeError('original complete case is not masked')
    if prepared['storage_reservation']['estimated_new_bytes_upper_bound'] > 16 * 1024**3:
        raise RuntimeError('actual relocation and one scratch copy exceed this concrete request bound')
    prepared.update({
        'status': 'root_authorized_completed_actual_preparation', 'cpu_task_kind': 'conversion',
        'cpu_threads': 4, 'estimated_storage_bytes': 16 * 1024**3,
        'estimated_temp_peak_bytes': 1024**3, 'cwd': str(ROOT), 'worktree_root': str(ROOT),
        'qualification': 'actual_source_denied_relocation_and_rehashed_payload_negatives',
    })
    prepared['input_files'] += [str(prepared_path), str(run / prep_attempt / 'execution-receipt.json')]
    execute(run, prepared)
    result = load(run / 'm4-actual-validation-001/m4-actual-validation/results/actual-validation-receipt.json')
    if not (result['status'] == 'completed' and result['source_unchanged'] is True
            and result['isolated_replay']['portable'] is True
            and result['isolated_replay']['denied_probes_passed'] is True
            and result['semantic_negatives']['passed'] is True and result['semantic_negatives']['count'] == 2):
        raise RuntimeError('actual relocation acceptance is incomplete')
    print(f'{case}: actual relocated replay and both rehashed payload negatives completed; source unchanged.', flush=True)


if __name__ == '__main__':
    main()
