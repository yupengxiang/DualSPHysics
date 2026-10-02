"""Register F7 observations only from a completed, source-bound dense conversion."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LAB = ROOT / 'lagrangian-fluid-lab'
DATA = Path('/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7')

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def register(conversion_request, destination, prefix):
    request = json.loads(conversion_request.read_text())
    assert request['family_id'] == 'F7' and request['cpu_task_kind'] == 'conversion'
    source_dir = DATA / request['case_id'] / request['attempt_id']
    receipt_path = source_dir / 'execution-receipt.json'
    report_path = source_dir / 'conversion-report.json'
    receipt = json.loads(receipt_path.read_text())
    report = json.loads(report_path.read_text())
    if receipt.get('status') != 'completed' or receipt.get('returncode') != 0:
        raise ValueError('Actual completed converter receipt required')
    if receipt.get('request_sha256') != digest(conversion_request):
        raise ValueError('Converter receipt request digest differs')
    actual_inputs = receipt.get('input_hashes_at_launch', {})
    if any(actual_inputs.get(p) != sha for p, sha in request['input_sha256'].items()):
        raise ValueError('Converter receipt input binding differs')
    source = source_dir / 'trajectory.h5'
    if not source.is_file() or report['output_hdf5'] != str(source):
        raise ValueError('Converter final H5 binding required')
    if report['frames'] != 6001 or not report['partvtk_validation']['all_passed']:
        raise ValueError('Complete native dense timeline and official PartVTK checks required')
    if source.stat().st_size <= 0 or len(report['output_sha256']) != 64:
        raise ValueError('Actual output digest required')
    def argument(flag):
        return request['command'][request['command'].index(flag)+1]
    destination.mkdir(parents=True, exist_ok=False)
    scripts = LAB / 'scripts'
    config = {'source_hdf5': str(source), 'source_hdf5_sha256': report['output_sha256'],
        'solver_output': str(Path(argument('--data-root')).parent),
        'generated_xml': argument('--generated-xml'),
        'native_ledger_helper': str(LAB/'campaigns/ds-data-02/families/F2/f2_handoff_20261002_native_ledger.py'),
        'partvtkout': '/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTKOut_linux64',
        'terminal_conversion_receipt': str(receipt_path),
        'terminal_conversion_receipt_sha256': digest(receipt_path),
        'terminal_conversion_report': str(report_path),
        'terminal_conversion_report_sha256': digest(report_path),
        'frames_expected': 6001, 'scientific_reader_changes': False,
        'q_n_status': 'not_assessed', 'production_approval': 'none'}
    config_path = destination / 'binding.json'
    config_path.write_text(json.dumps(config, indent=2)+'\n')
    common = [config_path, conversion_request, receipt_path, report_path, Path(config['generated_xml']),
        Path(config['partvtkout']), Path(config['native_ledger_helper']), Path(__file__).resolve(),
        scripts/'ds_data02_strict_dispatch_v1.py', scripts/'ds_data02_runtime_v2.py',
        scripts/'ds_data02_f3_nvme_input_audit_v1.py', scripts/'ds_data02_f3_macro_input_audit_v2.py',
        scripts/'ds_data02_native_labels.py']
    event = LAB/'campaigns/ds-data-02/families/F7/labels/moving_obstacle_event_config.json'
    for mode in ['observation', 'labels']:
        module = scripts/f'ds_data02_f7_nvme_{mode}_v1.py'
        if mode == 'observation':
            command=[str(LAB/'.venv/bin/python'),str(module),'--config',str(config_path),
                '--output-dir','{attempt_root}','--scratch-parent','/tmp/ds-data-02-root-nvme']
            extra=[scripts/'ds_data02_f7_native_integrity_v1.py',scripts/'ds_data02_f7_reference_macro_v1.py']
        else:
            command=[str(LAB/'.venv/bin/python'),str(module),'--binding',str(config_path),'--config',str(event),
                '--output-dir','{attempt_root}','--scratch-parent','/tmp/ds-data-02-root-nvme']
            extra=[scripts/'ds_data02_f7_reference_labels_v1.py',event]
        files=list(dict.fromkeys(str(p) for p in common+[module]+extra))
        r={'schema':'ds02.runner-request.v2','family_id':'F7','case_id':request['case_id'],
            'attempt_id':f'{prefix}-nvme-{mode}-001','kind':'cpu',
            'cpu_task_kind':'audit' if mode=='observation' else 'labels','cpu_threads':2,
            'max_wall_seconds':10800 if mode=='observation' else 14400,
            'estimated_storage_bytes':20*1024**3, 'cwd':str(LAB),'worktree_root':str(ROOT),
            'command':command,'input_files':files,'input_sha256':{p:digest(p) for p in files},
            'source_binding_policy':'Actual terminal converter digest checked during immutable NVMe copy before scientific use; no duplicate large source input hash pass.',
            'q_n_status':'not_assessed','production_approval':'none'}
        rp=destination/f'{mode}-request.json';rp.write_text(json.dumps(r,indent=2)+'\n')
        print(json.dumps({'request':str(rp),'sha256':digest(rp)}),flush=True)
    return config

if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--conversion-request',type=Path,required=True)
    p.add_argument('--destination',type=Path,required=True)
    p.add_argument('--attempt-prefix',required=True)
    a=p.parse_args()
    register(a.conversion_request,a.destination,a.attempt_prefix)
