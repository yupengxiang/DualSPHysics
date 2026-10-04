import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile

import h5py
import numpy as np


def sha(p):
    h = hashlib.sha256()
    with Path(p).open('rb') as f:
        for block in iter(lambda: f.read(8*1024**2), b''):
            h.update(block)
    return h.hexdigest()


p = argparse.ArgumentParser()
p.add_argument('--binding', required=True)
p.add_argument('--output-dir', required=True)
a = p.parse_args()
b = json.loads(Path(a.binding).read_text())
out = Path(a.output_dir)
source = Path(b['receipt'])
source_sha = sha(source)
receipt = json.loads(source.read_text())
assert receipt['status'] == 'running'
assert not Path('/proc',str(receipt['pid'])).exists()
current = {path:sha(path) for path in receipt['input_hashes_at_launch']}
assert current == receipt['input_hashes_at_launch']
result = {'schema':'ds02.root.unfinalized-artifact-verification.v1',
          'original_receipt':str(source),'original_receipt_sha256':source_sha,
          'original_launcher_OS_returncode':'unknown; original receipt remains unchanged',
          'input_hashes_current_match_launch':True,
          'provenance_limit':'No original end-of-run hash observation or OS wait status; current byte equality verified separately',
          'q_n':'not_granted','production_approval':'none','independent_case_count_increment':0}
if b['kind'] == 'native':
    run = Path(b['run_out'])
    text = run.read_text()
    assert 'Finished execution (code=0).' in text
    assert '**3D-Simulation parameters' in text or '** 3D-Simulation parameters' in text
    files = sorted(Path(b['data_root']).glob('Part_[0-9][0-9][0-9][0-9].bi4'))
    assert len(files) == b['expected_frames']
    assert [q.stem for q in files] == ['Part_'+str(i).zfill(4) for i in range(len(files))]
    assert all(q.stat().st_size > 0 for q in files)
    result.update(native_solver_self_reported_returncode=0,original_command=receipt['command'],
                  original_request=receipt['request'],run_out_sha256=sha(run),
                  native_frames=len(files),native_frame_sizes=[q.stat().st_size for q in files],
                  full_native_state_and_time_QA='pending converter; file census alone does not establish numerical qualification')
else:
    report = json.loads(Path(b['artifact_report']).read_text())
    source_h5 = Path(b['source_h5'])
    assert source_h5.stat().st_size == b['expected_bytes']
    expected = report['pose_trajectory']['sha256'] if b['kind']=='pose' else report['output_sha256']
    scratch = Path(b['scratch_parent'])
    scratch.mkdir(parents=True,exist_ok=True)
    assert shutil.disk_usage(scratch).free-source_h5.stat().st_size >= b['nvme_min_free_bytes']
    with tempfile.TemporaryDirectory(prefix='unfinalized-artifact-',dir=scratch) as private:
        target = Path(private)/'verified.h5'
        h = hashlib.sha256()
        with source_h5.open('rb') as src,target.open('xb') as dst:
            for block in iter(lambda:src.read(8*1024**2),b''):
                h.update(block)
                dst.write(block)
        assert h.hexdigest()==expected and sha(target)==expected
        with h5py.File(target,'r') as f:
            assert f['position'].shape == (b['expected_frames'],b['expected_particles'],3)
            times=f['time'][:]
            assert times[0]==0 and times[-1]>=b['window_end_s'] and np.isfinite(times).all() and np.all(np.diff(times)>0)
            keys=['time','particle_id','particle_zone','initial_type','initial_mk','initial_mass',
                  'mass','type','mk','valid','position','velocity','density']
            assert all(key in f and not f[key].dtype.hasobject for key in keys)
            fluid=f['initial_type'][:]==3
            assert int(fluid.sum())==b['expected_fluid'] and np.all(f['initial_mass'][:]>0)
            assert len(np.unique(np.stack([f['particle_zone'][:],f['particle_id'][:]],axis=1),axis=0))==b['expected_particles']
            if b['kind']=='pose':
                assert report['all_13_payloads_bitwise_unchanged'] and report['pose']['status']=='pass'
                for key in keys:
                    ds=f[key];fingerprint=hashlib.sha256()
                    if ds.ndim==1:
                        for start in range(0,ds.shape[0],131072):fingerprint.update(ds[start:start+131072].tobytes(order='C'))
                    else:
                        for i in range(ds.shape[0]):fingerprint.update(ds[i:i+1].tobytes(order='C'))
                    assert fingerprint.hexdigest()==report['mandatory_payload_fingerprints'][key]['values_sha256']
            result.update(verified_hdf5=str(source_h5),verified_hdf5_sha256=expected,
                          frames=len(times),particles=b['expected_particles'],fluid_particles=int(fluid.sum()),
                          native_window_s=[float(times[0]),float(times[-1])],
                          all_13_payload_fingerprints_reverified=b['kind']=='pose',
                          immutable_source_written=False,private_copy_deleted=True)
    assert sha(source_h5)==expected
assert sha(source)==source_sha
assert {path:sha(path) for path in receipt['input_hashes_at_launch']}==current
with (out/'artifact-verification.json').open('x') as f:
    json.dump(result,f,indent=2)
    f.write('\n')
