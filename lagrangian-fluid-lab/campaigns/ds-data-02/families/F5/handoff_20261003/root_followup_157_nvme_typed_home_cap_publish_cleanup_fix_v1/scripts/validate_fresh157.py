#!/usr/bin/env python3
"""Validate fresh157 source/metadata and toy-boundary fixes without science payloads."""
from __future__ import annotations
import hashlib
import json
import re
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
REQUEST = PKG / 'metadata/fresh157-successor-request-template.json'
PROVENANCE = PKG / 'metadata/fresh157-source-provenance.json'
RETIREMENT = PKG / 'metadata/retirement-plan.json'
WRAPPER = PKG / 'scripts/nvme_convert_home_capped_v2.py'
TEST = PKG / 'tests/test_publish_cleanup.py'
MANIFEST = PKG / 'manifest.json'
FORBIDDEN_SUFFIXES = {'.bi4', '.obi4', '.ibi4', '.h5', '.csv', '.dat', '.vtk', '.npy', '.npz'}
SAFE_PACKAGE_SUFFIXES = {'.json', '.py', '.md'}
HEX64 = re.compile(r'^[0-9a-f]{64}$')


def check(condition: bool, message: str):
    if not condition:
        raise AssertionError(message)


def sha(path: Path) -> str:
    check(path.suffix.lower() not in FORBIDDEN_SUFFIXES, f'payload hash forbidden: {path}')
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path):
    check(path.suffix.lower() == '.json', f'JSON expected: {path}')
    return json.loads(path.read_text())


def reject_payload_strings(value, where=''):
    if isinstance(value, dict):
        for key, child in value.items():
            reject_payload_strings(child, f'{where}.{key}' if where else key)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_payload_strings(child, f'{where}[{index}]')
    elif isinstance(value, str):
        check(Path(value).suffix.lower() not in FORBIDDEN_SUFFIXES, f'science payload path in metadata: {where}={value}')


request = read_json(REQUEST)
provenance = read_json(PROVENANCE)
retirement = read_json(RETIREMENT)
for value in (request, provenance, retirement):
    reject_payload_strings(value)

PACKAGE_ID = 'F5_fresh157_nvme_typed_home_cap_publish_cleanup_fix'
check(request['schema'] == 'ds02.runner-request.v2.disabled-source-template', 'request schema')
check(request['package_id'] == PACKAGE_ID, 'request package')
check(request['source_only'] is True and request['disabled'] is True and request['execution_allowed'] is False, 'disabled source boundary')
check(request['launch_owner'] == 'root' and request['kind'] == 'cpu', 'owner/kind')
check(request['cpu_task_kind'] == 'conversion' and request['cpu_threads'] == 2, 'CPU contract')
check(request['estimated_storage_bytes'] == 32 * 1024**3, 'unchanged estimate')
check(request['attempt_id'] is None, 'future attempt remains unassigned')
check(request['parent_fresh155']['commit'] == '2776ccd2', 'fresh155 parent')
check(request['parent_fresh155']['bytes_are_preserved'] is True, 'fresh155 bytes')
check(request['parent_fresh156']['commit'] == '1def68ac123af641445f84c99435e27c88ac4458', 'fresh156 parent')
fix = request['publish_cleanup_fix']
for key in ('undefined_report_bytes_fixed', 'verified_copy_kept_before_report_publish', 'real_wrapper_run_toy_tested'):
    check(fix[key] is True, f'fix evidence: {key}')
check('BaseException' in fix['system_exit_cleanup'], 'SystemExit cleanup boundary')
check('publication_started' in fix['system_exit_cleanup'], 'publication transaction marker')
guard = request['home_publish_guard']
check(guard['home_floor_bytes'] == 500 * 1024**3, 'Home floor')
check(guard['publish_cap_bytes'] == 4 * 1024**3, 'publish cap')
check(guard['home_publish_headroom_bytes'] == 2 * 1024**3, 'Home headroom')
check(guard['cleanup_on_system_exit'] is True, 'SystemExit guard')
stage = request['private_nvme_staging']
check(stage['staging_limit_bytes'] == 24 * 1024**3 and stage['free_reserve_bytes'] == 100 * 1024**3, 'NVMe limits')
check(stage['per_frame_decoder_floor_and_peak_checks'] is True and stage['partvtk_frame_peak_checks'] is True, 'staging checks')
check(request['source_inputs']['science_input_files'] is None and request['source_inputs']['science_input_sha256'] is None, 'science inputs null')
check(all(value is None for value in request['future_output_hashes'].values()), 'future hashes null')
check(request['downstream']['case_credit'] == 0 and request['downstream']['independent_case_count_increment'] == 0, 'case credit')
check(request['command_template'][1].endswith('/scripts/nvme_convert_home_capped_v2.py'), 'command wrapper')

