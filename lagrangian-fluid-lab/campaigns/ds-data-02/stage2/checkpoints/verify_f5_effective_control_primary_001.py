"""Independent small-source checks for two actual F5 controls; no HDF5 read."""
import csv
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
import xml.etree.ElementTree as ET


STAGE2 = Path(__file__).resolve().parents[1]


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            digest.update(block)
    return digest.hexdigest()


def main():
    report_path = STAGE2 / 'reference/stage2_f5_effective_condition_audit_v2.json'
    report = json.loads(report_path.read_text())
    current = report['current_catalog']
    assert sha(current['path']) == current['sha256']
    catalog = json.loads(Path(current['path']).read_text())
    checked = {}

    def bind(path, expected):
        path = str(Path(path).resolve())
        assert Path(path).suffix.lower() not in {'.h5', '.hdf5', '.bi4', '.obi4'}
        actual = sha(path)
        assert actual == expected, path
        if path in checked:
            assert checked[path] == actual
        checked[path] = actual

    def walk(value):
        if isinstance(value, dict):
            if isinstance(value.get('path'), str) and value.get('sha256'):
                bind(value['path'], value['sha256'])
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(report['current_catalog'])
    walk(report['review_matrix'])
    results = []
    for result in report['results']:
        row = next(case for case in catalog['cases'] if case['physical_case_id'] == result['physical_case_id'])
        assert row['family_id'] == 'F5'
        assert row['runtime_case_alias'] == result['current_runtime_case_alias']
        walk(result)
        for role in ('generated_xml', 'solver_receipt', 'gencase_receipt'):
            node = row['source_bindings'][role]
            bind(node['path'], node['recomputed_sha256'])
        checks = result['source_input_checks']
        for entry in checks['definition_inputs'] + checks['motion_inputs']:
            bind(entry['path'], entry['receipt_sha256'])
        recipe = result['numerical_recipe']
        xml_path = Path(recipe['xml_controls']['file']['path'])
        assert str(xml_path) == row['source_bindings']['generated_xml']['path']
        tree = ET.parse(xml_path)
        params = {p.attrib['key']: p.attrib['value'] for p in tree.findall('.//parameter')}
        cfls = {float(node.attrib['value']) for node in tree.findall('.//cflnumber')}
        assert cfls == {0.2}
        assert float(params['TimeMax']) == 26
        assert float(params['TimeOut']) == 0.02
        receipt_path = Path(row['source_bindings']['solver_receipt']['path'])
        receipt = json.loads(receipt_path.read_text())
        assert receipt['status'] == 'completed' and receipt['returncode'] == 0
        command = receipt['command']
        assert command == recipe['effective_controls']['command']
        assert '-tmax:16' in command and '-tout:0.02' in command
        assert not any(flag.lower().startswith('-cfl:') for flag in command)
        motion = result['physical_condition']['motion_input']
        motion_path = Path(motion['file']['path'])
        refs = [n.attrib['name'] for n in tree.findall('.//file') if n.attrib.get('name', '').endswith('.dat')]
        assert any((xml_path.parent / name).resolve() == motion_path.resolve() for name in refs)
        points = []
        for line in motion_path.read_text().splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(('#', '//')):
                continue
            try:
                values = [float(v) for v in stripped.split()]
            except ValueError:
                continue
            assert len(values) == 2 and all(math.isfinite(v) for v in values)
            points.append(values)
        assert len(points) == motion['row_count'] == 641
        assert points[0][0] == motion['time_first_s'] == 0
        assert points[-1][0] == motion['time_last_s']
        assert all(b[0] > a[0] for a, b in zip(points, points[1:]))
        assert all(p[1] == 0 for p in points[-3:])
        runparts_path = Path(receipt['output_root']) / 'solver_output/RunPARTs.csv'
        assert str(runparts_path) == result['runparts']['file']['path']
        lines = [line for line in runparts_path.read_text().splitlines() if line and not line.startswith(('#', '//'))]
        reader = csv.DictReader(lines, delimiter=';')
        records = [r for r in reader if str(r.get('Part', '')).isdigit()]
        times = [float(r['TimeStep [s]']) for r in records]
        assert len(records) == result['runparts']['row_count'] == row['frames']
        assert times[0] == 0 and all(b > a for a, b in zip(times, times[1:]))
        assert times[-1] == row['actual_time_window_s'][1] == result['runparts']['time_last_s']
        assert sum(int(r['Steps'].replace(',', '')) for r in records) == result['runparts']['steps_sum']
        assert all(int(r['DTsMin'].replace(',', '')) == 0 for r in records)
        runout_path = Path(receipt['output_root']) / 'solver_output/Run.out'
        assert runout_path.is_file()
        checked[str(runout_path.resolve())] = sha(runout_path)
        results.append({
            'sentinel_id': result['sentinel_id'], 'physical_case_id': row['physical_case_id'],
            'xml_tmax_s': 26, 'effective_cli_tmax_s': 16, 'effective_cfl': 0.2,
            'saved_frames': len(records), 'actual_last_time_s': times[-1],
            'motion_last_time_s': points[-1][0], 'motion_last_three_values_zero': True,
            'saved_window_min_dt_s': min(float(r['DtMin [s]']) for r in records[1:]),
            'saved_window_max_dt_s': max(float(r['DtMax [s]']) for r in records[1:]),
            'dt_min_counter_total': 0,
        })
    for path, expected in checked.items():
        assert sha(path) == expected
    proof = {
        'schema': 'ds02.stage2.f5-effective-control-independent-verification.v1',
        'observed_at_utc': datetime.now(timezone.utc).isoformat(),
        'status': 'PASS_SCOPED_SOURCE_CONTROL_AND_SAVED_TIME',
        'producer_report': {'path': str(report_path), 'sha256': sha(report_path)},
        'current_catalog_sha256': current['sha256'],
        'independent_prepost_small_input_sha256': checked, 'results': results,
        'findings': ['Producer v2 physical_condition.payload still includes dp_m; forward correction required before cross-resolution grouping.'],
        'unknown_scope': ['No HDF5/raw payload read; no observer/convergence/scientific qualification.',
                          'RunPARTs dt summaries and counters are saved-window evidence, not a full actual step/clamp history.',
                          'Zero-ending short motion curve does not by itself prove solver motion semantics after the curve ends.'],
        'credit': {'QI': 'UNKNOWN', 'QN': 'UNKNOWN', 'QE': 'UNKNOWN'},
    }
    out = STAGE2 / 'checkpoints/F5_EFFECTIVE_CONTROL_INDEPENDENT_VERIFICATION_001.json'
    with out.open('x') as stream:
        json.dump(proof, stream, indent=2, ensure_ascii=False)
        stream.write('\n')
    print(json.dumps({'status': proof['status'], 'cases': len(results), 'small_files_verified': len(checked)}))


if __name__ == '__main__':
    main()
