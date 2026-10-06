#!/usr/bin/env python3
"""Run the real fresh157 wrapper against a toy converter and toy payload.

The toy uses a .toy byte stream, so this test never imports h5py/numpy and never
opens a science input.  It still exercises the wrapper's real staging, report
fixed-point, verified-copy call, Home partial publication, and BaseException
cleanup paths.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import shutil
import sys
import tempfile
import types
from pathlib import Path


INTEGRATION_SCRIPTS = Path(
    '/home/jade/.codex/worktrees/ds-data-02-integration/'
    'DualSPHysics/lagrangian-fluid-lab/scripts'
)
PACKAGE_SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(INTEGRATION_SCRIPTS))
sys.path.insert(0, str(PACKAGE_SCRIPTS))
from home_publish_math import HomePublishGuardError

# Import the real wrapper with a fake direct-converter module.  The fake is only
# a producer for this toy; the wrapper implementation itself is not replaced.
fake_converter = types.ModuleType('ds_data02_direct_convert')
fake_converter.tempfile = tempfile
fake_converter.decode_frame = lambda *args, **kwargs: None
fake_converter._run_partvtk_frame = lambda *args, **kwargs: None

def fake_direct_parser():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--generated-xml', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--decoder', type=Path, required=True)
    parser.add_argument('--partvtk', type=Path)
    parser.add_argument('--validation-dir', type=Path)
    parser.add_argument('--solver-log', type=Path)
    parser.add_argument('--solver-receipt', type=Path, required=True)
    parser.add_argument('--gencase-receipt', type=Path, required=True)
    parser.add_argument('--owner-metadata', type=Path, required=True)
    parser.add_argument('--compare-hdf5', type=Path)
    parser.add_argument('--particle-chunk', type=int, default=65536)
    parser.add_argument('--skip-partvtk-validation', action='store_true')
    parser.add_argument('--keep-validation-csv', action='store_true')
    return parser

TOY_BYTES = b'fresh157-toy-conversion-payload\n'

def fake_convert_direct(*, output, report_path, validation_dir, **kwargs):
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(TOY_BYTES)
    validation_dir.mkdir(parents=True, exist_ok=True)
    (validation_dir / 'toy-frame-check.txt').write_text('toy PartVTK check passed\n')
    report_path.write_text(json.dumps({
        'schema': 'fresh157.toy.converter-report.v1',
        'frames': 1,
        'particles': 3,
        'partvtk_validation': {'all_passed': True, 'frames_checked': 1},
        'output_sha256': hashlib.sha256(TOY_BYTES).hexdigest(),
    }, sort_keys=True) + '\n')

fake_converter._build_parser = fake_direct_parser
fake_converter.convert_direct = fake_convert_direct
sys.modules['ds_data02_direct_convert'] = fake_converter

# The real integration helper imports scientific dependencies, so the test
# supplies a toy equivalent with the same verified_copy contract.  It hashes
# only TOY_BYTES and is called by the real wrapper.
fake_copy_module = types.ModuleType('ds_data02_f3_nvme_input_audit_v1')
def toy_verified_copy(source, target, expected):
    data = Path(source).read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        raise ValueError('toy attestation mismatch')
    Path(target).write_bytes(data)
    Path(target).chmod(0o400)
    return actual
fake_copy_module.verified_copy = toy_verified_copy
sys.modules['ds_data02_f3_nvme_input_audit_v1'] = fake_copy_module

import nvme_convert_home_capped_v2 as wrapper  # noqa: E402

DiskUsage = collections.namedtuple('DiskUsage', 'total used free')
FAKE_NVME_USAGE = DiskUsage(256 * 1024**3, 0, 200 * 1024**3)


def make_argv(root: Path, staging: Path, ledger: Path, lock: Path, attempt: str):
    home = root / 'home'
    home.mkdir(parents=True, exist_ok=True)
    attempt_root = home / attempt
    attempt_root.mkdir(parents=True, exist_ok=True)
    output = attempt_root / 'trajectory.toy'
    report = attempt_root / 'conversion-report.json'
    return [
        '--staging-root', str(staging),
        '--staging-limit-bytes', str(24 * 1024**3),
        '--nvme-free-reserve-bytes', str(100 * 1024**3),
        '--home-publish-cap-bytes', str(4 * 1024**3),
        '--home-floor-bytes', str(500 * 1024**3),
        '--home-publish-headroom-bytes', str(2 * 1024**3),
        '--home-root', str(home),
        '--resource-ledger', str(ledger),
        '--resource-ledger-lock', str(lock),
        '--current-attempt-id', attempt,
        '--',
        '--data-root', str(root / 'toy-data'),
        '--generated-xml', str(root / 'toy-case.xml'),
        '--output', str(output),
        '--report', str(report),
        '--decoder', str(root / 'toy-decoder'),
        '--solver-receipt', str(root / 'toy-solver.json'),
        '--gencase-receipt', str(root / 'toy-gencase.json'),
        '--owner-metadata', str(root / 'toy-owner.json'),
    ], output, report


def prepare_case(root: Path, staging: Path, name: str):
    ledger = root / f'{name}-ledger.json'
    lock = root / f'{name}-ledger.lock'
    ledger.write_text(json.dumps({
        'schema': 'toy.resource-ledger.v1',
        'limits': {'home_min_free_bytes': 500 * 1024**3},
        'reservations': [{'id': name, 'new_storage_bytes': 0}],
    }) + '\n')
    lock.touch()
    argv, output, report = make_argv(root, staging, ledger, lock, name)
    _wrapper, _converter, merged = wrapper.parse_cli(argv)
    return merged, output, report


def assert_no_publication(output: Path, report: Path):
    for path in (output, report, output.with_suffix(output.suffix + '.partial'), report.with_suffix(report.suffix + '.partial')):
        assert not path.exists(), f'leftover publication artifact: {path}'


def run_tests():
    assert wrapper._report_bytes({'b': 2, 'a': 1}) == len(
        (json.dumps({'b': 2, 'a': 1}, indent=2, sort_keys=True) + '\n').encode('utf-8')
    )
    original_home_free = wrapper._home_free
    original_disk_usage = wrapper.shutil.disk_usage
    original_verified_copy = wrapper.verified_copy
    original_replace = wrapper.os.replace
    original_same_device = wrapper._same_device
    wrapper._home_free = lambda _path: 2 * 1024**40
    wrapper.shutil.disk_usage = lambda _path: FAKE_NVME_USAGE
    try:
        with tempfile.TemporaryDirectory(prefix='fresh157-publish-', dir='/tmp') as td, tempfile.TemporaryDirectory(prefix='fresh157-stage-', dir='/tmp') as sd:
            root = Path(td)
            staging = Path(sd)
            # Keep every toy artifact under /tmp while mocking only the
            # separate-filesystem predicate required by the production guard.
            wrapper._same_device = lambda a, b: (
                False if Path(a).resolve() == staging.resolve() or Path(b).resolve() == staging.resolve()
                else original_same_device(a, b)
            )
            merged, output, report_path = prepare_case(root, staging, 'success-attempt')
            assert merged.staging_root == staging
            assert merged.output == output
            assert merged.report == report_path
            assert merged.home_publish_cap_bytes == 4 * 1024**3
            copy_calls = []
            def counting_verified_copy(source, target, expected):
                copy_calls.append((Path(source), Path(target), expected))
                return original_verified_copy(source, target, expected)
            wrapper.verified_copy = counting_verified_copy
            report = wrapper.run(merged, staging, 24 * 1024**3)
            assert len(copy_calls) == 1
            assert output.read_bytes() == TOY_BYTES
            assert report_path.exists()
            published_bytes = (json.dumps(report, indent=2, sort_keys=True) + '\n').encode('utf-8')
            assert report_path.read_bytes() == published_bytes
            assert report['storage_protocol']['final_report_bytes'] == len(published_bytes)
            assert report['storage_protocol']['verified_published_output_sha256'] == hashlib.sha256(TOY_BYTES).hexdigest()
            assert not output.with_suffix(output.suffix + '.partial').exists()
            assert not report_path.with_suffix(report_path.suffix + '.partial').exists()
            wrapper.verified_copy = original_verified_copy

            # The real run path also rejects a toy publication over a smaller
            # cap; the reviewed production cap remains exactly 4 GiB above.
            merged, output, report_path = prepare_case(root, staging, 'cap-refusal')
            merged.home_publish_cap_bytes = 16
            try:
                wrapper.run(merged, staging, 24 * 1024**3)
            except HomePublishGuardError as exc:
                assert 'cap exceeded' in str(exc)
            else:
                raise AssertionError('real run cap refusal did not trigger')
            assert_no_publication(output, report_path)

            # RuntimeError after verified_copy must clean the Home partial.
            merged, output, report_path = prepare_case(root, staging, 'exception-after-copy')
            def fail_after_copy(source, target, expected):
                actual = original_verified_copy(source, target, expected)
                raise RuntimeError('toy failure after verified_copy')
            wrapper.verified_copy = fail_after_copy
            try:
                wrapper.run(merged, staging, 24 * 1024**3)
            except RuntimeError as exc:
                assert 'after verified_copy' in str(exc)
            else:
                raise AssertionError('exception-after-copy did not fail')
            assert_no_publication(output, report_path)
            wrapper.verified_copy = original_verified_copy

            # SystemExit(143) after the first os.replace must clean the output
            # that already moved and both partial names.
            merged, output, report_path = prepare_case(root, staging, 'system-exit-after-first-rename')
            replace_calls = []
            def exit_after_first_rename(source, target):
                original_replace(source, target)
                replace_calls.append((Path(source), Path(target)))
                if len(replace_calls) == 1:
                    raise SystemExit(143)
            wrapper.os.replace = exit_after_first_rename
            try:
                wrapper.run(merged, staging, 24 * 1024**3)
            except SystemExit as exc:
                assert exc.code == 143
            else:
                raise AssertionError('SystemExit cleanup case did not exit')
            assert len(replace_calls) == 1
            assert_no_publication(output, report_path)
    finally:
        wrapper._home_free = original_home_free
        wrapper.shutil.disk_usage = original_disk_usage
        wrapper.verified_copy = original_verified_copy
        wrapper.os.replace = original_replace
        wrapper._same_device = original_same_device
    print('fresh157 real-wrapper publish and cleanup toy tests passed')


if __name__ == '__main__':
    run_tests()
