#!/usr/bin/env python3
"""Build F3 fresh080 typed267 -> XMF/render source handoff.

This builder reads JSON/XML/source metadata and producer-reported digests only.
It never opens or hashes H5/BI4/CSV/VTK/scientific arrays and never launches a job.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

WT = Path('/home/jade/.codex/worktrees/ds-data-02-f3/DualSPHysics')
FAMILY = WT / 'lagrangian-fluid-lab/campaigns/ds-data-02/families/F3'
HANDOFF = FAMILY / 'handoff_20261003'
SRC078 = HANDOFF / 'root_followup_078_f3_actual_converter_scope_typed_xmf_v1'
SRC079 = HANDOFF / 'root_followup_079_f3_actual_typed267_xmf_render_v1'
OUT = HANDOFF / 'root_followup_080_f3_actual_typed267_xmf_render_v1'
INTEGRATION = Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics')
ROOT267 = INTEGRATION / 'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f3_remaining14_actual_legacy_scope_full836_typed_267'
DATA = Path('/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3')

CASES = ['0430', '0440', '0480', '0520']
BAD_SUFFIXES = {'.bi4', '.ibi4', '.csv', '.h5', '.hdf5', '.vtk', '.npy', '.npz'}


def sha256_file(path: Path) -> str:
    if path.suffix.lower() in BAD_SUFFIXES:
        raise AssertionError(f'refusing source hash of scientific payload: {path}')
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def replace_recursive(obj: Any, mapping: dict[str, str]) -> Any:
    pairs = sorted(((a, b) for a, b in mapping.items() if a and a != b), key=lambda p: len(p[0]), reverse=True)
    def repl(value: Any) -> Any:
        if isinstance(value, str):
            for old, new in pairs:
                value = value.replace(old, new)
            return value
        if isinstance(value, list):
            return [repl(v) for v in value]
        if isinstance(value, dict):
            return {repl(k): repl(v) for k, v in value.items()}
        return value
    return repl(obj)


def copy_with_fresh_rewrite(src: Path, dst: Path) -> None:
    text = src.read_text(encoding='utf-8')
    text = text.replace(str(SRC079), str(OUT)).replace('fresh079', 'fresh080')
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(text, encoding='utf-8')


def assert_metadata_path(path: Path) -> None:
    if path.suffix.lower() in BAD_SUFFIXES:
        raise AssertionError(f'raw scientific path entered metadata closure: {path}')
    if not path.is_file():
        raise AssertionError(f'missing metadata input: {path}')


def closure(paths: list[Path]) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in sorted({Path(x) for x in paths}, key=lambda x: str(x)):
        assert_metadata_path(p)
        out[str(p)] = sha256_file(p)
    return out


def find_arg(command: list[str], name: str) -> str:
    for i, token in enumerate(command):
        if token == name and i + 1 < len(command):
            return command[i + 1]
    raise AssertionError(f'command missing {name}')


def compact_native(owner: dict[str, Any]) -> dict[str, Any]:
    native = owner['native_receipt']
    quality = owner['actual_native_binding']['native_quality']
    return {
        'actual_3d': quality['actual_3d'],
        'attempt_id': native['attempt_id'],
        'dimension': quality['dimension'],
        'expected_saved_frames': quality['saved_frames'],
        'fixed_particles': quality['fixed_particles'],
        'fluid_particles': quality['fluid_particles'],
        'moving_particles': quality['moving_particles'],
        'output_root': native['output_root'],
        'receipt': native['path'],
        'receipt_sha256': native['sha256'],
        'returncode': native['returncode'],
        'status': native['status'],
        'time_window_s': quality['event_window_s'],
        'total_particles': quality['total_particles'],
        'tmax': 8.35,
        'tout': 0.01,
    }


def make_info(ay: str) -> dict[str, Any]:
    case = f'F3_STAGE1_DP006_P1000_AY{ay}'
    owner_src = SRC078 / 'owners' / f'{case}.actual-converter-scope.owner.json'
    root_req_src = ROOT267 / f'{case}-typed-request.json'
    if not owner_src.is_file() or not root_req_src.is_file():
        raise AssertionError(f'missing source owner/request for {case}')
    owner = load(owner_src)
    root_req = load(root_req_src)
    raw_root_req = root_req_src.read_bytes()
    root_req_sha = hashlib.sha256(raw_root_req).hexdigest()
    case_dir = DATA / case
    completed = []
    for rec_path in sorted(case_dir.glob('*typed*/execution-receipt.json')):
        rec = load(rec_path)
        if rec.get('status') == 'completed' and rec.get('returncode') == 0:
            completed.append((rec_path, rec))
    if len(completed) != 1:
        raise AssertionError(f'{case}: expected exactly one completed typed receipt, found {len(completed)}')
    typed_receipt_path, typed_receipt = completed[0]
    typed_root = typed_receipt_path.parent
    report_path = typed_root / 'conversion-report.json'
    if not report_path.is_file():
        raise AssertionError(f'{case}: missing completed conversion report')
    report = load(report_path)
    report_sha = sha256_file(report_path)
    receipt_sha = sha256_file(typed_receipt_path)
    if receipt_sha != typed_receipt.get('receipt_sha256', receipt_sha):
        # The runtime receipt has no self-digest field in some historical runs; the
        # source handoff stores the actual file digest below.
        pass
    if report.get('conversion_status') != 'completed' or report.get('frames') != 836 or report.get('particles') != 179208:
        raise AssertionError(f'{case}: typed report contract')
    if report.get('solver_dimension', {}).get('solver_dimension') != 3:
        raise AssertionError(f'{case}: typed report is not 3-D')
    if report.get('partvtk_validation', {}).get('all_passed') is not True:
        raise AssertionError(f'{case}: PartVTK report did not pass')
    native = owner['native_receipt']
    native_path = Path(native['path'])
    native_actual_sha = sha256_file(native_path)
    if native_actual_sha != native['sha256']:
        raise AssertionError(f'{case}: native receipt hash mismatch')
    native_doc = load(native_path)
    if native_doc.get('status') != 'completed' or native_doc.get('returncode') != 0:
        raise AssertionError(f'{case}: native receipt status')
    source_xml = Path(find_arg(root_req['command'], '--generated-xml'))
    prepared_report = Path(owner['prepared_input']['report']['path'])
    genuine = owner['actual_gencase_receipt']
    parent_qa = owner['parent_initial_qa']
    for p in (source_xml, prepared_report, Path(genuine['path']), Path(parent_qa['path'])):
        assert_metadata_path(p)
    physical = root_req['physical_case_id']
    actual_hash = owner['physical_condition_sha256']
    source_hash = owner['source_physical_condition_sha256']
    if actual_hash != report['hash_scopes']['physical_condition_sha256']:
        raise AssertionError(f'{case}: report/owner actual scope mismatch')
    if physical != report['hash_scopes']['physical_condition']['physical_case_id']:
        raise AssertionError(f'{case}: report/owner physical identity mismatch')
    return {
        'case_id': case,
        'physical_case_id': physical,
        'owner_src': owner_src,
        'owner': owner,
        'root_req_src': root_req_src,
        'root_req': root_req,
        'root_req_sha': root_req_sha,
        'typed_receipt_path': typed_receipt_path,
        'typed_receipt': typed_receipt,
        'typed_receipt_sha': receipt_sha,
        'typed_root': typed_root,
        'report_path': report_path,
        'report': report,
        'report_sha': report_sha,
        'native_path': native_path,
        'native_actual_sha': native_actual_sha,
        'source_xml': source_xml,
        'source_xml_sha': sha256_file(source_xml),
        'prepared_report': prepared_report,
        'prepared_report_sha': sha256_file(prepared_report),
        'gencase_path': Path(genuine['path']),
        'gencase_sha': genuine['sha256'],
        'parent_qa_path': Path(parent_qa['path']),
        'parent_qa_sha': parent_qa['sha256'],
        'physical_hash': actual_hash,
        'source_hash': source_hash,
        'h5_path': Path(report['output_hdf5']),
        # This is intentionally adopted from the producer report. The H5 is never read.
        'h5_sha': report['output_sha256'],
        'native': native,
        'native_doc': native_doc,
    }


def local(rel: str) -> Path:
    return OUT / rel


def main() -> None:
    if not OUT.exists():
        OUT.mkdir(parents=True)
    if not SRC078.is_dir() or not SRC079.is_dir() or not ROOT267.is_dir():
        raise SystemExit('required prior handoffs are missing')

    # Reuse the reviewed worker implementation and static runtime contracts.
    for rel in ('workers/export_xmf.py', 'workers/render_native023.py'):
        (OUT / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SRC079 / rel, OUT / rel)
    for rel_dir in ('metadata/contracts', 'metadata/root142'):
        for src in (SRC079 / rel_dir).rglob('*'):
            if src.is_file():
                copy_with_fresh_rewrite(src, OUT / rel_dir / src.relative_to(SRC079 / rel_dir))
    for rel in ('metadata/runtime-contract.json', 'metadata/lineage-policy.json'):
        copy_with_fresh_rewrite(SRC079 / rel, OUT / rel)

    infos = [make_info(ay) for ay in CASES]
    for info in infos:
        case = info['case_id']
        # Preserve the actual converter owner bytes; fresh079 did the same for fresh078.
        owner_dst = OUT / 'owners' / f'{case}.actual-converter-scope.owner.json'
        owner_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(info['owner_src'], owner_dst)
        # Preserve Root267's historical request bytes as an immutable producer record.
        root_req_dst = OUT / 'metadata/upstream/root267' / f'{case}-typed-request.json'
        root_req_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(info['root_req_src'], root_req_dst)

    # Write package metadata before deriving bound hash maps.
    provenance_cases = []
    registry_cases = []
    for info in infos:
        owner = info['owner']
        report = info['report']
        case = info['case_id']
        owner_dst = OUT / 'owners' / f'{case}.actual-converter-scope.owner.json'
        root_req_dst = OUT / 'metadata/upstream/root267' / f'{case}-typed-request.json'
        provenance_cases.append({
            'case_id': case,
            'physical_case_id': info['physical_case_id'],
            'physical_condition_sha256': info['physical_hash'],
            'source_plan_condition_sha256': info['source_hash'],
            'actual_converter_scope_schema': owner['actual_converter_physical_condition_scope']['schema'],
            'actual_converter_scope_sha256': owner['actual_converter_physical_condition_scope_sha256'],
            'root267_request': {'path': str(root_req_dst), 'sha256': info['root_req_sha']},
            'actual_typed_receipt': {'path': str(info['typed_receipt_path']), 'sha256': info['typed_receipt_sha']},
            'actual_conversion_report': {'path': str(info['report_path']), 'sha256': info['report_sha']},
            'actual_typed_attempt_id': info['typed_root'].name,
            'actual_typed_status': {'status': info['typed_receipt'].get('status'), 'returncode': info['typed_receipt'].get('returncode')},
            'actual_conversion_summary': {
                'frames': report['frames'], 'particles': report['particles'],
                'dimension': report['solver_dimension']['solver_dimension'],
                'partvtk_all_passed': report['partvtk_validation']['all_passed'],
                'producer_h5_sha256': info['h5_sha'],
                'producer_h5_sha256_source': 'conversion-report.json output_sha256; source builder did not read H5',
            },
            'actual_native_receipt': {'path': str(info['native_path']), 'sha256': info['native_actual_sha']},
            'source_agent_read_arrays': False,
            'source_agent_read_science_payloads': False,
        })
        registry_cases.append({
            'case_id': case,
            'physical_case_id': info['physical_case_id'],
            'physical_condition_sha256': info['physical_hash'],
            'source_plan_condition_sha256': info['source_hash'],
            'actual_converter_scope_schema': owner['actual_converter_physical_condition_scope']['schema'],
            'actual_converter_scope_sha256': owner['actual_converter_physical_condition_scope_sha256'],
            'actual_typed_receipt': {'path': str(info['typed_receipt_path']), 'sha256': info['typed_receipt_sha']},
            'actual_conversion_report': {'path': str(info['report_path']), 'sha256': info['report_sha']},
            'frames': info['report']['frames'], 'particles': info['report']['particles'], 'dimension': 3,
            'partvtk_all_passed': True,
            'typed_request': {'path': str(root_req_dst), 'sha256': info['root_req_sha']},
            'owner': {'path': str(owner_dst), 'sha256': sha256_file(owner_dst)},
        })
    write_json(OUT / 'metadata/actual-typed267-provenance.json', {
        'schema': 'ds02.f3.fresh080.actual-typed267-provenance.v1',
        'family_id': 'F3', 'fresh_id': 'fresh080',
        'actual_typed_scope': 'Root267 historical request lineage with completed/0 typed producer receipts',
        'all_actual_typed_completed0': True,
        'all_actual_typed_metadata_only': True,
        'all_actual_native_completed0': True,
        'source_agent_read_arrays': False,
        'source_agent_read_science_payloads': False,
        'source_agent_hashed_science_payloads': False,
        'source_agent_started_jobs': False,
        'source_agent_modified_shared_state': False,
        'cases': provenance_cases,
    })
    write_json(OUT / 'metadata/case-registry.json', {
        'schema': 'ds02.f3.fresh080.case-registry.v1',
        'family_id': 'F3', 'fresh_id': 'fresh080', 'case_count': 4,
        'independent_case_count_increment': 0, 'source_only': True,
        'scope_semantics': 'actual converter legacy-owner-scope.v0 and original source condition tuple/hash remain separate; no cross-resolution identity claim',
        'native_contract': {'dimension': 3, 'fixed_particles': 111708, 'fluid_particles': 67500, 'moving_particles': 0, 'total_particles': 179208, 'frames': 836, 'tmax': 8.35, 'tout': 0.01},
        'cases': registry_cases,
    })
    write_json(OUT / 'metadata/selection.json', {
        'schema': 'ds02.f3.fresh080.selection.v1', 'family_id': 'F3', 'fresh_id': 'fresh080',
        'included_cases': [f'F3_STAGE1_DP006_P1000_AY{ay}' for ay in CASES],
        'included_case_count': 4,
        'excluded_from_this_handoff': {
            'F3_STAGE1_DP006_P1000_AY0590': 'not included in this four-case source package; no downstream request is generated here',
            'F3_STAGE1_DP006_P1000_AY0610': 'not included in this four-case source package; no downstream request is generated here',
            'other_remaining14': 'preserved in fresh077/fresh078 evidence and outside this exact four-case downstream handoff',
        },
        'no_future_status_inference': True,
        'source_only': True,
    })

    # Static paths used by the workers. They are source/metadata only; H5/BI4/CSV never enter this list.
    def static_paths() -> list[Path]:
        paths = [
            OUT / 'metadata/actual-typed267-provenance.json', OUT / 'metadata/case-registry.json',
            OUT / 'metadata/selection.json', OUT / 'metadata/runtime-contract.json', OUT / 'metadata/lineage-policy.json',
            OUT / 'workers/export_xmf.py', OUT / 'workers/render_native023.py',
            INTEGRATION / 'lagrangian-fluid-lab/.venv/bin/python',
            INTEGRATION / 'lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py',
            INTEGRATION / 'lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py',
        ]
        paths.extend(sorted((OUT / 'metadata/contracts').glob('*.json')))
        paths.extend(sorted((OUT / 'metadata/root142').glob('*.json')))
        return paths

    def case_meta_paths(info: dict[str, Any]) -> list[Path]:
        case = info['case_id']
        return [
            OUT / 'owners' / f'{case}.actual-converter-scope.owner.json',
            OUT / 'metadata/upstream/root267' / f'{case}-typed-request.json',
            info['typed_receipt_path'], info['report_path'], info['native_path'], info['gencase_path'],
            info['source_xml'], info['prepared_report'], info['parent_qa_path'],
        ]

    # Build each XMF binding from the validated fresh079 schema, then make every
    # case/path/hash field explicit from current producer metadata.
    xmf_binding_paths: list[Path] = []
    xmf_request_paths: list[Path] = []
    render_binding_paths: list[Path] = []
    render_request_paths: list[Path] = []
    for info in infos:
        case = info['case_id']; ay = case[-4:]; physical = info['physical_case_id']; owner = info['owner']; root_req = info['root_req']
        old_case = 'F3_STAGE1_DP006_P1000_AY0340'
        old_physical = 'F3_TWOAXIS_PITCH1000_AY0340_STAGE1_FIRST24_NEW'
        template_binding = load(SRC079 / 'requests/xmf' / f'{old_physical}-fresh079-xmf-binding.json')
        template_req = load(SRC079 / 'requests/xmf' / f'{old_physical}-fresh079-normal-xmf-request.json')
        template_render_binding = load(SRC079 / 'requests/render' / f'{old_physical}-fresh079-render-binding.json')
        template_render_req = load(SRC079 / 'requests/render' / f'{old_physical}-fresh079-native023-render-request.json')
        owner_dst = OUT / 'owners' / f'{case}.actual-converter-scope.owner.json'
        root_req_dst = OUT / 'metadata/upstream/root267' / f'{case}-typed-request.json'
        owner_sha = sha256_file(owner_dst)
        # Build a target-aware string map from template provenance to target provenance.
        old_owner = SRC079 / 'owners' / f'{old_case}.actual-converter-scope.owner.json'
        old_root_req = SRC079 / 'metadata/upstream' / f'{old_case}-typed-request.json'
        old_xmf_binding_path = SRC079 / 'requests/xmf' / f'{old_physical}-fresh079-xmf-binding.json'
        old_xmf_req_path = SRC079 / 'requests/xmf' / f'{old_physical}-fresh079-normal-xmf-request.json'
        old_render_binding_path = SRC079 / 'requests/render' / f'{old_physical}-fresh079-render-binding.json'
        old_render_req_path = SRC079 / 'requests/render' / f'{old_physical}-fresh079-native023-render-request.json'
        old_info = make_info('0430')
        mapping = {
            str(SRC079): str(OUT), 'fresh079': 'fresh080',
            old_case: case, old_physical: physical,
            old_info['physical_hash']: info['physical_hash'], old_info['source_hash']: info['source_hash'],
            str(old_info['native_path']): str(info['native_path']), old_info['native']['attempt_id']: info['native']['attempt_id'],
            old_info['native']['sha256']: info['native_actual_sha'],
            str(old_info['typed_receipt_path']): str(info['typed_receipt_path']), old_info['typed_receipt_sha']: info['typed_receipt_sha'],
            str(old_info['report_path']): str(info['report_path']), old_info['report_sha']: info['report_sha'],
            str(old_info['h5_path']): str(info['h5_path']), old_info['h5_sha']: info['h5_sha'],
            str(old_info['source_xml']): str(info['source_xml']), old_info['source_xml_sha']: info['source_xml_sha'],
            str(old_info['prepared_report']): str(info['prepared_report']), old_info['prepared_report_sha']: info['prepared_report_sha'],
            str(old_info['gencase_path']): str(info['gencase_path']), old_info['gencase_sha']: info['gencase_sha'],
            str(old_info['parent_qa_path']): str(info['parent_qa_path']), old_info['parent_qa_sha']: info['parent_qa_sha'],
            str(old_owner): str(owner_dst), sha256_file(old_owner): owner_sha,
            str(old_root_req): str(root_req_dst), sha256_file(old_root_req): info['root_req_sha'],
            str(old_xmf_binding_path): str(OUT / 'requests/xmf' / f'{physical}-fresh080-xmf-binding.json'),
            str(old_xmf_req_path): str(OUT / 'requests/xmf' / f'{physical}-fresh080-normal-xmf-request.json'),
            str(old_render_binding_path): str(OUT / 'requests/render' / f'{physical}-fresh080-render-binding.json'),
            str(old_render_req_path): str(OUT / 'requests/render' / f'{physical}-fresh080-native023-render-request.json'),
        }
        binding = replace_recursive(template_binding, mapping)
        binding.update({
            'schema': 'ds02.f3.fresh080.actual-typed267-xmf-binding.v1', 'fresh_id': 'fresh080',
            'case_id': case, 'physical_case_id': physical,
            'actual_converter_physical_condition_scope': copy.deepcopy(owner['actual_converter_physical_condition_scope']),
            'actual_converter_physical_condition_scope_sha256': info['physical_hash'],
            'physical_condition_sha256': info['physical_hash'],
            'source_plan_condition_sha256': info['source_hash'],
            'source_physical_condition_sha256': info['source_hash'],
            'source_parameter_tuple': copy.deepcopy(root_req['source_parameter_tuple']),
            'source_canonical_physical_binding': copy.deepcopy(root_req.get('source_canonical_physical_binding')),
            'owner_metadata': {'path': str(owner_dst), 'sha256': owner_sha},
            'native_receipt': str(info['native_path']), 'typed_receipt': str(info['typed_receipt_path']),
            'conversion_report': str(info['report_path']), 'trajectory_h5': str(info['h5_path']),
            'trajectory_h5_sha256': info['h5_sha'], 'producer_payload_sha256': info['h5_sha'],
            'producer_payload_hash_source': 'actual conversion-report.json output_sha256; source agent did not open or hash H5',
            'typed_metadata': {
                'receipt_sha256': info['typed_receipt_sha'], 'conversion_report_sha256': info['report_sha'],
                'trajectory_h5_sha256': info['h5_sha'], 'trajectory_h5_sha256_source': 'producer report',
                'conversion_status': info['report']['conversion_status'],
            },
            'n3_vector_spec': replace_recursive(binding['n3_vector_spec'], {str(SRC079): str(OUT), 'fresh079': 'fresh080'}),
            'renderer_contract': replace_recursive(binding['renderer_contract'], {str(SRC079): str(OUT), 'fresh079': 'fresh080'}),
            'owner_and_input_lineage': {
                'owner': {'path': str(owner_dst), 'sha256': owner_sha},
                'root267_typed_request': {'path': str(root_req_dst), 'sha256': info['root_req_sha']},
                'typed_receipt': {'path': str(info['typed_receipt_path']), 'sha256': info['typed_receipt_sha']},
                'conversion_report': {'path': str(info['report_path']), 'sha256': info['report_sha']},
                'native_receipt': {'path': str(info['native_path']), 'sha256': info['native_actual_sha']},
                'genuine_gencase_receipt': {'path': str(info['gencase_path']), 'sha256': info['gencase_sha']},
                'generated_xml': {'path': str(info['source_xml']), 'sha256': info['source_xml_sha']},
                'prepared_input_report': {'path': str(info['prepared_report']), 'sha256': info['prepared_report_sha']},
                'parent_initial_qa': {'path': str(info['parent_qa_path']), 'sha256': info['parent_qa_sha']},
            },
            'future_hashes_null': True, 'disabled': True, 'execution_allowed': False, 'launch_allowed': False,
            'arrays_read': False, 'jobs_started': False, 'shared_state_modified': False,
            'source_only': True, 'independent_case_count_increment': 0,
            'production_approval': 'none', 'q_n': 'not_granted', 'numerical_precision_status': 'not_accepted',
        })
        binding['n3_vector_spec']['path'] = str(OUT / 'metadata/contracts/n3-vector-spec.json')
        binding['n3_vector_spec']['sha256'] = sha256_file(OUT / 'metadata/contracts/n3-vector-spec.json')
        binding['renderer_contract']['renderer_source'] = str(INTEGRATION / 'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_native_renderer_proxy_lifetime_diagnostic_023/render.py')
        # Bound metadata excludes all raw science; the producer H5 digest is kept separately.
        meta_paths = static_paths() + case_meta_paths(info)
        binding['bound_metadata_sha256'] = closure(meta_paths)
        xmf_binding_path = OUT / 'requests/xmf' / f'{physical}-fresh080-xmf-binding.json'
        write_json(xmf_binding_path, binding)
        xmf_binding_sha = sha256_file(xmf_binding_path)
        xmf_binding_paths.append(xmf_binding_path)

        req = replace_recursive(template_req, mapping)
        req.update({
            'schema': 'ds02.runner-request.v2', 'fresh_id': 'fresh080', 'case_id': case, 'physical_case_id': physical,
            'attempt_id': f'root-stage1-f3-ay{ay}-full836-xmf-080',
            'binding': {'path': str(xmf_binding_path), 'sha256': xmf_binding_sha},
            'typed_request': {'path': str(root_req_dst), 'sha256': info['root_req_sha']},
            'owner_metadata': {'path': str(owner_dst), 'sha256': owner_sha},
            'physical_condition_sha256': info['physical_hash'], 'actual_converter_physical_condition_scope_sha256': info['physical_hash'],
            'source_plan_condition_sha256': info['source_hash'], 'source_physical_condition_sha256': info['source_hash'],
            'source_parameter_tuple': copy.deepcopy(root_req['source_parameter_tuple']),
            'source_only': True, 'disabled': True, 'execution_allowed': False, 'launch_allowed': False,
            'launch_owner': 'root', 'arrays_read': False, 'jobs_started': False, 'shared_state_modified': False,
            'request_status': 'disabled_pending_root_review_actual_typed_bound',
            'status': 'source_only_disabled_actual_typed_bound_xmf_future',
            'claim': 'Disabled XMF sidecar request only; actual typed producer is completed/0, future XMF/visual outputs remain null.',
            'native_receipt': str(info['native_path']) if 'native_receipt' not in req else req.get('native_receipt'),
            'actual_native_prerequisite': compact_native(owner),
            'typed_prerequisites': {
                'receipt': {'path': str(info['typed_receipt_path']), 'sha256': info['typed_receipt_sha'], 'status': 'completed', 'returncode': 0},
                'conversion_report': {'path': str(info['report_path']), 'sha256': info['report_sha'], 'status': 'completed'},
                'trajectory_h5': {'path': str(info['h5_path']), 'sha256': info['h5_sha'], 'hash_source': 'producer conversion report; source agent did not read H5'},
            },
            'n3_vector_spec': binding['n3_vector_spec'], 'renderer_contract': binding['renderer_contract'],
            'xmf_shape_contract': binding['xmf_shape_contract'],
            'worker_contract_preflight': {
                'contract_path': str(OUT / 'metadata/contracts/xmf-worker-contract.json'),
                'contract_sha256': sha256_file(OUT / 'metadata/contracts/xmf-worker-contract.json'),
                'passed': True, 'producer_scope_schema': 'legacy-owner-scope.v0',
                'raw_payloads_in_source_hash_closure': False, 'safe_input_closure': True,
            },
            'command': [str(INTEGRATION / 'lagrangian-fluid-lab/.venv/bin/python'), str(OUT / 'workers/export_xmf.py'), '--binding', str(xmf_binding_path), '--output-dir', '{attempt_root}/xdmf'],
            'input_files': [], 'input_sha256': {},
            'future_outputs': {'execution_receipt': '{attempt_root}/execution-receipt.json', 'execution_receipt_sha256': None, 'manifest': '{attempt_root}/xdmf/manifest.json', 'manifest_sha256': None, 'visual_decision': None, 'xdmf': '{attempt_root}/xdmf/case.xmf', 'xdmf_sha256': None},
        })
        # The request input closure includes only source/metadata and the local binding.
        req_paths = static_paths() + case_meta_paths(info) + [xmf_binding_path]
        req['input_sha256'] = closure(req_paths)
        req['input_files'] = sorted(req['input_sha256'])
        req_path = OUT / 'requests/xmf' / f'{physical}-fresh080-normal-xmf-request.json'
        write_json(req_path, req)
        xmf_request_paths.append(req_path)

        render_binding = replace_recursive(template_render_binding, mapping)
        render_binding.update({
            'schema': 'ds02.f3.fresh080.actual-typed267-root023-render-binding.v1', 'fresh_id': 'fresh080',
            'case_id': case, 'physical_case_id': physical,
            'physical_condition_sha256': info['physical_hash'], 'actual_converter_physical_condition_scope_sha256': info['physical_hash'],
            'source_physical_condition_sha256': info['source_hash'], 'producer_payload_sha256': info['h5_sha'],
            'trajectory_h5': str(info['h5_path']), 'trajectory_h5_sha256': info['h5_sha'],
            'native_receipt': str(info['native_path']),
            'typed_receipt': str(info['typed_receipt_path']), 'conversion_report': str(info['report_path']),
            'owner_metadata': {'path': str(owner_dst), 'sha256': owner_sha},
            'xmf_binding': {'path': str(xmf_binding_path), 'sha256': xmf_binding_sha},
            'normal_xmf_request': {'path': str(req_path), 'sha256': sha256_file(req_path)},
            'typed_request': {'path': str(root_req_dst), 'sha256': info['root_req_sha']},
            'n3_vector_spec': binding['n3_vector_spec'], 'renderer_contract': binding['renderer_contract'],
            'source_only': True, 'arrays_read': False, 'jobs_started': False, 'shared_state_modified': False,
            'disabled': True, 'execution_allowed': False, 'launch_allowed': False,
            'future_hashes_null': True, 'independent_case_count_increment': 0,
            'production_approval': 'none', 'q_n': 'not_granted', 'numerical_precision_status': 'not_accepted',
        })
        render_binding['n3_vector_spec']['path'] = str(OUT / 'metadata/contracts/n3-vector-spec.json')
        render_binding['n3_vector_spec']['sha256'] = sha256_file(OUT / 'metadata/contracts/n3-vector-spec.json')
        render_binding['bound_metadata_sha256'] = closure(static_paths() + case_meta_paths(info) + [xmf_binding_path, req_path])
        render_binding_path = OUT / 'requests/render' / f'{physical}-fresh080-render-binding.json'
        write_json(render_binding_path, render_binding)
        render_binding_sha = sha256_file(render_binding_path)
        render_binding_paths.append(render_binding_path)

        render_req = replace_recursive(template_render_req, mapping)
        render_req.update({
            'schema': 'ds02.runner-request.v2', 'fresh_id': 'fresh080', 'case_id': case, 'physical_case_id': physical,
            'attempt_id': f'root-stage1-f3-ay{ay}-full836-native023-render-080',
            'render_binding': {'path': str(render_binding_path), 'sha256': render_binding_sha},
            'xmf_binding': {'path': str(xmf_binding_path), 'sha256': xmf_binding_sha},
            'depends_on_normal_xmf_request': str(req_path),
            'depends_on_normal_xmf_request_sha256': sha256_file(req_path),
            'typed_request': {'path': str(root_req_dst), 'sha256': info['root_req_sha']},
            'owner_metadata': {'path': str(owner_dst), 'sha256': owner_sha},
            'physical_condition_sha256': info['physical_hash'], 'actual_converter_physical_condition_scope_sha256': info['physical_hash'],
            'source_physical_condition_sha256': info['source_hash'], 'producer_payload_sha256': info['h5_sha'],
            'trajectory_h5': str(info['h5_path']), 'trajectory_h5_sha256': info['h5_sha'],
            'native_receipt': str(info['native_path']), 'typed_receipt': str(info['typed_receipt_path']), 'conversion_report': str(info['report_path']),
            'n3_vector_spec': binding['n3_vector_spec'], 'renderer_contract': binding['renderer_contract'],
            'source_only': True, 'arrays_read': False, 'jobs_started': False, 'shared_state_modified': False,
            'disabled': True, 'execution_allowed': False, 'launch_allowed': False, 'launch_owner': 'root',
            'request_status': 'disabled_pending_root_review_actual_xmf_future',
            'status': 'source_only_disabled_root023_render_future',
            'command': [
                '/usr/bin/env', 'VTK_SMP_MAX_THREADS=2', 'LP_NUM_THREADS=2', 'LIBGL_ALWAYS_SOFTWARE=1',
                'MESA_LOADER_DRIVER_OVERRIDE=llvmpipe', '__EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/50_mesa.json',
                'VTK_DEFAULT_OPENGL_WINDOW=vtkEGLRenderWindow', 'QT_QPA_PLATFORM=offscreen', 'OMP_NUM_THREADS=2',
                str(Path('/home/jade/ParaView-6.1.1-MPI-Linux-Python3.12-x86_64/bin/pvpython')),
                '--force-offscreen-rendering', str(OUT / 'workers/render_native023.py'), '--manifest', '{normal_attempt_root}/xdmf/manifest.json', '--output-dir', '{attempt_root}/render'
            ],
            'input_files': [], 'input_sha256': {},
            'future_outputs': {
                'contact_pages': '{attempt_root}/render/contact-pages', 'contact_pages_sha256': None,
                'execution_receipt': '{attempt_root}/execution-receipt.json', 'execution_receipt_sha256': None,
                'full_saved_animation': '{attempt_root}/render/full_saved_animation.gif', 'full_saved_animation_sha256': None,
                'output_root': '{attempt_root}/render', 'pvsm': '{attempt_root}/render/case.pvsm', 'pvsm_sha256': None,
                'render_manifest': '{attempt_root}/render/render-manifest.json', 'render_manifest_sha256': None,
                'render_report': '{attempt_root}/render/render-report.json', 'render_report_sha256': None,
                'visual_decision': None,
            },
        })
        render_req_paths = static_paths() + case_meta_paths(info) + [xmf_binding_path, req_path, render_binding_path]
        render_req['input_sha256'] = closure(render_req_paths)
        render_req['input_files'] = sorted(render_req['input_sha256'])
        render_req_path = OUT / 'requests/render' / f'{physical}-fresh080-native023-render-request.json'
        write_json(render_req_path, render_req)
        render_request_paths.append(render_req_path)

    write_json(OUT / 'requests/xmf-bindings.json', {
        'schema': 'ds02.f3.fresh080.xmf-bindings.v1', 'family_id': 'F3', 'fresh_id': 'fresh080',
        'case_count': 4, 'source_only': True, 'all_requests_disabled': True,
        'bindings': [{'case_id': i['case_id'], 'physical_case_id': i['physical_case_id'], 'binding': str(p), 'sha256': sha256_file(p)} for i, p in zip(infos, xmf_binding_paths)],
    })
    write_json(OUT / 'requests/render-bindings.json', {
        'schema': 'ds02.f3.fresh080.render-bindings.v1', 'family_id': 'F3', 'fresh_id': 'fresh080',
        'case_count': 4, 'source_only': True, 'all_requests_disabled': True,
        'bindings': [{'case_id': i['case_id'], 'physical_case_id': i['physical_case_id'], 'binding': str(p), 'sha256': sha256_file(p)} for i, p in zip(infos, render_binding_paths)],
    })

    # Package README states exactly what is actual and what remains future.
    write_text(OUT / 'README.md', '''# F3 fresh080 actual Root267 typed267 to XMF/render handoff

This source-only package binds four actual completed/0 typed producer receipts for AY0430, AY0440, AY0480, and AY0520. Each producer report records 836 frames, 179208 particles, genuine 3-D metadata, and `partvtk_validation.all_passed=true`. The producer H5 digest is adopted from each completed conversion report; this builder did not open or hash H5, BI4, CSV, VTK, or numerical arrays.

Each case preserves the original Root267 request JSON as historical producer metadata and keeps the actual converter scope as `legacy-owner-scope.v0`. The source physical parameter tuple/hash and actual converter scope/hash remain separate; no cross-resolution physical identity, Q-N, precision, production, or visual acceptance is granted.

Each disabled XMF request uses the reviewed exporter worker, dynamic N3 velocity contract (`shape[1:] -> 179208 3`), actual typed receipt/report/native receipt, and safe metadata-only input closure. Each disabled Root023 render request uses a separate `{attempt_root}/render` directory, depends on the future XMF child, preserves all 836 frames/native fields, and requests automatic native bounds. Future XMF, render, visual, Q-N, and precision outputs remain null/ungranted.

AY0590 and AY0610 are intentionally outside this exact four-case handoff; no downstream requests for them are generated here. Original prior handoff evidence remains unchanged. No solver, conversion, XMF, render, registry, ledger, or shared-state operation was performed by this package.
''')

    # Copy this builder and the validator after all package paths exist.
    shutil.copy2(Path(__file__), OUT / 'build_fresh080.py')
    validator = OUT / 'validate_source_contract.py'
    write_text(validator, VALIDATOR)

    # Manifest is written last so its file list includes all source package content except itself.
    package_files = []
    for p in sorted(OUT.rglob('*')):
        if not p.is_file() or p == OUT / 'manifest.json':
            continue
        package_files.append({'path': str(p.relative_to(OUT)), 'bytes': p.stat().st_size, 'sha256': sha256_file(p)})
    write_json(OUT / 'manifest.json', {
        'schema': 'ds02.f3.fresh080.manifest.v1', 'family_id': 'F3', 'fresh_id': 'fresh080',
        'case_count': 4, 'included_cases': [i['case_id'] for i in infos],
        'source_only': True, 'execution_allowed': False, 'jobs_started': False, 'arrays_read': False,
        'scientific_payloads_copied': False, 'scientific_payloads_hashed_by_source_builder': False,
        'shared_state_modified': False, 'all_xmf_requests_disabled': True, 'all_render_requests_disabled': True,
        'independent_case_count_increment': 0,
        'dependency_graph': 'Root267 actual typed completed/0 -> disabled XMF -> disabled Root023 render',
        'producer_h5_digest_policy': 'adopt report output_sha256; source builder did not read H5',
        'files': package_files,
    })
    print(json.dumps({'status': 'built', 'package': str(OUT), 'cases': [i['case_id'] for i in infos], 'files': len(package_files)}, indent=2))


VALIDATOR = r'''#!/usr/bin/env python3
"""Validate fresh080 source contract without opening scientific payloads."""
from __future__ import annotations
import ast, hashlib, json
from pathlib import Path
HERE = Path(__file__).resolve().parent
BAD = {'.bi4','.ibi4','.csv','.h5','.hdf5','.vtk','.npy','.npz'}
CASES = ['0430','0440','0480','0520']
def sha(p: Path) -> str:
    if p.suffix.lower() in BAD: raise AssertionError('scientific payload in source validator: '+str(p))
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()
def load(p): return json.loads(Path(p).read_text(encoding='utf-8'))
def check(c,m):
    if not c: raise AssertionError(m)
def closure(d,label,allow_future=False):
    files=d.get('input_files'); hashes=d.get('input_sha256')
    check(isinstance(files,list) and isinstance(hashes,dict),label+': closure types')
    check(set(files)==set(hashes),label+': closure key mismatch')
    for text in files:
        p=Path(text); check(p.suffix.lower() not in BAD,label+': raw payload '+text)
        check(p.is_file(),label+': missing '+text); check(sha(p)==hashes[text],label+': hash '+text)
def future_null(d,label):
    for k,v in d.get('future_outputs',{}).items():
        if k.endswith('_sha256') or k in {'visual_decision'}: check(v is None,label+': future '+k)
def main():
    files=[p for p in HERE.rglob('*') if p.is_file()]
    check(not any(p.suffix.lower() in BAD for p in files),'scientific payload copied')
    for p in files:
        if p.suffix=='.json': load(p)
        elif p.suffix=='.py': ast.parse(p.read_text(encoding='utf-8'))
    m=load(HERE/'manifest.json')
    check(m['fresh_id']=='fresh080' and m['family_id']=='F3' and m['case_count']==4,'manifest')
    check(m['execution_allowed'] is False and m['jobs_started'] is False and m['arrays_read'] is False,'side effects')
    check(m['all_xmf_requests_disabled'] and m['all_render_requests_disabled'],'disabled')
    check(not any('fresh079' in p.read_text(errors='ignore') for p in files if p.suffix == '.json'),'stale fresh079 runtime JSON literal')
    reg=load(HERE/'metadata/case-registry.json'); check(reg['case_count']==4,'registry count')
    prov=load(HERE/'metadata/actual-typed267-provenance.json'); check(prov['all_actual_typed_completed0'] is True,'provenance completed')
    cases={x['case_id']:x for x in reg['cases']}; check(len(cases)==4,'case identities')
    for ay in CASES:
        case='F3_STAGE1_DP006_P1000_AY'+ay; row=cases[case]
        owner=load(HERE/'owners'/f'{case}.actual-converter-scope.owner.json')
        rootreq=load(HERE/'metadata/upstream/root267'/f'{case}-typed-request.json')
        tpath=Path(row['actual_typed_receipt']['path']); rpath=Path(row['actual_conversion_report']['path'])
        tr=load(tpath); rp=load(rpath)
        check(tr['status']=='completed' and tr['returncode']==0,case+': typed status')
        check(rp['conversion_status']=='completed' and rp['frames']==836 and rp['particles']==179208,case+': report')
        check(rp['solver_dimension']['solver_dimension']==3 and rp['partvtk_validation']['all_passed'] is True,case+': typed contract')
        check(owner['actual_converter_physical_condition_scope']['schema']=='legacy-owner-scope.v0',case+': actual scope')
        check(owner['physical_condition_sha256']!=owner['source_physical_condition_sha256'],case+': source/actual collision')
        check(rootreq['case_id']==case and rootreq['physical_condition_sha256']==owner['physical_condition_sha256'],case+': root267 identity')
        physical=row['physical_case_id']
        xb=load(HERE/'requests/xmf'/f'{physical}-fresh080-xmf-binding.json')
        xr=load(HERE/'requests/xmf'/f'{physical}-fresh080-normal-xmf-request.json')
        rb=load(HERE/'requests/render'/f'{physical}-fresh080-render-binding.json')
        rr=load(HERE/'requests/render'/f'{physical}-fresh080-native023-render-request.json')
        check(xb['producer_scope_schema']=='legacy-owner-scope.v0' and xb['physical_condition_sha256']==owner['physical_condition_sha256'],case+': xmf scope')
        check(xb['source_plan_condition_sha256']==owner['source_physical_condition_sha256'],case+': source scope')
        check(xb['trajectory_h5_sha256']==rp['output_sha256'],case+': producer H5 provenance')
        check(xb['future_hashes_null'] is True and xb['future_normal_xmf']['xdmf_sha256'] is None,case+': future XMF')
        for d,label in ((xr,'xmf request'),(rr,'render request')):
            check(d['disabled'] is True and d['execution_allowed'] is False and d['launch_allowed'] is False,case+': '+label+' disabled')
            closure(d,case+': '+label); future_null(d,case+': '+label)
        check(xr['command'][-1]=='{attempt_root}/xdmf',case+': xmf output')
        check(rr['command'][-1]=='{attempt_root}/render' and '{normal_attempt_root}/xdmf/manifest.json' in rr['command'],case+': render output')
        check(rb['future_xdmf']['sha256'] is None and rb['future_manifest']['sha256'] is None,case+': render future')
        check(rb['xmf_binding']['path']==xr['binding']['path'],case+': render/xmf binding')
        check('producer_scope_schema' in xb and 'producer_scope_schema' in rb,case+': literal scope field')
        for path,digest in xb['bound_metadata_sha256'].items():
            p=Path(path); check(p.suffix.lower() not in BAD,case+': xmf raw closure'); check(p.is_file() and sha(p)==digest,case+': xmf bound metadata')
        for path,digest in rb['bound_metadata_sha256'].items():
            p=Path(path); check(p.suffix.lower() not in BAD,case+': render raw closure'); check(p.is_file() and sha(p)==digest,case+': render bound metadata')
    export=(HERE/'workers/export_xmf.py').read_text(); render=(HERE/'workers/render_native023.py').read_text()
    for token in ('producer_scope_schema','trajectory_h5','output_hdf5','partvtk_validation','xmf_shape_contract'):
        check(token in export,'export worker contract '+token)
    for token in ('load_manifest','camera_bounds','all_frames_rendered','source_h5_sha256'):
        check(token in render,'render worker contract '+token)
    print(json.dumps({'status':'pass','fresh_id':'fresh080','family_id':'F3','cases':4,'actual_typed_completed0':True,'xmf_disabled':True,'render_disabled':True,'arrays_opened':False,'jobs_started':False},indent=2))
if __name__=='__main__': main()
'''

if __name__ == '__main__':
    main()
