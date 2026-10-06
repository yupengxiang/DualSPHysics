#!/usr/bin/env python3
import argparse
import json
import sys
import tempfile
import types
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from home_publish_math import HomePublishGuardError, evaluate_publish, other_reserved_storage_bytes, planned_publish_bytes
# Keep this toy test independent of the system h5py/numpy ABI.  The wrapper's
# actual producer imports are source inputs; no converter is invoked here.
fake_converter = types.ModuleType('ds_data02_direct_convert')
fake_converter.tempfile = tempfile
fake_converter.decode_frame = lambda *args, **kwargs: None
fake_converter._run_partvtk_frame = lambda *args, **kwargs: None
def forbidden_real_converter(*args, **kwargs):
    raise AssertionError('toy CLI test must not invoke the real converter')
fake_converter.convert_direct = forbidden_real_converter
def fake_direct_parser():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--generated-xml', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--decoder', type=Path, required=True)
    parser.add_argument('--partvtk', type=Path)
    parser.add_argument('--solver-receipt', type=Path, required=True)
    parser.add_argument('--gencase-receipt', type=Path, required=True)
    parser.add_argument('--owner-metadata', type=Path, required=True)
    parser.add_argument('--particle-chunk', type=int, default=65536)
    parser.add_argument('--skip-partvtk-validation', action='store_true')
    parser.add_argument('--keep-validation-csv', action='store_true')
    return parser
fake_converter._build_parser = fake_direct_parser
sys.modules['ds_data02_direct_convert'] = fake_converter
fake_copy_module = types.ModuleType('ds_data02_f3_nvme_input_audit_v1')
fake_copy_module.verified_copy = lambda *args, **kwargs: None
sys.modules['ds_data02_f3_nvme_input_audit_v1'] = fake_copy_module
from nvme_convert_home_capped_v1 import HomePublishRefusal, _check_stage_budget, _prepare_report, main as wrapper_main, parse_cli

