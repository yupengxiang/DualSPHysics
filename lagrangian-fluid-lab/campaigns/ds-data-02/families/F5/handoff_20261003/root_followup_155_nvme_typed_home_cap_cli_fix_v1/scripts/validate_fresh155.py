#!/usr/bin/env python3
"""Validate fresh155 source/metadata without touching science payloads."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
REQUEST = PKG / 'metadata/fresh155-successor-request-template.json'
PROVENANCE = PKG / 'metadata/fresh155-source-provenance.json'
RETIREMENT = PKG / 'metadata/retirement-plan.json'
MANIFEST = PKG / 'manifest.json'
FORBIDDEN_SUFFIXES = {'.bi4', '.obi4', '.ibi4', '.h5', '.csv', '.dat', '.vtk', '.npy', '.npz'}
SAFE_PACKAGE_SUFFIXES = {'.json', '.py', '.md'}


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
        suffix = Path(value).suffix.lower()
        check(suffix not in FORBIDDEN_SUFFIXES, f'science payload path in metadata: {where}={value}')


request = read_json(REQUEST)
provenance = read_json(PROVENANCE)
retirement = read_json(RETIREMENT)
reject_payload_strings(request)
reject_payload_strings(provenance)
reject_payload_strings(retirement)

check(request['schema'] == 'ds02.runner-request.v2.disabled-source-template', 'request schema')
check(request['package_id'] == 'F5_fresh155_nvme_typed_home_cap_cli_fix', 'request package')
check(request['source_only'] is True, 'request source_only')
check(request['disabled'] is True and request['execution_allowed'] is False, 'request disabled')
check(request['launch_owner'] == 'root' and request['kind'] == 'cpu', 'request owner/kind')
check(request['cpu_task_kind'] == 'conversion' and request['cpu_threads'] == 2, 'request CPU contract')
check(request['estimated_storage_bytes'] == 32 * 1024**3, 'reservation estimate')
check(request['attempt_id'] is None, 'template attempt remains unassigned')
guard = request['home_publish_guard']
check(guard['publish_cap_bytes'] == 4 * 1024**3, '4 GiB publish cap')
check(guard['home_floor_bytes'] == 500 * 1024**3, '500 GiB Home floor')
check(guard['home_publish_headroom_bytes'] == 2 * 1024**3, 'Home headroom')
check(guard['other_ledger_reservations_included'] is True, 'other reservations')
check(guard['current_attempt_id_must_match_one_reservation_id'] is True, 'reservation identity')
stage = request['private_nvme_staging']
check(stage['staging_limit_bytes'] == 24 * 1024**3, '24 GiB stage')
check(stage['free_reserve_bytes'] == 100 * 1024**3, '100 GiB NVMe reserve')
check(stage['separate_filesystem_required'] is True, 'separate stage filesystem')
check(stage['per_frame_decoder_floor_and_peak_checks'] is True, 'per-frame stage check')
check(stage['partvtk_frame_peak_checks'] is True, 'PartVTK stage check')
contract = request['conversion_contract']
check(contract['direct_converter'] == 'unchanged ds_data02_direct_convert.convert_direct', 'direct converter')
check(contract['decoder_and_eos'].startswith('unchanged'), 'EOS/decoder')
check(contract['partvtk_validation'].startswith('required'), 'PartVTK')
check(request['source_inputs']['science_input_files'] is None, 'science files null')
check(request['source_inputs']['science_input_sha256'] is None, 'science hashes null')
check(request['source_inputs']['provenance_file'] == 'metadata/fresh155-source-provenance.json', 'provenance path')
check(request['source_inputs']['all_hashes_are_non_science_source_or_metadata'] is True, 'source hash scope')
check(all(value is None for value in request['future_output_hashes'].values()), 'future hashes null')
check(request['downstream']['case_credit'] == 0, 'case credit')
parent_request = request['parent_fresh154']
check(parent_request['commit'] == '138b1aa176b33eb6b2b554e71a68baa78eec6b1e', 'parent commit')
check(parent_request['bytes_are_preserved'] is True, 'parent byte preservation')
cli_request = request['cli_entry_fix']
check(cli_request['wrapper_parser_and_direct_parser_remain_separate'] is True, 'CLI parser separation')
check(cli_request['run_receives_merged_namespace'] is True, 'merged namespace contract')
check(cli_request['real_converter_not_invoked_by_source_tests'] is True, 'CLI toy boundary')

check(provenance['schema'] == 'ds02.f5.fresh155.nvme-typed-home-cap-cli-fix-source-provenance.v1', 'provenance schema')
check(provenance['source_only_package'] is True and provenance['no_jobs_started'] is True, 'provenance safety')
check(provenance['package_id'] == 'F5_fresh155_nvme_typed_home_cap_cli_fix', 'provenance package')
parent_provenance = provenance['parent_fresh154']
check(parent_provenance['manifest_sha256'] == request['parent_fresh154']['manifest_sha256'], 'parent manifest binding')
check(parent_provenance['bytes_preserved'] is True, 'provenance parent bytes')
cli_provenance = provenance['cli_fix']
check(cli_provenance['run_receives_merged_namespace'] is True, 'provenance merged namespace')
check(cli_provenance['real_converter_invoked_by_source_tests'] is False, 'provenance CLI boundary')
policy = provenance['science_payload_policy']
check(policy['opened'] is False and policy['hashed'] is False and policy['copied'] is False, 'science safety')
storage = provenance['storage_contract']
check(storage['home_publish_cap_bytes'] == 4 * 1024**3, 'provenance cap')
check(storage['home_floor_bytes'] == 500 * 1024**3, 'provenance floor')
check(storage['nvme_staging_limit_bytes'] == 24 * 1024**3, 'provenance stage')
check(storage['nvme_free_reserve_bytes'] == 100 * 1024**3, 'provenance NVMe floor')
check(storage['typed_controller_estimate_bytes_unchanged'] == 32 * 1024**3, 'old estimate')
snapshot = provenance['fresh153_snapshot_preserved']
check(snapshot['home_free_over_floor_bytes'] == 26514726912, 'fresh153 margin')
check(snapshot['root854_typed_estimate_bytes'] == 32 * 1024**3, 'fresh153 estimate')
check(snapshot['observed_h5_sizes_are_diagnostic_only'] is True, 'observed size boundary')
for item in provenance['source_evidence']:
    path = Path(item['path'])
    check(path.suffix.lower() in SAFE_PACKAGE_SUFFIXES, f'unsafe source evidence: {path}')
    check(path.exists(), f'missing source evidence: {path}')
    check(sha(path) == item['sha256'], f'source evidence SHA: {path}')

wrapper = (PKG / 'scripts/nvme_convert_home_capped_v1.py').read_text()
for required in (
    'INTEGRATION_SCRIPT_ROOT', 'converter.decode_frame',
    'converter._run_partvtk_frame', '_check_stage_budget',
    'resource_ledger_lock', 'fcntl.LOCK_EX', 'verified_copy',
    'home_publish_cap_bytes', 'home_min_free_bytes', 'current_attempt_id',
    'report_partial', 'os.replace', 'DEFAULT_STAGING_LIMIT',
    'def _build_wrapper_parser', 'def _merge_cli_namespaces',
    'def parse_cli', 'def main', 'runner=run',
    'merged.staging_root', 'converter_options',
):
    check(required in wrapper, f'wrapper contract: {required}')
check("kwargs['dir'] = str(owned_path)" in wrapper, 'private decoder scratch')
check('run_partvtk=True' in wrapper, 'PartVTK cannot be skipped')
check('output_moved = True' in wrapper, 'one-sided publish cleanup')

check(retirement['schema'] == 'ds02.f5.fresh155.metadata-wait-retirement.v1', 'retirement schema')
check(retirement['source_preparation_did_not_retire_anything'] is True, 'retirement boundary')
check(retirement['controller_owner'] == 'root', 'retirement owner')
check(len(retirement['retire_only_if']) >= 4, 'retirement conditions')
check(len(retirement['do_not_retire']) >= 3, 'retirement protections')

manifest = read_json(MANIFEST)
check(manifest['schema'] == 'ds02.f5.fresh155.package-manifest.v1', 'manifest schema')
check(manifest['manifest_excludes'] == ['metadata/fresh155-validator-report.json', 'manifest.json'], 'manifest excludes')
for relative, expected in manifest['files'].items():
    path = PKG / relative
    check(path.exists() and path.suffix.lower() in SAFE_PACKAGE_SUFFIXES, f'package file: {path}')
    check(sha(path) == expected, f'package SHA: {relative}')
package_files = {
    path.relative_to(PKG).as_posix()
    for path in PKG.rglob('*')
    if path.is_file() and '__pycache__' not in path.parts
    and path.name not in {'manifest.json', 'fresh155-validator-report.json'}
}
check(package_files == set(manifest['files']), 'manifest inventory')
print(json.dumps({
    'status': 'passed',
    'package': str(PKG),
    'science_payload_opened': False,
    'science_payload_hashed': False,
    'home_cap_bytes': guard['publish_cap_bytes'],
    'home_floor_bytes': guard['home_floor_bytes'],
    'nvme_staging_limit_bytes': stage['staging_limit_bytes'],
    'metadata_successor_disabled': True,
}, indent=2, sort_keys=True))
