import argparse
import json
from pathlib import Path
import sys

import h5py
import numpy as np

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB / 'scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ds_data02_nvme_convert_v1 as staged
from test_ds_data02_direct_convert import _write_provenance


def test_staged_conversion_matches_all_reference_arrays_and_preserves_source(tmp_path):
    src = _write_provenance(tmp_path)
    kwargs = dict(data_root=src['data'], generated_xml=src['xml'], decoder=src['decoder'],
        solver_log=src['solver_log'], solver_receipt=src['solver_receipt'],
        gencase_receipt=src['gencase_receipt'], owner_metadata=src['owner'], run_partvtk=False)
    reference = tmp_path / 'reference.h5'
    staged.converter.convert_direct(output=reference, report_path=tmp_path/'reference.json', **kwargs)
    before = staged.converter.raw_tree_manifest(src['data'])
    output = tmp_path / 'published.h5'
    args = staged.converter._build_parser().parse_args([
        '--data-root', str(src['data']), '--generated-xml', str(src['xml']),
        '--decoder', str(src['decoder']), '--solver-log', str(src['solver_log']),
        '--solver-receipt', str(src['solver_receipt']), '--gencase-receipt', str(src['gencase_receipt']),
        '--owner-metadata', str(src['owner']), '--skip-partvtk-validation',
        '--output', str(output), '--report', str(tmp_path/'published.json')])
    report = staged.run(args, tmp_path/'scratch', 1024**2)
    with h5py.File(reference) as a, h5py.File(output) as b:
        assert set(a) == set(b)
        for key in a:
            assert np.array_equal(a[key][:], b[key][:], equal_nan=True), key
        assert dict(a.attrs) == dict(b.attrs)
    assert before == staged.converter.raw_tree_manifest(src['data'])
    assert report['output_hdf5'] == str(output)
    assert report['output_sha256'] == staged.converter.sha256_file(output)
    assert list((tmp_path/'scratch').iterdir()) == []
