"""Resolve frozen Stage1 case manifests through exact XMF references, without globs."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import h5py


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def resolve_case(case, review):
    manifest_path = review / case['portable_manifest']
    manifest = json.loads(manifest_path.read_text())
    if manifest['physical_case_id'] != case['physical_case_id']:
        raise ValueError('Manifest physical case differs from catalog')
    xmf = Path(case['original_server_XMF']['path'])
    if sha256(xmf) != case['original_server_XMF']['sha256']:
        raise ValueError('Frozen XMF hash changed')
    references = {str((xmf.parent / item.text.strip().split(':', 1)[0]).resolve())
                  for item in ET.parse(xmf).iter('DataItem') if item.attrib.get('Format') == 'HDF'}
    if len(references) != 1:
        raise ValueError('Expected exactly one immutable HDF5 state source')
    trajectory = Path(next(iter(references)))
    declared = manifest.get('trajectory_h5', manifest.get('source_h5'))
    if declared and Path(declared).resolve() != trajectory:
        raise ValueError('Manifest and XMF disagree on source state')
    expected = manifest['source_h5_sha256']
    if not isinstance(expected, str) or len(expected) != 64:
        raise ValueError('Missing producer-declared HDF5 digest')
    stat = trajectory.stat()
    conversion_path = trajectory.parent / 'conversion-report.json'
    conversion = json.loads(conversion_path.read_text()) if conversion_path.is_file() else {}
    source = conversion.get('source_provenance', {})
    with h5py.File(trajectory, 'r') as h:
        times = h['time'][:]
        if len(times) != case['frames'] or [float(times[0]), float(times[-1])] != case['actual_time_window_s']:
            raise ValueError('Actual HDF5 timeline differs from frozen catalog')
        if h['position'].shape != (case['frames'], case['particles'], 3):
            raise ValueError('HDF5 state shape differs from frozen catalog')
        header = dict(fields={k: dict(shape=list(v.shape), dtype=str(v.dtype), chunks=v.chunks)
                              for k, v in h.items() if isinstance(v, h5py.Dataset)},
                      units=json.loads(h.attrs['units_json']) if 'units_json' in h.attrs else None,
                      identity_key=str(h.attrs.get('identity_key', 'unknown')),
                      coordinate_frame=str(h.attrs.get('coordinate_frame', 'unknown')),
                      conversion_complete=bool(h.attrs.get('conversion_complete', False)))
    bindings = {}
    for key in ('generated_xml', 'gencase_receipt', 'solver_receipt', 'owner_metadata'):
        binding = source.get(key)
        if isinstance(binding, dict) and binding.get('path'):
            p = Path(binding['path'])
            bindings[key] = dict(binding, accessible=p.is_file(),
                                 recomputed_sha256=sha256(p) if p.is_file() else None)
    raw_root = source.get('data_root')
    return dict(family_id=case['family_id'], physical_case_id=case['physical_case_id'],
                runtime_case_alias=case['runtime_case_alias'], frames=case['frames'],
                particles=case['particles'], actual_time_window_s=case['actual_time_window_s'],
                known_numeric_physical_parameters=case['known_numeric_physical_parameters'],
                manifest=dict(path=str(manifest_path), recomputed_sha256=sha256(manifest_path)),
                xmf=dict(path=str(xmf), recomputed_sha256=sha256(xmf)),
                trajectory=dict(path=str(trajectory), producer_declared_sha256=expected,
                                recomputed_sha256=None, bytes=stat.st_size, mtime_ns=stat.st_mtime_ns),
                conversion_report=dict(path=str(conversion_path), recomputed_sha256=sha256(conversion_path))
                                  if conversion_path.is_file() else None,
                source_bindings=bindings,
                raw_root=dict(path=raw_root, accessible=Path(raw_root).is_dir()) if raw_root else None,
                header=header, scientific_scan_status='NOT_SCANNED',
                quality=dict(visual='STAGE1_PRESERVED', QI='NOT_ASSESSED', QN='NOT_ASSESSED', QE='NOT_ASSESSED'))


def build(review):
    cases_path = review / 'CASES_336.json'
    cases = json.loads(cases_path.read_text())['cases']
    if len(cases) != 336 or len({r['physical_case_id'] for r in cases}) != 336:
        raise ValueError('Frozen physical catalog must contain 336 unique cases')
    rows = []
    for case in cases:
        try:
            rows.append(resolve_case(case, review))
        except (OSError, ValueError, KeyError) as error:
            rows.append(dict(family_id=case['family_id'], physical_case_id=case['physical_case_id'],
                             scientific_scan_status='EVIDENCE_UNKNOWN', error=str(error)))
    counts = Counter(r['family_id'] for r in rows)
    if counts != Counter({f'F{i}': 48 for i in range(1, 8)}):
        raise ValueError('Frozen family counts differ')
    return dict(schema='ds02.stage2.current336.v1', source_catalog=str(cases_path),
                source_catalog_sha256=sha256(cases_path), cases=rows,
                scope='Actual HDF5 headers, exact XMF bindings, and small source digests only; no full scientific scan or QN/QE.',
                total_hdf5_bytes=sum(r.get('trajectory', {}).get('bytes', 0) for r in rows),
                unresolved=sum(r['scientific_scan_status'] == 'EVIDENCE_UNKNOWN' for r in rows))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = build(args.review.resolve())
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write('\n')
    print(json.dumps(dict(cases=len(result['cases']), unresolved=result['unresolved'], bytes=result['total_hdf5_bytes'])))


if __name__ == '__main__':
    main()
