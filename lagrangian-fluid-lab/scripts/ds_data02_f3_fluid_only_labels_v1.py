"""F3 transport reference view preserving every recorded dynamic fluid field."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import signal
import tempfile
from types import SimpleNamespace

import h5py
import numpy as np

from ds_data02_f3_nvme_input_audit_v1 import verified_copy
from ds_data02_native_labels import digest
from ds_data02_verified_native_labels_v1 import label_closure


class IntegerView:
    def __init__(self, dataset, dtype, allowed=None):
        self.dataset, self.dtype, self.allowed = dataset, np.dtype(dtype), allowed
        self.shape = dataset.shape

    def __getitem__(self, key):
        value = np.asarray(self.dataset[key])
        if not np.isfinite(value).all() or not np.equal(value, np.rint(value)).all():
            raise ValueError('Native categorical field is nonfinite or fractional')
        if self.allowed is not None and not np.isin(value, self.allowed).all():
            raise ValueError('Unsupported native categorical value')
        limits = np.iinfo(self.dtype)
        if (value < limits.min).any() or (value > limits.max).any():
            raise ValueError('Native integer field exceeds declared dtype')
        return value.astype(self.dtype)


class FluidOnlyView:
    def __init__(self, path, binding):
        self.h = h5py.File(path, 'r')
        try:
            required = ['time', 'particle_id', 'particle_zone', 'position', 'velocity', 'valid', 'type', 'mass', 'mk']
            if any(name not in self.h for name in required):
                raise ValueError('Required actual dynamic native field absent')
            nt, n = self.h['valid'].shape
            if (nt, n) != (binding['frames'], binding['fluid_particles']):
                raise ValueError('Fluid-only recorded dimensions differ')
            self.fields = {name: self.h[name] for name in self.h}
            for name, dtype, allowed in [('type', 'i1', [0, 1, 2, 3]), ('mk', 'i4', None), ('particle_id', 'u4', None), ('particle_zone', 'i4', None)]:
                self.fields[name] = IntegerView(self.h[name], dtype, allowed)
            for name in ['type', 'mk', 'mass']:
                if self.h[name].shape != (nt, n):
                    raise ValueError('Native dynamic scalar shape mismatch')
            if self.h['position'].shape != (nt, n, 3) or self.h['velocity'].shape != (nt, n, 3):
                raise ValueError('Native dynamic vector shape mismatch')
            ids, zones = self.fields['particle_id'][:], self.fields['particle_zone'][:]
            if not np.array_equal(ids, np.arange(binding['fluid_id_range'][0], binding['fluid_id_range'][1]+1)) or not (zones == 0).all():
                raise ValueError('Recorded identity differs from official native cohort')
            initial_type, initial_mk = self.fields['type'][0], self.fields['mk'][0]
            initial_mass = self.h['mass'][0]
            if not (initial_type == 3).all() or not (initial_mk == 1).all() or not (self.h['valid'][0] == 1).all():
                raise ValueError('Initial native cohort is not the audited fluid population')
            if not np.isfinite(initial_mass).all() or not (initial_mass > 0).all():
                raise ValueError('Native initial mass invalid')
            self.fields.update(initial_type=initial_type, initial_mk=initial_mk, initial_mass=initial_mass)
            self.attrs = dict(self.h.attrs)
            if self.attrs.get('coordinate_frame', binding['coordinate_frame']) != binding['coordinate_frame']:
                raise ValueError('Contradictory recorded coordinate frame')
            self.attrs['coordinate_frame'] = binding['coordinate_frame']
        except BaseException:
            self.h.close()
            raise

    def __contains__(self, key):
        return key in self.fields

    def __getitem__(self, key):
        return self.fields[key]

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.h.close()


def isolated_module(path, source, binding):
    """Only this private module's File lookup routes the one read-only source."""
    spec = importlib.util.spec_from_file_location('_ds02_f3_private_reader', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    def file_router(path, mode='r', *args, **kwargs):
        if Path(path).resolve() == source.resolve():
            if mode != 'r' or args or kwargs:
                raise ValueError('Adapted source must remain strictly read-only')
            return FluidOnlyView(path, binding)
        return h5py.File(path, mode, *args, **kwargs)
    module.h5py = SimpleNamespace(File=file_router)
    return module


def run(binding_path, config_path, output_dir, scratch):
    binding = json.loads(binding_path.read_text())
    source = Path(binding['source_hdf5'])
    for name in ['anchor_receipt', 'anchor_report']:
        if digest(binding[name]) != binding[name+'_sha256']:
            raise ValueError('Official anchor binding changed')
    receipt = json.loads(Path(binding['anchor_receipt']).read_text())
    anchor = json.loads(Path(binding['anchor_report']).read_text())
    if receipt['status'] != 'completed' or receipt['returncode'] != 0 or not anchor['all_frames_passed']:
        raise ValueError('Actual official anchor completion required')
    if anchor['h5_path'] != str(source):
        raise ValueError('Official anchors refer to a different source')
    scratch.mkdir(parents=True, exist_ok=True)
    free = os.statvfs(scratch)
    if free.f_bavail*free.f_frsize < source.stat().st_size+100*1024**3:
        raise ValueError('Insufficient NVMe capacity')
    output_dir.mkdir(parents=True, exist_ok=True)
    final, stage = output_dir/'native-labels.h5', output_dir/'native-labels.h5.unpublished'
    if final.exists() or stage.exists():
        raise FileExistsError('Preserve previous label artifact')
    before = source.stat()
    with tempfile.TemporaryDirectory(prefix='ds02-f3-fluid-reference-', dir=scratch) as tmp:
        target = Path(tmp)/'source.h5'
        verified_copy(source, target, binding['source_hdf5_sha256'])
        audit = isolated_module(Path(__file__).with_name('ds_data02_f3_macro_input_audit_v2.py'), target, binding).audit_input(target)
        if audit['status'] != 'pass':
            (output_dir/'failed-native-input-audit.json').write_text(json.dumps(audit, indent=2)+'\n')
            raise ValueError('Recorded active fluid states failed finite positive audit')
        module = isolated_module(Path(__file__).with_name('ds_data02_native_labels.py'), target, binding)
        with FluidOnlyView(target, binding) as view:
            ids = np.column_stack((view['particle_zone'][:], view['particle_id'][:]))
            mass = float(view['initial_mass'][:].astype(float).sum())
        result = module.materialize(target, stage, json.loads(config_path.read_text()), particle_chunk=16384)
        closure = label_closure(stage, ids, mass)
        if not closure['passed']:
            (output_dir/'failed-closure.json').write_text(json.dumps(closure, indent=2)+'\n')
            raise ValueError('Fluid-only transport labels failed closure')
        with h5py.File(stage, 'r+') as h:
            h.attrs.update(source_hdf5=str(source.resolve()), fluid_only_reference=True,
                           fixed_trajectory_present=False, full_typed_q_i_granted=False,
                           mass_normalization='none; actual stored native per-frame mass',
                           adapter_policy='categorical integer validation; actual dynamic fields passed through; initial fields from actual frame zero')
        after = source.stat()
        if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
            raise ValueError('Immutable original changed')
        os.replace(stage, final)
    audit['path'] = str(source)
    result.update(path=str(final), sha256=digest(final), source_hdf5=str(source),
                  source_hdf5_sha256=binding['source_hdf5_sha256'], closure=closure,
                  native_input_audit=audit, fluid_only_reference=True,
                  full_typed_q_i_granted=False, private_scratch_removed=True,
                  native_header_mass_kg=binding['native_header_mass_kg'],
                  actual_stored_initial_mass_kg=mass, mass_normalization='none')
    (output_dir/'labels-report.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ['binding', 'config', 'output-dir', 'scratch-parent']:
        p.add_argument('--'+name, type=Path, required=True)
    a = p.parse_args()
    def stop(*_):
        raise SystemExit(143)
    signal.signal(signal.SIGTERM, stop)
    print(json.dumps(run(a.binding, a.config, a.output_dir, a.scratch_parent)), flush=True)
