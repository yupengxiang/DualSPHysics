"""Independent bounded metadata verification of the immutable v34 catalog.

No production arrays are opened or hashed. This verifies identity/provenance
and explicit unknowns, not scientific fields, labels, or replay qualification.
"""
from pathlib import Path
import datetime
import hashlib
import json

S = Path(__file__).resolve().parents[2]
OUT = S / 'lineage/v34-namespace330-v6-root307-actual335-primary-001'
FORBIDDEN = {'.h5', '.hdf5', '.bi4', '.obi4', '.ibi4', '.vtk', '.jsonl'}
verified = {}


def sha(path):
    path = Path(path).absolute()
    assert path.is_file() and not path.is_symlink()
    assert path.suffix.lower() not in FORBIDDEN
    assert path.stat().st_size <= 10485760
    before = path.stat()
    value = hashlib.sha256(path.read_bytes()).hexdigest()
    after = path.stat()
    assert (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
    verified[str(path)] = value
    return value


def load(path):
    sha(path)
    return json.loads(Path(path).read_text())


def canonical(v):
    return hashlib.sha256(json.dumps({k: x for k, x in v.items() if k != 'sha256'}, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def main():
    catalog_path = OUT / 'namespace330-scoped-v6-root307-catalog.json'
    request_path = OUT / 'namespace330-scoped-v6-root307-source-request.json'
    c, q = load(catalog_path), load(request_path)
    assert c['sha256'] == canonical(c) and q['sha256'] == canonical(q)
    assert q['artifacts']['catalog']['file_sha256'] == sha(catalog_path)
    assert q['artifacts']['catalog']['canonical_sha256'] == c['sha256']
    assert Path(q['artifacts']['catalog']['path']) == catalog_path
    for ref in c['source_inputs']:
        assert sha(ref['path']) == ref['file_sha256']
    current = load(c['current_binding']['path'])
    assert sha(c['current_binding']['path']) == 'df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b'
    assert [(x['physical_case_id'], x['family_id']) for x in current['cases']] == [(x['physical_case_id'], x['family_id']) for x in c['cases']]
    aliases = []
    for row in c['cases']:
        assert row['quality']['QI'] == row['quality']['QN'] == row['quality']['QE'] == 'UNKNOWN'
        assert row['split']['split_safe'] is False
        if row['canonical_case_id'] is None:
            aliases.append(row['physical_case_id'])
            assert row['identity']['identity_credit'] is False and row['identity']['source_join_credit'] is False
            assert row['lifecycle']['status'] == 'HISTORICAL_ALIAS_UNRESOLVED'
            assert not row['lifecycle']['producer_refs']
        else:
            assert row['canonical_case_id'] == row['physical_case_id']
            assert row['identity']['identity_credit'] is True
            assert row['lifecycle']['status'] == 'ACTUAL_SAVED_MASK_COMPLETED'
            for ref in row['lifecycle']['producer_refs']:
                assert sha(ref['path']) == ref['file_sha256'], ref
    assert aliases == ['F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090']
    assert sum(row['lifecycle']['failed_history_count'] for row in c['cases']) == 8
    for ref in q['artifacts']['family_cards']:
        card = load(ref['path'])
        assert sha(ref['path']) == ref['file_sha256']
        assert canonical(card) == card['sha256'] == ref['canonical_sha256']
        rows = [row for row in c['cases'] if row['family_id'] == ref['family_id']]
        assert card['canonical_case_ids'] == [row['canonical_case_id'] for row in rows if row['canonical_case_id'] is not None]
        assert card['historical_reference_case_ids'] == [row['physical_case_id'] for row in rows if row['canonical_case_id'] is None]
        assert len(card['case_refs']) == card['case_count'] == 48
        for item, row in zip(card['case_refs'], rows):
            assert item['canonical_case_id'] == row['canonical_case_id']
            assert item['physical_case_id_lookup'] == row['physical_case_id']
            assert item['producer_id'] == row['lifecycle']['producer_id']
            assert item['split_safe'] is False and item['quality'] == {'QI': 'UNKNOWN', 'QN': 'UNKNOWN', 'QE': 'UNKNOWN'}
    result = {'schema': 'ds02.stage2.root-v34-canonical-catalog-independent-verification.v1',
              'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'status': 'VERIFIED_METADATA_IDENTITY_AND_ALIAS_PARTITION_ONLY',
              'catalog': {'path': str(catalog_path), 'sha256': sha(catalog_path)},
              'request': {'path': str(request_path), 'sha256': sha(request_path)},
              'canonical_cases': 335, 'historical_aliases': aliases, 'failed_history_entries': 8,
              'family_cards': 7, 'verified_bounded_metadata_files': verified,
              'scientific_qualification': {'QI': 'UNKNOWN', 'QN': 'UNKNOWN', 'QE': 'UNKNOWN'},
              'physical_split_index_bound': False, 'split_safe': False,
              'production_payload_opened_or_hashed': False, 'goal_complete': False,
              'limits': ['No V27 artifact was supplied; all physical grouping stays unassigned.',
                         'Producer metadata file hashes are verified; scientific payloads and full replay remain pending.']}
    target = OUT / 'root-v34-independent-metadata-verification-v1.json'
    assert not target.exists()
    target.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'path': str(target), 'sha256': sha(target), 'verified_metadata_files': len(verified), 'canonical_cases': 335, 'aliases': 1, 'scientific_credit': 0}))


if __name__ == '__main__':
    main()
