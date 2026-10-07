"""Verify portable metadata and code; never open solver/trajectory payloads."""
from __future__ import annotations

from collections import Counter
import hashlib
import itertools
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def read(name):
    return json.loads((ROOT / name).read_text())


def local(name):
    p = ROOT / name
    assert p.resolve().is_relative_to(ROOT), name
    assert p.is_file() and not p.is_symlink(), name
    return p


def main():
    catalog = read('CASES_336.json')['cases']
    assert len(catalog) == 336
    identity = [(r['family_id'], r['physical_case_id']) for r in catalog]
    assert len(set(identity)) == 336
    assert Counter(r['family_id'] for r in catalog) == {f'F{i}': 48 for i in range(1, 8)}
    comparisons = 0
    for i in range(1, 8):
        rows = [r for r in catalog if r['family_id'] == f'F{i}']
        first8 = {r['physical_case_id'] for r in rows if r['first8_member']}
        first24 = {r['physical_case_id'] for r in rows if r['first24_member']}
        final48 = {r['physical_case_id'] for r in rows if r['final48_member']}
        assert (len(first8), len(first24), len(final48)) == (8, 24, 48)
        assert first8 < first24 < final48
        for a, b in itertools.combinations(rows, 2):
            av = a['known_numeric_physical_parameters']
            bv = b['known_numeric_physical_parameters']
            assert any(isinstance(av[k], (int, float)) and not isinstance(av[k], bool)
                       and isinstance(bv[k], (int, float)) and not isinstance(bv[k], bool)
                       and av[k] != bv[k] for k in av.keys() & bv.keys()), (a['physical_case_id'], b['physical_case_id'])
            comparisons += 1
    for row in catalog:
        assert row['Q_N'] == row['Q_E'] == 0
        assert row['precision_status'] == '视觉检查通过、数值精度未验收'
        assert row['frames'] > 1 and row['particles'] > 0
        assert row['actual_time_window_s'][0] == 0 and row['actual_time_window_s'][1] > 0
        for key in ['portable_manifest', 'portable_visual_decision']:
            local(row[key])
        local(row['physical_proof']['package_path'])
        for report in row['portable_full_animation_reports']:
            local(report)

    evidence = read('EVIDENCE_INDEX.json')
    checked = 0
    for item in evidence['files']:
        if not item.get('packaged'):
            continue
        p = local(item['package_path'])
        assert p.suffix.lower() in {'.json', '.md', '.py', '.xml'}, p
        assert p.stat().st_size == item['bytes']
        sha = hashlib.sha256(p.read_bytes()).hexdigest()
        assert sha == item['packaged_metadata_sha256']
        for expected in item['source_declared_sha256_values']:
            assert sha == expected, item['source_path']
        checked += 1
    delivery = read(evidence['seed_roles']['delivery336'][0])['cases']
    assert {(r['family_id'], r['physical_case_id']) for r in delivery} == set(identity)
    for original, packaged in zip(delivery, catalog):
        assert (original['family_id'], original['physical_case_id']) == (packaged['family_id'], packaged['physical_case_id'])
        assert original['primary_delivery']['frames'] == packaged['frames']
        assert original['primary_delivery']['actual_time_window_s'] == packaged['actual_time_window_s']

    recipes = read('NUMERICAL_RECIPE_INDEX.json')['cases']
    assert {(r['family_id'], r['physical_case_id']) for r in recipes} == set(identity)
    for recipe in recipes:
        local(recipe['portable_native_receipt'])
        assert recipe['XML_candidates']
        for xml in recipe['XML_candidates']:
            local(xml['package_path'])
            assert xml['current_matches_launch'] is True
            assert xml['current_matches_after_run'] in {True, None}

    source_index = read('SOURCE_INDEX.json')
    checked_sources = 0
    if (ROOT / 'source').exists():
        for item in source_index['files']:
            p = local(item['package_path'])
            assert p.suffix == '.py'
            assert hashlib.sha256(p.read_bytes()).hexdigest() == item['sha256']
            checked_sources += 1
    for preview in read('PREVIEW_INDEX.json')['cases']:
        assert (preview['family_id'], preview['physical_case_id']) in set(identity)
        for item in preview['files']:
            p = local(item['package_path'])
            assert p.suffix == '.png' and p.stat().st_size == item['bytes']
            producer_sha = item['source_reference'].get('sha256')
            if producer_sha:
                assert hashlib.sha256(p.read_bytes()).hexdigest() == producer_sha

    manifest_checks = 0
    if (ROOT / 'PACKAGE_MANIFEST.json').exists():
        for item in read('PACKAGE_MANIFEST.json')['files']:
            p = local(item['path'])
            assert p.suffix.lower() not in {'.h5', '.hdf5', '.bi4', '.ibi4', '.csv', '.dat', '.vtk', '.log', '.jsonl', '.xmf'}
            assert hashlib.sha256(p.read_bytes()).hexdigest() == item['sha256']
            manifest_checks += 1
    result = {'result': 'pass', 'cases': 336, 'per_family': 48, 'nested_8_24_48': 'pass',
              'known_numeric_pair_comparisons': comparisons, 'metadata_files_verified': checked,
              'source_files_verified': checked_sources, 'actual_launch_recipe_rows': len(recipes),
              'package_manifest_files_verified': manifest_checks, 'scientific_array_files_opened': 0,
              'new_visual_acceptances': 0, 'new_Q_N_Q_E_credit': 0,
              'limitations': 'Metadata/copy/identity integrity checks only; no independent solver, convergence, trajectory or physical accuracy verification.'}
    (ROOT / 'PACKAGE_VALIDATION.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
