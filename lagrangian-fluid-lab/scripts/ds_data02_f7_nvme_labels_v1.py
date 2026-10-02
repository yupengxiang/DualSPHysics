"""Observe complete F7 labels on verified NVMe bytes and publish once."""
import argparse
import json
import os
from pathlib import Path
import signal
import tempfile

import h5py

from ds_data02_f3_nvme_input_audit_v1 import verified_copy
from ds_data02_f7_reference_labels_v1 import observe
from ds_data02_native_labels import digest

def run(binding_path, config_path, output_dir, scratch):
    binding=json.loads(binding_path.read_text())
    source=Path(binding['source_hdf5'])
    signature=lambda p: (p.stat().st_dev,p.stat().st_ino,p.stat().st_size,p.stat().st_mtime_ns)
    before=signature(source)
    scratch.mkdir(parents=True,exist_ok=True)
    usage=os.statvfs(scratch)
    if usage.f_bavail*usage.f_frsize < source.stat().st_size+100*1024**3:
        raise ValueError('Source copy requires source size plus 100 GiB free')
    output_dir.mkdir(parents=True,exist_ok=True)
    final=output_dir/'native-labels.h5'
    stage=output_dir/'native-labels.h5.unpublished'
    if final.exists() or stage.exists():
        raise FileExistsError('Existing label output or owned unpublished stage')
    with tempfile.TemporaryDirectory(prefix='ds02-f7-labels-',dir=scratch) as temporary:
        target=Path(temporary)/'trajectory.h5'
        actual=verified_copy(source,target,binding['source_hdf5_sha256'])
        report=observe(target,stage,json.loads(config_path.read_text()),particle_chunk=65536)
        # This private stage has no downstream consumer. Rebind source path
        # before the single publication; all scientific arrays are unchanged.
        with h5py.File(stage,'r+') as h:
            assert str(h.attrs['source_hdf5_sha256'])==actual
            assert str(h.attrs['source_hdf5'])==str(target.resolve())
            h.attrs['source_hdf5']=str(source.resolve())
            h.attrs['audit_storage_protocol']='SHA256-identical private NVMe source; original read-only; native observer unchanged'
            h.attrs['audited_copy_sha256']=actual
        if signature(source)!=before:
            raise ValueError('Original changed during read-only label observation')
        report['source_hdf5']=str(source)
        report['path']=str(final)
        report['sha256']=digest(stage)
        report['audit_storage_protocol']={'source_verified_before_observation':True,
            'audited_copy_sha256':actual,'original_stat_unchanged':True,
            'scientific_reader':'unchanged ds_data02_f7_reference_labels_v1.observe',
            'source_path_rebound_on_unpublished_stage':True}
        os.replace(stage,final)
    report['private_scratch_removed']=True
    (output_dir/'labels-report.json').write_text(json.dumps(report,indent=2)+'\n')
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['binding','config','output-dir','scratch-parent']:
        p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args()
    def stop_owned(*_):
        raise SystemExit(143)
    signal.signal(signal.SIGTERM,stop_owned)
    r=run(a.binding,a.config,a.output_dir,a.scratch_parent)
    print(json.dumps({k:r[k] for k in ['path','sha256','frames','all_observed_crossing_rows','final_native_exclusion_mass_kg','q_n_status']}),flush=True)
