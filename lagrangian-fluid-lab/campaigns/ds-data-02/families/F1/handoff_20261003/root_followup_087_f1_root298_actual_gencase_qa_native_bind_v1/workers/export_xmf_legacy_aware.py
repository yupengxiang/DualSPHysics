"""Legacy-aware full temporal XDMF exporter for F1 typed Root186 products.

The worker is intentionally a Root-owned CPU action.  It reads the immutable
trajectory only when the registered request runs.  The HDF5 physical-condition
attribute is checked against the converter's legacy-owner-scope.v0 report hash;
the canonical physical owner is checked separately and is never forced to equal
the legacy scope.  No numerical precision or Q-N claim is made.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET


FIELDS = ('valid', 'initial_type', 'particle_id', 'particle_zone', 'initial_mk',
          'initial_mass', 'mass', 'velocity', 'density', 'pressure', 'type')
HEX = set('0123456789abcdefABCDEF')


class ExportError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def require_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise ExportError(f'{label} is missing: {path}')


def require_hash(path: Path, expected: str, label: str) -> None:
    require_file(path, label)
    actual = sha256(path)
    if actual != expected:
        raise ExportError(f'{label} SHA differs: {actual} != {expected}')


def decode_attr(value) -> str:
    if isinstance(value, bytes):
        return value.decode('utf-8')
    return str(value)


def canonical_binding_hash(value: dict) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def verify_legacy_aware_binding(binding: dict) -> tuple[dict, dict, dict, dict]:
    canonical_path = Path(binding['canonical_owner'])
    typed_owner_path = Path(binding['typed_owner'])
    canonical = load(canonical_path)
    typed_owner = load(typed_owner_path)
    if sha256(canonical_path) != binding['canonical_owner_sha256']:
        raise ExportError('canonical owner SHA differs')
    if sha256(typed_owner_path) != binding['typed_owner_sha256']:
        raise ExportError('typed owner SHA differs')
    canonical_sha = binding['canonical_physical_condition_sha256']
    if canonical.get('physical_condition_sha256') != canonical_sha:
        raise ExportError('canonical owner physical condition differs')
    if canonical_binding_hash(canonical['physical_binding']) != binding['canonical_physical_binding_sha256']:
        raise ExportError('canonical physical_binding JSON hash differs')
    if typed_owner.get('source_owner') != binding['canonical_owner']:
        raise ExportError('typed owner does not point at canonical source owner')
    if typed_owner.get('source_owner_sha256') != binding['canonical_owner_sha256']:
        raise ExportError('typed owner source owner SHA differs')
    if typed_owner.get('physical_condition_sha256') != canonical_sha:
        raise ExportError('typed owner canonical condition differs')

    report_path = Path(binding['typed_conversion_report'])
    receipt_path = Path(binding['typed_execution_receipt'])
    report = load(report_path)
    receipt = load(receipt_path)
    require_hash(report_path, binding['typed_conversion_report_sha256'], 'typed conversion report')
    require_hash(receipt_path, binding['typed_execution_receipt_sha256'], 'typed execution receipt')
    if report.get('conversion_status') != 'completed':
        raise ExportError('typed conversion is not completed')
    if (receipt.get('status'), receipt.get('returncode')) != ('completed', 0):
        raise ExportError('typed receipt is not completed/0')
    scopes = report.get('hash_scopes', {})
    legacy = scopes.get('physical_condition_sha256')
    legacy_scope = scopes.get('physical_condition', {})
    if legacy != binding['legacy_h5_physical_condition_sha256']:
        raise ExportError('legacy H5 scope differs from converter report')
    if legacy_scope.get('schema') != 'legacy-owner-scope.v0':
        raise ExportError('unexpected H5 physical-condition scope')
    if legacy == canonical_sha:
        raise ExportError('legacy and canonical physical hashes were collapsed')
    if legacy_scope.get('physical_case_id') != canonical.get('physical_case_id'):
        raise ExportError('legacy physical case id differs from canonical case')
    if int(report.get('frames', -1)) != int(binding['expected_frames']):
        raise ExportError('typed frame count differs')
    if int(report.get('solver_dimension', {}).get('solver_dimension', -1)) != 3:
        raise ExportError('typed product is not 3-D')
    provenance = report.get('source_provenance', {})
    for key, path_key, sha_key in (
        ('generated_xml', 'generated_xml', 'generated_xml_sha256'),
        ('gencase_receipt', 'actual_gencase_receipt', 'actual_gencase_receipt_sha256'),
    ):
        entry = provenance.get(key, {})
        if entry.get('path') != binding[path_key] or entry.get('sha256') != binding[sha_key]:
            raise ExportError(f'report source provenance mismatch: {key}')
    generated_xml = Path(binding['generated_xml'])
    generated_def = Path(binding['generated_def'])
    require_hash(generated_xml, binding['generated_xml_sha256'], 'generated XML')
    require_hash(generated_def, binding['generated_def_sha256'], 'generated Def')
    source_def = Path(binding['source_definition'])
    require_hash(source_def, binding['source_definition_sha256'], 'source Definition')
    return canonical, typed_owner, report, receipt


def add_item(parent, dataset, source: Path, frame: int, frames: int, particles: int) -> None:
    shape = tuple(int(v) for v in dataset.shape)
    dtype = dataset.dtype
    if dtype.kind not in 'uifb':
        raise ExportError(f'unsupported dataset dtype {dataset.name}: {dtype}')
    dynamic = len(shape) >= 2 and shape[:2] == (frames, particles)
    if not dynamic and shape != (particles,):
        raise ExportError(f'unexpected dataset shape {dataset.name}: {shape}')
    target = parent
    if dynamic:
        dimensions = ' '.join(map(str, shape[2:])) if len(shape) > 2 else str(particles)
        target = ET.SubElement(parent, 'DataItem', ItemType='HyperSlab',
                               Dimensions=dimensions, Type='HyperSlab')
        selection = ET.SubElement(target, 'DataItem', Dimensions=f'3 {len(shape)}',
                                  Format='XML')
        selection.text = '\n' + '\n'.join(' '.join(map(str, row)) for row in (
            [frame] + [0] * (len(shape) - 1),
            [1] * len(shape),
            [1] + list(shape[1:]),
        )) + '\n'
    ET.SubElement(target, 'DataItem', Dimensions=' '.join(map(str, shape)),
                  NumberType='Float' if dtype.kind == 'f' else 'UInt' if dtype.kind in 'ub' else 'Int',
                  Precision=str(dtype.itemsize), Format='HDF').text = f'{source}:{dataset.name}'


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--binding', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    binding = load(args.binding)
    canonical, typed_owner, report, receipt = verify_legacy_aware_binding(binding)
    source = Path(binding['typed_output_h5'])
    require_file(source, 'typed trajectory H5')
    output_dir = args.output_dir
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ExportError(f'refusing to reuse non-empty output directory: {output_dir}')
    output_dir.mkdir(parents=True, exist_ok=True)

    # Scientific H5 bytes are not rehashed here.  The converter's verified
    # output_sha256 is the registered source hash; this job only reads the H5
    # datasets required to publish the temporal XDMF sidecar.
    import h5py
    import numpy as np

    root = ET.Element('Xdmf', Version='2.0')
    domain = ET.SubElement(root, 'Domain')
    collection = ET.SubElement(domain, 'Grid', Name=binding['physical_case_id'],
                               GridType='Collection', CollectionType='Temporal')
    with h5py.File(source, 'r') as h:
        required = {'time', 'position', *FIELDS}
        missing = sorted(required - set(h))
        if missing:
            raise ExportError(f'typed H5 lacks fields: {missing}')
        attr = decode_attr(h.attrs.get('physical_condition_sha256', ''))
        if attr != binding['legacy_h5_physical_condition_sha256']:
            raise ExportError('H5 physical_condition_sha256 is not the report legacy scope')
        frames, particles, dimension = tuple(int(v) for v in h['position'].shape)
        if (frames, particles, dimension) != (int(binding['expected_frames']), int(report['particles']), 3):
            raise ExportError('typed H5 shape differs from metadata report')
        times = np.asarray(h['time'][:], dtype=np.float64)
        if len(times) != frames or not np.isfinite(times).all() or times[0] != 0 or not np.all(np.diff(times) > 0):
            raise ExportError('typed H5 time axis is not finite and strictly increasing')
        if float(times[-1]) < float(binding['physical_window_s'][1]):
            raise ExportError('typed H5 time axis does not cover physical window')
        metadata = {name: {'shape': [int(v) for v in h[name].shape], 'dtype': str(h[name].dtype)}
                    for name in ('time', 'position', *FIELDS)}
        for frame, time in enumerate(times):
            grid = ET.SubElement(collection, 'Grid', Name=f'frame_{frame:04d}', GridType='Uniform')
            ET.SubElement(grid, 'Time', Value=format(float(time), '.17g'))
            ET.SubElement(grid, 'Topology', TopologyType='Polyvertex', NumberOfElements=str(particles))
            geometry = ET.SubElement(grid, 'Geometry', GeometryType='XYZ')
            add_item(geometry, h['position'], source, frame, frames, particles)
            for name in FIELDS:
                attribute = ET.SubElement(grid, 'Attribute', Name=name, Center='Node',
                                          AttributeType='Vector' if name == 'velocity' else 'Scalar')
                add_item(attribute, h[name], source, frame, frames, particles)

    ET.indent(root)
    xdmf = output_dir / 'case.xmf'
    ET.ElementTree(root).write(xdmf, encoding='utf-8', xml_declaration=True)
    xdmf_sha = sha256(xdmf)
    manifest = {
        **binding,
        'schema': 'ds02.stage1.paraview-temporal-product.v1',
        'xdmf': str(xdmf),
        'xdmf_sha256': xdmf_sha,
        'source_h5_sha256': binding['typed_output_sha256'],
        'source_h5_hash_source': 'actual converter report output_sha256; no source-turn H5 rehash',
        'fields': metadata,
        'frames': frames,
        'particles': particles,
        'actual_time_s': times.tolist(),
        'coordinate_frame': report.get('coordinate_frame', 'source_native_coordinates'),
        'source_h5_read_only': True,
        'relative_or_absolute_paths': 'absolute immutable HDF5 reference',
        'identity_and_state': 'All original saved particles and fields, including native fixed/moving/floating/fluid geometry',
        'type_aliases': {'fixed': [0], 'moving': [1], 'floating': [2], 'fluid': [3]},
        'boundary_type_codes': [0],
        'finite_fields': ['mass', 'velocity', 'density', 'pressure'],
        'camera_bounds_policy': 'native023 scans valid native positions across every actual saved XDMF time',
        'visual_status': 'pending actual Root194 ParaView full-animation review',
        'numerical_precision_status': 'not accepted; no Q-N cross-resolution claim',
        'independent_case_increment': 0,
        'count_policy': 'one derived view for one existing physical condition',
    }
    (output_dir / 'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    (output_dir / 'README.txt').write_text(
        'Open case.xmf in ParaView 6.1.1. All original saved frames and native fields are retained.\n'
        'The HDF5 physical-condition attribute uses legacy-owner-scope.v0; canonical physical identity is recorded separately in manifest.json.\n'
        'Visual review and numerical precision/Q-N assessment remain pending.\n', encoding='utf-8')
    print(json.dumps({'xdmf': str(xdmf), 'frames': frames, 'particles': particles}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
