"""Verify v35 identity and bounded V27 source rebinding; no split approval."""
from pathlib import Path

HERE = Path(__file__).resolve().parent
S = HERE.parents[1]
BASE = HERE / 'verify_v34_v1.py'
code = BASE.read_text()
# Reuse the frozen identity/card/proof-file verifier; change only the output
# namespace and the explicit limit statement now that an index is supplied.
replacements = {
    "v34-namespace330-v6-root307-actual335-primary-001": "v35-namespace330-v6-root307-actual335-physical-policy-primary-001",
    "root-v34-canonical-catalog-independent-verification.v1": "root-v35-canonical-catalog-independent-verification.v2",
    "root-v34-independent-metadata-verification-v1.json": "root-v35-independent-metadata-verification-v2.json",
    "'physical_split_index_bound': False": "'physical_split_index_bound': True",
    "No V27 artifact was supplied; all physical grouping stays unassigned.": "V27 source rebinding and group membership are verified, but all 336 groups remain unsafe; no physical-equivalence or split approval.",
}
for old, new in replacements.items():
    assert code.count(old) == 1, old
    code = code.replace(old, new)
context = {'__file__': str(BASE), '__name__': 'root_v35_frozen_identity_verifier'}
exec(compile(code, str(BASE), 'exec'), context)
load, sha, canonical = (context[key] for key in ['load', 'sha', 'canonical'])


def main():
    index = load(S / 'lineage/v27-effective-condition-directory-root307-001/EFFECTIVE_PHYSICAL_UNION_INDEX_V27.json')
    assert canonical(index) == index['sha256']
    source = load(S / 'lineage/v27-effective-condition-directory-root307-001/effective-condition-metadata-request-v27.json')
    assert canonical(source) == source['sha256']
    folder = S / 'lineage/v27-effective-condition-primary-rebound-root307-001'
    request = load(folder / 'effective-condition-metadata-request-v27-primary-rebound.json')
    sidecar = load(folder / 'effective-condition-v27-primary-rebinding-sidecar.json')
    assert canonical(request) == request['sha256'] and canonical(sidecar) == sidecar['sha256']
    assert request['source_rebinding_sidecar']['sha256'] == sidecar['sha256']
    assert sha(sidecar['source_request']['path']) == sidecar['source_request']['file_sha256']
    detail_refs = request['source_inputs']['v26_case_details']
    assert len(detail_refs) == sidecar['case_detail_count'] == 336
    current = load(S / 'CURRENT336.json')
    for i, (ref, row, expected) in enumerate(zip(detail_refs, index['cases'], current['cases'])):
        path = Path(ref['path'])
        assert path.is_relative_to(S / 'lineage/v26-effective-condition-directory/cases')
        assert sha(path) == ref['file_sha256']
        detail = load(path)
        assert canonical(detail) == detail['sha256'] == ref['sha256'] == row['source_case_sha256_v26']
        assert detail['current_index'] == row['current_index'] == i
        assert detail['physical_case_id'] == row['physical_case_id'] == expected['physical_case_id']
        assert row['family_id'] == expected['family_id']
    catalog = load(context['OUT'] / 'namespace330-scoped-v6-root307-catalog.json')
    groups = {group['group_id']: group for group in index['physical_union_groups']}
    assert len(groups) == len(index['physical_union_groups']) == 336
    for i, (row, record) in enumerate(zip(index['cases'], catalog['cases'])):
        group = groups[row['physical_union_group_id_v27']]
        assert group['current_indices'] == [i] and group['split_safe'] is False
        assert record['split']['physical_union_group_id_v27'] == group['group_id']
        assert record['split']['split_safe'] is False
        assert all(axis in row['forbidden_cross_split_dimensions'] for axis in ['resolution', 'window', 'recovery'])
    # These are bookkeeping checks over declared keys. Singleton unsafe
    # groups cannot establish equivalence across resolutions or time windows.
    audit = load(S / 'lineage/v29-effective-condition-policy-root307-primary-001/effective-condition-leakage-audit-v29.json')
    assert canonical(audit) == audit['sha256']
    assert audit['summary']['case_count'] == audit['summary']['unsafe_group_count'] == 336
    assert audit['summary']['unknown_physical_case_count'] == 150
    context['main']()


if __name__ == '__main__':
    main()