def run_tests():
    assert planned_publish_bytes(7,3)==10
    ok=evaluate_publish(h5_bytes=7,report_bytes=3,cap_bytes=10,home_free_bytes=30,home_floor_bytes=15,other_reserved_bytes=0,headroom_bytes=2)
    assert ok['planned_publish_bytes']==10
    try: evaluate_publish(h5_bytes=8,report_bytes=3,cap_bytes=10,home_free_bytes=30,home_floor_bytes=15,other_reserved_bytes=0,headroom_bytes=2)
    except HomePublishGuardError as e: assert 'cap exceeded' in str(e)
    else: raise AssertionError('cap boundary did not reject')
    try: evaluate_publish(h5_bytes=7,report_bytes=3,cap_bytes=100,home_free_bytes=30,home_floor_bytes=15,other_reserved_bytes=12,headroom_bytes=4)
    except HomePublishGuardError as e: assert 'floor' in str(e)
    else: raise AssertionError('reservation floor boundary did not reject')
    ledger={'reservations':[{'id':'self','new_storage_bytes':32},{'id':'other','new_storage_bytes':5}]}
    assert other_reserved_storage_bytes(ledger,'self')==5
    assert other_reserved_storage_bytes(ledger,None)==37
    with tempfile.TemporaryDirectory(prefix='fresh154-toy-', dir='/tmp') as root:
        stage=Path(root)/'stage'
        stage.mkdir()
        h5=stage/'trajectory.h5'
        h5.write_bytes(b'0123456789abcdef')
        direct_report=stage/'conversion-report.json'
        direct_report.write_text(json.dumps({'output_sha256':'0'*64,'frames':1,'particles':1})+'\n')
        validation=stage/'partvtk-validation'
        validation.mkdir()
        report,total,guard=_prepare_report(
            staged_report=direct_report, output=Path('/home/jade/toy-fresh154.h5'),
            staged_h5=h5, private_validation=validation,
            cap_bytes=4096, configured_home_floor_bytes=1000,
            effective_home_floor_bytes=1000, home_headroom_bytes=1,
            other_reserved_bytes=10, home_free_bytes=100000,
            current_attempt_id='toy-attempt', current_reservation_storage_bytes=32,
            staging_limit_bytes=4096, nvme_free_reserve_bytes=0,
            staging_root=Path(root), started=0.0)
        preview=stage/'final-conversion-report.preview.json'
        assert report['storage_protocol']['final_report_bytes']==preview.stat().st_size
        assert total==h5.stat().st_size+preview.stat().st_size
        assert guard['planned_publish_bytes']==total
        try:
            _prepare_report(
                staged_report=direct_report, output=Path('/home/jade/toy-fresh154-cap.h5'),
                staged_h5=h5, private_validation=validation,
                cap_bytes=16, configured_home_floor_bytes=1000,
                effective_home_floor_bytes=1000, home_headroom_bytes=1,
                other_reserved_bytes=0, home_free_bytes=100000,
                current_attempt_id='toy-attempt', current_reservation_storage_bytes=32,
                staging_limit_bytes=4096, nvme_free_reserve_bytes=0,
                staging_root=Path(root), started=0.0)
        except HomePublishGuardError:
            pass
        else:
            raise AssertionError('private report cap boundary did not reject')
        (stage/'over-limit.bin').write_bytes(b'01234567890')
        try:
            _check_stage_budget(stage=stage, staging_root=Path(root),
                                staging_limit_bytes=10, nvme_free_reserve_bytes=0,
                                reason='toy')
        except HomePublishRefusal:
            pass
        else:
            raise AssertionError('private staging peak boundary did not reject')
    with tempfile.TemporaryDirectory(prefix='fresh155-attempt-', dir='/tmp') as attempt:
        attempt_root = Path(attempt)
        toy_output = attempt_root / 'trajectory.h5'
        toy_report = attempt_root / 'conversion-report.json'
        toy_staging = Path('/tmp/fresh155-toy-staging')
        toy_argv = [
            '--staging-root', str(toy_staging),
            '--staging-limit-bytes', '25769803776',
            '--nvme-free-reserve-bytes', '107374182400',
            '--home-publish-cap-bytes', '4294967296',
            '--home-floor-bytes', '536870912000',
            '--current-attempt-id', 'toy-cli-attempt', '--',
            '--data-root', '/tmp/toy-data',
            '--generated-xml', '/tmp/toy-case.xml',
            '--output', str(toy_output),
            '--report', str(toy_report),
            '--decoder', '/tmp/toy-decoder',
            '--partvtk', '/tmp/toy-partvtk',
            '--solver-receipt', '/tmp/toy-solver-receipt.json',
            '--gencase-receipt', '/tmp/toy-gencase-receipt.json',
            '--owner-metadata', '/tmp/toy-owner.json',
        ]
        wrapper_options, converter_options, merged = parse_cli(toy_argv)
        assert wrapper_options.staging_root == toy_staging
        assert wrapper_options.current_attempt_id == 'toy-cli-attempt'
        assert converter_options.output == toy_output
        assert converter_options.report == toy_report
        assert merged.staging_root == wrapper_options.staging_root
        assert merged.output == converter_options.output
        seen = []
        def fake_runner(config, staging_root, staging_limit_bytes):
            seen.append((config, staging_root, staging_limit_bytes))
            return {
                'frames': 1,
                'particles': 1,
                'partvtk_validation': {'all_passed': True},
                'output_sha256': '0' * 64,
            }
        assert wrapper_main(toy_argv, runner=fake_runner, install_signal_handlers=False) == 0
        assert len(seen) == 1
        config, staging_root, staging_limit_bytes = seen[0]
        assert config.current_attempt_id == 'toy-cli-attempt'
        assert config.output == toy_output
        assert config.report == toy_report
        assert config.output.parent == attempt_root and config.output.parent.exists()
        assert staging_root == toy_staging
        assert staging_limit_bytes == 25769803776
    print('fresh155 toy boundary tests passed')
if __name__=='__main__': run_tests()
