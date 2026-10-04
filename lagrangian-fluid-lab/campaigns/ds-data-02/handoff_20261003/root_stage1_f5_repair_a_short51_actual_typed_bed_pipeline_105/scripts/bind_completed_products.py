from __future__ import annotations

import argparse
import hashlib
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

BASE = Path(__file__).resolve().parent / 'f5_065_source_placeholder'
# When copied into fresh065/scripts, BASE is replaced by the handoff parent.
TARGET_CONDITION_SHA = '268d4ea37228fb63ef493a6e535740bb765d165d874f97804443d5e11eb3497c'
EXPECTED_FRAMES = 51
EXPECTED_PARTICLES = 214385
EXPECTED_FLUID = 40710


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError(f'JSON object required: {path}')
    return value


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def write_json(path: Path, value: dict[str, Any], force: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        raise FileExistsError(f'refusing to overwrite bound artifact: {path}; use --force')
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def replace_path_hashes(request: dict[str, Any], paths: list[Path]) -> None:
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        absolute = path.resolve()
        if str(absolute) not in seen:
            seen.add(str(absolute))
            unique.append(absolute)
    missing = [str(path) for path in unique if not path.is_file()]
    require(not missing, f'bound request has missing input files: {missing}')
    request['input_files'] = [str(path) for path in unique]
    request['input_sha256'] = {str(path): sha(path) for path in unique}


def validate_receipt(path: Path, label: str) -> dict[str, Any]:
    value = load(path)
    require(value.get('status') == 'completed', f'{label} status is not completed')
    require(value.get('returncode') == 0, f'{label} returncode is not zero')
    return value


def validate_conversion(report_path: Path, h5_path: Path, solver_receipt: Path, gencase_receipt: Path) -> tuple[dict[str, Any], str, str]:
    require(report_path.is_file(), f'conversion report missing: {report_path}')
    require(h5_path.is_file(), f'trajectory H5 missing: {h5_path}')
    report = load(report_path)
    require(report.get('schema') == 'ds-data-02.bi4-direct-conversion.v1', 'unexpected conversion schema')
    require(report.get('conversion_status') == 'completed', 'conversion is not completed')
    require(Path(str(report.get('output_hdf5', ''))).resolve() == h5_path.resolve(), 'conversion output H5 path mismatch')
    require(report.get('frames') == EXPECTED_FRAMES, 'conversion frame count is not 51')
    require(report.get('particles') == EXPECTED_PARTICLES, 'conversion particle count is not 214385')
    require(report.get('solver_dimension', {}).get('solver_dimension') == 3, 'conversion is not 3-D')
    h5_sha = sha(h5_path)
    require(report.get('output_sha256') == h5_sha, 'conversion report H5 hash does not match published H5')
    solver = validate_receipt(solver_receipt, 'actual093 short solver')
    gencase = validate_receipt(gencase_receipt, 'actual075 GenCase')
    require(Path(str(solver.get('output_root', ''))).resolve().name.endswith('native-093'), 'short receipt is not actual093')
    require(Path(str(gencase.get('output_root', ''))).resolve().name.endswith('genuine-gencase-075'), 'GenCase receipt is not actual075')
    observed = str(report.get('hash_scopes', {}).get('physical_condition_sha256', ''))
    require(len(observed) == 64 and all(ch in '0123456789abcdef' for ch in observed), 'conversion report has no observed physical hash')
    return report, h5_sha, observed


def validate_xmf(path: Path) -> str:
    require(path.is_file(), f'XMF missing: {path}')
    root = ET.parse(path).getroot()
    times = [float(node.attrib['Value']) for node in root.iter('Time')]
    require(len(times) == EXPECTED_FRAMES, f'XMF time count {len(times)} != 51')
    manifest = json.loads(path.with_name('manifest.json').read_text())
    actual = manifest['actual_time_s']
    require(times == actual and all(math.isfinite(value) for value in times), 'XMF time axis differs from recorded native H5 time')
    require(times[0] == 0 and times[-1] >= 1.0 and all(b > a for a, b in zip(times, times[1:])), 'XMF native time does not cover full short event monotonically')
    return sha(path)


def handoff_paths() -> dict[str, Path]:
    base = Path(__file__).resolve().parents[1]
    case = Path('/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_A061')
    conv = case / 'root-stage1-f5-explicit-bed-repair-a-short-event-native-typed-nvme-065'
    xmf = case / 'root-stage1-f5-explicit-bed-repair-a-short-event-native-xmf-065'
    return {
        'base': base,
        'xmf_template': base / 'xmf-binding-template.json',
        'xmf_request_template': base / 'xmf-request-template.json',
        'bed_template': base / 'bed-audit-binding-template.json',
        'bed_request_template': base / 'bed-audit-request-template.json',
        'xmf_worker': base / 'workers/export_xmf.py',
        'bed_worker': base / 'workers/bed_audit.py',
        'owner': base / 'owner-metadata.json',
        'solver_receipt': case / 'root-stage1-f5-explicit-bed-repair-a-short-event-native-093/execution-receipt.json',
        'gencase_receipt': case / 'root-stage1-f5-explicit-bed-repair-a-genuine-gencase-075/execution-receipt.json',
        'qa_receipt': case / 'root-stage1-f5-explicit-bed-repair-a-native-qa-083/execution-receipt.json',
        'qa_report': case / 'root-stage1-f5-explicit-bed-repair-a-native-qa-083/initial-qa/a061-native-initial-qa.json',
        'conversion_report': conv / 'conversion-report.json',
        'trajectory_h5': conv / 'trajectory.h5',
        'xdmf': xmf / 'case.xmf',
        'xmf_manifest': xmf / 'manifest.json',
        'runtime': Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py'),
        'strict': Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py'),
    }


def bind_xmf(paths: dict[str, Path], out_dir: Path, force: bool) -> dict[str, Any]:
    report, h5_sha, observed = validate_conversion(paths['conversion_report'], paths['trajectory_h5'], paths['solver_receipt'], paths['gencase_receipt'])
    binding = load(paths['xmf_template'])
    binding.update({
        'conversion_report': str(paths['conversion_report'].resolve()),
        'conversion_report_sha256': sha(paths['conversion_report']),
        'trajectory_h5': str(paths['trajectory_h5'].resolve()),
        'trajectory_h5_sha256': h5_sha,
        'physical_condition_sha256': observed,
        'declared_campaign_physical_condition_sha256': TARGET_CONDITION_SHA,
        'physical_condition_hash_match': observed == TARGET_CONDITION_SHA,
        'conversion_frames': report['frames'],
        'conversion_particles': report['particles'],
        'bound_status': 'root-bound-after-actual-nvme-conversion',
        'bound_by': 'fresh065/scripts/bind_completed_products.py',
    })
    binding_path = out_dir / 'xmf-binding.json'
    write_json(binding_path, binding, force)
    request = load(paths['xmf_request_template'])
    request.update({
        'physical_condition_sha256': observed,
        'declared_campaign_physical_condition_sha256': TARGET_CONDITION_SHA,
        'physical_condition_hash_match': observed == TARGET_CONDITION_SHA,
        'command': [str(Path('/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python')), str(paths['xmf_worker'].resolve()), '--binding', str(binding_path.resolve()), '--output-dir', '{attempt_root}'],
        'input_binding': str(binding_path.resolve()),
        'launch_allowed': False,
        'bound_status': 'ready_for_root_review_then_enable',
    })
    replace_path_hashes(request, [paths['xmf_worker'], binding_path, paths['owner'], paths['solver_receipt'], paths['gencase_receipt'], paths['conversion_report'], paths['trajectory_h5']])
    request_path = out_dir / 'xmf-request.json'
    write_json(request_path, request, force)
    return {'observed_physical_condition_sha256': observed, 'declared_campaign_physical_condition_sha256': TARGET_CONDITION_SHA, 'physical_condition_hash_match': observed == TARGET_CONDITION_SHA, 'xmf_binding': str(binding_path), 'xmf_request': str(request_path), 'trajectory_h5_sha256': h5_sha}


def bind_bed(paths: dict[str, Path], out_dir: Path, force: bool) -> dict[str, Any]:
    report, h5_sha, observed = validate_conversion(paths['conversion_report'], paths['trajectory_h5'], paths['solver_receipt'], paths['gencase_receipt'])
    xmf_sha = validate_xmf(paths['xdmf'])
    require(paths['xmf_manifest'].is_file(), f'XMF manifest missing: {paths["xmf_manifest"]}')
    binding = load(paths['bed_template'])
    binding.update({
        'physical_condition_sha256': observed,
        'declared_campaign_physical_condition_sha256': TARGET_CONDITION_SHA,
        'physical_condition_hash_match': observed == TARGET_CONDITION_SHA,
        'native_conversion_report': str(paths['conversion_report'].resolve()),
        'native_conversion_report_sha256': sha(paths['conversion_report']),
        'trajectory_h5': str(paths['trajectory_h5'].resolve()),
        'trajectory_h5_sha256': h5_sha,
        'xdmf': str(paths['xdmf'].resolve()),
        'xdmf_sha256': xmf_sha,
        'xmf_manifest': str(paths['xmf_manifest'].resolve()),
        'xmf_manifest_sha256': sha(paths['xmf_manifest']),
        'bound_status': 'root-bound-after-actual-nvme-conversion-and-xmf-publication',
        'bound_by': 'fresh065/scripts/bind_completed_products.py',
        'conversion_frames': report['frames'],
        'conversion_particles': report['particles'],
    })
    binding_path = out_dir / 'bed-audit-binding.json'
    write_json(binding_path, binding, force)
    request = load(paths['bed_request_template'])
    request.update({
        'physical_condition_sha256': observed,
        'declared_campaign_physical_condition_sha256': TARGET_CONDITION_SHA,
        'physical_condition_hash_match': observed == TARGET_CONDITION_SHA,
        'command': [str(Path('/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python')), str(paths['bed_worker'].resolve()), '--binding', str(binding_path.resolve()), '--trajectory-h5', str(paths['trajectory_h5'].resolve()), '--xdmf', str(paths['xdmf'].resolve()), '--output-dir', '{attempt_root}'],
        'input_binding': str(binding_path.resolve()),
        'launch_allowed': False,
        'bound_status': 'ready_for_root_review_then_enable',
    })
    replace_path_hashes(request, [paths['bed_worker'], binding_path, paths['owner'], paths['runtime'], paths['strict'], paths['gencase_receipt'], paths['qa_receipt'], paths['qa_report'], paths['solver_receipt'], paths['conversion_report'], paths['trajectory_h5'], paths['xdmf'], paths['xmf_manifest']])
    request_path = out_dir / 'bed-audit-request.json'
    write_json(request_path, request, force)
    return {'observed_physical_condition_sha256': observed, 'declared_campaign_physical_condition_sha256': TARGET_CONDITION_SHA, 'physical_condition_hash_match': observed == TARGET_CONDITION_SHA, 'bed_binding': str(binding_path), 'bed_request': str(request_path), 'trajectory_h5_sha256': h5_sha, 'xdmf_sha256': xmf_sha}


def main() -> int:
    parser = argparse.ArgumentParser(description='Bind actual F5 A061 conversion/XMF products without decoding native arrays.')
    parser.add_argument('--mode', choices=('xmf', 'bed'), required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    paths = handoff_paths()
    result = bind_xmf(paths, args.output_dir.resolve(), args.force) if args.mode == 'xmf' else bind_bed(paths, args.output_dir.resolve(), args.force)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
