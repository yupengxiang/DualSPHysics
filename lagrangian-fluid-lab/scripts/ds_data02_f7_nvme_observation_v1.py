"""Run unchanged full F7 integrity/macros on a verified temporary NVMe copy."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import tempfile

from ds_data02_f3_nvme_input_audit_v1 import verified_copy
from ds_data02_f7_native_integrity_v1 import inspect
from ds_data02_f7_reference_macro_v1 import series

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def bind_original(value, transient, original):
    if isinstance(value, str):
        return original if value == transient else value
    if isinstance(value, list):
        return [bind_original(x, transient, original) for x in value]
    if isinstance(value, dict):
        return {k: bind_original(v, transient, original) for k, v in value.items()}
    return value

def signature(path):
    s = path.stat()
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)

def run(config_path, output, scratch):
    config = json.loads(config_path.read_text())
    source = Path(config['source_hdf5'])
    before = signature(source)
    output.mkdir(parents=True, exist_ok=True)
    if any((output/name).exists() for name in ['source-contract.json','full-integrity-report.json','macro-series.json','nvme-observation.json']):
        raise FileExistsError('Existing completed observation output')
    scratch.mkdir(parents=True, exist_ok=True)
    usage = os.statvfs(scratch)
    if usage.f_bavail * usage.f_frsize < source.stat().st_size + 100*1024**3:
        raise ValueError('Temporary NVMe copy requires source size plus 100 GiB free')
    with tempfile.TemporaryDirectory(prefix='ds02-f7-observation-', dir=scratch) as temporary:
        target = Path(temporary)/'trajectory.h5'
        actual = verified_copy(source, target, config['source_hdf5_sha256'])
        print(json.dumps({'stage':'verified-copy','source':str(source),'sha256':actual}),flush=True)
        report = inspect(target, Path(config['solver_output']), Path(config['generated_xml']),
            Path(config['native_ledger_helper']), Path(config['partvtkout']), output)
        # Rebind the logical artifact to its unchanged original bytes after the
        # identical scientific reader has audited the checksum-identical copy.
        contract_path = output/'source-contract.json'
        contract = bind_original(json.loads(contract_path.read_text()), str(target), str(source))
        contract['audit_storage_protocol'] = {'original':str(source),
            'audited_copy_sha256':actual,'original_untouched':True,
            'reader':'unchanged ds_data02_f7_native_integrity_v1.inspect'}
        contract_path.write_text(json.dumps(contract,indent=2)+'\n')
        report = bind_original(report,str(target),str(source))
        report['source_contract']['sha256'] = digest(contract_path)
        report['audit_storage_protocol'] = contract['audit_storage_protocol']
        (output/'full-integrity-report.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps({'stage':'full-integrity','q_i_status':report['q_i_status']}),flush=True)
        macro = series(target,output/'macro-series.json')
        macro = bind_original(macro,str(target),str(source))
        macro['audit_storage_protocol'] = {'audited_copy_sha256':actual,
            'reader':'unchanged ds_data02_f7_reference_macro_v1.series'}
        (output/'macro-series.json').write_text(json.dumps(macro,indent=2)+'\n')
        if signature(source)!=before:
            raise ValueError('Original source changed during read-only observation')
    result = {'schema':'ds02.f7.nvme-observation.v1','config':str(config_path),
        'config_sha256':digest(config_path),'source_hdf5':str(source),
        'source_hdf5_sha256':actual,'copy_verified_before_scientific_audit':True,
        'private_scratch_removed':True,'original_stat_unchanged':True,
        'q_i_status':report['q_i_status'],'q_n_status':'not_assessed',
        'production_approval':'none','macro':{'path':str(output/'macro-series.json'),
        'sha256':digest(output/'macro-series.json')},'integrity_report':{
        'path':str(output/'full-integrity-report.json'),
        'sha256':digest(output/'full-integrity-report.json')}}
    (output/'nvme-observation.json').write_text(json.dumps(result,indent=2)+'\n')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ['config','output-dir','scratch-parent']:
        p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args()
    def stop_owned(*_):
        raise SystemExit(143)
    signal.signal(signal.SIGTERM,stop_owned)
    r=run(a.config,a.output_dir,a.scratch_parent)
    print(json.dumps(r),flush=True)
    raise SystemExit(0 if r['q_i_status']=='Q-I-structure-pass' else 1)