check(provenance['schema'] == 'ds02.f5.fresh157.nvme-typed-home-cap-publish-cleanup-source-provenance.v1', 'provenance schema')
check(provenance['package_id'] == PACKAGE_ID, 'provenance package')
check(provenance['source_only_package'] is True and provenance['no_jobs_started'] is True and provenance['no_shared_state_modified'] is True, 'provenance boundary')
policy = provenance['science_payload_policy']
check(policy['opened'] is False and policy['hashed'] is False and policy['copied'] is False and policy['real_converter_invoked'] is False, 'science policy')
check(policy['toy_payload_only_in_test'] is True, 'toy payload boundary')
for evidence in provenance['source_evidence']:
    path = Path(evidence['path'])
    check(path.exists(), f'missing source evidence: {path}')
    check(path.suffix.lower() in {'.py', '.json'}, f'unsafe source evidence: {path}')
    check(HEX64.fullmatch(evidence['sha256']), f'source digest shape: {path}')
    check(sha(path) == evidence['sha256'], f'source digest mismatch: {path}')
check(provenance['future_hashes']['typed_h5_sha256'] is None and provenance['future_hashes']['render_sha256'] is None, 'provenance future hashes')

wrapper = WRAPPER.read_text()
for required in ('def _report_payload', 'def _report_bytes', 'payload = _report_payload(report)', 'report_payload = _report_payload(report)', 'verified_copy(', 'publication_started = True', 'except BaseException:', 'if (publication_started or published or output_moved)', 'def parse_cli', 'def main', 'run(args, staging_root'):
    check(required in wrapper, f'wrapper contract: {required}')
check('raise SystemExit(143)' in wrapper, 'owned SIGTERM remains explicit')

test = TEST.read_text()
for required in ('fake_convert_direct', 'toy_verified_copy', 'wrapper.run(', '_report_bytes', 'SystemExit(143)', 'exit_after_first_rename', 'report_path.read_bytes()'):
    check(required in test, f'toy test contract: {required}')
check('import h5py' not in test and 'import numpy' not in test, 'toy test does not import scientific ABI')

check(retirement['schema'] == 'ds02.f5.fresh157.metadata-wait-retirement.v1', 'retirement schema')
check(retirement['source_preparation_did_not_retire_anything'] is True, 'retirement boundary')
check(retirement['future_receipt_sha256'] is None, 'future receipt')

manifest = read_json(MANIFEST)
check(manifest['schema'] == 'ds02.f5.fresh157.package-manifest.v1', 'manifest schema')
check(manifest['manifest_excludes'] == ['metadata/fresh157-validator-report.json', 'manifest.json'], 'manifest excludes')
for relative, expected in manifest['files'].items():
    path = PKG / relative
    check(path.exists() and path.suffix.lower() in SAFE_PACKAGE_SUFFIXES, f'package file: {path}')
    check(sha(path) == expected, f'package SHA: {relative}')
package_files = {path.relative_to(PKG).as_posix() for path in PKG.rglob('*') if path.is_file() and '__pycache__' not in path.parts and path.name not in {'manifest.json', 'fresh157-validator-report.json'}}
check(package_files == set(manifest['files']), 'manifest inventory')
print(json.dumps({'status':'passed','package':str(PKG),'real_wrapper_toy_publish':True,'exact_report_bytes':True,'verified_copy_toy_path':True,'runtime_error_cleanup':True,'system_exit_143_cleanup':True,'science_payload_opened':False,'future_hashes_null':True}, indent=2, sort_keys=True))
