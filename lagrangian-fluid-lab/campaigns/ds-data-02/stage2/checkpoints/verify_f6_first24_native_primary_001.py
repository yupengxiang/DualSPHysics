"""Verify real F6 native exclusions against prior complete typed scans, no H5 read."""
import csv
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

STAGE = Path(__file__).resolve().parents[1]
DATA = Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1048576), b''):
            h.update(b)
    return h.hexdigest()


def load(path):
    return json.loads(Path(path).read_text())


def table(path, delimiter=','):
    lines = [l for l in Path(path).read_text().splitlines() if l.strip() and not l.strip().startswith(('#', '//'))]
    return list(csv.DictReader(lines, delimiter=delimiter))


def main():
    current = load(STAGE / 'CURRENT336.json')
    ledger = load(DATA / 'runtime/resource-ledger.json')
    charges = {r['id']: r for r in ledger['charges']}
    checked, results, causes = {}, [], Counter()

    def bind(path, expected):
        path = str(Path(path).resolve())
        assert Path(path).suffix.lower() not in {'.h5', '.hdf5'}
        if path in checked:
            assert checked[path] == expected
        else:
            assert sha(path) == expected, path
            checked[path] = expected

    def receipt(path, request):
        r = load(path)
        assert r['status'] == 'completed' and r['returncode'] == 0
        expected = {str(Path(k).resolve()): v for k, v in request['input_sha256'].items()}
        assert r['input_hashes_at_launch'] == r['input_hashes_after_run'] == expected
        for p, digest in expected.items():
            bind(p, digest)
        size = sum(p.stat().st_size for p in path.parent.rglob('*') if p.is_file())
        ident = '/'.join((request['family_id'], request['case_id'], request['attempt_id']))
        assert r['terminal_storage_guard']['status'] == 'passed'
        assert size == r['bytes'] == r['terminal_storage_guard']['actual_bytes'] == charges[ident]['new_storage_bytes']
        assert not any(v['id'] == ident for v in ledger['reservations'])
        return r, size

    for request_path in sorted((STAGE / 'requests/omission-forensics-f6-join-v3').glob('*.json')):
        request = load(request_path)
        index = int(request_path.name.split('-')[2])
        row = current['cases'][index]
        assert row['family_id'] == 'F6'
        root = DATA / 'families/F6' / request['case_id'] / request['attempt_id']
        receipt_path = root / 'execution-receipt.json'
        r, size = receipt(receipt_path, request)
        assert sha(request_path) == r['request_sha256']
        report_path = root / 'omission-forensics.json'
        report = load(report_path)
        assert report['physical_case_id'] == row['physical_case_id']
        assert report['trajectory']['path'] == row['trajectory']['path']
        assert report['trajectory']['sha256'] == row['trajectory']['producer_declared_sha256']
        stat = Path(row['trajectory']['path']).stat()
        assert stat.st_size == report['trajectory']['bytes'] == row['trajectory']['bytes']
        assert stat.st_mtime_ns == report['trajectory']['mtime_ns'] == row['trajectory']['mtime_ns']
        scan = load(report['scan']['path'])
        assert scan['physical_case_id'] == row['physical_case_id']
        assert scan['trajectory'] == row['trajectory']['path'] and scan['frames'] == row['frames']
        assert report['scan_completion']['trajectory_sha256_launch'] == report['scan_completion']['trajectory_sha256_end'] == row['trajectory']['producer_declared_sha256']
        native = report['native_decode']
        assert native['command'][2] == row['raw_root']['path']
        decode_request_path = STAGE / 'requests/omission-forensics-f6-v3' / f'decode-F6-{index}-v3.json'
        decode_receipt_path = Path(native['receipt']['path'])
        dr, decode_size = receipt(decode_receipt_path, load(decode_request_path))
        assert sha(decode_request_path) == dr['request_sha256'] and dr['command'] == native['command']
        partout_path = Path(native['partout']['path'])
        natives = table(partout_path)
        by_id = {int(n['Idp']): n for n in natives}
        assert len(by_id) == len(natives)
        missing = {int(n['idp']): n for n in scan['missing_id_records'] if n['type_code'] == 3}
        assert all(n['zone'] == 0 for n in missing.values())
        assert set(missing) == set(by_id)
        excluded = {int(n['idp']): n for n in report['excluded_particles']}
        assert set(excluded) == set(by_id) and report['typed_identity']['missing_fluid_count'] == len(missing)
        xml = ET.parse(row['source_bindings']['generated_xml']['path'])
        params = {p.attrib['key']: p.attrib['value'] for p in xml.findall('.//parameter')}
        lo, hi = float(params['RhopOutMin']), float(params['RhopOutMax'])
        local = Counter()
        for ident, n in by_id.items():
            e, m = excluded[ident], missing[ident]
            code = int(n['Motive'])
            assert code == e['native_motive_code']
            assert int(n['PartOut']) == m['first_missing_frame'] == e['first_missing_frame']
            assert e['first_missing_bracket_s'] == m['first_missing_bracket_s']
            assert e['initial_mass_kg'] == m['initial_mass_kg']
            assert e['physical_fate'] == 'UNKNOWN' and e['legal_outflow_proven'] is False
            assert [float(n[f'Pos.{axis} [m]']) for axis in ('x', 'y', 'z')] == e['partvtkout_position_m']
            rho = float(n['Rhop [kg/m^3]'])
            assert rho == e['partvtkout_density_kg_m3']
            if code == 2:
                assert (rho < lo or rho > hi) and e['native_exit_cause'] == 'NUMERICAL_DENSITY_EXCLUSION'
            elif code == 1:
                assert e['native_exit_cause'] == 'NUMERICAL_POSITION_EXCLUSION'
            else:
                assert e['native_exit_cause'] not in {'NUMERICAL_DENSITY_EXCLUSION', 'NUMERICAL_POSITION_EXCLUSION'}
            local[e['native_exit_cause']] += 1
        times = [n for n in table(native['runparts']['path'], ';') if str(n.get('Part', '')).isdigit()]
        assert len(times) == row['frames'] and [float(n['TimeStep [s]']) for n in times] == scan['time_s']
        assert native['max_saved_time_delta_s'] == 0
        for name in ('NpOut', 'NpOutPos', 'NpOutRho', 'NpOutMov'):
            # These fields count exclusions in each saved window, not cumulative final totals.
            assert sum(int(n[name].replace(',', '')) for n in times) == native['runparts_totals'][name]
        assert sum(n['initial_mass_kg'] for n in missing.values()) == report['typed_identity']['missing_fluid_initial_mass_kg']
        causes.update(local)
        results.append({'current_index': index, 'physical_case_id': row['physical_case_id'],
                        'request': {'path': str(request_path), 'sha256': sha(request_path)},
                        'receipt': {'path': str(receipt_path), 'sha256': sha(receipt_path)},
                        'report': {'path': str(report_path), 'sha256': sha(report_path)},
                        'csv': {'path': str(partout_path), 'sha256': sha(partout_path)},
                        'native_and_typed_missing_IDs_exact': True, 'native_and_typed_first_gap_frame_exact': True,
                        'all_saved_times_exact': True, 'fluid_omitted_count': len(missing),
                        'fluid_omitted_initial_mass_kg': report['typed_identity']['missing_fluid_initial_mass_kg'],
                        'causes': dict(local), 'join_terminal_bytes': size, 'decode_terminal_bytes': decode_size})
    for path, digest in checked.items():
        assert sha(path) == digest
    assert len(results) == 24
    proof = {'schema': 'ds02.stage2.f6-first24-native-independent-verification.v1',
             'observed_at_utc': datetime.now(timezone.utc).isoformat(),
             'status': 'PASS_SCOPED_NATIVE_EXCLUSION_ID_TIME_AND_MASS_LEDGER',
             'current_catalog_sha256': sha(STAGE / 'CURRENT336.json'), 'cases': len(results),
             'excluded_fluid_ids': sum(r['fluid_omitted_count'] for r in results), 'causes': dict(causes),
             'unique_registered_inputs_independently_prepost_hashed': len(checked), 'input_sha256': checked,
             'results': results,
             'scope': 'Actual official native CSV/RunPARTs/XML and CURRENT-bound prior scans/decoder/join receipts; H5 stat only. Omitted initial masses inherited from guard-bound full scans; no independent perMK H5 reduction.',
             'remaining': 'F6 24 newly verified cases plus2 prior indexed native joins; remaining22 F6 joins not credited by this snapshot. F2 prior48/F4prior22, global union96 pending separate membership union proof.',
             'unknown': ['Physical fate and dynamical impact remain UNKNOWN; no legal spill proof.',
                         'Historical converter complete imported code closure and independent perMK static H5 denominator remain incomplete.'],
             'credit': {'QI_dynamics': 'UNKNOWN', 'QN': 'UNKNOWN', 'QE': 'UNKNOWN'}}
    out = STAGE / 'checkpoints/F6_FIRST24_NATIVE_INDEPENDENT_VERIFICATION_001.json'
    with out.open('x') as stream:
        json.dump(proof, stream, indent=2)
        stream.write('\n')
    print(json.dumps({'cases': len(results), 'native_excluded_fluid_ids': proof['excluded_fluid_ids'],
                      'causes': dict(causes), 'unique_inputs_prepost': len(checked)}))


if __name__ == '__main__':
    main()
